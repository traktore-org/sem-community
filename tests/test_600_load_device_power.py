"""#600 — load device live power from an energy counter: observed_power_w
routing (power sensor wins → energy-derived fallback → None) + factory
autodetect of a companion power sensor."""

from unittest.mock import MagicMock

import custom_components.solar_energy_management.devices.base as base_mod
from custom_components.solar_energy_management.devices.base import (
    SwitchDevice,
    surplus_device_from_spec,
)


def _hass(states):
    h = MagicMock()
    h.states.get = lambda eid: states.get(eid)
    return h


def _st(value):
    s = MagicMock()
    s.state = str(value)
    s.attributes = {}
    return s


def test_observed_power_prefers_power_sensor():
    h = _hass({"sensor.hp_power": _st(1450)})
    d = SwitchDevice(h, "hp", "Heat Pump", 1000, power_entity_id="sensor.hp_power")
    d._status.is_active = True
    assert d.observed_power_w() == 1450.0


def test_observed_power_sensor_wins_over_energy():
    h = _hass({"sensor.hp_power": _st(1450), "sensor.hp_energy": _st(100.0)})
    d = SwitchDevice(
        h, "hp", "Heat Pump", 1000,
        power_entity_id="sensor.hp_power", energy_entity_id="sensor.hp_energy",
    )
    assert d.observed_power_w() == 1450.0


def test_observed_power_energy_fallback_first_call_is_baseline_zero():
    # No power sensor → derive from the energy counter. First reading sets the
    # baseline → 0 W (the deriver's math is covered by test_600_energy_rate_deriver).
    h = _hass({"sensor.hp_energy": _st(100.0)})
    d = SwitchDevice(h, "hp", "Heat Pump", 1000, energy_entity_id="sensor.hp_energy")
    assert d.observed_power_w() == 0.0
    assert d._energy_deriver is not None  # lazily created


def test_observed_power_none_when_no_signal():
    d = SwitchDevice(_hass({}), "hp", "Heat Pump", 1000)
    assert d.observed_power_w() is None


def test_observed_power_unavailable_power_falls_to_energy():
    h = _hass({"sensor.hp_power": _st("unavailable"), "sensor.hp_energy": _st(5.0)})
    d = SwitchDevice(
        h, "hp", "Heat Pump", 1000,
        power_entity_id="sensor.hp_power", energy_entity_id="sensor.hp_energy",
    )
    assert d.observed_power_w() == 0.0  # energy baseline, not None


# ── factory: autodetect a companion power sensor when energy-only ──
def test_factory_autodetects_companion_power_sensor(monkeypatch):
    def fake_find(hass, energy_entity, rule):
        return "sensor.hp_power" if energy_entity == "sensor.hp_energy" else None

    import custom_components.solar_energy_management.ha_energy_reader as her
    monkeypatch.setattr(her, "_find_power_sensor_on_device", fake_find)

    dev = surplus_device_from_spec(
        MagicMock(), "hp", {"name": "HP", "energy_entity_id": "sensor.hp_energy"},
    )
    # autodetect promoted the companion power sensor to power_entity_id
    assert dev.power_entity_id == "sensor.hp_power"
    assert dev.energy_entity_id == "sensor.hp_energy"


def test_factory_keeps_energy_when_no_companion(monkeypatch):
    import custom_components.solar_energy_management.ha_energy_reader as her
    monkeypatch.setattr(her, "_find_power_sensor_on_device", lambda *a, **k: None)

    dev = surplus_device_from_spec(
        MagicMock(), "hw", {"name": "HW", "energy_entity_id": "sensor.dhw_energy"},
    )
    assert dev.power_entity_id is None
    assert dev.energy_entity_id == "sensor.dhw_energy"  # deriver fallback path
