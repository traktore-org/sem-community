"""Battery control adapters — encapsulate per-brand command surface.

Unifies the two control axes that pre-v1.7.0 lived in separate
modules:

- the deleted ``BatteryProtectionMixin`` (#624; reactive discharge limiting via
  ``number.set_value`` on a discharge control entity)
- ``force_charge.py`` brand impls (#624; proactive forced
  charge via brand-specific services)

into one :class:`BatteryControlAdapter` protocol with one method
per :class:`BatteryIntent`. Mirrors the EV ``charger_adapters/``
pattern.
"""
import logging

from .base import BatteryControlAdapter
from .deye import DeyeBatteryAdapter, DeyeCapability, DeyeControlSnapshot
from .generic import GenericBatteryAdapter
from typing import Optional

from .goodwe import GoodWeBatteryAdapter
from .huawei import HuaweiBatteryAdapter
from ...utils.log_gate import log_on_change

_LOGGER = logging.getLogger(__name__)


def adapter_for(hass, config: dict) -> BatteryControlAdapter:
    """Pick the right battery adapter for this battery.

    Auto-detect priority (matches today's
    ``adapter_for`` factory):

    1. Explicit ``battery_charge_platform`` config wins
    2. Huawei Solar integration loaded → HuaweiBatteryAdapter
    3. GoodWe integration loaded → GoodWeBatteryAdapter
    4. Otherwise → GenericBatteryAdapter (switch + number target)

    (#1183) Steps 1–3 name the brand of the install. In a home with more
    than one battery a brand counts only for a battery whose own entities
    belong to it (``_own_brand_domains``): the brand's service calls go to
    the brand's inverter, and a sibling battery would force-charge it.
    """
    platform = (config.get("battery_charge_platform") or "auto").lower()
    if platform == "deye":
        return DeyeBatteryAdapter(hass, config)
    if platform == "huawei":
        if "huawei_solar" not in _own_brand_domains(hass, config):
            return GenericBatteryAdapter(hass, config)
        return HuaweiBatteryAdapter(hass, config)
    if platform == "goodwe":
        if "goodwe" not in _own_brand_domains(hass, config):
            return GenericBatteryAdapter(hass, config)
        return GoodWeBatteryAdapter(hass, config)
    if platform == "generic":
        return GenericBatteryAdapter(hass, config)

    # #531: a battery with its OWN AC-coupled control surface (a power-strategy
    # select, or a bidirectional power setpoint — e.g. Sessy) is not a brand DC
    # battery, even when a Huawei/GoodWe integration is loaded for a SIBLING in
    # a mixed fleet; (#1183) nor is any battery whose own entities belong to
    # another integration (``auto_brand``).
    domain = auto_brand(hass, config)
    if domain == "huawei_solar":
        return HuaweiBatteryAdapter(hass, config)
    if domain == "goodwe":
        return GoodWeBatteryAdapter(hass, config)
    return GenericBatteryAdapter(hass, config)


#: The brand integrations auto-detect drives a battery through, in the order
#: a one-battery home asks them, and the platform name each one pins.
_BRAND_DOMAINS: tuple = (("huawei_solar", "huawei"), ("goodwe", "goodwe"))


def _own_control_surface(config: dict) -> bool:
    """(#531) A battery with its own AC-coupled control: a power-strategy
    select, a bidirectional setpoint or a power-direction entity (#869)."""
    return bool(config.get("battery_strategy_control_entity")
                or config.get("battery_setpoint_bidirectional")
                or config.get("battery_power_direction_entity"))


