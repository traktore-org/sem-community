"""#773 — the residual audited: home minus everything SEM can see.

The arc's capstone. After #768/#769/#772 every controlled load has a
kWh, so ``home`` stops being a black box::

    true_baseload = home − Σ(controlled device kWh)

That remainder is the house SEM does NOT touch — fridge, standby,
lighting, router — and its defining property is that it is BORING: it
moves with season and occupancy, slowly, and never jumps. So its drift
is a free sensor-health check, the #628 lens pointed one level inward.
The day identity asks "do the metered rows agree with each other"; this
asks "does the leftover behave like a house".

Boundary discipline (the #703/#704 lesson, applied before it bites):
device ledger rows roll at SUNRISE, the home row at MIDNIGHT. A daily
subtraction across that mismatch would mis-book every small-hours kWh,
so the controlled-loads subtrahend is a MIDNIGHT-KEYED MIRROR booked at
the filing seam — the same shape as ``MIDNIGHT_EV_CATEGORY``, for the
same reason.

Honesty rules (#628 / #755, pinned here):
- silence is not zero: no home row → no baseload number at all;
- an estimated per-device kWh (source "rated") keeps the number
  DISPLAYABLE but disqualifies it as a measurement — ``measured`` is
  False and the drift check refuses the day rather than compare
  across it;
- a breach names the suspected term (the largest day-over-day mover
  among the devices and the home row), not just "imbalance";
- a NEGATIVE baseload is an over-subtraction and is reported through
  the #771 partition checker (controlled loads are members of the
  home fleet row), never clamped quiet.
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.health_check import (
    HealthCheck,
)
from custom_components.solar_energy_management.coordinator.types import (
    EnergyTotals,
)

TODAY = date(2026, 8, 14)


def _calc() -> EnergyCalculator:
    return EnergyCalculator({}, MagicMock())


def _hc() -> HealthCheck:
    return HealthCheck()


def _seal(day, baseload, *, measured=True, home=None, devices=None,
          estimated_kwh=None):
    """One sealed day of history, in the shape the calculator writes.

    ``estimated_kwh=None`` omits the key — the pre-fix (legacy) row shape,
    which the restore-compat tests below rely on.
    """
    row = {
        "date": str(day),
        "baseload_kwh": baseload,
        "home_kwh": home if home is not None else baseload + 2.0,
        "controlled_kwh": (home if home is not None else baseload + 2.0)
        - baseload,
        "measured": measured,
        "devices": devices or {},
    }
    if estimated_kwh is not None:
        row["estimated_kwh"] = estimated_kwh
    return row


def _history(*days):
    return list(days)


# ───────────────────────────────────────────────────────────────────────
# 1. the number — computed from the ledger, refusing silence
# ───────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestTheBaseloadIsASubtraction773:
    def test_home_minus_controlled_loads(self) -> None:
        calc = _calc()
        calc._daily_accumulators[f"home_{TODAY}"] = 12.0
        calc.accumulate_controlled_load(3.0, TODAY, estimated=False)
        calc.accumulate_controlled_load(1.5, TODAY, estimated=False)
        b = calc.get_true_baseload(TODAY)
        assert b["today_kwh"] == pytest.approx(7.5)
        assert b["controlled_today_kwh"] == pytest.approx(4.5)
        assert b["measured"] is True

    def test_no_home_row_means_no_number(self) -> None:
        """Silence is not zero: before the balance has written a home row
        there is nothing to subtract from, and publishing 0 − controlled
        would report the house as a negative-consumption fault."""
        calc = _calc()
        calc.accumulate_controlled_load(3.0, TODAY, estimated=False)
        assert calc.get_true_baseload(TODAY)["today_kwh"] is None

    def test_an_estimated_subtrahend_displays_but_is_not_measured(self) -> None:
        """The issue's explicit call: rated×runtime disqualifies the
        number for training, not for display. The value is still there;
        ``measured`` says what it is."""
        calc = _calc()
        calc._daily_accumulators[f"home_{TODAY}"] = 12.0
        calc.accumulate_controlled_load(3.0, TODAY, estimated=False)
        calc.accumulate_controlled_load(2.0, TODAY, estimated=True)
        b = calc.get_true_baseload(TODAY)
        assert b["today_kwh"] == pytest.approx(7.0)
        assert b["estimated_today_kwh"] == pytest.approx(2.0)
        assert b["measured"] is False

    def test_a_negative_result_is_published_not_clamped(self) -> None:
        """Over-subtraction is unambiguous — a sign error or a
        double-count — and clamping it to zero would hide exactly the
        fault this sensor exists to expose."""
        calc = _calc()
        calc._daily_accumulators[f"home_{TODAY}"] = 2.0
        calc.accumulate_controlled_load(5.0, TODAY, estimated=False)
        assert calc.get_true_baseload(TODAY)["today_kwh"] == pytest.approx(-3.0)

    def test_the_mirror_is_midnight_keyed_and_survives_a_restart(self) -> None:
        calc = _calc()
        calc.accumulate_controlled_load(3.0, TODAY, estimated=False)
        fresh = _calc()
        fresh.restore_state(calc.get_state())
        fresh._daily_accumulators[f"home_{TODAY}"] = 10.0
        assert fresh.get_true_baseload(TODAY)["today_kwh"] == pytest.approx(7.0)


# ───────────────────────────────────────────────────────────────────────
# 2. the seal — one history row per finished day
# ───────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestTheDaySealsIntoHistory773:
    def test_rollover_seals_yesterday(self) -> None:
        calc = _calc()
        yesterday = TODAY - timedelta(days=1)
        calc._daily_accumulators[f"home_{yesterday}"] = 10.0
        calc.accumulate_controlled_load(4.0, yesterday, estimated=False)
        calc._check_rollover(TODAY, calc._month_key(TODAY), str(TODAY.year))
        assert len(calc.baseload_history) == 1
        sealed = calc.baseload_history[-1]
        assert sealed["date"] == str(yesterday)
        assert sealed["baseload_kwh"] == pytest.approx(6.0)
        assert sealed["measured"] is True

    def test_a_day_without_a_home_row_is_a_gap_not_a_zero(self) -> None:
        """#628 discipline: the day is refused, not recorded as 0 —
        a zero here would poison every later median."""
        calc = _calc()
        yesterday = TODAY - timedelta(days=1)
        calc.accumulate_controlled_load(4.0, yesterday, estimated=False)
        calc._check_rollover(TODAY, calc._month_key(TODAY), str(TODAY.year))
        assert len(calc.baseload_history) == 0

    def test_an_estimated_day_seals_as_unmeasured(self) -> None:
        calc = _calc()
        yesterday = TODAY - timedelta(days=1)
        calc._daily_accumulators[f"home_{yesterday}"] = 10.0
        calc.accumulate_controlled_load(4.0, yesterday, estimated=True)
        calc._check_rollover(TODAY, calc._month_key(TODAY), str(TODAY.year))
        assert calc.baseload_history[-1]["measured"] is False

    def test_the_history_survives_a_restart(self) -> None:
        calc = _calc()
        yesterday = TODAY - timedelta(days=1)
        calc._daily_accumulators[f"home_{yesterday}"] = 10.0
        calc.accumulate_controlled_load(4.0, yesterday, estimated=False)
        calc._check_rollover(TODAY, calc._month_key(TODAY), str(TODAY.year))
        fresh = _calc()
        fresh.restore_state(calc.get_state())
        assert len(fresh.baseload_history) == 1
        assert fresh.baseload_history[-1]["baseload_kwh"] == pytest.approx(6.0)

    def test_no_double_seal_for_the_same_day(self) -> None:
        calc = _calc()
        yesterday = TODAY - timedelta(days=1)
        calc._daily_accumulators[f"home_{yesterday}"] = 10.0
        calc.accumulate_controlled_load(4.0, yesterday, estimated=False)
        calc._check_rollover(TODAY, calc._month_key(TODAY), str(TODAY.year))
        calc._daily_accumulators[f"home_{yesterday}"] = 10.0
        calc._check_rollover(TODAY, calc._month_key(TODAY), str(TODAY.year))
        assert len(calc.baseload_history) == 1


# ───────────────────────────────────────────────────────────────────────
# 3. the drift check — a step is a finding, and it names its suspect
# ───────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestBaseloadDriftNamesItsSuspect773:
    def _steady(self, n=4, kwh=6.0, devices=None):
        return [
            _seal(TODAY - timedelta(days=n - i), kwh,
                  devices=devices or {"pool": 2.0})
            for i in range(n)
        ]

    def test_a_boring_baseload_is_silent(self) -> None:
        hc = _hc()
        history = self._steady() + [_seal(TODAY, 6.4, devices={"pool": 2.0})]
        assert hc.check_baseload_drift(history) == []

    def test_a_step_change_is_a_violation(self) -> None:
        hc = _hc()
        history = self._steady() + [
            _seal(TODAY, 14.0, home=16.0, devices={"pool": 2.0})]
        violations = hc.check_baseload_drift(history)
        assert len(violations) == 1

    def test_the_violation_names_the_moving_term(self) -> None:
        """The step came in through the HOME row (a metered row died or
        double-counted upstream) while every device held steady — the
        message must say so, because 'imbalance' alone sends the user
        hunting through every sensor they own."""
        hc = _hc()
        history = self._steady() + [
            _seal(TODAY, 14.0, home=16.0, devices={"pool": 2.0})]
        msg = hc.check_baseload_drift(history)[0]
        assert "home" in msg
        assert "pool" not in msg

    def test_a_device_step_names_the_device(self) -> None:
        """Inverse: home steady, one device's ledger row collapsed (its
        meter died → its real draw slid into the baseload). The suspect
        is the device, by id.

        The dead device is a 4 kWh/day load on purpose: the band is
        deliberately wide (occupancy swings must not fire), so a small
        device dying is BELOW it and stays uncaught — the check trades
        sensitivity for never being muted (#660). A load big enough to
        matter clears the band."""
        hc = _hc()
        history = [
            _seal(TODAY - timedelta(days=4 - i), 6.0, home=10.0,
                  devices={"pool": 4.0})
            for i in range(4)
        ] + [_seal(TODAY, 10.0, home=10.0, devices={"pool": 0.0})]
        msg = hc.check_baseload_drift(history)[0]
        assert "pool" in msg

    def test_an_unmeasured_day_is_refused_not_compared(self) -> None:
        """#628 discipline: the gap day neither fires nor feeds the
        reference. An estimate compared against measurements would fire
        on healthy hardware — the #660 mute path."""
        hc = _hc()
        history = self._steady() + [
            _seal(TODAY, 14.0, home=16.0, measured=False,
                  devices={"pool": 2.0})]
        assert hc.check_baseload_drift(history) == []

    def test_too_little_history_is_silent(self) -> None:
        hc = _hc()
        history = [_seal(TODAY - timedelta(days=1), 6.0),
                   _seal(TODAY, 14.0, home=16.0)]
        assert hc.check_baseload_drift(history) == []

    def test_occupancy_swing_does_not_fire(self) -> None:
        """A weekend at home is not a dead sensor. The tolerance must
        pass a ~40% swing on a small baseload."""
        hc = _hc()
        history = self._steady(kwh=5.0) + [
            _seal(TODAY, 6.8, home=8.8, devices={"pool": 2.0})]
        assert hc.check_baseload_drift(history) == []


# ───────────────────────────────────────────────────────────────────────
# 3b. a bounded estimate does not silence the check
# ───────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestABoundedEstimateStillCounts773:
    """The .175 soak's very first sealed day was ``measured: false`` — one
    meterless pool pump (0.21 kWh estimated, rated×runtime) made the whole
    day ineligible, and a house with ANY meterless device would starve the
    drift check of reference days forever. Dormant-by-default is the #660
    death by other means.

    The honest rule is not "no estimate anywhere" but "no estimate big
    enough to move the verdict": the estimate's error is bounded by the
    estimated kWh itself, so a day whose estimated portion is well inside
    the 2 kWh band cannot flip a comparison. The seal records the size;
    eligibility reads the size; ``measured`` stays strict — it is the
    published purity flag, not the eligibility gate."""

    def _steady(self, n=4, kwh=6.0, est=0.3):
        return [
            _seal(TODAY - timedelta(days=n - i), kwh, measured=False,
                  estimated_kwh=est, devices={"pool": 2.0})
            for i in range(n)
        ]

    def test_a_small_estimate_does_not_silence_the_check(self) -> None:
        hc = _hc()
        history = self._steady() + [
            _seal(TODAY, 14.0, home=16.0, measured=False,
                  estimated_kwh=0.3, devices={"pool": 2.0})]
        assert len(hc.check_baseload_drift(history)) == 1

    def test_a_boring_bounded_day_stays_silent(self) -> None:
        hc = _hc()
        history = self._steady() + [
            _seal(TODAY, 6.4, measured=False, estimated_kwh=0.3,
                  devices={"pool": 2.0})]
        assert hc.check_baseload_drift(history) == []

    def test_a_large_estimate_is_still_a_gap(self) -> None:
        """An estimate a quarter the size of the band CAN move the verdict
        — that day neither fires nor feeds the reference."""
        hc = _hc()
        history = self._steady() + [
            _seal(TODAY, 14.0, home=16.0, measured=False,
                  estimated_kwh=5.0, devices={"pool": 2.0})]
        assert hc.check_baseload_drift(history) == []

    def test_a_legacy_unmeasured_day_stays_a_gap(self) -> None:
        """Rows sealed before this fix carry no ``estimated_kwh``. An
        unmeasured legacy row has an estimate of UNKNOWN size — treating
        it as bounded would compare against an unbounded error, so it
        stays a gap and ages out of the 14-day window."""
        hc = _hc()
        history = self._steady() + [
            _seal(TODAY, 14.0, home=16.0, measured=False,
                  devices={"pool": 2.0})]
        assert hc.check_baseload_drift(history) == []

    def test_a_legacy_measured_day_is_still_eligible(self) -> None:
        """The inverse compat rule: legacy ``measured: true`` means a
        recorded estimate of exactly zero."""
        hc = _hc()
        history = [
            _seal(TODAY - timedelta(days=4 - i), 6.0, devices={"pool": 2.0})
            for i in range(4)
        ] + [_seal(TODAY, 14.0, home=16.0, devices={"pool": 2.0})]
        assert len(hc.check_baseload_drift(history)) == 1

    def test_the_seal_records_the_estimate_size(self) -> None:
        calc = _calc()
        yesterday = TODAY - timedelta(days=1)
        calc._daily_accumulators[f"home_{yesterday}"] = 10.0
        calc.accumulate_controlled_load(4.0, yesterday, estimated=False)
        calc.accumulate_controlled_load(0.25, yesterday, estimated=True)
        calc._check_rollover(TODAY, calc._month_key(TODAY), str(TODAY.year))
        sealed = calc.baseload_history[-1]
        assert sealed["estimated_kwh"] == pytest.approx(0.25)
        assert sealed["measured"] is False


# ───────────────────────────────────────────────────────────────────────
# 4. the negative residual reports through the partition checker
# ───────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestControlledLoadsArePartitionMembers773:
    def test_devices_exceeding_home_is_an_over_count(self) -> None:
        """Σ(controlled loads) > home is the energy-domain shape of a
        negative baseload — one physical draw counted twice, or a sign
        error. Same checker, same over-count-only discipline, and the
        message names the members."""
        hc = _hc()
        energy = EnergyTotals(daily_home=5.0)
        violations = hc.check_ledger_partitions(
            energy,
            per_device_daily={"pool": 4.0, "heat_pump": 3.5},
        )
        assert len(violations) == 1
        assert "pool" in violations[0] and "heat_pump" in violations[0]

    def test_a_faithful_split_is_silent(self) -> None:
        hc = _hc()
        energy = EnergyTotals(daily_home=12.0)
        assert hc.check_ledger_partitions(
            energy,
            per_device_daily={"pool": 4.0, "heat_pump": 3.5},
        ) == []

    def test_shortfall_is_never_a_violation(self) -> None:
        """Most of home IS baseload — the devices summing far below the
        home row is the healthy state, not a fault."""
        hc = _hc()
        energy = EnergyTotals(daily_home=20.0)
        assert hc.check_ledger_partitions(
            energy, per_device_daily={"pool": 0.5},
        ) == []


# ───────────────────────────────────────────────────────────────────────
# 5. wired into the cycle
# ───────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestWiredIntoTheCycle773:
    def test_the_filing_seam_feeds_the_midnight_mirror(self) -> None:
        """Every filed increment lands in the mirror too, flagged by its
        provenance — the same one write that feeds the device ledger."""
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )

        surplus = MagicMock()
        surplus._devices = {
            "pool": SimpleNamespace(
                device_id="pool", last_cycle_energy_kwh=0.2,
                energy_split_label=None, daily_energy_is_measured=True,
            ),
            "vent": SimpleNamespace(
                device_id="vent", last_cycle_energy_kwh=0.1,
                energy_split_label=None, daily_energy_is_measured=False,
            ),
        }
        coord = SimpleNamespace(
            _energy_calculator=MagicMock(),
            _surplus_controller=surplus,
        )
        coord._comfort_split_for = (
            SEMCoordinator._comfort_split_for.__get__(coord))
        SEMCoordinator._file_device_energy(coord, TODAY)

        calls = coord._energy_calculator.accumulate_controlled_load\
            .call_args_list
        assert len(calls) == 2
        booked = {
            (c.args[0], c.kwargs.get("estimated")) for c in calls
        }
        assert (0.2, False) in booked
        assert (0.1, True) in booked

    def test_run_all_checks_carries_the_new_terms(self) -> None:
        """The call site must pass the per-device dict and the baseload
        history, or both checks are dead code — the #660 failure mode
        (a checker nothing feeds) rebuilt one issue later."""
        import ast
        import pathlib

        src = pathlib.Path(
            "custom_components/solar_energy_management/coordinator/"
            "coordinator.py"
        )
        if not src.exists():
            src = pathlib.Path(__file__).parent.parent / "coordinator" / \
                "coordinator.py"
        tree = ast.parse(src.read_text())
        kwargs_seen: set = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "run_all_checks"):
                kwargs_seen |= {k.arg for k in node.keywords}
        assert "per_device_daily" in kwargs_seen
        assert "baseload_history" in kwargs_seen

    def test_published_keys_exist(self) -> None:
        """The pair the issue asks for, in the published dict: the live
        W residual and the day's kWh beside its honesty flag."""
        e = EnergyTotals()
        fields = set(EnergyTotals.__dataclass_fields__)
        for f in (
            "true_baseload_power",
            "true_baseload_today",
            "controlled_loads_today",
            "true_baseload_measured",
        ):
            assert f in fields, f"EnergyTotals.{f} missing"
