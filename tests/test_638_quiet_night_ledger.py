"""#638 — a quiet night is still a night: it owes the same ledger answers.

Found on the .175 campaign (round 2, 15.08): with nothing to schedule, the
plan came back with ``arbitrage: None`` and an empty hour axis. Not a
missing advisor — an ORDERING bug. ``_shadow_energy_plan`` answered "no
demands" and returned BEFORE the ledger was ever built, so everything
derived from the ledger (the price/SOC strip, the self-consumption
expectation, the arbitrage verdict) was absent exactly on the nights when
the arbitrage verdict is the only thing left to say.

Three consequences, all pinned here:
  * the advisor's own contract — "ADVICE ALWAYS (it is the framework's
    sharpest audit: if the books lie anywhere, an absurd advice is the
    first symptom)" — was silently false for the quiet regime;
  * the card's arbitrage line and hour axis vanished with no explanation
    on the very night a user has time to read them;
  * ``arbitrage_shadow_demand`` could never inject its demand when it
    would have been the ONLY demand — the unreachable branch.

The quiet answer itself must not move: same why, same why_codes, same
not_scheduled list, still no demands and no blocks.
"""
import pathlib
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator import ev_night_targets

from .test_638_shadow_mode import (  # noqa: F401 — _freeze_now is autouse
    _fake_self, _idle_load, _power, _scheduler, _freeze_now,
)


@pytest.fixture
def no_ev_targets(monkeypatch):
    monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                        lambda coord, energy: {})


def _quiet_plan(**config):
    """A READY world with nothing to do — the regime that lost the ledger.

    SOC 20 % of a 10 kWh battery sits BELOW the 30 % floor, so the house
    runs off the meter all night: there is real grid draw for a delivery
    hour to displace, and 8 kWh of room to buy into. With the harness
    curve (10 ct at 02-03, 28 ct elsewhere) the round trip clears easily —
    an opportunity the advisor is supposed to see and report.
    """
    fake = _fake_self(devices=[_idle_load()])
    fake.config.update(config)
    ok = SEMCoordinator._shadow_energy_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(), power=_power(20.0))
    assert ok is True, "a quiet night is an answer, not a retry"
    return fake._energy_plan_shadow


def test_a_quiet_night_still_gets_an_arbitrage_verdict(no_ev_targets):
    plan = _quiet_plan()
    assert plan["demands"] == []           # genuinely the quiet regime
    arb = plan.get("arbitrage")
    assert arb is not None, "the advisor never ran on a night with no demands"
    assert arb.get("reason"), f"a verdict with no reason: {arb}"
    assert arb["opportunity"] is True, (
        "10 ct in, 28 ct out, 8 kWh of room — the advisor should see it")


def test_the_shadow_demand_reaches_an_otherwise_quiet_night(no_ev_targets):
    """The config-gated injection was unreachable in the one regime where
    the shadow cycle would be the whole plan."""
    plan = _quiet_plan(arbitrage_shadow_demand=True)
    ids = {d["id"] for d in (plan.get("demands") or [])}
    assert "arbitrage:battery" in ids, f"demands={ids}"
    # And it is a real packed plan now, not the quiet payload wearing a
    # demand: the blocks the shadow cycle would buy in must be there.
    assert [b for b in (plan.get("blocks") or [])
            if b["id"] == "arbitrage:battery"]


def test_the_quiet_night_publishes_the_ledger_it_judged(no_ev_targets):
    """The hour axis and the self-consumption expectation are ledger facts,
    not packing results — a night with nothing to schedule still has
    prices, a battery trajectory and a share it expects to keep."""
    plan = _quiet_plan()
    slots = plan.get("slots") or []
    assert slots, "the quiet plan judged a night it never showed"
    assert all("price" in s and "start" in s and "end" in s for s in slots)
    assert plan.get("self_consumption") is not None


def test_the_quiet_face_shows_the_arbitrage_verdict():
    """Half a fix is a payload nobody can see.

    The card takes an early exit to the compact "nothing to schedule" face
    the moment the demand list is empty — so a verdict published on a quiet
    night would still never reach the user. ONE renderer for the arbitrage
    line, called from BOTH faces: two copies is how the busy night and the
    quiet night came to disagree in the first place.
    """
    card = (pathlib.Path(__file__).resolve().parent.parent / "dashboard"
            / "card" / "src" / "cards" / "sem-energy-plan-card.js").read_text()
    assert "_renderArb(" in card, "no single arbitrage renderer"
    idle_face, _, full_face = card.partition("    render() {")
    assert "this._renderArb(" in idle_face, "the quiet face drops the verdict"
    assert "this._renderArb(" in full_face, "the busy face lost the verdict"
    # …and the quiet branch has to HAND it the verdict.
    call = full_face.split("verdict === 'idle' || !demands.length", 1)[1] \
        .split(");", 1)[0]
    assert "a.arbitrage" in call, f"quiet call site: {call}"


def test_the_quiet_night_still_says_nothing_planned(no_ev_targets):
    """The gate's sentence must survive the ledger appearing.

    ``plan_gate`` told a deliberately empty plan apart from an unreadable
    one by "no demands AND no slots" — true only while the quiet plan
    published no slots. The moment it published the ledger it judged
    (above), that discriminator stopped matching and every device's
    coverage silently became ``not in plan``: technically true, but it is
    the sentence for "the plan left YOU out", read on a night the plan
    left EVERYONE out on purpose. The quiet regime is the empty DEMAND
    list; the slots are the books, not the schedule.

    Found on the .175 campaign minutes after the ledger fix went live —
    the unit tests kept passing because they hand-built the old shape.
    """
    from custom_components.solar_energy_management.coordinator \
        .energy_plan_actuation import plan_gate
    from datetime import datetime, timedelta
    plan = _quiet_plan()
    now = datetime.fromisoformat(plan["computed_at"]) + timedelta(minutes=5)
    for demand_id in ("battery", "load:pump", "ev:keba"):
        gate = plan_gate(plan, demand_id, now)
        assert gate.covered is False        # an empty plan rules nothing
        assert gate.reason == "nothing planned", (
            f"{demand_id}: {gate.reason}")


def test_the_quiet_answer_itself_does_not_move(no_ev_targets):
    """Everything the quiet payload already promised the card stays put."""
    plan = _quiet_plan()
    assert plan["fits"] is True
    assert plan["demands"] == []
    assert plan["blocks"] == []
    assert "no overnight demands" in plan["summary"][0]
    assert "battery_no_deficit" in plan["why_codes"]
    # (#744) ``_idle_load`` never asked for guaranteed runtime, so it is not
    # a night candidate and owes no why-not. The quiet night still SAYS so —
    # via ``no_load_needs_night`` above, which is keyed on loads_seen.
    assert plan["not_scheduled"] == []
    assert "no_load_needs_night" in plan["why_codes"]
    assert plan["replan_cause"] is None or isinstance(plan["replan_cause"], str)
