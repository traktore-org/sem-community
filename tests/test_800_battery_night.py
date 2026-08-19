"""#800 — the battery's night, written down.

The #755 learner answers demand-size questions; #778's budget question
("how much may tonight spend") needs the battery's night as a SUPPLY
story, and none of its three series was recorded anywhere: overnight
drain (flow-attributed — a SOC delta conflates house drain with the very
EV assist the budget will feed), morning refill vs the dampened
forecast's promise, and clipping hours (pack full while export runs —
the only possible evidence for "more could have been spent").

Recording only in 2.0: the budget consumer is #778/2.1. Design rules
inherited from the learner: silence is not a measurement (gaps refuse
the night), censoring is explicit (reserve-hit censors drain from
BELOW — the mirror of the demand direction), covariates are stamped but
not modeled.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.battery_night import (
    FULL_SOC, MAX_SAMPLE_GAP_S, BatteryNightTracker, Sample,
)


def _s(home=0.0, ev=0.0, grid=0.0, soc=60.0, export=0.0, measured=True,
       soc_available=True, grid_home=0.0, home_total=0.0):
    return Sample(
        battery_to_home_w=home, battery_to_ev_w=ev, battery_to_grid_w=grid,
        grid_to_home_w=grid_home, home_w=home_total,
        soc=soc, soc_available=soc_available, export_w=export,
        measured=measured,
    )


def _night(tr, t0=0.0, hours=8.0, home_w=500.0, **kw):
    """Drive a whole night of 60-s ticks."""
    t = t0
    while t <= t0 + hours * 3600.0:
        tr.tick(t, True, _s(home=home_w, **kw))
        t += 60.0
    return t


class TestNightDrain:

    def test_drain_integrates_battery_to_home_only(self):
        tr = BatteryNightTracker(reserve_soc=20.0)
        tr.start("2026-08-18", outdoor_temp_c=14.0)
        t = 0.0
        while t <= 3600.0:                      # one hour
            tr.tick(t, True, _s(home=1000.0, ev=4000.0, grid=2000.0))
            t += 60.0
        tr.tick(t, False, _s())                 # morning
        rec = tr._record()
        assert rec["drain_kwh"] == pytest.approx(1.0, rel=0.02)
        assert rec["assist_kwh"] == pytest.approx(4.0, rel=0.02)
        assert rec["export_kwh"] == pytest.approx(2.0, rel=0.02)

    def test_a_gap_refuses_the_night(self):
        tr = BatteryNightTracker(reserve_soc=20.0)
        tr.start("2026-08-18", outdoor_temp_c=None)
        tr.tick(0.0, True, _s(home=1000.0))
        tr.tick(60.0, True, _s(home=1000.0))
        # restart hole: 20 minutes of nothing
        tr.tick(60.0 + 1200.0, True, _s(home=1000.0))
        tr.tick(60.0 + 1260.0, False, _s())
        rec = tr._record()
        assert rec["gap_s"] >= 1200.0 - MAX_SAMPLE_GAP_S
        assert rec["trainable"] is False

    def test_an_unmeasured_cycle_is_a_gap_not_a_zero(self):
        tr = BatteryNightTracker(reserve_soc=20.0)
        tr.start("2026-08-18", outdoor_temp_c=None)
        tr.tick(0.0, True, _s(home=1000.0))
        tr.tick(60.0, True, _s(home=0.0, measured=False))
        tr.tick(120.0, True, _s(home=1000.0))
        tr.tick(180.0, False, _s())
        rec = tr._record()
        assert rec["gap_s"] > 0
        assert rec["trainable"] is False

    def test_reserve_hit_censors_drain_from_below(self):
        tr = BatteryNightTracker(reserve_soc=20.0)
        tr.start("2026-08-18", outdoor_temp_c=None)
        tr.tick(0.0, True, _s(home=800.0, soc=21.0))
        tr.tick(60.0, True, _s(home=0.0, soc=19.5))   # floor reached
        tr.tick(120.0, False, _s())
        rec = tr._record()
        assert rec["reserve_hit"] is True

    def test_soc_endpoints_recorded(self):
        tr = BatteryNightTracker(reserve_soc=20.0)
        tr.start("2026-08-18", outdoor_temp_c=None)
        tr.tick(0.0, True, _s(soc=95.0))
        tr.tick(60.0, True, _s(soc=80.0))
        tr.tick(120.0, False, _s(soc=79.0))
        rec = tr._record()
        assert rec["soc_start"] == pytest.approx(95.0)
        assert rec["soc_morning"] == pytest.approx(80.0)

    def test_soc_never_available_refuses_the_night(self):
        tr = BatteryNightTracker(reserve_soc=20.0)
        tr.start("2026-08-18", outdoor_temp_c=None)
        tr.tick(0.0, True, _s(soc_available=False))
        tr.tick(60.0, True, _s(soc_available=False))
        tr.tick(120.0, False, _s())
        rec = tr._record()
        assert rec["trainable"] is False


class TestDayPhase:

    def _through_night(self):
        tr = BatteryNightTracker(reserve_soc=20.0)
        tr.start("2026-08-18", outdoor_temp_c=None)
        tr.tick(0.0, True, _s(home=500.0, soc=80.0))
        tr.tick(60.0, False, _s(soc=79.0))      # day begins
        return tr

    def test_forecast_promise_captured_once_at_day_start(self):
        tr = self._through_night()
        tr.set_forecast_kwh(31.5)
        tr.set_forecast_kwh(99.0)               # later restatement ignored
        tr.tick(120.0, False, _s(soc=80.0))
        tr.tick(180.0, True, _s(soc=90.0))      # next night → seal
        rec = tr.sealed()[-1]
        assert rec["forecast_kwh"] == pytest.approx(31.5)

    def test_refill_full_at_is_first_full_timestamp(self):
        tr = self._through_night()
        tr.tick(1000.0, False, _s(soc=98.0))
        tr.tick(2000.0, False, _s(soc=FULL_SOC + 0.2))
        tr.tick(3000.0, False, _s(soc=100.0))
        tr.tick(4000.0, True, _s())
        rec = tr.sealed()[-1]
        assert rec["refill_full_at"] == pytest.approx(2000.0)

    def test_never_full_records_none(self):
        tr = self._through_night()
        tr.tick(1000.0, False, _s(soc=90.0))
        tr.tick(2000.0, True, _s())
        assert tr.sealed()[-1]["refill_full_at"] is None

    def test_clipping_counts_only_full_and_exporting(self):
        tr = self._through_night()
        t = 120.0
        while t <= 120.0 + 3600.0:              # 1 h full + exporting
            tr.tick(t, False, _s(soc=99.8, export=1500.0))
            t += 60.0
        while t <= 120.0 + 7200.0:              # 1 h full, NO export
            tr.tick(t, False, _s(soc=99.8, export=0.0))
            t += 60.0
        tr.tick(t, True, _s())
        rec = tr.sealed()[-1]
        assert rec["clipped_hours"] == pytest.approx(1.0, rel=0.05)


class TestLifecycle:

    def test_seal_happens_at_day_to_night_flip_with_night_date_key(self):
        tr = BatteryNightTracker(reserve_soc=20.0)
        tr.start("2026-08-18", outdoor_temp_c=7.5)
        tr.tick(0.0, True, _s(home=500.0, soc=70.0))
        tr.tick(60.0, False, _s(soc=69.0))
        assert tr.sealed() == []                 # day running — not sealed yet
        tr.tick(120.0, True, _s(soc=69.0))
        assert len(tr.sealed()) == 1
        assert tr.sealed()[0]["date"] == "2026-08-18"
        assert tr.sealed()[0]["outdoor_temp_c"] == pytest.approx(7.5)

    def test_sealed_history_is_capped(self):
        tr = BatteryNightTracker(reserve_soc=20.0, max_nights=3)
        for i in range(5):
            tr.start(f"2026-08-{10 + i}", outdoor_temp_c=None)
            tr.tick(i * 1000.0, True, _s(soc=70.0))
            tr.tick(i * 1000.0 + 60.0, False, _s(soc=69.0))
            tr.tick(i * 1000.0 + 120.0, True, _s(soc=69.0))
        assert len(tr.sealed()) == 3
        assert tr.sealed()[-1]["date"] == "2026-08-14"

    def test_state_round_trip_mid_night(self):
        tr = BatteryNightTracker(reserve_soc=20.0)
        tr.start("2026-08-18", outdoor_temp_c=3.0)
        tr.tick(0.0, True, _s(home=1000.0, soc=88.0))
        tr.tick(60.0, True, _s(home=1000.0, soc=87.0))
        state = tr.to_dict()
        tr2 = BatteryNightTracker(reserve_soc=20.0)
        tr2.from_dict(state)
        tr2.tick(120.0, True, _s(home=1000.0, soc=86.0))
        tr2.tick(180.0, False, _s())
        rec = tr2._record()
        assert rec["drain_kwh"] > 0.03           # both halves counted
        assert rec["soc_start"] == pytest.approx(88.0)
        assert rec["outdoor_temp_c"] == pytest.approx(3.0)


class TestCoordinatorWiring:
    """The real ``_record_battery_night`` on a stub host (house pattern:
    test_743_probe_observability's _GrantStub)."""

    def _host(self, *, night):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )

        h = SimpleNamespace()
        h._record_battery_night = SEMCoordinator._record_battery_night.__get__(h)
        h._outdoor_temp_c = SEMCoordinator._outdoor_temp_c.__get__(h)
        h.config = {"battery_reserve_soc": 20}
        h.time_manager = SimpleNamespace(is_night_mode=lambda: night["v"])
        h._cycle_forecast = SimpleNamespace(
            available=True, forecast_today_kwh=28.0)
        h._forecast_tracker = SimpleNamespace(
            apply_dampening=lambda kwh: kwh * 0.9)
        h._storage = MagicMock()
        h._storage.get_battery_night_state.return_value = {}
        from unittest.mock import AsyncMock
        h._storage.async_save_energy_throttled = AsyncMock()
        wst = SimpleNamespace(
            entity_id="weather.home", attributes={"temperature": 11.5})
        h.hass = SimpleNamespace(
            states=SimpleNamespace(async_all=lambda _d: [wst]))
        return h

    def test_a_full_night_records_and_persists_on_seal(self):
        from types import SimpleNamespace
        night = {"v": True}
        h = self._host(night=night)
        power = SimpleNamespace(
            battery_soc=85.0, battery_soc_unavailable=False,
            grid_export_power=0.0, battery_power_unavailable=False)
        flows = SimpleNamespace(
            battery_to_home=600.0, battery_to_ev=0.0, battery_to_grid=0.0)
        import asyncio
        run = lambda: asyncio.run(h._record_battery_night(power, flows))
        run()                                            # opens the night
        run()
        assert h._battery_night.phase == "night"
        assert h._battery_night._temp_c == pytest.approx(11.5)

        night["v"] = False                              # morning
        run()
        assert h._battery_night.phase == "day"
        # dampened promise captured: 28.0 × 0.9
        assert h._battery_night._forecast_kwh == pytest.approx(25.2)

        night["v"] = True                               # next night → seal
        run()
        h._storage.set_battery_night_state.assert_called()
        sealed = h._battery_night.sealed()
        assert len(sealed) == 1
        assert sealed[0]["outdoor_temp_c"] == pytest.approx(11.5)
        assert sealed[0]["forecast_kwh"] == pytest.approx(25.2)


