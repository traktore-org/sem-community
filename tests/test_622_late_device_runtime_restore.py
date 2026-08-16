"""Regression: accrued daily runtime survives restart for a LATE-arriving
auto-discovered load (#622).

Reporter alexmc1510: the pool-pump ("Depuradora Piscina") daily-target
progress bar — "X/Y h on solar today", the accrued runtime toward the
device's minimum-runtime goal — reset to 0 on every HA restart and the
load re-ran its whole daily target.

#586 fixed the runtime restore for devices that EXIST at setup: the
coordinator restores accrued runtime from storage once, right after the
registry has registered the devices. But an auto-discovered load whose
backing switch entity isn't ready during initial setup is not created
then — it appears only via the registry's 35 s delayed re-discovery,
AFTER that one-shot restore already ran and found no device. That later
rebuild restores accrued runtime only from an IN-MEMORY snapshot
(``_restore_accrued_runtimes``), which is empty for a device that was
never populated from storage — so the progress reset to 0.

Fix: the coordinator's ``_restore_device_runtimes`` is made idempotent
(only fills a device that came back empty, never clobbers a live value)
and the registry re-invokes it via ``_runtime_restore_hook`` after EVERY
``async_refresh_devices`` rebuild — so the late device is filled from
storage.

These pin both halves in isolation (no full-hass reload needed).
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import homeassistant.util.dt as dt_util

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)

_DEVICE_ID = "energy_dashboard_depuradora_piscina"
_ACCRUED_SEC = 9360.0  # 2.6 h already run toward a 4 h daily target


def _rt_dev(accrued=0.0, meter_day=None):
    return SimpleNamespace(
        _daily_runtime_accumulated_sec=accrued,
        _daily_runtime_meter_day=meter_day,
    )


def _fake_coord(devices):
    """A minimal stand-in exposing exactly what _restore_device_runtimes reads."""
    today = dt_util.now().date().isoformat()
    storage = MagicMock()
    storage.get_device_runtimes.return_value = {
        _DEVICE_ID: {"accumulated_sec": _ACCRUED_SEC, "meter_day": today},
    }
    surplus = MagicMock()
    surplus.get_device = lambda did: devices.get(did)
    return SimpleNamespace(_storage=storage, _surplus_controller=surplus)


@pytest.mark.unit
class TestRestoreIdempotent:
    """coordinator._restore_device_runtimes must be safe to call repeatedly."""

    def test_absent_device_then_late_fill(self):
        # Startup restore: the device does not exist yet (entity not ready) —
        # nothing to restore, no crash.
        devices: dict = {}
        coord = _fake_coord(devices)
        SEMCoordinator._restore_device_runtimes(coord)  # device absent

        # The 35 s re-discovery finally creates the device, fresh at 0.0.
        late = _rt_dev(accrued=0.0, meter_day=None)
        devices[_DEVICE_ID] = late
        SEMCoordinator._restore_device_runtimes(coord)  # re-invoked by the hook

        assert late._daily_runtime_accumulated_sec == pytest.approx(_ACCRUED_SEC)
        assert late._daily_runtime_meter_day == dt_util.now().date()

    def test_never_clobbers_live_value(self):
        # A device that already accrued this session must NOT be reset to the
        # (possibly staler) stored value when the restore re-runs.
        live = _rt_dev(accrued=12000.0, meter_day=dt_util.now().date())
        coord = _fake_coord({_DEVICE_ID: live})
        SEMCoordinator._restore_device_runtimes(coord)
        assert live._daily_runtime_accumulated_sec == 12000.0

    def test_stale_day_restore_self_corrects_on_rollover(self):
        # A restart spanning midnight fills yesterday's accrued onto a fresh
        # device (restore doesn't gate on the day). The next
        # update_daily_runtime(today) must detect the rollover and reset it —
        # so the stale value never survives past one cycle.
        from datetime import date, timedelta

        from custom_components.solar_energy_management.devices.base import (
            ControllableDevice,
            DeviceControlMode,
        )

        yesterday = (dt_util.now().date() - timedelta(days=1)).isoformat()
        storage = MagicMock()
        storage.get_device_runtimes.return_value = {
            _DEVICE_ID: {"accumulated_sec": _ACCRUED_SEC, "meter_day": yesterday},
        }
        # Duck-typed device carrying exactly the fields update_daily_runtime
        # touches on the rollover path (is_active False → no power access).
        dev = SimpleNamespace(
            name="Depuradora Piscina",
            _daily_runtime_accumulated_sec=0.0,
            _daily_runtime_meter_day=None,
            _daily_runtime_last_check=None,
            is_active=False,
            control_mode=DeviceControlMode.SURPLUS,
            observed_on=lambda: None,
            # (#768) the rollover now logs and clears the day's ENERGY beside
            # its runtime, so the stand-in carries those fields too.
            _daily_energy_kwh=0.0,
            _daily_energy_source="none",
            _daily_energy_blind_s=0.0,
            _energy_counter_last_kwh=None,
        )
        surplus = MagicMock()
        surplus.get_device = lambda did: {_DEVICE_ID: dev}.get(did)
        coord = SimpleNamespace(_storage=storage, _surplus_controller=surplus)

        SEMCoordinator._restore_device_runtimes(coord)
        # Stale yesterday value is loaded...
        assert dev._daily_runtime_accumulated_sec == pytest.approx(_ACCRUED_SEC)
        assert dev._daily_runtime_meter_day == date.fromisoformat(yesterday)

        # ...but the first cycle on the new day rebases it to 0.
        ControllableDevice.update_daily_runtime(dev, dt_util.now().date())
        assert dev._daily_runtime_accumulated_sec == 0.0


def _wire_reg():
    reg = UnifiedDeviceRegistry(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    # Neutralise everything async_refresh_devices does around the hook so the
    # test isolates the wiring, not discovery.
    reg._capture_calibrated_ratings = MagicMock(return_value=False)
    reg._capture_accrued_runtimes = MagicMock(return_value={})
    reg._sync_to_surplus_controller = MagicMock()
    reg._sync_to_load_manager = MagicMock()
    reg._restore_accrued_runtimes = MagicMock()
    reg._seed_and_apply_ratings = AsyncMock(return_value=False)
    return reg


@pytest.mark.asyncio
async def test_refresh_invokes_runtime_restore_hook_after_inmemory_restore():
    """async_refresh_devices must re-apply persisted runtime via the hook on
    every rebuild — and AFTER the in-memory snapshot restore, so the hook only
    fills devices the snapshot left empty."""
    reg = _wire_reg()

    order: list = []
    reg._restore_accrued_runtimes.side_effect = lambda *_a: order.append("inmemory")
    reg._runtime_restore_hook = MagicMock(side_effect=lambda: order.append("storage"))

    one_device = [{
        "energy_sensor": "sensor.depuradora_piscina_energy",
        "power_sensor": None,
        "name": "Depuradora Piscina",
        "is_ev": False,
    }]
    with patch(
        "custom_components.solar_energy_management.features."
        "device_registry.read_energy_dashboard_config",
        new=AsyncMock(return_value={"present": True}),
    ), patch(
        "custom_components.solar_energy_management.features."
        "device_registry.get_all_individual_devices",
        return_value=one_device,
    ):
        await reg.async_refresh_devices()

    reg._runtime_restore_hook.assert_called_once()
    # Storage fill must run AFTER the in-memory restore, never before.
    assert order == ["inmemory", "storage"]


@pytest.mark.asyncio
async def test_refresh_survives_hook_exception():
    """A throwing hook must not break device discovery."""
    reg = _wire_reg()
    reg._runtime_restore_hook = MagicMock(side_effect=RuntimeError("boom"))
    one_device = [{
        "energy_sensor": "sensor.depuradora_piscina_energy",
        "power_sensor": None,
        "name": "Depuradora Piscina",
        "is_ev": False,
    }]
    with patch(
        "custom_components.solar_energy_management.features."
        "device_registry.read_energy_dashboard_config",
        new=AsyncMock(return_value={"present": True}),
    ), patch(
        "custom_components.solar_energy_management.features."
        "device_registry.get_all_individual_devices",
        return_value=one_device,
    ):
        # The hook raises, but discovery must complete without propagating.
        await reg.async_refresh_devices()
    reg._runtime_restore_hook.assert_called_once()
