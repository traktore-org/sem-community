"""#628 — daily home consumption is the reconciled residual, not a stopwatch.

Home is the one row nothing meters. Every other row has hardware behind it;
home is *by definition* what is left when the metered rows are subtracted from
each other::

    home = solar + import − export + discharge − charge − EV

SEM evaluated that identity INSTANTANEOUSLY — in watts, every cycle — and
integrated the result. That is the last open column of #628, and it is not a
mistake in any single place: home is a SMALL difference of LARGE terms, so it
inherits their relative error magnified by the ratio between them.

Two independent installs say the same thing. On the developer's own PROD
hardware (Huawei SUN2000 + LUNA2000 + KEBA), where solar, grid and battery each
agree with their meters to ≤0.5 %, daily home for 25–31 July 2026 still landed
−8 % to +15 % off the meter-derived figure — in BOTH directions, which rules out
a one-way clamp or a missing sample. On #628's reporter's install, solar/import/
export all match to ~1.0× while home reads 28.7 vs 36.3 kWh.

So the daily row stops being sampled and starts being derived. Lifetime home
(``seed_lifetime_from_hardware``) and yearly home (``seed_yearly_from_statistics``)
were ALREADY seeded from exactly this balance; only the daily row was still a
stopwatch, and only the daily row was wrong.

The property these tests pin is stronger than "home is more accurate": SEM's
seven daily numbers now ADD UP. Home is the exact residual of the six rows
published beside it, each independently pinned to the user's own counters.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import Mock

import pytest
from freezegun import freeze_time

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EV_CATEGORY,
    MIDNIGHT_EV_CATEGORY,
    MAX_PLAUSIBLE_DAILY_KWH,
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings
from custom_components.solar_energy_management.utils.time_manager import TimeManager

DAY = date(2026, 7, 15)

SOLAR = "sensor.inverter_total_yield"
IMPORT = "sensor.p1_import"
EXPORT = "sensor.p1_export"
BATT_IN = "sensor.bms_charged"
BATT_OUT = "sensor.bms_discharged"
WALLBOX = "sensor.wallbox_total_energy"

METERS = {
    "solar": SOLAR,
    "grid_import": IMPORT,
    "grid_export": EXPORT,
    "battery_charge": BATT_IN,
    "battery_discharge": BATT_OUT,
}
ALL_CATEGORIES = tuple(METERS)


def _hass(values: dict) -> Mock:
    """Mock hass whose states track ``values`` LIVE, so a test can move a
    counter between cycles the way real hardware does."""
    hass = Mock()
    hass.data = {}
    hass.config = Mock()
    hass.config.config_dir = "/config"

    def _get(entity_id):
        if entity_id not in values:
            return None
        state = Mock()
        state.state = str(values[entity_id])
        state.attributes = {"unit_of_measurement": "kWh"}
        return state

    hass.states.get = _get
    return hass


def _rig(
    rows: dict,
    *,
    metered=ALL_CATEGORIES,
    enabled: bool = True,
    ev_counter: bool = False,
    ev_kwh: float = 0.0,
    update_interval: int = 10,
):
    """A calculator whose daily rows already hold ``rows``, with counters wired
    for ``metered``.

    Seeding the rows and leaving the counters at 0 is the honest shape of a
    mid-day cycle: the first reconcile anchors each category on the value the
    integrator already had, its counter delta is 0, and the row is unchanged —
    but now COUNTER-BACKED, which is the precondition the home balance reads.
    """
    values = {METERS[cat]: 0.0 for cat in metered}
    hass = _hass(values)
    calc = EnergyCalculator({"update_interval": update_interval}, TimeManager(hass))
    calc.configure_solar_counters(
        hass, [SOLAR] if "solar" in metered else [], enabled
    )
    calc.configure_meter_counters(
        hass,
        {cat: [METERS[cat]] for cat in metered if cat != "solar"},
        enabled,
    )
    if ev_counter:
        values[WALLBOX] = 0.0
        calc.configure_ev_counters(hass, [WALLBOX], enabled)
    for category, kwh in rows.items():
        calc._daily_accumulators[f"{category}_{DAY}"] = kwh
    if ev_kwh:
        calc._daily_accumulators[f"{MIDNIGHT_EV_CATEGORY}_{DAY}"] = ev_kwh
    # Past the upgrade day — see ``TestUpgradeDay`` for the guard itself.
    calc._midnight_ev_since = DAY - timedelta(days=1)
    return calc, values


def _cycle(calc: EnergyCalculator, **power):
    """One cycle. ``_last_update`` is cleared so the configured interval is
    used: these tests compress hours into consecutive statements, and a >120 s
    apparent gap would make ``calculate_energy`` skip the cycle entirely
    (accumulator-spike guard) — silently skipping the code under test."""
    calc._last_update = None
    readings = PowerReadings(**power)
    readings.calculate_derived()
    return calc.calculate_energy(readings)


# A day with the shape that breaks the stopwatch: a 34 kWh residual carried by
# a 53 kWh solar term. Numbers rounded from the developer's PROD hardware,
# 31 July 2026, where SEM's integrated home came back 3.2 kWh (−9 %) low.
BIG_DAY = {
    "solar": 53.80,
    "grid_import": 1.20,
    "grid_export": 20.30,
    "battery_charge": 8.00,
    "battery_discharge": 6.90,
}
BIG_DAY_HOME = 53.80 + 1.20 - 20.30 + 6.90 - 8.00  # 33.60


@pytest.mark.unit
@freeze_time("2026-07-15 12:00:00")
class TestTheBalance628:
    def test_the_balance_can_actually_fire(self):
        """Bug class 8 at birth: every assertion below would pass vacuously if
        the balance never ran, so first prove the switch has two positions. The
        OFF position is not hypothetical — it is what shipped until now, and it
        is still what an install without ``prefer_hardware_energy`` gets."""
        off, _ = _rig({**BIG_DAY, "home": 30.0}, enabled=False)
        assert _cycle(off).daily_home == 30.0, "disabled balance overrode the row"

        on, _ = _rig({**BIG_DAY, "home": 30.0})
        assert _cycle(on).daily_home == pytest.approx(BIG_DAY_HOME, abs=0.01)

    def test_home_is_the_residual_of_the_reconciled_rows(self):
        """THE issue. Whatever the integrator sampled its way to, the published
        row is the balance of the six rows beside it."""
        calc, _ = _rig({**BIG_DAY, "home": 30.42})
        energy = _cycle(calc)

        assert energy.daily_home == pytest.approx(BIG_DAY_HOME, abs=0.01)
        assert (
            energy.daily_solar
            + energy.daily_grid_import
            - energy.daily_grid_export
            + energy.daily_battery_discharge
            - energy.daily_battery_charge
            - energy.daily_home
        ) == pytest.approx(0.0, abs=0.01), "the seven published rows do not add up"

    def test_the_residual_no_longer_inherits_the_integrator(self):
        """The magnification property, stated as a test: two installs whose
        integrators drifted in OPPOSITE directions land on the same number,
        because the number no longer comes from the integrator at all."""
        low, _ = _rig({**BIG_DAY, "home": 30.40})   # −9 %, the 31 Jul shape
        high, _ = _rig({**BIG_DAY, "home": 38.60})  # +15 %, the 27 Jul shape
        assert _cycle(low).daily_home == _cycle(high).daily_home

    def test_a_material_correction_moves_month_year_and_lifetime(self):
        """One call writes the daily row, so one call corrects every period —
        the #666 lesson. A month that keeps the old daily sum is a month that
        disagrees with the days inside it."""
        calc, _ = _rig({**BIG_DAY, "home": 30.00})
        for accumulators, key in (
            (calc._monthly_accumulators, "home_2026_7"),
            (calc._yearly_accumulators, "home_2026"),
            (calc._lifetime_accumulators, "lifetime_home"),
        ):
            accumulators[key] = 100.0

        _cycle(calc)

        delta = BIG_DAY_HOME - 30.00  # +3.60
        assert calc._monthly_accumulators["home_2026_7"] == pytest.approx(100 + delta)
        assert calc._yearly_accumulators["home_2026"] == pytest.approx(100 + delta)
        assert calc._lifetime_accumulators["lifetime_home"] == pytest.approx(100 + delta)

    def test_a_longer_period_is_never_dragged_below_zero(self):
        """The delta is bidirectional now. One day's downward correction must
        not push a month negative — the same guard the metered rows carry."""
        calc, _ = _rig({**BIG_DAY, "home": 90.00})  # wildly over
        calc._monthly_accumulators["home_2026_7"] = 1.0
        _cycle(calc)
        assert calc._monthly_accumulators["home_2026_7"] == 0.0


@pytest.mark.unit
@freeze_time("2026-07-15 12:00:00")
class TestTheGate628:
    def test_a_present_unmetered_term_stands_the_balance_down(self):
        """#628's own rule applied to a residual. With no battery counters, a
        real 6.9 kWh of discharge is a number nobody checked — deriving home
        from it would launder the integrator's error into a figure that LOOKS
        meter-backed. The integrator keeps the row instead."""
        calc, _ = _rig(
            {**BIG_DAY, "home": 30.00},
            metered=("solar", "grid_import", "grid_export"),
        )
        assert _cycle(calc).daily_home == 30.00

    def test_an_absent_term_does_not_stand_the_balance_down(self):
        """The other half, and the reason for the epsilon: an install with no
        battery integrates 0 kWh of charge all day. That zero is not an
        unverified number, it is the absence of a flow, and demanding a BMS
        counter of it would disable the balance on every battery-less install
        for nothing."""
        rows = {
            "solar": 40.0, "grid_import": 5.0, "grid_export": 12.0,
            "battery_charge": 0.0, "battery_discharge": 0.0, "home": 28.0,
        }
        calc, _ = _rig(rows, metered=("solar", "grid_import", "grid_export"))
        assert _cycle(calc).daily_home == pytest.approx(33.0, abs=0.01)

    def test_a_partial_counter_set_is_not_counter_backed(self):
        """Completeness, not availability. A two-string install with one
        inverter unavailable has a solar row that is only PARTLY the
        hardware's; the home residual would silently absorb the difference."""
        values = {SOLAR: 0.0, "sensor.inverter_b_total_yield": 0.0}
        hass = _hass(values)
        calc = EnergyCalculator({"update_interval": 10}, TimeManager(hass))
        calc.configure_solar_counters(
            hass, [SOLAR, "sensor.inverter_b_total_yield"], True
        )
        calc.configure_meter_counters(
            hass,
            {c: [METERS[c]] for c in ALL_CATEGORIES if c != "solar"},
            True,
        )
        for cat, kwh in {**BIG_DAY, "home": 30.0}.items():
            calc._daily_accumulators[f"{cat}_{DAY}"] = kwh
        calc._midnight_ev_since = DAY - timedelta(days=1)
        for entity in (IMPORT, EXPORT, BATT_IN, BATT_OUT):
            values[entity] = 0.0

        del values["sensor.inverter_b_total_yield"]  # one inverter drops out
        assert _cycle(calc).daily_home == 30.0

    def test_the_balance_stands_down_continuously_not_with_a_jump(self):
        """Standing down hands the row back to the integrator — which resumes
        from wherever the balance left the accumulator, not from some stale
        parallel total. A discontinuity here would be a visible step in a
        TOTAL sensor and read as a new bug."""
        calc, values = _rig({**BIG_DAY, "home": 30.00})
        assert _cycle(calc).daily_home == pytest.approx(BIG_DAY_HOME, abs=0.01)

        del values[IMPORT]  # the P1 meter goes unavailable
        resumed = _cycle(calc, solar_power=1000.0, grid_export_power=1000.0)
        assert resumed.daily_home == pytest.approx(BIG_DAY_HOME, abs=0.01)

    def test_a_negative_balance_clamps_and_says_so(self):
        """The house always draws ≥ 0, so the clamp stays — but what it REMOVED
        is recorded (#660). A sustained engagement means one of the six rows is
        signed wrong, and that is a finding, not a number to hide."""
        rows = {
            "solar": 1.0, "grid_import": 0.0, "grid_export": 20.0,
            "battery_charge": 0.0, "battery_discharge": 0.0, "home": 5.0,
        }
        calc, _ = _rig(rows)
        assert _cycle(calc).daily_home == 0.0
        assert calc.clamp_engagement["daily_home_balance"] == pytest.approx(19.0)

    def test_an_implausible_balance_is_refused_not_published(self):
        """A counter in the wrong magnitude (Wh read as kWh) must not become a
        1000× home figure. Refusing the cycle leaves the integrator's row.

        Probed through GRID IMPORT deliberately: solar and battery are already
        held to a physical ceiling derived from the configured hardware before
        the balance ever reads them, so they cannot carry an absurd term in.
        Grid has no such ceiling — a house can legitimately import any amount —
        which makes it the one leg where this guard is still the last line."""
        rows = {**BIG_DAY, "grid_import": MAX_PLAUSIBLE_DAILY_KWH - 1, "home": 30.0}
        calc, _ = _rig(rows)
        assert _cycle(calc).daily_home == 30.0

    def test_a_row_already_on_the_balance_is_left_alone(self):
        """Dead band. Once adopted the balance recomputes every cycle, and
        rewriting the accumulator for a 0.01 kWh difference would be pure
        churn on a value that is already right."""
        calc, _ = _rig({**BIG_DAY, "home": BIG_DAY_HOME + 0.02})
        assert _cycle(calc).daily_home == pytest.approx(BIG_DAY_HOME + 0.02, abs=0.005)


