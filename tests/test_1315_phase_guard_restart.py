"""#1315 — every HA restart sent "Phase limit exceeded … (grid:l1:missing, …)"
and then "returned to safe levels".

RienduPre (2.3.0-beta.5, observer mode, DSMR phase sensors): SEM's first
cycle ran before the DSMR integration had loaded, so every phase read
``missing``. The notice took that first snapshot for an incident, and the
observer text said the limit was EXCEEDED although nothing was measured.

Bug class 86 (a warm-up read taken for a fact): a guard that has had no full
reading since start waits for its meter on the wall clock — until HA runs,
then ``UNAVAILABLE_REPAIR_THRESHOLD_S`` — before it says anything. The guard
itself still holds the chargers at once in enforcing mode; only the notice
waits. A missing reading gets its own text, and a limit notice names the
phase that is over.

These tests drive the REAL evaluator and enforcer, configured like the
reporter's home, so the snapshot shapes are the ones the coordinator makes.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import CoreState
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator import (
    repair_issues as ri,
)
from custom_components.solar_energy_management.coordinator.active_phase_guard import (
    update_active_phase_guard,
)
from custom_components.solar_energy_management.coordinator.notifications import (
    NotificationManager,
)

#: The one constant, never a fresh literal (class 46).
HOLD = ri.UNAVAILABLE_REPAIR_THRESHOLD_S
_ROOT = Path(__file__).resolve().parents[1]


def _reading(value, unit):
    return SimpleNamespace(
        state=str(value),
        attributes={"unit_of_measurement": unit},
        last_updated=dt_util.utcnow(),
        last_reported=dt_util.utcnow(),
    )


class _Home:
    """The reporter's home: grid_only, three phases, 23 A, DSMR power and
    voltage per phase. ``amps`` per phase, or None for "not loaded yet"."""

    def __init__(self, *, enforcing: bool = False):
        self.amps = {1: None, 2: None, 3: None}
        config = {
            "phase_guard_enabled": True,
            "phase_guard_enforcement_enabled": enforcing,
            "phase_guard_topology": "grid_only",
            "phase_guard_phase_count": 3,
            "phase_guard_grid_limit_a": 23,
            "phase_guard_max_age_s": 30,
            "phase_guard_notifications_enabled": True,
            "enable_mobile_notifications": True,
        }
        for phase in (1, 2, 3):
            config[f"phase_guard_grid_l{phase}_power_entity"] = (
                f"sensor.electricity_meter_energieverbruik_fase_l{phase}")
            config[f"phase_guard_grid_l{phase}_voltage_entity"] = (
                f"sensor.electricity_meter_spanning_fase_l{phase}")
        hass = MagicMock()
        hass.state = CoreState.starting
        hass.states.get = MagicMock(side_effect=self._get)
        hass.bus.async_fire = MagicMock()
        self.hass = hass
        self.coord = SimpleNamespace(
            config=config, hass=hass, _observer_mode=False)
        self.manager = NotificationManager(hass, config)
        self.manager._send_mobile_notification = AsyncMock()

    def _get(self, entity_id):
        for phase, amps in self.amps.items():
            if amps is None:
                continue
            if entity_id.endswith(f"energieverbruik_fase_l{phase}"):
                return _reading(amps * 230.0, "W")
            if entity_id.endswith(f"spanning_fase_l{phase}"):
                return _reading(230.0, "V")
        return None

    async def cycle(self, now: float) -> dict:
        snapshot = update_active_phase_guard(self.coord)
        await self.manager.notify_phase_guard_transition(
            snapshot, enabled=True, now=now)
        return snapshot

    @property
    def sent(self) -> list:
        return [call.args[0]
                for call in self.manager._send_mobile_notification.await_args_list]

    @property
    def events(self) -> list:
        return [call.args[1]["state"]
                for call in self.hass.bus.async_fire.call_args_list]


@pytest.mark.asyncio
async def test_the_reporters_restart_sends_nothing():
    """HA starting, DSMR not loaded: every phase reads missing; seconds
    later 1–8 A per phase. Before the fix: two push notices."""
    home = _Home()
    snapshot = await home.cycle(now=0.0)
    assert snapshot["stop_reason"] == (
        "grid:l1:missing,grid:l2:missing,grid:l3:missing")  # premise
    await home.cycle(now=10.0)
    home.hass.state = CoreState.running
    await home.cycle(now=20.0)
    home.amps = {1: 1.0, 2: 8.0, 3: 4.0}
    snapshot = await home.cycle(now=30.0)
    assert snapshot["safe"] is True
    await home.cycle(now=40.0)

    assert home.sent == []
    assert home.events == []


@pytest.mark.asyncio
async def test_enforcing_restart_holds_the_chargers_but_sends_nothing():
    """The guard fails closed at once; the notice still waits."""
    home = _Home(enforcing=True)
    home.hass.state = CoreState.running
    snapshot = await home.cycle(now=0.0)
    assert snapshot["control_authorized"] is False
    home.amps = {1: 1.0, 2: 8.0, 3: 4.0}
    for step in range(1, 6):
        snapshot = await home.cycle(now=10.0 * step)
    assert snapshot["control_authorized"] is True  # premise: re-armed

    assert home.sent == []
    assert home.events == []


@pytest.mark.asyncio
async def test_a_meter_still_missing_after_the_wait_is_reported_as_missing():
    home = _Home()
    await home.cycle(now=0.0)            # HA still starting: no clock yet
    await home.cycle(now=HOLD + 100.0)
    assert home.sent == []
    home.hass.state = CoreState.running
    await home.cycle(now=1000.0)         # the wait starts here
    await home.cycle(now=1000.0 + HOLD - 1.0)
    assert home.sent == []

    await home.cycle(now=1000.0 + HOLD)
    await home.cycle(now=1000.0 + HOLD + 10.0)

    assert len(home.sent) == 1
    text = home.sent[0]
    assert "unavailable" in text.lower()
    assert "exceeded" not in text.lower()
    assert "grid L1 sensor" in text
    assert home.events == ["phase_guard_observer_no_reading"]


@pytest.mark.asyncio
async def test_a_reading_lost_after_start_is_reported_at_once_as_missing():
    home = _Home()
    home.hass.state = CoreState.running
    home.amps = {1: 1.0, 2: 8.0, 3: 4.0}
    await home.cycle(now=0.0)
    home.amps[2] = None
    await home.cycle(now=10.0)

    assert len(home.sent) == 1
    text = home.sent[0].lower()
    assert "unavailable" in text and "exceeded" not in text
    assert "grid l2 sensor" in text
    home.amps[2] = 8.0
    await home.cycle(now=20.0)
    assert home.events == [
        "phase_guard_observer_no_reading", "phase_guard_recovered"]


@pytest.mark.asyncio
async def test_an_overload_during_the_wait_is_reported_at_once():
    """The wait is for a missing reading only. A phase measured over the
    limit is a real incident, and the notice names that phase."""
    home = _Home()
    home.hass.state = CoreState.running
    home.amps = {1: None, 2: 25.0, 3: None}
    await home.cycle(now=0.0)

    assert len(home.sent) == 1
    text = home.sent[0]
    assert "exceeded" in text.lower()
    assert "grid L2 25.0 A" in text
    assert "grid L1" not in text.split("(")[0]
    assert home.events == ["phase_guard_observer_warning"]


@pytest.mark.asyncio
async def test_an_overload_after_a_missing_reading_is_a_new_notice():
    home = _Home()
    home.hass.state = CoreState.running
    home.amps = {1: 1.0, 2: 8.0, 3: 4.0}
    await home.cycle(now=0.0)
    home.amps[1] = None
    await home.cycle(now=10.0)
    home.amps[1] = 1.0
    home.amps[2] = 25.0
    await home.cycle(now=20.0)

    assert home.events == [
        "phase_guard_observer_no_reading", "phase_guard_observer_warning"]
    assert "grid L2 25.0 A" in home.sent[1]


@pytest.mark.asyncio
async def test_enforcing_block_names_the_phase_over_the_limit():
    home = _Home(enforcing=True)
    home.hass.state = CoreState.running
    home.amps = {1: 1.0, 2: 8.0, 3: 4.0}
    for step in range(5):
        await home.cycle(now=10.0 * step)
    home.amps = {1: None, 2: 25.0, 3: 4.0}
    await home.cycle(now=100.0)

    assert home.events == ["phase_guard_blocked"]
    assert "grid L2 25.0 A" in home.sent[0]


def test_every_language_says_missing_apart_from_exceeded():
    tables = json.loads(
        (_ROOT / "dashboard" / "translations.json").read_text(encoding="utf-8"))
    assert len(tables) == 16
    for lang, table in tables.items():
        missing = table.get("notif_phase_guard_observer_no_reading")
        exceeded = table.get("notif_phase_guard_observer_warning")
        assert missing, lang
        assert missing != exceeded, lang
        assert "{location}" in missing and "{reason}" in missing, lang
