"""Regression: accrued daily runtime survives an HA restart (#586).

Reporter RienduPre: the load "day target" (DAGDOEL) card shows a progress
bar ``X/Y u op zon vandaag`` — the accrued runtime toward the daily
minimum-runtime goal. After restarting Home Assistant mid-day it reset to
``0.0/5.5`` while the target (5.5 h) itself survived.

Root cause (ordering bug in ``__init__.py:async_setup_entry``):
``SEMCoordinator._restore_device_runtimes()`` was called during
``async_config_entry_first_refresh()`` — BEFORE the
``UnifiedDeviceRegistry`` is initialised. At that point the surplus
controller holds no devices, so ``get_device()`` returned ``None`` for
every persisted runtime and nothing was restored. The goal target
survived because goals are re-applied at device registration
(``_apply_goals``); the accrued runtime was silently dropped.

The fix moves the restore to run once, right after the registry has
(re-)registered the devices.

This test drives the real integration: register a service device with a
runtime goal, accrue some runtime, persist it, reload the config entry
(a restart in miniature), and assert the accrued runtime is back — not 0.
"""
from __future__ import annotations

import importlib.util

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pytest_homeassistant_custom_component") is None,
    reason="pytest-homeassistant-custom-component not installed; CI runs these",
)


from custom_components.solar_energy_management.const import DOMAIN

_DEVICE_ID = "zwembad_warmtepomp"
_ACCRUED_SEC = 9000.0  # 2.5 h already run toward a 5.5 h daily target


@pytest.mark.asyncio
async def test_accrued_runtime_survives_reload(
    sem_real_hass, sem_config_entry,
) -> None:
    hass = sem_real_hass
    sem_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(sem_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][sem_config_entry.entry_id]
    registry = coordinator._device_registry
    assert registry is not None, "device registry not initialised"

    # Register a surplus device (the pool heat pump) and give it a
    # 5.5 h/day minimum-runtime goal — persisted, so it survives the reload.
    await registry.async_register_service_device({
        "device_id": _DEVICE_ID,
        "entity_id": "switch.zwembad_warmtepomp",
        "name": "Zwembad Warmtepomp",
        "priority": 5,
        "rated_power": 4000,
        "control_mode": "surplus",
    })
    await registry.async_update_device_goal(
        _DEVICE_ID, "daily_min_runtime_min", 330  # 5.5 h
    )

    device = coordinator._surplus_controller.get_device(_DEVICE_ID)
    assert device is not None
    assert device.daily_min_runtime_sec == 330 * 60

    # Accrue runtime toward the target, as a running day would, and persist
    # it exactly the way the coordinator's step-13 persistence does. The
    # meter-day stamp must come from the coordinator's OWN day source
    # (#704: the TimeManager sunrise meter day) — a hand-stamped calendar
    # date diverges whenever the test clock is before sunrise (HA test envs
    # run US/Pacific), and the first post-reload tick would then read the
    # restored day as a rollover and reset the accrued value.
    device._daily_runtime_accumulated_sec = _ACCRUED_SEC
    device._daily_runtime_meter_day = (
        coordinator.time_manager.get_current_meter_day_sunrise_based()
    )
    coordinator._persist_device_runtimes()
    await coordinator._storage.async_save_daily()

    # Restart in miniature: reload the config entry. This tears the
    # coordinator + registry down and rebuilds them from persisted state —
    # the exact path an HA restart takes.
    assert await hass.config_entries.async_reload(sem_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][sem_config_entry.entry_id]
    device = coordinator._surplus_controller.get_device(_DEVICE_ID)
    assert device is not None, (
        "service device was not re-registered after reload"
    )
    # Target survived (this always worked — it's applied at registration).
    assert device.daily_min_runtime_sec == 330 * 60
    # Accrued runtime must survive too. Pre-fix this was 0.0 because the
    # restore ran before any device existed. A single post-reload cycle may
    # add a little if the device reads as on, so allow a small tolerance —
    # the point is it is NOT reset to 0.
    assert device._daily_runtime_accumulated_sec > 0.0, (
        "accrued daily runtime reset to 0 after restart (#586)"
    )
    assert device._daily_runtime_accumulated_sec == pytest.approx(
        _ACCRUED_SEC, abs=120.0
    )


# ---------------------------------------------------------------------------
# Unit: the 35 s re-discovery rebuild must not drop accrued runtime either.
#
# _sync_to_surplus_controller recreates every auto-discovered device as a
# fresh object (_daily_runtime_accumulated_sec = 0.0). async_refresh_devices
# snapshots the accrued runtime before that rebuild and re-applies it after,
# mirroring the #576 rated-power capture/restore. These pin that logic in
# isolation (no full-hass reload needed).
# ---------------------------------------------------------------------------

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)


def _rt_dev(accrued=0.0, meter_day=None):
    return SimpleNamespace(
        _daily_runtime_accumulated_sec=accrued,
        _daily_runtime_meter_day=meter_day,
    )


def _rt_reg(devices):
    reg = UnifiedDeviceRegistry(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    ctrl = MagicMock()
    ctrl._devices = devices
    ctrl.get_device = lambda did: devices.get(did)
    reg._surplus_controller = ctrl
    return reg


@pytest.mark.unit
class TestAccruedRuntimeRebuild:
    def test_capture_records_accrued(self):
        day = date(2026, 7, 13)
        reg = _rt_reg({"pump": _rt_dev(accrued=9000.0, meter_day=day)})
        snap = reg._capture_accrued_runtimes()
        assert snap == {"pump": (9000.0, day)}

    def test_capture_ignores_fresh_and_dayless(self):
        day = date(2026, 7, 13)
        reg = _rt_reg({
            "fresh": _rt_dev(accrued=0.0, meter_day=day),      # nothing accrued
            "dayless": _rt_dev(accrued=1234.0, meter_day=None),  # never ran a cycle
        })
        assert reg._capture_accrued_runtimes() == {}

    def test_restore_fills_rebuilt_empty_device(self):
        day = date(2026, 7, 13)
        # Snapshot taken from the OLD (pre-rebuild) device.
        old = {"pump": _rt_dev(accrued=9000.0, meter_day=day)}
        reg = _rt_reg(old)
        snap = reg._capture_accrued_runtimes()

        # Rebuild replaces the object with a fresh 0.0 one (the bug's trigger).
        rebuilt = _rt_dev(accrued=0.0, meter_day=None)
        reg._surplus_controller._devices = {"pump": rebuilt}
        reg._surplus_controller.get_device = lambda did: {"pump": rebuilt}.get(did)

        reg._restore_accrued_runtimes(snap)
        assert rebuilt._daily_runtime_accumulated_sec == 9000.0
        assert rebuilt._daily_runtime_meter_day == day

    def test_restore_never_clobbers_live_value(self):
        day = date(2026, 7, 13)
        # A service device keeps its live object across the sync — it already
        # holds a (possibly newer) value and must be left untouched.
        live = _rt_dev(accrued=12000.0, meter_day=day)
        reg = _rt_reg({"pump": live})
        reg._restore_accrued_runtimes({"pump": (9000.0, day)})
        assert live._daily_runtime_accumulated_sec == 12000.0
