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

from ..charger_types import BatteryIntent, ExportIntent
from ...utils.select_option import listed_option

_LOGGER = logging.getLogger(__name__)


def unload_release_reason(adapter, was_observer: bool) -> Optional[str]:
    """(#936) Why THIS adapter must be commanded once more on unload — or
    ``None``: leave the battery exactly as found.

    Unload used to run ``command_normal()`` ("restore discharge to max") on
    every adapter, whatever SEM had or had not done. On 08.09.2026 the .46
    test rig — observer mode ON, so SEM had commanded nothing, ever — wrote
    the SHARED Huawei discharge-limit register from 750 to 5000 W on its
    way out, while PROD was holding it at 750. The #908 rule for loads
    applies here word for word: release what SEM started, leave the rest.

    - observer was on → nothing. Observer commands nothing, including on
      the way out.
    - a forcible charge / discharge SEM started is still active → stop it
      (the inverter must not be left in a forced mode nobody manages).
    - a discharge limit SEM wrote in this lifetime is still in force → hand
      it back (``command_normal`` restores the maximum; the same-value skip
      makes it a no-op when it already is).
    - (#1181) a forced charge or sale SEM started has not been seen to stop,
      or the power setpoint SEM wrote is not 0 W → stop it. A lifetime whose
      first command was a sale wrote no limit, so the limit alone missed it.
    - otherwise → nothing. SEM never commanded this battery.
    """
    if was_observer:
        return None
    if getattr(adapter, "_forcible_charging", False) or getattr(adapter, "_forcible_discharging", False):
        return "a forcible operation SEM started is still active"
    charge = getattr(adapter, "_charge_adapter", None)
    if charge is not None and bool(getattr(charge, "is_active", False)):
        return "a forced charge SEM started is still active"
    if (getattr(adapter, "_sem_forced_charge", None) is True
            or getattr(adapter, "_sem_forced_discharge", None) is True):
        return "a forced charge or sale SEM started has not been seen to stop"
    setpoint = getattr(adapter, "_last_force_discharge_w", None)
    if isinstance(setpoint, (int, float)) and not isinstance(setpoint, bool) and setpoint != 0:
        return f"a power setpoint SEM wrote ({setpoint:.0f} W) is still in force"
    try:
        last = float(getattr(adapter, "_last_discharge_limit_w", -1.0))
    except (TypeError, ValueError):
        last = -1.0
    if last >= 0:
        return f"a discharge limit SEM wrote ({last:.0f} W) is still in force"
    return None


