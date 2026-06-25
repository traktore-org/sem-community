"""Coverage for ``coordinator/repair_issues.py`` + the
sensor_reader / forecast_reader / ev_taper_detector wiring.

Repair issues are the graceful-unavailability channel that replaced
the recovery-log spam (community feedback 2026-06-06). Tests pin:

1. The threshold gate — a single transient cycle does NOT raise a
   Repair; only after ``UNAVAILABLE_REPAIR_THRESHOLD_S`` of stale
   reads does the issue file.
2. Recovery clears the Repair (and reset internal latches).
3. Forecast log-once + Repair-after-1-hour behaviour.
4. Helper signatures are stable (dedup, idempotent delete).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator import (
    repair_issues as ri,
)
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.coordinator.forecast_reader import (
    ForecastReader,
)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _hass_with(states):
    """Minimal ``hass`` mock with a ``.states.get`` dispatcher."""
    h = MagicMock()
    h.states.get.side_effect = lambda eid: states.get(eid)
    return h


def _state(value, unit=None, friendly=None):
    s = MagicMock()
    s.state = value
    s.attributes = {}
    if unit:
        s.attributes["unit_of_measurement"] = unit
    if friendly:
        s.attributes["friendly_name"] = friendly
    return s


# ──────────────────────────────────────────────
# repair_issues helpers (smoke-test the wrappers)
# ──────────────────────────────────────────────


@patch("custom_components.solar_energy_management.coordinator.repair_issues.ir")
def test_raise_sensor_unavailable_calls_ir(mock_ir):
    """``raise_sensor_unavailable`` delegates to ``ir.async_create_issue``
    with the expected fields."""
    hass = MagicMock()
    ri.raise_sensor_unavailable(
        hass, "sensor.foo", friendly_name="Foo", minutes_unavailable=7
    )
    mock_ir.async_create_issue.assert_called_once()
    kwargs = mock_ir.async_create_issue.call_args.kwargs
    assert kwargs["issue_id"] == "sensor_unavailable_sensor.foo"
    assert kwargs["translation_key"] == "sensor_unavailable"
    placeholders = kwargs["translation_placeholders"]
    assert placeholders["entity_id"] == "sensor.foo"
    assert placeholders["friendly_name"] == "Foo"
    assert placeholders["minutes"] == "7"


@patch("custom_components.solar_energy_management.coordinator.repair_issues.ir")
def test_clear_sensor_unavailable_calls_delete(mock_ir):
    hass = MagicMock()
    ri.clear_sensor_unavailable(hass, "sensor.foo")
    mock_ir.async_delete_issue.assert_called_once()
    args = mock_ir.async_delete_issue.call_args.args
    assert args[2] == "sensor_unavailable_sensor.foo"


@patch("custom_components.solar_energy_management.coordinator.repair_issues.ir")
def test_clear_is_idempotent_when_ir_throws(mock_ir):
    """The wrappers never propagate exceptions — a failed
    ``async_delete_issue`` doesn't crash the coordinator cycle."""
    mock_ir.async_delete_issue.side_effect = RuntimeError("nope")
    hass = MagicMock()
    ri.clear_sensor_unavailable(hass, "sensor.foo")  # must not raise


# ──────────────────────────────────────────────
# sensor_reader integration
# ──────────────────────────────────────────────


@patch("custom_components.solar_energy_management.coordinator.repair_issues")
def test_sensor_reader_transient_flap_does_not_raise(mock_ri_module):
    """Single-cycle unavailability stays silent — the threshold is the
    whole point: a Huawei modbus blink shouldn't surface a Repair."""
    # patch the module *attribute* so the lazy import inside
    # ``_read_sensor`` picks it up.
    states = {"sensor.foo": None}  # missing → counts as unavailable
    hass = _hass_with(states)
    reader = SensorReader(hass, {})
    reader._sign_vote_warmup = 0
    # First call — sensor goes unavailable. No Repair on first miss.
    val = reader._read_sensor("sensor.foo", "test")
    assert val == 0.0
    # No Repair raised yet; only the timestamp was stamped.
    assert "sensor.foo" in reader._sensor_unavailable_since
    assert "sensor.foo" not in reader._sensor_repair_raised


