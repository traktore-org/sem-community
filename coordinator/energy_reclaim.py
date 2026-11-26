"""#576 — reclaimable battery-charge power.

The single quantity behind "loads charge before the battery": above the
reserve zone, power that would otherwise charge the home battery is added
to the surplus pool, so the surplus loads (walked by their own priority)
consume it first and the battery is the sink at the bottom. Pure function
so it is fully unit-testable without a coordinator.

There is **no opt-in toggle** — this is simply how device priority relates
to battery charging. The reserve floor (``battery_priority_soc``) protects
the evening: below it, the battery still fills first.
"""
from __future__ import annotations

from typing import Optional


def ev_reclaims_battery_charge(
    *,
    soc: float,
    priority_soc: float,
    ev_priority: int,
    battery_priority: Optional[int],
    battery_commanded: bool,
) -> bool:
    """Whether the EV may reclaim battery-charge power on its surplus path
    (#576 P2.2).

    The EV path stops subtracting ``battery_charge_w`` from its surplus — i.e.
    the EV charges *before* the battery — iff ALL hold:

    * the battery is NOT under an explicit command (force/scheduled/arbitrage
      charge is honored — the battery keeps its power),
    * a battery exists in the priority list (``battery_priority`` is not None),
    * SOC is at/above the reserve floor (``battery_priority_soc``),
    * the EV sits **above** the battery in the one list
      (``ev_priority < battery_priority``).

    This is the same rule the loads use (see the hand-back in
    ``SurplusController.update``), applied on the EV path — the position-based
    reclaim that replaces the old fixed ``auto_start_soc`` (90 %) gate. Below
    the floor, below the battery, or while the battery is commanded → the
    battery keeps its charge (today's behaviour).
    """
    if not pack_yields_charge(soc=soc, priority_soc=priority_soc,
                              battery_priority=battery_priority,
                              battery_commanded=battery_commanded):
        return False
    return ev_priority < battery_priority


def pack_yields_charge(
    *,
    soc: Optional[float],
    priority_soc: float,
    battery_priority: Optional[int],
    battery_commanded: bool,
) -> bool:
    """(#1435) Does the pack give its charge power to a device ranked above
    it? The pack's half of ``ev_reclaims_battery_charge``: not commanded, in
    the priority list, SOC read and at or above the reserve floor. A device
    gets the charge when this holds AND it ranks above the pack."""
    if battery_commanded:
        return False
    if battery_priority is None or soc is None:
        return False
    return soc >= priority_soc


def reclaimable_battery_w(
    *,
    battery_charge_power: float,
    soc: float,
    priority_soc: float,
    battery_commanded: bool,
    grid_import_w: Optional[float] = 0.0,
    absorbed_w: float = 0.0,
) -> float:
    """Watts of SOLAR currently charging the battery that a higher-priority
    load may take instead.

    Returns 0.0 (battery keeps the charge) unless ALL hold:
      - SOC is at/above the reserve zone (``battery_priority_soc``),
      - the battery is NOT under an explicit/scheduled command
        (force-charge / scheduled / arbitrage — those are honored),
      - the battery is actually charging (positive power).

    (#938) Only the solar-funded share of that charge is surplus. The reclaim
    was built on the picture "the sun would charge the battery, so a load may
    have those watts instead" — and read the WHOLE charge power as if it were
    that. An inverter filling its pack from the GRID (a TOU window set in the
    inverter, an external EMS — anything SEM did not command) presents the
    same positive charge power with nothing behind it but the meter. Live: a
    Solar-only pool pump switched on at 01:29 and ran 4.3 h against a night
    grid charge that ``solar_bounded_surplus`` had already pinned to 0 W on
    the export side (alexmc1510, 09.09.2026). Import while
    the pack charges means the grid, not the sun, is filling it — so the
    import comes off the top. Before any load commits, this is exactly the
    solar-funded share (``solar − house − ev``); once a load runs on it the
    pool is unchanged whether the pack yields or not, which is the #899
    commit-then-measure question and stays with the EV redirect.
    ``grid_import_w`` is what the meter shows — or, on a dark cycle, what
    it last showed (``held_grid_import``); ``None`` means the meter has not
    been read once this lifetime, and with no evidence that the sun is
    funding the charge nothing is reclaimed (fail-closed, the #925 rule).
    ``solar_bounded_reclaim`` in the surplus controller is the independent
    second ceiling (``surplus + reclaim ≤ solar``).
    """
    if battery_commanded:
        return 0.0
    if soc < priority_soc:
        return 0.0
    if grid_import_w is None:
        return 0.0
    charge = max(0.0, float(battery_charge_power))
    # (#1102) ``absorbed_w`` — import the loads' export-side pool already
    # took off (``import_absorbed_by_loads_w``); it is not taken twice.
    unpaid = max(0.0, float(grid_import_w) - max(0.0, float(absorbed_w or 0.0)))
    return max(0.0, charge - unpaid)


