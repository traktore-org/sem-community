"""#1316 — an inverter that goes unavailable at night is asleep, not dark.

RienduPre's Growatt MOD 9000 (Grott over MQTT) no longer freezes on its dusk
value (#1065); its entities go ``unavailable`` from dusk to dawn. #1065's rule
only lowers a stale NUMBER of ≤ 25 W to 0 W, so every night cycle was a dark
solar read:

* ``inputs_degraded`` True from 19:27 to 07:43 — and that holds every flip of
  the battery's car clamp and its release all night (#818,
  ``held_on_blind_cycle``);
* ``sem_diag_sensors_unavailable`` = 2, and the outage clock filed a
  "sensor unavailable" Repair each night;
* the whole night booked as solar downtime (#1022).

At night SEM knows what solar is: nothing. A solar entity that gives no
number with the sun down now reads 0 W and counts as a read. Links, each
driven for real:

* the reporter's night through ``read_power`` (unavailable, unknown, text);
* every solar read path: one Energy-Dashboard sensor, several inverters, the
  #592 override, the legacy config, per-string (ED and legacy), V+I pairs;
* no outage clock, no Repair, no downtime minutes, no held battery flip;
* the twins that keep today's rule: daylight, no sun entity, a missing
  entity, sunrise before the inverter wakes, and #988 refusing the 0 W when
  the balance says solar was there just after dusk.
"""
from __future__ import annotations

import ast
import inspect
import math
import textwrap
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import (
    repair_issues as ri,
)
from custom_components.solar_energy_management.coordinator.actuate_battery import (
    held_on_blind_cycle,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
)
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.coordinator.types import SEMData
from custom_components.solar_energy_management.ha_energy_reader import (
    EnergyDashboardConfig,
)
from custom_components.solar_energy_management.tests.test_1065_asleep_solar_reads_zero import (  # noqa: E501
    FRESH_S,
    _reader,
    _state,
    _sun,
)

PV = "sensor.dng0a4702r_pv_all_power"
PV2 = "sensor.cmg4bd702g_pv_all_power"
GRID = "sensor.p1_power"


def _night(pv_state="unavailable", sun="below_horizon", extra=None):
    """The reporter's setup: one ED solar sensor, a live grid meter."""
    states = {GRID: _state(-450, FRESH_S)}
    if pv_state is not None:
        states[PV] = _state(pv_state, FRESH_S)
    states.update(extra or {})
    reader, table = _reader(states, sun=sun,
                            config={"grid_power_sensor": GRID})
    reader.set_energy_dashboard_config(EnergyDashboardConfig(
        solar_power=PV, solar_power_list=[PV], has_solar=True))
    return reader, table


def _clears(cleared, entity_id) -> int:
    """Clears of one entity's Repair (the live grid meter clears its own)."""
    return sum(1 for c in cleared.call_args_list if c.args[1:] == (entity_id,))


def _clock(monkeypatch, start=1000.0):
    """The outage clock in ``_read_sensor`` reads ``time.monotonic``."""
    import time as _time
    now = [start]
    monkeypatch.setattr(_time, "monotonic", lambda: now[0])
    return now


