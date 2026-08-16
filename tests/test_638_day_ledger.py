"""#638 day horizon — the day expressed as ledger slots the night packer
already understands.

The design rule (Guido: "even with dayplanner" — one mind, no second
engine): the DAY becomes ``LedgerSlot``s — expected-surplus hours are
price-0 slots capped at the surplus power (the sun is free but finite);
deficit hours carry the import rate from the SAME tariff provider the
night packer reads (never a parallel price path). ``build_night_ledger`` +
``pack_night`` then run unchanged over them.

The hourly solar curve is synthesized from the scalar day total with the
sine-shape model ``forecast_tracker`` already trusts (low mornings, noon
peak) — the forecast integrations publish day totals, not curves.
"""
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.solar_energy_management.coordinator.day_ledger import (
    build_day_slots,
    expected_solar_kwh_between,
)
from custom_components.solar_energy_management.coordinator.energy_planner import (
    Demand,
    build_night_ledger,
    pack_night,
)

TZ = timezone.utc


def _t(h, m=0, day=8):
    return datetime(2026, 8, day, h, m, tzinfo=TZ)


SUNRISE, SUNSET = _t(6), _t(20)


class TestTheSolarShape:
    """The sine model: zero outside daylight, noon-heavy, integrates to
    the day total."""

    def test_night_hours_have_no_sun(self):
        assert expected_solar_kwh_between(
            _t(3), _t(4), day_kwh=20.0, sunrise=SUNRISE, sunset=SUNSET) == 0.0
        assert expected_solar_kwh_between(
            _t(21), _t(22), day_kwh=20.0, sunrise=SUNRISE, sunset=SUNSET) == 0.0

    def test_the_whole_day_integrates_to_the_total(self):
        total = expected_solar_kwh_between(
            SUNRISE, SUNSET, day_kwh=20.0, sunrise=SUNRISE, sunset=SUNSET)
        assert total == pytest.approx(20.0, abs=0.01)

    def test_noon_beats_the_morning(self):
        morning = expected_solar_kwh_between(
            _t(7), _t(8), day_kwh=20.0, sunrise=SUNRISE, sunset=SUNSET)
        noon = expected_solar_kwh_between(
            _t(12), _t(13), day_kwh=20.0, sunrise=SUNRISE, sunset=SUNSET)
        assert noon > morning * 2

    def test_a_slot_straddling_sunrise_counts_only_the_lit_part(self):
        lit = expected_solar_kwh_between(
            _t(6), _t(7), day_kwh=20.0, sunrise=SUNRISE, sunset=SUNSET)
        straddling = expected_solar_kwh_between(
            _t(5), _t(7), day_kwh=20.0, sunrise=SUNRISE, sunset=SUNSET)
        assert straddling == pytest.approx(lit, abs=1e-9)

    def test_no_forecast_is_no_sun(self):
        assert expected_solar_kwh_between(
            _t(12), _t(13), day_kwh=0.0, sunrise=SUNRISE, sunset=SUNSET) == 0.0


def _slots(**kw):
    args = dict(
        start=_t(8), end=_t(18),
        day_kwh=20.0, sunrise=SUNRISE, sunset=SUNSET,
        home_w_at=lambda t: 500.0,
        price_at=lambda t: 0.30,
        level_cheap_at=lambda t: False,
    )
    args.update(kw)
    return build_day_slots(**args)


