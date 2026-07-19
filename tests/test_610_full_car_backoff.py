"""#610 — full-car offer backoff.

PROD 2026-07-18, car at 100 % (kWh-target mode, no vehicle SOC sensor):
SEM correctly showed "System ready", but the start-kick ladder re-offered
~10 A every time the surplus persisted — the bounded give-up ("car not
latching — full/refusing") re-armed immediately, producing continuous
``keba.set_current`` UDP chatter against a BMS that kept declining.

The fix tunes the RETRY CADENCE only (per the #440 truth model the
estimated SOC never gates charging): after FULL_CAR_GIVEUP_STREAK
consecutive no-latch give-ups, offers stop for FULL_CAR_BACKOFF_S.
Ended early by a real draw (preconditioning wakes the BMS), an unplug /
mode change / DISABLE, or expiry — and after expiry a still-full car
re-arms after ONE further ladder, not three.
"""
import pytest

from custom_components.solar_energy_management.coordinator.charge_stability import (
    ChargeStability,
    FULL_CAR_BACKOFF_S,
    FULL_CAR_GIVEUP_STREAK,
    START_KICK_GIVEUP_S,
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


def _view(*, power_w=0.0, connected=True, cid="wb"):
    return ChargerView(
        power=ChargerPower(charger_id=cid, power_w=power_w,
                           connected=connected, charging=power_w > 500),
        energy=ChargerEnergy(charger_id=cid),
        mode="min_plus_solar",
        config={"ev_min_current": 6, "ev_phases": 3, "ev_voltage": 230,
                "ev_max_current": 16},
        fleet=FleetContext(is_night=False, solar_w=3000.0, min_solar_w=200.0,
                           tariff_level=None),
    )


def _charge(cid="wb", amps=6):
    return ChargerDecision(
        charger_id=cid, mode="min_plus_solar",
        intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=amps,
        budget_w=4140.0, reason="min_plus_solar: surplus ok",
    )


def _filter(st, view, adapter, now):
    return st.filter(_charge(), view, adapter,
                     enable_delay_s=60, disable_delay_s=300, now_ts=now)


def _run_ladder_to_giveup(st, adapter, t0, *, view=None):
    """Walk one full enable→start→escalate→give-up sequence.

    Emulates the real actuation loop: last_intent=None before the fresh
    start (the reconciler idled the charger after the previous give-up),
    CHARGE_AT_AMPS once the start has been commanded. Returns
    ``(final_decision, t_end)``.
    """
    view = view or _view(power_w=120.0)  # plugged, never draws
    adapter.last_intent = None
    d = _filter(st, view, adapter, now=t0)                # arm enable delay
    if "full-car backoff" in d.reason:
        return d, t0
    d = _filter(st, view, adapter, now=t0 + 60.0)         # gentle start
    if "full-car backoff" in d.reason:
        return d, t0 + 60.0
    assert d.intent is ChargerIntent.CHARGE_AT_AMPS
    adapter.last_intent = ChargerIntent.CHARGE_AT_AMPS
    t = t0 + 60.0
    for i in range(1, 5):                                 # climb to ceiling
        t = t0 + 60.0 + i * (START_KICK_GRACE_S + 1)
        _filter(st, view, adapter, now=t)
    t = t + START_KICK_GIVEUP_S + 5
    d = _filter(st, view, adapter, now=t)                 # give-up
    return d, t


LADDER_SPAN = 60.0 + 5 * (START_KICK_GRACE_S + 1) + START_KICK_GIVEUP_S + 60


@pytest.mark.unit
class TestFullCarBackoff:
    def test_single_giveup_does_not_backoff(self):
        st = ChargeStability()
        adapter = FakeAdapter()
        d, _ = _run_ladder_to_giveup(st, adapter, 0.0)
        assert d.intent is ChargerIntent.IDLE
        assert "not latching" in d.reason
        assert "backing off" not in d.reason
        assert "wb" not in st._giveup_backoff_until

    def test_streak_of_giveups_arms_long_backoff(self):
        st = ChargeStability()
        adapter = FakeAdapter()
        t = 0.0
        d = None
        for _ in range(FULL_CAR_GIVEUP_STREAK):
            d, t = _run_ladder_to_giveup(st, adapter, t)
            t += 10.0
        assert "backing off" in d.reason
        assert "wb" in st._giveup_backoff_until
        # Any fresh-start attempt inside the backoff stays quiet — no
        # enable-delay arming, no start command, no ladder.
        adapter.last_intent = None
        for dt in (30.0, 300.0, FULL_CAR_BACKOFF_S - 60.0):
            d2 = _filter(st, _view(power_w=120.0), adapter, now=t + dt)
            assert d2.intent is ChargerIntent.IDLE
            assert "full-car backoff" in d2.reason

    def test_backoff_expires_then_one_giveup_rearms(self):
        st = ChargeStability()
        adapter = FakeAdapter()
        t = 0.0
        for _ in range(FULL_CAR_GIVEUP_STREAK):
            _, t = _run_ladder_to_giveup(st, adapter, t)
            t += 10.0
        # Past expiry the ladder runs again (the re-offer the issue asks
        # to preserve — a car accepting after preconditioning is picked
        # up within one cooldown)...
        t_after = t + FULL_CAR_BACKOFF_S + 10.0
        d, t_end = _run_ladder_to_giveup(st, adapter, t_after)
        # ...but a still-declining car re-arms after ONE ladder, because
        # the streak survives the expiry.
        assert "backing off" in d.reason
        assert st._giveup_backoff_until["wb"] > t_end

    def test_real_draw_clears_streak_and_backoff(self):
        st = ChargeStability()
        adapter = FakeAdapter()
        t = 0.0
        for _ in range(FULL_CAR_GIVEUP_STREAK):
            _, t = _run_ladder_to_giveup(st, adapter, t)
            t += 10.0
        assert "wb" in st._giveup_backoff_until
        # The car starts drawing (e.g. a KEBA auto-start / preconditioning
        # freed BMS headroom) → backoff and streak end immediately.
        adapter.last_intent = None
        d = _filter(st, _view(power_w=4140.0), adapter, now=t + 30.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert "wb" not in st._giveup_backoff_until
        assert "wb" not in st._giveup_streak

    def test_unplug_clears_streak_and_backoff(self):
        st = ChargeStability()
        adapter = FakeAdapter()
        t = 0.0
        for _ in range(FULL_CAR_GIVEUP_STREAK):
            _, t = _run_ladder_to_giveup(st, adapter, t)
            t += 10.0
        assert "wb" in st._giveup_backoff_until
        # Unplug → out-of-scope branch clears the backoff: the plug event
        # is the "status changed" signal that re-opens offers.
        _filter(st, _view(power_w=0.0, connected=False), adapter, now=t + 5.0)
        assert "wb" not in st._giveup_backoff_until
        assert "wb" not in st._giveup_streak
        # Re-plug: a fresh ladder is allowed immediately.
        adapter.last_intent = None
        _filter(st, _view(power_w=120.0), adapter, now=t + 20.0)
        d = _filter(st, _view(power_w=120.0), adapter, now=t + 20.0 + 60.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS

    def test_backoff_survives_restart_via_timer_snapshot(self):
        st = ChargeStability()
        adapter = FakeAdapter()
        t = 0.0
        for _ in range(FULL_CAR_GIVEUP_STREAK):
            _, t = _run_ladder_to_giveup(st, adapter, t)
            t += 10.0
        armed_until = st._giveup_backoff_until["wb"]
        # Snapshot 100 s into the backoff, restore on a fresh instance
        # whose monotonic clock starts near zero (a restart).
        snap = st.snapshot_timers(t + 100.0)
        remaining_before = armed_until - (t + 100.0)
        st2 = ChargeStability()
        st2.restore_timers(snap, 5.0)
        assert st2._giveup_streak["wb"] == FULL_CAR_GIVEUP_STREAK
        restored_remaining = st2._giveup_backoff_until["wb"] - 5.0
        assert restored_remaining == pytest.approx(remaining_before, abs=0.1)
        # And it is ENFORCED on the new instance.
        adapter2 = FakeAdapter()
        d = _filter(st2, _view(power_w=120.0), adapter2, now=10.0)
        assert d.intent is ChargerIntent.IDLE
        assert "full-car backoff" in d.reason

    def test_restore_rejects_corrupt_backoff_blob(self):
        st = ChargeStability()
        st.restore_timers({
            "giveup_streak": {"wb": "many", "ok": 2},
            "giveup_backoff_remaining": {
                "wb": "soon", "neg": -5.0, "huge": FULL_CAR_BACKOFF_S * 10,
                "ok": 300.0,
            },
        }, 100.0)
        assert st._giveup_streak == {"ok": 2}
        assert list(st._giveup_backoff_until) == ["ok"]
        assert st._giveup_backoff_until["ok"] == pytest.approx(400.0)
