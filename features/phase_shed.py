"""(#1048 C2) A phase over its limit sheds loads, not only chargers.

The phase guard acts on chargers: it clamps an increase to the measured
headroom and stops a charger outright when a phase is over. A house whose L3
is over because of a pool heat pump has no charger to stop, and the guard
watched the fuse go. This module is the guard's half of the shed path, pure:

* which phases are over their limit this cycle, and by how many amps;
* which loads may answer for a phase — those known to sit on it (or on all
  three) first, those of unknown phase only after them, each in reverse
  priority, the drag list's order;
* how many amps switching one off frees on that phase.

Load management throws the switches (its shed and restore, with their
anti-flicker) and the surplus controller backs off the loads it owns; the
guard's own recovery latch decides when they may come back — the margin it
asks of every phase for its recovery cycles, so a shed load does not flap.
The guard reacts once per coordinator cycle.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Tuple

from ..consts.devices import load_phase

#: The guard's phase keys → the words a load carries.
GUARD_PHASES = {"l1": "L1", "l2": "L2", "l3": "L3"}
#: Nominal phase voltage for turning a load's watts into amps on its line.
DEFAULT_VOLTAGE_V = 230.0
#: Fleet EV draw above which a car counts as charging: then the chargers'
#: own stop is the guard's first answer to an over phase.
EV_DRAWING_W = 100.0
#: Cycles a phase may stay over after the chargers were told to stop before
#: loads answer for it too — one cycle for the stop to land.
CHARGERS_FIRST_CYCLES = 2


def over_phases(snapshot: Mapping[str, Any]) -> Dict[str, float]:
    """``{"L3": 7.0}`` — the phases measured over their limit, by the larger
    excess of the two lanes. A phase the guard could not read is not "over":
    the guard already fails closed on it (the chargers stop), and loads are
    never shed on a guess."""
    out: Dict[str, float] = {}
    if not isinstance(snapshot, Mapping):
        return out
    for lane in ("grid", "inverter"):
        phases = snapshot.get(lane)
        if not isinstance(phases, Mapping):
            continue
        for key, reading in phases.items():
            name = GUARD_PHASES.get(str(key))
            if name is None or not isinstance(reading, Mapping):
                continue
            if not reading.get("data_fresh") or reading.get("reason") != "over_limit":
                continue
            try:
                excess = float(reading["current_a"]) - float(reading["limit_a"])
            except (KeyError, TypeError, ValueError):
                continue
            if excess > 0:
                out[name] = max(out.get(name, 0.0), round(excess, 3))
    return out


def single_phase_supply(snapshot: Mapping[str, Any]) -> bool:
    """A one-phase guard: every load sits on L1, whatever it was given."""
    try:
        return int(float(snapshot.get("phase_count", 3))) == 1
    except (AttributeError, TypeError, ValueError):
        return False


def draws_on(load: Any, phase: str, *, single_phase: bool = False) -> bool:
    """Does a load on ``load`` draw on ``phase``? Unknown is no answer."""
    if single_phase:
        return True
    p = load_phase(load)
    return p == phase or p == "3ph"


def relief_a(load: Any, draw_w: float, phase: str, *,
             single_phase: bool = False,
             voltage_v: float = DEFAULT_VOLTAGE_V) -> float:
    """The amps switching this load off frees on ``phase``: all of a load on
    that line, a third of a three-phase one — and nothing promised for a load
    of unknown phase, which is shed one per cycle for the meter to answer."""
    if draw_w <= 0 or voltage_v <= 0:
        return 0.0
    if single_phase:
        return draw_w / voltage_v
    p = load_phase(load)
    if p == phase:
        return draw_w / voltage_v
    if p == "3ph":
        return draw_w / (3.0 * voltage_v)
    return 0.0


def order_candidates(
    rows: Iterable[Tuple[str, Mapping[str, Any], float]], phase: str, *,
    single_phase: bool = False,
) -> Tuple[List[Tuple[str, Mapping[str, Any], float]],
           List[Tuple[str, Mapping[str, Any], float]]]:
    """``(known, unknown)`` for ``phase``: loads known to draw on it first,
    loads of unknown phase after them, each highest priority number first.
    A load known to sit on ANOTHER line is never a candidate."""
    known: List[Tuple[str, Mapping[str, Any], float]] = []
    unknown: List[Tuple[str, Mapping[str, Any], float]] = []
    for did, info, draw_w in rows:
        p = load_phase(info.get("phase"))
        if draws_on(p, phase, single_phase=single_phase):
            known.append((did, info, draw_w))
        elif p == "unknown":
            unknown.append((did, info, draw_w))
    known.sort(key=lambda c: c[1].get("priority", 5), reverse=True)
    unknown.sort(key=lambda c: c[1].get("priority", 5), reverse=True)
    return known, unknown
