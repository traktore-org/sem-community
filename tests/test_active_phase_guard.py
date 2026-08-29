"""Regression tests for the active EV write gate of the dual phase guard."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from custom_components.solar_energy_management.coordinator.active_phase_guard import (
    ActivePhaseGuard,
    filter_charger_decision,
    update_active_phase_guard,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
)


def _decision(intent=ChargerIntent.CHARGE_AT_AMPS, amps=16):
    return ChargerDecision(
        charger_id="zaptec",
        mode="always_max",
        intent=intent,
        commanded_amps=amps,
        budget_w=amps * 3 * 230,
        reason="test decision",
    )


def _guard(*, safe=True, fresh=True, margin=4.0, reason="", phase_count=3):
    phase = {
        "current_a": 16.0 - margin,
        "margin_a": margin,
        "limit_a": 16.0,
        "safe": safe,
        "data_fresh": fresh,
        "reason": None if safe else "over_limit",
        "source": "direct_current",
    }
    return {
        "mode": "observer",
        "topology": "hybrid_load_port",
        "phase_count": phase_count,
        "read_only": True,
        "safe": safe,
        "data_fresh": fresh,
        "stop_reason": reason,
        "grid": {f"l{n}": dict(phase) for n in range(1, phase_count + 1)},
        "inverter": {f"l{n}": dict(phase) for n in range(1, phase_count + 1)},
    }


def _config(**overrides):
    config = {
        "phase_guard_enabled": True,
        "phase_guard_enforcement_enabled": True,
        "phase_guard_recovery_margin_a": 2.0,
        "phase_guard_recovery_cycles": 3,
    }
    config.update(overrides)
    return config


def _adapter(*, phases=3, voltage=230, minimum=6, maximum=32):
    return SimpleNamespace(
        phases=phases,
        voltage=voltage,
        min_current_a=minimum,
        max_current_a=maximum,
    )


def _power(amps, *, phases=3, voltage=230):
    return SimpleNamespace(power_w=amps * phases * voltage)


def test_observer_mode_never_changes_the_charger_decision():
    enforcer = ActivePhaseGuard()
    decision = _decision()

    snapshot = enforcer.update(
        _guard(safe=False, fresh=False, reason="grid:l1:unavailable"),
        _config(phase_guard_enforcement_enabled=False),
    )

    assert snapshot["mode"] == "observer"
    assert snapshot["read_only"] is True
    assert enforcer.filter_decision(decision) is decision


def test_global_observer_mode_remains_read_only_even_if_enforcement_is_selected():
    enforcer = ActivePhaseGuard()
    decision = _decision()

    snapshot = enforcer.update(
        _guard(safe=False, fresh=False, reason="grid:l1:unavailable"),
        _config(observer_mode=True),
    )

    assert snapshot["mode"] == "observer"
    assert snapshot["read_only"] is True
    assert enforcer.filter_decision(decision) is decision


def test_evaluator_exception_fails_closed_instead_of_breaking_control_cycle():
    coord = SimpleNamespace(
        config=_config(),
        hass=SimpleNamespace(states=object()),
        _observer_mode=False,
    )

    with patch(
        "custom_components.solar_energy_management.coordinator.dual_phase_guard."
        "evaluate_dual_phase_guard",
        side_effect=RuntimeError("sensor registry failed"),
    ):
        snapshot = update_active_phase_guard(coord)

    assert snapshot["mode"] == "enforcing_blocked"
    assert snapshot["safe"] is False
    assert snapshot["data_fresh"] is False
    assert snapshot["stop_reason"] == "phase_guard_evaluation_failed"
    assert coord._active_phase_guard.control_authorized is False


def test_disabled_guard_skips_measurement_evaluation():
    coord = SimpleNamespace(
        config=_config(phase_guard_enabled=False),
        hass=SimpleNamespace(states=object()),
        _observer_mode=False,
    )

    with patch(
        "custom_components.solar_energy_management.coordinator.dual_phase_guard."
        "evaluate_dual_phase_guard",
        side_effect=AssertionError("disabled guard must not read sensors"),
    ) as evaluate:
        snapshot = update_active_phase_guard(coord)

    evaluate.assert_not_called()
    assert snapshot["mode"] == "disabled"
    assert snapshot["control_authorized"] is True
    assert filter_charger_decision(coord, _decision()) == _decision()


def test_enabling_after_observer_mode_still_starts_fail_closed():
    enforcer = ActivePhaseGuard()
    enforcer.update(
        _guard(margin=4.0),
        _config(phase_guard_enforcement_enabled=False),
    )

    snapshot = enforcer.update(_guard(margin=4.0), _config())

    assert snapshot["mode"] == "enforcing_recovery"
    assert snapshot["control_authorized"] is False
    assert snapshot["recovery_cycles"] == 1


def test_enforcement_starts_fail_closed_until_safe_recovery_hold_completes():
    enforcer = ActivePhaseGuard()

    first = enforcer.update(_guard(margin=4.0), _config())
    second = enforcer.update(_guard(margin=4.0), _config())
    third = enforcer.update(_guard(margin=4.0), _config())

    assert first["mode"] == "enforcing_recovery"
    assert first["control_authorized"] is False
    assert second["control_authorized"] is False
    assert third["mode"] == "enforcing_armed"
    assert third["control_authorized"] is True


def test_single_phase_guard_recovers_and_clamps_using_l1_margin_only():
    enforcer = ActivePhaseGuard()
    guard = _guard(margin=4.0, phase_count=1)
    snapshots = [enforcer.update(guard, _config()) for _ in range(3)]

    filtered = enforcer.filter_decision(
        _decision(amps=16),
        adapter=_adapter(phases=1),
        power=_power(10, phases=1),
    )

    assert snapshots[-1]["mode"] == "enforcing_armed"
    assert filtered.intent is ChargerIntent.CHARGE_AT_AMPS
    assert filtered.commanded_amps == 14


def test_three_phase_charger_is_blocked_behind_single_phase_measurement_guard():
    enforcer = ActivePhaseGuard()
    for _ in range(3):
        enforcer.update(_guard(margin=4.0, phase_count=1), _config())

    filtered = enforcer.filter_decision(
        _decision(amps=16),
        adapter=_adapter(phases=3),
        power=_power(10, phases=3),
    )

    assert filtered.intent is ChargerIntent.DISABLE
    assert "phase_count_mismatch" in filtered.reason


def test_unsafe_or_stale_data_forces_immediate_disable_not_debounced_idle():
    enforcer = ActivePhaseGuard()
    for _ in range(3):
        enforcer.update(_guard(margin=4.0), _config())
    assert enforcer.control_authorized is True

    snapshot = enforcer.update(
        _guard(safe=False, fresh=False, reason="grid:l1:stale"), _config()
    )
    filtered = enforcer.filter_decision(_decision(ChargerIntent.IDLE, 0))

    assert snapshot["mode"] == "enforcing_blocked"
    assert snapshot["control_authorized"] is False
    assert filtered.intent is ChargerIntent.DISABLE
    assert filtered.commanded_amps == 0
    assert filtered.budget_w == 0
    assert filtered.bridgeable is False
    assert "grid:l1:stale" in filtered.reason


def test_any_over_limit_lane_forces_disable_for_all_charge_intents():
    enforcer = ActivePhaseGuard()
    for _ in range(3):
        enforcer.update(_guard(margin=4.0), _config())

    snapshot = _guard(safe=False, fresh=True, margin=-0.5,
                      reason="inverter:l3:over_limit")
    enforcer.update(snapshot, _config())

    for intent in (ChargerIntent.CHARGE_AT_AMPS, ChargerIntent.CHARGE_MAX):
        filtered = enforcer.filter_decision(_decision(intent))
        assert filtered.intent is ChargerIntent.DISABLE
        assert filtered.commanded_amps == 0


def test_existing_disable_passes_through_while_guard_is_blocked():
    enforcer = ActivePhaseGuard()
    enforcer.update(
        _guard(safe=False, fresh=False, reason="invalid_configuration"), _config()
    )
    decision = _decision(ChargerIntent.DISABLE, 0)

    assert enforcer.filter_decision(decision) is decision


def test_recovery_requires_margin_on_all_required_phases_and_resets_streak():
    enforcer = ActivePhaseGuard()
    config = _config()

    enforcer.update(_guard(margin=4.0), config)
    narrow = _guard(margin=4.0)
    narrow["inverter"]["l2"]["margin_a"] = 1.5
    waiting = enforcer.update(narrow, config)
    after_reset = enforcer.update(_guard(margin=4.0), config)

    assert waiting["mode"] == "enforcing_recovery"
    assert waiting["recovery_cycles"] == 0
    assert after_reset["recovery_cycles"] == 1
    assert after_reset["control_authorized"] is False


def test_once_armed_hysteresis_allows_operation_inside_reset_band_until_trip():
    enforcer = ActivePhaseGuard()
    for _ in range(3):
        enforcer.update(_guard(margin=4.0), _config())

    snapshot = enforcer.update(_guard(margin=0.5), _config())
    decision = _decision()

    assert snapshot["mode"] == "enforcing_armed"
    assert enforcer.filter_decision(
        decision, adapter=_adapter(), power=_power(15.5)
    ) is decision


def test_safe_write_is_clamped_to_measured_headroom_before_actuation():
    enforcer = ActivePhaseGuard()
    for _ in range(3):
        enforcer.update(_guard(margin=4.0), _config())
    enforcer.update(_guard(margin=3.0), _config())

    filtered = enforcer.filter_decision(
        _decision(ChargerIntent.CHARGE_AT_AMPS, 16),
        adapter=_adapter(),
        power=_power(8),
    )

    assert filtered.intent is ChargerIntent.CHARGE_AT_AMPS
    assert filtered.commanded_amps == 11
    assert filtered.budget_w == 11 * 3 * 230
    assert "clamped" in filtered.reason


def test_running_charger_command_is_brought_down_to_in_flight_headroom():
    enforcer = ActivePhaseGuard()
    for _ in range(3):
        enforcer.update(_guard(margin=4.0), _config())
    enforcer.update(_guard(margin=0.4), _config())

    filtered = enforcer.filter_decision(
        _decision(ChargerIntent.CHARGE_AT_AMPS, 16),
        adapter=_adapter(),
        power=_power(14),
    )

    assert filtered.intent is ChargerIntent.CHARGE_AT_AMPS
    assert filtered.commanded_amps == 14
    assert filtered.commanded_amps < 16
    assert filtered.budget_w == 14 * 3 * 230


def test_multi_charger_increases_reserve_shared_headroom_within_cycle():
    enforcer = ActivePhaseGuard()
    for _ in range(3):
        enforcer.update(_guard(margin=4.0), _config())
    enforcer.update(_guard(margin=3.0), _config())

    first = enforcer.filter_decision(
        _decision(ChargerIntent.CHARGE_AT_AMPS, 10),
        adapter=_adapter(),
        power=_power(8),
    )
    second = enforcer.filter_decision(
        ChargerDecision(
            charger_id="second",
            mode="always_max",
            intent=ChargerIntent.CHARGE_AT_AMPS,
            commanded_amps=10,
            reason="second",
        ),
        adapter=_adapter(),
        power=_power(0),
    )

    assert first.commanded_amps == 10
    assert second.intent is ChargerIntent.DISABLE
    assert "headroom" in second.reason


def test_missing_actuation_context_fails_closed_for_a_charge_write():
    enforcer = ActivePhaseGuard()
    for _ in range(3):
        enforcer.update(_guard(margin=4.0), _config())

    filtered = enforcer.filter_decision(_decision())

    assert filtered.intent is ChargerIntent.DISABLE
    assert "context_missing" in filtered.reason


def test_grid_only_snapshot_does_not_require_an_inverter_lane():
    enforcer = ActivePhaseGuard()
    guard = _guard(margin=4.0)
    guard["topology"] = "grid_only"
    guard.pop("inverter")

    snapshots = [enforcer.update(guard, _config()) for _ in range(3)]

    assert snapshots[-1]["mode"] == "enforcing_armed"
    assert snapshots[-1]["control_authorized"] is True


def test_charge_max_is_converted_to_a_headroom_clamped_amp_command():
    enforcer = ActivePhaseGuard()
    for _ in range(3):
        enforcer.update(_guard(margin=4.0), _config())
    enforcer.update(_guard(margin=3.0), _config())

    filtered = enforcer.filter_decision(
        _decision(ChargerIntent.CHARGE_MAX, 0),
        adapter=_adapter(maximum=32),
        power=_power(8),
    )

    assert filtered.intent is ChargerIntent.CHARGE_AT_AMPS
    assert filtered.commanded_amps == 11


def test_charge_max_reserves_shared_headroom_before_next_charger():
    enforcer = ActivePhaseGuard()
    for _ in range(3):
        enforcer.update(_guard(margin=4.0), _config())
    enforcer.update(_guard(margin=3.0), _config())

    first = enforcer.filter_decision(
        _decision(ChargerIntent.CHARGE_MAX, 0),
        adapter=_adapter(maximum=32),
        power=_power(8),
    )
    second = enforcer.filter_decision(
        ChargerDecision(
            charger_id="second",
            mode="always_max",
            intent=ChargerIntent.CHARGE_AT_AMPS,
            commanded_amps=10,
            reason="second",
        ),
        adapter=_adapter(),
        power=_power(0),
    )

    assert first.intent is ChargerIntent.CHARGE_AT_AMPS
    assert first.commanded_amps == 11
    assert second.intent is ChargerIntent.DISABLE
    assert "headroom_below_minimum" in second.reason


def test_headroom_below_charger_minimum_forces_disable():
    enforcer = ActivePhaseGuard()
    for _ in range(3):
        enforcer.update(_guard(margin=4.0), _config())
    enforcer.update(_guard(margin=3.0), _config())

    filtered = enforcer.filter_decision(
        _decision(ChargerIntent.CHARGE_AT_AMPS, 16),
        adapter=_adapter(minimum=6),
        power=_power(0),
    )

    assert filtered.intent is ChargerIntent.DISABLE
    assert "headroom_below_minimum" in filtered.reason


def test_non_finite_recovery_margin_configuration_fails_closed():
    enforcer = ActivePhaseGuard()

    snapshot = enforcer.update(
        _guard(margin=4.0),
        _config(phase_guard_recovery_margin_a=float("nan")),
    )

    assert snapshot["mode"] == "enforcing_blocked"
    assert snapshot["stop_reason"] == "invalid_enforcement_configuration"
    assert enforcer.filter_decision(_decision()).intent is ChargerIntent.DISABLE


def test_non_finite_phase_margin_cannot_advance_recovery():
    enforcer = ActivePhaseGuard()
    guard = _guard(margin=4.0)
    guard["grid"]["l2"]["margin_a"] = float("nan")

    snapshots = [enforcer.update(guard, _config()) for _ in range(3)]

    assert snapshots[-1]["mode"] == "enforcing_recovery"
    assert snapshots[-1]["control_authorized"] is False
    assert snapshots[-1]["recovery_cycles"] == 0


def test_malformed_snapshot_fails_closed_without_raising():
    enforcer = ActivePhaseGuard()

    snapshot = enforcer.update({}, _config())
    filtered = enforcer.filter_decision(_decision())

    assert snapshot["mode"] == "enforcing_blocked"
    assert snapshot["stop_reason"] == "phase_guard_snapshot_invalid"
    assert filtered.intent is ChargerIntent.DISABLE


def test_cycle_helper_evaluates_once_caches_runtime_snapshot_and_filters():
    coord = SimpleNamespace(
        config=_config(),
        hass=SimpleNamespace(states=object()),
    )
    raw = _guard(safe=False, fresh=False, reason="grid:l2:unavailable")

    with patch(
        "custom_components.solar_energy_management.coordinator.dual_phase_guard.evaluate_dual_phase_guard",
        return_value=raw,
    ) as evaluate:
        runtime = update_active_phase_guard(coord)

    assert evaluate.call_count == 1
    assert coord._phase_guard_snapshot is runtime
    assert runtime["mode"] == "enforcing_blocked"
    assert filter_charger_decision(coord, _decision()).intent is ChargerIntent.DISABLE


def test_cycle_helper_uses_live_observer_mode_over_stale_config_value():
    config = _config(observer_mode=False)
    coord = SimpleNamespace(
        config=config,
        _observer_mode=True,
        hass=SimpleNamespace(states=object()),
    )

    with patch(
        "custom_components.solar_energy_management.coordinator.dual_phase_guard.evaluate_dual_phase_guard",
        return_value=_guard(margin=4.0),
    ):
        runtime = update_active_phase_guard(coord)

    assert runtime["mode"] == "observer"
    assert runtime["read_only"] is True
    assert filter_charger_decision(coord, _decision()) == _decision()


def test_grid_only_evaluator_failure_keeps_complete_diagnostic_lane_schema():
    coord = SimpleNamespace(
        config=_config(phase_guard_topology="grid_only"),
        hass=SimpleNamespace(states=object()),
    )

    with patch(
        "custom_components.solar_energy_management.coordinator.dual_phase_guard.evaluate_dual_phase_guard",
        side_effect=RuntimeError("sensor registry unavailable"),
    ):
        runtime = update_active_phase_guard(coord)

    assert runtime["safe"] is False
    assert runtime["stop_reason"] == "phase_guard_evaluation_failed"
    assert runtime["grid"] == {}
    assert runtime["inverter"] == {}


def test_filter_helper_is_fail_closed_if_cycle_snapshot_was_not_evaluated():
    coord = SimpleNamespace(config=_config())

    filtered = filter_charger_decision(coord, _decision())

    assert filtered.intent is ChargerIntent.DISABLE
    assert "phase_guard_snapshot_invalid" in filtered.reason
    assert coord._phase_guard_snapshot["mode"] == "enforcing_blocked"
    assert coord._phase_guard_snapshot["stop_reason"] == "phase_guard_snapshot_invalid"


def test_coordinator_wires_one_cycle_evaluation_and_both_actuation_paths():
    source = (
        Path(__file__).parents[1] / "coordinator" / "coordinator.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "filter_charger_decision"
    ]
    assert len(calls) == 2
    for call in calls:
        assert [ast.unparse(arg) for arg in call.args] == ["self", "decision"]
        keywords = {item.arg: ast.unparse(item.value) for item in call.keywords}
        assert keywords == {"adapter": "adapter", "power": "view.power"}

    updates = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "update_active_phase_guard"
    ]
    assert len(updates) == 1
    assert ast.unparse(updates[0]) == "update_active_phase_guard(self)"

    actuations = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "actuate"
    ]
    assert len(actuations) == 2
    assert len(calls) == len(actuations) == 2
    assert max(call.lineno for call in updates) < min(call.lineno for call in calls)
    guard_lines = sorted(call.lineno for call in calls)
    actuation_lines = sorted(call.lineno for call in actuations)
    assert all(
        guard_line < actuation_line
        for guard_line, actuation_line in zip(guard_lines, actuation_lines, strict=False)
    )


def test_coordinator_only_updates_and_notifies_guard_when_enabled():
    source = (
        Path(__file__).parents[1] / "coordinator" / "coordinator.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    guarded_calls = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if "phase_guard_enabled" not in ast.unparse(node.test):
            continue
        for child in node.body:
            for call in ast.walk(child):
                if isinstance(call, ast.Call):
                    guarded_calls.add(ast.unparse(call.func))

    assert "update_active_phase_guard" in guarded_calls
    assert "self._notification_manager.notify_phase_guard_transition" in guarded_calls
