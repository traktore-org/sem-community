"""#846 — SEM measures the result of every command it issues.

Guido, 26.08, watching PROD: *"the A to the charger is a choice of SEM,
therefore the math is not correcting itself. The idea is from EVCC: fire,
check, adjust."*

Live evidence: SEM commanded 16 A and believed it had bought
16 x 3 x 230 = 11.04 kW; the car drew 10.02 kW. A 1 kW, ~9 % gap on SEM's
own decision, re-issued every ten seconds, never questioned. The nameplate
conversion feeds the surplus->amps math, the night planner's block sizing,
the peak guard and the phase guard, so the error is systemic rather than
cosmetic.

The learner is deliberately timid, and the timidity is the design:

* **per (charger, phase count)** — the same car at 16 A is ~11 kW on three
  phases and ~3.7 kW on one, so one number would be wrong by 3x the moment
  a switch lands;
* **only while the belief is confirmed and steady** — no switch in flight,
  no taper, setpoint unchanged;
* **a sample implying a DIFFERENT phase count is refused, not absorbed** —
  otherwise the first serious phase-belief bug becomes invisible, smoothed
  into a plausible-looking constant. This is the clause that earns its keep;
* **bounded** to a sane band around nameplate — outside it something else is
  wrong and the honest answer is nameplate plus a diagnostic;
* **never widens a limit** — a measurement may lower what SEM believes it
  bought (freeing headroom), never justify exceeding a configured cap.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.watts_per_amp import (
    MIN_SAMPLES,
    WattsPerAmpLearner,
)

NOMINAL_3P = 3 * 230.0      # 690 W/A
NOMINAL_1P = 1 * 230.0      # 230 W/A


def _learn(l, cid="c1", phases=3, amps=16, watts=10020.0, n=MIN_SAMPLES,
           **kw):
    for _ in range(n):
        l.record(cid, phases=phases, commanded_amps=amps, observed_w=watts,
                 nominal_wpa=NOMINAL_3P if phases == 3 else NOMINAL_1P, **kw)
    return l


class TestItLearnsWhatTheCarActuallyTakes:
    def test_the_prod_case(self):
        """16 A -> 10.02 kW is 626 W/A, not the nameplate 690."""
        l = _learn(WattsPerAmpLearner())
        assert l.watts_per_amp("c1", 3) == pytest.approx(626.25, abs=1.0)
        assert l.watts_for_amps("c1", 3, 16, NOMINAL_3P) == pytest.approx(10020, abs=20)

    def test_nameplate_until_confidence_is_earned(self):
        l = _learn(WattsPerAmpLearner(), n=MIN_SAMPLES - 1)
        assert l.watts_per_amp("c1", 3) is None
        assert l.watts_for_amps("c1", 3, 16, NOMINAL_3P) == pytest.approx(11040)

    def test_it_is_a_median_not_a_mean(self):
        """One outlier cycle must not move the answer."""
        l = WattsPerAmpLearner()
        _learn(l, watts=10020.0, n=MIN_SAMPLES)
        l.record("c1", phases=3, commanded_amps=16, observed_w=7000.0,
                 nominal_wpa=NOMINAL_3P)
        assert l.watts_per_amp("c1", 3) == pytest.approx(626.25, abs=2.0)


class TestPhaseCountIsPartOfTheKey:
    def test_one_and_three_phase_are_separate_facts(self):
        l = WattsPerAmpLearner()
        _learn(l, phases=3, watts=10020.0)
        _learn(l, phases=1, amps=16, watts=3450.0)
        assert l.watts_per_amp("c1", 3) == pytest.approx(626.25, abs=1.0)
        assert l.watts_per_amp("c1", 1) == pytest.approx(215.6, abs=1.0)

    def test_an_unlearned_phase_falls_back_to_nameplate_not_the_other_phase(self):
        l = _learn(WattsPerAmpLearner(), phases=3)
        assert l.watts_per_amp("c1", 1) is None
        assert l.watts_for_amps("c1", 1, 16, NOMINAL_1P) == pytest.approx(3680)


class TestTheGates:
    def test_a_switch_in_flight_is_refused(self):
        l = _learn(WattsPerAmpLearner(), switch_in_flight=True)
        assert l.watts_per_amp("c1", 3) is None

    def test_a_tapering_car_teaches_nothing(self):
        l = _learn(WattsPerAmpLearner(), tapering=True)
        assert l.watts_per_amp("c1", 3) is None

    def test_an_unsteady_setpoint_is_refused(self):
        l = _learn(WattsPerAmpLearner(), setpoint_steady=False)
        assert l.watts_per_amp("c1", 3) is None

    def test_an_unconfirmed_belief_is_refused(self):
        l = _learn(WattsPerAmpLearner(), belief_confirmed=False)
        assert l.watts_per_amp("c1", 3) is None


class TestItRefusesWhatItCannotHonestlyExplain:
    def test_a_sample_implying_another_phase_count_is_refused(self):
        """A 3-phase belief with a draw that fits ONE phase is a phase-belief
        disagreement, not a 33 %-efficient car. Absorbing it would hide the
        very bug the contradiction cap exists to surface."""
        l = _learn(WattsPerAmpLearner(), phases=3, amps=16, watts=3600.0)
        assert l.watts_per_amp("c1", 3) is None
        assert l.refused("c1", 3) >= MIN_SAMPLES

    def test_a_draw_above_nameplate_is_refused(self):
        l = _learn(WattsPerAmpLearner(), watts=12000.0)
        assert l.watts_per_amp("c1", 3) is None

    def test_the_accepted_band_is_narrow(self):
        l = _learn(WattsPerAmpLearner(), watts=11040.0 * 0.80)
        assert l.watts_per_amp("c1", 3) is not None      # 80 % is plausible
        l2 = _learn(WattsPerAmpLearner(), watts=11040.0 * 0.60)
        assert l2.watts_per_amp("c1", 3) is None         # 60 % is not


class TestItNeverWidensALimit:
    def test_measured_may_lower_but_never_raise_the_belief(self):
        """A car drawing MORE than nameplate (bad voltage reading, wrong
        phase config) must not license SEM to believe it bought more."""
        l = WattsPerAmpLearner()
        for _ in range(MIN_SAMPLES):
            l.record("c1", phases=3, commanded_amps=16, observed_w=11500.0,
                     nominal_wpa=NOMINAL_3P)
        assert l.watts_for_amps("c1", 3, 16, NOMINAL_3P) <= 11040.0

    def test_amps_for_watts_rounds_down_with_the_measurement(self):
        """Converting a surplus into amps with a measured W/A must not hand
        out an amp the car will exceed."""
        l = _learn(WattsPerAmpLearner())
        assert l.amps_for_watts("c1", 3, 6000.0, NOMINAL_3P) == 9   # 6000/626 = 9.58


class TestTheDiagnosticSurface:
    def test_it_reports_what_it_knows(self):
        l = _learn(WattsPerAmpLearner())
        d = l.as_dict()
        assert d["c1"]["3"]["watts_per_amp"] == pytest.approx(626.25, abs=1.0)
        assert d["c1"]["3"]["samples"] >= MIN_SAMPLES
        # `in` alone would pass on a None — the ratio must be a real number,
        # because it is what tells a reader HOW far from nameplate this car is.
        d2 = l.as_dict_with_nominal(lambda cid, ph: NOMINAL_3P if ph == 3 else NOMINAL_1P)
        assert d2["c1"]["3"]["nominal_ratio"] == pytest.approx(0.908, abs=0.005)
        assert d2["c1"]["3"]["refused"] == 0


class TestRefusalsAreClassified:
    """A mutation check killed the first design: a separate "fits another
    phase count" gate passed every test even when removed, because the band
    already catches it for 1φ/3φ. The classification is the part that has a
    job — it points a reader at the phase belief instead of at this number."""

    def test_a_one_phase_draw_under_a_three_phase_belief_says_phase_belief(self):
        l = _learn(WattsPerAmpLearner(), phases=3, amps=16, watts=3600.0)
        assert l.watts_per_amp("c1", 3) is None
        assert l.refusal_reasons("c1", 3).get("phase_belief", 0) >= MIN_SAMPLES

    def test_a_merely_odd_draw_says_implausible(self):
        l = _learn(WattsPerAmpLearner(), phases=3, amps=16, watts=11040.0 * 0.55)
        assert l.watts_per_amp("c1", 3) is None
        r = l.refusal_reasons("c1", 3)
        assert r.get("implausible", 0) >= MIN_SAMPLES and "phase_belief" not in r


class TestTheGatesAreRealNotVacuous:
    """A getattr that never finds its attribute is a gate that never fires.
    The sequencer must actually answer the in-flight question."""

    def test_the_sequencer_answers_in_flight(self):
        from custom_components.solar_energy_management.coordinator.ev_phase_sequencer import (
            PhaseSwitchSequencer,
        )
        seq = PhaseSwitchSequencer()
        assert seq.in_flight is False
        seq._state = "stopping"
        assert seq.in_flight is True
        seq._state = "settling"
        assert seq.in_flight is True
        seq._state = "idle"
        assert seq.in_flight is False

    def test_the_coordinator_feeds_the_learner_from_the_trace_site(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import coordinator as cm
        src = inspect.getsource(cm)
        assert "_feed_wpa_learner(amps, observed, connected)" in src
        assert "_wpa_learner = WattsPerAmpLearner()" in src

    def test_the_adapter_conversions_consult_the_learner(self):
        import inspect
        from custom_components.solar_energy_management.coordinator.charger_adapters import base
        src = inspect.getsource(base)
        assert "_wpa_context" in src
        assert src.count("learner.watts_for_amps") == 1
        assert src.count("learner.amps_for_watts") == 1

    def test_the_taper_gate_asks_a_question_that_exists(self):
        """The first draft read `.tapering`, which no detector has — a gate
        that never fires. It must use the same `full_detected` SEM already
        publishes as `taper_detected`."""
        import inspect
        from custom_components.solar_energy_management.coordinator import coordinator as cm
        from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
            EVTaperDetector,
        )
        assert isinstance(getattr(EVTaperDetector, "full_detected", None), property)
        assert not hasattr(EVTaperDetector, "tapering")
        feeder = inspect.getsource(cm.SEMCoordinator._feed_wpa_learner)
        assert "full_detected" in feeder and ".tapering" not in feeder

    def test_the_belief_gate_reads_the_contradiction_counter(self):
        """Third vacuous gate of this build: _phase_conn_memo remembers
        whether the CAR IS PLUGGED IN, not whether the phase belief is
        disputed. Reading it left the gate permanently open."""
        import inspect
        from custom_components.solar_energy_management.coordinator import coordinator as cm
        feeder = inspect.getsource(cm.SEMCoordinator._feed_wpa_learner)
        # strip comments — the WRONG name is named in one, as the record of
        # why it is wrong, and a blunt substring test would fail on prose.
        code = "\n".join(l.split("#", 1)[0] for l in feeder.split("\n"))
        assert "_phase_contradictions" in code
        assert "_phase_conn_memo" not in code

    def test_every_gate_the_feeder_claims_is_wired_to_something_real(self):
        """One test that fails if any gate becomes a getattr against a name
        nothing sets — the failure mode this build hit three times."""
        import inspect
        from custom_components.solar_energy_management.coordinator import coordinator as cm
        feeder = inspect.getsource(cm.SEMCoordinator._feed_wpa_learner)
        for kw in ("belief_confirmed=", "setpoint_steady=",
                   "switch_in_flight=", "tapering="):
            assert kw in feeder, f"{kw} gate missing from the feed"
        # and none of them may be a bare literal
        for kw in ("belief_confirmed=True", "setpoint_steady=True",
                   "switch_in_flight=False", "tapering=False"):
            assert kw not in feeder, f"{kw} is hardcoded — the gate is theatre"


class TestNoMeasurementSaysWhy:
    """Live on .175 the learner reported nothing, and nothing distinguished
    "not fed" from "fed and refused". The second is a finding; the first is
    a bug. The surface must tell them apart."""

    def test_a_refused_bucket_appears_with_its_reason(self):
        l = _learn(WattsPerAmpLearner(), phases=3, amps=16, watts=4950.0)
        d = l.as_dict()
        row = d["c1"]["3"]
        assert row["watts_per_amp"] is None
        assert row["refused"] >= MIN_SAMPLES
        assert row["refusal_reasons"].get("phase_belief", 0) >= MIN_SAMPLES

    def test_the_prod_rig_case_is_a_phase_question_not_an_efficiency_one(self):
        """.175: 4950 W at 16 A = 309 W/A against a 690 nominal — 1.34 phases'
        worth. The honest answer is "your phase count is wrong", not
        "this car is 45 % efficient"."""
        l = _learn(WattsPerAmpLearner(), phases=3, amps=16, watts=4950.0)
        assert l.refusal_reasons("c1", 3).get("phase_belief", 0) >= MIN_SAMPLES
        assert l.watts_for_amps("c1", 3, 16, NOMINAL_3P) == pytest.approx(11040)

    def test_a_measured_bucket_still_carries_its_ratio(self):
        l = _learn(WattsPerAmpLearner())
        d = l.as_dict_with_nominal(lambda c, ph: NOMINAL_3P if ph == 3 else NOMINAL_1P)
        assert d["c1"]["3"]["nominal_ratio"] == pytest.approx(0.908, abs=0.005)
