"""#1201 — the battery and grid binary sensors said Off while their power was dark.

``binary_sensor.sem_battery_charging``, ``battery_discharging``,
``grid_export_active`` and ``solar_active`` said Off while every read of the
power they are built from was dark. ``_build_system_status`` built them as
"power > 50 W", and a dark read is 0.0. The status beside them already had
the rule (#1197): None while the power is dark, held through the dark-read
grace, then unknown. Binary sensors had no hold, so a None would have
flipped them on every short blink.

Found beside it: with one unit of two dark (#1186), the power SEM shows
keeps that unit's last read for the grace (``shown_w``), but the status and
the flags were built from the reader's 0 W, so "Idle" stood beside 900 W.

Links, each driven for real:

* the real reader → ``SEMCoordinator._build_system_status`` →
  ``SEMData.to_dict``: a dark power is no flag; a real 0 W is still Off;
* every #1186 shape of a total with one dark unit: the status and flags
  say what they said while the unit was live;
* the real ``SEMSolarBinarySensor``: a flag holds its last value through
  the grace on the power's clock, then shows unknown, never Off;
* a guard: with every power dark, every status field built from a power
  is None, and every such binary sensor is held.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.binary_sensor import (
    BinarySensorEntityDescription,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
)

from custom_components.solar_energy_management.binary_sensor import (
    BINARY_SENSOR_TYPES,
    HELD_FLAG_KEYS,
    SEMSolarBinarySensor,
)
from custom_components.solar_energy_management.consts.core import (
    SENSOR_DARK_READ_GRACE_S,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
    SEMData,
    SystemStatus,
)
from custom_components.solar_energy_management.ha_energy_reader import (
    EnergyDashboardConfig,
)
from custom_components.solar_energy_management.sensor import SEMSolarSensor
from custom_components.solar_energy_management.tests.test_1164_force_charge_stall import (  # noqa: E501
    _reader,
    _state,
)
from custom_components.solar_energy_management.tests.test_1167_own_power_read import (  # noqa: E501
    _ed_reader,
)
from custom_components.solar_energy_management.tests.test_1186_dark_unit_of_a_total import (  # noqa: E501
    SHAPE_IDS,
    SHAPES,
    _read,
    _shape,
)

GRACE = SENSOR_DARK_READ_GRACE_S
FLAGS = ("solar_active", "battery_charging", "battery_discharging",
         "grid_export_active")
CONFIG = {"battery_power_sensor": "sensor.bp", "battery_soc_sensor": "sensor.soc",
          "grid_power_sensor": "sensor.grid",
          "solar_production_sensor": "sensor.pv"}


def _status(power, *, selling=False):
    return SEMCoordinator._build_system_status(
        SimpleNamespace(_battery_arbitrage_active=selling), power, "idle")


def _publish(power, **kw):
    data = SEMData()
    data.power = power
    data.status = _status(power, **kw)
    return data.to_dict()


def _legacy(battery, grid, solar=0, **kw):
    states = {"sensor.soc": _state(60, "%"), "sensor.bp": _state(battery, "W"),
              "sensor.grid": _state(grid, "W"), "sensor.pv": _state(solar, "W")}
    return _publish(_reader(states, dict(CONFIG)).read_power(), **kw)


def _flags(out):
    return {k: out[k] for k in FLAGS}


# ── 1. The reader → the status builder → to_dict ──────────────────────────

class TestADarkPowerIsNoFlag:
    @pytest.mark.parametrize("dark", ["unavailable", "unknown", "none", "nan"])
    def test_the_reporter_case_every_battery_power_dark(self, dark):
        out = _legacy(dark, 300, 2000)
        assert out["battery_power"] is None, "the fleet power's own rule"
        assert out["battery_charging"] is None, "not Off"
        assert out["battery_discharging"] is None, "not Off"
        # the other flags still read their own live power
        assert out["solar_active"] is True
        assert out["grid_export_active"] is True

    @pytest.mark.parametrize("dark", ["unavailable", "unknown", "none", "nan"])
    def test_a_dark_meter_is_no_export_flag(self, dark):
        out = _legacy(0, dark, 2000)
        assert out["grid_power"] is None
        assert out["grid_export_active"] is None, "not Off"
        assert out["battery_charging"] is False

    @pytest.mark.parametrize("dark", ["unavailable", "unknown", "none", "nan"])
    def test_a_dark_inverter_is_no_solar_flag(self, dark):
        out = _legacy(0, 0, dark)
        assert out["solar_power"] is None
        assert out["solar_active"] is None, "not Off"

    def test_a_real_0_w_is_still_off(self):
        """The twin: an idle pack, a quiet meter and a night inverter read
        0 W and say Off."""
        assert _flags(_legacy(0, 0, 0)) == dict.fromkeys(FLAGS, False)

    def test_a_live_power_still_says_what_it_does(self):
        assert _legacy(1500, 0)["battery_charging"] is True
        assert _legacy(1500, 0)["battery_discharging"] is False
        assert _legacy(-1500, 0)["battery_discharging"] is True
        assert _legacy(-1500, 0, selling=True)["battery_discharging"] is True
        # SEM's grid power is positive for export
        assert _legacy(0, 900)["grid_export_active"] is True
        assert _legacy(0, -900)["grid_export_active"] is False
        assert _legacy(0, 0, 2000)["solar_active"] is True

    def test_one_battery_of_two_dark_still_has_its_flags(self):
        """The fleet total is published while one unit answers (#818)."""
        power = _ed_reader({"sensor.b1_power": _state(1500, "W"),
                            "sensor.b2_power": _state("unavailable", "W")},
                           combined=["sensor.b1_power", "sensor.b2_power"]
                           ).read_power()
        out = _publish(power)
        assert out["battery_charging"] is True
        assert out["battery_discharging"] is False

    def test_a_home_with_nothing_but_a_meter_is_off_not_dark(self):
        """Zero config: no battery and no inverter sensor is nothing dark."""
        power = _reader({"sensor.grid": _state(-300, "W")},
                        {"grid_power_sensor": "sensor.grid"}).read_power()
        out = _publish(power)
        assert out["battery_charging"] is False
        assert out["battery_discharging"] is False
        assert out["solar_active"] is False
        assert out["grid_export_active"] is False


# ── 2. One dark unit of a total: the word agrees with the shown number ────

# What each word says, from a published dict
def _words(out):
    return (out["battery_status"], out["grid_status"], _flags(out))


# A solar shape the #1186 list has no case for: the live inverter reads 0 W
SOLAR_ZERO = ("two-inverters-one-at-0",
              dict(ed=EnergyDashboardConfig(
                  solar_power="sensor.inv_a",
                  solar_power_list=["sensor.inv_a", "sensor.inv_b"],
                  has_solar=True)),
              {"sensor.inv_a": 0, "sensor.inv_b": 1500}, "sensor.inv_b",
              "solar_power", 0.0, 1500.0)


class TestADarkUnitKeepsItsWordForTheGrace:
    @pytest.mark.parametrize("shape", SHAPES + [SOLAR_ZERO],
                             ids=SHAPE_IDS + [SOLAR_ZERO[0]])
    def test_the_words_are_what_they_were_while_live(self, shape):
        r, clock, states, dark, field, steering, shown = _shape(shape)
        live = _publish(r.read_power())
        p = _read(r, clock, states, **{dark: "unavailable"})
        held = _publish(p)
        assert held[field] == pytest.approx(shown), "the number SEM shows"
        assert _words(held) == _words(live)

    def test_the_cases_that_tell_old_from_new(self):
        """Not vacuous: in these shapes the reader's 0 W for the dark unit
        gives another word than the shown figure."""
        told = []
        for shape in SHAPES + [SOLAR_ZERO]:
            r, clock, states, dark, *_ = _shape(shape)
            r.read_power()
            p = _read(r, clock, states, **{dark: "unavailable"})
            raw = _publish(dataclasses.replace(p, held_w={}))
            if _words(raw) != _words(_publish(p)):
                told.append(shape[0])
        assert set(told) >= {"fleet-pair-unit", "one-battery-two-sensors",
                             "declared-grid-pair",
                             "manual-grid-pair-dashboard",
                             "two-inverters-one-at-0"}

    @pytest.mark.parametrize("shape", SHAPES + [SOLAR_ZERO],
                             ids=SHAPE_IDS + [SOLAR_ZERO[0]])
    def test_past_the_grace_the_words_follow_the_0_w(self, shape):
        r, clock, states, dark, *_ = _shape(shape)
        r.read_power()
        _read(r, clock, states, **{dark: "unavailable"})
        p = _read(r, clock, states, step=GRACE)
        assert p.held_w == {}
        assert _words(_publish(p)) == _words(
            _publish(dataclasses.replace(p, held_w={})))

    def test_the_trace_says_what_the_held_unit_adds(self):
        """(review) The cycle trace prints the status word beside the
        reader's watts. With a held unit they differ, so it says why."""
        from custom_components.solar_energy_management.tests.test_cycle_trace_wiring import (  # noqa: E501
            _semdata,
            _Stub,
        )
        r, clock, states, dark, *_ = _shape(
            next(s for s in SHAPES if s[0] == "one-battery-two-sensors"))
        r.read_power()
        p = _read(r, clock, states, **{dark: "unavailable"})
        stub = _Stub()
        sem = _semdata(calculated_current=0, reason="", available_power=0,
                       battery_status=_status(p).battery_status)
        stub._collect_trace(sem, p, None)
        bat = stub.trace_recent(1)[0]["subsystems"]["battery"]
        assert bat["process"]["detail"] == "discharging"
        assert bat["process"]["data"]["held_w"] == -900
        assert bat["integration"]["data"]["discharge_w"] == 0, (
            "steering keeps the reader's 0 W")
        # nothing held: the record is as before
        live = _reader({"sensor.bp": _state(500, "W"),
                        "sensor.soc": _state(60, "%")}, dict(CONFIG)).read_power()
        stub._collect_trace(sem, live, None)
        assert "held_w" not in stub.trace_recent(1)[0]["subsystems"][
            "battery"]["process"]["data"]

    def test_selling_reads_the_shown_discharge(self):
        """#523: the 'selling' word comes from the shown discharge too."""
        r, clock, states, dark, *_ = _shape(
            next(s for s in SHAPES if s[0] == "one-battery-two-sensors"))
        r.read_power()
        p = _read(r, clock, states, **{dark: "unavailable"})
        assert _publish(p, selling=True)["battery_status"] == "selling"


# ── 3. The entity: the power's grace, never Off ───────────────────────────

def _flag_entity(coordinator, key):
    coordinator.data = {"last_update": "x"}
    coordinator.last_update_success = True
    return SEMSolarBinarySensor(
        coordinator, BinarySensorEntityDescription(key=key), MagicMock())


def _power_entity(coordinator, key):
    desc = SensorEntityDescription(key=key, name="x",
                                   device_class=SensorDeviceClass.POWER)
    return SEMSolarSensor(coordinator=coordinator, description=desc,
                          entry_id="e")


def _cycle(flag, power, out, t):
    for e in (flag, power):
        e.coordinator.data = out
        e._now_monotonic = lambda: t
    flag._update_from_coordinator()
    power._update_from_coordinator()


# key, power key, a live cycle, the dark cycle, the live value
ENTITY_CASES = [
    ("battery_charging", "battery_power", (1500, 0, 0), ("unavailable", 0, 0),
     True),
    ("battery_discharging", "battery_power", (-800, 0, 0),
     ("unavailable", 0, 0), True),
    ("battery_charging", "battery_power", (0, 0, 0), ("unavailable", 0, 0),
     False),
    ("grid_export_active", "grid_power", (0, 900, 0), (0, "unavailable", 0),
     True),
    ("solar_active", "solar_power", (0, 0, 2500), (0, 0, "unavailable"), True),
]
ENTITY_IDS = [f"{c[0]}-{c[4]}" for c in ENTITY_CASES]


@pytest.mark.parametrize("key,power_key,live,dark,was", ENTITY_CASES,
                         ids=ENTITY_IDS)
def test_the_flag_holds_on_the_power_clock_and_never_says_off(
        mock_coordinator, key, power_key, live, dark, was):
    flag = _flag_entity(mock_coordinator, key)
    power = _power_entity(mock_coordinator, power_key)
    _cycle(flag, power, _legacy(*live), 1000.0)
    assert flag.is_on is was

    _cycle(flag, power, _legacy(*dark), 1010.0)
    assert flag.is_on is was, "held, not flipped"
    assert flag.extra_state_attributes == {"stale_s": 10}
    assert power._attr_available is True, "the number beside it agrees"

    _cycle(flag, power, _legacy(*dark), 1000.0 + GRACE)
    assert flag.is_on is was, "the edge is <=, as the power's"
    assert power._attr_available is True

    _cycle(flag, power, _legacy(*dark), 1000.0 + GRACE + 1)
    assert power._attr_available is False, "one clock for both"
    assert flag.is_on is None, "unknown, not Off"
    assert flag.available is True
    assert flag.extra_state_attributes is None


def test_a_short_blink_never_flips_the_flag(mock_coordinator):
    flag = _flag_entity(mock_coordinator, "battery_discharging")
    power = _power_entity(mock_coordinator, "battery_power")
    seen = []
    for t, battery in ((1000, -800), (1010, "unavailable"),
                       (1020, "unavailable"), (1030, -800), (1040, "unknown")):
        _cycle(flag, power, _legacy(battery, 0), float(t))
        seen.append(flag.is_on)
    assert seen == [True] * 5


def test_a_live_read_ends_the_hold(mock_coordinator):
    flag = _flag_entity(mock_coordinator, "battery_charging")
    power = _power_entity(mock_coordinator, "battery_power")
    _cycle(flag, power, _legacy(1500, 0), 1000.0)
    _cycle(flag, power, _legacy("unavailable", 0), 1010.0)
    _cycle(flag, power, _legacy(0, 0), 1020.0)
    assert flag.is_on is False, "the new read, at once"
    assert flag.extra_state_attributes is None


@pytest.mark.parametrize("key", sorted(HELD_FLAG_KEYS))
def test_a_flag_never_read_is_unknown_not_off(mock_coordinator, key):
    flag = _flag_entity(mock_coordinator, key)
    power = _power_entity(mock_coordinator, "battery_power")
    _cycle(flag, power, _legacy("unavailable", "unavailable", "unavailable"),
           1000.0)
    assert flag.is_on is None
    assert flag.available is True


def test_a_flag_built_at_setup_reads_the_first_cycle(mock_coordinator):
    """The coordinator's first refresh runs before the platform: the entity
    must show it on its first write, not wait a cycle."""
    mock_coordinator.data = _legacy(1500, 0)
    mock_coordinator.last_update_success = True
    flag = SEMSolarBinarySensor(
        mock_coordinator,
        BinarySensorEntityDescription(key="battery_charging"), MagicMock())
    assert flag.is_on is True


def test_the_coordinator_update_runs_the_hold_before_the_write(
        mock_coordinator):
    """HA's own path: ``_handle_coordinator_update`` → the state write. The
    write must see the held value and its ``stale_s``."""
    flag = _flag_entity(mock_coordinator, "grid_export_active")
    flag._now_monotonic = lambda: 1000.0
    mock_coordinator.data = _legacy(0, 900)
    written = []
    with patch.object(SEMSolarBinarySensor, "async_write_ha_state",
                      lambda self: written.append(
                          (self.is_on, self.extra_state_attributes))):
        flag._handle_coordinator_update()
        flag._now_monotonic = lambda: 1030.0
        mock_coordinator.data = _legacy(0, "unavailable")
        flag._handle_coordinator_update()
    assert written == [(True, None), (True, {"stale_s": 30})]


def test_another_binary_sensor_is_not_held(mock_coordinator):
    """The twin: a key outside ``HELD_FLAG_KEYS`` shows its value at once."""
    flag = _flag_entity(mock_coordinator, "ev_connected")
    flag._now_monotonic = lambda: 1000.0
    mock_coordinator.data = {"ev_connected": True}
    flag._update_from_coordinator()
    assert flag.is_on is True
    mock_coordinator.data = {"ev_connected": None}
    flag._update_from_coordinator()
    assert flag.is_on is None
    assert flag.extra_state_attributes is None


# ── 4. Guard: every status field built from a power is held ───────────────

# Fields of ``SystemStatus`` that are not built from a solar, grid or
# battery power, each with why
NOT_FROM_A_POWER = {
    "ev_connected": "the charger's plug state, not a power",
    "ev_charging": "the charger's own state, not a power",
}


def _all_dark_power():
    p = PowerReadings()
    p.solar_power_unavailable = True
    p.grid_power_unavailable = True
    p.battery_power_all_unavailable = True
    return p


def test_every_field_built_from_a_power_is_none_while_it_is_dark():
    status = _status(_all_dark_power())
    for f in dataclasses.fields(SystemStatus):
        if f.name in NOT_FROM_A_POWER:
            continue
        assert getattr(status, f.name) is None, (
            f"SystemStatus.{f.name} reads a dark power as a value; give it "
            "the dark rule or declare it in NOT_FROM_A_POWER")


def test_every_such_binary_sensor_is_held_and_published():
    binary_keys = {d.key for d in BINARY_SENSOR_TYPES}
    out = _publish(_all_dark_power())
    from_a_power = {f.name for f in dataclasses.fields(SystemStatus)
                    if f.name not in NOT_FROM_A_POWER}
    flags = from_a_power & binary_keys
    assert flags == set(FLAGS)
    assert flags == HELD_FLAG_KEYS, (
        "a binary sensor that is None while its power is dark must be held "
        "through the grace, or it flips on every blink")
    for key in HELD_FLAG_KEYS:
        assert key in out and out[key] is None


def test_the_declared_fields_are_real():
    names = {f.name for f in dataclasses.fields(SystemStatus)}
    assert set(NOT_FROM_A_POWER) <= names
