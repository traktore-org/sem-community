"""Regression for durable auto-discovered EV charger storage."""
from custom_components.solar_energy_management import (
    build_discovered_charger_storage,
    stable_discovered_charger_id,
)


def test_stable_id_uses_platform_and_device_identity():
    charger = {"_platform": "zaptec_custom", "_device_id": "charger-42"}
    first = stable_discovered_charger_id(charger)
    second = stable_discovered_charger_id(dict(charger))
    other = stable_discovered_charger_id({**charger, "_device_id": "charger-99"})

    assert first == second
    assert first.startswith("zaptec_custom_")
    assert first != other


def test_discovered_charger_is_persisted_to_data_and_options():
    discovered = {
        "_platform": "zaptec_custom",
        "_device_id": "charger-42",
        "ev_charging_power_sensor": "sensor.zaptec_garage_total_charge_power",
        "ev_current_control_entity": "number.zaptec_garage_available_current",
    }
    new_data, new_options, chargers = build_discovered_charger_storage(
        {"solar_power_sensor": "sensor.pv"},
        {"observer_mode": True},
        discovered,
    )

    assert new_data["solar_power_sensor"] == "sensor.pv"
    assert new_options["observer_mode"] is True
    assert new_data["ev_chargers"] == chargers
    assert new_options["ev_chargers"] == chargers
    assert chargers[0]["id"] == stable_discovered_charger_id(discovered)
    assert chargers[0]["name"] == "Zaptec Charger"
    assert "_platform" not in chargers[0]
    assert "_device_id" not in chargers[0]
