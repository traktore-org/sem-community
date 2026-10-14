"""#1083 — the simulation model: one recorded day, hour by hour, through
SEM's real battery decisions, priced with SEM's own cost rule.

Every day here is built from numbers, so each expected figure can be
checked by hand.
"""
import ast
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from custom_components.solar_energy_management.analytics.simulation.balance import (
    balance_hour,
    cost_hour,
    summarise_day,
)
from custom_components.solar_energy_management.analytics.simulation.battery_sim import (
    DEFAULTS_TAKEN,
    SimHour,
    SimParams,
    SimState,
    scheduler_rates,
    simulate_day,
    sim_config,
    synth_view,
)
from custom_components.solar_energy_management.analytics.simulation.hourly_day import (
    HourlyDay,
)
from custom_components.solar_energy_management.analytics.simulation.summary import (
    summarise,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryView,
)

ETA = math.sqrt(0.92)
DATE = "2026-10-12"
PKG = Path(__file__).resolve().parents[1] / "analytics" / "simulation"


def _day(**over):
    """A plain autumn day: night house 0.4 kWh/h, sun 08–17, prices flat
    0.30/0.08 and SOC 50 % every hour unless a test says otherwise."""
    solar = [0.0] * 24
    for h, kwh in zip(range(8, 18), (0.3, 1.0, 2.0, 3.0, 3.5, 3.5, 3.0, 2.0, 1.0, 0.3), strict=True):
        solar[h] = kwh
    base = dict(
        date=DATE, tags=["mixed"],
        solar=solar,
        home=[0.4] * 24,
        soc_pct=[50.0] * 24,
        import_rate=[0.30] * 24,
        export_rate=[0.08] * 24,
        forecast_kwh=20.0,
    )
    base.update(over)
    return HourlyDay(**base)


def _params(**over):
    base = dict(capacity_kwh=10.0, reserve_pct=10.0)
    base.update(over)
    return SimParams(**base)


def _hour(res, h):
    return res.hours[h]


# ── balance and price ───────────────────────────────────────────────


def test_balance_closes_and_names_the_losses():
    b = balance_hour(solar=3.0, grid_import=0.5, grid_export=0.2,
                     battery_charge=1.0, battery_discharge=0.0, ev=1.0)
    assert b.home_kwh == pytest.approx(3.0 + 0.5 - 1.0 - 0.2 - 1.0)
    assert b.stored_kwh == pytest.approx(ETA)
    assert b.loss_kwh == pytest.approx(1.0 - ETA)
    assert b.clamped_kwh == 0.0


def test_negative_export_priced_on_its_own():
    c = cost_hour(1.0, 2.0, 0.30, -0.05)
    assert c.import_cost == pytest.approx(0.30)
    assert c.export_revenue == pytest.approx(-0.10)     # signed, like cost_export
    assert c.net_cost == pytest.approx(0.40)             # paid to send it out
    assert c.negative_export_kwh == pytest.approx(2.0)
    assert c.negative_export_cost == pytest.approx(0.10)  # shown, not added again


def test_solar_savings_follow_the_cost_rule():
    # Production's path: solar_to_home + solar_to_ev, solar served first.
    c = cost_hour(0.5, 0.0, 0.30, 0.08, solar_kwh=1.0, home_kwh=2.0,
                  ev_kwh=1.0)
    assert c.solar_savings == pytest.approx(1.0 * 0.30)
    c = cost_hour(0.0, 2.0, 0.30, 0.08, solar_kwh=5.0, home_kwh=2.0,
                  ev_kwh=1.0)
    assert c.solar_savings == pytest.approx(3.0 * 0.30)


# ── the simulated day ───────────────────────────────────────────────


def test_balance_identity_every_hour():
    res = simulate_day(_day(ev=[0.0] * 18 + [3.0, 3.0] + [0.0] * 4),
                       _params(), {})
    for row in res.hours:
        home = (row["solar"] + row["grid_import"] + row["battery_discharge"]
                - row["ev"] - row["grid_export"] - row["battery_charge"])
        assert home == pytest.approx(row["home"], abs=1e-9)
        assert row["home"] == pytest.approx(0.4)          # the house as recorded


