"""#1197 — the battery status said Idle while every battery power sensor was dark.

``sensor.sem_battery_status`` read Idle while the battery power entity beside
it showed unavailable. ``_build_system_status`` built the status from the
charge and discharge power, and a dark read is 0.0 — the same as an idle
pack. The fleet power has a rule for this (``battery_power_all_unavailable``
→ None, held for the dark-read grace, then unavailable); the status built
from it had none. The grid status is the same shape: Idle while the meter is
dark (``grid_power_unavailable``).

Links, each driven for real:

* the real reader → ``SEMCoordinator._build_system_status`` →
  ``SEMData.to_dict``: a dark power is no status; a real 0 W still is Idle;
  one battery of two dark still has a status (the fleet total's rule);
* the real ``SEMSolarSensor``: the status holds its last word through the
  grace on the power's clock, then shows unknown — never Idle. The entity
  stays, so the battery decisions on it stay for the Why card (#1084).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
)

from custom_components.solar_energy_management.consts.core import (
    SENSOR_DARK_READ_GRACE_S,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.types import SEMData
from custom_components.solar_energy_management.sensor import SEMSolarSensor
from custom_components.solar_energy_management.tests.test_1164_force_charge_stall import (  # noqa: E501
    _reader,
    _state,
)
from custom_components.solar_energy_management.tests.test_1167_own_power_read import (  # noqa: E501
    _ed_reader,
)

CONFIG = {"battery_power_sensor": "sensor.bp", "battery_soc_sensor": "sensor.soc",
          "grid_power_sensor": "sensor.grid"}
TWO = ["sensor.b1_power", "sensor.b2_power"]


def _publish(power, *, selling=False):
    data = SEMData()
    data.power = power
    data.status = SEMCoordinator._build_system_status(
        SimpleNamespace(_battery_arbitrage_active=selling), power, "idle")
    return data.to_dict()


def _legacy(battery, grid, **kw):
    states = {"sensor.soc": _state(60, "%"), "sensor.bp": _state(battery, "W"),
              "sensor.grid": _state(grid, "W")}
    return _publish(_reader(states, dict(CONFIG)).read_power(), **kw)


# ── 1. The reader → the status builder → to_dict ──────────────────────────

class TestADarkPowerIsNoStatus:
    def test_the_reporter_case_every_battery_power_dark(self):
        out = _legacy("unavailable", 300)
        assert out["battery_power"] is None, "the fleet power's own rule"
        assert out["battery_status"] is None, "not 'idle'"

    def test_unknown_is_no_status(self):
        assert _legacy("unknown", 300)["battery_status"] is None

    def test_a_state_that_is_no_number_is_no_status(self):
        """(#1202) "none" or "nan" is dark like "unavailable"."""
        assert _legacy("none", 300)["battery_status"] is None
        assert _legacy("nan", 300)["battery_status"] is None

    def test_a_real_0_w_is_still_idle(self):
        """The twin: an idle pack reads 0 W and says so."""
        out = _legacy(0, 300)
        assert out["battery_power"] == 0.0
        assert out["battery_status"] == "idle"

    def test_a_live_pack_still_says_what_it_does(self):
        assert _legacy(1500, 300)["battery_status"] == "charging"
        assert _legacy(-1500, 300)["battery_status"] == "discharging"
        assert _legacy(-1500, 300, selling=True)["battery_status"] == "selling"

    def test_a_dark_pack_is_no_status_even_while_selling(self):
        assert _legacy("unavailable", 300, selling=True)["battery_status"] is None

    def test_one_battery_of_two_dark_still_has_a_status(self):
        """The fleet total is published while one unit answers (#818), so the
        status built from it is too; the dark unit's own is None (#1170)."""
        power = _ed_reader({"sensor.b1_power": _state(1500, "W"),
                            "sensor.b2_power": _state("unavailable", "W")},
                           combined=TWO).read_power()
        out = _publish(power)
        assert out["battery_status"] == "charging"
        assert out["battery_b2_status"] is None

    def test_both_batteries_dark_is_no_status(self):
        power = _ed_reader({"sensor.b1_power": _state("unavailable", "W"),
                            "sensor.b2_power": _state("unavailable", "W")},
                           combined=TWO).read_power()
        assert _publish(power)["battery_status"] is None

    def test_a_home_with_no_battery_is_idle_not_dark(self):
        """Zero config: no battery sensor, nothing dark, the old word."""
        power = _reader({"sensor.grid": _state(-300, "W")},
                        {"grid_power_sensor": "sensor.grid"}).read_power()
        out = _publish(power)
        assert out["battery_status"] == "idle"
        assert out["grid_status"] == "import"


class TestADarkMeterIsNoGridStatus:
    def test_a_dark_meter_is_no_grid_status(self):
        out = _legacy(0, "unavailable")
        assert out["grid_power"] is None
        assert out["grid_status"] is None, "not 'idle'"

    def test_a_quiet_meter_is_still_idle(self):
        assert _legacy(0, 0)["grid_status"] == "idle"

    def test_a_live_meter_still_says_what_it_does(self):
        # SEM's grid power is positive for export
        assert _legacy(0, -900)["grid_status"] == "import"
        assert _legacy(0, 900)["grid_status"] == "export"


# ── 2. The entity: the power's grace, never Idle ──────────────────────────

def _entity(mock_coordinator, key):
    mock_coordinator.data = {"last_update": "x"}
    mock_coordinator.last_update_success = True
    desc = SensorEntityDescription(key=key, name="x", device_class=None)
    return SEMSolarSensor(coordinator=mock_coordinator, description=desc,
                          entry_id="e")


def _power_entity(mock_coordinator, key):
    mock_coordinator.data = {"last_update": "x"}
    desc = SensorEntityDescription(key=key, name="x",
                                   device_class=SensorDeviceClass.POWER)
    return SEMSolarSensor(coordinator=mock_coordinator, description=desc,
                          entry_id="e")


def _cycle(entities, battery, grid, t):
    out = _legacy(battery, grid)
    for e in entities:
        e.coordinator.data = out
        e._now_monotonic = lambda: t
        e._update_from_coordinator()


@pytest.mark.parametrize("key,power_key,live,dark_battery,dark_grid,word", [
    ("battery_status", "battery_power", (-800, 300), "unavailable", 300,
     "Discharging"),
    ("grid_status", "grid_power", (0, -900), 0, "unavailable", "Importing"),
])
def test_the_status_holds_on_the_power_clock_and_never_says_idle(
        mock_coordinator, key, power_key, live, dark_battery, dark_grid, word):
    status = _entity(mock_coordinator, key)
    power = _power_entity(mock_coordinator, power_key)
    _cycle([status, power], *live, 1000.0)
    assert status.native_value == word

    _cycle([status, power], dark_battery, dark_grid, 1010.0)
    assert status._attr_available is True
    assert status.native_value == word, "held, not Idle"
    assert status.extra_state_attributes.get("stale_s") == 10
    assert power._attr_available is True, "the number beside it agrees"

    _cycle([status, power], dark_battery, dark_grid,
           1000.0 + SENSOR_DARK_READ_GRACE_S + 1)
    assert power._attr_available is False, "one clock for both"
    assert status.native_value is None, "not Idle"
    # unknown, not unavailable: the entity stays, with its attributes
    assert status._attr_available is True
    assert status.available is True


@pytest.mark.parametrize("key,battery,grid", [
    ("battery_status", "unavailable", 300),
    ("grid_status", 0, "unavailable"),
])
def test_a_status_never_read_is_unknown_not_idle(
        mock_coordinator, key, battery, grid):
    status = _entity(mock_coordinator, key)
    _cycle([status], battery, grid, 1000.0)
    assert status.native_value is None
    assert status._attr_available is True


def test_a_real_idle_is_published_as_idle(mock_coordinator):
    status = _entity(mock_coordinator, "battery_status")
    _cycle([status], 0, 0, 1000.0)
    assert status._attr_available is True
    assert status.native_value == "Idle"


def test_the_battery_decisions_stay_on_the_status_while_dark(mock_coordinator):
    """The Why card reads the battery's newest decision from this entity's
    ``per_battery_last_decision`` (#1084); an hour of dark battery must not
    hide a Force charge SEM started meanwhile."""
    from custom_components.solar_energy_management.tests.test_1084_decision_log import (  # noqa: E501
        KIND_BATTERY,
        _log,
        _rec,
    )
    status = _entity(mock_coordinator, "battery_status")
    log = _log()
    _rec(log, "force_charge", 3000, kind=KIND_BATTERY, did="b1")
    mock_coordinator._surplus_controller = SimpleNamespace(decision_log=log)
    _cycle([status], 500, 0, 1000.0)
    _cycle([status], "unavailable", 0, 1000.0 + 3600)
    assert status.native_value is None
    assert status.available is True
    assert "b1" in status.extra_state_attributes["per_battery_last_decision"]


def test_the_trace_reads_a_dark_status_as_no_word():
    """The cycle trace (real ``_trace_battery``) reads the status; None must
    not break it or print the word "None"."""
    from custom_components.solar_energy_management.tests.test_cycle_trace_wiring import (  # noqa: E501
        _power as _trace_power,
        _semdata,
        _Stub,
    )
    stub = _Stub()
    dark = _reader({"sensor.soc": _state(60, "%"),
                    "sensor.bp": _state("unavailable", "W")},
                   dict(CONFIG)).read_power()
    sem = _semdata(calculated_current=0, reason="", available_power=0,
                   battery_status=SEMCoordinator._build_system_status(
                       SimpleNamespace(_battery_arbitrage_active=False),
                       dark, "idle").battery_status)
    stub._collect_trace(sem, _trace_power(ev_power=0.0), None)
    bat = stub.trace_recent(1)[0]["subsystems"]["battery"]
    assert bat["process"]["detail"] == ""
