"""#1245 — old battery sales still count as solar in year totals.

#1191 books the battery's sale beside the export (``grid_export_battery``).
On an install already running, its year, month and lifetime rows held only
what SEM booked since then: the yearly seed reads the sale's history (#1216)
but runs once, on a year that holds nothing yet, and the lifetime seed reads
hardware counters. Every older sale still counted as solar sent out, in the
yearly and lifetime CO2 avoided.

SEM's own ``flow_battery_to_grid_energy`` sensor (#776) holds the sale since
SEM published it. ``read_sale_history`` reads it into the three rows once:
each row only rises, never above the export beside it, after the seeds that
set that export. The lifetime row moves the ROI's SEM-era self-consumed total
by the same kWh, so the ROI does not pay those sales as pre-SEM savings.
"""
import ast
import inspect
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import (
    energy_calculator as ec_module,
)
from custom_components.solar_energy_management.coordinator import storage
from custom_components.solar_energy_management.coordinator.energy_calculator import (
    GRID_CO2_KG_PER_KWH,
    GRID_EXPORT_BATTERY_CATEGORY,
    EnergyCalculator,
    _sale_history_spans,
)
from custom_components.solar_energy_management.ha_energy_reader import (
    EnergyDashboardConfig,
)
from custom_components.solar_energy_management.utils.helpers import (
    BATTERY_SALE_SENSOR_KEY,
)

SALE = GRID_EXPORT_BATTERY_CATEGORY
SALE_ENTITY = "sensor.pack_sold"        # a renamed entity: found by unique id
NOW = datetime(2026, 10, 31, 12, 0, 0)
YEAR, MONTH = "2026", "2026_10"


class _Registry:
    def __init__(self, mapping):
        self.mapping = mapping

    def async_get_entity_id(self, domain, platform, unique_id):
        assert (domain, platform) == ("sensor", "solar_energy_management")
        return self.mapping.get(unique_id)


def _month(y, m, s):
    # noon UTC on the 1st: the same month in every zone a test runs in
    return {"start": datetime(y, m, 1, 12, tzinfo=timezone.utc).timestamp(),
            "sum": s}


#: the sensor since May 2025 (SEM 2.0): 60 kWh sold in 2025, then 150 kWh
#: this year up to the end of September, 20 more in October
HISTORY = [_month(2025, 5, 10.0), _month(2025, 12, 60.0),
           _month(2026, 1, 70.0), _month(2026, 9, 210.0),
           _month(2026, 10, 230.0)]


@pytest.fixture
def env(monkeypatch):
    from homeassistant.components import recorder as recorder_mod
    from homeassistant.components.recorder import statistics as rec_stats
    from homeassistant.helpers import entity_registry as er

    state = {"registry": {f"sem_{BATTERY_SALE_SENSOR_KEY}": SALE_ENTITY},
             "stats": {SALE_ENTITY: HISTORY}, "queries": []}
    monkeypatch.setattr(ec_module.dt_util, "now", lambda: NOW)
    monkeypatch.setattr(er, "async_get", lambda hass: _Registry(state["registry"]))

    def _no_instance(hass):
        raise RuntimeError("no recorder instance in unit tests")
    monkeypatch.setattr(recorder_mod, "get_instance", _no_instance)

    def _stats(hass, start, end, ids, period, units, types):
        state["queries"].append({"ids": set(ids), "period": period,
                                 "start": start, "types": set(types)})
        if state["stats"] is None:
            raise OSError("database is locked")
        return {eid: rows for eid, rows in state["stats"].items() if eid in ids}
    monkeypatch.setattr(rec_stats, "statistics_during_period", _stats)
    return state


def _running(rows=None):
    """An install running since 2025: both seeds done, the sale rows hold
    only what SEM booked since #1191 (5 kWh, all this month)."""
    c = EnergyCalculator({"electricity_import_rate": 0.30,
                          "electricity_export_rate": 0.08}, MagicMock())
    c._get_avg_import_rate = lambda: 0.30
    c._get_avg_export_rate = lambda: 0.08
    c._yearly_seeded = True
    c._lifetime_seeded = True
    c._yearly_accumulators.update({
        f"solar_{YEAR}": 5000.0, f"grid_export_{YEAR}": 2500.0,
        f"grid_import_{YEAR}": 1500.0, f"{SALE}_{YEAR}": 5.0})
    c._monthly_accumulators.update({
        f"solar_{MONTH}": 200.0, f"grid_export_{MONTH}": 80.0,
        f"{SALE}_{MONTH}": 5.0})
    c._lifetime_accumulators.update({
        "lifetime_solar": 40000.0, "lifetime_grid_export": 20000.0,
        "lifetime_grid_import": 12000.0, f"lifetime_{SALE}": 5.0})
    c._accumulated_self_consumed_kwh = 6000.0
    c._accumulated_export_kwh = 4000.0
    c._accumulated_grid_import_kwh = 3000.0
    c._accumulated_savings = 900.0
    if rows:
        for store, values in rows.items():
            getattr(c, store).update(values)
    return c