class TestTheReportersNight:
    @pytest.mark.parametrize("dark", ["unavailable", "unknown", "none"],
                             ids=["unavailable", "unknown", "not-a-number"])
    def test_asleep_inverter_reads_0_w_and_the_cycle_is_not_degraded(self, dark):
        reader, _ = _night(dark)
        p = reader.read_power()
        assert p.solar_power == 0.0
        assert p.solar_power_unavailable is False, "SEM knows: 0 W, not unknown"
        assert p.inputs_degraded is False, (
            "an inverter asleep at night must not hold every battery flip "
            "from dusk to dawn")
        assert "solar" not in p.dark_inputs
        assert SEMData(power=p).to_dict()["solar_power"] == 0.0

    def test_no_outage_clock_no_repair_no_unavailable_count(self, monkeypatch):
        now = _clock(monkeypatch)
        raised = MagicMock()
        monkeypatch.setattr(ri, "raise_sensor_unavailable", raised)
        reader, _ = _night()
        for _ in range(3):
            reader.read_power()
            now[0] += ri.UNAVAILABLE_REPAIR_THRESHOLD_S
        raised.assert_not_called()
        assert PV not in reader._sensor_unavailable, (
            "sem_diag_sensors_unavailable counts this set")
        assert PV not in reader._sensor_unavailable_since
        assert PV in reader._entities_read, "(#1140) its Repairs have an owner"

    def test_a_repair_filed_before_dusk_is_cleared(self, monkeypatch):
        """The inverter went dark 10 min before sunset: the Repair was filed
        in daylight. Asleep at night is not a fault, so it is cleared — and
        the count and the Repair say the same thing."""
        now = _clock(monkeypatch)
        raised, cleared = MagicMock(), MagicMock()
        monkeypatch.setattr(ri, "raise_sensor_unavailable", raised)
        monkeypatch.setattr(ri, "clear_sensor_unavailable", cleared)
        reader, table = _night(sun="above_horizon")
        reader._sensor_repair_reconciled.add(PV)    # a live read earlier today
        reader.read_power()
        now[0] += ri.UNAVAILABLE_REPAIR_THRESHOLD_S
        reader.read_power()
        raised.assert_called_once()
        table["sun.sun"] = _sun("below_horizon")
        reader.read_power()
        assert _clears(cleared, PV) == 1
        assert PV not in reader._sensor_repair_raised
        reader.read_power()
        assert _clears(cleared, PV) == 1            # once, not every cycle

    def test_a_repair_from_before_a_restart_is_cleared(self, monkeypatch):
        """(#933) The Repair is persistent: the first asleep read of a new
        reader clears one an older version filed last night."""
        cleared = MagicMock()
        monkeypatch.setattr(ri, "clear_sensor_unavailable", cleared)
        reader, _ = _night()
        reader.read_power()
        assert _clears(cleared, PV) == 1

    def test_no_solar_downtime_at_night(self, monkeypatch):
        now = _clock(monkeypatch)
        reader, _ = _night()
        for _ in range(3):
            p = reader.read_power()
            now[0] += 600.0
        assert p.solar_downtime_min_today == 0.0

    def test_the_battery_clamp_is_not_held(self):
        """The #818 hold reads ``inputs_degraded``: a flip between the car
        clamp and its release goes out at night."""
        reader, _ = _night()
        p = reader.read_power()
        decision = MagicMock(intent=BatteryIntent.LIMIT_DISCHARGE)
        adapter = MagicMock(last_intent=BatteryIntent.NORMAL)
        assert held_on_blind_cycle(decision, adapter, p.inputs_degraded) is False


