"""#532 — a SEM restart/reload mid-forcible-discharge must not strand it.

Huawei battery→grid arbitrage is the ``huawei_solar.forcible_discharge_soc``
SERVICE — the inverter runs it autonomously until ``target_soc``. A restart
gives a fresh adapter ``_forcible_discharging = False`` so the flag-gated
``_stop_forcible()`` never fires, and the inverter drains the battery to the
reserve floor unsupervised (PROD incident 2026-06-19: 80%→20% to grid).

The fix: on the first non-force-discharge cycle after startup (once
``huawei_solar`` is loaded), detect an active forcible op via the integration's
status sensor and issue one ``stop_forcible_charge`` for anything SEM didn't
start this lifetime. ``command_force_discharge`` opts out (it re-asserts).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.battery_adapters.huawei import (
    HuaweiBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
)

_STOP = ("huawei_solar", "stop_forcible_charge")
_SELL = ("huawei_solar", "forcible_discharge_soc")
_LIMIT = ("number", "set_value")


def _fake_state(eid, state):
    s = MagicMock()
    s.entity_id = eid
    s.state = state
    return s


def _hass_huawei(forcible_state=None, loaded=True):
    """hass where huawei_solar is (optionally) loaded and a forcible-status
    sensor (optionally) reports ``forcible_state``."""
    h = MagicMock()
    h.services.async_call = AsyncMock()
    h.data = {"huawei_solar": {}} if loaded else {}
    h.config_entries.async_entries = MagicMock(return_value=[])
    sensors = []
    if forcible_state is not None:
        sensors.append(
            _fake_state("sensor.batteries_forcible_charge", forcible_state)
        )
    h.states.async_all = MagicMock(return_value=sensors)
    return h


def _adapter(h, **cfg):
    base = {
        "inverter_device_id": "dev1",
        "battery_max_discharge_power": 5000,
        "battery_discharge_control_entity": "number.lim",
    }
    base.update(cfg)
    return HuaweiBatteryAdapter(h, base)


def _calls(h):
    return [(c.args[0], c.args[1]) for c in h.services.async_call.await_args_list]


# ── the incident: restart mid-discharge → orphan stopped ────────────────

@pytest.mark.asyncio
async def test_restart_normal_stops_orphan_discharge():
    h = _hass_huawei(forcible_state="Discharge")
    a = _adapter(h)  # fresh adapter == restart; _forcible_discharging False
    await a.command_normal()
    calls = _calls(h)
    assert _STOP in calls, "must cancel the orphan forcible discharge"
    assert _LIMIT not in calls, "defer the discharge-limit write this cycle"
    assert a.last_intent is BatteryIntent.NORMAL
    assert a._startup_orphan_checked is True


@pytest.mark.asyncio
async def test_restart_no_orphan_applies_limit_normally():
    h = _hass_huawei(forcible_state="Stopped")  # nothing in flight
    a = _adapter(h)
    await a.command_normal()
    calls = _calls(h)
    assert _STOP not in calls
    assert _LIMIT in calls
    assert a._startup_orphan_checked is True


@pytest.mark.asyncio
async def test_orphan_stop_recovers_to_normal_limit_after_retries():
    # One clean stop + 2 belt-and-braces retries (flaky Modbus), then the
    # normal discharge-limit is applied.
    h = _hass_huawei(forcible_state="Discharge")
    a = _adapter(h)
    await a.command_normal()  # cycle1: orphan stop, _stop_retries=2
    await a.command_normal()  # cycle2: retry stop
    await a.command_normal()  # cycle3: retry stop
    h.services.async_call.reset_mock()
    await a.command_normal()  # cycle4: retries spent → apply limit
    calls = _calls(h)
    assert _STOP not in calls
    assert _LIMIT in calls


# ── startup race: wait until huawei_solar is loaded ─────────────────────

@pytest.mark.asyncio
async def test_orphan_check_waits_for_sensor_ready():
    # huawei_solar is loaded but the forcible sensor is still 'unknown'
    # (just-polled lag). Must NOT burn the one-shot — re-check next cycle.
    h = _hass_huawei(forcible_state="unknown")
    a = _adapter(h)
    await a.command_normal()
    assert a._startup_orphan_checked is False, "pending sensor must not consume the one-shot"
    assert _STOP not in _calls(h)
    # sensor now reports the in-flight discharge
    h.states.async_all = MagicMock(
        return_value=[_fake_state("sensor.batteries_forcible_charge", "Discharge")]
    )
    h.services.async_call.reset_mock()
    await a.command_normal()
    assert _STOP in _calls(h)
    assert a._startup_orphan_checked is True


@pytest.mark.asyncio
async def test_orphan_check_waits_for_integration_loaded():
    h = _hass_huawei(forcible_state="Discharge", loaded=False)
    a = _adapter(h)
    await a.command_normal()  # not loaded → don't burn the one-shot
    assert a._startup_orphan_checked is False
    assert _STOP not in _calls(h)
    assert _LIMIT in _calls(h)  # behaved as plain NORMAL
    # integration finishes loading
    h.data = {"huawei_solar": {}}
    h.services.async_call.reset_mock()
    await a.command_normal()  # now detects + stops
    assert _STOP in _calls(h)
    assert a._startup_orphan_checked is True


# ── resume arbitrage after restart: re-assert, don't stop ───────────────

@pytest.mark.asyncio
async def test_restart_resume_arbitrage_reissues_not_stops():
    h = _hass_huawei(forcible_state="Discharge")
    a = _adapter(h)
    await a.command_force_discharge(4000, 20.0)
    calls = _calls(h)
    assert _SELL in calls, "re-assert the sell"
    assert _STOP not in calls, "must NOT stop when resuming arbitrage"
    assert a._startup_orphan_checked is True


@pytest.mark.asyncio
async def test_own_discharge_then_normal_still_stops():
    # We start the discharge ourselves (not an orphan), then NORMAL must still
    # stop it via the regular _stop_forcible path.
    h = _hass_huawei(forcible_state="Discharge")
    a = _adapter(h)
    await a.command_force_discharge(4000, 20.0)  # we own it
    h.services.async_call.reset_mock()
    await a.command_normal()
    assert _STOP in _calls(h)


# ── other exits also cancel an orphan ───────────────────────────────────

@pytest.mark.asyncio
async def test_restart_force_charge_stops_orphan_first():
    h = _hass_huawei(forcible_state="Discharge")
    a = _adapter(h)
    await a.command_force_charge(100.0, 3000, 60)
    assert _STOP in _calls(h)
    assert a._startup_orphan_checked is True


@pytest.mark.asyncio
async def test_restart_limit_discharge_stops_orphan_first():
    h = _hass_huawei(forcible_state="Discharge")
    a = _adapter(h)
    await a.command_limit_discharge(800)
    assert _STOP in _calls(h)


@pytest.mark.asyncio
async def test_restart_stop_force_discharge_stops_orphan():
    h = _hass_huawei(forcible_state="Discharge")
    a = _adapter(h)
    await a.command_stop_force_discharge()
    assert _STOP in _calls(h)


# ── status-sensor classification + robustness ───────────────────────────

@pytest.mark.parametrize("state,active", [
    ("Discharge", True),
    ("Charge", True),
    ("Forcible discharge", True),
    ("Forcible charge", True),
    ("Stopped", False),
    ("Stop", False),
    ("unknown", False),
    ("unavailable", False),
    ("Idle", False),
    ("", False),
])
def test_forcible_status_active_classification(state, active):
    a = _adapter(_hass_huawei(forcible_state=state))
    assert a._forcible_status_active() is active


def test_no_forcible_sensor_means_inactive():
    a = _adapter(_hass_huawei(forcible_state=None))
    assert a._forcible_status_active() is False


def test_forcible_status_robust_to_non_iterable_states():
    h = _hass_huawei()
    h.states.async_all = MagicMock(side_effect=TypeError("not iterable"))
    a = _adapter(h)
    assert a._forcible_status_active() is False


def test_forcible_status_ignores_unrelated_sensors():
    h = _hass_huawei()
    h.states.async_all = MagicMock(return_value=[
        _fake_state("sensor.kitchen_temperature", "Discharge"),  # not forcible
        _fake_state("sensor.battery_soc", "72"),
    ])
    a = _adapter(h)
    assert a._forcible_status_active() is False
