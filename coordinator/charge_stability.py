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
* **Disable delay** (``ev_disable_delay_seconds``, default 180 s — evcc
  disable.delay = 3 min): a (smoothed) deficit must persist before the
  stop; meanwhile the charger ramps down to and holds minimum current.

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

from ..const import DEFAULT_MAX_CHARGING_CURRENT
from .charger_types import ChargerDecision, ChargerIntent, ChargerView
from .decide import effective_min_amps

if TYPE_CHECKING:  # pragma: no cover
    from .charger_adapters.base import ChargerAdapter

_LOGGER = logging.getLogger(__name__)

# Modes whose DAY decisions are surplus-driven and therefore flicker
# with the solar signal. Night decisions (floors, cheap windows) and
# always_max are deliberate, not flicker — they bypass the filter.
SURPLUS_DAY_MODES = frozenset({"solar_only", "min_plus_solar", "solar_plus_cheap"})

DEFAULT_ENABLE_DELAY_S = 60   # evcc enable.delay = 1 min
DEFAULT_DISABLE_DELAY_S = 180  # evcc disable.delay = 3 min (was 300)
# Stability defaults — evcc-aligned (#546). evcc does NOT freeze the current;
# it TRACKS surplus each control cycle and only writes on a meaningful change
# (whole-amp rounding + a small tolerance), with 1-min start / 3-min stop
# delays. It doesn't flap because the box holds the offered current — so once
# SEM's failsafe is persisted (Phase A: the box no longer reverts to its 6 A
# floor), a steady-needing car (Zoe) charges THROUGH smooth changes, and the
# old long "freeze" is unnecessary. So: track on a ~30 s cadence, only for a
# ≥2 A move, over a 5-cycle median (rejects single-cycle spikes). The deadband
# + median are the anti-flap, not a multi-minute hold. Peak management still
# overrides and reduces promptly (15-min peak window leaves ample headroom).
DEFAULT_SMOOTH_WINDOW = 5
DEFAULT_MIN_CHANGE_AMPS = 2
DEFAULT_MIN_CHANGE_INTERVAL_S = 30  # evcc-style cadence (was 90)
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

