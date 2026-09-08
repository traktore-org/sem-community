"""#934 — one rule for a SOC on a dark cycle, and every reader of the dark
flag says what a blink does to it.

``_hold_battery_soc`` holds the last accepted SOC through a dark read and
raises ``battery_soc_unavailable`` on EVERY such cycle. Charge pacing read
that boolean as "no SOC" and its writer restored the inverter's charge-limit
register on every modbus blink, then re-engaged one cycle later — a
``number.set_value`` pair per dropout, ~500 a day on PROD's link. The pacer's
own regression is ``test_934_pacing_holds_through_a_blink.py``; this file
pins the CLASS:

* ``soc_grace.soc_for_a_limit`` is the one place that decides which SOC a
  LIMIT may be held on — the fresh read, or the held value while it is a
  measurement and younger than ``SENSOR_DARK_READ_GRACE_S``;
* the shape the reader actually makes flows through it to the wire;
* every other direct read of ``battery_soc_unavailable`` in the coordinator
  carries a ``# DARK-SOC:`` declaration — display, record, plan, or an
  ACTION that must not ride a held SOC (#932). The FLEET-READ lint pattern:
  the next limit-type consumer cannot read the boolean without saying so.
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from custom_components.solar_energy_management.consts.core import (
    SENSOR_DARK_READ_GRACE_S,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.coordinator.soc_grace import (
    soc_for_a_limit,
    soc_hold_age_s,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
)

GRACE = SENSOR_DARK_READ_GRACE_S


def _reading(**kw):
    return SimpleNamespace(**kw)


@pytest.mark.unit
class TestSocForALimit:
    def test_a_fresh_read_is_the_value(self):
        assert soc_for_a_limit(_reading(battery_soc=63.5)) == pytest.approx(63.5)

    def test_a_genuine_zero_is_a_reading(self):
        assert soc_for_a_limit(_reading(
            battery_soc=0.0, battery_soc_unavailable=False)) == pytest.approx(0.0)

    def test_a_held_measurement_inside_the_grace_is_the_value(self):
        assert soc_for_a_limit(_reading(
            battery_soc=60.0, battery_soc_unavailable=True,
            battery_soc_known=True, battery_soc_stale_s=30,
        )) == pytest.approx(60.0)

    def test_the_boundary_is_the_sensor_grace_inclusive(self):
        """Same edge as the entity hold (``_age <= SENSOR_DARK_READ_GRACE_S``):
        one grace, one boundary, everywhere a blink is forgiven."""
        at = _reading(battery_soc=60.0, battery_soc_unavailable=True,
                      battery_soc_known=True, battery_soc_stale_s=GRACE)
        past = _reading(battery_soc=60.0, battery_soc_unavailable=True,
                        battery_soc_known=True, battery_soc_stale_s=GRACE + 1)
        assert soc_for_a_limit(at) == pytest.approx(60.0)
        assert soc_for_a_limit(past) is None

    def test_a_value_never_read_is_not_a_measurement_at_any_age(self):
        """(#875) 0.0 before the first read is not an empty pack."""
        for age in (0, 5, GRACE + 60):
            assert soc_for_a_limit(_reading(
                battery_soc=0.0, battery_soc_unavailable=True,
                battery_soc_known=False, battery_soc_stale_s=age)) is None

    def test_a_dataclass_reading_carries_the_defaults_the_rule_expects(self):
        """The producer's defaults ARE the fresh-read shape: no hand-built
        flags needed for a reading that was read this cycle."""
        assert soc_for_a_limit(PowerReadings(battery_soc=42.0)) == pytest.approx(42.0)
        assert soc_hold_age_s(PowerReadings()) is None

    def test_a_dark_reading_without_an_age_is_not_a_hold(self):
        """Fail-closed: a producer that raises the flag without stamping the
        age (a hand-built reading, the scenario harness, a future reader)
        gets 'unknown', never 'held since 0 s' — an unbounded hold is the
        very thing a limit must not have."""
        assert soc_for_a_limit(_reading(
            battery_soc=60.0, battery_soc_unavailable=True)) is None
        assert soc_for_a_limit(PowerReadings(
            battery_soc=60.0, battery_soc_unavailable=True)) is None

    def test_no_reading_is_no_value(self):
        assert soc_for_a_limit(None) is None
        assert soc_for_a_limit(_reading(battery_soc=None)) is None
        assert soc_for_a_limit(_reading(battery_soc="n/a")) is None

    def test_a_garbage_age_is_no_age(self):
        assert soc_hold_age_s(_reading(battery_soc_stale_s="soon")) is None
        assert soc_hold_age_s(_reading(battery_soc_stale_s=-4)) is None
        assert soc_hold_age_s(_reading(battery_soc_stale_s=17.9)) == 17
        assert soc_hold_age_s(_reading(battery_soc_stale_s=0)) == 0


# ─── the shape the reader makes, through to the wire ────────────────────────

def _state(value):
    import homeassistant.util.dt as dt_util
    s = Mock()
    s.state = str(value)
    s.attributes = {"unit_of_measurement": "%"}
    s.last_updated = s.last_reported = dt_util.utcnow()
    return s


def _reader(soc_state, clock):
    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.get = lambda eid: _state(soc_state[0]) if eid == "sensor.soc" else None
    r = SensorReader(hass, {"battery_soc_sensor": "sensor.soc"})
    r._energy_dashboard_config = None
    r._now_monotonic = lambda: clock[0]
    return r


def _ledger(hours=8, solar_w=6800.0, home_w=800.0):
    t0 = datetime(2026, 9, 8, 8, 0)
    return [SimpleNamespace(
        start=t0 + timedelta(hours=i), end=t0 + timedelta(hours=i + 1),
        hours=1.0, soc_kwh=6.0, home_batt_kwh=0.0, solar_w=float(solar_w),
        cap_override_w=max(0.0, solar_w - home_w), grid_committed_w=0.0,
    ) for i in range(hours)]


def _pacer():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states.get = MagicMock(return_value=SimpleNamespace(state="5000"))
    fake = SimpleNamespace(
        hass=hass,
        config={
            "battery_charge_pacing_enabled": True,
            "battery_charge_power_limit_entity": "number.batt_charge_limit",
            "battery_max_target_soc": 100.0,
            "inverter_ac_limit_w": 20000.0,
            "battery_max_charge_power_w": 10000.0,
        },
        data={},
        battery_capacity_kwh=21.0,
        _planning_evidence={"forecast_trust_d1": 0.9},
        _observer_mode=False,
        _charge_pacing_writer=None,
        _today_pacing_ledger=lambda: _ledger(),
    )
    return fake, hass


def _writes(hass):
    return [c.args[2]["value"] for c in hass.services.async_call.await_args_list]


@pytest.mark.asyncio
class TestTheShapeTheReaderMakes:
    async def test_reader_to_wire_a_blink_is_held_and_an_outage_restores_once(self):
        """End to end, no hand-built flags (class 78's lesson): the reader's
        own hold feeds the pacer."""
        fake, hass = _pacer()
        soc, clock = ["40"], [1000.0]
        r = _reader(soc, clock)
        await SEMCoordinator._run_charge_pacing(fake, r.read_power())
        assert fake._charge_pacing_state["action"] == "wrote"
        cap = fake._charge_pacing_state["cap_w"]
        assert cap is not None and 0 < cap < 10000.0, "the pacer needs a real cap to hold"
        # The blink: 30 s dark.
        soc[0], clock[0] = "unavailable", 1030.0
        p = r.read_power()
        assert isinstance(p, PowerReadings) and p.battery_soc_unavailable
        await SEMCoordinator._run_charge_pacing(fake, p)
        st = fake._charge_pacing_state
        assert st["action"] == "held", st
        assert st["cap_w"] == pytest.approx(cap)
        assert st["soc"] == pytest.approx(40.0)
        assert st["soc_stale_s"] == 30
        assert len(_writes(hass)) == 1, (
            f"a blink produced a register write: {_writes(hass)} — the old "
            "flag-only read restored the register here and wrote the cap "
            "back on the next cycle")
        # Back: nothing to re-engage.
        soc[0], clock[0] = "40", 1060.0
        await SEMCoordinator._run_charge_pacing(fake, r.read_power())
        assert fake._charge_pacing_state["action"] == "held"
        assert len(_writes(hass)) == 1
        # A real outage: past the grace the pacer lets go, once.
        soc[0], clock[0] = "unavailable", 1060.0 + GRACE + 30.0
        await SEMCoordinator._run_charge_pacing(fake, r.read_power())
        st = fake._charge_pacing_state
        assert st["action"] == "restored"
        assert st["soc"] is None and st["cap_w"] is None
        assert st["soc_stale_s"] is None, "no SOC decided on → no age to show"
        assert "expired" in st["reason"]
        assert _writes(hass) == [pytest.approx(cap), 5000.0]
        clock[0] += 30.0
        await SEMCoordinator._run_charge_pacing(fake, r.read_power())
        assert fake._charge_pacing_state["action"] == "idle"
        assert len(_writes(hass)) == 2


# ─── the guard: every direct read of the dark flag declares itself ──────────

_COORD_PY = Path(__file__).resolve().parent.parent / "coordinator" / "coordinator.py"
ANNOTATION = "# DARK-SOC:"
KINDS = ("display", "record", "plan", "action")
FLAG = "battery_soc_unavailable"


def _enclosing(tree, line):
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= line <= end and (best is None or node.lineno > best[0]):
                best = (node.lineno, node.name)
    return best[1] if best else "<module>"


def _flag_reads(tree):
    """Line numbers of every read of the flag: ``x.battery_soc_unavailable``
    and ``getattr(x, "battery_soc_unavailable", ...)`` alike."""
    hits = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == FLAG:
            hits.add(node.lineno)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "getattr" and len(node.args) >= 2
              and isinstance(node.args[1], ast.Constant)
              and node.args[1].value == FLAG):
            hits.add(node.lineno)
    return sorted(hits)


