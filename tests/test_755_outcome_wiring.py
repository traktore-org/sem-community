"""#755 pillar 1 — wiring the outcome recorder into the cycle.

The recorder itself is pure (``test_755_demand_outcome.py``). This file pins
the two things the wiring must get right, both of which are honesty questions
rather than plumbing questions:

**Where does a demand's draw come from, and is it a measurement?** Every
source SEM has is a different answer. A device with a power sensor is measured.
A device with nothing to read is not — and SEM knows its rated power, which is
exactly the tempting number to record as if it were real. One charger's own
sensor is measured; the FLEET sum standing in for one of several chargers is
not (`ev_control._this_charger_power` documents that fallback as over-counting
— it is the #315 bug class, and recording it as truth would teach it to a
model).

**When does a night open and close?** On the stamp and on the plan's clearing,
once each — not once per cycle, and never blending two nights into one record.
"""

from datetime import date, datetime, timezone
from types import MethodType, SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.demand_outcome import (
    DemandOutcomeRecorder,
    battery_draw,
    device_draw,
    ev_draw,
)
from custom_components.solar_energy_management.coordinator.overnight_actuation import (
    PlanGate,
)


UTC = timezone.utc


def _at(h, m=0, day=12):
    return datetime(2026, 8, day, h, m, tzinfo=UTC)


def _rec_for(rec, demand_id):
    """One open record, through the recorder's public door (see #653 note in
    ``test_755_demand_outcome``)."""
    return next((r for r in rec.open_records()
                 if r.demand_id == demand_id), None)


class TestDrawHonesty:
    """Every draw carries whether it was measured. Nothing else in the build
    is allowed to decide that question later."""

    def test_a_device_with_a_power_sensor_is_measured(self):
        dev = SimpleNamespace(observed_power_w=lambda: 1450.0,
                              rated_power=2000.0, is_active=True)
        assert device_draw(dev) == (1450.0, True)

    def test_a_device_with_nothing_to_read_is_an_estimate(self):
        """SEM knows the rated power. That is not the same as knowing the
        draw — and rated_power is itself a learned ratchet (#744)."""
        dev = SimpleNamespace(observed_power_w=lambda: None,
                              rated_power=2000.0, is_active=True)
        watts, measured = device_draw(dev)
        assert watts == 2000.0      # still shown to the user...
        assert measured is False    # ...but never taught to a model

    def test_an_unobservable_idle_device_is_still_not_a_measurement(self):
        """'SEM commanded it off' is a command, not a reading. One rule: no
        power source, no measurement — no special case for the easy half."""
        dev = SimpleNamespace(observed_power_w=lambda: None,
                              rated_power=2000.0, is_active=False)
        assert device_draw(dev) == (0.0, False)

    def test_a_charger_with_its_own_sensor_is_measured(self):
        power = SimpleNamespace(ev_power=9000.0,
                                ev_power_per_charger={"keba": 4800.0,
                                                      "wallbox": 4200.0})
        assert ev_draw("keba", power, charger_count=2) == (4800.0, True)

    def test_the_only_charger_owns_the_fleet_reading(self):
        power = SimpleNamespace(ev_power=4800.0, ev_power_per_charger={})
        assert ev_draw("keba", power, charger_count=1) == (4800.0, True)

    def test_the_fleet_sum_standing_in_for_one_of_several_is_not(self):
        """The #315 fallback: over-counts by every other charger's draw."""
        power = SimpleNamespace(ev_power=9000.0, ev_power_per_charger={})
        watts, measured = ev_draw("keba", power, charger_count=2)
        assert watts == 9000.0
        assert measured is False

    def test_a_legacy_top_level_sensor_still_counts_as_this_chargers_own(self):
        """Configs predating the per-charger map put the sensor on the
        charger itself; the canonical accessor reads it, so it is measured."""
        power = SimpleNamespace(ev_power=9000.0, ev_power_per_charger={})
        assert ev_draw("keba", power, charger_count=2,
                       charger_w=4800.0, has_own_sensor=True) == (4800.0, True)

    def test_battery_charge_power_is_measured(self):
        power = SimpleNamespace(battery_charge_power=3300.0)
        assert battery_draw(power) == (3300.0, True)


def _plan(demands=None):
    return {
        "computed_at": "2026-08-12T21:00:00+00:00",
        "demands": demands if demands is not None else [
            {"id": "ev:keba", "kind": "ev", "needed_kwh": 10.0,
             "planned_kwh": 10.0, "status": "fits"},
            {"id": "load:heizband", "kind": "load", "needed_kwh": 2.0,
             "planned_kwh": 1.6, "status": "partial"},
        ],
    }


