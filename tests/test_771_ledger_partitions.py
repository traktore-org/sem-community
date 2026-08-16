"""#771 — the per-device breakdowns must reconcile against the fleet row.

Three subsidiary ledgers are computed and published; none was ever compared
against the total it decomposes. The fleet identity (#628) checks the fleet
rows, so a two-charger install can balance perfectly while the split between
the two chargers is nonsense — and unlike #761's doubled home reading, a
misattribution moves no total, so nobody will ever spot it by eye.

WHICH DIRECTION IS CHECKED, AND WHY ONLY ONE
--------------------------------------------
Over-count only, exactly like the per-string POWER check that survived the
#660 sweep in ``check_flows`` — and for the same reasons, which apply just as
hard to the energy figures:

* **Under-count is legitimate and common.** ``discover_pv_strings_from_registry``
  caps discovery at 4 slots, so a 6-string install sums to less than the
  inverter total, forever. Each charger's daily bucket rolls over at ITS OWN
  ``Charge by`` deadline (#280) while the fleet EV day falls back to midnight
  the moment two chargers disagree (#723), so after one charger's rollover the
  members legitimately sum below the fleet for hours. And
  ``_reconcile_solar_energy`` corrects ``daily_solar`` UPWARD from the hardware
  counter (#556), moving the fleet row off the integration the strings share.
  A shortfall check would fire every day on correct hardware, and a check that
  cries wolf is a check that gets muted — the #660 failure one level up.

* **Over-count has no benign reading.** It means one physical thing is
  enumerated twice. Which is not hypothetical: the emit loops in
  ``integrate_energy_flows`` publish *every member ever seen today*, and the
  per-charger daily rollover in the coordinator only visits chargers still in
  the config. Rename a charger or a string entity mid-day and the old bucket
  keeps its kWh, keeps being published, and is added to a sum that now
  double-counts the same energy. That is #761's shape precisely.

So the violation names the residual AND the members, marking any member that
is no longer live — because that member is the suspect, and naming it is the
difference between "something is wrong" and "delete this stale id".

WHAT IS *NOT* HERE, AND WHY
---------------------------
Issue #771's table lists a ``per_battery`` charge/discharge row. There is no
such ledger to check: ``EnergyTotals.per_battery`` / ``per_inverter``, the
three ``*_view`` properties over them, and the ``daily_kwh`` /
``daily_charge_kwh`` / ``daily_discharge_kwh`` fields on the runtime and
snapshot dataclasses have no production writer anywhere — only this repo's
tests ever put a number in them. Building a reconciler over a dict nothing
populates would be a checker that cannot fail: coverage-shaped, detection-free,
the exact instrument #660 dismantled. The honest fix is deletion, pinned below.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.health_check import (
    HealthCheck,
)
from custom_components.solar_energy_management.coordinator.types import (
    ChargerEnergyFlows,
    EnergyFlows,
    EnergyTotals,
    PowerReadings,
    StringEnergy,
)


def _flows(**kw) -> EnergyFlows:
    return EnergyFlows(**kw)


def _joined(violations: list[str]) -> str:
    return " | ".join(violations)


@pytest.mark.unit
class TestPerChargerDailyEnergyReconciles771:
    """``Σ _daily_ev_per_charger`` vs ``energy.daily_ev``.

    The sharpest of the three: the members are integrated in
    ``coordinator._update_ev_tracking`` from each charger's own power reading,
    the fleet row in ``EnergyCalculator.calculate_energy`` from
    ``power.ev_power``. Two producers, two inputs, one physical quantity.
    """

    def test_a_stale_charger_bucket_is_caught_and_named(self):
        """The live defect: a charger id disappears from the config, its daily
        bucket is never reset again (the rollover only visits configured
        chargers) and it keeps inflating every per-charger sum."""
        v = HealthCheck().check_ledger_partitions(
            EnergyTotals(daily_ev=10.0),
            per_charger_daily={"keba": 10.0, "keba_old": 12.0},
            live_charger_ids=["keba"],
        )
        assert v, "a 12 kWh phantom charger passed unnoticed"
        msg = _joined(v)
        assert "keba_old" in msg, f"the suspect member is not named: {msg}"
        assert "12" in msg, f"the member's contribution is not stated: {msg}"

    def test_a_faithful_split_is_silent(self):
        assert HealthCheck().check_ledger_partitions(
            EnergyTotals(daily_ev=10.0),
            per_charger_daily={"a": 6.0, "b": 4.0},
            live_charger_ids=["a", "b"],
        ) == []

    def test_a_shortfall_is_not_a_violation(self):
        """Charger A rolled over at its 07:00 deadline; the fleet EV day did
        not (two chargers disagree → midnight fallback, #723). The members
        legitimately sum below the fleet until the next boundary."""
        assert HealthCheck().check_ledger_partitions(
            EnergyTotals(daily_ev=10.0),
            per_charger_daily={"a": 0.0, "b": 4.0},
            live_charger_ids=["a", "b"],
        ) == []

    def test_rounding_does_not_fire(self):
        assert HealthCheck().check_ledger_partitions(
            EnergyTotals(daily_ev=10.0),
            per_charger_daily={"a": 6.02, "b": 4.02},
            live_charger_ids=["a", "b"],
        ) == []

    def test_an_empty_day_cannot_fire(self):
        """Before dawn every row is 0.0. A relative band around 0 is
        meaningless, so the absolute floor has to hold the check shut."""
        assert HealthCheck().check_ledger_partitions(
            EnergyTotals(daily_ev=0.0),
            per_charger_daily={"a": 0.0},
            live_charger_ids=["a"],
        ) == []

    def test_no_breakdown_means_nothing_to_check(self):
        """Single-charger installs never populate the dict. Absence of a
        breakdown is not a disagreement."""
        assert HealthCheck().check_ledger_partitions(
            EnergyTotals(daily_ev=10.0), per_charger_daily={},
        ) == []


@pytest.mark.unit
class TestPerChargerFlowSplitReconciles771:
    """``Σ EnergyFlows.per_charger`` vs the fleet ``*_to_ev`` rows.

    The other representation of the same physical energy — this one carries
    the solar/grid/battery ORIGIN per charger, which is what the per-charger
    cost and savings figures are built on. Same emit-everything-ever-seen
    semantics, so the same stale-member exposure.
    """

    def test_a_double_counted_charger_is_caught(self):
        v = HealthCheck().check_ledger_partitions(
            EnergyTotals(),
            energy_flows=_flows(
                solar_to_ev=6.0, grid_to_ev=4.0,
                per_charger={
                    "garage": ChargerEnergyFlows(solar_to_ev=6.0, grid_to_ev=4.0),
                    "carport": ChargerEnergyFlows(solar_to_ev=6.0, grid_to_ev=4.0),
                },
            ),
            live_charger_ids=["carport"],
        )
        assert v, "the same 10 kWh counted under two ids passed unnoticed"
        msg = _joined(v)
        assert "garage" in msg and "carport" in msg, msg

    def test_a_faithful_split_is_silent(self):
        assert HealthCheck().check_ledger_partitions(
            EnergyTotals(),
            energy_flows=_flows(
                solar_to_ev=6.0, grid_to_ev=4.0, battery_to_ev=2.0,
                per_charger={
                    "a": ChargerEnergyFlows(
                        solar_to_ev=4.0, grid_to_ev=1.0, battery_to_ev=2.0,
                    ),
                    "b": ChargerEnergyFlows(solar_to_ev=2.0, grid_to_ev=3.0),
                },
            ),
            live_charger_ids=["a", "b"],
        ) == []

    def test_a_charger_missing_from_the_split_is_not_a_violation(self):
        """A charger that has not reported a per-charger draw yet contributes
        to the fleet row and not to the split. Under-count, not over-count."""
        assert HealthCheck().check_ledger_partitions(
            EnergyTotals(),
            energy_flows=_flows(
                solar_to_ev=6.0, grid_to_ev=4.0,
                per_charger={"a": ChargerEnergyFlows(solar_to_ev=3.0)},
            ),
            live_charger_ids=["a", "b"],
        ) == []


@pytest.mark.unit
class TestPerStringEnergyReconciles771:
    """``Σ EnergyFlows.per_string`` vs ``energy.daily_solar``."""

    def test_a_double_counted_string_is_caught_and_named(self):
        v = HealthCheck().check_ledger_partitions(
            EnergyTotals(daily_solar=10.0),
            energy_flows=_flows(per_string={
                "pv1": StringEnergy(energy_kwh=6.0),
                "pv2": StringEnergy(energy_kwh=4.0),
                "pv2_old": StringEnergy(energy_kwh=4.0),
            }),
        )
        assert v, "a string counted twice passed unnoticed"
        assert "pv2_old" in _joined(v)

    def test_inverter_efficiency_headroom_does_not_fire(self):
        """``_read_pv_string`` synthesises V×I on Huawei — the members are DC
        while ``daily_solar`` integrates the AC total, so a healthy system runs
        a few percent over every sunny day. Same band as the power check."""
        assert HealthCheck().check_ledger_partitions(
            EnergyTotals(daily_solar=10.0),
            energy_flows=_flows(per_string={
                "pv1": StringEnergy(energy_kwh=5.15),
                "pv2": StringEnergy(energy_kwh=5.15),
            }),
        ) == []

    def test_the_four_slot_discovery_cap_does_not_fire(self):
        """Six strings, four discovered — the members sum to two thirds of the
        day forever, on correct hardware."""
        assert HealthCheck().check_ledger_partitions(
            EnergyTotals(daily_solar=30.0),
            energy_flows=_flows(per_string={
                f"pv{i}": StringEnergy(energy_kwh=5.0) for i in range(1, 5)
            }),
        ) == []


@pytest.mark.unit
class TestWiredIntoTheCycle771:
    """A checker nothing calls is a checker that does not exist."""

    def test_run_all_checks_reports_partition_violations(self):
        hc = HealthCheck()
        v = hc.run_all_checks(
            PowerReadings(),
            energy=EnergyTotals(daily_ev=10.0),
            per_charger_daily={"a": 10.0, "ghost": 12.0},
            live_charger_ids=["a"],
        )
        assert any("ghost" in x for x in v), v
        assert hc.total_violations >= 1

    def test_the_coordinator_passes_the_partitions(self):
        """The call site must hand over the three breakdowns; without them the
        new checker runs on ``None`` every cycle and reports a clean bill."""
        import ast
        import inspect
        from custom_components.solar_energy_management.coordinator import (
            coordinator as coord_mod,
        )

        tree = ast.parse(inspect.getsource(coord_mod))
        calls = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "run_all_checks"
        ]
        assert calls, "run_all_checks is not called anywhere"
        passed = {k.arg for c in calls for k in c.keywords}
        for kw in ("energy", "energy_flows", "per_charger_daily",
                   "live_charger_ids"):
            assert kw in passed, (
                f"run_all_checks is called without {kw!r} — the partition "
                "check would see nothing and pass vacuously every cycle"
            )


@pytest.mark.unit
class TestTheDeadPerDeviceEnergySurfaceIsGone771:
    """#771's table names a ``per_battery`` ledger. It never existed.

    ``EnergyTotals.per_inverter`` / ``per_battery`` and their three ``*_view``
    properties had no production writer and no production reader — every
    number that was ever in them was put there by a test. Same for the daily
    kWh fields on the runtime/snapshot dataclasses, and for ``InverterRuntime``
    as a whole (never instantiated outside tests).

    Deleted rather than reconciled: a checker over a dict nothing fills cannot
    fail, and would have published "per-battery ledger verified" forever. This
    test is the ratchet — re-adding the surface means wiring a writer AND a
    reconciler at the same time, not a field that looks like data.
    """

    def test_energy_totals_has_no_unpopulated_per_device_dicts(self):
        fields = {f for f in EnergyTotals.__dataclass_fields__}
        assert "per_inverter" not in fields
        assert "per_battery" not in fields
        for prop in (
            "daily_solar_view",
            "daily_battery_charge_view",
            "daily_battery_discharge_view",
        ):
            assert not hasattr(EnergyTotals, prop), (
                f"{prop} is back — it sums a dict with no writer, so it "
                "silently returns the legacy fallback on every install"
            )

    def test_the_runtime_dataclasses_carry_no_phantom_daily_kwh(self):
        from custom_components.solar_energy_management.coordinator import (
            charger_types,
        )

        assert not hasattr(charger_types, "InverterRuntime"), (
            "InverterRuntime is back — nothing instantiates it, so every "
            "field on it is dead by construction"
        )
        for name, dead in (
            ("BatteryRuntime", ("daily_charge_kwh", "daily_discharge_kwh")),
            ("InverterPower", ("daily_kwh",)),
            ("BatteryPower", ("daily_charge_kwh", "daily_discharge_kwh")),
        ):
            cls = getattr(charger_types, name)
            for f in dead:
                assert f not in cls.__dataclass_fields__, (
                    f"{name}.{f} is back with no writer — it publishes 0.0 "
                    "as a measurement, which is #755 contract 1"
                )

    def test_the_phantom_per_device_flow_slices_are_gone(self):
        """``InverterFlows`` / ``BatteryFlows`` are the same phantom one
        level over — declared as the per-inverter and per-battery mirrors
        of ``ChargerFlows``, but with no container field to live on
        (``PowerFlows`` has ``per_charger`` and nothing else) and no
        producer in ``flow_calculator``.

        They were worse than merely dead: the comment above them asserted
        that ``sum(flows.per_inverter[i].solar_to_X) == flows.solar_to_X``
        "holds by construction" — a conservation invariant claimed about
        an attribution algorithm that never constructs them. That is the
        #771 complaint in its purest form: a per-device row that reads as
        reconciled against the fleet identity while nothing computes it.

        ``ChargerFlows`` stays: ``flow_calculator`` really does fill
        ``PowerFlows.per_charger`` and integrate it into
        ``EnergyFlows.per_charger``, which is why the origin-split check
        above has something to reconcile.
        """
        from custom_components.solar_energy_management.coordinator import (
            charger_types,
        )
        from custom_components.solar_energy_management.coordinator.types import (
            PowerFlows,
        )

        for name in ("InverterFlows", "BatteryFlows"):
            assert not hasattr(charger_types, name), (
                f"{name} is back — nothing constructs it and no container "
                "holds it, so its conservation invariant is a claim about "
                "code that does not exist"
            )
        assert "per_charger" in PowerFlows.__dataclass_fields__
        for phantom in ("per_inverter", "per_battery"):
            assert phantom not in PowerFlows.__dataclass_fields__
