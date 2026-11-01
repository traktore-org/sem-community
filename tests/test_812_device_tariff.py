"""#812 — a tariff per device (a heat pump on its own meter and price).

A German "Messkonzept 8" house buys the heat pump's kWh on a second, cheaper
contract with its own meter. SEM assumed one import price for the house. A
device may now name its own tariff: a fixed rate or a price entity, and
optionally its own meter.

* none set = the house tariff, exactly as before;
* a fixed rate prices the device's grid kWh and reads ``normal`` — a flat
  price has nothing to compare against, so it is never cheap (#994);
* a price entity is classified by the house classifier, so the device's
  cheap hours follow its own curve;
* the cost sensor exists only when a tariff is set;
* the settings are in the options flow AND the cards.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator.device_tariff import (
    LEVEL_FIXED, DeviceCycle, DeviceTariffs, apply_tariff, device_price_level, grid_share,
    heat_pump_tariff, tariff_of,
)
from custom_components.solar_energy_management.coordinator.decision_log import (
    DecisionLog, record_load,
)
from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.price_signal import (
    is_cheap_name,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.devices.base import DeviceControlMode

ROOT = Path(__file__).resolve().parents[1]
H = 3600.0

#: 24 hourly prices starting NOW — now is the cheapest hour.
CURVE_CHEAP_NOW = [0.05] + [0.30 + 0.01 * i for i in range(23)]
#: …and one where now is the dearest hour.
CURVE_DEAR_NOW = [0.60] + [0.10 + 0.01 * i for i in range(23)]


def _load(device_id="pump", min_power=731, *, rate=None, entity=None,
          meter=None, deficit_s=4 * H):
    """A cheap-hours load (the #953 shape), optionally on its own tariff."""
    d = MagicMock()
    d.device_id = device_id
    d.name = device_id
    d.priority = 1
    d.min_power_threshold = min_power
    d.rated_power = min_power
    d.is_enabled = True
    d.managed_externally = False
    d.is_active = False
    d.device_type = MagicMock(value="switch")
    d.control_mode = DeviceControlMode.SURPLUS
    d._sem_owned = False
    d.battery_assist_enabled = False
    d.battery_eligible_overnight = False
    d.top_up_policy = "cheap_hours"
    d.remaining_daily_runtime_sec = deficit_s
    d.has_runtime_deficit = deficit_s > 0
    d.needs_offpeak_activation = deficit_s > 0
    d.activate = AsyncMock(return_value=min_power)
    d.adjust_power = AsyncMock(return_value=min_power)
    d.get_current_consumption = MagicMock(return_value=0.0)
    d.can_activate = MagicMock(return_value=True)
    d.can_deactivate = MagicMock(return_value=True)
    d.status = MagicMock()
    d.status.allocated_power_w = 0.0
    d._offpeak_forced = False
    d._offpeak_forced_date = None
    d._batt_overnight_forced = False
    d._batt_overnight_forced_date = None
    d._daily_runtime_meter_day = None
    d.daily_targets_met = False
    d.daily_max_runtime_reached = False
    d.stop_condition_met = False
    d.is_deadline_approaching = False
    d.start_reserve_w = 0.0
    d.comfort_state = ""
    d.__class__ = MagicMock

    async def _deact():
        d.is_active = False
    d.deactivate = AsyncMock(side_effect=_deact)
    # the tariff fields as a real device carries them (class defaults)
    d.tariff_rate, d.tariff_entity, d.tariff_meter = 0.0, "", ""
    d._tariff_level, d.tariff_inputs = None, None
    apply_tariff(d, {k: v for k, v in (("tariff_rate", rate),
                                       ("tariff_entity", entity),
                                       ("tariff_meter", meter)) if v is not None})
    return d


def _price_state(curve, state=None):
    now = dt_util.now().replace(minute=0, second=0, microsecond=0)
    raw = [{"start": (now + timedelta(hours=i)).isoformat(), "value": v}
           for i, v in enumerate(curve)]
    return SimpleNamespace(state=str(curve[0] if state is None else state),
                           attributes={"raw_today": raw})


def _hass_with(states: dict):
    hass = MagicMock()
    hass.states.get = lambda eid: states.get(eid)
    return hass


async def _night_cycle(sc, price_level):
    await sc.update(0.0, price_level=price_level, reclaim_w=0.0,
                    battery_priority=100, battery_soc=80.0,
                    battery_reserve_soc=10.0, is_night=True,
                    daylight_remaining_s=0.0)


# ── 1. default = the house tariff, exactly ───────────────────────────────


@pytest.mark.unit
class TestNoTariffIsTheHouseTariff:
    def test_a_device_without_one_reads_the_house_level(self):
        d = _load()
        DeviceTariffs(None).stamp([d])
        assert d._tariff_level is None and d.tariff_inputs is None
        for house in ("cheap", "normal", "expensive", "flat", None):
            assert device_price_level(d, house) == house

    async def test_the_cheap_hour_still_starts_the_load(self, mock_hass):
        sc = SurplusController(mock_hass, regulation_offset=0)
        pump = _load()
        sc.register_device(pump)
        await _night_cycle(sc, "cheap")
        pump.activate.assert_awaited_once()

    async def test_a_normal_hour_still_does_not(self, mock_hass):
        sc = SurplusController(mock_hass, regulation_offset=0)
        pump = _load()
        sc.register_device(pump)
        await _night_cycle(sc, "normal")
        assert not pump.activate.called

    def test_nothing_is_booked_and_no_inputs_change(self):
        tariffs = DeviceTariffs(None)
        d = _load()
        assert tariffs.cycle([d], {}, dt_util.now()) == []
        assert tariffs.price_now(d) is None
        log = DecisionLog(None)
        log.set_inputs({"import_price": 0.30, "price_level": "cheap"})
        rec = record_load(log, d, on=True)
        assert rec.inputs == {"import_price": 0.30, "price_level": "cheap"}

    def test_a_mock_attribute_is_not_a_tariff(self):
        """A device that never set the fields must not read as configured
        because a test double answers every attribute."""
        assert not tariff_of(MagicMock()).configured


# ── 2. a fixed rate: priced, and "normal" ────────────────────────────────


@pytest.mark.unit
class TestAFixedRate:
    def test_it_reads_normal_never_cheap(self):
        d = _load(rate=0.21)
        tariffs = DeviceTariffs(None)
        assert tariffs.level(d) == LEVEL_FIXED == "normal"
        tariffs.stamp([d])
        assert device_price_level(d, "cheap") == "normal"
        assert not is_cheap_name(device_price_level(d, "very_cheap"))

    async def test_a_cheap_house_hour_does_not_start_it(self, mock_hass):
        sc = SurplusController(mock_hass, regulation_offset=0)
        pump = _load(rate=0.21)
        sc.register_device(pump)
        await _night_cycle(sc, "cheap")
        assert not pump.activate.called

    async def test_a_running_top_up_ends_with_its_own_reason(self, mock_hass):
        sc = SurplusController(mock_hass, regulation_offset=0)
        pump = _load(rate=0.21, deficit_s=3 * H)
        pump.is_active = True
        pump._sem_owned = True
        pump._offpeak_forced = True
        pump._daily_runtime_meter_day = dt_util.now().date()
        pump._offpeak_forced_date = pump._daily_runtime_meter_day
        pump.needs_offpeak_activation = False
        pump.get_current_consumption = MagicMock(return_value=731.0)
        sc.register_device(pump)
        await _night_cycle(sc, "cheap")
        assert pump.deactivate.called

    def test_its_price_is_the_rate(self):
        d = _load(rate=0.20)
        assert DeviceTariffs(None).price_now(d) == pytest.approx(0.20)
        assert grid_share(800.0, 2000.0) == pytest.approx(0.4)

    def test_the_log_shows_the_device_price(self):
        d = _load(rate=0.20)
        DeviceTariffs(None).stamp([d])
        log = DecisionLog(None)
        log.set_inputs({"import_price": 0.30, "price_level": "cheap", "soc": 50})
        rec = record_load(log, d, on=True)
        assert rec.inputs["import_price"] == pytest.approx(0.20)
        assert rec.inputs["price_level"] == "normal"
        assert rec.inputs["soc"] == 50       # the house context stays


# ── 3. a price entity: its own curve gates it ────────────────────────────


@pytest.mark.unit
class TestAPriceEntity:
    async def test_its_cheap_hour_starts_it_when_the_house_is_normal(self, mock_hass):
        mock_hass.states.get = lambda eid: (
            _price_state(CURVE_CHEAP_NOW) if eid == "sensor.hp_price" else None)
        sc = SurplusController(mock_hass, regulation_offset=0)
        pump = _load(entity="sensor.hp_price")
        sc.register_device(pump)
        await _night_cycle(sc, "normal")
        assert is_cheap_name(pump._tariff_level), pump._tariff_level
        pump.activate.assert_awaited_once()

    async def test_its_dear_hour_holds_it_when_the_house_is_cheap(self, mock_hass):
        mock_hass.states.get = lambda eid: (
            _price_state(CURVE_DEAR_NOW) if eid == "sensor.hp_price" else None)
        sc = SurplusController(mock_hass, regulation_offset=0)
        pump = _load(entity="sensor.hp_price")
        sc.register_device(pump)
        await _night_cycle(sc, "cheap")
        assert not is_cheap_name(pump._tariff_level)
        assert not pump.activate.called

    def test_the_house_classifier_is_reused_not_copied(self):
        from custom_components.solar_energy_management.tests.ast_contracts import calls
        assert calls(DeviceTariffs.provider_for, "DynamicTariffProvider")
        assert calls(DeviceTariffs.level, "comparative_level")
        assert calls(DeviceTariffs.level, "absence_word")

    def test_an_unreadable_entity_is_not_cheap_and_falls_back_to_the_rate(self):
        d = _load(rate=0.19, entity="sensor.hp_price")
        tariffs = DeviceTariffs(_hass_with({
            "sensor.hp_price": SimpleNamespace(state="unavailable", attributes={})}))
        assert not is_cheap_name(tariffs.level(d))
        assert tariffs.price_now(d) == pytest.approx(0.19)

    def test_the_price_is_the_entity_state(self):
        d = _load(entity="sensor.hp_price")
        tariffs = DeviceTariffs(_hass_with({"sensor.hp_price": _price_state(CURVE_CHEAP_NOW)}))
        assert tariffs.price_now(d) == pytest.approx(0.05)


# ── 4. the own meter: a stamped, plausible step ──────────────────────────

T_NOON = datetime(2026, 10, 3, 12, 0, 0)


def _meter(value):
    return {"sensor.hp_meter": SimpleNamespace(state=str(value), attributes={})}


def _read(d, store, value, at, *, entity="sensor.hp_meter"):
    """Read the meter and, as the booking does, keep the baseline."""
    step, baseline = DeviceTariffs(_hass_with({
        entity: SimpleNamespace(state=str(value), attributes={})})).meter_step(
            d, store, at)
    if baseline is not None:
        store[d.device_id] = baseline
    return step


@pytest.mark.unit
class TestTheOwnMeter:
    def _pump(self):
        d = _load("heat_pump", rate=0.20, meter="sensor.hp_meter")
        d.rated_power = 3000.0
        return d

    def test_a_plausible_step_is_the_use(self):
        store, d = {}, self._pump()
        assert _read(d, store, 100.0, T_NOON) is None
        # 0.04 kWh in 1 min: under 3 kW × 1 min = 0.05
        assert _read(d, store, 100.04, T_NOON + timedelta(minutes=1)) == pytest.approx(0.04)

    def test_reading_alone_does_not_move_the_baseline(self):
        store, d = {}, self._pump()
        _read(d, store, 100.0, T_NOON)
        DeviceTariffs(_hass_with(_meter(100.04))).meter_step(
            d, store, T_NOON + timedelta(minutes=1))
        assert store["heat_pump"]["value"] == pytest.approx(100.0)

    def test_an_implausible_step_rebaselines_and_says_so(self, caplog):
        store, d = {}, self._pump()
        _read(d, store, 100.0, T_NOON)
        with caplog.at_level("INFO"):
            step = _read(d, store, 103.0, T_NOON + timedelta(minutes=1))
        assert step is None and "re-baselined" in caplog.text
        assert store["heat_pump"]["value"] == pytest.approx(103.0)

    def test_midnight_is_no_boundary(self):
        store, d = {}, self._pump()
        _read(d, store, 100.0, datetime(2026, 10, 3, 23, 59, 30))
        assert _read(d, store, 100.02, datetime(2026, 10, 4, 0, 0, 0)) == \
            pytest.approx(0.02)

    def test_a_restart_loses_nothing(self):
        store, d = {}, self._pump()
        _read(d, store, 100.0, T_NOON)
        calc = EnergyCalculator({}, MagicMock())
        calc.device_meter_last = store
        fresh = EnergyCalculator({}, MagicMock())
        fresh.restore_state(calc.get_state())
        assert fresh.device_meter_last["heat_pump"]["entity"] == "sensor.hp_meter"
        assert _read(d, fresh.device_meter_last, 100.5,
                     T_NOON + timedelta(minutes=30)) == pytest.approx(0.5)
        # after days off the step is still plausible for the time that passed
        assert _read(d, fresh.device_meter_last, 130.0,
                     T_NOON + timedelta(days=3)) == pytest.approx(29.5)

    def test_a_swapped_meter_entity_rebaselines(self):
        store, d = {}, self._pump()
        _read(d, store, 100.0, T_NOON)
        d.tariff_meter = "sensor.hp_meter_new"
        assert _read(d, store, 100.02, T_NOON + timedelta(minutes=1),
                     entity="sensor.hp_meter_new") is None
        assert store["heat_pump"]["entity"] == "sensor.hp_meter_new"


# ── 5. the books: split in the one import booking ────────────────────────

_CALC_DT = "custom_components.solar_energy_management.coordinator.energy_calculator.dt_util"


def _cycle(calc, now, *, import_w, home_w=None, grid_to_home=None, entries=()):
    """One real ``calculate_energy`` cycle at ``now``."""
    from unittest.mock import patch

    from custom_components.solar_energy_management.coordinator.types import (
        PowerReadings,
    )
    p = PowerReadings(solar_power=0.0, grid_power=-float(import_w))
    p.calculate_derived()
    home = float(import_w if home_w is None else home_w)
    p.home_consumption_power = home
    flows = SimpleNamespace(grid_to_home=float(import_w if grid_to_home is None
                                               else grid_to_home),
                            solar_to_home=0.0, solar_to_ev=0.0, grid_to_ev=0.0,
                            grid_to_battery=0.0, battery_to_home=0.0,
                            battery_to_ev=0.0, solar_to_battery=0.0,
                            solar_to_grid=0.0, battery_to_grid=0.0)
    calc.set_device_tariff_cycle(list(entries))
    with patch(_CALC_DT) as dt:
        dt.now.return_value = now
        calc.calculate_energy(p, flows)


def _calc(rate):
    calc = EnergyCalculator({"update_interval": 3600}, MagicMock())
    calc._import_rate = rate
    return calc


@pytest.mark.unit
class TestTheBooks:
    def test_no_device_is_todays_number(self):
        calc = _calc(0.30)
        _cycle(calc, T_NOON, import_w=2000.0)        # 1 h at 2 kW
        assert calc._get_daily_cost("cost_import", T_NOON.date()) == pytest.approx(0.60)

    def test_the_cycle_is_split_where_it_is_booked(self):
        calc = _calc(0.30)
        pump = DeviceCycle("heat_pump", power_w=1000.0, price=0.20)
        # 2 kW import, all of the house from the grid: the pump's 1 kWh at 0.20
        _cycle(calc, T_NOON, import_w=2000.0, entries=[pump])
        day = T_NOON.date()
        assert calc._get_daily_cost("cost_import", day) == pytest.approx(0.50)
        assert calc.get_device_tariff("heat_pump", day) == {
            "daily_grid_kwh": pytest.approx(1.0), "daily_cost": pytest.approx(0.20)}

    def test_only_the_grids_share_is_the_devices(self):
        calc = _calc(0.30)
        pump = DeviceCycle("heat_pump", power_w=1000.0, price=0.20)
        _cycle(calc, T_NOON, import_w=1000.0, home_w=2000.0, grid_to_home=1000.0,
               entries=[pump])
        assert calc.get_device_tariff("heat_pump", T_NOON.date())["daily_grid_kwh"] == \
            pytest.approx(0.5)

    def test_a_negative_price_day_counts_each_kwh_once(self):
        calc = _calc(-0.10)
        pump = DeviceCycle("heat_pump", power_w=1000.0, price=0.20)
        _cycle(calc, T_NOON, import_w=2000.0, entries=[pump])
        # 1 kWh house at −0.10 + 1 kWh pump at 0.20
        assert calc._get_daily_cost("cost_import", T_NOON.date()) == pytest.approx(0.10)

    def test_the_house_never_pays_less_than_its_own_kwh(self):
        # the reviewer's case: imported at 0.10, the rate later 0.40, the pump
        # bills at 0.05 — every kWh is priced in its own cycle, nothing moves
        calc = _calc(0.10)
        _cycle(calc, T_NOON, import_w=1000.0)
        calc._import_rate = 0.40
        # the next cycle, 2 min later: 30 kW for 2 min = 1 kWh, all the pump's
        pump = DeviceCycle("heat_pump", power_w=30000.0, price=0.05)
        _cycle(calc, T_NOON + timedelta(minutes=2), import_w=30000.0, entries=[pump])
        assert calc._get_daily_cost("cost_import", T_NOON.date()) == pytest.approx(0.15)

    def test_a_solar_fed_step_books_only_its_grid_share(self):
        calc = _calc(0.30)
        # 1.5 kWh on the meter; the grid carried a quarter of the house
        _cycle(calc, T_NOON, import_w=500.0, home_w=2000.0, grid_to_home=500.0,
               entries=[DeviceCycle("heat_pump", meter=True, meter_kwh=1.5,
                                    price=0.20)])
        day = T_NOON.date()
        assert calc.get_device_tariff("heat_pump", day)["daily_grid_kwh"] == \
            pytest.approx(0.375, abs=0.006)
        # the rest of the 0.5 kWh import is the house's
        assert calc._get_daily_cost("cost_import", day) == pytest.approx(
            0.375 * 0.20 + 0.125 * 0.30, abs=0.006)

    def test_a_step_is_booked_in_its_own_cycle(self):
        calc = _calc(0.30)
        _cycle(calc, datetime(2026, 10, 3, 23, 59, 0), import_w=0.0)
        after = datetime(2026, 10, 4, 0, 0, 0)
        # 1 min at 60 kW = 1 kWh imported, all of the house from the grid
        _cycle(calc, after, import_w=60000.0,
               entries=[DeviceCycle("heat_pump", meter=True, meter_kwh=0.4, price=0.20)])
        assert calc.get_device_tariff("heat_pump", after.date())["daily_grid_kwh"] == \
            pytest.approx(0.4)
        assert calc._get_daily_cost("cost_import", after.date()) == pytest.approx(
            0.4 * 0.20 + 0.6 * 0.30)

    def test_two_devices_share_the_import_in_proportion(self):
        def run(order):
            calc = _calc(0.30)
            # 1 kWh imported; the two want 1.5 and 0.5 kWh of grid → 3:1
            _cycle(calc, T_NOON, import_w=1000.0, entries=order)
            day = T_NOON.date()
            return (calc.get_device_tariff("a", day)["daily_grid_kwh"],
                    calc.get_device_tariff("b", day)["daily_grid_kwh"],
                    calc._get_daily_cost("cost_import", day))
        a = DeviceCycle("a", meter=True, meter_kwh=1.5, price=0.10)
        b = DeviceCycle("b", meter=True, meter_kwh=0.5, price=0.20)
        assert run([a, b]) == run([b, a])
        ka, kb, cost = run([a, b])
        assert (ka, kb) == (pytest.approx(0.75, abs=0.006),
                            pytest.approx(0.25, abs=0.006))
        assert cost == pytest.approx(0.75 * 0.10 + 0.25 * 0.20, abs=0.006)

    def test_an_early_return_leaves_the_step_for_the_next_cycle(self):
        from custom_components.solar_energy_management.coordinator.device_tariff import (
            DeviceTariffs as DT,
        )
        calc = _calc(0.30)
        d = _load("heat_pump", rate=0.20, meter="sensor.hp_meter")
        d.rated_power = 3000.0
        _read(d, calc.device_meter_last, 100.0, T_NOON)
        _cycle(calc, T_NOON, import_w=0.0)
        # a 5-min gap: calculate_energy skips the cycle; the step is not lost
        t1 = T_NOON + timedelta(minutes=5)
        staged = DT(_hass_with(_meter(100.2))).cycle([d], calc.device_meter_last, t1)
        _cycle(calc, t1, import_w=60000.0, entries=staged)
        assert calc.device_meter_last["heat_pump"]["value"] == pytest.approx(100.0)
        # next cycle, 1 min on: the whole step since the baseline is judged.
        # (#1228) It spans the skipped minutes, so this cycle's import does
        # not price it; with no grid counter the house booked none of that
        # time either, so it is dropped (test_1228 books it from the rows)
        t2 = t1 + timedelta(minutes=1)
        staged = DT(_hass_with(_meter(100.25))).cycle([d], calc.device_meter_last, t2)
        _cycle(calc, t2, import_w=60000.0, entries=staged)
        assert calc.get_device_tariff("heat_pump", t2.date())["daily_grid_kwh"] == 0.0
        assert calc.device_meter_last["heat_pump"]["value"] == pytest.approx(100.25)
        assert calc.device_meter_gaps == {}

    def test_an_unreadable_price_is_the_house_rate(self):
        calc = _calc(0.30)
        _cycle(calc, T_NOON, import_w=2000.0,
               entries=[DeviceCycle("heat_pump", power_w=1000.0, price=None)])
        day = T_NOON.date()
        assert calc._get_daily_cost("cost_import", day) == pytest.approx(0.60)
        assert calc.get_device_tariff("heat_pump", day)["daily_cost"] == pytest.approx(0.30)


# ── 6. heat pump config → device, and a goal on any load ─────────────────


@pytest.mark.unit
class TestWhereTheTariffComesFrom:
    def test_a_heat_pump_row_carries_it(self):
        from custom_components.solar_energy_management import _heat_pump_rows
        rows = _heat_pump_rows({
            "heat_pump_relay1_entity": "switch.a",
            "heat_pump_relay2_entity": "switch.b",
            "heat_pump_tariff_rate": 0.22,
            "heat_pump_tariff_meter": "sensor.hp_meter",
            "heat_pumps": [{"heat_pump_climate_entity": "climate.x",
                            "heat_pump_tariff_entity": "sensor.hp2_price"}],
        })
        d1, d2 = SimpleNamespace(), SimpleNamespace()
        apply_tariff(d1, heat_pump_tariff(rows[0]))
        apply_tariff(d2, heat_pump_tariff(rows[1]))
        assert tariff_of(d1).rate == pytest.approx(0.22)
        assert tariff_of(d1).meter == "sensor.hp_meter"
        assert tariff_of(d2).entity == "sensor.hp2_price"

    def test_a_goal_sets_it_on_any_load(self):
        from custom_components.solar_energy_management.features.device_registry import (
            UnifiedDeviceRegistry,
        )
        assert {"tariff_rate", "tariff_entity", "tariff_meter"} <= set(
            UnifiedDeviceRegistry.GOAL_PROPERTIES)
        reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
        reg._device_goals = {"pool": {"tariff_rate": "0.18"}}
        dev = SimpleNamespace(device_id="pool", tariff_rate=0.0, tariff_entity="",
                              tariff_meter="")
        reg._apply_goals(dev)
        assert tariff_of(dev).rate == pytest.approx(0.18)

    def test_a_bad_rate_is_none(self):
        for bad in (-1, "x", float("nan"), None, True):
            d = SimpleNamespace()
            apply_tariff(d, {"tariff_rate": bad})
            assert not tariff_of(d).configured


# ── 7. the cost sensor exists only when set ──────────────────────────────


@pytest.mark.unit
class TestTheSensorExistsOnlyWhenSet:
    def test_one_sensor_per_device_with_a_tariff(self):
        from custom_components.solar_energy_management.sensor import (
            _device_tariff_descriptions,
        )
        coord = SimpleNamespace(_surplus_controller=SimpleNamespace(_devices={
            "heat_pump": _load("heat_pump", rate=0.2),
            "heat_pump_2": _load("heat_pump_2"),
            "pool": _load("pool", entity="sensor.pool_price"),
        }))
        hass = SimpleNamespace(config=SimpleNamespace(currency="EUR"))
        keys = [d.key for d in _device_tariff_descriptions(hass, coord)]
        assert keys == ["daily_tariff_cost_heat_pump", "daily_tariff_cost_pool"]

    def test_none_set_means_none(self):
        from custom_components.solar_energy_management.sensor import (
            _device_tariff_descriptions,
        )
        coord = SimpleNamespace(_surplus_controller=SimpleNamespace(
            _devices={"heat_pump": _load("heat_pump")}))
        hass = SimpleNamespace(config=SimpleNamespace(currency="EUR"))
        assert _device_tariff_descriptions(hass, coord) == []


# ── 8. the settings: options flow AND cards ──────────────────────────────

FLOW_KEYS = ("heat_pump_tariff_rate", "heat_pump_tariff_entity",
             "heat_pump_tariff_meter")


@pytest.mark.unit
class TestTheSettingsAreEverywhere:
    def test_both_heat_pump_steps_show_them(self):
        from custom_components.solar_energy_management.config_flow import (
            OPTIONS_FLOW_OWNED_KEYS, OptionsFlowHandler,
        )
        fields = OptionsFlowHandler._heat_pump_tariff_fields(
            SimpleNamespace(hass=None), lambda k: None)
        assert {str(k) for k in fields} == set(FLOW_KEYS)
        src = (ROOT / "config_flow.py").read_text("utf-8")
        assert src.count("OptionsFlowHandler._heat_pump_tariff_fields(self, ") == 2
        assert set(FLOW_KEYS) <= OPTIONS_FLOW_OWNED_KEYS

    def test_they_reload_like_the_rest_of_the_pump(self):
        from custom_components.solar_energy_management import (
            _SET_OPTION_STRUCTURAL_KEYS,
        )
        assert set(FLOW_KEYS) <= _SET_OPTION_STRUCTURAL_KEYS
        card = (ROOT / "dashboard/card/src/cards/sem-config-card.js").read_text("utf-8")
        for k in FLOW_KEYS:
            assert f"'{k}'" in card

    def test_the_config_card_shows_them(self):
        card = (ROOT / "dashboard/card/src/cards/sem-config-card.js").read_text("utf-8")
        for k in FLOW_KEYS:
            assert re.search(rf"_render\w+\('{k}'", card), k

    def test_the_load_card_shows_them_per_device(self):
        card = (ROOT / "dashboard/card/src/cards/sem-load-priority-card.js").read_text("utf-8")
        assert "_renderOwnTariff(device)" in card
        for k in ("tariff_rate", "tariff_entity", "tariff_meter"):
            assert f"'{k}'" in card

    def test_every_language_has_the_words(self):
        dash = json.loads((ROOT / "dashboard/translations.json").read_text("utf-8"))
        words = ("device_tariff_section", "device_tariff_rate",
                 "device_tariff_entity", "device_tariff_meter",
                 "device_tariff_hint", "device_tariff_heat_pump",
                 "config_help_hp_tariff_rate", "config_help_hp_tariff_entity",
                 "config_help_hp_tariff_meter")
        assert [(lang, w) for lang, t in dash.items() for w in words
                if not t.get(w)] == []
        for path in [ROOT / "strings.json", *sorted((ROOT / "translations").glob("*.json"))]:
            data = json.loads(path.read_text("utf-8"))
            steps = data["options"]["step"]
            for k in FLOW_KEYS:
                assert steps["heat_pump"]["data"].get(k), (path.name, k)
                assert steps["heat_pump_unit"]["data"].get(k), (path.name, k)
            assert "{device}" in data["entity"]["sensor"]["per_device_tariff_cost"]["name"]


# ── 9. pipeline: a real setup with a heat pump on its own rate ───────────


@pytest.mark.asyncio
async def test_a_real_setup_gives_the_pump_its_tariff_and_sensor(
        sem_real_hass, sem_config_entry):
    """Config row → controller → stamp → gate, log and books → the sensor."""
    from custom_components.solar_energy_management.const import DOMAIN
    from .test_services_real import _seed_sem_input_sensors

    _seed_sem_input_sensors(sem_real_hass)
    for eid in ("switch.hp_relay", "switch.hp_relay_b",
                "switch.hp2_relay", "switch.hp2_relay_b"):
        sem_real_hass.states.async_set(eid, "off")
    sem_config_entry.add_to_hass(sem_real_hass)
    sem_real_hass.config_entries.async_update_entry(
        sem_config_entry, options={
            **sem_config_entry.options,
            "heat_pump_relay1_entity": "switch.hp_relay",
            "heat_pump_relay2_entity": "switch.hp_relay_b",
            "heat_pump_tariff_rate": 0.21,
            "heat_pumps": [{"heat_pump_relay1_entity": "switch.hp2_relay",
                            "heat_pump_relay2_entity": "switch.hp2_relay_b"}],
        })
    assert await sem_real_hass.config_entries.async_setup(sem_config_entry.entry_id)
    await sem_real_hass.async_block_till_done()

    coord = sem_real_hass.data[DOMAIN][sem_config_entry.entry_id]
    coord = getattr(coord, "coordinator", coord)
    sc = coord._surplus_controller
    hp, hp2 = sc.get_device("heat_pump"), sc.get_device("heat_pump_2")
    assert tariff_of(hp).rate == pytest.approx(0.21)
    assert not tariff_of(hp2).configured

    # the gate: own tariff reads normal, the second pump the house level
    sc.device_tariffs.stamp([hp, hp2])
    assert device_price_level(hp, "cheap") == "normal"
    assert device_price_level(hp2, "cheap") == "cheap"

    # the books: staged for the pump only, at its rate
    coord._stage_device_tariffs()
    staged = coord._energy_calculator._device_tariff_cycle
    assert [(e.device_id, e.price) for e in staged] == [("heat_pump", pytest.approx(0.21))]
    # (#1293) and every registered device, with or without its own tariff
    assert {"heat_pump", "heat_pump_2"} <= coord._energy_calculator._cycle_known
    out = coord._device_tariff_books()
    assert "daily_tariff_cost_heat_pump" in out
    assert not any(k.endswith("heat_pump_2") for k in out)

    # the sensor: there for the pump on its own rate, absent for the other
    assert sem_real_hass.states.get("sensor.sem_daily_tariff_cost_heat_pump") is not None
    assert sem_real_hass.states.get("sensor.sem_daily_tariff_cost_heat_pump_2") is None


# ── 10. an unreadable own price: gate, plan and cost read the house ──────


@pytest.mark.unit
class TestAnUnreadablePriceIsTheHouses:
    def test_gate_and_plan_read_the_house(self):
        d = _load("heat_pump", entity="sensor.hp_price")
        tariffs = DeviceTariffs(_hass_with({
            "sensor.hp_price": SimpleNamespace(state="unavailable", attributes={})}))
        tariffs.stamp([d])
        assert device_price_level(d, "cheap") == "cheap"
        assert d.tariff_inputs is None
        assert tariffs.plan_tariff(d) is None
        assert tariffs.price_now(d) is None        # → the house rate in the books

    def test_a_fixed_rate_behind_it_still_holds(self):
        d = _load("heat_pump", rate=0.19, entity="sensor.hp_price")
        tariffs = DeviceTariffs(_hass_with({
            "sensor.hp_price": SimpleNamespace(state="unavailable", attributes={})}))
        tariffs.stamp([d])
        assert device_price_level(d, "cheap") != "cheap"
        assert tariffs.plan_tariff(d) is not None


# ── 11. the plan reads the device's own tariff ───────────────────────────


@pytest.mark.unit
class TestThePlanReadsTheOwnTariff:
    HOUSE = [0.40, 0.10, 0.40, 0.40, 0.40, 0.40]   # house cheap at slot 1

    def _ledger(self):
        from custom_components.solar_energy_management.coordinator.energy_planner import (
            LedgerSlot, build_night_ledger,
        )
        t0 = dt_util.now().replace(minute=0, second=0, microsecond=0)
        slots = [LedgerSlot(start=t0 + timedelta(hours=n),
                            end=t0 + timedelta(hours=n + 1), price=p,
                            level_cheap=p < 0.15, home_w=300.0)
                 for n, p in enumerate(self.HOUSE)]
        return t0, build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0,
                                      max_discharge_w=5000.0, peak_limit_w=0.0)

    def _pack(self, tariff):
        from custom_components.solar_energy_management.coordinator.energy_planner import (
            Demand, pack_night,
        )
        t0, ledger = self._ledger()
        d = Demand(id="load:heat_pump", kind="load", energy_kwh=1.0,
                   max_power_w=1000.0, min_power_w=1000.0,
                   deadline=t0 + timedelta(hours=6), needs_cheap_level=True,
                   tariff=tariff)
        plan = pack_night([d], ledger)
        return t0, [a for a in plan.allocations if a.demand_id == d.id], plan

    def test_no_tariff_packs_the_house_cheap_hour(self):
        t0, allocs, _ = self._pack(None)
        assert [a.start for a in allocs] == [t0 + timedelta(hours=1)]

    def test_a_fixed_rate_has_no_cheaper_hour(self):
        d = _load("heat_pump", rate=0.20)
        tariff = DeviceTariffs(None).plan_tariff(d)
        _, allocs, plan = self._pack(tariff)
        assert allocs == []
        assert "no cheap window" in plan.results[0].note

    def test_a_price_entity_packs_its_own_cheap_hour(self):
        # the device curve is cheapest at slot 4, dear at the house's slot 1
        curve = [0.30, 0.50, 0.32, 0.31, 0.05, 0.33] + [0.30] * 18
        d = _load("heat_pump", entity="sensor.hp_price")
        tariffs = DeviceTariffs(_hass_with({
            "sensor.hp_price": _price_state(curve)}))
        t0, allocs, _ = self._pack(tariffs.plan_tariff(d))
        assert [a.start for a in allocs] == [t0 + timedelta(hours=4)]
        assert allocs[0].price == pytest.approx(0.05)

    def test_the_coordinator_builds_load_demands_through_the_one_reader(self):
        from custom_components.solar_energy_management.tests.ast_contracts import (
            call_kwargs,
        )
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        # every load and comfort demand names its tariff …
        plan_fns = [getattr(SEMCoordinator, n) for n in dir(SEMCoordinator)
                    if callable(getattr(SEMCoordinator, n, None))
                    and any("_plan_tariff" in str(c) for c in
                            getattr(getattr(SEMCoordinator, n), "__code__",
                                    SimpleNamespace(co_varnames=()))
                            .co_varnames)]
        assert len(plan_fns) == 1, plan_fns
        demands = call_kwargs(plan_fns[0], "Demand")
        named = [kw for kw in demands if "needs_cheap_level" in kw]
        assert named and all("tariff" in kw for kw in named)
        # … and that reader is the live gate's DeviceTariffs
        from custom_components.solar_energy_management.tests.ast_contracts import calls
        assert calls(plan_fns[0], "plan_tariff")


def test_the_meter_baseline_really_survives_a_restart():
    """(#812) The baseline was emitted by get_state() but not in the store's
    key list, so it read back empty after every restart."""
    from custom_components.solar_energy_management.coordinator import storage
    assert "device_meter_last" in storage.CALCULATOR_STATE_KEYS
