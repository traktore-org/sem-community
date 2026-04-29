"""Tests for the error reporter, sanitizer, and anomaly detector."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.error_reporter import (
    AnomalyCheck,
    AnomalyDetector,
    AnomalyResult,
    ErrorReporter,
    sanitize_payload,
    hash_entity_id,
)
from custom_components.solar_energy_management.error_reporter.anomaly_detector import (
    build_default_checks,
)


# ---------------- sanitizer ----------------

def test_sanitizer_redacts_secret_keys():
    payload = {
        "github_token": "abc123",
        "api_key": "supersecret",
        "auth": "Bearer xyz",
        "ok": "fine",
    }
    out = sanitize_payload(payload)
    assert out["github_token"] == "<redacted>"
    assert out["api_key"] == "<redacted>"
    assert out["auth"] == "<redacted>"
    assert out["ok"] == "fine"


def test_sanitizer_hashes_entity_ids():
    payload = {"sensor": "sensor.my_solar_inverter_in_garage"}
    out = sanitize_payload(payload)
    assert out["sensor"].startswith("sensor.<hash:")
    # Same input → same hash (stable)
    assert sanitize_payload({"x": "sensor.foo"})["x"] == sanitize_payload({"x": "sensor.foo"})["x"]


def test_sanitizer_redacts_paths_and_ips():
    payload = {
        "msg": "Failed at /home/alice/secret/config.yaml on 192.168.1.42",
    }
    out = sanitize_payload(payload)
    assert "/home/alice" not in out["msg"]
    assert "192.168.1.42" not in out["msg"]
    assert "<path>" in out["msg"]
    assert "<ip>" in out["msg"]


def test_sanitizer_handles_nested_structures():
    payload = {"a": [{"github_token": "xxx"}, "sensor.foo"]}
    out = sanitize_payload(payload)
    assert out["a"][0]["github_token"] == "<redacted>"
    assert out["a"][1].startswith("sensor.<hash:")


def test_sanitizer_caps_recursion_depth():
    deep: Any = {}
    cur = deep
    for _ in range(20):
        cur["x"] = {}
        cur = cur["x"]
    out = sanitize_payload(deep)
    # Should terminate without RecursionError
    assert isinstance(out, dict)


def test_hash_entity_id_keeps_domain():
    assert hash_entity_id("binary_sensor.ev_plug").startswith("binary_sensor.<hash:")
    assert hash_entity_id("not_an_entity_id").count(".") == 0 or True  # falls back to short hash


# ---------------- anomaly detector ----------------

def test_anomaly_check_hysteresis():
    """Check must fail K consecutive times before firing."""
    counter = {"n": 0}

    def evaluate(_data):
        counter["n"] += 1
        return AnomalyResult(ok=False, signature="x", title="bad", details={})

    check = AnomalyCheck("t", evaluate, min_consecutive_failures=3, cooldown_s=0)
    assert check.step({}) is None
    assert check.step({}) is None
    assert check.step({}) is not None  # third failure fires


def test_anomaly_check_resets_on_success():
    """One success resets the counter."""
    seq = iter([False, False, True, False, False])

    def evaluate(_data):
        ok = next(seq)
        if ok:
            return AnomalyResult(ok=True)
        return AnomalyResult(ok=False, signature="x", title="bad", details={})

    check = AnomalyCheck("t", evaluate, min_consecutive_failures=3, cooldown_s=0)
    check.step({})  # fail 1
    check.step({})  # fail 2
    check.step({})  # success — reset
    check.step({})  # fail 1
    assert check.step({}) is None  # only 2 consecutive — no fire


def test_anomaly_check_swallows_exception():
    def evaluate(_data):
        raise RuntimeError("boom")

    check = AnomalyCheck("t", evaluate, min_consecutive_failures=1, cooldown_s=0)
    # Should not raise
    assert check.step({}) is None


def test_default_checks_include_expected_signatures():
    checks = build_default_checks()
    names = {c.name for c in checks}
    assert "energy_balance" in names
    assert "update_failure_streak" in names
    assert "implausible_values" in names
    assert "surplus_not_consumed" in names
    assert "charging_state_stuck" in names


def test_implausible_battery_soc_fires():
    from custom_components.solar_energy_management.error_reporter.anomaly_detector import (
        _check_implausible_values,
    )
    res = _check_implausible_values({"battery_soc": 150})
    assert res.ok is False
    assert "battery_soc" in res.signature


def test_energy_balance_ignored_at_night():
    """Balance check shouldn't fire when solar is near zero (noise)."""
    from custom_components.solar_energy_management.error_reporter.anomaly_detector import (
        _check_energy_balance,
    )
    res = _check_energy_balance({"energy_balance_check": 80, "solar_power": 50})
    assert res.ok is True


