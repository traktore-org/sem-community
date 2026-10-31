"""#1237 — setup finds a two-sensor grid meter the way SEM does later.

When the Energy Dashboard's grid entry has kWh counters and no power sensor,
setup said "No grid power sensor found" and showed a sensor picker. A meter
with one import and one export power sensor (DSMR, SlimmeLezer) is found by
SEM itself once it runs. A user who picked one of the two there had that one
saved as the only grid sensor: SEM reads it first and never looks for the
pair, so export read 0 W.

Setup now runs the SAME search (``SensorReader._discover_split_grid_power``),
so a found pair is shown as found and the picker is not opened. Bug class 10
(the split-pair half): two places that must agree on what a meter is.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management import config_flow as cf
from custom_components.solar_energy_management.coordinator import (
    sensor_reader as sr_mod,
)
from custom_components.solar_energy_management.ha_energy_reader import (
    EnergyDashboardConfig,
)
from custom_components.solar_energy_management.setup_check import (
    ASK_MISSING, build_setup_check,
)

from .test_1225_slimmelezer_pair import (
    EXP, IMP, _counters_only, _slimmelezer,
)

CTR_IN = "sensor.slimmelezer_energy_consumed_tariff_1"
CTR_OUT = "sensor.slimmelezer_energy_produced_tariff_1"


def _cfg(**kw):
    """What the Energy Dashboard gave: counters only on the grid entry."""
    cfg = EnergyDashboardConfig()
    cfg.has_solar = cfg.has_grid = True
    cfg.solar_power = "sensor.pv"
    cfg.solar_power_list = ["sensor.pv"]
    cfg.grid_import_energy = CTR_IN
    cfg.grid_export_energy = CTR_OUT
    cfg.grid_import_energy_list = [CTR_IN]
    cfg.grid_export_energy_list = [CTR_OUT]
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def _hass(house):
    house.reader = None
    hass = house._reader().hass          # states.get / async_all over the house
    hass.config.language = "en"
    return hass


def _check(house, cfg=None):
    hass = _hass(house)
    with patch.object(sr_mod.er, "async_get", return_value=house._registry()), \
            patch.object(sr_mod, "is_sem_entity", lambda *a, **k: False):
        return build_setup_check(hass, cfg or _cfg())


def test_a_found_pair_is_shown_as_found_and_asks_nothing():
    check = _check(_slimmelezer(import_kw=1.2, export_kw=0.0))
    assert check.ask is None
    assert check.grid_from == "pair"
    assert check.grid_pair == (IMP, EXP)
    assert check.grid_w == pytest.approx(1200.0)          # kW read as W
    # No single sensor stands for the meter, so no sign question and no
    # "use the other meter" can pin one half of it.
    assert check.grid_entity is None
    assert check.other_grid is None


def test_counters_with_no_pair_still_open_the_picker():
    check = _check(_counters_only())
    assert check.ask == ASK_MISSING
    assert check.grid_from == "missing"
    assert check.grid_pair == (None, None)


def test_setup_and_the_reader_pick_the_same_pair():
    """One search, two callers: what setup shows is what SEM reads."""
    house = _slimmelezer(import_kw=0.8, export_kw=0.0)
    check = _check(house)
    power, picks = house.read()
    assert picks[:2] == check.grid_pair == (IMP, EXP)
    assert power.grid_power == pytest.approx(-800.0)


def test_a_dashboard_power_sensor_is_not_searched_for_a_pair():
    """Zero-config sibling: a power sensor from the dashboard is used as it
    always was; the pair search only runs where SEM would run it."""
    house = _slimmelezer(import_kw=1.2, export_kw=0.0)
    house.add("sensor.meter", 310, "W")
    check = _check(house, _cfg(grid_import_power="sensor.meter"))
    assert check.grid_from == "dashboard"
    assert check.grid_entity == "sensor.meter"
    assert check.grid_pair == (None, None)


def test_a_declared_dashboard_pair_wins_over_the_search():
    house = _slimmelezer(import_kw=1.2, export_kw=0.0)
    house.add("sensor.in", 0, "W")
    house.add("sensor.out", 900, "W")
    check = _check(house, _cfg(grid_power_from="sensor.in",
                               grid_power_to="sensor.out"))
    assert check.grid_from == "dashboard"
    assert check.grid_w == -900
    assert check.grid_pair == (None, None)


def test_a_search_that_breaks_never_breaks_setup():
    house = _slimmelezer(import_kw=1.2, export_kw=0.0)
    hass = _hass(house)
    with patch.object(sr_mod.SensorReader, "_discover_split_grid_power",
                      side_effect=RuntimeError("boom")):
        check = build_setup_check(hass, _cfg())
    assert check.ask == ASK_MISSING


# ── the real flow ──────────────────────────────────────────────────────────

async def _run_flow(house, cfg, first_input=None):
    flow = cf.SolarEnergyManagementConfigFlow()
    flow.hass = _hass(house)
    patches = [
        patch.object(cf, "read_energy_dashboard_config",
                     AsyncMock(return_value=cfg)),
        patch("custom_components.solar_energy_management.hardware_detection."
              "propose_energy_sources", return_value={}),
        patch.object(cf, "_power_sensor_selector", return_value=MagicMock()),
        patch.object(cf, "discover_inverter_from_registry", return_value=None),
        patch.object(sr_mod.er, "async_get", return_value=house._registry()),
        patch.object(sr_mod, "is_sem_entity", lambda *a, **k: False),
    ]
    for p in patches:
        p.start()
    try:
        return flow, await flow.async_step_user(first_input)
    finally:
        for p in patches:
            p.stop()


@pytest.mark.asyncio
async def test_the_flow_does_not_open_the_picker_for_a_pair():
    flow, shown = await _run_flow(_slimmelezer(1.2, 0.0), _cfg())
    assert shown["step_id"] == "user"
    flow, done = await _run_flow(_slimmelezer(1.2, 0.0), _cfg(), first_input={})
    assert done["step_id"] == "hardware"
    # nothing pinned: SEM goes on looking for the pair by itself
    assert "grid_power_sensor" not in flow._data


@pytest.mark.asyncio
async def test_the_flow_still_opens_the_picker_when_there_is_no_pair():
    _, shown = await _run_flow(_counters_only(), _cfg())
    assert shown["step_id"] == "pick_grid"
