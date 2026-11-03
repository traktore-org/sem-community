"""#1306 — two batteries of different size are planned as what they are.

The fleet's size was one number: the setting, or the first capacity-looking
sensor in the house, which for two packs is one pack's size. Each per-pack
runtime then took the whole setting as its own. The night charge used a
fixed 9.5 kWh, because setup never wrote ``battery_usable_capacity_kwh``.

Now a pack's own capacity sensor is read on its device (the crawler's
``battery_capacity_spec`` role); a pack without one gets its share of the
setting, split by the packs' discharge ceilings; the fleet is the sum. One
pack keeps today's answer exactly.
"""
from __future__ import annotations

from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.consts.role_lexicon import role_for
from custom_components.solar_energy_management.coordinator import sensor_reader as sr
from custom_components.solar_energy_management.coordinator import ev_night_targets
from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
    BatteryChargeScheduler,
    SchedulerConfig,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryPower,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.ha_energy_reader import (
    EnergyDashboardConfig,
)
from custom_components.solar_energy_management.tests.test_1164_force_charge_stall import (
    _reader,
    _state,
)
from custom_components.solar_energy_management.tests.test_638_shadow_mode import (
    _fake_load,
    _fake_self,
    _scheduler,
)


# ── the crawler names the role from the key alone ─────────────────────

class TestTheCapacityRole:
    @pytest.mark.parametrize("key", [
        "rated_ess_capacity", "storage_rated_capacity", "battery_capacity",
        "usable_capacity", "nominal_capacity_kwh", "total_capacity",
    ])
    def test_a_nameplate_key_is_the_spec(self, key):
        assert role_for("sensor", key) == "battery_capacity_spec"

    @pytest.mark.parametrize("key", [
        "state_of_capacity", "remaining_capacity", "capacity_percent",
        "capacity_today",
    ])
    def test_a_level_or_a_counter_is_not(self, key):
        assert role_for("sensor", key) != "battery_capacity_spec"


# ── the reader finds each pack's own size on its device ──────────────

def _registry(devices):
    """{entity_id: (device_id, [(sibling_id, translation_key), ...])}"""
    reg = MagicMock()

    def _get(eid):
        dev = devices.get(eid)
        return NS(device_id=dev[0]) if dev else None
    reg.async_get = _get

    def _for_device(_reg, device_id):
        for _eid, (dev, sibs) in devices.items():
            if dev == device_id:
                return [NS(domain=s.split(".")[0], entity_id=s, translation_key=tk)
                        for s, tk in sibs]
        return []
    return reg, _for_device


def _fleet(monkeypatch, states, devices):
    r = _reader(states, {})
    r.hass.states.async_all = MagicMock(return_value=[])
    r._sign_vote_warmup = 0
    r.set_energy_dashboard_config(EnergyDashboardConfig(
        grid_power_from="sensor.imp", grid_power_to="sensor.exp",
        battery_power="sensor.b1", battery_power_list=["sensor.b1", "sensor.b2"],
        has_grid=True, has_battery=True))
    r._soc_entity_by_power = {"sensor.b1": "sensor.soc1", "sensor.b2": "sensor.soc2"}
    reg, for_device = _registry(devices)
    monkeypatch.setattr(sr.er, "async_get", lambda hass: reg)
    monkeypatch.setattr(sr.er, "async_entries_for_device", for_device)
    return r


def _states(cap1="10000", unit1="Wh", cap2="5", unit2="kWh"):
    st = {"sensor.b1": _state(0, "W"), "sensor.b2": _state(0, "W"),
          "sensor.imp": _state(0, "W"), "sensor.exp": _state(0, "W"),
          "sensor.soc1": _state(20, "%"), "sensor.soc2": _state(80, "%"),
          "sensor.b1_rated_capacity": _state(cap1, unit1),
          "sensor.b2_battery_capacity": _state(cap2, unit2)}
    return st


DEVICES = {
    "sensor.b1": ("dev1", [("sensor.b1", None), ("sensor.soc1", None),
                           ("sensor.b1_rated_capacity", "rated_ess_capacity")]),
    "sensor.b2": ("dev2", [("sensor.b2", None), ("sensor.soc2", None),
                           ("sensor.b2_battery_capacity", None)]),
}


