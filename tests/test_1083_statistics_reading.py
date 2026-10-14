"""#1083 — reading a day from the recorder's hourly statistics.

The rows are two real days of one install (numbers only, rounded to
10 Wh). SEM's daily counters sometimes step back by a few Wh, and once a
counter reset late (the car's 4.53 kWh of the day before, taken back at
07:00). The old reading zeroed every such hour and called it missing:
7 to 8 hours a day, and a simulated cost 30 % above the real one.
"""
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.solar_energy_management.analytics.simulation.battery_sim import (
    SimParams,
    simulate_day,
)
from custom_components.solar_energy_management.analytics.simulation.hourly_day import (
    FLOW_ROLES,
    HourlyDay,
)

TZ = timezone(timedelta(hours=2))
IMPORT_RATE = 0.36
EXPORT_RATE = 0.075

# 7 Oct: a sunny-ish day; the car charged at 14:00 and 15:00.
DAY_1 = {
    "solar": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.02, 1.24, 2.32, 2.55, 2.98,
              3.37, 2.83, 2.4, 1.13, 1.02, 0.72, 0.07, 0.0, 0.0, 0.0, 0.0, 0.0],
    "grid_import": [0.02, 0.03, 0.03, 0.02, -0.02, 0.02, 0.02, 0.07, 0.15,
                    0.05, 0.1, 0.02, 0.0, 0.07, 0.25, 0.1, 0.04, 0.03, 0.04,
                    0.05, 0.04, -0.03, 0.03, 0.02],
    "grid_export": [0.01, 0.01, 0.02, 0.01, 0.0, 0.01, -0.03, 0.01, 0.0, 0.02,
                    -0.02, 0.01, 0.01, -0.03, 0.05, 0.01, -0.04, 0.02, 0.01,
                    -0.02, 0.01, 0.02, -0.04, 0.02],
    "battery_charge": [0.0, 0.0, 0.0, 0.05, 0.06, 0.05, 0.1, 0.06, 0.77, 1.24,
                       1.48, 2.79, 2.23, 2.21, 0.07, 0.38, 0.04, 0.05, 0.0,
                       0.1, 0.0, 0.06, 0.05, 0.0],
    "battery_discharge": [0.7, 0.74, 0.78, 0.71, 0.63, 0.75, 0.93, 0.67, 0.28,
                          0.27, 0.17, 0.0, 0.0, 0.0, 3.25, 0.37, 0.82, 1.02,
                          1.7, 1.53, 1.41, 1.07, 0.85, 0.62],
    "ev": [0.0] * 14 + [4.07, 0.46] + [0.0] * 8,
    "home": [0.71, 0.76, 0.8, 0.62, 0.55, 0.7, 0.94, 0.7, 0.9, 1.36, 1.36,
             0.2, 1.13, 0.75, 1.73, 0.74, 1.86, 1.64, 1.84, 1.46, 1.48, 0.96,
             0.85, 0.64],
    "soc": [65.91, 61.7, 57.36, 53.01, 48.7, 44.52, 39.32, 34.66, 33.01,
            36.73, 45.13, 59.86, 76.19, 90.99, 88.51, 78.06, 75.73, 70.81,
            61.9, 50.44, 42.46, 33.36, 27.42, 22.66],
}
#: the counters' own end-of-day values
TOTALS_1 = {"solar": 20.65, "grid_import": 1.15, "grid_export": 0.07,
            "battery_charge": 11.79, "battery_discharge": 19.27, "ev": 4.53,
            "home": 24.68}

# 8 Oct: grey, the pack at its floor. The car counter kept yesterday's
# 4.53 kWh past midnight and dropped it at 07:00.
DAY_2 = {
    "solar": [0.0] * 8 + [0.23, 0.28, 0.62, 0.67, 0.67, 0.5, 0.69, 0.29,
                          0.26, 0.07] + [0.0] * 6,
    "grid_import": [0.46, 0.57, 0.57, 0.6, 0.87, 0.71, 0.72, 1.3, 1.37, 1.2,
                    0.14, 0.86, 0.85, 1.25, 0.91, 0.86, 0.89, 0.97, 1.16,
                    1.44, 1.3, 1.14, 1.06, 0.69],
    "grid_export": [0.0] * 10 + [0.01] + [0.0] * 13,
    "battery_charge": [0.0] * 8 + [0.01, 0.0, 0.03, 0.0, 0.0, 0.0, 0.02,
                                   0.0, 0.0, 0.0, 0.06] + [0.0] * 5,
    "battery_discharge": [0.09] + [0.0] * 23,
    "ev": [4.53] + [0.0] * 6 + [-4.53] + [0.0] * 16,
    "home": [0.56, 0.58, 0.58, 0.57, 0.87, 0.67, 0.74, 1.31, 1.56, 1.51,
             0.74, 1.5, 1.57, 1.75, 1.5, 1.19, 1.13, 1.06, 1.07, 1.5, 1.27,
             1.15, 1.07, 0.66],
    "soc": [20.0] * 5 + [19.99] + [19.0] * 18,
}
TOTALS_2 = {"solar": 4.28, "grid_import": 21.89, "grid_export": 0.01,
            "battery_charge": 0.12, "battery_discharge": 0.09, "ev": 0.0,
            "home": 26.11}

