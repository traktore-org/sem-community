"""Surplus charge stability — hysteresis delays + setpoint smoothing.

The v1.7 ``decide() → actuate()`` pipeline replaced the legacy
``_execute_ev_control`` solar path and silently dropped its stability
layer (v1.7.1-beta.14). The ``ev_*`` stability config keys kept
existing but nothing read them on the new path — the only surviving
guard was the 2-cycle IDLE debounce in ``actuate``.

RienduPre's #461 logs show both consequences: the contactor cycling
every ~20 s as solar hovered around the 6 A minimum, and the commanded
current bouncing until the car declared the supply unreliable and
ended the session itself.

This module reintroduces the full layer as a stateful filter between
``decide()`` and ``actuate()``:

* **Layer 1 — median smoothing** (``ev_surplus_smooth_window``,
  default 3 cycles): the per-cycle target current stream is
  median-filtered BEFORE any start/stop logic, so a single-cycle
  inverter flicker (Huawei observed 8 kW → 0 W → 8 kW) never becomes
  a decision at all.
* **Layer 2 — delta guard** (``ev_min_change_amps``, default 1 A):
  sub-threshold changes keep the previous setpoint.
* **Layer 3 — time debounce** (``ev_min_change_interval_sec``,
  default 30 s): at most one setpoint CHANGE per window. (Layer 5,
  the heartbeat re-send, lives in ``devices.base._set_current`` #392.)
* **Ramp limit** (``ev_ramp_rate_amps``, default 2 A): mid-session
  adjustments move at most ±ramp per change; a session cold-starts at
  minimum current (the 2026-05-31 PROD grid-overshoot fix) and climbs.
* **Enable delay** (``ev_enable_delay_seconds``, default 60 s): a
  start needs the (smoothed) surplus to hold continuously first.
* **Disable delay** (``ev_disable_delay_seconds``, default 300 s): a
  (smoothed) deficit must persist before the stop; meanwhile the
  charger ramps down to and holds minimum current.

Timing semantics use separate pv enable/disable persistence timers.
The disable semantics deliberately *improve on* the legacy path, which
measured from session START (a minimum-run time): once a session was
older than the window, a single-cycle cloud dip stopped it instantly.
Here the stop is gated on **deficit persistence**, which protects the
contactor for the whole session.

Scope: daytime surplus modes only (``solar_only`` / ``min_plus_solar``
/ ``solar_plus_cheap``). Night floors, ``always_max``, OFF/DISABLE
and disconnected EVs pass through untouched — stopping for safety or
user intent must never be delayed or smoothed.
"""
from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import Dict, List, Optional, TYPE_CHECKING

from .charger_types import ChargerDecision, ChargerIntent, ChargerView
from .decide import effective_min_amps

if TYPE_CHECKING:  # pragma: no cover
    from .charger_adapters.base import ChargerAdapter

_LOGGER = logging.getLogger(__name__)

# Modes whose DAY decisions are surplus-driven and therefore flicker
# with the solar signal. Night decisions (floors, cheap windows) and
# always_max are deliberate, not flicker — they bypass the filter.
SURPLUS_DAY_MODES = frozenset({"solar_only", "min_plus_solar", "solar_plus_cheap"})

DEFAULT_ENABLE_DELAY_S = 60
DEFAULT_DISABLE_DELAY_S = 300
# Stability defaults tuned for a calm, steady charge (cars — a Zoe
# especially — drop a session when the current keeps moving). "Balanced":
# change the offered current at most ~every 90 s and only for a ≥2 A move,
# over a 5-cycle (~50 s) median. Once charging it should look like a
# staircase with rare gentle steps, not a sawtooth. Peak management is the
# only thing allowed to override this and reduce promptly.
DEFAULT_SMOOTH_WINDOW = 5
DEFAULT_MIN_CHANGE_AMPS = 2
DEFAULT_MIN_CHANGE_INTERVAL_S = 90
DEFAULT_RAMP_AMPS = 2

