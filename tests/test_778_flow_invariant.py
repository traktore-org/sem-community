"""#778 — a night whose energy books do not balance is not evidence.

Found on .175 while backfilling: SEM reported the battery discharging 4.06 kWh
that day and simultaneously reported 13.96 kWh flowing OUT of it (9.39 home +
0.19 EV + 4.38 grid). 3.4x more energy leaving the battery than left the
battery. PROD holds the invariant on the same code (3.04 <= 4.04), so it is a
rig artifact — but nothing in SEM noticed either way, and #778 integrates
exactly that inflated flow into ``drain_kwh``.

The consequence is quiet and bad: an inflated drain makes the overnight-need
envelope too large, the budget stays at zero forever, and the card says
"holding" — a sentence that sounds like a considered decision. The user is told
their house needs 13 kWh a night when it needs 5.

So the invariant becomes an evidence-quality gate, exactly like the gap
tolerance already is: a night that violated conservation is recorded, is
visible, and is NOT trainable. It is not silently repaired — clamping the
number would hide the cause, and the cause is a real misconfiguration
somewhere that deserves to be found.
"""

import pytest

from custom_components.solar_energy_management.coordinator.flow_invariant import (
    TOLERANCE_FRACTION,
    flows_balance,
)


class TestTheInvariant:
    def test_flows_within_the_discharge_balance(self):
        assert flows_balance(discharge_kwh=10.0, to_home=6.0, to_ev=2.0,
                             to_grid=1.0) is True

    def test_the_prod_reading_balances(self):
        """PROD, 23.08: discharged 4.04, flows 2.9 + 0.1 + 0.04."""
        assert flows_balance(discharge_kwh=4.04, to_home=2.9, to_ev=0.1,
                             to_grid=0.04) is True

    def test_the_rig_reading_does_not(self):
        """.175, same moment: discharged 4.06, flows 9.39 + 0.19 + 4.38."""
        assert flows_balance(discharge_kwh=4.06, to_home=9.39, to_ev=0.19,
                             to_grid=4.38) is False

    def test_a_small_overshoot_is_tolerated(self):
        """Sampling and rounding put the two sides a little apart; the gate is
        for the 3x case, not for measurement noise."""
        assert flows_balance(discharge_kwh=10.0, to_home=10.0 * (1 + TOLERANCE_FRACTION / 2),
                             to_ev=0.0, to_grid=0.0) is True

    def test_a_large_overshoot_is_not(self):
        assert flows_balance(discharge_kwh=10.0, to_home=13.0, to_ev=0.0,
                             to_grid=0.0) is False

    def test_flows_below_the_discharge_are_always_fine(self):
        """Losses, self-consumption in the inverter, unattributed flow — the
        invariant is one-sided by nature."""
        assert flows_balance(discharge_kwh=10.0, to_home=1.0, to_ev=0.0,
                             to_grid=0.0) is True


class TestItNeverRaises:
    """Evaluated once per night on live sensor values, some of which will be
    missing. A quality gate that throws would take the whole record with it."""

    @pytest.mark.parametrize("bad", [None, "x", float("nan")])
    def test_junk_discharge_is_unverifiable_not_false(self, bad):
        """Unknown is not the same as violated: without a discharge figure
        there is nothing to check, and failing every such night closed would
        discard evidence on installs that simply do not publish it."""
        assert flows_balance(discharge_kwh=bad, to_home=1.0, to_ev=0.0,
                             to_grid=0.0) is True

    @pytest.mark.parametrize("bad", [None, "x"])
    def test_junk_flows_count_as_zero(self, bad):
        assert flows_balance(discharge_kwh=10.0, to_home=bad, to_ev=0.0,
                             to_grid=0.0) is True

    def test_a_zero_discharge_night_is_not_flagged(self):
        """A battery that never discharged cannot violate anything, and 0/0
        must not become a division."""
        assert flows_balance(discharge_kwh=0.0, to_home=0.0, to_ev=0.0,
                             to_grid=0.0) is True


class TestTheNightRecordCarriesIt:
    def test_a_violating_night_is_recorded_but_not_trainable(self):
        from custom_components.solar_energy_management.coordinator.battery_night import (
            BatteryNightTracker, Sample,
        )
        tr = BatteryNightTracker(reserve_soc=10.0)
        tr.start("2026-08-21", outdoor_temp_c=None)
        t = 0.0
        # An hour of night at SEM's own cycle interval: 4 kW to home, while
        # the battery reports having discharged only 1 kWh in total. Ticks
        # must stay inside MAX_SAMPLE_GAP_S or the recorder treats each one as
        # a hole and integrates nothing.
        for _ in range(120):
            t += 30.0
            tr.tick(t, True, Sample(
                battery_to_home_w=4000.0, battery_to_ev_w=0.0,
                battery_to_grid_w=0.0, grid_to_home_w=0.0,
                soc=80.0, soc_available=True,
                battery_discharge_kwh=1.0,
            ))
        t += 30.0
        tr.tick(t, False, Sample(
            battery_to_home_w=0.0, battery_to_ev_w=0.0, battery_to_grid_w=0.0,
            grid_to_home_w=0.0, soc=60.0, soc_available=True,
            battery_discharge_kwh=1.0,
        ))
        rec = tr.sealed()[-1] if tr.sealed() else tr.current_record()
        assert rec is not None
        assert rec.get("flows_balanced") is False
        assert rec.get("trainable") is False, (
            "a night whose flows exceed the discharge was accepted as "
            "trainable evidence")