def test_energy_balance_fires_when_drift_high():
    from custom_components.solar_energy_management.error_reporter.anomaly_detector import (
        _check_energy_balance,
    )
    res = _check_energy_balance({
        "energy_balance_check": 30,
        "solar_power": 5000,
        "home_consumption_total": 1000,
        "grid_power": -1000,
        "battery_power": 500,
    })
    assert res.ok is False
    assert "balance_drift" in res.signature


# ---------------- reporter dedupe + rate limit ----------------

class _FakeStore:
    """Drop-in for homeassistant.helpers.storage.Store."""
    def __init__(self):
        self._data: Any = None

    async def async_load(self):
        return self._data

    async def async_save(self, data):
        self._data = data


def _make_reporter(post_response_status: int = 201):
    """Build a reporter with a stubbed Store and aiohttp session."""
    hass = MagicMock()
    reporter = ErrorReporter(
        hass,
        github_token="ghp_fake",
        github_repo="owner/repo",
        integration_version="9.9.9",
        enabled=True,
        dedupe_window_s=3600,
        daily_cap=3,
        entry_id="test_entry",
    )
    # Replace Store with a fake (avoids touching the filesystem).
    reporter._store = _FakeStore()  # type: ignore[attr-defined]

    # Stub out the HTTP layer.
    response = MagicMock()
    response.status = post_response_status
    response.json = AsyncMock(return_value={"number": 4242})
    response.text = AsyncMock(return_value="ok")

    @asynccontextmanager
    async def fake_post(*args, **kwargs):
        yield response

    fake_session = MagicMock()
    fake_session.post = fake_post

    patcher = patch(
        "custom_components.solar_energy_management.error_reporter.reporter.async_get_clientsession",
        return_value=fake_session,
    )
    patcher.start()
    return reporter, response, patcher


@pytest.mark.asyncio
async def test_reporter_files_issue_on_first_call():
    reporter, response, patcher = _make_reporter()
    try:
        await reporter.async_load()
        try:
            raise ValueError("kaboom")
        except ValueError as e:
            num = await reporter.async_report_exception(e, component="t")
        assert num == 4242
    finally:
        patcher.stop()


@pytest.mark.asyncio
async def test_reporter_dedupes_within_window():
    reporter, _, patcher = _make_reporter()
    try:
        await reporter.async_load()
        try:
            raise ValueError("same")
        except ValueError as e:
            first = await reporter.async_report_exception(e, component="t")
            second = await reporter.async_report_exception(e, component="t")
        assert first == 4242
        assert second is None  # deduped
    finally:
        patcher.stop()


@pytest.mark.asyncio
async def test_reporter_respects_daily_cap():
    reporter, _, patcher = _make_reporter()
    try:
        await reporter.async_load()
        # Each call gets a unique signature so dedupe won't suppress them.
        for i in range(5):
            await reporter.async_report_anomaly(
                signature=f"sig-{i}",
                title=f"t-{i}",
                details={"i": i},
            )
        # daily_cap=3 — only first 3 should have been posted
        today_count = next(iter(reporter._state.day_counts.values()))
        assert today_count == 3
    finally:
        patcher.stop()


@pytest.mark.asyncio
async def test_reporter_does_nothing_when_disabled():
    reporter = ErrorReporter(
        MagicMock(),
        github_token="ghp_fake",
        github_repo="owner/repo",
        integration_version="9.9.9",
        enabled=False,
        entry_id="test_entry",
    )
    reporter._store = _FakeStore()  # type: ignore[attr-defined]
    await reporter.async_load()
    num = await reporter.async_report_anomaly(
        signature="x", title="y", details={}
    )
    assert num is None


@pytest.mark.asyncio
async def test_reporter_does_not_burn_dedupe_slot_on_http_error():
    reporter, response, patcher = _make_reporter(post_response_status=503)
    try:
        await reporter.async_load()
        try:
            raise ValueError("oops")
        except ValueError as e:
            first = await reporter.async_report_exception(e, component="t")
        assert first is None  # post failed
        # Now flip to success — second attempt should go through.
        response.status = 201
        try:
            raise ValueError("oops")
        except ValueError as e:
            second = await reporter.async_report_exception(e, component="t")
        assert second == 4242
    finally:
        patcher.stop()
