"""Regression tests for resilient Zaptec registry discovery."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from custom_components.solar_energy_management.hardware_detection import (
    discover_all_ev_chargers_from_registry,
)


def _entry(entity_id, platform, device_id, device_class=None):
    return SimpleNamespace(
        entity_id=entity_id,
        platform=platform,
        device_id=device_id,
        original_device_class=device_class,
        disabled_by=None,
    )


def test_zaptec_variant_prefers_charger_device_and_infers_missing_device_classes():
    entries = [
        # Zaptec installation/site aggregate — must not be registered as charger.
        _entry(
            "sensor.zaptec_home_installation_total_charge_power",
            "zaptec_custom",
            "site-1",
        ),
        # Actual charger. Some Zaptec/custom registry versions omit device class.
        _entry("binary_sensor.zaptec_garage_cable_connected", "zaptec_custom", "charger-42"),
        _entry("binary_sensor.zaptec_garage_charging", "zaptec_custom", "charger-42"),
        _entry("sensor.zaptec_garage_total_charge_power", "zaptec_custom", "charger-42"),
        _entry("sensor.zaptec_garage_signed_meter_value_kwh", "zaptec_custom", "charger-42"),
        _entry("number.zaptec_garage_available_current", "zaptec_custom", "charger-42"),
        _entry("button.zaptec_garage_resume_charging", "zaptec_custom", "charger-42"),
    ]
    registry = MagicMock()
    registry.entities.values.return_value = entries

    with patch(
        "custom_components.solar_energy_management.hardware_detection.entity_registry.async_get",
        return_value=registry,
    ):
        found = discover_all_ev_chargers_from_registry(MagicMock())

    assert len(found) == 1
    charger = found[0]
    assert charger["_platform"] == "zaptec_custom"
    assert charger["_device_id"] == "charger-42"
    assert charger["ev_charging_power_sensor"] == "sensor.zaptec_garage_total_charge_power"
    assert charger["ev_total_energy_sensor"] == "sensor.zaptec_garage_signed_meter_value_kwh"
    assert charger["ev_current_control_entity"] == "number.zaptec_garage_available_current"


def test_zaptec_without_its_number_reports_no_control_at_all():
    """(#804, 25.08) This test used to pin the OPPOSITE: a Zaptec with no
    current number fell back to ``zaptec.limit_current``. That service writes
    the INSTALLATION's available_current — the user's per-phase grid guard
    (3×25 A on the reporting install), shared by every charger on the site
    and, per the reporter's EVCC layering, never SEM's throttle.

    The new contract: such a charger is still discovered (it is readable, and
    the resume button is a real start/stop surface) but carries NO service
    control. Honest absence beats commanding through the wrong scope."""
    entries = [
        _entry("binary_sensor.zaptec_driveway_cable_connected", "zaptec_custom", "charger-99"),
        _entry("binary_sensor.zaptec_driveway_charging", "zaptec_custom", "charger-99"),
        _entry("button.zaptec_driveway_resume_charging", "zaptec_custom", "charger-99"),
    ]
    registry = MagicMock()
    registry.entities.values.return_value = entries

    with patch(
        "custom_components.solar_energy_management.hardware_detection.entity_registry.async_get",
        return_value=registry,
    ):
        found = discover_all_ev_chargers_from_registry(MagicMock())

    assert len(found) == 1
    assert found[0]["_device_id"] == "charger-99"
    assert "ev_charger_service" not in found[0], (
        "the installation-scoped limit_current fallback is back (#804)"
    )
    assert "ev_service_device_id" not in found[0]
