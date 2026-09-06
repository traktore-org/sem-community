"""BatteryControlAdapter protocol — battery's only command contract.

Every brand-specific service call SEM makes for batteries flows
through one method on this protocol. The actuator
(:func:`actuate_battery`) says ``await adapter.command_force_charge(...)``;
the adapter dispatches to the brand-specific HA service.

Pre-v1.7.0 the battery command surface was split across:

- the deleted ``battery_protection.py`` (#624) —
  discharge limiting via ``number.set_value``
- ``battery_adapters/force_charge.py`` (brand force-charge impls
  + brand subclasses) — forced charge via brand services

This protocol unifies both axes. New brand support: subclass
``BatteryControlAdapter``, implement the four ``command_*`` methods,
register in ``adapter_for()``.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

from ..charger_types import BatteryIntent

_LOGGER = logging.getLogger(__name__)


class BatteryControlAdapter(ABC):
    """One adapter per battery brand. Mirrors
    :class:`ChargerAdapter` on the EV side.

    Each method maps 1:1 to a :class:`BatteryIntent`:

        NORMAL              → command_normal()
        LIMIT_DISCHARGE     → command_limit_discharge(watts)
        FORCE_CHARGE        → command_force_charge(target_soc, power_w, duration_min)
        STOP_FORCE_CHARGE   → command_stop_force_charge()

    The actuator never branches on brand; the adapter does.
    """

    #: (#840) Consecutive write refusals before the capability is withdrawn.
    #: Three is the charger side's number and the same reasoning: enough that a
    #: transient modbus stumble is not mistaken for a permanent limitation,
    #: few enough that a device which simply cannot do it is not asked all day.
    FORCE_DISCHARGE_FAILURE_LIMIT: int = 3

    #: (#840) How long to wait between silent probes once the capability has
    #: been withdrawn. Ten minutes turns @RienduPre's 360 failed writes an hour
    #: into six, none of them logged — while still letting a device that
    #: recovers do so without the user having to restart SEM to find out.
    FORCE_DISCHARGE_RETRY_S: float = 600.0

    @classmethod
    def expected_operating_modes(cls):
        """(#845) The inverter operating-policy states SEM's model assumes,
        or ``None`` when this brand has no known expectation (the watch then
        publishes the mode and never judges it). Observe-only: nothing in
        SEM may ever WRITE a policy selector — that boundary is the user's."""
        return None

    #: (#915) Read-back after a control write. The generic adapter — the one
    #: a roster proposal lands on — implements it; brands with their own
    #: read-back (Deye) or none report "nothing pending" and are unchanged.
    write_not_taken_strikes: int = 0
    last_unverified_entity: str = ""
    last_unverified_wanted: str = ""
    last_unverified_seen: str = ""

    # ── (#915) did the write TAKE? ────────────────────────────────────
    # A declared key says what a register is CALLED; it cannot say whether
    # the register accepts a write, expires it after sixty minutes, or is a
    # global setting the vendor says to leave alone (@Azlinon named four such
    # on EG4). That answer only exists after the first write — so the write
    # is recorded here and judged on the NEXT cycle, non-blocking, in the
    # entity's own unit. Not error handling: a register that ignores a write
    # raises nothing (#824's lesson, from the other side of the wire).
    _WRITE_GRACE_S: float = 8.0
    _WRITE_TOLERANCE_NATIVE: float = 1.0
    #: (06.09 audit) A clock is the wrong witness. Huawei's own adapter
    #: documents that the HA entity shows the STALE commanded value until
    #: huawei_solar next polls it (30-60 s) — longer than any fixed grace,
    #: so a correct write would have been judged "not reflected" and three
    #: changed writes would have raised a Repair on a working battery. The
    #: verdict therefore waits until the entity has been REPORTED since the
    #: write (HA's ``last_reported`` / ``last_updated``), and only gives up
    #: on an integration that stays silent this long — which is its own
    #: fault, and the sensor-unavailable Repair's business, not this one's.
    _WRITE_REPORT_WAIT_S: float = 180.0

    def _note_pending_write(self, entity_id: str, watts: float) -> None:
        import time as _time
        pending = getattr(self, "_pending_write", None)
        # A write already waiting to be judged is not re-armed by an
        # identical one: re-noting reset the grace every cycle and the
        # verdict never came (06.09 audit).
        if (pending and pending[0] == entity_id
                and abs(pending[1] - float(watts)) < 1e-6):
            return
        # monotonic for the grace, wall-clock to compare with HA's
        # ``last_reported`` (a datetime); both taken at the same instant
        self._pending_write = (entity_id, float(watts), _time.monotonic(),
                               _time.time())

    def verify_pending_write(self):
        import time as _time
        pending = getattr(self, "_pending_write", None)
        if not pending:
            return None
        entity_id, watts, at = pending[0], pending[1], pending[2]
        wrote_wall = pending[3] if len(pending) > 3 else None
        elapsed = _time.monotonic() - at
        if elapsed < self._WRITE_GRACE_S:
            return None          # not yet judged; integrations poll
        from ..units import power_state_to_watts, power_unit_scale
        st = self._hass.states.get(entity_id)
        # Has the integration REPORTED the entity since the write? Until it
        # has, the state is the stale pre-write value by definition and there
        # is nothing to judge (06.09 audit — Huawei polls every 30-60 s).
        reported = (getattr(st, "last_reported", None)
                    or getattr(st, "last_updated", None)) if st is not None else None
        try:
            reported_ts = float(reported.timestamp()) if reported is not None else None
        except (AttributeError, TypeError, ValueError):
            reported_ts = None
        if (reported_ts is not None and wrote_wall is not None
                and reported_ts < wrote_wall
                and elapsed < self._WRITE_REPORT_WAIT_S):
            return None          # no report since the write yet — wait
        self._pending_write = None
        attrs = getattr(st, "attributes", None) or {}
        # Compared in WATTS through the one canonical converter (#641): the
        # entity's own unit decides the scale, and one native unit of it is
        # the tolerance — the resolution the register can express.
        scale = power_unit_scale(st) if st is not None else 1.0
        seen_w = power_state_to_watts(st) if st is not None else None
        tol_w = self._WRITE_TOLERANCE_NATIVE * scale
        # the entity may clamp to its own max — a reflected write is one
        # that landed within tolerance OR at the entity's ceiling
        ceiling = attrs.get("max")
        ceiling_w = float(ceiling) * scale if ceiling is not None else None
        reflected = seen_w is not None and (
            abs(seen_w - watts) <= tol_w
            or (ceiling_w is not None and watts >= ceiling_w
                and abs(seen_w - ceiling_w) <= tol_w))
        if reflected:
            self.write_not_taken_strikes = 0
            self.last_unverified_entity = ""
            return True
        self.write_not_taken_strikes += 1
        self.last_unverified_entity = entity_id
        label = str(attrs.get("unit_of_measurement") or "W")
        self.last_unverified_wanted = f"{watts / scale:g} {label}"
        self.last_unverified_seen = (f"{seen_w / scale:g} {label}"
                                     if seen_w is not None
                                     else str(getattr(st, "state", "missing")))
        self._last_error = (
            f"write not reflected by {entity_id}: wanted "
            f"{self.last_unverified_wanted}, reads {self.last_unverified_seen}")
        return False

    @property
    def last_discharge_limit_w(self) -> float:
        """(#900) The discharge limit this adapter last commanded, -1 when
        none yet — the anchor the actuator quantises the next one against."""
        return float(getattr(self, "_last_discharge_limit_w", -1.0))

    def __init__(self, hass, config: dict) -> None:
        self._hass = hass
        self._config = config
        self._last_intent: "Optional[BatteryIntent]" = None
        self._last_error: "Optional[str]" = None
        self._last_discharge_limit_w: float = -1.0
        """Last applied discharge limit — used by command_limit_discharge
        to de-dup consecutive same-value writes. Mirrors today's
        100 W hysteresis (formerly BatteryProtectionMixin)
        (battery_protection.py:106-109)."""
        # #523 export arbitrage — the number entity that sets the battery's
        # forcible discharge-to-grid power. Brand-agnostic: any battery whose
        # integration exposes such a number (Huawei LUNA "Forcible discharge
        # power", a Sessy/Growatt setpoint, a template/script-backed number)
        # can sell to grid. Empty → ``supports_forced_discharge`` is False
        # and the actuator drops FORCE_DISCHARGE.
        self._force_discharge_entity: str = config.get(
            "battery_force_discharge_control_entity", "",
        )
        # (#840) Consecutive refusals of the forcible-discharge write.
        #
        # @RienduPre's Growatt exposes the setpoint entity but its firmware
        # does not implement the write ("Not supported by device"), and SEM
        # retried every cycle for nineteen hours — 2,364 log lines. That
        # register will not appear tomorrow: the retry is the fault, and the
        # log spam only its symptom.
        #
        # Deliberately NOT parsed from the error string: those differ per
        # integration and change without notice. Count evidence instead, the
        # way the charger side already does (3 strikes → Repair, cleared on
        # success). Not persisted, so a restart re-arms it and a firmware
        # update or corrected entity gets another chance without the user
        # needing to know SEM had given up.
        self._force_discharge_failures: int = 0
        # (#840) The last value whose write was REFUSED. Distinct from
        # ``_last_force_discharge_w``, which records what actually landed.
        self._last_force_discharge_attempt_w: "Optional[float]" = None
        #: Monotonic deadline before the next silent probe (#840).
        self._force_discharge_retry_after: float = 0.0
        #: (#872) How often SEM's OWN unit check refused a write, as opposed
        #: to the device refusing one. These are different faults with
        #: different fixes, and the withdrawal message used to know only
        #: about the second — so it blamed firmware for a flaky entity.
        #: Latched-bool logging is fine for volume; a bool is useless as
        #: evidence, and this is evidence.
        self._fd_unit_refusals: int = 0
        # de-dup writes. None = never written (so the first write of any sign
        # always goes through; a plain -1.0 sentinel would alias a real
        # negative charge setpoint on a bidirectional entity, #523).
        self._last_force_discharge_w: Optional[float] = None
        # #709: runtime scope — config entry + battery identity. Injected by the
        # coordinator's ``_battery_adapter_context``; pure metadata, never part
        # of entry data/options and never serialised into the adapter.
        self._config_entry_id: str = config.get("config_entry_id", "")
        self._battery_id: str = config.get("battery_id", "")

    # ─── Capability ────────────────────────────────────────────

    @property
    @abstractmethod
    def max_charge_power_w(self) -> float:
        """Brand-reported max charge power."""

    @property
    @abstractmethod
    def max_discharge_power_w(self) -> float:
        """Brand-reported max discharge power. Returned to NORMAL."""

    @property
    @abstractmethod
    def supports_forced_charge(self) -> bool:
        """True if this brand has a forced-charge service.
        ``Sonnen`` would return False — protection-only adapter."""

    def _raise_force_discharge_repair(
        self, error: str, *, unstable: bool = False,
    ) -> None:
        """(#840) Surface the withdrawn capability outside the log.

        (#872) ``unstable`` carries the same suspicion the log line now
        makes — the Repair is the surface, and a surface that contradicts
        the log is worse than no surface at all.
        """
        try:
            from ..repair_issues import raise_battery_force_discharge_unsupported
            raise_battery_force_discharge_unsupported(
                self._hass, self._force_discharge_entity, error=error,
                unstable=unstable)
        except Exception as e:  # noqa: BLE001 — a repair never costs a cycle
            _LOGGER.debug("force-discharge repair not raised: %s", e)

    def _clear_force_discharge_repair(self) -> None:
        try:
            from ..repair_issues import clear_battery_force_discharge_unsupported
            clear_battery_force_discharge_unsupported(
                self._hass, self._force_discharge_entity)
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("force-discharge repair not cleared: %s", e)

    @property
    def supports_forced_discharge(self) -> bool:
        """True when a forcible-discharge control entity is configured
        (#523) — brand-agnostic battery→grid arbitrage. No entity → the
        actuator drops FORCE_DISCHARGE.

        (#840) Also False once the device has REFUSED the write
        ``FORCE_DISCHARGE_FAILURE_LIMIT`` times in a row. Muting the log while
        still advertising the capability would be the worse half of a fix: the
        actuator would go on issuing FORCE_DISCHARGE and the planner would go
        on budgeting an export that can never happen, silently. Withdrawing it
        makes the loss of function explicit to every consumer at once."""
        if not self._force_discharge_entity:
            return False
        return self._force_discharge_failures < self.FORCE_DISCHARGE_FAILURE_LIMIT

    @property
    def last_intent(self) -> "Optional[BatteryIntent]":
        return self._last_intent

    @property
    def last_error(self) -> "Optional[str]":
        return self._last_error

    # ─── Commands ──────────────────────────────────────────────

    async def async_recover_pending(self) -> bool:
        """Recover persistent brand state before first actuation.

        Most adapters have no transactional state and therefore need no work.
        Stateful adapters override this method and fail closed on recovery
        errors.
        """
        return True

    @abstractmethod
    async def command_normal(self) -> None:
        """Restore default discharge limit (max_discharge_power_w)."""

    @abstractmethod
    async def command_limit_discharge(self, watts: float) -> None:
        """Hold discharge to ``watts``. Implementations apply
        hysteresis — if ``watts`` is within ±100 W of the last
        applied value, skip the HA service call."""

    @abstractmethod
    async def command_force_charge(
        self,
        target_soc: float,
        charge_power_w: float,
        duration_min: int,
    ) -> None:
        """Start a forced grid → battery charge."""

    @abstractmethod
    async def command_stop_force_charge(self) -> None:
        """Cancel an active forced charge."""

    async def command_force_discharge(
        self, power_w: float, floor_soc: float,
    ) -> None:
        """Sell to grid: set the configured forcible-discharge power
        (#523), clamped to the brand's max discharge. Brand-agnostic —
        any battery with a discharge-power number entity can use it.

        Sets ``_last_intent`` ONLY when the write succeeds — a failed
        write leaves ``_last_intent`` unchanged so the next cycle
        re-issues the command rather than masquerading as successful."""
        watts = max(0.0, min(float(power_w), self.max_discharge_power_w))
        ok = await self._write_force_discharge(watts)
        if ok:
            self._last_error = None
            self._last_intent = BatteryIntent.FORCE_DISCHARGE
        else:
            self._last_error = "write_force_discharge failed"

    async def command_stop_force_discharge(self) -> None:
        """Stop selling — zero the forcible-discharge power and restore
        the brand default discharge limit.

        Both writes must succeed to record STOP_FORCE_DISCHARGE — a
        partial failure leaves ``_last_intent`` unchanged so the next
        cycle retries."""
        ok = await self._write_force_discharge(0.0)
        if not ok:
            self._last_error = "write_force_discharge(0) failed on stop"
            return
        await self.command_normal()
        # command_normal sets _last_intent = NORMAL; override to STOP.
        self._last_error = None
        self._last_intent = BatteryIntent.STOP_FORCE_DISCHARGE

    async def command_off(self) -> None:
        """#523 (RienduPre): SEM hands-off this battery.

        On the transition INTO off — from any SEM-controlled state — do a
        one-time clean handoff via ``command_normal`` (clears a force
        command, releases the power strategy SEM took, un-limits the
        discharge) so the battery isn't stranded in a SEM-imposed mode.
        After that, every subsequent off cycle is a true no-op: SEM issues
        nothing and the inverter manages the battery on its own. Brand-
        agnostic — relies only on each adapter's ``command_normal``.

        If the internal ``command_normal`` fails, OFF is NOT recorded so
        the next cycle retries the clean handoff."""
        if self._last_intent is BatteryIntent.OFF:
            return  # already handed off — stay completely silent
        await self.command_normal()
        # Only record OFF if command_normal succeeded (it sets NORMAL on
        # success; if it failed _last_intent stays at the prior value).
        if self._last_intent is BatteryIntent.NORMAL:
            self._last_error = None
            self._last_intent = BatteryIntent.OFF

    def _force_charge_already_stopped(self) -> bool:
        """True when a STOP_FORCE_CHARGE would command nothing (#757).

        Stopping something that is already stopped is not a command — it
        is noise on the wire. That distinction did not matter while the
        stop was issued once, at the transition out of a forced charge.
        The one-gate build (#638 C4) changed the shape of the decision:
        ``decide_battery`` now returns STOP_FORCE_CHARGE on EVERY cycle
        the scheduler is SCHEDULED and the plan block is not open, so a
        21:00 verdict with a 02:00 block asks ~1800 times. On a single
        serial Modbus link that is the #538 collision class, one layer up.

        The predicate is deliberately the ``command_off`` shape (see
        above): ``_last_intent`` is the record of what the HARDWARE was
        last told, so it may only be set on a write that actually landed.
        Every caller therefore has to keep the honest-retry discipline —
        a failed stop leaves the intent alone and the next cycle tries
        again. ``_forcible_charging`` is the Huawei-only belt-and-braces
        (absent elsewhere, hence the ``getattr``): if we believe a charge
        is running, we never stay silent.
        """
        return (
            self._last_intent is BatteryIntent.STOP_FORCE_CHARGE
            and not getattr(self, "_forcible_charging", False)
        )

    async def _write_force_discharge(self, watts: float) -> bool:
        """De-dup'd write of the battery power setpoint. ``watts`` is a
        SIGNED setpoint on a bidirectional control entity: ``> 0`` =
        discharge to grid (the #523 arbitrage path), ``< 0`` = charge from
        grid (AC-coupled Sessy-style bidirectional setpoint), ``0`` = idle.
        Mutual exclusion is the callers' job: ``command_normal`` /
        ``command_limit_discharge`` / ``command_force_charge`` /
        ``command_stop_force_charge`` zero this so the battery can't keep
        selling once SEM moves to any other mode.

        Returns True on success (including benign no-ops), False only on
        an exception from the HA service call. Callers must check the
        return value and NOT record intent when False (#589)."""
        if not self._force_discharge_entity:
            return True  # no-op needed — benign success
        # (#749) ONE validation rule with the discharge-limit path: reject
        # non-power units (a current-native number would take watts as
        # amperes), reject unreadable states, and SCALE to the entity's
        # native unit (a kW setpoint gets 3.0, not 3000 — which its range
        # clamp would otherwise turn into full tilt). Refusal is loud and
        # returns False so the caller never records intent (#589).
        from ..power_control import native_power_scale
        scale = native_power_scale(self._hass, self._force_discharge_entity)
        if scale is None or scale <= 0:
            self._fd_unit_refusals += 1
            if not getattr(self, "_fd_unit_refused_logged", False):
                self._fd_unit_refused_logged = True
                _LOGGER.warning(
                    "Battery: forcible-discharge write to %s REFUSED — the "
                    "entity's unit is not a supported power unit (or its "
                    "state is unreadable). Pick a W/kW power setpoint for "
                    "'Forcible-discharge power entity' (#749)",
                    self._force_discharge_entity,
                )
            return False
        # Clamp to the control entity's actual min/max (#523, mirrors the EV
        # #487 fix). A Sessy setpoint maxes at roughly ±2200 W, but the
        # computed charge/discharge power can exceed that (e.g. a fleet
        # battery_max_charge_power_w of 4400 written to a single 2200 W unit).
        # HA REJECTS an out-of-range number write, so the setpoint stays at its
        # last value (0) and the battery never charges — exactly the symptom
        # RienduPre saw (strategy → API, setpoint stuck at 0).
        st = self._hass.states.get(self._force_discharge_entity)
        attrs = getattr(st, "attributes", None) if st is not None else None
        _requested = watts
        if isinstance(attrs, dict):
            # (#749) the entity's min/max are NATIVE units — scale them to
            # watts so the clamp, the de-dup and every log stay in W; only
            # the service-call value converts back at the boundary.
            lo = attrs.get("min")
            if isinstance(lo, (int, float)):
                watts = max(float(lo) * scale, watts)
            hi = attrs.get("max")
            if isinstance(hi, (int, float)):
                watts = min(float(hi) * scale, watts)
        # #531: a silent clamp hides a real mismatch (fleet power > a single
        # unit's setpoint range). Surface it once per clamped write so the
        # cause is visible in the log instead of a mysteriously-capped battery.
        if abs(watts - _requested) >= 1.0:
            _LOGGER.warning(
                "Battery: setpoint %.0f W clamped to %.0f W by %s entity range "
                "[%s, %s] — check battery_max_charge/discharge_power vs the "
                "unit's rating",
                _requested, watts, self._force_discharge_entity,
                attrs.get("min"), attrs.get("max"),
            )
        # (#840) The device has refused enough times to settle the question.
        # Ask again only occasionally, and silently: a firmware update or a
        # cleared fault should recover on its own, but nobody needs to watch
        # it being asked.
        if self._force_discharge_failures >= self.FORCE_DISCHARGE_FAILURE_LIMIT:
            import time as _time
            now = _time.monotonic()
            if now < self._force_discharge_retry_after:
                return False
            self._force_discharge_retry_after = now + self.FORCE_DISCHARGE_RETRY_S
        # (#840) Do not re-issue a write that just failed with the SAME value.
        #
        # ``command_normal`` / ``command_limit_discharge`` / ``command_off``
        # each write 0 W as #523 mutual exclusion, and command_normal runs on
        # EVERY ordinary cycle. On a device that refuses the register that is
        # a guaranteed failure every cycle for the life of the install —
        # @RienduPre's Growatt logged 2,364 of them in nineteen hours, none
        # from the export feature (dormant on his system), all from this
        # routine zero.
        #
        # The repeat is unbounded BY CONSTRUCTION: ``_last_force_discharge_w``
        # is only assigned after a SUCCESSFUL call, so a failing write never
        # records itself and the de-dup below never engages.
        #
        # A same-value block was the first attempt at this and it was wrong:
        # test_fd2_retry_after_failure requires a TRANSIENT failure to be
        # retried with the same value, and it should be — a modbus blip that
        # clears must not permanently disable export. The distinction cannot
        # be made from the error, so it is made from persistence instead: the
        # strike counter below withdraws the capability after
        # FORCE_DISCHARGE_FAILURE_LIMIT consecutive refusals, and a SILENT
        # probe every FORCE_DISCHARGE_RETRY_S lets a device that recovers say
        # so without anyone watching the log.
        # Skip when within 100 W of the last applied value — the 0→0 case
        # (the common NORMAL cycle) must not spam the bus.
        if (self._last_force_discharge_w is not None
                and abs(watts - self._last_force_discharge_w) < 100.0):
            return True  # de-dup skip — no write needed, treat as success
        try:
            # Domain-aware: real-hardware setpoints are ``number.*`` (Huawei
            # forcible-discharge, Growatt/Sessy power numbers), but a user may
            # also wire an ``input_number.*`` helper. Both expose ``set_value``;
            # route to the control entity's own domain so either works.
            domain = self._force_discharge_entity.split(".", 1)[0]
            if domain not in ("number", "input_number"):
                domain = "number"
            await self._hass.services.async_call(
                domain, "set_value",
                # (#749) the one place watts become the entity's native unit.
                {"entity_id": self._force_discharge_entity,
                 "value": watts / scale},
                blocking=True,
            )
            self._last_force_discharge_w = watts
            self._last_force_discharge_attempt_w = None
            if self._force_discharge_failures:
                # Recovered — say so, and re-arm. A transient refusal that
                # cleared should not leave a countdown half-spent.
                _LOGGER.info(
                    "Battery: %s accepted a setpoint again after %d "
                    "refusal(s) — forcible discharge is available",
                    self._force_discharge_entity,
                    self._force_discharge_failures,
                )
                self._force_discharge_failures = 0
                self._clear_force_discharge_repair()
            if watts > 0:
                _LOGGER.info(
                    "Battery: forcible-discharge %.0f W → %s (arbitrage)",
                    watts, self._force_discharge_entity,
                )
            elif watts < 0:
                _LOGGER.info(
                    "Battery: forcible-charge %.0f W → %s "
                    "(bidirectional setpoint)",
                    -watts, self._force_discharge_entity,
                )
            return True
        except Exception as e:  # noqa: BLE001
            self._last_force_discharge_attempt_w = watts
            self._force_discharge_failures += 1
            limit = self.FORCE_DISCHARGE_FAILURE_LIMIT
            if self._force_discharge_failures > limit:
                # Past the limit this is a silent probe. It already said its
                # piece; repeating it is the 2,364-line log (#840).
                return False
            if self._force_discharge_failures < limit:
                _LOGGER.warning(
                    "Battery: failed to set forcible discharge via %s "
                    "(attempt %d/%d): %s",
                    self._force_discharge_entity,
                    self._force_discharge_failures, limit, e,
                )
            else:
                # The last word on the subject. Everything after this is
                # silence, because the answer will not change (#840).
                #
                # (#872) But say WHICH answer. Two different things refuse a
                # write in this function, on different cycles: our own unit
                # check (entity unreadable / wrong unit — returns early, no
                # strike) and the device (a real exception — one strike). If
                # BOTH have refused, the device is almost certainly not the
                # fault: an entity that is readable on some cycles and dark
                # on others produces exactly this pair. RienduPre read his
                # log and said so ("a misdirected entity reference rather
                # than a real hardware limitation") — and our message, which
                # could see only its own counter, argued him out of it.
                if self._fd_unit_refusals:
                    detail = (
                        f"{e} — but SEM's own unit check ALSO refused "
                        f"{self._fd_unit_refusals} write(s) to "
                        f"{self._force_discharge_entity} on other cycles "
                        f"(unit unreadable or not a power unit). An "
                        f"INTERMITTENTLY UNAVAILABLE entity produces exactly "
                        f"this pair, so check the entity before the firmware"
                    )
                    _LOGGER.warning(
                        "Battery: %s refused the forcible-discharge setpoint "
                        "%d times (%s). Withdrawing battery-to-grid export "
                        "and no longer attempting it. The likely fault is "
                        "the ENTITY, not the device: SEM's own unit check "
                        "refused %d further write(s) to it on other cycles "
                        "because its unit or state was unreadable — an "
                        "intermittently unavailable entity looks exactly "
                        "like this. Check %s stays available with a W/kW "
                        "unit; restart SEM to try again.",
                        self._force_discharge_entity, limit, e,
                        self._fd_unit_refusals, self._force_discharge_entity,
                    )
                else:
                    detail = str(e)
                    _LOGGER.warning(
                        "Battery: %s refused the forcible-discharge setpoint "
                        "%d times (%s). Treating battery-to-grid export as "
                        "unsupported on this device and no longer attempting "
                        "it. If this is wrong — a renamed entity, or firmware "
                        "that gained the register — restart SEM to try again.",
                        self._force_discharge_entity, limit, e,
                    )
                # Start the backoff HERE, at the moment of withdrawal —
                # otherwise the deadline is still 0.0 and the very next cycle
                # fires a probe, spending a strike for nothing.
                import time as _time
                self._force_discharge_retry_after = (
                    _time.monotonic() + self.FORCE_DISCHARGE_RETRY_S)
                # (#799) The Repair is the surface, so it carries the same
                # suspicion — a Repair that says "unsupported device" while
                # the log says "flaky entity" is worse than no Repair.
                self._raise_force_discharge_repair(
                    detail, unstable=bool(self._fd_unit_refusals))
            return False
