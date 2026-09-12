"""#923 — the real dashboard template, pruned for a minimal install, holds no
reference to an entity the install does not create; a full install loses
nothing; an unknown verdict prunes nothing."""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import yaml

from custom_components.solar_energy_management.coordinator.install_modules import (
    Module, Presence, absent_entity_ids,
)
from custom_components.solar_energy_management.features.dashboard_generator import (
    DashboardGenerator,
)

TEMPLATE = Path(__file__).resolve().parents[1] / "dashboard" / "sem_dashboard_template.yaml"
ABSENT = {m: Presence.ABSENT for m in Module}
PRESENT = {m: Presence.PRESENT for m in Module}


def _generator(full_config, presence=None):
    hass = MagicMock()
    entry = MagicMock()
    entry.data = full_config
    entry.options = {}
    if presence is not None:
        entry.runtime_data.setup_presence = presence
    hass.config_entries.async_entries.return_value = [entry]
    hass.data = {}
    return DashboardGenerator(hass)


def _template():
    return yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))


def _dump(tpl):
    return json.dumps(tpl, sort_keys=True)


def test_a_minimal_install_references_no_absent_entity():
    tpl = _template()
    _generator({}, ABSENT)._prune_absent_modules(tpl)
    assert {"battery", "ev"}.isdisjoint(v.get("path") for v in tpl["views"])
    dumped = _dump(tpl)
    leftovers = sorted(
        eid for eid in absent_entity_ids(ABSENT)
        if re.search(rf"(?<![a-z0-9_.]){re.escape(eid)}(?![a-z0-9_])", dumped))
    assert not leftovers, leftovers


def test_the_sankey_keeps_its_core_nodes():
    tpl = _template()
    _generator({}, ABSENT)._prune_absent_modules(tpl)
    dumped = _dump(tpl)
    for core in ("sensor.sem_daily_solar_energy", "sensor.sem_flow_solar_to_home_energy",
                 "sensor.sem_daily_home_energy", "sensor.sem_daily_grid_export_energy"):
        assert core in dumped


def test_a_full_install_loses_nothing():
    tpl = _template()
    before = _dump(tpl)
    _generator({"ev_chargers": [{"id": "ev_charger"}]}, PRESENT)._prune_absent_modules(tpl)
    assert _dump(tpl) == before


def test_an_unknown_verdict_prunes_nothing():
    tpl = _template()
    before = _dump(tpl)
    _generator({"ev_chargers": [{"id": "ev_charger"}]})._prune_absent_modules(tpl)
    assert _dump(tpl) == before


def test_dashboard_ev_data_keeps_ev_entities_but_not_the_ev_tab():
    tpl = _template()
    _generator({}, {**ABSENT, Module.EV: Presence.PRESENT})._prune_absent_modules(tpl)
    assert "ev" not in [v.get("path") for v in tpl["views"]]
    assert "sensor.sem_flow_solar_to_ev_energy" in _dump(tpl)


def test_an_emptied_stack_is_removed():
    tpl = {"views": [{"path": "home", "cards": [
        {"type": "vertical-stack", "cards": [
            {"type": "custom:sem-gauge-card", "entity": "sensor.sem_battery_soc"},
        ]},
        {"type": "custom:sem-gauge-card", "entity": "sensor.sem_autarky_rate"},
    ]}]}
    _generator({}, ABSENT)._prune_absent_modules(tpl)
    assert tpl["views"][0]["cards"] == [
        {"type": "custom:sem-gauge-card", "entity": "sensor.sem_autarky_rate"}]
