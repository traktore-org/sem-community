"""#769 — the heat pump has no ledger row.

#768 gave every controlled device a daily kWh with its provenance. A daily
figure alone still cannot answer the question a heat-pump house actually
asks: *how much did SG-Ready shift?* That needs three more things.

1. **The cycle's increment.** ``daily_energy_kwh`` is a running total; the
   ledger needs the delta the device just booked, so it can be filed under a
   period and an attribution bucket. The device is the only thing that knows
   whether this cycle booked anything at all (a blind cycle books nothing,
   and a nothing is not a zero).

2. **Periods.** Daily / monthly / yearly / lifetime, on the same footing as
   EV — and keyed off the SAME day the device rolls on (the sunrise meter
   day, #620/#704), so there is one day boundary in the system rather than
   two that disagree for six hours every morning.

3. **The split.** Energy booked while SEM was asking for more (SG-Ready
   BOOST / FORCE_ON) is energy SEM shifted; energy booked in NORMAL is
   energy the pump would have used anyway. Without the split "we ran the
   heat pump on solar" is an unfalsifiable claim.

The split mechanism is deliberately generic — a device names its own bucket
— because #685 puts additional heat pumps in the one device list as generic
climate devices, and the ledger is keyed per ``device_id`` from the start.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)
from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode,
    DeviceState,
    SwitchDevice,
)
from custom_components.solar_energy_management.devices.heat_pump_controller import (
    HeatPumpController,
    SGReadyState,
)

TODAY = date(2026, 8, 14)
_START = datetime(2026, 8, 14, 12, 0, 0)
_CURSOR = {"t": _START}


class _Clock:
    """A hass whose states come from a dict."""

    def __init__(self, states: dict | None = None):
        self._states = states or {}
        self.states = SimpleNamespace(get=lambda e: self._states.get(e))

    def set(self, entity: str, value) -> None:
        self._states[entity] = (
            None if value is None
            else SimpleNamespace(state=str(value), attributes={})
        )


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    import custom_components.solar_energy_management.devices.base as base_mod

    _CURSOR["t"] = _START
    fake = MagicMock()
    fake.now.side_effect = lambda: _CURSOR["t"]
    fake.side_effect = lambda *a, **kw: datetime(*a, **kw)
    monkeypatch.setattr(base_mod, "datetime", fake)
    yield


def _device(hass, **kw) -> SwitchDevice:
    dev = SwitchDevice(
        hass=hass, device_id="pool", name="Pool", rated_power=2000,
        entity_id="switch.pool", **kw,
    )
    dev.control_mode = DeviceControlMode.SURPLUS
    dev._status.state = DeviceState.ACTIVE
    return dev


def _run(dev, cycles: int, seconds: float, day: date = TODAY) -> None:
    if dev._daily_runtime_last_check is None:
        dev.update_daily_runtime(day)
    for _ in range(cycles):
        _CURSOR["t"] = _CURSOR["t"] + timedelta(seconds=seconds)
        dev.update_daily_runtime(day)


def _calc() -> EnergyCalculator:
    return EnergyCalculator({}, MagicMock())


# ───────────────────────────────────────────────────────────────────────
# 1. the cycle's increment
# ───────────────────────────────────────────────────────────────────────

class TestTheDeviceReportsWhatItJustBooked:
    """A running total can't be filed. The delta can."""

    def test_a_counter_delta_is_this_cycles_increment(self) -> None:
        hass = _Clock()
        hass.set("sensor.pool_kwh", 100.0)
        dev = _device(hass, energy_entity_id="sensor.pool_kwh")

        _run(dev, 1, 60)                       # baseline read, books nothing
        assert dev.last_cycle_energy_kwh == 0.0

        hass.set("sensor.pool_kwh", 100.25)
        _run(dev, 1, 60)
        assert dev.last_cycle_energy_kwh == pytest.approx(0.25)

        # The NEXT cycle books nothing more — the increment is per cycle,
        # not a high-water mark.
        _run(dev, 1, 60)
        assert dev.last_cycle_energy_kwh == 0.0
        assert dev.daily_energy_kwh == pytest.approx(0.25)

    def test_the_power_path_reports_its_integral(self) -> None:
        hass = _Clock()
        hass.set("sensor.pool_w", 1800)
        dev = _device(hass, power_entity_id="sensor.pool_w")

        _run(dev, 1, 60)   # first read: no previous sample, mean == 1800 W
        assert dev.last_cycle_energy_kwh == pytest.approx(1800 * 60 / 3_600_000)

    def test_the_estimate_reports_its_increment_too(self) -> None:
        """An estimate is still a number the balance has to account for —
        it is flagged, not withheld (#755 contract 1 is about recording it
        AS a measurement, not about hiding it)."""
        dev = _device(_Clock())      # no counter, no power sensor
        _run(dev, 1, 60)
        assert dev.last_cycle_energy_kwh == pytest.approx(2000 * 60 / 3_600_000)
        assert dev.daily_energy_is_measured is False

    def test_a_blind_cycle_books_no_increment(self) -> None:
        hass = _Clock()
        hass.set("sensor.pool_kwh", None)
        dev = _device(hass, energy_entity_id="sensor.pool_kwh")
        _run(dev, 2, 60)
        assert dev.last_cycle_energy_kwh == 0.0
        assert dev.daily_energy_blind_s == pytest.approx(120.0)

    def test_a_counter_that_rebooted_books_no_increment(self) -> None:
        hass = _Clock()
        hass.set("sensor.pool_kwh", 100.0)
        dev = _device(hass, energy_entity_id="sensor.pool_kwh")
        _run(dev, 1, 60)
        hass.set("sensor.pool_kwh", 0.4)      # counter reset
        _run(dev, 1, 60)
        assert dev.last_cycle_energy_kwh == 0.0

    def test_the_day_rollover_clears_the_increment(self) -> None:
        hass = _Clock()
        hass.set("sensor.pool_kwh", 100.0)
        dev = _device(hass, energy_entity_id="sensor.pool_kwh")
        _run(dev, 1, 60)
        hass.set("sensor.pool_kwh", 100.5)
        _run(dev, 1, 60)
        assert dev.last_cycle_energy_kwh == pytest.approx(0.5)

        _CURSOR["t"] = _CURSOR["t"] + timedelta(seconds=60)
        dev.update_daily_runtime(date(2026, 8, 15))
        assert dev.last_cycle_energy_kwh == 0.0