def _self(plan=None, devices=(), gate=None, night=date(2026, 8, 12)):
    """A fake coordinator.

    The night key is ``_shadow_plan_date`` — the stamped energy day —
    deliberately NOT the plan's ``computed_at``: a re-stamp (the ask changed)
    is the SAME night and must keep the record it has accumulated.
    """
    rec = DemandOutcomeRecorder(max_gap_s=3600)
    gate = gate if gate is not None else PlanGate(covered=True, in_block=True,
                                                  block_power_w=4000.0)
    me = SimpleNamespace(
        _overnight_shadow_plan=plan,
        _shadow_plan_date=night if plan is not None else None,
        _demand_outcomes=rec,
        _overnight_plan_gate=lambda did, now=None: gate,
        _surplus_controller=SimpleNamespace(
            get_devices_sorted=lambda: list(devices)),
        _ev_devices={"keba": SimpleNamespace(power_entity_id=None)},
        _charger_power_w=lambda cid, power, dev=None: 0.0,
        _storage=None,
    )
    # The seal/persist collaborators are the REAL methods, bound — stubbing
    # them would leave the night-sealing path untested by the tests that
    # exist to test it.
    for name in ("_seal_demand_outcomes", "_persist_demand_outcomes",
                 "_refresh_demand_review"):
        setattr(me, name, MethodType(getattr(SEMCoordinator, name), me))
    return me


def _heizband(watts=1000.0):
    return SimpleNamespace(device_id="heizband",
                           observed_power_w=lambda: watts,
                           rated_power=1200.0, is_active=True)


def _power(ev_w=4000.0):
    return SimpleNamespace(ev_power=ev_w, ev_power_per_charger={},
                           battery_charge_power=0.0)


class TestNightLifecycle:
    def test_the_stamp_opens_the_night_from_the_plan_rows(self):
        me = _self(plan=_plan(), devices=[_heizband()])
        SEMCoordinator._record_demand_outcomes(me, _at(22, 0), _power())
        ids = sorted(r.demand_id for r in me._demand_outcomes.open_records())
        assert ids == ["ev:keba", "load:heizband"]
        ev = _rec_for(me._demand_outcomes, "ev:keba")
        assert (ev.asked_kwh, ev.planned_kwh, ev.status) == (10.0, 10.0, "fits")

    def test_a_second_cycle_does_not_reopen_the_night(self):
        me = _self(plan=_plan(), devices=[_heizband()])
        SEMCoordinator._record_demand_outcomes(me, _at(22, 0), _power())
        SEMCoordinator._record_demand_outcomes(me, _at(22, 30), _power())
        assert me._demand_outcomes.history() == []
        # ...and the second cycle's interval was integrated: 4 kW x 30 min
        assert _rec_for(me._demand_outcomes, "ev:keba").actual_kwh == \
            pytest.approx(2.0, abs=0.01)

    def test_every_demand_is_observed_each_cycle(self):
        me = _self(plan=_plan(), devices=[_heizband(1000.0)])
        SEMCoordinator._record_demand_outcomes(me, _at(22, 0), _power())
        SEMCoordinator._record_demand_outcomes(me, _at(23, 0), _power())
        heiz = _rec_for(me._demand_outcomes, "load:heizband")
        assert heiz.actual_kwh == pytest.approx(1.0, abs=0.01)
        assert heiz.measured is True

    def test_authority_and_block_are_two_independent_axes(self):
        """``covered`` answers "was the plan in charge at all"; ``in_block``
        answers "did it say run NOW". A demand drawing under an authoritative
        plan but OUTSIDE its window is the interesting case — energy the plan
        did not direct, on a night the plan owned."""
        me = _self(plan=_plan(), devices=[_heizband()],
                   gate=PlanGate(covered=True, in_block=False))
        SEMCoordinator._record_demand_outcomes(me, _at(22, 0), _power())
        SEMCoordinator._record_demand_outcomes(me, _at(23, 0), _power())
        ev = _rec_for(me._demand_outcomes, "ev:keba")
        assert ev.actual_kwh == pytest.approx(4.0, abs=0.01)
        assert ev.in_block_kwh == pytest.approx(0.0, abs=0.01)
        assert ev.covered_s == pytest.approx(3600, abs=1)

    def test_an_uncovered_night_is_recorded_as_the_reactive_layers(self):
        me = _self(plan=_plan(), devices=[_heizband()],
                   gate=PlanGate(covered=False, reason="no plan"))
        SEMCoordinator._record_demand_outcomes(me, _at(22, 0), _power())
        SEMCoordinator._record_demand_outcomes(me, _at(23, 0), _power())
        ev = _rec_for(me._demand_outcomes, "ev:keba")
        assert ev.uncovered_s == pytest.approx(3600, abs=1)
        assert ev.covered_s == 0.0

    def test_the_plan_clearing_seals_the_night(self):
        """Night end clears the stamp — that is when the record becomes
        history, not something a later night may still append to."""
        me = _self(plan=_plan(), devices=[_heizband()])
        SEMCoordinator._record_demand_outcomes(me, _at(22, 0), _power())
        SEMCoordinator._record_demand_outcomes(me, _at(23, 0), _power())
        me._overnight_shadow_plan = None
        me._shadow_plan_date = None
        SEMCoordinator._record_demand_outcomes(me, _at(7, 0, day=13), _power())
        ids = sorted(r.demand_id for r in me._demand_outcomes.history())
        assert ids == ["ev:keba", "load:heizband"]
        assert me._demand_outcomes.open_records() == []

    def test_a_new_night_never_blends_into_the_old_record(self):
        me = _self(plan=_plan(), devices=[_heizband()])
        SEMCoordinator._record_demand_outcomes(me, _at(22, 0), _power())
        SEMCoordinator._record_demand_outcomes(me, _at(23, 0), _power())
        me._overnight_shadow_plan = _plan()
        me._shadow_plan_date = date(2026, 8, 13)
        SEMCoordinator._record_demand_outcomes(me, _at(22, 0, day=13), _power())
        assert len(me._demand_outcomes.history()) == 2      # last night sealed
        assert _rec_for(me._demand_outcomes, "ev:keba").actual_kwh == 0.0

    def test_no_plan_at_all_records_nothing_and_does_not_raise(self):
        me = _self(plan=None, devices=[_heizband()], night=None)
        SEMCoordinator._record_demand_outcomes(me, _at(22, 0), _power())
        assert me._demand_outcomes.open_records() == []
        assert me._demand_outcomes.history() == []


