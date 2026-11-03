"""#1302 — "Controlled loads vs home residual" fired every night after midnight.

RienduPre (Growatt + 2× Sessy, a heat pump on a whole-kWh counter), just
after midnight on 2026-11-03::

    Controlled loads vs home residual: members sum to 5.12kWh against a
    fleet total of 0.03kWh — 5.09kWh over the 0.50kWh band. … Members:
    heat_pump=3.00kWh [counter sensor.warmtepomp_totale_energie reads
    2122.00kWh], energy_dashboard_airconditioner=1.08kWh, …

Two windows on either side of one comparison (class 55):

1. The members were each device's own day total, which rolls at SUNRISE
   (#620). The home row rolls at MIDNIGHT. From midnight to sunrise the
   members held all of yesterday's daylight use against a home row that had
   started again at 0 — every winter night with a heat pump.
2. A whole-kWh counter books a step when its value moves, and the step holds
   everything since the value last moved. Its first step after midnight is
   partly the evening before, and one step (1 kWh) is more than the 0.5 kWh
   band while the home row is still small.

The members are now each device's row of the midnight-keyed controlled-loads
mirror, less any step that began before midnight. The drift check's device
terms (sealed beside each day) move to the same rows.
"""
from __future__ import annotations

import ast
import math
import pathlib
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.energy_calculator import (
    CONTROLLED_LOADS_DEVICE_PREFIX,
    CONTROLLED_LOADS_UNSURE_PREFIX,
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.health_check import (
    HealthCheck,
    home_member_evidence,
    home_member_totals,
)
from custom_components.solar_energy_management.coordinator.types import (
    EnergyTotals,
    PowerReadings,
)
from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode,
    SwitchDevice,
)

TZ = ZoneInfo("Europe/Amsterdam")
EVENING = date(2026, 11, 2)
NIGHT = date(2026, 11, 3)
LABEL = "Controlled loads vs home residual"

HP_W = 1500.0          # the heat pump, all night
TV_W = 50.0            # a small load on a power sensor
HOUSE_W = 100.0        # what no device meters
HP_COUNTER_AT_2200 = 2119.625   # true kWh; the sensor shows it floored
HOME_BEFORE_2200 = 9.0          # the evening's home row at 22:00

_CURSOR = {"t": datetime(2026, 11, 2, 22, 0, 0)}


@pytest.fixture(autouse=True)
def _night(monkeypatch):
    """One wall clock for the devices (naive ``datetime.now``) and for the
    coordinator and the calculator (``dt_util.now``), in Amsterdam."""
    import custom_components.solar_energy_management.devices.base as base_mod

    old_tz = dt_util.DEFAULT_TIME_ZONE
    dt_util.set_default_time_zone(TZ)
    _CURSOR["t"] = datetime(2026, 11, 2, 22, 0, 0)
    fake = MagicMock()
    fake.now.side_effect = lambda: _CURSOR["t"]
    fake.side_effect = lambda *a, **kw: datetime(*a, **kw)
    monkeypatch.setattr(base_mod, "datetime", fake)
    monkeypatch.setattr(
        dt_util, "now", lambda *a, **kw: _CURSOR["t"].replace(tzinfo=TZ))
    yield
    dt_util.set_default_time_zone(old_tz)


class _Hass:
    def __init__(self):
        self._states = {}
        self.states = SimpleNamespace(get=lambda e: self._states.get(e))

    def set(self, entity, value, unit):
        self._states[entity] = SimpleNamespace(
            state=str(value), attributes={"unit_of_measurement": unit})


def _device(hass, device_id, **kw) -> SwitchDevice:
    dev = SwitchDevice(
        hass=hass, device_id=device_id, name=device_id, rated_power=2000,
        entity_id=f"switch.{device_id}", **kw)
    dev.control_mode = DeviceControlMode.SURPLUS
    return dev


def _coord(devices, calc):
    coord = SimpleNamespace(
        _energy_calculator=calc,
        _surplus_controller=SimpleNamespace(
            _devices={d.device_id: d for d in devices}),
        _ev_devices={}, _ev_device=None,
    )
    coord._comfort_split_for = SEMCoordinator._comfort_split_for.__get__(coord)
    return coord


