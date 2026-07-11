"""Observation mode — a charger SEM reads + traces but never commands (2026-07-11).

Used to isolate a shared charger (a test instance that must never touch real
hardware) and as a general "watch without controlling" mode. Config key
``ev_monitor_only`` (global) or per-charger ``monitor_only``.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.actuate import actuate
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision, ChargerIntent, ChargerPower,
)


class _Reconciler:
    def __init__(self):
        self.applied = False

    async def reconcile_and_apply(self, decision, adapter, power, now):
        self.applied = True


class _Adapter:
    def __init__(self, monitor_only):
        self._monitor_only = monitor_only

    @property
    def monitor_only(self):
        return self._monitor_only


def _decision():
    return ChargerDecision(charger_id="keba", mode="min_plus_solar",
                           intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=16)


def _power():
    return ChargerPower(charger_id="keba", power_w=0.0, connected=True)


@pytest.mark.unit
class TestObservationMode:
    @pytest.mark.asyncio
    async def test_monitor_only_issues_no_command(self):
        rec = _Reconciler()
        await actuate(_decision(), _Adapter(monitor_only=True), _power(), rec)
        assert rec.applied is False        # SEM did NOT touch the hardware

    @pytest.mark.asyncio
    async def test_normal_charger_is_commanded(self):
        rec = _Reconciler()
        await actuate(_decision(), _Adapter(monitor_only=False), _power(), rec)
        assert rec.applied is True         # normal path still actuates


@pytest.mark.unit
def test_adapter_reads_device_monitor_only():
    # the base adapter property reads the wrapped device's flag — test the
    # property function directly (the ABC has many abstract methods).
    from custom_components.solar_energy_management.coordinator.charger_adapters.base import (
        ChargerAdapter,
    )
    from types import SimpleNamespace

    fget = ChargerAdapter.monitor_only.fget
    assert fget(SimpleNamespace(_device=SimpleNamespace(monitor_only=True))) is True
    assert fget(SimpleNamespace(_device=SimpleNamespace(monitor_only=False))) is False
    assert fget(SimpleNamespace(_device=None)) is False       # robust: no device
    assert fget(SimpleNamespace()) is False                   # robust: no _device
