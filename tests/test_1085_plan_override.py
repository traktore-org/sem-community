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


def test_charger_force_is_a_mode_input_not_a_rewrite():
    # decide() runs with always_max, so its safety layers still apply
    overrides = po.set_override({}, "charger1", "force", LATER, NOW)
    assert po.charger_mode_for(overrides, "charger1", "solar_only", NOW) == "always_max"
    assert po.charger_mode_for(overrides, "charger2", "solar_only", NOW) == "solar_only"
    assert po.charger_mode_for({}, "charger1", "solar_only", NOW) == "solar_only"
    assert po.charger_mode_for(
        overrides, "charger1", "solar_only", LATER + timedelta(seconds=1)) == "solar_only"


def test_charger_force_never_wakes_a_hands_off_charger():
    overrides = po.set_override({}, "charger1", "force", LATER, NOW)
    assert po.charger_mode_for(overrides, "charger1", "off", NOW) == "off"


def test_charger_force_only_labels_an_unclamped_charge_max():
    overrides = po.set_override({}, "charger1", "force", LATER, NOW)
    out = po.apply_to_charger_decision(
        overrides, "charger1", _decision(intent=ChargerIntent.CHARGE_MAX), NOW)
    assert out.intent is ChargerIntent.CHARGE_MAX
    assert out.reason_code == RC.CHARGER_PLAN_OVERRIDE_RUN
    clamped = _decision(intent=ChargerIntent.CHARGE_AT_AMPS, capped_by_limit=True)
    assert po.apply_to_charger_decision(overrides, "charger1", clamped, NOW) is clamped


@pytest.mark.parametrize("intent", [
    ChargerIntent.RELEASE, ChargerIntent.IDLE, ChargerIntent.DISABLE])
def test_charger_skip_leaves_a_non_charging_decision_alone(intent):
    overrides = po.set_override({}, "charger1", "skip", LATER, NOW)
    decision = _decision(intent=intent, commanded_amps=0)
    assert po.apply_to_charger_decision(overrides, "charger1", decision, NOW) is decision


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


# ── safety: the decide() layers still win (review of the 2.3 branch) ───

def _view(**kw):
    from custom_components.solar_energy_management.coordinator.charger_types import (
        ChargerEnergy, ChargerPower, ChargerView, FleetContext)
    fleet = kw.pop("fleet", FleetContext())
    power = kw.pop("power", ChargerPower(charger_id="charger1", power_w=4000.0, connected=True, charging=True))
    return ChargerView(power=power, energy=ChargerEnergy(charger_id="charger1"), fleet=fleet,
                       config={}, **kw)


def _decide_with_override(action, view_mode, **view_kw):
    from dataclasses import replace
    from custom_components.solar_energy_management.coordinator.decide import decide
    overrides = po.set_override({}, "charger1", action, LATER, NOW)
    view = _view(mode=view_mode, **view_kw)
    view = replace(view, mode=po.charger_mode_for(overrides, "charger1", view.mode, NOW))
    return po.apply_to_charger_decision(overrides, "charger1", decide(view), NOW)


def test_force_on_a_hands_off_charger_still_sends_nothing():
    out = _decide_with_override("force", "off")
    assert out.intent is ChargerIntent.RELEASE


def test_skip_on_a_hands_off_charger_sends_nothing():
    out = _decide_with_override("skip", "off")
    assert out.intent is ChargerIntent.RELEASE


def test_force_does_not_charge_past_the_max_soc_stop():
    out = _decide_with_override("force", "solar_only", soc_ceiling_reached=True)
    assert out.intent is not ChargerIntent.CHARGE_MAX
    assert out.intent is not ChargerIntent.CHARGE_AT_AMPS


def test_force_does_not_beat_the_peak_emergency():
    from custom_components.solar_energy_management.coordinator.charger_types import FleetContext
    out = _decide_with_override(
        "force", "solar_only", fleet=FleetContext(peak_state="emergency"))
    assert out.intent not in (ChargerIntent.CHARGE_MAX, ChargerIntent.CHARGE_AT_AMPS)


# ── stored overrides ─────────────────────────────────────────────────────

def test_deserialize_drops_a_naive_timestamp():
    raw = {"charger1": {"action": "skip", "expires_at": "2026-10-30T06:00:00",
                        "value": None, "set_at": None}}
    assert po.deserialize(raw) == {}
    raw = {"charger1": {"action": "skip", "expires_at": LATER.isoformat(),
                        "value": None, "set_at": "2026-10-29T18:00:00"}}
    assert po.deserialize(raw) == {}


def test_deserialize_drops_an_entry_longer_than_a_day():
    far = NOW + timedelta(days=30)
    raw = {"charger1": {"action": "skip", "expires_at": far.isoformat(),
                        "value": None, "set_at": NOW.isoformat()}}
    assert po.deserialize(raw) == {}


def test_set_override_refuses_more_than_a_day():
    with pytest.raises(ValueError):
        po.set_override({}, "charger1", "skip",
                        NOW + timedelta(minutes=po.MAX_OVERRIDE_MINUTES + 1), NOW)
    po.set_override({}, "charger1", "skip",
                    NOW + timedelta(minutes=po.MAX_OVERRIDE_MINUTES), NOW)


class TestAcrossAClockChange:
    """A day with 25 real hours (DST fall-back) must not change the cap."""

    def test_a_full_day_set_on_fall_back_day_holds(self):
        from datetime import datetime, timedelta, timezone
        from zoneinfo import ZoneInfo

        from custom_components.solar_energy_management.coordinator import (
            plan_override as po,
        )
        zrh = ZoneInfo("Europe/Zurich")
        now = datetime(2026, 10, 24, 12, 0, tzinfo=zrh)
        # the coordinator adds the minutes to the UTC clock
        out = po.set_override({}, "c1", "skip",
                              now.astimezone(timezone.utc) + timedelta(hours=24), now)
        # wall-clock +24 h is 25 real hours on this day: refused
        with pytest.raises(ValueError):
            po.set_override({}, "c1", "skip", now + timedelta(hours=24), now)
        raw = po.serialize(out)
        assert "c1" in po.deserialize(raw)
        assert po.active_override(out, "c1", now.astimezone(timezone.utc) + timedelta(hours=23)) is not None
        assert po.active_override(out, "c1", now.astimezone(timezone.utc) + timedelta(hours=25)) is None
