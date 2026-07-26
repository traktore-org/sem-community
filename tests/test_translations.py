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


# Translation keys set at runtime rather than taken from an entity
# description's ``key``, which the static scan above cannot see.
#
# ``select.SEMPerChargerSelect`` does ``_attr_translation_key = config_key``
# and the call sites pass the bare config key while the *description* key is
# ``charger_<id>_…`` — so these two are live for every per-charger install and
# must not read as orphaned.
_DYNAMIC_TRANSLATION_KEYS = {
    ("select", "ev_target_type"),
    ("select", "charge_mode"),
}


def test_no_orphaned_translations():
    """Every entity translation key must belong to an entity that exists.

    The old form of this test allowed up to ten orphans ("keys used by other
    systems") and failed only above that. Nothing was using them: the allowance
    was carrying ten dead ``entity.number.*`` keys — ``ev_target_soc``,
    ``daily_ev_target``, ``ev_phases`` and friends, global entities until #255
    made them per-charger — in all 17 files, 170 strings every translator paid
    for and no user could ever see (#676).

    A tolerance on a correctness check is the same shape as the bug it hides:
    it reads as covered. So the threshold is zero, and the two genuinely
    dynamic keys are named above rather than absorbed into a budget.
    """
    keys = _extract_entity_keys()
    valid_keys = {(domain, key) for domain, key in keys} | _DYNAMIC_TRANSLATION_KEYS

    with open(_path("strings.json")) as f:
        strings = json.load(f)

    orphaned = []
    for domain in ["sensor", "number", "switch", "binary_sensor", "select"]:
        section = strings.get("entity", {}).get(domain, {})
        for key in section:
            if (domain, key) not in valid_keys:
                orphaned.append(f"{domain}.{key}")

    assert not orphaned, (
        f"{len(orphaned)} orphaned entity translations in strings.json — no "
        f"entity description carries these keys, so HA never looks them up:\n"
        + "\n".join(f"  {o}" for o in sorted(orphaned))
        + "\n\nDelete them, or — if the entity sets its translation_key at "
        "runtime — add it to _DYNAMIC_TRANSLATION_KEYS with the reason (#676)."
    )


def test_the_orphan_rule_can_actually_fire():
    """Bug class 8: the scan must find real entity keys, and the exemption
    list must be a short named set rather than a silent catch-all."""
    keys = _extract_entity_keys()
    assert len(keys) > 100, f"only {len(keys)} entity keys found — the scan broke"
    assert ("number", "battery_capacity") in keys, "known-live key went missing"
    assert ("number", "ev_target_soc") not in keys, (
        "ev_target_soc is a real entity key again — remove it from the #676 "
        "deletion instead of keeping this assertion"
    )
    assert len(_DYNAMIC_TRANSLATION_KEYS) < 5, (
        "the runtime-key exemption list is growing into the tolerance this "
        "test just removed — verify each entry against the code"
    )
