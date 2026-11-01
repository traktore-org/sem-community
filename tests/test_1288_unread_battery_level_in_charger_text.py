"""#1288 — the charger text must not print "Bat 0%" before the level is read.

After a restart the battery level is the placeholder 0.0 until the sensor
reports (``battery_soc_known`` False). The wallbox text read it as a real 0 %.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.consts.states import ChargingState
from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator
from custom_components.solar_energy_management.coordinator.notifications import (
    NotificationManager,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings

SOC_STATES = (ChargingState.SOLAR_PAUSE_LOW_BATTERY,
              ChargingState.SOLAR_WAITING_BATTERY_PRIORITY)


def _nm():
    hass = MagicMock()
    hass.config.language = "en"
    return NotificationManager(hass, {})


def _text(nm, state, **data):
    return nm._get_notification_messages(state, data)["charger"]


@pytest.mark.parametrize("state", SOC_STATES)
def test_a_known_level_is_still_printed(state):
    nm = _nm()
    assert "Bat 37%" in _text(nm, state, battery_soc=37, battery_soc_known=True)
    assert "Bat 37%" in _text(nm, state, battery_soc=37)  # old callers


@pytest.mark.parametrize("state", SOC_STATES)
def test_a_real_zero_is_still_printed(state):
    assert "Bat 0%" in _text(_nm(), state, battery_soc=0, battery_soc_known=True)


@pytest.mark.parametrize("state", SOC_STATES)
def test_an_unread_level_prints_no_percent(state):
    text = _text(_nm(), state, battery_soc=0.0, battery_soc_known=False)
    assert "%" not in text and "{" not in text
    assert text.endswith("Bat") and text.split(":")[0] in ("Pause", "Wait")


@pytest.mark.parametrize("lang", ["en", "de", "fr", "nl", "it", "es", "da", "cs"])
@pytest.mark.parametrize("state", SOC_STATES)
def test_every_language_drops_the_percent(lang, state):
    nm = _nm()
    nm.hass.config.language = lang
    text = _text(nm, state, battery_soc=0.0, battery_soc_known=False)
    assert "%" not in text and "{" not in text and text.strip()


@pytest.mark.asyncio
@pytest.mark.parametrize("known,unavailable,expect_pct", [
    (False, False, False),   # never read since the restart
    (True, True, False),     # sensor offline
    (True, False, True),     # a real reading
])
async def test_the_real_pipeline_hands_over_the_flag(known, unavailable, expect_pct):
    """``_send_notifications`` builds the data the text is made from."""
    nm = _nm()
    seen = []

    async def _capture(state, data, **kw):
        seen.append(nm._get_notification_messages(state, data)["charger"])

    nm.notify_state_change = _capture
    nm.notify_battery_full = AsyncMock()
    nm.notify_high_grid_import = AsyncMock()
    fake = SimpleNamespace(
        _notification_manager=nm, config={}, _night_target_per_charger_map={},
        _effective_states_per_charger={},
        _build_per_charger_intelligence=lambda: {})
    power = PowerReadings(battery_soc=0.0 if not known else 0.0,
                          battery_soc_known=known,
                          battery_soc_unavailable=unavailable)
    ctx = SimpleNamespace(charging_strategy="x", charging_strategy_reason="x",
                          canonical_strategy="x")
    energy = SimpleNamespace(daily_ev=0.0, daily_solar=0, daily_home=0)
    perf = SimpleNamespace(current_vs_peak_percentage=0, autarky_rate=0)
    fc = SimpleNamespace(forecast_tomorrow_kwh=0)
    await SEMCoordinator._send_notifications(
        fake, ChargingState.SOLAR_WAITING_BATTERY_PRIORITY, power, energy,
        SimpleNamespace(), perf, ctx, fc, 0, 0, 0)
    assert seen, "no charger text was made"
    assert ("%" in seen[0]) is expect_pct, seen[0]
