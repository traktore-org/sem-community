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


# ── (#1369) the Legionella run may start early, never late ────────────────

from datetime import timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import patch  # noqa: E402

from custom_components.solar_energy_management.devices import hot_water_controller as hwc  # noqa: E402


def _since(dev, hours):
    dev._last_legionella_time = hwc.dt_util.now() - timedelta(hours=hours)


_T0 = hwc.dt_util.now()


async def _chk(dev, good, minute):
    """One Legionella check ``minute`` minutes into the test."""
    with patch.object(hwc.dt_util, "now", return_value=_T0 + timedelta(minutes=minute)):
        return await dev.check_legionella_cycle(good_hour=good)


class TestLegionellaEarly:
    @pytest.mark.asyncio
    async def test_a_good_hour_in_the_last_day_starts_it_early(self):
        dev = _tank(_Hass(), 48.0)
        _since(dev, dev.legionella_interval_hours - 10)
        assert dev.legionella_early_window and not dev.legionella_overdue
        # the good hour must hold 10 minutes first
        assert await _chk(dev, True, 0) is None
        assert await _chk(dev, True, 5) is None
        assert await _chk(dev, True, 10) == "legionella_started"
        assert dev._last_legionella_path == "early_start"
        assert dev.runs_without_surplus is True

    @pytest.mark.asyncio
    async def test_without_a_good_hour_it_waits_for_the_due_time(self):
        dev = _tank(_Hass(), 48.0)
        _since(dev, dev.legionella_interval_hours - 10)
        assert await dev.check_legionella_cycle(good_hour=False) is None
        assert dev.runs_without_surplus is False

    @pytest.mark.asyncio
    async def test_more_than_a_day_before_due_a_good_hour_does_nothing(self):
        dev = _tank(_Hass(), 48.0)
        _since(dev, dev.legionella_interval_hours - 30)
        assert await dev.check_legionella_cycle(good_hour=True) is None

    @pytest.mark.asyncio
    async def test_when_due_it_runs_as_before_whatever_the_hour(self):
        dev = _tank(_Hass(), 48.0)
        _since(dev, dev.legionella_interval_hours + 1)
        assert await dev.check_legionella_cycle(good_hour=False) == "legionella_started"
        assert dev._last_legionella_path == "overdue_start"

    @pytest.mark.asyncio
    async def test_no_early_start_without_a_reading_or_while_blocked_or_away(self):
        dev = _tank(_Hass(), None)
        _since(dev, dev.legionella_interval_hours - 10)
        assert await dev.check_legionella_cycle(good_hour=True) is None
        dev = _tank(_Hass(), 48.0)
        _since(dev, dev.legionella_interval_hours - 10)
        dev._legionella_blocked_until = hwc.dt_util.now() + timedelta(hours=5)
        assert await dev.check_legionella_cycle(good_hour=True) is None
        dev = _tank(_Hass(), 48.0)
        _since(dev, dev.legionella_interval_hours - 10)
        dev.vacation = True
        assert await dev.check_legionella_cycle(good_hour=True) != "legionella_started"


class TestTheGoodHour:
    def _coord(self, dev, level="normal"):
        from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator
        fake = SimpleNamespace(_surplus_controller=SimpleNamespace(_devices={"hot_water": dev}))
        return lambda surplus: SEMCoordinator._legionella_good_hour_now(
            fake, surplus, SimpleNamespace(tariff_price_level=level))

    def test_enough_sun_for_the_tank(self):
        f = self._coord(_tank(_Hass(), 48.0))
        assert f(3300.0) is True
        assert f(3100.0) is False   # rated 3200: the surplus alone decides
        assert f(1500.0) is False
        assert f(None) is False

    def test_a_cheap_hour(self):
        assert self._coord(_tank(_Hass(), 48.0), "cheap")(0.0) is True


# ── (#1369) heating that does not warm the tank ────────────────────────────