#: (#1102) How long an import must last before the loads' pool carries it.
#: A charger's power sensor can trail the meter by a minute at a start or a
#: ramp (KEBA, cloud boxes) — that import is the car's, not the house's.
LOADS_IMPORT_SUSTAIN_S: float = 120.0


#: (#1102) How long a car's start keeps the window open: the window itself
#: plus the minute a charger's power sensor can trail the meter.
CAR_START_HOLD_S: float = LOADS_IMPORT_SUSTAIN_S + 60.0


def car_may_be_charging(
    state: dict,
    now_s: float,
    *,
    plugged: bool,
    commanded_amps: float,
    ev_draw_w: float,
    hold_s: float = CAR_START_HOLD_S,
) -> bool:
    """(#1102) May a car's draw be in the meter but not in its power sensor?

    This opens the two-minute window in ``sustained_import``, so it must be
    true BEFORE the charger's power reading catches up — and only around a
    CHANGE. A plugged car that is full, or a 6 A offer a car does not take,
    lasts all afternoon; read as "may charge" it held the window open, and
    a house import that paused once every two minutes was never counted
    (found in review: the reporter's own square wave, boiler never stopped).

    So the window opens for ``hold_s`` after a change EVENT — a car plugged
    in or out, SEM's offer moving up or down, or the car's draw falling
    below ``EV_ACTIVE_CHARGE_FLOOR_W`` — and stays open while the car really
    draws more than that floor (#739's 500 W: a charger's standby, KEBA
    110-140 W, is not a car charging). A stop or a ramp-down lags the same
    way a start does: the charger reads 0 W while the meter still shows the
    car's import (found in review: a 30 s meter stopped the boiler at every
    car stop). Not the reader's ``ev_charging``: #739 holds it False until
    the power reads 500 W, so it lags with the sensor. A plugged car seen at
    start-up counts as a plug-in. ``state`` is the caller's dict, kept here.
    """
    from .sensor_reader import EV_ACTIVE_CHARGE_FLOOR_W
    now = float(now_s)
    amps = float(commanded_amps or 0)
    drawing = float(ev_draw_w or 0.0) > EV_ACTIVE_CHARGE_FLOOR_W
    if (bool(plugged) != state.get("plugged", False)
            or amps != float(state.get("amps", 0.0))
            or (state.get("drawing", False) and not drawing)):
        state["start"] = now
    state["plugged"] = bool(plugged)
    state["amps"] = amps
    state["drawing"] = drawing
    start = state.get("start")
    return drawing or (start is not None and now - start <= hold_s)


def sustained_import(
    state: dict,
    now_s: float,
    *,
    grid_import_w: float,
    grid_import_known: bool,
    car_active: bool,
    hold_s: float = LOADS_IMPORT_SUSTAIN_S,
) -> Optional[float]:
    """(#1102) The import the loads' pool carries this cycle.

    With no car charging it is the MEAN of the last ``hold_s`` seconds: a
    house load that cycles every two minutes still counts at its average,
    and a kettle's 20 s does not stop a 3 kW boiler (found in review: the
    live reading did, and the load then cycled at its minimum on/off
    times). While a car may charge (``car_active``, see
    ``car_may_be_charging``) it is the LOWEST reading of the last ``hold_s``
    seconds: the charger's power sensor can trail the meter by a minute at
    a start, a ramp or a stop, and that import is the car's. The history is
    kept every cycle, so a car that starts now is judged against the
    minutes before it. When there is no reading inside the window
    (start-up, or a dark gap longer than ``hold_s``), a charging car's
    import counts as none until ``hold_s`` of readings have passed.

    A dark meter is ``None`` — no evidence, and unlike the reclaim's
    ``held_grid_import`` this figure STOPS loads, so a held value would act
    on a blink (#934: a blink holds, it does not act). A dark cycle adds no
    reading and keeps the ones before it: if a blink cleared them, every
    blink would give the house two minutes in which its import is not
    counted (class 58). ``state`` is the caller's dict, kept here.
    """
    if not grid_import_known:
        return None
    live = max(0.0, float(grid_import_w or 0.0))
    now = float(now_s)
    samples = state.setdefault("samples", [])
    while samples and now - samples[0][0] > hold_s:
        samples.pop(0)
    if not samples:
        state["since"] = now
    samples.append((now, live))
    if not car_active:
        return sum(w for _, w in samples) / len(samples)
    if now - state["since"] < hold_s:
        return 0.0
    return min(w for _, w in samples)


