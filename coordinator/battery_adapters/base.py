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

    @property
    def supports_forced_discharge(self) -> bool:
        """True when a forcible-discharge control entity is configured
        (#523) — brand-agnostic battery→grid arbitrage. No entity → the
        actuator drops FORCE_DISCHARGE."""
        return bool(self._force_discharge_entity)

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
            _LOGGER.warning(
                "Battery: failed to set forcible discharge: %s", e,
            )
            return False
