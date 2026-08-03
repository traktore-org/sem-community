"""SEM Health Check — periodic validation of calculation integrity.

#660 — what this can and cannot see.

Most of what used to live here was **clamp-then-check**: verify ``0 ≤ x ≤ 100``
on a value whose only producer clamps it to ``[0, 100]`` three lines after
computing it, or ``≥ 0`` on a ``max(0, …)`` field. Those checks are
algebraically unfireable, so ``diag_health_violations: 0`` read as
"calculations verified" when it meant "nothing was actually examined". The
HA-PROD 2026-06-01 autarky bug (pinned at 0 % while self-consumption read
98 %) is an *in-range wrong number*: the instrument blessed it, and the whole
sign-bug family stayed invisible to it for a year.

The replacement instrument is **clamp engagement** — how much each guard
actually had to remove. The clamped output is definitionally clean; the
removal is the evidence. One engaged cycle is a rounding or transient
artefact, so a violation is only raised after the same clamp has engaged for
``_CLAMP_CYCLES`` consecutive cycles. See ``EnergyCalculator._record_clamp``
and ``PowerReadings.home_residual_clamped_w``.

The same rule applies to the flow checks: a greedy allocator that drains
``min(avail, need)`` cannot over-allocate a source or emit a negative flow, so
asserting those two things about its own output in the same cycle proves
nothing. What is NOT by construction is a cross-producer invariant — e.g. the
per-string sensors versus the inverter total — and that's what remains here.
"""
import logging
from .types import PowerReadings, PowerFlows, CostData

_LOGGER = logging.getLogger(__name__)


