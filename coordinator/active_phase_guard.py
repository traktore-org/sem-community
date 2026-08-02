"""Fail-closed EV actuation gate for the dual per-phase current guard.

The measurement evaluator remains pure in :mod:`dual_phase_guard`.  This module
owns only the small amount of state needed to make its snapshot actionable:
trip immediately, then require several fresh cycles below a lower reset
threshold before EV control is authorised again.
"""
from __future__ import annotations

from dataclasses import replace
import logging
import math
from typing import Any, Dict

from .charger_types import ChargerDecision, ChargerIntent

_LOGGER = logging.getLogger(__name__)

DEFAULT_RECOVERY_MARGIN_A = 2.0
DEFAULT_RECOVERY_CYCLES = 3


def _runtime_config(coord: Any) -> Dict[str, Any]:
    """Copy config and overlay safety-relevant live coordinator state."""
    config = dict(getattr(coord, "config", {}) or {})
    if hasattr(coord, "_observer_mode"):
        config["observer_mode"] = bool(coord._observer_mode)
    return config


class ActivePhaseGuard:
    """Latch and apply the dual-lane guard to charger decisions.

    Enforcement is opt-in.  While blocked, every temporary-idle or charging
    decision is converted to ``DISABLE`` so the reconciler takes its immediate
    stop path instead of its normal idle debounce.  An existing explicit
    ``DISABLE`` decision passes through unchanged.
    """

    def __init__(self) -> None:
        self.control_authorized = False
        self._enforcing = False
        self._recovery_cycles = 0
        self._required_recovery_cycles = DEFAULT_RECOVERY_CYCLES
        self._block_reason = "phase_guard_not_evaluated"
        self._guard_snapshot: Dict[str, Any] = {}
        self._reserved_increase_a = 0.0

    def update(self, guard: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        """Consume one measurement snapshot and return runtime diagnostics."""
        self._guard_snapshot = dict(guard) if isinstance(guard, dict) else {}
        # One update is one coordinator cycle.  Allocations made while filtering
        # several chargers below share this per-cycle reservation.
        self._reserved_increase_a = 0.0
        was_enforcing = self._enforcing
        self._enforcing = bool(
            config.get("phase_guard_enabled", False)
            and config.get("phase_guard_enforcement_enabled", False)
            and not config.get("observer_mode", False)
        )
        if self._enforcing and not was_enforcing:
            # Enabling enforcement is itself a safety transition: never inherit
            # the observer path's pass-through authorization.
            self.control_authorized = False
            self._recovery_cycles = 0
        if not self._enforcing:
            self.control_authorized = True
            self._recovery_cycles = 0
            snapshot = dict(guard) if isinstance(guard, dict) else {}
            snapshot.update(
                mode="observer",
                read_only=True,
                control_authorized=True,
                recovery_cycles=0,
            )
            return snapshot

        try:
            recovery_margin = float(
                config.get(
                    "phase_guard_recovery_margin_a", DEFAULT_RECOVERY_MARGIN_A
                )
            )
            required_cycles = int(
                config.get("phase_guard_recovery_cycles", DEFAULT_RECOVERY_CYCLES)
            )
        except (TypeError, ValueError):
            recovery_margin = DEFAULT_RECOVERY_MARGIN_A
            required_cycles = DEFAULT_RECOVERY_CYCLES

        if (
            not math.isfinite(recovery_margin)
            or recovery_margin < 0
            or required_cycles < 1
        ):
            self.control_authorized = False
            self._recovery_cycles = 0
            self._block_reason = "invalid_enforcement_configuration"
            self._required_recovery_cycles = max(1, required_cycles)
            return self._runtime_snapshot(guard, "enforcing_blocked")

        self._required_recovery_cycles = required_cycles
        topology = str(guard.get("topology", "hybrid_load_port")) if isinstance(guard, dict) else ""
        valid_snapshot = (
            isinstance(guard, dict)
            and isinstance(guard.get("grid"), dict)
            and (
                topology == "grid_only"
                or isinstance(guard.get("inverter"), dict)
            )
            and "safe" in guard
            and "data_fresh" in guard
        )
        if not valid_snapshot:
            self.control_authorized = False
            self._recovery_cycles = 0
            self._block_reason = "phase_guard_snapshot_invalid"
            return self._runtime_snapshot(guard, "enforcing_blocked")

        if not bool(guard.get("safe")) or not bool(guard.get("data_fresh")):
            self.control_authorized = False
            self._recovery_cycles = 0
            self._block_reason = str(guard.get("stop_reason") or "phase_guard_unsafe")
            return self._runtime_snapshot(guard, "enforcing_blocked")

        if self.control_authorized:
            self._block_reason = ""
            return self._runtime_snapshot(guard, "enforcing_armed")

        if self._all_required_margins_at_least(guard, recovery_margin):
            self._recovery_cycles += 1
        else:
            self._recovery_cycles = 0

        if self._recovery_cycles >= required_cycles:
            self.control_authorized = True
            self._block_reason = ""
            return self._runtime_snapshot(guard, "enforcing_armed")

        self._block_reason = (
            f"recovery_hold:{self._recovery_cycles}/{required_cycles}"
            if self._recovery_cycles
            else f"recovery_margin_below:{recovery_margin:g}A"
        )
        return self._runtime_snapshot(guard, "enforcing_recovery")

    def filter_decision(
        self, decision: ChargerDecision, *, adapter: Any = None, power: Any = None
    ) -> ChargerDecision:
        """Apply the latch and clamp charging increases to verified headroom."""
        if not self._enforcing:
            return decision
        if decision.intent is ChargerIntent.DISABLE:
            return decision
        if not self.control_authorized:
            return self._disable_decision(decision, self._block_reason)
        if decision.intent is ChargerIntent.IDLE:
            return decision
        if decision.intent not in (
            ChargerIntent.CHARGE_AT_AMPS,
            ChargerIntent.CHARGE_MAX,
        ):
            return self._disable_decision(decision, "unsupported_charge_intent")

        context = self._actuation_context(adapter, power)
        min_margin = self._minimum_required_margin()
        if context is None or min_margin is None:
            return self._disable_decision(decision, "context_missing")

        phases, voltage, minimum_a, maximum_a, current_a = context
        required_phases = self._required_phase_keys(self._guard_snapshot)
        # A one-phase charger on a three-phase monitored supply is valid.  It is
        # conservatively clamped by the smallest measured phase/lane margin.
        # The unsafe inverse (three-phase charger with only L1 monitored) stops.
        if required_phases is None or phases > len(required_phases):
            return self._disable_decision(decision, "phase_count_mismatch")
        if decision.intent is ChargerIntent.CHARGE_MAX:
            desired_a = maximum_a
        else:
            try:
                desired_a = float(decision.commanded_amps)
            except (TypeError, ValueError):
                return self._disable_decision(decision, "context_invalid")
            if not math.isfinite(desired_a) or desired_a < 0:
                return self._disable_decision(decision, "context_invalid")
            desired_a = min(desired_a, maximum_a)

        available_increase_a = max(0.0, min_margin - self._reserved_increase_a)
        max_safe_a = math.floor(current_a + available_increase_a + 1e-9)
        target_a = int(min(desired_a, max_safe_a))

        if target_a < minimum_a:
            return self._disable_decision(decision, "headroom_below_minimum")

        granted_increase_a = max(0.0, target_a - current_a)
        self._reserved_increase_a += granted_increase_a

        # Preserve the original immutable decision when no clamp is needed.
        if desired_a <= max_safe_a:
            return decision
        return replace(
            decision,
            intent=ChargerIntent.CHARGE_AT_AMPS,
            commanded_amps=target_a,
            budget_w=float(target_a * phases * voltage),
            bridgeable=False,
            reason=(
                f"{decision.reason}; phase guard clamped to {target_a}A "
                f"(headroom {available_increase_a:.2f}A)"
            ),
        )

    @staticmethod
    def _disable_decision(decision: ChargerDecision, reason: str) -> ChargerDecision:
        return replace(
            decision,
            intent=ChargerIntent.DISABLE,
            commanded_amps=0,
            budget_w=0.0,
            bridgeable=False,
            reason=f"phase guard: {reason} — immediate EV stop",
        )

    @staticmethod
    def _actuation_context(adapter: Any, power: Any):
        try:
            phases = int(adapter.phases)
            voltage = float(adapter.voltage)
            minimum_a = int(adapter.min_current_a)
            maximum_a = int(adapter.max_current_a)
            power_w = float(power.power_w)
        except (AttributeError, TypeError, ValueError):
            return None
        if (
            phases not in (1, 3)
            or not math.isfinite(voltage)
            or voltage <= 0
            or minimum_a < 0
            or maximum_a < minimum_a
            or not math.isfinite(power_w)
            or power_w < 0
        ):
            return None
        current_a = power_w / (phases * voltage)
        if not math.isfinite(current_a):
            return None
        return phases, voltage, minimum_a, maximum_a, current_a

    def _minimum_required_margin(self):
        guard = self._guard_snapshot
        topology = str(guard.get("topology", "hybrid_load_port"))
        lane_names = ("grid",) if topology == "grid_only" else ("grid", "inverter")
        required_phases = self._required_phase_keys(guard)
        if required_phases is None:
            return None
        margins = []
        for lane_name in lane_names:
            lane = guard.get(lane_name)
            if not isinstance(lane, dict) or set(lane) != set(required_phases):
                return None
            for phase in required_phases:
                value = lane[phase].get("margin_a") if isinstance(lane[phase], dict) else None
                if value is None:
                    return None
                try:
                    margin = float(value)
                except (TypeError, ValueError):
                    return None
                if not math.isfinite(margin) or margin < 0:
                    return None
                margins.append(margin)
        return min(margins) if margins else None

    def _runtime_snapshot(self, guard: Any, mode: str) -> Dict[str, Any]:
        snapshot = dict(guard) if isinstance(guard, dict) else {}
        snapshot.update(
            mode=mode,
            read_only=False,
            control_authorized=self.control_authorized,
            recovery_cycles=self._recovery_cycles,
        )
        if not self.control_authorized:
            snapshot["stop_reason"] = self._block_reason
            snapshot["safe"] = bool(snapshot.get("safe", False))
            snapshot["data_fresh"] = bool(snapshot.get("data_fresh", False))
        return snapshot

    @staticmethod
    def _all_required_margins_at_least(
        guard: Dict[str, Any], recovery_margin: float
    ) -> bool:
        topology = str(guard.get("topology", "hybrid_load_port"))
        lane_names = ("grid",) if topology == "grid_only" else ("grid", "inverter")
        required_phases = ActivePhaseGuard._required_phase_keys(guard)
        if required_phases is None:
            return False
        for lane_name in lane_names:
            lane = guard.get(lane_name)
            if not isinstance(lane, dict) or set(lane) != set(required_phases):
                return False
            for phase in required_phases:
                margin = lane[phase].get("margin_a") if isinstance(lane[phase], dict) else None
                if margin is None:
                    return False
                try:
                    value = float(margin)
                    if not math.isfinite(value) or value < recovery_margin:
                        return False
                except (TypeError, ValueError):
                    return False
        return True

    @staticmethod
    def _required_phase_keys(guard: Dict[str, Any]):
        """Return monitored phase keys; legacy snapshots default to three phases."""
        raw_phase_count = guard.get("phase_count", 3)
        try:
            numeric_phase_count = float(raw_phase_count)
            if (
                isinstance(raw_phase_count, bool)
                or not math.isfinite(numeric_phase_count)
                or not numeric_phase_count.is_integer()
            ):
                return None
            phase_count = int(numeric_phase_count)
        except (TypeError, ValueError):
            return None
        if phase_count not in {1, 3}:
            return None
        return tuple(f"l{phase}" for phase in range(1, phase_count + 1))


def update_active_phase_guard(coord: Any) -> Dict[str, Any]:
    """Evaluate and latch the guard exactly once for the current coordinator cycle."""
    from .dual_phase_guard import evaluate_dual_phase_guard

    enforcer = getattr(coord, "_active_phase_guard", None)
    if not isinstance(enforcer, ActivePhaseGuard):
        enforcer = ActivePhaseGuard()
        coord._active_phase_guard = enforcer
    config = _runtime_config(coord)
    try:
        raw = evaluate_dual_phase_guard(coord.hass.states, config)
    except Exception:  # noqa: BLE001 — safety boundary must fail closed
        _LOGGER.exception("Phase-guard measurement evaluation failed")
        topology = str(config.get("phase_guard_topology", "hybrid_load_port"))
        raw = {
            "mode": "observer",
            "topology": topology,
            "read_only": True,
            "safe": False,
            "data_fresh": False,
            "stop_reason": "phase_guard_evaluation_failed",
            "grid": {},
        }
        if topology != "grid_only":
            raw["inverter"] = {}
    runtime = enforcer.update(raw, config)
    coord._phase_guard_snapshot = runtime
    return runtime


def filter_charger_decision(
    coord: Any, decision: ChargerDecision, *, adapter: Any = None, power: Any = None
) -> ChargerDecision:
    """Apply the cached guard state; fail closed if enforcement skipped evaluation."""
    enforcer = getattr(coord, "_active_phase_guard", None)
    if not isinstance(enforcer, ActivePhaseGuard):
        enforcer = ActivePhaseGuard()
        coord._active_phase_guard = enforcer
        runtime = enforcer.update({}, _runtime_config(coord))
        coord._phase_guard_snapshot = runtime
    return enforcer.filter_decision(decision, adapter=adapter, power=power)
