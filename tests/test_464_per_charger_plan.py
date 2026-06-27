"""#464 — per-charger today_plan: each charger's plan strip shows ITS plan.

RienduPre's follow-up screenshot: the 12-hour plan strip rendered
identically under both Wallbox sections. Root cause: the plan was
composed once from the PRIMARY charger's night plan / target /
deadline and the EV card rendered that single fleet-level plan inside
every charger section. The fix composes one plan per charger
(``charger_<cid>_today_plan``), surfaces them as the
``per_charger_plans`` attribute on ``sensor.sem_charging_state``, and
the card's strip reads its own charger's plan.

These are anchor tests in the #351-M4 style — they pin that the
surfaces exist so a refactor can't silently collapse the plans back
to fleet-level.
"""
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent


@pytest.mark.unit
class TestPerChargerPlanSurfaces:
    def test_coordinator_emits_per_charger_plan_keys(self) -> None:
        body = (REPO / "coordinator" / "coordinator.py").read_text()
        assert 'result[f"charger_{_cid}_today_plan"]' in body, (
            "#464 anchor — per-charger today_plan result key missing; "
            "the EV card strip falls back to the fleet plan and both "
            "chargers show an identical strip again."
        )

    def test_coordinator_clears_stale_night_plans_each_cycle(self) -> None:
        # The per-charger night-plan dict used to be write-only and
        # never cleared — composing day plans from it would serve
        # yesterday's night plan. The cycle must reset it.
        body = (REPO / "coordinator" / "coordinator.py").read_text()
        assert "self._night_plan_per_charger = {}" in body.split(
            "def __init__", 1,
        )[1], (
            "#464 anchor — _night_plan_per_charger is no longer cleared "
            "per cycle; stale night plans leak into daytime per-charger "
            "plans."
        )

    def test_sensor_exposes_per_charger_plans_attribute(self) -> None:
        body = (REPO / "sensor.py").read_text()
        assert '"per_charger_plans"' in body, (
            "#464 regression — sensor.py charging_state sensor does not "
            "expose per_charger_plans; the card cannot read per-charger "
            "plans."
        )

    def test_card_strip_reads_its_chargers_plan(self) -> None:
        body = (REPO / "dashboard" / "card" / "src" / "cards"
                / "sem-ev-status-card.js").read_text()
        assert "_renderPlanStrip(id)" in body, (
            "#464 regression — the charger section renders the plan "
            "strip without passing its charger id."
        )
        assert "per_charger_plans" in body, (
            "#464 regression — the strip no longer reads "
            "per_charger_plans; both chargers show the fleet plan."
        )

    def test_card_strip_has_title_and_help(self) -> None:
        # The reporter's literal question was "what is this bar for?" —
        # the strip now carries a title and a ?-toggle help text.
        body = (REPO / "dashboard" / "card" / "src" / "cards"
                / "sem-ev-status-card.js").read_text()
        assert "plan_strip_title" in body
        assert "plan_strip_help" in body
        assert "_showHelp" in body

    def test_translations_cover_strip_title_and_help(self) -> None:
        import json
        data = json.loads(
            (REPO / "dashboard" / "translations.json").read_text(
                encoding="utf-8",
            ),
        )
        for lang, table in data.items():
            assert "plan_strip_title" in table, f"{lang} misses plan_strip_title"
            assert "plan_strip_help" in table, f"{lang} misses plan_strip_help"