class _Night:
    """RienduPre's night through the real device accrual, the real filing
    seam and the real calculator rows, 30 s cycles from 22:00 to 01:30.

    The heat pump's counter shows whole kWh: it moves at 22:15, 22:55,
    23:35, 00:15 and 00:55. The home row is written the way the integral
    books it: every watt of the cycle, on the cycle's own calendar day.
    """

    def __init__(self, *, copy_of_heat_pump=False):
        self.hass = _Hass()
        self.heat_pump = _device(
            self.hass, "heat_pump",
            energy_entity_id="sensor.warmtepomp_totale_energie")
        self.tv = _device(
            self.hass, "energy_dashboard_tv_sonos_arc",
            power_entity_id="sensor.tv_power")
        self.devices = [self.heat_pump, self.tv]
        if copy_of_heat_pump:
            # A real double count: a second load reading the pump's draw.
            self.copy = _device(
                self.hass, "heat_pump_copy", power_entity_id="sensor.hp_power")
            self.devices.append(self.copy)
        # SEM has run all day: the counter last moved at 21:35, seen.
        hp = self.heat_pump
        hp._energy_counter_last_kwh = 2119.0
        hp._energy_counter_read_in_run = True
        hp._energy_counter_moved_at = datetime(2026, 11, 2, 21, 35)
        hp._energy_counter_last_at = datetime(2026, 11, 2, 21, 35)
        self.calc = EnergyCalculator({}, MagicMock())
        self.calc._daily_accumulators[f"home_{EVENING}"] = HOME_BEFORE_2200
        self.coord = _coord(self.devices, self.calc)
        self.hp_true = HP_COUNTER_AT_2200
        self._show()
        for dev in self.devices:   # the first cycle only sets the clock
            dev.update_daily_runtime(EVENING)

    hp_reads = None   # a reading to show instead of the true counter

    def _show(self):
        shown = (self.hp_reads if self.hp_reads is not None
                 else float(math.floor(self.hp_true)))
        self.hass.set("sensor.warmtepomp_totale_energie", shown, "kWh")
        self.hass.set("sensor.tv_power", TV_W, "W")
        self.hass.set("sensor.hp_power", HP_W, "W")

    def cycle(self, seconds=30.0):
        before = _CURSOR["t"]
        _CURSOR["t"] = before + timedelta(seconds=seconds)
        now = _CURSOR["t"]
        self.hp_true += HP_W * seconds / 3_600_000.0
        self._show()
        home_w = HP_W + TV_W + HOUSE_W
        key = f"home_{now.date()}"
        self.calc._daily_accumulators[key] = (
            self.calc._daily_accumulators.get(key, 0.0)
            + home_w * seconds / 3_600_000.0)
        # The device day rolls at sunrise: still the evening's all night.
        for dev in self.devices:
            dev.update_daily_runtime(EVENING)
        SEMCoordinator._file_device_energy(self.coord, EVENING, PowerReadings())

    def run_to(self, hh, mm):
        target = datetime(2026, 11, 3 if hh < 12 else 2, hh, mm)
        while _CURSOR["t"] < target:
            self.cycle()

    @property
    def today(self):
        return _CURSOR["t"].date()

    @property
    def home(self):
        return self.calc._daily_accumulators.get(f"home_{self.today}", 0.0)

    def check(self, members):
        return HealthCheck().check_ledger_partitions(
            EnergyTotals(daily_home=self.home),
            per_device_daily=members,
            per_device_evidence=home_member_evidence(self.devices),
        )

    def fixed_members(self):
        """What the coordinator now hands the check."""
        return home_member_totals(
            self.devices, (),
            self.calc.controlled_loads_by_device(self.today, sure_only=True))