# ───────────────────────────────────────────────────────────────────────
# 2. the attribution bucket
# ───────────────────────────────────────────────────────────────────────

class TestTheSplitLabel:
    def test_an_ordinary_load_has_no_split(self) -> None:
        assert _device(_Clock()).energy_split_label is None

    @pytest.mark.parametrize("state,label", [
        (SGReadyState.BLOCKED, "sg1"),
        (SGReadyState.NORMAL, "sg2"),
        (SGReadyState.BOOST, "sg3"),
        (SGReadyState.FORCE_ON, "sg4"),
    ])
    def test_the_heat_pump_names_its_sg_ready_state(self, state, label) -> None:
        hp = HeatPumpController(hass=_Clock())
        hp._hp_status.sg_ready_state = state
        assert hp.energy_split_label == label

    def test_shifted_means_boost_or_forced(self) -> None:
        """The whole point of the split: separate what SEM caused from what
        the pump would have done on its own thermostat."""
        from custom_components.solar_energy_management.coordinator.energy_calculator import (
            SHIFTED_SPLITS,
        )
        assert SHIFTED_SPLITS == ("sg3", "sg4")


# ───────────────────────────────────────────────────────────────────────
# 3. the ledger
# ───────────────────────────────────────────────────────────────────────

class TestTheLedgerKeepsPeriods:
    def test_increments_roll_up_into_every_period(self) -> None:
        c = _calc()
        for _ in range(3):
            c.accumulate_device_energy("heat_pump", 0.5, TODAY)
        row = c.get_device_energy("heat_pump", TODAY)
        assert row["monthly_kwh"] == pytest.approx(1.5)
        assert row["yearly_kwh"] == pytest.approx(1.5)
        assert row["lifetime_kwh"] == pytest.approx(1.5)

    def test_a_new_month_resets_monthly_and_nothing_else(self) -> None:
        c = _calc()
        c.accumulate_device_energy("heat_pump", 4.0, date(2026, 8, 31))
        c.accumulate_device_energy("heat_pump", 1.0, date(2026, 9, 1))
        row = c.get_device_energy("heat_pump", date(2026, 9, 1))
        assert row["monthly_kwh"] == pytest.approx(1.0)
        assert row["yearly_kwh"] == pytest.approx(5.0)
        assert row["lifetime_kwh"] == pytest.approx(5.0)

    def test_a_new_year_resets_yearly_and_not_lifetime(self) -> None:
        c = _calc()
        c.accumulate_device_energy("heat_pump", 900.0, date(2026, 12, 31))
        c.accumulate_device_energy("heat_pump", 3.0, date(2027, 1, 1))
        row = c.get_device_energy("heat_pump", date(2027, 1, 1))
        assert row["yearly_kwh"] == pytest.approx(3.0)
        assert row["lifetime_kwh"] == pytest.approx(903.0)

    def test_two_devices_do_not_bleed_into_each_other(self) -> None:
        c = _calc()
        c.accumulate_device_energy("heat_pump", 2.0, TODAY)
        c.accumulate_device_energy("pool", 7.0, TODAY)
        assert c.get_device_energy("heat_pump", TODAY)["lifetime_kwh"] == pytest.approx(2.0)
        assert c.get_device_energy("pool", TODAY)["lifetime_kwh"] == pytest.approx(7.0)

    def test_an_unknown_device_reads_zero_not_an_error(self) -> None:
        row = _calc().get_device_energy("never_seen", TODAY)
        assert row["lifetime_kwh"] == 0.0