class TestTheReaderReadsEachPack:
    def test_each_pack_carries_its_own_kwh(self, monkeypatch):
        r = _fleet(monkeypatch, _states(), DEVICES)
        p = r.read_power()
        assert p.batteries["b1"].capacity_kwh == 10.0
        assert p.batteries["b2"].capacity_kwh == 5.0

    def test_the_fleet_soc_is_weighted_by_those_sizes(self, monkeypatch):
        r = _fleet(monkeypatch, _states(), DEVICES)
        p = r.read_power()
        # 10 kWh at 20 % + 5 kWh at 80 % = 6 of 15 kWh = 40 %, not the mean 50
        assert p.fleet_battery_soc == pytest.approx(40.0)

    def test_a_soc_percentage_named_capacity_is_not_a_size(self, monkeypatch):
        states = _states(cap2="80", unit2="%")
        r = _fleet(monkeypatch, states, DEVICES)
        p = r.read_power()
        assert p.batteries["b2"].capacity_kwh == 0.0

    def test_a_pack_without_a_sensor_reads_zero_and_the_answer_sticks(self, monkeypatch):
        devices = {"sensor.b1": DEVICES["sensor.b1"],
                   "sensor.b2": ("dev2", [("sensor.b2", None)])}
        r = _fleet(monkeypatch, _states(), devices)
        assert r.read_power().batteries["b2"].capacity_kwh == 0.0
        assert r._capacity_entity_by_power["sensor.b2"] is None
        assert r._capacity_entity_by_power["sensor.b1"] == "sensor.b1_rated_capacity"

    def test_the_fleet_detect_still_takes_the_first_sensor_in_the_house(self, monkeypatch):
        # unchanged on purpose: one pack, the setting empty, this is its size
        r = _fleet(monkeypatch, _states(), DEVICES)
        r.hass.states.async_all = MagicMock(return_value=[
            r.hass.states.get("sensor.b2_battery_capacity")])
        r.hass.states.get("sensor.b2_battery_capacity").entity_id = "sensor.b2_battery_capacity"
        r.hass.states.get("sensor.b2_battery_capacity").attributes["friendly_name"] = "cap"
        monkeypatch.setattr(sr, "is_sem_entity", lambda *a, **k: False)
        assert r.auto_detect_battery_capacity_kwh() == 5.0


# ── the coordinator's fleet and per-pack numbers ─────────────────────

def _coord(total=15.0, adapters=None):
    c = NS(battery_capacity_kwh=total, _battery_adapters=adapters)
    c.fleet_battery_capacity_kwh = lambda power=None: SEMCoordinator.fleet_battery_capacity_kwh(c, power)
    c._unit_capacity_kwh = lambda bid, power=None: SEMCoordinator._unit_capacity_kwh(c, bid, power)
    return c


def _two(cap1, cap2, soc1=20.0, soc2=80.0):
    return NS(battery_soc=40.0, batteries={
        "b1": BatteryPower(battery_id="b1", power_w=0.0, soc_pct=soc1, capacity_kwh=cap1),
        "b2": BatteryPower(battery_id="b2", power_w=0.0, soc_pct=soc2, capacity_kwh=cap2),
    })


class TestFleetAndShares:
    def test_two_declared_packs_sum(self):
        assert _coord().fleet_battery_capacity_kwh(_two(10.0, 5.0)) == 15.0

    def test_one_pack_is_the_setting_as_before(self):
        one = NS(batteries={"b1": BatteryPower(battery_id="b1", power_w=0.0,
                                               soc_pct=50.0, capacity_kwh=7.0)})
        assert _coord(total=12.0).fleet_battery_capacity_kwh(one) == 12.0
        assert _coord(total=12.0).fleet_battery_capacity_kwh(NS(batteries={})) == 12.0
        assert _coord(total=12.0).fleet_battery_capacity_kwh(None) == 12.0

    def test_undeclared_packs_share_the_setting_by_their_ceilings(self):
        c = _coord(total=15.0, adapters={"b1": NS(_max_discharge_w=5000.0),
                                         "b2": NS(_max_discharge_w=2500.0)})
        p = _two(0.0, 0.0)
        assert c._unit_capacity_kwh("b1", p) == 10.0
        assert c._unit_capacity_kwh("b2", p) == 5.0
        assert c.fleet_battery_capacity_kwh(p) == 15.0

    def test_one_declared_pack_leaves_the_rest_to_the_other(self):
        c = _coord(total=15.0, adapters={"b1": NS(_max_discharge_w=5000.0),
                                         "b2": NS(_max_discharge_w=5000.0)})
        p = _two(10.0, 0.0)
        assert c._unit_capacity_kwh("b1", p) == 10.0
        assert c._unit_capacity_kwh("b2", p) == 5.0

    def test_no_ceilings_means_equal_shares(self):
        c = _coord(total=16.0, adapters=None)
        p = _two(0.0, 0.0)
        assert c._unit_capacity_kwh("b1", p) == 8.0
        assert c._unit_capacity_kwh("b2", p) == 8.0

    def test_declared_above_the_setting_never_goes_negative(self):
        c = _coord(total=8.0, adapters=None)
        p = _two(10.0, 0.0)
        assert c._unit_capacity_kwh("b2", p) == 0.0
        assert c.fleet_battery_capacity_kwh(p) == 10.0


