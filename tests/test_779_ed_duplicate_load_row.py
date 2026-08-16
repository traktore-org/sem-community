"""#779 — a device set to Mode=Off is still switched off (regression in 2.0.0-beta.2).

Reported by @onkelfu (SolarEdge Modbus + KEBA P30). After upgrading to 2.0, SEM
switched off Shelly devices it should only monitor — a dishwasher configured
with Mode=Off in the SEM UI got turned off again minutes after being switched on
by hand ("via Home Assistant Core Integration"). The diagnostics showed the same
appliance TWICE:

    energy_dashboard_spuelmaschine  → individual_device, is_controllable: true
    load_device_spuelmaschine       → smart_switch,      is_controllable: true

Root cause (BUG_CLASSES class 12 — duplicate device row): with the
UnifiedDeviceRegistry active, LoadManagement's own pattern discovery is guarded
off, so a ``load_device_<slug>`` smart-switch row can only be one a pre-2.0
version persisted. The registry re-discovers the same physical device from the
Energy Dashboard as ``energy_dashboard_<slug>`` — the authoritative row that
carries the user's Mode setting (``control_mode``). The stale ``load_device_*``
twin has NO ``control_mode`` (so Mode=Off on the ED row never reached it) and
stays ``is_controllable``/sheddable, so the peak-shed loop actuated the
appliance behind the user's back. #748 folded the CHARGER-duplicate variant of
this at the data layer but matched only a charger's entities — a plain smart
plug shares none, so it survived. #436's spare keeps every ``load_device_*`` key
alive, so the ghost is immortal across restarts.

Fix: ``_prune_ed_duplicate_lm_rows`` — fold, at the data layer, any
``load_device_*`` row whose switch/control entity IS the actuation surface an
ED device controls (dedup on the shared CONTROL entity, not the id — never on a
power/energy sensor, which #744 can derive or share across a multi-channel
device's two loads), then de-persist. A ``load_device_*`` row with no matching
ED twin is the device's only representation and is left untouched.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
    UnifiedDevice,
)


@pytest.fixture
def config_entry_lm():
    """A config entry with load management enabled (peak limit set)."""
    entry = MagicMock()
    entry.data = {}
    entry.options = {
        "load_management_enabled": True,
        "target_peak_limit": 5.0,
        "warning_peak_level": 4.5,
        "emergency_peak_level": 6.0,
        "peak_hysteresis": 0.3,
    }
    entry.entry_id = "test_entry"
    return entry


class _SurplusController:
    def __init__(self, devices=None):
        self._devices = dict(devices or {})

    def get_device(self, did):
        return self._devices.get(did)


class _FakeLoadManager:
    """Just enough of LoadManagementCoordinator for the data-layer fold."""

    def __init__(self, devices, shed=None):
        self._devices = dict(devices)
        self._devices_shed = list(shed or [])
        self._save_device_configuration = AsyncMock()


def _ed_dishwasher():
    """The registry's authoritative row: the dishwasher as an ED individual
    device whose discovered control IS the Shelly switch. is_controllable
    because it has a control config."""
    return UnifiedDevice(
        energy_sensor="sensor.spuelmaschine_energy",
        power_sensor="sensor.spuelmaschine_power",
        name="Spuelmaschine",
        priority=10,
        control={"type": "switch", "entity": "switch.spuelmaschine"},
    )


def _reg(load_manager, ed_devices=None, service_regs=None):
    r = UnifiedDeviceRegistry(
        MagicMock(), _SurplusController(), load_manager, MagicMock()
    )
    r._has_battery = False
    r._devices = list(ed_devices or [])
    if service_regs is not None:
        r._service_registrations = dict(service_regs)
    r.hass.states.get = MagicMock(return_value=None)
    return r


def _seed_lm():
    return _FakeLoadManager({
        # the legacy ghost — SAME Shelly switch as the ED dishwasher, no
        # control_mode. MUST be dropped.
        "load_device_spuelmaschine": {
            "device_type": "smart_switch",
            "switch_entity": "switch.spuelmaschine",
            "power_entity": "sensor.spuelmaschine_power",
            "is_controllable": True,
        },
        # a genuinely unrelated smart plug with NO ED twin — MUST survive
        # (it's the device's only representation; cf. #748 dishwasher).
        "load_device_freezer": {
            "device_type": "smart_switch",
            "switch_entity": "switch.freezer",
            "power_entity": "sensor.freezer_power",
            "is_controllable": True,
        },
        # authoritative charger row — MUST survive.
        "load_device_ev_charger": {
            "device_type": "ev_charger",
            "switch_entity": "number.keba_current",
            "power_entity": "sensor.keba_power",
            "charger_id": "ev_charger",
        },
    })


@pytest.mark.unit
class TestDataLayerFold:
    def test_ed_duplicate_ghost_is_dropped(self):
        lm = _seed_lm()
        reg = _reg(lm, ed_devices=[_ed_dishwasher()])
        pruned = reg._prune_ed_duplicate_lm_rows()
        assert pruned is True
        assert "load_device_spuelmaschine" not in lm._devices   # ghost dropped
        assert "load_device_freezer" in lm._devices             # no ED twin: kept
        assert "load_device_ev_charger" in lm._devices          # charger kept

    def test_shared_power_sensor_alone_does_not_fold_a_neighbour(self):
        """The match is on the CONTROL surface only — NOT power/energy. A
        multi-channel device (a Shelly 2PM) can present two distinct ED loads
        that resolve to the same whole-device power sensor (#744 derived /
        shortest-name fallback); a ghost that shares only that power sensor but
        has its OWN distinct switch is a different device and MUST survive."""
        ed = UnifiedDevice(
            energy_sensor="sensor.shelly2pm_energy",
            power_sensor="sensor.shelly2pm_power",           # shared whole-device power
            name="Channel A",
            priority=10,
            control={"type": "switch", "entity": "switch.shelly2pm_channel_a"},
        )
        lm = _FakeLoadManager({
            "load_device_channel_b": {
                "device_type": "smart_switch",
                "switch_entity": "switch.shelly2pm_channel_b",   # DIFFERENT relay
                "power_entity": "sensor.shelly2pm_power",         # same power sensor
                "is_controllable": True,
            },
        })
        assert _reg(lm, ed_devices=[ed])._prune_ed_duplicate_lm_rows() is False
        assert "load_device_channel_b" in lm._devices            # neighbour kept

    def test_no_control_ed_row_does_not_fold_the_only_controllable_row(self):
        """An ED row that discovered NO control (is_controllable False) is not
        an authoritative actuation surface — it must NOT fold the ghost that
        holds the device's only switch, or the device becomes uncontrollable."""
        ed = UnifiedDevice(
            energy_sensor="sensor.spuelmaschine_energy",
            power_sensor="sensor.spuelmaschine_power",
            name="Spuelmaschine",
            priority=10,
            control=None,                                    # no control surface
        )
        lm = _seed_lm()
        assert _reg(lm, ed_devices=[ed])._prune_ed_duplicate_lm_rows() is False
        assert "load_device_spuelmaschine" in lm._devices

    def test_no_ed_devices_prunes_nothing(self):
        lm = _seed_lm()
        pruned = _reg(lm, ed_devices=[])._prune_ed_duplicate_lm_rows()
        assert pruned is False
        assert "load_device_spuelmaschine" in lm._devices       # untouched

    def test_service_registration_never_folded(self):
        """A load_device_* id that is an explicit service registration is spared
        even when it shares an entity with an ED device."""
        lm = _FakeLoadManager({
            "load_device_spuelmaschine": {
                "device_type": "smart_switch",
                "switch_entity": "switch.spuelmaschine",
                "power_entity": "sensor.spuelmaschine_power",
            },
        })
        reg = _reg(lm, ed_devices=[_ed_dishwasher()],
                   service_regs={"load_device_spuelmaschine": {}})
        assert reg._prune_ed_duplicate_lm_rows() is False
        assert "load_device_spuelmaschine" in lm._devices

    def test_pruned_ghost_removed_from_shed_list(self):
        """A ghost currently shed must also leave _devices_shed — else
        _restore_loads would KeyError indexing the removed row."""
        lm = _seed_lm()
        lm._devices_shed = ["load_device_spuelmaschine"]
        _reg(lm, ed_devices=[_ed_dishwasher()])._prune_ed_duplicate_lm_rows()
        assert "load_device_spuelmaschine" not in lm._devices_shed

    def test_sync_returns_true_and_depersists(self):
        """Full sync path: the fold makes _sync_to_load_manager report a change,
        which the caller uses to de-persist the ghost out of the store."""
        lm = _seed_lm()
        reg = _reg(lm, ed_devices=[_ed_dishwasher()])
        # _sync_to_load_manager re-adds the ED rows then folds the ghost.
        assert reg._sync_to_load_manager() is True
        assert "load_device_spuelmaschine" not in lm._devices
        assert "energy_dashboard_spuelmaschine" in lm._devices  # ED row present