class TestSpecCoverage778:
    """The two record fields the #778 spec demands beyond the flows.

    Overnight HOUSE need is drain + what the GRID supplied meanwhile — a
    night where the battery sat at reserve under-observes the need via
    battery_to_home alone. And the refill promise decomposes only if the
    day's house consumption is on the record (PV-wrong vs
    consumption-wrong are different lessons)."""

    def test_night_grid_supply_is_recorded_beside_the_drain(self):
        tr = BatteryNightTracker(reserve_soc=20.0)
        tr.start("2026-08-18", outdoor_temp_c=None)
        t = 0.0
        while t <= 3600.0:
            tr.tick(t, True, _s(home=400.0, grid_home=800.0))
            t += 60.0
        tr.tick(t, False, _s())
        rec = tr._record()
        assert rec["drain_kwh"] == pytest.approx(0.4, rel=0.03)
        assert rec["night_grid_kwh"] == pytest.approx(0.8, rel=0.03)

    def test_day_home_consumption_is_recorded(self):
        tr = BatteryNightTracker(reserve_soc=20.0)
        tr.start("2026-08-18", outdoor_temp_c=None)
        tr.tick(0.0, True, _s(soc=80.0))
        tr.tick(60.0, False, _s(soc=79.0))
        t = 120.0
        while t <= 120.0 + 3600.0:
            tr.tick(t, False, _s(soc=85.0, home_total=1500.0))
            t += 60.0
        tr.tick(t, True, _s())
        rec = tr.sealed()[-1]
        assert rec["day_home_kwh"] == pytest.approx(1.5, rel=0.03)


