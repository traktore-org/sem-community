"""#804 Phase B+C — the phase-switch sequencer and the auto planner.

evcc's field history says mid-charge switching is where the quirks live
(Easee cloud pauses, Zaptec ignoring switches, cars hanging), so SEM's
default sequence is stop → switch → settle → start — ~90 s per switch,
buying away the whole quirk class. The sequencer is pure (clock passed
in); the auto planner adds hysteresis + hard caps evcc doesn't have.
"""

from custom_components.solar_energy_management.coordinator.ev_phase_sequencer import (
    MIN_SWITCH_GAP_S, SETTLE_S, AUTO_UP_DELAY_S, AUTO_DOWN_DELAY_S,
    AUTO_MIN_INTERVAL_S, AUTO_MAX_PER_SESSION,
    PhaseAutoPlanner, PhaseSwitchSequencer,
)


def _run(seq, now, desired, believed, charging, ready=True):
    return seq.tick(now=now, desired_phases=desired, believed_phases=believed,
                    charging=charging, capability_ready=ready)


class TestSequence:

    def test_idle_when_nothing_desired(self):
        seq = PhaseSwitchSequencer()
        r = _run(seq, 0.0, None, 3, charging=True)
        assert r.state == "idle"
        assert not r.hold_charging
        assert r.issue_switch is None

    def test_full_sequence_stop_switch_settle(self):
        seq = PhaseSwitchSequencer()
        # trigger: user wants 1p, charger believed on 3p, car charging
        r = _run(seq, 0.0, 1, 3, charging=True)
        assert r.state == "stopping"
        assert r.hold_charging is True
        assert r.issue_switch is None
        # still drawing — keep holding, never switch under load
        r = _run(seq, 30.0, 1, 3, charging=True)
        assert r.state == "stopping"
        # draw stopped — the switch fires exactly once
        r = _run(seq, 60.0, 1, 3, charging=False)
        assert r.state == "settling"
        assert r.issue_switch == 1
        # settling: hold, no second switch
        r = _run(seq, 90.0, 1, 3, charging=False)
        assert r.state == "settling"
        assert r.issue_switch is None
        assert r.hold_charging is True
        # settle window over — release; believed follows the command
        r = _run(seq, 60.0 + SETTLE_S + 1, 1, None, charging=False)
        assert r.state == "idle"
        assert not r.hold_charging
        assert r.believed_phases == 1

    def test_not_charging_skips_straight_to_switch(self):
        seq = PhaseSwitchSequencer()
        r = _run(seq, 0.0, 3, 1, charging=False)
        assert r.state == "settling"
        assert r.issue_switch == 3

    def test_desired_equals_believed_is_a_noop(self):
        seq = PhaseSwitchSequencer()
        r = _run(seq, 0.0, 3, 3, charging=True)
        assert r.state == "idle"
        assert r.issue_switch is None

    def test_capability_lost_aborts_safely(self):
        seq = PhaseSwitchSequencer()
        _run(seq, 0.0, 1, 3, charging=True)          # stopping
        r = _run(seq, 30.0, 1, 3, charging=True, ready=False)
        assert r.state == "idle"
        assert not r.hold_charging
        assert r.issue_switch is None

    def test_min_gap_between_switches(self):
        seq = PhaseSwitchSequencer()
        _run(seq, 0.0, 1, 3, charging=False)          # switch #1 at t=0
        _run(seq, SETTLE_S + 1, 1, None, charging=False)  # settled
        # immediately ask back to 3 — refused inside the gap
        r = _run(seq, SETTLE_S + 2, 3, 1, charging=False)
        assert r.state == "idle"
        assert r.issue_switch is None
        # after the gap it goes through
        r = _run(seq, MIN_SWITCH_GAP_S + 1, 3, 1, charging=False)
        assert r.issue_switch == 3


class TestAutoPlanner:
    """Scale down when 3p can't hold min current on the surplus; scale up
    when surplus sustains 3p at min + margin. Asymmetric delays, hard
    min-interval, session cap — the contactor-protection philosophy."""

    def _p(self):
        return PhaseAutoPlanner(min_current_a=6, voltage=230.0)

    def test_down_after_sustained_starvation(self):
        p = self._p()
        # 3p min = 4140 W; surplus stuck at 2000 W
        t = 0.0
        assert p.desired(t, believed=3, surplus_w=2000.0) is None
        t = AUTO_DOWN_DELAY_S + 1
        assert p.desired(t, believed=3, surplus_w=2000.0) == 1

    def test_up_after_sustained_headroom(self):
        p = self._p()
        # 3p min + 10% margin = ~4554 W; surplus 5200 W sustained
        t = 0.0
        assert p.desired(t, believed=1, surplus_w=5200.0) is None
        t = AUTO_UP_DELAY_S + 1
        assert p.desired(t, believed=1, surplus_w=5200.0) == 3

    def test_a_blip_resets_the_timer(self):
        p = self._p()
        p.desired(0.0, believed=1, surplus_w=5200.0)
        p.desired(AUTO_UP_DELAY_S / 2, believed=1, surplus_w=1000.0)  # blip
        r = p.desired(AUTO_UP_DELAY_S + 1, believed=1, surplus_w=5200.0)
        assert r is None, "the sustain clock must restart after the blip"

    def test_min_interval_between_auto_switches(self):
        p = self._p()
        assert p.desired(0.0, believed=3, surplus_w=2000.0) is None
        t = AUTO_DOWN_DELAY_S + 1
        assert p.desired(t, believed=3, surplus_w=2000.0) == 1
        p.note_switched(t)
        # headroom returns quickly — but the interval gate holds
        t2 = t + AUTO_UP_DELAY_S + 2
        assert p.desired(t2, believed=1, surplus_w=6000.0) is None
        t3 = t + AUTO_MIN_INTERVAL_S + AUTO_UP_DELAY_S + 2
        assert p.desired(t3, believed=1, surplus_w=6000.0) == 3

    def test_session_cap(self):
        p = self._p()
        t = 0.0
        for _ in range(AUTO_MAX_PER_SESSION):
            p.note_switched(t)
            t += AUTO_MIN_INTERVAL_S + AUTO_DOWN_DELAY_S + 10
        # cap reached — no further auto switches this session
        t += AUTO_DOWN_DELAY_S + 1
        assert p.desired(t, believed=3, surplus_w=1000.0) is None
        p.new_session()
        t += AUTO_DOWN_DELAY_S + 1
        assert p.desired(t, believed=3, surplus_w=1000.0) == 1

    def test_unknown_believed_stays_quiet(self):
        p = self._p()
        assert p.desired(0.0, believed=None, surplus_w=6000.0) is None


class TestInertness:

    def test_module_is_pure(self):
        import ast, inspect
        from custom_components.solar_energy_management.coordinator import (
            ev_phase_sequencer,
        )
        tree = ast.parse(inspect.getsource(ev_phase_sequencer))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mod = getattr(node, "module", "") or ""
                names = [a.name for a in node.names]
                for n in [mod] + names:
                    assert not n.startswith("homeassistant"), (
                        f"sequencer must stay pure, imports {n}")