# ───────────────────────────────────────────────────────────────────────
# 1. the reporter's night
# ───────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestTheNight:
    def test_the_night_reads_like_the_report(self):
        """The fixture is the issue: 3.0 kWh before midnight, 4.0 after the
        00:15 tick, and the device's own day did not roll at midnight."""
        night = _Night()
        night.run_to(23, 59)
        assert night.heat_pump.daily_energy_kwh == pytest.approx(3.0)
        night.run_to(0, 16)
        assert night.heat_pump.daily_energy_kwh == pytest.approx(4.0)
        assert night.home < 0.5

    def test_no_violation_on_any_cycle_of_the_night(self):
        night = _Night()
        fired = []
        while _CURSOR["t"] < datetime(2026, 11, 3, 1, 30):
            night.cycle()
            v = [x for x in night.check(night.fixed_members())
                 if x.startswith(LABEL)]
            if v:
                fired.append((_CURSOR["t"], v[0]))
        assert not fired, fired[:3]

    def test_the_old_members_fire_after_midnight(self):
        """Vacuity twin: the device's own day total (sunrise-keyed) on the
        same night reports the false double count."""
        night = _Night()
        night.run_to(0, 5)
        old = {d.device_id: d.daily_energy_kwh for d in night.devices}
        v = [x for x in night.check(old) if x.startswith(LABEL)]
        assert v and "heat_pump=3.00kWh" in v[0]

    def test_the_whole_first_tick_fires_at_00_15(self):
        """Vacuity twin for part 2: the midnight rows WITH the 00:15 step
        (begun at 23:35) are 1.0 kWh against a 0.41 kWh home row."""
        night = _Night()
        night.run_to(0, 16)
        full = home_member_totals(
            night.devices, (), night.calc.controlled_loads_by_device(night.today))
        assert full["heat_pump"] == pytest.approx(1.0)
        v = [x for x in night.check(full) if x.startswith(LABEL)]
        assert v, f"home {night.home:.2f}: the twin no longer shows the tick"
        assert night.fixed_members()["heat_pump"] == pytest.approx(0.0)

    def test_the_next_tick_is_sure_and_counts(self):
        """00:55: the step began at 00:15, after midnight — the day's."""
        night = _Night()
        night.run_to(0, 56)
        assert night.fixed_members()["heat_pump"] == pytest.approx(1.0)
        assert night.fixed_members()["energy_dashboard_tv_sonos_arc"] == \
            pytest.approx(TV_W * (56 / 60) / 1000.0, abs=0.002)

    def test_a_real_double_count_still_fires_at_night(self):
        """The check keeps what it is for: a second load reading the pump's
        draw is caught before sunrise, on the night's own numbers."""
        night = _Night(copy_of_heat_pump=True)
        night.run_to(1, 0)
        v = [x for x in night.check(night.fixed_members())
             if x.startswith(LABEL)]
        assert v and "heat_pump_copy=1.50kWh" in v[0]
        assert "counted twice" in v[0]

    def test_a_device_first_read_after_midnight_does_not_fire(self):
        """A device with no stored baseline read first at 00:05: its 00:15
        step reaches back to a move SEM never saw (23:35)."""
        night = _Night()
        night.run_to(0, 5)
        late = _device(night.hass, "heat_pump_2",
                       energy_entity_id="sensor.warmtepomp_totale_energie")
        late.update_daily_runtime(EVENING)
        night.devices.append(late)
        night.coord._surplus_controller._devices["heat_pump_2"] = late
        while _CURSOR["t"] < datetime(2026, 11, 3, 0, 30):
            night.cycle()
            assert not [x for x in night.check(night.fixed_members())
                        if x.startswith(LABEL) and "heat_pump_2=1" in x]
        assert night.calc.controlled_loads_by_device(
            NIGHT)["heat_pump_2"] == pytest.approx(1.0)

    def _restart(self, night, *, baseline, moved_at, reading):
        """HA restarts now: the pump is a fresh object, its baseline and the
        time of its last move come back from the store."""
        from custom_components.solar_energy_management.coordinator.storage import (
            SEMStorage,
        )
        store = SEMStorage.__new__(SEMStorage)
        store._daily_data = {}
        store.set_device_runtime(
            "heat_pump", 0.0, str(EVENING), accumulated_kwh=3.0,
            counter_baseline_kwh=baseline,
            counter_moved_at=moved_at.isoformat() if moved_at else None)
        hp = _device(night.hass, "heat_pump",
                     energy_entity_id="sensor.warmtepomp_totale_energie")
        SEMCoordinator._restore_device_energy(
            hp, store.get_device_runtimes()["heat_pump"])
        night.devices[0] = hp
        night.heat_pump = hp
        night.coord._surplus_controller._devices["heat_pump"] = hp
        night.hp_true = reading
        hp.update_daily_runtime(EVENING)
        return hp

    def test_a_lifetime_jump_after_a_restart_still_fires(self):
        """The reviewer's path: the stored baseline is 0 (the sensor read 0
        before the restart), the first read is 0 too, and the lifetime value
        comes a cycle later. The last move up (23:35) is on record, so only
        what 100 kW could draw before midnight is held back."""
        night = _Night()
        night.run_to(0, 30)
        self._restart(night, baseline=0.0,
                      moved_at=datetime(2026, 11, 2, 23, 35), reading=0.5)
        night.cycle()
        assert night.heat_pump.last_cycle_energy_kwh == 0.0
        night.hp_true = 1906.2
        night.cycle()
        assert night.heat_pump.last_cycle_energy_kwh == pytest.approx(1906.0)
        v = [x for x in night.check(night.fixed_members())
             if x.startswith(LABEL)]
        assert v and "heat_pump=190" in v[0], v

    def test_a_restart_across_midnight_does_not_fire(self):
        """HA down 23:30-00:20. The first step after it began at the last
        move SEM saw (23:10): all of it may be the evening's."""
        night = _Night()
        night.run_to(23, 30)
        _CURSOR["t"] = datetime(2026, 11, 3, 0, 20)
        self._restart(night, baseline=2121.0,
                      moved_at=datetime(2026, 11, 2, 23, 10), reading=2123.3)
        while _CURSOR["t"] < datetime(2026, 11, 3, 0, 50):
            night.cycle()
            assert not [x for x in night.check(night.fixed_members())
                        if x.startswith(LABEL)]
        # 2.0 kWh at the first read, 1.0 at the 00:48 tick, whose start
        # (the counter's move during the outage) nobody saw.
        assert night.calc.controlled_loads_by_device(
            NIGHT)["heat_pump"] == pytest.approx(3.0)
        assert night.fixed_members()["heat_pump"] == pytest.approx(0.0)

    def test_a_drop_is_no_move(self):
        """The counter reads 0 at 00:01 and is back at 00:10, one kWh up: the
        kWh began at its last move UP (23:35), not at the drop."""
        night = _Night()
        night.run_to(0, 1)
        night.hp_reads = 0.0
        night.cycle()
        assert night.heat_pump._energy_counter_last_kwh == 0.0
        night.hp_reads = None
        night.cycle()     # back at 2122: the drop recovered, nothing used
        night.run_to(0, 16)
        assert night.calc.controlled_loads_by_device(
            NIGHT)["heat_pump"] == pytest.approx(1.0)
        assert night.fixed_members()["heat_pump"] == pytest.approx(0.0)

    def test_an_idle_evening_hides_no_lifetime_jump(self):
        """The reviewer's round-3 path: an air conditioner (2 kW) last moved
        at 20:00, a restart restores a 0 baseline, and at 09:00 it reads its
        lifetime 300 kWh. At most 2 × 2 kW × 4 h is the evening's."""
        calc = EnergyCalculator({}, MagicMock())
        hass = _Hass()
        ac = _device(hass, "airco", energy_entity_id="sensor.ac")
        ac._energy_counter_last_kwh = 0.0
        ac._energy_counter_moved_at = datetime(2026, 11, 2, 20, 0)
        hass.set("sensor.ac", 300.0, "kWh")
        _CURSOR["t"] = datetime(2026, 11, 3, 9, 0)
        ac.update_daily_runtime(NIGHT)
        _CURSOR["t"] = datetime(2026, 11, 3, 9, 0, 30)
        ac.update_daily_runtime(NIGHT)
        assert ac.last_cycle_energy_kwh == pytest.approx(300.0)
        SEMCoordinator._file_device_energy(_coord([ac], calc), NIGHT,
                                           PowerReadings())
        sure = calc.controlled_loads_by_device(NIGHT, sure_only=True)
        assert sure["airco"] == pytest.approx(300.0 - 16.0)
        v = HealthCheck().check_ledger_partitions(
            EnergyTotals(daily_home=5.0),
            per_device_daily=home_member_totals([ac], (), sure))
        assert v and "airco=284.00kWh" in v[0]

    def test_a_seasonal_load_hides_no_lifetime_jump(self):
        """Last moved on 1 September: a day at most is the evening's."""
        calc = EnergyCalculator({}, MagicMock())
        hass = _Hass()
        ac = _device(hass, "airco", energy_entity_id="sensor.ac")
        ac._energy_counter_last_kwh = 0.0
        ac._energy_counter_moved_at = datetime(2026, 9, 1, 15, 0)
        hass.set("sensor.ac", 300.0, "kWh")
        _CURSOR["t"] = datetime(2026, 11, 3, 9, 0)
        ac.update_daily_runtime(NIGHT)
        _CURSOR["t"] = datetime(2026, 11, 3, 9, 0, 30)
        ac.update_daily_runtime(NIGHT)
        SEMCoordinator._file_device_energy(_coord([ac], calc), NIGHT,
                                           PowerReadings())
        assert calc.controlled_loads_by_device(NIGHT, sure_only=True)[
            "airco"] == pytest.approx(300.0 - 96.0)

    def test_only_what_could_be_drawn_before_midnight_is_unsure(self):
        """No rating: a step that began a minute before midnight holds at
        most 100 kW for that minute from the evening; the rest is the
        day's."""
        calc = EnergyCalculator({}, MagicMock())
        dev = SimpleNamespace(
            device_id="x", last_cycle_energy_kwh=5.0,
            last_cycle_energy_window_s=120.0, energy_split_label=None,
            daily_energy_is_measured=True)
        _CURSOR["t"] = datetime(2026, 11, 3, 0, 1)
        SEMCoordinator._file_device_energy(_coord([dev], calc), EVENING,
                                           PowerReadings())
        assert calc.controlled_loads_by_device(NIGHT, sure_only=True)[
            "x"] == pytest.approx(5.0 - 100.0 / 60.0)

    def test_a_lifetime_counter_read_as_a_day_still_fires(self):
        """#979's shape through the real path: a restart brings back a 0 kWh
        baseline and the counter reads its lifetime 1906 kWh. Booked at the
        first read, it is sure — the check names it, sensor and reading."""
        night = _Night()
        night.run_to(0, 30)
        hp = _device(night.hass, "heat_pump_new",
                     energy_entity_id="sensor.heat_pump_total_energy")
        hp._energy_counter_last_kwh = 0.0
        night.hass.set("sensor.heat_pump_total_energy", 1906.0, "kWh")
        hp.update_daily_runtime(EVENING)
        night.devices.append(hp)
        night.coord._surplus_controller._devices["heat_pump_new"] = hp
        night.cycle()
        v = [x for x in night.check(night.fixed_members())
             if x.startswith(LABEL)]
        assert v and "heat_pump_new=1906.00kWh" in v[0]
        assert "counter sensor.heat_pump_total_energy reads 1906.00kWh" in v[0]

    def test_the_evening_is_unchanged(self):
        """Before midnight the members are the evening's rows, and no row is
        held back: every step began inside the day."""
        night = _Night()
        night.run_to(23, 50)
        assert night.calc.controlled_loads_by_device(
            EVENING, sure_only=True)["heat_pump"] == pytest.approx(3.0)
        assert not [x for x in night.check(night.fixed_members())
                    if x.startswith(LABEL)]


