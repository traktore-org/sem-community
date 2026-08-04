"""Conservative discovery of direct per-phase grid current sensors.

The radio or field-bus transport is intentionally outside this module. Home
Assistant integrations expose the usable sensor entities; this helper only
accepts one unambiguous family containing every configured phase.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any

_BAD_STATES = {"", "none", "unknown", "unavailable"}
_EXCLUDED_TOKENS = ("battery", "charger", "ev_", "load", "output", "pv", "solar")
_GRID_TOKENS = ("grid", "mains", "smart_meter")
_PHASE_PATTERNS = (
    re.compile(r"(?<![a-z0-9])l([123])(?=_|$)"),
    re.compile(r"(?<![a-z0-9])phase_?([123])(?=_|$)"),
    re.compile(r"(?<![a-z0-9])line_?([123])(?=_|$)"),
)


def _candidate(state: Any) -> tuple[str, int, str] | None:
    entity_id = str(getattr(state, "entity_id", "")).lower()
    if not entity_id.startswith("sensor.") or "current" not in entity_id:
        return None
    if not any(token in entity_id for token in _GRID_TOKENS):
        return None
    if any(token in entity_id for token in _EXCLUDED_TOKENS):
        return None

    attributes = getattr(state, "attributes", {}) or {}
    if str(attributes.get("unit_of_measurement", "")).strip().lower() != "a":
        return None
    raw = str(getattr(state, "state", "")).strip().lower()
    if raw in _BAD_STATES:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value < 0:
        return None

    for pattern in _PHASE_PATTERNS:
        match = pattern.search(entity_id)
        if match:
            phase = int(match.group(1))
            family = entity_id[: match.start()] + "{phase}" + entity_id[match.end() :]
            return family, phase, entity_id
    return None


def discover_grid_phase_current_entities(
    states: Iterable[Any], phase_count: int = 3
) -> dict[str, str]:
    """Return one unambiguous family containing all configured phases."""
    if isinstance(phase_count, bool) or phase_count not in {1, 3}:
        return {}
    required_phases = set(range(1, phase_count + 1))
    families: dict[str, dict[int, str]] = {}
    for state in states:
        candidate = _candidate(state)
        if candidate is None:
            continue
        family, phase, entity_id = candidate
        phases = families.setdefault(family, {})
        if phase in phases and phases[phase] != entity_id:
            return {}
        phases[phase] = entity_id

    complete = [
        phases for phases in families.values() if required_phases.issubset(phases)
    ]
    if len(complete) != 1:
        return {}
    phases = complete[0]
    return {
        f"phase_guard_grid_l{phase}_current_entity": phases[phase]
        for phase in range(1, phase_count + 1)
    }
