"""Controllable device abstractions for Solar Energy Management.

This module provides a unified device hierarchy for surplus-based control:
- SwitchDevice: on/off devices (hot water relay, smart plugs)
- CurrentControlDevice: variable current devices (EV chargers)
- SetpointDevice: numerical target devices (heat pump, battery)
- ScheduleDevice: deadline-based devices (dishwasher, washer)
"""
from .base import (
    ControllableDevice,
    SwitchDevice,
    CurrentControlDevice,
    SetpointDevice,
    ScheduleDevice,
    DeviceState,
)

__all__ = [
    "ControllableDevice",
    "SwitchDevice",
    "CurrentControlDevice",
    "SetpointDevice",
    "ScheduleDevice",
    "DeviceState",
]
