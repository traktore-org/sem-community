"""#1241 — two grid meters, one power pair each, summed.

A house meter and a heat pump meter: both meters' kWh counters are in the
Energy Dashboard grid entry and no power sensor is. SEM looked for ONE
import/export pair, on the device of the FIRST counter, and read it as the
whole grid, so the second meter's power was never added (bug class 65: one
anchor, the first match, the fleet read as one).

Now: one pair per meter (the unit its counters sit on), each trusted like
the single pair always was, import and export summed across them.
All other meters covered or none: a sum over some of them would be taken for
the whole grid, so the first pair alone is read, as before, and the gap is
said once. A home with one meter (tariff counters included) is unchanged.
"""
from __future__ import annotations

import logging

import pytest

from .test_1240_same_entry_is_same_device import Rig, _state, kwh

_IMP_A = "sensor.house_reading_electricity_currently_delivered"
_EXP_A = "sensor.house_reading_electricity_currently_returned"
_IN_A = "sensor.house_reading_electricity_delivered_1"
_OUT_A = "sensor.house_reading_electricity_returned_1"
_IMP_B = "sensor.hp_reading_electricity_currently_delivered"
_EXP_B = "sensor.hp_reading_electricity_currently_returned"
_IN_B = "sensor.hp_reading_electricity_delivered_1"
_OUT_B = "sensor.hp_reading_electricity_returned_1"


def _meter(prefix, dev, *, imp_kw, exp_kw, pair_dev=None):
    """One meter as the roster declares it: a pair and two counters."""
    pair_dev = pair_dev or dev
    return [
        (f"sensor.{prefix}_reading_electricity_currently_delivered", "dsmr_reader",
         "current_power_usage", pair_dev, "01JE", _state(imp_kw, "kW")),
        (f"sensor.{prefix}_reading_electricity_currently_returned", "dsmr_reader",
         "current_power_return", pair_dev, "01JE", _state(exp_kw, "kW")),
        (f"sensor.{prefix}_reading_electricity_delivered_1", "dsmr_reader",
         "low_tariff_usage", dev, "01JE", kwh(100.0)),
        (f"sensor.{prefix}_reading_electricity_returned_1", "dsmr_reader",
         "low_tariff_returned", dev, "01JE", kwh(10.0)),
    ]


def _two(a=(1.0, 0.0), b=(0.5, 0.0), **b_kw):
    rows = (_meter("house", "devA", imp_kw=a[0], exp_kw=a[1])
            + _meter("hp", "devB", imp_kw=b[0], exp_kw=b[1], **b_kw))
    return Rig(rows, [_IN_A, _IN_B], [_OUT_A, _OUT_B])


class TestTwoMetersAreSummed:
    def test_both_imports_are_added(self):
        assert _two().read().grid_power == pytest.approx(-1500.0)

    def test_the_second_meters_export_is_added(self):
        rig = _two(a=(1.0, 0.0), b=(0.0, 2.0))
        assert rig.read().grid_power == pytest.approx(1000.0)

    def test_one_meter_exports_while_the_other_imports(self):
        rig = _two(a=(0.2, 0.0), b=(0.0, 3.0))
        assert rig.read().grid_power == pytest.approx(2800.0)

    def test_the_first_meter_is_still_the_main_pick(self):
        rig = _two()
        rig.read()
        assert rig.picks == (_IMP_A, _EXP_A, "declared")

    def test_a_restart_reads_the_sum_at_once(self):
        rig = _two()
        rig.read()
        rig.reader.invalidate_split_grid_cache()
        assert rig.read().grid_power == pytest.approx(-1500.0)

    def test_the_source_names_every_pair(self):
        rig = _two()
        rig.read()
        key = rig.reader._grid_source_key
        assert key.startswith("discovered:") and _IMP_B in key and _EXP_B in key
        assert rig.reader.grid_read_is_pair()

    def test_each_pair_is_checked_for_both_sides_at_once(self):
        rig = _two(a=(1.0, 0.0), b=(0.5, 0.0))
        rig.read()
        assert {"grid", "grid#2"} <= set(rig.reader._split_pair_audits)

    def test_the_name_tier_finds_a_second_meter_on_its_own_device(self):
        rows = [
            ("sensor.main_grid_import", "custom", "k1", "devA", "01JE", _state(1.0, "kW")),
            ("sensor.main_grid_export", "custom", "k2", "devA", "01JE", _state(0.0, "kW")),
            ("sensor.main_imported", "custom", "k3", "devA", "01JE", kwh(5.0)),
            ("sensor.hp_grid_import", "custom", "k4", "devB", "01JE", _state(0.5, "kW")),
            ("sensor.hp_grid_export", "custom", "k5", "devB", "01JE", _state(0.0, "kW")),
            ("sensor.hp_imported", "custom", "k6", "devB", "01JE", kwh(5.0)),
        ]
        rig = Rig(rows, ["sensor.main_imported", "sensor.hp_imported"], [])
        assert rig.read().grid_power == pytest.approx(-1500.0)
        assert rig.picks[2] == "same-device"