def test_recorded_flows_repriced_equal_the_recorded_cost():
    imp = [0.0] * 24
    exp = [0.0] * 24
    imp[2], imp[19], imp[22] = 1.2, 0.8, 0.5
    exp[12], exp[13] = 2.0, 1.5
    rin = [0.20] * 24
    rin[19] = 0.45
    rout = [0.08] * 24
    rout[13] = -0.04
    day = _day(grid_import=imp, grid_export=exp, import_rate=rin,
               export_rate=rout)
    res = simulate_day(day, _params(), {})
    by_hand = (1.2 * 0.20 + 0.8 * 0.45 + 0.5 * 0.20) - (2.0 * 0.08 + 1.5 * -0.04)
    assert round(res.actual_cost, 2) == round(by_hand, 2) == 0.60
    assert res.actual["negative_export_kwh"] == pytest.approx(1.5)
    assert res.actual["negative_export_cost"] == pytest.approx(0.06)


def test_soc_stays_within_reserve_and_capacity():
    res = simulate_day(_day(home=[1.5] * 24), _params(reserve_pct=20.0), {})
    for row in res.hours:
        assert 20.0 - 1e-9 <= row["soc_end_pct"] <= 100.0 + 1e-9
    big_sun = [4.0] * 24
    res = simulate_day(_day(solar=big_sun), _params(), {})
    assert max(r["soc_end_pct"] for r in res.hours) == pytest.approx(100.0)


def test_roundtrip_applied_both_ways():
    solar = [0.0] * 24
    solar[10] = 2.0
    home = [0.0] * 24
    home[20] = 1.0
    res = simulate_day(_day(solar=solar, home=home), _params(), {})
    up = _hour(res, 10)
    assert up["battery_charge"] == pytest.approx(2.0)
    assert (up["soc_end_pct"] - up["soc_start_pct"]) / 100 * 10 == pytest.approx(2.0 * ETA)
    down = _hour(res, 20)
    assert down["battery_discharge"] == pytest.approx(1.0)
    assert (down["soc_start_pct"] - down["soc_end_pct"]) / 100 * 10 == pytest.approx(1.0 / ETA)
    assert up["loss_kwh"] + down["loss_kwh"] == pytest.approx(
        2.0 * (1 - ETA) + 1.0 * (1 / ETA - 1))


def test_limit_discharge_hour_obeys_the_limit():
    # A car draws 6 kWh at night; the pack is above the buffer, there is no
    # sun, so SEM's real protection clamps the pack to the house.
    ev = [0.0] * 24
    ev[21] = 6.0
    res = simulate_day(_day(ev=ev, soc_pct=[90.0] * 24), _params(), {})
    row = _hour(res, 21)
    assert row["intent"] == "limit_discharge"
    assert row["battery_discharge"] <= 0.4 + 1e-9
    assert row["grid_import"] == pytest.approx(6.0 + 0.4 - row["battery_discharge"])


def test_force_charge_hour_draws_from_the_grid():
    res = simulate_day(_day(soc_pct=[20.0] * 24), _params(),
                       {"battery_mode": "force_charge"})
    row = _hour(res, 1)
    assert row["intent"] == "force_charge"
    assert row["grid_import"] > 0.4 + 1.0
    assert row["battery_charge"] == pytest.approx(row["grid_import"] - 0.4)


def test_night_scheduler_charges_in_the_planned_block():
    # Night charging on, a grey day ahead, cheap night, dear day: SEM's real
    # scheduler asks for a charge and the packed plan opens a block.
    rin = [0.10] * 6 + [0.40] * 18
    res = simulate_day(
        _day(soc_pct=[20.0] * 24, import_rate=rin, forecast_kwh=3.0,
             home=[1.0] * 24),
        _params(), {"battery_charge_scheduler_enabled": True})
    night = [r for r in res.hours if r["hour"] < 8]
    assert any(r["intent"] == "force_charge" for r in night)
    charged = sum(r["battery_charge"] for r in night if r["intent"] == "force_charge")
    assert charged > 0


def test_peak_limit_caps_the_forced_charge():
    res = simulate_day(_day(soc_pct=[20.0] * 24, home=[2.5] * 24), _params(peak_limit_kw=3.0),
                       {"battery_mode": "force_charge"})
    row = _hour(res, 1)
    assert row["intent"] == "force_charge"
    assert row["grid_import"] <= 3.0 + 1e-9
    assert row["over_limit_kwh"] == 0.0


