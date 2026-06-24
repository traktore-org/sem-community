"""EV start-kick — a car that won't latch a gentle min-current start.

Guido's PROD KEBA P30 (3-phase) needs ~9 A offered to *begin* the
handshake, then holds at 6 A. SEM's day/solar start was hard-wired to the
sustain floor (``min_amps`` from ``ev_min_current``), so:

* ``ev_min_current=9`` → a 4140 W solar+battery budget read as "6 A < 9 A
  min" → ``charge_wanted`` flips → start/stop oscillation.
* ``ev_min_current=6`` → start offered 6 A → the car never latched.

The fix (charge_stability.py): keep ``min_amps`` as the sustain floor /
``charge_wanted`` threshold, start GENTLY at ``min_amps`` (preserves the
documented KEBA cold-start grid-overshoot fix), and — only when the car
still isn't drawing after ``START_KICK_GRACE_S`` — escalate to the
``initial_current`` ("Vehicle Start Amps") kick and hold it until the car
draws, then settle to the budget. End state for Guido: ``ev_min_current=6``
(budget clears, no oscillation) + ``initial_current=9/10`` (car latches).
"""
import pytest

from custom_components.solar_energy_management.coordinator.charge_stability import (
    ChargeStability,
    START_KICK_GRACE_S,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerEnergy,
    ChargerIntent,
    ChargerPower,
    ChargerView,
    FleetContext,
)


class FakeAdapter:
    def __init__(self, last_intent=None, min_current_a=6, max_current_a=16):
        self.last_intent = last_intent
        self.min_current_a = min_current_a
        self.max_current_a = max_current_a

    def actual_charging(self, power):
        return power.power_w > 500.0


def _view(*, power_w=0.0, ev_min_current=6, initial_current=0,
          ev_max_current=16, solar_w=3000.0, cid="wb"):
    cfg = {"ev_min_current": ev_min_current, "ev_phases": 3,
           "ev_voltage": 230, "ev_max_current": ev_max_current}
    if initial_current:
        cfg["initial_current"] = initial_current
    return ChargerView(
        power=ChargerPower(charger_id=cid, power_w=power_w,
                           connected=True, charging=power_w > 500),
        energy=ChargerEnergy(charger_id=cid),
        mode="solar_only",
        config=cfg,
        fleet=FleetContext(is_night=False, solar_w=solar_w, min_solar_w=200.0,
                           tariff_level=None),
    )


def _charge(cid="wb", amps=6):
    return ChargerDecision(
        charger_id=cid, mode="solar_only",
        intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=amps,
        budget_w=4140.0, reason="solar_only: surplus ok",
    )


def _filter(st, view, adapter, now):
    return st.filter(_charge(), view, adapter,
                     enable_delay_s=60, disable_delay_s=300, now_ts=now)


