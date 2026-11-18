"""(#1382) The day's flow split keeps one base all day.

The split (grid to house, sun to battery …) is published as daily counters.
#1324 fitted it to the day's totals, but picked the base from this cycle's
counter reads: the day's rows while the home row was the meters' balance,
the split's own sums for the rest otherwise, and the raw split when no
counter read at all. One missing read switched the base, and the counters
stepped back by the day's whole gap between the bases (up to about 1 kWh).
The recorder reads a big step back as a reset; a chart built on those
counters then counts the day again (test system: grid 15.1 kWh against
8.1 kWh real import).

The rule: with grid or battery counters set up, the targets are the day's
rows and the house is their balance, whatever this cycle read.
"""
from __future__ import annotations

import ast
import textwrap
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Optional
from unittest.mock import Mock

import pytest
from freezegun import freeze_time

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    MIDNIGHT_EV_CATEGORY,
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.flow_calculator import (
    fit_flows_to_totals,
)
from custom_components.solar_energy_management.coordinator.types import (
    EnergyFlows,
    PowerReadings,
)
from custom_components.solar_energy_management.utils.time_manager import TimeManager

ROOT = Path(__file__).resolve().parent.parent
DAY = date(2026, 11, 17)

SOLAR = "sensor.inverter_total_yield"
METERS = {
    "grid_import": "sensor.p1_import",
    "grid_export": "sensor.p1_export",
    "battery_charge": "sensor.bms_charged",
    "battery_discharge": "sensor.bms_discharged",
}

# A test-system day. The rows are what the counters say; the home row is
# what the integrator had before the balance ran.
ROWS = {
    "solar": 9.40, "grid_import": 8.10, "grid_export": 1.20,
    "battery_charge": 4.60, "battery_discharge": 3.90, "home": 13.0,
}
EV_ROW = 2.30
# The split as integrated: its sums run short of the rows, by about 1 kWh
# on solar — the gap between the two bases.
RAW = dict(
    solar_to_home=4.10, solar_to_ev=0.40, solar_to_battery=3.20, solar_to_grid=0.70,
    grid_to_home=4.90, grid_to_ev=1.60, grid_to_battery=1.10,
    battery_to_home=3.10, battery_to_ev=0.20, battery_to_grid=0.40,
)
CELLS = tuple(RAW)


def _hass(values: dict) -> Mock:
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


def _rig(*, solar_counter: bool = True):
    values = {e: 0.0 for e in METERS.values()}
    if solar_counter:
        values[SOLAR] = 0.0
    hass = _hass(values)
    calc = EnergyCalculator({"update_interval": 10}, TimeManager(hass))
    calc.configure_solar_counters(hass, [SOLAR] if solar_counter else [], True)
    calc.configure_meter_counters(hass, {c: [e] for c, e in METERS.items()}, True)
    for category, kwh in ROWS.items():
        calc._daily_accumulators[f"{category}_{DAY}"] = kwh
    calc._daily_accumulators[f"{MIDNIGHT_EV_CATEGORY}_{DAY}"] = EV_ROW
    calc._midnight_ev_since = DAY - timedelta(days=1)
    return calc, values


def _cycle(calc: EnergyCalculator) -> None:
    """One real cycle with no power: the rows stay, only the reads change."""
    calc._last_update = None
    readings = PowerReadings()
    readings.calculate_derived()
    calc.calculate_energy(readings)


def _publish(totals: Optional[Dict[str, Optional[float]]]) -> Dict[str, float]:
    """What the coordinator publishes: the fit when there are totals."""
    flows = EnergyFlows(**RAW)
    if isinstance(totals, dict):
        flows = fit_flows_to_totals(flows, totals)
    return {c: getattr(flows, c) for c in CELLS}


def _old_rule(calc: EnergyCalculator) -> Optional[Dict[str, Optional[float]]]:
    """``calendar_day_totals`` as it was before #1382: picked by this cycle."""
    today, acc, backed = calc.booking_day, calc._daily_accumulators, calc._counter_backed
    if today is None:
        return None
    if "home" not in backed:
        metered = ("grid_import", "grid_export", "battery_charge", "battery_discharge")
        if not [c for c in metered if c in backed]:
            return None
        out = {"solar": None, "home": None, "ev": None}
        for c in metered:
            out[c] = acc.get(f"{c}_{today}", 0.0) if c in backed else None
        return out
    out = {c: acc.get(f"{c}_{today}", 0.0) for c in (
        "solar", "grid_import", "grid_export", "battery_charge", "battery_discharge", "home")}
    out["ev"] = acc.get(f"{MIDNIGHT_EV_CATEGORY}_{today}", 0.0)
    return out


def _new_rule(calc: EnergyCalculator):
    """What the coordinator asks: the totals of the split's own day."""
    return calc.calendar_day_totals(DAY)


