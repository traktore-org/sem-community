"""#906 — a blind meter is not a light slot.

PROD 02.09 20:46–20:50: the grid sensor was ``unavailable`` for 73 s of the
slot's first 8 minutes; the tracker integrated those samples as 0 W, the
allowance climbed from 5856 W to 6187 W inside a slot averaging ~8 kW, and
the guard released at 5.9/6.0 kW. Unread is not zero — and for a security
layer zero is the OPTIMISTIC direction.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.solar_energy_management.coordinator.peak_guard import (
    PeakSlotTracker,
    slot_allowed_import_w,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
)
from custom_components.solar_energy_management.coordinator.decide import (
    clamp_to_peak_slot,
)

from .test_decide import _view as _decide_view

T0 = datetime(2026, 9, 2, 20, 45, 0)
PROD_TABLE = {8: 394.4, 10: 515.0, 12: 582.5, 14: 621.8, 16: 389.1}


@pytest.mark.unit
class TestTheTrackerHoldsTheLastValidSampleAcrossAGap:

    def _run(self, samples):
        tr = PeakSlotTracker()
        for i, w in enumerate(samples):
            tr.update(T0 + timedelta(seconds=10 * i), w)
        return tr

    def test_a_blind_sample_integrates_the_last_valid_import(self):
        steady = self._run([8000.0] * 13)          # 2 min at 8 kW
        blind = self._run([8000.0] * 7 + [None] * 6)
        assert blind.imported_kwh == pytest.approx(steady.imported_kwh)

    def test_a_blind_sample_is_not_zero(self):
        blind = self._run([8000.0] * 7 + [None] * 6)
        zeroed = self._run([8000.0] * 7 + [0.0] * 6)
        assert blind.imported_kwh > zeroed.imported_kwh

    def test_headroom_never_grows_while_blind(self):
        tr = PeakSlotTracker()
        allowed = []
        for i in range(12):
            w = 8000.0 if i < 6 else None
            tr.update(T0 + timedelta(seconds=10 * i), w)
            allowed.append(slot_allowed_import_w(
                6.0, tr.imported_kwh, tr.elapsed_s, blind=tr.blind))
        seen = allowed[5]
        for a in allowed[6:]:
            assert a <= seen + 1e-6, "the allowance may not grow on a blind sample"

    def test_the_tracker_says_when_it_is_blind(self):
        tr = self._run([8000.0, None])
        assert tr.blind is True
        tr.update(T0 + timedelta(seconds=20), 8000.0)
        assert tr.blind is False

    def test_a_slot_boundary_resets_blindness_with_the_slot(self):
        tr = PeakSlotTracker()
        tr.update(T0 + timedelta(seconds=880), 8000.0)
        tr.update(T0 + timedelta(seconds=890), None)
        assert tr.blind is True
        tr.update(T0 + timedelta(seconds=905), 8000.0)   # new slot, real sample
        assert tr.blind is False


@pytest.mark.unit
class TestTheAllowanceIsCappedWhileBlind:

    def test_a_blind_slot_may_not_exceed_the_target(self):
        # Light so far, but we cannot see: never more than the target itself.
        assert slot_allowed_import_w(6.0, 0.1, 600.0, blind=True) == pytest.approx(6000.0)

    def test_a_seen_slot_keeps_its_burst_allowance(self):
        assert slot_allowed_import_w(6.0, 0.1, 600.0) > 6000.0
        assert slot_allowed_import_w(6.0, 0.1, 600.0, blind=False) > 6000.0

    def test_spent_is_spent_either_way(self):
        assert slot_allowed_import_w(6.0, 1.5, 600.0, blind=True) == 0.0


@pytest.mark.unit
class TestTheGuardDoesNotCreditABlindMeter:
    """``_others_w = grid_import − this charger`` — with grid read as 0 the
    house vanished and the EV was offered the whole allowance."""

    def _mk(self, *, grid_known, allowed_w=6000.0, home_w=1000.0,
            grid_import_w=0.0, this_w=8500.0):
        v = _decide_view("solar_plus_battery")
        f = v.fleet
        object.__setattr__(f, "peak_slot_allowed_w", allowed_w)
        object.__setattr__(f, "grid_import_w", grid_import_w)
        object.__setattr__(f, "grid_import_known", grid_known)
        object.__setattr__(f, "home_w", home_w)
        object.__setattr__(v, "wpa_table", dict(PROD_TABLE))
        object.__setattr__(v.power, "power_w", this_w)
        return v

    def _ask(self, amps=14):
        return ChargerDecision(
            charger_id="ch1", mode="solar_plus_battery",
            intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=amps,
            budget_w=8700.0, reason="deadline floor 14A",
        )

    def test_a_blind_meter_charges_the_house_against_the_allowance(self):
        seen = clamp_to_peak_slot(self._ask(), self._mk(grid_known=True,
                                                         grid_import_w=9500.0))
        blind = clamp_to_peak_slot(self._ask(), self._mk(grid_known=False,
                                                          grid_import_w=0.0))
        assert seen.commanded_amps == blind.commanded_amps
        assert blind.commanded_amps < 14, "the house was not read as absent"
        assert blind.capped_by_limit

    def test_fleet_default_is_known(self):
        from custom_components.solar_energy_management.coordinator.charger_types import (
            FleetContext,
        )
        assert FleetContext().grid_import_known is True
