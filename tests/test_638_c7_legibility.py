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
        SEMCoordinator._shadow_energy_plan(
            fake, _scheduler(), energy=MagicMock(), power=_power())
        plan = fake._energy_plan_shadow
        rows = plan.get("not_scheduled")
        assert rows, "the opted-out charger must appear structurally"
        assert {"id": "ev:ev_charger", "why": "mode"} in rows

    def test_a_disconnected_car_lands_with_its_why(self, freeze_targets):
        fake = _fake_self(devices=[_fake_load()])
        power = _power()
        power.ev_connected_per_charger = {"ev_charger": False}
        SEMCoordinator._shadow_energy_plan(
            fake, _scheduler(), energy=MagicMock(), power=power)
        rows = fake._energy_plan_shadow.get("not_scheduled")
        assert {"id": "ev:ev_charger", "why": "disconnected"} in rows

    def test_a_planned_night_has_an_empty_list_not_a_missing_key(
            self, freeze_targets):
        fake = _fake_self(devices=[_fake_load()])
        SEMCoordinator._shadow_energy_plan(
            fake, _scheduler(), energy=MagicMock(), power=_power())
        assert fake._energy_plan_shadow.get("not_scheduled") == []


@pytest.mark.unit
class TestCoverageReachesTheCard:
    def test_the_sensor_attrs_carry_the_coverage_map(self):
        from custom_components.solar_energy_management.sensor import (
            _energy_plan_attrs,
        )
        plan = {"computed_at": "2026-08-11T21:00:00+00:00",
                "coverage": {"ev:keba": "covered",
                             "load:heizband": "actuation off"}}
        attrs = _energy_plan_attrs(plan)
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


def _coord(**attrs):
    """A coordinator stand-in carrying the REAL evaluator.

    The view and the gate are two consumers of one rule, so a fake that
    stubs the evaluator would pin nothing. Bind the real method.
    """
    fake = SimpleNamespace(**attrs)
    fake._plan_gate_now = SEMCoordinator._plan_gate_now.__get__(
        fake, SEMCoordinator)
    return fake


def _live_plan(status="fits", demand_id="load:pump"):
    """A stamped plan whose span contains ``now`` — the shape the gate trusts."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    start = dt_util.now() - timedelta(minutes=30)
    end = start + timedelta(hours=8)
    return {"computed_at": start.isoformat(), "fits": True,
            "demands": [{"id": demand_id, "status": status}],
            "slots": [{"start": start.isoformat(), "end": end.isoformat()}],
            "blocks": [{"id": demand_id, "start": start.isoformat(),
                        "end": end.isoformat(), "power_w": 800.0}]}


@pytest.mark.unit
class TestCoverageViewIsUserShaped:
    """The view is EVALUATED, never remembered.

    ``_plan_coverage_seen`` is the transition log's memory: a demand is
    written there only when somebody ASKS its gate. Loads are asked from
    ``_energy_plan_load_windows``, which returns early when actuation is off
    or nothing is stamped — so replaying the memory as a live view showed
    yesterday's answer. Live on .175 15.08: with the kill-switch off the
    EV row correctly read ``actuation off`` while ``load:sim_pool_pump``
    still read ``covered`` — the one surface a user checks to see that the
    kill-switch took hold, contradicting the kill-switch.
    """

    def test_the_kill_switch_un_covers_every_remembered_row(self):
        fake = _coord(
            _plan_coverage_seen={"ev:keba": (True, ""), "load:pump": (True, "")},
            _energy_plan_actuation=False,
            _energy_plan_shadow=_live_plan())
        assert SEMCoordinator._plan_coverage_view(fake) == {
            "ev:keba": "actuation off", "load:pump": "actuation off"}

    def test_a_covered_demand_still_reads_covered(self):
        fake = _coord(
            _plan_coverage_seen={"load:pump": (False, "no plan")},
            _energy_plan_actuation=True,
            _energy_plan_shadow=_live_plan())
        assert SEMCoordinator._plan_coverage_view(fake) == {
            "load:pump": "covered"}

    def test_a_row_nobody_re_asked_shows_the_plans_current_verdict(self):
        """A re-stamp that degraded a demand must reach the card even when
        that demand's gate was not asked this cycle."""
        fake = _coord(
            _plan_coverage_seen={"load:pump": (True, "")},
            _energy_plan_actuation=True,
            _energy_plan_shadow=_live_plan(status="yields"))
        assert SEMCoordinator._plan_coverage_view(fake) == {
            "load:pump": "verdict yields"}

    def test_no_map_yet_is_an_empty_dict(self):
        view = SEMCoordinator._plan_coverage_view(_coord())
        assert view == {}

    def test_the_kill_switch_rule_has_exactly_one_evaluator(self):
        """Systematic pin: the view and the gate must not each own a copy
        of the rule — two copies is how they came to disagree."""
        import inspect
        src = inspect.getsource(SEMCoordinator)
        assert src.count('PlanGate(reason="actuation off")') == 1


