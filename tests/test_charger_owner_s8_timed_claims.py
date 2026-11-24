"""(#1381, charger owner S8) Every timed claim on a charger, in one view.

A pause (#980), a plan override (#1085), a battery boost (#1025) and SEM's
own hand-back after a guard stop each kept their own record; nobody could
answer "what holds this charger right now, and until when". The owner
reads all four in one place; the diagnostics download shows it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator import charger_owner as owner
from custom_components.solar_energy_management.coordinator.plan_override import (
    PlanOverride,
)

NOW = datetime(2026, 11, 24, 18, 0, tzinfo=timezone.utc)


def test_all_four_kinds_are_listed():
    coord = SimpleNamespace(
        config={"ev_chargers": [{"id": "c", "pause_charging_until":
                                 (NOW + timedelta(hours=1)).isoformat(),
                                 "pause_resume_mode": "min_plus_solar"}]},
        _plan_overrides={"c": PlanOverride("c", "skip", NOW + timedelta(hours=8))},
        _battery_boost=SimpleNamespace(charger_id="c", floor_soc=40.0),
        _guard_stops={"c": {"failures": 1, "left_off": False}},
    )
    kinds = [c["kind"] for c in owner.timed_claims(coord, "c", NOW)]
    assert kinds == ["pause", "override:skip", "battery_boost", "hand_back"]


def test_an_expired_pause_or_override_is_not_a_claim():
    coord = SimpleNamespace(
        config={"ev_chargers": [{"id": "c", "pause_charging_until":
                                 (NOW - timedelta(minutes=1)).isoformat()}]},
        _plan_overrides={"c": PlanOverride("c", "force", NOW - timedelta(seconds=1))},
    )
    assert owner.timed_claims(coord, "c", NOW) == []


def test_another_chargers_boost_is_not_this_ones():
    coord = SimpleNamespace(config={}, _battery_boost=SimpleNamespace(
        charger_id="other", floor_soc=40.0))
    assert owner.timed_claims(coord, "c", NOW) == []


def test_the_diagnostics_view_never_raises_on_a_bare_coordinator():
    assert owner.diagnostics(SimpleNamespace()) == {}