class TestTheSplitIsKeptBesideTheTotal:
    def test_splits_accumulate_and_sum_to_the_device_total(self) -> None:
        c = _calc()
        c.accumulate_device_energy("heat_pump", 1.0, TODAY, split="sg2")
        c.accumulate_device_energy("heat_pump", 2.0, TODAY, split="sg3")
        c.accumulate_device_energy("heat_pump", 0.5, TODAY, split="sg4")

        daily = c.get_device_splits("heat_pump", TODAY)
        assert daily == {
            "sg2": pytest.approx(1.0),
            "sg3": pytest.approx(2.0),
            "sg4": pytest.approx(0.5),
        }
        assert sum(daily.values()) == pytest.approx(
            c.get_device_energy("heat_pump", TODAY)["lifetime_kwh"]
        )

    def test_shifted_is_boost_plus_forced(self) -> None:
        c = _calc()
        c.accumulate_device_energy("heat_pump", 6.0, TODAY, split="sg2")
        c.accumulate_device_energy("heat_pump", 2.0, TODAY, split="sg3")
        c.accumulate_device_energy("heat_pump", 1.0, TODAY, split="sg4")
        assert c.get_device_shifted("heat_pump", TODAY) == pytest.approx(3.0)

    def test_shifted_lifetime_outlives_the_day(self) -> None:
        c = _calc()
        c.accumulate_device_energy("heat_pump", 2.0, date(2026, 8, 13), split="sg3")
        c.accumulate_device_energy("heat_pump", 1.0, TODAY, split="sg3")
        assert c.get_device_shifted("heat_pump", TODAY) == pytest.approx(1.0)
        assert c.get_device_shifted("heat_pump", TODAY, lifetime=True) == pytest.approx(3.0)

    def test_an_unsplit_increment_still_counts_toward_the_total(self) -> None:
        """A device with no split (every ordinary load) must not vanish."""
        c = _calc()
        c.accumulate_device_energy("pool", 3.0, TODAY)
        assert c.get_device_energy("pool", TODAY)["lifetime_kwh"] == pytest.approx(3.0)
        assert c.get_device_splits("pool", TODAY) == {}


