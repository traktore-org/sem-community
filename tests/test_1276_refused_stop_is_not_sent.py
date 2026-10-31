"""#1276 — a Huawei battery whose sale power is a number: a refused 0 W stop
counted as sent. The record went to 0 W, the sale was marked stopped, and the
two retries skipped the write because the record already said 0 W. The
battery kept selling while SEM showed it stopped."""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator.battery_adapters.huawei import (
    HuaweiBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
)

SALE = "number.inverter_sale_power"
LIMIT = "number.battery_1_max_discharge"
MAX_W = 5000.0


class _Hass:
    """Numbers that take what is written; zero writes can be refused."""

    def __init__(self):
        self.calls: list = []
        self.refuse_zero = False
        self._states = {
            e: SimpleNamespace(state=str(v), attributes={
                "unit_of_measurement": "W", "min": -MAX_W, "max": MAX_W})
            for e, v in ((SALE, 0.0), (LIMIT, MAX_W))}
        self.states = SimpleNamespace(get=self._states.get,
                                      async_all=lambda *a, **k: [])
        self.services = SimpleNamespace(async_call=self._call)
        self.data = {}

    async def _call(self, domain, service, data=None, **kw):
        data = dict(data or {})
        self.calls.append((domain, service, data))
        if (service == "set_value" and data.get("entity_id") == SALE
                and self.refuse_zero and float(data["value"]) == 0.0):
            raise RuntimeError("register refused")
        if service == "set_value" and data["entity_id"] in self._states:
            old = self._states[data["entity_id"]]
            self._states[data["entity_id"]] = SimpleNamespace(
                state=str(float(data["value"])), attributes=old.attributes)

    def sale_writes(self) -> list:
        return [c[2]["value"] for c in self.calls
                if c[1] == "set_value" and c[2].get("entity_id") == SALE]


def _huawei(hass):
    a = HuaweiBatteryAdapter(hass, {
        "battery_discharge_control_entity": LIMIT,
        "battery_force_discharge_control_entity": SALE,
        "battery_max_discharge_power": MAX_W})
    a._inverter_device_id = ""
    a._startup_orphan_checked = True
    return a


class TestARefusedStopIsNotSent:
    async def test_the_sale_stays_marked_until_the_stop_lands(self):
        hass = _Hass()
        a = _huawei(hass)
        await a.command_force_discharge(3000.0, 10.0)
        assert a._forcible_discharging is True
        hass.refuse_zero = True
        await a.command_stop_force_discharge()
        assert a._forcible_discharging is True, "the stop did not land"
        assert a._last_force_discharge_w == 3000.0
        assert a.last_intent is not BatteryIntent.STOP_FORCE_DISCHARGE

    async def test_the_next_cycle_writes_the_stop_again(self):
        hass = _Hass()
        a = _huawei(hass)
        await a.command_force_discharge(3000.0, 10.0)
        hass.refuse_zero = True
        await a.command_stop_force_discharge()
        hass.refuse_zero = False
        before = len(hass.sale_writes())
        await a.command_stop_force_discharge()
        assert hass.sale_writes()[before:] == [0.0]
        assert hass._states[SALE].state == "0.0"
        assert a._forcible_discharging is False
        assert a.last_intent is BatteryIntent.STOP_FORCE_DISCHARGE

    async def test_a_refused_stop_through_normal_is_retried_too(self):
        hass = _Hass()
        a = _huawei(hass)
        await a.command_force_discharge(3000.0, 10.0)
        hass.refuse_zero = True
        await a.command_normal()
        assert a._forcible_discharging is True
        hass.refuse_zero = False
        await a.command_normal()
        assert hass._states[SALE].state == "0.0"
        assert a._forcible_discharging is False

    async def test_a_landed_stop_is_unchanged(self):
        hass = _Hass()
        a = _huawei(hass)
        await a.command_force_discharge(3000.0, 10.0)
        await a.command_stop_force_discharge()
        assert a._forcible_discharging is False
        assert a._last_force_discharge_w == 0.0
        assert a._stop_retries == 2
        assert hass.sale_writes() == [3000.0, 0.0]
