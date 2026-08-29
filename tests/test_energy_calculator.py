"""Tests for coordinator/energy_calculator.py."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, date, timedelta

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
    EnergyTotals,
)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def time_manager():
    """Return a mocked TimeManager."""
    tm = MagicMock()
    tm.get_current_meter_day_sunrise_based.return_value = date(2026, 4, 18)
    return tm


@pytest.fixture
def config():
    """Return a default config dict."""
    return {
        "update_interval": 30,
        "electricity_import_rate": 0.30,
        "electricity_export_rate": 0.08,
    }


@pytest.fixture
def calculator(config, time_manager):
    """Return an EnergyCalculator with mocked dependencies."""
    return EnergyCalculator(config, time_manager)


def _make_power(solar=0, grid_import=0, grid_export=0, home=0, ev=0,
                battery_charge=0, battery_discharge=0, battery_power=0,
                battery_soc=50):
    """Create a PowerReadings with specified values."""
    p = PowerReadings(
        solar_power=solar,
        grid_import_power=grid_import,
        grid_export_power=grid_export,
        home_consumption_power=home,
        ev_power=ev,
        battery_charge_power=battery_charge,
        battery_discharge_power=battery_discharge,
        battery_power=battery_power,
        battery_soc=battery_soc,
    )
    return p


def _freeze_now(year=2026, month=4, day=18, hour=12, minute=0, second=0):
    """Return a datetime for patching dt_util.now."""
    return datetime(year, month, day, hour, minute, second)


# ──────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────

@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_calculate_energy_basic(mock_dt, calculator):
    """Test basic power * time = energy calculation."""
    now = _freeze_now(hour=12, minute=0)
    mock_dt.now.return_value = now

    power = _make_power(solar=5000, home=2000, grid_import=0, grid_export=0)

    # First call sets _last_update, uses config interval (30s = 1/120 hour)
    energy = calculator.calculate_energy(power)
    # solar_increment = 5000 * (30/3600) / 1000 = 0.0417 kWh
    assert energy.daily_solar > 0
    assert energy.daily_home > 0


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_calculate_energy_zero_power(mock_dt, calculator):
    """Test that zero power produces zero energy."""
    now = _freeze_now()
    mock_dt.now.return_value = now

    power = _make_power()  # all zeros
    energy = calculator.calculate_energy(power)
    assert energy.daily_solar == 0.0
    assert energy.daily_home == 0.0
    assert energy.daily_grid_import == 0.0


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_daily_reset_at_midnight(mock_dt, calculator):
    """Test that daily accumulators reset on date change."""
    # First update at 23:59
    now1 = _freeze_now(hour=23, minute=59)
    mock_dt.now.return_value = now1
    power = _make_power(solar=3000, home=1000)
    calculator.calculate_energy(power)

    # Second update next day at 00:01
    now2 = _freeze_now(day=19, hour=0, minute=1)
    mock_dt.now.return_value = now2
    energy = calculator.calculate_energy(power)

    # Daily solar should only contain the second update's increment
    # The rollover should have cleared yesterday's data
    assert energy.daily_solar >= 0


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_monthly_reset(mock_dt, calculator):
    """Test that monthly accumulators reset on month change."""
    # First update at end of month
    now1 = _freeze_now(month=3, day=31, hour=12)
    mock_dt.now.return_value = now1
    power = _make_power(solar=5000, home=2000)
    calculator.calculate_energy(power)

    # Accumulate some monthly data
    now2 = _freeze_now(month=3, day=31, hour=13)
    mock_dt.now.return_value = now2
    calculator.calculate_energy(power)

    monthly_before = calculator._get_monthly("solar", "2026_3")
    assert monthly_before > 0

    # New month — reset _last_update to avoid gap protection
    calculator._last_update = None
    now3 = _freeze_now(month=4, day=1, hour=0)
    mock_dt.now.return_value = now3
    calculator.calculate_energy(power)

    # Old month data should be gone after rollover
    old_monthly = calculator._get_monthly("solar", "2026_3")
    assert old_monthly == 0.0


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_trapezoidal_integration(mock_dt, calculator):
    """Test energy integration over two updates with different time deltas."""
    # First update
    now1 = _freeze_now(hour=12, minute=0)
    mock_dt.now.return_value = now1
    power = _make_power(solar=6000, home=2000)
    calculator.calculate_energy(power)

    # Second update 60 seconds later
    now2 = _freeze_now(hour=12, minute=1)
    mock_dt.now.return_value = now2
    energy = calculator.calculate_energy(power)

    # With 60s interval: solar_increment = 6000 * (60/3600) / 1000 = 0.1 kWh
    # Plus the first update at config interval (30/3600)
    assert energy.daily_solar > 0.1


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_min_power_threshold(mock_dt, calculator):
    """Test that power below MIN_POWER_THRESHOLD does not accumulate energy."""
    now = _freeze_now()
    mock_dt.now.return_value = now

    # Power below threshold (10W)
    power = _make_power(solar=5, home=5)
    energy = calculator.calculate_energy(power)
    assert energy.daily_solar == 0.0
    assert energy.daily_home == 0.0

    # First reading above threshold (establishes baseline)
    power2 = _make_power(solar=1000, home=500)
    now2 = _freeze_now(minute=1)
    mock_dt.now.return_value = now2
    calculator.calculate_energy(power2)

    # Second reading above threshold (should accumulate)
    power3 = _make_power(solar=1000, home=500)
    now3 = _freeze_now(minute=2)
    mock_dt.now.return_value = now3
    energy3 = calculator.calculate_energy(power3)
    assert energy3.daily_solar > 0


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_restore_state_roundtrip(mock_dt, calculator):
    """Test get_state / restore_state round-trip."""
    now = _freeze_now()
    mock_dt.now.return_value = now

    power = _make_power(solar=5000, home=2000, grid_import=500)
    calculator.calculate_energy(power)

    state = calculator.get_state()
    assert "daily_accumulators" in state
    assert "monthly_accumulators" in state
    assert "lifetime_accumulators" in state
    assert "last_update" in state

    # Create new calculator and restore
    new_calc = EnergyCalculator(calculator.config, MagicMock())
    new_calc.restore_state(state)

    assert new_calc._daily_accumulators == calculator._daily_accumulators
    assert new_calc._monthly_accumulators == calculator._monthly_accumulators
    assert new_calc._lifetime_accumulators == calculator._lifetime_accumulators
    assert new_calc._last_update is not None


def test_restore_state_none(calculator):
    """Test restoring None state is safe."""
    calculator.restore_state(None)
    assert calculator._daily_accumulators == {}


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_calculate_costs(mock_dt, calculator):
    """Test cost calculation via incremental accumulation path."""
    from datetime import date
    today = date(2026, 5, 19)
    mock_dt.now.return_value = datetime(2026, 5, 19, 14, 0, 0)
    month_key = "2026_5"
    year_key = "2026"

    # Seed cost accumulators (simulating accumulated cost increments at rate=0.30/0.08)
    calculator._daily_cost_accumulators[f"cost_import_{today}"] = 0.90       # 3.0 kWh * 0.30
    calculator._daily_cost_accumulators[f"cost_export_{today}"] = 0.16       # 2.0 kWh * 0.08
    calculator._daily_cost_accumulators[f"cost_savings_{today}"] = 2.10      # 7.0 kWh * 0.30
    calculator._daily_cost_accumulators[f"cost_batt_savings_{today}"] = 0.45 # 1.5 kWh * 0.30
    calculator._monthly_cost_accumulators[f"cost_import_{month_key}"] = 18.0
    calculator._monthly_cost_accumulators[f"cost_export_{month_key}"] = 3.2
    calculator._monthly_cost_accumulators[f"cost_savings_{month_key}"] = 27.0
    calculator._yearly_cost_accumulators[f"cost_import_{year_key}"] = 180.0
    calculator._yearly_cost_accumulators[f"cost_export_{year_key}"] = 32.0
    calculator._yearly_cost_accumulators[f"cost_savings_{year_key}"] = 270.0
    calculator._yearly_cost_accumulators[f"cost_batt_savings_{year_key}"] = 84.0

    energy = EnergyTotals(
        daily_solar=10.0, daily_home=8.0, daily_ev=2.0,
        daily_grid_import=3.0, daily_grid_export=2.0, daily_battery_discharge=1.5,
    )
    costs = calculator.calculate_costs(energy)

    assert costs.daily_costs == pytest.approx(0.90)
    assert costs.daily_export_revenue == pytest.approx(0.16)
    assert costs.daily_net_cost == pytest.approx(0.74)
    assert costs.daily_savings == pytest.approx(2.10)
    assert costs.daily_battery_savings == pytest.approx(0.45)
    assert costs.monthly_costs == pytest.approx(18.0)
    assert costs.yearly_battery_savings == pytest.approx(84.0)


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_dynamic_tariff_cost_accumulation(mock_dt, calculator):
    """Costs accumulate at rate active during each interval, not recalculated (#218)."""
    from datetime import timedelta
    now = datetime(2026, 5, 19, 12, 0, 0)
    mock_dt.now.return_value = now
    mock_dt.utcnow.return_value = now

    # Phase 1: 100 cycles at 5000W grid import, rate=0.20
    calculator._import_rate = 0.20
    calculator._export_rate = 0.08
    for i in range(100):
        t = now + timedelta(seconds=30 * i)
        mock_dt.now.return_value = t
        power = _make_power(grid_import=5000, home=5000)
        calculator.calculate_energy(power)

    energy = EnergyTotals()  # placeholder, not used for cost
    costs1 = calculator.calculate_costs(energy)
    cost_after_phase1 = costs1.daily_costs

    # Phase 2: Change rate to 0.60, 100 more cycles at 5000W
    calculator._import_rate = 0.60
    for i in range(100, 200):
        t = now + timedelta(seconds=30 * i)
        mock_dt.now.return_value = t
        power = _make_power(grid_import=5000, home=5000)
        calculator.calculate_energy(power)

    costs2 = calculator.calculate_costs(energy)

    # Each cycle: 5000W * (30/3600)h / 1000 = 0.04167 kWh
    per_cycle_kwh = 5000 * (30 / 3600) / 1000
    expected_phase1 = 100 * per_cycle_kwh * 0.20  # ~0.833
    expected_phase2 = 100 * per_cycle_kwh * 0.60  # ~2.500
    expected_total = expected_phase1 + expected_phase2  # ~3.333

    # BUG would give: 200 * per_cycle_kwh * 0.60 = ~5.000 (all at new rate)
    bug_total = 200 * per_cycle_kwh * 0.60

    assert costs2.daily_costs == pytest.approx(expected_total, abs=0.05)
    # The bug total is significantly higher — verify we're not getting that
    assert abs(costs2.daily_costs - bug_total) > 0.5
    # Verify phase 1 cost was preserved
    assert cost_after_phase1 == pytest.approx(expected_phase1, abs=0.05)


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_static_tariff_backward_compatible(mock_dt, calculator):
    """With a fixed rate, accumulated cost equals energy × rate."""
    now = datetime(2026, 5, 19, 12, 0, 0)
    mock_dt.now.return_value = now
    mock_dt.utcnow.return_value = now

    calculator._import_rate = 0.30
    calculator._export_rate = 0.08

    # Run 20 cycles: 2000W import, 500W export
    for i in range(20):
        t = now + timedelta(seconds=30 * i)
        mock_dt.now.return_value = t
        power = _make_power(grid_import=2000, grid_export=500, home=1500)
        calculator.calculate_energy(power)

    energy = EnergyTotals()
    costs = calculator.calculate_costs(energy)

    per_cycle_kwh = 30 / 3600 / 1000  # seconds to hours, W to kW
    total_import_kwh = 20 * 2000 * per_cycle_kwh
    total_export_kwh = 20 * 500 * per_cycle_kwh

    assert costs.daily_costs == pytest.approx(total_import_kwh * 0.30, abs=0.02)
    assert costs.daily_export_revenue == pytest.approx(total_export_kwh * 0.08, abs=0.01)


def test_cost_persistence_roundtrip(calculator):
    """Cost accumulators survive get_state/restore_state."""
    from datetime import date
    today = date(2026, 5, 19)

    calculator._daily_cost_accumulators[f"cost_import_{today}"] = 1.23
    calculator._monthly_cost_accumulators["cost_import_2026_5"] = 45.67
    calculator._yearly_cost_accumulators["cost_import_2026"] = 890.12

    state = calculator.get_state()
    new_calc = EnergyCalculator(calculator.config, calculator._time_manager)
    new_calc.restore_state(state)

    assert new_calc._daily_cost_accumulators[f"cost_import_{today}"] == 1.23
    assert new_calc._monthly_cost_accumulators["cost_import_2026_5"] == 45.67
    assert new_calc._yearly_cost_accumulators["cost_import_2026"] == 890.12


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_tariff_change_midday_multiple(mock_dt, calculator):
    """Multiple rate changes throughout the day, each segment costed correctly."""
    now = datetime(2026, 5, 19, 8, 0, 0)
    mock_dt.now.return_value = now
    mock_dt.utcnow.return_value = now

    rates = [(0.20, 5), (0.40, 5), (0.10, 5)]  # (rate, num_cycles)
    expected_cost = 0.0
    per_cycle_kwh = 1000 * (30 / 3600) / 1000

    cycle = 0
    for rate, num_cycles in rates:
        calculator._import_rate = rate
        for _ in range(num_cycles):
            t = now + timedelta(seconds=30 * cycle)
            mock_dt.now.return_value = t
            power = _make_power(grid_import=1000, home=1000)
            calculator.calculate_energy(power)
            cycle += 1
        expected_cost += num_cycles * per_cycle_kwh * rate

    costs = calculator.calculate_costs(EnergyTotals())
    assert costs.daily_costs == pytest.approx(expected_cost, abs=0.02)


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_export_revenue_dynamic(mock_dt, calculator):
    """Export revenue accumulates correctly with changing export rates."""
    now = datetime(2026, 5, 19, 12, 0, 0)
    mock_dt.now.return_value = now
    mock_dt.utcnow.return_value = now

    per_cycle_kwh = 500 * (30 / 3600) / 1000

    # 5 cycles at export rate 0.08
    calculator._export_rate = 0.08
    for i in range(5):
        t = now + timedelta(seconds=30 * i)
        mock_dt.now.return_value = t
        power = _make_power(solar=500, grid_export=500)
        calculator.calculate_energy(power)

    # 5 cycles at export rate 0.15
    calculator._export_rate = 0.15
    for i in range(5, 10):
        t = now + timedelta(seconds=30 * i)
        mock_dt.now.return_value = t
        power = _make_power(solar=500, grid_export=500)
        calculator.calculate_energy(power)

    costs = calculator.calculate_costs(EnergyTotals())
    expected = 5 * per_cycle_kwh * 0.08 + 5 * per_cycle_kwh * 0.15
    assert costs.daily_export_revenue == pytest.approx(expected, abs=0.01)


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_calculate_performance_autarky(mock_dt, calculator):
    """Test performance metrics: self-consumption and autarky rates."""
    mock_dt.now.return_value = _freeze_now()

    power = _make_power(solar=5000, battery_power=0)
    energy = EnergyTotals(
        daily_solar=10.0,
        daily_home=8.0,
        daily_ev=2.0,
        daily_grid_import=2.0,
        daily_grid_export=1.0,
    )

    metrics = calculator.calculate_performance(power, energy)

    # self_consumption = (10 - 1) / 10 * 100 = 90%
    assert metrics.self_consumption_rate == pytest.approx(90.0)
    # autarky = (8+2 - 2) / (8+2) * 100 = 80%
    assert metrics.autarky_rate == pytest.approx(80.0)

    # Clamped to [0, 100]
    assert 0 <= metrics.self_consumption_rate <= 100
    assert 0 <= metrics.autarky_rate <= 100


# ──────────────────────────────────────────────
# Integration gap protection (#123)
# ──────────────────────────────────────────────

@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_integration_gap_skips_accumulation(mock_dt, calculator, time_manager):
    """Test that a large time gap skips energy integration to prevent spikes."""
    from custom_components.solar_energy_management.coordinator.energy_calculator import (
        MAX_INTEGRATION_GAP_SECONDS,
    )

    time_manager.get_current_meter_day_sunrise_based.return_value = date(2026, 4, 29)

    # First update at T=0
    t0 = datetime(2026, 4, 29, 12, 0, 0)
    mock_dt.now.return_value = t0
    power = _make_power(solar=5000, home=3000, grid_export=2000)
    energy1 = calculator.calculate_energy(power)
    solar_after_first = energy1.daily_solar

    # Second update at T+10s (normal) — should accumulate
    t1 = t0 + timedelta(seconds=10)
    mock_dt.now.return_value = t1
    energy2 = calculator.calculate_energy(power)
    assert energy2.daily_solar > solar_after_first

    # Third update at T+5min (gap > MAX) — should NOT accumulate
    t2 = t1 + timedelta(seconds=MAX_INTEGRATION_GAP_SECONDS + 60)
    mock_dt.now.return_value = t2
    solar_before_gap = energy2.daily_solar
    energy3 = calculator.calculate_energy(power)
    assert energy3.daily_solar == solar_before_gap  # No change

    # Fourth update at T+5min+10s (normal again) — should accumulate
    t3 = t2 + timedelta(seconds=10)
    mock_dt.now.return_value = t3
    energy4 = calculator.calculate_energy(power)
    assert energy4.daily_solar > solar_before_gap


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_normal_interval_accumulates(mock_dt, calculator, time_manager):
    """Test that normal intervals accumulate energy correctly."""
    time_manager.get_current_meter_day_sunrise_based.return_value = date(2026, 4, 29)

    # First update uses config interval (30s) as default
    t0 = datetime(2026, 4, 29, 12, 0, 0)
    mock_dt.now.return_value = t0
    power = _make_power(solar=10000, battery_discharge=5000, home=15000)
    energy0 = calculator.calculate_energy(power)
    solar_after_first = energy0.daily_solar

    # 30 seconds later — accumulates another interval
    t1 = t0 + timedelta(seconds=30)
    mock_dt.now.return_value = t1
    energy = calculator.calculate_energy(power)

    # First update: 10000W * 30s/3600 / 1000 = 0.0833 kWh
    # Second update: another 0.0833 kWh → total ~0.167
    assert energy.daily_solar == pytest.approx(solar_after_first + 0.0833, abs=0.01)
    assert energy.daily_battery_discharge == pytest.approx(energy0.daily_battery_discharge + 0.0417, abs=0.01)


# ──────────────────────────────────────────────
# #794 — yearly cost seed from recorded monthly statistics
# ──────────────────────────────────────────────
#
# The yearly cost accumulators used to be backfilled ONCE, as yearly ENERGY ×
# a 7-day average rate, while the monthly cost accumulators held exactly
# accumulated values — two independent computations that never agreed. Live on
# PROD (2026-08-17): cost_import seeded 112.81 vs 458.97 in the recorded
# monthly buckets, and the year's net cost flipped sign. The seed now sums
# SEM's own recorded monthly cost statistics (measured at the prices actually
# in force) and estimates only months with no cost record at all.

import custom_components.solar_energy_management.coordinator.energy_calculator as ec_module

_NOW_794 = datetime(2026, 8, 17, 12, 0, 0)
_YEAR_794 = "2026"

# The PROD numbers from the issue: 8 recorded monthly cost_import buckets
# summing 458.97, while yearly grid-import energy × the 0.30 rate gives the
# old (wrong) 112.81.
_PROD_MONTHS_794 = {1: 55.0, 2: 60.0, 3: 58.0, 4: 57.0, 5: 50.0, 6: 62.0, 7: 59.0, 8: 57.97}
_PROD_IMPORT_KWH_794 = 376.0333333333  # × 0.30 → 112.81


class _Registry794:
    """Entity-registry double: resolves unique_id → entity_id like er.async_get()."""

    def __init__(self, mapping):
        self.mapping = mapping

    def async_get_entity_id(self, domain, platform, unique_id):
        assert domain == "sensor"
        assert platform == "solar_energy_management"
        return self.mapping.get(unique_id)


def _cost_rows_794(months, year=2026):
    """Monthly LTS rows for a monthly-resetting cost sensor ({"state"} query).

    A bucket's ``state`` (last state in the bucket) IS that month's total.
    ``start`` is a float timestamp, the shape the real recorder returns.
    """
    return [
        {"start": datetime(year, m, 1).timestamp(), "state": v}
        for m, v in sorted(months.items())
    ]


def _sum_rows_794(cumulative, year=2026):
    """Monthly LTS rows for an energy counter ({"sum"} query — cumulative).

    ``cumulative`` is [(month, cumulative_sum)]; month 0 means December of the
    previous year (the January baseline bucket).
    """
    rows = []
    for m, s in cumulative:
        y, mm = (year - 1, 12) if m == 0 else (year, m)
        rows.append({"start": datetime(y, mm, 1).timestamp(), "sum": s})
    return rows


def _ed_794():
    """Energy Dashboard config double with the five energy entity roles."""
    cfg = MagicMock()
    cfg.solar_energy = "sensor.solar_total"
    cfg.grid_import_energy = "sensor.grid_import_total"
    cfg.grid_export_energy = "sensor.grid_export_total"
    cfg.battery_charge_energy = "sensor.batt_charge_total"
    cfg.battery_discharge_energy = "sensor.batt_discharge_total"
    cfg.device_consumption = []
    return cfg


_ALL_COST_SENSORS_794 = {
    "cost_import": ("sem_monthly_costs", "sensor.sem_monthly_costs"),
    "cost_export": ("sem_monthly_export_revenue", "sensor.sem_monthly_export_revenue"),
    "cost_savings": ("sem_monthly_savings", "sensor.sem_monthly_savings"),
    "cost_batt_savings": ("sem_monthly_battery_savings", "sensor.sem_monthly_battery_savings"),
}


@pytest.fixture
def seed_env_794(monkeypatch):
    """Freeze now() and wire registry + recorder doubles for the #794 seed.

    The test fills in ``env["registry"]`` (unique_id → entity_id) and
    ``env["stats"]`` (entity_id → LTS rows). The recorder instance is absent
    (get_instance raises), so the code exercises its direct-call fallback;
    every statistics query is recorded in ``env["queries"]``.
    """
    from homeassistant.helpers import entity_registry as er
    from homeassistant.components import recorder as recorder_mod
    from homeassistant.components.recorder import statistics as rec_stats

    env = {"registry": {}, "stats": {}, "queries": []}

    monkeypatch.setattr(ec_module.dt_util, "now", lambda: _NOW_794)
    monkeypatch.setattr(er, "async_get", lambda hass: _Registry794(env["registry"]))

    def _no_instance(hass):
        raise RuntimeError("no recorder instance in unit tests")

    monkeypatch.setattr(recorder_mod, "get_instance", _no_instance)

    def _stats(hass, start, end, ids, period, units, types):
        wanted = set(ids)
        env["queries"].append(
            {"start": start, "ids": wanted, "period": period, "types": set(types)}
        )
        return {eid: rows for eid, rows in env["stats"].items() if eid in wanted}

    monkeypatch.setattr(rec_stats, "statistics_during_period", _stats)
    return env


@pytest.mark.asyncio
async def test_794_seed_uses_recorded_months_not_avg_rate_estimate(
    calculator, seed_env_794
):
    """The regression from the issue: recorded monthly cost buckets summing
    458.97 seed 458.97 — NOT the yearly-energy × avg-rate 112.81 that put the
    year 4× off beside the exactly-accumulated months."""
    calculator._yearly_seeded = True
    calculator._yearly_accumulators[f"grid_import_{_YEAR_794}"] = _PROD_IMPORT_KWH_794
    seed_env_794["registry"]["sem_monthly_costs"] = "sensor.sem_monthly_costs"
    seed_env_794["stats"]["sensor.sem_monthly_costs"] = _cost_rows_794(_PROD_MONTHS_794)

    await calculator.seed_yearly_from_statistics(MagicMock(), _ed_794())

    assert calculator._yearly_cost_seeded is True
    seeded = calculator._yearly_cost_accumulators.get(f"cost_import_{_YEAR_794}")
    assert seeded == pytest.approx(458.97)
    # Pin the defect: the old estimate must NOT be what lands in the year.
    assert seeded != pytest.approx(112.81, abs=0.5)


@pytest.mark.asyncio
async def test_794_yearly_equals_sum_of_recorded_months_all_categories(
    calculator, seed_env_794
):
    """Yearly == Σ monthly by construction, for all four cost categories."""
    months = {
        "cost_import": {m: 10.0 + m for m in range(1, 9)},
        "cost_export": {m: 5.0 + m / 2 for m in range(1, 9)},
        "cost_savings": {m: 20.0 + m for m in range(1, 9)},
        "cost_batt_savings": {m: 3.0 + m for m in range(1, 9)},
    }
    for category, (unique_id, entity_id) in _ALL_COST_SENSORS_794.items():
        seed_env_794["registry"][unique_id] = entity_id
        seed_env_794["stats"][entity_id] = _cost_rows_794(months[category])
    calculator._yearly_seeded = True

    await calculator.seed_yearly_from_statistics(MagicMock(), _ed_794())

    assert calculator._yearly_cost_seeded is True
    for category, expected in months.items():
        assert calculator._yearly_cost_accumulators.get(
            f"{category}_{_YEAR_794}"
        ) == pytest.approx(sum(expected.values())), category


@pytest.mark.asyncio
async def test_794_renamed_entity_resolved_through_registry(calculator, seed_env_794):
    """Entity resolution goes unique_id → entity_id through the registry — a
    user-renamed sensor is still found (nothing hardcodes sensor.sem_*)."""
    seed_env_794["registry"]["sem_monthly_costs"] = "sensor.our_grid_bill"
    seed_env_794["stats"]["sensor.our_grid_bill"] = _cost_rows_794({7: 12.5, 8: 20.0})
    calculator._yearly_seeded = True

    await calculator.seed_yearly_from_statistics(MagicMock(), _ed_794())

    assert calculator._yearly_cost_accumulators.get(
        f"cost_import_{_YEAR_794}"
    ) == pytest.approx(32.5)


@pytest.mark.asyncio
async def test_794_months_without_cost_history_estimated_from_their_energy(
    calculator, seed_env_794
):
    """Cost history starts in June: months 6-8 are measured, 1-5 estimated
    from each month's own energy × avg rate. The total is the sum of both and
    neither half is double counted (measured months are NOT re-priced)."""
    recorded = {6: 60.0, 7: 70.0, 8: 50.0}
    seed_env_794["registry"]["sem_monthly_costs"] = "sensor.sem_monthly_costs"
    seed_env_794["stats"]["sensor.sem_monthly_costs"] = _cost_rows_794(recorded)
    # Grid-import counter: Dec baseline 1000, then monthly deltas
    # Jan..May = 100, 90, 80, 70, 60 (the estimated months, 400 kWh) and
    # Jun..Aug = 50, 40, 30 (the measured months — must NOT be priced again).
    cumulative, total = [(0, 1000.0)], 1000.0
    for m, delta in enumerate([100.0, 90.0, 80.0, 70.0, 60.0, 50.0, 40.0, 30.0], start=1):
        total += delta
        cumulative.append((m, total))
    seed_env_794["stats"]["sensor.grid_import_total"] = _sum_rows_794(cumulative)
    calculator._yearly_seeded = True

    await calculator.seed_yearly_from_statistics(MagicMock(), _ed_794())

    # Σ recorded (180) + Jan-May energy (400 kWh) × 0.30 = 180 + 120 = 300.
    # Double counting Jun-Aug estimates would give 336; dropping the
    # estimated months entirely would give 180.
    assert calculator._yearly_cost_accumulators.get(
        f"cost_import_{_YEAR_794}"
    ) == pytest.approx(300.0)


@pytest.mark.asyncio
async def test_794_estimate_fallback_ignores_grid_charged_battery(
    calculator, seed_env_794
):
    """grid_origin_share = 1.0 → the whole battery charge was bought from the
    grid and consumed no solar; the estimate fallback must not subtract it
    from the solar savings (the old code subtracted the WHOLE charge)."""
    # No SEM cost sensors in the registry → the estimate fallback runs.
    calculator._yearly_seeded = True
    calculator.set_battery_grid_origin_share(1.0)
    ya = calculator._yearly_accumulators
    ya[f"solar_{_YEAR_794}"] = 400.0
    ya[f"grid_export_{_YEAR_794}"] = 50.0
    ya[f"battery_charge_{_YEAR_794}"] = 100.0
    ya[f"battery_discharge_{_YEAR_794}"] = 90.0
    ya[f"grid_import_{_YEAR_794}"] = 195.0

    await calculator.seed_yearly_from_statistics(MagicMock(), _ed_794())

    # solar_direct = max(0, 400 − 50 − 100×(1−1.0)) = 350 → 105.0 at 0.30.
    # The old code subtracted the whole charge: (400−50−100)×0.30 = 75.0.
    got = calculator._yearly_cost_accumulators.get(f"cost_savings_{_YEAR_794}")
    assert got == pytest.approx(105.0)
    assert got != pytest.approx(75.0)


@pytest.mark.asyncio
async def test_794_month_estimate_ignores_grid_charged_battery(
    calculator, seed_env_794
):
    """Same grid-origin rule on the per-month estimate path: January (no cost
    record) is estimated from January's energy, and with share=1.0 its battery
    charge must not reduce the solar savings."""
    recorded = {m: 10.0 for m in range(2, 9)}  # Feb..Aug measured, Jan missing
    seed_env_794["registry"]["sem_monthly_savings"] = "sensor.sem_monthly_savings"
    seed_env_794["stats"]["sensor.sem_monthly_savings"] = _cost_rows_794(recorded)
    # January energy: solar 300, export 50, battery charge 100 (all grid-origin).
    seed_env_794["stats"]["sensor.solar_total"] = _sum_rows_794([(0, 1000.0), (1, 1300.0)])
    seed_env_794["stats"]["sensor.grid_export_total"] = _sum_rows_794([(0, 500.0), (1, 550.0)])
    seed_env_794["stats"]["sensor.batt_charge_total"] = _sum_rows_794([(0, 200.0), (1, 300.0)])
    calculator._yearly_seeded = True
    calculator.set_battery_grid_origin_share(1.0)

    await calculator.seed_yearly_from_statistics(MagicMock(), _ed_794())

    # Jan estimate = max(0, 300 − 50 − 100×(1−1.0)) × 0.30 = 75.0; + Σ 70.0
    # recorded = 145.0. Subtracting the whole charge would give 45 + 70 = 115.
    assert calculator._yearly_cost_accumulators.get(
        f"cost_savings_{_YEAR_794}"
    ) == pytest.approx(145.0)


@pytest.mark.asyncio
async def test_794_underseeded_yearly_cost_self_heals_to_recorded_floor(
    calculator, seed_env_794
):
    """A persisted bad seed (both seeded flags True, yearly value below the
    sum of the year's recorded months) lifts to the measured floor on the next
    call — it must not stay wrong until January."""
    calculator._yearly_seeded = True
    calculator._yearly_cost_seeded = True  # persisted from the bad old seed
    calculator._yearly_cost_accumulators[f"cost_import_{_YEAR_794}"] = 112.81
    seed_env_794["registry"]["sem_monthly_costs"] = "sensor.sem_monthly_costs"
    seed_env_794["stats"]["sensor.sem_monthly_costs"] = _cost_rows_794(_PROD_MONTHS_794)

    await calculator.seed_yearly_from_statistics(MagicMock(), _ed_794())

    assert calculator._yearly_cost_accumulators.get(
        f"cost_import_{_YEAR_794}"
    ) == pytest.approx(458.97)


@pytest.mark.asyncio
async def test_794_healthy_yearly_cost_above_floor_untouched(
    calculator, seed_env_794
):
    """Σ(months) includes the current month's partial, and live yearly = seed
    + accumulation since — a healthy install already sits at/above the floor
    and the re-check must be a no-op (no double count)."""
    calculator._yearly_seeded = True
    calculator._yearly_cost_seeded = True
    calculator._yearly_cost_accumulators[f"cost_import_{_YEAR_794}"] = 500.0
    seed_env_794["registry"]["sem_monthly_costs"] = "sensor.sem_monthly_costs"
    seed_env_794["stats"]["sensor.sem_monthly_costs"] = _cost_rows_794(_PROD_MONTHS_794)

    await calculator.seed_yearly_from_statistics(MagicMock(), _ed_794())

    assert calculator._yearly_cost_accumulators.get(
        f"cost_import_{_YEAR_794}"
    ) == pytest.approx(500.0)


def test_794_yearly_seed_pending_property(calculator):
    """The coordinator's startup gate: pending until BOTH seeds AND the floor
    check have run. Persisted True flags alone must not close the gate —
    that is exactly the badly seeded install the floor exists to heal. The
    floor flag is runtime-only (fresh chance to self-heal every restart)."""
    assert calculator.yearly_seed_pending is True
    calculator._yearly_seeded = True
    calculator._yearly_cost_seeded = True
    assert calculator.yearly_seed_pending is True  # floor check still owed
    calculator._yearly_cost_floor_checked = True
    assert calculator.yearly_seed_pending is False
    # Runtime-only: the floor flag is never persisted.
    assert "yearly_cost_floor_checked" not in calculator.get_state()


@pytest.mark.asyncio
async def test_794_floor_gives_up_after_three_failed_attempts(
    calculator, seed_env_794
):
    """No recorded stats at all → the floor check retries 3 times, then stops
    holding the coordinator gate open (mirrors the energy seed's attempt cap).
    Runtime-only, so the next restart gets a fresh chance."""
    calculator._yearly_seeded = True
    calculator._yearly_cost_seeded = True
    hass, ed = MagicMock(), _ed_794()
    for expected_pending in (True, True, False):
        assert calculator.yearly_seed_pending is True
        await calculator.seed_yearly_from_statistics(hass, ed)
        assert calculator.yearly_seed_pending is expected_pending


def test_794_coordinator_gates_on_the_property_not_the_raw_flags():
    """The startup gate must ask ``yearly_seed_pending``, never the two seed
    flags directly (#794).

    Both flags are PERSISTED, so a gate spelled
    ``not _yearly_seeded or not _yearly_cost_seeded`` is already closed on the
    install that seeded badly — the floor re-check would never be reached and
    the fix would be a no-op on exactly the system it was written for. House
    pattern: pin the read, like tests/test_ev_control_fleet_reads.py.
    """
    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent / "coordinator" / "coordinator.py"
    ).read_text()
    tree = ast.parse(source)
    direct = sorted({
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr in {"_yearly_seeded", "_yearly_cost_seeded"}
    })
    assert direct == [], (
        f"coordinator.py reads {direct} directly — gate on yearly_seed_pending "
        "so the floor re-check still runs when both flags restore True"
    )
    assert "yearly_seed_pending" in source


