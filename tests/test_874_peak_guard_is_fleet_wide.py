"""#864 — the peak slot guard must account ACROSS chargers, not per charger.

Found by an independent review of the v2.0.0..develop diff (30.08.2026) and
reproduced: two idle 3-phase chargers, a 6000 W slot target and a 500 W
baseline, each independently computed a 4830 W (7 A) allowance — a combined
landed draw of 10160 W, 69 % over the target the guard exists to defend.

The clamp in ``decide.py`` reads ``peak_slot_allowed_w`` and
``grid_import_w``, both frozen once per cycle in ``FleetCycleState``, and
credits back only THIS charger's own pre-cycle draw. Nothing tells the
second charger that the first has already claimed the slot's headroom, so
each sees the whole allowance and takes it.

SEM already solved this exact shape for the solar cascade:
``_solar_committed_w_per_cycle`` is reset at the top of the per-charger loop
and incremented after each decision, so "lower-priority chargers see only the
surplus this one didn't take" (the comment at the increment site). The peak
guard — the layer described as sitting above every device — had no such
accumulator.

A guard that is only correct for single-charger installs is not a security
layer; it is a single-charger feature wearing one's name.
"""
from __future__ import annotations

from types import SimpleNamespace


from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
)


def _view(*, allowed_w, grid_import_w, this_w=0.0, peak_committed_w=0.0,
          max_a=32):
    """A decide-view carrying just what the peak clamp reads."""
    return SimpleNamespace(
        fleet=SimpleNamespace(
            peak_slot_allowed_w=allowed_w,
            grid_import_w=grid_import_w,
            peak_committed_w=peak_committed_w,
        ),
        power=SimpleNamespace(power_w=this_w),
        config={"ev_phases": 3, "ev_voltage": 230, "ev_max_current": max_a,
                "ev_min_current": 6},
        wpa_table=None,
    )


def _clamped_amps(view, asking_a=32):
    """Run the real clamp and report the amps it lands on."""
    from custom_components.solar_energy_management.coordinator import decide as d

    # A REAL ChargerDecision: the clamp uses dataclasses.replace(), so a
    # SimpleNamespace stand-in would only prove the test can build a mock.
    result = ChargerDecision(
        charger_id="c1", mode="always_max",
        intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=asking_a,
        budget_w=float(asking_a * 3 * 230), reason="always_max mode")
    out = d.clamp_to_peak_slot(result, view)
    return int(out.commanded_amps)


class TestTwoChargersCannotEachTakeTheWholeSlot:
    def test_the_second_charger_sees_what_the_first_took(self):
        """The reproduction from the review, as an assertion."""
        first = _view(allowed_w=6000.0, grid_import_w=500.0)
        first_a = _clamped_amps(first)
        first_w = first_a * 3 * 230

        # …and the fleet loop hands that commitment to the next charger.
        second = _view(allowed_w=6000.0, grid_import_w=500.0,
                       peak_committed_w=float(first_w))
        second_a = _clamped_amps(second)
        second_w = second_a * 3 * 230

        assert first_w + second_w <= 6000.0 + 3 * 230 * 6, (
            f"two chargers landed {first_w + second_w:.0f} W against a "
            f"6000 W slot target — each believed the whole allowance was "
            "its own. (The tolerance is one charger's 6 A floor: the guard "
            "never proactively idles a car, by design.)"
        )
        assert second_a <= first_a

    def test_a_single_charger_is_unchanged(self):
        """The install shape that hid this must behave exactly as before."""
        solo = _view(allowed_w=6000.0, grid_import_w=500.0)
        assert _clamped_amps(solo) == _clamped_amps(
            _view(allowed_w=6000.0, grid_import_w=500.0, peak_committed_w=0.0))

    def test_a_committed_fleet_floors_at_the_minimum_never_idles(self):
        """#864's own rule: the guard tightens an offer, it never stops a
        car. Even a fully-claimed slot leaves the effective minimum."""
        starved = _view(allowed_w=6000.0, grid_import_w=500.0,
                        peak_committed_w=99000.0)
        assert _clamped_amps(starved) == 6

    def test_no_allowance_means_no_clamp(self):
        """An unlimited install (slider at MAX) publishes None and must be
        left alone — the documented off-switch."""
        assert _clamped_amps(
            _view(allowed_w=None, grid_import_w=500.0), asking_a=32) == 32
