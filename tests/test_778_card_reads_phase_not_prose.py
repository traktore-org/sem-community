"""#778 phase 6 — the card decides on the token, never on the prose.

``why`` / ``refill_why`` are sentences written for a person, and they are
rendered in sixteen languages. A card that decided WHAT to render by matching
their contents would break the first time one was reworded, and would already
be broken today in fifteen of those languages. The published ``phase`` token
exists precisely so the decision and the display are different things.

This is a shrink-only ratchet in the house style: the source of truth is what
the card files actually contain, and the assertion is that no comparison ever
reads the prose.
"""

import re
from pathlib import Path

import pytest

CARDS = Path(__file__).resolve().parent.parent / "dashboard" / "card" / "src"

# Attributes that carry human prose. Displaying them is the whole point;
# BRANCHING on them is the defect.
PROSE_ATTRS = ("why", "refill_why", "battery_spendable_reason",
               "battery_capacity_reason", "battery_refill_reason")

# A comparison or membership test against a prose attribute, in any of the
# spellings JS offers: a.why === '...', a.why.includes(...), a.why.startsWith,
# a.why.match, switch (a.why).
_COMPARISON = re.compile(
    r"""(?:\.|\[['"])(?P<attr>%s)(?:['"]\])?          # the prose attribute
        \s*
        (?:                                            # followed by...
            ={2,3}|!={1,2}                             #   a comparison
          | \.\s*(?:includes|startsWith|endsWith|match|search|indexOf|test)\b
        )""" % "|".join(PROSE_ATTRS),
    re.VERBOSE,
)


def _card_sources():
    return sorted(CARDS.rglob("*.js"))


@pytest.mark.parametrize("path", _card_sources(), ids=lambda p: p.name)
def test_no_card_branches_on_a_reason_string(path):
    src = path.read_text(encoding="utf-8")
    hits = [m.group(0) for m in _COMPARISON.finditer(src)]
    assert not hits, (
        f"{path.name} decides what to render by matching a translated reason "
        f"string: {hits}. Switch on the published token instead (the "
        f"``phase`` attribute on battery_spendable_kwh) and DISPLAY the prose."
    )


def test_the_battery_card_does_switch_on_the_token():
    """The inverse pin. Without this the rule above is satisfied by a card
    that reads neither — which is how the states became indistinguishable in
    the first place."""
    src = (CARDS / "cards" / "sem-battery-card.js").read_text(encoding="utf-8")
    assert "a.phase" in src or "attrs.phase" in src, (
        "the battery card no longer reads the published phase token")
    assert "planning_phase_" in src, (
        "the phase pill no longer resolves a per-phase translation key")


def test_the_zones_card_gates_the_floor_on_the_token():
    """A dynamic-floor marker drawn while the budget is still learning would
    claim a floor SEM has not computed."""
    src = (CARDS / "cards" / "sem-battery-zones-card.js").read_text(encoding="utf-8")
    assert "phase !== 'spending'" in src, (
        "the zones card no longer gates tonight's floor on the spending phase")
