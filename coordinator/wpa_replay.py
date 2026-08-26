"""(#846) A cold watts-per-amp learner replays itself from SEM's own
recorded series.

Guido, 26.08, after the first deploy left PROD's learner empty because the
car had stopped charging minutes earlier: *"We already learned something
from this — can you backfill prod."* The recorder already held the
evidence. Replaying it is what the learner would have learned had it been
running.

Sources — SEM's OWN per-charger sensors, never the box's:

* ``sensor.sem_charger_<cid>_commanded_current`` — sparse, SEM's hand.
  (The KEBA's ``max_current`` reports 63 A — "no limit" — for the first
  seconds of a session while the car already draws 10 kW; replaying that
  would file a 159 W/A refusal under "phase_belief". SEM's series has no
  such sentinel: it is 0 until SEM commands.)
* ``sensor.sem_charger_<cid>_power`` — the same median-of-3 read the live
  feed sees, one row per cycle.

Two of the live gates are answered from the SHAPE of history:

* steady — ``STEADY_AFTER_S`` after a setpoint change before a row can
  teach (the Zoe settles in ~10 s; live requires two cycles), at most one
  sample per ``SAMPLE_EVERY_S`` — the live cadence;
* not tapering — a row must sit within ``PLATEAU_FRACTION`` of its run's
  p90. The recorded ``taper_trend`` cannot stand in: on PROD it reads
  "declining" after every one of SEM's own ramp-downs, which would exclude
  every 8 A window the learner most needs.

The band inside the learner does the rest: a run that is all taper passes
the shape rule (nothing above it to compare with) and is refused there,
counted, and named.

Pure rules up top; the recorder read and the entity resolution are the two
injectable seams at the bottom.
"""
from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional, Sequence, Tuple

_LOGGER = logging.getLogger(__name__)

#: A setpoint must have been in force this long before a row can teach.
STEADY_AFTER_S: int = 30
#: One sample per live cycle — the recorder is denser than the learner.
SAMPLE_EVERY_S: int = 30
#: A row must sit within this fraction of its run's p90 to be representative.
PLATEAU_FRACTION: float = 0.95
#: How far back a cold start looks. Bounded by the recorder's own keep_days
#: at the call site; a week of sessions is more than one window's worth.
DEFAULT_LOOKBACK_DAYS: int = 7

Sample = Tuple[float, int, float]          # (ts, commanded amps, watts)
Series = Sequence[Tuple[float, float]]     # [(ts, value)]


def _p90(values: List[float]) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(0.9 * (len(s) - 1) + 0.5))]


def samples_from_history(setpoints: Series, powers: Series) -> List[Sample]:
    """The teaching moments in two recorded series.

    ``setpoints``: SEM's commanded amps, as state changes (``0`` = idle).
    ``powers``: this charger's draw, one row per cycle. Both ``(ts, value)``
    in seconds, any epoch, chronological.
    """
    sp = sorted((float(t), float(a)) for t, a in setpoints)
    pw = sorted((float(t), float(w)) for t, w in powers)
    if not sp or not pw:
        return []

    # Cut the power rows into runs — one per setpoint in force.
    runs: List[Tuple[float, int, List[Tuple[float, float]]]] = []
    i = 0
    for k, (t_start, amps) in enumerate(sp):
        t_end = sp[k + 1][0] if k + 1 < len(sp) else float("inf")
        rows: List[Tuple[float, float]] = []
        while i < len(pw) and pw[i][0] < t_end:
            if pw[i][0] >= t_start:
                rows.append(pw[i])
            i += 1
        a = int(round(amps))
        if a >= 1 and rows:
            runs.append((t_start, a, rows))

    out: List[Sample] = []
    for t_start, amps, rows in runs:
        settled = [(t, w) for t, w in rows if t >= t_start + STEADY_AFTER_S and w > 0]
        if not settled:
            continue
        plateau = _p90([w for _, w in settled])
        floor = PLATEAU_FRACTION * plateau
        last: Optional[float] = None
        for t, w in settled:
            if w < floor:
                continue
            if last is not None and t - last < SAMPLE_EVERY_S:
                continue
            out.append((t, amps, w))
            last = t
    return out


