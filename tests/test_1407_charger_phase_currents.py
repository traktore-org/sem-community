"""#1407 — a charge SEM did not start read "0 A" and the configured 3 phases.

@RVallen78: a Zaptec charged at 7.26 A on one phase (1.5 kW), run by evcc,
SEM's mode Off. The card said "charging · 0 A" and "0 A ●●● 3 phases".
Zaptec's own sensors said 7.26 / 0.04 / 0.02 A.

Two readers took SEM's command for the charge: the card's amps were
``commanded_current`` (0 while SEM sends nothing), and the phase estimate
divides the power by that command, so with no command it said nothing and
the card fell back to the configured 3.

Now SEM reads the charger's own current on each phase where its device has
one sensor per phase (Zaptec, Peblar, go-e, NRGkick): the highest phase
current is the amps, the phases at 1 A or more are the count. The W/A
estimate stays the fallback. The cards share one amps rule
(``dashboard/card/test/charger-amps.test.js``).
"""
from __future__ import annotations

import json
import math
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.ev_phases import (
    PHASE_LEG_ACTIVE_A,
    estimate_active_phases,
    phases_from_leg_currents,
)
from custom_components.solar_energy_management.coordinator.units import (
    current_state_to_amps,
)
from custom_components.solar_energy_management.devices.base import (
    CurrentControlDevice,
)
from custom_components.solar_energy_management.hardware_detection import (
    phase_current_legs,
)

from .cycle_rig import CycleRig, make_hass

HERE = os.path.dirname(os.path.abspath(__file__))
CAPTURES = os.path.join(HERE, "integrations_rig", "captures")


