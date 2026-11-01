"""#1280 — a sale meeting a running switch / work-mode grid charge.

The rule: the sale goes first and the charge SEM started ends with it, in the
same command, before the sale is written. A pack must not be told to sell and
to charge from the grid at once. A stop that fails withholds the sale: the
next cycle asks again. A charge the user started is not SEM's to end.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    forced_ops,
)

from .test_1181_switch_charge_stops import (
    SALE,
    _KINDS,
    _charge_decision,
    _life,
    _restart,
)

pytestmark = pytest.mark.asyncio


def _sale():
    return BatteryDecision(
        battery_id="b1", intent=BatteryIntent.FORCE_DISCHARGE,
        discharge_power_w=3000.0, floor_soc=20.0)


def _make(kind, life):
    return (life.generic if kind == "generic" else life.goodwe)(
        battery_force_discharge_control_entity=SALE)


@pytest.mark.parametrize("kind", list(_KINDS))
async def test_a_sale_ends_the_charge_first(kind):
    _, actuator, on, off = _KINDS[kind]
    life = _life()
    adapter = _make(kind, life)
    await actuate_battery(_charge_decision(), adapter)
    assert life.hass.read(actuator) == on
    life.hass.calls.clear()
    await actuate_battery(_sale(), adapter)
    assert life.hass.read(actuator) == off
    assert life.hass.read(SALE) == "3000.0"
    order = [c[2].get("entity_id") for c in life.hass.calls]
    assert order.index(actuator) < order.index(SALE)
    assert forced_ops(adapter) == (False, True)


@pytest.mark.parametrize("kind", list(_KINDS))
async def test_a_charge_that_will_not_stop_withholds_the_sale(kind):
    _, actuator, on, _ = _KINDS[kind]
    life = _life()
    adapter = _make(kind, life)
    await actuate_battery(_charge_decision(), adapter)
    life.hass.raise_on = (("switch", "turn_off") if kind == "generic"
                          else ("select", "select_option"))
    await actuate_battery(_sale(), adapter)
    assert float(life.hass.read(SALE)) == 0.0
    assert "stop_forced_charge failed" in adapter.last_error
    assert forced_ops(adapter)[1] is not True
    life.hass.raise_on = None
    await actuate_battery(_sale(), adapter)         # the next cycle
    assert life.hass.read(SALE) == "3000.0"
    assert life.hass.read(actuator) != on


@pytest.mark.parametrize("kind", list(_KINDS))
async def test_a_charge_the_user_started_is_left_on(kind):
    _, actuator, on, _ = _KINDS[kind]
    life = _life()
    life.hass.set(actuator, on)
    adapter = _make(kind, _restart(life))
    await adapter.async_adopt_running_charge()
    await actuate_battery(_sale(), adapter)
    assert life.hass.read(actuator) == on
    assert life.hass.read(SALE) == "3000.0"


@pytest.mark.parametrize("kind", list(_KINDS))
async def test_a_sale_with_no_charge_sends_no_stop(kind):
    _, actuator, _, _ = _KINDS[kind]
    life = _life()
    adapter = _make(kind, life)
    await actuate_battery(_sale(), adapter)
    assert [c for c in life.hass.calls if c[2].get("entity_id") == actuator] == []
