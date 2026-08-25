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
    # #553: the flicker grace only exists for winding down SEM's own stop —
    # establish an active charge first (at boot, idle is settled and a rogue
    # draw is disabled immediately; see test_boot_rogue_draw below).
    rec.reconcile(DesiredState.CHARGE, 10,
                  _obs(charging=True, power=6000.0, setpoint=10), now=0.0)
    # cycles 1..3 (< threshold 4): flicker hold → NONE
    for cycle in range(1, 4):
        actions = rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=6000.0),
                                now=cycle * 10.0)
        assert actions == [Action(ActionKind.NONE)], f"cycle {cycle}: {actions}"
    # cycle 4 (>= threshold): confirmed real → DISABLE
    actions = rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=6000.0), now=40.0)
    assert actions == [Action(ActionKind.DISABLE)]


def test_boot_rogue_draw_disables_first_cycle():
    """#553 — at boot SEM has commanded nothing: a draw found while
    desired=IDLE is not our wind-down; DISABLE on the very first cycle."""
    rec = _rec()
    actions = rec.reconcile(DesiredState.IDLE, 0,
                            _obs(charging=True, power=6000.0), now=0.0)
    assert actions == [Action(ActionKind.DISABLE)]


def test_idle_settled_then_draw_disables_immediately():
    # #552 INVERSION of the old test_idle_resets_flicker_counter_when_box_stops:
    # once idle has SETTLED (box observed open + no draw), a newly-appearing
    # draw is a rogue self-start (KEBA auto-start, #315) — it gets DISABLE on
    # the FIRST cycle, not a fresh flicker-grace. The grace is reserved for
    # winding down a session SEM itself just stopped.
    rec = _rec()
    # At boot idle is already settled (#553), so this first draw is itself
    # rogue → immediate DISABLE (review M2: assert it, don't mislabel it).
    a0 = rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=6000.0), now=10.0)
    assert a0 == [Action(ActionKind.DISABLE)]
    rec.reconcile(DesiredState.IDLE, 0, _obs(charging=False), now=20.0)  # settled again
    # (#763 round 3) A rogue edge 20 s after our last DISABLE stays inside
    # the evcc-parity reassert dwell: the intent stands but the write is
    # deferred — hammering the bridge every cycle was the old behavior
    # this changed. Parity with OFF holds: both rows share the dwell.
    actions = rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=6000.0), now=30.0)
    assert Action(ActionKind.DISABLE) not in actions
    # ...and the re-assert lands once the dwell has passed.
    actions = rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=6000.0), now=71.0)
    assert actions == [Action(ActionKind.DISABLE)]


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
    # #553: grace requires a wind-down — start a charge episode first.
    rec.reconcile(DesiredState.CHARGE, 10,
                  _obs(charging=True, power=4000.0, setpoint=10), now=0.0)
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


# ─────────────────────────────────────────────────────────────────
# #536 — enable BACKOFF: don't fight a self-pausing charger forever
# (Wallbox Eco-Smart / Autostart flips its own switch back → oscillation)
# ─────────────────────────────────────────────────────────────────


def _rec_enable(max_attempts=3, retry=300.0):
    return ChargerReconciler(charger_id="ev_charger", heartbeat_s=5.0,
                             max_enable_attempts=max_attempts,
                             enable_retry_interval_s=retry)


def test_enable_retries_max_then_backs_off():
    rec = _rec_enable(max_attempts=3)
    for c in range(3):  # try hard for max_attempts cycles
        a = rec.reconcile(DesiredState.CHARGE, 16, _obs_en(enabled=False), now=c*10.0)
        assert any(x.kind is _AK.ENABLE for x in a), f"cycle {c}: {a}"
    for c in range(3, 8):  # then stop fighting, surface
        a = rec.reconcile(DesiredState.CHARGE, 16, _obs_en(enabled=False), now=c*10.0)
        assert any(x.kind is _AK.REPORT_ENABLE_BLOCKED for x in a), f"cycle {c}: {a}"
        assert not any(x.kind is _AK.ENABLE for x in a), f"cycle {c}: {a}"


