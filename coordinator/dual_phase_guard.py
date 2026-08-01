"""Observer-only dual per-phase guard for Grid and Inverter/Load lanes.

The module is intentionally pure/read-only: it only reads HA states and returns
structured diagnostics. It never calls a Home Assistant service or charger.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.util import dt as dt_util

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

    unit = str(
        getattr(state, "attributes", {}).get("unit_of_measurement", "")
    ).strip().lower()
    if unit != expected_unit.lower():
        return None, "invalid_unit"

    last_updated = getattr(state, "last_updated", None)
    if last_updated is None:
        return None, "missing_timestamp"
    try:
        age = (dt_util.utcnow() - last_updated).total_seconds()
    except (TypeError, ValueError):
        return None, "invalid_timestamp"
    if age < -5 or age > max_age_s:
        return None, "stale"

    try:
        value = float(raw)
    except (TypeError, ValueError):
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
    """Evaluate two independent L1-L3 16 A guards without actuating.

    Grid current is ``abs(power_w / voltage_v)`` so export is protected too.
    Inverter/Load current is read directly from the configured non-negative RMS
    current entities.
    """
    topology = str(config.get("phase_guard_topology", "hybrid_load_port"))
    invalid_configuration = False
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
        for phase in range(1, 4)
    )
    if configured_grid_currents not in {0, 3}:
        invalid_configuration = True

    result: Dict[str, Any] = {
        "mode": "observer",
        "topology": topology,
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

    for phase in range(1, 4):
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
