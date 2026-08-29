"""#779 — Mode = Off must mean SEM keeps its hands off, including its books.

onkelfu, on v2.0.0-beta.3: his dishwasher is configured **Mode: Off**, and
SEM switches it off anyway — reproducibly, within seconds of an HA restart.
The same for his heat pump and network gear. beta.3 retired the duplicate
``load_device_spuelmaschine`` row he was pointed at; the switch-off survived
that, because the duplicate was never the mechanism.

The mechanism is one flag, written by a path that cannot know what it means.

``_sem_owned`` answers "did SEM start this load?", and exactly one clause
acts on it: ``compute_load_intent``'s class-17 release — *mode switched to
Off while SEM is DRIVING the load, so stop it once and let go* (PROD
2026-07-23). That clause is right, and it is careful: a load the USER turned
on is deliberately left alone.

But #766 added ``sync_belief_to_observation``, the per-cycle twin of
``adopt_if_running``, so a switch that turns on outside SEM's own
``activate()`` stops being invisible. It adopts belief AND ownership — for
every device in the walk, at every mode. ``adopt_if_running``, the one-shot
it was modelled on, is gated at both call sites on
``control_mode == SURPLUS``; the per-cycle twin inherited the body and not
the gate.

So a load the user switches on under Mode = Off is *claimed* by SEM on the
next cycle, and the release clause — reading a flag that now says SEM was
driving it — stops it. After a restart the belief starts IDLE and the switch
is already ON, so the very first cycle does it. The user turns it back on;
SEM takes it away again.

Ownership is a fact about who acted, not a summary of what is on. The fix is
the gate the one-shot already had: adopt the belief at any mode (the books
should be honest, and Off is monitoring), claim ownership only where SEM is
allowed to drive.
"""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock, Mock


from custom_components.solar_energy_management.coordinator.surplus_controller import (
    compute_load_intent,
)
from custom_components.solar_energy_management.coordinator.plan_verdict import (
    PlanVerdict,
)
from custom_components.solar_energy_management.devices import base as _devbase
from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode, DeviceState, SwitchDevice,
)


def _dev(mode=DeviceControlMode.OFF, state="on", believes_active=False):
    """onkelfu's dishwasher: a real switch, user-operated, Mode = Off."""
    hass = MagicMock()
    st = Mock()
    st.state = state
    hass.states.get = Mock(return_value=st)
    d = SwitchDevice(
        hass=hass,
        device_id="energy_dashboard_spuelmaschine",
        name="Spülmaschine",
        rated_power=2000.0,
        entity_id="switch.spuelmaschine",
    )
    d.control_mode = mode
    if believes_active:
        d._status.state = DeviceState.ACTIVE
    return d


class TestOwnershipIsAFactAboutWhoActed:
    """``_sem_owned`` must not be manufactured by an observation."""

    def test_an_off_mode_load_is_seen_but_not_claimed(self):
        # The user switched the dishwasher on. SEM may write that down.
        # It may not conclude from it that SEM started the dishwasher.
        d = _dev(mode=DeviceControlMode.OFF, state="on")
        assert d.sync_belief_to_observation() is True
        assert d.is_active is True, "Off is monitoring — the books stay honest"
        assert d._sem_owned is False, (
            "SEM claimed a load it never touched; the class-17 release "
            "clause reads this flag and will switch the user's load off"
        )

    def test_a_peak_only_load_is_seen_but_not_claimed(self):
        # Peak-only is the user's load too — SEM only sheds it under peak
        # risk, which is the load manager's business, not ownership.
        d = _dev(mode=DeviceControlMode.PEAK_ONLY, state="on")
        assert d.sync_belief_to_observation() is True
        assert d.is_active is True
        assert d._sem_owned is False

    def test_a_surplus_load_is_still_claimed(self):
        # #766's whole point: under SURPLUS an external ON comes under
        # normal control, so goal gates and force expiry can stop it.
        # That must not regress.
        d = _dev(mode=DeviceControlMode.SURPLUS, state="on")
        assert d.sync_belief_to_observation() is True
        assert d.is_active is True
        assert d._sem_owned is True

    def test_an_external_off_still_releases_at_any_mode(self):
        d = _dev(mode=DeviceControlMode.OFF, state="off", believes_active=True)
        d._sem_owned = True
        assert d.sync_belief_to_observation() is True
        assert d.is_active is False


class TestTheUsersLoadSurvivesTheWalk:
    """End of the chain: the intent the walk actually computes."""

    def test_sem_does_not_stop_a_load_the_user_switched_on_under_mode_off(self):
        d = _dev(mode=DeviceControlMode.OFF, state="on")
        d.sync_belief_to_observation()          # the cycle SEM sees it come on
        intent = compute_load_intent(
            d, remaining_surplus_w=0.0, is_shed_target=False, plan=PlanVerdict(),
        )
        assert intent.on is True, (
            "Mode = Off and SEM issued a stop — onkelfu's report exactly"
        )
        assert "releasing" not in intent.reason

    def test_a_mode_flip_while_sem_drives_the_load_still_releases_it(self):
        # The clause the fix must NOT break: SEM really was driving this one
        # (it called activate()), the user then moved the mode to Off.
        # Stranding it running forever was the 2026-07-23 PROD bug.
        d = _dev(mode=DeviceControlMode.OFF, state="on", believes_active=True)
        d._sem_owned = True                     # set by SEM's own activate()
        intent = compute_load_intent(
            d, remaining_surplus_w=0.0, is_shed_target=False, plan=PlanVerdict(),
        )
        assert intent.on is False
        assert "releasing" in intent.reason