class TestTheTwinsKeepTodaysRule:
    def test_in_daylight_a_dark_read_stays_dark(self, monkeypatch):
        now = _clock(monkeypatch)
        raised = MagicMock()
        monkeypatch.setattr(ri, "raise_sensor_unavailable", raised)
        reader, _ = _night(sun="above_horizon")
        p = reader.read_power()
        assert p.solar_power_unavailable is True
        assert p.inputs_degraded is True and "solar" in p.dark_inputs
        now[0] += ri.UNAVAILABLE_REPAIR_THRESHOLD_S
        reader.read_power()
        raised.assert_called_once()
        assert PV in reader._sensor_unavailable

    def test_no_sun_entity_is_not_night(self):
        reader, _ = _night(sun=None)
        p = reader.read_power()
        assert p.solar_power_unavailable is True
        assert p.inputs_degraded is True

    def test_a_missing_entity_is_a_setup_fault_not_sleep(self):
        reader, _ = _night(pv_state=None)
        p = reader.read_power()
        assert p.solar_power_unavailable is True
        assert p.inputs_degraded is True

    def test_sunrise_before_the_inverter_wakes(self, monkeypatch):
        """Sun up, no number: dark again, and the outage clock starts at
        sunrise, not at dusk — no Repair the moment the sun rises."""
        now = _clock(monkeypatch)
        raised = MagicMock()
        monkeypatch.setattr(ri, "raise_sensor_unavailable", raised)
        reader, table = _night()
        reader.read_power()
        now[0] += 10 * 3600.0                           # the whole night
        reader.read_power()
        table["sun.sun"] = _sun("above_horizon")
        p = reader.read_power()
        assert p.inputs_degraded is True
        assert reader._sensor_unavailable_since[PV] == now[0]
        raised.assert_not_called()
        # In daylight a report that never comes is the fault the Repair is
        # for (the #1065 W3 rule): still dark past the threshold, it files.
        now[0] += ri.UNAVAILABLE_REPAIR_THRESHOLD_S
        reader.read_power()
        raised.assert_called_once()

    def test_the_inverter_waking_reads_its_value(self):
        reader, table = _night()
        assert reader.read_power().solar_power == 0.0
        table["sun.sun"] = _sun("above_horizon")
        table[PV] = _state(120, FRESH_S)
        p = reader.read_power()
        assert p.solar_power == 120.0
        assert p.inputs_degraded is False

    def test_a_dusk_zero_the_balance_disproves_is_still_dark(self):
        """#988 stays the net: 1.5 kW leaves the house, nothing comes in,
        and solar read 600 W a moment ago — the asleep 0 W is refused."""
        reader, table = _night(pv_state=600, extra={GRID: _state(1500, FRESH_S)})
        reader._now_monotonic = lambda: 1000.0
        first = reader.read_power()
        assert first.solar_power == 600.0
        assert first.grid_power > 0, "this meter's + is export"
        table[PV] = _state("unavailable", FRESH_S)
        p = reader.read_power()
        assert p.solar_power == 0.0
        assert p.inputs_degraded is True and "solar" in p.dark_inputs


