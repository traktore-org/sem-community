"""#781 — a configuration knob is not a load.

onkelfu's diagnostics: 24 of his 50 Load-Management rows are
``load_device_wled_*`` — "umkehren", "einfrieren", "senden/empfang
synchronisieren", "nachtlicht". Every one is a WLED *setting* exposed as a
``switch.*``. They arrived because pattern discovery admits any ``switch.*``
that can be paired with a power sensor, and one ``sensor.wled_treppe_power``
pairs with all of them: ``_names_match`` is a substring test, so the segment
name is inside every sibling switch's name.

The consequence is not cosmetic. Each row lands ``is_controllable`` and
``peak_only``, so a peak event can flip the LED strip's *reverse* setting
looking for watts that were never there (``W = 0``).

HA already answers "is this a knob or a load": ``entity_category``. A
CONFIG or DIAGNOSTIC entity is a device's own configuration surface, never
its primary control — the same registry-driven shape as the #744 light
filter, and equally unguessable from the entity_id.

Two halves, because a filter alone changes nothing for onkelfu: pattern
discovery must not admit them, AND the rows a pre-2.0 version already
persisted must retire — ``load_device_*`` keys are spared by the #436
prune, so nothing else would ever remove them.

(#1419) Both halves are now wider: pattern discovery is gone, and the sync
keeps a ``load_device_*`` row only when it is a charger's.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.features import (
    load_device_discovery as ldd,
)
from custom_components.solar_energy_management.features.load_device_discovery import (
    LoadDeviceDiscovery,
)
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)


class _Entry:
    def __init__(self, entity_id, device_id=None, entity_category=None,
                 disabled_by=None):
        self.entity_id = entity_id
        self.device_id = device_id
        self.domain = entity_id.split(".", 1)[0]
        self.entity_category = entity_category
        self.disabled_by = disabled_by


class _Registry:
    def __init__(self, entries):
        self._entries = list(entries)
        self._by_id = {e.entity_id: e for e in self._entries}

    def async_get(self, entity_id):
        return self._by_id.get(entity_id)


class _Hass:
    def __init__(self, states):
        self._states = {
            k: MagicMock(state=str(v), attributes={}) for k, v in states.items()
        }
        self.states = MagicMock()
        self.states.get = self._states.get
        self.states.async_entity_ids = lambda: list(self._states)


def _discovery(monkeypatch, states, entries):
    reg = _Registry(entries)
    monkeypatch.setattr(ldd.entity_registry, "async_get", lambda hass: reg)
    disc = LoadDeviceDiscovery.__new__(LoadDeviceDiscovery)
    disc.hass = _Hass(states)
    disc._entity_registry = reg
    return disc


# onkelfu's shape: one WLED strip, one power sensor, four setting switches
# and no primary switch at all (the strip's own control is ``light.*``).
WLED_STATES = {
    "switch.wled_treppe_umkehren": "off",
    "switch.wled_treppe_einfrieren": "off",
    "switch.wled_treppe_nachtlicht": "off",
    "sensor.wled_treppe_power": "0.0",
}
WLED_ENTRIES = [
    _Entry("switch.wled_treppe_umkehren", "wled", entity_category="config"),
    _Entry("switch.wled_treppe_einfrieren", "wled", entity_category="config"),
    _Entry("switch.wled_treppe_nachtlicht", "wled", entity_category="config"),
    _Entry("sensor.wled_treppe_power", "wled"),
]


# (#1419) TestDiscoveryRefusesAConfigurationSurface stood here: pattern
# discovery refusing a WLED setting. Pattern discovery is gone — no switch
# becomes a load by its name any more — so there is nothing left to refuse.


@pytest.mark.unit
class TestTheControlPickRefusesOneToo:
    """The same class on the OTHER discovery path. An Energy-Dashboard
    consumer is imported for its energy row and then asked "what switches
    this?" — ``_find_control_by_name`` answers with any ``switch.*`` whose
    id merely CONTAINS the base name. For a WLED strip that is its reverse
    setting, and SEM would then "control" the load by flipping it."""

    def test_a_setting_is_not_chosen_as_the_devices_control(self, monkeypatch):
        disc = _discovery(
            monkeypatch,
            {"switch.wled_treppe_umkehren": "off"},
            [_Entry("switch.wled_treppe_umkehren", "wled",
                    entity_category="config")],
        )
        assert disc._find_control_by_name("wled_treppe") is None

    def test_the_real_switch_is_still_found_by_name(self, monkeypatch):
        disc = _discovery(
            monkeypatch,
            {"switch.dishwasher": "on"},
            [_Entry("switch.dishwasher", "dw")],
        )
        found = disc._find_control_by_name("dishwasher")
        assert found is not None and found["entity"] == "switch.dishwasher"

    def test_a_shelly_setting_is_not_chosen_as_the_control(self, monkeypatch):
        """The brand path matches on a substring of the base name too — a
        Shelly's ``auto off`` timer is a setting, not the relay."""
        disc = _discovery(
            monkeypatch,
            {"switch.shelly_boiler_auto_off": "off"},
            [_Entry("switch.shelly_boiler_auto_off", "shelly",
                    entity_category="config")],
        )
        assert disc._find_control_by_integration("sensor.shelly_boiler_energy") \
            is None

    def test_the_shelly_relay_is_still_found(self, monkeypatch):
        disc = _discovery(
            monkeypatch,
            {"switch.shelly_boiler": "on"},
            [_Entry("switch.shelly_boiler", "shelly")],
        )
        found = disc._find_control_by_integration("sensor.shelly_boiler_energy")
        assert found is not None and found["entity"] == "switch.shelly_boiler"

    def test_an_esphome_diagnostic_switch_is_not_chosen(self, monkeypatch):
        """ESPHome nodes publish a ``restart`` switch on every device."""
        disc = _discovery(
            monkeypatch,
            {"switch.esphome_pump_restart": "off"},
            [_Entry("switch.esphome_pump_restart", "esp",
                    entity_category="config")],
        )
        assert disc._find_control_by_integration("sensor.esphome_pump_energy") \
            is None


