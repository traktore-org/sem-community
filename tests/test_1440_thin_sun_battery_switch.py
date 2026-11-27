"""#1440 — the thin-sun rule reads the charger's battery switch.

Found live on the .175 test rig (27.11): the gate asked the legacy
``ev_battery_may_assist`` (unset = yes) and ignored the switch on the card,
so it always concluded "the battery pays"; with the switch on, every
session was dropped on its first cycle; the plan booked grid blocks the
gate would never run.
"""
from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator import (
    coordinator as coord_mod,
)
from custom_components.solar_energy_management.coordinator import (
    reason_codes as RC,
)
from custom_components.solar_energy_management.coordinator.build_view import (
    _battery_boost_allowed,
    _battery_may_assist_ev,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerIntent,
)

ROOT = Path(coord_mod.__file__).resolve().parents[1]
HELP_OFF = "solar_plus_cheap"
HELP_ON = "min_plus_solar"


def test_the_switch_answers_may_the_battery_help():
    assert _battery_may_assist_ev({}, {"id": "a", "charge_mode": HELP_OFF}) is False
    assert _battery_may_assist_ev({}, {"id": "a", "charge_mode": HELP_ON}) is True
    assert _battery_may_assist_ev({}, {"id": "a", "charge_mode": "solar_only"}) is False
    assert _battery_may_assist_ev(
        {}, {"id": "a", "charge_mode": "solar_plus_battery"}) is True
    # Now / Off keep the remembered switch
    assert _battery_may_assist_ev(
        {}, {"id": "a", "charge_mode": "always_max", "ev_battery_help": False}) is False


def test_a_per_charger_never_still_reads_off():
    cfg = {"id": "a", "charge_mode": HELP_ON, "ev_battery_may_assist": False}
    assert _battery_may_assist_ev({}, cfg) is False


def test_unset_and_battery_hands_off_are_unchanged():
    assert _battery_may_assist_ev({}, {"id": "a"}) is True
    assert _battery_may_assist_ev({"battery_mode": "off"},
                                  {"id": "a", "charge_mode": HELP_ON}) is False


def test_a_boost_is_the_users_command_not_the_switch():
    # switch off, but the user asked for a boost: allowed
    assert _battery_boost_allowed({}, {"id": "a", "charge_mode": HELP_OFF}) is True
    assert _battery_boost_allowed(
        {}, {"id": "a", "ev_battery_may_assist": False}) is False
    assert _battery_boost_allowed({"battery_mode": "off"}, {"id": "a"}) is False


def _t(h, m=0):
    from homeassistant.util import dt as dt_util
    return datetime(2026, 11, 27, h, m, tzinfo=dt_util.get_default_time_zone())


def test_a_session_survives_with_the_switch_on(monkeypatch):
    host = SimpleNamespace()
    on = SimpleNamespace(reason_code=RC.CHARGER_SUN_PLUS_GRID,
                         intent=ChargerIntent.CHARGE_AT_AMPS, mode=HELP_ON)
    monkeypatch.setattr(coord_mod.dt_util, "now", lambda: _t(12))
    coord_mod._note_thin_sun(host, "a", on)
    monkeypatch.setattr(coord_mod.dt_util, "now", lambda: _t(12, 5))
    coord_mod._note_thin_sun(host, "a", on)
    assert coord_mod._thin_sun_started(host, "a") == _t(12)


def test_other_modes_still_end_a_session(monkeypatch):
    host = SimpleNamespace()
    monkeypatch.setattr(coord_mod.dt_util, "now", lambda: _t(12))
    coord_mod._note_thin_sun(host, "a", SimpleNamespace(
        reason_code=RC.CHARGER_SUN_PLUS_GRID,
        intent=ChargerIntent.CHARGE_AT_AMPS, mode=HELP_OFF))
    coord_mod._note_thin_sun(host, "a", SimpleNamespace(
        reason_code=RC.CHARGER_SUN_PLUS_GRID,
        intent=ChargerIntent.CHARGE_AT_AMPS, mode="always_max"))
    assert coord_mod._thin_sun_started(host, "a") is None


def test_the_plan_books_grid_in_sun_only_with_the_switch_off():
    """Plan == gate: the planner's ``grid_in_sun`` asks the same reader
    the live gate asks (``_battery_may_assist_ev``)."""
    tree = ast.parse((ROOT / "coordinator" / "coordinator.py").read_text())
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "grid_in_sun":
            names = {getattr(n, "attr", getattr(n, "id", None))
                     for n in ast.walk(node.value)}
            found.append("_battery_may_assist_ev" in names)
    assert found and all(found), found


def test_the_plan_books_no_grid_in_sun_with_the_switch_on(monkeypatch):
    from unittest.mock import MagicMock
    from custom_components.solar_energy_management.coordinator import (
        energy_planner, ev_night_targets,
    )
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    from .test_638_shadow_mode import _fake_self, _power, _scheduler
    monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                        lambda coord, energy: {"ev_charger": 10.0})
    seen = []
    real = energy_planner.pack_night

    def spy(demands, *a, **kw):
        seen.extend(demands)
        return real(demands, *a, **kw)
    monkeypatch.setattr(energy_planner, "pack_night", spy)

    def run(mode):
        seen.clear()
        fake = _fake_self()
        fake._tariff_optimized_for = lambda cfg: True
        for c in fake.config.get("ev_chargers") or []:
            c["charge_mode"] = mode
        SEMCoordinator._shadow_energy_plan(
            fake, _scheduler(), energy=MagicMock(), power=_power())
        return [d for d in seen if d.kind == "ev"]

    on = run(HELP_ON)
    off = run(HELP_OFF)
    assert on and not any(d.grid_in_sun for d in on)
    assert off and all(d.grid_in_sun for d in off)
