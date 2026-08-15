"""#638 — the plan must be part of the decision, not a note under the door.

Live on PROD, 2026-08-06. The energy planner reserved 22:00→22:18:52
for the car (1.52 kWh at 4833 W) and published it: ``sensor.sem_energy_plan``
= ``fits``, ``actuation: true``, the block rendered on the card. The car
charged 21:01→~21:30 at the Min floor instead and reported "Night mode -
Target reached" at 22:37 — finished half an hour before the plan's window
ever opened. Same night, the published state read "Tariff mode - Waiting
for cheap price" with ``calculated_current: 0`` while the reconciler wrote
10 A and the car pulled 4.9 kW.

Root cause: the verdict never reached the decision. Every other night
input is a typed field on ``ChargerView`` — ``deadline_amps``,
``top_up_amps``, ``night_deliverable_kwh``, ``soc_ceiling_reached``. The
one signal that says *don't charge yet* was smuggled into the untyped
config mapping (``build_view.py``: ``cfg_with_wait["_tariff_wait"] = ...``),
so it was invisible in the type and duly invisible to two of the three
night-capable modes. ``solar_only`` and ``min_plus_solar`` route straight
to ``night_top_up_decision``, which had no wait branch at all.

This is a REPEAT, which is why the guard below is behavioural rather than
a one-line fix: ``tests/scenarios/2026-06-02_min_plus_solar_night_deadline_floor.yaml``
records "the commit that fixed the SolarPlusCheapMode tariff_wait gap" —
fixed in one mode, left standing in its two siblings. A guard that only
pins today's three modes would let the fourth repeat it.
"""
import re
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerEnergy,
    ChargerIntent,
    ChargerPower,
    ChargerView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide import (
    MODE_STRATEGIES,
    decide,
)
from custom_components.solar_energy_management.coordinator.plan_verdict import (
    NO_OPINION,
    PlanVerdict,
    verdict_from_night_plan,
)


# The two modes a plan may never hold back, and why. Both are the user
# overriding the planner on purpose, so a hold would be SEM disobeying an
# explicit instruction — the opposite failure to the one this file fixes.
UNPLANNABLE = {
    "off": "the user switched the charger off — there is nothing to plan",
    "always_max": "an explicit 'charge now, ignore everything' override",
}

NIGHT_MODES = sorted(set(MODE_STRATEGIES) - set(UNPLANNABLE))


def _night_view(mode: str, *, plan: PlanVerdict = NO_OPINION,
                target_kwh: float = 10.0, deadline_amps: int = 10,
                config: dict | None = None) -> ChargerView:
    """A connected charger, at night, still owing energy.

    Deliberately the shape PROD was in: a real remaining target and a
    deadline floor already computed, i.e. every reason to charge. The only
    thing that should stop it is the plan.
    """
    return ChargerView(
        power=ChargerPower(charger_id="keba", power_w=0.0, connected=True,
                           charging=False),
        energy=ChargerEnergy(charger_id="keba"),
        mode=mode,
        config=config or {"ev_min_current": 10, "ev_max_current": 16,
                          "ev_phases": 3, "ev_voltage": 230},
        fleet=FleetContext(solar_w=0.0, home_w=400.0, battery_soc=80.0,
                           is_night=True),
        target_kwh=target_kwh,
        deadline_amps=deadline_amps,
        plan=plan,
    )


class TestTheVerdictIsPartOfThePicture:
    """It has to be a field, not a key in an untyped mapping.

    The whole failure was that a reader of ``decide()`` could not SEE that
    a plan existed. Typed field = the picture the decision is handed.
    """

    def test_the_view_carries_a_plan_verdict(self):
        assert isinstance(_night_view("solar_only").plan, PlanVerdict)

    def test_absence_is_the_default_and_means_no_opinion(self):
        """Fail-open, unchanged: no plan ⇒ behave exactly as before #638.

        Every install without the energy planner, and every cycle where
        the plan is stale or the switch is off, lands here.
        """
        assert NO_OPINION.hold is False
        assert NO_OPINION.reason == ""
        assert NO_OPINION.until is None
        # A view built without mentioning the plan gets it anyway.
        bare = ChargerView(
            power=ChargerPower(charger_id="keba", connected=True),
            energy=ChargerEnergy(charger_id="keba"),
            mode="solar_only", config={}, fleet=FleetContext(),
        )
        assert bare.plan == NO_OPINION

    def test_the_verdict_is_not_smuggled_through_the_config_mapping(self):
        """The private ``_tariff_wait`` key is gone.

        Pinned because that key IS the bug: an untyped side-channel that
        one mode happened to know about. If it comes back, so does the
        class.
        """
        import inspect
        import io
        import tokenize

        from custom_components.solar_energy_management.coordinator import (
            build_view,
            decide as decide_mod,
        )

        def _code_only(src: str) -> str:
            """The module with its comments dropped.

            The invariant is about what the code DOES; the comments in
            both modules deliberately name the old key to record why it
            went away, and that history is worth more than the two lines
            of tokenising it costs to keep.
            """
            return " ".join(
                t.string
                for t in tokenize.generate_tokens(io.StringIO(src).readline)
                if t.type != tokenize.COMMENT
            )

        # A WRITE (``cfg["_tariff_wait"] = ...``) or a READ
        # (``cfg.get("_tariff_wait")``). Whitespace-tolerant because the
        # token stream above is re-joined with spaces.
        side_channel = re.compile(
            r'\[\s*["\']_tariff_wait["\']\s*\]'
            r'|\.\s*get\s*\(\s*["\']_tariff_wait["\']'
        )
        for mod in (build_view, decide_mod):
            hit = side_channel.search(_code_only(inspect.getsource(mod)))
            assert hit is None, (
                f"{mod.__name__} still routes the plan through the config "
                f"mapping ({hit.group(0)!r}) — put it on the view instead"
            )


