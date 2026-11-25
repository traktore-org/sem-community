"""#804 Phase B+C — the phase-switch sequencer and the auto planner.

evcc switches phases mid-charge and patches the fallout per driver:
Easee's cloud imposes a pause they work around, Zaptec silently ignores
a switch unless the current is nudged, and every switch fires a wake-up
retry because "some vehicles may hang on phase switch" (their comment).
SEM buys that whole quirk class away with one default sequence:

    stop → switch → settle → start

~90 s per switch — irrelevant at the frequency the planner and the caps
below allow. The sequencer is the only path a phase switch may take,
manual (Phase B) or automatic (Phase C).

The auto planner adds what evcc doesn't have: dedicated asymmetric
hysteresis (up reasonably fast, down slow), a hard minimum interval
between switches and a per-session cap — the same contactor-protection
philosophy as the #763 ceasefire, applied before the damage.

Pure: clocks passed in, no Home Assistant, no I/O. The caller owns
observed state (charging), belief (config nameplate / the #716 W/A
estimate), and the actual service call — which runs through the same
observer seam as every other actuation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# The post-switch quiet window: no decisions, no phase measurement — the
# car and the box renegotiate. evcc uses the same 60 s.
SETTLE_S = 60.0

# Hard floor between ANY two switches (manual included) — a select is a
# UI element and fat fingers happen; the contactor doesn't care whose.
MIN_SWITCH_GAP_S = 120.0

# (#804) How long the stop before a switch may take. The hold that waits
# for it suppresses every charge command, so an unbounded wait is a charger
# SEM never commands again: @HorizonKane's go-e kept drawing through SEM's
# stop — the one surface that could open it was not configured — and the
# sequence sat in ``stopping`` for the rest of the session. A Zaptec opens
# in 3-15 s (measured). A box still drawing after two minutes is not slow,
# it is not listening, so SEM gives the switch up and says so. Three
# minutes: a cloud-reported charger's power can lag ~90 s (Wallbox), and a
# slow stop must not be read as a deaf one.
STOP_WAIT_S = 180.0

# (#1423) After a switch was dropped because SEM could not read the
# charger's draw through the stop, the next switch that needs a stop waits
# this long. A sensor that goes dark whenever the box stops would otherwise
# get a stop, a three-minute hold and a resume every few minutes. A switch
# at rest (a reading says nothing flows) needs no stop and does not wait.
# The planner's own gap between automatic switches.
BLIND_RETRY_S = 1800.0

# (#1423) After this many such drops in a row, no switch that needs a stop
# is asked for until the target changes or the car is known to be unplugged
# (``forgive_blind``): that charger's power cannot be read through a stop,
# and each try costs a stop and a three-minute hold for nothing.
BLIND_DROPS_MAX = 2

# Phase C hysteresis — up after 5 sustained minutes of headroom, down
# after 10 sustained minutes of starvation. Asymmetric on purpose: a
# missed up-switch costs yield, a flappy down-switch costs the contactor.
AUTO_UP_DELAY_S = 300.0
AUTO_DOWN_DELAY_S = 600.0

# Between automatic switches (per charger). evcc has no such cap; their
# issue history is why we do.
AUTO_MIN_INTERVAL_S = 1800.0

# Automatic switches per charging session — after this, the phase stays
# where it is until the next plug-in.
AUTO_MAX_PER_SESSION = 4

# (#1412) How long thin sun must hold before an idle charger whose phase
# count SEM does not know is set to one phase. The up delay: a start gains
# yield, and no charge is stopped for it.
AUTO_START_DELAY_S = AUTO_UP_DELAY_S

# (#1412) The start window counts only while the planner is asked every
# cycle. A manual phase mode or an unplugged car skips it; a window left
# standing from before must not switch on the first cycle back (#1008).
AUTO_START_GAP_S = 120.0

# Headroom margin required above the 3-phase minimum before scaling up —
# switching up onto a knife edge just schedules the down-switch.
AUTO_UP_MARGIN = 1.10


@dataclass(frozen=True)
class SeqResult:
    state: str                       # idle / stopping / settling
    hold_charging: bool              # force the charger decision to IDLE
    issue_switch: Optional[int]      # fire the switch command NOW (1|3)
    believed_phases: Optional[int]   # sequencer's post-switch belief
    gave_up: bool = False            # (#804) the box never stopped — drop it
    at_rest: bool = False            # (#1412) the switch needed no stop: the
    #                                  charger was not drawing when it fired
    blind_drop: bool = False         # (#1423) dropped: no reading said the
    #                                  stop took before the wait ran out


class PhaseSwitchSequencer:
    """stop → switch → settle, one switch at a time, never under load."""

    def __init__(self) -> None:
        self._state = "idle"
        self._pending: Optional[int] = None
        self._switched_at = 0.0
        self._stopping_since: Optional[float] = None
        self._last_switch_at = float("-inf")
        self._blind_drop_at = float("-inf")
        self._blind_drops = 0
        self._blind_target: Optional[int] = None

    @property
    def in_flight(self) -> bool:
        """(#846) True while a switch is mid-sequence (stopping or settling).
        Anything measured now describes the ramp, not the car — the W/A
        learner gates on this. A property rather than a caller poking
        ``_state``: one name, one truth."""
        return self._state in ("stopping", "settling")

    @property
    def pending(self) -> Optional[int]:
        """(#1412) The phase count a switch in flight is going to, or None.
        A caller whose reason for the switch is "the car draws" must keep
        asking while the car stops for it."""
        return self._pending if self._state != "idle" else None

    @property
    def blind_capped(self) -> bool:
        """(#1423) True once ``BLIND_DROPS_MAX`` switches in a row were
        dropped because the charger's draw could not be read through the
        stop: no switch that needs a stop is asked for until
        ``forgive_blind``."""
        return self._blind_drops >= BLIND_DROPS_MAX

    def forgive_blind(self) -> None:
        """(#1423) A new car (a known unplug): the drops and their wait
        start again."""
        self._blind_drops = 0
        self._blind_target = None
        self._blind_drop_at = float("-inf")

    def _result(self, hold: bool, issue: Optional[int] = None,
                gave_up: bool = False, at_rest: bool = False) -> SeqResult:
        return SeqResult(state=self._state, hold_charging=hold,
                         issue_switch=issue, believed_phases=None,
                         gave_up=gave_up, at_rest=at_rest)

    def _abort(self, gave_up: bool = False) -> SeqResult:
        self._state = "idle"
        self._pending = None
        self._stopping_since = None
        return self._result(hold=False, gave_up=gave_up)

    def cancel(self) -> None:
        """(#1381 D29) The switch just issued did not go out (withheld or
        refused): no settle, and no belief asserted at its end — the
        charger is still on the phases it had."""
        self._abort()

    def _fire(self, now: float, target: int,
              at_rest: bool = False) -> SeqResult:
        self._state = "settling"
        self._pending = target
        self._switched_at = now
        self._last_switch_at = now
        self.forgive_blind()      # (#1423) a switch went out: count again
        return self._result(hold=True, issue=target, at_rest=at_rest)

    def tick(self, now: float, desired_phases: Optional[int],
             believed_phases: Optional[int], charging: bool,
             capability_ready: bool, blind: bool = False) -> SeqResult:
        # (#1423) ``blind``: no reading says whether the charger draws (its
        # power sensor is dark and no status answers), so ``charging`` False
        # is no answer. A blind charger is never at rest: no switch fires
        # while it lasts. A draw seen wins over it.
        blind = bool(blind) and not charging
        # The CALLER's belief is the truth (it carries the measurement);
        # the sequencer only ever asserts a belief ONCE, at settle-end, for
        # the switch it just performed. Live on PROD the sequencer's sticky
        # post-switch belief overwrote the fresh measurement every cycle:
        # the estimate read 3, the belief stayed 1 forever.
        believed = believed_phases

        if self._state == "settling":
            if not capability_ready:
                return self._abort()
            if now - self._switched_at > SETTLE_S:
                # The command is assumed to have taken — said ONCE; the
                # #716 W/A estimate confirms or contradicts once charging
                # resumes, and from then on measurement owns the belief.
                target = self._pending
                self._state = "idle"
                self._pending = None
                return SeqResult(state=self._state, hold_charging=False,
                                 issue_switch=None, believed_phases=target)
            return self._result(hold=True)

        if self._state == "stopping":
            if (not capability_ready or desired_phases is None
                    or desired_phases == believed):
                return self._abort()
            if charging:
                if (self._stopping_since is not None
                        and now - self._stopping_since >= STOP_WAIT_S):
                    # The box is not taking SEM's stop. Holding costs it
                    # every charge command; the switch is the thing to drop.
                    return self._abort(gave_up=True)
                return self._result(hold=True)   # never switch under load
            if blind:
                # (#1423) The stop holds, and nothing fires until a reading
                # says it took. When the wait runs out still blind, the
                # switch is dropped: no reading said the box drew, so it is
                # not blamed ("gave up") and the target is not marked.
                if (self._stopping_since is not None
                        and now - self._stopping_since >= STOP_WAIT_S):
                    self._blind_drop_at = now
                    self._blind_drops += 1
                    self._blind_target = desired_phases
                    self._abort()
                    return SeqResult(
                        state=self._state, hold_charging=False,
                        issue_switch=None, believed_phases=None,
                        blind_drop=True)
                return self._result(hold=True)
            return self._fire(now, desired_phases)   # after a stop: under load

        # idle — look for a trigger
        if (not capability_ready or desired_phases not in (1, 3)
                or desired_phases == believed):
            return self._result(hold=False)
        if now - self._last_switch_at < MIN_SWITCH_GAP_S:
            return self._result(hold=False)
        if blind:
            # (#1423) It may be charging: a switch now could open the
            # contactor under load. Asked again when a reading returns.
            return self._result(hold=False)
        if self._blind_drops and desired_phases != self._blind_target:
            self.forgive_blind()            # a new target: count again
        if charging and (self.blind_capped
                         or now - self._blind_drop_at < BLIND_RETRY_S):
            return self._result(hold=False)
        if charging:
            self._state = "stopping"
            self._pending = desired_phases
            self._stopping_since = now
            return self._result(hold=True)
        return self._fire(now, desired_phases, at_rest=True)


class PhaseAutoPlanner:
    """Phase C: WHAT the phases should be, from sustained surplus.

    The sustain clocks run on every call regardless of gates — starvation
    is a fact about power, not about whether a switch is currently
    permitted — while the interval and session gates only veto the
    ANSWER. The caller reports actual switches via ``note_switched`` and
    plug-cycles via ``new_session``.
    """

    def __init__(self, min_current_a: int, voltage: float) -> None:
        self._one_p_min_w = float(min_current_a) * float(voltage)
        self._three_p_min_w = 3.0 * self._one_p_min_w
        self._up_threshold_w = self._three_p_min_w * AUTO_UP_MARGIN
        self._up_since: Optional[float] = None
        self._down_since: Optional[float] = None
        self._start_since: Optional[float] = None
        self._start_seen = float("-inf")
        self._last_switch_at = float("-inf")
        self._session_switches = 0

    def note_switched(self, now: float, at_rest: bool = False) -> None:
        """A switch went out. ``at_rest``: the charger was not drawing, so
        the contactor was not opened under load. The per-session cap
        protects the contactor from just that, so a switch at rest does not
        count toward it (#1412: a car plugged in for days switched twice a
        day, spent the four on day 2 and sat idle in thin sun on day 3).
        The interval between switches and the daily bound
        (``PHASE_REST_SWITCHES_PER_DAY``, the tick's) still hold."""
        self._last_switch_at = now
        if not at_rest:
            self._session_switches += 1
        self._up_since = None
        self._down_since = None
        self._start_since = None

    def rest(self) -> None:
        """(#1412) No sun to judge by: the night, or a charge the grid pays
        for. The sustain clocks stand still. Left running they read "no
        spare sun" as starvation and set a three-phase charger to one phase
        ten minutes into its night charge."""
        self._up_since = None
        self._down_since = None
        self._start_since = None

    def new_session(self) -> None:
        # A new car (or replug) gets a fresh switch budget; the minimum
        # interval survives the replug — it protects the box, not the car.
        # (#1008) The sustain clocks are the new car's too: a window that
        # filled up while the last car was still here says nothing about
        # this one, and left standing it switched on the first cycle.
        self._session_switches = 0
        self._up_since = None
        self._down_since = None
        self._start_since = None

    def desired(self, now: float, believed: Optional[int],
                surplus_w: float, idle: bool = False) -> Optional[int]:
        """The phase count to switch to, or None.

        ``idle``: the car is connected and draws nothing. Only then may an
        unknown belief be answered (#1412).
        """
        if believed is None:
            self._up_since = None
            self._down_since = None
            # (#1412) The belief comes from a measured draw, and a car that
            # never starts gives none: with less sun than three phases need
            # at the minimum current, auto waited for a number that could
            # not come. An idle charger offered enough for one phase, and
            # too little for three, is set to one phase. Idle only: with a
            # car drawing, the draw is the answer and SEM waits for it. The
            # interval and session caps hold as for every automatic switch.
            if not idle or not (
                    self._one_p_min_w <= surplus_w < self._three_p_min_w):
                self._start_since = None
                return None
            if (self._start_since is None
                    or now - self._start_seen > AUTO_START_GAP_S):
                self._start_since = now
            self._start_seen = now
            if self._session_switches >= AUTO_MAX_PER_SESSION:
                return None
            if now - self._last_switch_at < AUTO_MIN_INTERVAL_S:
                return None
            if now - self._start_since > AUTO_START_DELAY_S:
                return 1
            return None
        self._start_since = None

        # Sustain clocks first — gates only veto the answer.
        if believed >= 3:
            self._up_since = None
            if surplus_w < self._three_p_min_w:
                if self._down_since is None:
                    self._down_since = now
            else:
                self._down_since = None
        else:
            self._down_since = None
            if surplus_w >= self._up_threshold_w:
                if self._up_since is None:
                    self._up_since = now
            else:
                self._up_since = None

        if self._session_switches >= AUTO_MAX_PER_SESSION:
            return None
        if now - self._last_switch_at < AUTO_MIN_INTERVAL_S:
            return None

        if (believed >= 3 and self._down_since is not None
                and now - self._down_since > AUTO_DOWN_DELAY_S):
            return 1
        if (believed == 1 and self._up_since is not None
                and now - self._up_since > AUTO_UP_DELAY_S):
            return 3
        return None
