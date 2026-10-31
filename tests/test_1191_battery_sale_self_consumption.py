"""#1191 — a battery sale is not solar sent out.

Self-consumption was (solar − export) ÷ solar. All export counted as solar's,
also what the battery sold. A morning with little sun and a sale exports more
than the sun made: the rate went below 0 %, the clamp held it at 0 % and,
after a while, the health check said the formula was wrong.

The cure is the class 120 question: does the total hold what is taken away
from it? Solar holds only solar's export. The battery's part of the export
(``battery_to_grid``, the allocator serves solar first) is booked beside the
export row and taken out of it before anything takes export away from solar:
the rate, CO2 avoided (day, year, lifetime, the live correction), the day-end
ROI snapshot, the assistant's "% of solar exported" and the night audit.
"""
from __future__ import annotations

import ast
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import MagicMock

import pytest
from freezegun import freeze_time

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    GRID_CO2_KG_PER_KWH,
    GRID_EXPORT_BATTERY_CATEGORY,
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.flow_calculator import (
    FlowCalculator,
)
from custom_components.solar_energy_management.coordinator.types import (
    EnergyTotals,
    PowerReadings,
)
from custom_components.solar_energy_management.utils.helpers import (
    battery_export_part,
    solar_export,
)
from custom_components.solar_energy_management.utils.time_manager import TimeManager

REPO = Path(__file__).resolve().parents[1]
DAY = date(2026, 10, 26)
MORNING = "2026-10-26 08:00:00"
STEP_S = 60


def _calc() -> EnergyCalculator:
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    calc = EnergyCalculator({"update_interval": STEP_S}, TimeManager(hass))
    calc._import_rate = 0.30
    return calc


def _read(*, solar=0.0, home=0.0, battery=0.0, grid=0.0, **flags) -> PowerReadings:
    """One read. Signs as SEM holds them: grid + is export, battery − is
    discharge."""
    p = PowerReadings(solar_power=solar, battery_power=battery, grid_power=grid,
                      **flags)
    p.calculate_derived()
    p.home_consumption_power = home
    return p


def _calls(rel: str, callee: str) -> list:
    """Every call to ``callee`` (a name or an attribute) in one file."""
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and (
        getattr(n.func, "attr", None) == callee
        or getattr(n.func, "id", None) == callee)]


def _cycle(calc: EnergyCalculator, power: PowerReadings, flows=None) -> EnergyTotals:
    """One ``STEP_S`` cycle; the flows come from the real allocator unless
    the test hands its own in."""
    calc._last_update = None
    if flows is None:
        flows = FlowCalculator().calculate_power_flows(power)
    return calc.calculate_energy(power, flows)


def _kwh(watts: float, cycles: int = 1) -> float:
    return watts * STEP_S * cycles / 3_600_000


def _row(calc: EnergyCalculator, category: str) -> float:
    return calc._daily_accumulators.get(f"{category}_{DAY}", 0.0)


def _sale_morning(calc: EnergyCalculator, cycles: int = 30) -> EnergyTotals:
    """The reported shape: 1 kW of sun, the house takes 0.5 kW, the pack
    sells 4 kW. The meter sees 4.5 kW of export; 0.5 kW of it is solar's."""
    energy = None
    for _ in range(cycles):
        energy = _cycle(calc, _read(solar=1000.0, home=500.0, battery=-4000.0,
                                    grid=4500.0))
    return energy


@pytest.fixture
def morning():
    with freeze_time(MORNING) as frozen:
        yield frozen


# ── the helpers ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestTheHelpers:
    def test_the_battery_part_is_its_flow(self):
        assert battery_export_part(4500.0, 4000.0) == pytest.approx(4000.0)

    def test_the_battery_part_is_never_more_than_the_export(self):
        assert battery_export_part(3000.0, 4000.0) == pytest.approx(3000.0)

    def test_no_flow_keeps_the_export_solars(self):
        assert battery_export_part(4500.0, 0.0) == 0.0
        assert battery_export_part(4500.0, None) == 0.0

    def test_junk_is_zero(self):
        assert battery_export_part(-5.0, 100.0) == 0.0
        assert battery_export_part(None, 100.0) == 0.0
        assert battery_export_part(100.0, -5.0) == 0.0

    def test_solar_export_takes_the_battery_part_away(self):
        assert solar_export(4.5, 4.0) == pytest.approx(0.5)
        assert solar_export(4.5, 0.0) == pytest.approx(4.5)
        assert solar_export(1.0, 3.0) == 0.0
        assert solar_export(None, 1.0) == 0.0
        assert solar_export(2.0, -1.0) == pytest.approx(2.0)


