"""Battery control adapters — encapsulate per-brand command surface.

Unifies the two control axes that pre-v1.7.0 lived in separate
modules:

- ``BatteryProtectionMixin`` (reactive discharge limiting via
  ``number.set_value`` on a discharge control entity)
- ``BatteryChargeAdapter`` + brand subclasses (proactive forced
  charge via brand-specific services)

into one :class:`BatteryControlAdapter` protocol with one method
per :class:`BatteryIntent`. Mirrors the EV ``charger_adapters/``
pattern.
"""
from .base import BatteryControlAdapter
from .generic import GenericBatteryAdapter
from .goodwe import GoodWeBatteryAdapter
from .huawei import HuaweiBatteryAdapter


def adapter_for(hass, config: dict) -> BatteryControlAdapter:
    """Pick the right battery adapter for this install.

    Auto-detect priority (matches today's
    ``BatteryChargeAdapter.adapter_for`` factory):

    1. Explicit ``battery_charge_platform`` config wins
    2. Huawei Solar integration loaded → HuaweiBatteryAdapter
    3. GoodWe integration loaded → GoodWeBatteryAdapter
    4. Otherwise → GenericBatteryAdapter (switch + number target)
    """
    platform = (config.get("battery_charge_platform") or "auto").lower()
    if platform == "huawei":
        return HuaweiBatteryAdapter(hass, config)
    if platform == "goodwe":
        return GoodWeBatteryAdapter(hass, config)
    if platform == "generic":
        return GenericBatteryAdapter(hass, config)

    # Auto-detect
    try:
        if hass and "huawei_solar" in getattr(hass, "data", {}):
            return HuaweiBatteryAdapter(hass, config)
        if hass and "goodwe" in getattr(hass, "data", {}):
            return GoodWeBatteryAdapter(hass, config)
    except (AttributeError, TypeError):
        pass
    return GenericBatteryAdapter(hass, config)


__all__ = [
    "BatteryControlAdapter",
    "HuaweiBatteryAdapter",
    "GoodWeBatteryAdapter",
    "GenericBatteryAdapter",
    "adapter_for",
]
