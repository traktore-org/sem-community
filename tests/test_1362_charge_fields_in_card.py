"""(#1362) The grid-charge fields on the System screen.

The select pair showed for one battery only, and the charge switch and the
charge target had no field at all (only the crawler filled them). Pinned
(#1321, on the SEM dashboard): each key has an entity field with its domains,
stages and reloads like the select pair, and the built bundle carries them.
Their behaviour is pinned in dashboard/card/test/next-system-settings.test.js.
"""
from __future__ import annotations

import re
from pathlib import Path

from custom_components.solar_energy_management import _SET_OPTION_STRUCTURAL_KEYS

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "dashboard" / "card" / "src" / "util" / "next-settings.js"
KEYS = ("battery_charge_select_entity", "battery_charge_select_option",
        "battery_force_charge_switch", "battery_target_soc_entity")


def test_every_charge_key_reloads_the_entry():
    for key in KEYS:
        assert key in _SET_OPTION_STRUCTURAL_KEYS, key


def test_the_screen_stages_every_charge_key():
    src = SETTINGS.read_text()
    block = src[src.index("export const STRUCTURAL_KEYS"):]
    block = block[:block.index("]);")]
    for key in KEYS:
        assert f"'{key}'" in block, key


def test_the_screen_has_a_picker_for_the_switch_and_the_target():
    src = SETTINGS.read_text()
    assert re.search(r"battery_force_charge_switch: \{ domain: \['switch', 'input_boolean'\]", src)
    assert re.search(r"battery_target_soc_entity: \{ domain: \['number', 'input_number'\]", src)


def test_the_built_bundle_has_the_fields():
    dist = (ROOT / "dashboard" / "card" / "dist" / "sem-cards.js").read_text()
    for word in ("config_charge_switch_entity", "config_charge_target_entity",
                 "config_charge_select_option"):
        assert word in dist, word
