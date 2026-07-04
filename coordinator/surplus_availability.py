"""Surplus availability signal for user automations (#559 Phase 0).

``peak_only`` is SEM's "bring your own automation" device mode — the
user's automation runs the device, SEM only sheds for peaks. For those
automations to *catch* the surplus, SEM exposes a debounced
availability signal:

- ``binary_sensor.sem_surplus_available`` — ON when the unallocated
  surplus has stayed above the configurable threshold for a sustain
  period; OFF when it has stayed below the hysteresis floor (80 % of
  the threshold) for the release period.
- A ``solar_energy_management_surplus`` bus event fired on every
  TRANSITION (never per-cycle — a flapping cloud must not storm the
  automation bus).

The state machine is pure (time injected) so the debounce is unit-
testable without HA.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Debounce: surplus must hold above threshold this long before ON …
SUSTAIN_ON_SECONDS = 60.0
# … and below the hysteresis floor this long before OFF. Longer than
# the ON sustain so short dips (cloud edges) don't drop the signal.
SUSTAIN_OFF_SECONDS = 120.0
# OFF evaluates against threshold × this factor (hysteresis band).
HYSTERESIS_FACTOR = 0.8

DEFAULT_THRESHOLD_W = 1500.0


@dataclass
class SurplusTransition:
    """Returned when the availability state flips."""
    available: bool
    surplus_w: float
    threshold_w: float


class SurplusAvailability:
    """Debounced above/below-threshold state machine."""

    def __init__(self) -> None:
        self.available: bool = False
        self._above_since: Optional[float] = None
        self._below_since: Optional[float] = None

    def update(
        self, surplus_w: float, threshold_w: float, now_mono: float
    ) -> Optional[SurplusTransition]:
        """Feed one cycle; returns a transition when the state flips."""
        if threshold_w <= 0:
            threshold_w = DEFAULT_THRESHOLD_W

        if not self.available:
            self._below_since = None
            if surplus_w >= threshold_w:
                if self._above_since is None:
                    self._above_since = now_mono
                if now_mono - self._above_since >= SUSTAIN_ON_SECONDS:
                    self.available = True
                    self._above_since = None
                    return SurplusTransition(True, surplus_w, threshold_w)
            else:
                self._above_since = None
        else:
            self._above_since = None
            if surplus_w < threshold_w * HYSTERESIS_FACTOR:
                if self._below_since is None:
                    self._below_since = now_mono
                if now_mono - self._below_since >= SUSTAIN_OFF_SECONDS:
                    self.available = False
                    self._below_since = None
                    return SurplusTransition(False, surplus_w, threshold_w)
            else:
                self._below_since = None
        return None
