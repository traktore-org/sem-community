"""#757 — a stop that is already stopped is not a command.

The one-gate build (#638 C4) changed the shape of the battery decision:
``decide_battery`` now returns ``STOP_FORCE_CHARGE`` on EVERY cycle where
the scheduler is SCHEDULED and the plan block is not open — both the
"covered but outside the block" case and the "uncovered" case. On develop
that branch had no return at all and fell through to LIMIT_DISCHARGE, so
the stop was issued once, at the transition, and never again.

``actuate_battery`` dispatches unconditionally, so between a 21:00
scheduler verdict and a 02:00 plan block that is ~1800 stop commands. On
Huawei each one used to be a real ``huawei_solar.stop_forcible_charge``
on the single serial Modbus link — precisely the collision #538 fixed one
layer down for the discharge limit.

These tests pin the frequency, not the behaviour-in-the-abstract: the
hardware must see the stop ONCE per transition, and a stop that FAILED
must still be retried (silence must never be bought with a lie).
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from custom_components.solar_energy_management.coordinator.battery_adapters.huawei import (
    HuaweiBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.goodwe import (
    GoodWeBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.deye import (
    DeyeBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.force_charge import (
    ChargeCommandStatus,
    ChargeStatus,
)


def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.get = Mock(return_value=None)
    hass.states.async_all = Mock(return_value=[])
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock(return_value=None)
    return hass


def _entity_state(current: float, lo: float = 0.0, hi: float = 10000.0) -> Mock:
    st = Mock()
    st.state = str(current)
    st.attributes = {"min": lo, "max": hi}
    return st


def _ok() -> ChargeStatus:
    return ChargeStatus(status=ChargeCommandStatus.IDLE, message="stopped")


def _failed() -> ChargeStatus:
    return ChargeStatus(status=ChargeCommandStatus.FAILED, message="boom")


def _make_huawei() -> HuaweiBatteryAdapter:
    hass = _make_hass()
    config = {
        "inverter_device_id": "dev-abc",
        "battery_max_charge_power": 5000,
        "battery_max_discharge_power": 5000,
    }
    with patch(
        "custom_components.solar_energy_management.coordinator"
        ".battery_adapters.huawei.HuaweiBatteryAdapter._autodetect_battery_device",
        return_value=None,
    ):
        adapter = HuaweiBatteryAdapter(hass, config)
    # Boot orphan check already consumed — we are testing steady state.
    adapter._startup_orphan_checked = True
    return adapter


class TestHuaweiStopFrequency:
    """The blocker: the write storm between two planned blocks."""

    @pytest.mark.asyncio
    async def test_the_night_between_blocks_issues_exactly_one_stop(self) -> None:
        """300 cycles outside the block → ONE stop on the wire.

        This is the shape of a real night: the scheduler goes SCHEDULED in
        the evening, the plan block opens hours later, and every cycle in
        between asks for a stop.
        """
        adapter = _make_huawei()
        adapter._charge_adapter.stop_forced_charge = AsyncMock(return_value=_ok())

        for _ in range(300):
            await adapter.command_stop_force_charge()

        assert adapter._charge_adapter.stop_forced_charge.await_count == 1
        assert adapter.last_intent is BatteryIntent.STOP_FORCE_CHARGE

    @pytest.mark.asyncio
    async def test_a_real_charge_is_still_stopped(self) -> None:
        """Idempotency must not mean deafness — after a charge, stop lands."""
        adapter = _make_huawei()
        adapter._charge_adapter.start_forced_charge = AsyncMock(
            return_value=ChargeStatus(
                status=ChargeCommandStatus.CHARGING, message="on"),
        )
        adapter._charge_adapter.stop_forced_charge = AsyncMock(return_value=_ok())

        await adapter.command_force_charge(80.0, 3000.0, 120)
        assert adapter._forcible_charging is True

        await adapter.command_stop_force_charge()
        assert adapter._charge_adapter.stop_forced_charge.await_count == 1
        assert adapter._forcible_charging is False

        # A second block opens and closes — the hardware hears both edges.
        await adapter.command_force_charge(80.0, 3000.0, 120)
        await adapter.command_stop_force_charge()
        assert adapter._charge_adapter.stop_forced_charge.await_count == 2

    @pytest.mark.asyncio
    async def test_a_failed_stop_is_retried_not_swallowed(self) -> None:
        """A dropped Modbus stop must not be recorded as success.

        The whole point of the guard is that ``_last_intent`` means "the
        hardware is stopped". Recording it on a failed write would make
        the guard lie and leave the battery charging all night.
        """
        adapter = _make_huawei()
        adapter._charge_adapter.stop_forced_charge = AsyncMock(
            return_value=_failed())

        await adapter.command_stop_force_charge()
        assert adapter.last_intent is not BatteryIntent.STOP_FORCE_CHARGE
        assert adapter.last_error is not None

        await adapter.command_stop_force_charge()
        assert adapter._charge_adapter.stop_forced_charge.await_count == 2

        # It recovers the moment the link does.
        adapter._charge_adapter.stop_forced_charge = AsyncMock(return_value=_ok())
        await adapter.command_stop_force_charge()
        assert adapter.last_intent is BatteryIntent.STOP_FORCE_CHARGE
        assert adapter.last_error is None


class TestEveryBrandIsIdempotent:
    """The guard belongs to the class of adapter, not to one brand."""

    @pytest.mark.asyncio
    async def test_generic_repeats_are_silent(self) -> None:
        hass = _make_hass()
        hass.states.get = Mock(return_value=_entity_state(0.0))
        adapter = GenericBatteryAdapter(hass, {
            "battery_max_charge_power": 5000,
            "battery_max_discharge_power": 5000,
            "battery_force_charge_switch": "switch.force_charge",
            "battery_target_soc_entity": "number.target_soc",
        })
        adapter._charge_adapter.stop_forced_charge = AsyncMock(return_value=_ok())
        adapter._set_strategy = AsyncMock(return_value=None)

        for _ in range(50):
            await adapter.command_stop_force_charge()

        assert adapter._charge_adapter.stop_forced_charge.await_count == 1
        assert adapter._set_strategy.await_count == 1
        assert adapter.last_intent is BatteryIntent.STOP_FORCE_CHARGE

    @pytest.mark.asyncio
    async def test_goodwe_repeats_are_silent(self) -> None:
        hass = _make_hass()
        hass.states.get = Mock(return_value=_entity_state(0.0))
        adapter = GoodWeBatteryAdapter(hass, {
            "battery_max_charge_power": 5000,
            "battery_max_discharge_power": 5000,
        })
        adapter._charge_adapter.stop_forced_charge = AsyncMock(return_value=_ok())

        for _ in range(50):
            await adapter.command_stop_force_charge()

        assert adapter._charge_adapter.stop_forced_charge.await_count == 1
        assert adapter.last_intent is BatteryIntent.STOP_FORCE_CHARGE

    @pytest.mark.asyncio
    async def test_deye_repeats_do_not_reread_the_store(self) -> None:
        """Deye's stop is a Store read plus a restore write. Once the
        restore has landed there is nothing left to restore, so every
        further cycle is a disk read and a hardware write for nothing."""
        hass = _make_hass()
        adapter = DeyeBatteryAdapter(hass, {
            "battery_max_charge_power": 5000,
            "battery_max_discharge_power": 5000,
        })
        # No pending snapshot: the adapter is already back to normal.
        adapter._load_snapshot = AsyncMock(return_value=None)
        adapter._snapshot_load_failed = False
        adapter._unsafe_latched = False

        for _ in range(50):
            await adapter.command_stop_force_charge()

        assert adapter._load_snapshot.await_count == 1
        assert adapter.last_intent is BatteryIntent.STOP_FORCE_CHARGE
