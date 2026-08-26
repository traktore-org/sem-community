"""#820 — pace the battery's daytime fill to land full at day's end.

@ArneGollin1987's 21 kWh pack is full by ~11:30 and sits there for hours:
bad for longevity, and midday harvest is capped whenever PV alone saturates
the inverter's AC limit while the pack has nothing left to absorb. His
export price is fixed, so this paces on forecast + headroom only — price
never enters.

The math deliberately reuses the model the user already sees:
``provisional_soc_curve`` (day_ledger) predicts the fill under a given
charge-power cap, so the pace is its INVERSION — the smallest constant cap
that still lands the pack at its target by the last slot. One model,
displayed and actuated, never two opinions of the same day.

Every refusal is a named reason, because "no cap" has four different
meanings a user must be able to tell apart on the card.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PacingDecision:
    cap_w: Optional[float]
    """The charge-power cap to write, or None = leave the hardware alone."""
    reason: str
    """Why — a token-bearing sentence; the card renders a token, not this."""
    full_at: Optional[str] = None
    """ISO time the paced fill is predicted to reach target (diagnostic)."""


def _fill_kwh(ledger, cap_w: float) -> float:
    """kWh the pack absorbs over the ledger under a constant cap — the same
    per-slot arithmetic as provisional_soc_curve's charging term."""
    total = 0.0
    for s in ledger:
        leftover = 0.0
        if s.cap_override_w is not None:
            leftover = max(0.0, s.cap_override_w - s.grid_committed_w)
        total += min(leftover, cap_w) * s.hours / 1000.0
    return total


def _full_slot(ledger, cap_w: float, need_kwh: float):
    filled = 0.0
    for i, s in enumerate(ledger):
        leftover = 0.0
        if s.cap_override_w is not None:
            leftover = max(0.0, s.cap_override_w - s.grid_committed_w)
        filled += min(leftover, cap_w) * s.hours / 1000.0
        if filled >= need_kwh:
            return i
    return None


def paced_charge_cap_w(
    *,
    ledger,
    capacity_kwh: float,
    soc_pct: float,
    target_soc_pct: float = 100.0,
    floor_soc_pct: float = 35.0,
    forecast_trusted: bool = False,
    inverter_ac_limit_w: float = 0.0,
    hw_max_charge_w: float = 10000.0,
    end_margin_slots: int = 1,
) -> PacingDecision:
    """The smallest constant charge cap that still fills the pack in time.

    Guards, in the order a person would apply them:

    1. **Buffer first** — below ``floor_soc_pct`` the pack charges ASAP.
       The reporter's own staging: ~30-40 % as fast as the sun allows is
       the safety net against a cloudy afternoon.
    2. **Trust** — an untrusted forecast paces nothing. Greedy's failure
       mode is cosmetic (full at 11:30); a pace built on a forecast that
       disappoints strands the pack half-full at sunset, which is material.
    3. **Feasibility** — if even uncapped charging cannot reach the target,
       any cap only makes it worse: no cap.
    4. **Clipping** — hours where surplus exceeds the inverter's AC limit
       are sun that cannot be exported anyway; the cap opens to at least
       swallow the predicted clip. Captured energy beats an even pace.
    """
    if capacity_kwh <= 0 or not ledger:
        return PacingDecision(None, "pacing idle — no day model")
    if soc_pct < floor_soc_pct:
        return PacingDecision(
            None, f"filling the safety buffer to {floor_soc_pct:.0f}% "
                  "as fast as the sun allows")
    if not forecast_trusted:
        return PacingDecision(
            None, "forecast trust not earned — pacing on a forecast that "
                  "disappoints strands the pack half-full, so: greedy")

    need_kwh = max(0.0, (target_soc_pct - soc_pct) / 100.0 * capacity_kwh)
    if need_kwh <= 0.05:
        return PacingDecision(None, "target already reached")

    if _fill_kwh(ledger, hw_max_charge_w) < need_kwh:
        return PacingDecision(
            None, "the day cannot fill the pack even uncapped — a cap "
                  "only makes it worse")

    # Binary-search the smallest cap that still lands the target by the
    # end (with the margin) — the inversion of provisional_soc_curve.
    last_ok = len(ledger) - 1 - max(0, end_margin_slots - 1)
    lo, hi = 0.0, hw_max_charge_w
    for _ in range(24):
        mid = (lo + hi) / 2.0
        slot = _full_slot(ledger, mid, need_kwh)
        if slot is not None and slot <= last_ok:
            hi = mid
        else:
            lo = mid
    cap = hi

    # Clipping guard: any slot whose surplus exceeds the AC limit is energy
    # that cannot leave the roof — open the cap far enough to absorb the
    # worst predicted clip on top of the pace.
    reason = "paced to land full at day's end"
    if inverter_ac_limit_w and inverter_ac_limit_w > 0:
        worst_clip = 0.0
        for s in ledger:
            # Clipping is SOLAR against the AC limit — the inverter clips
            # its output, and the battery is the only place the excess DC
            # can go. Slots that carry solar_w use it; older ledger shapes
            # fall back to the surplus budget, which under-asks by the
            # house draw and errs toward pacing (never toward a stale cap).
            solar = getattr(s, "solar_w", None)
            basis = solar if solar is not None else s.cap_override_w
            if basis is not None:
                worst_clip = max(worst_clip, basis - inverter_ac_limit_w)
        if worst_clip > 0:
            cap = min(hw_max_charge_w, max(cap, worst_clip))
            reason = ("paced, opened for predicted clipping — captured sun "
                      "beats an even pace")

    slot = _full_slot(ledger, cap, need_kwh)
    full_at = ledger[slot].end.isoformat() if slot is not None else None
    return PacingDecision(round(cap, 0), reason, full_at)


