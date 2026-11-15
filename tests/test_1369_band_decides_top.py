"""(#1369) A hot water tank with a comfort band heats to the band's top.

A user set Keep at 52 °C (+4 extra) and the tank stopped at 50 °C: the old
Solar Heating Target (Configuration tab, default 50) capped it from outside
the band. Now the band decides alone — Keep at + Extra is the top — as on
the my-PV and evcc controllers. A tank without a band, a band whose
thermometer is silent, Legionella and the vacation dump are unchanged.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.devices.base import DeviceControlMode
from custom_components.solar_energy_management.devices.hot_water_controller import (
    HotWaterController,
)
from custom_components.solar_energy_management.tests.test_1062_hot_water_fields import (
    _Hass,
)

SENSOR = "sensor.tank"
SWITCH = "switch.boiler"


def _tank(hass, temp, *, band=True, solar_target=50.0, entity_id=SWITCH):
    """The reporter's numbers: Keep at 52, Extra 4, Run now past 36,
    Solar Heating Target left at its default 50."""
    if entity_id.startswith("switch."):
        hass.set(entity_id, "off")
    else:
        hass.set(entity_id, "off", current_temperature=temp, temperature=solar_target)
    if temp is None:
        hass.set(SENSOR, "unavailable")
    else:
        hass.set(SENSOR, str(temp), unit_of_measurement="°C")
    dev = HotWaterController(
        hass=hass, entity_id=entity_id, temperature_entity_id=SENSOR,
        solar_target_temp=solar_target, rated_power=3200.0,
        legionella_target_temp=60.0)
    dev.control_mode = DeviceControlMode.SURPLUS
    if band:
        dev.comfort_entity = SENSOR
        dev.comfort_target, dev.comfort_offset, dev.comfort_limit = 52.0, 4.0, 36.0
    dev.withheld_commands = []
    return dev


class TestTheBandDecidesTheTop:
    def test_between_the_old_target_and_the_band_top_it_may_heat(self):
        dev = _tank(_Hass(), 51.0)
        assert dev.band_top_c() == 56.0
        assert dev.is_temperature_safe() is True
        assert dev._last_temperature_safety_path == "normal_below_band_top"

    def test_at_the_band_top_it_stops(self):
        dev = _tank(_Hass(), 56.0)
        assert dev.is_temperature_safe() is False
        assert dev._last_temperature_safety_path == "normal_at_band_top"

    def test_a_setpoint_tank_is_sent_the_band_top(self):
        dev = _tank(_Hass(), 51.0, entity_id="water_heater.dhw")
        assert dev._active_target_temp() == 56.0

    def test_a_band_with_no_extra_tops_at_keep_at(self):
        dev = _tank(_Hass(), 51.0)
        dev.comfort_offset = 0.0
        assert dev.band_top_c() == 52.0


class TestWhatStaysAsBefore:
    def test_without_a_band_the_solar_target_caps(self):
        dev = _tank(_Hass(), 50.0, band=False)
        assert dev.band_top_c() is None
        assert dev.is_temperature_safe() is False
        assert dev._last_temperature_safety_path == "normal_at_solar_target"
        assert dev._active_target_temp() == 50.0

    def test_a_silent_thermometer_falls_back_to_the_solar_target(self):
        # the band is disengaged, so the band decides nothing; the tank's
        # own temperature attribute is read and capped as before
        dev = _tank(_Hass(), 51.0, entity_id="water_heater.dhw")
        dev.comfort_entity = "sensor.dead"
        assert dev.band_top_c() is None
        assert dev._active_target_temp() == 50.0

    def test_legionella_keeps_its_own_target(self):
        dev = _tank(_Hass(), 58.0)
        dev._legionella_cycle_active = True
        assert dev._active_target_temp() == 60.0
        assert dev.is_temperature_safe() is True

    def test_the_vacation_dump_keeps_the_minimum(self):
        dev = _tank(_Hass(), 51.0)
        dev.vacation, dev.vacation_dhw_surplus = True, True
        assert dev._active_target_temp() == dev.min_temperature

    def test_a_restart_readopts_a_boost_sent_at_the_band_top(self):
        hass = _Hass()
        dev = _tank(hass, 51.0, entity_id="water_heater.dhw")
        hass.set("water_heater.dhw", "eco", current_temperature=51.0,
                 temperature=56.0, operation_mode="eco")
        old = _tank(_Hass(), 51.0, entity_id="water_heater.dhw", band=False)
        # the band tank recognises 56 °C as its own boost; a tank without
        # a band does not (56 is neither its solar nor its Legionella target)
        assert dev._adoptable_now() is True
        old.hass = hass
        assert old._adoptable_now() is False


@pytest.mark.asyncio
async def test_the_engine_heats_past_50_on_the_sun():
    """End to end: 51 °C, 4 kW of sun — the run starts (before #1369 the
    tank refused at its 50 °C Solar Heating Target)."""
    hass = _Hass()
    dev = _tank(hass, 51.0)
    sc = SurplusController(hass)
    sc.register_device(dev)
    await sc.update(4000.0, price_level="normal", is_night=False,
                    battery_soc=50.0, battery_reserve_soc=10.0,
                    daylight_remaining_s=3600.0, solar_w=5000.0)
    assert hass.calls("turn_on"), hass.services.async_call.await_args_list
    assert dev.is_active


class TestReviewFindings:
    """(#1369 review) restart adoption, a cap, one thermometer."""

    def test_a_restart_readopts_even_while_the_band_thermometer_is_silent(self):
        hass = _Hass()
        dev = _tank(hass, 51.0, entity_id="water_heater.dhw")
        dev.comfort_entity = "sensor.band_not_up_yet"
        hass.set("water_heater.dhw", "eco", current_temperature=51.0,
                 temperature=56.0, operation_mode="eco")
        assert dev.band_top_c() is None          # disengaged for the cutoff
        assert dev._adoptable_now() is True      # but SEM's boost is still SEM's

    def test_the_top_never_passes_the_legionella_target(self):
        dev = _tank(_Hass(), 61.0)
        dev.comfort_target, dev.comfort_offset = 70.0, 10.0
        assert dev.band_top_c() == 60.0
        assert dev.is_temperature_safe() is False

    def test_the_cutoff_reads_the_band_thermometer(self):
        hass = _Hass()
        dev = _tank(hass, 51.0)
        dev.comfort_entity = "sensor.band"
        hass.set("sensor.band", "56.5", unit_of_measurement="°C")
        # the tank sensor says 51, the band's own thermometer says 56.5
        assert dev.is_temperature_safe() is False
        assert dev._last_temperature_safety_path == "normal_at_band_top"

    def test_a_misconfigured_band_has_no_top(self):
        dev = _tank(_Hass(), 51.0)
        dev.comfort_limit = 60.0   # limit above Keep at: disengaged
        assert dev._band_fields_top_c() is None
        assert dev.band_top_c() is None

    def test_away_keeps_the_old_target(self):
        dev = _tank(_Hass(), 51.0)
        dev.vacation = True
        assert dev.band_top_c() is None
        assert dev._active_target_temp() == 50.0
