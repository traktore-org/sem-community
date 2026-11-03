"""(#998) The ledger of unproven causal claims only ever shrinks.

Bug class 99 is *a verdict naming a cause its own scope refutes*. #992 swept
it by reading — three passes, nine files, twelve fixes — and then a reviewer
found two more INSIDE those fixes, and a thirteenth turned up minutes after
the merge in a file the sweep never opened. That is not a failure of care.
It is what reading nine files out of twenty-four gets you.

So this is a RATCHET, not a ban. A reason that merely describes the decision
needs nothing. A reason that asserts something about the WORLD is a claim,
and a claim carries ``# CAUSE:`` naming the state in that scope which proves
it. Writing the annotation is the work: it is what surfaces the ones that
cannot be written.

The worked example is the one this mechanism was built beside. The charger
hold said ``inputs degraded (sensor unavailable)``. Try to annotate it and
you cannot: the flag behind it is raised by three different gates, and two
of them are sensors that answered perfectly well with a number SEM chose to
disbelieve. The annotation fails, so the string changes — it names the read
that actually went dark.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from .causal_claims import ANNOTATION, claims

from .ratchet_guard import assert_not_loosened

BASELINE = Path(__file__).parent / "causal_claim_baseline.json"


def _unannotated_per_file() -> dict:
    per: dict = {}
    for c in claims():
        if not c.annotated:
            per[c.file] = per.get(c.file, 0) + 1
    return per


@pytest.mark.unit
class TestTheLedgerShrinks:

    def test_no_new_unproven_claims(self):
        current = _unannotated_per_file()
        base = json.loads(BASELINE.read_text(encoding="utf-8"))["per_file"]
        grew = {f: (base.get(f, 0), n) for f, n in current.items()
                if n > base.get(f, 0)}
        assert not grew, (
            "new reason string(s) asserting a cause with nothing cited:"
            + "".join(f"\n  {f}: {was} -> {now}" for f, (was, now) in grew.items())
            + f"\n\nAdd `{ANNOTATION} <the state in THIS scope that proves it>` "
              "on or above the line. If you cannot write that sentence, the "
              "string is the bug — say what the code actually knows instead. "
              "Regenerate deliberately with tests/regen_causal_baseline.py."
        )

    def test_the_total_never_rises(self):
        total = sum(_unannotated_per_file().values())
        base = json.loads(BASELINE.read_text(encoding="utf-8"))["total"]
        assert total <= base, (
            f"unproven causal claims rose {base} -> {total}. "
            "The ledger only shrinks.")
        # (#1304) the ledger file itself may not have been loosened quietly
        assert_not_loosened(BASELINE, lambda d: d["total"], "causal claims")

    def test_the_ratchet_is_measuring_something(self):
        """A ratchet over an empty set holds forever and means nothing —
        the same vacuity this whole arc is about. If the enumerator stops
        matching because the idiom changed, fail loudly instead."""
        assert claims(), (
            "the causal-claim enumerator matches nothing at all — either "
            "every reason was annotated (delete this ratchet and celebrate) "
            "or `reason=` is no longer how SEM says why")


@pytest.mark.unit
class TestTheEnumeratorItself:
    """It gates merges, so it is tested like anything else (#925)."""

    def test_a_decision_describing_itself_is_not_a_claim(self, tmp_path):
        (tmp_path / "m.py").write_text(
            'x = f(reason="mode=force_discharge (manual sell to grid)")\n')
        assert claims(tmp_path) == []

    def test_a_claim_about_the_world_is_caught(self, tmp_path):
        (tmp_path / "m.py").write_text('x = f(reason="sensor unavailable")\n')
        found = claims(tmp_path)
        assert len(found) == 1 and not found[0].annotated

    def test_an_annotation_on_the_line_discharges_it(self, tmp_path):
        (tmp_path / "m.py").write_text(
            'x = f(reason="sensor unavailable")  # CAUSE: state.state is None\n')
        assert claims(tmp_path)[0].annotated

    def test_an_annotation_above_discharges_it(self, tmp_path):
        (tmp_path / "m.py").write_text(
            "# CAUSE: state.state is None\n"
            'x = f(reason="sensor unavailable")\n')
        assert claims(tmp_path)[0].annotated

    def test_the_literal_half_of_an_fstring_is_what_is_judged(self, tmp_path):
        (tmp_path / "m.py").write_text(
            'x = f(reason=f"held {amps}A — sensor unavailable")\n')
        assert len(claims(tmp_path)) == 1

    def test_interpolated_values_alone_are_not_a_claim(self, tmp_path):
        (tmp_path / "m.py").write_text('x = f(reason=f"{amps}A")\n')
        assert claims(tmp_path) == []

    def test_a_file_it_cannot_parse_is_not_a_pass(self, tmp_path):
        (tmp_path / "m.py").write_text("def broken(\n")
        with pytest.raises(SyntaxError):
            claims(tmp_path)

    def test_an_annotation_above_a_multi_line_reason_is_found(self, tmp_path):
        """A `reason=` routinely spans four or five lines, so the annotation
        sits above the STATEMENT, not above the string. The first version of
        the enumerator looked only at the line above the literal and reported
        every annotated claim as unproven — the ledger would not move no
        matter how much work was done."""
        (tmp_path / "m.py").write_text(
            "def f():\n"
            "    return replace(\n"
            "        d,\n"
            "        # CAUSE: the guard above is `target < floor`\n"
            "        reason=(\n"
            '            f"budget {t}A is below the floor — holding off "\n'
            '            f"instead of cycling"\n'
            "        ),\n"
            "    )\n")
        found = claims(tmp_path)
        assert len(found) == 1
        assert found[0].annotated, "annotation above the statement was missed"

    def test_an_annotation_inside_the_statement_also_counts(self, tmp_path):
        (tmp_path / "m.py").write_text(
            "def f():\n"
            "    return g(\n"
            '        reason="sensor unavailable",  # CAUSE: state is None\n'
            "    )\n")
        assert claims(tmp_path)[0].annotated

    def test_a_comment_further_up_past_a_blank_line_does_not_count(self, tmp_path):
        """The annotation belongs to the claim, not to the function."""
        (tmp_path / "m.py").write_text(
            "def f():\n"
            "    # CAUSE: something unrelated\n"
            "\n"
            '    return g(reason="sensor unavailable")\n')
        assert not claims(tmp_path)[0].annotated
