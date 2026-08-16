"""#774 — the meter refutes the anchor.

PROD, 14.08.2026 15:31: the car drawing 8760 W, session 2.4 kWh, and the
Energy Plan card saying "NOT SCHEDULED TONIGHT — ev_charger: car is
already full" with ``estimated_soc`` at 100.0.

``_energy_since_full`` is the deficit below full. Charging SUBTRACTS from
it (clamped at zero) and only two paths ever raise it: a vehicle-SOC
reading, and ``apply_daily_decay`` — which runs *once per day at rollover
while the car is NOT connected*. ``reset_session`` clears the sensor
anchor because "the anchor is meaningless across sessions" but leaves
``_soc_anchored`` / ``_energy_since_full`` standing.

So charge-to-full → unplug → drive → replug the SAME day never reaches a
rollover, the deficit stays pinned at 0.0, and ``still_full`` reads True
for the whole of the next charge.

That is #755 contract 1 inverted: an estimate outranking a measurement.
A pack that accepts 8.7 kW had room for it. Delivered energy in excess of
the remaining deficit is proof the reference is stale — and a stale
reference is no reference, not a licence to invent a replacement number.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.ev_availability import (
    plan_car_fullness,
)
from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
    EVTaperDetector,
)

CAPACITY = 52.0


def _full_car() -> EVTaperDetector:
    """A detector left exactly where last night's completed charge left it."""
    det = EVTaperDetector({"ev_battery_capacity_kwh": CAPACITY})
    det._soc_anchored = True
    det._energy_since_full = 0.0
    det._estimated_soc = 100.0
    det.reset_session()  # the morning unplug
    return det


def _deliver(det: EVTaperDetector, kwh: float, cycles: int = 1) -> None:
    for _ in range(cycles):
        det.update_energy(kwh / cycles)


class TestTheMeterRefutesTheAnchor:
    def test_the_prod_shape_a_replug_after_a_drive_is_not_a_full_car(self) -> None:
        """8.7 kW for ~17 min = 2.4 kWh into a pack we believed was full."""
        det = _full_car()
        _deliver(det, 2.4, cycles=100)

        assert det.still_full is False
        assert plan_car_fullness(det) is None  # no opinion → the plan asks

    def test_rounding_noise_does_not_unseat_a_real_anchor(self) -> None:
        """A genuinely full pack trickling a few Wh keeps its reference."""
        det = _full_car()
        _deliver(det, 0.05, cycles=5)

        assert det.still_full is True

    def test_a_real_deficit_is_spent_before_the_anchor_is_questioned(self) -> None:
        """The normal charge: 5 kWh into a pack believed 15 kWh empty walks
        the deficit down and touches nothing else."""
        det = _full_car()
        det._energy_since_full = 15.0
        _deliver(det, 5.0, cycles=200)

        assert det._soc_anchored is True
        assert det._energy_since_full == pytest.approx(15.0 - 5.0 * 0.9, abs=0.3)
        assert det.still_full is False

    def test_the_estimate_that_ran_out_mid_charge_is_refuted_too(self) -> None:
        """Same path from the other side: a 2 kWh estimate that eats 9 kWh
        was wrong about the pack, not about the meter."""
        det = _full_car()
        det._energy_since_full = 2.0
        _deliver(det, 9.0, cycles=300)

        assert det._soc_anchored is False

    def test_a_detected_full_charge_is_never_refuted_by_its_own_trickle(self) -> None:
        """``_full_detected`` short-circuits booking entirely — the taper
        anchor is the ONE reference a live charge may not overturn."""
        det = _full_car()
        det._full_detected = True
        _deliver(det, 3.0, cycles=100)

        assert det._soc_anchored is True
        assert det.still_full is True


class TestWhatTheUserSeesAfterwards:
    def test_an_unanchored_zero_deficit_detector_reports_no_soc(self) -> None:
        """The #245 display gate (``not _soc_anchored and _energy_since_full
        == 0.0`` → None) is what makes un-anchoring the honest move: the
        sensor says "unknown", not a confident 100 %."""
        det = _full_car()
        _deliver(det, 2.4, cycles=100)

        assert det._soc_anchored is False
        assert det._energy_since_full == 0.0

    def test_the_next_real_reference_re_arms_it(self) -> None:
        """A vehicle-SOC reading anchors again immediately — refutation
        clears the stale reference, it does not blind the detector."""
        det = _full_car()
        _deliver(det, 2.4, cycles=100)

        assert det.get_virtual_soc(64.0) == 64.0
        assert det._soc_anchored is True
        assert det._energy_since_full == pytest.approx(
            (100.0 - 64.0) / 100.0 * CAPACITY
        )

    def test_a_refuted_anchor_does_not_re_arm_itself_on_the_next_kwh(self) -> None:
        """Once refuted the detector stays quiet until a real reference —
        ``update_energy`` is deliberately inert while unanchored (#245)."""
        det = _full_car()
        _deliver(det, 2.4, cycles=100)
        _deliver(det, 5.0, cycles=100)

        assert det._soc_anchored is False
