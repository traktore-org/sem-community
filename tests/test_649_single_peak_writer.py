"""#649 — one peak writer per device.

Peak shed/restore for surplus-mode loads lived in TWO engines with separate
state, anti-flicker and restore criteria: ``LoadManagement`` (``_devices_shed``
+ ``_pre_shed_was_on``) and the surplus controller (``is_active`` + source
markers, which already receives ``peak_state`` and sheds its own actives).

Shedding twice was survivable. RESTORING was not: ``_restore_device`` turns the
switch back on the moment the peak recedes — with zero surplus and surplus
intent OFF — after which ``device_reconciler`` reads it as ``external_on``
("don't fight the user") and the load runs on grid all night.

Same single-writer exclusion the EV charger got in #461-peak, now applied to
surplus-mode loads the surplus controller actually drives.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.load_management import (
    LoadManagementCoordinator,
)
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)


def _info(**kw):
    base = dict(
        switch_entity="switch.x", power_entity="sensor.x_power",
        friendly_name="X", power_rating=1.0, is_available=True, priority=5,
        is_critical=False, is_controllable=True, device_type="individual_device",
        control_mode="surplus", surplus_managed=True,
        control={"type": "switch", "entity": "switch.x"},
    )
    base.update(kw)
    return base


@pytest.fixture
def lm649(mock_hass):
    entry = MagicMock()
    entry.options = {"load_management_enabled": True, "target_peak_limit": 5.0}
    entry.entry_id = "e"
    with patch(
        "custom_components.solar_energy_management.features.load_management.LoadDeviceDiscovery"
    ) as MockDiscovery, patch(
        "custom_components.solar_energy_management.features.load_management.Store"
    ) as MockStore:
        disc = MagicMock()
        disc.get_device_current_state = MagicMock(
            return_value={"is_on": True, "current_power": 1000}
        )
        disc.turn_on_device = AsyncMock(return_value=True)
        disc.turn_off_device = AsyncMock(return_value=True)
        MockDiscovery.return_value = disc
        MockStore.return_value = MagicMock(
            async_load=AsyncMock(return_value=None), async_save=AsyncMock()
        )
        c = LoadManagementCoordinator(mock_hass, entry)
        c.hass.services.async_call = AsyncMock()
        c._device_discovery = disc
        c._observer_mode = False
        yield c


@pytest.mark.unit
class TestSheddingSelection649:
    @pytest.mark.parametrize(
        "kw,shed_here",
        [
            (dict(control_mode="surplus", surplus_managed=True), False),   # #649
            (dict(device_type="ev_charger"), False),                       # #461-peak
            (dict(control_mode="peak_only"), True),   # LM keeps sole ownership
            # surplus mode but NO live controller object (e.g. a service-control
            # type the surplus sync skips) — excluding it would orphan the load
            (dict(control_mode="surplus", surplus_managed=False), True),
        ],
    )
    def test_who_the_load_manager_may_shed(self, lm649, kw, shed_here):
        lm649._devices["d1"] = _info(**kw)
        picked = [did for did, _ in lm649._get_devices_for_shedding()]
        assert ("d1" in picked) is shed_here

    @pytest.mark.asyncio
    async def test_emergency_pass_skips_surplus_devices(self, lm649):
        lm649._devices["pump"] = _info()
        lm649._devices["boiler"] = _info(control_mode="peak_only")
        lm649._shed_device = AsyncMock()
        lm649._last_grid_import_w = 5500.0  # (#896) the plan reads the meter
        await lm649._emergency_load_shedding()
        shed = [c.args[0] for c in lm649._shed_device.await_args_list]
        assert shed == ["boiler"]

    @pytest.mark.asyncio
    async def test_shed_device_refuses_even_if_called_directly(self, lm649):
        """Belt-and-braces: a future caller must not bypass the selection skip."""
        lm649._devices["pump"] = _info()
        await lm649._shed_device("pump", "EMERGENCY")
        assert "pump" not in lm649._devices_shed
        lm649.hass.services.async_call.assert_not_called()


@pytest.mark.unit
class TestRestoreIsTheDangerousHalf649:
    @pytest.mark.asyncio
    async def test_stale_shed_entry_is_dropped_not_switched_on(self, lm649):
        """The #649 failure itself: a surplus load restored by the LM at dusk
        (zero surplus, intent OFF) is then read as ``external_on`` and runs on
        grid all night. Upgrades and mid-shed mode changes can leave the entry
        behind, so the restore path must drop it WITHOUT actuating."""
        lm649._devices["pump"] = _info()
        lm649._devices["pump"]["_pre_shed_was_on"] = True
        lm649._devices_shed.append("pump")
        # off + was-on-before-shed = precisely the state pre-fix turned back ON
        lm649._device_discovery.get_device_current_state = MagicMock(
            return_value={"is_on": False, "current_power": 0}
        )

        await lm649._restore_device("pump")

        assert lm649._devices_shed == []          # released…
        lm649.hass.services.async_call.assert_not_called()   # …but not turned on
        lm649._device_discovery.turn_on_device.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_peak_only_device_still_restores(self, lm649):
        lm649._devices["boiler"] = _info(
            control_mode="peak_only", surplus_managed=False,
            switch_entity="switch.boiler", control={"type": "switch", "entity": "switch.boiler"},
        )
        lm649._devices["boiler"]["_pre_shed_was_on"] = True
        lm649._devices_shed.append("boiler")
        # a shed device reads OFF — otherwise the anti-flicker check declines
        lm649._device_discovery.get_device_current_state = MagicMock(
            return_value={"is_on": False, "current_power": 0}
        )

        await lm649._restore_device("boiler")

        assert lm649.hass.services.async_call.await_count >= 1
        assert lm649._devices_shed == []


@pytest.mark.unit
class TestStaleEntryDoesNotPinTheStateMachine649:
    """A non-empty ``_devices_shed`` reads as SHEDDING, so ``_restore_loads``
    never runs — and the restore-path guard that drops the stale entry is never
    reached. The load manager must not hold shed state for a device it doesn't
    own, on or off."""

    def test_cleanup_evicts_a_running_surplus_device(self, lm649):
        lm649._devices["pump"] = _info()          # surplus, and back ON
        lm649._devices_shed.append("pump")
        lm649._cleanup_shed_list()
        assert lm649._devices_shed == []

    def test_cleanup_keeps_a_running_peak_only_device(self, lm649):
        """The existing contract: an LM-shed device that is on again stays
        tracked (it's genuinely ours) until it reads off."""
        lm649._devices["boiler"] = _info(control_mode="peak_only", surplus_managed=False)
        lm649._devices_shed.append("boiler")
        lm649._cleanup_shed_list()
        assert lm649._devices_shed == ["boiler"]


@pytest.mark.unit
class TestSheddableMetricsMatchWhatWeShed649:
    """"How much can we shed?" must not count loads shedding will skip."""

    def test_surplus_device_is_not_counted_as_available_reduction(self, lm649):
        lm649._devices["pump"] = _info()
        lm649._devices["boiler"] = _info(control_mode="peak_only", surplus_managed=False)
        data = lm649.get_load_management_data()
        assert data["controllable_devices"] == 1          # the boiler only
        assert data["available_load_reduction"] == pytest.approx(1.0)   # 1000 W


@pytest.mark.unit
class TestRegistryMarksTheOwner649:
    def _reg(self, registered_ids):
        reg = UnifiedDeviceRegistry(MagicMock(), MagicMock(), MagicMock(), MagicMock())
        sc = MagicMock()
        sc.get_device = MagicMock(side_effect=lambda d: MagicMock() if d in registered_ids else None)
        reg._surplus_controller = sc
        lm = MagicMock()
        lm._devices = {}
        reg._load_manager = lm
        reg._service_registrations = {}
        reg._control_mode_overrides = {}
        reg._dependency_overrides = {}
        reg._get_power_rating = MagicMock(return_value=1000.0)
        return reg

    def test_sync_flags_only_devices_the_surplus_controller_drives(self):
        from custom_components.solar_energy_management.features.device_registry import (
            UnifiedDevice,
        )
        reg = self._reg({"energy_dashboard_pond_pump"})
        reg._devices = [
            UnifiedDevice(
                energy_sensor="sensor.pond_pump_energy", power_sensor=None,
                name="Pond pump", priority=5,
                control={"type": "switch", "entity": "switch.pond"},
            ),
            UnifiedDevice(
                energy_sensor="sensor.boiler_energy", power_sensor=None,
                name="Boiler", priority=6,
                control={"type": "service", "service": "x.y"},
            ),
        ]
        reg._sync_to_load_manager()
        lm = reg._load_manager._devices
        assert lm["energy_dashboard_pond_pump"]["surplus_managed"] is True
        assert lm["energy_dashboard_boiler"]["surplus_managed"] is False

    @pytest.mark.asyncio
    async def test_mode_change_updates_the_load_manager_entry_immediately(self):
        """Otherwise up to 35 s (the rediscovery interval) of peak shedding
        targets a device the user has just handed to the surplus controller."""
        reg = self._reg({"energy_dashboard_pond_pump"})
        reg._save_storage = AsyncMock()
        reg._load_manager._devices["energy_dashboard_pond_pump"] = _info(
            control_mode="peak_only", surplus_managed=False,
        )
        await reg.update_device_control_mode("energy_dashboard_pond_pump", "surplus")
        entry = reg._load_manager._devices["energy_dashboard_pond_pump"]
        assert entry["control_mode"] == "surplus"
        assert entry["surplus_managed"] is True

        # …and back: ownership returns to the load manager just as promptly
        await reg.update_device_control_mode("energy_dashboard_pond_pump", "peak_only")
        assert entry["control_mode"] == "peak_only"

    @pytest.mark.asyncio
    async def test_mode_change_on_an_undriven_device_keeps_it_load_manager_owned(self):
        """Flipping a device the surplus controller doesn't drive to "surplus"
        must NOT hand it away — nobody would shed it."""
        reg = self._reg(set())          # get_device returns None for everything
        reg._save_storage = AsyncMock()
        reg._load_manager._devices["energy_dashboard_boiler"] = _info(
            control_mode="peak_only", surplus_managed=False,
        )
        await reg.update_device_control_mode("energy_dashboard_boiler", "surplus")
        assert reg._load_manager._devices["energy_dashboard_boiler"]["surplus_managed"] is False

    @pytest.mark.asyncio
    async def test_mode_change_before_the_first_sync_is_a_no_op(self):
        """Boot ordering: the LM entry may not exist yet — must not crash."""
        reg = self._reg({"energy_dashboard_pond_pump"})
        reg._save_storage = AsyncMock()
        await reg.update_device_control_mode("energy_dashboard_pond_pump", "surplus")
        assert reg._load_manager._devices == {}
