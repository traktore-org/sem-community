"""SEM Solar Energy Management sensors."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorEntityDescription,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfPower,
    UnitOfEnergy,
    UnitOfElectricCurrent,
    UnitOfLength,
    UnitOfTemperature,
    UnitOfTime,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr

from .const import SENSOR_LABEL_MAPPING
from .consts.labels import SEM_LABELS
from .coordinator import SEMCoordinator
from .features.device_axes import (
    has_control_handle as _has_control_handle,
    may_actuate as _may_actuate,
    user_hands_off as _user_hands_off,
)

type SEMConfigEntry = ConfigEntry[SEMCoordinator]

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0  # Coordinator handles all updates


def _energy_plan_state(plan: Any) -> str:
    """(#638) Collapse tonight's plan to one verdict word.

    ``pending`` — the planner has not answered for tonight yet (before the
    night window, or still waiting on a not-ready world). ``idle`` — it
    answered "nothing needs the night", which is a real answer, not a gap.
    ``fits`` / ``yields`` — everything got its floor, or something did not.
    """
    if not isinstance(plan, dict):
        return "pending"
    if not plan.get("demands"):
        return "idle"
    return "fits" if plan.get("fits") else "yields"


# HA's recorder refuses to store a state whose attributes serialize above
# 16 KiB: it logs a warning and records NO attributes at all, so the plan
# would silently vanish from history. Stay under it with headroom.
_PLAN_ATTR_BUDGET_BYTES = 15000


def _merge_plan_blocks(blocks: Any) -> List[Dict[str, Any]]:
    """(#638) Collapse a demand's back-to-back slot allocations into runs.

    The packer allocates per market slot, so a pump running four consecutive
    quarter-hours arrives as four blocks. The strip draws them as one bar
    regardless, and on a 15-minute curve those per-slot blocks are the single
    largest term in the payload — merging them is free to the card and is
    what keeps a normal 15-min night under the recorder's limit at all.

    ``price`` is dropped rather than carried: a merged run spans slots that
    may differ in price, and quoting one of them would be a lie. The per-slot
    prices stay on the ledger rows, and ``diagnose`` still has every original
    allocation with its own price.

    Grouping by demand id is load-bearing, not tidiness: the packer emits
    allocations SLOT-major (every demand for 05:00, then every demand for
    06:00), so a demand's own consecutive blocks are never neighbours in the
    list. Comparing each block only against the previous one merges nothing
    at all on real data — verified live on HA-TEST.
    """
    by_id: Dict[Any, List[Dict[str, Any]]] = {}
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        by_id.setdefault(b.get("id"), []).append({
            "id": b.get("id"),
            "start": b.get("start"),
            "end": b.get("end"),
            "power_w": b.get("power_w"),
        })
    out: List[Dict[str, Any]] = []
    for rows in by_id.values():
        rows.sort(key=lambda r: str(r["start"]))
        run: List[Dict[str, Any]] = []
        for row in rows:
            prev = run[-1] if run else None
            if (prev and prev["power_w"] == row["power_w"]
                    and prev["end"] == row["start"]):
                prev["end"] = row["end"]
                continue
            run.append(row)
        out.extend(run)
    return out


def _energy_plan_attrs(
    plan: Any, extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """(#638) Project tonight's stashed plan into entity attributes.

    ``extra`` is for the payloads that ride on the SAME state but do not
    come from the plan — ``tomorrow``, the #755 ``review``. They belong
    here rather than at the call site because the byte budget below is
    the whole point of this function: the recorder weighs the finished
    state, not the part of it this projection happened to build, and a
    trim computed before the last two writers is a trim that does not
    trim (#758). One place adds, one place counts.

    Three things are deliberately not copied wholesale:

    * ``summary`` / ``allocations`` — log prose. The logs quote it and the
      ``diagnose`` payload carries it; the card reads the structured rows.
    * the ledger's ``home_w`` and ``soc_kwh`` columns — the strip does not
      draw them, and they are most of what pushes a 15-minute price curve
      over a long winter night past the recorder's limit.
    * per-slot allocations — merged into runs, see ``_merge_plan_blocks``.

    If the projection is *still* too large (a 15-min curve × a large fleet),
    the timeline is dropped rather than the whole payload: the card falls
    back to the per-demand list and says the chart was omitted. A visibly
    reduced card beats an entity whose attributes disappear from history.
    """
    if not isinstance(plan, dict):
        # Daytime: no plan to project, but the review still has to reach the
        # card — it is the record of LAST night, not of tonight's.
        return {k: v for k, v in (extra or {}).items() if v}
    attrs: Dict[str, Any] = {
        "computed_at": plan.get("computed_at"),
        "fits": plan.get("fits"),
        "total_cost": plan.get("total_cost"),
        "takeover": plan.get("takeover"),
        "demands": plan.get("demands") or [],
        "slots": [{
            "start": s.get("start"), "end": s.get("end"),
            "price": s.get("price"), "cheap": s.get("cheap"),
            "home_grid_w": s.get("home_grid_w"),
        } for s in (plan.get("slots") or [])],
        "blocks": _merge_plan_blocks(plan.get("blocks")),
        # A string here means the battery figures behind this plan came from
        # a SUBSET of the fleet (#638 finding #3) — the card says so rather
        # than presenting a degraded plan as a healthy one.
        "battery_fleet_partial": plan.get("battery_fleet_partial"),
        # (#638 G4) True while the actuation switch is on — the plan's
        # blocks feed the night signals; the card swaps its shadow chip.
        "actuation": bool(plan.get("actuation", False)),
        # (night 3, finding 3) "initial" vs "ask changed" — a re-stamped
        # night is distinguishable from the first answer on the entity,
        # not only in container logs (which rotate too fast for evidence).
        "replan_cause": plan.get("replan_cause"),
        # (08-08) the idle answer's why — the card shows it so a quiet
        # plan reads as an answer, never as a disappearance.
        "why": plan.get("why"),
        # (#638 C7) what will NOT be done and why — the card's
        # "not scheduled tonight" list, machine keys the card translates.
        "not_scheduled": plan.get("not_scheduled") or [],
        # (#638 C7) the quiet face's machine codes → translated sentences.
        "why_codes": plan.get("why_codes") or [],
        # (#638 C7) per-demand plan-vs-reactive attribution, live.
        "coverage": plan.get("coverage") or {},
        # (#638, the last string) the shadow arbitrage advisor's verdict
        # with its numbers — the morning plan-vs-Sankey audit reads it
        # here. Small by construction (a few blocks at most).
        "arbitrage": plan.get("arbitrage"),
    }
    for key, value in (extra or {}).items():
        if value:
            attrs[key] = value
    def _too_big() -> bool:
        try:
            return len(json.dumps(attrs, default=str)) > _PLAN_ATTR_BUDGET_BYTES
        except (TypeError, ValueError):  # pragma: no cover — defensive
            return True

    if _too_big():
        attrs["slots"] = []
        attrs["blocks"] = []
        attrs["timeline_omitted"] = True
    # (#758) The timeline is the biggest term, but it is not the only one,
    # and going over means the recorder keeps NOTHING. If dropping it was
    # not enough, drop what rode along and say so — the plan itself is what
    # this entity is for.
    if extra and _too_big():
        for key in extra:
            attrs.pop(key, None)
        attrs["extras_omitted"] = True
    return attrs


def _phase_guard_current_description(*, key: str) -> SensorEntityDescription:
    """Create one translated read-only phase-current diagnostic.

    Disabled by default: these only carry data once the phase guard is
    configured, and registering 12 permanently-unavailable entities on
    every unconfigured install is registry churn (repo pattern for
    rarely-used diagnostics)."""
    return SensorEntityDescription(
        key=key,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
    )


SENSOR_TYPES = [

    # ============================================================================
    # CORE REAL-TIME POWER MEASUREMENTS
    # ============================================================================
    # These sensors provide instantaneous power readings and are the foundation
    # of the Solar Energy Management system.
    # 
    # Hardware Requirements:
    #   - Solar inverter (Huawei Solar or compatible)
    # ============================================================================

    SensorEntityDescription(
        key="solar_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="home_consumption_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="grid_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="grid_active_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="grid_import_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="grid_export_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="battery_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="battery_charge_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="battery_discharge_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="ev_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    # Removed: ev_charging_power — duplicate of ev_power
    SensorEntityDescription(
        key="available_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),

    # ============================================================================
    # BATTERY STATUS & MONITORING
    # ============================================================================
    # Comprehensive battery health, status, and performance metrics.
    # 
    # Hardware Requirements:
    #   - Battery storage system (e.g., Huawei LUNA2000)
    # ============================================================================

    SensorEntityDescription(
        key="battery_soc",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="battery_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="battery_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SensorEntityDescription(
        key="inverter_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SensorEntityDescription(
        key="battery_cycles_estimated",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=1,
        icon="mdi:battery-sync",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="battery_health_score",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        icon="mdi:battery-heart-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),

    # ============================================================================
    # EV CHARGING CONTROL & STATUS
    # ============================================================================
    # EV charger control parameters and charging session tracking.
    # 
    # Hardware Requirements:
    #   - EV wallbox (e.g., KEBA P30 c-series)
    # ============================================================================

    SensorEntityDescription(
        key="calculated_current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
    ),
    # Removed: ev_max_current, ev_max_current_available — duplicates of calculated_current
    # Removed: EV session/total energy - not useful (session resets on plug, total tracked by Energy Dashboard)

    # ============================================================================
    # CHARGING STATE & AUTOMATION STATUS
    # ============================================================================
    # System automation states, charging modes, and decision tracking.
    # These sensors reflect the current operational mode and automation decisions.
    # ============================================================================

    SensorEntityDescription(
        key="charging_state",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="grid_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="solar_charging_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="night_charging_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # (#638) The joint energy planner's verdict for tonight. SHADOW: this
    # reports what the planner WOULD do — nothing here actuates. State is a
    # stable key (``fits``/``yields``/``idle``/``pending``) so the card and
    # the tests can branch on it; the plan itself rides as attributes.
    SensorEntityDescription(
        key="energy_plan",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="battery_priority_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="charging_strategy",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # Removed: solar_optimization_status — just checks solar_power > 50, no real logic
    # Removed: grid_management_status — duplicate of grid_status
    # Removed: Debug sensors (use load_management_status instead)
    # automation_decision_reason, controlled_tariff_status
    # Removed: Energy Source Debug Sensors (redundant, use HA Energy Dashboard)
    # energy_source_solar_status, energy_source_home_status, energy_source_grid_import_status
    # energy_source_grid_export_status, energy_source_battery_charge_status, energy_source_battery_discharge_status
    # energy_system_health

    # ============================================================================
    # DAILY ENERGY TOTALS
    # ============================================================================
    # Today's cumulative energy measurements (reset at midnight 00:00).
    # 
    # State Class: TOTAL (with last_reset at midnight)
    # ============================================================================

    SensorEntityDescription(
        key="daily_solar_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    # Removed: Redundant solar yield sensors (use daily_solar_energy instead)
    # daily_solar_yield_energy, daily_solar_yield_efficiency_adjusted_energy
    SensorEntityDescription(
        key="daily_home_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="daily_grid_import_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="daily_grid_export_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="daily_battery_charge_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="daily_battery_discharge_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    # (#770) The charge, split by origin. One number for free roof energy and
    # bought valley energy is what made savings and ROI credit a grid-charged
    # kWh with the full import price it never earned — and the joint planner
    # made grid charging the norm, not the exception.
    SensorEntityDescription(
        key="daily_battery_charge_solar",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="daily_battery_charge_grid",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="daily_battery_grid_cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",  # replaced by hass.config.currency
        suggested_display_precision=2,
    ),
    # What is IN the battery right now, not what went in today — the figure
    # autarky needs, because a grid-charged discharge is grid supply that was
    # merely time-shifted.
    SensorEntityDescription(
        key="battery_stored_grid_share",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
    ),
    # (#773) The audited residual: home minus every controlled load SEM can
    # see. The house SEM does NOT touch — and therefore the row whose drift
    # is a free sensor-health check. Both may go NEGATIVE: that is the
    # diagnostic's sharpest finding (a double-count or sign error), so no
    # clamp and no non-negative device_class assumptions beyond what HA's
    # POWER/ENERGY classes already allow.
    SensorEntityDescription(
        key="true_baseload_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="daily_true_baseload_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="daily_ev_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    # Removed: Redundant (use daily_home_energy instead)
    # daily_home_consumption_actual_energy

    # ============================================================================
    # MONTHLY ENERGY TOTALS
    # ============================================================================
    # This month's cumulative energy measurements (reset on 1st of month).
    # 
    # State Class: TOTAL (with last_reset at first of month)
    # ============================================================================

    SensorEntityDescription(
        key="monthly_solar_yield_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="monthly_grid_import_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="monthly_grid_export_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="monthly_battery_charge_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="monthly_battery_discharge_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="monthly_home_consumption_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    # #666 — the last of its label-registry siblings to get an entity. The
    # monthly EV accumulator was always written and ``consts/labels.py``
    # always declared ``monthly_ev_consumption``; only this was missing.
    SensorEntityDescription(
        key="monthly_ev_consumption_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    # Removed: Redundant (use monthly_home_consumption_energy instead)
    # monthly_home_consumption_actual_energy

    # ============================================================================
    # YEARLY ENERGY TOTALS (reset on Jan 1)
    # ============================================================================
    SensorEntityDescription(
        key="yearly_solar_yield_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        # #573 — lifetime solar production; seeded from and reconciled against
        # the inverter's own energy counter, so it matches TotalActiveProduction
        # / Gesamtenergieertrag. state_class TOTAL (not TOTAL_INCREASING) to match
        # the sibling monthly/yearly solar-yield sensors and to tolerate the rare
        # one-time #551 downward self-heal re-seed (Wh-as-kWh correction) without
        # tripping HA's "total_increasing went backwards" warning.
        key="lifetime_solar_yield_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        icon="mdi:solar-power-variant",
    ),
    SensorEntityDescription(
        key="yearly_grid_import_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="yearly_grid_export_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="yearly_battery_charge_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="yearly_battery_discharge_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="yearly_home_consumption_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="yearly_ev_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),

    # ============================================================================
    # YEARLY COSTS
    # ============================================================================
    SensorEntityDescription(
        key="yearly_costs",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="yearly_savings",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="yearly_battery_savings",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="yearly_export_revenue",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="yearly_net_cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
        suggested_display_precision=2,
    ),

    # ============================================================================
    # ROI
    # ============================================================================
    SensorEntityDescription(
        key="lifetime_total_savings",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
        icon="mdi:cash-check",
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="lifetime_grid_cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
        icon="mdi:cash-minus",
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="roi_percentage",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="%",
        icon="mdi:chart-line",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="roi_payback_years",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="years",
        icon="mdi:calendar-clock",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="roi_annual_savings",
        device_class=SensorDeviceClass.MONETARY,
        # (#646) monetary permits only state_class None/TOTAL — MEASUREMENT
        # was invalid and broke long-term statistics.
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
        icon="mdi:cash-fast",
        suggested_display_precision=0,
    ),

    # ============================================================================
    # FORECAST ACCURACY
    # ============================================================================
    # (#544) forecast_accuracy_today / forecast_accuracy_7d removed — dead
    # (written by forecast_tracker, read by no card/decision).
    SensorEntityDescription(
        key="forecast_correction_factor",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:tune-vertical",
        suggested_display_precision=2,
    ),
    # (#544) forecast_deviation_kwh removed — dead.
    SensorEntityDescription(
        key="forecast_corrected_today",
        # (#646) no ENERGY device_class — this is a *prediction* that moves
        # up and down, not measured energy accumulation; energy permits only
        # TOTAL/TOTAL_INCREASING, so the pairing was invalid.
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:crystal-ball",
        suggested_display_precision=1,
    ),
    # (#544) forecast_corrected_tomorrow removed — dead.
    SensorEntityDescription(
        key="forecast_history_days",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:calendar-clock",
    ),

    # ============================================================================
    # ENVIRONMENTAL IMPACT
    # ============================================================================
    SensorEntityDescription(
        key="daily_co2_avoided",
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="kg",
        icon="mdi:molecule-co2",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="yearly_co2_avoided",
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="kg",
        icon="mdi:molecule-co2",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="yearly_trees_equivalent",
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="trees",
        icon="mdi:tree",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="lifetime_co2_avoided",
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="kg",
        icon="mdi:molecule-co2",
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="lifetime_trees_equivalent",
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="trees",
        icon="mdi:forest",
        suggested_display_precision=1,
    ),

    # ============================================================================
    # REAL-TIME POWER FLOWS
    # ============================================================================
    # Instantaneous power flows between system components.
    # These are calculated values showing current power distribution.
    # Used for Power Flow cards and real-time visualizations.
    # ============================================================================

    SensorEntityDescription(
        key="flow_solar_to_home_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="flow_solar_to_battery_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="flow_solar_to_grid_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="flow_solar_to_ev_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="flow_battery_to_home_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    # (#776) Exported battery energy — force_discharge / the arbitrage
    # sell. Doubles as the compliance witness for installs whose grid
    # contract prohibits selling stored energy: it must read 0 there.
    SensorEntityDescription(
        key="flow_battery_to_grid_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="flow_battery_to_ev_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="flow_grid_to_home_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="flow_grid_to_ev_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="flow_grid_to_battery_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),

    # ============================================================================
    # ENERGY FLOW TOTALS (FOR SANKEY CHARTS)
    # ============================================================================
    # Cumulative energy flows between components.
    # These are TOTAL sensors that track energy flows over time.
    # 
    # Primary use: Sankey Chart visualization in Energy Dashboard
    # State Class: TOTAL (reset daily at midnight)
    # ============================================================================

    SensorEntityDescription(
        key="flow_solar_to_home_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="flow_solar_to_ev_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="flow_solar_to_battery_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="flow_solar_to_grid_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="flow_grid_to_home_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="flow_grid_to_ev_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="flow_grid_to_battery_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="flow_battery_to_home_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="flow_battery_to_ev_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="flow_battery_to_grid_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),

    # ============================================================================
    # PERFORMANCE & EFFICIENCY METRICS
    # ============================================================================
    # System performance indicators and efficiency calculations.
    # These provide insights into system optimization and energy usage patterns.
    # ============================================================================

    SensorEntityDescription(
        key="self_consumption_rate",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
    ),
    # Removed: Redundant (duplicate of self_consumption_rate)
    # self_consumption_rate_daily, grid_self_consumption
    SensorEntityDescription(
        key="autarky_rate",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
    ),
    # Removed: Redundant efficiency sensors (keep self_consumption_rate, autarky_rate)
    # autarky_rate_daily, solar_utilization, solar_efficiency, performance_ratio (hardcoded)
    # power_flow_efficiency, inverter_efficiency, inverter_load_ratio

    # ============================================================================
    # FINANCIAL TRACKING
    # ============================================================================
    # Cost calculations, savings tracking, and financial metrics.
    # 
    # Currency: Dynamically set from Home Assistant configuration
    # ============================================================================

    SensorEntityDescription(
        key="daily_savings",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
    ),
    SensorEntityDescription(
        key="daily_battery_savings",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
    ),
    SensorEntityDescription(
        key="daily_costs",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
    ),
    SensorEntityDescription(
        key="daily_export_revenue",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
    ),
    SensorEntityDescription(
        key="daily_net_cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
    ),
    SensorEntityDescription(
        key="monthly_savings",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
    ),
    SensorEntityDescription(
        key="monthly_battery_savings",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
    ),
    SensorEntityDescription(
        key="monthly_costs",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
    ),
    SensorEntityDescription(
        key="monthly_export_revenue",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
    ),
    SensorEntityDescription(
        key="monthly_net_cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
    ),
    # Removed: battery_discharge_value — duplicate of daily_battery_savings
    SensorEntityDescription(
        key="power_charge_cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
    ),
    # Removed: Debug sensors not needed
    # daily_cost_data_source, monthly_cost_data_source

    # ============================================================================
    # PEAK LOAD MANAGEMENT
    # ============================================================================
    # 15-minute consecutive peak load tracking and demand management.
    # 
    # Hardware Requirements:
    #   - Smart meter with 15-minute interval measurements
    # 
    # Primary use: Demand charge cost optimization
    # ============================================================================

    SensorEntityDescription(
        key="consecutive_peak_15min",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
    ),
    SensorEntityDescription(
        key="monthly_consecutive_peak",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
    ),
    SensorEntityDescription(
        key="current_vs_peak_percentage",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="target_peak_limit",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
    ),
    SensorEntityDescription(
        key="peak_margin",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
    ),
    SensorEntityDescription(
        key="load_management_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="load_management_recommendation",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="loads_currently_shed",
    ),
    SensorEntityDescription(
        key="available_load_reduction",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
    ),
    SensorEntityDescription(
        key="controllable_devices_count",
        state_class=SensorStateClass.MEASUREMENT,
    ),

    # Removed: GRID QUALITY & LOAD BALANCER - Hardware sensors not populated
    # power_factor, grid_frequency, load_balancer_l1, load_balancer_l2, load_balancer_l3, load_balancer_total

    # Removed: SYSTEM DIAGNOSTICS & DATA QUALITY - use HA native diagnostics
    # energy_tracking_mode, energy_data_quality, home_consumption_energy_daily_source
    # home_consumption_energy_monthly_source, energy_balance_check, last_update

    # ============================================================================
    # SURPLUS CONTROLLER (Phase 0)
    # ============================================================================

    SensorEntityDescription(
        key="surplus_total_w",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="surplus_distributable_w",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="surplus_allocated_w",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="surplus_unallocated_w",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="surplus_active_devices",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="surplus_total_devices",
        state_class=SensorStateClass.MEASUREMENT,
    ),

    # ============================================================================
    # SOLAR FORECAST (Phase 0.3)
    # ============================================================================

    SensorEntityDescription(
        key="forecast_today_kwh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="forecast_tomorrow_kwh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="forecast_remaining_today_kwh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    # (#575) forecast_power_now_w restored — the "Forecast vs Actual" dashboard
    # chart is its consumer again (regressed to a no-op in the LitElement
    # migration, then removed as "dead" by #544). forecast_power_next_hour_w
    # stays removed — still an orphan with no consumer.
    SensorEntityDescription(
        key="forecast_power_now_w",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="forecast_peak_power_today_w",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="forecast_peak_time_today",
    ),
    SensorEntityDescription(
        key="best_surplus_window",
    ),
    SensorEntityDescription(
        key="forecast_surplus_kwh",
        # (#646 sweep) no ENERGY device_class — a forecast fluctuates; the
        # energy+MEASUREMENT pairing was invalid (4th sibling, found by the
        # whole-table guard).
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="forecast_dampening_factor",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:tune-vertical-variant",
        suggested_display_precision=3,
    ),
    SensorEntityDescription(
        key="forecast_source",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="charging_recommendation",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),

    # ============================================================================
    # VPP GRID-EVENT DISPATCH (#580)
    # ============================================================================
    SensorEntityDescription(
        key="vpp_event",
        icon="mdi:transmission-tower",
    ),

    # ============================================================================
    # NIGHT WINDOW
    # ============================================================================
    SensorEntityDescription(
        key="night_start_time",
    ),
    SensorEntityDescription(
        key="night_end_time",
    ),
    SensorEntityDescription(
        key="night_window_hours",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="h",
    ),

    # ============================================================================
    # DYNAMIC TARIFF (Phase 1)
    # ============================================================================

    SensorEntityDescription(
        key="tariff_current_import_rate",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="tariff_current_export_rate",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="tariff_price_level",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="tariff_provider",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="tariff_next_cheap_start",
    ),

    # ============================================================================
    # HEAT PUMP (Phase 2)
    # ============================================================================

    SensorEntityDescription(
        key="heat_pump_mode",
    ),
    SensorEntityDescription(
        key="heat_pump_sg_ready_state",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # #432: diagnostic sensor exposing WHY the heat pump is or is not
    # registered. State is one of six strings (registered_sg_ready /
    # registered_climate_only / registered_sg_ready_and_climate /
    # not_configured / partial_sg_ready_only_relay1 /
    # partial_sg_ready_only_relay2). Attributes expose the resolved
    # entity ids + live HA state of each. The whole point is to let
    # users with non-standard wiring (ESP relays / Shellies / Nibe
    # Modbus template switches) self-diagnose remotely.
    SensorEntityDescription(
        key="heat_pump_registration_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # (#769) The heat pump's ledger row — the same four horizons every other
    # consumer already had. On a heat-pump house this is the largest
    # controllable load in the building and until now it had no kWh anywhere:
    # it vanished into the ``home`` residual (#767). ``shifted_today`` is the
    # part SEM caused, split out by SG-Ready state, which is what turns
    # "SG-Ready shifted X kWh" from a claim into a measurement.
    SensorEntityDescription(
        key="heat_pump_energy_today",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="heat_pump_energy_month",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="heat_pump_energy_year",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="heat_pump_energy_total",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="heat_pump_energy_shifted_today",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),

    # ============================================================================
    # PV PERFORMANCE (Phase 5)
    # ============================================================================

    SensorEntityDescription(
        key="pv_daily_specific_yield",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="kWh/kWp",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="pv_performance_vs_forecast",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="pv_estimated_annual_degradation",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="pv_degradation_trend",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),

    # ============================================================================
    # ENERGY ASSISTANT (Phase 6)
    # ============================================================================

    SensorEntityDescription(
        key="energy_optimization_score",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="points",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="energy_tip",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="energy_tip_category",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="energy_ev_solar_percentage",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
    ),

    # ============================================================================
    # CONSUMPTION/SOLAR PREDICTOR (Phase 8, #3)
    # ============================================================================

    SensorEntityDescription(
        key="predictor_training_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="predictor_model_accuracy",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # (#544) predicted_consumption_next_hour / predicted_consumption_today_kwh
    # / predicted_solar_next_hour removed — published, never charted/read.
    SensorEntityDescription(
        key="predicted_surplus_window",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),

    # ============================================================================
    # BATTERY CHARGE SCHEDULER (Phase 9, #6)
    # ============================================================================

    SensorEntityDescription(
        key="battery_scheduler_state",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="battery_scheduler_target_soc",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="battery_scheduler_deficit_kwh",
        # (#646) no ENERGY device_class — a computed deficit fluctuates;
        # the energy+MEASUREMENT pairing was invalid.
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="battery_scheduler_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),

    # ============================================================================
    # EV SESSION TRACKING
    # ============================================================================

    SensorEntityDescription(
        key="session_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="session_solar_share",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="session_cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
    ),
    SensorEntityDescription(
        key="session_duration",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="min",
    ),

    # ============================================================================
    # BATTERY SESSION TRACKING
    # ============================================================================

    SensorEntityDescription(
        key="battery_session_type",
    ),
    SensorEntityDescription(
        key="battery_session_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="battery_session_solar_share",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="battery_session_cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
    ),
    SensorEntityDescription(
        key="battery_session_savings",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
    ),
    SensorEntityDescription(
        key="battery_session_duration",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="min",
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="battery_session_avg_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),

    # ============================================================================
    # LIFETIME EV STATISTICS
    # ============================================================================

    SensorEntityDescription(
        key="lifetime_ev_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="lifetime_ev_solar",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="lifetime_ev_cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CHF",
    ),
    SensorEntityDescription(
        key="lifetime_ev_sessions",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="lifetime_ev_solar_share",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
    ),
    # (#793) the other two thirds of the split — battery-sourced kWh were in
    # the solar-share denominator but visible nowhere, so "not solar" and
    # "charged for" looked like the same number when they were two.
    SensorEntityDescription(
        key="lifetime_ev_battery_share",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="lifetime_ev_grid_share",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="vehicle_soc",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
    ),
    # Estimated driving range (#245): from a real range entity if configured,
    # else derived from vehicle SOC × capacity ÷ consumption (ev_kwh_per_100km).
    SensorEntityDescription(
        key="ev_remaining_range",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=0,
        icon="mdi:map-marker-distance",
    ),

    # ============================================================================
    # EV INTELLIGENCE (#106)
    # ============================================================================

    SensorEntityDescription(
        key="ev_taper_trend",
    ),
    # (#544) Dead fleet EV-intelligence sensors removed — written but read
    # by no card / generator / decision: ev_taper_ratio,
    # ev_taper_minutes_to_full, ev_estimated_soc, ev_last_full_charge,
    # ev_energy_since_full, ev_predicted_daily_consumption,
    # ev_battery_health. (ev_taper_trend kept — it's a DIAGNOSTIC_SENSOR.)
    # Multi-charger (#112)
    SensorEntityDescription(
        key="ev_charger_count",
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="diag_charger_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
    ),

    # Diagnostics (System tab)
    SensorEntityDescription(
        key="diag_version",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="diag_grid_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="diag_grid_sign",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="diag_battery_sign",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # #590 — diag_grid_sign_contradiction / diag_battery_sign_contradiction
    # retired into the one perception health surface (binary_sensor.sem_layer_
    # _mismatch, tagged perception:<signal>) + the diagnose cross_checks dump.
    SensorEntityDescription(
        key="diag_charger_control",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="diag_battery_capacity",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="diag_update_interval",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="diag_observer_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # Diagnostics for the independent grid and inverter/Load lanes plus the
    # active gate state. Disabled by default — only meaningful once configured.
    SensorEntityDescription(
        key="diag_phase_guard_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="diag_phase_guard_safe",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="diag_phase_guard_data_fresh",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="diag_phase_guard_stop_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    _phase_guard_current_description(key="diag_grid_l1_current_a"),
    _phase_guard_current_description(key="diag_grid_l1_margin_a"),
    _phase_guard_current_description(key="diag_grid_l2_current_a"),
    _phase_guard_current_description(key="diag_grid_l2_margin_a"),
    _phase_guard_current_description(key="diag_grid_l3_current_a"),
    _phase_guard_current_description(key="diag_grid_l3_margin_a"),
    _phase_guard_current_description(key="diag_inverter_l1_current_a"),
    _phase_guard_current_description(key="diag_inverter_l1_margin_a"),
    _phase_guard_current_description(key="diag_inverter_l2_current_a"),
    _phase_guard_current_description(key="diag_inverter_l2_margin_a"),
    _phase_guard_current_description(key="diag_inverter_l3_current_a"),
    _phase_guard_current_description(key="diag_inverter_l3_margin_a"),
    # diag_ev_assist_headroom removed — observe-only instrumentation for #545
    # (the Zone-4 chicken-and-egg), now fixed + closed.
    SensorEntityDescription(
        key="diag_sensors_unavailable",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="diag_ed_config",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
]



def _ensure_labels_registered(hass: HomeAssistant) -> None:
    """Create SEM's labels in HA's label registry (#670).

    ``async_update_entity(labels=...)`` stores label **IDs** verbatim: it does
    not validate them and it does not create them. SEM never touched the label
    registry, so for years it wrote ids HA had never heard of — the forward
    lookup worked (``labels(entity)`` returned them) while every reverse lookup
    returned nothing. ``label_entities('sem_monthly')`` -> 0, which is the
    entire point of the feature and everything the HA UI's label filter uses.

    That silence is also why the #667 drift went unnoticed for so long: with
    the registry side missing, a correct label and a typo'd one behaved
    identically.

    ``label_id`` is ``slugify(name)``, so creating a label *named* ``sem_daily``
    yields exactly the id ``SENSOR_LABEL_MAPPING`` already uses — no mapping
    layer. Create-only: an id that already exists is left completely alone, so
    a user who renamed or recoloured a SEM label keeps their change, and their
    own labels are never touched.

    Labels are cosmetic: nothing here may break sensor setup. The whole pass
    is wrapped, not just the write — reading an *unloaded* registry raises too
    (``AttributeError: no attribute '_label_data'``), which took the entire
    sensor platform down with it before this guard.
    """
    try:
        label_registry = lr.async_get(hass)
    except Exception as err:  # pragma: no cover - defensive
        _LOGGER.debug("Label registry unavailable — skipping registration: %s", err)
        return

    for label_id, description in SEM_LABELS.items():
        try:
            if label_registry.async_get_label(label_id) is not None:
                continue
            label_registry.async_create(name=label_id, description=description)
        except ValueError:
            # A label of that *name* exists under a different id — only
            # reachable if a user renamed one of their own labels to ours.
            # Theirs wins; we do not rename or delete user labels.
            _LOGGER.debug("Label name %s already in use — not creating", label_id)
        except Exception as err:
            _LOGGER.debug("Could not register label %s: %s", label_id, err)
            return


async def _apply_labels_to_sensors(hass: HomeAssistant, sensors) -> None:
    """Apply labels to SEM sensors for dynamic dashboard support."""
    # Must come first: applying an id that does not exist in the label
    # registry is accepted without complaint and resolves to nothing (#670).
    _ensure_labels_registered(hass)

    entity_registry = er.async_get(hass)

    for sensor in sensors:
        # Get labels for this sensor key
        sensor_key = sensor.entity_description.key
        labels = SENSOR_LABEL_MAPPING.get(sensor_key, set()).copy()

        if labels:
            try:
                # Update entity with labels
                entity_registry.async_update_entity(
                    sensor.entity_id,
                    labels=labels
                )
                _LOGGER.debug(
                    "Applied labels %s to sensor %s",
                    labels,
                    sensor.entity_id
                )
            except Exception as e:
                _LOGGER.warning(
                    "Failed to apply labels to sensor %s: %s",
                    sensor.entity_id,
                    e
                )


def _fix_entity_ids(
    hass: HomeAssistant,
    entry: ConfigEntry,
    descriptions: list,
    platform: str,
) -> None:
    """Fix entity_ids from pre-translation installs.

    When translations were missing, HA generated wrong entity_ids
    (e.g. sensor.sem instead of sensor.sem_forecast_peak_time_today).
    This finds entities by unique_id and renames them to the correct
    entity_id based on the description key.
    """
    try:
        registry = er.async_get(hass)
        # Build unique_id → expected entity_id map
        expected = {}
        for desc in descriptions:
            uid = f"sem_{desc.key}"
            expected_eid = f"{platform}.sem_{desc.key}"
            expected[uid] = expected_eid

        for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
            if entity_entry.domain != platform:
                continue
            uid = entity_entry.unique_id or ""
            if uid in expected:
                correct_eid = expected[uid]
                if entity_entry.entity_id != correct_eid:
                    # Check if the correct entity_id is available
                    existing = registry.async_get(correct_eid)
                    if existing is None:
                        registry.async_update_entity(
                            entity_entry.entity_id,
                            new_entity_id=correct_eid,
                        )
                        _LOGGER.info(
                            "Fixed entity_id: %s → %s (translation was missing at creation)",
                            entity_entry.entity_id, correct_eid,
                        )
    except Exception as e:
        _LOGGER.debug("Entity ID fix skipped: %s", e)


def _cleanup_stale_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    descriptions: list,
    platform: str,
) -> None:
    """Remove orphaned entities from previous SEM versions.

    Compares registered entities against current entity descriptions
    and removes any that no longer exist in the code.
    """
    try:
        registry = er.async_get(hass)
        valid_keys = {d.key for d in descriptions}

        stale = []
        for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
            if entity_entry.domain != platform:
                continue
            # SEM uses two unique_id formats:
            #   sensors: "sem_{key}"
            #   numbers/switches: "{entry_id}_{key}"
            unique_id = entity_entry.unique_id or ""
            key = None
            if unique_id.startswith("sem_"):
                key = unique_id[4:]  # Strip "sem_" prefix
            elif unique_id.startswith(f"{entry.entry_id}_"):
                key = unique_id[len(entry.entry_id) + 1:]  # Strip entry_id prefix
            if key and key not in valid_keys:
                stale.append((entity_entry, key))

        for entity_entry, key in stale:
            _LOGGER.info(
                "Removing stale entity %s (key '%s' no longer exists)",
                entity_entry.entity_id, key,
            )
            registry.async_remove(entity_entry.entity_id)
    except Exception as e:
        _LOGGER.debug("Stale entity cleanup skipped: %s", e)


async def async_setup_entry(
    hass: HomeAssistant, entry: SEMConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up SEM Solar Energy Management sensors."""
    _LOGGER.info("Setting up SEM sensors for entry %s", entry.entry_id)

    coordinator: SEMCoordinator = entry.runtime_data
    _LOGGER.info("Got coordinator, creating %d sensors", len(SENSOR_TYPES))

    sensors = [
        SEMSolarSensor(coordinator, description, entry.entry_id)
        for description in SENSOR_TYPES
    ]

    # Per-charger sensors (#131): create power + session sensors for each configured charger
    full_config = {**entry.data, **entry.options}
    ev_chargers = full_config.get("ev_chargers", [])
    _LOGGER.info("Per-charger setup: %d charger(s) in config", len(ev_chargers))
    per_charger_descriptions = []
    for charger_cfg in ev_chargers:
        cid = charger_cfg.get("id", "ev_charger")
        cname = charger_cfg.get("name", "EV Charger")
        per_charger_descriptions.extend([
            SensorEntityDescription(
                key=f"charger_{cid}_power",
                name=f"{cname} Power",
                device_class=SensorDeviceClass.POWER,
                state_class=SensorStateClass.MEASUREMENT,
                native_unit_of_measurement=UnitOfPower.WATT,
                suggested_display_precision=0,
            ),
            # Per-charger commanded current (#291): SEM's own authoritative
            # ``_current_setpoint`` — what SEM ASKED the charger to do, in amps.
            # Diagnostic counterweight to the upstream
            # ``sensor.keba_p30_max_current`` (and analogous KEBA/Wallbox/Easee
            # sensors) which can read stale after SEM sends ``set_current`` —
            # see #291 for the 2026-05-29 PROD observation. Trust this sensor
            # when you want "what is SEM trying to do"; trust the upstream
            # sensor for "what does the charger think it can do."
            SensorEntityDescription(
                key=f"charger_{cid}_commanded_current",
                name=f"{cname} Commanded Current",
                device_class=SensorDeviceClass.CURRENT,
                state_class=SensorStateClass.MEASUREMENT,
                native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
                suggested_display_precision=1,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
            SensorEntityDescription(
                key=f"charger_{cid}_session_energy",
                name=f"{cname} Session Energy",
                device_class=SensorDeviceClass.ENERGY,
                state_class=SensorStateClass.TOTAL,
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                suggested_display_precision=2,
            ),
            # #135: pass-through of the charger's own ``ev_session_energy_sensor``
            # value (e.g. KEBA's ``sensor.keba_p30_session_energy`` reading
            # 14.61 kWh across a multi-day session). SEM's ``session_energy``
            # above is an INTERNAL integration that resets on coordinator
            # reload and may differ from the charger's own counter — load-
            # bearing for solar-share / cost calculations, NOT a pass-through.
            # This new ``_external`` sensor surfaces the charger's truth
            # alongside it so users (and the dashboard) can compare. Falls
            # back to 0 when the configured sensor is unavailable / missing.
            SensorEntityDescription(
                key=f"charger_{cid}_session_energy_external",
                name=f"{cname} Session Energy (charger)",
                device_class=SensorDeviceClass.ENERGY,
                state_class=SensorStateClass.TOTAL,
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                suggested_display_precision=2,
            ),
            SensorEntityDescription(
                key=f"charger_{cid}_session_solar_share",
                name=f"{cname} Solar Share",
                native_unit_of_measurement=PERCENTAGE,
                suggested_display_precision=0,
            ),
            SensorEntityDescription(
                key=f"charger_{cid}_taper_trend",
                name=f"{cname} Taper Trend",
            ),
            SensorEntityDescription(
                key=f"charger_{cid}_taper_ratio",
                name=f"{cname} Taper Ratio",
                native_unit_of_measurement=PERCENTAGE,
                suggested_display_precision=0,
            ),
            # Per-charger daily energy (#193)
            SensorEntityDescription(
                key=f"charger_{cid}_daily_energy",
                name=f"{cname} Daily Energy",
                device_class=SensorDeviceClass.ENERGY,
                state_class=SensorStateClass.TOTAL_INCREASING,
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                suggested_display_precision=2,
            ),
            # Per-charger intelligence sensors (#193)
            SensorEntityDescription(
                key=f"charger_{cid}_estimated_soc",
                name=f"{cname} Estimated SOC",
                device_class=SensorDeviceClass.BATTERY,
                state_class=SensorStateClass.MEASUREMENT,
                native_unit_of_measurement=PERCENTAGE,
                suggested_display_precision=0,
            ),
            # #383: real per-charger vehicle SOC. Populated from the
            # charger's ``vehicle_soc_entity`` config; ``None`` /
            # unavailable when not configured. Multi-charger cards
            # used to mirror each other's SOC because the global
            # ``sem_vehicle_soc`` got context-swap clobbered across
            # the per-charger update loop; this sensor exposes the
            # correct per-charger value so the card stops needing
            # the global fallback.
            SensorEntityDescription(
                key=f"charger_{cid}_vehicle_soc",
                name=f"{cname} Vehicle SOC",
                device_class=SensorDeviceClass.BATTERY,
                state_class=SensorStateClass.MEASUREMENT,
                native_unit_of_measurement=PERCENTAGE,
                suggested_display_precision=0,
            ),
            # (#440) per-charger _nights_until_charge and _charge_needed
            # were removed alongside the global versions — see comment
            # in the main SENSOR_TYPES block.
            SensorEntityDescription(
                key=f"charger_{cid}_taper_minutes_to_full",
                name=f"{cname} Minutes to Full",
                native_unit_of_measurement=UnitOfTime.MINUTES,
                suggested_display_precision=0,
            ),
        ])

    # v1.6.15: per-charger flow attribution sensors. Gated on
    # ``len(ev_chargers) > 1`` — for single-charger setups the fleet
    # ``sensor.sem_flow_*_to_ev_*`` entities are authoritative (each
    # fleet sensor IS the single charger's flow) and adding duplicates
    # would just clutter the entity registry. The dashboard generator's
    # Sankey card per-charger split (also v1.6.15) reads these entities.
    if len(ev_chargers) > 1:
        for charger_cfg in ev_chargers:
            cid = charger_cfg.get("id", "ev_charger")
            cname = charger_cfg.get("name", "EV Charger")
            per_charger_descriptions.extend([
                SensorEntityDescription(
                    key=f"charger_{cid}_flow_solar_to_ev_power",
                    name=f"{cname} Solar → EV Power",
                    device_class=SensorDeviceClass.POWER,
                    state_class=SensorStateClass.MEASUREMENT,
                    native_unit_of_measurement=UnitOfPower.WATT,
                    suggested_display_precision=0,
                ),
                SensorEntityDescription(
                    key=f"charger_{cid}_flow_grid_to_ev_power",
                    name=f"{cname} Grid → EV Power",
                    device_class=SensorDeviceClass.POWER,
                    state_class=SensorStateClass.MEASUREMENT,
                    native_unit_of_measurement=UnitOfPower.WATT,
                    suggested_display_precision=0,
                ),
                SensorEntityDescription(
                    key=f"charger_{cid}_flow_battery_to_ev_power",
                    name=f"{cname} Battery → EV Power",
                    device_class=SensorDeviceClass.POWER,
                    state_class=SensorStateClass.MEASUREMENT,
                    native_unit_of_measurement=UnitOfPower.WATT,
                    suggested_display_precision=0,
                ),
                # Energy counters — integrated by ``FlowCalculator.integrate_energy_flows``
                # daily-resetting, surfaced as TOTAL so HA Energy
                # dashboard can use them in the EV-source breakdown.
                SensorEntityDescription(
                    key=f"charger_{cid}_flow_solar_to_ev_energy",
                    name=f"{cname} Solar → EV Energy",
                    device_class=SensorDeviceClass.ENERGY,
                    state_class=SensorStateClass.TOTAL,
                    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                    suggested_display_precision=2,
                ),
                SensorEntityDescription(
                    key=f"charger_{cid}_flow_grid_to_ev_energy",
                    name=f"{cname} Grid → EV Energy",
                    device_class=SensorDeviceClass.ENERGY,
                    state_class=SensorStateClass.TOTAL,
                    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                    suggested_display_precision=2,
                ),
                SensorEntityDescription(
                    key=f"charger_{cid}_flow_battery_to_ev_energy",
                    name=f"{cname} Battery → EV Energy",
                    device_class=SensorDeviceClass.ENERGY,
                    state_class=SensorStateClass.TOTAL,
                    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                    suggested_display_precision=2,
                ),
            ])

    for desc in per_charger_descriptions:
        sensors.append(SEMSolarSensor(coordinator, desc, entry.entry_id))

    if per_charger_descriptions:
        _LOGGER.info("Created %d per-charger sensors for %d charger(s)",
                      len(per_charger_descriptions), len(ev_chargers))

    # v1.7.0 / #312: per-PV-string sensor surface. Auto-discovered at
    # config-flow time (``hardware_detection.discover_pv_strings_from_registry``)
    # and stashed on the coordinator's sensor reader via
    # ``set_pv_strings``. Gated on ≥ 2 strings to keep single-string
    # installs identical to today (no entity-registry clutter).
    #
    # Defensive getattr on the coordinator's reader handle — keeps test
    # mocks (``MagicMock``-only coordinators in ``test_integration.py``)
    # working when the reader isn't wired through.
    per_string_descriptions = []
    _sr = getattr(coordinator, "_sensor_reader", None)
    pv_strings = getattr(_sr, "_pv_strings", {}) if _sr is not None else {}
    pv_strings = pv_strings or {}
    if len(pv_strings) >= 2:
        # (#566) user-chosen names from options — a custom name replaces the
        # verbose default in the ENTITY name (so it shows in HA history / the
        # Energy Dashboard). The compact chip label lives in the string_name
        # attribute (see SEMSolarSensor.extra_state_attributes). Unnamed slots
        # keep "PV String N" so existing installs are unchanged.
        _pv_names = getattr(_sr, "_pv_string_names", {}) if _sr is not None else {}
        for slot in sorted(pv_strings.keys()):
            # ``slot`` is the normalised label ``pv1`` / ``pv2`` / ...
            n = slot.replace("pv", "")
            base = _pv_names.get(slot) or f"PV String {n}"
            per_string_descriptions.extend([
                SensorEntityDescription(
                    key=f"pv_string_{slot}_power",
                    name=f"{base} Power",
                    device_class=SensorDeviceClass.POWER,
                    state_class=SensorStateClass.MEASUREMENT,
                    native_unit_of_measurement=UnitOfPower.WATT,
                    suggested_display_precision=0,
                ),
                SensorEntityDescription(
                    key=f"pv_string_{slot}_daily_energy",
                    name=f"{base} Daily Energy",
                    device_class=SensorDeviceClass.ENERGY,
                    state_class=SensorStateClass.TOTAL,
                    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                    suggested_display_precision=2,
                ),
            ])
        for desc in per_string_descriptions:
            sensors.append(SEMSolarSensor(coordinator, desc, entry.entry_id))
        _LOGGER.info(
            "Created %d per-PV-string sensors for %d string(s) (#312)",
            len(per_string_descriptions), len(pv_strings),
        )

    # Phase A of per-battery card mirror — auto-discover the multi-
    # battery surface from the coordinator's sensor reader (single-
    # battery installs leave ``battery_power_list`` at length 1 and
    # produce zero per-battery sensors, preserving today's fleet-
    # sensor behaviour). Same gating + getattr pattern as per-PV-
    # string surface above.
    per_battery_descriptions = []
    _ed = getattr(_sr, "_energy_dashboard_config", None) if _sr is not None else None
    batt_list = list(getattr(_ed, "battery_power_list", []) or []) if _ed is not None else []
    if len(batt_list) > 1:
        for idx in range(len(batt_list)):
            bid = f"b{idx + 1}"
            # Names are positional ("Battery b1 Power"), NOT derived from the
            # source entity. An earlier comment here described a
            # "Battery b1 — battery_1_lade_entladeleistung" form and computed
            # the label for it, but no description ever used the value; the
            # battery card supplies the readable name via ``friendly_name``.
            per_battery_descriptions.extend([
                SensorEntityDescription(
                    key=f"battery_{bid}_power",
                    name=f"Battery {bid} Power",
                    device_class=SensorDeviceClass.POWER,
                    state_class=SensorStateClass.MEASUREMENT,
                    native_unit_of_measurement=UnitOfPower.WATT,
                    suggested_display_precision=0,
                ),
                SensorEntityDescription(
                    key=f"battery_{bid}_soc",
                    name=f"Battery {bid} SOC",
                    device_class=SensorDeviceClass.BATTERY,
                    state_class=SensorStateClass.MEASUREMENT,
                    native_unit_of_measurement=PERCENTAGE,
                    suggested_display_precision=0,
                ),
                SensorEntityDescription(
                    key=f"battery_{bid}_status",
                    name=f"Battery {bid} Status",
                    # No device_class — values are localised strings
                    # ("charging" / "discharging" / "idle"); same shape
                    # as the existing fleet ``battery_status``.
                ),
                SensorEntityDescription(
                    key=f"battery_{bid}_capacity_kwh",
                    name=f"Battery {bid} Capacity",
                    device_class=SensorDeviceClass.ENERGY_STORAGE,
                    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                    suggested_display_precision=1,
                ),
            ])
        for desc in per_battery_descriptions:
            sensors.append(SEMSolarSensor(coordinator, desc, entry.entry_id))
        _LOGGER.info(
            "Created %d per-battery sensors for %d batter%s (Phase A)",
            len(per_battery_descriptions), len(batt_list),
            "y" if len(batt_list) == 1 else "ies",
        )

    _LOGGER.info("Adding %d sensors to Home Assistant", len(sensors))
    async_add_entities(sensors)

    # Fix entity_ids from pre-translation installs and clean up stale entities
    all_descriptions = (
        list(SENSOR_TYPES)
        + per_charger_descriptions
        + per_string_descriptions
        + per_battery_descriptions
    )
    _fix_entity_ids(hass, entry, all_descriptions, "sensor")
    _cleanup_stale_entities(hass, entry, all_descriptions, "sensor")

    # Apply labels to entities after they are created
    await _apply_labels_to_sensors(hass, sensors)


class SEMSolarSensor(CoordinatorEntity, RestoreSensor):
    """SEM Solar Energy Management sensor with state persistence."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    # #581 — recorder impact. Large UI-helper attributes (device maps, plan
    # rows, hourly curves, peak history) exist purely to feed the live
    # Lovelace cards; they have no historical/charting value but are
    # re-serialised on every 10 s coordinator cycle. Recorded, they dominate
    # the ``state_attributes`` table (the reporter measured 4.4 GB total, with
    # the ``devices`` map on ``controllable_devices_count`` alone at ~9 KiB per
    # write → 816 MiB in 10 days). ``_unrecorded_attributes`` keeps them on the
    # live state (cards still read them) while excluding them from the recorder.
    _unrecorded_attributes = frozenset({
        "devices",
        "device_list",
        "per_charger_states",
        "per_charger_plans",
        "today_plan",
        "upcoming",
        "schedule_today",
        "schedule_surplus_hours",
        "schedule_ev_hours",
        "energy_dashboard",
        "schedule",
        # (#657) ``top_5_peaks`` / ``top_5_peaks_formatted`` were dropped —
        # they were built from a coordinator key no producer ever wrote, so
        # neither attribute ever reached a state to be recorded.
        # #580 — VPP event history (UI/accounting helper, no charting value)
        "events",
        "last_event",
        # (#699) atomic balance snapshot for the cards — every value is
        # already recorded via its own sensor; recording the bundle again
        # would double the write volume for zero charting value.
        "power_snapshot",
    })

    # Sensors disabled by default (not used by dashboard template)
    DISABLED_BY_DEFAULT: set = set()

    # Diagnostic sensors (system status, not primary measurements)
    DIAGNOSTIC_SENSORS = {
        "charging_state", "grid_status", "solar_charging_status",
        "night_charging_status", "battery_priority_status",
        "charging_strategy", "battery_status",
        "load_management_status", "load_management_recommendation",
        "loads_currently_shed", "controllable_devices_count",
        "forecast_source", "charging_recommendation",
        "tariff_price_level", "tariff_provider", "tariff_next_cheap_start",
        "heat_pump_mode", "heat_pump_sg_ready_state", "heat_pump_registration_status",
        "pv_degradation_trend", "energy_tip", "energy_tip_category",
        "ev_taper_trend",
    }

    def __init__(
        self,
        coordinator: SEMCoordinator,
        description: SensorEntityDescription,
        entry_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description

        self._attr_unique_id = f"sem_{description.key}"
        self._attr_translation_key = description.key
        self._attr_device_info = coordinator.device_info
        self._attr_suggested_object_id = f"sem_{description.key}"
        # Force stable entity ID regardless of HA language
        self.entity_id = f"sensor.sem_{description.key}"

        # Start unavailable — only become available after first coordinator update (#70)
        # Prevents zero-value spikes in history/energy dashboard during HA restart
        self._attr_available = False
        self._attr_native_value = None

        # #289 — ``sem_ev_power`` lagged the upstream KEBA charging-power
        # sensor by up to ~5 kW for several seconds because the coordinator
        # only re-reads on its 10 s cycle. For the EV-power sensor
        # specifically we ALSO subscribe to upstream state changes so the
        # published value matches reality within one HA dispatch instead
        # of one coordinator cycle. The energy balance
        # (``home_consumption_power``) stays on cycle granularity and
        # corrects itself the next tick — already self-healing.
        self._unsub_ev_power_track = None

        # Use HA configured currency for monetary sensors (instead of hardcoded CHF)
        if description.device_class == SensorDeviceClass.MONETARY:
            self._attr_native_unit_of_measurement = coordinator.hass.config.currency

        # Entity category
        if description.key in self.DIAGNOSTIC_SENSORS:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Disabled by default
        if description.key in self.DISABLED_BY_DEFAULT:
            self._attr_entity_registry_enabled_default = False

        # Set initial value from coordinator if available
        if coordinator.data:
            self._update_from_coordinator()

        # Set dynamic currency for cost sensors
        if description.key in ["daily_savings", "monthly_savings", "daily_costs", "monthly_costs",
                               "monthly_power_cost", "load_balancing_savings_potential",
                               "daily_battery_savings", "monthly_battery_savings",
                               "battery_discharge_value",
                               # (#770) what today's grid-charging cost
                               "daily_battery_grid_cost"]:
            self._attr_native_unit_of_measurement = coordinator.hass.config.currency

    async def async_added_to_hass(self) -> None:
        """Register callbacks and restore state when entity is added to hass."""
        await super().async_added_to_hass()

        # Restore state for accumulating sensors (TOTAL state class)
        if self.entity_description.state_class == SensorStateClass.TOTAL:
            # Use RestoreSensor's async_get_last_sensor_data (returns native_value)
            if (last_sensor_data := await self.async_get_last_sensor_data()) is not None:
                try:
                    # Get the native value directly (not the formatted state string)
                    restored_value = last_sensor_data.native_value

                    if restored_value is not None:
                        # Check if restored state is from same energy day (07:00 offset)
                        from homeassistant.util import dt as dt_util
                        now = dt_util.now()
                        energy_day_start = now.replace(hour=7, minute=0, second=0, microsecond=0)
                        if now.hour < 7:
                            energy_day_start -= timedelta(days=1)

                        # Get last_changed from extra_data or use current time as fallback
                        # Note: SensorExtraStoredData doesn't store last_changed, so we restore unconditionally
                        # This is safe because daily reset in coordinator will handle stale data
                        self._attr_native_value = float(restored_value)
                        self._attr_native_unit_of_measurement = last_sensor_data.native_unit_of_measurement
                        _LOGGER.info(
                            f"Restored {self.entity_description.key} to {restored_value} "
                            f"with unit {last_sensor_data.native_unit_of_measurement}"
                        )
                except (ValueError, TypeError) as e:
                    _LOGGER.warning(
                        f"Failed to restore state for {self.entity_description.key}: {e}"
                    )

        # #289 — wire the sub-cycle EV-power passthrough for the one
        # sensor that observably benefits (the dashboard reads it at
        # 1 s resolution; everything else is happy on the 10 s
        # coordinator cycle). Resolved here rather than in __init__
        # because the upstream entity IDs come from the coordinator's
        # config, which is fully populated by the time the entity is
        # added to hass.
        if self.entity_description.key == "ev_power":
            self._subscribe_ev_power_upstreams()

    @callback
    def _subscribe_ev_power_upstreams(self) -> None:
        """Subscribe to every upstream entity that feeds sem_ev_power.

        Resolution mirrors ``SensorReader._read_ev_power``:
          * multi-charger (``ev_chargers`` config has 2+ entries):
            sum of each charger's ``ev_charging_power_sensor``
          * single-charger / legacy: ``ev_power_sensor`` /
            ``ev_charging_power_sensor`` from the top-level config

        When any tracked upstream changes, re-sum from
        ``hass.states.get()`` (stateless, matches SensorReader exactly)
        and push the new value to ``sem_ev_power`` immediately.
        """
        config = self.coordinator.config or {}
        ev_chargers = config.get("ev_chargers") or []

        entity_ids: list[str] = []
        if len(ev_chargers) > 1:
            for ch in ev_chargers:
                cps = ch.get("ev_charging_power_sensor")
                if cps:
                    entity_ids.append(cps)
        else:
            # Single-charger / legacy: prefer the top-level sensor;
            # fall back to the per-charger entry if that's where the
            # config flow stored it.
            single = (
                config.get("ev_power_sensor")
                or config.get("ev_charging_power_sensor")
            )
            if not single and ev_chargers:
                single = ev_chargers[0].get("ev_charging_power_sensor")
            if single:
                entity_ids.append(single)

        if not entity_ids:
            # No upstream wired (config wizard skipped EV power, or
            # configured an Energy Dashboard derivation only). Cycle-
            # granularity is the best we can do; nothing to subscribe.
            return

        # Cache the resolved set so the callback re-sums from the same
        # entities (stateless re-read; matches SensorReader).
        self._ev_power_upstream_entities = list(entity_ids)
        self._unsub_ev_power_track = async_track_state_change_event(
            self.hass, entity_ids, self._handle_ev_power_change,
        )
        _LOGGER.debug(
            "#289 sem_ev_power tracking %d upstream(s): %s",
            len(entity_ids), entity_ids,
        )

    @callback
    def _handle_ev_power_change(self, event) -> None:
        """Re-sum upstream EV power on any tracked entity change."""
        total = 0.0
        any_valid = False
        for eid in self._ev_power_upstream_entities:
            st = self.hass.states.get(eid)
            if st is None or st.state in ("unavailable", "unknown", None):
                continue
            try:
                total += float(st.state)
                any_valid = True
            except (ValueError, TypeError):
                # Upstream momentarily unparseable — skip; the coordinator
                # cycle will re-read on its own cadence either way.
                continue

        if not any_valid:
            # Don't flip to None mid-session over a transient
            # upstream-unavailable blip; coordinator will reconcile.
            return

        self._attr_native_value = round(total, 0)
        self._attr_available = True
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Remove callbacks when entity is removed from hass."""
        await super().async_will_remove_from_hass()
        # CoordinatorEntity already handles coordinator callbacks, no need to remove extra ones
        # #289 — clean up the EV-power upstream subscription.
        if self._unsub_ev_power_track is not None:
            self._unsub_ev_power_track()
            self._unsub_ev_power_track = None

    def _update_from_coordinator(self) -> None:
        """Update entity state from coordinator data."""
        if not self.coordinator.data:
            self._attr_available = False
            self._attr_native_value = None
            return

        key = self.entity_description.key

        # Map sensor keys to coordinator data keys (only for keys that differ)
        # Most keys now match directly since the new coordinator provides them as-is
        key_mapping = {
            # These keys are now provided directly by the coordinator with the same name
            # No mapping needed - just use the key as-is
        }

        data_key = key_mapping.get(key, key)

        # Check if data key exists in coordinator data
        if data_key in self.coordinator.data:
            self._attr_available = True  # Data received — sensor is available (#70)
            value = self.coordinator.data[data_key]

            # Special handling for charging state
            if self.entity_description.key == "charging_state":
                value = self._format_charging_state(value)

            # (#638) The energy plan's STATE is a verdict key, never the
            # plan dict itself — a dict here would stringify into a >255-char
            # state and get rejected. The plan rides as attributes below.
            elif self.entity_description.key == "energy_plan":
                value = _energy_plan_state(value)

            # Special handling for battery status
            elif self.entity_description.key == "battery_status":
                battery_status_map = {
                    "idle": "Idle",
                    "charging": "Charging",
                    "discharging": "Discharging",
                    "full": "Full",
                    "standby": "Standby"
                }
                value = battery_status_map.get(value, value.capitalize() if isinstance(value, str) else value)

            # Special handling for grid status
            elif self.entity_description.key == "grid_status":
                grid_status_map = {
                    "import": "Importing",
                    "export": "Exporting",
                    "idle": "Idle",
                    "offline": "Offline"
                }
                value = grid_status_map.get(value, value.capitalize() if isinstance(value, str) else value)

            # Calculate self-consumption if not provided
            elif self.entity_description.key == "self_consumption_rate" and value is None:
                solar = self.coordinator.data.get("solar_production_total", 0)
                grid_export = max(0, -self.coordinator.data.get("grid_power", 0))
                if solar > 0:
                    value = round((solar - grid_export) / solar * 100, 1)
                else:
                    value = 0

            # Convert ISO timestamp strings to datetime for TIMESTAMP sensors
            if (isinstance(value, str)
                    and self.entity_description.device_class == SensorDeviceClass.TIMESTAMP):
                try:
                    value = datetime.fromisoformat(value)
                except (ValueError, TypeError):
                    value = None

            # Convert string numbers to float/int for numeric sensors
            elif isinstance(value, str):
                if value.replace('.', '').replace('-', '').isdigit():
                    try:
                        value = float(value) if '.' in value else int(value)
                    except (ValueError, TypeError):
                        pass  # Keep as string if conversion fails
                else:
                    # For non-numeric strings on numeric sensors, treat as invalid
                    if (self.entity_description.device_class in [
                        SensorDeviceClass.POWER, SensorDeviceClass.ENERGY,
                        SensorDeviceClass.MONETARY, SensorDeviceClass.BATTERY
                    ]):
                        value = None

            # Set values and mark as available (but unavailable if value is None)
            # Exception: timestamp sensors (e.g. ev_last_full_charge) are available
            # even when None — "no event yet" is a valid state, not unavailable.
            self._attr_native_value = value
            if self.entity_description.device_class == SensorDeviceClass.TIMESTAMP:
                self._attr_available = True
            else:
                self._attr_available = value is not None
        else:
            # Data key not found - mark as unavailable
            self._attr_available = False
            self._attr_native_value = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_from_coordinator()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        if not self.coordinator.data:
            return {}

        # Base attributes.
        #
        # #581 — ``last_update`` was stamped with ``dt_util.now()`` on every
        # coordinator cycle (coordinator.py) and copied onto ALL ~177 SEM
        # entities. Because HA fires ``state_changed`` whenever the state OR any
        # attribute changes, this volatile timestamp forced a recorder write for
        # every SEM entity every 10 s — even sensors whose real value never
        # changed (e.g. ``yearly_co2_avoided``). That drove ~70% of all
        # ``states`` rows in the reporter's DB (15.7 M rows / 1.9 GB). It was
        # never consumed by any dashboard card, and the diagnostics service
        # reads ``last_update``/``delta_triggered`` from ``coordinator.data``
        # directly (not from entity attributes), so dropping them here has no
        # user-visible effect. ``delta_triggered`` was additionally never even
        # populated in coordinator data (always ``None``). Sensors that carry
        # their own genuinely-changing attributes still record normally; static
        # sensors now stop churning the recorder.
        attrs: Dict[str, Any] = {}

        # Add specific attributes based on sensor type
        if self.entity_description.key == "charging_state":
            # #351 M4 — per-charger effective state map. Makes the
            # disagreement visible: fleet ``charging_state`` may be
            # NIGHT_CHARGING_ACTIVE even when a specific charger's
            # ``charge_mode`` is solar_only (effective state SOLAR_IDLE).
            # Built from the ``charger_<id>_charging_state`` result keys
            # that the coordinator's per-charger loop emits.
            _per_charger_states = {}
            for k, v in self.coordinator.data.items():
                if k.startswith("charger_") and k.endswith("_charging_state"):
                    cid = k[len("charger_"):-len("_charging_state")]
                    _per_charger_states[cid] = v
            # #464 — per-charger plan rows. Same shape as ``today_plan``
            # below; the EV card's per-charger plan strip reads its own
            # charger's plan here (falling back to the fleet plan), so two
            # chargers with different targets/deadlines no longer show an
            # identical strip.
            _per_charger_plans = {}
            for k, v in self.coordinator.data.items():
                if k.startswith("charger_") and k.endswith("_today_plan"):
                    cid = k[len("charger_"):-len("_today_plan")]
                    _per_charger_plans[cid] = v or []
            # (#804 Phase A) Observed phase model per charger: the
            # measured-W/A phase estimate + the user-named switch
            # capability's validation verdict. Observe-only surface.
            _per_charger_phases = {}
            for k, v in self.coordinator.data.items():
                if k.startswith("charger_") and k.endswith("_active_phases"):
                    cid = k[len("charger_"):-len("_active_phases")]
                    _per_charger_phases[cid] = {
                        "active_phases": v,
                        "switch_entity": self.coordinator.data.get(
                            f"charger_{cid}_phase_switch_entity"),
                        "switch_valid": self.coordinator.data.get(
                            f"charger_{cid}_phase_switch_valid"),
                    }
            attrs.update({
                "battery_soc": self.coordinator.data.get("battery_soc"),
                "calculated_current": self.coordinator.data.get("calculated_current"),
                "available_power": self.coordinator.data.get("available_power"),
                "battery_too_low": self.coordinator.data.get("battery_too_low"),
                "battery_needs_priority": self.coordinator.data.get("battery_needs_priority"),
                "solar_sufficient": self.coordinator.data.get("solar_sufficient"),
                "charging_strategy": self.coordinator.data.get("charging_strategy"),
                "strategy_reason": self.coordinator.data.get("charging_strategy_reason"),
                "per_charger_states": _per_charger_states,
                # EV charge-target deadline (#246) + tariff-optimized status (#247)
                "ev_target_time": self.coordinator.data.get("ev_target_time"),
                "ev_tariff_optimized": self.coordinator.data.get("ev_tariff_optimized"),
                "ev_tariff_waiting": self.coordinator.data.get("ev_tariff_waiting"),
                "ev_deadline_reachable": self.coordinator.data.get("ev_deadline_reachable"),
                "ev_deadline_hours": self.coordinator.data.get("ev_deadline_hours"),
                "ev_next_cheap_window": self.coordinator.data.get("ev_next_cheap_window"),
                # Today's plan rows (#282) — list of {when, kind, label, detail, values}.
                # sem-today-plan-card consumes this directly.
                "today_plan": self.coordinator.data.get("today_plan") or [],
                # Per-charger plan rows (#464) — {cid: [rows…]}.
                "per_charger_plans": _per_charger_plans,
                # Observed phase model (#804 Phase A) — {cid: {active_phases,
                # switch_entity, switch_valid}}.
                "per_charger_phases": _per_charger_phases,
            })
        elif self.entity_description.key in (
            "roi_payback_years", "roi_annual_savings",
        ):
            # (#796) These two depend on the system age. While the install
            # date is the "Jan 1 this year" fallback rather than detected
            # from statistics, they are estimates and say so here instead
            # of presenting a guessed date as a measurement.
            attrs["install_date_estimated"] = bool(
                self.coordinator.data.get("roi_install_date_estimated")
            )
        elif (self.entity_description.key.startswith("charger_")
              and self.entity_description.key.endswith("_estimated_soc")):
            # #708 — the stale-sensor overshoot guard rides as attributes
            # of the per-charger Estimated SOC sensor (no new entities):
            # the session energy-accounted SOC, whether it is what
            # currently holds the charge stopped, and the provenance of the
            # reading the card's info line quotes.
            #
            # The age was originally computed client-side off the
            # vehicle_soc mirror's own ``last_changed``. That measured the
            # wrong interval: an entity going unavailable writes a new
            # state, so a dead sensor dated itself "0 min ago" and the info
            # line lost the value it was explaining exactly when the
            # estimate took over the gauge. The server now publishes the
            # last usable reading and the instant it was taken; the card
            # still does the subtraction, so nothing here moves per minute.
            cid_708 = self.entity_description.key[
                len("charger_"):-len("_estimated_soc")
            ]
            attrs.update({
                "energy_accounted_soc": self.coordinator.data.get(
                    f"charger_{cid_708}_energy_accounted_soc"
                ),
                "estimate_stop_active": self.coordinator.data.get(
                    f"charger_{cid_708}_estimate_stop_active"
                ),
                "vehicle_soc_last": self.coordinator.data.get(
                    f"charger_{cid_708}_vehicle_soc_last"
                ),
                "vehicle_soc_last_at": self.coordinator.data.get(
                    f"charger_{cid_708}_vehicle_soc_last_at"
                ),
            })
        elif self.entity_description.key == "energy_plan":
            # (#638) SHADOW — what the joint planner WOULD do this energy
            # day. sem-energy-plan-card renders these directly; the log
            # lines and the ``diagnose`` stash carry the same plan in prose.
            # (#758) ``tomorrow`` and ``review`` go THROUGH the projection,
            # not around it: they land on this same state, so they have to
            # be inside the recorder's byte budget, not appended after it.
            #   tomorrow — (#638 consolidation / #722) the NEXT energy day's
            #     books for the card's Tomorrow view; live, never stamped.
            #   review   — (#755 pillar 4) what the record has to say, as
            #     machine codes the card translates. Survives the daytime
            #     hours when there is no plan to project.
            attrs.update(_energy_plan_attrs(
                self.coordinator.data.get("energy_plan"),
                extra={
                    "tomorrow": self.coordinator.data.get(
                        "energy_plan_tomorrow"),
                    "review": self.coordinator.data.get("energy_plan_review"),
                },
            ))
        elif self.entity_description.key == "vpp_event":
            # #580 — per-event accounting for payment reconciliation.
            d = self.coordinator.data
            attrs.update({
                "direction": d.get("vpp_event_direction"),
                "started": d.get("vpp_event_started"),
                "delivered_kwh_so_far": d.get("vpp_event_delivered_kwh"),
                "observer": d.get("vpp_event_observer"),
                "reason": d.get("vpp_event_reason"),
                "last_event": d.get("vpp_last_event"),
                "events": d.get("vpp_events") or [],
            })
        elif self.entity_description.key == "charging_strategy":
            attrs.update({
                "reason": self.coordinator.data.get("charging_strategy_reason"),
                "charging_state": self.coordinator.data.get("charging_state"),
                "battery_soc": self.coordinator.data.get("battery_soc"),
                "forecast_remaining_today_kwh": self.coordinator.data.get("forecast_remaining_today_kwh"),
                "daily_ev_energy": self.coordinator.data.get("daily_ev_energy"),
                "forecast_available": self.coordinator.data.get("forecast_available"),
            })
        elif self.entity_description.key == "available_power":
            attrs.update({
                "solar_production": self.coordinator.data.get("solar_production_total"),
                # (#657) ``home_consumption_total`` was never published — the
                # coordinator's key is ``home_consumption_power``.
                "home_consumption": self.coordinator.data.get("home_consumption_power"),
                "safe_discharge_power": self.coordinator.data.get("safe_discharge_power"),
                "excess_solar": self.coordinator.data.get("excess_solar"),
            })
        elif self.entity_description.key == "home_consumption_power":
            # (#699) The ATOMIC balance snapshot for the cards, built by the
            # coordinator (which owns the #237/#444 home-hold state): a
            # known-incoherent cycle carries the LAST COHERENT set forward
            # (flagged ``held``) instead of a chimera of fresh and
            # substituted values — the cards' books add up at every render
            # by construction. Home is the carrier because it is the last
            # value computed FROM the others. Unrecorded — every value
            # already has its own recorded sensor.
            snap = self.coordinator.data.get("power_snapshot")
            if snap:
                attrs["power_snapshot"] = snap
        elif self.entity_description.key == "tariff_current_import_rate":
            # Rich price data for the price card (#257): level, summary, next
            # cheap window, and the upcoming hourly curve.
            d = self.coordinator.data
            attrs.update({
                "price_level": d.get("tariff_price_level"),
                "currency": d.get("tariff_currency"),
                "provider": d.get("tariff_provider"),
                "is_dynamic": d.get("tariff_is_dynamic"),
                "today_min": d.get("tariff_today_min_price"),
                "today_max": d.get("tariff_today_max_price"),
                "today_avg": d.get("tariff_today_avg_price"),
                "next_cheap_start": d.get("tariff_next_cheap_start"),
                "next_cheap_end": d.get("tariff_next_cheap_end"),
                "upcoming": d.get("tariff_upcoming"),
                "schedule_today": d.get("tariff_schedule_today"),
            })
        elif self.entity_description.key == "heat_pump_registration_status":
            # #432: surface WHY the heat pump is or is not registered.
            # State is a single string from the six-value namespace
            # (see HeatPumpSensorData). Attributes expose the resolved
            # entity ids + their live HA state — so users can self-diagnose
            # remotely without us owning the hardware. Mirrors the #359
            # ``classifier_path`` pattern on tariff_price_level.
            d = self.coordinator.data
            attrs.update({
                "registered": d.get("heat_pump_registered"),
                "mode": d.get("heat_pump_mode"),
                "sg_ready_state": d.get("heat_pump_sg_ready_state"),
                "relay1_entity": d.get("heat_pump_relay1_entity"),
                "relay2_entity": d.get("heat_pump_relay2_entity"),
                "climate_entity": d.get("heat_pump_climate_entity"),
                "relay1_state": d.get("heat_pump_relay1_state"),
                "relay2_state": d.get("heat_pump_relay2_state"),
                "climate_state": d.get("heat_pump_climate_state"),
            })
        elif self.entity_description.key == "tariff_price_level":
            # #359: surface WHICH classifier path produced the current level.
            # Lets users in cold-start / unit-mismatch / derivative-entity
            # setups self-diagnose why they're stuck on ``normal`` without
            # having to ask a maintainer for a debug log.
            d = self.coordinator.data
            attrs.update({
                "classifier_path": d.get("tariff_classifier_path"),
                "provider": d.get("tariff_provider"),
                "is_dynamic": d.get("tariff_is_dynamic"),
                "current_import_rate": d.get("tariff_current_import_rate"),
            })
        elif self.entity_description.key == "forecast_dampening_factor":
            # #416: mirror the #359 ``classifier_path`` pattern — expose
            # WHICH branch of the dampening calculation produced the
            # current value so installs hitting an unexpected ceiling /
            # floor can self-diagnose without a maintainer reading the
            # debug log. PROD telemetry on 2026-06-04 showed 35% of
            # ``correction_factor`` records pinned at the post-shrinkage
            # ceiling without any visible signal — this attribute is the
            # signal.
            d = self.coordinator.data
            attrs.update({
                "dampening_path": d.get("forecast_dampening_path"),
                "confidence": d.get("forecast_dampening_confidence"),
                "live_ratio": d.get("forecast_dampening_live_ratio"),
                "normalized_ratio": d.get("forecast_dampening_normalized_ratio"),
                "smoothed_ratio": d.get("forecast_dampening_smoothed_ratio"),
                "pre_clamp": d.get("forecast_dampening_pre_clamp"),
                "correction_factor_historical": d.get("forecast_correction_factor"),
            })
        elif self.entity_description.key == "forecast_correction_factor":
            d = self.coordinator.data
            attrs.update({
                "correction_path": d.get("forecast_correction_path"),
                "bucket_size": d.get("forecast_correction_bucket_size"),
                "weather_category": d.get("forecast_weather_category"),
                "history_days": d.get("forecast_history_days"),
            })
        elif self.entity_description.key == "load_management_status":
            # Add device list details for dashboard table
            devices = self.coordinator.data.get("load_management_devices", {})
            if devices:
                # Attribute is ``devices``; the coordinator key it comes from
                # is ``load_management_devices`` (both are in
                # ``_unrecorded_attributes`` under the ATTRIBUTE name).
                attrs["devices"] = devices
                # Also add a formatted list for easy display
                device_list = []
                for device_id, device_info in devices.items():
                    device_list.append({
                        "id": device_id,
                        "name": device_info.get("friendly_name", device_id),
                        "priority": device_info.get("priority", 5),
                        "critical": device_info.get("is_critical", False),
                        # (#780) both axes; ``controllable`` stays for one
                        # release under its old (mixed) meaning.
                        "has_control_handle": _has_control_handle(device_info),
                        "control_mode": device_info.get("control_mode"),
                        "controllable": _may_actuate(device_info),
                        "power": device_info.get("power_rating", 0),
                        "available": device_info.get("is_available", False),
                    })
                attrs["device_list"] = device_list
        elif self.entity_description.key == "controllable_devices_count":
            # Expose full device list for the drag-and-drop priority card
            # Prefer UnifiedDeviceRegistry (single source of truth) over load_manager
            try:
                registry = getattr(self.coordinator, '_device_registry', None)
                if registry:
                    attrs["devices"] = registry.get_devices_for_sensor()
                elif hasattr(self.coordinator, '_load_manager') and self.coordinator._load_manager:
                    lm_data = self.coordinator._load_manager.get_load_management_data()
                    devices = lm_data.get("devices", {})
                    if devices:
                        attrs["devices"] = {
                            device_id: {
                                "name": info.get("friendly_name", device_id),
                                "priority": info.get("priority", 5),
                                # (#780) capability and permission, separately
                                "has_control_handle": _has_control_handle(info),
                                "user_hands_off": _user_hands_off(info),
                                "control_mode": info.get("control_mode"),
                                "is_controllable": _may_actuate(info),
                                "is_critical": info.get("is_critical", False),
                                "power_rating": info.get("power_rating", 0),
                                "power_entity": info.get("power_entity"),
                                "switch_entity": info.get("switch_entity"),
                                "is_available": info.get("is_available", False),
                                "is_on": info.get("is_on", False),
                                "current_power": info.get("current_power", 0),
                                "device_type": info.get("device_type", "unknown"),
                            }
                            for device_id, info in devices.items()
                        }
            except Exception:
                pass
        elif self.entity_description.key == "target_peak_limit":
            # (#717 redesign) The Control-tab slider needs to know whether
            # the system is currently unlimited to render its MAX notch as
            # "Unlimited" instead of a stale 80.0 kW number.
            attrs["peak_limit_unlimited"] = self.coordinator.data.get(
                "peak_limit_unlimited", False
            )
        elif self.entity_description.key == "monthly_consecutive_peak":
            # (#657) The ``top_5_peaks`` / ``top_5_peaks_formatted`` pair used
            # to be built here from ``peak_history_top5`` — a key no producer
            # was ever written for, in this repo's whole history. The
            # formatter ran on an empty list every cycle and the attributes
            # never appeared. Removed rather than invented: a real top-5 peak
            # history means querying recorder statistics, which is a feature,
            # not a bug fix. ``monthly_consecutive_peak`` (the state) and the
            # three attributes below are unaffected.
            attrs["target_peak_limit"] = self.coordinator.data.get("target_peak_limit", 5.0)
            attrs["peak_trend"] = self.coordinator.data.get("peak_trend", "Unknown")
            attrs["tariff_type"] = self.coordinator.data.get("tariff_type", "unknown")

        # Schedule card hourly data (#63) — attached to surplus_total_w
        if self.entity_description.key == "surplus_total_w":
            attrs["schedule_surplus_hours"] = self.coordinator.data.get("schedule_surplus_hours", [])
            attrs["schedule_ev_hours"] = self.coordinator.data.get("schedule_ev_hours", [])

        # Energy Dashboard mapping (#250) — attach full entity IDs so the System
        # card's Copy diagnostics can list the actual sensors, not just presence.
        if self.entity_description.key == "diag_ed_config":
            try:
                detail = self.coordinator.get_ed_config_detail()
                if detail:
                    attrs["energy_dashboard"] = detail
            except Exception:
                pass

        # Battery charge scheduler (#6) — attach schedule to state sensor
        if self.entity_description.key == "battery_scheduler_state":
            schedule = self.coordinator.data.get("battery_scheduler_schedule", {})
            if schedule:
                attrs["schedule"] = schedule

        # (#566) per-PV-string display name — the cards read this to label the
        # chip/diagram/legend (custom name from options, else compact "PVn").
        _key = self.entity_description.key
        if _key.startswith("pv_string_") and (
            _key.endswith("_power") or _key.endswith("_daily_energy")
        ):
            # key is pv_string_<slot>_power|_daily_energy; slot (pvN) is the
            # first token after the prefix.
            slot = _key[len("pv_string_"):].split("_", 1)[0]
            _sr = getattr(self.coordinator, "_sensor_reader", None)
            if _sr is not None:
                attrs["string_name"] = _sr.pv_string_display_name(slot)

        return attrs

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        self._update_from_coordinator()
        is_available = self._attr_available and self.coordinator.last_update_success
        # Log unavailability once per sensor, not every cycle
        if not is_available and not getattr(self, '_logged_unavailable', False):
            _LOGGER.warning("Sensor %s is unavailable", self.entity_description.key)
            self._logged_unavailable = True
        elif is_available and getattr(self, '_logged_unavailable', False):
            _LOGGER.info("Sensor %s is available again", self.entity_description.key)
            self._logged_unavailable = False
        return is_available

    @property
    def native_value(self) -> str | int | float | None:
        """Return the state of the sensor."""
        # Always update from coordinator to ensure fresh data in tests
        self._update_from_coordinator()
        return self._attr_native_value

    @property
    def last_reset(self) -> datetime | None:
        """Return the time when the sensor was last reset.

        For TOTAL sensors that reset periodically (daily/monthly), this property
        informs Home Assistant's statistics system about the reset cycle, preventing
        negative values in the Energy Dashboard.

        Returns:
            datetime | None: Reset timestamp for periodic sensors, None for lifetime totals
        """
        # Only apply to TOTAL sensors that reset periodically
        if self.entity_description.state_class != SensorStateClass.TOTAL:
            return None

        from homeassistant.util import dt as dt_util
        now = dt_util.now()
        sensor_key = self.entity_description.key

        # Daily reset patterns (reset at midnight 00:00:00)
        daily_reset_patterns = [
            "daily_",  # All daily_* sensors
            "flow_",   # All flow energy sensors (reset daily)
            "sem_daily_",  # SEM daily sensors
            "home_consumption_energy_daily",  # Daily home consumption
        ]

        # Monthly reset patterns (reset at first day of month 00:00:00)
        monthly_reset_patterns = [
            "monthly_",  # All monthly_* sensors
            "home_consumption_energy_monthly",  # Monthly home consumption
            "power_charge_cost",  # Monthly power charge cost
        ]

        # Yearly reset patterns (reset on Jan 1 00:00:00)
        yearly_reset_patterns = [
            "yearly_",  # All yearly_* sensors
        ]

        # Check if sensor resets daily
        if any(pattern in sensor_key for pattern in daily_reset_patterns):
            # Return midnight of current day (00:00:00)
            return now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Check if sensor resets monthly
        if any(pattern in sensor_key for pattern in monthly_reset_patterns):
            # Return first day of current month at midnight
            return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Check if sensor resets yearly
        if any(pattern in sensor_key for pattern in yearly_reset_patterns):
            # Return Jan 1 of current year at midnight
            return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

        # Lifetime totals (never reset) return None
        return None

    def _format_charging_state(self, state: str) -> str:
        """Format charging state to human-readable message (#62).

        The cosmetic ``1a9b3c9`` demotion guard (SOLAR_CHARGING_ACTIVE →
        SOLAR_CHARGING_ALLOWED when calc_current=0 and ev_power<500W)
        was removed in Phase D.2 (#282). Pre-D.2 it papered over the
        budget-formula disagreement between ``_build_charging_context``
        and ``_execute_ev_control``; the canonical-EVBudget unification
        eliminated that disagreement by construction, so the demotion
        is now dead code — verified across daytime battery_assist and
        nighttime MIN_PV soak in v1.6.0/1.6.1.
        """
        from .consts.states import get_status_message

        if not state or not self.coordinator.data:
            return "Unknown"

        return get_status_message(state, self.hass)