def test_enable_probes_once_after_retry_interval():
    rec = _rec_enable(max_attempts=2, retry=300.0)
    rec.reconcile(DesiredState.CHARGE, 16, _obs_en(enabled=False), now=0.0)   # ENABLE
    rec.reconcile(DesiredState.CHARGE, 16, _obs_en(enabled=False), now=10.0)  # ENABLE, gave_up=10
    a = rec.reconcile(DesiredState.CHARGE, 16, _obs_en(enabled=False), now=200.0)  # within window
    assert not any(x.kind is _AK.ENABLE for x in a)
    a = rec.reconcile(DesiredState.CHARGE, 16, _obs_en(enabled=False), now=320.0)  # window elapsed
    assert any(x.kind is _AK.ENABLE for x in a)


def test_enable_backoff_resets_when_switch_sticks():
    rec = _rec_enable(max_attempts=2)
    rec.reconcile(DesiredState.CHARGE, 16, _obs_en(enabled=False), now=0.0)
    rec.reconcile(DesiredState.CHARGE, 16, _obs_en(enabled=False), now=10.0)  # exhausted
    rec.reconcile(DesiredState.CHARGE, 16, _obs_en(enabled=True, charging=True, power=4000), now=20.0)
    a = rec.reconcile(DesiredState.CHARGE, 16, _obs_en(enabled=False), now=30.0)
    assert any(x.kind is _AK.ENABLE for x in a)  # fresh round, not immediately backed off


def test_enable_backoff_resets_on_idle():
    rec = _rec_enable(max_attempts=2)
    rec.reconcile(DesiredState.CHARGE, 16, _obs_en(enabled=False), now=0.0)
    rec.reconcile(DesiredState.CHARGE, 16, _obs_en(enabled=False), now=10.0)  # exhausted
    rec.reconcile(DesiredState.IDLE, 0, _obs_en(enabled=False), now=20.0)     # leave CHARGE → reset
    a = rec.reconcile(DesiredState.CHARGE, 16, _obs_en(enabled=False), now=30.0)
    assert any(x.kind is _AK.ENABLE for x in a)  # fresh round


def test_charge_uncontrollable_switch_suppresses_charge_actions():
    """Switch unavailable/locked → REPORT_ENABLE_BLOCKED ONLY, no charge
    action — else a successful command_current clears the repair we just
    raised, flapping it every cycle (reviewer Warning 2)."""
    rec = _rec()
    actions = rec.reconcile(DesiredState.CHARGE, 16,
                            _obs_en(enabled=None, controllable=False), now=0.0)
    assert actions == [Action(_AK.REPORT_ENABLE_BLOCKED)]


# ─── #536 effective-max (CHARGE_MAX clamp drift) ───
def test_effective_max_current_clamps_to_entity_max():
    """CHARGE_MAX must resolve to the entity-clamped max, not the hardware
    max — else the reconciler drifts forever (config 32 A, entity caps 16 A)."""
    from types import SimpleNamespace
    hass = MagicMock(); hass.services.has_service = MagicMock(return_value=True)
    hass.states.get = MagicMock(side_effect=lambda eid: SimpleNamespace(
        attributes={"min": 6, "max": 16}) if eid == "number.wb_current" else None)
    dev = CurrentControlDevice(
        hass=hass, device_id="wb", name="WB", priority=5, min_current=6.0,
        max_current=32.0, phases=3, voltage=230.0, power_entity_id="sensor.p",
        charger_service=None, charger_service_entity_id=None,
        current_entity_id="number.wb_current")
    assert dev.effective_max_current() == 16.0
    assert adapter_for(dev).max_current_a == 16


def test_effective_max_current_no_entity_returns_config_max():
    """Service-controlled charger (KEBA, no current entity) → config max."""
    hass = MagicMock(); hass.services.has_service = MagicMock(return_value=True)
    dev = CurrentControlDevice(
        hass=hass, device_id="k", name="K", priority=5, min_current=6.0,
        max_current=32.0, phases=3, voltage=230.0, power_entity_id="sensor.p",
        charger_service="keba.set_current", charger_service_entity_id=None,
        current_entity_id=None)
    assert dev.effective_max_current() == 32.0
    assert adapter_for(dev).max_current_a == 32


