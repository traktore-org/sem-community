"""#1295 — lifetime totals above 100 MWh were dropped at each restart.

A Dutch P1 meter counts since it was fitted: the #1294 home's import counter
read 122,342 kWh. The store's load check dropped every row above 100 MWh, a
bound made for a Wh value read as kWh (#563). It dropped
``lifetime_grid_import`` (122,341.9) and ``lifetime_home`` (102,101.6) at the
09:20 restart. The seed then raised import back to its counter, and the home,
gone, was rebuilt from that one step: 122,342 kWh, at every restart.

The same bound dropped money: a year's cost in yen or forint, a month's in
rupiah, passes 100,000 in a normal home.

Fix: a lifetime total has no fixed bound; the seed compares it with its own
counter (#551). Cost rows are money and have none either. A missing lifetime
home is rebuilt from the counters' balance, and a home the old bound hurt is
rebuilt once.
"""
from __future__ import annotations

import ast
import inspect
import math
import textwrap
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator import storage as storage_mod
from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.storage import SEMStorage
from custom_components.solar_energy_management.consts.core import MAX_PLAUSIBLE_DAILY_KWH
from custom_components.solar_energy_management.ha_energy_reader import (
    EnergyDashboardConfig,
)

# The #1294 home: a P1 import counter since the meter was fitted.
IMPORT = 122_341.9
EXPORT = 40_000.0
SOLAR = 19_759.7
HOME = 102_101.6          # SOLAR + IMPORT − EXPORT
COUNTERS = {
    "sensor.p1_import": IMPORT,
    "sensor.p1_export": EXPORT,
    "sensor.inverter_kwh": SOLAR,
}


def _state(value, unit="kWh"):
    return SimpleNamespace(state=str(value), attributes={"unit_of_measurement": unit})


def _ed():
    cfg = EnergyDashboardConfig()
    for category, ids in (
        ("solar", ["sensor.inverter_kwh"]), ("grid_import", ["sensor.p1_import"]),
        ("grid_export", ["sensor.p1_export"]), ("battery_charge", []),
        ("battery_discharge", []),
    ):
        setattr(cfg, f"{category}_energy_list", list(ids))
        setattr(cfg, f"{category}_energy", ids[0] if ids else None)
    return cfg


def _hass(values):
    hass = MagicMock()
    hass.is_running = True
    hass.states.get = lambda eid: _state(values[eid]) if eid in values else None
    return hass


def _calc():
    return EnergyCalculator(config={}, time_manager=MagicMock())


def _storage(daily=None):
    hass = MagicMock()
    with patch.object(storage_mod, "Store") as store_cls:
        store_cls.side_effect = [MagicMock(), MagicMock()]
        s = SEMStorage(hass, "entry")
    s._energy_store = MagicMock()
    s._energy_store.async_load = AsyncMock(return_value=None)
    s._daily_store = MagicMock()
    s._daily_store.async_load = AsyncMock(return_value=daily)
    return s


def _lifetime(calc, key):
    return calc._lifetime_accumulators.get(f"lifetime_{key}")


async def _restart(daily, values=COUNTERS):
    """Load ``daily`` the way setup does, then run the first lifetime seed."""
    store = _storage(daily)
    await store.async_load()
    calc = _calc()
    calc.restore_state(store.export_energy_calculator_state())
    calc.seed_lifetime_from_hardware(_hass(values), _ed())
    return calc


def _saved(lifetime, **extra):
    return {
        "baselines": {}, "daily_accumulators": {}, "monthly_accumulators": {},
        "yearly_accumulators": {}, "lifetime_accumulators": dict(lifetime),
        "lifetime_seed_counters": {
            "solar": ["sensor.inverter_kwh"], "grid_import": ["sensor.p1_import"],
            "grid_export": ["sensor.p1_export"], "battery_charge": [],
            "battery_discharge": [],
        },
        **extra,
    }


def _good_lifetime(home=HOME + 250.0):
    return {
        "lifetime_solar": SOLAR, "lifetime_grid_import": IMPORT,
        "lifetime_grid_export": EXPORT, "lifetime_home": home,
    }


# ── the store keeps a lifetime total above 100 MWh ─────────────────────


