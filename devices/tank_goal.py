"""(#1369, step 1) One goal object for a hot water tank — in the shadow.

A tank's goal (where it heats to, where it stops, when it may start) is
decided in about nine places. Seven issues came from adding the same rule in
several of them. This module states the whole goal in ONE pure function.

Step 1 is inert: nothing reads the goal to decide. The controller builds it
beside today's code each cycle and COUNTS where the two disagree
(``HotWaterController.compare_tank_goal``). Pure: no Home Assistant, no I/O,
and no price rule (the price view answers that, #1372).

The rules are written from the behaviour the tests pin, not by calling the
controller's methods — a copy that called them could never disagree.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

# (#1369) The shared numbers live HERE, once: the controller imports them, so
# today's rules and the goal cannot drift apart. No Home Assistant import.

#: a new start needs this much room below the top (or the user's stop): no
#: one-minute run for a tenth of a degree
START_MARGIN_K = 1.0
#: once a start was refused, it waits this much more: no flip on noise
START_MARGIN_STICKY_K = 0.2
#: a switched tank holding its Legionella temperature switches off this far
#: above the target; the tank holds the heat through the hold
LEGIONELLA_HOLD_BAND_K = 0.5
#: a reading this far under the target is noise, not a dip: the hold goes on
LEGIONELLA_HOLD_DIP_K = 0.3

#: (#1369) ``compare_tank_goal(engine_stop=RECOMPUTE)``: the engine did not
#: say whether it stopped the tank, so today's stop rule is asked in its pure form
RECOMPUTE = object()


@dataclass(frozen=True)
class TankInputs:
    """Everything the goal reads. Temperatures in °C; None = not known."""

    tank_c: Optional[float]            # the tank's own sensor
    band_c: Optional[float]            # the comfort band's sensor
    keep_c: Optional[float]            # Keep at (None = no heating band)
    extra_c: Optional[float]           # Extra above Keep at (a difference)
    too_cold_c: Optional[float]        # Run now past (the too-cold limit)
    fallback_top_c: float              # the Solar Heating Target
    min_temperature_c: float           # the away dump's cap
    legionella_target_c: float
    user_stop_c: Optional[float] = None   # the user's own stop on this tank
    other_stop_met: bool = False       # a stop on some other sensor holds
    legionella_active: bool = False
    legionella_hold: bool = False      # the run reached its target, holding
    hold_stopped: bool = False         # the hold's last off/on (hysteresis)
    margin_refused: bool = False       # the last start was refused by margin
    vacation: bool = False
    vacation_dump: bool = False        # away: free sun may still fill the tank
    may_buy: bool = False              # carried for step 2; no rule here
    switched: bool = True              # a relay (SEM ends the run), not a setpoint
    sensor_expected: bool = False      # a sensor is set up: silent = not heated blind
    start_gap_c: float = 0.0           # an away too-cold run heats this far above the limit
    away_floor_open: bool = False      # that run is going and still inside the gap
    now: Optional[datetime] = None


@dataclass(frozen=True)
class TankGoal:
    """The tank's whole goal this cycle, in °C."""

    too_cold_below: Optional[float]
    keep_at: Optional[float]
    top: float
    top_source: str          # band | fallback | away | legionella | user_stop
    stop_at: float           # the temperature a run ends at now
    start_below: float       # a start needs the reading under this
    band_state: str          # forced | willing | banked | disengaged
    may_start: bool
    must_stop: bool
    needs_heat_now: bool
    legionella_blocked: bool
    reason: str              # a short stable word, never user text
    reading_c: Optional[float] = None
    reading_source: Optional[str] = None   # band | tank | None
    # (#1369, step 2) the top the BAND's fields set, the user's stop on it —
    # what the cards show as the top, whatever the tank does now (away, a
    # run). None without a heating band whose limit sits below Keep at.
    band_top: Optional[float] = None


def _band_set(i: TankInputs) -> bool:
    return i.keep_c is not None and i.too_cold_c is not None


def _band_usable(i: TankInputs) -> bool:
    """A heating band whose limit sits below Keep at and whose sensor reads."""
    return _band_set(i) and i.too_cold_c < i.keep_c and i.band_c is not None


def _reading(i: TankInputs) -> Tuple[Optional[float], Optional[str]]:
    """ONE reading for start and stop: the band's sensor when the band is
    in use, else the tank's (C1: a start and a stop used to read different ones).
    A Legionella run reads the tank's own thermometer: that is the water."""
    if i.legionella_active and i.tank_c is not None:
        return i.tank_c, "tank"
    if _band_usable(i) and not i.vacation:
        return i.band_c, "band"
    if i.tank_c is not None:
        return i.tank_c, "tank"
    return None, None


def _band_state(i: TankInputs) -> str:
    if i.vacation or not _band_usable(i):
        return "disengaged"
    if i.band_c <= i.too_cold_c:
        return "forced"
    if i.band_c >= i.keep_c + (i.extra_c or 0.0):
        return "banked"
    return "willing"


def _too_cold(i: TankInputs) -> bool:
    return _band_usable(i) and i.band_c <= i.too_cold_c


def _away_dump(i: TankInputs) -> bool:
    return i.vacation and i.vacation_dump


def _away_heats(i: TankInputs) -> bool:
    """(C2) Away with the dump: a too-cold tank still heats back above its
    limit, and a run it started goes on until it is past the limit + gap."""
    if not (_away_dump(i) and _band_usable(i)):
        return False
    if i.band_c <= i.too_cold_c:
        return True
    return i.away_floor_open and i.band_c < i.keep_c + (i.extra_c or 0.0)


