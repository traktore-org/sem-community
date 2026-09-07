"""(#925) The source-string guard ledger only ever shrinks.

121 assertions across 97 of SEM's 589 test files pin a structural fact by
searching source TEXT::

    src = inspect.getsource(SEMCoordinator._shadow_energy_plan)
    assert "export_rate=" in src

That is the shape that let #924 live for a month. It is coupled to the
SPELLING of the code rather than to the code, so it cannot tell you
whether the call is reached, whether siblings elsewhere lack it, whether a
rename quietly broke it, or whether the string it found was in a comment.

They are not all wrong. Pinning that a user-visible log line, an
annotation, or a comment exists is a genuine use — the thing being checked
really IS text. So this is a RATCHET, not a ban: the count may fall and
must never rise. A new one means either converting an old one first, or
making a deliberate case for it.

``tests/ast_contracts.py`` is the replacement, and it exists precisely so
this is a fair ask: the sound form is now one line too, where before it
was thirty and lost every time.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
BASELINE = TESTS / "source_string_guard_baseline.json"

#: `assert <anything> in src` / `in source` — the family, not one spelling.
PATTERN = re.compile(r"assert\s+[^\n=]*\bin\s+(src|source|_src)\b")


def _count() -> dict:
    per_file = {}
    for p in sorted(TESTS.glob("test_*.py")):
        n = len(PATTERN.findall(p.read_text(encoding="utf-8")))
        if n:
            per_file[p.name] = n
    return per_file


class TestTheLedgerShrinks:

    def test_no_new_source_string_guards(self):
        current = _count()
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        base_files = baseline["per_file"]

        grew = {f: (base_files.get(f, 0), n) for f, n in current.items()
                if n > base_files.get(f, 0)}
        assert not grew, (
            "new source-string guard(s) — each is a check coupled to the "
            "SPELLING of the code, not the code, and that is the #924 defect:"
            + "".join(f"\n  {f}: {was} -> {now}" for f, (was, now) in grew.items())
            + "\n\nUse tests/ast_contracts.py instead — calls(), call_kwargs(), "
              "reads_attribute(), call_sites(). If the thing you are pinning "
              "genuinely IS text (a log line a user reads, a comment, an "
              "annotation), say so in the test and raise the baseline "
              "deliberately with tests/regen_source_string_baseline.py."
        )

    def test_the_total_never_rises(self):
        current = _count()
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        total = sum(current.values())
        assert total <= baseline["total"], (
            f"source-string guards rose {baseline['total']} -> {total}. "
            "The ledger only shrinks.")

    def test_the_ratchet_is_measuring_something(self):
        """A ratchet over an empty set holds forever and means nothing —
        the same vacuity this arc is about. If the pattern stops matching
        because the idiom changed, this fails loudly rather than passing."""
        current = _count()
        assert sum(current.values()) > 0, (
            "the source-string pattern matches nothing at all — either "
            "every one was converted (delete this ratchet and celebrate) "
            "or the regex no longer matches the idiom in use")