# #610 — full-car offer backoff. A single give-up re-armed as soon as the
# surplus persisted again, which against a genuinely-full car produced
# continuous kick-ladder chatter all afternoon (PROD 2026-07-18: car at
# 100 %, kWh-target mode, no vehicle SOC sensor — UDP set_current noise
# against a BMS that kept declining). After this many CONSECUTIVE
# no-latch give-ups the offers stop for FULL_CAR_BACKOFF_S, ended early
# by a real draw (car accepts again, e.g. after preconditioning) or by
# an unplug / mode change / DISABLE. Per the #440 truth model the
# estimated SOC still never gates charging — this tunes the RETRY
# CADENCE only.
FULL_CAR_GIVEUP_STREAK = 3
FULL_CAR_BACKOFF_S = 1200.0

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
        # (#893) The car's DEMONSTRATED latch floor for this session. The
        # start ladder climbs until the car draws, then settles back to the
        # budget minimum — assuming a latched car keeps drawing there. A
        # fussy vehicle does not (live on .175, 01.09: latched and drew
        # 3.1 kW at 8 A, refused 6 A at 0.13 kW standby), so every settle
        # re-ran the whole cycle: ladder up, draw, settle, un-latch — a
        # contactor click every ~3 minutes for as long as the budget sat
        # under the car's floor. Un-latching after a settle to LOWER amps
        # teaches the floor (= the amps it was last drawing at); a draw at
        # lower amps decays it; a disconnect clears it (new car, new floor).
        self._car_floor_a: Dict[str, int] = {}
        self._draw_amps: Dict[str, int] = {}
        # Last time the car was observed drawing — latch hysteresis.
        self._latched: Dict[str, float] = {}
        # #610 — consecutive no-latch give-ups and the full-car backoff
        # deadline (monotonic). Deliberately NOT cleared by _reset(): the
        # give-up path itself calls _reset, and the whole point is that
        # the streak/backoff survive it. Cleared by a real draw, by the
        # out-of-scope branch (unplug / mode change / DISABLE), or expiry.
        self._giveup_streak: Dict[str, int] = {}
        self._giveup_backoff_until: Dict[str, float] = {}
        # Set when the disable-bridge STOPS. While present, an IDLE decision is
        # honoured as-is and the bridge does NOT re-engage even if the car is
        # still drawing (actuator lag) — closes the bounded re-engagement the
        # latch-clear alone leaves. Cleared on a genuine no-draw or a real
        # CHARGE (#461 / PROD 2026-06-27 re-engagement loop).
        self._stopped_at: Dict[str, float] = {}
        # #552 — session OWNERSHIP. Chargers whose current session was started
        # by THIS filter (every charge-commit passes through ``_commit_amps``).
        # The deficit-bridge/hold below only ever engages for owned sessions:
        # a draw SEM didn't command (KEBA auto-start at its stored setpoint,
        # #315) must NOT be adopted and held — that converted "police the
        # rogue draw" into "endorse it at min amps for the grace window",
        # draining the home battery in ~90 s bursts every car-retry (PROD
        # 2026-07-02, solar_only after sunset). Ownership is stability-local
        # on purpose: ``adapter.last_intent`` can go stale (a stability stop
        # that lands while the car happens to blip 0 W never reaches the
        # adapter, leaving last_intent=CHARGE forever).
        self._sem_session: set[str] = set()

    # ------------------------------------------------------------------ #
    # Restart-safe timer persistence (#589)                               #
    # ------------------------------------------------------------------ #

    def snapshot_timers(self, now_mono: float) -> dict:
        """Return elapsed-seconds for each per-charger timer dict.

        Encodes the ELAPSED time (``now_mono - stamp``) rather than the
        raw monotonic stamp so the snapshot is clock-independent — it
        survives an HA restart whose ``time.monotonic()`` begins near 0.

        Only finite, non-negative elapsed values are emitted; negative
        values (clock skew / future stamp) are silently dropped so a
        corrupt snapshot cannot mis-arm a stop on restore.

        The six timer dicts covered: ``deficit``, ``deep_deficit``,
        ``surplus``, ``start``, ``latched``, ``stopped_at``.
        """
        def _elapsed(d: Dict[str, float]) -> Dict[str, float]:
            out = {}
            for cid, stamp in d.items():
                elapsed = now_mono - stamp
                if 0.0 <= elapsed < float("inf"):
                    out[cid] = elapsed
            return out

        return {
            "deficit": _elapsed(self._deficit_since),
            "deep_deficit": _elapsed(self._deep_deficit_since),
            "surplus": _elapsed(self._surplus_since),
            "start": _elapsed(self._start_since),
            "latched": _elapsed(self._latched),
            "stopped_at": _elapsed(self._stopped_at),
            # #610 — full-car backoff survives a restart: the streak as-is,
            # the deadline as REMAINING seconds (it's a future deadline, not
            # an elapsed timer, so the _elapsed shape doesn't fit).
            "giveup_streak": dict(self._giveup_streak),
            "giveup_backoff_remaining": {
                cid: bu - now_mono
                for cid, bu in self._giveup_backoff_until.items()
                if bu - now_mono > 0.0
            },
        }

    def restore_timers(self, saved: dict, now_mono: float) -> None:
        """Rebase persisted elapsed-seconds back onto the current monotonic clock.

        The rebase formula is: ``stamp = now_mono - elapsed``, so that
        ``now_mono - stamp == elapsed`` — the countdown resumes from
        exactly where it was at snapshot time.  We deliberately do NOT
        add downtime (the HA restart gap) — a deep-deficit countdown
        that was 40 s old before restart is still 40 s old after, which
        means a charger that was about to be stopped will be stopped
        promptly rather than being granted a full fresh grace window that
        would drain the battery.

        Guards:
        * ``elapsed < 0`` — impossible (clock moved backward), skip.
        * ``elapsed > 86400`` (24 h) — stale blob or clock jump; skip to
          avoid mis-arming a stop that should have resolved long ago.
        * Malformed input (non-dict, missing keys, non-numeric values) —
          logged at DEBUG and silently ignored; never raises.
        """
        _MAX_ELAPSED_S = 86_400.0

        if not isinstance(saved, dict):
            _LOGGER.debug("restore_timers: saved is not a dict (%r), skipping", type(saved))
            return

        _map: dict[str, Dict[str, float]] = {
            "deficit": self._deficit_since,
            "deep_deficit": self._deep_deficit_since,
            "surplus": self._surplus_since,
            "start": self._start_since,
            "latched": self._latched,
            "stopped_at": self._stopped_at,
        }

        for key, target in _map.items():
            blob = saved.get(key)
            if not isinstance(blob, dict):
                continue
            for cid, elapsed in blob.items():
                try:
                    elapsed_f = float(elapsed)
                except (TypeError, ValueError):
                    _LOGGER.debug(
                        "restore_timers[%s][%s]: non-numeric elapsed %r, skipping",
                        key, cid, elapsed,
                    )
                    continue
                if elapsed_f < 0.0 or elapsed_f >= _MAX_ELAPSED_S:
                    _LOGGER.debug(
                        "restore_timers[%s][%s]: elapsed %.1f s outside valid range "
                        "[0, %.0f], skipping",
                        key, cid, elapsed_f, _MAX_ELAPSED_S,
                    )
                    continue
                target[cid] = now_mono - elapsed_f

        # #610 — full-car backoff round-trip. Streak: plain ints. Deadline:
        # persisted as REMAINING seconds, rebased to now + remaining (same
        # no-downtime-credit philosophy as the elapsed timers — a backoff
        # with 10 min left before restart has 10 min left after). Bounds
        # guard against stale/corrupt blobs.
        streaks = saved.get("giveup_streak")
        if isinstance(streaks, dict):
            for cid, n in streaks.items():
                try:
                    n_i = int(n)
                except (TypeError, ValueError):
                    continue
                if 0 < n_i <= 1000:
                    self._giveup_streak[str(cid)] = n_i
        remaining = saved.get("giveup_backoff_remaining")
        if isinstance(remaining, dict):
            for cid, rem in remaining.items():
                try:
                    rem_f = float(rem)
                except (TypeError, ValueError):
                    continue
                if 0.0 < rem_f <= FULL_CAR_BACKOFF_S:
                    self._giveup_backoff_until[str(cid)] = now_mono + rem_f

    def _reset(self, cid: str) -> None:
        self._surplus_since.pop(cid, None)
        self._deficit_since.pop(cid, None)
        self._deep_deficit_since.pop(cid, None)
        self._stopped_at.pop(cid, None)
        self._amps_history.pop(cid, None)
        self._last_amps.pop(cid, None)
        self._last_change_ts.pop(cid, None)
        self._start_since.pop(cid, None)
        self._start_offer.pop(cid, None)
        self._latched.pop(cid, None)
        self._sem_session.discard(cid)

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
        # #552 — every charge-commit flows through here (fresh start, start
        # kick, mid-session adjust, deficit hold), so this is the single
        # point where a session becomes SEM-owned.
        self._sem_session.add(cid)

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
            or decision.intent is ChargerIntent.RELEASE   # (#898) hands-off
        ):
            self._reset(cid)
            # #610 — an unplug / mode change / DISABLE ends the full-car
            # backoff: a plug or user status change is exactly the signal
            # that should re-open start offers.
            self._giveup_streak.pop(cid, None)
            self._giveup_backoff_until.pop(cid, None)
            self._car_floor_a.pop(cid, None)   # (#893) new plug, new floor
            self._draw_amps.pop(cid, None)
            return decision

        cfg = view.config if isinstance(view.config, dict) else {}
        min_amps = max(
            effective_min_amps(cfg, 6),
            int(getattr(adapter, "min_current_a", 6) or 6),
        )
        # (#789) The old ``or 0`` here was never a default — it was the
        # sentinel for "config is silent, ask the hardware", which is what
        # the adapter branch is for. Spelled as a number it read like a
        # third opinion on the ceiling; spelled as a conditional the intent
        # is the code, and the only default left is the constant.
        _cfg_max = cfg.get("ev_max_current")
        max_amps = int(_cfg_max) if _cfg_max else int(
            getattr(adapter, "max_current_a", DEFAULT_MAX_CHARGING_CURRENT)
            or DEFAULT_MAX_CHARGING_CURRENT,
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
        drawing = adapter.actual_charging(view.power)
        if drawing:
            # #610 — the car accepted current again (e.g. after
            # preconditioning freed BMS headroom): end the backoff.
            self._giveup_streak.pop(cid, None)
            self._giveup_backoff_until.pop(cid, None)

        # (#818) A cycle that cannot SEE must not steer.
        #
        # When a shared input was unavailable, its number is the reader's
        # 0.0 fallback, so the surplus maths reads "no sun, no grid, no
        # battery" and would wind the car down — ~50 times a day on a
        # Huawei modbus install. SEM does not substitute a value for the
        # missing one (that is #741's frozen 8 A, #758's false measured
        # zero and #774's stale belief, all over again). It keeps doing
        # what it was already doing and waits for sight to return.
        #
        # Deliberately narrow:
        #   - only while actually CHARGING — starting needs positive
        #     evidence, and a blind cycle is not evidence;
        #   - only with a committed command to keep;
        #   - clamped to the live floor/ceiling first, because #741 is
        #     precisely a hold that preserved a floor-violating value;
        #   - DISABLE, disconnect and non-surplus modes never arrive here
        #     (returned above) — a stop must never wait for a sensor.
        if view.fleet.inputs_degraded and charging:
            held = self._last_amps.get(cid)
            if held is not None:
                held = max(min_amps, min(max_amps, int(held)))
                # Feed the smoothed stream too, so a dark stretch leaves no
                # hole for the median to snap through on recovery.
                self._median_amps(cid, held, smooth_window)
                self._commit_amps(cid, held, now)
                return replace(
                    decision,
                    intent=ChargerIntent.CHARGE_AT_AMPS,
                    commanded_amps=held,
                    reason=f"inputs degraded (sensor unavailable) — holding {held}A",
                )

        # #610 — full-car backoff gate. MUST sit ABOVE the ``charge_wanted``
        # split, not inside it. It has now moved twice, for two different
        # bypasses of the same shape (a guard on one branch, an unguarded
        # passthrough on the other):
        #   1. fresh-start-only → the ladder block bypassed it, because
        #      ``adapter.last_intent`` stays CHARGE_AT_AMPS across a give-up
        #      (the IDLE actuation is debounced), so the next cycle re-entered
        #      the ladder with freshly-reset state and climbed again.
        #      PROD 2026-07-19: armed 11:10:12, ladder restarted 11:10:42.
        #   2. inside ``charge_wanted`` → the NOT-wanted branch bypassed it.
        #      ``charge_wanted`` is the MEDIAN, which lags the raw decision by
        #      up to ``smooth_window - 1`` cycles: after two low-budget cycles
        #      the median reads below the floor while THIS cycle's decision is
        #      a real CHARGE, so control fell through to one of the three
        #      ``return decision`` passthroughs below (night / post-stop /
        #      #552 ownership) and the raw offer reached the charger unfiltered.
        #      PROD 2026-07-26, window armed 17:35:15-17:55:15: five decisions
        #      escaped (17:41:54 12A, 17:49:36 12A, 17:50:37 12A, 17:52:37 11A,
        #      17:52:47 11A) — recognisable in the log because their reason has
        #      NO ``stability:`` prefix. Trigger was the Huawei grid meter's
        #      single-sample dropouts oscillating the budget.
        # Gating on the RAW state (armed + not drawing) rather than on a
        # smoothed or branch-local one is what closes the class: there is no
        # longer a path from here to an actuation that skips it.
        backoff_until = self._giveup_backoff_until.get(cid)
        if backoff_until is not None and not drawing:
            if now < backoff_until:
                return replace(
                    decision,
                    intent=ChargerIntent.IDLE,
                    commanded_amps=0,
                    reason=(
                        f"stability: full-car backoff — car declined "
                        f"{self._giveup_streak.get(cid, 0)} start "
                        f"ladders; next offer in "
                        f"{max(0.0, backoff_until - now) / 60.0:.0f} min "
                        f"— {decision.reason}"
                    ),
                )
            self._giveup_backoff_until.pop(cid, None)

        if charge_wanted:
            self._deficit_since.pop(cid, None)
            self._deep_deficit_since.pop(cid, None)
            self._stopped_at.pop(cid, None)  # a real charge ends the stop-settle
            target = max(min_amps, min(max_amps, med_amps))
            if drawing:
                self._latched[cid] = now
                # (#893) remember the amps the car is ACTUALLY drawing at,
                # and let a draw at lower amps decay a learned floor.
                _drawn = int(self._last_amps.get(cid) or 0)
                if _drawn > 0:
                    self._draw_amps[cid] = _drawn
                    _f = self._car_floor_a.get(cid)
                    if _f is not None and _drawn < _f:
                        self._car_floor_a[cid] = _drawn
            else:
                # (#893) not drawing while the last recorded draw sat ABOVE
                # this cycle's target = the car told us its floor — both the
                # un-latch right after a settle to lower amps, and a stale
                # draw record from the previous same-plug session (each
                # give-up round used to re-poke 6 A and click the contactor;
                # re-flooring immediately keeps the whole night quiet).
                _ld = self._draw_amps.get(cid)
                if _ld and _ld > target:
                    self._car_floor_a[cid] = _ld
            _floor = self._car_floor_a.get(cid)
            if _floor and target < _floor and not drawing:
                # Offering sub-floor amps is a stop this car executes and a
                # click the contactor pays for; laddering back up just to
                # settle below the floor again is the churn. Hold off until
                # the budget clears the floor (or the night lane sizes it).
                # NEVER while the car is drawing: easing an active draw is
                # _adjust's job, and the ease-below-floor is the one probe
                # that lets the floor DECAY when the car's appetite changes.
                self._reset(cid)
                return replace(
                    decision, intent=ChargerIntent.IDLE, commanded_amps=0,
                    reason=(
                        f"stability: budget {target}A is below this car's "
                        f"demonstrated {_floor}A latch floor — holding off "
                        f"instead of cycling the contactor (#893) — "
                        f"{decision.reason}"
                    ),
                )
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
                # (#610 backoff is gated ABOVE, outside the charge_wanted
                # split — see the two-bypass note there.)
                # Fresh start (no prior charge command). Day waits for the
                # surplus to persist enable_delay_s (anti-flap); night starts
                # at once (the planner already decided). Begin gently at min;
                # the auto-escalation below climbs from here if no draw.
                since = self._surplus_since.setdefault(cid, now)
                held = now - since
                if night or held >= max(0.0, float(enable_delay_s)):
                    self._surplus_since.pop(cid, None)
                    # (#893) same as the ladder default: a known latch
                    # floor starts AT the floor, not at a min the car
                    # already refused. Guard above ensures target >= floor.
                    start_a = max(
                        min_amps,
                        min(max_amps, int(self._car_floor_a.get(cid, min_amps))),
                    )
                    self._start_since[cid] = now
                    self._start_offer[cid] = start_a
                    self._commit_amps(cid, start_a, now)
                    return replace(
                        decision, intent=ChargerIntent.CHARGE_AT_AMPS,
                        commanded_amps=start_a,
                        reason=(f"stability: starting at {start_a}A "
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
            # (#893) A car that demonstrated a latch floor gets offered
            # that floor straight away — poking it at 6 A again is a
            # handshake we already know it refuses (one wasted grace
            # period per start, live on the 31.08 KEBA night). The floor
            # guard above guarantees target >= floor whenever we get here.
            _start_default = max(
                min_amps,
                min(kick_ceiling, int(self._car_floor_a.get(cid, min_amps))),
            )
            offer = int(self._start_offer.get(cid, _start_default))
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
                # #610 — count consecutive give-ups; enough in a row means
                # the car is genuinely full/refusing → long backoff before
                # the next ladder (streak survives expiry, so a still-full
                # car re-arms after ONE further ladder, not three).
                streak = self._giveup_streak.get(cid, 0) + 1
                self._giveup_streak[cid] = streak
                backoff_note = ""
                if streak >= FULL_CAR_GIVEUP_STREAK:
                    self._giveup_backoff_until[cid] = now + FULL_CAR_BACKOFF_S
                    backoff_note = (
                        f" — backing off {FULL_CAR_BACKOFF_S / 60.0:.0f} min "
                        f"after {streak} declined ladders"
                    )
                return replace(
                    decision,
                    intent=ChargerIntent.IDLE,
                    commanded_amps=0,
                    reason=(
                        f"stability: no draw at {offer}A after escalation "
                        f"— car not latching (full/refusing)"
                        f"{backoff_note} — "
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
        # NB: do NOT drop the draw latch here — the deficit-bridge below needs
        # it to survive a bursty car's blips (else the stop timer resets every
        # blip and never fires; PROD 2026-06-26). The bridge refreshes it on
        # each real draw and clears it on a genuine (no-draw) stop.
        if night:
            # Night: no solar-deficit bridge — the night planner owns the
            # start/stop decision (target reached, tariff wait, etc.). Honour
            # whatever it decided (IDLE here) without imposing the day's
            # deficit-persistence hold.
            self._deficit_since.pop(cid, None)
            self._deep_deficit_since.pop(cid, None)
            return decision
        # Post-stop settle: once the bridge has STOPPED, honour the IDLE while
        # the car winds down. Without this, actuator lag (KEBA hasn't cut the
        # contactor yet, so the car still draws on the next cycle) re-stamps the
        # draw-latch and re-opens the hold — the bounded re-engagement the
        # latch-clear alone leaves (review finding, PROD 2026-06-27). When the
        # car has actually stopped drawing, finalize the genuine stop; a real
        # CHARGE clears this flag above so charging always resumes normally.
        if cid in self._stopped_at:
            if not adapter.actual_charging(view.power):
                self._stopped_at.pop(cid, None)
                self._latched.pop(cid, None)
                self._deficit_since.pop(cid, None)
                self._deep_deficit_since.pop(cid, None)
            return decision
        # #552 — OWNERSHIP GATE. The deficit-bridge below exists to protect a
        # session SEM STARTED from flapping on a transient dip. A draw SEM
        # never commanded (KEBA auto-starts at its stored setpoint when the
        # car retries, #315) is NOT a session to hold — bridging it rewrote
        # decide()'s correct IDLE into CHARGE_AT_AMPS min-amps, made the
        # reconciler formally START the rogue session (enable + failsafe-arm
        # + write), and drained the home battery into the car in ~90 s bursts
        # every ~10 min after sunset (PROD 2026-07-02, solar_only, SOC 99%).
        # Pass decide()'s IDLE through untouched: the reconciler's IDLE row
        # stops the un-owned draw. This also covers a coordinator restart
        # mid-deficit: an unknown session in deficit is stopped, not held —
        # policy (decide) says idle, and SEM cannot vouch for a session it
        # doesn't remember starting. (Restart mid-SURPLUS still adopts via
        # the charge_wanted branch above, unchanged.)
        if cid not in self._sem_session:
            self._deficit_since.pop(cid, None)
            self._deep_deficit_since.pop(cid, None)
            self._latched.pop(cid, None)
            return decision
        # Smoothed deficit (day).
        # A bursty car (Zoe) blips ``charging`` False between pulses. Without
        # the latch, every blip reset the deficit timer (line below) so the
        # disable-bridge NEVER reached its threshold — the contactor stayed on
        # and the battery kept feeding the car below the buffer floor (PROD
        # 2026-06-26: timer cycled 170→99→20s, never 180s). Refresh the latch
        # whenever the car actually draws during the bridge (the charge-path
        # latch at line ~291 doesn't run here), then hold the deficit state
        # through a recent draw (LATCH_HOLD_S) so the bridge accumulates to its
        # stop instead of resetting on a transient blip. A car that genuinely
        # stops (no draw for LATCH_HOLD_S) still falls through to the reset.
        if adapter.actual_charging(view.power):
            self._latched[cid] = now
        held_recently = (
            cid in self._latched and (now - self._latched[cid]) <= LATCH_HOLD_S
        )
        if not charging and not held_recently:
            self._deficit_since.pop(cid, None)
            self._deep_deficit_since.pop(cid, None)
            self._latched.pop(cid, None)  # genuine stop — drop the latch
            self._sem_session.discard(cid)  # #552 — session over
            return decision
        since = self._deficit_since.setdefault(cid, now)
        held = now - since

        # Transient dip vs structural stop is decided ONCE in decide()
        # (#461 single source of truth) and carried on ``decision.bridgeable``
        # — the bridge no longer re-derives solar / surplus / SoC / tariff
        # here (that duplication across engines was the bug class). A
        # STRUCTURAL idle (not bridgeable: sun gone, battery can't assist with
        # no real surplus, or a not-cheap tariff) gets only the short grace
        # (absorbs a single-cycle flicker) before a hard stop, so SEM doesn't
        # import grid. A TRANSIENT dip keeps the full disable-delay bridge so a
        # steady car (Zoe) doesn't flap. decide() already appended the
        # structural cause to ``decision.reason`` ("[structural: …]").
        short_grace = not decision.bridgeable
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
            # DURABLE stop: drop the draw-latch too. Without this the bridge
            # re-engages in a loop (PROD 2026-06-27 history: hold → stop →
            # "holding 8A" again, forever). The car was still winding down
            # within LATCH_HOLD_S, so the next cycle saw held_recently=True,
            # skipped the genuine-stop return, re-entered the hold, and
            # re-offered min current — self-sustaining. The latch survives
            # blips DURING a hold; once we STOP it must clear.
            self._latched.pop(cid, None)
            # Arm the post-stop settle so actuator lag (car still drawing next
            # cycle) can't re-open the hold before KEBA cuts the contactor.
            self._stopped_at[cid] = now
            # #552 — SEM ended this session; ownership ends WITH it. Without
            # this, a stability stop that lands while the car blips 0 W never
            # reaches the adapter (reconciler sees idle+no-draw → no-op), the
            # stale CHARGE last_intent kept ``charging`` True, and the bridge
            # re-entered from idle on the next cycle — the self-sustaining
            # burst loop.
            self._sem_session.discard(cid)
            if stop_for_short:
                # Re-stamp so the strategy sensor shows SEM CHOSE to stop;
                # decision.reason already carries the structural cause.
                return replace(
                    decision, intent=ChargerIntent.IDLE, commanded_amps=0,
                    reason=f"stability: structural idle — not bridging — "
                           f"{decision.reason}",
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