def _ed(**kw):
    """A dashboard whose lifetime seed can run: solar, import and export."""
    return EnergyDashboardConfig(**{
        "solar_energy": "sensor.solar_total",
        "grid_import_energy": "sensor.grid_import_total",
        "grid_export_energy": "sensor.grid_export_total", **kw})


def _costs(c):
    today = NOW.date()
    return c.calculate_costs(c._build_current_totals(today, MONTH, YEAR))


# ── the reported shape ─────────────────────────────────────────────────

@pytest.mark.asyncio
class TestTheRunningInstall:
    async def test_the_rows_take_the_history(self, env):
        c = _running()
        await c.read_sale_history(MagicMock(), _ed())
        assert c._yearly_accumulators[f"{SALE}_{YEAR}"] == pytest.approx(170.0)
        assert c._monthly_accumulators[f"{SALE}_{MONTH}"] == pytest.approx(20.0)
        assert c._lifetime_accumulators[f"lifetime_{SALE}"] == pytest.approx(230.0)
        assert c._sale_history_read is True
        assert not c.sale_history_pending
        # one query of the whole history, month rows of the sum
        (q,) = env["queries"]
        assert q["ids"] == {SALE_ENTITY} and q["period"] == "month"
        assert q["types"] == {"sum"} and q["start"].year <= 2000

    async def test_the_year_and_lifetime_co2_count_the_old_sales(self, env):
        c = _running()
        before = _costs(c)
        await c.read_sale_history(MagicMock(), _ed())
        after = _costs(c)
        # 165 kWh of this year's sale left solar's export
        assert after.yearly_co2_avoided_kg - before.yearly_co2_avoided_kg == \
            pytest.approx(165.0 * GRID_CO2_KG_PER_KWH, abs=0.1)
        assert after.lifetime_co2_avoided_kg - before.lifetime_co2_avoided_kg == \
            pytest.approx(225.0 * GRID_CO2_KG_PER_KWH, abs=0.1)
        # twin: the old rows read solar's export as the whole export bar 5 kWh
        assert before.yearly_co2_avoided_kg == pytest.approx(
            (5000.0 - (2500.0 - 5.0)) * GRID_CO2_KG_PER_KWH, abs=0.1)

    async def test_the_roi_keeps_its_figure(self, env):
        """The old sales were counted as solar's export in the SEM-era total
        too. Moving the lifetime row alone paid 225 kWh as pre-SEM savings."""
        c = _running()
        before = _costs(c).lifetime_total_savings
        await c.read_sale_history(MagicMock(), _ed())
        assert c._accumulated_self_consumed_kwh == pytest.approx(6225.0)
        assert _costs(c).lifetime_total_savings == pytest.approx(before)
        # twin: the lifetime row moved alone
        alone = _running()
        alone._lifetime_accumulators[f"lifetime_{SALE}"] = 230.0
        assert _costs(alone).lifetime_total_savings == pytest.approx(
            before + 225.0 * 0.30, abs=0.02)

    async def test_read_once(self, env):
        c = _running()
        await c.read_sale_history(MagicMock(), _ed())
        c._lifetime_accumulators[f"lifetime_{SALE}"] = 1.0
        await c.read_sale_history(MagicMock(), _ed())
        assert c._lifetime_accumulators[f"lifetime_{SALE}"] == 1.0
        assert len(env["queries"]) == 1


