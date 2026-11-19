"""arc #921 — the plan says when the meter closes and when it reopens.

Two rows from the grid verdict's ``until``: an OPEN verdict carries the next
closing, a CLOSED one carries the reopening. Translated in all 16 languages —
``test_963_plan_events_that_wont_happen.py::TestPlanIsTranslated`` reads the
composer's keys and fails the build on any language left in English.
"""
from datetime import datetime, timezone

from custom_components.solar_energy_management.coordinator.today_plan import (
    KIND_EXPORT_CLOSED, KIND_EXPORT_REOPENS, compose_today_plan,
)

TZ = timezone.utc
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=TZ)


class TestExportRows:
    def test_a_closing_and_a_reopening_are_rows(self):
        plan = compose_today_plan(now=NOW, export_closes_at=NOW.replace(hour=14),
                                  export_reopens_at=NOW.replace(hour=16))
        kinds = [r["kind"] for r in plan]
        assert KIND_EXPORT_CLOSED in kinds and KIND_EXPORT_REOPENS in kinds

    def test_the_rows_carry_their_translation_keys(self):
        plan = compose_today_plan(now=NOW, export_closes_at=NOW.replace(hour=14))
        row = next(r for r in plan if r["kind"] == KIND_EXPORT_CLOSED)
        assert row["label"] == "plan_export_closed"

    def test_nothing_when_the_meter_stays_open(self):
        assert all(r["kind"] not in (KIND_EXPORT_CLOSED, KIND_EXPORT_REOPENS)
                   for r in compose_today_plan(now=NOW))

    def test_a_past_closing_is_not_a_row(self):
        plan = compose_today_plan(now=NOW, export_closes_at=NOW.replace(hour=9))
        assert all(r["kind"] != KIND_EXPORT_CLOSED for r in plan)

    def test_beyond_the_horizon_is_not_a_row(self):
        plan = compose_today_plan(now=NOW, horizon_hours=2, export_closes_at=NOW.replace(hour=20))
        assert all(r["kind"] != KIND_EXPORT_CLOSED for r in plan)


class TestTheCardKnowsTheKinds:
    def test_the_card_maps_both_kinds(self):
        """The card's KINDS table, parsed — not its source text (#925)."""
        import re
        from pathlib import Path
        # (#1321) the Today list of the SEM dashboard's Now screen
        text = (Path(__file__).resolve().parent.parent / "dashboard" / "card" / "src" / "util"
                / "next-today-rows.js").read_text(encoding="utf-8")
        table = text[text.index("export const KINDS = {"):text.index("};", text.index("export const KINDS = {"))]
        kinds = set(re.findall(r"^\s*([a-z_]+):\s*\{", table, re.M))
        assert {"export_closed", "export_reopens"} <= kinds