class TestMorningVerdictLine:
    """(#800 commit 2) The battery sentence in the morning review —
    codes + numbers out, prose stays on the card (#755 pillar 4 rules:
    silence about the trivial, silence when untrainable)."""

    def _rec(self, **kw):
        base = {
            "date": "2026-08-18", "drain_kwh": 4.2, "assist_kwh": 0.0,
            "export_kwh": 0.0, "night_grid_kwh": 0.0, "day_home_kwh": 9.0,
            "soc_start": 90.0, "soc_morning": 62.0, "reserve_hit": False,
            "gap_s": 0.0, "trainable": True, "refill_full_at": None,
            "clipped_hours": 0.0, "forecast_kwh": 30.0,
            "outdoor_temp_c": 12.0,
        }
        base.update(kw)
        return base

    def test_clipping_wins_the_verdict(self):
        from custom_components.solar_energy_management.coordinator.demand_review import (
            review_battery_night,
        )
        v = review_battery_night(self._rec(
            refill_full_at=1755500000.0, clipped_hours=3.4))
        assert v["code"] == "batt_clipped"
        assert v["drained"] == pytest.approx(4.2)
        assert v["clipped_h"] == pytest.approx(3.4)

    def test_refilled_reports_the_full_timestamp(self):
        from custom_components.solar_energy_management.coordinator.demand_review import (
            review_battery_night,
        )
        v = review_battery_night(self._rec(refill_full_at=1755500000.0))
        assert v["code"] == "batt_refilled"
        assert v["full_at_ts"] == pytest.approx(1755500000.0)

    def test_a_promised_refill_that_never_came_is_short(self):
        from custom_components.solar_energy_management.coordinator.demand_review import (
            review_battery_night,
        )
        v = review_battery_night(self._rec())
        assert v["code"] == "batt_short"

    def test_untrainable_nights_stay_silent(self):
        from custom_components.solar_energy_management.coordinator.demand_review import (
            review_battery_night,
        )
        assert review_battery_night(self._rec(trainable=False)) is None
        assert review_battery_night(None) is None

    def test_a_trivial_night_stays_silent(self):
        from custom_components.solar_energy_management.coordinator.demand_review import (
            review_battery_night,
        )
        v = review_battery_night(self._rec(
            drain_kwh=0.2, forecast_kwh=None, clipped_hours=0.0))
        assert v is None


