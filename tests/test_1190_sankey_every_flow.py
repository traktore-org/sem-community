"""#1190 — the Energy tab Sankey draws every energy flow SEM publishes.

SEM booked a sold battery's energy in ``sensor.sem_flow_battery_to_grid_energy``
(#776), but the Sankey's Battery node listed only Home and EV. The Export
total held that energy and no line led to it from Battery.

The guard reads the flow keys from ``SENSOR_TYPES``, so the next flow SEM
adds fails here until the Sankey draws it: a child of its source total in the
first column, and a node in the middle column that leads to its target total.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import yaml

from custom_components.solar_energy_management.features.dashboard_generator import (
    DashboardGenerator,
)
from custom_components.solar_energy_management.sensor import SENSOR_TYPES

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "dashboard" / "sem_dashboard_template.yaml"
TRANSLATIONS = ROOT / "dashboard" / "translations.json"

# Each end of a flow, as the Sankey's total node for it.
SOURCE_TOTAL = {
    "solar": "sensor.sem_daily_solar_energy",
    "grid": "sensor.sem_daily_grid_import_energy",
    "battery": "sensor.sem_daily_battery_discharge_energy",
}
TARGET_TOTAL = {
    "home": "sensor.sem_daily_home_energy",
    "ev": "sensor.sem_daily_ev_energy",
    "battery": "sensor.sem_daily_battery_charge_energy",
    "grid": "sensor.sem_daily_grid_export_energy",
}
# Non-greedy: an end of two words (``heat_pump``) still matches, so a flow
# like that cannot slip past the guard.
FLOW_KEY = re.compile(r"^flow_([a-z_]+?)_to_([a-z_]+)_energy$")


def _template():
    return yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))


def _sankey(tpl):
    """The one ``custom:sankey-chart`` card config in the template."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "custom:sankey-chart":
                found.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(tpl)
    assert len(found) == 1, f"expected one sankey-chart, found {len(found)}"
    return found[0]


def _columns(sankey):
    return [{e["entity_id"]: e for e in section["entities"]}
            for section in sankey["sections"]]


def _flow_keys():
    keys = [d.key for d in SENSOR_TYPES if FLOW_KEY.match(d.key)]
    assert len(keys) >= 10, keys  # never pass on an empty list
    return keys


def test_the_new_label_is_translated_in_every_language():
    tables = json.loads(TRANSLATIONS.read_text(encoding="utf-8"))
    assert len(tables) >= 16
    for lang, table in tables.items():
        assert table.get("Bat>Grid"), lang
        if lang != "en":
            assert table["Bat>Grid"] != "Bat>Grid", lang


def _generator(presence, language="en"):
    hass = MagicMock()
    hass.config.language = language
    entry = MagicMock()
    entry.data = {"ev_chargers": [{"id": "ev_charger"}]}
    entry.options = {}
    entry.runtime_data.setup_presence = presence
    hass.config_entries.async_entries.return_value = [entry]
    hass.data = {}
    gen = DashboardGenerator(hass)
    gen._cached_translations = json.loads(TRANSLATIONS.read_text(encoding="utf-8"))
    return gen


def test_no_cyrillic_letters_in_the_tables():
    """The Czech "Export" read "Přeток": three Cyrillic letters that look
    Latin. None of SEM's languages is written in Cyrillic."""
    cyrillic = re.compile("[Ѐ-ӿ]")
    files = [TRANSLATIONS, ROOT / "strings.json", *sorted((ROOT / "translations").glob("*.json"))]
    assert len(files) >= 18
    found = [f"{f.name}: {m.group(0)!r} in {line.strip()[:60]}"
             for f in files
             for line in f.read_text(encoding="utf-8").splitlines()
             for m in [cyrillic.search(line)] if m]
    assert not found, found
