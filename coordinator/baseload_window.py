"""(#1394) The live base load as a short mean, house and devices alike.

The live base load is ``home - sum(device draws)``. ``home`` is assembled
from meters that report at their own times: on HA-PROD the grid meter and
the battery each report every 15-25 s, a smart plug every second. A cycle's
``home`` therefore mixes readings up to ~20 s apart, and no single instant
exists at which "the house was complete". When a big plug switches between
those reports, the plug's new draw and the house's old one meet in one
subtraction: 24.11 09:39:19, house 984 W (the coffee machine already off in
the grid read), the coffee machine still counted at 1365 W, base -667 W.

The first fix (draw alignment) took each plug's value at the OLDEST meter
report. That instant is not when ``home`` was made either, so it moved the
error instead of removing it: on 24.11 it gave 17 negative readings where
plain subtraction gave 12.

Subtracting two numbers sampled at different moments is only right on
average. So both sides are averaged over the same short window: the skew of
a few seconds then weighs ``skew / window`` of a step, not all of it. On the
same day a 120 s window gave no negative reading at all (lowest 166 W),
while a real, lasting double count still shows: it is negative in every
sample, so it is negative in the mean.
"""
from __future__ import annotations

from collections import deque
from typing import Deque, Optional, Tuple

#: The averaging window. Several reports of the slowest house meter
#: (15-25 s) fit in it; a lasting double count still shows within two
#: minutes.
WINDOW_S = 120.0


class BaseloadWindow:
    """``(time, home_w, devices_w)`` samples of the last ``WINDOW_S``."""

    def __init__(self, window_s: float = WINDOW_S) -> None:
        self._window = float(window_s)
        self._samples: Deque[Tuple[float, float, float]] = deque()

    def add(self, now: float, home_w: float, devices_w: float) -> float:
        """Note this cycle's pair; return mean(home) - mean(devices).

        A sample stands for the time since the one before it, so an
        irregular cycle does not tilt the mean; the first one in the window
        borrows its neighbour's interval. A clock that runs backwards starts
        the window again.
        """
        samples = self._samples
        if samples and now < samples[-1][0]:
            samples.clear()
        samples.append((float(now), float(home_w), float(devices_w)))
        while samples and samples[0][0] <= now - self._window:
            samples.popleft()
        return self._mean()

    def _mean(self) -> float:
        samples = list(self._samples)
        if len(samples) == 1:
            return samples[0][1] - samples[0][2]
        total = home = devices = 0.0
        for i, (t, h, d) in enumerate(samples):
            span = (t - samples[i - 1][0]) if i else (samples[1][0] - t)
            weight = max(0.0, span)
            total += weight
            home += weight * h
            devices += weight * d
        if total <= 0.0:            # all at one instant (a test burst)
            n = len(samples)
            return (sum(s[1] for s in samples) - sum(s[2] for s in samples)) / n
        return (home - devices) / total

    def clear(self) -> None:
        self._samples.clear()

    @property
    def size(self) -> int:
        return len(self._samples)


def live_baseload(window: Optional[BaseloadWindow], now: float,
                  home_w: float, devices_w: float) -> float:
    """The one producer the coordinator calls; a missing window = plain."""
    if window is None:
        return home_w - devices_w
    return window.add(now, home_w, devices_w)