class TestTheLedgerSurvivesARestart:
    def test_state_round_trips(self) -> None:
        c = _calc()
        c.accumulate_device_energy("heat_pump", 4.0, TODAY, split="sg3")
        state = c.get_state()

        fresh = _calc()
        fresh.restore_state(state)
        row = fresh.get_device_energy("heat_pump", TODAY)
        assert row["lifetime_kwh"] == pytest.approx(4.0)
        assert row["monthly_kwh"] == pytest.approx(4.0)
        assert fresh.get_device_shifted("heat_pump", TODAY) == pytest.approx(4.0)


class TestTheCalendarPruneDoesNotEatTheDeviceDay:
    """The device day rolls at SUNRISE (#620/#704). The daily prune keeps
    only keys ending in the CALENDAR day — which is exactly how the EV
    bucket used to get wiped every night, and why it carries an exemption.
    A device split bucket has the same boundary and needs the same one."""

    # The month key the REAL caller passes — ``f"{year}_{month}"``, not an
    # ISO string. Using anything else here would have hidden the bug the
    # monthly test below exists to catch.
    MONTH_KEY = "2026_8"

    def test_a_sunrise_keyed_split_survives_the_midnight_sweep(self) -> None:
        c = _calc()
        # It is 02:00 on the 15th; the load's meter day is still the 14th.
        c.accumulate_device_energy("heat_pump", 2.0, TODAY, split="sg3")
        c._check_rollover(date(2026, 8, 15), self.MONTH_KEY, "2026")
        assert c.get_device_shifted("heat_pump", TODAY) == pytest.approx(2.0)

    def test_last_weeks_split_is_swept(self) -> None:
        c = _calc()
        c.accumulate_device_energy("heat_pump", 2.0, date(2026, 8, 1), split="sg3")
        c._check_rollover(date(2026, 8, 15), self.MONTH_KEY, "2026")
        assert c.get_device_shifted("heat_pump", date(2026, 8, 1)) == 0.0

    def test_the_monthly_total_survives_the_sweep_it_runs_every_cycle(self) -> None:
        """The monthly prune is not gated on the month CHANGING — it runs on
        every cycle and deletes any key that doesn't end in the current
        month key. A device row written under a different key format is
        therefore deleted seconds after it is written, and the monthly total
        silently degrades to 'whatever the last cycle booked'."""
        c = _calc()
        c.accumulate_device_energy("heat_pump", 2.0, TODAY)
        c._check_rollover(TODAY, self.MONTH_KEY, "2026")
        assert c.get_device_energy("heat_pump", TODAY)["monthly_kwh"] == \
            pytest.approx(2.0)

    def test_the_yearly_total_survives_it_too(self) -> None:
        c = _calc()
        c.accumulate_device_energy("heat_pump", 2.0, TODAY)
        c._check_rollover(TODAY, self.MONTH_KEY, "2026")
        assert c.get_device_energy("heat_pump", TODAY)["yearly_kwh"] == \
            pytest.approx(2.0)


# ───────────────────────────────────────────────────────────────────────
# 4. the wiring — the coordinator feeds the ledger every cycle
# ───────────────────────────────────────────────────────────────────────

