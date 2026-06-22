"""Charger state reconciler — desired-vs-observed convergence (#392).

Replaces the per-cycle imperative actuator. These tests pin the pure
decision table: given a desired state, an observed state and a clock,
the reconciler emits the MINIMUM set of actions to converge — and
emits NONE when already converged (the root-cause fix for the 391×
keba.disable spam seen on PROD 2026-06-21).
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    ActionKind,
    DesiredState,
    ObservedState,
    desired_from_decision,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
)


def _decision(intent: ChargerIntent, amps: int = 0) -> ChargerDecision:
    # ChargerDecision requires: charger_id, mode, intent (+ optional fields).
    # mode is a required positional field — supply a stub value.
    return ChargerDecision(
        charger_id="ev_charger",
        mode="solar",
        intent=intent,
        commanded_amps=amps,
        reason="test",
        budget_w=0.0,
    )


def test_desired_from_decision_maps_every_intent():
    assert desired_from_decision(_decision(ChargerIntent.DISABLE)) == (DesiredState.OFF, 0)
    assert desired_from_decision(_decision(ChargerIntent.IDLE)) == (DesiredState.IDLE, 0)
    assert desired_from_decision(_decision(ChargerIntent.CHARGE_AT_AMPS, 10)) == (DesiredState.CHARGE, 10)
    # CHARGE_MAX maps to CHARGE with amps=0 sentinel — apply layer resolves max.
    assert desired_from_decision(_decision(ChargerIntent.CHARGE_MAX)) == (DesiredState.CHARGE, 0)


from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    Action, ActionKind, ChargerReconciler, ObservedState,
)

HEARTBEAT_S = 5.0  # KEBA refresh interval


def _rec() -> ChargerReconciler:
    return ChargerReconciler(charger_id="ev_charger", heartbeat_s=HEARTBEAT_S,
                             idle_disable_threshold=4)


def _obs(charging=False, setpoint=0, self_charging=False, power=0.0) -> ObservedState:
    return ObservedState(charging=charging, setpoint_a=setpoint,
                         self_charging=self_charging, power_w=power)


def test_idle_not_drawing_emits_nothing_every_cycle():
    """The PROD bug: IDLE + already-open contactor must NOT re-disable."""
    rec = _rec()
    for cycle in range(100):
        actions = rec.reconcile(DesiredState.IDLE, 0, _obs(charging=False), now=cycle * 10.0)
        assert actions == [Action(ActionKind.NONE)], f"cycle {cycle} spammed: {actions}"


def test_off_drawing_disables_immediately_no_flicker_grace():
    rec = _rec()
    actions = rec.reconcile(DesiredState.OFF, 0, _obs(charging=True, power=4000.0), now=0.0)
    assert actions == [Action(ActionKind.DISABLE)]


def test_idle_drawing_holds_then_disables_after_threshold():
    rec = _rec()
    # cycles 1..3 (< threshold 4): flicker hold → NONE
    for cycle in range(1, 4):
        actions = rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=6000.0),
                                now=cycle * 10.0)
        assert actions == [Action(ActionKind.NONE)], f"cycle {cycle}: {actions}"
    # cycle 4 (>= threshold): confirmed real → DISABLE
    actions = rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=6000.0), now=40.0)
    assert actions == [Action(ActionKind.DISABLE)]


def test_idle_resets_flicker_counter_when_box_stops():
    rec = _rec()
    rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=6000.0), now=10.0)  # count=1
    rec.reconcile(DesiredState.IDLE, 0, _obs(charging=False), now=20.0)  # stopped → NONE + reset
    # next drawing idle starts a fresh hold window, not an immediate disable
    actions = rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=6000.0), now=30.0)
    assert actions == [Action(ActionKind.NONE)]


def test_charge_not_charging_starts():
    rec = _rec()
    actions = rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=False), now=0.0)
    assert actions == [Action(ActionKind.START_AND_WRITE, 10)]


def test_charge_steady_writes_only_on_heartbeat():
    """Steady CHARGE(10): write on start, then only every heartbeat_s."""
    rec = _rec()
    rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=False), now=0.0)  # START
    writes = 0
    for cycle in range(1, 100):
        t = cycle * 1.0  # 1 s cycle to make heartbeat counting easy
        actions = rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=True, setpoint=10), now=t)
        if actions != [Action(ActionKind.NONE)]:
            writes += 1
            assert actions == [Action(ActionKind.WRITE_CURRENT, 10)]
    # 99 cycles over 1 s each, heartbeat 5 s → ~19 refreshes, not 99
    assert 15 <= writes <= 21, writes


def test_charge_target_change_writes_immediately():
    rec = _rec()
    rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=False), now=0.0)
    actions = rec.reconcile(DesiredState.CHARGE, 12, _obs(charging=True, setpoint=10), now=1.0)
    assert actions == [Action(ActionKind.WRITE_CURRENT, 12)]


def test_charge_drift_rewrites():
    """Box silently reverted to 6 A (failsafe) while we wanted 10 → re-assert."""
    rec = _rec()
    rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=False), now=0.0)
    actions = rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=True, setpoint=6), now=1.0)
    assert actions == [Action(ActionKind.WRITE_CURRENT, 10)]


# ─────────────────────────────────────────────────────────────────
# Task 3 — effectful layer: observe() + reconcile_and_apply()
# ─────────────────────────────────────────────────────────────────

from unittest.mock import AsyncMock, MagicMock
from custom_components.solar_energy_management.coordinator.charger_types import ChargerPower


def _mock_adapter(max_a=32):
    a = MagicMock()
    a.command_disable = AsyncMock()
    a.command_current = AsyncMock()
    a.command_max = AsyncMock()
    a.arm_failsafe = AsyncMock()
    a.max_current_a = max_a
    return a


def _power(power_w=0.0):
    return ChargerPower(charger_id="ev_charger", power_w=power_w)


@pytest.mark.asyncio
async def test_apply_idle_idempotent_no_calls_when_open():
    rec = _rec()
    adapter = _mock_adapter()
    adapter.actual_charging = MagicMock(return_value=False)
    adapter.is_self_charging = MagicMock(return_value=False)
    for cycle in range(50):
        await rec.reconcile_and_apply(
            _decision(ChargerIntent.IDLE), adapter, _power(0.0), now=cycle * 10.0)
    adapter.command_disable.assert_not_called()
    adapter.command_current.assert_not_called()


@pytest.mark.asyncio
async def test_apply_charge_max_resolves_hardware_max():
    rec = _rec()
    adapter = _mock_adapter(max_a=32)
    adapter.actual_charging = MagicMock(return_value=True)
    adapter.is_self_charging = MagicMock(return_value=False)
    adapter._device = MagicMock(_current_setpoint=32)
    await rec.reconcile_and_apply(
        _decision(ChargerIntent.CHARGE_MAX), adapter, _power(22000.0), now=100.0)
    # heartbeat due (last_write_at=0) → a refresh write at max
    adapter.command_current.assert_called_once_with(32)


# ─────────────────────────────────────────────────────────────────
# Task 4 — wire reconciler into actuate() as optional parameter
# ─────────────────────────────────────────────────────────────────

from custom_components.solar_energy_management.coordinator.actuate import actuate


@pytest.mark.asyncio
async def test_actuate_delegates_to_reconciler_when_provided():
    rec = _rec()
    adapter = _mock_adapter()
    adapter.actual_charging = MagicMock(return_value=False)
    adapter.is_self_charging = MagicMock(return_value=False)
    # IDLE + open contactor → reconciler issues nothing
    await actuate(_decision(ChargerIntent.IDLE), adapter, _power(0.0), reconciler=rec)
    adapter.command_disable.assert_not_called()


@pytest.mark.asyncio
async def test_actuate_legacy_path_unchanged_without_reconciler():
    adapter = _mock_adapter()
    adapter.is_self_charging = MagicMock(return_value=False)
    adapter.reset_idle_debounce = MagicMock()
    # CHARGE_MAX with no reconciler → legacy dispatch calls command_max
    await actuate(_decision(ChargerIntent.CHARGE_MAX), adapter, _power(0.0))
    adapter.command_max.assert_awaited_once()


def test_off_not_drawing_emits_nothing():
    """mode=off + EV unplugged/contactor open → zero service calls (the
    primary production scenario; must not fall through to DISABLE)."""
    rec = _rec()
    for cycle in range(10):
        actions = rec.reconcile(DesiredState.OFF, 0, _obs(charging=False), now=cycle * 10.0)
        assert actions == [Action(ActionKind.NONE)], f"cycle {cycle} spammed: {actions}"


@pytest.mark.asyncio
async def test_start_arms_failsafe_once():
    rec = _rec()
    adapter = _mock_adapter()
    adapter.actual_charging = MagicMock(side_effect=[False, True, True])
    adapter.is_self_charging = MagicMock(return_value=False)
    adapter._device = MagicMock(_current_setpoint=10)
    adapter.arm_failsafe = AsyncMock()
    # cycle 1: not charging → START arms failsafe
    await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_AT_AMPS, 10),
                                  adapter, _power(0.0), now=0.0)
    adapter.arm_failsafe.assert_awaited_once()
    # cycle 2: charging steady → no re-arm
    await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_AT_AMPS, 10),
                                  adapter, _power(7000.0), now=1.0)
    adapter.arm_failsafe.assert_awaited_once()


@pytest.mark.asyncio
async def test_failsafe_armed_once_per_charge_episode_not_on_transient_drop():
    """A transient observed-drop while desired stays CHARGE must NOT
    re-START / re-arm the failsafe. The failsafe is armed once on the
    idle→charge transition; recovery from a mid-charge drop rides the
    heartbeat WRITE (command_current re-opens a dropped session and keeps
    the already-armed failsafe fed). Re-arming every drop would be the
    keba.set_failsafe spam this design removes."""
    rec = _rec()
    adapter = _mock_adapter()
    adapter.is_self_charging = MagicMock(return_value=False)
    adapter._device = MagicMock(_current_setpoint=10)
    adapter.arm_failsafe = AsyncMock()
    # transition into charge → START + arm once
    adapter.actual_charging = MagicMock(return_value=True)
    await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_AT_AMPS, 10),
                                  adapter, _power(7000.0), now=0.0)
    assert adapter.arm_failsafe.await_count == 1
    # box drops out while we still want CHARGE → NO re-arm (rides heartbeat)
    adapter.actual_charging = MagicMock(return_value=False)
    for cycle in range(1, 6):
        await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_AT_AMPS, 10),
                                      adapter, _power(0.0), now=float(cycle))
    assert adapter.arm_failsafe.await_count == 1  # still 1 — no re-arm spam
    # only a real idle→charge transition re-arms
    await rec.reconcile_and_apply(_decision(ChargerIntent.IDLE), adapter,
                                  _power(0.0), now=10.0)
    await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_AT_AMPS, 10),
                                  adapter, _power(0.0), now=11.0)
    assert adapter.arm_failsafe.await_count == 2


@pytest.mark.asyncio
async def test_charge_never_drawing_starts_once_then_heartbeat_no_respam():
    """REGRESSION (HA-TEST 2026-06-21): a charger that never reports
    drawing (mock, ramp lag, or a full-but-plugged car held in a deadline
    mode) must START exactly once, then only heartbeat-WRITE — NOT re-START
    + re-arm-failsafe every cycle. 100 cycles, START gated on transition."""
    rec = _rec()
    adapter = _mock_adapter()
    adapter.is_self_charging = MagicMock(return_value=False)
    adapter.actual_charging = MagicMock(return_value=False)  # never draws
    adapter._device = MagicMock(_current_setpoint=6)
    adapter.arm_failsafe = AsyncMock()
    for cycle in range(100):
        await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_AT_AMPS, 6),
                                      adapter, _power(0.0), now=cycle * 10.0)
    assert adapter.arm_failsafe.await_count == 1, "failsafe re-armed every cycle (spam)"
    # writes are heartbeat-paced (5s heartbeat, 10s cycles → ~1/cycle), not 0,
    # so the device watchdog stays fed — but no START/arm storm.
    assert adapter.command_current.call_count >= 1


@pytest.mark.asyncio
async def test_charge_max_drift_corrects():
    rec = _rec()
    adapter = _mock_adapter(max_a=32)
    adapter.is_self_charging = MagicMock(return_value=False)
    adapter.actual_charging = MagicMock(return_value=True)
    adapter.arm_failsafe = AsyncMock()
    adapter._device = MagicMock(_current_setpoint=32)
    # establish the charge episode (START) so the next cycle exercises drift
    await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_MAX),
                                  adapter, _power(22000.0), now=0.0)
    adapter.command_current.reset_mock()
    # box reverted to 6 A failsafe floor while we still want max → re-assert 32
    adapter._device._current_setpoint = 6
    await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_MAX),
                                  adapter, _power(4000.0), now=1.0)
    adapter.command_current.assert_called_once_with(32)


# ─────────────────────────────────────────────────────────────────
# #536 — enable-switch reconciliation (Wallbox: commanded but 0 W)
# ─────────────────────────────────────────────────────────────────
#
# A switch-controlled charger (Wallbox: number current entity +
# switch.charging_enable) was started once via start_session and the
# enable switch was never re-asserted: _session_active latched True, so
# if the switch went off (Wallbox auto-pause / lock / eco-smart) SEM wrote
# the current forever with the contactor open → commanded 16A, 0W (#536).
# The reconciler must reconcile the ACTUAL enable-switch state.

from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    ActionKind as _AK, ObservedState as _OS,
)


def _obs_en(enabled, controllable=True, charging=False, setpoint=0, power=0.0):
    return _OS(charging=charging, setpoint_a=setpoint, self_charging=False,
              power_w=power, enabled=enabled, enable_controllable=controllable)


def test_charge_reasserts_enable_when_switch_off():
    """desired CHARGE + enable switch OFF → emit ENABLE (re-assert)."""
    rec = _rec()
    actions = rec.reconcile(DesiredState.CHARGE, 16, _obs_en(enabled=False), now=100.0)
    assert any(a.kind is _AK.ENABLE for a in actions), actions


def test_charge_no_enable_when_switch_on_even_if_not_drawing():
    """Full-but-plugged car: switch ON, drawing 0 W → NO ENABLE churn
    (keys on the switch state, not on power)."""
    rec = _rec()
    actions = rec.reconcile(DesiredState.CHARGE, 16,
                            _obs_en(enabled=True, charging=False, power=0.0), now=100.0)
    assert not any(a.kind is _AK.ENABLE for a in actions), actions


def test_charge_no_enable_action_when_charger_has_no_switch():
    """KEBA / service charger (no start-stop switch) → enabled=None → no
    ENABLE action (existing session/failsafe path unaffected)."""
    rec = _rec()
    actions = rec.reconcile(DesiredState.CHARGE, 16, _obs_en(enabled=None), now=100.0)
    assert not any(a.kind is _AK.ENABLE for a in actions), actions


def test_charge_enable_uncontrollable_surfaces_repair():
    """Switch present but unavailable/unknown (locked / eco-smart) →
    REPORT_ENABLE_BLOCKED so it's surfaced, not silent."""
    rec = _rec()
    actions = rec.reconcile(DesiredState.CHARGE, 16,
                            _obs_en(enabled=None, controllable=False), now=100.0)
    assert any(a.kind is _AK.REPORT_ENABLE_BLOCKED for a in actions), actions


