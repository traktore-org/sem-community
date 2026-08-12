"""#755 pillar 2 — self-consumption as an explicit objective.

Until now the planner optimised ONE thing: money, via slot price. Keeping
your own solar instead of exporting it was a side effect of pricing surplus
hours at zero — the sun won every comparison by fiat, and the plan could
neither say how much of tomorrow's solar it expected to keep nor be judged
on it afterwards.

Two things change here.

**The sun is not free — it costs the feed-in you forgo.** A surplus slot
prices at the export rate. In every normal install that still puts solar
below the cheapest grid hour, so the schedule barely moves; but the reason
it wins becomes an economic one that can LOSE. A night hour cheaper than
your feed-in tariff should win, and with a price of zero it never could.
With no export tariff configured the rate is 0 and the sun is free again —
which is also correct: exporting earns nothing, so keeping it costs nothing.

**The share is predicted, then audited.** The plan states the split it
expects (solar, kept, exported) and how much of the keeping is its own
doing. The night recorder integrates the same two quantities from real
power, so the morning comparison is like-for-like over the same window —
not a plan horizon measured against a calendar-day sensor.
"""

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.solar_energy_management.coordinator.day_ledger import (
    build_day_slots,
)
from custom_components.solar_energy_management.coordinator.overnight_planner import (
    Demand,
    LedgerSlot,
    build_night_ledger,
    pack_night,
)
from custom_components.solar_energy_management.coordinator.self_consumption import (
    SelfConsumption,
    predict_self_consumption,
)

from .test_638_shadow_mode import (  # noqa: F401 — fixtures come along
    _fake_self, _fake_load, _power, _scheduler, freeze_targets,
)


UTC = timezone.utc


def _t(h, m=0, day=12):
    return datetime(2026, 8, day, h, m, tzinfo=UTC)


def _open_summary(rec):
    """The night still in flight.

    The recorder's public ``night_summary()`` read had no production caller
    (only these tests) and went the way of every #653 orphan; the in-flight
    night is inspected here instead. Sealed nights ARE public —
    ``night_summaries()``, which is what the review reads."""
    return rec._summary


def _slots(**kw):
    kw.setdefault("start", _t(8))
    kw.setdefault("end", _t(18))
    kw.setdefault("day_kwh", 20.0)
    kw.setdefault("sunrise", _t(6))
    kw.setdefault("sunset", _t(20))
    kw.setdefault("home_w_at", lambda t: 500.0)
    kw.setdefault("price_at", lambda t: 0.30)
    kw.setdefault("level_cheap_at", lambda t: False)
    return build_day_slots(**kw)


class TestTheSunIsNotFree:
    def test_a_surplus_slot_prices_at_the_forgone_feed_in(self):
        """Consuming your own kWh costs you the feed-in you would have been
        paid for it. That is the whole economics of self-consumption, and
        pricing it at zero hid it."""
        noon = [s for s in _slots(export_rate=0.075) if s.start.hour == 12][0]
        assert noon.price == pytest.approx(0.075)
        assert noon.level_cheap is True, "still a preferred window"
        assert noon.cap_override_w is not None, "still finite"

    def test_without_a_feed_in_tariff_the_sun_really_is_free(self):
        """Nothing is forgone when export earns nothing."""
        noon = [s for s in _slots(export_rate=0.0) if s.start.hour == 12][0]
        assert noon.price == 0.0

    def test_the_slot_remembers_the_solar_it_was_built_from(self):
        """The surplus was derived from solar minus house and then the
        inputs were thrown away, so nothing downstream could ever say how
        much solar a slot carried. Both survive now."""
        noon = [s for s in _slots() if s.start.hour == 12][0]
        assert noon.solar_w > 2000.0
        assert noon.home_gross_w == pytest.approx(500.0)
        # the net-draw field keeps its old meaning: the house rides the sun
        assert noon.home_w == 0.0
        assert noon.cap_override_w == pytest.approx(
            noon.solar_w - noon.home_gross_w)

    def test_a_night_hour_cheaper_than_the_feed_in_beats_the_sun(self):
        """The point of an economic objective is that it can lose. Import at
        0.02 while export pays 0.075 and running at night is genuinely
        better — under the old fiat price of zero, noon always won."""
        night = LedgerSlot(start=_t(2), end=_t(3), price=0.02,
                           level_cheap=True, home_w=0.0)
        noon = LedgerSlot(start=_t(12), end=_t(13), price=0.075,
                          level_cheap=True, home_w=0.0,
                          cap_override_w=3000.0, solar_w=3500.0,
                          home_gross_w=500.0)
        ledger = build_night_ledger([night, noon], soc_kwh=0.0, floor_kwh=0.0,
                                    max_discharge_w=0.0, peak_limit_w=10000.0)
        plan = pack_night([Demand(id="heater", kind="load", energy_kwh=1.0,
                                  max_power_w=1000.0)],
                          ledger, peak_limit_w=10000.0)
        assert [a.start for a in plan.allocations] == [_t(2)]


