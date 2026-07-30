"""#692-#695 — the four bugs the #638 scenario battery surfaced in SHIPPED code.

One class ties #692 and #693 together: a config value enforced somewhere that
was never READ from where installs actually write it. #694 and #695 are the
battery-SOC honesty pair: never fabricate a value (0.0 for a warming unit),
never adopt someone else's (an EV charger's car SOC as the house battery).

#692  LoadManagementCoordinator read entry.options only; the install flow
      writes entry.data → every never-re-saved install ran the 5.0 kW default.
#693  SchedulerConfig read ``peak_limit_w`` — a key nothing writes → the
      night schedule's peak cap was dead (0 = no limit) on every install.
#694  Per-battery SOC published 0.0 while the unit's sensor was warming or
      undetected — indistinguishable from an empty battery.
#695  The #529 global SOC scan's exclusion list did not know ``charger`` /
      ``wallbox`` — a wallbox exposing the CAR's SOC could be adopted as the
      house battery (#250 class).
"""
from __future__ import annotations

from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.features.load_management import (
    LoadManagementCoordinator,
)
from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
    SchedulerConfig,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryPower,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
)


# ──────────────────────────────────────────────────────────────────
# #692 — the load manager must read the merged entry view
# ──────────────────────────────────────────────────────────────────

def _lm(data=None, options=None):
    """A LoadManagementCoordinator on a stub entry, discovery/store mocked."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = data if data is not None else {}
    entry.options = options if options is not None else {}
    with patch(
        "custom_components.solar_energy_management.features.load_management.LoadDeviceDiscovery"
    ), patch(
        "custom_components.solar_energy_management.features.load_management.Store"
    ):
        return LoadManagementCoordinator(MagicMock(), entry)


def test_692_install_flow_data_is_enough():
    """The exact live shape: data carries the configured limit, options is
    empty (the install has never been re-saved through the options flow).
    Before the fix this enforced the 5.0 kW DEFAULT and silently ignored
    the user's 6.0."""
    lm = _lm(data={"target_peak_limit": 6.0, "warning_peak_level": 5.5,
                   "emergency_peak_level": 7.0, "peak_hysteresis": 0.4,
                   "load_management_enabled": True},
             options={})
    assert lm._target_peak_limit == 6.0
    assert lm._warning_level == 5.5
    assert lm._emergency_level == 7.0
    assert lm._hysteresis == 0.4
    assert lm._enabled is True


def test_692_options_still_win_over_data():
    """An options-flow re-save (or update_target_peak_limit) writes options —
    the newer surface must keep winning."""
    lm = _lm(data={"target_peak_limit": 6.0},
             options={"target_peak_limit": 8.0})
    assert lm._target_peak_limit == 8.0


def test_692_mappingproxy_surfaces_read_fine():
    """HA's real entry surfaces are MappingProxy, not dict — the merge must
    not depend on dict identity."""
    lm = _lm(data=MappingProxyType({"target_peak_limit": 6.5}),
             options=MappingProxyType({}))
    assert lm._target_peak_limit == 6.5


def test_692_a_stub_entry_without_mappings_falls_back_to_defaults():
    """A non-mapping surface (bare MagicMock entry) contributes nothing —
    construction must not raise, defaults apply."""
    entry = MagicMock()          # .data/.options are auto-MagicMocks
    entry.entry_id = "test_entry"
    with patch(
        "custom_components.solar_energy_management.features.load_management.LoadDeviceDiscovery"
    ), patch(
        "custom_components.solar_energy_management.features.load_management.Store"
    ):
        lm = LoadManagementCoordinator(MagicMock(), entry)
    assert lm._target_peak_limit == 5.0     # DEFAULT_TARGET_PEAK_LIMIT


# ──────────────────────────────────────────────────────────────────
# #693 — the scheduler cap must come from a key installs carry
# ──────────────────────────────────────────────────────────────────

def test_693_target_peak_limit_kw_becomes_the_cap_in_w():
    cfg = SchedulerConfig.from_config({"target_peak_limit": 6.0})
    assert cfg.peak_limit_w == 6000.0


def test_693_the_dead_key_is_ignored():
    """``peak_limit_w`` is written by nothing — a lingering value (tests,
    hand-edited storage) must not beat the real key."""
    cfg = SchedulerConfig.from_config({
        "target_peak_limit": 6.0,
        "peak_limit_w": 9999.0,
    })
    assert cfg.peak_limit_w == 6000.0


def test_693_no_key_means_no_cap_not_a_crash():
    """An entry without target_peak_limit (pre-flow shapes) keeps today's
    behaviour: 0 = no limit."""
    cfg = SchedulerConfig.from_config({})
    assert cfg.peak_limit_w == 0.0


# ──────────────────────────────────────────────────────────────────
# #694 — an unresolved per-battery SOC is None, never 0.0
# ──────────────────────────────────────────────────────────────────