@pytest.mark.unit
class TestTheEvTerm628:
    """The day-boundary half. ``EV_CATEGORY`` rolls at the charge deadline
    (#279); daily home is a CALENDAR-day quantity. Composing a midnight row out
    of a deadline row is exactly the bug class closed in #703/#704."""

    @freeze_time("2026-07-15 03:00:00")
    def test_the_ev_term_is_the_calendar_mirror_not_the_deadline_bucket(self):
        """A car charging at 03:00 belongs to the calendar day it is charging
        on. The deadline bucket still holds last evening's session too — and
        subtracting THAT from today's balance would eat 10 kWh of the house's
        consumption."""
        rows = {
            "solar": 0.0, "grid_import": 20.0, "grid_export": 0.0,
            "battery_charge": 0.0, "battery_discharge": 0.0, "home": 0.0,
        }
        calc, _ = _rig(rows, update_interval=3600)
        ev_day = calc._ev_reset_day(__import__(
            "homeassistant.util.dt", fromlist=["now"]).now())
        assert ev_day != DAY, "harness broken — the two day keys must differ here"
        calc._daily_accumulators[f"{EV_CATEGORY}_{ev_day}"] = 10.0  # last evening

        energy = _cycle(calc, ev_power=7000.0)  # one hour at 7 kW

        assert calc._daily_accumulators[f"{EV_CATEGORY}_{ev_day}"] == pytest.approx(17.0)
        assert calc._daily_accumulators[
            f"{MIDNIGHT_EV_CATEGORY}_{DAY}"] == pytest.approx(7.0)
        # 20 imported, 7 into the car → 13 for the house. Not 3.
        assert energy.daily_home == pytest.approx(13.0, abs=0.01)

    @freeze_time("2026-07-15 03:00:00")
    def test_the_mirror_never_reaches_a_longer_period(self):
        """DAILY-ONLY by design. Monthly, yearly and lifetime EV are owned by
        the one deadline-keyed bucket, so there is still a single EV total in
        the system and the mirror cannot double-count into any of them."""
        calc, _ = _rig({}, update_interval=3600)
        _cycle(calc, ev_power=7000.0)

        assert calc._daily_accumulators[
            f"{MIDNIGHT_EV_CATEGORY}_{DAY}"] == pytest.approx(7.0)
        for accumulators in (
            calc._monthly_accumulators,
            calc._yearly_accumulators,
            calc._lifetime_accumulators,
        ):
            assert not [
                k for k in accumulators if MIDNIGHT_EV_CATEGORY in k
            ], f"the daily-only mirror leaked into {accumulators}"
        assert calc._monthly_accumulators["ev_2026_7"] == pytest.approx(7.0)

    @freeze_time("2026-07-15 12:00:00")
    def test_the_mirror_name_survives_the_midnight_rollover_rule(self):
        """``_check_rollover`` keeps any key starting ``ev_`` across midnight,
        because those roll at the deadline. The mirror MUST roll at midnight,
        which is the whole reason its category is not spelled ``ev_midnight``.
        A rename that forgot this would silently freeze the term for a day."""
        calc, _ = _rig({})
        calc._daily_accumulators[f"{MIDNIGHT_EV_CATEGORY}_{DAY - timedelta(days=1)}"] = 9.0
        _cycle(calc)
        assert f"{MIDNIGHT_EV_CATEGORY}_{DAY - timedelta(days=1)}" not in (
            calc._daily_accumulators
        )

    @freeze_time("2026-07-15 12:00:00")
    def test_the_mirror_recovers_charging_sem_did_not_see(self):
        """The mirror carries the same counter reconciliation as its sibling —
        otherwise a charge during SEM downtime would be missing from the EV
        term and land in the house's column instead."""
        calc, values = _rig({}, ev_counter=True)
        _cycle(calc)                      # baseline at 0
        values[WALLBOX] = 6.0             # charged while SEM was not integrating
        _cycle(calc)
        assert calc._daily_accumulators[
            f"{MIDNIGHT_EV_CATEGORY}_{DAY}"] == pytest.approx(6.0)


