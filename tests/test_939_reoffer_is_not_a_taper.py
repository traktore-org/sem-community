"""#939 — SEM's own re-offer, unanswered, is not a car finishing.

Live (09.09.2026, Victron EVCS as a switch charger, Tesla with a SOC
sensor, 60 kWh configured): the box had charged 4.8 kWh on the sun at up
to 3.66 kW. SEM withdrew its offer at 18:20 and the box wound down with the
evening on its own. At 20:45:02 the night window opened and SEM offered
6 A. The car did not answer — it drew nothing until 21:55 — and at
20:45:32, three samples after the offer, the detector logged "EV charge
complete". The car's own sensor read 71 %.

The #708 withdrawal guard held the full-confirm while the offer was
withdrawn, but left the decline latched before it standing. The re-offer
lifted the guard, and the car's silence was scored against a decline that
belonged to the charge before. From then on ``still_full`` read True for a
car at 71 %, and the plan's car-full term flipped with the charger's own
draw — the 60 s on / 20 s off the owner filmed.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator import (
    ev_taper_detector as etd,
)
from custom_components.solar_energy_management.coordinator.ev_availability import (
    plan_car_fullness,
)
from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
    EVTaperDetector,
)

# The detector stamps samples and cuts its five-minute trend window with
# ``time.monotonic()``. Driven at test speed, every sample would land inside
# one window; the simulated clock gives it the 10-second cycles it has live.
_CLOCK = [0.0]


@pytest.fixture(autouse=True)
def _simulated_monotonic(monkeypatch):
    _CLOCK[0] = 0.0
    monkeypatch.setattr(etd, "time", SimpleNamespace(monotonic=lambda: _CLOCK[0]))

CONFIG = {"ev_battery_capacity_kwh": 60}
BASE = datetime(2026, 9, 9, 17, 0, 0)

PEAK_W = 3664.0          # the day's session peak (single-phase 16 A)
SUN_A = 16.0
NIGHT_A = 6.0            # the deadline floor SEM offered at 20:45:02
CAR_SOC = 71.0           # what the Tesla reported all evening
WIND_DOWN_W = [3000.0, 2400.0, 1800.0, 1200.0, 600.0]
SAMPLES_PER_STEP = 12    # 12 × 10 s = 2 min
HANDSHAKE_W = 500.0


def _feed(det, power_w, setpoint_a, count, cursor):
    for _ in range(count):
        _CLOCK[0] = float(cursor)
        det.update(power_w, setpoint_a, True, BASE + timedelta(seconds=cursor))
        cursor += 10
    return cursor


def _evening(det, withdrawn_samples):
    """The afternoon and the evening, up to the moment SEM re-offers.

    Returns the cursor. Leaves the detector with every precondition of the
    full-anchor met except a live offer: peak > 3 kW, session energy far
    above the floor, and the decline latched — under a WITHDRAWN offer.
    """
    det.get_virtual_soc(CAR_SOC)  # the car's own reading, known all along
    cursor = _feed(det, PEAK_W, SUN_A, 180, 0)   # 30 min on the sun ≈ 1.8 kWh
    # 18:20 — SEM withdraws; the box keeps drawing and winds down by itself.
    for step in WIND_DOWN_W:
        cursor = _feed(det, step, 0.0, SAMPLES_PER_STEP, cursor)
    # The sun is gone; the offer is still withdrawn.
    return _feed(det, 0.0, 0.0, withdrawn_samples, cursor)


class TestAnUnansweredReofferIsNotAFullCar:
    def _run(self, withdrawn_samples):
        det = EVTaperDetector(CONFIG)
        cursor = _evening(det, withdrawn_samples)
        # The precondition this test is about — pinned, or the test below
        # could pass on a detector that never latched anything.
        assert det._declining_phase is True
        assert det._full_detected is False, "the withdrawal guard held"
        # 20:45:02 — SEM offers 6 A; the car answers nothing for 70 minutes.
        _feed(det, 0.0, NIGHT_A, 420, cursor)
        return det

    def test_right_after_the_withdrawal(self):
        """Six withdrawn samples: the five-minute trend window still holds
        the wind-down, so only clearing the samples keeps the latch from
        being re-earned off the old charge."""
        det = self._run(withdrawn_samples=6)
        assert det._full_detected is False, (
            "SEM's own 6 A offer went unanswered and the detector called the "
            "car full on a decline from the charge before it (#939)."
        )
        assert det._last_full_timestamp is None

    def test_the_live_shape_hours_later(self):
        """2.5 h between the withdrawal and the night offer, as live."""
        det = self._run(withdrawn_samples=900)
        assert det._full_detected is False
        assert det._last_full_timestamp is None

    def test_the_car_at_71_percent_is_not_still_full(self):
        det = self._run(withdrawn_samples=6)
        assert det.still_full is False
        assert det.get_virtual_soc(CAR_SOC) == CAR_SOC

    def test_the_plans_car_full_term_no_longer_follows_the_draw(self):
        """The cycling itself: the plan asked "is this car full?" and got
        True while the charger was off and None while it drew — so every
        stop re-planned the car out and every start re-planned it in."""
        det = self._run(withdrawn_samples=6)
        at_rest = plan_car_fullness(det, drawing_w=0.0, handshake_w=HANDSHAKE_W)
        drawing = plan_car_fullness(det, drawing_w=1800.0, handshake_w=HANDSHAKE_W)
        assert at_rest is None
        assert at_rest == drawing


class TestTheNewChargeCanStillFinish:
    def test_a_car_that_answers_and_tapers_under_the_new_offer_anchors(self):
        """Clearing the latch at the offer costs the feature nothing: the car
        answers the 6 A offer, charges, tapers under it, and stops."""
        det = EVTaperDetector(CONFIG)
        cursor = _evening(det, withdrawn_samples=6)
        cursor = _feed(det, 1400.0, NIGHT_A, 60, cursor)   # it answers
        for step in (1100.0, 800.0, 500.0, 250.0):
            cursor = _feed(det, step, NIGHT_A, SAMPLES_PER_STEP, cursor)
        _feed(det, 0.0, NIGHT_A, 6, cursor)
        assert det._full_detected is True

    def test_an_offer_that_never_lapsed_is_not_a_fresh_charge(self):
        """Only the 0 → offer edge clears. A car that tapers and stops under
        an offer SEM kept live the whole time still anchors (the #708
        genuine case, through the same helper as above)."""
        det = EVTaperDetector(CONFIG)
        det.get_virtual_soc(CAR_SOC)
        cursor = _feed(det, PEAK_W, SUN_A, 180, 0)
        for step in WIND_DOWN_W:
            cursor = _feed(det, step, SUN_A, SAMPLES_PER_STEP, cursor)
        _feed(det, 0.0, SUN_A, 6, cursor)
        assert det._full_detected is True
