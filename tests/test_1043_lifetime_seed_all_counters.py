"""#1043 — the lifetime seed added up the FIRST Energy Dashboard counter only.

RienduPre (2.1, Growatt, dual-tariff meter, three solar counters):
``sem_lifetime_co2_avoided`` 260.9 kg while ``sem_yearly_co2_avoided`` was
610.4 kg — the lifetime figure below one year of itself.

Two faults, one seed:

* grid and battery were seeded from the scalar ``*_energy`` field, which is the
  first source only — tariff 1 of a dual-tariff meter. Solar was summed (#556);
  the yearly seed and the monthly energy query read the scalar for all five.
* a counter still loading read as 0, so the sum of three solar counters was the
  first one alone and looked complete. That number then passed every check —
  and against a GOOD stored value it fired the #551 downward heal, shrinking a
  correct lifetime to the one inverter that had loaded.

The reporter's numbers: solar 12,388 + 27,870 + 20,343 = 60,601 kWh (SEM held
12,396), export T1 10,358 + T2 24,838 = 35,196 kWh (SEM held ≈ 10,357).
"""
from __future__ import annotations

import ast
import inspect
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator import (
    energy_calculator as ec_module,
)
from custom_components.solar_energy_management.coordinator.energy_calculator import (
    GRID_CO2_KG_PER_KWH,
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.repair_issues import (
    UNAVAILABLE_REPAIR_THRESHOLD_S,
)
from custom_components.solar_energy_management.ha_energy_reader import (
    EnergyDashboardConfig,
    energy_counters,
)

SOLAR = {"sensor.inv1_kwh": 12_388.0, "sensor.inv2_kwh": 27_870.0, "sensor.inv3_kwh": 20_343.0}
IMPORT = {"sensor.import_t1": 4_100.0, "sensor.import_t2": 5_900.0}
EXPORT = {"sensor.export_t1": 10_358.0, "sensor.export_t2": 24_838.0}
CHARGE = {"sensor.batt_charge": 3_000.0}
DISCHARGE = {"sensor.batt_discharge": 2_700.0}


def _state(value, unit="kWh"):
    return SimpleNamespace(state=str(value), attributes={"unit_of_measurement": unit})


def _ed(solar=SOLAR, imp=IMPORT, exp=EXPORT, charge=CHARGE, discharge=DISCHARGE):
    """A real ``EnergyDashboardConfig`` filled the way the reader fills it:
    every source in the list, the scalar = the first one."""
    cfg = EnergyDashboardConfig()
    for category, ids in (
        ("solar", list(solar)), ("grid_import", list(imp)),
        ("grid_export", list(exp)), ("battery_charge", list(charge)),
        ("battery_discharge", list(discharge)),
    ):
        setattr(cfg, f"{category}_energy_list", list(ids))
        setattr(cfg, f"{category}_energy", ids[0] if ids else None)
    return cfg


def _values(**overrides):
    values = {**SOLAR, **IMPORT, **EXPORT, **CHARGE, **DISCHARGE}
    values.update(overrides)
    return values


def _hass(values, running=True):
    """``values``: entity → number, or a string state (``"unavailable"``).
    An entity not in ``values`` has no state at all."""
    hass = MagicMock()
    hass.is_running = running
    hass.states.get = lambda eid: _state(values[eid]) if eid in values else None
    return hass


def _calc():
    return EnergyCalculator(config={}, time_manager=MagicMock())


def _lifetime(calc, key):
    return calc._lifetime_accumulators.get(f"lifetime_{key}", 0.0)


# ── the helper ───────────────────────────────────────────────────────────


@pytest.mark.unit
class TestEnergyCounters:
    def test_list_wins_over_the_scalar(self):
        assert energy_counters(_ed(), "grid_export") == ["sensor.export_t1", "sensor.export_t2"]

    def test_scalar_is_the_fallback(self):
        cfg = SimpleNamespace(grid_import_energy="sensor.only")
        assert energy_counters(cfg, "grid_import") == ["sensor.only"]
        assert energy_counters(SimpleNamespace(), "grid_import") == []

    def test_a_mock_without_lists_falls_back_and_drops_non_strings(self):
        cfg = MagicMock()
        cfg.solar_energy = "sensor.pv"
        assert energy_counters(cfg, "solar") == ["sensor.pv"]
        assert energy_counters(MagicMock(), "solar") == []

    def test_duplicates_are_read_once(self):
        cfg = SimpleNamespace(solar_energy_list=["sensor.a", "sensor.a", "sensor.b"])
        assert energy_counters(cfg, "solar") == ["sensor.a", "sensor.b"]


# ── the lifetime seed ────────────────────────────────────────────────────


@pytest.mark.unit
class TestLifetimeSeedSumsEveryCounter:
    def test_fresh_seed_adds_every_tariff_and_inverter(self):
        """The reporter's install, seeded from scratch."""
        calc = _calc()
        calc.seed_lifetime_from_hardware(_hass(_values()), _ed())

        assert calc._lifetime_seeded is True
        assert _lifetime(calc, "solar") == pytest.approx(60_601)
        assert _lifetime(calc, "grid_export") == pytest.approx(35_196)
        assert _lifetime(calc, "grid_import") == pytest.approx(10_000)
        assert _lifetime(calc, "battery_charge") == pytest.approx(3_000)
        assert _lifetime(calc, "battery_discharge") == pytest.approx(2_700)
        # home = solar + import + discharge − export − charge
        assert _lifetime(calc, "home") == pytest.approx(60_601 + 10_000 + 2_700 - 35_196 - 3_000)

    def test_lifetime_co2_is_no_longer_below_one_year(self):
        """The symptom: (12,396 − 10,357) × 0.128 = 261 kg. Every counter:
        (60,601 − 35,196) × 0.128 ≈ 3,252 kg."""
        calc = _calc()
        calc.seed_lifetime_from_hardware(_hass(_values()), _ed())
        self_consumed = calc._get_lifetime("solar") - calc._get_lifetime("grid_export")
        assert self_consumed * GRID_CO2_KG_PER_KWH == pytest.approx(3_251.8, abs=0.1)

    def test_a_seed_from_before_1043_heals(self):
        """The reporter's stored state: first inverter + tariff 1 only, no
        record of the counters. It re-seeds from the full sums."""
        calc = _calc()
        calc._lifetime_accumulators.update({
            "lifetime_solar": 12_396.0, "lifetime_grid_import": 4_100.0,
            "lifetime_grid_export": 10_357.0, "lifetime_battery_charge": 3_000.0,
            "lifetime_battery_discharge": 2_700.0,
        })
        calc.seed_lifetime_from_hardware(_hass(_values()), _ed())
        assert _lifetime(calc, "solar") == pytest.approx(60_601)
        assert _lifetime(calc, "grid_export") == pytest.approx(35_196)

    def test_a_first_tariff_seed_above_half_heals_too(self):
        """The half-of-hardware check alone does not catch tariff 1 when it is
        the bigger half — here every stored value is ≥ 55 % of the sum, so the
        old checks found nothing to fix. No record + a two-counter list does,
        and the home balance moves by the same amounts."""
        imp = {"sensor.import_t1": 6_000.0, "sensor.import_t2": 4_000.0}
        exp = {"sensor.export_t1": 6_000.0, "sensor.export_t2": 5_000.0}
        solar = {"sensor.pv": 20_000.0}
        values = {**solar, **imp, **exp, **CHARGE, **DISCHARGE}
        calc = _calc()
        calc._lifetime_accumulators.update({
            "lifetime_solar": 20_100.0, "lifetime_grid_import": 6_000.0,
            "lifetime_grid_export": 6_000.0, "lifetime_battery_charge": 3_000.0,
            "lifetime_battery_discharge": 2_700.0, "lifetime_home": 19_800.0,
            "lifetime_ev": 1_234.0,
        })
        calc.seed_lifetime_from_hardware(_hass(values), _ed(solar=solar, imp=imp, exp=exp))
        assert _lifetime(calc, "grid_import") == pytest.approx(10_000)
        assert _lifetime(calc, "grid_export") == pytest.approx(11_000)
        assert _lifetime(calc, "solar") == pytest.approx(20_100)  # not lowered
        assert _lifetime(calc, "home") == pytest.approx(19_800 + 4_000 - 5_000)
        assert _lifetime(calc, "ev") == pytest.approx(1_234)

    def test_single_counter_install_with_no_record_is_left_alone(self):
        """No list is longer than one, so a seed from before #1043 read the
        same counters — nothing to re-take, the record is only written."""
        one = dict(solar={"sensor.pv": 20_000.0}, imp={"sensor.gi": 9_000.0},
                   exp={"sensor.ge": 7_000.0})
        values = {"sensor.pv": 20_000.0, "sensor.gi": 9_000.0, "sensor.ge": 7_000.0,
                  **CHARGE, **DISCHARGE}
        calc = _calc()
        stored = {
            "lifetime_solar": 20_500.0, "lifetime_grid_import": 8_900.0,
            "lifetime_grid_export": 7_050.0, "lifetime_battery_charge": 3_010.0,
            "lifetime_battery_discharge": 2_705.0, "lifetime_home": 21_000.0,
        }
        calc._lifetime_accumulators.update(stored)
        calc.seed_lifetime_from_hardware(_hass(values), _ed(**one))
        assert calc._lifetime_seeded is True
        assert calc._lifetime_accumulators == stored
        assert calc._lifetime_seed_counters["grid_import"] == ["sensor.gi"]

    def test_a_matching_record_does_not_re_seed(self):
        calc = _calc()
        calc.seed_lifetime_from_hardware(_hass(_values()), _ed())
        state = calc.get_state()

        later = _calc()
        later.restore_state(state)
        # Live accumulation moved the totals on since the seed — one of them
        # below its counter, which only a CHANGED set may raise.
        later._lifetime_accumulators["lifetime_solar"] += 40.0
        later._lifetime_accumulators["lifetime_grid_export"] -= 300.0
        before = dict(later._lifetime_accumulators)
        later.seed_lifetime_from_hardware(_hass(_values()), _ed())
        assert later._lifetime_seeded is True
        assert later._lifetime_accumulators == before

    def test_a_new_counter_in_the_dashboard_is_added(self):
        """A small new inverter: the old checks (half, 90 %) see nothing, the
        record sees a new set and raises the total by its counter."""
        calc = _calc()
        two = {k: SOLAR[k] for k in ("sensor.inv1_kwh", "sensor.inv2_kwh")}
        calc.seed_lifetime_from_hardware(_hass(_values()), _ed(solar=two))
        assert _lifetime(calc, "solar") == pytest.approx(12_388 + 27_870)

        later = _calc()
        later.restore_state(calc.get_state())
        with_new = {**two, "sensor.inv_new": 500.0}
        later.seed_lifetime_from_hardware(
            _hass(_values(**{"sensor.inv_new": 500.0})), _ed(solar=with_new))
        assert _lifetime(later, "solar") == pytest.approx(12_388 + 27_870 + 500)
        assert later._lifetime_seed_counters["solar"] == sorted(with_new)


@pytest.mark.unit
class TestReSeedNeverLowersHistory:
    """Review of #1043: a new or changed counter set must not overwrite the
    history SEM holds with a smaller hardware sum."""

    def _good(self, record=True):
        calc = _calc()
        calc.seed_lifetime_from_hardware(_hass(_values()), _ed())
        later = _calc()
        state = calc.get_state()
        if not record:
            state["lifetime_seed_counters"] = None
        later.restore_state(state)
        later._lifetime_accumulators["lifetime_solar"] = 60_700.0
        return later

    def test_a_replaced_inverter_on_an_old_seed_keeps_its_history(self):
        """No record, two inverters, inverter 2 swapped: its counter starts
        again. The hardware sum is 35,000 against 55,000 SEM holds."""
        solar = {"sensor.inv1_kwh": 30_000.0, "sensor.inv2_kwh": 5_000.0}
        calc = _calc()
        calc._lifetime_accumulators.update({
            "lifetime_solar": 55_000.0, "lifetime_grid_import": 10_000.0,
            "lifetime_grid_export": 35_196.0, "lifetime_battery_charge": 3_000.0,
            "lifetime_battery_discharge": 2_700.0,
        })
        values = {**solar, **IMPORT, **EXPORT, **CHARGE, **DISCHARGE}
        calc.seed_lifetime_from_hardware(_hass(values), _ed(solar=solar))
        assert calc._lifetime_seeded is True
        assert _lifetime(calc, "solar") == pytest.approx(55_000)

    def test_a_removed_dashboard_row_keeps_its_history(self):
        calc = self._good()
        two = {k: SOLAR[k] for k in ("sensor.inv1_kwh", "sensor.inv2_kwh")}
        calc.seed_lifetime_from_hardware(_hass(_values()), _ed(solar=two))
        assert calc._lifetime_seeded is True
        assert _lifetime(calc, "solar") == pytest.approx(60_700)

    def test_a_gone_counter_left_out_keeps_the_history(self, monkeypatch):
        """Its integration was deleted, its row left in the dashboard. After
        the wait it is left out — and the sum without it is only a floor."""
        clock = [1_000.0]
        monkeypatch.setattr(ec_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        calc = self._good()
        values = _values()
        del values["sensor.inv2_kwh"], values["sensor.inv3_kwh"]
        calc.seed_lifetime_from_hardware(_hass(values), _ed())
        clock[0] += UNAVAILABLE_REPAIR_THRESHOLD_S
        calc.seed_lifetime_from_hardware(_hass(values), _ed())
        assert calc._lifetime_seeded is True
        # 12,388 alone is under half of 60,700: the #551 downward heal would
        # have fired on a complete set. On a floor it may not.
        assert _lifetime(calc, "solar") == pytest.approx(60_700)

    def test_a_dark_counter_left_out_keeps_the_history(self, monkeypatch):
        clock = [1_000.0]
        monkeypatch.setattr(ec_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        calc = self._good(record=False)
        dark = _values(**{"sensor.inv2_kwh": "unavailable", "sensor.inv3_kwh": "unavailable"})
        calc.seed_lifetime_from_hardware(_hass(dark), _ed())
        assert calc._lifetime_seeded is False
        clock[0] += UNAVAILABLE_REPAIR_THRESHOLD_S
        calc.seed_lifetime_from_hardware(_hass(dark), _ed())
        assert calc._lifetime_seeded is True
        assert _lifetime(calc, "solar") == pytest.approx(60_700)
        # Next start, the counters are back: the set changed, the total is
        # raised if the counters prove it too low — never lowered.
        later = _calc()
        later.restore_state(calc.get_state())
        later.seed_lifetime_from_hardware(_hass(_values()), _ed())
        assert _lifetime(later, "solar") == pytest.approx(60_700)

    def test_a_fresh_seed_with_a_counter_left_out_is_healed_later(self, monkeypatch):
        clock = [1_000.0]
        monkeypatch.setattr(ec_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        calc = _calc()
        dark = _values(**{"sensor.export_t2": "unavailable"})
        calc.seed_lifetime_from_hardware(_hass(dark), _ed())
        clock[0] += UNAVAILABLE_REPAIR_THRESHOLD_S
        calc.seed_lifetime_from_hardware(_hass(dark), _ed())
        assert _lifetime(calc, "grid_export") == pytest.approx(10_358)

        later = _calc()
        later.restore_state(calc.get_state())
        later.seed_lifetime_from_hardware(_hass(_values()), _ed())
        assert _lifetime(later, "grid_export") == pytest.approx(35_196)

    def test_a_below_half_category_does_not_lower_another(self):
        """Review round 2: export below half of its new sum calls for a
        re-seed. That must not set solar — whose new inverter counts from
        0 — down to the counter, nor the EV total to the first charger."""
        solar = {"sensor.inv_new": 20_000.0}
        exp = {"sensor.export_t1": 2_000.0, "sensor.export_t2": 6_000.0}
        values = {**solar, **IMPORT, **exp, **CHARGE, **DISCHARGE,
                  "sensor.wallbox_total_energy": 3_000.0}
        ed = _ed(solar=solar, exp=exp)
        ed.device_consumption = [{"stat_consumption": "sensor.wallbox_total_energy"}]
        calc = _calc()
        calc._lifetime_accumulators.update({
            "lifetime_solar": 30_000.0, "lifetime_grid_import": 10_000.0,
            "lifetime_grid_export": 3_000.0, "lifetime_battery_charge": 3_000.0,
            "lifetime_battery_discharge": 2_700.0, "lifetime_home": 31_000.0,
            "lifetime_ev": 5_000.0,
        })
        calc.seed_lifetime_from_hardware(_hass(values), ed)
        assert calc._lifetime_seeded is True
        assert _lifetime(calc, "solar") == pytest.approx(30_000)
        assert _lifetime(calc, "grid_export") == pytest.approx(8_000)
        assert _lifetime(calc, "home") == pytest.approx(31_000 - 5_000)
        assert _lifetime(calc, "ev") == pytest.approx(5_000)

    def test_a_night_restart_on_the_upgrade_keeps_solar(self, monkeypatch):
        """Inverters 2 and 3 asleep past the wait, on the upgrade restart of
        the reporter's tariff-1 export: export is raised, solar — a floor
        tonight — keeps the 60,000 SEM holds instead of 12,388."""
        clock = [1_000.0]
        monkeypatch.setattr(ec_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        calc = _calc()
        calc._lifetime_accumulators.update({
            "lifetime_solar": 60_000.0, "lifetime_grid_import": 10_000.0,
            "lifetime_grid_export": 10_357.0, "lifetime_battery_charge": 3_000.0,
            "lifetime_battery_discharge": 2_700.0,
        })
        night = _values(**{"sensor.inv2_kwh": "unavailable", "sensor.inv3_kwh": "unavailable"})
        calc.seed_lifetime_from_hardware(_hass(night), _ed())
        clock[0] += UNAVAILABLE_REPAIR_THRESHOLD_S
        calc.seed_lifetime_from_hardware(_hass(night), _ed())
        assert calc._lifetime_seeded is True
        assert _lifetime(calc, "solar") == pytest.approx(60_000)
        assert _lifetime(calc, "grid_export") == pytest.approx(35_196)

    def test_a_floor_never_starts_the_unit_heal(self, monkeypatch):
        """Solar stored above twice its partial sum is not the #551 ×1000
        case — so export, a little above its counter, and home stay."""
        clock = [1_000.0]
        monkeypatch.setattr(ec_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        calc = self._good()
        calc._lifetime_accumulators["lifetime_grid_export"] = 35_300.0
        calc._lifetime_accumulators["lifetime_home"] = 34_000.0
        night = _values(**{"sensor.inv2_kwh": "unavailable", "sensor.inv3_kwh": "unavailable"})
        calc.seed_lifetime_from_hardware(_hass(night), _ed())
        clock[0] += UNAVAILABLE_REPAIR_THRESHOLD_S
        calc.seed_lifetime_from_hardware(_hass(night), _ed())
        assert calc._lifetime_seeded is True
        assert _lifetime(calc, "solar") == pytest.approx(60_700)
        assert _lifetime(calc, "grid_export") == pytest.approx(35_300)
        assert _lifetime(calc, "home") == pytest.approx(34_000)


@pytest.mark.unit
class TestLifetimeSeedWaitsForEveryCounter:
    def test_a_counter_still_loading_holds_the_seed(self):
        calc = _calc()
        loading = _values(**{"sensor.inv2_kwh": "unavailable", "sensor.inv3_kwh": "unknown"})
        calc.seed_lifetime_from_hardware(_hass(loading), _ed())
        assert calc._lifetime_seeded is False
        assert _lifetime(calc, "solar") == 0.0

        calc.seed_lifetime_from_hardware(_hass(_values()), _ed())
        assert calc._lifetime_seeded is True
        assert _lifetime(calc, "solar") == pytest.approx(60_601)

    def test_a_tariff_still_loading_holds_the_seed(self):
        calc = _calc()
        calc.seed_lifetime_from_hardware(
            _hass(_values(**{"sensor.export_t2": "unavailable"})), _ed())
        assert calc._lifetime_seeded is False
        assert _lifetime(calc, "grid_export") == 0.0

    def test_a_partial_read_cannot_shrink_a_good_lifetime(self):
        """The #551 downward heal fires on stored > 2 × hardware. One inverter
        of three read alone is 12,388 against a correct 60,700 — before #1043
        that SHRANK the lifetime to the one inverter."""
        calc = _calc()
        calc.seed_lifetime_from_hardware(_hass(_values()), _ed())
        later = _calc()
        later.restore_state(calc.get_state())
        later._lifetime_accumulators["lifetime_solar"] = 60_700.0

        loading = _values(**{"sensor.inv2_kwh": "unavailable", "sensor.inv3_kwh": "unavailable"})
        later.seed_lifetime_from_hardware(_hass(loading), _ed())
        assert later._lifetime_seeded is False
        assert _lifetime(later, "solar") == pytest.approx(60_700)

    @pytest.mark.parametrize("reading", ["garbage", "nan", "inf", 0, -5])
    def test_a_counter_with_no_usable_number_holds_the_seed(self, reading):
        calc = _calc()
        calc.seed_lifetime_from_hardware(
            _hass(_values(**{"sensor.inv3_kwh": reading})), _ed())
        assert calc._lifetime_seeded is False

    def test_an_absent_counter_holds_the_seed_while_ha_starts(self, monkeypatch):
        """Before HA runs, an integration still loading has NO state at all
        (bug class 86) — that is not a counter that is gone, however long
        the start takes."""
        clock = [1_000.0]
        monkeypatch.setattr(ec_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        values = _values()
        del values["sensor.inv3_kwh"]
        calc = _calc()
        calc.seed_lifetime_from_hardware(_hass(values, running=False), _ed())
        clock[0] += 10 * UNAVAILABLE_REPAIR_THRESHOLD_S
        calc.seed_lifetime_from_hardware(_hass(values, running=False), _ed())
        assert calc._lifetime_seeded is False
        assert _lifetime(calc, "solar") == 0.0

    def test_the_wait_starts_when_ha_runs(self, monkeypatch):
        clock = [1_000.0]
        monkeypatch.setattr(ec_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        values = _values()
        del values["sensor.inv3_kwh"]
        calc = _calc()
        calc.seed_lifetime_from_hardware(_hass(values, running=False), _ed())
        clock[0] += 10 * UNAVAILABLE_REPAIR_THRESHOLD_S
        calc.seed_lifetime_from_hardware(_hass(values), _ed())
        assert calc._lifetime_seeded is False
        clock[0] += UNAVAILABLE_REPAIR_THRESHOLD_S
        calc.seed_lifetime_from_hardware(_hass(values), _ed())
        assert calc._lifetime_seeded is True

    def test_each_counter_has_its_own_wait(self, monkeypatch):
        """A counter that goes dark late does not inherit the wait another
        counter already served."""
        clock = [1_000.0]
        monkeypatch.setattr(ec_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        calc = _calc()
        calc.seed_lifetime_from_hardware(
            _hass(_values(**{"sensor.inv2_kwh": "unavailable"})), _ed())
        clock[0] += UNAVAILABLE_REPAIR_THRESHOLD_S - 1
        late = _values(**{"sensor.inv3_kwh": "unavailable"})
        calc.seed_lifetime_from_hardware(_hass(late), _ed())
        clock[0] += 1
        calc.seed_lifetime_from_hardware(_hass(late), _ed())
        assert calc._lifetime_seeded is False

    def test_a_counter_that_reads_again_starts_a_new_wait(self, monkeypatch):
        """Ready once, dark again: the old wait does not carry over."""
        clock = [1_000.0]
        monkeypatch.setattr(ec_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        calc = _calc()
        calc.seed_lifetime_from_hardware(
            _hass(_values(**{"sensor.inv2_kwh": "unavailable"})), _ed())
        clock[0] += 100
        calc.seed_lifetime_from_hardware(
            _hass(_values(**{"sensor.inv3_kwh": "unavailable"})), _ed())
        clock[0] += 250
        both = _values(**{"sensor.inv2_kwh": "unavailable", "sensor.inv3_kwh": "unavailable"})
        calc.seed_lifetime_from_hardware(_hass(both), _ed())
        clock[0] += 50
        calc.seed_lifetime_from_hardware(_hass(both), _ed())
        # inv3 has waited its 300 s; inv2 only 50 s since it went dark again.
        assert calc._lifetime_seeded is False

    def test_an_absent_counter_is_left_out_after_the_wait(self, monkeypatch):
        """A stale Energy Dashboard row must not hold the seed for ever: once
        HA runs and the wait is over, the counter is left out."""
        clock = [1_000.0]
        monkeypatch.setattr(ec_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        values = _values()
        del values["sensor.inv3_kwh"]
        calc = _calc()

        calc.seed_lifetime_from_hardware(_hass(values), _ed())
        assert calc._lifetime_seeded is False
        clock[0] += UNAVAILABLE_REPAIR_THRESHOLD_S - 1
        calc.seed_lifetime_from_hardware(_hass(values), _ed())
        assert calc._lifetime_seeded is False

        clock[0] += 1
        calc.seed_lifetime_from_hardware(_hass(values), _ed())
        assert calc._lifetime_seeded is True
        assert _lifetime(calc, "solar") == pytest.approx(12_388 + 27_870)
        assert calc._lifetime_seed_counters["solar"] == ["sensor.inv1_kwh", "sensor.inv2_kwh"]

    def test_an_external_statistic_is_left_out_at_once(self):
        """``tibber:…`` ids in the dashboard are statistics, not entities:
        they never have a state, so there is nothing to wait for."""
        imp = {**IMPORT, "tibber:energy_consumption_home": 0.0}
        values = _values()
        calc = _calc()
        calc.seed_lifetime_from_hardware(_hass(values), _ed(imp=imp))
        assert calc._lifetime_seeded is True
        assert _lifetime(calc, "grid_import") == pytest.approx(10_000)


@pytest.mark.unit
class TestBatteryLessInstall:
    def test_an_install_without_a_battery_seeds(self):
        """The battery wait read 0 + 0 on an install with no battery in the
        Energy Dashboard and returned on every cycle — it never seeded."""
        values = {**SOLAR, **IMPORT, **EXPORT}
        calc = _calc()
        calc.seed_lifetime_from_hardware(_hass(values), _ed(charge={}, discharge={}))
        assert calc._lifetime_seeded is True
        assert _lifetime(calc, "solar") == pytest.approx(60_601)
        assert _lifetime(calc, "battery_charge") == 0.0

    def test_a_listed_battery_reading_zero_waits_then_is_left_out(self, monkeypatch):
        clock = [1_000.0]
        monkeypatch.setattr(ec_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        calc = _calc()
        values = _values(**{"sensor.batt_charge": 0, "sensor.batt_discharge": 0})
        calc.seed_lifetime_from_hardware(_hass(values), _ed())
        assert calc._lifetime_seeded is False
        clock[0] += UNAVAILABLE_REPAIR_THRESHOLD_S
        calc.seed_lifetime_from_hardware(_hass(values), _ed())
        assert calc._lifetime_seeded is True
        assert _lifetime(calc, "solar") == pytest.approx(60_601)
        assert _lifetime(calc, "battery_charge") == 0.0


@pytest.mark.unit
class TestSeedRecordStorage:
    def test_the_record_round_trips(self):
        calc = _calc()
        calc.seed_lifetime_from_hardware(_hass(_values()), _ed())
        state = calc.get_state()
        assert state["lifetime_seed_counters"]["grid_export"] == [
            "sensor.export_t1", "sensor.export_t2"]

        later = _calc()
        later.restore_state(state)
        assert later._lifetime_seed_counters == calc._lifetime_seed_counters

    @pytest.mark.parametrize("damaged", [
        "solar", ["sensor.a"], {"solar": "sensor.a"}, {"solar": [1, 2]}, {1: ["sensor.a"]},
    ])
    def test_a_damaged_record_reads_as_no_record(self, damaged):
        calc = _calc()
        calc.restore_state({"lifetime_seed_counters": damaged})
        assert calc._lifetime_seed_counters is None

    def test_the_store_carries_the_record(self):
        from custom_components.solar_energy_management.coordinator import storage
        assert "lifetime_seed_counters" in storage.CALCULATOR_STATE_KEYS


# ── the yearly seed and the monthly energy query ─────────────────────────


def _rows(first, last):
    return [
        {"start": "2026-01-01T00:00:00", "sum": first},
        {"start": "2026-09-30T12:00:00", "sum": last},
    ]


@pytest.mark.unit
class TestYearlySeedSumsEveryCounter:
    @pytest.mark.asyncio
    async def test_every_tariff_and_inverter_adds_to_the_year(self):
        stats = {
            "sensor.inv1_kwh": _rows(100, 1_100), "sensor.inv2_kwh": _rows(200, 2_200),
            "sensor.inv3_kwh": _rows(300, 1_800),
            "sensor.import_t1": _rows(0, 400), "sensor.import_t2": _rows(0, 600),
            "sensor.export_t1": _rows(0, 700), "sensor.export_t2": _rows(0, 1_300),
            "sensor.batt_charge": _rows(0, 500), "sensor.batt_discharge": _rows(0, 450),
        }
        statistics = MagicMock()
        statistics.statistics_during_period = MagicMock(return_value=stats)
        calc = _calc()
        with patch.dict("sys.modules", {
            "homeassistant.components.recorder": MagicMock(),
            "homeassistant.components.recorder.statistics": statistics,
        }):
            await calc.seed_yearly_from_statistics(MagicMock(), _ed())

        asked = [
            set(c.args[3]) for c in statistics.statistics_during_period.call_args_list
            if len(c.args) > 3 and isinstance(c.args[3], (list, set, tuple))
        ]
        assert set(stats) in asked
        year = str(datetime.now().year)
        acc = calc._yearly_accumulators
        assert acc[f"solar_{year}"] == pytest.approx(1_000 + 2_000 + 1_500)
        assert acc[f"grid_import_{year}"] == pytest.approx(1_000)
        assert acc[f"grid_export_{year}"] == pytest.approx(2_000)
        assert acc[f"home_{year}"] == pytest.approx(4_500 + 1_000 + 450 - 2_000 - 500)

    @pytest.mark.asyncio
    async def test_a_category_with_no_statistics_keeps_its_live_value(self):
        """Unchanged from before: no rows for any counter of a category is no
        seed for it, not a 0 written over what live tracking holds."""
        stats = {eid: _rows(0, 100) for eid in (*SOLAR, *IMPORT, *CHARGE, *DISCHARGE)}
        statistics = MagicMock()
        statistics.statistics_during_period = MagicMock(return_value=stats)
        calc = _calc()
        year = str(datetime.now().year)
        calc._yearly_accumulators[f"grid_export_{year}"] = 3.0
        with patch.dict("sys.modules", {
            "homeassistant.components.recorder": MagicMock(),
            "homeassistant.components.recorder.statistics": statistics,
        }):
            await calc.seed_yearly_from_statistics(MagicMock(), _ed())
        assert calc._yearly_accumulators[f"grid_export_{year}"] == 3.0


@pytest.mark.unit
class TestMonthlyEnergySumsEveryCounter:
    @pytest.mark.asyncio
    async def test_each_months_tariffs_add_up(self):
        def rows(dec, jan, feb):
            return [
                {"start": datetime(2025, 12, 1), "sum": dec},
                {"start": datetime(2026, 1, 1), "sum": jan},
                {"start": datetime(2026, 2, 1), "sum": feb},
            ]

        stats = {
            "sensor.export_t1": rows(1_000, 1_100, 1_250),
            "sensor.export_t2": rows(5_000, 5_300, 5_700),
        }
        calc = _calc()
        calc._recorder_stats = AsyncMock(return_value=stats)
        result = await calc._query_monthly_energy(MagicMock(), _ed(), "2026")

        asked = calc._recorder_stats.await_args.args[2]
        assert {"sensor.export_t1", "sensor.export_t2", "sensor.inv3_kwh"} <= asked
        assert result["grid_export"] == {1: pytest.approx(100 + 300), 2: pytest.approx(150 + 400)}


# ── the guard ────────────────────────────────────────────────────────────

_SCALARS = {
    "solar_energy", "grid_import_energy", "grid_export_energy",
    "battery_charge_energy", "battery_discharge_energy",
}


def _scalar_reads(source: str) -> list:
    """Attribute reads AND string names — ``getattr(ed, "solar_energy")``
    was how ``_query_monthly_energy`` read the first counter."""
    hits = []
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, ast.Attribute) and n.attr in _SCALARS:
            hits.append((n.lineno, n.attr))
        elif isinstance(n, ast.Constant) and n.value in _SCALARS:
            hits.append((n.lineno, n.value))
    return sorted(hits)


@pytest.mark.unit
class TestNoFirstCounterReads:
    def test_energy_calculator_reads_no_first_counter_field(self):
        """Every energy total in the calculator comes from
        ``energy_counters`` — a scalar ``*_energy`` read there is one part
        of a sum taken for the whole of it, which is this bug."""
        source = Path(inspect.getfile(ec_module)).read_text(encoding="utf-8")
        assert _scalar_reads(source) == []

    def test_the_guard_sees_the_shapes_it_bans(self):
        bad = "def f(ed_config):\n    return ed_config.grid_import_energy\n"
        assert _scalar_reads(bad) == [(2, "grid_import_energy")]
        bad = "def f(ed):\n    return getattr(ed, 'solar_energy', None)\n"
        assert _scalar_reads(bad) == [(2, "solar_energy")]