class HealthCheck:
    """Validates energy balance and calculation integrity each cycle."""

    # After this many consecutive violating cycles the per-cycle WARNING
    # drops to debug until the violations clear (#487 triage logs: 413
    # near-identical lines drowned the log + diagnose ring buffer).
    _WARN_CYCLES = 6

    # (#660) A clamp must engage for this many CONSECUTIVE cycles before it
    # counts as a violation. At the 10 s coordinator cycle that's ~5 minutes
    # — long enough that a stale sensor or a rounding wobble has cleared,
    # short enough that a wrong formula is reported the same session.
    _CLAMP_CYCLES = 30

    def __init__(self) -> None:
        self._violation_count: int = 0
        self._last_violations: list[str] = []
        self._violation_streak: int = 0
        # (#660) clamp name → consecutive cycles it has been engaged.
        self._clamp_streaks: dict[str, int] = {}

    def check_power_balance(
        self, power: PowerReadings, home_hold_active: bool = False,
    ) -> list[str]:
        """Verify energy balance: solar + import + discharge ≈ home + ev + export + charge.

        ``home_consumption_power`` is derived as the residual of the
        other readings (``calculate_derived``), so the balance is an
        identity unless the residual went negative — inputs sampled
        at different instants (stale solar/EV/grid sensor) — and got
        clamped to 0 and/or replaced by the coordinator's home-hold
        (``_smooth_home_consumption``). While that hold is active the
        gap is a KNOWN, already-handled input inconsistency: report
        it at debug only, not as a violation. RienduPre's #461 dump
        showed 69 "violations" that were all the hold bridging a
        Growatt solar sensor frozen for ~5 min. Once the hold window
        is exhausted the gap is a genuinely stuck sensor and warns.
        """
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

        # (#660) The residual the home-consumption clamp had to remove.
        #
        # These two are ONE fault reported two ways, so they are mutually
        # exclusive. When the residual went negative, ``home_consumption_power``
        # is 0 and the balance gap above is exactly the amount the clamp
        # removed — reporting both doubles ``diag_health_violations`` and logs
        # the same disagreement twice per cycle. The clamp record is the
        # sharper of the two (it names the direction: the inputs demand a
        # NEGATIVE house load), so it wins when it is engaged.
        #
        # The balance check is NOT redundant in general, which is why it
        # survives as the fallback: ``_smooth_home_consumption`` can replace
        # ``home_consumption_power`` AFTER ``calculate_derived`` has run, and
        # once the hold window is exhausted a held value that no longer
        # matches live inputs shows up here with the clamp record at 0.
        clamped = float(getattr(power, "home_residual_clamped_w", 0.0) or 0.0)
        if clamped > 50:
            if home_hold_active:
                _LOGGER.debug(
                    "Home-consumption residual clamped by %.0fW while the "
                    "hold is bridging — known input inconsistency",
                    clamped,
                )
            else:
                violations.append(
                    f"Home consumption residual clamped by {clamped:.0f}W "
                    f"(inputs produce a NEGATIVE house load — a power sensor "
                    f"is stale or its sign is inverted)"
                )
        elif imbalance > 50:  # Allow 50 W tolerance for rounding
            if home_hold_active:
                _LOGGER.debug(
                    "Energy balance gap %.0fW (supply=%.0fW, demand=%.0fW) "
                    "bridged by the home-consumption hold — input sensors "
                    "momentarily inconsistent, not counted as a violation",
                    imbalance, supply, demand,
                )
            else:
                violations.append(
                    f"Energy balance: supply={supply:.0f}W, demand={demand:.0f}W, "
                    f"imbalance={imbalance:.0f}W (inputs inconsistent — a power "
                    f"sensor is likely stale)"
                )

        # Non-negative checks — RAW reads only.
        #
        # (#660) ``home_consumption``, ``grid_import``, ``grid_export``,
        # ``battery_charge`` and ``battery_discharge`` used to be in this
        # list. All five are ``max(0, ±scalar)`` in
        # ``PowerReadings.calculate_derived``, so they cannot be negative on
        # any production path and the check was inert padding — five sixths
        # of a loop that looked like coverage. What replaces them for the
        # derived home value is the clamp record above; the grid/battery
        # pairs have their own real instrument at the netting site
        # (``SplitSensorExclusivityAudit``, #661).
        #
        # These two survive because they are read straight off a sensor and
        # a negative value is genuinely possible (and genuinely wrong).
        non_negative_fields = [
            # FLEET-READ: health check iterates fleet-level fields; the
            # non-negative invariant applies to the whole-house EV total.
            ("ev_power", power.ev_power),
            ("solar_power", power.solar_power),
        ]
        for name, val in non_negative_fields:
            # (#660) −1 W was mistuned: an inverter idling overnight reports
            # a small negative (its own standby draw through the DC side),
            # and a KEBA on standby does the same. That's normal hardware
            # behaviour, not a calculation fault, and it produced violations
            # every night. −50 W still catches an inverted sign, which is
            # the failure this is here for.
            if val < -50:
                violations.append(f"{name} is negative: {val:.1f}W")

        # Mutual exclusivity is NOT checked here — it cannot be (#661).
        #
        # ``grid_import_power`` / ``grid_export_power`` (and the battery pair)
        # are not inputs: ``PowerReadings.calculate_derived`` re-derives all
        # four from ONE signed scalar with ``max(0, ±x)``. "Both active" is
        # therefore unrepresentable by construction on every production path,
        # and the check that used to live here could not fail — it read as
        # coverage while detecting nothing. Its unit test passed only because
        # it hand-built a ``PowerReadings``, bypassing the derivation.
        #
        # The real check runs where the evidence still exists: at each split
        # netting site in ``SensorReader``, via ``SplitSensorExclusivityAudit``
        # (``_audit_split_pair``), surfaced as the ``split_pair_exclusivity``
        # cross-check in the perception trace.

        return violations

    def check_flows(self, power: PowerReadings, flows: PowerFlows) -> list[str]:
        """Cross-producer flow invariants — the ones that aren't theorems.

        (#660) Two checks used to live here: "solar is not over-allocated" and
        "no flow is negative". ``calculate_power_flows`` is a greedy allocator
        that drains ``sources_left`` via ``delivered = min(avail, need)`` and
        skips any pair where either side is ``<= 0``. Both properties are
        therefore theorems of that loop, and they were being asserted about
        its own output, in the same cycle, with nothing in between. They could
        not fail, so they told a user with a real flow problem "health check
        clean" — the worst possible first lead.

        What survives is the invariant that spans two INDEPENDENT producers,
        so it can actually be false.
        """
        violations: list[str] = []

        # Per-PV-string sensors vs the inverter total. The strings are read
        # from their own entities; ``solar_power`` comes from the inverter's
        # AC total (or the Energy-Dashboard list). ``types.PowerReadings``
        # documents the invariant as ``sum(per_string) ≈ solar_power``.
        #
        # Only the OVER-count direction is checked, and deliberately so:
        # ``discover_pv_strings_from_registry`` caps discovery at 4 slots, so
        # an install with 5+ strings/inverters legitimately sums to LESS than
        # the total and an under-count check would fire forever on correct
        # hardware. An over-count has no benign reading — it means a string
        # entity is being double-counted, or the total is only one inverter
        # of several.
        if flows.solar_per_string:
            per_string = sum(
                float(v or 0.0) for v in flows.solar_per_string.values()
            )
            # 10 % or 100 W, whichever is larger. That looks slack until you
            # note WHICH side is being compared: the per-string values are
            # frequently DC (``sensor_reader._read_pv_string`` synthesises
            # V×I when the inverter exposes no per-string power entity, which
            # is the Huawei case on HA-PROD), while ``solar_power`` is the AC
            # total. Inverter efficiency alone puts the DC sum 2–5 % above the
            # AC total on a healthy system, and the two sides are sampled at
            # different instants on a moving cloud edge. A 2 % band false-fires
            # on correct hardware every sunny afternoon.
            #
            # The fault this exists to catch is not subtle: a string entity
            # counted twice (+100 %) or a total that covers one inverter of
            # several (+100 % and up). 10 % separates those from physics with
            # room to spare.
            tolerance = max(100.0, 0.10 * float(power.solar_power))
            if per_string > float(power.solar_power) + tolerance:
                violations.append(
                    f"PV strings sum to {per_string:.0f}W but the inverter "
                    f"total reads {power.solar_power:.0f}W — a string is "
                    f"double-counted, or the total covers fewer inverters "
                    f"than the strings do"
                )

        return violations

    def check_clamps(self, clamp_engagement: dict[str, float]) -> list[str]:
        """(#660) Report clamps that have been engaged for too long.

        ``EnergyCalculator`` records how much each ``max(0, …)`` /
        ``min(100, …)`` guard removed this cycle. A guard that engages once
        is doing its job against a transient; a guard that engages every
        cycle for ``_CLAMP_CYCLES`` is holding a wrong formula inside the
        valid range, which is precisely the failure the old range checks
        could not see.

        Streaks are per clamp name and reset the moment that clamp goes
        quiet, so a cleared bug clears the violation.
        """
        violations: list[str] = []
        engaged = clamp_engagement or {}

        for name in list(self._clamp_streaks):
            if name not in engaged:
                del self._clamp_streaks[name]

        for name, amount in engaged.items():
            streak = self._clamp_streaks.get(name, 0) + 1
            self._clamp_streaks[name] = streak
            if streak >= self._CLAMP_CYCLES:
                violations.append(
                    f"{name} has been clamped for {streak} consecutive "
                    f"cycles (last correction {amount}) — the value stays in "
                    f"range only because the clamp is holding it there; the "
                    f"formula behind it is wrong"
                )
        return violations

    def check_costs(self, costs: CostData) -> list[str]:
        """Verify cost values that can actually be negative.

        (#660) ``daily_savings`` and ``daily_battery_savings`` were also
        checked here, but both are ``max(0, …)`` at their only assignment
        site — the check could not fire. They are not instrumented as clamp
        engagement either; see ``EnergyCalculator.calculate_costs`` for why
        (a negative raw saving is legitimate under a negative import price).
        ``daily_costs`` is a raw accumulator with no floor, so it is the one
        that stays.
        """
        violations: list[str] = []
        val = getattr(costs, "daily_costs", 0)
        if val < -0.01:
            violations.append(f"Cost daily_costs is negative: {val:.4f}")
        return violations

    def run_all_checks(
        self,
        power: PowerReadings,
        flows: PowerFlows | None = None,
        costs: CostData | None = None,
        clamp_engagement: dict[str, float] | None = None,
        home_hold_active: bool = False,
    ) -> list[str]:
        """Run all health checks and return violations list.

        (#660) The ``autarky`` / ``self_consumption`` parameters are gone.
        They fed a range check on values their producer had already clamped
        into that range; ``clamp_engagement`` carries the same two metrics
        with the information still attached.
        """
        violations = self.check_power_balance(power, home_hold_active)
        if flows is not None:
            violations += self.check_flows(power, flows)
        violations += self.check_clamps(clamp_engagement or {})
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
