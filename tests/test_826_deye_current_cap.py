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
    """The NumberSelectorConfig bounds for one options-flow FIELD.

    Anchored on the ``vol.Optional("<key>"`` declaration on purpose: these
    keys also appear in plain key lists (OPTIONS_FLOW_OWNED_KEYS, the Deye
    copy-through loop) two thousand lines earlier, and a lazy search from
    the first mention happily reads a completely different field's bounds —
    which it did, and made this test pass while the bug was still there.
    """
    src = CONFIG_FLOW.read_text()
    m = re.search(
        r'vol\.Optional\(\s*\n\s*"' + re.escape(key) + r'"'
        r'.*?NumberSelectorConfig\(\s*\n?(.*?)\)',
        src, re.S)
    assert m, f"no vol.Optional field declaration found for {key}"
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
