"""(#1081) A stuck outdoor thermometer taught the learner a wrong COP.

On the test machine SEM read a thermometer that stood at 11.8 °C for two
days while the real weather ran from -1 to 8 °C. Every hour landed in one
temperature bin, and its "learned" COP (3.49) was a mix of all weather —
0.33 under the true value there. Now 12 hours with the same mean and no
fresh report are not samples, and the card says the thermometer is stuck.
"""
from __future__ import annotations

from custom_components.solar_energy_management.coordinator import cop_learner as cl


def _feed(s, hours, *, t, cop=3.0, age=None, start=0, e0=0.0, h0=0.0):
    """Whole clean hours, six readings each: 1.2 kWh in, cop × 1.2 kWh out."""
    n = 0
    for i in range(hours):
        temp = t(start + i) if callable(t) else t
        for _ in range(6):
            s = cl.observe(s, hour_id=start + i, elec_kwh=round(e0 + n * 0.2, 3),
                           heat_kwh=round(h0 + n * 0.2 * cop, 3),
                           outdoor_c=temp, running=True, outdoor_age_s=age)
            n += 1
    e, h = round(e0 + n * 0.2, 3), round(h0 + n * 0.2 * cop, 3)
    s = cl.observe(s, hour_id=start + hours, elec_kwh=e, heat_kwh=h,
                   outdoor_c=t(start + hours) if callable(t) else t,
                   running=True, outdoor_age_s=age)
    return s, e, h


def test_a_thermometer_that_never_moves_teaches_nothing():
    s, _, _ = _feed(None, 30, t=11.8, age=20 * 3600.0)
    assert cl.learned_points(s) == []
    out = cl.summary(s, has_meter=True)
    assert out["state"] == cl.NOT_ENOUGH and out["temp_stuck"] is True
    assert out["rejected"]["temperature_stuck"] >= 18
    assert out["hours"] == 0                       # the first 11 were taken out


def test_without_a_report_time_it_is_never_called_stuck():
    s, _, _ = _feed(None, 30, t=11.8, age=None)
    assert cl.learned_points(s) == [(11.8, 3.0)]
    assert "temp_stuck" not in cl.summary(s, has_meter=True)


def test_a_live_source_that_repeats_whole_degrees_still_teaches():
    """A weather service rounds to 1 °C and reports every hour: a foggy day
    at 0 °C is real, and it is the cold weather worth learning."""
    s, _, _ = _feed(None, 30, t=0.0, age=1200.0)
    assert cl.learned_points(s) == [(0.0, 3.0)]
    assert "temp_stuck" not in cl.summary(s, has_meter=True)


def test_a_moving_thermometer_is_never_called_stuck():
    s, _, _ = _feed(None, 48, t=lambda i: 3.0 + (i % 5) * 0.3)
    assert cl.summary(s, has_meter=True)["state"] == cl.LEARNED
    assert not cl.summary(s, has_meter=True)["rejected"].get("temperature_stuck")


def test_it_learns_again_when_the_thermometer_moves():
    s, e, h = _feed(None, 20, t=11.8, age=20 * 3600.0)
    assert cl.summary(s, has_meter=True).get("temp_stuck")
    s, _, _ = _feed(s, 8, t=lambda i: 4.0 + (i % 3) * 0.2, start=20, e0=e, h0=h, age=60.0)
    out = cl.summary(s, has_meter=True)
    assert "temp_stuck" not in out and out["state"] == cl.LEARNED
    assert all(t != 11.8 for t, _ in out["points"])


def test_good_samples_from_before_it_stuck_are_kept():
    s, e, h = _feed(None, 8, t=lambda i: 11.0 + (i % 4) * 0.2, age=60.0)
    before = cl.learned_points(s)
    assert before
    s, _, _ = _feed(s, 20, t=11.8, start=8, e0=e, h0=h, age=20 * 3600.0, cop=2.0)
    pts = cl.learned_points(s)
    assert pts and abs(pts[0][1] - 3.0) < 0.05, pts   # the cop 2.0 hours are gone


def test_an_older_good_day_at_the_same_value_is_kept():
    s, e, h = _feed(None, 5, t=5.0, age=60.0)
    s, e, h = _feed(s, 3, t=6.3, start=5, e0=e, h0=h, age=60.0)
    s, _, _ = _feed(s, 14, t=5.0, start=8, e0=e, h0=h, age=20 * 3600.0, cop=2.0)
    # the five good hours at 5.0 stay; none of the stuck run's hours do
    assert [c for t, c in s["bins"]["4"] if t == 5.0] == [3.0] * 5


def test_a_full_bin_loses_nothing_to_a_stuck_run():
    s, e, h = _feed(None, 30, t=lambda i: 5.0 if i % 2 else 5.1, age=60.0)
    before = [list(x) for x in s["bins"]["4"]]
    assert len(before) == cl.MAX_SAMPLES_PER_BIN
    s, _, _ = _feed(s, 20, t=5.0, start=30, e0=e, h0=h, age=20 * 3600.0, cop=2.0)
    after = s["bins"]["4"]
    # the hour the run began in had a fresh report and is one real sample;
    # none of the stuck hours (cop 2.0) is in, and no older sample left for them
    assert after[:-1] == before[1:] and not [x for x in after[:-1] if x[1] < 2.5]


def test_a_calm_night_that_ends_keeps_its_hours():
    """Eight equal hours without a fresh report, then the value moves: the
    held hours were real and become samples."""
    s, e, h = _feed(None, 8, t=2.0, age=20 * 3600.0)
    s, _, _ = _feed(s, 3, t=lambda i: 2.4 + (i - 8) * 0.5, start=8, e0=e, h0=h, age=20 * 3600.0)
    assert len(s["bins"]["2"]) >= 8 and len(s.get("t_pending") or []) <= 1


def test_the_state_survives_json_with_held_hours():
    import json
    s, _, _ = _feed(None, 6, t=2.0, age=20 * 3600.0)
    assert s.get("t_pending")
    again = cl._valid(json.loads(json.dumps(s)))
    assert again.get("t_pending") == s["t_pending"] and again["bins"] == s["bins"]


def test_the_same_value_on_both_sides_of_a_gap_is_not_one_run():
    s, e, h = _feed(None, 8, t=5.0, age=20 * 3600.0)
    s, _, _ = _feed(s, 8, t=5.0, start=30, e0=e, h0=h, age=20 * 3600.0)
    assert not cl.summary(s, has_meter=True)["rejected"].get("temperature_stuck")


def test_a_store_with_a_bad_counter_starts_fresh():
    s, _, _ = _feed(None, 3, t=5.0)
    s["t_same"] = "many"
    assert cl.summary(s, has_meter=True)["hours"] == 0


def test_the_card_text_exists_in_every_language():
    import json
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    d = json.loads((root / "dashboard" / "translations.json").read_text())
    key = "hp_cop_" + "temp_stuck"
    assert all(d[lang].get(key) for lang in d)
