"""#708 — a SEM-commanded stop must not be read as "the car is full".

Live on beta.9 (Azlinon, 11.5 kW three-phase session): the vehicle SOC
sensor showed 100 % while the car was demonstrably not full, and the
next night's charge was skipped on that reading.

The mechanism is in ``EVTaperDetector.update``. The taper-to-full gate
fires on three ingredients:

    _declining_phase  and  ev_power < 50 W  and  session_peak > 3000 W

Every one of them was satisfied by Azlinon's session for an honest
reason — the BMS really had tapered, the peak really was 11.5 kW, and
the session energy was far above the floor. The last ingredient, "power
under 50 W for ~30 s", is where the inference breaks: **SEM had just
commanded the charger to stop.** A car that finishes and a charger SEM
switched off produce the identical reading, and the gate never asks
which happened.

The missing term is SEM's own hand. Every stop path in
``devices/base.py`` (``deactivate``, the session-stop path, and the
quota-hold branch) zeroes ``_current_setpoint``, so the detector is
already being handed the evidence — it just never looks. Once SEM has
withdrawn an offer it made, 0 W says nothing about the pack, and the
anchor must wait.

The distinction that matters, and why the guard is not simply
"setpoint must be > 0": a charger SEM does not control (observer mode
zeroes every setpoint; an uncontrolled box never had one) reads 0 A for
the whole session. There SEM withdrew nothing, the taper is the only
evidence there is, and the anchor must still work. The guard is
*withdrawal*, not *absence*.

Timing note for the genuine case: SEM holds an offer for
``ev_disable_delay_seconds`` (default 180 s) after the draw falls away,
and the full-confirm needs 3 cycles (~30 s). A car that finishes on its
own therefore anchors long before SEM's setpoint drops — the guard does
not race the feature it protects.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
    EVTaperDetector,
    FULL_POWER_THRESHOLD,
)


# Azlinon's car: a 77 kWh pack on an 11.5 kW three-phase box. The
# session-energy floor for this capacity is the 1.0 kWh cap, which a
# real 11.5 kW session clears in minutes.
CONFIG = {
    "ev_battery_capacity_kwh": 77,
    "ev_target_soc": 80,
    "ev_min_soc_threshold": 20,
}

BASE = datetime(2026, 8, 5, 21, 0, 0)

# The taper he actually had: a long plateau at three-phase full tilt,
# then the BMS walking the current down. Monotone, so the regression
# reads "declining" and the phase latches — exactly as designed.
PLATEAU_W = 11500.0
TAPER_STEPS_W = [9000.0, 7000.0, 5000.0, 3000.0, 1500.0]
SAMPLES_PER_STEP = 12  # 12 × 10 s = 2 min per step
OFFERED_A = 16.0


def _feed(detector, power_w, setpoint_a, count, cursor):
    """Feed ``count`` 10-second samples, returning the advanced cursor."""
    for _ in range(count):
        detector.update(power_w, setpoint_a, True, BASE + timedelta(seconds=cursor))
        cursor += 10
    return cursor


def _feed_real_taper(detector, setpoint_a=OFFERED_A):
    """A genuine 11.5 kW session tapering under BMS control.

    Leaves the detector with: peak 11.5 kW, ``_declining_phase`` latched,
    session energy far above the floor — i.e. every precondition of the
    full-anchor satisfied except the final low-power reading.
    """
    cursor = 0
    cursor = _feed(detector, PLATEAU_W, setpoint_a, 30, cursor)  # 5 min ≈ 0.96 kWh
    cursor = _feed(detector, PLATEAU_W, setpoint_a, 30, cursor)  # 10 min ≈ 1.9 kWh
    for step in TAPER_STEPS_W:
        cursor = _feed(detector, step, setpoint_a, SAMPLES_PER_STEP, cursor)
    return cursor


class TestASemCommandedStopIsNotEvidenceOfFull:
    """The live report: SEM stopped the charge, the detector read the
    silence it had itself created as the car reaching 100 %."""

    @staticmethod
    def _run() -> EVTaperDetector:
        det = EVTaperDetector(CONFIG)
        cursor = _feed_real_taper(det)
        # SEM stops: every stop path zeroes the setpoint, and the draw
        # follows within a cycle. Six samples — twice what the
        # three-sample confirm needs, and past the 3-cycle settling
        # window, so nothing incidental is doing the work here.
        _feed(det, 0.0, 0.0, 6, cursor)
        return det

    def test_it_does_not_anchor_full(self):
        det = self._run()
        assert det._full_detected is False, (
            "SEM commanded the stop; the 0 W that followed is SEM's own "
            "doing and says nothing about the pack (#708)."
        )

    def test_it_does_not_pin_soc_at_100(self):
        det = self._run()
        assert det._estimated_soc < 100.0, (
            "Virtual SOC pinned at 100 % from a SEM-commanded stop — this "
            "is the reading Azlinon saw, and what skipped the next night."
        )

    def test_it_records_no_full_timestamp(self):
        det = self._run()
        assert det._last_full_timestamp is None, (
            "A last-full anchor from a SEM-commanded stop outlives the "
            "session and biases every later energy-since-full estimate."
        )


class TestTheGenuineCaseStillWorks:
    """The guard adds one term. It must not cost the feature."""

    def test_a_car_finishing_under_a_live_offer_still_anchors(self):
        """SEM keeps offering 16 A; the car stops drawing because it is
        full. This is the detector's whole purpose."""
        det = EVTaperDetector(CONFIG)
        cursor = _feed_real_taper(det)
        _feed(det, 0.0, OFFERED_A, 6, cursor)
        assert det._full_detected is True
        assert det._estimated_soc == 100.0
        assert det._last_full_timestamp is not None

    def test_a_throttled_but_still_live_offer_still_anchors(self):
        """SEM narrowing the offer (cloud passing: 16 A → 6 A) is not a
        withdrawal. If the car then stops drawing at an offer it could
        have taken, it is full."""
        det = EVTaperDetector(CONFIG)
        cursor = _feed_real_taper(det)
        _feed(det, 0.0, 6.0, 6, cursor)
        assert det._full_detected is True

    def test_an_uncontrolled_charger_still_anchors(self):
        """Observer mode zeroes every setpoint, and a box SEM does not
        control never had one. SEM withdrew nothing here — the taper is
        the only evidence available and it must still count.

        This is the case that rules out the naive guard
        ``current_setpoint > 0``: it would silently delete taper-to-full
        for every observer-mode install.
        """
        det = EVTaperDetector(CONFIG)
        cursor = _feed_real_taper(det, setpoint_a=0.0)
        _feed(det, 0.0, 0.0, 6, cursor)
        assert det._full_detected is True, (
            "Observer mode / uncontrolled charger: setpoint is 0 A for the "
            "whole session, but SEM withdrew nothing. Absence of an offer "
            "is not withdrawal of one."
        )


