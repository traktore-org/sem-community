"""(#1086) "Why now" answers from the live state when no record fits.

A record is written only when a command is SENT. A battery never commanded,
or a charger whose last command is a stop while it charges now, must answer
with the live reason, never silence or the old row.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator.decision_log import (
    KIND_BATTERY, KIND_CHARGER, KIND_LOAD, DecisionLog, current,
    current_by_kind)
from custom_components.solar_energy_management.analytics.energy_assistant import (
    EnergyAssistant)
from custom_components.solar_energy_management.analytics.pv_performance import (
    PVPerformanceAnalyzer)
from custom_components.solar_energy_management.coordinator.forecast_tracker import (
    ForecastTracker)


def _coord(data=None, battery=None):
    return SimpleNamespace(decision_log=DecisionLog(), data=data or {},
                           _last_battery_decisions=battery or {})


def _rec(c, kind, dev, verb, value=None, when=None):
    c.decision_log.record(device_id=dev, kind=kind, verb=verb, value=value,
                          reason_code="x", text="record text", now=when,
                          quiet_first_rest=False)


def _now():
    return datetime.now(timezone.utc)


def test_battery_never_commanded_answers_its_live_reason():
    c = _coord(battery={"b1": {"intent": "normal", "reason": "SOC fine"}})
    got = current(KIND_BATTERY, "b1", c)
    assert got["text"] == "SOC fine" and got["live"] is True


def test_nothing_anywhere_is_none():
    assert current(KIND_BATTERY, "b1", _coord()) is None
    assert current(KIND_LOAD, "l1", _coord()) is None


def test_charger_old_stop_but_charging_now_gives_the_live_reason():
    c = _coord({"charger_c1_strategy": "solar surplus",
                "charger_c1_commanded_current": 8.0,
                "charger_c1_power": 4100.0})
    _rec(c, KIND_CHARGER, "c1", "stop", when=_now() - timedelta(hours=1))
    got = current(KIND_CHARGER, "c1", c)
    assert got["text"] == "solar surplus" and got.get("live") is True


def test_charger_fitting_record_wins():
    c = _coord({"charger_c1_strategy": "live text",
                "charger_c1_commanded_current": 8.0})
    _rec(c, KIND_CHARGER, "c1", "charge", 8.0, when=_now())
    assert current(KIND_CHARGER, "c1", c)["text"] == "record text"


def test_charger_stop_record_and_idle_now_keeps_the_record():
    c = _coord({"charger_c1_strategy": "live text",
                "charger_c1_commanded_current": 0.0, "charger_c1_power": 0.0})
    _rec(c, KIND_CHARGER, "c1", "stop", when=_now())
    assert current(KIND_CHARGER, "c1", c)["text"] == "record text"


def test_old_record_loses_to_the_live_reason():
    c = _coord({"charger_c1_strategy": "live text"})
    _rec(c, KIND_CHARGER, "c1", "charge", 8.0, when=_now() - timedelta(hours=30))
    assert current(KIND_CHARGER, "c1", c)["text"] == "live text"


def test_battery_record_that_disagrees_with_live_intent_loses():
    c = _coord(battery={"b1": {"intent": "normal", "reason": "idle now"}})
    _rec(c, KIND_BATTERY, "b1", "force_charge", 3000.0, when=_now())
    assert current(KIND_BATTERY, "b1", c)["text"] == "idle now"


def test_load_without_live_reason_keeps_its_old_record():
    c = _coord()
    _rec(c, KIND_LOAD, "l1", "off", when=_now() - timedelta(hours=30))
    assert current(KIND_LOAD, "l1", c)["text"] == "record text"


def test_by_kind_lists_never_commanded_devices():
    c = _coord(battery={"b1": {"intent": "normal", "reason": "r1"}})
    assert set(current_by_kind(KIND_BATTERY, c)) == {"b1"}


def test_tracker_row_without_actual_is_skipped_not_zero():
    t = ForecastTracker()
    t.restore_state({"history": [
        {"date": "2026-11-01", "forecast": 12.0, "weather": "sunny"},
        {"date": "2026-11-02", "forecast": 12.0, "actual": 6.0,
         "accuracy": 50.0, "factor": 0.5, "weather": "sunny"}]})
    assert t._history[0].actual_kwh is None
    assert t._history[0].accuracy_pct is None
    assert t.accuracy_7d == 50.0          # the no-actual day is not a 0 %
    assert t._rolling_7d_factor() == 0.5  # nor a 1.0 correction


def test_pv_performance_skips_a_month_without_readings():
    a = PVPerformanceAnalyzer.__new__(PVPerformanceAnalyzer)
    a.MAX_MONTHS = 36
    a.restore_state({"monthly_history": [
        {"year": 2026, "month": 9},
        {"year": 2026, "month": 10, "total_kwh": 400.0, "specific_yield": 40.0,
         "forecast_kwh": 390.0, "performance_ratio": 102.0}]})
    assert [(r.month) for r in a._monthly_history] == [10]


def test_trend_skips_days_without_the_metric():
    ea = EnergyAssistant.__new__(EnergyAssistant)
    ea._daily_stats = [{"date": str(i), "grid_import": 5.0} for i in range(5)]
    assert ea._get_trend("never_stored") == "stable"