@patch("custom_components.solar_energy_management.coordinator.repair_issues")
def test_sensor_reader_raises_after_threshold(mock_ri_module):
    """Once the outage clock exceeds the threshold, ``raise_sensor_unavailable``
    is called exactly once for that outage."""
    mock_ri_module.UNAVAILABLE_REPAIR_THRESHOLD_S = 300
    raise_calls = []
    mock_ri_module.raise_sensor_unavailable.side_effect = (
        lambda h, eid, friendly_name=None, minutes_unavailable=0:
        raise_calls.append((eid, minutes_unavailable))
    )

    states = {"sensor.foo": _state("unavailable", friendly="Foo Sensor")}
    hass = _hass_with(states)
    reader = SensorReader(hass, {})
    reader._sign_vote_warmup = 0

    # First read → stamps the outage start.
    with patch("time.monotonic", return_value=1000.0):
        reader._read_sensor("sensor.foo", "test")
    # Second read 301 s later → escalates to Repair.
    with patch("time.monotonic", return_value=1301.0):
        reader._read_sensor("sensor.foo", "test")
    assert len(raise_calls) == 1
    eid, mins = raise_calls[0]
    assert eid == "sensor.foo"
    assert mins == 5  # 301 s // 60

    # Third read 600 s later → does NOT re-raise (latched).
    with patch("time.monotonic", return_value=1600.0):
        reader._read_sensor("sensor.foo", "test")
    assert len(raise_calls) == 1


@patch("custom_components.solar_energy_management.coordinator.repair_issues")
def test_sensor_reader_clears_repair_on_recovery(mock_ri_module):
    """Sensor coming back resets the outage clock AND clears the Repair."""
    mock_ri_module.UNAVAILABLE_REPAIR_THRESHOLD_S = 300
    cleared = []
    mock_ri_module.clear_sensor_unavailable.side_effect = (
        lambda h, eid: cleared.append(eid)
    )

    # Sensor unavailable, then recovers.
    states = {"sensor.foo": _state("unavailable")}
    hass = _hass_with(states)
    reader = SensorReader(hass, {})
    reader._sign_vote_warmup = 0

    with patch("time.monotonic", return_value=1000.0):
        reader._read_sensor("sensor.foo", "test")
    with patch("time.monotonic", return_value=1301.0):
        reader._read_sensor("sensor.foo", "test")
    # Now flip to available.
    states["sensor.foo"] = _state("42.0")
    with patch("time.monotonic", return_value=1400.0):
        val = reader._read_sensor("sensor.foo", "test")
    assert val == 42.0
    assert cleared == ["sensor.foo"]
    assert "sensor.foo" not in reader._sensor_unavailable_since
    assert "sensor.foo" not in reader._sensor_repair_raised


# ──────────────────────────────────────────────
# forecast_reader log-once gate
# ──────────────────────────────────────────────


@patch("custom_components.solar_energy_management.coordinator.repair_issues")
def test_forecast_reader_logs_once_per_outage(mock_ri_module, caplog):
    """Pre-fix: ``detect_source`` logged INFO every cycle when no
    integration was found. Post-fix: log once, Repair after 1h."""
    import logging

    states = {}  # no forecast entities anywhere
    hass = _hass_with(states)
    reader = ForecastReader(hass)

    # Five consecutive misses — only one INFO log.
    with caplog.at_level(logging.INFO, logger=(
        "custom_components.solar_energy_management.coordinator.forecast_reader"
    )):
        for _ in range(5):
            reader.detect_source()
    no_forecast_msgs = [
        r for r in caplog.records
        if "No solar forecast integration detected" in r.message
    ]
    assert len(no_forecast_msgs) == 1, (
        f"expected single log, got {len(no_forecast_msgs)}"
    )
    assert reader._no_forecast_logged is True
    assert reader._no_forecast_since_mono is not None
    # Repair not yet raised — under the 1h threshold.
    assert reader._no_forecast_repair_raised is False
    mock_ri_module.raise_no_forecast_integration.assert_not_called()


