"""#1083 — the Simulation tab must give back the real bill before any
what-if is believed.

PROD 14.10.2026, own settings over 30 days: actual 7.90, simulated 18.45
(+134 %). The causes, each pinned here with PROD-shaped numbers:

* the car's daily counter keeps yesterday's total past midnight and drops
  it at 07:00 — netting that step back FORWARD put a phantom charge at
  00:00 and took the real one out of the morning;
* a solar counter that booked ~0.5 kWh an hour at night (July) — the
  meters must decide each hour's net;
* a counter that jumped (144 kWh of solar in one hour) — the day says so;
* every day restarted at the recorded SOC × the NEW capacity and the
  end-of-day difference was credited daily — the pack now carries from
  day to day and its end is valued once;
* the real pack fed the car above the buffer and stopped there; the
  hourly model drained through the buffer in one step;
* the real inverter leaves a share of the house to the grid, and the
  meter buys and sells inside one hour — an hourly model that covers
  100 % and nets the hour was too good.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.solar_energy_management.analytics.day_tags import (
    CAR_MIN_KWH,
    tag_day,
)
from custom_components.solar_energy_management.analytics.simulation.battery_sim import (
    MODEL_BALANCE,
    PeriodChain,
    SimParams,
    sim_config,
    simulate_day,
    simulate_period,
    uncovered_share,
    uncovered_sums,
)
from custom_components.solar_energy_management.analytics.simulation.ev_retime import (
    ChargerLimits,
    retime,
)
from custom_components.solar_energy_management.analytics.simulation.hourly_day import (
    COUNTERS_DISAGREE,
    FLOW_ROLES,
    HourlyDay,
)
from custom_components.solar_energy_management.tools.replay import sim_accuracy

TZ = timezone(timedelta(hours=2))


def _rows(date, values, key="change"):
    day = datetime.fromisoformat(date).replace(tzinfo=TZ)
    return [{"start": (day + timedelta(hours=h)).isoformat(), key: v}
            for h, v in enumerate(values)]


def _flows(date, **over):
    """A quiet day's statistics rows; ``over`` replaces a role's 24 values."""
    base = {role: [0.0] * 24 for role in FLOW_ROLES}
    base["home"] = [0.5] * 24
    base["grid_import"] = [0.5] * 24
    base.update(over)
    rows = {role: _rows(date, vals) for role, vals in base.items()}
    rows["soc"] = _rows(date, [50.0] * 24, key="mean")
    return rows


# ── reading the counters ────────────────────────────────────────────


def test_a_late_midnight_reset_cancels_the_phantom_not_the_real_charge():
    # PROD 19.09.2026: the car counter held yesterday's 5.38 kWh past
    # midnight (+5.38 at 00:00), dropped it at 07:00 and then counted the
    # real session 09:00–14:00 (15.38 kWh).
    ev = [5.38] + [0.0] * 6 + [-5.38, 0.0, 0.01, 0.32, 2.25, 4.69, 4.84,
                                3.27] + [0.0] * 9
    day = HourlyDay.from_statistics(_flows("2026-09-19", ev=ev),
                                    date="2026-09-19", tz=TZ)
    assert day.ev[0] == 0.0
    assert day.ev[12] == pytest.approx(4.69)
    assert day.ev[9] == pytest.approx(0.01)
    assert day.total("ev") == pytest.approx(15.38)


def test_the_meters_decide_an_hours_net():
    # PROD 16.07.2026 00:00: the solar counter booked 0.51 kWh at night
    # while the pack gave 0.57 and the grid 0.06 to a 0.62 kWh house.
    solar = [0.51] + [0.0] * 23
    imp = [0.06] + [0.5] * 23
    dis = [0.57] + [0.0] * 23
    home = [0.62] + [0.5] * 23
    day = HourlyDay.from_statistics(
        _flows("2026-07-16", solar=solar, grid_import=imp,
               battery_discharge=dis, home=home),
        date="2026-07-16", tz=TZ)
    net = (day.solar[0] - day.home[0] - day.ev[0])
    meters = (day.grid_export[0] + day.battery_charge[0]
              - day.grid_import[0] - day.battery_discharge[0])
    assert net == pytest.approx(meters)
    assert day.home[0] == pytest.approx(0.51 + 0.06 + 0.57)


def test_a_counter_that_jumped_marks_the_day():
    # PROD 24.04.2026 14:00: 144 kWh of solar, 239 kWh of car in one hour.
    solar = [0.0] * 14 + [144.27] + [0.0] * 9
    ev = [0.0] * 14 + [238.51] + [0.0] * 9
    day = HourlyDay.from_statistics(_flows("2026-04-24", solar=solar, ev=ev),
                                    date="2026-04-24", tz=TZ)
    assert day.counters_disagree
    assert any(n.startswith(COUNTERS_DISAGREE) for n in day.notes)
    res = simulate_day(day, SimParams(capacity_kwh=10.0, reserve_pct=10.0), {})
    assert res.indicative


# ── one run is one pack ─────────────────────────────────────────────


def _night_day(date, soc=60.0):
    return HourlyDay(date=date, tags=["grey"], home=[0.5] * 24,
                     grid_import=[0.5] * 24, soc_pct=[soc] * 24,
                     import_rate=[0.30] * 24, export_rate=[0.08] * 24)


def test_the_pack_carries_from_day_to_day():
    cfg = {"battery_capacity_kwh": 10.0}
    params = SimParams(capacity_kwh=10.0, reserve_pct=10.0)
    run = simulate_period([_night_day("2026-10-01"), _night_day("2026-10-02")],
                          params, cfg)
    first, second = run.days
    assert second.start_soc_pct == pytest.approx(first.end_soc_pct)
    # the second day does not get the recorded 60 % back for free
    assert second.start_soc_pct < 60.0


def test_a_gap_in_the_dates_starts_from_the_record_again():
    cfg = {"battery_capacity_kwh": 10.0}
    params = SimParams(capacity_kwh=10.0, reserve_pct=10.0)
    run = simulate_period([_night_day("2026-10-01"),
                           _night_day("2026-10-05", soc=80.0)], params, cfg)
    assert run.days[1].start_soc_pct == pytest.approx(80.0)


def test_stored_energy_is_valued_once_at_the_end():
    cfg = {"battery_capacity_kwh": 10.0}
    params = SimParams(capacity_kwh=10.0, reserve_pct=10.0)
    days = [_night_day(f"2026-10-0{d}") for d in (1, 2, 3)]
    run = simulate_period(days, params, cfg)
    assert all(d.stored_energy_value == 0.0 for d in run.days)
    end = run.days[-1]
    want = (end.end_kwh - end.recorded_end_kwh) * (0.92 ** 0.5) * 0.30
    assert run.stored_energy_value == pytest.approx(want, abs=1e-3)


def test_a_bigger_pack_is_never_dearer_on_a_flat_tariff():
    # PROD: 30 kWh came out dearer than 20 kWh — impossible on a flat tariff.
    solar = [0.0] * 8 + [1.0, 2.5, 4.0, 5.0, 5.5, 5.0, 4.0, 2.5, 1.0] + [0.0] * 7
    days = []
    for d in range(1, 8):
        days.append(HourlyDay(
            date=f"2026-09-0{d}", tags=["mixed"], solar=solar,
            home=[0.6] * 24, soc_pct=[50.0] * 24,
            import_rate=[0.36] * 24, export_rate=[0.075] * 24))
    cfg = {"battery_capacity_kwh": 15.0}
    costs = []
    for cap in (15.0, 20.0, 30.0):
        run = simulate_period(days, SimParams(capacity_kwh=cap, reserve_pct=20.0),
                              cfg)
        costs.append(sum(d.simulated_cost for d in run.days)
                     - run.stored_energy_value)
    assert costs[0] >= costs[1] - 0.01 >= costs[2] - 0.02


# ── the real pack's habits ─────────────────────────────────────────


def test_the_car_takes_the_pack_only_down_to_the_buffer():
    # PROD 20.08.2026 19:00: 5.6 kWh into the car, the pack at 98 %. Live
    # SEM clamps the car at the buffer (75 %) within seconds; the hourly
    # model drained it to 63 % in one step.
    ev = [0.0] * 19 + [5.6] + [0.0] * 4
    day = HourlyDay(date="2026-08-20", tags=["mixed", "car"], ev=ev,
                    home=[0.1] * 24, soc_pct=[98.0] * 24,
                    import_rate=[0.36] * 24, export_rate=[0.075] * 24)
    cfg = {"battery_capacity_kwh": 15.0, "battery_buffer_soc": 75.0,
           "ev_chargers": [{"id": "c", "charge_mode": "solar_plus_battery"}]}
    res = simulate_day(day, SimParams(capacity_kwh=15.0, reserve_pct=20.0),
                       cfg, uncovered=0.0)
    row = res.hours[19]
    assert row["soc_end_pct"] >= 75.0 - 0.01
    assert row["grid_import"] > 3.0


def test_the_share_the_real_pack_left_to_the_grid_is_learned():
    # The real pack, well above its reserve, left 10 % of the night house
    # to the grid every hour.
    day = HourlyDay(date="2026-09-10", tags=["grey"], home=[0.6] * 24,
                    grid_import=[0.06] * 24, battery_discharge=[0.54] * 24,
                    soc_pct=[70.0] * 24, import_rate=[0.36] * 24,
                    export_rate=[0.075] * 24)
    grid, deficit = uncovered_sums(day, 20.0)
    assert uncovered_share(grid, deficit) == pytest.approx(0.10)
    res = simulate_day(day, SimParams(capacity_kwh=15.0, reserve_pct=20.0),
                       {"battery_capacity_kwh": 15.0})
    assert res.hours[2]["grid_import"] == pytest.approx(0.06, abs=1e-6)


def test_buying_and_selling_inside_one_hour_stays_as_recorded():
    imp = [0.0] * 24
    exp = [0.0] * 24
    solar = [0.0] * 24
    imp[13], exp[13], solar[13] = 0.7, 2.5, 4.0
    day = HourlyDay(date="2026-08-12", tags=["sunny"], solar=solar,
                    home=[0.5] * 24, grid_import=imp, grid_export=exp,
                    soc_pct=[100.0] * 24, import_rate=[0.36] * 24,
                    export_rate=[0.075] * 24)
    res = simulate_day(day, SimParams(capacity_kwh=15.0, reserve_pct=20.0),
                       {"battery_capacity_kwh": 15.0}, uncovered=0.0)
    assert res.hours[13]["grid_import"] >= 0.7 - 1e-9


# ── the car tag ────────────────────────────────────────────────────


@pytest.mark.parametrize(("sessions", "car"), [
    ([0.49], False),           # PROD 03.10.2026: a car that only woke up
    ([0.0], False),
    ([0.5, 0.6], True),        # two short sessions add up
    ([4.54], True),            # PROD 07.10.2026
])
def test_a_car_day_needs_real_energy(sessions, car):
    tags = tag_day(date="2026-10-03", session_kwh=sessions)
    assert tags.car is car
    assert ("car" in tags.tags) is car
    assert CAR_MIN_KWH == 1.0


# ── another charge mode ────────────────────────────────────────────

SUN = [0.0] * 9 + [2.0, 4.0, 6.0, 7.0, 7.0, 6.0, 4.0, 2.0] + [0.0] * 7
HOME = [0.5] * 24
LIMITS = ChargerLimits(min_kw=4.14, max_kw=11.0, departure_h=7, gate_kw=1.0)


def _evening_car(kwh=10.0):
    ev = [0.0] * 24
    ev[19], ev[20] = kwh / 2, kwh / 2
    return ev


def test_recorded_mode_keeps_the_car_as_it_was():
    out = retime("recorded", _evening_car(), SUN, HOME, [0.3] * 24, LIMITS)
    assert out.ev == _evening_car() and out.moved_kwh == 0.0


def test_solar_only_moves_the_car_into_the_sun():
    out = retime("solar_only", _evening_car(), SUN, HOME, [0.3] * 24, LIMITS)
    assert sum(out.ev) == pytest.approx(10.0)
    assert out.ev[19] == out.ev[20] == 0.0
    assert all(out.ev[h] == 0.0 for h in range(24) if SUN[h] - 0.5 < 4.14)
    assert out.moved_kwh == pytest.approx(10.0)
    assert out.not_delivered_kwh == 0.0


def test_what_solar_only_cannot_place_is_not_delivered():
    out = retime("solar_only", _evening_car(60.0), SUN, HOME, [0.3] * 24,
                 LIMITS)
    assert out.not_delivered_kwh > 0.0
    assert sum(out.ev) + out.not_delivered_kwh == pytest.approx(60.0)


def test_cheapest_hours_fill_the_night_before_departure():
    prices = [0.30] * 24
    prices[2] = prices[3] = 0.10
    out = retime("solar_plus_cheap", _evening_car(), [0.0] * 24, HOME, prices,
                 LIMITS)
    assert out.ev[2] > 0 and out.ev[2] + out.ev[3] == pytest.approx(10.0)


def test_always_max_starts_when_the_car_did():
    out = retime("always_max", _evening_car(), SUN, HOME, [0.3] * 24, LIMITS)
    assert out.ev[19] == pytest.approx(10.0)


def test_off_delivers_nothing():
    out = retime("off", _evening_car(), SUN, HOME, [0.3] * 24, LIMITS)
    assert sum(out.ev) == 0.0 and out.not_delivered_kwh == pytest.approx(10.0)


def test_the_charger_floor_defaults_to_six_amps_on_three_phases():
    lim = ChargerLimits.from_config({})
    assert lim.min_kw == pytest.approx(4.14)


def test_a_mode_whatif_reports_moved_and_undelivered_energy():
    day = HourlyDay(date="2026-09-01", tags=["mixed", "car"], solar=SUN,
                    home=HOME, ev=_evening_car(60.0), soc_pct=[50.0] * 24,
                    import_rate=[0.3] * 24, export_rate=[0.08] * 24)
    res = simulate_day(day, SimParams(capacity_kwh=10.0, reserve_pct=10.0,
                                      ev_mode="solar_only"), {})
    assert res.ev_moved_kwh > 0 and res.ev_not_delivered_kwh > 0
    assert res.ev_not_delivered_value == pytest.approx(
        res.ev_not_delivered_kwh * 0.3)
    assert any("not delivered" in r for r in res.indicative_reasons)


# ── another battery mode ───────────────────────────────────────────


def test_the_battery_mode_reaches_sems_decision():
    cfg = sim_config({"battery_mode": "auto"},
                     SimParams(capacity_kwh=10.0, reserve_pct=10.0,
                               battery_mode="force_charge"))
    assert cfg["battery_mode"] == "force_charge"
    day = _night_day("2026-10-01", soc=30.0)
    res = simulate_day(day, SimParams(capacity_kwh=10.0, reserve_pct=10.0,
                                      battery_mode="force_charge"), {})
    assert any(r["intent"] == "force_charge" for r in res.hours)
    assert res.simulated["grid_import"] > res.actual["grid_import"]


# ── the harness ────────────────────────────────────────────────────


def _fixture(days=3, bill_off=None):
    rows = {}
    start = datetime(2026, 9, 1, tzinfo=TZ)
    for role in FLOW_ROLES + ("soc", "import_rate", "export_rate", "cost",
                              "revenue"):
        rows[role] = []
    for d in range(days):
        day0 = start + timedelta(days=d)
        for h in range(24):
            t = (day0 + timedelta(hours=h)).isoformat()
            vals = {"solar": 0.0, "grid_import": 0.5, "grid_export": 0.0,
                    "battery_charge": 0.0, "battery_discharge": 0.0,
                    "ev": 0.0, "home": 0.5}
            for role, v in vals.items():
                rows[role].append({"start": t, "change": v})
            rows["soc"].append({"start": t, "mean": 20.0})
            rows["import_rate"].append({"start": t, "mean": 0.36})
            rows["export_rate"].append({"start": t, "mean": 0.075})
            cost = 0.5 * 0.36
            if bill_off is not None and d == bill_off and h == 0:
                cost += 5.0
            rows["cost"].append({"start": t, "change": cost})
            rows["revenue"].append({"start": t, "change": 0.0})
    return {"tz": "+02:00", "rows": rows}


def test_harness_reproduces_a_day_the_pack_could_not_change():
    fx = _fixture()
    fx["tz"] = "Europe/Zurich"
    days = sim_accuracy.load_days(fx)
    cfg = {"battery_capacity_kwh": 10.0, "battery_reserve_soc": 20.0}
    rep = sim_accuracy.measure(days, cfg)
    assert rep.total.days == 3
    assert rep.total.error_pct == pytest.approx(0.0, abs=0.5)
    assert rep.gate_met
    assert json.loads(json.dumps(rep.as_dict()))["gate_met"] is True


def test_harness_leaves_out_a_day_whose_bill_disagrees_with_its_meter():
    fx = _fixture(bill_off=1)
    fx["tz"] = "Europe/Zurich"
    days = sim_accuracy.load_days(fx)
    rep = sim_accuracy.measure(days, {"battery_capacity_kwh": 10.0})
    assert rep.total.days == 2
    assert [e["why"] for e in rep.excluded] == ["bill ≠ meter"]


def test_harness_runs_both_models():
    fx = _fixture()
    fx["tz"] = "Europe/Zurich"
    days = sim_accuracy.load_days(fx)
    rep = sim_accuracy.measure(days, {"battery_capacity_kwh": 10.0},
                               model=MODEL_BALANCE)
    assert rep.model == MODEL_BALANCE and rep.total.days == 3


def test_a_chain_restarts_after_a_gap():
    chain = PeriodChain(SimParams(capacity_kwh=10.0, reserve_pct=10.0),
                        {"battery_capacity_kwh": 10.0})
    a = chain.add(_night_day("2026-10-01"))
    b = chain.add(_night_day("2026-10-03", soc=90.0))
    assert a.start_soc_pct == pytest.approx(60.0)
    assert b.start_soc_pct == pytest.approx(90.0)
    chain.finish()
