"""Fail-closed contract tests for the explicit Deye battery adapter."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.solar_energy_management.coordinator.battery_adapters import (
    DeyeBatteryAdapter,
    GenericBatteryAdapter,
    adapter_for,
)


class _States:
    def __init__(self, values):
        self._values = values

    def get(self, entity_id):
        return self._values.get(entity_id)


class _Store:
    def __init__(self, events=None):
        self.data = None
        self.unsafe = False
        self.events = events if events is not None else []

    async def async_save(self, data):
        self.events.append("snapshot_saved")
        self.data = data

    async def async_load(self):
        return self.data

    async def async_clear(self):
        self.events.append("snapshot_cleared")
        self.data = None

    async def async_set_unsafe(self, value):
        self.unsafe = bool(value)


class _Hass:
    def __init__(self, values, *, events=None, mismatch_pairs=None, fail_pairs=None):
        self.states = _States(values)
        self.data = {}
        self.config_entries = SimpleNamespace(async_entries=lambda _domain: [])
        self.events = events if events is not None else []
        self.mismatch_pairs = set(mismatch_pairs or ())
        self.fail_pairs = set(fail_pairs or ())

        async def _call(domain, service, data, blocking=True):
            entity_id = data["entity_id"]
            if "value" in data:
                value = data["value"]
            elif "option" in data:
                value = data["option"]
            elif "time" in data:
                value = data["time"]
            else:
                value = service == "turn_on"
            self.events.append((entity_id, value))
            if (entity_id, value) in self.fail_pairs:
                raise RuntimeError("simulated service failure")
            if (entity_id, value) in self.mismatch_pairs:
                return
            state = values[entity_id]
            if domain == "switch":
                state.state = "on" if value else "off"
            else:
                state.state = str(value)

        self.services = SimpleNamespace(async_call=AsyncMock(side_effect=_call))


def _state(value, *, age_s=1, **attributes):
    return SimpleNamespace(
        state=str(value),
        attributes=attributes,
        last_updated=datetime.now(timezone.utc) - timedelta(seconds=age_s),
        last_changed=datetime.now(timezone.utc) - timedelta(seconds=age_s),
    )


def _valid_setup(*, program_control=True):
    config = {
        "battery_charge_platform": "deye",
        "deye_grid_charge_switch": "switch.grid_charge",
        "deye_charge_current_entity": "number.grid_charge_current",
        "deye_battery_voltage_entity": "sensor.battery_voltage",
        "deye_battery_voltage_max_age_s": 60,
        "deye_max_charge_current_a": 25,
        "deye_bms_max_charge_current_a": 20,
        "deye_max_discharge_power": 5000,
        "deye_program_control": program_control,
        "deye_program_groups": [],
    }
    states = {
        "switch.grid_charge": _state("off"),
        "number.grid_charge_current": _state(
            0, unit_of_measurement="A", min=0, max=32,
        ),
        "sensor.battery_voltage": _state(53.35),
    }
    for index in range(1, 7):
        time_entity = f"time.program_{index}"
        soc_entity = f"number.program_{index}_soc"
        charge_entity = f"select.program_{index}_charging"
        config["deye_program_groups"].append(
            {"time": time_entity, "soc": soc_entity, "charge": charge_entity}
        )
        states[time_entity] = _state("00:00:00")
        states[soc_entity] = _state(
            21, unit_of_measurement="%", min=0, max=100,
        )
        states[charge_entity] = _state(
            "Disabled", options=["Disabled", "Grid", "Generator", "Both"],
        )
    return config, states


def _adapter(config=None, states=None, *, hass=None):
    if config is None or states is None:
        config, states = _valid_setup()
    return DeyeBatteryAdapter(hass or _Hass(states), config)


def _active_adapter(*, mismatch_pairs=None, fail_pairs=None, store=None, events=None):
    config, states = _valid_setup()
    shared_events = events if events is not None else []
    snapshot_store = store or _Store(shared_events)
    config.update(
        config_entry_id="entry-1",
        battery_id="battery-1",
        deye_snapshot_store=snapshot_store,
        deye_observer_mode=False,
        deye_actuation_enabled=True,
        deye_readback_attempts=1,
    )
    hass = _Hass(
        states,
        events=shared_events,
        mismatch_pairs=mismatch_pairs,
        fail_pairs=fail_pairs,
    )
    return DeyeBatteryAdapter(hass, config), config, states, snapshot_store, shared_events


def test_complete_capability_is_available_and_serialisable():
    adapter = _adapter()

    capability = adapter.capability()

    assert capability.available is True
    assert capability.reason == "ok"
    assert capability.max_charge_current_a == 20
    assert 0 <= capability.battery_voltage_age_s < 10
    assert capability.snapshot_supported is False
    assert capability.readback_supported is False
    assert capability.restore_supported is False
    assert adapter.supports_forced_charge is False
    assert adapter.max_charge_power_w == pytest.approx(20 * 53.35)
    assert asdict(capability)["available"] is True


def test_explicit_factory_selects_deye_but_auto_never_does():
    config, states = _valid_setup()
    hass = _Hass(states)

    assert isinstance(adapter_for(hass, config), DeyeBatteryAdapter)
    auto_config = dict(config)
    auto_config["battery_charge_platform"] = "auto"
    assert isinstance(adapter_for(hass, auto_config), GenericBatteryAdapter)


@pytest.mark.parametrize(
    ("mutate", "reason_fragment"),
    [
        (lambda c, s: c.update(deye_grid_charge_switch="number.grid_charge_current"), "switch.*"),
        (lambda c, s: setattr(s["switch.grid_charge"], "state", "unavailable"), "switch state"),
        (lambda c, s: s["number.grid_charge_current"].attributes.update(unit_of_measurement="W"), "unit A"),
        (lambda c, s: s["number.grid_charge_current"].attributes.update(min=-1), "0 <= min"),
        (lambda c, s: setattr(s["number.grid_charge_current"], "state", "unknown"), "current state"),
        (lambda c, s: setattr(s["sensor.battery_voltage"], "state", "nan"), "voltage state"),
        (lambda c, s: setattr(s["sensor.battery_voltage"], "state", "0"), "at least 40"),
        (lambda c, s: setattr(s["sensor.battery_voltage"], "state", "39.9"), "at least 40"),
        (lambda c, s: setattr(s["sensor.battery_voltage"], "last_updated", datetime.now(timezone.utc) - timedelta(seconds=120)), "stale"),
        (lambda c, s: c.pop("deye_max_charge_current_a"), "safe max"),
        (lambda c, s: c.update(deye_max_charge_current_a=float("inf")), "safe max"),
        (lambda c, s: c.update(deye_bms_max_charge_current_a=-1), "BMS max"),
        (lambda c, s: c.update(deye_battery_voltage_max_age_s="bad"), "max age"),
        (lambda c, s: c["deye_program_groups"].pop(), "requires 6"),
        (lambda c, s: s["number.program_1_soc"].attributes.update(max=99), "SOC range"),
        (lambda c, s: s["number.program_1_soc"].attributes.update(max=float("inf")), "finite"),
        (lambda c, s: s["select.program_1_charging"].attributes.update(options=["Disabled"]), "Disabled and Grid"),
        (lambda c, s: setattr(s["select.program_1_charging"], "state", "unavailable"), "select state"),
        (lambda c, s: c["deye_program_groups"][0].update(time="select.wrong_time_domain"), "time entity"),
    ],
)
def test_capability_fail_closed(mutate, reason_fragment):
    config, states = _valid_setup()
    mutate(config, states)

    capability = _adapter(config, states).capability()

    assert capability.available is False
    assert capability.max_charge_current_a == 0
    assert reason_fragment.lower() in capability.reason.lower()


def test_program_entities_are_optional_only_when_program_control_is_disabled():
    config, states = _valid_setup(program_control=False)
    config["deye_program_groups"] = []

    capability = _adapter(config, states).capability()

    assert capability.available is True


def test_default_voltage_freshness_is_30_seconds():
    config, states = _valid_setup()
    config.pop("deye_battery_voltage_max_age_s")
    states["sensor.battery_voltage"].last_updated = (
        datetime.now(timezone.utc) - timedelta(seconds=31)
    )

    capability = _adapter(config, states).capability()

    assert capability.available is False
    assert "stale" in capability.reason


@pytest.mark.asyncio
async def test_observer_mode_is_no_write_and_never_records_force_charge():
    adapter = _adapter()

    await adapter.command_force_charge(80, 3000, 60)

    adapter._hass.services.async_call.assert_not_awaited()
    assert adapter.last_intent is None
    assert "observer mode" in adapter.last_error


def test_invalid_discharge_config_falls_back_to_zero():
    config, states = _valid_setup()
    config["deye_max_discharge_power"] = float("nan")

    assert _adapter(config, states).max_discharge_power_w == 0


def test_active_writes_require_store_scope_and_explicit_operator_gates():
    adapter, _, _, _, _ = _active_adapter()
    assert adapter.capability().snapshot_supported is True
    assert adapter.supports_forced_charge is True


@pytest.mark.asyncio
async def test_string_false_never_opens_actuation_gate():
    _, config, states, _, _ = _active_adapter()
    config = dict(config)
    config["deye_actuation_enabled"] = "false"
    hass = _Hass(states)
    adapter = DeyeBatteryAdapter(hass, config)

    await adapter.command_force_charge(80, 1067, 60)

    assert adapter.supports_forced_charge is False
    hass.services.async_call.assert_not_awaited()
    assert adapter.last_intent is None
    assert "explicitly enabled" in adapter.last_error


def test_non_string_scope_ids_never_enable_writes():
    _, config, states, _, _ = _active_adapter()
    config = dict(config)
    config["config_entry_id"] = None
    config["battery_id"] = 123

    adapter = DeyeBatteryAdapter(_Hass(states), config)

    assert adapter.supports_forced_charge is False


def test_store_without_unsafe_persistence_never_enables_writes():
    _, config, states, _, _ = _active_adapter()
    config = dict(config)
    config["deye_snapshot_store"] = SimpleNamespace(
        async_save=AsyncMock(),
        async_load=AsyncMock(return_value=None),
        async_clear=AsyncMock(),
    )

    adapter = DeyeBatteryAdapter(_Hass(states), config)

    assert adapter.supports_forced_charge is False


@pytest.mark.asyncio
async def test_snapshot_must_read_back_from_store_before_first_write():
    class _NonPersistingStore(_Store):
        async def async_save(self, data):
            self.events.append("snapshot_save_attempted")

    config, states = _valid_setup()
    events = []
    store = _NonPersistingStore(events)
    config.update(
        config_entry_id="entry-1",
        battery_id="battery-1",
        deye_snapshot_store=store,
        deye_observer_mode=False,
        deye_actuation_enabled=True,
        deye_readback_attempts=1,
    )
    hass = _Hass(states, events=events)
    adapter = DeyeBatteryAdapter(hass, config)

    await adapter.command_force_charge(80, 1067, 60)

    hass.services.async_call.assert_not_awaited()
    assert adapter.last_intent is None
    assert "persistence failed" in adapter.last_error


@pytest.mark.asyncio
async def test_snapshot_is_persisted_before_first_write_and_stop_restores_in_safe_order():
    adapter, _, states, store, events = _active_adapter()

    await adapter.command_force_charge(80, 1067, 60)

    assert events[0] == "snapshot_saved"
    assert store.data is not None
    assert store.data["config_entry_id"] == "entry-1"
    assert store.data["battery_id"] == "battery-1"
    assert len(store.data["program_times"]) == 6
    assert store.data["created_at"] <= adapter._session_first_write_at
    assert adapter.last_intent.name == "FORCE_CHARGE"
    assert states["number.grid_charge_current"].state == "20.0"
    assert states["number.program_1_soc"].state == "80.0"
    assert states["select.program_1_charging"].state == "Grid"
    assert states["switch.grid_charge"].state == "on"

    stop_start = len(events)
    await adapter.command_stop_force_charge()
    stop_events = events[stop_start:]

    assert stop_events[0] == ("number.grid_charge_current", 0.0)
    assert stop_events[1] == ("switch.grid_charge", False)
    assert stop_events[-2] == ("switch.grid_charge", False)
    assert stop_events[-1] == "snapshot_cleared"
    assert store.data is None
    assert adapter.last_intent.name == "STOP_FORCE_CHARGE"
    assert states["number.grid_charge_current"].state == "0.0"
    assert states["number.program_1_soc"].state == "21.0"
    assert states["select.program_1_charging"].state == "Disabled"
    assert states["switch.grid_charge"].state == "off"


@pytest.mark.asyncio
async def test_readback_mismatch_rolls_back_and_does_not_record_success():
    adapter, _, states, store, _ = _active_adapter(
        mismatch_pairs={("select.program_1_charging", "Grid")},
    )

    await adapter.command_force_charge(80, 1067, 60)

    assert adapter.last_intent is None
    assert "rollback verified" in adapter.last_error
    assert adapter.unsafe_latched is False
    assert store.data is None
    assert states["number.grid_charge_current"].state == "0.0"
    assert states["number.program_1_soc"].state == "21.0"
    assert states["switch.grid_charge"].state == "off"


@pytest.mark.asyncio
async def test_rollback_readback_failure_persists_unsafe_latch():
    adapter, _, states, store, events = _active_adapter(
        mismatch_pairs={
            ("select.program_1_charging", "Grid"),
            ("number.grid_charge_current", 0.0),
        },
    )
    # Pre-existing external charging: failed safe-zero must still switch off
    # and must never restore 5 A / re-enable the switch.
    states["switch.grid_charge"].state = "on"
    states["number.grid_charge_current"].state = "5"

    await adapter.command_force_charge(80, 1067, 60)

    assert adapter.last_intent is None
    assert adapter.unsafe_latched is True
    assert store.unsafe is True
    assert store.data is not None
    assert "rollback FAILED" in adapter.last_error
    assert adapter.supports_forced_charge is False
    rollback_start = events.index(("number.grid_charge_current", 0.0))
    rollback_events = events[rollback_start:]
    assert len(rollback_events) == 2
    assert rollback_events[1] == ("switch.grid_charge", False)
    assert ("number.grid_charge_current", 5.0) not in rollback_events
    assert ("switch.grid_charge", True) not in rollback_events
    assert states["switch.grid_charge"].state == "off"
    assert adapter.unsafe_latched is True
    assert store.unsafe is True


@pytest.mark.asyncio
async def test_unsafe_latch_without_snapshot_never_reports_normal_success():
    adapter, _, _, store, _ = _active_adapter()
    adapter._unsafe_latched = True
    store.unsafe = True

    await adapter.command_normal()

    assert adapter.last_intent is None
    assert "unsafe latch" in adapter.last_error


@pytest.mark.asyncio
async def test_persisted_snapshot_can_be_restored_after_adapter_restart():
    adapter, config, states, store, events = _active_adapter()
    await adapter.command_force_charge(80, 1067, 60)
    assert store.data is not None

    restarted_hass = _Hass(states, events=events)
    restarted = DeyeBatteryAdapter(restarted_hass, config)
    await restarted.command_normal()

    assert restarted.last_intent.name == "NORMAL"
    assert restarted.unsafe_latched is False
    assert store.data is None
    assert states["switch.grid_charge"].state == "off"


@pytest.mark.asyncio
async def test_snapshot_scope_or_entity_mapping_mismatch_blocks_restore_and_latches():
    adapter, config, states, store, events = _active_adapter()
    await adapter.command_force_charge(80, 1067, 60)
    config = dict(config)
    config["battery_id"] = "different-battery"
    mismatched = DeyeBatteryAdapter(_Hass(states, events=events), config)

    await mismatched.command_stop_force_charge()

    assert mismatched.last_intent is None
    assert mismatched.unsafe_latched is True
    assert store.unsafe is True
    assert "scope mismatch" in mismatched.last_error


@pytest.mark.asyncio
async def test_stale_persisted_snapshot_is_never_overwritten_by_new_session():
    adapter, config, states, store, events = _active_adapter()
    await adapter.command_force_charge(80, 1067, 60)
    saved_session = store.data["session_id"]
    store.data["created_at"] -= 3600
    restarted = DeyeBatteryAdapter(_Hass(states, events=events), config)

    await restarted.command_force_charge(90, 1500, 60)

    assert restarted.last_intent is None
    assert "pending Deye snapshot" in restarted.last_error
    assert store.data["session_id"] == saved_session


@pytest.mark.asyncio
async def test_corrupt_snapshot_never_reports_successful_stop_or_writes():
    _, config, states, store, events = _active_adapter()
    store.data = {"grid_charge_enabled": "false"}
    restarted_hass = _Hass(states, events=events)
    restarted = DeyeBatteryAdapter(restarted_hass, config)

    await restarted.command_stop_force_charge()

    restarted_hass.services.async_call.assert_not_awaited()
    assert restarted.last_intent is None
    assert restarted.unsafe_latched is True
    assert store.unsafe is True
    assert store.data == {"grid_charge_enabled": "false"}
    assert "snapshot load failed" in restarted.last_error
