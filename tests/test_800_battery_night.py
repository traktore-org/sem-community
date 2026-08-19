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
        h._record_battery_night(power, flows)          # opens the night
        h._record_battery_night(power, flows)
        assert h._battery_night.phase == "night"
        assert h._battery_night._temp_c == pytest.approx(11.5)

        night["v"] = False                              # morning
        h._record_battery_night(power, flows)
        assert h._battery_night.phase == "day"
        # dampened promise captured: 28.0 × 0.9
        assert h._battery_night._forecast_kwh == pytest.approx(25.2)

        night["v"] = True                               # next night → seal
        h._record_battery_night(power, flows)
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
