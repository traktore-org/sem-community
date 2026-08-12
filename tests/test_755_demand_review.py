"""#755 pillar 4 — the recommender.

Pillars 1–3 write the record, price the sun, and learn the ask. None of that
is worth anything if it stays in a JSON blob: the point of the ONE MIND is
that the house can *tell you what it learned about you*, in your language,
without you knowing what a percentile is.

This is that layer, and its whole discipline is restraint:

* it speaks in machine CODES, never prose — the card translates (C7's
  pattern), so a Dutch user reads Dutch and no internal jargon ever reaches
  a screen;
* it says nothing until the learner is confident — "still learning, 3 of 5
  nights" is an honest sentence and a made-up recommendation is not;
* it stays quiet about differences too small to act on. A card that nags
  about 200 Wh gets ignored, and then it is worth nothing when it has
  something real to say;
* it SUGGESTS. Nothing here writes a setting.
"""

import json
import re
from pathlib import Path

import pytest

from custom_components.solar_energy_management.coordinator.demand_outcome import (
    DemandRecord, NightSummary,
)
from custom_components.solar_energy_management.coordinator.demand_review import (
    DemandVerdict,
    review_demand,
    review_night,
    review_share,
)

REPO = Path(__file__).resolve().parents[1]


def _rec(actual, *, did="ev:keba", kind="ev", asked=10.0, planned=None,
         status="fits", night="2026-08-01", samples=10, measured=True,
         gap_s=0.0):
    return DemandRecord(
        demand_id=did, kind=kind, night=night, asked_kwh=asked,
        planned_kwh=asked if planned is None else planned,
        status=status, actual_kwh=actual, measured=measured, samples=samples,
        gap_s=gap_s)


def _nights(values, **kw):
    """One record per night, dated so 'most recent' is unambiguous."""
    return [_rec(v, night=f"2026-08-{i + 1:02d}", **kw)
            for i, v in enumerate(values)]


class TestTheVerdictPerDemand:
    def test_a_thin_history_says_it_is_still_learning(self):
        v = review_demand("ev:keba", _nights([7.0, 7.2]))
        assert v.code == "learning"
        assert v.nights == 2
        assert v.suggested_kwh is None

    def test_a_confident_saving_is_named_with_its_number(self):
        v = review_demand("ev:keba", _nights([5.0, 6.0, 6.5, 7.0, 8.0]))
        assert v.code == "took_less"
        assert v.asked_kwh == pytest.approx(10.0)
        assert v.suggested_kwh == pytest.approx(7.0)
        assert v.nights == 5

    def test_a_difference_too_small_to_act_on_is_not_a_recommendation(self):
        """Asked 10, learned 9.7. Telling the user to shave 300 Wh off is
        noise dressed as insight, and a card that does it every morning is a
        card nobody reads on the morning it matters."""
        v = review_demand("ev:keba",
                          _nights([9.55, 9.6, 9.65, 9.7, 9.75]))
        assert v.code == "on_target"
        assert v.suggested_kwh is None       # nothing to act on, nothing said

    def test_a_demand_that_ran_the_ask_dry_every_night_asks_for_more(self):
        v = review_demand("ev:keba", _nights([10.0] * 6))
        assert v.code == "at_ceiling"
        assert v.suggested_kwh is None or v.suggested_kwh >= 10.0

    def test_last_nights_number_rides_along(self):
        """The recommendation is about the history; the morning question is
        about last night. Both, from the same record, with no second path."""
        v = review_demand("ev:keba", _nights([5.0, 6.0, 6.5, 7.0, 8.0]))
        assert v.last_kwh == pytest.approx(8.0)      # 2026-08-05, the newest

    def test_the_ask_comes_from_the_record_not_from_a_second_source(self):
        """The record already says what was asked. Re-reading the config here
        would open a second path to the same number that can disagree with
        the one the night actually ran under."""
        recs = _nights([5.0, 6.0, 6.5, 7.0, 8.0])
        recs[-1] = _rec(8.0, asked=12.0, night="2026-08-05")
        v = review_demand("ev:keba", recs)
        assert v.asked_kwh == pytest.approx(12.0)

    def test_no_history_is_no_row(self):
        assert review_demand("ev:keba", []) is None

    def test_an_untrainable_history_is_still_a_row_but_never_a_number(self):
        """Estimated nights may not teach (#743/#744/#753). They may still be
        counted as 'we have not learned anything yet' — silence about the
        demand entirely would read as 'this device does not exist'."""
        v = review_demand("ev:keba", _nights([7.0] * 8, measured=False))
        assert v.code == "learning"
        assert v.nights == 0
        assert v.suggested_kwh is None


