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


class TestCoordinatorWiring:
    """(Phase B) The per-charger tick: capability from config, belief from
    the W/A estimate, hold overrides the decision to IDLE, the switch is
    ONE service call behind the observer seam."""

    def _host(self, observer=False, cfg=None):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock
        from custom_components.solar_energy_management.coordinator import (
            ev_control,
        )
        h = SimpleNamespace()
        h._phase_switch_tick = ev_control.EVControlMixin._phase_switch_tick.__get__(h)
        h._observer_mode = observer
        h._surplus_controller = None
        sun = MagicMock()
        h.hass = SimpleNamespace(
            states=SimpleNamespace(get=lambda eid: sun),
            services=SimpleNamespace(async_call=AsyncMock()),
        )
        h.cfg = cfg if cfg is not None else {
            "ev_phase_switch_entity": "number.keba_phases",
            "phase_mode": "1",
            "ev_voltage": 230,
            "ev_min_current": 6,
        }
        return h

    def _decision(self, amps=10, budget=4600.0):
        from custom_components.solar_energy_management.coordinator.charger_types import (
            ChargerDecision, ChargerIntent,
        )
        return ChargerDecision(
            charger_id="c1", mode="solar_only",
            intent=ChargerIntent.CHARGE_AT_AMPS,
            commanded_amps=amps, budget_w=budget, reason="test")

    def _cp(self, power_w, charging, connected=True):
        from custom_components.solar_energy_management.coordinator.charger_types import (
            ChargerPower,
        )
        return ChargerPower(charger_id="c1", power_w=power_w,
                            connected=connected, charging=charging)

    def test_manual_switch_walks_the_sequence(self):
        import asyncio
        from custom_components.solar_energy_management.coordinator.charger_types import (
            ChargerIntent,
        )
        from custom_components.solar_energy_management.coordinator.ev_phase_sequencer import (
            SETTLE_S,
        )
        h = self._host()
        run = lambda d, cp, t: asyncio.run(
            h._phase_switch_tick("c1", h.cfg, d, cp, t))
        # charging 3-phase at 10A: 6900W → belief 3; user wants 1
        d = run(self._decision(amps=10), self._cp(6900.0, True), 0.0)
        assert d.intent is ChargerIntent.IDLE, "stopping must hold charging"
        assert "phase switch" in d.reason
        # draw stops → the ONE service call fires
        d = run(self._decision(amps=10), self._cp(0.0, False), 30.0)
        assert d.intent is ChargerIntent.IDLE, "settling still holds"
        h.hass.services.async_call.assert_awaited_once()
        call = h.hass.services.async_call.await_args
        assert call.args[0] == "number" and call.args[1] == "set_value"
        assert call.args[2] == {"entity_id": "number.keba_phases", "value": 1.0}
        # settle over → decision passes through untouched
        d0 = self._decision(amps=6)
        d = run(d0, self._cp(0.0, False), 30.0 + SETTLE_S + 1)
        assert d is d0

    def test_observer_mode_never_calls_the_service(self):
        import asyncio
        h = self._host(observer=True)
        run = lambda d, cp, t: asyncio.run(
            h._phase_switch_tick("c1", h.cfg, d, cp, t))
        run(self._decision(amps=10), self._cp(6900.0, True), 0.0)
        run(self._decision(amps=10), self._cp(0.0, False), 30.0)
        h.hass.services.async_call.assert_not_awaited()

    def test_no_capability_passes_through(self):
        import asyncio
        h = self._host(cfg={"phase_mode": "1"})
        d0 = self._decision()
        d = asyncio.run(h._phase_switch_tick(
            "c1", h.cfg, d0, self._cp(6900.0, True), 0.0))
        assert d is d0
        assert not hasattr(h, "_phase_sequencers") or not getattr(
            h, "_phase_sequencers", {})
