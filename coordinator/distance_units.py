"""Distance-unit normalisation for vehicle range diagnostics."""
from __future__ import annotations

import math
from typing import Any, Optional


_KM_UNITS = {"km", "kilometer", "kilometers", "kilometre", "kilometres"}
_M_UNITS = {"m", "meter", "meters", "metre", "metres"}
_MI_UNITS = {"mi", "mile", "miles"}


def distance_to_km(value: Any, unit: Any) -> Optional[float]:
    """Convert a length value to kilometres, or ``None`` fail-closed.

    Home Assistant entities do not guarantee a unit. Treating an unknown unit
    as kilometres can inflate a metre-based vehicle range by ×1000, so unknown,
    non-finite and negative values are deliberately rejected.
    """
    if unit is None:
        return None
    normalized = str(unit).strip().lower()
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric < 0:
        return None

    if normalized in _KM_UNITS:
        return numeric
    if normalized in _M_UNITS:
        return numeric / 1000.0
    if normalized in _MI_UNITS:
        return numeric * 1.609344
    return None
