"""Type definitions for SEM coordinator modules.

Key dataclasses:
- PowerReadings: Instantaneous sensor values with derived splits
- PowerFlows / EnergyFlows: Source-to-destination flow distribution
- EnergyTotals: Daily/monthly energy accumulators
- CostData: Import costs, savings, export revenue
- SessionData: Per-EV-session cost attribution and energy source tracking
- SEMData: Complete coordinator output (flat dict via to_dict())
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Dict, Any, List, Optional
from enum import Enum

if TYPE_CHECKING:  # pragma: no cover — type-only
    from .charger_types import (
        BatteryPower, BatteryRuntime, InverterPower, InverterRuntime,
    )

_LOGGER = logging.getLogger(__name__)


class EnergySource(Enum):
    """Energy data source."""
    HARDWARE = "hardware"
    CALCULATED = "calculated"
    MIXED = "mixed"


class FleetEvPower(float):
    """Newtype for the fleet-aggregated EV power sum (v1.6.16).

    Background. In multi-charger setups (``len(ev_chargers) > 1``)
    ``PowerReadings.ev_power`` is the SUM across every charger's draw,
    populated by ``sensor_reader`` from per-charger power sensors. Code
    paths that loop per-charger and read the fleet sum directly produce
    the recurring bug class that filled the v1.6.4 → v1.6.6 hotfix
    sequence (#284, #289, #315, #318).

    Goal. Make "I deliberately want the fleet sum" structurally
    explicit — every read carries a written reason at the call site.

    Mechanism. ``FleetEvPower`` subclasses ``float`` so arithmetic and
    comparisons still work (no migration cost for the ~15 legitimate
    fleet reads across ``coordinator/``). Layered on top:

    1. The ``.as_fleet_total(reason: str)`` accessor returns the
       underlying watts and documents intent in the code (not a
       comment). The ``reason`` arg has no runtime effect but appears
       in code review and ``git blame`` — the structural improvement
       over the v1.6.8 ``# FLEET-READ:`` comment.

    2. The expanded AST lint
       (``tests/test_fleet_ev_power_reads_global.py``) treats
       ``power.ev_power.as_fleet_total(...)`` as equivalent to the
       comment annotation. Reads that are neither acknowledged form
       fail CI across every ``coordinator/`` module — not just
       ``ev_control.py`` like the v1.6.8 lint.

    Mostly the v1.6.8 ``# FLEET-READ:`` comment idiom continues to
    work — there is no flag-day. New code is encouraged to use the
    method form because it appears in the bytecode (mypy, IDE hover,
    even ``ast.dump``).
    """

    __slots__ = ()

    def as_fleet_total(self, reason: str) -> float:
        """Return the underlying watts; ``reason`` documents intent.

        Args:
            reason: short string explaining WHY this call site wants
                the fleet sum rather than a per-charger draw. Required
                positional argument — by convention the lint at
                ``tests/test_fleet_ev_power_reads_global.py`` accepts
                any non-empty string. Keep it concrete: "energy
                balance computation" beats "fleet read".

        Returns:
            The wrapped watts as a plain ``float``. Identical to
            ``float(self)``; the layer exists for documentation, not
            for unit conversion.
        """
        return float(self)

    def __repr__(self) -> str:  # noqa: D401
        return f"FleetEvPower({float(self):.1f})"


@dataclass
class PowerReadings:
    """Current power readings from sensors.

    v1.7.0 arch/multi-device-primary: the per-device dicts
    (``inverters``, ``batteries``, ``ev_power_per_charger``,
    ``solar_power_per_string``) are the PRIMARY representation.
    The legacy fleet float fields (``solar_power``, ``battery_power``,
    ``ev_power``) are kept as cached sums for backward compat with
    downstream consumers; ``sensor_reader`` populates both. The
    ``fleet_solar_w`` / ``fleet_battery_w`` / ``fleet_ev_w``
    properties are the sanctioned way to read the fleet sum going
    forward — they recompute from the dict and so cannot drift.

    Pin: ``solar_power == fleet_solar_w`` and
    ``battery_power == fleet_battery_w`` whenever the dicts are
    populated. Enforced by the Step 8 invariant test suite.
    """
    solar_power: float = 0.0
    grid_power: float = 0.0  # Negative = import, Positive = export
    battery_power: float = 0.0  # Positive = charge, Negative = discharge
    # v1.6.16: typed as ``FleetEvPower`` — a ``float`` subclass marking
    # the fleet-aggregated EV power sum. Reads that want the sum
    # acknowledge it via ``.as_fleet_total(reason)`` (preferred) or
    # ``# FLEET-READ:`` comment (legacy v1.6.8 idiom). The AST lint at
    # ``tests/test_fleet_ev_power_reads_global.py`` covers every
    # ``coordinator/`` module — not just ``ev_control.py``. See
    # ``docs/MULTI_CHARGER.md`` for the full invariant.
    ev_power: "FleetEvPower" = field(default_factory=lambda: FleetEvPower(0.0))
    home_consumption_power: float = 0.0

    # Per-charger EV power (v1.6.9). Populated by ``sensor_reader`` for
    # multi-charger setups (``len(ev_chargers) > 1``); each key is a
    # charger id and the value is that charger's draw in watts. Sum of
    # values equals ``ev_power``. Empty dict in single-charger setups —
    # downstream code must fall back to ``ev_power`` when the dict is
    # empty (see ``flow_calculator.calculate_power_flows``). Drives the
    # per-charger flow attribution that closes the #316 family.
    ev_power_per_charger: "Dict[str, float]" = field(default_factory=dict)

    # Per-PV-string solar power (v1.7.0 / #312). Populated by
    # ``sensor_reader`` when the entity registry auto-discovery (see
    # ``hardware_detection.discover_pv_strings_from_registry``) found
    # ≥ 2 string sensors. Each key is a stable slot label (``"pv1"``,
    # ``"pv2"``, …) and the value is that string's instantaneous power
    # in watts. The structural mirror of ``ev_power_per_charger`` —
    # strings are SOURCES so the sum invariant is
    # ``sum(solar_power_per_string.values()) ≈ solar_power`` (within
    # rounding); chargers are DESTINATIONS so the per-charger sum
    # equals ``ev_power``. Empty dict in single-string / single-
    # inverter setups; downstream readers must fall back to
    # ``solar_power``.
    solar_power_per_string: "Dict[str, float]" = field(default_factory=dict)

    # v1.7.0 arch/multi-inverter-battery-primary.
    #
    # Per-inverter and per-battery dicts are now the PRIMARY
    # representation of multi-device fleets. ``sensor_reader``
    # populates them whenever the config lists more than one
    # source (``solar_power_list`` length > 1 or
    # ``battery_power_list`` length > 1). The fleet ``solar_power``
    # and ``battery_power`` fields above stay as cached sums for
    # backward compat — every downstream consumer that adds up
    # ``solar_power`` continues to work — but new code should
    # read the dicts via ``fleet_solar_w`` / ``fleet_battery_w``
    # (the ``@property`` accessors below) so a future refactor
    # can swap the cached sums to computed-on-read without a
    # consumer churn.
    #
    # Sum invariants pinned by ``tests/test_step8_invariants.py``:
    #   ``solar_power == fleet_solar_w`` (cached == computed)
    #   ``battery_power == fleet_battery_w``
    # The invariant doesn't fire on single-device setups (dict
    # empty) — they keep the fleet field semantics unchanged.
    inverters: "Dict[str, InverterPower]" = field(default_factory=dict)
    batteries: "Dict[str, BatteryPower]" = field(default_factory=dict)

    # Derived values
    grid_import_power: float = 0.0
    grid_export_power: float = 0.0
    battery_charge_power: float = 0.0
    battery_discharge_power: float = 0.0

    # Battery state
    battery_soc: float = 0.0
    battery_soc_unavailable: bool = False  # True when SOC sensor is offline
    battery_temperature: float = 25.0

    # Battery health (calculated from energy data)
    battery_cycles_estimated: float = 0.0
    battery_health_score: float = 100.0

    # EV state
    ev_connected: bool = False
    ev_charging: bool = False

    # Timestamps
    timestamp: Optional[datetime] = None

    def calculate_derived(self) -> None:
        """Calculate derived power values from raw readings."""
        # Grid: negative = import, positive = export
        self.grid_import_power = max(0, -self.grid_power)
        self.grid_export_power = max(0, self.grid_power)

        # Battery: positive = charge, negative = discharge
        self.battery_charge_power = max(0, self.battery_power)
        self.battery_discharge_power = max(0, -self.battery_power)

        # Home consumption from energy balance
        energy_in = self.solar_power + self.grid_import_power + self.battery_discharge_power
        energy_out = self.ev_power + self.grid_export_power + self.battery_charge_power
        self.home_consumption_power = max(0, energy_in - energy_out)

    # ─── arch/multi-inverter-battery-primary @property views ───
    #
    # ``fleet_*_w`` accessors compute from the per-device dict —
    # the sanctioned way to obtain a fleet sum going forward.
    # New code reads these; legacy ``solar_power``/``battery_power``
    # consumers continue to work via the cached field.

    @property
    def fleet_solar_w(self) -> float:
        """Fleet-aggregated solar AC power (W). Computed from the
        per-inverter dict. Empty dict (single-inverter or pre-v1.7.0
        snapshot) falls back to the cached ``solar_power``."""
        if not self.inverters:
            return self.solar_power
        return sum(i.power_w for i in self.inverters.values())

    @property
    def fleet_battery_w(self) -> float:
        """Fleet-aggregated battery power (W; + = charge,
        − = discharge). Computed from the per-battery dict."""
        if not self.batteries:
            return self.battery_power
        return sum(b.power_w for b in self.batteries.values())

    @property
    def fleet_battery_soc(self) -> float:
        """Capacity-weighted fleet SOC (0-100). Falls back to the
        single ``battery_soc`` field when the per-battery dict is
        empty or no unit reports its capacity."""
        if not self.batteries:
            return self.battery_soc
        total_capacity = sum(b.capacity_kwh for b in self.batteries.values())
        if total_capacity <= 0:
            # No capacity → simple arithmetic mean (better than 0)
            socs = [b.soc_pct for b in self.batteries.values()]
            return sum(socs) / len(socs) if socs else self.battery_soc
        weighted_sum = sum(
            b.soc_pct * b.capacity_kwh for b in self.batteries.values()
        )
        return weighted_sum / total_capacity


@dataclass
class ChargerFlows:
    """Per-charger slice of the EV power flow attribution (v1.6.9).

    Mirrors the EV-relevant subset of :class:`PowerFlows` for ONE
    charger. The fleet-level ``PowerFlows.solar_to_ev`` (etc.) is the
    sum over all chargers' values here — invariant pinned in the
    scenario tests.

    Closes the #316 / #284 family of multi-charger complaints
    ("charger 2 looks like it's drawing from grid even in solar_only
    mode") by exposing per-charger sourcing the dashboard can render
    instead of attributing the fleet proportional split equally.
    """
    solar_to_ev: float = 0.0
    grid_to_ev: float = 0.0
    battery_to_ev: float = 0.0


@dataclass
class PowerFlows:
    """Power flow distribution between sources and destinations."""
    # Solar flows (W)
    solar_to_home: float = 0.0
    solar_to_battery: float = 0.0
    solar_to_ev: float = 0.0
    solar_to_grid: float = 0.0

    # Grid flows (W)
    grid_to_home: float = 0.0
    grid_to_ev: float = 0.0
    grid_to_battery: float = 0.0

    # Battery flows (W)
    battery_to_home: float = 0.0
    battery_to_ev: float = 0.0

    # Per-charger EV flow split (v1.6.9). Populated by
    # ``flow_calculator.calculate_power_flows`` when ``PowerReadings``
    # provides ``ev_power_per_charger``. Sum invariant:
    # ``sum(c.solar_to_ev for c in per_charger.values()) == solar_to_ev``
    # (similarly for grid_to_ev and battery_to_ev). Empty dict in
    # single-charger setups — backward-compat for downstream readers
    # that only know about the fleet-level fields.
    per_charger: "Dict[str, ChargerFlows]" = field(default_factory=dict)

    # Per-PV-string raw power carrier (v1.7.0 / #312). NOT a flow —
    # strings don't have destination attribution; this just carries
    # the per-string power from ``PowerReadings`` to
    # ``integrate_energy_flows`` without expanding the integrator's
    # signature. Populated by ``calculate_power_flows`` when the
    # readings include ``solar_power_per_string``. Sum invariant
    # holds at the read level (sum ≈ ``solar_power``); the integrator
    # owns the persistence of per-string kWh.
    solar_per_string: "Dict[str, float]" = field(default_factory=dict)


@dataclass
class EnergyTotals:
    """Daily/monthly energy totals.

    v1.7.0 arch follow-up: ``daily_solar`` / ``daily_battery_charge``
    / ``daily_battery_discharge`` are populated as plain fields by
    sensor_reader for single-device installs. Multi-device installs
    populate ``per_inverter`` / ``per_battery`` dicts and the
    legacy fields stay at 0 — the ``daily_solar_view`` /
    ``daily_battery_charge_view`` / ``daily_battery_discharge_view``
    @property accessors compute from the dicts and fall back to the
    legacy field when the dict is empty.

    The properties don't shadow the fields (Python dataclass
    semantics) — consumers must read ``.daily_solar_view`` etc.
    to get the per-device-aware value. ``to_dict()`` already emits
    the legacy fields; the view properties become the canonical
    sensor source once multi-device installs are common.
    """
    # Daily totals (kWh)
    daily_solar: float = 0.0
    daily_home: float = 0.0
    daily_ev: float = 0.0
    daily_grid_import: float = 0.0
    daily_grid_export: float = 0.0
    daily_battery_charge: float = 0.0
    daily_battery_discharge: float = 0.0

    # Monthly totals (kWh)
    monthly_solar: float = 0.0
    monthly_home: float = 0.0
    monthly_grid_import: float = 0.0
    monthly_grid_export: float = 0.0
    monthly_battery_charge: float = 0.0
    monthly_battery_discharge: float = 0.0

    # Yearly totals (kWh)
    yearly_solar: float = 0.0
    yearly_home: float = 0.0
    yearly_grid_import: float = 0.0
    yearly_grid_export: float = 0.0
    yearly_battery_charge: float = 0.0
    yearly_battery_discharge: float = 0.0
    yearly_ev: float = 0.0

    # v1.7.0 arch follow-up — per-device runtime dicts.
    # Populated by sensor_reader on multi-device installs. Empty on
    # single-device installs → the view properties fall back to the
    # legacy fields. See ``coordinator/charger_types.py`` for the
    # runtime dataclass shapes.
    per_inverter: "Dict[str, InverterRuntime]" = field(default_factory=dict)
    per_battery: "Dict[str, BatteryRuntime]" = field(default_factory=dict)

    @property
    def daily_solar_view(self) -> float:
        """Per-device-aware daily solar kWh. Falls back to
        ``daily_solar`` when no per-inverter data."""
        if not self.per_inverter:
            return self.daily_solar
        return sum(i.daily_kwh for i in self.per_inverter.values())

    @property
    def daily_battery_charge_view(self) -> float:
        if not self.per_battery:
            return self.daily_battery_charge
        return sum(b.daily_charge_kwh for b in self.per_battery.values())

    @property
    def daily_battery_discharge_view(self) -> float:
        if not self.per_battery:
            return self.daily_battery_discharge
        return sum(b.daily_discharge_kwh for b in self.per_battery.values())


@dataclass
class StringEnergy:
    """Per-PV-string daily energy total (v1.7.0 / #312).

    Mirror of :class:`ChargerEnergyFlows` for the source side. Each
    PV string accumulates its own daily kWh, integrated over time by
    ``FlowCalculator.integrate_energy_flows`` from
    ``PowerReadings.solar_power_per_string``. Sum invariant:
    ``sum(per_string.values()) ≈ energy_flows.solar_to_*`` total
    (the per-string aggregate equals the fleet solar contribution).

    Empty dict in single-string setups; the fleet
    ``EnergyTotals.daily_solar`` is authoritative there.
    """
    energy_kwh: float = 0.0


@dataclass
class ChargerEnergyFlows:
    """Per-charger slice of the daily EV energy flow attribution (v1.6.15).

    Mirrors :class:`ChargerFlows` (power, W) at the kWh level, integrated
    over time by ``FlowCalculator.integrate_energy_flows``. The fleet
    ``EnergyFlows.solar_to_ev`` (etc.) is the sum across all chargers'
    values here — invariant pinned in
    ``tests/test_per_charger_energy_flows.py``.

    Empty / not-populated in single-charger setups; the fleet-level
    ``EnergyFlows`` fields are authoritative there.
    """
    solar_to_ev: float = 0.0
    grid_to_ev: float = 0.0
    battery_to_ev: float = 0.0


@dataclass
class EnergyFlows:
    """Daily energy flow distribution (kWh)."""
    # Solar flows
    solar_to_home: float = 0.0
    solar_to_battery: float = 0.0
    solar_to_ev: float = 0.0
    solar_to_grid: float = 0.0

    # Grid flows
    grid_to_home: float = 0.0
    grid_to_ev: float = 0.0
    grid_to_battery: float = 0.0

    # Battery flows
    battery_to_home: float = 0.0
    battery_to_ev: float = 0.0

    # Per-charger EV energy split (v1.6.15). Populated by
    # ``FlowCalculator.integrate_energy_flows`` when
    # ``PowerFlows.per_charger`` is non-empty (multi-charger setups).
    # Empty dict in single-charger setups — readers fall back to the
    # fleet fields above. Invariant:
    # ``sum(c.solar_to_ev for c in per_charger.values()) == solar_to_ev``
    # within rounding tolerance.
    per_charger: "Dict[str, ChargerEnergyFlows]" = field(default_factory=dict)

    # Per-PV-string daily energy contribution (v1.7.0 / #312).
    # Integrated by ``FlowCalculator.integrate_energy_flows`` from
    # ``PowerReadings.solar_power_per_string`` over time. Empty dict
    # in single-string setups. Sum invariant within rounding:
    # ``sum(s.energy_kwh) ≈ aggregate solar integration this day``.
    per_string: "Dict[str, StringEnergy]" = field(default_factory=dict)


@dataclass
class CostData:
    """Cost and savings calculations.

    Savings split (#351 M2):

    * ``daily_savings`` — SOLAR self-consumption savings only
      (``solar_to_home`` + ``solar_to_ev``).
    * ``daily_battery_savings`` — battery-discharge savings (any
      destination: ``battery_to_home`` + ``battery_to_ev``).
    * ``daily_total_savings`` — sum of the two; the headline number
      users should compare against import costs. Pre-#351 M2 the
      dashboard surfaced ``daily_savings`` as the headline which
      understated savings by the ``battery_to_ev`` portion on
      battery-assist days.
    """
    daily_costs: float = 0.0
    daily_savings: float = 0.0
    daily_export_revenue: float = 0.0
    daily_net_cost: float = 0.0
    daily_battery_savings: float = 0.0
    daily_total_savings: float = 0.0   # #351 M2 — solar + battery savings

    monthly_costs: float = 0.0
    monthly_savings: float = 0.0
    monthly_battery_savings: float = 0.0
    monthly_total_savings: float = 0.0  # #351 M2
    monthly_export_revenue: float = 0.0
    monthly_net_cost: float = 0.0

    # Yearly costs
    yearly_costs: float = 0.0
    yearly_savings: float = 0.0
    yearly_battery_savings: float = 0.0
    yearly_total_savings: float = 0.0  # #351 M2
    yearly_export_revenue: float = 0.0
    yearly_net_cost: float = 0.0

    # Environmental impact
    daily_co2_avoided_kg: float = 0.0
    yearly_co2_avoided_kg: float = 0.0
    yearly_trees_equivalent: float = 0.0
    lifetime_co2_avoided_kg: float = 0.0
    lifetime_trees_equivalent: float = 0.0

    # ROI
    lifetime_total_savings: float = 0.0  # all-time savings (solar + export + battery)
    lifetime_grid_cost: float = 0.0  # all-time grid spend
    roi_percentage: float = 0.0  # savings / investment × 100
    roi_payback_years: float = 0.0  # estimated years to payback
    roi_annual_savings: float = 0.0  # projected annual savings rate


@dataclass
class PerformanceMetrics:
    """System performance metrics."""
    self_consumption_rate: float = 0.0  # % of solar used locally
    autarky_rate: float = 0.0  # % of consumption from own generation
    solar_efficiency: float = 0.0
    battery_efficiency: float = 0.0


@dataclass
class SystemStatus:
    """System status indicators."""
    grid_status: str = "idle"  # import, export, idle
    battery_status: str = "idle"  # charging, discharging, idle
    solar_active: bool = False
    ev_connected: bool = False
    ev_charging: bool = False
    battery_charging: bool = False
    battery_discharging: bool = False
    grid_export_active: bool = False


@dataclass
class LoadManagementData:
    """Load management and peak tracking data."""
    target_peak_limit: float = 5.0  # kW
    peak_margin: float = 0.5  # kW
    load_management_status: str = "idle"
    loads_currently_shed: str = "none"
    available_load_reduction: float = 0.0  # kW
    controllable_devices_count: int = 0
    consecutive_peak_15min: float = 0.0  # kW
    monthly_consecutive_peak: float = 0.0  # kW
    current_vs_peak_percentage: float = 0.0
    controlled_tariff_status: str = "unknown"
    load_management_recommendation: str = "none"
    power_charge_cost: float = 0.0
    peak_trend: str = "stable"
    tariff_type: str = "unknown"


@dataclass
class SurplusControlData:
    """Surplus controller state for coordinator data."""
    surplus_total_w: float = 0.0
    surplus_distributable_w: float = 0.0
    surplus_regulation_offset_w: float = 50.0
    surplus_allocated_w: float = 0.0
    surplus_unallocated_w: float = 0.0
    surplus_active_devices: int = 0
    surplus_total_devices: int = 0


@dataclass
class ForecastSensorData:
    """Forecast data for coordinator sensors."""
    forecast_today_kwh: float = 0.0
    forecast_tomorrow_kwh: float = 0.0
    forecast_remaining_today_kwh: float = 0.0
    forecast_power_now_w: float = 0.0
    forecast_power_next_hour_w: float = 0.0
    forecast_peak_power_today_w: float = 0.0
    forecast_peak_time_today: str = ""
    forecast_source: str = "none"
    forecast_available: bool = False
    charging_recommendation: str = "no_forecast"
    best_surplus_window: str = ""
    forecast_surplus_kwh: float = 0.0
    forecast_dampening_factor: float = 1.0


@dataclass
class TariffSensorData:
    """Tariff data for coordinator sensors."""
    tariff_current_import_rate: float = 0.0
    tariff_current_export_rate: float = 0.0
    tariff_price_level: str = "normal"
    tariff_provider: str = "static"
    tariff_is_dynamic: bool = False
    tariff_today_min_price: Optional[float] = None
    tariff_today_max_price: Optional[float] = None
    tariff_today_avg_price: Optional[float] = None
    tariff_next_cheap_start: Optional[str] = None
    # #359: diagnostic — which classifier branch produced ``tariff_price_level``.
    # Exposed as an attribute on ``sensor.sem_tariff_price_level`` so users in
    # cold-start / unit-mismatch / derivative-entity setups can self-diagnose
    # why they don't see ``cheap``/``expensive`` even with a dynamic tariff.
    tariff_classifier_path: str = "unknown"


@dataclass
class HeatPumpSensorData:
    """Heat pump data for coordinator sensors.

    The ``heat_pump_registered`` flag distinguishes "no controller
    registered" from "controller registered, currently in NORMAL
    state" — both produce ``heat_pump_sg_ready_state == 2`` so the
    presence flag is needed for the dashboard auto-hide logic on
    the heat pump section (#437).
    """
    heat_pump_registered: bool = False
    heat_pump_mode: str = "normal"
    heat_pump_sg_ready_state: int = 2
    heat_pump_solar_boost: bool = False
    # #432 / #446-followup: surface "why didn't the heat pump register?"
    # so users with non-standard SG-Ready wiring (ESP relays, Shellies,
    # Modbus-bridged template switches for Nibe S-Series) can debug
    # without owning the hardware on our side. One of six string states:
    #   registered_sg_ready, registered_climate_only,
    #   registered_sg_ready_and_climate, not_configured,
    #   partial_sg_ready_only_relay1, partial_sg_ready_only_relay2
    # plus the resolved entity ids + their live states for the diagnostic
    # attributes on ``sensor.sem_heat_pump_registration_status``.
    heat_pump_registration_status: str = "not_configured"
    heat_pump_relay1_entity: Optional[str] = None
    heat_pump_relay2_entity: Optional[str] = None
    heat_pump_climate_entity: Optional[str] = None
    heat_pump_relay1_state: Optional[str] = None
    heat_pump_relay2_state: Optional[str] = None
    heat_pump_climate_state: Optional[str] = None
    # v1.7.2-beta.2 (2026-06-07): wire the #421 audit's internal
    # ``_last_*_path`` recorders to a user-visible surface. The audit
    # shipped the recording in v1.7.0-beta.24 but never exposed the
    # values, so the diagnostic surface was useless for end-user
    # debugging. Each path is a short string naming the branch the
    # controller last took — see HeatPumpController for the
    # vocabulary (e.g. ``force_on``, ``boost``, ``boost+climate``,
    # ``normal``, ``blocked``, ``parent_declines``, ``already_warm_skip``).
    heat_pump_activation_path: Optional[str] = None
    heat_pump_deactivation_path: Optional[str] = None
    heat_pump_relay_path: Optional[str] = None
    heat_pump_temperature_reading_path: Optional[str] = None
    heat_pump_offpeak_path: Optional[str] = None
    heat_pump_current_temperature: Optional[float] = None


@dataclass
class HotWaterSensorData:
    """Hot water controller data for coordinator sensors (#454).

    Surfaced when the user has configured a ``hot_water_entity`` and SEM
    has instantiated + registered ``HotWaterController`` with the
    SurplusController. When no boiler is configured, ``hot_water_registered``
    stays False and the rest of the fields are None — the dashboard
    Config tab Hot Water section uses this to auto-hide the live-status
    block (same pattern as heat pump).

    All the ``_*_path`` fields are the runtime telemetry the #420 audit
    wired into the controller — surfaced here so the Diagnose modal
    shows concrete decision branches instead of black-box state.
    """
    hot_water_registered: bool = False
    hot_water_entity: Optional[str] = None
    hot_water_temperature_sensor: Optional[str] = None
    hot_water_current_temperature: Optional[float] = None
    hot_water_solar_target: Optional[float] = None
    hot_water_max_temperature: Optional[float] = None
    hot_water_legionella_target: Optional[float] = None
    hot_water_hours_since_legionella: Optional[float] = None
    hot_water_legionella_cycle_active: bool = False
    # #420 telemetry surface — same _last_*_path vocabulary as the
    # controller. Pre-wire-up these were defined but never read; this
    # dataclass plumbs them through to coordinator.data.
    hot_water_activation_path: Optional[str] = None
    hot_water_deactivation_path: Optional[str] = None
    hot_water_temperature_safety_path: Optional[str] = None
    hot_water_temperature_reading_path: Optional[str] = None
    hot_water_legionella_path: Optional[str] = None


@dataclass
class PVAnalyticsData:
    """PV analytics data for coordinator sensors."""
    pv_daily_specific_yield: float = 0.0
    pv_performance_vs_forecast: float = 0.0
    pv_estimated_annual_degradation: float = 0.0
    pv_degradation_trend: str = "unknown"


@dataclass
class EnergyAssistantSensorData:
    """Energy assistant data for coordinator sensors."""
    energy_optimization_score: int = 0
    energy_tip: str = "No recommendations at this time"
    energy_tip_category: str = "none"
    energy_ev_solar_percentage: float = 0.0


@dataclass
class UtilitySignalSensorData:
    """Utility signal data for coordinator sensors."""
    utility_signal_active: bool = False
    utility_signal_source: str = "none"
    utility_signal_count_today: int = 0


@dataclass
class EVTaperData:
    """EV taper detection state.

    Detects when the car's BMS reduces charging current as the battery
    approaches full charge (CC-CV transition). The characteristic power
    staircase (e.g. 6290W → 4340W → 2550W → 0W over ~17 min) is detected
    via linear regression on power samples where SEM's setpoint was stable.
    """
    trend: str = "unknown"          # "declining", "stable", "rising", "unknown"
    taper_ratio_pct: float = 0.0    # Current power / session peak * 100
    slope_w_per_min: float = 0.0    # Linear regression slope (negative = declining)
    minutes_to_full: float = 0.0    # Estimated minutes until BMS taper completes
    ev_full_detected: bool = False  # True when taper reached 0W after declining


@dataclass
class EVIntelligenceData:
    """EV intelligence sensor data — display-only after #440.

    Combines taper detection, virtual SOC estimation, and consumption
    prediction. The skip-decision fields (``nights_until_charge``,
    ``charge_needed``, ``charge_skip_reason``) were removed in #440
    because charge mode is the sole authority on whether to charge —
    estimated SOC and predicted consumption are diagnostic signals
    only, they do not override the user's stated mode.
    """
    taper: EVTaperData = field(default_factory=EVTaperData)
    estimated_soc_pct: Optional[float] = 0.0  # Virtual SOC (0-100); None = unknown (no anchor yet)
    last_full_charge: Optional[str] = None   # ISO timestamp of last detected full
    energy_since_full_kwh: float = 0.0       # Energy consumed since last full
    predicted_daily_ev_kwh: float = 0.0      # Tomorrow's predicted EV consumption (display)
    ev_battery_health_pct: float = 0.0       # EV battery health estimate (display)


@dataclass
class SessionData:
    """Per-session EV charging cost and energy attribution.

    Tracked by SEMCoordinator._update_session_tracking() each cycle.
    Session starts when ev_power > 50W, ends when EV disconnects.
    Data is kept after session ends for display until next session starts.

    Attributes:
        active: Whether a charging session is currently in progress.
        start_time: ISO-format timestamp of session start.
        duration_minutes: Elapsed time since session start.
        energy_kwh: Total energy delivered (solar + grid + battery).
        solar_energy_kwh: Energy from solar (via solar_to_ev flow).
        grid_energy_kwh: Energy from grid (via grid_to_ev flow).
        battery_energy_kwh: Energy from battery (via battery_to_ev flow).
        solar_share_pct: Percentage of energy from solar (0-100).
        cost_chf: Grid energy cost (grid_energy × import_rate).
        avg_power_w: Average charging power over session duration.
    """
    active: bool = False
    start_time: Optional[str] = None
    duration_minutes: float = 0
    energy_kwh: float = 0
    solar_energy_kwh: float = 0
    grid_energy_kwh: float = 0
    battery_energy_kwh: float = 0
    solar_share_pct: float = 0
    cost_chf: float = 0
    avg_power_w: float = 0


@dataclass
class BatterySessionData:
    """Per-session battery charge/discharge tracking.

    Tracks energy source attribution during charge sessions (how much
    came from solar vs grid) and savings during discharge sessions
    (avoided grid cost). Session starts when charge/discharge power
    exceeds 50W, ends when power stays below 50W for 3 consecutive
    cycles (~30s) or the battery switches direction.
    """
    active: bool = False
    session_type: str = "idle"  # "charge", "discharge", or "idle"
    start_time: Optional[str] = None
    duration_minutes: float = 0
    energy_kwh: float = 0
    solar_energy_kwh: float = 0   # charge only: from solar_to_battery flow
    grid_energy_kwh: float = 0    # charge only: from grid_to_battery flow
    solar_share_pct: float = 0    # charge only: solar / total * 100
    cost: float = 0               # charge: grid portion × import_rate
    savings: float = 0            # discharge: energy × import_rate (avoided grid)
    avg_power_w: float = 0


@dataclass
class SEMData:
    """Complete SEM data structure combining all components."""
    power: PowerReadings = field(default_factory=PowerReadings)
    power_flows: PowerFlows = field(default_factory=PowerFlows)
    energy: EnergyTotals = field(default_factory=EnergyTotals)
    energy_flows: EnergyFlows = field(default_factory=EnergyFlows)
    costs: CostData = field(default_factory=CostData)
    performance: PerformanceMetrics = field(default_factory=PerformanceMetrics)
    status: SystemStatus = field(default_factory=SystemStatus)
    load_management: LoadManagementData = field(default_factory=LoadManagementData)

    # Charging control
    charging_state: str = "idle"
    charging_strategy: str = "idle"
    charging_strategy_reason: str = ""
    available_power: float = 0.0
    calculated_current: float = 0.0

    # New phase data
    surplus_control: SurplusControlData = field(default_factory=SurplusControlData)
    forecast: ForecastSensorData = field(default_factory=ForecastSensorData)
    tariff: TariffSensorData = field(default_factory=TariffSensorData)
    heat_pump: HeatPumpSensorData = field(default_factory=HeatPumpSensorData)
    hot_water: HotWaterSensorData = field(default_factory=HotWaterSensorData)
    pv_analytics: PVAnalyticsData = field(default_factory=PVAnalyticsData)
    energy_assistant: EnergyAssistantSensorData = field(default_factory=EnergyAssistantSensorData)
    utility_signal: UtilitySignalSensorData = field(default_factory=UtilitySignalSensorData)

    # Session tracking (primary charger — backward compat)
    session: SessionData = field(default_factory=SessionData)
    # Per-charger sessions (keyed by charger_id)
    sessions: Dict[str, SessionData] = field(default_factory=dict)
    # Battery session tracking
    battery_session: BatterySessionData = field(default_factory=BatterySessionData)

    # System metadata
    currency: str = "EUR"
    # Multi-charger metadata
    ev_charger_count: int = 0
    ev_charger_ids: List[str] = field(default_factory=list)

    # EV intelligence
    ev_intelligence: EVIntelligenceData = field(default_factory=EVIntelligenceData)
    # Per-charger intelligence (#193)
    per_charger_intelligence: Dict[str, dict] = field(default_factory=dict)
    # Per-charger daily energy (#193)
    per_charger_daily_energy: Dict[str, float] = field(default_factory=dict)

    # Timestamps
    last_update: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to flat dictionary for coordinator.data."""
        data = {
            # Power readings
            "solar_power": self.power.solar_power,
            "grid_power": self.power.grid_power,
            "grid_active_power": -self.power.grid_power,  # positive=import, negative=export (K-Flow convention)
            "battery_power": self.power.battery_power,
            "ev_power": self.power.ev_power,
            "home_consumption_power": self.power.home_consumption_power,
            "grid_import_power": self.power.grid_import_power,
            "grid_export_power": self.power.grid_export_power,
            "battery_charge_power": self.power.battery_charge_power,
            "battery_discharge_power": self.power.battery_discharge_power,
            "battery_soc": None if self.power.battery_soc_unavailable else self.power.battery_soc,
            "battery_temperature": self.power.battery_temperature,
            "battery_cycles_estimated": self.power.battery_cycles_estimated,
            "battery_health_score": self.power.battery_health_score,
            "ev_connected": self.power.ev_connected,
            "ev_charging": self.power.ev_charging,

            # Power flows
            "flow_solar_to_home_power": self.power_flows.solar_to_home,
            "flow_solar_to_battery_power": self.power_flows.solar_to_battery,
            "flow_solar_to_ev_power": self.power_flows.solar_to_ev,
            "flow_solar_to_grid_power": self.power_flows.solar_to_grid,
            "flow_grid_to_home_power": self.power_flows.grid_to_home,
            "flow_grid_to_ev_power": self.power_flows.grid_to_ev,
            "flow_grid_to_battery_power": self.power_flows.grid_to_battery,
            "flow_battery_to_home_power": self.power_flows.battery_to_home,
            "flow_battery_to_ev_power": self.power_flows.battery_to_ev,

            # Daily energy
            "daily_solar_energy": self.energy.daily_solar,
            "daily_home_energy": self.energy.daily_home,
            "daily_ev_energy": self.energy.daily_ev,
            "daily_grid_import_energy": self.energy.daily_grid_import,
            "daily_grid_export_energy": self.energy.daily_grid_export,
            "daily_battery_charge_energy": self.energy.daily_battery_charge,
            "daily_battery_discharge_energy": self.energy.daily_battery_discharge,

            # Monthly energy
            "monthly_solar_yield_energy": self.energy.monthly_solar,
            "monthly_home_consumption_energy": self.energy.monthly_home,
            "monthly_grid_import_energy": self.energy.monthly_grid_import,
            "monthly_grid_export_energy": self.energy.monthly_grid_export,
            "monthly_battery_charge_energy": self.energy.monthly_battery_charge,
            "monthly_battery_discharge_energy": self.energy.monthly_battery_discharge,

            # Yearly energy
            "yearly_solar_yield_energy": self.energy.yearly_solar,
            "yearly_home_consumption_energy": self.energy.yearly_home,
            "yearly_grid_import_energy": self.energy.yearly_grid_import,
            "yearly_grid_export_energy": self.energy.yearly_grid_export,
            "yearly_battery_charge_energy": self.energy.yearly_battery_charge,
            "yearly_battery_discharge_energy": self.energy.yearly_battery_discharge,
            "yearly_ev_energy": self.energy.yearly_ev,

            # Energy flows
            "flow_solar_to_home_energy": self.energy_flows.solar_to_home,
            "flow_solar_to_battery_energy": self.energy_flows.solar_to_battery,
            "flow_solar_to_ev_energy": self.energy_flows.solar_to_ev,
            "flow_solar_to_grid_energy": self.energy_flows.solar_to_grid,
            "flow_grid_to_home_energy": self.energy_flows.grid_to_home,
            "flow_grid_to_ev_energy": self.energy_flows.grid_to_ev,
            "flow_grid_to_battery_energy": self.energy_flows.grid_to_battery,
            "flow_battery_to_home_energy": self.energy_flows.battery_to_home,
            "flow_battery_to_ev_energy": self.energy_flows.battery_to_ev,

            # Per-charger flow surface (v1.6.15). Emit only when the
            # multi-charger pipeline has populated these maps; in
            # single-charger setups the dicts are empty and the keys
            # are skipped, so the fleet sensors stay authoritative.
            **{
                f"charger_{cid}_flow_solar_to_ev_power": cf.solar_to_ev
                for cid, cf in (self.power_flows.per_charger or {}).items()
            },
            **{
                f"charger_{cid}_flow_grid_to_ev_power": cf.grid_to_ev
                for cid, cf in (self.power_flows.per_charger or {}).items()
            },
            **{
                f"charger_{cid}_flow_battery_to_ev_power": cf.battery_to_ev
                for cid, cf in (self.power_flows.per_charger or {}).items()
            },
            **{
                f"charger_{cid}_flow_solar_to_ev_energy": cef.solar_to_ev
                for cid, cef in (self.energy_flows.per_charger or {}).items()
            },
            **{
                f"charger_{cid}_flow_grid_to_ev_energy": cef.grid_to_ev
                for cid, cef in (self.energy_flows.per_charger or {}).items()
            },
            **{
                f"charger_{cid}_flow_battery_to_ev_energy": cef.battery_to_ev
                for cid, cef in (self.energy_flows.per_charger or {}).items()
            },

            # Per-PV-string surface (v1.7.0 / #312). Emit only when
            # multi-string discovery populated these. Single-string
            # / single-inverter setups skip the keys and the fleet
            # ``sensor.sem_solar_power`` stays authoritative.
            **{
                f"pv_string_{sid}_power": w
                for sid, w in (self.power.solar_power_per_string or {}).items()
            },
            **{
                f"pv_string_{sid}_daily_energy": se.energy_kwh
                for sid, se in (self.energy_flows.per_string or {}).items()
            },

            # Costs
            "daily_costs": self.costs.daily_costs,
            "daily_savings": self.costs.daily_savings,
            "daily_export_revenue": self.costs.daily_export_revenue,
            "daily_net_cost": self.costs.daily_net_cost,
            "daily_battery_savings": self.costs.daily_battery_savings,
            "monthly_costs": self.costs.monthly_costs,
            "monthly_savings": self.costs.monthly_savings,
            "monthly_export_revenue": self.costs.monthly_export_revenue,
            "monthly_net_cost": self.costs.monthly_net_cost,
            # Yearly costs
            "yearly_costs": self.costs.yearly_costs,
            "yearly_savings": self.costs.yearly_savings,
            "yearly_battery_savings": self.costs.yearly_battery_savings,
            "yearly_export_revenue": self.costs.yearly_export_revenue,
            "yearly_net_cost": self.costs.yearly_net_cost,

            # Environmental impact
            "daily_co2_avoided": self.costs.daily_co2_avoided_kg,
            "yearly_co2_avoided": self.costs.yearly_co2_avoided_kg,
            "yearly_trees_equivalent": self.costs.yearly_trees_equivalent,
            "lifetime_co2_avoided": self.costs.lifetime_co2_avoided_kg,
            "lifetime_trees_equivalent": self.costs.lifetime_trees_equivalent,

            # ROI
            "lifetime_total_savings": self.costs.lifetime_total_savings,
            "lifetime_grid_cost": self.costs.lifetime_grid_cost,
            "roi_percentage": self.costs.roi_percentage,
            "roi_payback_years": self.costs.roi_payback_years,
            "roi_annual_savings": self.costs.roi_annual_savings,

            # Financial additions
            "battery_discharge_value": self.costs.daily_battery_savings,
            "monthly_battery_savings": self.costs.monthly_battery_savings,

            # Performance
            "self_consumption_rate": self.performance.self_consumption_rate,
            "autarky_rate": self.performance.autarky_rate,
            "solar_efficiency": self.performance.solar_efficiency,
            "battery_efficiency": self.performance.battery_efficiency,

            # Status
            "grid_status": self.status.grid_status,
            "battery_status": self.status.battery_status,
            "solar_active": self.status.solar_active,
            "battery_charging": self.status.battery_charging,
            "battery_discharging": self.status.battery_discharging,
            "grid_export_active": self.status.grid_export_active,

            # Charging control
            "charging_state": self.charging_state,
            "charging_strategy": self.charging_strategy,
            "charging_strategy_reason": self.charging_strategy_reason,
            "available_power": self.available_power,
            "calculated_current": self.calculated_current,

            # EV aliases and routing
            "ev_charging_power": self.power.ev_power,
            "ev_max_current": self.calculated_current,
            "ev_max_current_available": self.calculated_current,

            # Status sensors (derived from charging_state)
            "solar_charging_status": self._get_solar_charging_status(),
            "night_charging_status": self._get_night_charging_status(),
            "battery_priority_status": self._get_battery_priority_status(),
            "solar_optimization_status": "active" if self.power.solar_power > 50 else "idle",
            "grid_management_status": self.status.grid_status,

            # Legacy aliases for compatibility
            "solar_production_total": self.power.solar_power,

            # Load management
            "target_peak_limit": self.load_management.target_peak_limit,
            "peak_margin": self.load_management.peak_margin,
            "load_management_status": self.load_management.load_management_status,
            "loads_currently_shed": self.load_management.loads_currently_shed,
            "available_load_reduction": self.load_management.available_load_reduction,
            "controllable_devices_count": self.load_management.controllable_devices_count,
            "consecutive_peak_15min": self.load_management.consecutive_peak_15min,
            "monthly_consecutive_peak": self.load_management.monthly_consecutive_peak,
            "current_vs_peak_percentage": self.load_management.current_vs_peak_percentage,
            "controlled_tariff_status": self.load_management.controlled_tariff_status,
            "load_management_recommendation": self.load_management.load_management_recommendation,
            "power_charge_cost": self.load_management.power_charge_cost,
            "peak_trend": self.load_management.peak_trend,
            "tariff_type": self.load_management.tariff_type,

            # Timestamp
            "last_update": self.last_update,

            # Surplus controller (Phase 0)
            "surplus_total_w": self.surplus_control.surplus_total_w,
            "surplus_distributable_w": self.surplus_control.surplus_distributable_w,
            "surplus_regulation_offset_w": self.surplus_control.surplus_regulation_offset_w,
            "surplus_allocated_w": self.surplus_control.surplus_allocated_w,
            "surplus_unallocated_w": self.surplus_control.surplus_unallocated_w,
            "surplus_active_devices": self.surplus_control.surplus_active_devices,
            "surplus_total_devices": self.surplus_control.surplus_total_devices,

            # Forecast (Phase 0)
            "forecast_today_kwh": self.forecast.forecast_today_kwh,
            "forecast_tomorrow_kwh": self.forecast.forecast_tomorrow_kwh,
            "forecast_remaining_today_kwh": self.forecast.forecast_remaining_today_kwh,
            # (#544) forecast_power_now_w / forecast_power_next_hour_w removed — dead.
            "forecast_peak_power_today_w": self.forecast.forecast_peak_power_today_w,
            "forecast_peak_time_today": self.forecast.forecast_peak_time_today,
            "forecast_source": self.forecast.forecast_source,
            "forecast_available": self.forecast.forecast_available,
            "charging_recommendation": self.forecast.charging_recommendation,
            "best_surplus_window": self.forecast.best_surplus_window,
            "forecast_surplus_kwh": self.forecast.forecast_surplus_kwh,
            "forecast_dampening_factor": self.forecast.forecast_dampening_factor,

            # Tariff (Phase 1)
            "tariff_current_import_rate": self.tariff.tariff_current_import_rate,
            "tariff_current_export_rate": self.tariff.tariff_current_export_rate,
            "tariff_price_level": self.tariff.tariff_price_level,
            "tariff_provider": self.tariff.tariff_provider,
            "tariff_is_dynamic": self.tariff.tariff_is_dynamic,
            "tariff_today_min_price": self.tariff.tariff_today_min_price,
            "tariff_today_max_price": self.tariff.tariff_today_max_price,
            "tariff_today_avg_price": self.tariff.tariff_today_avg_price,
            "tariff_next_cheap_start": self.tariff.tariff_next_cheap_start,
            "tariff_classifier_path": self.tariff.tariff_classifier_path,

            # Heat pump (Phase 2)
            "heat_pump_registered": self.heat_pump.heat_pump_registered,
            "heat_pump_mode": self.heat_pump.heat_pump_mode,
            "heat_pump_sg_ready_state": self.heat_pump.heat_pump_sg_ready_state,
            "heat_pump_solar_boost": self.heat_pump.heat_pump_solar_boost,
            # #432 diagnostic surface — exposed via
            # ``sensor.sem_heat_pump_registration_status`` state +
            # extra_state_attributes for self-diagnosis.
            "heat_pump_registration_status": self.heat_pump.heat_pump_registration_status,
            "heat_pump_relay1_entity": self.heat_pump.heat_pump_relay1_entity,
            "heat_pump_relay2_entity": self.heat_pump.heat_pump_relay2_entity,
            "heat_pump_climate_entity": self.heat_pump.heat_pump_climate_entity,
            "heat_pump_relay1_state": self.heat_pump.heat_pump_relay1_state,
            "heat_pump_relay2_state": self.heat_pump.heat_pump_relay2_state,
            "heat_pump_climate_state": self.heat_pump.heat_pump_climate_state,
            # v1.7.2-beta.2: #421 audit's runtime path recorders.
            # Internal Python attrs on HeatPumpController, now wired
            # through the dataclass so the diagnose surface + any
            # future "Why did the heat pump (not) activate?" UI can
            # show concrete decision branches instead of black-box state.
            "heat_pump_activation_path": self.heat_pump.heat_pump_activation_path,
            "heat_pump_deactivation_path": self.heat_pump.heat_pump_deactivation_path,
            "heat_pump_relay_path": self.heat_pump.heat_pump_relay_path,
            "heat_pump_temperature_reading_path": self.heat_pump.heat_pump_temperature_reading_path,
            "heat_pump_offpeak_path": self.heat_pump.heat_pump_offpeak_path,
            "heat_pump_current_temperature": self.heat_pump.heat_pump_current_temperature,

            # Hot water (#454)
            "hot_water_registered": self.hot_water.hot_water_registered,
            "hot_water_entity": self.hot_water.hot_water_entity,
            "hot_water_temperature_sensor": self.hot_water.hot_water_temperature_sensor,
            "hot_water_current_temperature": self.hot_water.hot_water_current_temperature,
            "hot_water_solar_target": self.hot_water.hot_water_solar_target,
            "hot_water_max_temperature": self.hot_water.hot_water_max_temperature,
            "hot_water_legionella_target": self.hot_water.hot_water_legionella_target,
            "hot_water_hours_since_legionella": self.hot_water.hot_water_hours_since_legionella,
            "hot_water_legionella_cycle_active": self.hot_water.hot_water_legionella_cycle_active,
            "hot_water_activation_path": self.hot_water.hot_water_activation_path,
            "hot_water_deactivation_path": self.hot_water.hot_water_deactivation_path,
            "hot_water_temperature_safety_path": self.hot_water.hot_water_temperature_safety_path,
            "hot_water_temperature_reading_path": self.hot_water.hot_water_temperature_reading_path,
            "hot_water_legionella_path": self.hot_water.hot_water_legionella_path,

            # PV analytics (Phase 5)
            "pv_daily_specific_yield": self.pv_analytics.pv_daily_specific_yield,
            "pv_performance_vs_forecast": self.pv_analytics.pv_performance_vs_forecast,
            "pv_estimated_annual_degradation": self.pv_analytics.pv_estimated_annual_degradation,
            "pv_degradation_trend": self.pv_analytics.pv_degradation_trend,

            # Energy assistant (Phase 6)
            "energy_optimization_score": self.energy_assistant.energy_optimization_score,
            "energy_tip": self.energy_assistant.energy_tip,
            "energy_tip_category": self.energy_assistant.energy_tip_category,
            "energy_ev_solar_percentage": self.energy_assistant.energy_ev_solar_percentage,

            # Utility signals (Phase 7)
            "utility_signal_active": self.utility_signal.utility_signal_active,
            "utility_signal_source": self.utility_signal.utility_signal_source,
            "utility_signal_count_today": self.utility_signal.utility_signal_count_today,

            # Session tracking (primary charger)
            "session_active": self.session.active,
            "session_energy": self.session.energy_kwh,
            "session_solar_share": self.session.solar_share_pct,
            "session_cost": self.session.cost_chf,
            "session_duration": self.session.duration_minutes,
            "session_solar_energy": self.session.solar_energy_kwh,
            "session_grid_energy": self.session.grid_energy_kwh,
            "session_battery_energy": self.session.battery_energy_kwh,
            "session_avg_power": self.session.avg_power_w,

            # Battery session tracking
            "battery_session_active": self.battery_session.active,
            "battery_session_type": self.battery_session.session_type,
            "battery_session_energy": self.battery_session.energy_kwh,
            "battery_session_solar_share": self.battery_session.solar_share_pct,
            "battery_session_cost": self.battery_session.cost,
            "battery_session_savings": self.battery_session.savings,
            "battery_session_duration": self.battery_session.duration_minutes,
            "battery_session_avg_power": self.battery_session.avg_power_w,

            # System metadata
            "currency": self.currency,
            # Multi-charger
            "ev_charger_count": self.ev_charger_count,
            "ev_charger_ids": self.ev_charger_ids,
        }

        # Per-charger data (dynamic keys: charger_{id}_power, charger_{id}_session_energy, etc.)
        try:
            for cid in self.ev_charger_ids:
                session = self.sessions.get(cid, SessionData())
                data.update({
                    f"charger_{cid}_session_energy": round(session.energy_kwh, 2),
                    f"charger_{cid}_session_solar_share": round(session.solar_share_pct, 1),
                    f"charger_{cid}_session_duration": round(session.duration_minutes, 1),
                    f"charger_{cid}_daily_energy": round(
                        self.per_charger_daily_energy.get(cid, 0.0), 2
                    ),
                })
        except Exception as e:
            _LOGGER.warning("Per-charger to_dict failed: %s", e)

        # Per-battery flat-dict unpack (Phase A of #TBD fleet/per-battery
        # card mirror). Mirrors the per-charger pattern above. Powered
        # by ``PowerReadings.batteries`` (populated by sensor_reader
        # only when ``battery_power_list`` length > 1 — single-battery
        # installs leave it empty and produce zero per-battery keys,
        # preserving today's fleet-sensor behaviour). Status is
        # derived from the sign of power_w (positive = charging,
        # negative = discharging, near-zero = idle); the
        # ``_BATTERY_STATUS_DEADBAND_W`` mirrors the session-tracking
        # dead-band so the per-battery status doesn't toggle on
        # inverter rebalance noise.
        try:
            _STATUS_DEADBAND_W = 50.0
            for bid, bp in self.power.batteries.items():
                if bp.power_w > _STATUS_DEADBAND_W:
                    status = "charging"
                elif bp.power_w < -_STATUS_DEADBAND_W:
                    status = "discharging"
                else:
                    status = "idle"
                data.update({
                    f"battery_{bid}_power": round(bp.power_w, 1),
                    f"battery_{bid}_soc": round(bp.soc_pct, 1),
                    f"battery_{bid}_status": status,
                    f"battery_{bid}_capacity_kwh": round(bp.capacity_kwh, 1),
                })
        except Exception as e:
            _LOGGER.warning("Per-battery to_dict failed: %s", e)

        # Per-charger intelligence from taper detectors (#193)
        try:
            per_charger_intel = self.per_charger_intelligence
            for cid, intel in per_charger_intel.items():
                data.update({
                    f"charger_{cid}_estimated_soc": intel.get("estimated_soc", 0),
                    # #383: real vehicle SOC reading per charger (None
                    # when no per-charger ``vehicle_soc_entity`` is
                    # configured). The card prefers this over the
                    # global ``sensor.sem_vehicle_soc`` which gets
                    # clobbered across the per-charger update loop.
                    f"charger_{cid}_vehicle_soc": intel.get("vehicle_soc"),
                    f"charger_{cid}_taper_minutes_to_full": intel.get("minutes_to_full"),
                })
        except Exception as e:
            _LOGGER.warning("Per-charger intelligence to_dict failed: %s", e)

        # EV intelligence — access safely in case taper data is incomplete
        try:
            _ei = self.ev_intelligence
            # (#544) only ev_taper_trend remains (DIAGNOSTIC_SENSOR); the rest
            # of the fleet EV-intelligence sensors were dead and removed.
            data.update({
                "ev_taper_trend": _ei.taper.trend,
            })
        except Exception as e:
            _LOGGER.warning("EV intelligence to_dict failed: %s", e)

        return data

    def _get_solar_charging_status(self) -> str:
        """Get solar charging status from charging state."""
        solar_states = ["solar_charging_active", "solar_super_charging", "solar_target_reached", "solar_min_pv"]
        if self.charging_state in solar_states:
            return "active"
        elif "solar" in self.charging_state.lower():
            return self.charging_state.replace("solar_", "")
        return "idle"

    def _get_night_charging_status(self) -> str:
        """Get night charging status from charging state."""
        night_states = ["night_charging_active", "night_target_reached"]
        if self.charging_state in night_states:
            return "active"
        elif "night" in self.charging_state.lower():
            return self.charging_state.replace("night_", "")
        return "idle"


    def _get_battery_priority_status(self) -> str:
        """Get battery priority status from charging state."""
        if self.charging_state == "solar_waiting_battery_priority":
            return "waiting"
        if self.power.battery_soc < 80:  # Default priority threshold
            return "priority"
        return "normal"
