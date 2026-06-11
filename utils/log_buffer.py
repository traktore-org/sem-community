"""In-memory ring buffer of SEM log records for the diagnose surface.

Supervisor installs route Home Assistant's log to journald — there is no
flat ``home-assistant.log`` to tail, so the diagnose payload's
``recent_logs`` was a "please run `ha core logs`" placeholder on exactly
the installs that report bugs most (the entire #461/#462 triage ran
without log visibility). A ``logging.Handler`` attached to the
integration's root logger captures every SEM record regardless of where
HA routes its output: child loggers (``…solar_energy_management.coordinator
.sensor_reader`` etc.) propagate to the ancestor logger, whose handlers
see the records.

INFO and above only — DEBUG would balloon the dump and the diagnose
surface targets "what was SEM doing around the incident", not tracing.
"""
from __future__ import annotations

import logging
from collections import deque

SEM_LOGGER_NAME = "custom_components.solar_energy_management"

_FORMAT = "%(asctime)s %(levelname)s (%(name)s) %(message)s"


class SEMLogBuffer(logging.Handler):
    """Ring buffer handler — keeps the last ``capacity`` formatted lines."""

    def __init__(self, capacity: int = 300) -> None:
        super().__init__(level=logging.INFO)
        self._lines: deque[str] = deque(maxlen=capacity)
        self.setFormatter(logging.Formatter(_FORMAT))

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        try:
            self._lines.append(self.format(record))
        except Exception:  # noqa: BLE001 — a log handler must never raise
            pass

    def get_lines(self, count: int = 80) -> list[str]:
        """Return up to the last ``count`` captured lines, oldest first."""
        return list(self._lines)[-count:]


def ensure_attached() -> SEMLogBuffer:
    """Attach (or reuse) the buffer on the integration's root logger.

    Idempotent across reloads — the logger object is module-global and
    survives config-entry teardown, so a second setup finds and reuses
    the existing handler instead of stacking duplicates.
    """
    logger = logging.getLogger(SEM_LOGGER_NAME)
    for handler in logger.handlers:
        if isinstance(handler, SEMLogBuffer):
            return handler
    buffer = SEMLogBuffer()
    logger.addHandler(buffer)
    return buffer
