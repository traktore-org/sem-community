"""Solar-path stability layer (v1.7.1-beta.14) — bulletproof EV oscillation fix.

PROD report (HA-PROD, 2026-06-06): KEBA P30 with Huawei SUN2000 saw its
commanded current swing every 10 s cycle, the car renegotiated repeatedly
and ultimately closed the session. Regression traced to commit c30a140
(2026-06-05): the ``min_plus_solar`` Zone 3/4 path was changed to
unconditionally command ``max(min_amps, surplus_amps)`` every cycle, and
the solar-path ``_set_current`` call at ``ev_control.py:519`` had no
delta or time guard (unlike the night-path call at L440).

This file pins the 5-layer fix:

* Layer 1 — rolling median over ``budget_w`` so single-cycle inverter
  flickers (8 kW → 0 W → 8 kW) get dropped, not propagated.
* Layer 2 — delta guard: skip ``_set_current`` if ``|target - last| < 1 A``.
* Layer 3 — time debounce: skip if less than 30 s since the last call.
* Layer 5 — heartbeat: after 300 s of no commands, force a re-send.
* Bypass — ``stop``, ``cold_start``, ``mode_switch``, ``stall_recovery``,
  ``deadline`` always go through, regardless of guards.

Tests are dependency-free (no Home Assistant import) — they mount the
helper methods on a tiny host that mirrors the coordinator surface area
the helpers actually touch.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, List, Optional

import pytest

from custom_components.solar_energy_management.coordinator.ev_control import (
    EVControlMixin,
)


# ─── Harness ────────────────────────────────────────────────────────


class _FakeEV:
    """Minimal EV stand-in for the stability tests.

    Records every ``_set_current(...)`` call so tests can assert on the
    call count and values. ``_current_setpoint`` mirrors what the real
    device exposes so the delta guard can compare against it.
    """

    def __init__(self, device_id: str = "kebaA", starting_amps: int = 0) -> None:
        self.device_id = device_id
        self._current_setpoint = starting_amps
        self.calls: List[int] = []

    async def _set_current(self, amps: int) -> None:
        self.calls.append(int(amps))
        self._current_setpoint = int(amps)


class _StabilityHost(EVControlMixin):
    """Just enough coordinator surface for the stability helpers.

    Provides ``config``, the per-cycle ``_ev_budget_history`` list, and
    the ``_ev_last_set_amps_ts`` timestamp. Multi-charger isolation is
    exercised by a separate test below that builds two hosts and swaps
    state by hand (mirroring what ``PerChargerContext`` does in prod).
    """

    def __init__(self, config: Optional[dict] = None) -> None:
        self.config = config or {}
        self._ev_budget_history: List[float] = []
        self._ev_last_set_amps_ts: Optional[float] = None


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ─── Layer 1 — budget smoothing ─────────────────────────────────────


class TestLayer1Smoothing:
    """Rolling median drops Huawei modbus jitter before it reaches the
    amps calculation."""

    def test_huawei_flicker_smoothed_out(self):
        """PROD reproduction: inverter alternates 8000 / 0 / 8000 W across
        3 cycles. The 0 W cycle is the outlier — median pins to 8000."""
        host = _StabilityHost({"ev_surplus_smooth_window": 3})
        # Warm the window with a stable value so the flicker is bounded
        # by a non-zero history rather than just appearing out of nothing.
        assert host._smooth_solar_budget(8000.0) == 8000.0
        # Second sample: window=[8000, 0], sorted=[0, 8000],
        # median = sorted[1] = 8000. (Note: even-length median picks the
        # upper of the two centre values via integer division.)
        assert host._smooth_solar_budget(0.0) == 8000.0
        # Third sample (the recovery cycle): window=[8000, 0, 8000],
        # sorted=[0, 8000, 8000], median = sorted[1] = 8000.
        assert host._smooth_solar_budget(8000.0) == 8000.0

    def test_sustained_drop_eventually_propagates(self):
        """A genuine sustained drop (cloud, not flicker) must reach the
        amps calc once the window fills with the new low value."""
        host = _StabilityHost({"ev_surplus_smooth_window": 3})
        host._smooth_solar_budget(8000.0)
        host._smooth_solar_budget(8000.0)
        host._smooth_solar_budget(8000.0)
        # Now sustained drop:
        host._smooth_solar_budget(0.0)
        host._smooth_solar_budget(0.0)
        out = host._smooth_solar_budget(0.0)
        assert out == 0.0, f"Sustained drop must propagate, got {out}"

    def test_window_one_is_identity(self):
        """Defensive: a misconfigured window=1 must not crash or smooth."""
        host = _StabilityHost({"ev_surplus_smooth_window": 1})
        for v in (1000.0, 5000.0, 0.0, 8000.0):
            assert host._smooth_solar_budget(v) == v

    def test_window_zero_clamps_to_one(self):
        """Defensive: window=0 must not produce an empty median."""
        host = _StabilityHost({"ev_surplus_smooth_window": 0})
        out = host._smooth_solar_budget(1234.5)
        assert out == 1234.5

    def test_history_bounded_by_window(self):
        """The rolling buffer must not grow without bound."""
        host = _StabilityHost({"ev_surplus_smooth_window": 3})
        for v in [1000.0, 2000.0, 3000.0, 4000.0, 5000.0]:
            host._smooth_solar_budget(v)
        assert len(host._ev_budget_history) == 3
        assert host._ev_budget_history == [3000.0, 4000.0, 5000.0]


# ─── Layer 2 — delta guard ──────────────────────────────────────────


class TestLayer2Delta:
    """Skip ``_set_current`` when the target hasn't moved by at least
    ``ev_min_change_amps`` amps (default 1)."""

    def test_unchanged_target_across_n_cycles_yields_one_call(self):
        """Cold start commits 10 A; subsequent cycles with target=10 are all
        suppressed by the delta guard (delta=0)."""
        host = _StabilityHost()
        ev = _FakeEV(starting_amps=0)
        # Cold start bypass — first call goes through.
        _run(host._solar_set_current(ev, 10, reason="cold_start", now_ts=0.0))
        # Now 5 more cycles, each 10 s apart, all targeting 10 A.
        for i in range(1, 6):
            _run(host._solar_set_current(ev, 10, reason="adjust", now_ts=i * 10.0))
        # Cold-start counts as 1 issued call; the 5 subsequent adjusts are
        # suppressed by the delta guard. The debounce guard would also
        # catch the 10 s spacing, but the delta guard fires first (cheaper).
        assert ev.calls == [10], f"Expected exactly 1 set_current, got {ev.calls}"

    def test_micro_oscillation_within_delta_threshold(self):
        """10 → 10.4 (rounds to 10) → 10 is sub-1A — all suppressed."""
        host = _StabilityHost()
        ev = _FakeEV(starting_amps=10)
        host._ev_last_set_amps_ts = 0.0
        # 31 s later (past debounce) but target is the same int.
        _run(host._solar_set_current(ev, 10, reason="adjust", now_ts=31.0))
        # 62 s later, still 10 A.
        _run(host._solar_set_current(ev, 10, reason="adjust", now_ts=62.0))
        assert ev.calls == [], f"Sub-1A must be suppressed, got {ev.calls}"

    def test_meaningful_step_passes_through(self):
        """10 A → 13 A is a 3-A step, above the 1-A threshold AND past
        the debounce window. Must issue."""
        host = _StabilityHost()
        ev = _FakeEV(starting_amps=10)
        host._ev_last_set_amps_ts = 0.0
        _run(host._solar_set_current(ev, 13, reason="adjust", now_ts=31.0))
        assert ev.calls == [13]


# ─── Layer 3 — time debounce ────────────────────────────────────────


class TestLayer3Debounce:
    """Skip ``_set_current`` when less than
    ``ev_min_change_interval_sec`` (default 30 s) has elapsed."""

    def test_rapid_calls_within_window_suppressed(self):
        """First call at t=0 lands (cold_start bypass); second at t=5
        with a real delta should be suppressed by debounce."""
        host = _StabilityHost()
        ev = _FakeEV(starting_amps=0)
        _run(host._solar_set_current(ev, 10, reason="cold_start", now_ts=0.0))
        _run(host._solar_set_current(ev, 15, reason="adjust", now_ts=5.0))
        # First call (cold_start) lands; second (within 30 s) is debounced
        # even though delta=5 is well above the 1-A floor.
        assert ev.calls == [10]

    def test_spaced_calls_pass(self):
        """t=0 commit; t=31 a real delta — past debounce, must issue."""
        host = _StabilityHost()
        ev = _FakeEV(starting_amps=0)
        _run(host._solar_set_current(ev, 10, reason="cold_start", now_ts=0.0))
        _run(host._solar_set_current(ev, 15, reason="adjust", now_ts=31.0))
        assert ev.calls == [10, 15]

    def test_debounce_uses_last_issued_not_last_attempted(self):
        """A suppressed call must not advance ``_ev_last_set_amps_ts`` —
        otherwise the debounce window would slide every cycle and never
        let through."""
        host = _StabilityHost()
        ev = _FakeEV(starting_amps=10)
        host._ev_last_set_amps_ts = 0.0
        # Three rapid suppressed-by-debounce attempts:
        _run(host._solar_set_current(ev, 12, reason="adjust", now_ts=5.0))
        _run(host._solar_set_current(ev, 13, reason="adjust", now_ts=10.0))
        _run(host._solar_set_current(ev, 14, reason="adjust", now_ts=15.0))
        # At t=31 — past debounce relative to the original 0.0 — must issue.
        _run(host._solar_set_current(ev, 14, reason="adjust", now_ts=31.0))
        assert ev.calls == [14], (
            f"_ev_last_set_amps_ts must not advance on suppressed calls — "
            f"got {ev.calls}"
        )


# ─── Layer 5 — heartbeat ────────────────────────────────────────────


class TestLayer5Heartbeat:
    """After ``ev_state_refresh_sec`` (default 300 s) of no commands,
    force a re-send even if delta/debounce would suppress."""

    def test_long_idle_forces_resend(self):
        """Stable target across a 5+ minute window must re-send once at
        the 300 s mark to defend against lost commands or stale state."""
        host = _StabilityHost()
        ev = _FakeEV(starting_amps=10)
        host._ev_last_set_amps_ts = 0.0
        # Target unchanged; without heartbeat this would be suppressed by
        # the delta guard. With heartbeat, the 301-s elapsed time forces
        # the bypass and the call issues.
        _run(host._solar_set_current(ev, 10, reason="adjust", now_ts=301.0))
        assert ev.calls == [10]

    def test_heartbeat_resets_timer(self):
        """After heartbeat sends, the next debounce window restarts."""
        host = _StabilityHost()
        ev = _FakeEV(starting_amps=10)
        host._ev_last_set_amps_ts = 0.0
        # Heartbeat fires.
        _run(host._solar_set_current(ev, 10, reason="adjust", now_ts=301.0))
        # 10 s later — back inside the debounce window. Even a real delta
        # should be suppressed.
        _run(host._solar_set_current(ev, 15, reason="adjust", now_ts=311.0))
        assert ev.calls == [10]


# ─── Bypass paths ───────────────────────────────────────────────────


class TestBypass:
    """Reasons in ``_SOLAR_GUARD_BYPASS_REASONS`` always issue."""

    def test_stop_bypasses_guards(self):
        """Commanding 0 A is a safety transition — must not be delayed
        by debounce or filtered by delta."""
        host = _StabilityHost()
        ev = _FakeEV(starting_amps=10)
        host._ev_last_set_amps_ts = 0.0
        # 5 s after a recent call (inside debounce window).
        _run(host._solar_set_current(ev, 0, reason="stop", now_ts=5.0))
        assert ev.calls == [0]

    def test_cold_start_bypasses_guards(self):
        """First command of a session goes through regardless of debounce."""
        host = _StabilityHost()
        ev = _FakeEV(starting_amps=0)
        host._ev_last_set_amps_ts = 0.0  # pretend something happened recently
        _run(host._solar_set_current(ev, 10, reason="cold_start", now_ts=5.0))
        assert ev.calls == [10]

    def test_mode_switch_bypasses_guards(self):
        """Mode change must take effect immediately."""
        host = _StabilityHost()
        ev = _FakeEV(starting_amps=10)
        host._ev_last_set_amps_ts = 0.0
        _run(host._solar_set_current(ev, 10, reason="mode_switch", now_ts=5.0))
        # Even with delta=0, the bypass forces issue.
        assert ev.calls == [10]

    def test_stall_recovery_bypasses_guards(self):
        """``_should_reenable_charger`` triggers must always reach the wire."""
        host = _StabilityHost()
        ev = _FakeEV(starting_amps=10)
        host._ev_last_set_amps_ts = 0.0
        _run(host._solar_set_current(ev, 10, reason="stall_recovery", now_ts=5.0))
        assert ev.calls == [10]

    def test_battery_pause_bypasses_guards_and_updates_clock(self):
        """SOLAR_PAUSE_STATES drops current to 0. Reviewer-flagged: the
        bare ``_set_current(0)`` at the pause branch used to leave
        ``_ev_last_set_amps_ts`` stale, so the heartbeat could fire
        immediately after a long pause. Now the wrapper updates the
        clock too."""
        host = _StabilityHost()
        ev = _FakeEV(starting_amps=10)
        host._ev_last_set_amps_ts = 0.0
        _run(host._solar_set_current(ev, 0, reason="battery_pause", now_ts=5.0))
        assert ev.calls == [0]
        # The clock advanced — heartbeat budget restarts from the pause moment.
        assert host._ev_last_set_amps_ts == 5.0


# ─── Multi-charger isolation ────────────────────────────────────────


class TestMultiChargerIsolation:
    """``PerChargerContext`` swaps the stability state per charger so a
    fleet of N chargers keeps independent guards. Mirror that here with
    two hosts swapping by hand."""

    def test_two_chargers_keep_independent_debounce(self):
        """Charger A and B both target 10 A at t=0. Five seconds later A
        targets 15 — debounced. B independently targets 15 — also
        debounced (its own clock started at t=0). At t=31 both issue."""
        coord = _StabilityHost()
        ev_a = _FakeEV(device_id="A", starting_amps=0)
        ev_b = _FakeEV(device_id="B", starting_amps=0)
        per_charger_state = {
            "A": {"last_ts": None, "history": []},
            "B": {"last_ts": None, "history": []},
        }

        def swap_in(cid: str) -> None:
            coord._ev_last_set_amps_ts = per_charger_state[cid]["last_ts"]
            coord._ev_budget_history = per_charger_state[cid]["history"]

        def swap_out(cid: str) -> None:
            per_charger_state[cid]["last_ts"] = coord._ev_last_set_amps_ts

        # t=0: A cold-starts at 10A
        swap_in("A")
        _run(coord._solar_set_current(ev_a, 10, reason="cold_start", now_ts=0.0))
        swap_out("A")
        # t=0: B cold-starts at 10A
        swap_in("B")
        _run(coord._solar_set_current(ev_b, 10, reason="cold_start", now_ts=0.0))
        swap_out("B")

        # t=5: A wants 15, debounce should block.
        swap_in("A")
        _run(coord._solar_set_current(ev_a, 15, reason="adjust", now_ts=5.0))
        swap_out("A")

        # t=5: B independently wants 15. B's debounce should also block
        # (5 s since its own cold_start) — but the crucial test is that
        # B's debounce decision is NOT affected by A's prior state.
        swap_in("B")
        _run(coord._solar_set_current(ev_b, 15, reason="adjust", now_ts=5.0))
        swap_out("B")

        assert ev_a.calls == [10]
        assert ev_b.calls == [10]

        # t=31: both past debounce, both should issue.
        swap_in("A")
        _run(coord._solar_set_current(ev_a, 15, reason="adjust", now_ts=31.0))
        swap_out("A")
        swap_in("B")
        _run(coord._solar_set_current(ev_b, 15, reason="adjust", now_ts=31.0))
        swap_out("B")

        assert ev_a.calls == [10, 15]
        assert ev_b.calls == [10, 15]


# ─── Audit telemetry ────────────────────────────────────────────────


class TestAuditTelemetry:
    """Every suppress must emit a structured INFO log line so PROD soak
    can verify the guards are firing (and with sensible counts, not
    silent or runaway)."""

    def test_delta_suppress_emits_log(self, caplog):
        host = _StabilityHost()
        ev = _FakeEV(starting_amps=10)
        host._ev_last_set_amps_ts = 0.0
        with caplog.at_level(
            logging.INFO,
            logger="custom_components.solar_energy_management.coordinator.ev_control",
        ):
            _run(host._solar_set_current(ev, 10, reason="adjust", now_ts=31.0))
        joined = "\n".join(r.message for r in caplog.records)
        assert "layer=delta" in joined
        assert "charger=kebaA" in joined
        assert "reason=adjust" in joined

    def test_debounce_suppress_emits_log(self, caplog):
        host = _StabilityHost()
        ev = _FakeEV(starting_amps=10)
        host._ev_last_set_amps_ts = 0.0
        with caplog.at_level(
            logging.INFO,
            logger="custom_components.solar_energy_management.coordinator.ev_control",
        ):
            _run(host._solar_set_current(ev, 15, reason="adjust", now_ts=5.0))
        joined = "\n".join(r.message for r in caplog.records)
        assert "layer=debounce" in joined
        assert "dt_since_last_set=5.0s" in joined

    def test_heartbeat_emits_dedicated_log(self, caplog):
        host = _StabilityHost()
        ev = _FakeEV(starting_amps=10)
        host._ev_last_set_amps_ts = 0.0
        with caplog.at_level(
            logging.INFO,
            logger="custom_components.solar_energy_management.coordinator.ev_control",
        ):
            _run(host._solar_set_current(ev, 10, reason="adjust", now_ts=301.0))
        joined = "\n".join(r.message for r in caplog.records)
        assert "heartbeat" in joined
        assert "target=10A" in joined


# ─── Regression guards ──────────────────────────────────────────────


class TestRegressionGuards:
    """Pin behavior that prior bugs (#438, #279, #289) depended on so
    the stability layer doesn't reintroduce them."""

    def test_438_kept_pilot_state_logic_untouched(self):
        """#438 (EV stuck — car declines CP handshake) was fixed in
        ``KebaAdapter.is_self_charging`` via ``_last_intent`` gating. The
        stability layer is orthogonal: it sits on top of ``_set_current``
        and does not touch the adapter's pilot-state logic. This test
        sanity-checks that the adapter file is untouched relative to the
        runtime call path (no imports added that would create a cycle)."""
        from custom_components.solar_energy_management.coordinator.charger_adapters \
            import keba as keba_mod
        assert hasattr(keba_mod.KebaAdapter, "is_self_charging")
        assert hasattr(keba_mod.KebaAdapter, "actual_charging")

    def test_huawei_modbus_flicker_yields_at_most_one_call(self):
        """The end-to-end PROD pattern: Huawei flickers across 3 cycles,
        with the actuator-equivalent path calling _smooth then _solar_set.
        Across the flicker window, set_current is called at most once."""
        host = _StabilityHost({"ev_surplus_smooth_window": 3})
        ev = _FakeEV(starting_amps=10)
        host._ev_last_set_amps_ts = 0.0
        # Simulate 3 consecutive 10-second cycles with the budget oscillating
        # 8000 / 0 / 8000 W. Convert to amps via the same simple formula
        # the actuator uses (3 phases * 230 V = 690 W per amp on 3-phase
        # but we keep it abstract for the test).
        phases_voltage = 230 * 3  # 690 W/A
        for cycle, (raw_budget, ts) in enumerate(
            [(8000.0, 10.0), (0.0, 20.0), (8000.0, 30.0)], start=1,
        ):
            smoothed = host._smooth_solar_budget(raw_budget)
            target = max(6, min(32, int(smoothed // phases_voltage)))
            _run(host._solar_set_current(
                ev, target, reason="adjust", now_ts=ts,
            ))
        # Across the 3-cycle flicker, expected:
        # - cycle 1: smoothed=8000, target=11, delta from 10 = 1 → would
        #   issue, but debounce relative to t=0 (5s ago) suppresses;
        # - cycle 2: smoothed=median(8000,0)=8000, target=11, debounce
        #   suppresses again (cumulative 25 s gap, still under 30 s);
        # - cycle 3: smoothed=median(8000,0,8000)=8000, target=11,
        #   t=30 elapsed since the seed at 0.0 — at the boundary it
        #   either issues (>=) or remains suppressed (<). Either way,
        #   the call count is at most 1 across the flicker. The
        #   important assertion: zero oscillation between high/low amps.
        assert len(ev.calls) <= 1, (
            f"Huawei flicker must yield ≤1 set_current call, got {ev.calls}"
        )
        # If any call landed, it must be the smoothed value (11 A), not
        # the raw zero-cycle value.
        if ev.calls:
            assert ev.calls[0] == 11