# #461 part 2 — deep-deficit escape from the disable hold. The 300 s
# disable delay is designed to BRIDGE a transient dip — a passing cloud
# that drops solar from 8 kW to 3 kW for a minute while the EV wants 4 —
# by holding minimum current rather than cycling the contactor. But when
# solar is genuinely ~0 (dusk, heavy overcast, the is_night flag not yet
# flipped), there is nothing to bridge TO: that held minimum current is
# pulled entirely from the home battery and the grid. RienduPre's PROD
# logs caught exactly this — solar=0 W, the hold commanding 9 A, the car
# flapping 4.35 kW↔0.12 kW while the battery drained at 5 kW and the grid
# imported 1.7 kW, for the full five-minute window, every window.
#
# So we split the deficit: a TRANSIENT deficit (solar still meaningful,
# >= min_solar_w) keeps the full bridge; a DEEP deficit (solar below
# min_solar_w — the same "no meaningful solar" threshold solar_only's
# decide() idles on) gets only a short grace before a hard stop. The
# grace (not an instant stop) absorbs a single-cycle inverter flicker to
# 0 W (Huawei observed 8 kW → 0 W → 8 kW) so a momentary zero doesn't
# end a real daytime session — it must persist past the grace first.
DEFAULT_DEEP_DEFICIT_GRACE_S = 45

_CHARGE_INTENTS = (ChargerIntent.CHARGE_AT_AMPS, ChargerIntent.CHARGE_MAX)

# #524: tariff levels where bridging a solar deficit by holding minimum
# current would import EXPENSIVE grid. In these windows the transient
# bridge is cut short to the deep-deficit grace instead of the full
# disable delay. ``cheap`` / ``very_cheap`` (and unknown/static → None)
# keep the full bridge — there grid is cheap or price-agnostic.
_NOT_CHEAP_LEVELS = frozenset({"normal", "expensive", "very_expensive"})

# Grace after the gentle min-current start before escalating to the
# ``initial_current`` start-kick when the car still isn't drawing. Some
# vehicles (e.g. a 3-phase EV that needs ~9 A to begin the handshake)
# never latch a 6 A offer; SEM starts gently to avoid the documented
# KEBA cold-start grid overshoot, then — only if no current flows —
# bumps to the higher start-amps to force the latch. Short enough to
# beat the stall detector's refusal (~90 s); long enough to let a
# slightly slow but normal car draw at the minimum first.
START_KICK_GRACE_S = 20.0

# Amps to raise the start offer by each grace when a car won't latch at the
# minimum. SEM climbs min → min+step → … until the car draws, then settles
# back to the target. Auto-discovers a fussy car's latch current, no knob.
START_KICK_STEP_A = 2

# Ceiling for the start escalation. Bounded WELL below the charger max so a
# car that suddenly accepts a high offer can't spike the grid, and a
# full/refusing car is never held at 32 A. Known fussy cars latch under
# this (a Renault Zoe begins at ~9-10 A). The escalation actually climbs to
# ``max(target_current, START_KICK_MAX_A)`` so a high deadline target is
# still reachable.
START_KICK_MAX_A = 10

# After holding the escalation ceiling this long with the car still drawing
# nothing, conclude it won't latch (full / refusing / needs more than we'll
# safely offer) and stop offering — let decide()/the stall detector own the
# refusal instead of holding a high current forever.
START_KICK_GIVEUP_S = 90.0

# Once a car has drawn, treat a low/zero power reading as a transient and
# HOLD the steady current for this long before concluding it really stopped.
# Bridges the brief 0 W blips that would otherwise trigger a re-start at a
# different current — the change that makes a Zoe drop the session. Longer
# than a couple of cycles, shorter than a real "car finished / unplugged".
LATCH_HOLD_S = 60.0