# ── the reported case through the real allocator and calculator ──────────


@pytest.mark.unit
@pytest.mark.usefixtures("morning")
class TestTheReportedMorning:
    def test_the_rate_is_solars_own_share(self):
        calc = _calc()
        energy = _sale_morning(calc)
        metrics = calc.calculate_performance(PowerReadings(), energy, None)
        # solar 0.5 kWh, of which 0.25 kWh went out → 50 %; was −350 → 0 %
        assert energy.daily_solar == pytest.approx(0.5, abs=0.01)
        assert energy.daily_grid_export == pytest.approx(2.25, abs=0.01)
        assert metrics.self_consumption_rate == pytest.approx(50.0, abs=0.5)

    def test_the_clamp_stays_quiet(self):
        """The clamp's record is what the #660 health check counts."""
        calc = _calc()
        energy = _sale_morning(calc)
        calc.calculate_performance(PowerReadings(), energy, None)
        assert "self_consumption_rate" not in calc.clamp_engagement

    def test_the_old_rule_on_the_same_morning_engaged_the_clamp(self):
        """The twin: the same totals with no battery part read below 0 %."""
        calc = _calc()
        energy = _sale_morning(calc)
        energy.daily_grid_export_battery = 0.0
        metrics = calc.calculate_performance(PowerReadings(), energy, None)
        assert metrics.self_consumption_rate == 0.0
        assert calc.clamp_engagement["self_consumption_rate"] > 300

    def test_the_battery_row_holds_the_sale(self):
        calc = _calc()
        energy = _sale_morning(calc, cycles=1)
        assert _row(calc, GRID_EXPORT_BATTERY_CATEGORY) == pytest.approx(_kwh(4000.0))
        assert _row(calc, "grid_export") == pytest.approx(_kwh(4500.0))
        assert energy.daily_grid_export_battery == round(_kwh(4000.0), 2)

    def test_every_period_moves(self):
        calc = _calc()
        energy = _sale_morning(calc)
        assert energy.daily_grid_export_battery > 0
        assert energy.monthly_grid_export_battery == energy.daily_grid_export_battery
        assert energy.yearly_grid_export_battery == energy.daily_grid_export_battery
        assert calc._get_lifetime(GRID_EXPORT_BATTERY_CATEGORY) == pytest.approx(
            energy.daily_grid_export_battery, abs=0.01)

    def test_a_gap_cycle_reads_the_row_back(self):
        """``_build_current_totals`` (a skipped cycle) must not flap it to 0."""
        calc = _calc()
        _sale_morning(calc)
        energy = calc._build_current_totals(DAY, f"{DAY.year}_{DAY.month}",
                                            str(DAY.year))
        assert energy.daily_grid_export_battery == pytest.approx(
            round(_row(calc, GRID_EXPORT_BATTERY_CATEGORY), 2))
        assert energy.daily_grid_export_battery > 0


@pytest.mark.unit
@pytest.mark.usefixtures("morning")
class TestNoSaleNoChange:
    def test_a_solar_export_reads_as_before(self):
        calc = _calc()
        for _ in range(30):
            energy = _cycle(calc, _read(solar=5000.0, home=1000.0, grid=4000.0))
        metrics = calc.calculate_performance(PowerReadings(), energy, None)
        assert energy.daily_grid_export_battery == 0.0
        assert metrics.self_consumption_rate == pytest.approx(20.0, abs=0.5)

    def test_without_flows_all_export_is_solars(self):
        calc = _calc()
        calc._last_update = None
        energy = calc.calculate_energy(
            _read(solar=1000.0, home=500.0, battery=-4000.0, grid=4500.0), None)
        assert energy.daily_grid_export_battery == 0.0
        assert _row(calc, GRID_EXPORT_BATTERY_CATEGORY) == 0.0

    def test_export_the_flows_left_unassigned_stays_solars(self):
        """A read that does not add up: 4.5 kW out, 1 kW of sun, the pack
        gives 1 kW, the house takes 1 kW. The sun serves the house, so the
        flows give the pack 1 kW of the export; the 3.5 kW nobody made stays
        solar's, as before."""
        calc = _calc()
        _cycle(calc, _read(solar=1000.0, home=1000.0, battery=-1000.0, grid=4500.0))
        assert _row(calc, GRID_EXPORT_BATTERY_CATEGORY) == pytest.approx(
            _kwh(1000.0))

    def test_a_charging_pack_sells_nothing(self):
        calc = _calc()
        _cycle(calc, _read(solar=6000.0, home=500.0, battery=2000.0, grid=3500.0))
        assert _row(calc, GRID_EXPORT_BATTERY_CATEGORY) == 0.0

    def test_the_legacy_two_arg_rate_is_unchanged(self):
        calc = _calc()
        energy = EnergyTotals(daily_solar=10.0, daily_grid_export=2.0)
        assert calc.calculate_performance(
            PowerReadings(), energy).self_consumption_rate == pytest.approx(80.0)


