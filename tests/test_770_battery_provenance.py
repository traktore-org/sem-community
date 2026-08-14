"""#770 — a grid-charged kWh and a solar-charged kWh are the same number.

``daily_battery_charge`` sums everything that went into the battery. The flow
layer already knows better (``solar_to_battery`` / ``grid_to_battery``), but
that attribution never reaches the ledger, and three downstream figures
inherit the error:

* **savings** credit every discharged kWh against the full import price, as
  though the stored energy were free solar. A kWh bought at 0.11 and
  discharged against 0.28 saves 0.17, not 0.28.
* **ROI / payback** are computed from those savings.
* **autarky** counts battery discharge as own supply. The code says so in a
  comment: *"strictly some battery discharge originated from cheap-tariff
  grid charge … SEM doesn't track battery-energy provenance"*.

Before the one-gate build grid charging was rare, so the error was small.
After it the planner force-charges in the cheap valley on any night with a
deficit — which is most winter nights. The error is now the feature.

What's missing is a **store with provenance**: the battery is inventory, and
inventory has a cost basis. Electrons are not tagged, so a discharge draws
from what is stored in proportion — the standard weighted-average model — and
what SEM does NOT know is carried as ``unknown`` rather than quietly assumed
to be solar (#755 contract 1: an assumption is not a measurement).
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator.battery_provenance import (
    BatteryProvenance,
)

TODAY = date(2026, 8, 14)
_DT = (
    "custom_components.solar_energy_management.coordinator"
    ".energy_calculator.dt_util"
)


def _store(**kw) -> BatteryProvenance:
    return BatteryProvenance(**kw)


# What ONE pool holds is not production surface — SEM measures one fleet SOC
# and publishes one fleet share, so the store exposes fleet reads only (#653
# deleted the per-battery twins that nothing called). The pool is still
# observable through the state the store persists, which is the better probe
# anyway: it asserts the numbers that actually survive a restart.

def _pool(s: BatteryProvenance, bid: str) -> dict:
    return s.get_state()["pools"].get(bid, {})


def _total(s: BatteryProvenance, bid: str) -> float:
    p = _pool(s, bid)
    return (
        p.get("solar_kwh", 0.0) + p.get("grid_kwh", 0.0) + p.get("unknown_kwh", 0.0)
    )


def _grid_frac(s: BatteryProvenance, bid: str) -> float:
    total = _total(s, bid)
    return _pool(s, bid).get("grid_kwh", 0.0) / total if total > 0 else 0.0


def _avg_grid_cost(s: BatteryProvenance, bid: str) -> float:
    grid = _pool(s, bid).get("grid_kwh", 0.0)
    return _pool(s, bid).get("grid_cost", 0.0) / grid if grid > 0 else 0.0


# ───────────────────────────────────────────────────────────────────────
# 1. the store
# ───────────────────────────────────────────────────────────────────────

class TestTheStoreRemembersWhereItCameFrom:
    def test_a_solar_charge_stores_solar(self) -> None:
        s = _store()
        s.charge("b1", solar_kwh=2.0, grid_kwh=0.0, import_rate=0.28)
        assert _total(s, "b1") == pytest.approx(2.0)
        assert _grid_frac(s, "b1") == pytest.approx(0.0)

    def test_a_grid_charge_stores_grid_and_what_it_cost(self) -> None:
        s = _store()
        s.charge("b1", solar_kwh=0.0, grid_kwh=4.0, import_rate=0.11)
        assert _grid_frac(s, "b1") == pytest.approx(1.0)
        assert _avg_grid_cost(s, "b1") == pytest.approx(0.11)

    def test_two_grid_charges_at_different_prices_average(self) -> None:
        """The valley is not one price. A pool has a weighted average."""
        s = _store()
        s.charge("b1", 0.0, 2.0, import_rate=0.10)
        s.charge("b1", 0.0, 2.0, import_rate=0.20)
        assert _avg_grid_cost(s, "b1") == pytest.approx(0.15)

    def test_batteries_do_not_share_a_pool(self) -> None:
        """#523: one battery can be force-charged while another rides solar."""
        s = _store()
        s.charge("b1", 0.0, 3.0, import_rate=0.11)
        s.charge("b2", 3.0, 0.0, import_rate=0.11)
        assert _grid_frac(s, "b1") == pytest.approx(1.0)
        assert _grid_frac(s, "b2") == pytest.approx(0.0)


