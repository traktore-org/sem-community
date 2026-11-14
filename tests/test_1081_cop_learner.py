"""(#1081) The COP learned from a heat meter.

A synthetic winter: a pump whose true COP follows a known curve, read every
minute for 60 days with the noise a real install has — standby hours, short
runs, defrost, hot water, a counter reset, unread meters, restarts. The
learner must find the curve within 0.2 at -7, 2 and 12 °C, and nothing it
learns may act until the user picks it.
"""
from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator import cop_learner as cl
from custom_components.solar_energy_management.coordinator.heat_cost import (
    device_cop_at, device_has_cop_shape, learned_curve_of)


def true_cop(t: float) -> float:
    # a real air-to-water shape: 2.3 at -10, 3.2 at 2, 4.4 at 15
    return 3.2 + 0.075 * (t - 2.0) - 0.0012 * (t - 2.0) ** 2


def _winter(days=60, seed=1081, restart_every_h=97):
    """Feed a learner minute by minute; return the final state."""
    rng = random.Random(seed)
    state = cl.new_state()
    elec = 1000.0
    heat = 3000.0
    start = datetime(2026, 12, 1)
    for h in range(days * 24):
        ts = start + timedelta(hours=h)
        # outdoor: seasonal drift + day swing, -12 … 16 °C
        t_out = (2.0 + 9.0 * math.sin(h / (24 * 9.0))
                 + 4.0 * math.sin((ts.hour - 9) / 24 * 2 * math.pi))
        kind = rng.random()
        hot_water = kind < 0.06
        defrost = 0.06 <= kind < 0.11
        standby = 0.11 <= kind < 0.25
        short = 0.25 <= kind < 0.30
        unread = 0.30 <= kind < 0.32
        if h == 700:
            heat = 0.0              # the heat meter was replaced
        hour_id = 500_000 + h          # whole hours, as the coordinator passes
        for m in range(60):
            running = not standby and (not short or m < 12)
            p_kw = 2.0 if running else 0.005
            cop = true_cop(t_out) * rng.uniform(0.97, 1.03)
            if hot_water:
                cop = 2.2
            if defrost and 20 <= m < 30:
                cop = -0.5          # heat taken back from the house
            elec += p_kw / 60.0
            heat += max(p_kw * cop / 60.0, -0.02) if running else 0.0
            heat = max(heat, 0.0)
            e_in, h_in = elec, heat
            if unread and m == 30:
                e_in = None
            state = cl.observe(state, hour_id=hour_id, elec_kwh=e_in,
                               heat_kwh=h_in, outdoor_c=t_out,
                               running=running)
            # (SEM cannot tell a hot-water hour: it is NOT flagged here, as
            # the coordinator does not flag it — the median must carry it)
        if restart_every_h and h % restart_every_h == 0:
            # a restart: the store round-trips through JSON
            state = json.loads(json.dumps(state))
    return state


@pytest.fixture(scope="module")
def winter():
    return _winter()


class TestASyntheticWinter:
    def test_the_curve_is_found_within_0_2(self, winter):
        pts = cl.learned_points(winter)
        assert len(pts) >= 8, pts
        dev = SimpleNamespace(cop=3.0, cop_curve=None, cop_source="learned",
                              cop_learned=pts)
        for t in (-7.0, 2.0, 12.0):
            cop, src = device_cop_at(dev, t)
            assert src == "learned"
            assert abs(cop - true_cop(t)) <= 0.2, (t, cop, true_cop(t))

    def test_each_kind_of_noise_is_left_out(self, winter):
        rej = winter["rejected"]
        for why in ("standby", "short_run", "reset", "unread"):
            assert rej.get(why, 0) > 0, (why, rej)

    def test_the_store_stays_small(self, winter):
        n = sum(len(s) for s in winter["bins"].values())
        assert n <= len(winter["bins"]) * cl.MAX_SAMPLES_PER_BIN
        assert len(json.dumps(winter)) < 40_000

    def test_the_summary_says_what_the_card_shows(self, winter):
        s = cl.summary(winter, has_meter=True)
        assert s["state"] == cl.LEARNED
        assert s["hours"] > 100
        assert s["tmin"] < 0 < s["tmax"]


