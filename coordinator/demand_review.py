"""#755 pillar 4 — what the record has to tell you.

Pillars 1–3 write down what each demand actually did, price the sun so the
plan's preference for it is economic rather than declared, and learn what a
demand really needs. This layer is the only one the user ever meets, and its
whole job is restraint.

* **Codes, not prose.** Every verdict is a machine code (``took_less``,
  ``at_ceiling``, …) that the card renders through ``semLocalize`` — the C7
  pattern. A sentence composed here would be English-only and would put
  internal vocabulary on somebody's dashboard.
* **Silence until confident.** Below the learner's threshold the verdict is
  ``learning`` with the count. "Still learning, 3 of 5 nights" is honest; a
  recommendation from two nights is a guess with a number stapled to it.
* **Silence about the trivial.** A saving smaller than ``NOISE_KWH`` (or
  ``NOISE_RATIO`` of the ask) is not reported. A card that nags about 200 Wh
  every morning is a card nobody reads on the morning it matters.
* **Suggest, never apply.** Nothing here writes a setting. Pinned by
  ``test_755_demand_review.py``.

Pure: values in, values out. No clock, no I/O, no Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from .demand_learner import (
    DEFAULT_MIN_NIGHTS, DEFAULT_PERCENTILE, suggest_ask,
)

# Per-demand verdicts.
CODE_LEARNING = "learning"        # not enough clean nights yet
CODE_ON_TARGET = "on_target"      # the ask matches what it takes
CODE_TOOK_LESS = "took_less"      # it reliably needs less than it asks
CODE_AT_CEILING = "at_ceiling"    # it uses the whole ask — it may need more

# The night's solar share, predicted vs measured.
CODE_SC_MET = "sc_met"
CODE_SC_MISSED = "sc_missed"
CODE_SC_BEAT = "sc_beat"

# Below this, a difference is not worth a user's attention.
NOISE_KWH = 0.5
NOISE_RATIO = 0.05

# How far the measured share may sit from the predicted one and still count
# as kept. Forecast error alone moves it by more than a couple of points.
SHARE_TOLERANCE = 0.05

# A night with less sun than this has no share worth reporting — the ratio
# is dominated by rounding and reads as a failure that never happened.
MIN_SOLAR_KWH = 0.5


@dataclass
class DemandVerdict:
    """One demand's answer to "is your ask right?", with its numbers."""

    demand_id: str
    kind: str
    code: str
    asked_kwh: float
    last_kwh: float
    suggested_kwh: Optional[float] = None
    nights: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "demand_id": self.demand_id,
            "kind": self.kind,
            "code": self.code,
            "asked_kwh": round(self.asked_kwh, 2),
            "last_kwh": round(self.last_kwh, 2),
            "suggested_kwh": (None if self.suggested_kwh is None
                              else round(self.suggested_kwh, 2)),
            "nights": self.nights,
        }


def _newest(records: Sequence) -> Any:
    return max(records, key=lambda r: str(getattr(r, "night", "")))


def review_demand(demand_id: str, records: List, *,
                  configured_kwh: Optional[float] = None,
                  kind: Optional[str] = None,
                  min_nights: int = DEFAULT_MIN_NIGHTS,
                  percentile: float = DEFAULT_PERCENTILE,
                  noise_kwh: float = NOISE_KWH,
                  noise_ratio: float = NOISE_RATIO
                  ) -> Optional[DemandVerdict]:
    """This demand's verdict, or ``None`` when there is nothing to say.

    ``configured_kwh`` defaults to the ask on the most recent record. That is
    deliberate: the record already carries the number the night actually ran
    under, and reading the config again here would open a second path to the
    same value that can disagree with it.
    """
    rows = [r for r in (records or []) if r is not None]
    if not rows:
        return None

    latest = _newest(rows)
    asked = float(configured_kwh if configured_kwh is not None
                  else getattr(latest, "asked_kwh", 0.0) or 0.0)
    s = suggest_ask(demand_id, rows, asked,
                    min_nights=min_nights, percentile=percentile)

    verdict = DemandVerdict(
        demand_id=demand_id,
        kind=str(kind if kind is not None else getattr(latest, "kind", "")),
        code=CODE_LEARNING, asked_kwh=asked,
        last_kwh=float(getattr(latest, "actual_kwh", 0.0) or 0.0),
        nights=s.nights_used)

    if s.basis == "at_ceiling":
        verdict.code = CODE_AT_CEILING
        # No honest number exists for "how much more" — the ask was the lid
        # every night, so the need above it was never observed.
        verdict.nights = s.ceiling_nights
        return verdict
    if not s.confident:
        return verdict

    material = max(float(noise_kwh), asked * float(noise_ratio))
    if s.suggested_kwh <= asked - material:
        verdict.code = CODE_TOOK_LESS
        verdict.suggested_kwh = s.suggested_kwh
    elif s.suggested_kwh >= asked + material:
        # The floor climbed above the ask: nights that were never allowed to
        # finish took more than the ask now describes.
        verdict.code = CODE_AT_CEILING
        verdict.suggested_kwh = s.suggested_kwh
    else:
        verdict.code = CODE_ON_TARGET
    return verdict


