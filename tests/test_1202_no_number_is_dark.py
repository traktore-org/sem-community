"""#1202 — a sensor state that is no number read as 0 W, not dark.

``_read_sensor`` counted a read as dark only for "unknown" and "unavailable".
Any other state that is no number ("none", "error", "") fell into the parse
``except`` and returned 0.0 with no dark mark: ``sensor.sem_battery_power``
showed 0 W, ``sensor.sem_battery_status`` said Idle, and ``inputs_degraded``
stayed off, so SEM steered on the 0 W. "nan" was worse: ``float("nan")``
does not fail, so NaN went into the sums as a reading (comment on #1202,
found while fixing #1196).

The rule now: a read is a reading only when it gives a finite number
(``units.state_number``). Every other state is dark, exactly as
"unavailable" is. Links, each driven for real:

* ``units``: every helper returns its default for text, "nan" and "inf";
* the reader: the same tallies, return values and Repair clock as
  "unavailable", for every power input name;
* ``read_power`` → ``to_dict``: a whole home read with each shape equals the
  same home read with "unavailable" — fleet, per-battery, split grid, PV
  strings, SOC (the guard for the class: a new read path that decides dark
  by a word list fails here);
* the siblings (review): the fleet SOC average, the energy counters that
  correct the daily rows, the forecast power reads, the live EV power sum,
  the held-power history, and ``sensors_ready``.
"""
from __future__ import annotations

import dataclasses
import math
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.forecast_reader import (
    ForecastReader,
)
from custom_components.solar_energy_management.coordinator.types import SEMData
from custom_components.solar_energy_management.coordinator.units import (
    energy_state_to_kwh,
    power_state_to_watts,
    state_number,
    temperature_state_to_celsius,
)
from custom_components.solar_energy_management.devices.held_power import (
    held_power_from_states,
)
from custom_components.solar_energy_management.ha_energy_reader import (
    EnergyDashboardConfig,
)
from custom_components.solar_energy_management.tests.test_1164_force_charge_stall import (  # noqa: E501
    _reader,
    _state,
)
from custom_components.solar_energy_management.tests.test_ev_power_sub_cycle import (  # noqa: E501
    _build_sensor_with_upstreams,
    _make_state,
)

#: states that give no number — each must read exactly as "unavailable"
NO_NUMBER = ["none", "None", "nan", "NaN", "inf", "-inf", "Infinity",
             "error", "", "  ", "Unknown"]
POWER_INPUTS = ["solar", "grid", "grid_import", "grid_export", "battery"]


# ── 1. units ───────────────────────────────────────────────────────────────

class TestUnitsGiveNoNumber:
    @pytest.mark.parametrize("raw", NO_NUMBER + ["unknown", "unavailable", None])
    def test_no_number_is_none(self, raw):
        assert state_number(raw) is None

    @pytest.mark.parametrize("raw,value", [
        ("0", 0.0), ("-3.2", -3.2), (" 12 ", 12.0), ("1e3", 1000.0), (5, 5.0)])
    def test_a_number_is_kept(self, raw, value):
        assert state_number(raw) == value

    @pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "none"])
    def test_every_helper_returns_its_default(self, raw):
        st = SimpleNamespace(state=raw, attributes={"unit_of_measurement": "kW"})
        assert power_state_to_watts(st) is None
        assert power_state_to_watts(st, default=0.0) == 0.0
        assert energy_state_to_kwh(st) is None
        assert temperature_state_to_celsius(st) is None


# ── 2. The reader: one door, the same marks as "unavailable" ───────────────

def _tallies(reader):
    return (dict(reader._input_dark), dict(reader._input_reads),
            reader._battery_power_missing, set(reader._sensor_unavailable),
            set(reader._sensor_unavailable_since))


def _one_read(raw, name, *, allow_none):
    r = _reader({"sensor.x": _state(raw, "W")}, {})
    r._input_dark, r._input_reads = {}, {}
    r._battery_power_missing = False
    value = r._read_sensor("sensor.x", name, allow_none=allow_none)
    return value, _tallies(r)


