"""#1216 — recorded history counts a battery sale as solar export.

#1191 made the live numbers take only solar's export away from solar. The
readers of recorded history still took ALL export away, because the
history they read held no split of who exported:

* the battery simulation's "actual" self-consumption (``energy_totals``),
  and its "simulated" one when the what-if pack sells;
* the estimate of months before SEM kept costs (``_estimate_month_cost``)
  and the whole-year fallback (``_seed_yearly_cost_estimate``) — which also
  paid a sold kWh as an avoided import beside its export revenue (#776);
* the yearly energy seed, which set the year's export from the recorder and
  left the battery's part beside it at what SEM had seen live.

The split exists in history since SEM published its ``battery_to_grid``
flow sensor (#776). Every reader now loads it beside the export; a period
with none of it reads as before (all export is solar's).
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.analytics.simulation.battery_sim import (
    BatteryIntent,
    SimHour,
    SimParams,
    _dispatch,
    simulate_day,
)
from custom_components.solar_energy_management.analytics.simulation.hourly_day import (
    GRID_EXPORT_BATTERY,
    HourlyDay,
)
from custom_components.solar_energy_management.coordinator import (
    energy_calculator as ec_module,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
)
from custom_components.solar_energy_management.coordinator.energy_calculator import (
    GRID_EXPORT_BATTERY_CATEGORY,
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.simulation_job import (
    SALE_ROLES,
    energy_totals,
)
from custom_components.solar_energy_management.utils.helpers import (
    BATTERY_SALE_SENSOR_KEY,
)

from .test_1083_simulation_job import _finish, _job

DATE = "2026-10-10"
TZ = timezone.utc
SALE_ENTITY = "sensor.pack_sold"        # a renamed entity: found by unique id


# ── the shared key ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_the_sale_sensor_exists_and_resets_daily():
    """The readers ask the recorder for this sensor: it must be one SEM
    publishes, a TOTAL with a daily ``last_reset`` (``flow_*``), so an
    hour's ``change`` and a month's ``sum`` delta are the energy."""
    from homeassistant.components.sensor import SensorStateClass

    from custom_components.solar_energy_management.sensor import SENSOR_TYPES
    desc = next((d for d in SENSOR_TYPES if d.key == BATTERY_SALE_SENSOR_KEY),
                None)
    assert desc is not None, BATTERY_SALE_SENSOR_KEY
    assert desc.state_class == SensorStateClass.TOTAL
    assert BATTERY_SALE_SENSOR_KEY.startswith("flow_")
    assert SALE_ROLES == {GRID_EXPORT_BATTERY: BATTERY_SALE_SENSOR_KEY}
    assert GRID_EXPORT_BATTERY == GRID_EXPORT_BATTERY_CATEGORY


# ── the simulation: one recorded day ──────────────────────────────────

#: a morning sale at 06:00 (4 kWh out of the pack, 0.5 to the house),
#: 2 kWh of sun from 09:00 to 15:00 with a 0.5 kWh house: 14 kWh of solar,
#: 10.5 of it exported, plus the 4 kWh sale
def _flows(h):
    solar = 2.0 if 9 <= h <= 15 else 0.0
    if h == 6:
        return dict(solar=0.0, grid_import=0.0, grid_export=4.0,
                    battery_charge=0.0, battery_discharge=4.5, ev=0.0,
                    home=0.5)
    return dict(solar=solar, grid_import=0.0 if solar else 0.5,
                grid_export=max(0.0, solar - 0.5), battery_charge=0.0,
                battery_discharge=0.0, ev=0.0, home=0.5)


def _role_rows(sale=True, sale_rows=None):
    day = datetime.fromisoformat(DATE).replace(tzinfo=TZ)
    rows = {}
    for role in ("solar", "grid_import", "grid_export", "battery_charge",
                 "battery_discharge", "ev", "home"):
        rows[role] = [{"start": day + timedelta(hours=h),
                       "change": _flows(h)[role]} for h in range(24)]
    rows["soc"] = [{"start": day + timedelta(hours=h), "mean": 80.0}
                   for h in range(24)]
    if sale_rows is not None:
        rows[GRID_EXPORT_BATTERY] = sale_rows
    elif sale:
        rows[GRID_EXPORT_BATTERY] = [
            {"start": day + timedelta(hours=h),
             "change": 4.0 if h == 6 else 0.0} for h in range(24)]
    return rows


CFG = {"battery_capacity_kwh": 10.0, "battery_reserve_soc": 10.0,
       "electricity_import_rate": 0.30, "electricity_export_rate": 0.08}


def _day(**kw):
    return HourlyDay.from_statistics(_role_rows(**kw), date=DATE, tz=TZ)


@pytest.mark.unit
class TestTheRecordedDay:
    def test_the_sale_is_read_as_a_part_not_a_flow(self):
        day = _day()
        assert day.sale_recorded and day.sale_known
        assert day.grid_export_battery[6] == pytest.approx(4.0)
        assert day.sale(6) == pytest.approx(4.0)
        assert day.missing_hours == [] and not day.counter_jumped
        # not in the balance: the house is untouched
        assert day.home == pytest.approx([0.5] * 24)

    def test_no_sale_rows_read_zero_and_no_missing_hour(self):
        day = _day(sale=False)
        assert day.grid_export_battery == [0.0] * 24
        assert day.missing_hours == [] and day.notes == []

    def test_the_sale_is_never_more_than_the_export(self):
        start = datetime.fromisoformat(DATE).replace(tzinfo=TZ)
        day = _day(sale_rows=[{"start": start + timedelta(hours=6),
                               "change": 9.0}])
        assert day.sale(6) == pytest.approx(4.0)
        assert day.sale(7) == 0.0

    def test_a_sale_counter_step_back_is_netted_quietly(self):
        start = datetime.fromisoformat(DATE).replace(tzinfo=TZ)
        day = _day(sale_rows=[
            {"start": start + timedelta(hours=6), "change": 4.0},
            {"start": start + timedelta(hours=8), "change": -1.0}])
        assert sum(day.grid_export_battery) == pytest.approx(3.0)
        assert min(day.grid_export_battery) >= 0.0
        assert not day.counter_jumped

    def test_actual_self_consumption_leaves_the_sale_out(self):
        """14 kWh of sun, 10.5 sent out: 25 %. The old rule took the
        14.5 kWh export away and read 0 %."""
        params = SimParams(capacity_kwh=10.0, reserve_pct=10.0)
        res = simulate_day(_day(), params, CFG)
        assert res.actual[GRID_EXPORT_BATTERY] == pytest.approx(4.0)
        e = energy_totals([res], sim_cap=10.0, real_cap=10.0)
        assert e["actual"]["grid_export_kwh"] == pytest.approx(14.5)
        assert e["actual"]["self_consumption_pct"] == pytest.approx(25.0)
        # the twin: no recorded split — all export is solar's, as before
        old = simulate_day(_day(sale=False), params, CFG)
        assert energy_totals([old], 10.0, 10.0)["actual"][
            "self_consumption_pct"] == pytest.approx(0.0)


# ── the simulation: the what-if pack sells ────────────────────────────

def _hour(solar, home):
    return SimHour(index=12, start=datetime(2026, 10, 10, 12), solar=solar,
                   home=home, ev=0.0, import_rate=0.3, export_rate=0.08)


def _sell(w):
    return BatteryDecision(battery_id="b", intent=BatteryIntent.FORCE_DISCHARGE,
                           discharge_power_w=w, floor_soc=10.0)


@pytest.mark.unit
class TestTheSimulatedSale:
    PARAMS = SimParams(capacity_kwh=10.0, reserve_pct=10.0)

    def test_a_sale_over_a_surplus_is_all_the_packs(self):
        flow, _ = _dispatch(_sell(3000.0), _hour(2.0, 0.5), 8.0, self.PARAMS)
        assert flow.grid_export == pytest.approx(4.5)
        assert flow.battery_export == pytest.approx(3.0)

    def test_a_sale_into_a_deficit_sells_what_the_house_left(self):
        flow, _ = _dispatch(_sell(3000.0), _hour(0.0, 1.0), 8.0, self.PARAMS)
        assert flow.grid_export == pytest.approx(2.0)
        assert flow.battery_export == pytest.approx(2.0)
        flow, _ = _dispatch(_sell(500.0), _hour(0.0, 1.0), 8.0, self.PARAMS)
        assert flow.grid_export == 0.0 and flow.battery_export == 0.0

    def test_self_consuming_never_sells(self):
        normal = BatteryDecision(battery_id="b", intent=BatteryIntent.NORMAL)
        flow, _ = _dispatch(normal, _hour(2.0, 0.5), 9.9, self.PARAMS)
        assert flow.grid_export > 0 and flow.battery_export == 0.0

    FORCE = SimParams(capacity_kwh=10.0, reserve_pct=10.0,
                      battery_mode="force_discharge")

    def test_a_force_discharge_what_if_counts_its_sale_apart(self):
        res = simulate_day(_day(), self.FORCE, CFG)
        s = res.simulated
        sold = s[GRID_EXPORT_BATTERY]
        assert sold > 1.0, s
        assert sold <= s["grid_export"] + 1e-9
        e = energy_totals([res], 10.0, 10.0)["simulated"]
        solar_out = s["grid_export"] - sold
        assert e["self_consumption_pct"] == pytest.approx(
            100.0 * (s["solar"] - solar_out) / s["solar"], abs=0.05)
        # the old rule read the sale as solar sent out
        old = 100.0 * max(0.0, s["solar"] - s["grid_export"]) / s["solar"]
        assert e["self_consumption_pct"] > old + 5.0

    def test_a_day_before_the_sensor_compares_on_one_rule(self):
        """The real pack discharged, the recorder has no sale rows: the
        actual side cannot split, so the simulated side does not either.
        Splitting one side only made the what-if look better (review)."""
        day = _day(sale=False)
        assert not day.sale_recorded and not day.sale_known
        res = simulate_day(day, self.FORCE, CFG)
        assert res.simulated["battery_discharge"] > 1.0
        assert res.simulated[GRID_EXPORT_BATTERY] == 0.0
        e = energy_totals([res], 10.0, 10.0)["simulated"]
        s = res.simulated
        assert e["self_consumption_pct"] == pytest.approx(
            100.0 * max(0.0, s["solar"] - s["grid_export"]) / s["solar"],
            abs=0.05)

    def test_a_day_with_no_discharge_is_known(self):
        """Nothing left the real pack (or there is none): nobody but the
        sun exported, so the what-if pack's sale is split."""
        rows = _role_rows(sale=False)
        for row in rows["battery_discharge"]:
            row["change"] = 0.0
        rows["grid_export"][6]["change"] = 0.0
        rows["grid_import"][6]["change"] = 0.5
        day = HourlyDay.from_statistics(rows, date=DATE, tz=TZ)
        assert not day.sale_recorded and day.sale_known
        res = simulate_day(day, self.FORCE, CFG)
        assert res.simulated[GRID_EXPORT_BATTERY] > 1.0