class ChargePacingWriter:
    """Owns the ONE side effect: the user-named max-charge-power number.

    Rules, each load-bearing:
    * the entity's value is CAPTURED on first engage and RESTORED on
      disengage — a stale cap left on an inverter register outlives SEM's
      next restart and throttles the battery for nobody;
    * writes dedupe at 100 W (the force-discharge writer's threshold);
    * observer mode never writes — the decision is still published, so the
      rig shows what WOULD happen (the house observer seam).
    """

    def __init__(self) -> None:
        self.engaged: bool = False
        self.restore_value: float | None = None
        self.last_written_w: float | None = None

    async def apply(self, hass, entity_id: str, cap_w, *,
                    observer: bool) -> str:
        """Returns a short action token: wrote|held|restored|idle|observer."""
        if not entity_id:
            return "idle"
        if cap_w is None:
            if self.engaged:
                if observer:
                    self.engaged = False
                    self.restore_value = None
                    self.last_written_w = None
                    return "observer"
                value = self.restore_value
                self.engaged = False
                self.restore_value = None
                self.last_written_w = None
                if value is not None:
                    await hass.services.async_call(
                        "number", "set_value",
                        {"entity_id": entity_id, "value": float(value)},
                        blocking=False)
                    return "restored"
            return "idle"
        if observer:
            return "observer"
        if not self.engaged:
            st = hass.states.get(entity_id)
            try:
                self.restore_value = float(st.state) if st else None
            except (TypeError, ValueError):
                self.restore_value = None
            self.engaged = True
        if (self.last_written_w is not None
                and abs(cap_w - self.last_written_w) < 100.0):
            return "held"
        self.last_written_w = float(cap_w)
        await hass.services.async_call(
            "number", "set_value",
            {"entity_id": entity_id, "value": float(cap_w)},
            blocking=False)
        return "wrote"


def today_remaining_slots(*, now, sunrise, sunset, day_kwh, home_w_at,
                          builder, price_at=None, level_cheap_at=None):
    """Today's remaining day, [now, sunset), in the planner's slot shape.

    The PROD campaign (26.08 morning) caught pacing hooked to the tomorrow
    PREVIEW ledger — a night-only artifact. It solved a correct cap on
    tomorrow's books at 23:00 and had nothing to read in the hours it is
    meant to act. This is the daytime source.

    ``day_kwh`` is the FULL day's forecast, not the remaining kWh: the day
    builder distributes the total over the solar curve between sunrise and
    sunset and tiles only [start, end), so the window naturally receives
    the remaining fraction. Passing the remaining kWh as the total would
    hand the window only the curve's fraction of it — under-counting the
    afternoon and pacing too tight.
    """
    if day_kwh is None or day_kwh <= 0:
        return []
    if now < sunrise or now >= sunset:
        return []
    return builder(
        start=now, end=sunset, day_kwh=float(day_kwh),
        sunrise=sunrise, sunset=sunset, home_w_at=home_w_at,
        **({"price_at": price_at} if price_at else {}),
        **({"level_cheap_at": level_cheap_at} if level_cheap_at else {}),
    )
