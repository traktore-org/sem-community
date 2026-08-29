"""Card sources may not index a module-level array out of its range.

Found live on .175 while photographing the #778 floor marker: the SOC Zones
card read ``ZONES[3].entity`` from a THREE-element array, so ``render()`` threw
``TypeError: Cannot read properties of undefined (reading 'entity')`` on every
single pass. The card has never displayed. It shipped that way in commit
52266507 and has been in every 2.0 beta since.

Why nothing caught it: a card that throws inside ``render()`` does not break
the page — Lit swallows it, the element simply stays empty, and the dashboard
around it looks completely normal. There is no red error card, no failing test
(the suite never renders a card), and nothing in the logs a user would read.
The only symptom is a card that is not there, which reads as "not configured".

That is also how the #778 floor marker could be built, deployed and reviewed
without anyone noticing it could never appear: it lives inside the dead card.

This lint is deliberately narrow — a constant integer index into a
module-level array literal, checked against that literal's length. It cannot
catch computed indices, and it does not try; it catches the mistake that
actually happened.
"""

import re
from pathlib import Path

import pytest

CARDS = Path(__file__).resolve().parent.parent / "dashboard" / "card" / "src"

_ARRAY = re.compile(
    r"^const\s+([A-Z][A-Z0-9_]*)\s*=\s*\[(.*?)^\];", re.MULTILINE | re.DOTALL)
_INDEX = re.compile(r"\b([A-Z][A-Z0-9_]*)\[(\d+)\]")


def _top_level_entries(body: str) -> int:
    """Count entries in an array literal, ignoring nesting and strings."""
    depth = 0
    count = 1 if body.strip() else 0
    in_str = None
    prev = ""
    for ch in body:
        if in_str:
            if ch == in_str and prev != "\\":
                in_str = None
        elif ch in "\"'`":
            in_str = ch
        elif ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
        elif ch == "," and depth == 0:
            count += 1
        prev = ch
    return count


def _sources():
    return sorted(CARDS.rglob("*.js"))


@pytest.mark.parametrize("path", _sources(), ids=lambda p: p.name)
def test_no_constant_index_past_the_end(path):
    src = path.read_text(encoding="utf-8")
    sizes = {}
    for m in _ARRAY.finditer(src):
        name, body = m.group(1), m.group(2)
        # trailing comma after the last entry would over-count
        n = _top_level_entries(body.rstrip().rstrip(","))
        sizes[name] = n

    bad = []
    for m in _INDEX.finditer(src):
        name, idx = m.group(1), int(m.group(2))
        if name in sizes and idx >= sizes[name]:
            line = src[:m.start()].count("\n") + 1
            bad.append(f"{path.name}:{line} {name}[{idx}] but {name} has "
                       f"{sizes[name]} entries")
    assert not bad, (
        "a card indexes past the end of a constant array — render() throws and "
        "the card silently never appears: " + "; ".join(bad))


def test_the_lint_can_see_the_bug_it_was_written_for():
    """Guard the guard. A lint whose regexes stop matching becomes a test that
    passes because it checks nothing — and this one is checking source text,
    which is exactly where that rot happens."""
    sample = "const ZONES = [\n  { id: 'a' },\n  { id: 'b' },\n  { id: 'c' },\n];\n" \
             "const x = this._state(ZONES[3].entity);\n"
    sizes = {m.group(1): _top_level_entries(m.group(2).rstrip().rstrip(","))
             for m in _ARRAY.finditer(sample)}
    assert sizes.get("ZONES") == 3, sizes
    hits = [(m.group(1), int(m.group(2))) for m in _INDEX.finditer(sample)
            if m.group(1) in sizes and int(m.group(2)) >= sizes[m.group(1)]]
    assert hits == [("ZONES", 3)]
