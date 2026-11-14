"""(#1081) A heat pump's COP learned from its own heat meter.

Every completed hour gives one sample: heat delivered ÷ electricity used,
filed under that hour's mean outdoor temperature. Samples sit in 2 °C bins;
a bin is TRUSTED once it holds ``TRUST_HOURS`` hours, and only trusted bins
make the learned curve. Each bin's point is the median temperature and the
median COP of its samples, so a few defrost, short or hot-water hours do not
drag it. SEM cannot tell a hot-water hour; a meter that counts hot water
teaches the mixed COP, and the card says which meter it learns from.

Pure: no Home Assistant, no I/O. The coordinator feeds ``observe`` once a
cycle and stores ``state`` (a plain dict) in SEM's energy store. The curve is
only USED when the user picks it for that heat pump (``cop_source`` =
"learned"); until then it is shown, never acted on.
"""
from __future__ import annotations

import math
from statistics import median
from typing import Any, Dict, Optional

STATE_VERSION = 1
BIN_WIDTH_C = 2.0
TRUST_HOURS = 6
#: newest samples kept per bin — bounds the store (≈ 35 bins × 24)
MAX_SAMPLES_PER_BIN = 24
#: an hour that used less electricity than this is standby, not running —
#: and SEM's ledger rounds to 0.01 kWh, so a smaller hour would be ±3 % noise
MIN_ELEC_KWH = 0.3
#: an hour the pump ran less of than this is a short run (starts, defrost)
MIN_RUN_SHARE = 0.25
#: a COP outside this band is a meter glitch, not a heat pump
COP_MIN, COP_MAX = 1.0, 7.0

#: a heat counter this coarse against the hour's heat is noise: an hour must
#: deliver at least this many of the meter's smallest steps
MIN_STEPS_PER_HOUR = 10
#: learned COPs this low (median of every sample) mean the "heat meter"
#: counts electricity — a wrong match, or no heat pump: nothing is learned
ELECTRIC_COP = 1.2
ELECTRIC_LIKE_MIN = 0.85
#: a running hour that used this much and moved no heat = a lagging counter
STALL_ELEC_KWH = 0.05

#: an outdoor reading outside this band is a broken sensor
OUTDOOR_MIN_C, OUTDOOR_MAX_C = -40.0, 50.0

#: what the learner can say about a heat pump
LEARNED, NOT_ENOUGH, NO_METER = "learned", "not_enough", "no_meter"
LOOKS_ELECTRIC = "looks_electric"


def new_state() -> Dict[str, Any]:
    return {"v": STATE_VERSION, "bins": {}, "hour": None, "rejected": {}}


def _pair_ok(p: Any) -> bool:
    return (isinstance(p, (list, tuple)) and len(p) == 2
            and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                    for x in p))


def _valid(state: Any) -> Dict[str, Any]:
    """The stored state, or a fresh one when any part of it is not the
    shape this code wrote — a bad store must never fail every cycle."""
    if not isinstance(state, dict) or state.get("v") != STATE_VERSION:
        return new_state()
    state.setdefault("bins", {})
    state.setdefault("rejected", {})
    state.setdefault("hour", None)
    bins = state["bins"]
    if (not isinstance(bins, dict)
            or not all(isinstance(v, list) and all(_pair_ok(p) for p in v)
                       for v in bins.values())
            or not isinstance(state["rejected"], dict)
            or not (state["hour"] is None or _hour_ok(state["hour"]))
            or not _res_ok(state.get("heat_res", 1.0))):
        return new_state()
    return state


def _res_ok(v: Any) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v) and 0 < v <= 1.0)


_HOUR_NUMS = ("elec0", "elec1", "heat0", "heat1", "sum_temp", "n_temp",
              "n", "n_run")


def _hour_ok(hour: Any) -> bool:
    if not isinstance(hour, dict):
        return False
    for k in _HOUR_NUMS:
        v = hour.get(k)
        if v is not None and (isinstance(v, bool)
                              or not isinstance(v, (int, float))
                              or not math.isfinite(v)):
            return False
    return True


def _resolution(v: float) -> float:
    """The finest step a counter reading shows: 3.0 → 1, 3.6 → 0.1."""
    for res in (1.0, 0.1, 0.01, 0.001):
        if abs(v / res - round(v / res)) < 1e-6:
            return res
    return 0.0001


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def bin_key(outdoor_c: float) -> str:
    """The 2 °C bin a temperature falls in, as its lower edge ("-8", "2")."""
    import math
    lo = math.floor(float(outdoor_c) / BIN_WIDTH_C) * BIN_WIDTH_C
    return f"{lo:g}"


def _reject(state: Dict[str, Any], why: str) -> None:
    state["rejected"][why] = int(state["rejected"].get(why, 0)) + 1


