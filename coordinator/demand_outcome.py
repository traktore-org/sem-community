"""#755 — the per-demand outcome recorder.

The overnight plan captures two of the three numbers that matter: what each
demand ASKED for (the demand signature) and what the packer PROMISED it (the
allocation). The third — what it actually DID — was never written down. That
gap is why "fits" has never been checked against reality, why the morning
report has nothing to compare, and why a learning layer would have nothing to
read.

This module writes the third number.

Two design constraints drive everything here:

**The night is one unit.** A night spans midnight, and SEM's per-device runtime
accumulators live in the daily bucket that empties there (the #753 wart). So the
recorder integrates its own energy from power samples and is persisted in the
DURABLE energy store, not the daily one.

**An estimate is not a measurement.** Every sample carries a ``measured`` flag,
and one estimated sample is enough to mark the whole record untrainable. This is
deliberate strictness: #743 (curtailed days poisoning the dampening model), #744
(an energy-tick estimate teaching the up-only rated-power ratchet) and #753 (a
warm-up sensor teaching a disconnect) were all the same mistake — a guess
entering a model through a door marked "measurement". A learner is a far bigger
blast radius than a ratchet, so the door is nailed shut here rather than at each
consumer.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, NamedTuple, Optional

# A sample gap longer than this means we stopped watching (restart, hang). The
# power reading on the far side says nothing about the hole, so the interval is
# recorded as a gap rather than integrated — integrating across it would invent
# energy that never flowed.
DEFAULT_MAX_GAP_S = 900

# Nights kept. Enough for the learner to see behaviour across a month without
# unbounded growth in the store.
DEFAULT_MAX_NIGHTS = 60


class Draw(NamedTuple):
    """A demand's instantaneous draw, and whether it is a MEASUREMENT.

    The second field is the whole point. Every source SEM has answers the
    honesty question differently, and the answer must be decided HERE — at the
    sensor — not inferred later by whoever consumes the record.
    """

    watts: float
    measured: bool


def device_draw(device) -> Draw:
    """A load's or comfort demand's draw.

    ``observed_power_w`` returns None when the device has neither a power
    sensor nor an energy counter — it deliberately does NOT substitute
    ``rated_power`` (devices/base.py:371). We do substitute it, because the
    morning report should still say roughly what ran, but the number is flagged
    for what it is. ``rated_power`` is itself a learned up-only ratchet (#744);
    letting it back into a learner as a measurement would close the loop on
    SEM's own guess.

    An idle unobservable device gets 0 W and is STILL unmeasured: "SEM
    commanded it off" is a command, not a reading.
    """
    try:
        watts = device.observed_power_w()
    except Exception:                              # noqa: BLE001
        watts = None
    if watts is not None:
        return Draw(float(watts), True)
    if getattr(device, "is_active", False):
        return Draw(float(getattr(device, "rated_power", 0.0) or 0.0), False)
    return Draw(0.0, False)


def ev_draw(charger_id: str, power, charger_count: int = 1,
            charger_w: Optional[float] = None,
            has_own_sensor: bool = False) -> Draw:
    """One charger's draw, and whether anything charger-specific answered.

    Four cases, and only the last is dishonest:

    1. the cycle's per-charger map has this charger — smoothed and normalized
       by the sensor reader (measured);
    2. a legacy top-level power entity on this charger (measured) — the caller
       passes the value it already read through ``_charger_power_w``, the
       canonical accessor, rather than opening a second read path;
    3. the sole charger in the install, where the fleet total IS its draw
       (measured);
    4. the fleet total standing in for one of SEVERAL chargers — the
       documented #315 over-count fallback. Off by every other car on the
       property. Shown to the user, never taught to a model.
    """
    per = getattr(power, "ev_power_per_charger", None) or {}
    if charger_id in per:
        return Draw(float(per[charger_id] or 0.0), True)
    if has_own_sensor:
        return Draw(float(charger_w or 0.0), True)
    fleet = float(getattr(power, "ev_power", 0.0) or 0.0)
    return Draw(fleet, int(charger_count or 1) <= 1)


def battery_draw(power) -> Draw:
    """The battery's charge power, and whether a sensor actually said so.

    ``battery_charge_power`` is ``max(0, battery_power)``, and
    ``battery_power`` is 0.0 when its sensor could not be read — so an
    offline battery meter and an idle battery produce the same number.
    This used to return ``measured=True`` for both, which put a confident
    zero in the night ledger and made the morning verdict say the battery
    took none of what it asked for when the truth was that nobody looked.

    Contract 1 of #755: silence is never a measurement of zero.
    """
    unavailable = bool(getattr(power, "battery_power_unavailable", False))
    watts = float(getattr(power, "battery_charge_power", 0.0) or 0.0)
    return Draw(watts, not unavailable)


@dataclass
class DemandRecord:
    """One demand's night: the ask, the promise, and the outcome."""

    demand_id: str
    kind: str = ""
    night: str = ""

    # What was wanted and what was promised (seeded at stamp time)
    asked_kwh: float = 0.0
    planned_kwh: float = 0.0
    status: str = ""            # fits | partial | yields

    # What actually happened (integrated from samples)
    actual_kwh: float = 0.0
    in_block_kwh: float = 0.0
    covered_s: float = 0.0
    uncovered_s: float = 0.0
    gap_s: float = 0.0
    samples: int = 0
    measured: bool = True
    first_run: Optional[str] = None
    last_run: Optional[str] = None

    @property
    def trainable(self) -> bool:
        """May a model read this record?

        Requires an actual measurement to exist. Silence is not a measurement
        of zero — a demand with no samples might have been unobservable, not
        idle, and a learner cannot tell the difference.
        """
        return bool(self.measured and self.samples > 0)

    @property
    def delivered_ratio(self) -> Optional[float]:
        """Actual over promised — the honesty of a 'fits'."""
        if self.planned_kwh <= 0:
            return None
        return self.actual_kwh / self.planned_kwh

    @property
    def ask_accuracy(self) -> Optional[float]:
        """Actual over asked — how well the ASK described the real need.

        This is the number pillar 2 learns from: an EV that asks 10 kWh and
        reliably takes 7 is over-asking, and next night's ask can say so.
        """
        if self.asked_kwh <= 0:
            return None
        return self.actual_kwh / self.asked_kwh

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DemandRecord":
        known = {f for f in cls.__dataclass_fields__}      # noqa: F821
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class NightSummary:
    """(#755 pillar 2) The night's solar split — predicted, then measured.

    The plan's horizon is not a calendar day, so judging its predicted share
    against the daily ``self_consumption_rate`` sensor would compare two
    different windows and call the difference an error. This integrates the
    same two quantities over the SAME window the plan covered, under the
    same left-attribution and gap rules as the per-demand energy.
    """

    night: str = ""
    predicted_share: Optional[float] = None
    solar_kwh: float = 0.0
    exported_kwh: float = 0.0
    samples: int = 0

    @property
    def self_consumed_kwh(self) -> float:
        return max(0.0, self.solar_kwh - self.exported_kwh)

    @property
    def actual_share(self) -> Optional[float]:
        """None when no solar was produced — a midwinter night kept 0 of 0,
        which is not a 0 % failure."""
        if self.solar_kwh <= 0:
            return None
        return self.self_consumed_kwh / self.solar_kwh

    def as_dict(self) -> Dict[str, Any]:
        return {
            "night": self.night,
            "predicted_share": self.predicted_share,
            "solar_kwh": round(self.solar_kwh, 3),
            "exported_kwh": round(self.exported_kwh, 3),
            "samples": self.samples,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "NightSummary":
        known = {f for f in cls.__dataclass_fields__}      # noqa: F821
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class _Cursor:
    """Where a demand's integration last stood."""

    ts: Optional[datetime] = None
    power_w: float = 0.0
    in_block: bool = False
    covered: bool = False


@dataclass
class _TotalsCursor:
    """Where the night's solar/export integration last stood."""

    ts: Optional[datetime] = None
    solar_w: float = 0.0
    export_w: float = 0.0


class DemandOutcomeRecorder:
    """Accumulates per-demand outcomes across a night and keeps the history."""

    def __init__(self, max_gap_s: int = DEFAULT_MAX_GAP_S,
                 max_nights: int = DEFAULT_MAX_NIGHTS) -> None:
        self._max_gap_s = int(max_gap_s)
        self._max_nights = int(max_nights)
        self._night: str = ""
        self._open: Dict[str, DemandRecord] = {}
        self._cursors: Dict[str, _Cursor] = {}
        self._history: List[DemandRecord] = []
        self._summary = NightSummary()
        self._totals_cursor = _TotalsCursor()
        self._summaries: List[NightSummary] = []

    @property
    def night(self) -> str:
        """The energy day currently open, "" when none is."""
        return self._night

    # ── night lifecycle ───────────────────────────────────────────────

    def open_night(self, night: str, demands: List[Dict[str, Any]],
                   predicted_share: Optional[float] = None) -> None:
        """Seed the night from the stamp: one record per planned demand.

        Re-opening while a night is still open closes it first, so a re-stamp
        never silently blends two nights into one record.

        ``predicted_share`` (#755 pillar 2) is the plan's own claim about how
        much of the horizon's solar it expects to keep. Stored HERE, at the
        stamp, so the morning compares the claim that was actually made — a
        re-stamped night restates it, and the comparison follows.
        """
        if self._open:
            self.close_night()
        self._night = str(night)
        self._open = {}
        self._cursors = {}
        self._summary = NightSummary(night=self._night,
                                     predicted_share=predicted_share)
        self._totals_cursor = _TotalsCursor()
        for d in demands or []:
            did = str(d.get("id") or "")
            if not did:
                continue
            self._open[did] = DemandRecord(
                demand_id=did,
                kind=str(d.get("kind") or ""),
                night=self._night,
                asked_kwh=float(d.get("needed_kwh") or 0.0),
                planned_kwh=float(d.get("planned_kwh") or 0.0),
                status=str(d.get("status") or ""),
            )

    def close_night(self) -> List[DemandRecord]:
        """Seal the night, append it to history, return its records."""
        closed = list(self._open.values())
        self._history.extend(closed)
        if len(self._history) > self._max_nights:
            self._history = self._history[-self._max_nights:]
        if self._summary.night:
            self._summaries.append(self._summary)
            if len(self._summaries) > self._max_nights:
                self._summaries = self._summaries[-self._max_nights:]
        self._open = {}
        self._cursors = {}
        self._night = ""
        self._summary = NightSummary()
        self._totals_cursor = _TotalsCursor()
        return closed

    # ── observation ───────────────────────────────────────────────────

    def observe(self, now: datetime, demand_id: str, *, power_w: float,
                measured: bool = True, in_block: bool = False,
                covered: Optional[bool] = None) -> None:
        """Record this demand's draw at ``now``.

        The interval since the previous sample is attributed to the state that
        held DURING it — i.e. to the flags of the sample that opened it.
        """
        rec = self._open.get(demand_id)
        if rec is None:
            return
        cur = self._cursors.get(demand_id)
        p = float(power_w or 0.0)

        if cur is not None and cur.ts is not None:
            dt_s = (now - cur.ts).total_seconds()
            if dt_s <= 0:
                pass                                   # out-of-order, ignore
            elif dt_s > self._max_gap_s:
                rec.gap_s += dt_s                      # a hole, not energy
            else:
                kwh = cur.power_w * dt_s / 3_600_000.0
                rec.actual_kwh += kwh
                if cur.in_block:
                    rec.in_block_kwh += kwh
                if cur.covered:
                    rec.covered_s += dt_s
                else:
                    rec.uncovered_s += dt_s
                if kwh > 0:
                    iso = cur.ts.isoformat()
                    if rec.first_run is None:
                        rec.first_run = iso
                    rec.last_run = now.isoformat()

        rec.samples += 1
        # One estimate is enough to disqualify the record. Strict on purpose.
        if not measured:
            rec.measured = False

        self._cursors[demand_id] = _Cursor(
            ts=now, power_w=p, in_block=bool(in_block),
            covered=bool(covered) if covered is not None else bool(in_block),
        )

    def observe_totals(self, now: datetime, *, solar_w: float,
                       export_w: float) -> None:
        """(#755 pillar 2) The night's solar and export, at ``now``.

        Same left-attribution and same gap guard as the per-demand energy —
        an interval belongs to the sample that OPENED it, and a hole is a
        hole. Inventing solar across a restart would surface as a plan that
        missed its share for no reason anybody could find.
        """
        cur = self._totals_cursor
        if cur.ts is not None:
            dt_s = (now - cur.ts).total_seconds()
            if 0 < dt_s <= self._max_gap_s:
                self._summary.solar_kwh += cur.solar_w * dt_s / 3_600_000.0
                self._summary.exported_kwh += \
                    cur.export_w * dt_s / 3_600_000.0
        self._summary.samples += 1
        self._totals_cursor = _TotalsCursor(
            ts=now, solar_w=max(0.0, float(solar_w or 0.0)),
            export_w=max(0.0, float(export_w or 0.0)))

    # ── reads ─────────────────────────────────────────────────────────

    # Deliberately few. ``night_summary`` (the open night's split),
    # ``record_for`` and ``trainable_history`` existed here and were read by
    # nothing but their own tests — #653's exact shape. The reader groups and
    # filters what it needs (``demand_review``, ``demand_learner``); the
    # recorder hands over what it has.

    def night_summaries(self) -> List[NightSummary]:
        """Sealed nights, oldest first."""
        return list(self._summaries)

    def open_records(self) -> List[DemandRecord]:
        return list(self._open.values())

    def history(self, demand_id: Optional[str] = None) -> List[DemandRecord]:
        if demand_id is None:
            return list(self._history)
        return [r for r in self._history if r.demand_id == demand_id]

    # ── persistence (durable store — NOT the daily bucket) ────────────

    def get_state(self) -> Dict[str, Any]:
        return {
            "night": self._night,
            "open": [r.as_dict() for r in self._open.values()],
            "cursors": {
                k: {
                    "ts": c.ts.isoformat() if c.ts else None,
                    "power_w": c.power_w,
                    "in_block": c.in_block,
                    "covered": c.covered,
                }
                for k, c in self._cursors.items()
            },
            "history": [r.as_dict() for r in self._history],
            "summary": self._summary.as_dict(),
            "totals_cursor": {
                "ts": (self._totals_cursor.ts.isoformat()
                       if self._totals_cursor.ts else None),
                "solar_w": self._totals_cursor.solar_w,
                "export_w": self._totals_cursor.export_w,
            },
            "summaries": [s.as_dict() for s in self._summaries],
        }

    def restore_state(self, state: Dict[str, Any]) -> None:
        if not isinstance(state, dict):
            return
        self._night = str(state.get("night") or "")
        self._open = {}
        for d in state.get("open") or []:
            try:
                r = DemandRecord.from_dict(d)
                self._open[r.demand_id] = r
            except Exception:                          # noqa: BLE001
                continue
        self._cursors = {}
        for k, c in (state.get("cursors") or {}).items():
            try:
                ts = c.get("ts")
                self._cursors[k] = _Cursor(
                    ts=datetime.fromisoformat(ts) if ts else None,
                    power_w=float(c.get("power_w") or 0.0),
                    in_block=bool(c.get("in_block")),
                    covered=bool(c.get("covered")),
                )
            except Exception:                          # noqa: BLE001
                continue
        self._history = []
        for d in state.get("history") or []:
            try:
                self._history.append(DemandRecord.from_dict(d))
            except Exception:                          # noqa: BLE001
                continue
        if len(self._history) > self._max_nights:
            self._history = self._history[-self._max_nights:]
        try:
            self._summary = NightSummary.from_dict(state.get("summary") or {})
        except Exception:                              # noqa: BLE001
            self._summary = NightSummary(night=self._night)
        tc = state.get("totals_cursor") or {}
        try:
            _ts = tc.get("ts")
            self._totals_cursor = _TotalsCursor(
                ts=datetime.fromisoformat(_ts) if _ts else None,
                solar_w=float(tc.get("solar_w") or 0.0),
                export_w=float(tc.get("export_w") or 0.0))
        except Exception:                              # noqa: BLE001
            self._totals_cursor = _TotalsCursor()
        self._summaries = []
        for d in state.get("summaries") or []:
            try:
                self._summaries.append(NightSummary.from_dict(d))
            except Exception:                          # noqa: BLE001
                continue
        if len(self._summaries) > self._max_nights:
            self._summaries = self._summaries[-self._max_nights:]
