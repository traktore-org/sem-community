"""#1381 — after the phase guard stops a charger SEM yields to, the user is told.

The reporter's night of 23→24.11: the guard switched off a charger another
party steers at 16:44; nothing switched it back on; at 02:00 the car was at
12 % and SEM's state read "night charging active" at 0 W. Until SEM can hand
such a charger back (the charger owner), it says what happened: a Repair
naming the charger, and an honest state. Both clear when the charger draws
again or the car is unplugged.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from custom_components.solar_energy_management.coordinator import guard_notice as gn
from custom_components.solar_energy_management.consts.states import (
    ChargingState,
    get_status_message,
)

T0 = 1_795_000_000.0
CID = "laadpaal_links"


def _coord():
    dev = SimpleNamespace(name="Laadpaal Links")
    return SimpleNamespace(hass=object(), _ev_devices={CID: dev}, _ev_device=None)


def _power(watts, *, absent=False):
    return SimpleNamespace(power_w=watts, car_absent=absent)


class _Registry:
    def __init__(self):
        self.created, self.deleted = [], []

    def create(self, hass, domain, issue_id, **kw):
        self.created.append((issue_id, kw.get("translation_placeholders")))

    def delete(self, hass, domain, issue_id):
        self.deleted.append(issue_id)


def _patched(reg, existing=()):
    known = set(existing)

    class _IR:
        IssueSeverity = SimpleNamespace(WARNING="warning")

        @staticmethod
        def async_create_issue(hass, domain, issue_id, **kw):
            reg.create(hass, domain, issue_id, **kw)

        @staticmethod
        def async_delete_issue(hass, domain, issue_id):
            reg.delete(hass, domain, issue_id)
            known.discard(issue_id)

        @staticmethod
        def async_get(hass):
            return SimpleNamespace(
                async_get_issue=lambda d, i: object() if i in known else None)

    return patch.object(gn, "_ir", lambda: _IR)


def test_the_stop_raises_one_repair_naming_the_charger():
    coord, reg = _coord(), _Registry()
    with _patched(reg):
        gn.note_stop(coord, CID, "phase L3 at 28.0 A > 23.0 A", now=T0)
        gn.note_stop(coord, CID, "phase L3 at 28.0 A > 23.0 A", now=T0 + 10)
    assert reg.created == [(f"guard_stopped_{CID}", {"charger": "Laadpaal Links"})]


def test_the_state_is_honest_while_it_is_off():
    coord, reg = _coord(), _Registry()
    with _patched(reg):
        gn.note_stop(coord, CID, "r", now=T0)
        assert gn.effective_state(coord, CID, ChargingState.NIGHT_CHARGING_ACTIVE) \
            == ChargingState.PHASE_GUARD_STOPPED
        assert gn.fleet_state(coord, ChargingState.NIGHT_CHARGING_ACTIVE,
                              any_drawing=False) == ChargingState.PHASE_GUARD_STOPPED
        assert gn.fleet_state(coord, ChargingState.NIGHT_CHARGING_ACTIVE,
                              any_drawing=True) == ChargingState.NIGHT_CHARGING_ACTIVE


def test_the_draw_right_after_the_stop_does_not_clear_it():
    coord, reg = _coord(), _Registry()
    with _patched(reg):
        gn.note_stop(coord, CID, "r", now=T0)
        gn.update(coord, CID, _power(10300), now=T0 + 20)   # meter still lags
        assert gn.held(coord, CID) is True
        assert reg.deleted == []


def test_a_charge_again_clears_it():
    coord, reg = _coord(), _Registry()
    with _patched(reg):
        gn.note_stop(coord, CID, "r", now=T0)
        gn.update(coord, CID, _power(0), now=T0 + 3600)
        assert gn.held(coord, CID) is True
        gn.update(coord, CID, _power(10400), now=T0 + 9 * 3600)   # 02:01 by hand
        assert gn.held(coord, CID) is False
        assert gn.effective_state(coord, CID, "x") == "x"
    assert reg.deleted == [f"guard_stopped_{CID}"]


def test_an_unplugged_car_clears_it():
    coord, reg = _coord(), _Registry()
    with _patched(reg):
        gn.note_stop(coord, CID, "r", now=T0)
        gn.update(coord, CID, _power(0, absent=True), now=T0 + 120)
        assert gn.held(coord, CID) is False


def test_a_restart_keeps_it_through_the_repair():
    coord, reg = _coord(), _Registry()
    with _patched(reg, existing={f"guard_stopped_{CID}"}):
        assert gn.held(coord, CID) is True                       # after restart
        gn.update(coord, CID, _power(10400), now=T0)            # no grace now
        assert gn.held(coord, CID) is False


def test_nothing_held_means_nothing_changes():
    coord, reg = _coord(), _Registry()
    with _patched(reg):
        gn.update(coord, CID, _power(0), now=T0)
        assert gn.effective_state(coord, CID, "night_charging_active") \
            == "night_charging_active"
    assert reg.created == [] and reg.deleted == []


def test_the_state_has_a_text():
    assert "phase guard" in get_status_message(ChargingState.PHASE_GUARD_STOPPED)


def test_the_coordinator_wires_both_charger_paths():
    import inspect
    from custom_components.solar_energy_management.coordinator import coordinator
    src = inspect.getsource(coordinator)
    assert src.count("guard_notice") >= 4
    assert src.count(".note_stop(") == 2 and src.count("_gn.update(") == 2
    assert ".fleet_state(" in src and ".effective_state(" in src
