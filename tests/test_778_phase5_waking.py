"""#778 phase 5 — the budget reaches the sinks, and only when invited.

This is the first behaviour in the arc that is not inert, so the tests that
matter most are the ones proving it stays asleep. Three independent gates must
all agree before a single watt moves that would not have moved before:

    forecast_spending_enabled   master switch, default OFF
    may_assist_ev               per-battery permission
    battery_spendable_kwh > 0   measured evidence, not a guess

Any one of them missing and the old behaviour is exactly preserved — the
#537 surplus threshold decides, as it always did.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.decide import (
    battery_assist_budget_w,
)


class _Fleet:
    def __init__(self, **kw):
        self.battery_soc = 90.0
        self.auto_start_soc = 90.0
        self.buffer_soc = 40.0
        self.priority_soc = 20.0
        self.battery_assist_min_surplus_w = 1200.0
        self.battery_may_assist_ev = True
        self.battery_spendable_kwh = 0.0
        self.forecast_spending_enabled = False
        self.battery_assist_max_power_w = 5000.0
        self.battery_assist_max_power = 5000.0
        self.__dict__.update(kw)


class _View:
    def __init__(self, fleet, surplus_w=0.0):
        self.fleet = fleet
        self._surplus = surplus_w


@pytest.fixture(autouse=True)
def _stub_surplus(monkeypatch):
    """Isolate the gate under test from the surplus calculation itself."""
    import custom_components.solar_energy_management.coordinator.decide as d
    monkeypatch.setattr(d, "self_consumption_surplus_w",
                        lambda view: getattr(view, "_surplus", 0.0))
    yield


@pytest.mark.unit
class TestItStaysAsleepByDefault:

    def test_no_surplus_and_no_switch_means_no_assist(self):
        """Today's behaviour, unchanged: a sunless evening never drains the
        pack into the car."""
        v = _View(_Fleet(), surplus_w=0.0)
        assert battery_assist_budget_w(v) == 0.0

    def test_the_budget_alone_is_not_enough(self):
        """Evidence without the master switch changes nothing."""
        v = _View(_Fleet(battery_spendable_kwh=12.0), surplus_w=0.0)
        assert battery_assist_budget_w(v) == 0.0

    def test_the_switch_alone_is_not_enough(self):
        """The switch without evidence must not invent permission to spend."""
        v = _View(_Fleet(forecast_spending_enabled=True), surplus_w=0.0)
        assert battery_assist_budget_w(v) == 0.0

    def test_permission_denied_beats_both(self):
        """'The house may use my battery, the car may not' — the control that
        did not exist before this arc."""
        v = _View(_Fleet(forecast_spending_enabled=True,
                         battery_spendable_kwh=12.0,
                         battery_may_assist_ev=False), surplus_w=0.0)
        assert battery_assist_budget_w(v) == 0.0


@pytest.mark.unit
class TestWithAllThreeItActs:

    def test_the_evening_case_finally_works(self):
        """The maintainer's PROD night: no surplus at 20:00, a full pack, and a
        forecast that refills it tomorrow. Previously impossible by
        construction, because the only question asked was about *now*."""
        v = _View(_Fleet(forecast_spending_enabled=True,
                         battery_spendable_kwh=12.0), surplus_w=0.0)
        assert battery_assist_budget_w(v) > 0.0

    def test_daytime_surplus_still_works_untouched(self):
        """The old path must not regress: real surplus assists as it always
        did, with no switch and no budget."""
        v = _View(_Fleet(), surplus_w=3000.0)
        assert battery_assist_budget_w(v) > 0.0

    def test_a_low_soc_pack_is_still_protected(self):
        """Zone gating is upstream of all of this and still governs."""
        v = _View(_Fleet(battery_soc=25.0, forecast_spending_enabled=True,
                         battery_spendable_kwh=12.0), surplus_w=0.0)
        assert battery_assist_budget_w(v) == 0.0
