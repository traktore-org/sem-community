"""#748 — one physical EV charger, three device rows.

Reported by @jappish84 (on #628, v1.7.5): one Garo charger produced THREE rows
in the Device priority list — the authoritative ``load_device_ev_charger``, an
Energy-Dashboard ``individual_device`` ("Billaddare") whose control entity is
the charger's start/stop switch, and a ``smart_switch`` ``load_device_garo_laddbox``
that appeared the moment the user wired up start/stop (as #700's own reply
advised). All three carry ``switch.garo_laddbox``.

This is BUG_CLASSES class 12 (duplicate device row) — specifically the variant
where the fold is applied at the DISPLAY layer only. #700 suppressed the ED
duplicate inside ``get_devices_for_sensor`` (the card payload) but never removed
it from ``LoadManagement._devices``, and ``_sync_to_load_manager`` deliberately
SPARES every ``load_device_*`` key — so the bogus rows stayed in the
load-management loop and in diagnostics, controllable, behind the EV
controller's back. #700 also missed "Billaddare" entirely because
``_configured_charger_entities()`` knew only the charger's *power* entity, not
its start/stop switch.

These tests pin the fix at the DATA (registry) layer, per the issue's own guard
requirement: "a charger's declared entities are unavailable to load discovery at
the registry level, not that the card happens not to render them."
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
    UnifiedDevice,
)
from custom_components.solar_energy_management.features.load_management import (
    LoadManagementCoordinator,
)
from custom_components.solar_energy_management.features.load_device_discovery import (
    LoadDeviceDiscovery,
)


# The one physical charger, as configured by the reporter.
CHARGER_ROW = {
    "id": "ev_charger",
    "name": "Ny laddare 1",
    "power_entity": "sensor.garo_laddbox_power",
    "current_entity": "number.garo_laddbox_current_limit",
    "start_stop_entity": "switch.garo_laddbox",
    "control_entity": "number.garo_laddbox_current_limit",
}


class _SurplusController:
    def __init__(self, devices=None):
        self._devices = dict(devices or {})

    def get_device(self, did):
        return self._devices.get(did)


class _FakeLoadManager:
    """Just enough of LoadManagementCoordinator for _sync_to_load_manager."""

    def __init__(self, devices):
        self._devices = dict(devices)
        self._save_device_configuration = AsyncMock()


def _reg(load_manager, charger_rows=None, ed_devices=None):
    r = UnifiedDeviceRegistry(
        MagicMock(), _SurplusController(), load_manager, MagicMock()
    )
    r._has_battery = False
    r._devices = list(ed_devices or [])
    r.hass.states.get = MagicMock(return_value=None)
    # Only exercise the DIRECT-string identity path (#748's widening). The
    # registry-device fallback needs a real entity registry; it's covered
    # elsewhere (#700) and would only ADD matches, never remove one.
    r._same_registry_device_as_charger = lambda e: False
    # Distinguish "not passed" (default one charger) from "" (no chargers).
    r.set_ev_chargers([CHARGER_ROW] if charger_rows is None else charger_rows)
    return r


@pytest.mark.unit
class TestChargerIdentitySet:
    def test_identity_set_covers_all_declared_entities(self):
        """#700 saw only power_entity. The set must now include the start/stop
        switch and current number — the entities the ED / smart-switch rows
        actually name."""
        ents = _reg(_FakeLoadManager({}))._configured_charger_entities()
        assert "sensor.garo_laddbox_power" in ents
        assert "switch.garo_laddbox" in ents            # the miss #700 left
        assert "number.garo_laddbox_current_limit" in ents

    def test_power_only_row_still_works(self):
        """A legacy charger row carrying only power_entity degrades to the old
        power-only behaviour, not an error."""
        ents = _reg(
            _FakeLoadManager({}),
            charger_rows=[{"id": "c1", "power_entity": "sensor.c1_power"}],
        )._configured_charger_entities()
        assert ents == {"sensor.c1_power"}


@pytest.mark.unit
class TestDataLayerDepersist:
    """The core fix: _sync_to_load_manager drops the persisted duplicates from
    LoadManagement._devices, keeping only the authoritative charger row."""

    def _seeded_lm(self):
        return _FakeLoadManager({
            # authoritative charger row — MUST survive (it IS the charger)
            "load_device_ev_charger": {
                "device_type": "ev_charger",
                "switch_entity": "number.garo_laddbox_current_limit",
                "power_entity": "sensor.garo_laddbox_power",
                "charger_id": "ev_charger",
            },
            # smart_switch dup — persisted, immortal (spared by the load_device_*
            # prune). Shares the charger's start/stop switch → MUST be dropped.
            "load_device_garo_laddbox": {
                "device_type": "smart_switch",
                "switch_entity": "switch.garo_laddbox",
                "power_entity": "sensor.garo_laddbox_power",
            },
            # a genuinely unrelated load — MUST survive.
            "load_device_dishwasher": {
                "device_type": "smart_switch",
                "switch_entity": "switch.dishwasher",
                "power_entity": "sensor.dishwasher_power",
            },
        })

    def test_smart_switch_duplicate_is_dropped(self):
        lm = self._seeded_lm()
        pruned = _reg(lm)._sync_to_load_manager()
        assert pruned is True
        assert "load_device_garo_laddbox" not in lm._devices     # dup dropped
        assert "load_device_ev_charger" in lm._devices           # charger kept
        assert "load_device_dishwasher" in lm._devices           # unrelated kept

    def test_authoritative_charger_row_never_pruned_as_its_own_duplicate(self):
        """The charger row names the charger's own current number — the exact
        entity in the identity set. It must never be dropped as a duplicate of
        itself."""
        lm = _FakeLoadManager({
            "load_device_ev_charger": {
                "device_type": "ev_charger",
                "switch_entity": "number.garo_laddbox_current_limit",
                "power_entity": "sensor.garo_laddbox_power",
                "charger_id": "ev_charger",
            },
        })
        _reg(lm)._sync_to_load_manager()
        assert "load_device_ev_charger" in lm._devices

    def test_ed_manual_mapping_duplicate_is_dropped(self):
        """"Billaddare": an ED individual device manually mapped to the
        charger's start/stop switch. It re-enters LoadManagement via the sync's
        add loop (it's an ED registry device); the reconcile must then drop it —
        its CONTROL entity is the charger's switch, though its own power/energy
        sensors are not charger entities (exactly why #700 missed it)."""
        billaddare = UnifiedDevice(
            energy_sensor="sensor.garo_laddbox_session",
            power_sensor=None,
            name="Billaddare",
            priority=5,
            control={"type": "switch", "entity": "switch.garo_laddbox"},
            has_manual_mapping=True,
        )
        assert billaddare.device_id == "energy_dashboard_garo_laddbox_session"
        lm = _FakeLoadManager({
            "load_device_ev_charger": {
                "device_type": "ev_charger",
                "switch_entity": "number.garo_laddbox_current_limit",
                "power_entity": "sensor.garo_laddbox_power",
                "charger_id": "ev_charger",
            },
        })
        pruned = _reg(lm, ed_devices=[billaddare])._sync_to_load_manager()
        assert pruned is True
        assert billaddare.device_id not in lm._devices

    def test_no_chargers_configured_prunes_nothing(self):
        lm = self._seeded_lm()
        pruned = _reg(lm, charger_rows=[])._sync_to_load_manager()
        assert pruned is False
        assert "load_device_garo_laddbox" in lm._devices          # untouched

    def test_id_less_charger_row_fails_safe(self):
        """A charger row with no id can't build its protected authoritative
        set — the prune must fail SAFE (touch nothing), never risk deleting the
        charger's own load row."""
        lm = self._seeded_lm()
        pruned = _reg(
            lm, charger_rows=[{"power_entity": "sensor.garo_laddbox_power",
                               "start_stop_entity": "switch.garo_laddbox"}],
        )._sync_to_load_manager()
        assert pruned is False
        assert "load_device_garo_laddbox" in lm._devices          # untouched
        assert "load_device_ev_charger" in lm._devices


@pytest.mark.unit
class TestReconcileRunsWithoutEnergyDashboard:
    """HIGH-review fix: the persisted smart-switch duplicate must be dropped
    even on installs with no Energy Dashboard individual devices — where
    async_refresh_devices early-returns before the sync. The reconcile runs
    BEFORE those returns, so it still fires."""

    def _seeded_lm(self):
        return _FakeLoadManager({
            "load_device_ev_charger": {
                "device_type": "ev_charger",
                "switch_entity": "number.garo_laddbox_current_limit",
                "power_entity": "sensor.garo_laddbox_power",
                "charger_id": "ev_charger",
            },
            "load_device_garo_laddbox": {
                "device_type": "smart_switch",
                "switch_entity": "switch.garo_laddbox",
                "power_entity": "sensor.garo_laddbox_power",
            },
        })

    async def test_direct_reconcile_helper_drops_and_persists(self):
        lm = self._seeded_lm()
        reg = _reg(lm)
        await reg._reconcile_charger_dups_and_persist()
        assert "load_device_garo_laddbox" not in lm._devices
        assert "load_device_ev_charger" in lm._devices
        lm._save_device_configuration.assert_awaited()            # de-persisted

    async def test_async_refresh_prunes_when_no_energy_dashboard(self):
        """No ED at all → async_refresh_devices returns at the first guard, but
        the persisted duplicate is already gone."""
        lm = self._seeded_lm()
        reg = _reg(lm)
        with patch(
            "custom_components.solar_energy_management.features."
            "device_registry.read_energy_dashboard_config",
            new=AsyncMock(return_value=None),
        ):
            await reg.async_refresh_devices()
        assert "load_device_garo_laddbox" not in lm._devices
        assert "load_device_ev_charger" in lm._devices
        lm._save_device_configuration.assert_awaited()


@pytest.mark.unit
class TestDisplayLayerFold:
    """The card payload must also fold the ED row whose CONTROL entity is the
    charger's switch (the #700 miss, completed at the display layer)."""

    def test_billaddare_folded_in_card_by_control_entity(self):
        billaddare = UnifiedDevice(
            energy_sensor="sensor.garo_laddbox_session",
            power_sensor=None,
            name="Billaddare",
            priority=5,
            control={"type": "switch", "entity": "switch.garo_laddbox"},
            has_manual_mapping=True,
        )
        devs = _reg(_FakeLoadManager({}), ed_devices=[billaddare]).get_devices_for_sensor()
        assert billaddare.device_id not in devs

    def test_unrelated_ed_device_untouched_in_card(self):
        other = UnifiedDevice(
            energy_sensor="sensor.dishwasher_energy",
            power_sensor="sensor.dishwasher_power",
            name="Dishwasher",
            priority=6,
            control={"type": "switch", "entity": "switch.dishwasher"},
        )
        devs = _reg(_FakeLoadManager({}), ed_devices=[other]).get_devices_for_sensor()
        assert other.device_id in devs


@pytest.mark.unit
class TestDiscoveryExclusion:
    """Pattern discovery must skip a switch already claimed as a charger's
    start/stop control — the third duplicate row's point of creation."""

    def _discovery_with_entities(self, entities):
        hass = MagicMock()
        hass.states.async_entity_ids = MagicMock(return_value=list(entities))

        def _get(eid):
            return SimpleNamespace(
                state="off" if eid.startswith("switch.") else "1500",
                attributes={"friendly_name": eid},
            )

        hass.states.get = MagicMock(side_effect=_get)
        d = LoadDeviceDiscovery(hass)
        return d

    def test_charger_switch_excluded_from_discovery(self):
        d = self._discovery_with_entities([
            "switch.garo_laddbox", "sensor.garo_laddbox_power",
            "switch.dishwasher", "sensor.dishwasher_power",
        ])
        found = d.discover_controllable_devices(
            excluded_entities={"switch.garo_laddbox", "sensor.garo_laddbox_power"}
        )
        assert "load_device_garo_laddbox" not in found
        # the genuinely-unclaimed smart plug is still discovered
        assert "load_device_dishwasher" in found

    def test_no_exclusion_set_is_backwards_compatible(self):
        d = self._discovery_with_entities([
            "switch.dishwasher", "sensor.dishwasher_power",
        ])
        found = d.discover_controllable_devices()
        assert "load_device_dishwasher" in found


@pytest.mark.unit
class TestRegisterChargerCarriesControlEntities:
    """register_ev_charger must store the stop switch + status sensor so
    _charger_claimed_entities can feed them to discovery (unified-inactive
    path)."""

    async def test_register_and_claimed_entities(self):
        lm = LoadManagementCoordinator.__new__(LoadManagementCoordinator)
        lm._devices = {}
        lm.hass = MagicMock()
        lm.hass.states.get = MagicMock(
            return_value=SimpleNamespace(state="0", attributes={})
        )
        lm._save_device_configuration = AsyncMock()
        lm._trigger_callbacks = MagicMock()

        ok = await lm.register_ev_charger(
            current_control_entity="number.garo_laddbox_current_limit",
            power_entity="sensor.garo_laddbox_power",
            charger_id="ev_charger",
            charger_name="Ny laddare 1",
            start_stop_entity="switch.garo_laddbox",
            status_entity="sensor.garo_laddbox_status",
        )
        assert ok is True
        row = lm._devices["load_device_ev_charger"]
        assert row["start_stop_entity"] == "switch.garo_laddbox"
        assert row["status_entity"] == "sensor.garo_laddbox_status"

        claimed = lm._charger_claimed_entities()
        assert "switch.garo_laddbox" in claimed          # the stop switch
        assert "number.garo_laddbox_current_limit" in claimed
        assert "sensor.garo_laddbox_power" in claimed
        assert "sensor.garo_laddbox_status" in claimed
