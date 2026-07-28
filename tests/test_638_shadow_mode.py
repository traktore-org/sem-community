"""#638 G3 — the shadow hook: real demand models in, logged plan out, no actuation.

Runs ``SEMCoordinator._shadow_overnight_plan`` unbound against a minimal fake
coordinator: a real per-charger night-target map (monkeypatched), one load with
a runtime deficit, the battery scheduler's deficit, and an hourly price curve.
Asserts the plan is computed, stashed, and explainable — and that the hook can
NEVER break the cycle (any internal error degrades to a debug log).
"""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator import ev_night_targets


class _FakeTariff:
    def get_price_at(self, t):
        # Cheap 02:00-04:00, pricier elsewhere.
        return 0.10 if t.hour in (2, 3) else 0.28


class _FakeTime:
    def get_night_end_time(self):
        return "07:00"


def _fake_load(did="pump", priority=4):
    return SimpleNamespace(
        device_id=did, has_runtime_deficit=True,
        battery_eligible_overnight=True, top_up_policy="solar_only",
        daily_min_runtime_sec=4 * 3600, _daily_runtime_accumulated_sec=2 * 3600,
        rated_power=800.0, priority=priority,
    )


def _fake_self(devices=()):
    fake = SimpleNamespace(
        config={
            "ev_chargers": [{"id": "ev_charger", "ev_phases": 3,
                             "ev_voltage": 230, "ev_max_current": 16,
                             "ev_min_current": 6, "ev_target_time": "06:30",
                             "priority": 3}],
            "peak_limit_w": 6000.0,
            "battery_priority_soc": 30,
        },
        time_manager=_FakeTime(),
        _tariff_provider=_FakeTariff(),
        _surplus_controller=SimpleNamespace(
            get_devices_sorted=lambda: list(devices)),
        _overnight_shadow_plan=None,
        # The canonical one-list accessors the shadow now uses (#576).
        _ev_priority_for=lambda cid: 3,
        _device_registry=SimpleNamespace(battery_surplus_priority=lambda: 2),
        _expected_night_home_w=lambda energy: 400.0,
        battery_capacity_kwh=10.0,
    )
    return fake


def _power(soc=80.0):
    return SimpleNamespace(battery_soc=soc)


def _scheduler(deficit=3.0):
    return SimpleNamespace(
        decision=SimpleNamespace(deficit_kwh=deficit),
        _config=SimpleNamespace(battery_max_charge_power_w=5000.0),
    )


@pytest.fixture
def freeze_targets(monkeypatch):
    monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                        lambda coord, energy: {"ev_charger": 6.0})


def test_shadow_plan_computes_and_stashes(freeze_targets):
    fake = _fake_self(devices=[_fake_load()])
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(), energy=MagicMock(), phantom_ev_kwh=10.0,
        phantom_ev_w=11000.0, power=_power())
    plan = fake._overnight_shadow_plan
    assert plan is not None
    assert plan["fits"] is True
    # All three demand kinds present in the summary.
    joined = " ".join(plan["summary"])
    assert "ev:ev_charger" in joined
    assert "load:pump" in joined
    assert "battery" in joined
    assert plan["allocations"], "expected per-slot allocation lines"
    assert plan["total_cost"] > 0
    # The Tier-2 pump runs off the battery: no grid slot, no price.
    pump_lines = [ln for ln in plan["allocations"] if "load:pump" in ln]
    assert pump_lines and all("from battery" in ln for ln in pump_lines)


def test_shadow_never_breaks_the_cycle():
    """A hostile fake (every attribute missing/raising) must degrade to a
    debug log — the battery pipeline continues."""
    fake = SimpleNamespace(config={}, _overnight_shadow_plan="untouched")
    SEMCoordinator._shadow_overnight_plan(
        fake, object(), energy=None, phantom_ev_kwh=0, phantom_ev_w=0,
        power=None)
    # No exception escaped; the stash was either cleared or left alone.
    assert fake._overnight_shadow_plan in (None, "untouched")


def test_no_demands_no_plan(freeze_targets, monkeypatch):
    monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                        lambda coord, energy: {})
    fake = _fake_self(devices=[])
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
    assert fake._overnight_shadow_plan is None


def test_shadow_respects_the_peak_cap(freeze_targets):
    """6 kW peak − 400 W expected home = 5.6 kW cap: the 11 kW-capable EV
    must be granted at most the cap in any slot."""
    fake = _fake_self(devices=[])
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
    plan = fake._overnight_shadow_plan
    assert plan is not None
    import re
    for line in plan["allocations"]:
        m = re.search(r"(\d+) W ", line)
        assert m and float(m.group(1)) <= 5600.0, line
