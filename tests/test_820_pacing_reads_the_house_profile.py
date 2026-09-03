"""#820 — pacing sizes the day against the HOUSE PROFILE, not a flat night draw.

@ArneGollin1987 on beta.5 (02.09): *"the algorithm calculated 800 Watts till
8 pm to fill the battery to 100% and forecast says there will be sun just till
8 pm … So it did not calculate the forecast - house consumption. My battery
did fill up to 88% SOC because since 7pm PV generation - house consumption
does not leave leftover for battery, even though the PV generation followed
the forecast nicely."*

He is right, and the subtraction is not missing — it reads the wrong number.
``build_day_slots`` computes ``surplus = solar - home_w_at(t)`` and its
docstring names the input *"the predictor's hourly profile with the flat
fallback, same as the night collector"*. The night packer passes exactly
that. The pacing ledger passed ``lambda t: flat_home`` — the average
OVERNIGHT draw, held constant across the whole day. Evening hours therefore
modelled a sleeping house against a setting sun: SEM saw surplus at 19:00
that the kitchen was already eating, paced to land full at sunset, and the
pack stopped at 88 %.

One profile, every day-ledger consumer: ``_day_home_w_at()``.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.solar_energy_management.coordinator.charge_pacing import (
    paced_charge_cap_w,
    today_remaining_slots,
)
from custom_components.solar_energy_management.coordinator.day_ledger import (
    build_day_slots,
)

NOW = datetime(2026, 9, 3, 12, 0)
SUNRISE = datetime(2026, 9, 3, 6, 40)
SUNSET = datetime(2026, 9, 3, 20, 0)

#: A real house: quiet at night, awake in the evening. Index = hours from NOW.
EVENING_PROFILE = {12: 400.0, 13: 400.0, 14: 450.0, 15: 500.0,
                   16: 700.0, 17: 1200.0, 18: 2200.0, 19: 2600.0}
NIGHT_FLAT_W = 400.0


def _slots(home_w_at):
    return today_remaining_slots(
        now=NOW, sunrise=SUNRISE, sunset=SUNSET, day_kwh=40.0,
        home_w_at=home_w_at, builder=build_day_slots,
        price_at=lambda ts: 0.30, level_cheap_at=lambda ts: False,
    )


def _profile_at(t):
    return EVENING_PROFILE.get(t.hour, NIGHT_FLAT_W)


@pytest.mark.unit
class TestTheEveningIsNotANightHouse:

    def test_a_flat_night_draw_invents_evening_surplus(self):
        """The defect, stated as a measurement: the flat model believes the
        last hours still charge the pack; the profile knows better."""
        flat = _slots(lambda t: NIGHT_FLAT_W)
        real = _slots(_profile_at)

        def _tail_kwh(ledger):
            return sum(
                max(0.0, s.cap_override_w or 0.0) * s.hours / 1000.0
                for s in ledger if s.start.hour >= 18
            )

        assert _tail_kwh(flat) > _tail_kwh(real) + 1.0, (
            "a flat night draw must over-count the evening"
        )

    def test_the_cap_rises_when_the_evening_is_modelled_honestly(self):
        """Same pack, same forecast: knowing the evening is busy means the
        fill has to happen EARLIER, so the paced cap is higher — the
        reporter's pack reaches 100 % instead of stalling at 88 %."""
        kw = dict(capacity_kwh=19.2, soc_pct=60.0, target_soc_pct=100.0,
                  floor_soc_pct=35.0, forecast_trusted=True,
                  hw_max_charge_w=10000.0)
        flat = paced_charge_cap_w(ledger=_slots(lambda t: NIGHT_FLAT_W), **kw)
        real = paced_charge_cap_w(ledger=_slots(_profile_at), **kw)
        assert flat.cap_w is not None and real.cap_w is not None
        assert real.cap_w > flat.cap_w, (
            f"flat={flat.cap_w} W vs profile={real.cap_w} W — the honest "
            "evening must raise the pace, not lower it"
        )

    def test_the_pack_is_full_before_the_house_wakes_up(self):
        """The promise the cap has to keep: full by the last slot that can
        actually deliver, not by nominal sunset."""
        d = paced_charge_cap_w(
            ledger=_slots(_profile_at), capacity_kwh=19.2, soc_pct=60.0,
            target_soc_pct=100.0, floor_soc_pct=35.0, forecast_trusted=True,
            hw_max_charge_w=10000.0,
        )
        assert d.full_at is not None
        assert datetime.fromisoformat(d.full_at) <= NOW + timedelta(hours=7)


@pytest.mark.unit
class TestOneProfileForEveryDayLedger:
    """``_day_home_w_at`` is THE accessor — the night packer's closure,
    promoted so pacing and the previews read the same house."""

    def _coord(self, hourly=None, flat=500.0):
        from unittest.mock import MagicMock
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        c = SEMCoordinator.__new__(SEMCoordinator)
        if hourly is None:
            c._predictor = None
        else:
            pred = MagicMock()
            pred.predict_consumption_24h.return_value = hourly
            c._predictor = pred
        c._expected_night_home_w = lambda energy=None, **kw: flat
        return c

    def test_the_profile_wins_when_trained(self):
        c = self._coord(hourly=[100.0 + 100 * i for i in range(24)])
        at = c._day_home_w_at(NOW)
        assert at(NOW) == pytest.approx(100.0)
        assert at(NOW + timedelta(hours=3)) == pytest.approx(400.0)

    def test_a_zero_hour_is_a_data_gap_not_a_sleeping_house(self):
        hourly = [0.0] * 24
        c = self._coord(hourly=hourly, flat=500.0)
        assert c._day_home_w_at(NOW)(NOW) == pytest.approx(500.0)

    def test_no_predictor_falls_back_flat(self):
        c = self._coord(hourly=None, flat=500.0)
        assert c._day_home_w_at(NOW)(NOW + timedelta(hours=5)) == pytest.approx(500.0)

    def test_beyond_the_horizon_falls_back_flat(self):
        c = self._coord(hourly=[250.0] * 24, flat=500.0)
        assert c._day_home_w_at(NOW)(NOW + timedelta(hours=30)) == pytest.approx(500.0)

    def test_every_day_ledger_site_uses_it(self):
        """Structural: no site may hand a day ledger a constant house."""
        import inspect
        from custom_components.solar_energy_management.coordinator import (
            coordinator as cm,
        )
        src = inspect.getsource(cm)
        assert "home_w_at=lambda t: flat_home" not in src, (
            "a flat night draw is not a day profile (#820)"
        )
        assert src.count("_day_home_w_at(") >= 4