class TestTheReaderCountsNoNumberDark:
    @pytest.mark.parametrize("name", POWER_INPUTS + ["ev", "battery_soc"])
    @pytest.mark.parametrize("raw", NO_NUMBER)
    @pytest.mark.parametrize("allow_none", [False, True])
    def test_the_same_as_unavailable(self, raw, name, allow_none):
        assert (_one_read(raw, name, allow_none=allow_none)
                == _one_read("unavailable", name, allow_none=allow_none))

    @pytest.mark.parametrize("name", POWER_INPUTS)
    def test_the_reporter_case_none_is_dark(self, name):
        """Pinned on its own, so the oracle above cannot pass by both sides
        being wrong in the same way."""
        value, (dark, reads, *_rest) = _one_read("none", name, allow_none=False)
        assert value == 0.0
        assert dark == {name: 1}
        assert reads == {}

    def test_a_real_number_is_still_a_read(self):
        value, (dark, reads, missing, unavailable, _since) = _one_read(
            "0", "battery", allow_none=False)
        assert value == 0.0
        assert dark == {} and reads == {"battery": 1}
        assert missing is False and unavailable == set()

    def test_a_kw_number_still_converts(self):
        r = _reader({"sensor.x": _state("1.5", "kW")}, {})
        assert r._read_sensor("sensor.x", "solar") == 1500.0

    def test_a_number_after_none_is_a_recovery(self):
        states = {"sensor.x": _state("none", "W")}
        r = _reader(states, {})
        r._read_sensor("sensor.x", "grid")
        assert "sensor.x" in r._sensor_unavailable
        states["sensor.x"] = _state("250", "W")
        assert r._read_sensor("sensor.x", "grid") == 250.0
        assert "sensor.x" not in r._sensor_unavailable
        assert "sensor.x" not in r._sensor_unavailable_since

    @patch("custom_components.solar_energy_management.coordinator.repair_issues")
    def test_a_sensor_stuck_on_none_gets_the_repair(self, ri):
        """The Repair says SEM cannot use the sensor until it gives a valid
        value — true for "none" as for "unavailable"."""
        ri.UNAVAILABLE_REPAIR_THRESHOLD_S = 300
        raised = []
        ri.raise_sensor_unavailable.side_effect = (
            lambda h, eid, friendly_name=None, minutes_unavailable=0:
            raised.append(eid))
        r = _reader({"sensor.x": _state("none", "W")}, {})
        with patch("time.monotonic", return_value=1000.0):
            r._read_sensor("sensor.x", "solar")
        with patch("time.monotonic", return_value=1301.0):
            r._read_sensor("sensor.x", "solar")
        assert raised == ["sensor.x"]


# ── 3. A whole home: read_power → to_dict, against "unavailable" ───────────

def _publish(power):
    data = SEMData()
    data.power = power
    data.status = SEMCoordinator._build_system_status(
        SimpleNamespace(_battery_arbitrage_active=False), power, "idle")
    return data.to_dict()


def _legacy_home(raw, which):
    """Solar, grid, battery power and SOC on their own sensors."""
    live = {"sensor.pv": 2000, "sensor.grid": -300, "sensor.bp": 800,
            "sensor.soc": 60}
    states = {eid: _state(raw if eid == which else v, "%" if "soc" in eid else "W")
              for eid, v in live.items()}
    return _reader(states, {
        "solar_production_sensor": "sensor.pv", "grid_power_sensor": "sensor.grid",
        "battery_power_sensor": "sensor.bp", "battery_soc_sensor": "sensor.soc",
    })


def _ed_home(raw, which):
    """Two inverters, a split grid pair, two batteries, two PV strings."""
    live = {"sensor.inv1": 1500, "sensor.inv2": 900, "sensor.imp": 0,
            "sensor.exp": 400, "sensor.b1": 600, "sensor.b2": 300,
            "sensor.pv1": 800, "sensor.pv2": 700}
    states = {eid: _state(raw if eid == which else v, "W")
              for eid, v in live.items()}
    r = _reader(states, {})
    r.hass.states.async_all = MagicMock(return_value=[])
    r._sign_vote_warmup = 0
    r.set_energy_dashboard_config(EnergyDashboardConfig(
        solar_power="sensor.inv1", solar_power_list=["sensor.inv1", "sensor.inv2"],
        grid_power_from="sensor.imp", grid_power_to="sensor.exp",
        battery_power="sensor.b1", battery_power_list=["sensor.b1", "sensor.b2"],
        has_solar=True, has_grid=True, has_battery=True))
    r.set_pv_strings({"pv1_power": "sensor.pv1", "pv2_power": "sensor.pv2"})
    return r


def _as_published(reader):
    power = reader.read_power()
    return dataclasses.asdict(power), _publish(power)


LEGACY = ["sensor.pv", "sensor.grid", "sensor.bp", "sensor.soc"]
ED = ["sensor.inv1", "sensor.inv2", "sensor.imp", "sensor.exp",
      "sensor.b1", "sensor.b2", "sensor.pv1", "sensor.pv2"]


