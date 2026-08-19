"""#800 — the battery's night, written down.

The #755 learner answers demand-size questions; #778's budget question
("how much may tonight spend") needs the battery's night as a SUPPLY
story. Three series, none recorded anywhere before this module:

* **Overnight drain** — flow-attributed (``battery_to_home`` only). A SOC
  delta would conflate house drain with evening EV assist and export,
  poisoning the series the moment the assist feature this feeds ever
  runs. Assist and export are recorded beside it for attribution.
* **Morning refill** — when the pack first reached full, against the
  dampened forecast's promise captured at day start.
* **Clipping hours** — SOC full while export runs: the only possible
  evidence for "more could have been spent last night for free".

Design rules inherited from the learner (#755), adapted where the
direction flips:

* Silence is not a measurement: an unmeasured cycle or a sampling hole
  accumulates ``gap_s`` and refuses the night (``trainable=False``) —
  never integrated across.
* Censoring is explicit and here it points DOWN: a night where the
  battery hit reserve and the grid took over observes LESS drain than
  the house needed (``reserve_hit`` — the budget's consumer must treat
  such drains as floors, the mirror of the demand learner's ceilings).
* Covariates are stamped, not modeled: date and outdoor temperature ride
  the record so a heating-season bucketing is POSSIBLE later; building
  buckets waits for real records (the pillar rule).

Recording only — the budget consumer is #778 (2.1). Pure: values in,
values out. No clock, no I/O, no Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# A sampling hole longer than this is a gap: nothing is integrated
# across it and the night is refused. Mirrors demand_outcome's guard.
MAX_SAMPLE_GAP_S = 300.0

# "Full" for refill/clipping purposes. 99.5 would miss BMS balancing
# plateaus that sit at 99.x for hours while the pack is, for every
# practical purpose, full and clipping.
FULL_SOC = 99.0

# Export above this counts as clipping while the pack is full — below it
# is metering noise around zero.
CLIP_EXPORT_W = 50.0

# Reserve slack: SOC within this of the configured reserve counts as
# having reached the floor (SOC sensors step in whole percent).
RESERVE_EPS = 1.0

DEFAULT_MAX_NIGHTS = 60


@dataclass
class Sample:
    """One cycle's readings, flows in watts."""
    battery_to_home_w: float = 0.0
    battery_to_ev_w: float = 0.0
    battery_to_grid_w: float = 0.0
    # (#778 spec) The house's overnight NEED is drain + what the grid
    # supplied meanwhile — battery_to_home alone under-observes it on any
    # night the battery sat at reserve or a mode kept it out of the loop.
    grid_to_home_w: float = 0.0
    # Day-phase house consumption — lets 2.1 decompose a missed refill
    # promise into PV-wrong vs consumption-wrong.
    home_w: float = 0.0
    soc: Optional[float] = None
    soc_available: bool = True
    export_w: float = 0.0
    measured: bool = True