class TestADeclineDoesNotOutliveTheRecovery:
    """``_declining_phase`` is a one-way latch: ``_analyze`` sets it on the
    first five-minute declining window and only ``reset_session`` clears
    it. So a car that dips and then returns to full tilt is still, in the
    detector's memory, "tapering" — and the next pause it takes reads as
    the end of the charge.

    The withdrawal guard above does not reach this: no SEM command is
    involved, the offer stays live throughout. It is the same false
    anchor arriving by the other door.

    The threshold is ``TAPER_RATIO_DETECTED`` read backwards. Below 70 %
    of session peak plus a declining trend is what *confirms* a taper, so
    at or above 70 % the charge is by definition not in one. Using the
    same number keeps one meaning of "still tapering" in the file.
    """

    def test_a_car_that_returns_to_full_tilt_is_not_tapering(self):
        det = EVTaperDetector(CONFIG)
        cursor = _feed_real_taper(det)                       # latch set
        # The car comes back: 10 min at three-phase full tilt, under the
        # same live 16 A offer. Nothing about this is a taper.
        cursor = _feed(det, PLATEAU_W, OFFERED_A, 60, cursor)
        # ...and then stops drawing on its own — a BMS balance step, cabin
        # preconditioning ending, any of the pauses a real car takes.
        _feed(det, 0.0, OFFERED_A, 6, cursor)
        assert det._full_detected is False, (
            "A pause after a return to 11.5 kW anchored 100 % on a decline "
            "that ended ten minutes earlier (#708)."
        )

    def test_a_real_taper_after_the_recovery_still_anchors(self):
        """Clearing the latch must cost nothing: the car tapers again, and
        this time it really is finishing."""
        det = EVTaperDetector(CONFIG)
        cursor = _feed_real_taper(det)
        cursor = _feed(det, PLATEAU_W, OFFERED_A, 60, cursor)
        for step in TAPER_STEPS_W:
            cursor = _feed(det, step, OFFERED_A, SAMPLES_PER_STEP, cursor)
        _feed(det, 0.0, OFFERED_A, 6, cursor)
        assert det._full_detected is True

    def test_the_clear_does_not_survive_a_still_declining_cycle(self):
        """The safety argument for clearing at 70 %: a genuine taper's
        first steps pass back down THROUGH that band (9 kW is 78 % of an
        11.5 kW peak), so the latch is cleared and immediately re-set by
        ``_analyze`` at the end of the same cycle, because the trend is
        still declining. Pinned rather than merely commented — the whole
        fix rests on this."""
        det = EVTaperDetector(CONFIG)
        cursor = _feed(det, PLATEAU_W, OFFERED_A, 60, 0)
        assert det._declining_phase is False, "a plateau is not a decline"
        _feed(det, 9000.0, OFFERED_A, SAMPLES_PER_STEP, cursor)
        assert det._declining_phase is True, (
            "9 kW is 78 % of an 11.5 kW peak — above the clear threshold — "
            "but the slope is still declining, so the phase must hold."
        )

    def test_a_wobble_inside_the_taper_band_is_still_a_taper(self):
        """Not every rise is a recovery. A BMS that lifts from 3 kW back to
        6 kW — 52 % of an 11.5 kW peak — never left the taper band, and the
        end of that charge is still an end of charge."""
        det = EVTaperDetector(CONFIG)
        cursor = _feed_real_taper(det)
        cursor = _feed(det, 6000.0, OFFERED_A, 18, cursor)
        _feed(det, 0.0, OFFERED_A, 6, cursor)
        assert det._full_detected is True


