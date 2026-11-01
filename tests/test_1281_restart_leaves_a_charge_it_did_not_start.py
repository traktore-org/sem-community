"""#1281 — a restart must not turn off a charge switch SEM never turned on.

After a restart nothing in memory says who started a grid charge, so the
first stop (the night scheduler's verdict) went to the generic switch or the
GoodWe work mode even when the user had turned it on. The record of the
charges SEM started (#1181) answers that: a battery it does not name has no
charge of SEM's to stop.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.battery_adapters.charge_record import (
    ForcedChargeRecord,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    forced_ops,
)

from .test_1181_switch_charge_stops import (
    _KINDS,
    _Life,
    _Hass,
    _Store,
    _charge_decision,
    _cycle,
    _life,
    _restart,
)
from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)

pytestmark = pytest.mark.asyncio


def _no_block():
    sched = SimpleNamespace(state="scheduled", charge_power_w=3000.0,
                            price_forced=False, target_soc=80.0,
                            duration_min=60, from_arbitrage=False)
    gate = SimpleNamespace(covered=True, in_block=False, next_block_start=None,
                           reason="", block_power_w=0.0)
    return sched, gate


@pytest.mark.parametrize("kind", list(_KINDS))
async def test_a_charge_the_user_started_survives_the_restart(kind):
    make, actuator, on, off = _KINDS[kind]
    life = _life()
    life.hass.set(actuator, on)                      # the user's own charge
    adapter = make(_restart(life))
    await adapter.async_adopt_running_charge()
    sched, gate = _no_block()
    decision = await _cycle(adapter, sched=sched, gate=gate)
    assert life.hass.read(actuator) == on
    assert life.hass.calls == []
    assert decision.intent is not BatteryIntent.STOP_FORCE_CHARGE


@pytest.mark.parametrize("kind", list(_KINDS))
async def test_a_charge_sem_started_is_still_stopped(kind):
    make, actuator, on, off = _KINDS[kind]
    first = _life()
    await actuate_battery(_charge_decision(), make(first))
    adapter = make(_restart(first))
    await adapter.async_adopt_running_charge()
    sched, gate = _no_block()
    decision = await _cycle(adapter, sched=sched, gate=gate)
    assert decision.intent is BatteryIntent.STOP_FORCE_CHARGE
    assert first.hass.read(actuator) == off


@pytest.mark.parametrize("kind", list(_KINDS))
async def test_a_record_that_cannot_be_read_keeps_the_old_stop(kind):
    """SEM cannot tell its charge from the user's: the stop stays as it was."""
    make, actuator, on, off = _KINDS[kind]
    hass = _Hass()
    hass.set(actuator, on)

    class _Broken(_Store):
        async def async_load(self):
            raise OSError("disk")

    life = _Life(hass, _Broken(), _Store())
    adapter = make(life)
    await adapter.async_adopt_running_charge()
    assert forced_ops(adapter) == (None, None)


@pytest.mark.parametrize("kind", list(_KINDS))
async def test_no_store_means_no_claim(kind):
    """A record kept only in memory forgets across a restart: it proves
    nothing about who started a charge."""
    make, actuator, on, off = _KINDS[kind]
    hass = _Hass()
    life = _Life(hass, None, _Store())
    life.record = ForcedChargeRecord()
    adapter = make(life)
    await adapter.async_adopt_running_charge()
    assert forced_ops(adapter) == (None, None)


@pytest.mark.parametrize("kind", list(_KINDS))
async def test_a_charge_sem_starts_later_is_still_its_own(kind):
    make, actuator, on, off = _KINDS[kind]
    life = _life()
    adapter = make(life)
    await adapter.async_adopt_running_charge()
    assert forced_ops(adapter)[0] is False
    await actuate_battery(_charge_decision(), adapter)
    assert life.hass.read(actuator) == on
    assert forced_ops(adapter)[0] is True
