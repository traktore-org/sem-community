"""#1275 — two Huawei packs on one device ended each other's sale.

Both packs sold through ``forcible_discharge_soc`` to ONE device. Pack 1
reached its floor and sent ``stop_forcible_charge`` (plus two retries): the
device stopped selling for both. Pack 2's own flag still said the sale ran,
so it never sent the sale again, and SEM showed a sale while nothing was
sold. The device's record is now shared: a stop to the device ends every
sale on it, and a pack whose sale was ended sends it again. The stop
retries leave a sibling's running sale alone.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.solar_energy_management.coordinator.battery_adapters.huawei import (
    HuaweiBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)

DEV = "luna_device"
SELL, STOP = "forcible_discharge_soc", "stop_forcible_charge"


def _hass():
    h = MagicMock()
    h.services.async_call = AsyncMock()
    h.data = {"huawei_solar": {}}
    h.config_entries.async_entries = MagicMock(return_value=[])
    h.states.async_all = MagicMock(return_value=[])
    return h


def _pack(h, shared, n):
    a = HuaweiBatteryAdapter(h, {
        "inverter_device_id": DEV,
        "battery_discharge_control_entity": f"number.lim{n}",
        "battery_max_discharge_power": 5000,
        "device_sales": shared,
    })
    a._startup_orphan_checked = True
    return a


def _services(h):
    return [c.args[1] for c in h.services.async_call.await_args_list]


class TestAStopToTheDeviceEndsEverySale:
    async def test_the_sibling_sends_its_sale_again(self):
        h, shared = _hass(), {}
        p1, p2 = _pack(h, shared, 1), _pack(h, shared, 2)
        await p1.command_force_discharge(3000.0, 10.0)
        await p2.command_force_discharge(3000.0, 10.0)
        await p1.command_stop_force_discharge()
        h.services.async_call.reset_mock()
        await p2.command_force_discharge(3000.0, 10.0)
        assert _services(h) == [SELL]

    async def test_a_sale_nobody_ended_is_sent_once(self):
        h, shared = _hass(), {}
        p1, p2 = _pack(h, shared, 1), _pack(h, shared, 2)
        await p1.command_force_discharge(3000.0, 10.0)
        await p2.command_force_discharge(3000.0, 10.0)
        h.services.async_call.reset_mock()
        for _ in range(3):
            await p1.command_force_discharge(3000.0, 10.0)
            await p2.command_force_discharge(3000.0, 10.0)
        assert _services(h) == []

    async def test_a_resent_sale_stands_again(self):
        h, shared = _hass(), {}
        p1, p2 = _pack(h, shared, 1), _pack(h, shared, 2)
        await p1.command_force_discharge(3000.0, 10.0)
        await p2.command_force_discharge(3000.0, 10.0)
        await p1.command_stop_force_discharge()
        await p2.command_force_discharge(3000.0, 10.0)
        h.services.async_call.reset_mock()
        await p2.command_force_discharge(3000.0, 10.0)
        assert _services(h) == []

    async def test_one_pack_alone_is_as_before(self):
        h = _hass()
        p = _pack(h, {}, 1)
        await p.command_force_discharge(3000.0, 10.0)
        await p.command_force_discharge(3000.0, 10.0)
        assert _services(h) == [SELL]


class TestTheStopRetriesLeaveASiblingsSale:
    async def test_no_retry_stop_while_a_sibling_sells(self):
        h, shared = _hass(), {}
        p1, p2 = _pack(h, shared, 1), _pack(h, shared, 2)
        await p1.command_force_discharge(3000.0, 10.0)
        await p2.command_force_discharge(3000.0, 10.0)
        await p1.command_stop_force_discharge()
        await p2.command_force_discharge(3000.0, 10.0)   # sells again
        h.services.async_call.reset_mock()
        for _ in range(3):
            await p1.command_normal()
        assert STOP not in _services(h)

    async def test_the_retries_go_out_when_no_sibling_sells(self):
        h, shared = _hass(), {}
        p1, p2 = _pack(h, shared, 1), _pack(h, shared, 2)
        await p1.command_force_discharge(3000.0, 10.0)
        await p1.command_stop_force_discharge()
        h.services.async_call.reset_mock()
        await p1.command_normal()
        assert _services(h) == [STOP]
        assert p2._forcible_discharging is False


class TestTheCoordinatorSharesOneRecord:
    def test_every_battery_context_carries_the_same_record(self):
        stub = MagicMock()
        stub.hass = None
        stub.config = {}
        stub.config_entry = None
        stub.battery_control_slugs = ("b1", "b2")
        stub._energy_dashboard_config = SimpleNamespace()
        for name in ("_battery_adapter_context", "_per_battery_config",
                     "_battery_own_entities", "_charge_target_hold",
                     "_forced_charge_record"):
            setattr(stub, name, getattr(SEMCoordinator, name).__get__(stub))
        a = stub._battery_adapter_context("b1", 0, 2)["device_sales"]
        b = stub._battery_adapter_context("b2", 1, 2)["device_sales"]
        assert isinstance(a, dict) and a is b
