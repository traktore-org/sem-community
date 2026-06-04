"""Test the Solar Energy Management config flow.

Aligned with the slim 3-step install flow introduced in the slim-down work
tracked by issue #98:

    user  →  ev_charger  →  hardware  →  create_entry

Tests for the removed install steps (notifications / settings /
load_management) live on the OptionsFlowHandler now and have their own
coverage further down this file.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.solar_energy_management.config_flow import (
    SolarEnergyManagementConfigFlow,
    OptionsFlowHandler,
)
from custom_components.solar_energy_management.const import DOMAIN
from custom_components.solar_energy_management.ha_energy_reader import EnergyDashboardConfig


def _make_energy_dashboard_config(
    has_solar=True, has_grid=True, has_battery=True, has_ev=True
):
    """Create a fully configured EnergyDashboardConfig for testing."""
    config = EnergyDashboardConfig()
    config.has_solar = has_solar
    config.has_grid = has_grid
    config.has_battery = has_battery
    config.has_ev = has_ev
    if has_solar:
        config.solar_power = "sensor.solar_power"
        config.solar_energy = "sensor.solar_energy"
    if has_grid:
        config.grid_import_power = "sensor.grid_import_power"
        config.grid_import_energy = "sensor.grid_import_energy"
        config.grid_export_power = "sensor.grid_export_power"
        config.grid_export_energy = "sensor.grid_export_energy"
    if has_battery:
        config.battery_power = "sensor.battery_power"
        config.battery_charge_energy = "sensor.battery_charge_energy"
        config.battery_discharge_energy = "sensor.battery_discharge_energy"
    if has_ev:
        config.ev_power = "sensor.ev_power"
        config.ev_energy = "sensor.ev_energy"
    return config


# Valid EV charger input for reuse across tests. Vehicle SOC fields moved
# to the OptionsFlow, so they no longer appear here.
VALID_EV_INPUT = {
    "ev_connected_sensor": "binary_sensor.ev_connected",
    "ev_charging_sensor": "binary_sensor.ev_charging",
    "ev_charging_power_sensor": "sensor.ev_charging_power",
    "ev_charger_service": "",
    "ev_current_sensor": "",
    "ev_total_energy_sensor": "sensor.ev_total_energy",
}

# Valid hardware step input. The "generate_dashboard_on_install" toggle
# is intentionally False in tests to keep them deterministic.
VALID_HARDWARE_INPUT = {
    "battery_capacity_kwh": 12,
    "target_peak_limit": 5.0,
    "generate_dashboard_on_install": False,
}


def _create_flow(mock_hass):
    """Create and initialize a config flow instance with mocked hass."""
    flow = SolarEnergyManagementConfigFlow()
    flow.hass = mock_hass
    return flow


@pytest.mark.unit
class TestSolarEnergyManagementConfigFlow:
    """Test the slim 3-step install flow."""

    @pytest.mark.asyncio
    async def test_form_display(self, mock_hass):
        """async_step_user shows the form when Energy Dashboard is configured."""
        energy_config = _make_energy_dashboard_config()
        flow = _create_flow(mock_hass)

        with patch(
            "custom_components.solar_energy_management.config_flow.read_energy_dashboard_config",
            new_callable=AsyncMock,
            return_value=energy_config,
        ):
            result = await flow.async_step_user()

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert "summary" in result.get("description_placeholders", {})

    @pytest.mark.asyncio
    async def test_energy_dashboard_not_configured(self, mock_hass):
        """Abort with reason energy_dashboard_not_configured."""
        flow = _create_flow(mock_hass)

        with patch(
            "custom_components.solar_energy_management.config_flow.read_energy_dashboard_config",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await flow.async_step_user()

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "energy_dashboard_not_configured"

    @pytest.mark.asyncio
    async def test_energy_dashboard_incomplete(self, mock_hass):
        """Abort when Energy Dashboard is missing solar."""
        energy_config = _make_energy_dashboard_config(has_solar=False, has_grid=True)
        flow = _create_flow(mock_hass)

        with patch(
            "custom_components.solar_energy_management.config_flow.read_energy_dashboard_config",
            new_callable=AsyncMock,
            return_value=energy_config,
        ):
            result = await flow.async_step_user()

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "energy_dashboard_incomplete"
        assert "Solar" in result["description_placeholders"]["missing"]

    @pytest.mark.asyncio
    async def test_energy_dashboard_incomplete_no_grid(self, mock_hass):
        """Abort when Energy Dashboard has solar but no grid."""
        energy_config = _make_energy_dashboard_config(has_solar=True, has_grid=False)
        flow = _create_flow(mock_hass)

        with patch(
            "custom_components.solar_energy_management.config_flow.read_energy_dashboard_config",
            new_callable=AsyncMock,
            return_value=energy_config,
        ):
            result = await flow.async_step_user()

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "energy_dashboard_incomplete"
        assert "Grid" in result["description_placeholders"]["missing"]

    @pytest.mark.asyncio
    async def test_user_step_proceeds_to_ev_charger(self, mock_hass):
        """Submitting the user step (with observer_mode) advances to ev_charger."""
        energy_config = _make_energy_dashboard_config()
        flow = _create_flow(mock_hass)

        mock_detector = MagicMock()
        mock_detector.get_suggested_ev_defaults.return_value = {}
        mock_detector.validate_ev_configuration.return_value = {}

        with patch(
            "custom_components.solar_energy_management.config_flow.read_energy_dashboard_config",
            new_callable=AsyncMock,
            return_value=energy_config,
        ), patch(
            "custom_components.solar_energy_management.config_flow.HardwareDetector",
            return_value=mock_detector,
        ), patch(
            "custom_components.solar_energy_management.config_flow.discover_ev_charger_from_registry",
            return_value={},
        ):
            result = await flow.async_step_user(user_input={"observer_mode": False})

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "ev_charger"
        # observer_mode value is persisted into self._data so the hardware step
        # can include it in the created entry
        assert flow._data.get("observer_mode") is False

    @pytest.mark.asyncio
    async def test_user_step_observer_mode_persisted(self, mock_hass):
        """observer_mode=True survives into self._data."""
        energy_config = _make_energy_dashboard_config()
        flow = _create_flow(mock_hass)

        mock_detector = MagicMock()
        mock_detector.get_suggested_ev_defaults.return_value = {}
        mock_detector.validate_ev_configuration.return_value = {}

        with patch(
            "custom_components.solar_energy_management.config_flow.read_energy_dashboard_config",
            new_callable=AsyncMock,
            return_value=energy_config,
        ), patch(
            "custom_components.solar_energy_management.config_flow.HardwareDetector",
            return_value=mock_detector,
        ), patch(
            "custom_components.solar_energy_management.config_flow.discover_ev_charger_from_registry",
            return_value={},
        ):
            await flow.async_step_user(user_input={"observer_mode": True})

        assert flow._data.get("observer_mode") is True

    @pytest.mark.asyncio
    async def test_ev_charger_step_validation(self, mock_hass):
        """EV charger entity validation surfaces errors back to the form."""
        energy_config = _make_energy_dashboard_config()
        flow = _create_flow(mock_hass)
        flow._energy_dashboard_config = energy_config

        mock_detector = MagicMock()
        mock_detector.get_suggested_ev_defaults.return_value = {}
        mock_detector.validate_ev_configuration.return_value = {
            "ev_connected_sensor": "Required sensor not configured",
            "ev_charging_sensor": "Entity not found or invalid",
        }

        with patch(
            "custom_components.solar_energy_management.config_flow.HardwareDetector",
            return_value=mock_detector,
        ), patch(
            "custom_components.solar_energy_management.config_flow.discover_ev_charger_from_registry",
            return_value={},
        ):
            result = await flow.async_step_ev_charger(
                user_input={
                    "ev_connected_sensor": "",
                    "ev_charging_sensor": "binary_sensor.nonexistent",
                    "ev_charging_power_sensor": "sensor.ev_power",
                }
            )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "ev_charger"
        assert "ev_connected_sensor" in result["errors"]
        assert "ev_charging_sensor" in result["errors"]

    @pytest.mark.asyncio
    async def test_ev_charger_step_valid_advances_to_hardware(self, mock_hass):
        """Valid EV charger input now advances to the hardware step."""
        energy_config = _make_energy_dashboard_config()
        flow = _create_flow(mock_hass)
        flow._energy_dashboard_config = energy_config
        flow._data = energy_config.to_dict()

        mock_detector = MagicMock()
        mock_detector.validate_ev_configuration.return_value = {}
        mock_detector.get_suggested_ev_defaults.return_value = {}

        with patch(
            "custom_components.solar_energy_management.config_flow.HardwareDetector",
            return_value=mock_detector,
        ), patch(
            "custom_components.solar_energy_management.config_flow.discover_ev_charger_from_registry",
            return_value={},
        ), patch(
            "custom_components.solar_energy_management.config_flow.discover_inverter_from_registry",
            return_value=None,
        ):
            result = await flow.async_step_ev_charger(user_input=VALID_EV_INPUT)

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "hardware"

    @pytest.mark.asyncio
    async def test_hardware_step_creates_entry(self, mock_hass):
        """Submitting the hardware step creates the config entry with merged defaults."""
        energy_config = _make_energy_dashboard_config()
        flow = _create_flow(mock_hass)
        flow._energy_dashboard_config = energy_config
        flow._data = {
            **energy_config.to_dict(),
            **VALID_EV_INPUT,
            "observer_mode": False,
        }

        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        with patch(
            "custom_components.solar_energy_management.config_flow.discover_inverter_from_registry",
            return_value="number.batteries_maximale_entladeleistung",
        ):
            result = await flow.async_step_hardware(user_input=VALID_HARDWARE_INPUT)

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "Solar Energy Management"
        data = result["data"]
        # Hardware step inputs
        assert data["battery_capacity_kwh"] == 12
        assert data["target_peak_limit"] == 5.0
        # Auto-detected discharge entity from inverter discovery
        assert (
            data["battery_discharge_control_entity"]
            == "number.batteries_maximale_entladeleistung"
        )
        # Bucket-C defaults silently merged
        assert data["update_interval"] == 10  # DEFAULT_UPDATE_INTERVAL
        assert data["daily_ev_target"] == 10  # DEFAULT_DAILY_EV_TARGET
        assert data["enable_charger_notifications"] is True
        assert data["load_management_enabled"] is True
        # Energy Dashboard sensors are still present
        assert data["solar_power_sensor"] == "sensor.solar_power"
        # EV inputs from previous step
        assert data["ev_connected_sensor"] == "binary_sensor.ev_connected"
        # Observer mode preserved from user step
        assert data["observer_mode"] is False

    @pytest.mark.asyncio
    async def test_ev_charger_step_schema_keeps_wallbox_control_field(self, mock_hass):
        """#397 onboarding slim-down: only `ev_current_control_entity` survives
        from the PR #390 expansion. It's the genuine Wallbox install-time
        blocker — no default can substitute for picking the right number
        entity. The other 8 fields from #390 (tunables with sensible
        defaults) reverted to OptionsFlow."""
        energy_config = _make_energy_dashboard_config()
        flow = _create_flow(mock_hass)
        flow._energy_dashboard_config = energy_config

        mock_detector = MagicMock()
        mock_detector.get_suggested_ev_defaults.return_value = {}

        with patch(
            "custom_components.solar_energy_management.config_flow.HardwareDetector",
            return_value=mock_detector,
        ), patch(
            "custom_components.solar_energy_management.config_flow.discover_ev_charger_from_registry",
            return_value={},
        ):
            result = await flow.async_step_ev_charger(user_input=None)

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "ev_charger"
        schema_keys = {str(k) for k in result["data_schema"].schema.keys()}

        # Wallbox install-time blocker — STAYS.
        assert "ev_current_control_entity" in schema_keys, (
            "#384 Part 2: the one #390 field that must remain at install — "
            "Wallbox-style chargers cannot be configured without it"
        )

        # The 8 per-charger tunables reverted to OptionsFlow per #397 to
        # bring the install step back to the slim-3-step shape.
        for reverted in (
            "ev_surplus_priority",
            "daily_ev_target",
            "daily_ev_target_max",
            "ev_night_initial_current",
            "ev_min_current",
            "ev_target_soc",
            "ev_target_soc_max",
            "ev_battery_capacity_kwh",
        ):
            assert reverted not in schema_keys, (
                f"#397: {reverted} must NOT appear at install — it lives in "
                "OptionsFlow with a sensible default. Surfacing it again "
                "would reopen the 16-field abandon-zone install step."
            )

    @pytest.mark.asyncio
    async def test_hardware_step_migrates_current_control_entity(self, mock_hass):
        """The one #390 field we kept (`ev_current_control_entity`) must still
        land in `ev_chargers[0]` via the _EV_KEYS bridge."""
        energy_config = _make_energy_dashboard_config()
        flow = _create_flow(mock_hass)
        flow._energy_dashboard_config = energy_config
        flow._data = {
            **energy_config.to_dict(),
            **VALID_EV_INPUT,
            "observer_mode": False,
            "ev_current_control_entity": "number.wallbox_max_charging_current",
        }

        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        with patch(
            "custom_components.solar_energy_management.config_flow.discover_inverter_from_registry",
            return_value="number.batteries_maximale_entladeleistung",
        ):
            result = await flow.async_step_hardware(user_input=VALID_HARDWARE_INPUT)

        assert result["type"] == FlowResultType.CREATE_ENTRY
        charger_0 = result["data"]["ev_chargers"][0]
        assert charger_0["ev_current_control_entity"] == "number.wallbox_max_charging_current"

    @pytest.mark.asyncio
    async def test_hardware_step_no_inverter_detected_uses_empty(self, mock_hass):
        """If discover_inverter_from_registry returns None, the key is set to ''."""
        energy_config = _make_energy_dashboard_config()
        flow = _create_flow(mock_hass)
        flow._energy_dashboard_config = energy_config
        flow._data = {
            **energy_config.to_dict(),
            **VALID_EV_INPUT,
            "observer_mode": False,
        }

        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        with patch(
            "custom_components.solar_energy_management.config_flow.discover_inverter_from_registry",
            return_value=None,
        ):
            result = await flow.async_step_hardware(user_input=VALID_HARDWARE_INPUT)

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"]["battery_discharge_control_entity"] == ""

    @pytest.mark.asyncio
    async def test_full_flow_creates_entry(self, mock_hass):
        """End-to-end walk through the slim 3-step install flow."""
        energy_config = _make_energy_dashboard_config()
        flow = _create_flow(mock_hass)

        mock_detector = MagicMock()
        mock_detector.get_suggested_ev_defaults.return_value = {}
        mock_detector.validate_ev_configuration.return_value = {}

        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        with patch(
            "custom_components.solar_energy_management.config_flow.read_energy_dashboard_config",
            new_callable=AsyncMock,
            return_value=energy_config,
        ), patch(
            "custom_components.solar_energy_management.config_flow.HardwareDetector",
            return_value=mock_detector,
        ), patch(
            "custom_components.solar_energy_management.config_flow.discover_ev_charger_from_registry",
            return_value={},
        ), patch(
            "custom_components.solar_energy_management.config_flow.discover_inverter_from_registry",
            return_value=None,
        ):
            # Step 1: user
            result = await flow.async_step_user(user_input={"observer_mode": False})
            assert result["step_id"] == "ev_charger"

            # Step 2: ev_charger
            result = await flow.async_step_ev_charger(user_input=VALID_EV_INPUT)
            assert result["step_id"] == "hardware"

            # Step 3: hardware → creates entry
            result = await flow.async_step_hardware(user_input=VALID_HARDWARE_INPUT)

        assert result["type"] == FlowResultType.CREATE_ENTRY
        data = result["data"]
        assert data["solar_power_sensor"] == "sensor.solar_power"
        assert data["ev_connected_sensor"] == "binary_sensor.ev_connected"
        assert data["battery_capacity_kwh"] == 12
        assert data["target_peak_limit"] == 5.0
        # Defaults silently filled in
        assert data["update_interval"] == 10
        assert data["enable_charger_notifications"] is True

    @pytest.mark.asyncio
    async def test_duplicate_entry_prevention(self, mock_hass):
        """Duplicate setup is caught by the unique-id guard in the hardware step."""
        flow = _create_flow(mock_hass)
        flow._data = {}
        flow._energy_dashboard_config = _make_energy_dashboard_config()

        flow.async_set_unique_id = AsyncMock()

        from homeassistant.data_entry_flow import AbortFlow

        flow._abort_if_unique_id_configured = MagicMock(
            side_effect=AbortFlow("already_configured")
        )

        with patch(
            "custom_components.solar_energy_management.config_flow.discover_inverter_from_registry",
            return_value=None,
        ):
            result = await flow.async_step_hardware(user_input=VALID_HARDWARE_INPUT)

        # AbortFlow caught by the generic except, form re-displayed with base error
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "hardware"
        assert result["errors"]["base"] == "unknown"
        flow._abort_if_unique_id_configured.assert_called_once()

    @pytest.mark.asyncio
    async def test_options_flow_exists(self, mock_hass, config_entry):
        """The options flow handler is reachable from the config flow class."""
        options_flow = SolarEnergyManagementConfigFlow.async_get_options_flow(
            config_entry
        )
        assert isinstance(options_flow, OptionsFlowHandler)

    @pytest.mark.asyncio
    async def test_options_flow_init_shows_ev_charger(self, mock_hass, config_entry):
        """OptionsFlow init still routes to the ev_charger sub-step."""
        options_flow = OptionsFlowHandler(config_entry)
        options_flow.hass = mock_hass
        config_entry.options = {}

        with patch.object(
            type(options_flow),
            "config_entry",
            new_callable=lambda: property(lambda self: config_entry),
        ):
            result = await options_flow.async_step_init()

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "ev_charger"

    @pytest.mark.asyncio
    async def test_energy_dashboard_summary_content(self, mock_hass):
        """User-step summary lists every detected category."""
        energy_config = _make_energy_dashboard_config(
            has_solar=True, has_grid=True, has_battery=True, has_ev=True
        )
        flow = _create_flow(mock_hass)

        with patch(
            "custom_components.solar_energy_management.config_flow.read_energy_dashboard_config",
            new_callable=AsyncMock,
            return_value=energy_config,
        ):
            result = await flow.async_step_user()

        summary = result["description_placeholders"]["summary"]
        assert "Solar" in summary
        assert "Grid" in summary
        assert "Battery" in summary
        assert "EV" in summary

    @pytest.mark.asyncio
    async def test_energy_dashboard_summary_without_optional(self, mock_hass):
        """Summary excludes categories that are not configured."""
        energy_config = _make_energy_dashboard_config(
            has_solar=True, has_grid=True, has_battery=False, has_ev=False
        )
        flow = _create_flow(mock_hass)

        with patch(
            "custom_components.solar_energy_management.config_flow.read_energy_dashboard_config",
            new_callable=AsyncMock,
            return_value=energy_config,
        ):
            result = await flow.async_step_user()

        summary = result["description_placeholders"]["summary"]
        assert "Solar" in summary
        assert "Grid" in summary
        assert "Battery" not in summary
        assert "EV" not in summary
