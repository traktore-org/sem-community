"""#778 — tomorrow's committed demand is the FLEET's, not one global key.

Found by mutation testing during the pre-2.1-beta audit (30.08.2026), and
the mutation is the point: replacing the budget's ``committed_demand_kwh``
argument with a hardcoded ``0.0`` left all 408 #778/#873 tests GREEN,
including ``test_778_assembly.py`` — the file written that same day
specifically to execute this assembly. Its fixture never populated
``ev_chargers``, so this parameter had never been exercised by any test in
the suite.

The defect: ``refill_estimate``'s docstring is explicit that the refill must
be counted AFTER tomorrow's claims, and Guido pinned it before the arc was
built — *"will it refill" is not a scalar forecast question: the morning
solar is also claimed by tomorrow's packed EV blocks and loads.* The
coordinator already computes exactly that in ``_compose_tomorrow_preview``,
summing EVERY charger's own ``daily_ev_target`` (falling back to the global
only when a charger has none). The budget read the single global key
instead.

Consequence on any multi-charger install: committed demand is undercounted,
so the surplus that survives it is overstated, so ``expected_refill`` is
overstated, so ``battery_spendable_kwh`` is overstated — a number rendered
on three cards and read by ``decide.py``'s battery→EV assist, which that
file's own comment calls "the first non-inert behaviour in the arc".

Overstating the refill spends energy tomorrow's sun will not put back. This
fails in the dangerous direction.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.refill_estimate import (
    committed_ev_demand_kwh,
)


class TestEveryChargerCounts:
    def test_two_chargers_commit_the_sum_of_their_targets(self):
        cfg = {"ev_chargers": [
            {"id": "keba_1", "daily_ev_target": 10.0},
            {"id": "zaptec_2", "daily_ev_target": 6.0},
        ]}
        assert committed_ev_demand_kwh(cfg) == pytest.approx(16.0), (
            "a two-car household commits both cars' energy; reading one "
            "global key undercounts it and overstates what tomorrow refills"
        )

    def test_a_charger_without_its_own_target_falls_back_to_the_global(self):
        """Same precedence as _compose_tomorrow_preview, so the two readers
        of this one fact cannot disagree."""
        cfg = {"daily_ev_target": 8.0, "ev_chargers": [
            {"id": "keba_1", "daily_ev_target": 10.0},
            {"id": "zaptec_2"},
        ]}
        assert committed_ev_demand_kwh(cfg) == pytest.approx(18.0)

    def test_a_single_charger_install_is_unchanged(self):
        """The install shape that hid this: one charger, so the global key
        and the fleet sum agree and the bug is invisible."""
        assert committed_ev_demand_kwh(
            {"daily_ev_target": 10.0,
             "ev_chargers": [{"id": "keba_1"}]}) == pytest.approx(10.0)

    def test_no_chargers_configured_falls_back_to_the_global(self):
        """A legacy single-charger install has no ev_chargers list at all."""
        assert committed_ev_demand_kwh(
            {"daily_ev_target": 7.0}) == pytest.approx(7.0)

    def test_nothing_configured_commits_nothing(self):
        assert committed_ev_demand_kwh({}) == 0.0
        assert committed_ev_demand_kwh(None) == 0.0

    def test_a_negligible_target_is_not_a_claim(self):
        """Mirrors the preview's own 0.05 kWh floor — a rounding crumb is
        not a booked charge."""
        assert committed_ev_demand_kwh(
            {"ev_chargers": [{"id": "a", "daily_ev_target": 0.01}]}) == 0.0

    @pytest.mark.parametrize("junk", ["", "abc", None, {}])
    def test_unreadable_targets_do_not_break_the_budget(self, junk):
        cfg = {"ev_chargers": [
            {"id": "good", "daily_ev_target": 5.0},
            {"id": "bad", "daily_ev_target": junk},
        ]}
        assert committed_ev_demand_kwh(cfg) == pytest.approx(5.0)


class TestTheBudgetUsesIt:
    def test_the_assembly_passes_the_fleet_sum(self):
        """The wiring the mutation proved was untested: run the real
        assembly with two chargers and confirm the committed demand that
        reaches the refill estimate is the SUM."""
        from .test_778_assembly import evidence

        # The forecast is chosen so the committed term is actually VISIBLE,
        # and that window is narrow enough to be worth stating:
        #   too big  -> the refill is capped by the pack's dawn headroom and
        #               both answers are 6.5, so the test passes whatever the
        #               wiring does — the same blind spot the mutation used;
        #   too small -> the surplus floors at zero for one car as well as
        #               two, and both answers are 0.0.
        # At 25 kWh one car leaves 6.5 kWh of refill and two leave 3.0.
        kw = dict(soc=100.0, forecast_tomorrow=25.0)
        one = evidence(**kw, ev_chargers=[
            {"id": "keba_1", "daily_ev_target": 4.0}])
        two = evidence(**kw, ev_chargers=[
            {"id": "keba_1", "daily_ev_target": 4.0},
            {"id": "zaptec_2", "daily_ev_target": 4.0}])

        assert one["battery_expected_refill_kwh"] == pytest.approx(6.5)
        assert two["battery_expected_refill_kwh"] == pytest.approx(3.0)
        assert two["battery_expected_refill_kwh"] < one["battery_expected_refill_kwh"], (
            "a second car booked for tomorrow claims more of tomorrow's sun, "
            "so LESS of it is left to refill the pack — if these are equal, "
            "the second charger's demand never reached the budget"
        )