def _declaration(lines, ln):
    """The ``# DARK-SOC:`` text on the read's line or the line above, or None."""
    for text in (lines[ln - 1], lines[ln - 2] if ln >= 2 else ""):
        if ANNOTATION in text:
            return text.split(ANNOTATION, 1)[1].strip()
    return None


@pytest.mark.unit
class TestEveryDarkSocReadDeclaresItself:
    def test_the_pacer_reads_the_soc_through_the_limit_rule(self):
        tree = ast.parse(_COORD_PY.read_text())
        direct = [ln for ln in _flag_reads(tree)
                  if _enclosing(tree, ln) == "_run_charge_pacing"]
        assert direct == [], (
            f"_run_charge_pacing reads the dark flag directly at {direct}; a "
            "limit is held on soc_for_a_limit(power)")
        pacing = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.AsyncFunctionDef)
                      and n.name == "_run_charge_pacing")
        called = {n.func.id for n in ast.walk(pacing)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert "soc_for_a_limit" in called

    def test_every_direct_read_declares_what_a_blink_does_to_it(self):
        lines = _COORD_PY.read_text().splitlines()
        tree = ast.parse("\n".join(lines))
        reads = _flag_reads(tree)
        assert len(reads) >= 5, "the lint found nothing — is it reading the right file?"
        offenders = []
        for ln in reads:
            decl = _declaration(lines, ln)
            if decl is None or not decl.startswith(KINDS):
                offenders.append(
                    f"  line {ln} in {_enclosing(tree, ln)}: {lines[ln - 1].strip()}")
        assert not offenders, (
            "direct reads of battery_soc_unavailable without a "
            f"'{ANNOTATION} <{'|'.join(KINDS)}> — <why>' declaration on the same "
            "or the previous line. A LIMIT reads through soc_for_a_limit; anything "
            "else says what a one-cycle blink does to it:\n" + "\n".join(offenders))
