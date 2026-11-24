"""(#1381 D30/D31) Now waits for its car; only the user's Now lifts Off.

D30: the verification review found that any known unplug cleared any
charger ``force`` at once — a Now picked before the cable was in, or an
automation arming a force for a car about to arrive, died on the next cycle.
Now a charger force set while the car is away WAITS: it starts on the first
cycle the car is known to be in (a relative Now counts its minutes from
then; a chosen clock time keeps it), and only a STARTED force ends on unplug.

D31: ``plan_override`` with ``action: force, value: -1`` lifted Off like the
user's Now. The user's Now is now a flag set only by the mode select, the
card's Now and the service's explicit ``user_now`` — no value stands in.
"""
from __future__ import annotations

from datetime import timedelta

from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator import plan_override as po


def _waiting(minutes=60, fixed_end=False, user_now=True):
    now = dt_util.utcnow()
    exp = now + timedelta(minutes=minutes if fixed_end else po.MAX_OVERRIDE_MINUTES)
    return po.set_override({}, "c", "force", exp, now, user_now=user_now,
                           started=False, minutes=minutes,
                           fixed_end=fixed_end), now


def test_d30_a_now_set_while_the_car_is_away_is_not_ended_by_that_unplug():
    ov, now = _waiting()
    assert po.end_now_on_unplug(ov, "c", car_absent=True, now=now) is ov
    assert po.charger_mode_for(ov, "c", "sun", now) == "always_max"


def test_d30_it_starts_at_the_plug_in_and_counts_its_minutes_from_there():
    ov, now = _waiting(minutes=60)
    later = now + timedelta(hours=3)
    started = po.end_now_on_unplug(ov, "c", car_absent=False, now=later)
    rec = started["c"]
    assert rec.started is True
    assert abs((rec.expires_at - (later + timedelta(minutes=60))).total_seconds()) < 1


def test_d30_a_chosen_clock_time_keeps_its_end():
    ov, now = _waiting(minutes=90, fixed_end=True)
    end = ov["c"].expires_at
    started = po.end_now_on_unplug(ov, "c", car_absent=False,
                                   now=now + timedelta(minutes=30))
    assert started["c"].expires_at == end


def test_d30_an_unplug_after_it_started_ends_it():
    ov, now = _waiting()
    started = po.end_now_on_unplug(ov, "c", car_absent=False, now=now)
    assert po.end_now_on_unplug(started, "c", car_absent=True, now=now) == {}


def test_d30_an_unknown_plug_state_neither_starts_nor_ends_it():
    ov, now = _waiting()
    assert po.end_now_on_unplug(ov, "c", car_absent=None, now=now) is ov


def test_d30_the_waiting_state_survives_a_restart():
    ov, now = _waiting(minutes=45)
    back = po.deserialize(po.serialize(ov))
    assert back["c"].started is False and back["c"].minutes == 45
    assert back["c"].user_now is True


def test_d31_a_service_force_with_any_value_never_lifts_off():
    now = dt_util.utcnow()
    for value in (None, -1.0, 0.0, 1.0):
        ov = po.set_override({}, "c", "force", now + timedelta(minutes=60),
                             now, value=value)
        assert po.charger_mode_for(ov, "c", "off", now) == "off", value


def test_d31_only_the_users_now_lifts_off():
    ov, now = _waiting()
    assert po.charger_mode_for(ov, "c", "off", now) == "always_max"


def test_d31_a_stored_minus_one_value_is_not_a_users_now():
    now = dt_util.utcnow()
    raw = {"c": {"action": "force", "value": -1.0,
                 "expires_at": (now + timedelta(minutes=60)).isoformat(),
                 "set_at": now.isoformat()}}
    assert po.charger_mode_for(po.deserialize(raw), "c", "off", now) == "off"


def test_d31_the_service_schema_names_user_now():
    """The plan_override service takes ``user_now`` and hands it on: read as
    code (the schema's key and the call's keyword), not as spelling."""
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).resolve().parents[1] / "__init__.py").read_text())
    schema_keys = {n.args[0].value for n in ast.walk(tree)
                   if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "Optional"
                   and n.args and isinstance(n.args[0], ast.Constant)}
    assert {"user_now", "fixed_end"} <= schema_keys
    passed = {k.arg for n in ast.walk(tree)
              if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "set_plan_override"
              for k in n.keywords}
    assert {"user_now", "fixed_end"} <= passed
