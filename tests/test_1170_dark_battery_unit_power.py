"""#1170 — a battery's own power entity showed 0 W while its sensor was dark.

With two batteries, ``sensor.sem_battery_b2_power`` read 0 W while battery
2's power sensor was unavailable. An idle pack also reads 0 W, so the two
looked the same; the SOC entity beside it already said unknown. The fleet
total keeps a rule for this (``battery_power_all_unavailable`` → None, the
entity holds its last value for the dark-read grace and then shows
unavailable). Each unit had no such rule: ``to_dict`` published the reader's
0.0 fallback as a reading, and the status built from it said "idle".

Each unit now publishes its power and status as None when its own
``power_read`` (#1167) is False. Links, each driven for real:

* the real reader → ``SEMData.to_dict`` for a dark, unknown, not-a-number,
  impossible and half-dark (two-sensor pair) unit, and the sign flip;
* the real ``SEMSolarSensor`` holds the unit's last value for the grace and
  then shows unavailable — never 0 W; the status holds on the same clock,
  then shows unknown (#1197), and never says "idle";
* a structural list of every per-unit key ``to_dict`` publishes, so a new
  per-unit reading cannot ship without the rule (or a filed reason).
"""
from __future__ import annotations

import re

import pytest
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
)

from custom_components.solar_energy_management.consts.core import (
    SENSOR_DARK_READ_GRACE_S,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryPower,
)
from custom_components.solar_energy_management.coordinator.types import (
    SEMData,
    StringEnergy,
)
from custom_components.solar_energy_management.sensor import SEMSolarSensor
from custom_components.solar_energy_management.tests.test_1164_force_charge_stall import (  # noqa: E501
    _state,
)
from custom_components.solar_energy_management.tests.test_1167_own_power_read import (  # noqa: E501
    _ed_reader,
)

TWO = ["sensor.b1_power", "sensor.b2_power"]


def _published(states, **kw):
    data = SEMData()
    data.power = _ed_reader(states, **kw).read_power()
    return data.to_dict()


# ── 1. The reader → to_dict ────────────────────────────────────────────────

class TestADarkUnitPublishesNoPower:
    def test_the_reporter_case_b2_dark_b1_live(self):
        out = _published({"sensor.b1_power": _state(1500, "W"),
                          "sensor.b2_power": _state("unavailable", "W")},
                         combined=TWO)
        assert out["battery_b2_power"] is None, "not the reader's 0.0"
        assert out["battery_b2_status"] is None, "not 'idle'"
        assert out["battery_b1_power"] == 1500.0
        assert out["battery_b1_status"] == "charging"
        # The fleet total is not dark: one unit still answers, so it shows
        # the sum it has (#818's rule) — the unit's flag is the unit's.
        assert out["battery_power"] == 1500.0

    def test_an_idle_pack_still_reads_0_w(self):
        """The twin: a real 0 W is a reading and is published as one."""
        out = _published({"sensor.b1_power": _state(1500, "W"),
                          "sensor.b2_power": _state(0, "W")}, combined=TWO)
        assert out["battery_b2_power"] == 0.0
        assert out["battery_b2_status"] == "idle"

    @pytest.mark.parametrize("dark", [
        "unavailable", "unknown", "none", 22_806_824,
    ], ids=["unavailable", "unknown", "not-a-number", "impossible-902"])
    def test_every_shape_of_no_reading(self, dark):
        out = _published({"sensor.b1_power": _state(-300, "W"),
                          "sensor.b2_power": _state(dark, "W")}, combined=TWO)
        assert out["battery_b2_power"] is None
        assert out["battery_b2_status"] is None
        assert out["battery_b1_power"] == -300.0
        assert out["battery_b1_status"] == "discharging"

    @pytest.mark.parametrize("to_state,from_state,power", [
        ("1200", "0", 1200.0),
        ("unavailable", "0", None),     # a dark side is half a number
        ("0", "unavailable", None),
    ])
    def test_a_two_sensor_pair_needs_both_sides(self, to_state, from_state,
                                                power):
        out = _published({"sensor.b1_power": _state(0, "W"),
                          "sensor.p_to": _state(to_state, "W"),
                          "sensor.p_from": _state(from_state, "W")},
                         combined=["sensor.b1_power"],
                         pairs=[("sensor.p_from", "sensor.p_to")])
        assert out["battery_b2_power"] == power
        assert (out["battery_b2_status"] is None) is (power is None)

    def test_the_sign_flip_does_not_turn_a_dark_unit_into_a_number(self):
        out = _published({"sensor.b1_power": _state(250, "W"),
                          "sensor.b2_power": _state("unavailable", "W")},
                         combined=TWO, config={  # (#1375) the tap names each battery
                             "battery_sign_user_flip_sensors": [
                                 "sensor.b1_power", "sensor.b2_power"]})
        assert out["battery_b1_power"] == -250.0, "the flip ran"
        assert out["battery_b2_power"] is None

    def test_a_unit_never_marked_read_publishes_no_power(self):
        """The flag is opt-in: a reading nobody said was read is none."""
        data = SEMData()
        data.power.batteries = {
            "b1": BatteryPower(battery_id="b1", power_w=0.0, soc_pct=50.0),
            "b2": BatteryPower(battery_id="b2", power_w=-200.0, soc_pct=50.0,
                               power_read=True),
        }
        out = data.to_dict()
        assert out["battery_b1_power"] is None
        assert out["battery_b2_power"] == -200.0
        assert out["battery_b1_soc"] == 50.0, "the SOC keeps its own rule"


