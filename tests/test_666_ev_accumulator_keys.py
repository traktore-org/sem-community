"""#666 — the accumulator category an entity is WRITTEN under must be the one
it is READ back under.

``EnergyCalculator._accumulate(category, ...)`` writes four keys in one call —
``<cat>_<day>``, ``<cat>_<month>``, ``<cat>_<year>`` and ``lifetime_<cat>``.
Every read is a separate ``_get_*(category, ...)`` call with the category
spelled out again at the call site. Nothing joins the two: a disagreement
produces no error, no log line and no missing entity — just a sensor frozen at
whatever it was last seeded with.

EV was written under ``ev_daily_sun`` while **four** independent sites (both
yearly reads, the recorder year-seeding, and the reconcile's monthly write) had
each guessed the obvious ``ev``. Live on PROD: ``daily_ev = 10.77 kWh`` with
``yearly_ev = 0.0``. Since ``_accumulate`` increments daily and yearly in the
SAME call, that pair of readings is not circumstantial — it is only reachable
if the read key and the write key differ.

The category is now the constant ``EV_CATEGORY``, and the sunrise/deadline
boundary lives in the day KEY where a boundary belongs, not in the namespace.

The guard below is the invariant that would have caught this on the day it was
written, and it is deliberately NOT a list of category strings to keep in sync
(that is the same class of bug one level up). It drives off the ``EnergyTotals``
dataclass: run one real integration cycle with every flow non-zero, then assert
that for every ``daily_X`` field, its ``monthly_X`` / ``yearly_X`` siblings
moved too. A future category whose read and write keys drift apart fails here
without anyone remembering to add it.
"""
from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock

import pytest
from freezegun import freeze_time

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EV_CATEGORY,
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.types import (
    EnergyTotals,
    PowerFlows,
    PowerReadings,
    SEMData,
)
from custom_components.solar_energy_management.utils.time_manager import TimeManager

_PERIODS = ("daily", "monthly", "yearly")


def _make_calc() -> EnergyCalculator:
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    # 120 s (the integration-gap ceiling) is the first cycle's assumed interval.
    # Deliberately the longest legal one: ``_get_daily`` rounds to 2 decimals,
    # so at a 30 s interval a 500 W flow reads back as a genuine 0.0 and the
    # probe would accuse itself of the very mismatch it is looking for.
    return EnergyCalculator({"update_interval": 120}, TimeManager(hass))


def _categories() -> list[str]:
    """Every category that publishes a daily total, from the dataclass itself."""
    names = {f.name for f in dataclasses.fields(EnergyTotals)}
    return sorted(n[len("daily_"):] for n in names if n.startswith("daily_"))


def _run_one_cycle(calc: EnergyCalculator) -> EnergyTotals:
    """One integration cycle with EVERY flow non-zero.

    Not physically simultaneous (a house does not import and export at once) —
    that is the point: this is a key-plumbing probe, not a scenario. Each
    category must integrate so that a read/write mismatch anywhere shows up.

    ``power_flows`` is passed for the same reason (#770). Categories fed by
    the flow layer rather than by a raw power reading — the battery
    charge-origin split is the first — integrate only when it is supplied.
    Omitting it left them silently at zero, so the sweep below could not have
    caught a key mismatch in any of them: a guard that cannot fail on half
    its own parameter set. Same bug class the guard exists to catch, one
    level up.
    """
    power = PowerReadings(solar_power=5000.0, ev_power=3000.0)
    power.calculate_derived()
    power.home_consumption_power = 2000.0
    power.grid_import_power = 4000.0
    power.grid_export_power = 3500.0
    power.battery_charge_power = 2500.0
    power.battery_discharge_power = 2000.0
    flows = PowerFlows(solar_to_battery=1500.0, grid_to_battery=1000.0)
    return calc.calculate_energy(power, flows)


