"""Regression tests for #581 — recorder impact from high-frequency SEM sensors.

The recorder DB grew to ~9.6 GB in ~10 days because:

1. Row explosion (``states`` table, ~15.7 M rows / 1.9 GB): the base
   ``last_update`` attribute was stamped with ``dt_util.now()`` on every 10 s
   coordinator cycle and copied onto ALL ~177 SEM entities. HA fires
   ``state_changed`` whenever the state OR any attribute changes, so this
   volatile timestamp forced a recorder write for every SEM entity every cycle
   — even sensors whose real value never changed. ``delta_triggered`` was a
   dead attribute (never populated) that added bytes to every row.

2. Byte bloat (``state_attributes`` table, 4.4 GB): large UI-helper maps —
   most notably the ~9 KiB ``devices`` map on
   ``sensor.sem_controllable_devices_count`` (816 MiB of payload alone) — were
   re-serialised and recorded on every cycle despite having no historical
   value.

The fix removes the volatile base attributes from the live state and marks the
large UI-helper attributes as ``_unrecorded_attributes`` so they stay on the
live entity (cards still read them) but are excluded from the recorder.
"""
import pytest

from homeassistant.components.sensor import SensorEntityDescription

from custom_components.solar_energy_management.sensor import SEMSolarSensor


def _make_sensor(coordinator, key):
    return SEMSolarSensor(
        coordinator=coordinator,
        description=SensorEntityDescription(key=key, name=key, icon="mdi:flash"),
        entry_id="test_entry_id",
    )


@pytest.mark.unit
class TestRecorderImpact581:
    """The recorder-impact root-cause fix for #581."""

    @pytest.mark.asyncio
    async def test_volatile_base_attributes_removed(self, mock_coordinator):
        """last_update/delta_triggered no longer land on any SEM entity.

        These changed every cycle (last_update) or were dead (delta_triggered)
        and forced a recorder write for every entity every 10 s.
        """
        mock_coordinator.data = {
            "solar_power": 2500,
            "last_update": "2026-07-09 12:00:00",
            "delta_triggered": True,
        }
        attrs = _make_sensor(mock_coordinator, "solar_power").extra_state_attributes

        assert "last_update" not in attrs
        assert "delta_triggered" not in attrs

    @pytest.mark.asyncio
    async def test_large_ui_maps_are_unrecorded(self, mock_coordinator):
        """The heavy UI-helper attribute keys are excluded from the recorder."""
        unrecorded = SEMSolarSensor._unrecorded_attributes
        # The reporter's #1 offender — the device map on the count sensor.
        assert "devices" in unrecorded
        # And the other large list/map payloads with no historical value.
        for key in (
            "device_list",
            "per_charger_states",
            "per_charger_plans",
            "today_plan",
            "upcoming",
            "schedule_today",
            "schedule_surplus_hours",
            "schedule_ev_hours",
            "energy_dashboard",
            "schedule",
            # top_5_peaks / top_5_peaks_formatted were removed in #657 — the
            # attributes were built from a coordinator key nothing ever wrote,
            # so they never reached a state for the recorder to store.
        ):
            assert key in unrecorded, f"{key} should be excluded from recorder"

    @pytest.mark.asyncio
    async def test_devices_map_present_live_but_unrecorded(self, mock_coordinator):
        """controllable_devices_count still exposes the devices map to cards.

        The fix must be behaviour-preserving: the drag-and-drop priority card
        reads ``devices`` off the live state. It must remain on
        ``extra_state_attributes`` (live) while being in
        ``_unrecorded_attributes`` (not persisted).
        """
        from unittest.mock import MagicMock

        device_map = {
            "dev1": {"name": "Heat pump", "priority": 1, "current_power": 1200},
            "dev2": {"name": "EV charger", "priority": 2, "current_power": 7200},
        }
        registry = MagicMock()
        registry.get_devices_for_sensor.return_value = device_map
        mock_coordinator._device_registry = registry
        mock_coordinator.data = {"controllable_devices_count": 2}

        sensor = _make_sensor(mock_coordinator, "controllable_devices_count")
        attrs = sensor.extra_state_attributes

        # Live state keeps the map (cards keep working) ...
        assert attrs["devices"] == device_map
        # ... but the recorder is told to drop it.
        assert "devices" in sensor._unrecorded_attributes

    @pytest.mark.asyncio
    async def test_load_management_devices_present_live_but_unrecorded(self, mock_coordinator):
        """load_management_status also exposes devices/device_list live-only."""
        device_map = {
            "dev1": {"friendly_name": "Boiler", "priority": 3, "power_rating": 2000},
        }
        mock_coordinator.data = {
            "load_management_status": "normal",
            "load_management_devices": device_map,
        }
        sensor = _make_sensor(mock_coordinator, "load_management_status")
        attrs = sensor.extra_state_attributes

        assert attrs["devices"] == device_map
        assert "device_list" in attrs
        assert "devices" in sensor._unrecorded_attributes
        assert "device_list" in sensor._unrecorded_attributes
