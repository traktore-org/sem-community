"""SEM log ring buffer (#461/#462 triage gap on Supervisor installs)."""
from __future__ import annotations

import logging

import pytest

from custom_components.solar_energy_management.utils.log_buffer import (
    SEM_LOGGER_NAME,
    SEMLogBuffer,
    ensure_attached,
)


@pytest.fixture
def clean_logger():
    """Detach any buffers the tests (or prior tests) attached."""
    logger = logging.getLogger(SEM_LOGGER_NAME)
    yield logger
    for handler in list(logger.handlers):
        if isinstance(handler, SEMLogBuffer):
            logger.removeHandler(handler)


@pytest.mark.unit
class TestLogBuffer:
    def test_child_logger_records_are_captured(self, clean_logger):
        buf = ensure_attached()
        child = logging.getLogger(f"{SEM_LOGGER_NAME}.coordinator.sensor_reader")
        child.warning("Manual grid power entities CONTRADICT the counters")
        lines = buf.get_lines()
        assert len(lines) == 1
        assert "CONTRADICT" in lines[0]
        assert "WARNING" in lines[0]
        assert "sensor_reader" in lines[0]

    def test_debug_records_are_excluded(self, clean_logger):
        buf = ensure_attached()
        child = logging.getLogger(f"{SEM_LOGGER_NAME}.coordinator")
        child.setLevel(logging.DEBUG)
        child.debug("noisy per-cycle detail")
        child.info("worth keeping")
        lines = buf.get_lines()
        assert len(lines) == 1
        assert "worth keeping" in lines[0]

    def test_capacity_is_bounded_and_tail_ordered(self, clean_logger):
        buf = SEMLogBuffer(capacity=5)
        logging.getLogger(SEM_LOGGER_NAME).addHandler(buf)
        log = logging.getLogger(f"{SEM_LOGGER_NAME}.x")
        for i in range(12):
            log.info("line %d", i)
        lines = buf.get_lines(count=3)
        assert len(lines) == 3
        assert lines[-1].endswith("line 11")
        assert lines[0].endswith("line 9")

    def test_ensure_attached_is_idempotent(self, clean_logger):
        first = ensure_attached()
        second = ensure_attached()
        assert first is second
        buffers = [
            h for h in clean_logger.handlers if isinstance(h, SEMLogBuffer)
        ]
        assert len(buffers) == 1

    def test_handler_never_raises_on_bad_record(self, clean_logger):
        """Mismatched format args raise inside Formatter — emit swallows.

        Exercises ``emit`` directly: routing through the logger would ALSO
        hit pytest's own capture handler, which deliberately re-raises
        formatting errors and would fail the test for the wrong reason.
        """
        buf = ensure_attached()
        record = logging.LogRecord(
            name=f"{SEM_LOGGER_NAME}.bad", level=logging.INFO,
            pathname=__file__, lineno=1,
            msg="only %s and %s", args=("one-arg",), exc_info=None,
        )
        buf.emit(record)  # must not raise
        assert isinstance(buf.get_lines(), list)


@pytest.mark.unit
class TestDiagnosticsPrefersBuffer:
    @pytest.mark.asyncio
    async def test_recent_logs_served_from_buffer(self, clean_logger):
        from unittest.mock import MagicMock
        from custom_components.solar_energy_management.const import DOMAIN
        from custom_components.solar_energy_management.diagnostics import (
            _get_recent_sem_logs,
        )

        buf = ensure_attached()
        logging.getLogger(f"{SEM_LOGGER_NAME}.coordinator").info("buffered line")

        hass = MagicMock()
        hass.data = {f"{DOMAIN}_log_buffer": buf}
        out = await _get_recent_sem_logs(hass)
        assert out == buf.get_lines()
        assert any("buffered line" in line for line in out)

    @pytest.mark.asyncio
    async def test_empty_buffer_reports_itself(self, clean_logger):
        from unittest.mock import MagicMock
        from custom_components.solar_energy_management.const import DOMAIN
        from custom_components.solar_energy_management.diagnostics import (
            _get_recent_sem_logs,
        )

        hass = MagicMock()
        hass.data = {f"{DOMAIN}_log_buffer": ensure_attached()}
        out = await _get_recent_sem_logs(hass)
        assert out == ["<no SEM log records captured since startup>"]
