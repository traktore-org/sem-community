"""#660 — no vacuous health check.

``diag_health_violations: 0`` used to mean "nothing was actually examined".
``HealthCheck`` verified values against constraints their own producer had
already enforced three lines earlier:

* ``check_metrics`` verified ``[0, 100]`` on autarky / self-consumption, whose
  only assignment sites are ``max(0, min(100, …))``.
* ``check_costs`` verified ``≥ 0`` on two fields that are ``max(0, …)``.
* five of seven ``non_negative_fields`` are ``max(0, ±scalar)`` in
  ``calculate_derived``.
* ``check_flows`` asserted "source not over-allocated" and "no negative flow"
  about a greedy ``min(avail, need)`` allocator's own output, in the same
  cycle. Both are theorems of that loop.

Ledger class **8 — tautological / can't-fire check**. The HA-PROD 2026-06-01
autarky bug (pinned 0 % while self-consumption read 98 %) is an *in-range
wrong number*: the instrument blessed it.

The guard below is the standing rule, not just a regression test: **every
check must be shown to fire on a deliberately violating input.** A check that
cannot be made to fail joins the inert set silently otherwise — any future
``max(0)``-derived sensor added to ``non_negative_fields`` would.

Crucially the inputs here are built through the REAL derivation
(``calculate_derived`` / ``EnergyCalculator``), not hand-assembled — a
hand-built dataclass can violate invariants production cannot reach, which is
exactly how the retired exclusivity check's unit test passed while the check
was unfireable (#661).
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from custom_components.solar_energy_management.coordinator.health_check import (
    HealthCheck,
)
from custom_components.solar_energy_management.coordinator.types import (
    CostData,
    PowerFlows,
    PowerReadings,
)

_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _balanced_readings() -> PowerReadings:
    """A house whose sensors agree: 5 kW solar, 2 kW export, 3 kW home."""
    p = PowerReadings()
    p.solar_power = 5000.0
    p.grid_power = 2000.0  # + = export
    p.battery_power = 0.0
    p.calculate_derived()
    return p


@pytest.mark.unit
class TestCleanSystemIsQuiet660:
    """The floor: a coherent system must produce zero violations, or the
    checks below are just noise generators."""

    def test_balanced_house_has_no_violations(self):
        hc = HealthCheck()
        assert hc.run_all_checks(_balanced_readings()) == []

    def test_inverter_standby_draw_is_not_a_violation(self):
        """−10 W overnight standby is hardware behaviour, not a fault.

        The old ``< -1`` threshold made every night a violation streak.
        """
        p = PowerReadings()
        p.solar_power = -10.0
        p.grid_power = -10.0
        p.calculate_derived()
        assert HealthCheck().check_power_balance(p) == []


@pytest.mark.unit
class TestEveryCheckCanFire660:
    """One deliberately violating input per surviving check."""

    def test_home_residual_clamp_fires(self):
        """A stale/inverted sensor drives the residual negative.

        Reached through ``calculate_derived``: export + EV exceed everything
        coming in, so the house would have to consume −4 kW.
        """
        p = PowerReadings()
        p.solar_power = 1000.0
        p.grid_power = 3000.0  # exporting 3 kW while producing 1 kW
        p.ev_power = 2000.0
        p.calculate_derived()

        assert p.home_consumption_power == 0
        assert p.home_residual_clamped_w == pytest.approx(4000.0)

        violations = HealthCheck().check_power_balance(p)
        assert any("residual clamped" in v for v in violations), violations

    def test_one_fault_is_reported_once(self):
        """The balance gap and the clamp record are the SAME disagreement.

        Reporting both doubles ``diag_health_violations`` and logs the
        inconsistency twice per cycle for one root cause.
        """
        p = PowerReadings()
        p.solar_power = 1000.0
        p.grid_power = 3000.0
        p.ev_power = 2000.0
        p.calculate_derived()

        violations = HealthCheck().check_power_balance(p)
        assert len(violations) == 1, violations
        assert not any("Energy balance:" in v for v in violations), violations

    def test_a_held_home_value_still_fires_the_balance_check(self):
        """The balance check is the fallback, not dead weight.

        ``_smooth_home_consumption`` replaces ``home_consumption_power``
        AFTER ``calculate_derived`` ran. A held value that no longer matches
        live inputs has a clamp record of 0 — only the balance check sees it.
        """
        p = _balanced_readings()  # home == 3000, clamp record == 0
        p.home_consumption_power = 300.0  # stale hold from 5 minutes ago
        assert p.home_residual_clamped_w == 0

        violations = HealthCheck().check_power_balance(p)
        assert any("Energy balance:" in v for v in violations), violations

    def test_home_residual_clamp_is_silent_under_the_hold(self):
        """The hold is a KNOWN, already-handled inconsistency (#461)."""
        p = PowerReadings()
        p.solar_power = 1000.0
        p.grid_power = 3000.0
        p.ev_power = 2000.0
        p.calculate_derived()
        assert HealthCheck().check_power_balance(p, home_hold_active=True) == []

    def test_negative_raw_solar_fires(self):
        p = _balanced_readings()
        p.solar_power = -800.0  # inverted sign, not standby
        assert any(
            "solar_power is negative" in v
            for v in HealthCheck().check_power_balance(p)
        )

    def test_negative_raw_ev_fires(self):
        p = _balanced_readings()
        p.ev_power = -900.0
        assert any(
            "ev_power is negative" in v
            for v in HealthCheck().check_power_balance(p)
        )

    def test_per_string_over_count_fires(self):
        """Two strings summing above the inverter total = double-count."""
        p = _balanced_readings()  # solar_power = 5000
        flows = PowerFlows()
        flows.solar_per_string = {"pv1": 5000.0, "pv2": 5000.0}
        violations = HealthCheck().check_flows(p, flows)
        assert any("double-counted" in v for v in violations), violations

    def test_per_string_within_conversion_loss_is_quiet(self):
        """DC string sum above AC total is normal physics, not a fault.

        ``sensor_reader._read_pv_string`` synthesises per-string power as
        V×I when the inverter exposes no per-string power entity — that is
        the DC side, and the Huawei shape on HA-PROD. At 96 % inverter
        efficiency the sum sits ~4 % above the AC total on a HEALTHY system,
        so a tight band would flag correct hardware every sunny afternoon.
        """
        p = _balanced_readings()  # solar_power = 5000 (AC)
        flows = PowerFlows()
        flows.solar_per_string = {"pv1": 2600.0, "pv2": 2600.0}  # +4 % DC
        assert HealthCheck().check_flows(p, flows) == []

    def test_capped_string_discovery_does_not_fire(self):
        """5+ inverters → discovery caps at 4 slots → sum is legitimately
        LOW. Checking the under-count direction would fire forever."""
        p = _balanced_readings()
        flows = PowerFlows()
        flows.solar_per_string = {f"pv{i}": 500.0 for i in range(1, 5)}
        assert HealthCheck().check_flows(p, flows) == []

    def test_negative_daily_cost_fires(self):
        costs = CostData()
        costs.daily_costs = -1.5
        assert HealthCheck().check_costs(costs)

    def test_sustained_clamp_fires(self):
        hc = HealthCheck()
        for _ in range(HealthCheck._CLAMP_CYCLES - 1):
            assert hc.check_clamps({"autarky_rate": 12.4}) == []
        violations = hc.check_clamps({"autarky_rate": 12.4})
        assert any("autarky_rate" in v for v in violations), violations

    def test_a_transient_clamp_does_not_fire(self):
        """One-off clamping is the guard doing its job, not a bug."""
        hc = HealthCheck()
        for _ in range(HealthCheck._CLAMP_CYCLES * 2):
            assert hc.check_clamps({"autarky_rate": 5.0}) == []
            assert hc.check_clamps({}) == []

    def test_clearing_the_bug_clears_the_streak(self):
        hc = HealthCheck()
        for _ in range(HealthCheck._CLAMP_CYCLES):
            hc.check_clamps({"autarky_rate": 12.4})
        hc.check_clamps({})
        assert hc.check_clamps({"autarky_rate": 12.4}) == []


@pytest.mark.unit
class TestTheClampsAreActuallyRecorded660:
    """The instrument only works if the producers feed it."""

    def test_the_autarky_clamp_is_recorded(self):
        from custom_components.solar_energy_management.coordinator.energy_calculator import (  # noqa: E501
            EnergyCalculator,
        )

        calc = EnergyCalculator({}, time_manager=None)
        assert calc._record_clamp("autarky_rate", -30.0, 0.0, eps=0.1) == 0.0
        assert calc.clamp_engagement["autarky_rate"] == pytest.approx(30.0)

    def test_a_quiet_clamp_clears_its_own_key_only(self):
        from custom_components.solar_energy_management.coordinator.energy_calculator import (  # noqa: E501
            EnergyCalculator,
        )

        calc = EnergyCalculator({}, time_manager=None)
        calc._record_clamp("autarky_rate", -30.0, 0.0, eps=0.1)
        calc._record_clamp("self_consumption_rate", 140.0, 100.0, eps=0.1)
        # autarky recovers; the other record must survive.
        calc._record_clamp("autarky_rate", 42.0, 42.0, eps=0.1)
        assert "autarky_rate" not in calc.clamp_engagement
        assert "self_consumption_rate" in calc.clamp_engagement

    def test_a_skipped_branch_does_not_leave_a_stale_record(self):
        """Both rate clamps sit inside ``if`` branches. On a day with no
        solar yet, the branch is skipped — a record left over from an
        earlier cycle would keep incrementing its streak into a violation
        nothing is currently producing."""
        from custom_components.solar_energy_management.coordinator.energy_calculator import (  # noqa: E501
            EnergyCalculator,
        )
        from custom_components.solar_energy_management.coordinator.types import (
            EnergyTotals,
        )

        calc = EnergyCalculator({}, time_manager=None)
        calc.clamp_engagement["autarky_rate"] = 30.0
        calc.clamp_engagement["self_consumption_rate"] = 12.0

        # daily_solar == 0 and no consumption → neither branch runs.
        calc.calculate_performance(PowerReadings(), EnergyTotals())

        assert "autarky_rate" not in calc.clamp_engagement
        assert "self_consumption_rate" not in calc.clamp_engagement

    def test_the_savings_floors_stay_uninstrumented(self):
        """Not every clamp is worth an instrument.

        Under a negative import price (Nord Pool / ENTSO-E intraday) a raw
        daily saving is legitimately negative, so the ``max(0, …)`` floor on
        savings engages on CORRECT behaviour. Wiring it into the engagement
        record would raise a violation every negative-price hour — the exact
        noise #660 exists to remove.
        """
        source = (_ROOT / "coordinator" / "energy_calculator.py").read_text()
        recorded = {
            line.split('"')[1]
            for line in source.splitlines()
            if "_record_clamp(" in line and '"' in line
        }
        assert "daily_savings" not in recorded
        assert "daily_battery_savings" not in recorded

    def test_the_constructor_still_finishes(self):
        """Guard for the shape of the #660 edit itself: ``_record_clamp``
        was first written INSIDE ``__init__``, whose remaining body then
        became unreachable after its ``return``."""
        from custom_components.solar_energy_management.coordinator.energy_calculator import (  # noqa: E501
            EnergyCalculator,
        )

        calc = EnergyCalculator({}, time_manager=None)
        # The last attribute assigned in ``__init__``.
        assert calc._install_year_decimal is None
        assert calc._accumulated_savings == 0.0


@pytest.mark.unit
class TestTheInertSetCannotGrowSilently660:
    """Static guard: nothing that ``calculate_derived`` clamps may be listed
    in ``non_negative_fields``. Such an entry is unfireable by construction
    and reads as coverage."""

    def _clamped_attrs(self) -> set[str]:
        """Attributes assigned ``max(0, …)`` inside ``calculate_derived``."""
        tree = ast.parse((_ROOT / "coordinator" / "types.py").read_text())
        clamped: set[str] = set()
        for fn in ast.walk(tree):
            if not (
                isinstance(fn, ast.FunctionDef)
                and fn.name == "calculate_derived"
            ):
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Assign):
                    continue
                call = node.value
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "max"
                ):
                    continue
                for t in node.targets:
                    if isinstance(t, ast.Attribute):
                        clamped.add(t.attr)
        return clamped

    def test_clamped_fields_are_not_in_the_non_negative_list(self):
        clamped = self._clamped_attrs()
        assert clamped, "AST scan found no clamps — the walk broke, not types.py"

        source = (_ROOT / "coordinator" / "health_check.py").read_text()
        block = source.split("non_negative_fields = [", 1)[1].split("]", 1)[0]

        listed = {
            attr
            for attr in clamped
            # ``home_residual_clamped_w`` is the RECORD of a clamp, not a
            # clamped value — it belongs nowhere near this list either way.
            if attr != "home_residual_clamped_w" and f"power.{attr}" in block
        }
        assert not listed, (
            "these fields are max(0, …) in calculate_derived, so a "
            f"non-negative check on them can never fire (#660): {sorted(listed)}"
        )
