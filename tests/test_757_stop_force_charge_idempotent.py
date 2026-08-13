"""#757 — STOP_FORCE_CHARGE is a transition, not a per-cycle command.

The one-gate scheduler repeats a STOP_FORCE_CHARGE verdict on EVERY cycle
between planned blocks (SCHEDULED-outside-window, idle, target_reached, …).
The dispatch is unconditional, so before this fix each brand adapter re-issued
its stop to the inverter every cycle — ~1800 redundant writes a night on the
single serial Modbus link, the exact collision #538 fixed for the discharge
limit (`huawei_solar` read-coordinator transaction-ID mismatches + timeouts).

Two guards close it, mirroring the `command_off` pattern (base.py:187) and the
#538 `_apply_discharge_limit` guard:

  * source layer — `ChargeController.stop_forced_charge` returns early when
    ``_active`` is False (nothing to cancel → no service call);
  * intent layer — each `command_stop_force_charge` no-ops once
    ``_last_intent`` is already STOP_FORCE_CHARGE, and records STOP only when
    the stop actually landed (honest retry, #589 class 4).

These tests pin REAL behaviour: they count the actual HA service calls a
second stop makes (must be zero) and prove a failed stop retries.
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
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.force_charge import (
    ChargeCommandStatus,
    ChargeStatus,
    HuaweiChargeAdapter,
    GoodWeChargeAdapter,
    GenericChargeAdapter,
)


def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.get = Mock(return_value=None)
    hass.states.async_all = Mock(return_value=[])
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock(return_value=None)
    return hass


def _write_calls(hass: MagicMock) -> int:
    """Count HA service calls that actually touch the inverter — the stop
    services + any set_value/select_option/turn_off write. Read-only calls
    (none here) would be excluded."""
    return hass.services.async_call.await_count


# ─────────────────────────────────────────────────────────────────────────────
# Source layer: ChargeController.stop_forced_charge is idempotent on _active
# ─────────────────────────────────────────────────────────────────────────────

def _huawei_charge_ctl():
    hass = _make_hass()
    return HuaweiChargeAdapter(hass, {"inverter_device_id": "dev-1"}), hass


def _goodwe_charge_ctl():
    hass = _make_hass()
    return GoodWeChargeAdapter(
        hass, {"inverter_work_mode_entity": "select.wm",
                "inverter_normal_work_mode": "General"},
    ), hass


def _generic_charge_ctl():
    hass = _make_hass()
    return GenericChargeAdapter(
        hass, {"battery_force_charge_switch": "switch.fc"},
    ), hass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "factory",
    [_huawei_charge_ctl, _goodwe_charge_ctl, _generic_charge_ctl],
    ids=["huawei", "goodwe", "generic"],
)
async def test_charge_controller_stop_is_transition_only(factory) -> None:
    """An active stop issues ONE write; the next stop (already inactive)
    issues NONE — the source-layer flood guard."""
    ctl, hass = factory()
    ctl._active = True

    status = await ctl.stop_forced_charge()
    assert status.status is ChargeCommandStatus.IDLE
    assert ctl.is_active is False
    assert _write_calls(hass) == 1  # the real stop landed

    hass.services.async_call.reset_mock()
    status2 = await ctl.stop_forced_charge()
    assert status2.status is ChargeCommandStatus.IDLE
    # Nothing active → NO second Modbus write (the #757 flood is gone).
    hass.services.async_call.assert_not_awaited()


# ─────────────────────────────────────────────────────────────────────────────
# Intent layer: command_stop_force_charge no-ops once already stopped
# ─────────────────────────────────────────────────────────────────────────────

def _make_huawei():
    hass = _make_hass()
    with patch(
        "custom_components.solar_energy_management.coordinator"
        ".battery_adapters.huawei.HuaweiBatteryAdapter._autodetect_battery_device",
        return_value=None,
    ):
        adapter = HuaweiBatteryAdapter(hass, {
            "inverter_device_id": "dev-abc",
            "battery_max_charge_power": 5000,
            "battery_max_discharge_power": 5000,
        })
    adapter._startup_orphan_checked = True  # skip the one-shot boot clear
    return adapter, hass


def _make_generic():
    hass = _make_hass()
    hass.states.get = Mock(return_value=None)
    adapter = GenericBatteryAdapter(hass, {
        "battery_max_charge_power": 5000,
        "battery_max_discharge_power": 5000,
        "battery_force_charge_switch": "switch.force_charge",
        "battery_target_soc_entity": "number.target_soc",
    })
    return adapter, hass


def _make_goodwe():
    hass = _make_hass()
    adapter = GoodWeBatteryAdapter(hass, {
        "battery_max_charge_power": 5000,
        "battery_max_discharge_power": 5000,
        "inverter_work_mode_entity": "select.goodwe_work_mode",
        "inverter_normal_work_mode": "General",
    })
    return adapter, hass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "factory",
    [_make_huawei, _make_generic, _make_goodwe],
    ids=["huawei", "generic", "goodwe"],
)
async def test_repeated_stop_writes_once(factory) -> None:
    """Two consecutive STOP_FORCE_CHARGE verdicts issue at most ONE stop
    to the inverter — the reported #757 flood."""
    adapter, hass = factory()
    # Simulate an active forced charge that the scheduler now stops.
    adapter._last_intent = BatteryIntent.FORCE_CHARGE
    adapter._charge_adapter._active = True

    await adapter.command_stop_force_charge()
    assert adapter.last_intent is BatteryIntent.STOP_FORCE_CHARGE
    after_first = _write_calls(hass)
    assert after_first >= 1  # the transition actually stopped the inverter

    await adapter.command_stop_force_charge()  # already stopped
    # No new writes — the second verdict is a pure no-op.
    assert _write_calls(hass) == after_first


# ─────────────────────────────────────────────────────────────────────────────
# Honest retry: a FAILED stop must not record STOP, and must retry next cycle
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "factory",
    [_make_huawei, _make_generic, _make_goodwe],
    ids=["huawei", "generic", "goodwe"],
)
async def test_failed_stop_not_recorded_then_retries(factory) -> None:
    """A stop that FAILS leaves _last_intent != STOP (so the guard can't
    suppress it) and re-issues on the next cycle until it lands."""
    adapter, _ = factory()
    adapter._last_intent = BatteryIntent.FORCE_CHARGE
    adapter._forcible_charging = True  # huawei: a charge SEM must stop

    adapter._charge_adapter.stop_forced_charge = AsyncMock(
        return_value=ChargeStatus(
            status=ChargeCommandStatus.FAILED, message="modbus timeout",
        ),
    )
    await adapter.command_stop_force_charge()
    assert adapter.last_intent is not BatteryIntent.STOP_FORCE_CHARGE
    assert adapter.last_error is not None

    # Next cycle: service recovers → the guard did NOT block the retry.
    adapter._charge_adapter.stop_forced_charge = AsyncMock(
        return_value=ChargeStatus(status=ChargeCommandStatus.IDLE),
    )
    await adapter.command_stop_force_charge()
    adapter._charge_adapter.stop_forced_charge.assert_awaited_once()
    assert adapter.last_intent is BatteryIntent.STOP_FORCE_CHARGE
    assert adapter.last_error is None