class TestOneHour:
    def _hour(self, state, hour, e0, e1, h0, h1, t=5.0, running=True, n=6):
        for i in range(n):
            f = i / (n - 1)
            state = cl.observe(state, hour_id=hour, elec_kwh=e0 + (e1 - e0) * f,
                               heat_kwh=h0 + (h1 - h0) * f, outdoor_c=t,
                               running=running)
        return state

    def test_a_clean_hour_is_one_sample_when_the_next_begins(self):
        s = self._hour(cl.new_state(), "h1", 0, 1.0, 0, 3.5)
        assert s["bins"] == {}
        s = cl.observe(s, hour_id="h2", elec_kwh=1.0, heat_kwh=3.5,
                       outdoor_c=5, running=True)
        assert s["bins"] == {"4": [[5.0, 3.5]]}

    @pytest.mark.parametrize("cop", [0.6, 8.5])
    def test_an_impossible_cop_is_a_glitch(self, cop):
        s = self._hour(cl.new_state(), "h1", 0, 1.0, 0, cop)
        s = cl.observe(s, hour_id="h2", elec_kwh=1.0, heat_kwh=cop,
                       outdoor_c=5, running=True)
        assert s["bins"] == {} and s["rejected"] == {"implausible": 1}

    def test_no_outdoor_temperature_is_no_sample(self):
        s = self._hour(cl.new_state(), "h1", 0, 1.0, 0, 3.5, t=None)
        s = cl.observe(s, hour_id="h2", elec_kwh=1.0, heat_kwh=3.5,
                       outdoor_c=None, running=True)
        assert s["bins"] == {} and s["rejected"] == {"unread": 1}

    def test_six_hours_make_a_bin_trusted(self):
        s = cl.new_state()
        for i in range(cl.TRUST_HOURS - 1):
            s = self._hour(s, f"h{i}", i, i + 1.0, 3 * i, 3 * i + 3.0)
        s = cl.observe(s, hour_id="z", elec_kwh=cl.TRUST_HOURS - 1.0,
                       heat_kwh=3 * (cl.TRUST_HOURS - 1.0), outdoor_c=5,
                       running=True)
        assert cl.learned_points(s) == []
        assert cl.summary(s, has_meter=True)["state"] == cl.NOT_ENOUGH
        s = self._hour(s, "z", cl.TRUST_HOURS - 1.0, float(cl.TRUST_HOURS),
                       3 * (cl.TRUST_HOURS - 1.0), 3.0 * cl.TRUST_HOURS)
        s = cl.observe(s, hour_id="zz", elec_kwh=float(cl.TRUST_HOURS),
                       heat_kwh=3.0 * cl.TRUST_HOURS, outdoor_c=5, running=True)
        assert cl.learned_points(s) == [(5.0, 3.0)]

    def test_a_broken_store_starts_fresh(self):
        for junk in (None, [], "x", {"v": 99}):
            assert cl.observe(junk, hour_id="h", elec_kwh=1, heat_kwh=1,
                              outdoor_c=1, running=True)["v"] == cl.STATE_VERSION

    def test_no_meter_says_so(self):
        assert cl.summary(None, has_meter=False)["state"] == cl.NO_METER


class TestNothingActsUntilPicked:
    PTS = [(-6.0, 2.4), (2.0, 3.2), (10.0, 4.1)]

    def test_never_picked_is_todays_behaviour(self):
        flat = SimpleNamespace(cop=3.0, cop_curve=None, cop_source="",
                               cop_learned=self.PTS)
        assert device_cop_at(flat, -6.0) == (3.0, "flat")
        assert not device_has_cop_shape(flat)
        curve = [(-7.0, 2.5), (12.0, 4.2)]
        mine = SimpleNamespace(cop=3.0, cop_curve=curve, cop_source="",
                               cop_learned=self.PTS)
        assert device_cop_at(mine, -7.0) == (2.5, "curve")

    def test_flat_picked_ignores_both_curves(self):
        dev = SimpleNamespace(cop=3.0, cop_curve=[(-7.0, 2.5), (12.0, 4.2)],
                              cop_source="flat", cop_learned=self.PTS)
        assert device_cop_at(dev, -7.0) == (3.0, "flat")
        assert not device_has_cop_shape(dev)

    def test_learned_with_too_few_points_falls_back(self):
        dev = SimpleNamespace(cop=3.0, cop_curve=None, cop_source="learned",
                              cop_learned=[(2.0, 3.2)])
        assert learned_curve_of(dev) is None
        assert device_cop_at(dev, 2.0) == (3.0, "flat")

    def test_outside_what_it_learned_the_users_curve_answers(self):
        dev = SimpleNamespace(cop=3.0, cop_curve=[(-15.0, 1.9), (12.0, 4.2)],
                              cop_source="learned", cop_learned=self.PTS)
        assert device_cop_at(dev, 2.0) == (3.2, "learned")
        cop, src = device_cop_at(dev, -15.0)
        assert (cop, src) == (1.9, "curve")
        # without a curve of the user's, the learned end holds
        dev.cop_curve = None
        assert device_cop_at(dev, -15.0) == (2.4, "learned")


def _hours(s, n, *, e0=0.0, h0=0.0, cop=3.0, t=3.0, start=0, heat_of=None):
    """n whole hours, six readings each; ``heat_of(e)`` overrides the meter."""
    e, h = e0, h0
    for k in range(n):
        for i in range(6):
            e = e0 + (k * 6 + i) * 0.2
            h = heat_of(e) if heat_of else h0 + (e - e0) * cop
            s = cl.observe(s, hour_id=start + k, elec_kwh=e, heat_kwh=h,
                           outdoor_c=t, running=True)
    return cl.observe(s, hour_id=start + n, elec_kwh=e + 0.2,
                      heat_kwh=heat_of(e + 0.2) if heat_of else h + 0.2 * cop,
                      outdoor_c=t, running=True)


