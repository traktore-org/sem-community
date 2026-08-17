"""Unit tests for the night EV charge planner (#246 deadline, #247 tariff).

Pure logic — no HomeAssistant. Covers deadline scaling (short forces higher
current, impossible warns, min/max clamp) and tariff gating (charge when cheap,
wait when waiting still meets Min, charge anyway when Min would be missed).
"""
from datetime import datetime

import pytest

from custom_components.solar_energy_management.coordinator.ev_tariff_planner import (
    plan_night_charge,
    resolve_deadline,
)

# 3-phase * 230 V ≈ 690 W/A (the night default).
WPA = 690.0
NOW = datetime(2026, 5, 26, 22, 0, 0)  # 22:00


def _plan(**kw):
    base = dict(
        now=NOW,
        remaining_to_min_kwh=10.0,
        min_amps=6,
        max_amps=32,
        watts_per_amp=WPA,
        target_time="07:00",
        night_end="07:00",
    )
    base.update(kw)
    return plan_night_charge(**base)


# --------------------------------------------------------------------------
# resolve_deadline
# --------------------------------------------------------------------------
class TestResolveDeadline:
    def test_future_today(self):
        d = resolve_deadline(datetime(2026, 5, 26, 5, 0), "07:00")
        assert d == datetime(2026, 5, 26, 7, 0)

    def test_past_rolls_to_tomorrow(self):
        # 22:00 now, 07:00 deadline → 07:00 tomorrow (night spans midnight)
        d = resolve_deadline(NOW, "07:00")
        assert d == datetime(2026, 5, 27, 7, 0)

    def test_hhmmss_accepted(self):
        d = resolve_deadline(datetime(2026, 5, 26, 5, 0), "07:30:00")
        assert d == datetime(2026, 5, 26, 7, 30)

    def test_blank_and_malformed(self):
        assert resolve_deadline(NOW, None) is None
        assert resolve_deadline(NOW, "") is None
        assert resolve_deadline(NOW, "garbage") is None

    def test_resolve_deadline_dst_fallback_is_actual_elapsed(self):
        # #274/M2: on a fall-back night (Europe/Zurich 2026-10-25, clocks go
        # 03:00 CEST → 02:00 CET), 01:00 → 07:00 is 7 ACTUAL hours, not the 6 a
        # naive wall-clock diff gives. The zoneinfo-aware subtraction must reflect
        # the extra repeated hour so the deadline current isn't mis-sized.
        try:
            from zoneinfo import ZoneInfo
            zh = ZoneInfo("Europe/Zurich")
        except Exception:
            pytest.skip("zoneinfo/tzdata unavailable")
        now = datetime(2026, 10, 25, 1, 0, tzinfo=zh)  # 01:00 CEST
        p = plan_night_charge(
            now=now, remaining_to_min_kwh=10.0, min_amps=6, max_amps=32,
            watts_per_amp=WPA, target_time="07:00", night_end="07:00",
        )
        assert p.hours_to_deadline == pytest.approx(7.0, abs=0.05)


