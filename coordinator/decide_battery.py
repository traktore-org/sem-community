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
   IDLE but the adapter is still in FORCE_CHARGE intent.
3. LIMIT_DISCHARGE (EV) — EV charging AND either solar surplus is below
   the ``battery_assist_min_surplus`` gate OR battery SoC is below the
   ``battery_buffer_soc`` floor (any mode/time); clamp battery to home
   consumption (1:1 protection) so grid+solar fund the car. Grid-funded
   cheap-hours load draw is excluded from the home budget.
4. LIMIT_DISCHARGE (grid-funded loads, #620) — cheap-hours top-up loads
   ("Finish overnight from: Grid") are running; clamp battery to
   home − grid_funded so the grid, not the battery, feeds them.
5. NORMAL — default.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .charger_types import BatteryDecision, BatteryIntent
from ..consts.battery_modes import arbitrage_allowed_for_mode

if TYPE_CHECKING:  # pragma: no cover
    from .charger_types import BatteryView

_LOGGER = logging.getLogger(__name__)


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


def decide_battery(view: "BatteryView") -> BatteryDecision:
    """Compute this battery's per-cycle decision.

    Pure function — same input → same output.
    """
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
        if soc is not None and soc > reserve:
            return BatteryDecision(
                battery_id=rt.battery_id,
                intent=BatteryIntent.FORCE_DISCHARGE,
                discharge_power_w=float(cfg.get("battery_max_discharge_power", 5000.0) or 0.0),
                floor_soc=reserve,
                reason="mode=force_discharge (manual sell to grid)",
            )
        _soc_txt = f"{soc:.0f}%" if soc is not None else "unavailable"
        return BatteryDecision(
            battery_id=rt.battery_id,
            intent=BatteryIntent.NORMAL,
            reason=f"mode=force_discharge but SOC {_soc_txt} ≤ reserve {reserve:.0f}% — hold",
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
                return BatteryDecision(
                    battery_id=rt.battery_id,
                    intent=BatteryIntent.STOP_FORCE_CHARGE,
                    reason="scheduler SCHEDULED — outside the planned "
                           f"block{when}",
                )
            why = getattr(gate, "reason", "") if gate is not None else "no gate"
            return BatteryDecision(
                battery_id=rt.battery_id,
                intent=BatteryIntent.STOP_FORCE_CHARGE,
                reason=f"scheduled but the plan does not cover the battery "
                       f"({why or 'uncovered'}) — pre-charge is "
                       "optimization, not guarantee",
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
                if soc is not None and soc > floor:
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
        if state_value in ("target_reached", "not_needed", "idle", "not_profitable"):
            # Route the stop by WHICH scheduler produced the verdict (#533):
            # an arbitrage verdict (from_arbitrage) was selling → STOP_FORCE_
            # DISCHARGE; the night charge scheduler's same-named states stop a
            # force-CHARGE. Before this, both emitted STOP_FORCE_CHARGE and
            # relied on the Huawei stop-charge service ALSO clearing a forcible
            # discharge (a brand coincidence) — a generic adapter would have
            # kept selling. The actuator may no-op if already in that state
            # (adapter idempotency).
            if getattr(sched, "from_arbitrage", False):
                return BatteryDecision(
                    battery_id=rt.battery_id,
                    intent=BatteryIntent.STOP_FORCE_DISCHARGE,
                    reason=f"arbitrage {state_value} → stop selling to grid",
                )
            return BatteryDecision(
                battery_id=rt.battery_id,
                intent=BatteryIntent.STOP_FORCE_CHARGE,
                reason=f"scheduler {state_value} → ensure not force-charging",
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

    if protection_enabled and (view.ev_connected or view.ev_charging):
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
        # (#875) a SOC never read lands on the protective side too.
        below_buffer = (float(f.battery_soc) < buffer_soc
                        or not getattr(f, "battery_soc_known", True))
        if surplus_w < gate_w or below_buffer:
            # #531: split the home budget across the fleet — N batteries each
            # told to inject the FULL home load over-injects N× and leaks the
            # surplus to the EV, defeating the protection. Each gets home/N.
            # (#620) grid-funded cheap-hours loads are excluded from the home
            # budget — the grid feeds them, not the battery (see below).
            n = max(1, int(getattr(f, "battery_count", 1) or 1))
            gf_w = max(0.0, float(getattr(view, "grid_funded_load_w", 0.0) or 0.0))
            home_w = max(0.0, view.home_consumption_w - gf_w) / n
            if below_buffer:
                why = (
                    f"ev plugged in + battery SoC {f.soc_label} < buffer "
                    f"{buffer_soc:.0f}% (self-consumption floor)"
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
                    f"{why} → discharge limit {home_w:.0f} W (home/{n} across fleet)"
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
            return BatteryDecision(
                battery_id=rt.battery_id,
                intent=BatteryIntent.LIMIT_DISCHARGE,
                discharge_limit_w=home_w,
                reason=(
                    f"grid-funded load(s) {gf_w:.0f}W running (cheap-hours "
                    f"top-up) → discharge limit {home_w:.0f} W (home/{n} "
                    f"across fleet) so the grid feeds them"
                ),
            )

    # ─── NORMAL ───
    return BatteryDecision(
        battery_id=rt.battery_id,
        intent=BatteryIntent.NORMAL,
        reason="no protection / no force-charge — default discharge",
    )


