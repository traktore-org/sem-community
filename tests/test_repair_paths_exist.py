"""(#1371) A Repair text that names a menu path must name one that exists.

A user followed "Settings → Integrations → SEM → Configure → Sensors → Grid
import power" to a place that was not there. Every "A → B" path in the issue
texts is read from the shipped JSON and each step after the first is checked
against the real names: HA's own fixed parts, the options-flow step titles
and the dashboard Configuration tab sections.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TRANSLATIONS = ROOT / "translations"
LANGS = sorted(p.stem for p in TRANSLATIONS.glob("*.json"))
DASHBOARD = json.loads((ROOT / "dashboard" / "translations.json").read_text("utf-8"))
HA_FIXED = (
    "Devices & Services", "Integrations", "SEM", "Configure", "States",
    "Actions", "Settings", "<code>",
)
SEPARATOR = " → "


def _issue_texts(issues: dict) -> dict[str, str]:
    """Every title and description under issues.*, keyed by its path."""
    found: dict[str, str] = {}

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, str) and path.rsplit(".", 1)[-1] in ("title", "description"):
            found[path] = node

    walk(issues, "issues")
    return found


def _plain(text: str) -> str:
    """Drop code fences and inline code, then bold/italic marks."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`[^`]*`", "<code>", text)
    return text.replace("*", "")


def _titles(lang: str) -> set[str]:
    """Options-flow step titles and menu names for one language."""
    path = ROOT / "strings.json" if lang == "en" else TRANSLATIONS / f"{lang}.json"
    options = json.loads(path.read_text("utf-8")).get("options", {}).get("step", {})
    names = set()
    for step in options.values():
        names.add(step.get("title", ""))
        names.update(step.get("menu_options", {}).values())
    return {n for n in names if n and "{" not in n}


def _sections(lang: str) -> set[str]:
    """Titles of the dashboard Configuration tab sections."""
    table = DASHBOARD["zh" if lang == "zh-Hans" else lang]
    return {v for k, v in table.items()
            if k.startswith("config_section_") and "subtitle" not in k}


def _dashboard_key(lang: str) -> str:
    return "zh" if lang == "zh-Hans" else lang


def _bad_steps_en(text: str, allowed: tuple[str, ...]) -> list[str]:
    """Steps after an arrow that start with no known name."""
    parts = _plain(text).split(SEPARATOR)[1:]
    return [p.strip()[:40] for p in parts if not p.strip().startswith(allowed)]


@pytest.mark.parametrize("key,text", sorted(
    _issue_texts(json.loads((ROOT / "strings.json").read_text("utf-8"))["issues"]).items()))
def test_english_paths_name_real_places(key, text):
    allowed = HA_FIXED + tuple(_titles("en")) + tuple(_sections("en"))
    assert not _bad_steps_en(text, allowed), f"{key} names a menu that does not exist"


def test_there_are_paths_to_check():
    texts = _issue_texts(json.loads((ROOT / "strings.json").read_text("utf-8"))["issues"])
    assert sum(SEPARATOR in _plain(t) for t in texts.values()) >= 5


def test_the_check_refuses_a_made_up_menu():
    allowed = HA_FIXED + tuple(_titles("en")) + tuple(_sections("en"))
    bad = "Open Settings → Integrations → SEM → Configure → Sensors → Grid import power"
    assert _bad_steps_en(bad, allowed)


@pytest.mark.parametrize("lang", LANGS)
def test_translated_paths_follow_english_and_name_real_sections(lang):
    en = _issue_texts(json.loads((ROOT / "strings.json").read_text("utf-8"))["issues"])
    local = _issue_texts(json.loads((TRANSLATIONS / f"{lang}.json").read_text("utf-8"))["issues"])
    tab = DASHBOARD[_dashboard_key(lang)]["config_tab_title"]
    names = tuple(_sections(lang) | _titles(lang))
    for key, text in en.items():
        assert _plain(local[key]).count(SEPARATOR) == _plain(text).count(SEPARATOR), key
        plain = _plain(local[key])
        for hit in re.finditer(re.escape(tab) + SEPARATOR + r"([^→]+)", plain):
            if plain[hit.end():].startswith("→ SEM"):
                continue  # HA's own Settings path, not the Configuration tab
            step = hit.group(1).strip()
            assert step.startswith(names), f"{lang} {key}: {step[:40]!r}"