def test_694_unresolved_soc_defaults_to_none():
    bp = BatteryPower(battery_id="b1")
    assert bp.soc_pct is None


def test_694_fleet_average_excludes_the_warming_unit():
    """The live shape: b1's modbus SOC warming after a restart, b2 at 65%.
    Averaging a fabricated 0 in would read the fleet at ~32% — the fleet is
    b2's 65% until b1 resolves (the #638 partial-fleet label says so)."""
    p = PowerReadings()
    p.batteries = {
        "b1": BatteryPower(battery_id="b1", soc_pct=None, capacity_kwh=10.0),
        "b2": BatteryPower(battery_id="b2", soc_pct=65.0, capacity_kwh=10.0),
    }
    assert p.fleet_battery_soc == 65.0


def test_694_fleet_average_weighted_over_resolved_units_only():
    p = PowerReadings()
    p.batteries = {
        "b1": BatteryPower(battery_id="b1", soc_pct=80.0, capacity_kwh=5.0),
        "b2": BatteryPower(battery_id="b2", soc_pct=60.0, capacity_kwh=15.0),
        "b3": BatteryPower(battery_id="b3", soc_pct=None, capacity_kwh=10.0),
    }
    # (80*5 + 60*15) / 20 — b3 contributes neither SOC nor capacity weight.
    assert p.fleet_battery_soc == pytest.approx(65.0)


def test_694_nothing_resolved_falls_back_to_the_scalar():
    p = PowerReadings()
    p.battery_soc = 42.0
    p.batteries = {
        "b1": BatteryPower(battery_id="b1", soc_pct=None),
        "b2": BatteryPower(battery_id="b2", soc_pct=None),
    }
    assert p.fleet_battery_soc == 42.0


def test_694_to_dict_publishes_none_not_zero(monkeypatch):
    """The entity must show unknown while the unit warms — 0.0 is a claim
    ("this battery is empty") the reader cannot back."""
    from custom_components.solar_energy_management.coordinator import types as t
    data = t.SEMData()
    data.power.batteries = {
        "b1": BatteryPower(battery_id="b1", soc_pct=None, power_w=0.0),
        "b2": BatteryPower(battery_id="b2", soc_pct=65.0, power_w=-200.0),
    }
    d = data.to_dict()
    assert d["battery_b1_soc"] is None
    assert d["battery_b2_soc"] == 65.0


# ──────────────────────────────────────────────────────────────────
# #695 — the global scan must not adopt a charger's car SOC
# ──────────────────────────────────────────────────────────────────

def _scan_reader(states):
    """A SensorReader shell driving ONLY the strategy-3 global scan:
    no cache, prefix and device-registry strategies come up empty."""
    from custom_components.solar_energy_management.coordinator.sensor_reader import (
        SensorReader,
    )
    reader = SensorReader.__new__(SensorReader)
    reader._soc_entity_by_power = {}
    hass = MagicMock()
    hass.states.get = lambda eid: states.get(eid)
    hass.states.async_all = lambda domain: [
        s for eid, s in states.items() if eid.startswith(f"{domain}.")
    ]
    reader.hass = hass
    return reader


def _state(eid, value, unit="%", device_class="battery"):
    s = MagicMock()
    s.entity_id = eid
    s.state = value
    s.attributes = {"unit_of_measurement": unit, "device_class": device_class}
    return s


def test_695_a_chargers_car_soc_is_not_the_house_battery(monkeypatch):
    """The rig shape: the only %-battery sensor in the system is an EV
    charger's vehicle SOC. Before the fix the guarded scan adopted it
    (exactly one candidate). It must return None instead."""
    reader = _scan_reader({
        "sensor.mock_charger_2_soc": _state("sensor.mock_charger_2_soc", "55"),
    })
    reader._try_soc_candidates = lambda p, k: None    # strategy 1 comes up dry
    with patch(
        "custom_components.solar_energy_management.coordinator.sensor_reader.er"
    ) as er_mod:
        er_mod.async_get.side_effect = RuntimeError("no registry")
        got = reader._auto_detect_battery_soc("sensor.some_battery_power")
    assert got is None


def test_695_a_wallbox_soc_is_excluded_too():
    reader = _scan_reader({
        "sensor.wallbox_soc": _state("sensor.wallbox_soc", "80"),
        "sensor.home_battery_state_of_charge": _state(
            "sensor.home_battery_state_of_charge", "71"),
    })
    reader._try_soc_candidates = lambda p, k: None    # strategy 1 comes up dry
    with patch(
        "custom_components.solar_energy_management.coordinator.sensor_reader.er"
    ) as er_mod:
        er_mod.async_get.side_effect = RuntimeError("no registry")
        got = reader._auto_detect_battery_soc("sensor.some_battery_power")
    # The wallbox is excluded, the home battery is the single unambiguous
    # candidate — the scan still WORKS, it just stopped guessing wrong.
    assert got == "sensor.home_battery_state_of_charge"
