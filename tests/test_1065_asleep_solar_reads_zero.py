"""#1065 — an inverter asleep at night reads 0 W, not its last daytime value.

RienduPre's two Growatt inverters report through Grott over MQTT. At dusk they
go to sleep and stop sending; the entities stay 'available' holding their last
value. One string froze at 8.1 W at 19:23, and SEM published 8 W of solar —
``sem_solar_power``, ``sem_flow_solar_to_home_power`` and
``sem_pv_string_pv1_power`` — all night.

SEM already KNEW this reading was an asleep inverter: #851's predicate (a solar
sensor that stopped reporting, ≤ 25 W, sun below the horizon) silenced the
frozen-sensor warning for exactly this shape. It only silenced the warning.
The value path never asked, so the held 8.1 W kept feeding the balance; and the
per-string read never asked either, so the same entity was republished per
string.

The fix is the one predicate, read by both paths: what the warning calls
asleep reads 0 W. Everything the warning still flags keeps its value — solar
stale in daylight, stale above 25 W at night, an unknown sun, a fresh reading.
"""
from __future__ import annotations

import ast
import pathlib
import textwrap
from datetime import timedelta
from unittest.mock import MagicMock, Mock

import homeassistant.util.dt as dt_util
import pytest

from custom_components.solar_energy_management.coordinator import sensor_reader as sr_mod
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.ha_energy_reader import (
    EnergyDashboardConfig,
)

STALE_S = 90 * 60          # 19:23 → 20:52, the reporter's snapshot
FRESH_S = 5


def _state(value, age_s: float, unit: str = "W"):
    s = Mock()
    s.state = str(value)
    s.attributes = {"unit_of_measurement": unit, "friendly_name": "PV"}
    now = dt_util.utcnow()
    s.last_updated = now - timedelta(seconds=age_s)
    s.last_reported = now - timedelta(seconds=age_s)
    return s


def _sun(state: str):
    s = Mock()
    s.state = state
    s.attributes = {}
    return s


def _reader(states: dict, sun: str | None = "below_horizon", config=None):
    hass = MagicMock()
    table = dict(states)
    if sun is not None:
        table["sun.sun"] = _sun(sun)
    hass.states.get = MagicMock(side_effect=lambda eid: table.get(eid))
    hass.states.async_all = MagicMock(return_value=[])
    reader = SensorReader(hass, config or {})
    reader._sign_vote_warmup = 0
    return reader, table


# The reporter's diagnostics dump: three Energy-Dashboard solar sources, which
# #378 also uses as the three PV-string slots.
PV1 = "sensor.cmg4bd702g_pv1_power"
PV2 = "sensor.dng0a4702r_pv1_power"
PV3 = "sensor.dng0a4702r_pv2_power"


def _reporters_night(sun="below_horizon", pv1=8.1, pv1_age=STALE_S):
    reader, table = _reader({
        PV1: _state(pv1, pv1_age),
        PV2: _state(0.0, STALE_S),
        PV3: _state(0.0, STALE_S),
    }, sun=sun)
    ed = EnergyDashboardConfig(
        solar_power=PV1,
        solar_power_list=[PV1, PV2, PV3],
        has_solar=True,
    )
    reader.set_energy_dashboard_config(ed)
    reader.set_pv_strings({"pv1_power": PV1, "pv2_power": PV2, "pv3_power": PV3})
    return reader, table