# ── #763 — the stop-war ceasefire ────────────────────────────────────────────
# onkelfu's Mercedes + Modbus KEBA: SEM's stop WORKS (contactor opens), the
# box re-closes on the car's retry at its stored 6 A, SEM stops it again —
# each round-trip aborts one handshake, and after ~2 h of 0↔4.1 kW the car
# latches a charging fault only a physical replug clears. The #536 backoff
# exists for the ENABLE direction; this is its mirror: after N successful
# stop→redraw round-trips, SEM stands down for a long window and SAYS SO,
# because a strobing contactor is worse for the car than 6 A of unplanned
# charge. A round-trip = the draw REAPPEARING after our stop settled; a
# steady draw that never stops is the #627/#548 family, not this.

def _war_round(rec, t):
    """One full stop-war round-trip at time t: box re-closed (draw), SEM
    disables, box opens (settled)."""
    a = rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=4100.0), now=t)
    rec.reconcile(DesiredState.IDLE, 0, _obs(charging=False), now=t + 5)
    return a


def test_three_stop_war_rounds_trigger_ceasefire():
    # (#763 round 3) rounds spaced ≥ the reassert dwell — the old 20-s
    # spacing was a fast-KEBA-era artifact; real wars run minutes apart.
    rec = _rec()
    assert _war_round(rec, 10.0) == [Action(ActionKind.DISABLE)]
    assert _war_round(rec, 110.0) == [Action(ActionKind.DISABLE)]
    assert _war_round(rec, 210.0) == [Action(ActionKind.DISABLE)]
    # Fourth self-start within the window: ceasefire — no DISABLE, say why.
    actions = rec.reconcile(
        DesiredState.IDLE, 0, _obs(charging=True, power=4100.0), now=270.0)
    assert Action(ActionKind.DISABLE) not in actions
    assert actions[0].kind is ActionKind.REPORT_STOP_WAR


def test_ceasefire_holds_for_the_backoff_window():
    rec = _rec()
    for t in (10.0, 110.0, 210.0):
        _war_round(rec, t)
    rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=4100.0), now=270.0)
    # Deep inside the backoff the box may draw — SEM does not cut it.
    actions = rec.reconcile(
        DesiredState.IDLE, 0, _obs(charging=True, power=4100.0), now=900.0)
    assert Action(ActionKind.DISABLE) not in actions


def test_ceasefire_expires_into_one_probe():
    rec = _rec()
    for t in (10.0, 110.0, 210.0):
        _war_round(rec, t)
    rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=4100.0), now=270.0)
    # After the window one DISABLE probe goes out — if the box comes back
    # again, the next ceasefire follows without re-counting from zero.
    actions = rec.reconcile(
        DesiredState.IDLE, 0, _obs(charging=True, power=4100.0), now=270.0 + 1801.0)
    assert actions == [Action(ActionKind.DISABLE)]


def test_quiet_spell_resets_the_war_counter():
    # (#763 beta.7) The quiet horizon is an HOUR now, not 15 minutes —
    # onkelfu's Mercedes retried every ~12 min, so a sub-hour "quiet"
    # is just a slow-retrying car between attempts, not a surrendered
    # box. Same scenario, honest timescale.
    rec = _rec()
    _war_round(rec, 10.0)
    _war_round(rec, 110.0)
    rec.reconcile(DesiredState.IDLE, 0, _obs(charging=False), now=4000.0)
    assert _war_round(rec, 4010.0) == [Action(ActionKind.DISABLE)]
    assert _war_round(rec, 4110.0) == [Action(ActionKind.DISABLE)]
    # Only the third round of the NEW episode may trigger the ceasefire —
    # proving the old rounds aged out.
    actions = rec.reconcile(
        DesiredState.IDLE, 0, _obs(charging=True, power=4100.0), now=4210.0)
    assert actions == [Action(ActionKind.DISABLE)]