@pytest.mark.unit
class TestAccumulatorKeyRoundTrip666:
    @freeze_time("2026-07-15 12:00:00")
    def test_the_probe_actually_integrates(self):
        """Bug class 8, applied at birth: if the cycle silently integrated
        nothing, every assertion below would pass vacuously."""
        totals = _run_one_cycle(_make_calc())
        assert totals.daily_solar > 0, "probe integrated nothing — cycle broke"
        assert len(_categories()) == 9, (
            f"expected 9 daily categories, found {_categories()} — if a "
            "category was added or removed, confirm the guard still covers it"
        )

    @freeze_time("2026-07-15 12:00:00")
    @pytest.mark.parametrize("category", _categories())
    def test_daily_monthly_yearly_move_together(self, category):
        """THE closure. One ``_accumulate`` call writes all periods at once, so
        any period sitting at zero while its daily sibling moved means the read
        key does not match the write key."""
        totals = _run_one_cycle(_make_calc())
        moved = {
            period: getattr(totals, f"{period}_{category}")
            for period in _PERIODS
            if hasattr(totals, f"{period}_{category}")
        }
        assert moved["daily"] > 0, f"daily_{category} did not integrate"
        stuck = [p for p, v in moved.items() if v == 0]
        assert not stuck, (
            f"{[f'{p}_{category}' for p in stuck]} stayed at 0 while "
            f"daily_{category} reached {moved['daily']:.4f}. _accumulate writes "
            "daily, monthly and yearly in ONE call — a period at zero means the "
            f"read key disagrees with the write key for '{category}' (#666)."
        )

    @freeze_time("2026-07-15 12:00:00")
    def test_ev_publishes_all_three_periods(self):
        """Pinned by name as well as by the sweep: monthly_ev was the field
        that never existed, so ``monthly_ev_consumption`` — declared in the
        label registry all along — had no sensor to attach to."""
        totals = _run_one_cycle(_make_calc())
        assert totals.daily_ev > 0
        assert totals.monthly_ev > 0
        assert totals.yearly_ev > 0
        # ...and it reaches the entity layer: the sensor reads the published
        # dict, so a field with no to_dict entry is still an invisible one.
        published = SEMData(energy=totals).to_dict()
        assert published["monthly_ev_consumption_energy"] == totals.monthly_ev

    @freeze_time("2026-07-15 12:00:00")
    def test_ev_is_written_under_the_plain_category(self):
        """The boundary belongs in the day key, not the namespace."""
        calc = _make_calc()
        _run_one_cycle(calc)
        assert EV_CATEGORY == "ev"
        assert any(k.startswith("ev_") for k in calc._daily_accumulators)
        assert not any("ev_daily_sun" in k for k in calc._daily_accumulators)
        assert calc._lifetime_accumulators.get("lifetime_ev", 0.0) > 0


@pytest.mark.unit
class TestLegacyKeyMigration666:
    """Existing installs have ``ev_daily_sun_*`` on disk. The rename must not
    orphan their history."""

    def test_daily_monthly_yearly_and_lifetime_are_all_renamed(self):
        calc = _make_calc()
        calc.restore_state({
            "daily_accumulators": {"ev_daily_sun_2026-07-15": 10.77, "solar_2026-07-15": 8.0},
            "monthly_accumulators": {"ev_daily_sun_2026_7": 120.0},
            "yearly_accumulators": {"ev_daily_sun_2026": 900.0},
            "lifetime_accumulators": {"lifetime_ev_daily_sun": 2500.0},
        })
        assert calc._daily_accumulators == {"ev_2026-07-15": 10.77, "solar_2026-07-15": 8.0}
        assert calc._monthly_accumulators == {"ev_2026_7": 120.0}
        assert calc._yearly_accumulators == {"ev_2026": 900.0}
        assert calc._lifetime_accumulators == {"lifetime_ev": 2500.0}

    def test_the_migration_can_actually_fire(self):
        """Without it, the restored history is unreadable — this is the
        pre-fix world, and the reason the migration is not optional."""
        raw = {"ev_daily_sun_2026": 900.0}
        calc = _make_calc()
        calc._yearly_accumulators = dict(raw)  # as if restored unmigrated
        assert calc._get_yearly(EV_CATEGORY, "2026") == 0.0
        assert EnergyCalculator._migrate_ev_keys(raw) == {"ev_2026": 900.0}

    def test_it_is_idempotent_and_a_no_op_once_clean(self):
        clean = {"ev_2026": 900.0, "solar_2026": 8.0}
        once = EnergyCalculator._migrate_ev_keys(clean)
        assert once == clean
        assert EnergyCalculator._migrate_ev_keys(once) == clean
        # A clean store is returned unchanged, not rebuilt.
        assert once is clean

    def test_a_collision_sums_rather_than_letting_one_win(self):
        """Impossible by construction, but both halves are real integrated
        energy — dropping either would lose kWh the user actually used."""
        merged = EnergyCalculator._migrate_ev_keys(
            {"ev_daily_sun_2026": 400.0, "ev_2026": 500.0}
        )
        assert merged == {"ev_2026": 900.0}

    def test_it_survives_a_missing_or_malformed_store(self):
        assert EnergyCalculator._migrate_ev_keys({}) == {}
        assert EnergyCalculator._migrate_ev_keys(None) == {}
