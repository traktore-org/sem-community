"""(#638 / #705 Phase 3) The drift learner — what makes comfort PLANNABLE.

A room's temperature drifts toward ambient while its device is off. Learn
the rate (°C/h) from the readings SEM already takes, and "the room hits
the limit at 17:20" becomes a deadline-shaped demand the day planner can
place into a forecast-surplus window — exactly like tonight's EV floor.

Pure module: samples in, rate and predictions out. No HA imports.
"""
from datetime import datetime, timedelta

from custom_components.solar_energy_management.coordinator.comfort_drift import (
    DriftEstimate,
    learn_drift,
    time_to_limit,
)

T0 = datetime(2026, 8, 7, 12, 0)


def _samples(rate_c_per_h, hours=2.0, start=24.0, n=9):
    step = hours / (n - 1)
    return [(T0 + timedelta(hours=i * step), start + rate_c_per_h * i * step)
            for i in range(n)]


class TestLearnDrift:
    def test_a_warming_room_yields_a_positive_rate(self):
        est = learn_drift(_samples(+0.8))
        assert est is not None
        assert abs(est.rate_c_per_h - 0.8) < 0.05

    def test_a_cooling_room_yields_a_negative_rate(self):
        est = learn_drift(_samples(-0.5))
        assert abs(est.rate_c_per_h + 0.5) < 0.05

    def test_too_few_samples_is_no_estimate(self):
        assert learn_drift(_samples(0.8)[:2]) is None

    def test_noise_does_not_flip_the_sign(self):
        pts = _samples(+0.8)
        noisy = [(t, v + (0.1 if i % 2 else -0.1)) for i, (t, v) in enumerate(pts)]
        est = learn_drift(noisy)
        assert est.rate_c_per_h > 0.5

    def test_a_flat_room_is_a_zero_rate_not_none(self):
        est = learn_drift(_samples(0.0))
        assert est is not None
        assert abs(est.rate_c_per_h) < 0.01


class TestTimeToLimit:
    def test_predicts_when_the_room_hits_the_limit(self):
        est = DriftEstimate(rate_c_per_h=0.8)
        eta = time_to_limit(est, current_c=24.0, limit_c=26.0,
                            direction="cool", now=T0)
        assert eta == T0 + timedelta(hours=2.5)

    def test_heat_direction_mirrors(self):
        est = DriftEstimate(rate_c_per_h=-1.0)   # room losing heat
        eta = time_to_limit(est, current_c=20.0, limit_c=18.0,
                            direction="heat", now=T0)
        assert eta == T0 + timedelta(hours=2.0)

    def test_a_room_drifting_away_from_the_limit_never_arrives(self):
        est = DriftEstimate(rate_c_per_h=-0.5)   # cooling by itself
        assert time_to_limit(est, current_c=24.0, limit_c=26.0,
                             direction="cool", now=T0) is None

    def test_a_flat_room_never_arrives(self):
        est = DriftEstimate(rate_c_per_h=0.0)
        assert time_to_limit(est, current_c=24.0, limit_c=26.0,
                             direction="cool", now=T0) is None

    def test_already_past_the_limit_is_now(self):
        est = DriftEstimate(rate_c_per_h=0.8)
        assert time_to_limit(est, current_c=26.5, limit_c=26.0,
                             direction="cool", now=T0) == T0