@pytest.mark.unit
@pytest.mark.usefixtures("morning")
class TestADarkPack:
    def test_a_held_sale_keeps_its_battery_part(self):
        """(#1177) A dark pack books its held watts; its flow share is held
        with it, so the held sale is still the battery's."""
        calc = _calc()
        _cycle(calc, _read(solar=1000.0, home=500.0, battery=-4000.0, grid=4500.0))
        _cycle(calc, _read(solar=1000.0, home=500.0, battery=0.0, grid=4500.0,
                           battery_power_all_unavailable=True))
        assert _row(calc, GRID_EXPORT_BATTERY_CATEGORY) == pytest.approx(
            _kwh(4000.0, 2))


@pytest.mark.unit
@pytest.mark.usefixtures("morning")
class TestADarkMeter:
    """(#1191 review) A dark grid meter books its held export (#1177). The
    live read then has 0 W export, so its flows give the pack no part."""

    def test_a_held_export_keeps_the_battery_part_of_its_read(self):
        calc = _calc()
        _cycle(calc, _read(solar=1000.0, home=500.0, battery=-4000.0, grid=4500.0))
        _cycle(calc, _read(solar=1000.0, home=500.0, battery=-4000.0, grid=0.0,
                           grid_power_unavailable=True))
        assert _row(calc, "grid_export") == pytest.approx(_kwh(4500.0, 2))
        assert _row(calc, GRID_EXPORT_BATTERY_CATEGORY) == pytest.approx(
            _kwh(4000.0, 2))

    def test_a_skipped_cycles_read_keeps_its_part(self):
        """(review 2) A cycle skipped for a gap still takes its live read,
        and a dark meter can hold it: its battery part goes with it."""
        from homeassistant.util import dt as dt_util
        calc = _calc()
        calc._last_update = dt_util.now() - timedelta(hours=1)    # a gap
        calc.calculate_energy(
            _read(solar=1000.0, home=500.0, battery=-4000.0, grid=4500.0),
            FlowCalculator().calculate_power_flows(
                _read(solar=1000.0, home=500.0, battery=-4000.0, grid=4500.0)))
        assert _row(calc, "grid_export") == 0.0, "the gap cycle booked energy"
        _cycle(calc, _read(solar=1000.0, home=500.0, battery=-4000.0, grid=0.0,
                           grid_power_unavailable=True))
        assert _row(calc, "grid_export") == pytest.approx(_kwh(4500.0))
        assert _row(calc, GRID_EXPORT_BATTERY_CATEGORY) == pytest.approx(
            _kwh(4000.0))

    def test_a_meter_dark_past_its_grace_books_nothing(self):
        calc = _calc()
        _cycle(calc, _read(solar=1000.0, home=500.0, battery=-4000.0, grid=4500.0))
        calc._integral_last_live["grid"] = (
            calc._integral_last_live["grid"][0],
            calc._integral_last_live["grid"][1] - timedelta(hours=1))
        _cycle(calc, _read(solar=1000.0, home=500.0, battery=-4000.0, grid=0.0,
                           grid_power_unavailable=True))
        assert _row(calc, "grid_export") == pytest.approx(_kwh(4500.0))
        assert _row(calc, GRID_EXPORT_BATTERY_CATEGORY) == pytest.approx(
            _kwh(4000.0))


EXPORT_METER = "sensor.p1_exported_energy"