def test_import_over_the_limit_is_reported_never_dropped():
    # The pack is at its reserve, so the house's own 5 kWh hour lands on the
    # meter: 2 kWh above a 3 kW limit, reported and still imported.
    home = [0.4] * 24
    home[2] = 5.0
    res = simulate_day(_day(home=home, soc_pct=[10.0] * 24),
                       _params(peak_limit_kw=3.0), {})
    row = _hour(res, 2)
    assert row["grid_import"] == pytest.approx(5.0)
    assert row["over_limit_kwh"] == pytest.approx(2.0)
    assert res.kwh_over_limit >= 2.0


def test_flat_and_recorded_prices_agree_when_recorded_is_flat():
    day = _day(import_rate=[0.30] * 24, export_rate=[0.08] * 24)
    rec = simulate_day(day, _params(), {})
    flat = simulate_day(day, _params(import_rate=0.30, export_rate=0.08), {})
    assert rec.simulated_cost == pytest.approx(flat.simulated_cost)
    assert rec.actual_cost == pytest.approx(flat.actual_cost)


def test_indicative_reasons_listed():
    clean = simulate_day(_day(), _params(), {})
    assert clean.indicative is False
    assert all(r in clean.indicative_reasons for r in DEFAULTS_TAKEN)

    rin = [0.30] * 24
    rin[5] = None
    soc = [50.0] * 24
    soc[3] = None
    res = simulate_day(_day(import_rate=rin, soc_pct=soc), _params(), {})
    assert res.indicative is True
    joined = " ".join(res.indicative_reasons)
    assert "price hour" in joined and "SOC hour" in joined

    gap = simulate_day(_day(tags=["grey", "gap"]), _params(), {})
    assert gap.indicative is True
    assert any("gap" in r for r in gap.indicative_reasons)


def test_synth_view_fills_the_real_view():
    cfg = sim_config({"battery_buffer_soc": 60}, _params(peak_limit_kw=4.0))
    hour = SimHour(index=20, start=datetime(2026, 10, 12, 20), solar=0.0,
                   home=0.8, ev=2.0, import_rate=0.3, export_rate=0.08)
    view = synth_view(hour, SimState(soc_kwh=5.0, last_w=-300.0), _params(peak_limit_kw=4.0), cfg)
    assert isinstance(view, BatteryView)
    assert view.runtime.last_known_soc == pytest.approx(50.0)
    assert view.runtime.last_known_w == pytest.approx(-300.0)
    assert view.config["battery_capacity_kwh"] == 10.0
    assert view.config["battery_reserve_soc"] == 10.0
    assert view.config["target_peak_limit"] == 4.0
    assert view.fleet.peak_slot_allowed_w == pytest.approx(4000.0)
    assert view.fleet.buffer_soc == 60.0
    assert view.ev_charging is True and view.ev_connected is True
    assert view.home_consumption_w == pytest.approx(800.0)
    assert view.sem_forced_charge is False


def test_same_choices_cost_the_same():
    # The recorded pack sat at 90 % all day and the house bought 0.5 kWh an
    # hour. Draining the same pack is not a saving: the energy left the pack.
    day = _day(solar=[0.0] * 24, home=[0.5] * 24, grid_import=[0.5] * 24,
               soc_pct=[90.0] * 24)
    res = simulate_day(day, _params(), {})
    assert res.simulated["grid_import"] < 12.0          # the sim did drain it
    assert res.stored_energy_value < 0
    assert res.delta == pytest.approx(0.0, abs=0.01)


def test_a_bigger_pack_gets_no_free_start_energy():
    day = _day(solar=[0.0] * 24, home=[0.5] * 24, grid_import=[0.5] * 24,
               soc_pct=[90.0] * 24)
    res = simulate_day(day, _params(capacity_kwh=20.0), {})
    assert res.delta == pytest.approx(0.0, abs=0.01)


def test_scheduler_reads_production_price_inputs():
    # Flat 0.20 with one dear hour at 19:00. Production takes the cheapest
    # 4 h of the next 12 and the mean daytime rate, not the day's max.
    rin = [0.20] * 24
    rin[19] = 0.90
    hours = [SimHour(index=h, start=datetime(2026, 10, 12, h), solar=0.0,
                     home=0.4, ev=0.0, import_rate=rin[h], export_rate=0.08)
             for h in range(24)]
    off_peak, peak, current = scheduler_rates(hours, trigger_hour=21)
    assert off_peak == pytest.approx(0.20)
    assert peak == pytest.approx((12 * 0.20 + 0.90) / 13)
    assert current == pytest.approx(0.20)


