"""Regression tests for the phase-guard topology wizard."""
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
    for phase in range(1, 4):
        key = f"phase_guard_grid_l{phase}_current_entity"
        assert key in markers
        assert markers[key].description["suggested_value"] == (
            f"sensor.smart_meter_grid_l{phase}_current"
        )