# ───────────────────────────────────────────────────────────────────────
# 2. the rows
# ───────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestTheRows:
    def test_the_rows_sum_to_the_mirror(self):
        night = _Night(copy_of_heat_pump=True)
        night.run_to(1, 0)
        rows = night.calc.controlled_loads_by_device(night.today)
        mirror = night.calc.get_true_baseload(night.today)["controlled_today_kwh"]
        assert sum(rows.values()) == pytest.approx(mirror, abs=0.01)
        assert set(rows) == {"heat_pump", "heat_pump_copy",
                             "energy_dashboard_tv_sonos_arc"}

    def test_a_charger_gets_no_row(self):
        """(#1044) The seam books home members only — so do the rows."""
        calc = EnergyCalculator({}, MagicMock())
        heater = SimpleNamespace(
            device_id="heater", last_cycle_energy_kwh=0.2,
            last_cycle_energy_window_s=30.0, energy_split_label=None,
            daily_energy_is_measured=True)
        box = SimpleNamespace(
            device_id="wallbox", last_cycle_energy_kwh=1.0,
            last_cycle_energy_window_s=30.0, energy_split_label=None,
            daily_energy_is_measured=True, power_entity_id="sensor.box")
        power = PowerReadings()
        power.ev_power_entities = frozenset({"sensor.box"})
        coord = _coord([heater, box], calc)
        coord._ev_devices = {"wallbox": box}
        _CURSOR["t"] = datetime(2026, 11, 3, 12, 0)
        SEMCoordinator._file_device_energy(coord, NIGHT, power)
        assert calc.controlled_loads_by_device(NIGHT) == {
            "heater": pytest.approx(0.2)}

    def test_an_unknown_window_is_not_sure(self):
        """A counter baseline restored from storage says nothing of when the
        step began: kept in the row, left out of the sure part."""
        calc = EnergyCalculator({}, MagicMock())
        dev = SimpleNamespace(
            device_id="hp", last_cycle_energy_kwh=1.0,
            last_cycle_energy_window_s=None, energy_split_label=None,
            daily_energy_is_measured=True)
        _CURSOR["t"] = datetime(2026, 11, 3, 14, 0)
        SEMCoordinator._file_device_energy(_coord([dev], calc), NIGHT,
                                           PowerReadings())
        assert calc.controlled_loads_by_device(NIGHT) == {"hp": 1.0}
        assert calc.controlled_loads_by_device(NIGHT, sure_only=True) == {
            "hp": 0.0}

    def test_the_rows_survive_a_restart(self):
        night = _Night()
        night.run_to(0, 56)
        before = night.calc.controlled_loads_by_device(night.today)
        sure = night.calc.controlled_loads_by_device(night.today, sure_only=True)
        fresh = EnergyCalculator({}, MagicMock())
        fresh.restore_state(night.calc.get_state())
        assert fresh.controlled_loads_by_device(night.today) == before
        assert fresh.controlled_loads_by_device(
            night.today, sure_only=True) == sure

    def test_the_store_keeps_the_rows(self):
        from custom_components.solar_energy_management.coordinator.storage import (
            SEMStorage,
        )
        night = _Night()
        night.run_to(0, 56)
        daily = {"daily_accumulators": dict(night.calc._daily_accumulators)}
        assert SEMStorage._validate_daily_data(daily)
        assert any(k.startswith(CONTROLLED_LOADS_DEVICE_PREFIX)
                   for k in daily["daily_accumulators"])
        assert any(k.startswith(CONTROLLED_LOADS_UNSURE_PREFIX)
                   for k in daily["daily_accumulators"])

    def test_the_rollover_sweeps_yesterdays_rows(self):
        calc = EnergyCalculator({}, MagicMock())
        for day in (EVENING, NIGHT):
            calc.accumulate_controlled_load(
                1.0, day, estimated=False, device_id="hp", unsure_kwh=1.0)
        calc._check_rollover(NIGHT, calc._month_key(NIGHT), str(NIGHT.year))
        assert calc.controlled_loads_by_device(EVENING) == {}
        assert calc.controlled_loads_by_device(NIGHT) == {"hp": 1.0}
        assert not any(str(EVENING) in k and "controlled_loads" in k
                       for k in calc._daily_accumulators)