class ChargeStability:
    """Per-charger smoothing + enable/disable delay state.

    One instance lives on the coordinator; all state is keyed by
    charger id so multi-charger fleets get independent windows and
    timers (pinned by ``test_multi_charger_control`` for the legacy
    path — same contract here).
    """

    def __init__(self) -> None:
        self._surplus_since: Dict[str, float] = {}
        self._deficit_since: Dict[str, float] = {}
        self._deep_deficit_since: Dict[str, float] = {}
        self._amps_history: Dict[str, List[int]] = {}
        self._last_amps: Dict[str, int] = {}
        self._last_change_ts: Dict[str, float] = {}
        # When the current start step began (times the auto-escalation), and
        # the current start offer being climbed toward a latch.
        self._start_since: Dict[str, float] = {}
        self._start_offer: Dict[str, int] = {}
        # Last time the car was observed drawing — latch hysteresis.
        self._latched: Dict[str, float] = {}

    def _reset(self, cid: str) -> None:
        self._surplus_since.pop(cid, None)
        self._deficit_since.pop(cid, None)
        self._deep_deficit_since.pop(cid, None)
        self._amps_history.pop(cid, None)
        self._last_amps.pop(cid, None)
        self._last_change_ts.pop(cid, None)
        self._start_since.pop(cid, None)
        self._start_offer.pop(cid, None)
        self._latched.pop(cid, None)

    def _median_amps(self, cid: str, raw_amps: int, window: int) -> int:
        """Layer 1 — rolling median of the raw target-amps stream.

        Median, not mean: a single-cycle flicker is dropped entirely
        rather than halved. For even-length windows the UPPER of the
        two centre values is used — biases toward the recent/higher
        sample, the safe direction for a charge controller (legacy
        ``_smooth_solar_budget`` contract).
        """
        window = max(1, int(window))
        hist = self._amps_history.setdefault(cid, [])
        hist.append(int(raw_amps))
        while len(hist) > window:
            hist.pop(0)
        ordered = sorted(hist)
        return ordered[len(ordered) // 2]

    def _commit_amps(self, cid: str, amps: int, now: float) -> None:
        if self._last_amps.get(cid) != amps:
            self._last_change_ts[cid] = now
        self._last_amps[cid] = amps

    def filter(
        self,
        decision: ChargerDecision,
        view: ChargerView,
        adapter: "ChargerAdapter",
        *,
        enable_delay_s: float = DEFAULT_ENABLE_DELAY_S,
        disable_delay_s: float = DEFAULT_DISABLE_DELAY_S,
        smooth_window: int = DEFAULT_SMOOTH_WINDOW,
        min_change_amps: int = DEFAULT_MIN_CHANGE_AMPS,
        min_change_interval_s: float = DEFAULT_MIN_CHANGE_INTERVAL_S,
        ramp_amps: int = DEFAULT_RAMP_AMPS,
        deep_deficit_grace_s: float = DEFAULT_DEEP_DEFICIT_GRACE_S,
        now_ts: Optional[float] = None,
    ) -> ChargerDecision:
        """Apply smoothing + enable/disable delays to a surplus-mode
        day decision.

        Returns the decision unchanged when out of scope; otherwise a
        possibly-overridden decision whose reason names the active
        guard so the strategy sensor explains the hold (the #461
        "state says idle but EV draws 4.5 kW" confusion class).
        """
        cid = decision.charger_id
        now = now_ts if now_ts is not None else time.monotonic()
        # Day vs night differ ONLY in how the target current is decided
        # (solar surplus vs the night planner's deadline) and in the
        # day-only guards (surplus enable-delay, solar-deficit bridge).
        # The latch/hold/escalation below is SHARED — one charging
        # behaviour for both, so a fussy car (a Zoe that won't start at
        # 6 A) is handled identically day or night.
        night = bool(view.fleet.is_night)

        # Out of scope → transparent. DISABLE (user off / self-resume
        # guard) and disconnects also clear all state: the next
        # session starts a fresh window with a cold history.
        if (
            view.mode not in SURPLUS_DAY_MODES
            or not view.power.connected
            or decision.intent is ChargerIntent.DISABLE
        ):
            self._reset(cid)
            return decision

        cfg = view.config if isinstance(view.config, dict) else {}
        min_amps = max(
            effective_min_amps(cfg, 6),
            int(getattr(adapter, "min_current_a", 6) or 6),
        )
        max_amps = int(cfg.get("ev_max_current", 0) or 0) or int(
            getattr(adapter, "max_current_a", 32) or 32,
        )

        # Raw target this cycle: the decided amps for CHARGE, 0 for
        # IDLE. CHARGE_MAX (not produced by surplus modes, defensive)
        # maps to the ceiling.
        if decision.intent is ChargerIntent.CHARGE_MAX:
            raw_amps = max_amps
        elif decision.intent is ChargerIntent.CHARGE_AT_AMPS:
            raw_amps = int(decision.commanded_amps)
        else:
            raw_amps = 0

        # Layer 1 — the smoothed stream drives ALL start/stop logic,
        # exactly like the legacy path smoothed budget_w before the
        # threshold compare. A 1-cycle dip or spike never reaches the
        # timers below.
        med_amps = self._median_amps(cid, raw_amps, smooth_window)
        charge_wanted = med_amps >= min_amps

        # "Charging" = the adapter last commanded a charge OR the EV is
        # measurably drawing (covers coordinator restarts mid-session,
        # where last_intent is None but power is real).
        charging = (
            getattr(adapter, "last_intent", None) in _CHARGE_INTENTS
            or adapter.actual_charging(view.power)
        )

        if charge_wanted:
            self._deficit_since.pop(cid, None)
            self._deep_deficit_since.pop(cid, None)
            target = max(min_amps, min(max_amps, med_amps))
            drawing = adapter.actual_charging(view.power)
            if drawing:
                self._latched[cid] = now
            # Latch hysteresis: once a car has drawn, a single low/zero power
            # reading is almost always a transient (the car blips, a sensor
            # hiccup) — NOT a reason to re-start at a different current. Any
            # current change re-signals the pilot and many cars (Zoe) drop the
            # session on it, so a naive re-start oscillates forever. Hold the
            # steady current through dips up to LATCH_HOLD_S; only a sustained
            # outage past that falls through to a real re-start.
            held_recently = (
                cid in self._latched and (now - self._latched[cid]) <= LATCH_HOLD_S
            )
            if charging and (drawing or held_recently):
                self._surplus_since.pop(cid, None)
                # First real draw of a SEM-initiated start → adopt the latch
                # current as the steady hold and anchor the debounce clock so
                # the existing ``ev_min_change_interval_sec`` holds it for a
                # full interval before ``_adjust`` eases toward the target.
                if cid in self._start_since:
                    self._start_since.pop(cid, None)
                    self._start_offer.pop(cid, None)
                    self._last_change_ts[cid] = now
                # ``_adjust`` ramp/delta/debounce keep changes rare and gentle.
                # During a dip (held_recently, not drawing) it re-sends the held
                # value — steady — because the target hasn't meaningfully moved.
                return self._adjust(
                    decision, cid, target, now,
                    min_change_amps=min_change_amps,
                    min_change_interval_s=min_change_interval_s,
                    ramp_amps=ramp_amps,
                )
            if not charging:
                # Fresh start (no prior charge command). Day waits for the
                # surplus to persist enable_delay_s (anti-flap); night starts
                # at once (the planner already decided). Begin gently at min;
                # the auto-escalation below climbs from here if no draw.
                since = self._surplus_since.setdefault(cid, now)
                held = now - since
                if night or held >= max(0.0, float(enable_delay_s)):
                    self._surplus_since.pop(cid, None)
                    self._start_since[cid] = now
                    self._start_offer[cid] = min_amps
                    self._commit_amps(cid, min_amps, now)
                    return replace(
                        decision, intent=ChargerIntent.CHARGE_AT_AMPS,
                        commanded_amps=min_amps,
                        reason=(f"stability: starting at {min_amps}A "
                                f"(auto-raises if no draw) — {decision.reason}"),
                    )
                return replace(
                    decision, intent=ChargerIntent.IDLE, commanded_amps=0,
                    reason=(f"stability: surplus must hold {enable_delay_s:.0f}s "
                            f"before start ({held:.0f}s elapsed) — {decision.reason}"),
                )
            # Commanded a charge but the car is NOT drawing. Some
            # vehicles refuse a gentle 6 A handshake and need a brief
            # higher start-amps kick to latch ("Vehicle Start Amps" /
            # ``initial_current``). Hold the gentle current through a
            # short grace, then escalate to ``start_amps`` and keep it
            # until the car draws. A car that never draws is stopped by
            # the stall detector (ev_control), not here.
            # Commanded a charge but the car is NOT drawing. Most cars
            # draw at the minimum immediately; a fussy one (a Zoe needs
            # ~9-10 A to begin the handshake) won't. So if no current
            # flows after a short grace, automatically raise the offer one
            # step and wait again — climbing until the car latches, then
            # settling back to the minimum (the drawing branch above).
            # There is NO separate "start amps" knob: SEM discovers the
            # latch current itself, capped at the charger max. A car that
            # never draws is stopped by the stall detector (ev_control).
            # Bounded ceiling: never escalate past max(target, 10 A),
            # capped at the charger max. Protects the grid from a sudden
            # high-current latch and stops a refusing car being held at 32 A.
            kick_ceiling = min(max_amps, max(target, START_KICK_MAX_A))
            offer = int(self._start_offer.get(cid, min_amps))
            s0 = self._start_since.setdefault(cid, now)
            if offer < kick_ceiling and (now - s0) >= START_KICK_GRACE_S:
                offer = min(kick_ceiling, offer + START_KICK_STEP_A)
                self._start_offer[cid] = offer
                self._start_since[cid] = now  # restart the grace per step
            elif offer >= kick_ceiling and (now - s0) >= START_KICK_GIVEUP_S:
                # Held the ceiling, still no draw → the car won't latch.
                # Stop offering (don't sit at a high current); the stall
                # detector / planner own the refusal.
                self._reset(cid)
                return replace(
                    decision,
                    intent=ChargerIntent.IDLE,
                    commanded_amps=0,
                    reason=(
                        f"stability: no draw at {offer}A after escalation "
                        f"— car not latching (full/refusing) — "
                        f"{decision.reason}"
                    ),
                )
            self._commit_amps(cid, offer, now)
            if offer > min_amps:
                reason = (
                    f"stability: car not drawing — trying {offer}A to "
                    f"start (settles to {target}A) — {decision.reason}"
                )
            else:
                reason = (
                    f"stability: starting at {offer}A "
                    f"(auto-raises if no draw) — {decision.reason}"
                )
            return replace(
                decision,
                intent=ChargerIntent.CHARGE_AT_AMPS,
                commanded_amps=offer,
                reason=reason,
            )

        # charge no longer wanted (smoothed target below the floor).
        self._surplus_since.pop(cid, None)
        self._start_since.pop(cid, None)
        self._start_offer.pop(cid, None)
        self._latched.pop(cid, None)
        if night:
            # Night: no solar-deficit bridge — the night planner owns the
            # start/stop decision (target reached, tariff wait, etc.). Honour
            # whatever it decided (IDLE here) without imposing the day's
            # deficit-persistence hold.
            self._deficit_since.pop(cid, None)
            self._deep_deficit_since.pop(cid, None)
            return decision
        # Smoothed deficit (day).
        if not charging:
            self._deficit_since.pop(cid, None)
            self._deep_deficit_since.pop(cid, None)
            return decision
        since = self._deficit_since.setdefault(cid, now)
        held = now - since

        # #461 part 2 — deep-deficit escape. A deficit while solar is
        # below ``min_solar_w`` is not a cloud to bridge; it is genuine
        # darkness, and the hold's minimum current would come entirely
        # from the battery + grid. Once the deep deficit outlives the
        # short grace (long enough to ride out a single-cycle inverter
        # flicker to 0 W, far shorter than the 300 s transient bridge),
        # stop now instead of holding for the full disable window. A
        # transient deficit (solar still >= min_solar_w) clears the
        # timer and keeps the full bridge below.
        deep_deficit = view.fleet.solar_w < view.fleet.min_solar_w
        # #524: in a NOT-cheap tariff window, holding minimum current to
        # bridge a deficit imports EXPENSIVE grid — exactly what
        # solar_plus_cheap / min_plus_solar exist to avoid. Treat it like a
        # deep deficit (short grace, not the full 300 s bridge). cheap /
        # very_cheap and unknown/static (tariff_level None) keep the bridge.
        expensive_deficit = view.fleet.tariff_level in _NOT_CHEAP_LEVELS
        short_grace = deep_deficit or expensive_deficit
        if short_grace:
            deep_since = self._deep_deficit_since.setdefault(cid, now)
            deep_held = now - deep_since
        else:
            self._deep_deficit_since.pop(cid, None)
            deep_held = 0.0

        stop_for_short = short_grace and deep_held >= max(
            0.0, float(deep_deficit_grace_s),
        )
        if held >= max(0.0, float(disable_delay_s)) or stop_for_short:
            self._deficit_since.pop(cid, None)
            self._deep_deficit_since.pop(cid, None)
            self._amps_history.pop(cid, None)
            self._last_amps.pop(cid, None)
            self._last_change_ts.pop(cid, None)
            # Short-grace stops always re-stamp the reason — even when
            # decide() already idled — so the strategy sensor shows SEM
            # CHOSE to stop (no cheap surplus) rather than silently holding
            # the contactor on battery/grid. The transient-persisted stop
            # keeps the legacy pass-through when already IDLE.
            if stop_for_short:
                if deep_deficit:
                    reason = (
                        f"stability: deep deficit "
                        f"{deep_held:.0f}s/{deep_deficit_grace_s:.0f}s "
                        f"(solar {view.fleet.solar_w:.0f}W < "
                        f"{view.fleet.min_solar_w:.0f}W) — no surplus to "
                        f"bridge — {decision.reason}"
                    )
                else:
                    reason = (
                        f"stability: not-cheap tariff "
                        f"({view.fleet.tariff_level}) "
                        f"{deep_held:.0f}s/{deep_deficit_grace_s:.0f}s — "
                        f"not bridging expensive grid — {decision.reason}"
                    )
                return replace(
                    decision, intent=ChargerIntent.IDLE, commanded_amps=0,
                    reason=reason,
                )
            if decision.intent is ChargerIntent.IDLE:
                return decision
            return replace(
                decision, intent=ChargerIntent.IDLE, commanded_amps=0,
                reason=f"stability: deficit persisted — {decision.reason}",
            )
        # Hold the session: ramp down toward and hold minimum current
        # until the deficit outlives the disable window. (Transient dip,
        # or a deep deficit still inside its short grace.)
        last = self._last_amps.get(cid)
        hold = min_amps if last is None else max(min_amps, last - max(1, int(ramp_amps)))
        self._commit_amps(cid, hold, now)
        return replace(
            decision,
            intent=ChargerIntent.CHARGE_AT_AMPS,
            commanded_amps=hold,
            reason=(
                f"stability: deficit {held:.0f}s/{disable_delay_s:.0f}s — "
                f"holding {hold}A before stop — {decision.reason}"
            ),
        )

    def _adjust(
        self,
        decision: ChargerDecision,
        cid: str,
        target: int,
        now: float,
        *,
        min_change_amps: int,
        min_change_interval_s: float,
        ramp_amps: int,
    ) -> ChargerDecision:
        """Mid-session setpoint adjustment: ramp limit + delta guard +
        time debounce (Layers 2/3 + ramp). The returned decision is
        always CHARGE_AT_AMPS — re-sending an unchanged value is free
        (``_set_current`` dedups and heartbeats, #392)."""
        last = self._last_amps.get(cid)
        if last is None:
            # First filtered cycle of an already-running session
            # (restart / filter newly deployed): adopt the target.
            self._commit_amps(cid, target, now)
            if decision.intent is ChargerIntent.CHARGE_AT_AMPS \
                    and decision.commanded_amps == target:
                return decision
            return replace(
                decision, intent=ChargerIntent.CHARGE_AT_AMPS,
                commanded_amps=target,
                reason=f"stability: smoothed → {target}A — {decision.reason}",
            )

        ramp = max(1, int(ramp_amps))
        ramped = max(last - ramp, min(last + ramp, target))
        suppressed = None
        if abs(ramped - last) < max(0, int(min_change_amps)):
            suppressed = "delta"
        else:
            last_change = self._last_change_ts.get(cid)
            if (
                last_change is not None
                and (now - last_change) < max(0.0, float(min_change_interval_s))
            ):
                suppressed = "debounce"
        amps = last if suppressed else ramped
        self._commit_amps(cid, amps, now)

        if amps == decision.commanded_amps \
                and decision.intent is ChargerIntent.CHARGE_AT_AMPS:
            return decision
        if suppressed:
            note = f"stability: {suppressed} guard — holding {amps}A"
        elif amps != target:
            note = f"stability: ramping {amps}A toward {target}A"
        else:
            note = f"stability: smoothed → {amps}A"
        return replace(
            decision,
            intent=ChargerIntent.CHARGE_AT_AMPS,
            commanded_amps=amps,
            reason=f"{note} — {decision.reason}",
        )
