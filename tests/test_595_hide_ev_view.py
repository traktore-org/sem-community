"""#595 — the EV tab is removed when no EV charger is configured."""

from unittest.mock import MagicMock

from custom_components.solar_energy_management.features.dashboard_generator import (
    DashboardGenerator,
)


def _generator(full_config):
    hass = MagicMock()
    entry = MagicMock()
    entry.data = full_config
    entry.options = {}
    hass.config_entries.async_entries.return_value = [entry]
    return DashboardGenerator(hass)


def _template():
    return {"views": [
        {"title": "Home", "path": "home"},
        {"title": "EV", "path": "ev"},
        {"title": "Battery", "path": "battery"},
    ]}


def test_ev_tab_removed_when_no_charger():
    gen = _generator({})  # no ev_chargers, no ev_charging_power_sensor
    tpl = _template()
    gen._prune_ev_view_if_no_charger(tpl)
    paths = [v["path"] for v in tpl["views"]]
    assert "ev" not in paths
    assert paths == ["home", "battery"]  # others untouched


def test_ev_tab_kept_when_charger_configured():
    gen = _generator({"ev_chargers": [{"id": "ev_charger"}]})
    tpl = _template()
    gen._prune_ev_view_if_no_charger(tpl)
    assert "ev" in [v["path"] for v in tpl["views"]]


def test_ev_tab_kept_with_legacy_power_sensor():
    gen = _generator({"ev_charging_power_sensor": "sensor.keba_power"})
    tpl = _template()
    gen._prune_ev_view_if_no_charger(tpl)
    assert "ev" in [v["path"] for v in tpl["views"]]


def test_no_entries_is_a_noop():
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = []
    gen = DashboardGenerator(hass)
    tpl = _template()
    gen._prune_ev_view_if_no_charger(tpl)
    assert len(tpl["views"]) == 3  # unchanged