class TestTheCoordinatorFilesTheIncrement:
    def _coord(self, devices):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )

        calc = MagicMock()
        surplus = MagicMock()
        surplus._devices = devices
        coord = SimpleNamespace(
            _energy_calculator=calc, _surplus_controller=surplus)
        # (#772) The seam derives a comfort bucket for label-less devices;
        # bind the real method so these stand-ins keep exercising the true
        # filing path. None of the devices here carries a comfort band, so
        # the derivation returns None and the #769 expectations stand.
        coord._comfort_split_for = SEMCoordinator._comfort_split_for.__get__(coord)
        return coord

    def test_each_device_increment_is_filed_under_its_split(self) -> None:
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )

        hp = SimpleNamespace(
            device_id="heat_pump",
            last_cycle_energy_kwh=0.4,
            energy_split_label="sg3",
        )
        pool = SimpleNamespace(
            device_id="pool", last_cycle_energy_kwh=0.1, energy_split_label=None,
        )
        coord = self._coord({"heat_pump": hp, "pool": pool})

        SEMCoordinator._file_device_energy(coord, TODAY)

        calls = coord._energy_calculator.accumulate_device_energy.call_args_list
        assert len(calls) == 2
        assert calls[0].args == ("heat_pump", 0.4, TODAY)
        assert calls[0].kwargs == {"split": "sg3"}
        assert calls[1].kwargs == {"split": None}

    def test_a_device_that_booked_nothing_is_not_filed(self) -> None:
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )

        idle = SimpleNamespace(
            device_id="pool", last_cycle_energy_kwh=0.0, energy_split_label=None,
        )
        coord = self._coord({"pool": idle})
        SEMCoordinator._file_device_energy(coord, TODAY)
        coord._energy_calculator.accumulate_device_energy.assert_not_called()

    def test_a_legacy_device_without_the_fields_is_skipped_quietly(self) -> None:
        """Duck-typed stand-ins and any device built before #768 must not
        break the cycle."""
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )

        coord = self._coord({"old": SimpleNamespace(device_id="old")})
        SEMCoordinator._file_device_energy(coord, TODAY)
        coord._energy_calculator.accumulate_device_energy.assert_not_called()


# ───────────────────────────────────────────────────────────────────────
# 5. the surface — the row a heat-pump house can actually read
# ───────────────────────────────────────────────────────────────────────

class TestTheRowSurfaces:
    def test_the_sensor_dataclass_carries_the_ledger(self) -> None:
        from custom_components.solar_energy_management.coordinator.types import (
            HeatPumpSensorData,
        )

        d = HeatPumpSensorData(
            heat_pump_energy_today=3.0,
            heat_pump_energy_month=40.0,
            heat_pump_energy_year=900.0,
            heat_pump_energy_total=4200.0,
            heat_pump_energy_shifted_today=1.2,
            heat_pump_energy_shifted_total=310.0,
            heat_pump_energy_source="counter",
            heat_pump_energy_measured=True,
        )
        assert d.heat_pump_energy_today == 3.0
        assert d.heat_pump_energy_measured is True

    def test_the_sensor_keys_are_published(self) -> None:
        from custom_components.solar_energy_management.coordinator.types import (
            HeatPumpSensorData, SEMData,
        )

        data = SEMData()
        data.heat_pump = HeatPumpSensorData(
            heat_pump_energy_today=3.0,
            heat_pump_energy_month=40.0,
            heat_pump_energy_year=900.0,
            heat_pump_energy_total=4200.0,
            heat_pump_energy_shifted_today=1.2,
        )
        d = data.to_dict()
        assert d["heat_pump_energy_today"] == 3.0
        assert d["heat_pump_energy_month"] == 40.0
        assert d["heat_pump_energy_year"] == 900.0
        assert d["heat_pump_energy_total"] == 4200.0
        assert d["heat_pump_energy_shifted_today"] == 1.2

    def test_every_new_sensor_key_has_an_entity(self) -> None:
        """A published key with no SensorEntityDescription is a number
        nobody can see — the #666 failure mode."""
        from custom_components.solar_energy_management import sensor as sensor_mod

        keys = {d.key for d in sensor_mod.SENSOR_TYPES}
        for k in (
            "heat_pump_energy_today", "heat_pump_energy_month",
            "heat_pump_energy_year", "heat_pump_energy_total",
            "heat_pump_energy_shifted_today",
        ):
            assert k in keys, f"{k} is published but has no entity"

    def test_every_new_sensor_key_is_labelled(self) -> None:
        from custom_components.solar_energy_management.consts.labels import (
            SENSOR_LABEL_MAPPING,
        )

        for k in (
            "heat_pump_energy_today", "heat_pump_energy_month",
            "heat_pump_energy_year", "heat_pump_energy_total",
            "heat_pump_energy_shifted_today",
        ):
            assert k in SENSOR_LABEL_MAPPING, f"{k} has no label registry entry"
