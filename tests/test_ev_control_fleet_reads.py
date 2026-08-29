"""AST lint: every ``power.ev_power`` read in ``ev_control.py`` must be
either inside the per-charger helper or carry a ``# FLEET-READ:`` tag.

The recurring bug class through v1.6.0 → v1.6.6 was per-charger code
paths accidentally reading the fleet-summed ``power.ev_power``. v1.6.7
lifted the swap mechanism into ``PerChargerContext`` and v1.6.8 sweeps
the remaining reads in ``coordinator/ev_control.py`` to use
``self._this_charger_power(ev, power)`` cached as ``this_power_w``
locally.

This test pins that invariant going forward — any new ``power.ev_power``
read added to ``ev_control.py`` must be annotated with
``# FLEET-READ: <reason>`` on the same line (or the immediately
preceding line) or the test fails CI. This is the cheapest enforcement
that catches the bug class on PR review rather than after release.

The ``_this_charger_power`` helper itself is exempt — it's the
sanctioned fallback path. Docstrings and comments mentioning
``power.ev_power`` are also exempt because they're text, not code.

See ``docs/MULTI_CHARGER.md`` for the full invariant.
"""

from __future__ import annotations

import ast
from pathlib import Path



_COORD = Path(__file__).resolve().parent.parent / "coordinator"
EV_CONTROL_PY = _COORD / "ev_control.py"

# (2.1 audit) The invariant is not a property of one file — every module that
# runs per-charger logic can regress the same way. The new per-charger
# modules the 2.1 branch added are scanned with the same rules; they were
# clean on arrival, and this keeps them that way.
SCANNED_FILES = [
    EV_CONTROL_PY,
    _COORD / "watts_per_amp.py",
    _COORD / "wpa_replay.py",
    _COORD / "charge_pacing.py",
    _COORD / "charger_reconciler.py",
]

# Functions whose body is allowed to read ``power.ev_power`` directly.
# Currently only the helper that DEFINES the fleet-fallback path.
EXEMPT_FUNCTIONS = frozenset({"_this_charger_power"})

# The annotation that opts a single read out of the lint. Place it as a
# line comment on the same line as the read OR on the line above:
#
#     foo = power.ev_power  # FLEET-READ: explanation
#
#     # FLEET-READ: explanation
#     foo = power.ev_power
ANNOTATION = "# FLEET-READ:"


def _find_function_for_line(tree: ast.Module, line: int) -> str | None:
    """Return the innermost function definition enclosing the given line.

    Walks the AST top-down looking for ``FunctionDef`` /
    ``AsyncFunctionDef`` nodes whose line range contains ``line``.
    Returns the name of the deepest match, or ``None`` if the read is at
    module scope (which would itself be a bug — included in the lint
    output for visibility).
    """
    best: tuple[int, str] | None = None  # (start_line, name)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", node.lineno)
            if start <= line <= end:
                if best is None or start > best[0]:
                    best = (start, node.name)
    return best[1] if best else None


def _read_lines() -> list[str]:
    return EV_CONTROL_PY.read_text().splitlines()