@pytest.mark.asyncio
class TestEachRowOnlyRises:
    async def test_never_above_the_export(self, env):
        c = _running({"_yearly_accumulators": {f"grid_export_{YEAR}": 100.0},
                      "_monthly_accumulators": {f"grid_export_{MONTH}": 12.0},
                      "_lifetime_accumulators": {"lifetime_grid_export": 150.0}})
        await c.read_sale_history(MagicMock(), _ed())
        assert c._yearly_accumulators[f"{SALE}_{YEAR}"] == pytest.approx(100.0)
        assert c._monthly_accumulators[f"{SALE}_{MONTH}"] == pytest.approx(12.0)
        assert c._lifetime_accumulators[f"lifetime_{SALE}"] == pytest.approx(150.0)
        assert c._accumulated_self_consumed_kwh == pytest.approx(6145.0)

    async def test_a_live_row_above_its_history_stays(self, env):
        """The live row also holds the meter's corrections (#1191)."""
        c = _running({"_yearly_accumulators": {f"{SALE}_{YEAR}": 400.0},
                      "_monthly_accumulators": {f"{SALE}_{MONTH}": 30.0},
                      "_lifetime_accumulators": {f"lifetime_{SALE}": 400.0}})
        await c.read_sale_history(MagicMock(), _ed())
        assert c._yearly_accumulators[f"{SALE}_{YEAR}"] == 400.0
        assert c._monthly_accumulators[f"{SALE}_{MONTH}"] == 30.0
        assert c._lifetime_accumulators[f"lifetime_{SALE}"] == 400.0
        assert c._accumulated_self_consumed_kwh == 6000.0
        assert c._sale_history_read is True

    async def test_no_history_changes_nothing(self, env):
        env["stats"] = {}
        c = _running()
        await c.read_sale_history(MagicMock(), _ed())
        assert c._yearly_accumulators[f"{SALE}_{YEAR}"] == 5.0
        assert c._lifetime_accumulators[f"lifetime_{SALE}"] == 5.0
        assert c._accumulated_self_consumed_kwh == 6000.0
        assert c._sale_history_read is True


# ── when it runs ───────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestItWaitsForTheSeeds:
    async def test_no_yearly_seed_yet_asks_nothing(self, env):
        c = _running()
        c._yearly_seeded = False
        await c.read_sale_history(MagicMock(), _ed())
        assert env["queries"] == []
        assert c._yearly_accumulators[f"{SALE}_{YEAR}"] == 5.0
        assert c.sale_history_pending

    async def test_the_lifetime_waits_for_this_starts_lifetime_seed(self, env):
        c = _running()
        c._lifetime_seeded = False
        await c.read_sale_history(MagicMock(), _ed())
        assert c._yearly_accumulators[f"{SALE}_{YEAR}"] == pytest.approx(170.0)
        assert c._lifetime_accumulators[f"lifetime_{SALE}"] == 5.0
        assert c._accumulated_self_consumed_kwh == 6000.0
        assert c.sale_history_pending and not c._sale_history_read
        # the year is done: no query each cycle while the lifetime waits
        await c.read_sale_history(MagicMock(), _ed())
        assert len(env["queries"]) == 1
        # the lifetime seed raises the export, then the row follows
        c._lifetime_accumulators["lifetime_grid_export"] = 21000.0
        c._lifetime_seeded = True
        await c.read_sale_history(MagicMock(), _ed())
        assert c._lifetime_accumulators[f"lifetime_{SALE}"] == pytest.approx(230.0)
        assert c._accumulated_self_consumed_kwh == pytest.approx(6225.0)
        assert c._sale_history_read is True

    @pytest.mark.parametrize("missing", [
        {"grid_export_energy": None},
        {"grid_export_energy": None, "grid_export_energy_list": ["meter:export"]},
        {"solar_energy": None}, {"grid_import_energy": None}])
    async def test_a_lifetime_seed_that_can_never_run_is_not_waited_for(
            self, env, missing):
        """The lifetime seed waits for solar, import and export counters that
        read (an external statistic never has a state). Without one it never
        seeds, and every lifetime row is SEM's own."""
        c = _running()
        c._lifetime_seeded = False
        ed = _ed(**missing)
        c.seed_lifetime_from_hardware(MagicMock(**{"states.get.return_value": None,
                                                   "is_running": True}), ed)
        assert c._lifetime_seeded is False
        await c.read_sale_history(MagicMock(), ed)
        assert c._lifetime_accumulators[f"lifetime_{SALE}"] == pytest.approx(230.0)
        assert c._sale_history_read is True

    async def test_without_an_energy_dashboard_it_reads_at_once(self, env):
        c = _running()
        c._yearly_seeded = c._lifetime_seeded = False
        await c.read_sale_history(MagicMock(), None)
        assert c._yearly_accumulators[f"{SALE}_{YEAR}"] == pytest.approx(170.0)
        assert c._lifetime_accumulators[f"lifetime_{SALE}"] == pytest.approx(230.0)
        assert c._sale_history_read is True

    @pytest.mark.parametrize("cause", ["no sensor", "recorder", "raises"])
    async def test_a_start_that_cannot_read_gives_up_until_the_next(
            self, env, cause, monkeypatch):
        c = _running()
        if cause == "no sensor":
            env["registry"].clear()
        elif cause == "recorder":
            env["stats"] = None
        else:
            async def _boom(*a):
                raise RuntimeError("recorder gone")
            monkeypatch.setattr(c, "_recorder_stats", _boom)
        for _ in range(3):
            assert c.sale_history_pending
            if cause == "raises":
                with pytest.raises(RuntimeError):
                    await c.read_sale_history(MagicMock(), _ed())
            else:
                await c.read_sale_history(MagicMock(), _ed())
        asked = len(env["queries"])
        await c.read_sale_history(MagicMock(), _ed())   # a 4th cycle asks nothing
        assert len(env["queries"]) == asked
        assert not c.sale_history_pending
        assert c._sale_history_read is False
        assert c._yearly_accumulators[f"{SALE}_{YEAR}"] == 5.0
        # the next start asks again
        later = _running()
        later.restore_state(c.get_state())
        assert later.sale_history_pending