@pytest.mark.unit
class TestStoreKeepsLifetime:
    @pytest.mark.asyncio
    async def test_the_reporter_values_survive_the_load(self):
        store = _storage(_saved(_good_lifetime(HOME)))
        await store.async_load()
        lifetime = store.export_energy_calculator_state()["lifetime_accumulators"]
        assert lifetime["lifetime_grid_import"] == IMPORT
        assert lifetime["lifetime_home"] == HOME

    @pytest.mark.parametrize("acc_key", ["lifetime_accumulators"])
    @pytest.mark.parametrize("validator", ["_validate_daily_data", "_validate_energy_data"])
    def test_both_stores_keep_a_large_lifetime(self, validator, acc_key):
        data = {acc_key: {"lifetime_grid_import": 1_500_000.0}}
        assert getattr(SEMStorage, validator)(data) is True
        assert data[acc_key] == {"lifetime_grid_import": 1_500_000.0}

    @pytest.mark.parametrize("acc_key, value", [
        ("yearly_cost_accumulators", 180_000.0),     # forint or yen, one year
        ("monthly_cost_accumulators", 650_000.0),    # rupiah, one month
        ("daily_cost_accumulators", 180_000.0),      # dong, one day with a car
    ])
    def test_money_has_no_kwh_bound(self, acc_key, value):
        data = {acc_key: {"cost_2026": value}}
        assert SEMStorage._validate_daily_data(data) is True
        assert data[acc_key] == {"cost_2026": value}

    @pytest.mark.parametrize("acc_key, too_big", [
        ("daily_accumulators", 150_000.0), ("monthly_accumulators", 150_000.0),
        ("yearly_accumulators", 5_000_000.0),
    ])
    def test_a_period_row_keeps_its_bound(self, acc_key, too_big):
        """#563's bound stays where a home's kWh cannot reach it."""
        data = {acc_key: {"solar_2026": too_big, "home_2026": 12.5}}
        assert SEMStorage._validate_daily_data(data) is True
        assert data[acc_key] == {"home_2026": 12.5}

    def test_a_large_array_keeps_its_year(self):
        """About 100 kWp makes 150 MWh in a year: kept."""
        data = {"yearly_accumulators": {"solar_2026": 150_000.0}}
        assert SEMStorage._validate_daily_data(data) is True
        assert data["yearly_accumulators"] == {"solar_2026": 150_000.0}

    def test_no_period_bound_is_below_what_its_days_can_hold(self):
        """A row's bound sits above the most the daily ceiling lets in."""
        bounds = storage_mod.ACCUMULATOR_ROW_BOUNDS
        for acc_key, days in (("daily_accumulators", 1), ("monthly_accumulators", 31),
                              ("yearly_accumulators", 366)):
            assert bounds[acc_key] >= days * MAX_PLAUSIBLE_DAILY_KWH, acc_key

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, "12", None])
    @pytest.mark.parametrize("acc_key", sorted(storage_mod.ACCUMULATOR_ROW_BOUNDS))
    def test_no_number_is_dropped_in_every_row(self, acc_key, bad):
        data = {acc_key: {"lifetime_solar": bad, "keep": 3.0}}
        assert SEMStorage._validate_daily_data(data) is True
        assert data[acc_key] == {"keep": 3.0}


@pytest.mark.unit
class TestEveryRowSaysItsBound:
    """Guard: a row the store repairs states its own bound — none is the
    100 MWh bound by default."""

    def test_every_calculator_row_is_listed(self):
        rows = {k for k in storage_mod.CALCULATOR_STATE_KEYS if k.endswith("_accumulators")}
        assert rows
        assert rows <= set(storage_mod.ACCUMULATOR_ROW_BOUNDS)

    def test_lifetime_and_money_have_no_bound(self):
        bounds = storage_mod.ACCUMULATOR_ROW_BOUNDS
        assert bounds["lifetime_accumulators"] is None
        for key in bounds:
            if "cost" in key:
                assert bounds[key] is None, key

    def test_the_validators_repair_every_listed_row(self):
        for validator in ("_validate_daily_data", "_validate_energy_data"):
            for acc_key in storage_mod.ACCUMULATOR_ROW_BOUNDS:
                data = {acc_key: {"bad": "x"}}
                getattr(SEMStorage, validator)(data)
                assert data[acc_key] == {}, (validator, acc_key)

    def test_no_literal_bound_in_the_repair(self):
        """The bound comes from the table, never a number in the loop."""
        src = textwrap.dedent(inspect.getsource(SEMStorage._repair_accumulator_dicts))
        numbers = [
            n.value for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
            and not isinstance(n.value, bool) and abs(n.value) >= 1_000
        ]
        assert numbers == []


# ── the restart, through the store and the seed ─────────────────────────