def test_a_charge_episode_ends_the_war():
    rec = _rec()
    for t in (10.0, 110.0, 210.0):
        _war_round(rec, t)
    # SEM wants to charge again — the war state must not suppress it.
    actions = rec.reconcile(
        DesiredState.CHARGE, 10, _obs(charging=False), now=270.0)
    assert actions == [Action(ActionKind.START_AND_WRITE, 10)]
    # And back to idle: a fresh episode counts from zero.
    rec.reconcile(DesiredState.IDLE, 0, _obs(charging=False), now=280.0)
    assert _war_round(rec, 340.0)[0].kind in (ActionKind.NONE, ActionKind.DISABLE)


def test_user_off_gets_the_same_protection():
    """The OFF row disables every cycle too — same box, same car, same
    fault. The ceasefire covers both."""
    rec = _rec()
    for t in (10.0, 110.0, 210.0):
        a = rec.reconcile(DesiredState.OFF, 0, _obs(charging=True, power=4100.0), now=t)
        # (#823) this synthetic war is EXACTLY periodic, so from the second
        # round it also carries the failsafe advisory — which is correct: a
        # box returning on a constant interval IS the failsafe signature.
        # The pin here is the stop behaviour, so filter the advisory.
        a = [x for x in a
             if x.kind is not ActionKind.REPORT_FAILSAFE_SUSPECTED]
        assert a == [Action(ActionKind.DISABLE)]
        rec.reconcile(DesiredState.OFF, 0, _obs(charging=False), now=t + 5)
    actions = rec.reconcile(
        DesiredState.OFF, 0, _obs(charging=True, power=4100.0), now=270.0)
    assert Action(ActionKind.DISABLE) not in actions
    assert actions[0].kind is ActionKind.REPORT_STOP_WAR


# ── #763 beta.7 recurrence (onkelfu, 18.08): the quiet-reset raced the car ───
# The ceasefire was tuned on the KEBA's rapid retries (rounds seconds
# apart). onkelfu's Mercedes retries every ~12 minutes — SLOWER than the
# old 600 s quiet-reset — so every burst counted from zero, the ceasefire
# never engaged, and the car faulted again on beta.7 (two STOP×3 warnings
# 717 s apart in his diagnostics). Quiet is exactly what a slow-retrying
# car looks like between retries; only a LONG quiet, a disconnect, or SEM
# itself wanting CHARGE ends a war.


def _obs_conn(connected, charging=False, power=0.0):
    return ObservedState(charging=charging, setpoint_a=0,
                         self_charging=False, power_w=power,
                         connected=connected)


def test_a_slow_retrying_car_still_reaches_ceasefire():
    rec = _rec()
    assert _war_round(rec, 0.0) == [Action(ActionKind.DISABLE)]
    assert _war_round(rec, 717.0) == [Action(ActionKind.DISABLE)]
    assert _war_round(rec, 1434.0) == [Action(ActionKind.DISABLE)]
    actions = rec.reconcile(
        DesiredState.IDLE, 0, _obs(charging=True, power=4100.0), now=2151.0)
    assert Action(ActionKind.DISABLE) not in actions
    assert actions[0].kind is ActionKind.REPORT_STOP_WAR


def test_disconnect_ends_the_war():
    """Unplugging is the one true end of a war — the handshake partner
    left. A fresh plug-in must count from zero."""
    rec = _rec()
    for t in (10.0, 110.0, 210.0):
        _war_round(rec, t)
    rec.reconcile(DesiredState.IDLE, 0, _obs_conn(False), now=220.0)
    # Replugged: three NEW rounds before any ceasefire.
    assert _war_round(rec, 300.0) == [Action(ActionKind.DISABLE)]
    assert _war_round(rec, 400.0) == [Action(ActionKind.DISABLE)]
    assert _war_round(rec, 500.0) == [Action(ActionKind.DISABLE)]
    actions = rec.reconcile(
        DesiredState.IDLE, 0, _obs(charging=True, power=4100.0), now=600.0)
    assert actions[0].kind is ActionKind.REPORT_STOP_WAR