@pytest.mark.unit
class TestActuationDefaultsOn:
    """(#638 C8) After the retirement, a solar_plus_cheap install with
    actuation off has NO cheap-window timing at all — default-off would be
    a silent feature regression. The switch stays as the kill-switch."""

    def test_the_coordinator_default_is_on(self):
        import inspect
        src = inspect.getsource(SEMCoordinator.__init__)
        assert 'config.get("energy_plan_actuation", True)' in src

    def test_the_switch_seed_default_is_on(self):
        # (#777) The seed moved from a literal ``options.get`` into the
        # explicit-config-beats-ghost precedence; the C8 default itself
        # is unchanged and now pinned structurally.
        from custom_components.solar_energy_management.switch import (
            SEMSolarSwitch,
        )
        assert SEMSolarSwitch._PERSISTED_DEFAULTS["energy_plan_actuation"] is True


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
        ok = SEMCoordinator._shadow_energy_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(), power=_power())
        assert ok is True
        plan = fake._energy_plan_shadow
        assert plan["demands"] == []
        assert plan["why_codes"] == [
            "ev_target_met", "no_load_needs_night", "battery_no_deficit"]
        # The headline code says the night needs nobody; the row says which
        # device that was and why (they answer different questions).
        assert plan["not_scheduled"] == [
            {"id": "load:pump", "why": "no_runtime_need"}]

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
        SEMCoordinator._shadow_energy_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(), power=power)
        plan = fake._energy_plan_shadow
        assert {"id": "ev:ev_charger", "why": "disconnected"} \
            in plan["not_scheduled"]
        # The EV code must NOT claim "target met" — the car is absent.
        assert "ev_target_met" not in plan["why_codes"]


def _load(did="pump", **over):
    """A load the collector WOULD plan, before the override under test."""
    dev = SimpleNamespace(
        device_id=did, name=did.title(), has_runtime_deficit=True,
        stop_condition_met=False, battery_eligible_overnight=True,
        top_up_policy="solar_only", daily_min_runtime_sec=4 * 3600,
        _daily_runtime_accumulated_sec=2 * 3600, rated_power=800.0, priority=4)
    for key, value in over.items():
        setattr(dev, key, value)
    return dev