# ── the simulation: the job reads the sensor ──────────────────────────

class _Stats:
    """The recorder: every SEM sensor by ``sensor.sem_<key>``, the sale by
    a renamed entity."""

    def __init__(self, sale=True):
        self.sale = sale
        self.asked = set()

    async def __call__(self, _hass, start, end, entity_ids, types):
        self.asked |= set(entity_ids)
        rows = _role_rows(sale=self.sale)
        by_key = {"solar": "daily_solar_energy",
                  "grid_import": "daily_grid_import_energy",
                  "grid_export": "daily_grid_export_energy",
                  "battery_charge": "daily_battery_charge_energy",
                  "battery_discharge": "daily_battery_discharge_energy",
                  "ev": "daily_ev_energy", "home": "daily_home_energy",
                  "soc": "battery_soc"}
        out = {f"sensor.sem_{key}": rows[role] for role, key in by_key.items()}
        if GRID_EXPORT_BATTERY in rows:
            out[SALE_ENTITY] = rows[GRID_EXPORT_BATTERY]
        return {eid: r for eid, r in out.items() if eid in entity_ids}


def _entity(key):
    return SALE_ENTITY if key == BATTERY_SALE_SENSOR_KEY else f"sensor.sem_{key}"


def test_the_job_finds_the_sale_sensor_by_unique_id(monkeypatch):
    from types import SimpleNamespace

    from homeassistant.helpers import entity_registry as er

    from custom_components.solar_energy_management.coordinator.simulation_job import (
        SimulationJob,
    )
    monkeypatch.setattr(er, "async_get", lambda hass: _Registry(
        {f"sem_{BATTERY_SALE_SENSOR_KEY}": SALE_ENTITY,
         "sem_daily_solar_energy": "sensor.sun"}))
    job = SimulationJob(MagicMock(), SimpleNamespace(config={}),
                        read_stats=lambda *a: None)
    assert job._entity_ids() == {GRID_EXPORT_BATTERY: SALE_ENTITY,
                                 "solar": "sensor.sun"}


