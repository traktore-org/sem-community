"""Coordinator module for Solar Energy Management.

This module provides a modular coordinator architecture:
- SEMCoordinator: Main orchestrator (DataUpdateCoordinator)
- SensorReader: Hardware sensor reading
- EnergyCalculator: Energy integration from power
- FlowCalculator: Power and energy flow calculations
- ChargingStateMachine: Charging mode selection (solar/night/idle)
- SurplusController: Multi-device surplus distribution (Phase 0)
- ForecastReader: Solar forecast integration (Phase 0.3)
- SEMStorage: Persistence
- NotificationManager: Mobile/KEBA notifications
"""
from .coordinator import SEMCoordinator
from .types import (
    PowerReadings,
    PowerFlows,
    EnergyTotals,
    EnergyFlows,
    CostData,
    PerformanceMetrics,
    SystemStatus,
    LoadManagementData,
    SurplusControlData,
    ForecastSensorData,
    TariffSensorData,
    HeatPumpSensorData,
    PVAnalyticsData,
    EnergyAssistantSensorData,
    UtilitySignalSensorData,
    SEMData,
)
from .sensor_reader import SensorReader
from .energy_calculator import EnergyCalculator
from .flow_calculator import FlowCalculator
from .charging_control import ChargingStateMachine, ChargingContext
from .surplus_controller import SurplusController
from .forecast_reader import ForecastReader
from .storage import SEMStorage
from .notifications import NotificationManager

__all__ = [
    "SEMCoordinator",
    "PowerReadings",
    "PowerFlows",
    "EnergyTotals",
    "EnergyFlows",
    "CostData",
    "PerformanceMetrics",
    "SystemStatus",
    "LoadManagementData",
    "SurplusControlData",
    "ForecastSensorData",
    "TariffSensorData",
    "HeatPumpSensorData",
    "PVAnalyticsData",
    "EnergyAssistantSensorData",
    "UtilitySignalSensorData",
    "SEMData",
    "SensorReader",
    "EnergyCalculator",
    "FlowCalculator",
    "ChargingStateMachine",
    "ChargingContext",
    "SurplusController",
    "ForecastReader",
    "SEMStorage",
    "NotificationManager",
]