def _three_cycles(rule):
    """All counters read; then the import counter is gone; then all are."""
    calc, values = _rig()
    published, backed = [], []
    _cycle(calc)
    backed.append(set(calc._counter_backed))
    published.append(_publish(rule(calc)))
    values.pop(METERS["grid_import"])
    _cycle(calc)
    backed.append(set(calc._counter_backed))
    published.append(_publish(rule(calc)))
    values.clear()
    _cycle(calc)
    backed.append(set(calc._counter_backed))
    published.append(_publish(rule(calc)))
    return published, backed


@pytest.mark.unit
@freeze_time("2026-11-17 12:00:00")
def test_one_missing_read_does_not_move_the_split():
    published, backed = _three_cycles(_new_rule)
    # The reads really changed: the home balance ran, stood down, and no
    # counter read at all in the last cycle.
    assert "home" in backed[0]
    assert "home" not in backed[1] and "grid_export" in backed[1]
    assert backed[2] == set()
    for cell in CELLS:
        assert published[1][cell] == pytest.approx(published[0][cell], abs=0.001), cell
        assert published[2][cell] == pytest.approx(published[0][cell], abs=0.001), cell
    # …and the base is the day's rows: the split adds up to them.
    p = published[0]
    assert p["grid_to_home"] + p["grid_to_ev"] + p["grid_to_battery"] == pytest.approx(
        ROWS["grid_import"], abs=0.01)
    assert sum(p[c] for c in CELLS if c.startswith("solar_")) == pytest.approx(
        ROWS["solar"], abs=0.01)


@pytest.mark.unit
@freeze_time("2026-11-17 12:00:00")
def test_the_old_rule_stepped_back_on_the_same_cycles():
    """The twin: the same three cycles under the old rule move the split."""
    published, backed = _three_cycles(_old_rule)
    assert "home" in backed[0] and "home" not in backed[1]
    drops = {c: published[0][c] - published[1][c] for c in CELLS}
    assert max(drops.values()) > 0.1, drops
    drops = {c: published[0][c] - published[2][c] for c in CELLS}
    assert max(drops.values()) > 0.1, drops


@pytest.mark.unit
@freeze_time("2026-11-17 12:00:00")
def test_no_solar_counter_keeps_the_same_base():
    """PROD shape: no solar counter, so the home balance never runs."""
    calc, values = _rig(solar_counter=False)
    _cycle(calc)
    assert "home" not in calc._counter_backed
    first = _publish(calc.calendar_day_totals(DAY))
    values.clear()
    _cycle(calc)
    assert calc._counter_backed == set()
    second = _publish(calc.calendar_day_totals(DAY))
    for cell in CELLS:
        assert second[cell] == pytest.approx(first[cell], abs=0.001), cell
    assert sum(first[c] for c in CELLS if c.startswith("grid_")) == pytest.approx(
        ROWS["grid_import"], abs=0.01)


@pytest.mark.unit
def test_no_meters_leave_the_split_as_integrated():
    calc, _ = _rig()
    calc._meter_counter_enabled = False
    calc.booking_day = DAY
    for backed in (set(), {"home", "grid_import"}):
        calc._counter_backed = backed
        assert calc.calendar_day_totals(DAY) is None


@pytest.mark.unit
def test_the_ev_column_waits_for_a_whole_mirror_day():
    calc, _ = _rig()
    calc.booking_day = DAY
    assert calc.calendar_day_totals(DAY)["ev"] == EV_ROW
    for since in (DAY, None):   # born today, or not yet: the split's own EV sum
        calc._midnight_ev_since = since
        assert calc.calendar_day_totals(DAY)["ev"] is None