# ── persistence ────────────────────────────────────────────────────────

class TestTheFlagIsKept:
    def test_it_is_in_the_store_list(self):
        assert "sale_history_read" in storage.CALCULATOR_STATE_KEYS

    @pytest.mark.asyncio
    async def test_a_restart_does_not_read_again(self, env):
        c = _running()
        await c.read_sale_history(MagicMock(), _ed())
        later = _running()
        later.restore_state(c.get_state())
        assert later._sale_history_read is True
        assert not later.sale_history_pending

    @pytest.mark.parametrize("junk", ["yes", 1, None, [True]])
    def test_junk_reads_as_not_read(self, junk):
        c = _running()
        state = c.get_state()
        state["sale_history_read"] = junk
        c.restore_state(state)
        assert c._sale_history_read is False


# ── the spans ──────────────────────────────────────────────────────────

class TestTheSpans:
    def test_year_month_and_life(self):
        assert _sale_history_spans(HISTORY, 2026, 10) == {
            "lifetime": pytest.approx(230.0), "year": pytest.approx(170.0),
            "month": pytest.approx(20.0)}

    def test_a_sensor_new_this_month_starts_from_zero(self):
        rows = [_month(2026, 10, 7.5)]
        assert _sale_history_spans(rows, 2026, 10) == {
            "lifetime": 7.5, "year": 7.5, "month": 7.5}

    def test_rows_without_a_number_and_later_rows_are_left_out(self):
        rows = [_month(2025, 12, 60.0), {**_month(2026, 3, 0.0), "sum": None},
                _month(2026, 9, float("nan")), _month(2026, 10, 90.0),
                _month(2026, 11, 999.0), {"start": None, "sum": 5.0}]
        assert _sale_history_spans(rows, 2026, 10) == {
            "lifetime": 90.0, "year": 30.0, "month": 30.0}

    def test_no_month_with_a_number(self):
        assert _sale_history_spans([], 2026, 10) is None
        assert _sale_history_spans([{"start": 1.0, "sum": None}], 2026, 10) is None

    def test_a_sum_that_fell_reads_zero(self):
        rows = [_month(2025, 12, 60.0), _month(2026, 10, 40.0)]
        assert _sale_history_spans(rows, 2026, 10)["year"] == 0.0


# ── the coordinator asks for it ───────────────────────────────────────

def test_the_cycle_reads_it_after_the_yearly_seed():
    """The cycle calls the read, gated on its pending flag, after the yearly
    seed and the lifetime seed, which set the export the rows are held
    under."""
    from custom_components.solar_energy_management.coordinator import coordinator
    tree = ast.parse(inspect.getsource(coordinator))
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        calls = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                calls[attr] = min(calls.get(attr, node.lineno), node.lineno)
        if "read_sale_history" in calls:
            break
    else:
        pytest.fail("no coordinator function calls read_sale_history")
    assert calls["seed_lifetime_from_hardware"] < calls["read_sale_history"]
    assert calls["seed_yearly_from_statistics"] < calls["read_sale_history"]
    src = ast.get_source_segment(inspect.getsource(coordinator), fn)
    assert "sale_history_pending" in src
    # a dashboard that could not be read is not "no dashboard" (#925)
    gate = src[:src.index("read_sale_history")]
    assert gate.rstrip().rfind("_ed_answered") > gate.rfind("Step 9b2")