class TestEveryNightModeHonoursAHold:
    """The class-killer.

    Behavioural, not AST, and parametrized over ``MODE_STRATEGIES`` itself
    — so a mode added next year is covered the day it is registered,
    without anyone remembering this file exists. That is the property the
    2026-06-02 fix lacked when it repaired ``solar_plus_cheap`` alone.
    """

    @pytest.mark.parametrize("mode", NIGHT_MODES)
    def test_a_hold_stops_the_charge(self, mode):
        d = decide(_night_view(mode, plan=PlanVerdict(
            hold=True, reason="joint energy plan: block opens at 22:00")))
        assert d.intent is not ChargerIntent.CHARGE_AT_AMPS, (
            f"{mode} charged straight through the plan's hold — this is the "
            "PROD 2026-08-06 failure: the car finished before its own "
            "planned window opened"
        )

    @pytest.mark.parametrize("mode", NIGHT_MODES)
    def test_the_reason_says_it_is_the_plan_holding(self, mode):
        """A hold the user can't attribute is a hold they'll switch off."""
        d = decide(_night_view(mode, plan=PlanVerdict(
            hold=True, reason="joint energy plan: block opens at 22:00")))
        assert "wait" in d.reason.lower() or "hold" in d.reason.lower()

    @pytest.mark.parametrize("mode", sorted(UNPLANNABLE))
    def test_the_user_overrides_outrank_the_plan(self, mode):
        """``off`` and ``always_max`` are instructions, not preferences.

        Holding these back would be the mirror-image bug: SEM quietly
        disobeying something the user set explicitly.
        """
        held = decide(_night_view(mode, plan=PlanVerdict(hold=True)))
        free = decide(_night_view(mode, plan=NO_OPINION))
        assert held.intent is free.intent, UNPLANNABLE[mode]


class TestAHoldNeverCostsTheGuarantee:
    """No opinion ⇒ byte-for-byte today's behaviour.

    The risk of this change is a car that doesn't charge. These pin the
    other side: nothing moves unless a plan actively says so.
    """

    @pytest.mark.parametrize("mode", NIGHT_MODES)
    def test_no_plan_still_charges_at_the_deadline_floor(self, mode):
        d = decide(_night_view(mode, plan=NO_OPINION))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 10

    @pytest.mark.parametrize("mode", NIGHT_MODES)
    def test_a_verdict_with_no_hold_is_the_same_as_no_verdict(self, mode):
        """``hold=False`` is a plan that says "go" — not a weaker "no plan"."""
        explicit = decide(_night_view(mode, plan=PlanVerdict(hold=False)))
        absent = decide(_night_view(mode, plan=NO_OPINION))
        assert (explicit.intent, explicit.commanded_amps) == \
               (absent.intent, absent.commanded_amps)

    @pytest.mark.parametrize("mode", NIGHT_MODES)
    def test_a_finished_charge_is_never_blamed_on_the_planner(self, mode):
        """Nothing owed ⇒ idle, but NOT "waiting for the planned window".

        The honesty half of this fix. PROD spent 2026-08-06 evening
        publishing "Tariff mode - Waiting for cheap price" while the
        reconciler wrote 10 A; the inverse — reporting a hold for a charge
        that simply finished — would be the same lie pointing the other
        way, and would send the user hunting a planner bug that isn't
        there.
        """
        d = decide(_night_view(mode, target_kwh=0.0, plan=PlanVerdict(
            hold=True, reason="SENTINEL-plan-reason")))
        assert d.intent is not ChargerIntent.CHARGE_AT_AMPS
        assert "SENTINEL-plan-reason" not in d.reason
        assert "planned window" not in d.reason


