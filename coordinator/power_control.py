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

from ..utils.log_gate import log_on_change
from .units import (
    is_battery_control_power_unit,
    normalize_unit,
    power_unit_scale,
)
from .units import finite_float

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
            log_on_change(
                _LOGGER, f"power_control:{entity_id}", logging.WARNING,
                "Battery power control %s rejected: unit %r is not a supported "
                "power-control unit",
                entity_id,
                attrs.get("unit_of_measurement"),
            )
            return None
        return power_unit_scale(state)

    if require_explicit_unit or _looks_like_current(entity_id):
        log_on_change(
            _LOGGER, f"power_control:{entity_id}", logging.WARNING,
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


def clamp_to_entity_range(
    attrs,
    watts: float,
    scale: float,
    *,
    round_down_to_step: bool = False,
) -> float:
    """Clamp a watt value to a number entity's own min/max (#523).

    ``min``/``max``/``step`` are the entity's NATIVE units, so they are
    scaled to watts with ``scale`` (from :func:`native_power_scale`); the
    result stays in watts. Home Assistant REFUSES a ``number.set_value``
    outside the range, and a non-blocking call never hears about it — the
    register keeps its old value while the writer believes it moved
    (RienduPre's Sessy setpoint stuck at 0, #523; Arne's charge limit stuck
    at 1560 W, #820). ONE clamp for every power write.

    ``round_down_to_step`` is for a ceiling (a charge cap): rounding it up
    to the next step would let through more than was decided. The grid
    starts at zero (#820: min 10, step 100 means 1400, not 1410). A cap
    below the first grid point lands on the entity's MIN — Home Assistant
    always accepts the min, and it is the smallest cap the entity has.
    """
    if not isinstance(attrs, Mapping):
        return watts
    lo = attrs.get("min")
    lo_w = (float(lo) * scale
            if isinstance(lo, (int, float)) and math.isfinite(lo) else None)
    hi = attrs.get("max")
    hi_w = (float(hi) * scale
            if isinstance(hi, (int, float)) and math.isfinite(hi) else None)
    step = attrs.get("step")
    step_w = (float(step) * scale
              if round_down_to_step and isinstance(step, (int, float))
              and math.isfinite(step) and step > 0 else None)

    def _floor(value: float) -> float:
        # (#820, 02.10) The grid starts at ZERO. Arne's Sungrow template
        # number has min 10 and step 100; a grid anchored at the min gave
        # 1410 W and, with step 10, 1151 W — values off the step the user
        # sees. A min that sits on its own step's grid is the same grid.
        # The tiny tolerance keeps 2.4 kW / 0.1 kW at 24 steps, not 23.
        return math.floor(value / step_w + 1e-9) * step_w

    if step_w is not None:
        watts = _floor(watts)
    if hi_w is not None:
        if step_w is not None and watts > hi_w:
            # a capped ceiling is still a value on the step (#820 review)
            hi_w = _floor(hi_w)
        watts = min(hi_w, watts)
    if lo_w is not None:
        # The entity's own floor wins over the grid: Home Assistant
        # accepts its min, and nothing lower — a cap below the first
        # grid point lands here.
        watts = max(lo_w, watts)
    return watts


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


def entity_max_watts(hass, entity_id: str) -> float | None:
    """The highest value the control entity accepts, in watts.

    ``None`` when the entity, its unit or its ``max`` attribute cannot be
    read; the caller then keeps its configured ceiling.
    """
    if not entity_id:
        return None
    scale_to_watts = _native_power_scale(hass, entity_id)
    if scale_to_watts is None:
        return None
    attrs = getattr(hass.states.get(entity_id), "attributes", None)
    if not isinstance(attrs, Mapping):
        return None
    try:
        bound = float(attrs.get("max"))
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(bound) or bound < 0:
        return None
    return bound * scale_to_watts


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
        current_value = finite_float(state.state)
        native_value = float(watts) / scale_to_watts
    except (TypeError, ValueError, OverflowError):
        log_on_change(
            _LOGGER, f"power_control:{entity_id}", logging.WARNING,
            "Battery power control %s rejected: unreadable state or setpoint",
            entity_id,
        )
        return None
    if not all(math.isfinite(value) for value in (
        current_value, native_value, scale_to_watts,
    )):
        log_on_change(
            _LOGGER, f"power_control:{entity_id}", logging.WARNING,
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
                log_on_change(
                    _LOGGER, f"power_control:{entity_id}", logging.WARNING,
                    "Battery power control %s rejected: non-finite %s bound",
                    entity_id,
                    key,
                )
                return None
            if compare(native_value, bound):
                log_on_change(
                    _LOGGER, f"power_control:{entity_id}", logging.WARNING,
                    "Battery power control %s rejected: %.3f is outside %s=%s",
                    entity_id,
                    native_value,
                    key,
                    raw_bound,
                )
                return None

    domain = entity_id.split(".", 1)[0]
    if domain not in {"number", "input_number"}:
        log_on_change(
            _LOGGER, f"power_control:{entity_id}", logging.WARNING,
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


async def async_write_power_setpoint_verbose(
    hass,
    entity_id: str,
    watts: float,
    *,
    context: str,
    force: bool = False,
) -> tuple:
    """Validate, convert, and write a watt setpoint.

    Returns ``(ok, wrote)``: ``ok`` is success as before; ``wrote`` is True
    only when a service call actually went out. The idempotent same-value
    skip (#900/#538) is ``(True, False)`` — and that distinction is what the
    #915 read-back needs: noting a "write" that never happened re-armed its
    grace timer every cycle and no verdict could ever be reached (06.09
    audit).

    ``force`` skips the same-value check, for a caller that knows it wrote
    another value last: the entity can still show the value from before
    that write until the integration next reads it (#1175).
    """
    prepared = prepare_power_setpoint(hass, entity_id, watts)
    if prepared is None:
        return False, False
    # (#900) Idempotency for EVERY writer, not one adapter (#538 had it on
    # the Huawei path only; the generic adapter — where the wizard had pinned
    # a Huawei install — wrote its max every cycle). Compare in native units
    # to the LIVE entity state, so an external change is still re-asserted;
    # one native unit is the resolution the entity can express.
    if (not force and abs(prepared.current_value - prepared.value)
            < 1.0 / prepared.scale_to_watts):
        log_on_change(
            _LOGGER, f"setpoint-skip:{entity_id}", logging.DEBUG,
            "%s: %s already at %.3f — no write", context, entity_id, prepared.value,
        )
        return True, False
    try:
        await hass.services.async_call(
            prepared.domain,
            "set_value",
            {"entity_id": entity_id, "value": prepared.value},
            blocking=True,
        )
    except Exception as err:  # noqa: BLE001 - HA service exceptions vary
        log_on_change(
            _LOGGER, f"power_control:set:{entity_id}", logging.WARNING,
            "%s: failed to set %s: %s", context, entity_id, err,
        )
        return False, False
    return True, True


async def async_write_power_setpoint(
    hass,
    entity_id: str,
    watts: float,
    *,
    context: str,
    force: bool = False,
) -> bool:
    """Validate, convert, and write a watt setpoint. Return success."""
    ok, _wrote = await async_write_power_setpoint_verbose(
        hass, entity_id, watts, context=context, force=force)
    return ok