def _metered_calc(counter: dict, category: str = "grid_export"):
    """A calculator whose ``category`` row follows a meter (#628)."""
    def _get(entity_id):
        if entity_id not in counter:
            return None
        state = MagicMock()
        state.state = str(counter[entity_id])
        state.attributes = {"unit_of_measurement": "kWh"}
        return state
    hass = MagicMock()
    hass.states.get = _get
    calc = EnergyCalculator({"update_interval": STEP_S}, TimeManager(hass))
    calc.configure_meter_counters(hass, {category: list(counter)}, True)
    return calc


@pytest.mark.unit
@pytest.mark.usefixtures("morning")
class TestTheMeterCorrection:
    """(#1191 review) The export row follows its meter; the battery row is
    the flows'. The meter's correction must keep the battery's share, or a
    meter ahead of a big sale lands the gap on solar's export."""

    def _morning(self, ahead: float):
        counter = {EXPORT_METER: 1000.0}
        calc = _metered_calc(counter)
        sale = _read(solar=1000.0, home=500.0, battery=-4000.0, grid=4500.0)
        _cycle(calc, sale)                      # sets the meter's baseline
        for _ in range(60):
            counter[EXPORT_METER] += _kwh(4500.0) * ahead
            energy = _cycle(calc, sale)
        return calc, energy

    def test_a_meter_ahead_keeps_the_battery_share(self):
        calc, energy = self._morning(ahead=1.10)
        export, battery = _row(calc, "grid_export"), _row(
            calc, GRID_EXPORT_BATTERY_CATEGORY)
        assert export > _kwh(4500.0, 61) * 1.05, "the meter was not adopted"
        assert battery / export == pytest.approx(4000.0 / 4500.0, rel=0.01)
        metrics = calc.calculate_performance(PowerReadings(), energy, None)
        assert "self_consumption_rate" not in calc.clamp_engagement
        assert metrics.self_consumption_rate == pytest.approx(45.0, abs=2.0)

    def test_every_period_moves_with_the_correction(self):
        calc, energy = self._morning(ahead=1.10)
        daily = _row(calc, GRID_EXPORT_BATTERY_CATEGORY)
        assert calc._monthly_accumulators[
            f"{GRID_EXPORT_BATTERY_CATEGORY}_{DAY.year}_{DAY.month}"] == pytest.approx(daily)
        assert calc._yearly_accumulators[
            f"{GRID_EXPORT_BATTERY_CATEGORY}_{DAY.year}"] == pytest.approx(daily)
        assert calc._lifetime_accumulators[
            f"lifetime_{GRID_EXPORT_BATTERY_CATEGORY}"] == pytest.approx(daily)

    def test_a_meter_behind_keeps_it_too(self):
        calc, _ = self._morning(ahead=0.90)
        export, battery = _row(calc, "grid_export"), _row(
            calc, GRID_EXPORT_BATTERY_CATEGORY)
        assert export < _kwh(4500.0, 61) * 0.95, "the meter was not adopted"
        assert battery / export == pytest.approx(4000.0 / 4500.0, rel=0.01)

    def test_an_afternoons_drift_leaves_the_mornings_sale(self):
        """(review 2) A correction is split as what was added since the last
        one: the meter agreed all morning, so a solar-only afternoon that it
        reads 10 % low moves (almost) none of the sale."""
        counter = {EXPORT_METER: 1000.0}
        calc = _metered_calc(counter)
        sale = _read(solar=1000.0, home=500.0, battery=-4000.0, grid=4500.0)
        sun = _read(solar=5000.0, home=1000.0, grid=4000.0)
        _cycle(calc, sale)
        for _ in range(60):
            counter[EXPORT_METER] += _kwh(4500.0)
            _cycle(calc, sale)
        morning = _row(calc, GRID_EXPORT_BATTERY_CATEGORY)
        for _ in range(120):
            counter[EXPORT_METER] += _kwh(4000.0) * 0.9
            _cycle(calc, sun)
        export = _row(calc, "grid_export")
        assert export < _kwh(4500.0, 61) + _kwh(4000.0, 120) * 0.95, \
            "the meter was not adopted"
        # only the first correction (just over the 0.05 kWh threshold) is
        # spread over the whole day
        assert _row(calc, GRID_EXPORT_BATTERY_CATEGORY) == pytest.approx(
            morning, abs=0.05)

    def test_a_counter_reset_starts_a_new_window(self):
        counter = {EXPORT_METER: 1000.0}
        calc = _metered_calc(counter)
        sale = _read(solar=1000.0, home=500.0, battery=-4000.0, grid=4500.0)
        _cycle(calc, sale)
        counter[EXPORT_METER] = 5.0                     # the meter rebooted
        _cycle(calc, sale)
        mark = calc._meter_baselines["grid_export"]["beside_mark"]
        assert mark["row"] == pytest.approx(_row(calc, "grid_export"))
        assert mark["parts"][GRID_EXPORT_BATTERY_CATEGORY] == pytest.approx(
            _row(calc, GRID_EXPORT_BATTERY_CATEGORY))

    def test_with_no_sale_the_correction_moves_nothing_else(self):
        counter = {EXPORT_METER: 1000.0}
        calc = _metered_calc(counter)
        sun = _read(solar=5000.0, home=1000.0, grid=4000.0)
        _cycle(calc, sun)
        for _ in range(60):
            counter[EXPORT_METER] += _kwh(4000.0) * 1.1
            _cycle(calc, sun)
        assert _row(calc, GRID_EXPORT_BATTERY_CATEGORY) == 0.0


