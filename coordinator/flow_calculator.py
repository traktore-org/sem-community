"""Power and energy flow calculation module for SEM coordinator.

This module calculates how energy flows between sources and destinations
using proportional allocation. This is more physically accurate than
priority-based allocation because electricity naturally mixes.

Sources: Solar, Grid Import, Battery Discharge
Destinations: Home, EV, Battery Charge, Grid Export
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date
from typing import Dict, Optional

from homeassistant.util import dt as dt_util

from .types import (
    ChargerEnergyFlows,
    ChargerFlows,
    EnergyFlows,
    EnergyTotals,
    PowerFlows,
    PowerReadings,
    StringEnergy,
)

_LOGGER = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────────────
# Canonical EV-budget calculation — the unified source of truth (#282)
#
# Background: SEM historically had THREE separate "how many watts can the
# EV draw right now" calculations that could (and did) disagree:
#   B1 coordinator.py:898 `available_power` → published sensors
#   B2 coordinator.py:2589 `ev_budget` in `_build_charging_context`
#                                          → state machine input
#   B3 ev_control.py:440-452 `budget_w` → the actuator
#
# Live evidence captured 2026-05-29 (PROD): state machine returned
# SOLAR_CHARGING_ACTIVE because its budget view included battery_redirect
# while the actuator's budget view didn't, leaving the dashboard label
# claiming "Charging active" while the car drew 0 W. Commit 1a9b3c9
# installed a sensor-level demotion guard as the cosmetic stopgap.
#
# This module defines the replacement: ONE method, ONE dataclass, used
# by all three former call sites. See docs/plans/2026-05-29_ev_budget_unification.md
# for the four-phase rollout. Phase A landed this code purely additively.
# ───────────────────────────────────────────────────────────────────────


class EVBudgetStrategy:
    """Strategy values the canonical budget dispatches on.

    These are the canonical names. The coordinator's legacy
    ``_determine_charging_strategy`` returns strings that map onto these
    via ``_strategy_from_legacy`` in coordinator.py (Phase B). The
    distinction between SOLAR_ONLY (Zone 3, redirect allowed) and
    SELF_CONSUMPTION (Zone 2, redirect denied) is now first-class — the
    legacy code conflated both as ``"solar_only"`` and used substring
    matching on the human-readable ``charging_strategy_reason`` to tell
    them apart, which was brittle and the proximate cause of the
    three-way disagreement (#282).
    """

    IDLE = "idle"
    """EV gets nothing. Strategy decided to not charge this cycle."""

    SELF_CONSUMPTION = "self_consumption"
    """Zone 2: surplus only, NO battery-charge redirect to EV. Battery
    still 'owns' any surplus while SOC is in the priority band."""

    SOLAR_ONLY = "solar_only"
    """Zone 3: solar surplus + forecast-aware battery-charge redirect."""

    BATTERY_ASSIST = "battery_assist"
    """Zone 4-ish: surplus + redirect + active battery DISCHARGE to EV.
    The battery is willing to power the EV directly because forecast
    or SOC makes that the right trade."""

    MIN_PV = "min_pv"
    """User asked: 'guarantee Min current, add surplus on top.' The
    canonical budget floors at ``min_power_floor_w``."""

    NOW = "now"
    """User asked: 'charge at maximum right now, regardless of solar.'
    Budget is the charger's full nameplate power; grid backfill is
    expected and intentional."""


@dataclass
class EVBudget:
    """Single source of truth for what the EV is allowed to draw right now.

    All consumers (published sensors, state machine, actuator) read from
    instances of this class. The decomposition exists so callers can
    introspect "where did this watt come from" without re-deriving:

    Attributes:
        strategy: The strategy this budget was computed for (see
            ``EVBudgetStrategy``).
        solar_surplus: ``max(0, solar - home - batt_charge)``. Always
            the "free" part — what solar could deliver without battery
            help. Same across all strategies (except ``IDLE`` and
            ``NOW``, where it is 0 because the strategy makes the
            surplus irrelevant).
        battery_redirect: How much battery-charge power can be diverted
            to the EV (forecast/SOC aware). Non-zero for ``SOLAR_ONLY``
            and ``BATTERY_ASSIST`` and ``MIN_PV``. Always zero for
            ``SELF_CONSUMPTION`` (Zone 2 — battery has priority).
        battery_assist: How much the battery can actively DISCHARGE to
            the EV. Non-zero only for ``BATTERY_ASSIST``.
        net_w: ``solar_surplus + battery_redirect + battery_assist``,
            clamped to ``>= 0``, with strategy-specific overrides
            applied:
              - IDLE: 0
              - MIN_PV: ``max(min_power_floor_w, sum)``
              - NOW: ``override_max_w`` (typically charger nameplate)
            This is the SETPOINT (target total watts) the charger is
            allowed to draw.
        current_a: ``net_w`` expressed as charger current (integer
            amps). Uses ``math.floor`` so the charger stays strictly
            under the budget — round-to-nearest was the source of the
            0.5 A grid-leak boundary issue, fixed in
            ``calculate_charging_current`` and preserved here. Clamped
            to ``[0, 16]`` (16 A is the SEM-supported per-phase limit).
    """

    strategy: str
    solar_surplus: float
    battery_redirect: float
    battery_assist: float
    net_w: float
    current_a: int

    def __post_init__(self):
        # Defensive: protect downstream from negative leaks.
        if self.net_w < 0:
            self.net_w = 0.0
        if self.current_a < 0:
            self.current_a = 0


def battery_redirect_w(
    battery_charge_w: float,
    battery_soc: float,
    battery_capacity_kwh: float,
    forecast_remaining_kwh: float,
) -> float:
    """How much battery charge power can be redirected to EV.

    Forecast-aware: if the remaining solar today can still refill the
    battery, divert some of the current battery_charge_w to the EV
    instead — proportional to how much "extra" forecast exists beyond
    the battery's need. Without a forecast, fall back to the 80% SOC
    threshold (battery full enough that redirect is safe).

    Module-level (not a method on FlowCalculator) so the strategy
    decision path in ``decide.py`` can compute the same redirect for
    the intent decision WITHOUT instantiating a FlowCalculator —
    avoiding the regression where ``SolarOnlyMode.decide()`` checked
    bare surplus against the charger min, returned IDLE, and so
    ``calculate_canonical_ev_budget(SOLAR_ONLY)``'s redirect branch
    was never reached even though it had a viable budget. See the
    triage in ``tests/test_scenarios.py::_XFAIL_DRIFT`` for the
    scenario this restores.
    """
    if battery_charge_w <= 0:
        return 0

    battery_need_kwh = max(0, (100 - battery_soc) / 100 * battery_capacity_kwh)

    if forecast_remaining_kwh > 0:
        # Forecast available: redirect proportional to excess forecast
        if forecast_remaining_kwh >= battery_need_kwh and battery_need_kwh > 0:
            # Forecast covers battery — redirect proportionally.
            # Use max(0.05, ratio) so we always redirect at least 5%
            # at the exact boundary (forecast == battery_need gives
            # ratio=0 without this).
            ratio = min(1.0, 1.0 - battery_need_kwh / forecast_remaining_kwh)
            return battery_charge_w * max(0.05, ratio)
        elif battery_need_kwh <= 0.5:
            # Battery nearly full — redirect all
            return battery_charge_w
        else:
            # Forecast can't cover battery need — keep charging
            return 0
    else:
        # No forecast — SOC threshold fallback
        if battery_soc >= 80:
            return battery_charge_w  # Battery full enough, redirect all
        return 0


class FlowCalculator:
    """Calculates power and energy flows using proportional allocation."""

    def __init__(self):
        """Initialize flow calculator."""
        # Accumulators for energy flows (reset daily)
        self._flow_accumulators: Dict[str, float] = {}
        # v1.6.15: per-charger EV flow accumulators (kWh), reset daily
        # alongside ``_flow_accumulators``. Outer key is the charger id,
        # inner key is one of ``_PER_CHARGER_ACCUMULATED_ATTRS``. Empty
        # in single-charger setups (no per-charger PowerFlows entries
        # arrive at ``integrate_energy_flows``).
        self._per_charger_accumulators: Dict[str, Dict[str, float]] = {}
        # v1.7.0 / #312: per-PV-string daily kWh accumulators, reset
        # daily alongside the fleet + per-charger ones. Outer key is
        # the string slot label (``"pv1"``, ``"pv2"``, …), inner key
        # is ``"energy_kwh"`` (kept as a dict for symmetry with the
        # per-charger schema). Empty in single-string setups.
        self._per_string_accumulators: Dict[str, Dict[str, float]] = {}
        self._current_date: date = dt_util.now().date()

    def calculate_power_flows(self, power: PowerReadings) -> PowerFlows:
        """Calculate instantaneous power flows using priority-based allocation (#349).

        Sources drain in priority order — ``solar → battery_discharge →
        grid_import`` (best-for-user first). Destinations are served in
        priority order — ``home → ev → battery_charge → grid_export``.

        Pre-#349 SEM used proportional allocation: every source split
        across every destination by demand percentage. That model
        broke user intent whenever multiple consumers ran in parallel
        — on HA-PROD 2026-06-01 the dashboard showed 6.6 kWh of
        grid_to_ev on a day the EV was actually 91 % solar (the home
        battery was charging from grid; proportional allocation
        attributed a slice of that grid pull to the EV). It also broke
        algebraic conservation in supply ≠ demand cycles (scenario:
        solar=5000 W, home=500 W, grid_export=0 mis-specified →
        solar_to_home overshoots home demand).

        Priority allocation matches user intent AND conserves on
        both sides for every cycle:

            sum(flows_to_dest) = dest_demand   for every destination
            sum(flows_from_src) = src_supply   for every source

        when the input ``power`` is balanced (supply == demand). When
        the input is unbalanced (sensor lag, transient mismatch), the
        algorithm degrades gracefully — destinations are served up to
        their demand from the available supplies in priority order;
        leftover supply lands in ``solar_to_grid`` (acting as the
        slack variable) and leftover demand reads zero on the missing
        rows. Pinned in ``tests/test_349_flow_priority_attribution.py``.

        v1.6.9 multi-charger split + v1.7.0 per-string passthrough
        (see below the allocator) are unchanged.
        """
        flows = PowerFlows()

        # Get source powers (priority order: solar > battery > grid)
        solar = power.solar_power
        battery_discharge = power.battery_discharge_power
        grid_import = power.grid_import_power

        # Get destination powers (priority order: home > ev > battery_charge > grid_export)
        home = power.home_consumption_power
        # FLEET-READ: fleet EV demand drives the destination allocation;
        # per-charger split happens below via ``power.ev_power_per_charger``.
        ev = power.ev_power
        battery_charge = power.battery_charge_power
        grid_export = power.grid_export_power

        # Skip if everything's idle (avoids spurious zero-flow rows).
        if (solar + battery_discharge + grid_import < 1
                and home + ev + battery_charge + grid_export < 1):
            return flows

        # Greedy priority allocator. Each (source, destination) pair
        # consumes ``min(source_left, dest_left)``; the chosen field on
        # ``flows`` is set; both counters tick down. ``solar_to_battery``
        # / ``solar_to_grid`` / etc. roll up the leftovers naturally.
        sources_left = {
            "solar": solar,
            "battery": battery_discharge,
            "grid": grid_import,
        }
        destinations_left = {
            "home": home,
            "ev": ev,
            "battery_charge": battery_charge,
            "grid_export": grid_export,
        }

        # Allowed (source, destination) pairs. The omissions are
        # deliberate:
        # - ``grid → grid_export``: a flow-meter sign artefact, not real.
        # - ``battery_discharge → battery_charge``: a battery can't
        #   simultaneously discharge and charge itself.
        # - ``battery_discharge → grid_export``: SEM doesn't support
        #   battery-to-grid arbitrage (the few installs that do would
        #   need a ``battery_to_grid`` flow field — out of scope here).
        #   In a normal install solar/battery sign-conflicts caused by
        #   sensor lag are rare; if they happen the leftover battery
        #   discharge stays unattributed for that cycle, which is a
        #   small honest under-count rather than a wrong attribution.
        pairs = [
            ("solar", "home"),
            ("solar", "ev"),
            ("solar", "battery_charge"),
            ("solar", "grid_export"),
            ("battery", "home"),
            ("battery", "ev"),
            ("grid", "home"),
            ("grid", "ev"),
            ("grid", "battery_charge"),
        ]
        flow_field = {
            ("solar", "home"): "solar_to_home",
            ("solar", "ev"): "solar_to_ev",
            ("solar", "battery_charge"): "solar_to_battery",
            ("solar", "grid_export"): "solar_to_grid",
            ("battery", "home"): "battery_to_home",
            ("battery", "ev"): "battery_to_ev",
            ("grid", "home"): "grid_to_home",
            ("grid", "ev"): "grid_to_ev",
            ("grid", "battery_charge"): "grid_to_battery",
        }
        for src, dst in pairs:
            avail = sources_left[src]
            need = destinations_left[dst]
            if avail <= 0 or need <= 0:
                continue
            delivered = min(avail, need)
            field = flow_field[(src, dst)]
            setattr(flows, field, round(delivered, 1))
            sources_left[src] = avail - delivered
            destinations_left[dst] = need - delivered

        # v1.6.9 per-charger attribution. When per-charger draws are
        # available, split the fleet-level EV flows by each charger's
        # share of the total EV draw. Math: ``charger_share = c_draw /
        # ev_total`` × fleet ``flows.*_to_ev``. Sum invariant holds by
        # v1.7.0 / #312: carry per-string raw power onto the flows
        # object so ``integrate_energy_flows`` can accumulate kWh per
        # string without an API change. Strings are SOURCES so there's
        # no destination attribution to compute — just pass-through.
        if power.solar_power_per_string:
            flows.solar_per_string = dict(power.solar_power_per_string)

        # Per-charger native attribution (Step 5 of arch/
        # multi-charger-primary, addresses #351 finding M3).
        #
        # Pre-Step-5 SEM did proportional fraction-of-fleet:
        # ``flows.per_charger[cid].solar_to_ev = flows.solar_to_ev *
        # (charger_ev_w / fleet_ev_w)``. If charger A was on solar
        # and charger B was on grid (different priorities or just
        # different surplus availability), both got the SAME
        # proportional mix — losing the priority signal that the
        # main allocator above just computed.
        #
        # Step 5 attribution: priority-allocate each charger's
        # draw against the residual supply, in charger priority
        # order. Higher-priority chargers get first claim on
        # solar; lower-priority ones fall back to battery / grid.
        # The sum invariant
        # ``sum(per_charger.solar_to_ev) == fleet.solar_to_ev``
        # is preserved by construction (we just split the same
        # totals across chargers in priority order instead of by
        # equal fraction).
        if power.ev_power_per_charger:
            # Sort chargers by priority (lower = higher priority).
            # Falls back to dict-insertion order if priority dict
            # not provided — preserves v1.6.9 behaviour on single-
            # charger setups.
            priorities = getattr(power, "ev_priority_per_charger", None) or {}
            sorted_cids = sorted(
                power.ev_power_per_charger.keys(),
                key=lambda c: (priorities.get(c, 999), c),
            )

            # Per-source pool of fleet-attributed EV flow that's
            # still up for grabs by per-charger consumers.
            ev_pool = {
                "solar": flows.solar_to_ev,
                "grid": flows.grid_to_ev,
                "battery": flows.battery_to_ev,
            }

            for cid in sorted_cids:
                charger_ev_w = power.ev_power_per_charger.get(cid, 0.0)
                if charger_ev_w <= 0:
                    # Idle charger: zero-filled ChargerFlows (the
                    # v1.6.9 behaviour preserved).
                    flows.per_charger[cid] = ChargerFlows()
                    continue

                # Allocate from each source in priority order
                # (solar first, then battery, then grid).
                need = charger_ev_w
                solar_share = min(ev_pool["solar"], need)
                ev_pool["solar"] -= solar_share
                need -= solar_share

                battery_share = min(ev_pool["battery"], need)
                ev_pool["battery"] -= battery_share
                need -= battery_share

                grid_share = min(ev_pool["grid"], need)
                ev_pool["grid"] -= grid_share
                need -= grid_share

                flows.per_charger[cid] = ChargerFlows(
                    solar_to_ev=round(solar_share, 1),
                    grid_to_ev=round(grid_share, 1),
                    battery_to_ev=round(battery_share, 1),
                )

        return flows

    # Attributes covered by the running accumulator. Defined as a tuple so
    # ``integrate_energy_flows`` and the storage hooks share one source of truth.
    _ACCUMULATED_ATTRS = (
        "solar_to_home", "solar_to_ev", "solar_to_battery", "solar_to_grid",
        "grid_to_home", "grid_to_ev", "grid_to_battery",
        "battery_to_home", "battery_to_ev",
    )

    # v1.6.15: per-charger EV slice. Only the three EV-side flows
    # have a per-charger attribution surface — the rest stay fleet-level.
    _PER_CHARGER_ACCUMULATED_ATTRS = (
        "solar_to_ev", "grid_to_ev", "battery_to_ev",
    )

    # v1.7.0 / #312: per-string slot label form. Just one quantity
    # per string (kWh contribution this day). Kept as a tuple-of-one
    # for symmetry with the per-charger pattern and to make a future
    # second per-string scalar (e.g. peak watts) a one-line add.
    _PER_STRING_ACCUMULATED_ATTRS = (
        "energy_kwh",
    )

    def integrate_energy_flows(
        self, power_flows: PowerFlows, interval_seconds: float,
    ) -> EnergyFlows:
        """Time-integrate per-cycle power flows into daily energy flows (#282).

        Replaces ``calculate_energy_flows`` (proportional allocation across
        daily totals), which credited solar to the EV even when the EV
        wasn't drawing — a sunny day with a 30-min EV plug-in showed
        flow_solar_to_ev_energy ≈ daily_solar × (daily_ev / total_demand),
        which is fictional. The user's late-afternoon plug-in saw 85 %
        attributed-daily solar share while the actual session share was 12 %.

        This version integrates the instantaneous ``power_flows`` (already
        correctly attributed by ``calculate_power_flows`` based on the
        current cycle's demand) over time, so:

        * Solar that flowed to the GRID at noon while the EV was unplugged
          stays counted as solar_to_grid — not retroactively re-allocated.
        * Battery discharge in the afternoon shows up as battery_to_ev, with
          its origin (charged from morning solar) NOT re-credited as solar.

        The user sees small, honest numbers that match the session
        attribution. Bills + daily_solar_share now reflect what physically
        happened, not an aggregate average.

        Args:
            power_flows: Current cycle's instantaneous PowerFlows (watts).
            interval_seconds: Time since the last integration step
                (typically ``self.update_interval.total_seconds()``).

        Returns:
            EnergyFlows in kWh accumulated since the last day boundary.
        """
        # Day rollover — clear at local midnight. Solar-day or sunrise-based
        # rollover would shift this; keeping calendar-day for consistency with
        # daily_solar_energy / daily_grid_export_energy.
        today = dt_util.now().date()
        if today != self._current_date:
            self._flow_accumulators.clear()
            self._per_charger_accumulators.clear()
            self._per_string_accumulators.clear()
            self._current_date = today

        hours = max(0.0, interval_seconds) / 3600.0
        for attr in self._ACCUMULATED_ATTRS:
            watts = getattr(power_flows, attr, 0.0) or 0.0
            self._flow_accumulators[attr] = (
                self._flow_accumulators.get(attr, 0.0) + watts * hours / 1000.0
            )

        flows = EnergyFlows()
        for attr in self._ACCUMULATED_ATTRS:
            setattr(flows, attr, round(self._flow_accumulators.get(attr, 0.0), 3))

        # v1.6.15: per-charger EV slice. Integrate ``power_flows.per_charger``
        # into a parallel dict-of-dicts so each charger has its own kWh
        # counter. Sum invariant: per_charger totals match the fleet
        # ``flows.solar_to_ev`` (etc.) modulo rounding (pinned in
        # ``tests/test_per_charger_energy_flows.py``).
        if power_flows.per_charger:
            for cid, cflow in power_flows.per_charger.items():
                acc = self._per_charger_accumulators.setdefault(cid, {})
                for attr in self._PER_CHARGER_ACCUMULATED_ATTRS:
                    watts = getattr(cflow, attr, 0.0) or 0.0
                    acc[attr] = acc.get(attr, 0.0) + watts * hours / 1000.0

        # Emit every charger ever seen in the accumulator — even those
        # the current cycle's ``power_flows`` doesn't mention (e.g. car
        # unplugged mid-day). The user-visible counter must not regress
        # to 0 just because the charger went idle.
        for cid, acc in self._per_charger_accumulators.items():
            flows.per_charger[cid] = ChargerEnergyFlows(
                solar_to_ev=round(acc.get("solar_to_ev", 0.0), 3),
                grid_to_ev=round(acc.get("grid_to_ev", 0.0), 3),
                battery_to_ev=round(acc.get("battery_to_ev", 0.0), 3),
            )

        # v1.7.0 / #312: per-PV-string slice. Integrate the raw
        # per-string power carried on ``power_flows.solar_per_string``
        # into a parallel dict-of-dicts so each string has its own
        # kWh counter. Sum invariant pinned in tests:
        # ``sum(per_string.energy_kwh) ≈ fleet solar integration``
        # within rounding.
        if power_flows.solar_per_string:
            for sid, watts in power_flows.solar_per_string.items():
                acc = self._per_string_accumulators.setdefault(sid, {})
                w = watts or 0.0
                acc["energy_kwh"] = (
                    acc.get("energy_kwh", 0.0) + w * hours / 1000.0
                )

        # Emit every string ever seen — clouds shading one panel
        # array mid-day shouldn't regress the user-visible counter to 0
        # (same semantic as the per-charger emit above).
        for sid, acc in self._per_string_accumulators.items():
            flows.per_string[sid] = StringEnergy(
                energy_kwh=round(acc.get("energy_kwh", 0.0), 3),
            )

        return flows

    def get_flow_accumulator_state(self) -> dict:
        """Snapshot for persistence (#282). Keys + date so restore can
        detect a stale snapshot from a previous day.

        v1.6.15 adds ``per_charger`` — restored only if non-empty so
        single-charger storage stays bit-for-bit compatible with the
        pre-v1.6.15 snapshot format.
        """
        snap = {
            "date": self._current_date.isoformat(),
            "accumulators": dict(self._flow_accumulators),
        }
        if self._per_charger_accumulators:
            snap["per_charger"] = {
                cid: dict(acc)
                for cid, acc in self._per_charger_accumulators.items()
            }
        if self._per_string_accumulators:
            snap["per_string"] = {
                sid: dict(acc)
                for sid, acc in self._per_string_accumulators.items()
            }
        return snap

    def restore_flow_accumulator_state(self, state: dict) -> None:
        """Restore on coordinator startup so an HA restart mid-day doesn't
        reset the daily flow counters back to 0 (#282)."""
        if not isinstance(state, dict):
            return
        try:
            saved_date = date.fromisoformat(state.get("date", ""))
        except (TypeError, ValueError):
            return
        # If today is a different day, treat as stale — don't carry yesterday's
        # accumulator into today's counters.
        if saved_date != self._current_date:
            return
        acc = state.get("accumulators")
        if isinstance(acc, dict):
            for k in self._ACCUMULATED_ATTRS:
                v = acc.get(k)
                if isinstance(v, (int, float)):
                    self._flow_accumulators[k] = float(v)

        # v1.6.15: restore per-charger slice if present. Missing key is
        # the expected case for pre-v1.6.15 snapshots — silently skip.
        pc = state.get("per_charger")
        if isinstance(pc, dict):
            for cid, acc in pc.items():
                if not isinstance(acc, dict):
                    continue
                target = self._per_charger_accumulators.setdefault(str(cid), {})
                for k in self._PER_CHARGER_ACCUMULATED_ATTRS:
                    v = acc.get(k)
                    if isinstance(v, (int, float)):
                        target[k] = float(v)

        # v1.7.0: restore per-string slice if present. Missing key is
        # the expected case for pre-v1.7.0 snapshots — silently skip.
        ps = state.get("per_string")
        if isinstance(ps, dict):
            for sid, acc in ps.items():
                if not isinstance(acc, dict):
                    continue
                target = self._per_string_accumulators.setdefault(str(sid), {})
                for k in self._PER_STRING_ACCUMULATED_ATTRS:
                    v = acc.get(k)
                    if isinstance(v, (int, float)):
                        target[k] = float(v)

    def calculate_energy_flows(self, energy: EnergyTotals) -> EnergyFlows:
        """Legacy proportional-allocation energy flows (kept for tests).

        ⚠️  Misleading attribution — use ``integrate_energy_flows`` instead.
        Spreads daily totals proportionally to demand without regard to
        timing, so a sunny morning with no EV charging still credits solar
        to a brief afternoon EV plug-in.

        Retained because some tests pin the old behaviour and because the
        function is mathematically valid as a Sankey-style aggregate when
        timing doesn't matter (full-day overviews). Not wired into the
        coordinator update cycle anymore (#282).
        """
        flows = EnergyFlows()

        # Get source energies
        solar = energy.daily_solar
        grid_import = energy.daily_grid_import
        battery_discharge = energy.daily_battery_discharge

        # Get destination energies
        home = energy.daily_home
        ev = energy.daily_ev
        battery_charge = energy.daily_battery_charge
        grid_export = energy.daily_grid_export

        # Calculate total demand
        total_demand = home + ev + battery_charge + grid_export

        if total_demand < 0.001:  # Less than 1Wh
            return flows

        # Calculate demand percentages
        home_pct = home / total_demand
        ev_pct = ev / total_demand
        battery_charge_pct = battery_charge / total_demand
        grid_export_pct = grid_export / total_demand

        # Distribute solar energy proportionally
        flows.solar_to_home = round(solar * home_pct, 3)
        flows.solar_to_ev = round(solar * ev_pct, 3)
        flows.solar_to_battery = round(solar * battery_charge_pct, 3)
        flows.solar_to_grid = round(solar * grid_export_pct, 3)

        # Grid import to destinations (excluding grid export)
        demand_without_export = home + ev + battery_charge
        if demand_without_export > 0.001:
            home_pct_no_export = home / demand_without_export
            ev_pct_no_export = ev / demand_without_export
            battery_pct_no_export = battery_charge / demand_without_export

            flows.grid_to_home = round(grid_import * home_pct_no_export, 3)
            flows.grid_to_ev = round(grid_import * ev_pct_no_export, 3)
            flows.grid_to_battery = round(grid_import * battery_pct_no_export, 3)

        # Battery discharge to home and EV
        demand_for_battery = home + ev
        if demand_for_battery > 0.001:
            home_pct_battery = home / demand_for_battery
            ev_pct_battery = ev / demand_for_battery

            flows.battery_to_home = round(battery_discharge * home_pct_battery, 3)
            flows.battery_to_ev = round(battery_discharge * ev_pct_battery, 3)

        # Verify energy balance and adjust if needed
        home_received = flows.solar_to_home + flows.grid_to_home + flows.battery_to_home
        if abs(home - home_received) > 0.001:
            # Absorb rounding difference into solar_to_home
            flows.solar_to_home = round(flows.solar_to_home + (home - home_received), 3)

        _LOGGER.debug(
            f"Energy flows calculated: "
            f"Solar→Home: {flows.solar_to_home:.3f}, "
            f"Solar→Grid: {flows.solar_to_grid:.3f}, "
            f"Grid→Home: {flows.grid_to_home:.3f}"
        )

        return flows

    # ``calculate_ev_budget`` removed in Phase D.2 (#282). Pre-D.2 it lived
    # alongside ``calculate_canonical_ev_budget`` and the two diverged on
    # the surplus floor — exactly the duplication that produced the
    # 2026-05-28 PROD surplus leak. The canonical primitive is the single
    # source of truth now; informational/diagnostic callers that need a
    # budget figure should resolve a strategy first and call
    # ``calculate_canonical_ev_budget(strategy=…)``.

    def _calculate_battery_redirect(self, battery_charge_w: float,
                                     battery_soc: float,
                                     battery_capacity_kwh: float,
                                     forecast_remaining_kwh: float) -> float:
        """Thin wrapper kept for method-call call sites.

        Delegates to the module-level free function so the strategy
        decision path (``decide.py``) can compute the same value
        without instantiating a ``FlowCalculator``.
        """
        return battery_redirect_w(
            battery_charge_w, battery_soc,
            battery_capacity_kwh, forecast_remaining_kwh,
        )

    # ``calculate_available_power`` removed in Phase D.2 (#282). Zero
    # production callers as of v1.6.0 — the canonical EVBudget supersedes
    # it; published sensors derive from the same cached cycle budget the
    # state machine and actuator use.
    #
    # ``calculate_charging_current`` removed in Phase D.2 (#282). Both
    # production call sites (the night charge sizing and the actuator
    # ramp) now go through ``EVControlMixin._watts_to_amps`` which carries
    # the per-charger watts-per-amp + round-down policy directly; carrying
    # a second copy here just invited the rounding disagreement that the
    # 2026-05-28 surplus leak exhibited.

    # ───────────────────────────────────────────────────────────────────
    # Canonical EV-budget calculation — Phase A of #282 unification
    # ───────────────────────────────────────────────────────────────────

    def calculate_canonical_ev_budget(
        self,
        power: PowerReadings,
        *,
        strategy: str,
        battery_soc: float = 0.0,
        battery_capacity_kwh: float = 15.0,
        forecast_remaining_kwh: float = 0.0,
        battery_auto_start_soc: float = 90.0,
        battery_buffer_soc: float = 70.0,
        battery_assist_floor_soc: float = 60.0,
        battery_assist_max_power_w: float = 4500.0,
        min_power_floor_w: float = 0.0,
        override_max_w: Optional[float] = None,
        voltage: float = 230.0,
        phases: int = 3,
    ) -> EVBudget:
        """The one method. Strategy-aware. Replaces the three legacy paths.

        Computes the canonical setpoint (watts) the EV charger is
        allowed to draw right now, broken down into its components so
        the caller can publish each piece as a diagnostic sensor.

        Args:
            power: This cycle's sensor readings.
            strategy: One of :class:`EVBudgetStrategy`'s constants.
                Each strategy has a single, well-defined formula —
                callers MUST translate their own (legacy) strategy
                names into one of these explicitly.
            battery_soc, battery_capacity_kwh, forecast_remaining_kwh:
                Inputs to the redirect/assist sub-calculations.
            battery_auto_start_soc, battery_buffer_soc,
                battery_assist_floor_soc, battery_assist_max_power_w:
                Strategy thresholds, normally read from config. Defaults
                match the SEM-wide defaults so calls without overrides
                still produce sensible numbers.
            min_power_floor_w: Set this when strategy is ``MIN_PV`` to
                guarantee a minimum setpoint (the "Min" part of Min+PV).
                Ignored for other strategies.
            override_max_w: Set this when strategy is ``NOW`` to bypass
                the surplus calculation entirely. Typically the
                charger's nameplate power (max_current * phases *
                voltage). Ignored for other strategies.
            voltage, phases: Charger electrical parameters for the
                amps conversion. Defaults match a 3-phase EU charger
                at 230 V — KEBA, Wallbox, etc.

        Returns:
            :class:`EVBudget` with all components filled in.

        Raises:
            ValueError: if ``strategy`` is unknown. We refuse to
                silently fall through to a "safe" default because every
                strategy must be mapped explicitly — silent fallthrough
                was exactly the #282 disagreement mode.
        """
        # Always compute the building blocks. Strategies that don't
        # consume a particular block get it set to 0 in the dataclass —
        # makes the diagnostic sensors honest about the decomposition.
        raw_surplus = max(
            0.0,
            power.solar_power
            - power.home_consumption_power
            - power.battery_charge_power,
        )

        # ─── IDLE ───────────────────────────────────────────────────
        if strategy == EVBudgetStrategy.IDLE:
            return EVBudget(
                strategy=strategy,
                solar_surplus=0.0,
                battery_redirect=0.0,
                battery_assist=0.0,
                net_w=0.0,
                current_a=0,
            )

        # ─── NOW ────────────────────────────────────────────────────
        # User-asked override. Grid backfill is intentional in this mode.
        if strategy == EVBudgetStrategy.NOW:
            net_w = override_max_w if override_max_w is not None else (
                16.0 * phases * voltage  # SEM upper bound
            )
            net_w = max(0.0, net_w)
            return EVBudget(
                strategy=strategy,
                solar_surplus=0.0,
                battery_redirect=0.0,
                battery_assist=0.0,
                net_w=round(net_w, 0),
                current_a=self._watts_to_amps(net_w, voltage, phases),
            )

        # ─── SELF_CONSUMPTION (Zone 2) ──────────────────────────────
        # Surplus only. Battery has priority in this band — no redirect.
        # Special-case: when SOC >= auto_start_soc, the battery doesn't
        # need its share, so we don't subtract batt_charge from surplus.
        # This mirrors the legacy `_self_consumption_strategy` and the
        # legacy B3 actuator path (ev_control.py:447) that disagreed
        # with the state machine for years.
        if strategy == EVBudgetStrategy.SELF_CONSUMPTION:
            if battery_soc >= battery_auto_start_soc:
                surplus = max(
                    0.0,
                    power.solar_power - power.home_consumption_power,
                )
            else:
                surplus = raw_surplus
            return EVBudget(
                strategy=strategy,
                solar_surplus=round(surplus, 0),
                battery_redirect=0.0,
                battery_assist=0.0,
                net_w=round(surplus, 0),
                current_a=self._watts_to_amps(surplus, voltage, phases),
            )

        # ─── SOLAR_ONLY (Zone 3) ────────────────────────────────────
        # Surplus + forecast-aware redirect.
        if strategy == EVBudgetStrategy.SOLAR_ONLY:
            redirect = self._calculate_battery_redirect(
                power.battery_charge_power, battery_soc,
                battery_capacity_kwh, forecast_remaining_kwh,
            )
            net_w = raw_surplus + redirect
            return EVBudget(
                strategy=strategy,
                solar_surplus=round(raw_surplus, 0),
                battery_redirect=round(redirect, 0),
                battery_assist=0.0,
                net_w=round(net_w, 0),
                current_a=self._watts_to_amps(net_w, voltage, phases),
            )

        # ─── BATTERY_ASSIST ─────────────────────────────────────────
        # Surplus + redirect + active battery discharge to EV.
        if strategy == EVBudgetStrategy.BATTERY_ASSIST:
            redirect = self._calculate_battery_redirect(
                power.battery_charge_power, battery_soc,
                battery_capacity_kwh, forecast_remaining_kwh,
            )
            assist = self._calculate_battery_assist_w(
                power, battery_soc,
                battery_auto_start_soc, battery_buffer_soc,
                battery_assist_floor_soc, battery_assist_max_power_w,
            )
            net_w = raw_surplus + redirect + assist
            return EVBudget(
                strategy=strategy,
                solar_surplus=round(raw_surplus, 0),
                battery_redirect=round(redirect, 0),
                battery_assist=round(assist, 0),
                net_w=round(net_w, 0),
                current_a=self._watts_to_amps(net_w, voltage, phases),
            )

        # ─── MIN_PV ─────────────────────────────────────────────────
        # Surplus + redirect, floored at min_power_floor_w (grid backfills
        # the difference when surplus is insufficient — by user request).
        if strategy == EVBudgetStrategy.MIN_PV:
            redirect = self._calculate_battery_redirect(
                power.battery_charge_power, battery_soc,
                battery_capacity_kwh, forecast_remaining_kwh,
            )
            surplus_plus_redirect = raw_surplus + redirect
            net_w = max(min_power_floor_w, surplus_plus_redirect)
            return EVBudget(
                strategy=strategy,
                solar_surplus=round(raw_surplus, 0),
                battery_redirect=round(redirect, 0),
                battery_assist=0.0,
                net_w=round(net_w, 0),
                current_a=self._watts_to_amps(net_w, voltage, phases),
            )

        # Unknown strategy — refuse to silently fall through. Silent
        # fallthrough was the #282 disagreement root cause; the unifier
        # must be loud.
        raise ValueError(
            f"calculate_canonical_ev_budget: unknown strategy {strategy!r}. "
            f"Map your legacy strategy to one of EVBudgetStrategy.* explicitly."
        )

    def _watts_to_amps(self, watts: float, voltage: float, phases: int) -> int:
        """Floor watts → integer amps, clamped to [0, 16].

        Floor (not round-to-nearest) because the actuator must stay
        strictly under the budget — round-to-nearest can push +0.5 A
        over the surplus floor and silently leak grid (#282 / Scenario 0).
        """
        if watts <= 0:
            return 0
        amps = math.floor(watts / (voltage * phases))
        return max(0, min(16, amps))

    def _calculate_battery_assist_w(
        self,
        power: PowerReadings,
        battery_soc: float,
        battery_auto_start_soc: float,
        battery_buffer_soc: float,
        battery_assist_floor_soc: float,
        battery_assist_max_power_w: float,
    ) -> float:
        """How much battery discharge to attribute to EV in battery_assist mode.

        Mirrors the legacy formula from `_calculate_solar_ev_budget` in
        ev_control.py (the only place this lived before unification):

        - SOC below assist floor: 0 (the battery shouldn't assist).
        - Battery already discharging (>= 100 W): use measured value.
        - Battery not yet discharging:
            - Zone 4 (SOC >= auto_start_soc): full assist.
            - Zone 3 (SOC >= buffer_soc):
                proportional ramp 0.5 → 1.0 across the [buffer, auto_start]
                band.
            - Zone 2 (SOC < buffer_soc): 0 (shouldn't reach here — the
                strategy decision should have chosen solar_only — but
                guard anyway).
        """
        if battery_soc <= battery_assist_floor_soc:
            return 0.0

        measured_discharge = max(0.0, power.battery_discharge_power)
        if measured_discharge >= 100:
            return measured_discharge

        if battery_soc >= battery_auto_start_soc:
            return battery_assist_max_power_w
        if battery_soc >= battery_buffer_soc:
            band = max(1.0, battery_auto_start_soc - battery_buffer_soc)
            ratio = (battery_soc - battery_buffer_soc) / band
            return battery_assist_max_power_w * (0.5 + 0.5 * ratio)
        return 0.0
