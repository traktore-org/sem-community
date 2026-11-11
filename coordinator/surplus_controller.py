"""Surplus controller for Solar Energy Management.

SEM surplus control algorithm:
1. 10s control loop - evaluates surplus every coordinator update
2. Sequential priority activation - Priority 1 first, cascade down
3. Minimum power threshold per device
4. Regulation offset (default 50W) - always export small buffer to grid
5. Dynamic add/remove - LIFO deactivation on surplus decrease
6. Variable-power devices get proportional control
7. Manual loads reduce available surplus automatically

This replaces the EV-only surplus routing with a generic multi-device
surplus distribution system.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..devices.base import ControllableDevice, DeviceState, DeviceControlMode
from . import reason_codes as RC  # (#1174)
from .plan_verdict import NO_OPINION, PlanVerdict

from ..utils.log_gate import log_on_change
from .device_tariff import device_price_level  # (#812)
from .price_signal import is_cheap_name, is_expensive_name

_LOGGER = logging.getLogger(__name__)

# Defaults
DEFAULT_REGULATION_OFFSET = 50  # Watts - always keep small export
DEFAULT_MIN_SURPLUS_CHANGE = 100  # Watts - suppress adjustments below this
# (#1102) Import the loads' pool ignores — a zero-export inverter's own grid
# setpoint (Victron ESS +50 W) plus meter noise. See solar_bounded_surplus.
IMPORT_DEADBAND_W = 100.0
# (#1335) Solar production at or under this is no sun: night, or an inverter
# in standby. Read from the solar power reading itself, never from the pool.
NO_SUN_W = 50.0


@dataclass(frozen=True)
class BatteryTierContext:
    """(#620/#625) Pure inputs for the device battery tiers, computed from
    config + live readings. Tier-1 assist budget is offered ONLY when the
    battery is above the Buffer SoC AND there is real surplus past the Solar
    Gate (the same gate the EV assist uses, #537) — so the battery tops loads
    up out of surplus it would otherwise export, never below the buffer.
    Reserve floor for Tier-2 is the load reclaim reserve
    (``battery_priority_soc``)."""
    soc: Optional[float]
    buffer_soc: float
    reserve_soc: float
    assist_budget_w: float
    #: (#885/#878) The floor the tier-1 assist actually stops at:
    #: ``max(buffer_soc, dynamic_floor_pct)``. Separate from ``buffer_soc``
    #: so the configured value stays readable as itself — the EV side and
    #: this one now compute it through the SAME helper, so they cannot
    #: disagree about how deep the pack may go.
    effective_floor_soc: float = 0.0
    #: (#1114) The same budget for a load ranked ABOVE the battery: its
    #: Solar Gate counts the pack's charge power it may reclaim, as a
    #: charger above the battery does. ``None`` = no difference.
    assist_budget_above_battery_w: Optional[float] = None


def tier1_battery_reserved_w(devices, *, below_priority, allowance_w,
                             exclude_ids=()) -> float:
    """(#885) Pack watts claimed by Tier-1 loads that OUTRANK a charger.

    Rule, 31.08: *"The order tells who is first and gets power from the
    battery. The next will get powered from the grid if there is nothing
    left."* The one priority axis is
    :meth:`UnifiedDeviceRegistry.priority_for` — loads, the battery and
    every charger read their slot from it. But the cycle SPENDS the pack in
    call order: every charger commits in the per-charger loop, and the load
    pass only runs afterwards. So a prio-9 charger took battery power ahead
    of a prio-1 hot-water load, and dragging that load to the top of the
    list changed nothing.

    This is the missing half: before a charger is offered the pack, set
    aside what higher-ranked Tier-1 loads are going to want from it.

    Deliberately narrow about who counts:

    * **Tier 1 only** (``battery_assist_enabled``). A "finish overnight from
      battery" load (``battery_eligible_overnight``) reserves NOTHING here.

      Two things make that safe, and neither is the one first written down.
      It is NOT that the SOC bands cannot overlap: the Tier-2 clause of
      ``compute_load_intent`` gates only on the opt-in, night and ``soc > reserve``, with no upper bound tying
      it below the buffer. What actually separates them is
      (a) **time** — Tier 2 runs in the overnight pass while the charger's
      Zone 3/4 assist exists only in ``_decide_day``, and ``decide`` dispatches
      night and day exclusively; and (b) **ledger** — a Tier-2 draw never
      decrements ``_tier1_budget_left``, so it is not spending this allowance
      in the first place.

      Recorded precisely because the plausible-sounding reason is the wrong
      one: if someone later gives Tier 2 an upper SOC gate, or starts billing
      it against this budget, the invariant this comment protects moves.
    * **Not opted in, not counted.** The default is off for both flags; a
      load nobody enrolled must never push a car onto the grid.
    * **Strictly higher rank.** Equal or lower priority yields to the
      charger, which is the whole point of the ordering.
    * **Already running — reserve what the PACK is actually funding.** The
      first cut skipped active devices entirely, reasoning that their draw
      is already inside ``home_consumption_power``. That is true of the
      SOLAR ledger and false of the battery one, which is the ledger this
      function exists to ration: ``battery_assist_potential_w`` is a pure
      SOC number and does not shrink because a load is drawing from the
      pack. Skipping them flip-flopped — the load starts, stops reserving,
      the charger's ceiling springs back to the full allowance, the load's
      own budget goes to zero and it is commanded off, whereupon it
      reserves again. So an active device reserves ``_tier1_batt_w``: the
      watts the walk measured the pack funding for it last cycle. A
      solar-funded load records 0 and correctly reserves nothing; a
      battery-funded one keeps exactly its claim. Measured, not
      re-derived — the same rule ``ChargerDecision.assist_w`` follows.

    The claim itself is an ESTIMATE — the device's learned ``rated_power``
    where it has one, else the threshold it needs to switch on at all. A
    load that then draws less simply leaves the remainder in the pool on
    the next cycle. Self-correcting, and far closer to the user's stated
    intent than "whoever the cycle happens to call first wins".

    Args:
        devices: The registered surplus devices (any iterable).
        below_priority: This charger's slot in the one list. Loads must
            rank strictly above it (a LOWER number) to reserve.
        allowance_w: The pack's assist cap — the reservation can never
            exceed the whole allowance.

    Returns:
        Watts to withhold from this charger, ``0.0`` if nothing outranks it.
    """
    return _reserved_for_seniors(
        devices, below_priority=below_priority, cap_w=allowance_w,
        axis="battery", exclude_ids=exclude_ids,
    )


def surplus_reserved_w(devices, *, below_priority, available_w,
                       exclude_ids=()) -> float:
    """(#885) SOLAR watts claimed by loads that OUTRANK a charger.

    The battery axis was only half the problem. ``solar_committed_w`` cascades
    from charger to charger, but nothing carried a LOAD's claim across the
    charger/load boundary — the load pass simply runs later in the cycle
    (``_surplus_controller.update``) than the per-charger loop, so a prio-9
    charger spent the sun before a prio-1 hot water tank was ever consulted,
    and the tank then ran on grid. The drag list decided nothing.

    Same fix, same seam: set aside what higher-ranked loads will take before a
    charger is offered the surplus.

    **The ``is_active`` rule is the OPPOSITE of the battery axis, and for a
    real reason.** A running device's draw is already inside
    ``home_consumption_power``, and the charger's surplus is
    ``solar - home - committed`` — so an active load has ALREADY reduced what
    every charger sees. Reserving for it again would bill the same watts
    twice. The battery ceiling has no such term: it is a pure SOC number, so
    there an active load must keep reserving. One walk, two axes, opposite
    rules — stated here because the asymmetry looks like a bug until you know
    which ledger each one is protecting.
    """
    return _reserved_for_seniors(
        devices, below_priority=below_priority, cap_w=available_w,
        axis="solar", exclude_ids=exclude_ids,
    )


def _reserved_for_seniors(devices, *, below_priority, cap_w, axis,
                          exclude_ids=()) -> float:
    """The shared priority walk behind both reservations.

    ONE implementation on purpose: two copies of "who outranks this charger"
    would drift, and drifting duplicates of a single computed value are the
    class this branch already had to remove once (#282).

    ``exclude_ids`` — the EV chargers. They MUST NOT be reserved for here:
    a charger's claim already cascades through ``solar_committed_w`` /
    ``assist_committed_w``, so counting it again as if it were a load bills
    the same watts twice and can consume the entire allowance.

    ``get_devices_sorted()`` is supposed to filter chargers out via
    ``managed_externally``, and both registration sites do set it — but that
    invariant is enforced in other files, so this walk no longer depends on
    it. Passing the ids costs nothing and cannot silently regress.

    (Provenance, because the comment first written here was wrong: this was
    added while chasing a ``budget=0W`` on .175 that I attributed to a
    charger being reserved against its sibling. It was not — that budget is
    ``self_consumption_surplus_w`` correctly subtracting battery charge
    because the pack outranks the charger in the one list (#576 P2.2). The
    exclusion is still right, on its own merits and not on that evidence.)
    """
    excluded = frozenset(exclude_ids or ())
    try:
        rank = int(below_priority)
    except (TypeError, ValueError):
        return 0.0
    cap = max(0.0, float(cap_w or 0.0))
    if cap <= 0.0:
        return 0.0

    reserved = 0.0
    for device in devices or ():
        if getattr(device, "device_id", None) in excluded:
            continue
        try:
            if int(getattr(device, "priority", 99)) >= rank:
                continue
        except (TypeError, ValueError):
            continue
        active = bool(getattr(device, "is_active", False))

        if axis == "battery":
            if not getattr(device, "battery_assist_enabled", False):
                continue
            if active:
                # Running: reserve the MEASURED pack draw, not a rated guess.
                # 0.0 means the walk funded it from solar — it needs nothing
                # from the battery and must not hold any back.
                claim = float(getattr(device, "_tier1_batt_w", 0.0) or 0.0)
            else:
                claim = _rated_claim(device)
        else:
            # Solar. An active device is already inside ``home_w`` and has
            # therefore already shrunk every charger's surplus — reserving
            # again would double-count it.
            if active:
                continue
            # Only a device the allocator would actually switch on competes:
            # ``peak_only`` never proactively starts, and one that cannot
            # activate (cap reached, anti-cycle, unmet dependency) is not
            # about to take anything.
            mode = getattr(device, "control_mode", None)
            if getattr(mode, "value", mode) != "surplus":
                continue
            if not _would_start(device):
                continue
            claim = _rated_claim(device)

        reserved += max(0.0, claim)
        if reserved >= cap:
            return cap
    return min(cap, reserved)


def _phase_held(device) -> bool:
    """(#1048) Held for a phase over its limit: the hold names the phase."""
    return isinstance(getattr(device, "_phase_hold", None), str)


def _phase_shed(device) -> bool:
    """(#1048) Taken by the phase guard: back it off."""
    return getattr(device, "_phase_shed", False) is True


def _would_start(device) -> bool:
    """Cheap, READ-ONLY "is this device even a candidate to switch on".

    Deliberately NOT ``device.can_activate()``. That method looks like a
    predicate and is not: its sustained-surplus branch **starts the dwell
    clock** as a side effect (``self._surplus_since = datetime.now()``, see
    ``devices/base.py``). This walk runs once per charger, before the load
    pass, so calling it here would start that clock when a CHARGER asked
    about the device rather than when real surplus appeared — letting loads
    activate ahead of their own debounce, several times per cycle.

    So: only the two conditions that are genuinely read-only and genuinely
    mean "not today". Everything else (dependencies, anti-cycle, dwell) is
    left to the load pass, which is the only place allowed to evaluate them.
    Erring toward reserving is the safe direction here — it protects the
    senior device, which is the whole point of the walk.
    """
    if getattr(device, "daily_max_runtime_reached", False):
        return False
    # (#1048) held for a phase over its limit
    if _phase_held(device):
        return False
    until = getattr(device, "_external_off_until", None)
    if until is not None:
        try:
            from datetime import datetime as _dt
            if _dt.now() < until:
                return False
        except (TypeError, ValueError):
            pass
    return True


def _rated_claim(device) -> float:
    """What a not-yet-running device is expected to draw: its learned rating,
    else the threshold it needs to switch on at all."""
    claim = float(getattr(device, "rated_power", 0.0) or 0.0)
    if claim <= 0.0:
        claim = float(getattr(device, "min_power_threshold", 0.0) or 0.0)
    return claim


def build_battery_tier_context(
    config, battery_soc, true_surplus_w,
    assist_committed_w: float = 0.0,
    dynamic_floor_pct=None,
    reclaim_w: float = 0.0,
) -> BatteryTierContext:
    """(#625, extracted from the coordinator's update cycle) Pure computation
    of the battery-tier context handed to :meth:`SurplusController.update`.

    (#885) Two arguments that make the pack ONE resource instead of two.

    ``assist_committed_w`` — what the EV chargers have already been offered
    from the battery this cycle. Before it, this function returned the FULL
    ``battery_assist_max_power`` regardless, so on a 5000 W pack the chargers
    could be offered 5000 W and the loads another 5000 W in the same cycle.
    Rule, 31.08: *"The order tells who is first and gets power from the
    battery. The next will get powered from the grid if there is nothing
    left."* Netting the budget is that sentence.

    ``dynamic_floor_pct`` — the level tonight's measured need says must
    remain at dawn (#878). The EV side has honoured it since #878; this path
    still gated on ``buffer_soc`` alone, so the loads drained straight
    through a floor the chargers were respecting. A floor kept by one
    consumer and ignored by the other is not a floor. ``None`` falls back to
    the buffer — never to no floor at all.

    (#1114) ``reclaim_w`` — the pack's charge power a load above the
    battery may take (#576). A charger above the battery reads its Solar
    Gate with that power in (``decide.self_consumption_surplus_w``); the
    loads read it without, so a "Solar + battery" load above the battery
    got no help while the pack charged. One gate: a load above the battery
    gets the budget with the reclaim counted, a load below it does not.
    """
    from ..consts.core import (
        DEFAULT_BATTERY_ASSIST_MAX_POWER as _DEF_ASSIST,
        DEFAULT_BATTERY_BUFFER_SOC as _DEF_BUFFER,
        DEFAULT_BATTERY_ASSIST_MIN_SURPLUS as _DEF_GATE,
    )
    buffer_soc = float(config.get("battery_buffer_soc", _DEF_BUFFER) or _DEF_BUFFER)
    reserve_soc = float(config.get("battery_priority_soc", 30) or 30)
    solar_gate = float(config.get("battery_assist_min_surplus", _DEF_GATE) or _DEF_GATE)
    # (#885/#878) The SAME effective floor the EV side uses — one function,
    # so the two consumers cannot disagree about how deep the pack may go.
    from .flow_calculator import _effective_assist_floor
    effective_floor = _effective_assist_floor(buffer_soc, dynamic_floor_pct)
    cap = float(config.get("battery_assist_max_power", _DEF_ASSIST) or _DEF_ASSIST)
    # (#885) net of what the chargers already took: one pack, one allowance,
    # consumed in device order. Never negative — an over-commitment upstream
    # must leave zero here, not a negative budget that reads as a credit.
    remaining = max(0.0, cap - max(0.0, float(assist_committed_w or 0.0)))
    above_floor = battery_soc is not None and battery_soc > effective_floor
    assist_budget = remaining if (above_floor and true_surplus_w >= solar_gate) else 0.0
    above_battery = (
        remaining
        if (above_floor and true_surplus_w + max(0.0, float(reclaim_w or 0.0))
            >= solar_gate)
        else 0.0
    )
    return BatteryTierContext(
        soc=battery_soc, buffer_soc=buffer_soc,
        reserve_soc=reserve_soc, assist_budget_w=assist_budget,
        effective_floor_soc=effective_floor,
        assist_budget_above_battery_w=above_battery,
    )


def effective_peak_state(load_manager_state, vpp_shed_loads: bool):
    """(#625, extracted) The peak posture handed to the surplus controller:
    the load-manager's state, escalated to EMERGENCY while a VPP export
    event wants discretionary loads shed (#580 → #508 W2 peak_shed_all)."""
    if vpp_shed_loads:
        from ..const import LoadManagementState
        return LoadManagementState.EMERGENCY
    return load_manager_state


def solar_bounded_surplus(
    grid_export_w: float,
    active_draw_w: float,
    solar_w: "Optional[float]" = None,
    *,
    grid_import_w: "Optional[float]" = 0.0,
    ev_draw_w: float = 0.0,
    battery_discharge_w: "Optional[float]" = 0.0,
) -> float:
    """The feedback-free SOLAR surplus, physically bounded by production (#620).

    ``grid_export + active_draw`` reconstructs "the surplus that would exist if
    the controller's own loads were off" — the stable quantity to allocate from
    (without the add-back the signal chases its own tail as loads switch on).

    (#1102) The add-back is only that if the grid side is SIGNED: export is
    the clamped half (``max(0, grid)``), so an import read as 0 W and the loads'
    own draw came back whole. @lostcontrol's 3 kW boiler (no battery) ran on
    with 2 kW imported — the pool said 3 kW, not 1 kW, and after its own debit
    the walk sat at −50 W, inside the −100 W LIFO band, while the sun stayed
    above 3 kW. So the import comes off, with two exceptions:

    * the share the chargers' draw explains (``ev_draw_w``, fleet). A charger
      is decided before the loads and already leaves a running load above it
      its sun (#885); what it draws past that — a Min floor, Now, a cheap-hour
      plan — is the charger's own grid, and must not stop that load.
    * the first ``IMPORT_DEADBAND_W``: a zero-export inverter holds a small
      import on purpose (Victron ESS: +50 W by default), and the LIFO band
      leaves only 50 W past the export offset.

    The import comes off here first; the reclaim (``reclaimable_battery_w``,
    #938) takes off only what this side could not (``import_absorbed_by_loads_w``).
    So a load BELOW the battery pays the whole import — a pack charging from
    the grid does not yield to it — and the two addends together are the whole
    balance, ``draw + export + charge − import``, whether a load runs or not.
    The coordinator hands in a SUSTAINED import (``sustained_import``: the
    mean of the last two minutes, or while a car may charge the lowest
    reading of them, ``None`` on a dark meter) and, as ``ev_draw_w``, the
    car's highest draw of the same two minutes (``sustained_car_draw``): a
    charger's power sensor can trail the meter by a minute at a start, a
    ramp or a stop, and that import is the car's. ``grid_import_w=None`` takes nothing
    off: the running loads hold, and nothing new can start on a dark meter.

    (#1112) The home battery is the other source that is not the sun. In a
    battery home the pack covers a load the sun no longer funds, the meter
    reads 0 W, and a Solar-only load ran on the pack. So the pack's
    discharge (``battery_discharge_w``, sustained like the import) comes
    off the same way, and the chargers' draw explains it as it explains
    the import. A "Solar + battery" load gets its pack share back through
    the Tier-1 headroom, which now sees the shortfall it pays for.

    The result is then clamped to ``[0, solar]``: **you cannot have more SOLAR
    surplus than the sun is producing.** This one physical invariant is the whole
    guard — between sunset and sunrise ``solar_w`` is ~0, so the surplus is
    pinned to 0 no matter what the add-back, a noisy grid sensor, or a battery→
    grid discharge tries to fabricate (the phantom overnight "surplus" @onkelfu
    hit when a load ran off the battery at night). ``solar_w=None`` (sensor
    unavailable) skips the cap and falls back to the raw add-back.
    """
    deficit = loads_import_deficit_w(
        grid_import_w, ev_draw_w=ev_draw_w,
        battery_discharge_w=battery_discharge_w)
    surplus = float(grid_export_w) - deficit + float(active_draw_w)
    if solar_w is not None:
        surplus = min(surplus, float(solar_w))
    return max(0.0, surplus)


def loads_import_deficit_w(
    grid_import_w: "Optional[float]", *, ev_draw_w: float = 0.0,
    battery_discharge_w: "Optional[float]" = 0.0,
) -> float:
    """(#1102) The import the loads' pool carries: the meter's import less
    what the chargers' draw explains and less ``IMPORT_DEADBAND_W``.
    ``None`` (no live reading) is no evidence — nothing.

    (#1112) Plus the pack's discharge: power the sun did not make. A dark
    battery reading (``None``) adds nothing."""
    if grid_import_w is None:
        return 0.0
    not_sun = float(grid_import_w) + max(0.0, float(battery_discharge_w or 0.0))
    return max(0.0, not_sun
               - max(0.0, float(ev_draw_w or 0.0)) - IMPORT_DEADBAND_W)


def import_absorbed_by_loads_w(
    *,
    grid_export_w: float,
    active_draw_w: float,
    grid_import_w: "Optional[float]",
    ev_draw_w: float = 0.0,
) -> float:
    """(#1102) How much of the import the loads' pool has already taken off
    — at most down to 0, so at most their own credited draw. The reclaim
    (#938) takes off only the rest. Without this a load above a charging
    pack paid the same import twice once it ran (pool AND reclaim) but once
    at its start, and cycled on a steady import (a single-phase hybrid on a
    summed meter, a Victron setpoint above 100 W)."""
    deficit = loads_import_deficit_w(grid_import_w, ev_draw_w=ev_draw_w)
    return min(deficit, max(0.0, float(grid_export_w) + float(active_draw_w)))


def reclaim_handed_back(remaining_w: float, reclaim_w: float) -> float:
    """(#576, #1102) The walk's pool after it crosses the battery's slot.

    The battery takes back what is left of the reclaim, never more than the
    loads above it left: ``remaining − min(reclaim, max(0, remaining))``.
    The old form, ``max(0, remaining − reclaim)``, gives the same answer
    while ``remaining ≥ 0`` — and wipes a deficit the loads above the
    battery made, so the stop pass never saw it (class 137).
    """
    remaining = float(remaining_w)
    return remaining - min(max(0.0, float(reclaim_w or 0.0)), max(0.0, remaining))


def solar_bounded_reclaim(
    reclaim_w: float,
    *,
    surplus_w: float,
    solar_w: "Optional[float]" = None,
) -> float:
    """(#938) The #620 invariant on the WHOLE load pool, not on one addend.

    ``update()`` allocates from ``surplus + reclaim``: the feedback-free
    export surplus (already ``≤ solar`` via ``solar_bounded_surplus``) PLUS
    the battery-charge power a load above the battery may reclaim (#576).
    The bound sat on the first addend only; the reclaim joined the pool
    below it. So a battery charging from the grid at night — an inverter TOU
    window, nothing SEM commanded — put kilowatts of "surplus" in front of a
    Solar-only pump with the sun at 0 W, and the pump ran until the charge
    ended (alexmc1510, 09.09.2026: on 01:29, on again 01:45 after a manual
    off, off 06:03, "4.3/4 h on solar today").

    You cannot reclaim more sun than there is: ``surplus_w + result ≤
    solar_w``. ``solar_w=None`` (no reading) reclaims NOTHING — deliberately
    unlike ``solar_bounded_surplus``, which lets a raw export figure through
    on a missing reading because export IS physical evidence of the sun; a
    charging battery is not. In production the reader never yields None (a
    dark solar sensor reads 0.0 and pins the pool that way), so this is the
    contract for callers, not a live branch. ``reclaimable_battery_w``'s
    grid-import term is the independent second ceiling.
    """
    reclaim = max(0.0, float(reclaim_w or 0.0))
    if solar_w is None:
        return 0.0
    return max(0.0, min(reclaim, float(solar_w) - float(surplus_w or 0.0)))


def sun_can_still_finish(
    deficit_s: float,
    *,
    daylight_remaining_s: "Optional[float]",
    is_night: bool,
) -> bool:
    """(#953) Is there still enough daylight left today to close this deficit?

    "Finish overnight from: **Grid**" is a FINISH source — the picker's own
    word. Its battery twin has been window-gated since #633 ("must not fire
    in daytime", caught live at 09:10 in full sun); the grid half of the
    same picker had no window at all, only the tariff level. So the first
    cheap slot after the meter day rolls at sunrise bought the whole daily
    target from the meter before the sun had produced a watt, and the day's
    solar went to export (alexmc1510, Huawei, 13.09.2026: Solar-only pool
    pump, 4 h/day, ON at 07:52:39 — sunrise, to the second — and still
    running at 08:24 on 78 W of sun with the pack discharging 857 W).

    The gate is the honest reading of "finish": while today's remaining
    daylight is at least as long as the outstanding deficit, the sun can
    still deliver it, so the grid waits. Deliberately about the free
    window's LENGTH, not about cloud — a dark day is exactly what the
    overnight top-up exists for, and #559's contract is that free comes
    first ("solar_only devices accept missing the target on a dark day").

    Monotone, so it cannot flap: while the load runs, the deficit and the
    remaining daylight shrink at the same one second per second, so their
    difference is constant; while it is off only the daylight shrinks. The
    gate opens once per day and never closes again.

    Returns ``False`` — the top-up may proceed — in every case where we
    cannot claim the sun still has time:

    * ``is_night`` — the overnight window the picker promises. Read from
      ``TimeManager.is_night_mode()``, which has its own clock fallback, so
      the promised behaviour never depends on a sunset reading.
    * no ``daylight_remaining_s`` (no sun data) — unknown is not a claim.
    * no deficit — nothing to finish.
    """
    if is_night:
        return False
    if daylight_remaining_s is None:
        return False
    deficit = float(deficit_s or 0.0)
    if deficit <= 0.0:
        return False
    return float(daylight_remaining_s) >= deficit


def grid_top_up_defers_to_sun(
    device: "ControllableDevice",
    *,
    daylight_remaining_s: "Optional[float]",
    is_night: bool,
    comfort_block_open: bool = False,
) -> bool:
    """(#953) Does THIS device's cheap-hours grid top-up wait for the sun?

    :func:`sun_can_still_finish` on the device's own runtime deficit, with
    two exemptions where the COMFORT band is speaking. ``ComfortBandMixin``
    makes a breached band read as a runtime deficit (``forced``) — a cold
    room is about NOW. And the #638-C5 joint plan creates banking runs in
    a ``willing`` band's comfort block — that block belongs to the plan
    that placed it. Neither is the daily runtime floor. Mirrors
    ``ComfortBandMixin.daily_targets_met``, which for the same reason
    refuses to let a met floor stand the paid sources down while the band
    is forced.

    (#1102) ``willing`` alone is NOT the banking run. A tank sits in its
    willing band most of the day, so exempting the state exempted every
    band device: the daily minimum was bought from the grid in the first
    cheap hour after sunrise (noon on a midday low tariff, 1.7 kW of sun,
    four hours of daylight left), then this same wait ended it once the
    band was full. The banking exemption needs ``comfort_block_open`` —
    the plan's comfort block, ``PlanVerdict.comfort_in_block``.
    """
    state = getattr(device, "comfort_state", "")
    if state == "forced":
        return False
    if comfort_block_open and state == "willing":
        return False
    return sun_can_still_finish(
        float(getattr(device, "remaining_daily_runtime_sec", 0.0) or 0.0),
        daylight_remaining_s=daylight_remaining_s,
        is_night=is_night,
    )


def grid_top_up_waits_until(
    device: "ControllableDevice",
    *,
    sunrise: "Optional[datetime]",
    sunset: datetime,
) -> "Optional[datetime]":
    """(#1330) Until when does this device's grid top-up wait for the sun?

    The planner's copy of :func:`grid_top_up_defers_to_sun`, asked of a
    later hour. A day hour ``t`` waits while ``sunset - max(t, sunrise)``
    still covers the deficit, so every start up to ``sunset - deficit``
    waits. ``None``: nothing waits (no deficit, a forced band, or a day
    shorter than the deficit). ``sunset`` is the same sunset + 10 min the
    live wait reads. A start AT the returned time waits one more cycle; the
    plan counts that hour as usable. Not for a comfort block: that run does
    not wait.
    """
    if getattr(device, "comfort_state", "") == "forced":
        return None
    deficit_s = float(getattr(device, "remaining_daily_runtime_sec", 0.0) or 0.0)
    if deficit_s <= 0.0:
        return None
    cutoff = sunset - timedelta(seconds=deficit_s)
    if sunrise is not None and sunrise > cutoff:
        return None
    return cutoff


def price_damped_pool(distributable: float, price_level: str) -> float:
    """(#953) A price signal may DAMP the solar pool; it may never inflate it.

    This used to add a *virtual* +3 kW (cheap) / +10 kW (negative) to
    ``distributable`` "to encourage consumption". That number is not a
    measurement of anything: it entered the pool after the coordinator had
    bounded the real surplus by the sun (#620) and the reclaim by the sun
    and the meter (#938), and it was handed to the ordinary SOLAR activation
    pass. The consequences were all of a piece — a load in mode "Solar only"
    ("SEM runs it on solar surplus — never imports from grid") ran from the
    grid in every cheap hour of a dynamic tariff; the run was labelled
    ``source="solar"`` and booked to the "h on solar today" bar; it carried
    no force marker, so neither the force-expiry pass nor the deficit LIFO
    could end it; and it applied to every device at once, with none of the
    per-device opt-in, deficit bound, peak-slot guard (#864) or day-rollover
    expiry that the real cheap-hours top-up pass carries. #559's
    "Finish overnight from: Grid" IS the sanctioned way to buy a cheap hour,
    per device and per target.

    So the invariant is the #620 one, now true of the whole pool at its last
    writer: **you cannot distribute more solar surplus than the sun is
    producing.** The expensive-hour damping stays — lowering the pool can
    only ever make SEM spend less — and the final ``min`` makes the
    direction structural rather than a property of the branches.
    """
    damped = distributable
    # (#994) was ``== "expensive"`` — very_expensive silently did not damp
    # the pool, the one drift the six hand-typed copies had already produced.
    if is_expensive_name(price_level):
        damped = max(0.0, distributable - 500)
    return min(damped, distributable)


@dataclass(frozen=True)
class LoadIntent:
    """(desired-state, phase 1) The MANAGEMENT layer's decision for one load:
    what state it should be in, and why. Execution reconciles reality to this —
    it is the single source of truth for on/off, so a gate that yields ``on=False``
    stops a running load *by construction* (no separate deactivation path to
    forget). ``source`` derives the legacy force markers instead of hand-setting
    them (``_batt_overnight_forced == source == 'tier2_battery'`` etc.)."""
    on: bool
    power_w: float
    source: Optional[str]   # 'solar'|'tier1_battery'|'tier2_battery'|'cheap_grid'|'comfort_floor'|None
    reason: str
    #: (#1174) the reason as a stable code (``reason_codes``); empty = the
    #: source names it. Recorded only, left out of equality.
    code: str = field(default="", compare=False)
    #: (#1335) The watts layer 3 sends with the start or re-tune, when they
    #: differ from ``power_w`` (what the load is expected to draw, which the
    #: walk books). A switch ignores it; a watt setpoint follows it. None =
    #: send ``power_w``.
    command_w: Optional[float] = field(default=None, compare=False)
    #: (#1335) Layer 3 lets go of an ADOPTED claim (mode Off): ownership and
    #: force markers are cleared with no write. Layer 1 only says so.
    release: bool = field(default=False, compare=False)
    #: (#1323) The load is to be stepped DOWN — below its normal state, not
    #: merely off: a lower setpoint or the "blocked" signal. Layer 1 only
    #: says so; layer 3 sends it and takes it back when no intent asks.
    step_down: bool = False


#: (#1335) Sources that buy the run (grid, battery) or need no sun (the
#: comfort floor): a run on them holds its power and is never re-tuned to
#: the sun's pool, and the walk lets it take only the sun that is left.
PAID_SOURCES = ("cheap_grid", "tier2_battery", "comfort_floor")

#: (#1323) The decision log's verb for a load held below its normal state.
STEP_DOWN_VERB = "step_down"


def _expected_draw(device, command_w: float, *, fallback: float) -> float:
    """(#1335) What the load will draw when sent ``command_w``. A watt
    setpoint says so itself (``expected_draw_w``: the value its entity will
    take); anything else draws ``fallback`` — its rating on a start, its
    measured draw while it runs."""
    fn = getattr(device, "expected_draw_w", None)
    if callable(fn):
        try:
            value = fn(command_w)
        except Exception:  # noqa: BLE001 — an unreadable entity is no answer
            value = None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(0.0, float(value))
    return float(fallback)


def _num(value, default: float = 0.0) -> float:
    """A device's watt figure as a float — only a real number counts (a
    test double or a broken attribute is not a rating)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return float(default)


def _start_refused(device, now: Optional[datetime] = None) -> bool:
    """(#1335) Would ``can_activate`` refuse a start right now? Its
    read-only twin — ``can_activate`` starts the activation-delay clock, and
    the walk only asks. A load that cannot start this cycle takes nothing
    from the pool, so the sun goes to the next load (the old passes did the
    same: they debited only a start that happened)."""
    now = now or datetime.now()
    try:
        if _phase_held(device):
            return True
        if getattr(device, "daily_max_runtime_reached", False) is True:
            return True
        deps = getattr(device, "_check_dependencies", None)
        if callable(deps) and deps() is False:
            return True
        until = getattr(device, "_external_off_until", None)
        if isinstance(until, datetime) and now < until:
            return True
        min_off = getattr(device, "min_off_seconds", 0)
        last_off = getattr(device, "_last_deactivated", None)
        if (isinstance(min_off, (int, float)) and min_off > 0
                and isinstance(last_off, datetime)
                and (now - last_off).total_seconds() < min_off):
            return True
        delay = getattr(device, "activation_delay_seconds", 0)
        if isinstance(delay, (int, float)) and delay > 0:
            since = getattr(device, "_surplus_since", None)
            if not isinstance(since, datetime) or (now - since).total_seconds() < delay:
                return True
    except Exception:  # noqa: BLE001 — unknown is not refused
        return False
    return False


def sem_started(device) -> bool:
    """(#847/#908/#1335) THE ownership rule of every stop that undoes SEM's
    own action — layer 1's Mode-Off release and the teardown: SEM issued the
    ON itself. An adopted load (seen running, claimed so goal gates could
    stop it) and the user's own load never qualify."""
    # commanded ⊆ owned, as the device property states it (#847)
    return (bool(getattr(device, "_sem_owned", False))
            and bool(getattr(device, "_sem_commanded", False)))


def _heater_band(device: "ControllableDevice"):
    """(#1102) A load's thermometer band as ``(state, below_keep_at)``, or
    None for a load without an engaged band (no fields, no reading, a
    misconfigured band). ``below_keep_at`` is in the band's own direction:
    a heater below its target, a cooler above it."""
    state = getattr(device, "comfort_state", None)
    if state not in ("forced", "willing", "banked"):
        return None
    read = getattr(device, "_comfort_reading", None)
    thresholds = getattr(device, "_comfort_thresholds_c", None)
    direction = getattr(device, "_comfort_direction", None)
    if not (callable(read) and callable(thresholds) and callable(direction)):
        return None
    try:
        temp = read()
        target = float(thresholds()[0])
        cooling = direction() == "cool"
    except Exception:  # noqa: BLE001 — an unreadable band is no band
        return None
    if not isinstance(temp, (int, float)):
        return None
    below = float(temp) > target if cooling else float(temp) < target
    return state, below


def _goal_wants_start(device: "ControllableDevice") -> bool:
    """(#1102) The device's own start gap below Keep at. A device without
    the rule (a test double, an older device class) starts as before."""
    wants = getattr(device, "comfort_goal_wants_start", None)
    if not callable(wants):
        return True
    try:
        return wants() is not False
    except Exception:  # noqa: BLE001 — an unreadable band starts as before
        return True


#: (#1102) A device's own run (Legionella): SEM-driven, never re-tuned.
OWN_RUN_SOURCE = "legionella"

#: (#1321) The user's one-off "run now" (``plan_override`` force). SEM-driven:
#: SEM started it, so SEM stops it once the override ends.
OVERRIDE_SOURCE = "override"

#: (#1321) The one-off actions a load acts on; ``cap``/``move`` stay inert.
LOAD_OVERRIDE_ACTIONS = ("skip", "force")


def override_may_force(device: "ControllableDevice") -> bool:
    """(#1321) May a ``force`` override run this load at all? Not while the
    device is on vacation (a heat pump or a tank SEM must not encourage),
    not past its daily cap, not once its own stop condition is met."""
    if getattr(device, "vacation", False) is True:
        return False
    if getattr(device, "daily_max_runtime_reached", False) is True:
        return False
    if getattr(device, "stop_condition_met", False) is True:
        return False
    return True


def _heater_claim(device: "ControllableDevice", active: bool, held: float) -> float:
    """(#1102) What a heater rung expects to draw: the measured draw while it
    runs and a power reading exists, else its rating. A tank without a power
    sensor of its own reports a stored figure, not a measurement — the floor
    rung claimed 1000 W for a 3000 W boiler on .175."""
    rated = _num(getattr(device, "rated_power", 0.0))
    if active and getattr(device, "power_entity_id", None) and held > 0:
        return float(held)
    return rated


def compute_load_intent(
    device: "ControllableDevice",
    *,
    remaining_surplus_w: float,
    tier1_headroom_w: float = 0.0,
    price_is_cheap: bool = False,
    peak_freeze: bool = False,
    is_shed_target: bool = False,
    soc_above_reserve: bool = False,
    is_night: bool = True,
    daylight_remaining_s: "Optional[float]" = None,
    plan: "PlanVerdict" = NO_OPINION,
    override: Optional[str] = None,
    grid_start_fits: bool = True,
    shed_code: str = RC.LOAD_PEAK_SHED,
    price_is_expensive: bool = False,
    buying_w: float = 0.0,
) -> LoadIntent:
    """(desired-state, phase 1) Pure precedence walk → the load's desired state.

    Layer 1: one ordered decision (first match wins) — every reason a load
    turns on or off docks here (#1335: the 7 imperative passes it replaced
    are gone). It writes no control state (ownership, markers, timers);
    the device getters it reads keep their own diagnostic caches. ``remaining_surplus_w`` is the solar
    surplus left for THIS device after higher-priority loads (the caller's
    priority walk fills it); the battery/grid clauses don't consume it.
    Everything else is read off ``device`` so it works on a real device or a mock.
    ``override`` (#1321) is the load's active one-off action (``skip`` /
    ``force``), or None.
    """
    mode = getattr(device, "control_mode", DeviceControlMode.SURPLUS)
    active = bool(getattr(device, "is_active", False))
    held = device.get_current_consumption() if active else 0.0
    # (#638 Stage 3) Loads consult the same PlanVerdict the EV does —
    # the one gate, no side channels (the legacy plan_window bool died
    # in the C5 merge).
    plan_hold = plan.hold
    # (#953) "Finish overnight from: Grid" is a FINISH source — it waits
    # while today's remaining daylight can still deliver the outstanding
    # deficit. No separate stop clause is needed on THIS path: the intent is
    # rebuilt from scratch every cycle and ``_apply_source_markers`` derives
    # ``_offpeak_forced`` from the source, so a load whose gate has closed
    # simply falls through to the solar clause (kept, marker cleared) or to
    # "no source available" (stopped). The old imperative passes carried a
    # sticky marker and needed a twin in their force-expiry pass — class 17.
    sun_still_has_time = grid_top_up_defers_to_sun(
        device, daylight_remaining_s=daylight_remaining_s, is_night=is_night,
        comfort_block_open=plan.comfort_in_block)

    # 0. (#1335) Disabled: SEM no longer manages it. A run SEM started is
    #    ended once — nothing else would ever stop it; any other is left
    #    exactly as it is.
    if getattr(device, "is_enabled", True) is False:
        if active and sem_started(device):
            return LoadIntent(False, 0.0, None,
                              "disabled — ending SEM-started run",
                              RC.LOAD_DISABLED)
        # AS-OBSERVED: disabled and not SEM's run — left exactly as it is
        return LoadIntent(active, held, None, "disabled — not managed")

    # 1. Not SEM-driven. Off = monitor only; Peak-only = user-managed, but SEM
    #    still SHEDS it under peak risk.
    if mode == DeviceControlMode.OFF:
        # Switching the mode to Off while SEM is DRIVING the load must release
        # it (stop once, clear ownership), not strand it running forever —
        # class-17 sibling caught live (PROD 2026-07-23: mode→off, load stayed
        # on and SEM never touched it again). A load the USER turned on
        # (not _sem_owned) is left exactly as-is.
        if active and sem_started(device):
            # SEM issued the ON - opt-out undoes SEM's own action.
            return LoadIntent(False, 0.0, None, "mode off — ending SEM-started run",
                              RC.LOAD_MODE_OFF)
        if getattr(device, "_sem_owned", False):
            # (#847) ADOPTED only (user/externally started, claimed
            # under Surplus so goal gates could stop it). Opt-out
            # releases the claim with ZERO writes - the load stays
            # exactly as it is (hoyte). (#1335) Layer 3 releases it.
            # AS-OBSERVED: adopted load under Off — released, never switched
            return LoadIntent(active, held, None, "off — monitor only",
                              release=True)
        # AS-OBSERVED: mode Off is monitoring — the user's load as it is
        return LoadIntent(active, held, None, "off — monitor only")
    # 1b. (#1021) Behind the grid operator's relay and the relay is on: the
    #     relay cuts the power, so SEM keeps its hands off — no write in
    #     either direction, nothing counted, and the reason says who holds it.
    if getattr(device, "locked_by_operator", False) is True:
        # AS-OBSERVED: the operator's relay holds it — no write either way
        return LoadIntent(active, 0.0, None, "locked by the grid operator")
    if mode == DeviceControlMode.PEAK_ONLY:
        # This controller never proactively sheds peak_only loads — the load
        # manager owns their peak shedding via shed_priority. Matches the old
        # peak-shed pass, which skipped non-SURPLUS devices (ruflo M1).
        # AS-OBSERVED: peak-only is the user's; the load manager sheds it
        return LoadIntent(active, held, None, "peak_only — user-managed")

    # --- SURPLUS mode below ---
    # 2. Peak shed wins over any run reason.
    if is_shed_target:
        if shed_code == RC.LOAD_PHASE_GUARD:
            return LoadIntent(False, 0.0, None, "phase over its limit",
                              RC.LOAD_PHASE_GUARD)
        return LoadIntent(False, 0.0, None, "peak shed", RC.LOAD_PEAK_SHED)

    # 2b. (#638 Stage 3) The plan may STOP a paid run whose window closed —
    #     the hold is only ever raised while the remaining blocks can still
    #     deliver the deficit (load_verdict), so cutting here reclaims the
    #     energy for the planned block instead of letting the run bleed on.
    #     ONLY paid, plan-owned runs: solar runs are never plan-gated (the
    #     sun is spending itself), and user-started runs are not SEM's to cut.
    if (active and plan_hold
            and (getattr(device, "_batt_overnight_forced", False)
                 or getattr(device, "_offpeak_forced", False))):
        return LoadIntent(False, 0.0, None,
                          plan.reason or "joint energy plan: window closed",
                          RC.LOAD_PLAN_CLOSED)

    # 2c. (#1335) The device's own run (Legionella) is over: the stop says
    #     so. Ahead of the done gates — a tank just disinfected is above its
    #     normal target too, and "stop condition met" is not why it stops.
    if active and getattr(device, "own_run_ending", False) is True:
        return LoadIntent(False, 0.0, None,
                          "Legionella run over", RC.LOAD_LEGIONELLA_END)

    # 3. Done for the day — the hard stops (cap overrides the deficit).
    #    (#688) The daily MINIMUM is deliberately NOT one of them. It is a
    #    floor, not a stop: reaching it ends the PAID sources (clause 4), but
    #    free solar surplus may carry the load on up to the Maximum. Mirrors
    #    the EV floor/ceiling contract (#245) that this slider was built to
    #    mirror — treating Min as a stop made Max unreachable whenever Min > 0.
    if getattr(device, "daily_max_runtime_reached", False):
        return LoadIntent(False, 0.0, None, "daily max cap reached",
                          RC.LOAD_DAILY_MAX)
    if getattr(device, "stop_condition_met", False):
        return LoadIntent(False, 0.0, None, "stop condition met",
                          RC.LOAD_STOP_CONDITION)
    # 3c. (#1335) What the device's own start would refuse is decided here,
    #     where it can say so: a tank at its target, or a temperature sensor
    #     that is set up but reads nothing (SEM does not heat blind). Starts
    #     only — a run already going is left to its thermostat, as before.
    refusal = getattr(device, "start_refusal", None)
    if isinstance(refusal, str) and not active:
        if refusal == "sensor":
            return LoadIntent(False, 0.0, None,
                              "temperature sensor reads nothing — not started",
                              RC.LOAD_NO_READING)
        if refusal == "season":
            # (#1323) heat or cool by the forecast, and no outdoor reading
            # yet. A unit that is too cold never says this: it heats.
            return LoadIntent(False, 0.0, None,
                              "no outdoor reading yet — heat or cool not picked",
                              RC.LOAD_NO_SEASON)
        return LoadIntent(False, 0.0, None, "at its target temperature",
                          RC.LOAD_AT_TARGET)
    # 3d. (#594/#1335) Away: no comfort heating. A run stops; the optional
    #     hot-water dump may still take free sun (capped at the minimum
    #     temperature by the device's own target), nothing paid.
    sun_only = False
    if getattr(device, "vacation", False) is True:
        if getattr(device, "vacation_dhw_surplus", False) is not True:
            return LoadIntent(False, 0.0, None,
                              "comfort heating paused while away",
                              RC.LOAD_VACATION)
        sun_only = True

    # 3a. (#1121) The device's own run (Legionella) needs no sun: kept as
    #     it is, never re-tuned. Only a shed (clause 2) or its own end stops it.
    #     (#1102/#1335) It STARTS here too (and ends at 2c): the hot-water
    #     device only says the run is due or over and never switches itself,
    #     so the run is SEM's own command (Mode Off and teardown stop it).
    if getattr(device, "runs_without_surplus", False) is True:
        if active:
            return LoadIntent(True, _heater_claim(device, True, held), OWN_RUN_SOURCE,
                              "Legionella run — ends at its own target",
                              RC.LOAD_LEGIONELLA)
        return LoadIntent(True, _heater_claim(device, False, held), OWN_RUN_SOURCE,
                          "Legionella run due", RC.LOAD_LEGIONELLA)

    # 3e. (#1321) The user's one-off, for the minutes they chose: ``skip``
    #     keeps it off, ``force`` runs it with or without sun. Only in
    #     Smart (surplus) mode — Off and Peak-only returned above, so a
    #     standing opt-out outranks a one-off, as for chargers and batteries.
    #     Everything above still wins: the operator's lock (1b), the peak
    #     shed (2 — a forced load CAN be shed by a peak), the daily cap and
    #     the device's own stop (3) and its own run (3a). A force does not
    #     START under a peak warning (``peak_freeze``), nor on vacation.
    #     A tank at its target or with a dead sensor is not started (3c).
    #     ``skip`` is an ordinary stop: the minimum run still holds (only
    #     Mode Off beats it). ``force`` has its own source, so the whole-set
    #     rules for sun runs — the deficit stop and "no sun" — pass it by,
    #     and the walk books it only the sun that is left (#1335).
    #     When the override ends this clause is simply not taken: the walk
    #     below decides again, and with no sun it stops the run SEM started.
    # (#1323) The peak limit near, on a load that can step down (clause 3f).
    peak_step_down = (not active and peak_freeze
                      and getattr(device, "step_down_ready", False) is True)
    if override == "skip":
        if peak_step_down:
            # (#1321/#1323) A pause must not undo a PEAK step-down: a plain
            # off intent let layer 3 release it after its hold while the
            # peak was still near. The peak's intent wins — the load is off
            # either way, and the step-down is the peak's, so it says so.
            # A PRICE step-down is not kept: a pause means SEM does nothing.
            return LoadIntent(False, 0.0, None,
                              "peak limit near — stepped down",
                              RC.LOAD_STEP_DOWN_PEAK, step_down=True)
        return LoadIntent(False, 0.0, None, "paused by you for now",
                          RC.LOAD_OVERRIDE_STOP)
    if (override == "force" and override_may_force(device)
            and (active or not peak_freeze)):
        return LoadIntent(True, _heater_claim(device, active, held), OVERRIDE_SOURCE,
                          "run now — set by you", RC.LOAD_OVERRIDE_RUN)

    # 3b. A ScheduleDevice past its deadline is a hard commitment — force it on
    #     regardless of surplus or peak posture (matches the old deadline pass,
    #     which was deliberately not peak-gated). ruflo B1. (#1048/#1335) A
    #     phase over its limit outranks it: a deadline beats the peak, not a fuse.
    if (getattr(device, "is_deadline_approaching", False) is True and not active
            and not _phase_held(device)):
        _rated = _num(getattr(device, "rated_power", 0.0))
        return LoadIntent(True, _rated, "solar", "deadline force", RC.LOAD_DEADLINE)

    # 3f. (#1323) A shortfall: the load steps DOWN. Only a load that can
    #     (``step_down_ready`` — the user switched it on, and its comfort
    #     band reads inside its range, so "too cold" below still leads), and
    #     only one that is not running: a run is ended by its own reasons
    #     above and in layer 2, never by this. Two causes, both already known
    #     to the walk: the peak limit is near (``peak_freeze``, the load
    #     manager's own state), or the house buys grid power in an expensive
    #     hour. Stepping down lowers that import, so a load already stepped
    #     down stays so while the hour is expensive and no sun is left over —
    #     the cause is the expensive hour without sun, not the meter reading
    #     its own effect.
    if not active and getattr(device, "step_down_ready", False) is True:
        if peak_step_down:
            return LoadIntent(False, 0.0, None,
                              "peak limit near — stepped down",
                              RC.LOAD_STEP_DOWN_PEAK, step_down=True)
        stepped = getattr(device, "is_stepped_down", False) is True
        if price_is_expensive and (
                float(buying_w) > DEFAULT_MIN_SURPLUS_CHANGE
                or (stepped and float(remaining_surplus_w) <= 0.0)):
            return LoadIntent(False, 0.0, None,
                              "expensive grid power — stepped down",
                              RC.LOAD_STEP_DOWN_PRICE, step_down=True)

    # 4. A source can power it. peak_freeze blocks *new* starts but keeps a
    #    running load on (only an explicit shed removes it, clause 2).
    rated = _num(getattr(device, "rated_power", 0.0))
    threshold = _num(getattr(device, "min_power_threshold", rated), rated) or rated
    if rated <= 0.0:
        # no rating learned yet: it claims what it needs to switch on at all
        # (the same fallback as ``_rated_claim``)
        rated = threshold
    can_start = active or not peak_freeze
    band = _heater_band(device)
    # (#1102) With a thermometer band the band leads: the daily run time
    # asks nothing (a hot tank was heated again for its minutes), and the
    # band's own "too cold" is the floor rung below — not a deficit that
    # waits for the user's paid sources.
    deficit = (band is None
               and bool(getattr(device, "has_runtime_deficit", False)))
    if sun_only:
        # (#594) the vacation dump: free sun only — no band, no paid source
        band, deficit, tier1_headroom_w = None, False, 0.0
    # (#1335) A run on a paid source (the markers layer 3 derived from the
    # source it was started on) keeps its source while that source's own
    # terms hold; the sun does not relabel it.
    paid_marked = active and (
        getattr(device, "_offpeak_forced", False) is True
        or getattr(device, "_batt_overnight_forced", False) is True)

    # (#688) Past the floor, only FREE surplus may extend the run — the
    # battery has nothing left to guarantee, so the Tier-1 assist stands down.
    # (Tier-2 and cheap-grid below are already deficit-gated, so they close
    # themselves at the floor; pinned by tests either way.)
    if getattr(device, "daily_targets_met", False):
        tier1_headroom_w = 0.0
    effective = float(remaining_surplus_w) + float(tier1_headroom_w)
    # (#688) the start RESERVE: a fresh start needs margin on top of the
    # threshold (600 W pump, 800 W ask), so the start itself plus the next
    # cloud doesn't flip the surplus negative and cycle the device. STARTS
    # only — a running load keeps the plain threshold; reserving against a
    # healthy run would CREATE the cycling this prevents.
    start_bar = threshold
    if not active:
        start_bar = threshold + max(
            0.0, _num(getattr(device, "start_reserve_w", 0.0)))
    # (#1335) What the sun's run is sent: a fresh start the free power, a
    # running load the free power plus its Tier-1 share — a watt setpoint
    # follows it, a switch ignores it. What it is expected to draw is what
    # the walk books (#1156: a running load its measured draw).
    sun_command = max(0.0, float(remaining_surplus_w)
                      + (float(tier1_headroom_w) if active else 0.0))
    sun_claim = _expected_draw(device, sun_command,
                               fallback=held if active else rated)
    # A paid start is sent its threshold; a paid run holds what it draws.
    paid_claim = (held if active
                  else _expected_draw(device, threshold, fallback=rated))
    paid_command = None if active else threshold
    sun_src = ("tier1_battery"
               if tier1_headroom_w > 0 and remaining_surplus_w < threshold
               else "solar")

    # (#1102) Too cold: at or past the limit it heats NOW on any tariff, and
    # a run the floor started goes on to Keep at, not just past the limit.
    # Peak shed (clause 2) and the operator's lock (1b) still outrank it.
    if band is not None and can_start and (
            band[0] == "forced"
            or (active and band[1]
                and getattr(device, "_comfort_floor_run", False) is True)):
        src = "solar" if effective >= threshold else "comfort_floor"
        return LoadIntent(True, _heater_claim(device, active, held), src,
                          "too cold — heats to its keep-at temperature",
                          RC.LOAD_COMFORT_FLOOR)

    if effective >= start_bar and can_start and not paid_marked:
        return LoadIntent(True, sun_claim, sun_src,
                          f"{sun_src}: {effective:.0f}W ≥ {threshold:.0f}W",
                          command_w=sun_command)

    # (#638 C5) Comfort banking: a WILLING band inside its planned block.
    # The ONE sanctioned place the plan CREATES a run — banking has no
    # reactive run reason at all (a willing room otherwise only rides
    # free surplus). Forced rooms never land here: forcing lives on the
    # deficit paths, and a forced room's comfort_state is not "willing".
    # (#1102) Its COMFORT block — the runtime block is the deficit
    # clauses' to serve, under their own source, price and daylight terms —
    # and Keep at is the goal there: it heats up to Keep at; Extra above it
    # is for the sun only. (#864/#1335) A start from the grid must fit the
    # billing slot, as the cheap-hours start does.
    # (#1102) A START also needs the reading clearly below Keep at (the
    # device's start gap); a run already going heats on to Keep at.
    if (plan.comfort_in_block and can_start and band is not None
            and band[0] == "willing" and band[1]
            and (active or (grid_start_fits and _goal_wants_start(device)))):
        return LoadIntent(True, _heater_claim(device, active, held), "cheap_grid",
                          plan.reason or "joint plan: heats to its keep-at temperature",
                          RC.LOAD_COMFORT_GOAL, command_w=paid_command)

    # Overnight battery (Tier-2): finish a runtime deficit off the battery.
    # (#633) gated on night — "Finish overnight from: Battery" must not fire
    # in daytime (caught live at 09:10 in full sun).
    # (#638 G4) ``plan_hold`` = the joint energy plan placed this
    # load's blocks elsewhere tonight — an extra AND-gate on the start,
    # never a run reason. No trusted plan leaves behaviour untouched.
    if (deficit and can_start and is_night
            and not plan_hold
            and getattr(device, "battery_eligible_overnight", False)
            and soc_above_reserve):
        return LoadIntent(True, paid_claim, "tier2_battery",
                          "overnight battery — runtime deficit",
                          command_w=paid_command)

    # Cheap-hours grid: finish a runtime deficit off the grid in a cheap window.
    # (#953) ``not sun_still_has_time`` is the window its battery twin has had
    # since #633 — at night it is trivially true, so the overnight promise is
    # unchanged; by day the meter only pays once the sun has run out of time.
    # (#864/#1335) A START must fit the billing slot (``grid_start_fits``,
    # layer 2 reads the slot): price says go, the meter's budget says how
    # much. A run already going is the reactive shed's to judge.
    if (deficit and can_start and price_is_cheap
            and not plan_hold and not sun_still_has_time
            and (active or grid_start_fits)
            and getattr(device, "top_up_policy", "solar_only") == "cheap_hours"):
        return LoadIntent(True, paid_claim, "cheap_grid",
                          "cheap-hours grid — runtime deficit",
                          command_w=paid_command)

    if paid_marked:
        # (#1335) The paid run's own terms no longer hold. Sun enough to
        # carry it: it goes on as a sun run. Otherwise it ends, and says why
        # (the old force-expiry pass and goal gate, in one place).
        if effective >= threshold:
            return LoadIntent(True, sun_claim, sun_src,
                              f"{sun_src}: {effective:.0f}W ≥ {threshold:.0f}W",
                              command_w=sun_command)
        if getattr(device, "daily_targets_met", False):
            return LoadIntent(False, 0.0, None,
                              "daily target met — ending battery/grid top-up",
                              RC.LOAD_TARGET_MET)
        return LoadIntent(False, 0.0, None, "battery/grid top-up ended",
                          RC.LOAD_OVERNIGHT_END)

    if active:
        # (#1335, D2) A running sun load stays on here even when its own
        # share fell short: the whole-set walk (layer 2) stops the LOWEST
        # priority ones first once the pool runs more than 100 W short, so a
        # higher-priority load never loses first.
        return LoadIntent(True, sun_claim, sun_src,
                          f"{sun_src}: running on {max(0.0, effective):.0f}W",
                          command_w=sun_command)

    # 5. No source → off. When a plan hold is what suppressed the paid
    #    sources, SAY SO — "no source available" with a block twenty
    #    minutes away reads as a bug; the plan's own words read as a plan.
    if plan_hold and deficit:
        detail = f" (until {plan.until:%H:%M})" if plan.until else ""
        return LoadIntent(False, 0.0, None,
                          (plan.reason or "joint energy plan: waiting for the planned window") + detail,
                          RC.LOAD_PLAN_WAIT)
    return LoadIntent(False, 0.0, None, "no source available", RC.LOAD_NO_SOURCE)


def _load_meter_day(device: "ControllableDevice"):
    """(#703) The load's OWN day boundary — the sunrise-held meter day its
    runtime/deficit live on, NOT the calendar date. The coordinator holds
    ``_load_meter_day`` through the night, so an overnight top-up keeps
    serving the day it started; a force stamped and expired against the
    CALENDAR date instead was killed at exactly 00:00 ("day rollover") while
    its deficit was still open, then re-forced a min_off later — a spurious
    contactor flap every midnight. Stamping AND staleness both read this one
    boundary, so expiry lands at sunrise — the same instant the deficit
    itself resets — by construction. Falls back to the calendar date before
    the first runtime tick stamps the device (fresh boot)."""
    day = getattr(device, "_daily_runtime_meter_day", None)
    if day is not None:
        return day
    from homeassistant.util import dt as dt_util
    return dt_util.now().date()


def _apply_source_markers(device: "ControllableDevice", intent: LoadIntent) -> None:
    """(desired-state, phase 2) The legacy force markers become a DERIVED VIEW of
    the intent's source — recomputed each reconcile, never hand-set — so they
    cannot leak (bug-class 18). Dates are stamped for the load's METER day
    (#703) — the same boundary its deficit lives on."""
    today = _load_meter_day(device)
    is_tier2 = intent.source == "tier2_battery"
    is_grid = intent.source == "cheap_grid"
    device._batt_overnight_forced = is_tier2
    device._batt_overnight_forced_date = today if is_tier2 else None
    device._offpeak_forced = is_grid
    device._offpeak_forced_date = today if is_grid else None
    # (#1102/#1335) remember a run the comfort floor started, so it goes on
    # to Keep at — written here with the other derived markers, not by the
    # layers that decide
    device._comfort_floor_run = bool(
        intent.on and intent.code == RC.LOAD_COMFORT_FLOOR)


def _clear_source_markers(device: "ControllableDevice") -> None:
    device._batt_overnight_forced = False
    device._batt_overnight_forced_date = None
    device._offpeak_forced = False
    device._offpeak_forced_date = None
    device._comfort_floor_run = False


def _reconcile_load_observe(device: "ControllableDevice", intent: LoadIntent,
                            active: bool, controller=None) -> float:
    """OBSERVER mode = the layer-3 intercept, in one place.

    Management (layer 1) + decision (layer 2) already ran live against the real
    sensors and produced ``intent``. Here — the ONLY execution seam — we LOG the
    command we WOULD send and return the load's OBSERVED draw, without actuating
    or mutating any device state. The would-command log is the observation/test
    surface: HA-TEST runs the full real pipeline and audits these lines with zero
    hardware risk. This is why observer mode needs no separate ``observe_only``
    path — a clean layer cut makes it a one-line branch in the actuator.
    """
    # (#764) Record the would-decision on the controller's standard surface
    # BEFORE the log lines — the surface can never drift from what the log
    # says. Optional: bare callers keep the pure behavior.
    if controller is not None:
        try:
            controller.record_observer_decision(device, intent, active=active)
        except Exception:  # noqa: BLE001 — the surface must never break the seam
            pass
    # Deliberately NOTHING is mutated here — not even the surplus debounce timer
    # (the H2 reset in the actuating path). Observer is a pure shadow: each cycle
    # independently says "given reality now, I would do X". (Belief-sync via
    # reconcile_all at update()'s top is separate and permitted — see there.)
    # (#1084) The decision log's load seam under observer: the same command
    # the WOULD line below names, flagged as observed. A hold sends nothing.
    _log = getattr(controller, "decision_log", None)
    if intent.on and (not active or intent.source not in (None, OWN_RUN_SOURCE)):
        from .decision_log import record_load
        record_load(_log, device, on=True, watts=intent.power_w,
                    reason_code=intent.code or intent.source or RC.LOAD_START,
                    text=intent.reason, observer=True)
    elif not intent.on and active:
        from .decision_log import record_load
        record_load(_log, device, on=False,
                    reason_code=intent.code or RC.LOAD_STOP,
                    text=intent.reason, observer=True)
    # (#1323) the step-down SEM would send, or take back — the same two
    # commands layer 3 sends for real, flagged as observed
    stepped = getattr(device, "is_stepped_down", False) is True
    if intent.step_down and not stepped and not active:
        from .decision_log import record_load
        record_load(_log, device, on=False, reason_code=intent.code,
                    text=intent.reason, observer=True, verb=STEP_DOWN_VERB)
    elif stepped and not intent.step_down and not intent.on:
        from .decision_log import record_load
        record_load(_log, device, on=False,
                    reason_code=RC.LOAD_STEP_DOWN_END,
                    text="step-down released", observer=True)
    observed = device.get_current_consumption() if active else 0.0
    name = getattr(device, "name", None) or getattr(device, "device_id", "?")
    # (#762) transition-gated: a WOULD that has not changed is not news —
    # ~950 INFO lines/day on .175 for decisions holding perfectly still.
    # One key per device: ACTIVATE→ADJUST→DEACTIVATE edges all log.
    _key = f"observer:{getattr(device, 'device_id', name)}"
    if intent.on and not active:
        log_on_change(_LOGGER, _key, logging.INFO,
                      "OBSERVER · WOULD ACTIVATE %s @ %.0fW [source=%s] — %s",
                      name, intent.power_w, intent.source, intent.reason)
    elif not intent.on and active:
        log_on_change(_LOGGER, _key, logging.INFO,
                      "OBSERVER · WOULD DEACTIVATE %s — %s", name, intent.reason)
    elif intent.on and active and intent.source not in (None, OWN_RUN_SOURCE):
        log_on_change(_LOGGER, _key, logging.INFO,
                      "OBSERVER · WOULD ADJUST %s → %.0fW [source=%s] — %s",
                      name, intent.power_w, intent.source, intent.reason)
    elif intent.step_down and not stepped:
        log_on_change(_LOGGER, _key, logging.INFO,
                      "OBSERVER · WOULD STEP DOWN %s — %s", name, intent.reason)
    elif stepped and not intent.step_down:
        log_on_change(_LOGGER, _key, logging.INFO,
                      "OBSERVER · WOULD RELEASE STEP-DOWN %s", name)
    # else: idle, or on-but-not-SEM-driven (source is None) → no command to log.
    return observed


def _note_load(device, *, on: bool, watts: Optional[float] = None,
               reason_code: str = "", text: str = "",
               observer: bool = False, verb: Optional[str] = None) -> None:
    """(#1084) Hand a load command to the decision log, if one is wired.

    The module-level choke points below take a device, not the controller;
    the device knows its controller from ``register_device``. Recording only.
    """
    from .decision_log import record_load
    _log = getattr(getattr(device, "_controller", None), "decision_log", None)
    record_load(_log, device, on=on,
                watts=watts, reason_code=reason_code, text=text,
                observer=observer, verb=verb)


async def _activate_owned(device: "ControllableDevice", watts: float,
                          *, reason_code: str = "", text: str = "") -> float:
    """Actuate ON **and** record ownership — the single choke point.

    Ownership follows from SEM having actuated the device, so it belongs next to
    the actuation, not in each activation pass. Pre-fix it was recorded at the
    call site and four of the five passes forgot it (Tier-2 overnight battery,
    cheap-hours grid, ScheduleDevice deadline) — no ``activate()`` implementation
    sets ``_sem_owned`` either, so those loads ran with ownership False while SEM
    was driving them. The mode→Off release (:func:`compute_load_intent` and the
    force-expiry pass) is gated on exactly that flag, so setting Mode → Off left
    the load running forever: bug class 17 again, instance 5. Caught live on PROD
    2026-07-26 — a towel heater started by the Tier-2 pass kept heating 5 minutes
    after Mode → Off. Guarded by ``tests/test_load_ownership_choke_point.py``.
    """
    consumed = await device.activate(watts)
    if consumed > 0:
        device.record_activated()
        # (#1084) logged once it took: a refused start sent nothing new
        _note_load(device, on=True, watts=watts,
                   reason_code=reason_code or RC.LOAD_START, text=text)
    return consumed


async def _adjust_owned(device: "ControllableDevice", watts: float,
                        *, reason_code: str = "", text: str = "") -> float:
    """(#1084) Re-tune a running load's setpoint — the one place it happens,
    so the decision log sees a setpoint change of a meaningful size."""
    consumed = await device.adjust_power(watts)
    _note_load(device, on=True, watts=watts,
               reason_code=reason_code or RC.LOAD_ADJUST, text=text)
    return consumed


async def _deactivate_owned(device: "ControllableDevice",
                            *, reason_code: str = "", text: str = "") -> bool:
    """Actuate OFF **and** release ownership. Returns True if it stopped.

    Anti-flicker can refuse the stop, so ownership is only released once the
    device actually reports idle.
    """
    await device.deactivate()
    if device.is_active:
        return False
    device.record_deactivated()
    _note_load(device, on=False, reason_code=reason_code or RC.LOAD_STOP,
               text=text)
    return True


def _step_down_must_end(device) -> bool:
    """(#1323) Is a stepped-down load out of SEM's hands, so its step-down
    ends whatever the minimum hold says? Mode Off or peak-only, disabled,
    behind the operator's relay, the house is away, or it is too cold."""
    return (getattr(device, "control_mode", DeviceControlMode.SURPLUS)
            != DeviceControlMode.SURPLUS
            or getattr(device, "is_enabled", True) is False
            or getattr(device, "locked_by_operator", False) is True
            or getattr(device, "vacation", False) is True
            # too cold: the comfort floor leads, whatever the peak says
            or getattr(device, "comfort_state", "") == "forced")


async def _release_step_down(device) -> None:
    """(#1323) Take a step-down back and note it. Layer 3's own helper."""
    if await device.release_step_down():
        _note_load(device, on=False, reason_code=RC.LOAD_STEP_DOWN_END,
                   text="step-down released")


async def reconcile_load(device: "ControllableDevice", intent: LoadIntent,
                         *, observer: bool = False, controller=None) -> float:
    """(desired-state, phase 2) The EXECUTION layer: make the load's reality match
    the management layer's ``intent``. This is the SINGLE place a load is actuated.

    Anti-cycle lives here (``can_activate`` / ``can_deactivate`` own min_on /
    min_off), so a stop can lag the intent by the anti-flicker window — but the
    *decision* has no separate stop path to forget. Returns the load's resulting
    consumption (for the caller's surplus accounting).

    ``observer=True`` cuts the trigger: layers 1+2 still ran for real, but the
    actuator only logs what it would do (see :func:`_reconcile_load_observe`).
    """
    active = bool(getattr(device, "is_active", False))

    if observer:
        return _reconcile_load_observe(device, intent, active,
                                       controller=controller)

    if intent.release:
        # (#847/#1335) mode Off on an ADOPTED load: let go of the claim with
        # no write — the load stays exactly as the user has it.
        device._sem_owned = False
        _clear_source_markers(device)

    # (#1323) Step-down: sent and taken back here, nowhere else.
    stepped = getattr(device, "is_stepped_down", False) is True
    if stepped and not intent.step_down:
        # No intent asks for it any more. The minimum hold is against a
        # cause that flickers; anything that wants the load (a run, "too
        # cold") or takes it out of SEM's hands ends the step-down at once.
        # A start that can go out this cycle REPLACES the step-down: the
        # start writes the final state, so the contacts move once, not
        # twice. If it does not take, the release follows below.
        starting = intent.on and not active and device.can_activate()
        if not starting and (intent.on or _step_down_must_end(device)
                             or device.can_release_step_down()):
            await _release_step_down(device)
    elif intent.step_down and not stepped and not active:
        if device.can_step_down() and await device.step_down():
            _note_load(device, on=False, reason_code=intent.code,
                       text=intent.reason, verb=STEP_DOWN_VERB)

    command = intent.power_w if intent.command_w is None else intent.command_w
    if intent.on and not active:
        if not device.can_activate():
            return 0.0
        consumed = await _activate_owned(
            device, command,
            reason_code=intent.code or intent.source or RC.LOAD_START,
            text=intent.reason)
        if consumed > 0:
            device.reset_surplus_timer()
            _apply_source_markers(device, intent)
        elif getattr(device, "is_stepped_down", False) is True:
            # (#1323) the start did not take: the step-down still ends
            await _release_step_down(device)
        return consumed

    if not intent.on and active:
        if intent.code in (RC.LOAD_MODE_OFF, RC.LOAD_DISABLED):
            # (class-17 sibling / #644 / #1335) The user's own Off (or
            # disabling the load) beats the minimum run: a deliberate command beats flicker protection.
            # The anti-cycle rule lives here, so its one exception does too
            # (the device's own deactivate gates on the unified clock).
            device._last_activated = None
            _st = getattr(device, "_status", None)
            if _st is not None and hasattr(_st, "last_activated"):
                _st.last_activated = None
        elif not device.can_deactivate():
            return device.get_current_consumption()   # anti-flicker holds it on
        if await _deactivate_owned(device,
                                   reason_code=intent.code or RC.LOAD_STOP,
                                   text=intent.reason):
            _clear_source_markers(device)
            return 0.0
        return device.get_current_consumption()

    if intent.on and active:
        # source is None ⇒ "not SEM-driven" (off / peak-only kept as observed):
        # never actuate it — SEM only re-tunes loads it is actually driving.
        if intent.source is None:
            return device.get_current_consumption()
        if (intent.source in (OWN_RUN_SOURCE, OVERRIDE_SOURCE)
                or intent.source in PAID_SOURCES):
            # (#1335) never re-tuned: an own run, or a paid run holding the
            # power its start set (offering it the sun's pool wrote its floor
            # every other cycle). A tank that holds a setpoint for another
            # target (a run began while it heated on sun) gets the run's own
            # target written once.
            if getattr(device, "target_stale", False) is True:
                await device.adjust_power(intent.power_w)
            _apply_source_markers(device, intent)
            return device.get_current_consumption()
        consumed = await _adjust_owned(
            device, command,
            reason_code=intent.code or intent.source or RC.LOAD_ADJUST,
            text=intent.reason)
        _apply_source_markers(device, intent)
        return consumed

    # not intent.on and not active — idle. Reset the sustained-surplus debounce
    # so a cloud-shadow gap restarts the activation delay, matching the old
    # activation pass's reset_surplus_timer (ruflo H2). Harmless for off/peak
    # loads (their timer is never consulted).
    device.reset_surplus_timer()
    return 0.0


@dataclass
class SurplusAllocation:
    """Allocation result for a single device."""
    device_id: str
    device_name: str
    priority: int
    allocated_watts: float
    actual_consumption_watts: float
    state: str


@dataclass
class SurplusAllocationData:
    """Complete surplus allocation state."""
    total_surplus_w: float = 0.0
    distributable_surplus_w: float = 0.0
    regulation_offset_w: float = DEFAULT_REGULATION_OFFSET
    allocated_w: float = 0.0
    unallocated_w: float = 0.0
    active_devices: int = 0
    total_devices: int = 0
    allocations: List[SurplusAllocation] = field(default_factory=list)
    last_update: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "surplus_total_w": round(self.total_surplus_w, 1),
            "surplus_distributable_w": round(self.distributable_surplus_w, 1),
            "surplus_regulation_offset_w": self.regulation_offset_w,
            "surplus_allocated_w": round(self.allocated_w, 1),
            "surplus_unallocated_w": round(self.unallocated_w, 1),
            "surplus_active_devices": self.active_devices,
            "surplus_total_devices": self.total_devices,
            "surplus_allocations": [
                {
                    "device": a.device_name,
                    "priority": a.priority,
                    "allocated_w": round(a.allocated_watts, 1),
                    "consuming_w": round(a.actual_consumption_watts, 1),
                    "state": a.state,
                }
                for a in self.allocations
            ],
            "surplus_last_update": self.last_update.isoformat() if self.last_update else None,
        }


async def deactivate_devices(devices, reason: str = "teardown") -> int:
    """Release every load SEM COMMANDED on in ``devices`` (#656, #908).

    Module-level so the teardown path can use it after the registry has been
    detached — at removal time there is no controller left to ask, only the
    devices themselves. (#1335) This is the one stop outside
    ``reconcile_load``, on purpose: it must work with no controller, and it
    must stop a load inside its minimum run. It reads the same ownership rule
    (``sem_started``), and a device's own ``send()`` still withholds under
    observer mode.

    Deliberately takes the RAW device collection rather than
    ``get_devices_sorted()``: that view hides ``is_enabled=False`` and
    ``managed_externally`` devices, both of which SEM may have COMMANDED on
    and which a teardown that skips them would strand. Lowest priority first,
    so the log reads like a normal shed.

    (#908) Actuates ONLY loads SEM actually commanded on — ``_sem_commanded``,
    recorded at the ``_activate_owned`` choke point. The strands #656 exists
    to clear (a hot-water boost, an SG-Ready relay, a SEM-forced switch) all
    carry it. A load that was merely ADOPTED (external/user ON, claimed under
    Surplus so goal gates could stop it) or observed in observer mode was
    never SEM's to switch off — removing the integration must leave the user's
    loads exactly as they are (markusschloesser, observer-mode install:
    removal switched off his fridge and freezer, which SEM never commanded).
    This is the same ownership predicate every other stop path uses
    (``compute_load_intent`` clause 1, the force-expiry pass, the #847 mode→Off
    handler): actuate the commanded, leave the rest untouched. In observer
    mode SEM commands nothing, so this makes teardown a guaranteed no-op.

    Best-effort: one device failing must not abort the rest. The alternative
    to swallowing here is an unattended heating device left commanded on by an
    integration on its way out.
    """
    devices = sorted(
        devices, key=lambda d: getattr(d, "priority", 99) or 99, reverse=True,
    )
    stopped = 0
    for device in devices:
        if getattr(device, "is_stepped_down", False) is True:
            # (#1323) a step-down is SEM's own command: taken back, so a
            # pump is not left blocked by an integration that is gone
            try:
                await device.release_step_down()
            except Exception:  # noqa: BLE001 — the rest must still be released
                _LOGGER.warning("Could not release the step-down of %s (%s)",
                                getattr(device, "name", "?"), reason, exc_info=True)
        if not getattr(device, "is_active", False):
            continue
        # (#908) SEM only releases what SEM commanded. An adopted / external /
        # observer-mode load stays exactly as the user has it. (#1335) The
        # same rule as layer 1's Mode-Off release, from one function.
        if not sem_started(device):
            continue
        try:
            await _deactivate_owned(device, reason_code=RC.LOAD_TEARDOWN, text=reason)
            stopped += 1
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "Could not deactivate %s during %s (continuing): %s",
                getattr(device, "device_id", device), reason, e,
            )
    _LOGGER.info(
        "Deactivated %d of %d surplus-controlled devices (%s)",
        stopped, len(devices), reason,
    )
    return stopped


class SurplusController:
    """Controls surplus power distribution across multiple devices.

    Implements priority-based surplus routing:
    - Devices are sorted by priority (1=highest)
    - Each device has a minimum power threshold
    - Variable-power devices get proportional surplus
    - On/off devices get their full rated power or nothing
    - LIFO deactivation when surplus drops
    """

    def publish_observer_decision(self, *, key: str, name: str, action: str,
                                  power_w: float = 0.0, source=None,
                                  reason: str = "", kind: str = "load",
                                  **extra) -> None:
        """(#764) One WOULD decision, one surface — for EVERY family.

        Loads, chargers and batteries all land in the same
        ``observer_decisions`` map (keyed ``<device_id>`` / ``ev:<cid>`` /
        ``battery:<bid>``, with ``kind`` naming the family) so a simulation
        reads ONE attribute and gets the whole shadow cycle. The map always
        carries the CURRENT would-state — a fresh reader needs no history.
        The bus event fires only on decision TRANSITIONS, judged on the
        digit-stripped action/source/reason (the #762 rule: a wobbling watt
        number is not an edge).
        """
        import re as _re
        payload = {
            "device_id": key,
            "kind": kind,
            "name": name or key,
            "action": action,
            "power_w": float(power_w or 0.0),
            "source": source,
            "reason": reason,
        }
        payload.update(extra)
        self.observer_decisions[key] = payload
        self._observer_published_this_cycle.add(key)
        edge_key = _re.sub(r"-?\d+(?:[.,]\d+)?", "#",
                           f"{action}|{source}|{reason}")
        if self._observer_decision_keys.get(key) == edge_key:
            return
        self._observer_decision_keys[key] = edge_key
        try:
            self.hass.bus.async_fire(
                "solar_energy_management_observer_decision", dict(payload))
        except Exception:  # noqa: BLE001 — the event must never break the seam
            pass

    def retire_unpublished_observer_decisions(self) -> None:
        """(#764) The surface is a ROSTER, not a ledger — sweep once a cycle.

        ``observer_decisions`` answers "what would SEM do right now", so a
        device that no longer decides has to leave. Whoever published this
        cycle stays; everyone else is dropped, edge state included, so a
        device that leaves and comes back announces itself instead of
        returning silently.

        Found live on .175 the day this shipped: the legacy single-charger
        fallback decided once at startup, before ``_ev_devices`` was
        populated, and its row then sat on a one-charger rig's surface
        reading as a second charger. Same class as #744 — an append-only
        map describes history, and a simulation needs the present tense.
        """
        live = self._observer_published_this_cycle
        self._observer_published_this_cycle = set()
        # An empty pass empties the map, and that is the honest answer: SEM
        # would do nothing. A cycle that DIED never reaches the sweep (it is
        # the last step of ``_async_update_data``), so an error preserves the
        # last known shadow rather than blanking it.
        for key in [k for k in self.observer_decisions if k not in live]:
            self.observer_decisions.pop(key, None)
            self._observer_decision_keys.pop(key, None)

    def record_observer_decision(self, device, intent: "LoadIntent",
                                 *, active: bool) -> None:
        """(#764) A load's WOULD decision, mapped onto the shared surface.

        ``hold`` means no command would be sent — the device is already
        where SEM wants it.
        """
        if intent.on and not active:
            action = "activate"
        elif not intent.on and active:
            action = "deactivate"
        elif intent.on and active and intent.source not in (None, OWN_RUN_SOURCE):
            action = "adjust"
        elif (getattr(intent, "step_down", False)
              and getattr(device, "is_stepped_down", False) is not True):
            # (#1323) a standing step-down is re-published every cycle:
            # the roster is swept, so a state SEM would hold must say so
            action = "step_down"
        else:
            action = "hold"
        did = str(getattr(device, "device_id", "") or "")
        self.publish_observer_decision(
            key=did,
            name=str(getattr(device, "name", "") or did),
            action=action,
            power_w=float(intent.power_w or 0.0),
            source=intent.source,
            reason=intent.reason,
            kind="load",
            # (#1102) the rung, as a stable code — not only its source
            reason_code=str(getattr(intent, "code", "") or "") or None,
        )

    def __init__(
        self,
        hass: HomeAssistant,
        regulation_offset: float = DEFAULT_REGULATION_OFFSET,
    ):
        self.hass = hass
        self.regulation_offset = regulation_offset
        # (#764) Observer mode's WOULD decisions, published as a standard
        # surface: this map rides the observer-mode switch's attributes
        # (a fresh session reads the current would-state instantly) and a
        # bus event fires on every decision TRANSITION — so a simulation
        # bridge is a five-line HA automation, not an SSH log scraper.
        self.observer_decisions: Dict[str, dict] = {}
        self._observer_decision_keys: Dict[str, str] = {}
        self._observer_published_this_cycle: set[str] = set()
        # (#1084) The decision log: why a device's command changed. Owned
        # here because all three actuator seams (chargers, batteries, loads)
        # already hold this controller. Recording only; never restored.
        from .decision_log import DecisionLog
        self.decision_log = DecisionLog(hass)
        # (#812) Each device's own tariff, when it has one. Stamped once per
        # cycle in ``update``; a device without one reads the house level.
        from .device_tariff import DeviceTariffs
        self.device_tariffs = DeviceTariffs(hass)
        self.max_export_w: float = 0  # 0 = no limit. E.g., 10000 for 10kW export limit
        self._devices: Dict[str, ControllableDevice] = {}
        self._allocation_data = SurplusAllocationData()
        self._price_responsive_mode = False
        self._last_surplus = 0.0
        self._smoothed_surplus: Optional[float] = None
        # (#620) battery context, refreshed each update(); inert defaults so a
        # helper called before the first update() is a no-op.
        self._batt_soc: Optional[float] = None
        #: (#885) The tier-1 assist floor — max(buffer, dynamic floor).
        self._batt_buffer_soc: float = 100.0
        self._batt_reserve_soc: float = 100.0
        self._batt_assist_budget_w: float = 0.0
        self._batt_assist_budget_above_w: Optional[float] = None
        self._batt_priority: Optional[int] = None
        self._tier1_budget_left: float = 0.0
        # (arc Phase 4) last raw surplus samples for the median-of-3 pre-filter
        self._surplus_samples: List[float] = []
        # (#1321) this cycle's one-off overrides on loads, stamped by update():
        # device_id → {"action", "until"}. Empty = nothing set (the common case).
        self._load_overrides: Dict[str, Dict[str, Any]] = {}
        # (#1335) the last three solar production readings (None = no
        # reading that cycle), for the no-sun stop
        self._solar_samples: List[Optional[float]] = []
        # (#638 G4) per-cycle window verdicts from the joint energy plan:
        # device_id → True (inside its planned block) / False (planned
        # elsewhere tonight — don't start now). Absent = the plan has no say.
        # Stamped by update() from the coordinator; empty when actuation is
        # off or no trusted plan exists.
        self._plan_windows: dict = {}
        # (#864) the billing slot, stamped each cycle; None = no ceiling
        self._peak_slot_allowed_w: Optional[float] = None
        self._grid_import_w: float = 0.0
        self._grid_import_known: bool = True
        # (#1021) The grid operator's relay this cycle, stamped by the
        # coordinator. Devices marked "behind the relay" read it through
        # ``locked_by_operator``. INERT = no relay configured.
        from .shed_signal import INERT
        self.shed_signal = INERT

    @property
    def allocation_data(self) -> SurplusAllocationData:
        """Return current allocation state."""
        return self._allocation_data

    @property
    def price_responsive_mode(self) -> bool:
        return self._price_responsive_mode

    @price_responsive_mode.setter
    def price_responsive_mode(self, value: bool) -> None:
        self._price_responsive_mode = value

    # ``set_anticipated_surplus`` lived here until #659, together with the
    # ``_anticipated_surplus_w`` / ``_anticipated_deadline`` fields. It was
    # the #106 "pre-warm devices before the EV taper completes" promise, and
    # it was dead on both ends: nothing ever called it, and nothing ever read
    # the two fields it set. The docstring described behaviour ("will factor
    # this in 2 min before the deadline") that no code implemented — the kind
    # of spec-vs-reality gap that reads as a working feature to the next
    # person who greps for it.
    #
    # If pre-warming is wanted, it belongs in the surplus computation itself
    # (``_compute_surplus`` / the desired-state ``compute_load_intent`` path),
    # not in a setter that hopes someone downstream looks.

    # ``distribute_ev_budget`` lived here until #651: a priority cascade
    # that split the fleet EV budget across chargers, with its own 60 s /
    # 500 W reallocation hysteresis in ``_ev_last_realloc_time`` /
    # ``_ev_prev_allocation``. It ran every solar cycle and its result
    # reached exactly one place — ``PerChargerContext.budget_w`` — which
    # nothing read. Two allocators for one concept, one of them invisible:
    # a contributor fixing a multi-charger allocation bug would have edited
    # this one, watched its unit tests pass, and changed nothing on the
    # hardware. The surviving allocator is ``decide`` subtracting
    # ``fleet.solar_committed_w``, accumulated per charger in the
    # coordinator's priority loop from each charger's actual decision.

    # Volatile per-device CONTROL state that must survive a device-object
    # rebuild (config edit / rediscovery re-registers a FRESH object for the
    # same device_id). Lost markers are how the deficit-LIFO killed a running
    # Tier-2 load 23 min early on PROD (2026-07-22: rediscovery at 22:15:14
    # wiped Heizband's _batt_overnight_forced; the LIFO exemption no longer
    # matched). Bug class 14 (rebuilt device loses accrued state) × #620.
    _VOLATILE_CONTROL_FIELDS = (
        "_offpeak_forced", "_offpeak_forced_date",
        "_batt_overnight_forced", "_batt_overnight_forced_date",
        "_last_activated", "_last_deactivated",   # anti-cycle windows
        "_observed_off_since", "_external_off_until",
        "_surplus_since",                          # activation debounce
        "_held_power",           # (#1067) a rating hold spans the rebuild
    )
    # _sem_owned is transplanted separately: only from an ACTIVE old object —
    # a stale False (reconciler cleared it while the entity flickered) must not
    # override adopt_if_running's re-own on the fresh object (ruflo M).

    def register_device(self, device: ControllableDevice) -> None:
        """Register a device for surplus control.

        Replacing an existing registration (same ``device_id``) transplants the
        volatile control state onto the new object — a rebuild must never reset
        force markers, anti-cycle timing, or ownership of a RUNNING load.
        """
        old = self._devices.get(device.device_id)
        if old is not None and old is not device:
            for f in self._VOLATILE_CONTROL_FIELDS:
                if hasattr(old, f) and hasattr(device, f):
                    setattr(device, f, getattr(old, f))
            # Belief: if the old object was ACTIVE and the fresh one defaults to
            # idle, carry the active state — the physical load is still on and
            # SEM is still driving it. Ownership travels with an active belief
            # only (see _VOLATILE_CONTROL_FIELDS note).
            if old.is_active:
                if not device.is_active:
                    device._status.state = old._status.state
                if hasattr(old, "_sem_owned"):
                    device._sem_owned = old._sem_owned
                    # (#847) Carry the COMMANDED half too. A rebuild (ED
                    # refresh, re-registration) replaces the object while
                    # the physical load runs; carrying ownership alone would
                    # land a SEM-STARTED load on the fresh object as merely
                    # "adopted", and the mode-Off release would then leave it
                    # running forever — class 17, instance 5, exactly the
                    # towel heater this transplant exists to prevent.
                    device._sem_commanded = getattr(
                        old, "_sem_commanded", False)
            if (getattr(old, "_offpeak_forced", False)
                    or getattr(old, "_batt_overnight_forced", False)):
                _LOGGER.info(
                    "Re-register %s: transplanted volatile control state "
                    "(offpeak=%s, overnight_batt=%s, active=%s)",
                    device.device_id,
                    getattr(old, "_offpeak_forced", False),
                    getattr(old, "_batt_overnight_forced", False),
                    device.is_active,
                )
        self._devices[device.device_id] = device
        device._controller = self  # Allow device to look up dependencies (#122)
        depends = getattr(device, 'depends_on', None) or "none"
        _LOGGER.info(
            "Registered device: %s (priority=%d, min=%dW, type=%s, depends_on=%s)",
            device.name, device.priority, device.min_power_threshold,
            device.device_type.value, depends,
        )

    def get_dependents(self, device_id: str) -> list:
        """Get all devices that depend on the given device (#122)."""
        return [d for d in self._devices.values()
                if device_id in getattr(d, 'depends_on', [])]

    # ``validate_dependencies`` lived here until #662. It was a cycle
    # detector with no production caller (only tests), and its walk
    # hard-coded ``dep_list[0]`` — so for a device requiring [a, b] with the
    # loop through ``b`` it followed the ``a``-chain, found nothing and
    # reported clean. A validator that can't see half the graph and that
    # nothing calls is not a safety net; it is a second, weaker
    # implementation of a concept the registry already owns correctly.
    #
    # Cycles are now prevented where they are created, not reported after
    # the fact: DeviceRegistry._dependency_would_cycle walks ALL parents
    # across BOTH persisted stores and rejects the write, on every path
    # (UI select, set_device_property, register_surplus_device), plus a
    # load-time sanitize for stores written before the guard existed.

    def unregister_device(self, device_id: str) -> None:
        """Remove a device from surplus control."""
        if device_id in self._devices:
            del self._devices[device_id]
            _LOGGER.info("Unregistered device: %s", device_id)

    def clear_devices(self) -> None:
        """Drop every registered device.

        Called from ``async_unload_entry`` so a HA-side reload doesn't
        leak the prior cycle's device registrations into the next setup.
        Pre-fix, reloads left the registered EV charger / heat pump /
        switch devices in ``self._devices`` — the new setup re-registered
        them on top, causing each reload to grow the dispatch list.
        """
        if self._devices:
            count = len(self._devices)
            self._devices.clear()
            _LOGGER.info("Cleared %d registered devices on unload", count)

    def detach_devices(self) -> List[ControllableDevice]:
        """Clear the registry and hand the devices back to the caller (#656).

        ``clear_devices()`` on its own is what stranded loads: unload dropped
        the references to devices SEM had switched ON, and nothing was left
        that could turn them off. Teardown needs both halves — the registry
        emptied (so a reload can't leak the prior cycle's registrations) AND
        something still holding the actuators, in case this unload turns out
        to be a removal rather than a reload.
        """
        devices = list(self._devices.values())
        self.clear_devices()
        return devices

    def get_device(self, device_id: str) -> Optional[ControllableDevice]:
        """Get a registered device by ID."""
        return self._devices.get(device_id)

    def get_devices_sorted(self) -> List[ControllableDevice]:
        """Get all devices sorted by priority (1=highest).

        Devices with managed_externally=True are excluded (e.g., EV charger
        during night mode when the coordinator manages it directly).
        """
        return sorted(
            [d for d in self._devices.values()
             if d.is_enabled and not d.managed_externally],
            key=lambda d: d.priority,
        )

    def active_surplus_draw_w(self) -> float:
        """Sum the current draw of the surplus devices this controller
        has activated (#508 W7).

        The coordinator builds a *feedback-free* true house surplus as
        signed grid + ``active_surplus_draw_w()`` (#1102: export minus the
        import, see ``solar_bounded_surplus``). Without the addback,
        every device the controller turns on shrinks the grid export it
        reads next cycle, so the surplus signal would chase its own tail
        and the device would oscillate. Adding back the controller's own
        active draw makes the input the surplus that WOULD exist if its
        devices were off — the stable quantity to allocate from.

        Externally-managed devices (the EV, driven by the decide/actuate
        path) are excluded — their draw is already reflected in grid
        export and must not be re-credited here.

        (#1102) So are loads the walk never debits: mode Off (the user's
        own, e.g. a monitored washer plug the belief sync sees running)
        and a load behind the operator's relay while it is on (#1021).
        Crediting them put their draw — and, once the pool saw the import,
        the import they cause — back on the table for every Solar-only load.
        """
        from ..devices.base import DeviceControlMode
        return sum(
            d.get_current_consumption()
            for d in self.get_devices_sorted()
            if d.is_active
            and d.control_mode != DeviceControlMode.OFF
            and getattr(d, "locked_by_operator", False) is not True
        )

    def grid_funded_draw_w(self) -> float:
        """(#620) Total draw of loads currently running on the cheap-hours GRID
        top-up (``_offpeak_forced``). Fed into ``BatteryView.grid_funded_load_w``
        so the battery discharge limit excludes them — the grid, not the
        battery, funds a "Finish overnight from: Grid" load. Tier-2
        (``_batt_overnight_forced``) loads are deliberately NOT counted: they
        run off the battery by design."""
        return sum(
            float(d.get_current_consumption() or 0.0)
            for d in self._devices.values()
            if d.is_active and getattr(d, "_offpeak_forced", False)
        )

    def _override_action(self, device) -> Optional[str]:
        """(#1321) This load's active one-off action (``skip``/``force``),
        or None. Only a Smart-mode (surplus) load acts on one; in any other
        mode the override is held but read as nothing."""
        rec = self._load_overrides.get(getattr(device, "device_id", None))
        action = rec.get("action") if isinstance(rec, dict) else None
        if action not in LOAD_OVERRIDE_ACTIONS:
            return None
        if getattr(device, "control_mode", None) != DeviceControlMode.SURPLUS:
            return None
        return action

    def load_override_status(self, device_id: str) -> Optional[Dict[str, Any]]:
        """(#1321) ``{"action", "until"}`` for the device map, or None."""
        rec = self._load_overrides.get(device_id)
        return dict(rec) if isinstance(rec, dict) else None

    def _desired_intents(self, devices, *, remaining_surplus, reclaim_w,
                         battery_priority, price_level,
                         peak_freeze, peak_shed, peak_shed_all):
        """(desired-state, phase 3) The management-layer decision for the whole
        load set: the priority walk → one ``LoadIntent`` per device. Pure of
        actuation (``reconcile_load`` applies them); the shared cycle context
        (``self._batt_*`` / ``self._tier1_budget_left``) is already stamped by
        ``update()``. (#1335) Layer 2: it writes no device state but the
        Tier-1 bookkeeping (what the pack funds per load, #885)."""
        soc_above = (self._batt_soc is not None
                     and self._batt_soc > self._batt_reserve_soc)

        # Peak-shed targets: reverse priority; EMERGENCY sheds all, SHEDDING
        # one — (#1335) one that can actually stop, as the old pass skipped a
        # load its minimum run still holds and shed the next one up.
        shed = set()
        if peak_shed:
            for d in reversed(devices):
                if d.control_mode == DeviceControlMode.SURPLUS and d.is_active:
                    if not peak_shed_all and d.can_deactivate() is False:
                        continue
                    shed.add(d.device_id)
                    if not peak_shed_all:
                        break
        # (#1048) …and every load the phase guard took for its phase.
        phase = {d.device_id for d in devices if _phase_shed(d) and d.is_active}

        now = datetime.now()
        remaining = float(remaining_surplus)
        reclaim_handed = False
        intents = {}
        # (#1102) What the walk took from the pool for each load: the deficit
        # stop below gives back exactly this when it stops one.
        spend: Dict[str, float] = {}
        for device in devices:
            did = device.device_id
            # (#576) hand the reclaim back at the battery's slot
            if (not reclaim_handed and battery_priority is not None
                    and reclaim_w > 0 and device.priority >= battery_priority):
                remaining = reclaim_handed_back(remaining, reclaim_w)
                reclaim_handed = True
            tier1 = self._tier1_headroom_w(device)
            intent = compute_load_intent(
                device, remaining_surplus_w=remaining, tier1_headroom_w=tier1,
                # (#812) the device's own tariff when it has one
                price_is_cheap=is_cheap_name(
                    device_price_level(device, price_level)),
                peak_freeze=peak_freeze,
                is_night=getattr(self, "_is_night_cycle", True),
                # (#953) same cycle context as is_night — stamped by update()
                daylight_remaining_s=getattr(
                    self, "_daylight_remaining_s", None),
                is_shed_target=did in shed or did in phase,
                shed_code=(RC.LOAD_PEAK_SHED if did in shed
                           else RC.LOAD_PHASE_GUARD),
                soc_above_reserve=soc_above,
                # (#638 G4) the joint plan's per-device window verdict this
                # cycle; absent from the dict = the plan has no say.
                plan=self._plan_windows.get(did) or NO_OPINION,
                # (#864) a grid start must fit the billing slot
                grid_start_fits=self._grid_start_fits(device),
                # (#1321) the user's one-off on this load, if any
                override=self._override_action(device),
                # (#1323) the step-down's two facts: this load's price level
                # and what the house buys now (0 when the meter is unread)
                price_is_expensive=is_expensive_name(
                    device_price_level(device, price_level)),
                buying_w=(max(0.0, float(getattr(self, "_grid_import_w", 0.0) or 0.0))
                          if getattr(self, "_grid_import_known", True) else 0.0))
            intents[did] = intent
            spend[did] = debit = self._walk_debit(
                device, intent, remaining=remaining, now=now)
            remaining -= debit

        # (#1335, D2) The deficit stop — the whole-set rule the old passes
        # ran as their LIFO: once the walk is more than 100 W short, stop sun
        # loads from the LOWEST priority up until it is not. A paid run, an
        # own run and the comfort floor need no sun and are not the sun's to
        # stop; a load its minimum run holds is passed over (the next one up
        # frees the power instead). Cancelling a start costs nothing.
        if remaining < -DEFAULT_MIN_SURPLUS_CHANGE:
            for device in reversed(devices):
                if remaining >= 0:
                    break
                did = device.device_id
                if not self._sun_run(device, intents[did]):
                    continue
                charged = spend.get(did, 0.0)
                if device.is_active and device.can_deactivate() is False:
                    if charged > 0.0:
                        self._say_min_run_holds(device, intents)
                    continue
                if charged <= 0.0:
                    continue
                remaining += self._stop_short(device, intents, spend)

        # (#1335) No sun at all: SOLAR PRODUCTION itself reads next to
        # nothing (``_no_sun``: two of the last three readings, and a live
        # reading now) — not the pool, which is the surplus less the export
        # margin and reads 0 at noon whenever the house takes the sun or the
        # inverter does not export. A load SEM started on the sun alone has
        # no reason left to run and stops, whatever it draws right now. The
        # 100 W band above is against flapping while there IS sun; alone it
        # kept a switch whose power sensor reads 0 W on through the night.
        # Not touched: a load the user switched on (the band rule above is
        # all it gets, as before), a paid run, the comfort floor, an own
        # run, the battery's Tier-1 share, a minimum run. With any sun, or
        # with no solar reading, nothing changes.
        if self._no_sun():
            for device in reversed(devices):
                did = device.device_id
                intent = intents[did]
                if (not device.is_active and intent.on
                        and intent.source == "solar"
                        and self._sun_run(device, intent)):
                    # …and nothing starts on a pool that is only the
                    # smoothing's memory of the day (the pool lags the sun
                    # by a few cycles; the stop above would be undone).
                    intents[did] = LoadIntent(
                        False, 0.0, None, "no sun left", RC.LOAD_NO_SOURCE)
                    continue
                if not (device.is_active and sem_started(device)
                        and intent.source == "solar"
                        and self._sun_run(device, intent)):
                    continue
                if device.can_deactivate() is False:
                    self._say_min_run_holds(device, intents)
                    continue
                self._stop_short(device, intents, spend, reason="no sun left")
        return intents

    @staticmethod
    def _say_min_run_holds(device, intents) -> None:
        """(#1335) A stop for a short pool is due, and the load's minimum
        run time holds it on. The intent stays ON with the same power,
        source and command — the walk's books do not change — but it says
        so: "solar: running on 0W" read as running on sun with no sun."""
        did = device.device_id
        intents[did] = replace(
            intents[did],
            reason="minimum run time holds it — not enough sun",
            code=RC.LOAD_MIN_RUN_HOLD)

    def _no_sun(self) -> bool:
        """(#1335) Is solar production itself gone? True when the reading is
        live this cycle and at least two of the last three cycles read
        ``NO_SUN_W`` or less (the surplus filter's own two-of-three rule: one
        dropout is not dusk). No reading, or fewer than three cycles: False —
        unknown is not night."""
        samples = getattr(self, "_solar_samples", None) or []
        if len(samples) < 3 or samples[-1] is None:
            return False
        if samples[-1] > NO_SUN_W:
            # the sun is back this cycle: two dark cycles behind it are a
            # dropout, not dusk
            return False
        return sum(1 for w in samples if w is not None and w <= NO_SUN_W) >= 2

    def _stop_short(self, device, intents, spend, *,
                    reason: str = "not enough sun") -> float:
        """(#1335) Turn one sun load's intent off for a short pool, with
        what requires it (#122, D6). Returns the watts the walk gets back."""
        did = device.device_id
        intents[did] = LoadIntent(False, 0.0, None, reason, RC.LOAD_SURPLUS_SHORT)
        freed = float(spend.get(did, 0.0))
        name = getattr(device, "name", did)
        for dep in self.get_dependents(did):
            dep_intent = intents.get(dep.device_id)
            if (dep_intent is None or not dep_intent.on
                    or dep_intent.source is None
                    or not dep.is_active
                    or dep.can_deactivate() is False):
                continue
            intents[dep.device_id] = LoadIntent(
                False, 0.0, None, f"{name} stopped", RC.LOAD_DEPENDENCY)
            freed += float(spend.get(dep.device_id, 0.0))
        return freed

    @staticmethod
    def _sun_run(device, intent: "LoadIntent") -> bool:
        """(#1335) A run the deficit stop may end: SURPLUS mode, on the sun
        (or the Tier-1 assist), not the comfort floor or a deadline."""
        return (device.control_mode == DeviceControlMode.SURPLUS
                and intent.on
                and intent.source in ("solar", "tier1_battery")
                and intent.code not in (RC.LOAD_COMFORT_FLOOR, RC.LOAD_DEADLINE)
                and getattr(device, "runs_without_surplus", False) is not True)

    def _walk_debit(self, device, intent: "LoadIntent", *, remaining: float,
                    now: datetime) -> float:
        """(#1335) What one load takes from the walk's pool this cycle.

        * a sun run: what it is expected to draw, less the battery's Tier-1
          share of the shortfall (that share leaves the pack, #885 records
          it on the device and the cycle's budget);
        * a paid run, an own run, the comfort floor: the sun that is left,
          no more — it buys the rest by design, and taking it all would push
          the walk negative and stop a sun load AHEAD of it (#1102);
        * a load that stays on without being SEM's to re-tune (peak-only,
          or a stop its minimum run holds): its measured draw — it sits in
          the pool's add-back, so skipping it would give its watts away;
        * a start that cannot happen this cycle: nothing.
        """
        active = bool(getattr(device, "is_active", False))
        if intent.on and not active and _start_refused(device, now):
            return 0.0
        left = max(0.0, float(remaining))
        if intent.on and intent.source in ("solar", "tier1_battery"):
            draw = max(0.0, float(intent.power_w or 0.0))
            headroom = self._tier1_headroom_w(device)
            if headroom > 0:
                assist = min(headroom, max(0.0, draw - left))
                # (#885) What the PACK funds for this device, so the next
                # cycle's charger loop reserves the measured number.
                device._tier1_batt_w = assist
                self._tier1_budget_left = max(0.0, self._tier1_budget_left - assist)
                return draw - assist
            return draw
        if intent.on and intent.source is not None:
            return min(max(0.0, float(intent.power_w or 0.0)), left)
        if not active:
            return 0.0
        if (device.control_mode == DeviceControlMode.OFF
                or getattr(device, "locked_by_operator", False) is True):
            return 0.0
        if intent.on or device.can_deactivate() is False:
            held_w = max(0.0, float(device.get_current_consumption() or 0.0))
            if (getattr(device, "_offpeak_forced", False) is True
                    or getattr(device, "_batt_overnight_forced", False) is True):
                return min(held_w, left)
            return held_w
        return 0.0

    def _grid_start_fits(self, device) -> bool:
        """(#864) Does a grid start at this load's threshold fit the live
        15-min billing slot? No ceiling configured = it fits."""
        allowed = getattr(self, "_peak_slot_allowed_w", None)
        if allowed is None:
            return True
        from .peak_guard import clamp_import_command
        need = float(getattr(device, "min_power_threshold", 0.0) or 0.0)
        fit_w, clamped = clamp_import_command(
            need, allowed, float(getattr(self, "_grid_import_w", 0.0) or 0.0),
            grid_import_known=bool(getattr(self, "_grid_import_known", True)))
        return not (clamped and fit_w < need)

    async def _finish_via_desired_state(self, devices, *, remaining_surplus,
            reclaim_w, battery_priority, price_level, peak_state, peak_freeze,
            peak_shed, peak_shed_all, distributable, available_power_w,
            observer=False):
        """(desired-state, phase 3) Compute intents, reconcile every load (the
        single actuator), and assemble the same ``SurplusAllocationData`` the
        old imperative ``update()`` returned.

        ``observer=True`` runs the exact same decision, but the reconcile step
        only logs what it would command — the read-only path for observer mode."""
        intents = self._desired_intents(
            devices, remaining_surplus=remaining_surplus, reclaim_w=reclaim_w,
            battery_priority=battery_priority, price_level=price_level,
            peak_freeze=peak_freeze, peak_shed=peak_shed,
            peak_shed_all=peak_shed_all)
        allocations: List[SurplusAllocation] = []
        active_count = 0
        for device in devices:
            intent = intents[device.device_id]
            was_on = bool(device.is_active)
            consumed = float(await reconcile_load(
                device, intent, observer=observer, controller=self) or 0.0)
            # A start that took this cycle counts what ``activate`` returned —
            # the device's own meter has not seen it yet (the old passes did
            # the same).
            started = not observer and intent.on and not was_on and consumed > 0
            active = bool(device.is_active) or started
            if started:
                consumption = allocated = consumed
            else:
                consumption = device.get_current_consumption() if active else 0.0
                allocated = device.status.allocated_power_w if active else 0.0
            if active:
                active_count += 1
            # Off is the user's, a relay-locked load the operator's: neither
            # is SEM's to allocate (the old passes left both out too)
            if (device.control_mode == DeviceControlMode.OFF
                    or getattr(device, "is_enabled", True) is False
                    or getattr(device, "locked_by_operator", False) is True):
                continue
            allocations.append(SurplusAllocation(
                device_id=device.device_id, device_name=device.name,
                priority=device.priority,
                allocated_watts=allocated,
                actual_consumption_watts=consumption,
                state=DeviceState.ACTIVE.value if active else DeviceState.IDLE.value))
        total_allocated = sum(a.actual_consumption_watts for a in allocations)
        self._allocation_data = SurplusAllocationData(
            total_surplus_w=available_power_w,
            distributable_surplus_w=distributable,
            regulation_offset_w=self.regulation_offset,
            allocated_w=total_allocated,
            unallocated_w=max(0.0, distributable - total_allocated),
            active_devices=active_count, total_devices=len(self._devices),
            allocations=allocations, last_update=dt_util.now())
        return self._allocation_data

    async def update(
        self,
        available_power_w: float,
        price_level: Optional[str] = None,
        peak_state: Optional[str] = None,
        reclaim_w: float = 0.0,
        battery_priority: Optional[int] = None,
        # (#620) battery context for the two device battery tiers. Defaults
        # make the whole feature INERT: with no battery data and both
        # per-device flags off (their default), _tier1/_tier2 are no-ops and
        # allocation is byte-identical to pre-#620.
        battery_soc: Optional[float] = None,
        battery_buffer_soc: float = 100.0,
        battery_reserve_soc: float = 100.0,
        battery_assist_budget_w: float = 0.0,
        # (#1114) the budget for a load ranked above the battery (its gate
        # counts the reclaim). None = the same as ``battery_assist_budget_w``.
        battery_assist_budget_above_w: Optional[float] = None,
        observer: bool = False,
        is_night: bool = True,
        # (#638 G4) device_id → True/False window verdicts from the joint
        # energy plan; None/empty = no trusted plan → today's behaviour.
        plan_windows: Optional[dict] = None,
        # (#864) the live 15-min slot allowance + current import — the
        # security layer's preventive gate on grid-backed force starts.
        # None allowance = no ceiling configured / guard off.
        peak_slot_allowed_w: Optional[float] = None,
        grid_import_w: float = 0.0,
        # (#925 audit) False when the grid sensor was unreadable this
        # cycle — grid_import_w is then a fallback, not a measurement.
        grid_import_known: bool = True,
        # (#871, arc #921) the grid-export sink is CLOSED this cycle: the
        # "always export a little" regulation buffer is the one threshold that
        # exists to FEED the meter, so it relaxes to zero. Safety gates (peak
        # guard, reserve SOC, stop-war) are untouched.
        grid_closed: bool = False,
        # (#953) Seconds of daylight left today, from the coordinator's
        # TimeManager. None = no sun data; the cheap-hours grid top-up then
        # keeps its pre-#953 behaviour (unknown is not a claim about the sun).
        daylight_remaining_s: Optional[float] = None,
        # (#1321) device_id → {"action", "until"}: the active one-off
        # overrides. None/empty = none set → behaviour unchanged.
        load_overrides: Optional[dict] = None,
        # (#1335) Solar production right now, W. None = no live reading
        # (the default, and a dark solar sensor): the no-sun stop never
        # fires on it.
        solar_w: Optional[float] = None,
    ) -> SurplusAllocationData:
        """Run the surplus allocation algorithm.

        This is called every coordinator update cycle (~10s).

        Args:
            available_power_w: Total available surplus power. Since #508 W7
                the coordinator passes the feedback-free TRUE house surplus
                (signed grid + this controller's own active draw, #1102), not the
                EV charging budget — heat pump / hot water boost on what the
                house is actually exporting after the EV and battery take
                their share.
            price_level: Current price level (cheap/normal/expensive) for price-responsive mode.
            peak_state: Current ``LoadManagementState`` (#508 W2). When the
                grid-import peak is at risk (WARNING / SHEDDING / EMERGENCY)
                the controller stops ADDING discretionary load, and on
                SHEDDING / EMERGENCY proactively backs its own active
                devices off by reverse priority — so it complements the
                load manager instead of re-activating, next cycle, whatever
                the load manager just shed. ``None`` = no peak awareness
                (legacy behaviour).

        Returns:
            SurplusAllocationData with allocation results.
        """
        # (arc) Reconcile belief vs observed reality BEFORE allocating, so a
        # load that silently dropped off (failed turn_on) or was toggled by the
        # user isn't counted as active / credited runtime this cycle, and SEM
        # doesn't immediately re-fight a manual off. Scoped to on/off loads
        # (switch + climate); EV / heat-pump / setpoint keep their own handling.
        # NB: reconcile_all is belief-sync, not actuation — it corrects SEM's
        # view of reality (is_active, _sem_owned, off-grace) and NEVER issues a
        # service call. It runs in observer mode too (permitted + wanted): on
        # shared hardware the real decision needs accurate belief state.
        from ..devices.base import DeviceType
        from .device_reconciler import reconcile_all
        reconcile_all([
            d for d in self._devices.values()
            if getattr(d, "device_type", None) in (DeviceType.SWITCH, DeviceType.CLIMATE)
        ])
        # (#812) A device with its own tariff gates on its own price level
        # this cycle (``device_price_level``); the rest read ``price_level``.
        self.device_tariffs.stamp(self._devices.values())

        # #508 W2 — peak posture. WARNING freezes new activation (don't add
        # load while the peak is climbing); SHEDDING/EMERGENCY additionally
        # sheds the controller's own discretionary devices. EMERGENCY sheds
        # all of them at once; SHEDDING sheds gently (one per cycle) so the
        # combined load-manager + surplus back-off doesn't overshoot.
        from ..const import LoadManagementState
        # (#620) stash the battery context for the tier helpers this cycle.
        self._batt_soc = battery_soc
        self._batt_buffer_soc = battery_buffer_soc
        self._batt_reserve_soc = battery_reserve_soc
        self._batt_assist_budget_w = max(0.0, float(battery_assist_budget_w or 0.0))
        self._batt_assist_budget_above_w = (
            None if battery_assist_budget_above_w is None
            else max(0.0, float(battery_assist_budget_above_w)))
        self._batt_priority = battery_priority
        # (#633) "Finish overnight from: Battery" is a NIGHT source — layer
        # 1's Tier-2 clause gates on this cycle flag.
        self._is_night_cycle = bool(is_night)
        # (#953) the free window's remaining length — the "finish" gate on
        # the cheap-hours grid top-up, read by layer 1. Stamped here so every
        # load reads one value per cycle.
        self._daylight_remaining_s = (
            None if daylight_remaining_s is None
            else max(0.0, float(daylight_remaining_s)))
        # (#638 G4) stamp this cycle's joint-plan window verdicts for the
        # intent path.
        self._plan_windows = dict(plan_windows or {})
        # (#1321) this cycle's one-off overrides, read by layer 1 (clause 3e)
        self._load_overrides = {
            str(k): dict(v) for k, v in (load_overrides or {}).items()
            if isinstance(v, dict)}
        # (#864/#1335) the billing slot a grid start must fit, for layer 2
        self._peak_slot_allowed_w = peak_slot_allowed_w
        self._grid_import_w = float(grid_import_w or 0.0)
        self._grid_import_known = bool(grid_import_known)
        # (#766) Belief follows the switch, every cycle — the per-cycle twin
        # of adopt_if_running. Without it, a switch turned ON outside SEM's
        # own activate() (an external actuator, a user, a box self-start)
        # stays invisible: never seen active, never deactivated, runtime
        # never accrued (the N2 pool ran 00:00→07:50 on an idle belief).
        for _dev in self._devices.values():
            try:
                _sync = getattr(_dev, "sync_belief_to_observation", None)
                if callable(_sync):
                    _sync()
            except Exception:  # noqa: BLE001 — one device never stalls the walk
                # (#914) the sync also carries the restart adoption of a
                # setpoint tank / SG-Ready pump — a failure leaves a trace.
                _LOGGER.debug(
                    "Belief sync skipped for %s",
                    getattr(_dev, "device_id", "?"), exc_info=True,
                )
                continue
        peak_freeze = peak_state in (
            LoadManagementState.WARNING,
            LoadManagementState.SHEDDING,
            LoadManagementState.EMERGENCY,
        )
        peak_shed = peak_state in (
            LoadManagementState.SHEDDING,
            LoadManagementState.EMERGENCY,
        )
        peak_shed_all = peak_state == LoadManagementState.EMERGENCY
        # (arc Phase 4) Median-of-3 pre-filter: a SINGLE-cycle spike/dropout
        # (inverter glitch, sensor blip) still moves the EMA below by 30% of its
        # magnitude — enough to flap a marginal load. The median passes only
        # values seen in ≥2 of the last 3 cycles, so one bad sample never
        # reaches the EMA at all. Real trends (2+ consistent cycles) pass with
        # one cycle of extra latency, which the EMA's own inertia already dwarfs.
        self._solar_samples.append(
            float(solar_w) if isinstance(solar_w, (int, float))
            and not isinstance(solar_w, bool) else None)
        del self._solar_samples[:-3]
        self._surplus_samples.append(available_power_w)
        if len(self._surplus_samples) > 3:
            self._surplus_samples.pop(0)
        if len(self._surplus_samples) == 3:
            filtered_w = sorted(self._surplus_samples)[1]
        else:
            filtered_w = available_power_w  # warm-up (first 2 cycles): raw

        # EMA smoothing to reduce oscillation from cloud transients
        if self._smoothed_surplus is None:
            self._smoothed_surplus = filtered_w
        else:
            self._smoothed_surplus = 0.3 * filtered_w + 0.7 * self._smoothed_surplus

        # Apply regulation offset — none while the meter is closed (#871)
        _offset = 0.0 if grid_closed else self.regulation_offset
        distributable = self._smoothed_surplus - _offset
        self._grid_closed = bool(grid_closed)
        self._last_surplus = distributable

        # Feed-in/export limitation: add virtual surplus when approaching limit
        if self.max_export_w > 0 and self._smoothed_surplus > self.max_export_w:
            excess_export = self._smoothed_surplus - self.max_export_w
            distributable += excess_export  # Force-route excess to devices

        # Price-responsive adjustments
        if self._price_responsive_mode and price_level:
            distributable = self._apply_price_adjustment(distributable, price_level)

        devices = self.get_devices_sorted()
        # (#1335) …plus a load that was disabled while a run SEM started is
        # still going: layer 1 ends that run once. Without it nothing would
        # ever visit the load again. Externally managed devices (the EV
        # chargers) are never added: their whole lifecycle is ev_control's.
        devices += sorted(
            (d for d in self._devices.values()
             if not d.is_enabled and not d.managed_externally
             and ((d.is_active and sem_started(d))
                  # (#1323) …or it is stepped down: layer 3 takes that back
                  or getattr(d, "is_stepped_down", False) is True)),
            key=lambda d: d.priority)
        # (#576) The home battery sits at ``battery_priority`` in this walk.
        # ``reclaim_w`` (the power that would charge it) is offered at the TOP;
        # when the walk crosses the battery's slot it is handed back to the
        # battery, so loads ABOVE the battery reclaim it and loads BELOW see
        # only the export surplus.
        remaining_surplus = distributable + max(0.0, reclaim_w)
        # (#620) Tier-1 running budget — the battery can only supply its assist
        # budget ONCE, not once per device. Decremented as each battery-assist
        # load draws from it, so N loads can't each claim the full budget.
        self._tier1_budget_left = max(
            self._batt_assist_budget_w, self._batt_assist_budget_above_w or 0.0)
        # (#885) Clear each device's recorded battery draw before the walk
        # re-measures it. This is what the per-charger reservation reads for
        # loads that are ALREADY RUNNING, so a stale value would keep
        # reserving for a device that has since stopped.
        for _d in self._devices.values():
            _d._tier1_batt_w = 0.0

        # (#1335) The one engine: layer 1 (``compute_load_intent``) and
        # layer 2 (``_desired_intents``) decide, layer 3 (``reconcile_load``)
        # switches — on every install. Observer mode is one branch in layer 3:
        # the same decision runs against live sensors and only logs what it
        # would command.
        return await self._finish_via_desired_state(
            devices, remaining_surplus=remaining_surplus, reclaim_w=reclaim_w,
            battery_priority=battery_priority, price_level=price_level,
            peak_state=peak_state, peak_freeze=peak_freeze,
            peak_shed=peak_shed, peak_shed_all=peak_shed_all,
            distributable=distributable, available_power_w=available_power_w,
            observer=observer,
        )

    def _tier1_headroom_w(self, device) -> float:
        """(#620) Tier 1 daytime battery-assist headroom for one device (W).

        Non-zero ONLY when the device opted into ``battery_assist_enabled``
        (the "Solar + battery" mode) AND the battery is above the Buffer SoC.
        Returns the assist budget the coordinator passed (the same
        surplus-above-buffer budget the EV assist uses, #537/#545) — so the
        device may activate on surplus + battery down to the buffer, never
        below it. Everything else → 0 (inert)."""
        if not getattr(device, "battery_assist_enabled", False):
            return 0.0
        # (#688) Past its daily floor the device has nothing left to guarantee,
        # so the battery stops paying for it — free surplus only from here to
        # the Max cap. Single point: layers 1 and 2 read their headroom
        # through here.
        if getattr(device, "daily_targets_met", False):
            return 0.0
        soc = self._batt_soc
        if soc is None or soc <= self._batt_buffer_soc:
            return 0.0
        # Running budget: shrinks as earlier (higher-priority) battery-assist
        # loads claim it this cycle, so the battery isn't multi-spent.
        return max(0.0, min(self._tier1_budget_for(device), self._tier1_budget_left))

    def _tier1_budget_for(self, device) -> float:
        """(#1114) The Tier-1 budget this device's Solar Gate opens: a load
        ranked above the battery counts the charge power it may reclaim,
        the way a charger above the battery does."""
        above = getattr(self, "_batt_assist_budget_above_w", None)
        bprio = getattr(self, "_batt_priority", None)
        if (above is not None and bprio is not None
                and int(getattr(device, "priority", 0)) < int(bprio)):
            return above
        return self._batt_assist_budget_w

    def _apply_price_adjustment(self, distributable: float, price_level: str) -> float:
        """(#953) Damp the distributable surplus for the price level.

        One line, and deliberately so: the whole rule lives in the pure
        ``price_damped_pool`` — a price signal lowers the pool or leaves it
        alone, and can never raise it above the sun the coordinator already
        bounded it by. See that function for what the virtual surplus did.
        """
        return price_damped_pool(distributable, price_level)

    async def deactivate_all(self, reason: str = "emergency") -> None:
        """Deactivate all devices (emergency stop, or SEM going away).

        Iterates ``self._devices`` rather than ``get_devices_sorted()`` (#656).
        That view hides devices that are ``is_enabled=False`` or
        ``managed_externally`` — both of which can be latched ON right now, and
        a teardown that skips them leaves exactly the strand this exists to
        prevent. Lowest priority first, so the log reads like a normal shed.

        One device failing must not abort the rest: this runs on the
        unload/remove path, where the alternative to a best-effort loop is an
        unattended heating device left commanded on by an integration that is
        on its way out.

        ``reason`` only labels the log line, so an emergency stop doesn't read
        as a teardown in the journal.
        """
        await deactivate_devices(self._devices.values(), reason)