class TestAHomeReadsNoNumberAsUnavailable:
    """The class guard: whichever path reads a sensor, a state that gives no
    number must leave the same trace as "unavailable". NaN never equals
    itself, so a "nan" let through anywhere fails here too."""

    @pytest.mark.parametrize("which", LEGACY)
    @pytest.mark.parametrize("raw", ["none", "nan", "inf", "error"])
    def test_legacy_home(self, raw, which):
        assert (_as_published(_legacy_home(raw, which))
                == _as_published(_legacy_home("unavailable", which)))

    @pytest.mark.parametrize("which", ED)
    @pytest.mark.parametrize("raw", ["none", "nan", "inf", "error"])
    def test_energy_dashboard_home(self, raw, which):
        assert (_as_published(_ed_home(raw, which))
                == _as_published(_ed_home("unavailable", which)))


class TestTheReporterCase:
    """Pinned on its own: the fleet battery power and status."""

    def test_battery_none_is_no_power_and_no_status(self):
        power = _legacy_home("none", "sensor.bp").read_power()
        assert power.battery_power_all_unavailable is True
        assert power.battery_power_read is False
        assert power.inputs_degraded is True
        assert "battery" in power.dark_inputs
        out = _publish(power)
        assert out["battery_power"] is None, "not 0 W"
        assert out["battery_status"] is None, "not 'idle'"

    def test_solar_nan_is_no_number_in_the_sums(self):
        power = _legacy_home("nan", "sensor.pv").read_power()
        assert power.solar_power == 0.0
        assert power.solar_power_unavailable is True
        assert _publish(power)["solar_power"] is None

    def test_one_battery_of_two_none_is_its_own_dark_unit(self):
        power = _ed_home("none", "sensor.b2").read_power()
        assert power.batteries["b1"].power_read is True
        assert power.batteries["b2"].power_read is False
        assert _publish(power)["battery_b2_power"] is None

    def test_a_string_nan_is_not_read(self):
        power = _ed_home("nan", "sensor.pv2").read_power()
        assert power.solar_power_per_string_read["pv2"] is False
        assert power.solar_power_per_string["pv2"] == 0.0

    def test_a_soc_nan_is_no_soc(self):
        power = _legacy_home("nan", "sensor.soc").read_power()
        assert power.battery_soc_known is False
        assert not math.isnan(power.battery_soc)

    def test_a_home_that_reads_numbers_is_untouched(self):
        """The twin: nothing dark, every figure read."""
        power = _legacy_home(None, None).read_power()
        assert power.inputs_degraded is False
        assert power.battery_power_read is True
        out = _publish(power)
        assert out["battery_power"] == 800.0
        assert out["battery_status"] == "charging"


# ── 4. The siblings ────────────────────────────────────────────────────────

class TestTheFleetSocAverage:
    """(review) The average read each unit without ``allow_none``, so a dark
    unit was a 0 % unit: 60 % and "unavailable" averaged to 30 %, covering
    2 of 2. "nan" joined that once it stopped being NaN."""

    @pytest.mark.parametrize("raw", ["unavailable", "none", "nan"])
    def test_a_dark_unit_is_left_out_not_zero(self, raw):
        r = _reader({"sensor.soc1": _state(60, "%"), "sensor.soc2": _state(raw, "%")},
                    {})
        r._soc_entity_by_power = {"sensor.b1": "sensor.soc1",
                                  "sensor.b2": "sensor.soc2"}
        assert r._read_battery_soc_average(["sensor.b1", "sensor.b2"]) == 60.0
        assert (r._soc_units_expected, r._soc_units_read) == (2, 1)

    def test_two_read_units_still_average(self):
        r = _reader({"sensor.soc1": _state(60, "%"), "sensor.soc2": _state(0, "%")},
                    {})
        r._soc_entity_by_power = {"sensor.b1": "sensor.soc1",
                                  "sensor.b2": "sensor.soc2"}
        assert r._read_battery_soc_average(["sensor.b1", "sensor.b2"]) == 30.0
        assert r._soc_units_read == 2


class TestTheEnergyCounters:
    """(review) A counter that gives no number read as 0 kWh: it looked like
    a reset, and the next real read booked the whole register into the day."""

    @staticmethod
    def _day(gap):
        from custom_components.solar_energy_management.tests.test_628_meter_reconciliation import (  # noqa: E501
            IMPORT_METER,
            _calc,
            _daily,
            _reconcile,
            _state as _kwh,
        )
        states = {IMPORT_METER: _kwh(12345.0)}
        calc = _calc(states)
        _reconcile(calc)
        states[IMPORT_METER] = _kwh(gap)
        _reconcile(calc)
        states[IMPORT_METER] = _kwh(12348.2)
        _reconcile(calc)
        return (_daily(calc), dict(calc._monthly_accumulators),
                calc._meter_baselines["grid_import"])

    @pytest.mark.parametrize("gap", ["nan", "none", "inf", "error"])
    def test_the_same_as_unavailable(self, gap):
        assert self._day(gap) == self._day("unavailable")

    def test_the_day_keeps_its_own_energy(self):
        assert self._day("nan")[0] == pytest.approx(3.2)