class TestTheReportersNight:
    def test_asleep_inverter_reads_zero_in_total_and_per_string(self):
        """20:52, sun −16°, PV1 frozen at 8.1 W since 19:23."""
        reader, _ = _reporters_night()
        readings = reader.read_power()
        assert readings.solar_power == 0.0, (
            "an inverter asleep at night produces nothing — 8.1 W held from "
            "19:23 is not a reading"
        )
        assert readings.solar_power_per_string["pv1"] == 0.0, (
            "the per-string sensor must say what the total says"
        )
        assert readings.inverters[PV1].power_w == 0.0
        assert sum(readings.solar_power_per_string.values()) == readings.solar_power

    def test_asleep_zero_is_a_reading_not_a_dark_input(self):
        """SEM KNOWS the value is 0 W — this is not 'unavailable'."""
        reader, _ = _reporters_night()
        readings = reader.read_power()
        assert readings.solar_power_unavailable is False
        assert "solar" not in readings.dark_inputs

    def test_same_value_in_daylight_is_kept(self):
        """A stall in daylight is a fault the user must see — the value is
        not knowable, so SEM keeps it and warns (W3), as before."""
        reader, _ = _reporters_night(sun="above_horizon")
        readings = reader.read_power()
        assert readings.solar_power == pytest.approx(8.1)
        assert readings.solar_power_per_string["pv1"] == pytest.approx(8.1)
        assert PV1 in reader._frozen_sensors

    def test_fresh_small_reading_at_night_is_kept(self):
        """An inverter still REPORTING 8 W after sunset is a measurement."""
        reader, _ = _reporters_night(pv1_age=FRESH_S)
        readings = reader.read_power()
        assert readings.solar_power == pytest.approx(8.1)
        assert readings.solar_power_per_string["pv1"] == pytest.approx(8.1)

    def test_stale_above_threshold_at_night_is_kept_and_warns(self):
        """40 W held at midnight is the stuck reading #851 still flags."""
        reader, _ = _reporters_night(pv1=40.0)
        readings = reader.read_power()
        assert readings.solar_power == pytest.approx(40.0)
        assert PV1 in reader._frozen_sensors

    def test_unknown_sun_keeps_the_value(self):
        reader, _ = _reporters_night(sun=None)
        readings = reader.read_power()
        assert readings.solar_power == pytest.approx(8.1)

    def test_inverter_waking_reads_its_value_again(self):
        """The rule never sticks: the first fresh report is read as-is."""
        reader, table = _reporters_night()
        assert reader.read_power().solar_power == 0.0
        table[PV1] = _state(14.0, FRESH_S)
        table["sun.sun"] = _sun("above_horizon")
        readings = reader.read_power()
        assert readings.solar_power == pytest.approx(14.0)
        assert readings.solar_power_per_string["pv1"] == pytest.approx(14.0)

    def test_sunrise_before_the_inverter_wakes_stays_zero(self):
        """Review finding: sunrise brings no new data. The dusk report, judged
        asleep, must not come back as 8 W of production until the inverter
        sends a NEW report."""
        reader, table = _reporters_night()
        assert reader.read_power().solar_power == 0.0
        table["sun.sun"] = _sun("above_horizon")          # same reports, sun up
        readings = reader.read_power()
        assert readings.solar_power == 0.0
        assert readings.solar_power_per_string["pv1"] == 0.0
        # ...and the warning still speaks: a report that never comes in
        # daylight is the fault W3 exists for. The hold is the value's only.
        assert PV1 in reader._frozen_sensors

    def test_a_report_never_judged_asleep_is_not_held(self):
        """The hold needs a night verdict first: the same stale report seen
        only in daylight keeps its value (W3 flags it)."""
        reader, table = _reporters_night(sun="above_horizon")
        assert reader.read_power().solar_power == pytest.approx(8.1)
        table["sun.sun"] = _sun("below_horizon")
        assert reader.read_power().solar_power == 0.0

    def test_negative_standby_draw_reads_zero(self):
        """Some inverters report their own night draw as −6 W."""
        reader, _ = _reporters_night(pv1=-6.0)
        readings = reader.read_power()
        assert readings.solar_power == 0.0
        assert readings.solar_power_per_string["pv1"] == 0.0


class TestMissingInformationKeepsTheValue:
    @pytest.mark.parametrize("stamp", ["mock", "none"])
    def test_unreadable_report_stamp(self, stamp):
        s = Mock()
        s.state = "8.1"
        s.attributes = {"unit_of_measurement": "W"}
        if stamp == "mock":
            s.last_reported = MagicMock()
            s.last_updated = MagicMock()
        else:
            s.last_reported = None
            s.last_updated = None
        reader, _ = _reader({PV1: s})
        assert reader._read_solar_power(PV1) == pytest.approx(8.1)


class TestEveryOtherSolarRead:
    def test_single_ed_solar_sensor(self):
        reader, _ = _reader({PV1: _state(8.1, STALE_S)})
        reader.set_energy_dashboard_config(
            EnergyDashboardConfig(solar_power=PV1, solar_power_list=[PV1], has_solar=True))
        assert reader.read_power().solar_power == 0.0

    def test_solar_override_sensor(self):
        """#592 override (energy-only Energy Dashboard)."""
        reader, _ = _reader({"sensor.my_solar": _state(8.1, STALE_S)},
                            config={"solar_production_sensor": "sensor.my_solar"})
        reader.set_energy_dashboard_config(
            EnergyDashboardConfig(solar_energy="sensor.pv_kwh",
                                  solar_energy_list=["sensor.pv_kwh"], has_solar=True))
        assert reader.read_power().solar_power == 0.0

    def test_legacy_config(self):
        reader, _ = _reader({"sensor.my_solar": _state(8.1, STALE_S)},
                            config={"solar_production_sensor": "sensor.my_solar"})
        assert reader.read_power().solar_power == 0.0

    def test_legacy_per_string(self):
        reader, _ = _reader({
            "sensor.my_solar": _state(8.1, STALE_S),
            PV1: _state(8.1, STALE_S), PV2: _state(0.0, STALE_S),
        }, config={"solar_production_sensor": "sensor.my_solar"})
        reader.set_pv_strings({"pv1_power": PV1, "pv2_power": PV2})
        readings = reader.read_power()
        assert readings.solar_power_per_string == {"pv1": 0.0, "pv2": 0.0}

    def test_voltage_times_current_string(self):
        """V+I synthesis: 300 V × 0.03 A frozen at dusk is 9 W of nothing."""
        reader, _ = _reader({
            "sensor.inv_pv_1_voltage": _state(300.0, STALE_S, unit="V"),
            "sensor.inv_pv_1_current": _state(0.03, STALE_S, unit="A"),
            "sensor.inv_pv_2_voltage": _state(0.0, STALE_S, unit="V"),
            "sensor.inv_pv_2_current": _state(0.0, STALE_S, unit="A"),
        })
        reader.set_pv_strings({}, {
            "pv1": ("sensor.inv_pv_1_voltage", "sensor.inv_pv_1_current"),
            "pv2": ("sensor.inv_pv_2_voltage", "sensor.inv_pv_2_current"),
        })
        assert reader._read_pv_string_source(
            "pv1", reader._pv_strings["pv1"]) == 0.0

    def test_voltage_times_current_with_one_side_live_is_kept(self):
        """A live current reading is a measurement — only a fully silent
        string is asleep."""
        reader, _ = _reader({
            "sensor.inv_pv_1_voltage": _state(300.0, STALE_S, unit="V"),
            "sensor.inv_pv_1_current": _state(0.03, FRESH_S, unit="A"),
        })
        assert reader._read_pv_string_source(
            "pv1", ("sensor.inv_pv_1_voltage", "sensor.inv_pv_1_current"),
        ) == pytest.approx(9.0)


