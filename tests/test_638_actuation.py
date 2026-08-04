"""#638 G4 — actuation: the plan feeds the existing signals, fail-open.

Three surfaces, all pure:

* ``plan_gate`` — the trust rule. Every doubt (no plan, stale stamp, out of
  span, demand missing, verdict not ``fits``) resolves to UNCOVERED, and an
  UNCOVERED gate must leave every caller behaving exactly as before G4.
* ``ev_overlay`` — the EV's two signals (wait / amps floor), with the
  reactive guarantees senior: a forcing deadline or an unreachable floor is
  never gated, and waiting is only allowed while the remaining blocks can
  still deliver the remaining floor.
* ``compute_load_intent`` + the imperative passes — ``plan_window`` is an
  extra AND-gate on the tier-2 / cheap-hours starts, never a run reason.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.overnight_actuation import (
    UNCOVERED,
    PlanGate,
    ev_overlay,
    load_window,
    plan_gate,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    compute_load_intent,
)

NOW = datetime(2026, 7, 29, 23, 30)


def _plan(*, status="fits", blocks=None, computed_at=None,
          span=(22, 7), demand_id="ev:ch1"):
    """A minimal G3c-shaped stash: hourly slots 22:00 → 07:00 by default."""
    start_day = NOW.replace(hour=0, minute=0)
    slots = []
    t = start_day.replace(hour=span[0]) - timedelta(days=0)
    if span[0] > NOW.hour:  # window began yesterday evening relative to NOW
        t -= timedelta(days=1) if span[0] <= 23 and NOW.hour < span[0] else timedelta()
    t = NOW.replace(hour=span[0], minute=0)
    if t > NOW:
        t -= timedelta(days=1)
    end = NOW.replace(hour=span[1], minute=0)
    if end <= t:
        end += timedelta(days=1)
    while t < end:
        s_end = min(t + timedelta(hours=1), end)
        slots.append({"start": t.isoformat(), "end": s_end.isoformat()})
        t = s_end
    return {
        "computed_at": (computed_at or NOW - timedelta(hours=1)).isoformat(),
        "fits": status == "fits",
        "demands": [{"id": demand_id, "status": status}],
        "slots": slots,
        "blocks": blocks or [],
    }


def _block(demand_id, start_h, end_h, power_w, minute=0):
    start = NOW.replace(hour=start_h, minute=minute)
    if start_h < 12 and NOW.hour > 12:
        start += timedelta(days=1)
    end = NOW.replace(hour=end_h, minute=minute)
    if end_h < 12 and NOW.hour > 12:
        end += timedelta(days=1)
    if end <= start:
        end += timedelta(days=1)
    return {"id": demand_id, "start": start.isoformat(),
            "end": end.isoformat(), "power_w": power_w}


@pytest.mark.unit
class TestTheTrustRule:
    """UNCOVERED on any doubt — the safe direction is always 'no say'."""

    def test_no_plan_is_uncovered(self):
        assert plan_gate(None, "ev:ch1", NOW) is UNCOVERED
        assert plan_gate("not-a-dict", "ev:ch1", NOW) is UNCOVERED
        assert plan_gate({}, "ev:ch1", NOW) is UNCOVERED

    def test_a_missing_demand_is_uncovered(self):
        assert plan_gate(_plan(), "ev:other", NOW) is UNCOVERED

    def test_a_yielding_demand_is_uncovered(self):
        """The plan could not place the full floor — it has nothing to
        promise, so the reactive layer keeps this demand entirely."""
        for status in ("yields", "partial"):
            assert plan_gate(_plan(status=status), "ev:ch1", NOW) is UNCOVERED

    def test_a_stale_stamp_is_uncovered(self):
        old = _plan(computed_at=NOW - timedelta(hours=15))
        assert plan_gate(old, "ev:ch1", NOW) is UNCOVERED

    def test_outside_the_plans_own_span_is_uncovered(self):
        """A night plan must have no say over the following afternoon —
        a daytime cheap window is not the plan's to block."""
        afternoon = NOW.replace(hour=14) + timedelta(days=1)
        assert plan_gate(_plan(), "ev:ch1", afternoon) is UNCOVERED

    def test_a_malformed_block_distrusts_the_whole_demand(self):
        """Acting on a partial view of a demand's blocks (wrong
        remaining_kwh, wrong membership) is worse than declining —
        malformed data resolves to UNCOVERED, never to an exception."""
        p = _plan(blocks=[{"id": "ev:ch1", "start": "garbage", "end": None,
                           "power_w": "x"}])
        assert plan_gate(p, "ev:ch1", NOW) is UNCOVERED

    def test_a_fits_demand_inside_its_block_is_covered(self):
        p = _plan(blocks=[_block("ev:ch1", 23, 1, 4140)])
        gate = plan_gate(p, "ev:ch1", NOW)
        assert gate.covered and gate.in_block
        assert gate.block_power_w == 4140

    def test_between_blocks_is_covered_but_not_in_block(self):
        p = _plan(blocks=[_block("ev:ch1", 2, 4, 4140)])
        gate = plan_gate(p, "ev:ch1", NOW)
        assert gate.covered and not gate.in_block
        # 2 h × 4.14 kW still deliverable later tonight.
        assert gate.remaining_kwh == pytest.approx(8.28)

    def test_remaining_energy_counts_only_whats_left_of_a_running_block(self):
        p = _plan(blocks=[_block("ev:ch1", 23, 1, 4000)])  # NOW is 23:30
        gate = plan_gate(p, "ev:ch1", NOW)
        assert gate.remaining_kwh == pytest.approx(6.0)  # 1.5 h of 4 kW


