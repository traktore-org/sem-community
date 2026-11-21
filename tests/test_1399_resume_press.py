"""#1399 — a paused Zaptec is resumed by its button, not by a higher current.

@RVallen78, Zaptec Go 2, 2.3.0-beta.21: "Start now" at 20:15. SEM wrote
``number.zaptec_max_stroom`` = 20 A and the car drew 0 W all evening; the
Zaptec app said "paused". EVCC on the same box starts it fine — EVCC sends
"resume charging".

A Zaptec paused by a "stop charging" command (its app, EVCC, a schedule)
holds the pause until "resume charging" is pressed; a higher current does not
clear it (``tools/zaptec_sim``). SEM pressed the button only inside
``start_session``, and only while its own ``_session_active`` flag was False
— a flag about SEM's LAST press, read as "the box is running" (bug class 83).
The reconciler never pressed a button at all: ``enable_state()`` answers
``(None, True)`` for one, so #804's "the ENABLE budget paces the presses" was
never wired.

The box answers the question itself: the Zaptec integration makes the resume
button available only while the charger is paused, and HA skips a press on an
unavailable entity. Every test below drives the REAL reconciler, adapter and
device against a small box model with exactly those two rules.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import charger_reconciler as rc
from custom_components.solar_energy_management.coordinator.charger_adapters import (
    GenericAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_adapters.base import (
    ChargerAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    ChargerReconciler,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
    ChargerPower,
)
from custom_components.solar_energy_management.devices.base import (
    CurrentControlDevice,
)

CYCLE_S = 10.0
RESUME = "button.zaptec_hervat_het_opladen"
CURRENT = "number.zaptec_max_stroom"
PRESS = ("button", "press")


class Box:
    """A Zaptec Go 2, as far as SEM can touch it.

    * a current of 0 is a SOFT pause: raising it charges again;
    * a final stop (``hard_stopped``) holds until "resume charging";
    * the resume button is available only while hard-stopped (the real
      integration's ``is_command_valid``); a press on it while unavailable is
      skipped by HA without an error;
    * ``lag_s``: how long the cloud takes to act on a press and report it.
    """

    def __init__(self, *, hard_stopped: bool, max_a: float = 0.0,
                 cable: bool = True, lag_s: float = 0.0,
                 resumes: bool = True) -> None:
        self.hard_stopped = hard_stopped
        self.max_a = max_a
        self.cable = cable
        self.lag_s = lag_s
        self.resumes = resumes          # False: a press reaches it, nothing moves
        self.clock = 0.0
        self._resume_at: float | None = None
        self.presses_taken = 0

    @property
    def button_available(self) -> bool:
        return self.cable and self.hard_stopped

    def tick(self, now: float) -> None:
        self.clock = now
        if self._resume_at is not None and now >= self._resume_at:
            self.hard_stopped = False
            self._resume_at = None

    def press(self) -> None:
        if not self.button_available:
            return                       # HA: unavailable entity, skipped
        self.presses_taken += 1
        if self.resumes and self._resume_at is None:
            self._resume_at = self.clock + self.lag_s
            if self.lag_s <= 0:
                self.hard_stopped = False
                self._resume_at = None

    @property
    def charging(self) -> bool:
        return self.cable and not self.hard_stopped and self.max_a >= 6

    @property
    def power_w(self) -> float:
        return round(self.max_a * 230.0 * 3, 1) if self.charging else 0.0


def _rig(box: Box, *, session_active: bool, refuse_press: bool = False):
    """A real ``CurrentControlDevice`` wired to ``box`` through a fake HA."""
    sent: list[tuple] = []
    hass = MagicMock()

    async def _call(domain, service, data=None, blocking=True):
        sent.append((domain, service, dict(data or {})))
        if (domain, service) == PRESS:
            if refuse_press:
                raise RuntimeError("Running command 'resume_charging' failed")
            box.press()
        elif (domain, service) == ("number", "set_value"):
            box.max_a = float((data or {}).get("value", 0))

    def _get(eid):
        if eid == RESUME:
            return SimpleNamespace(
                state="2026-11-20T18:00:00+00:00" if box.button_available
                else "unavailable", attributes={})
        if eid == CURRENT:
            return SimpleNamespace(state=str(box.max_a),
                                   attributes={"min": 0, "max": 20, "step": 1})
        return None

    hass.services.async_call = _call
    hass.services.has_service = MagicMock(return_value=False)
    hass.states.get = MagicMock(side_effect=_get)
    dev = CurrentControlDevice(
        hass=hass, device_id="zaptec", name="Zaptec Charger", priority=5,
        min_current=6.0, max_current=20.0, phases=3, voltage=230.0,
        power_entity_id="sensor.zaptec_laadvermogen", current_entity_id=CURRENT)
    dev.start_stop_entity = RESUME
    dev._session_active = session_active
    return dev, sent


def _charge(amps: int = 16) -> ChargerDecision:
    return ChargerDecision(
        charger_id="zaptec", mode="always_max",
        intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=amps,
        reason="plan override — forced to charge")


def _idle() -> ChargerDecision:
    return ChargerDecision(charger_id="zaptec", mode="solar_plus_cheap",
                           intent=ChargerIntent.IDLE, reason="waiting")


def _run(box, dev, decisions, *, rec=None, start=0.0, plug_known=True):
    """One coordinator cycle per decision; returns the reconciler."""
    adapter = GenericAdapter(dev)
    rec = rec or ChargerReconciler(charger_id="zaptec", heartbeat_s=300.0)
    now = start
    for decision in decisions:
        box.tick(now)
        power = ChargerPower(
            charger_id="zaptec", power_w=box.power_w,
            connected=box.cable if plug_known else False,
            charging=box.charging, plug_known=plug_known)
        asyncio.run(rec.reconcile_and_apply(decision, adapter, power, now=now))
        now += CYCLE_S
    return rec


def _presses(sent) -> list:
    return [c for c in sent if (c[0], c[1]) == PRESS]


# ── the reporter's evening ──────────────────────────────────────────────

@pytest.mark.unit
def test_start_now_on_a_paused_box_presses_resume_and_the_car_charges():
    """The live case: an earlier session left ``_session_active`` True, the
    box was paused by somebody else, and "Start now" asks for a charge."""
    box = Box(hard_stopped=True, max_a=0.0)
    dev, sent = _rig(box, session_active=True)
    _run(box, dev, [_charge()] * 6)
    assert box.charging, f"the box is still paused — sent: {sent}"
    assert box.power_w > 5000
    assert len(_presses(sent)) == 1, sent


@pytest.mark.unit
def test_the_old_rule_leaves_the_box_paused_forever(monkeypatch):
    """Vacuity twin: with the button read as never pressable (the old
    reconciler, which saw no button at all), the same evening writes 16 A
    into a paused box for ten minutes and presses nothing."""
    monkeypatch.setattr(ChargerAdapter, "resume_pressable", lambda self: False)
    box = Box(hard_stopped=True, max_a=0.0)
    dev, sent = _rig(box, session_active=True)
    _run(box, dev, [_charge()] * 60)
    assert not box.charging and box.max_a == 16, sent
    assert not _presses(sent), sent


@pytest.mark.unit
def test_a_box_paused_in_the_middle_of_a_charge_is_resumed():
    """SEM is charging; the app (or EVCC) pauses the box. The next press
    comes once the gap since the start has passed."""
    box = Box(hard_stopped=False, max_a=0.0)
    dev, sent = _rig(box, session_active=False)
    rec = _run(box, dev, [_charge()] * 3)
    assert box.charging
    box.hard_stopped = True                     # paused from outside
    n = int(rc.RESUME_PRESS_GAP_S / CYCLE_S) + 3
    _run(box, dev, [_charge()] * n, rec=rec, start=3 * CYCLE_S)
    assert box.charging, sent
    assert box.presses_taken == 1, sent


# ── what must NOT be pressed ────────────────────────────────────────────

@pytest.mark.unit
def test_a_soft_pause_resumes_on_the_current_and_nothing_extra_is_pressed():
    """0 A is a soft pause: the button is unavailable, the current write
    alone resumes the box, and the reconciler adds no press."""
    box = Box(hard_stopped=False, max_a=0.0)
    dev, sent = _rig(box, session_active=True)
    _run(box, dev, [_charge()] * 30)
    assert box.charging
    assert not _presses(sent), sent


@pytest.mark.unit
@pytest.mark.parametrize("decision", [_idle(), ChargerDecision(
    charger_id="zaptec", mode="off", intent=ChargerIntent.RELEASE,
    reason="off"), ChargerDecision(
    charger_id="zaptec", mode="solar", intent=ChargerIntent.DISABLE,
    reason="stop")], ids=["idle", "release", "disable"])
def test_no_press_unless_sem_wants_a_charge(decision):
    box = Box(hard_stopped=True)
    dev, sent = _rig(box, session_active=True)
    _run(box, dev, [decision] * 40)
    assert not _presses(sent) and box.hard_stopped, sent


@pytest.mark.unit
def test_no_press_when_the_plug_is_not_known():
    """A press is a start: a charger that cannot say whether a car is there
    is not pressed outside its own session start."""
    box = Box(hard_stopped=True)
    dev, sent = _rig(box, session_active=True)
    _run(box, dev, [_charge()] * 40, plug_known=False)
    assert not _presses(sent), sent


@pytest.mark.unit
def test_a_switch_surface_is_untouched():
    """Only a ``button.`` is a resume surface; a switch keeps #536."""
    box = Box(hard_stopped=False)
    dev, _ = _rig(box, session_active=True)
    dev.start_stop_entity = "switch.wallbox_pause_resume"
    assert GenericAdapter(dev).resume_pressable() is False


# ── pacing ──────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_a_box_that_never_resumes_gets_a_few_spaced_presses_then_quiet():
    """The Go 2's own lock (or a brand whose button is always pressable):
    the press reaches the box and nothing moves. At most RESUME_PRESS_MAX
    presses, each RESUME_PRESS_GAP_S apart, over half an hour."""
    box = Box(hard_stopped=True, resumes=False)
    dev, sent = _rig(box, session_active=True)
    rec = ChargerReconciler(charger_id="zaptec", heartbeat_s=300.0)
    stamps = []
    adapter = GenericAdapter(dev)
    for i in range(180):
        now = i * CYCLE_S
        before = len(_presses(sent))
        power = ChargerPower(charger_id="zaptec", power_w=0.0, connected=True)
        asyncio.run(rec.reconcile_and_apply(_charge(), adapter, power, now=now))
        if len(_presses(sent)) > before:
            stamps.append(now)
    assert len(stamps) == rc.RESUME_PRESS_MAX, stamps
    gaps = [stamps[i + 1] - stamps[i] for i in range(len(stamps) - 1)]
    assert all(g >= rc.RESUME_PRESS_GAP_S for g in gaps), gaps


@pytest.mark.unit
def test_cloud_lag_does_not_double_press():
    """The box takes a minute to act on the press and to say so; the button
    reads available all that time. One press, not six."""
    box = Box(hard_stopped=True, lag_s=60.0)
    dev, sent = _rig(box, session_active=True)
    _run(box, dev, [_charge()] * 12)
    assert box.charging, sent
    assert len(_presses(sent)) == 1, sent


@pytest.mark.unit
def test_the_first_cycle_of_a_charge_presses_once_not_twice():
    """``_session_active`` False and a paused box: the reconciler's press
    claims the session, so ``start_session`` does not press again."""
    box = Box(hard_stopped=True)
    dev, sent = _rig(box, session_active=False)
    _run(box, dev, [_charge()])
    assert len(_presses(sent)) == 1, sent
    assert dev._session_active is True


@pytest.mark.unit
def test_a_long_pause_from_charging_counts_afresh():
    """A stretch with no draw spends its presses; after a pause from
    charging of RESUME_RESET_S, a new charge may press again."""
    box = Box(hard_stopped=True, resumes=False)
    dev, sent = _rig(box, session_active=True)
    n = int(rc.RESUME_PRESS_GAP_S / CYCLE_S) * (rc.RESUME_PRESS_MAX + 1)
    rec = _run(box, dev, [_charge()] * n)
    spent = len(_presses(sent))
    assert spent == rc.RESUME_PRESS_MAX
    pause = int(rc.RESUME_RESET_S / CYCLE_S) + 1
    _run(box, dev, [_idle()] * pause + [_charge()] * 2, rec=rec,
         start=n * CYCLE_S)
    assert len(_presses(sent)) == spent + 1, sent


@pytest.mark.unit
def test_a_flapping_decision_still_resumes_a_paused_box():
    """Review: a start stamp on every transition kept the gap from ever
    passing while the decision flapped (charge 60 s, idle 20 s)."""
    box = Box(hard_stopped=False)
    dev, sent = _rig(box, session_active=False)
    rec = _run(box, dev, [_charge()] * 3)
    assert box.charging
    box.hard_stopped = True                     # paused from outside
    _run(box, dev, ([_idle()] * 2 + [_charge()] * 6) * 10, rec=rec,
         start=3 * CYCLE_S)
    assert box.presses_taken == 1, sent


@pytest.mark.unit
def test_a_flapping_decision_cannot_reset_the_count():
    """Review: an always-pressable button and a car that never draws, with
    the decision flapping (charge 150 s, idle 30 s) for two hours — the
    count holds, so at most RESUME_PRESS_MAX presses."""
    box = Box(hard_stopped=True, resumes=False)
    dev, sent = _rig(box, session_active=True)
    _run(box, dev, ([_charge()] * 15 + [_idle()] * 3) * 40)
    assert len(_presses(sent)) == rc.RESUME_PRESS_MAX, sent


@pytest.mark.unit
def test_observer_mode_does_not_spend_the_real_presses():
    """Review: withheld presses counted against the real budget, so a paused
    box seen in observer mode was never pressed once observer mode ended."""
    box = Box(hard_stopped=True)
    dev, sent = _rig(box, session_active=True)
    dev.observer_mode = True
    rec = _run(box, dev, [_charge()] * 50)
    assert box.hard_stopped and not _presses(sent), sent   # nothing left
    dev.observer_mode = False
    _run(box, dev, [_charge()] * 3, rec=rec, start=50 * CYCLE_S)
    assert box.charging, sent
    assert len(_presses(sent)) == 1, sent


@pytest.mark.unit
def test_a_button_beside_another_start_is_not_a_resume_surface():
    """Review: with a start service beside the button, a press claims no
    session, and ``start_session`` would send its own start too."""
    box = Box(hard_stopped=True)
    dev, _ = _rig(box, session_active=True)
    dev.start_service = "zaptec.resume_charging"
    assert GenericAdapter(dev).resume_pressable() is False


@pytest.mark.unit
def test_a_claiming_press_forgets_the_park():
    """Review: the press skips ``start_session``, which is where SEM records
    that it said yes again (#935); the press records it instead."""
    box = Box(hard_stopped=True)
    dev, _ = _rig(box, session_active=False)
    calls = []

    async def _remember(parked):
        calls.append(parked)

    dev._remember_parked = _remember
    _run(box, dev, [_charge()])
    assert calls and calls[-1] is False, calls


# ── a refused press ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_a_refused_press_costs_neither_the_cycle_nor_the_current_write():
    box = Box(hard_stopped=True)
    dev, sent = _rig(box, session_active=True, refuse_press=True)
    _run(box, dev, [_charge()])
    assert ("number", "set_value", {"entity_id": CURRENT, "value": 16.0}) in sent, sent


# ── the readable answer ─────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.parametrize("state,expected", [
    ("unavailable", False), ("", False), (None, False),
    ("unknown", True), ("2026-11-20T18:00:00+00:00", True),
])
def test_resume_pressable_reads_the_button(state, expected):
    box = Box(hard_stopped=False)
    dev, _ = _rig(box, session_active=True)
    st = None if state is None else SimpleNamespace(state=state, attributes={})
    dev.hass.states.get = MagicMock(return_value=st)
    assert GenericAdapter(dev).resume_pressable() is expected
