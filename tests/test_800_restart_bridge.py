"""A restart must not cost the night — bridge the hole with the pack's own SOC.

Guido, 23.08: *"that is not a good scenario, people are rebooting the system,
it has to be more reliable."* He is right, and the failure was worse than a
lost night:

* a restart makes the tracker miss every sample in between, so the energy that
  flowed during the hole is simply **not counted**. The drain comes out too
  SMALL, the overnight-need envelope built from it comes out too small, and the
  budget under-reserves — the unsafe direction, silently;
* past ``GAP_TOLERANCE_S`` the night is refused entirely. Home Assistant
  updates, add-on installs and power cuts are ordinary events; an install that
  restarts most evenings would never reach five usable nights and would sit at
  "learning" forever with nothing explaining why.

The fix is to notice that a restart is a hole in the SAMPLING, not in the
physics. The battery's state-of-charge is a counter that kept running the whole
time, so the pack itself can say what happened while SEM was not watching:

    bridged_kwh = capacity x (soc_before - soc_after) / 100

Attributing all of it to the house slightly OVER-states the drain when some of
it went to the car or the grid. That is deliberate: a larger drain means a
larger reserve and less spending, and of the two ways to be wrong here that is
the one that cannot strand anybody.
"""

import pytest

from custom_components.solar_energy_management.coordinator.battery_night import (
    GAP_TOLERANCE_S,
    MAX_SAMPLE_GAP_S,
    BatteryNightTracker,
    Sample,
)

CAP = 15.0


def _s(**kw):
    base = dict(battery_to_home_w=0.0, battery_to_ev_w=0.0, battery_to_grid_w=0.0,
                grid_to_home_w=0.0, soc=None, soc_available=True, measured=True)
    base.update(kw)
    return Sample(**base)


def _tracker():
    return BatteryNightTracker(reserve_soc=10.0, capacity_kwh=CAP)


def _run(tr, t0, seconds, *, power, soc, step=30.0):
    """Tick a stretch of night at a steady draw."""
    t = t0
    end = t0 + seconds
    while t < end:
        t += step
        tr.tick(t, True, _s(battery_to_home_w=power, soc=soc))
    return t


class TestTheBridgeMeasuresTheHole:
    def test_a_restart_gap_is_bridged_from_soc(self):
        """Ten minutes of outage across which the pack fell 8 points. On a
        15 kWh pack that is 1.2 kWh, and it must appear in the drain."""
        tr = _tracker()
        tr.start("2026-08-23", outdoor_temp_c=None)
        t = _run(tr, 0.0, 300.0, power=2000.0, soc=80.0)
        before = tr._record()["drain_kwh"]

        # the restart: one tick, 600 s later, SOC 8 points lower
        t += 600.0
        tr.tick(t, True, _s(battery_to_home_w=2000.0, soc=72.0))

        after = tr._record()["drain_kwh"]
        assert after - before == pytest.approx(CAP * 8.0 / 100.0, abs=0.05), (
            "the energy that left the pack during the outage was not counted")

    def test_the_bridge_is_recorded_so_it_can_be_audited(self):
        tr = _tracker()
        tr.start("2026-08-23", outdoor_temp_c=None)
        t = _run(tr, 0.0, 300.0, power=2000.0, soc=80.0)
        t += 600.0
        tr.tick(t, True, _s(battery_to_home_w=2000.0, soc=72.0))
        rec = tr._record()
        assert rec["bridged_kwh"] == pytest.approx(1.2, abs=0.05)
        assert rec["bridged_s"] >= 600.0

    def test_a_bridged_night_stays_trainable(self):
        """The reliability point. A restart used to spend the night's
        trainability; now the pack itself covers the hole, so it does not."""
        tr = _tracker()
        tr.start("2026-08-23", outdoor_temp_c=None)
        t = _run(tr, 0.0, 300.0, power=2000.0, soc=80.0)
        t += GAP_TOLERANCE_S * 3          # well past the old tolerance
        tr.tick(t, True, _s(battery_to_home_w=2000.0, soc=70.0))
        t = _run(tr, t, 300.0, power=2000.0, soc=70.0)
        t += 30.0
        tr.tick(t, False, _s(soc=70.0))       # morning: night -> day
        t += 30.0
        tr.tick(t, True, _s(soc=70.0))        # next night opening seals it
        rec = tr.sealed()[-1]
        assert rec["trainable"] is True, (
            "a restart still costs the night even though the pack said what "
            "happened")

    def test_a_charging_gap_does_not_subtract_from_the_drain(self):
        """SOC ROSE across the hole — the pack was charging. That is not
        negative house demand; it must not reduce what the night measured."""
        tr = _tracker()
        tr.start("2026-08-23", outdoor_temp_c=None)
        t = _run(tr, 0.0, 300.0, power=2000.0, soc=60.0)
        before = tr._record()["drain_kwh"]
        t += 600.0
        tr.tick(t, True, _s(battery_to_home_w=2000.0, soc=75.0))
        assert tr._record()["drain_kwh"] >= before


