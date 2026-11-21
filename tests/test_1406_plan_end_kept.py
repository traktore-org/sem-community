"""#1406 — the plan's end is sent on its own key, so the size trim never takes it.

On the Plan card, "Skip tonight" and "Start now" last until the plan's end.
The card read that end from the last slot only. When the plan is too big for
the recorder, ``_energy_plan_attrs`` sends ``slots: []`` (``timeline_omitted``),
and the card fell back to 720 minutes: a skip set at 09:23 ended at 21:23,
before the night it was meant to skip.

``ends_at`` is the latest slot end of the FULL plan, taken before any trim, and
no trim level drops it. The card reads it first (``planEndMs``).
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management import sensor as sensor_mod
from custom_components.solar_energy_management.coordinator import coordinator as coord_mod
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.sensor import (
    _PLAN_ATTR_BUDGET_BYTES,
    _energy_plan_attrs,
    _plan_ends_at,
)
from custom_components.solar_energy_management.utils.attr_budget import (
    fit_state_attributes,
)

from .test_638_plan_surface import _size, _synthetic_plan
from .test_638_shadow_mode import (  # noqa: F401 — fixtures come along
    _DayCapableTime, _fake_load, _fake_self, _power, _scheduler, freeze_targets,
)


def _day_plan(monkeypatch, hour=9, minute=23):
    """The real planner, stamped by day: the plan runs now → tomorrow 07:00."""
    fake = _fake_self(devices=[_fake_load()])
    fake.time_manager = _DayCapableTime()
    fixed = datetime(2026, 11, 21, hour, minute,
                     tzinfo=coord_mod.dt_util.DEFAULT_TIME_ZONE)
    monkeypatch.setattr(coord_mod.dt_util, "now", lambda *a, **k: fixed)
    SEMCoordinator._shadow_energy_plan(
        fake, _scheduler(), energy=MagicMock(), power=_power())
    plan = fake._energy_plan_shadow
    assert isinstance(plan, dict) and plan["slots"], "the planner made no plan"
    return plan, fixed


def test_the_report_a_day_plan_too_big_keeps_its_end(freeze_targets, monkeypatch):
    """The report: a skip at 09:23 on a plan too big for the sensor. The slots
    go; the end stays, and it is tomorrow 07:00, not 12 hours from now."""
    plan, now = _day_plan(monkeypatch)
    # The real plan from this fake is small; a small budget makes the sensor
    # trim it the way a large home's plan is trimmed.
    monkeypatch.setattr(sensor_mod, "_PLAN_ATTR_BUDGET_BYTES", 1500)
    attrs = _energy_plan_attrs(plan)
    assert attrs["timeline_omitted"] is True and attrs["slots"] == []
    end = datetime.fromisoformat(attrs["ends_at"])
    assert end == now.replace(hour=7, minute=0) + timedelta(days=1)
    assert end == datetime.fromisoformat(plan["slots"][-1]["end"])
    minutes = (end - now).total_seconds() / 60
    assert minutes > 720, "the skip must reach the night it skips"


def test_a_plan_that_fits_sends_the_same_end(freeze_targets, monkeypatch):
    plan, _ = _day_plan(monkeypatch)
    attrs = _energy_plan_attrs(plan)
    assert not attrs.get("timeline_omitted")
    assert attrs["ends_at"] == attrs["slots"][-1]["end"]


@pytest.mark.parametrize("shape", [
    # slots alone overflow: slots go, blocks stay
    dict(slots=200, demands=3, blocks_per_demand=1),
    # blocks overflow too: blocks go, runs stay
    dict(slots=96, demands=12, blocks_per_demand=60),
])
def test_every_trim_level_keeps_the_end(shape):
    plan = _synthetic_plan(**shape)
    for i, b in enumerate(plan["blocks"]):
        b["power_w"] = 100.0 + i          # no two touch: merging cannot save it
    attrs = _energy_plan_attrs(plan)
    assert attrs["timeline_omitted"] is True and attrs["slots"] == []
    assert attrs["ends_at"] == plan["slots"][-1]["end"]
    assert _size(attrs) <= _PLAN_ATTR_BUDGET_BYTES


def test_the_last_trim_step_keeps_the_end():
    """Even when every demand's runs go, the end stays."""
    plan = _synthetic_plan(slots=96, demands=40, blocks_per_demand=60)
    for i, b in enumerate(plan["blocks"]):
        b["power_w"] = 100.0 + i
    attrs = _energy_plan_attrs(plan)
    assert attrs["blocks"] == []
    rows = [d for d in attrs["demands"] if isinstance(d, dict)]
    assert any("runs" not in d for d in rows), "no runs were dropped; the test proves nothing"
    assert attrs["ends_at"] == plan["slots"][-1]["end"]