@pytest.mark.asyncio
@pytest.mark.parametrize("sale, pct", [(True, 25.0), (False, 0.0)])
async def test_the_run_reads_the_sale_beside_the_export(sale, pct):
    stats = _Stats(sale=sale)
    job, storage, _ = _job(tags=[{"date": DATE, "tags": ["mixed"]}],
                           stats=stats, cfg={**CFG, "simulation_tab": True})
    job._entity_id = _entity
    job.start([DATE], SimParams(capacity_kwh=10.0, reserve_pct=10.0))
    await _finish(job)
    assert SALE_ENTITY in stats.asked
    res = storage.get_simulation_runs()[0]["result"]
    assert [d["date"] for d in res["days"]] == [DATE]
    assert res["energy"]["actual"]["self_consumption_pct"] == pytest.approx(pct)


# ── the cost estimates ────────────────────────────────────────────────

YEAR = "2026"
NOW = datetime(2026, 8, 17, 12, 0, 0)


@pytest.fixture
def calc():
    c = EnergyCalculator({"electricity_import_rate": 0.30,
                          "electricity_export_rate": 0.08}, MagicMock())
    c._get_avg_import_rate = lambda: 0.30
    c._get_avg_export_rate = lambda: 0.08
    return c


#: March: 100 kWh sun, 60 exported of which the pack sold 40, 20 charged
#: from the sun, 50 discharged
MARCH = {"solar": {3: 100.0}, "grid_export": {3: 60.0},
         "battery_charge": {3: 20.0}, "battery_discharge": {3: 50.0},
         "grid_import": {3: 30.0}}


