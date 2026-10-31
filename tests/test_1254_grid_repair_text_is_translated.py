"""#1254: the two grid Repairs stay translated in every language.

test_1129 reads every key. This pins the two keys by name, and proves the
rule catches the case it was written for: English prose that names the
settings in the user's language.
"""
import json
import os

import pytest

from .test_1129_untranslated_prose import (
    _COMPONENT_DIR, _copied_prose, _english_sentences,
)

KEYS = ("split_grid_guessed", "split_grid_rejected")


def _issues(lang: str) -> dict:
    path = os.path.join(_COMPONENT_DIR, "translations", f"{lang}.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)["issues"]


def _languages() -> list[str]:
    folder = os.path.join(_COMPONENT_DIR, "translations")
    return sorted(n[:-5] for n in os.listdir(folder)
                  if n.endswith(".json") and n != "en.json")


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("lang", _languages())
def test_the_description_is_not_english(lang, key):
    en = {"d": _issues("en")[key]["description"]}
    other = {"d": _issues(lang)[key]["description"]}
    assert not _copied_prose(en, other), f"{lang}.{key} copies English"
    assert not _english_sentences(other), f"{lang}.{key} has English sentences"


@pytest.mark.parametrize("key", KEYS)
def test_the_rule_flags_english_with_translated_setting_names(key):
    english = _issues("en")[key]["description"]
    fake = english.replace("**Grid power**", "**Netzleistung**").replace(
        "**Sensor sources**", "**Sensorquellen**")
    assert _copied_prose({"d": english}, {"d": fake}) == ["d"]