@pytest.mark.unit
class TestShedBehaviour:
    """End-to-end: the ghost was sheddable (that is the harm); after the fold it
    is gone, so the shed loop can no longer touch the appliance. Uses the REAL
    LoadManagementCoordinator so the assertion pins actual behaviour, not a
    restatement of the prune."""

    def _real_lm(self, mock_hass, config_entry_lm):
        from custom_components.solar_energy_management.load_management import (
            LoadManagementCoordinator,
        )
        with patch(
            "custom_components.solar_energy_management.features."
            "load_management.LoadDeviceDiscovery"
        ) as MockDiscovery, patch(
            "custom_components.solar_energy_management.features."
            "load_management.Store"
        ):
            disc = MagicMock()
            disc.get_device_current_state = MagicMock(
                return_value={"is_on": True, "current_power": 1500}
            )
            MockDiscovery.return_value = disc
            lm = LoadManagementCoordinator(mock_hass, config_entry_lm)
        lm._unified_registry_active = True
        return lm

    def test_ghost_sheddable_before_fold_gone_after(self, mock_hass, config_entry_lm):
        lm = self._real_lm(mock_hass, config_entry_lm)
        lm._devices = {
            "load_device_spuelmaschine": {
                "device_type": "smart_switch",
                "switch_entity": "switch.spuelmaschine",
                "power_entity": "sensor.spuelmaschine_power",
                "is_controllable": True,
                "is_available": True,
                "is_critical": False,
                "priority": 5,
                # NOTE: no control_mode — this is exactly why Mode=Off (set on
                # the ED twin) never protected it.
            },
        }
        # The harm: with no control_mode, the ghost is a live shed candidate.
        candidates = dict(lm._get_devices_for_shedding())
        assert "load_device_spuelmaschine" in candidates

        # The fix: the registry folds the ED-duplicate ghost.
        reg = _reg(lm, ed_devices=[_ed_dishwasher()])
        assert reg._prune_ed_duplicate_lm_rows() is True

        # Now it cannot be shed — it is no longer a device at all.
        candidates_after = dict(lm._get_devices_for_shedding())
        assert "load_device_spuelmaschine" not in candidates_after