def _close_hour(state: Dict[str, Any], hour: Dict[str, Any]) -> None:
    """Turn a finished hour into a sample, or count why it was not one."""
    if hour.get("bad"):
        _reject(state, "unread")
        return
    e0, e1 = hour.get("elec0"), hour.get("elec1")
    h0, h1 = hour.get("heat0"), hour.get("heat1")
    if None in (e0, e1, h0, h1) or not hour.get("n_temp"):
        _reject(state, "unread")
        return
    de, dh = e1 - e0, h1 - h0
    if de < 0 or dh < 0:
        state.pop("stalled", None)
        state.pop("heat_res", None)   # a new counter: learn its step again
        _reject(state, "reset")
        return
    was_stalled = state.pop("stalled", False)
    if dh == 0 and de >= STALL_ELEC_KWH:
        # the pump used power, the heat counter did not move: it lags, and
        # the next hour would carry this one's heat
        state["stalled"] = True
        _reject(state, "lagging_meter")
        return
    if was_stalled:
        _reject(state, "lagging_meter")
        return
    if de < MIN_ELEC_KWH:
        _reject(state, "standby")
        return
    n = int(hour.get("n", 0) or 0)
    if n and (hour.get("n_run", 0) / n) < MIN_RUN_SHARE:
        _reject(state, "short_run")
        return
    if dh < MIN_STEPS_PER_HOUR * float(state.get("heat_res", 1.0)):
        _reject(state, "coarse_meter")
        return
    cop = dh / de
    if ELECTRIC_LIKE_MIN <= cop < COP_MIN:
        # a little under 1: an electricity meter, not a broken one
        _reject(state, "electric_like")
        return
    if not COP_MIN <= cop <= COP_MAX:
        _reject(state, "implausible")
        return
    t = hour["sum_temp"] / hour["n_temp"]
    samples = state["bins"].setdefault(bin_key(t), [])
    samples.append([round(t, 1), round(cop, 3)])
    if len(samples) > MAX_SAMPLES_PER_BIN:
        del samples[: len(samples) - MAX_SAMPLES_PER_BIN]


def observe(state: Any, *, hour_id: Any, elec_kwh: Any, heat_kwh: Any,
            outdoor_c: Any, running: bool,
            meter: Optional[str] = None) -> Dict[str, Any]:
    """Feed one reading (any cadence). ``hour_id`` names the clock hour; a
    new id closes the previous hour into a sample. The coordinator passes
    whole hours since the epoch (an int — no DST double hour): an id that
    is not the next one means readings were missed (a restart, a pause),
    and the closing reading would carry the gap's energy — that hour is
    dropped.

    ``meter`` names the heat meter: another one starts the learner fresh
    (a new meter, a new pump — its samples are not this one's).

    ``elec_kwh`` / ``heat_kwh`` are the counters' readings (kWh, rising);
    ``running`` says the pump drew power at this reading. An unread value spoils the hour, never guesses."""
    state = _valid(state)
    if meter is not None:
        if state.get("meter") not in (None, meter):
            state = new_state()
        state["meter"] = meter
    e, h, t = _num(elec_kwh), _num(heat_kwh), _num(outdoor_c)
    if t is not None and not OUTDOOR_MIN_C <= t <= OUTDOOR_MAX_C:
        t = None
    if h is not None:
        # the finest step the heat counter has ever shown = its resolution
        state["heat_res"] = min(float(state.get("heat_res", 1.0)),
                                _resolution(h))
    hour = state.get("hour")
    if hour is None or hour.get("id") != hour_id:
        old_id = None if hour is None else hour.get("id")
        if (isinstance(old_id, int) and isinstance(hour_id, int)
                and hour_id != old_id + 1):
            state.pop("stalled", None)
            _reject(state, "gap")
        elif hour is not None:
            # the reading at the turn is the closing value of the old hour
            if e is not None:
                hour["elec1"] = e
            if h is not None:
                hour["heat1"] = h
            _close_hour(state, hour)
        hour = {"id": hour_id, "elec0": e, "heat0": h, "elec1": e, "heat1": h,
                "sum_temp": 0.0, "n_temp": 0, "n": 0, "n_run": 0,
                "bad": e is None or h is None}
        state["hour"] = hour
        if t is not None:
            hour["sum_temp"] += t
            hour["n_temp"] += 1
        hour["n"] += 1
        hour["n_run"] += 1 if running else 0
        return state
    if e is None or h is None:
        hour["bad"] = True
    else:
        if hour.get("elec0") is None or hour.get("heat0") is None:
            hour["bad"] = True
        hour["elec1"], hour["heat1"] = e, h
    if t is not None:
        hour["sum_temp"] += t
        hour["n_temp"] += 1
    hour["n"] += 1
    hour["n_run"] += 1 if running else 0
    return state


def _looks_electric(state: Dict[str, Any], need: int) -> bool:
    cops = [c for v in state["bins"].values() for _, c in v]
    if len(cops) >= need and median(cops) <= ELECTRIC_COP:
        return True
    under = int(state["rejected"].get("electric_like", 0) or 0)
    return under >= need and under > len(cops)


def learned_points(state: Any, *, need: int = TRUST_HOURS) -> list:
    """The learned curve: ``[(°C, COP)]`` from trusted bins, sorted."""
    state = _valid(state)
    if _looks_electric(state, need):
        return []
    pts = []
    for samples in state["bins"].values():
        if len(samples) >= need:
            pts.append((round(median(s[0] for s in samples), 1),
                        round(median(s[1] for s in samples), 2)))
    return sorted(pts)


def summary(state: Any, *, has_meter: bool, need: int = TRUST_HOURS) -> Dict[str, Any]:
    """What the cards show: state, hours, the range and the points."""
    if not has_meter:
        return {"state": NO_METER, "hours": 0, "need": need, "points": []}
    state = _valid(state)
    hours = sum(len(s) for s in state["bins"].values())
    pts = learned_points(state, need=need)
    out: Dict[str, Any] = {
        "state": (LEARNED if pts else
                  LOOKS_ELECTRIC if _looks_electric(state, need) else NOT_ENOUGH),
        "hours": hours, "need": need,
        "points": [[t, c] for t, c in pts],
        "rejected": dict(state.get("rejected") or {}),
    }
    if pts:
        out["tmin"], out["tmax"] = pts[0][0], pts[-1][0]
    return out
