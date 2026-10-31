"""#1278 — a restart is no gap, and a settings check between 5 and 10 %
shows the what-if with its error instead of hiding it."""
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.analytics.day_tags import (
    tag_day, tag_gap, without_restart_gap,
)
from custom_components.solar_energy_management.coordinator.simulation_job import (
    Calibration,
)
from .test_1083_simulation_job import DATES, _job, _tag


def _own(actual, simulated):
    return SimpleNamespace(
        actual_cost=actual, simulated_cost=simulated,
        actual={"import_cost": 100.0, "export_revenue": 0.0, "ev": 0.0})


def test_the_tagger_has_no_restart_input():
    with pytest.raises(TypeError):
        tag_gap(restarted=True)
    assert not tag_day(date="d").gap


def test_an_old_restart_only_gap_is_lifted():
    rec = {"date": "d", "tags": ["mixed", "gap"], "gap": True,
           "gap_why": ["a restart"]}
    out = without_restart_gap(rec)
    assert out["gap"] is False and out["gap_why"] == []
    assert out["tags"] == ["mixed"]
    assert rec["gap"] is True


@pytest.mark.parametrize("why", [
    ["a reading dark 40 min in daylight"],
    ["a restart", "the solar counter did not move"],
])
def test_any_other_gap_reason_stays(why):
    rec = {"date": "d", "tags": ["gap"], "gap": True, "gap_why": why}
    assert without_restart_gap(rec) == rec


@pytest.mark.asyncio
async def test_the_job_offers_a_restart_day_and_not_a_dark_one():
    dark = dict(_tag(DATES[1]), gap=True, tags=["gap"],
                gap_why=["a reading dark 40 min in daylight"])
    restart = dict(_tag(DATES[2]), gap=True, tags=["gap"],
                   gap_why=["a restart"])
    job, _, _ = _job(tags=[_tag(DATES[0]), dark, restart])
    sel = {d["date"]: d["selectable"] for d in job.days()["days"]}
    assert sel == {DATES[0]: True, DATES[1]: False, DATES[2]: True}
    assert job.period_days(DATES[0], DATES[2]) == [DATES[0], DATES[2]]


@pytest.mark.parametrize("sim,calibrated", [
    (105.3, True),     # PROD's 5.3 %: shown, with the error
    (110.0, True),
    (110.5, False),
    (90.0, True),
])
def test_the_what_if_hides_only_past_the_refuse_limit(sim, calibrated):
    c = Calibration()
    c.add(_own(100.0, sim))
    out = c.as_dict()
    assert out["calibrated"] is calibrated
    assert out["max_pct"] == 5.0 and out["refuse_pct"] == 10.0
