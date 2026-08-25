"""#804 — phase switching goes dormant in 2.0; it wakes, whole, in 2.1.

The feature shipped and real testing found it harmful on two of the three
brands that tried it:

* **Wattpilot** (@HorizonKane): every SEM stop latches the box into a paused
  force-state a current write cannot clear. The stop→switch→settle→start
  sequence pauses charging and nothing resumes it — and in Min+Solar SEM
  re-issues the stop after a manual resume. A tug-of-war.
* **Zaptec** (@coppe218): the brand has no phase command at all — it switches
  implicitly on a current threshold — so the sequence stops the charger,
  "switches" nothing, and retries forever.

Making it safe is real 2.1 work: a resume surface per brand (button / switch /
service), the Zaptec threshold model, stop-eagerness awareness on latching
hardware, and the per-phase current guard — switching down lands the whole
load on ONE phase, which a kW peak model cannot see (a 3×25 A connection is
fused per phase, folded into #804 from the short-lived #843).

Until then the actuation sits behind ``ev_phase_switching_enabled``, default
OFF (Guido, 25.08: deactivate in 2.0, move the arc to 2.1). The house
pattern — land it asleep, wake it deliberately — and the gate covers BOTH
halves: the actuation AND the selector's existence, because a knob that
visibly switches while the actuation is dormant is the #462 lie.
"""
from __future__ import annotations

import asyncio
import inspect

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock


def _host(cfg):
    from custom_components.solar_energy_management.coordinator import ev_control
    h = SimpleNamespace()
    h._phase_switch_tick = ev_control.EVControlMixin._phase_switch_tick.__get__(h)
    h._observer_mode = False
    h._surplus_controller = None
    h.hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda eid: MagicMock()),
        services=SimpleNamespace(async_call=AsyncMock()),
    )
    h.cfg = cfg
    return h


def _decision(amps=10):
    from custom_components.solar_energy_management.coordinator.charger_types import (
        ChargerDecision, ChargerIntent,
    )
    return ChargerDecision(
        charger_id="c1", mode="solar_only",
        intent=ChargerIntent.CHARGE_AT_AMPS,
        commanded_amps=amps, budget_w=4600.0, reason="test")


def _cp(power_w=4000.0, charging=True):
    from custom_components.solar_energy_management.coordinator.charger_types import (
        ChargerPower,
    )
    return ChargerPower(charger_id="c1", power_w=power_w,
                        connected=True, charging=charging)


CFG_WITH_ENTITY = {
    "ev_phase_switch_entity": "number.keba_phases",
    "phase_mode": "1",
    "ev_voltage": 230,
    "ev_min_current": 6,
}


class TestTheGateIsOffByDefault:
    def test_a_configured_entity_alone_no_longer_activates(self):
        """The pre-fix gate was 'is an entity configured' — exactly how both
        reporters walked into the broken path."""
        h = _host(dict(CFG_WITH_ENTITY))
        d = _decision()
        out = asyncio.run(h._phase_switch_tick("c1", h.cfg, d, _cp(), 10.0))
        assert out is d, (
            "phase switching ran on entity presence alone — the 2.0 dormancy "
            "gate is not holding (#804)"
        )
        h.hass.services.async_call.assert_not_awaited()
        assert not getattr(h, "_phase_sequencers", None), (
            "per-charger phase state was built while dormant"
        )

    def test_the_opt_in_wakes_it(self):
        """Both reporters keep testing by flipping it on knowingly."""
        h = _host(dict(CFG_WITH_ENTITY, ev_phase_switching_enabled=True))
        asyncio.run(h._phase_switch_tick("c1", h.cfg, _decision(), _cp(), 10.0))
        assert getattr(h, "_phase_sequencers", None) is not None, (
            "the opt-in did not wake the path"
        )

    def test_no_entity_is_still_a_pass_through(self):
        h = _host({"ev_phase_switching_enabled": True})
        d = _decision()
        out = asyncio.run(h._phase_switch_tick("c1", h.cfg, d, _cp(), 10.0))
        assert out is d


class TestTheSelectorFollowsTheSameGate:
    """One gate, both halves — a live knob over dormant actuation looks
    applied and does nothing (#462)."""

    def test_selector_creation_checks_the_gate(self):
        import custom_components.solar_energy_management.select as sel
        src = inspect.getsource(sel)
        assert "ev_phase_switching_enabled" in src, (
            "select.py still creates the phase-mode selector on entity "
            "presence alone (#804)"
        )
