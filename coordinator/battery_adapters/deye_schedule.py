"""Pure, deterministic compiler for Deye's six-slot TOU schedule.

This module has no Home Assistant side effects.  It validates Deye's six
ordered daily boundaries, derives the active slot from an aware local time,
and compiles a bounded charge window into the exact slots that overlap it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
import math
from typing import Iterable

_PROGRAM_COUNT = 6
_SECONDS_PER_DAY = 24 * 60 * 60


class DeyeScheduleError(ValueError):
    """Raised when a Deye schedule cannot be compiled safely."""


@dataclass(frozen=True)
class DeyeChargeWindowPlan:
    """Validated slot updates for one temporary grid-charge window."""

    slot_indices: tuple[int, ...]  # one-based Deye program numbers
    reserve_soc: float
    charging_source: str = "Grid"


def _boundary_seconds(value: str) -> int:
    if not isinstance(value, str) or not value.strip():
        raise DeyeScheduleError("program boundary must be a non-empty string")
    try:
        parsed = time.fromisoformat(value.strip())
    except ValueError as err:
        raise DeyeScheduleError(f"invalid program boundary {value!r}") from err
    if parsed.tzinfo is not None:
        raise DeyeScheduleError("program boundaries must be local wall-clock times")
    return parsed.hour * 3600 + parsed.minute * 60 + parsed.second


def validate_deye_boundaries(values: Iterable[str]) -> tuple[int, ...]:
    """Return six strictly increasing boundary seconds or fail closed."""

    raw = tuple(values)
    if len(raw) != _PROGRAM_COUNT:
        raise DeyeScheduleError(
            f"Deye schedule requires exactly {_PROGRAM_COUNT} boundaries"
        )
    boundaries = tuple(_boundary_seconds(value) for value in raw)
    if len(set(boundaries)) != _PROGRAM_COUNT:
        raise DeyeScheduleError("Deye program boundaries must be unique")
    if any(left >= right for left, right in zip(boundaries, boundaries[1:])):
        raise DeyeScheduleError("Deye program boundaries must be strictly increasing")
    return boundaries


def _aware_seconds(now: datetime) -> int:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise DeyeScheduleError("current time must be timezone-aware")
    return now.hour * 3600 + now.minute * 60 + now.second


# (#758) ``active_deye_slot`` stood here — "which of the six programs is
# running right now", validated, wrap-aware, three tests, and no caller in
# the shipped integration. The adapter never needs it: it compiles a window
# into the slots that OVERLAP it (below) rather than asking which one is
# current. Deleted rather than baselined — the #653 rule is wire it, delete
# it, or say why it stays, and there was nothing to wire it to. Found by the
# orphan guard the moment that guard learned to look at module scope.


def compile_deye_charge_window(
    values: Iterable[str],
    now: datetime,
    duration_min: int,
    reserve_soc: float,
) -> DeyeChargeWindowPlan:
    """Compile a temporary window into only the overlapping Deye slots.

    The window starts at ``now`` and may cross midnight.  Durations longer
    than one day are rejected: a temporary dispatch must never silently
    rewrite a whole recurring daily schedule.
    """

    boundaries = validate_deye_boundaries(values)
    start = _aware_seconds(now)
    if isinstance(duration_min, bool) or isinstance(reserve_soc, bool):
        raise DeyeScheduleError("duration and reserve SOC must be numeric, not boolean")
    try:
        duration = int(duration_min)
        target = float(reserve_soc)
    except (TypeError, ValueError, OverflowError) as err:
        raise DeyeScheduleError("duration and reserve SOC must be numeric") from err
    if duration != duration_min or not 1 <= duration <= 24 * 60:
        raise DeyeScheduleError("duration must be between 1 and 1440 whole minutes")
    if not math.isfinite(target) or not 0 <= target <= 100:
        raise DeyeScheduleError("reserve SOC must be finite and within 0-100")

    window_start = start
    window_end = start + duration * 60
    selected: list[int] = []
    for index, slot_start in enumerate(boundaries):
        slot_end = (
            boundaries[index + 1]
            if index + 1 < _PROGRAM_COUNT
            else boundaries[0] + _SECONDS_PER_DAY
        )
        # Compare two adjacent daily copies so both the pre-first-boundary
        # (slot 6) region and a window crossing midnight are represented.
        overlaps = False
        for day_shift in (-_SECONDS_PER_DAY, 0, _SECONDS_PER_DAY):
            left = slot_start + day_shift
            right = slot_end + day_shift
            if max(window_start, left) < min(window_end, right):
                overlaps = True
                break
        if overlaps:
            selected.append(index + 1)

    if not selected:
        raise DeyeScheduleError("charge window does not overlap a valid Deye slot")
    return DeyeChargeWindowPlan(tuple(selected), target)
