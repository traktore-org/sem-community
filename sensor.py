"""SEM Solar Energy Management sensors."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any, Dict

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorEntity,
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
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, STATUS_MESSAGES, ChargingState, SENSOR_LABEL_MAPPING
from .coordinator import SEMCoordinator

type SEMConfigEntry = ConfigEntry[SEMCoordinator]

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0  # Coordinator handles all updates

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
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="CHF",
        icon="mdi:cash-fast",
        suggested_display_precision=0,
    ),

    # ============================================================================
    # FORECAST ACCURACY
    # ============================================================================
    SensorEntityDescription(
        key="forecast_accuracy_today",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="%",
        icon="mdi:chart-timeline-variant-shimmer",
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="forecast_accuracy_7d",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="%",
        icon="mdi:chart-timeline-variant-shimmer",
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="forecast_correction_factor",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:tune-vertical",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="forecast_deviation_kwh",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:swap-vertical",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="forecast_corrected_today",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:crystal-ball",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="forecast_corrected_tomorrow",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:crystal-ball",
        suggested_display_precision=1,
    ),
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
    SensorEntityDescription(
        key="forecast_power_now_w",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="forecast_power_next_hour_w",
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
        device_class=SensorDeviceClass.ENERGY,
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
    # UTILITY SIGNALS (Phase 7)
    # ============================================================================

    SensorEntityDescription(
        key="utility_signal_source",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="utility_signal_count_today",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
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
    SensorEntityDescription(
        key="predicted_consumption_next_hour",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="predicted_consumption_today_kwh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="predicted_solar_next_hour",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
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
        device_class=SensorDeviceClass.ENERGY,
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
    SensorEntityDescription(
        key="ev_taper_ratio",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="ev_taper_minutes_to_full",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="min",
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="ev_estimated_soc",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="ev_last_full_charge",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="ev_energy_since_full",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_predicted_daily_consumption",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_nights_until_charge",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="ev_charge_needed",
    ),
    SensorEntityDescription(
        key="ev_battery_health",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="ev_charge_skip_reason",
    ),
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
    SensorEntityDescription(
        key="diag_sensors_unavailable",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="diag_ed_config",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
]



async def _apply_labels_to_sensors(hass: HomeAssistant, sensors) -> None:
    """Apply labels to SEM sensors for dynamic dashboard support."""
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
            SensorEntityDescription(
                key=f"charger_{cid}_nights_until_charge",
                name=f"{cname} Nights Until Charge",
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=0,
            ),
            SensorEntityDescription(
                key=f"charger_{cid}_charge_needed",
                name=f"{cname} Charge Needed",
            ),
            SensorEntityDescription(
                key=f"charger_{cid}_taper_minutes_to_full",
                name=f"{cname} Minutes to Full",
                native_unit_of_measurement=UnitOfTime.MINUTES,
                suggested_display_precision=0,
            ),
        ])

    for desc in per_charger_descriptions:
        sensors.append(SEMSolarSensor(coordinator, desc, entry.entry_id))

    if per_charger_descriptions:
        _LOGGER.info("Created %d per-charger sensors for %d charger(s)",
                      len(per_charger_descriptions), len(ev_chargers))

    _LOGGER.info("Adding %d sensors to Home Assistant", len(sensors))
    async_add_entities(sensors)

    # Fix entity_ids from pre-translation installs and clean up stale entities
    all_descriptions = list(SENSOR_TYPES) + per_charger_descriptions
    _fix_entity_ids(hass, entry, all_descriptions, "sensor")
    _cleanup_stale_entities(hass, entry, all_descriptions, "sensor")

    # Apply labels to entities after they are created
    await _apply_labels_to_sensors(hass, sensors)


class SEMSolarSensor(CoordinatorEntity, RestoreSensor):
    """SEM Solar Energy Management sensor with state persistence."""

    _attr_should_poll = False
    _attr_has_entity_name = True

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
        "heat_pump_mode", "heat_pump_sg_ready_state",
        "pv_degradation_trend", "energy_tip", "energy_tip_category",
        "utility_signal_source",
        "ev_taper_trend", "ev_charge_needed", "ev_charge_skip_reason",
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
                               "battery_discharge_value"]:
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

    async def async_will_remove_from_hass(self) -> None:
        """Remove callbacks when entity is removed from hass."""
        await super().async_will_remove_from_hass()
        # CoordinatorEntity already handles coordinator callbacks, no need to remove extra ones

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

        # Base attributes
        attrs = {
            "last_update": self.coordinator.data.get("last_update"),
            "delta_triggered": self.coordinator.data.get("delta_triggered"),
        }

        # Add specific attributes based on sensor type
        if self.entity_description.key == "charging_state":
            attrs.update({
                "battery_soc": self.coordinator.data.get("battery_soc"),
                "calculated_current": self.coordinator.data.get("calculated_current"),
                "available_power": self.coordinator.data.get("available_power"),
                "battery_too_low": self.coordinator.data.get("battery_too_low"),
                "battery_needs_priority": self.coordinator.data.get("battery_needs_priority"),
                "solar_sufficient": self.coordinator.data.get("solar_sufficient"),
                "charging_strategy": self.coordinator.data.get("charging_strategy"),
                "strategy_reason": self.coordinator.data.get("charging_strategy_reason"),
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
                "home_consumption": self.coordinator.data.get("home_consumption_total"),
                "safe_discharge_power": self.coordinator.data.get("safe_discharge_power"),
                "excess_solar": self.coordinator.data.get("excess_solar"),
            })
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
        elif self.entity_description.key == "load_management_status":
            # Add device list details for dashboard table
            devices = self.coordinator.data.get("load_management_devices", {})
            if devices:
                attrs["devices"] = devices
                # Also add a formatted list for easy display
                device_list = []
                for device_id, device_info in devices.items():
                    device_list.append({
                        "id": device_id,
                        "name": device_info.get("friendly_name", device_id),
                        "priority": device_info.get("priority", 5),
                        "critical": device_info.get("is_critical", False),
                        "controllable": device_info.get("is_controllable", True),
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
                                "is_controllable": info.get("is_controllable", True),
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
        elif self.entity_description.key == "monthly_consecutive_peak":
            # Add historical top 5 peaks from HA statistics
            peak_history = self.coordinator.data.get("peak_history_top5", [])
            if peak_history:
                attrs["top_5_peaks"] = peak_history
                # Also format as readable strings
                attrs["top_5_peaks_formatted"] = [
                    f"{p['value']} kW ({p['date']} {p['time']})"
                    for p in peak_history
                ]
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

        Display-honesty guard (#282 followup): the state machine can return
        SOLAR_CHARGING_ACTIVE based on the redirect-inflated ``ev_budget``
        even when the actuator is at 0 A and the EV is drawing nothing,
        because ``_build_charging_context`` and ``_execute_ev_control`` use
        *different* budget formulas. Caught live on PROD 2026-05-29 when
        the dashboard showed "Solar mode - Charging active" with
        ``calculated_current=0 A`` and ``ev_power=0 W``. Until the three
        budget paths are unified, demote the displayed label whenever the
        published actuator state contradicts "active": this is a
        last-mile fix at the user-facing string only — the underlying
        ``charging_state`` value is unchanged, so other consumers
        (solar_charging_status, notifications, automations) keep their
        existing behaviour.
        """
        from .consts.states import ChargingState, get_status_message

        if not state or not self.coordinator.data:
            return "Unknown"

        # Only the "active" labels lie when the actuator is idle. Allowed /
        # waiting / paused / target_reached / super-charging already match
        # what the user sees on the dashboard.
        if state == ChargingState.SOLAR_CHARGING_ACTIVE:
            try:
                calc_a = float(self.coordinator.data.get("calculated_current", 0) or 0)
                ev_w = float(self.coordinator.data.get("ev_charging_power", 0) or 0)
            except (TypeError, ValueError):
                calc_a, ev_w = 0.0, 0.0
            # Idle floor: 6 A * 3-phase * 230 V ≈ 4140 W is the smallest real
            # session; 500 W is comfortably "definitely not charging" with
            # headroom for measurement noise and wallbox standby draw.
            if calc_a == 0 and ev_w < 500:
                state = ChargingState.SOLAR_CHARGING_ALLOWED

        return get_status_message(state, self.hass)