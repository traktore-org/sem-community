"""#1246 — a saved grid sign follows a new meter on a home with no Energy
Dashboard. The lock is saved with the meter it was learned on and dropped
when the grid is read from another one."""
from __future__ import annotations

from .test_1192_flip_with_no_grid_source import (
    EXP, IMP, METER, _legacy_reader,
)
OLD = "sensor.old_meter"


def test_the_lock_is_saved_with_the_meter_it_was_learned_on():
    r = _legacy_reader()
    r.read_power()
    r._grid_sign_detected = True
    r._grid_sign_inverted = True
    assert r.export_sign_state()["grid_source"] == f"combined:{METER}"


def test_a_lock_learned_on_another_meter_is_dropped():
    r = _legacy_reader()
    r.restore_sign_state({"grid_detected": True, "grid_inverted": True,
                          "grid_source": f"combined:{OLD}"})
    r.read_power()
    assert r._grid_sign_inverted is False


def test_a_lock_learned_on_the_same_meter_is_kept():
    r = _legacy_reader()
    r.restore_sign_state({"grid_detected": True, "grid_inverted": True,
                          "grid_source": f"combined:{METER}"})
    assert r.read_power().grid_power == -2000
    assert r._grid_sign_detected is True and r._grid_sign_inverted is True


def test_a_store_from_before_the_source_was_saved_keeps_its_lock():
    """Nothing says which meter it was learned on: keep it, and name the
    meter now so the next change is seen."""
    r = _legacy_reader()
    r.restore_sign_state({"grid_detected": True, "grid_inverted": True,
                          "grid_source": None})
    assert r.read_power().grid_power == -2000
    assert r._grid_sign_inverted is True
    assert r.export_sign_state()["grid_source"] == f"combined:{METER}"


def test_a_manual_pair_keeps_its_lock_on_the_same_pair():
    r = _legacy_reader(pair=True)
    r.restore_sign_state({"grid_detected": True, "grid_inverted": True,
                          "grid_source": f"manual:{IMP}|{EXP}"})
    r.read_power()
    assert r.export_sign_state()["grid_source"] == f"manual:{IMP}|{EXP}"
    assert r._grid_sign_detected is True


def test_a_pair_lock_meeting_a_one_sensor_meter_is_dropped():
    """The #1215 case: the balance check saved a lock on a pair, a one-sensor
    meter is set later."""
    r = _legacy_reader()
    r.restore_sign_state({"grid_detected": True, "grid_inverted": True,
                          "grid_source": f"manual:{IMP}|{EXP}"})
    r.read_power()
    assert r._grid_sign_inverted is False