class BatteryNightTracker:
    """Night → day → seal-at-next-night state machine.

    One record spans night N and the FOLLOWING day, because the refill
    and the clipping ARE the day's answer to the night's question. It
    seals when the next night begins.
    """

    def __init__(self, reserve_soc: float,
                 max_nights: int = DEFAULT_MAX_NIGHTS) -> None:
        self.reserve_soc = float(reserve_soc)
        self.max_nights = int(max_nights)
        self._sealed: List[Dict[str, Any]] = []
        self._reset()

    def _reset(self) -> None:
        self._phase = "idle"           # idle / night / day
        self._date: Optional[str] = None
        self._last_ts: Optional[float] = None
        self._drain_j = 0.0            # watt-seconds
        self._assist_j = 0.0
        self._export_j = 0.0
        self._gap_s = 0.0
        self._reserve_hit = False
        self._soc_start: Optional[float] = None
        self._soc_morning: Optional[float] = None
        self._soc_seen = False
        self._temp_c: Optional[float] = None
        self._forecast_kwh: Optional[float] = None
        self._refill_full_at: Optional[float] = None
        self._clipped_s = 0.0
        self._night_grid_j = 0.0
        self._day_home_j = 0.0

    # ── lifecycle ────────────────────────────────────────────────

    def start(self, night_date: str,
              outdoor_temp_c: Optional[float]) -> None:
        """Open a night. An open record that never reached its seal is
        dropped — a half night teaches nothing safely."""
        self._reset()
        self._phase = "night"
        self._date = str(night_date)
        self._temp_c = outdoor_temp_c

    def set_forecast_kwh(self, kwh: Optional[float]) -> None:
        """The dampened forecast's promise for the refill day — first
        call wins; a later restatement is a different claim than the one
        the morning should be judged against (#755 pillar 2's rule)."""
        if self._forecast_kwh is None and kwh is not None:
            self._forecast_kwh = float(kwh)

    def tick(self, now: float, in_night: bool, s: Sample) -> None:
        if self._phase == "idle":
            return
        dt = 0.0
        if self._last_ts is not None:
            dt = max(0.0, now - self._last_ts)
        self._last_ts = now

        if dt > MAX_SAMPLE_GAP_S:
            self._gap_s += dt
            dt = 0.0                    # never integrate across a hole
        if not s.measured:
            self._gap_s += dt
            dt = 0.0

        if self._phase == "night":
            if not in_night:
                # Morning: freeze the night half, open the day half. The
                # flip tick's SOC belongs to the DAY — the night's morning
                # value is whatever its own last tick recorded.
                self._phase = "day"
                return
            if s.soc_available and s.soc is not None:
                self._soc_seen = True
            if dt > 0:
                self._drain_j += s.battery_to_home_w * dt
                self._assist_j += s.battery_to_ev_w * dt
                self._export_j += s.battery_to_grid_w * dt
                self._night_grid_j += s.grid_to_home_w * dt
            if s.soc_available and s.soc is not None:
                if self._soc_start is None:
                    self._soc_start = float(s.soc)
                self._soc_morning = float(s.soc)
                if s.soc <= self.reserve_soc + RESERVE_EPS:
                    self._reserve_hit = True
            return

        # ── day phase ──
        if in_night:
            self._sealed.append(self._record())
            del self._sealed[:-self.max_nights]
            self._reset()
            return
        if dt > 0:
            self._day_home_j += s.home_w * dt
        if s.soc_available and s.soc is not None and s.soc >= FULL_SOC:
            if self._refill_full_at is None:
                self._refill_full_at = now
            if dt > 0 and s.export_w > CLIP_EXPORT_W:
                self._clipped_s += dt

    # ── reads ────────────────────────────────────────────────────

    @property
    def phase(self) -> str:
        return self._phase


    def _record(self) -> Dict[str, Any]:
        return {
            "date": self._date,
            "drain_kwh": round(self._drain_j / 3.6e6, 3),
            "assist_kwh": round(self._assist_j / 3.6e6, 3),
            "export_kwh": round(self._export_j / 3.6e6, 3),
            "soc_start": self._soc_start,
            "soc_morning": self._soc_morning,
            "reserve_hit": self._reserve_hit,
            "night_grid_kwh": round(self._night_grid_j / 3.6e6, 3),
            "day_home_kwh": round(self._day_home_j / 3.6e6, 3),
            "gap_s": round(self._gap_s, 1),
            "trainable": self._gap_s == 0.0 and self._soc_seen,
            "refill_full_at": self._refill_full_at,
            "clipped_hours": round(self._clipped_s / 3600.0, 2),
            "forecast_kwh": self._forecast_kwh,
            "outdoor_temp_c": self._temp_c,
        }

    def sealed(self) -> List[Dict[str, Any]]:
        return list(self._sealed)

    # ── persistence (restart mid-night must not halve the record) ──

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase": self._phase, "date": self._date,
            "last_ts": self._last_ts,
            "drain_j": self._drain_j, "assist_j": self._assist_j,
            "export_j": self._export_j, "gap_s": self._gap_s,
            "reserve_hit": self._reserve_hit,
            "soc_start": self._soc_start,
            "soc_morning": self._soc_morning,
            "soc_seen": self._soc_seen, "temp_c": self._temp_c,
            "forecast_kwh": self._forecast_kwh,
            "refill_full_at": self._refill_full_at,
            "clipped_s": self._clipped_s,
            "night_grid_j": self._night_grid_j,
            "day_home_j": self._day_home_j,
            "sealed": list(self._sealed),
        }

    def from_dict(self, d: Optional[Dict[str, Any]]) -> None:
        if not isinstance(d, dict) or not d:
            return
        self._phase = str(d.get("phase", "idle"))
        self._date = d.get("date")
        # A restart IS a hole in the sampling — the next tick's dt spans
        # the reboot and the gap guard prices it honestly. Keeping
        # last_ts persisted does exactly that; forcing it to None would
        # integrate across the outage instead.
        self._last_ts = d.get("last_ts")
        self._drain_j = float(d.get("drain_j", 0.0) or 0.0)
        self._assist_j = float(d.get("assist_j", 0.0) or 0.0)
        self._export_j = float(d.get("export_j", 0.0) or 0.0)
        self._gap_s = float(d.get("gap_s", 0.0) or 0.0)
        self._reserve_hit = bool(d.get("reserve_hit", False))
        self._soc_start = d.get("soc_start")
        self._soc_morning = d.get("soc_morning")
        self._soc_seen = bool(d.get("soc_seen", False))
        self._temp_c = d.get("temp_c")
        self._forecast_kwh = d.get("forecast_kwh")
        self._refill_full_at = d.get("refill_full_at")
        self._clipped_s = float(d.get("clipped_s", 0.0) or 0.0)
        self._night_grid_j = float(d.get("night_grid_j", 0.0) or 0.0)
        self._day_home_j = float(d.get("day_home_j", 0.0) or 0.0)
        sealed = d.get("sealed")
        if isinstance(sealed, list):
            self._sealed = [r for r in sealed if isinstance(r, dict)]
            del self._sealed[:-self.max_nights]