class TestHeatingWorks:
    def _running(self, temp, watts=3200.0):
        hass = _Hass()
        dev = _tank(hass, temp)
        dev.power_entity_id = "sensor.boiler_power"
        hass.set("sensor.boiler_power", str(watts), unit_of_measurement="W")
        dev.state = hwc.DeviceState.ACTIVE if hasattr(hwc, "DeviceState") else dev.state
        return hass, dev

    def _at(self, minutes):
        return patch.object(hwc.dt_util, "now",
                            return_value=self._t0 + timedelta(minutes=minutes))

    def setup_method(self):
        self._t0 = hwc.dt_util.now()

    def _go(self, dev, hass, minutes, temp):
        hass.set(SENSOR, str(temp), unit_of_measurement="°C")
        with self._at(minutes), patch.object(type(dev), "is_active", new=True):
            return dev.check_heating_works()

    def test_an_hour_of_draw_without_warming_is_a_fault(self):
        hass, dev = self._running(40.0)
        assert self._go(dev, hass, 0, 40.0) is None
        assert self._go(dev, hass, 30, 40.3) is None
        assert self._go(dev, hass, 61, 40.5) is None      # an hour: not yet
        assert self._go(dev, hass, 121, 40.6) is True
        assert dev.heating_fault is True
        assert self._go(dev, hass, 130, 40.6) is None     # said once
        assert self._go(dev, hass, 150, 41.7) is False    # warms again: clears
        assert dev.heating_fault is False

    def test_a_warming_tank_is_fine(self):
        hass, dev = self._running(40.0)
        self._go(dev, hass, 0, 40.0)
        assert self._go(dev, hass, 61, 43.0) is False   # first rise: clear once
        assert self._go(dev, hass, 121, 45.0) is None
        assert dev.heating_fault is False

    def test_no_measured_draw_is_never_blamed(self):
        hass, dev = self._running(40.0, watts=0.0)
        self._go(dev, hass, 0, 40.0)
        assert self._go(dev, hass, 240, 40.0) is None
        dev2 = _tank(_Hass(), 40.0)       # no power sensor, no counter
        with patch.object(type(dev2), "is_active", new=True):
            assert dev2.check_heating_works() is None

    def test_near_its_target_no_fault(self):
        hass, dev = self._running(55.0)
        self._go(dev, hass, 0, 55.0)
        assert self._go(dev, hass, 121, 55.2) is None   # top 56: within 2 K


class TestReviewRound2:
    @pytest.mark.asyncio
    async def test_an_early_run_stops_when_its_good_hour_ends(self):
        dev = _tank(_Hass(), 48.0)
        _since(dev, dev.legionella_interval_hours - 10)
        await _chk(dev, True, 0)
        assert await _chk(dev, True, 10) == "legionella_started"
        assert await _chk(dev, True, 11) == "legionella_heating"
        # a passing cloud does not stop it: the good hour must be gone 15 min
        assert await _chk(dev, False, 12) == "legionella_heating"
        assert await _chk(dev, True, 14) == "legionella_heating"
        assert await _chk(dev, False, 15) == "legionella_heating"
        assert await _chk(dev, False, 31) == "legionella_early_paused"
        assert dev.runs_without_surplus is False
        assert dev._legionella_blocked_until is None      # no penalty
        # and at the due time it runs as before
        _since(dev, dev.legionella_interval_hours + 1)
        assert await dev.check_legionella_cycle(good_hour=False) == "legionella_started"
        assert await dev.check_legionella_cycle(good_hour=False) == "legionella_heating"

    def test_a_restart_still_clears_an_old_repair(self):
        hass = _Hass()
        dev = _tank(hass, 40.0)
        dev.power_entity_id = "sensor.boiler_power"
        hass.set("sensor.boiler_power", "3200", unit_of_measurement="W")
        t0 = hwc.dt_util.now()
        for m, temp in ((0, 40.0), (30, 41.2)):
            hass.set(SENSOR, str(temp), unit_of_measurement="°C")
            with patch.object(hwc.dt_util, "now", return_value=t0 + timedelta(minutes=m)), \
                    patch.object(type(dev), "is_active", new=True):
                out = dev.check_heating_works()
        assert out is False   # fresh process, tank warms: the clear goes out once

    def test_a_setpoint_tank_is_not_checked(self):
        hass = _Hass()
        dev = _tank(hass, 40.0, entity_id="water_heater.dhw")
        dev.power_entity_id = "sensor.hp_power"
        hass.set("sensor.hp_power", "3200", unit_of_measurement="W")
        with patch.object(type(dev), "is_active", new=True):
            assert dev.check_heating_works() is None
        assert dev._heat_check is None