#: the install's own settings, as the form offers them
OWN = SimParams(capacity_kwh=15.0, reserve_pct=20.0, peak_limit_kw=6.0,
                import_rate="recorded", export_rate="recorded",
                max_charge_w=5000.0, max_discharge_w=5000.0, roundtrip=0.92)
CFG = {"electricity_import_rate": IMPORT_RATE,
       "electricity_export_rate": EXPORT_RATE,
       "battery_capacity_kwh": 15.0, "target_peak_limit": 6.0}


def _rows(date, values, key="change"):
    start = datetime.fromisoformat(date).replace(tzinfo=TZ)
    return [{"start": (start + timedelta(hours=h)).timestamp(), key: v}
            for h, v in enumerate(values)]


def _read(date, raw):
    rows = {role: _rows(date, raw[role]) for role in FLOW_ROLES}
    rows["soc"] = _rows(date, raw["soc"], "mean")
    rows["import_rate"] = _rows(date, [IMPORT_RATE] * 24, "mean")
    rows["export_rate"] = _rows(date, [EXPORT_RATE] * 24, "mean")
    return HourlyDay.from_statistics(rows, date=date, tz=TZ)


DAYS = [("2026-10-07", DAY_1, TOTALS_1), ("2026-10-08", DAY_2, TOTALS_2)]


@pytest.mark.parametrize(("date", "raw", "totals"), DAYS)
def test_hours_add_up_to_the_counter(date, raw, totals):
    day = _read(date, raw)
    for role in FLOW_ROLES:
        assert day.total(role) == pytest.approx(totals[role], abs=0.01), role
        assert min(getattr(day, role)) >= 0.0, role


@pytest.mark.parametrize(("date", "raw", "totals"), DAYS)
def test_a_step_back_is_no_missing_hour(date, raw, totals):
    assert _read(date, raw).missing_hours == []


def test_small_step_backs_net_against_the_next_hour():
    day = _read("2026-10-07", DAY_1)
    assert day.grid_import[4] == 0.0
    assert day.grid_import[5] == pytest.approx(0.0)       # 0.02 − 0.02
    assert day.grid_import[6] == pytest.approx(0.02)
    assert day.notes == []


def test_a_late_reset_is_taken_back_and_said():
    day = _read("2026-10-08", DAY_2)
    assert day.ev == [0.0] * 24
    assert len(day.notes) == 1
    assert "ev" in day.notes[0] and "4.53" in day.notes[0]
    assert "07:00" in day.notes[0]
    res = simulate_day(day, OWN, CFG)
    assert res.indicative is True
    assert day.notes[0] in res.indicative_reasons
    assert not any("missing" in r for r in res.indicative_reasons)


def test_a_row_with_no_change_is_zero_not_missing():
    rows = {role: _rows("2026-10-07", DAY_1[role]) for role in FLOW_ROLES}
    rows["home"][3]["change"] = None
    day = HourlyDay.from_statistics(rows, date="2026-10-07", tz=TZ)
    assert day.home[3] == 0.0
    assert day.missing_hours == []


def test_an_absent_row_is_missing():
    rows = {role: _rows("2026-10-07", DAY_1[role]) for role in FLOW_ROLES}
    del rows["solar"][12]
    day = HourlyDay.from_statistics(rows, date="2026-10-07", tz=TZ)
    assert day.missing_hours == [12]


def test_a_day_that_steps_below_zero_stays_at_zero():
    vals = [0.1] * 24
    vals[20] = -5.0
    rows = {role: _rows("2026-10-07", vals if role == "home" else [0.0] * 24)
            for role in FLOW_ROLES}
    day = HourlyDay.from_statistics(rows, date="2026-10-07", tz=TZ)
    assert day.home == [0.0] * 24
    assert any("home" in n for n in day.notes)


@pytest.mark.parametrize(("date", "raw", "totals"), DAYS)
def test_recorded_flows_reprice_to_the_recorded_cost(date, raw, totals):
    res = simulate_day(_read(date, raw), OWN, CFG)
    want = totals["grid_import"] * IMPORT_RATE - totals["grid_export"] * EXPORT_RATE
    assert res.actual_cost == pytest.approx(want, abs=0.01)


def test_own_settings_on_a_grey_day_match_the_real_cost():
    """Pack at its floor, nothing to decide: only the hourly averaging
    is left between the simulated and the real cost."""
    res = simulate_day(_read("2026-10-08", DAY_2), OWN, CFG)
    assert res.simulated_cost == pytest.approx(res.actual_cost, rel=0.02)


def test_own_settings_over_both_days_stay_close():
    """The car day differs by one modelled choice: the simulated pack does
    not feed the car (14:00, 3.25 kWh from the pack) — that is the gap."""
    results = [simulate_day(_read(d, raw), OWN, CFG) for d, raw, _ in DAYS]
    actual = sum(r.actual_cost for r in results)
    simulated = sum(r.simulated_cost - r.stored_energy_value for r in results)
    car_gap = 3.25 * IMPORT_RATE
    assert abs(simulated - actual) <= car_gap
