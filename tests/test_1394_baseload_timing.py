"""(#1394) The live base load takes each device's draw as it stood when the
house reading was complete.

PROD, 19.11 05:18:29 UTC: house 647 W (grid meter read 05:18:21), coffee
machine plug 1334 W (changed 05:18:28), base load -687 W. Six seconds later
the grid read 2190 W and the base load was right again. A plug reports every
second; this grid meter every 15-20 s.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.draw_alignment import (
    MAX_SHIFT,
    DrawHistory,
    house_complete_at,
)
from custom_components.solar_energy_management.devices.base import CurrentControlDevice

from .cycle_rig import CycleRig

NOW = datetime(2026, 11, 19, 5, 18, 29, tzinfo=timezone.utc)


def _t(seconds_before_now: float) -> datetime:
    return NOW - timedelta(seconds=seconds_before_now)


class TestDrawHistory:
    def test_the_coffee_machine_counts_once_the_grid_has_seen_it(self):
        h = DrawHistory()
        grid_read = _t(8)                                   # 05:18:21
        # 05:18:19 cycle: the plug idles at 15 W, changed 05:18:18
        assert h.as_of("plug", 15.1, _t(11), _t(10)) == 15.1
        # 05:18:29 cycle: the plug jumped at 05:18:28, after the grid read
        assert h.as_of("plug", 1334.0, _t(1), grid_read) == 15.1
        # 05:18:39 cycle: the grid read at 05:18:35 includes the machine
        assert h.as_of("plug", 1334.0, _t(1), _t(-6)) == 1334.0

    def test_no_house_time_keeps_the_live_value(self):
        h = DrawHistory()
        h.as_of("plug", 15.0, _t(20), _t(15))
        assert h.as_of("plug", 1334.0, _t(1), None) == 1334.0

    def test_no_change_time_keeps_the_live_value(self):
        assert DrawHistory().as_of("energy-only", 500.0, None, _t(8)) == 500.0

    def test_nothing_older_seen_keeps_the_live_value(self):
        # first sight of the device: there is no earlier value to use
        assert DrawHistory().as_of("plug", 1334.0, _t(1), _t(8)) == 1334.0

    def test_a_shift_longer_than_the_limit_is_not_made(self):
        h = DrawHistory()
        h.as_of("plug", 10.0, _t(200), _t(199))
        old = NOW - MAX_SHIFT - timedelta(seconds=30)
        assert h.as_of("plug", 900.0, _t(1), old) == 900.0

    def test_devices_keep_separate_histories(self):
        h = DrawHistory()
        h.as_of("a", 10.0, _t(30), _t(29))
        h.as_of("b", 700.0, _t(30), _t(29))
        assert h.as_of("a", 1200.0, _t(1), _t(8)) == 10.0
        assert h.as_of("b", 700.0, _t(30), _t(8)) == 700.0


class TestHouseCompleteAt:
    def test_the_oldest_recent_report_wins(self):
        reports = {"grid": _t(8), "solar": _t(2), "battery": _t(3)}
        assert house_complete_at(reports, NOW) == _t(8)

    def test_a_flat_sensor_not_resent_is_left_out(self):
        # solar at night, an integration that skips identical writes
        reports = {"grid": _t(8), "solar": _t(3 * 3600)}
        assert house_complete_at(reports, NOW) == _t(8)

    def test_nothing_recent_means_no_alignment(self):
        assert house_complete_at({"grid": _t(600)}, NOW) is None
        assert house_complete_at({}, NOW) is None


# ── the real cycle ─────────────────────────────────────────────────────

WIRED = {
    "solar_production_sensor": "sensor.solar",
    "grid_power_sensor": "sensor.grid",
    "battery_power_sensor": "sensor.batt",
    "battery_soc_sensor": "sensor.soc",
    "battery_capacity_kwh": 10.0,
    "battery_reserve_soc": 20,
}


class _TimedStates:
    """States with HA's two clocks: ``last_updated`` (value changed) and
    ``last_reported`` (last write, even unchanged)."""

    def __init__(self):
        self._m = {}

    def put(self, entity_id, value, changed, reported=None):
        self._m[entity_id] = (value, changed, reported or changed)

    def get(self, entity_id):
        if entity_id not in self._m:
            return None
        value, changed, reported = self._m[entity_id]
        return SimpleNamespace(entity_id=entity_id, state=str(value), attributes={},
                               last_updated=changed, last_reported=reported)

    def async_all(self, *args, **kwargs):
        return []


def _rig(timed: bool):
    rig = CycleRig(config=dict(WIRED), states={})
    states = _TimedStates()
    rig.hass.states = states
    rig.coord._sensor_reader.hass = rig.hass
    plug = CurrentControlDevice(MagicMock(), device_id="kaffeetoaster", name="Kaffeetoaster",
                                power_entity_id="sensor.kaffeetoaster_power",
                                current_entity_id="number.kaffeetoaster_amps")
    plug.hass = rig.hass
    rig.coord._surplus_controller.register_device(plug)
    return rig, states, timed


async def _tick(rig, states, timed, *, grid_w, grid_at, plug_w, plug_at):
    now = datetime.now(timezone.utc)
    stamp = (lambda s: now - timedelta(seconds=s)) if timed else (lambda s: None)
    states.put("sensor.solar", 0, stamp(3600), stamp(2))       # flat, polled
    states.put("sensor.batt", 0, stamp(3600), stamp(3))
    states.put("sensor.soc", 20, stamp(3600), stamp(3))
    states.put("sensor.grid", -grid_w, stamp(grid_at))
    states.put("sensor.kaffeetoaster_power", plug_w, stamp(plug_at))
    return await rig.coord._async_update_data()


async def _the_morning(timed: bool):
    rig, states, timed = _rig(timed)
    out = []
    # 05:18:19 — the plug idles (since 11 s), grid read 2 s ago. The rig's
    # cycles run back to back, so each stamp says how old it is at its tick.
    out.append(await _tick(rig, states, timed, grid_w=655, grid_at=2, plug_w=15.1, plug_at=11))
    # 05:18:29 — plug jumped 1 s ago, grid still from 8 s ago
    out.append(await _tick(rig, states, timed, grid_w=647, grid_at=8, plug_w=1334, plug_at=1))
    # 05:18:39 — grid read 4 s ago includes the machine; plug unchanged since
    out.append(await _tick(rig, states, timed, grid_w=2190, grid_at=4, plug_w=1334, plug_at=11))
    return [r["true_baseload_power"] for r in out], [r["home_consumption_power"] for r in out]


@pytest.mark.asyncio
class TestTheCycle:
    async def test_the_base_load_stays_positive_through_the_switch_on(self):
        base, home = await _the_morning(timed=True)
        assert home == pytest.approx([655, 647, 2190], abs=1)
        assert base[0] == pytest.approx(655 - 15.1, abs=1)
        assert base[1] == pytest.approx(647 - 15.1, abs=1), \
            "the plug's new load is not in the house reading yet"
        assert base[2] == pytest.approx(2190 - 1334, abs=1)
        assert min(base) > 0

    async def test_twin_without_times_it_reads_the_false_negative(self):
        # No report times (an old HA, a test stand-in): the live value as
        # before — and the 19.11 number comes back.
        base, _ = await _the_morning(timed=False)
        assert base[1] == pytest.approx(647 - 1334, abs=1)
