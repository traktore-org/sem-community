"""#650 — "critical" / "controllable" survive a registry rebuild.

Pre-fix both flags were written ONLY into ``LoadManagement._devices``, while
``_sync_to_load_manager`` REPLACES that entry wholesale on every rebuild (drag,
the 35 s re-discovery, a config change, restart). So "hands off the pond pump"
or "the freezer is critical" reverted to the dataclass defaults within 35 s and
the next peak event shed the device anyway — ledger class 14, the same shape as
the #122 dependency wipe.

The flags now live in registry override stores next to priority / control_mode /
dependencies, are re-applied at device build, and flow through to LoadManagement.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDevice, UnifiedDeviceRegistry,
)


def _reg():
    reg = UnifiedDeviceRegistry(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    reg._critical_overrides = {}
    reg._controllable_overrides = {}
    reg._control_mode_overrides = {}
    reg._save_storage = AsyncMock()
    reg.async_refresh_devices = AsyncMock()
    return reg


def _dev(**kw):
    base = dict(
        energy_sensor="sensor.pond_pump_energy", power_sensor="sensor.pond_pump_power",
        name="Pond pump", priority=50, control={"type": "switch", "entity": "switch.pond"},
    )
    base.update(kw)
    return UnifiedDevice(**base)


@pytest.mark.unit
class TestControllableOverrideSemantics650:
    def test_false_override_forces_not_controllable(self):
        # the user's explicit "hands off" beats a present control config
        assert _dev(controllable_override=False).is_controllable is False

    def test_no_override_falls_back_to_derived(self):
        assert _dev().is_controllable is True
        assert _dev(control=None).is_controllable is False

    def test_true_override_cannot_invent_controllability(self):
        """An override may only RESTRICT — otherwise LoadManagement counts a
        device as sheddable that has nothing to switch."""
        assert _dev(control=None, controllable_override=True).is_controllable is False


@pytest.mark.unit
class TestFlagsSurviveRebuild650:
    @pytest.mark.asyncio
    async def test_set_flag_persists_and_rebuild_reapplies(self):
        reg = _reg()
        await reg.async_set_device_flag("energy_dashboard_pond_pump", "controllable", False)
        await reg.async_set_device_flag("energy_dashboard_freezer", "critical", True)

        assert reg._save_storage.await_count == 2      # persisted, not in-memory only
        assert reg.async_refresh_devices.await_count == 2

        # what the rebuild would construct for each device
        d_pump = UnifiedDevice(
            energy_sensor="sensor.pond_pump_energy", power_sensor=None,
            name="Pond pump", priority=50, control={"type": "switch", "entity": "switch.p"},
            is_critical=bool(reg._critical_overrides.get("energy_dashboard_pond_pump", False)),
            controllable_override=reg._controllable_overrides.get("energy_dashboard_pond_pump"),
        )
        d_frz = UnifiedDevice(
            energy_sensor="sensor.freezer_energy", power_sensor=None,
            name="Freezer", priority=51, control={"type": "switch", "entity": "switch.f"},
            is_critical=bool(reg._critical_overrides.get("energy_dashboard_freezer", False)),
            controllable_override=reg._controllable_overrides.get("energy_dashboard_freezer"),
        )
        assert d_pump.is_controllable is False   # was True again after 35 s pre-fix
        assert d_frz.is_critical is True

    @pytest.mark.asyncio
    async def test_re_enabling_controllable_clears_the_override(self):
        reg = _reg()
        await reg.async_set_device_flag("d1", "controllable", False)
        assert reg._controllable_overrides == {"d1": False}
        await reg.async_set_device_flag("d1", "controllable", True)
        assert "d1" not in reg._controllable_overrides   # back to derived

    @pytest.mark.asyncio
    async def test_unknown_flag_is_a_no_op(self):
        reg = _reg()
        await reg.async_set_device_flag("d1", "nonsense", True)
        assert reg._critical_overrides == {} and reg._controllable_overrides == {}
        reg._save_storage.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_overrides_round_trip_through_the_store(self):
        """The wipe returns the moment these drop out of the saved payload."""
        reg = UnifiedDeviceRegistry(MagicMock(), MagicMock(), MagicMock(), MagicMock())
        reg._store = MagicMock()
        reg._store.async_save = AsyncMock()
        reg._critical_overrides = {"d_frz": True}
        reg._controllable_overrides = {"d_pump": False}
        await reg._save_storage()
        payload = reg._store.async_save.await_args.args[0]
        assert payload["critical_overrides"] == {"d_frz": True}
        assert payload["controllable_overrides"] == {"d_pump": False}

        # …and come back on the next boot
        fresh = UnifiedDeviceRegistry(MagicMock(), MagicMock(), MagicMock(), MagicMock())
        fresh._store = MagicMock()
        fresh._store.async_load = AsyncMock(return_value=payload)
        fresh.async_refresh_devices = AsyncMock()
        fresh._register_service_devices = MagicMock()
        fresh.hass.async_create_task = MagicMock()
        await fresh.async_initialize()
        assert fresh._critical_overrides == {"d_frz": True}
        assert fresh._controllable_overrides == {"d_pump": False}

    @pytest.mark.asyncio
    async def test_old_store_without_the_new_keys_loads_clean(self):
        reg = UnifiedDeviceRegistry(MagicMock(), MagicMock(), MagicMock(), MagicMock())
        reg._store = MagicMock()
        reg._store.async_load = AsyncMock(return_value={"mappings": {}, "priority_overrides": {}})
        reg.async_refresh_devices = AsyncMock()
        reg._register_service_devices = MagicMock()
        reg.hass.async_create_task = MagicMock()
        await reg.async_initialize()
        assert reg._critical_overrides == {} and reg._controllable_overrides == {}


@pytest.mark.unit
class TestLegacyFlagAdoption650:
    """Users who toggled before the override stores existed must not be handed
    the very reset this issue is about, on upgrade."""

    def _reg_with_lm(self, devices):
        reg = _reg()
        lm = MagicMock()
        lm._devices = devices
        reg._load_manager = lm
        return reg

    @pytest.mark.asyncio
    async def test_adopts_non_default_flags_once(self):
        reg = self._reg_with_lm({
            "energy_dashboard_freezer": {"is_critical": True, "is_controllable": True},
            "energy_dashboard_pond": {"is_critical": False, "is_controllable": False},
        })
        await reg._adopt_legacy_device_flags()
        assert reg._critical_overrides == {"energy_dashboard_freezer": True}
        assert reg._controllable_overrides == {"energy_dashboard_pond": False}
        reg._save_storage.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_defaults_are_not_adopted(self):
        reg = self._reg_with_lm({
            "energy_dashboard_x": {"is_critical": False, "is_controllable": True},
        })
        await reg._adopt_legacy_device_flags()
        assert reg._critical_overrides == {} and reg._controllable_overrides == {}
        reg._save_storage.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_never_overwrites_an_existing_override(self):
        """Otherwise a stale LM value would resurrect on every rebuild."""
        reg = self._reg_with_lm({
            "energy_dashboard_x": {"is_critical": True, "is_controllable": False},
        })
        reg._critical_overrides["energy_dashboard_x"] = False
        reg._controllable_overrides.clear()
        await reg._adopt_legacy_device_flags()
        assert reg._critical_overrides["energy_dashboard_x"] is False

    @pytest.mark.asyncio
    async def test_re_enable_is_not_re_adopted_on_the_next_refresh(self):
        """The regression the fix itself nearly introduced.

        Adoption reads ``lm._devices``, but after the first sync that dict holds
        the REGISTRY's own output. So a per-refresh adoption would see the stale
        ``is_controllable: False``, re-insert the override the user had just
        cleared, and revert the toggle within 35 s — the exact #650 symptom,
        for the re-enable direction. The one-shot flag is what stops it.
        """
        reg = self._reg_with_lm({
            "energy_dashboard_pond": {"is_critical": False, "is_controllable": False},
        })
        await reg._adopt_legacy_device_flags()          # boot: adopt the opt-out
        assert reg._controllable_overrides == {"energy_dashboard_pond": False}

        # user clicks "controllable" back on — the key is REMOVED …
        await reg.async_set_device_flag("energy_dashboard_pond", "controllable", True)
        assert "energy_dashboard_pond" not in reg._controllable_overrides

        # … and the refresh that follows must not resurrect it from the stale LM
        await reg._adopt_legacy_device_flags()
        assert "energy_dashboard_pond" not in reg._controllable_overrides

    @pytest.mark.asyncio
    async def test_adoption_deferred_while_load_manager_is_empty(self):
        """Skipping the empty-LM boot cycle must not burn the one shot."""
        reg = self._reg_with_lm({})
        await reg._adopt_legacy_device_flags()
        assert reg._legacy_flags_adopted is False

        reg._load_manager._devices = {
            "energy_dashboard_frz": {"is_critical": True, "is_controllable": True},
        }
        await reg._adopt_legacy_device_flags()
        assert reg._critical_overrides == {"energy_dashboard_frz": True}

    @pytest.mark.asyncio
    async def test_ignores_non_registry_devices(self):
        reg = self._reg_with_lm({"load_device_ev_charger": {"is_critical": True}})
        await reg._adopt_legacy_device_flags()
        assert reg._critical_overrides == {}


@pytest.mark.unit
class TestSyncCarriesFlagsToLoadManager650:
    def test_sync_writes_the_overridden_values(self):
        reg = _reg()
        lm = MagicMock()
        lm._devices = {}
        reg._load_manager = lm
        reg._service_registrations = {}
        reg._get_power_rating = MagicMock(return_value=1000.0)
        reg._devices = [
            _dev(controllable_override=False),
            _dev(energy_sensor="sensor.freezer_energy", name="Freezer", is_critical=True),
        ]

        reg._sync_to_load_manager()

        pump = lm._devices["energy_dashboard_pond_pump"]
        frz = lm._devices["energy_dashboard_freezer"]
        assert pump["is_controllable"] is False   # the wholesale replace no longer resets it
        assert frz["is_critical"] is True
