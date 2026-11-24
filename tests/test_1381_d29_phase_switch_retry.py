"""(#1381 D29) A phase switch that did not go out is not re-sent every cycle.

The verification review (tip 5d010742) found a refused or observer-withheld
phase switch retried EVERY cycle: a log line per cycle per charger, a
traceback per cycle for a refused write, and nothing counted toward the
6-a-day bound or any back-off.

Now:
* withheld (observer mode, or a charger SEM yields to): listed ONCE in
  ``withheld_commands``; no re-issue and no new line while it stays withheld;
* refused (the write raised): retried after 10, 20, 40 minutes; each try
  counts toward the daily bound of writes at rest; after the fourth refusal
  SEM gives up with one WARNING and a Repair naming the charger.
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.solar_energy_management.coordinator import ev_control
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision, ChargerIntent, ChargerPower,
)
from custom_components.solar_energy_management.devices.base import ControllableDevice


class _Dev(ControllableDevice):
    async def activate(self, w):
        return 0.0

    async def deactivate(self):
        return None

    async def adjust_power(self, w):
        return 0.0


def _host(observer=False, refuse=False):
    h = SimpleNamespace()
    h._phase_switch_tick = ev_control.EVControlMixin._phase_switch_tick.__get__(h)
    h._observer_mode = observer
    h._surplus_controller = None
    sun = MagicMock()
    call = AsyncMock(side_effect=RuntimeError("entity unavailable")) if refuse \
        else AsyncMock()
    h.hass = SimpleNamespace(states=SimpleNamespace(get=lambda eid: sun),
                             services=SimpleNamespace(async_call=call))
    h.cfg = {"ev_phase_switch_entity": "number.wb_phases",
             "ev_phase_switching_enabled": True, "phase_mode": "1",
             "ev_voltage": 230, "ev_min_current": 6}
    dev = _Dev.__new__(_Dev)
    dev.hass = h.hass
    dev.device_id = dev.name = "c1"
    dev.observer_mode = observer
    dev.external_yield = False
    return h, dev


def _decision():
    return ChargerDecision(charger_id="c1", mode="solar_only",
                           intent=ChargerIntent.CHARGE_AT_AMPS,
                           commanded_amps=10, budget_w=4600.0, reason="t")


def _cp(w, charging):
    return ChargerPower(charger_id="c1", power_w=w, connected=True,
                        charging=charging)


def _tick(h, dev, t, drawing=False):
    asyncio.run(h._phase_switch_tick(
        "c1", h.cfg, _decision(),
        _cp(6900.0 if drawing else 0.0, drawing), t, device=dev))


def _run(h, dev, until, step=10.0, start=30.0):
    """The car charges on three phases whenever SEM is not stopping it for
    a switch (a refused switch leaves it on three), and rests while the
    sequencer holds it stopped."""
    if start <= 30.0:
        _tick(h, dev, 0.0, drawing=True)
    t = start
    while t <= until:
        state = getattr(h, "_phase_switch_states", {}).get("c1", "idle")
        _tick(h, dev, t, drawing=state in ("idle", None, "not_taking"))
        t += step


def test_a_withheld_switch_is_listed_once_not_every_cycle(caplog):
    h, dev = _host(observer=True)
    caplog.set_level(logging.INFO)
    _run(h, dev, until=30.0)
    assert len(dev.withheld_commands) == 1
    n_lines = len([r for r in caplog.records if "#804" in r.getMessage()])
    _run(h, dev, until=1800.0, start=40.0)
    h.hass.services.async_call.assert_not_awaited()
    assert len(dev.withheld_commands) == 1
    assert len([r for r in caplog.records if "#804" in r.getMessage()]) == n_lines


def test_a_refused_switch_backs_off_10_20_40_then_gives_up_with_a_repair(caplog):
    h, dev = _host(refuse=True)
    created = []
    h._raise_phase_refused_repair = None  # the tick finds the module helper
    caplog.set_level(logging.INFO)
    import custom_components.solar_energy_management.coordinator.ev_control as m
    orig = getattr(m, "_raise_phase_switch_repair", None)
    m._raise_phase_switch_repair = lambda host, cid, target, tries: created.append(
        (cid, target, tries))
    try:
        _run(h, dev, until=30.0)
        assert h.hass.services.async_call.await_count == 1
        # nothing again inside the first 10 minutes
        _run(h, dev, until=600.0, start=40.0)
        assert h.hass.services.async_call.await_count == 1
        # the whole day: tries at +10, +20, +40 min, then give up
        _run(h, dev, until=6 * 3600.0, start=640.0)
        assert h.hass.services.async_call.await_count == 4
        assert created and created[0][0] == "c1" and created[0][2] == 4
        # one WARNING (the give-up), no traceback per cycle
        warns = [r for r in caplog.records if r.levelno >= logging.WARNING
                 and "#804" in r.getMessage()]
        assert len(warns) == 1
        assert not any(r.exc_info for r in warns)
    finally:
        if orig is None:
            del m._raise_phase_switch_repair
        else:
            m._raise_phase_switch_repair = orig


def test_each_refused_try_counts_toward_the_daily_bound():
    h, dev = _host(refuse=True)
    _run(h, dev, until=30.0)
    tries = getattr(h, "_phase_rest_switch_times", {}).get("c1", [])
    assert len(tries) == 1


def test_a_successful_switch_clears_the_record():
    h, dev = _host()
    _run(h, dev, until=30.0)
    assert h.hass.services.async_call.await_count == 1
    assert "c1" not in getattr(h, "_phase_switch_tries", {})


# ── D36: a held switch stays on the roster; a plain False is a refusal ───

def test_d36_a_withheld_switch_is_republished_every_cycle_while_held():
    """``withheld_commands`` is a roster swept every cycle: listing the
    switch once made it vanish after one cycle."""
    h, dev = _host(observer=True)
    _tick(h, dev, 0.0, drawing=True)
    t = 30.0
    seen = []
    while t <= 600.0:
        dev.withheld_commands = []            # the coordinator's sweep
        state = getattr(h, "_phase_switch_states", {}).get("c1", "idle")
        _tick(h, dev, t, drawing=state in ("idle", None, "not_taking"))
        seen.append(len(dev.withheld_commands))
        t += 10.0
    assert all(n == 1 for n in seen), seen
    assert dev.withheld_commands[0]["service"] == "number.set_value"
    h.hass.services.async_call.assert_not_awaited()


def test_d36_a_plain_false_from_the_seam_is_a_refusal_with_back_off():
    h, dev = _host()

    async def _false(*a, **k):
        return False
    dev.send = _false
    _run(h, dev, until=600.0)
    rec = h._phase_switch_tries["c1"]
    assert rec.get("fails") == 1 and not rec.get("withheld"), rec
    assert rec["next_try"] >= 600.0
    assert len(h._phase_rest_switch_times["c1"]) == 1
