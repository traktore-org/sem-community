"""#909 — the peak block's numbers reach the card.

Guido, 03.09, with the EV card and the Load Management card on one screen:
*"How is this possible? 4.3 kW charging and 4.36 kW margin."* Both were
right. "Current Peak" is the **15-minute rolling average** of grid import —
the metric a demand tariff bills — and the car had run six of those fifteen
minutes. Nothing on the card said "average", and the number that actually
bounds the next command, the #864 slot allowance, was published nowhere an
entity could see it: it lived in ``coordinator.data`` and on no attribute.

So the card could not have shown it. This pins the surface: the peak-limit
entity carries the guard's own two numbers, absent when there is nothing
honest to publish.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorEntityDescription

from custom_components.solar_energy_management.sensor import SEMSolarSensor


def _sensor(data):
    coord = MagicMock()
    coord.data = {"last_update": "x", **data}
    coord.last_update_success = True
    s = SEMSolarSensor(
        coordinator=coord,
        description=SensorEntityDescription(key="target_peak_limit", name="x"),
        entry_id="e",
    )
    return s


@pytest.mark.unit
class TestTheGuardsNumbersAreOnTheLimitEntity:

    def test_the_slot_allowance_and_usage_are_published(self):
        s = _sensor({"target_peak_limit": 6.0, "peak_slot_allowed_w": 4023.0,
                     "peak_slot_used_kwh": 0.83})
        a = s.extra_state_attributes
        assert a["peak_slot_allowed_w"] == 4023.0
        assert a["peak_slot_used_kwh"] == 0.83

    def test_an_uncapped_install_publishes_absence_not_zero(self):
        s = _sensor({"target_peak_limit": 80.0, "peak_limit_unlimited": True})
        a = s.extra_state_attributes
        assert a["peak_limit_unlimited"] is True
        assert a["peak_slot_allowed_w"] is None
        assert a["peak_slot_used_kwh"] is None

    def test_the_existing_unlimited_flag_still_rides(self):
        s = _sensor({"target_peak_limit": 6.0, "peak_limit_unlimited": False})
        assert s.extra_state_attributes["peak_limit_unlimited"] is False


@pytest.mark.unit
class TestTheCardReadsThem:
    """Structural: the card must read the guard's numbers and name the
    average, or the surface is back where it started."""

    def _card(self):
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        p = os.path.join(root, "dashboard", "card", "src", "cards",
                         "sem-load-priority-card.js")
        with open(p, encoding="utf-8") as fh:
            return fh.read()

    def test_it_reads_the_slot_attributes(self):
        src = self._card()
        assert "peak_slot_allowed_w" in src and "peak_slot_used_kwh" in src

    def test_it_says_average_not_current_peak(self):
        src = self._card()
        assert "peak_15min_avg" in src, "the 15-minute average must be named"

    def test_it_shows_the_instantaneous_draw_beside_it(self):
        src = self._card()
        assert "importKw" in src and "peak_right_now" in src

    def test_the_helpers_are_the_shared_pure_ones(self):
        src = self._card()
        assert "from '../util/peak-slot.js'" in src
