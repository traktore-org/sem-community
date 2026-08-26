"""#846 — SEM measures the result of every command it issues.

Guido, 26.08, watching PROD: *"the A to the charger is a choice of SEM,
therefore the math is not correcting itself. The idea is from EVCC: fire,
check, adjust."*

Live evidence, PROD 26.08 (KEBA P30 + Renault Zoe, 3-phase, SEM's own
recorded ``commanded_current`` against the charger's power):

    commanded   drawn      W/A    of nameplate (690 W/A)
       8 A     3.32 kW     415        0.60
      10 A     5.13 kW     513        0.74
      12 A     7.13 kW     594        0.86
      14 A     8.57 kW     612        0.89
      16 A    10.02 kW     626        0.91

The FIRST build of this learner kept ONE watts-per-amp per (charger, phase
count). That table is the reason it was wrong: learned at 8 A it would have
predicted 6.6 kW for 16 A while the car takes 10.0 — a 3.4 kW error in the
one direction that breaches a budget. So the commanded SETPOINT is part of
the key. Between two measured setpoints the draw is interpolated linearly
in watts (a bridge, replaced by a measurement the moment SEM visits that
setpoint); outside the measured range it is nameplate.

The learner is deliberately timid, and the timidity is the design:

* **per (charger, phase count, commanded amps)**;
* **only while the belief is confirmed and steady** — no switch in flight,
  no taper, setpoint unchanged;
* **a sample implying a DIFFERENT phase count is refused, not absorbed**;
* **bounded** to a sane band around nameplate — wide enough for a Zoe at
  8 A (0.60), still closed to a 1-phase draw under a 3-phase belief (0.33);
* **never widens a limit** — a measurement may lower what SEM believes it
  bought, never justify exceeding a configured cap;
* **survives a restart** — learned state that gates behaviour is not
  allowed to die at boot (the #638 night-2 rule).
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.watts_per_amp import (
    MIN_SAMPLES,
    WattsPerAmpLearner,
)

NOMINAL_3P = 3 * 230.0      # 690 W/A
NOMINAL_1P = 1 * 230.0      # 230 W/A

#: PROD 26.08 — what the Zoe actually took at each setpoint (W).
ZOE = {8: 3320.0, 10: 5130.0, 12: 7130.0, 14: 8570.0, 16: 10020.0}


def _learn(l, cid="c1", phases=3, amps=16, watts=10020.0, n=MIN_SAMPLES,
           **kw):
    for _ in range(n):
        l.record(cid, phases=phases, commanded_amps=amps, observed_w=watts,
                 nominal_wpa=NOMINAL_3P if phases == 3 else NOMINAL_1P, **kw)
    return l


def _zoe(l=None, amps=ZOE, cid="c1"):
    l = l or WattsPerAmpLearner()
    for a in amps:
        _learn(l, cid=cid, amps=a, watts=ZOE[a])
    return l


class TestItLearnsWhatTheCarActuallyTakes:
    def test_the_prod_case(self):
        l = _learn(WattsPerAmpLearner())
        assert l.watts_per_amp("c1", 3, 16) == pytest.approx(626.25)
        assert l.watts_for_amps("c1", 3, 16, NOMINAL_3P) == pytest.approx(10020)

    def test_nameplate_until_confidence_is_earned(self):
        l = _learn(WattsPerAmpLearner(), n=MIN_SAMPLES - 1)
        assert l.watts_per_amp("c1", 3, 16) is None
        assert l.watts_for_amps("c1", 3, 16, NOMINAL_3P) == pytest.approx(11040)

    def test_it_is_a_median_not_a_mean(self):
        l = _learn(WattsPerAmpLearner(), n=MIN_SAMPLES)
        # one wild-but-in-band sample must not drag the estimate
        l.record("c1", phases=3, commanded_amps=16, observed_w=11500.0,
                 nominal_wpa=NOMINAL_3P)
        assert l.watts_per_amp("c1", 3, 16) == pytest.approx(626.25)


class TestTheSetpointIsPartOfTheKey:
    """The first build's one-number-per-phase model, measured against the
    car that disproved it."""

    def test_each_setpoint_learns_its_own_draw(self):
        l = _zoe()
        for a, w in ZOE.items():
            assert l.watts_for_amps("c1", 3, a, NOMINAL_3P) == pytest.approx(w)

    def test_learned_at_8_never_predicts_16(self):
        """THE unsafe case: 415 W/A x 16 = 6.6 kW; the car takes 10.0."""
        l = _zoe(amps=[8])
        assert l.watts_for_amps("c1", 3, 8, NOMINAL_3P) == pytest.approx(3320)
        assert l.watts_for_amps("c1", 3, 16, NOMINAL_3P) == pytest.approx(11040)

    def test_learned_at_16_never_predicts_8(self):
        """The wasteful twin: 626 x 8 = 5.0 kW promised, 3.3 kW drawn."""
        l = _zoe(amps=[16])
        assert l.watts_for_amps("c1", 3, 8, NOMINAL_3P) == pytest.approx(5520)

    def test_between_two_measured_setpoints_it_bridges_linearly_in_watts(self):
        l = _zoe(amps=[8, 16])
        # 3320 + (10020-3320)/8 per amp
        assert l.watts_for_amps("c1", 3, 12, NOMINAL_3P) == pytest.approx(6670)
        assert l.watts_for_amps("c1", 3, 10, NOMINAL_3P) == pytest.approx(4995)
        # the bridge is within 7 % of the Zoe's truth at every setpoint —
        # and a measurement replaces it the first time SEM stands there
        for a in (10, 12, 14):
            assert abs(l.watts_for_amps("c1", 3, a, NOMINAL_3P) - ZOE[a]) / ZOE[a] < 0.07

    def test_a_measurement_replaces_the_bridge(self):
        l = _zoe(amps=[8, 16])
        _learn(l, amps=12, watts=ZOE[12])
        assert l.watts_for_amps("c1", 3, 12, NOMINAL_3P) == pytest.approx(7130)
        # and the bridges on either side now run through the new point
        assert l.watts_for_amps("c1", 3, 10, NOMINAL_3P) == pytest.approx((3320 + 7130) / 2)

    def test_outside_the_measured_range_it_is_nameplate(self):
        l = _zoe(amps=[10, 12])
        assert l.watts_for_amps("c1", 3, 8, NOMINAL_3P) == pytest.approx(5520)
        assert l.watts_for_amps("c1", 3, 16, NOMINAL_3P) == pytest.approx(11040)

    def test_the_bridge_never_exceeds_nameplate(self):
        l = _zoe(amps=[8, 16])
        for a in range(8, 17):
            assert l.watts_for_amps("c1", 3, a, NOMINAL_3P) <= a * NOMINAL_3P + 1e-6

    def test_amps_are_bucketed_as_integers(self):
        l = WattsPerAmpLearner()
        _learn(l, amps=16.0)
        assert l.watts_per_amp("c1", 3, 16) == pytest.approx(626.25)


class TestAmpsForWattsWalksTheLadder:
    def test_it_finds_the_largest_setpoint_that_fits(self):
        l = _zoe()
        # nameplate says 5500 // 690 = 7 A; the flat 626 model says 8;
        # the car's own ladder says 10 A takes 5.13 kW and fits
        assert l.amps_for_watts("c1", 3, 5500.0, NOMINAL_3P, max_amps=16) == 10

    def test_unmeasured_is_the_old_nameplate_formula(self):
        l = WattsPerAmpLearner()
        assert l.amps_for_watts("c1", 3, 7000.0, NOMINAL_3P, max_amps=16) == int(7000 // 690)

    def test_it_rounds_down_never_up(self):
        l = _zoe()
        # 7130 exactly fits 12 A; one watt less must not
        assert l.amps_for_watts("c1", 3, 7130.0, NOMINAL_3P, max_amps=16) == 12
        assert l.amps_for_watts("c1", 3, 7129.0, NOMINAL_3P, max_amps=16) == 11

    def test_it_respects_the_ceiling(self):
        l = _zoe()
        assert l.amps_for_watts("c1", 3, 50000.0, NOMINAL_3P, max_amps=16) == 16

    def test_nothing_fits_is_zero(self):
        l = _zoe()
        assert l.amps_for_watts("c1", 3, 100.0, NOMINAL_3P, max_amps=16) == 0


class TestPhaseCountIsPartOfTheKey:
    def test_one_and_three_phase_are_separate_facts(self):
        l = WattsPerAmpLearner()
        _learn(l, phases=3, watts=10020.0)
        _learn(l, phases=1, watts=3400.0)
        assert l.watts_per_amp("c1", 3, 16) == pytest.approx(626.25)
        assert l.watts_per_amp("c1", 1, 16) == pytest.approx(212.5)

    def test_an_unlearned_phase_falls_back_to_nameplate_not_the_other_phase(self):
        l = _learn(WattsPerAmpLearner(), phases=3)
        assert l.watts_for_amps("c1", 1, 16, NOMINAL_1P) == pytest.approx(3680)


class TestTheGates:
    def test_a_switch_in_flight_is_refused(self):
        l = _learn(WattsPerAmpLearner(), switch_in_flight=True)
        assert l.watts_per_amp("c1", 3, 16) is None

    def test_a_tapering_car_teaches_nothing(self):
        l = _learn(WattsPerAmpLearner(), tapering=True)
        assert l.watts_per_amp("c1", 3, 16) is None

    def test_an_unsteady_setpoint_is_refused(self):
        l = _learn(WattsPerAmpLearner(), setpoint_steady=False)
        assert l.watts_per_amp("c1", 3, 16) is None

    def test_an_unconfirmed_belief_is_refused(self):
        l = _learn(WattsPerAmpLearner(), belief_confirmed=False)
        assert l.watts_per_amp("c1", 3, 16) is None


class TestItRefusesWhatItCannotHonestlyExplain:
    def test_a_one_phase_draw_under_a_three_phase_belief_is_refused(self):
        l = _learn(WattsPerAmpLearner(), phases=3, watts=3680.0)   # 230 W/A = 0.33
        assert l.watts_per_amp("c1", 3, 16) is None
        assert l.refused("c1", 3) == MIN_SAMPLES

    def test_a_draw_above_nameplate_is_refused(self):
        l = _learn(WattsPerAmpLearner(), watts=12500.0)             # 1.13x
        assert l.watts_per_amp("c1", 3, 16) is None

    def test_a_low_amps_partial_draw_is_a_fact_not_a_fault(self):
        """The Zoe at 8 A draws 60 % of nameplate, steadily, every day.
        The first build's 0.75 floor refused it; the band must admit it."""
        l = _learn(WattsPerAmpLearner(), amps=8, watts=ZOE[8])      # 0.60x
        assert l.watts_per_amp("c1", 3, 8) == pytest.approx(415)
        assert l.refused("c1", 3) == 0

    def test_the_175_rig_is_still_refused(self):
        """4950 W at 16 A = 309 W/A = 0.45x — a phase question, refused."""
        l = _learn(WattsPerAmpLearner(), watts=4950.0)
        assert l.watts_per_amp("c1", 3, 16) is None
        assert l.refused("c1", 3) == MIN_SAMPLES

    def test_the_accepted_band(self):
        from custom_components.solar_energy_management.coordinator import watts_per_amp as m
        assert m.MIN_RATIO == 0.5
        assert m.MAX_RATIO == 1.05