def _find_ev_power_reads(tree: ast.Module) -> list[tuple[int, str]]:
    """Return ``(line, enclosing_function)`` for every ``power.ev_power``
    attribute read in the file."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "ev_power"
            and isinstance(node.value, ast.Name)
            and node.value.id == "power"
        ):
            func = _find_function_for_line(tree, node.lineno) or "<module>"
            hits.append((node.lineno, func))
    return hits


def _is_annotated(lines: list[str], line_no: int) -> bool:
    """True if the read at ``line_no`` (1-based) carries a
    ``# FLEET-READ:`` annotation on the same line or the immediately
    preceding line.

    Note: only **same-line** or **previous-line** annotations are
    recognised. Two-lines-above doesn't count — keep the annotation
    visually adjacent to the read so reviewers see it.

    Also: only the ``power.ev_power`` dotted form is checked by the
    lint (see ``_find_ev_power_reads``). ``getattr(power, "ev_power",
    ...)`` would bypass the AST walker — by convention treat that as
    forbidden anywhere outside ``_this_charger_power``, but it is not
    mechanically enforced.
    """
    idx = line_no - 1  # to 0-based
    same = lines[idx] if 0 <= idx < len(lines) else ""
    prev = lines[idx - 1] if 0 < idx < len(lines) else ""
    return ANNOTATION in same or ANNOTATION in prev


class TestEvPowerReads:
    """Pin the multi-charger invariant at lint level.

    These tests parse ``coordinator/ev_control.py`` and check every
    ``power.ev_power`` AST node. They do not exercise runtime behaviour
    — that's covered by the unit and scenario tests.
    """

    def test_all_reads_are_exempt_or_annotated(self):
        """Every ``power.ev_power`` read must be either inside the
        sanctioned ``_this_charger_power`` helper OR carry a
        ``# FLEET-READ:`` annotation explaining why a fleet sum is
        deliberately wanted.

        When this test fails, the message lists each offending read with
        its line number and enclosing function. Fix by either:

        1. Replacing the read with ``this_power_w`` (cached via
           ``self._this_charger_power(ev, power)`` at the top of the
           function) — the right answer for per-charger code paths.
        2. Adding ``# FLEET-READ: <reason>`` immediately above or on the
           same line — for the rare case where you genuinely mean the
           fleet sum (e.g. a sensor that aggregates across the fleet).

        Coverage caveats (intentional, both rare in practice):

        - Only the ``power.ev_power`` dotted form is walked. A
          ``getattr(power, "ev_power", 0.0)`` would silently bypass the
          AST check — by convention this is treated as forbidden too,
          but not mechanically enforced.
        - The annotation must be on the same line as the read or the
          one immediately above. Two-lines-above won't satisfy the
          check — keep the annotation visually adjacent.
        """
        offenders: list[str] = []
        for path in SCANNED_FILES:
            source = path.read_text()
            tree = ast.parse(source)
            lines = source.splitlines()
            for line_no, func in _find_ev_power_reads(tree):
                if func in EXEMPT_FUNCTIONS:
                    continue
                if _is_annotated(lines, line_no):
                    continue
                offenders.append(f"  {path.name}:L{line_no} in {func}()")

        assert not offenders, (
            "Found unannotated ``power.ev_power`` reads in per-charger "
            "modules outside the sanctioned helper "
            "``_this_charger_power``. In multi-charger setups "
            "``power.ev_power`` is the GLOBAL SUM across all chargers — "
            "reading it directly inside a per-charger code path is the "
            "bug class that caused #284, #289, #315 and #318.\n\n"
            "Each offender:\n" + "\n".join(offenders) + "\n\n"
            "Fix: either replace with ``this_power_w`` cached via "
            "``self._this_charger_power(ev, power)`` (preferred), or "
            "annotate with ``# FLEET-READ: <reason>`` on the same line or "
            "the line immediately above (only when fleet semantics are "
            "explicitly wanted).\n\n"
            "See docs/MULTI_CHARGER.md for the full invariant."
        )

    def test_helper_is_only_exempt_function(self):
        """The exemption list is intentionally minimal — exactly one
        function. If you find yourself wanting to add another, talk to
        a maintainer first; almost certainly the right answer is the
        ``# FLEET-READ:`` annotation on the specific read instead."""
        assert EXEMPT_FUNCTIONS == frozenset({"_this_charger_power"})

    def test_lint_actually_detects_unannotated_reads(self):
        """Sanity: if we deliberately strip the ``# FLEET-READ:``
        annotations and re-run the analysis on a synthetic source, the
        offender list is non-empty. Guards against the lint silently
        passing because the AST walk found nothing (e.g. after a future
        refactor that renames ``power`` to ``readings`` everywhere)."""
        synthetic = (
            "def f(power):\n"
            "    if power.ev_power > 100:\n"  # unannotated -> should be flagged
            "        return True\n"
            "    return False\n"
        )
        tree = ast.parse(synthetic)
        lines = synthetic.splitlines()
        hits = _find_ev_power_reads(tree)
        assert hits, "AST walker failed to find a power.ev_power read"
        # The synthetic source has no annotation -> the offender list is
        # non-empty.
        unannotated = [h for h in hits if not _is_annotated(lines, h[0])]
        assert unannotated, "Lint failed to flag unannotated read"

    def test_annotation_on_same_line_exempts(self):
        synthetic = (
            "def f(power):\n"
            "    return power.ev_power  # FLEET-READ: aggregate sensor\n"
        )
        tree = ast.parse(synthetic)
        lines = synthetic.splitlines()
        hits = _find_ev_power_reads(tree)
        assert hits, "AST walker failed to find the read"
        assert all(_is_annotated(lines, h[0]) for h in hits)

    def test_annotation_on_previous_line_exempts(self):
        synthetic = (
            "def f(power):\n"
            "    # FLEET-READ: aggregate sensor\n"
            "    return power.ev_power\n"
        )
        tree = ast.parse(synthetic)
        lines = synthetic.splitlines()
        hits = _find_ev_power_reads(tree)
        assert hits
        assert all(_is_annotated(lines, h[0]) for h in hits)