class TestNeverAPartialSumAsTheWhole:
    def test_a_second_meter_with_no_pair_reads_the_first_alone_and_says_so(self, caplog):
        rows = _meter("house", "devA", imp_kw=1.0, exp_kw=0.0) + [
            (_IN_B, "dsmr_reader", "low_tariff_usage", "devB", "01JE", kwh(5.0)),
            (_OUT_B, "dsmr_reader", "low_tariff_returned", "devB", "01JE", kwh(5.0)),
        ]
        rig = Rig(rows, [_IN_A, _IN_B], [_OUT_A, _OUT_B])
        with caplog.at_level(logging.WARNING):
            for _ in range(3):
                power = rig.read()
        assert power.grid_power == pytest.approx(-1000.0)      # as before
        said = [r for r in caplog.records if "grid meters" in r.getMessage()]
        assert len(said) == 1                                   # once
        assert _IN_B in said[0].getMessage()

    def test_a_pair_on_another_device_is_not_the_second_meters(self, caplog):
        rig = _two(pair_dev="devC")
        with caplog.at_level(logging.WARNING):
            power = rig.read()
        assert power.grid_power == pytest.approx(-1000.0)
        assert any("grid meters" in r.getMessage() for r in caplog.records)

    def test_one_meter_missing_among_three_adds_none(self):
        rows = (_meter("house", "devA", imp_kw=1.0, exp_kw=0.0)
                + _meter("hp", "devB", imp_kw=0.5, exp_kw=0.0)
                + [("sensor.c_in", "dsmr_reader", "low_tariff_usage", "devC",
                    "01JE", kwh(1.0))])
        rig = Rig(rows, [_IN_A, _IN_B, "sensor.c_in"], [])
        assert rig.read().grid_power == pytest.approx(-1000.0)

    def test_a_late_second_meter_is_added_once_it_appears(self):
        rows = _meter("house", "devA", imp_kw=1.0, exp_kw=0.0) + [
            (_IN_B, "dsmr_reader", "low_tariff_usage", "devB", "01JE", kwh(5.0)),
            (_OUT_B, "dsmr_reader", "low_tariff_returned", "devB", "01JE", kwh(5.0)),
        ]
        rig = Rig(rows, [_IN_A, _IN_B], [_OUT_A, _OUT_B])
        assert rig.read().grid_power == pytest.approx(-1000.0)
        from .test_1240_same_entry_is_same_device import _row
        for r in _meter("hp", "devB", imp_kw=0.5, exp_kw=0.0)[:2]:
            rig.states[r[0]] = r[5]
            rig.registry.entities[r[0]] = _row(
                r[0], r[1], r[2], device=r[3], entry=r[4])
        power = None
        for _ in range(8):
            power = rig.read()
        assert power.grid_power == pytest.approx(-1500.0)


class TestOneMeterIsUnchanged:
    def test_tariff_counters_of_one_meter_are_one_meter(self, caplog):
        rows = _meter("house", "devA", imp_kw=1.0, exp_kw=0.0) + [
            ("sensor.house_delivered_2", "dsmr_reader", "normal_tariff_usage",
             "devA", "01JE", kwh(9.0)),
        ]
        rig = Rig(rows, [_IN_A, "sensor.house_delivered_2"], [_OUT_A])
        with caplog.at_level(logging.WARNING):
            power = rig.read()
        assert power.grid_power == pytest.approx(-1000.0)
        assert rig.reader._grid_source_key == f"discovered:{_IMP_A}|{_EXP_A}"
        assert not [r for r in caplog.records if "grid meters" in r.getMessage()]
        assert rig.reader._split_grid_discovery.get("more") in (None, [])

    def test_a_single_counter_is_unchanged(self):
        rig = Rig(_meter("house", "devA", imp_kw=1.0, exp_kw=0.4), [_IN_A], [_OUT_A])
        assert rig.read().grid_power == pytest.approx(-600.0)
        assert rig.reader._grid_source_key == f"discovered:{_IMP_A}|{_EXP_A}"

    def test_counters_with_no_unit_are_one_meter(self, caplog):
        rows = [
            (_IMP_A, "dsmr_reader", "current_power_usage", None, None, _state(1.0, "kW")),
            (_EXP_A, "dsmr_reader", "current_power_return", None, None, _state(0.0, "kW")),
            (_IN_A, "dsmr_reader", "low_tariff_usage", None, None, kwh(1.0)),
            (_IN_B, "dsmr_reader", "normal_tariff_usage", None, None, kwh(1.0)),
        ]
        rig = Rig(rows, [_IN_A, _IN_B], [])
        with caplog.at_level(logging.WARNING):
            rig.read()
        # no unit, no trust: still the name-tier check, as before
        assert rig.picks == (_IMP_A, _EXP_A, "declared-elsewhere")
        assert not [r for r in caplog.records if "grid meters" in r.getMessage()]
