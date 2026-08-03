"""#584 — per-charger plug state so a car-less charger doesn't push a false
"solar charging started" notification.

Root cause: ``PowerReadings`` never carried per-charger connected/charging,
so ``build_charger_view`` fell back to the fleet OR for every charger. In a
multi-charger fleet a car-less charger therefore looked connected whenever a
SIBLING had a car → it entered SOLAR_CHARGING_ACTIVE and fired a push
("[Laadpaal Links] Zonneladen gestart" with no car plugged in).

Fix #1: sensor_reader records each charger's OWN plug/charging sensor into
``ev_connected_per_charger`` / ``ev_charging_per_charger``; build_charger_view
prefers that over the fleet fallback → a disconnected charger's decide() idles.
Fix #2: the notification dispatcher skips a charger SEM doesn't see connected.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.build_view import (
    build_charger_view,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    FleetCycleState,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings


def _power(*, fleet=True, per_charger=None):
    """Mock PowerReadings with the fields build_charger_view reads."""
    p = MagicMock()
    p.solar_power = 8000
    p.home_consumption_power = 1000
    p.battery_power = 0
    p.battery_charge_power = 0
    p.battery_discharge_power = 0
    p.battery_soc = 80
    p.grid_import_power = 0.0
    p.grid_export_power = 0.0
    p.ev_power = 0
    p.ev_power_per_charger = None
    p.ev_connected = fleet
    p.ev_charging = False
    p.ev_connected_per_charger = per_charger
    p.ev_charging_per_charger = None
    return p


@pytest.mark.unit
class TestPerChargerConnectedResolution:
    """build_charger_view uses a charger's OWN plug sensor when present, and
    only falls back to the fleet OR for a charger without one."""

    def _view(self, cid, power):
        state = FleetCycleState(
            power=power, config={"battery_capacity_kwh": 15}, is_night=False,
        )
        return build_charger_view(
            state, charger_id=cid, charger_cfg={"id": cid},
            mode="solar_only", daily_ev_kwh=0.0,
        )

    def test_own_sensor_disconnected_wins_over_connected_fleet(self):
        # THE bug: fleet says connected (a sibling has a car) but this
        # charger's own sensor says no car → the view must be disconnected.
        p = _power(fleet=True, per_charger={"left": False})
        assert self._view("left", p).power.connected is False

    def test_charger_without_own_sensor_falls_back_to_fleet(self):
        p = _power(fleet=True, per_charger={"left": False})
        assert self._view("right", p).power.connected is True

    def test_own_sensor_connected_wins_over_disconnected_fleet(self):
        p = _power(fleet=False, per_charger={"left": True})
        assert self._view("left", p).power.connected is True


@pytest.mark.unit
def test_power_readings_per_charger_fields_default_empty():
    p = PowerReadings()
    assert p.ev_connected_per_charger == {}
    assert p.ev_charging_per_charger == {}
    # per-instance dicts, not a shared class default
    p.ev_connected_per_charger["a"] = True
    assert PowerReadings().ev_connected_per_charger == {}


def _coord_for_dispatch(effective_states, connected_map, fleet_connected):
    coord = MagicMock()
    coord._notification_manager = AsyncMock()
    coord._effective_states_per_charger = effective_states
    coord._build_per_charger_intelligence = MagicMock(return_value={})
    coord.time_manager = MagicMock()
    coord.time_manager.is_night_mode = MagicMock(return_value=False)
    coord.config = {"update_interval": 30}
    coord._ev_devices = {}
    coord._last_ev_connected_per_charger = {}
    power = MagicMock()
    power.battery_soc = 80.0
    power.grid_import_power = 0.0
    power.ev_connected = fleet_connected
    power.ev_connected_per_charger = connected_map
    energy = MagicMock(daily_ev=0.0, daily_solar=0.0, daily_home=0.0)
    performance = MagicMock(current_vs_peak_percentage=0.0, autarky_rate=0.0)
    forecast = MagicMock(forecast_tomorrow_kwh=10.0)
    return coord, power, energy, performance, forecast


@pytest.mark.unit
class TestNotificationGate:
    """The dispatcher skips a charger SEM doesn't see connected (#584)."""

    async def _run(self, connected_map, fleet_connected=True):
        states = {
            "left": ("solar_charging_active", "Laadpaal Links"),
            "right": ("solar_charging_active", "Laadpaal Rechts"),
        }
        coord, power, energy, perf, fc = _coord_for_dispatch(
            states, connected_map, fleet_connected)
        await SEMCoordinator._send_notifications(
            coord, "idle", power, energy, MagicMock(), perf,
            MagicMock(), fc, 0.0, 6, 4000.0,
        )
        return [c.kwargs.get("charger_id")
                for c in coord._notification_manager.notify_state_change.await_args_list]

    async def test_disconnected_charger_is_suppressed(self):
        notified = await self._run({"left": False, "right": True})
        assert "right" in notified          # has a car → notified
        assert "left" not in notified       # no car → suppressed (the #584 fix)

    async def test_sensorless_charger_uses_fleet_fallback(self):
        # neither charger has a per-charger entry → both use the fleet flag.
        notified = await self._run({}, fleet_connected=True)
        assert set(notified) == {"left", "right"}

    async def test_all_disconnected_notifies_none(self):
        notified = await self._run({"left": False, "right": False})
        assert notified == []
