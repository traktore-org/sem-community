"""SEM Solar Energy Management sensors."""
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
    UnitOfTemperature,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, STATUS_MESSAGES, ChargingState, SENSOR_LABEL_MAPPING
from .coordinator import SEMCoordinator

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
    ),
    SensorEntityDescription(
        key="home_consumption_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="grid_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="grid_import_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="grid_export_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="battery_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="battery_charge_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="battery_discharge_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="ev_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    # Removed: ev_charging_power — duplicate of ev_power
    SensorEntityDescription(
        key="available_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
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
    ),
    SensorEntityDescription(
        key="battery_health_score",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        icon="mdi:battery-heart-variant",
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
    ),
    SensorEntityDescription(
        key="grid_status",
    ),
    SensorEntityDescription(
        key="solar_charging_status",
    ),
    SensorEntityDescription(
        key="night_charging_status",
    ),
    SensorEntityDescription(
        key="battery_priority_status",
    ),
    SensorEntityDescription(
        key="charging_strategy",
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
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="kg",
        icon="mdi:molecule-co2",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="yearly_co2_avoided",
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
    ),
    SensorEntityDescription(
        key="flow_solar_to_battery_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="flow_solar_to_grid_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="flow_solar_to_ev_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="flow_battery_to_home_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="flow_battery_to_ev_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="flow_grid_to_home_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="flow_grid_to_ev_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="flow_grid_to_battery_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
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
    ),
    SensorEntityDescription(
        key="load_management_recommendation",
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
    ),
    SensorEntityDescription(
        key="surplus_distributable_w",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="surplus_allocated_w",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="surplus_unallocated_w",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
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
    ),
    SensorEntityDescription(
        key="forecast_power_next_hour_w",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="forecast_peak_power_today_w",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
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
    ),
    SensorEntityDescription(
        key="forecast_source",
    ),
    SensorEntityDescription(
        key="charging_recommendation",
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
    ),
    SensorEntityDescription(
        key="tariff_provider",
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
    ),
    SensorEntityDescription(
        key="pv_performance_vs_forecast",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="pv_estimated_annual_degradation",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="pv_degradation_trend",
    ),

    # ============================================================================
    # ENERGY ASSISTANT (Phase 6)
    # ============================================================================

    SensorEntityDescription(
        key="energy_optimization_score",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="points",
    ),
    SensorEntityDescription(
        key="energy_tip",
    ),
    SensorEntityDescription(
        key="energy_tip_category",
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
    ),
    SensorEntityDescription(
        key="utility_signal_count_today",
        state_class=SensorStateClass.MEASUREMENT,
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


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up SEM Solar Energy Management sensors."""
    _LOGGER.info("Setting up SEM sensors for entry %s", entry.entry_id)

    if DOMAIN not in hass.data:
        _LOGGER.error("SEM domain not in hass.data")
        return

    if entry.entry_id not in hass.data[DOMAIN]:
        _LOGGER.error("Entry ID %s not in hass.data[%s]", entry.entry_id, DOMAIN)
        return

    coordinator = hass.data[DOMAIN][entry.entry_id]
    _LOGGER.info("Got coordinator, creating %d sensors", len(SENSOR_TYPES))

    sensors = [
        SEMSolarSensor(coordinator, description, entry.entry_id)
        for description in SENSOR_TYPES
    ]

    _LOGGER.info("Adding %d sensors to Home Assistant", len(sensors))
    async_add_entities(sensors)

    # Apply labels to entities after they are created
    await _apply_labels_to_sensors(hass, sensors)


class SEMSolarSensor(CoordinatorEntity, RestoreSensor):
    """SEM Solar Energy Management sensor with state persistence."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _logged_unavailable: bool = False

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

        # Initialize availability and value
        self._attr_available = True
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

            # Convert string numbers to float/int for numeric sensors
            if isinstance(value, str):
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
            self._attr_native_value = value
            self._attr_available = value is not None
        else:
            # Data key not found - mark as unavailable
            self._attr_available = False
            self._attr_native_value = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_from_coordinator()

        # Aggressive database lock prevention
        import asyncio
        import random

        # Define sensor priority levels
        critical_sensors = ["available_power", "calculated_current", "charging_state", "battery_soc"]
        important_sensors = ["solar_power", "grid_power", "battery_power", "ev_power", "home_consumption"]

        # Determine update category
        if any(sensor in self.entity_description.key for sensor in critical_sensors):
            # Critical: 1-5 second delay
            delay = 1 + (hash(self.entity_id) % 40) / 10
        elif any(sensor in self.entity_description.key for sensor in important_sensors):
            # Important: 5-15 second delay
            delay = 5 + (hash(self.entity_id) % 100) / 10
        else:
            # Non-essential: 15-60 second delay
            delay = 15 + (hash(self.entity_id) % 450) / 10

        # Add random jitter to prevent synchronized updates
        delay += random.uniform(0, 2)

        async def delayed_write() -> None:
            await asyncio.sleep(delay)
            # Double-check if entity still exists before writing
            try:
                self.async_write_ha_state()
            except Exception:
                pass  # Silently ignore if entity is gone

        asyncio.create_task(delayed_write())

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

        return attrs

    @property
    def available(self) -> bool:
        """Return if entity is available. Logs once on transition."""
        # Always update from coordinator to ensure fresh availability in tests
        self._update_from_coordinator()
        is_available = self._attr_available and self.coordinator.last_update_success
        if not is_available and not self._logged_unavailable:
            _LOGGER.warning("Sensor %s is unavailable", self.entity_description.key)
            self._logged_unavailable = True
        elif is_available and self._logged_unavailable:
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

        # Check if sensor resets daily
        if any(pattern in sensor_key for pattern in daily_reset_patterns):
            # Return midnight of current day (00:00:00)
            return now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Check if sensor resets monthly
        if any(pattern in sensor_key for pattern in monthly_reset_patterns):
            # Return first day of current month at midnight
            return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Lifetime totals (never reset) return None
        return None

    def _format_charging_state(self, state: str) -> str:
        """Format charging state to human-readable message."""
        if not state or not self.coordinator.data:
            return "Unknown"
        return STATUS_MESSAGES.get(state, state)