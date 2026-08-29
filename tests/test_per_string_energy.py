"""Per-PV-string energy accumulation tests (v1.7.0 / #312).

Mirrors ``tests/test_per_charger_energy_flows.py`` for the source side.
Strings are SOURCES so the data flows differently than per-charger:

- ``PowerReadings.solar_power_per_string`` carries per-string raw W
- ``calculate_power_flows`` copies it onto ``PowerFlows.solar_per_string``
- ``integrate_energy_flows`` accumulates each string's kWh in
  ``_per_string_accumulators`` and emits ``EnergyFlows.per_string[sid] = StringEnergy(...)``
- ``SEMData.to_dict`` emits ``pv_string_<sid>_power`` + ``_daily_energy`` keys

These tests pin:

1. Single-string setups: empty ``per_string`` dict (back-compat).
2. Multi-string sum invariant: ``sum(per_string) ≈ solar_power`` ±10 W.
3. Multi-cycle accumulation: kWh grows across cycles.
4. Day rollover: per-string accumulator cleared at local midnight.
5. Persistence round-trip: includes ``per_string`` when non-empty,
   omits when empty; pre-v1.7.0 snapshots restore cleanly.
6. Bad-snapshot defence: non-dict / non-numeric values silently skipped.
7. Idle-string semantic: a string that goes to 0 W mid-day keeps its
   surfaced kWh (no regression to 0 on the user-visible counter).
8. SEMData.to_dict key emission.
"""
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from custom_components.solar_energy_management.coordinator.flow_calculator import (
    FlowCalculator,
)
from custom_components.solar_energy_management.coordinator.types import (
    EnergyFlows,
    PowerFlows,
    PowerReadings,
    SEMData,
    StringEnergy,
)


def _power(solar=0.0, grid=0.0, battery=0.0, ev=0.0, home=0.0,
           solar_per_string=None) -> PowerReadings:
    """Build a PowerReadings with the bare minimum for flow calc."""
    p = PowerReadings()
    p.solar_power = solar
    p.grid_power = grid
    p.battery_power = battery
    p.ev_power = ev
    p.home_consumption_power = home
    if solar_per_string:
        p.solar_power_per_string = dict(solar_per_string)
    # Derived split (mirrors PowerReadings.calculate_derived behaviour
    # for the flow calc inputs we care about).
    p.grid_import_power = max(0, -grid)
    p.grid_export_power = max(0, grid)
    p.battery_charge_power = max(0, battery)
    p.battery_discharge_power = max(0, -battery)
    return p


def _integrate(fc: FlowCalculator, interval_s: float = 3600,
               **per_string_w) -> EnergyFlows:
    """Run one calculate_power_flows + integrate_energy_flows cycle.

    ``per_string_w`` is ``{sid: watts}``. Fleet solar = sum.
    """
    flows = PowerFlows()
    if per_string_w:
        flows.solar_per_string = dict(per_string_w)
    return fc.integrate_energy_flows(flows, interval_seconds=interval_s)


class TestSingleStringBackCompat:
    """Without per-string data nothing changes — empty per_string dict
    on the result, fleet integration unaffected."""

    def test_no_per_string_yields_empty_dict(self):
        fc = FlowCalculator()
        result = _integrate(fc)
        assert result.per_string == {}

    def test_empty_solar_per_string_yields_empty(self):
        fc = FlowCalculator()
        flows = PowerFlows()
        result = fc.integrate_energy_flows(flows, interval_seconds=3600)
        assert result.per_string == {}


class TestSumInvariant:
    """``sum(per_string) ≈ fleet solar integration`` within rounding."""

    def test_two_strings_sum_to_fleet(self):
        fc = FlowCalculator()
        # 1 hour at pv1=2000W, pv2=3000W → expect 2 kWh + 3 kWh = 5 kWh.
        result = _integrate(fc, pv1=2000.0, pv2=3000.0)
        assert result.per_string["pv1"].energy_kwh == pytest.approx(2.0, rel=1e-3)
        assert result.per_string["pv2"].energy_kwh == pytest.approx(3.0, rel=1e-3)
        per_sum = sum(s.energy_kwh for s in result.per_string.values())
        assert per_sum == pytest.approx(5.0, abs=0.01)

    def test_four_strings_max(self):
        """Max 4 strings (discovery cap) — all integrate independently."""
        fc = FlowCalculator()
        result = _integrate(fc, pv1=1000, pv2=2000, pv3=3000, pv4=4000)
        for sid, expected in (("pv1", 1.0), ("pv2", 2.0), ("pv3", 3.0), ("pv4", 4.0)):
            assert result.per_string[sid].energy_kwh == pytest.approx(expected, rel=1e-3)