class TestADischargeDrawsProportionally:
    def test_a_half_grid_pool_discharges_half_grid(self) -> None:
        """Electrons aren't tagged. Inventory is drawn in proportion."""
        s = _store()
        s.charge("b1", 5.0, 0.0, import_rate=0.28)
        s.charge("b1", 0.0, 5.0, import_rate=0.10)

        mix = s.discharge("b1", 2.0)
        assert mix.solar_kwh == pytest.approx(1.0)
        assert mix.grid_kwh == pytest.approx(1.0)
        assert mix.grid_cost == pytest.approx(0.10)   # 1 kWh at 0.10
        assert mix.unknown_kwh == pytest.approx(0.0)

    def test_the_pool_shrinks_by_what_was_drawn(self) -> None:
        s = _store()
        s.charge("b1", 4.0, 4.0, import_rate=0.10)
        s.discharge("b1", 4.0)
        assert _total(s, "b1") == pytest.approx(4.0)
        assert _grid_frac(s, "b1") == pytest.approx(0.5)

    def test_the_mix_never_exceeds_the_pool(self) -> None:
        s = _store()
        s.charge("b1", 1.0, 0.0, import_rate=0.10)
        mix = s.discharge("b1", 3.0)
        assert mix.solar_kwh == pytest.approx(1.0)
        assert mix.unknown_kwh == pytest.approx(2.0)
        assert _total(s, "b1") == pytest.approx(0.0)

    def test_an_empty_pool_yields_unknown_not_solar(self) -> None:
        """A fresh install discharging a battery SEM never watched charge
        knows nothing about that energy. Calling it solar would be an
        assumption recorded as a measurement (#755 contract 1)."""
        s = _store()
        mix = s.discharge("b1", 3.0)
        assert mix.unknown_kwh == pytest.approx(3.0)
        assert mix.solar_kwh == pytest.approx(0.0)
        assert mix.grid_kwh == pytest.approx(0.0)
        assert mix.grid_cost == pytest.approx(0.0)

    def test_a_zero_discharge_draws_nothing(self) -> None:
        s = _store()
        s.charge("b1", 1.0, 1.0, import_rate=0.10)
        mix = s.discharge("b1", 0.0)
        assert mix.solar_kwh == 0.0 and mix.grid_kwh == 0.0
        assert _total(s, "b1") == pytest.approx(2.0)


class TestTheStoreIsTiedToAMeasurement:
    """Integrated power drifts. SOC is measured. The pool is reconciled to
    it so a month of rounding error can't invent stored energy."""

    def test_a_pool_bigger_than_the_battery_is_scaled_down(self) -> None:
        s = _store()
        s.charge("b1", 6.0, 6.0, import_rate=0.10)
        s.reconcile_to_stored("b1", 6.0)      # SOC says 6 kWh, pool says 12
        assert _total(s, "b1") == pytest.approx(6.0)
        assert _grid_frac(s, "b1") == pytest.approx(0.5)   # ratio preserved

    def test_scaling_down_scales_the_cost_with_it(self) -> None:
        s = _store()
        s.charge("b1", 0.0, 10.0, import_rate=0.20)
        s.reconcile_to_stored("b1", 5.0)
        assert _avg_grid_cost(s, "b1") == pytest.approx(0.20)  # per-kWh unchanged

    def test_a_pool_smaller_than_the_soc_gains_unknown_not_solar(self) -> None:
        """Charging SEM didn't see (a restart, another controller) is
        energy of unknown origin — not a windfall of free solar."""
        s = _store()
        s.charge("b1", 2.0, 0.0, import_rate=0.10)
        s.reconcile_to_stored("b1", 5.0)
        assert _total(s, "b1") == pytest.approx(5.0)
        mix = s.discharge("b1", 5.0)
        assert mix.solar_kwh == pytest.approx(2.0)
        assert mix.unknown_kwh == pytest.approx(3.0)

    def test_reconcile_ignores_a_missing_soc(self) -> None:
        s = _store()
        s.charge("b1", 2.0, 0.0, import_rate=0.10)
        s.reconcile_to_stored("b1", None)
        assert _total(s, "b1") == pytest.approx(2.0)