def test_one_dear_evening_hour_does_not_force_a_night_charge():
    rin = [0.20] * 24
    rin[19] = 0.90
    res = simulate_day(
        _day(soc_pct=[20.0] * 24, import_rate=rin, forecast_kwh=3.0,
             home=[1.0] * 24),
        _params(), {"battery_charge_scheduler_enabled": True,
                    "battery_cycle_cost": 0.02})
    assert not any(r["intent"] == "force_charge" for r in res.hours[:5])


def test_start_soc_lifted_to_reserve_marks_the_day():
    res = simulate_day(_day(soc_pct=[5.0] * 24), _params(reserve_pct=30.0), {})
    assert res.start_soc_pct == pytest.approx(30.0)
    assert res.indicative is True


def test_epoch_start_needs_a_time_zone():
    with pytest.raises(ValueError):
        HourlyDay.from_statistics(
            {"home": [{"start": 1760220000.0, "change": 0.4}]},
            date="2026-10-12")


# ── recorder rows ────────────────────────────────────────────────────


def test_from_statistics_reads_changes_and_means():
    tz = timezone(timedelta(hours=2))
    start = datetime(2026, 10, 12, 0, tzinfo=tz)

    def rows(values, key="change"):
        return [{"start": start + timedelta(hours=h), key: v}
                for h, v in enumerate(values)]

    solar = [0.0] * 24
    solar[12] = 3.0
    imp = [0.5] * 24
    imp[4] = -120.0                      # counter reset
    day = HourlyDay.from_statistics(
        {"solar": rows(solar), "grid_import": rows(imp),
         "grid_export": rows([0.0] * 24), "home": rows([0.5] * 24),
         "soc": rows([40.0] * 23, key="mean"),
         "import_rate": rows([0.3] * 24, key="mean"),
         "forecast": rows([18.5] * 24, key="mean")},
        date="2026-10-12", tags=["mixed"], tz=tz)
    assert day.solar[12] == 3.0
    assert day.grid_import[4] == 0.0 and 4 in day.missing_hours
    assert day.battery_charge == [0.0] * 24        # no battery role: 0, not missing
    assert day.soc_pct[23] is None and day.soc_pct[0] == 40.0
    assert day.forecast_kwh == 18.5
    assert day.missing_hours == [4]


def test_from_statistics_without_a_core_role_misses_every_hour():
    day = HourlyDay.from_statistics({}, date="2026-10-12")
    assert day.missing_hours == list(range(24))


# ── summary ─────────────────────────────────────────────────────────


def test_summary_totals_per_tag():
    sunny = simulate_day(_day(tags=["sunny", "car"]), _params(), {})
    grey = simulate_day(_day(tags=["grey"], solar=[0.0] * 24), _params(), {})
    out = summarise([sunny, grey])
    assert out["modelled"] is True
    assert [d["date"] for d in out["days"]] == [DATE, DATE]
    assert out["by_tag"]["sunny"]["days"] == 1
    assert out["by_tag"]["car"]["actual_cost"] == round(sunny.actual_cost, 2)
    assert out["by_tag"]["grey"]["simulated_cost"] == round(grey.simulated_cost, 2)
    assert out["by_tag"]["mixed"]["days"] == 0
    assert out["overall"]["days"] == 2
    assert out["overall"]["delta"] == pytest.approx(
        round(sunny.delta + grey.delta, 2), abs=0.011)


def test_summarise_day_adds_hours():
    out = summarise_day([{"grid_import": 1.0, "net_cost": 0.3},
                         {"grid_import": 0.5, "net_cost": 0.15}])
    assert out["grid_import"] == 1.5
    assert out["net_cost"] == pytest.approx(0.45)


# ── purity ──────────────────────────────────────────────────────────


def test_package_imports_no_home_assistant():
    files = sorted(PKG.glob("*.py"))
    assert len(files) >= 5
    for path in files:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                assert not name.startswith("homeassistant"), (path.name, name)
                assert "mock" not in name, (path.name, name)
            if isinstance(node, ast.Name):
                assert node.id != "hass", path.name