def test_idle_does_not_emit_enable():
    """desired IDLE/OFF never emits ENABLE regardless of switch state."""
    rec = _rec()
    a1 = rec.reconcile(DesiredState.IDLE, 0, _obs_en(enabled=False), now=10.0)
    a2 = rec.reconcile(DesiredState.OFF, 0, _obs_en(enabled=True, charging=True, power=4000), now=20.0)
    assert not any(a.kind is _AK.ENABLE for a in a1 + a2)


@pytest.mark.asyncio
async def test_apply_enable_calls_adapter_ensure_enabled():
    """ENABLE action → adapter.ensure_enabled() awaited; then current still written."""
    rec = _rec()
    adapter = _mock_adapter()
    adapter.actual_charging = MagicMock(return_value=False)
    adapter.is_self_charging = MagicMock(return_value=False)
    adapter.ensure_enabled = AsyncMock()
    adapter.enable_state = MagicMock(return_value=(False, True))  # switch off, controllable
    adapter._device = MagicMock(_current_setpoint=0)
    await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_AT_AMPS, 16),
                                  adapter, _power(0.0), now=100.0)
    adapter.ensure_enabled.assert_awaited()


@pytest.mark.asyncio
async def test_apply_no_ensure_enabled_when_switch_on():
    rec = _rec()
    adapter = _mock_adapter()
    adapter.actual_charging = MagicMock(return_value=True)
    adapter.is_self_charging = MagicMock(return_value=False)
    adapter.ensure_enabled = AsyncMock()
    adapter.enable_state = MagicMock(return_value=(True, True))  # switch on
    adapter._device = MagicMock(_current_setpoint=16)
    await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_AT_AMPS, 16),
                                  adapter, _power(11000.0), now=100.0)
    adapter.ensure_enabled.assert_not_awaited()