class TestOneWriterForTheClaim:
    """The structural close-out — the reason this is #779 and not a fourth
    copy of the same gate.

    ``tests/test_load_ownership_choke_point.py`` already funnels *actuation*
    through ``_activate_owned``/``_deactivate_owned`` and lints for raw call
    sites — bug class 17, instance 5, the towel heater that drew 648 W five
    minutes after Mode → Off. That discipline was right; its SCOPE was one
    file. The claim has a second family of writers — the three that adopt an
    observed ON — and they live in ``devices/base.py``, which the lint never
    read. Each carried the mode gate separately (or, in #766's case, not at
    all): ``adopt_if_running`` relied on BOTH its call sites in
    ``device_registry.py`` to check the mode before calling it, and
    ``sync_belief_to_observation`` checked nothing.

    So: one writer, ``_adopt_ownership``, which holds the gate itself. The
    call-site gates become redundant and go — duplicated policy that can
    drift is the same hazard one step later.

    The asymmetry is deliberate and is what the guard encodes: RELEASING
    ownership (``= False``) is always safe and stays free — the reconciler
    and ``mark_reconciled_off`` do it. CLAIMING it is the direction that
    needs a reason.
    """

    _BASE = Path(_devbase.__file__)
    # ``record_activated`` is the other sanctioned claim: SEM issued the
    # command itself, so it owns the result by construction — no observation
    # to second-guess. ``_adopt_ownership`` is the one for everything SEM
    # merely SAW turn on.
    _CLAIM_SITES = {"record_activated", "_adopt_ownership"}

    def _claiming_assignments(self, path: Path):
        """Every ``*._sem_owned = …`` that DECIDES ownership, with its
        enclosing function.

        Two forms are not decisions and stay free:

        * ``= False`` — a release. Always safe: handing a load back needs no
          justification, which is why the reconciler and ``mark_reconciled_off``
          do it directly.
        * ``= <other>._sem_owned`` — carrying a decision already made.
          ``SurplusController.register_device`` transplants ownership onto the
          fresh object when a rebuild replaces a RUNNING load; that must keep
          working, including when it carries a stale ``True`` onto a device
          whose mode has since become Off — the ``compute_load_intent``
          release is the backstop that then stops it once.

        Anything else is a new claim, and new claims need the gate.
        """
        tree = ast.parse(path.read_text())
        parent_of = {}
        for scope in ast.walk(tree):
            if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for node in ast.walk(scope):
                    parent_of.setdefault(node, scope.name)
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for tgt in node.targets:
                if not isinstance(tgt, ast.Attribute) or tgt.attr != "_sem_owned":
                    continue
                val = node.value
                if isinstance(val, ast.Constant) and val.value is False:
                    continue
                if isinstance(val, ast.Attribute) and val.attr == "_sem_owned":
                    continue
                found.append((parent_of.get(node, "<module>"), node.lineno))
        return found

    def test_the_claim_has_exactly_one_adoption_writer(self):
        offenders = [
            f"{fn}:{line}" for fn, line in self._claiming_assignments(self._BASE)
            if fn not in self._CLAIM_SITES
        ]
        assert not offenders, (
            "_sem_owned is claimed outside the sanctioned writers "
            f"{sorted(self._CLAIM_SITES)}. Every one of these has to remember "
            "the mode gate on its own — which is how #779 happened. Route it "
            f"through _adopt_ownership(). Found:\n  " + "\n  ".join(offenders)
        )

    def test_nothing_outside_the_device_layer_claims_ownership(self):
        repo = self._BASE.parent.parent
        offenders = []
        for path in sorted(repo.rglob("*.py")):
            rel = path.relative_to(repo)
            if rel.parts[0] in ("tests", "dashboard", "docs"):
                continue
            if path == self._BASE:
                continue
            for fn, line in self._claiming_assignments(path):
                offenders.append(f"{rel}:{line} (in {fn})")
        assert not offenders, (
            "Ownership is claimed outside devices/base.py — releases are "
            "free, claims are not. Found:\n  " + "\n  ".join(offenders)
        )

    def test_the_adopters_all_route_through_it(self):
        src = self._BASE.read_text()
        assert "def _adopt_ownership(" in src, "_adopt_ownership was removed"
        # sync_belief_to_observation + SwitchDevice/ClimateDevice adopt_if_running
        assert src.count("self._adopt_ownership(") >= 3, (
            "an adoption path stopped routing through _adopt_ownership"
        )

    def test_the_registry_no_longer_carries_a_duplicate_gate(self):
        """The two call-site gates were the ones that had to be remembered.
        With the gate inside, they are dead policy — and dead policy drifts."""
        from custom_components.solar_energy_management.features import (
            device_registry as dr,
        )
        src = Path(dr.__file__).read_text()
        assert "adopt_if_running()" in src, "the adopters stopped being called"
        lines = src.splitlines()
        for i, line in enumerate(lines):
            if "adopt_if_running()" not in line:
                continue
            guard = lines[i - 1].strip()
            assert not guard.startswith("if "), (
                f"device_registry.py:{i} still gates the adopter itself "
                f"({guard!r}) — that check now lives in _adopt_ownership, and "
                "two copies of one policy is how the third copy gets forgotten"
            )

    def test_an_off_mode_load_is_adopted_at_registration_without_a_claim(self):
        """Now that the registry calls it unconditionally, the one-shot has to
        hold the same line the per-cycle twin does: the books see the load,
        SEM does not claim it."""
        d = _dev(mode=DeviceControlMode.OFF, state="on")
        assert d.adopt_if_running() is True
        assert d.is_active is True
        assert d._sem_owned is False

    def test_a_surplus_load_is_still_claimed_at_registration(self):
        d = _dev(mode=DeviceControlMode.SURPLUS, state="on")
        assert d.adopt_if_running() is True
        assert d._sem_owned is True