class TestPersistenceAndFreshness:
    """Two gaps found verifying beta.9 on PROD.

    1. The night was persisted ONLY at seal — a restart mid-night dropped
       everything accumulated, which is exactly the silent-regression the
       #755 store note warns about (and the reason to_dict/from_dict and
       its round-trip test exist at all).
    2. The verdict read only SEALED records, and a record seals when the
       NEXT night begins — so last night's battery row would appear on
       the card in the evening. A morning verdict has to be readable in
       the morning: once the night half is complete (day phase) the open
       record already answers drained/refilled/clipped-so-far.
    """

    def test_the_open_night_is_readable_once_the_night_half_is_done(self):
        tr = BatteryNightTracker(reserve_soc=20.0)
        tr.start("2026-08-19", outdoor_temp_c=None)
        assert tr.current_record() is None          # mid-night: not yet
        tr.tick(0.0, True, _s(home=900.0, soc=80.0))
        tr.tick(60.0, True, _s(home=900.0, soc=79.0))
        assert tr.current_record() is None
        tr.tick(120.0, False, _s(soc=79.0))         # morning flip
        rec = tr.current_record()
        assert rec is not None
        assert rec["drain_kwh"] > 0
        assert rec["date"] == "2026-08-19"

    def test_current_record_clears_when_the_next_night_opens(self):
        tr = BatteryNightTracker(reserve_soc=20.0)
        tr.start("2026-08-19", outdoor_temp_c=None)
        tr.tick(0.0, True, _s(home=900.0, soc=80.0))
        tr.tick(60.0, False, _s(soc=79.0))
        assert tr.current_record() is not None
        tr.tick(120.0, True, _s(soc=79.0))          # seals → new night
        assert tr.current_record() is None
        assert len(tr.sealed()) == 1