class TestTheFleetDrawsAndReconcilesAsOne:
    """SEM measures ONE ``battery_discharge_power`` and one fleet SOC. The
    pools are per battery because charging is (one unit can be force-charged
    while another rides solar), but the draw and the reconciliation have only
    fleet-level evidence — so they act on the fleet, in proportion."""

    def test_a_fleet_discharge_draws_from_every_pool(self) -> None:
        s = _store()
        s.charge("b1", 3.0, 0.0, import_rate=0.10)     # all solar
        s.charge("b2", 0.0, 1.0, import_rate=0.20)     # all grid
        mix = s.discharge_fleet(2.0)
        assert mix.solar_kwh == pytest.approx(1.5)
        assert mix.grid_kwh == pytest.approx(0.5)
        assert mix.grid_cost == pytest.approx(0.10)
        assert _total(s, "b1") == pytest.approx(1.5)
        assert _total(s, "b2") == pytest.approx(0.5)

    def test_an_empty_fleet_discharges_unknown(self) -> None:
        s = _store()
        assert s.discharge_fleet(2.0).unknown_kwh == pytest.approx(2.0)

    def test_the_fleet_reconciles_to_the_measured_soc(self) -> None:
        s = _store()
        s.charge("b1", 4.0, 0.0, import_rate=0.10)
        s.charge("b2", 0.0, 4.0, import_rate=0.10)
        s.reconcile_fleet_to_stored(4.0)               # SOC says 4, pool says 8
        assert _total(s, "b1") + _total(s, "b2") == pytest.approx(4.0)
        assert s.fleet_grid_fraction() == pytest.approx(0.5)

    def test_a_missing_fleet_soc_does_nothing(self) -> None:
        s = _store()
        s.charge("b1", 2.0, 0.0, import_rate=0.10)
        s.reconcile_fleet_to_stored(None)
        assert _total(s, "b1") == pytest.approx(2.0)

    def test_an_empty_fleet_reconciles_into_unknown(self) -> None:
        """A battery SEM never watched fill is not full of free solar."""
        s = _store()
        s.reconcile_fleet_to_stored(6.0)
        assert s.discharge_fleet(6.0).unknown_kwh == pytest.approx(6.0)


class TestWhatAStoredKwhIsWorth:
    def test_an_empty_pool_is_worth_the_import_rate(self) -> None:
        """Legacy answer. SEM knows nothing, so the number does not move."""
        assert _store().implied_savings_rate(0.28) == pytest.approx(0.28)

    def test_a_solar_pool_is_worth_the_import_rate(self) -> None:
        s = _store()
        s.charge("b1", 5.0, 0.0, import_rate=0.28)
        assert s.implied_savings_rate(0.28) == pytest.approx(0.28)

    def test_a_bought_pool_is_worth_only_the_spread(self) -> None:
        s = _store()
        s.charge("b1", 0.0, 5.0, import_rate=0.11)
        assert s.implied_savings_rate(0.28) == pytest.approx(0.17)


class TestTheStoreSurvivesARestart:
    def test_round_trip(self) -> None:
        s = _store()
        s.charge("b1", 3.0, 2.0, import_rate=0.12)
        s.charge("b2", 0.0, 1.0, import_rate=0.30)
        state = s.get_state()

        restored = _store()
        restored.restore_state(state)
        assert _total(restored, "b1") == pytest.approx(5.0)
        assert _grid_frac(restored, "b1") == pytest.approx(0.4)
        assert _avg_grid_cost(restored, "b2") == pytest.approx(0.30)

    def test_junk_state_is_ignored_not_fatal(self) -> None:
        s = _store()
        s.restore_state({"pools": {"b1": {"solar_kwh": "nonsense"}}})
        assert _total(s, "b1") == 0.0


