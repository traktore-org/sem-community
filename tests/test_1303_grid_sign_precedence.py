"""#1303 — one place says which grid-sign rule wins.

Ten rules grew in ``sensor_reader.py``, one per bug, and the order lived in
docstrings. ``coordinator/grid_sign.py`` now holds it as a list. This table
states, for every pair of rules that can disagree, which one the read
applies — each row is taken from the test that pinned the rule.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator import grid_sign as gs
from custom_components.solar_energy_management.coordinator.grid_sign import (
    GridSignEvidence,
    grid_sign_decision,
    lock_base,
)
from custom_components.solar_energy_management.tests.test_971_flip_bound_to_source import (
    COMBINED,
    _combined_reader,
)


def ev(**kw) -> GridSignEvidence:
    base = dict(option_invert=False, read_is_pair=False, model_fixed=None,
                lock_detected=False, lock_inverted=False,
                flip_bound_here=False, flip_on_old_lock=False)
    base.update(kw)
    return GridSignEvidence(**base)


class TestTheOrderIsWrittenDown:
    def test_the_list_names_the_five_steps(self):
        assert gs.PRECEDENCE == ("option", "pair", "model", "lock", "none")

    def test_every_source_a_decision_can_name_is_in_the_list(self):
        seen = set()
        for e in (ev(option_invert=True), ev(read_is_pair=True),
                  ev(model_fixed=True), ev(lock_detected=True), ev()):
            seen.add(grid_sign_decision(e).source)
        assert seen == set(gs.PRECEDENCE)


# (winner, evidence, expected base) — one row per pair that can disagree
TABLE = [
    # option beats the lock (#352: the setting short-circuits the autodetect)
    ("option > lock", ev(option_invert=True, lock_detected=True, lock_inverted=False), True),
    # option beats a pair (the setting is the user's word, a pair is a read)
    ("option > pair", ev(option_invert=True, read_is_pair=True), True),
    # option beats the model
    ("option > model", ev(option_invert=True, model_fixed=False), True),
    # a pair takes no lock (#1215)
    ("pair > lock", ev(read_is_pair=True, lock_detected=True, lock_inverted=True), False),
    # the model beats the lock (#1294: a saved lock said the opposite)
    ("model > lock", ev(model_fixed=True, lock_detected=True, lock_inverted=False), True),
    ("model > lock (other way)", ev(model_fixed=False, lock_detected=True, lock_inverted=True), False),
    # the lock beats nothing-known
    ("lock > none", ev(lock_detected=True, lock_inverted=True), True),
    # no lock: the flag as it stands (the self-heal's put-back)
    ("none keeps the flag", ev(lock_inverted=True), True),
    ("none, fresh reader", ev(), False),
]


@pytest.mark.parametrize("name, evidence, base", TABLE, ids=[t[0] for t in TABLE])
def test_which_rule_wins(name, evidence, base):
    d = grid_sign_decision(evidence)
    assert d.base_negate is base, name
    assert d.source == gs.PRECEDENCE[[
        evidence.option_invert, evidence.read_is_pair,
        evidence.model_fixed is not None, evidence.lock_detected, True].index(True)]


class TestTheFlipSitsOnTop:
    """#461: the one-tap flip turns the base around, whatever decided it."""

    @pytest.mark.parametrize("base_ev", [
        ev(option_invert=True), ev(read_is_pair=True), ev(model_fixed=True),
        ev(lock_detected=True, lock_inverted=True), ev(),
    ], ids=["option", "pair", "model", "lock", "none"])
    def test_a_bound_flip_turns_every_base_around(self, base_ev):
        plain = grid_sign_decision(base_ev)
        flipped = grid_sign_decision(ev(**{**base_ev.__dict__, "flip_bound_here": True}))
        assert flipped.flip is True
        assert flipped.negate is (not plain.negate)
        assert flipped.base_negate is plain.base_negate

    def test_a_flip_bound_elsewhere_does_nothing(self):
        # #971 / #1192
        d = grid_sign_decision(ev(lock_detected=True, flip_bound_here=False))
        assert d.flip is False and d.negate is False

    def test_a_flip_tapped_against_an_old_lock_on_a_fixed_meter_is_off(self):
        # #1294: the model now sets the sign; the flip would turn it around
        d = grid_sign_decision(ev(model_fixed=True, flip_bound_here=True,
                                  flip_on_old_lock=True))
        assert d.flip is False and d.negate is True

    def test_the_same_flip_on_the_option_read_stays_on(self):
        # the option read takes no lock: _flip_on_an_old_lock is False there,
        # so the evidence never carries True with the option; pin the pure rule
        d = grid_sign_decision(ev(option_invert=True, flip_bound_here=True))
        assert d.negate is False


class TestTheReaderUsesTheOnePlace:
    def test_detect_returns_what_the_decision_says(self):
        r = _combined_reader()
        readings = r.read_power()
        assert r._detect_grid_sign(readings) is lock_base(r.grid_sign_evidence())[0]
        assert r.grid_sign_decision().source == "lock"

    def test_the_read_applies_base_then_flip(self):
        # lock says no negation, a flip bound to the combined meter turns it:
        # +2000 raw reads as 2000 W of import (SEM: − is import)
        r = _combined_reader(flip=True, flip_source=f"combined:{COMBINED}")
        readings = r.read_power()
        d = r.grid_sign_decision()
        assert (d.base_negate, d.flip, d.negate) == (False, True, True)
        assert readings.grid_power == -2000
        assert r.user_flip_applies() is d.flip

    def test_the_option_wins_and_the_detectors_do_not_run(self):
        r = _combined_reader()
        r._raw_config["grid_sign_invert"] = True
        r._grid_sign_detected = False
        readings = r.read_power()
        assert r.grid_sign_decision().source == "option"
        assert readings.grid_power == -2000
        assert r._grid_sign_detected is False
