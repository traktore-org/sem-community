"""Test that ALL entity keys have translations in ALL language files.

This test prevents the Growatt entity naming bug where missing translations
caused HA to generate wrong entity_ids on non-English installs (e.g.
sensor.sem → sensor.sem_energie on German HA).

Every entity key in sensor.py, number.py, switch.py, binary_sensor.py,
and select.py MUST have a translation in strings.json AND every
translations/*.json file.
"""
import json
import os
import re
import glob
import pytest

# Resolve paths relative to the component root (parent of tests/)
_COMPONENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _path(filename):
    return os.path.join(_COMPONENT_DIR, filename)


def _extract_entity_keys():
    """Extract all entity keys from platform files."""
    keys = {}

    for fname, list_pattern in [
        ("sensor.py", "SENSOR_TYPES"),
        ("number.py", "NUMBER_TYPES"),
    ]:
        with open(_path(fname)) as f:
            content = f.read()
        start = content.find(f"{list_pattern} = [")
        if start < 0:
            continue
        end = content.find("\n]", start) + 2
        domain = "sensor" if "sensor" in fname else "number"
        for key in re.findall(r'key="([^"]+)"', content[start:end]):
            keys[(domain, key)] = fname

    for fname in ["switch.py", "binary_sensor.py", "select.py"]:
        with open(_path(fname)) as f:
            content = f.read()
        domain = fname.replace(".py", "")
        for key in re.findall(r'key="([^"]+)"', content):
            keys[(domain, key)] = fname

    return keys


def test_strings_json_has_all_keys():
    """strings.json must have translations for every entity key."""
    keys = _extract_entity_keys()
    with open(_path("strings.json")) as f:
        strings = json.load(f)

    missing = []
    for (domain, key), source in keys.items():
        section = strings.get("entity", {}).get(domain, {})
        if key not in section:
            missing.append(f"{domain}.{key} (from {source})")

    assert not missing, (
        f"{len(missing)} entity keys missing from strings.json:\n"
        + "\n".join(f"  {m}" for m in sorted(missing))
    )


def test_all_languages_have_all_keys():
    """Every translations/*.json must have translations for every entity key."""
    keys = _extract_entity_keys()
    lang_files = sorted(glob.glob(os.path.join(_COMPONENT_DIR, "translations", "*.json")))

    assert len(lang_files) >= 15, f"Expected 15+ language files, found {len(lang_files)}"

    all_missing = {}
    for lang_file in lang_files:
        lang = lang_file.split("/")[-1].replace(".json", "")
        with open(lang_file) as f:
            trans = json.load(f)

        missing = []
        for (domain, key), source in keys.items():
            section = trans.get("entity", {}).get(domain, {})
            if key not in section:
                missing.append(f"{domain}.{key}")

        if missing:
            all_missing[lang] = missing

    if all_missing:
        report = []
        for lang, keys_list in sorted(all_missing.items()):
            report.append(f"  {lang}: {len(keys_list)} missing — {keys_list[:3]}...")
        pytest.fail(
            f"Missing translations in {len(all_missing)} language(s):\n"
            + "\n".join(report)
        )


def test_no_orphaned_translations():
    """Translation keys should correspond to actual entity keys (no stale translations)."""
    keys = _extract_entity_keys()
    valid_keys = {(domain, key) for domain, key in keys}

    with open(_path("strings.json")) as f:
        strings = json.load(f)

    orphaned = []
    for domain in ["sensor", "number", "switch", "binary_sensor", "select"]:
        section = strings.get("entity", {}).get(domain, {})
        for key in section:
            if (domain, key) not in valid_keys:
                orphaned.append(f"{domain}.{key}")

    # Allow some orphans (keys used by other systems)
    # but warn if there are many
    if len(orphaned) > 10:
        pytest.fail(
            f"{len(orphaned)} orphaned translations in strings.json "
            f"(keys without matching entity descriptions):\n"
            + "\n".join(f"  {o}" for o in sorted(orphaned)[:20])
        )
