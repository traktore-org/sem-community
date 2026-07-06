"""Controllable device abstractions for Solar Energy Management.

This module provides a unified device hierarchy for surplus-based control:
- SwitchDevice: on/off devices (hot water relay, smart plugs)
- ClimateDevice: on/off climate.* devices (air-conditioners, heat pumps)
- CurrentControlDevice: variable current devices (EV chargers)
- SetpointDevice: numerical target devices (heat pump, battery)
- ScheduleDevice: deadline-based devices (dishwasher, washer)
"""
from .base import (
    ControllableDevice,
    SwitchDevice,
    ClimateDevice,
    CurrentControlDevice,
    SetpointDevice,
    ScheduleDevice,
    DeviceState,
    surplus_device_from_spec,
)

__all__ = [
    "ControllableDevice",
    "SwitchDevice",
    "ClimateDevice",
    "CurrentControlDevice",
    "SetpointDevice",
    "ScheduleDevice",
    "DeviceState",
    "surplus_device_from_spec",
]
