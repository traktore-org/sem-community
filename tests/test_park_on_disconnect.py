"""park-on-disconnect — a car that leaves must leave the box OFF.

Guido, PROD 26.08: he set the EV target to 0, yet the car "started charging
as soon as I plugged in." The recorder proved SEM sent the box NOTHING for
the four hours between the previous session ending and the plug-in — it was
left ENABLED, and an enabled KEBA (auth off at the DIP level) auto-starts any
plug-in on its own. SEM then bounded it at the 1 kWh quota-hold floor, but the
kWh was never the point: the box should never have been hot.

His pre-SEM automation disabled the KEBA after every charge, which is exactly
why a plug-in never auto-started for him — a disabled box holds across a
plug-in on this hardware. SEM regressed by treating "not drawing" as "off":
the reconciler's IDLE/OFF path issues nothing once the contactor is quiet
(the #552 spam fix), so a finished/disconnected car left the box enabled.

The fix: one PARK_OFF on the settled disconnect edge → a clean disable + the
dead-man's-off failsafe, the box held cold until SEM next starts a charge.
"""
from __future__ import annotations

from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    PARK_ON_DISCONNECT_CYCLES,
    ActionKind,
    ChargerReconciler,
    DesiredState,
    ObservedState,
)


def _rec() -> ChargerReconciler:
    return ChargerReconciler(charger_id="ev_charger", heartbeat_s=5.0,
                             idle_disable_threshold=4)


def _obs(*, connected=True, charging=False, power=0.0,
         self_charging=False) -> ObservedState:
    return ObservedState(charging=charging, setpoint_a=0,
                         self_charging=self_charging, power_w=power,
                         connected=connected)


def _kinds(actions):
    return [a.kind for a in actions]


def _run(rec, obs, *, desired=DesiredState.IDLE, start=0.0, n=1, step=10.0):
    out = []
    for i in range(n):
        out.append(rec.reconcile(desired, 0, obs, now=start + i * step))
    return out


class TestItParksTheBoxWhenTheCarLeaves:
    def test_a_settled_disconnect_emits_park_off_once(self):
        rec = _rec()
        _run(rec, _obs(connected=True), n=1)                    # car present
        rounds = _run(rec, _obs(connected=False), n=4, start=10.0)
        kinds = [_kinds(r) for r in rounds]
        # debounced: nothing on the first disconnected cycle, PARK_OFF on the
        # second, then silence
        assert ActionKind.PARK_OFF not in kinds[0]
        assert kinds[PARK_ON_DISCONNECT_CYCLES - 1] == [ActionKind.PARK_OFF]
        for later in kinds[PARK_ON_DISCONNECT_CYCLES:]:
            assert ActionKind.PARK_OFF not in later
            assert later == [ActionKind.NONE]

    def test_it_parks_exactly_once_across_a_long_absence(self):
        rec = _rec()
        _run(rec, _obs(connected=True), n=1)
        rounds = _run(rec, _obs(connected=False), n=200, start=10.0)
        parks = sum(ActionKind.PARK_OFF in _kinds(r) for r in rounds)
        assert parks == 1

    def test_a_one_cycle_unplug_blip_never_parks(self):
        """project_ev_flap_udp_blip: a single-cycle disconnect is a UDP blip,
        not a real unplug — parking on it would kill a live charge."""
        rec = _rec()
        _run(rec, _obs(connected=True, charging=True, power=10000.0), n=1)
        blip = rec.reconcile(DesiredState.CHARGE, 16,
                             _obs(connected=False, charging=True, power=10000.0),
                             now=10.0)
        assert ActionKind.PARK_OFF not in _kinds(blip)
        back = rec.reconcile(DesiredState.CHARGE, 16,
                            _obs(connected=True, charging=True, power=10000.0),
                            now=20.0)
        assert ActionKind.PARK_OFF not in _kinds(back)

    def test_reconnect_rearms_the_park_for_the_next_departure(self):
        rec = _rec()
        _run(rec, _obs(connected=True), n=1)
        first = _run(rec, _obs(connected=False), n=2, start=10.0)
        assert ActionKind.PARK_OFF in _kinds(first[-1])
        _run(rec, _obs(connected=True), n=1, start=40.0)       # car back
        second = _run(rec, _obs(connected=False), n=2, start=50.0)
        assert ActionKind.PARK_OFF in _kinds(second[-1])       # parks again


class TestItDoesNotParkWhenItShouldCharge:
    def test_a_connected_drawing_car_is_never_parked(self):
        rec = _rec()
        rounds = _run(rec, _obs(connected=True, charging=True, power=10000.0),
                      desired=DesiredState.CHARGE, n=5)
        for r in rounds:
            assert ActionKind.PARK_OFF not in _kinds(r)

    def test_a_connected_idle_car_stops_the_normal_way_not_park(self):
        """Min=0 with the car STILL PLUGGED and drawing is the quota-hold's
        job (bound the draw, avoid the disable war) — PARK_OFF is only for a
        car that has physically left."""
        rec = _rec()
        rounds = _run(rec, _obs(connected=True, charging=True, power=3300.0),
                      desired=DesiredState.IDLE, n=5)
        for r in rounds:
            assert ActionKind.PARK_OFF not in _kinds(r)


class TestTheTonightScenario:
    def test_finish_then_unplug_leaves_the_box_parked_before_the_replug(self):
        """The exact PROD sequence: charge → car full → unplug. The box must
        be PARK_OFF before the next plug-in, so it lands cold."""
        rec = _rec()
        # charging
        rec.reconcile(DesiredState.CHARGE, 16,
                      _obs(connected=True, charging=True, power=10000.0), now=0.0)
        # car full — connected, not drawing, decision idle
        for i in range(3):
            a = rec.reconcile(DesiredState.IDLE, 0,
                              _obs(connected=True, charging=False), now=10.0 + i * 10)
            assert ActionKind.PARK_OFF not in _kinds(a)   # still plugged, not parked
        # unplug — the settled edge parks the box
        rec.reconcile(DesiredState.IDLE, 0, _obs(connected=False), now=100.0)
        parked = rec.reconcile(DesiredState.IDLE, 0, _obs(connected=False), now=110.0)
        assert _kinds(parked) == [ActionKind.PARK_OFF]


class TestTheApplyPathCallsTheCleanDisable:
    def test_park_off_action_calls_command_park_off_not_command_disable(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import (
            charger_reconciler as cr,
        )
        src = inspect.getsource(cr.ChargerReconciler._apply_actions)
        assert "ActionKind.PARK_OFF" in src
        assert "command_park_off()" in src

    def test_keba_park_off_disables_without_a_quota(self):
        """The whole point: PARK_OFF must NOT write an energy quota (the next
        plug-in would inherit it as a fresh allowance). It disables outright."""
        import inspect
        from custom_components.solar_energy_management.coordinator.charger_adapters import (
            keba,
        )
        import re
        src = inspect.getsource(keba.KebaAdapter.command_park_off)
        # strip the docstring — it NAMES set_energy/quota to explain what the
        # method AVOIDS; the test is about the code, not the prose
        code = re.sub(r'"""', "", re.sub(r'""".*?"""', "", src, count=1,
                                         flags=re.DOTALL))
        assert "self._device.park_off()" in code
        assert "set_energy" not in code

    def test_the_generic_default_is_a_plain_disable(self):
        import inspect
        from custom_components.solar_energy_management.coordinator.charger_adapters import (
            base,
        )
        src = inspect.getsource(base.ChargerAdapter.command_park_off)
        assert "command_disable()" in src
