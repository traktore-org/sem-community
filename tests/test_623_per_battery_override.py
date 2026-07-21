"""Regression tests for #623 — a per-unit surface suppressed by a fleet override.

RienduPre's install: a 2×Sessy Energy-Dashboard battery fleet that ALSO sets
the explicit SEM ``battery_power_sensor`` combined override. After #597 every
individual battery sensor (``sensor.sem_battery_b1_power`` …) went
``unavailable`` — "lost my individual battery information somewhere during the
1.7.5 betas".

Root shape (bug class 16 — *per-unit surface suppressed by a higher-precedence
fleet override*): the per-UNIT population (``readings.batteries`` /
``readings.inverters``) lived INSIDE the fleet-scalar if/elif chain, so the
override branch — inserted at the TOP of that chain by #597 (battery) / #592
(solar) — short-circuited *before* the per-unit loop ran. The per-battery SOC
path and the per-PV-string surface were already decoupled and were unaffected.

Closure: per-unit population is decoupled from fleet-scalar selection — it runs
whenever the ED exposes ≥2 units, and the per-unit sum owns the fleet scalar
(the override applies only when there is no ≥2 breakdown). This preserves the
#589 ``fleet == sum(per-unit)`` consistency-by-construction invariant AND the
#597/#592 energy-only override for single/combined installs.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.ha_energy_reader import (
    EnergyDashboardConfig,
)


def _state(value, unit="W"):
    s = MagicMock()
    s.state = str(value)
    s.attributes = {"unit_of_measurement": unit}
    return s


def _reader(mock_hass, states, config=None):
    def mock_get(entity_id):
        return states.get(entity_id)

    mock_hass.states.get = MagicMock(side_effect=mock_get)
    mock_hass.states.async_all = MagicMock(return_value=[])
    reader = SensorReader(mock_hass, config or {})
    reader._sign_vote_warmup = 0
    return reader


class Test623BatteryOverrideKeepsPerBattery:
    def test_two_batteries_with_combined_override_still_populate_per_battery(
        self, mock_hass
    ):
        """#623 — 2×Sessy ED fleet + a combined ``battery_power_sensor``
        override. The override must NOT suppress the per-battery surface."""
        states = {
            "sensor.sessy1_power": _state(500),
            "sensor.sessy2_power": _state(300),
            # Deliberately DISTINCT from the per-battery sum (800) so the
            # assertions prove the per-battery breakdown owns the fleet scalar,
            # not the override — the override must not silently win here.
            "sensor.actueel_battery_total_charge": _state(12345),
        }
        reader = _reader(
            mock_hass,
            states,
            config={"battery_power_sensor": "sensor.actueel_battery_total_charge"},
        )
        ed = EnergyDashboardConfig(
            battery_power="sensor.sessy1_power",
            battery_power_list=["sensor.sessy1_power", "sensor.sessy2_power"],
            has_battery=True,
            has_solar=False,
            has_grid=False,
        )
        reader.set_energy_dashboard_config(ed)
        readings = reader._read_from_energy_dashboard()

        # The regression: readings.batteries was empty → every b1/b2 sensor
        # read ``unavailable``.
        assert set(readings.batteries.keys()) == {"b1", "b2"}
        assert readings.batteries["b1"].power_w == 500.0
        assert readings.batteries["b2"].power_w == 300.0
        # Fleet == sum(per-battery) — consistency-by-construction (#589).
        assert readings.battery_power == 800.0

    def test_single_combined_battery_override_unchanged_597(self, mock_hass):
        """#597 must still hold: an energy-only ED (no per-battery power list)
        uses the override for the fleet scalar, with no per-battery surface."""
        states = {"sensor.batt_override": _state(-1800)}
        reader = _reader(
            mock_hass,
            states,
            config={"battery_power_sensor": "sensor.batt_override"},
        )
        ed = EnergyDashboardConfig(
            battery_power=None,  # batt:pwr=none (Huawei)
            battery_power_list=[],
            has_battery=True,
            has_solar=False,
            has_grid=False,
        )
        reader.set_energy_dashboard_config(ed)
        readings = reader._read_from_energy_dashboard()

        assert readings.battery_power == -1800.0
        assert readings.batteries == {}


class Test623SolarOverrideKeepsPerInverter:
    def test_two_inverters_with_override_still_populate_per_inverter(
        self, mock_hass
    ):
        """Sibling sweep (#592 solar override): a 2-inverter ED fleet + a solar
        override must keep the per-inverter dict so ``solar_power ==
        fleet_solar_w`` (types.py pin) holds by construction."""
        states = {
            "sensor.inv1_power": _state(3000),
            "sensor.inv2_power": _state(2000),
            # Distinct from the per-inverter sum (5000) so the assertions prove
            # the per-inverter sum owns the fleet scalar, not the override.
            "sensor.total_solar": _state(9999),
        }
        reader = _reader(
            mock_hass,
            states,
            config={"solar_production_sensor": "sensor.total_solar"},
        )
        ed = EnergyDashboardConfig(
            solar_power="sensor.inv1_power",
            solar_power_list=["sensor.inv1_power", "sensor.inv2_power"],
            has_solar=True,
            has_grid=False,
            has_battery=False,
        )
        reader.set_energy_dashboard_config(ed)
        readings = reader._read_from_energy_dashboard()

        assert set(readings.inverters.keys()) == {
            "sensor.inv1_power",
            "sensor.inv2_power",
        }
        assert readings.solar_power == 5000.0
        assert readings.solar_power == readings.fleet_solar_w

    def test_single_solar_override_unchanged_592(self, mock_hass):
        """#592 must still hold: an energy-only ED (no per-inverter power list)
        uses the override for the fleet scalar, with no per-inverter surface."""
        states = {"sensor.total_solar": _state(4000)}
        reader = _reader(
            mock_hass,
            states,
            config={"solar_production_sensor": "sensor.total_solar"},
        )
        ed = EnergyDashboardConfig(
            solar_power=None,  # ED exposes solar energy only
            solar_power_list=[],
            has_solar=True,
            has_grid=False,
            has_battery=False,
        )
        reader.set_energy_dashboard_config(ed)
        readings = reader._read_from_energy_dashboard()

        assert readings.solar_power == 4000.0
        assert readings.inverters == {}
