"""#1290 — a load's wait compares hours, not kWh.

The plan sized a load's blocks with the rating of planning time. The wait
counted the deficit with the rating of now, which only goes up. A raise during
a block made the next block look short and ended the wait, so the load could
run outside its block. The deficit is now compared with the blocks in hours.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator import (
    coordinator as coord_mod,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
    merge_load_gates,
    plan_gate,
)

TZ = coord_mod.dt_util.DEFAULT_TIME_ZONE
STAMP = datetime(2026, 7, 29, 22, 0, tzinfo=TZ)


def _at(h, m=0):
    return STAMP.replace(hour=h, minute=m) + timedelta(days=1 if h < 12 else 0)


def _load_plan(power_w):
    def _iso(h):
        return _at(h).isoformat()
    return {
        "computed_at": STAMP.isoformat(),
        "demands": [{"id": "load:boiler", "status": "fits"}],
        "slots": [{"start": STAMP.isoformat(), "end": _iso(7)}],
        "blocks": [
            {"id": "load:boiler", "start": _iso(22), "end": _iso(23),
             "power_w": power_w},
            {"id": "load:boiler", "start": _iso(1), "end": _iso(2),
             "power_w": power_w},
        ],
    }


def _windows(monkeypatch, plan_dict, *, rated_now, deficit_h, at):
    monkeypatch.setattr(coord_mod.dt_util, "now", lambda *a, **k: at)
    fake = SimpleNamespace(
        _energy_plan_actuation=True, _energy_plan_shadow=plan_dict,
        _energy_plan_gate=lambda did, now: plan_gate(plan_dict, did, now))
    dev = SimpleNamespace(
        device_id="boiler", daily_min_runtime_sec=2 * 3600,
        _daily_runtime_accumulated_sec=(2 - deficit_h) * 3600,
        rated_power=rated_now)
    return SEMCoordinator._energy_plan_load_windows(fake, [dev])


def test_a_rating_raised_after_the_plan_keeps_the_hold(monkeypatch):
    # planned at 800 W; one hour ran in block 1, one hour left; the rating
    # has since risen to 1000 W — still one hour of blocks for one hour left
    w = _windows(monkeypatch, _load_plan(800.0), rated_now=1000.0,
                 deficit_h=1.0, at=_at(23, 30))
    assert "boiler" in w and w["boiler"].hold, (
        "the next block holds the whole runtime — the load must wait (#1290)")


def test_the_kwh_count_would_have_released_it():
    """Twin: the old kWh count with the raised rating."""
    absent = plan_gate(None, "comfort:boiler", _at(23, 30))
    gate = plan_gate(_load_plan(800.0), "load:boiler", _at(23, 30))
    old = merge_load_gates(gate, absent, deficit_kwh=1.0 * 1000.0 / 1000.0)
    assert old is None


def test_a_real_runtime_shortage_still_releases(monkeypatch):
    w = _windows(monkeypatch, _load_plan(800.0), rated_now=1000.0,
                 deficit_h=1.5, at=_at(23, 30))
    assert "boiler" not in w
