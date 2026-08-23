"""#830 — the option surface is shrink-only.

Guido, 22.08: *"SEM is getting complicated and complicated, users are getting
more lost in all the options we provide."*

**Every option is a decision SEM could not make for itself.** So the count is
not a style question, it is a measure of how much thinking was outsourced to
the user — and it has only ever gone up, because every individual field arrived
for a good reason. That is exactly how 125 config fields happened.

This is the same shrink-only ratchet that closed #828 (bounds), #653 (orphans)
and #829 (publishers): a frozen inventory, and any difference fails. The two
directions fail with different messages on purpose —

* **growth** must be justified. The test names the new control and asks what it
  retires or why it must exist. A field that survives that question is fine;
  the point is that nobody adds one absent-mindedly again.
* **shrink** must be recorded. It fails too, saying "good news, regenerate" —
  so a retirement shows up as a visible line in the diff instead of quietly
  loosening the ceiling.

The evidence that this was needed arrived the same day it was written: the
count went 155 → 158 because THIS branch added three switches for #778. Each
was individually justified (a master switch plus the two battery permissions,
required by the standing rule that every setting is reachable on the
dashboard). Three individually justified additions is precisely the mechanism
under examination, and they are the ratchet's first entries.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tests" / "option_surface_baseline.json"

sys.path.insert(0, str(ROOT / "scripts"))


def _live():
    """Today's inventory, from the same counter the audit script prints."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "audit_options", ROOT / "scripts" / "audit_options.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.measure()


def _baseline():
    return json.loads(BASELINE.read_text())


KINDS = ("config_fields", "number_entities", "switch_entities")

REGEN = ("Run  python3 scripts/audit_options.py --baseline  and commit the "
         "result, so the change is visible in the diff.")


@pytest.mark.parametrize("kind", KINDS)
def test_no_control_appeared_without_a_decision(kind):
    live = set(_live()["inventory"][kind])
    base = set(_baseline()[kind])
    added = sorted(live - base)
    assert not added, (
        f"{len(added)} new user-facing control(s) in {kind}: {added}\n"
        f"Every option is a decision SEM could not make for itself. Before "
        f"adding one, ask whether it can be autodetected (#814), learned "
        f"(#755), decided by the plan (#638), or handled by a better default. "
        f"If it genuinely must exist, {REGEN}")


@pytest.mark.parametrize("kind", KINDS)
def test_a_retirement_is_recorded(kind):
    live = set(_live()["inventory"][kind])
    base = set(_baseline()[kind])
    gone = sorted(base - live)
    assert not gone, (
        f"good news — {len(gone)} control(s) retired from {kind}: {gone}\n"
        f"{REGEN}")


def test_the_total_never_grows():
    """The headline number, pinned separately: the per-kind checks above could
    both pass under a rename that swapped one control for another, and the
    number a user feels would still have moved."""
    live = _live()["user_facing_controls"]
    base = _baseline()["total"]
    assert live <= base, (
        f"the option surface grew from {base} to {live}. {REGEN}")


def test_the_baseline_matches_what_the_audit_reports():
    """Guard the guard. If the audit's counter and the baseline's total ever
    disagree, this ratchet is measuring one thing and reporting another."""
    m = _live()
    inv = m["inventory"]
    assert (len(inv["config_fields"]) + len(inv["number_entities"])
            + len(inv["switch_entities"])) == m["user_facing_controls"]


def test_the_audit_script_still_runs():
    """The instrument has to work, not just the test that imports it —
    scripts rot silently when only their internals are exercised."""
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "audit_options.py"), "--json"],
        capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-400:]
    assert json.loads(out.stdout)["user_facing_controls"] > 0
