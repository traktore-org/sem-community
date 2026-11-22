"""(#1411) Thin sun plus grid — one rule, for the plan and for the live gate.

A sun hour is THIN when the spare sun is below a charger's minimum power.
That sun leaves through the meter at the export price, and the car's
"At least" is bought from the grid later. Charging at the minimum NOW takes
the spare sun and buys only the rest:

    blended = (sun · export + (min − sun) · import_now) / min

THE INVARIANT. The rule fires only when the blended price beats the
cheapest alternative — the cheapest hour without spare sun the car may
still use before its deadline — by the margin: ``blended <= (1 − margin) ×
cheapest_other`` (10 % to start, 5 % to keep running). Nothing else about
the prices is promised. In particular it is NOT "never when export >=
import": on a dynamic tariff where this hour is the cheapest of the window
(import now 0.10, later 0.25) the blend beats the alternative even with an
export price of 0.30, and buying now is right.

On a ONE-PRICE tariff the invariant reduces to "export below import":

* export = import (net metering): the blend equals the import price —
  never 10 % below it. The rule never fires; waiting costs nothing.
* export below import: it fires from enough sun to save 10 % (flat 0.30,
  export 0.075, a 4.14 kW minimum: from about 550 W).
* a cheaper night: only from enough sun to beat the night price by 10 %.

The export price is the one stored in the tariff settings — the number SEM
uses for every money figure. It has to be right for this mode.

Pure: no clock reads, no I/O, no Home Assistant imports. ``energy_planner``
prices and gates a thin sun slot with these functions, and
``decide.SolarPlusCheapMode`` asks the same ones every cycle — inside a
thin-sun block of the stamped plan only, so the plan on the card and what
the charger does cannot hold two opinions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: A blend this close to the bar is not "below" it: a rounding tie must not
#: start a grid charge (and a re-plan must not flip on it).
PRICE_EPS = 1e-6

#: The worth-it margin: the blended price must be at least this share below
#: the cheapest alternative. A constant, not an option. Without it 200 W of
#: sun on a flat 0.30 with a 0.075 export price "saved" 3 % and bought 95 %
#: grid — Min + Solar by day under another name. The smaller margin keeps a
#: running session through a price or a sun that drifts at the edge.
START_MARGIN = 0.10
RUN_MARGIN = 0.05

#: Spare sun below this is meter noise, not a sun hour (the day ledger's
#: ``DEFAULT_SURPLUS_MARGIN_W`` — the plan has no sun slot below it either).
#: A running session keeps going down to a quarter of it.
MIN_SUN_W = 200.0
RUN_SUN_FACTOR = 0.25

#: The battery "takes the sun" above this charge power: that sun is not
#: leaving the property, so it has no export price to beat. A running
#: session lets go only above the higher number — a pack trickling at the
#: edge must not open and close the contactor.
BATTERY_TAKES_W = 100.0
BATTERY_TAKES_RUN_W = 500.0

#: The pack may feed the car above its own surplus gate
#: (``battery_assist_min_surplus_w``): no START there. A running session
#: keeps going until the sun is this far above the gate, instead of
#: stopping while the sun grows.
PACK_GATE_RUN_EXTRA_W = 300.0

#: "Strong sun later covers the need" stops a START at the need; a running
#: session stops only when the forecast covers this much more.
FORECAST_RUN_EXTRA_KWH = 1.0

#: With a home battery the plan books a thin-sun block only where the pack
#: is full: only then does that sun really leave through the meter.
PACK_FULL_SHARE = 0.98

#: A pack charging above this is not hovering at its veto, it is plainly
#: taking the sun: hard, the minimum block does not bridge it.
BATTERY_TAKES_HARD_W = 2 * BATTERY_TAKES_RUN_W

#: How long the spare sun may sit below the run floor before a running
#: session ends. Three minutes: a kettle or a passing cloud takes the
#: surplus away for a minute or two, and a restart costs far more than
#: bridging it — 200 W of sun again, an open plan block and the stability
#: layer's 60 s start delay. Past it the car is on plain grid power at the
#: full price, and that is a hard stop, inside the minimum block too.
NO_SUN_GRACE_S = 180.0

#: How long a running session is bridged while a price cannot be read (the
#: provider hiccups, an entity is unavailable). Five minutes, not the whole
#: minimum block: a rule that buys on a price comparison must not buy for
#: long on no comparison at all.
PRICE_BRIDGE_S = 300.0

#: The pack discharging this much more than the house draws is feeding the
#: car (W) — less when it is below its buffer, where it may not at all.
PACK_FEEDS_CAR_W = 200.0
PACK_FEEDS_CAR_BELOW_BUFFER_W = 50.0

#: A block of the plan that opens within this many seconds is "near": a
#: running session whose block a re-stamp moved one slot on keeps going.
NEXT_SLOT_S = 3600.0

#: THE HARD LIMITS — the one list. Each ends a thin-sun session AT ONCE,
#: inside the minimum block too; the block bridges soft conditions only (a
#: sun dip, a price between the two margins, a battery hovering at its
#: veto, a block that moved). Word → why it is hard.
HARD_LIMITS = {
    "no_need": "the 'At least' is met: there is nothing left to buy",
    "car_absent": "no car to charge (the mode answers before the rule is asked)",
    "peak_hour": "the tariff turned to a peak level: the mode pauses every "
                 "grid top-up there (answered before the rule is asked)",
    "peak_limit": "the peak limit is shedding: holding the car would breach "
                  "the limit the house is billed on",
    "battery_pays": "the home battery is discharging into the car: the rule "
                    "priced grid power, not the pack's stored energy",
    "battery_takes_sun": "the battery is plainly charging from that sun: it "
                         "is not leaving the property, so nothing is saved",
    "never_pays": "no amount of thin sun gets the blend below the bar any "
                  "more (export at or above import on one price): the price "
                  "moved under the session",
    "sun_gone": "the spare sun stayed below the run floor past the grace: "
                "this is a grid charge at the full price now",
    "price_unknown": "a price could not be read for longer than the bridge: "
                     "the rule buys on a comparison, not on none",
}


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
    """Is charging at ``min_w`` on ``sun_w`` of spare sun plus the grid
    cheaper than the cheapest other hour still open to the car, by the
    margin? ``blended <= (1 − margin) × cheapest_other`` — the invariant in
    the module docstring, and the whole of it.

    Any unknown is a no: a price that could not be read buys nothing
    (#925). Strong sun (``sun_w >= min_w``) is not this rule's business —
    it needs no grid at all. ``running``: the car is already charging on
    this rule — the smaller margin and the lower sun floor apply, so a
    session does not end and restart at the edge.
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
    margin = RUN_MARGIN if running else START_MARGIN
    # ``abs``: a negative reference is beaten by going further below it
    bar = ref - abs(ref) * margin
    return blended_price(sun, need, export, imp) <= bar - PRICE_EPS


def pack_out_of_the_way(soc_kwh: Optional[float],
                        cap_kwh: Optional[float]) -> bool:
    """May the PLAN count a sun hour's surplus as leaving the property?
    Yes without a home battery, and with one only when it is full — a pack
    with room takes that sun first, so there is nothing to beat."""
    try:
        cap = float(cap_kwh or 0.0)
        if cap <= 0.0:
            return True
        return float(soc_kwh or 0.0) >= PACK_FULL_SHARE * cap
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class ThinSun:
    """What the live gate needs to ask the rule, for ONE charger, this cycle.

    Built by the coordinator from the same tariff provider and the stamped
    plan. The default is "not evaluated": every field unknown, and the rule
    answers no — an install without prices, a broken provider and a view
    built by an old call site all behave as before.
    """

    #: What a kWh earns when it leaves the property. None = no export price
    #: is stored (the key is absent or not a number): the rule stays off.
    export_price: Optional[float] = None
    #: What a kWh from the grid costs right now.
    import_now: Optional[float] = None
    #: The cheapest dark hour from now to this charger's deadline.
    cheapest_later: Optional[float] = None
    #: Energy (kWh) the forecast still expects today in hours whose spare
    #: sun reaches this charger's minimum power. None = no forecast.
    strong_sun_kwh: Optional[float] = None
    #: The stamped plan has a "spare sun plus grid" block for this charger
    #: that is open right now. The charger acts only there: where the plan
    #: shows none — a pack with room, a sunnier thin hour picked instead —
    #: it does not act either.
    in_block: bool = False
    #: (run pair of ``in_block``) Such a block is open now or opens within
    #: the next slot. A running session survives a re-stamp that moved its
    #: block one slot on; it starts nothing.
    block_near: bool = False
    #: Seconds since this rule started the running session; None = it
    #: started none. Kept by the coordinator, read for the minimum block.
    session_s: Optional[float] = None
    #: Seconds the spare sun has been below the run floor without a break
    #: in this session; None = it is not below it. The coordinator times it.
    no_sun_s: Optional[float] = None
    #: Seconds one of the prices has been unreadable without a break in
    #: this session; None = all three are read. The coordinator times it.
    no_price_s: Optional[float] = None
    #: The charger's minimum block (``ev_min_block_minutes``), in seconds.
    min_block_s: float = 900.0


NOT_EVALUATED = ThinSun()


def thin_sun_verdict(t: Optional[ThinSun], *, sun_w: float, min_w: float,
                     need_kwh: Optional[float],
                     battery_charge_w: float = 0.0,
                     grid_room_w: Optional[float] = None,
                     running: bool = False,
                     pack_could_pay: bool = False,
                     hard: Optional[str] = None) -> tuple:
    """The live gate's answer → ``(fires, why)``.

    ``why`` is a short machine word for the reason text and the tests:
    ``ok``, ``held``, or the first condition that said no.

    HARD limits (``HARD_LIMITS``, the one list) end a session at once.
    ``hard`` carries the two only ``decide`` can see — the peak limit
    shedding and the pack feeding the car; the rest are asked here, before
    the hold. A missing car and a peak-level hour never get this far: the
    mode answers them first.

    Every other condition is SOFT. A session this rule started is HELD for
    the charger's minimum block over the soft conditions, and after that
    each one is asked with its "keep running" threshold, which is easier
    than the one that starts. So none of them can open and close the
    contactor by hovering at its edge.
    """
    if t is None:
        return (False, "not_evaluated")
    if need_kwh is None or need_kwh <= 0.1:
        return (False, "no_need")
    if hard:
        return (False, hard)
    # only a session THIS rule started runs on the easier thresholds: a car
    # that is charging for another reason gets the strict start
    run = bool(running and t.session_s is not None)
    run_floor_w = MIN_SUN_W * RUN_SUN_FACTOR
    if run:
        if battery_charge_w > BATTERY_TAKES_HARD_W:
            return (False, "battery_takes_sun")
        if (t.export_price is None or t.import_now is None
                or t.cheapest_later is None):
            # a short gap is bridged below; a long one is no comparison
            if t.no_price_s is not None and float(t.no_price_s) >= PRICE_BRIDGE_S:
                return (False, "price_unknown")
        elif not thin_sun_pays(
                sun_w=max(run_floor_w, float(min_w) - 1.0), min_w=min_w,
                export_price=t.export_price, import_price=t.import_now,
                cheapest_other=t.cheapest_later, running=True):
            # the best a thin-sun session can do — sun just under the
            # minimum — no longer clears the bar
            return (False, "never_pays")
        if (sun_w < run_floor_w and t.no_sun_s is not None
                and float(t.no_sun_s) >= NO_SUN_GRACE_S):
            return (False, "sun_gone")
        if float(t.session_s) < float(t.min_block_s):
            return (True, "held")
    if not (t.in_block or (run and t.block_near)):
        return (False, "no_plan_block")
    if battery_charge_w > (BATTERY_TAKES_RUN_W if run else BATTERY_TAKES_W):
        return (False, "battery_takes_sun")
    if pack_could_pay:
        # The home battery is free to discharge into the car right now
        # (above its buffer, enough spare sun to open its own gate): the
        # "grid's share" would come out of the pack, at a price this rule
        # never compared. The battery's rules decide then, not this one.
        return (False, "battery_would_pay")
    if sun_w < (run_floor_w if run else MIN_SUN_W):
        return (False, "no_sun")
    if sun_w >= min_w:
        return (False, "strong_sun")
    if t.export_price is None:
        return (False, "export_unknown")
    if t.strong_sun_kwh is None:
        return (False, "forecast_unknown")
    if t.strong_sun_kwh >= float(need_kwh) + (
            FORECAST_RUN_EXTRA_KWH if run else 0.0):
        return (False, "forecast_covers")
    # ``grid_room_w``: the grid watts the peak limit leaves free right now;
    # None = no limit set (the absence of a ceiling is not a ceiling of 0).
    if (not run and grid_room_w is not None
            and (min_w - sun_w) > float(grid_room_w)):
        return (False, "no_grid_room")
    if not thin_sun_pays(sun_w=sun_w, min_w=min_w,
                         export_price=t.export_price,
                         import_price=t.import_now,
                         cheapest_other=t.cheapest_later, running=run):
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
