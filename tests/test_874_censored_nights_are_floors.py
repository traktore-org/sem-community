"""#778 — a night the grid finished must not read as a small night.

Found by an independent review of the v2.0.0..develop diff (30.08.2026).

``expected_overnight_need`` ranks ``drain_kwh`` at the 85th percentile, to
reserve enough for the nights that ask the most. But ``battery_night.py``'s
own module docstring states the censoring plainly:

    "a night where the battery hit reserve and the grid took over observes
     LESS drain than the house needed (``reserve_hit`` — the budget's
     consumer must treat such drains as floors …)"

The consumer never did. It read ``drain_kwh`` alone, so exactly the nights
that needed the MOST — the ones that emptied the pack and handed over to the
grid — recorded artificially low and sorted into the MIDDLE of the
distribution, dragging the p85 threshold DOWN. The percentile designed to
protect the biggest nights was being lowered by them.

``night_grid_kwh`` was recorded for this and had no consumer anywhere in the
package.

The fix needs no special case: ``drain_kwh`` integrates
``battery_to_home_w`` and ``night_grid_kwh`` integrates ``grid_to_home_w``,
both home-directed with the EV excluded, so their SUM is the house's actual
overnight need on every night. On an uncensored night the grid term is ~0
and the sum is the drain, unchanged.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.measured_capacity import (
    expected_overnight_need,
)


def _night(date, drain, grid=0.0, reserve_hit=False, trainable=True):
    return {"date": date, "drain_kwh": drain, "night_grid_kwh": grid,
            "reserve_hit": reserve_hit, "trainable": trainable,
            "soc_start": 90.0, "soc_morning": 40.0}


class TestTheGridShareCounts:
    def test_a_censored_night_counts_what_the_grid_finished(self):
        """One night: battery gave 4 kWh then hit reserve, grid gave 5 more.
        The house needed 9, not 4."""
        nights = [_night(f"2026-08-{d:02d}", 4.0, grid=5.0, reserve_hit=True)
                  for d in range(1, 11)]
        assert expected_overnight_need(nights) == pytest.approx(9.0), (
            "the night that emptied the pack was recorded as the SMALLEST "
            "kind of night"
        )

    def test_an_uncensored_night_is_unchanged(self):
        nights = [_night(f"2026-08-{d:02d}", 6.0) for d in range(1, 11)]
        assert expected_overnight_need(nights) == pytest.approx(6.0)

    def test_censored_nights_raise_the_reserve_they_used_to_lower(self):
        """The defect stated as its consequence, measured both ways.

        The same four hard nights, once with the grid share recorded (what
        the house actually needed) and once without it (what the battery
        alone observed). The censored reading must not produce the SMALLER
        reserve — that is the inversion: the nights that already proved the
        reserve insufficient were the ones pulling it down.
        """
        ordinary = [_night(f"2026-08-{d:02d}", 5.0) for d in range(1, 7)]
        hard_true = ordinary + [
            _night(f"2026-08-{d:02d}", 4.0, grid=7.0, reserve_hit=True)
            for d in range(7, 11)]
        hard_censored = ordinary + [
            _night(f"2026-08-{d:02d}", 4.0, reserve_hit=True)
            for d in range(7, 11)]

        with_grid = expected_overnight_need(hard_true)
        without = expected_overnight_need(hard_censored)

        assert with_grid == pytest.approx(11.0)
        assert without == pytest.approx(5.0)
        assert with_grid > without, (
            "four nights that emptied the pack and needed 11 kWh each were "
            "read as the four SMALLEST nights, lowering the reserve below an "
            "ordinary night"
        )

    def test_a_record_without_the_grid_field_still_works(self):
        """Records written before this field existed must not break."""
        old = [{"date": f"2026-08-{d:02d}", "drain_kwh": 6.0,
                "trainable": True, "soc_start": 90.0, "soc_morning": 40.0}
               for d in range(1, 11)]
        assert expected_overnight_need(old) == pytest.approx(6.0)

    def test_an_unreadable_grid_value_is_ignored_not_fatal(self):
        nights = [_night(f"2026-08-{d:02d}", 6.0) for d in range(1, 10)]
        nights.append(_night("2026-08-10", 6.0, grid="nonsense"))
        assert expected_overnight_need(nights) == pytest.approx(6.0)

    def test_untrainable_nights_are_still_excluded(self):
        """The existing quality gate is untouched."""
        nights = [_night(f"2026-08-{d:02d}", 5.0) for d in range(1, 11)]
        nights.append(_night("2026-08-20", 99.0, grid=99.0, trainable=False))
        assert expected_overnight_need(nights) == pytest.approx(5.0)