class TestThePredictedShare:
    def test_solar_beyond_the_house_is_exported_when_nothing_is_planned(self):
        sc = predict_self_consumption(
            [LedgerSlot(start=_t(12), end=_t(13), price=0.075,
                        cap_override_w=2500.0, solar_w=3000.0,
                        home_gross_w=500.0)],
            blocks=[])
        assert sc.solar_kwh == pytest.approx(3.0)
        assert sc.self_consumed_kwh == pytest.approx(0.5)
        assert sc.exported_kwh == pytest.approx(2.5)
        assert sc.share == pytest.approx(1 / 6, abs=0.001)
        assert sc.from_plan_kwh == pytest.approx(0.0)

    def test_a_planned_block_in_the_sun_is_solar_the_plan_kept(self):
        """The number that answers 'what did planning buy me': solar that
        would have been exported and was consumed because a block sat
        there."""
        sc = predict_self_consumption(
            [LedgerSlot(start=_t(12), end=_t(13), price=0.075,
                        cap_override_w=2500.0, solar_w=3000.0,
                        home_gross_w=500.0)],
            blocks=[{"id": "ev:keba", "start": _t(12).isoformat(),
                     "end": _t(13).isoformat(), "power_w": 2000.0}])
        assert sc.self_consumed_kwh == pytest.approx(2.5)
        assert sc.exported_kwh == pytest.approx(0.5)
        assert sc.from_plan_kwh == pytest.approx(2.0)
        assert sc.share == pytest.approx(2.5 / 3.0, abs=0.001)

    def test_a_block_bigger_than_the_surplus_does_not_invent_solar(self):
        """Draw beyond the sun comes off the grid. It must not be counted as
        self-consumption — that would be the estimate-teaching-the-model bug
        in a new costume."""
        sc = predict_self_consumption(
            [LedgerSlot(start=_t(12), end=_t(13), price=0.075,
                        cap_override_w=2500.0, solar_w=3000.0,
                        home_gross_w=500.0)],
            blocks=[{"id": "ev:keba", "start": _t(12).isoformat(),
                     "end": _t(13).isoformat(), "power_w": 9000.0}])
        assert sc.self_consumed_kwh == pytest.approx(3.0)
        assert sc.exported_kwh == pytest.approx(0.0)
        assert sc.from_plan_kwh == pytest.approx(2.5)

    def test_a_night_block_keeps_no_solar(self):
        sc = predict_self_consumption(
            [LedgerSlot(start=_t(2), end=_t(3), price=0.10, home_w=400.0)],
            blocks=[{"id": "ev:keba", "start": _t(2).isoformat(),
                     "end": _t(3).isoformat(), "power_w": 4000.0}])
        assert sc.solar_kwh == pytest.approx(0.0)
        assert sc.from_plan_kwh == pytest.approx(0.0)
        assert sc.share is None, "no solar means no share, not zero percent"

    def test_a_block_overlapping_a_slot_partially_counts_pro_rata(self):
        sc = predict_self_consumption(
            [LedgerSlot(start=_t(12), end=_t(13), price=0.075,
                        cap_override_w=2500.0, solar_w=3000.0,
                        home_gross_w=500.0)],
            blocks=[{"id": "ev:keba", "start": _t(12, 30).isoformat(),
                     "end": _t(14).isoformat(), "power_w": 2000.0}])
        # only 30 min of the block lies in the sunny slot -> 1.0 kWh
        assert sc.from_plan_kwh == pytest.approx(1.0)

    def test_the_whole_day_rolls_up(self):
        sc = predict_self_consumption(_slots(export_rate=0.075), blocks=[])
        assert sc.solar_kwh > 10.0
        assert sc.exported_kwh > 0.0
        assert 0.0 < sc.share < 1.0


class TestTheCoordinatorStatesAndMeasuresIt:
    def test_the_day_slots_are_priced_at_the_configured_feed_in(self):
        """The objective is only real if the real build path carries it —
        a pure module nobody passes the rate to optimises nothing."""
        import inspect
        from custom_components.solar_energy_management.coordinator \
            .coordinator import SEMCoordinator

        src = inspect.getsource(SEMCoordinator._shadow_overnight_plan)
        assert "export_rate=" in src, (
            "build_day_slots must be given the feed-in rate, else every "
            "surplus slot prices at 0 and the sun wins by fiat again")
        assert "electricity_export_rate" in src

    def test_the_stamped_plan_states_the_share_it_expects(self, freeze_targets):
        """A prediction nobody wrote down cannot be wrong, which is the same
        as not being an objective."""
        from unittest.mock import MagicMock
        from custom_components.solar_energy_management.coordinator \
            .coordinator import SEMCoordinator

        fake = _fake_self(devices=[_fake_load()])
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(), energy=MagicMock(), power=_power())
        sc = fake._overnight_shadow_plan["self_consumption"]
        assert set(sc) == {"solar_kwh", "self_consumed_kwh", "exported_kwh",
                           "from_plan_kwh", "share"}

    def test_the_recorder_is_told_the_prediction_and_the_meter(self):
        """Predicted and actual must enter through the SAME door — the night
        record — or the morning compares a plan horizon against a
        calendar-day sensor and calls the difference an error."""
        import inspect
        from custom_components.solar_energy_management.coordinator \
            .coordinator import SEMCoordinator

        src = inspect.getsource(SEMCoordinator._record_demand_outcomes)
        assert "predicted_share" in src
        assert "observe_totals(" in src