class TestDaySlots:
    def test_an_odd_start_yields_a_partial_first_slot_then_aligned(self):
        """(the midnight pause, live 00:01 on 09.08) A re-plan mid-hour
        must be able to CONTINUE an interrupted run — the ledger models
        the remainder of the current interval as a real, priced slot,
        then returns to the market grid. Without it, the earliest slot
        was the next full hour and an in-progress block paused ~58 min
        for no economic reason."""
        slots = _slots(start=_t(8, 17))
        assert slots[0].start == _t(8, 17)
        assert slots[0].end == _t(9), "partial first slot ends ON the grid"
        assert slots[1].start == _t(9) and slots[1].end == _t(10)

    def test_slots_tile_the_window_hourly(self):
        slots = _slots()
        assert len(slots) == 10
        assert slots[0].start == _t(8) and slots[-1].end == _t(18)
        for a, b in zip(slots, slots[1:]):
            assert a.end == b.start

    def test_a_surplus_hour_is_a_free_capped_slot(self):
        """Noon on a 20 kWh day is well past 2 kW of surplus over a 500 W
        house: the sun is cheap but finite (cap = surplus), and the home is
        already paid for (home_w 0 — it runs on the same sun, not on the
        ledger's battery walk).

        Price 0 here because this fixture passes no ``export_rate``, and with
        no feed-in tariff nothing is forgone by consuming your own kWh. Where
        one IS configured the slot prices at it (#755) — see
        ``test_755_self_consumption.py::TestTheSunIsNotFree``."""
        noon = [s for s in _slots() if s.start.hour == 12][0]
        assert noon.price == 0.0
        assert noon.level_cheap is True
        assert noon.home_w == 0.0
        assert noon.cap_override_w is not None and noon.cap_override_w > 1000.0

    def test_a_deficit_hour_pays_the_import_rate(self):
        """17:00–18:00 on the sine tail: little sun, the house draws the
        difference — the slot prices at the provider's rate and the home's
        NET draw rides the normal ledger walk."""
        evening = [s for s in _slots(home_w_at=lambda t: 2500.0)
                   if s.start.hour == 17][0]
        assert evening.price == 0.30
        assert evening.home_w > 0.0
        assert evening.cap_override_w is None

    def test_the_margin_keeps_knife_edge_surplus_honest(self):
        """A 100 W computed surplus is forecast noise, not a free window."""
        slots = _slots(home_w_at=lambda t: 2500.0, surplus_margin_w=200.0,
                       day_kwh=6.0)
        assert all(s.cap_override_w is None or s.cap_override_w >= 200.0
                   for s in slots)

    def test_an_unpriced_deficit_hour_stays_honestly_unpriced(self):
        def _raise(t):
            raise RuntimeError("day-ahead not published")
        slots = _slots(price_at=_raise, home_w_at=lambda t: 5000.0)
        deficit = [s for s in slots if s.cap_override_w is None]
        assert deficit and all(s.price is None for s in deficit)

    def test_the_cheap_level_reads_the_same_provider_gate(self):
        slots = _slots(level_cheap_at=lambda t: t.hour == 17,
                       home_w_at=lambda t: 5000.0)
        seventeen = [s for s in slots if s.start.hour == 17][0]
        sixteen = [s for s in slots if s.start.hour == 16][0]
        assert seventeen.level_cheap is True
        assert sixteen.level_cheap is False

    def test_an_empty_window_is_no_slots(self):
        assert _slots(start=_t(18), end=_t(18)) == []


class TestThePackerRunsUnchangedOverTheDay:
    """The whole point: no second engine. A day-shaped slot list feeds the
    SAME build_night_ledger + pack_night, and a price-driven demand lands
    in the free sun window before any paid hour."""

    def test_a_demand_packs_into_the_sun_first(self):
        slots = _slots()
        ledger = build_night_ledger(
            slots, soc_kwh=5.0, floor_kwh=2.0,
            max_discharge_w=5000.0, peak_limit_w=6000.0)
        plan = pack_night(
            [Demand(id="load:pool", kind="load", energy_kwh=2.0,
                    max_power_w=1500.0, min_power_w=1500.0,
                    deadline=_t(18), priority=1)],
            ledger, floor_kwh=2.0, max_discharge_w=5000.0,
            peak_limit_w=6000.0)
        assert plan.fits is True
        assert plan.total_cost == pytest.approx(0.0, abs=0.01), (
            "2 kWh must ride the free surplus window, not the paid hours")
        for a in plan.allocations:
            assert 9 <= a.start.hour <= 16, (
                f"allocation at {a.start} — outside the sun window")


