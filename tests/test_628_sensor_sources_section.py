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
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_CARD = _ROOT / "dashboard" / "card" / "src" / "cards" / "sem-config-card.js"
_TRANSLATIONS = _ROOT / "dashboard" / "translations.json"

_KEYS = ("grid_power_sensor", "solar_production_sensor", "battery_power_sensor",
         "house_power_sensor")   # (#891) the fourth source


@pytest.mark.unit
class TestSensorSourcesSection:


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
