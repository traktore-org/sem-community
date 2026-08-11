"""#744 — a load device that IS drawing power reads "Off" / shows the 1 kW
placeholder in the Load Management priority view.

Split from the #744 enhancement (sub-kW formatting) and the #745 defect (a
*switch*-controlled load reading Off); this half is the ROOT CAUSE the #745
fix could not reach.

The Load Management priority payload (``UnifiedDeviceRegistry.get_devices_for_sensor``)
reads on/off and live watts from ``UnifiedDevice.power_sensor``. That field is
populated only from the Energy Dashboard's ``stat_rate`` / ``stat_power`` power
link — which HA's individual-device UI does not collect: it asks for the kWh
energy sensor only. So ``power_sensor`` is ``None`` for virtually every load,
``current_power`` reads 0, and a device with no discoverable on/off control
entity (a power-only Shelly PM mini at 400 W, a furnace blower at 250 W) renders
"Off" and shows the 1 kW rated placeholder — exactly @Azlinon's report on beta.12.

solar / grid / battery already recover a missing power link by deriving the
companion power sensor from the energy sensor's own HA device
(``_derive_missing_power_sensors`` — #250), and the SurplusController's own
device factory does the same for a kWh-only load (#600 ``surplus_device_from_spec``).
The registry / DISPLAY path had no such derivation. The fix adds
``_find_load_power_sensor`` and calls it in both ED consumers, AFTER control
discovery so a *derived* sensor never widens control/shed eligibility.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import custom_components.solar_energy_management.ha_energy_reader as her
import custom_components.solar_energy_management.features.load_device_discovery as ldd
from custom_components.solar_energy_management.ha_energy_reader import (
    _find_load_power_sensor,
    _load_object_stem,
)
from custom_components.solar_energy_management.features.load_device_discovery import (
    LoadDeviceDiscovery,
)
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
    UnifiedDevice,
)


# ── a minimal entity registry backing the device-scoped scans ──
class _Entry:
    def __init__(self, entity_id, device_id, domain="sensor", disabled_by=None):
        self.entity_id = entity_id
        self.device_id = device_id
        self.domain = domain
        self.disabled_by = disabled_by


class _Registry:
    def __init__(self, entries):
        self._by_id = {e.entity_id: e for e in entries}
        self._entries = entries

    def async_get(self, entity_id):
        return self._by_id.get(entity_id)


def _st(value, unit=None, device_class=None):
    attrs = {}
    if unit is not None:
        attrs["unit_of_measurement"] = unit
    if device_class is not None:
        attrs["device_class"] = device_class
    return SimpleNamespace(state=str(value), attributes=attrs, last_updated=None)


def _install_registry(monkeypatch, entries, states):
    """Wire a fake entity registry + state machine so the REAL
    ``_find_load_power_sensor`` runs against controlled data."""
    reg = _Registry(entries)
    entries_for = lambda registry, device_id: [
        e for e in registry._entries if e.device_id == device_id
    ]
    monkeypatch.setattr(her.er, "async_get", lambda hass: reg)
    monkeypatch.setattr(her.er, "async_entries_for_device", entries_for)
    hass = MagicMock()
    hass.states.get = lambda eid: states.get(eid)
    return hass, reg, entries_for


# ── the derivation helper itself ──
@pytest.mark.unit
class TestFindLoadPowerSensor:
    def test_derives_companion_power_sensor_for_kwh_only_load(self, monkeypatch):
        # THE BUG: a Shelly PM mini in the ED as its energy counter only. Its
        # power sensor lives on the same HA device. Pre-fix nothing derived it.
        entries = [
            _Entry("sensor.upstairs_fridge_energy", "dev_fridge"),
            _Entry("sensor.upstairs_fridge_power", "dev_fridge"),
        ]
        states = {
            "sensor.upstairs_fridge_energy": _st(12.5, "kWh", "energy"),
            "sensor.upstairs_fridge_power": _st(400, "W", "power"),
        }
        hass, _, _ = _install_registry(monkeypatch, entries, states)
        assert _find_load_power_sensor(hass, "sensor.upstairs_fridge_energy") \
            == "sensor.upstairs_fridge_power"

    def test_stem_affinity_picks_the_right_channel(self, monkeypatch):
        # A Shelly 2PM: channel A's energy sensor must map to channel A's power,
        # never channel B's — even when the registry lists B first and the names
        # are the same length (so the shortest-name tie-break can't decide).
        entries = [
            _Entry("sensor.shelly_2pm_channel_b_power", "dev_2pm"),
            _Entry("sensor.shelly_2pm_channel_a_power", "dev_2pm"),
            _Entry("sensor.shelly_2pm_channel_a_energy", "dev_2pm"),
        ]
        states = {
            "sensor.shelly_2pm_channel_b_power": _st(1500, "W", "power"),
            "sensor.shelly_2pm_channel_a_power": _st(400, "W", "power"),
            "sensor.shelly_2pm_channel_a_energy": _st(3.0, "kWh", "energy"),
        }
        hass, _, _ = _install_registry(monkeypatch, entries, states)
        assert _find_load_power_sensor(
            hass, "sensor.shelly_2pm_channel_a_energy") \
            == "sensor.shelly_2pm_channel_a_power"

    def test_energy_and_reactive_sensors_are_not_mistaken_for_power(self, monkeypatch):
        entries = [
            _Entry("sensor.dryer_energy", "dev_dryer"),
            _Entry("sensor.dryer_reactive_power", "dev_dryer"),
            _Entry("sensor.dryer_power", "dev_dryer"),
        ]
        states = {
            "sensor.dryer_energy": _st(9.9, "kWh", "energy"),
            "sensor.dryer_reactive_power": _st(30, "var", "reactive_power"),
            "sensor.dryer_power": _st(1800, "W", "power"),
        }
        hass, _, _ = _install_registry(monkeypatch, entries, states)
        assert _find_load_power_sensor(hass, "sensor.dryer_energy") \
            == "sensor.dryer_power"

    def test_no_companion_power_sensor_returns_none(self, monkeypatch):
        entries = [_Entry("sensor.solo_energy", "dev_solo")]
        states = {"sensor.solo_energy": _st(3.0, "kWh", "energy")}
        hass, _, _ = _install_registry(monkeypatch, entries, states)
        assert _find_load_power_sensor(hass, "sensor.solo_energy") is None

    def test_no_hass_is_a_no_op(self):
        assert _find_load_power_sensor(None, "sensor.x_energy") is None

    def test_stem_helper_strips_energy_power_suffixes(self):
        assert _load_object_stem("sensor.foo_energy") == "foo"
        assert _load_object_stem("sensor.foo_power") == "foo"
        assert _load_object_stem("sensor.foo_total_energy") == "foo"
        assert _load_object_stem("sensor.channel_a_power") == "channel_a"


# ── end-to-end: derived power sensor flips the reporter's row ON ──
class _SurplusController:
    _devices: dict = {}

    def get_device(self, did):
        return None


@pytest.mark.unit
class TestDerivedPowerFlipsPriorityRowOn:
    """The reporter's exact symptom, end to end: a power-only load (no on/off
    control entity) at 400 W must read ON and show 400 W in the priority
    payload — which only happens once the power sensor is derived."""

    def test_power_only_load_reads_on_after_derivation(self, monkeypatch):
        entries = [
            _Entry("sensor.upstairs_fridge_energy", "dev_fridge"),
            _Entry("sensor.upstairs_fridge_power", "dev_fridge"),
        ]
        states = {
            "sensor.upstairs_fridge_energy": _st(12.5, "kWh", "energy"),
            "sensor.upstairs_fridge_power": _st(400, "W", "power"),
        }
        hass, _, _ = _install_registry(monkeypatch, entries, states)

        # Real derivation → the load's power sensor.
        derived = _find_load_power_sensor(hass, "sensor.upstairs_fridge_energy")
        assert derived == "sensor.upstairs_fridge_power"

        # Feed it into a UnifiedDevice with NO control entity (a PM mini has no
        # relay) and render the priority payload.
        ud = UnifiedDevice(
            energy_sensor="sensor.upstairs_fridge_energy",
            power_sensor=derived,
            name="Upstairs Fridge",
            priority=5,
            control=None,
        )
        reg = UnifiedDeviceRegistry(
            MagicMock(), _SurplusController(), MagicMock(), MagicMock())
        reg._has_battery = False
        reg._devices = [ud]
        reg.hass.states.get = lambda eid: states.get(eid)

        row = reg.get_devices_for_sensor()[ud.device_id]
        # Pre-fix: power_sensor=None → current_power=0 → is_on False → "Off".
        assert row["is_on"] is True
        assert row["current_power"] == 400


# ── the adversarial-review [HIGH]: a DERIVED sensor must not widen control ──
@pytest.mark.unit
class TestDerivedPowerDoesNotWidenControl:
    """A display fix must not turn a load controllable. ``_find_control_by_integration``
    brand-matches on the power sensor name (``power_lower``), so if the derived
    sensor reached control discovery a load whose power sensor merely CONTAINS a
    brand token would get an invented service control → ``is_controllable`` →
    auto-shed-eligible. Deriving AFTER control discovery keeps control keyed off
    the ED-configured link only. Drive the REAL ED discovery to pin it."""

    async def test_brand_named_derived_sensor_stays_uncontrollable(self, monkeypatch):
        # A power-only load: energy sensor has no brand token and no on/off
        # entity on its device, but the device's power sensor is named with a
        # brand token ("easee"). If that derived sensor fed control discovery,
        # the unconditional Easee branch would make it controllable.
        entries = [
            _Entry("sensor.plain_load_energy", "dev_plain"),
            _Entry("sensor.easee_meter_power", "dev_plain"),
        ]
        states = {
            "sensor.plain_load_energy": _st(2.0, "kWh", "energy"),
            "sensor.easee_meter_power": _st(400, "W", "power"),
        }
        hass, reg, entries_for = _install_registry(monkeypatch, entries, states)
        hass.states.async_entity_ids = lambda: [e.entity_id for e in entries]
        # Both the control-side scan (load_device_discovery.entity_registry) and
        # the derive-side scan (ha_energy_reader.er) hit the same fake registry.
        monkeypatch.setattr(ldd.entity_registry, "async_get", lambda hass: reg)
        monkeypatch.setattr(ldd.entity_registry, "async_entries_for_device", entries_for)
        monkeypatch.setattr(
            ldd, "read_energy_dashboard_config", AsyncMock(return_value=MagicMock()))
        monkeypatch.setattr(ldd, "get_all_individual_devices", lambda cfg, hass: [{
            "energy_sensor": "sensor.plain_load_energy",
            "power_sensor": None,        # ED carries no stat_rate — the real case
            "name": "Plain Load",
            "is_ev": False,
        }])

        disc = LoadDeviceDiscovery(hass)
        result = await disc.discover_from_energy_dashboard()

        assert len(result) == 1
        info = next(iter(result.values()))
        # Display: the derived power sensor IS surfaced (so watts/on-off work)…
        assert info["power_entity"] == "sensor.easee_meter_power"
        # …but control was NOT invented from that brand-named derived sensor.
        assert info["is_controllable"] is False
        assert info["control"] is None
