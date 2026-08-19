"""#645 — SEM's day boundaries are DECLARED, not deduplicated.

The audit filed this as "duplicated mechanism: nine subsystems each re-derive
what day it is". The verifier corrected the closure, and the correction is the
whole point of this file: SEM has **four genuinely different, intentional day
boundaries**, and collapsing them into one injected date would break three of
them.

  1. **Calendar midnight** — energy + flow accumulators. Deliberately matches
     HA's own Energy Dashboard so SEM's daily kWh reconcile against it.
  2. **EV deadline-based** (#279) — an EV "day" ends at the user's departure
     deadline, not at midnight.
  3. **Sunrise, EV bucket** (`ev_daily_sun`) — the overnight charge belongs to
     the night it started, so the per-charger bucket rolls at sunrise.
  4. **Sunrise-gated load day** (#620, explicit product decision) — resetting a
     load's daily target at midnight would let it drain the battery all night
     refilling a brand-new target before the sun is up.

So the repetition is not duplication, and the guard cannot be "call the shared
helper". What it CAN be, and what this file is, is two rules:

**Rule 1 (absolute).** A calendar day is never derived from the OS clock.
``date.today()`` / ``datetime.now().date()`` read the *container's* timezone,
which for a supervised or Docker install is routinely UTC while
``hass.config.time_zone`` is the user's. Near midnight the two name different
days. Duration arithmetic on ``datetime.now()`` is fine and stays allowed —
both ends use the same clock — this rule is only about naming a DAY.

**Rule 2 (ratchet).** Every remaining ``dt_util.now().date()`` in production is
a *day-boundary authority* and must be declared below with which of the four
boundaries it serves and whether its memo survives a restart. A tenth authority
appearing undeclared fails CI: not to forbid it, but to force the author to
answer the question that made this issue expensive — *what happens if HA
restarts across your boundary?* That was the live bug (#645): the EV virtual-SOC
decay's memo was re-initialised to today on every start, so a restart spanning
midnight skipped a day's decay and the night-charge planner read a stale
"still nearly full" SOC.

Same ratchet shape as ``tests/test_653_orphan_methods.py``, which is proven in
this repo: the allowlist must be edited deliberately, and it shrinks.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Directories that ship as the integration. ``tools/`` is developer scripting
# that runs on the dev box, not inside HA, so the OS clock IS its clock.
PRODUCTION_GLOBS = ("*.py", "coordinator/**/*.py", "features/**/*.py",
                    "devices/**/*.py", "analytics/**/*.py", "utils/**/*.py")
EXCLUDED_DIRS = {"tests", "tools", "node_modules", "dashboard", "scripts"}

# Rule 1 — naming a day off the OS clock.
NAIVE_DAY = re.compile(
    r"(?<![\w.])(?:date\.today\(\)|datetime\.now\(\)\.date\(\))"
)
# Rule 2 — the HA-local day derivations that ARE the authorities.
HA_DAY = re.compile(r"dt_util\.now\(\)\.date\(\)")


# (file, symbol/context, boundary, memo persisted across a restart?)
#
# "persisted" answers: if HA restarts across this boundary, does the subsystem
# still know the boundary was crossed? "n/a" = the value is used immediately
# and never memoised, so a restart cannot lose anything.
DECLARED_AUTHORITIES = {
    ("coordinator/coordinator.py", "battery-night record key (#800)"):
        ("calendar", "survives — the date is only the sealed record's KEY; "
                     "the real boundary is is_night_mode()'s flip, the open "
                     "night persists whole (to_dict/from_dict incl. last_ts) "
                     "and a restart across it prices its outage as a gap, "
                     "which refuses the night rather than mislabeling it"),
    ("coordinator/coordinator.py", "_tracker_date init"):
        ("calendar", "n/a — the hour arrays it guards start empty anyway; "
                     "the decay that USED to ride on it moved out in #645"),
    ("coordinator/coordinator.py", "tariff diagnostics"):
        ("calendar", "n/a — filters today's price points for a diagnostic "
                     "count, recomputed every cycle"),
    ("coordinator/coordinator.py", "_load_meter_day"):
        ("sunrise-load", "yes — persisted per device as meter_day, and a "
                         "stale restore is repaired (#622)"),
    ("coordinator/flow_calculator.py", "_current_date init"):
        ("calendar", "yes — saved with the snapshot; restore rejects a "
                     "stale-day snapshot rather than double-counting"),
    ("coordinator/flow_calculator.py", "accumulator rollover"):
        ("calendar", "yes — same snapshot; deliberately calendar so daily "
                     "flow kWh reconcile with the HA Energy Dashboard"),
    ("coordinator/forecast_tracker.py", "sunrise/sunset day clamp"):
        ("calendar", "n/a — clamps a tomorrow-dated sun event back one day "
                     "within a single call"),
    ("coordinator/surplus_controller.py", "_apply_source_markers"):
        ("calendar", "no, by design — the force markers are a derived view "
                     "recomputed each reconcile and default off on restart, "
                     "so a stale force cannot survive one"),
    ("coordinator/surplus_controller.py", "overnight force expiry"):
        ("calendar", "no, by design — same markers; the date check exists so "
                     "yesterday's cheap-window force does not refill today's "
                     "target from grid"),
    ("analytics/energy_assistant.py", "_record_daily_stats"):
        ("calendar", "n/a — keys an in-memory trend list; a lost day costs "
                     "one trend point, nothing accumulates wrong"),
    ("analytics/pv_performance.py", "month-to-date divisor"):
        ("calendar", "n/a — read once per calculation"),
    ("devices/appliance_scheduler.py", "completed today"):
        ("calendar", "n/a — filters a history list for display"),
    ("devices/appliance_scheduler.py", "missed today"):
        ("calendar", "n/a — filters a history list for display"),
}


def _production_files():
    seen = set()
    for pattern in PRODUCTION_GLOBS:
        for path in REPO.glob(pattern):
            rel = path.relative_to(REPO)
            if rel.parts[0] in EXCLUDED_DIRS or not path.is_file():
                continue
            seen.add(rel)
    return sorted(seen)


def _hits(pattern):
    out = []
    for rel in _production_files():
        text = (REPO / rel).read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            code = line.split("#", 1)[0]
            if pattern.search(code):
                out.append((str(rel), lineno, line.strip()))
    return out


@pytest.mark.unit
class TestNoDayFromTheOsClock645:
    """Rule 1 — absolute, no allowlist."""

    def test_no_production_code_names_a_day_off_the_os_clock(self):
        hits = _hits(NAIVE_DAY)
        assert not hits, (
            "A calendar day must come from HA's clock, not the container's:\n"
            + "\n".join(f"  {f}:{n}  {src}" for f, n, src in hits)
            + "\n\nUse dt_util.now().date(). The OS clock is routinely UTC "
              "while hass.config.time_zone is the user's, so near midnight "
              "these name different days. (Duration arithmetic on "
              "datetime.now() is fine and not what this checks.)"
        )

    def test_the_rule_can_actually_fire(self):
        """The check must be able to fail — a regex that matches nothing is
        not a guard (docs/BUG_CLASSES.md class 8)."""
        assert NAIVE_DAY.search("today = date.today()")
        assert NAIVE_DAY.search("if h.completed_at.date() == datetime.now().date():")
        # ...and must NOT fire on the legitimate uses it would otherwise eat.
        assert not NAIVE_DAY.search("elapsed = (datetime.now() - start).seconds")
        assert not NAIVE_DAY.search("today = dt_util.now().date()")


@pytest.mark.unit
class TestDayBoundaryRegistry645:
    """Rule 2 — the ratchet."""

    def test_the_authority_count_has_not_grown(self):
        hits = _hits(HA_DAY)
        assert len(hits) <= len(DECLARED_AUTHORITIES), (
            f"{len(hits)} day-boundary authorities in production, "
            f"{len(DECLARED_AUTHORITIES)} declared.\n"
            + "\n".join(f"  {f}:{n}  {src}" for f, n, src in hits)
            + "\n\nA new one is not forbidden — but declare it in "
              "DECLARED_AUTHORITIES with which of SEM's four day boundaries "
              "it serves (calendar / ev-deadline / sunrise-ev / sunrise-load) "
              "and, critically, whether its memo survives a restart that "
              "SPANS the boundary. That question is what #645 was."
        )

    def test_every_declaring_file_still_has_an_authority(self):
        """Keeps the registry from rotting into fiction: a declared file that
        no longer derives a day must be removed from the list."""
        files_with_hits = {f for f, _, _ in _hits(HA_DAY)}
        declared_files = {f for f, _ in DECLARED_AUTHORITIES}
        stale = declared_files - files_with_hits
        assert not stale, (
            f"Declared but no longer a day-boundary authority: {sorted(stale)}. "
            "Remove the entry — the registry is only worth reading if it is true."
        )

    def test_every_declaration_names_a_real_boundary(self):
        valid = {"calendar", "ev-deadline", "sunrise-ev", "sunrise-load"}
        for key, (boundary, note) in DECLARED_AUTHORITIES.items():
            assert boundary in valid, f"{key}: unknown boundary {boundary!r}"
            assert note.strip(), f"{key}: restart behaviour undocumented"

    def test_all_four_boundaries_are_documented_in_the_module_docstring(self):
        """The four-boundary fact is the load-bearing correction to the filed
        issue — if it stops being written down, the next sweep re-files the
        same wrong closure."""
        doc = __doc__ or ""
        for phrase in ("Calendar midnight", "EV deadline-based",
                       "Sunrise, EV bucket", "Sunrise-gated load day"):
            assert phrase in doc
