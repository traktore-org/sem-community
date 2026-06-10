"""Actuation hardening for CurrentControlDevice (#462 follow-up).

RienduPre's install had ``ev_charger_service: number.set_value`` — the
service path then sent ``{current: X}``, which ``number.set_value``'s
schema rejects (``extra keys not allowed @ data['current']``). EVERY
current command on both chargers failed for days, including the 0 A for
off-mode, with only per-cycle ERROR log lines as evidence.

Three contracts under test:

1. ``number.set_value`` configured as the charger SERVICE is mapped to
   the number-entity write it was meant to be (``value`` + entity_id).
2. Genuine per-integration services still get ``service_param_name``.
3. Three consecutive set-current failures raise a Repair issue; the next
   successful write clears it.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.solar_energy_management.devices.base import (
    CurrentControlDevice,
)


def _device(**kwargs) -> CurrentControlDevice:
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    defaults = dict(
        hass=hass,
        device_id="ev_charger_1",
        name="Laadpaal Rechts",
        min_current=6.0,
        max_current=32.0,
        phases=3,
    )
    defaults.update(kwargs)
    return CurrentControlDevice(**defaults)


@pytest.mark.unit
class TestNumberSetValueServiceShape:
    @pytest.mark.asyncio
    async def test_number_set_value_service_routes_with_value_param(self):
        """The misconfigured-but-recoverable shape: service=number.set_value
        must send {entity_id, value}, never the per-integration param."""
        dev = _device(
            charger_service="number.set_value",
            current_entity_id="number.wallbox_rechts_max_charging_current_2",
        )
        await dev._set_current(16)
        dev.hass.services.async_call.assert_awaited_once_with(
            "number", "set_value",
            {
                "entity_id": "number.wallbox_rechts_max_charging_current_2",
                "value": 16,
            },
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_number_set_value_falls_back_to_service_entity_id(self):
        """No current_entity_id → the configured service entity is the target."""
        dev = _device(
            charger_service="number.set_value",
            charger_service_entity_id="number.wallbox_max_current",
        )
        await dev._set_current(10)
        call = dev.hass.services.async_call.await_args
        assert call.args[2]["entity_id"] == "number.wallbox_max_current"
        assert call.args[2]["value"] == 10
        assert "current" not in call.args[2]

    @pytest.mark.asyncio
    async def test_real_integration_service_keeps_param_name(self):
        """KEBA-style global services keep the per-integration param."""
        dev = _device(charger_service="keba.set_current")
        dev.service_param_name = "current"
        await dev._set_current(13)
        call = dev.hass.services.async_call.await_args
        assert call.args[0] == "keba"
        assert call.args[1] == "set_current"
        assert call.args[2] == {"current": 13}


@pytest.mark.unit
class TestActuationFailureRepair:
    @pytest.mark.asyncio
    async def test_three_consecutive_failures_raise_repair(self):
        dev = _device(current_entity_id="number.gone")
        dev.hass.services.async_call = AsyncMock(
            side_effect=Exception("extra keys not allowed @ data['current']"),
        )
        with patch(
            "custom_components.solar_energy_management.coordinator."
            "repair_issues.raise_charger_actuation_failed"
        ) as raise_repair:
            await dev._set_current(10)
            await dev._set_current(10)
            raise_repair.assert_not_called()  # streak of 2 — not yet
            await dev._set_current(10)
            raise_repair.assert_called_once()
            kwargs = raise_repair.call_args
            assert kwargs.args[1] == "ev_charger_1"
            assert "extra keys" in kwargs.kwargs["error"]
            # A 4th failure must not re-raise (idempotent guard)
            await dev._set_current(10)
            raise_repair.assert_called_once()

    @pytest.mark.asyncio
    async def test_successful_write_clears_repair_and_streak(self):
        dev = _device(current_entity_id="number.flaky")
        dev.hass.services.async_call = AsyncMock(side_effect=Exception("boom"))
        with patch(
            "custom_components.solar_energy_management.coordinator."
            "repair_issues.raise_charger_actuation_failed"
        ), patch(
            "custom_components.solar_energy_management.coordinator."
            "repair_issues.clear_charger_actuation_failed"
        ) as clear_repair:
            for _ in range(3):
                await dev._set_current(10)
            assert dev._actuation_repair_raised is True

            dev.hass.services.async_call = AsyncMock()  # recovers
            await dev._set_current(12)
            clear_repair.assert_called_once()
            assert dev._actuation_failures == 0
            assert dev._actuation_repair_raised is False

    @pytest.mark.asyncio
    async def test_intermittent_failures_never_raise(self):
        """Fail-fail-succeed cycles (flaky Wi-Fi) stay below the threshold."""
        dev = _device(current_entity_id="number.flaky")
        with patch(
            "custom_components.solar_energy_management.coordinator."
            "repair_issues.raise_charger_actuation_failed"
        ) as raise_repair:
            for round_no in range(3):
                dev.hass.services.async_call = AsyncMock(side_effect=Exception("x"))
                await dev._set_current(10 + round_no)
                await dev._set_current(11 + round_no)
                dev.hass.services.async_call = AsyncMock()
                await dev._set_current(12 + round_no)
            raise_repair.assert_not_called()