async def async_release_batteries_on_unload(coordinator) -> dict:
    """(#936 — rule, 08.09.2026: *"on uninstall SEM should go to observation
    mode on and then uninstall"*.) Flip the coordinator to observer mode
    FIRST, so no cycle still in flight commands anything, then hand back only
    what SEM itself commanded (see :func:`unload_release_reason`).

    Returns ``{battery_id: what happened}`` for the caller to log. Never
    raises: a flaky Modbus must not block an unload.
    """
    was_observer = bool(getattr(coordinator, "_observer_mode", False))
    try:
        coordinator._observer_mode = True
    except Exception:  # noqa: BLE001 — a read-only stand-in in tests
        pass
    outcome: dict = {}
    adapters = getattr(coordinator, "_battery_adapters", {}) or {}
    for bid, adapter in adapters.items():
        # (#1178) a cycle still running may have left another battery as
        # this one's limit writer; the hand-back is every battery's own.
        # (#1182) The same for the sale power.
        try:
            adapter._limit_writer = None
            adapter._setpoint_writer = None
        except Exception:  # noqa: BLE001 — a read-only stand-in in tests
            pass
        why = unload_release_reason(adapter, was_observer)
        if why is None:
            outcome[bid] = ("observer mode — nothing was ever commanded, nothing written"
                            if was_observer else "nothing commanded in this lifetime — left as found")
            continue
        try:
            await adapter.command_normal()
            # (#1181) a stop that failed records no NORMAL: say so, there is
            # no next cycle to try it again
            err = (getattr(adapter, "last_error", None)
                   if getattr(adapter, "last_intent", None) is not BatteryIntent.NORMAL
                   else None)
            outcome[bid] = (f"release incomplete ({why}): {err}" if err
                            else f"released: {why}")
        except Exception as e:  # noqa: BLE001
            outcome[bid] = f"release failed (non-blocking): {e}"
    return outcome


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
    #: (#933) the entity the last REFLECTED write proved — a Repair raised
    #: against it before a restart/reload can go on this lifetime's proof.
    last_verified_entity: str = ""
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

    #: (#1138) A limit write the entity did not keep is sent ONCE more: the
    #: 100 W same-limit skip below would otherwise hold the old register
    #: value until the wanted limit moves. ``_limit_resent_for_w`` is the
    #: limit that already had its one extra send, so a register that keeps
    #: refusing is not written every cycle (#538, #900).
    _limit_resend_due: bool = False
    _limit_resent_for_w: "Optional[float]" = None

    #: (#1178) Set by the pipeline only while the cycle's commands run, when
    #: another battery shares this adapter's discharge limit entity: the
    #: battery that writes it (its own id on a cycle nobody writes it, after
    #: a stop). ``None``: this adapter writes it. See
    #: ``coordinator/battery_shared_limit.py``.
    _limit_writer: "Optional[str]" = None
    #: (#1178) The ``(watts, force)`` of the limit write held back this
    #: cycle — sent after all if the writer's sale did not go out.
    _limit_withheld: "Optional[tuple]" = None
    #: (#1178) This cycle's command sent a stop that the device must not
    #: get a write right after (Huawei's one write per cycle). Reset by the
    #: pipeline each cycle.
    _sent_stop: bool = False
    #: (#1178) This cycle's command sent the sale, or found it running.
    #: Reset by the pipeline each cycle: ``last_intent`` outlives a sale that
    #: has stopped going out.
    _sale_sent: bool = False
    #: (#1182) The same for the sale power entity: set by the pipeline only
    #: while the cycle's commands run, when another battery shares it — the
    #: battery that writes it. ``None``: this adapter writes it.
    _setpoint_writer: "Optional[str]" = None
    #: (#1182) The value held back for that writer this cycle — sent after
    #: all if the writer's command did not reach the entity.
    _setpoint_withheld: "Optional[float]" = None
    #: (#1182) This cycle's command, as the writer, left the sale power
    #: entity holding its value (sent, or skipped as the same value). A
    #: refused write is not that. Reset each cycle.
    _setpoint_spoke: bool = False
    #: (#1182) The zero held back was a stop on a device that takes no
    #: write right after one: sent after all, it is still that stop.
    _stop_withheld: bool = False

    def sale_setpoint_entity(self) -> str:
        """(#1182) The sale power entity this adapter's commands write, or
        ``""``. A brand that sells another way overrides it."""
        return str(self._force_discharge_entity or "")

    def sale_surface(self) -> str:
        """(#1182) What a sale from this battery lands on. Batteries with
        the same answer sell as one, so the sale is split per answer."""
        return self.sale_setpoint_entity()

    def _limit_not_mine(self, watts: float, force: bool = False) -> bool:
        """(#1178) True when this adapter must not write the shared
        discharge limit this cycle: every ``_apply_discharge_limit`` then
        sends nothing and keeps what it would have sent. The pipeline gives
        this adapter the writer's record after the cycle."""
        if self._limit_writer is None:
            return False
        self._limit_withheld = (float(watts), bool(force))
        return True

    def _limit_already_sent(self, watts: float) -> bool:
        """The same-limit skip for ``command_limit_discharge``: True when the
        last limit is within 100 W of ``watts`` and nothing asks for a
        re-send. A pending re-send is used up by the call that sees it."""
        if self._limit_resend_due:
            self._limit_resend_due = False
            return False
        return (self._last_discharge_limit_w >= 0
                and abs(watts - self._last_discharge_limit_w) < 100.0)

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
            # (07.09 re-audit) A NAIVE datetime is read by Python as LOCAL
            # time, so `.timestamp()` would shift by the host's UTC offset
            # and a fresh report could look older than the write. HA's own
            # State is always tz-aware; a helper or a test double may not be.
            if reported is not None and reported.tzinfo is None:
                import datetime as _dt
                reported = reported.replace(tzinfo=_dt.timezone.utc)
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
            self._limit_resent_for_w = None
            self.write_not_taken_strikes = 0
            self.last_unverified_entity = ""
            self.last_verified_entity = entity_id
            return True
        self.write_not_taken_strikes += 1
        if (entity_id == getattr(self, "_discharge_control_entity", None)
                and self._limit_resent_for_w != watts):
            self._limit_resend_due = True
            self._limit_resent_for_w = watts
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

    #: (#1066) Per direction: did a forced charge / discharge SEM started
    #: land, and has its stop landed since? None = unknown (this adapter has
    #: not seen either). Written by ``actuate_battery._note_forced_op``, and
    #: for a charge (#1181) by :meth:`async_adopt_running_charge` (True: the
    #: last lifetime started one) and :meth:`_stop_own_charge` (False: Off or
    #: the unload hand-back stopped it).
    _sem_forced_charge: "Optional[bool]" = None
    _sem_forced_discharge: "Optional[bool]" = None
    #: (#1066) cycles in a row a stop has not landed while a flag is True
    _sem_stop_misses: int = 0

    #: (#1066) what ``last_error`` says when SEM is asked to limit discharge
    #: and has no entity to write the limit to.
    NO_DISCHARGE_LIMIT_ERROR = (
        "no discharge limit entity — SEM cannot cap this battery, so it "
        "covers any load on the meter, the car included")

    def _discharge_limit_unwritable(self) -> bool:
        """(#1066) True when a LIMIT_DISCHARGE has nowhere to go — and say so.

        With no ``battery_discharge_control_entity`` the brand writers used
        to record the asked-for watts as the limit in force and return. No
        write went out, nothing said so, and the discharge-limit sensor and
        the Diagnose block both showed a cap the battery never had.
        @RienduPre's 2× Sessy (no discharge-limit setting at all, only the
        power setpoint) covered 2.3 kW of car from the pack that way.

        Records no limit (-1, "none written") and puts the gap in
        ``last_error`` — the Deye convention for a limit it cannot apply.
        The intent is still recorded by the caller: it is what SEM asked for.
        """
        if getattr(self, "_discharge_control_entity", ""):
            return False
        self._last_discharge_limit_w = -1.0
        self._last_error = self.NO_DISCHARGE_LIMIT_ERROR
        if not getattr(self, "_no_limit_said", False):
            self._no_limit_said = True
            _LOGGER.warning(
                "Battery: asked to limit discharge, but no discharge limit "
                "entity is set — SEM cannot keep this battery out of the car "
                "(%s, #1066)", type(self).__name__)
        return True

    def _clear_no_limit_error(self) -> None:
        """(#1066) The gap is only an error while a limit is asked for."""
        if self._last_error == self.NO_DISCHARGE_LIMIT_ERROR:
            self._last_error = None

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
        # (#933) The Repair is persistent; the count above is not. A reload
        # builds this adapter at zero, so "recovered from refusals" never
        # fires for a Repair its predecessor raised — the first accepted
        # discharge setpoint of this adapter's life clears it, once.
        self._force_discharge_repair_reconciled: bool = False
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
        re-issues the command rather than masquerading as successful.

        (#1175) A discharge limit SEM wrote before the sale is put back to
        the max first (:meth:`_hand_back_own_limit`)."""
        await self._hand_back_own_limit()
        await self._send_sale(power_w)

    def _own_limit_held(self) -> bool:
        """(#1175) Is the last discharge limit SEM wrote below the pack's
        max? −1 (SEM wrote none) is no. So is one entity for both the limit
        and the sale power: that register is the sale's own. (#1165 review)
        The sale power the sale really writes: a Huawei sale by service
        writes no entity, so a limit there still holds it."""
        if getattr(self, "_discharge_control_entity", "") == self.sale_setpoint_entity():
            return False
        return 0.0 <= self.last_discharge_limit_w < float(self.max_discharge_power_w)

    async def _hand_back_own_limit(self) -> None:
        """(#1175) Before a sale: put back the pack's max discharge when the
        last limit SEM wrote is below it.

        A limit SEM wrote to keep the pack for the house (the 0 W cheap-hour
        hold, the EV clamp) stays in the register until a command writes it
        again, and only NORMAL did. On a brand where that limit also caps a
        forced discharge, the sale then sends nothing. A limit SEM did not
        write (``last_discharge_limit_w`` is −1) is left as it is (#936).

        The write skips the same-value check: SEM knows it wrote a lower
        limit, and the entity can still show the max from before that write
        until the integration reads it again (review). A failed write leaves
        the record low, so the next sale cycle asks again.
        """
        if not self._own_limit_held():
            return
        apply = getattr(self, "_apply_discharge_limit", None)
        if apply is None:
            return
        await apply(float(self.max_discharge_power_w), force=True)
        if (not self._own_limit_held()
                and self._last_intent is BatteryIntent.LIMIT_DISCHARGE):
            # The limit is gone. Left as the last command, LIMIT_DISCHARGE at
            # the max reads as a limit in force, and a hold that comes back
            # next cycle waits out the lowering dwell (review). A sale that
            # goes out this cycle records its own intent after this.
            self._last_intent = None

    async def _send_sale(self, power_w: float) -> None:
        """The sale's own write: the forcible-discharge power, clamped to
        the brand's max. Records the intent only when the write landed."""
        watts = max(0.0, min(float(power_w), self.max_discharge_power_w))
        ok = await self._write_force_discharge(watts)
        if ok:
            self._sale_sent = True   # (#1178)
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
        ok = await self._zero_setpoint()
        if not ok:
            self._last_error = "write_force_discharge(0) failed on stop"
            return
        await self.command_normal()
        # command_normal sets _last_intent = NORMAL; override to STOP.
        # (#1181) It records no NORMAL when the stop of a charge SEM started
        # failed: the sale stop landed, but that error stays to be seen.
        if self._last_intent is BatteryIntent.NORMAL:
            self._last_error = None
        self._last_intent = BatteryIntent.STOP_FORCE_DISCHARGE

    # ── (#955) export control: the dialect is per brand ──────────────────
    #: What the adapter last wrote as an export cap; None = released / never.
    _last_export_limit_w: Optional[float] = None
    #: The export axis's OWN #538 de-dup marker. Never ``_last_intent``: that
    #: one belongs to the battery axis, and a shared marker means an export
    #: write silently un-de-dups the next discharge limit (and vice versa) —
    #: two axes, two markers, or the register gets rewritten every cycle.
    _last_export_intent: Optional["ExportIntent"] = None

    async def command_limit_export(self, watts: float) -> None:
        """Cap grid feed-in at ``watts`` (0 = zero export). Brands without an
        export control raise ``NotImplementedError`` — the guard records the
        refusal; it is a state, not a crash."""
        raise NotImplementedError("this battery adapter has no export control")

    async def command_release_export(self) -> None:
        """Put the feed-in limit back to what SEM found."""
        raise NotImplementedError("this battery adapter has no export control")

    def export_release_recipe(self):
        """(#955) How to undo THIS adapter's export cut without the adapter —
        ``{"domain","service","data"}`` — persisted so a restart can adopt the
        cut and a removal can replay the release. None = nothing to undo."""
        return None

    #: A restore recipe adopted from a previous lifetime's store. It is the
    #: ONLY record of what that lifetime found, so it outranks anything this
    #: one can read back — by the time we adopt, the inverter is already
    #: showing SEM's own cut.
    _adopted_recipe = None

    def adopt_export_prior(self, recipe) -> None:
        """(#955) A previous lifetime engaged the cut; take over its prior so
        ``command_release_export`` restores what SEM originally found.

        KEEP THE RECIPE. It carries the mode the previous lifetime captured,
        and a brand whose restore is mode-dependent (Huawei) cannot recompute
        it: reading the inverter now returns SEM's own "Zero Power". Dropping
        it made the restart path fall back to "Unlimited" — the very defect
        the capture was added to fix, one lifetime later.
        """
        self._last_export_limit_w = 0.0
        self._last_export_intent = ExportIntent.LIMIT
        if isinstance(recipe, dict) and recipe.get("service"):
            self._adopted_recipe = dict(recipe)

    def export_control_wired(self) -> bool:
        """(#1183) Does this adapter have something to cut export with?

        A brand that overrides ``command_limit_export`` has its own way
        (Huawei: a service on the inverter; Deye: its work-mode select). The
        generic adapter only once its number is set. Asked by the export
        pick, so a generic battery beside the inverter's battery is not
        offered a cut it cannot make.
        """
        fn = getattr(type(self), "command_limit_export", None)
        owner = getattr(fn, "__qualname__", "").split(".")[0] if fn else ""
        return bool(owner) and owner != "BatteryControlAdapter"

    def holds_export_cut(self) -> bool:
        """(#908) Is THIS adapter holding a cut SEM itself made?

        Not the same question as :meth:`export_release_recipe`, which answers
        "how would I undo one" — Huawei can always answer that (the
        integration owns the reset), so on a mixed fleet the recipe said yes
        for an inverter SEM had never touched, and a teardown would have
        reset a feed-in limit the OWNER set. One cut is made through one
        adapter; only that one may be handed back.
        """
        return self._last_export_intent is ExportIntent.LIMIT

    def export_dry_run(self, intent, watts: float) -> dict:
        """(#955) What the export verb WOULD send this cycle, without sending.

        The export axis's half of #855: an observer rig is judged on what
        would hit the wire, so the wire must be readable. Returns one row in
        the ``withheld_commands`` shape — ``{"service": "domain.service",
        "data": {...}, "why": None}`` — or, when the real verb would refuse
        before writing, ``{"service": None, "data": None, "why": "<the
        refusal, in the verb's own words>"}``. Pure: no write, no capture, no
        marker touched. Brands override; the default is the base refusal.
        """
        return {"service": None, "data": None,
                "why": "this battery adapter has no export control"}

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

    async def async_adopt_running_charge(self) -> None:
        """(#1181) Before this adapter's decisions: take over a forced
        charge SEM started and has not seen stop, in the last lifetime too.

        An HA restart never unloads the entry, so a switch or mode charge
        (GoodWe, the generic switch setup) runs on across it. The new
        adapter knew nothing of it: with night charging off by then, no stop
        came, and Off and an unload had nothing to stop either. The charge
        adapter's record (``charge_record.ForcedChargeRecord``) says whether
        SEM turned this battery's actuator on; if so the charge is active,
        and ``_sem_forced_charge`` is True, so the next NORMAL or limit
        decision stops it first (``decide_battery._stop_what_sem_started``).
        Only while the actuator still reads a charge, and not before it can
        be read: the coordinator asks on every cycle, and it is a no-op once
        settled.

        Reads only (bar dropping a name whose actuator reads no charge), so
        the coordinator calls it in observer mode too: the decision then
        still sends nothing. Brands that keep no such record (Huawei reads
        its own status sensor, Deye its snapshot) do nothing here. Never
        raises."""
        adopt = getattr(getattr(self, "_charge_adapter", None), "adopt_running", None)
        if adopt is None:
            return
        try:
            if await adopt():
                self._sem_forced_charge = True
                # An Off or a stop recorded before the charge could be seen
                # (its actuator not loaded yet) no longer says what the pack
                # was last told: without this, Off stays silent and the
                # charge runs on (review).
                if self._last_intent in (BatteryIntent.OFF,
                                         BatteryIntent.STOP_FORCE_CHARGE):
                    self._last_intent = None
        except Exception:  # noqa: BLE001 — a record never costs a cycle
            _LOGGER.debug("forced charge not adopted", exc_info=True)

    async def _stop_own_charge(self) -> bool:
        """(#1181) A forced charge SEM started, stopped by the hand-back.

        Off and the unload release both hand the battery back through
        ``command_normal`` (Off through ``command_off``). On GoodWe and the
        generic switch setup that zeroed the setpoint and lifted the limit,
        but only the stop turns the work mode or the switch back, so the
        pack went on charging from the grid with nothing watching it, and
        the charge target SEM wrote stayed (#1180). Huawei's own
        ``command_normal`` already stops its charge; Deye's restores its
        snapshot.

        No charge of SEM's active → True, nothing sent. A stop that landed →
        True, and ``_sem_forced_charge`` is False: the next decision has
        nothing left to stop. A stop that failed → False and ``last_error``
        says so. The caller still writes the rest of its hand-back (the
        zero, the strategy, the limit: an unload has no next cycle, and the
        #1066 protection cycle must still write its limit) and only records
        no NORMAL / OFF, so the next cycle tries the stop again (#589)."""
        charge = getattr(self, "_charge_adapter", None)
        if charge is None or not bool(getattr(charge, "is_active", False)):
            return True
        from .force_charge import ChargeCommandStatus
        status = await charge.stop_forced_charge()
        if getattr(status, "status", None) is ChargeCommandStatus.FAILED:
            self._last_error = (
                f"{self.STOP_OWN_CHARGE_FAILED}: {getattr(status, 'message', '')}")
            return False
        if str(self._last_error or "").startswith(self.STOP_OWN_CHARGE_FAILED):
            self._last_error = None
        self._sem_forced_charge = False
        return True

    #: (#1181) how ``last_error`` names a hand-back stop that failed
    STOP_OWN_CHARGE_FAILED = "stop_forced_charge failed"

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

    # ── (#809/#869) the setpoint model: how SEM's signed watts reach the wire ──
    SETPOINT_MODELS = ("signed", "inverted", "direction_select")

    def _setpoint_model(self) -> str:
        m = str((self._config or {}).get("battery_setpoint_model") or "signed")
        return m if m in self.SETPOINT_MODELS else "signed"

    def _setpoint_to_wire(self, watts: float) -> float:
        m = self._setpoint_model()
        if m == "inverted":
            return -watts
        if m == "direction_select":
            return abs(watts)
        return watts

    def _setpoint_from_wire(self, wire: float, sign: float) -> float:
        m = self._setpoint_model()
        if m == "inverted":
            return -wire
        if m == "direction_select":
            return sign * abs(wire)
        return wire

    async def _direction_ready(self, watts: float) -> bool:
        """``direction_select`` only: True when the select READS the
        direction ``watts`` needs. Otherwise write it (once per wanted
        value) and answer False — the number waits for the next cycle,
        which is when a Modbus-backed select shows what it took (#978)."""
        if self._setpoint_model() != "direction_select" or watts == 0:
            return True
        ent = str(self._config.get("battery_power_direction_entity") or "")
        if not ent:
            if not getattr(self, "_direction_missing_said", False):
                self._direction_missing_said = True
                _LOGGER.warning(
                    "Battery: setpoint model is direction_select but no "
                    "direction select is configured "
                    "(battery_power_direction_entity) — nothing written",
                )
            return False
        # (#1039) the option the select lists — a label would be refused,
        # and the read below would then wait for it forever
        want = listed_option(self._hass, ent, str(self._config.get(
            "battery_direction_discharge_value" if watts > 0
            else "battery_direction_charge_value")
            or ("discharge" if watts > 0 else "charge")))
        st = self._hass.states.get(ent)
        if st is not None and str(getattr(st, "state", "")) == want:
            return True
        sent = getattr(self, "_direction_sent", None)
        if sent is None:
            sent = self._direction_sent = {}
        if sent.get(ent) != want:
            try:
                await self._hass.services.async_call(
                    "select", "select_option",
                    {"entity_id": ent, "option": want}, blocking=True,
                )
            except Exception as exc:  # noqa: BLE001
                self._last_error = f"direction select write failed: {exc}"
                return False
            sent[ent] = want
        self._last_error = f"waiting for {ent} to read {want}"
        return False

    def _setpoint_is_inert(self) -> bool:
        """(#1005) True when the power setpoint controls nothing right now.

        A DC battery's setpoint is always live, so this is False here. An
        AC-coupled battery gates it behind a power-strategy mode and ignores
        the setpoint in every other mode — see the override in
        ``generic.py``.
        """
        return False

    async def _zero_setpoint(self) -> bool:
        """The #523 mutual-exclusion zero — the ONE door for it (#1005).

        Every mode change zeroes the setpoint so the battery cannot keep
        selling into the next mode. When the setpoint is inert the write
        lands nowhere: the device refuses it, the refusal spends the #840
        strikes that withdraw battery-to-grid, and the caller reads the
        refusal as a transient fault and repeats it every cycle for ever
        (@RienduPre, 2× Sessy — 165 refusals in 28 h). Nothing to zero is
        done, not failed.

        SEM hands control back in this order — zero the setpoint, THEN leave
        the active mode — so the zero still lands on the cycle that matters.
        Only the cycles after it, where the register already controls
        nothing, are skipped.

        A skip FORGETS the register (``_last_force_discharge_w = None``).
        That marker is the de-dup's whole evidence that the register already
        holds a value, and SEM may only claim that for a write it made. If
        the hand-back cycle's zero were dropped and the skip then kept the
        marker at the old power, the next force op at the same power would be
        de-dup'd away — no write, no error, no strike, and a battery that
        does nothing while SEM reports it selling (found in review).
        """
        if self._setpoint_is_inert():
            self._last_force_discharge_w = None
            return True
        return await self._write_force_discharge(0.0)

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
        if self._setpoint_writer is not None:
            # (#1182) another battery writes the shared entity this cycle;
            # the pipeline gives this adapter its record after the cycle
            self._setpoint_withheld = float(watts)
            return True
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
        # (#809/#869) SEM's sign is + = discharge, − = charge. The WIRE
        # value is what the entity takes: the same (``signed``), its mirror
        # (``inverted`` — Victron's ESS grid setpoint, + = import), or a
        # magnitude behind a charge/discharge select (``direction_select``
        # — Anker Solix). The clamp applies to the wire value: an unsigned
        # entity has min 0, and clamping SEM's −4400 against that is the
        # bug this exists to avoid.
        sign = 1.0 if watts >= 0 else -1.0
        wire = self._setpoint_to_wire(watts)
        if isinstance(attrs, dict):
            # (#749) the entity's min/max are NATIVE units — scale them to
            # watts so the clamp, the de-dup and every log stay in W; only
            # the service-call value converts back at the boundary. (#820)
            # The clamp itself is shared with the charge pacer.
            from ..power_control import clamp_to_entity_range
            wire = clamp_to_entity_range(attrs, wire, scale)
        watts = self._setpoint_from_wire(wire, sign)
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
            self._setpoint_spoke = True   # (#1182) the entity holds it
            return True  # de-dup skip — no write needed, treat as success
        try:
            # Domain-aware: real-hardware setpoints are ``number.*`` (Huawei
            # forcible-discharge, Growatt/Sessy power numbers), but a user may
            # also wire an ``input_number.*`` helper. Both expose ``set_value``;
            # route to the control entity's own domain so either works.
            domain = self._force_discharge_entity.split(".", 1)[0]
            if domain not in ("number", "input_number"):
                domain = "number"
            # (#869) a direction select is written first and READ back
            # before the number goes out — the #978 rule, the strategy's
            # shape. Until it reads, the write is withheld, not sent blind.
            if not await self._direction_ready(watts):
                return False
            await self._hass.services.async_call(
                domain, "set_value",
                # (#749) the one place watts become the entity's native unit.
                {"entity_id": self._force_discharge_entity,
                 "value": wire / scale},
                blocking=True,
            )
            self._last_force_discharge_w = watts
            self._setpoint_spoke = True   # (#1182) the write landed
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
            elif watts > 0 and not self._force_discharge_repair_reconciled:
                # (#933) once, on an accepted DISCHARGE setpoint — the
                # capability the Repair names. The routine 0 W proves nothing:
                # a register can take 0 and refuse every real setpoint.
                self._clear_force_discharge_repair()
            if watts > 0:
                self._force_discharge_repair_reconciled = True
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
