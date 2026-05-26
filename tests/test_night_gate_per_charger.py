"""Phase 3 (#255): night gate moved off the global switch onto per-charger, plus the
one-time global→per-charger reconciliation (force-off)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.solar_energy_management.coordinator.charging_control import (
    ChargingStateMachine,
)
from custom_components.solar_energy_management.switch import SEMPerChargerSwitch


def _sm(chargers, switch_states):
    hass = MagicMock()
    hass.states.is_state = Mock(side_effect=lambda eid, st: switch_states.get(eid) == st)
    return ChargingStateMachine(hass, {"ev_chargers": chargers}, MagicMock())


class TestNightGatePerCharger:
    def test_any_charger_on_enables(self):
        sm = _sm([{"id": "a"}, {"id": "b"}], {"switch.sem_charger_b_night_charging": "on"})
        assert sm._any_night_charging_enabled() is True

    def test_all_per_charger_off_disables(self):
        sm = _sm([{"id": "a"}, {"id": "b"}], {})
        assert sm._any_night_charging_enabled() is False

    def test_legacy_no_chargers_falls_back_to_global(self):
        assert _sm([], {"switch.sem_night_charging": "on"})._any_night_charging_enabled() is True
        assert _sm([], {})._any_night_charging_enabled() is False

    def test_single_charger_on(self):
        sm = _sm([{"id": "ev_charger"}], {"switch.sem_charger_ev_charger_night_charging": "on"})
        assert sm._any_night_charging_enabled() is True


class TestReconciliationForceOff:
    @pytest.mark.asyncio
    async def test_force_off_overrides_restored_on(self):
        """The one-time reconciliation forces a per-charger switch OFF even if its own
        restored state was 'on' (global was OFF → don't silently re-enable)."""
        coord = MagicMock()
        desc = SwitchEntityDescription(key="charger_a_night_charging")
        sw = SEMPerChargerSwitch(coord, desc, "e", "a", "A", force_off=True)
        sw.async_get_last_state = AsyncMock(return_value=MagicMock(state="on"))
        with patch.object(CoordinatorEntity, "async_added_to_hass", AsyncMock()):
            await sw.async_added_to_hass()
        assert sw.is_on is False

    @pytest.mark.asyncio
    async def test_no_force_keeps_restored_on(self):
        coord = MagicMock()
        desc = SwitchEntityDescription(key="charger_a_night_charging")
        sw = SEMPerChargerSwitch(coord, desc, "e", "a", "A", force_off=False)
        sw.async_get_last_state = AsyncMock(return_value=MagicMock(state="on"))
        with patch.object(CoordinatorEntity, "async_added_to_hass", AsyncMock()):
            await sw.async_added_to_hass()
        assert sw.is_on is True