@patch("custom_components.solar_energy_management.coordinator.repair_issues")
def test_forecast_reader_raises_repair_after_threshold(mock_ri_module):
    """After 1 hour of detection failure, file a Repair (once)."""
    states = {}
    hass = _hass_with(states)
    reader = ForecastReader(hass)

    # First call → log + stamp; no Repair yet.
    reader._mono_time = lambda: 0.0
    reader.detect_source()
    assert reader._no_forecast_repair_raised is False

    # Jump 1 hour 1 second → Repair fires.
    reader._mono_time = lambda: 3601.0
    reader.detect_source()
    assert reader._no_forecast_repair_raised is True
    mock_ri_module.raise_no_forecast_integration.assert_called_once_with(hass)

    # Another call later → still only one Repair (latched).
    reader._mono_time = lambda: 7200.0
    reader.detect_source()
    mock_ri_module.raise_no_forecast_integration.assert_called_once()

# ──────────────────────────────────────────────
# #526 — SOC-cap-unenforceable repair
# ──────────────────────────────────────────────


def test_raise_soc_cap_unenforceable_creates_issue():
    hass = MagicMock()
    with patch.object(ri.ir, "async_create_issue") as create:
        ri.raise_soc_cap_unenforceable(hass, "ev_charger", name="Laadpaal Links", target_soc=80.0)
    assert create.called
    kwargs = create.call_args.kwargs
    assert kwargs["issue_id"] == "soc_cap_unenforceable_ev_charger"
    assert kwargs["translation_key"] == "soc_cap_unenforceable"
    assert kwargs["translation_placeholders"] == {"name": "Laadpaal Links", "target": "80"}
    assert kwargs["severity"] is ri.ir.IssueSeverity.WARNING


def test_clear_soc_cap_unenforceable_deletes_issue():
    hass = MagicMock()
    with patch.object(ri.ir, "async_delete_issue") as delete:
        ri.clear_soc_cap_unenforceable(hass, "ev_charger")
    delete.assert_called_once_with(hass, ri.DOMAIN, "soc_cap_unenforceable_ev_charger")


# ──────────────────────────────────────────────
# #546 — KEBA failsafe-active repair
# ──────────────────────────────────────────────


def test_raise_keba_failsafe_active_creates_issue():
    hass = MagicMock()
    with patch.object(ri.ir, "async_create_issue") as create:
        ri.raise_keba_failsafe_active(hass, charger_name="KEBA P30")
    assert create.called
    kwargs = create.call_args.kwargs
    assert kwargs["issue_id"] == "keba_failsafe_active"
    assert kwargs["translation_key"] == "keba_failsafe_active"
    assert kwargs["translation_placeholders"] == {"name": "KEBA P30"}
    assert kwargs["severity"] is ri.ir.IssueSeverity.WARNING
    assert kwargs["learn_more_url"] == ri.KEBA_FAILSAFE_DOC_URL


def test_clear_keba_failsafe_active_deletes_issue():
    hass = MagicMock()
    with patch.object(ri.ir, "async_delete_issue") as delete:
        ri.clear_keba_failsafe_active(hass)
    delete.assert_called_once_with(hass, ri.DOMAIN, "keba_failsafe_active")


def _fs_state(entity_id, state):
    s = MagicMock()
    s.entity_id = entity_id
    s.state = state
    return s


def test_detect_keba_failsafe_state_on_off_none():
    hass = MagicMock()
    # ON
    hass.states.async_all.return_value = [
        _fs_state("binary_sensor.keba_p30_failsafe_mode", "on"),
    ]
    assert ri.detect_keba_failsafe_state(hass) is True
    # OFF
    hass.states.async_all.return_value = [
        _fs_state("binary_sensor.keba_p30_failsafe_mode", "off"),
    ]
    assert ri.detect_keba_failsafe_state(hass) is False
    # No failsafe sensor → None (can't tell, stay silent)
    hass.states.async_all.return_value = [
        _fs_state("binary_sensor.keba_p30_plug", "on"),
    ]
    assert ri.detect_keba_failsafe_state(hass) is None
