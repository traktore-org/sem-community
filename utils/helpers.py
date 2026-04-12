"""Helper utility functions for Solar Energy Management.

This module contains pure utility functions that have no dependencies
on the coordinator or other components.
"""
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)


def safe_float(value: Any, default: float = 0) -> float:
    """Safely convert value to float, handling 'unavailable' and other invalid states.

    Args:
        value: Value to convert to float
        default: Default value if conversion fails

    Returns:
        Float value or default

    Examples:
        >>> safe_float("123.45")
        123.45
        >>> safe_float("unavailable", 0)
        0
        >>> safe_float(None, 100)
        100
    """
    if value in (None, "unknown", "unavailable", "None"):
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_format(value: Any, format_spec: str = ":.1f", fallback: str = "--") -> str:
    """Safely format a value, handling None cases.

    Args:
        value: Value to format
        format_spec: Python format specification (default: ":.1f")
        fallback: Fallback string if formatting fails (default: "--")

    Returns:
        Formatted string or fallback

    Examples:
        >>> safe_format(123.456, ":.2f")
        '123.46'
        >>> safe_format(None)
        '--'
        >>> safe_format("invalid", ":.1f", "N/A")
        'N/A'
    """
    if value is None:
        return fallback
    try:
        return f"{value:{format_spec}}"
    except (ValueError, TypeError):
        return fallback


def convert_power_to_watts(value: float, unit: str, sensor_name: str = "") -> float:
    """Convert power value to watts based on unit, with standardized handling.

    Args:
        value: Power value to convert
        unit: Unit of measurement (e.g., "W", "kW")
        sensor_name: Name of sensor (used for EV detection heuristic)

    Returns:
        Power value in watts

    Examples:
        >>> convert_power_to_watts(5.2, "kW", "solar_power")
        5200.0
        >>> convert_power_to_watts(1500, "W", "home_power")
        1500.0
        >>> convert_power_to_watts(11.5, "unknown", "ev_charging_power")
        11500.0
    """
    unit_lower = unit.lower() if unit else ""

    if unit_lower in ["kw", "kilowatt", "kilowatts"]:
        return value * 1000  # Convert kW to W
    elif unit_lower in ["w", "watt", "watts"]:
        return value  # Already in watts
    else:
        # Default assumption: most power sensors are in W
        # Special case for EV sensors: default to kW conversion if unit not specified or unknown
        if "ev" in sensor_name.lower() or "keba" in sensor_name.lower():
            if unit:
                _LOGGER.warning(
                    f"EV power sensor {sensor_name} has unknown unit '{unit}', assuming kW"
                )
            return value * 1000  # EV sensors default to kW
        else:
            if unit:
                _LOGGER.warning(
                    f"Power sensor {sensor_name} has unknown unit '{unit}', assuming W"
                )
            return value  # Default to watts for non-EV sensors