class TestTheForecastPowerReads:
    @staticmethod
    def _forecast(states):
        f = ForecastReader.__new__(ForecastReader)
        f.hass = MagicMock()
        f.hass.states.get = lambda eid: states.get(eid)
        f._last_unit_conversion_count = 0
        return f

    @pytest.mark.parametrize("raw", ["nan", "inf", "none"])
    def test_one_plane_with_no_number_is_left_out(self, raw):
        f = self._forecast({"sensor.a": _state(raw, "W"),
                            "sensor.b": _state("1.2", "kW")})
        assert f._sum_power_w(["sensor.a", "sensor.b"], default=-1.0) == 1200.0
        assert f._sum_power_w(["sensor.a"], default=-1.0) == -1.0

    @pytest.mark.parametrize("raw", ["nan", "inf", "none"])
    def test_a_read_with_no_number_is_the_default(self, raw):
        f = self._forecast({"sensor.a": _state(raw, "W")})
        assert f._read_power_w("sensor.a", -1.0) == -1.0

    def test_a_kw_read_still_converts_and_is_counted(self):
        f = self._forecast({"sensor.a": _state("0.5", "kW")})
        assert f._read_power_w("sensor.a", -1.0) == 500.0
        assert f._last_unit_conversion_count == 1


class TestTheLiveEvPowerSum:
    @pytest.mark.parametrize("raw", ["nan", "inf", "none"])
    def test_no_number_is_skipped_not_summed(self, raw):
        sensor = _build_sensor_with_upstreams(
            config={"ev_power_sensor": "sensor.x"},
            state_lookup={"sensor.x": _make_state(raw)})
        sensor._ev_power_upstream_entities = ["sensor.x"]
        sensor._attr_native_value = 2000
        sensor._handle_ev_power_change(MagicMock())
        assert sensor._attr_native_value == 2000
        sensor.async_write_ha_state.assert_not_called()

    def test_one_charger_nan_does_not_poison_the_other(self):
        sensor = _build_sensor_with_upstreams(
            config={}, state_lookup={"sensor.a": _make_state("nan"),
                                     "sensor.b": _make_state(3000)})
        sensor._ev_power_upstream_entities = ["sensor.a", "sensor.b"]
        sensor._handle_ev_power_change(MagicMock())
        assert sensor._attr_native_value == 3000

    def test_a_kw_charger_is_summed_in_watts(self):
        """The coordinator reads the same sensor in watts; the live sum
        added the raw 7.4 between cycles."""
        st = _state("7.4", "kW")
        sensor = _build_sensor_with_upstreams(
            config={}, state_lookup={"sensor.a": st})
        sensor._ev_power_upstream_entities = ["sensor.a"]
        sensor._handle_ev_power_change(MagicMock())
        assert sensor._attr_native_value == 7400


class TestTheHeldPowerHistory:
    @pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "none"])
    def test_no_number_breaks_the_run(self, raw):
        def row(t, v):
            return SimpleNamespace(state=v, last_changed=SimpleNamespace(
                timestamp=lambda t=t: float(t)))
        rows = [row(0, "500"), row(30, raw), row(60, "500"), row(120, "500")]
        held = held_power_from_states(rows, 1.0, end=130.0, cap_w=10_000.0)
        assert math.isfinite(held)
        assert held_power_from_states(
            [row(0, "500"), row(30, "unavailable"), row(60, "500"),
             row(120, "500")], 1.0, end=130.0, cap_w=10_000.0) == held


class TestSensorsReady:
    @pytest.mark.parametrize("raw", ["none", "nan", "error"])
    def test_no_number_is_not_ready(self, raw):
        r = _reader({"sensor.pv": _state(raw, "W"), "sensor.grid": _state(raw, "W")},
                    {"solar_production_sensor": "sensor.pv",
                     "grid_power_sensor": "sensor.grid"})
        assert r.sensors_ready() is False

    def test_a_number_is_ready(self):
        r = _reader({"sensor.pv": _state("none", "W"), "sensor.grid": _state(0, "W")},
                    {"solar_production_sensor": "sensor.pv",
                     "grid_power_sensor": "sensor.grid"})
        assert r.sensors_ready() is True
