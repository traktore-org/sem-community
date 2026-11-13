"""(#1310) Today's plan printed "Osiągnięto Min ({kwh} kWh)".

@matekogon, 2.3.0-beta.9, Polish: the Today's plan card showed the row
"Jutro 03:15 — Osiągnięto Min ({kwh} kWh)" under a charge start marked
"planned window — energy plan block". The row is built in two places. The
older estimate fills ``{kwh}`` with the kWh still owed to Min; the row built
from the energy plan's blocks (#742) gave no values at all, so the card's
``_format`` had nothing to put in the text and showed the raw name.

The same shape sat in the target row: with no target kWh it sent ``{}`` for a
text that names ``{kwh}``.

Guards:
* every row the composer can build, in every language, gets a value for each
  ``{name}`` its label and detail texts name (run on real composes that reach
  every ``PlanRow(...)`` call in the module — this also covers a detail key
  picked at run time);
* an AST check over every ``PlanRow(...)`` in ``today_plan.py``: the keys the
  label/detail name must be in the ``values`` dict on every branch.
"""
import ast
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from custom_components.solar_energy_management.coordinator import today_plan
from custom_components.solar_energy_management.coordinator.today_plan import (
    KIND_EV_MIN_REACHED,
    KIND_EV_TARGET_REACHED,
    compose_today_plan,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "coordinator" / "today_plan.py"
TZ = timezone.utc
NOW = datetime(2026, 11, 9, 21, 49, tzinfo=TZ)   # the clock in the screenshot
_PH = re.compile(r"\{(\w+)\}")


@pytest.fixture(scope="module")
def tables():
    return json.loads(
        (ROOT / "dashboard" / "translations.json").read_text(encoding="utf-8"))


def _blocks(*windows, late=False):
    return [{"start": s.isoformat(), "end": e.isoformat(), "power_w": 7000.0,
             **({"late": True} if late else {})} for s, e in windows]


def _prices(levels):
    """Hourly points from the next whole hour, one level each."""
    start = NOW.replace(minute=0) + timedelta(hours=1)
    return [{"t": (start + timedelta(hours=i)).isoformat(), "price": 0.3 + i / 100,
             "level": lv} for i, lv in enumerate(levels)]


def _scenarios():
    """Composes that, between them, reach every row kind the module builds.

    The composer keeps 8 rows, so each scenario holds only a few kinds.
    """
    night = NOW + timedelta(minutes=11)
    yield "reporter: joint plan blocks", dict(
        now=NOW, ev_min_remaining_kwh=8.4, night_start=night,
        ev_deadline=NOW + timedelta(hours=8, minutes=11),
        ev_plan_blocks=_blocks((NOW + timedelta(minutes=11),
                                NOW + timedelta(hours=5, minutes=26))))
    yield "joint plan with a top-up block", dict(
        now=NOW, ev_min_remaining_kwh=8.4,
        ev_plan_blocks=_blocks((NOW + timedelta(hours=1), NOW + timedelta(hours=2)))
        + _blocks((NOW + timedelta(hours=6), NOW + timedelta(hours=7)), late=True))
    yield "estimate, cheap hold", dict(
        now=NOW, ev_min_remaining_kwh=6.0, ev_effective_rate_kw=3.7,
        ev_tariff_optimized=True, ev_tariff_waiting=True,
        ev_next_cheap_window=NOW + timedelta(hours=2))
    for detail in ("plan_ev_charge_night", "plan_ev_charge_estimate", None):
        yield f"estimate, night start, detail={detail}", dict(
            now=NOW, ev_min_remaining_kwh=6.0, ev_effective_rate_kw=3.7,
            night_start=night, ev_row_detail=detail)
    for pause in (True, False):
        yield f"tariff blocks, pause claim={pause}", dict(
            now=NOW, currency="PLN",
            ev_tariff_optimized=pause, ev_min_remaining_kwh=6.0 if pause else None,
            upcoming_prices=_prices(["cheap", "cheap", "normal",
                                     "expensive", "expensive", "normal"]))
    yield "solar, battery full, export closes", dict(
        now=NOW.replace(hour=8), solar_peak_time="12:30", solar_remaining_kwh=9.2,
        battery_full_eta=NOW.replace(hour=8) + timedelta(hours=3),
        export_closes_at=NOW.replace(hour=8) + timedelta(hours=4))
    yield "battery empty, export reopens", dict(
        now=NOW, battery_empty_eta=NOW + timedelta(hours=3),
        export_reopens_at=NOW + timedelta(hours=4))
    yield "live target", dict(
        now=NOW, ev_target_eta=NOW + timedelta(hours=2), ev_target_kwh=22.5)
    yield "live target with no kWh", dict(
        now=NOW, ev_target_eta=NOW + timedelta(hours=2))
    yield "devices", dict(
        now=NOW, device_runs=[
            {"name": "Pompa", "when": NOW + timedelta(hours=1), "done": False},
            {"name": "Bojler", "when": NOW, "done": True}])


def _plan_row_calls():
    """Every ``PlanRow(...)`` call in the module, as AST nodes."""
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "PlanRow"]


