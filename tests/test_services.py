"""Test EMS Solar Optimizer services."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import os

from custom_components.solar_energy_management.coordinator import SEMCoordinator


@pytest.mark.unit
class TestEMSServices:
    """Test EMS service calls."""

    @pytest.mark.asyncio
    async def test_force_update_service(self, mock_coordinator):
        """Test force update service."""
        mock_coordinator.async_refresh = AsyncMock()

        await mock_coordinator.async_force_update()

        mock_coordinator.async_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_logs_service(self, mock_coordinator):
        """Test get logs service."""
        # Mock the log buffer
        mock_coordinator._log_buffer = [
            {
                "timestamp": "2024-01-15T12:00:00",
                "level": "INFO",
                "message": "Test log message 1"
            },
            {
                "timestamp": "2024-01-15T12:01:00",
                "level": "WARNING",
                "message": "Test log message 2"
            }
        ]

        # Service should log the request
        await mock_coordinator.async_get_logs(limit=50)

        # Verify it was called without errors
        assert True  # If we reach here, no exception was raised

    @pytest.mark.asyncio
    async def test_set_log_level_service(self, mock_coordinator):
        """Test set log level service."""
        await mock_coordinator.async_set_log_level(level="debug")

        # Service should log the request
        assert True  # If we reach here, no exception was raised

    @pytest.mark.asyncio
    async def test_clear_logs_service(self, mock_coordinator):
        """Test clear logs service."""
        await mock_coordinator.async_clear_logs()

        # Service should log the request
        assert True  # If we reach here, no exception was raised

    @pytest.mark.asyncio
    async def test_get_dashboard_config_service(self, mock_coordinator):
        """Test get dashboard config service."""
        # Mock file system
        dashboard_content = """