def review_share(summaries: Sequence) -> Optional[Dict[str, Any]]:
    """The most recent night whose solar share can honestly be judged.

    Skipped when the plan made no claim (nothing to compare) or the sky was
    shut (a 0 kWh denominator reports 0% and reads as the plan's failure).
    """
    for s in sorted((x for x in (summaries or []) if x is not None),
                    key=lambda x: str(getattr(x, "night", "")), reverse=True):
        predicted = getattr(s, "predicted_share", None)
        solar = float(getattr(s, "solar_kwh", 0.0) or 0.0)
        if predicted is None or solar < MIN_SOLAR_KWH:
            continue
        actual = getattr(s, "actual_share", None)
        if actual is None:
            continue
        if actual < float(predicted) - SHARE_TOLERANCE:
            code = CODE_SC_MISSED
        elif actual > float(predicted) + SHARE_TOLERANCE:
            code = CODE_SC_BEAT
        else:
            code = CODE_SC_MET
        return {
            "night": getattr(s, "night", ""),
            "code": code,
            "predicted_share": round(float(predicted), 3),
            "actual_share": round(float(actual), 3),
            "solar_kwh": round(solar, 2),
            "self_consumed_kwh": round(
                float(getattr(s, "self_consumed_kwh", 0.0) or 0.0), 2),
        }
    return None


# (#800 commit 2) The battery's morning sentence.
CODE_BATT_CLIPPED = "batt_clipped"    # full + exporting: more was spendable
CODE_BATT_REFILLED = "batt_refilled"  # promise kept — full again
CODE_BATT_SHORT = "batt_short"        # promised a refill that never came
CODE_BATT_NIGHT = "batt_night"        # plain: what the night drained

# Clipping below this is a rounding of the day, not a lesson.
BATT_CLIP_NOISE_H = 0.5


def review_battery_night(record) -> Optional[Dict[str, Any]]:
    """(#800) One row about the battery's night, or silence.

    Same restraint rules as the demand rows: an untrainable night says
    nothing (its numbers are holes wearing units), and a trivial one —
    sub-noise drain, no clipping, no broken promise — is not worth the
    morning's attention. Codes + numbers only; the card owns the prose
    and the local clock (``full_at_ts`` stays an epoch — formatting it
    here would bake in a timezone this module doesn't have).
    """
    if not isinstance(record, dict) or not record.get("trainable"):
        return None
    drained = float(record.get("drain_kwh", 0.0) or 0.0)
    clipped = float(record.get("clipped_hours", 0.0) or 0.0)
    full_at = record.get("refill_full_at")
    promised = record.get("forecast_kwh") is not None

    out: Dict[str, Any] = {
        "drained": round(drained, 1),
        "clipped_h": round(clipped, 1),
        "full_at_ts": full_at,
    }
    if clipped >= BATT_CLIP_NOISE_H:
        out["code"] = CODE_BATT_CLIPPED
        return out
    if full_at is not None:
        out["code"] = CODE_BATT_REFILLED
        return out
    if promised:
        out["code"] = CODE_BATT_SHORT
        return out
    if drained < NOISE_KWH:
        return None
    out["code"] = CODE_BATT_NIGHT
    return out


def review_night(records: List, summaries: Optional[Sequence] = None,
                 **kwargs) -> Dict[str, Any]:
    """The whole review: one row per demand, plus the night's solar share.

    Takes the recorder's flat history and does the grouping itself, so the
    caller never has to hold a shape this module could have derived.
    """
    by_id: Dict[str, List] = {}
    for r in records or []:
        did = str(getattr(r, "demand_id", "") or "")
        if did:
            by_id.setdefault(did, []).append(r)

    rows = []
    for did in sorted(by_id):
        v = review_demand(did, by_id[did], **kwargs)
        if v is not None:
            rows.append(v.as_dict())

    out: Dict[str, Any] = {"demands": rows}
    share = review_share(summaries or [])
    if share:
        out["self_consumption"] = share
    return out