@pytest.mark.unit
class TestTheEvOverlay:
    """wait / floor_amps — and the reactive guarantees stay senior."""

    def _gate(self, **kw):
        base = dict(covered=True, in_block=False, block_power_w=0.0,
                    remaining_kwh=10.0)
        base.update(kw)
        return PlanGate(**base)

    def test_uncovered_changes_nothing(self):
        assert ev_overlay(UNCOVERED, remaining_kwh=5, reachable=True,
                          deadline_active=False, watts_per_amp=690,
                          min_amps=6, max_amps=16) == (False, 0)

    def test_a_forcing_deadline_is_never_gated(self):
        assert ev_overlay(self._gate(), remaining_kwh=5, reachable=True,
                          deadline_active=True, watts_per_amp=690,
                          min_amps=6, max_amps=16) == (False, 0)

    def test_an_unreachable_floor_is_never_gated(self):
        assert ev_overlay(self._gate(), remaining_kwh=5, reachable=False,
                          deadline_active=False, watts_per_amp=690,
                          min_amps=6, max_amps=16) == (False, 0)

    def test_in_block_charges_at_least_the_planned_power(self):
        wait, amps = ev_overlay(
            self._gate(in_block=True, block_power_w=4140.0),
            remaining_kwh=5, reachable=True, deadline_active=False,
            watts_per_amp=690, min_amps=6, max_amps=16)
        assert (wait, amps) == (False, 6)  # 4140/690 = exactly 6 A

    def test_planned_amps_clamp_to_the_charger_limits(self):
        _, amps = ev_overlay(
            self._gate(in_block=True, block_power_w=20000.0),
            remaining_kwh=5, reachable=True, deadline_active=False,
            watts_per_amp=690, min_amps=6, max_amps=16)
        assert amps == 16

    def test_outside_a_block_waits_while_the_blocks_still_cover_the_floor(self):
        wait, amps = ev_overlay(
            self._gate(remaining_kwh=8.0),
            remaining_kwh=7.5, reachable=True, deadline_active=False,
            watts_per_amp=690, min_amps=6, max_amps=16)
        assert (wait, amps) == (True, 0)

    def test_outside_a_block_falls_back_when_the_blocks_cannot(self):
        """Reality diverged (slow charger, shrunk window): degrade to the
        pre-G4 reactive top-up, never to a missed floor."""
        wait, amps = ev_overlay(
            self._gate(remaining_kwh=4.0),
            remaining_kwh=7.5, reachable=True, deadline_active=False,
            watts_per_amp=690, min_amps=6, max_amps=16)
        assert (wait, amps) == (False, 0)


