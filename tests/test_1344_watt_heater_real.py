"""#1344 — a heater driven by a WATT setpoint, on a real Home Assistant.

There is no such heater on the test hardware, and the test server only
watches, so every write would be held back there. This runs a real
``HomeAssistant`` with the real SEM setup and a real ``input_number``
helper as the heater's setpoint, and reads what SEM wrote from the
helper's own state.

The load enters SEM the way a user's does: it is an individual device in
the Energy dashboard (HA's own energy manager), the user maps its control
with the ``set_device_control_mapping`` service, and the registry builds
the watt-setpoint class because the mapped entity declares watts. Keep at,
Extra from surplus and Run now past are set with ``update_device_config``.
Watch-only mode is off for this test.
"""
from __future__ import annotations

import pytest
from homeassistant.setup import async_setup_component

from custom_components.solar_energy_management.const import DOMAIN
from custom_components.solar_energy_management.devices.power_setpoint import (
    PowerSetpointDevice,
)

from .test_services_real import _seed_sem_input_sensors

ROD = "input_number.rod_watts"
ENERGY = "sensor.rod_energy"
TANK = "sensor.rod_tank"
SOLAR = "sensor.test_solar_power"
GRID = "sensor.test_grid_power"
HOUSE_W = 500.0


def _watts(hass) -> float:
    return float(hass.states.get(ROD).state)


def _tank(hass, temp) -> None:
    hass.states.async_set(TANK, str(temp), {
        "unit_of_measurement": "°C", "device_class": "temperature"})


async def _cycles(hass, entry, n, solar_w):
    """Real coordinator cycles with a meter that sees what the rod draws:
    export = sun − house − the helper's value (SEM convention: + export)."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    for _ in range(n):
        hass.states.async_set(SOLAR, str(solar_w), {"unit_of_measurement": "W"})
        hass.states.async_set(GRID, str(solar_w - HOUSE_W - _watts(hass)),
                              {"unit_of_measurement": "W"})
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    return coordinator


def _rod(hass, entry) -> PowerSetpointDevice:
    devices = hass.data[DOMAIN][entry.entry_id]._surplus_controller._devices
    rods = [d for d in devices.values() if isinstance(d, PowerSetpointDevice)]
    assert len(rods) == 1, {k: type(v).__name__ for k, v in devices.items()}
    rod = rods[0]
    # no waiting in real minutes: its own anti-cycle timers are not the subject
    for attr in ("min_on_seconds", "min_off_seconds", "activation_delay_seconds",
                 "min_power_change_interval", "_min_power_change_interval"):
        if hasattr(rod, attr):
            setattr(rod, attr, 0)
    return rod


@pytest.mark.asyncio
async def test_a_watt_heater_follows_the_three_fields_on_a_real_instance(
    sem_real_hass, sem_config_entry, hass_storage,
) -> None:
    from homeassistant.components.energy.data import async_get_manager

    hass = sem_real_hass
    assert await async_setup_component(hass, "input_number", {"input_number": {
        "rod_watts": {"name": "Heating rod setpoint", "min": 0, "max": 3000,
                      "step": 1, "unit_of_measurement": "W", "initial": 0}}})
    hass.states.async_set(ENERGY, "12.5", {
        "unit_of_measurement": "kWh", "device_class": "energy",
        "state_class": "total_increasing", "friendly_name": "Heating rod"})
    _tank(hass, 45.0)
    hass.config.components.add("energy")
    manager = await async_get_manager(hass)
    await manager.async_update({
        "energy_sources": [
            {"type": "solar", "stat_energy_from": "sensor.test_solar_energy",
             "stat_rate": SOLAR},
            {"type": "grid",
             "flow_from": [{"stat_energy_from": "sensor.test_grid_import"}],
             "flow_to": [{"stat_energy_to": "sensor.test_grid_export"}],
             "stat_rate": GRID},
        ],
        "device_consumption": [{"stat_consumption": ENERGY}]})

    _seed_sem_input_sensors(hass)
    hass.states.async_set("sensor.test_battery_soc", "100", {"unit_of_measurement": "%"})
    entry = sem_config_entry
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "observer_mode": False})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # the user maps the control: the helper declares watts
    await hass.services.async_call(DOMAIN, "set_device_control_mapping", {
        "energy_sensor": ENERGY, "control_entity": ROD, "control_type": "current",
    }, blocking=True)
    await hass.async_block_till_done()
    rod = _rod(hass, entry)
    did = rod.device_id

    async def conf(prop, value):
        await hass.services.async_call(DOMAIN, "update_device_config", {
            "device_id": did, "property": prop, "value": value}, blocking=True)

    await conf("control_mode", "surplus")
    await conf("comfort_entity", TANK)
    await conf("comfort_target", "50")
    await conf("comfort_offset", "5")
    await conf("comfort_limit", "36")
    await hass.async_block_till_done()
    rod = _rod(hass, entry)
    assert (rod.comfort_entity, rod.comfort_target, rod.comfort_limit) == (TANK, 50.0, 36.0)
    assert rod.top_up_policy == "solar_only"          # the grid setting is Off
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator._observer_mode is False

    # (d) grid setting Off, no sun, tank under Keep at but above its limit:
    #     solar only is solar only — nothing is bought
    await _cycles(hass, entry, 4, 0.0)
    assert not rod.is_active and _watts(hass) == 0.0

    # (a) under "Run now past": at once, at the helper's maximum — the load
    #     has no power sensor, so its 1 kW rating is only a placeholder
    _tank(hass, 34.0)
    await _cycles(hass, entry, 4, 0.0)
    assert rod.is_active and _watts(hass) == 3000.0

    # (c) at Keep at + Extra: it stops, the helper goes to 0
    _tank(hass, 56.0)
    await _cycles(hass, entry, 4, 2500.0)
    assert not rod.is_active and _watts(hass) == 0.0

    # (b) spare sun, tank between its limit and its ceiling: the helper
    #     follows the free power (2500 W sun − 500 W house), not its maximum
    _tank(hass, 45.0)
    await _cycles(hass, entry, 12, 2500.0)
    assert rod.is_active
    assert 1000.0 <= _watts(hass) <= 2000.0, _watts(hass)
    await _cycles(hass, entry, 12, 1800.0)             # a cloud: it follows down
    assert rod.is_active and 500.0 <= _watts(hass) <= 1300.0, _watts(hass)

    # …and when the tank then falls under its limit, the run is not left at
    # the sun's setpoint: it goes to the maximum
    _tank(hass, 34.0)
    await _cycles(hass, entry, 4, 1800.0)
    assert rod.is_active and _watts(hass) == 3000.0
    _tank(hass, 45.0)                                   # back above the limit

    # (e) a reload (a restart in miniature): the stored fields AND the mode
    #     are on the rebuilt load, and still act
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    rod = _rod(hass, entry)
    assert rod.device_id == did
    assert rod.control_mode.value == "surplus", (
        "the rebuilt watt load lost the mode the user gave it")
    assert (rod.comfort_entity, rod.comfort_target, rod.comfort_offset,
            rod.comfort_limit) == (TANK, 50.0, 5.0, 36.0)
    _tank(hass, 34.0)
    await _cycles(hass, entry, 4, 0.0)
    assert rod.is_active and _watts(hass) == 3000.0
    _tank(hass, 56.0)
    await _cycles(hass, entry, 4, 0.0)
    assert not rod.is_active and _watts(hass) == 0.0
