"""#768 — runtime seconds are not energy.

`update_daily_runtime` accrues SECONDS. That is the right number for "has
this device had its hour today" (#620), and it is the only per-device
number SEM keeps. Nothing multiplies it by anything.

Meanwhile two energy signals are read every cycle and dropped on the
floor: the optional #600 energy counter, and `observed_power_w()`. So
every controlled load — heat pump, hot water, pool pump, heizband —
disappears into `home`, which is a residual and therefore cannot complain
(#767).

This adds the per-device daily kWh, sourced in a fixed order and carrying
its provenance:

1. energy counter delta — MEASURED
2. integrated power sensor — MEASURED
3. `rated_power` × runtime — ESTIMATED, flagged, never trainable (#755
   contract 1: an estimate may not be recorded as a measurement)

and a fourth state nobody usually writes down: BLIND. A sensor that
cannot be read is not a device drawing zero watts, so the seconds spent
unable to look are counted and reported rather than quietly booked as 0.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode,
    DeviceState,
    SwitchDevice,
)

TODAY = date(2026, 8, 14)


class _Clock:
    """A hass whose states come from a dict, plus a movable wall clock."""

    def __init__(self, states: dict | None = None):
        self._states = states or {}
        self.states = SimpleNamespace(get=lambda e: self._states.get(e))

    def set(self, entity: str, value) -> None:
        self._states[entity] = (
            None if value is None
            else SimpleNamespace(state=str(value), attributes={})
        )


def _device(hass, **kw) -> SwitchDevice:
    dev = SwitchDevice(
        hass=hass, device_id="pool", name="Pool", rated_power=2000,
        entity_id="switch.pool", **kw,
    )
    dev.control_mode = DeviceControlMode.SURPLUS
    return dev


_START = datetime(2026, 8, 14, 12, 0, 0)
_CURSOR = {"t": _START}


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    """The house pattern (test_device_cooldown): patch the module's
    ``datetime`` so ``now()`` walks a cursor the test advances."""
    import custom_components.solar_energy_management.devices.base as base_mod

    _CURSOR["t"] = _START
    fake = MagicMock()
    fake.now.side_effect = lambda: _CURSOR["t"]
    fake.side_effect = lambda *a, **kw: datetime(*a, **kw)
    monkeypatch.setattr(base_mod, "datetime", fake)
    yield


def _run(dev, cycles: int, seconds: float, day: date = TODAY) -> None:
    """Drive `cycles` coordinator ticks `seconds` apart.

    A device's very first cycle only sets the time reference — there is no
    elapsed window yet — so prime it once and then run exactly `cycles`
    accruing ticks, whether or not this device has been driven before.
    """
    if dev._daily_runtime_last_check is None:
        dev.update_daily_runtime(day)
    for _ in range(cycles):
        _CURSOR["t"] = _CURSOR["t"] + timedelta(seconds=seconds)
        dev.update_daily_runtime(day)


class TestTheCounterIsTheFirstChoice:
    def test_a_counter_delta_is_measured_energy(self) -> None:
        hass = _Clock()
        hass.set("sensor.pool_kwh", 100.0)
        dev = _device(hass, energy_entity_id="sensor.pool_kwh")
        dev._status.state = DeviceState.ACTIVE

        _run(dev, 1, 60)
        hass.set("sensor.pool_kwh", 100.03)
        _run(dev, 1, 60)

        assert dev.daily_energy_kwh == pytest.approx(0.03, abs=1e-6)
        assert dev.daily_energy_source == "counter"
        assert dev.daily_energy_is_measured is True

    def test_a_counter_that_reboots_rebaselines_instead_of_booking(self) -> None:
        """A TOTAL_INCREASING counter that resets to 0 has not un-consumed
        its lifetime energy — the delta is meaningless, not negative."""
        hass = _Clock()
        hass.set("sensor.pool_kwh", 100.0)
        dev = _device(hass, energy_entity_id="sensor.pool_kwh")
        _run(dev, 1, 60)
        hass.set("sensor.pool_kwh", 0.0)
        _run(dev, 1, 60)
        hass.set("sensor.pool_kwh", 0.02)
        _run(dev, 1, 60)

        assert dev.daily_energy_kwh == pytest.approx(0.02, abs=1e-6)

    def test_an_unreadable_counter_is_blind_time_not_zero(self) -> None:
        """#755 contract 1 — silence is never a measurement of zero."""
        hass = _Clock()
        hass.set("sensor.pool_kwh", 100.0)
        dev = _device(hass, energy_entity_id="sensor.pool_kwh")
        _run(dev, 1, 60)
        hass.set("sensor.pool_kwh", None)
        _run(dev, 2, 60)

        assert dev.daily_energy_kwh == 0.0
        assert dev.daily_energy_blind_s == pytest.approx(120.0, abs=1.0)

    def test_the_counter_counts_while_sem_believes_the_device_is_off(self) -> None:
        """The balance wants what the device DREW, not what SEM ran. A heat
        pump on its own thermostat is still energy leaving the house."""
        hass = _Clock()
        hass.set("sensor.pool_kwh", 100.0)
        dev = _device(hass, energy_entity_id="sensor.pool_kwh")
        dev.control_mode = DeviceControlMode.OFF
        _run(dev, 1, 60)
        hass.set("sensor.pool_kwh", 100.5)
        _run(dev, 1, 60)

        assert dev.daily_energy_kwh == pytest.approx(0.5, abs=1e-6)


