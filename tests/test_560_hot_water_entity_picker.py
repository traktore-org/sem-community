"""Lint: entity pickers must never receive a ``[null]`` domain filter (#560).

``sem-config-card.js`` renders every entity picker via ``_renderPicker``.
The bug: the ``hot_water_entity`` control-entity picker was called with a
literal ``null`` domain, and ``_renderPicker`` passed it straight through as
``.includeDomains=${[domain]}`` → ``[null]``. HA's ``<ha-entity-picker>``
then filters to a non-existent "null" domain and hides EVERY entity, so the
user could not select their hot-water control switch (a ``switch.*`` SwitchBot
relay) while the sibling power-sensor picker worked fine.

Two structural guards for the class:

1. ``_renderPicker`` must NOT bind ``.includeDomains`` to a bare ``[domain]``
   array — it has to normalise (null → no filter, string → ``[string]``,
   array → as-is).
2. The ``hot_water_entity`` picker call must offer the control domains the
   ``HotWaterController`` actually drives (``switch`` at minimum, plus
   ``water_heater`` / ``climate``), never a bare ``null``.
"""
import re
from pathlib import Path

CONFIG_CARD = (
    Path(__file__).resolve().parent.parent
    / "dashboard" / "card" / "src" / "cards" / "sem-config-card.js"
)


def test_render_picker_normalises_domain():
    src = CONFIG_CARD.read_text(encoding="utf-8")
    assert CONFIG_CARD.is_file(), f"missing card source: {CONFIG_CARD}"
    # The ``[null]``-producing anti-pattern must be gone. A bare
    # ``.includeDomains=${[domain]}`` re-introduces #560.
    assert ".includeDomains=${[domain]}" not in src, (
        "_renderPicker binds .includeDomains to a bare [domain] array — a "
        "null domain becomes [null] and hides every entity (#560). Normalise "
        "the domain (null → undefined, string → [string], array → as-is)."
    )


def test_hot_water_entity_picker_offers_switch_domain():
    src = CONFIG_CARD.read_text(encoding="utf-8")
    # Locate the hot_water_entity _renderPicker call and capture its args.
    m = re.search(
        r"_renderPicker\(\s*'hot_water_entity'.*?\)", src, re.S
    )
    assert m, "hot_water_entity _renderPicker call not found"
    call = m.group(0)
    assert "'switch'" in call, (
        "hot_water_entity picker must offer the 'switch' control domain so a "
        "SwitchBot / Shelly relay can be selected (#560); found:\n" + call
    )
    # Guard against a regression back to the bare-null domain argument.
    assert re.search(r"'hot_water_entity'\s*,\s*'config_hw_entity'\s*,\s*null", call) is None, (
        "hot_water_entity picker passes a null domain again (#560)."
    )