# ── 2. The entity: the fleet's grace, never a 0 W ──────────────────────────

def _entity(mock_coordinator, key, device_class):
    mock_coordinator.data = {"last_update": "x"}
    mock_coordinator.last_update_success = True
    desc = SensorEntityDescription(key=key, name="x", device_class=device_class)
    return SEMSolarSensor(coordinator=mock_coordinator, description=desc,
                          entry_id="e")


def _cycle(entities, b2_state, t):
    out = _published({"sensor.b1_power": _state(1500, "W"),
                      "sensor.b2_power": _state(b2_state, "W")}, combined=TWO)
    for e in entities:
        e.coordinator.data = out
        e._now_monotonic = lambda: t
        e._update_from_coordinator()


class TestTheEntityHoldsThenShowsUnavailable:
    def test_a_blink_holds_the_last_value_then_an_outage_blanks(
            self, mock_coordinator):
        power = _entity(mock_coordinator, "battery_b2_power",
                        SensorDeviceClass.POWER)
        _cycle([power], -800, 1000.0)
        assert power.native_value == -800.0 and power._attr_available

        _cycle([power], "unavailable", 1030.0)
        assert power._attr_available is True
        assert power.native_value == -800.0, "held, not 0 W"
        assert power.extra_state_attributes.get("stale_s") == 30

        _cycle([power], "unavailable", 1000.0 + SENSOR_DARK_READ_GRACE_S + 1)
        assert power._attr_available is False
        assert power.native_value is None, "unavailable, not 0 W"

    def test_never_read_is_unavailable_not_0_w(self, mock_coordinator):
        power = _entity(mock_coordinator, "battery_b2_power",
                        SensorDeviceClass.POWER)
        _cycle([power], "unavailable", 1000.0)
        assert power._attr_available is False
        assert power.native_value is None

    def test_the_status_holds_on_the_power_clock_and_never_says_idle(
            self, mock_coordinator):
        """The status is built from the power, so it blinks and blanks with
        it: held through the grace (no flip to unavailable or to "idle" on
        a one-cycle blink), then unavailable."""
        power = _entity(mock_coordinator, "battery_b2_power",
                        SensorDeviceClass.POWER)
        status = _entity(mock_coordinator, "battery_b2_status", None)
        _cycle([power, status], -800, 1000.0)
        assert status.native_value == "discharging"

        _cycle([power, status], "unavailable", 1010.0)
        assert status._attr_available is True
        assert status.native_value == "discharging", "held, not idle"
        assert status.extra_state_attributes.get("stale_s") == 10
        assert power.native_value == -800.0, "the number beside it agrees"

        _cycle([power, status], "unavailable",
               1000.0 + SENSOR_DARK_READ_GRACE_S + 1)
        # (#1197) unknown, not unavailable: the entity stays, and with it
        # its decision attributes (#1084).
        assert status._attr_available is True
        assert status.native_value is None
        assert power._attr_available is False, "one clock for both"

    def test_a_status_never_read_is_unknown_not_idle(self,
                                                      mock_coordinator):
        status = _entity(mock_coordinator, "battery_b2_status", None)
        _cycle([status], "unavailable", 1000.0)
        assert status.native_value is None, "not idle"
        assert status._attr_available is True, "unknown (#1197)"

    def test_only_a_battery_unit_status_is_held(self, mock_coordinator):
        """The twin: every other text sensor shows its None at once."""
        other = _entity(mock_coordinator, "battery_session_type", None)
        for value, t in (("charge", 1000.0), (None, 1010.0)):
            other.coordinator.data = {**other.coordinator.data,
                                      "battery_session_type": value}
            other._now_monotonic = lambda t=t: t
            other._update_from_coordinator()
        assert other._attr_available is False
        assert other.native_value is None


