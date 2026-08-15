"""#638 one-gate C7 — the user reads what will be done, when, and why not.

The one gate concentrates every decision, so it must concentrate the
explanation. Two structured surfaces feed the card (prose in ``summary``
is for logs, not for rendering):

* ``not_scheduled`` on the plan payload — every device the collector
  deliberately left out, with a machine why (``mode`` / ``disconnected``)
  the card translates per user language. "The plan has no EV line" must
  read differently for an opted-out mode vs an absent car.
* ``energy_plan_coverage`` on the coordinator data — the per-demand
  verdict transitions (the user-facing twin of the ``#638 coverage`` log
  line): ``covered`` or the gate's named doubt, so a demand running
  reactively is visible on the card, never silent.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)

from .test_638_shadow_mode import (  # noqa: F401 — fixtures by name
    _fake_load,
    _fake_self,
    _power,
    _scheduler,
    freeze_targets,
)


@pytest.mark.unit
class TestNotScheduledIsStructured:
    def test_a_mode_opt_out_lands_with_its_why(self, freeze_targets):
        fake = _fake_self(devices=[_fake_load()])
        fake._mode_allows_night_charging = lambda cfg: False
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(), energy=MagicMock(), power=_power())
        plan = fake._overnight_shadow_plan
        rows = plan.get("not_scheduled")
        assert rows, "the opted-out charger must appear structurally"
        assert {"id": "ev:ev_charger", "why": "mode"} in rows

    def test_a_disconnected_car_lands_with_its_why(self, freeze_targets):
        fake = _fake_self(devices=[_fake_load()])
        power = _power()
        power.ev_connected_per_charger = {"ev_charger": False}
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(), energy=MagicMock(), power=power)
        rows = fake._overnight_shadow_plan.get("not_scheduled")
        assert {"id": "ev:ev_charger", "why": "disconnected"} in rows

    def test_a_planned_night_has_an_empty_list_not_a_missing_key(
            self, freeze_targets):
        fake = _fake_self(devices=[_fake_load()])
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(), energy=MagicMock(), power=_power())
        assert fake._overnight_shadow_plan.get("not_scheduled") == []


@pytest.mark.unit
class TestCoverageReachesTheCard:
    def test_the_sensor_attrs_carry_the_coverage_map(self):
        from custom_components.solar_energy_management.sensor import (
            _overnight_plan_attrs,
        )
        plan = {"computed_at": "2026-08-11T21:00:00+00:00",
                "coverage": {"ev:keba": "covered",
                             "load:heizband": "actuation off"}}
        attrs = _overnight_plan_attrs(plan)
        assert attrs["coverage"] == {"ev:keba": "covered",
                                     "load:heizband": "actuation off"}

    def test_the_coordinator_publishes_the_seen_map(self):
        """The energy_plan payload rides with the live coverage map —
        flipping to reactive mid-night must change the card next cycle."""
        import inspect
        src = inspect.getsource(SEMCoordinator._async_update_data) \
            if hasattr(SEMCoordinator, "_async_update_data") else ""
        # The publish site stitches coverage in beside `actuation` — pin
        # at the source level (the exact publish path is exercised live).
        allsrc = inspect.getsource(SEMCoordinator)
        assert "_plan_coverage_view" in allsrc


@pytest.mark.unit
class TestCoverageViewIsUserShaped:
    def test_covered_and_reasons_map_cleanly(self):
        fake = SimpleNamespace(_plan_coverage_seen={
            "ev:keba": (True, ""),
            "load:heizband": (False, "actuation off"),
            "battery": (False, "verdict yields"),
        })
        view = SEMCoordinator._plan_coverage_view(fake)
        assert view == {
            "ev:keba": "covered",
            "load:heizband": "actuation off",
            "battery": "verdict yields",
        }

    def test_no_map_yet_is_an_empty_dict(self):
        view = SEMCoordinator._plan_coverage_view(SimpleNamespace())
        assert view == {}


@pytest.mark.unit
class TestActuationDefaultsOn:
    """(#638 C8) After the retirement, a solar_plus_cheap install with
    actuation off has NO cheap-window timing at all — default-off would be
    a silent feature regression. The switch stays as the kill-switch."""

    def test_the_coordinator_default_is_on(self):
        import inspect
        src = inspect.getsource(SEMCoordinator.__init__)
        assert 'config.get("overnight_actuation", True)' in src

    def test_the_switch_seed_default_is_on(self):
        # (#777) The seed moved from a literal ``options.get`` into the
        # explicit-config-beats-ghost precedence; the C8 default itself
        # is unchanged and now pinned structurally.
        from custom_components.solar_energy_management.switch import (
            SEMSolarSwitch,
        )
        assert SEMSolarSwitch._PERSISTED_DEFAULTS["overnight_actuation"] is True


@pytest.mark.unit
class TestTheQuietFaceSpeaksInSentences:
    """(Guido, first live look at the card) The raw diagnostic line
    (`ev_targets={...}, mode_opted_out=[]...`) looked unfinished on the
    rendered face. The idle payload now carries machine CODES the card
    translates; the prose stays for logs/diagnose only."""

    def test_the_idle_payload_carries_why_codes(self, monkeypatch):
        from custom_components.solar_energy_management.coordinator import (
            ev_night_targets,
        )
        monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                            lambda coord, energy: {"ev_charger": 0.0})
        from .test_638_shadow_mode import _idle_load
        fake = _fake_self(devices=[_idle_load()])
        ok = SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(), power=_power())
        assert ok is True
        plan = fake._overnight_shadow_plan
        assert plan["demands"] == []
        assert plan["why_codes"] == [
            "ev_target_met", "no_load_needs_night", "battery_no_deficit"]
        assert plan["not_scheduled"] == []

    def test_an_idle_night_with_an_unplugged_car_names_it(self, monkeypatch):
        from custom_components.solar_energy_management.coordinator import (
            ev_night_targets,
        )
        monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                            lambda coord, energy: {"ev_charger": 4.0})
        from .test_638_shadow_mode import _idle_load
        fake = _fake_self(devices=[_idle_load()])
        power = _power()
        power.ev_connected_per_charger = {"ev_charger": False}
        SEMCoordinator._shadow_overnight_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(), power=power)
        plan = fake._overnight_shadow_plan
        assert {"id": "ev:ev_charger", "why": "disconnected"} \
            in plan["not_scheduled"]
        # The EV code must NOT claim "target met" — the car is absent.
        assert "ev_target_met" not in plan["why_codes"]


# The reasons for which "the plan is unreadable" IS the honest sentence:
# the plan really did break trust and the user can do nothing but wait for
# the next stamp. Every OTHER reason owes the user a specific sentence.
_UNREADABLE_IS_HONEST = {"malformed block", "unreadable plan", "no span"}


@pytest.mark.unit
class TestTheQuietPlanIsNotUnreadable:
    """A night with nothing to schedule is a READABLE answer.

    The quiet 22:00 plan publishes ``demands``/``slots``/``blocks`` as empty
    lists on purpose ("nothing needs the night"). Gating that shape on the
    slot span made every demand answer ``no span``, and the card has no
    sentence for that reason — so it fell through to *"the plan is
    unreadable"* on a night when the plan was perfectly readable and simply
    had nothing to do. Live on PROD 15.08 12:10:51: battery + 10 loads +
    comfort, every coverage value ``no span``.
    """

    NOW = datetime(2026, 8, 15, 23, 30, tzinfo=timezone.utc)

    def _quiet(self):
        return {"computed_at": "2026-08-15T22:00:00+00:00", "fits": True,
                "demands": [], "slots": [], "blocks": [],
                "why_codes": ["battery_no_deficit"]}

    def test_the_quiet_plan_names_itself(self):
        from custom_components.solar_energy_management.coordinator \
            .overnight_actuation import plan_gate
        gate = plan_gate(self._quiet(), "battery", self.NOW)
        # Still uncovered — an empty plan has no say over anything.
        assert gate.covered is False
        assert gate.reason == "nothing planned"

    def test_a_plan_that_lost_its_span_still_says_no_span(self):
        """The discriminator is the EMPTY shape, not the missing span: a
        plan that packed demands but has no readable slots is genuinely
        broken and must keep saying so."""
        from custom_components.solar_energy_management.coordinator \
            .overnight_actuation import plan_gate
        broken = self._quiet()
        broken["demands"] = [{"id": "battery", "status": "fits"}]
        gate = plan_gate(broken, "battery", self.NOW)
        assert gate.reason == "no span"

    def test_every_gate_reason_has_a_card_sentence(self):
        """Systematic pin: a reason the gate can emit that the card cannot
        translate renders as "unreadable" — the bug class, not one bug.
        Adding a reason now forces either a card key or an explicit entry
        in the honest-unreadable set."""
        import json
        import pathlib
        import re
        root = pathlib.Path(__file__).resolve().parent.parent
        src = (root / "coordinator" / "overnight_actuation.py").read_text()
        reasons = set(re.findall(r'PlanGate\(reason=[\'"]([^\'"{]+)[\'"]', src))
        reasons.add("actuation off")  # the coordinator's own kill-switch reason
        assert "nothing planned" in reasons

        card = (root / "dashboard" / "card" / "src" / "cards"
                / "sem-energy-plan-card.js").read_text()
        block = card.split("_covKey(reason)", 1)[1].split("}", 1)[0]
        mapped = dict(re.findall(r"'([^']+)':\s*'(overnight_cov_[a-z_]+)'",
                                 block))

        unmapped = {r for r in reasons
                    if r not in mapped and r not in _UNREADABLE_IS_HONEST}
        assert not unmapped, (
            f"gate reasons with no card sentence: {sorted(unmapped)} — "
            "either map them in _covKey or declare them honestly unreadable")

        langs = json.loads(
            (root / "dashboard" / "translations.json").read_text())
        for reason, key in mapped.items():
            missing = [lg for lg, t in langs.items() if not t.get(key)]
            assert not missing, f"{key} ({reason}) missing in {missing}"
