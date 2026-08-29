"""#705 Phase 3 — pre-cool (and pre-heat) bank to the band's EDGE.

Phases 1+2 built the drift models and the direction-aware ask; C5 gave
banking its actuation. What was missing is the DEPTH: the ask sized the
energy only to TARGET, but the whole point of pre-cooling is to buy the
full band — cool to ``target − offset`` (heat: ``target + offset``) in
the cheap/free window so the room COASTS through the expensive one. The
run's natural stop already agrees: the C5 clause holds the device while
``willing``, and crossing the edge flips the state to ``banked``.
"""

from collections import deque
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.comfort_drift import (
    banking_energy_kwh,
)

NOW = datetime(2026, 8, 12, 13, 0)


@pytest.mark.unit
class TestBankingReachesTheEdge:
    def test_cool_banks_below_target(self):
        # Room 24 °C, target 22, offset 1 → the bank ends at 21. At an
        # active −1 °C/h on a 1 kW unit: 3 °C → 3 h → 3 kWh (was 2 to
        # target only).
        kwh = banking_energy_kwh(
            current_c=24.0, target_c=22.0, offset_c=1.0, direction="cool",
            active_rate_c_per_h=-1.0, rated_power_w=1000.0)
        assert kwh == pytest.approx(3.0)

    def test_heat_banks_above_target(self):
        kwh = banking_energy_kwh(
            current_c=19.0, target_c=21.0, offset_c=1.0, direction="heat",
            active_rate_c_per_h=1.0, rated_power_w=1000.0)
        assert kwh == pytest.approx(3.0)

    def test_already_at_the_edge_is_zero(self):
        kwh = banking_energy_kwh(
            current_c=21.0, target_c=22.0, offset_c=1.0, direction="cool",
            active_rate_c_per_h=-1.0, rated_power_w=1000.0)
        assert kwh == 0.0

    def test_a_contradicting_rate_still_refuses(self):
        kwh = banking_energy_kwh(
            current_c=24.0, target_c=22.0, offset_c=1.0, direction="cool",
            active_rate_c_per_h=+0.5, rated_power_w=1000.0)
        assert kwh is None

    def test_no_offset_keeps_the_old_target_depth(self):
        kwh = banking_energy_kwh(
            current_c=24.0, target_c=22.0, direction="cool",
            active_rate_c_per_h=-1.0, rated_power_w=1000.0)
        assert kwh == pytest.approx(2.0)


@pytest.mark.unit
class TestTheCoolAskEndToEnd:
    def test_a_warming_room_asks_to_precool_the_full_band(self):
        """A cooling device with an engaged band and learned drifts
        produces the deadline-shaped pre-cool demand."""
        from custom_components.solar_energy_management.devices.base import (
            ComfortBandMixin,
        )
        dev = SimpleNamespace()
        dev.comfort_state = "willing"
        dev.comfort_target = 22.0
        dev.comfort_offset = 1.0
        dev.comfort_limit = 26.0
        dev.rated_power = 1000.0
        dev._comfort_direction = lambda: "cool"
        dev._comfort_reading = lambda: 24.0
        dev._comfort_thresholds_c = lambda: (22.0, 1.0, 26.0)
        # Free-running warms +0.5 °C/h; running cools −1 °C/h.
        dev._comfort_off_samples = deque(
            (NOW - timedelta(minutes=60 - m), 23.0 + 0.5 * m / 60)
            for m in range(0, 61, 10))
        dev._comfort_on_samples = deque(
            (NOW - timedelta(minutes=60 - m), 25.0 - 1.0 * m / 60)
            for m in range(0, 61, 10))
        # willing: between banked (<=21) and forced (>=26)
        ask = ComfortBandMixin.comfort_plan_demand(dev, NOW)
        assert ask is not None
        # 24 → 21 at 1 °C/h = 3 h on 1 kW = 3 kWh — the FULL band.
        assert ask["energy_kwh"] == pytest.approx(3.0, rel=0.1)
        # The limit (26) is 2 °C away at +0.5 °C/h → ~4 h deadline.
        assert (ask["deadline"] - NOW) > timedelta(hours=3)