def test_every_recorder_query_asks_energy_in_kwh():
    """Left out, the recorder hands sums in the unit each sensor's state
    shows: a Wh counter or a sensor shown in Wh reads 1000 times too high.
    Every ``statistics_during_period`` call in the package names the units."""
    import pathlib

    from custom_components.solar_energy_management.coordinator.units import (
        RECORDER_UNITS,
    )
    assert RECORDER_UNITS == {"energy": "kWh"}
    root = pathlib.Path(ec_module.__file__).resolve().parents[1]
    calls = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).parts
        if rel[0] in ("tests", "tools", "scripts"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            args = [ast.unparse(a) for a in node.args]
            name = ast.unparse(node.func)
            if name.endswith("statistics_during_period"):
                units = args[5] if len(args) > 5 else next(
                    (ast.unparse(k.value) for k in node.keywords if k.arg == "units"),
                    None)
            elif args and args[0].endswith("statistics_during_period"):
                units = args[6] if len(args) > 6 else None   # through the executor
            else:
                continue
            calls.append((str(path.relative_to(root)), node.lineno, units))
    assert len(calls) >= 6, calls
    wrong = [c for c in calls if c[2] != "RECORDER_UNITS"]
    assert not wrong, wrong


# ── a real recorder ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_real_recorder_hands_the_month_end_sums(recorder_mock, hass):
    """The read through Home Assistant's own recorder: hourly rows of the
    sensor, asked for as month rows. A month row holds the sum at its END:
    read as the first hour's sum, the history would hold 80 kWh, not 95."""
    from datetime import timedelta

    from homeassistant.components.recorder.statistics import (
        async_import_statistics,
    )
    from homeassistant.helpers import entity_registry as er
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_wait_recording_done,
    )

    entry = er.async_get(hass).async_get_or_create(
        "sensor", "solar_energy_management", f"sem_{BATTERY_SALE_SENSOR_KEY}",
        suggested_object_id="pack_sold")
    now = dt_util.now()
    hour = now.replace(minute=0, second=0, microsecond=0)
    last_year = hour.replace(year=now.year - 1, month=3, day=15, hour=12)
    rows = [(last_year, 40.0), (last_year + timedelta(days=5), 50.0),
            (hour.replace(day=1, hour=1), 80.0), (hour - timedelta(hours=2), 95.0)]
    async_import_statistics(hass, {
        "has_mean": False, "has_sum": True, "name": None, "source": "recorder",
        "statistic_id": entry.entity_id, "unit_of_measurement": "kWh"},
        [{"start": dt_util.as_utc(start), "state": s, "sum": s}
         for start, s in rows])
    await async_wait_recording_done(hass)

    c = EnergyCalculator({}, MagicMock())
    year, month = str(now.year), c._month_key(now.date())
    c._yearly_accumulators[f"grid_export_{year}"] = 1000.0
    c._monthly_accumulators[f"grid_export_{month}"] = 1000.0
    c._lifetime_accumulators["lifetime_grid_export"] = 1000.0
    await c.read_sale_history(hass, None)

    assert c._sale_history_read is True
    assert c._lifetime_accumulators[f"lifetime_{SALE}"] == pytest.approx(95.0)
    assert c._yearly_accumulators[f"{SALE}_{year}"] == pytest.approx(45.0)
    assert c._monthly_accumulators[f"{SALE}_{month}"] == pytest.approx(45.0)


@pytest.mark.asyncio
async def test_a_real_recorder_in_wh_reads_kwh(recorder_mock, hass):
    """A user may show SEM's sensor in Wh. Its history is then 12,000 Wh,
    and read without a unit it put 12,000 "kWh" into the rows — held only
    by the export."""
    from datetime import timedelta

    from homeassistant.components.recorder.statistics import (
        async_import_statistics,
    )
    from homeassistant.helpers import entity_registry as er
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_wait_recording_done,
    )

    entry = er.async_get(hass).async_get_or_create(
        "sensor", "solar_energy_management", f"sem_{BATTERY_SALE_SENSOR_KEY}",
        suggested_object_id="pack_sold")
    hass.states.async_set(entry.entity_id, "0", {"unit_of_measurement": "Wh",
                                                 "device_class": "energy",
                                                 "state_class": "total"})
    now = dt_util.now()
    hour = now.replace(minute=0, second=0, microsecond=0)
    async_import_statistics(hass, {
        "has_mean": False, "has_sum": True, "name": None, "source": "recorder",
        "statistic_id": entry.entity_id, "unit_of_measurement": "kWh"},
        [{"start": dt_util.as_utc(hour - timedelta(hours=h)), "state": s, "sum": s}
         for h, s in ((3, 0.0), (2, 12.0))])
    await async_wait_recording_done(hass)

    c = EnergyCalculator({}, MagicMock())
    c._lifetime_accumulators["lifetime_grid_export"] = 5000.0
    await c.read_sale_history(hass, None)
    assert c._lifetime_accumulators[f"lifetime_{SALE}"] == pytest.approx(12.0)
    assert c._accumulated_self_consumed_kwh == pytest.approx(12.0)