@pytest.mark.unit
def test_a_day_of_cycles_never_steps_back():
    """Oracle: the rows and the raw split grow all day at different rates,
    and the backing changes every few cycles. Under one base no published
    cell steps back; under the old rule they do."""
    calc = EnergyCalculator.__new__(EnergyCalculator)
    calc.booking_day = DAY
    calc._meter_counter_enabled = True
    calc._midnight_ev_since = DAY - timedelta(days=1)
    patterns = (
        {"solar", "grid_import", "grid_export", "battery_charge", "battery_discharge", "home"},
        {"grid_export", "battery_charge", "battery_discharge"},
        set(),
        {"grid_import"},
    )
    # The rows run ahead of the raw split by their own factor (the
    # integrator loses energy when a read drops out).
    factor = {"solar": 1.06, "grid_import": 1.03, "grid_export": 0.98,
              "battery_charge": 1.02, "battery_discharge": 1.04, "ev": 1.05}
    worst = {"new": 0.0, "old": 0.0}
    last = {"new": None, "old": None}
    for step in range(1, 145):
        raw = {c: v * step / 144 for c, v in RAW.items()}
        calc._daily_accumulators = {
            f"solar_{DAY}": factor["solar"] * sum(raw[c] for c in CELLS if c.startswith("solar_")),
            f"grid_import_{DAY}": factor["grid_import"] * (
                raw["grid_to_home"] + raw["grid_to_ev"] + raw["grid_to_battery"]),
            f"battery_discharge_{DAY}": factor["battery_discharge"] * (
                raw["battery_to_home"] + raw["battery_to_ev"] + raw["battery_to_grid"]),
            f"grid_export_{DAY}": factor["grid_export"] * (
                raw["solar_to_grid"] + raw["battery_to_grid"]),
            f"battery_charge_{DAY}": factor["battery_charge"] * (
                raw["solar_to_battery"] + raw["grid_to_battery"]),
            f"{MIDNIGHT_EV_CATEGORY}_{DAY}": factor["ev"] * (
                raw["solar_to_ev"] + raw["grid_to_ev"] + raw["battery_to_ev"]),
            f"home_{DAY}": 13.0 * step / 144,
        }
        calc._counter_backed = patterns[(step // 3) % len(patterns)]
        for name, rule in (("new", _new_rule), ("old", _old_rule)):
            flows = EnergyFlows(**raw)
            totals = rule(calc)
            if isinstance(totals, dict):
                flows = fit_flows_to_totals(flows, totals)
            now = {c: getattr(flows, c) for c in CELLS}
            if last[name] is not None:
                worst[name] = max(worst[name], max(last[name][c] - now[c] for c in CELLS))
            last[name] = now
    assert worst["new"] <= 0.001, worst
    assert worst["old"] > 0.05, worst


@pytest.mark.unit
@freeze_time("2026-11-17 12:00:00")
def test_a_skipped_cycle_after_a_restart_keeps_the_base():
    """A restart of over two minutes: ``calculate_energy`` skips its first
    cycle and books nothing, so ``booking_day`` is still unset."""
    from datetime import datetime
    from homeassistant.util import dt as dt_util

    calc, _ = _rig()
    _cycle(calc)
    before = _publish(_new_rule(calc))
    calc.booking_day = None                      # a new process
    calc._last_update = dt_util.now() - timedelta(minutes=10)
    assert isinstance(calc._last_update, datetime)
    calc.calculate_energy(PowerReadings())
    assert calc.booking_day is None              # the cycle was skipped
    after = _publish(_new_rule(calc))
    for cell in CELLS:
        assert after[cell] == pytest.approx(before[cell], abs=0.001), cell
    # The old rule read ``booking_day``: the raw split for that cycle.
    assert _publish(_old_rule(calc)) == _publish(None)
    assert max(before[c] - _publish(None)[c] for c in CELLS) > 0.1


@pytest.mark.unit
def test_a_new_day_never_takes_yesterdays_rows():
    """A gap across midnight: the flows are the new day's, ``booking_day``
    is still yesterday. The new day's rows are empty, so nothing is scaled
    up to yesterday's totals."""
    calc, _ = _rig()
    calc.booking_day = DAY
    tomorrow = DAY + timedelta(days=1)
    totals = calc.calendar_day_totals(tomorrow)
    assert totals["grid_import"] == 0.0 and totals["solar"] == 0.0
    tiny = EnergyFlows(grid_to_home=0.003, solar_to_home=0.001)
    out = fit_flows_to_totals(tiny, totals)
    assert out.grid_to_home <= 0.003 and out.solar_to_home <= 0.001


# ── Guard: the base reads nothing ``calculate_energy`` rebuilds each cycle ──

def _rebuilt_each_cycle() -> set:
    """``self.X`` that ``calculate_energy`` sets to a fresh empty container."""
    tree = ast.parse((ROOT / "coordinator" / "energy_calculator.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "calculate_energy")
    def _empty(v: ast.AST) -> bool:
        if isinstance(v, ast.Dict):
            return not v.keys
        if isinstance(v, ast.List):
            return not v.elts
        return (isinstance(v, ast.Call) and isinstance(v.func, ast.Name)
                and v.func.id in ("set", "dict", "list") and not v.args)

    out = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue
        pairs = []
        for t in node.targets:
            if (isinstance(t, ast.Tuple) and isinstance(node.value, ast.Tuple)
                    and len(t.elts) == len(node.value.elts)):
                pairs.extend(zip(t.elts, node.value.elts, strict=True))
            else:
                pairs.append((t, node.value))
        for t, v in pairs:
            if (_empty(v) and isinstance(t, ast.Attribute)
                    and isinstance(t.value, ast.Name) and t.value.id == "self"):
                out.add(t.attr)
    return out


def _self_reads(source: str, name: str) -> set:
    tree = ast.parse(textwrap.dedent(source))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == name)
    return {n.attr for n in ast.walk(fn)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
            and n.value.id == "self"}


@pytest.mark.unit
def test_the_base_reads_no_state_of_this_cycle():
    # ``booking_day`` too: a cycle ``calculate_energy`` skips never sets it.
    per_cycle = _rebuilt_each_cycle() | {"booking_day"}
    assert {"_counter_backed", "_meter_staged"} <= per_cycle   # the scan finds them
    src = (ROOT / "coordinator" / "energy_calculator.py").read_text()
    assert not _self_reads(src, "calendar_day_totals") & per_cycle


@pytest.mark.unit
def test_the_guard_catches_the_old_rule():
    old = '''
    def calendar_day_totals(self):
        if "home" not in self._counter_backed:
            return None
        return {}
    '''
    assert "_counter_backed" in _self_reads(old, "calendar_day_totals") & _rebuilt_each_cycle()