# ───────────────────────────────────────────────────────────────────────
# 2. the fleet split
# ───────────────────────────────────────────────────────────────────────

class TestTheFleetSplitFollowsThePower:
    """The flow layer attributes solar/grid for the FLEET. Which physical
    battery got the solar electrons is unknowable, so the fleet's split is
    allocated in proportion to each battery's charge power — the same
    honesty as the discharge draw."""

    def test_an_equal_split_for_equally_charging_batteries(self) -> None:
        from custom_components.solar_energy_management.coordinator.battery_provenance import (
            allocate_fleet_charge,
        )
        alloc = allocate_fleet_charge(
            {"b1": 1000.0, "b2": 1000.0}, solar_kwh=2.0, grid_kwh=1.0,
        )
        assert alloc["b1"] == pytest.approx((1.0, 0.5))
        assert alloc["b2"] == pytest.approx((1.0, 0.5))

    def test_the_bigger_draw_takes_the_bigger_share(self) -> None:
        from custom_components.solar_energy_management.coordinator.battery_provenance import (
            allocate_fleet_charge,
        )
        alloc = allocate_fleet_charge(
            {"b1": 3000.0, "b2": 1000.0}, solar_kwh=4.0, grid_kwh=0.0,
        )
        assert alloc["b1"][0] == pytest.approx(3.0)
        assert alloc["b2"][0] == pytest.approx(1.0)

    def test_a_battery_that_is_not_charging_gets_nothing(self) -> None:
        from custom_components.solar_energy_management.coordinator.battery_provenance import (
            allocate_fleet_charge,
        )
        alloc = allocate_fleet_charge(
            {"b1": 2000.0, "b2": 0.0}, solar_kwh=2.0, grid_kwh=0.0,
        )
        assert alloc["b2"] == pytest.approx((0.0, 0.0))

    def test_no_charging_at_all_allocates_nothing(self) -> None:
        from custom_components.solar_energy_management.coordinator.battery_provenance import (
            allocate_fleet_charge,
        )
        assert allocate_fleet_charge({"b1": 0.0}, 1.0, 1.0) == {"b1": (0.0, 0.0)}

    def test_a_single_unnamed_battery_still_gets_the_whole_split(self) -> None:
        """The common install has one battery and no per-battery sensors."""
        from custom_components.solar_energy_management.coordinator.battery_provenance import (
            allocate_fleet_charge,
        )
        alloc = allocate_fleet_charge({}, solar_kwh=2.0, grid_kwh=1.0)
        assert alloc == {"fleet": (2.0, 1.0)}


# ───────────────────────────────────────────────────────────────────────
# 3. the ledger rows
# ───────────────────────────────────────────────────────────────────────

def _calc(**cfg):
    from custom_components.solar_energy_management.coordinator.energy_calculator import (
        EnergyCalculator,
    )
    return EnergyCalculator(cfg, MagicMock())


class TestTheLedgerKeepsTheSplit:
    def test_charge_is_filed_by_source(self) -> None:
        c = _calc()
        c.accumulate_battery_charge_split(2.0, 1.0, TODAY)
        rows = c.get_battery_charge_split(TODAY)
        assert rows["solar_today_kwh"] == pytest.approx(2.0)
        assert rows["grid_today_kwh"] == pytest.approx(1.0)

    def test_the_split_sums_to_the_total_charge(self) -> None:
        c = _calc()
        c.accumulate_battery_charge_split(2.0, 1.0, TODAY)
        c.accumulate_battery_charge_split(1.5, 0.5, TODAY)
        rows = c.get_battery_charge_split(TODAY)
        assert rows["solar_today_kwh"] + rows["grid_today_kwh"] == pytest.approx(5.0)

    def test_the_split_has_the_longer_horizons_too(self) -> None:
        c = _calc()
        c.accumulate_battery_charge_split(2.0, 1.0, TODAY)
        rows = c.get_battery_charge_split(TODAY)
        assert rows["grid_month_kwh"] == pytest.approx(1.0)
        assert rows["grid_year_kwh"] == pytest.approx(1.0)
        assert rows["grid_total_kwh"] == pytest.approx(1.0)

    def test_nothing_charged_files_nothing(self) -> None:
        c = _calc()
        c.accumulate_battery_charge_split(0.0, 0.0, TODAY)
        assert c.get_battery_charge_split(TODAY)["solar_today_kwh"] == 0.0


