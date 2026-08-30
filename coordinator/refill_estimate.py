"""#778 — what tomorrow can actually put back, after tomorrow's own claims.

Guido pinned this before anyone built it: *"'will it refill' is not a scalar
forecast question — the morning solar is also claimed by tomorrow's packed EV
blocks and loads."* A 40 kWh day that owes the house 12 kWh and the car 10 kWh
refills the pack with 18 kWh, not 40, and a budget fed the raw number would
sell energy that was never coming back.

Two quantities come out of this, and the second is the interesting one:

* **refill** — what the pack can expect to regain tomorrow, after the house and
  the day's committed demands take their share, capped by what the pack can
  physically hold.
* **clipped** — surplus beyond that cap. This is the strongest argument the
  budget can ever make: energy that will be thrown away tomorrow *unless room
  is made tonight*. Spending it is not a bet on the forecast, it is a bet
  against waste, and only a ledger that subtracts demands can see it.

Trust: a forecast is scaled by the measured, per-horizon factor from
``forecast_ledger`` when one has been earned. Until then it is scaled by a
deliberately conservative constant and the reason says so — the alternative,
refusing to estimate until a season has passed, would mean the feature never
starts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: Applied when no measured trust exists for the horizon yet. Deliberately
#: pessimistic: an over-promising forecast on an untested install is how a
#: battery ends the night at its floor.
UNTRUSTED_FACTOR: float = 0.7


@dataclass(frozen=True)
class RefillEstimate:
    refill_kwh: Optional[float]
    """What the pack can expect back tomorrow. ``None`` when unknowable."""

    clipped_kwh: float
    """Surplus tomorrow cannot store — provably free to spend tonight."""

    trusted: bool
    """True when a measured per-horizon trust factor was applied."""

    reason: str


def _f(value) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def dawn_headroom_kwh(usable_capacity_kwh, soc_pct,
                      overnight_need_kwh=None) -> Optional[float]:
    """How much tomorrow's sun the pack can actually absorb.

    The refill question is "will tomorrow put back what I spend tonight",
    and the pack does not receive tomorrow's sun at sunset — it receives it
    after the overnight draw. So the room that counts is the room at DAWN.

    Measuring it NOW (``usable * (100 - soc) / 100``, which is what the
    caller did until 30.08.2026) inverts the whole feature at the top of the
    range: a pack sitting full on the eve of a clipping day reports zero
    headroom, so zero refill, so rule 3 spends nothing — while the estimator
    below prints "spending that tonight costs nothing, the pack cannot hold
    it" on the same cycle. Live on .175: SOC 100, 49.3 kWh would be clipped,
    spendable 0.0. The inversion showed as non-monotonicity — SOC 95 spent
    0.75 kWh, SOC 100 spent 0.00.

    An unknown night is NOT extra room: it falls back to the room the pack
    has now, which is the conservative half of the answer. An unknown pack
    or SOC returns None, which reaches ``estimate_refill``'s honest "no idea
    what the pack can hold" branch rather than pretending to a headroom of
    zero — which would silently mean "tomorrow refills nothing" (rule 4: a
    dark input is not permission).
    """
    cap = _f(usable_capacity_kwh)
    soc = _f(soc_pct)
    if cap is None or cap <= 0:
        # Nothing is known about the pack at all — say so, and let
        # ``estimate_refill`` take its honest "no idea what the pack can
        # hold" branch rather than invent a bound.
        return None
    if soc is None:
        # The pack's capacity IS known; only its level is dark. The room is
        # then somewhere in [0, cap], and the upper bound is a fact — so
        # report it rather than nothing. Reporting nothing sent the caller
        # down the unbounded branch, which published "35.5 kWh expected
        # back" onto a 12.5 kWh pack whenever the SOC sensor dropped out
        # (found by running the assembly across a scenario table,
        # 30.08.2026). The pack cannot absorb more than itself.
        #
        # This does not loosen rule 4: an unknown SOC still spends NOTHING —
        # ``spendable_budget`` refuses on the dark input itself, not on the
        # refill. What changes is only the number the surface shows.
        return cap
    need = _f(overnight_need_kwh)
    need = max(0.0, need) if need is not None else 0.0
    energy_now = cap * max(0.0, min(100.0, soc)) / 100.0
    energy_at_dawn = max(0.0, energy_now - need)
    return max(0.0, cap - energy_at_dawn)


def estimate_refill(
    forecast_tomorrow_kwh,
    house_tomorrow_kwh,
    committed_demand_kwh=0.0,
    pack_headroom_kwh=None,
    trust: Optional[float] = None,
) -> RefillEstimate:
    """How much of tomorrow's sun actually reaches the pack.

    ``committed_demand_kwh`` is what tomorrow's plan has already promised to
    the car and deferrable loads — the subtraction a scalar forecast cannot do.
    ``pack_headroom_kwh`` is how much the battery could absorb; surplus beyond
    it is reported as ``clipped``.
    """
    fc = _f(forecast_tomorrow_kwh)
    house = _f(house_tomorrow_kwh)
    if fc is None or house is None:
        missing = "tomorrow's solar forecast" if fc is None else "tomorrow's expected house load"
        return RefillEstimate(None, 0.0, False, f"unknown {missing}")

    committed = max(0.0, _f(committed_demand_kwh) or 0.0)

    t = _f(trust)
    trusted = t is not None and 0.0 <= t <= 1.0
    factor = t if trusted else UNTRUSTED_FACTOR

    surplus = max(0.0, fc * factor - house - committed)

    headroom = _f(pack_headroom_kwh)
    if headroom is None or headroom < 0:
        # No idea what the pack can hold — report the surplus, claim no clipping.
        return RefillEstimate(
            round(surplus, 2), 0.0, trusted,
            (f"{surplus:.1f} kWh expected back "
             f"({'measured' if trusted else 'unproven'} forecast trust "
             f"{factor:.2f}, after {house:.1f} kWh house"
             f"{f' + {committed:.1f} kWh committed' if committed else ''})"),
        )

    refill = min(surplus, headroom)
    clipped = max(0.0, surplus - headroom)

    if clipped > 0:
        reason = (f"{refill:.1f} kWh fits, {clipped:.1f} kWh would be clipped — "
                  "spending that tonight costs nothing, the pack cannot hold it")
    else:
        reason = (f"{refill:.1f} kWh expected back "
                  f"({'measured' if trusted else 'unproven'} forecast trust "
                  f"{factor:.2f}, after {house:.1f} kWh house"
                  f"{f' + {committed:.1f} kWh committed' if committed else ''})")

    return RefillEstimate(round(refill, 2), round(clipped, 2), trusted, reason)
