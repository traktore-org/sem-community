"""Safe battery power-control writes.

SEM decisions use watts while Home Assistant number entities may expose another
native unit. Every automatic discharge-limit write passes through this module
so current, percentage, unavailable, and out-of-range controls fail closed.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass

from .units import (
    is_battery_control_power_unit,
    normalize_unit,
    power_unit_scale,
)

_LOGGER = logging.getLogger(__name__)
_UNREADABLE_STATES = {"unknown", "unavailable", "none", ""}


@dataclass(frozen=True)
class PreparedPowerSetpoint:
    """A validated Home Assistant native-unit setpoint."""

    domain: str
    value: float
    current_value: float
    scale_to_watts: float
    unit: str


def _looks_like_current(entity_id: str) -> bool:
    name = entity_id.lower()
    return "current" in name or "ampere" in name or name.endswith("_amps")


def _native_power_scale(
    hass,
    entity_id: str,
    *,
    require_explicit_unit: bool = False,
) -> float | None:
    """Return native-unit-to-watts scale, or ``None`` when unsafe."""
    state = hass.states.get(entity_id)
    if state is None:
        return None

    raw_state = str(getattr(state, "state", "")).strip().lower()
    if raw_state in _UNREADABLE_STATES:
        return None

    attrs = getattr(state, "attributes", None)
    if not isinstance(attrs, Mapping):
        # Lightweight legacy test doubles and helper-like entities may not
        # expose a real attributes mapping. Keep the historical base-unit
        # assumption while still blocking obvious current-register names.
        return None if _looks_like_current(entity_id) else 1.0

    unit = normalize_unit(state)
    if unit:
        if not is_battery_control_power_unit(state):
            _LOGGER.warning(
                "Battery power control %s rejected: unit %r is not a supported "
                "power-control unit",
                entity_id,
                attrs.get("unit_of_measurement"),
            )
            return None
        return power_unit_scale(state)

    if require_explicit_unit or _looks_like_current(entity_id):
        _LOGGER.warning(
            "Battery power control %s rejected: explicit power unit required",
            entity_id,
        )
        return None

    # Unitless number helpers have historically meant watts when explicitly
    # selected by the user. Preserve that supported configuration.
    return 1.0


def native_power_scale(
    hass,
    entity_id: str,
    *,
    require_explicit_unit: bool = False,
) -> float | None:
    """Public face of :func:`_native_power_scale` (#749): the forcible-
    discharge setpoint write shares the ONE validation rule with the
    discharge-limit path instead of growing a second, laxer one."""
    return _native_power_scale(
        hass, entity_id, require_explicit_unit=require_explicit_unit)


def is_valid_power_control_entity(
    hass,
    entity_id: str,
    *,
    require_explicit_unit: bool = False,
) -> bool:
    """Return whether a live entity is safe for a battery power setpoint."""
    return _native_power_scale(
        hass,
        entity_id,
        require_explicit_unit=require_explicit_unit,
    ) is not None


def prepare_power_setpoint(
    hass,
    entity_id: str,
    watts: float,
    *,
    require_explicit_unit: bool = False,
) -> PreparedPowerSetpoint | None:
    """Validate and convert a watt request to the entity's native unit."""
    scale_to_watts = _native_power_scale(
        hass,
        entity_id,
        require_explicit_unit=require_explicit_unit,
    )
    if scale_to_watts is None:
        return None

    state = hass.states.get(entity_id)
    if state is None:  # defensive; _native_power_scale already checked
        return None
    try:
        current_value = float(state.state)
        native_value = float(watts) / scale_to_watts
    except (TypeError, ValueError, OverflowError):
        _LOGGER.warning(
            "Battery power control %s rejected: unreadable state or setpoint",
            entity_id,
        )
        return None
    if not all(math.isfinite(value) for value in (
        current_value, native_value, scale_to_watts,
    )):
        _LOGGER.warning(
            "Battery power control %s rejected: non-finite state or setpoint",
            entity_id,
        )
        return None

    attrs = getattr(state, "attributes", None)
    if isinstance(attrs, Mapping):
        bounds = (
            ("min", lambda value, bound: value < bound),
            ("max", lambda value, bound: value > bound),
        )
        for key, compare in bounds:
            raw_bound = attrs.get(key)
            if raw_bound is None:
                continue
            try:
                bound = float(raw_bound)
            except (TypeError, ValueError, OverflowError):
                continue
            if not math.isfinite(bound):
                _LOGGER.warning(
                    "Battery power control %s rejected: non-finite %s bound",
                    entity_id,
                    key,
                )
                return None
            if compare(native_value, bound):
                _LOGGER.warning(
                    "Battery power control %s rejected: %.3f is outside %s=%s",
                    entity_id,
                    native_value,
                    key,
                    raw_bound,
                )
                return None

    domain = entity_id.split(".", 1)[0]
    if domain not in {"number", "input_number"}:
        _LOGGER.warning(
            "Battery power control %s rejected: unsupported domain %s",
            entity_id,
            domain,
        )
        return None

    return PreparedPowerSetpoint(
        domain=domain,
        value=native_value,
        current_value=current_value,
        scale_to_watts=scale_to_watts,
        unit=normalize_unit(state),
    )


async def async_write_power_setpoint(
    hass,
    entity_id: str,
    watts: float,
    *,
    context: str,
) -> bool:
    """Validate, convert, and write a watt setpoint. Return success."""
    prepared = prepare_power_setpoint(hass, entity_id, watts)
    if prepared is None:
        return False
    try:
        await hass.services.async_call(
            prepared.domain,
            "set_value",
            {"entity_id": entity_id, "value": prepared.value},
            blocking=True,
        )
    except Exception as err:  # noqa: BLE001 - HA service exceptions vary
        _LOGGER.warning("%s: failed to set %s: %s", context, entity_id, err)
        return False
    return True
