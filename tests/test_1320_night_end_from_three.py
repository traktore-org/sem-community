"""(#1320) An off-peak period that ends at 04:00 could not be set.

The night ends at sunrise or at "Night Latest End", whichever comes first.
The slider started at 05:00, so a reporter whose cheap tariff ends at 04:00
had no way to end the night there. It now starts at 03:00.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.solar_energy_management import number as number_mod
from custom_components.solar_energy_management.utils.time_manager import TimeManager


def _description():
    for group in vars(number_mod).values():
        if isinstance(group, (list, tuple)):
            for d in group:
                if getattr(d, "key", None) == "night_latest_end":
                    return d
    raise AssertionError("no night_latest_end number")


def test_the_slider_reaches_four_and_three():
    d = _description()
    assert d.native_min_value == 3.0 and d.native_max_value == 9.0
    assert (4.0 - d.native_min_value) % d.native_step == 0      # 04:00 is a step


def test_four_ends_the_night_at_four_before_a_later_sunrise():
    tm = TimeManager(MagicMock(), {"night_latest_end": 4.0})
    tm.get_sunrise_time = lambda: "07:12"
    tm.get_night_start_time = lambda: "17:30"
    assert tm.get_night_window()[1] == "04:00"


def test_an_earlier_sunrise_still_ends_it():
    tm = TimeManager(MagicMock(), {"night_latest_end": 4.0})
    tm.get_sunrise_time = lambda: "03:40"
    tm.get_night_start_time = lambda: "22:30"
    assert tm.get_night_window()[1] == "03:40"