class TestWhenTheBridgeCannotBeTrusted:
    def test_no_soc_means_no_bridge_and_no_trainability(self):
        """Without SOC on both sides the hole is unmeasurable, and the night
        must go back to being refused rather than silently under-counted."""
        tr = _tracker()
        tr.start("2026-08-23", outdoor_temp_c=None)
        t = _run(tr, 0.0, 300.0, power=2000.0, soc=None)
        t += GAP_TOLERANCE_S * 3
        tr.tick(t, True, _s(battery_to_home_w=2000.0, soc=None, soc_available=False))
        t += 30.0
        tr.tick(t, False, _s(soc=None, soc_available=False))   # morning
        t += 30.0
        tr.tick(t, True, _s(soc=None, soc_available=False))    # seals it
        rec = tr.sealed()[-1]
        assert rec["trainable"] is False

    def test_no_capacity_means_no_bridge(self):
        """An install that never configured a capacity cannot convert SOC
        points into kWh. Guessing one would fabricate the very number the
        envelope is built from."""
        tr = BatteryNightTracker(reserve_soc=10.0, capacity_kwh=None)
        tr.start("2026-08-23", outdoor_temp_c=None)
        t = _run(tr, 0.0, 300.0, power=2000.0, soc=80.0)
        before = tr._record()["drain_kwh"]
        t += 600.0
        tr.tick(t, True, _s(battery_to_home_w=2000.0, soc=72.0))
        assert tr._record()["drain_kwh"] == pytest.approx(before, abs=1e-6)
        assert tr._record()["bridged_kwh"] == 0.0

    def test_an_implausible_jump_is_refused(self):
        """A pack cannot lose more than it holds. An SOC sensor that jumps
        from 80 to 5 across a reboot is more likely re-initialising than
        reporting a real 11 kWh discharge."""
        tr = _tracker()
        tr.start("2026-08-23", outdoor_temp_c=None)
        t = _run(tr, 0.0, 300.0, power=200.0, soc=80.0)
        before = tr._record()["drain_kwh"]
        t += 400.0                     # a real hole, with 75 SOC points claimed
        tr.tick(t, True, _s(battery_to_home_w=200.0, soc=5.0))
        rec = tr._record()
        assert rec["drain_kwh"] == pytest.approx(before, abs=1e-6)
        assert rec["trainable"] is False, (
            "an implausible SOC jump was accepted as measurement")


class TestOrdinaryOperationIsUnchanged:
    def test_a_night_without_gaps_measures_exactly_as_before(self):
        tr = _tracker()
        tr.start("2026-08-23", outdoor_temp_c=None)
        t = _run(tr, 0.0, 3600.0, power=2000.0, soc=80.0)
        rec = tr._record()
        assert rec["drain_kwh"] == pytest.approx(2.0, abs=0.05)
        assert rec["bridged_kwh"] == 0.0
        assert rec["bridged_s"] == 0.0

    def test_a_short_blip_still_uses_the_zero_order_hold(self):
        """Sub-gap blips keep their existing treatment — the bridge is for
        holes the sampler could not cover at all."""
        tr = _tracker()
        tr.start("2026-08-23", outdoor_temp_c=None)
        t = _run(tr, 0.0, 300.0, power=2000.0, soc=80.0)
        t += 60.0
        tr.tick(t, True, _s(battery_to_home_w=0.0, soc=80.0, measured=False))
        assert tr._record()["bridged_kwh"] == 0.0
        assert tr._record()["held_s"] > 0