@pytest.mark.unit
@freeze_time("2026-07-15 12:00:00")
class TestUpgradeDay628:
    def test_the_upgrade_day_keeps_the_integrator(self):
        """The mirror only knows the charging it has watched. On the first
        cycle after an upgrade it is born mid-day while every other row already
        holds the whole day, so subtracting it would credit the car's morning
        charge to the house — a 20 kWh error on exactly the day people look."""
        calc, _ = _rig({**BIG_DAY, "home": 30.00})
        calc._midnight_ev_since = None  # as an upgraded install arrives
        assert _cycle(calc).daily_home == 30.00
        assert calc._midnight_ev_since == DAY

    def test_the_day_after_the_upgrade_derives(self):
        calc, _ = _rig({**BIG_DAY, "home": 30.00})
        calc._midnight_ev_since = DAY - timedelta(days=1)
        assert _cycle(calc).daily_home == pytest.approx(BIG_DAY_HOME, abs=0.01)

    def test_a_restart_is_not_an_upgrade(self):
        """``midnight_ev_since`` must survive the store, or every restart would
        look like the upgrade day and suppress the balance forever."""
        calc, _ = _rig({**BIG_DAY, "home": 30.00})
        calc._midnight_ev_baselines = {"date": str(DAY), "base": {WALLBOX: 3.0}}
        state = calc.get_state()

        restored, _ = _rig({**BIG_DAY, "home": 30.00})
        restored._midnight_ev_since = None
        restored.restore_state(state)

        assert restored._midnight_ev_since == DAY - timedelta(days=1)
        assert restored._midnight_ev_baselines["base"] == {WALLBOX: 3.0}
        assert _cycle(restored).daily_home == pytest.approx(BIG_DAY_HOME, abs=0.01)