def _compose_recording_builders(kw):
    """Compose, and note the line of each ``PlanRow(...)`` that built a row."""
    real = today_plan.PlanRow
    lines = set()

    def spy(*a, **k):
        lines.add(sys._getframe(1).f_lineno)
        return real(*a, **k)

    with patch.object(today_plan, "PlanRow", spy):
        plan = compose_today_plan(**kw)
    return plan, lines


class TestTheReportedRow:
    def test_the_plan_blocks_row_carries_the_kwh(self):
        plan = compose_today_plan(**dict(_scenarios())["reporter: joint plan blocks"])
        row = next(r for r in plan if r["kind"] == KIND_EV_MIN_REACHED)
        assert row["label"] == "plan_ev_min_reached"
        assert row["values"] == {"kwh": "8.4"}

    def test_both_builders_say_the_same_kwh(self):
        """The plan-blocks row and the estimate row name one quantity."""
        joint = compose_today_plan(
            now=NOW, ev_min_remaining_kwh=6.3,
            ev_plan_blocks=_blocks((NOW + timedelta(hours=1),
                                    NOW + timedelta(hours=3))))
        est = compose_today_plan(
            now=NOW, ev_min_remaining_kwh=6.3, ev_effective_rate_kw=3.7,
            night_start=NOW + timedelta(hours=1))
        pick = [next(r for r in p if r["kind"] == KIND_EV_MIN_REACHED)["values"]
                for p in (joint, est)]
        assert pick == [{"kwh": "6.3"}, {"kwh": "6.3"}]

    def test_a_target_with_no_kwh_is_no_row(self):
        """Its text names {kwh}; with none, the row would print the name."""
        plan = compose_today_plan(now=NOW, ev_target_eta=NOW + timedelta(hours=2))
        assert [r for r in plan if r["kind"] == KIND_EV_TARGET_REACHED] == []

    def test_a_target_of_zero_kwh_is_still_a_row(self):
        plan = compose_today_plan(now=NOW, ev_target_eta=NOW + timedelta(hours=2),
                                  ev_target_kwh=0.0)
        row = next(r for r in plan if r["kind"] == KIND_EV_TARGET_REACHED)
        assert row["values"] == {"kwh": "0.0"}


class TestEveryRowFillsItsText:
    @pytest.fixture(scope="class")
    def rows(self):
        return [(name, r) for name, kw in _scenarios()
                for r in compose_today_plan(**kw)]

    def test_the_scenarios_reach_every_builder(self):
        """Each ``PlanRow(...)`` line builds a row in some scenario — so the
        name check below runs on every builder, not one per kind."""
        built = set()
        for _name, kw in _scenarios():
            built |= _compose_recording_builders(kw)[1]
        want = {c.lineno for c in _plan_row_calls()}
        assert want - built == set(), f"no scenario reaches lines {sorted(want - built)}"
        assert built <= want, f"the spy saw lines that are no call: {sorted(built - want)}"

    def test_every_name_in_every_language_has_a_value(self, rows, tables):
        bad = []
        for name, r in rows:
            for field in ("label", "detail"):
                key = r.get(field)
                if not key:
                    continue
                for lang, table in tables.items():
                    text = table.get(key)
                    assert text is not None, f"{lang} has no {key}"
                    need = set(_PH.findall(text)) - set(r.get("values") or {})
                    if need:
                        bad.append((name, lang, key, sorted(need)))
        assert not bad, f"rows that print a raw {{name}}: {bad[:6]}"


def _dict_keys(node):
    """Keys a ``values=`` expression gives on its WORST branch, or None."""
    if node is None:
        return set()
    if isinstance(node, ast.Dict):
        if not all(isinstance(k, ast.Constant) for k in node.keys):
            return None
        return {k.value for k in node.keys}
    if isinstance(node, ast.IfExp):
        a, b = _dict_keys(node.body), _dict_keys(node.orelse)
        return None if a is None or b is None else a & b
    return None


class TestEveryPlanRowCall:
    def test_values_cover_what_the_texts_name(self, tables):
        en = tables["en"]
        calls = _plan_row_calls()
        assert len(calls) >= 15, "the scan lost the PlanRow calls"
        bad = []
        for call in calls:
            if call.args or any(k.arg is None for k in call.keywords):
                bad.append((call.lineno, "positional or ** args the scan cannot read"))
                continue
            kws = {k.arg: k.value for k in call.keywords}
            keys = {c.value for f in ("label", "detail") if f in kws
                    for c in ast.walk(kws[f])
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)
                    and c.value in en}
            need = set().union(*(set(_PH.findall(en[k])) for k in keys)) if keys else set()
            have = _dict_keys(kws.get("values"))
            if have is None:
                bad.append((call.lineno, "values the scan cannot read"))
            elif need - have:
                bad.append((call.lineno, sorted(need - have)))
        assert not bad, f"PlanRow calls that leave a {{name}} empty: {bad}"
