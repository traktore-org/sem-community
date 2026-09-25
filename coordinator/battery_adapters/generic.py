"""GenericBatteryAdapter — brand-agnostic fallback.

Works with any inverter that exposes:
- A number entity for the battery discharge limit
- (optionally) A switch entity to force charge + a number entity
  for the SOC target

If forced-charge entities aren't configured, the adapter still
serves NORMAL / LIMIT_DISCHARGE (the reactive protection only).
"""
from __future__ import annotations

import logging
from typing import Optional

from ..charger_types import BatteryIntent, ExportIntent
from ..power_control import async_write_power_setpoint_verbose
from .base import BatteryControlAdapter

_LOGGER = logging.getLogger(__name__)


class GenericBatteryAdapter(BatteryControlAdapter):
    def __init__(self, hass, config: dict) -> None:
        super().__init__(hass, config)
        self._discharge_control_entity = config.get(
            "battery_discharge_control_entity", "",
        )
        self._max_discharge_w = float(
            config.get("battery_max_discharge_power", 5000),
        )
        self._force_charge_switch = config.get(
            "battery_force_charge_switch", "",
        )
        self._target_soc_entity = config.get("battery_target_soc_entity", "")
        # AC-coupled batteries (Sessy, …) gate the power setpoint behind a
        # "power strategy" mode select — the setpoint is IGNORED unless the
        # strategy is the active/API value (in eco/NOM the battery just self-
        # consumes). SEM switches it to the active value before forcing a
        # discharge and back to the idle/self-consumption value when done.
        self._strategy_entity = config.get("battery_strategy_control_entity", "")
        self._strategy_active = config.get("battery_strategy_active_value", "api")
        self._strategy_idle = config.get("battery_strategy_idle_value", "eco")
        # #523 (Rien, beta.42): map each per-battery MODE to the right Sessy
        # power strategy. ``eco`` is NOT self-consumption — ``nom`` (zero-on-
        # meter) is — so Auto / Self-consumption must set ``nom``, and ``Off``
        # must idle the battery, not leave it in ``eco``. Force charge/discharge
        # keep using ``_strategy_active`` (api). All configurable for other
        # AC-coupled brands.
        self._strategy_self_consume = config.get(
            "battery_strategy_self_consume_value", "nom")
        self._strategy_off = config.get("battery_strategy_off_value", "idle")
        #: the strategy the select was last SEEN at (#978) — never what SEM
        #: last sent. A flip is cached only once the entity reads it.
        self._last_strategy = None
        #: value → monotonic of the last SEND the select has not been seen to
        #: take. Per value, so an interleaved NORMAL (the select already reads
        #: ``nom``) cannot erase the evidence that ``api`` never landed — the
        #: reviewer's repro: a flap every cycle re-sent ``api`` forever and
        #: counted nothing (#978 challenge record).
        self._strategy_sent = {}
        #: (value, seen) of the last miss said aloud — say each once
        self._strategy_miss_said = None
        #: a miss / a landing not yet turned into a #915 verdict
        self._strategy_verdict = None
        self._setpoint_withheld_said = False
        # #523: AC-coupled batteries (Sessy, …) expose ONE bidirectional power
        # setpoint — the same ``battery_force_discharge_control_entity`` that
        # SEM writes a positive value to for discharge takes a NEGATIVE value
        # to charge. There is no separate force-charge switch, so the
        # switch-based GenericChargeAdapter can't drive them. When this flag is
        # set, force-charge writes ``-power`` to that same setpoint (gated by
        # strategy → active), mirroring force-discharge's ``+power``.
        # (#869) a direction select is two directions by construction.
        self._setpoint_bidirectional = bool(
            config.get("battery_setpoint_bidirectional", False)
            or (str(config.get("battery_setpoint_model") or "") == "direction_select"
                and config.get("battery_power_direction_entity")),
        )
        # #523: the user's own strategy before SEM took control (e.g. a Sessy
        # running ``nom``/``roi`` for self-consumption). Captured when SEM
        # switches to the active value and restored when SEM releases — so we
        # don't clobber their normal mode with the ``eco`` fallback.
        self._restore_strategy: "Optional[str]" = None
        # True once SEM has switched the strategy to the active/API value this
        # episode. Distinguishes "SEM took control → must hand it back" from
        # "SEM never touched it → leave the user's mode alone" (#523).
        self._took_control: bool = False
        # Lazy import for delegate
        try:
            from .force_charge import GenericChargeAdapter
            self._charge_adapter = GenericChargeAdapter(hass, config)
        except Exception:  # noqa: BLE001
            self._charge_adapter = None
        # #531: adopt a stranded API strategy left by a prior instance.
        self._detect_stranded_strategy()

    def _detect_stranded_strategy(self) -> None:
        """Detect a strategy left in the active/API value across a reload.

        If SEM is reloaded mid-discharge/arbitrage episode, a fresh adapter
        starts ``_took_control=False`` and would never hand the strategy
        back — stranding an AC-coupled battery in API (setpoint-controlled)
        instead of self-consumption. If the strategy entity is already at the
        active value at construction, the previous instance left it there:
        adopt control so the next NORMAL/STOP restores cleanly. The user's
        true prior mode is unrecoverable across the reload, so release falls
        to the idle default (the documented unreadable-prior fallback).
        """
        if not self._strategy_entity:
            return
        try:
            st = self._hass.states.get(self._strategy_entity)
        except Exception:  # noqa: BLE001
            return
        cur = getattr(st, "state", None)
        if isinstance(cur, str) and cur == self._strategy_active:
            self._took_control = True
            self._last_strategy = cur
            _LOGGER.info(
                "Generic battery: adopting stranded '%s' strategy on %s "
                "(reload mid-episode) — will restore idle on release",
                cur, self._strategy_entity,
            )

    #: (#978) a flip that did not land is re-sent no faster than this
    STRATEGY_RETRY_S: float = 60.0

    def _read_strategy(self) -> "Optional[str]":
        """What the strategy select READS now — ``None`` when it cannot be
        read (no state, unknown/unavailable, not a string). Three states
        (#925): "unreadable" is not "did not land"."""
        if not self._strategy_entity:
            return None
        try:
            st = self._hass.states.get(self._strategy_entity)
        except Exception:  # noqa: BLE001
            return None
        cur = getattr(st, "state", None)
        if not isinstance(cur, str) or cur in ("", "unknown", "unavailable"):
            return None
        return cur

    def _strategy_state_text(self) -> str:
        """The raw state for a message — ``missing`` when there is none."""
        try:
            st = self._hass.states.get(self._strategy_entity)
        except Exception:  # noqa: BLE001
            st = None
        cur = getattr(st, "state", None) if st is not None else None
        return str(cur) if isinstance(cur, str) and cur else "missing"

    def _strategy_landed(self, value: str) -> None:
        """The select reads ``value``. Everything cleared here is keyed on
        THIS value: a NORMAL finding ``nom`` already there says nothing
        about the ``api`` the select never took (challenge record)."""
        sent = self._strategy_sent.pop(value, None) is not None
        if self._strategy_miss_said and self._strategy_miss_said[0] == value:
            self._strategy_miss_said = None
        if value == self._strategy_active:
            self._setpoint_withheld_said = False
        if sent or self._last_strategy != value:
            _LOGGER.info(
                "Generic battery: power strategy → %s (%s)%s",
                value, self._strategy_entity, "" if sent else " — read, not sent",
            )
        self._last_strategy = value
        # (#915) the same read-back ledger the setpoint uses: the landing of
        # the value that MISSED clears the strikes it earned and files a
        # True verdict.
        if (self.last_unverified_entity == self._strategy_entity
                and self.last_unverified_wanted == value):
            self.write_not_taken_strikes = 0
            self.last_unverified_entity = ""
            self.last_verified_entity = self._strategy_entity
            self._strategy_verdict = True

    def _strategy_missed(self, value: str, age_s: float) -> None:
        seen = self._strategy_state_text()
        self.write_not_taken_strikes += 1
        self.last_unverified_entity = self._strategy_entity
        self.last_unverified_wanted = value
        self.last_unverified_seen = seen
        self._last_error = (
            f"power strategy not taken by {self._strategy_entity}: "
            f"wanted {value}, reads {seen}")
        self._strategy_verdict = False
        if self._strategy_miss_said != (value, seen):
            self._strategy_miss_said = (value, seen)
            _LOGGER.warning(
                "Generic battery: asked %s for power strategy '%s' %.0f s ago "
                "and it still reads %s — the flip did not land. SEM is NOT "
                "caching it and re-sends every %.0f s; the setpoint stays "
                "withheld until the select reads '%s'. If HA logs 'Referenced "
                "entities … missing or not currently available' for it, the "
                "id SEM targets is not the live select — check "
                "battery_strategy_control_entity (#978).",
                self._strategy_entity, value, age_s, seen,
                self.STRATEGY_RETRY_S, value,
            )

    async def _set_strategy(self, value: str) -> None:
        """Switch the battery's power-strategy mode — and believe the ENTITY,
        not the service call (#978).

        ``select_option`` on a target HA cannot resolve is a WARNING in HA's
        log and a normal return here; the first cut cached the value on that
        return and the de-dup then blocked every retry for the life of the
        process, so one dropped flip withdrew battery-to-grid for good
        (@RienduPre's Sessy, still on ``nom``). Now: nothing is sent when the
        select already reads ``value``; a flip is cached only once the
        select reads it; one that has not landed after ``STRATEGY_RETRY_S``
        is a MISS on the #915 read-back ledger (a Repair after three) and
        is re-sent. No-op without a strategy entity."""
        if not self._strategy_entity:
            return
        import time as _time
        if self._read_strategy() == value:
            self._strategy_landed(value)
            return
        now = _time.monotonic()
        sent_at = self._strategy_sent.get(value)
        if sent_at is not None:
            age = now - sent_at
            if age < self.STRATEGY_RETRY_S:
                return          # sent recently — the select may be catching up
            self._strategy_missed(value, age)
        # Domain-aware: real batteries expose a ``select.*`` strategy; a user
        # may also point it at an ``input_select.*`` helper. Both have
        # ``select_option``.
        domain = self._strategy_entity.split(".", 1)[0]
        if domain not in ("select", "input_select"):
            domain = "select"
        try:
            await self._hass.services.async_call(
                domain, "select_option",
                {"entity_id": self._strategy_entity, "option": value},
                blocking=True,
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("Generic battery: failed to set strategy: %s", e)
            self._strategy_sent[value] = now
            return
        self._strategy_sent[value] = now
        if self._read_strategy() == value:
            self._strategy_landed(value)
        else:
            _LOGGER.debug(
                "Generic battery: power strategy '%s' sent to %s, not "
                "reflected yet (reads %s)",
                value, self._strategy_entity, self._strategy_state_text(),
            )

    def _strategy_is_active(self) -> bool:
        """True when the setpoint will be honoured: no strategy select to
        gate it, or the select reads the active value."""
        if not self._strategy_entity:
            return True
        return self._read_strategy() == self._strategy_active

    def _setpoint_is_inert(self) -> bool:
        """(#1005) The strategy select READS a mode that ignores the setpoint.

        #978's rule — the setpoint is refused unless the strategy is active,
        and a refused setpoint spends a strike against the DEVICE for a fault
        that is not the device's — was applied to the two force paths only.
        The mutual-exclusion zero in NORMAL / OFF / LIMIT_DISCHARGE / the two
        stops kept writing, so an AC-coupled battery sitting in ``nom``
        collected a refusal per cycle: @RienduPre's 2× Sessy, 165 each in
        28 h, three of which are enough to withdraw battery-to-grid (#840).

        NOT the same test as ``_strategy_is_active``. That one asks "will a
        write land?" and answers no when the select is unreadable. This one
        asks "is the register already controlling nothing?", and an unreadable
        select cannot say so (#925). Unread → write the zero: it can only
        ever stop the battery, never start it.
        """
        if not self._strategy_entity:
            return False
        cur = self._read_strategy()
        return cur is not None and cur != self._strategy_active

    def _withhold_setpoint(self, what: str) -> None:
        """(#978) The setpoint is IGNORED unless the strategy is active, and
        a refused setpoint would spend a strike against the DEVICE for a
        fault that is the strategy's. Say so once, write nothing."""
        seen = self._strategy_state_text()
        self._last_error = (
            f"power strategy {self._strategy_entity} reads {seen}, not "
            f"'{self._strategy_active}' — {what} setpoint withheld")
        if not self._setpoint_withheld_said:
            self._setpoint_withheld_said = True
            _LOGGER.info(
                "Battery: %s reads %s, not '%s' — the %s setpoint would be "
                "refused, so SEM is not writing it (and not counting it "
                "against the device) until the strategy lands (#978)",
                self._strategy_entity, seen, self._strategy_active, what,
            )

    def verify_pending_write(self):
        """(#915) The setpoint's verdict — and, when nothing is pending
        there, the strategy select's (#978): a miss and a landing each speak
        once through the same channel, so the same Repair covers both."""
        v = super().verify_pending_write()
        if v is None and self._strategy_verdict is not None:
            v, self._strategy_verdict = self._strategy_verdict, None
        return v

    async def _enter_active_strategy(self) -> bool:
        """Capture the user's current strategy (once), mark that SEM has taken
        control, then switch to the active (API) value so the setpoint takes
        effect."""
        if self._strategy_entity and not self._took_control:
            st = self._hass.states.get(self._strategy_entity)
            cur = getattr(st, "state", None)
            # Only remember a real, restorable option — never the active value
            # itself, and not a MagicMock/unknown/unavailable.
            if (isinstance(cur, str)
                    and cur not in (self._strategy_active, "unknown",
                                    "unavailable", "")):
                self._restore_strategy = cur
            self._took_control = True
        await self._set_strategy(self._strategy_active)
        return self._strategy_is_active()

    async def _release_strategy(self) -> None:
        """Hand strategy control back. Only restore a strategy SEM actually
        CHANGED (captured the user's prior value when it switched to the
        active/API value). If SEM never took control, leave the user's
        strategy alone — forcing the configured idle default (e.g. ``eco``)
        would clobber their self-consumption mode (e.g. Sessy ``nom`` =
        zero-on-meter), which stops the battery charging from solar surplus
        (#523: battery sat idle at 20 % SOC while 1 kW of surplus exported).

        When SEM DID take control, hand it back to the captured prior mode —
        or the configured idle fallback if the prior was unreadable (never
        leave the battery stranded in API)."""
        if not self._took_control:
            return
        await self._set_strategy(self._restore_strategy or self._strategy_idle)
        self._restore_strategy = None
        self._took_control = False

    async def command_force_discharge(
        self, power_w: float, floor_soc: float,
    ) -> None:
        # Switch to the active (API) strategy BEFORE writing the setpoint —
        # an AC-coupled battery ignores the setpoint in eco/self-consumption.
        # (#978) And write NOTHING until the select reads it: a setpoint
        # into a battery still on ``nom`` is refused by the firmware and
        # would spend the device's strikes for the strategy's fault.
        if not await self._enter_active_strategy():
            self._withhold_setpoint("discharge")
            return
        await super().command_force_discharge(power_w, floor_soc)

    @property
    def max_charge_power_w(self) -> float:
        return float(self._config.get("battery_max_charge_power", 5000))

    @property
    def max_discharge_power_w(self) -> float:
        return self._max_discharge_w

    @property
    def supports_forced_charge(self) -> bool:
        # A bidirectional setpoint can charge via a negative value on the
        # same entity — no charge switch needed (#523, Sessy).
        if self._setpoint_bidirectional and self._force_discharge_entity:
            return True
        return bool(self._force_charge_switch and self._target_soc_entity)

    # ── (#955) export control is a writable number, when there is one ────
    async def command_limit_export(self, watts: float) -> None:
        ent = str(self._config.get("export_limit_entity", "") or "")
        if not ent:
            raise NotImplementedError("no export limit entity configured")
        if not ent.startswith("number."):
            raise NotImplementedError(
                f"{ent} is read-only — an export limit SEM can see but not set")
        if getattr(self, "_export_prior", None) is None:
            st = self._hass.states.get(ent)
            try:
                self._export_prior = float(getattr(st, "state", None))
            except (TypeError, ValueError):
                raise NotImplementedError(
                    f"{ent} is unreadable — nothing to restore to") from None
        w = max(0.0, float(watts))
        await self._hass.services.async_call(
            "number", "set_value", {"entity_id": ent, "value": w})
        self._last_export_limit_w = w
        self._last_export_intent = ExportIntent.LIMIT

    def export_release_recipe(self):
        ent = str(self._config.get("export_limit_entity", "") or "")
        prior = getattr(self, "_export_prior", None)
        if not ent or prior is None:
            return None
        return {"domain": "number", "service": "set_value",
                "data": {"entity_id": ent, "value": float(prior)}}

    def adopt_export_prior(self, recipe) -> None:
        try:
            self._export_prior = float((recipe or {}).get("data", {}).get("value"))
        except (TypeError, ValueError):
            self._export_prior = None
        self._last_export_limit_w = 0.0
        self._last_export_intent = ExportIntent.LIMIT

    async def command_release_export(self) -> None:
        ent = str(self._config.get("export_limit_entity", "") or "")
        prior = getattr(self, "_export_prior", None)
        if ent and prior is not None:
            await self._hass.services.async_call(
                "number", "set_value", {"entity_id": ent, "value": float(prior)})
        self._export_prior = None
        self._last_export_limit_w = None
        self._last_export_intent = ExportIntent.RELEASE

    def export_dry_run(self, intent, watts: float) -> dict:
        """(#955) The number write that WOULD happen — see the base class."""
        ent = str(self._config.get("export_limit_entity", "") or "")
        if not ent:
            return {"service": None, "data": None, "why": "no export limit entity configured"}
        if not ent.startswith("number."):
            return {"service": None, "data": None,
                    "why": f"{ent} is read-only — an export limit SEM can see but not set"}
        prior = getattr(self, "_export_prior", None)
        if prior is None:
            try:
                prior = float(getattr(self._hass.states.get(ent), "state", None))
            except (TypeError, ValueError):
                return {"service": None, "data": None,
                        "why": f"{ent} is unreadable — nothing to restore to"}
        value = max(0.0, float(watts)) if intent is ExportIntent.LIMIT else float(prior)
        return {"service": "number.set_value",
                "data": {"entity_id": ent, "value": value}, "why": None}

    async def command_normal(self) -> None:
        await self._zero_setpoint()  # #523 mutual exclusion (#1005)
        # AC-coupled (Sessy): self-consumption is its OWN power strategy
        # (``nom`` = zero-on-meter), NOT the setpoint. Actively set it so a
        # battery left in eco/api/idle by a prior mode returns to self-
        # consuming — #523 (Rien): Auto / Self-consumption used to leave the
        # Sessy stuck in ``eco`` (which doesn't self-consume). De-dup'd, so a
        # battery already in ``nom`` isn't re-written.
        await self._set_strategy(self._strategy_self_consume)
        await self._apply_discharge_limit(self._max_discharge_w)
        self._last_intent = BatteryIntent.NORMAL

    async def command_off(self) -> None:
        """#523 (Rien): a Sessy in 'Off' should sit IDLE (no charge/discharge),
        not self-consume and not stay in ``eco``. Set the idle power strategy
        and zero the setpoint, then stay silent (one-shot like the base). A
        non-AC-coupled battery (no strategy entity) has no native idle — defer
        to the base hands-off behaviour."""
        if self._last_intent is BatteryIntent.OFF:
            return
        if not self._strategy_entity:
            await super().command_off()
            return
        await self._zero_setpoint()  # (#1005)
        await self._set_strategy(self._strategy_off)
        self._last_intent = BatteryIntent.OFF

    async def command_limit_discharge(self, watts: float) -> None:
        await self._zero_setpoint()  # #523 mutual exclusion (#1005)
        await self._set_strategy(self._strategy_self_consume)
        watts = max(0.0, min(watts, self._max_discharge_w))
        if (self._last_discharge_limit_w >= 0
                and abs(watts - self._last_discharge_limit_w) < 100.0):
            self._last_intent = BatteryIntent.LIMIT_DISCHARGE
            return
        await self._apply_discharge_limit(watts)
        self._last_intent = BatteryIntent.LIMIT_DISCHARGE

    async def command_force_charge(
        self, target_soc: float, charge_power_w: float, duration_min: int,
    ) -> None:
        # #523 AC-coupled bidirectional setpoint (Sessy): charge = NEGATIVE
        # power on the same setpoint entity. Set the active strategy first
        # (the setpoint is ignored in self-consumption mode) then write the
        # negative value — the mirror of command_force_discharge.
        if self._setpoint_bidirectional and self._force_discharge_entity:
            if not await self._enter_active_strategy():
                self._withhold_setpoint("charge")           # (#978)
                return
            watts = max(0.0, min(float(charge_power_w), self.max_charge_power_w))
            ok = await self._write_force_discharge(-watts)
            if ok:
                self._last_error = None
                self._last_intent = BatteryIntent.FORCE_CHARGE
            else:
                self._last_error = "bidirectional charge write failed"
                # _last_intent intentionally NOT updated — retry next cycle (#589)
            return
        ok_zero = await self._zero_setpoint()  # #523 mutual exclusion (#1005)
        if not ok_zero:
            self._last_error = "mutual-exclusion zero-write failed"
            return
        if self._charge_adapter is None:
            _LOGGER.warning(
                "GenericBatteryAdapter: no forced-charge backend — "
                "command_force_charge ignored",
            )
            return
        from .force_charge import ChargeCommand, ChargeCommandStatus
        cmd = ChargeCommand(
            target_soc=target_soc,
            max_power_w=charge_power_w,
            duration_minutes=duration_min,
        )
        status = await self._charge_adapter.start_forced_charge(cmd)
        if status.status is ChargeCommandStatus.FAILED:
            self._last_error = f"start_forced_charge failed: {status.message}"
            # _last_intent intentionally NOT updated — retry next cycle (#589)
        else:
            self._last_error = None
            self._last_intent = BatteryIntent.FORCE_CHARGE

    async def command_stop_force_charge(self) -> None:
        if self._force_charge_already_stopped():
            return  # (#757) already stopped — a repeat is noise, not a command
        ok = await self._zero_setpoint()  # #523 mutual exclusion (#1005)
        # Back to self-consumption (nom), not the old eco/idle release.
        await self._set_strategy(self._strategy_self_consume)
        if self._charge_adapter is not None:
            from .force_charge import ChargeCommandStatus
            status = await self._charge_adapter.stop_forced_charge()
            # #757 honest retry: a failed stop must not record the intent, or
            # the guard above would suppress the retry (#589 class 4).
            if status.status is ChargeCommandStatus.FAILED:
                self._last_error = f"stop_forced_charge failed: {status.message}"
                return
        if not ok:
            self._last_error = "mutual-exclusion zero-write failed on stop"
            return
        self._last_error = None
        self._last_intent = BatteryIntent.STOP_FORCE_CHARGE

    async def _apply_discharge_limit(self, watts: float) -> None:
        if not self._discharge_control_entity:
            self._last_discharge_limit_w = watts
            return
        ok, wrote = await async_write_power_setpoint_verbose(
            self._hass,
            self._discharge_control_entity,
            watts,
            context="Generic battery discharge limit",
        )
        if ok:
            self._last_discharge_limit_w = watts
            if wrote:
                # only a write that went OUT is judged; the same-value skip
                # is not a write and must not re-arm the grace (06.09 audit)
                self._note_pending_write(self._discharge_control_entity, watts)

