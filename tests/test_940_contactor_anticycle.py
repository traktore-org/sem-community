"""#940 — a switch-controlled charger's contactor has a minimum dwell.

alexmc1510's HA switch history for ``switch.cargador_coche_carga_de_ve``,
09.09.2026, while SEM's plan coverage for the charger flapped (#939):

    22:13:24 On → 22:14:23 Off  (59 s)
    22:14:43 On → 22:15:43 Off  (60 s)
    22:16:03 On → 22:17:04 Off  (61 s)
    22:17:24 On → 22:18:24 Off  (60 s)

Six minutes of 60 s on / 20 s off. The 60 s is ``STOP_REASSERT_DWELL_S``
— which paces the REPEAT of a DISABLE and says nothing about the opposite
command — and the 20 s is two coordinator cycles: nothing at all stood
between "SEM wants CHARGE again" and ``ensure_enabled`` closing the relay.

These tests pin the floor: SEM's own contactor MOVES are separated by
``CONTACTOR_MIN_OFF_S`` (close) and ``CONTACTOR_MIN_ON_S`` (open); a
re-assert of a command already in force moves no relay and must not re-arm
either clock (bug class 73 — stamping it starves the stop forever, which is
worse than the bug); a DEMAND never waits (``DesiredState.OFF``, a declared
``safety_stop``, mode Off's one-shot RELEASE, a real disconnect); a
current-number charger never sees the floor at all; and the hold is a HOLD
— it does not spend the #536 enable budget, raise its Repair, or swallow
the heartbeat current write.
"""
from __future__ import annotations

import random
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    CONTACTOR_MIN_OFF_S,
    CONTACTOR_MIN_ON_S,
    STOP_REASSERT_DWELL_S,
    ActionKind,
    ChargerReconciler,
    DesiredState,
    ObservedState,
    observe,
)
from custom_components.solar_energy_management.devices.base import (
    CurrentControlDevice,
)

CYCLE_S = 10.0
CLOSES = (ActionKind.ENABLE, ActionKind.START_AND_WRITE)
OPENS = (ActionKind.DISABLE, ActionKind.PARK_OFF)


def _rec() -> ChargerReconciler:
    return ChargerReconciler(charger_id="ev_charger", heartbeat_s=5.0,
                             idle_disable_threshold=4)


def _obs(*, charging=False, setpoint=0, self_charging=False, power=0.0,
         enabled=None, surface=True, connected=True,
         enable_controllable=True) -> ObservedState:
    return ObservedState(charging=charging, setpoint_a=setpoint,
                         self_charging=self_charging, power_w=power,
                         enabled=enabled, enable_controllable=enable_controllable,
                         contactor_surface=surface, connected=connected)


def _kinds(actions):
    return [a.kind for a in actions]


# ── the reporter's own cadence ────────────────────────────────────────