# ─── #536 adapter-level enable_state / ensure_enabled (real methods) ───
from types import SimpleNamespace
from custom_components.solar_energy_management.devices.base import CurrentControlDevice
from custom_components.solar_energy_management.coordinator.charger_adapters import adapter_for


def _wallbox_device(switch_state):
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.services.has_service = MagicMock(return_value=True)
    hass.states.get = MagicMock(
        side_effect=lambda eid: SimpleNamespace(state=switch_state)
        if eid == "switch.wb_enable" and switch_state is not None else None)
    dev = CurrentControlDevice(
        hass=hass, device_id="wb", name="WB", priority=5, min_current=6.0,
        max_current=32.0, phases=3, voltage=230.0, power_entity_id="sensor.p",
        charger_service="0", charger_service_entity_id=None,
        current_entity_id="number.wb_current")
    dev.start_stop_entity = "switch.wb_enable"
    return dev, hass


def test_adapter_enable_state_off_on_unavailable():
    dev_off, _ = _wallbox_device("off")
    assert adapter_for(dev_off).enable_state() == (False, True)
    dev_on, _ = _wallbox_device("on")
    assert adapter_for(dev_on).enable_state() == (True, True)
    dev_unavail, _ = _wallbox_device("unavailable")
    assert adapter_for(dev_unavail).enable_state() == (None, False)
    dev_missing, _ = _wallbox_device(None)  # entity returns no state
    assert adapter_for(dev_missing).enable_state() == (None, False)


