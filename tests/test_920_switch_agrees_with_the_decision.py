"""#920 — the switch and the decision must answer the same question.

Seen on PROD 06.09.2026 20:05: `switch.sem_battery_may_export` read **off**
while SEM opened a 5 kW sell block ("selling before the night"). Nothing
actually sold, and only because that battery happened to be pinned to an
adapter with no forced-discharge path (#919) — on a Huawei adapter it would
have sold the pack to the grid under a switch that said no.

Neither side was wrong on its own. TWO features can sell — #533's arbitrage
(gated by `battery_grid_arbitrage_enabled`) and #778's forecast spend (gated
by `forecast_spending_enabled`) — and each asks `may_export` with its own
flag, which is correct. The switch asked with only the arbitrage one, so it
answered "may the ARBITRAGE feature sell?" while wearing the label "Battery
may sell to grid".

`tests/test_knob_wiring.py` guards that the permission is READ at all. This
guards that the two readers AGREE, across every combination — which is the
property a user actually relies on.
"""
from __future__ import annotations

import itertools

import pytest

from custom_components.solar_energy_management.consts.battery_modes import (
    arbitrage_allowed_for_mode,
)
from custom_components.solar_energy_management.consts.battery_permissions import (
    effective_permissions,
)

MODES = ("auto", "self_consumption", "allow_arbitrage", "off")
PERMS = (None, {"may_export": True}, {"may_export": False})
FLAGS = (False, True)


def _switch_shows(mode, stored, arbitrage_on, spend_on) -> bool:
    """What switch.py renders — every path that can sell."""
    from custom_components.solar_energy_management.switch import (
        battery_may_export_display,
    )
    return battery_may_export_display(mode, stored, arbitrage_on, spend_on)


def _decision_may_sell(mode, stored, arbitrage_on, spend_on) -> bool:
    """A MODEL of what decide_battery asks — written out here rather than
    calling the switch's helper, so this stays a comparison and not a
    tautology. `test_the_decision_site_still_has_this_shape` below pins the
    model against the real call site."""
    perms = effective_permissions(mode, stored)
    return bool(arbitrage_allowed_for_mode(mode, arbitrage_on, perms)
                or arbitrage_allowed_for_mode(mode, spend_on, perms))


@pytest.mark.unit
class TestTheSwitchAnswersItsOwnLabel:

    @pytest.mark.parametrize(
        "mode,stored,arb,spend",
        [(m, p, a, s) for m, p, a, s
         in itertools.product(MODES, PERMS, FLAGS, FLAGS)])
    def test_the_switch_agrees_with_the_decision(self, mode, stored, arb, spend):
        shown = _switch_shows(mode, stored, arb, spend)
        will = _decision_may_sell(mode, stored, arb, spend)
        assert shown == will, (
            f"mode={mode} perms={stored} arbitrage={arb} spend={spend}: "
            f"switch shows {shown}, decision would {'sell' if will else 'not sell'}")

    def test_the_prod_case_that_found_it(self):
        """auto, no stored permission, arbitrage OFF, spend ON — the exact
        PROD configuration. The switch used to read off while the spend path
        sold."""
        assert _switch_shows("auto", None, False, True) is True
        assert _decision_may_sell("auto", None, False, True) is True

    def test_a_revoked_permission_still_blocks_both_paths(self):
        """The thing the switch is FOR: an explicit no stops every seller,
        whichever feature is enabled."""
        for arb, spend in itertools.product(FLAGS, FLAGS):
            assert _switch_shows("auto", {"may_export": False}, arb, spend) is False
            assert _decision_may_sell("auto", {"may_export": False}, arb, spend) is False

    def test_self_consumption_never_sells(self):
        """Guido, 06.09: 'I set it to self consumption, because I do not want
        to sell to grid.' That must hold with every feature switched on."""
        assert _switch_shows("self_consumption", None, True, True) is False
        assert _decision_may_sell("self_consumption", None, True, True) is False

    def test_nothing_enabled_sells_nothing(self):
        for mode in ("auto", "self_consumption", "off"):
            assert _decision_may_sell(mode, None, False, False) is False

    def test_a_revocation_beats_the_legacy_allow_arbitrage_mode(self):
        """Found by the combination guard, not by looking for it: on the
        legacy `allow_arbitrage` mode SEM sold even when the user had
        explicitly revoked the permission — the switch said no and the pack
        went to the grid. An UNSET permission still short-circuits, so an
        existing install that never touched the switch does not move."""
        revoked = {"may_export": False}
        assert _decision_may_sell("allow_arbitrage", revoked, True, True) is False
        assert _switch_shows("allow_arbitrage", revoked, True, True) is False
        # untouched: the legacy opt-in still beats both master switches
        assert _decision_may_sell("allow_arbitrage", None, False, False) is True


    def test_the_decision_site_still_has_this_shape(self):
        """The model above is only worth something while decide_battery
        really asks `arbitrage_allowed_for_mode(mode, <this feature's own
        flag>, perms)`. If that call moves or gains an argument, the model
        is stale and this whole file is measuring nothing."""
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "coordinator" / "decide_battery.py").read_text()
        assert "arbitrage_allowed_for_mode(mode, _gate_flag, _perms)" in src, (
            "decide_battery's permission call changed — re-derive the model")
        assert '_gate_flag = (bool(getattr(view, "forecast_spending_enabled", False))' in src, (
            "the spend path no longer gates on its own switch")
