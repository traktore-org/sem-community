"""#709 — Deye config/options flow + diagnostics for a real SEM install.

This slice ships the options-flow surface that lets an operator wire a
Deye hybrid inverter (forced grid charging) in a real Home Assistant
install WITHOUT hand-editing YAML. It also exposes read-only Deye
diagnostics.

Config shape produced by the flow (matches the DeyeBatteryAdapter
contract in ``battery_adapters/deye.py``):

    battery_charge_platform: deye
    deye_grid_charge_switch: switch.*
    deye_charge_current_entity: number.*            # unit A
    deye_battery_voltage_entity: sensor.*
    deye_max_charge_current_a: float                # safe ceiling
    deye_bms_max_charge_current_a: float|None       # optional BMS max
    deye_program_control: true
    deye_program_groups: [ {time, soc, charge} x6 ]
    deye_work_mode_control: bool
    deye_work_mode_entity: select.*
    deye_work_mode_load_first_option: str
    deye_work_mode_battery_first_option: str        # distinct from load_first
    deye_force_charge_work_mode: load_first|battery_first
    deye_observer_mode: true   # DEFAULT true — no writes until operator opts out
    deye_actuation_enabled: false  # DEFAULT false — exact bool required to write
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.config_flow import (
    OptionsFlowHandler,
)


def _flow(mock_hass, config_entry):
    flow = OptionsFlowHandler(config_entry)
    flow.hass = mock_hass
    flow.hass.data = {"_entry": config_entry}  # used by _run_step patch
    return flow


async def _run_step(flow, step_name, *args):
    """Invoke an options-flow step with the ``config_entry`` property patched
    to return the mock (newer HA resolves ``self.config_entry`` through the
    configured-entry registry; tests supply a plain MagicMock)."""
    from unittest.mock import patch

    entry = flow.hass.data.get("_entry")
    step = getattr(flow, step_name)
    with patch.object(
        type(flow),
        "config_entry",
        new_callable=lambda: property(lambda self: entry if entry is not None else MagicMock()),
    ):
        return await step(*args)


def _deye_platform_input():
    """A complete, valid Deye options submission (the happy path)."""
    data = {
        "battery_charge_platform": "deye",
        "deye_grid_charge_switch": "switch.deye_grid_charge",
        "deye_charge_current_entity": "number.deye_charge_current",
        "deye_battery_voltage_entity": "sensor.deye_battery_voltage",
        "deye_max_charge_current_a": 25,
        "deye_bms_max_charge_current_a": 30,
        "deye_program_control": True,
        "deye_work_mode_control": True,
        "deye_work_mode_entity": "select.deye_energy_pattern",
        "deye_work_mode_load_first_option": "Load First",
        "deye_work_mode_battery_first_option": "Battery First",
        "deye_force_charge_work_mode": "battery_first",
        "deye_observer_mode": False,
        "deye_actuation_enabled": True,
    }
    for n in range(1, 7):
        data[f"deye_program_{n}_time"] = f"select.deye_slice_{n}_time"
        data[f"deye_program_{n}_soc"] = f"number.deye_slice_{n}_soc"
        data[f"deye_program_{n}_charge"] = f"select.deye_slice_{n}_charge"
    return data


def _assert_deye_keys(payload: dict):
    """Assert the saved payload matches the documented Deye contract."""
    assert payload.get("battery_charge_platform") == "deye"
    assert payload["deye_grid_charge_switch"] == "switch.deye_grid_charge"
    assert payload["deye_charge_current_entity"] == "number.deye_charge_current"
    assert payload["deye_battery_voltage_entity"] == "sensor.deye_battery_voltage"
    assert payload["deye_max_charge_current_a"] == 25
    assert payload["deye_bms_max_charge_current_a"] == 30
    # Booleans must remain REAL bools — never strings.
    assert payload["deye_program_control"] is True
    assert payload["deye_work_mode_control"] is True
    assert payload["deye_work_mode_load_first_option"] == "Load First"
    assert payload["deye_work_mode_battery_first_option"] == "Battery First"
    assert payload["deye_force_charge_work_mode"] == "battery_first"
    assert payload["deye_observer_mode"] is False
    assert payload["deye_actuation_enabled"] is True
    # Exactly six complete program groups, each {time, soc, charge}.
    groups = payload["deye_program_groups"]
    assert isinstance(groups, list)
    assert len(groups) == 6
    for idx, group in enumerate(groups, start=1):
        assert group["time"] == f"select.deye_slice_{idx}_time"
        assert group["soc"] == f"number.deye_slice_{idx}_soc"
        assert group["charge"] == f"select.deye_slice_{idx}_charge"


class TestDeyeOptionsFlow:
    @pytest.mark.asyncio
    async def test_scheduler_only_opens_deye_step_when_selected(
        self, mock_hass, config_entry
    ):
        generic = _flow(mock_hass, config_entry)
        generic_result = await _run_step(
            generic, "async_step_battery_scheduler",
            {"battery_charge_platform": "generic"},
        )
        assert generic_result["step_id"] != "deye"

        deye = _flow(mock_hass, config_entry)
        deye_result = await _run_step(
            deye, "async_step_battery_scheduler",
            {"battery_charge_platform": "deye"},
        )
        assert deye_result["step_id"] == "deye"

    @pytest.mark.asyncio
    async def test_submit_complete_form_stores_full_contract(self, mock_hass, config_entry):
        flow = _flow(mock_hass, config_entry)
        result = await _run_step(flow, "async_step_deye", _deye_platform_input())
        # Proceeds past Deye after a valid submission. With no configured PV
        # strings the existing flow may immediately skip pv_naming.
        assert result["type"] == "form"
        assert result["step_id"] != "deye"
        _assert_deye_keys(flow._data)

    @pytest.mark.asyncio
    async def test_defaults_observer_on_actuation_off(self, mock_hass, config_entry):
        """Fresh form defaults: observer_mode True, actuation_enabled False —
        so a bare Deye config never actuates until the operator opts in."""
        flow = _flow(mock_hass, config_entry)
        result = await _run_step(flow, "async_step_deye")
        assert result["type"] == "form"
        schema = result["data_schema"]
        def _default(name: str):
            marker = next(k for k in schema.schema if str(k) == name)
            return marker.default() if callable(marker.default) else marker.default

        assert _default("deye_observer_mode") is True
        assert _default("deye_actuation_enabled") is False
        assert _default("deye_program_control") is True
        assert _default("deye_work_mode_control") is False

    @pytest.mark.asyncio
    async def test_platform_not_deye_skips_work_mode_requirement(self, mock_hass, config_entry):
        """Choosing a non-Deye platform doesn't demand Deye work-mode options."""
        data = _deye_platform_input()
        data["battery_charge_platform"] = "generic"
        data.pop("deye_work_mode_entity", None)
        data["deye_work_mode_control"] = False
        flow = _flow(mock_hass, config_entry)
        result = await _run_step(flow, "async_step_deye", data)
        assert result["step_id"] != "deye"

    @pytest.mark.asyncio
    async def test_missing_sixth_program_group_is_validation_error(self, mock_hass, config_entry):
        """Deye requires exactly six complete program groups — five is invalid."""
        data = _deye_platform_input()
        # Drop group 6 entirely.
        for key in ("deye_program_6_time", "deye_program_6_soc", "deye_program_6_charge"):
            data.pop(key, None)
        flow = _flow(mock_hass, config_entry)
        result = await _run_step(flow, "async_step_deye", data)
        assert result["type"] == "form"
        assert result["step_id"] == "deye"
        assert result["errors"]

    @pytest.mark.asyncio
    async def test_incomplete_program_group_invalid(self, mock_hass, config_entry):
        """A group missing one of time/soc/charge is incomplete → invalid."""
        data = _deye_platform_input()
        data.pop("deye_program_3_soc", None)
        flow = _flow(mock_hass, config_entry)
        result = await _run_step(flow, "async_step_deye", data)
        assert result["step_id"] == "deye"
        assert result["errors"]

    @pytest.mark.asyncio
    async def test_work_mode_mappings_must_be_distinct(self, mock_hass, config_entry):
        data = _deye_platform_input()
        data["deye_work_mode_load_first_option"] = "Same"
        data["deye_work_mode_battery_first_option"] = "Same"
        flow = _flow(mock_hass, config_entry)
        result = await _run_step(flow, "async_step_deye", data)
        assert result["step_id"] == "deye"
        assert result["errors"]

    @pytest.mark.asyncio
    async def test_force_charge_mode_must_be_valid(self, mock_hass, config_entry):
        data = _deye_platform_input()
        data["deye_force_charge_work_mode"] = "bogus"
        flow = _flow(mock_hass, config_entry)
        result = await _run_step(flow, "async_step_deye", data)
        assert result["step_id"] == "deye"
        assert result["errors"]

    @pytest.mark.asyncio
    async def test_round_trip_payload_feeds_capability(self, mock_hass, config_entry):
        """The saved options must be directly consumable by the real
        DeyeBatteryAdapter config contract (list-of-6 groups resolve)."""
        from custom_components.solar_energy_management.coordinator.battery_adapters.deye import (
            DeyeBatteryAdapter,
        )

        flow = _flow(mock_hass, config_entry)
        await _run_step(flow, "async_step_deye", _deye_platform_input())
        payload = dict(flow._data)

        class _States:
            def __init__(self, mapping):
                self._mapping = mapping
            def get(self, eid):
                return self._mapping.get(eid)

        from datetime import datetime, timedelta, timezone
        from types import SimpleNamespace

        now = datetime.now(timezone.utc)

        def st(value, **attrs):
            return SimpleNamespace(
                state=str(value), attributes=attrs,
                last_updated=now - timedelta(seconds=1),
                last_changed=now - timedelta(seconds=1),
            )

        states = {
            "switch.deye_grid_charge": st("off"),
            "number.deye_charge_current": st(0, unit_of_measurement="A", min=0, max=32),
            "sensor.deye_battery_voltage": st(53.35),
        }
        groups = payload["deye_program_groups"]
        for g in groups:
            states[g["time"]] = st("01:00:00")
            states[g["soc"]] = st(21, unit_of_measurement="%", min=0, max=100)
            states[g["charge"]] = st("Disabled", options=["Disabled", "Grid"])

        _hass = MagicMock()
        _hass.states = _States(states)

        adapter_config = {
            **payload,
            "deye_snapshot_store": MagicMock(),
            "deye_max_charge_current_a": 25,
            "deye_bms_max_charge_current_a": 30,
        }
        adapter = DeyeBatteryAdapter(_hass, adapter_config)
        # The saved six groups must resolve to six complete slots.
        slots = adapter._program_slots()
        assert len(slots) == 6
        assert all(slot is not None for slot in slots)

    @pytest.mark.asyncio
    async def test_no_store_in_options(self, mock_hass, config_entry):
        """The runtime snapshot store must never be serialised into the
        saved entry options (it is attached to the adapter, not the entry)."""
        flow = _flow(mock_hass, config_entry)
        await _run_step(flow, "async_step_deye", _deye_platform_input())
        payload = dict(flow._data)
        assert "deye_snapshot_store" not in payload
        assert all(
            not isinstance(v, type) for v in payload.values()
        )  # nothing but plain data
