"""#628 fix 4 (+ #696) — the Sensor sources section stays wired.

The three power-source override keys existed in the data model since #592/#597
(SensorReaderConfig + backend structural reload) but had no UI surface — the
"right entity exists but SEM can't be pointed at it" class. This pins the
card surface so it can't silently regress:

- the ``sensor_sources`` accordion section exists with a resolvable docs link
  (anchor resolution itself is guarded by test_618_docs_anchors),
- all three pickers render in ``_renderSensorSources``,
- all three keys are card-structural (staged → one Apply → one reload; the
  backend-subset rule is guarded by test_528_structural_keys_parity),
- every language carries the new translation keys.
"""
import json
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_CARD = _ROOT / "dashboard" / "card" / "src" / "cards" / "sem-config-card.js"
_TRANSLATIONS = _ROOT / "dashboard" / "translations.json"

_KEYS = ("grid_power_sensor", "solar_production_sensor", "battery_power_sensor")


@pytest.mark.unit
class TestSensorSourcesSection:
    def test_section_registered(self):
        src = _CARD.read_text(encoding="utf-8")
        assert "id: 'sensor_sources'" in src
        assert "sensor_sources: (T) => this._renderSensorSources(T)" in src
        m = re.search(r"id: 'sensor_sources'.*?docs: '([^']+)'", src, re.S)
        assert m and "#sensor-source-overrides" in m.group(1)

    def test_all_three_pickers_render_in_the_section(self):
        src = _CARD.read_text(encoding="utf-8")
        m = re.search(r"_renderSensorSources\(T\) \{(.*?)\n    \}", src, re.S)
        assert m, "_renderSensorSources not found"
        body = m.group(1)
        for key in _KEYS:
            assert f"'{key}'" in body, f"{key} picker missing from the section"
        # failure honesty: every picker carries its unavailable-override warning
        assert body.count("_sourceUnavailableWarning") == 3

    def test_keys_are_card_structural(self):
        src = _CARD.read_text(encoding="utf-8")
        m = re.search(r"const STRUCTURAL_KEYS = new Set\(\[(.*?)\]\)", src, re.S)
        assert m
        keys = set(re.findall(r"'([^']+)'", m.group(1)))
        missing = set(_KEYS) - keys
        assert not missing, (
            f"{missing} not card-structural — their edits would commit "
            "per-field (a reload per keystroke) instead of one Apply batch"
        )

    def test_moved_pickers_render_exactly_once(self):
        """battery_power_sensor moved out of Battery & zones and
        solar_production_sensor out of Tariff — each key must have exactly ONE
        picker on the whole card, or two pickers fight over one option."""
        src = _CARD.read_text(encoding="utf-8")
        for key in _KEYS:
            count = len(re.findall(rf"_renderPicker\('{key}'", src))
            assert count == 1, f"{key} rendered {count}× (expected exactly 1)"

    def test_translations_cover_all_languages(self):
        tr = json.loads(_TRANSLATIONS.read_text(encoding="utf-8"))
        needed = (
            "config_section_sensor_sources", "config_sources_intro",
            "config_grid_power_sensor", "config_help_grid_power_sensor",
            "config_sources_all_auto", "config_sources_overridden",
            "config_source_unavailable",
        )
        for lang, table in tr.items():
            for key in needed:
                assert table.get(key), f"{lang} missing {key}"
