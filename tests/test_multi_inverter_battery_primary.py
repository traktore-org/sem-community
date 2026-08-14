"""Tests for the per-inverter and per-battery primary types
(v1.7.0 arch/multi-inverter-battery-primary).

Same pattern as the EV side (test_step8_invariants.py): the
per-device dict is the PRIMARY representation; the fleet float
field is a cached sum. Invariants pin the relationship and the
@property accessors.
"""
import pytest

from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryPower,
    InverterPower,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings


class TestInverterPowerType:
    """Frozen-dataclass shape pins."""

    def test_default_init(self):
        i = InverterPower(inverter_id="sun2000")
        assert i.inverter_id == "sun2000"
        assert i.power_w == 0.0
        # (#771) ``daily_kwh`` is gone: sensor_reader builds this snapshot
        # from an instantaneous power read and never had a per-inverter
        # energy counter to fill it from, so it was 0.0 on every install
        # ever — a measurement-shaped default (#755 contract 1).
        assert i.name == ""

    def test_frozen(self):
        from dataclasses import FrozenInstanceError
        i = InverterPower(inverter_id="sun2000", power_w=5000.0)
        with pytest.raises(FrozenInstanceError):
            i.power_w = 6000.0  # type: ignore[misc]


class TestBatteryPowerType:
    def test_default_init(self):
        b = BatteryPower(battery_id="luna2000")
        assert b.battery_id == "luna2000"
        assert b.power_w == 0.0
        # None until the unit's SOC sensor resolves (#694) — 0.0 here was
        # the fabricated "empty battery" claim.
        assert b.soc_pct is None
        assert b.capacity_kwh == 0.0

    def test_frozen(self):
        from dataclasses import FrozenInstanceError
        b = BatteryPower(battery_id="luna2000", power_w=1500.0)
        with pytest.raises(FrozenInstanceError):
            b.soc_pct = 80.0  # type: ignore[misc]


class TestFleetSolarProperty:
    """``PowerReadings.fleet_solar_w`` computes from the inverters
    dict; falls back to cached ``solar_power`` when empty."""

    def test_empty_dict_falls_back_to_solar_power(self):
        r = PowerReadings(solar_power=5000.0)
        assert r.fleet_solar_w == 5000.0

    def test_single_inverter(self):
        r = PowerReadings(solar_power=5000.0)
        r.inverters["a"] = InverterPower(inverter_id="a", power_w=5000.0)
        assert r.fleet_solar_w == 5000.0

    def test_two_inverters_sum(self):
        r = PowerReadings(solar_power=11000.0)
        r.inverters["a"] = InverterPower(inverter_id="a", power_w=5000.0)
        r.inverters["b"] = InverterPower(inverter_id="b", power_w=6000.0)
        assert r.fleet_solar_w == 11000.0

    def test_three_inverters_sum(self):
        r = PowerReadings()
        r.inverters["a"] = InverterPower(inverter_id="a", power_w=3500.0)
        r.inverters["b"] = InverterPower(inverter_id="b", power_w=2500.0)
        r.inverters["c"] = InverterPower(inverter_id="c", power_w=4000.0)
        assert r.fleet_solar_w == pytest.approx(10000.0, abs=0.01)