class TestItNeverWidensALimit:
    def test_measured_may_lower_but_never_raise_the_belief(self):
        l = _learn(WattsPerAmpLearner(), watts=11300.0)             # 1.02x — in band
        assert l.watts_for_amps("c1", 3, 16, NOMINAL_3P) == pytest.approx(11040)

    def test_amps_for_watts_rounds_down_with_the_measurement(self):
        l = _learn(WattsPerAmpLearner())
        # 10020 W buys exactly the measured 16 A. A watt less: 15 A is
        # UNMEASURED with only one bucket, so it is nameplate (10350 W) and
        # does not fit either — 14 A (9660 W) is the honest answer. Never a
        # setpoint SEM has no evidence for.
        assert l.amps_for_watts("c1", 3, 10020.0, NOMINAL_3P, max_amps=32) == 16
        assert l.amps_for_watts("c1", 3, 10019.0, NOMINAL_3P, max_amps=32) == 14
        # with the Zoe's 8 A bucket too, 15 A is bridged (9182 W) and fits
        _learn(l, amps=8, watts=ZOE[8])
        assert l.amps_for_watts("c1", 3, 10019.0, NOMINAL_3P, max_amps=32) == 15


class TestItSurvivesARestart:
    def test_state_round_trips(self):
        a = _zoe()
        _learn(a, amps=16, watts=3680.0)   # a refusal on the record too
        b = WattsPerAmpLearner()
        b.restore(a.as_state())
        for amps in ZOE:
            assert b.watts_per_amp("c1", 3, amps) == pytest.approx(
                a.watts_per_amp("c1", 3, amps), abs=0.01)   # stored to 2 dp
        assert b.refused("c1", 3) == a.refused("c1", 3)
        assert b.refusal_reasons("c1", 3) == a.refusal_reasons("c1", 3)

    def test_the_state_is_json_safe(self):
        import json
        s = _zoe().as_state()
        assert json.loads(json.dumps(s)) == s

    def test_a_corrupt_entry_is_dropped_alone(self):
        s = _zoe().as_state()
        # poison one bucket, keep the others
        k16 = next(k for k in s["samples"] if k.endswith("|16"))
        s["samples"][k16] = ["not", "numbers"]
        s["samples"]["garbage"] = [1, 2, 3]
        b = WattsPerAmpLearner()
        b.restore(s)
        assert b.watts_per_amp("c1", 3, 16) is None
        assert b.watts_per_amp("c1", 3, 8) == pytest.approx(415)

    def test_restoring_nothing_is_a_no_op(self):
        b = WattsPerAmpLearner()
        b.restore(None)
        b.restore({})
        b.restore("nonsense")
        assert b.as_dict() == {}

    def test_cold_is_a_question_per_charger_and_phase_count(self):
        l = WattsPerAmpLearner()
        assert l.is_cold("c1", 3)
        l.record("c1", phases=3, commanded_amps=16, observed_w=10020.0,
                 nominal_wpa=NOMINAL_3P)
        assert not l.is_cold("c1", 3)
        # a refusal is also evidence of having been fed…
        r = _learn(WattsPerAmpLearner(), cid="c2", watts=3680.0)
        assert not r.is_cold("c2", 3)
        # …under THAT phase count. PROD 26.08: a day refused under a mis-set
        # ev_phases=1 must not stop the corrected count from replaying.
        assert r.is_cold("c2", 1)