# (#1419) TestThePowerSensorBindsToItsOwnChannel stood here: the power
# sensor pattern discovery paired with a switch. Gone with that discovery.


# ── retirement: the rows a pre-2.0 install already persisted ───────────────
class _FakeLoadManager:
    def __init__(self, devices):
        self._devices = dict(devices)
        self._save_device_configuration = AsyncMock()


def _registry_with_rows(monkeypatch, rows, entries, chargers=None,
                        service_regs=None):
    disc = _discovery(monkeypatch, {}, entries)
    lm = _FakeLoadManager(rows)
    reg = UnifiedDeviceRegistry(MagicMock(), MagicMock(), lm, disc)
    reg._devices = []
    reg._ev_charger_rows = list(chargers or [])
    reg._service_registrations = dict(service_regs or {})
    return reg, lm


PERSISTED = {
    "load_device_wled_treppe_umkehren": {
        "switch_entity": "switch.wled_treppe_umkehren",
        "power_entity": "sensor.wled_treppe_power",
        "is_controllable": True,
    },
    "load_device_dishwasher": {
        "switch_entity": "switch.dishwasher",
        "power_entity": "sensor.dishwasher_power",
        "is_controllable": True,
    },
}
PERSISTED_ENTRIES = [
    _Entry("switch.wled_treppe_umkehren", "wled", entity_category="config"),
    _Entry("switch.dishwasher", "dw"),
]


