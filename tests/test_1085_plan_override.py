"""#1085 Part B — one-off plan overrides: storage, expiry, per-device
translation. Pure-module tests — no hass, mirrors curtailment.py's own
test style."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.solar_energy_management.coordinator import (
    plan_override as po,
    reason_codes as RC,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
)

NOW = datetime(2026, 10, 29, 18, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(hours=4)


# ── set / clear / active / purge ───────────────────────────────────────

def test_set_override_round_trips_through_active_override():
    out = po.set_override({}, "battery1", "skip", LATER, NOW)
    rec = po.active_override(out, "battery1", NOW)
    assert rec is not None
    assert rec.action == "skip"
    assert rec.expires_at == LATER


def test_set_override_bad_action_raises():
    with pytest.raises(ValueError):
        po.set_override({}, "battery1", "dance", LATER, NOW)


def test_set_override_past_expiry_raises():
    with pytest.raises(ValueError):
        po.set_override({}, "battery1", "skip", NOW - timedelta(minutes=1), NOW)


def test_set_override_replaces_the_prior_one():
    out = po.set_override({}, "battery1", "skip", LATER, NOW)
    out = po.set_override(out, "battery1", "force", LATER, NOW)
    assert len(out) == 1
    assert po.active_override(out, "battery1", NOW).action == "force"


def test_set_override_never_mutates_the_input():
    original = {}
    po.set_override(original, "battery1", "skip", LATER, NOW)
    assert original == {}


def test_active_override_is_none_past_expiry():
    out = po.set_override({}, "battery1", "skip", LATER, NOW)
    assert po.active_override(out, "battery1", LATER + timedelta(seconds=1)) is None


def test_active_override_is_none_for_an_unknown_device():
    assert po.active_override({}, "battery1", NOW) is None


def test_active_override_does_not_purge():
    out = po.set_override({}, "battery1", "skip", LATER, NOW)
    po.active_override(out, "battery1", LATER + timedelta(seconds=1))
    assert "battery1" in out  # a read never mutates the store


def test_clear_override_removes_only_the_named_device():
    out = po.set_override({}, "battery1", "skip", LATER, NOW)
    out = po.set_override(out, "charger1", "force", LATER, NOW)
    out = po.clear_override(out, "battery1")
    assert "battery1" not in out
    assert "charger1" in out


def test_clear_override_on_an_unset_device_is_a_no_op():
    assert po.clear_override({}, "battery1") == {}


def test_purge_expired_drops_only_lapsed_entries():
    out = po.set_override({}, "battery1", "skip", LATER, NOW)
    out = po.set_override(out, "charger1", "force", NOW + timedelta(minutes=1), NOW)
    purged = po.purge_expired(out, NOW + timedelta(minutes=2))
    assert "charger1" not in purged
    assert "battery1" in purged


# ── serialize / deserialize ─────────────────────────────────────────────

def test_serialize_deserialize_round_trip():
    out = po.set_override({}, "battery1", "cap", LATER, NOW, value=2500.0)
    restored = po.deserialize(po.serialize(out))
    rec = restored["battery1"]
    assert rec.action == "cap"
    assert rec.value == 2500.0
    assert rec.expires_at == LATER
    assert rec.set_at == NOW


def test_deserialize_drops_a_malformed_entry_without_raising():
    raw = {
        "battery1": {"action": "skip", "expires_at": "not-a-date"},
        "charger1": {"action": "not-an-action", "expires_at": LATER.isoformat()},
        "heater1": "not-even-a-dict",
        "pump1": {"action": "force", "expires_at": LATER.isoformat()},
    }
    restored = po.deserialize(raw)
    assert list(restored) == ["pump1"]


def test_deserialize_of_not_a_dict_is_empty():
    assert po.deserialize(None) == {}
    assert po.deserialize([1, 2, 3]) == {}


# ── battery translation ─────────────────────────────────────────────────

def test_battery_skip_sets_mode_off():
    overrides = po.set_override({}, "battery1", "skip", LATER, NOW)
    cfg = po.apply_to_battery_config(overrides, "battery1", {"battery_mode": "auto"}, NOW)
    assert cfg["battery_mode"] == "off"


def test_battery_force_sets_mode_force_charge():
    overrides = po.set_override({}, "battery1", "force", LATER, NOW)
    cfg = po.apply_to_battery_config(overrides, "battery1", {"battery_mode": "auto"}, NOW)
    assert cfg["battery_mode"] == "force_charge"


def test_battery_no_override_passes_config_through_unchanged():
    cfg_in = {"battery_mode": "auto", "battery_max_charge_power_w": 4000}
    cfg_out = po.apply_to_battery_config({}, "battery1", cfg_in, NOW)
    assert cfg_out == cfg_in
    assert cfg_out is not cfg_in  # a new dict, per the VPP precedent it mirrors


def test_battery_standing_off_outranks_a_one_off_force():
    overrides = po.set_override({}, "battery1", "force", LATER, NOW)
    cfg = po.apply_to_battery_config(overrides, "battery1", {"battery_mode": "off"}, NOW)
    assert cfg["battery_mode"] == "off"


def test_battery_cap_and_move_are_not_yet_consumed():
    for action in ("cap", "move"):
        overrides = po.set_override({}, "battery1", action, LATER, NOW, value=1000.0)
        cfg = po.apply_to_battery_config(overrides, "battery1", {"battery_mode": "auto"}, NOW)
        assert cfg["battery_mode"] == "auto"


def test_battery_expired_override_is_inert():
    overrides = po.set_override({}, "battery1", "skip", LATER, NOW)
    cfg = po.apply_to_battery_config(
        overrides, "battery1", {"battery_mode": "auto"}, LATER + timedelta(seconds=1))
    assert cfg["battery_mode"] == "auto"


def test_battery_override_only_touches_its_own_device():
    overrides = po.set_override({}, "battery1", "skip", LATER, NOW)
    cfg = po.apply_to_battery_config(overrides, "battery2", {"battery_mode": "auto"}, NOW)
    assert cfg["battery_mode"] == "auto"


# ── charger translation ─────────────────────────────────────────────────

def _decision(**changes) -> ChargerDecision:
    base = dict(charger_id="charger1", mode="solar_only",
                intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=10,
                reason="solar mode, surplus 4200W, ramp to 10A")
    base.update(changes)
    return ChargerDecision(**base)


def test_charger_skip_rewrites_to_disable():
    overrides = po.set_override({}, "charger1", "skip", LATER, NOW)
    out = po.apply_to_charger_decision(overrides, "charger1", _decision(), NOW)
    assert out.intent is ChargerIntent.DISABLE
    assert out.commanded_amps == 0
    assert out.safety_stop is True
    assert out.reason_code == RC.CHARGER_PLAN_OVERRIDE_STOP
    assert out.reason_params == {"time": f"{LATER:%H:%M}"}


def test_charger_force_rewrites_to_charge_max():
    overrides = po.set_override({}, "charger1", "force", LATER, NOW)
    out = po.apply_to_charger_decision(overrides, "charger1", _decision(), NOW)
    assert out.intent is ChargerIntent.CHARGE_MAX
    assert out.reason_code == RC.CHARGER_PLAN_OVERRIDE_RUN


def test_charger_no_override_passes_decision_through_unchanged():
    decision = _decision()
    out = po.apply_to_charger_decision({}, "charger1", decision, NOW)
    assert out is decision


def test_charger_cap_and_move_are_not_yet_consumed():
    for action in ("cap", "move"):
        overrides = po.set_override({}, "charger1", action, LATER, NOW, value=16.0)
        decision = _decision()
        out = po.apply_to_charger_decision(overrides, "charger1", decision, NOW)
        assert out is decision


def test_charger_expired_override_is_inert():
    overrides = po.set_override({}, "charger1", "skip", LATER, NOW)
    decision = _decision()
    out = po.apply_to_charger_decision(
        overrides, "charger1", decision, LATER + timedelta(seconds=1))
    assert out is decision


def test_charger_override_only_touches_its_own_device():
    overrides = po.set_override({}, "charger1", "skip", LATER, NOW)
    decision = _decision(charger_id="charger2")
    out = po.apply_to_charger_decision(overrides, "charger2", decision, NOW)
    assert out is decision


# ── status payload ───────────────────────────────────────────────────────

def test_status_payload_none_when_inactive():
    assert po.status_payload({}, "battery1", NOW) is None


def test_status_payload_shape():
    overrides = po.set_override({}, "battery1", "skip", LATER, NOW)
    payload = po.status_payload(overrides, "battery1", NOW)
    assert payload == {"action": "skip", "until": f"{LATER:%H:%M}"}