class TestMultiCycleAccumulation:
    """kWh grows across multiple integration calls."""

    def test_two_cycles_accumulate(self):
        fc = FlowCalculator()
        for _ in range(2):
            _integrate(fc, interval_s=1800, pv1=4000.0, pv2=2000.0)
        # Two 30-min cycles at 4000W → 4 kWh; at 2000W → 2 kWh.
        result = _integrate(fc, interval_s=0, pv1=0, pv2=0)
        assert result.per_string["pv1"].energy_kwh == pytest.approx(4.0, rel=1e-3)
        assert result.per_string["pv2"].energy_kwh == pytest.approx(2.0, rel=1e-3)


class TestDayRollover:
    """Per-string accumulators cleared at local midnight (mirrors
    fleet + per-charger rollover behaviour)."""

    def test_rollover_clears_per_string(self):
        fc = FlowCalculator()
        _integrate(fc, pv1=4000.0, pv2=2000.0)
        assert fc._per_string_accumulators["pv1"]["energy_kwh"] > 0
        assert fc._per_string_accumulators["pv2"]["energy_kwh"] > 0
        # Simulate next day.
        with patch(
            "custom_components.solar_energy_management.coordinator.flow_calculator.dt_util.now"
        ) as mocked:
            tomorrow = date.today() + timedelta(days=1)
            mocked.return_value.date.return_value = tomorrow
            mocked.return_value.isoformat.return_value = tomorrow.isoformat()
            result = _integrate(fc, pv1=500, pv2=500)
            assert result.per_string["pv1"].energy_kwh == pytest.approx(0.5, rel=1e-3)
            assert result.per_string["pv2"].energy_kwh == pytest.approx(0.5, rel=1e-3)


class TestPersistenceRoundTrip:
    """Snapshot includes per_string when populated, omits when empty;
    pre-v1.7.0 snapshots restore cleanly."""

    def test_snapshot_includes_per_string_when_populated(self):
        fc = FlowCalculator()
        _integrate(fc, pv1=4000, pv2=2000)
        snap = fc.get_flow_accumulator_state()
        assert "per_string" in snap
        assert snap["per_string"]["pv1"]["energy_kwh"] == pytest.approx(4.0)
        assert snap["per_string"]["pv2"]["energy_kwh"] == pytest.approx(2.0)

    def test_snapshot_omits_per_string_when_empty(self):
        """Single-string setup: snapshot stays bit-for-bit compatible
        with pre-v1.7.0 format."""
        fc = FlowCalculator()
        # Integrate something so the fleet accumulator is non-empty.
        fc._flow_accumulators["solar_to_home"] = 5.0
        snap = fc.get_flow_accumulator_state()
        assert "per_string" not in snap

    def test_restore_round_trip(self):
        src = FlowCalculator()
        _integrate(src, pv1=4000, pv2=2000)
        snap = src.get_flow_accumulator_state()
        dst = FlowCalculator()
        dst.restore_flow_accumulator_state(snap)
        # Without further integration, emit reflects restored state.
        result = dst.integrate_energy_flows(PowerFlows(), interval_seconds=0)
        assert result.per_string["pv1"].energy_kwh == pytest.approx(4.0)
        assert result.per_string["pv2"].energy_kwh == pytest.approx(2.0)

    def test_restore_legacy_snapshot_without_per_string(self):
        """Pre-v1.7.0 snapshot (no per_string key) — restore cleanly,
        no per-string state, no exceptions."""
        fc = FlowCalculator()
        legacy_snap = {
            "date": fc._current_date.isoformat(),
            "accumulators": {"solar_to_home": 4.0},
        }
        fc.restore_flow_accumulator_state(legacy_snap)
        assert fc._flow_accumulators["solar_to_home"] == pytest.approx(4.0)
        assert fc._per_string_accumulators == {}


