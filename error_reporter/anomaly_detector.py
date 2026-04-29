"""Anomaly detection for SEM coordinator data.

Each ``AnomalyCheck`` examines the latest ``coordinator.data`` snapshot and
returns ``AnomalyResult(ok, signature, details)``. The detector applies
hysteresis (a check must fail K consecutive evaluations before firing)
before handing it off to ``ErrorReporter``.

Designed to run from inside the coordinator's update loop — every check
is a small pure function reading the data dict; no I/O.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnomalyResult:
    """Outcome of a single check evaluation."""

    ok: bool
    signature: str = ""
    title: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class AnomalyCheck:
    """A single anomaly check.

    ``evaluate`` takes the coordinator data snapshot and returns an
    :class:`AnomalyResult`. ``min_consecutive_failures`` controls hysteresis.
    ``cooldown_s`` ensures a fired anomaly isn't re-evaluated immediately
    after reset.
    """

    name: str
    evaluate: Callable[[Mapping[str, Any]], AnomalyResult]
    min_consecutive_failures: int = 3
    cooldown_s: int = 5 * 60

    # internal mutable state
    _consecutive_failures: int = 0
    _last_fired_at: float = 0.0

    def step(self, data: Mapping[str, Any]) -> Optional[AnomalyResult]:
        """Advance the check by one tick. Returns the result if it should
        fire (i.e. crossed the hysteresis threshold), else ``None``."""
        now = time.time()
        if now - self._last_fired_at < self.cooldown_s:
            return None

        try:
            result = self.evaluate(data)
        except Exception:
            _LOGGER.exception("Anomaly check %s raised", self.name)
            return None

        if result.ok:
            self._consecutive_failures = 0
            return None

        self._consecutive_failures += 1
        if self._consecutive_failures >= self.min_consecutive_failures:
            self._last_fired_at = now
            self._consecutive_failures = 0
            return result
        return None


class AnomalyDetector:
    """Runs a list of checks against the coordinator data on each tick."""

    def __init__(self, checks: list[AnomalyCheck]) -> None:
        self._checks = checks

    def step(self, data: Mapping[str, Any]) -> list[AnomalyResult]:
        """Returns the list of results that fired this tick."""
        fired: list[AnomalyResult] = []
        for check in self._checks:
            result = check.step(data)
            if result is not None and not result.ok:
                fired.append(result)
        return fired


# ============================================================
# Built-in checks for SEM
# ============================================================
# Each check reads from coordinator.data — see types.SEMData fields.

def _check_energy_balance(data: Mapping[str, Any]) -> AnomalyResult:
    """Solar = home + grid_export + battery_charge - grid_import - battery_discharge.

    A persistent imbalance > 15% of solar production means a sensor
    is mis-mapped or a sign convention is wrong.
    """
    balance = data.get("energy_balance_check")
    solar = data.get("solar_power") or 0
    if balance is None:
        return AnomalyResult(ok=True)
    # `energy_balance_check` is already a percentage in this codebase.
    if abs(balance) <= 15:
        return AnomalyResult(ok=True)
    if solar < 200:
        # Don't flag at night — noise dominates.
        return AnomalyResult(ok=True)
    return AnomalyResult(
        ok=False,
        signature=f"balance_drift:{int(abs(balance) // 5) * 5}",
        title=f"Energy balance off by ~{balance:.1f}%",
        details={
            "component": "coordinator",
            "balance_pct": balance,
            "solar_power_w": solar,
            "home_consumption_total_w": data.get("home_consumption_total"),
            "grid_power_w": data.get("grid_power"),
            "battery_power_w": data.get("battery_power"),
        },
    )


def _check_update_failure_streak(data: Mapping[str, Any]) -> AnomalyResult:
    """Coordinator has reported >= 5 consecutive update failures."""
    streak = data.get("_update_failure_streak", 0)
    if streak < 5:
        return AnomalyResult(ok=True)
    return AnomalyResult(
        ok=False,
        signature=f"update_fail_streak:{streak // 5 * 5}",
        title=f"{streak} consecutive coordinator update failures",
        details={
            "component": "coordinator",
            "streak": streak,
            "last_error": data.get("_last_update_error"),
        },
    )


def _check_implausible_values(data: Mapping[str, Any]) -> AnomalyResult:
    """Sanity-bound a few key sensors."""
    soc = data.get("battery_soc")
    if isinstance(soc, (int, float)) and not (0 <= soc <= 100):
        return AnomalyResult(
            ok=False,
            signature="implausible:battery_soc",
            title=f"battery_soc out of range: {soc}",
            details={"component": "sensor_reader", "battery_soc": soc},
        )
    solar = data.get("solar_power")
    if isinstance(solar, (int, float)) and solar < -100:
        return AnomalyResult(
            ok=False,
            signature="implausible:solar_negative",
            title=f"solar_power persistently negative: {solar}W",
            details={"component": "sensor_reader", "solar_power": solar},
        )
    return AnomalyResult(ok=True)


def _check_surplus_not_consumed(data: Mapping[str, Any]) -> AnomalyResult:
    """Large solar surplus while EV is idle and battery has capacity.

    Indicates the surplus controller / EV control isn't engaging.
    """
    surplus = data.get("available_power") or 0
    soc = data.get("battery_soc") or 0
    ev_connected = data.get("ev_connected")
    ev_charging = data.get("ev_charging")
    grid_power = data.get("grid_power") or 0  # negative = export

    if surplus < 1500:
        return AnomalyResult(ok=True)
    if soc >= 95:
        return AnomalyResult(ok=True)  # battery essentially full
    if not ev_connected:
        return AnomalyResult(ok=True)
    if ev_charging:
        return AnomalyResult(ok=True)
    if grid_power < -1000:
        # Already exporting heavily; this isn't "lost" surplus.
        return AnomalyResult(ok=True)
    return AnomalyResult(
        ok=False,
        signature="surplus_not_consumed",
        title="Solar surplus not being consumed by EV or battery",
        details={
            "component": "surplus_controller",
            "available_power_w": surplus,
            "battery_soc_pct": soc,
            "ev_connected": ev_connected,
            "ev_charging": ev_charging,
            "grid_power_w": grid_power,
        },
    )


def _check_charging_state_stuck(data: Mapping[str, Any]) -> AnomalyResult:
    """Charging state hasn't changed in > 6h while EV is connected."""
    state = data.get("charging_state")
    last_change = data.get("_charging_state_last_change")
    if not state or not last_change:
        return AnomalyResult(ok=True)
    if not data.get("ev_connected"):
        return AnomalyResult(ok=True)
    age_s = time.time() - last_change
    if age_s < 6 * 60 * 60:
        return AnomalyResult(ok=True)
    return AnomalyResult(
        ok=False,
        signature=f"state_stuck:{state}",
        title=f"Charging state '{state}' unchanged for {int(age_s/3600)}h",
        details={
            "component": "charging_control",
            "state": state,
            "age_hours": age_s / 3600,
        },
    )


def build_default_checks() -> list[AnomalyCheck]:
    """Default suite of checks. Used by the coordinator."""
    return [
        AnomalyCheck("energy_balance", _check_energy_balance,
                     min_consecutive_failures=10, cooldown_s=60 * 60),
        AnomalyCheck("update_failure_streak", _check_update_failure_streak,
                     min_consecutive_failures=1, cooldown_s=30 * 60),
        AnomalyCheck("implausible_values", _check_implausible_values,
                     min_consecutive_failures=3, cooldown_s=15 * 60),
        AnomalyCheck("surplus_not_consumed", _check_surplus_not_consumed,
                     min_consecutive_failures=30, cooldown_s=60 * 60),
        AnomalyCheck("charging_state_stuck", _check_charging_state_stuck,
                     min_consecutive_failures=1, cooldown_s=2 * 60 * 60),
    ]