class TestOnePlaceTranslatesTheNightPlan:
    """The ``NightChargePlan`` → verdict translation lives in one function.

    Not for tidiness: SEM computes that plan at TWO sites — once for the
    primary charger in ``_build_charging_context`` and once per charger in
    the multi-charger loop — and those two drifting apart is a named,
    recurring class (#683/#684). A translation copied into both is a
    translation that will diverge the first time the verdict grows a
    field, which is exactly what Stage 2 does when it adds ``until``.
    """

    def test_no_plan_is_no_opinion(self):
        """No plan computed this cycle ⇒ the planner has nothing to say.

        Passed ``None`` rather than a plan for every cycle outside the
        night window and every charger whose remaining target is already
        met. Must be indistinguishable from an install with no planner.
        """
        assert verdict_from_night_plan(None) == NO_OPINION

    def test_a_waiting_plan_becomes_a_hold_that_carries_its_reason(self):
        """The words the user reads come from the plan, not from a rewrite.

        Both layers quoting ONE string is what stops the published state
        and the action telling different stories, as they did all evening
        on 2026-08-06.
        """
        verdict = verdict_from_night_plan(SimpleNamespace(
            should_wait_for_cheap=True,
            reason="joint energy plan: outside the planned window"))
        assert verdict.hold is True
        assert verdict.reason == "joint energy plan: outside the planned window"

    def test_a_plan_that_says_go_is_not_a_hold(self):
        """In-window: the plan raised a floor, it did not ask anyone to wait."""
        verdict = verdict_from_night_plan(SimpleNamespace(
            should_wait_for_cheap=False,
            reason="joint energy plan: in planned window — floor 10A"))
        assert verdict.hold is False

    def test_every_call_site_builds_its_verdict_through_the_factory(self):
        """No caller hand-rolls a ``PlanVerdict``.

        The factory's whole justification is that Stage 2's ``until``
        reaches every charger the day it is written. A call site that
        constructs the verdict itself opts out of that silently — it
        keeps compiling, keeps passing, and just never gains the new
        field. That is the #683/#684 primary-vs-per-charger drift class
        in miniature, and it had already happened here: the legacy
        single-charger branch built its own ``PlanVerdict(hold=...)``
        and dropped the planner's reason text on the floor.
        """
        import inspect
        import io
        import tokenize

        from custom_components.solar_energy_management.coordinator import (
            coordinator as coord_mod,
        )

        src = inspect.getsource(coord_mod)
        code = " ".join(
            t.string
            for t in tokenize.generate_tokens(io.StringIO(src).readline)
            if t.type != tokenize.COMMENT
        )
        assert "PlanVerdict (" not in code and "PlanVerdict(" not in code, (
            "coordinator.py constructs a PlanVerdict directly — build it "
            "with verdict_from_night_plan() so Stage 2's `until` reaches "
            "this call site too"
        )

    def test_a_plan_missing_its_fields_does_not_hold(self):
        """Fail-open on a malformed plan.

        The overlay writes onto whatever object ``_compute_night_plan``
        returned, and that path is wrapped in a bare ``except`` precisely
        because a crash there must read as "no plan". A missing attribute
        has to land the same way — never as a silent refusal to charge.
        """
        assert verdict_from_night_plan(SimpleNamespace()).hold is False


class TestTheVerdictIsDayNightAgnostic:
    """(#638, day/night arc) Night is where planning is currently
    mandatory — prices and blocks are known ahead. A daytime planner
    (forecast windows, surplus placement) has the identical shape: "not
    now, later, here's why". It must populate THIS field rather than grow
    a second channel, because a second channel is how the night verdict
    got lost in the first place.
    """

    def test_no_field_is_named_for_the_night(self):
        """Structure, not prose — a field name is what binds the type to a
        time of day. ``tariff_wait`` is the cautionary example: a boolean
        named after the night's reason for holding, which is why nobody
        thought to consult it in a daytime path, and why it had nowhere to
        put "until when" or "why".
        """
        from dataclasses import fields

        bound = [f.name for f in fields(PlanVerdict)
                 if any(w in f.name for w in ("night", "tariff", "cheap",
                                              "solar", "overnight"))]
        assert not bound, (
            f"{bound} name a time of day or an energy source — a daytime "
            "planner would have to invent a parallel field instead of "
            "filling this one"
        )

    def test_the_verdict_is_pure(self):
        """No HA imports: the load intent layer must be able to share it."""
        import inspect

        from custom_components.solar_energy_management.coordinator import (
            plan_verdict,
        )

        assert "homeassistant" not in inspect.getsource(plan_verdict)


class TestStage2TheVerdictCarriesUntil:
    """(#638 Stage 2) One instant, one story: the ``until`` the user reads
    is the ``next_block_start`` the decision used."""

    def test_the_factory_reads_the_plans_next_window(self):
        from datetime import datetime
        when = datetime(2026, 8, 7, 22, 0)
        v = verdict_from_night_plan(SimpleNamespace(
            should_wait_for_cheap=True, reason="waiting", next_cheap_start=when))
        assert v.until == when

    def test_no_next_window_is_none(self):
        v = verdict_from_night_plan(SimpleNamespace(
            should_wait_for_cheap=True, reason="waiting"))
        assert v.until is None

    def test_decide_renders_the_until(self):
        from datetime import datetime
        d = decide(_night_view("min_plus_solar", plan=PlanVerdict(
            hold=True, reason="planned window ahead",
            until=datetime(2026, 8, 7, 22, 0))))
        assert "until 22:00" in d.reason
