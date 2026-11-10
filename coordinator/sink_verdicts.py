"""arc #921 — a sink has a STATE, not a price.

SEM's balance layer reasons about energy. Price already decides WHEN in SEM
(cheap hours, negative-import force charge, the arbitrage floor) through the
LEVEL the tariff provider classifies; it must not start deciding HOW MUCH.
So the arc's one model is a per-cycle verdict per destination a kWh can take:

    OPEN   — energy may go there (the sink's own gates still apply)
    HELD   — it may, but not now: keep the energy where it is
    CLOSED — it may not; for the grid this is ENFORCED by the export guard

Computed ONCE per cycle here, threaded into ``FleetCycleState``, and consumed
by the routers (surplus, decide_battery, pacing, the plan). No consumer
re-derives a verdict from a price. Pure: no hass, no clock of its own.

An UNKNOWN price is OPEN, never CLOSED (#925, class 86): "I could not ask" is
not "the meter is hostile", and acting on a missing price would push energy
around for no reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional, Tuple
from .price_signal import (
    CHEAP_LEVELS as _CHEAP_LEVELS, is_cheap_name, is_expensive_name,
)
from ..tariff.value_layer import DEFAULT_EXPORT_VALUE_THRESHOLD, export_not_worth
from . import reason_codes as RC

OPEN = "open"
HELD = "held"
CLOSED = "closed"

SINKS = ("grid_export", "battery", "house", "ev")

#: Tariff levels under which the pack is KEPT rather than spent on the house.
#: (#994) the ONE vocabulary — see coordinator/price_signal.py. An unknown
#: level is not cheap, so a flat tariff never holds the pack.
_KEEP_LEVELS = tuple(lv.value for lv in _CHEAP_LEVELS)


@dataclass(frozen=True)
class SinkVerdict:
    sink: str
    state: str
    reason: str
    until: Optional[datetime] = None
    #: (#1174) why, as a stable code and its numbers — recorded only, left
    #: out of equality (``reason_codes``)
    reason_code: str = field(default="", compare=False)
    reason_params: Dict[str, Any] = field(default_factory=dict, compare=False)

    def to_dict(self) -> Dict[str, Any]:
        return {"sink": self.sink, "state": self.state, "reason": self.reason,
                "until": self.until.isoformat() if self.until else None}


def _money(v) -> str:
    """(#1174) A per-kWh value as the sentence shows it: up to 3 decimals."""
    return f"{round(float(v), 3):g}"


class _Verdicts(dict):
    """A plain dict with one convenience for readers and tests."""

    def state_of(self, sink: str) -> str:
        return self[sink].state


def _level(p) -> str:
    lv = getattr(p, "level", None)
    return str(getattr(lv, "value", lv) or "").lower()


def next_closed_window(now: datetime, upcoming,
                       closed_at: Optional[Callable[[datetime], bool]] = None,
                       ) -> Optional[Tuple[datetime, datetime]]:
    """The first run of NEGATIVE slots at or after ``now`` as ``(start, end)``.

    (#1090) ``closed_at(slot_start)`` replaces the level test when given: on
    a value tariff the meter closes on the export VALUE, and a Dutch import
    curve with energy tax never reads "negative".

    ``end`` is the closing boundary — the first non-negative slot's start, or
    the last negative slot plus its cadence when the curve ends negative. A run
    already in progress starts at ``now``. ``None`` when there is none, when
    the curve is empty, and when it cannot be read — absence is OPEN.
    """
    pts = [p for p in (upcoming or []) if getattr(p, "timestamp", None) is not None]
    pts.sort(key=lambda p: p.timestamp)
    if not pts:
        return None
    gaps = [b.timestamp - a.timestamp for a, b in zip(pts, pts[1:], strict=False)
            if b.timestamp > a.timestamp]
    slot = min(gaps) if gaps else timedelta(hours=1)
    start = end = None
    for p in pts:
        if p.timestamp + slot <= now:
            continue                                   # already over
        if (closed_at(p.timestamp) if closed_at is not None
                else _level(p) == "negative"):
            if start is None:
                start = max(now, p.timestamp)
            end = p.timestamp + slot
        elif start is not None:
            return start, p.timestamp
    return (start, end) if start is not None else None


#: (#970) Once released, the peak hold stays released until the pack has
#: fallen this far under the release level — a level hovering at the mark
#: would otherwise flip the discharge limit with every point.
PEAK_HOLD_RELEASE_BAND_SOC: float = 10.0


def peak_hold_state(verdict: Any) -> str:
    """(#970) What the peak hold said in this house verdict: ``held``,
    ``released``, ``dear_hour``, ``unread``, ``no_limit`` — or ``""`` when
    the verdict is not the peak hold's."""
    params = getattr(verdict, "reason_params", None)
    return str(params.get("peak_hold", "")) if isinstance(params, dict) else ""


def peak_hold_verdict(*, level: str, peak_limit_set: bool,
                      pack_soc: Optional[float], release_soc: float,
                      sun_refills_pack: bool, released: bool) -> SinkVerdict:
    """(#970) The house verdict while "keep the battery for the peak limit"
    is on. HELD only on what was read: no limit, an unread level, a dear
    hour, or a high pack the sun refills each leave the house OPEN."""
    if not peak_limit_set:
        return SinkVerdict("house", OPEN,
                           "no peak limit set — nothing to hold the import at",
                           reason_params={"peak_hold": "no_limit"})
    if is_expensive_name(level):
        return SinkVerdict("house", OPEN,
                           f"{level} hour — the pack may cover the house",
                           reason_params={"peak_hold": "dear_hour"})
    if pack_soc is None:
        return SinkVerdict("house", OPEN,
                           "battery level not read — not holding on a guess",
                           reason_params={"peak_hold": "unread"})
    mark = float(release_soc) - (PEAK_HOLD_RELEASE_BAND_SOC if released else 0.0)
    if sun_refills_pack and float(pack_soc) >= mark:
        return SinkVerdict(
            "house", OPEN,
            f"battery at {float(pack_soc):.0f}% and the coming sun refills it "
            "— the pack covers the house",
            reason_params={"peak_hold": "released"})
    return SinkVerdict("house", HELD,
                       "kept for the peak limit — the house buys up to it",
                       reason_code=RC.BATTERY_PEAK_HOLD,
                       reason_params={"peak_hold": "held"})


def sink_verdicts(*, now: datetime, tariff_level: Optional[str], upcoming,
                  export_rate: Optional[float], export_rate_known: bool,
                  export_guard_enabled: bool,
                  house_sink_enabled: bool, morning_window_enabled: bool,
                  departure: Optional[datetime], morning_hours: float,
                  forecast_refills_pack: bool,
                  pacing_horizon_end: Optional[datetime],
                  export_threshold: float = DEFAULT_EXPORT_VALUE_THRESHOLD,
                  export_at: Optional[Callable[[datetime], Any]] = None,
                  peak_hold_enabled: bool = False,
                  peak_limit_set: bool = False,
                  pack_soc: Optional[float] = None,
                  peak_hold_release_soc: float = 75.0,
                  sun_refills_pack: bool = False,
                  peak_hold_released: bool = False,
                  ) -> Dict[str, SinkVerdict]:
    """One verdict per sink. Unknown is OPEN, never CLOSED.

    (#1090) ``export_rate`` is the export VALUE; the meter closes when
    ``export_not_worth`` says so against ``export_threshold``. ``export_at``
    (the value per slot) moves the closed window onto the same rule; without
    it the window follows the NEGATIVE level, as before.
    """
    level = str(tariff_level or "").lower()
    out: _Verdicts = _Verdicts()
    readable = export_guard_enabled and export_rate_known and export_rate is not None
    # The grid closes on the EXPORT price's sign — what the meter pays or
    # charges for a kWh leaving the house. On a spot feed-in that is the
    # same curve as the import level; on a static feed-in with a dynamic
    # import it is not, and a negative IMPORT hour must not close the meter
    # for a kWh that still earns 7.5 ct. The level still drives the house.
    # (#1090) One rule for "not worth exporting": value below the threshold.
    # At the default 0.0 that is the old ``< 0.0`` — zero still exports.
    export_negative = readable and bool(export_not_worth(export_rate, export_threshold))

    def _value_closed_at(ts) -> bool:
        try:
            return bool(export_not_worth(export_at(ts), export_threshold))
        except Exception:  # noqa: BLE001 — an unread slot is OPEN
            return False
    win = (next_closed_window(
        now, upcoming, _value_closed_at if export_at is not None else None)
        if readable else None)

    # grid export — CLOSED only on a READ negative level with the guard on
    if not export_guard_enabled:
        out["grid_export"] = SinkVerdict("grid_export", OPEN, "export guard off",
                                         reason_code=RC.EXPORT_GUARD_OFF)
    elif not export_rate_known:
        out["grid_export"] = SinkVerdict(
            "grid_export", OPEN, "export price unknown — not closing on a guess",
            reason_code=RC.EXPORT_PRICE_UNKNOWN)
    elif export_negative:
        out["grid_export"] = SinkVerdict(
            "grid_export", CLOSED,
            ("export price negative — the meter is closed"
             if export_threshold == DEFAULT_EXPORT_VALUE_THRESHOLD else
             f"export value below {export_threshold:g} — the meter is closed"),
            until=win[1] if win else None,
            reason_code=(RC.EXPORT_NEGATIVE_PRICE
                         if export_threshold == DEFAULT_EXPORT_VALUE_THRESHOLD
                         else RC.EXPORT_NOT_WORTH),
            reason_params=({} if export_threshold == DEFAULT_EXPORT_VALUE_THRESHOLD
                           else {"value": _money(export_rate),
                                 "threshold": _money(export_threshold)}))
    else:
        out["grid_export"] = SinkVerdict(
            "grid_export", OPEN, "export price not negative",
            until=win[0] if win else None,
            reason_code=RC.EXPORT_RELEASED)

    # battery — HELD headroom when a CLOSED window starts inside the pacing horizon (#926)
    if win and pacing_horizon_end is not None and win[0] < pacing_horizon_end:
        out["battery"] = SinkVerdict(
            "battery", HELD, "hold headroom — the meter closes before the day ends",
            until=win[0])
    else:
        out["battery"] = SinkVerdict("battery", OPEN, "fill as the day model says")

    # house — spent on the house in EXPENSIVE hours, kept in CHEAP/NEGATIVE ones (#879)
    # (#970) …and, by its own switch, kept for the peak limit: the house buys
    # up to the limit and the pack covers only the rest (the #1003 floor in
    # ``decide_battery`` — this verdict adds a WHEN, never a second HOW MUCH).
    # It needs a limit to hold at, yields to a dear hour (the pack is worth
    # most there) and to an unread level, and lets go once the pack is high
    # and the coming sun refills it — a full pack could not take that sun.
    _peak = (peak_hold_verdict(
        level=level, peak_limit_set=peak_limit_set, pack_soc=pack_soc,
        release_soc=peak_hold_release_soc, sun_refills_pack=sun_refills_pack,
        released=peak_hold_released) if peak_hold_enabled else None)
    if house_sink_enabled and is_cheap_name(level):
        out["house"] = SinkVerdict(
            "house", HELD, f"{level} hour — let the house import, keep the pack")
    elif _peak is not None:
        out["house"] = _peak
    elif not house_sink_enabled:
        out["house"] = SinkVerdict(
            "house", OPEN, "house sink off — inverter self-consumption rule")
    elif level == "flat":
        out["house"] = SinkVerdict(
            "house", OPEN, "flat tariff — no better hour to save it for")
    elif level in ("no_prices", "", "unknown"):
        out["house"] = SinkVerdict(
            "house", OPEN, "no prices to compare — the pack may cover the house")
    else:
        out["house"] = SinkVerdict(
            "house", OPEN, f"{level} hour — the pack may cover the house")

    # ev — a morning window before departure, if the sun refills the pack today (#892)
    if not morning_window_enabled:
        out["ev"] = SinkVerdict("ev", OPEN, "legacy assist rule")
    elif departure is None:
        out["ev"] = SinkVerdict("ev", HELD, "no departure time configured")
    elif not forecast_refills_pack:
        out["ev"] = SinkVerdict("ev", HELD, "forecast will not refill the pack today")
    else:
        opens = departure - timedelta(hours=float(morning_hours or 0.0))
        if now < opens or now >= departure:
            out["ev"] = SinkVerdict("ev", HELD, "outside the morning window", until=opens)
        else:
            out["ev"] = SinkVerdict(
                "ev", OPEN, "morning window — empty the pack into the car", until=departure)
    return out
