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

from custom_components.solar_energy_management.coordinator import coordinator as coord_mod
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator import ev_night_targets


@pytest.fixture(autouse=True)
def _freeze_now(monkeypatch):
    """Pin the wall clock — the planner window is ``now → night_end``.

    Slot count, and therefore every energy figure derived from it, moves with
    the time of day the suite happens to run at. ``test_shadow_respects_the_
    peak_cap`` reasons about "400 W across the window vs 5 kWh above the
    floor": that is true for a 9 h night and false for a 14 h one, so it
    passed when written (just after midnight) and failed every run before
    ~18:30 local. 22:00 is the hour the real trigger fires.
    """
    fixed = datetime(2026, 7, 29, 22, 0,
                     tzinfo=coord_mod.dt_util.DEFAULT_TIME_ZONE)
    monkeypatch.setattr(coord_mod.dt_util, "now", lambda *a, **k: fixed)


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
    # No exception escaped. A hostile fake with no devices legitimately
    # reaches the LOUD no-demands answer (a dict), dies earlier (stash
    # untouched), or clears — never raises into the pipeline.
    plan = fake._overnight_shadow_plan
    assert plan in (None, "untouched") or isinstance(plan, dict)


def test_no_demands_is_a_loud_valid_answer(freeze_targets, monkeypatch):
    """'Nothing needs the night' is a 22:00 answer, not silence — a silent
    shadow is indistinguishable from a broken one (three placement bugs
    were invisible for exactly this reason)."""
    monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                        lambda coord, energy: {})
    # A READY world (a registered device — just no deficit), not the
    # zero-devices warm-up shape, which returns False and retries instead.
    idle = SimpleNamespace(device_id="pump", has_runtime_deficit=False,
                           battery_eligible_overnight=True,
                           top_up_policy="solar_only",
                           daily_min_runtime_sec=0,
                           _daily_runtime_accumulated_sec=0,
                           rated_power=800.0, priority=4)
    fake = _fake_self(devices=[idle])
    ok = SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
    assert ok is True                       # a real answer — stampable
    plan = fake._overnight_shadow_plan
    assert plan is not None
    assert plan["fits"] is True
    assert "no overnight demands" in plan["summary"][0]


def test_warmup_world_retries_not_stamps(freeze_targets, monkeypatch):
    """Zero registered devices + empty target map + no deficit = the first
    refresh after a restart (delayed rediscovery) — not an answer. The hook
    returns False so the trigger retries next cycle (caught live on TEST:
    the shadow stamped a whole night on the warm-up shape)."""
    monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                        lambda coord, energy: {})
    fake = _fake_self(devices=[])
    ok = SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
    assert ok is False
    assert fake._overnight_shadow_plan is None


def test_shadow_fires_without_the_battery_scheduler(monkeypatch):
    """Caught live on PROD (2026-07-28): the shadow was hosted inside
    ``if scheduler.enabled:`` — and the battery scheduler defaults OFF, so
    the shadow never ran on the machine it was soaking on. Pin the placement:
    ``_run_battery_pipeline`` must carry its own trigger (the ``_shadow_plan_date``
    stamp) OUTSIDE the enabled branch, and phantom=None must render as
    'scheduler off', not crash the format string."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]
           / "coordinator" / "coordinator.py").read_text()
    assert src.count("self._shadow_overnight_plan(") >= 2, \
        "expected the evaluate-site call AND the scheduler-independent trigger"
    assert "_shadow_plan_date" in src
    # The None-phantom path must not raise (the %-format regression guard).
    fake = _fake_self(devices=[])
    monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                        lambda coord, energy: {"ev_charger": 2.0})
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=None, phantom_ev_w=None, power=_power())
    assert fake._overnight_shadow_plan is not None


def test_shadow_respects_the_peak_cap(freeze_targets):
    """The ledger DERIVES the cap: while the battery carries home (8 kWh SOC,
    3 kWh floor, 400 W home), home is NOT on the meter — the full 6 kW peak
    is headroom, and no allocation may exceed it. (The old flat model
    subtracted home from every slot; the trajectory is exact.)"""
    fake = _fake_self(devices=[])
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
    plan = fake._overnight_shadow_plan
    assert plan is not None
    import re
    for line in plan["allocations"]:
        m = re.search(r"(\d+) W ", line)
        assert m and float(m.group(1)) <= 6000.0, line
    # 5 kWh above the floor covers 400 W past the window — no takeover.
    assert plan["takeover"] is None


class TestPriceLevelAt:
    """#638: the shared level-at-time accessor — the plan packs cheap-hours
    loads exactly where execution's price_is_cheap gate would fire."""

    def test_static_provider_nt_is_cheap_at_time(self):
        from datetime import datetime as _dt
        from custom_components.solar_energy_management.tariff.tariff_provider import (
            PriceLevel, StaticTariffProvider,
        )
        p = StaticTariffProvider(peak_rate=0.30, off_peak_rate=0.20,
                                 peak_start=7, peak_end=20)
        night = _dt(2026, 7, 29, 2, 0)     # Wednesday 02:00 = NT
        day = _dt(2026, 7, 29, 12, 0)      # Wednesday noon = HT
        assert p.get_price_level_at(night) == PriceLevel.CHEAP
        assert p.get_price_level_at(day) == PriceLevel.NORMAL

    def test_base_default_is_unknown(self):
        from custom_components.solar_energy_management.tariff.tariff_provider import (
            TariffProvider,
        )
        assert TariffProvider.get_price_level_at(
            MagicMock(spec=[]), None) is None


def test_soc_not_ready_retries(freeze_targets):
    """Finding #2 (PROD night 1): at the first refresh the SOC sensor was
    unavailable — None became 0 kWh and a 77%-full battery planned as empty
    (bogus 03:00 takeover). A configured battery with no SOC reading is a
    not-ready world: retry, don't plan."""
    fake = _fake_self(devices=[])
    ok = SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=0, phantom_ev_w=0, power=SimpleNamespace(battery_soc=None))
    assert ok is False
    assert fake._overnight_shadow_plan is None


def test_off_mode_load_is_not_a_demand(freeze_targets):
    """Finding #1 (PROD night 1): the off-mode heizband 'yielded' 3.1 kWh —
    but compute_load_intent never night-runs an off/peak_only device. The
    demand builder mirrors the intent gate."""
    from custom_components.solar_energy_management.devices.base import (
        DeviceControlMode,
    )
    off = _fake_load(did="heizband")
    off.control_mode = DeviceControlMode.OFF
    fake = _fake_self(devices=[off])
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(),
        phantom_ev_kwh=0, phantom_ev_w=0, power=_power())
    plan = fake._overnight_shadow_plan
    assert plan is not None
    assert not any("heizband" in ln for ln in plan.get("summary", []))
