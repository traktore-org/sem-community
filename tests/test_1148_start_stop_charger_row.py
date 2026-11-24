"""#1148 — a start/stop-only charger logged an ERROR at every start.

Some chargers have no current control: SEM only starts and stops them, by
switch, button, service or charge mode. The builder's gate lets them run
(``charger_is_complete``, #1095), but ``register_ev_charger`` refused them::

    ERROR EV charger registration requires either current_control_entity
    or charger_service

…at every start, and returned before writing the row. A row saved under
the same id before kept its OLD control — e.g. the Zaptec site limit
(#1144). Nothing wrote to it (an ``ev_charger`` row is never shed here,
#461-peak), but the row still named it.

The rule now: such a charger gets its row with ``control_type``
``"start_stop"`` and no current control, the row is replaced whole (so a
stale control goes), and nothing in load management writes a current for
it — not the shed, not the restore, not the legacy fallbacks behind the
#461-peak guard.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.features.load_management import (
    LoadManagementCoordinator,
)

SITE_LIMIT = "number.zaptec_site_available_current"
GO_POWER = "sensor.go_charge_power"
GO_SWITCH = "switch.go_charging"
GO_BUTTON = "button.go_resume_charging"
ROW = "load_device_ev_charger"
NO_CURRENT = "requires either current_control_entity or charger_service"


def _lm(devices=None):
    lm = LoadManagementCoordinator.__new__(LoadManagementCoordinator)
    lm._devices = dict(devices or {})
    lm.hass = MagicMock()
    lm.hass.states.get = MagicMock(
        return_value=SimpleNamespace(state="0", attributes={}))
    lm.hass.services.async_call = AsyncMock()
    lm._save_device_configuration = AsyncMock()
    lm._trigger_callbacks = MagicMock()
    return lm


def _stale_site_limit_row():
    """The row an older setup saved: the Zaptec site limit as control."""
    return {ROW: {
        "switch_entity": SITE_LIMIT,
        "charger_service": "number.set_value",
        "power_entity": GO_POWER,
        "device_type": "ev_charger",
        "control_type": "current",
        "control": {"type": "current", "entity": SITE_LIMIT},
        "charger_id": "ev_charger",
        "priority": 3,
    }}


def _errors(caplog):
    return [r for r in caplog.records if r.levelno >= logging.ERROR]


# ── registration ──

@pytest.mark.asyncio
@pytest.mark.parametrize("how", [
    {"start_stop_entity": GO_SWITCH},
    {"start_stop_entity": GO_BUTTON},
    {"start_stop_service": "easee.action_command"},
    {"charge_mode_entity": "select.go_charge_mode"},
])
async def test_a_start_stop_only_charger_registers_without_an_error(
        caplog, how):
    lm = _lm()
    with caplog.at_level(logging.DEBUG):
        ok = await lm.register_ev_charger(
            current_control_entity=None, charger_service=None,
            power_entity=GO_POWER, charger_name="Go", **how)
    assert ok is True
    assert not _errors(caplog)
    assert NO_CURRENT not in caplog.text
    row = lm._devices[ROW]
    assert row["device_type"] == "ev_charger"
    assert row["control_type"] == "start_stop"
    assert row["switch_entity"] is None
    assert row["charger_service"] is None
    assert row["power_entity"] == GO_POWER
    assert row["friendly_name"] == "Go"
    lm._save_device_configuration.assert_awaited()


@pytest.mark.asyncio
async def test_the_stop_switch_is_still_on_the_row():
    """#748 reads the row: the charger's stop switch is named on it.
    (#1419: pattern discovery, which used to read it, is gone.)"""
    lm = _lm()
    await lm.register_ev_charger(
        power_entity=GO_POWER, start_stop_entity=GO_SWITCH)
    assert lm._devices[ROW]["start_stop_entity"] == GO_SWITCH


@pytest.mark.asyncio
async def test_a_charger_with_a_current_control_is_unchanged():
    """The twin, so the pins above are not passing on a row that never
    stores a control."""
    lm = _lm()
    await lm.register_ev_charger(
        current_control_entity="number.go_max_current",
        power_entity=GO_POWER, start_stop_entity=GO_SWITCH)
    row = lm._devices[ROW]
    assert row["control_type"] == "current"
    assert row["switch_entity"] == "number.go_max_current"


@pytest.mark.asyncio
async def test_no_way_to_act_at_all_is_still_refused_but_not_an_error(caplog):
    lm = _lm()
    with caplog.at_level(logging.DEBUG):
        ok = await lm.register_ev_charger(power_entity=GO_POWER)
    assert ok is False
    assert ROW not in lm._devices
    assert not _errors(caplog)


# ── a stale saved control is cleared ──

@pytest.mark.asyncio
async def test_a_stale_saved_site_limit_is_cleared(caplog):
    lm = _lm(_stale_site_limit_row())
    with caplog.at_level(logging.DEBUG):
        ok = await lm.register_ev_charger(
            power_entity=GO_POWER, start_stop_entity=GO_SWITCH)
    assert ok is True
    assert not _errors(caplog)
    row = lm._devices[ROW]
    assert SITE_LIMIT not in repr(row)
    assert row["switch_entity"] is None
    assert row["charger_service"] is None
    assert "control" not in row
    assert row["control_type"] == "start_stop"
    # …and the cleared row is what is saved
    lm._save_device_configuration.assert_awaited()


# ── nothing writes a current for it ──

def _shed_ready(lm):
    lm._observer_mode = False
    lm._devices_shed = []
    # (#896) the shed ledger and its in-flight set, built in __init__
    from custom_components.solar_energy_management.features.shed_ledger import ShedLedger
    lm._ledger = ShedLedger(MagicMock(async_save=AsyncMock()))
    lm._shedding_now = set()
    lm._recover_noted = set()
    lm._last_shedding_time = None
    lm._last_restore_time = None
    lm._can_shed_device = MagicMock(return_value=True)
    lm._device_discovery = MagicMock()
    lm._device_discovery.turn_off_device = AsyncMock(return_value=True)
    lm._device_discovery.turn_on_device = AsyncMock(return_value=True)
    return lm


@pytest.mark.asyncio
async def test_shedding_writes_nothing_for_it():
    lm = _shed_ready(_lm(_stale_site_limit_row()))
    await lm.register_ev_charger(
        power_entity=GO_POWER, start_stop_entity=GO_SWITCH)
    assert lm._devices[ROW]["switch_entity"] is None
    assert await lm._shed_device(ROW, "EMERGENCY") is False
    lm.hass.services.async_call.assert_not_awaited()
    lm._device_discovery.turn_off_device.assert_not_awaited()
    assert ROW not in [d for d, _ in lm._get_devices_for_shedding()]


@pytest.mark.asyncio
async def test_the_legacy_fallbacks_write_nothing_past_the_guard(monkeypatch):
    """Belt and braces: even with the #461-peak guard removed, the row's
    own fallbacks have no current to write and do not throw its switch."""
    lm = _shed_ready(_lm())
    await lm.register_ev_charger(
        power_entity=GO_POWER, start_stop_entity=GO_SWITCH)
    assert lm._devices[ROW]["control_type"] == "start_stop"
    monkeypatch.setattr(
        LoadManagementCoordinator, "_peak_managed_elsewhere",
        staticmethod(lambda info: False))
    assert await lm._shed_device(ROW, "EMERGENCY") is False
    lm.hass.services.async_call.assert_not_awaited()
    lm._device_discovery.turn_off_device.assert_not_awaited()

    lm._devices_shed.append(ROW)
    await lm._restore_device(ROW)
    lm.hass.services.async_call.assert_not_awaited()
    lm._device_discovery.turn_on_device.assert_not_awaited()


# ── the real setup: the builder hands the start/stop over ──

@pytest.mark.asyncio
async def test_setup_registers_a_start_stop_only_charger_without_an_error(
        sem_real_hass, caplog):
    from .test_1149_second_charger_own_wiring import GO, _entry, _set_up
    from .test_1144_saved_site_limit import _unload

    hass = sem_real_hass
    entry = _entry(hass, GO, load_management_enabled=True)
    with caplog.at_level(logging.DEBUG):
        await _set_up(hass, entry)
    try:
        assert NO_CURRENT not in caplog.text
        lm = entry.runtime_data._load_manager
        assert lm is not None
        # the first charger, fully wired, keeps its current control
        assert lm._devices["load_device_ev_charger"]["control_type"] == "current"
        row = lm._devices["load_device_ev_charger_1"]
        assert row["control_type"] == "start_stop"
        assert row["switch_entity"] is None
        assert row["charger_service"] is None
        assert row["start_stop_entity"] == GO["ev_start_stop_entity"]
    finally:
        await _unload(hass, entry)