def test_consecutive_ceasefires_escalate_the_backoff():
    """A war that survives its first ceasefire is persistent — each
    further ceasefire doubles the stand-down, so the abort rate decays
    instead of settling at one abort per backoff forever."""
    rec = _rec()
    for t in (10.0, 110.0, 210.0):
        _war_round(rec, t)
    rec.reconcile(DesiredState.IDLE, 0,
                  _obs(charging=True, power=4100.0), now=270.0)  # ceasefire 1
    # Probe after the first 1800 s window…
    a = rec.reconcile(DesiredState.IDLE, 0,
                      _obs(charging=True, power=4100.0), now=270.0 + 1801.0)
    assert a == [Action(ActionKind.DISABLE)]
    rec.reconcile(DesiredState.IDLE, 0, _obs(charging=False),
                  now=270.0 + 1810.0)                             # stop takes
    # …box returns: ceasefire 2, now 2× long.
    a = rec.reconcile(DesiredState.IDLE, 0,
                      _obs(charging=True, power=4100.0), now=270.0 + 1900.0)
    assert a[0].kind is ActionKind.REPORT_STOP_WAR
    inside_2x = 270.0 + 1900.0 + 1801.0    # would have expired at 1× pace
    a = rec.reconcile(DesiredState.IDLE, 0,
                      _obs(charging=True, power=4100.0), now=inside_2x)
    assert Action(ActionKind.DISABLE) not in a
    after_2x = 270.0 + 1900.0 + 3601.0
    a = rec.reconcile(DesiredState.IDLE, 0,
                      _obs(charging=True, power=4100.0), now=after_2x)
    assert a == [Action(ActionKind.DISABLE)]


def test_war_state_is_snapshotable_for_diagnostics():
    """(#763 beta.7) onkelfu's dump showed empty charge_stability giveup
    fields and NOTHING from the reconciler — the machinery that actually
    owns the stop war was invisible, and he reasonably concluded it never
    engaged. The war state must ride the diagnostics download."""
    rec = _rec()
    for t in (10.0, 30.0, 50.0):
        _war_round(rec, t)
    rec.reconcile(DesiredState.IDLE, 0,
                  _obs(charging=True, power=4100.0), now=70.0)  # ceasefire
    snap = rec.snapshot_war(now=100.0)
    assert snap["rounds"] == 4
    assert snap["ceasefires"] == 1
    assert snap["backoff_remaining_s"] == pytest.approx(1770.0)
    assert snap["stop_commanded_while_drawing"] >= 0


# ── #763 round 3 — evcc-parity reassert dwell ────────────────────────────────
# evcc floors ALL corrective contactor commands at chargerSwitchDuration
# (60 s): its syncCharger logs the self-start, re-syncs its own belief, and
# lets the next control tick re-disable — never faster than the floor. Our
# settled-rogue row re-issued DISABLE every 10-s cycle while a burst
# lasted: 3-6 redundant writes through the user's bridge per burst, each a
# fresh chance to abort the car's handshake. One DISABLE per dwell is
# enough — the box either obeys it or the war accounting handles it.


def test_disable_reasserts_at_the_dwell_not_every_cycle():
    rec = _rec()
    a = rec.reconcile(DesiredState.IDLE, 0,
                      _obs(charging=True, power=4100.0), now=1000.0)
    assert a == [Action(ActionKind.DISABLE)]
    for t in (1010.0, 1020.0, 1030.0, 1040.0, 1050.0):
        a = rec.reconcile(DesiredState.IDLE, 0,
                          _obs(charging=True, power=4100.0), now=t)
        assert Action(ActionKind.DISABLE) not in a, f"re-spammed at t={t}"
    a = rec.reconcile(DesiredState.IDLE, 0,
                      _obs(charging=True, power=4100.0), now=1061.0)
    assert a == [Action(ActionKind.DISABLE)]


def test_user_off_shares_the_dwell():
    rec = _rec()
    a = rec.reconcile(DesiredState.OFF, 0,
                      _obs(charging=True, power=4100.0), now=1000.0)
    assert a == [Action(ActionKind.DISABLE)]
    a = rec.reconcile(DesiredState.OFF, 0,
                      _obs(charging=True, power=4100.0), now=1010.0)
    assert Action(ActionKind.DISABLE) not in a
