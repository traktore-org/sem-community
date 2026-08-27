"""park_off on the device layer — a clean keba.disable, no quota, dead-man
armed. (park-on-disconnect / #846 companion.)"""
from __future__ import annotations

import pytest


class _Services:
    def __init__(self, have):
        self._have = set(have)
        self.calls = []

    def has_service(self, domain, service):
        return f"{domain}.{service}" in self._have

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append((f"{domain}.{service}", dict(data)))


class _Hass:
    def __init__(self, have):
        self.services = _Services(have)
        self.states = None


def _keba_device():
    from custom_components.solar_energy_management.devices.base import (
        CurrentControlDevice,
    )
    dev = CurrentControlDevice.__new__(CurrentControlDevice)
    dev.hass = _Hass({"keba.disable", "keba.set_failsafe", "keba.set_energy",
                      "keba.enable", "keba.set_current"})
    dev.name = "EV Charger"
    dev.charger_service = "keba.set_current"
    dev.start_stop_entity = None
    dev.min_current = 8
    dev.arm_failsafe_enabled = True
    dev.steady_failsafe = True
    dev._session_active = True
    dev._current_setpoint = 16.0
    dev._last_write_at = 123.0
    from custom_components.solar_energy_management.devices.base import (
        DeviceState,
        DeviceStatus,
    )
    dev._status = DeviceStatus(state=DeviceState.ACTIVE)
    return dev


@pytest.mark.asyncio
async def test_park_off_disables_and_never_writes_a_quota():
    dev = _keba_device()
    await dev.park_off()
    services = [c[0] for c in dev.hass.services.calls]
    assert "keba.disable" in services
    # the dead-man OFF failsafe is armed (fallback 0)
    fs = [c for c in dev.hass.services.calls if c[0] == "keba.set_failsafe"]
    assert fs and fs[-1][1]["failsafe_fallback"] == 0
    # NEVER a quota — that is the auto-charge this prevents
    assert "keba.set_energy" not in services
    assert not dev._session_active


@pytest.mark.asyncio
async def test_park_off_survives_a_missing_disable_service():
    dev = _keba_device()
    dev.hass = _Hass({"keba.set_current"})     # no disable/failsafe
    await dev.park_off()                        # must not raise
    assert not dev._session_active
