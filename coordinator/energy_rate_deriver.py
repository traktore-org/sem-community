"""Derive a live power (W) signal from a cumulative energy (kWh) counter (#600).

Load devices (heat pump, hot water, generic) whose only per-device meter is a
``TOTAL_INCREASING`` kWh counter — e.g. Viessmann ViCare's "DHW energy this year"
— have no power sensor to feed. A naive fixed-window derivative spikes: a 0.1 kWh
step landing in a 30 s window reads as ≈ 12 kW.

The fix (see docs/superpowers/specs/2026-07-16-load-device-energy-derive-design.md):
divide each energy step by the **actual elapsed time since the last change**, hold
that value until the next change, and guard the edges (too-fast step, counter reset,
idle decay, absurd-data clamp). The result is a stair-stepped average-power signal —
the best achievable from a lumpy counter, and never a false spike.

Pure + self-contained (state = last baseline + last power); the caller passes a
monotonic timestamp, so it is unit-testable without Home Assistant.
"""

from __future__ import annotations

from typing import Optional

# Defaults — all tunable per instance.
_MIN_DT_S = 5.0          # a step faster than this is noise → hold, don't spike
_IDLE_TIMEOUT_S = 900.0  # counter unmoved this long → device off → decay to 0
_MAX_POWER_W = 30000.0   # absurd-data backstop (overridable per update via rated power)


class EnergyRateDeriver:
    """Turn a monotonically-increasing kWh counter into a live power (W) value."""

    def __init__(
        self,
        *,
        min_dt_s: float = _MIN_DT_S,
        idle_timeout_s: float = _IDLE_TIMEOUT_S,
        max_power_w: float = _MAX_POWER_W,
    ) -> None:
        self._min_dt_s = min_dt_s
        self._idle_timeout_s = idle_timeout_s
        self._max_power_w = max_power_w
        self._baseline_kwh: Optional[float] = None
        self._baseline_t: Optional[float] = None
        self._last_power_w: float = 0.0

    @property
    def last_power_w(self) -> float:
        return self._last_power_w

    def reset(self) -> None:
        """Forget the baseline (e.g. the source sensor went unavailable)."""
        self._baseline_kwh = None
        self._baseline_t = None
        self._last_power_w = 0.0

    def update(
        self,
        energy_kwh: Optional[float],
        now_s: float,
        *,
        max_power_w: Optional[float] = None,
    ) -> float:
        """Feed the latest counter reading; return the derived power in W.

        ``now_s`` is a monotonic timestamp (seconds). ``max_power_w`` overrides
        the clamp for this reading (e.g. ``2 × rated_power`` when known).
        """
        cap = max_power_w if max_power_w is not None else self._max_power_w

        # Unreadable reading → hold the last value (don't fabricate a change).
        if energy_kwh is None:
            return self._last_power_w

        # First reading → establish the baseline, no rate yet.
        if self._baseline_kwh is None or self._baseline_t is None:
            self._baseline_kwh = energy_kwh
            self._baseline_t = now_s
            self._last_power_w = 0.0
            return 0.0

        # TOTAL_INCREASING reset / yearly rollover → re-baseline, read 0.
        if energy_kwh < self._baseline_kwh:
            self._baseline_kwh = energy_kwh
            self._baseline_t = now_s
            self._last_power_w = 0.0
            return 0.0

        # Counter unchanged → hold the last power until the device is clearly
        # idle (no step for idle_timeout), then decay to 0.
        if energy_kwh == self._baseline_kwh:
            if now_s - self._baseline_t > self._idle_timeout_s:
                self._last_power_w = 0.0
            return self._last_power_w

        # A real step. Ignore a step that arrives faster than min_dt (avoids the
        # divide-by-tiny spike) WITHOUT advancing the baseline — so the energy
        # keeps accumulating until enough wall-clock has passed to divide by.
        dt = now_s - self._baseline_t
        if dt < self._min_dt_s:
            return self._last_power_w

        power = (energy_kwh - self._baseline_kwh) * 3_600_000.0 / dt
        power = min(power, cap)
        self._baseline_kwh = energy_kwh
        self._baseline_t = now_s
        self._last_power_w = power
        return power
