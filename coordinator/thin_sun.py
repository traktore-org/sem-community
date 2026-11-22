"""(#1411) Thin sun plus grid — one rule, for the plan and for the live gate.

A sun hour is THIN when the spare sun is below a charger's minimum power.
Today that sun leaves through the meter at the export price, and the car's
"At least" is bought from the grid later. Charging at the minimum NOW takes
the spare sun and buys only the rest:

    blended = (sun · export + (min − sun) · import_now) / min

It pays when that blended price is lower than the cheapest import price the
car could still get before its deadline. Three tariffs, one sum:

* export = import (net metering): the blend equals the import price, never
  lower — the rule never fires, waiting costs nothing.
* one price all day, export below import: any spare sun makes the blend
  lower — it fires.
* a cheaper night: it fires only from enough sun to beat the night price.

Pure: no clock reads, no I/O, no Home Assistant imports. ``energy_planner``
prices and gates a thin sun slot with these functions, and
``decide.SolarPlusCheapMode`` asks the same ones every cycle — so the plan
on the card and what the charger does cannot hold two opinions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: A blend this close to the reference is not "lower": a rounding tie must
#: not start a grid charge (and a re-plan must not flip on it).
PRICE_EPS = 1e-6

#: Spare sun below this is meter noise, not a sun hour (the day ledger's
#: ``DEFAULT_SURPLUS_MARGIN_W`` — the plan has no sun slot below it either).
MIN_SUN_W = 200.0

#: (#1411) Anti-flap. A session that is already charging keeps running
#: through a thinner moment: a quarter of the starting sun is enough, and
#: the price test is made as if the sun were a quarter stronger than it is
#: right now. Starting stays strict. Without this a cloud at the threshold
#: opens the contactor, and the sun a minute later closes it again — the
#: churn class the stability layer exists for, which cannot bridge this
#: stop because holding it buys grid power.
#:
#: The relaxation is on the SUN, never on the price itself: where no
#: amount of sun makes the blend cheaper (export = import), a running
#: session gets no pass either.
RUN_SUN_FACTOR = 0.25
RUN_SUN_BOOST = 1.25

#: The battery "takes the sun" above this charge power: that sun is not
#: leaving the property, so it has no export price to beat.
BATTERY_TAKES_W = 100.0


def blended_price(sun_w: float, power_w: float,
                  export_price: float, import_price: float) -> float:
    """What a kWh costs when ``power_w`` runs on ``sun_w`` of spare sun and
    the grid for the rest: the sun's share at the export price (what it
    would have earned), the rest at the import price."""
    if power_w <= 0:
        return float(import_price)
    from_sun = max(0.0, min(float(power_w), float(sun_w)))
    return (from_sun * float(export_price)
            + (float(power_w) - from_sun) * float(import_price)) / float(power_w)


def thin_sun_pays(*, sun_w: Optional[float], min_w: Optional[float],
                  export_price: Optional[float],
                  import_price: Optional[float],
                  cheapest_other: Optional[float],
                  running: bool = False) -> bool:
    """Does charging at ``min_w`` on ``sun_w`` of spare sun plus the grid
    cost less than the cheapest other hour still open to the car?

    Any unknown is a no: a price that could not be read buys nothing
    (#925). Strong sun (``sun_w >= min_w``) is not this rule's business —
    it needs no grid at all. ``running``: the car is already charging on
    this rule — the two thresholds relax a little (``RUN_*``), so a
    session does not end and restart on a thin cloud.
    """
    if (sun_w is None or min_w is None or export_price is None
            or import_price is None or cheapest_other is None):
        return False
    try:
        sun, need = float(sun_w), float(min_w)
        ref = float(cheapest_other)
        export, imp = float(export_price), float(import_price)
    except (TypeError, ValueError):
        return False
    floor_w = MIN_SUN_W * (RUN_SUN_FACTOR if running else 1.0)
    if need <= 0 or sun < floor_w or sun >= need:
        return False
    priced_sun = min(sun * RUN_SUN_BOOST, need) if running else sun
    return blended_price(priced_sun, need, export, imp) < ref - PRICE_EPS


@dataclass(frozen=True)
class ThinSun:
    """What the live gate needs to ask the rule, for ONE charger, this cycle.

    Built by the coordinator from the same tariff provider and the same
    forecast the plan reads. The default is "not evaluated": every field
    unknown, and the rule answers no — an install without prices, a broken
    provider and a view built by an old call site all behave as before.
    """

    #: What a kWh earns when it leaves the property. None = the user never
    #: gave SEM an export price: the rule stays off.
    export_price: Optional[float] = None
    #: What a kWh from the grid costs right now.
    import_now: Optional[float] = None
    #: The cheapest import price from now to this charger's deadline.
    cheapest_later: Optional[float] = None
    #: Energy (kWh) the forecast still expects today in hours whose spare
    #: sun reaches this charger's minimum power. None = no forecast.
    strong_sun_kwh: Optional[float] = None


NOT_EVALUATED = ThinSun()


def thin_sun_verdict(t: Optional[ThinSun], *, sun_w: float, min_w: float,
                     need_kwh: Optional[float],
                     battery_charge_w: float = 0.0,
                     grid_room_w: Optional[float] = None,
                     running: bool = False,
                     pack_could_pay: bool = False) -> tuple:
    """The live gate's answer → ``(fires, why)``.

    ``why`` is a short machine word for the reason text and the tests:
    ``ok`` or the first condition that said no. The order is the order a
    reader would ask in: is there a need, is the sun really spare, would
    strong sun do it for free, is there room on the meter, does it pay.
    """
    if t is None:
        return (False, "not_evaluated")
    if need_kwh is None or need_kwh <= 0.1:
        return (False, "no_need")
    if battery_charge_w > BATTERY_TAKES_W:
        return (False, "battery_takes_sun")
    if pack_could_pay:
        # The home battery is free to discharge into the car right now
        # (above its buffer, enough spare sun to open its own gate): the
        # "grid's share" would come out of the pack, at a price this rule
        # never compared. The battery's rules decide then, not this one.
        return (False, "battery_would_pay")
    if sun_w < MIN_SUN_W * (RUN_SUN_FACTOR if running else 1.0):
        return (False, "no_sun")
    if sun_w >= min_w:
        return (False, "strong_sun")
    if t.export_price is None:
        return (False, "export_unknown")
    if t.strong_sun_kwh is None:
        return (False, "forecast_unknown")
    if t.strong_sun_kwh >= float(need_kwh):
        return (False, "forecast_covers")
    # ``grid_room_w``: the grid watts the peak limit leaves free right now;
    # None = no limit set (the absence of a ceiling is not a ceiling of 0).
    if (not running and grid_room_w is not None
            and (min_w - sun_w) > float(grid_room_w)):
        # a running session is already inside the measured import; the
        # senior peak clamps slow or stop it, not this start check
        return (False, "no_grid_room")
    if not thin_sun_pays(sun_w=sun_w, min_w=min_w,
                         export_price=t.export_price,
                         import_price=t.import_now,
                         cheapest_other=t.cheapest_later, running=running):
        return (False, "not_cheaper")
    return (True, "ok")


@dataclass(frozen=True)
class ThinSunRefs:
    """What the PLAN's own ledger says about the hours still to come, for
    one charger — kept from the stamp so the live gate compares against the
    same hours the plan compared against, not a second reading of the
    tariff and the forecast.

    ``dark``: ``(end, price)`` of every priced hour without spare sun that
    the charger may still use. ``strong``: ``(start, end, kwh)`` of every
    hour whose spare sun reaches the charger's minimum power.
    """

    dark: tuple = ()
    strong: tuple = ()
    #: The stamped plan had at least one sun hour — a forecast existed and
    #: said "spare sun". Without one the plan cannot show a thin sun block,
    #: and the live rule does not act on a forecast it cannot ask.
    forecast_known: bool = False

    def cheapest_after(self, now) -> Optional[float]:
        """The cheapest dark hour that has not ended yet; None = none left."""
        ps = [float(p) for end, p in self.dark if end > now]
        return min(ps) if ps else None

    def strong_kwh_after(self, now) -> float:
        """Strong-sun energy still to come; a running hour counts for the
        part of it that is left."""
        total = 0.0
        for start, end, kwh in self.strong:
            if end <= now:
                continue
            span = (end - start).total_seconds()
            left = (end - max(start, now)).total_seconds()
            if span > 0:
                total += float(kwh) * max(0.0, left) / span
        return total


def refs_from_ledger(ledger, *, deadline, min_w: float,
                     max_w: float) -> ThinSunRefs:
    """Read the two reference lists off the plan's ledger for a demand with
    this deadline and these power bounds — the hours the packer itself
    ranks the thin sun slot against (``energy_planner._cheapest_dark``)."""
    dark, strong = [], []
    any_sun = False
    need = max(1.0, float(min_w))
    for s in ledger or ():
        if deadline is not None and s.end > deadline:
            continue
        cap = getattr(s, "cap_override_w", None)
        if cap is not None:
            any_sun = True
        if cap is None:
            if s.price is not None:
                dark.append((s.end, float(s.price)))
        elif float(cap) >= need:
            hours = max(0.0, (s.end - s.start).total_seconds() / 3600.0)
            strong.append((s.start, s.end,
                           min(float(cap), float(max_w)) * hours / 1000.0))
    return ThinSunRefs(dark=tuple(dark), strong=tuple(strong),
                       forecast_known=any_sun)
