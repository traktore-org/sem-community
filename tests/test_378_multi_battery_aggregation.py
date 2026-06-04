"""Regression tests for #378 — multi-battery flow aggregation.

The reported bug:
  - Growatt setup with 2 batteries
  - Both batteries charging at ~2 kW each (4 kW total)
  - SEM's flow display shows only ONE battery's 2 kW going to battery;
    the other 2 kW shows as "flowing to house"
  - i.e. the missing 2 kW gets attributed to ``home_consumption_power``

Root cause (one of):
  1. Sensor reader picks up only one battery (``battery_power_list``
     in Energy Dashboard config has only 1 entry)
  2. SEM's autodetect for the user's brand misses the 2nd battery
  3. A future arch change bypasses the per-battery aggregation in
     ``PowerReadings.fleet_battery_w`` / the cached ``battery_power``

#1 and #2 require live diagnostics from the user. This file pins
**#3** structurally: if the per-battery aggregation contract is
broken (cached ``battery_power`` no longer reflects the true sum,
or ``calculate_derived`` doesn't use the cached field, or the
home-consumption energy balance silently drops a battery),
regression caught here.

The existing ``tests/test_multi_device_aggregation.py`` covers the
sensor-reader sum path. This file covers the
``PowerReadings.calculate_derived`` consumer side — the layer that
turns the cached/per-battery data into the home-consumption
attribution the user sees on the dashboard.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
)


# ---------------------------------------------------------------------------
# Single-source aggregation (the cached ``battery_power`` field)
# ---------------------------------------------------------------------------


class Test378SingleCachedBatteryField:
    """When ``battery_power`` is the canonical sum (sensor reader pre-summed),
    the energy balance must not silently drop part of it."""

    def test_4kw_battery_charge_subtracted_from_home_balance(self) -> None:
        """The #378 user's regime: solar=8kW, batteries=4kW total charge.

        With 2 batteries each at 2 kW, the cached ``battery_power``
        should equal 4 kW. ``calculate_derived`` subtracts 4 kW from
        the home-consumption balance. If a future change silently
        treated battery_power as only 2 kW, home would be inflated
        by 2 kW — exactly the #378 symptom on the dashboard.
        """
        pr = PowerReadings(
            solar_power=8000,
            grid_power=0,           # neither importing nor exporting
            battery_power=4000,     # 2 batteries × 2 kW charge each, summed
            ev_power=0,
        )
        pr.calculate_derived()

        assert pr.battery_charge_power == 4000
        assert pr.battery_discharge_power == 0
        # Energy balance: 8000 (solar) + 0 (grid in) + 0 (batt out) =
        #                 8000 (in) − (0 ev + 0 grid out + 4000 batt in) = 4000 home
        assert pr.home_consumption_power == 4000

    def test_only_one_battery_counted_inflates_home(self) -> None:
        """The bug: only one battery read → 2 kW missing. The energy
        balance has nowhere to put 2 kW so it goes to ``home``.

        This is the WRONG behaviour from the user's perspective; the
        test exists to make the symptom visible (if you ran the live
        system in this state, the dashboard would show 4 kW home
        even though the actual home draw is 2 kW). Catches the case
        where someone "fixes" home_consumption_power to clamp at a
        different value and silently masks the underlying drop.
        """
        pr = PowerReadings(
            solar_power=8000,
            grid_power=0,
            battery_power=2000,     # BUG: only 1 of 2 batteries counted
            ev_power=0,
        )
        pr.calculate_derived()

        # Expected (wrong) home is 6000 W when actual is 2000 W —
        # the missing 2 kW shows up here. THIS is what the user sees
        # in the dashboard; the assertion documents the bug surface.
        assert pr.home_consumption_power == 6000


# ---------------------------------------------------------------------------
# Per-battery dict aggregation (the new #375 surface)
# ---------------------------------------------------------------------------


class Test378FleetBatteryWAggregation:
    """When the per-battery dict is populated (arch/multi-inverter-battery-primary),
    ``fleet_battery_w`` must sum it correctly. The cached
    ``battery_power`` field should be kept in sync — invariant from
    ``tests/test_step8_invariants.py``.
    """

    def test_fleet_battery_w_sums_two_batteries(self) -> None:
        """Two batteries each at 2 kW charging → fleet_battery_w = 4 kW."""
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryPower,
        )
        pr = PowerReadings(
            solar_power=8000, grid_power=0,
            battery_power=4000,  # cached sum
        )
        pr.batteries = {
            "battery_1": BatteryPower(battery_id="battery_1", power_w=2000, soc_pct=50),
            "battery_2": BatteryPower(battery_id="battery_2", power_w=2000, soc_pct=55),
        }
        assert pr.fleet_battery_w == 4000

    def test_fleet_battery_w_falls_back_to_cached_when_dict_empty(self) -> None:
        """Single-battery and pre-v1.7 snapshots — empty dict → use cached field."""
        pr = PowerReadings(battery_power=3000)
        assert pr.fleet_battery_w == 3000

    def test_fleet_battery_w_handles_discharge_mix(self) -> None:
        """One battery charging, one discharging — fleet sum nets out."""
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryPower,
        )
        pr = PowerReadings(battery_power=500)
        pr.batteries = {
            "battery_1": BatteryPower(battery_id="battery_1", power_w=2000, soc_pct=80),
            "battery_2": BatteryPower(battery_id="battery_2", power_w=-1500, soc_pct=20),
        }
        assert pr.fleet_battery_w == 500


# ---------------------------------------------------------------------------
# Cross-check: per-battery aggregation should agree with the cached field
# ---------------------------------------------------------------------------


def test_378_per_battery_dict_should_match_cached_field() -> None:
    """The arch invariant: cached ``battery_power`` must equal
    ``fleet_battery_w`` (the per-battery sum) when both are populated.

    If they ever diverge in production, the sensor reader has a
    bug — one of the two paths skipped a battery. This invariant is
    the structural guard against #378's class.
    """
    from custom_components.solar_energy_management.coordinator.charger_types import (
        BatteryPower,
    )
    # Per-battery total = 4 kW; cached field also = 4 kW. Agreement = OK.
    pr = PowerReadings(battery_power=4000)
    pr.batteries = {
        "battery_1": BatteryPower(battery_id="battery_1", power_w=2000, soc_pct=50),
        "battery_2": BatteryPower(battery_id="battery_2", power_w=2000, soc_pct=55),
    }
    assert pr.fleet_battery_w == pr.battery_power

    # Misaligned (the #378 PROD state): cached=2000 (one battery only),
    # per-battery dict=4000 (both). Their disagreement is the diagnostic
    # signal. SEM should LOG WARN here, but the cached field is what
    # drives downstream math — the dashboard shows the bug.
    pr_bug = PowerReadings(battery_power=2000)
    pr_bug.batteries = {
        "battery_1": BatteryPower(battery_id="battery_1", power_w=2000, soc_pct=50),
        "battery_2": BatteryPower(battery_id="battery_2", power_w=2000, soc_pct=55),
    }
    assert pr_bug.fleet_battery_w != pr_bug.battery_power
    # The diagnostic: fleet=4000, cached=2000 → cached is the
    # under-counter; the dashboard will see home_consumption inflated
    # by 2000W.
