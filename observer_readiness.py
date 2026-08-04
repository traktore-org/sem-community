"""Pure 72-hour observer-mode readiness countdown helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

OBSERVATION_TARGET_SECONDS = 72 * 60 * 60


def _parse_started_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def observation_progress(
    started_at: Any,
    *,
    now: datetime | None = None,
) -> dict[str, int | bool]:
    """Return a fail-closed, bounded 72-hour observation countdown."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)

    started = _parse_started_at(started_at)
    elapsed = 0 if started is None else int((current - started).total_seconds())
    elapsed = max(0, min(OBSERVATION_TARGET_SECONDS, elapsed))
    remaining = OBSERVATION_TARGET_SECONDS - elapsed

    return {
        "elapsed_seconds": elapsed,
        "remaining_seconds": remaining,
        "target_seconds": OBSERVATION_TARGET_SECONDS,
        "ready": remaining == 0,
    }