@pytest.mark.unit
class TestPersistedConfigRowsRetire:
    """(#1419) The sync's keep rule retires these now: it keeps a
    ``load_device_*`` row only when it is a charger's. #781's own prune for
    a setting switch, and #779's for an Energy Dashboard twin, are gone."""

    def test_a_persisted_wled_setting_row_is_dropped(self, monkeypatch):
        reg, lm = _registry_with_rows(monkeypatch, PERSISTED, PERSISTED_ENTRIES)
        assert reg._sync_to_load_manager() is True
        assert "load_device_wled_treppe_umkehren" not in lm._devices

    def test_the_plain_appliance_row_is_dropped_too(self, monkeypatch):
        """#781 kept it as a real load. (#1419) It was never on the Devices
        card either — nobody could set it — so it goes as well."""
        reg, lm = _registry_with_rows(monkeypatch, PERSISTED, PERSISTED_ENTRIES)
        reg._sync_to_load_manager()
        assert "load_device_dishwasher" not in lm._devices

    def test_an_authoritative_charger_row_is_never_retired(self, monkeypatch):
        """A charger's own row names charger entities by design — and a
        charger control can legitimately carry a category."""
        rows = {"load_device_keba": {
            "switch_entity": "switch.keba_charging_enable",
            "device_type": "ev_charger",
        }}
        entries = [_Entry("switch.keba_charging_enable", "keba",
                          entity_category="config")]
        reg, lm = _registry_with_rows(
            monkeypatch, rows, entries, chargers=[{"id": "keba"}])
        assert reg._sync_to_load_manager() is False
        assert "load_device_keba" in lm._devices

    def test_an_explicit_service_registration_is_never_retired(self, monkeypatch):
        """A user who registered it by hand made a decision, not a guess —
        the documented escape hatch (#559 Phase 0)."""
        rows = {"load_device_stage_relay": {
            "switch_entity": "switch.stage_relay"}}
        entries = [_Entry("switch.stage_relay", "stage",
                          entity_category="config")]
        reg, lm = _registry_with_rows(
            monkeypatch, rows, entries,
            service_regs={"load_device_stage_relay": {
                "entity_id": "switch.stage_relay"}})
        reg._service_lm_row = MagicMock(
            return_value={"switch_entity": "switch.stage_relay"})
        reg._sync_to_load_manager()
        assert "load_device_stage_relay" in lm._devices

    def test_the_removal_is_persisted_by_the_sync(self, monkeypatch):
        """LoadManagement reloads its own store at init — a drop that isn't
        written back is undone by the next restart (the #744 lesson)."""
        reg, lm = _registry_with_rows(monkeypatch, PERSISTED, PERSISTED_ENTRIES)
        assert reg._sync_to_load_manager() is True
        assert "load_device_wled_treppe_umkehren" not in lm._devices