class TestReviewFindings:
    """(#1081 review) what a wrong or coarse meter must not teach."""

    def test_an_electricity_meter_as_heat_meter_learns_nothing(self):
        # COP 1.0: the heat meter counts what the electricity meter counts
        s = _hours(cl.new_state(), 12, cop=1.0, t=3.0)
        s = _hours(s, 12, cop=1.02, t=9.0, start=12, e0=50.0, h0=50.0)
        assert cl.learned_points(s) == []
        summ = cl.summary(s, has_meter=True)
        assert summ["state"] == cl.LOOKS_ELECTRIC
        assert summ["points"] == []

    def test_a_coarse_heat_counter_is_not_learned_from(self):
        # whole-kWh heat counter: hours swing 0 / 2 / 3 kWh for 1.2 kWh used
        s = _hours(cl.new_state(), 30, cop=3.0,
                   heat_of=lambda e: float(math.floor(e * 3.0)))
        assert cl.learned_points(s) == []
        assert s["rejected"].get("coarse_meter", 0) > 0

    def test_a_fine_counter_still_learns(self):
        s = _hours(cl.new_state(), 8, cop=3.0,
                   heat_of=lambda e: round(e * 3.0, 2))
        assert cl.learned_points(s) == [(3.0, 3.0)]

    def test_the_hour_after_a_stalled_heat_counter_is_dropped(self):
        # the heat counter sends nothing for an hour, then catches up
        def lazy(e):
            return 3.0 * (1.2 if 1.2 <= e < 2.6 else e)
        s = _hours(cl.new_state(), 3, heat_of=lazy)
        assert s["bins"] == {} or all(
            abs(c - 3.0) < 0.05 for b in s["bins"].values() for _, c in b)
        assert s["rejected"].get("lagging_meter", 0) >= 1

    def test_a_corrupt_store_starts_fresh_instead_of_failing(self):
        for bad in ({"v": 1, "bins": []}, {"v": 1, "bins": {"2": "x"}},
                    {"v": 1, "bins": {"2": [["a", 3]]}}, {"v": 1, "rejected": 5},
                    {"v": 1, "hour": "x"}):
            s = cl.observe(bad, hour_id=1, elec_kwh=0, heat_kwh=0,
                           outdoor_c=3, running=True)
            cl.summary(s, has_meter=True)
            cl.learned_points(s)

    def test_observe_takes_no_hot_water_flag(self):
        # SEM cannot tell a hot-water hour; no flag pretends it can
        import inspect
        assert "dhw" not in inspect.signature(cl.observe).parameters


class TestWhatTheCoordinatorAdds:
    def _hour(self, s, hid, e0, h0, cop=3.0, t=5.0, meter=None):
        for i in range(6):
            s = cl.observe(s, hour_id=hid, elec_kwh=e0 + i * 0.2,
                           heat_kwh=h0 + i * 0.2 * cop, outdoor_c=t,
                           running=True, meter=meter)
        return s

    def test_a_missed_hour_drops_the_hour_before_it(self):
        s = self._hour(cl.new_state(), 10, 0.0, 0.0)
        # readings resume two hours later: the counters jumped by the gap
        s = cl.observe(s, hour_id=12, elec_kwh=5.0, heat_kwh=30.0, outdoor_c=5,
                       running=True)
        assert s["bins"] == {} and s["rejected"] == {"gap": 1}

    def test_the_next_hour_closes_it(self):
        s = self._hour(cl.new_state(), 10, 0.0, 0.0)
        s = cl.observe(s, hour_id=11, elec_kwh=1.2, heat_kwh=3.6, outdoor_c=5,
                       running=True)
        assert s["bins"] == {"4": [[5.0, 3.0]]}

    def test_another_meter_starts_fresh(self):
        s = self._hour(cl.new_state(), 10, 0.0, 0.0, meter="sensor.a")
        s = self._hour(s, 11, 1.2, 3.6, meter="sensor.a")
        assert s["bins"]
        s = cl.observe(s, hour_id=12, elec_kwh=2.4, heat_kwh=0.0, outdoor_c=5,
                       running=True, meter="sensor.b")
        assert s["bins"] == {} and s["meter"] == "sensor.b"

    @pytest.mark.parametrize("bad", [-999.0, 85.0, float("nan")])
    def test_a_broken_thermometer_is_no_reading(self, bad):
        s = self._hour(cl.new_state(), 10, 0.0, 0.0, t=bad)
        s = cl.observe(s, hour_id=11, elec_kwh=1.2, heat_kwh=3.6, outdoor_c=bad,
                       running=True)
        assert s["bins"] == {} and s["rejected"] == {"unread": 1}