def _entries(capture, device=None):
    """Registry-shaped entries of one capture, optionally one device's."""
    with open(os.path.join(CAPTURES, capture + ".json"), encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for e in data["entities"]:
        if device is not None and e.get("device") != device:
            continue
        out.append(SimpleNamespace(
            entity_id=e["entity_id"], unique_id=e.get("unique_id"),
            translation_key=e.get("translation_key"),
            original_device_class=e.get("original_device_class"),
            unit_of_measurement=e.get("unit_of_measurement"),
            disabled_by=e.get("disabled_by"), device_id=e.get("device")))
    return out


def _leg(eid, uid, tk=None, dc="current", unit="A", disabled=None, dev="d1"):
    return SimpleNamespace(entity_id=eid, unique_id=uid, translation_key=tk,
                           original_device_class=dc, unit_of_measurement=unit,
                           disabled_by=disabled, device_id=dev)


ZAP = "sensor.zaptec_go2_zap012345_current_phase"


# ── which sensors are the phases ─────────────────────────────────────────

class TestTheLegs:

    def test_zaptec_charger_device(self):
        assert phase_current_legs(_entries("zaptec", "zaptec:chg1")) == (
            ZAP + "1", ZAP + "2", ZAP + "3")

    def test_zaptec_installation_is_no_charger(self):
        """``available_current_phase1..3`` is the site's limit, not a flow."""
        assert phase_current_legs(_entries("zaptec", "zaptec:inst1")) is None

    def test_zaptec_whole_capture_never_takes_the_site_limit(self):
        legs = phase_current_legs(_entries("zaptec"))
        assert legs == (ZAP + "1", ZAP + "2", ZAP + "3")

    def test_dutch_entity_ids_are_read_by_key(self):
        """The reporter's install: ids in Dutch, keys in English."""
        es = [_leg(f"sensor.laadpaal_stroom_fase{n}", f"abc_current_phase{n}",
                   f"current_phase{n}") for n in (1, 2, 3)]
        assert phase_current_legs(es) == tuple(
            f"sensor.laadpaal_stroom_fase{n}" for n in (1, 2, 3))

    @pytest.mark.parametrize("capture,prefix", [
        ("peblar", "sensor.peblar_ev_charger_current_phase_"),
        ("goecharger", "sensor.goecharger_wallbox_go_e_i_l"),
    ])
    def test_other_brands(self, capture, prefix):
        assert phase_current_legs(_entries(capture)) == tuple(
            f"{prefix}{n}" for n in (1, 2, 3))

    def test_nrgkick(self):
        assert phase_current_legs(_entries("nrgkick")) == tuple(
            f"sensor.nrgkick_test_l{n}_current" for n in (1, 2, 3))

    @pytest.mark.parametrize("capture", ["easee", "keba", "openevse", "ohme",
                                         "v2c", "tesla_fleet"])
    def test_no_phase_sensors_is_none(self, capture):
        assert phase_current_legs(_entries(capture)) is None

    def test_two_sensors_for_one_phase_is_none(self):
        es = [_leg(f"sensor.a_l{n}", f"a_l{n}") for n in (1, 2, 3)]
        es.append(_leg("sensor.b_l1", "b_current_l1"))
        assert phase_current_legs(es) is None

    def test_a_missing_phase_is_none(self):
        es = [_leg(f"sensor.a_l{n}", f"a_l{n}") for n in (1, 2)]
        assert phase_current_legs(es) is None

    def test_a_disabled_phase_is_none(self):
        es = [_leg(f"sensor.a_l{n}", f"a_l{n}",
                   disabled="integration" if n == 3 else None) for n in (1, 2, 3)]
        assert phase_current_legs(es) is None

    @pytest.mark.parametrize("word", ["available", "max", "limit", "offered",
                                      "set", "dynamic", "circuit", "min"])
    def test_a_limit_is_no_flow(self, word):
        es = [_leg(f"sensor.a_{word}_current_l{n}", f"a_{word}_current_l{n}")
              for n in (1, 2, 3)]
        assert phase_current_legs(es) is None

    @pytest.mark.parametrize("word", ["max", "requested", "allocated", "pilot",
                                      "grid", "house", "installation"])
    def test_a_dash_ends_a_word_too(self, word):
        """Review: ``{serial}-{key}`` unique ids — ``abc123-max_current_l1``."""
        es = [_leg(f"sensor.a_l{n}", f"abc123-{word}_current_l{n}")
              for n in (1, 2, 3)]
        assert phase_current_legs(es) is None

    def test_a_serial_dash_key_leg_is_found(self):
        es = [_leg(f"sensor.a_l{n}", f"abc123-current_l{n}") for n in (1, 2, 3)]
        assert phase_current_legs(es) == tuple(f"sensor.a_l{n}" for n in (1, 2, 3))

    def test_sems_own_sensors_are_never_a_chargers(self):
        """Class 136: SEM's own per-phase diagnostics on the same device."""
        es = [_leg(f"sensor.sem_diag_l{n}", f"diag_grid_l{n}_current_a")
              for n in (1, 2, 3)]
        for e in es:
            e.platform = "solar_energy_management"
        assert phase_current_legs(es) is None

    def test_voltage_and_power_legs_are_not_currents(self):
        es = [_leg(f"sensor.a_voltage_l{n}", f"a_voltage_l{n}", dc="voltage",
                   unit="V") for n in (1, 2, 3)]
        es += [_leg(f"sensor.a_power_l{n}", f"a_power_l{n}", dc="power",
                    unit="W") for n in (1, 2, 3)]
        assert phase_current_legs(es) is None

    def test_no_device_class_but_amps(self):
        es = [_leg(f"sensor.a_i_l{n}", f"a_i_l{n}", dc=None, unit="mA")
              for n in (1, 2, 3)]
        assert phase_current_legs(es) == tuple(
            f"sensor.a_i_l{n}" for n in (1, 2, 3))

    def test_three_phase_sum_is_no_leg(self):
        """``3_phase`` names all three, not phase 3."""
        es = [_leg("sensor.a_3_phase_current", "a_3_phase_current")]
        assert phase_current_legs(es) is None


# ── amps and phases from the legs ────────────────────────────────────────

class TestTheRule:

    def test_the_report(self):
        assert phases_from_leg_currents([7.26, 0.04, 0.02]) == (7.3, 1)

    def test_three_phases(self):
        assert phases_from_leg_currents([9.8, 9.9, 9.7]) == (9.9, 3)

    def test_two_phases(self):
        assert phases_from_leg_currents([10.0, 10.1, 0.1]) == (10.1, 2)

    def test_idle_reads_its_amps_and_no_count(self):
        assert phases_from_leg_currents([0.04, 0.02, 0.0]) == (0.0, None)

    def test_the_threshold(self):
        just = PHASE_LEG_ACTIVE_A
        assert phases_from_leg_currents([just, 0.0, 0.0]) == (round(just, 1), 1)
        assert phases_from_leg_currents([just - 0.01, 0.0, 0.0])[1] is None

    def test_a_negative_reading_counts_by_size(self):
        assert phases_from_leg_currents([-7.2, 0.0, 0.0]) == (7.2, 1)

    @pytest.mark.parametrize("bad", [None, [], [math.nan, 1, 1],
                                     [math.inf, 1, 1], ["x", 1, 1]])
    def test_no_reading(self, bad):
        assert phases_from_leg_currents(bad) == (None, None)

    def test_power_agrees(self):
        assert phases_from_leg_currents([7.26, 0.04, 0.02], power_w=1500) == (7.3, 1)
        assert phases_from_leg_currents([0.04, 0.02, 0.0], power_w=0) == (0.0, None)

    def test_lagging_phases_show_nothing(self):
        """Review: power says 7 kW, the phases still read idle — not "0 A"."""
        assert phases_from_leg_currents([0.04, 0.02, 0.0], power_w=7000) == (None, None)

    def test_lagging_power_shows_nothing(self):
        """The reverse: the charge ended, the phases still read 7 A."""
        assert phases_from_leg_currents([7.0, 0.0, 0.0], power_w=0) == (None, None)

    def test_milliamps(self):
        st = SimpleNamespace(state="7260", attributes={"unit_of_measurement": "mA"})
        assert current_state_to_amps(st) == pytest.approx(7.26)
        st = SimpleNamespace(state="unavailable", attributes={})
        assert current_state_to_amps(st) is None

    def test_the_old_estimate_had_nothing_to_divide_by(self):
        """The twin: SEM commands 0 A, so W/A says nothing."""
        assert estimate_active_phases(1500.0, 0, 230.0) is None


# ── the charger reads its own device ─────────────────────────────────────

class _Registry:
    def __init__(self, entries):
        self.entries = list(entries)

    def async_get(self, entity_id):
        for e in self.entries:
            if e.entity_id == entity_id:
                return e
        return None


@pytest.fixture
def registry(monkeypatch):
    from homeassistant.helpers import entity_registry as er
    reg = _Registry([])
    monkeypatch.setattr(er, "async_get", lambda hass: reg)
    monkeypatch.setattr(
        er, "async_entries_for_device",
        lambda r, dev_id, **kw: [e for e in r.entries if e.device_id == dev_id])
    return reg


def _zaptec_registry(reg, dev="zaptec:chg1", prefix="zap"):
    """A Zaptec charger device and its site, as the registry holds them."""
    reg.entries += [
        _leg(f"number.{prefix}_charger_max_current", f"{prefix}_charger_max_current",
             "charger_max_current", dev=dev),
        _leg(f"sensor.{prefix}_total_charge_power", f"{prefix}_total_charge_power",
             "total_charge_power", dc="power", unit="W", dev=dev),
    ] + [_leg(f"sensor.{prefix}_current_phase{n}", f"{prefix}_current_phase{n}",
              f"current_phase{n}", dev=dev) for n in (1, 2, 3)] + [
        _leg(f"sensor.site_available_current_phase{n}",
             f"site_available_current_phase{n}", f"available_current_phase{n}",
             dev="zaptec:site") for n in (1, 2, 3)]


def _device(hass, prefix="zap"):
    return CurrentControlDevice(
        hass, device_id=prefix, name=prefix, phases=3,
        power_entity_id=f"sensor.{prefix}_total_charge_power",
        current_entity_id=f"number.{prefix}_charger_max_current")


class TestTheDeviceRead:

    def test_reads_its_own_phases(self, registry):
        _zaptec_registry(registry)
        hass = make_hass({f"sensor.zap_current_phase{n}": v
                          for n, v in ((1, 7.26), (2, 0.04), (3, 0.02))})
        assert _device(hass).phase_leg_currents() == [7.26, 0.04, 0.02]

    def test_a_dark_phase_is_no_reading(self, registry):
        _zaptec_registry(registry)
        hass = make_hass({"sensor.zap_current_phase1": 7.26,
                          "sensor.zap_current_phase2": "unavailable",
                          "sensor.zap_current_phase3": 0.02})
        assert _device(hass).phase_leg_currents() is None

    def test_no_phase_sensors(self, registry):
        registry.entries += [_leg("number.k_current", "k_current", dev="keba")]
        hass = make_hass({})
        dev = CurrentControlDevice(hass, device_id="k", name="k",
                                   current_entity_id="number.k_current")
        assert dev.phase_leg_currents() is None

    def test_each_charger_reads_its_own(self, registry):
        """Two boxes: each reads its own device, never the other's."""
        _zaptec_registry(registry, dev="zaptec:a", prefix="a")
        _zaptec_registry(registry, dev="zaptec:b", prefix="b")
        hass = make_hass({**{f"sensor.a_current_phase{n}": 7.0 for n in (1, 2, 3)},
                          "sensor.b_current_phase1": 16.0,
                          "sensor.b_current_phase2": 0.0,
                          "sensor.b_current_phase3": 0.0})
        assert _device(hass, "a").phase_leg_currents() == [7.0, 7.0, 7.0]
        assert _device(hass, "b").phase_leg_currents() == [16.0, 0.0, 0.0]

    def test_two_chargers_on_one_set_of_legs_read_none(self, registry):
        """Class 52: one set of phase sensors, two chargers (a two-socket
        box) — the reading is neither charger's."""
        _zaptec_registry(registry, dev="zaptec:a", prefix="a")
        registry.entries.append(_leg("number.b_charger_max_current",
                                     "b_charger_max_current", dev="zaptec:a"))
        hass = make_hass({f"sensor.a_current_phase{n}": 7.0 for n in (1, 2, 3)})
        a = _device(hass, "a")
        b = CurrentControlDevice(hass, device_id="b", name="b",
                                 current_entity_id="number.b_charger_max_current")
        assert a.phase_leg_currents() == [7.0, 7.0, 7.0]
        assert a.phase_leg_currents(others=[b]) is None
        assert b.phase_leg_currents(others=[a]) is None

    def test_the_service_device_is_asked_last(self, registry):
        """A service device can be a whole site (#1376): the charger's own
        entities' device comes first."""
        _zaptec_registry(registry)
        registry.entries += [_leg(f"sensor.site_l{n}", f"site_current_l{n}x",
                                  dev="zaptec:site") for n in (1, 2, 3)]
        registry.entries += [_leg(f"sensor.site_i_l{n}", f"s_i_l{n}",
                                  dev="zaptec:site") for n in (1, 2, 3)]
        hass = make_hass({f"sensor.zap_current_phase{n}": 4.0 for n in (1, 2, 3)})
        dev = _device(hass)
        dev.service_device_id = "zaptec:site"
        assert dev._own_device_ids(registry)[-1] == "zaptec:site"
        assert dev.phase_leg_currents() == [4.0, 4.0, 4.0]

    def test_a_sensor_turned_on_later_is_found(self, registry, monkeypatch):
        from custom_components.solar_energy_management.devices import base
        clock = [1000.0]
        monkeypatch.setattr(base.time, "monotonic", lambda: clock[0])
        hass = make_hass({f"sensor.zap_current_phase{n}": 5.0 for n in (1, 2, 3)})
        dev = _device(hass)
        assert dev.phase_leg_currents() is None        # integration not loaded
        _zaptec_registry(registry)
        clock[0] += dev.PHASE_LEGS_MISSING_S + 1
        assert dev.phase_leg_currents() == [5.0, 5.0, 5.0]

    def test_a_sensor_that_left_is_dropped(self, registry, monkeypatch):
        from custom_components.solar_energy_management.devices import base
        clock = [1000.0]
        monkeypatch.setattr(base.time, "monotonic", lambda: clock[0])
        _zaptec_registry(registry)
        hass = make_hass({f"sensor.zap_current_phase{n}": 5.0 for n in (1, 2, 3)})
        dev = _device(hass)
        assert dev.phase_leg_currents() == [5.0, 5.0, 5.0]
        registry.entries = [e for e in registry.entries
                            if e.entity_id != "sensor.zap_current_phase3"]
        clock[0] += dev.PHASE_LEGS_FOUND_S + 1
        assert dev.phase_leg_currents() is None


# ── the real cycle ───────────────────────────────────────────────────────

WIRED = {
    "solar_production_sensor": "sensor.solar",
    "grid_power_sensor": "sensor.grid",
    "battery_power_sensor": "sensor.batt",
    "battery_soc_sensor": "sensor.soc",
    "ev_power_sensor": "sensor.zap_total_charge_power",
    "battery_capacity_kwh": 15.0,
    "battery_reserve_soc": 20,
}


def _rig(mode, legs, ev_w):
    charger = {
        "id": "zap", "name": "zap", "ev_min_current": 6, "ev_max_current": 16,
        "ev_phases": 3, "ev_voltage": 230,
        "ev_current_control_entity": "number.zap_charger_max_current",
        "ev_connected_sensor": "binary_sensor.zap_connected",
        "ev_power_sensor": "sensor.zap_total_charge_power",
        "charge_mode": mode, "ev_target_type": "kwh", "daily_ev_target": 20,
    }
    states = {"sensor.solar": 3000, "sensor.grid": -500, "sensor.batt": 0,
              "sensor.soc": 60, "sensor.zap_total_charge_power": ev_w,
              "binary_sensor.zap_connected": "on",
              "number.zap_charger_max_current": 16}
    for n, v in enumerate(legs or (), start=1):
        states[f"sensor.zap_current_phase{n}"] = v
    rig = CycleRig(config=dict(WIRED), chargers=[charger], states=states)
    rig.coord.time_manager.is_night_mode = lambda: False
    return rig


@pytest.mark.asyncio
class TestTheCycle:

    async def test_the_report_another_system_charges(self, registry):
        """SEM Off, evcc charges 7.26 A on one phase: 1 phase, 7.3 A."""
        _zaptec_registry(registry)
        rig = _rig("off", (7.26, 0.04, 0.02), 1500)
        res = await rig.tick()
        assert res["charger_zap_commanded_current"] == 0
        assert res["charger_zap_measured_current"] == 7.3
        assert res["charger_zap_active_phases"] == 1

    async def test_twin_without_phase_sensors(self, registry):
        """The old answer, kept where nothing better is known."""
        rig = _rig("off", None, 1500)
        res = await rig.tick()
        assert res["charger_zap_measured_current"] is None
        assert res["charger_zap_active_phases"] is None

    async def test_three_phases_measured(self, registry):
        _zaptec_registry(registry)
        rig = _rig("off", (9.8, 9.9, 9.7), 6800)
        res = await rig.tick()
        assert res["charger_zap_measured_current"] == 9.9
        assert res["charger_zap_active_phases"] == 3

    async def test_lagging_phases_fall_back(self, registry):
        """The power says a charge flows, the phases still read idle: no
        measured amps, and no phase count from them."""
        _zaptec_registry(registry)
        rig = _rig("off", (0.04, 0.02, 0.0), 1500)
        res = await rig.tick()
        assert res["charger_zap_measured_current"] is None
        assert res["charger_zap_active_phases"] is None

    async def test_two_chargers_on_one_set_of_legs(self, registry):
        """The real loop hands each charger the others: one set of phase
        sensors on a two-socket box is neither socket's reading."""
        _zaptec_registry(registry)
        registry.entries.append(_leg("number.zap2_current", "zap2_current",
                                     dev="zaptec:chg1"))
        rig = _rig("off", (7.26, 0.04, 0.02), 1500)
        second = {"id": "zap2", "name": "zap2", "ev_phases": 3,
                  "ev_current_control_entity": "number.zap2_current",
                  "ev_connected_sensor": "binary_sensor.zap_connected",
                  "ev_power_sensor": "sensor.zap_total_charge_power",
                  "charge_mode": "off"}
        rig.coord.config["ev_chargers"].append(second)
        rig._add_charger(second)
        res = await rig.tick()
        assert res["charger_zap_measured_current"] is None
        assert res["charger_zap2_measured_current"] is None

    async def test_idle_box_reads_no_count(self, registry):
        _zaptec_registry(registry)
        rig = _rig("off", (0.04, 0.02, 0.0), 0)
        res = await rig.tick()
        assert res["charger_zap_measured_current"] == 0.0
        assert res["charger_zap_active_phases"] is None


def test_the_charging_state_sensor_publishes_it():
    from custom_components.solar_energy_management.sensor import SEMSolarSensor
    me = MagicMock()
    me.entity_description.key = "charging_state"
    me.coordinator.data = {
        "charger_zap_active_phases": 1,
        "charger_zap_measured_current": 7.3,
        "charger_kb_active_phases": None,
        "charger_kb_measured_current": None,
    }
    attrs = SEMSolarSensor._extra_state_attributes_base(me)
    assert attrs["per_charger_phases"]["zap"]["measured_current"] == 7.3
    assert attrs["per_charger_phases"]["zap"]["active_phases"] == 1
    assert attrs["per_charger_phases"]["kb"]["measured_current"] is None