class TestTheGuardIsSessionScoped:
    """A withdrawal belongs to the session it happened in."""

    def test_a_later_offer_reopens_the_anchor(self):
        """SEM stops (blocked), then offers again — say the night window
        opens. The car draws, tapers, finishes under that live offer.
        The earlier withdrawal must not still be blocking."""
        det = EVTaperDetector(CONFIG)
        cursor = _feed_real_taper(det)
        cursor = _feed(det, 0.0, 0.0, 6, cursor)          # SEM stops
        assert det._full_detected is False
        cursor = _feed(det, PLATEAU_W, OFFERED_A, 30, cursor)  # SEM offers again
        for step in TAPER_STEPS_W:
            cursor = _feed(det, step, OFFERED_A, SAMPLES_PER_STEP, cursor)
        _feed(det, 0.0, OFFERED_A, 6, cursor)
        assert det._full_detected is True

    def test_a_disconnect_clears_the_withdrawal(self):
        """``reset_session`` is the session boundary. Whatever SEM did to
        the last car must not follow the next one onto the same box."""
        det = EVTaperDetector(CONFIG)
        cursor = _feed_real_taper(det)
        _feed(det, 0.0, 0.0, 6, cursor)
        det.reset_session()

        # New car, uncontrolled/observer shape (setpoint 0 throughout).
        # If the previous session's withdrawal survived the reset, this
        # would be wrongly blocked.
        cursor = _feed_real_taper(det, setpoint_a=0.0)
        _feed(det, 0.0, 0.0, 6, cursor)
        assert det._full_detected is True