class TestOnePredicate:
    def test_warning_and_value_share_the_threshold(self):
        """The warning's 'asleep' and the value's 'asleep' are one rule: at
        25 W both say asleep, at 26 W both say a reading."""
        for watts, asleep in ((25.0, True), (26.0, False)):
            reader, _ = _reader({PV1: _state(watts, STALE_S)})
            got = reader._read_solar_power(PV1)
            assert (got == 0.0) is asleep, watts
            assert (PV1 not in reader._frozen_sensors) is asleep, watts

    def test_every_solar_read_goes_through_one_door(self):
        """Structural: a NEW solar read that calls ``_read_sensor(..., "solar")``
        directly — or a per-string read that skips ``_read_pv_string_source``
        — would bring the held night value back. Only the two doors may. A
        label passed as a variable may only appear in a pass-through helper,
        and that helper's own callers are checked by the same rule."""
        offenders, found = _scan_solar_reads()
        assert not offenders, offenders
        # Vacuity: the walker must actually see both doors.
        assert ("_read_solar_power", "solar") in found
        assert ("_read_pv_string_source", "pv string") in found

    def test_the_guard_catches_a_bypass(self):
        """Vacuity of the walker itself, on code it was not written for."""
        src = textwrap.dedent("""
            class R:
                def a(self):
                    return self._read_sensor(x, "solar")
                def b(self):
                    return self._read_sensor(x, name="solar")
                def c(self):
                    return self._read_sensors_sum(xs, "solar")
                def d(self, slot):
                    return self._read_sensor(x, f"pv_{slot}")
                def e(self, label):
                    return self._read_sensor(x, label)
        """)
        offenders, _ = _scan_solar_reads({"probe.py": src})
        assert sorted(o[0] for o in offenders) == ["a", "b", "c", "d", "e"]


_DOORS = {"solar": "_read_solar_power", "pv string": "_read_pv_string_source"}
# Helpers that pass a caller's label straight through. Their callers are
# checked like any other call, because the helper is a callee below.
_PASS_THROUGH = {"_read_sensors_sum"}
_CALLEES = {"_read_sensor"} | _PASS_THROUGH


def _package_sources() -> dict:
    root = pathlib.Path(sr_mod.__file__).resolve().parent.parent
    out = {}
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(("tests/", "tools/")) or "__pycache__" in rel:
            continue
        out[rel] = path.read_text(encoding="utf-8")
    return out


def _scan_solar_reads(sources: dict | None = None):
    offenders, found = [], set()
    for rel, src in (sources or _package_sources()).items():
        tree = ast.parse(src)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in ast.walk(fn):
                if not (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr in _CALLEES):
                    continue
                label = call.args[1] if len(call.args) >= 2 else next(
                    (k.value for k in call.keywords if k.arg == "name"), None)
                if label is None:
                    continue
                if isinstance(label, ast.Constant):
                    text = str(label.value)
                    kind = ("solar" if text == "solar"
                            else "pv string" if text.startswith("pv_") else None)
                elif isinstance(label, ast.JoinedStr):
                    head = label.values[0] if label.values else None
                    kind = ("pv string" if isinstance(head, ast.Constant)
                            and str(head.value).startswith("pv_") else None)
                else:
                    kind = "variable"
                if kind is None:
                    continue
                if kind == "variable":
                    if fn.name not in _PASS_THROUGH:
                        offenders.append((fn.name, rel, call.lineno, kind))
                    continue
                found.add((fn.name, kind))
                if fn.name != _DOORS[kind]:
                    offenders.append((fn.name, rel, call.lineno, kind))
    return offenders, found
