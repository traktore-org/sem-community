"""Contract lint (#543): every user-facing NUMBER knob must have a config reader.

A `NumberEntityDescription` in ``number.py`` publishes a slider the user can
move. If no code ever reads that config key, the slider is a **dead stepper** —
the user sets a value that does nothing (exactly the class the 2026-06-25 wiring
census burned down: ``maximum_grid_import``, ``battery_resume_soc``,
``battery_minimum_soc``, ``battery_assist_floor_soc`` …).

This test fails CI the moment a NUMBER knob is added (or left) without a reader,
so the dead-stepper class can't regrow silently.

A knob counts as *wired* if its config key is read anywhere in the package via a
config-access pattern (``.get("key")`` / ``["key"]``) outside the pure
definition/UI surface (``number.py`` defines it, ``config_flow.py`` seeds it).
"""
from __future__ import annotations

import re
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent

# Files that DEFINE/seed knobs rather than READ them — references here don't
# count as a reader.
_DEFINITION_FILES = {"number.py", "config_flow.py"}

# Knobs intentionally without a runtime config reader (document the why here so
# a reviewer must justify each entry). Empty today — every knob is wired.
_ALLOWLIST: set[str] = set()


def _config_key_map() -> dict[str, str]:
    """Parse number.py's CONFIG_KEY_MAP (entity key → stored config key).

    Some knobs persist under a different config key than their entity key
    (e.g. ``battery_capacity`` → ``battery_capacity_kwh``, legionella →
    ``hot_water_legionella_*``). The reader check must follow the same map
    the read/write path uses, else it false-flags a wired knob as dead.
    """
    src = (PKG / "number.py").read_text()
    m = re.search(r"CONFIG_KEY_MAP\s*=\s*\{(.*?)\}", src, re.DOTALL)
    if not m:
        return {}
    return dict(re.findall(r'"([^"]+)"\s*:\s*"([^"]+)"', m.group(1)))


def _number_type_keys() -> list[str]:
    block = (PKG / "number.py").read_text()
    block = block[block.index("NUMBER_TYPES = ["):]
    keys, seen = [], set()
    for k in re.findall(r'key="([^"]+)"', block):
        if k not in seen:
            seen.add(k)
            keys.append(k)
    return keys


def _all_reader_text() -> str:
    out = []
    for p in PKG.rglob("*.py"):
        rel = p.relative_to(PKG)
        if rel.parts[0] in {"tests", "node_modules"}:
            continue
        if p.name in _DEFINITION_FILES:
            continue
        out.append(p.read_text())
    return "\n".join(out)


def test_every_number_knob_has_a_config_reader():
    keys = _number_type_keys()
    assert keys, "NUMBER_TYPES parse produced no keys — test wiring broke"

    key_map = _config_key_map()
    readers = _all_reader_text()
    dead = []
    for k in keys:
        if k in _ALLOWLIST:
            continue
        # Follow the entity-key → stored-config-key map (number.py) before
        # checking for a reader — a mapped knob is read under its target key.
        config_key = key_map.get(k, k)
        # config-read patterns: .get("k") / .get('k') / ["k"] / ['k']
        pat = rf'''\.get\(\s*["']{re.escape(config_key)}["']|\[\s*["']{re.escape(config_key)}["']\s*\]'''
        if not re.search(pat, readers):
            dead.append(f"{k} (config key: {config_key})" if config_key != k else k)

    assert not dead, (
        "Dead stepper(s) — NUMBER knob with no config reader anywhere in the "
        f"package (user sets a no-op): {dead}. Either wire the key to a reader, "
        "remove the slider, or (with justification) add it to _ALLOWLIST."
    )