class TestEverySolarReadPath:
    def test_several_inverters_one_asleep(self):
        reader, _ = _reader({
            PV: _state("unavailable", FRESH_S), PV2: _state(0, FRESH_S),
            GRID: _state(-450, FRESH_S)}, config={"grid_power_sensor": GRID})
        reader.set_energy_dashboard_config(EnergyDashboardConfig(
            solar_power=PV, solar_power_list=[PV, PV2], has_solar=True))
        p = reader.read_power()
        assert p.solar_power == 0.0
        assert p.inverters[PV].power_w == 0.0
        assert p.inputs_degraded is False

    def test_the_override_sensor(self):
        """#592 override beside an energy-only dashboard."""
        reader, _ = _reader({"sensor.my_solar": _state("unavailable", FRESH_S)},
                            config={"solar_production_sensor": "sensor.my_solar"})
        reader.set_energy_dashboard_config(EnergyDashboardConfig(
            solar_energy="sensor.pv_kwh", solar_energy_list=["sensor.pv_kwh"],
            has_solar=True))
        p = reader.read_power()
        assert p.solar_power == 0.0 and p.inputs_degraded is False

    def test_the_legacy_config(self):
        reader, _ = _reader({"sensor.my_solar": _state("unavailable", FRESH_S)},
                            config={"solar_production_sensor": "sensor.my_solar"})
        p = reader.read_power()
        assert p.solar_power == 0.0 and p.inputs_degraded is False

    @pytest.mark.parametrize("legacy", [False, True], ids=["ed", "legacy"])
    def test_per_string(self, legacy):
        """A string asleep at night reads 0 W, as the total does — not
        'unavailable' beside a 0 W total."""
        s1, s2 = "sensor.dng0a4702r_pv1_power", "sensor.dng0a4702r_pv2_power"
        states = {PV: _state("unavailable", FRESH_S),
                  s1: _state("unavailable", FRESH_S),
                  s2: _state("unknown", FRESH_S)}
        if legacy:
            reader, _ = _reader(states, config={"solar_production_sensor": PV})
        else:
            reader, _ = _reader(states)
            reader.set_energy_dashboard_config(EnergyDashboardConfig(
                solar_power=PV, solar_power_list=[PV], has_solar=True))
        reader.set_pv_strings({"pv1_power": s1, "pv2_power": s2})
        p = reader.read_power()
        out = SEMData(power=p).to_dict()
        assert p.solar_power_per_string == {"pv1": 0.0, "pv2": 0.0}
        assert p.solar_power_per_string_read == {"pv1": True, "pv2": True}
        assert out["pv_string_pv1_power"] == 0.0
        assert out["pv_string_pv2_power"] == 0.0
        assert s1 not in reader._sensor_unavailable

    @pytest.mark.parametrize("v,i", [
        ("unavailable", 0.0), (300.0, "unavailable"),
        ("unavailable", "unavailable")])
    def test_voltage_times_current_pair(self, v, i):
        ve, ie = "sensor.inv_pv_1_voltage", "sensor.inv_pv_1_current"
        reader, _ = _reader({ve: _state(v, FRESH_S, unit="V"),
                             ie: _state(i, FRESH_S, unit="A")})
        assert reader._read_pv_string_source("pv1", (ve, ie)) == 0.0

    def test_a_pair_with_a_negative_live_half_reads_plus_0_w(self):
        """0 V × −0.1 A is −0.0: shown as "-0 W". Asleep is 0 W."""
        ve, ie = "sensor.inv_pv_1_voltage", "sensor.inv_pv_1_current"
        reader, _ = _reader({ve: _state("unavailable", FRESH_S, unit="V"),
                             ie: _state(-0.1, FRESH_S, unit="A")})
        got = reader._read_pv_string_source("pv1", (ve, ie))
        assert got == 0.0 and math.copysign(1.0, got) == 1.0

    def test_voltage_times_current_pair_in_daylight_stays_dark(self):
        ve, ie = "sensor.inv_pv_1_voltage", "sensor.inv_pv_1_current"
        reader, _ = _reader({ve: _state("unavailable", FRESH_S, unit="V"),
                             ie: _state(2.0, FRESH_S, unit="A")},
                            sun="above_horizon")
        assert reader._read_pv_string_source("pv1", (ve, ie)) is None

    def test_a_string_in_daylight_stays_dark(self):
        reader, _ = _reader({PV: _state("unavailable", FRESH_S)},
                            sun="above_horizon")
        assert reader._read_pv_string_source("pv1", PV) is None


# ── The two doors ask first ───────────────────────────────────────────────

_DOORS = ("_read_solar_power", "_read_pv_string_source")


def _unasked_reads(src: str) -> list:
    """Each ``_read_sensor`` call in a door whose entity was not first given
    to ``_no_number_asleep`` (same expression, earlier line)."""
    out = []
    for fn in ast.walk(ast.parse(textwrap.dedent(src))):
        if not isinstance(fn, ast.FunctionDef):
            continue
        asked = []
        reads = []
        for call in ast.walk(fn):
            if not (isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute) and call.args):
                continue
            key = (ast.dump(call.args[0]), call.lineno)
            if call.func.attr == "_no_number_asleep":
                asked.append(key)
            elif call.func.attr == "_read_sensor":
                reads.append(key)
        for arg, line in reads:
            if not any(a == arg and al <= line for a, al in asked):
                out.append((fn.name, line))
    return out


class TestTheDoorsAskFirst:
    def test_every_read_in_both_doors_asks_first(self):
        """A new read in a door that skips the question would bring the dark
        night back for that path."""
        for door in _DOORS:
            src = inspect.getsource(getattr(SensorReader, door))
            assert "_read_sensor(" in src, door           # vacuity
            assert not _unasked_reads(src), door

    def test_the_check_catches_a_read_that_skips_it(self):
        src = """
            def d(self, a, b):
                if self._no_number_asleep(a, "solar"):
                    return 0.0
                x = self._read_sensor(a, "solar")
                y = self._read_sensor(b, "solar")
                return x + y
        """
        assert [line for _, line in _unasked_reads(src)] == [6]