# ───────────────────────────────────────────────────────────────────────
# 4. what the split is FOR
# ───────────────────────────────────────────────────────────────────────

class TestSavingsPayForWhatTheEnergyCost:
    def test_a_solar_kwh_saves_the_whole_import_price(self) -> None:
        from custom_components.solar_energy_management.coordinator.battery_provenance import (
            discharge_savings,
        )
        from custom_components.solar_energy_management.coordinator.battery_provenance import (
            DischargeMix,
        )
        mix = DischargeMix(solar_kwh=1.0, grid_kwh=0.0, grid_cost=0.0)
        assert discharge_savings(mix, import_rate=0.28) == pytest.approx(0.28)

    def test_a_grid_kwh_saves_only_the_spread(self) -> None:
        """The number in the issue: bought at 0.11, discharged against
        0.28 → 0.17 saved, not 0.28."""
        from custom_components.solar_energy_management.coordinator.battery_provenance import (
            DischargeMix, discharge_savings,
        )
        mix = DischargeMix(solar_kwh=0.0, grid_kwh=1.0, grid_cost=0.11)
        assert discharge_savings(mix, import_rate=0.28) == pytest.approx(0.17)

    def test_a_losing_arbitrage_is_reported_as_a_loss(self) -> None:
        """Bought at 0.30, discharged against 0.20. Clamping this to zero
        would hide exactly the mistake the user needs to see."""
        from custom_components.solar_energy_management.coordinator.battery_provenance import (
            DischargeMix, discharge_savings,
        )
        mix = DischargeMix(solar_kwh=0.0, grid_kwh=1.0, grid_cost=0.30)
        assert discharge_savings(mix, import_rate=0.20) == pytest.approx(-0.10)

    def test_unknown_energy_keeps_the_legacy_credit(self) -> None:
        """We don't know, so we don't change the number — but we count the
        kWh so #773 can audit how much of the total rests on that."""
        from custom_components.solar_energy_management.coordinator.battery_provenance import (
            DischargeMix, discharge_savings,
        )
        mix = DischargeMix(unknown_kwh=2.0)
        assert discharge_savings(mix, import_rate=0.25) == pytest.approx(0.50)


