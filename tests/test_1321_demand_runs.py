"""#1321 — each plan demand publishes its own runs, so a gap stays a gap."""
from custom_components.solar_energy_management.sensor import (
    _PLAN_ATTR_BUDGET_BYTES,
    _energy_plan_attrs,
)

import json

CAR = "ev:keba"


def _block(h0, h1, w, demand=CAR):
    return {"id": demand, "start": f"2026-11-19T{h0:02d}:00:00+01:00",
            "end": f"2026-11-19T{h1:02d}:00:00+01:00", "power_w": w, "price": 0.1}


def _plan(blocks, **extra):
    return {"computed_at": "2026-11-19T00:30:00+01:00", "fits": True,
            "demands": [{"id": CAR, "status": "fits", "planned_kwh": 5.0}],
            "slots": [], "blocks": blocks, **extra}


def test_two_runs_with_a_gap_are_published_as_two_runs():
    attrs = _energy_plan_attrs(_plan([_block(1, 2, 3000.0), _block(4, 5, 2000.0)]))
    runs = attrs["demands"][0]["runs"]
    assert [(r[0][11:16], r[1][11:16], r[2]) for r in runs] == [
        ("01:00", "02:00", 3000), ("04:00", "05:00", 2000)]


def test_touching_slots_of_one_power_are_one_run():
    attrs = _energy_plan_attrs(_plan([_block(1, 2, 3000.0), _block(2, 3, 3000.0)]))
    assert len(attrs["demands"][0]["runs"]) == 1


def test_a_demand_without_blocks_gets_no_runs_key():
    attrs = _energy_plan_attrs(_plan([]))
    assert "runs" not in attrs["demands"][0]


def test_runs_go_last_when_everything_else_has_gone():
    blocks = [{**_block(0, 1, 100.0 + i, f"load:d{d}"),
               "start": f"2026-11-19T{(i // 60) % 24:02d}:{i % 60:02d}:00+01:00",
               "end": f"2026-11-19T{(i // 60) % 24:02d}:{i % 60:02d}:30+01:00"}
              for d in range(12) for i in range(100)]
    plan = _plan(blocks)
    plan["demands"] = [{"id": f"load:d{d}", "status": "fits"} for d in range(12)]
    attrs = _energy_plan_attrs(plan)
    assert attrs["blocks"] == []
    assert len(json.dumps(attrs, default=str)) <= _PLAN_ATTR_BUDGET_BYTES
    assert attrs["demands"] and all("runs" not in d for d in attrs["demands"])


def test_a_learning_verdict_says_how_many_nights_it_needs():
    from custom_components.solar_energy_management.coordinator.demand_review import (
        DemandVerdict,
    )
    row = DemandVerdict("battery", "battery", "learning", 1.0, 1.0, nights=2, needed=5).as_dict()
    assert (row["nights"], row["needed"]) == (2, 5)


def test_no_surplus_tip_when_next_to_nothing_is_exported():
    from unittest.mock import MagicMock
    from custom_components.solar_energy_management.analytics.energy_assistant import (
        EnergyAssistant,
    )
    hass = MagicMock()
    hass.config.currency = "CHF"
    a = EnergyAssistant(hass)
    a._analyze_surplus(0.02, 0.02, False, False)
    assert a._tips == [], "100 % of 0.02 kWh is not advice"
    a._analyze_surplus(8.0, 10.0, False, False)
    assert [t.category for t in a._tips] == ["surplus", "surplus"]
