"""#638 night 3 (2026-08-07→08) — the three findings the live night handed us.

1. **A car that is known absent is not a demand.** Both machines packed EV
   kWh for unplugged cars (PROD 4.94 kWh, the clone 10 kWh at the 21:00
   stamp) — ledger spent on a demand that can never draw, and real demands
   starve behind it. Only a configured plug sensor may answer "no car";
   an install with no sensor to ask keeps the demand (fail-visible, the
   mode-gate precedent). The plug-in re-plans within a cycle because the
   connection is term 1 of the demand signature — proven live on the
   clone: connect 00:07:32, stamp the same second.

2. **The stamp precedes the decisions.** The EV chain ran before the plan
   trigger in the update cycle, so the cycle in which a car connected was
   decided against the stale plan — a 10 s ``active`` blip in observer
   mode; against real hardware, an enable command taken straight back.

3. **A re-plan says why.** Guido shrinking the ASK to 0.5 kWh at 00:11
   silently became "the" night — the payload now carries ``replan_cause``
   so a re-stamped night is distinguishable from the first answer.
"""
from datetime import datetime
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator import (
    coordinator as coord_mod,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.ev_availability import (
    plan_connectivity,
)


class TestPlanConnectivity:
    """The pure three-state answer: True/False from a configured sensor,
    None when there is nothing to ask (→ the caller plans, fail-visible)."""

    def test_the_per_charger_map_answers_no(self):
        power = SimpleNamespace(ev_connected_per_charger={"keba": False})
        assert plan_connectivity("keba", {}, {}, power) is False

    def test_the_per_charger_map_answers_yes(self):
        power = SimpleNamespace(ev_connected_per_charger={"keba": True})
        assert plan_connectivity("keba", {}, {}, power) is True

    def test_a_configured_flat_sensor_answers_through_the_fleet_flag(self):
        power = SimpleNamespace(ev_connected=False)
        cfg = {"ev_plug_sensor": "binary_sensor.plug"}
        assert plan_connectivity("keba", {}, cfg, power) is False

    def test_the_flat_ev_connected_sensor_key_counts_too(self):
        power = SimpleNamespace(ev_connected=True)
        cfg = {"ev_connected_sensor": "binary_sensor.plug"}
        assert plan_connectivity("keba", {}, cfg, power) is True

    def test_a_per_charger_sensor_without_a_map_falls_to_the_fleet(self):
        """A power object built without the map (older read paths, tests)
        must still honour a charger whose OWN sensor is configured."""
        power = SimpleNamespace(ev_connected=False)
        charger_cfg = {"ev_connected_sensor": "binary_sensor.plug"}
        assert plan_connectivity("keba", charger_cfg, {}, power) is False

    def test_no_sensor_anywhere_is_unknown_not_disconnected(self):
        """The empty-sensor read publishes ``ev_connected=False`` on installs
        with NO plug sensor at all — treating that as 'no car' would starve
        every sensor-less install's night plan."""
        power = SimpleNamespace(ev_connected=False)
        assert plan_connectivity("keba", {}, {}, power) is None

    def test_no_power_readings_is_unknown(self):
        assert plan_connectivity("keba", {}, {}, None) is None


def _freeze(monkeypatch, hour, minute=0, day=8):
    fixed = datetime(2026, 8, day, hour, minute,
                     tzinfo=coord_mod.dt_util.DEFAULT_TIME_ZONE)
    monkeypatch.setattr(coord_mod.dt_util, "now", lambda *a, **k: fixed)
    return fixed


@pytest.fixture
def _freeze_2200(monkeypatch):
    return _freeze(monkeypatch, 22)


def _tick_self(sig=("ask",), compute_ok=True):
    calls = []

    def _compute(scheduler, energy, phantom_kwh, phantom_w, power=None,
                 replan_cause="initial"):
        calls.append(replan_cause)
        return compute_ok

    fake = SimpleNamespace(
        _battery_charge_scheduler=SimpleNamespace(),
        time_manager=SimpleNamespace(get_night_end_time=lambda: "07:00"),
        config={"battery_capacity_kwh": 0},
        _overnight_demand_signature=lambda power: fake._sig,
        _shadow_overnight_plan=_compute,
        _shadow_plan_date=None,
        _plan_ev_conn_sig=None,
        _sig=sig,
        _compute_calls=calls,
    )
    return fake


class TestOvernightPlanTick:
    """The extracted trigger, called BEFORE the charging decisions
    (finding 2) — and since the horizon-spanning change, ONCE PER ENERGY
    DAY (night-end to night-end) rather than once per night: the plan
    always covers now → the coming night's end, so a daytime tick stamps
    the day+night plan and the sunrise boundary opens the next period."""

    def test_the_first_tick_stamps_the_period(self, _freeze_2200):
        fake = _tick_self()
        SEMCoordinator._overnight_plan_tick(fake, power=None, energy=None)
        assert fake._shadow_plan_date is not None
        assert fake._plan_ev_conn_sig == ("ask",)
        assert fake._compute_calls == ["initial"]

    def test_an_unchanged_ask_does_not_restamp(self, _freeze_2200):
        fake = _tick_self()
        SEMCoordinator._overnight_plan_tick(fake, power=None, energy=None)
        SEMCoordinator._overnight_plan_tick(fake, power=None, energy=None)
        assert fake._compute_calls == ["initial"]

    def test_a_changed_ask_replans_with_the_cause(self, _freeze_2200):
        fake = _tick_self()
        SEMCoordinator._overnight_plan_tick(fake, power=None, energy=None)
        fake._sig = ("ask", "changed")
        SEMCoordinator._overnight_plan_tick(fake, power=None, energy=None)
        assert fake._compute_calls == ["initial", "ask changed"]
        assert fake._plan_ev_conn_sig == ("ask", "changed")

    def test_a_daytime_tick_plans_toward_the_coming_night(self, monkeypatch):
        """The spanning change: 14:00 is not 'outside the window' any
        more — the day IS part of the horizon (comfort banking, load
        scheduling into surplus windows need a daytime answer)."""
        _freeze(monkeypatch, 14)
        fake = _tick_self()
        SEMCoordinator._overnight_plan_tick(fake, power=None, energy=None)
        assert fake._compute_calls == ["initial"]
        assert fake._shadow_plan_date is not None

    def test_one_period_spans_day_and_night(self, monkeypatch):
        """A 14:00 stamp, the same evening, and 03:00 past midnight all
        belong to ONE energy day — no re-stamp without an ask change."""
        _freeze(monkeypatch, 14)
        fake = _tick_self()
        SEMCoordinator._overnight_plan_tick(fake, power=None, energy=None)
        _freeze(monkeypatch, 22)
        SEMCoordinator._overnight_plan_tick(fake, power=None, energy=None)
        _freeze(monkeypatch, 3, day=9)
        SEMCoordinator._overnight_plan_tick(fake, power=None, energy=None)
        assert fake._compute_calls == ["initial"]

    def test_the_night_end_boundary_opens_the_next_period(self, monkeypatch):
        _freeze(monkeypatch, 22)
        fake = _tick_self()
        SEMCoordinator._overnight_plan_tick(fake, power=None, energy=None)
        # 07:30 next day — past night_end 07:00: a fresh energy day.
        _freeze(monkeypatch, 7, minute=30, day=9)
        SEMCoordinator._overnight_plan_tick(fake, power=None, energy=None)
        assert fake._compute_calls == ["initial", "initial"]

    def test_a_not_ready_world_retries_without_a_stamp(self, _freeze_2200):
        fake = _tick_self(compute_ok=False)
        SEMCoordinator._overnight_plan_tick(fake, power=None, energy=None)
        assert fake._shadow_plan_date is None
        # and the retry is still an "initial" answer, not a re-plan
        SEMCoordinator._overnight_plan_tick(fake, power=None, energy=None)
        assert fake._compute_calls == ["initial", "initial"]

    def test_the_tick_never_breaks_the_cycle(self, _freeze_2200):
        hostile = SimpleNamespace()  # every attribute missing
        SEMCoordinator._overnight_plan_tick(hostile, power=None, energy=None)


class TestTheStampPrecedesTheDecisions:
    """Finding 2 as a structural pin: the tick call sits BEFORE the EV
    session/decision chain in ``_async_update_data`` — the plan's authority
    begins at the stamp, so the stamp must come before the first decision
    that reads it."""

    def test_source_order(self):
        import inspect
        src = inspect.getsource(SEMCoordinator._async_update_data)
        tick = src.index("_overnight_plan_tick(")
        ev_chain = src.index("Step 4.5")
        assert tick < ev_chain, (
            "_overnight_plan_tick must run before the EV session/decision "
            "chain — deciding a fresh connect against the stale plan is the "
            "night-3 blip (one cycle of enable-then-revoke on hardware)"
        )

    def test_the_inline_trigger_block_is_gone(self):
        import inspect
        src = inspect.getsource(SEMCoordinator._async_update_data)
        assert "_shadow_overnight_plan(" not in src, (
            "the trigger body must live only in _overnight_plan_tick — two "
            "copies is the drift invitation this extraction removes"
        )
