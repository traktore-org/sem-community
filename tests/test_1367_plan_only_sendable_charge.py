"""#1367 — the plan showed a battery charge SEM cannot send.

A battery whose adapter takes no charge command (no charge control set)
got a charge block anyway: SEM then dropped the command, and the plan had
counted that energy as stored. Now the plan leaves it out and says why;
with two packs, only the one that takes commands is planned.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator import coordinator as coord_mod
from custom_components.solar_energy_management.coordinator import ev_night_targets
from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
    SchedulerState,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)

from .test_638_shadow_mode import (  # noqa: F401 — fixtures come along
    _DayCapableTime, _fake_self, _power,
)
from .test_1311_battery_grid_charge_night_only import (
    _MiddayAndNightCheap, _scheduler,
)

TZ = coord_mod.dt_util.DEFAULT_TIME_ZONE


def _ad(ok):
    return SimpleNamespace(supports_forced_charge=ok)


def _plan(monkeypatch, adapters, caps=None, deficit=4.0):
    monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                        lambda coord, energy: {})
    fake = _fake_self(devices=[])
    fake.time_manager = _DayCapableTime()
    fake._tariff_provider = _MiddayAndNightCheap()
    fake._live_battery_adapters = lambda: list(adapters.items())
    fake._unit_capacity_kwh = lambda bid, power=None: (caps or {}).get(bid, 0.0)
    fake._charge_command_share = (
        lambda power=None: SEMCoordinator._charge_command_share(fake, power))
    fixed = datetime(2026, 7, 29, 22, 0, tzinfo=TZ)
    monkeypatch.setattr(coord_mod.dt_util, "now", lambda *a, **k: fixed)
    SEMCoordinator._shadow_energy_plan(
        fake, _scheduler(SchedulerState.SCHEDULED, deficit),
        energy=MagicMock(), power=_power())
    return fake._energy_plan_shadow


def _battery_row(plan):
    return next((r for r in plan.get("demands", []) if r["id"] == "battery"), None)


def test_a_battery_that_takes_commands_is_planned_as_before(monkeypatch):
    plan = _plan(monkeypatch, {"b1": _ad(True)})
    row = _battery_row(plan)
    assert row and row["needed_kwh"] == 4.0
    assert not [r for r in plan["not_scheduled"] if r["id"].startswith("battery")]


def test_no_charge_control_means_no_charge_block_and_a_reason(monkeypatch):
    plan = _plan(monkeypatch, {"b1": _ad(False)})
    assert _battery_row(plan) is None
    assert not any(a.startswith("battery") for a in plan.get("allocations") or [])
    assert {"id": "battery", "why": "no_charge_control", "label": None} in plan["not_scheduled"]
    # the quiet answer does not claim the battery needs nothing
    assert "battery_no_deficit" not in (plan.get("why_codes") or [])


def test_two_packs_only_the_commanded_one_is_planned(monkeypatch):
    plan = _plan(monkeypatch, {"b1": _ad(True), "b2": _ad(False)},
                 caps={"b1": 10.0, "b2": 5.0}, deficit=6.0)
    row = _battery_row(plan)
    assert row and abs(row["needed_kwh"] - 4.0) < 0.01   # 10 of 15 kWh
    assert [r for r in plan["not_scheduled"] if r["id"].startswith("battery")] == [
        {"id": "battery:b2", "why": "no_charge_control", "label": None}]


def test_could_not_ask_plans_as_before(monkeypatch):
    # no adapter built yet, or one that answers no bool: unknown, not "no"
    for adapters in ({}, {"b1": SimpleNamespace(supports_forced_charge=None)}):
        plan = _plan(monkeypatch, adapters)
        assert _battery_row(plan)["needed_kwh"] == 4.0


def test_every_language_has_the_reason():
    import json
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    d = json.loads((root / "dashboard" / "translations.json").read_text())
    key = "energy_plan_why_" + "no_charge_control"
    assert all(d[lang].get(key) for lang in d)
