"""(#1067) The power a load HOLDS — never one reading of it.

A load's rating is learned from its power sensor and only ever goes up, so
whatever number teaches it first stays. A compressor or motor start reads
several times the running draw for a few seconds: lostcontrol's 200 W
dehumidifier was rated ~1.4 kW, so SEM waited for 1.4 kW of surplus before
it would switch it on, and never did.

Both learning paths ask the same question here: what is the highest power
the sensor stayed at or above for ``hold_s`` seconds? A start peak is gone
before the time is up; a running level is not. ``HeldPower`` answers it one
live reading at a time; ``held_power_w`` answers it over recorder history.
"""
from __future__ import annotations

from collections import deque
from typing import Deque, Iterable, Optional, Tuple

from ..consts.core import RATED_POWER_HOLD_S, RATED_POWER_SAMPLE_GAP_S


class HeldPower:
    """The lowest reading over the last ``hold_s`` seconds of an unbroken run
    of readings — the level the load has held for all of them. ``None`` until
    the run is ``hold_s`` long."""

    def __init__(self, hold_s: float = RATED_POWER_HOLD_S,
                 gap_s: float = RATED_POWER_SAMPLE_GAP_S) -> None:
        self._hold_s = float(hold_s)
        self._gap_s = float(gap_s)
        self._samples: Deque[Tuple[float, float]] = deque()
        self._since: Optional[float] = None

    def reset(self) -> None:
        """The load stopped (or we stopped watching it): start again."""
        self._samples.clear()
        self._since = None

    def add(self, t: float, watts: float) -> Optional[float]:
        """Take one reading at monotonic time ``t``; return the held level."""
        if self._samples and (t - self._samples[-1][0] > self._gap_s
                              or t < self._samples[-1][0]):
            self.reset()       # we did not see the time between: no hold
        if self._since is None:
            self._since = t
        self._samples.append((t, float(watts)))
        while self._samples[0][0] < t - self._hold_s:
            self._samples.popleft()
        if t - self._since < self._hold_s:
            return None
        return min(w for _, w in self._samples)


def held_power_w(points: Iterable[Tuple[float, Optional[float]]],
                 end: float, hold_s: float = RATED_POWER_HOLD_S) -> float:
    """The highest power a sensor's history stayed at or above for ``hold_s``.

    ``points`` are ``(time_s, watts)`` state changes, oldest first; each value
    holds until the next change, the last one until ``end``. A value of
    ``None`` (unavailable, not a number) counts as 0 W, so it breaks a run.
    0.0 when no run was ever that long.
    """
    ts, vs = [], []
    for t, w in points:
        ts.append(float(t))
        vs.append(float(w) if w is not None else 0.0)
    n = len(ts)
    if n == 0:
        return 0.0
    ends = ts[1:] + [float(end)]
    best = 0.0
    window: Deque[int] = deque()     # indexes i..j, values rising: [0] is the min
    j = -1
    for i in range(n):
        while window and window[0] < i:
            window.popleft()
        # Grow the window from state i until the states in it cover hold_s.
        while j < n - 1 and (j < i or ends[j] < ts[i] + hold_s):
            j += 1
            while window and vs[window[-1]] >= vs[j]:
                window.pop()
            window.append(j)
        if ends[j] < ts[i] + hold_s:
            break                    # not enough time left after state i
        best = max(best, vs[window[0]])
    return best