class TestAutarkyStopsCountingBoughtEnergyAsOwn:
    def test_a_solar_charged_battery_is_own_supply(self) -> None:
        c = _calc()
        flows = MagicMock(
            solar_to_home=4.0, solar_to_ev=0.0,
            battery_to_home=4.0, battery_to_ev=0.0,
            grid_to_home=2.0, grid_to_ev=0.0,
        )
        from custom_components.solar_energy_management.coordinator.types import (
            EnergyTotals,
        )
        m = c.calculate_performance(
            MagicMock(), EnergyTotals(daily_solar=10.0), flows
        )
        assert m.autarky_rate == pytest.approx(80.0)

    def test_a_grid_charged_battery_is_not(self) -> None:
        """Same flows, but the battery's stored energy was bought. The
        discharged kWh are grid supply that was merely time-shifted."""
        c = _calc()
        c.set_battery_grid_origin_share(1.0)
        flows = MagicMock(
            solar_to_home=4.0, solar_to_ev=0.0,
            battery_to_home=4.0, battery_to_ev=0.0,
            grid_to_home=2.0, grid_to_ev=0.0,
        )
        from custom_components.solar_energy_management.coordinator.types import (
            EnergyTotals,
        )
        m = c.calculate_performance(
            MagicMock(), EnergyTotals(daily_solar=10.0), flows
        )
        assert m.autarky_rate == pytest.approx(40.0)

    def test_a_half_grid_battery_lands_in_between(self) -> None:
        c = _calc()
        c.set_battery_grid_origin_share(0.5)
        flows = MagicMock(
            solar_to_home=4.0, solar_to_ev=0.0,
            battery_to_home=4.0, battery_to_ev=0.0,
            grid_to_home=2.0, grid_to_ev=0.0,
        )
        from custom_components.solar_energy_management.coordinator.types import (
            EnergyTotals,
        )
        m = c.calculate_performance(
            MagicMock(), EnergyTotals(daily_solar=10.0), flows
        )
        assert m.autarky_rate == pytest.approx(60.0)

    def test_self_consumption_is_untouched(self) -> None:
        """(solar − export) / solar never involved the battery's provenance
        — it was already right, and #770 must not 'fix' it."""
        c = _calc()
        c.set_battery_grid_origin_share(1.0)
        from custom_components.solar_energy_management.coordinator.types import (
            EnergyTotals,
        )
        m = c.calculate_performance(
            MagicMock(),
            EnergyTotals(daily_solar=10.0, daily_grid_export=2.0), None,
        )
        assert m.self_consumption_rate == pytest.approx(80.0)


# ───────────────────────────────────────────────────────────────────────
# 5. the surface
# ───────────────────────────────────────────────────────────────────────

class TestTheRowSurfaces:
    KEYS = (
        "daily_battery_charge_solar",
        "daily_battery_charge_grid",
        "battery_stored_grid_share",
        "daily_battery_grid_cost",
    )

    def test_the_keys_are_published(self) -> None:
        """The four keys the user sees. Note where each one lives: the two
        kWh rows are energy, the money is a cost and the share is a
        performance figure. The published NAMES are the contract — the
        dataclass a field sits on is not, and moving one must not rename an
        entity out from under an install."""
        from custom_components.solar_energy_management.coordinator.types import (
            CostData, EnergyTotals, PerformanceMetrics, SEMData,
        )
        data = SEMData()
        data.energy = EnergyTotals(
            daily_battery_charge_solar=3.0,
            daily_battery_charge_grid=1.0,
        )
        data.costs = CostData(daily_battery_grid_cost=0.11)
        data.performance = PerformanceMetrics(battery_stored_grid_share=25.0)
        d = data.to_dict()
        assert d["daily_battery_charge_solar"] == 3.0
        assert d["daily_battery_charge_grid"] == 1.0
        assert d["battery_stored_grid_share"] == 25.0
        assert d["daily_battery_grid_cost"] == 0.11

    def test_every_key_has_an_entity(self) -> None:
        from custom_components.solar_energy_management import sensor as sensor_mod

        keys = {d.key for d in sensor_mod.SENSOR_TYPES}
        for k in self.KEYS:
            assert k in keys, f"{k} is published but has no entity (#666)"

    def test_every_key_is_labelled(self) -> None:
        from custom_components.solar_energy_management.consts.labels import (
            SENSOR_LABEL_MAPPING,
        )
        for k in self.KEYS:
            assert k in SENSOR_LABEL_MAPPING, f"{k} has no label"


# ───────────────────────────────────────────────────────────────────────
# 6. the seam — none of the above matters unless the cycle uses it
# ───────────────────────────────────────────────────────────────────────