def test_the_sensor_gate_keeps_the_end():
    """The platform's own exit gate drops large non-scalar attributes. The
    end is one string, so it stays even when the gate trims."""
    plan = _synthetic_plan(slots=200, demands=3, blocks_per_demand=1)
    attrs = _energy_plan_attrs(plan)
    out = fit_state_attributes(attrs, limit=600)
    assert out.get("attributes_trimmed"), "the gate did not trim; the test proves nothing"
    assert out["ends_at"] == plan["slots"][-1]["end"]


def test_the_end_is_the_latest_time_not_the_largest_text():
    """Across the autumn clock change the offset drops by an hour: as text,
    02:30+02:00 sorts after 02:15+01:00, but it is 45 minutes earlier."""
    plan = {"demands": [], "slots": [
        {"start": "2026-10-25T02:00:00+02:00", "end": "2026-10-25T02:30:00+02:00"},
        {"start": "2026-10-25T02:00:00+01:00", "end": "2026-10-25T02:15:00+01:00"},
    ]}
    assert _energy_plan_attrs(plan)["ends_at"] == "2026-10-25T02:15:00+01:00"


@pytest.mark.parametrize("slots", [
    [],
    None,
    [{"start": "x", "end": "not a time"}],
    [{"start": "2026-11-21T22:00:00", "end": "2026-11-22T07:00:00"}],   # no zone
    [{"start": "x", "end": None}],
])
def test_no_readable_end_sends_none(slots):
    """No end the card can trust: the key says None, and the card keeps its
    own fallback. Never a made-up time."""
    attrs = _energy_plan_attrs({"demands": [], "slots": slots})
    assert attrs["ends_at"] is None


def test_the_end_reader_skips_rows_that_are_not_rows():
    assert _plan_ends_at(["not a row", 5, None]) is None
    assert _plan_ends_at("not a list") is None
    assert _plan_ends_at(["x", {"end": "2026-11-22T07:00:00+01:00"}]) == "2026-11-22T07:00:00+01:00"


def test_a_bad_row_beside_good_ones_is_skipped():
    plan = {"demands": [], "slots": [
        {"start": "2026-11-21T22:00:00+01:00", "end": "2026-11-22T07:00:00+01:00"},
        {"start": "x", "end": "garbage"},
    ]}
    assert _energy_plan_attrs(plan)["ends_at"] == "2026-11-22T07:00:00+01:00"


def test_no_plan_sends_no_end():
    """By day with no plan the sensor carries only the review; no end."""
    assert "ends_at" not in _energy_plan_attrs(None, extra={"review": {"x": 1}})


def test_a_stored_plan_from_an_older_build_gets_its_end():
    """A plan saved before #1406 has no end of its own; the sensor reads it
    from the stored slots, so a restart does not bring the 12 hours back."""
    t = datetime(2026, 11, 21, 22, 0, tzinfo=timezone(timedelta(hours=1)))
    plan = {"computed_at": t.isoformat(), "demands": [], "slots": [
        {"start": (t + timedelta(hours=i)).isoformat(),
         "end": (t + timedelta(hours=i + 1)).isoformat()} for i in range(9)]}
    assert _energy_plan_attrs(plan)["ends_at"] == "2026-11-22T07:00:00+01:00"