class TestTomorrowPreview:
    """(#638 consolidation / #722, tintinz's idea adopted) The NEXT energy
    day's books, previewed before any plan exists — rendered by the Energy
    Plan card's Tomorrow view. Same day_ledger machinery, same tariff
    accessors: a preview must never grow its own data path (the exact
    disease #722's today-anchored tomorrow view showed)."""

    def _preview(self, **kw):
        from custom_components.solar_energy_management.coordinator.day_ledger import (
            tomorrow_preview,
        )
        args = dict(
            day_start=_t(6, day=9), day_end=_t(21, day=9),
            day_kwh=41.0, sunrise=_t(6, day=9), sunset=_t(20, day=9),
            home_w_at=lambda t: 500.0,
            price_at=lambda t: 0.28,
            level_cheap_at=lambda t: False,
            stamps_at=_t(6, 7, day=9),
        )
        args.update(kw)
        return tomorrow_preview(**args)

    def test_a_sunny_forecast_becomes_surplus_windows(self):
        p = self._preview()
        assert p["forecast_kwh"] == 41.0
        assert p["surplus_windows"], "41 kWh over a 500 W house has surplus"
        w = p["surplus_windows"][0]
        assert w["start"] < w["end"]
        # adjacent surplus slots merge into ONE window, not 8 slivers
        assert len(p["surplus_windows"]) <= 2

    def test_cheap_windows_come_from_the_same_level_gate(self):
        p = self._preview(day_kwh=0.0,
                          level_cheap_at=lambda t: t.hour in (13, 14))
        assert len(p["cheap_windows"]) == 1
        assert "13:00" in p["cheap_windows"][0]["start"]
        assert "15:00" in p["cheap_windows"][0]["end"]

    def test_published_prices_read_final(self):
        assert self._preview()["prices"] == "final"

    def test_an_unpublished_day_ahead_reads_preliminary(self):
        assert self._preview(price_at=lambda t: None)["prices"] == "preliminary"

    def test_the_stamp_time_is_carried(self):
        assert "06:07" in self._preview()["stamps_at"]

    def test_a_dark_unpriced_day_still_has_the_shape(self):
        p = self._preview(day_kwh=0.0, price_at=lambda t: None)
        assert p["surplus_windows"] == [] and p["prices"] == "preliminary"
        assert "forecast_kwh" in p and "cheap_windows" in p


class TestProvisionalSocCurve:
    """(Guido, 08-08: 'we can also predict the battery level and when the
    devices get surplus — pull it together') — the missing half of the
    tomorrow walk: the ledger walk models the battery DISCHARGING to the
    home; through a surplus day the leftover sun CHARGES it. The curve is
    the walk's soc plus cumulative leftover-surplus charging, capped at
    capacity — provisional by nature, labeled so."""

    def _curve(self, **kw):
        from custom_components.solar_energy_management.coordinator.day_ledger import (
            provisional_soc_curve,
        )
        slots = _slots(day_kwh=30.0)   # deep surplus midday over 500 W home
        ledger = build_night_ledger(
            slots, soc_kwh=kw.pop("soc", 4.0), floor_kwh=2.0,
            max_discharge_w=5000.0, peak_limit_w=6000.0)
        args = dict(capacity_kwh=10.0, max_charge_w=3000.0)
        args.update(kw)
        return provisional_soc_curve(ledger, **args)

    def test_the_sun_charges_the_battery_through_the_day(self):
        pts = self._curve()
        assert pts[0]["kwh"] == 4.0
        assert pts[-1]["kwh"] > pts[0]["kwh"]

    def test_the_curve_caps_at_capacity(self):
        pts = self._curve()
        assert all(p["kwh"] <= 10.0 + 1e-6 for p in pts)
        assert pts[-1]["kwh"] == 10.0   # 30 kWh day fills a 10 kWh pack

    def test_charging_respects_the_power_cap(self):
        slow = self._curve(max_charge_w=500.0)
        fast = self._curve(max_charge_w=3000.0)
        mid = len(slow) // 2
        assert slow[mid]["kwh"] < fast[mid]["kwh"]

    def test_committed_grants_reduce_the_leftover(self):
        """A slot whose surplus budget is already granted to devices has
        less left for the battery — the curve must read the ledger's
        grid_committed_w, not the raw cap."""
        slots = _slots(day_kwh=30.0)
        ledger = build_night_ledger(slots, soc_kwh=4.0, floor_kwh=2.0,
                                    max_discharge_w=5000.0,
                                    peak_limit_w=6000.0)
        free = [s for s in ledger if s.cap_override_w is not None]
        for s in free:
            s.grid_committed_w = s.cap_override_w   # devices took it all
        from custom_components.solar_energy_management.coordinator.day_ledger import (
            provisional_soc_curve,
        )
        pts = provisional_soc_curve(ledger, capacity_kwh=10.0,
                                    max_charge_w=3000.0)
        assert pts[-1]["kwh"] < 10.0, "nothing left over — pack stays short"

    def test_no_battery_is_no_curve(self):
        assert self._curve(capacity_kwh=0.0) == []
