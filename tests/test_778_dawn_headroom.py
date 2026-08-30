"""#778 — the refill headroom is the room the pack has AT DAWN, not now.

Found live on .175 on 30.08.2026 during the 2.1 pre-release campaign. The
rig sat at SOC 100 % on the eve of a day whose forecast would clip 49 kWh,
and ``sensor.sem_battery_spendable_kwh`` read **0.0** with the reason
"nothing spendable — tomorrow's forecast refills nothing", while the refill
estimator's own string on the same entity said:

    "0.0 kWh fits, 49.3 kWh would be clipped — spending that tonight costs
     nothing, the pack cannot hold it"

Both sentences came from the same cycle. The estimator was right and the
number was wrong, because the caller measured headroom as

    usable_kwh * (100 - soc_now) / 100

— the room the pack has at SUNSET. At SOC 100 that is 0 by construction, so
``refill = min(surplus, 0) = 0``, so rule 3 ("only spend what tomorrow puts
back") spends nothing.

The refill question is "will tomorrow's sun put back what I spend tonight".
The pack does not receive that sun at sunset; it receives it after the
overnight draw. So the room that matters is the room at dawn. Measuring it
now inverts the feature exactly where it is most confident — a full pack on
the eve of a clipping day is the textbook case for spending overnight, and
it is the one case that returned zero.

The inversion is visible as non-monotonicity: with headroom-now, SOC 95
spent 0.75 kWh and SOC 100 spent 0.00. A fuller pack must never be allowed
to spend less than a less-full one.
"""
import pytest

from custom_components.solar_energy_management.coordinator.refill_estimate import (
    dawn_headroom_kwh,
    estimate_refill,
)
from custom_components.solar_energy_management.coordinator.spendable_budget import (
    spendable_budget,
)

# The .175 evening that exposed this, to the digit.
USABLE = 15.0
NEED = 6.99
TRUST = 0.862
FORECAST = 60.0


def _spendable(soc, *, usable=USABLE, need=NEED):
    hr = dawn_headroom_kwh(usable, soc, need)
    r = estimate_refill(FORECAST, house_tomorrow_kwh=need,
                        committed_demand_kwh=0.0,
                        pack_headroom_kwh=hr, trust=TRUST)
    b = spendable_budget(soc_pct=soc, usable_capacity_kwh=usable,
                         overnight_need_kwh=need,
                         expected_refill_kwh=r.refill_kwh,
                         static_floor_pct=None, pessimism=None,
                         discharge_efficiency=None,
                         refill_trusted=bool(r.trusted))
    return b.spendable_kwh


class TestDawnHeadroom:
    def test_room_at_dawn_is_room_now_plus_the_overnight_draw(self):
        # SOC 100 of a 15 kWh pack that will draw 6.99 kWh overnight lands
        # at 8.01 kWh, so it can absorb 6.99 kWh of tomorrow's sun.
        assert dawn_headroom_kwh(15.0, 100.0, 6.99) == pytest.approx(6.99)
        # SOC 80 already has 3.0 kWh of room; the night adds its own draw.
        assert dawn_headroom_kwh(15.0, 80.0, 6.99) == pytest.approx(9.99)

    def test_never_promises_more_room_than_the_pack_has(self):
        # A night bigger than the pack cannot make the pack bigger.
        assert dawn_headroom_kwh(15.0, 40.0, 99.0) == pytest.approx(15.0)
        assert dawn_headroom_kwh(15.0, 0.0, 0.0) == pytest.approx(15.0)

    def test_a_full_pack_still_has_room_by_dawn(self):
        assert dawn_headroom_kwh(15.0, 100.0, 6.99) > 0.0

    @pytest.mark.parametrize("bad", [None, "", "abc", float("nan")])
    def test_a_dark_input_is_not_permission(self, bad):
        # Rule 4: unknown spends nothing. None flows to estimate_refill's
        # "no idea what the pack can hold" branch rather than inventing a
        # headroom of zero (which would silently mean "refill nothing").
        assert dawn_headroom_kwh(bad, 100.0, 6.99) is None
        assert dawn_headroom_kwh(15.0, bad, 6.99) is None

    def test_an_unknown_night_is_treated_as_no_extra_room(self):
        # Not knowing the overnight draw must not INVENT room; it falls
        # back to the room the pack has now, which is the conservative half.
        assert dawn_headroom_kwh(15.0, 80.0, None) == pytest.approx(3.0)


class TestTheInversionIsGone:
    def test_a_full_pack_on_a_clipping_day_has_something_spendable(self):
        """The exact .175 reading: SOC 100, 49 kWh would be clipped."""
        assert _spendable(100.0) > 0.0

    def test_a_fuller_pack_never_spends_less(self):
        """The inversion, stated as the invariant it broke."""
        socs = [50.0, 60.0, 70.0, 80.0, 85.0, 90.0, 95.0, 100.0]
        vals = [_spendable(s) for s in socs]
        for lo, hi, a, b in zip(socs, socs[1:], vals, vals[1:]):
            assert b >= a - 1e-9, (
                f"SOC {hi} spends {b:.2f} kWh but SOC {lo} spends {a:.2f} — "
                "a fuller pack must never be allowed to spend less"
            )

    def test_the_floor_still_wins_at_the_bottom(self):
        """Dawn headroom relaxes rule 3, never rules 1 and 2."""
        assert _spendable(50.0) == 0.0
        assert _spendable(30.0) == 0.0