# ── the siblings ─────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.usefixtures("morning")
class TestCo2Avoided:
    def test_a_sale_takes_nothing_off_the_day(self):
        calc = _calc()
        energy = _sale_morning(calc)
        costs = calc.calculate_costs(energy)
        used = energy.daily_solar - (energy.daily_grid_export
                                     - energy.daily_grid_export_battery)
        assert used > 0.2
        assert costs.daily_co2_avoided_kg == pytest.approx(
            round(used * GRID_CO2_KG_PER_KWH, 2), abs=0.011)
        assert costs.daily_co2_avoided_kg > 0

    def test_year_and_lifetime_follow(self):
        """Five hours of the morning: the year and lifetime round to 0.1 kg."""
        calc = _calc()
        energy = _sale_morning(calc, cycles=300)
        costs = calc.calculate_costs(energy)
        assert costs.yearly_co2_avoided_kg > 0
        assert costs.lifetime_co2_avoided_kg > 0

    def test_the_old_rule_would_have_said_zero(self):
        calc = _calc()
        energy = _sale_morning(calc)
        energy.daily_grid_export_battery = 0.0
        assert calc.calculate_costs(energy).daily_co2_avoided_kg == 0.0

    def test_the_live_correction_counts_the_solar_the_house_used(self):
        """(#1088) The live-intensity correction books per kWh of solar used
        here; with the sale taken as solar's it booked nothing."""
        calc = _calc()
        calc._co2_live = True
        calc._grid_co2_kg = GRID_CO2_KG_PER_KWH + 0.1
        _cycle(calc, _read(solar=1000.0, home=500.0, battery=-4000.0, grid=4500.0))
        from custom_components.solar_energy_management.coordinator.energy_calculator import (
            CO2_CORRECTION_CATEGORY,
        )
        assert _row(calc, CO2_CORRECTION_CATEGORY) == pytest.approx(
            _kwh(500.0) * 0.1)


@pytest.mark.unit
class TestTheDayEndSnapshot:
    def test_the_roi_books_solars_own_use(self):
        calc = _calc()
        d = str(DAY)
        calc._daily_accumulators.update({
            f"solar_{d}": 2.0, f"grid_export_{d}": 5.0,
            f"{GRID_EXPORT_BATTERY_CATEGORY}_{d}": 4.0,
        })
        calc._snapshot_daily_costs(DAY)
        assert calc._accumulated_self_consumed_kwh == pytest.approx(1.0)

    def test_without_a_sale_as_before(self):
        calc = _calc()
        d = str(DAY)
        calc._daily_accumulators.update({f"solar_{d}": 10.0, f"grid_export_{d}": 4.0})
        calc._snapshot_daily_costs(DAY)
        assert calc._accumulated_self_consumed_kwh == pytest.approx(6.0)


