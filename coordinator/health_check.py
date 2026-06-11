"""SEM Health Check — periodic validation of calculation integrity."""
import logging
from .types import PowerReadings, PowerFlows, CostData

_LOGGER = logging.getLogger(__name__)


class HealthCheck:
    """Validates energy balance and calculation integrity each cycle."""

    # After this many consecutive violating cycles the per-cycle WARNING
    # drops to debug until the violations clear (#487 triage logs: 413
    # near-identical lines drowned the log + diagnose ring buffer).
    _WARN_CYCLES = 6

    def __init__(self) -> None:
        self._violation_count: int = 0
        self._last_violations: list[str] = []
        self._violation_streak: int = 0

    def check_power_balance(self, power: PowerReadings) -> list[str]:
        """Verify energy balance: solar + import + discharge ≈ home + ev + export + charge."""
        violations: list[str] = []

        supply = power.solar_power + power.grid_import_power + power.battery_discharge_power
        demand = (
            power.home_consumption_power
            # FLEET-READ: whole-house energy balance check — needs the
            # fleet EV total to validate supply ≈ demand.
            + power.ev_power
            + power.grid_export_power
            + power.battery_charge_power
        )
        imbalance = abs(supply - demand)

        if imbalance > 50:  # Allow 50 W tolerance for rounding
            violations.append(
                f"Energy balance: supply={supply:.0f}W, demand={demand:.0f}W, imbalance={imbalance:.0f}W"
            )

        # Non-negative checks
        non_negative_fields = [
            ("home_consumption", power.home_consumption_power),
            ("grid_import", power.grid_import_power),
            ("grid_export", power.grid_export_power),
            ("battery_charge", power.battery_charge_power),
            ("battery_discharge", power.battery_discharge_power),
            # FLEET-READ: health check iterates fleet-level fields; the
            # non-negative invariant applies to the whole-house EV total.
            ("ev_power", power.ev_power),
            ("solar_power", power.solar_power),
        ]
        for name, val in non_negative_fields:
            if val < -1:  # Allow -1 W for rounding
                violations.append(f"{name} is negative: {val:.1f}W")

        # Mutual exclusivity
        if power.grid_import_power > 10 and power.grid_export_power > 10:
            violations.append(
                f"Grid import ({power.grid_import_power:.0f}W) and export"
                f" ({power.grid_export_power:.0f}W) both active"
            )

        if power.battery_charge_power > 10 and power.battery_discharge_power > 10:
            violations.append(
                f"Battery charge ({power.battery_charge_power:.0f}W) and discharge"
                f" ({power.battery_discharge_power:.0f}W) both active"
            )

        return violations

    def check_flows(self, power: PowerReadings, flows: PowerFlows) -> list[str]:
        """Verify flow allocations don't exceed source power."""
        violations: list[str] = []

        solar_allocated = (
            flows.solar_to_home + flows.solar_to_battery + flows.solar_to_grid + flows.solar_to_ev
        )
        if solar_allocated > power.solar_power + 50:
            violations.append(
                f"Solar over-allocated: {solar_allocated:.0f}W > {power.solar_power:.0f}W production"
            )

        # All flows non-negative
        flow_fields = [
            "solar_to_home", "solar_to_battery", "solar_to_grid", "solar_to_ev",
            "grid_to_home", "grid_to_battery", "grid_to_ev",
            "battery_to_home", "battery_to_ev",
        ]
        for name in flow_fields:
            val = getattr(flows, name, 0)
            if val < -1:
                violations.append(f"Flow {name} is negative: {val:.1f}W")

        return violations

    def check_metrics(self, autarky: float, self_consumption: float) -> list[str]:
        """Verify percentage metrics are in valid range [0, 100]."""
        violations: list[str] = []
        if autarky < 0 or autarky > 100:
            violations.append(f"Autarky out of range: {autarky:.1f}%")
        if self_consumption < 0 or self_consumption > 100:
            violations.append(f"Self-consumption out of range: {self_consumption:.1f}%")
        return violations

    def check_costs(self, costs: CostData) -> list[str]:
        """Verify cost values are non-negative."""
        violations: list[str] = []
        cost_fields = ["daily_costs", "daily_savings", "daily_battery_savings"]
        for name in cost_fields:
            val = getattr(costs, name, 0)
            if val < -0.01:
                violations.append(f"Cost {name} is negative: {val:.4f}")
        return violations

    def run_all_checks(
        self,
        power: PowerReadings,
        flows: PowerFlows | None = None,
        autarky: float = 0,
        self_consumption: float = 0,
        costs: CostData | None = None,
    ) -> list[str]:
        """Run all health checks and return violations list."""
        violations = self.check_power_balance(power)
        if flows is not None:
            violations += self.check_flows(power, flows)
        violations += self.check_metrics(autarky, self_consumption)
        if costs is not None:
            violations += self.check_costs(costs)

        if violations:
            self._violation_count += len(violations)
            self._last_violations = violations
            self._violation_streak += 1
            if self._violation_streak <= self._WARN_CYCLES:
                for v in violations:
                    _LOGGER.warning("Health check violation: %s", v)
                if self._violation_streak == self._WARN_CYCLES:
                    _LOGGER.warning(
                        "Health check violations persist — further "
                        "occurrences drop to debug until they clear "
                        "(diag: sem health sensors keep counting)",
                    )
            else:
                for v in violations:
                    _LOGGER.debug("Health check violation: %s", v)
        else:
            if self._violation_streak > self._WARN_CYCLES:
                _LOGGER.info("Health check violations cleared")
            self._violation_streak = 0
            self._last_violations = []

        return violations

    @property
    def total_violations(self) -> int:
        """Cumulative count of all violations seen since startup."""
        return self._violation_count

    @property
    def last_violations(self) -> list[str]:
        """Violations detected in the most recent cycle (empty if all OK)."""
        return self._last_violations
