"""#1032 review — what the setup WIZARD prefills, end to end through
config_flow's own EV step, for every rig integration. One reader: a field
the crawler cannot fill stays empty for the user; nothing is filled from a
second, pattern-based reader."""
from __future__ import annotations

import pytest

from .integrations_rig.rig import load_capture, replay

FIELDS = ("ev_connected_sensor", "ev_charging_sensor",
          "ev_charging_power_sensor", "ev_current_control_entity",
          "ev_start_stop_entity", "ev_charge_mode_entity",
          "ev_session_energy_sensor", "ev_total_energy_sensor")


async def _prefill(hass, *names):
    from custom_components.solar_energy_management.config_flow import (
        SolarEnergyManagementConfigFlow,
    )
    for n in names:
        await replay(hass, load_capture(n))
    flow = SolarEnergyManagementConfigFlow()
    flow.hass = hass
    flow.context = {"source": "user"}
    result = await flow.async_step_ev_charger()
    out = {}
    in_form = set()
    for key in result["data_schema"].schema:
        name = str(key)
        if name not in FIELDS:
            continue
        in_form.add(name)
        default = key.default() if callable(getattr(key, "default", None)) else None
        suggested = (getattr(key, "description", None) or {}).get("suggested_value")
        val = suggested or default
        if val:
            out[name] = val
    return out, in_form


#: What the wizard should prefill. Fields absent here must stay EMPTY.
EXPECTED = {
    "openevse": {
        "ev_connected_sensor": "binary_sensor.openevse_mock_config_vehicle_connected",
        "ev_charging_power_sensor": "sensor.openevse_mock_config_charging_power",
        "ev_current_control_entity": "number.openevse_mock_config_charge_rate",
        "ev_session_energy_sensor": "sensor.openevse_mock_config_usage_this_session",
        "ev_total_energy_sensor": "sensor.openevse_mock_config_total_energy_usage",
    },
    "nrgkick": {
        "ev_charging_sensor": "sensor.nrgkick_test_status",
        "ev_charging_power_sensor": "sensor.nrgkick_test_total_active_power",
        "ev_current_control_entity": "number.nrgkick_test_charging_current",
        "ev_start_stop_entity": "switch.nrgkick_test_charging_enabled",
        "ev_session_energy_sensor": "sensor.nrgkick_test_charged_energy",
        "ev_total_energy_sensor": "sensor.nrgkick_test_total_charged_energy",
    },
    "keba": {
        "ev_connected_sensor": "binary_sensor.keba_p30_plug",
        "ev_charging_sensor": "binary_sensor.keba_p30_charging_state",
        "ev_charging_power_sensor": "sensor.keba_p30_charging_power",
        "ev_total_energy_sensor": "sensor.keba_p30_total_energy",
    },
    "myenergi": {
        "ev_charging_power_sensor":
            "sensor.test_zappi_1_myenergi_test_zappi_1_power_ct_internal_load",
        "ev_charge_mode_entity": "select.test_zappi_1_myenergi_test_zappi_1_charge_mode",
    },
    "zaptec": {
        "ev_charging_power_sensor": "sensor.zaptec_go2_zap012345_total_charge_power",
        "ev_current_control_entity": "number.abbastova_available_current",
        "ev_session_energy_sensor":
            "sensor.zaptec_go2_zap012345_completed_session_energy",
    },
    "goecharger": {
        "ev_connected_sensor": "sensor.goecharger_wallbox_go_e_car_status",
        "ev_charging_sensor": "sensor.goecharger_wallbox_go_e_car_status",
        "ev_charging_power_sensor": "sensor.goecharger_wallbox_go_e_p_all",
        "ev_start_stop_entity": "switch.goecharger_wallbox_go_e_allow_charging",
        "ev_session_energy_sensor":
            "sensor.goecharger_wallbox_go_e_current_session_charged_energy",
        "ev_total_energy_sensor": "sensor.goecharger_wallbox_go_e_energy_total",
    },
    "vicare": {},
    "blue_current": {},
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
async def test_the_wizard_prefills_only_what_the_crawler_found(hass, name):
    got, in_form = await _prefill(hass, name)
    want = EXPECTED[name]
    for field in sorted(in_form):
        assert got.get(field) == want.get(field), (
            f"{name}.{field}: wizard prefills {got.get(field)!r}, "
            f"expected {want.get(field)!r}")


async def test_a_required_field_the_roles_cannot_fill_stays_empty(hass):
    """The review's replay: OpenEVSE's status sensor is the signal the roles
    chose not to trust; the retired glob path used to fill it."""
    got, in_form = await _prefill(hass, "openevse")
    assert "ev_charging_sensor" in in_form
    assert "ev_charging_sensor" not in got