def _load(**kw):
    base = dict(
        device_id="pump", control_mode=None, is_active=False,
        has_runtime_deficit=True, battery_eligible_overnight=False,
        top_up_policy="cheap_hours", rated_power=800.0,
        min_power_threshold=800.0, daily_max_runtime_reached=False,
        stop_condition_met=False, daily_targets_met=False,
        is_deadline_approaching=False, _sem_owned=False,
        get_current_consumption=lambda: 0.0,
    )
    base.update(kw)
    dev = SimpleNamespace(**base)
    # control_mode default: SURPLUS — import lazily to keep module scope light
    from custom_components.solar_energy_management.devices.base import (
        DeviceControlMode,
    )
    if dev.control_mode is None:
        dev.control_mode = DeviceControlMode.SURPLUS
    return dev


@pytest.mark.unit
class TestTheLoadWindowGate:
    """plan_window is an AND-gate on the starts — never a run reason."""

    def test_cheap_hours_blocked_outside_the_planned_window(self):
        intent = compute_load_intent(
            _load(), remaining_surplus_w=0.0, price_is_cheap=True,
            is_night=True, plan_window=False)
        assert not intent.on

    def test_cheap_hours_fires_inside_the_planned_window(self):
        intent = compute_load_intent(
            _load(), remaining_surplus_w=0.0, price_is_cheap=True,
            is_night=True, plan_window=True)
        assert intent.on and intent.source == "cheap_grid"

    def test_no_plan_leaves_todays_behaviour(self):
        intent = compute_load_intent(
            _load(), remaining_surplus_w=0.0, price_is_cheap=True,
            is_night=True, plan_window=None)
        assert intent.on and intent.source == "cheap_grid"

    def test_tier2_blocked_outside_the_planned_window(self):
        dev = _load(battery_eligible_overnight=True, top_up_policy="solar_only")
        intent = compute_load_intent(
            dev, remaining_surplus_w=0.0, is_night=True,
            soc_above_reserve=True, plan_window=False)
        assert not intent.on

    def test_tier2_fires_inside_the_planned_window(self):
        dev = _load(battery_eligible_overnight=True, top_up_policy="solar_only")
        intent = compute_load_intent(
            dev, remaining_surplus_w=0.0, is_night=True,
            soc_above_reserve=True, plan_window=True)
        assert intent.on and intent.source == "tier2_battery"

    def test_the_window_never_creates_a_run(self):
        """In-window but no deficit → off. The plan narrows WHEN, the
        execution gates keep deciding WHETHER."""
        dev = _load(has_runtime_deficit=False)
        intent = compute_load_intent(
            dev, remaining_surplus_w=0.0, price_is_cheap=True,
            is_night=True, plan_window=True)
        assert not intent.on

    def test_the_window_does_not_override_the_price_gate(self):
        """In-window while the price level is NOT cheap → the cheap-hours
        clause still refuses; execution's gate stays the guarantee."""
        intent = compute_load_intent(
            _load(), remaining_surplus_w=0.0, price_is_cheap=False,
            is_night=True, plan_window=True)
        assert not intent.on


@pytest.mark.unit
class TestLoadWindowHelper:
    def test_uncovered_means_no_say(self):
        assert load_window(UNCOVERED) is None

    def test_covered_maps_to_the_block_membership(self):
        assert load_window(PlanGate(covered=True, in_block=True)) is True
        assert load_window(PlanGate(covered=True, in_block=False)) is False


@pytest.mark.unit
class TestEverySiteThatComputesANightPlanAppliesTheOverlay:
    """The per-charger-vs-primary parity class (#683/#684), structurally.

    The private night plan is computed at TWO coordinator sites — the
    multi-charger loop and ``_build_charging_context`` (the primary). The
    G4 overlay must sit at every one of them: a site without it actuates
    every charger except the one a single-charger install actually has.
    Pinning the counts equal fails the moment someone adds a third
    ``_compute_night_plan`` call without its ``ev_overlay``.
    """

    def test_overlay_count_matches_plan_count(self):
        from pathlib import Path

        import custom_components.solar_energy_management.coordinator.coordinator as m
        src = Path(m.__file__).read_text()
        plans = src.count("self._compute_night_plan(")
        overlays = src.count("ev_overlay(")
        assert plans >= 2, "expected both known night-plan sites"
        assert overlays == plans, (
            f"{plans} _compute_night_plan site(s) but {overlays} "
            "ev_overlay call(s) — a night-plan site is missing the "
            "#638 G4 joint-plan overlay"
        )
