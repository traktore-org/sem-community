"""(#1380) ONE owner for "what temperature does this device read?".

Heat pump, hot water tank and climate units all asked this question in their
own code, each with its own order, so a heat pump with only a climate entity
read nothing while the tank read it. One order for every device:

1. the thermometer the user picked (``temperature_entity_id``, a sensor),
2. the device's own climate / water_heater ``current_temperature``,
3. nothing: ``None``, never 0.

A picked sensor that is broken falls through to the device's own entity: a
real reading beats a blind device. Reading is side-effect free; callers that
keep telemetry (``_last_temperature_reading_path``) store the path
themselves.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

_BAD_STATES = ("unknown", "unavailable")

PATH_SENSOR = "sensor"
PATH_ATTRIBUTE = "entity_attribute"
PATH_NONE = "no_source_configured"


@dataclass(frozen=True)
class TemperatureReading:
    """A device temperature in °C (or None) and which source answered."""

    value: Optional[float]
    path: str


def _read_sensor(hass: Any, entity_id: str) -> Tuple[Optional[float], str]:
    """The picked sensor in °C; its own unit decides (#1118)."""
    from ..coordinator.units import temperature_state_to_celsius
    state = hass.states.get(entity_id)
    if state is None:
        return None, f"{PATH_SENSOR}_missing"
    if state.state in _BAD_STATES:
        return None, f"{PATH_SENSOR}_unavailable"
    value = temperature_state_to_celsius(state, None)
    if value is None:
        return None, f"{PATH_SENSOR}_invalid"
    return value, PATH_SENSOR


def _read_own_entity(hass: Any, device: Any, entity_id: str) -> Tuple[Optional[float], bool]:
    """(°C, attribute_was_bad) from the device's own entity attribute."""
    state = hass.states.get(entity_id)
    raw = (state.attributes or {}).get("current_temperature") if state else None
    if raw is None:
        return None, False
    value = device._attribute_temp_c(raw)  # the install's unit decides
    return value, value is None


def temperature_reading(hass: Any, device: Any) -> TemperatureReading:
    """The one read, with the path that answered. Writes nothing."""
    if hass is None:
        return TemperatureReading(None, PATH_NONE)
    sensor_id = getattr(device, "temperature_entity_id", None)
    sensor_path = None
    if sensor_id:
        value, sensor_path = _read_sensor(hass, sensor_id)
        if value is not None:
            return TemperatureReading(value, sensor_path)
    own_id = getattr(device, "own_temperature_entity_id", None)
    attribute_bad = False
    if own_id:
        value, attribute_bad = _read_own_entity(hass, device, own_id)
        if value is not None:
            return TemperatureReading(value, PATH_ATTRIBUTE)
    if sensor_path:
        return TemperatureReading(None, sensor_path)
    return TemperatureReading(
        None, f"{PATH_ATTRIBUTE}_invalid" if attribute_bad else PATH_NONE)


def read_device_temperature(hass: Any, device: Any) -> Optional[float]:
    """The device's temperature in °C, or None."""
    return temperature_reading(hass, device).value


def asked_temperature(device: Any) -> Optional[float]:
    """A controller's reading for the coordinator: a float or None. A
    device without a thermometer, or one that raises, answers None."""
    getter = getattr(device, "get_current_temperature", None)
    if getter is None:
        return None
    try:
        value = getter()
        return float(value) if value is not None else None
    except (ValueError, TypeError, AttributeError):
        return None
