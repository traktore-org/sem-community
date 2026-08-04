"""Observer-mode 72 hour readiness countdown."""

from datetime import UTC, datetime, timedelta

from custom_components.solar_energy_management.observer_readiness import (
    OBSERVATION_TARGET_SECONDS,
    observation_progress,
)


def test_countdown_reports_elapsed_and_remaining_time():
    started = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)
    now = started + timedelta(hours=25, minutes=30)

    result = observation_progress(started.isoformat(), now=now)

    assert OBSERVATION_TARGET_SECONDS == 72 * 60 * 60
    assert result == {
        "elapsed_seconds": 25 * 60 * 60 + 30 * 60,
        "remaining_seconds": 46 * 60 * 60 + 30 * 60,
        "target_seconds": 72 * 60 * 60,
        "ready": False,
    }


def test_countdown_is_ready_after_72_hours_and_never_goes_negative():
    started = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)

    result = observation_progress(
        started.isoformat(), now=started + timedelta(hours=80)
    )

    assert result["elapsed_seconds"] == 72 * 60 * 60
    assert result["remaining_seconds"] == 0
    assert result["ready"] is True


def test_missing_or_invalid_start_is_fail_closed():
    now = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)

    for started in (None, "", "not-a-date"):
        result = observation_progress(started, now=now)
        assert result["elapsed_seconds"] == 0
        assert result["remaining_seconds"] == 72 * 60 * 60
        assert result["ready"] is False


def test_future_start_is_clamped_to_zero_elapsed():
    now = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)

    result = observation_progress(
        (now + timedelta(hours=1)).isoformat(), now=now
    )

    assert result["elapsed_seconds"] == 0
    assert result["remaining_seconds"] == 72 * 60 * 60
    assert result["ready"] is False