def sustained_car_draw(
    state: dict,
    now_s: float,
    *,
    ev_draw_w: float,
    car_active: bool,
    hold_s: float = LOADS_IMPORT_SUSTAIN_S,
) -> float:
    """(#1102) The chargers' draw paired with ``sustained_import``.

    While a car may charge, the import is the lowest of two minutes, so the
    car's share must be the HIGHEST of the same two minutes. Paired with the
    live draw, a ramp from 11 kW to 4 kW put the meter's lagging 11 kW
    against a 4 kW car and booked 7 kW to the house (found in review: the
    boiler stopped at every ramp-down). With no car it is the live draw.
    Every cycle adds a reading, so the window holds the minutes before a
    change. ``state`` is the caller's dict, kept here.
    """
    live = max(0.0, float(ev_draw_w or 0.0))
    now = float(now_s)
    samples = state.setdefault("samples", [])
    while samples and now - samples[0][0] > hold_s:
        samples.pop(0)
    samples.append((now, live))
    if not car_active:
        return live
    return max(w for _, w in samples)


def held_grid_import(
    prev_import_w: Optional[float],
    *,
    grid_import_w: float,
    grid_import_known: bool,
) -> Optional[float]:
    """(#938) The import the reclaim may subtract this cycle.

    A readable meter is the answer, and becomes the hold. A dark meter is
    no evidence either way (the #925 rule): the reader's fallback is 0.0,
    which ``reclaimable_battery_w`` would read as "nothing imported" and
    credit the WHOLE charge for that one cycle — a single blink turning a
    grid charge into surplus, and a start the next cycle's LIFO has to
    undo. So a dark cycle rides on the last readable value instead (the
    #934 held-value shape: a blink holds the limit, it does not act).
    ``None`` = no readable meter yet this lifetime → the caller reclaims
    nothing. An install with NO grid sensor is never dark (nothing was
    read), so it keeps its 0.0 and the sun ceiling alone applies.
    """
    if grid_import_known:
        return max(0.0, float(grid_import_w or 0.0))
    return prev_import_w


# ── (#899) Commit-then-measure for the solar_only battery redirect ─────────
#: Grid import (W) the meter may show while a redirect is credited before the
#: cycle counts as "the pack did not yield". Above house-meter noise, below
#: the smallest redirect worth crediting (one 6 A phase ≈ 1.4 kW).
REDIRECT_IMPORT_TOLERANCE_W: float = 300.0
#: Consecutive contradicting cycles before the redirect is vetoed for the
#: rest of the plug-in. Three cycles ≈ 30 s: past any inverter settle time,
#: short enough that the meter, not the car, pays for the mistake.
REDIRECT_VETO_STRIKES: int = 3


def redirect_strikes(prev: int, *, redirect_w: float, grid_import_w: float,
                     charging: bool, grid_import_known: bool = True) -> int:
    """One cycle's verdict on the redirect. A strike is a cycle where a
    redirect was in the budget, the car was charging, and the meter still
    imported more than the tolerance — the watts the pack was supposed to
    give up came from the grid instead. Any cycle that agrees (no redirect,
    not charging, or import within tolerance) resets the count: the inverter
    yielded after all.

    ``grid_import_known`` (#925 audit) — False when the grid sensor was
    unreadable this cycle. THIS IS NOT AGREEMENT. ``grid_import_w`` is then
    the reader's 0.0 fallback, which is below any tolerance, so the
    unguarded version read a dark meter as "the pack yielded after all" and
    RESET the counter. On the maintainer's own hardware the grid read is
    absent ~137 times a day, so a single blip interleaved with genuinely
    failing cycles delays the three-strike veto indefinitely — the safety
    mechanism disabled by exactly the condition it was built for.

    An unreadable meter is no evidence either way: it neither strikes nor
    forgives. HOLD the count and wait for a cycle we can actually see.
    """
    if not grid_import_known:
        return int(prev)
    if redirect_w > 0.0 and charging and grid_import_w > REDIRECT_IMPORT_TOLERANCE_W:
        return int(prev) + 1
    return 0

