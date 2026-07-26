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


def _runtime_translation_keys():
    """Keys assigned at runtime rather than read off a description's ``key``.

    The per-charger entities set ``_attr_translation_key = config_key`` while
    their description key carries the charger id, so the ``key="…"`` scan above
    cannot see them. #676 handled that with a two-entry exemption set; #677
    added nine more, at which point the exemption set *was* the hand-maintained
    mirror of a growing structure that bug class 24 is about. So it derives
    them from the source instead — one derivation, shared with the #677 guard.
    """
    # Relative, not ``from tests.…``: CI copies the tree to
    # custom_components/solar_energy_management/, so the absolute form
    # resolves locally and ModuleNotFoundErrors in CI (the #671 lesson).
    from .test_677_per_charger_names import per_charger_translation_keys

    return {
        (domain, key)
        for domain, names in per_charger_translation_keys().items()
        for key in names
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
    it reads as covered. So the threshold is zero, and the genuinely dynamic
    keys are *derived* from the source rather than absorbed into a budget.
    """
    keys = _extract_entity_keys()
    valid_keys = {(domain, key) for domain, key in keys} | _runtime_translation_keys()

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
        "runtime — make _runtime_translation_keys() derive it (#676, #677)."
    )


def test_the_orphan_rule_can_actually_fire():
    """Bug class 8: both scans must find real keys, and the runtime set must
    be derived from the source rather than hand-listed."""
    keys = _extract_entity_keys()
    assert len(keys) > 100, f"only {len(keys)} entity keys found — the scan broke"
    assert ("number", "battery_capacity") in keys, "known-live key went missing"

    runtime = _runtime_translation_keys()
    assert len(runtime) >= 11, (
        f"only {len(runtime)} runtime keys derived — the per-charger "
        "derivation broke, which would silently re-open #676"
    )
    assert ("select", "charge_mode") in runtime
    assert ("number", "ev_target_soc") in runtime, (
        "ev_target_soc is a per-charger runtime key (#677); if it went global "
        "again, the {charger} placeholder in its name will raise"
    )
    assert not (keys.keys() & runtime), (
        "a key is claimed both by a global entity description and by the "
        "per-charger derivation — see TestNoStaleGlobalKeys677"
    )
