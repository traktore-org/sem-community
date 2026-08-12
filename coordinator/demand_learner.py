"""#755 pillar 3 — per-demand behaviour, learned from the record.

``demand_outcome`` writes what each demand actually did. This layer reads it
back and answers one question per demand: **when this thing asks for X, what
does it really need?**

The design turns entirely on the fact that ``actual_kwh`` is *censored*.

* **Censored from above by the plan.** A night where the packer promised less
  than was asked says nothing about the need. Learning "asked 10, took 6, so
  6 is enough" from a night where 6 was all that was OFFERED is the plan's own
  constraint teaching the plan to ask for less. It converges downward,
  silently, over weeks, and each step looks locally reasonable. This is #744
  (an estimate teaching a model) wearing the plan's own uniform, and it is the
  reason this module exists as a separate, testable door rather than as a mean
  inside a card.
* **Censored from above by the ask.** A night that ran right up to the ask
  proves the need was *at least* that much and possibly more. It may raise a
  suggestion. It may never lower one.

So only nights where the demand was offered everything it asked for **and
stopped on its own** teach the ask. Every other trainable night is a floor:
whatever a demand accepted, it needed at least that much.

What this deliberately does NOT try to detect: a full grant that was cut
short by something outside the record — the car unplugged early, the driver
came home late. By energy alone that night is *identical in shape* to a
satisfied one (asked 10, granted 10, took 6), so a rule to exclude it would
also exclude the exact case the learner exists to see. What the record CAN
see is a hole in itself: ``gap_s > 0`` means a restart or a dead sensor ate
real kWh, and that night is refused. The rest of the interruptions are noise
in one direction only, which is why the statistic is a high percentile
rather than a mean — one short night cannot pull the suggestion down.

Two further rules, both about not being wrong in public:

* **Cold start.** Until ``min_nights`` teaching nights exist, the suggestion
  IS the configured ask.
* **Suggest, never apply.** Nothing in the demand-collection path reads this
  module. The user owns their target; a learner that quietly rewrites it
  changes what the hardware does on the strength of a model nobody agreed
  to, invisibly. Pinned by ``test_755_demand_learner.py``.

Pure: values in, values out. No clock, no I/O, no Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

# Teaching nights required before the learner speaks with confidence. Below
# this the configured ask stands unchanged.
DEFAULT_MIN_NIGHTS = 5

# Where in the distribution of "what it took when nothing stopped it" the
# suggestion sits. Deliberately high: under-asking strands a car short of
# target — a real harm the user feels in the morning — while over-asking
# costs a little scheduling slack. The asymmetry belongs in the statistic,
# not in a fudge factor bolted on afterwards.
DEFAULT_PERCENTILE = 0.8

# Within this fraction of the ask counts as having run the ask dry. Sensor
# noise and the last partial cycle mean an EV that hits target rarely lands
# on the ask to three decimals.
CEILING_EPS = 0.02


def teaches_the_ask(record) -> bool:
    """May this night lower the ask?

    Only if it is trainable (the recorder's estimate guard), was offered
    everything it asked for, was recorded without a hole, and still stopped
    short of the ask. Anything else is censored — a floor at best.
    """
    if record is None or not getattr(record, "trainable", False):
        return False
    asked = float(getattr(record, "asked_kwh", 0.0) or 0.0)
    if asked <= 0:
        return False
    if str(getattr(record, "status", "")) != "fits":
        return False
    planned = float(getattr(record, "planned_kwh", 0.0) or 0.0)
    if planned + 1e-9 < asked:
        return False                       # promised less than asked
    if float(getattr(record, "gap_s", 0.0) or 0.0) > 0:
        return False                       # a hole ate real kWh
    actual = float(getattr(record, "actual_kwh", 0.0) or 0.0)
    return actual < asked * (1.0 - CEILING_EPS)


def hit_the_ask(record) -> bool:
    """Did this night run the ask dry?

    The other informative shape. It cannot lower anything, but a run of them
    is evidence in its own right: the ask is a lid, and the real need may be
    behind it.
    """
    if record is None or not getattr(record, "trainable", False):
        return False
    asked = float(getattr(record, "asked_kwh", 0.0) or 0.0)
    if asked <= 0:
        return False
    actual = float(getattr(record, "actual_kwh", 0.0) or 0.0)
    return actual >= asked * (1.0 - CEILING_EPS)


def _nearest_rank(values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile — no interpolation between two nights that
    actually happened. With five samples an interpolated p80 reports a
    number no night ever produced; the rank picks a real one."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(1, min(len(ordered),
                     int(-(-len(ordered) * max(0.0, min(1.0, p)) // 1))))
    return float(ordered[idx - 1])


@dataclass
class AskSuggestion:
    """What the record says this demand should ask for, and why."""

    demand_id: str
    configured_kwh: float
    suggested_kwh: float
    nights_used: int = 0
    ceiling_nights: int = 0
    censored_floor_kwh: float = 0.0
    confident: bool = False
    # cold_start | learned | floor | at_ceiling
    basis: str = "cold_start"

    @property
    def delta_kwh(self) -> float:
        return self.suggested_kwh - self.configured_kwh

    @property
    def saving_ratio(self) -> Optional[float]:
        """How much of the configured ask the suggestion would give back.
        None when there is no configured ask to compare against."""
        if self.configured_kwh <= 0:
            return None
        return -self.delta_kwh / self.configured_kwh

    def as_dict(self) -> Dict[str, Any]:
        return {
            "demand_id": self.demand_id,
            "configured_kwh": round(self.configured_kwh, 2),
            "suggested_kwh": round(self.suggested_kwh, 2),
            "delta_kwh": round(self.delta_kwh, 2),
            "nights_used": self.nights_used,
            "ceiling_nights": self.ceiling_nights,
            "confident": self.confident,
            "basis": self.basis,
        }


def suggest_ask(demand_id: str, records: List, configured_kwh: float, *,
                min_nights: int = DEFAULT_MIN_NIGHTS,
                percentile: float = DEFAULT_PERCENTILE) -> AskSuggestion:
    """The ask this demand's own history supports.

    ``records`` are ``DemandRecord``s for ONE demand; anything untrainable is
    ignored here as well as at the recorder — this is the door that leads
    into a model, so it is worth two locks.
    """
    trainable = [r for r in (records or [])
                 if getattr(r, "trainable", False)]
    teaching = [float(r.actual_kwh) for r in trainable if teaches_the_ask(r)]
    ceiling = [r for r in trainable if hit_the_ask(r)]

    # The floor is built from the CENSORED nights only — the ones that prove
    # a need without bounding it. Including the teaching nights here would
    # make ``max(learned, floor)`` collapse to the maximum every time and the
    # percentile would be dead code that still looked alive.
    floor = max((float(getattr(r, "actual_kwh", 0.0) or 0.0)
                 for r in trainable if not teaches_the_ask(r)), default=0.0)
    need = max(1, int(min_nights))
    configured = float(configured_kwh or 0.0)

    if len(teaching) >= need:
        learned = _nearest_rank(teaching, percentile)
        suggested = max(learned, floor)
        basis = "learned" if suggested <= learned + 1e-9 else "floor"
    elif not teaching and len(ceiling) >= need:
        # Every night ran the ask dry and none ever stopped on its own. That
        # is not "no information" — it is the ask acting as a lid, and the
        # user is the only one who can lift it.
        suggested = max(configured, floor)
        basis = "at_ceiling"
    else:
        return AskSuggestion(
            demand_id=demand_id, configured_kwh=configured,
            suggested_kwh=configured, nights_used=len(teaching),
            ceiling_nights=len(ceiling), censored_floor_kwh=round(floor, 2),
            confident=False, basis="cold_start")

    return AskSuggestion(
        demand_id=demand_id, configured_kwh=configured,
        suggested_kwh=round(suggested, 2), nights_used=len(teaching),
        ceiling_nights=len(ceiling), censored_floor_kwh=round(floor, 2),
        confident=True, basis=basis)