class TestThePowerSensorIsTheSecond:
    def test_power_is_integrated_over_the_cycle(self) -> None:
        hass = _Clock()
        hass.set("sensor.pool_w", 3600.0)
        dev = _device(hass, power_entity_id="sensor.pool_w")
        dev._status.state = DeviceState.ACTIVE

        _run(dev, 10, 60)  # 3600 W for 10 min = 0.6 kWh

        assert dev.daily_energy_kwh == pytest.approx(0.6, abs=0.01)
        assert dev.daily_energy_source == "power"
        assert dev.daily_energy_is_measured is True

    def test_a_counter_outranks_a_power_sensor_for_energy(self) -> None:
        """The opposite of ``observed_power_w``'s ranking, deliberately: for
        POWER the sensor is direct and the counter is derived; for ENERGY the
        counter IS the integral and the power sensor is the derivation."""
        hass = _Clock()
        hass.set("sensor.pool_w", 3600.0)
        hass.set("sensor.pool_kwh", 100.0)
        dev = _device(
            hass, power_entity_id="sensor.pool_w", energy_entity_id="sensor.pool_kwh"
        )
        _run(dev, 10, 60)

        assert dev.daily_energy_source == "counter"
        assert dev.daily_energy_kwh == 0.0  # the counter did not move


class TestRatedPowerIsTheEstimateOfLastResort:
    def test_no_sensor_falls_back_to_rated_times_runtime(self) -> None:
        hass = _Clock()
        dev = _device(hass)  # 2000 W rated, no power/energy entity
        dev._status.state = DeviceState.ACTIVE

        _run(dev, 30, 60)  # 2000 W × 30 min = 1.0 kWh

        assert dev.daily_energy_kwh == pytest.approx(1.0, abs=0.02)
        assert dev.daily_energy_source == "rated"

    def test_the_estimate_says_it_is_an_estimate(self) -> None:
        hass = _Clock()
        dev = _device(hass)
        dev._status.state = DeviceState.ACTIVE
        _run(dev, 5, 60)

        assert dev.daily_energy_is_measured is False
        assert dev.to_dict()["daily_energy_measured"] is False

    def test_an_idle_device_estimates_nothing(self) -> None:
        hass = _Clock()
        dev = _device(hass)
        _run(dev, 30, 60)

        assert dev.daily_energy_kwh == 0.0

    def test_a_device_with_no_signal_at_all_has_no_number(self) -> None:
        hass = _Clock()
        dev = _device(hass)
        dev.rated_power = 0
        dev._status.state = DeviceState.ACTIVE
        _run(dev, 30, 60)

        assert dev.daily_energy_source == "none"
        assert dev.daily_energy_kwh == 0.0
        assert dev.daily_energy_is_measured is False


class TestTheDayBoundary:
    def test_the_meter_day_rollover_resets_the_kwh(self) -> None:
        hass = _Clock()
        hass.set("sensor.pool_kwh", 100.0)
        dev = _device(hass, energy_entity_id="sensor.pool_kwh")
        _run(dev, 1, 60)
        # 0.5 kWh across the two cycles is 15 kW — a big pool heater, and
        # under #782's physics ceiling. What this test pins is the rollover,
        # not the plausibility of the delta; the numbers are incidental and
        # only have to be numbers a house circuit could actually deliver.
        hass.set("sensor.pool_kwh", 100.5)
        _run(dev, 1, 60)
        assert dev.daily_energy_kwh == pytest.approx(0.5)

        dev.update_daily_runtime(date(2026, 8, 15))
        assert dev.daily_energy_kwh == 0.0
        assert dev.daily_energy_blind_s == 0.0

    def test_the_rollover_keeps_the_counter_baseline(self) -> None:
        """Resetting the baseline too would book the whole lifetime total
        into the first cycle of the new day."""
        hass = _Clock()
        hass.set("sensor.pool_kwh", 100.0)
        dev = _device(hass, energy_entity_id="sensor.pool_kwh")
        _run(dev, 1, 60)
        dev.update_daily_runtime(date(2026, 8, 15))
        hass.set("sensor.pool_kwh", 100.1)
        _run(dev, 1, 60, day=date(2026, 8, 15))

        assert dev.daily_energy_kwh == pytest.approx(0.1, abs=1e-6)


