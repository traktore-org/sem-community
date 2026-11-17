"""(#1081) Drift samples kept across restarts — RECORD ONLY.

One row per free-running clock hour, 14 days, in SEM's own store. A restart
restores them; a damaged store is a fresh start; a small summary rides the
comfort block. Nothing decides from any of it.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator import drift_store as ds
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.storage import SEMStorage
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)
from custom_components.solar_energy_management.tests.test_1081_preheat import (
    NOW, _learned, _tank,
)

H0 = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def _hour(ts):
    return int(ts.timestamp() // 3600)


def _off_hours(dev, hours, *, start=H0, rate=-0.5):
    """Device-off samples every 10 min for each of ``hours`` whole hours."""
    dev._comfort_on_samples = deque()
    dev._comfort_off_samples = deque(
        (start + timedelta(hours=h, minutes=m), 50.0 + rate * (h + m / 60))
        for h in range(hours) for m in range(0, 60, 10))
    return start + timedelta(hours=hours + 1)


# ── folding ───────────────────────────────────────────────────────────────

def test_a_free_running_hour_becomes_one_row():
    _h, dev, _s = _tank(50.0)
    now = _off_hours(dev, 3)
    dev.drift_fold(now, lambda: 4.0)
    rows = dev._drift_rows
    assert [r[0] for r in rows] == [_hour(H0) + i for i in range(3)]
    slope, mean, outdoor, n = rows[0][1:]
    assert slope == pytest.approx(-0.5, abs=0.01) and outdoor == 4.0 and n == 6


def test_an_hour_the_device_ran_is_not_free_running():
    _h, dev, _s = _tank(50.0)
    now = _off_hours(dev, 2)
    dev._comfort_on_samples.append((H0 + timedelta(minutes=5), 49.0))
    dev.drift_fold(now, lambda: 4.0)
    assert [r[0] for r in dev._drift_rows] == [_hour(H0) + 1]


def test_it_folds_once_per_hour_and_never_the_current_hour():
    _h, dev, _s = _tank(50.0)
    now = _off_hours(dev, 2)
    calls = []
    dev.drift_fold(now, lambda: calls.append(1) or 4.0)
    dev.drift_fold(now + timedelta(minutes=5), lambda: calls.append(1) or 4.0)
    assert len(calls) == 1 and len(dev._drift_rows) == 2
    assert all(r[0] < _hour(now) for r in dev._drift_rows)


def test_no_outdoor_reading_still_records_the_hour():
    _h, dev, _s = _tank(50.0)
    dev.drift_fold(_off_hours(dev, 1), lambda: None)
    assert dev._drift_rows[0][3] is None


# ── bound and pruning ─────────────────────────────────────────────────────

def test_rows_older_than_14_days_are_dropped():
    now_h = _hour(H0)
    rows = [ds.make_row(now_h - 400 + i, -0.5, 50.0, 3.0, 6) for i in range(400)]
    kept = ds.prune(rows, now_h)
    assert len(kept) <= ds.KEEP_HOURS + 1 and kept[0][0] >= now_h - ds.KEEP_HOURS


def test_the_store_is_bounded_in_rows_and_bytes():
    import json
    now_h = _hour(H0)
    raw = {"hours": [ds.make_row(now_h - i, -0.5, 50.0, 3.0, 6) for i in range(2000)]}
    rows = ds.sanitize(raw, now_h)
    assert len(rows) <= ds.KEEP_HOURS + 1
    assert len(json.dumps({"hours": rows})) < 20000


# ── persist and restore ───────────────────────────────────────────────────

def _storage():
    st = SEMStorage.__new__(SEMStorage)
    st._energy_data = {}
    return st


def test_the_store_round_trips_through_a_new_device():
    _h, dev, _s = _tank(50.0)
    now = _off_hours(dev, 4)
    dev.drift_fold(now, lambda: 4.0)
    st = _storage()
    st.set_drift_state({dev.device_id: dev.drift_memo()})
    stored = st.get_drift_state()
    _h, fresh, _s = _tank(50.0)
    fresh.drift_restore(stored[dev.device_id], now)
    assert fresh._drift_rows == dev._drift_rows
    assert fresh.drift_summary() == dev.drift_summary()


@pytest.mark.parametrize("bad", [
    None, "x", 5, [], {}, {"hours": "x"}, {"hours": [1, 2]}, {"hours": [[1, 2, 3]]},
    {"hours": [["a", 1, 2, 3, 4]]}, {"hours": [[1, float("nan"), 2, 3, 4]]},
    {"hours": [[0, 1, 2, 3, 4]]},            # far too old
])
def test_a_damaged_store_is_a_fresh_start(bad):
    _h, dev, _s = _tank(50.0)
    dev.drift_restore(bad, H0)
    assert dev._drift_rows == [] and dev.drift_summary() is None
    assert dev._drift_restored is True


def test_one_bad_row_does_not_cost_the_good_ones():
    h = _hour(H0)
    good = ds.make_row(h - 3, -0.4, 50.0, 3.0, 6)
    rows = ds.sanitize({"hours": [good, ["x"], [h - 2, "bad", 1, 2, 3]]}, h)
    assert rows == [good]


def test_the_storage_getter_survives_a_non_dict():
    st = _storage()
    st._energy_data["drift_state"] = "junk"
    assert st.get_drift_state() == {}


def test_the_coordinator_restores_once_then_folds_and_the_save_carries_the_rows():
    _h, dev, _s = _tank(50.0)
    st = _storage()
    now = _off_hours(dev, 3)
    coord = SimpleNamespace(
        _storage=st, _outdoor_temperature_or_none=lambda: 4.0,
        _surplus_controller=SimpleNamespace(_devices={dev.device_id: dev}))
    SEMCoordinator._record_drift_rows(coord, dev, now)
    assert len(dev._drift_rows) == 3
    memos = SEMCoordinator._drift_memos(coord)
    assert set(memos) == {dev.device_id}
    st.set_drift_state(memos)
    # a restart: a new device, the same store
    _h, again, _s = _tank(50.0)
    coord2 = SimpleNamespace(
        _storage=st, _outdoor_temperature_or_none=lambda: 4.0,
        _surplus_controller=SimpleNamespace(_devices={again.device_id: again}))
    SEMCoordinator._record_drift_rows(coord2, again, now)
    assert again._drift_rows == dev._drift_rows


def test_a_unit_without_a_band_is_left_alone():
    plain = SimpleNamespace(device_id="x")
    coord = SimpleNamespace(_storage=_storage())
    SEMCoordinator._record_drift_rows(coord, plain, H0)
    assert not hasattr(plain, "_drift_rows")


# ── the summary ───────────────────────────────────────────────────────────

def _rows(n, outdoor=lambda i: 4.0, slope=lambda i: -0.5):
    h = _hour(H0)
    return [ds.make_row(h + i, slope(i), 50.0, outdoor(i), 6) for i in range(n)]


def test_no_rows_no_summary():
    assert ds.summarize([]) is None


def test_a_few_hours_say_learning():
    s = ds.summarize(_rows(ds.MIN_HOURS - 1))
    assert s["state"] == ds.LEARNING and "rate_c_per_h" not in s
    assert s["hours"] == ds.MIN_HOURS - 1 and s["samples"] == 6 * (ds.MIN_HOURS - 1)


def test_enough_hours_give_a_rate_at_the_mean_outdoor_when_it_barely_moved():
    s = ds.summarize(_rows(24))
    assert s["state"] == ds.LEARNED
    assert s["rate_c_per_h"] == -0.5 and s["ref_outdoor_c"] == 4.0


def test_a_spread_of_outdoor_temperature_gives_the_rate_at_the_reference():
    # colder outdoors cools faster: -0.1 K/h per K below 15 C
    s = ds.summarize(_rows(48, outdoor=lambda i: float(i % 20),
                           slope=lambda i: -0.1 * (15 - (i % 20))))
    assert s["state"] == ds.LEARNED and s["ref_outdoor_c"] == ds.REFERENCE_OUTDOOR_C
    assert s["rate_c_per_h"] == pytest.approx(-1.0, abs=0.02)


def test_the_comfort_block_carries_it_only_with_rows():
    _h, dev, _s = _tank(50.0)
    assert "drift" not in UnifiedDeviceRegistry._comfort_payload(dev)["comfort"]
    dev._drift_rows = _rows(3)
    drift = UnifiedDeviceRegistry._comfort_payload(dev)["comfort"]["drift"]
    assert drift["state"] == ds.LEARNING and drift["hours"] == 3


# ── nothing decides from it ───────────────────────────────────────────────

@pytest.mark.parametrize("temp", [47.0, 50.5, 54.0])
def test_the_planners_demand_is_the_same_with_and_without_stored_rows(temp):
    for goal in (True, False):
        _h, plain, _s = _tank(temp)
        _h, stored, _s = _tank(temp)
        for d in (plain, stored):
            _learned(d)
            d._comfort_off_samples = deque(
                (NOW - timedelta(minutes=60 - m), temp - 0.01 * m)
                for m in range(0, 61, 10))
        stored._drift_rows = _rows(48, slope=lambda i: -3.0)   # a wild rate
        assert (plain.comfort_plan_demand(NOW, goal=goal)
                == stored.comfort_plan_demand(NOW, goal=goal))
        assert plain.comfort_state == stored.comfort_state


def test_folding_never_touches_the_four_hour_buffers():
    _h, dev, _s = _tank(50.0)
    now = _off_hours(dev, 3)
    before = (list(dev._comfort_on_samples), list(dev._comfort_off_samples))
    dev.drift_fold(now, lambda: 4.0)
    assert before == (list(dev._comfort_on_samples), list(dev._comfort_off_samples))


def test_no_planner_module_reads_the_rows():
    """The only readers are the device's own methods and the Diagnose block."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    readers = []
    for p in root.rglob("*.py"):
        if "tests" in p.parts or "node_modules" in p.parts:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        if "drift_summary" in text or "_drift_rows" in text or "drift_store" in text:
            readers.append(p.relative_to(root).as_posix())
    assert set(readers) <= {
        "devices/base.py", "coordinator/drift_store.py",
        "features/device_registry.py", "coordinator/coordinator.py"}
    coord = (root / "coordinator" / "coordinator.py").read_text()
    assert "._drift_rows" not in coord and ".drift_summary" not in coord