class TestTheControlBindsToItsOwnChannel:
    """#781, the control half — a wrong bind here ACTUATES the wrong circuit.

    The power-sensor half already prefers an exact base-name match. The
    control paths did not: each loop returned the FIRST loose hit. Two loose
    rules feed them, and on a multi-channel device both are wrong in the same
    way — they discard exactly the character that names the channel.

    ``_names_match``'s last resort strips every digit, so ``shelly_kanal_1``
    and ``shelly_kanal_2`` clean to the same string; a bare substring test
    makes ``shelly_kanal_1`` match ``shelly_kanal_10``. Binding channel 1's
    energy to channel 2's relay means SEM sheds the freezer believing it is
    the towel heater.

    So on the control side digits are load-bearing: an exact base name wins,
    a substring is accepted only at an ``_`` boundary, and a match that
    survives only by dropping digits is not a match at all. "No control
    found" is the honest answer — the same reasoning as
    ``_find_control_in_device``'s strict filter.
    """

    # Two relays and two meters on one Shelly Pro, plus a third channel whose
    # number merely starts with the first channel's digits.
    MULTI = {
        "switch.shelly_kanal_2": "on",
        "switch.shelly_kanal_10": "on",
        "switch.shelly_kanal_1": "on",
        "sensor.shelly_kanal_1_energy": "1.0",
    }
    MULTI_ENTRIES = [
        _Entry("switch.shelly_kanal_2", "shelly"),
        _Entry("switch.shelly_kanal_10", "shelly"),
        _Entry("switch.shelly_kanal_1", "shelly"),
        _Entry("sensor.shelly_kanal_1_energy", "shelly"),
    ]

    def test_the_name_path_takes_its_own_relay_not_a_neighbour(
            self, monkeypatch):
        """``switch.shelly_kanal_2`` is listed first and contains no part of
        channel 1's name; ``switch.shelly_kanal_10`` merely starts with it."""
        disc = _discovery(monkeypatch, self.MULTI, self.MULTI_ENTRIES)
        got = disc._find_control_by_name("shelly_kanal_1")
        assert got is not None
        assert got["entity"] == "switch.shelly_kanal_1"

    def test_a_neighbour_is_not_a_fallback_when_the_relay_is_absent(
            self, monkeypatch):
        """Channel 1 has a meter but no relay of its own. Channel 2's relay
        is not a lesser answer — it is a wrong one."""
        states = {k: v for k, v in self.MULTI.items()
                  if k != "switch.shelly_kanal_1"}
        entries = [e for e in self.MULTI_ENTRIES
                   if e.entity_id != "switch.shelly_kanal_1"]
        disc = _discovery(monkeypatch, states, entries)
        assert disc._find_control_by_name("shelly_kanal_1") is None

    def test_ten_is_not_one(self, monkeypatch):
        """The substring test that made ``kanal_1`` match ``kanal_10``."""
        states = {"switch.shelly_kanal_10": "on",
                  "sensor.shelly_kanal_1_energy": "1.0"}
        entries = [_Entry("switch.shelly_kanal_10", "shelly"),
                   _Entry("sensor.shelly_kanal_1_energy", "shelly")]
        disc = _discovery(monkeypatch, states, entries)
        assert disc._find_control_by_name("shelly_kanal_1") is None

    def test_a_suffixed_relay_is_still_the_same_channel(self, monkeypatch):
        """A boundary match is still a match — ``_relay`` names the same
        channel, it does not renumber it."""
        states = {"switch.shelly_kanal_1_relay": "on",
                  "sensor.shelly_kanal_1_energy": "1.0"}
        entries = [_Entry("switch.shelly_kanal_1_relay", "shelly"),
                   _Entry("sensor.shelly_kanal_1_energy", "shelly")]
        disc = _discovery(monkeypatch, states, entries)
        got = disc._find_control_by_name("shelly_kanal_1")
        assert got is not None
        assert got["entity"] == "switch.shelly_kanal_1_relay"

    def test_the_shelly_brand_path_stops_stripping_digits(self, monkeypatch):
        """The live shape: ``_names_match`` cleans both channels to
        ``shellykanal`` and channel 2's relay is reached first."""
        disc = _discovery(monkeypatch, self.MULTI, self.MULTI_ENTRIES)
        got = disc._find_control_by_integration("sensor.shelly_kanal_1_energy")
        assert got is not None
        assert got["entity"] == "switch.shelly_kanal_1"

    def test_the_shelly_brand_path_refuses_a_neighbour_outright(
            self, monkeypatch):
        """No relay for this channel — the digit-stripped sibling must not
        stand in for it."""
        states = {"switch.shelly_kanal_2": "on",
                  "sensor.shelly_kanal_1_energy": "1.0"}
        entries = [_Entry("switch.shelly_kanal_2", "shelly"),
                   _Entry("sensor.shelly_kanal_1_energy", "shelly")]
        disc = _discovery(monkeypatch, states, entries)
        assert disc._find_control_by_integration(
            "sensor.shelly_kanal_1_energy") is None

    def test_the_esphome_branch_takes_its_own_pump(self, monkeypatch):
        """``esphome_pump_1`` must not adopt ``esphome_pump_10``'s switch."""
        states = {"switch.esphome_pump_10": "on",
                  "switch.esphome_pump_1": "on",
                  "sensor.esphome_pump_1_energy": "1.0"}
        entries = [_Entry("switch.esphome_pump_10", "esphome"),
                   _Entry("switch.esphome_pump_1", "esphome"),
                   _Entry("sensor.esphome_pump_1_energy", "esphome")]
        disc = _discovery(monkeypatch, states, entries)
        got = disc._find_control_by_integration("sensor.esphome_pump_1_energy")
        assert got is not None
        assert got["entity"] == "switch.esphome_pump_1"

    def test_an_unrelated_name_still_matches_at_a_boundary(self, monkeypatch):
        """The rule must not break ordinary naming: a base name that is a
        boundary-suffix of the switch's name is the same device."""
        states = {"switch.wohnzimmer_steckdose": "on",
                  "sensor.steckdose_energy": "1.0"}
        entries = [_Entry("switch.wohnzimmer_steckdose", "plug"),
                   _Entry("sensor.steckdose_energy", "plug")]
        disc = _discovery(monkeypatch, states, entries)
        got = disc._find_control_by_name("steckdose")
        assert got is not None
        assert got["entity"] == "switch.wohnzimmer_steckdose"
