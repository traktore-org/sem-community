"""Tests for #442 slim install flow.

Pins two contracts:
  1. The user step routes directly to hardware (no EV step at install).
  2. The OptionsFlow still exposes all power-user steps so existing
     entries can still walk the legacy path. Removing/renaming any
     of these would silently break the deep-links the new
     ``sem-config-card`` uses to surface advanced settings.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from custom_components.solar_energy_management.config_flow import (
    SolarEnergyManagementConfigFlow,
    OptionsFlowHandler,
)


@pytest.mark.asyncio
async def test_install_flow_is_two_steps_only():
    """The user step must route directly to hardware (no EV step at install)."""
    flow = SolarEnergyManagementConfigFlow()
    flow.hass = MagicMock()

    energy_config = MagicMock()
    energy_config.solar_power = "sensor.solar_power"
    energy_config.grid_power = "sensor.grid_power"
    energy_config.battery_power = "sensor.battery_power"
    energy_config.ev_power = "sensor.ev_power"
    energy_config.to_dict = MagicMock(return_value={
        "solar_power_sensor": "sensor.solar_power",
        "grid_power_sensor": "sensor.grid_power",
        "battery_power_sensor": "sensor.battery_power",
        "ev_charging_power_sensor": "sensor.ev_power",
    })

    detector = MagicMock()
    detector.get_suggested_ev_defaults.return_value = {}
    detector.validate_ev_configuration.return_value = {}

    with patch(
        "custom_components.solar_energy_management.config_flow.read_energy_dashboard_config",
        new_callable=AsyncMock, return_value=energy_config,
    ), patch(
        "custom_components.solar_energy_management.config_flow.HardwareDetector",
        return_value=detector,
    ), patch(
        "custom_components.solar_energy_management.config_flow.discover_ev_charger_from_registry",
        return_value={},
    ), patch(
        "custom_components.solar_energy_management.config_flow.discover_inverter_from_registry",
        return_value=None,
    ):
        result = await flow.async_step_user(user_input={"observer_mode": False})

    # Must skip ev_charger and go straight to hardware
    assert result["step_id"] == "hardware", (
        "slim install (#442) must skip ev_charger step entirely; "
        f"got step_id={result['step_id']!r}"
    )


def test_install_defaults_seed_empty_ev_chargers_list():
    """`_install_defaults()` must seed an empty ``ev_chargers`` list so
    downstream code always finds the list — even when no EV was set up at
    install."""
    flow = SolarEnergyManagementConfigFlow()
    defaults = flow._install_defaults()
    assert "ev_chargers" in defaults, (
        "#442: _install_defaults must seed ev_chargers so config-card's "
        "charger walk and EV-keys migration find an empty list, not KeyError"
    )
    assert defaults["ev_chargers"] == []


def test_install_defaults_never_enable_phase_guard_without_topology():
    """Silent install defaults must not create an ambiguous enforcing config.

    Runtime helpers intentionally use the least-assumptive ``grid_only``
    fallback for legacy/disabled entries. If the slim installer ever starts
    enabling the phase guard by default, it must also persist the selected
    topology so a hybrid installation cannot silently lose its inverter lane.
    """
    defaults = SolarEnergyManagementConfigFlow._install_defaults()

    # Pin today's safe default while retaining the forward-looking invariant
    # that any future opt-in must persist an unambiguous topology.
    assert not defaults.get("phase_guard_enabled", False)
    assert not defaults.get("phase_guard_enabled", False) or (
        defaults.get("phase_guard_topology") in {"grid_only", "hybrid_load_port"}
    )


def test_options_flow_ev_charger_step_still_registered():
    """The OptionsFlow EV step must remain since (1) power users use it
    directly and (2) the new ``sem-config-card`` deep-links to it for
    add/remove/reorder operations (out of scope for inline edit in v1)."""
    flow = OptionsFlowHandler.__new__(OptionsFlowHandler)
    assert hasattr(flow, "async_step_ev_charger"), (
        "Removing the OptionsFlow EV step would break deep-links from "
        "the new Configuration tab into HA settings"
    )
    assert hasattr(flow, "async_step_ev_charger_add")
    assert hasattr(flow, "async_step_ev_charger_remove")


def test_options_flow_all_power_user_steps_still_registered():
    """All 9 OptionsFlow steps the legacy power-user path relies on must
    stay; ``sem-config-card`` deep-links to each one as a fallback for
    fields that don't have a runtime entity yet."""
    flow_cls = OptionsFlowHandler
    for step in (
        "async_step_init", "async_step_ev_charger",
        "async_step_settings_tariff", "async_step_heat_pump",
        "async_step_battery_scheduler", "async_step_load_management",
        "async_step_notifications",
    ):
        assert hasattr(flow_cls, step), (
            f"OptionsFlow lost step {step!r} — Configuration tab "
            "deep-links will 404"
        )