class TestTheNightsShare:
    def test_a_kept_promise_is_named_as_one(self):
        s = NightSummary(night="2026-08-01", predicted_share=0.70,
                         solar_kwh=20.0, exported_kwh=5.5, samples=50)
        assert review_share([s])["code"] == "sc_met"

    def test_missing_the_predicted_share_is_named(self):
        s = NightSummary(night="2026-08-01", predicted_share=0.80,
                         solar_kwh=20.0, exported_kwh=10.0, samples=50)
        r = review_share([s])
        assert r["code"] == "sc_missed"
        assert r["actual_share"] == pytest.approx(0.5)
        assert r["predicted_share"] == pytest.approx(0.8)

    def test_beating_it_is_named_too(self):
        s = NightSummary(night="2026-08-01", predicted_share=0.50,
                         solar_kwh=20.0, exported_kwh=2.0, samples=50)
        assert review_share([s])["code"] == "sc_beat"

    def test_a_sunless_night_has_no_share_to_report(self):
        """0 kWh of solar means the question does not apply. Reporting 0%
        would read as a failure of the plan on a night the sky was shut."""
        s = NightSummary(night="2026-08-01", predicted_share=0.8,
                         solar_kwh=0.0, exported_kwh=0.0, samples=50)
        assert review_share([s]) is None

    def test_a_night_the_plan_made_no_claim_about_has_nothing_to_compare(self):
        s = NightSummary(night="2026-08-01", predicted_share=None,
                         solar_kwh=20.0, exported_kwh=4.0, samples=50)
        assert review_share([s]) is None

    def test_the_newest_night_with_sun_is_the_one_reported(self):
        old = NightSummary(night="2026-08-01", predicted_share=0.8,
                           solar_kwh=20.0, exported_kwh=10.0, samples=50)
        dark = NightSummary(night="2026-08-02", predicted_share=0.8,
                            solar_kwh=0.0, samples=50)
        assert review_share([old, dark])["night"] == "2026-08-01"

    def test_no_history_is_no_line(self):
        assert review_share([]) is None


class TestThePayload:
    def test_it_groups_a_flat_record_list_by_demand(self):
        recs = _nights([5.0, 6.0, 6.5, 7.0, 8.0])
        recs += _nights([1.0, 1.0], did="load:pool", kind="load", asked=2.0)
        out = review_night(recs)
        ids = [r["demand_id"] for r in out["demands"]]
        assert ids == ["ev:keba", "load:pool"]

    def test_it_carries_the_share_line_when_there_is_one(self):
        out = review_night(
            _nights([7.0]),
            summaries=[NightSummary(night="2026-08-01", predicted_share=0.8,
                                    solar_kwh=20.0, exported_kwh=10.0,
                                    samples=9)])
        assert out["self_consumption"]["code"] == "sc_missed"

    def test_an_empty_record_is_an_empty_payload_not_a_crash(self):
        assert review_night([]) == {"demands": []}

    def test_the_payload_is_small_enough_to_ride_on_an_entity(self):
        """The plan attributes already live under a 15 KiB recorder budget
        (#638). A review that pushed them over would take the whole plan's
        history down with it."""
        recs = []
        for n in range(8):
            recs += _nights([5.0, 6.0, 6.5, 7.0, 8.0],
                            did=f"load:device_{n}", kind="load")
        out = review_night(recs)
        assert len(json.dumps(out)) < 4000

    def test_a_verdict_serializes_flat(self):
        v = review_demand("ev:keba", _nights([5.0, 6.0, 6.5, 7.0, 8.0]))
        assert isinstance(v, DemandVerdict)
        d = v.as_dict()
        assert d["code"] == "took_less"
        assert set(d) >= {"demand_id", "kind", "code", "asked_kwh",
                          "last_kwh", "suggested_kwh", "nights"}


