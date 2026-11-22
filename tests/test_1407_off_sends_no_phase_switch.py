"""#1407 round 2 — Off sends no phase switch either.

Since #898 charge mode Off means SEM sends nothing to the charger. The
phase switch tick did not ask: with phase switching on, the 0 W an Off
charger is offered made the Auto planner ask for one phase, and the switch
went out while another system ran the box (the review of #1407 found it
behind the new Off hint, "Then SEM sends nothing"). A manual phase target
fired once too, and a switch already in flight went on.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.solar_energy_management.coordinator import ev_control
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision, ChargerIntent, ChargerPower,
)
from custom_components.solar_energy_management.coordinator.ev_phase_sequencer import (
    AUTO_DOWN_DELAY_S, AUTO_MIN_INTERVAL_S, SETTLE_S, STOP_WAIT_S,
)


def _host(**cfg_over):
    h = SimpleNamespace()
    h._phase_switch_tick = ev_control.EVControlMixin._phase_switch_tick.__get__(h)
    h._observer_mode = False
    h._surplus_controller = None
    h.config = {}
    h.hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda eid: MagicMock()),
        services=SimpleNamespace(async_call=AsyncMock()),
    )
    h.cfg = {
        "ev_phase_switch_entity": "number.box_phases",
        "ev_phase_switching_enabled": True,
        "phase_mode": "auto",
        "ev_voltage": 230.0, "ev_min_current": 6, "ev_max_current": 16,
    }
    h.cfg.update(cfg_over)
    return h


def _max():
    return ChargerDecision(charger_id="c1", mode="always_max",
                           intent=ChargerIntent.CHARGE_MAX, commanded_amps=0,
                           budget_w=0.0, reason="max")


def _off():
    return ChargerDecision(charger_id="c1", mode="off",
                           intent=ChargerIntent.RELEASE, commanded_amps=0,
                           budget_w=0.0, reason="off")


def _cp(power_w, charging=True):
    return ChargerPower(charger_id="c1", power_w=power_w, connected=True,
                        charging=charging)


def _tick(h, decision, cp, t):
    return asyncio.run(h._phase_switch_tick("c1", h.cfg, decision, cp, t,
                                            setpoint_a=16))


def _calls(h):
    return h.hass.services.async_call.await_count


def test_auto_sends_no_switch_to_an_off_charger():
    """Three phases learned under Always (max); then Off while another
    system charges, stops, and the box sits idle past the down delay."""
    h = _host()
    _tick(h, _max(), _cp(11000.0), 0.0)
    assert h._phase_believed["c1"] == 3
    t = 10.0
    while t < AUTO_DOWN_DELAY_S + AUTO_MIN_INTERVAL_S + 60:
        d = _tick(h, _off(), _cp(0.0, charging=False), t)
        assert d.intent is ChargerIntent.RELEASE
        t += 10.0
    assert _calls(h) == 0, "a phase switch went to a charger in Off"
    assert h._phase_switch_states["c1"] == "idle"


def test_the_same_idle_box_is_switched_when_sem_drives_it():
    """The twin: SEM's own Auto still switches — the gate is Off only."""
    h = _host()
    _tick(h, _max(), _cp(11000.0), 0.0)
    idle = ChargerDecision(charger_id="c1", mode="solar_only",
                           intent=ChargerIntent.IDLE, commanded_amps=0,
                           budget_w=0.0, reason="no sun")
    t = 10.0
    while t < AUTO_DOWN_DELAY_S + AUTO_MIN_INTERVAL_S + 60 and not _calls(h):
        _tick(h, idle, _cp(0.0, charging=False), t)
        t += 10.0
    assert _calls(h) == 1


def test_a_manual_target_sends_nothing_in_off():
    h = _host(phase_mode="1")
    for i in range(5):
        _tick(h, _off(), _cp(0.0, charging=False), 10.0 * i)
    assert _calls(h) == 0


def test_a_switch_in_flight_is_dropped_by_off():
    """A switch waiting for the car to stop, then Off: no switch when the
    other system's charge ends, and no "gave up" blame on the box."""
    h = _host(phase_mode="1")
    _tick(h, _max(), _cp(11000.0), 0.0)
    _tick(h, _max(), _cp(11000.0), 10.0)
    assert h._phase_switch_states["c1"] == "stopping"
    _tick(h, _off(), _cp(11000.0), 20.0)
    assert h._phase_switch_states["c1"] == "idle"
    for i in range(int(STOP_WAIT_S // 10) + 5):
        _tick(h, _off(), _cp(11000.0), 30.0 + 10 * i)
    for i in range(5):
        _tick(h, _off(), _cp(0.0, charging=False), 400.0 + 10 * i)
    assert _calls(h) == 0
    assert h._phase_contradictions["c1"]["count"] == 0, "blamed the box"


def test_a_switch_already_sent_settles_under_off():
    """The switch went out, then Off: it settles and keeps its belief, so
    leaving Off sends no second switch."""
    h = _host(phase_mode="1")
    _tick(h, _max(), _cp(11000.0), 0.0)
    assert h._phase_believed["c1"] == 3
    _tick(h, _max(), _cp(0.0, charging=False), 10.0)
    assert _calls(h) == 1
    assert h._phase_switch_states["c1"] == "settling"
    t = 20.0
    while t < 10.0 + SETTLE_S + 30:
        _tick(h, _off(), _cp(0.0, charging=False), t)
        t += 10.0
    assert h._phase_believed["c1"] == 1
    assert h._phase_switch_states["c1"] == "idle"
    for i in range(10):    # back to a mode SEM drives
        _tick(h, _max(), _cp(0.0, charging=False), t + 10 * i)
    assert _calls(h) == 1, "a second switch after Off"


def test_leaving_off_starts_the_down_clock_again():
    """A window from before Off is not carried across it."""
    h = _host()
    _tick(h, _max(), _cp(11000.0), 0.0)
    idle = ChargerDecision(charger_id="c1", mode="solar_only",
                           intent=ChargerIntent.IDLE, commanded_amps=0,
                           budget_w=0.0, reason="no sun")
    _tick(h, idle, _cp(0.0, charging=False), 10.0)       # the clock starts
    t = 20.0
    while t < AUTO_DOWN_DELAY_S + 100:
        _tick(h, _off(), _cp(0.0, charging=False), t)
        t += 10.0
    back = t
    _tick(h, idle, _cp(0.0, charging=False), back)
    assert _calls(h) == 0, "switched at once on a window from before Off"
    while _calls(h) == 0 and t < back + 3 * AUTO_DOWN_DELAY_S:
        t += 10.0
        _tick(h, idle, _cp(0.0, charging=False), t)
    assert t - back > AUTO_DOWN_DELAY_S


def test_by_current_writes_nothing_in_off(monkeypatch):
    """(#1015) The device path: no per-phase current write either."""
    monkeypatch.setattr(ev_control, "_phase_by_current_ready",
                        lambda host, cid, device, now: True)
    h = _host(ev_phase_switch_entity=None, phase_mode="1")
    dev = SimpleNamespace(switch_phases=AsyncMock(return_value=True),
                          phase_service="x.set_phases",
                          phase_readback=lambda: None)
    for i in range(5):
        asyncio.run(h._phase_switch_tick("c1", h.cfg, _off(),
                                         _cp(0.0, charging=False), 10.0 * i,
                                         setpoint_a=0, device=dev))
    assert dev.switch_phases.await_count == 0
