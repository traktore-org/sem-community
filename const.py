"""Constants for SEM Solar Energy Management integration.

This module re-exports all constants from the consts/ package for backward
compatibility. All existing imports (e.g. ``from .const import DOMAIN``)
continue to work unchanged.

For new code, you may import from specific sub-modules for clarity:
    from .consts.core import DOMAIN, DEFAULT_UPDATE_INTERVAL
    from .consts.states import ChargingState, STATUS_MESSAGES
    from .consts.devices import LOAD_MANAGEMENT_DEVICE_PATTERNS
    from .consts.labels import SENSOR_LABEL_MAPPING
"""
from .consts import *  # noqa: F401,F403