def _drive_the_flap(*, surface: bool, cycles: int = 240, block: int = 6):
    """Drive the reconciler with #939's flapping decision and return the
    relay's own on/off history — the same thing the reporter read out of
    HA's switch history.

    The decision alternates in ``block``-cycle runs (60 s of CHARGE, 60 s
    of IDLE at a 10 s cycle), which is what produced alexmc1510's cadence:
    the 4-cycle idle grace has to be spent before a stop is issued at all,
    so a 1-cycle alternation never reaches the relay in the first place.

    The relay is SIMULATED: it closes when SEM emits ENABLE /
    START_AND_WRITE, opens on DISABLE / PARK_OFF, and the car draws
    whenever it is closed. That is the physical fact the floor exists to
    bound; counting COMMANDS instead would count idempotent re-asserts that
    move no contactor — and it is that very confusion (bug class 73) that
    makes a floor look present while the relay cycles.
    """
    rec = _rec()
    t = 1000.0
    relay = False
    history = []
    for i in range(cycles):
        desired = (DesiredState.CHARGE if (i // block) % 2 == 0
                   else DesiredState.IDLE)
        obs = _obs(charging=relay, setpoint=6 if relay else 0,
                   enabled=relay, power=1800.0 if relay else 0.0,
                   surface=surface)
        for a in rec.reconcile(desired, 6, obs, t):
            if a.kind in CLOSES and not relay:
                relay = True
                history.append(("close", t))
            elif a.kind in OPENS and relay:
                relay = False
                history.append(("open", t))
        t += CYCLE_S
    return history


def test_the_reporters_cadence_no_longer_reaches_the_relay():
    """#939's flapping decision, 40 minutes of it, on a switch charger.

    Pre-#940 the relay followed the flap: SEM's DISABLE opened it, the
    desired state came back two cycles later and ``ensure_enabled`` closed
    it, over and over. The floor caps the CYCLE, not the repeat.
    """
    history = _drive_the_flap(surface=True)
    # The floor must SLOW the relay, not silence SEM: a fix that simply
    # stopped issuing stops would sail through a "few transitions" check
    # while the car charged all night against SEM's own judgement.
    assert len(history) >= 4, (
        f"only {len(history)} relay transitions in 40 min — SEM has stopped "
        f"acting, not stopped cycling: {history}")
    assert [k for k, _ in history] == ["close", "open"] * (len(history) // 2), (
        f"transitions must alternate: {history}")
    for (kind_a, t_a), (kind_b, t_b) in zip(history, history[1:], strict=False):
        floor = CONTACTOR_MIN_ON_S if kind_b == "open" else CONTACTOR_MIN_OFF_S
        assert t_b - t_a >= floor, (
            f"{kind_a}@{t_a} → {kind_b}@{t_b} is {t_b - t_a:.0f}s apart, "
            f"floor is {floor:.0f}s")
    # 40 minutes cannot buy more full cycles than the floor allows.
    assert len(history) <= 2 * (2400.0 / (CONTACTOR_MIN_ON_S
                                          + CONTACTOR_MIN_OFF_S)) + 2, (
        f"{len(history)} relay transitions in 40 min")


def test_the_pre_fix_cadence_is_what_the_oracle_catches():
    """Vacuity guard: the SAME drive on a charger with no relay surface
    still toggles fast — so the assertion above is measuring the floor, not
    a fixture that never cycles.

    This is also the pre-#940 behaviour, reproduced: the relay follows the
    flap on a cadence set by ``STOP_REASSERT_DWELL_S`` and the cycle time,
    the same shape as alexmc1510's switch history.
    """
    history = _drive_the_flap(surface=False)
    gaps = [b - a for (_, a), (_, b) in zip(history, history[1:], strict=False)]
    assert len(history) >= 8, f"the no-surface drive must cycle freely: {history}"
    assert min(gaps) < min(CONTACTOR_MIN_ON_S, CONTACTOR_MIN_OFF_S), (
        "a current-number charger must keep today's behaviour — if this "
        "run also respects the floor, the floor is being applied where it "
        "was explicitly scoped out")


# ── the two directions ────────────────────────────────────────────────

def test_min_off_holds_the_reclose():
    rec = _rec()
    t = 0.0
    # SEM charges, then — past the minimum ON — stops.
    rec.reconcile(DesiredState.CHARGE, 6, _obs(enabled=False), t)
    t = CONTACTOR_MIN_ON_S
    out = rec.reconcile(DesiredState.OFF, 0,
                        _obs(charging=True, power=1800.0, enabled=True), t)
    assert ActionKind.DISABLE in _kinds(out)
    opened_at = t
    # Two cycles later the decision flaps back — the relay stays open.
    t = opened_at + 2 * CYCLE_S
    out = rec.reconcile(DesiredState.CHARGE, 6, _obs(enabled=False), t)
    assert _kinds(out) == [ActionKind.NONE]
    assert rec.anticycle_snapshot(t)["holding"] == "min_off"
    # One second before the floor expires: still held.
    t = opened_at + CONTACTOR_MIN_OFF_S - 1.0
    assert _kinds(rec.reconcile(DesiredState.CHARGE, 6, _obs(enabled=False), t)) \
        == [ActionKind.NONE]
    # At the floor: the session opens.
    t = opened_at + CONTACTOR_MIN_OFF_S
    out = rec.reconcile(DesiredState.CHARGE, 6, _obs(enabled=False), t)
    assert ActionKind.START_AND_WRITE in _kinds(out)
    assert rec.anticycle_snapshot(t)["holding"] is None


def test_min_on_holds_a_discretionary_stop():
    rec = _rec()
    t = 0.0
    out = rec.reconcile(DesiredState.CHARGE, 6, _obs(enabled=False), t)
    assert ActionKind.START_AND_WRITE in _kinds(out)
    closed_at = t
    # The decision flaps to IDLE and the car IS drawing. The 4-cycle
    # flicker grace runs out first; after it, the #940 floor holds.
    for _ in range(6):
        t += CYCLE_S
        out = rec.reconcile(DesiredState.IDLE, 0,
                            _obs(charging=True, power=1800.0, enabled=True), t)
    assert _kinds(out) == [ActionKind.NONE]
    assert rec.anticycle_snapshot(t)["holding"] == "min_on"
    # At the floor the stop lands.
    t = closed_at + CONTACTOR_MIN_ON_S
    out = rec.reconcile(DesiredState.IDLE, 0,
                        _obs(charging=True, power=1800.0, enabled=True), t)
    assert ActionKind.DISABLE in _kinds(out)


def test_an_explicit_off_never_waits():
    """Every producer of ``ChargerIntent.DISABLE`` in the tree is a DEMAND —
    the #804 phase switch (never switch under load), the active phase
    guard's conductor protection, the VPP export pause. OFF already gets no
    flicker grace for the same reason; it gets no #940 floor either."""
    rec = _rec()
    t = 0.0
    rec.reconcile(DesiredState.CHARGE, 16, _obs(enabled=False), t)
    t += CYCLE_S
    out = rec.reconcile(DesiredState.OFF, 0,
                        _obs(charging=True, power=11000.0, enabled=True), t)
    assert ActionKind.DISABLE in _kinds(out)


def test_a_reassert_does_not_re_arm_the_floor():
    """Bug class 73, the one this fix could most easily have committed: a
    START_AND_WRITE is re-emitted on every CHARGE cycle once an IDLE cycle
    has cleared ``_charging_intent_active``, and a DISABLE once per reassert
    dwell while a stop is not taking. Neither moves a relay, so neither may
    refresh the clock — or a flapping decision would starve the stop
    forever, which is worse than the bug."""
    rec = _rec()
    t = 0.0
    rec.reconcile(DesiredState.CHARGE, 6, _obs(enabled=False), t)
    closed_at = rec._contactor_closed_at
    # Re-emitted starts while the relay is already believed closed.
    for _ in range(20):
        t += CYCLE_S
        rec.reconcile(DesiredState.CHARGE, 6, _obs(charging=True, power=1800.0,
                                                   setpoint=6, enabled=True), t)
    assert rec._contactor_closed_at == closed_at, "a re-assert re-armed min ON"
    # …and the stop lands the moment the floor expires.
    # …and the stop lands the moment the floor expires. From here on the
    # charger has no readable enable switch (KEBA / service / button) —
    # exactly where SEM's own command history IS the belief, and so where a
    # re-assert could re-arm the clock unchecked.
    t = CONTACTOR_MIN_ON_S
    seen = []
    for _ in range(6):
        seen += _kinds(rec.reconcile(
            DesiredState.IDLE, 0,
            _obs(charging=True, power=1800.0, enabled=None), t))
        t += CYCLE_S
    assert ActionKind.DISABLE in seen
    opened_at = rec._contactor_opened_at
    assert opened_at > 0
    # Re-asserted stops while the box keeps drawing (#763's dwell).
    for _ in range(30):
        t += CYCLE_S
        rec.reconcile(DesiredState.IDLE, 0,
                      _obs(charging=True, power=1800.0, enabled=None), t)
    assert rec._contactor_opened_at == opened_at, "a re-assert re-armed min OFF"


def test_a_box_that_opens_its_own_relay_releases_the_minimum_on():
    """A minimum ON protects a relay SEM closed. If the box opened it (an
    auto-pause, the user's own switch), there is nothing left to protect and
    the belief must follow the observation down."""
    rec = _rec()
    t = 0.0
    rec.reconcile(DesiredState.CHARGE, 6, _obs(enabled=False), t)
    assert rec._contactor_closed is True
    t += CYCLE_S
    rec.reconcile(DesiredState.IDLE, 0, _obs(enabled=False), t)
    assert rec._contactor_closed is False


def test_the_heartbeat_write_is_not_held_when_a_stop_did_not_take():
    """The close floor is keyed on the RELAY, not on the session flag: a box
    still drawing against SEM's stop must keep getting its current write —
    that is what feeds a KEBA failsafe watchdog."""
    rec = _rec()
    t = 0.0
    rec.reconcile(DesiredState.CHARGE, 6, _obs(enabled=False), t)
    t = CONTACTOR_MIN_ON_S
    for _ in range(6):
        rec.reconcile(DesiredState.IDLE, 0,
                      _obs(charging=True, power=1800.0, enabled=True), t)
        t += CYCLE_S
    # The box never let go: the switch still reads ON.
    t += CYCLE_S
    out = rec.reconcile(DesiredState.CHARGE, 10,
                        _obs(charging=True, power=1800.0, setpoint=6,
                             enabled=True), t)
    assert ActionKind.WRITE_CURRENT in _kinds(out) or \
        ActionKind.START_AND_WRITE in _kinds(out)


def test_a_current_number_charger_keeps_todays_behaviour():
    """No relay surface → no floor, in EITHER direction."""
    rec = _rec()
    t = 0.0
    rec.reconcile(DesiredState.CHARGE, 6, _obs(surface=False), t)
    t += CYCLE_S
    out = rec.reconcile(DesiredState.OFF, 0,
                        _obs(charging=True, power=1800.0, surface=False), t)
    assert ActionKind.DISABLE in _kinds(out), "stop must not wait"
    t += CYCLE_S
    out = rec.reconcile(DesiredState.CHARGE, 6, _obs(surface=False), t)
    assert ActionKind.START_AND_WRITE in _kinds(out), "start must not wait"


# ── safety keeps its right of way ─────────────────────────────────────

def test_a_safety_stop_bypasses_the_minimum_on():
    rec = _rec()
    t = 0.0
    rec.reconcile(DesiredState.CHARGE, 16, _obs(enabled=False), t)
    # The idle flicker grace is spent first so the ONLY thing left holding
    # the stop is the #940 floor.
    for _ in range(6):
        t += CYCLE_S
        held = rec.reconcile(DesiredState.IDLE, 0,
                             _obs(charging=True, power=9000.0, enabled=True), t)
    assert _kinds(held) == [ActionKind.NONE], "an ordinary stop waits"
    assert rec.anticycle_snapshot(t)["holding"] == "min_on"
    out = rec.reconcile(DesiredState.IDLE, 0,
                        _obs(charging=True, power=9000.0, enabled=True), t,
                        safety_stop=True)
    assert ActionKind.DISABLE in _kinds(out), (
        "a peak emergency / VPP pause opens the relay this cycle")


def test_release_and_park_off_bypass_the_minimum_on():
    # RELEASE — the ONE disable that ends SEM's session when the user picks
    # Off. SEM never speaks again, so a swallowed one strands the session.
    rec = _rec()
    t = 0.0
    rec.reconcile(DesiredState.CHARGE, 6, _obs(enabled=False), t)
    t += CYCLE_S
    out = rec.reconcile(DesiredState.RELEASED, 0,
                        _obs(charging=True, power=1800.0, enabled=True), t)
    assert _kinds(out) == [ActionKind.DISABLE]

    # PARK_OFF — the car physically left; the relay it protects is idle.
    rec = _rec()
    t = 0.0
    rec.reconcile(DesiredState.CHARGE, 6, _obs(enabled=False), t)
    for _ in range(3):
        t += CYCLE_S
        out = rec.reconcile(DesiredState.IDLE, 0,
                            _obs(connected=False, enabled=True), t)
        if ActionKind.PARK_OFF in _kinds(out):
            break
    assert ActionKind.PARK_OFF in _kinds(out)


def test_a_rogue_self_start_is_still_stopped_at_once():
    """The clocks track SEM's OWN commands. A box that closes its own
    contactor never earns a minimum ON — #315's KEBA auto-start must keep
    being disabled on the first cycle."""
    rec = _rec()
    t = 0.0
    # Idle has settled — SEM has commanded nothing.
    rec.reconcile(DesiredState.IDLE, 0, _obs(), t)
    t += CYCLE_S
    out = rec.reconcile(DesiredState.IDLE, 0,
                        _obs(charging=True, self_charging=True, power=4100.0), t)
    assert ActionKind.DISABLE in _kinds(out)


# ── the hold is a hold, not a swallowed command ───────────────────────

def test_the_hold_does_not_spend_the_enable_budget():
    """#536 gives up after five ENABLE attempts and raises a Repair. If the
    floor were enforced below the reconciler the attempts would be spent on
    commands that never went out, and a charger whose switch is perfectly
    fine would be reported as locked."""
    rec = _rec()
    t = 0.0
    rec.reconcile(DesiredState.CHARGE, 6, _obs(enabled=False), t)
    t = CONTACTOR_MIN_ON_S
    rec.reconcile(DesiredState.OFF, 0,
                  _obs(charging=True, power=1800.0, enabled=True), t)
    opened_at = t
    for i in range(1, 11):
        t = opened_at + i * CYCLE_S
        out = rec.reconcile(DesiredState.CHARGE, 6, _obs(enabled=False), t)
        assert _kinds(out) == [ActionKind.NONE]
    assert rec._enable_attempts == 0
    assert rec._enable_gave_up_at == 0.0


def test_an_uncontrollable_enable_switch_is_still_surfaced_while_held():
    rec = _rec()
    t = 0.0
    rec.reconcile(DesiredState.CHARGE, 6, _obs(enabled=False), t)
    t = CONTACTOR_MIN_ON_S
    rec.reconcile(DesiredState.OFF, 0,
                  _obs(charging=True, power=1800.0, enabled=True), t)
    t += CYCLE_S
    out = rec.reconcile(DesiredState.CHARGE, 6,
                        _obs(enabled=None, enable_controllable=False), t)
    assert _kinds(out) == [ActionKind.REPORT_ENABLE_BLOCKED]


def test_the_stop_reassert_dwell_still_paces_repeats():
    """The floor must not swallow #763's reassert: a stop that is not
    taking still gets re-issued once per dwell."""
    rec = _rec()
    t = 0.0
    out = rec.reconcile(DesiredState.OFF, 0, _obs(charging=True, power=4000.0), t)
    assert ActionKind.DISABLE in _kinds(out)
    t += CYCLE_S
    assert _kinds(rec.reconcile(DesiredState.OFF, 0,
                                _obs(charging=True, power=4000.0), t)) \
        == [ActionKind.NONE]
    t = STOP_REASSERT_DWELL_S
    assert ActionKind.DISABLE in _kinds(
        rec.reconcile(DesiredState.OFF, 0, _obs(charging=True, power=4000.0), t))


# ── the invariant oracle (the structural guard) ───────────────────────

def _fuzz_flips(surface: bool, cycles: int = 4000, seed: int = 940):
    """Drive the reconciler through random desired states against a
    SIMULATED relay and return every transition SEM caused, as
    ``(polarity, t, exempt)``.

    The relay is coherent — it follows SEM's own ENABLE / START_AND_WRITE
    and DISABLE / PARK_OFF, and is what ``observed.enabled`` reports — with
    a small chance per cycle of an EXTERNAL flip (the user's own switch, an
    app, a box auto-pause), because a belief that only ever agrees with
    itself proves nothing.

    ``exempt`` marks the cycles whose OPEN is a DEMAND rather than a
    preference and therefore bypasses the minimum ON by design: an explicit
    OFF, a declared ``safety_stop``, or a disconnect (PARK_OFF). The CLOSE
    side has no exemptions at all, so its invariant is absolute.

    Any NEW row that closes or opens the relay without going through the
    gate fails here, whatever it is called.
    """
    rnd = random.Random(seed)
    rec = _rec()
    t = 0.0
    relay = False
    flips = []
    for _ in range(cycles):
        if rnd.random() < 0.02:          # somebody else touched the switch
            relay = not relay
        desired = rnd.choice([DesiredState.CHARGE, DesiredState.IDLE,
                              DesiredState.IDLE, DesiredState.OFF])
        connected = rnd.random() < 0.9
        safety = rnd.random() < 0.05
        drawing = relay and rnd.random() < 0.9
        obs = _obs(charging=drawing, setpoint=rnd.choice([0, 6, 10, 16]),
                   self_charging=drawing and rnd.random() < 0.3,
                   power=4000.0 if drawing else 0.0,
                   enabled=relay, surface=surface, connected=connected)
        exempt = (desired is DesiredState.OFF) or safety or not connected
        for a in rec.reconcile(desired, rnd.choice([6, 10, 16]), obs, t,
                               safety_stop=safety):
            if a.kind in CLOSES and not relay:
                relay = True
                flips.append(("close", t, exempt))
            elif a.kind in OPENS and relay:
                relay = False
                flips.append(("open", t, exempt))
        t += CYCLE_S
    return flips


def _violations(flips):
    """(close_violations, discretionary_open_violations)."""
    close_v = open_v = 0
    last = {"close": None, "open": None}
    for kind, t, exempt in flips:
        opposite = "open" if kind == "close" else "close"
        prev = last[opposite]
        if prev is not None:
            if kind == "close" and t - prev < CONTACTOR_MIN_OFF_S:
                close_v += 1
            elif kind == "open" and not exempt \
                    and t - prev < CONTACTOR_MIN_ON_S:
                open_v += 1
        last[kind] = t
    return close_v, open_v


def test_no_route_through_reconcile_can_cycle_the_relay_faster_than_the_floor():
    flips = _fuzz_flips(surface=True)
    assert len(flips) > 8, "the fuzz must exercise the contactor"
    assert any(k == "close" for k, _, _ in flips)
    assert any(k == "open" for k, _, _ in flips)
    close_v, open_v = _violations(flips)
    assert close_v == 0, (
        f"{close_v} closes landed inside the {CONTACTOR_MIN_OFF_S:.0f}s "
        f"minimum OFF — a row in reconcile() bypassed the gate")
    assert open_v == 0, (
        f"{open_v} discretionary stops landed inside the "
        f"{CONTACTOR_MIN_ON_S:.0f}s minimum ON")


def test_the_oracle_would_fail_without_the_floor():
    """Same fuzz, no relay surface → violations in BOTH directions. An
    oracle that cannot fire is decoration (bug class 8)."""
    close_v, open_v = _violations(_fuzz_flips(surface=False))
    assert close_v > 0 and open_v > 0, (close_v, open_v)


# ── wiring: the device answers, observe() carries it ──────────────────

def _device(**kw):
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.services.has_service = MagicMock(return_value=False)
    hass.states.get = MagicMock(return_value=None)
    dev = CurrentControlDevice(
        hass=hass, device_id="ev", name="EV", priority=5, min_current=6.0,
        max_current=32.0, phases=3, voltage=230.0, power_entity_id="sensor.p",
        charger_service=kw.pop("charger_service", None),
        current_entity_id=kw.pop("current_entity_id", "number.ev_current"))
    for k, v in kw.items():
        setattr(dev, k, v)
    return dev, hass


def test_contactor_surface_recognises_every_discrete_mechanism():
    # The reporter's charger: a start/stop switch beside a current number.
    dev, _ = _device(start_stop_entity="switch.cargador_coche_carga_de_ve")
    assert dev.contactor_surface is True
    # A charge-mode select whose STOP option is unset still CLOSES a relay
    # (this is exactly alexmc1510's config: start='manual', stop=None).
    dev, _ = _device(charge_mode_entity="select.modo", charge_mode_start="manual")
    assert dev.contactor_surface is True
    # Brand start/stop services.
    dev, _ = _device(stop_service="easee.action_command")
    assert dev.contactor_surface is True
    # KEBA — enable/disable services registered.
    dev, hass = _device(charger_service="keba.set_current")
    hass.services.has_service = MagicMock(return_value=True)
    assert dev.contactor_surface is True
    # A current number and nothing else: 0 A is a pause, not a relay cycle.
    dev, _ = _device()
    assert dev.contactor_surface is False


def test_can_stop_charging_is_unchanged_by_the_shared_dispatch_list():
    """#627's answer must not move: the extracted helper feeds both."""
    dev, _ = _device(start_stop_entity="button.zaptec_resume")
    assert dev.can_stop_charging() is True          # unchanged: any entity
    # A select with only a START option is not a stop MECHANISM — #627 falls
    # through to the 0 A fallback, which this device's current entity can
    # express, so the answer stays True and unchanged.
    dev, _ = _device(charge_mode_entity="select.modo", charge_mode_start="manual")
    assert dev.can_stop_charging() is True
    assert dev.contactor_surface is True, "…and it is still a relay CLOSE"
    # The #627 answer itself is unmoved: a bare current entity whose min is
    # above 0 still reports "no mechanism can open this contactor".
    dev, hass = _device()
    hass.states.get = MagicMock(
        return_value=SimpleNamespace(attributes={"min": 6, "max": 32}))
    assert dev.can_stop_charging() is False
    assert dev.contactor_surface is False


def test_observe_carries_the_surface_from_the_device():
    dev, _ = _device(start_stop_entity="switch.ev")
    adapter = SimpleNamespace(
        _device=dev,
        actual_charging=lambda p: False,
        is_self_charging=lambda p: False,
        enable_state=lambda: (True, True),
    )
    power = SimpleNamespace(power_w=0.0, connected=True)
    assert observe(adapter, power).contactor_surface is True

    dev2, _ = _device()
    adapter._device = dev2
    assert observe(adapter, power).contactor_surface is False


def test_observe_defaults_false_when_the_device_cannot_say():
    adapter = SimpleNamespace(
        _device=None,
        actual_charging=lambda p: False,
        is_self_charging=lambda p: False,
    )
    power = SimpleNamespace(power_w=0.0, connected=True)
    assert observe(adapter, power).contactor_surface is False


# ── the safety producers actually set the flag ────────────────────────

def test_peak_emergency_and_vpp_pause_declare_themselves_safety_stops():
    from custom_components.solar_energy_management.coordinator.charger_types import (
        ChargerDecision, ChargerIntent,
    )
    from custom_components.solar_energy_management.coordinator.vpp_dispatch import (
        vpp_pause_override,
    )

    base = ChargerDecision(charger_id="ev", mode="solar",
                           intent=ChargerIntent.CHARGE_AT_AMPS,
                           commanded_amps=16, reason="solar")
    assert base.safety_stop is False
    paused = vpp_pause_override(base, paused=True)
    assert paused.intent is ChargerIntent.DISABLE and paused.safety_stop is True
    assert vpp_pause_override(base, paused=False).safety_stop is False


def test_the_peak_emergency_shed_bypasses_the_contactor_floor():
    """The one DEMAND that arrives as an IDLE. Pinned on the AST, not on a
    source substring: a comment mentioning ``safety_stop=True`` in the same
    window would satisfy a text search, and reordering the keywords would
    break one. This asserts the keyword is on the ``replace()`` call whose
    reason names the emergency."""
    import ast
    import inspect

    from custom_components.solar_energy_management.coordinator import decide as _decide

    tree = ast.parse(inspect.getsource(_decide.decide))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", "") != "replace":
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        reason = kw.get("reason")
        text = ast.dump(reason) if reason is not None else ""
        if "peak EMERGENCY" not in text:
            continue
        found.append(node)
        safety = kw.get("safety_stop")
        assert isinstance(safety, ast.Constant) and safety.value is True, (
            "the peak EMERGENCY shed must bypass the #940 contactor floor")
    assert len(found) == 1, (
        f"expected exactly one peak-EMERGENCY clamp in decide(), found "
        f"{len(found)} — if the branch moved, move this pin with it")


def test_the_snapshot_reports_the_floor_and_the_countdown():
    rec = _rec()
    t = 0.0
    rec.reconcile(DesiredState.CHARGE, 6, _obs(enabled=False), t)
    t = CONTACTOR_MIN_ON_S
    rec.reconcile(DesiredState.OFF, 0,
                  _obs(charging=True, power=1800.0, enabled=True), t)
    t += CYCLE_S
    rec.reconcile(DesiredState.CHARGE, 6, _obs(enabled=False), t)
    snap = rec.anticycle_snapshot(t)
    assert snap["holding"] == "min_off"
    assert 0 < snap["remaining_s"] <= CONTACTOR_MIN_OFF_S
    assert snap["min_on_s"] == CONTACTOR_MIN_ON_S
    assert snap["surface"] is True
    assert "anticycle" in rec.snapshot_war(t)


@pytest.mark.parametrize("floor", [CONTACTOR_MIN_ON_S, CONTACTOR_MIN_OFF_S])
def test_the_floors_are_longer_than_the_reassert_dwell(floor):
    """A floor at or below ``STOP_REASSERT_DWELL_S`` would change nothing:
    the reporter's relay already toggled on that period."""
    assert floor > STOP_REASSERT_DWELL_S