@pytest.mark.unit
class TestStartKick:
    def test_gentle_start_then_escalates_when_no_draw(self):
        """initial_current=9: start gently at 6 A, then escalate to 9 A
        once the car hasn't drawn for START_KICK_GRACE_S."""
        st = ChargeStability()
        adapter = FakeAdapter(min_current_a=6, max_current_a=16)
        # Car not drawing the whole time (power 120 W < 500 W threshold).
        view = _view(power_w=120.0, ev_min_current=6, initial_current=9)

        # Surplus must hold the enable delay first.
        d = _filter(st, view, adapter, now=0.0)
        assert d.intent is ChargerIntent.IDLE
        # Enable delay elapsed → gentle start at min (6 A).
        d = _filter(st, view, adapter, now=60.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 6
        # Adapter now reports a commanded charge but car still not drawing.
        adapter.last_intent = ChargerIntent.CHARGE_AT_AMPS
        # Still inside the kick grace → hold gentle 6 A.
        d = _filter(st, view, adapter, now=60.0 + START_KICK_GRACE_S - 1)
        assert d.commanded_amps == 6
        assert "gentle start" in d.reason
        # Grace elapsed, still no draw → escalate to the 9 A start kick.
        d = _filter(st, view, adapter, now=60.0 + START_KICK_GRACE_S + 1)
        assert d.commanded_amps == 9
        assert "start kick" in d.reason

    def test_kick_holds_until_draw_then_settles(self):
        """The 9 A kick persists until the car draws, then the setpoint
        ramps toward the budget sustain current (6 A)."""
        st = ChargeStability()
        adapter = FakeAdapter(min_current_a=6, max_current_a=16)
        view = _view(power_w=120.0, ev_min_current=6, initial_current=9)
        _filter(st, view, adapter, now=0.0)
        _filter(st, view, adapter, now=60.0)
        adapter.last_intent = ChargerIntent.CHARGE_AT_AMPS
        d = _filter(st, view, adapter, now=85.0)
        assert d.commanded_amps == 9  # escalated
        # Still no draw a cycle later → keep the kick.
        d = _filter(st, view, adapter, now=95.0)
        assert d.commanded_amps == 9
        # Car latches (now drawing 4.1 kW) → settle toward 6 A budget.
        drawing = _view(power_w=4140.0, ev_min_current=6, initial_current=9)
        d = st.filter(_charge(), drawing, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=105.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps <= 9  # ramping down from the kick
        assert d.commanded_amps >= 6  # not below the sustain floor

    def test_normal_car_draws_at_min_never_escalates(self):
        """A car that accepts the gentle 6 A start (draws immediately)
        must never see the kick, even with initial_current set."""
        st = ChargeStability()
        adapter = FakeAdapter(min_current_a=6, max_current_a=16)
        # Drawing from the first charging cycle.
        view = _view(power_w=4140.0, ev_min_current=6, initial_current=10)
        adapter.last_intent = ChargerIntent.CHARGE_AT_AMPS
        for t in (0.0, 30.0, 100.0, 200.0):
            d = st.filter(_charge(), view, adapter,
                          enable_delay_s=60, disable_delay_s=300, now_ts=t)
            assert d.commanded_amps <= 6 or d.commanded_amps == _charge().commanded_amps
            assert "start kick" not in d.reason

    def test_no_initial_current_is_legacy_gentle_start(self):
        """Without initial_current the start stays at min and never
        escalates (legacy behaviour preserved)."""
        st = ChargeStability()
        adapter = FakeAdapter(min_current_a=6, max_current_a=16)
        view = _view(power_w=120.0, ev_min_current=6, initial_current=0)
        _filter(st, view, adapter, now=0.0)
        d = _filter(st, view, adapter, now=60.0)
        assert d.commanded_amps == 6
        adapter.last_intent = ChargerIntent.CHARGE_AT_AMPS
        d = _filter(st, view, adapter, now=200.0)  # long past any grace
        assert d.commanded_amps == 6
        assert "start kick" not in d.reason

    def test_start_kick_clamped_to_max(self):
        """initial_current above the circuit max is clamped to max_amps."""
        st = ChargeStability()
        adapter = FakeAdapter(min_current_a=6, max_current_a=16)
        view = _view(power_w=120.0, ev_min_current=6, initial_current=32,
                     ev_max_current=16)
        _filter(st, view, adapter, now=0.0)
        _filter(st, view, adapter, now=60.0)
        adapter.last_intent = ChargerIntent.CHARGE_AT_AMPS
        d = _filter(st, view, adapter, now=85.0)
        assert d.commanded_amps == 16  # clamped to ev_max_current

    def test_post_latch_hold_then_gentle_settle(self):
        """First draw of a SEM-started session anchors the debounce, so the
        latch current holds for a full ev_min_change_interval_sec (reused as
        the stabilization hold), then eases toward the budget at the ramp."""
        st = ChargeStability()
        adapter = FakeAdapter(min_current_a=6, max_current_a=16)
        idle = _view(power_w=120.0, ev_min_current=6, initial_current=9)
        _filter(st, idle, adapter, now=0.0)    # IDLE — surplus must hold
        _filter(st, idle, adapter, now=60.0)   # gentle start at 6 A
        adapter.last_intent = ChargerIntent.CHARGE_AT_AMPS
        _filter(st, idle, adapter, now=85.0)   # escalate to 9 A kick
        drawing = _view(power_w=4140.0, ev_min_current=6, initial_current=9)
        # Car latches → hold the 9 A that latched it (debounce anchored).
        d = st.filter(_charge(), drawing, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=90.0)
        assert d.commanded_amps == 9
        # Still inside the 30 s debounce/hold → unchanged.
        d = st.filter(_charge(), drawing, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=110.0)
        assert d.commanded_amps == 9
        # Hold elapsed → one gentle ramp step toward the 6 A budget.
        d = st.filter(_charge(), drawing, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=125.0)
        assert d.commanded_amps == 7  # 9 - ramp(2)

    def test_sustain_floor_6_does_not_oscillate_on_4140w_budget(self):
        """With ev_min_current=6, a steady 6 A budget keeps charge_wanted
        true — no start/stop flip (the catch-22 that ev_min_current=9
        caused)."""
        st = ChargeStability()
        adapter = FakeAdapter(min_current_a=6, max_current_a=16)
        view = _view(power_w=4140.0, ev_min_current=6, initial_current=9)
        adapter.last_intent = ChargerIntent.CHARGE_AT_AMPS
        intents = set()
        for t in range(0, 300, 10):
            d = st.filter(_charge(), view, adapter,
                          enable_delay_s=60, disable_delay_s=300, now_ts=float(t))
            intents.add(d.intent)
        assert ChargerIntent.IDLE not in intents  # never stops while drawing
