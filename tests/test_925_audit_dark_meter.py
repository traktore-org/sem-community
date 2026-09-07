"""(#925 audit) Two live defects a ruflo pass found in the 2.1 diff, both
the same shape: a reading that was never taken, used as a measurement.

SEM's own doctrine is that an absent reading is not a reading of zero, and
both of these had the twin flag already computed one file away. Neither was
wired to its consumer. On the maintainer's hardware the grid read is absent
~137 times a day, so neither is hypothetical.
"""

from __future__ import annotations

from custom_components.solar_energy_management.coordinator.energy_reclaim import (
    REDIRECT_IMPORT_TOLERANCE_W,
    REDIRECT_VETO_STRIKES,
    redirect_strikes,
)
from custom_components.solar_energy_management.coordinator.peak_guard import (
    clamp_import_command,
)


class TestADarkMeterIsNotAgreement:
    """#899's veto counts three cycles where a credited redirect did not
    show up at the meter. A dark meter reads 0 W — below any tolerance —
    so the unguarded rule called it "the pack yielded after all" and reset
    the count. One routine blip interleaved with failing cycles delays the
    veto indefinitely: the safety mechanism disabled by exactly the
    condition it exists for."""

    IMPORTING = dict(redirect_w=1500.0, grid_import_w=2000.0, charging=True)

    def test_a_readable_meter_still_strikes(self):
        assert redirect_strikes(0, **self.IMPORTING) == 1
        assert redirect_strikes(1, **self.IMPORTING) == 2

    def test_a_readable_meter_that_agrees_still_forgives(self):
        assert redirect_strikes(2, redirect_w=1500.0, grid_import_w=0.0,
                                charging=True) == 0

    def test_a_dark_meter_neither_strikes_nor_forgives(self):
        """No evidence either way — hold the count."""
        assert redirect_strikes(2, redirect_w=1500.0, grid_import_w=0.0,
                                charging=True, grid_import_known=False) == 2
        assert redirect_strikes(0, redirect_w=1500.0, grid_import_w=0.0,
                                charging=True, grid_import_known=False) == 0

    def test_a_blip_no_longer_delays_the_veto(self):
        """The reported failure, end to end: fail, blip, fail, fail. Before
        the fix the blip reset the count and the veto never landed."""
        n = 0
        n = redirect_strikes(n, **self.IMPORTING)                       # 1
        n = redirect_strikes(n, redirect_w=1500.0, grid_import_w=0.0,
                             charging=True, grid_import_known=False)    # dark
        n = redirect_strikes(n, **self.IMPORTING)                       # 2
        n = redirect_strikes(n, **self.IMPORTING)                       # 3
        assert n >= REDIRECT_VETO_STRIKES, (
            f"a single dark cycle still swallows strikes: reached {n}")

    def test_the_tolerance_is_what_a_readable_meter_is_judged_against(self):
        assert redirect_strikes(
            0, redirect_w=1500.0,
            grid_import_w=REDIRECT_IMPORT_TOLERANCE_W - 1, charging=True) == 0


class TestADarkMeterProvesNoHeadroom:
    """#864's cheap-hours grid-forced start asks the slot budget whether a
    load fits. `others_w` credits everyone else's current draw — and a dark
    meter credited ZERO, inflating headroom to the whole allowance. That is
    #906's defect ("headroom grew the longer the meter stayed dark") in a
    sibling call site the #906 fix did not cover. The sibling computing the
    slot CEILING gates on the same flag correctly."""

    def test_a_readable_meter_grants_only_what_is_left(self):
        got, clamped = clamp_import_command(3000.0, 5000.0, 4000.0)
        assert (got, clamped) == (1000.0, True)

    def test_a_readable_meter_passes_a_command_that_fits(self):
        assert clamp_import_command(500.0, 5000.0, 1000.0) == (500.0, False)

    def test_a_dark_meter_grants_nothing(self):
        """Refusing is preventive: it declines to START a grid-funded load
        while blind and touches nothing already running."""
        got, clamped = clamp_import_command(
            3000.0, 5000.0, 0.0, grid_import_known=False)
        assert got == 0.0 and clamped is True, (
            "a dark meter was credited as 'nobody else is drawing' and "
            "handed out the whole slot allowance")

    def test_no_ceiling_configured_still_passes_through(self):
        """The guard being off is not the same as the meter being dark."""
        assert clamp_import_command(
            9000.0, None, 0.0, grid_import_known=False) == (9000.0, False)
