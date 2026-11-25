"""(#1394) The live base load is a short mean of the house and the devices.

``home`` is built from meters that report at their own times (on HA-PROD the
grid meter and the battery every 15-25 s, a smart plug every second), so one
cycle's ``home - devices`` can meet a plug's new draw against the house's old
one. PROD 24.11.2026 09:39:19: house 984 W, the coffee machine still counted
at 1365 W, base -667 W. The first fix (each plug's value at the oldest meter
report) moved the error instead of removing it: 17 negative readings that
day where plain subtraction gave 12. Averaging both sides over 120 s gives
none (fixture: the real PROD cycles around five of that day's events).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import coordinator as coord_mod
from custom_components.solar_energy_management.coordinator.baseload_window import (
    WINDOW_S,
    BaseloadWindow,
    live_baseload,
)
from custom_components.solar_energy_management.devices.base import CurrentControlDevice

from .ast_contracts import call_sites, symbol_reference_files
from .cycle_rig import CycleRig

FIXTURE = Path(__file__).parent / "fixtures" / "prod_baseload_cycles_20261124.json"
ROOT = Path(coord_mod.__file__).resolve().parent


def _segments():
    return json.loads(FIXTURE.read_text())["segments"]


# ── the window, on the real PROD cycles ────────────────────────────────

class TestRealCycles:
    def test_the_fixture_shows_the_false_negatives(self):
        """Plain subtraction of the recorded cycles goes negative (the bug)."""
        negatives = sum(1 for seg in _segments() for _, h, d in seg["cycles"] if h - d < 0)
        assert negatives >= 5

    def test_the_mean_never_goes_negative(self):
        for seg in _segments():
            window = BaseloadWindow()
            means = [window.add(t, h, d) for t, h, d in seg["cycles"]]
            assert min(means) > 400, seg["window"]

    def test_a_lasting_double_count_still_shows(self):
        """Negative is the diagnostic's sharpest finding: a device counted
        twice stays negative in every sample, so in the mean too."""
        window = BaseloadWindow()
        out = [window.add(10.0 * i, 500.0, 900.0) for i in range(30)]
        assert out[-1] == pytest.approx(-400.0)


class TestTheWindow:
    def test_one_sample_is_the_plain_difference(self):
        assert BaseloadWindow().add(0.0, 1000.0, 250.0) == pytest.approx(750.0)

    def test_old_samples_leave_the_window(self):
        window = BaseloadWindow()
        window.add(0.0, 5000.0, 0.0)
        out = window.add(WINDOW_S + 10.0, 800.0, 100.0)
        assert out == pytest.approx(700.0)
        assert window.size == 1

    def test_samples_weigh_by_how_long_they_stood(self):
        window = BaseloadWindow()
        window.add(0.0, 1000.0, 0.0)
        window.add(10.0, 1000.0, 0.0)
        out = window.add(40.0, 2000.0, 0.0)   # stood 30 s against 10 + 10
        assert out == pytest.approx((10 * 1000 + 10 * 1000 + 30 * 2000) / 50)

    def test_a_clock_that_runs_back_starts_again(self):
        window = BaseloadWindow()
        window.add(100.0, 9000.0, 0.0)
        assert window.add(50.0, 800.0, 100.0) == pytest.approx(700.0)

    def test_no_window_is_plain(self):
        assert live_baseload(None, 0.0, 900.0, 300.0) == pytest.approx(600.0)


# ── the real cycle ─────────────────────────────────────────────────────

WIRED = {
    "solar_production_sensor": "sensor.solar",
    "grid_power_sensor": "sensor.grid",
    "battery_power_sensor": "sensor.batt",
    "battery_soc_sensor": "sensor.soc",
    "battery_capacity_kwh": 10.0,
    "battery_reserve_soc": 20,
}


class _States:
    def __init__(self):
        self._m = {}

    def put(self, entity_id, value):
        self._m[entity_id] = value

    def get(self, entity_id):
        if entity_id not in self._m:
            return None
        return SimpleNamespace(entity_id=entity_id, state=str(self._m[entity_id]),
                               attributes={}, last_updated=None, last_reported=None)

    def async_all(self, *args, **kwargs):
        return []


@pytest.mark.asyncio
async def test_the_cycle_publishes_the_mean(monkeypatch):
    """19.11 05:18 through the real cycle, 10 s apart: the plug switches on
    a cycle before the grid read shows it. The published base load stays
    positive; plain subtraction gave -687 W on the middle cycle."""
    clock = {"t": 1000.0}
    monkeypatch.setattr(coord_mod.time, "monotonic", lambda: clock["t"])
    rig = CycleRig(config=dict(WIRED), states={})
    states = _States()
    rig.hass.states = states
    rig.coord._sensor_reader.hass = rig.hass
    plug = CurrentControlDevice(MagicMock(), device_id="kaffeetoaster", name="Kaffeetoaster",
                                power_entity_id="sensor.kaffeetoaster_power",
                                current_entity_id="number.kaffeetoaster_amps")
    plug.hass = rig.hass
    rig.coord._surplus_controller.register_device(plug)
    states.put("sensor.solar", 0)
    states.put("sensor.batt", 0)
    states.put("sensor.soc", 20)
    base = []
    for grid_w, plug_w in ((655, 15.1), (655, 15.1), (647, 1334), (2190, 1334), (2190, 1334)):
        states.put("sensor.grid", -grid_w)
        states.put("sensor.kaffeetoaster_power", plug_w)
        clock["t"] += 10.0
        base.append((await rig.coord._async_update_data())["true_baseload_power"])
    assert min(base) > 0, base
    assert base[0] == pytest.approx(655 - 15.1, abs=1)


def test_one_producer_and_no_instant_alignment():
    """The live base load comes from ``live_baseload`` only; the instant
    alignment that moved the error is gone from the package."""
    assert [f for f, _, _ in call_sites("live_baseload")] == ["coordinator/coordinator.py"]
    assert symbol_reference_files("DrawHistory") == []
    assert symbol_reference_files("house_complete_at") == []
    assert not (ROOT / "draw_alignment.py").exists()