class TestTheRecorderRunsInTheCycle:
    """A recorder nothing calls records nothing. Both ends are structural
    pins: the record is taken AFTER the decisions (so it measures what was
    actually done, not what was about to be), and it is re-seated at boot
    beside the plan it measures."""

    def test_the_record_is_taken_after_the_decisions(self):
        import inspect
        src = inspect.getsource(SEMCoordinator._async_update_data)
        assert "_record_demand_outcomes(" in src, (
            "the cycle must feed the outcome recorder — otherwise the plan's "
            "third number is still never written down")
        assert src.index("core_result = result") < \
            src.index("_record_demand_outcomes("), (
            "record AFTER the decisions: sampling before them measures the "
            "previous cycle's actuation against this cycle's plan")

    def test_the_record_is_restored_at_boot(self):
        import inspect
        src = inspect.getsource(SEMCoordinator._async_update_data)
        assert "_restore_demand_outcomes(" in src, (
            "a reboot mid-night that keeps the plan but loses the actuals "
            "produces a night whose 'took N kWh' starts at the reboot")


class TestUnobservableDemandsSurvive:
    def test_a_sensorless_device_is_recorded_but_not_trainable(self):
        dev = SimpleNamespace(device_id="heizband",
                              observed_power_w=lambda: None,
                              rated_power=1200.0, is_active=True)
        me = _self(plan=_plan(), devices=[dev])
        SEMCoordinator._record_demand_outcomes(me, _at(22, 0), _power())
        SEMCoordinator._record_demand_outcomes(me, _at(23, 0), _power())
        heiz = _rec_for(me._demand_outcomes, "load:heizband")
        assert heiz.actual_kwh == pytest.approx(1.2, abs=0.01)
        assert heiz.trainable is False

    def test_a_demand_whose_device_vanished_is_marked_unmeasured(self):
        """The device list can lose a device mid-night (reload, removal).
        Recording 0 kWh as fact would teach 'it never ran'."""
        me = _self(plan=_plan(), devices=[])
        SEMCoordinator._record_demand_outcomes(me, _at(22, 0), _power())
        SEMCoordinator._record_demand_outcomes(me, _at(23, 0), _power())
        heiz = _rec_for(me._demand_outcomes, "load:heizband")
        assert heiz.measured is False


class TestPersistence:
    def test_the_nights_record_round_trips_through_the_durable_store(self):
        saved = {}
        me = _self(plan=_plan(), devices=[_heizband()])
        me._storage = SimpleNamespace(
            set_demand_outcome_state=lambda s: saved.update(s),
            get_demand_outcome_state=lambda: saved,
        )
        SEMCoordinator._record_demand_outcomes(me, _at(22, 0), _power())
        SEMCoordinator._record_demand_outcomes(me, _at(23, 0), _power())
        assert saved, "the night's record must reach the durable store"

        revived = _self(plan=_plan(), devices=[_heizband()])
        SEMCoordinator._restore_demand_outcomes(revived, saved)
        assert _rec_for(revived._demand_outcomes, "ev:keba").actual_kwh == \
            pytest.approx(4.0, abs=0.01)
