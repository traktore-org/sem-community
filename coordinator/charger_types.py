"""Per-charger primary types (arch/multi-charger-primary, v1.7.0).

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
from typing import Dict, Mapping, Optional


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


# ─────────────────────────────────────────────────────────────────
# Per-charger view (the input to decide())
# ─────────────────────────────────────────────────────────────────

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

    # ─── SOC zones (Step 3) ────────────────────────────────────
    # The four-zone model from ``_zone_based_strategy``. Thresholds
    # are fleet config (one home battery), so they live here, not
    # on the per-charger view.

    auto_start_soc: float = 90.0
    buffer_soc: float = 70.0
    priority_soc: float = 30.0
    battery_floor_soc: float = 60.0
    battery_capacity_kwh: float = 15.0

    min_solar_w: float = 200.0
    """Solar below this is treated as "no meaningful solar" — the
    threshold for skipping the surplus calculation entirely.
    Same constant as ``_zone_based_strategy`` uses at
    ``coordinator.py:2709``."""

    # ─── Tariff (Step 3) ───────────────────────────────────────
    tariff_level: "Optional[str]" = None
    """``None`` when no dynamic tariff configured; otherwise one
    of ``"very_cheap"`` / ``"cheap"`` / ``"normal"`` / ``"expensive"`` /
    ``"very_expensive"`` (matches :class:`PriceLevel`). The
    ``solar_plus_cheap`` mode falls back to pure self-consumption
    during ``expensive`` / ``very_expensive`` windows."""


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
    """The peak-aware required current to reach Min by the per-
    charger ``ev_target_time`` (#246). ``0`` when no deadline."""


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