class TestTheDiagnosticSurface:
    def test_it_reports_a_table_per_charger_and_phase(self):
        d = _zoe(amps=[8, 16]).as_dict_with_nominal(
            lambda c, ph: NOMINAL_3P if ph == 3 else NOMINAL_1P)
        row = d["c1"]["3"]
        assert row["table"] == {"8": 415.0, "16": 626.2}
        assert row["samples"] == {"8": MIN_SAMPLES, "16": MIN_SAMPLES}
        assert row["nominal_ratio"]["8"] == pytest.approx(0.601, abs=0.002)
        assert row["nominal_ratio"]["16"] == pytest.approx(0.908, abs=0.002)
        assert row["refused"] == 0

    def test_a_bucket_below_confidence_is_not_in_the_table(self):
        l = _zoe(amps=[16])
        _learn(l, amps=10, watts=ZOE[10], n=MIN_SAMPLES - 1)
        row = l.as_dict()["c1"]["3"]
        assert "10" not in row["table"]
        assert row["samples"]["10"] == MIN_SAMPLES - 1


class TestRefusalsAreClassified:
    def test_a_one_phase_draw_under_a_three_phase_belief_says_phase_belief(self):
        l = _learn(WattsPerAmpLearner(), phases=3, watts=3680.0)
        assert l.refusal_reasons("c1", 3) == {"phase_belief": MIN_SAMPLES}

    def test_a_merely_odd_draw_says_implausible(self):
        l = _learn(WattsPerAmpLearner(), phases=3, watts=12500.0)
        assert l.refusal_reasons("c1", 3) == {"implausible": MIN_SAMPLES}


