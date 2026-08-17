"""#764 — observer mode publishes its WOULD decisions as a standard surface.

The observer seam logged "OBSERVER · WOULD ACTIVATE X" — human-readable,
grep-only, and on a host with a small log ring, gone in minutes. Building a
simulation against it meant scraping logs over SSH (the N2 sim-actuator
bridge, 13.08). Guido's call: make it standard, so anyone can simulate.

Two surfaces, one source of truth:
- ``SurplusController.observer_decisions`` — the per-device map of the
  CURRENT would-state, published so a fresh session reads it instantly
  (rides the observer-mode switch's attributes).
- A ``solar_energy_management_observer_decision`` bus event fired on every
  TRANSITION (the same edges the #762-gated log announces) — a user's sim
  bridge becomes a five-line HA automation instead of an SSH scraper.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController, _reconcile_load_observe, LoadIntent,
)
from custom_components.solar_energy_management.utils.log_gate import (
    reset_log_gate,
)


@pytest.fixture(autouse=True)
def _gate():
    reset_log_gate()
    yield
    reset_log_gate()


def _dev(did="sim_heizband", name="Sim Heizband", active=False):
    d = MagicMock()
    d.device_id = did
    d.name = name
    d.is_active = active
    d.get_current_consumption = MagicMock(return_value=800.0 if active else 0.0)
    return d


def _sc():
    sc = SurplusController(MagicMock())
    sc.hass.bus.async_fire = MagicMock()
    return sc


class TestTheDecisionMap:

    def test_a_would_activate_lands_in_the_map(self):
        sc = _sc()
        d = _dev()
        intent = LoadIntent(True, 1000.0, "tier2_battery", "overnight battery — runtime deficit")
        sc.record_observer_decision(d, intent, active=False)
        m = sc.observer_decisions["sim_heizband"]
        assert m["action"] == "activate"
        assert m["power_w"] == 1000.0
        assert m["source"] == "tier2_battery"
        assert "deficit" in m["reason"]

    def test_a_would_deactivate_lands(self):
        sc = _sc()
        d = _dev(active=True)
        intent = LoadIntent(False, 0.0, None, "daily max cap reached")
        sc.record_observer_decision(d, intent, active=True)
        assert sc.observer_decisions["sim_heizband"]["action"] == "deactivate"

    def test_converged_state_reads_hold(self):
        """No command would be sent — the map still answers, so a fresh
        reader knows the device is where SEM wants it."""
        sc = _sc()
        d = _dev(active=False)
        intent = LoadIntent(False, 0.0, None, "no source available")
        sc.record_observer_decision(d, intent, active=False)
        assert sc.observer_decisions["sim_heizband"]["action"] == "hold"


class TestTheEventFiresOnEdges:

    def test_first_decision_fires(self):
        sc = _sc()
        d = _dev()
        intent = LoadIntent(True, 1000.0, "solar", "solar: 6532W ≥ 1000W")
        sc.record_observer_decision(d, intent, active=False)
        sc.hass.bus.async_fire.assert_called_once()
        event, payload = sc.hass.bus.async_fire.call_args.args[:2]
        assert event == "solar_energy_management_observer_decision"
        assert payload["device_id"] == "sim_heizband"
        assert payload["action"] == "activate"

    def test_an_unchanged_decision_is_one_event_not_a_heartbeat(self):
        sc = _sc()
        d = _dev()
        intent = LoadIntent(True, 1000.0, "solar", "solar: 6532W ≥ 1000W")
        for _ in range(20):
            sc.record_observer_decision(d, intent, active=False)
        assert sc.hass.bus.async_fire.call_count == 1

    def test_a_transition_fires_again(self):
        sc = _sc()
        d = _dev()
        sc.record_observer_decision(
            d, LoadIntent(True, 1000.0, "solar", "run"), active=False)
        d.is_active = True
        sc.record_observer_decision(
            d, LoadIntent(False, 0.0, None, "stop"), active=True)
        assert sc.hass.bus.async_fire.call_count == 2

    def test_a_wobbling_power_is_not_an_edge(self):
        """Same dedup rule as the #762 log gate: the decision is the
        signal, a wobbling watt number is not."""
        sc = _sc()
        d = _dev(active=True)
        for w in (1000.0, 1004.0, 998.0):
            sc.record_observer_decision(
                d, LoadIntent(True, w, "solar", f"solar: {w:.0f}W"), active=True)
        assert sc.hass.bus.async_fire.call_count == 1


class TestTheSeamRecords:

    def test_reconcile_load_observe_feeds_the_map(self):
        """The seam function itself records — the surface can never drift
        from what the observer log says."""
        sc = _sc()
        d = _dev()
        intent = LoadIntent(True, 1000.0, "solar", "run")
        _reconcile_load_observe(d, intent, False, controller=sc)
        assert sc.observer_decisions["sim_heizband"]["action"] == "activate"

    def test_the_seam_still_works_without_a_controller(self):
        """Bare callers (tests, older paths) keep the pure behavior."""
        d = _dev(active=True)
        out = _reconcile_load_observe(
            d, LoadIntent(True, 800.0, "solar", "run"), True)
        assert out == 800.0


class TestTheSwitchCarriesTheMap:

    def _switch(self, observer_on=True, decisions=None):
        from custom_components.solar_energy_management.switch import SEMSolarSwitch
        coord = MagicMock()
        coord.config_entry.options = {}
        coord._surplus_controller.observer_decisions = decisions or {}
        desc = MagicMock()
        desc.key = "observer_mode"
        sw = SEMSolarSwitch.__new__(SEMSolarSwitch)
        sw.coordinator = coord
        sw.entity_description = desc
        sw._is_on = observer_on
        return sw

    def test_observer_on_publishes_the_map(self):
        m = {"sim_heizband": {"action": "activate", "power_w": 1000.0}}
        sw = self._switch(True, m)
        assert sw.extra_state_attributes == {"would_decisions": m}

    def test_observer_off_publishes_empty_not_stale(self):
        sw = self._switch(False, {"sim_heizband": {"action": "activate"}})
        assert sw.extra_state_attributes == {"would_decisions": {}}

    def test_other_switches_carry_nothing(self):
        sw = self._switch(True, {"x": {}})
        sw.entity_description.key = "vacation_mode"
        assert sw.extra_state_attributes is None
