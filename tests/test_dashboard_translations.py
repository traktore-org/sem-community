"""Dashboard translation parity guard (#539 review follow-up).

``dashboard/translations.json`` is the single source of truth for the
``semLocalize()`` runtime translations used by the custom cards. The
HA-entity-string guard (``test_translations.py``) only covers
``translations/*.json`` — it does NOT see this file. Without this test a
key added only to ``en`` (the common path) silently falls back to English
for every other locale, which is how ~35 keys drifted before stable.

This pins: every language present in ``dashboard/translations.json`` must
carry every key that ``en`` has.
"""
import json
import os

_COMPONENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TRANSLATIONS = os.path.join(_COMPONENT_DIR, "dashboard", "translations.json")


def test_dashboard_translations_have_full_parity_with_en():
    with open(_TRANSLATIONS, encoding="utf-8") as f:
        data = json.load(f)

    assert "en" in data, "dashboard/translations.json must have an 'en' base"
    assert len(data) >= 15, f"expected 15+ languages, found {len(data)}"

    en_keys = set(data["en"])
    missing = {}
    for lang, strings in data.items():
        if lang == "en":
            continue
        gap = [k for k in en_keys if k not in strings]
        if gap:
            missing[lang] = gap

    if missing:
        report = "\n".join(
            f"  {lang}: {len(keys)} missing — {keys[:5]}..."
            for lang, keys in sorted(missing.items())
        )
        raise AssertionError(
            f"{len(missing)} dashboard language(s) missing keys present in 'en':\n"
            + report
        )


def test_dashboard_translations_no_empty_values():
    """No blank/whitespace-only translation values (a common copy/paste slip)."""
    with open(_TRANSLATIONS, encoding="utf-8") as f:
        data = json.load(f)
    blanks = [
        f"{lang}.{k}"
        for lang, strings in data.items()
        for k, v in strings.items()
        if not isinstance(v, str) or not v.strip()
    ]
    assert not blanks, f"blank dashboard translation values: {blanks[:10]}"
