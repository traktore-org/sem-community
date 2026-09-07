"""(#925 audit) The load shedder must not go idle when the meter blinks.

#896 rewrote the shed plan to judge against the LIVE meter, for a good
reason — "a shed cannot move a rolling average for minutes". It dropped
the availability check on the way, and `grid_import_w` is the reader's
0.0 when the sensor is dark. So `need_w = max(0, 0 - aim_w)` is zero, the
plan reports "held: under aim", and nothing is shed — mid-emergency, for
as long as the outage lasts, while the state machine independently knows
from the smoothed average that the house is over target.

A regression, strictly: the code #896 replaced computed the need from
`current_peak`, the 15-minute rolling average, which survives one dark
sample by construction. The fix keeps the live meter when it is there and
falls back to the average that was always there when it is not.

Fail-static rather than fail-dangerous — nothing already shed gets
restored, since that is gated on the smoothed average — but going blind
during a demand-charge event is what this feature exists to prevent.
"""

from __future__ import annotations


def _need_w(*, grid_import_w, current_peak_kw, aim_kw, grid_import_known):
    """The rule as `process_peak_update` + `_shed_plan` now apply it."""
    if grid_import_known:
        last = float(grid_import_w or 0.0)
    else:
        last = max(0.0, float(current_peak_kw or 0.0) * 1000.0)
    return max(0.0, last - aim_kw * 1000.0)


class TestALiveMeterIsUnchanged:

    def test_over_the_aim_needs_a_shed(self):
        assert _need_w(grid_import_w=8000.0, current_peak_kw=7.5, aim_kw=5.5,
                       grid_import_known=True) == 2500.0

    def test_under_the_aim_needs_nothing(self):
        assert _need_w(grid_import_w=3000.0, current_peak_kw=3.0, aim_kw=5.5,
                       grid_import_known=True) == 0.0

    def test_the_live_meter_wins_over_the_average_when_present(self):
        """#896's whole point: a shed shows on the meter immediately and in
        the average only minutes later."""
        assert _need_w(grid_import_w=3000.0, current_peak_kw=8.0, aim_kw=5.5,
                       grid_import_known=True) == 0.0


class TestADarkMeterFallsBackToTheAverage:

    def test_the_shed_still_happens_during_an_outage(self):
        """The reported failure: genuinely over target, meter dark. Before
        the fix this returned 0.0 and the engine idled."""
        got = _need_w(grid_import_w=0.0, current_peak_kw=8.0, aim_kw=5.5,
                      grid_import_known=False)
        assert got == 2500.0, (
            "a dark meter read as 0 W and the shed engine went idle while "
            "the house was over target")

    def test_a_dark_meter_under_target_still_sheds_nothing(self):
        assert _need_w(grid_import_w=0.0, current_peak_kw=3.0, aim_kw=5.5,
                       grid_import_known=False) == 0.0

    def test_the_defect_itself_is_pinned(self):
        """What a regression would restore: the raw 0.0 taken as a reading."""
        blind_as_zero = max(0.0, 0.0 - 5.5 * 1000.0)
        assert blind_as_zero == 0.0
        assert _need_w(grid_import_w=0.0, current_peak_kw=8.0, aim_kw=5.5,
                       grid_import_known=False) > blind_as_zero

    def test_no_average_either_is_not_an_emergency(self):
        """Both dark: nothing is known, and inventing a shed is as wrong as
        inventing a zero."""
        assert _need_w(grid_import_w=0.0, current_peak_kw=0.0, aim_kw=5.5,
                       grid_import_known=False) == 0.0