class TestFleetBatteryProperty:
    def test_empty_falls_back(self):
        r = PowerReadings(battery_power=-2500.0)
        assert r.fleet_battery_w == -2500.0

    def test_two_batteries_sum_with_signs(self):
        """One charging (+1000), one discharging (-500). Sum = +500."""
        r = PowerReadings()
        r.batteries["a"] = BatteryPower(battery_id="a", power_w=1000.0)
        r.batteries["b"] = BatteryPower(battery_id="b", power_w=-500.0)
        assert r.fleet_battery_w == pytest.approx(500.0, abs=0.01)

    def test_capacity_weighted_soc(self):
        """Different capacities → weighted average."""
        r = PowerReadings()
        r.batteries["small"] = BatteryPower(
            battery_id="small", soc_pct=80.0, capacity_kwh=5.0,
        )
        r.batteries["big"] = BatteryPower(
            battery_id="big", soc_pct=50.0, capacity_kwh=15.0,
        )
        # weighted: (80*5 + 50*15) / 20 = (400 + 750) / 20 = 57.5
        assert r.fleet_battery_soc == pytest.approx(57.5, abs=0.01)

    def test_soc_falls_back_to_arithmetic_mean_when_no_capacity(self):
        r = PowerReadings()
        r.batteries["a"] = BatteryPower(battery_id="a", soc_pct=80.0)
        r.batteries["b"] = BatteryPower(battery_id="b", soc_pct=60.0)
        # arithmetic mean = 70
        assert r.fleet_battery_soc == pytest.approx(70.0, abs=0.01)

    def test_empty_battery_falls_back_to_battery_soc(self):
        r = PowerReadings(battery_soc=85.0)
        assert r.fleet_battery_soc == 85.0


class TestInvariants:
    """Sum invariants pinned for the multi-device fleets."""

    @pytest.mark.parametrize("inverters", [
        [("a", 5000.0)],
        [("a", 5000.0), ("b", 3000.0)],
        [("a", 5000.0), ("b", 3000.0), ("c", 2500.0)],
        [("a", 5000.0), ("b", 0.0)],  # one offline
    ])
    def test_solar_invariant_sum_equals_field(self, inverters):
        """When sensor_reader populates both the dict and the cached
        sum, they must agree."""
        total = sum(w for _, w in inverters)
        r = PowerReadings(solar_power=total)
        for iid, w in inverters:
            r.inverters[iid] = InverterPower(inverter_id=iid, power_w=w)
        assert r.solar_power == pytest.approx(r.fleet_solar_w, abs=0.01)

    @pytest.mark.parametrize("batteries", [
        [("a", 2000.0)],
        [("a", 2000.0), ("b", -1500.0)],   # one charging, one discharging
        [("a", 0.0), ("b", 0.0)],          # both idle
        [("a", -3000.0), ("b", -1000.0)],  # both discharging
    ])
    def test_battery_invariant_sum_equals_field(self, batteries):
        total = sum(w for _, w in batteries)
        r = PowerReadings(battery_power=total)
        for bid, w in batteries:
            r.batteries[bid] = BatteryPower(battery_id=bid, power_w=w)
        assert r.battery_power == pytest.approx(r.fleet_battery_w, abs=0.01)


class TestBackwardCompatibility:
    """Existing consumers reading ``solar_power`` / ``battery_power``
    directly continue to work — the per-device dict is additive,
    never replaces the field."""

    def test_pre_v170_snapshot_works(self):
        """An installation that doesn't populate the dicts (single
        inverter, single battery) behaves exactly like pre-v1.7.0."""
        r = PowerReadings(solar_power=5000.0, battery_power=-1500.0)
        # Dicts empty
        assert r.inverters == {}
        assert r.batteries == {}
        # Direct field reads unchanged
        assert r.solar_power == 5000.0
        assert r.battery_power == -1500.0
        # @property accessors fall back to the field
        assert r.fleet_solar_w == 5000.0
        assert r.fleet_battery_w == -1500.0

    def test_calculate_derived_still_uses_solar_power(self):
        """The home consumption math uses ``solar_power`` directly.
        Adding the per-inverter dict must not change the result."""
        r = PowerReadings(
            solar_power=5000.0, grid_power=-1000.0, battery_power=0.0,
            ev_power=4000.0,
        )
        r.calculate_derived()
        home_no_dict = r.home_consumption_power

        # Same scenario but populate the inverter dict
        r2 = PowerReadings(
            solar_power=5000.0, grid_power=-1000.0, battery_power=0.0,
            ev_power=4000.0,
        )
        r2.inverters["a"] = InverterPower(inverter_id="a", power_w=3000.0)
        r2.inverters["b"] = InverterPower(inverter_id="b", power_w=2000.0)
        r2.calculate_derived()
        home_with_dict = r2.home_consumption_power

        assert home_no_dict == home_with_dict