class TestCoordinatorPersistsEveryCycle:

    def test_a_mid_night_cycle_persists_the_open_record(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )

        h = SimpleNamespace()
        h._record_battery_night = SEMCoordinator._record_battery_night.__get__(h)
        h._outdoor_temp_c = SEMCoordinator._outdoor_temp_c.__get__(h)
        h.config = {"battery_reserve_soc": 20}
        h.time_manager = SimpleNamespace(is_night_mode=lambda: True)
        h._cycle_forecast = SimpleNamespace(available=False)
        h._forecast_tracker = SimpleNamespace(apply_dampening=lambda k: k)
        h._storage = MagicMock()
        h._storage.get_battery_night_state.return_value = {}
        from unittest.mock import AsyncMock
        h._storage.async_save_energy_throttled = AsyncMock()
        h.hass = SimpleNamespace(states=SimpleNamespace(async_all=lambda _d: []))
        power = SimpleNamespace(
            battery_soc=70.0, battery_soc_unavailable=False,
            grid_export_power=0.0, battery_power_unavailable=False,
            home_consumption_power=0.0)
        flows = SimpleNamespace(
            battery_to_home=800.0, battery_to_ev=0.0, battery_to_grid=0.0,
            grid_to_home=0.0)

        import asyncio
        asyncio.run(h._record_battery_night(power, flows))
        asyncio.run(h._record_battery_night(power, flows))
        # No seal has happened, yet the night must already be durable.
        assert h._storage.set_battery_night_state.called, (
            "a restart mid-night would lose the record")


class TestTheNightActuallyReachesDisk:
    """(#800 round 3, found live on .175 mid-night) set_battery_night_state
    mutated memory and nothing ever scheduled a WRITE — the energy store's
    delayed save re-arms on every call under the continuous update loop, so
    it only fires at a graceful stop (the async_save_energy_now docstring
    documents this exact trap, twice). A record whose whole point is
    surviving an unclean reboot cannot depend on a clean one. The fix is
    the house's throttled-real-write pattern: at most one disk write per
    interval, bounding unclean-reboot loss to that interval."""

    def test_storage_has_a_throttled_energy_save(self):
        import asyncio, time
        from unittest.mock import AsyncMock, MagicMock
        from custom_components.solar_energy_management.coordinator.storage import (
            SEMStorage,
        )
        st = SEMStorage.__new__(SEMStorage)
        st._energy_data = {"battery_nights": {"phase": "night"}}
        st._energy_store = MagicMock()
        st._energy_store.async_save = AsyncMock()
        st._last_energy_save_ts = 0.0
        asyncio.run(st.async_save_energy_throttled())
        asyncio.run(st.async_save_energy_throttled())   # inside the window
        assert st._energy_store.async_save.await_count == 1
        st._last_energy_save_ts = time.monotonic() - 10_000
        asyncio.run(st.async_save_energy_throttled())
        assert st._energy_store.async_save.await_count == 2

    def test_the_recorder_schedules_the_write_mid_night(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )

        h = SimpleNamespace()
        h._record_battery_night = SEMCoordinator._record_battery_night.__get__(h)
        h._outdoor_temp_c = SEMCoordinator._outdoor_temp_c.__get__(h)
        h.config = {"battery_reserve_soc": 20}
        h.time_manager = SimpleNamespace(is_night_mode=lambda: True)
        h._cycle_forecast = SimpleNamespace(available=False)
        h._forecast_tracker = SimpleNamespace(apply_dampening=lambda k: k)
        h._storage = MagicMock()
        h._storage.get_battery_night_state.return_value = {}
        h._storage.async_save_energy_throttled = AsyncMock()
        h.hass = SimpleNamespace(states=SimpleNamespace(async_all=lambda _d: []))
        power = SimpleNamespace(
            battery_soc=70.0, battery_soc_unavailable=False,
            grid_export_power=0.0, battery_power_unavailable=False,
            home_consumption_power=0.0)
        flows = SimpleNamespace(
            battery_to_home=800.0, battery_to_ev=0.0, battery_to_grid=0.0,
            grid_to_home=0.0)
        asyncio.run(h._record_battery_night(power, flows))
        asyncio.run(h._record_battery_night(power, flows))
        assert h._storage.async_save_energy_throttled.await_count >= 1, (
            "mid-night, memory-only: an unclean reboot loses the night")