@pytest.mark.unit
class TestTheAssistant:
    def _analyze(self, **kw):
        from custom_components.solar_energy_management.analytics.energy_assistant import (
            EnergyAssistant,
        )
        hass = MagicMock()
        hass.config.currency = "CHF"
        assistant = EnergyAssistant(hass)
        data = assistant.analyze(daily_solar_kwh=10.0, daily_home_kwh=5.0,
                                 self_consumption_rate=90.0, autarky_rate=60.0,
                                 **kw)
        titles = [t["title"] for t in assistant.get_all_tips()]
        return data, titles

    def test_a_sale_is_not_a_high_solar_export(self):
        _, titles = self._analyze(daily_grid_export_kwh=7.0,
                                  daily_battery_export_kwh=6.0)
        assert "High solar export" not in titles

    def test_a_real_solar_export_still_tips(self):
        _, titles = self._analyze(daily_grid_export_kwh=7.0)
        assert "High solar export" in titles

    def test_the_score_counts_solars_export(self):
        sale, _ = self._analyze(daily_grid_export_kwh=7.0,
                                daily_battery_export_kwh=6.0)
        same_solar, _ = self._analyze(daily_grid_export_kwh=1.0)
        old_rule, _ = self._analyze(daily_grid_export_kwh=7.0)
        score = "energy_optimization_score"
        assert sale.to_dict()[score] == same_solar.to_dict()[score]
        assert sale.to_dict()[score] > old_rule.to_dict()[score]

    def test_the_cycle_hands_the_battery_part_over(self):
        values = [kw.value for call in _calls("coordinator/coordinator.py", "analyze")
                  for kw in call.keywords if kw.arg == "daily_battery_export_kwh"]
        assert len(values) == 1
        assert isinstance(values[0], ast.Attribute)
        assert values[0].attr == "daily_grid_export_battery"


@pytest.mark.unit
class TestTheNightAudit:
    """(#755) The plan's share is of solar; the night recorder integrated the
    whole export against it."""

    def _me(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        from custom_components.solar_energy_management.coordinator.demand_outcome import (
            DemandOutcomeRecorder,
        )
        from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
            PlanGate,
        )
        me = SimpleNamespace(
            _energy_plan_shadow={"demands": [], "self_consumption": {"share": 0.9}},
            _shadow_plan_date=date(2026, 10, 25),
            _demand_outcomes=DemandOutcomeRecorder(max_gap_s=3600),
            _energy_plan_gate=lambda did, now=None: PlanGate(covered=True),
            _surplus_controller=SimpleNamespace(get_devices_sorted=lambda: []),
            _ev_devices={}, _charger_power_w=lambda cid, power, dev=None: 0.0,
            _storage=None,
        )
        for name in ("_seal_demand_outcomes", "_persist_demand_outcomes",
                     "_refresh_demand_review"):
            setattr(me, name, MethodType(getattr(SEMCoordinator, name), me))
        return me, SEMCoordinator._record_demand_outcomes

    def _night(self, flows):
        me, record = self._me()
        power = _read(solar=1000.0, home=500.0, battery=-4000.0, grid=4500.0)
        power.ev_power_per_charger = {}
        t0 = datetime(2026, 10, 26, 7, 0, tzinfo=timezone.utc)
        record(me, t0, power, flows)
        record(me, t0 + timedelta(hours=1), power, flows)
        return me._demand_outcomes._summary

    def test_a_sale_in_the_window_is_not_solar_sent_out(self):
        flows = FlowCalculator().calculate_power_flows(
            _read(solar=1000.0, home=500.0, battery=-4000.0, grid=4500.0))
        summary = self._night(flows)
        assert summary.solar_kwh == pytest.approx(1.0, abs=0.01)
        assert summary.exported_kwh == pytest.approx(0.5, abs=0.01)
        assert summary.actual_share == pytest.approx(0.5, abs=0.01)

    def test_without_flows_as_before(self):
        summary = self._night(None)
        assert summary.exported_kwh == pytest.approx(4.5, abs=0.01)

    def test_the_cycle_hands_the_flows_over(self):
        sites = _calls("coordinator/coordinator.py", "_record_demand_outcomes")
        assert sites, "nothing calls the night recorder"
        for call in sites:
            flows = call.args[2] if len(call.args) > 2 else next(
                (kw.value for kw in call.keywords if kw.arg == "power_flows"), None)
            # (#1185) the books' flows, built from the held watts
            assert isinstance(flows, ast.Name) and flows.id == "book_flows", (
                f"line {call.lineno}: the night audit gets no flows")