def feed_learner(learner, charger_id: str, phases: int, voltage: float,
                 samples: Sequence[Sample]) -> Dict[str, int]:
    """Offer every sample, in time order, under one phase count. The
    learner's own band refuses what history cannot explain."""
    nominal = int(phases) * float(voltage)
    accepted = refused = 0
    for _, amps, watts in sorted(samples):
        before = learner.refused(charger_id, phases)
        if learner.record(charger_id, phases=int(phases), commanded_amps=amps,
                          observed_w=watts, nominal_wpa=nominal):
            accepted += 1
        elif learner.refused(charger_id, phases) > before:
            refused += 1
    return {"accepted": accepted, "refused": refused}


# ── seams ──────────────────────────────────────────────────────────────
async def read_series(hass, entity_id: str, days: int) -> List[Tuple[float, float]]:
    """``[(ts, value)]`` of numeric states over the last ``days``, oldest
    first, including the state in force at the window's start."""
    from datetime import timedelta

    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.history import state_changes_during_period
    from homeassistant.util import dt as dt_util

    end = dt_util.utcnow()
    start = end - timedelta(days=int(days))
    history = await get_instance(hass).async_add_executor_job(
        state_changes_during_period, hass, start, end, str(entity_id), True,
    )
    out: List[Tuple[float, float]] = []
    for st in history.get(entity_id, []):
        try:
            v = float(st.state)
        except (TypeError, ValueError):
            continue          # unknown / unavailable rows carry no value
        out.append((st.last_changed.timestamp(), v))
    return out


def resolve_entity(hass, charger_id: str, key: str) -> str:
    """The entity id of SEM's own ``charger_<cid>_<key>`` sensor — by
    unique_id through the registry (renames survive), the literal id as a
    fallback."""
    unique = f"sem_charger_{charger_id}_{key}"
    try:
        from homeassistant.helpers import entity_registry as er

        from ..const import DOMAIN
        found = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, unique)
        if found:
            return found
    except Exception:  # noqa: BLE001 — the literal id is the fallback
        pass
    return f"sensor.{unique}"


async def run_replay(hass, learner, chargers: Sequence[dict], *, days: int,
                     read: Callable = read_series,
                     resolve: Callable = resolve_entity,
                     default_voltage: float = 230.0) -> Dict[str, dict]:
    """Replay every COLD charger. Warm ones are left alone: live samples
    are newer evidence than the recorder's tail. Returns a report per
    charger — what was read, what taught, and why not when nothing did."""
    report: Dict[str, dict] = {}
    for cfg in chargers or []:
        cid = str(cfg.get("id") or "")
        if not cid:
            continue
        row = {"days": int(days), "rows": 0, "samples": 0, "accepted": 0,
               "refused": 0, "reason": None}
        report[cid] = row
        if cfg.get("ev_phase_switching_enabled"):
            # history cannot say which phase count was in force per row;
            # the live path learns per phase there
            row["reason"] = "phase_switching_enabled"
            continue
        phases = int(cfg.get("ev_phases") or 3)
        if not learner.is_cold(cid, phases):
            row["reason"] = "warm"
            continue
        voltage = float(cfg.get("ev_voltage") or default_voltage)
        try:
            setpoints = await read(hass, resolve(hass, cid, "commanded_current"), days)
            powers = await read(hass, resolve(hass, cid, "power"), days)
        except Exception as err:  # noqa: BLE001 — a reason, never a crash
            row["reason"] = f"read_failed: {err}"[:120]
            continue
        row["rows"] = len(powers)
        if not setpoints or not powers:
            row["reason"] = "no_history"
            continue
        samples = samples_from_history(setpoints, powers)
        row["samples"] = len(samples)
        row.update(feed_learner(learner, cid, phases, voltage, samples))
        if not samples:
            row["reason"] = "no_steady_charging_in_history"
    return report