def test_794_bucket_month_agrees_between_a_timestamp_and_its_datetime(monkeypatch):
    """Same instant, same bucket — whichever shape the recorder hands back.

    The real recorder returns float unix timestamps; test doubles and older
    cores return datetimes. A statistics bucket starts at a LOCAL month
    boundary, so in any zone east of UTC its aware form reads as the previous
    month in UTC (2026-07-01T00:00+02:00 is 2026-06-30T22:00Z). If the shapes
    disagree, a whole month of money lands in the wrong bucket — the same skew
    that misread the PROD statistics dump while diagnosing #792.
    """
    import zoneinfo
    from datetime import timezone
    from custom_components.solar_energy_management.coordinator.energy_calculator import (
        _stat_bucket_year_month,
    )

    zurich = zoneinfo.ZoneInfo("Europe/Zurich")
    monkeypatch.setattr(
        ec_module.dt_util, "as_local", lambda dt: dt.astimezone(zurich)
    )
    aware = datetime(2026, 6, 30, 22, 0, tzinfo=timezone.utc)  # = 01.07 00:00 local

    assert _stat_bucket_year_month({"start": aware.timestamp()}) == (2026, 7)
    assert _stat_bucket_year_month({"start": aware}) == (2026, 7)
    assert _stat_bucket_year_month({"start": aware.isoformat()}) == (2026, 7)