def _band_top(i: TankInputs) -> Optional[float]:
    """Keep at + Extra, at most the Legionella target; None unless the band
    is engaged (in use and the house is home)."""
    if not _band_usable(i) or i.vacation:
        return None
    return min(i.keep_c + max(0.0, i.extra_c or 0.0), i.legionella_target_c)


def _fields_band_top(i: TankInputs) -> Optional[float]:
    """The band's FIELDS' top (Keep at + Extra, at most the Legionella
    target, at most the user's stop): needs no reading and ignores away."""
    if not _band_set(i) or i.too_cold_c >= i.keep_c:
        return None
    top = min(i.keep_c + max(0.0, i.extra_c or 0.0), i.legionella_target_c)
    return min(top, i.user_stop_c) if i.user_stop_c is not None else top


def _ceiling(i: TankInputs) -> Tuple[float, str]:
    """The top before the user's own stop."""
    if i.legionella_active:
        return i.legionella_target_c, "legionella"
    if _away_dump(i):
        top = i.min_temperature_c
        if _away_heats(i):
            # (C2, #1369) too cold wins: the away dump heats back above the limit
            top = max(top, i.too_cold_c + i.start_gap_c)
        return top, "away"
    band = _band_top(i)
    if band is not None:
        return band, "band"
    return i.fallback_top_c, "fallback"


def _cap_by_user_stop(i: TankInputs, top: float, source: str) -> Tuple[float, str]:
    if (i.user_stop_c is not None and not i.legionella_active
            and i.user_stop_c < top):
        return i.user_stop_c, "user_stop"
    return top, source


def _hold_stop(i: TankInputs, reading: Optional[float]) -> bool:
    """A switched tank in its Legionella hold goes off a little above target."""
    if not (i.switched and i.legionella_hold):
        return False
    if reading is None:
        return i.hold_stopped
    target = i.legionella_target_c
    return reading >= target + LEGIONELLA_HOLD_BAND_K or (
        i.hold_stopped and reading >= target - LEGIONELLA_HOLD_DIP_K)


def _must_stop(i: TankInputs, reading: Optional[float], state: str,
               top: float) -> bool:
    user_hit = (i.user_stop_c is not None and reading is not None
                and reading >= i.user_stop_c)
    if user_hit or i.other_stop_met:
        return True
    if i.legionella_active:
        return _hold_stop(i, reading)
    if state == "banked":
        return True
    # a setpoint tank ends its own run at the setpoint SEM wrote
    if not i.switched or reading is None:
        return False
    return reading >= top


def _start_lines(i: TankInputs) -> list:
    return [v for v in (_band_top(i), i.user_stop_c) if v is not None]


def _may_start(i: TankInputs, reading: Optional[float], state: str,
               ceiling: float) -> bool:
    if reading is None:
        return not i.sensor_expected
    if i.legionella_active:
        return reading < i.legionella_target_c
    if not (reading < ceiling or _away_heats(i)):
        return False
    lines = _start_lines(i)
    if lines and state != "forced":
        edge = min(lines) - START_MARGIN_K
        if i.margin_refused:
            edge -= START_MARGIN_STICKY_K
        return reading <= edge
    return True


def _needs_heat(i: TankInputs, reading: Optional[float], may_start: bool,
                must_stop: bool) -> bool:
    if i.legionella_active:
        if reading is None:
            return True
        floor = i.legionella_target_c - (LEGIONELLA_HOLD_DIP_K if i.legionella_hold else 0.0)
        return reading < floor
    return may_start and not must_stop and _too_cold(i)


def _reason(i, reading, may_start, must_stop) -> str:
    if i.legionella_active:
        return "legionella_run"
    if reading is None and i.sensor_expected:
        return "no_reading"
    if must_stop:
        return "at_stop"
    if _too_cold(i):
        return "too_cold"
    if not may_start:
        return "near_top"
    return "away" if i.vacation else "heat_ok"


def build_tank_goal(i: TankInputs) -> TankGoal:
    """The tank's goal from its inputs — the one set of rules."""
    reading, source = _reading(i)
    state = _band_state(i)
    ceiling, ceil_src = _ceiling(i)
    top, top_src = _cap_by_user_stop(i, ceiling, ceil_src)
    may_start = _may_start(i, reading, state, ceiling)
    must_stop = _must_stop(i, reading, state, top)
    lines = _start_lines(i)
    below = (min(lines) - START_MARGIN_K) if lines and not i.legionella_active else ceiling
    return TankGoal(
        too_cold_below=i.too_cold_c, keep_at=i.keep_c, top=top,
        top_source=top_src, stop_at=top, start_below=below,
        band_state=state, may_start=may_start, must_stop=must_stop,
        needs_heat_now=_needs_heat(i, reading, may_start, must_stop),
        legionella_blocked=(i.user_stop_c is not None
                            and i.user_stop_c < i.legionella_target_c),
        reason=_reason(i, reading, may_start, must_stop),
        reading_c=reading, reading_source=source,
        band_top=_fields_band_top(i))


#: the fields the shadow compares with today's decision
COMPARED = ("top", "keep_at", "too_cold_below", "band_state", "must_stop",
            "legionella_blocked")


def _same(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return a is not None and b is not None and abs(float(a) - float(b)) < 1e-6
    return a == b


def differences(goal: TankGoal, seen: dict) -> dict:
    """{field: (goal's value, what today's code decided)} for each compared
    field where the two differ. ``seen`` carries today's value per field."""
    out = {}
    for name in COMPARED:
        if name in seen and not _same(getattr(goal, name), seen[name]):
            out[name] = (getattr(goal, name), seen[name])
    return out
