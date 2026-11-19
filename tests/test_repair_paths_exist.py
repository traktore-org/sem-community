"""(#1371, #1321) A Repair text that names a menu path must name one that exists.

A user followed "Settings → Integrations → SEM → Configure → Sensors → Grid
import power" to a place that was not there. Every "A → B" path in the issue
texts is read from the shipped JSON and each step after the first is checked
against the real names: HA's own fixed parts, the options-flow step titles,
the System screen's group names, its "All settings" switch and the screens.
The classic Configuration tab is gone, so no text may point to it.
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


GROUP_KEYS = tuple(f"next_g_{g}" for g in ("pay", "may", "battery", "chargers", "heat", "reads", "misc"))
# View titles with no translation key stay English on every install.
SCREENS = ("Now", "Plan", "Devices", "Insights", "System")


def _sections(lang: str) -> set[str]:
    """Names a path step may start with on the SEM dashboard: the System
    screen's group cards, its All settings switch and the screens."""
    table = DASHBOARD["zh" if lang == "zh-Hans" else lang]
    names = {table[k] for k in GROUP_KEYS} | {table["next_all_settings"], table["System"], table["Now"]}
    return names | set(SCREENS)


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
    system = DASHBOARD[_dashboard_key(lang)]["System"]
    names = tuple(_sections(lang) | _titles(lang))
    for key, text in en.items():
        assert _plain(local[key]).count(SEPARATOR) == _plain(text).count(SEPARATOR), key
        plain = _plain(local[key])
        for hit in re.finditer(re.escape(system) + SEPARATOR + r"([^→]+)", plain):
            step = hit.group(1).strip()
            assert step.startswith(names), f"{lang} {key}: {step[:40]!r}"


@pytest.mark.parametrize("lang", LANGS)
def test_no_text_points_to_the_retired_configuration_tab(lang):
    """(#1321) The classic dashboard and its Configuration tab are gone."""
    path = ROOT / "strings.json" if lang == "en" else TRANSLATIONS / f"{lang}.json"
    texts = _issue_texts(json.loads(path.read_text("utf-8"))["issues"])
    tab = DASHBOARD[_dashboard_key(lang)]["config_tab_title"]
    for key, text in texts.items():
        plain = _plain(text)
        assert "⚙" not in plain, f"{lang} {key} names the Configuration tab icon"
        for hit in re.finditer(re.escape(tab) + SEPARATOR, plain):
            before, after = plain[:hit.start()], plain[hit.end():hit.end() + 60]
            if before.endswith("SEM" + SEPARATOR) or "→ SEM" in after:
                continue  # HA's own Settings path, which shares the word
            raise AssertionError(f"{lang} {key} starts a path at the retired tab")


def test_the_english_texts_name_the_new_screens_not_the_old_tabs():
    texts = _issue_texts(json.loads((ROOT / "strings.json").read_text("utf-8"))["issues"])
    joined = " ".join(_plain(t) for t in texts.values())
    for old in ("Configuration tab", "Configuration card", "EV tab", "Battery tab", "Configuration →"):
        assert old not in joined, old
    assert "System → Chargers" in joined and "Devices screen" in joined