@pytest.mark.unit
class TestEveryLeftOutLoadIsNamed:
    """(#638 C7) A device the collector skipped owes the user a why.

    The EV side has said why since C7 (``mode``/``disconnected``/
    ``car_full``); the load side skipped in five places and said nothing,
    so "why isn't my heater in tonight's plan?" had no answer anywhere on
    the card. Live on .175 15.08: four loads left out, ``not_scheduled``
    empty. Each ``continue`` in the collector now names itself.
    """

    def _rows(self, dev, freeze_targets):
        fake = _fake_self(devices=[dev])
        SEMCoordinator._shadow_energy_plan(
            fake, _scheduler(), energy=MagicMock(), power=_power())
        return fake._energy_plan_shadow.get("not_scheduled") or []

    def test_a_device_whose_mode_excludes_surplus_says_so(self, freeze_targets):
        from custom_components.solar_energy_management.devices.base import (
            DeviceControlMode,
        )
        rows = self._rows(_load(control_mode=DeviceControlMode.OFF),
                          freeze_targets)
        assert {"id": "load:pump", "why": "load_mode"} in rows

    def test_a_device_with_no_runtime_left_to_do_says_so(self, freeze_targets):
        rows = self._rows(_load(has_runtime_deficit=False), freeze_targets)
        assert {"id": "load:pump", "why": "no_runtime_need"} in rows

    def test_a_banked_room_says_it_is_already_at_target(self, freeze_targets):
        rows = self._rows(_load(stop_condition_met=True), freeze_targets)
        assert {"id": "load:pump", "why": "stop_condition"} in rows

    def test_a_daytime_only_device_says_it_does_not_do_nights(
            self, freeze_targets):
        rows = self._rows(_load(battery_eligible_overnight=False,
                                top_up_policy="solar_only"), freeze_targets)
        assert {"id": "load:pump", "why": "day_only"} in rows

    def test_a_device_with_no_measured_power_says_so(self, freeze_targets):
        rows = self._rows(_load(rated_power=0.0), freeze_targets)
        assert {"id": "load:pump", "why": "no_rated_power"} in rows

    def test_a_planned_load_is_not_in_the_left_out_list(self, freeze_targets):
        assert self._rows(_load(), freeze_targets) == []

    def test_the_quiet_night_names_its_left_out_loads_too(self, monkeypatch):
        """The 'nothing needs the night' payload is the one a user reads
        WHEN they wonder where their device went."""
        from custom_components.solar_energy_management.coordinator import (
            ev_night_targets,
        )
        monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                            lambda coord, energy: {"ev_charger": 0.0})
        fake = _fake_self(devices=[_load(has_runtime_deficit=False)])
        SEMCoordinator._shadow_energy_plan(
            fake, _scheduler(deficit=0.0), energy=MagicMock(), power=_power())
        plan = fake._energy_plan_shadow
        assert plan["demands"] == []
        assert {"id": "load:pump", "why": "no_runtime_need"} \
            in plan["not_scheduled"]

    def test_every_why_the_collector_emits_has_a_card_sentence(self):
        """Systematic pin, the twin of the gate-reason one below: a why
        with no translation renders as a blank chip in 16 languages."""
        import json
        import pathlib
        import re
        root = pathlib.Path(__file__).resolve().parent.parent
        src = (root / "coordinator" / "coordinator.py").read_text()
        codes = set(re.findall(r'"why": "([a-z_]+)"', src))
        codes |= set(re.findall(r'_left_out\([a-z_]+, "([a-z_]+)"\)', src))
        assert {"mode", "disconnected", "car_full"} <= codes, (
            "the EV whys moved — this pin is reading the wrong lines")
        assert {"load_mode", "no_runtime_need", "stop_condition", "day_only",
                "no_rated_power"} <= codes, (
            "the load whys moved — this pin is reading the wrong lines")
        card = (root / "dashboard" / "card" / "src" / "cards"
                / "sem-energy-plan-card.js").read_text()
        assert "'energy_plan_why_' + r.why" in card
        langs = json.loads(
            (root / "dashboard" / "translations.json").read_text())
        for code in sorted(codes):
            key = f"energy_plan_why_{code}"
            missing = [lg for lg, t in langs.items() if not t.get(key)]
            assert not missing, f"{key} missing in {missing}"


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
            .energy_plan_actuation import plan_gate
        gate = plan_gate(self._quiet(), "battery", self.NOW)
        # Still uncovered — an empty plan has no say over anything.
        assert gate.covered is False
        assert gate.reason == "nothing planned"

    def test_a_plan_that_lost_its_span_still_says_no_span(self):
        """The discriminator is the EMPTY shape, not the missing span: a
        plan that packed demands but has no readable slots is genuinely
        broken and must keep saying so."""
        from custom_components.solar_energy_management.coordinator \
            .energy_plan_actuation import plan_gate
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
        src = (root / "coordinator" / "energy_plan_actuation.py").read_text()
        reasons = set(re.findall(r'PlanGate\(reason=[\'"]([^\'"{]+)[\'"]', src))
        reasons.add("actuation off")  # the coordinator's own kill-switch reason
        assert "nothing planned" in reasons

        card = (root / "dashboard" / "card" / "src" / "cards"
                / "sem-energy-plan-card.js").read_text()
        block = card.split("_covKey(reason)", 1)[1].split("}", 1)[0]
        mapped = dict(re.findall(r"'([^']+)':\s*'(energy_plan_cov_[a-z_]+)'",
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
