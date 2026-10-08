"""#1068 — the day plan keeps the morning forecast when the sun does not come.

PROD 08.10.2026: forecast 18.3 kWh, real 4.3 kWh. By noon the tracker knew
(confidence 1.0) but the correction floor was 0.5 and the plan's day slots
read the raw provider remaining."""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from custom_components.solar_energy_management.coordinator.forecast_tracker import (
    ForecastTracker,
)

_NOW = ("custom_components.solar_energy_management.coordinator."
        "forecast_tracker.dt_util.now")
TZ_NOON = datetime(2026, 10, 8, 13, 0)


def _tracker(forecast_kwh: float, actual_kwh: float, now: datetime) -> ForecastTracker:
    t = ForecastTracker()
    t._today_forecast = forecast_kwh
    t._today_actual = actual_kwh
    t._correction_factor = 0.98
    t._get_sun_hours = lambda: (7.5, 18.9)
    # walk the EMA to steady state the way 5-min cycles would
    for k in range(36):
        with patch(_NOW, return_value=now - timedelta(minutes=5 * (36 - k))):
            t._calculate_dampening_factor()
    return t


def test_prod_day_noon_corrects_below_half():
    # 13:00, 5.5 sun-hours of 11.4: expected ≈ 47 % of 18.3 = 8.6 kWh,
    # measured 3.0 kWh → ratio ≈ 0.35. The 0.5 floor hid that.
    t = _tracker(18.3, 3.0, TZ_NOON)
    with patch(_NOW, return_value=TZ_NOON):
        rem = t.corrected_remaining_kwh(7.1)   # provider's raw remaining
    assert rem < 7.1 * 0.4


def test_published_dampening_factor_is_unchanged():
    # Asleep means asleep: the existing sensor and the surplus outlook keep
    # the 0.5 floor; only the new accessor reads the evidenced floor.
    t = _tracker(18.3, 3.0, TZ_NOON)
    with patch(_NOW, return_value=TZ_NOON):
        assert t.dampening_factor == pytest.approx(0.5)


def test_dawn_keeps_the_noise_floor():
    # 08:30: little expected yet — the 0.5 floor still applies.
    t = _tracker(18.3, 0.05, datetime(2026, 10, 8, 8, 30))
    with patch(_NOW, return_value=datetime(2026, 10, 8, 8, 30)):
        assert t.corrected_remaining_kwh(18.0) >= 18.0 * 0.5


def test_sunny_beat_still_capped_high():
    t = _tracker(10.0, 9.0, TZ_NOON)
    with patch(_NOW, return_value=TZ_NOON):
        assert t.corrected_remaining_kwh(4.0) <= 4.0 * 1.5


def test_zero_and_garbage_stay_safe():
    t = _tracker(18.3, 3.0, TZ_NOON)
    with patch(_NOW, return_value=TZ_NOON):
        assert t.corrected_remaining_kwh(0) == 0.0
        assert t.corrected_remaining_kwh(None) == 0.0
        assert t.corrected_remaining_kwh("x") == 0.0


# ── Task 3: the plan's day reads the corrected remaining (soak flag) ──
from types import SimpleNamespace  # noqa: E402

from custom_components.solar_energy_management.consts.core import (  # noqa: E402
    CONF_INTRADAY_FORECAST,
)
from custom_components.solar_energy_management.coordinator.coordinator import (  # noqa: E402
    SEMCoordinator,
)


def _coord(flag, remaining=7.1, tracker=None):
    c = SEMCoordinator.__new__(SEMCoordinator)
    c.config = {CONF_INTRADAY_FORECAST: True} if flag else {}
    c._forecast_reader = SimpleNamespace(forecast_data=SimpleNamespace(
        forecast_today_kwh=18.3, forecast_remaining_today_kwh=remaining,
        forecast_tomorrow_kwh=22.1))
    c._forecast_tracker = tracker or _tracker(18.3, 3.0, TZ_NOON)
    return c


def test_flag_off_is_todays_behaviour():
    c = _coord(flag=False)
    with patch(_NOW, return_value=TZ_NOON):
        assert c._plan_day_remaining_kwh() == 7.1


def test_day_slots_follow_measured_yield():
    c = _coord(flag=True)
    with patch(_NOW, return_value=TZ_NOON):
        rem = c._plan_day_remaining_kwh()
    assert rem == pytest.approx(7.1 * 0.35, abs=0.4)


def test_the_signature_reads_the_same_helper():
    """The anchor watches what the plan reads: with the flag on, a grey
    noon re-anchors on the corrected number, not the provider's."""
    c = _coord(flag=True)
    with patch(_NOW, return_value=TZ_NOON):
        sig = dict(t for t in c._energy_plan_demand_signature(
            SimpleNamespace(ev_connected=False, ev_connected_per_charger=None))
            if isinstance(t, tuple) and len(t) == 2
            and t[0] in ("solar", "solar_tomorrow"))
        expected = round(c._plan_day_remaining_kwh() / 2.0) * 2.0
    assert sig["solar"] == expected


