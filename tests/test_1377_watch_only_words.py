"""#1377 (beta.21 retest) — the lines beside the two control switches say
the state the switch shows, in every language.

The reporter read "Watch only: enabled" on the System screen while the Plan
screen said SEM controls the devices. Watch-only was off (the Plan header
chip read "En direct"). The System line under the switch was one help text
for both states, and the French one opened with "Activé," — "On," as a
fact. Now there is one line per state, and the plan switch has an Off line.
The card side is pinned in dashboard/card/test/watch-only-says-its-state.test.js.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLES = json.loads((ROOT / "dashboard" / "translations.json").read_text("utf-8"))
BUNDLE = (ROOT / "dashboard" / "card" / "dist" / "sem-cards.js").read_text("utf-8")
NEW = ("next_observer_on_sub", "next_observer_off_sub", "next_actuation_off")


def test_sixteen_languages_carry_the_new_lines():
    assert len(TABLES) == 16
    for lang, table in TABLES.items():
        for key in NEW:
            assert table.get(key), f"{lang}: {key} missing"
            if lang != "en":
                assert table[key] != TABLES["en"][key], f"{lang}: {key} is English"
        assert table["next_observer_on_sub"] != table["next_observer_off_sub"], lang
        assert table["next_actuation_off"] != table["next_actuation_sub"], lang


def test_the_one_line_for_both_states_is_gone():
    for lang, table in TABLES.items():
        assert "next_observer_sub" not in table, lang
    assert "next_observer_sub" not in BUNDLE


def test_the_built_card_uses_the_new_lines():
    for key in NEW:
        assert key in BUNDLE, f"dist/sem-cards.js was not rebuilt ({key})"


def test_the_french_lines_match_the_report():
    fr = TABLES["fr"]
    assert fr["next_observer_on_sub"].startswith("Activé")
    assert fr["next_observer_off_sub"].startswith("Désactivé")
    assert fr["next_actuation_off"].startswith("Désactivé")
