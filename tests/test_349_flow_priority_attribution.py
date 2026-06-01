"""Regression tests for #349 — flow attribution must match user intent.

Background. SEM's `flow_calculator.calculate_power_flows` used to
split each source proportionally across all destinations. In sunny
midday scenarios with the home battery simultaneously charging, this
attributed a chunk of `grid_import` to the EV even when the available
solar could have covered home + EV entirely (with the battery being
the actual grid-paid consumer). The HA-PROD 2026-06-01 dashboard
showed `flow_grid_to_ev_energy = 6.633 kWh` for a day where the
`session_solar_share` actuator metric said the car was 91% solar.

Fix: priority-based attribution. Sources drain in order
``solar → battery_discharge → grid_import``; destinations are served
in order ``home → ev → battery_charge → grid_export``. The same
conservation invariants hold (sum-of-flows = supply on each side),
the SUM totals are unchanged, only which (source, destination) pair
each watt is attributed to differs.

The tests pin both the new attribution semantics AND the conservation
invariants on either side.
"""
import pytest

from custom_components.solar_energy_management.coordinator.flow_calculator import (
    FlowCalculator,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings


def _calc():
    """Bare-bones FlowCalculator (no integration concerns here)."""
    from unittest.mock import MagicMock
    fc = FlowCalculator.__new__(FlowCalculator)
    fc.update_interval = MagicMock(total_seconds=lambda: 10.0)
    return fc


def _power(**kw):
    """Build a PowerReadings with derived `_import_power` /
    `_export_power` / `_discharge_power` fields set so the algorithm
    can read the split sources directly (mirrors what
    `PowerReadings.calculate_derived` does in the live pipeline)."""
    p = PowerReadings(**kw)
    grid = kw.get("grid_power", 0.0)
    batt = kw.get("battery_power", 0.0)
    # Sign convention per CLAUDE.md: grid- = import, batt- = discharge.
    p.grid_import_power = max(0.0, -grid)
    p.grid_export_power = max(0.0, grid)
    p.battery_charge_power = max(0.0, batt)
    p.battery_discharge_power = max(0.0, -batt)
    return p


class TestPriorityAttribution:
    """Source/destination priority order matches user intent."""

    def test_prod_sunny_midday_ev_is_100pct_solar(self):
        """The #349 PROD scenario. Solar = 8 kW covers home + EV fully,
        battery's 5 kW charge is the grid-paid consumer.

        Pre-fix proportional model: solar_to_ev ≈ 4174 W (52% solar),
        grid_to_ev ≈ 1826 W (the bug).

        Post-fix priority model: solar drains home → ev → battery in
        that order, so solar covers all 6 kW of EV before any reaches
        the battery; grid covers only the battery deficit.
        """
        fc = _calc()
        p = _power(
            solar_power=8000.0,
            grid_power=-3500.0,  # import 3.5 kW
            battery_power=5000.0,  # charging at 5 kW
            home_consumption_power=500.0,
            ev_power=6000.0,
            ev_connected=True,
        )
        f = fc.calculate_power_flows(p)
        assert f.solar_to_ev == pytest.approx(6000.0, abs=1)
        assert f.grid_to_ev == pytest.approx(0.0, abs=1)
        assert f.battery_to_ev == pytest.approx(0.0, abs=1)
        # Sanity: the battery's grid backfill is where grid landed
        assert f.grid_to_battery == pytest.approx(3500.0, abs=1)
        # Solar leftover (8000 - 500 - 6000) covered the rest of battery
        assert f.solar_to_battery == pytest.approx(1500.0, abs=1)

    def test_night_deficit_ev_is_100pct_grid(self):
        """Night scenario, no solar. Grid covers home + EV deficit
        after battery is drained for home."""
        fc = _calc()
        p = _power(
            solar_power=0.0,
            grid_power=-6000.0,  # import 6 kW
            battery_power=-500.0,  # discharging 500 W
            home_consumption_power=500.0,
            ev_power=6000.0,
            ev_connected=True,
        )
        f = fc.calculate_power_flows(p)
        # Battery's 500W drains to home (higher priority than EV)
        assert f.battery_to_home == pytest.approx(500.0, abs=1)
        assert f.battery_to_ev == pytest.approx(0.0, abs=1)
        # Grid covers EV in full
        assert f.grid_to_ev == pytest.approx(6000.0, abs=1)
        assert f.grid_to_home == pytest.approx(0.0, abs=1)

    def test_solar_excess_no_battery_priority(self):
        """Solar = 10 kW, demand only 1 kW home + 6 kW EV. Excess
        exports. No battery, no grid import."""
        fc = _calc()
        p = _power(
            solar_power=10000.0,
            grid_power=3000.0,  # exporting 3 kW
            battery_power=0.0,
            home_consumption_power=1000.0,
            ev_power=6000.0,
            ev_connected=True,
        )
        f = fc.calculate_power_flows(p)
        assert f.solar_to_home == pytest.approx(1000.0, abs=1)
        assert f.solar_to_ev == pytest.approx(6000.0, abs=1)
        assert f.solar_to_grid == pytest.approx(3000.0, abs=1)
        assert f.grid_to_ev == 0
        assert f.battery_to_ev == 0

    def test_battery_discharge_powers_ev_when_solar_insufficient(self):
        """Cloudy moment: solar=2 kW, home=500W, EV=4 kW, battery
        discharges 2.5 kW. Solar fully covers home + part of EV;
        battery covers the rest. No grid."""
        fc = _calc()
        p = _power(
            solar_power=2000.0,
            grid_power=0.0,
            battery_power=-2500.0,  # discharge
            home_consumption_power=500.0,
            ev_power=4000.0,
            ev_connected=True,
        )
        f = fc.calculate_power_flows(p)
        # Home first (priority order)
        assert f.solar_to_home == pytest.approx(500.0, abs=1)
        # EV next: 2000 - 500 = 1500 W of solar
        assert f.solar_to_ev == pytest.approx(1500.0, abs=1)
        # Battery covers the rest: 4000 - 1500 = 2500 W
        assert f.battery_to_ev == pytest.approx(2500.0, abs=1)
        assert f.grid_to_ev == 0


class TestConservationInvariants:
    """For every cycle: sum of flows out of a source = source power,
    sum of flows into a destination = destination power. Pin per-side
    so a future refactor can't introduce double-counting."""

    @pytest.mark.parametrize("scenario", [
        # (solar, grid_pwr, batt_pwr, home, ev, name)
        (8000, -3500, 5000, 500, 6000, "sunny_battery_charging"),
        (0, -6000, -500, 500, 6000, "night_battery_assist"),
        (10000, 3000, 0, 1000, 6000, "solar_export"),
        (2000, 0, -2500, 500, 4000, "cloudy_battery_discharge"),
        (5000, 0, 0, 500, 0, "no_ev"),
        (0, 0, 0, 0, 0, "all_idle"),
    ])
    def test_destination_conservation(self, scenario):
        solar, grid_pwr, batt_pwr, home, ev, name = scenario
        fc = _calc()
        p = _power(
            solar_power=solar, grid_power=grid_pwr,
            battery_power=batt_pwr, home_consumption_power=home,
            ev_power=ev, ev_connected=True,
        )
        f = fc.calculate_power_flows(p)

        # Every consumer (home, ev, batt_charge, grid_export) gets exactly its draw
        assert (f.solar_to_home + f.grid_to_home + f.battery_to_home
                == pytest.approx(home, abs=1)), \
            f"scenario={name}: home conservation broken"
        assert (f.solar_to_ev + f.grid_to_ev + f.battery_to_ev
                == pytest.approx(ev, abs=1)), \
            f"scenario={name}: ev conservation broken"
        assert (f.solar_to_battery + f.grid_to_battery
                == pytest.approx(p.battery_charge_power, abs=1)), \
            f"scenario={name}: battery_charge conservation broken"
        assert (f.solar_to_grid
                == pytest.approx(p.grid_export_power, abs=1)), \
            f"scenario={name}: grid_export conservation broken"

    @pytest.mark.parametrize("scenario", [
        (8000, -3500, 5000, 500, 6000, "sunny_battery_charging"),
        (0, -6000, -500, 500, 6000, "night_battery_assist"),
        (10000, 3000, 0, 1000, 6000, "solar_export"),
        (2000, 0, -2500, 500, 4000, "cloudy_battery_discharge"),
    ])
    def test_source_conservation(self, scenario):
        solar, grid_pwr, batt_pwr, home, ev, name = scenario
        fc = _calc()
        p = _power(
            solar_power=solar, grid_power=grid_pwr,
            battery_power=batt_pwr, home_consumption_power=home,
            ev_power=ev, ev_connected=True,
        )
        f = fc.calculate_power_flows(p)

        # Every supplier (solar, grid_import, battery_discharge) dispatches
        # exactly its supply
        assert (f.solar_to_home + f.solar_to_ev + f.solar_to_battery
                + f.solar_to_grid == pytest.approx(solar, abs=1)), \
            f"scenario={name}: solar conservation broken"
        assert (f.grid_to_home + f.grid_to_ev + f.grid_to_battery
                == pytest.approx(p.grid_import_power, abs=1)), \
            f"scenario={name}: grid_import conservation broken"
        assert (f.battery_to_home + f.battery_to_ev
                == pytest.approx(p.battery_discharge_power, abs=1)), \
            f"scenario={name}: battery_discharge conservation broken"
