"""#826 — SEM's own write ceiling must not be narrower than the ceiling it sits under.

@ab-elco-clal, running a Deye 12 kW hybrid, could not set "Maks. ladestrøm (A)"
above 100: *"Value X.0 is too large"*, with no way to raise it.

The two fields are a pair, and they disagreed:

    deye_max_charge_current_a       min=1  max=100   <- SEM's write ceiling
    deye_bms_max_charge_current_a   min=0  max=200   <- the BMS ceiling it must respect

SEM's ceiling is bounded BY the BMS ceiling, so it can never sensibly be the
lower of the two — a user who tells SEM the BMS allows 150 A cannot then tell
SEM it may write 150 A. Same bug class as #717 (peak sliders capped at 15 kW
on an 80 kW service), #746 (every EVSE ceilinged at 32 A) and #813 (options
pages rejecting their own stored values): a field narrower than the thing it
describes.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

CONFIG_FLOW = Path(__file__).resolve().parent.parent / "config_flow.py"


def _number_bounds(key: str) -> dict:
    """The bounds for one options-flow field.

    Reads `consts/bounds.py` first: since #828 these two fields are declared
    there ONCE and the flow builds its selector from it, so the table IS the
    declaration and there are no literals left to scan. Falls back to the
    flow's own literals for fields not yet migrated.

    The fallback stays anchored on the ``vol.Optional("<key>"`` declaration:
    these keys also appear in OPTIONS_FLOW_OWNED_KEYS and copy-through loops
    thousands of lines earlier, and searching from the first mention reads a
    different field's bounds — which is how this test's first version PASSED
    against the live bug.
    """
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "bounds", CONFIG_FLOW.parent / "consts" / "bounds.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bounds"] = mod
    spec.loader.exec_module(mod)
    if key in mod.BOUNDS:
        r = mod.BOUNDS[key]
        return {"min": float(r.min), "max": float(r.max)}

    src = CONFIG_FLOW.read_text()
    m = re.search(
        r'vol\.Optional\(\s*\n\s*"' + re.escape(key) + r'"'
        r'.*?NumberSelectorConfig\(\s*\n?(.*?)\)',
        src, re.S)
    assert m, f"no declaration found for {key} in the table or the flow"
    body = m.group(1)
    out = {}
    for name in ("min", "max"):
        mm = re.search(rf"\b{name}=([0-9.]+)", body)
        if mm:
            out[name] = float(mm.group(1))
    return out


@pytest.mark.unit
class TestTheWriteCeilingReachesTheBmsCeiling:

    def test_both_fields_exist(self):
        assert _number_bounds("deye_max_charge_current_a")
        assert _number_bounds("deye_bms_max_charge_current_a")

    def test_sem_may_be_told_to_write_up_to_the_bms_ceiling(self):
        """The reporter's exact complaint: 150 A is a legitimate value on a
        big Deye pack and the field refused it."""
        sem = _number_bounds("deye_max_charge_current_a")
        bms = _number_bounds("deye_bms_max_charge_current_a")
        assert sem["max"] >= bms["max"], (
            f"SEM's write ceiling caps at {sem['max']} A while the BMS ceiling "
            f"field allows {bms['max']} A — a user can describe a battery SEM "
            "is then forbidden to drive"
        )

    def test_the_floor_is_unchanged(self):
        """Raising a ceiling must not quietly move the floor: 1 A is the
        documented minimum write."""
        assert _number_bounds("deye_max_charge_current_a")["min"] == 1