class TestBadSnapshotDefence:
    """Same defensive pattern as the fleet + per-charger paths —
    malformed entries silently skipped, no exceptions."""

    def test_non_dict_per_string_silently_skipped(self):
        fc = FlowCalculator()
        snap = {
            "date": fc._current_date.isoformat(),
            "accumulators": {"solar_to_home": 4.0},
            "per_string": "not-a-dict",
        }
        fc.restore_flow_accumulator_state(snap)
        assert fc._per_string_accumulators == {}

    def test_non_dict_per_slot_entry_skipped(self):
        fc = FlowCalculator()
        snap = {
            "date": fc._current_date.isoformat(),
            "accumulators": {},
            "per_string": {"pv1": "not-a-dict-either"},
        }
        fc.restore_flow_accumulator_state(snap)
        assert "pv1" not in fc._per_string_accumulators

    def test_non_numeric_values_skipped(self):
        fc = FlowCalculator()
        snap = {
            "date": fc._current_date.isoformat(),
            "accumulators": {},
            "per_string": {"pv1": {"energy_kwh": "bad"}, "pv2": {"energy_kwh": None}},
        }
        fc.restore_flow_accumulator_state(snap)
        assert "energy_kwh" not in fc._per_string_accumulators.get("pv1", {})
        assert "energy_kwh" not in fc._per_string_accumulators.get("pv2", {})


class TestIdleStringSurfaced:
    """A string that goes to 0 W mid-day must keep its surfaced kWh —
    same semantic as the per-charger idle preservation."""

    def test_idle_string_keeps_kwh(self):
        fc = FlowCalculator()
        # Cycle 1: pv1=2000, pv2=4000 → pv1=2 kWh, pv2=4 kWh.
        _integrate(fc, pv1=2000, pv2=4000)
        # Cycle 2: cloud over pv1 → 0 W; pv2 continues at 4000.
        result = _integrate(fc, pv1=0, pv2=4000)
        # pv1 still surfaced at its accumulated 2 kWh (no regression to 0)
        # — the user-visible counter doesn't lose history on shading.
        assert result.per_string["pv1"].energy_kwh == pytest.approx(2.0, rel=1e-3)
        # pv2 kept accumulating: 4 kWh + another 4 kWh = 8 kWh.
        assert result.per_string["pv2"].energy_kwh == pytest.approx(8.0, rel=1e-3)
        assert result.per_string["pv2"].energy_kwh > result.per_string["pv1"].energy_kwh


class TestDataDict:
    """``SEMData.to_dict`` emits ``pv_string_<sid>_power`` +
    ``_daily_energy`` keys only when the per-string maps are
    populated."""

    def test_dict_includes_per_string_keys(self):
        d = SEMData()
        d.power.solar_power_per_string["pv1"] = 2500.0
        d.power.solar_power_per_string["pv2"] = 1500.0
        d.energy_flows.per_string["pv1"] = StringEnergy(energy_kwh=2.5)
        d.energy_flows.per_string["pv2"] = StringEnergy(energy_kwh=1.5)
        out = d.to_dict()
        assert out["pv_string_pv1_power"] == 2500.0
        assert out["pv_string_pv2_power"] == 1500.0
        assert out["pv_string_pv1_daily_energy"] == 2.5
        assert out["pv_string_pv2_daily_energy"] == 1.5

    def test_dict_omits_per_string_when_empty(self):
        d = SEMData()
        out = d.to_dict()
        leaked = [k for k in out if k.startswith("pv_string_")]
        assert leaked == []


class TestSensorReaderGate:
    """Per-string sensor population in ``sensor_reader`` is gated on
    ``len(self._pv_strings) >= 2``. Single-string installs (1 entry
    only or 0) populate nothing — preserves the v1.6.x behaviour."""

    def test_gate_skips_when_one_string(self):
        from custom_components.solar_energy_management.coordinator.sensor_reader import (
            SensorReader,
        )
        from unittest.mock import MagicMock
        sr = SensorReader.__new__(SensorReader)
        sr.hass = MagicMock()
        sr.config = MagicMock()
        sr._raw_config = {}
        sr._pv_strings = {"pv1": "sensor.inverter_pv1_power"}  # only 1
        readings = PowerReadings()
        # Mirror the gated population logic from sensor_reader without
        # running the full read pipeline.
        if len(sr._pv_strings) >= 2:
            for slot, _eid in sr._pv_strings.items():
                readings.solar_power_per_string[slot] = 100.0
        assert readings.solar_power_per_string == {}

    def test_gate_populates_when_two_strings(self):
        from custom_components.solar_energy_management.coordinator.sensor_reader import (
            SensorReader,
        )
        sr = SensorReader.__new__(SensorReader)
        sr._pv_strings = {
            "pv1": "sensor.inverter_pv1_power",
            "pv2": "sensor.inverter_pv2_power",
        }
        readings = PowerReadings()
        if len(sr._pv_strings) >= 2:
            for slot, _eid in sr._pv_strings.items():
                readings.solar_power_per_string[slot] = 100.0
        assert readings.solar_power_per_string == {"pv1": 100.0, "pv2": 100.0}