@pytest.mark.unit
class TestTheMonthEstimate:
    def test_a_recorded_sale_is_not_solar_sent_out(self, calc):
        energy = {**MARCH, GRID_EXPORT_BATTERY_CATEGORY: {3: 40.0}}
        # solar used on site: 100 − (60 − 40) − 20 = 60 kWh (old: 20)
        assert calc._estimate_month_cost(
            "cost_savings", 3, energy, 0.30, 0.08) == pytest.approx(18.0)
        # the pack delivered 50 − 40 = 10 kWh at home (old: all 50)
        assert calc._estimate_month_cost(
            "cost_batt_savings", 3, energy, 0.30, 0.08) == pytest.approx(3.0)
        # the export itself earns as before
        assert calc._estimate_month_cost(
            "cost_export", 3, energy, 0.30, 0.08) == pytest.approx(4.8)

    def test_without_a_recorded_split_as_before(self, calc):
        assert calc._estimate_month_cost(
            "cost_savings", 3, MARCH, 0.30, 0.08) == pytest.approx(6.0)
        assert calc._estimate_month_cost(
            "cost_batt_savings", 3, MARCH, 0.30, 0.08) == pytest.approx(15.0)

    def test_the_sale_is_never_more_than_the_export(self, calc):
        energy = {**MARCH, "battery_discharge": {3: 80.0},
                  GRID_EXPORT_BATTERY_CATEGORY: {3: 70.0}}
        # sold = 60 (the whole export): 100 − 0 − 20 = 80; 80 − 60 = 20
        assert calc._estimate_month_cost(
            "cost_savings", 3, energy, 0.30, 0.08) == pytest.approx(24.0)
        assert calc._estimate_month_cost(
            "cost_batt_savings", 3, energy, 0.30, 0.08) == pytest.approx(6.0)


class _Registry:
    def __init__(self, mapping):
        self.mapping = mapping

    def async_get_entity_id(self, domain, platform, unique_id):
        assert (domain, platform) == ("sensor", "solar_energy_management")
        return self.mapping.get(unique_id)


def _sum_rows(cumulative, year=2026):
    rows = []
    for m, s in cumulative:
        y, mm = (year - 1, 12) if m == 0 else (year, m)
        rows.append({"start": datetime(y, mm, 1).timestamp(), "sum": s})
    return rows


def _ed():
    cfg = MagicMock()
    cfg.solar_energy = "sensor.solar_total"
    cfg.grid_import_energy = "sensor.grid_import_total"
    cfg.grid_export_energy = "sensor.grid_export_total"
    cfg.battery_charge_energy = "sensor.batt_charge_total"
    cfg.battery_discharge_energy = "sensor.batt_discharge_total"
    cfg.device_consumption = []
    return cfg


