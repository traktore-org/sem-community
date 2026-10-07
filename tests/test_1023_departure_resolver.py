"""#1023 A0 — one resolver for the departure time.

The charge-by time was read in seven places. For a charger WITHOUT a time of
its own they disagreed: the card, the night plan and the EV-day boundary
fell back to the global time (the primary charger's, mirrored by #255) or
07:00, while the energy plan's demand and the night-deliverable window fell
back to the END of the night window — a car the card said was due at 07:00
was planned to 09:00 on a night ending then.

Every reader asks ``coordinator/departure.py`` now. The behavioural tests pin
the answer; the guard pins that no reader goes around it.
"""
from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from custom_components.solar_energy_management.coordinator.departure import (
    departure_for,
    departure_hhmm,
)
from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.ev_control import (
    EVControlMixin,
)

ROOT = Path(__file__).resolve().parents[1]
ZRH = ZoneInfo("Europe/Zurich")

OWN = {"id": "keba", "ev_target_time": "06:15"}
NONE = {"id": "zoe"}


# ── The answer ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("charger, config, want", [
    (OWN, {"ev_target_time": "08:00"}, "06:15"),     # its own wins
    (NONE, {"ev_target_time": "08:00"}, "08:00"),    # else the global one
    (NONE, {}, "07:00"),                             # else 07:00
    ({"ev_target_time": ""}, {"ev_target_time": "08:00"}, "08:00"),
    ({"ev_target_time": None}, {}, "07:00"),
    ({"ev_target_time": "soon"}, {"ev_target_time": "08:00"}, "08:00"),
    ({"ev_target_time": "25:00"}, {}, "07:00"),
])
def test_the_departure_time_of_day(charger, config, want):
    assert departure_hhmm(charger, config) == want


def test_the_next_departure_after_now():
    evening = datetime(2026, 10, 9, 22, 0, tzinfo=ZRH)
    assert departure_for(OWN, evening, {}) == datetime(2026, 10, 10, 6, 15,
                                                       tzinfo=ZRH)
    early = datetime(2026, 10, 10, 5, 0, tzinfo=ZRH)
    assert departure_for(OWN, early, {}) == datetime(2026, 10, 10, 6, 15,
                                                     tzinfo=ZRH)


# ── Every reader gives it ────────────────────────────────────────────────

def _night(start="22:00", end="09:00", hours=11.0):
    tm = MagicMock()
    tm.get_night_window.return_value = (start, end)
    tm.get_night_window_hours.return_value = hours
    tm.get_night_end_time.return_value = end
    return tm


@pytest.mark.parametrize("charger", [OWN, NONE])
def test_the_night_plan_reads_the_resolver(charger):
    config = {"ev_target_time": "07:00"}
    host = SimpleNamespace(config=config)
    assert (EVControlMixin._charger_target_time(host, charger)
            == departure_hhmm(charger, config))


@pytest.mark.parametrize("charger, hours", [(OWN, 8.25), (NONE, 9.0)])
def test_the_night_deliverable_window_ends_at_the_departure(charger, hours):
    """Night 22:00–09:00. A charger without its own time leaves at the global
    07:00 — nine hours, not the eleven up to the window's end."""
    config = {"ev_target_time": "07:00"}
    host = SimpleNamespace(config=config, time_manager=_night())
    host._charger_target_time = (
        lambda cfg: EVControlMixin._charger_target_time(host, cfg))
    cfg = {**charger, "ev_max_current": 16, "ev_phases": 1, "ev_voltage": 230}
    kwh = EVControlMixin._night_deliverable_kwh(host, cfg)
    assert kwh == pytest.approx(hours * 16 * 230 / 1000)


def test_the_ev_day_reads_the_resolver():
    config = {"ev_target_time": "07:00", "ev_chargers": [OWN, NONE]}
    calc = EnergyCalculator(config, MagicMock())
    assert calc._ev_deadlines() == ["06:15", "07:00"]


def test_no_chargers_still_has_a_day():
    calc = EnergyCalculator({}, MagicMock())
    assert calc._ev_deadlines() == ["07:00"]


# ── And nobody goes around it ────────────────────────────────────────────

#: Reads of ``ev_target_time`` allowed outside the resolver, and why.
ALLOWED = {
    # the resolver itself
    "coordinator/departure.py",
    # reads the coordinator's PUBLISHED answer, which is the resolver's
    "sensor.py",
}


def _reads(tree: ast.AST) -> list:
    """Every ``x.get("ev_target_time" …)`` and every ``x["ev_target_time"]``
    that is read, not written."""
    hits = []
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "get" and n.args
                and isinstance(n.args[0], ast.Constant)
                and n.args[0].value == "ev_target_time"):
            hits.append(n.lineno)
        elif (isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Load)
              and isinstance(n.slice, ast.Constant)
              and n.slice.value == "ev_target_time"):
            hits.append(n.lineno)
    return hits


def test_every_reader_asks_the_resolver():
    skip = {"tests", "scripts", "node_modules", ".git", "__pycache__",
            "dist", "tools"}
    found = []
    for p in sorted(ROOT.rglob("*.py")):
        rel = p.relative_to(ROOT)
        if set(rel.parts) & skip or str(rel) in ALLOWED:
            continue
        for line in _reads(ast.parse(p.read_text(encoding="utf-8"))):
            found.append(f"{rel}:{line}")
    assert not found, (
        "these read the charge-by time themselves — ask departure_hhmm / "
        f"departure_for (coordinator/departure.py): {found}")
