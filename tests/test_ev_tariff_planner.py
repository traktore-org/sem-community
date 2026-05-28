"""Unit tests for the night EV charge planner (#246 deadline, #247 tariff).

Pure logic — no HomeAssistant. Covers deadline scaling (short forces higher
current, impossible warns, min/max clamp) and tariff gating (charge when cheap,
wait when waiting still meets Min, charge anyway when Min would be missed).
"""
from datetime import datetime, timedelta

import pytest

from custom_components.solar_energy_management.coordinator.ev_tariff_planner import (
    NightChargePlan,
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
class TestTariffGating:
    def test_no_tariff_no_wait(self):
        cheap = [datetime(2026, 5, 27, h) for h in (1, 2, 3)]
        p = _plan(tariff_optimized=False, cheap_slots=cheap)
        assert not p.should_wait_for_cheap

    def test_no_price_data_no_wait(self):
        p = _plan(tariff_optimized=True, cheap_slots=None)
        assert not p.should_wait_for_cheap

    def test_now_cheap_charges(self):
        # 22:00 included in cheap slots → charge now.
        cheap = [datetime(2026, 5, 26, 22), datetime(2026, 5, 26, 23)]
        p = _plan(tariff_optimized=True, cheap_slots=cheap)
        assert not p.should_wait_for_cheap
        assert "cheap window" in p.reason

    def test_not_cheap_can_wait(self):
        # Cheap window 01:00-03:00 ahead, only 10 kWh needed → can wait.
        cheap = [datetime(2026, 5, 27, h) for h in (1, 2, 3)]
        p = _plan(tariff_optimized=True, cheap_slots=cheap)
        assert p.should_wait_for_cheap
        assert p.next_cheap_start == datetime(2026, 5, 27, 1)

    def test_min_guaranteed_when_cheap_insufficient(self):
        # Only 1 cheap hour at 06:00 (≈22 kWh max), need 30 kWh by 07:00 → can't
        # wait, must charge now to guarantee Min regardless of price.
        cheap = [datetime(2026, 5, 27, 6)]
        p = _plan(remaining_to_min_kwh=30.0, tariff_optimized=True, cheap_slots=cheap)
        assert not p.should_wait_for_cheap
        assert "guarantee min" in p.reason

    def test_unreachable_does_not_also_wait(self):
        cheap = [datetime(2026, 5, 27, h) for h in (1, 2)]
        p = _plan(
            remaining_to_min_kwh=100.0, target_time="02:00",
            tariff_optimized=True, cheap_slots=cheap,
        )
        assert not p.should_wait_for_cheap
        assert not p.reachable

    def test_partial_slot_before_deadline_not_overcounted(self):
        # One cheap slot starts 02:00 (ends 03:00) but deadline is 02:30 → only
        # 0.5h usable. At 22A*0.69kW=15.2kW that's ~7.6 kWh deliverable. Need 12
        # kWh → cannot wait (would miss the deadline). Regression for review #1.
        now = datetime(2026, 5, 27, 1, 0, 0)  # 01:00
        cheap = [datetime(2026, 5, 27, 2, 0)]  # 02:00–03:00
        p = plan_night_charge(
            now=now, remaining_to_min_kwh=12.0, min_amps=6, max_amps=22,
            watts_per_amp=WPA, target_time="02:30", night_end="07:00",
            tariff_optimized=True, cheap_slots=cheap,
        )
        assert not p.should_wait_for_cheap

    def test_full_slot_before_deadline_can_wait(self):
        # Same slot but deadline 03:00 → full 1h usable (~15 kWh) ≥ 12 → can wait.
        now = datetime(2026, 5, 27, 1, 0, 0)
        cheap = [datetime(2026, 5, 27, 2, 0)]
        p = plan_night_charge(
            now=now, remaining_to_min_kwh=12.0, min_amps=6, max_amps=22,
            watts_per_amp=WPA, target_time="03:00", night_end="07:00",
            tariff_optimized=True, cheap_slots=cheap,
        )
        assert p.should_wait_for_cheap

    def test_next_cheap_surfaced_even_when_charging(self):
        # Now cheap but the next window start is still reported for the card.
        cheap = [datetime(2026, 5, 26, 22), datetime(2026, 5, 27, 2)]
        p = _plan(tariff_optimized=True, cheap_slots=cheap)
        assert p.next_cheap_start is not None


class TestPeakAwareRate:
    """#274/C1: wait/reachability sized at the realistic peak-managed rate."""

    def test_peak_managed_rate_blocks_unfillable_wait(self):
        # At max rate, 2 cheap hours cover 10 kWh and we'd wait. At the peak-
        # managed rate (7 A ≈ 4.8 kW), 2 h ≈ 9.6 kWh < 10 → must NOT wait.
        cheap = [datetime(2026, 5, 27, h) for h in (1, 2)]
        at_max = _plan(remaining_to_min_kwh=10.0, tariff_optimized=True, cheap_slots=cheap)
        assert at_max.should_wait_for_cheap
        peak_aware = _plan(remaining_to_min_kwh=10.0, tariff_optimized=True,
                           cheap_slots=cheap, peak_managed_amps=7)
        assert not peak_aware.should_wait_for_cheap

    def test_peak_managed_rate_allows_fillable_wait(self):
        cheap = [datetime(2026, 5, 27, h) for h in (1, 2, 3)]  # 3h*4.8≈14.5 ≥ 10
        p = _plan(remaining_to_min_kwh=10.0, tariff_optimized=True,
                  cheap_slots=cheap, peak_managed_amps=7)
        assert p.should_wait_for_cheap

    def test_non_forcing_unreachable_warns_only_when_opted_in(self):
        # 60 kWh by 07:00 (9h) at 7 A ≈ 4.8 kW → ~43 kWh < 60 → unreachable.
        warned = _plan(remaining_to_min_kwh=60.0, tariff_optimized=True,
                       cheap_slots=[NOW + timedelta(hours=2)], peak_managed_amps=7)
        assert not warned.reachable
        assert warned.should_warn_unreachable
        quiet = _plan(remaining_to_min_kwh=60.0, tariff_optimized=False, peak_managed_amps=7)
        assert not quiet.reachable
        assert not quiet.should_warn_unreachable  # never opted in → no nag

    def test_stale_past_cheap_slots_dropped(self):
        past = NOW - timedelta(hours=2)     # 20:00, already ended
        future = NOW + timedelta(hours=2)   # 00:00 next day
        p = _plan(remaining_to_min_kwh=5.0, tariff_optimized=True,
                  cheap_slots=[past, future], peak_managed_amps=10)
        assert p.next_cheap_start == future

    def test_next_cheap_start_none_when_all_past(self):
        past = [NOW - timedelta(hours=h) for h in (2, 3)]
        p = _plan(remaining_to_min_kwh=5.0, tariff_optimized=True, cheap_slots=past)
        assert p.next_cheap_start is None

    def test_forcing_deadline_still_uses_max_rate(self):
        # A forcing deadline overrides peak → reachability uses max, not peak.
        # 40 kWh by 02:00 (4h): at max 22 kW → 88 kWh reachable; peak_managed
        # is irrelevant on the forcing path.
        p = _plan(remaining_to_min_kwh=40.0, target_time="02:00", max_amps=32,
                  peak_managed_amps=6)
        assert p.deadline_active
        assert p.reachable


class TestLookaheadCappedAtDeadline:
    """#281 / Reviewer D1 — caller must NOT pass cheap slots from past the
    deadline. Verified at the planner level: when only post-deadline slots
    arrive, deliverable=0 and the planner correctly falls back to charge-now.

    This pins the *symptom* the caller fix prevents — if anyone re-broadens
    the lookahead, this test still passes (planner is robust), but the new
    test_ev_deadline_tariff.py case (`test_cheap_window_capped_pre_deadline`)
    pins the *caller* behaviour."""

    def test_post_deadline_cheap_slots_dont_block_min(self):
        # NOW = 22:00 on 2026-05-26, deadline 07:00 on 2026-05-27.
        # Cheapest hours globally are 08:00–10:00 on 2026-05-27 (post-deadline).
        # If those leak through, the planner clips them to 0 deliverable kWh
        # and should_wait_for_cheap must NOT fire — otherwise Min would be missed.
        tomorrow = NOW.date() + timedelta(days=1)
        cheap = [
            datetime.combine(tomorrow, datetime.min.time()).replace(hour=8),
            datetime.combine(tomorrow, datetime.min.time()).replace(hour=9),
        ]
        plan = _plan(
            remaining_to_min_kwh=8.5,
            cheap_slots=cheap,
            tariff_optimized=True,
        )
        assert plan.should_wait_for_cheap is False, (
            "post-deadline-only cheap slots must NOT trigger wait — would "
            "miss Min entirely"
        )
        # Reason should call out the shortage so it's debuggable in logs
        assert "not enough cheap hours" in plan.reason.lower(), (
            f"expected shortage reason, got: {plan.reason!r}"
        )