class TestTheAuditIsLikeForLike:
    def test_the_recorder_integrates_solar_and_export_over_the_night(self):
        """The plan's horizon is not a calendar day. Comparing its predicted
        share against the daily self_consumption_rate sensor would compare
        two different windows and call the difference an error."""
        from custom_components.solar_energy_management.coordinator \
            .demand_outcome import DemandOutcomeRecorder

        rec = DemandOutcomeRecorder(max_gap_s=3600)
        rec.open_night("2026-08-12", demands=[], predicted_share=0.80)
        rec.observe_totals(_t(12), solar_w=4000.0, export_w=1000.0)
        rec.observe_totals(_t(13), solar_w=4000.0, export_w=1000.0)
        rec.observe_totals(_t(14), solar_w=0.0, export_w=0.0)
        summary = _open_summary(rec)
        assert summary.solar_kwh == pytest.approx(8.0, abs=0.01)
        assert summary.exported_kwh == pytest.approx(2.0, abs=0.01)
        assert summary.actual_share == pytest.approx(0.75, abs=0.01)
        assert summary.predicted_share == pytest.approx(0.80)

    def test_a_gap_is_not_integrated_into_the_share(self):
        """Same guard as the per-demand energy: a hole is a hole. Inventing
        solar across a restart would show up as a plan that missed its
        target for no reason."""
        from custom_components.solar_energy_management.coordinator \
            .demand_outcome import DemandOutcomeRecorder

        rec = DemandOutcomeRecorder()          # shipped default guard
        rec.open_night("2026-08-12", demands=[])
        rec.observe_totals(_t(12), solar_w=4000.0, export_w=1000.0)
        rec.observe_totals(_t(15), solar_w=4000.0, export_w=1000.0)
        assert _open_summary(rec).solar_kwh == pytest.approx(0.0, abs=0.01)

    def test_the_summary_survives_a_reboot(self):
        from custom_components.solar_energy_management.coordinator \
            .demand_outcome import DemandOutcomeRecorder

        rec = DemandOutcomeRecorder(max_gap_s=3600)
        rec.open_night("2026-08-12", demands=[], predicted_share=0.8)
        rec.observe_totals(_t(12), solar_w=4000.0, export_w=1000.0)
        rec.observe_totals(_t(13), solar_w=4000.0, export_w=1000.0)

        revived = DemandOutcomeRecorder(max_gap_s=3600)
        revived.restore_state(rec.get_state())
        revived.observe_totals(_t(14), solar_w=0.0, export_w=0.0)
        assert _open_summary(revived).solar_kwh == pytest.approx(8.0, abs=0.01)
        assert _open_summary(revived).predicted_share == pytest.approx(0.8)

    def test_closing_the_night_files_the_summary_in_history(self):
        from custom_components.solar_energy_management.coordinator \
            .demand_outcome import DemandOutcomeRecorder

        rec = DemandOutcomeRecorder(max_gap_s=3600)
        rec.open_night("2026-08-12", demands=[], predicted_share=0.9)
        rec.observe_totals(_t(12), solar_w=4000.0, export_w=0.0)
        rec.observe_totals(_t(13), solar_w=4000.0, export_w=0.0)
        rec.close_night()
        past = rec.night_summaries()
        assert [s.night for s in past] == ["2026-08-12"]
        assert past[0].actual_share == pytest.approx(1.0)
        assert past[0].predicted_share == pytest.approx(0.9)

    def test_a_night_with_no_solar_has_no_share_to_judge(self):
        """Midwinter, or a plan stamped at 23:00 that ends before sunrise.
        Reporting 0 % kept would read as a failure; there was nothing to
        keep."""
        from custom_components.solar_energy_management.coordinator \
            .demand_outcome import DemandOutcomeRecorder

        rec = DemandOutcomeRecorder(max_gap_s=3600)
        rec.open_night("2026-08-12", demands=[])
        rec.observe_totals(_t(2), solar_w=0.0, export_w=0.0)
        rec.observe_totals(_t(3), solar_w=0.0, export_w=0.0)
        assert _open_summary(rec).actual_share is None