def _own_brand_domains(hass, config: dict) -> tuple:
    """(#1183) The brand integrations this battery may be driven through.

    A home with one battery: every brand. The integration loaded there is
    the battery's own, and ``battery_fleet_size`` is unset outside the
    coordinator's per-battery context.

    A home with more batteries: only the brand that the battery's own
    entities belong to (``battery_own_entity_ids``, set per battery by
    ``_battery_adapter_context``), asked of the entity registry. A brand
    loaded for another battery is not this battery's. No brand among them,
    two brands, or a registry that does not answer: none, and the battery
    gets the generic adapter, which sends nothing to a brand's inverter.
    """
    try:
        fleet = int(config.get("battery_fleet_size") or 1)
    except (TypeError, ValueError):
        fleet = 1
    if fleet <= 1:
        return tuple(domain for domain, _name in _BRAND_DOMAINS)
    own = config.get("battery_own_entity_ids") or ()
    try:
        from homeassistant.helpers import entity_registry as er
        reg = er.async_get(hass)
        platforms = {
            str(getattr(reg.async_get(eid), "platform", "") or "")
            for eid in own if isinstance(eid, str) and eid
        }
    except Exception as err:  # noqa: BLE001 — no registry answer is no brand
        log_on_change(
            _LOGGER, "battery_brand_registry", logging.WARNING,
            "cannot read the entity registry to find a battery's brand, so "
            "it is driven as a generic battery (#1183): %s", err)
        return ()
    found = tuple(domain for domain, _name in _BRAND_DOMAINS
                  if domain in platforms)
    return found if len(found) == 1 else ()


def auto_brand(hass, config: dict) -> "Optional[str]":
    """The brand integration auto-detect drives this battery through, or
    None for the generic adapter.

    A battery with its OWN AC-coupled control surface (#531, e.g. Sessy)
    is not a brand DC battery. Otherwise the first of its brands
    (``_own_brand_domains``) that is loaded. Checks BOTH legacy
    ``hass.data`` and loaded config entries — modern integrations (incl.
    recent huawei_solar) store state in ``entry.runtime_data`` and never
    populate ``hass.data`` (#523: a real Huawei battery fell back to the
    Generic adapter and lost its force-discharge path).
    """
    if _own_control_surface(config):
        return None
    try:
        for domain in _own_brand_domains(hass, config):
            if _integration_loaded(hass, domain):
                return domain
    except (AttributeError, TypeError):
        pass
    return None


def pinned_generic_brand(hass, config: dict) -> "Optional[str]":
    """(#900) The brand a ``generic`` install would auto-detect to — or None.

    The options wizard used to offer generic / deye only and default to
    generic, so a Huawei or GoodWe install that walked that page once came
    out explicitly pinned to the generic adapter: no forcible charge, no
    #538 idempotent writes. The stored value is indistinguishable from a
    real choice, so the factory keeps honouring it; this names the case so
    a Repair can tell the user. A generic battery with its OWN control
    surface (a Sessy beside a Huawei fleet, #531) is a real choice and is
    not named.
    """
    if not _pinnable(config):
        return None
    # (#1183) the brand THIS battery would auto-detect to, not the install's
    return dict(_BRAND_DOMAINS).get(auto_brand(hass, config) or "")


def _pinnable(config: dict) -> bool:
    """A generic pin without its own control surface — the case #900 names."""
    platform = (config.get("battery_charge_platform") or "auto").lower()
    if platform != "generic":
        return False
    return not _own_control_surface(config)


def pinned_generic_pending(hass, config: dict) -> bool:
    """(#933) Could ``pinned_generic_brand``'s None still become a brand?

    True for a generic pin while a Huawei/GoodWe config entry exists that has
    not finished loading — HA reports ``is_running`` from ``starting`` on,
    and an entry in SETUP_RETRY is not loaded. That None is "not yet", not
    "no"."""
    if not _pinnable(config):
        return False
    for domain in _own_brand_domains(hass, config):    # (#1183)
        try:
            if (hass.config_entries.async_entries(domain)
                    and not _integration_loaded(hass, domain)):
                return True
        except (AttributeError, TypeError):
            continue
    return False


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
    "DeyeBatteryAdapter",
    "DeyeCapability",
    "DeyeControlSnapshot",
    "HuaweiBatteryAdapter",
    "GoodWeBatteryAdapter",
    "GenericBatteryAdapter",
    "adapter_for",
    "auto_brand",
]
