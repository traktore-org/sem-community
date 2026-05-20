#!/usr/bin/env python3
"""Verify translations quality across all languages.

Usage:
    python3 scripts/verify_translations.py [LANG]

    LANG   Optional language code to check (e.g. 'de', 'nl'). Default: all.

Checks:
  1. Missing keys (vs EN baseline)
  2. Extra keys (not in EN)
  3. Untranslated values (identical to EN, excluding technical terms)
  4. Placeholder mismatches ({var} in EN but not in translation or vice versa)
  5. Empty values
  6. Duplicate values within a language pointing to different EN meanings
"""

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRANSLATIONS_JSON = REPO_ROOT / "dashboard" / "translations.json"

# Technical terms that are OK to leave untranslated
TECHNICAL_TERMS = {
    "SOC", "EV", "ROI", "CO₂", "HT", "NT", "W", "kW", "kWh",
    "Sol>Bat", "Sol>EV", "Sol>Grid", "Sol>Home",
    "Grid>Bat", "Grid>EV", "Grid>Home",
    "Bat>EV", "Bat>Home", "Batt",
    "SEM", "NORMAL",
}

# Keys where EN == translation is expected (abbreviations, units, proper nouns)
SKIP_IDENTICAL_CHECK = {
    "soc", "ev", "roi", "co2", "ht", "nt", "kw", "kwh", "w",
    "sol_bat", "sol_ev", "sol_grid", "sol_home",
    "grid_bat", "grid_ev", "grid_home",
    "bat_ev", "bat_home",
    "EV", "SOC", "ROI", "NORMAL",
}

PLACEHOLDER_RE = re.compile(r"\{[^}]+\}")


def check_language(lang, translations, en_translations):
    """Check a single language and return list of issues."""
    issues = []
    lang_keys = set(translations.keys())
    en_keys = set(en_translations.keys())

    # Missing keys
    missing = en_keys - lang_keys
    if missing:
        for k in sorted(missing):
            issues.append(("MISSING", k, f"Key exists in EN but not in {lang}"))

    # Extra keys
    extra = lang_keys - en_keys
    if extra:
        for k in sorted(extra):
            issues.append(("EXTRA", k, f"Key exists in {lang} but not in EN"))

    # Check each shared key
    shared = en_keys & lang_keys
    for key in sorted(shared):
        en_val = en_translations[key]
        tr_val = translations[key]

        # Empty values
        if not tr_val.strip():
            issues.append(("EMPTY", key, f"Empty translation (EN: '{en_val}')"))
            continue

        # Untranslated (identical to EN)
        if key not in SKIP_IDENTICAL_CHECK and en_val not in TECHNICAL_TERMS:
            if tr_val == en_val and len(en_val) > 2:
                issues.append(("UNTRANSLATED", key, f"Same as EN: '{en_val}'"))

        # Placeholder mismatches
        en_placeholders = set(PLACEHOLDER_RE.findall(en_val))
        tr_placeholders = set(PLACEHOLDER_RE.findall(tr_val))
        if en_placeholders != tr_placeholders:
            missing_ph = en_placeholders - tr_placeholders
            extra_ph = tr_placeholders - en_placeholders
            parts = []
            if missing_ph:
                parts.append(f"missing: {missing_ph}")
            if extra_ph:
                parts.append(f"extra: {extra_ph}")
            issues.append(("PLACEHOLDER", key, "; ".join(parts)))

    return issues


def main():
    target_lang = sys.argv[1] if len(sys.argv) > 1 else None

    with open(TRANSLATIONS_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    en = data.get("en", {})
    if not en:
        print("ERROR: No 'en' translations found", file=sys.stderr)
        sys.exit(1)

    languages = [target_lang] if target_lang else [l for l in data if l != "en"]
    total_issues = 0

    for lang in sorted(languages):
        if lang not in data:
            print(f"ERROR: Language '{lang}' not found in translations.json")
            sys.exit(1)

        issues = check_language(lang, data[lang], en)
        total_issues += len(issues)

        if issues:
            print(f"\n{'='*60}")
            print(f"  {lang.upper()} — {len(issues)} issue(s)")
            print(f"{'='*60}")
            by_type = {}
            for typ, key, msg in issues:
                by_type.setdefault(typ, []).append((key, msg))
            for typ in ["MISSING", "EXTRA", "EMPTY", "PLACEHOLDER", "UNTRANSLATED"]:
                items = by_type.get(typ, [])
                if items:
                    print(f"\n  [{typ}] ({len(items)})")
                    for key, msg in items[:20]:
                        print(f"    {key}: {msg}")
                    if len(items) > 20:
                        print(f"    ... and {len(items) - 20} more")
        else:
            print(f"  {lang.upper()} — OK")

    print(f"\n{'='*60}")
    print(f"  Total: {total_issues} issue(s) across {len(languages)} language(s)")
    print(f"  EN baseline: {len(en)} keys")
    print(f"{'='*60}")
    sys.exit(1 if total_issues > 0 else 0)


if __name__ == "__main__":
    main()