class TestTheCoordinatorKeepsItAvailable:
    def test_sealing_a_night_refreshes_the_review(self):
        """The verdict is recomputed when a night CLOSES, not on every
        cycle: the inputs cannot change in between, and the plan sensor is
        read far more often than nights end."""
        from datetime import datetime, timedelta, timezone
        from types import MethodType, SimpleNamespace
        from custom_components.solar_energy_management.coordinator \
            .demand_outcome import DemandOutcomeRecorder
        from custom_components.solar_energy_management.coordinator \
            .coordinator import SEMCoordinator

        rec = DemandOutcomeRecorder()
        t0 = datetime(2026, 8, 1, 23, 0, tzinfo=timezone.utc)
        rec.open_night("2026-08-01", [{"id": "ev:keba", "kind": "ev",
                                       "needed_kwh": 10.0,
                                       "planned_kwh": 10.0,
                                       "status": "fits"}])
        for i in range(4):
            rec.observe(t0 + timedelta(minutes=15 * i), "ev:keba",
                        power_w=4000.0, measured=True, in_block=True,
                        covered=True)

        fake = SimpleNamespace(_demand_outcomes=rec, _storage=None,
                               _demand_review=None)
        for name in ("_persist_demand_outcomes", "_refresh_demand_review"):
            setattr(fake, name,
                    MethodType(getattr(SEMCoordinator, name), fake))
        SEMCoordinator._seal_demand_outcomes(fake)

        assert fake._demand_review is not None
        assert fake._demand_review["demands"][0]["demand_id"] == "ev:keba"

    def test_the_review_is_published_on_its_own_key(self):
        """It must outlive the plan. ``energy_plan`` empties out when there
        is nothing to plan — which is precisely the daytime hours in which a
        user reads last night's verdict."""
        import inspect
        from custom_components.solar_energy_management.coordinator \
            .coordinator import SEMCoordinator
        src = inspect.getsource(SEMCoordinator._async_update_data)
        assert '"energy_plan_review"' in src


class TestItOnlySuggests:
    def test_the_plan_build_never_reads_the_review(self):
        import inspect
        from custom_components.solar_energy_management.coordinator \
            .coordinator import SEMCoordinator
        src = inspect.getsource(SEMCoordinator._shadow_overnight_plan)
        assert "review_night" not in src and "review_demand" not in src


class TestTheUserCanReadIt:
    """Every code this module can emit must reach the screen as a sentence in
    the user's own language — otherwise the recommender ships raw jargon."""

    CODES = ["learning", "on_target", "took_less", "at_ceiling",
             "sc_met", "sc_missed", "sc_beat"]

    def test_every_code_has_a_key_in_every_language(self):
        data = json.loads((REPO / "dashboard" / "translations.json").read_text(
            encoding="utf-8"))
        missing = [(lang, f"overnight_review_{c}")
                   for lang in data for c in self.CODES
                   if f"overnight_review_{c}" not in data[lang]]
        assert not missing, f"untranslated review verdicts: {missing}"

    def test_the_codes_the_module_emits_are_exactly_the_translated_set(self):
        """The inverse guard. A code added to the module without a key would
        render as ``overnight_review_whatever`` on somebody's dashboard."""
        src = (REPO / "coordinator" / "demand_review.py").read_text(
            encoding="utf-8")
        emitted = set(re.findall(r'CODE_[A-Z_]+\s*=\s*"([a-z_]+)"', src))
        assert emitted == set(self.CODES), (
            f"module emits {sorted(emitted)}, translations cover "
            f"{sorted(self.CODES)}")

    def test_the_generated_bundle_carries_them(self):
        js = (REPO / "dashboard" / "card" / "sem-localize.js").read_text(
            encoding="utf-8")
        for c in self.CODES:
            assert f'"overnight_review_{c}"' in js, (
                f"overnight_review_{c} missing from sem-localize.js — run "
                f"scripts/regenerate_localize.py")

    def test_the_card_renders_the_review(self):
        card = (REPO / "dashboard" / "card" / "src" / "cards"
                / "sem-energy-plan-card.js").read_text(encoding="utf-8")
        assert "review" in card
        assert "overnight_review_" in card, (
            "the card must translate the verdict codes, not print them")

    def test_the_sensor_publishes_it_beside_the_plan(self):
        """It must survive the day. The plan attributes empty out when there
        is no plan tonight — which is exactly when a user reads the morning
        verdict — so the review rides on its own key."""
        src = (REPO / "sensor.py").read_text(encoding="utf-8")
        assert "energy_plan_review" in src