@pytest.mark.unit
class TestDiagnostics:
    def test_the_battery_part_is_in_the_daily_energy(self):
        from custom_components.solar_energy_management.coordinator.types import (
            SEMData,
        )
        data = SEMData()
        data.energy = EnergyTotals(daily_grid_export=2.25,
                                   daily_grid_export_battery=2.0)
        assert data.to_dict()["daily_grid_export_battery_kwh"] == 2.0
        tree = ast.parse((REPO / "diagnostics.py").read_text(encoding="utf-8"))
        reads = [
            value.args[0].value
            for node in ast.walk(tree) if isinstance(node, ast.Dict)
            for key, value in zip(node.keys, node.values, strict=True)
            if isinstance(key, ast.Constant) and key.value == "grid_export_battery_kwh"
            and isinstance(value, ast.Call) and value.args
            and isinstance(value.args[0], ast.Constant)
        ]
        assert reads == ["daily_grid_export_battery_kwh"]


# ── the guard ────────────────────────────────────────────────────────────

#: A subtraction "solar − export" or a division "export ÷ solar" outside the
#: helper. Each entry is (file, function) and the count it may hold, with why.
_ALLOWED = {
    # fed solar's export since #1191 (the coordinator hands it over)
    ("coordinator/demand_outcome.py", "self_consumed_kwh"): 1,
    # (#1216) the readers of recorded history load the sale beside the
    # export and go through the helper: no site named for them any more
}
_SOLAR = re.compile(r"solar", re.I)
_EXPORT = re.compile(r"export|\bexp\b", re.I)


def _offences():
    found = {}
    for path in sorted(REPO.rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        if rel.startswith(("tests/", "tools/", "scripts/")) or "/tests/" in rel:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if not isinstance(node, ast.BinOp):
                continue
            left, right = ast.unparse(node.left), ast.unparse(node.right)
            if isinstance(node.right, ast.Call) and ast.unparse(
                    node.right.func).endswith("solar_export"):
                continue
            # A balance (solar + import + … − export) is not the shape: its
            # left holds a sum, and the export there is a real outflow.
            sub = (isinstance(node.op, ast.Sub) and _SOLAR.search(left)
                   and " + " not in left
                   and _EXPORT.search(right) and not _SOLAR.search(right))
            div = (isinstance(node.op, ast.Div) and _EXPORT.search(left)
                   and _SOLAR.search(right) and not _SOLAR.search(left))
            if not (sub or div):
                continue
            fn, up = None, node
            while up in parents:
                up = parents[up]
                if isinstance(up, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn = up.name
                    break
            found.setdefault((rel, fn), []).append(
                f"{rel}:{node.lineno} {ast.unparse(node)}")
    return found


@pytest.mark.unit
class TestNoExportTakenFromSolarUnsplit:
    def test_only_the_named_sites_take_export_from_solar(self):
        found = _offences()
        extra = {k: v for k, v in found.items() if k not in _ALLOWED}
        assert not extra, (
            "export taken away from solar (or divided by it) without "
            "utils.helpers.solar_export — a battery sale is not solar's "
            f"(#1191): {extra}")

    def test_each_named_site_holds_exactly_its_count(self):
        found = _offences()
        for key, count in _ALLOWED.items():
            assert len(found.get(key, [])) == count, (key, found.get(key))

    def test_the_guard_sees_the_old_line(self):
        """It must catch the line #1191 removed, and the helper's call
        must pass."""
        bad = ast.parse("def f(energy):\n"
                        "    return energy.daily_solar - energy.daily_grid_export\n")
        node = next(n for n in ast.walk(bad) if isinstance(n, ast.BinOp))
        assert _SOLAR.search(ast.unparse(node.left))
        assert _EXPORT.search(ast.unparse(node.right))
        good = ast.parse("x = solar - solar_export(a, b)")
        call = next(n for n in ast.walk(good) if isinstance(n, ast.BinOp)).right
        assert ast.unparse(call.func).endswith("solar_export")

    def test_no_card_takes_export_from_solar(self):
        pattern = re.compile(r"solar\w*\s*-\s*[\w.]*export", re.I)
        hits = [f"{p.name}:{i}"
                for p in sorted((REPO / "dashboard/card/src").rglob("*.js"))
                for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                if pattern.search(line)]
        assert not hits, hits
