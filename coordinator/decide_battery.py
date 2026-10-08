"""Pure ``decide_battery(view) → BatteryDecision`` (Group B Step 3).

One pure function per cycle per battery. Replaces the branching
in the deleted ``BatteryProtectionMixin`` (#624) + :meth:`BatteryChargeScheduler.update`
that pre-v1.7.0 spread across two modules.

Pure: no ``self``, no HA calls. Input :class:`BatteryView`, output
:class:`BatteryDecision`.

Decision tree (precedence top-down):

1. FORCE_CHARGE — scheduler decided SCHEDULED and we're in the
   charge window.
2. STOP_FORCE_CHARGE — scheduler decided TARGET_REACHED / NOT_NEEDED /
   IDLE but the adapter is still in FORCE_CHARGE intent. (#1066) "Still"
   is ``view.sem_forced_charge`` / ``sem_forced_discharge``: once the stop
   has landed the verdict is no command at all, and the branches below
   decide. A forced op SEM started and has not seen stop is stopped before
   any NORMAL / LIMIT_DISCHARGE (``_stop_what_sem_started``).
3. LIMIT_DISCHARGE (EV) — EV charging AND either solar surplus is below
   the ``battery_assist_min_surplus`` gate OR battery SoC is below the
   ``battery_buffer_soc`` floor OR this battery may not feed the car
   (``may_assist_ev`` off, #1066) (any mode/time); clamp battery to home
   consumption (1:1 protection) so grid+solar fund the car. Grid-funded
   cheap-hours load draw is excluded from the home budget.
4. LIMIT_DISCHARGE (grid-funded loads, #620) — cheap-hours top-up loads
   ("Finish overnight from: Grid") are running; clamp battery to
   home − grid_funded so the grid, not the battery, feeds them.
5. NORMAL — default.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from .charger_types import BatteryDecision, BatteryIntent
from .peak_guard import cover_for_peak_w
from ..consts.battery_modes import arbitrage_allowed_for_mode
from ..consts.battery_permissions import effective_permissions, may_assist_ev

if TYPE_CHECKING:  # pragma: no cover
    from .charger_types import BatteryView

_LOGGER = logging.getLogger(__name__)


#: The scheduler states that mean "no forced op wanted" — each one answered
#: with a STOP, and only while its direction may still run (#1066).
_SCHEDULER_STOP_STATES = ("target_reached", "not_needed", "idle", "not_profitable")


def _flag(value):
    """A tri-state flag as SEM wrote it: True / False, else unknown (None)."""
    return value if isinstance(value, bool) else None


def forced_ops(adapter) -> "tuple":
    """(#1066) ``(charge, discharge)`` — what SEM knows about a forced op on
    this battery: ``None`` unknown, ``True`` started and not stopped,
    ``False`` stopped.

    The scheduler's stop verdicts (idle, not needed, outside the block…) are
    there on EVERY cycle the night scheduler is on — it never has no verdict.
    They were returned before the protection branches, so with the scheduler
    on the EV clamp, the #620 grid-funded clamp, the #879 house hold and the
    #892 morning window could never run: @RienduPre's evening read
    ``intent=stop_force_charge`` while 2.3 kW went from the pack into the car.

    A stop is a command only while there is something to stop. The flags are
    kept per direction by ``actuate_battery`` from what LANDED (a stop routed
    as a discharge stop does not end a switch-based forced charge — review).
    Huawei's own ``_forcible_*`` flags count as started too, as #757 asks
    them. No adapter → unknown: the old precedence.
    """
    if adapter is None:
        return None, None
    charge = _flag(getattr(adapter, "_sem_forced_charge", None))
    discharge = _flag(getattr(adapter, "_sem_forced_discharge", None))
    if getattr(adapter, "_forcible_charging", False) is True:
        charge = True
    if getattr(adapter, "_forcible_discharging", False) is True:
        discharge = True
    return charge, discharge


def stop_misses(adapter) -> int:
    """(#1066) Cycles in a row a stop has not landed (``actuate_battery``)."""
    v = getattr(adapter, "_sem_stop_misses", 0) if adapter is not None else 0
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


#: (#1066) Stop tries before protection is let through every other cycle.
#: Three, as the #840 strikes: a dropped write is retried, a stop that can
#: never land does not hold every protection branch off for good.
STOP_FIRST_TRIES = 3


def _stop_what_sem_started(view, decision: BatteryDecision) -> BatteryDecision:
    """(#1066) A forced op SEM started and has not seen stop is stopped
    before NORMAL or LIMIT_DISCHARGE — whichever branch asked for them.

    Before this the scheduler's every-cycle stop verdict was the only thing
    that ended one, and it was also what starved the protection branches.
    Only ``True`` counts here: an unknown flag never sends a stop on an
    install whose scheduler is off, so those decide exactly as before.

    A stop that does not land (a refusing register, a stop service that
    raises) is retried — but after ``STOP_FIRST_TRIES`` the protection goes
    out every other cycle (review round 2: develop's NORMAL / LIMIT wrote the
    limit even when their zero-write failed, so stop-only was worse there).
    With both directions open the stops take turns, discharge first: a sale
    left running empties the pack.
    """
    if decision.intent not in (BatteryIntent.NORMAL, BatteryIntent.LIMIT_DISCHARGE):
        return decision
    charge = getattr(view, "sem_forced_charge", None) is True
    discharge = getattr(view, "sem_forced_discharge", None) is True
    if not (charge or discharge):
        return decision
    m = int(getattr(view, "sem_stop_misses", 0) or 0)
    if m >= STOP_FIRST_TRIES and m % 2 == 1:
        return BatteryDecision(
            battery_id=decision.battery_id, intent=decision.intent,
            discharge_limit_w=decision.discharge_limit_w,
            # CAUSE: `m` is `view.sem_stop_misses` — the count actuate_battery
            # keeps of stops whose landing it did not see (`_note_forced_op`).
            reason=(f"{decision.reason} (a stop SEM sent has not landed in "
                    f"{m} cycles — it is retried every other cycle)"),
        )
    if charge and discharge:
        charge = (m // 2) % 2 == 1
    if charge:
        return BatteryDecision(
            battery_id=decision.battery_id,
            intent=BatteryIntent.STOP_FORCE_CHARGE,
            # CAUSE: `charge` is `view.sem_forced_charge is True` — a forced
            # charge landed and no charge stop has landed since.
            reason=("a forced charge SEM started has not been seen to stop "
                    f"— stopping it before {decision.intent.value}"),
        )
    return BatteryDecision(
        battery_id=decision.battery_id,
        intent=BatteryIntent.STOP_FORCE_DISCHARGE,
        # CAUSE: `discharge` is `view.sem_forced_discharge is True` — a sale
        # landed and no discharge stop has landed since.
        reason=("a forced discharge SEM started has not been seen to stop "
                f"— stopping it before {decision.intent.value}"),
    )


def effective_battery_count(pbcs: "list[dict]") -> int:
    """The divisor for the per-battery LIMIT_DISCHARGE home split (#691).

    #531 introduced the split so N batteries each told to inject the FULL
    home load don't over-inject N×. But the divisor must count CONSUMERS
    of the home budget, not configured rows:

    - a ``mode=off`` battery is hands-off (``decide_battery`` short-
      circuits to OFF before any command) — it never receives the clamp,
      so it must not eat a share. Live #691: 2 configured, 1 off, home
      ≈1 kW → the one controlled battery was limited to 500 W and the
      grid imported the other half all evening.
    - batteries sharing ONE discharge-limit entity (SolarEdge's inverter-
      level Storage Discharge Limit; any multi-battery install without
      per-battery ``battery_discharge_control_entities``, where every
      unit falls back to the same global key) are one actuation surface:
      a single write governs the whole bank, so together they are ONE
      consumer with the full budget. Distinct entities keep the #531
      split. A battery with no discharge-limit entity at all counts
      individually (unknown surface — today's behaviour).

    Takes the per-battery config dicts (``_per_battery_config`` output,
    fleet order). Returns at least 1.
    """
    surfaces: set[str] = set()
    unknown = 0
    for pbc in pbcs:
        if str(pbc.get("battery_mode", "auto") or "auto").lower() == "off":
            continue
        ent = pbc.get("battery_discharge_control_entity")
        if ent:
            surfaces.add(str(ent))
        else:
            unknown += 1
    return max(1, len(surfaces) + unknown)


def house_load_is_measured(fleet) -> bool:
    """Is this cycle's ``home_consumption_w`` a measurement? (#1003)

    It is the energy balance's RESIDUAL, not a sensor, so it stops being one
    in two ways and the peak floor has to ask about both:

    * a dark steering read (#818) — solar, grid or battery. The reader's 0.0
      fallback drops that term, and during a house-sink hold the battery term
      is zero anyway and a cheap hour is usually dark, so a dark grid read
      collapses the whole balance to nothing;
    * a balance that did not close (#660) — ``home_residual_clamped_w`` above
      zero means the inputs contradict each other and the figure was clamped
      up to zero. A grid sign the autodetect got wrong reads exactly so, and
      is READABLE, so the first test alone says nothing.

    Both under-state the house, which is the direction that lets a hold sit
    through a breach — so neither may be sized on.
    """
    return (not bool(getattr(fleet, "inputs_degraded", False))
            and float(getattr(fleet, "home_residual_clamped_w", 0.0) or 0.0) <= 0.0)


def reserve_stops_peak_cover(view: "BatteryView"):
    """(#1069) Why this pack may not cover a peak breach, or ``None``.

    The cover RAISES a discharge limit so the pack pays for what the meter
    may not buy. That is a spend, and a spend stops at the backup reserve:
    the review found the cover raising the limit at 15 % SOC with no floor
    at all. A SOC SEM cannot read is not spent either (#531's rule: when in
    doubt, hold). The limit then stays what its own branch asked for.
    """
    rt = view.runtime
    if not getattr(rt, "available", True) or not getattr(
            view.fleet, "battery_soc_known", True):
        return "the battery SOC is not readable"
    reserve = float(view.config.get("battery_reserve_soc") or 0.0)
    soc = float(getattr(rt, "last_known_soc", 0.0) or 0.0)
    if soc <= reserve:
        return (f"the battery is at {soc:.0f}%, at or below its "
                f"{reserve:.0f}% reserve")
    return None


def peak_cover_floor_w(view: "BatteryView", limit_w: float, n: int) -> float:
    """Raise a per-battery discharge limit to what the meter may not buy (#1003).

    Every LIMIT_DISCHARGE below hands part of the house's draw to the grid on
    purpose: the #879 hold keeps the pack for a dearer hour, the #620 clamp
    lets the grid fund the cheap-hours loads. Both save cents. Going over the
    limit costs far more — a capacity tariff bills the whole month on one bad
    15-minute slot — so every one of those limits gets a floor: the watts the
    meter may not buy for the HOUSE, which the pack has to cover instead.

    Only the house. ``home_consumption_w`` excludes the car (the balance
    subtracts ``ev_power``), and the trigger is the house's own import, not
    the meter's total — so a car that breaks the limit by itself neither
    raises this floor nor drains the pack, and the charger's own clamp is
    what answers for the car. Split by ``n`` like the limit it floors
    (#531/#691), so N batteries cover the excess once, and never lowering.

    Returns ``limit_w`` untouched when no limit is configured, on a cycle
    whose house figure is not a measurement (see
    :func:`house_load_is_measured`), and (#1069) when the pack is at its
    reserve or its SOC cannot be read (:func:`reserve_stops_peak_cover`).
    """
    f = view.fleet
    allowed_w = getattr(f, "peak_slot_allowed_w", None)
    if allowed_w is None or not house_load_is_measured(f):
        return float(limit_w)
    if reserve_stops_peak_cover(view) is not None:
        return float(limit_w)
    house_w = max(0.0, float(view.home_consumption_w or 0.0))
    # ``cover_for_peak_w`` cannot exceed the house it is derived from; the
    # bound is written anyway, because "never more than the house" is the
    # invariant that keeps the pack out of the car.
    cover_w = min(house_w, cover_for_peak_w(
        allowed_w, house_w, float(getattr(f, "solar_w", 0.0) or 0.0),
    )) / max(1, int(n or 1))
    return max(float(limit_w), cover_w)


#: (#1069) A forced charge follows the room in these steps, so the room's
#: wobble does not re-send a new power every cycle; below one step it stops.
FORCED_CHARGE_STEP_W = 250.0


def forced_charge_room_w(view: "BatteryView"):
    """(#1069) The watts this battery may charge without the meter going over
    the limit, or ``None`` when no limit is configured.

    The limit is on the meter, so the room is the allowance plus the sun,
    less the house and less what the chargers were offered this cycle
    (``peak_committed_w`` — they run first, and the car comes before the
    battery). ``home_consumption_w`` excludes the car and the pack's own
    charging, so nothing is counted twice. Split across the batteries like
    every other battery budget (#531).

    Before this a planned block, a negative price and a manual force charge
    all charged at full power: a 4.2 kW limit, the car offered 4.0 kW and a
    3 kW block put 7 kW on the meter (review, 08.10).
    """
    f = view.fleet
    allowed_w = getattr(f, "peak_slot_allowed_w", None)
    if allowed_w is None:
        return None
    # The sun counts as room only on a cycle that can see: a dark read
    # makes the house figure a guess, and a guess may not buy grid watts.
    sun_w = (max(0.0, float(getattr(f, "solar_w", 0.0) or 0.0))
             if house_load_is_measured(f) else 0.0)
    room_w = (float(allowed_w) + sun_w
              - max(0.0, float(view.home_consumption_w or 0.0))
              - max(0.0, float(getattr(f, "peak_committed_w", 0.0) or 0.0)))
    n = max(1, int(getattr(f, "battery_count", 1) or 1))
    return max(0.0, room_w) / n


def _cap_forced_charge(view, decision: BatteryDecision) -> BatteryDecision:
    """(#1069) Every FORCE_CHARGE answers to the limit — the peak guard sits
    above every mode of every device, a manual force charge included."""
    if decision.intent is not BatteryIntent.FORCE_CHARGE:
        return decision
    room_w = forced_charge_room_w(view)
    if room_w is None or float(decision.charge_power_w) <= room_w:
        return decision
    stepped_w = (room_w // FORCED_CHARGE_STEP_W) * FORCED_CHARGE_STEP_W
    allowed_w = float(view.fleet.peak_slot_allowed_w)
    if stepped_w < FORCED_CHARGE_STEP_W:
        return BatteryDecision(
            battery_id=decision.battery_id,
            intent=BatteryIntent.STOP_FORCE_CHARGE,
            room_capped=True,
            # CAUSE: `room_w` is forced_charge_room_w's sum of the allowance,
            # the sun, the house and the chargers' offers, all read above.
            reason=(f"{decision.reason} — no room under the grid limit "
                    f"({allowed_w:.0f} W allowed, {room_w:.0f} W left after "
                    "the house and the car)"),
        )
    return replace(
        decision, charge_power_w=stepped_w, room_capped=True,
        # CAUSE: `stepped_w` is `room_w` from forced_charge_room_w, floored to
        # a step, and the branch runs only when the decision asked for more.
        reason=(f"{decision.reason} — {stepped_w:.0f} W, the room left under "
                f"the grid limit ({allowed_w:.0f} W allowed)"),
    )


def decide_battery(view: "BatteryView") -> BatteryDecision:
    """Compute this battery's per-cycle decision.

    Pure function — same input → same output.
    """
    return _stop_what_sem_started(
        view, _cap_forced_charge(view, _decide_battery(view)))


def _decide_battery(view: "BatteryView") -> BatteryDecision:
    rt = view.runtime
    cfg = view.config

    # ─── Per-battery MODE override (#523) ───
    # Highest precedence: a user-chosen manual mode wins over the
    # scheduler / protection logic for THIS battery. ``auto`` (the
    # default, and the value for every single-battery install that never
    # sets a mode) falls straight through to today's behaviour.
    mode = str(cfg.get("battery_mode", "auto") or "auto").lower()
    reserve = cfg.get("battery_reserve_soc")
    reserve = float(reserve) if reserve is not None else 0.0

    if mode == "off":
        # #523 (RienduPre): SEM is fully hands-off this battery. Highest
        # precedence — short-circuit BEFORE the scheduler / arbitrage /
        # protection branches so none of them can issue a command. The
        # adapter's command_off() does a one-time clean handoff on entry
        # then stays silent; the inverter runs the battery on its own.
        return BatteryDecision(
            battery_id=rt.battery_id,
            intent=BatteryIntent.OFF,
            reason="mode=off (SEM hands-off — inverter self-manages)",
        )

    if mode == "force_discharge":
        # Respect the reserve floor even for a manual sell — never drain the
        # battery below its backup reserve. At/under the floor we fall through
        # to NORMAL so command_normal() zeroes the forcible-discharge setpoint.
        #
        # #531: when the SOC is UNAVAILABLE, do NOT sell. A setpoint battery
        # (Sessy) has no hardware reserve-stop — only the live SOC gates it —
        # so discharging "blind" could drain it past the backup reserve. When
        # in doubt, hold (the live SOC self-heals next cycle).
        soc = rt.last_known_soc
        # (#932) "Don't sell blind" was `soc is not None` — and last_known_soc
        # is a float that defaults to 0.0 and is built as `float(... or 0.0)`;
        # it is NEVER None. The reader HOLDS the last valid SOC through a
        # dropout and says so on the twin flag, which the runtime carries as
        # `available`. A held 60 % passed `60 > reserve` and kept the pack
        # discharging blind for as long as the link was down — on a setpoint
        # battery with no hardware reserve-stop behind it. Ask the flag.
        if rt.available and soc is not None and soc > reserve:
            return BatteryDecision(
                battery_id=rt.battery_id,
                intent=BatteryIntent.FORCE_DISCHARGE,
                discharge_power_w=float(cfg.get("battery_max_discharge_power", 5000.0) or 0.0),
                floor_soc=reserve,
                reason="mode=force_discharge (manual sell to grid)",
            )
        # (#992, class 99) The guard above is a three-way OR, and only ONE
        # of its arms is a comparison. Printing "≤ reserve" for the other
        # two states a relation nobody evaluated: a pack held at 80 % from
        # a dark read was told it was at or below a 70 % reserve, sending
        # the reader to look at a battery that is comfortably charged while
        # the real fault is the link to it.
        # …and "last seen X%" must be a reading that HAPPENED. The first
        # cut of this fix asked ``soc is not None`` to tell a held value
        # from one that never arrived — three lines under a comment saying
        # ``last_known_soc`` is never None. So a pack whose sensor had not
        # reported once was told it was "last seen 0%", a measurement
        # nobody took, and the dead arm that would have said otherwise
        # could not run. #875 already carries the flag that answers this.
        _soc_ever_read = bool(getattr(
            getattr(view, "fleet", None), "battery_soc_known", True))
        if soc is None:
            # Not the "never read" signal — that is the flag above — but the
            # field is typed float and a caller can still hand us None, and
            # a formatting crash here takes out the whole battery decision.
            _why = "SOC unknown — not selling blind"
        elif not rt.available:
            _why = (f"SOC unreadable (last seen {soc:.0f}%) — not selling blind"
                    if _soc_ever_read else
                    "SOC never read — not selling blind")
        elif not _soc_ever_read:
            _why = "SOC never read — not selling blind"
        else:
            _why = f"SOC {soc:.0f}% ≤ reserve {reserve:.0f}%"
        return BatteryDecision(
            battery_id=rt.battery_id,
            intent=BatteryIntent.NORMAL,
            reason=f"mode=force_discharge but {_why} — hold",
        )
    if mode == "force_charge":
        return BatteryDecision(
            battery_id=rt.battery_id,
            intent=BatteryIntent.FORCE_CHARGE,
            target_soc=100.0,
            # #523: fall through the two charge-power keys before the 5000 W
            # default. ``battery_max_charge_power_w`` is often present-as-None
            # (so a ``.get(key, 5000)`` returns None, not the default) — with the
            # bidirectional-setpoint charge path that yielded a 0 W setpoint and
            # the battery never charged. ``or`` chains past None/0 to a real value.
            charge_power_w=float(
                cfg.get("battery_max_charge_power_w")
                or cfg.get("battery_max_charge_power")
                or 5000.0
            ),
            duration_min=240,
            reason="mode=force_charge (manual charge to full)",
        )

    # ─── FORCE_CHARGE / STOP_FORCE_CHARGE branch ───
    # The pre-computed scheduler_decision tells us whether to be in
    # a forced-charge window. Pure read of its state field — the
    # scheduler's evaluate() did the work in BatteryChargeScheduler.
    sched = view.scheduler_decision
    # (#1066) A stop verdict is a command only while its direction may still
    # run. Once that stop has landed it says nothing, and the protection
    # branches below decide — the night scheduler is never without a
    # verdict, so letting it win here starved every branch under it.
    _charge_open = getattr(view, "sem_forced_charge", None) is not False
    _discharge_open = getattr(view, "sem_forced_discharge", None) is not False
    if sched is not None:
        state = getattr(sched, "state", None)
        state_value = getattr(state, "value", state) if state is not None else None

        if state_value == "scheduled":
            # (#638 one-gate C4) The scheduler owns WHAT (deficit, target,
            # power, economics); the joint plan owns WHEN. The old
            # ``_now_in_window`` read the scheduler's OWN window pick —
            # the second selector this build retires.
            sched_power = float(getattr(sched, "charge_power_w", 0.0) or 0.0)
            if bool(getattr(sched, "price_forced", False)):
                # Negative price: being PAID to consume is a reactive
                # price gate, not window selection — bypasses the plan.
                return BatteryDecision(
                    battery_id=rt.battery_id,
                    intent=BatteryIntent.FORCE_CHARGE,
                    target_soc=getattr(sched, "target_soc", 0.0),
                    charge_power_w=sched_power,
                    duration_min=getattr(sched, "duration_min", 60),
                    reason="negative price — charging regardless of plan",
                )
            gate = view.plan_gate
            if gate is not None and getattr(gate, "covered", False):
                if getattr(gate, "in_block", False):
                    block_w = float(
                        getattr(gate, "block_power_w", 0.0) or 0.0)
                    power = min(sched_power, block_w) if block_w > 0 \
                        else sched_power
                    return BatteryDecision(
                        battery_id=rt.battery_id,
                        intent=BatteryIntent.FORCE_CHARGE,
                        target_soc=getattr(sched, "target_soc", 0.0),
                        charge_power_w=power,
                        duration_min=getattr(sched, "duration_min", 60),
                        reason="scheduler SCHEDULED → plan block open — "
                               "force charge",
                    )
                nxt = getattr(gate, "next_block_start", None)
                when = f" (opens {nxt:%H:%M})" if nxt else ""
                if _charge_open:
                    return BatteryDecision(
                        battery_id=rt.battery_id,
                        intent=BatteryIntent.STOP_FORCE_CHARGE,
                        reason="scheduler SCHEDULED — outside the planned "
                               f"block{when}",
                    )
            else:
                why = (getattr(gate, "reason", "") if gate is not None
                       else "no gate")
                if _charge_open:
                    return BatteryDecision(
                        battery_id=rt.battery_id,
                        intent=BatteryIntent.STOP_FORCE_CHARGE,
                        reason=f"scheduled but the plan does not cover the "
                               f"battery ({why or 'uncovered'}) — pre-charge "
                               "is optimization, not guarantee",
                    )

        # Export arbitrage — the scheduler decided to SELL to the grid
        # this cycle (#523). Pure actuation of the scheduler's verdict, the
        # mirror of the SCHEDULED → FORCE_CHARGE path above. Gated PER
        # BATTERY by its mode (self_consumption never sells; allow_arbitrage
        # always may; auto follows the global toggle) and its OWN reserve
        # SOC — so a self-consumption battery keeps its charge while its
        # sibling sells, on the same shared verdict.
        # INTENTIONAL precedence (#533, user decision 2026-06-27 = pure
        # economics): this arbitrage branch runs BEFORE the EV LIMIT_DISCHARGE
        # clamp below. When selling is profitable the battery sells even with
        # an EV connected — the price signal decides, the EV/house do not
        # pre-empt it. Do NOT "fix" this ordering by gating arbitrage on
        # ev_connected; the profitability test (export > import÷eff + cycle) is
        # what keeps it sane.
        if state_value == "discharging_arbitrage":
            # (#778) Two triggers share this branch, distinguished on the
            # verdict itself: arbitrage (price economics) and the forecast
            # SPEND (budget economics). Each reads its OWN plan gate and its
            # OWN master switch — sharing either would let one feature's
            # switch open the other's valve.
            _spend = bool(getattr(sched, "from_forecast_spend", False))
            global_arb = bool(cfg.get("battery_grid_arbitrage_enabled", False))
            # (#638 one-gate C6) The plan says WHEN: the live economics
            # verdict alone no longer opens the valve — the stamped plan's
            # sell block must be open (view.arbitrage_sell, fleet-split by
            # the pipeline).
            _sell = getattr(
                view, "forecast_sell" if _spend else "arbitrage_sell", None)
            _sell_open = bool(_sell and _sell[0])
            # (#778) The user's export permission binds here too. Passing it
            # is not optional politeness: without it the "Battery may sell to
            # the grid" switch persists a value nothing reads, and a user who
            # revokes the permission watches SEM keep selling. Caught by
            # tests/test_knob_wiring.py, which exists for exactly this.
            _perms = getattr(view, "battery_permissions", None)
            _gate_flag = (bool(getattr(view, "forecast_spending_enabled", False))
                          if _spend else global_arb)
            if _sell_open and arbitrage_allowed_for_mode(mode, _gate_flag, _perms):
                # BOTH floors bind and the higher wins: the user's backup
                # reserve AND the verdict's arbitrage_reserve_soc. The old
                # either/or dropped the arbitrage reserve on every install
                # with a nonzero backup reserve (i.e. all of them) — and
                # handed the ACTUATOR the lower floor, which a hardware
                # end-SOC (Huawei) or a setpoint battery honors on its own
                # between SEM cycles. The #532 drain class, one seam later.
                # (#778) A THIRD floor joins the two: the forecast-derived
                # dynamic floor. The static reserves answer "never below this,
                # ever"; the dynamic one answers "not below this TONIGHT,
                # because the house still has to get to sunrise on it". The
                # higher always wins, and an unknown dynamic floor contributes
                # nothing rather than being read as zero.
                _dyn = getattr(view, "dynamic_floor_pct", None)
                floor = max(
                    reserve, float(getattr(sched, "floor_soc", 0.0) or 0.0)
                )
                if _dyn is not None:
                    try:
                        floor = max(floor, float(_dyn))
                    except (TypeError, ValueError):
                        pass
                soc = rt.last_known_soc
                # #531: don't sell blind — a setpoint battery has no hardware
                # reserve-stop, so an unavailable SOC must hold, not discharge.
                # (#932) …and "unavailable" is `rt.available`, not `soc is
                # None` — the number is HELD through a dark read and never
                # None once a reading has ever succeeded.
                if rt.available and soc is not None and soc > floor:
                    # Power discipline (#638 C6): the block-implied watts
                    # are the cap — the advisor bounded delivery by the
                    # home's own draw, so this stays an avoided-import
                    # delivery, never export-at-max. The pipeline already
                    # split the block power across the fleet (#531/#691
                    # treatment via effective_battery_count).
                    _cap = float(_sell[1] or 0.0)
                    _sched_w = float(getattr(sched, "discharge_power_w", 0.0) or 0.0)
                    # (#778) …and the budget caps it too, when the arc's master
                    # switch is on. Without the switch this is untouched, so an
                    # install already selling keeps selling exactly as before.
                    if getattr(view, "forecast_spending_enabled", False):
                        _budget_kwh = float(
                            getattr(view, "battery_spendable_kwh", 0.0) or 0.0)
                        if _budget_kwh <= 0.0:
                            return BatteryDecision(
                                battery_id=rt.battery_id,
                                intent=BatteryIntent.NORMAL,
                                reason=("export held — tonight's forecast budget "
                                        "has nothing spendable"),
                            )
                    return BatteryDecision(
                        battery_id=rt.battery_id,
                        intent=BatteryIntent.FORCE_DISCHARGE,
                        discharge_power_w=min(_cap, _sched_w) if _sched_w > 0 else _cap,
                        floor_soc=floor,
                        reason=getattr(sched, "reason", "export arbitrage")
                               + " — plan sell block open",
                    )
            # Not allowed for this battery (self_consumption / auto-with-
            # global-off) or already at/under its reserve → fall through to
            # the normal decision (don't sell this unit).

        # Target reached or no longer needed — stop a running force op.
        # NOTE: ``target_reached`` is only ever produced by the night-charge
        # ``evaluate()``, never by ``evaluate_arbitrage`` — so target_reached +
        # from_arbitrage is unreachable (harmless; kept for symmetry) (ruflo L4).
        if state_value in _SCHEDULER_STOP_STATES:
            # Route the stop by WHICH scheduler produced the verdict (#533):
            # an arbitrage verdict (from_arbitrage) was selling → STOP_FORCE_
            # DISCHARGE; the night charge scheduler's same-named states stop a
            # force-CHARGE. Before this, both emitted STOP_FORCE_CHARGE and
            # relied on the Huawei stop-charge service ALSO clearing a forcible
            # discharge (a brand coincidence) — a generic adapter would have
            # kept selling. The actuator may no-op if already in that state
            # (adapter idempotency).
            if getattr(sched, "from_arbitrage", False):
                if _discharge_open:
                    return BatteryDecision(
                        battery_id=rt.battery_id,
                        intent=BatteryIntent.STOP_FORCE_DISCHARGE,
                        reason=f"arbitrage {state_value} → stop selling to grid",
                    )
            elif _charge_open:
                return BatteryDecision(
                    battery_id=rt.battery_id,
                    intent=BatteryIntent.STOP_FORCE_CHARGE,
                    reason=f"scheduler {state_value} → ensure not force-charging",
                )

    # ─── arc #921: the sink verdicts (absent = every sink OPEN) ───
    _sv = getattr(view, "sink_verdicts", None) or {}
    _house_v = _sv.get("house")

    # (#892) A morning window before departure: the pack is SPENT into the
    # car deliberately, down to the drain floor — the EV protection clamp
    # below must not fight a window the user opened. Bounded by the floor
    # and by a SOC that was actually read.
    # (#1025) A battery boost is the same spend on the user's one-off, to the
    # boost's own floor. Both open: each was consented to its own depth, so
    # the pack may go to the deeper one.
    # (#1066) …unless THIS battery may not feed the car at all. The charger
    # side asks ``may_assist_ev`` before any window or boost (``decide.
    # _battery_assist_split``); the battery side never asked, so a pack the
    # user had kept for the house still covered the car on the meter. One
    # permission, both readers.
    _assist_ok = may_assist_ev(
        mode, effective_permissions(mode, getattr(view, "battery_permissions", None)))
    _window = bool(getattr(view, "morning_window_open", False))
    _boost = getattr(view, "battery_boost_floor_soc", None)
    if (_window or _boost is not None) and _assist_ok:
        _floors = []
        if _window:
            _floors.append(float(
                cfg.get("battery_morning_drain_floor_soc", 50.0) or 50.0))
        if _boost is not None:
            _floors.append(float(_boost))
        _floor = min(_floors)
        _why = ("battery boost" if _boost is not None and _floor == float(_boost)
                else "morning window")
        _soc = rt.last_known_soc
        if rt.available and _soc is not None and _soc > _floor:
            return BatteryDecision(
                battery_id=rt.battery_id, intent=BatteryIntent.NORMAL,
                reason=(f"{_why} — the pack feeds the car down to "
                        f"{_floor:.0f}% (SOC {_soc:.0f}%)"),
            )

    # (#879) The house as a sink: HELD in a cheap/negative hour means "let the
    # house import, keep the pack for the expensive hours" — the WHEN is the
    # tariff level, the HOW MUCH is zero house cover (0 W quantises to 0).
    #
    # (#1003) …except the meter has a ceiling. While the hold stands the house
    # buys everything, and a capacity tariff bills the whole month on one bad
    # 15-minute slot: waiting for a cheaper hour saves cents, going over the
    # limit costs far more. So the hold gives way to the limit — the pack
    # covers at least what the meter is not allowed to buy. The verdict still
    # says WHEN; this is the floor under its HOW MUCH, and it is the same slot
    # budget the EV and the cheap-hours loads are already sized against.
    if _house_v is not None and getattr(_house_v, "state", "") == "held":
        _f = view.fleet
        _allowed = getattr(_f, "peak_slot_allowed_w", None)
        _n = max(1, int(getattr(_f, "battery_count", 1) or 1))
        if _allowed is not None and not house_load_is_measured(_f):
            # A hold that cannot see cannot show the slot is safe, so it does
            # not hold: the pack covers the house, as it did before this sink
            # existed. That pre-#879 state is NORMAL, and NORMAL at the wire
            # IS this write — ``command_normal`` applies the pack's own max
            # discharge. Spelled as LIMIT_DISCHARGE on purpose: #818 blocks a
            # FLIP between NORMAL and LIMIT_DISCHARGE on a degraded cycle, so
            # a release spelled NORMAL is never written and the 0 W stands
            # through exactly the blindness that released it.
            #
            # The MAX and not the house figure: that figure is the balance's
            # residual and is precisely what this branch has just decided it
            # cannot read. A dark grid read makes it 0, which would write the
            # hold again and call it a release.
            _why = (", ".join(getattr(_f, "dark_inputs", ()) or ())
                    or "clamped balance")
            return BatteryDecision(
                battery_id=rt.battery_id, intent=BatteryIntent.LIMIT_DISCHARGE,
                discharge_limit_w=float(
                    cfg.get("battery_max_discharge_power", 5000.0) or 5000.0),
                # CAUSE: `_f.dark_inputs` is the reader's own list of which
                # reads came back dark, and the fallback names the other arm
                # of `house_load_is_measured` — `home_residual_clamped_w`,
                # tested one line up. Never a guess about which.
                reason=(f"house sink not held — {_why}: the house load is not "
                        "measured, so nothing shows the meter is under its limit"),
            )
        _cover_w = peak_cover_floor_w(view, 0.0, _n)
        _why = f"house sink held — {getattr(_house_v, 'reason', '')}"
        _stop = reserve_stops_peak_cover(view)
        if _stop is not None and cover_for_peak_w(
                _allowed, max(0.0, float(view.home_consumption_w or 0.0)),
                float(getattr(_f, "solar_w", 0.0) or 0.0)) > 0.0:
            # CAUSE: `_stop` is reserve_stops_peak_cover's own sentence —
            # the SOC and reserve it compared, or the unreadable SOC.
            _why = (f"{_why}; the meter is over its limit, but {_stop} — "
                    "the pack does not cover it")
        elif _cover_w > 0.0:
            _why = (
                f"{_why}; the meter may buy {float(_allowed):.0f} W for the "
                f"rest of this quarter hour, so the pack covers "
                f"{_cover_w:.0f} W"
            )
        return BatteryDecision(
            battery_id=rt.battery_id, intent=BatteryIntent.LIMIT_DISCHARGE,
            discharge_limit_w=_cover_w,
            reason=_why,
        )

    # ─── LIMIT_DISCHARGE branch (unified solar gate) ───
    # The home battery must NEVER be drained to charge the EV when there
    # isn't enough real solar surplus — in ANY charging mode
    # (min_plus_solar, solar_only, solar_plus_cheap, always_max) and at
    # any time of day/night. One knob governs it: when the EV is drawing
    # and the pure solar surplus (solar − home) is below
    # ``battery_assist_min_surplus_w`` (default 1200 W), clamp battery
    # discharge to the home load so grid+solar fund the car, never the
    # battery.
    #
    # Setting the gate to 0 W bypasses the SURPLUS arm (surplus ≥ 0 always
    # clears a 0 threshold), letting the battery support the EV without a
    # surplus requirement. The ``buffer_soc`` floor is still honoured as a
    # HARD constraint, though: gate=0 does NOT let the battery discharge
    # into the car below the self-consumption reserve — set ``buffer_soc``
    # low (or 0) for that.
    #
    # This UNIFIES (supersedes) the old night-only / hold_solar triggers:
    # at the default the overnight case is unchanged (no solar → surplus
    # 0 < 1200 → clamp). The retired ``battery_hold_solar_ev`` knob is
    # subsumed by this gate (cloudy solar below the gate clamps regardless).
    #
    # GATE ON ev_connected (plugged in), NOT ev_charging (drawing now):
    # a bursty car (e.g. Renault Zoe) toggles ev_charging on/off every
    # few seconds. Keying the clamp on ev_charging means it drops in the
    # gaps → the battery discharges freely → that energy feeds the next
    # pull → the battery drains overnight (PROD 2026-06-24, 93→41 %).
    # While a car is plugged in and surplus is below the gate, the
    # protection must HOLD regardless of the instantaneous draw. Fall
    # back to ev_charging so older views (no ev_connected) still gate.
    protection_enabled = bool(cfg.get("battery_discharge_protection_enabled", True))

    # (#1066) A battery the user has said may not feed the car is clamped
    # whenever a car is plugged in — with or without the legacy protection
    # switch, whatever the surplus or the spend consent: the newer, more
    # specific "no" wins (the class-75 rule). UNSET resolves to True, so no
    # install that has not asked moves.
    if (protection_enabled or not _assist_ok) and (view.ev_connected or view.ev_charging):
        f = view.fleet
        # Pure solar-vs-house surplus. Intentionally does NOT subtract
        # battery_charge_w (unlike decide.self_consumption_surplus_w): the
        # battery view's FleetContext doesn't populate it, and a battery
        # that is charging cannot simultaneously discharge — so the simpler
        # formula is safe here (slightly more permissive at worst).
        surplus_w = max(0.0, float(f.solar_w) - float(f.home_w))
        gate_w = float(getattr(f, "battery_assist_min_surplus_w", 1200.0))
        # Buffer SoC = the self-consumption reserve floor (the EV
        # battery-assist band only opens at/above it). Below the buffer the
        # battery must NOT feed the car in ANY zone, regardless of surplus —
        # otherwise (PROD 2026-06-26) at SoC 83 % with surplus ~1150 W > gate
        # the inverter freely discharged the battery into the car well below
        # the user's 85 % floor. So clamp when surplus is short OR SoC has
        # fallen below the buffer. Above the buffer with real surplus the
        # battery is free to assist (#545). buffer=0 disables the SoC arm.
        buffer_soc = float(getattr(f, "buffer_soc", 70.0))
        # (#885) The floor the charger side respects is the EFFECTIVE one —
        # buffer, or tonight's dynamic floor when it sits higher (#878).
        floor_soc = buffer_soc
        _dyn = getattr(view, "dynamic_floor_pct", None)
        if _dyn is not None:
            try:
                floor_soc = max(floor_soc, float(_dyn))
            except (TypeError, ValueError):
                pass
        # (#875) a SOC never read lands on the protective side too.
        below_buffer = (float(f.battery_soc) < floor_soc
                        or not getattr(f, "battery_soc_known", True))
        # (#885) The charger side opens the #537 solar gate when forecast
        # spending is on and tonight's budget has something spendable
        # (#778 phase 5). This clamp is the other reader of the same gate:
        # left closed, the charger offered assist amps the pack was pinned
        # from delivering and the car drew grid under a line that said
        # battery assist (PROD 02.09). One gate, two readers.
        # (03.09) …and the consent is the charger's mode as much as the
        # switch: a connected car in *Solar + battery* has already been told
        # it may have the pack (``ev_wants_pack``). Same gate as the charger
        # side, one more reader.
        spend_open = (
            (bool(getattr(view, "forecast_spending_enabled", False))
             or bool(getattr(view, "ev_wants_pack", False)))
            and float(getattr(view, "battery_spendable_kwh", 0.0) or 0.0) > 0.0
        )
        if (surplus_w < gate_w and not spend_open) or below_buffer or not _assist_ok:
            # #531: split the home budget across the fleet — N batteries each
            # told to inject the FULL home load over-injects N× and leaks the
            # surplus to the EV, defeating the protection. Each gets home/N.
            # (#620) grid-funded cheap-hours loads are excluded from the home
            # budget — the grid feeds them, not the battery (see below).
            n = max(1, int(getattr(f, "battery_count", 1) or 1))
            gf_w = max(0.0, float(getattr(view, "grid_funded_load_w", 0.0) or 0.0))
            home_w = max(0.0, view.home_consumption_w - gf_w) / n
            # (#1003) the grid-funded slice goes to the meter, and the meter
            # has a limit. Floored, never lowered; the car is not in this
            # figure, so this never feeds the car.
            _floored_w = peak_cover_floor_w(view, home_w, n)
            _peak_raised = _floored_w > home_w
            home_w = _floored_w
            if not _assist_ok:
                # (#1066) The permission alone decides here — name it, not
                # a surplus or SOC comparison that did not choose (#983).
                why = "ev plugged in + this battery may not feed the car (may_assist_ev off)"
            elif not getattr(f, "battery_soc_known", True):
                # (#983) ``below_buffer`` is a disjunction, and the unread
                # arm has no comparison in it: printing "SoC unknown < buffer
                # 70%" states a relation nobody evaluated, on the one input
                # that is missing. Name the missing read instead — the
                # clamp is the #875 protective default, not a measurement.
                why = ("ev plugged in + battery SoC never read — holding the "
                       "protective floor (#875)")
            elif below_buffer:
                why = (
                    f"ev plugged in + battery SoC {f.soc_label} < "
                    + (f"tonight's floor {floor_soc:.1f}%"
                       if floor_soc > buffer_soc else
                       f"buffer {buffer_soc:.0f}% (self-consumption floor)")
                )
            else:
                why = (
                    f"ev plugged in + solar surplus {surplus_w:.0f}W < gate "
                    f"{gate_w:.0f}W"
                )
            if gf_w > 0:
                why += f" (excl. {gf_w:.0f}W grid-funded load)"
            return BatteryDecision(
                battery_id=rt.battery_id,
                intent=BatteryIntent.LIMIT_DISCHARGE,
                discharge_limit_w=home_w,
                reason=(
                    f"{why} → discharge limit {home_w:.0f} W "
                    + (f"— raised, the meter may buy only "
                       f"{float(view.fleet.peak_slot_allowed_w):.0f} W for the "
                       f"rest of this quarter hour"
                       if _peak_raised else f"(home/{n} across fleet)")
                ),
            )

    # ─── LIMIT_DISCHARGE for grid-funded loads (#620) ───
    # "Finish overnight from: Grid" must actually pull from the GRID. The
    # inverter's self-consumption logic covers any house load from the battery,
    # so without a clamp the Battery/Grid picker choices are physically
    # identical (observed live: identical discharge either way, PROD
    # 2026-07-22). While cheap-hours loads run, cap discharge at the rest of
    # the home load — the grid funds the forced loads, the battery still
    # serves everything else. Independent of the EV (the branch above already
    # subtracts when both are active).
    if protection_enabled:
        gf_w = max(0.0, float(getattr(view, "grid_funded_load_w", 0.0) or 0.0))
        if gf_w > 0:
            f = view.fleet
            n = max(1, int(getattr(f, "battery_count", 1) or 1))
            home_w = max(0.0, view.home_consumption_w - gf_w) / n
            # (#1003) same floor as its sibling above: the grid funds these
            # loads to save cents, and the peak limit outranks that.
            _floored_w = peak_cover_floor_w(view, home_w, n)
            _peak_raised = _floored_w > home_w
            home_w = _floored_w
            return BatteryDecision(
                battery_id=rt.battery_id,
                intent=BatteryIntent.LIMIT_DISCHARGE,
                discharge_limit_w=home_w,
                reason=(
                    f"grid-funded load(s) {gf_w:.0f}W running (cheap-hours "
                    f"top-up) → discharge limit {home_w:.0f} W "
                    + (f"— raised, the meter may buy only "
                       f"{float(view.fleet.peak_slot_allowed_w):.0f} W for the "
                       f"rest of this quarter hour"
                       if _peak_raised else
                       f"(home/{n} across fleet) so the grid feeds them")
                ),
            )

    # ─── NORMAL ───
    return BatteryDecision(
        battery_id=rt.battery_id,
        intent=BatteryIntent.NORMAL,
        reason="no protection / no force-charge — default discharge",
    )


