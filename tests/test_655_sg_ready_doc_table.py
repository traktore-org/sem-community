"""#655 — the SG-Ready relay table in the docs must match the code.

``docs/SETUP_GUIDE.md`` carried the pre-#523 mapping for months after the
code was corrected: a plain 2-bit count (Blocked 0:0, Normal 0:1, Boost 1:0,
ForceOn 1:1) instead of the SG-Ready standard the pumps actually implement.

That is not a cosmetic drift. An installer verifying the wiring against the
guide sees SEM command Boost and relay 2 close, reads "Boost = relay 1", and
concludes the install is inverted — so they turn on ``invert_sg_ready``,
which inverts a *correct* install and drives Boost as (1,0). A standard heat
pump reads (1,0) as EVU-block. The pump then switches OFF on solar surplus:
exactly the #523 bug (RienduPre, Nibe), reintroduced by the documentation,
on real hardware, with the code perfectly correct.

Docs are part of the control path when the user is the actuator. So this
parses the shipped table and compares it row-by-row against
``SG_READY_RELAY_MAP``. Following the guide and following the code must give
the same relay states.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from custom_components.solar_energy_management.devices.heat_pump_controller import (
    SG_READY_RELAY_MAP,
    SGReadyState,
)

_GUIDE = pathlib.Path(__file__).resolve().parent.parent / "docs" / "SETUP_GUIDE.md"

# Table label → the state it documents. The labels are user-facing prose
# ("1 — Blocked"), so match on the state word rather than the number.
_LABELS = {
    "blocked": SGReadyState.BLOCKED,
    "normal": SGReadyState.NORMAL,
    "boost": SGReadyState.BOOST,
    "force on": SGReadyState.FORCE_ON,
}


def _cell_is_on(cell: str) -> bool:
    """``**On**`` / ``On`` → True, ``Off`` → False."""
    word = cell.replace("*", "").strip().lower()
    if word == "on":
        return True
    if word == "off":
        return False
    raise AssertionError(f"relay cell is neither On nor Off: {cell!r}")


def _documented_map() -> dict[SGReadyState, tuple[bool, bool]]:
    """Parse the SG-Ready table out of SETUP_GUIDE.md."""
    out: dict[SGReadyState, tuple[bool, bool]] = {}
    for line in _GUIDE.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 4:
            continue
        label = re.sub(r"^\s*\d+\s*[—-]\s*", "", cells[0]).strip().lower()
        state = _LABELS.get(label)
        if state is None:
            continue
        out[state] = (_cell_is_on(cells[1]), _cell_is_on(cells[2]))
    return out


@pytest.mark.unit
class TestSGReadyDocTableMatchesCode655:

    def test_the_guide_documents_all_four_states(self):
        documented = _documented_map()
        missing = sorted(s.name for s in SG_READY_RELAY_MAP if s not in documented)
        assert not missing, (
            "the SG-Ready table in docs/SETUP_GUIDE.md no longer documents "
            f"these states — the parser found {sorted(s.name for s in documented)}. "
            "Either the table moved/changed shape (fix this test) or a state "
            f"was dropped from the docs (fix the guide): {missing}"
        )

    @pytest.mark.parametrize("state", list(SG_READY_RELAY_MAP))
    def test_each_row_matches_the_relay_map(self, state):
        documented = _documented_map()[state]
        expected = SG_READY_RELAY_MAP[state]
        assert documented == expected, (
            f"docs/SETUP_GUIDE.md documents {state.name} as "
            f"relay1={documented[0]}, relay2={documented[1]} but "
            f"SG_READY_RELAY_MAP drives relay1={expected[0]}, "
            f"relay2={expected[1]}. An installer trusting the guide will "
            "conclude their wiring is inverted and enable invert_sg_ready on "
            "a correct install — which is the #523 EVU-block-on-surplus bug. "
            "Fix whichever one is wrong; they may not disagree."
        )

    def test_the_guide_warns_it_is_not_a_binary_count(self):
        """The trap that produced #523 is that the states look like they
        should count 00/01/10/11 and don't. Keep saying so out loud."""
        text = _GUIDE.read_text(encoding="utf-8").lower()
        assert "not a 2-bit count" in text, (
            "the SETUP_GUIDE no longer warns that SG-Ready state order is not "
            "a binary count — that assumption is what produced the wrong map "
            "in the first place (#523)"
        )
