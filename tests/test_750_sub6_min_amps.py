"""#750/#752 — the 6 A floor becomes hardware-derived, not hard-coded.

Two reporters, one ask: vehicle-side control (Tesla BLE, an ESP32 number)
can charge below 6 A, but SEM's config sliders were floored at 6 and so
the minimum could never reflect what the hardware actually supports.

The design: the CONFIG allows down to 1 A; enforcement is where it always
belonged — the hardware layer. The current write already clamps to the
control entity's own min/max (#487), and brand adapters keep their own
minima (KEBA's 6 A lives in its adapter, untouched). A configured 2 A
flows through the decision floor (`effective_min_amps`), the packer's
demand floor, and the overlay unchanged — those paths never hard-floored
at 6, they only DEFAULTED to it, which stays."""

import re

import pytest

from custom_components.solar_energy_management.coordinator.decide import (
    effective_min_amps,
)


@pytest.mark.unit
class TestTheDecisionFloorFollowsTheConfig:
    def test_two_amps_flows_through(self):
        assert effective_min_amps({"ev_min_current": 2}, 6) == 2

    def test_the_default_stays_six(self):
        assert effective_min_amps({}, 6) == 6
        assert effective_min_amps({"ev_min_current": None}, 6) == 6

    def test_the_vehicle_floor_still_wins_upward(self):
        assert effective_min_amps(
            {"ev_min_current": 2, "vehicle_min_current": 9}, 6) == 9


@pytest.mark.unit
class TestTheConfigSlidersAllowSub6:
    def test_no_current_slider_is_floored_at_six(self):
        from pathlib import Path
        src = Path(__file__).resolve().parent.parent.joinpath(
            "config_flow.py").read_text()
        floored = re.findall(r"min=6, max=\d+", src)
        assert floored == [], (
            f"current sliders still hard-floored at 6 A: {floored} — "
            "the hardware layer (#487 entity clamp, brand adapter minima) "
            "is the enforcement point, not the config")

    def test_the_defaults_are_untouched(self):
        from pathlib import Path
        src = Path(__file__).resolve().parent.parent.joinpath(
            "config_flow.py").read_text()
        assert 'self._data.get("ev_min_current", 6)' in src