class TestItSurvivesARestart:
    """The runtime persistence (#586/#622) only saves devices that have a
    runtime GOAL configured. The energy balance needs the others most of all —
    an auto-discovered pool pump nobody set a target on is exactly the load
    that vanishes into ``home``."""

    def _coord(self, devices, stored=None):
        storage = MagicMock()
        storage.get_device_runtimes.return_value = stored or {}
        storage.set_device_runtime = MagicMock()
        surplus = MagicMock()
        surplus.get_device = lambda did: devices.get(did)
        surplus._devices = devices
        return SimpleNamespace(_storage=storage, _surplus_controller=surplus)

    def test_a_load_with_no_runtime_goal_is_persisted_for_its_energy(self) -> None:
        dev = _device(_Clock())
        dev._daily_runtime_meter_day = TODAY
        dev._daily_energy_kwh = 1.4
        dev._energy_counter_last_kwh = 100.6
        coord = self._coord({"pool": dev})

        SEMCoordinator._persist_device_runtimes(coord)

        args, kwargs = coord._storage.set_device_runtime.call_args
        assert kwargs.get("accumulated_kwh") == pytest.approx(1.4)
        assert kwargs.get("counter_baseline_kwh") == pytest.approx(100.6)

    def test_the_kwh_comes_back_on_a_fresh_device(self) -> None:
        dev = _device(_Clock())
        coord = self._coord({"pool": dev}, stored={"pool": {
            "accumulated_sec": 0.0, "meter_day": TODAY.isoformat(),
            "accumulated_kwh": 1.4, "counter_baseline_kwh": 100.6,
        }})

        SEMCoordinator._restore_device_runtimes(coord)

        assert dev.daily_energy_kwh == pytest.approx(1.4)
        assert dev._energy_counter_last_kwh == pytest.approx(100.6)

    def test_a_restart_books_the_gap_the_meter_saw(self) -> None:
        """The counter kept counting while HA was down. Within the same meter
        day that is real energy the house used today — restoring the baseline
        is what lets the next cycle book it instead of losing it to a
        re-baseline."""
        hass = _Clock()
        hass.set("sensor.pool_kwh", 100.6)
        dev = _device(hass, energy_entity_id="sensor.pool_kwh")
        coord = self._coord({"pool": dev}, stored={"pool": {
            "accumulated_sec": 0.0, "meter_day": TODAY.isoformat(),
            "accumulated_kwh": 1.4, "counter_baseline_kwh": 100.0,
        }})
        SEMCoordinator._restore_device_runtimes(coord)

        _run(dev, 1, 60)

        assert dev.daily_energy_kwh == pytest.approx(2.0, abs=1e-6)

    def test_the_restore_never_clobbers_a_live_value(self) -> None:
        """A load with no runtime goal accrues 0 seconds forever, so the
        runtime restore's ``accumulated_sec > 0`` guard would let this run
        again and again. Energy needs its own guard."""
        dev = _device(_Clock())
        dev._daily_energy_kwh = 3.0
        dev._energy_counter_last_kwh = 200.0
        coord = self._coord({"pool": dev}, stored={"pool": {
            "accumulated_sec": 0.0, "meter_day": TODAY.isoformat(),
            "accumulated_kwh": 1.4, "counter_baseline_kwh": 100.0,
        }})

        SEMCoordinator._restore_device_runtimes(coord)

        assert dev.daily_energy_kwh == pytest.approx(3.0)
        assert dev._energy_counter_last_kwh == pytest.approx(200.0)


class TestItIsNotTheDeletedGoalSurface:
    def test_no_budget_knob_came_back(self) -> None:
        """#559 deleted a daily ENERGY BUDGET the device steered against.
        This is the opposite direction — an observation that gates nothing —
        and the freeze guard must stay green."""
        dev = _device(_Clock())
        for attr in (
            "daily_target_energy_kwh", "daily_max_energy_kwh",
            "_daily_energy_accumulated_kwh", "daily_max_energy_reached",
            "daily_energy_budget_kwh",
        ):
            assert not hasattr(dev, attr)
