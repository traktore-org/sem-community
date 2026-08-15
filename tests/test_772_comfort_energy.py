"""#772 — comfort energy gets a representation, split by plan placement.

Comfort is the one demand family where the plan CREATES runs (#638 C5:
a WILLING band actuates inside its planned block), and until this issue
it left no energy trace at all. The accrual itself rides #768 — a
climate zone is a ControllableDevice and books measured kWh like any
load — so what this file pins is the one thing the generic case cannot
say: **whether the kWh landed inside the zone's planned comfort block
or outside it.**

Why that split is the signal: the value of a pre-cool block is the
energy it DISPLACES, not the energy it uses. A block that banks four
hours of coasting and a block that runs the AC at 03:00 *and again at
17:00* book the same in-block kWh — the difference is entirely in the
out-of-block bucket. The in/out ratio over time is the first honest
answer to "is banking working here", and the first comfort signal the
learning layer (#755) could train on. #705 Ph3 decides WHEN to bank
and today gets no feedback on whether banking paid.

Design decisions pinned here:

- The bucket is derived AT THE FILING SEAM (``_file_device_energy``),
  from the ``comfort:{did}`` gate the actuation layer itself consults —
  not from a stamp cached on the device that could go stale when the
  plan clears or the kill-switch flips mid-day.
- A device that names its own bucket (the heat pump's SG-Ready state,
  #769) keeps it. The comfort split fills the label only for devices
  that would otherwise file unsplit.
- "No plan" is OUT-of-block, not unlabeled. A night the planner never
  banked is banking-not-working, and it must land in the denominator of
  the ratio — hiding it would make an idle planner look like a perfect
  one.
- A DISENGAGED band (no band configured, dead thermometer, misconfig)
  files no comfort claim at all. A zone that cannot say what its band
  wanted must not be counted for or against banking (#755 contract 1:
  silence is not a measurement).
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    COMFORT_SPLIT_IN,
    COMFORT_SPLIT_OUT,
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
    PlanGate,
    UNCOVERED,
)

TODAY = date(2026, 8, 14)


def _calc() -> EnergyCalculator:
    return EnergyCalculator({}, MagicMock())


def _coord(devices, gate: PlanGate):
    """A coordinator-shaped stand-in for the filing seam, in the same
    style as test_769_heat_pump_ledger — plus the plan gate the comfort
    split consults. The REAL ``_comfort_split_for`` is bound onto it, so
    the derivation under test is production code, not a test double."""
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )

    surplus = MagicMock()
    surplus._devices = devices
    coord = SimpleNamespace(
        _energy_calculator=MagicMock(),
        _surplus_controller=surplus,
        _energy_plan_gate=MagicMock(return_value=gate),
    )
    coord._comfort_split_for = SEMCoordinator._comfort_split_for.__get__(coord)
    return coord


def _zone(did="office_ac", kwh=0.5, comfort_state="willing", label=None):
    return SimpleNamespace(
        device_id=did,
        last_cycle_energy_kwh=kwh,
        energy_split_label=label,
        comfort_state=comfort_state,
    )


def _file(coord):
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )

    SEMCoordinator._file_device_energy(coord, TODAY)
    return coord._energy_calculator.accumulate_device_energy


# ───────────────────────────────────────────────────────────────────────
# 1. the split at the filing seam
# ───────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestComfortEnergySplitsOnThePlanBlock772:
    def test_in_block_energy_files_under_the_banked_bucket(self) -> None:
        coord = _coord(
            {"office_ac": _zone()},
            PlanGate(covered=True, in_block=True, block_power_w=1200.0),
        )
        acc = _file(coord)
        assert acc.call_args.kwargs == {"split": COMFORT_SPLIT_IN}
        # and the gate consulted is THIS zone's comfort demand, not load:
        gate_calls = coord._energy_plan_gate.call_args_list
        assert any(c.args[0] == "comfort:office_ac" for c in gate_calls)

    def test_out_of_block_energy_files_under_the_out_bucket(self) -> None:
        coord = _coord(
            {"office_ac": _zone()},
            PlanGate(covered=True, in_block=False),
        )
        assert _file(coord).call_args.kwargs == {"split": COMFORT_SPLIT_OUT}

    def test_no_plan_at_all_is_out_of_block_not_unlabeled(self) -> None:
        """An uncovered gate (no stamp, stale plan, actuation off) is a
        night the planner did NOT bank this zone. That energy belongs in
        the ratio's denominator — filing it unsplit would erase exactly
        the failure mode the ratio exists to expose."""
        coord = _coord({"office_ac": _zone()}, UNCOVERED)
        assert _file(coord).call_args.kwargs == {"split": COMFORT_SPLIT_OUT}

    def test_a_disengaged_band_files_no_comfort_claim(self) -> None:
        """Dead thermometer / no band configured: the zone cannot say
        what its band wanted, so it says nothing (#755 contract 1) —
        and the gate is not even consulted for it."""
        coord = _coord(
            {"pool": _zone(did="pool", comfort_state="disengaged")},
            PlanGate(covered=True, in_block=True),
        )
        assert _file(coord).call_args.kwargs == {"split": None}
        coord._energy_plan_gate.assert_not_called()

    def test_a_device_without_a_band_at_all_is_untouched(self) -> None:
        """Pre-#772 duck-typed devices carry no comfort_state; they file
        exactly as #769 left them."""
        dev = SimpleNamespace(
            device_id="pool", last_cycle_energy_kwh=0.2, energy_split_label=None,
        )
        coord = _coord({"pool": dev}, PlanGate(covered=True, in_block=True))
        assert _file(coord).call_args.kwargs == {"split": None}

    def test_the_device_own_label_stays_senior(self) -> None:
        """A heat pump with an engaged band still files under its
        SG-Ready state. The SG split answers #769's question (did SEM
        shift this energy) and must not be hijacked by #772's — one
        increment files under one bucket, and the device's own name for
        it wins."""
        hp = _zone(did="heat_pump", label="sg3", comfort_state="willing")
        coord = _coord({"heat_pump": hp}, PlanGate(covered=True, in_block=True))
        assert _file(coord).call_args.kwargs == {"split": "sg3"}

    @pytest.mark.parametrize("state", ["forced", "banked", "willing"])
    def test_every_engaged_band_state_is_split(self, state: str) -> None:
        """FORCED at 17:00 is the loss the ratio exists to see; BANKED
        coasting books ~nothing; WILLING inside a block is the plan's own
        run. All three are engaged states and all three file split."""
        coord = _coord(
            {"office_ac": _zone(comfort_state=state)},
            PlanGate(covered=True, in_block=False),
        )
        assert _file(coord).call_args.kwargs == {"split": COMFORT_SPLIT_OUT}


# ───────────────────────────────────────────────────────────────────────
# 2. the ledger read — the ratio's two numbers
# ───────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestTheComfortSplitIsReadable772:
    def test_the_split_reads_back_by_horizon(self) -> None:
        calc = _calc()
        calc.accumulate_device_energy(
            "office_ac", 1.2, TODAY, split=COMFORT_SPLIT_IN)
        calc.accumulate_device_energy(
            "office_ac", 0.4, TODAY, split=COMFORT_SPLIT_OUT)
        split = calc.get_comfort_split("office_ac", TODAY)
        assert split["in_block_today_kwh"] == pytest.approx(1.2)
        assert split["out_block_today_kwh"] == pytest.approx(0.4)
        assert split["in_block_month_kwh"] == pytest.approx(1.2)
        assert split["out_block_month_kwh"] == pytest.approx(0.4)

    def test_the_buckets_sit_beside_the_device_total(self) -> None:
        """#769's contract holds for the comfort buckets too: the split
        is accumulated BESIDE the total, never instead of it."""
        calc = _calc()
        calc.accumulate_device_energy(
            "office_ac", 1.2, TODAY, split=COMFORT_SPLIT_IN)
        calc.accumulate_device_energy(
            "office_ac", 0.4, TODAY, split=COMFORT_SPLIT_OUT)
        total = calc.get_device_energy("office_ac", TODAY)["daily_kwh"]
        assert total == pytest.approx(1.6)

    def test_the_monthly_bucket_outlives_the_daily_prune(self) -> None:
        """The daily accumulators keep today + yesterday only, so 'the
        ratio over a week' has to survive in the monthly bucket — pin
        that the midnight sweep leaves it standing."""
        calc = _calc()
        last_week = TODAY - timedelta(days=6)
        calc.accumulate_device_energy(
            "office_ac", 2.0, last_week, split=COMFORT_SPLIT_IN)
        calc._check_rollover(TODAY, calc._month_key(TODAY), str(TODAY.year))
        split = calc.get_comfort_split("office_ac", TODAY)
        assert split["in_block_today_kwh"] == 0.0
        assert split["in_block_month_kwh"] == pytest.approx(2.0)

    def test_an_unsplit_zone_reads_zero_not_an_error(self) -> None:
        split = _calc().get_comfort_split("office_ac", TODAY)
        assert split["in_block_today_kwh"] == 0.0
        assert split["out_block_today_kwh"] == 0.0

    def test_the_split_survives_a_restart(self) -> None:
        calc = _calc()
        calc.accumulate_device_energy(
            "office_ac", 0.8, TODAY, split=COMFORT_SPLIT_IN)
        fresh = _calc()
        fresh.restore_state(calc.get_state())
        assert fresh.get_comfort_split("office_ac", TODAY)[
            "in_block_today_kwh"] == pytest.approx(0.8)


# ───────────────────────────────────────────────────────────────────────
# 3. the morning reads the ratio
# ───────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestTheNightSealReportsTheRatio772:
    def test_sealing_a_comfort_demand_reads_the_split(self) -> None:
        """The night seal is the production consumer: for every comfort
        demand the night carried, the zone's month in/out ratio is read
        and logged — the feedback #705 Ph3 banks blind without. Pinned so
        ``get_comfort_split`` can never drift back into an orphan whose
        only caller is a test (#653/#660)."""
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )

        rec = MagicMock()
        rec.close_night.return_value = [
            SimpleNamespace(
                demand_id="comfort:office_ac", asked_kwh=1.0,
                planned_kwh=1.0, actual_kwh=0.9, in_block_kwh=0.9,
                measured=True,
            ),
        ]
        calc = MagicMock()
        calc.get_comfort_split.return_value = {
            "in_block_today_kwh": 0.9, "out_block_today_kwh": 0.2,
            "in_block_month_kwh": 5.0, "out_block_month_kwh": 2.0,
        }
        coord = SimpleNamespace(
            _demand_outcomes=rec,
            _energy_calculator=calc,
            time_manager=MagicMock(
                get_current_meter_day_sunrise_based=MagicMock(
                    return_value=TODAY)),
            _persist_demand_outcomes=MagicMock(),
            _refresh_demand_review=MagicMock(),
        )
        SEMCoordinator._seal_demand_outcomes(coord)
        calc.get_comfort_split.assert_called_once_with("office_ac", TODAY)

    def test_a_non_comfort_demand_reads_nothing(self) -> None:
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )

        rec = MagicMock()
        rec.close_night.return_value = [
            SimpleNamespace(
                demand_id="ev:keba", asked_kwh=8.0, planned_kwh=8.0,
                actual_kwh=8.0, in_block_kwh=8.0, measured=True,
            ),
        ]
        calc = MagicMock()
        coord = SimpleNamespace(
            _demand_outcomes=rec,
            _energy_calculator=calc,
            time_manager=MagicMock(),
            _persist_demand_outcomes=MagicMock(),
            _refresh_demand_review=MagicMock(),
        )
        SEMCoordinator._seal_demand_outcomes(coord)
        calc.get_comfort_split.assert_not_called()
