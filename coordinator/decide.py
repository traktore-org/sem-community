"""Pure ``decide(view) → ChargerDecision`` (Step 3 of the
arch/multi-charger-primary migration).

One pure function per cycle per charger. Replaces the chain
``_determine_charging_strategy + _build_charging_context +
ChargingStateMachine.update_state`` that pre-architecture
threaded through three modules with implicit contracts.

Properties of this design:

1. **Pure** — no ``self``, no HA calls, no clock reads. Input
   ``ChargerView``, output ``ChargerDecision``. Same input always
   produces the same output (modulo the explicit time field on
   ``FleetContext.is_night``).

2. **One mode = one strategy class** — the five ``EV_CHARGE_MODES``
   each get a ``ModeStrategy`` subclass. The strategy/state-machine
   disagreement class (#346) cannot exist by construction: each
   mode owns its full decision path.

3. **No re-derivation of mode** — ``view.mode`` is already
   resolved upstream via ``effective_charge_mode_for``. The mode
   strategies don't re-read config to determine mode.

4. **Conservation by construction** — every code path returns a
   ``ChargerDecision`` (no implicit fallthrough). The conservation
   tests in Step 8 verify intent-vs-outcome agreement.

This module does NOT yet replace ``_determine_charging_strategy``
in production — Step 4 wires the adapter, Step 6 wires the data
model. Until then this is exercised only by its own tests.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Dict, Optional, Type

from .charger_types import (
    ChargerDecision,
    ChargerIntent,
    ChargerView,
)

_LOGGER = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Helpers — shared zone math (pure, no state)
# ─────────────────────────────────────────────────────────────────

def soc_zone(soc: float, auto_start: float, buffer: float, priority: float) -> int:
    """Map SOC to zone number.

    Pre-architecture this lived as ``SEMCoordinator._raw_zone`` and
    was paired with ``_debounce_zone`` for stateful smoothing. The
    pure ``decide`` doesn't debounce here — that's a coordinator
    concern (the coordinator pre-debounces SOC before building the
    view, or wraps ``decide()`` in a debounce shim).

    Returns 1..4. Higher = more battery available.
    """
    if soc >= auto_start:
        return 4
    if soc >= buffer:
        return 3
    if soc >= priority:
        return 2
    return 1


def self_consumption_surplus_w(view: ChargerView) -> float:
    """Pure surplus = solar - home (- battery_charge unless Zone 4)
    (- solar_committed_w by higher-priority chargers).

    Ports ``_self_consumption_strategy`` from
    ``coordinator.py:2787``. Battery charges first below
    ``auto_start_soc``; above it, leftover solar redirects to EV.

    Step 6 multi-charger correctness: ``solar_committed_w`` is
    subtracted so the second charger in the per-charger loop sees
    only the surplus NOT already claimed by charger A. Prevents
    over-allocation of solar in multi-charger fleets.
    """
    f = view.fleet
    available = f.solar_w - f.home_w - f.solar_committed_w
    if f.battery_soc < f.auto_start_soc:
        available -= f.battery_charge_w
    return max(0.0, available)


def battery_assist_budget_w(view: ChargerView) -> float:
    """Budget for Zone 3/4 battery-assist charging.

    In ``min_plus_solar`` / ``solar_plus_cheap`` / ``always_max``
    modes (NOT solar_only / off), when the home battery is
    high enough (Zone 3 or 4), it can discharge to bridge the gap
    between solar surplus and EV demand. The budget here is:

      Zone 4 (SOC ≥ auto_start_soc): solar - home + usable_battery
        usable_battery = (SOC - floor_soc) / 100 × capacity, scaled
        per-cycle so we don't drain in one cycle. Bound by
        battery_discharge_w (the physical max the battery is
        currently providing).

      Zone 3 (buffer_soc ≤ SOC < auto_start_soc): same formula but
        only when forecast shows tomorrow has plenty of sun (legacy
        ``_zone_based_strategy`` line 2742-2750 — forecast check
        deferred to Step 5 here; for now we treat Zone 3 same as
        Zone 4).

      Zone 1/2: no battery assist. Return surplus only.
    """
    f = view.fleet
    surplus = self_consumption_surplus_w(view)
    zone = soc_zone(f.battery_soc, f.auto_start_soc, f.buffer_soc, f.priority_soc)
    if zone < 3:
        return surplus
    # Zone 3 or 4: add the battery's actual current discharge to
    # the EV budget. (Don't speculate on future discharge; use what
    # the inverter is reporting right now.)
    return surplus + f.battery_discharge_w


def amps_from_watts(watts: float, phases: int, voltage: int) -> int:
    """Watts → whole amps (round down). The actuator (Step 4)
    clamps to ``[min_current_a, max_current_a]``."""
    denom = max(1, phases * voltage)
    return int(watts // denom)


# ─────────────────────────────────────────────────────────────────
# Mode strategy protocol
# ─────────────────────────────────────────────────────────────────

class ModeStrategy(ABC):
    """One ``decide`` implementation per charge mode.

    Subclasses are pure: no ``self`` state, no instance attributes.
    Instantiated once at module import time, called by ``decide()``
    for every (charger, cycle) tuple.
    """

    @abstractmethod
    def decide(self, view: ChargerView) -> ChargerDecision:
        """Compute the per-cycle decision for this mode."""


# ─────────────────────────────────────────────────────────────────
# off — explicit user disable
# ─────────────────────────────────────────────────────────────────

class OffMode(ModeStrategy):
    """No charging, ever. Adapter calls ``command_disable()`` so
    KEBA-class firmware actually opens the contactor (#315)."""

    def decide(self, view: ChargerView) -> ChargerDecision:
        return ChargerDecision(
            charger_id=view.power.charger_id,
            mode="off",
            intent=ChargerIntent.DISABLE,
            commanded_amps=0,
            budget_w=0.0,
            reason="off mode — user-explicit disable",
        )


# ─────────────────────────────────────────────────────────────────
# always_max — full power regardless of source
# ─────────────────────────────────────────────────────────────────

class AlwaysMaxMode(ModeStrategy):
    """Charge at hardware max. Grid backfill expected."""

    def decide(self, view: ChargerView) -> ChargerDecision:
        if not view.power.connected:
            return ChargerDecision(
                charger_id=view.power.charger_id,
                mode="always_max",
                intent=ChargerIntent.IDLE,
                reason="always_max mode but EV disconnected",
            )
        return ChargerDecision(
            charger_id=view.power.charger_id,
            mode="always_max",
            intent=ChargerIntent.CHARGE_MAX,
            commanded_amps=0,  # adapter resolves from device.max_current
            budget_w=0.0,  # not budget-limited
            reason="always_max mode — charge at hardware maximum",
        )


# ─────────────────────────────────────────────────────────────────
# solar_only — strict surplus, never grid import
# ─────────────────────────────────────────────────────────────────

class SolarOnlyMode(ModeStrategy):
    """Charge only from solar surplus. Never imports grid for EV.

    Below ``min_power_threshold`` (the charger's
    ``min_current_a * phases * voltage``), the actuator must idle
    rather than command sub-min amps — KEBA would reject and
    self-charge (#353). Decision returns ``IDLE`` with
    ``budget_w`` set so the dashboard shows the available surplus.
    """

    MIN_AMPS_FALLBACK = 6
    PHASES_FALLBACK = 3
    VOLTAGE_FALLBACK = 230

    def decide(self, view: ChargerView) -> ChargerDecision:
        f = view.fleet
        cid = view.power.charger_id

        if not view.power.connected:
            return ChargerDecision(
                charger_id=cid, mode="solar_only",
                intent=ChargerIntent.IDLE,
                reason="solar_only mode but EV disconnected",
            )

        # No meaningful solar → idle. At night this fires immediately
        # (solar=0) producing the #346-correct behaviour: solar_only
        # at night never imports grid.
        if f.solar_w < f.min_solar_w:
            return ChargerDecision(
                charger_id=cid, mode="solar_only",
                intent=ChargerIntent.IDLE,
                reason=(
                    f"solar_only: solar={f.solar_w:.0f}W < "
                    f"{f.min_solar_w:.0f}W threshold"
                ),
            )

        # Compute surplus available to EV
        surplus_w = self_consumption_surplus_w(view)

        # The actuator/adapter knows the real min — for the decide
        # we use a sensible fallback (6 A × 3 × 230 V = 4140 W) so
        # the decision is correct even without the adapter wired in.
        # Step 4 will route min through the adapter.
        cfg = view.config
        min_amps = int(cfg.get("ev_min_current", self.MIN_AMPS_FALLBACK)) \
            if isinstance(cfg, dict) else self.MIN_AMPS_FALLBACK
        phases = int(cfg.get("ev_phases", self.PHASES_FALLBACK)) \
            if isinstance(cfg, dict) else self.PHASES_FALLBACK
        voltage = int(cfg.get("ev_voltage", self.VOLTAGE_FALLBACK)) \
            if isinstance(cfg, dict) else self.VOLTAGE_FALLBACK
        min_w = min_amps * phases * voltage

        if surplus_w < min_w:
            return ChargerDecision(
                charger_id=cid, mode="solar_only",
                intent=ChargerIntent.IDLE,
                budget_w=surplus_w,
                reason=(
                    f"solar_only: surplus={surplus_w:.0f}W < "
                    f"min={min_w}W (={min_amps}A) — idle"
                ),
            )

        amps = max(min_amps, amps_from_watts(surplus_w, phases, voltage))
        return ChargerDecision(
            charger_id=cid, mode="solar_only",
            intent=ChargerIntent.CHARGE_AT_AMPS,
            commanded_amps=amps, budget_w=surplus_w,
            reason=(
                f"solar_only: surplus={surplus_w:.0f}W → {amps}A "
                f"(solar={f.solar_w:.0f}W, home={f.home_w:.0f}W, "
                f"batt_chg={f.battery_charge_w:.0f}W)"
            ),
        )


# ─────────────────────────────────────────────────────────────────
# min_plus_solar — solar surplus + Min floor at night
# ─────────────────────────────────────────────────────────────────

class MinPlusSolarMode(ModeStrategy):
    """Daytime: zone-aware surplus (same as solar_only when SOC
    high enough). Night: top up to ``target_kwh`` Min floor using
    grid (#245).
    """

    def decide(self, view: ChargerView) -> ChargerDecision:
        f = view.fleet
        cid = view.power.charger_id

        if not view.power.connected:
            return ChargerDecision(
                charger_id=cid, mode="min_plus_solar",
                intent=ChargerIntent.IDLE,
                reason="min_plus_solar but EV disconnected",
            )

        if f.is_night:
            return self._decide_night(view)
        return self._decide_day(view)

    def _decide_night(self, view: ChargerView) -> ChargerDecision:
        cid = view.power.charger_id

        # Already at Min — idle.
        if view.target_kwh is not None and view.target_kwh <= 0.1:
            return ChargerDecision(
                charger_id=cid, mode="min_plus_solar",
                intent=ChargerIntent.IDLE,
                reason=(
                    f"min_plus_solar night: target reached "
                    f"(remaining={view.target_kwh:.2f} kWh)"
                ),
            )

        cfg = view.config if isinstance(view.config, dict) else {}
        min_amps = int(cfg.get("ev_min_current", 6))
        max_amps = int(cfg.get("ev_max_current", 32))

        # Deadline override (#246) — the planner pre-computed the
        # required current and put it on the view. If the deadline
        # is active, use it as the floor.
        if view.deadline_amps > 0:
            amps = min(max_amps, max(min_amps, view.deadline_amps))
            return ChargerDecision(
                charger_id=cid, mode="min_plus_solar",
                intent=ChargerIntent.CHARGE_AT_AMPS,
                commanded_amps=amps,
                reason=(
                    f"min_plus_solar night: deadline floor {amps}A, "
                    f"remaining {view.target_kwh:.1f} kWh"
                ),
            )

        # Plain night top-up at Min current (the floor).
        remaining_str = (
            f"{view.target_kwh:.1f}" if view.target_kwh is not None else "?"
        )
        return ChargerDecision(
            charger_id=cid, mode="min_plus_solar",
            intent=ChargerIntent.CHARGE_AT_AMPS,
            commanded_amps=min_amps,
            reason=(
                f"min_plus_solar night: top-up at {min_amps}A, "
                f"remaining {remaining_str} kWh"
            ),
        )

    def _decide_day(self, view: ChargerView) -> ChargerDecision:
        """Daytime min_plus_solar: Zone-aware battery assist on top
        of solar surplus. Zone 4 (SOC≥90) drains battery to EV;
        Zone 3 (SOC≥70) discharges battery if it's already; Zone 2
        is pure solar (same as solar_only); Zone 1 idles."""
        f = view.fleet
        cid = view.power.charger_id
        if not view.power.connected:
            return ChargerDecision(
                charger_id=cid, mode="min_plus_solar",
                intent=ChargerIntent.IDLE,
                reason="min_plus_solar day: EV disconnected",
            )
        zone = soc_zone(f.battery_soc, f.auto_start_soc, f.buffer_soc, f.priority_soc)
        # Zone 1: battery priority — never charge EV from anywhere
        # when battery is below priority_soc.
        if zone == 1:
            return ChargerDecision(
                charger_id=cid, mode="min_plus_solar",
                intent=ChargerIntent.IDLE,
                reason=(
                    f"min_plus_solar day: Zone 1 "
                    f"(SOC={f.battery_soc:.0f}% < priority="
                    f"{f.priority_soc:.0f}%) — battery priority"
                ),
            )
        # Zone 2: pure solar (same as solar_only).
        if zone == 2:
            return _SOLAR_ONLY.decide(view)
        # Zone 3 / 4: battery-assist budget includes battery_discharge.
        budget_w = battery_assist_budget_w(view)
        cfg = view.config if isinstance(view.config, dict) else {}
        min_amps = int(cfg.get("ev_min_current", 6))
        phases = int(cfg.get("ev_phases", 3))
        voltage = int(cfg.get("ev_voltage", 230))
        min_w = min_amps * phases * voltage
        if budget_w < min_w:
            return ChargerDecision(
                charger_id=cid, mode="min_plus_solar",
                intent=ChargerIntent.IDLE,
                budget_w=budget_w,
                reason=(
                    f"min_plus_solar day Zone {zone}: budget="
                    f"{budget_w:.0f}W < min={min_w}W — idle"
                ),
            )
        max_amps = int(cfg.get("ev_max_current", 32))
        amps = max(min_amps, min(max_amps, amps_from_watts(budget_w, phases, voltage)))
        return ChargerDecision(
            charger_id=cid, mode="min_plus_solar",
            intent=ChargerIntent.CHARGE_AT_AMPS,
            commanded_amps=amps, budget_w=budget_w,
            reason=(
                f"min_plus_solar day Zone {zone}: budget={budget_w:.0f}W "
                f"→ {amps}A (solar={f.solar_w:.0f}W + battery_dis="
                f"{f.battery_discharge_w:.0f}W)"
            ),
        )


# ─────────────────────────────────────────────────────────────────
# solar_plus_cheap — solar + cheap-tariff windows at night
# ─────────────────────────────────────────────────────────────────

class SolarPlusCheapMode(ModeStrategy):
    """During day: solar_only behaviour, but pauses during
    expensive tariff windows. At night: charge during the
    cheapest hours only (#247).
    """

    EXPENSIVE_LEVELS = frozenset({"expensive", "very_expensive"})

    def decide(self, view: ChargerView) -> ChargerDecision:
        f = view.fleet
        cid = view.power.charger_id

        if not view.power.connected:
            return ChargerDecision(
                charger_id=cid, mode="solar_plus_cheap",
                intent=ChargerIntent.IDLE,
                reason="solar_plus_cheap but EV disconnected",
            )

        # Day during expensive tariff window → fall back to pure
        # solar_only behaviour (the #247 daytime pause).
        if not f.is_night and f.tariff_level in self.EXPENSIVE_LEVELS:
            decision = _SOLAR_ONLY.decide(view)
            return ChargerDecision(
                charger_id=decision.charger_id,
                mode="solar_plus_cheap",
                intent=decision.intent,
                commanded_amps=decision.commanded_amps,
                budget_w=decision.budget_w,
                reason=(
                    f"solar_plus_cheap day: tariff={f.tariff_level} "
                    f"→ pausing grid imports — {decision.reason}"
                ),
            )

        # Day, normal/cheap tariff: solar surplus only (same as
        # min_plus_solar day path).
        if not f.is_night:
            return _SOLAR_ONLY.decide(view)

        # Night → defers to the night planner's tariff_wait flag.
        # This is the only mode that consults ``tariff_wait``.
        cfg = view.config if isinstance(view.config, dict) else {}
        if cfg.get("_tariff_wait", False):
            return ChargerDecision(
                charger_id=cid, mode="solar_plus_cheap",
                intent=ChargerIntent.IDLE,
                reason="solar_plus_cheap night: waiting for cheaper hour",
            )

        # Cheap window OR Min floor must be met — top up at Min.
        return _MIN_PLUS_SOLAR._decide_night(view)


# ─────────────────────────────────────────────────────────────────
# Dispatcher
# ─────────────────────────────────────────────────────────────────

_OFF = OffMode()
_ALWAYS_MAX = AlwaysMaxMode()
_SOLAR_ONLY = SolarOnlyMode()
_MIN_PLUS_SOLAR = MinPlusSolarMode()
_SOLAR_PLUS_CHEAP = SolarPlusCheapMode()

MODE_STRATEGIES: Dict[str, ModeStrategy] = {
    "off": _OFF,
    "always_max": _ALWAYS_MAX,
    "solar_only": _SOLAR_ONLY,
    "min_plus_solar": _MIN_PLUS_SOLAR,
    "solar_plus_cheap": _SOLAR_PLUS_CHEAP,
}


def decide(view: ChargerView) -> ChargerDecision:
    """Compute the per-charger per-cycle decision.

    Pure function. Dispatches by ``view.mode`` to the matching
    :class:`ModeStrategy`. Unknown modes fall back to ``off``
    (DISABLE) — loud failure mode is preferable to charging from
    grid when the user didn't ask for it.
    """
    strategy = MODE_STRATEGIES.get(view.mode)
    if strategy is None:
        _LOGGER.error(
            "decide: unknown mode %r for charger %s — falling back to OFF",
            view.mode, view.power.charger_id,
        )
        return _OFF.decide(view)
    return strategy.decide(view)
