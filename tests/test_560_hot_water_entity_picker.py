"""Lint: entity pickers must never receive a ``[null]`` domain filter (#560).

The bug: the ``hot_water_entity`` control-entity picker was given a literal
``null`` domain, which HA's ``<ha-entity-picker>`` read as a non-existent
"null" domain and hid EVERY entity, so the user could not select their
hot-water control switch (a ``switch.*`` SwitchBot relay).

Since #1321 the System screen draws the picker from ``ENTITY_FIELDS``: the
``hot_water_entity`` field must offer the control domains the
``HotWaterController`` actually drives (``switch`` at minimum, plus
``water_heater`` / ``climate``), never a bare null.
"""
import re
from pathlib import Path

SETTINGS = (
    Path(__file__).resolve().parent.parent
    / "dashboard" / "card" / "src" / "util" / "next-settings.js"
)


def test_hot_water_entity_picker_offers_switch_domain():
    src = SETTINGS.read_text(encoding="utf-8")
    m = re.search(r"\bhot_water_entity: \{ domain: (\[[^\]]*\]|[^,]+),", src)
    assert m, "hot_water_entity field not found in ENTITY_FIELDS"
    domains = m.group(1)
    assert "'switch'" in domains, (
        "hot_water_entity picker must offer the 'switch' control domain so a "
        "SwitchBot / Shelly relay can be selected (#560); found: " + domains
    )
    assert "null" not in domains, "hot_water_entity picker passes a null domain again (#560)"