@pytest.mark.unit
class TestRestartKeepsTheHome:
    @pytest.mark.asyncio
    async def test_a_store_from_this_build_keeps_its_home(self):
        """Saved by this build: the home moved on its own after the seed. A
        restart keeps it, and import stays at its counter."""
        lifetime = _good_lifetime()
        calc = await _restart(_saved(lifetime, lifetime_home_checked=True))
        assert _lifetime(calc, "grid_import") == pytest.approx(IMPORT)
        assert _lifetime(calc, "home") == pytest.approx(HOME + 250.0)

    @pytest.mark.asyncio
    async def test_ten_restarts_keep_the_home(self):
        calc = await _restart(_saved(_good_lifetime(), lifetime_home_checked=True))
        for _ in range(10):
            state = calc.get_state()
            store = _storage(dict(state, baselines={}))
            await store.async_load()
            calc = _calc()
            calc.restore_state(store.export_energy_calculator_state())
            calc.seed_lifetime_from_hardware(_hass(COUNTERS), _ed())
        assert _lifetime(calc, "home") == pytest.approx(HOME + 250.0)
        assert _lifetime(calc, "grid_import") == pytest.approx(IMPORT)

    @pytest.mark.asyncio
    async def test_a_home_the_old_bound_hurt_is_rebuilt_once(self):
        """The reporter's store after an old-build restart: the home was
        rebuilt from the import step alone. The first seed of this build
        rebuilds it from the counters' balance, once."""
        hurt = _good_lifetime(home=IMPORT + 3.0)
        calc = await _restart(_saved(hurt))
        assert _lifetime(calc, "home") == pytest.approx(HOME)
        assert calc._lifetime_home_checked is True

        calc._lifetime_accumulators["lifetime_home"] += 40.0   # the house ran
        state = calc.get_state()
        assert state["lifetime_home_checked"] is True
        store = _storage(dict(state, baselines={}))
        await store.async_load()
        later = _calc()
        later.restore_state(store.export_energy_calculator_state())
        later.seed_lifetime_from_hardware(_hass(COUNTERS), _ed())
        assert _lifetime(later, "home") == pytest.approx(HOME + 40.0)

    @pytest.mark.asyncio
    async def test_a_home_below_the_old_bound_is_not_touched(self):
        """No row and no counter reached 100 MWh: the old bound never ran,
        so the home is kept as it is."""
        small = {"sensor.p1_import": 9_000.0, "sensor.p1_export": 4_000.0,
                 "sensor.inverter_kwh": 6_000.0}
        lifetime = {"lifetime_solar": 6_000.0, "lifetime_grid_import": 9_000.0,
                    "lifetime_grid_export": 4_000.0, "lifetime_home": 11_500.0}
        calc = await _restart(_saved(lifetime), values=small)
        assert _lifetime(calc, "home") == pytest.approx(11_500.0)
        assert calc._lifetime_home_checked is True

    @pytest.mark.asyncio
    async def test_a_hurt_home_only_the_balance_shows_is_rebuilt(self):
        """The old bound dropped the home alone (no counter above 100 MWh):
        the seed raised nothing, so the home restarted near 0."""
        values = {"sensor.p1_import": 70_000.0, "sensor.p1_export": 10_000.0,
                  "sensor.inverter_kwh": 45_000.0}
        lifetime = {"lifetime_solar": 45_000.0, "lifetime_grid_import": 70_000.0,
                    "lifetime_grid_export": 10_000.0, "lifetime_home": 3.5}
        calc = await _restart(_saved(lifetime), values=values)
        assert _lifetime(calc, "home") == pytest.approx(105_000.0)


    @pytest.mark.asyncio
    async def test_an_ev_home_just_past_the_bound_is_not_touched(self):
        """No total ever passed 100 MWh; the balance did, by the car's kWh
        the live home leaves out. The old bound never ran: kept."""
        values = {"sensor.p1_import": 65_000.0, "sensor.p1_export": 20_000.0,
                  "sensor.inverter_kwh": 60_000.0}
        lifetime = {"lifetime_solar": 60_000.0, "lifetime_grid_import": 65_000.0,
                    "lifetime_grid_export": 20_000.0, "lifetime_home": 97_000.0}
        calc = await _restart(_saved(lifetime), values=values)
        assert _lifetime(calc, "home") == pytest.approx(97_000.0)
        assert calc._lifetime_home_checked is True

    @pytest.mark.asyncio
    async def test_the_check_reads_the_totals_the_rebuild_reads(self):
        """A counter below its saved total (an inverter left the dashboard):
        the rebuild reads the saved 60 MWh, so the check must too."""
        values = {"sensor.p1_import": 70_000.0, "sensor.p1_export": 20_000.0,
                  "sensor.inverter_kwh": 35_000.0}
        lifetime = {"lifetime_solar": 60_000.0, "lifetime_grid_import": 70_000.0,
                    "lifetime_grid_export": 20_000.0, "lifetime_home": 3.5}
        calc = await _restart(_saved(lifetime), values=values)
        assert _lifetime(calc, "solar") == pytest.approx(60_000.0)
        assert _lifetime(calc, "home") == pytest.approx(110_000.0)