class TestTheCycleFilesTheSplit:
    """``calculate_energy`` is the only place the ledger is written. A store
    that nobody charges and a split that nobody files are just code."""

    # 120 s is the integration cap (``MAX_INTEGRATION_GAP_SECONDS``); a
    # longer step is discarded as a sensor restart. 3000 W over 120 s is
    # 0.1 kWh, which keeps every number below round.
    STEP_S = 120

    @staticmethod
    def _cfg():
        return {
            "update_interval": 120,
            "electricity_import_rate": 0.30,
            "battery_capacity_kwh": 10.0,
        }

    def _run(self, calc, mock_dt, minute, **kw):
        from custom_components.solar_energy_management.coordinator.types import (
            PowerReadings, PowerFlows,
        )
        from datetime import datetime
        mock_dt.now.return_value = datetime(2026, 8, 14, 12, minute, 0)
        flows = PowerFlows(
            solar_to_battery=kw.pop("solar_to_battery", 0.0),
            grid_to_battery=kw.pop("grid_to_battery", 0.0),
        )
        return calc.calculate_energy(PowerReadings(**kw), flows)

    def _calc(self, mock_dt):
        """A calculator anchored on an idle cycle with an EMPTY battery.

        SOC is the pool's anchor: 10 kWh capacity at 1 % is 0.1 kWh, which is
        exactly what one 120 s cycle at 3000 W puts in. So every charge below
        lands on a battery whose measured contents SEM fully accounts for —
        no unknown remainder to blur the arithmetic.
        """
        from custom_components.solar_energy_management.coordinator.energy_calculator import (
            EnergyCalculator,
        )
        c = EnergyCalculator(self._cfg(), MagicMock())
        self._run(c, mock_dt, 0, battery_soc=0.0)
        return c

    @staticmethod
    def _savings(calc):
        return calc._daily_cost_accumulators.get(
            "cost_batt_savings_2026-08-14", 0.0
        )

    # The money and the stored-share are published by the builders that own
    # those types, not by ``calculate_energy`` (#666: a currency in the
    # ``daily_*`` energy namespace passes the accumulator sweep vacuously).
    # Both read the same accumulators the cycle just wrote.

    @staticmethod
    def _grid_cost(calc, energy):
        return calc.calculate_costs(energy).daily_battery_grid_cost

    @staticmethod
    def _stored_share(calc, energy):
        from custom_components.solar_energy_management.coordinator.types import (
            PowerReadings,
        )
        return calc.calculate_performance(
            PowerReadings(), energy,
        ).battery_stored_grid_share

    @patch(_DT)
    def test_the_charge_is_filed_by_origin(self, mock_dt) -> None:
        c = self._calc(mock_dt)
        e = self._run(
            c, mock_dt, 2,
            battery_charge_power=3000.0, battery_soc=1.0,
            solar_to_battery=1500.0, grid_to_battery=1500.0,
        )
        assert e.daily_battery_charge_solar == pytest.approx(0.05, abs=0.002)
        assert e.daily_battery_charge_grid == pytest.approx(0.05, abs=0.002)

    @patch(_DT)
    def test_what_the_bought_part_cost_is_recorded(self, mock_dt) -> None:
        c = self._calc(mock_dt)
        e = self._run(
            c, mock_dt, 2,
            battery_charge_power=3000.0, battery_soc=1.0,
            grid_to_battery=3000.0,
        )
        assert self._grid_cost(c, e) == pytest.approx(0.03, abs=0.002)

    @patch(_DT)
    def test_a_grid_charged_discharge_does_not_save_the_full_price(
        self, mock_dt,
    ) -> None:
        """The number the whole issue is about. A kWh bought at 0.30 and
        discharged against 0.30 saved NOTHING — it was moved, not made."""
        c = self._calc(mock_dt)
        self._run(
            c, mock_dt, 2,
            battery_charge_power=3000.0, battery_soc=1.0,
            grid_to_battery=3000.0,
        )
        before = self._savings(c)
        self._run(
            c, mock_dt, 4,
            battery_discharge_power=3000.0, battery_soc=1.0,
        )
        assert self._savings(c) - before == pytest.approx(0.0, abs=0.002)

    @patch(_DT)
    def test_a_solar_charged_discharge_still_saves_the_full_price(
        self, mock_dt,
    ) -> None:
        c = self._calc(mock_dt)
        self._run(
            c, mock_dt, 2,
            battery_charge_power=3000.0, battery_soc=1.0,
            solar_to_battery=3000.0,
        )
        before = self._savings(c)
        self._run(
            c, mock_dt, 4,
            battery_discharge_power=3000.0, battery_soc=1.0,
        )
        assert self._savings(c) - before == pytest.approx(0.03, abs=0.002)

    @patch(_DT)
    def test_the_stored_share_reaches_the_row(self, mock_dt) -> None:
        c = self._calc(mock_dt)
        e = self._run(
            c, mock_dt, 2,
            battery_charge_power=3000.0, battery_soc=1.0,
            grid_to_battery=3000.0,
        )
        assert self._stored_share(c, e) == pytest.approx(100.0, abs=0.5)

    @patch(_DT)
    def test_a_silent_soc_sensor_does_not_reconcile(self, mock_dt) -> None:
        """#755 contract 1. An offline SOC sensor is not a measurement of an
        empty battery, and reconciling to it would wipe the cost basis."""
        from custom_components.solar_energy_management.coordinator.battery_provenance import (
            FLEET_KEY,
        )
        c = self._calc(mock_dt)
        self._run(
            c, mock_dt, 2,
            battery_charge_power=3000.0, battery_soc=1.0,
            grid_to_battery=3000.0,
        )
        self._run(
            c, mock_dt, 4,
            battery_soc=0.0, battery_soc_unavailable=True,
        )
        assert _total(c._battery_provenance, FLEET_KEY) > 0.0
        assert _grid_frac(c._battery_provenance, FLEET_KEY) == \
            pytest.approx(1.0)

    @patch(_DT)
    def test_a_skipped_cycle_reads_the_row_back_instead_of_zeroing_it(
        self, mock_dt,
    ) -> None:
        """A gap longer than the integration limit skips the arithmetic — it
        does not mean the battery emptied and forgot what it cost. Every
        other row on that path is read back from the accumulators; the
        provenance row must be too, or the sensors flap to zero for one
        cycle after every sensor stall."""
        c = self._calc(mock_dt)
        charged = self._run(
            c, mock_dt, 2,
            battery_charge_power=3000.0, battery_soc=1.0,
            grid_to_battery=3000.0,
        )
        # 58 minutes later: past MAX_INTEGRATION_GAP_SECONDS, so
        # calculate_energy returns the accumulated totals untouched.
        skipped = self._run(c, mock_dt, 59, battery_soc=1.0)
        assert skipped.daily_battery_charge == charged.daily_battery_charge
        assert skipped.daily_battery_charge_grid == \
            charged.daily_battery_charge_grid
        assert skipped.daily_battery_charge_solar == \
            charged.daily_battery_charge_solar
        # The money and the share come from builders that run every cycle
        # regardless of the gap, so they are steady by construction — pinned
        # here anyway, because that is the property the user experiences.
        assert self._grid_cost(c, skipped) == self._grid_cost(c, charged)
        assert self._stored_share(c, skipped) == \
            self._stored_share(c, charged)

    @patch(_DT)
    def test_the_cost_basis_survives_a_restart(self, mock_dt) -> None:
        from custom_components.solar_energy_management.coordinator.energy_calculator import (
            EnergyCalculator,
        )
        from custom_components.solar_energy_management.coordinator.battery_provenance import (
            FLEET_KEY,
        )
        c = self._calc(mock_dt)
        self._run(
            c, mock_dt, 2,
            battery_charge_power=3000.0, battery_soc=1.0,
            grid_to_battery=3000.0,
        )
        state = c.get_state()
        fresh = EnergyCalculator(self._cfg(), MagicMock())
        fresh.restore_state(state)
        assert _grid_frac(fresh._battery_provenance, FLEET_KEY) == \
            pytest.approx(1.0)
        # ...and it survives the STORE, not just the calculator's own
        # round-trip. A key the calculator emits but ``storage`` does not
        # carry reads back as its default — no error, no log line (#668).
        # Here that would silently re-credit every purchase at the full
        # import price after each restart, which is the bug this whole row
        # exists to fix. The #658 guard caught it the day it was written.
        from custom_components.solar_energy_management.coordinator.storage import (
            CALCULATOR_STATE_KEYS,
        )
        assert "battery_provenance" in CALCULATOR_STATE_KEYS
