"""Observer-only dual per-phase guard for Grid and Inverter/Load lanes.

The module is intentionally pure/read-only: it only reads HA states and returns
structured diagnostics. It never calls a Home Assistant service or charger.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfPower
from homeassistant.util import dt as dt_util

from .units import is_power_unit, power_state_to_watts

_BAD_STATES = {STATE_UNKNOWN, STATE_UNAVAILABLE, "none", "None", ""}


def _read_number(
    states,
    entity_id: Optional[str],
    *,
    max_age_s: float,
    expected_unit: str,
) -> Tuple[Optional[float], Optional[str]]:
    if not entity_id:
        return None, "not_configured"
    state = states.get(entity_id)
    if state is None:
        return None, "missing"
    raw = getattr(state, "state", None)
    if raw in _BAD_STATES or str(raw).lower() in {"unknown", "unavailable", "none", ""}:
        return None, str(raw).lower() if raw is not None else "missing"

    attributes = getattr(state, "attributes", {}) or {}
    unit = str(attributes.get("unit_of_measurement", "")).strip().lower()
    is_power = expected_unit == UnitOfPower.WATT
    if is_power:
        # The shared converter also supports a historical unitless-as-watts
        # fallback. A safety gate must be stricter: only an explicit power unit
        # is accepted, then the canonical converter normalizes it to watts.
        if not is_power_unit(state):
            return None, "invalid_unit"
    elif unit != str(expected_unit).strip().lower():
        return None, "invalid_unit"

    # Freshness comes from last_REPORTED, not last_updated: HA only moves
    # last_updated when the value or attributes actually CHANGE, while a
    # healthy sensor holding a flat reading (grid voltage rounding to 230
    # for minutes, a quiet phase at exactly 0 W all night) keeps
    # re-reporting the same value — bumping only last_reported. Keying on
    # last_updated declared exactly those healthy-but-flat sensors stale
    # and failed the guard closed on a healthy install (caught live on the
    # HA-TEST rig). last_updated stays as the fallback for cores without
    # last_reported.
    reported = (
        getattr(state, "last_reported", None)
        or getattr(state, "last_updated", None)
    )
    if reported is None:
        return None, "missing_timestamp"
    try:
        age = (dt_util.utcnow() - reported).total_seconds()
    except (TypeError, ValueError):
        return None, "invalid_timestamp"
    if age < -5 or age > max_age_s:
        return None, "stale"

    if is_power:
        value = power_state_to_watts(state, default=None)
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None, "non_numeric"
    if value is None:
        return None, "non_numeric"
    if not math.isfinite(value):
        return None, "non_numeric"
    return value, None


def _unsafe_phase(reason: str, limit_a: float, *, source: str | None = None) -> Dict[str, Any]:
    return {
        "current_a": None,
        "margin_a": None,
        "limit_a": limit_a,
        "safe": False,
        "data_fresh": False,
        "reason": reason,
        "source": source,
    }


def _phase_result(
    current_a: float, limit_a: float, *, source: str | None = None
) -> Dict[str, Any]:
    safe = current_a <= limit_a
    return {
        "current_a": round(current_a, 3),
        "margin_a": round(limit_a - current_a, 3),
        "limit_a": limit_a,
        "safe": safe,
        "data_fresh": True,
        "reason": None if safe else "over_limit",
        "source": source,
    }


def evaluate_dual_phase_guard(states, config: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate independent one- or three-phase guards without actuating.

    Grid current is ``abs(power_w / voltage_v)`` so export is protected too.
    Inverter/Load current is read directly from the configured non-negative RMS
    current entities.
    """
    topology = str(config.get("phase_guard_topology", "hybrid_load_port"))
    invalid_configuration = False
    phase_count: Optional[int] = None
    raw_phase_count = config.get("phase_guard_phase_count", 3)
    try:
        numeric_phase_count = float(raw_phase_count)
        if (
            isinstance(raw_phase_count, bool)
            or not math.isfinite(numeric_phase_count)
            or not numeric_phase_count.is_integer()
        ):
            raise ValueError
        phase_count = int(numeric_phase_count)
    except (TypeError, ValueError):
        invalid_configuration = True
    if phase_count not in {1, 3}:
        invalid_configuration = True
    required_phases = range(1, (phase_count or 3) + 1)
    try:
        grid_limit = float(config.get("phase_guard_grid_limit_a", 16))
        inverter_limit = float(config.get("phase_guard_inverter_limit_a", 16))
        max_age = float(config.get("phase_guard_max_age_s", 30))
    except (TypeError, ValueError):
        grid_limit = inverter_limit = 16.0
        max_age = 30.0
        invalid_configuration = True
    if (
        not all(math.isfinite(value) for value in (grid_limit, inverter_limit, max_age))
        or grid_limit <= 0
        or inverter_limit <= 0
        or max_age <= 0
    ):
        invalid_configuration = True
    configured_grid_currents = sum(
        bool(config.get(f"phase_guard_grid_l{phase}_current_entity"))
        for phase in required_phases
    )
    if configured_grid_currents not in {0, phase_count}:
        invalid_configuration = True

    result: Dict[str, Any] = {
        "mode": "observer",
        "topology": topology,
        "phase_count": phase_count,
        "read_only": True,
        "safe": True,
        "data_fresh": True,
        "stop_reason": "",
        "grid": {},
        "inverter": {},
    }
    reasons = []

    if invalid_configuration:
        result["safe"] = False
        result["data_fresh"] = False
        result["stop_reason"] = "invalid_configuration"
        return result

    if topology not in {"grid_only", "hybrid_load_port"}:
        result["safe"] = False
        result["data_fresh"] = False
        result["stop_reason"] = "unsupported_topology"
        return result

    include_inverter = topology == "hybrid_load_port"

    for phase in required_phases:
        key = f"l{phase}"
        direct_current_entity = config.get(
            f"phase_guard_grid_l{phase}_current_entity"
        )
        if direct_current_entity:
            current, current_error = _read_number(
                states,
                direct_current_entity,
                max_age_s=max_age,
                expected_unit="A",
            )
            if current_error:
                lane = _unsafe_phase(
                    current_error, grid_limit, source="direct_current"
                )
            elif current is None or current < 0:
                lane = _unsafe_phase(
                    "invalid_current", grid_limit, source="direct_current"
                )
            else:
                lane = _phase_result(
                    current, grid_limit, source="direct_current"
                )
        else:
            power, power_error = _read_number(
                states,
                config.get(f"phase_guard_grid_l{phase}_power_entity"),
                max_age_s=max_age,
                expected_unit="W",
            )
            voltage, voltage_error = _read_number(
                states,
                config.get(f"phase_guard_grid_l{phase}_voltage_entity"),
                max_age_s=max_age,
                expected_unit="V",
            )
            if power_error:
                lane = _unsafe_phase(
                    power_error, grid_limit, source="derived_power_voltage"
                )
            elif voltage_error:
                lane = _unsafe_phase(
                    voltage_error, grid_limit, source="derived_power_voltage"
                )
            elif power is None:
                lane = _unsafe_phase(
                    "invalid_power", grid_limit, source="derived_power_voltage"
                )
            elif voltage is None or voltage <= 0:
                lane = _unsafe_phase(
                    "invalid_voltage", grid_limit, source="derived_power_voltage"
                )
            else:
                lane = _phase_result(
                    abs(power) / voltage,
                    grid_limit,
                    source="derived_power_voltage",
                )
        result["grid"][key] = lane
        if not lane["safe"]:
            reasons.append(f"grid:{key}:{lane['reason']}")

        if include_inverter:
            current, current_error = _read_number(
                states,
                config.get(f"phase_guard_inverter_l{phase}_current_entity"),
                max_age_s=max_age,
                expected_unit="A",
            )
            if current_error:
                inv = _unsafe_phase(current_error, inverter_limit)
            elif current is None or current < 0:
                # RMS current cannot be negative. Treat a signed or corrupt
                # sensor as invalid rather than turning it into false margin.
                inv = _unsafe_phase("invalid_current", inverter_limit)
            else:
                inv = _phase_result(current, inverter_limit)
            result["inverter"][key] = inv
            if not inv["safe"]:
                reasons.append(f"inverter:{key}:{inv['reason']}")

    result["safe"] = not reasons
    result["data_fresh"] = all(
        phase["data_fresh"]
        for lane in (result["grid"], result["inverter"])
        for phase in lane.values()
    )
    result["stop_reason"] = ",".join(reasons)
    return result
