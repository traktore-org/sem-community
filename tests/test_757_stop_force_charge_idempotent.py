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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "factory",
    [_make_huawei, _make_generic, _make_goodwe],
    ids=["huawei", "generic", "goodwe"],
)
async def test_boot_orphan_stop_still_reaches_inverter(factory) -> None:
    """Regression guard: the idempotency guard must NOT gate the FIRST stop on
    the in-memory ``_active``/last_intent flag. After a restart a fresh adapter
    has last_intent=None and the delegate's ``_active``=False, while the
    inverter may still be force-charging (an orphan from the prior lifetime).
    The transition stop MUST reach the hardware — a naive ``if not _active``
    source guard would strand GoodWe/Generic charging from grid unsupervised.
    """
    adapter, hass = factory()
    # Fresh-boot state: nothing recorded, delegate believes it is idle.
    assert adapter.last_intent is None
    assert adapter._charge_adapter._active is False

    await adapter.command_stop_force_charge()

    # The stop actually reached the inverter (orphan cleared, not skipped).
    assert _write_calls(hass) >= 1
    assert adapter.last_intent is BatteryIntent.STOP_FORCE_CHARGE


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
