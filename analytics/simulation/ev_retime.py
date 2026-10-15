"""(#1083) The car's day under another charge mode.

Pure. The car takes the SAME energy it took that day (the recorded EV kWh)
— only WHEN changes, as the chosen mode would place it. What the mode
cannot place that day is not delivered, and said so: never dropped
silently.

Placement per mode (SEM's canonical rules, docs/EV_CHARGING_LOGIC.md):

* ``recorded`` (default) — as it happened.
* ``solar_only`` — only hours whose solar surplus (solar − house) reaches
  the charger's minimum power; the car takes the surplus, up to its max.
  Never at night.
* ``solar_plus_battery`` — hours whose surplus reaches the battery-assist
  gate; the car takes at least its minimum (the pack tops it up, as SEM's
  assist does), up to its max.
* ``solar_plus_cheap`` — the surplus hours as ``solar_only``, the rest in
  the cheapest hours of the night (before departure, or from 21:00).
* ``min_plus_solar`` — from the hour the car first drew that day: at least
  the minimum, more when the surplus is bigger, until the energy is in.
* ``always_max`` — from the hour the car first drew: the charger's max.
* ``off`` — nothing.

Limits, stated on the tab: the car is taken as plugged in all day on a day
it charged (solar and cheap modes) or from its first hour (the others);
hourly means, so a minimum power is met by the hour's average.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence

HOURS = 24
RECORDED = "recorded"
EV_MODES = ("solar_only", "solar_plus_battery", "solar_plus_cheap",
            "min_plus_solar", "always_max", "off")
#: what a mode what-if offers; ``recorded`` keeps the day as it was
EV_MODE_CHOICES = (RECORDED,) + EV_MODES

VOLTS = 230.0
#: the floor: 6 A on three phases
DEFAULT_MIN_A = 6.0
DEFAULT_MAX_A = 16.0
DEFAULT_PHASES = 3.0
DEFAULT_DEPARTURE_H = 7
NIGHT_FROM_H = 21
#: an hour is solar while it makes at least this (kWh)
SOLAR_KWH = 0.05


@dataclass(frozen=True)
class ChargerLimits:
    min_kw: float
    max_kw: float
    departure_h: int = DEFAULT_DEPARTURE_H
    gate_kw: float = 1.0

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any]) -> "ChargerLimits":
        """The install's first charger; 6 A × 3 phases when unset."""
        ch: Mapping[str, Any] = {}
        for c in cfg.get("ev_chargers") or []:
            if isinstance(c, Mapping):
                ch = c
                break

        def num(key, default):
            for src in (ch, cfg):
                try:
                    v = src.get(key)
                    if v not in (None, ""):
                        return float(v)
                except (TypeError, ValueError):
                    continue
            return float(default)

        phases = num("ev_phases", DEFAULT_PHASES) or DEFAULT_PHASES
        min_a = num("ev_min_current", DEFAULT_MIN_A)
        max_a = num("ev_max_current", DEFAULT_MAX_A)
        dep = int(num("ev_departure_hour", DEFAULT_DEPARTURE_H)) % HOURS
        gate = num("battery_assist_min_surplus", 1000.0) / 1000.0
        min_kw = min_a * phases * VOLTS / 1000.0
        max_kw = max(min_kw, max_a * phases * VOLTS / 1000.0)
        return cls(min_kw=min_kw, max_kw=max_kw, departure_h=dep,
                   gate_kw=max(0.0, gate))


@dataclass
class Retimed:
    ev: List[float]
    #: kWh the car took in other hours than it did
    moved_kwh: float
    #: kWh the mode could not place that day
    not_delivered_kwh: float


def _surplus(solar: Sequence[float], home: Sequence[float], h: int) -> float:
    return max(0.0, float(solar[h]) - float(home[h]))


def retime(mode: Optional[str], ev: Sequence[float], solar: Sequence[float],
           home: Sequence[float], prices: Sequence[float],
           limits: ChargerLimits) -> Retimed:
    """Place the day's car energy as ``mode`` would."""
    rec = [max(0.0, float(x)) for x in ev]
    want = sum(rec)
    if not mode or mode == RECORDED or want <= 0.0:
        return Retimed(ev=list(rec), moved_kwh=0.0, not_delivered_kwh=0.0)
    if mode not in EV_MODES:
        raise ValueError(f"unknown charge mode {mode!r}")
    out = [0.0] * HOURS
    left = want

    def put(h: int, kwh: float) -> None:
        nonlocal left
        take = max(0.0, min(kwh, left, limits.max_kw - out[h]))
        out[h] += take
        left -= take

    first = next((h for h in range(HOURS) if rec[h] > 0.0), 0)
    if mode == "solar_only" or mode == "solar_plus_cheap":
        for h in range(HOURS):
            s = _surplus(solar, home, h)
            if s >= limits.min_kw:
                put(h, s)
    elif mode == "solar_plus_battery":
        for h in range(HOURS):
            s = _surplus(solar, home, h)
            if solar[h] >= SOLAR_KWH and s >= limits.gate_kw:
                put(h, max(s, limits.min_kw))
    elif mode == "min_plus_solar":
        for h in range(first, HOURS):
            put(h, max(limits.min_kw, _surplus(solar, home, h)))
    elif mode == "always_max":
        for h in range(first, HOURS):
            put(h, limits.max_kw)
    if mode == "solar_plus_cheap" and left > 0.0:
        night = [h for h in range(HOURS)
                 if h < limits.departure_h or h >= NIGHT_FROM_H]
        for h in sorted(night, key=lambda k: (float(prices[k]), k)):
            if left <= 0.0:
                break
            put(h, limits.max_kw)
    moved = sum(max(0.0, a - b) for a, b in zip(out, rec, strict=True))
    return Retimed(ev=out, moved_kwh=moved, not_delivered_kwh=max(0.0, left))