@pytest.mark.unit
class TestMissingHomeIsRebuilt:
    def test_a_missing_home_comes_from_the_balance(self):
        """A home that is gone (a row with no number) is rebuilt from every
        counter, not from the raised steps alone."""
        calc = _calc()
        calc._lifetime_home_checked = True
        calc._lifetime_seed_counters = {
            "solar": ["sensor.inverter_kwh"], "grid_import": ["sensor.p1_import"],
            "grid_export": ["sensor.p1_export"], "battery_charge": [],
            "battery_discharge": [],
        }
        calc._lifetime_accumulators.update({
            "lifetime_solar": SOLAR, "lifetime_grid_export": EXPORT,
        })
        calc.seed_lifetime_from_hardware(_hass(COUNTERS), _ed())
        assert _lifetime(calc, "grid_import") == pytest.approx(IMPORT)
        assert _lifetime(calc, "home") == pytest.approx(HOME)

    def test_a_missing_home_with_nothing_to_raise(self):
        calc = _calc()
        calc._lifetime_home_checked = True
        calc._lifetime_seed_counters = {
            "solar": ["sensor.inverter_kwh"], "grid_import": ["sensor.p1_import"],
            "grid_export": ["sensor.p1_export"], "battery_charge": [],
            "battery_discharge": [],
        }
        calc._lifetime_accumulators.update({
            "lifetime_solar": SOLAR, "lifetime_grid_import": IMPORT,
            "lifetime_grid_export": EXPORT,
        })
        calc.seed_lifetime_from_hardware(_hass(COUNTERS), _ed())
        assert _lifetime(calc, "home") == pytest.approx(HOME)

    def test_a_present_home_still_moves_by_the_raised_step(self):
        """#1043 unchanged: a home that holds its history moves by the step."""
        calc = _calc()
        calc._lifetime_home_checked = True
        calc._lifetime_seed_counters = {
            "solar": ["sensor.inverter_kwh"], "grid_import": ["sensor.p1_import"],
            "grid_export": ["sensor.p1_export"], "battery_charge": [],
            "battery_discharge": [],
        }
        calc._lifetime_accumulators.update({
            "lifetime_solar": SOLAR, "lifetime_grid_import": 1_000.0,
            "lifetime_grid_export": EXPORT, "lifetime_home": 500.0,
        })
        calc.seed_lifetime_from_hardware(_hass(COUNTERS), _ed())
        assert _lifetime(calc, "home") == pytest.approx(500.0 + IMPORT - 1_000.0)


@pytest.mark.unit
class TestInflatedLifetimeStillHealed:
    @pytest.mark.asyncio
    async def test_a_wh_read_as_kwh_total_is_healed_by_its_counter(self):
        """#563's case now reaches the seed: the #551 heal sets it from the
        counter, and the home from the balance."""
        inflated = {
            "lifetime_solar": SOLAR * 1000, "lifetime_grid_import": IMPORT * 1000,
            "lifetime_grid_export": EXPORT * 1000, "lifetime_home": 55.0,
        }
        calc = await _restart(_saved(inflated))
        assert _lifetime(calc, "solar") == pytest.approx(SOLAR)
        assert _lifetime(calc, "grid_import") == pytest.approx(IMPORT)
        assert _lifetime(calc, "home") == pytest.approx(HOME)
        assert calc._lifetime_home_checked is True


@pytest.mark.unit
class TestTheFlagIsSaved:
    def test_the_store_carries_it(self):
        assert "lifetime_home_checked" in storage_mod.CALCULATOR_STATE_KEYS

    @pytest.mark.parametrize("saved, expected", [
        (True, True), (False, False), (None, False), ("yes", False), (1, False),
    ])
    def test_it_restores_as_a_bool(self, saved, expected):
        calc = _calc()
        calc.restore_state({"lifetime_home_checked": saved})
        assert calc._lifetime_home_checked is expected