@pytest.fixture
def env(monkeypatch):
    from homeassistant.components import recorder as recorder_mod
    from homeassistant.components.recorder import statistics as rec_stats
    from homeassistant.helpers import entity_registry as er

    state = {"registry": {}, "stats": {}, "queries": []}
    monkeypatch.setattr(ec_module.dt_util, "now", lambda: NOW)
    monkeypatch.setattr(er, "async_get", lambda hass: _Registry(state["registry"]))

    def _no_instance(hass):
        raise RuntimeError("no recorder instance in unit tests")
    monkeypatch.setattr(recorder_mod, "get_instance", _no_instance)

    def _stats(hass, start, end, ids, period, units, types):
        state["queries"].append({"ids": set(ids), "period": period})
        return {eid: rows for eid, rows in state["stats"].items() if eid in ids}
    monkeypatch.setattr(rec_stats, "statistics_during_period", _stats)
    return state


@pytest.mark.asyncio
async def test_the_month_query_loads_the_sale_by_unique_id(calc, env):
    env["registry"][f"sem_{BATTERY_SALE_SENSOR_KEY}"] = SALE_ENTITY
    env["stats"]["sensor.grid_export_total"] = _sum_rows(
        [(0, 100.0), (1, 160.0), (2, 220.0)])
    # SEM's history starts in February: no January sale, 25 kWh in February
    env["stats"][SALE_ENTITY] = _sum_rows([(2, 25.0)])
    got = await calc._query_monthly_energy(MagicMock(), _ed(), YEAR)
    assert got["grid_export"] == {1: pytest.approx(60.0), 2: pytest.approx(60.0)}
    assert got[GRID_EXPORT_BATTERY_CATEGORY] == {2: pytest.approx(25.0)}
    # not in the registry: nothing asked, no series
    env["registry"].clear()
    got = await calc._query_monthly_energy(MagicMock(), _ed(), YEAR)
    assert GRID_EXPORT_BATTERY_CATEGORY not in got
    assert SALE_ENTITY not in env["queries"][-1]["ids"]


@pytest.mark.asyncio
async def test_months_before_cost_history_leave_the_sale_out(calc, env):
    """The seed end to end: savings recorded from March, January and
    February estimated. February's 30 kWh sale stays out of solar's export
    and out of the pack's avoided import."""
    calc._yearly_seeded = True
    env["registry"].update({
        "sem_monthly_savings": "sensor.sem_monthly_savings",
        "sem_monthly_battery_savings": "sensor.sem_monthly_battery_savings",
        f"sem_{BATTERY_SALE_SENSOR_KEY}": SALE_ENTITY,
    })
    recorded = [{"start": datetime(2026, m, 1).timestamp(), "state": 10.0}
                for m in range(3, 9)]
    env["stats"]["sensor.sem_monthly_savings"] = recorded
    env["stats"]["sensor.sem_monthly_battery_savings"] = recorded
    # Jan and Feb each: 100 sun, 50 out, 40 discharged; the pack sold 30 in Feb
    for eid, per_month in (("sensor.solar_total", 100.0),
                           ("sensor.grid_export_total", 50.0),
                           ("sensor.batt_discharge_total", 40.0)):
        env["stats"][eid] = _sum_rows(
            [(0, 0.0), (1, per_month), (2, 2 * per_month)])
    env["stats"][SALE_ENTITY] = _sum_rows([(1, 0.0), (2, 30.0)])

    await calc.seed_yearly_from_statistics(MagicMock(), _ed())

    ca = calc._yearly_cost_accumulators
    # solar: Jan (100 − 50) + Feb (100 − 20) = 130 kWh × 0.30 + 6 × 10
    assert ca[f"cost_savings_{YEAR}"] == pytest.approx(39.0 + 60.0)
    # pack: Jan 40 + Feb (40 − 30) = 50 kWh × 0.30 + 6 × 10
    assert ca[f"cost_batt_savings_{YEAR}"] == pytest.approx(15.0 + 60.0)


# ── the yearly fallback and the yearly energy seed ───────────────────

def _year(calc, sale=None):
    ya = calc._yearly_accumulators
    ya.update({f"solar_{YEAR}": 1000.0, f"grid_import_{YEAR}": 300.0,
               f"grid_export_{YEAR}": 600.0, f"battery_charge_{YEAR}": 200.0,
               f"battery_discharge_{YEAR}": 350.0})
    if sale is not None:
        ya[f"{GRID_EXPORT_BATTERY_CATEGORY}_{YEAR}"] = sale