def test_adapter_enable_state_none_when_no_switch():
    hass = MagicMock(); hass.services.has_service = MagicMock(return_value=True)
    dev = CurrentControlDevice(
        hass=hass, device_id="keba", name="K", priority=5, min_current=6.0,
        max_current=32.0, phases=3, voltage=230.0, power_entity_id="sensor.p",
        charger_service="keba.set_current", charger_service_entity_id=None,
        current_entity_id=None)
    # no start_stop_entity → enable reconciliation is N/A
    assert adapter_for(dev).enable_state() == (None, True)


@pytest.mark.asyncio
async def test_adapter_ensure_enabled_turns_switch_on():
    dev, hass = _wallbox_device("off")
    await adapter_for(dev).ensure_enabled()
    hass.services.async_call.assert_awaited_with(
        "switch", "turn_on", {"entity_id": "switch.wb_enable"}, blocking=True)


# ─────────────────────────────────────────────────────────────────
# Task 11 — reconciler-native self-resume coverage (was phantom via
# the now-dead _execute_ev_control / legacy actuate path: #315/#346/#353)
# ─────────────────────────────────────────────────────────────────


def test_off_self_charging_disables():
    """#315: box drawing against an OFF intent (self-resume on plug-in)
    must be force-disabled — even when the power-based `charging` flag is
    False, `self_charging` (last intent was IDLE/DISABLE + power>handshake)
    counts as drawing."""
    rec = _rec()
    actions = rec.reconcile(DesiredState.OFF, 0,
                            _obs(charging=False, self_charging=True, power=4000.0), now=0.0)
    assert actions == [Action(ActionKind.DISABLE)]