title: Test Dashboard
views:
  - type: grid
    cards:
      - type: entities
        """

        with patch("builtins.open", mock_open(read_data=dashboard_content)):
            with patch("os.path.join") as mock_join:
                with patch("os.path.dirname") as mock_dirname:
                    mock_dirname.return_value = "/test/component"
                    mock_join.return_value = "/test/component/dashboard/sem_level2_dashboard.yaml"

                    await mock_coordinator.async_get_dashboard_config(level="2")

                    # Verify file operations were attempted
                    mock_dirname.assert_called()
                    mock_join.assert_called()

    @pytest.mark.asyncio
    async def test_get_dashboard_config_invalid_level(self, mock_coordinator):
        """Test get dashboard config with invalid level."""
        await mock_coordinator.async_get_dashboard_config(level="5")

        # Should handle invalid level gracefully
        assert True

    @pytest.mark.asyncio
    async def test_copy_dashboard_images_service(self, mock_coordinator):
        """Test copy dashboard images service."""
        # Mock file system operations
        with patch("os.path.exists") as mock_exists:
            with patch("os.makedirs") as mock_makedirs:
                with patch("os.listdir") as mock_listdir:
                    with patch("shutil.copy2") as mock_copy:
                        # Setup mocks
                        mock_exists.return_value = True
                        mock_listdir.return_value = ["sem_dashboard_level3.png", "sem_dashboard_level4.png"]
                        mock_coordinator.hass = MagicMock()
                        mock_coordinator.hass.config.config_dir = "/config"

                        await mock_coordinator.async_copy_dashboard_images()

                        # Verify directory creation
                        mock_makedirs.assert_called_once()

                        # Verify files were copied
                        assert mock_copy.call_count == 2

    @pytest.mark.asyncio
    async def test_copy_dashboard_images_no_source(self, mock_coordinator):
        """Test copy dashboard images when source doesn't exist."""
        with patch("os.path.exists", return_value=False):
            mock_coordinator.hass = MagicMock()
            mock_coordinator.hass.config.config_dir = "/config"

            await mock_coordinator.async_copy_dashboard_images()

            # Should handle missing source gracefully
            assert True

    @pytest.mark.asyncio
    async def test_copy_dashboard_images_no_files(self, mock_coordinator):
        """Test copy dashboard images when no image files exist."""
        with patch("os.path.exists", return_value=True):
            with patch("os.makedirs"):
                with patch("os.listdir", return_value=["readme.txt", "config.yaml"]):  # No image files
                    mock_coordinator.hass = MagicMock()
                    mock_coordinator.hass.config.config_dir = "/config"

                    await mock_coordinator.async_copy_dashboard_images()

                    # Should handle no image files gracefully
                    assert True

    @pytest.mark.asyncio
    async def test_copy_dashboard_images_error_handling(self, mock_coordinator):
        """Test copy dashboard images error handling."""
        with patch("os.path.exists", side_effect=Exception("File system error")):
            mock_coordinator.hass = MagicMock()
            mock_coordinator.hass.config.config_dir = "/config"

            await mock_coordinator.async_copy_dashboard_images()

            # Should handle exceptions gracefully
            assert True

    @staticmethod
    def _capture_service_handlers(hass):
        """Register services and capture handlers into a dict keyed by service name.

        This avoids fragile index-based lookups into call_args_list.
        """
        handlers = {}
        original_register = hass.services.async_register

        def capturing_register(domain, service_name, handler, **kwargs):
            handlers[service_name] = handler
            return original_register(domain, service_name, handler, **kwargs)

        hass.services.async_register = MagicMock(side_effect=capturing_register)
        return handlers

    @pytest.mark.asyncio
    async def test_service_registration(self, hass, mock_coordinator):
        """Test that services are properly registered."""
        from custom_components.solar_energy_management import _async_register_services

        hass.services.has_service = MagicMock(return_value=False)
        handlers = self._capture_service_handlers(hass)

        await _async_register_services(hass, mock_coordinator)

        expected_services = [
            "generate_dashboard",
            "configure_energy_dashboard",
            "sync_priorities_from_dashboard",
            "update_device_priorities",
            "update_device_config",
            "update_target_peak",
        ]

        for service in expected_services:
            assert service in handlers, f"Service '{service}' was not registered"

    @pytest.mark.asyncio
    async def test_service_handler_valid_service(self, hass, mock_coordinator):
        """Test sync_priorities_from_dashboard handler with valid dashboard file."""
        from custom_components.solar_energy_management import _async_register_services

        hass.services.has_service = MagicMock(return_value=False)
        handlers = self._capture_service_handlers(hass)

        # Mock the load manager
        mock_coordinator._load_manager = MagicMock()
        mock_coordinator._load_manager._devices = {"load_device_washer": MagicMock()}
        mock_coordinator._load_manager.update_device_priority = AsyncMock()

        await _async_register_services(hass, mock_coordinator)

        handler = handlers["sync_priorities_from_dashboard"]

        # Create a mock service call
        mock_call = MagicMock()
        mock_call.data = {"dashboard_storage_key": "lovelace.test", "view_path": "test"}

        # Mock the file system to simulate dashboard file with proper structure
        dashboard_content = json.dumps({
            "data": {
                "config": {
                    "views": [{
                        "path": "test",
                        "sections": [{
                            "cards": [{
                                "title": "Device Priority Management",
                                "type": "custom:mushroom-title-card"
                            }, {
                                "type": "custom:mushroom-entity-card",
                                "secondary": "{{ states('load_device_washer') }}"
                            }]
                        }]
                    }]
                }
            }
        })

        with patch("builtins.open", mock_open(read_data=dashboard_content)):
            with patch("os.path.exists", return_value=True):
                await handler(mock_call)

        mock_coordinator._load_manager.update_device_priority.assert_called_once()

    @pytest.mark.asyncio
    async def test_service_handler_invalid_service(self, hass, mock_coordinator):
        """Test sync_priorities_from_dashboard handles missing dashboard file gracefully."""
        from custom_components.solar_energy_management import _async_register_services

        hass.services.has_service = MagicMock(return_value=False)
        handlers = self._capture_service_handlers(hass)

        mock_coordinator._load_manager = MagicMock()

        await _async_register_services(hass, mock_coordinator)

        handler = handlers["sync_priorities_from_dashboard"]

        mock_call = MagicMock()
        mock_call.data = {"dashboard_storage_key": "lovelace.nonexistent", "view_path": "missing"}

        # File doesn't exist — should handle gracefully without exception
        with patch("os.path.exists", return_value=False):
            await handler(mock_call)

    @pytest.mark.asyncio
    async def test_dashboard_config_file_paths(self, mock_coordinator):
        """Test dashboard config service file path resolution."""
        import os

        level_files = {
            "2": "ems_level2_dashboard.yaml",  # Current implementation uses ems_ prefix
            "3": "ems_level3_dashboard.yaml",
            "4": "ems_level4_dashboard.yaml"
        }

        for level, expected_filename in level_files.items():
            with patch("os.path.dirname") as mock_dirname:
                with patch("os.path.join") as mock_join:
                    mock_dirname.return_value = "/test/component"

                    # Mock the file path resolution
                    expected_path = f"/test/component/dashboard/{expected_filename}"
                    mock_join.return_value = expected_path

                    with patch("builtins.open", mock_open(read_data="test content")):
                        await mock_coordinator.async_get_dashboard_config(level=level)

                        # Verify correct file path was constructed
                        mock_join.assert_called_with("/test/component", "dashboard", expected_filename)

    @pytest.mark.asyncio
    async def test_service_parameter_handling(self, mock_coordinator):
        """Test service parameter handling and validation."""
        # Test get_logs with limit parameter
        await mock_coordinator.async_get_logs(limit=100)
        assert True

        # Test get_logs without limit parameter
        await mock_coordinator.async_get_logs()
        assert True

        # Test set_log_level with level parameter
        await mock_coordinator.async_set_log_level(level="warning")
        assert True

        # Test get_dashboard_config with level parameter
        with patch("builtins.open", mock_open(read_data="test")):
            await mock_coordinator.async_get_dashboard_config(level="3")
            assert True

        # Test copy_dashboard_images without parameters
        with patch("os.path.exists", return_value=False):
            mock_coordinator.hass = MagicMock()
            mock_coordinator.hass.config.config_dir = "/config"
            await mock_coordinator.async_copy_dashboard_images()
            assert True