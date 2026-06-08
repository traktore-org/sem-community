"""#420 — telemetry surface for HotWaterController.

Locks the ``*_path`` strings each decision branch publishes via
``to_dict``. Mirrors the #359 ``classifier_path`` / #416
``dampening_path`` precedents: one enum string per branch so users
can self-diagnose without us reading the debug log.

The audit's structural finding was: ``HotWaterController`` has
36 decision branches across 374 LOC, most with no user-visible
signal. The biggest silent-failure surface is
``is_temperature_safe()`` returning ``True`` when the temperature
sensor is unavailable — SEM keeps activating the heater forever,
relying only on the device's internal thermostat. Telemetry attribute
makes that state visible.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.devices.hot_water_controller import (
    DEFAULT_LEGIONELLA_INTERVAL_HOURS,
    DEFAULT_LEGIONELLA_TARGET,
    DEFAULT_SOLAR_TARGET_TEMP,
    HotWaterController,
)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────


@pytest.fixture
def mock_hass():
    h = MagicMock()
    h.services.async_call = AsyncMock()
    h.states = MagicMock()
    return h


def _state(state_val, attributes=None):
    s = MagicMock()
    s.state = str(state_val)
    s.attributes = attributes or {}
    return s


def _make(mock_hass, **kwargs):
    """Default HotWaterController set up for switch + sensor pattern."""
    return HotWaterController(
        hass=mock_hass,
        entity_id=kwargs.pop("entity_id", "switch.boiler"),
        temperature_entity_id=kwargs.pop("temperature_entity_id", "sensor.tank_temp"),
        **kwargs,
    )


# ──────────────────────────────────────────────
# temperature_reading_path
# ──────────────────────────────────────────────


def test_temperature_reading_path_entity_attribute(mock_hass):
    """water_heater domain — temp pulled from entity.attributes."""
    mock_hass.states.get = MagicMock(
        return_value=_state("on", {"current_temperature": 48.0})
    )
    h = HotWaterController(
        hass=mock_hass, entity_id="water_heater.boiler",
    )
    assert h.get_current_temperature() == 48.0
    assert h.to_dict()["temperature_reading_path"] == "entity_attribute"


def test_temperature_reading_path_separate_sensor(mock_hass):
    """switch domain — temp pulled from separate sensor entity."""
    mock_hass.states.get = MagicMock(return_value=_state("46.5"))
    h = _make(mock_hass)
    assert h.get_current_temperature() == 46.5
    assert h.to_dict()["temperature_reading_path"] == "separate_sensor"


def test_temperature_reading_path_separate_sensor_unavailable(mock_hass):
    """sensor reports 'unavailable' — path captures the breakage."""
    mock_hass.states.get = MagicMock(return_value=_state("unavailable"))
    h = _make(mock_hass)
    assert h.get_current_temperature() is None
    assert h.to_dict()["temperature_reading_path"] == "separate_sensor_unavailable"


def test_temperature_reading_path_separate_sensor_invalid(mock_hass):
    """sensor exists with a non-numeric, non-sentinel value."""
    mock_hass.states.get = MagicMock(return_value=_state("hot"))
    h = _make(mock_hass)
    assert h.get_current_temperature() is None
    assert h.to_dict()["temperature_reading_path"] == "separate_sensor_invalid"


def test_temperature_reading_path_no_source_configured(mock_hass):
    """No entity AND no separate sensor — operating 'blind'."""
    h = HotWaterController(hass=mock_hass, entity_id=None, temperature_entity_id=None)
    assert h.get_current_temperature() is None
    assert h.to_dict()["temperature_reading_path"] == "no_source_configured"


def test_temperature_reading_path_no_source_configured_on_every_call(mock_hass):
    """Reviewer finding — the no_source_configured label must update on
    EVERY call, not just the first. Previously a stale prior label could
    persist if the path had ever fired before.
    """
    h = HotWaterController(hass=mock_hass, entity_id=None, temperature_entity_id=None)
    # Pre-stage a stale label as if a previous call had set it
    h._last_temperature_reading_path = "separate_sensor_invalid"
    assert h.get_current_temperature() is None
    assert h.to_dict()["temperature_reading_path"] == "no_source_configured"


def test_temperature_reading_path_entity_attribute_invalid_no_fallback(mock_hass):
    """water_heater entity has a non-numeric current_temperature AND no
    separate sensor configured → path lands on entity_attribute_invalid.
    """
    mock_hass.states.get = MagicMock(
        return_value=_state("on", {"current_temperature": "warm"})
    )
    h = HotWaterController(
        hass=mock_hass, entity_id="water_heater.boiler",
        temperature_entity_id=None,
    )
    assert h.get_current_temperature() is None
    assert h.to_dict()["temperature_reading_path"] == "entity_attribute_invalid"


# ──────────────────────────────────────────────
# temperature_safety_path
# ──────────────────────────────────────────────


def test_temperature_safety_path_configured_sensor_broken(mock_hass):
    """#420 fix (v1.7.2): configured sensor reports unavailable → FAIL
    SAFE (was the silent-failure surface that motivated the audit; the
    pre-fix behaviour was ``no_sensor_assume_safe → True``)."""
    mock_hass.states.get = MagicMock(return_value=_state("unavailable"))
    h = _make(mock_hass)  # _make sets temperature_entity_id, so sensor IS configured
    assert h.is_temperature_safe() is False, (
        "configured-but-broken sensor must fail safe — pre-fix this "
        "let SEM activate the heater forever with no temperature feedback"
    )
    assert h.to_dict()["temperature_safety_path"] == "configured_sensor_broken"


def test_temperature_safety_path_no_sensor_configured(mock_hass):
    """When the user genuinely never configured a temperature sensor,
    rely on the device's internal thermostat — return True. Distinct
    from the configured-but-broken case above."""
    mock_hass.states.get = MagicMock(return_value=None)
    h = HotWaterController(
        hass=mock_hass, entity_id="switch.boiler",
        temperature_entity_id=None,  # explicitly no sensor configured
    )
    assert h.is_temperature_safe() is True
    assert h.to_dict()["temperature_safety_path"] == "no_sensor_configured"


def test_temperature_safety_path_normal_below_solar_target(mock_hass):
    mock_hass.states.get = MagicMock(return_value=_state("45.0"))
    h = _make(mock_hass, solar_target_temp=50.0)
    assert h.is_temperature_safe() is True
    assert h.to_dict()["temperature_safety_path"] == "normal_below_solar_target"


def test_temperature_safety_path_normal_at_solar_target(mock_hass):
    mock_hass.states.get = MagicMock(return_value=_state("52.0"))
    h = _make(mock_hass, solar_target_temp=50.0)
    assert h.is_temperature_safe() is False
    assert h.to_dict()["temperature_safety_path"] == "normal_at_solar_target"


def test_temperature_safety_path_legionella_below_target(mock_hass):
    mock_hass.states.get = MagicMock(return_value=_state("58.0"))
    h = _make(mock_hass, legionella_target_temp=65.0)
    h._legionella_cycle_active = True
    assert h.is_temperature_safe() is True
    assert h.to_dict()["temperature_safety_path"] == "in_legionella_cycle_below_target"


def test_temperature_safety_path_legionella_at_target(mock_hass):
    mock_hass.states.get = MagicMock(return_value=_state("66.0"))
    h = _make(mock_hass, legionella_target_temp=65.0)
    h._legionella_cycle_active = True
    assert h.is_temperature_safe() is False
    assert h.to_dict()["temperature_safety_path"] == "in_legionella_cycle_at_target"


# ──────────────────────────────────────────────
# legionella_path
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_legionella_path_idle(mock_hass):
    """Recent cycle + temp below 60°C — nothing to do."""
    mock_hass.states.get = MagicMock(return_value=_state("45.0"))
    h = _make(mock_hass)
    h._last_legionella_time = dt_util.now() - timedelta(hours=2)
    await h.check_legionella_cycle()
    assert h.to_dict()["legionella_path"] == "idle"


@pytest.mark.asyncio
async def test_legionella_path_natural_achievement(mock_hass):
    """Tank reached ≥60°C without a forced cycle."""
    mock_hass.states.get = MagicMock(return_value=_state("62.0"))
    h = _make(mock_hass)
    h._last_legionella_time = dt_util.now() - timedelta(hours=10)
    await h.check_legionella_cycle()
    assert h.to_dict()["legionella_path"] == "natural_achievement"


@pytest.mark.asyncio
async def test_legionella_path_overdue_start(mock_hass):
    """Cycle overdue + sensor available → forced cycle starts."""
    mock_hass.states.get = MagicMock(return_value=_state("40.0"))
    h = _make(mock_hass)
    h._last_legionella_time = dt_util.now() - timedelta(hours=100)  # overdue
    await h.check_legionella_cycle()
    assert h._legionella_cycle_active is True
    assert h.to_dict()["legionella_path"] == "overdue_start"


@pytest.mark.asyncio
async def test_legionella_path_overdue_no_sensor(mock_hass):
    """Cycle overdue but temp sensor unreachable — skip with warning."""
    mock_hass.states.get = MagicMock(return_value=_state("unavailable"))
    h = _make(mock_hass)
    h._last_legionella_time = dt_util.now() - timedelta(hours=100)
    await h.check_legionella_cycle()
    assert h._legionella_cycle_active is False
    assert h.to_dict()["legionella_path"] == "overdue_no_sensor"


@pytest.mark.asyncio
async def test_legionella_path_heating_to_target(mock_hass):
    """Cycle active + temp below target → still heating."""
    mock_hass.states.get = MagicMock(return_value=_state("55.0"))
    h = _make(mock_hass, legionella_target_temp=65.0)
    h._legionella_cycle_active = True
    h._last_legionella_time = dt_util.now() - timedelta(hours=100)
    await h.check_legionella_cycle()
    assert h.to_dict()["legionella_path"] == "heating_to_target"


@pytest.mark.asyncio
async def test_legionella_path_hold_reached_target(mock_hass):
    """Cycle active + temp at target + first time at target → start hold."""
    mock_hass.states.get = MagicMock(return_value=_state("66.0"))
    h = _make(mock_hass, legionella_target_temp=65.0)
    h._legionella_cycle_active = True
    h._legionella_hold_start = None  # first time at target
    h._last_legionella_time = dt_util.now() - timedelta(hours=100)
    await h.check_legionella_cycle()
    assert h.to_dict()["legionella_path"] == "hold_reached_target"


@pytest.mark.asyncio
async def test_legionella_path_hold_in_progress(mock_hass):
    """Cycle active + temp at target + hold already started + not yet
    elapsed → hold_in_progress."""
    mock_hass.states.get = MagicMock(return_value=_state("66.0"))
    h = _make(mock_hass, legionella_target_temp=65.0)
    h._legionella_cycle_active = True
    h._legionella_hold_start = dt_util.now() - timedelta(minutes=1)
    h._last_legionella_time = dt_util.now() - timedelta(hours=100)
    await h.check_legionella_cycle()
    assert h.to_dict()["legionella_path"] == "hold_in_progress"


@pytest.mark.asyncio
async def test_legionella_path_hold_complete(mock_hass):
    """Cycle active + temp at target + hold elapsed enough → complete,
    deactivate, reset flags."""
    # water_heater entity must carry the current_temperature attribute
    # so the controller can read 66°C — without it the path falls
    # through to ``heating_to_target`` (temp = None).
    mock_hass.states.get = MagicMock(
        return_value=_state("on", {"current_temperature": 66.0})
    )
    h = HotWaterController(
        hass=mock_hass, entity_id="water_heater.boiler",
        legionella_target_temp=65.0,
    )
    h._legionella_cycle_active = True
    # 65°C target → hold = 20 min, set start to 25 min ago
    h._legionella_hold_start = dt_util.now() - timedelta(minutes=25)
    h._last_legionella_time = dt_util.now() - timedelta(hours=100)
    await h.check_legionella_cycle()
    d = h.to_dict()
    assert d["legionella_path"] == "hold_complete"
    assert h._legionella_cycle_active is False
    assert h._legionella_hold_start is None


# ──────────────────────────────────────────────
# activation_path / deactivation_path
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_activation_path_blocked_unsafe(mock_hass):
    """Temperature above solar target → activation blocked."""
    mock_hass.states.get = MagicMock(return_value=_state("55.0"))
    h = _make(mock_hass, solar_target_temp=50.0)
    result = await h.activate(2000.0)
    assert result == 0.0
    assert h.to_dict()["activation_path"] == "blocked_unsafe"


@pytest.mark.asyncio
async def test_activation_path_water_heater(mock_hass):
    mock_hass.states.get = MagicMock(
        return_value=_state("on", {"current_temperature": 40.0})
    )
    h = HotWaterController(
        hass=mock_hass, entity_id="water_heater.boiler",
    )
    await h.activate(2000.0)
    assert h.to_dict()["activation_path"] == "water_heater"


@pytest.mark.asyncio
async def test_activation_path_climate(mock_hass):
    mock_hass.states.get = MagicMock(
        return_value=_state("heat", {"current_temperature": 40.0})
    )
    h = HotWaterController(
        hass=mock_hass, entity_id="climate.boiler",
    )
    await h.activate(2000.0)
    assert h.to_dict()["activation_path"] == "climate"


@pytest.mark.asyncio
async def test_deactivation_path_water_heater(mock_hass):
    mock_hass.states.get = MagicMock(return_value=_state("on"))
    h = HotWaterController(hass=mock_hass, entity_id="water_heater.boiler")
    await h.deactivate()
    assert h.to_dict()["deactivation_path"] == "water_heater"


@pytest.mark.asyncio
async def test_deactivation_path_climate(mock_hass):
    mock_hass.states.get = MagicMock(return_value=_state("heat"))
    h = HotWaterController(hass=mock_hass, entity_id="climate.boiler")
    await h.deactivate()
    assert h.to_dict()["deactivation_path"] == "climate"


# ──────────────────────────────────────────────
# legionella_hold_elapsed_minutes + hours_since_legionella_or_none
# ──────────────────────────────────────────────


def test_hold_elapsed_none_when_not_holding(mock_hass):
    h = _make(mock_hass)
    assert h.legionella_hold_elapsed_minutes is None
    assert h.to_dict()["legionella_hold_elapsed_minutes"] is None


def test_hold_elapsed_tracks_start(mock_hass):
    """Holding for ~5 minutes — sensor surfaces the elapsed time."""
    h = _make(mock_hass)
    h._legionella_hold_start = dt_util.now() - timedelta(minutes=5)
    elapsed = h.legionella_hold_elapsed_minutes
    assert elapsed is not None
    assert 4.5 < elapsed < 5.5
    assert h.to_dict()["legionella_hold_elapsed_minutes"] == elapsed


def test_hours_since_legionella_or_none_when_never_run(mock_hass):
    """Disambiguates the 999.0 sentinel from a real reading."""
    h = _make(mock_hass)
    # 999.0 sentinel is still returned by the existing accessor
    assert h.hours_since_legionella == 999.0
    # New accessor returns None unambiguously
    assert h.hours_since_legionella_or_none is None
    assert h.to_dict()["hours_since_legionella_or_none"] is None


def test_hours_since_legionella_or_none_with_real_value(mock_hass):
    h = _make(mock_hass)
    h._last_legionella_time = dt_util.now() - timedelta(hours=12)
    val = h.hours_since_legionella_or_none
    assert val is not None
    assert 11.5 < val < 12.5


# ──────────────────────────────────────────────
# Initial path state — uninitialized until first call
# ──────────────────────────────────────────────


def test_paths_start_uninitialized(mock_hass):
    """Brand-new controller hasn't run any decision yet."""
    h = _make(mock_hass)
    d = h.to_dict()
    # to_dict calls is_temperature_safe / get_current_temperature itself
    # which initializes a couple of paths, but legionella + activation
    # haven't fired yet.
    assert d["legionella_path"] == "uninitialized"
    assert d["activation_path"] == "uninitialized"
    assert d["deactivation_path"] == "uninitialized"
