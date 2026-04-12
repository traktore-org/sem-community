"""Backward compatibility shim — moved to features/device_registry.py."""
from .features.device_registry import *  # noqa: F401,F403
from .features.device_registry import UnifiedDeviceRegistry, UnifiedDevice  # noqa: F401