# ── the night charge is sized on the fleet, not on 9.5 kWh ───────────

class TestTheSchedulerIsToldTheFleet:
    def test_the_usable_share_follows_the_nameplate(self):
        s = BatteryChargeScheduler(MagicMock(), SchedulerConfig())
        s.set_fleet_capacity_kwh(15.0)
        assert s._config.battery_capacity_kwh == 15.0
        assert s._config.battery_usable_capacity_kwh == pytest.approx(14.25)

    def test_the_default_ten_kwh_pack_is_unchanged(self):
        s = BatteryChargeScheduler(MagicMock(), SchedulerConfig())
        s.set_fleet_capacity_kwh(10.0)
        assert s._config.battery_usable_capacity_kwh == pytest.approx(9.5)

    def test_a_set_usable_share_is_kept_as_given(self):
        s = BatteryChargeScheduler(MagicMock(), SchedulerConfig.from_config(
            {"battery_capacity_kwh": 10.0, "battery_usable_capacity_kwh": 8.0}))
        s.set_fleet_capacity_kwh(15.0)
        assert s._config.battery_usable_capacity_kwh == pytest.approx(8.0)

    def test_setup_saved_capacity_without_a_usable_share_follows_it(self):
        # the setup flow saves a capacity for every install and never the
        # usable share: a 14 kWh pack planned on 9.5 kWh before
        cfg = SchedulerConfig.from_config({"battery_capacity_kwh": 14.0})
        assert cfg.battery_usable_capacity_kwh == pytest.approx(13.3)
        assert cfg.usable_capacity_explicit is False
        s = BatteryChargeScheduler(MagicMock(), cfg)
        s.set_fleet_capacity_kwh(14.0)
        assert s._config.battery_usable_capacity_kwh == pytest.approx(13.3)

    def test_no_capacity_in_config_keeps_the_old_default(self):
        cfg = SchedulerConfig.from_config({})
        assert cfg.battery_capacity_kwh == 10.0
        assert cfg.battery_usable_capacity_kwh == pytest.approx(9.5)

    def test_zero_is_ignored(self):
        s = BatteryChargeScheduler(MagicMock(), SchedulerConfig())
        s.set_fleet_capacity_kwh(0.0)
        assert s._config.battery_usable_capacity_kwh == pytest.approx(9.5)


# ── the plan walks with the fleet's kWh ──────────────────────────────

@pytest.fixture
def freeze_targets(monkeypatch):
    monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                        lambda coord, energy: {"ev_charger": 6.0})


def _plan_self():
    fake = _fake_self(devices=[_fake_load()])
    fake.fleet_battery_capacity_kwh = (
        lambda power=None: SEMCoordinator.fleet_battery_capacity_kwh(fake, power))
    fake._unit_capacity_kwh = (
        lambda bid, power=None: SEMCoordinator._unit_capacity_kwh(fake, bid, power))
    fake._battery_adapters = None
    return fake


def _fleet_reading(cap1, cap2):
    p = _two(cap1, cap2)
    p.battery_soc_partial = False
    p.battery_soc_units_read = 2
    p.battery_soc_units_expected = 2
    p.battery_soc_units_configured = 2
    return p


class TestThePlan:
    def test_two_packs_start_the_night_with_their_real_kwh(self, freeze_targets):
        fake = _plan_self()            # the setting says 10 (one pack's size)
        SEMCoordinator._shadow_energy_plan(
            fake, _scheduler(), energy=MagicMock(), power=_fleet_reading(10.0, 5.0))
        plan = fake._energy_plan_shadow
        assert plan["has_battery"] is True
        # 40 % of 15 kWh, not 40 % of 10 (the first sensor) nor of 20 (10 each)
        assert plan["slots"][0]["soc_kwh"] == pytest.approx(6.0, abs=0.05)

    def test_one_pack_is_byte_identical_to_before(self, freeze_targets):
        before = _fake_self(devices=[_fake_load()])   # no fleet accessor: the old path
        SEMCoordinator._shadow_energy_plan(
            before, _scheduler(), energy=MagicMock(), power=NS(battery_soc=80.0))
        after = _plan_self()
        SEMCoordinator._shadow_energy_plan(
            after, _scheduler(), energy=MagicMock(), power=NS(battery_soc=80.0))
        a, b = dict(after._energy_plan_shadow), dict(before._energy_plan_shadow)
        a.pop("computed_at"), b.pop("computed_at")   # the clock, not the plan
        assert a == b
