"""The conservation check must compare like with like.

Found by review, and it is the worst kind of bug: one that fails SAFE and so
disables the feature silently rather than breaking anything loudly.

The first version compared the tracker's cumulative night flows — accumulated
from dusk, with no midnight reset — against ``daily_battery_discharge``, which
IS keyed on ``now.date()`` and resets at midnight
(``energy_calculator.py``: "Midnight-based reset — matches HA Energy
Dashboard"). Every real night spans midnight. So from 00:00 the counter
restarts near zero while the tracker keeps climbing, the two diverge by
however much discharged before midnight, and the check trips.

``flows_balanced`` latches for the whole record, and it gates ``trainable`` —
which gates ``expected_overnight_need`` and ``measured_capacity``. So a check
meant to reject the occasional impossible night would instead have rejected
almost EVERY night, and #778 would have sat at "learning" forever on real
hardware with nothing explaining why.

The fix is to stop comparing accumulators over different windows and compare
POWER per sample, which has no window at all. Two consequences worth keeping:

* it needs a duration tolerance, because two sensors read microseconds apart
  disagree constantly and one bad sample must not condemn a ten-hour night;
* it is strictly more sensitive than the old check when it does fire, because
  a sustained impossible flow shows up in every sample rather than being
  averaged into a daily total.
"""

import pytest

from custom_components.solar_energy_management.coordinator.battery_night import (
    BatteryNightTracker,
    Sample,
)
from custom_components.solar_energy_management.coordinator.flow_invariant import (
    VIOLATION_TOLERANCE_S,
    flows_balance,
)


def _s(**kw):
    base = dict(battery_to_home_w=0.0, battery_to_ev_w=0.0, battery_to_grid_w=0.0,
                grid_to_home_w=0.0, soc=None, soc_available=True, measured=True)
    base.update(kw)
    return Sample(**base)


def _tracker():
    return BatteryNightTracker(reserve_soc=10.0, capacity_kwh=15.0)


class TestThePerSampleInvariant:
    def test_flows_within_the_discharge_balance(self):
        assert flows_balance(discharge_w=3000.0, to_home=2000.0, to_ev=500.0,
                             to_grid=100.0) is True

    def test_flows_exceeding_the_discharge_do_not(self):
        assert flows_balance(discharge_w=1000.0, to_home=3000.0, to_ev=0.0,
                             to_grid=0.0) is False

    def test_a_charging_battery_attributes_no_outflow(self):
        """Discharge power is zero or negative while charging; any claimed
        outflow then is impossible."""
        assert flows_balance(discharge_w=0.0, to_home=2000.0, to_ev=0.0,
                             to_grid=0.0) is False

    def test_a_charging_battery_with_no_outflow_is_fine(self):
        assert flows_balance(discharge_w=0.0, to_home=0.0, to_ev=0.0,
                             to_grid=0.0) is True

    def test_measurement_noise_is_tolerated(self):
        assert flows_balance(discharge_w=1000.0, to_home=1100.0, to_ev=0.0,
                             to_grid=0.0) is True

    def test_an_unknown_discharge_is_unverifiable_not_guilty(self):
        assert flows_balance(discharge_w=None, to_home=5000.0, to_ev=0.0,
                             to_grid=0.0) is True


class TestANightSpanningMidnight:
    """The regression that motivated the fix.

    Ten hours of steady, entirely legitimate discharge. Under the old
    cumulative comparison the daily counter reset at midnight and the night
    was condemned; the per-sample check cannot see midnight at all.
    """

    def _run_night(self, hours=10.0, power=500.0, step=30.0):
        tr = _tracker()
        tr.start("2026-08-23", outdoor_temp_c=None)
        t = 0.0
        ticks = int(hours * 3600 / step)
        for i in range(ticks):
            t += step
            tr.tick(t, True, _s(battery_to_home_w=power, soc=90.0 - i * 0.01,
                                battery_discharge_w=power))
        return tr, t

    def test_a_legitimate_night_stays_balanced(self):
        tr, _ = self._run_night()
        rec = tr._record()
        assert rec["flows_balanced"] is True, (
            "a steady, physically possible night was rejected — the check is "
            "comparing quantities over different windows again")
        assert rec["trainable"] is True

    def test_a_genuinely_impossible_night_is_still_rejected(self):
        """The check must not have been softened into uselessness: sustained
        outflow above the discharge is still caught."""
        tr = _tracker()
        tr.start("2026-08-23", outdoor_temp_c=None)
        t = 0.0
        for _ in range(int(VIOLATION_TOLERANCE_S / 30) + 40):
            t += 30.0
            tr.tick(t, True, _s(battery_to_home_w=3000.0, soc=90.0,
                                battery_discharge_w=800.0))
        assert tr._record()["flows_balanced"] is False

    def test_one_bad_sample_does_not_condemn_a_night(self):
        """Two sensors read microseconds apart disagree constantly. A night is
        ten hours long; a single sample is thirty seconds of it."""
        tr, t = self._run_night(hours=1.0)
        t += 30.0
        tr.tick(t, True, _s(battery_to_home_w=9000.0, soc=88.0,
                            battery_discharge_w=100.0))
        assert tr._record()["flows_balanced"] is True

    def test_the_violation_duration_is_recorded(self):
        tr, t = self._run_night(hours=0.5)
        t += 30.0
        tr.tick(t, True, _s(battery_to_home_w=9000.0, soc=88.0,
                            battery_discharge_w=100.0))
        assert tr._record()["flow_violation_s"] > 0


class TestNoDischargeSignalAtAll:
    def test_an_install_without_the_signal_is_not_penalised(self):
        """Hardware that publishes no battery power must not lose every night
        — unverifiable is not the same as violated."""
        tr = _tracker()
        tr.start("2026-08-23", outdoor_temp_c=None)
        t = 0.0
        for _ in range(60):
            t += 30.0
            tr.tick(t, True, _s(battery_to_home_w=500.0, soc=90.0))
        rec = tr._record()
        assert rec["flows_balanced"] is True
        assert rec["trainable"] is True