@pytest.mark.unit
class TestTheYearlyFallback:
    def test_the_years_sale_is_left_out(self, calc):
        _year(calc, sale=150.0)
        calc._seed_yearly_cost_estimate(YEAR)
        ca = calc._yearly_cost_accumulators
        # 1000 − (600 − 150) − 200 = 350 kWh; the pack 350 − 150 = 200 kWh
        assert ca[f"cost_savings_{YEAR}"] == pytest.approx(105.0)
        assert ca[f"cost_batt_savings_{YEAR}"] == pytest.approx(60.0)
        assert ca[f"cost_export_{YEAR}"] == pytest.approx(48.0)

    def test_without_the_row_as_before(self, calc):
        _year(calc)
        calc._seed_yearly_cost_estimate(YEAR)
        ca = calc._yearly_cost_accumulators
        assert ca[f"cost_savings_{YEAR}"] == pytest.approx(60.0)
        assert ca[f"cost_batt_savings_{YEAR}"] == pytest.approx(105.0)


def _span(first, last):
    return [{"start": "2026-01-01T00:00:00", "sum": first},
            {"start": "2026-08-17T11:00:00", "sum": last}]


@pytest.fixture
def seed_env(env, monkeypatch):
    """The yearly energy seed reads ``statistics_during_period`` itself."""
    import sys
    rec_stats = sys.modules["homeassistant.components.recorder.statistics"]

    def _stats(hass, start, end, ids, period, units, types):
        env["queries"].append({"ids": set(ids), "period": period})
        return {eid: rows for eid, rows in env["stats"].items() if eid in ids}
    monkeypatch.setattr(rec_stats, "statistics_during_period", _stats)
    return env


@pytest.mark.asyncio
class TestTheYearlyEnergySeed:
    async def test_the_sale_row_follows_the_seeded_export(self, calc, seed_env):
        seed_env["registry"][f"sem_{BATTERY_SALE_SENSOR_KEY}"] = SALE_ENTITY
        seed_env["stats"].update({
            "sensor.solar_total": _span(0.0, 1000.0),
            "sensor.grid_export_total": _span(100.0, 700.0),
            SALE_ENTITY: _span(5.0, 155.0),
        })
        await calc.seed_yearly_from_statistics(MagicMock(), _ed())
        ya = calc._yearly_accumulators
        assert ya[f"grid_export_{YEAR}"] == pytest.approx(600.0)
        assert ya[f"{GRID_EXPORT_BATTERY_CATEGORY}_{YEAR}"] == pytest.approx(150.0)

    async def test_never_more_than_the_export(self, calc, seed_env):
        seed_env["registry"][f"sem_{BATTERY_SALE_SENSOR_KEY}"] = SALE_ENTITY
        seed_env["stats"].update({
            "sensor.solar_total": _span(0.0, 1000.0),
            "sensor.grid_export_total": _span(0.0, 40.0),
            SALE_ENTITY: _span(0.0, 90.0),
        })
        await calc.seed_yearly_from_statistics(MagicMock(), _ed())
        assert calc._yearly_accumulators[
            f"{GRID_EXPORT_BATTERY_CATEGORY}_{YEAR}"] == pytest.approx(40.0)

    async def test_no_history_of_the_sale_keeps_what_sem_saw(self, calc, seed_env):
        calc._yearly_accumulators[f"{GRID_EXPORT_BATTERY_CATEGORY}_{YEAR}"] = 2.0
        seed_env["stats"].update({
            "sensor.solar_total": _span(0.0, 1000.0),
            "sensor.grid_export_total": _span(0.0, 600.0),
        })
        await calc.seed_yearly_from_statistics(MagicMock(), _ed())
        assert calc._yearly_accumulators[
            f"{GRID_EXPORT_BATTERY_CATEGORY}_{YEAR}"] == pytest.approx(2.0)
        assert not any(SALE_ENTITY in q["ids"] for q in seed_env["queries"])

    async def test_an_export_not_seeded_leaves_the_row(self, calc, seed_env):
        seed_env["registry"][f"sem_{BATTERY_SALE_SENSOR_KEY}"] = SALE_ENTITY
        seed_env["stats"].update({
            "sensor.solar_total": _span(0.0, 1000.0),
            SALE_ENTITY: _span(0.0, 90.0),
        })
        await calc.seed_yearly_from_statistics(MagicMock(), _ed())
        assert f"{GRID_EXPORT_BATTERY_CATEGORY}_{YEAR}" not in calc._yearly_accumulators
