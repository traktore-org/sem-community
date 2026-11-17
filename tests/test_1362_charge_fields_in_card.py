"""(#1362) The grid-charge fields on the Configuration tab.

The select pair showed for one battery only, and the charge switch and the
charge target had no field at all (only the crawler filled them). Pinned:
the card has a field for each, they stage and reload like the select pair,
and the card source and the built bundle agree.
"""
from __future__ import annotations

import re
from pathlib import Path

from custom_components.solar_energy_management import _SET_OPTION_STRUCTURAL_KEYS

ROOT = Path(__file__).resolve().parent.parent
CARD = ROOT / "dashboard" / "card" / "src" / "cards" / "sem-config-card.js"
KEYS = ("battery_charge_select_entity", "battery_charge_select_option",
        "battery_force_charge_switch", "battery_target_soc_entity")


def test_every_charge_key_reloads_the_entry():
    for key in KEYS:
        assert key in _SET_OPTION_STRUCTURAL_KEYS, key


def test_the_card_stages_every_charge_key():
    src = CARD.read_text()
    block = src[src.index("const STRUCTURAL_KEYS"):]
    block = block[:block.index("]);")]
    for key in KEYS:
        assert f"'{key}'" in block, key


def test_the_card_has_a_picker_for_the_switch_and_the_target():
    src = CARD.read_text()
    assert re.search(r"_renderPicker\('battery_force_charge_switch',\s*'config_charge_switch_entity',\s*\['switch', 'input_boolean'\]", src)
    assert re.search(r"_renderPicker\('battery_target_soc_entity',\s*'config_charge_target_entity',\s*\['number', 'input_number'\]", src)


def test_the_built_bundle_has_the_fields():
    dist = (ROOT / "dashboard" / "card" / "dist" / "sem-cards.js").read_text()
    for word in ("config_charge_switch_entity", "config_charge_target_entity",
                 "_renderBatteryChargeFields"):
        assert word in dist, word
