"""(#1381) ONE battery-help switch: the charger's.

There were two: the battery card's install-wide "May the battery help charge
the car?" and the charger card's "May the battery help the car?" — both had
to be on. The install-wide one is gone. A one-time migration carries an OFF
over to every charger, so nothing that was forbidden becomes allowed; after
it the engine reads only the per-charger answer.
"""
import ast
import copy
import pathlib

from custom_components.solar_energy_management import _move_battery_help_to_chargers
from custom_components.solar_energy_management.coordinator.build_view import (
    _battery_may_assist_ev,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _opts(install):
    return {
        "battery_permissions": {"may_export": True, "may_assist_ev": install},
        "ev_chargers": [
            {"id": "a", "charge_mode": "solar_plus_battery"},
            {"id": "b", "charge_mode": "min_plus_solar"},
            {"id": "c", "charge_mode": "always_max"},
            {"id": "d", "charge_mode": "solar_only"},
        ],
    }


def test_install_off_turns_every_charger_off():
    opts, changed = _move_battery_help_to_chargers(_opts(False))
    assert changed
    by = {c["id"]: c for c in opts["ev_chargers"]}
    assert by["a"]["charge_mode"] == "solar_only"
    assert by["b"]["charge_mode"] == "solar_plus_cheap"
    assert by["c"]["charge_mode"] == "always_max" and by["c"]["ev_battery_help"] is False
    assert by["d"]["charge_mode"] == "solar_only"
    assert all(c["ev_battery_may_assist"] is False for c in opts["ev_chargers"])
    assert "may_assist_ev" not in opts["battery_permissions"]
    assert opts["battery_permissions"]["may_export"] is True


def test_install_on_leaves_each_charger_as_it_was():
    before = _opts(True)
    opts, changed = _move_battery_help_to_chargers(copy.deepcopy(before))
    assert changed                                   # the old key is dropped
    assert opts["ev_chargers"] == before["ev_chargers"]
    assert "may_assist_ev" not in opts["battery_permissions"]


def test_unset_install_switch_changes_nothing():
    before = {"ev_chargers": [{"id": "a", "charge_mode": "min_plus_solar"}]}
    opts, changed = _move_battery_help_to_chargers(copy.deepcopy(before))
    assert not changed and opts == before


def test_the_migration_is_idempotent():
    once, _ = _move_battery_help_to_chargers(_opts(False))
    twice, changed = _move_battery_help_to_chargers(copy.deepcopy(once))
    assert not changed and twice == once


def test_the_engine_reads_only_the_charger():
    old_install_no = {"battery_permissions": {"may_assist_ev": False}}
    assert _battery_may_assist_ev(old_install_no, {"id": "a"}) is True
    assert _battery_may_assist_ev({}, {"id": "a", "ev_battery_may_assist": False}) is False
    # SEM hands-off the battery entirely: still nothing for any car
    assert _battery_may_assist_ev({"battery_mode": "off"}, {"id": "a"}) is False


def test_no_engine_path_reads_the_install_permission_any_more():
    readers = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("tests/", "consts/battery_permissions.py")) or rel == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
                if name == "may_assist_ev":
                    readers.append(f"{rel}:{node.lineno}")
    assert readers == [], readers


def test_the_install_switch_entity_is_gone():
    from custom_components.solar_energy_management.switch import (
        PERMISSION_SWITCHES, SWITCH_TYPES,
    )
    assert "battery_may_assist_ev" not in {d.key for d in SWITCH_TYPES}
    assert "battery_may_assist_ev" not in PERMISSION_SWITCHES