# ───────────────────────────────────────────────────────────────────────
# 3. the device says how far back its step reaches
# ───────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestTheStepWindow:
    def test_a_counter_step_reaches_back_to_its_last_move(self):
        night = _Night()
        night.run_to(0, 15)
        night.cycle()   # the 00:15 tick
        assert night.heat_pump.last_cycle_energy_kwh == pytest.approx(1.0)
        assert night.heat_pump.last_cycle_energy_window_s == pytest.approx(
            40 * 60, abs=60)

    def test_a_power_step_is_the_cycle(self):
        night = _Night()
        night.run_to(0, 1)
        assert night.tv.last_cycle_energy_window_s == pytest.approx(30.0)

    def _restarted(self, baseline, reading):
        """A fresh device object after a restart: its counter baseline
        comes back from the store, with no time."""
        hass = _Hass()
        dev = _device(hass, "hp", energy_entity_id="sensor.c")
        hass.set("sensor.c", reading, "kWh")
        if baseline is not None:
            dev._energy_counter_last_kwh = baseline
        dev.update_daily_runtime(NIGHT)
        return hass, dev

    def _tick(self, dev, seconds=30):
        """Walk the clock in 30 s cycles (a jump over 120 s is a restart to
        the device and accrues nothing)."""
        for _ in range(int(seconds // 30)):
            _CURSOR["t"] = _CURSOR["t"] + timedelta(seconds=30)
            dev.update_daily_runtime(NIGHT)

    def test_a_step_at_the_first_read_of_a_run_is_the_cycles(self):
        """Booked now, against the stored baseline — the restart gap's kWh
        are booked now by design, and a lifetime counter shows here."""
        _hass, dev = self._restarted(99.0, 100.0)
        self._tick(dev)
        assert dev.last_cycle_energy_kwh == pytest.approx(1.0)
        assert dev.last_cycle_energy_window_s == pytest.approx(30.0)

    def test_a_step_with_no_move_seen_before_it_is_unknown(self):
        """The counter stood at its stored value; it moves later. Nobody saw
        when it reached that value, so nobody knows where the step began."""
        hass, dev = self._restarted(99.0, 99.0)
        self._tick(dev)
        assert dev.last_cycle_energy_kwh == 0.0
        self._tick(dev, 570)
        hass.set("sensor.c", 100.0, "kWh")
        self._tick(dev)
        assert dev.last_cycle_energy_kwh == pytest.approx(1.0)
        assert dev.last_cycle_energy_window_s is None

    def test_a_first_read_with_no_baseline_is_not_a_move(self):
        hass, dev = self._restarted(None, 99.0)
        self._tick(dev)
        self._tick(dev, 570)
        hass.set("sensor.c", 100.0, "kWh")
        self._tick(dev)
        assert dev.last_cycle_energy_kwh == pytest.approx(1.0)
        assert dev.last_cycle_energy_window_s is None
        self._tick(dev, 870)
        hass.set("sensor.c", 101.0, "kWh")
        self._tick(dev)
        assert dev.last_cycle_energy_kwh == pytest.approx(1.0)
        assert dev.last_cycle_energy_window_s == pytest.approx(900.0)


# ───────────────────────────────────────────────────────────────────────
# 4. the sealed day and the drift check (same class, swept)
# ───────────────────────────────────────────────────────────────────────

def _row(day, *, baseload, home, devices, midnight):
    row = {"date": str(day), "baseload_kwh": baseload, "home_kwh": home,
           "controlled_kwh": home - baseload, "measured": True,
           "estimated_kwh": 0.0, "devices": devices}
    if midnight is not None:
        row["devices_midnight"] = midnight
    return row


@pytest.mark.unit
class TestTheSeal:
    def test_a_day_with_rows_seals_its_midnight_rows(self):
        """The small hours are in the sealed term (the old sealed term was
        the sunrise row at midnight: the daylight part only)."""
        calc = EnergyCalculator({}, MagicMock())
        calc._daily_accumulators[f"home_{EVENING}"] = 12.0
        calc.accumulate_controlled_load(
            2.0, EVENING, estimated=False, device_id="hp")   # 00:00-sunrise
        calc.accumulate_controlled_load(
            3.0, EVENING, estimated=False, device_id="hp")   # daylight
        calc._daily_accumulators[f"device:hp_{EVENING}"] = 3.0
        calc._check_rollover(NIGHT, calc._month_key(NIGHT), str(NIGHT.year))
        sealed = calc.baseload_history[-1]
        assert sealed["devices"] == {"hp": 5.0}
        assert sealed["devices_midnight"] is True

    def test_a_day_begun_before_the_rows_seals_the_ledger_rows(self):
        """The upgrade day: the mirror holds kWh booked before the rows
        existed, so the rows are not the day — the old rows are sealed, and
        the row says so."""
        calc = EnergyCalculator({}, MagicMock())
        calc._daily_accumulators[f"home_{EVENING}"] = 12.0
        calc._daily_accumulators[f"controlled_loads_{EVENING}"] = 4.0
        calc.accumulate_controlled_load(
            1.0, EVENING, estimated=False, device_id="hp")
        calc._daily_accumulators[f"device:hp_{EVENING}"] = 3.0
        calc._check_rollover(NIGHT, calc._month_key(NIGHT), str(NIGHT.year))
        sealed = calc.baseload_history[-1]
        assert sealed["devices"] == {"hp": 3.0}
        assert sealed["devices_midnight"] is False


@pytest.mark.unit
class TestTheDriftCheckComparesLikeWithLike:
    def _days(self, n):
        return [EVENING - timedelta(days=n - i) for i in range(n)]

    def test_a_new_basis_is_no_move(self):
        """Old rows hold the pump's daylight part (4.0), the new row its whole
        day (7.5). That is no move; the home row moved."""
        days = self._days(5)
        history = [_row(d, baseload=4.0, home=10.0,
                        devices={"heat_pump": 4.0}, midnight=None)
                   for d in days[:-1]]
        history.append(_row(days[-1], baseload=7.0, home=13.0,
                            devices={"heat_pump": 7.5}, midnight=True))
        v = HealthCheck().check_baseload_drift(history)
        assert v and "Largest mover: home" in v[0]

    def test_on_one_basis_the_device_is_still_named(self):
        """Twin: the same numbers all on the midnight rows — the pump moved."""
        days = self._days(5)
        history = [_row(d, baseload=4.0, home=10.0,
                        devices={"heat_pump": 4.0}, midnight=True)
                   for d in days[:-1]]
        history.append(_row(days[-1], baseload=7.0, home=13.0,
                            devices={"heat_pump": 7.5}, midnight=True))
        v = HealthCheck().check_baseload_drift(history)
        assert v and "Largest mover: heat_pump" in v[0]

    def test_old_rows_alone_still_name_a_device(self):
        days = self._days(5)
        history = [_row(d, baseload=4.0, home=10.0,
                        devices={"heat_pump": 4.0}, midnight=None)
                   for d in days[:-1]]
        history.append(_row(days[-1], baseload=7.0, home=13.0,
                            devices={"heat_pump": 7.5}, midnight=None))
        v = HealthCheck().check_baseload_drift(history)
        assert v and "Largest mover: heat_pump" in v[0]


# ───────────────────────────────────────────────────────────────────────
# 5. the message and the wiring
# ───────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestTheMessageAndTheWiring:
    def test_the_message_names_what_it_can_be(self):
        """Its members are live devices: no removed id can hold a bucket."""
        v = HealthCheck().check_ledger_partitions(
            EnergyTotals(daily_home=0.1),
            per_device_daily={"heat_pump": 1.0, "heat_pump_copy": 1.0})
        assert v and "renamed or removed" not in v[0]
        assert "A device's energy is counted twice" in v[0]

    def test_the_other_partitions_keep_their_words(self):
        v = HealthCheck().check_ledger_partitions(
            EnergyTotals(daily_ev=1.0),
            per_charger_daily={"a": 1.0, "b": 1.0})
        assert v and "renamed or removed" in v[0]

    def _coordinator_tree(self):
        here = pathlib.Path(__file__).resolve().parent.parent
        return ast.parse((here / "coordinator" / "coordinator.py").read_text())

    def test_the_check_gets_the_sure_midnight_rows(self):
        calls = [n for n in ast.walk(self._coordinator_tree())
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "id", getattr(n.func, "attr", None))
                 == "home_member_totals"]
        assert calls, "guard reads nothing"
        for call in calls:
            assert len(call.args) == 3
            rows = [n for n in ast.walk(call.args[2])
                    if isinstance(n, ast.Call)
                    and getattr(n.func, "attr", None)
                    == "controlled_loads_by_device"]
            assert rows and any(
                k.arg == "sure_only" and getattr(k.value, "value", None) is True
                for k in rows[0].keywords)

    def test_the_seam_books_each_device_and_its_window(self):
        calls = [n for n in ast.walk(self._coordinator_tree())
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "attr", None) == "accumulate_controlled_load"]
        assert calls
        for call in calls:
            assert {"device_id", "unsure_kwh"} <= {k.arg for k in call.keywords}

    def test_the_check_reads_no_sunrise_total(self):
        here = pathlib.Path(__file__).resolve().parent.parent
        src = (here / "coordinator" / "health_check.py").read_text()
        tree = ast.parse(src)
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        strings = {n.value for n in ast.walk(tree)
                   if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        assert "daily_energy_kwh" not in names
        assert "daily_energy_kwh" not in strings