def test_both_day_readers_go_through_the_one_helper():
    """No second derivation: the slot builder and the signature both read
    the remaining via ``_plan_day_remaining_kwh`` (AST)."""
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "coordinator"
           / "coordinator.py").read_text()
    tree = ast.parse(src)
    fns = {n.name: n for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for name in ("_energy_plan_demand_signature", "_shadow_energy_plan"):
        body = ast.unparse(fns[name])
        assert "plan_day_remaining_kwh(self)" in body, name
        assert "forecast_remaining_today_kwh" not in body, (
            f"{name} reads the raw remaining directly (#1068)")


# ── Task 4: same decision, fresh trajectory ──
from custom_components.solar_energy_management.coordinator.coordinator import (  # noqa: E402
    keep_decision_take_trajectory, plan_decision_core,
)


def _plan(stamp, grid_w):
    return {
        "computed_at": stamp, "fits": True, "total_cost": None,
        "takeover": None, "demands": [], "blocks": [], "not_scheduled": [],
        "arbitrage": None, "battery_fleet_partial": None,
        "slots": [{"start": "2026-10-08T14:00:00+02:00",
                   "end": "2026-10-08T15:00:00+02:00",
                   "home_grid_w": grid_w}],
        "self_consumption": {"share": 1.0 if grid_w == 0 else 0.3},
        "summary": ["sky"], "forecast_sell": None,
    }


def test_an_unchanged_decision_keeps_its_stamp_and_takes_the_sky():
    prev = _plan("2026-10-08T09:02:43+02:00", 0.0)
    fresh = _plan("2026-10-08T13:00:00+02:00", 950.0)
    kept = keep_decision_take_trajectory(prev, fresh,
                                         "2026-10-08T13:00:00+02:00")
    assert kept["computed_at"] == prev["computed_at"]          # #775 holds
    assert kept["slots"][0]["home_grid_w"] == 950.0            # the sky
    assert kept["self_consumption"] == fresh["self_consumption"]
    assert kept["trajectory_at"] == "2026-10-08T13:00:00+02:00"
    assert plan_decision_core(kept) == plan_decision_core(prev)
    assert prev["slots"][0]["home_grid_w"] == 0.0              # no mutation


def test_the_775_branch_uses_it_only_under_the_flag():
    """Asleep means asleep: the fresh trajectory is taken only inside an
    ``if intraday_forecast_on(self)``; its ``else`` restores the outgoing
    plan exactly as before (AST)."""
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).resolve().parents[1] / "coordinator"
                      / "coordinator.py").read_text())

    def _calls(node, name):
        return any(isinstance(n, ast.Call)
                   and getattr(n.func, "id", getattr(n.func, "attr", "")) == name
                   for n in ast.walk(node))

    parent = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            parent[c] = n
    sites = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "keep_decision_take_trajectory"]
    assert sites, "no call"
    for call in sites:
        node, gate = call, None
        while node in parent:
            up = parent[node]
            if (isinstance(up, ast.If) and node in up.body
                    and _calls(up.test, "intraday_forecast_on")):
                gate = up
                break
            node = up
        assert gate is not None, "the fresh trajectory is taken ungated"
        restores = [n for n in ast.walk(ast.Module(body=gate.orelse, type_ignores=[]))
                    if isinstance(n, ast.Assign)
                    and getattr(n.value, "id", "") == "_prev_plan_775"]
        assert restores, "the else must restore the outgoing plan"


# ── Task 5: the remaining sensor says the corrected value ──
def test_remaining_sensor_shows_corrected_beside_raw(mock_coordinator):
    from custom_components.solar_energy_management.sensor import (
        SEMSolarSensor, SENSOR_TYPES,
    )
    desc = next(d for d in SENSOR_TYPES
                if d.key == "forecast_remaining_today_kwh")
    mock_coordinator.data = dict(mock_coordinator.data)
    mock_coordinator.data.update({
        "forecast_remaining_today_kwh": 7.1,
        "forecast_corrected_factor": 0.3,
        "forecast_corrected_floor": 0.1,
        "forecast_dampening_path": "blended_live+clamped_low",
    })
    s = SEMSolarSensor(coordinator=mock_coordinator, description=desc,
                       entry_id="e")
    attrs = s.extra_state_attributes
    assert attrs["corrected_kwh"] == 2.13
    assert attrs["correction_floor"] == 0.1
    assert attrs["correction_path"] == "blended_live+clamped_low"
    assert attrs["intraday_forecast"] is False


def test_tracker_publishes_the_corrected_factor():
    t = _tracker(18.3, 3.0, TZ_NOON)
    with patch(_NOW, return_value=TZ_NOON):
        d = t.get_data()
    assert d["forecast_corrected_factor"] < 0.4
    assert d["forecast_corrected_floor"] == 0.1
    assert d["forecast_dampening_factor"] == 0.5
