"""(#1381, charger owner) The hand-back, against the reviewer's findings.

Each test names the finding it pins (challenge-feature-charger-owner.md, S5):
F1 a partial hand-back, F2 a refused write, F3 no read-back, F4 a one-phase
car, F5 two chargers on one meter, F6 a stop SEM cannot invert, F7 the whole
back-off, F8 an old record.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from custom_components.solar_energy_management.coordinator import guard_hand_back as ghb

from .test_1381_guard_hand_back import (
    ARMED_ROOMY,
    LINKS,
    SW,
    T0,
    _guard_stop,
    _tick,
    _two_chargers,
)

NUM = "number.links_max_current"


def _record_two_writes(coord, states):
    """A stop that wrote a number AND a switch (two restores)."""
    states.values[NUM] = "16"
    rec = ghb.build_record(
        [{"domain": "number", "service": "set_value",
          "data": {"entity_id": NUM, "value": 0}, "prior": "16"},
         {"domain": "switch", "service": "turn_off",
          "data": {"entity_id": SW[LINKS]}, "prior": "on"}],
        now=T0, reason="r", draw_w=6900, phases=3, voltage=230, min_current_a=6)
    states.values[NUM] = "0"
    states.values[SW[LINKS]] = "off"
    coord._guard_stops = {LINKS: rec}
    return rec


@pytest.mark.asyncio
async def test_f1_a_partial_hand_back_is_kept_and_the_rest_retried():
    coord, states, hass = _two_chargers()
    rec = _record_two_writes(coord, states)
    real = hass.services.async_call.side_effect

    async def _switch_refused(domain, service, data, blocking=True):
        if domain == "switch":
            raise RuntimeError("entity unavailable")
        return await real(domain, service, data, blocking)

    hass.services.async_call.side_effect = _switch_refused
    states.values[NUM] = "0"

    async def _num(domain, service, data, blocking=True):
        if domain == "number":
            states.values[NUM] = str(data["value"])
        return await _switch_refused(domain, service, data, blocking)

    hass.services.async_call.side_effect = _num
    await _tick(coord, T0 + 3600, ARMED_ROOMY)
    rec = coord._guard_stops[LINKS]
    assert [r["entity_id"] for r in rec["done"]] == [NUM]
    assert [r["entity_id"] for r in rec["restores"]] == [SW[LINKS]]
    assert rec["failures"] == 1 and rec["next_try_at"] == T0 + 3600 + 600
    # next cycle: the number reads SEM's own restore, NOT a change by others
    await _tick(coord, T0 + 3700, ARMED_ROOMY)
    assert LINKS in coord._guard_stops
    # after the wait the switch goes; nothing is re-sent to the number
    hass.services.async_call.side_effect = real
    hass.calls.clear()
    await _tick(coord, T0 + 3600 + 601, ARMED_ROOMY)
    assert hass.calls == [("switch", "turn_on", SW[LINKS])]


@pytest.mark.asyncio
async def test_f2_a_refused_write_backs_off_and_does_not_retry_every_cycle():
    coord, states, hass = _two_chargers()
    await _guard_stop(coord, LINKS, 10300, T0)

    async def _refuse(*_a, **_k):
        raise RuntimeError("refused")

    hass.services.async_call.reset_mock()
    hass.services.async_call.side_effect = _refuse
    for i in range(5):                       # five cycles, 10 s apart
        await _tick(coord, T0 + 3600 + 10 * i, ARMED_ROOMY)
    rec = coord._guard_stops[LINKS]
    assert rec["failures"] == 1
    assert rec["next_try_at"] == T0 + 3600 + 600
    assert hass.services.async_call.await_count == 1


@pytest.mark.asyncio
async def test_f3_no_read_back_counts_as_a_failure():
    coord, states, hass = _two_chargers()
    await _guard_stop(coord, LINKS, 10300, T0)
    await _tick(coord, T0 + 3600, ARMED_ROOMY)
    assert states.values[SW[LINKS]] == "on"
    states.values[SW[LINKS]] = "off"         # the box switched itself off again
    await _tick(coord, T0 + 3600 + 60, ARMED_ROOMY)
    rec = coord._guard_stops[LINKS]
    assert rec["failures"] == 1 and rec["handed_back_at"] == 0.0
    assert [r["entity_id"] for r in rec["restores"]] == [SW[LINKS]]


@pytest.mark.asyncio
async def test_f3_a_read_back_confirms_and_the_record_ends():
    coord, states, hass = _two_chargers()
    await _guard_stop(coord, LINKS, 10300, T0)
    await _tick(coord, T0 + 3600, ARMED_ROOMY)
    await _tick(coord, T0 + 3600 + 60, ARMED_ROOMY)
    assert coord._guard_stops[LINKS]["confirmed"] is True
    await _tick(coord, T0 + 3600 + ghb.RETRIP_WINDOW_S + 61, ARMED_ROOMY)
    assert LINKS not in coord._guard_stops


def test_f4_a_one_phase_car_needs_its_whole_current_on_one_phase():
    one = ghb.build_record(
        [{"domain": "switch", "service": "turn_off",
          "data": {"entity_id": "switch.x"}, "prior": "on"}],
        now=T0, reason="r", draw_w=3680, phases=1, voltage=230, min_current_a=6)
    three = ghb.build_record(
        [{"domain": "switch", "service": "turn_off",
          "data": {"entity_id": "switch.x"}, "prior": "on"}],
        now=T0, reason="r", draw_w=3680, phases=3, voltage=230, min_current_a=6)
    assert one["draw_a"] == pytest.approx(16.0)
    assert three["draw_a"] == pytest.approx(6.0)


def test_f4_the_drawing_phases_come_from_the_legs_then_the_belief():
    adapter = SimpleNamespace(phases=3)
    legs = SimpleNamespace(_charger_leg_phases=lambda cid, dev, w: 1)
    belief = SimpleNamespace(_phase_believed={"c": 1})
    plain = SimpleNamespace()
    assert ghb._drawing_phases(legs, "c", adapter, None, 3680) == 1
    assert ghb._drawing_phases(belief, "c", adapter, None, 3680) == 1
    assert ghb._drawing_phases(plain, "c", adapter, None, 3680) == 3


def test_f6_a_brand_service_stop_is_left_off_with_a_reason_never_guessed():
    assert ghb.inverse_of({"domain": "keba", "service": "disable",
                           "data": {}, "prior": None}) is None
    assert ghb.inverse_of({"domain": "button", "service": "press",
                           "data": {"entity_id": "button.stop"},
                           "prior": "2026-11-24T10:00:00"}) is None
    rec = ghb.build_record(
        [{"domain": "keba", "service": "disable", "data": {}, "prior": None}],
        now=T0, reason="r", draw_w=10000, phases=3, voltage=230, min_current_a=6)
    assert rec["undoable"] is False


@pytest.mark.asyncio
async def test_f8_an_old_record_is_not_handed_back():
    coord, states, hass = _two_chargers()
    await _guard_stop(coord, LINKS, 10300, T0)
    hass.calls.clear()
    with patch("homeassistant.helpers.issue_registry.async_create_issue"):
        await _tick(coord, T0 + ghb.MAX_AGE_S + 60, ARMED_ROOMY)
    assert hass.calls == []
    assert coord._guard_stops[LINKS]["left_off"] is True


@pytest.mark.asyncio
async def test_a_damaged_record_never_breaks_the_cycle():
    coord, states, hass = _two_chargers()
    await _guard_stop(coord, LINKS, 10300, T0)
    coord._guard_stops[LINKS]["restores"] = [{"entity_id": SW[LINKS], "left": "off"}]
    with patch("homeassistant.helpers.issue_registry.async_create_issue"):
        await _tick(coord, T0 + 3600, ARMED_ROOMY)   # must not raise
    assert coord._guard_stops[LINKS]["left_off"] is True
