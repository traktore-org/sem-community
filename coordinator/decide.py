"""Pure ``decide(view) → ChargerDecision`` (Step 3 of the
arch/multi-charger-primary migration).

One pure function per cycle per charger. Replaces the chain
``_determine_charging_strategy + _build_charging_context +
ChargingStateMachine.update_state`` that pre-architecture
threaded through three modules with implicit contracts.

Properties of this design:

1. **Pure** — no ``self``, no HA calls, no clock reads. Input
   ``ChargerView``, output ``ChargerDecision``. Same input always
   produces the same output (modulo the explicit time field on
   ``FleetContext.is_night``).

2. **One mode = one strategy class** — the five ``EV_CHARGE_MODES``
   each get a ``ModeStrategy`` subclass. The strategy/state-machine
   disagreement class (#346) cannot exist by construction: each
   mode owns its full decision path.

3. **No re-derivation of mode** — ``view.mode`` is already
   resolved upstream via ``effective_charge_mode_for``. The mode
   strategies don't re-read config to determine mode.

4. **Conservation by construction** — every code path returns a
   ``ChargerDecision`` (no implicit fallthrough). The conservation
   tests in Step 8 verify intent-vs-outcome agreement.

This module does NOT yet replace ``_determine_charging_strategy``
in production — Step 4 wires the adapter, Step 6 wires the data
model. Until then this is exercised only by its own tests.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import replace
from typing import Dict, Optional, Type

from .charger_types import (
    ChargerDecision,
    ChargerIntent,
    ChargerView,
)
from .energy_reclaim import ev_reclaims_battery_charge

_LOGGER = logging.getLogger(__name__)


def _ev_reclaims(view: ChargerView) -> bool:
    """#576 P2.2 — does this charger reclaim battery-charge power? (Above the
    battery in the one list, SOC ≥ reserve floor, battery not commanded.)"""
    f = view.fleet
    return ev_reclaims_battery_charge(
        soc=f.battery_soc,
        priority_soc=f.priority_soc,
        ev_priority=view.ev_priority,
        battery_priority=f.battery_priority,
        battery_commanded=f.battery_commanded,
    )


def solar_charge_display_override(intent, drawing: bool,
                                  no_draw_elapsed_s: float,
                                  grace_s: float = 90.0) -> Optional[str]:
    """Cosmetic per-charger display state for solar charging.

    When SEM commands a charge but the car isn't actually drawing (power
    below the handshake threshold) for longer than ``grace_s``, the
    dashboard should read "ready", not "charging" — otherwise a satisfied /
    full / not-yet-ready car shows a misleading "Charging" while 0 W flows
    (observed live: min_plus_solar offering 9 A to a believed-full car).

    Deliberately **power-based, not SoC-estimate based** — SEM's energy
    estimate drifts (seen reading 100% while the car still drew 4.5 kW), so
    keying the display (let alone the command) off it would mislabel real
    charging. The actuator keeps offering current regardless; this only
    changes the label.

    Returns a ``ChargingState`` string to override with, or ``None`` to keep
    the normal intent-derived state (drawing, or still within ramp-up grace).
    """
    if intent not in (ChargerIntent.CHARGE_AT_AMPS, ChargerIntent.CHARGE_MAX):
        return None
    if drawing:
        return None
    if no_draw_elapsed_s >= grace_s:
        from ..consts.states import ChargingState
        return ChargingState.SOLAR_IDLE
    return None  # within ramp-up grace — a car can take ~30-60 s to start


# ─────────────────────────────────────────────────────────────────
# Helpers — shared zone math (pure, no state)
# ─────────────────────────────────────────────────────────────────

def soc_zone(soc: float, auto_start: float, buffer: float, priority: float) -> int:
    """Map SOC to zone number.

    Pre-architecture this lived as ``SEMCoordinator._raw_zone`` and
    was paired with ``_debounce_zone`` for stateful smoothing. The
    pure ``decide`` doesn't debounce here — that's a coordinator
    concern (the coordinator pre-debounces SOC before building the
    view, or wraps ``decide()`` in a debounce shim).

    Returns 1..4. Higher = more battery available.
    """
    if soc >= auto_start:
        return 4
    if soc >= buffer:
        return 3
    if soc >= priority:
        return 2
    return 1


def self_consumption_surplus_w(view: ChargerView) -> float:
    """Pure surplus = solar - home (- battery_charge unless Zone 4)
    (- solar_committed_w by higher-priority chargers).

    Ports ``_self_consumption_strategy`` from
    ``coordinator.py:2787``. Battery charges first below
    ``auto_start_soc``; above it, leftover solar redirects to EV.

    Step 6 multi-charger correctness: ``solar_committed_w`` is
    subtracted so the second charger in the per-charger loop sees
    only the surplus NOT already claimed by charger A. Prevents
    over-allocation of solar in multi-charger fleets.
    """
    f = view.fleet
    # #743 — granted curtailment watts count exactly like measured
    # solar: an export-limited inverter clamps production to
    # consumption, and the probe's grant is the bootstrap that lets
    # the array show what it can actually deliver.
    available = (
        f.solar_w + f.curtailment_grant_w - f.home_w - f.solar_committed_w
    )
    # #576 P2.2 — the EV reclaims battery-charge power (charges BEFORE the
    # battery) iff it sits above the battery in the one priority list AND SOC
    # ≥ the reserve floor AND the battery isn't under a command. Otherwise the
    # battery keeps its charge (subtract it). Replaces the old fixed
    # ``auto_start_soc`` (90 %) gate with the position rule the loads use.
    if not _ev_reclaims(view):
        available -= f.battery_charge_w
    return max(0.0, available)


def battery_assist_budget_w(view: ChargerView) -> float:
    """Budget for Zone 3/4 battery-assist charging.

    Called exclusively from ``MinPlusSolarMode._decide_day()`` (the
    Zone 3/4 path) — ``solar_plus_cheap`` delegates its day path to
    ``solar_only`` and ``always_max`` ignores any budget. When the
    home battery is high enough (Zone 3 or 4), it can discharge to
    bridge the gap between solar surplus and EV demand.

    The assist component is the shared SOC-based POTENTIAL
    (``flow_calculator.battery_assist_potential_w``) — capped by the
    user's ``battery_assist_max_power`` and zeroed below the buffer SOC.

    #545 / "max out till self-consumption": in the assist band (Zone 3/4,
    SOC >= buffer, surplus past the solar gate) the FULL potential is
    offered — the inverter discharges the battery into the car down to the
    buffer (the self-consumption reserve floor). The potential ramps with
    SOC (full at auto_start, 0.5x at buffer, 0 below), so the discharge
    self-tapers toward the floor and never crosses it. This supersedes the
    #501 "top up to EV minimum only" cap, which left a full battery idle
    while the EV grid-charged (the #545 chicken-and-egg).

    The pre-#501 formula added ``f.battery_discharge_w`` (the
    battery's TOTAL measured discharge, house share included), which
    ignored the config caps and ratcheted the commanded current
    upward on every home-load spike: more home draw → more discharge
    → bigger "EV budget" → higher amps → more discharge. Using
    potential instead of measurement also preserves the #439 fix —
    no chicken-and-egg gate on currently-flowing discharge.

      Zone 1/2: no battery assist. Return surplus only.
    """
    from .flow_calculator import battery_assist_potential_w

    f = view.fleet
    surplus = self_consumption_surplus_w(view)
    zone = soc_zone(f.battery_soc, f.auto_start_soc, f.buffer_soc, f.priority_soc)
    if zone < 3:
        return surplus
    # Solar gate: assist only SUPPLEMENTS real solar. Below the
    # configured surplus threshold (default 1200 W) the battery is
    # off-limits to the EV — a sunless evening/overnight session must
    # never drain the home battery into the car. Falls back to surplus
    # only (the day path then behaves like solar_only → idle).
    if surplus < f.battery_assist_min_surplus_w:
        return surplus
    potential = battery_assist_potential_w(
        f.battery_soc,
        f.buffer_soc,
        f.auto_start_soc,
        f.battery_assist_max_power_w,
    )
    # #545 / "max out till self-consumption" (user 2026-06-26): once past
    # the solar gate and in the assist band (Zone 3/4, SOC >= buffer),
    # OFFER THE FULL assist potential — let the inverter discharge the
    # battery into the car all the way down to the buffer (the
    # self-consumption reserve floor), not just enough to reach the EV
    # minimum. This raises the offered amps so the car draws more and the
    # otherwise-idle/exporting battery empties into the car, avoiding a
    # grid night-charge (#545 chicken-and-egg, observed live: a full
    # battery sat idle while the EV grid-charged). The potential
    # self-tapers as SOC falls toward the buffer (the ramp in
    # battery_assist_potential_w) and zeroes below it (zone < 3 returns
    # surplus above), so the battery is never drained past the
    # self-consumption floor. Solar-gated (real surplus required); pure
    # amps — SEM issues no battery command, the actuator clamps to the
    # charger max. Supersedes the #501 "top up to EV minimum only" cap.
    # Confirmed live 2026-06-26 that the car follows a higher offer
    # (Zoe: 8A→3.4kW vs 10A→5.3kW).
    return surplus + potential


def _relabel(decision: ChargerDecision, mode: str, prefix: str) -> ChargerDecision:
    """Re-stamp a decision delegated to another mode's strategy.

    Modes that fall back to another strategy's ``decide()`` must
    not leak the inner mode/reason verbatim: RienduPre's #461 dump
    showed ``charging_strategy: "solar_only: …"`` on a charger
    configured ``solar_plus_cheap``, reading like the configured
    mode was ignored. The relabel keeps the inner detail but names
    the configured mode and why it delegated.
    """
    return replace(
        decision, mode=mode, reason=f"{prefix} — {decision.reason}",
    )


def amps_from_watts(watts: float, phases: int, voltage: int) -> int:
    """Watts → whole amps (round down). The actuator (Step 4)
    clamps to ``[min_current_a, max_current_a]``."""
    denom = max(1, phases * voltage)
    return int(watts // denom)


def effective_min_amps(cfg: dict, fallback: int = 6) -> int:
    """Effective per-charger minimum current.

    Combines two SEM-side floors via three-way max (ADR 0010 pattern 3,
    #440):
      * ``ev_min_current`` — the user's chosen SEM-side floor (the
        per-charger minimum).
      * ``vehicle_min_current`` — per-vehicle handshake floor (e.g. a
        Renault Zoe needs ~9 A; if the user records that here, SEM
        won't offer 6 A and watch the contactor sit unused).
    The third leg of the max — the EVSE hardware minimum — is enforced
    in the adapter, not at the decide layer, so it doesn't appear here.

    Safety: the returned floor is also clamped to ``ev_max_current`` to
    prevent a misconfigured ``vehicle_min_current`` (e.g. 20 A on a 16 A
    circuit because the slider's max wasn't lowered) from pinning the
    commanded current above the circuit breaker via the downstream
    ``max(min, min(max, surplus))`` clamp. Reviewer-flagged 2026-06-06.

    Returns:
        ``min(ev_max_current, max(loadpoint_min, vehicle_min or 0))`` as int.
    """
    loadpoint_min = int(cfg.get("ev_min_current", fallback)) if isinstance(cfg, dict) else fallback
    effective = loadpoint_min
    if isinstance(cfg, dict):
        v = cfg.get("vehicle_min_current")
        if v is not None and v != "":
            try:
                effective = max(loadpoint_min, int(v))
            except (TypeError, ValueError):
                pass
        # Defensive clamp: never let the floor exceed the user-set
        # circuit max. If misconfigured the surplus_amps clamp would
        # otherwise pin commanded current at max.
        max_amps_raw = cfg.get("ev_max_current")
        if max_amps_raw is not None:
            try:
                effective = min(effective, int(max_amps_raw))
            except (TypeError, ValueError):
                pass
    return effective


# Tariff levels where holding minimum current to bridge a deficit would
# import EXPENSIVE grid — exactly what min_plus_solar / solar_plus_cheap
# exist to avoid (#524). ``cheap`` / ``very_cheap`` and unknown/static
# (tariff_level None) are bridgeable. Canonical here (decide owns tariff
# classification); charge_stability reads the resulting ``bridgeable`` flag.
_NOT_CHEAP_LEVELS = frozenset({"normal", "expensive", "very_expensive"})


def _idle_bridgeable(view: ChargerView) -> tuple[bool, str]:
    """Classify an IDLE decision: TRANSIENT dip (worth holding the contactor
    through to avoid flapping the car) vs STRUCTURAL stop (the stability
    bridge must NOT hold it — holding would import grid).

    Single source of truth (#461): the SoC / surplus / solar / tariff data
    all live here, so ``decide`` makes the call once and stamps it on the
    decision. ``charge_stability`` then reads ``decision.bridgeable`` instead
    of re-deriving the same truth — honouring the ChargerDecision contract
    ('all fields computed once in decide, no re-derivation downstream').

    Returns ``(bridgeable, why)``. ``why`` is empty when bridgeable; when
    structural it names the cause for the strategy-sensor reason (preserving
    the diagnostics that the bridge used to emit).

    STRUCTURAL (returns False) when ANY of:
      * the sun is effectively gone (``solar_w < min_solar_w``) — deep
        darkness, nothing to bridge to (#461 part 2);
      * a not-cheap tariff window (#524) — holding imports expensive grid;
      * the battery can't assist (``battery_soc < buffer_soc``) AND the real
        EV surplus (solar − home − reserved battery) can't sustain even the
        minimum charge — solar is high but fully consumed by the house /
        reserved for a below-buffer battery, so the hold imports grid
        (PROD 2026-06-27).
    Otherwise TRANSIENT (real surplus or battery assist, cheap/unknown
    tariff) → the full bridge is worth it.
    """
    f = view.fleet
    if float(f.solar_w) < float(f.min_solar_w):
        return False, (
            f"sun gone (solar {f.solar_w:.0f}W < {f.min_solar_w:.0f}W)"
        )
    if f.tariff_level in _NOT_CHEAP_LEVELS:
        return False, f"not-cheap tariff ({f.tariff_level})"
    cfg = view.config if isinstance(view.config, dict) else {}
    min_amps = effective_min_amps(cfg, 6)
    phases = int(cfg.get("ev_phases", 3))
    voltage = int(cfg.get("ev_voltage", 230))
    min_charge_w = min_amps * max(1, phases) * max(1, voltage)
    real_surplus_w = self_consumption_surplus_w(view)
    if float(f.battery_soc) < float(f.buffer_soc) and real_surplus_w < min_charge_w:
        return False, (
            f"no battery assist (SoC {f.battery_soc:.0f}% < buffer "
            f"{f.buffer_soc:.0f}%) + EV surplus {real_surplus_w:.0f}W "
            f"< min charge {min_charge_w:.0f}W"
        )
    return True, ""


# ─────────────────────────────────────────────────────────────────
# Mode strategy protocol
# ─────────────────────────────────────────────────────────────────

class ModeStrategy(ABC):
    """One ``decide`` implementation per charge mode.

    Subclasses are pure: no ``self`` state, no instance attributes.
    Instantiated once at module import time, called by ``decide()``
    for every (charger, cycle) tuple.
    """

    @abstractmethod
    def decide(self, view: ChargerView) -> ChargerDecision:
        """Compute the per-cycle decision for this mode."""


# ─────────────────────────────────────────────────────────────────
# off — explicit user disable
# ─────────────────────────────────────────────────────────────────

class OffMode(ModeStrategy):
    """No charging, ever. Adapter calls ``command_disable()`` so
    KEBA-class firmware actually opens the contactor (#315)."""

    def decide(self, view: ChargerView) -> ChargerDecision:
        return ChargerDecision(
            charger_id=view.power.charger_id,
            mode="off",
            intent=ChargerIntent.DISABLE,
            commanded_amps=0,
            budget_w=0.0,
            reason="off mode — user-explicit disable",
        )


# ─────────────────────────────────────────────────────────────────
# always_max — full power regardless of source
# ─────────────────────────────────────────────────────────────────

class AlwaysMaxMode(ModeStrategy):
    """Charge at hardware max. Grid backfill expected."""

    def decide(self, view: ChargerView) -> ChargerDecision:
        if not view.power.connected:
            return ChargerDecision(
                charger_id=view.power.charger_id,
                mode="always_max",
                intent=ChargerIntent.IDLE,
                reason="always_max mode but EV disconnected",
            )
        return ChargerDecision(
            charger_id=view.power.charger_id,
            mode="always_max",
            intent=ChargerIntent.CHARGE_MAX,
            commanded_amps=0,  # adapter resolves from device.max_current
            budget_w=0.0,  # not budget-limited
            reason="always_max mode — charge at hardware maximum",
        )


# ─────────────────────────────────────────────────────────────────
# solar_only — strict surplus, never grid import
# ─────────────────────────────────────────────────────────────────

class SolarOnlyMode(ModeStrategy):
    """Charge only from solar surplus. Never imports grid for EV.

    Below ``min_power_threshold`` (the charger's
    ``min_current_a * phases * voltage``), the actuator must idle
    rather than command sub-min amps — KEBA would reject and
    self-charge (#353). Decision returns ``IDLE`` with
    ``budget_w`` set so the dashboard shows the available surplus.
    """

    MIN_AMPS_FALLBACK = 6
    PHASES_FALLBACK = 3
    VOLTAGE_FALLBACK = 230

    def decide(self, view: ChargerView) -> ChargerDecision:
        f = view.fleet
        cid = view.power.charger_id

        if not view.power.connected:
            return ChargerDecision(
                charger_id=cid, mode="solar_only",
                intent=ChargerIntent.IDLE,
                reason="solar_only mode but EV disconnected",
            )

        # (#634) The "At least" floor is a mode-independent GUARANTEE: at
        # night, when the day's solar under-delivered the floor, top up the
        # DIFFERENCE from grid (the shared night decision — deadline-sized,
        # peak-managed #630). Floor 0 keeps the classic behaviour below:
        # solar_only never grids at night (#346).
        if f.is_night and view.target_kwh is not None and view.target_kwh > 0.1:
            return night_top_up_decision(view, "solar_only")

        # No meaningful solar → idle. At night this fires immediately
        # (solar=0) producing the #346-correct behaviour: solar_only
        # at night never imports grid.
        if f.solar_w < f.min_solar_w:
            return ChargerDecision(
                charger_id=cid, mode="solar_only",
                intent=ChargerIntent.IDLE,
                reason=(
                    f"solar_only: solar={f.solar_w:.0f}W < "
                    f"{f.min_solar_w:.0f}W threshold"
                ),
            )

        # Compute surplus available to EV. Bare surplus subtracts
        # battery_charge_w when SOC < auto_start_soc — the battery
        # has priority on solar in that band.
        bare_surplus_w = self_consumption_surplus_w(view)

        # Forecast-aware battery_charge redirect. The v1.6.x
        # ``calculate_canonical_ev_budget(SOLAR_ONLY)`` branch added
        # this on top of bare surplus; ported here so the strategy
        # decision sees the same effective budget the canonical
        # method will compute. Without the parity, a viable
        # SOLAR_ONLY cycle (high forecast, modest surplus) collapses
        # to IDLE before the canonical SOLAR_ONLY math gets a chance
        # to run — the regression
        # ``tests/scenarios/2026-05-29_budget_unify_redirect.yaml``
        # pins.
        # #576 P2.2 — avoid the double-count: when the position rule already
        # reclaims the battery charge (bare_surplus stops subtracting it), the
        # forecast redirect must NOT add it a second time. The redirect stays
        # only as the fallback for when the EV does NOT reclaim by position
        # (below the battery, or below the reserve floor) — its original role.
        from .flow_calculator import battery_redirect_w as _redirect
        redirect_w = 0.0 if _ev_reclaims(view) else _redirect(
            f.battery_charge_w, f.battery_soc,
            f.battery_capacity_kwh, f.forecast_remaining_kwh,
        )
        surplus_w = bare_surplus_w + redirect_w

        # The actuator/adapter knows the real min — for the decide
        # we use a sensible fallback (6 A × 3 × 230 V = 4140 W) so
        # the decision is correct even without the adapter wired in.
        # Step 4 will route min through the adapter.
        cfg = view.config
        min_amps = effective_min_amps(cfg, self.MIN_AMPS_FALLBACK)
        phases = int(cfg.get("ev_phases", self.PHASES_FALLBACK)) \
            if isinstance(cfg, dict) else self.PHASES_FALLBACK
        voltage = int(cfg.get("ev_voltage", self.VOLTAGE_FALLBACK)) \
            if isinstance(cfg, dict) else self.VOLTAGE_FALLBACK
        min_w = min_amps * phases * voltage

        if surplus_w < min_w:
            return ChargerDecision(
                charger_id=cid, mode="solar_only",
                intent=ChargerIntent.IDLE,
                budget_w=surplus_w,
                reason=(
                    f"solar_only: surplus={surplus_w:.0f}W "
                    f"(bare={bare_surplus_w:.0f}W + redirect={redirect_w:.0f}W) "
                    f"< min={min_w}W (={min_amps}A) — idle"
                ),
            )

        max_amps = int(cfg.get("ev_max_current", 32)) \
            if isinstance(cfg, dict) else 32
        amps = max(min_amps, min(max_amps, amps_from_watts(surplus_w, phases, voltage)))
        return ChargerDecision(
            charger_id=cid, mode="solar_only",
            intent=ChargerIntent.CHARGE_AT_AMPS,
            commanded_amps=amps, budget_w=surplus_w,
            reason=(
                f"solar_only: surplus={surplus_w:.0f}W "
                f"(bare={bare_surplus_w:.0f}W + redirect={redirect_w:.0f}W) "
                f"→ {amps}A (solar={f.solar_w:.0f}W, home={f.home_w:.0f}W, "
                f"batt_chg={f.battery_charge_w:.0f}W)"
            ),
        )


# ─────────────────────────────────────────────────────────────────
# min_plus_solar — solar surplus + Min floor at night
# ─────────────────────────────────────────────────────────────────

def night_top_up_decision(view: "ChargerView", mode_name: str) -> "ChargerDecision":
    """(#634) The shared overnight floor top-up decision — the "At least"
    guarantee. The MODE is the daytime axis; ANY night-capable mode delegates
    here (min_plus_solar always; solar_only when its floor > 0). Overnight
    source is GRID by design — never the home battery (#634 standing rule);
    internally this is the #620 three-source axis with the source
    auto-derived (floor>0 ⇒ grid, floor=0 ⇒ off), no GUI surface.
    Inherits the #630 peak-managed top-up rate and the deadline sizing."""
    cid = view.power.charger_id

    # Already at Min — idle.
    if view.target_kwh is not None and view.target_kwh <= 0.1:
        return ChargerDecision(
            charger_id=cid, mode=mode_name,
            intent=ChargerIntent.IDLE,
            reason=(
                f"{mode_name} night: target reached "
                f"(remaining={view.target_kwh:.2f} kWh)"
            ),
        )

    # (#638) The planning layer placed this charge in a later window.
    #
    # Sits BELOW target-reached, so a charge that simply finished is never
    # reported as waiting — and ABOVE every charge branch below, because
    # this function is the ONE seam all three night-capable modes funnel
    # through (``solar_only`` and ``min_plus_solar`` call it directly,
    # ``solar_plus_cheap`` via ``_decide_night``). Putting the check here
    # rather than in each mode is the whole point: the 2026-06-02 fix
    # repaired ``solar_plus_cheap`` alone and left the class standing in
    # its two siblings, which is how PROD came to finish a charge on
    # 2026-08-06 half an hour before its own planned window opened.
    #
    # Safe to obey unconditionally: ``overnight_actuation.ev_overlay``
    # only raises ``hold`` after PROVING the remaining blocks can still
    # deliver what is owed, and stands down entirely for a forcing
    # deadline or an unreachable floor. A hold is never a mere preference.
    if view.plan.hold:
        detail = f" — {view.plan.reason}" if view.plan.reason else ""
        if view.plan.until is not None:
            detail += f" (until {view.plan.until:%H:%M})"
        return ChargerDecision(
            charger_id=cid, mode=mode_name,
            intent=ChargerIntent.IDLE,
            reason=f"{mode_name} night: waiting for the planned window{detail}",
        )

    cfg = view.config if isinstance(view.config, dict) else {}
    min_amps = effective_min_amps(cfg, 6)
    max_amps = int(cfg.get("ev_max_current", 32))

    # Deadline override (#246) — the planner pre-computed the
    # required current and put it on the view. If the deadline
    # is active, use it as the floor.
    if view.deadline_amps > 0:
        # (#630 precedence fix) The deadline gives the REQUIRED floor; the
        # peak-managed top-up rate (#630) may charge FASTER than required —
        # finish early, free the window. Take whichever is higher, clamped.
        # Pre-fix the deadline branch shadowed top_up_amps entirely, so the
        # peak-managed rate never engaged at night (deadline_amps is always
        # >0 once a night window resolves).
        governed = max(view.deadline_amps, view.top_up_amps)
        amps = min(max_amps, max(min_amps, governed))
        tag = " (peak-managed)" if view.top_up_amps > view.deadline_amps else ""
        return ChargerDecision(
            charger_id=cid, mode=mode_name,
            intent=ChargerIntent.CHARGE_AT_AMPS,
            commanded_amps=amps,
            reason=(
                f"{mode_name} night: deadline floor {amps}A{tag}, "
                f"remaining {view.target_kwh:.1f} kWh"
            ),
        )

    # Plain night top-up. (#630) Run at the peak-managed headroom rate
    # when the planner computed one — finish early and free the window
    # for lower-priority cheap-hours loads — else the legacy Min floor.
    amps = max(min_amps, min(max_amps, view.top_up_amps)) \
        if view.top_up_amps > 0 else min_amps
    remaining_str = (
        f"{view.target_kwh:.1f}" if view.target_kwh is not None else "?"
    )
    return ChargerDecision(
        charger_id=cid, mode=mode_name,
        intent=ChargerIntent.CHARGE_AT_AMPS,
        commanded_amps=amps,
        reason=(
            f"{mode_name} night: top-up at {amps}A"
            + (" (peak-managed)" if amps != min_amps else "")
            + f", remaining {remaining_str} kWh"
        ),
    )




class MinPlusSolarMode(ModeStrategy):
    """Daytime: zone-aware surplus (same as solar_only when SOC
    high enough). Night: top up to ``target_kwh`` Min floor using
    grid (#245).
    """

    def decide(self, view: ChargerView) -> ChargerDecision:
        f = view.fleet
        cid = view.power.charger_id

        if not view.power.connected:
            return ChargerDecision(
                charger_id=cid, mode="min_plus_solar",
                intent=ChargerIntent.IDLE,
                reason="min_plus_solar but EV disconnected",
            )

        if f.is_night:
            return self._decide_night(view)
        return self._decide_day(view)

    def _decide_night(self, view: ChargerView) -> ChargerDecision:
        return night_top_up_decision(view, "min_plus_solar")

    def _decide_day(self, view: ChargerView) -> ChargerDecision:
        """Daytime min_plus_solar: Zone-aware battery assist on top
        of solar surplus. Zone 4 (SOC≥90) drains battery to EV;
        Zone 3 (SOC≥70) discharges battery if it's already; Zone 2
        is pure solar (same as solar_only); Zone 1 idles."""
        f = view.fleet
        cid = view.power.charger_id
        if not view.power.connected:
            return ChargerDecision(
                charger_id=cid, mode="min_plus_solar",
                intent=ChargerIntent.IDLE,
                reason="min_plus_solar day: EV disconnected",
            )
        zone = soc_zone(f.battery_soc, f.auto_start_soc, f.buffer_soc, f.priority_soc)
        # Zone 1: battery priority — never charge EV from anywhere
        # when battery is below priority_soc.
        if zone == 1:
            return ChargerDecision(
                charger_id=cid, mode="min_plus_solar",
                intent=ChargerIntent.IDLE,
                reason=(
                    f"min_plus_solar day: Zone 1 "
                    f"(SOC={f.battery_soc:.0f}% < priority="
                    f"{f.priority_soc:.0f}%) — battery priority"
                ),
            )
        # Zone 2: pure solar (same as solar_only).
        if zone == 2:
            return _relabel(
                _SOLAR_ONLY.decide(view), "min_plus_solar",
                f"min_plus_solar day Zone 2 (SOC={f.battery_soc:.0f}%)",
            )
        # Zone 3 / 4: surplus + capped SOC-based battery assist (#501).
        # The budget uses the battery's POTENTIAL (never gated on
        # currently-flowing discharge — that was the #439
        # chicken-and-egg) capped at ``battery_assist_max_power``.
        budget_w = battery_assist_budget_w(view)
        cfg = view.config if isinstance(view.config, dict) else {}
        min_amps = effective_min_amps(cfg, 6)
        max_amps = int(cfg.get("ev_max_current", 32))
        phases = int(cfg.get("ev_phases", 3))
        voltage = int(cfg.get("ev_voltage", 230))
        surplus_amps = amps_from_watts(budget_w, phases, voltage)

        # Need-gated min floor (#501, amends ADR 0010 pattern 1).
        # The mode's Min guarantee lives in the night top-up; the
        # daytime floor (commit-then-measure, grid backfills) engages
        # ONLY when tonight's window can no longer deliver the
        # remaining Min at max current — i.e. when waiting genuinely
        # risks the guarantee. Pre-#501 the floor was unconditional
        # in Zone 3/4: a cloudy afternoon at 70-90% SOC ground the
        # home battery into the EV with sustained grid backfill, and
        # the floor even applied after Min was already met.
        remaining = view.target_kwh
        floor_needed = (
            remaining is not None
            and remaining > 0.1
            and remaining > view.night_deliverable_kwh
        )
        if floor_needed:
            amps = max(min_amps, min(max_amps, surplus_amps))
            return ChargerDecision(
                charger_id=cid, mode="min_plus_solar",
                intent=ChargerIntent.CHARGE_AT_AMPS,
                commanded_amps=amps, budget_w=budget_w,
                reason=(
                    f"min_plus_solar day Zone {zone}: Min floor engaged "
                    f"({remaining:.1f} kWh remaining > "
                    f"{view.night_deliverable_kwh:.1f} kWh night-deliverable) "
                    f"→ {amps}A (budget={budget_w:.0f}W, floor={min_amps}A)"
                ),
            )
        if surplus_amps >= min_amps:
            amps = min(max_amps, surplus_amps)
            return ChargerDecision(
                charger_id=cid, mode="min_plus_solar",
                intent=ChargerIntent.CHARGE_AT_AMPS,
                commanded_amps=amps, budget_w=budget_w,
                reason=(
                    f"min_plus_solar day Zone {zone}: budget={budget_w:.0f}W "
                    f"→ {amps}A (solar surplus + capped battery assist)"
                ),
            )
        remaining_str = f"{remaining:.1f}" if remaining is not None else "?"
        return ChargerDecision(
            charger_id=cid, mode="min_plus_solar",
            intent=ChargerIntent.IDLE,
            reason=(
                f"min_plus_solar day Zone {zone}: budget={budget_w:.0f}W "
                f"below {min_amps}A min — Min ({remaining_str} kWh) is "
                f"covered by the night window, staying self-consumption-only"
            ),
        )


# ─────────────────────────────────────────────────────────────────
# solar_plus_cheap — solar + cheap-tariff windows at night
# ─────────────────────────────────────────────────────────────────

class SolarPlusCheapMode(ModeStrategy):
    """During day: solar_only behaviour, but pauses during
    expensive tariff windows. At night: charge during the
    cheapest hours only (#247).
    """

    EXPENSIVE_LEVELS = frozenset({"expensive", "very_expensive"})

    def decide(self, view: ChargerView) -> ChargerDecision:
        f = view.fleet
        cid = view.power.charger_id

        if not view.power.connected:
            return ChargerDecision(
                charger_id=cid, mode="solar_plus_cheap",
                intent=ChargerIntent.IDLE,
                reason="solar_plus_cheap but EV disconnected",
            )

        # Day during expensive tariff window → fall back to pure
        # solar_only behaviour (the #247 daytime pause).
        if not f.is_night and f.tariff_level in self.EXPENSIVE_LEVELS:
            return _relabel(
                _SOLAR_ONLY.decide(view), "solar_plus_cheap",
                f"solar_plus_cheap day: tariff={f.tariff_level} "
                f"→ pausing grid imports",
            )

        # Day, normal/cheap tariff: solar surplus only (same as
        # min_plus_solar day path).
        if not f.is_night:
            return _relabel(
                _SOLAR_ONLY.decide(view), "solar_plus_cheap",
                f"solar_plus_cheap day: tariff={f.tariff_level}",
            )

        # Night → the shared night decision, which consults the planning
        # layer's verdict for EVERY mode (#638). This mode used to carry
        # its own private copy of that check, reading
        # ``config["_tariff_wait"]``; it was the only one that did, and
        # the two siblings that didn't charged straight through the plan.
        # One seam, no per-mode copies to keep in sync.
        return _MIN_PLUS_SOLAR._decide_night(view)


# ─────────────────────────────────────────────────────────────────
# Dispatcher
# ─────────────────────────────────────────────────────────────────

_OFF = OffMode()
_ALWAYS_MAX = AlwaysMaxMode()
_SOLAR_ONLY = SolarOnlyMode()
_MIN_PLUS_SOLAR = MinPlusSolarMode()
_SOLAR_PLUS_CHEAP = SolarPlusCheapMode()

MODE_STRATEGIES: Dict[str, ModeStrategy] = {
    "off": _OFF,
    "always_max": _ALWAYS_MAX,
    "solar_only": _SOLAR_ONLY,
    "min_plus_solar": _MIN_PLUS_SOLAR,
    "solar_plus_cheap": _SOLAR_PLUS_CHEAP,
}


def decide(view: ChargerView) -> ChargerDecision:
    """Compute the per-charger per-cycle decision.

    Pure function. Dispatches by ``view.mode`` to the matching
    :class:`ModeStrategy`. Unknown modes fall back to ``off``
    (DISABLE) — loud failure mode is preferable to charging from
    grid when the user didn't ask for it.
    """
    # Max-SOC ceiling — stop in EVERY mode once the car hits its
    # configured max target (#548). The ceiling is computed upstream
    # (``_calculate_remaining_need(bound="max")``); previously it only
    # reached the retired ChargingStateMachine (soc_limit_active →
    # SOLAR_TARGET_REACHED), which the per-charger decision clobbered, so
    # the EV charged past the max SOC during solar surplus. Guard before
    # mode dispatch so solar_only / min_plus_solar / always_max /
    # solar_plus_cheap all honour it. Skip while disconnected so a stale
    # ceiling can't suppress the "idle — disconnected" reason.
    if view.soc_ceiling_reached and view.power.connected:
        # Max SOC/target is a STRUCTURAL stop — never bridge it.
        return ChargerDecision(
            charger_id=view.power.charger_id, mode=view.mode,
            intent=ChargerIntent.IDLE, bridgeable=False,
            reason=f"{view.mode}: max SOC/target reached — stop charging (#548)",
        )

    strategy = MODE_STRATEGIES.get(view.mode)
    if strategy is None:
        _LOGGER.error(
            "decide: unknown mode %r for charger %s — falling back to OFF",
            view.mode, view.power.charger_id,
        )
        return _OFF.decide(view)
    result = strategy.decide(view)
    # Single source of truth for the stability bridge (#461): classify an
    # IDLE as transient (hold) vs structural (stop now) HERE, where the SoC /
    # surplus / tariff data lives, and stamp it on the decision. The bridge
    # reads ``decision.bridgeable`` instead of re-deriving it. CHARGE/DISABLE
    # decisions keep the default (bridgeable=True, irrelevant to them).
    # Only DAY idles matter: the stability bridge bypasses at night (the night
    # planner owns start/stop), so classifying a night idle would just append a
    # misleading "[structural: sun gone]" to "target reached" / "waiting for
    # cheaper". Leave night idles at the default bridgeable=True (ignored).
    if result.intent is ChargerIntent.IDLE and not view.fleet.is_night:
        bridgeable, why = _idle_bridgeable(view)
        if bridgeable:
            result = replace(result, bridgeable=True)
        else:
            result = replace(
                result, bridgeable=False,
                reason=f"{result.reason} [structural: {why}]",
            )

    # (#747) PEAK SHED is a guarantee, senior to every mode — always_max
    # included: its "grid backfill expected" promise ends where the house's
    # peak defense begins. The load manager's actuation exclusion stays
    # (#649: one writer per device); THIS clamp is the compensating control
    # that exclusion always assumed, firing on the FIRST cycle of a shed
    # level — before the LM's delayed progressive shed reaches anyone's
    # freezer. Only real charging offers clamp; idle/disable have nothing
    # to shed.
    peak = getattr(view.fleet, "peak_state", "normal") or "normal"
    if peak in ("shedding", "emergency") and result.intent in (
            ChargerIntent.CHARGE_AT_AMPS, ChargerIntent.CHARGE_MAX):
        if peak == "emergency":
            return replace(
                result, intent=ChargerIntent.IDLE, commanded_amps=0,
                budget_w=0.0, bridgeable=False,
                reason=f"{result.reason} [peak EMERGENCY — EV sheds first]",
            )
        min_a = effective_min_amps(dict(view.config), 6)
        if (result.intent is ChargerIntent.CHARGE_MAX
                or result.commanded_amps > min_a):
            wpa = (float(view.config.get("ev_phases") or 3)
                   * float(view.config.get("ev_voltage") or 230))
            return replace(
                result, intent=ChargerIntent.CHARGE_AT_AMPS,
                commanded_amps=min_a, budget_w=min_a * wpa,
                reason=f"{result.reason} [peak SHEDDING — clamped to {min_a}A]",
            )
    return result
