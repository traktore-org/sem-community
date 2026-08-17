"""Per-device primary types (arch/multi-charger-primary, v1.7.0).

Naming note: the module is called ``charger_types`` for historical
reasons (it started as EV-only). With v1.7.0's
arch/multi-inverter-battery-primary work it also houses
``InverterPower`` and ``BatteryPower``. Future rename to
``per_device_types`` is a cleanup task.



The multi-charger architecture migration moves SEM's data model from
``fleet-primary + per_charger shadow dicts`` (the v1.4.0 → v1.6.16
pattern) to ``per-charger-primary + fleet computed view`` (this file).

Every type here is **frozen** — immutable for the lifetime of a
control cycle. The cycle pipeline is:

    sensors  →  Dict[charger_id, ChargerPower]
                                |
                                v
    for each charger:  ChargerView = build_view(...)        ← pure
                       ChargerDecision = decide(view)        ← pure
                       actuate(adapter, decision)            ← side-effect

    FleetView is computed from the per-charger dict as a @property.

No field on these types is mutated after construction. Replace via
``dataclasses.replace(view, foo=bar)`` if you need an evolution.

These types do not yet replace ``PowerReadings.ev_power`` or any of
the fleet shadow dicts in :mod:`coordinator.types` — that swap happens
in Step 6 of the architecture migration. For now they coexist; the
adapter / decide / actuate steps (2, 3, 4) build against these types
and the legacy types simultaneously.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from .plan_verdict import PlanVerdict


# ─────────────────────────────────────────────────────────────────
# Intent enum — what the decide step says the actuator must do
# ─────────────────────────────────────────────────────────────────

class ChargerIntent(Enum):
    """The actuator's command target, derived from ``ChargerDecision``.

    Intent is what we want the charger to BE doing — orthogonal to
    mode (user choice) and state (state-machine label). One intent
    maps cleanly to one ``ChargerAdapter`` method call. The mapping:

        IDLE              → adapter.command_idle()
        CHARGE_AT_AMPS    → adapter.command_current(amps)
        CHARGE_MAX        → adapter.command_max()
        DISABLE           → adapter.command_disable()

    Pre-architecture this was implicit in 200+ lines of branching
    inside ``_execute_ev_control``. Making it a first-class enum
    surfaces all the cases and lets the adapter encapsulate brand
    quirks (KEBA's 6A min, KEBA's self-resume, etc.) without
    polluting the actuator.
    """

    IDLE = "idle"
    """No charging; contactor open. Distinct from DISABLE in that
    IDLE is a temporary state (waiting for surplus), DISABLE is a
    permanent user-explicit OFF intent."""

    CHARGE_AT_AMPS = "charge_at_amps"
    """Charge at a specific amperage. The amps value comes from
    ``ChargerDecision.commanded_amps``."""

    CHARGE_MAX = "charge_max"
    """Charge at the charger's max — ``always_max`` mode or NOW
    strategy. The adapter resolves max from device config."""

    DISABLE = "disable"
    """User-explicit OFF — ``charge_mode = off``. The adapter MUST
    invoke the brand-specific disable (e.g. ``keba.disable``) so
    the contactor opens. Self-resume must be re-asserted every
    cycle until power drops below the handshake threshold."""


# ─────────────────────────────────────────────────────────────────
# Per-charger instantaneous power
# ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ChargerPower:
    """One charger's instantaneous draw + connection state.

    Replaces the per-cycle reads of
    ``power.ev_power_per_charger[cid]`` /
    ``power.ev_connected_per_charger[cid]`` /
    ``power.ev_charging_per_charger[cid]`` scattered across the
    coordinator. The fleet sum at ``PowerReadings.ev_power`` becomes
    a ``@property`` over the per-charger dict in Step 6 of the
    migration.

    Sign: power_w >= 0 always (chargers don't discharge in SEM's
    supported brands). 0 W is handshake idle (~110 W on KEBA at
    plug-in); 500 W is SEM's "actually charging" threshold (#315/
    #346/#353).
    """

    charger_id: str
    power_w: float = 0.0
    connected: bool = False
    charging: bool = False
    """``charging`` is the brand sensor's own boolean (e.g.
    ``binary_sensor.keba_p30_charging_state``). On KEBA it lags
    real draw by ~5 s (#289); consumers should prefer
    ``power_w > 500`` for the "actually charging" decision and
    treat ``charging`` as informational."""


# ─────────────────────────────────────────────────────────────────
# Per-inverter instantaneous reading (v1.7.0 arch follow-up)
# ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class InverterPower:
    """One inverter's instantaneous power reading.

    Inverters are SOURCES — SEM observes them, doesn't command them
    (the inverter brand integration handles its own modes). The
    per-inverter dict on :class:`PowerReadings` replaces what was a
    single fleet ``solar_power`` field summed in ``sensor_reader``
    (multi-inverter Pattern E in CLAUDE.md, ``solar_power_list``).

    Fleet sum invariant:
        ``PowerReadings.fleet_solar_w ==
         sum(i.power_w for i in PowerReadings.inverters.values())``

    Pinned in ``tests/test_step8_invariants.py`` (Step 8 follow-up).
    """

    inverter_id: str
    """Stable identifier — entity name when populated by sensor_reader,
    or test fixture id. Used as the dict key."""

    power_w: float = 0.0
    """Instantaneous AC output (W). ≥ 0 by SEM convention."""

    # (#771) ``daily_kwh`` used to sit here. ``sensor_reader`` builds this
    # snapshot from an instantaneous power read and has no per-inverter energy
    # counter to fill it from, so it was 0.0 on every install ever — a
    # measurement-shaped default, which is #755 contract 1. Per-inverter daily
    # energy needs a producer before it needs a field.

    name: str = ""
    """Human-readable label (e.g. "SUN2000-1") for dashboard display."""


# ─────────────────────────────────────────────────────────────────
# Per-battery instantaneous reading (v1.7.0 arch follow-up)
# ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BatteryPower:
    """One home battery's instantaneous power + state.

    Like inverters, batteries are OBSERVED, not commanded by SEM
    (the battery brand integration owns its own control loop;
    SEM only requests battery_priority via the inverter side).

    Fleet sum invariant:
        ``PowerReadings.fleet_battery_w ==
         sum(b.power_w for b in PowerReadings.batteries.values())``

    Sign: positive = charging, negative = discharging — matches
    SEM convention (CLAUDE.md).
    """

    battery_id: str
    """Stable identifier — entity name when populated by sensor_reader."""

    power_w: float = 0.0
    """Instantaneous power (W). + = charge, − = discharge."""

    soc_pct: Optional[float] = None
    """State of charge (0-100), or ``None`` while this unit's SOC is
    unresolved — undetected sensor or a modbus source still warming
    after a restart (#694: publishing 0.0 there made a warming battery
    indistinguishable from an empty one). Fleet SOC is the
    capacity-weighted average over the RESOLVED units."""

    capacity_kwh: float = 0.0
    """Nameplate capacity for this unit. Used by the fleet SOC
    weighted average + battery_assist budget math."""

    # (#771) ``daily_charge_kwh`` / ``daily_discharge_kwh`` deleted — same
    # reason as ``InverterPower.daily_kwh``: nothing ever wrote them.

    name: str = ""


# ─────────────────────────────────────────────────────────────────
# Per-device RUNTIME state (Group A + B of the arch follow-up)
# ─────────────────────────────────────────────────────────────────
#
# Runtime types are MUTABLE — they hold per-cycle state that evolves
# across the coordinator's lifetime: availability flags, last-known
# values used by smoothing fallbacks.
#
# Distinct from the FROZEN ``InverterPower`` / ``BatteryPower``
# types above — those are snapshots of the per-cycle SENSOR reading.
# The runtime is the persistent record across cycles.
#
# (#771) There is no ``InverterRuntime``. There was one — declared in the
# v1.7.0 arch follow-up alongside its per-inverter dict on ``EnergyTotals``,
# with a daily-kWh accumulator, an availability flag and a docstring claiming
# it drove a ``sensor.sem_inverter_<id>_available`` binary sensor. Nothing
# ever constructed one, on any path, so every field on it was dead and the
# binary sensor never existed. It is deleted rather than wired up: inverters
# are observed-only, and their fleet total is already reconciled against the
# per-string breakdown in ``HealthCheck.check_ledger_partitions``.

@dataclass
class BatteryRuntime:
    """Coordinator-level state for ONE home battery.

    Unlike inverters, batteries DO get the full decide/actuate
    treatment (Group B of this PR) — they have a real command
    surface (discharge limiting, forced charge). But the runtime
    dataclass itself is just the persistent state; the adapter
    holds the brand-specific service-call details.
    """

    battery_id: str
    # (#771) No ``daily_charge_kwh`` / ``daily_discharge_kwh`` /
    # ``daily_kwh_date`` — the coordinator builds this runtime from a power
    # reading (``_run_battery_pipeline``) and never had a per-battery energy
    # counter to fill them from. The fleet battery rows are the real ledger.
    last_known_soc: float = 0.0
    last_known_w: float = 0.0
    capacity_kwh: float = 0.0
    """Nameplate capacity of this unit. Used by the fleet
    capacity-weighted SOC and by the scheduler's deficit math."""
    available: bool = True
    name: str = ""


# ─────────────────────────────────────────────────────────────────
# (#771) There are no per-inverter / per-battery flow slices
# ─────────────────────────────────────────────────────────────────
#
# ``InverterFlows`` and ``BatteryFlows`` were declared here as the
# per-inverter and per-battery mirrors of ``ChargerFlows``, above a
# comment asserting that
#   sum(flows.per_inverter[i].solar_to_X) == flows.solar_to_X
# "holds by construction". It did not hold by construction or any
# other way: ``PowerFlows`` has ``per_charger`` and nothing else, so
# there was no container for the slices, and ``flow_calculator``
# never built one. The invariant was a claim about an algorithm that
# does not exist, and the only tests were frozen-dataclass shape pins
# — theorems about ``@dataclass(frozen=True)``.
#
# That is #771's complaint in its purest form: a per-device row that
# READS as reconciled against the fleet identity while nothing
# computes it. Deleted rather than filled in, because filling it in
# means writing the attribution first and the type after.
#
# ``ChargerFlows`` stays and is real: ``flow_calculator`` fills
# ``PowerFlows.per_charger`` in priority order and integrates it into
# ``EnergyFlows.per_charger``, which is what
# ``HealthCheck.check_ledger_partitions`` reconciles.


# ─────────────────────────────────────────────────────────────────
# Battery decide/actuate types (Group B Steps 2-4)
# ─────────────────────────────────────────────────────────────────

class BatteryIntent(Enum):
    """What ``actuate_battery`` should ask the adapter to do.

    Mirrors :class:`ChargerIntent` for batteries. One intent maps to
    exactly one adapter method — the actuator doesn't branch on
    brand or anything else.
    """

    NORMAL = "normal"
    """Default discharge limit (the brand's hardware max).
    Adapter calls ``number.set_value(max_discharge_w)`` or
    equivalent. The "no protection active, no force charge" state."""

    LIMIT_DISCHARGE = "limit_discharge"
    """Reactive protection during night EV charging — hold
    discharge to a specific watts value (typically home consumption,
    1:1 limit). Formerly the ``BatteryProtectionMixin`` logic (#624)."""

    FORCE_CHARGE = "force_charge"
    """Proactive grid-to-battery charge with target SOC and power.
    Today's ``BatteryChargeScheduler`` SCHEDULED state."""

    STOP_FORCE_CHARGE = "stop_force_charge"
    """End a forced charge — target reached, window ended, or
    scheduler decided NOT_NEEDED. Different from ``NORMAL`` because
    the adapter may need a brand-specific stop service
    (``huawei_solar.stop_forcible_charge``) instead of just
    setting back to default."""

    FORCE_DISCHARGE = "force_discharge"
    """#523 Tier 3 — proactive battery → GRID discharge (arbitrage).
    Sell stored energy when the dynamic export price is high and the
    sale beats the cost of recharging later. Hardware-gated: only
    adapters with ``supports_forced_discharge`` actuate it."""

    STOP_FORCE_DISCHARGE = "stop_force_discharge"
    """End a forced discharge — export no longer profitable or SOC
    hit the reserve floor. Restores the brand default."""

    OFF = "off"
    """#523 (RienduPre) — SEM is fully hands-off this battery. On the
    transition INTO off the adapter does a one-time clean handoff (clear
    any SEM force command, release the strategy, un-limit the discharge)
    so the battery isn't stranded in a SEM-imposed state, then stays
    completely silent — no protection, no scheduler, no arbitrage. The
    inverter runs the battery on its own. Bypasses every other branch in
    ``decide_battery`` (highest precedence)."""


@dataclass(frozen=True)
class BatteryDecision:
    """The output of ``decide_battery(view)`` for ONE battery this
    cycle. Immutable; consumed by ``actuate_battery``.
    """

    battery_id: str
    intent: BatteryIntent
    discharge_limit_w: float = 0.0
    """Used iff intent == LIMIT_DISCHARGE."""
    target_soc: float = 0.0
    """Used iff intent == FORCE_CHARGE."""
    charge_power_w: float = 0.0
    duration_min: int = 0
    discharge_power_w: float = 0.0
    """Used iff intent == FORCE_DISCHARGE (#523) — battery→grid power."""
    floor_soc: float = 0.0
    """Used iff intent == FORCE_DISCHARGE (#523) — stop discharging at
    this reserve SOC."""
    reason: str = ""


@dataclass(frozen=True)
class BatteryView:
    """All inputs needed to decide for ONE battery this cycle.

    Built once per battery at the top of the coordinator's per-
    battery loop. Pure ``decide_battery(view)`` reads only from
    this view — no coordinator state.
    """

    runtime: "BatteryRuntime"
    config: "Mapping[str, Any]"
    fleet: "FleetContext"
    charging_state: str
    """Current SEM ChargingState (string form). Drives the
    LIMIT_DISCHARGE gate (active iff NIGHT_CHARGING_ACTIVE)."""
    ev_charging: bool
    """Whether any charger in the fleet is currently *drawing* power.
    This flag flaps with bursty cars (e.g. a Renault Zoe that pulses
    on/off), so it is NOT used alone to gate the discharge protection
    — see ``ev_connected``."""
    home_consumption_w: float
    """Used as the discharge limit when LIMIT_DISCHARGE fires
    (the 1:1 protection)."""
    ev_connected: bool = False
    """Whether any charger in the fleet has a vehicle plugged in
    (cable connected), regardless of whether it is drawing right now.
    The discharge-protection gate keys off this so the clamp HOLDS
    steady through a bursty car's on/off pulses instead of flickering
    with ``ev_charging`` — which would let the battery drain between
    bursts and then feed the next pull. See decide_battery."""
    scheduler_decision: "Any" = None
    """The output of today's ``BatteryChargeScheduler.evaluate()``.
    Typed as ``Any`` so importing scheduler types in this module
    isn't load-bearing — the actual type is
    :class:`SchedulerDecision` from ``battery_charge_scheduler.py``."""
    grid_funded_load_w: float = 0.0
    """(#620) Total draw of loads currently running on the cheap-hours
    GRID top-up ("Finish overnight from: Grid"). The battery must not
    fund these — decide_battery subtracts this from the home-load
    discharge limit so the grid actually feeds them. Without it the
    inverter's self-consumption logic covers the load from the battery
    and the Battery/Grid picker choices behave identically
    (observed live, PROD 2026-07-22)."""
    plan_gate: "Any" = None
    """(#638 one-gate C4) The joint plan's trust-rule verdict for the
    ``battery`` demand this cycle (a ``PlanGate``, typed ``Any`` for the
    same import-lightness reason as ``scheduler_decision``). The
    scheduler says WHAT (deficit, target, power, economics); this says
    WHEN. ``None``/uncovered ⇒ no force-charge — pre-charge is
    optimization, not guarantee."""
    arbitrage_sell: "Any" = None
    """(#638 one-gate C6) The plan's WHEN for the arbitrage sell —
    ``(in_block, per_battery_power_w)`` from ``arbitrage_sell_gate``,
    already fleet-split by the pipeline. ``None``/closed ⇒ no sell this
    cycle regardless of the live economics verdict."""


# ─────────────────────────────────────────────────────────────────
# Per-charger calendar-reset energy
# ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ChargerEnergy:
    """One charger's calendar-reset energy counters.

    Single epoch — calendar midnight. The legacy sunrise-reset
    counter that bit autarky in #279 / #345 becomes a derived
    ``@property`` in Step 7 (``daily_kwh_since_sunrise =
    day_kwh - kwh_at_sunrise``), not a parallel accumulator on
    a different clock.
    """

    charger_id: str
    day_kwh: float = 0.0
    """kWh delivered today (calendar-reset, midnight)."""

    session_kwh: float = 0.0
    """kWh delivered this session (since last plug-in). Reset
    by the actuator when the charger reports a new session
    via the brand's session_energy sensor."""


# ─────────────────────────────────────────────────────────────────
# Per-charger decision (the output of decide())
# ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ChargerDecision:
    """The output of ``decide(view)`` — what one charger should do
    this cycle.

    Replaces the chain
    ``charging_strategy: str → ChargingState: str → _cycle_ev_budget:
    EVBudget → commanded_current: float`` that pre-architecture
    spread across ``_determine_charging_strategy`` +
    ``ChargingStateMachine.update_state`` + ``_execute_ev_control``.

    All fields are computed once in ``decide`` and consumed by
    ``actuate``. No re-derivation downstream. The post-cycle
    snapshot stored on the coordinator is the same ChargerDecision
    so dashboard sensors and notifications read a single
    consistent truth.
    """

    charger_id: str

    mode: str
    """The resolved per-charger charge mode (one of
    ``EV_CHARGE_MODES``). Resolved here so downstream consumers
    don't re-read ``effective_charge_mode_for``."""

    intent: ChargerIntent
    """What the actuator must do this cycle."""

    commanded_amps: int = 0
    """Used iff ``intent == CHARGE_AT_AMPS``. Always 0 for IDLE/
    DISABLE; ignored for CHARGE_MAX (the adapter resolves)."""

    budget_w: float = 0.0
    """Watts allocated to this charger this cycle. Carried on the
    decision so the dashboard sensor reads it without re-running
    the budget calculation."""

    reason: str = ""
    """Human-readable explanation — appears in the
    ``charging_strategy_reason`` sensor and in DEBUG logs.
    Examples: 'solar mode, surplus 4200W, ramp to 5A',
    'off mode — explicit user disable', 'night mode + min_plus_solar
    floor, deadline 06:00'."""

    bridgeable: bool = True
    """For an IDLE decision: is this a TRANSIENT dip worth holding the
    contactor through (a passing cloud while real surplus / battery
    assist exists) — or a STRUCTURAL stop (sun gone, battery below
    buffer with no real surplus, or a not-cheap tariff window) that the
    stability layer must NOT bridge by importing grid?

    Single source of truth (computed in ``decide`` where the SoC /
    surplus / tariff data already lives) so ``charge_stability`` does NOT
    re-derive it. ``True`` for CHARGE decisions and transient idles (the
    bridge holds for the full disable delay); ``False`` for structural
    idles (the bridge stops on the short grace). Honours the dataclass
    contract: 'All fields are computed once in decide … no re-derivation
    downstream.'"""


def solar_commitment_w(
    decision: ChargerDecision,
    *,
    phases: int,
    voltage: float,
    max_current_a: float,
) -> float:
    """Solar this charger claims out of the cycle's shared surplus (#665).

    The coordinator's per-charger loop accumulates this into
    ``_solar_committed_w_per_cycle`` and threads the running total into
    the next (lower-priority) charger's ``ChargerView.fleet.solar_committed_w``,
    so the cascade hands each charger only the surplus its seniors left.

    This lives here, named and importable, for one reason: it is the
    arithmetic the scenario harness must run to have honest multi-charger
    coverage. Before #665 it was inline in ``_async_update_data``, so the
    harness could only re-implement it test-side — and a re-implementation
    that drifts asserts nothing. One function, one caller in production,
    one caller in the harness: the two cannot disagree.

    Only the two CHARGE intents commit. IDLE and DISABLE claim nothing —
    an off-mode or idling charger must not shrink the surplus its
    lower-priority siblings can see (the invariant
    ``test_351_umbrella_regression.py::TestM5`` pins from the other side).

    Args:
        decision: This charger's ``decide()`` output.
        phases: The charger's phase count.
        voltage: The charger's per-phase voltage.
        max_current_a: The charger's ceiling, used for ``CHARGE_MAX``
            where ``commanded_amps`` is not meaningful (the adapter
            resolves the actual current).

    Returns:
        Watts of solar this charger claims — 0.0 for non-charging intents.
    """
    if decision.intent is ChargerIntent.CHARGE_AT_AMPS:
        # Never credit more than the budget the decision was granted:
        # commanded_amps can be raised by a floor (deadline / Min) that
        # grid or battery funds, and grid-funded watts are not solar.
        return max(0.0, min(
            float(decision.budget_w),
            float(decision.commanded_amps) * float(phases) * float(voltage),
        ))
    if decision.intent is ChargerIntent.CHARGE_MAX:
        return max(0.0, float(max_current_a) * float(phases) * float(voltage))
    return 0.0


def commanded_power_w(
    decision: ChargerDecision,
    *,
    phases: int,
    voltage: float,
    max_current_a: float,
) -> float:
    """Watts this decision commands — the whole commitment, whoever funds it.

    :func:`solar_commitment_w` answers "how much of the shared SOLAR surplus
    does this charger claim", so it caps at ``budget_w``. This answers the
    other question: how much power will flow if the actuator applies the
    decision — grid-funded deadline amps and battery-funded floors included.

    Two callers, one number: the night peak budget's per-charger commitment
    (which normally reads the setpoint the actuator wrote — and under
    observer mode nothing writes one), and the WOULD payload that observer
    mode publishes. A charger that would pull 6.9 kW must say 6.9 kW in
    both, or a two-charger simulation hands the junior charger phantom
    headroom.
    """
    if decision.intent is ChargerIntent.CHARGE_AT_AMPS:
        return max(
            0.0,
            float(decision.commanded_amps) * float(phases) * float(voltage),
        )
    if decision.intent is ChargerIntent.CHARGE_MAX:
        return max(0.0, float(max_current_a) * float(phases) * float(voltage))
    return 0.0


# ─────────────────────────────────────────────────────────────────
# Per-charger view (the input to decide())
# ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ArbitrageSignals:
    """Battery→grid arbitrage market signals (#533), computed ONCE per cycle
    and carried on :class:`FleetContext` — the single source of truth, so the
    arbitrage decision no longer depends on ad-hoc tariff/power reads scattered
    in the coordinator. ``None`` on FleetContext = arbitrage not evaluated this
    cycle (the default; it stays dormant until v1.7.4)."""

    export_rate: float = 0.0
    """Signed current export price (/kWh) — provider.get_current_export_rate()."""

    import_forecast_min: Optional[float] = None
    """Cheapest upcoming import price (/kWh), corrected to the all-in floor
    (provider.effective_import_floor). None = no forecast → don't sell."""

    storable_surplus_w: float = 0.0
    """Solar above home load (W) the battery could still absorb."""

    storable: bool = False
    """True when there's meaningful storable surplus and the battery isn't
    full → charge-first, don't sell (#531)."""


@dataclass(frozen=True)
class FleetContext:
    """Shared fleet-level inputs a single charger's decide() needs.

    Solar surplus, battery SOC, time-of-day, peak budget — all
    things the charger does NOT own but that influence its decision.
    Computed once per cycle from the unchanged ``PowerReadings`` /
    ``EnergyTotals`` and passed verbatim to every charger's
    ``ChargerView`` so two chargers always see the same fleet state.
    """

    solar_w: float = 0.0
    """Solar production this cycle (W)."""

    curtailment_grant_w: float = 0.0
    """#743 — bootstrap watts the curtailment probe grants when an
    export-limited inverter hides real solar behind clamped
    production. Added to the surplus exactly like measured solar;
    0.0 whenever the probe is off/idle."""

    home_w: float = 0.0
    """Home consumption (W). Pre-priority-attribution this was
    the slack variable; post-#349 it's a first-class demand."""

    battery_charge_w: float = 0.0
    """How much the home battery is taking from solar/grid this
    cycle. Used by ``decide`` to know whether battery is
    competing for surplus."""

    battery_discharge_w: float = 0.0
    """How much the home battery is providing this cycle."""

    battery_soc: float = 0.0
    """0-100. Below ``priority_soc`` blocks Zone 1 / Zone 2
    surplus-only chargers; above ``auto_start_soc`` enables
    battery-assist."""

    battery_count: int = 1
    """How many batteries SEM controls. #531: a per-battery
    LIMIT_DISCHARGE must split the home-consumption budget across the
    fleet — otherwise each of N batteries is told to inject the FULL
    home load (N× over-injection, defeating EV-night protection)."""

    grid_import_w: float = 0.0
    grid_export_w: float = 0.0

    is_night: bool = False
    """``time_manager.is_night_mode()``."""

    peak_budget_w: float = 5000.0
    """Total peak-import budget for the fleet (target_peak_limit).
    The multi-charger loop subtracts higher-priority chargers'
    commits before each charger's decide() runs."""

    peak_committed_w: float = 0.0
    """Watts already committed to higher-priority chargers in
    this cycle (the #274/H1 share-one-peak-budget invariant)."""

    arbitrage: Optional["ArbitrageSignals"] = None
    """Battery→grid arbitrage market signals (#533), computed once per cycle.
    None = arbitrage not evaluated (default; dormant until v1.7.4)."""

    solar_committed_w: float = 0.0
    """Solar surplus already committed to higher-priority chargers
    in this cycle. Step 6 multi-charger correctness: when the
    per-charger loop walks chargers in priority order, each call
    to ``decide(view)`` sees a fleet context where
    ``solar_committed_w`` reflects what previous chargers in the
    cycle already grabbed. Prevents two solar_only chargers from
    each thinking they can have ALL the surplus."""

    # ─── SOC zones (Step 3) ────────────────────────────────────
    # The four-zone model from ``_zone_based_strategy``. Thresholds
    # are fleet config (one home battery), so they live here, not
    # on the per-charger view.

    auto_start_soc: float = 90.0
    buffer_soc: float = 70.0
    priority_soc: float = 30.0
    battery_capacity_kwh: float = 15.0

    battery_assist_max_power_w: float = 4500.0
    """User-configured discharge cap when the battery assists the EV
    (``battery_assist_max_power``). #501: the Zone 3/4 day budget in
    ``decide.battery_assist_budget_w`` is capped by this — pre-#501 it
    added the battery's TOTAL measured discharge (including the share
    serving the house), which both ignored this cap and created a
    positive-feedback ratchet (home-load spike → more discharge →
    bigger EV budget → higher commanded amps → more discharge)."""

    battery_assist_min_surplus_w: float = 1200.0
    """Solar-surplus gate for battery assist (``battery_assist_min_surplus``).
    Battery assist only SUPPLEMENTS real solar — below this much pure
    solar surplus the battery is off-limits to the EV, so a sunless
    evening/overnight ``min_plus_solar`` session never drains the home
    battery into the car. Enforced in ``decide.battery_assist_budget_w``
    and ``FlowCalculator.calculate_canonical_ev_budget`` (the two layers
    must agree — the #282 class)."""

    min_solar_w: float = 1000.0
    """Raw PV below this is treated as "no meaningful solar / sun not
    up" — the floor that gates solar_only entry and the deep-deficit
    darkness detector. Default matches DEFAULT_MIN_SOLAR_POWER (1000 W)
    so the dataclass default agrees with the seeded config default.
    Distinct from ``battery_assist_min_surplus_w`` (an export-surplus
    floor, solar − home); this one is raw production."""

    peak_state: str = "normal"
    """(#747) The load manager's peak posture this cycle (normal /
    warning / shedding / emergency). decide() applies a SENIOR clamp on
    shed levels — the EV throttles before anyone's freezer sheds. The
    actuation exclusion in load_management stays (#649: one writer per
    device); this is the other half of its premise, finally real."""

    forecast_remaining_kwh: float = 0.0
    """Solar forecast remaining today (kWh), dampened by the
    ``ForecastTracker``. The ``solar_only`` regime uses this to
    decide whether the battery can be charged later from solar — if
    so, divert some of the current ``battery_charge_w`` to the EV
    via the canonical redirect (see ``flow_calculator.battery_redirect_w``).

    Pre-arch (v1.6.x) the legacy ``_determine_charging_strategy``
    let the SOLAR_ONLY canonical budget compute the redirect, so
    ``decide()`` didn't need this field. Post-#358 the redirect
    has to live in the strategy decision too — otherwise a viable
    SOLAR_ONLY cycle collapses to IDLE because the bare surplus
    falls under the charger min."""

    # ─── Tariff (Step 3) ───────────────────────────────────────
    tariff_level: "Optional[str]" = None
    """``None`` when no dynamic tariff configured; otherwise one
    of ``"very_cheap"`` / ``"cheap"`` / ``"normal"`` / ``"expensive"`` /
    ``"very_expensive"`` (matches :class:`PriceLevel`). The
    ``solar_plus_cheap`` mode falls back to pure self-consumption
    during ``expensive`` / ``very_expensive`` windows."""

    # ─── #576 priority list ────────────────────────────────────
    battery_priority: "Optional[int]" = None
    """The home battery's slot in the ONE device-priority list
    (``registry.battery_surplus_priority()``). ``None`` when the install
    has no battery. An EV reclaims battery-charge power (charges before the
    battery) only when it sits ABOVE this slot — see
    ``energy_reclaim.ev_reclaims_battery_charge``."""

    battery_commanded: bool = False
    """The battery is under an explicit charge/discharge command this cycle
    (force_charge / scheduled / arbitrage). While commanded the EV never
    reclaims — the battery command is honored (#576 U6)."""


@dataclass(frozen=True)
class FleetCycleState:
    """The cycle's fleet inputs — built ONCE per cycle, consumed by
    every ``build_charger_view`` call in that same cycle.

    Single source of truth for fleet-level state. Both the primary
    view (constructed inside ``coordinator._build_charging_context``)
    and the multi-charger loop's per-charger views derive their
    ``FleetContext`` from THE SAME ``FleetCycleState`` object —
    eliminating the post-#358 plumbing-asymmetry class where some
    callers passed ``tariff_level`` / ``forecast_remaining_kwh`` /
    night-plan signals and others didn't.

    The shape contains every FLEET-level input that any charger's
    ``decide()`` could need:

      * ``power`` — raw sensor readings (solar, home, battery,
        grid, EV) with derived fields populated
      * ``config`` — global config dict (SOC thresholds, capacity,
        peak limit, etc.)
      * ``is_night`` — ``time_manager.is_night_mode()``
      * ``tariff_level`` — resolved from ``_tariff_provider``
      * ``forecast_remaining_kwh`` — dampened solar forecast

    PER-CHARGER overrides (``target_kwh``, ``deadline_amps``,
    ``tariff_wait``, ``solar_committed_w``) stay as direct kwargs to
    ``build_charger_view`` — they LEGITIMATELY vary across chargers
    in the same cycle.

    When a new fleet input is added: land it as a field here. The
    AST lint at ``tests/test_fleet_state_completeness.py`` fails CI
    if any ``build_charger_view`` call site bypasses this state and
    passes a fleet-level kwarg directly.

    See ``coordinator._build_fleet_cycle_state`` for the construction.
    """

    power: "PowerReadings"
    config: "Mapping[str, Any]"
    is_night: bool = False
    tariff_level: "Optional[str]" = None
    forecast_remaining_kwh: float = 0.0
    # (#747) the load manager's peak posture, resolved once per cycle.
    peak_state: str = "normal"
    # #576 — fleet-level priority-list inputs (one home battery). Threaded
    # here so every charger's view sees the same slot + command state.
    battery_priority: "Optional[int]" = None
    battery_commanded: bool = False
    # #743 — the curtailment probe's surplus grant (W). An export-limited
    # inverter clamps production to consumption, hiding real solar from
    # the measured surplus; the probe grants bootstrap watts that decide()
    # treats exactly like measured solar (see coordinator/curtailment.py).
    # 0.0 = probe off/idle — the entire feature disappears from the math.
    curtailment_grant_w: float = 0.0


@dataclass(frozen=True)
class ChargerView:
    """Everything one charger's decide() needs.

    Built once per charger at the top of the per-charger loop.
    Immutable for the rest of the cycle. ``decide(view)`` is a pure
    function over this input.
    """

    power: ChargerPower
    energy: ChargerEnergy
    mode: str
    """Resolved per-charger charge mode (one of EV_CHARGE_MODES).
    Pre-resolved so decide() doesn't re-call ``effective_charge_mode_for``."""

    config: Mapping[str, object]
    """The per-charger config dict (``ev_chargers[i]`` entry)."""

    fleet: FleetContext

    target_kwh: Optional[float] = None
    """Per-charger remaining-need to the Min/Max bound — computed
    upstream using ``_daily_ev_per_charger[cid]`` (NOT the fleet
    ``energy.daily_ev`` that bit #318). ``None`` when no kWh-based
    target applies (SOC-bound)."""

    target_soc: Optional[float] = None
    """Per-charger SOC target (#245). ``None`` when kWh-bound."""

    deadline_amps: int = 0
    top_up_amps: int = 0  # (#630) peak-managed plain night top-up rate
    """The peak-aware required current to reach Min by the per-
    charger ``ev_target_time`` (#246). ``0`` when no deadline."""

    night_deliverable_kwh: float = float("inf")
    """How much energy tonight's window (night start → this charger's
    deadline) can deliver at the charger's max current (#501). The
    daytime ``min_plus_solar`` floor only engages when
    ``target_kwh > night_deliverable_kwh`` — i.e. when waiting for the
    night top-up would genuinely risk the Min-by-deadline guarantee.
    Default ``inf`` (floor never engages) so call sites that don't
    compute it get the self-consumption-maximizing behaviour rather
    than silent grid pull."""

    ev_priority: int = 999
    """This charger's slot in the ONE device-priority list
    (``registry.priority_for(cid)`` == the drag position). Compared against
    ``fleet.battery_priority``: this charger reclaims battery-charge power
    (charges before the battery) only when ``ev_priority <
    fleet.battery_priority`` AND SOC ≥ reserve floor (#576 P2.2). Defaults to
    999 (bottom) so a view built without it never spuriously reclaims."""

    plan: PlanVerdict = field(default_factory=PlanVerdict)
    """(#638) What the PLANNING layer decided for this charger this cycle.

    A typed field rather than a key in ``config`` on purpose. Its
    predecessor travelled as ``config["_tariff_wait"]`` — invisible in
    this class, therefore invisible to a reader of ``decide()``, therefore
    consulted by exactly one of the three night-capable modes. On
    2026-08-06 the car charged an hour early and finished before its own
    planned window opened, because two modes could not see a signal that
    was not in the picture they were handed.

    Defaults to no opinion, which every consumer must treat as "no planner
    exists" — the fail-open contract. Day/night agnostic (see
    :mod:`.plan_verdict`): a daytime planner fills this same field."""

    soc_ceiling_reached: bool = False
    """The car has reached its configured MAX target (SOC % ceiling, or
    the max-kWh ceiling) — stop charging in EVERY mode, including solar
    surplus (#548). Computed upstream as ``_calculate_remaining_need(
    bound="max") <= 0.1``. This is the surplus-charging stop that used to
    live only in the retired ChargingStateMachine (``soc_limit_active →
    SOLAR_TARGET_REACHED``); that state was clobbered by the per-charger
    decision, so the EV charged past the max SOC. ``decide()`` now reads
    this directly. Default ``False`` (kWh-mode default max is effectively
    unlimited, so surplus charging stays 'free' for kWh users)."""


# ─────────────────────────────────────────────────────────────────
# Fleet view (computed from per-charger dict)
# ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FleetView:
    """Aggregate view over all chargers. Computed; never primary.

    Constructed via ``FleetView.from_per_charger(power_dict,
    energy_dict)``. Replaces the v1.6.16 ``FleetEvPower`` newtype's
    role as the fleet sum — that newtype was a stopgap for
    fleet-vs-per-charger reads inside the actuator. Post-migration
    the actuator does not read fleet at all; this type exists for
    legitimate fleet consumers (dashboard fleet sensors, balance
    equations, peak budgeting).
    """

    total_power_w: float = 0.0
    total_day_kwh: float = 0.0
    any_connected: bool = False
    any_charging: bool = False
    count: int = 0
    per_charger: Mapping[str, ChargerPower] = field(default_factory=dict)

    @classmethod
    def from_per_charger(
        cls,
        power: Mapping[str, ChargerPower],
        energy: Mapping[str, ChargerEnergy],
    ) -> "FleetView":
        """Build the fleet view from per-charger dicts. The only
        sanctioned way to obtain a fleet number — no separate fleet
        sensor read, no parallel accumulator."""
        return cls(
            total_power_w=sum(c.power_w for c in power.values()),
            total_day_kwh=sum(
                energy.get(cid, ChargerEnergy(cid)).day_kwh
                for cid in power
            ),
            any_connected=any(c.connected for c in power.values()),
            any_charging=any(c.charging for c in power.values()),
            count=len(power),
            per_charger=dict(power),
        )