# --------------------------------------------------------------------------
# Deadline scaling (#246)
# --------------------------------------------------------------------------
class TestDeadlineScaling:
    def test_zero_need_no_pressure(self):
        p = _plan(remaining_to_min_kwh=0.0)
        assert p.deadline_amps == 0
        assert not p.deadline_active
        assert p.reachable

    def test_plenty_of_time_uses_min(self):
        # 10 kWh over ~9h = ~1.1 kW → below 6 A floor → not forcing.
        p = _plan(remaining_to_min_kwh=10.0)
        assert p.deadline_amps == 6
        assert not p.deadline_active
        assert p.reachable

    def test_short_deadline_forces_higher_current(self):
        # 20 kWh by 02:00 (4h) → 5 kW → 8 A, deadline-active.
        p = _plan(remaining_to_min_kwh=20.0, target_time="02:00")
        assert p.deadline_amps == 8
        assert p.deadline_active
        assert p.reachable
        assert p.hours_to_deadline == pytest.approx(4.0)

    def test_impossible_deadline_warns(self):
        # 100 kWh by 02:00 (4h); max 32A*0.69kW=22kW*4h=88kWh < 100 → unreachable.
        p = _plan(remaining_to_min_kwh=100.0, target_time="02:00")
        assert p.deadline_amps == 32  # clamped to max
        assert not p.reachable
        assert "unreachable" in p.reason

    def test_required_current_clamped_to_max(self):
        # 60 kWh by 03:00 (5h) → 12 kW → 18 A (within max).
        p = _plan(remaining_to_min_kwh=60.0, target_time="03:00")
        assert p.deadline_amps == pytest.approx(18, abs=1)
        assert p.deadline_active

    def test_deadline_passed_charges_at_max(self):
        # Deadline 21:00 already passed at 22:00 → next is tomorrow 21:00 (far),
        # so use a deadline that resolves in the past via night_end only when
        # target_time omitted. Here force hours_left<=0 by setting target now.
        p = plan_night_charge(
            now=NOW, remaining_to_min_kwh=5.0, min_amps=6, max_amps=32,
            watts_per_amp=WPA, target_time="22:00", night_end="22:00",
        )
        # 22:00 == now → resolve rolls to tomorrow 22:00 (24h away) → reachable.
        assert p.reachable

    def test_no_deadline_no_forcing(self):
        p = plan_night_charge(
            now=NOW, remaining_to_min_kwh=10.0, min_amps=6, max_amps=32,
            watts_per_amp=WPA, target_time=None, night_end=None,
        )
        assert p.deadline_amps == 0
        assert not p.deadline_active

    def test_default_deadline_at_window_end_never_forces(self):
        # The #246 review guard: a charge-by == night-window end (the seeded
        # default) must NOT force current or warn, even with a large target that
        # can't finish by then — existing peak-managed behaviour is preserved.
        p = plan_night_charge(
            now=NOW, remaining_to_min_kwh=80.0, min_amps=6, max_amps=32,
            watts_per_amp=WPA, target_time="07:00", night_end="07:00",
        )
        assert not p.deadline_active   # not forcing
        assert p.reachable             # no warning fired

    def test_deadline_after_window_end_does_not_force(self):
        # A deadline later than the window end adds no constraint → no forcing.
        p = plan_night_charge(
            now=NOW, remaining_to_min_kwh=40.0, min_amps=6, max_amps=32,
            watts_per_amp=WPA, target_time="09:00", night_end="07:00",
        )
        assert not p.deadline_active


# --------------------------------------------------------------------------
# Tariff gating (#247)
# --------------------------------------------------------------------------
class TestPeakAwareRate:
    """#274/C1: reachability sized at the realistic peak-managed rate.

    (#638 one-gate C3) The wait halves of this family died with the
    tariff-gating block — waiting is the overlay's job now. What remains
    is the guarantee math: reachability at the peak-managed rate, the
    opt-in unreachable warning, and the forcing deadline using max.
    """

    def test_non_forcing_unreachable_warns_only_when_opted_in(self):
        # 60 kWh by 07:00 (9h) at 7 A ≈ 4.8 kW → ~43 kWh < 60 → unreachable.
        warned = _plan(remaining_to_min_kwh=60.0, tariff_optimized=True,
                       peak_managed_amps=7)
        assert not warned.reachable
        assert warned.should_warn_unreachable
        quiet = _plan(remaining_to_min_kwh=60.0, tariff_optimized=False, peak_managed_amps=7)
        assert not quiet.reachable
        assert not quiet.should_warn_unreachable  # never opted in → no nag

    def test_forcing_deadline_still_uses_max_rate(self):
        # A forcing deadline overrides peak → reachability uses max, not peak.
        # 40 kWh by 02:00 (4h): at max 22 kW → 88 kWh reachable; peak_managed
        # is irrelevant on the forcing path.
        p = _plan(remaining_to_min_kwh=40.0, target_time="02:00", max_amps=32,
                  peak_managed_amps=6)
        assert p.deadline_active
        assert p.reachable
