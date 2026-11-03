"""#1300 — the grid-sign brand seed waits for an answer.

A meter of a known brand whose integration loads after SEM: on the first
cycle the sensor has a state but no registry row and no entry in HA's
source map. The seed ran once, learned nothing, and marked itself done. The
meter then read import as export until the solar swings had voted; a wrong
sign starts loads on grid power.

Now the seed marks itself done only when it has answered — a known brand,
an unknown one — and asks again next cycle when no integration owns the
sensor yet, for as long as the dark grace. The battery seed had the same
shape and gets the same rule.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from homeassistant.helpers.entity import entity_sources

from custom_components.solar_energy_management.consts.core import (
    SENSOR_DARK_READ_GRACE_S,
)
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)

from .test_1172_declared_power_key import _W, _device, _entity

GRID = "sensor.fronius_grid_power"       # a brand with a known sign, no model gate
SOLAR = "sensor.fronius_pv_power"
_ER = "custom_components.solar_energy_management.coordinator.sensor_reader.er.async_get"


def _reader(hass):
    hass.states.async_set(GRID, "976", _W)          # +976 = import (HA convention)
    hass.states.async_set(SOLAR, "100", _W)
    return SensorReader(hass, {
        "update_interval": 10,
        "grid_power_sensor": GRID,
        "solar_production_sensor": SOLAR,
    })


def _integration_loads(hass, platform="fronius"):
    """The meter's platform adds the entity: HA writes its source map. A
    YAML meter has no registry row, so the map is the only owner record."""
    entity_sources(hass)[GRID] = {"domain": platform, "custom_component": False}


def _registered_meter(hass, platform="fronius"):
    entry, dev = _device(hass, platform=platform, model_id="Symo", name="meter")
    _entity(hass, entry, dev, GRID, "grid_power", platform=platform,
            device_class="power")


class TestTheGridSeedWaits:
    async def test_the_seed_applies_on_the_cycle_the_integration_appears(self, hass):
        reader = _reader(hass)
        first = reader.read_power()
        assert first.grid_export_power == pytest.approx(976)   # nothing known yet
        assert reader._brand_seed_done is False
        _integration_loads(hass)
        second = reader.read_power()
        assert reader._grid_sign_inverted is True
        assert reader._brand_seed_done is True
        assert second.grid_import_power == pytest.approx(976)
        assert second.grid_export_power == 0

    async def test_a_known_meter_present_from_the_start_is_seeded_at_once(self, hass):
        _registered_meter(hass)
        reader = _reader(hass)
        assert reader.read_power().grid_import_power == pytest.approx(976)

    async def test_an_unknown_brand_is_an_answer_and_the_seed_is_done(self, hass):
        reader = _reader(hass)
        _integration_loads(hass, platform="template")
        reader.read_power()
        assert reader._brand_seed_done is True
        assert reader._grid_sign_inverted is False

    async def test_after_the_grace_the_seed_gives_up(self, hass, monkeypatch):
        reader = _reader(hass)
        clock = [1000.0]
        monkeypatch.setattr(reader, "_now_monotonic", lambda: clock[0])
        reader.read_power()
        clock[0] += SENSOR_DARK_READ_GRACE_S + 1
        reader.read_power()
        assert reader._brand_seed_done is True
        _integration_loads(hass)
        reader.read_power()
        assert reader._grid_sign_inverted is False     # left to the detectors

    async def test_a_reset_asks_again(self, hass):
        reader = _reader(hass)
        _integration_loads(hass, platform="template")
        reader.read_power()
        reader.reset_sign_state()
        assert reader._brand_seed_done is False
        assert reader._seed_first_miss == {}


class TestTheBatterySeedWaits:
    def _reader(self):
        hass = MagicMock()
        hass.states = MagicMock()
        return SensorReader(hass, {})

    def _registry(self, platform):
        reg = MagicMock()
        if platform is None:
            reg.async_get.return_value = None
        else:
            reg.async_get.return_value = MagicMock(platform=platform,
                                                   config_entry_id="c1")
        return reg

    def test_no_owner_yet_is_not_an_answer(self):
        r = self._reader()
        with patch(_ER, return_value=self._registry(None)):
            r._seed_battery_sign_from_platform("b1", "sensor.goodwe_battery")
        assert r._battery_brand_seed_done.get("b1", False) is False
        with patch(_ER, return_value=self._registry("goodwe")):
            r._seed_battery_sign_from_platform("b1", "sensor.goodwe_battery")
        assert r._battery_sign_inverted.get("b1") is True
        assert r._battery_brand_seed_done["b1"] is True

    def test_an_unknown_brand_is_done(self):
        r = self._reader()
        with patch(_ER, return_value=self._registry("template")):
            r._seed_battery_sign_from_platform("b1", "sensor.x")
        assert r._battery_brand_seed_done["b1"] is True

    def test_no_power_entity_is_done(self):
        r = self._reader()
        r._seed_battery_sign_from_platform("b1", None)
        assert r._battery_brand_seed_done["b1"] is True

    def test_after_the_grace_the_seed_gives_up(self, monkeypatch):
        r = self._reader()
        clock = [1000.0]
        monkeypatch.setattr(r, "_now_monotonic", lambda: clock[0])
        with patch(_ER, return_value=self._registry(None)):
            r._seed_battery_sign_from_platform("b1", "sensor.goodwe_battery")
            clock[0] += SENSOR_DARK_READ_GRACE_S + 1
            r._seed_battery_sign_from_platform("b1", "sensor.goodwe_battery")
        assert r._battery_brand_seed_done["b1"] is True
        assert "b1" not in r._battery_sign_inverted