class TestTheGatesAreRealNotVacuous:
    """A getattr that never finds its attribute is a gate that never fires."""

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

    def test_the_feed_is_per_charger_not_the_fleet_trace(self):
        """The first wiring fed from `_trace_ev`, which holds the FLEET
        ``power.ev_power`` and whichever device was bound last — on a
        two-charger install that attributes both cars' draw to one of them
        (docs/MULTI_CHARGER.md, the class this repo has shipped four
        hotfixes for). The feed lives in the per-charger loop, with THIS
        charger's power and THIS charger's setpoint."""
        import inspect
        from custom_components.solar_energy_management.coordinator import coordinator as cm
        assert "_feed_wpa_learner" not in inspect.getsource(cm.SEMCoordinator._trace_ev)
        src = inspect.getsource(cm.SEMCoordinator._async_update_data)
        assert "_feed_wpa_learner(cid, ev_dev, charger_power" in src
        feeder = inspect.getsource(cm.SEMCoordinator._feed_wpa_learner)
        code = "\n".join(l.split("#", 1)[0] for l in feeder.split("\n"))
        assert "power.ev_power" not in code
        assert "_ev_device" not in code

    def test_the_adapter_conversions_consult_the_learner(self):
        import inspect
        from custom_components.solar_energy_management.coordinator.charger_adapters import base
        src = inspect.getsource(base)
        assert "_wpa_context" in src
        assert src.count("learner.watts_for_amps") == 1
        assert src.count("learner.amps_for_watts") == 1

    def test_the_taper_gate_asks_a_question_that_exists(self):
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
        import inspect
        from custom_components.solar_energy_management.coordinator import coordinator as cm
        src = inspect.getsource(cm.SEMCoordinator._wpa_phases_for)
        code = "\n".join(l.split("#", 1)[0] for l in src.split("\n"))
        assert "_phase_contradictions" in code
        assert "_phase_conn_memo" not in code

    def test_every_gate_the_feeder_claims_is_wired_to_something_real(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import coordinator as cm
        feeder = inspect.getsource(cm.SEMCoordinator._feed_wpa_learner)
        for kw in ("belief_confirmed=", "setpoint_steady=",
                   "switch_in_flight=", "tapering="):
            assert kw in feeder, f"{kw} gate missing from the feed"
        for kw in ("belief_confirmed=True", "setpoint_steady=True",
                   "switch_in_flight=False", "tapering=False"):
            assert kw not in feeder, f"{kw} is hardcoded — the gate is theatre"


class TestNoMeasurementSaysWhy:
    def test_a_refused_bucket_appears_with_its_reason(self):
        l = _learn(WattsPerAmpLearner(), phases=3, amps=16, watts=4950.0)
        row = l.as_dict()["c1"]["3"]
        assert row["table"] == {}
        assert row["refused"] >= MIN_SAMPLES
        assert row["refusal_reasons"].get("phase_belief", 0) >= MIN_SAMPLES

    def test_the_prod_rig_case_is_a_phase_question_not_an_efficiency_one(self):
        l = _learn(WattsPerAmpLearner(), phases=3, amps=16, watts=4950.0)
        assert l.refusal_reasons("c1", 3).get("phase_belief", 0) >= MIN_SAMPLES
        assert l.watts_for_amps("c1", 3, 16, NOMINAL_3P) == pytest.approx(11040)


def _prod_coordinator(*, observer=False, switching=False, believed=None,
                      contradictions=0, full=False, connected=True,
                      chargers=("keba_prod",)):
    """PROD's install as the feeder sees it, straight after a restart:
    ``_phase_believed`` EMPTY (no switch entity, and the car has not
    charged since boot). The first build refused everything in this state."""
    from types import SimpleNamespace
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    c = SEMCoordinator.__new__(SEMCoordinator)
    c._wpa_learner = WattsPerAmpLearner()
    c._observer_mode = observer
    c.config = {"ev_voltage": 230, "ev_chargers": [
        {"id": cid, "ev_phases": 3, "ev_voltage": 230, "ev_max_current": 16,
         "ev_min_current": 8,
         "ev_phase_switching_enabled": switching,
         "ev_phase_switch_entity": "number.box_phases" if switching else None}
        for cid in chargers]}
    c._ev_devices = {cid: SimpleNamespace(charger_id=cid, _current_setpoint=0.0)
                     for cid in chargers}
    c._phase_believed = {} if believed is None else {cid: believed for cid in chargers}
    c._phase_contradictions = {cid: {"count": contradictions} for cid in chargers}
    c._phase_sequencers = {}
    c._ev_taper_detectors = {cid: SimpleNamespace(full_detected=full) for cid in chargers}
    c._ev_taper_detector = SimpleNamespace(full_detected=False)
    c._last_ev_connected_per_charger = {cid: connected for cid in chargers}
    c._ev_wpa_ema = {}
    c._storage = None
    return c


def _drive(c, amps=16, watts=10020.0, cycles=MIN_SAMPLES + 1, cid="keba_prod"):
    dev = c._ev_devices[cid]
    for _ in range(cycles):
        dev._current_setpoint = float(amps)
        c._feed_wpa_learner(cid, dev, float(watts),
                            c._last_ev_connected_per_charger.get(cid, False))


class TestTheWholeChainOnProdsRealNumbers:
    """.175 cannot prove this (observer mode never commands, so there is
    nothing to check). PROD is the only non-observer instance and the one
    that produced the evidence — the chain is proven here, driving the REAL
    feeder with PROD's measured values and PROD's real post-restart state."""

    def test_it_learns_on_an_install_without_phase_switching(self):
        """PROD: no switch entity, `_phase_believed` empty. The configured
        phase count IS the belief there — there is no machinery to dispute
        it, and the learner's own band is the only honest check."""
        c = _prod_coordinator()
        _drive(c)
        assert c._wpa_learner.watts_per_amp("keba_prod", 3, 16) == pytest.approx(626.25)

    def test_the_zoe_ladder_through_the_real_feeder(self):
        c = _prod_coordinator()
        for a, w in ZOE.items():
            _drive(c, amps=a, watts=w)
        for a, w in ZOE.items():
            assert c._wpa_learner.watts_for_amps("keba_prod", 3, a, NOMINAL_3P) == pytest.approx(w)

    def test_the_first_cycle_teaches_nothing_because_nothing_is_steady_yet(self):
        c = _prod_coordinator()
        _drive(c, cycles=1)
        assert c._wpa_learner.as_dict() == {}

    def test_a_ramping_setpoint_teaches_nothing(self):
        c = _prod_coordinator()
        for a in (8, 10, 12, 14, 16, 14, 12, 10, 8, 10, 12):
            _drive(c, amps=a, watts=a * 626.0, cycles=1)
        assert c._wpa_learner.as_dict() == {}

    def test_observer_mode_never_learns(self):
        c = _prod_coordinator(observer=True)
        _drive(c)
        assert c._wpa_learner.as_dict() == {}

    def test_a_disconnected_car_never_learns(self):
        c = _prod_coordinator(connected=False)
        _drive(c)
        assert c._wpa_learner.as_dict() == {}

    def test_with_switching_the_belief_must_exist_and_be_undisputed(self):
        c = _prod_coordinator(switching=True, believed=None)
        _drive(c)
        assert c._wpa_learner.as_dict() == {}
        c = _prod_coordinator(switching=True, believed=3, contradictions=1)
        _drive(c)
        assert c._wpa_learner.as_dict() == {}
        c = _prod_coordinator(switching=True, believed=3)
        _drive(c)
        assert c._wpa_learner.watts_per_amp("keba_prod", 3, 16) == pytest.approx(626.25)

    def test_with_switching_the_belief_keys_the_bucket_not_the_config(self):
        c = _prod_coordinator(switching=True, believed=1)
        _drive(c, watts=3400.0)
        assert c._wpa_learner.watts_per_amp("keba_prod", 1, 16) == pytest.approx(212.5)
        assert c._wpa_learner.watts_per_amp("keba_prod", 3, 16) is None

    def test_a_switch_in_flight_never_learns(self):
        from custom_components.solar_energy_management.coordinator.ev_phase_sequencer import (
            PhaseSwitchSequencer,
        )
        c = _prod_coordinator()
        seq = PhaseSwitchSequencer()
        seq._state = "settling"
        c._phase_sequencers = {"keba_prod": seq}
        _drive(c)
        assert c._wpa_learner.as_dict() == {}

    def test_a_full_car_never_learns(self):
        c = _prod_coordinator(full=True)
        _drive(c)
        assert c._wpa_learner.as_dict() == {}

    def test_two_chargers_learn_their_own_draw(self):
        """The fleet-read class: each charger's samples come from ITS power."""
        c = _prod_coordinator(chargers=("a", "b"))
        _drive(c, cid="a", amps=16, watts=10020.0)
        _drive(c, cid="b", amps=16, watts=3400.0)
        assert c._wpa_learner.watts_per_amp("a", 3, 16) == pytest.approx(626.25)
        assert c._wpa_learner.watts_per_amp("b", 3, 16) is None      # 0.31x → refused
        assert c._wpa_learner.refusal_reasons("b", 3) == {"phase_belief": MIN_SAMPLES}

    def test_and_then_the_conversion_returns_the_measured_watts(self):
        from types import SimpleNamespace
        from custom_components.solar_energy_management.coordinator.charger_adapters.base import (
            ChargerAdapter,
        )
        c = _prod_coordinator()
        _drive(c)
        dev = SimpleNamespace(charger_id="keba_prod", _coordinator=c)

        class A(ChargerAdapter):
            phases = 3
            voltage = 230
            max_current_a = 16
            min_current_a = 8

            def __init__(self):
                self._device = dev

            # the abstract surface the conversion never touches
            def actual_charging(self, *a, **k): return False
            def can_command_zero(self, *a, **k): return False
            async def command_current(self, *a, **k): return None
            async def command_disable(self, *a, **k): return None
            async def command_idle(self, *a, **k): return None
            async def command_max(self, *a, **k): return None
            def handshake_power_w(self, *a, **k): return 0.0
            def is_self_charging(self, *a, **k): return False

        a = A()
        assert a.watts_for_amps(16) == pytest.approx(10020)
        assert a.amps_for_watts(10020.0) == 16
        # 15 A is unmeasured → nameplate → does not fit → 14 (never a guess)
        assert a.amps_for_watts(10019.0) == 14
        _drive(c, amps=8, watts=3320.0)          # …until 8 A is measured too
        assert a.amps_for_watts(10019.0) == 15   # bridged 9182 W fits


class TestTheOldAccessorReadsTheLearnerFirst:
    """`_ev_watts_per_amp` (#638) is what the night packer and the
    deadline floor size blocks from. Three sources, one order:
    learned table → the #716 EMA it used to be → nameplate."""

    def test_nameplate_when_nothing_is_known(self):
        c = _prod_coordinator()
        cfg = c.config["ev_chargers"][0]
        assert c._ev_watts_per_amp("keba_prod", cfg) == pytest.approx(690)

    def test_the_ema_when_the_learner_is_cold(self):
        c = _prod_coordinator()
        c._ev_wpa_ema["keba_prod"] = 600.0
        cfg = c.config["ev_chargers"][0]
        assert c._ev_watts_per_amp("keba_prod", cfg) == pytest.approx(600)

    def test_the_learner_at_max_amps_once_measured(self):
        c = _prod_coordinator()
        c._ev_wpa_ema["keba_prod"] = 600.0
        _drive(c)
        cfg = c.config["ev_chargers"][0]
        assert c._ev_watts_per_amp("keba_prod", cfg) == pytest.approx(626.25)

    def test_block_sizing_uses_the_table_per_setpoint(self):
        """The packer's EV block: min at 8 A is 3.3 kW on this car, not
        8 x 626 = 5.0 kW — the difference between a slot under the peak
        and 'unplaceable'."""
        c = _prod_coordinator()
        for a, w in ZOE.items():
            _drive(c, amps=a, watts=w)
        cfg = c.config["ev_chargers"][0]
        assert c._ev_watts_for_amps("keba_prod", cfg, 8) == pytest.approx(3320)
        assert c._ev_watts_for_amps("keba_prod", cfg, 16) == pytest.approx(10020)
        cold = _prod_coordinator()
        assert cold._ev_watts_for_amps("keba_prod", cfg, 8) == pytest.approx(5520)
