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

# Headroom margin required above the 3-phase minimum before scaling up —
# switching up onto a knife edge just schedules the down-switch.
AUTO_UP_MARGIN = 1.10


@dataclass(frozen=True)
class SeqResult:
    state: str                       # idle / stopping / settling
    hold_charging: bool              # force the charger decision to IDLE
    issue_switch: Optional[int]      # fire the switch command NOW (1|3)
    believed_phases: Optional[int]   # sequencer's post-switch belief


class PhaseSwitchSequencer:
    """stop → switch → settle, one switch at a time, never under load."""

    def __init__(self) -> None:
        self._state = "idle"
        self._pending: Optional[int] = None
        self._switched_at = 0.0
        self._last_switch_at = float("-inf")

    @property
    def in_flight(self) -> bool:
        """(#846) True while a switch is mid-sequence (stopping or settling).
        Anything measured now describes the ramp, not the car — the W/A
        learner gates on this. A property rather than a caller poking
        ``_state``: one name, one truth."""
        return self._state in ("stopping", "settling")

    def _result(self, hold: bool, issue: Optional[int] = None) -> SeqResult:
        return SeqResult(state=self._state, hold_charging=hold,
                         issue_switch=issue, believed_phases=None)

    def _abort(self) -> SeqResult:
        self._state = "idle"
        self._pending = None
        return self._result(hold=False)

    def _fire(self, now: float, target: int) -> SeqResult:
        self._state = "settling"
        self._pending = target
        self._switched_at = now
        self._last_switch_at = now
        return self._result(hold=True, issue=target)

    def tick(self, now: float, desired_phases: Optional[int],
             believed_phases: Optional[int], charging: bool,
             capability_ready: bool) -> SeqResult:
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
                return self._result(hold=True)   # never switch under load
            return self._fire(now, desired_phases)

        # idle — look for a trigger
        if (not capability_ready or desired_phases not in (1, 3)
                or desired_phases == believed):
            return self._result(hold=False)
        if now - self._last_switch_at < MIN_SWITCH_GAP_S:
            return self._result(hold=False)
        if charging:
            self._state = "stopping"
            self._pending = desired_phases
            return self._result(hold=True)
        return self._fire(now, desired_phases)


class PhaseAutoPlanner:
    """Phase C: WHAT the phases should be, from sustained surplus.

    The sustain clocks run on every call regardless of gates — starvation
    is a fact about power, not about whether a switch is currently
    permitted — while the interval and session gates only veto the
    ANSWER. The caller reports actual switches via ``note_switched`` and
    plug-cycles via ``new_session``.
    """

    def __init__(self, min_current_a: int, voltage: float) -> None:
        self._three_p_min_w = 3.0 * float(min_current_a) * float(voltage)
        self._up_threshold_w = self._three_p_min_w * AUTO_UP_MARGIN
        self._up_since: Optional[float] = None
        self._down_since: Optional[float] = None
        self._last_switch_at = float("-inf")
        self._session_switches = 0

    def note_switched(self, now: float) -> None:
        self._last_switch_at = now
        self._session_switches += 1
        self._up_since = None
        self._down_since = None

    def new_session(self) -> None:
        # A new car (or replug) gets a fresh switch budget; the minimum
        # interval survives the replug — it protects the box, not the car.
        self._session_switches = 0

    def desired(self, now: float, believed: Optional[int],
                surplus_w: float) -> Optional[int]:
        if believed is None:
            self._up_since = None
            self._down_since = None
            return None

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
