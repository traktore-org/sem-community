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

    # #531: a battery with its OWN AC-coupled control surface (a power-strategy
    # select, or a bidirectional power setpoint — e.g. Sessy) is not a brand DC
    # battery, even when a Huawei/GoodWe integration is loaded for a SIBLING in
    # a mixed fleet. Without this gate the global auto-detect below promotes it
    # to a Huawei/GoodWe adapter whose service calls never reach it (the
    # mixed-brand self-heal bug). These per-battery keys come from
    # ``_per_battery_config`` overlays, so single-brand installs are unaffected.
    if (
        config.get("battery_strategy_control_entity")
        or config.get("battery_setpoint_bidirectional")
    ):
        return GenericBatteryAdapter(hass, config)

    # Auto-detect. Check BOTH legacy ``hass.data`` and loaded config
    # entries — modern integrations (incl. recent huawei_solar) store
    # state in ``entry.runtime_data`` and never populate ``hass.data``,
    # so the old ``"huawei_solar" in hass.data`` check silently failed and
    # a real Huawei battery fell back to the Generic adapter (no forcible-
    # discharge service path → #523 force-discharge dropped).
    try:
        if _integration_loaded(hass, "huawei_solar"):
            return HuaweiBatteryAdapter(hass, config)
        if _integration_loaded(hass, "goodwe"):
            return GoodWeBatteryAdapter(hass, config)
    except (AttributeError, TypeError):
        pass
    return GenericBatteryAdapter(hass, config)


def _integration_loaded(hass, domain: str) -> bool:
    """True if ``domain`` is set up — robust to hass.data vs runtime_data."""
    if not hass:
        return False
    if domain in getattr(hass, "data", {}):
        return True
    try:
        entries = hass.config_entries.async_entries(domain)
    except (AttributeError, TypeError):
        return False
    return any(
        getattr(getattr(e, "state", None), "value", None) == "loaded"
        or str(getattr(e, "state", "")) == "ConfigEntryState.LOADED"
        for e in entries
    )


__all__ = [
    "BatteryControlAdapter",
    "HuaweiBatteryAdapter",
    "GoodWeBatteryAdapter",
    "GenericBatteryAdapter",
    "adapter_for",
]
