"""#1083 — a recorded day: anonymised, resampled, dark stays dark."""
import gzip
from datetime import datetime
from zoneinfo import ZoneInfo

from custom_components.solar_energy_management.tools.replay.recorded_day import (
    ROLES,
    corpus_days,
    from_history,
    load_day,
    save_day,
)

TZ = "Europe/Zurich"
D0 = datetime(2026, 10, 13, tzinfo=ZoneInfo(TZ)).timestamp()


def _day(tags=None, date="2026-10-13"):
    return from_history(date, TZ, {
        "solar_power": [(D0 + 9 * 3600, "800"), (D0 + 11 * 3600, "unavailable"),
                        (D0 + 11 * 3600 + 1800, "900")],
        "grid_power": [(D0, "-600")],
        "some_private_entity_of_the_house": [(D0, "42")],
    }, tags=tags)


def test_unknown_entities_never_reach_a_corpus_day():
    d = _day()
    assert set(d.series) == {"solar_power", "grid_power"}
    assert set(d.series) <= set(ROLES)


def test_resampling_is_sticky_and_dark_stays_dark():
    d = _day()
    by_h = {round(d.local_hour(c.t), 2): c for c in d.cycles(cycle_s=600)}
    assert by_h[8.0].values["solar_power"] is None        # nothing yet
    assert by_h[10.0].values["solar_power"] == 800.0      # sticky
    assert by_h[11.17].dark("solar_power")                # dark, not 0 W
    assert by_h[12.0].values["solar_power"] == 900.0
    assert by_h[12.0].values["grid_power"] == -600.0      # held since midnight


def test_a_day_is_whole_local_day_at_the_cycle():
    d = _day()
    n = sum(1 for _ in d.cycles())
    assert n == 24 * 3600 // d.cycle_s


def test_save_load_round_trip_holds_no_entity_id(tmp_path):
    p = save_day(_day(tags={"tags": ["mixed"]}), tmp_path)
    raw = gzip.open(p, "rt").read()
    assert "sensor." not in raw and "private" not in raw
    back = load_day(p)
    assert back.series["solar_power"][1][1] is None
    assert back.tags == {"tags": ["mixed"]}


def test_corpus_picks_by_tag_and_skips_gap_days(tmp_path):
    save_day(_day({"tags": ["sunny"]}, "2026-10-01"), tmp_path)
    save_day(_day({"tags": ["grey", "car"]}, "2026-10-02"), tmp_path)
    save_day(_day({"tags": ["gap"]}, "2026-10-03"), tmp_path / "pinned")
    names = lambda ps: [p.name[:10] for p in ps]  # noqa: E731
    assert names(corpus_days(tmp_path)) == ["2026-10-01", "2026-10-02"]
    assert names(corpus_days(tmp_path, tags=["car"])) == ["2026-10-02"]
    assert names(corpus_days(tmp_path, include_gap=True))[-1] == "2026-10-03"
    assert names(corpus_days(tmp_path, tags=["gap"])) == ["2026-10-03"]