def test_idle_self_charging_flicker_then_disable():
    """#353: self-charging against an IDLE intent gets the flicker hold
    then a confirmed DISABLE (same path as power-based drawing)."""
    rec = _rec()
    for cyc in range(1, 4):  # < threshold → hold
        a = rec.reconcile(DesiredState.IDLE, 0,
                          _obs(charging=False, self_charging=True, power=4000.0), now=cyc*10.0)
        assert a == [Action(ActionKind.NONE)], f"cyc {cyc}: {a}"
    a = rec.reconcile(DesiredState.IDLE, 0,
                      _obs(charging=False, self_charging=True, power=4000.0), now=40.0)
    assert a == [Action(ActionKind.DISABLE)]


def test_charge_self_charging_does_not_disable_first():
    """#346 follow-up / MED gap: when we now WANT to charge and the box is
    already drawing (self-resumed during a prior idle), the reconciler must
    NOT disable-then-charge — it proceeds straight to charging (the desired
    outcome is already happening; interrupting it would be churn). The
    correct setpoint is asserted by START/WRITE. Pins the intended divergence
    from the legacy disable-before-any-intent guard."""
    rec = _rec()
    actions = rec.reconcile(DesiredState.CHARGE, 10,
                            _obs(charging=True, setpoint=10, self_charging=True, power=4000.0), now=0.0)
    assert not any(a.kind is ActionKind.DISABLE for a in actions), actions
    assert any(a.kind in (ActionKind.START_AND_WRITE, ActionKind.WRITE_CURRENT) for a in actions), actions
