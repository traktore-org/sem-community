"""(#1381) A stop the CHARGER made is not "the car is full".

Seen on the .175 rig (observer mode) on 25.11.2026: the shared wallbox was
stepped down by another controller (16 A → 10 A), then switched off. The rig's
taper detector read the step-down as a taper and the 0 W after the switch-off
as the end of the charge, anchored the car at 100 % ("taper", 06:01:31), and
the charger card showed "~100 % estimate" next to "16.8 kWh to go".

#708 already covers SEM's own withdrawal (its setpoint drops to 0). It cannot
see a stop made by someone else: in observer mode SEM never offered, so there
is nothing to withdraw. The charger itself knows better — its enable switch
reads off, or its own current limit reads 0. While the charger is not
offering, 0 W says nothing about the pack.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
    EVTaperDetector,
)

BASE = datetime(2026, 11, 25, 5, 0, 0)
CONFIG = {"ev_battery_capacity_kwh": 40, "ev_target_soc": 80}


def _feed(det, power_w, count, cursor, offering=None):
    for _ in range(count):
        det.update(power_w, 0.0, True, BASE + timedelta(seconds=cursor),
                   charger_offering=offering)
        cursor += 10
    return cursor


def _plateau_then_step_down(det, offering=None):
    cur = _feed(det, 11000.0, 60, 0, offering)      # 10 min at full tilt
    for p in (9000.0, 7000.0, 5000.0, 3000.0):       # another hand walks it down
        cur = _feed(det, p, 12, cur, offering)
    return cur


def test_charger_switched_off_is_not_full():
    det = EVTaperDetector(CONFIG)
    cur = _plateau_then_step_down(det, offering=True)
    # the box's enable switch now reads off: someone stopped the charger
    _feed(det, 0.0, 12, cur, offering=False)
    assert not det.full_detected
    assert det.anchor_kind != "taper"


def test_real_taper_with_charger_still_offering_is_full():
    det = EVTaperDetector(CONFIG)
    cur = _plateau_then_step_down(det, offering=True)
    _feed(det, 0.0, 12, cur, offering=True)
    assert det.full_detected
    assert det.anchor_kind == "taper"


def test_unknown_offer_keeps_todays_behaviour():
    det = EVTaperDetector(CONFIG)
    cur = _plateau_then_step_down(det)
    _feed(det, 0.0, 12, cur)
    assert det.full_detected


def test_a_stop_clears_the_decline_so_a_later_pause_is_not_full():
    det = EVTaperDetector(CONFIG)
    cur = _plateau_then_step_down(det, offering=True)
    cur = _feed(det, 0.0, 6, cur, offering=False)    # outside stop
    # switched on again, the car does not answer at once
    _feed(det, 0.0, 12, cur, offering=True)
    assert not det.full_detected


# ── the coordinator reads the charger's own word ──────────────────────────
from types import SimpleNamespace  # noqa: E402

from custom_components.solar_energy_management.coordinator.coordinator import (  # noqa: E402
    SEMCoordinator,
)


def _coord(states, cfg):
    c = SEMCoordinator.__new__(SEMCoordinator)
    c.config = {"ev_chargers": [dict(cfg, id="c1")]}
    c.hass = SimpleNamespace(states=SimpleNamespace(
        get=lambda eid: SimpleNamespace(state=states[eid]) if eid in states else None))
    return c


def test_enable_switch_off_means_not_offering():
    c = _coord({"switch.box_enable": "off"}, {"ev_start_stop_entity": "switch.box_enable"})
    assert c._charger_offering("c1") is False


def test_current_limit_zero_means_not_offering():
    c = _coord({"number.box_amps": "0"}, {"ev_current_control_entity": "number.box_amps"})
    assert c._charger_offering("c1") is False


def test_enable_on_means_offering():
    c = _coord({"switch.box_enable": "on", "number.box_amps": "10"},
               {"ev_start_stop_entity": "switch.box_enable",
                "ev_current_control_entity": "number.box_amps"})
    assert c._charger_offering("c1") is True


def test_nothing_readable_is_unknown():
    c = _coord({"switch.box_enable": "unavailable"}, {"ev_start_stop_entity": "switch.box_enable"})
    assert c._charger_offering("c1") is None
    assert _coord({}, {})._charger_offering("c1") is None