class TestEverythingIsSaid:
    """(#1369) No hidden rule: the logbook and the card name each reason."""

    @pytest.mark.asyncio
    async def test_an_early_start_has_its_own_reason(self):
        from custom_components.solar_energy_management.coordinator import reason_codes as RC
        from custom_components.solar_energy_management.coordinator.surplus_controller import (
            compute_load_intent)
        dev = _tank(_Hass(), 48.0)
        _since(dev, dev.legionella_interval_hours - 10)
        await _chk(dev, True, 0)
        await _chk(dev, True, 10)
        intent = compute_load_intent(dev, remaining_surplus_w=0.0, tier1_headroom_w=0.0,
                                     price_is_cheap=False, peak_freeze=False, is_night=True)
        assert intent.on is True
        assert intent.code == RC.LOAD_LEGIONELLA_EARLY

    def test_the_card_gets_every_fact_it_says(self):
        from custom_components.solar_energy_management.features.device_registry import (
            UnifiedDeviceRegistry)
        dev = _tank(_Hass(), 50.0)
        dev.comfort_target, dev.comfort_offset = 70.0, 10.0
        lines = UnifiedDeviceRegistry._band_lines(dev)
        assert lines["max_c"] == 60.0            # capped like the engine
        assert lines["own_run_early"] is False
        assert lines["heating_fault"] is False
        _since(dev, dev.legionella_interval_hours - 10)
        assert UnifiedDeviceRegistry._band_lines(dev)["own_run_soon"] is True
        dev.heating_fault = True
        assert UnifiedDeviceRegistry._band_lines(dev)["heating_fault"] is True

    def test_every_new_text_exists_in_every_language(self):
        import json
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        d = json.loads((root / "dashboard" / "translations.json").read_text())
        keys = ["hq_st_legionella_early", "hq_st_legionella_soon", "hq_st_no_rise",
                "why_reason_" + "legionella_early"]
        for lang, table in d.items():
            for k in keys:
                assert table.get(k), (lang, k)


class TestReviewRound3:
    @pytest.mark.asyncio
    async def test_a_flickering_good_hour_never_starts_it(self):
        dev = _tank(_Hass(), 48.0)
        _since(dev, dev.legionella_interval_hours - 10)
        for m in range(0, 60, 3):
            out = await _chk(dev, m % 6 == 0, m)   # good, bad, good, bad …
            assert out is None, m

    @pytest.mark.asyncio
    async def test_a_running_early_run_keeps_its_reason(self):
        from custom_components.solar_energy_management.coordinator import reason_codes as RC
        from custom_components.solar_energy_management.coordinator.surplus_controller import (
            compute_load_intent)
        hass = _Hass()
        dev = _tank(hass, 48.0)
        _since(dev, dev.legionella_interval_hours - 10)
        await _chk(dev, True, 0)
        await _chk(dev, True, 10)
        with patch.object(type(dev), "is_active", new=True):
            intent = compute_load_intent(dev, remaining_surplus_w=0.0, is_night=True)
        assert intent.code == RC.LOAD_LEGIONELLA_EARLY

    @pytest.mark.asyncio
    async def test_a_restart_drops_an_early_run_it_does_not_relabel_it(self):
        dev = _tank(_Hass(), 48.0)
        _since(dev, dev.legionella_interval_hours - 10)
        await _chk(dev, True, 0)
        await _chk(dev, True, 10)
        # a restart: a new controller with only the stored last-run time
        again = _tank(_Hass(), 48.0)
        again._last_legionella_time = dev._last_legionella_time
        assert again.runs_without_surplus is False
        assert getattr(again, "_legionella_early", False) is False
        assert await _chk(again, False, 11) is None      # not due: no run


class TestLostcontrolsSetup:
    """(#1369 challenge against #1102) Keep at 52, Extra 4, Run now past 36,
    a switch boiler, Legionella target 60 — and a "Stop when" at 53 °C on
    the tank's own thermometer."""

    def _his(self, temp=50.0):
        dev = _tank(_Hass(), temp)
        dev.stop_entity, dev.stop_at = SENSOR, 53.0
        return dev

    def test_the_card_names_the_real_top(self):
        from custom_components.solar_energy_management.features.device_registry import (
            UnifiedDeviceRegistry)
        lines = UnifiedDeviceRegistry._band_lines(self._his())
        assert lines["max_c"] == 53.0           # his stop, not 56
        assert lines["legionella_blocked"] is True
        assert (lines["stop_c"], lines["legionella_c"]) == (53.0, 60.0)

    @pytest.mark.asyncio
    async def test_no_early_run_that_could_never_finish(self):
        dev = self._his(48.0)
        _since(dev, dev.legionella_interval_hours - 10)
        assert dev.legionella_early_window is False
        await _chk(dev, True, 0)
        assert await _chk(dev, True, 10) is None
        assert dev.runs_without_surplus is False

    def test_a_stop_on_another_sensor_changes_nothing(self):
        dev = self._his()
        dev.stop_entity = "sensor.room"
        assert dev.user_stop_c() is None
        assert dev.legionella_blocked_by_stop is False

    def test_a_stop_above_the_target_does_not_block(self):
        dev = self._his()
        dev.stop_at = 62.0
        assert dev.legionella_blocked_by_stop is False