# ── 3. Every per-unit key to_dict publishes is declared ────────────────────

# A per-battery or per-PV-string key and the rule that blanks it when the
# unit's own sensor is dark. A new key of these units fails until it is
# listed here with its rule — or with the filed issue that says why it does
# not have one yet. (Per-charger keys are SEM's own sums and sessions, not a
# sensor read, and the per-charger power is published by the coordinator.)
_PER_UNIT = re.compile(r"^(battery|pv_string)_((?:b|pv)\d+)_(\w+)$")
_DECLARED = {
    ("battery", "power"): "power_read (#1170)",
    ("battery", "status"): "power_read (#1170)",
    ("battery", "soc"): "soc_pct None while unresolved (#694)",
    ("battery", "capacity_kwh"): "a size, not a reading",
    ("pv_string", "power"): "solar_power_per_string_read (#1196)",
    ("pv_string", "daily_energy"): "an integral (class 58)",
}
_BLANKS_ON_POWER_READ = {k for k, why in _DECLARED.items()
                         if why.startswith("power_read")}
_BLANKS_ON_STRING_READ = {k for k, why in _DECLARED.items()
                          if why.startswith("solar_power_per_string_read")}


def _every_unit_dark():
    data = SEMData()
    data.power.batteries = {
        "b1": BatteryPower(battery_id="b1", power_w=1500.0, soc_pct=50.0,
                           capacity_kwh=5.0, power_read=True),
        "b2": BatteryPower(battery_id="b2", power_w=0.0, soc_pct=None,
                           capacity_kwh=5.0, power_read=False),
    }
    data.power.solar_power_per_string = {"pv1": 0.0, "pv2": 0.0}
    # (#1196) pv1 a real 0 W (night), pv2 dark
    data.power.solar_power_per_string_read = {"pv1": True, "pv2": False}
    data.energy_flows.per_string = {"pv1": StringEnergy(1.0),
                                    "pv2": StringEnergy(0.0)}
    return data.to_dict()


def test_every_per_unit_key_is_declared():
    out = _every_unit_dark()
    seen = set()
    for key in out:
        m = _PER_UNIT.match(key)
        if not m:
            continue
        family = (m.group(1), m.group(3))
        seen.add(family)
        assert family in _DECLARED, (
            f"{key}: a per-unit key with no declared dark rule (#1170) — "
            "does it blank when its unit's own sensor is dark?")
    assert seen == set(_DECLARED), (
        "the fixture must publish every declared key, or the scan proves "
        f"nothing: missing {set(_DECLARED) - seen}")


def test_every_power_read_key_blanks_on_the_dark_unit_only():
    out = _every_unit_dark()
    for prefix, field in _BLANKS_ON_POWER_READ:
        assert out[f"{prefix}_b2_{field}"] is None, f"{prefix}_b2_{field}"
        assert out[f"{prefix}_b1_{field}"] is not None, f"{prefix}_b1_{field}"
    assert _BLANKS_ON_STRING_READ, "the string rule is declared"
    for prefix, field in _BLANKS_ON_STRING_READ:
        assert out[f"{prefix}_pv2_{field}"] is None, f"{prefix}_pv2_{field}"
        assert out[f"{prefix}_pv1_{field}"] == 0.0, f"{prefix}_pv1_{field}"
