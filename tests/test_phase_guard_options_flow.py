"""Regression tests for the phase-guard topology wizard."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.solar_energy_management.config_flow import OptionsFlowHandler


def test_options_flow_exposes_dedicated_phase_guard_wizard_steps():
    assert callable(getattr(OptionsFlowHandler, "async_step_settings_phase_guard_topology"))
    assert callable(getattr(OptionsFlowHandler, "async_step_settings_phase_guard"))


@pytest.mark.asyncio
async def test_disabled_topology_skips_sensor_mapping_and_disables_guard():
    flow = SimpleNamespace(
        _data={},
        async_step_settings_tariff=AsyncMock(
            return_value={"step_id": "settings_tariff"}
        ),
    )

    result = await OptionsFlowHandler.async_step_settings_phase_guard_topology(
        flow, {"phase_guard_topology": "disabled"}
    )

    assert result == {"step_id": "settings_tariff"}
    assert flow._data["phase_guard_enabled"] is False


@pytest.mark.asyncio
async def test_hybrid_topology_routes_to_separate_sensor_mapping_step():
    flow = SimpleNamespace(
        _data={},
        async_step_settings_phase_guard=AsyncMock(
            return_value={"step_id": "settings_phase_guard"}
        ),
    )

    result = await OptionsFlowHandler.async_step_settings_phase_guard_topology(
        flow, {"phase_guard_topology": "hybrid_load_port"}
    )

    assert result == {"step_id": "settings_phase_guard"}
    assert flow._data["phase_guard_enabled"] is True
    assert flow._data["phase_guard_phase_count"] == 3


@pytest.mark.asyncio
async def test_topology_step_preserves_selected_single_phase_count():
    flow = SimpleNamespace(
        _data={},
        async_step_settings_phase_guard=AsyncMock(
            return_value={"step_id": "settings_phase_guard"}
        ),
    )

    result = await OptionsFlowHandler.async_step_settings_phase_guard_topology(
        flow,
        {
            "phase_guard_topology": "hybrid_load_port",
            "phase_guard_phase_count": "1",
        },
    )

    assert result == {"step_id": "settings_phase_guard"}
    assert flow._data["phase_guard_phase_count"] == 1


@pytest.mark.asyncio
async def test_mapping_step_exposes_and_suggests_direct_grid_current_triplet():
    states = [
        SimpleNamespace(
            entity_id=f"sensor.smart_meter_grid_l{phase}_current",
            state="8",
            attributes={"unit_of_measurement": "A"},
        )
        for phase in range(1, 4)
    ]
    shown = {}

    def _show_form(**kwargs):
        shown.update(kwargs)
        return kwargs

    flow = SimpleNamespace(
        config_entry=SimpleNamespace(data={}, options={}),
        _data={"phase_guard_topology": "grid_only"},
        hass=SimpleNamespace(states=SimpleNamespace(async_all=Mock(return_value=states))),
        _cfg=OptionsFlowHandler._cfg,
        async_show_form=_show_form,
    )

    await OptionsFlowHandler.async_step_settings_phase_guard(flow)

    markers = {marker.schema: marker for marker in shown["data_schema"].schema}
    assert markers["phase_guard_enforcement_enabled"].default() is False
    assert markers["phase_guard_notifications_enabled"].default() is True
    assert markers["phase_guard_recovery_margin_a"].default() == 2.0
    assert markers["phase_guard_recovery_cycles"].default() == 3
    for phase in range(1, 4):
        key = f"phase_guard_grid_l{phase}_current_entity"
        assert key in markers
        assert markers[key].description["suggested_value"] == (
            f"sensor.smart_meter_grid_l{phase}_current"
        )


@pytest.mark.asyncio
async def test_single_phase_mapping_step_only_exposes_l1_sensor_fields():
    shown = {}

    def _show_form(**kwargs):
        shown.update(kwargs)
        return kwargs

    flow = SimpleNamespace(
        config_entry=SimpleNamespace(data={}, options={}),
        _data={
            "phase_guard_topology": "hybrid_load_port",
            "phase_guard_phase_count": 1,
        },
        hass=SimpleNamespace(
            states=SimpleNamespace(
                async_all=Mock(
                    return_value=[
                        SimpleNamespace(
                            entity_id="sensor.smart_meter_grid_l1_current",
                            state="8",
                            attributes={"unit_of_measurement": "A"},
                        )
                    ]
                )
            )
        ),
        _cfg=OptionsFlowHandler._cfg,
        async_show_form=_show_form,
    )

    await OptionsFlowHandler.async_step_settings_phase_guard(flow)

    keys = {marker.schema for marker in shown["data_schema"].schema}
    markers = {marker.schema: marker for marker in shown["data_schema"].schema}
    assert "phase_guard_grid_l1_current_entity" in keys
    assert markers["phase_guard_grid_l1_current_entity"].description[
        "suggested_value"
    ] == "sensor.smart_meter_grid_l1_current"
    assert "phase_guard_inverter_l1_current_entity" in keys
    assert "phase_guard_grid_l2_current_entity" not in keys
    assert "phase_guard_grid_l3_current_entity" not in keys
    assert "phase_guard_inverter_l2_current_entity" not in keys
    assert "phase_guard_inverter_l3_current_entity" not in keys


def test_phase_guard_safety_controls_are_localized_in_every_language():
    root = Path(__file__).resolve().parents[1]
    keys = {
        "phase_guard_enforcement_enabled",
        "phase_guard_recovery_margin_a",
        "phase_guard_recovery_cycles",
    }
    english = json.loads(
        (root / "translations" / "en.json").read_text(encoding="utf-8")
    )["options"]["step"]["settings_phase_guard"]

    for path in sorted((root / "translations").glob("*.json")):
        block = json.loads(path.read_text(encoding="utf-8"))["options"]["step"][
            "settings_phase_guard"
        ]
        assert keys <= block["data"].keys()
        assert keys <= block["data_description"].keys()
        if path.name != "en.json":
            for key in keys:
                assert block["data"][key] != english["data"][key], (path.name, key)
                assert block["data_description"][key] != english["data_description"][key], (
                    path.name,
                    key,
                )


def test_phase_guard_topology_copy_is_localized_in_every_language():
    root = Path(__file__).resolve().parents[1]
    english = json.loads(
        (root / "translations" / "en.json").read_text(encoding="utf-8")
    )
    english_step = english["options"]["step"]["settings_phase_guard_topology"]
    english_options = english["selector"]["phase_guard_topology"]["options"]

    for path in sorted((root / "translations").glob("*.json")):
        if path.name == "en.json":
            continue
        translation = json.loads(path.read_text(encoding="utf-8"))
        step = translation["options"]["step"]["settings_phase_guard_topology"]
        options = translation["selector"]["phase_guard_topology"]["options"]

        assert step["title"] != english_step["title"], (path.name, "title")
        assert step["description"] != english_step["description"], (
            path.name,
            "description",
        )
        for key in ("phase_guard_topology", "phase_guard_phase_count"):
            assert step["data"][key] != english_step["data"][key], (
                path.name,
                key,
            )
            assert step["data_description"][key] != english_step["data_description"][
                key
            ], (path.name, key)
        for key in ("disabled", "grid_only", "hybrid_load_port"):
            assert options[key] != english_options[key], (path.name, key)


def test_english_phase_guard_labels_explain_effect_without_internal_jargon():
    root = Path(__file__).resolve().parents[1]
    block = json.loads(
        (root / "translations" / "en.json").read_text(encoding="utf-8")
    )["options"]["step"]["settings_phase_guard"]

    assert "stop" in block["data"]["phase_guard_enforcement_enabled"].lower()
    recovery_label = block["data"]["phase_guard_recovery_cycles"].lower()
    assert "cycle" not in recovery_label
    assert "restart" not in recovery_label
