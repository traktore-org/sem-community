"""#1301 — a smaller second battery is returned to its OWN maximum.

Two packs of different size share one ``battery_max_discharge_power``. The
startup restore and ``command_normal`` asked every pack for that one value;
a pack whose limit control stops lower refused it, so its stale limit stayed
and a limit SEM set was never lifted. The pack's own ceiling is what its
control accepts (its ``max``), capped by the setting.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.actuate_battery import (
    restore_discharge_limit_on_startup,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.power_control import (
    entity_max_watts,
)


def _hass(states: dict, unit: str = "W"):
    hass = MagicMock()
    table = {}
    for ent, (val, mx) in states.items():
        table[ent] = SimpleNamespace(
            entity_id=ent, state=str(val),
            attributes={"unit_of_measurement": unit, "min": 0, "max": mx, "step": 1})
    hass.states.get = lambda ent: table.get(ent)

    async def call(domain, service, data, **kw):
        table[data["entity_id"]].state = str(data["value"])
    hass.services.async_call = AsyncMock(side_effect=call)
    return hass, table


def _written(hass):
    return {c.args[2]["entity_id"]: c.args[2]["value"]
            for c in hass.services.async_call.await_args_list}


class TestStartupRestore:
    @pytest.mark.asyncio
    async def test_each_pack_goes_back_to_its_own_top(self):
        hass, _ = _hass({"number.b1_limit": (500.0, 10000),
                         "number.b2_limit": (500.0, 3000)})
        await restore_discharge_limit_on_startup(hass, {
            "battery_discharge_control_entities": ["number.b1_limit", "number.b2_limit"],
            "battery_max_discharge_power": 5000,
        })
        assert _written(hass) == {"number.b1_limit": 5000, "number.b2_limit": 3000}

    @pytest.mark.asyncio
    async def test_the_setting_still_caps_a_bigger_pack(self):
        hass, _ = _hass({"number.b1_limit": (500.0, 10000)})
        await restore_discharge_limit_on_startup(hass, {
            "battery_discharge_control_entities": ["number.b1_limit"],
            "battery_max_discharge_power": 4000,
        })
        assert _written(hass) == {"number.b1_limit": 4000}

    @pytest.mark.asyncio
    async def test_a_kw_control_is_read_in_its_own_unit(self):
        hass, _ = _hass({"number.b2_limit": (0.5, 3)}, unit="kW")
        await restore_discharge_limit_on_startup(hass, {
            "battery_discharge_control_entities": ["number.b2_limit"],
            "battery_max_discharge_power": 5000,
        })
        assert _written(hass) == {"number.b2_limit": 3.0}


class TestAdapterCeiling:
    @pytest.mark.asyncio
    async def test_normal_lifts_the_small_packs_limit_again(self):
        hass, table = _hass({"number.b2_limit": (3000.0, 3000)})
        ad = GenericBatteryAdapter(hass, {
            "battery_discharge_control_entity": "number.b2_limit",
            "battery_max_discharge_power": 5000,
        })
        await ad.command_limit_discharge(1500.0)
        assert float(table["number.b2_limit"].state) == 1500.0
        await ad.command_normal()
        assert float(table["number.b2_limit"].state) == 3000.0

    def test_the_ceiling_is_the_smaller_of_setting_and_control(self):
        hass, _ = _hass({"number.b2_limit": (3000.0, 3000)})
        ad = GenericBatteryAdapter(hass, {
            "battery_discharge_control_entity": "number.b2_limit",
            "battery_max_discharge_power": 5000,
        })
        assert ad._max_discharge_w == 3000.0
        assert ad.max_discharge_power_w == 3000.0
        ad._max_discharge_w = 2000.0
        assert ad._max_discharge_w == 2000.0

    def test_no_control_keeps_the_setting(self):
        hass, _ = _hass({})
        ad = GenericBatteryAdapter(hass, {"battery_max_discharge_power": 5000})
        assert ad._max_discharge_w == 5000.0

    def test_a_control_without_a_max_keeps_the_setting(self):
        hass, table = _hass({"number.b1_limit": (500.0, 10000)})
        del table["number.b1_limit"].attributes["max"]
        ad = GenericBatteryAdapter(hass, {
            "battery_discharge_control_entity": "number.b1_limit",
            "battery_max_discharge_power": 5000,
        })
        assert ad._max_discharge_w == 5000.0
        assert entity_max_watts(hass, "number.b1_limit") is None

    def test_a_control_that_cannot_be_read_keeps_the_setting(self):
        hass, table = _hass({"number.b1_limit": ("unavailable", 3000)})
        ad = GenericBatteryAdapter(hass, {
            "battery_discharge_control_entity": "number.b1_limit",
            "battery_max_discharge_power": 5000,
        })
        assert ad._max_discharge_w == 5000.0
