"""EV auto start-escalation — one knob (Min Amps), automatic latch.

A fussy car (a 3-phase Renault Zoe R) needs ~9-10 A offered to *begin* the
AC handshake, then holds down to 6 A. The user only sets ONE current —
``ev_min_current`` (Min Amps). SEM starts there; if no current flows after
a short grace it automatically raises the offer one step at a time (capped
at the charger max) until the car latches, then settles back to Min Amps.
No ``initial_current`` / ``vehicle_min_current`` knobs needed.
"""
import pytest

from custom_components.solar_energy_management.coordinator.charge_stability import (
    ChargeStability,
    START_KICK_GRACE_S,
    START_KICK_STEP_A,
    START_KICK_MAX_A,
    START_KICK_GIVEUP_S,
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


def _view(*, power_w=0.0, ev_min_current=6, ev_max_current=16, cid="wb",
          is_night=False):
    return ChargerView(
        power=ChargerPower(charger_id=cid, power_w=power_w,
                           connected=True, charging=power_w > 500),
        energy=ChargerEnergy(charger_id=cid),
        mode="min_plus_solar",
        config={"ev_min_current": ev_min_current, "ev_phases": 3,
                "ev_voltage": 230, "ev_max_current": ev_max_current},
        fleet=FleetContext(is_night=is_night, solar_w=0.0 if is_night else 3000.0,
                           min_solar_w=200.0, tariff_level=None),
    )


def _charge(cid="wb", amps=6):
    return ChargerDecision(
        charger_id=cid, mode="min_plus_solar",
        intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=amps,
        budget_w=4140.0, reason="min_plus_solar night: deadline floor 6A",
    )


def _idle(cid="wb"):
    return ChargerDecision(
        charger_id=cid, mode="min_plus_solar",
        intent=ChargerIntent.IDLE, commanded_amps=0,
        reason="min_plus_solar night: target reached",
    )


def _filter(st, view, adapter, now):
    return st.filter(_charge(), view, adapter,
                     enable_delay_s=60, disable_delay_s=300, now_ts=now)


@pytest.mark.unit
class TestStartEscalation:
    def test_starts_at_min_then_auto_raises_when_no_draw(self):
        """Start at Min Amps (6), then climb +step each grace while the car
        isn't drawing: 6 → 8 → 10 …"""
        st = ChargeStability()
        adapter = FakeAdapter(min_current_a=6, max_current_a=16)
        view = _view(power_w=120.0, ev_min_current=6)  # never draws

        d = _filter(st, view, adapter, now=0.0)
        assert d.intent is ChargerIntent.IDLE          # enable delay
        d = _filter(st, view, adapter, now=60.0)
        assert d.commanded_amps == 6                   # gentle start at min
        adapter.last_intent = ChargerIntent.CHARGE_AT_AMPS
        # within grace → still 6
        d = _filter(st, view, adapter, now=60.0 + START_KICK_GRACE_S - 1)
        assert d.commanded_amps == 6
        # grace elapsed → raise one step
        d = _filter(st, view, adapter, now=60.0 + START_KICK_GRACE_S + 1)
        assert d.commanded_amps == 6 + START_KICK_STEP_A      # 8
        assert "trying" in d.reason
        # another grace → another step
        d = _filter(st, view, adapter, now=60.0 + 2 * START_KICK_GRACE_S + 2)
        assert d.commanded_amps == 6 + 2 * START_KICK_STEP_A  # 10

    def test_escalation_stops_when_car_draws_then_settles(self):
        """Once the car draws, stop climbing and settle back toward Min."""
        st = ChargeStability()
        adapter = FakeAdapter(min_current_a=6, max_current_a=16)
        idle = _view(power_w=120.0, ev_min_current=6)
        _filter(st, idle, adapter, now=0.0)
        _filter(st, idle, adapter, now=60.0)
        adapter.last_intent = ChargerIntent.CHARGE_AT_AMPS
        d = _filter(st, idle, adapter, now=85.0)
        assert d.commanded_amps == 8                   # climbed one step
        # Car latches at 4.1 kW → settle toward the 6 A min.
        drawing = _view(power_w=4140.0, ev_min_current=6)
        for t in (120.0, 160.0, 200.0, 240.0):
            d = st.filter(_charge(), drawing, adapter,
                          enable_delay_s=60, disable_delay_s=300, now_ts=t)
        assert d.commanded_amps == 6                   # settled to min
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS

    def test_normal_car_draws_at_min_never_escalates(self):
        """A car that draws at the gentle 6 A start never climbs."""
        st = ChargeStability()
        adapter = FakeAdapter(min_current_a=6, max_current_a=16)
        view = _view(power_w=4140.0, ev_min_current=6)  # drawing from t0
        adapter.last_intent = ChargerIntent.CHARGE_AT_AMPS
        for t in (0.0, 30.0, 100.0, 200.0):
            d = st.filter(_charge(), view, adapter,
                          enable_delay_s=60, disable_delay_s=300, now_ts=t)
            assert d.commanded_amps <= 6
            assert "trying" not in d.reason

    def test_escalation_capped_at_safe_ceiling_not_charger_max(self):
        """On a 32 A charger the climb must stop at START_KICK_MAX_A (10),
        NOT the 32 A max — the grid-spike-safety cap."""
        st = ChargeStability()
        adapter = FakeAdapter(min_current_a=6, max_current_a=32)
        view = _view(power_w=120.0, ev_min_current=6, ev_max_current=32)
        _filter(st, view, adapter, now=0.0)
        _filter(st, view, adapter, now=60.0)
        adapter.last_intent = ChargerIntent.CHARGE_AT_AMPS
        d = None
        for i in range(1, 6):  # climb several graces
            d = _filter(st, view, adapter, now=60.0 + i * (START_KICK_GRACE_S + 1))
        assert d.commanded_amps == START_KICK_MAX_A   # 10, capped — never 32

    def test_gives_up_when_car_never_latches(self):
        """Held at the ceiling past the give-up window with no draw → stop
        offering (IDLE), don't sit at a high current forever."""
        st = ChargeStability()
        adapter = FakeAdapter(min_current_a=6, max_current_a=32)
        view = _view(power_w=120.0, ev_min_current=6, ev_max_current=32)
        _filter(st, view, adapter, now=0.0)
        _filter(st, view, adapter, now=60.0)
        adapter.last_intent = ChargerIntent.CHARGE_AT_AMPS
        # Reach the ceiling.
        for i in range(1, 5):
            _filter(st, view, adapter, now=60.0 + i * (START_KICK_GRACE_S + 1))
        # Long past the give-up window, still no draw → IDLE.
        d = _filter(st, view, adapter, now=60.0 + 6 * START_KICK_GRACE_S + START_KICK_GIVEUP_S + 5)
        assert d.intent is ChargerIntent.IDLE
        assert "not latching" in d.reason

    def test_post_latch_hold_then_gentle_settle(self):
        """First draw anchors the debounce, so the latch current holds a
        full ev_min_change_interval_sec before easing toward Min."""
        st = ChargeStability()
        adapter = FakeAdapter(min_current_a=6, max_current_a=16)
        idle = _view(power_w=120.0, ev_min_current=6)
        _filter(st, idle, adapter, now=0.0)
        _filter(st, idle, adapter, now=60.0)
        adapter.last_intent = ChargerIntent.CHARGE_AT_AMPS
        _filter(st, idle, adapter, now=85.0)           # climbed to 8
        drawing = _view(power_w=4140.0, ev_min_current=6)
        d = st.filter(_charge(), drawing, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=90.0)
        assert d.commanded_amps == 8                   # hold the latch current
        d = st.filter(_charge(), drawing, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=150.0)
        assert d.commanded_amps == 8                   # still inside 90 s debounce
        d = st.filter(_charge(), drawing, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=185.0)
        assert d.commanded_amps == 6                   # debounce elapsed → settle

    def test_sustain_floor_does_not_oscillate_on_budget(self):
        """A steady 6 A budget keeps charge_wanted true — no start/stop flip."""
        st = ChargeStability()
        adapter = FakeAdapter(min_current_a=6, max_current_a=16)
        view = _view(power_w=4140.0, ev_min_current=6)
        adapter.last_intent = ChargerIntent.CHARGE_AT_AMPS
        intents = set()
        for t in range(0, 300, 10):
            d = st.filter(_charge(), view, adapter,
                          enable_delay_s=60, disable_delay_s=300, now_ts=float(t))
            intents.add(d.intent)
        assert ChargerIntent.IDLE not in intents


@pytest.mark.unit
class TestNightUnified:
    """Night now shares the SAME latch/hold/escalation as day — only the
    target current (deadline vs surplus) and the day-only guards differ."""

    def test_night_starts_immediately_no_enable_delay(self):
        # Day would IDLE-wait for the surplus to hold; night starts at once.
        st = ChargeStability()
        adapter = FakeAdapter(min_current_a=6, max_current_a=16)
        view = _view(power_w=120.0, is_night=True)
        d = st.filter(_charge(amps=6), view, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=0.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 6

    def test_night_auto_escalates_when_car_wont_latch(self):
        # The exact PROD case: 6 A deadline floor, Zoe draws 0 → climb.
        st = ChargeStability()
        adapter = FakeAdapter(min_current_a=6, max_current_a=16)
        view = _view(power_w=0.0, is_night=True)
        st.filter(_charge(amps=6), view, adapter,
                  enable_delay_s=60, disable_delay_s=300, now_ts=0.0)
        adapter.last_intent = ChargerIntent.CHARGE_AT_AMPS
        d = st.filter(_charge(amps=6), view, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=25.0)
        assert d.commanded_amps == 6 + START_KICK_STEP_A   # 8
        assert "trying" in d.reason

    def test_night_settles_to_deadline_current_after_latch(self):
        st = ChargeStability()
        adapter = FakeAdapter(min_current_a=6, max_current_a=16)
        idle = _view(power_w=0.0, is_night=True)
        st.filter(_charge(amps=6), idle, adapter,
                  enable_delay_s=60, disable_delay_s=300, now_ts=0.0)
        adapter.last_intent = ChargerIntent.CHARGE_AT_AMPS
        st.filter(_charge(amps=6), idle, adapter,
                  enable_delay_s=60, disable_delay_s=300, now_ts=25.0)   # → 8
        drawing = _view(power_w=4140.0, is_night=True)
        d = None
        for t in (60.0, 100.0, 140.0, 180.0):
            d = st.filter(_charge(amps=6), drawing, adapter,
                          enable_delay_s=60, disable_delay_s=300, now_ts=t)
        assert d.commanded_amps == 6                       # deadline current

    def test_transient_dip_holds_steady_no_restart(self):
        """Once latched, a single 0 W reading must NOT trigger a re-start at a
        different current — it holds steady through the dip (the oscillation
        that made the Zoe drop). Day or night."""
        st = ChargeStability()
        adapter = FakeAdapter(min_current_a=6, max_current_a=16,
                              last_intent=ChargerIntent.CHARGE_AT_AMPS)
        drawing = _view(power_w=4140.0, is_night=True)
        # Establish a steady charge at the latched current.
        for t in (0.0, 90.0, 180.0):
            d = st.filter(_charge(amps=6), drawing, adapter,
                          enable_delay_s=60, disable_delay_s=300, now_ts=t)
        held = d.commanded_amps
        # A transient 0 W blip — must hold the same current, not escalate.
        dip = _view(power_w=0.0, is_night=True)
        d = st.filter(_charge(amps=6), dip, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=200.0)
        assert d.commanded_amps == held
        assert "trying" not in d.reason          # did NOT re-start/escalate
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS

    def test_night_idle_passes_through(self):
        # Target reached → planner says IDLE → no day deficit-bridge hold.
        st = ChargeStability()
        adapter = FakeAdapter(min_current_a=6, max_current_a=16,
                              last_intent=ChargerIntent.CHARGE_AT_AMPS)
        view = _view(power_w=120.0, is_night=True)
        d = st.filter(_idle(), view, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=0.0)
        assert d.intent is ChargerIntent.IDLE
