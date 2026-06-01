"""Tests for the WallboxAdapter (#357).

Confirms:
- The adapter factory picks ``WallboxAdapter`` for Wallbox-like devices.
- ``command_idle`` / ``command_disable`` call the pause-resume switch
  in addition to ``_set_current(0)`` + ``stop_session``.
- Discovery is cached (no per-cycle registry lookup).
- Missing pause switch is a silent no-op (falls back to generic
  behaviour) — does not crash.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from custom_components.solar_energy_management.coordinator.charger_adapters import (
    GenericAdapter,
    KebaAdapter,
    WallboxAdapter,
    adapter_for,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerIntent,
)


def _make_device(
    charger_service: str = "",
    charger_service_entity_id: str = "",
    charger_current_entity: str = "",
    start_stop_entity: str = "",
    name: str = "test_charger",
):
    """Build a mock CurrentControlDevice with the minimum attrs the
    adapter inspects."""
    device = Mock()
    device.name = name
    device.charger_service = charger_service
    device.charger_service_entity_id = charger_service_entity_id
    device.charger_current_entity = charger_current_entity
    device.start_stop_entity = start_stop_entity
    device.hass = MagicMock()
    device.hass.services.async_call = AsyncMock()
    device._set_current = AsyncMock()
    device.stop_session = AsyncMock()
    device._session_active = False
    device.min_current = 6
    device.max_current = 32
    device.phases = 3
    device.voltage = 230
    return device


class TestAdapterFactory:
    """Factory picks the right adapter for each brand."""

    def test_wallbox_via_service_prefix(self):
        device = _make_device(charger_service="wallbox.set_charging_current")
        assert isinstance(adapter_for(device), WallboxAdapter)

    def test_wallbox_via_entity_id_match(self):
        device = _make_device(
            charger_service="number.set_value",
            charger_service_entity_id="number.wallbox_pulsar_charging_current",
        )
        assert isinstance(adapter_for(device), WallboxAdapter)

    def test_keba_wins_when_service_keba(self):
        # Even if entity_id contains "wallbox" (mixed install), KEBA
        # service name takes priority — the KEBA quirks are stronger.
        device = _make_device(charger_service="keba.set_current")
        assert isinstance(adapter_for(device), KebaAdapter)

    def test_generic_fallback(self):
        device = _make_device(
            charger_service="number.set_value",
            charger_service_entity_id="number.easee_current",
        )
        adapter = adapter_for(device)
        assert isinstance(adapter, GenericAdapter)
        # Must NOT be a WallboxAdapter (which is a GenericAdapter subclass).
        assert not isinstance(adapter, WallboxAdapter)


class TestWallboxPauseSwitch:
    """When a pause-resume switch is discoverable, command_idle /
    command_disable toggle it off in addition to set_current(0)."""

    @pytest.mark.asyncio
    async def test_disable_toggles_pause_switch(self):
        device = _make_device(
            charger_service_entity_id="number.wallbox_pulsar_charging_current",
        )
        adapter = WallboxAdapter(device)

        # Patch the discovery helper to return a fake switch — easier
        # than mocking the full registry.
        adapter._pause_switch_entity = "switch.wallbox_pulsar_pause_resume"
        adapter._pause_switch_searched = True

        await adapter.command_disable()

        # Generic path fired set_current(0) + stop_session.
        device._set_current.assert_called_with(0)
        device.stop_session.assert_called()

        # Wallbox-specific addition: switch.turn_off on the pause switch.
        calls = device.hass.services.async_call.call_args_list
        pause_calls = [
            c for c in calls
            if c.args[:2] == ("switch", "turn_off")
            and c.args[2].get("entity_id") == "switch.wallbox_pulsar_pause_resume"
        ]
        assert len(pause_calls) == 1
        assert adapter.last_intent is ChargerIntent.DISABLE

    @pytest.mark.asyncio
    async def test_idle_toggles_pause_switch(self):
        device = _make_device()
        adapter = WallboxAdapter(device)
        adapter._pause_switch_entity = "switch.wallbox_pulsar_pause_resume"
        adapter._pause_switch_searched = True

        await adapter.command_idle()

        device._set_current.assert_called_with(0)
        calls = device.hass.services.async_call.call_args_list
        pause_calls = [
            c for c in calls
            if c.args[:2] == ("switch", "turn_off")
            and c.args[2].get("entity_id") == "switch.wallbox_pulsar_pause_resume"
        ]
        assert len(pause_calls) == 1
        assert adapter.last_intent is ChargerIntent.IDLE

    @pytest.mark.asyncio
    async def test_no_pause_switch_silent_noop(self):
        """When no pause switch is discovered, the adapter still
        fires the generic ``_set_current(0)`` + ``stop_session`` path
        and does NOT crash."""
        device = _make_device()
        adapter = WallboxAdapter(device)
        # Discovery returns nothing.
        adapter._pause_switch_entity = None
        adapter._pause_switch_searched = True

        await adapter.command_disable()

        device._set_current.assert_called_with(0)
        device.stop_session.assert_called()
        # No switch.turn_off call.
        calls = device.hass.services.async_call.call_args_list
        switch_calls = [
            c for c in calls if c.args[:2] == ("switch", "turn_off")
        ]
        assert switch_calls == []
        assert adapter.last_intent is ChargerIntent.DISABLE

    @pytest.mark.asyncio
    async def test_pause_switch_failure_does_not_propagate(self):
        """If the switch service call raises, the disable path still
        completes — set_current(0) and stop_session both ran. The
        primary stop mechanism must succeed even if the auxiliary
        switch is offline."""
        device = _make_device()
        adapter = WallboxAdapter(device)
        adapter._pause_switch_entity = "switch.wallbox_pulsar_pause_resume"
        adapter._pause_switch_searched = True
        device.hass.services.async_call.side_effect = Exception(
            "service unavailable",
        )

        # Must not raise.
        await adapter.command_disable()

        device._set_current.assert_called_with(0)
        device.stop_session.assert_called()
        assert adapter.last_intent is ChargerIntent.DISABLE

    def test_discovery_cached_after_first_call(self):
        """Second call to ``_discover_pause_switch`` returns the
        cached value without touching the registry."""
        device = _make_device()
        adapter = WallboxAdapter(device)
        # Simulate first call having found nothing.
        adapter._pause_switch_entity = None
        adapter._pause_switch_searched = True

        # If the cache works, no registry call is made.
        with patch(
            "custom_components.solar_energy_management.coordinator.charger_adapters.wallbox.er.async_get"
        ) as mock_er:
            result = adapter._discover_pause_switch()

        assert result is None
        mock_er.assert_not_called()
