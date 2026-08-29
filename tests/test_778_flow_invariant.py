"""#778 — a night whose energy books do not balance is not evidence.

The pack cannot send out more power than it is discharging. When the attributed
flows exceed it for long enough, the night is recorded, is visible, and is NOT
trainable — the same treatment a night with too large a sampling gap gets.

The comparison is per-sample POWER. It used to be cumulative energy against
``daily_battery_discharge``, and that was wrong in a way worth remembering: the
daily counter resets at midnight and a night does not, so from 00:00 the two
diverged and the check condemned ordinary nights. It failed SAFE — the feature
just never activated — which is exactly why it survived review of the code and
was only caught by reading the two windows against each other.
``test_800_flow_invariant_window.py`` owns that regression; this file owns the
contract.
"""

import pytest

from custom_components.solar_energy_management.coordinator.flow_invariant import (
    NOISE_FLOOR_W,
    TOLERANCE_FRACTION,
    VIOLATION_TOLERANCE_S,
    flows_balance,
)


class TestTheInvariant:
    def test_flows_within_the_discharge_balance(self):
        assert flows_balance(discharge_w=3000.0, to_home=2000.0, to_ev=500.0,
                             to_grid=100.0) is True

    def test_flows_below_the_discharge_are_always_fine(self):
        """Losses, inverter self-consumption, unattributed flow — the
        invariant is one-sided by nature."""
        assert flows_balance(discharge_w=3000.0, to_home=200.0) is True

    def test_a_small_overshoot_is_tolerated(self):
        assert flows_balance(
            discharge_w=1000.0,
            to_home=1000.0 * (1 + TOLERANCE_FRACTION / 2)) is True

    def test_a_large_overshoot_is_not(self):
        assert flows_balance(discharge_w=1000.0, to_home=3000.0) is False

    def test_the_three_sinks_are_summed(self):
        """Each alone fits; together they cannot. Checking only the largest
        would miss a fleet quietly over-attributing across all three."""
        assert flows_balance(discharge_w=1000.0, to_home=600.0, to_ev=600.0,
                             to_grid=600.0) is False


class TestItNeverRaises:
    """Evaluated every cycle on live sensor values, some of which are missing
    or junk. A quality gate that throws takes the whole record with it."""

    @pytest.mark.parametrize("bad", [None, "x", float("nan")])
    def test_junk_discharge_is_unverifiable_not_false(self, bad):
        """Unknown is not violated: without a discharge reading there is
        nothing to check, and failing every such night would discard evidence
        on hardware that simply reports less."""
        assert flows_balance(discharge_w=bad, to_home=5000.0) is True

    @pytest.mark.parametrize("bad", [None, "x"])
    def test_junk_flows_count_as_zero(self, bad):
        assert flows_balance(discharge_w=1000.0, to_home=bad) is True

    def test_an_idle_battery_is_not_policed(self):
        """A pack at rest reads a few watts either way on both sides. Below
        the noise floor there is no conservation question to answer."""
        assert flows_balance(discharge_w=0.0,
                             to_home=NOISE_FLOOR_W / 2) is True

    def test_outflow_while_charging_is_a_violation(self):
        """Above the noise floor it is real: the pack is taking energy IN and
        SEM claims kilowatts flowing OUT of it."""
        assert flows_balance(discharge_w=0.0, to_home=2000.0) is False


class TestTheNightRecordCarriesIt:
    def test_a_sustained_violation_makes_the_night_untrainable(self):
        from custom_components.solar_energy_management.coordinator.battery_night import (
            BatteryNightTracker, Sample,
        )
        tr = BatteryNightTracker(reserve_soc=10.0, capacity_kwh=15.0)
        tr.start("2026-08-21", outdoor_temp_c=None)
        t = 0.0
        # Long enough to spend the tolerance: 4 kW claimed out of a pack
        # discharging 1 kW.
        for _ in range(int(VIOLATION_TOLERANCE_S / 30) + 30):
            t += 30.0
            tr.tick(t, True, Sample(
                battery_to_home_w=4000.0, battery_to_ev_w=0.0,
                battery_to_grid_w=0.0, grid_to_home_w=0.0,
                soc=80.0, soc_available=True, battery_discharge_w=1000.0))
        rec = tr._record()
        assert rec["flows_balanced"] is False
        assert rec["flow_violation_s"] > VIOLATION_TOLERANCE_S
        assert rec["trainable"] is False, (
            "a night whose flows exceeded the pack's discharge was accepted "
            "as trainable evidence")

    def test_the_violation_is_visible_on_the_record(self):
        """Recorded, not merely rejected: a user or maintainer must be able to
        argue with the verdict, which needs the number behind it."""
        from custom_components.solar_energy_management.coordinator.battery_night import (
            BatteryNightTracker, Sample,
        )
        tr = BatteryNightTracker(reserve_soc=10.0, capacity_kwh=15.0)
        tr.start("2026-08-21", outdoor_temp_c=None)
        t = 0.0
        for _ in range(4):
            t += 30.0
            tr.tick(t, True, Sample(
                battery_to_home_w=4000.0, battery_to_ev_w=0.0,
                battery_to_grid_w=0.0, grid_to_home_w=0.0,
                soc=80.0, soc_available=True, battery_discharge_w=1000.0))
        rec = tr._record()
        assert rec["flow_violation_s"] > 0
        assert rec["flows_balanced"] is True, (
            "four samples is two minutes — well inside the tolerance a night "
            "needs against sensor skew")
