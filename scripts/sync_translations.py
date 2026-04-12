#!/usr/bin/env python3
"""Sync entity translations from en.json to all other locale files.

Entity names must be identical across locales to produce consistent
entity_ids regardless of HA language setting. This script copies
the 'entity' section from en.json to de.json (and any other locales).

Run: python scripts/sync_translations.py
"""
import json
import sys
from pathlib import Path

translations_dir = Path(__file__).parent.parent / "translations"
en_path = translations_dir / "en.json"

if not en_path.exists():
    print(f"ERROR: {en_path} not found")
    sys.exit(1)

with open(en_path, encoding="utf-8") as f:
    en = json.load(f)

en_entity = en.get("entity", {})
synced = 0
errors = 0

for locale_path in translations_dir.glob("*.json"):
    if locale_path.name == "en.json":
        continue

    with open(locale_path, encoding="utf-8") as f:
        locale = json.load(f)

    old_entity = locale.get("entity", {})
    locale["entity"] = en_entity

    with open(locale_path, "w", encoding="utf-8") as f:
        json.dump(locale, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Report changes
    for entity_type in en_entity:
        old_keys = set(old_entity.get(entity_type, {}).keys())
        new_keys = set(en_entity.get(entity_type, {}).keys())
        added = new_keys - old_keys
        if added:
            print(f"  {locale_path.name}: +{len(added)} {entity_type}: {', '.join(sorted(added))}")

    synced += 1

print(f"Synced entity translations to {synced} locale(s)")