@pytest.mark.unit
@freeze_time("2026-07-15 12:00:00")
class TestReviewFindings628:
    """Cases raised by review of this change, kept because each one pins a
    property the implementation could lose again silently."""

    def test_the_battery_cap_lands_before_the_balance_reads_it(self):
        """The physical-limit caps are the sanity net for the metered rows, and
        home is DERIVED from those rows — so the net has to be in place before
        the derivation, not after it. Ordered the other way, one corrupt BMS
        register publishes a bogus house figure for a cycle before the cap that
        exists to prevent exactly that gets its turn."""
        calc, _ = _rig({**BIG_DAY, "battery_discharge": 90.00, "home": 30.00})
        calc.config["battery_capacity_kwh"] = 15  # → 45 kWh/day ceiling
        capped = 53.80 + 1.20 - 20.30 + 45.00 - 8.00

        for _ in range(2):  # stable, not a one-cycle coincidence
            energy = _cycle(calc)
            assert energy.daily_battery_discharge == 45.00
            assert energy.daily_home == pytest.approx(capped, abs=0.01)

    def test_a_charger_change_drops_the_mirror_baselines_in_place(self):
        """A charger added mid-run re-anchors the fleet bucket; the mirror
        tracks the SAME entity set and has to follow, or the two drift. And it
        must be emptied IN PLACE — ``_reconcile_ev_bucket`` holds this dict by
        reference, so rebinding would leave it writing to an orphan."""
        calc, _ = _rig({}, ev_counter=True)
        calc._midnight_ev_baselines.update(
            {"date": str(DAY), "base": {WALLBOX: 4.0}, "last": {WALLBOX: 4.0}}
        )
        held = calc._midnight_ev_baselines

        calc.configure_ev_counters(
            _hass({}), [WALLBOX, "sensor.second_wallbox"], True
        )

        assert calc._midnight_ev_baselines is held, "rebound, not cleared"
        assert held == {}

    def test_a_mid_day_restart_credits_the_counter_advance(self):
        """The gap a restart leaves is the mirror's whole reason to carry a
        counter: charging SEM did not watch still has to leave the house's
        column. Pins the delta across the store, not just the anchor."""
        calc, values = _rig({}, ev_counter=True)
        _cycle(calc)
        values[WALLBOX] = 4.0
        _cycle(calc)
        assert calc._daily_accumulators[
            f"{MIDNIGHT_EV_CATEGORY}_{DAY}"] == pytest.approx(4.0)
        state = calc.get_state()

        restored, rvalues = _rig({}, ev_counter=True)
        restored.restore_state(state)
        rvalues[WALLBOX] = 6.5  # kept charging while SEM was down
        _cycle(restored)

        assert restored._daily_accumulators[
            f"{MIDNIGHT_EV_CATEGORY}_{DAY}"] == pytest.approx(6.5)

    def test_a_mirror_counter_that_resets_re_anchors(self):
        """Plenty of wallboxes expose a DAILY counter that returns to zero on
        its own schedule. Read as a delta that is a large negative number, and
        the EV term — which the balance SUBTRACTS — would hand the car's whole
        day to the house."""
        calc, values = _rig({}, ev_counter=True)
        mirror = f"{MIDNIGHT_EV_CATEGORY}_{DAY}"
        _cycle(calc)
        values[WALLBOX] = 5.0
        _cycle(calc)
        assert calc._daily_accumulators[mirror] == pytest.approx(5.0)

        values[WALLBOX] = 0.0  # the counter rolls
        _cycle(calc)
        assert calc._daily_accumulators[mirror] == pytest.approx(5.0)

        values[WALLBOX] = 2.0  # and carries on from there
        _cycle(calc)
        assert calc._daily_accumulators[mirror] == pytest.approx(7.0)

    def test_real_export_without_an_export_meter_stands_the_balance_down(self):
        """The likeliest partial install: everything declared in the Energy
        Dashboard except the export leg. Export is genuinely happening, so it
        is present-and-unmetered — the balance must stand down rather than
        treat a 20 kWh term it cannot verify as zero."""
        calc, _ = _rig(
            {**BIG_DAY, "home": 30.00},
            metered=("solar", "grid_import", "battery_charge", "battery_discharge"),
        )
        assert _cycle(calc).daily_home == 30.00
