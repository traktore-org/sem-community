"""Charger state reconciler — desired-vs-observed convergence (#392).

The per-cycle imperative actuator (``actuate.py``) re-issued a hardware
command EVERY coordinator cycle regardless of whether anything changed —
the root cause of the recurring KEBA 6 A reverts and the 391× repeated
``keba.disable`` seen on PROD 2026-06-21. This module replaces that with
a reconciliation loop: compute the desired state, read the observed
state, emit only the actions needed to converge, and emit nothing when
already converged.

Design: docs/superpowers/specs/2026-06-21-charger-reconciler-design.md
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, List, Optional, Tuple

from .charger_types import ChargerDecision, ChargerIntent, ChargerPower

if TYPE_CHECKING:
    from .charger_adapters.base import ChargerAdapter

_LOGGER = logging.getLogger(__name__)


class DesiredState(Enum):
    """What SEM wants the charger to BE doing this cycle."""
    OFF = auto()     # user-explicit OFF (ChargerIntent.DISABLE)
    IDLE = auto()    # temporary pause (ChargerIntent.IDLE)
    CHARGE = auto()  # charging (CHARGE_AT_AMPS / CHARGE_MAX)
    RELEASED = auto()  # (#898) hands-off (ChargerIntent.RELEASE): SEM issues nothing


#: A real unplug persists; a UDP blip is one cycle (project_ev_flap_udp_blip).
#: Park only after the disconnect has held this many consecutive cycles.
PARK_ON_DISCONNECT_CYCLES: int = 2


class ActionKind(Enum):
    """Minimal hardware action the reconciler may emit."""
    NONE = auto()           # already converged — issue nothing
    DISABLE = auto()        # open the contactor (brand disable service)
    PARK_OFF = auto()       # car GONE — leave the box disabled+cold so the next plug-in can't auto-start
    WRITE_CURRENT = auto()  # set charging current (amps on the Action)
    START_AND_WRITE = auto()  # open a session + arm failsafe + write (amps)
    ENABLE = auto()         # re-assert the start/stop switch ON (#536 — Wallbox)
    REPORT_ENABLE_BLOCKED = auto()  # enable switch unavailable/locked — surface it (#536)
    REPORT_STOP_WAR = auto()        # box keeps re-starting against our stop — cease fire (#763)
    REPORT_STOP_UNENFORCEABLE = auto()  # no mechanism can open the contactor (#627)
    REPORT_FAILSAFE_SUSPECTED = auto()  # box re-enables on a CONSTANT interval after our stop (#823)
    CLEAR_FAILSAFE_SUSPECTED = auto()   # a stop finally HELD past the interval — the box was fixed (#823)


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    amps: int = 0
    # (#823) the learned stop→re-enable interval, on REPORT_FAILSAFE_SUSPECTED
    # only — the Repair cannot point at "Tmo FS: 600" without the number.
    interval_s: float = 0.0


@dataclass(frozen=True)
class ObservedState:
    """What the charger is actually doing, read from the adapter."""
    charging: bool       # adapter.actual_charging(power) — power-based
    setpoint_a: int      # the value SEM last believes it set
    self_charging: bool  # adapter.is_self_charging(power)
    power_w: float
    # #536 — start/stop enable switch reconciliation (Wallbox & friends).
    enabled: Optional[bool] = None
    """The ACTUAL enable-switch state. None = charger has no readable
    start/stop switch (KEBA / service / button control) → enable
    reconciliation is N/A. True/False = switch on/off."""
    enable_controllable: bool = True
    """False when the charger HAS an enable switch but its state is
    unavailable/unknown (Wallbox locked / eco-smart) — SEM can't drive
    it, so charging is silently impossible until surfaced (#536)."""
    stop_controllable: bool = True
    connected: bool = True
    """Whether the car is plugged in. Disconnect is the one TRUE end of
    a stop war (#763) — the handshake partner left, so the war memory
    resets. Defaults True: a charger that cannot say keeps the old
    behavior."""
    """False when NO configured mechanism can open the contactor (#627):
    no stop service, no charge-mode select, no start/stop entity, no
    ``<domain>.disable``, and a current entity whose ``min`` is above 0 so
    the 0 A fallback is unwritable. Deliberately separate from
    ``enable_controllable`` — that one gates the CHARGE rows, and a charger
    SEM can start but not stop must keep charging normally while the
    un-stoppability is surfaced. Conflating them would turn a reporting
    gap into a total loss of surplus charging."""


def desired_from_decision(decision: ChargerDecision) -> Tuple[DesiredState, int]:
    """Pure map: ChargerDecision → (DesiredState, amps).

    CHARGE_MAX returns amps=0 as a sentinel; the apply layer resolves
    the hardware max from the adapter (so this stays pure and the max
    isn't duplicated here)."""
    intent = decision.intent
    if intent is ChargerIntent.RELEASE:
        return DesiredState.RELEASED, 0
    if intent is ChargerIntent.DISABLE:
        return DesiredState.OFF, 0
    if intent is ChargerIntent.IDLE:
        return DesiredState.IDLE, 0
    if intent is ChargerIntent.CHARGE_MAX:
        return DesiredState.CHARGE, 0
    if intent is ChargerIntent.CHARGE_AT_AMPS:
        return DesiredState.CHARGE, int(decision.commanded_amps)
    # Defensive: unknown intent → safest is IDLE (no draw, no spam).
    _LOGGER.error("desired_from_decision: unknown intent %r → IDLE", intent)
    return DesiredState.IDLE, 0


# Consecutive IDLE cycles to hold the previous setpoint before
# converging to idle/disable — absorbs a solar-sensor flicker that
# would otherwise drive KEBA into "authorization rejected" (PROD
# 2026-06-02). Was ``ChargerAdapter.IDLE_DEBOUNCE_THRESHOLD`` until
# Task 11 moved idle ownership wholly into the reconciler.
DEFAULT_IDLE_DISABLE_THRESHOLD: int = 4

# #763 — stop-war ceasefire tuning. Rounds are settled→redraw edges; the
# backoff is deliberately LONG (one aborted handshake per half hour instead
# of six per minute), and a quiet spell means the box gave up on its own.
STOP_WAR_ROUNDS: int = 3
STOP_WAR_BACKOFF_S: float = 1800.0
# (#763 beta.7 recurrence) 3600, not 600: quiet is exactly what a
# slow-retrying car looks like BETWEEN retries. onkelfu's Mercedes came
# back every ~717 s — slower than the old 600 s reset — so every burst
# counted from zero and the ceasefire never engaged. A war ends on
# disconnect, on SEM wanting CHARGE, or on an HOUR of true quiet; not on
# a gap shorter than a car's retry period.
STOP_WAR_QUIET_RESET_S: float = 3600.0
# A war that survives its first ceasefire is persistent: each further
# ceasefire doubles the stand-down (capped), so the handshake-abort rate
# decays instead of settling at one abort per backoff forever.
STOP_WAR_BACKOFF_MAX_FACTOR: int = 8
# (#763 round 3, evcc parity) evcc floors every corrective contactor
# command at chargerSwitchDuration = 60 s — its syncCharger logs a
# self-start, re-syncs its own belief, and lets the NEXT control tick
# re-disable. We re-issued DISABLE every 10-s cycle while a burst
# lasted: redundant bridge writes, each a fresh chance to abort the
# car's handshake. One DISABLE per dwell; the war accounting (edges,
# ceasefire) is unaffected.
STOP_REASSERT_DWELL_S: float = 60.0


class ChargerReconciler:
    """Per-charger convergence engine. One instance per charger, cached
    for the charger's lifetime (it holds transition state). Pure
    ``reconcile`` for decisions; effectful ``reconcile_and_apply`` (Task 3)
    executes them via the adapter.
    """

    def __init__(self, charger_id: str, heartbeat_s: float,
                 idle_disable_threshold: int = DEFAULT_IDLE_DISABLE_THRESHOLD,
                 max_enable_attempts: int = 5,
                 enable_retry_interval_s: float = 300.0) -> None:
        self.charger_id = charger_id
        self._heartbeat_s = float(heartbeat_s)
        self._idle_disable_threshold = int(idle_disable_threshold)
        self._last_write_at: float = 0.0
        self._consecutive_idle_count: int = 0
        self._charging_intent_active: bool = False
        """True once we've issued the START for the current charge episode.
        Gates the START_AND_WRITE action on the *desired-state transition*
        into CHARGE, NOT on ``observed.charging`` — otherwise a charger
        that isn't drawing yet (ramp lag, a full-but-plugged car held in a
        deadline mode, a mock charger) would re-START + re-arm the failsafe
        every single cycle (the exact spam this whole change removes; caught
        live on HA-TEST 2026-06-21). Reset whenever desired leaves CHARGE."""
        # #536 enable backoff — a charger in an autonomous mode (Wallbox
        # Eco-Smart, app scheduling) keeps flipping its OWN enable switch
        # back off; re-asserting it every cycle is an infinite tug-of-war
        # (the start/stop oscillation). Try hard for ``max_enable_attempts``
        # cycles, then STOP fighting + surface the misconfig, probing once
        # per ``enable_retry_interval_s`` in case the user fixes it.
        self._max_enable_attempts: int = int(max_enable_attempts)
        self._enable_retry_interval_s: float = float(enable_retry_interval_s)
        self._enable_attempts: int = 0
        self._enable_gave_up_at: float = 0.0
        # #548 actuation observability — record what the reconciler last DID
        # and whether the charger kept drawing against a stop, so the
        # ``diagnose`` service can show "SEM commanded stop N× but the box
        # is still drawing" without another triage round.
        self._last_desired: "str | None" = None
        self._last_actions: List[str] = []
        self._last_apply_at: float = 0.0
        self._stop_commanded_while_drawing: int = 0
        """Consecutive cycles SEM has issued DISABLE while the charger is
        still drawing — a non-zero value means the stop is not taking
        (charger ignoring the command / re-enabled externally)."""
        # #552 — idle-settled marker. The IDLE flicker-grace (N cycles before
        # DISABLE) exists ONLY to absorb actuator lag while a session SEM just
        # stopped winds down. Once idle has SETTLED (contactor observed open,
        # no draw), a newly-appearing draw is a rogue self-start (KEBA
        # auto-start at its stored setpoint, #315) — it gets DISABLE
        # immediately, same as the user-explicit OFF row. Without this every
        # box self-start earned a fresh grace window (~3 cycles × 4.9 kW from
        # the home battery, every car-retry, all night).
        # #553 — initialized True: at boot SEM has commanded NOTHING, so a
        # draw found while desired=IDLE is by definition not our wind-down —
        # policy says idle, disable immediately. The grace re-arms on every
        # genuine CHARGE→IDLE transition (the only wind-down there is).
        self._idle_settled: bool = True
        # (park-on-disconnect) An enabled KEBA auto-starts the NEXT plug-in
        # on its own — "not drawing" is NOT "off". SEM used to issue nothing
        # when a car left (the box stayed enabled), so the next plug-in
        # auto-charged ~1 kWh before the quota-hold caught it (Guido, PROD
        # 26.08). His pre-SEM automation disabled the box after every charge
        # for exactly this. So: ONE PARK_OFF on the settled disconnect edge.
        # ``_seen_connected`` gates it to a real "car LEFT" edge: only a
        # charger we have observed WITH a car, now gone, is parked on
        # departure (an empty box at boot has nothing to park). The
        # ``_disconnect_run`` debounce rides past a single-cycle UDP unplug
        # blip (project_ev_flap_udp_blip) that would otherwise kill a live
        # charge.
        self._seen_connected: bool = False
        self._parked_off: bool = False
        self._disconnect_run: int = 0
        # #763 — the stop-war ceasefire, the #536 backoff's mirror. SEM's
        # stop WORKS (contactor opens) but the box re-closes on the car's
        # retry at its stored setpoint; every stop→redraw round-trip aborts
        # one handshake, and ~2 h of that latched a Mercedes' charging
        # fault (onkelfu, Modbus KEBA #763). After STOP_WAR_ROUNDS
        # round-trips SEM stands down for STOP_WAR_BACKOFF_S and reports —
        # a strobing contactor is worse for the car than a few kWh of
        # unplanned 6 A charge. A round is the settled→drawing EDGE; a
        # steady draw that never opens is the #627/#548 family, not this.
        self._stop_war_rounds: int = 0
        self._stop_war_last_round_at: float = 0.0
        self._stop_war_backoff_until: float = 0.0
        self._stop_war_draw_seen: bool = False
        self._stop_war_reported: bool = False
        self._stop_war_ceasefires: int = 0
        # (#823) stop→re-enable gap history. A failsafe timeout re-enables on
        # a CONSTANT interval after our DISABLE — a retrying car or a human
        # does not. Two matching gaps name it; the report never changes the
        # stop cadence (that war the box always wins, #763).
        self._failsafe_gaps: list = []
        self._failsafe_reported: bool = False
        self._failsafe_interval_s: float = 0.0
        # (#823) A gap only counts if the stop actually TOOK in between —
        # the box settled and then returned. Continuous drawing against a
        # stop is a DIFFERENT fault (stop-not-taking, #548) and produced
        # cycle-cadence "gaps" of 1-2 s that the tolerance floor happily
        # called constant. A failsafe that never lets the stop land is
        # indistinguishable from that case and is already reported by the
        # stop-war / stop-not-taking surfaces.
        self._failsafe_settled_since_disable: bool = False
        self._last_disable_issued_at: float = 0.0
        self._last_disable_at: float = float("-inf")

    def snapshot_war(self, now: float) -> dict:
        """(#763 beta.7) The war state for the diagnostics download.

        onkelfu's dump carried the charge-stability giveup fields (all
        empty — a different mechanism) and nothing from here, so the
        machinery that owns the stop war was invisible and looked
        disengaged. Read-only.
        """
        return {
            "rounds": self._stop_war_rounds,
            "ceasefires": self._stop_war_ceasefires,
            "backoff_remaining_s": round(
                max(0.0, self._stop_war_backoff_until - now), 1),
            "last_round_ago_s": round(
                now - self._stop_war_last_round_at, 1)
                if self._stop_war_last_round_at else None,
            "stop_commanded_while_drawing":
                self._stop_commanded_while_drawing,
            "last_desired": self._last_desired,
            "last_actions": list(self._last_actions),
        }

    def _gated_disable(self, now: float) -> List[Action]:
        """One DISABLE per STOP_REASSERT_DWELL_S (#763 round 3)."""
        if now - self._last_disable_at < STOP_REASSERT_DWELL_S:
            return [Action(ActionKind.NONE)]
        self._last_disable_at = now
        self._last_disable_issued_at = now          # (#823) gap anchor
        return [Action(ActionKind.DISABLE)]

    def _failsafe_action(self) -> List[Action]:
        """(#823) Name a constant-interval self-re-enable, once.

        Two gaps within 2% (or 5 s) of each other is the signature — a
        failsafe timeout is periodic TO THE SECOND, which is the whole
        discriminator. The tolerance is deliberately tight: onkelfu's
        Mercedes retried "every ~12 minutes", and a 10% band at that scale
        (72 s) would swallow a car timer's jitter and cry wolf (#611).
        The action only ever ACCOMPANIES the row's normal decision: naming
        the fault must not change the stop cadence."""
        if self._failsafe_reported or len(self._failsafe_gaps) < 2:
            return []
        a, b = self._failsafe_gaps[-2], self._failsafe_gaps[-1]
        mean = (a + b) / 2.0
        if mean <= 0 or abs(a - b) > max(5.0, 0.02 * mean):
            return []
        self._failsafe_reported = True
        self._failsafe_interval_s = round(mean, 1)
        return [Action(ActionKind.REPORT_FAILSAFE_SUSPECTED,
                       interval_s=self._failsafe_interval_s)]

    def _end_stop_war(self) -> None:
        self._stop_war_rounds = 0
        self._stop_war_backoff_until = 0.0
        self._stop_war_draw_seen = False
        self._stop_war_ceasefires = 0

    def reconcile(self, desired: DesiredState, amps: int,
                  observed: ObservedState, now: float) -> List[Action]:
        """Pure decision table (spec rows 1-8, first match wins)."""
        # (#898) Row 0 — RELEASED: hands-off, senior to every row below.
        # Charge mode Off used to be DISABLE, and the rogue-start guard
        # (#315/#552) re-asserted it on a session the USER started. Now:
        # leaving CHARGE for RELEASED ends SEM's OWN session with one
        # DISABLE (the user asked for Off, not for the car to finish); from
        # then on SEM issues nothing — no park-off on unplug, no failsafe
        # naming, no stop-war rounds. Whatever draws, draws.
        if desired is DesiredState.RELEASED:
            self._end_stop_war()
            self._consecutive_idle_count = 0
            self._idle_settled = False
            if observed.connected:
                self._seen_connected = True
                self._disconnect_run = 0
            if self._charging_intent_active:
                self._charging_intent_active = False
                self._enable_attempts = 0
                self._enable_gave_up_at = 0.0
                self._last_disable_at = now
                self._last_disable_issued_at = now
                return [Action(ActionKind.DISABLE)]
            return [Action(ActionKind.NONE)]
        # (#823) Recovery: a reported failsafe whose LAST stop has now held
        # quiet for twice the learned interval means the user fixed the box —
        # retire the Repair and re-arm the recogniser, so a later relapse is
        # named again rather than silently absorbed by a spent flag.
        if not observed.charging and self._last_disable_issued_at:
            self._failsafe_settled_since_disable = True
        if (self._failsafe_reported and self._failsafe_interval_s
                and not observed.charging and self._last_disable_issued_at
                and now - self._last_disable_issued_at
                > 2.0 * self._failsafe_interval_s):
            self._failsafe_reported = False
            self._failsafe_gaps.clear()
            self._failsafe_interval_s = 0.0
            return [Action(ActionKind.CLEAR_FAILSAFE_SUSPECTED)]
        # (#763) Unplugged = the war is over — its other party left.
        # (park-on-disconnect) …and the box must be left actively OFF, not
        # merely not-drawing: an enabled KEBA auto-starts the NEXT plug-in.
        # PARK_OFF fires only on a real "car LEFT" edge — a charger SEEN
        # connected, now gone. A box never observed with a car is not
        # "parked on departure"; nothing left.
        if observed.connected:
            self._seen_connected = True
            self._disconnect_run = 0
            self._parked_off = False
        else:
            self._end_stop_war()
            self._disconnect_run += 1
            if (self._seen_connected
                    and self._disconnect_run >= PARK_ON_DISCONNECT_CYCLES
                    and not self._parked_off):
                self._parked_off = True
                return [Action(ActionKind.PARK_OFF)]

        # OFF / IDLE share the convergence target (contactor open). The
        # only difference is the flicker grace, which OFF never gets.
        if desired in (DesiredState.OFF, DesiredState.IDLE):
            # Leaving CHARGE — the next CHARGE episode must START + re-arm,
            # and gets a fresh round of enable re-asserts (#536 backoff).
            # #552: a fresh CHARGE→IDLE transition begins a WIND-DOWN — the
            # flicker-grace below applies until idle settles.
            if self._charging_intent_active:
                self._idle_settled = False
            self._charging_intent_active = False
            self._enable_attempts = 0
            self._enable_gave_up_at = 0.0
            drawing = observed.charging or observed.self_charging
            if not drawing:
                # Row 2 — already converged. THE spam fix: issue nothing.
                self._consecutive_idle_count = 0
                self._idle_settled = True  # #552 — wind-down complete
                # #763 — the draw edge is over; a long quiet spell means
                # the box gave up on its own and the war is history.
                self._stop_war_draw_seen = False
                if (self._stop_war_rounds
                        and now - self._stop_war_last_round_at
                        > STOP_WAR_QUIET_RESET_S):
                    self._stop_war_rounds = 0
                    self._stop_war_ceasefires = 0
                return [Action(ActionKind.NONE)]
            if not observed.stop_controllable:
                # #627 — SEM has no mechanism that can open this contactor.
                # Still issue the DISABLE (it costs nothing and starts
                # working the moment a stop entity is configured), but say so
                # instead of counting failures into a log line nobody reads.
                # Applies to IDLE as well as OFF: the reporter's 4.1 kW came
                # out of the house batteries either way.
                return [Action(ActionKind.DISABLE),
                        Action(ActionKind.REPORT_STOP_UNENFORCEABLE)]
            # #763 — stop-war ceasefire, covering BOTH the OFF row and the
            # settled-rogue row below (same box, same car, same fault). A
            # war round is the settled→drawing EDGE: our stop landed, the
            # box came back. The wind-down flicker grace never counts —
            # that draw is our own session ending.
            if desired is DesiredState.OFF or self._idle_settled:
                if now < self._stop_war_backoff_until:
                    # Ceasefire holds: no DISABLE, the box may finish its
                    # 6 A session. Reported once per onset at apply.
                    return [Action(ActionKind.REPORT_STOP_WAR)]
                if not self._stop_war_draw_seen:
                    self._stop_war_draw_seen = True
                    if (self._stop_war_rounds
                            and now - self._stop_war_last_round_at
                            > STOP_WAR_QUIET_RESET_S):
                        self._stop_war_rounds = 0
                    self._stop_war_rounds += 1
                    self._stop_war_last_round_at = now
                    # (#823) the gap from OUR stop to the box's return —
                    # counted only when the stop actually took (a settle was
                    # observed since the disable) and the gap is failsafe-
                    # scale. No real controller timeout is under a minute;
                    # sub-minute returns are cars, humans, or cycle noise.
                    if (self._last_disable_issued_at
                            and self._failsafe_settled_since_disable
                            and now - self._last_disable_issued_at >= 60.0):
                        self._failsafe_gaps.append(
                            now - self._last_disable_issued_at)
                        del self._failsafe_gaps[:-4]
                    self._failsafe_settled_since_disable = False
                    if self._stop_war_rounds > STOP_WAR_ROUNDS:
                        self._stop_war_ceasefires += 1
                        factor = min(
                            2 ** (self._stop_war_ceasefires - 1),
                            STOP_WAR_BACKOFF_MAX_FACTOR,
                        )
                        self._stop_war_backoff_until = (
                            now + STOP_WAR_BACKOFF_S * factor)
                        return [Action(ActionKind.REPORT_STOP_WAR)]

            if desired is DesiredState.OFF:
                fs = self._failsafe_action()
                if fs:
                    if not observed.enable_controllable:
                        return fs + [Action(ActionKind.REPORT_ENABLE_BLOCKED)]
                    return fs + self._gated_disable(now)
                if not observed.enable_controllable:
                    # #548 — the contactor is app/cloud-locked (Wallbox
                    # Eco-Smart / Scheduled / Power-Sharing): SEM cannot
                    # open it. Issuing DISABLE every cycle is futile and
                    # hides the real cause from the user. Surface it.
                    return [Action(ActionKind.REPORT_ENABLE_BLOCKED)]
                # Row 1 — user-explicit OFF: open immediately, no grace —
                # then re-assert at the dwell, not every cycle.
                return self._gated_disable(now)
            # #552 — draw appeared AFTER idle had settled: not our wind-down
            # but a rogue self-start (KEBA auto-start, #315). Open the
            # contactor immediately, re-asserted every cycle it persists —
            # parity with the OFF row. The grace below stays reserved for
            # winding down a session SEM itself just stopped.
            if self._idle_settled:
                return self._gated_disable(now)
            # IDLE + drawing — flicker hold then confirm (rows 3-4).
            self._consecutive_idle_count += 1
            self._consecutive_idle_count = min(self._consecutive_idle_count, self._idle_disable_threshold)
            if self._consecutive_idle_count < self._idle_disable_threshold:
                return [Action(ActionKind.NONE)]
            return self._gated_disable(now)

        # desired is CHARGE — reset idle grace, and end any stop war: SEM
        # wanting the box to charge dissolves the disagreement (#763).
        self._end_stop_war()

        # desired is CHARGE — reset idle grace.
        #
        # Note on self-resume (#346): unlike the legacy actuator, which
        # force-disabled before applying ANY intent if the box was drawing
        # against consent, we do NOT disable-before-charge here. When we
        # want CHARGE and the box is already drawing (self-resumed during a
        # prior idle), the desired outcome is already happening — opening
        # then reclosing the contactor would be pointless churn. The
        # correct setpoint is asserted by START_AND_WRITE / WRITE below.
        # ``observed.self_charging`` therefore only drives the OFF/IDLE
        # rows above (where drawing IS against intent). Pinned by
        # ``test_charge_self_charging_does_not_disable_first``.
        self._consecutive_idle_count = 0

        # #536 — enable-switch reconciliation (prepended to the current
        # action). Keyed on the ACTUAL switch state, NOT on power, so a
        # full-but-plugged car (switch on, drawing 0 W) does not churn.
        enable_actions: List[Action] = []
        if not observed.enable_controllable:
            # Switch present but unavailable/unknown (locked / eco-smart):
            # SEM cannot drive it → charging is silently impossible. Surface.
            enable_actions.append(Action(ActionKind.REPORT_ENABLE_BLOCKED))
        elif observed.enabled is False:
            # Switch is OFF while we want to charge. Re-assert it — but with
            # BACKOFF so we don't fight a self-pausing charger forever (#536
            # start/stop oscillation; common on the Pulsar's
            # Autostart/Eco-Smart mode). Try hard for the first
            # ``max_enable_attempts`` cycles; after that, stop fighting and
            # surface the misconfig, probing once per retry interval.
            if self._enable_attempts < self._max_enable_attempts:
                self._enable_attempts += 1
                if self._enable_attempts >= self._max_enable_attempts:
                    self._enable_gave_up_at = now
                enable_actions.append(Action(ActionKind.ENABLE))
            elif now - self._enable_gave_up_at >= self._enable_retry_interval_s:
                # Backed off, retry window elapsed → a single probe.
                self._enable_gave_up_at = now
                enable_actions.append(Action(ActionKind.ENABLE))
            else:
                # Backed off, within window → surface, don't fight.
                enable_actions.append(Action(ActionKind.REPORT_ENABLE_BLOCKED))
        else:
            # enabled True (it stuck) or None (no readable switch) — the
            # contactor is where we want it; reset the backoff so a future
            # drop starts a fresh round of hard re-asserts.
            self._enable_attempts = 0
            self._enable_gave_up_at = 0.0

        if enable_actions and enable_actions[0].kind is ActionKind.REPORT_ENABLE_BLOCKED:
            # Switch is uncontrollable (locked / eco-smart / unavailable) —
            # SEM cannot drive the contactor, so DON'T also issue charge
            # commands: a successful command_current would clear the repair
            # we just raised, flapping it every cycle. Surface only.
            return enable_actions

        if not self._charging_intent_active:
            # Row 5 — TRANSITION into charging: open a session, arm the
            # failsafe, write. Gated on the desired transition (not on
            # observed.charging) so a not-yet-drawing charger doesn't
            # re-START every cycle. Recovery from a mid-charge device reset
            # is handled by the heartbeat WRITE below (command_current
            # re-opens a dropped KEBA session and keeps the already-armed
            # failsafe fed) — no re-arm spam needed.
            self._charging_intent_active = True
            self._last_write_at = now
            return enable_actions + [Action(ActionKind.START_AND_WRITE, amps)]
        if amps and observed.setpoint_a != amps:
            # Row 6 — target change or drift (failsafe revert) correction.
            self._last_write_at = now
            return enable_actions + [Action(ActionKind.WRITE_CURRENT, amps)]
        if (now - self._last_write_at) >= self._heartbeat_s:
            # Row 7 — refresh to feed the device failsafe watchdog.
            self._last_write_at = now
            return enable_actions + [Action(ActionKind.WRITE_CURRENT, amps)]
        # Row 8 — current converged; still re-assert the enable switch if
        # it drifted off (enable_actions is empty in the common case).
        return enable_actions or [Action(ActionKind.NONE)]

    async def reconcile_and_apply(self, decision: ChargerDecision,
                                 adapter: "ChargerAdapter",
                                 power: ChargerPower, now: float) -> None:
        """Compute desired+observed, reconcile, execute the actions."""
        desired, amps = desired_from_decision(decision)
        if desired is DesiredState.CHARGE and amps == 0:
            # Resolve the CHARGE_MAX sentinel to the hardware max so the
            # adapter writes a real value and drift detection works.
            amps = int(getattr(adapter, "max_current_a", 0)) or amps
        observed = observe(adapter, power)
        actions = self.reconcile(desired, amps, observed, now)

        # #548 actuation observability — record desired + actions + whether a
        # stop is failing to take (charger still drawing while we DISABLE).
        self._last_desired = desired.name
        self._last_actions = [a.kind.name for a in actions]
        self._last_apply_at = now
        _drawing = bool(observed.charging or observed.self_charging)
        # (#763 round 3) Counts cycles the stop INTENT holds against a
        # live draw — not emitted DISABLEs. With the reassert dwell, the
        # write lands once a minute; the box defying it is still one
        # defiance per cycle, and the "stop is not taking" warning must
        # keep its ~3-cycle timing.
        _stop_intent_held = (
            any(a.kind is ActionKind.DISABLE for a in actions)
            or (desired in (DesiredState.OFF, DesiredState.IDLE)
                and now - self._last_disable_at < STOP_REASSERT_DWELL_S)
        )
        if _stop_intent_held and _drawing:
            self._stop_commanded_while_drawing += 1
            if self._stop_commanded_while_drawing in (3, 12, 60):
                _LOGGER.warning(
                    "reconcile(%s): commanded STOP %d× but charger still drawing "
                    "%.0f W (status/power says charging) — the stop is not taking. "
                    "Check the charger's stop control (enable switch %s, status %s).",
                    self.charger_id, self._stop_commanded_while_drawing,
                    float(getattr(power, "power_w", 0.0) or 0.0),
                    getattr(getattr(adapter, "_device", None), "start_stop_entity", None),
                    getattr(getattr(adapter, "_device", None), "charging_status_entity", None),
                )
        elif not _drawing:
            self._stop_commanded_while_drawing = 0
            # #627 — the contactor is open again (user unplugged, car
            # finished, or a stop entity got configured): retire the repair.
            self._clear_stop_unenforceable(adapter)

        # ── #546 OFFER-STEADINESS PROBE (observe-only, DEBUG) ────────────
        # Diagnostic that pinned the 6↔9 A KEBA flap (#546, now resolved by
        # the managed-neutralize failsafe + delta-guard). Kept as a DEBUG
        # tool — logs desired/believed/hardware side by side so a future
        # flap can be re-diagnosed; gated on DEBUG so it's silent (and does
        # no per-cycle sensor read) on a normal INFO PROD.
        #   desired  = what SEM wants (this decision)
        #   believed = what SEM thinks it set (drives drift detection)
        #   hardware = the ACTUAL KEBA max_current sensor (ground truth)
        # BLIND_DRIFT = hardware ≠ believed → the box reverted and SEM didn't
        # see it. MIND_CHANGE = believed ≠ desired → SEM moved the target.
        if desired is DesiredState.CHARGE and _LOGGER.isEnabledFor(logging.DEBUG):
            try:
                _dev = getattr(adapter, "_device", None)
                # LIVE offered current from the configured current sensor
                # (#546). ``_dev.max_current`` is the static CONFIG CAP (32), not
                # the live offer — never use it here. KEBA's only live source is
                # the external sensor entity; None when unconfigured ("?").
                _hw = None
                _sensor = getattr(_dev, "current_sensor_entity_id", "") or ""
                _hass = getattr(_dev, "hass", None)
                if _sensor and _hass is not None:
                    _st = _hass.states.get(_sensor)
                    if _st is not None and _st.state not in (
                        "unknown", "unavailable", None, "",
                    ):
                        try:
                            _hw = int(round(float(_st.state)))
                        except (ValueError, TypeError):
                            _hw = None
                _fs = getattr(_dev, "failsafe", getattr(_dev, "failsafe_mode", None))
                _tags = []
                if _hw is not None and int(_hw) != int(observed.setpoint_a):
                    _tags.append(f"BLIND_DRIFT(hw{int(_hw)}≠belief{observed.setpoint_a})")
                if int(observed.setpoint_a) != int(amps):
                    _tags.append(f"MIND_CHANGE(belief{observed.setpoint_a}≠desired{amps})")
                _LOGGER.debug(
                    "EV-OFFER-PROBE(%s): desired=%dA believed=%dA hardware=%sA "
                    "drawn=%.0fW charging=%s failsafe=%s actions=%s %s",
                    self.charger_id, int(amps), int(observed.setpoint_a),
                    ("?" if _hw is None else int(_hw)),
                    float(getattr(power, "power_w", 0.0) or 0.0),
                    observed.charging, _fs,
                    [a.kind.name + (f"@{a.amps}" if a.amps else "") for a in actions],
                    " ".join(_tags),
                )
            except Exception:  # the probe must never break actuation
                pass

        await self._apply_actions(actions, adapter, decision, power)

    async def _apply_actions(self, actions, adapter, decision, power) -> None:
        """Execute the reconcile actions. Extracted (#700) so the one-shot
        warning behaviour is testable against the real action loop."""
        for action in actions:
            if action.kind is ActionKind.NONE:
                continue
            # (#700) any action other than the unenforceable-report means the
            # intent moved or a mechanism appeared — re-arm the one-shot
            # warning so the NEXT unenforceable episode warns again.
            if action.kind is not ActionKind.REPORT_STOP_UNENFORCEABLE:
                self._stop_unenforceable_warned = False
            if action.kind is not ActionKind.REPORT_STOP_WAR:
                self._stop_war_reported = False
            if action.kind is ActionKind.ENABLE:
                # #536 — re-assert the start/stop switch (idempotent).
                await adapter.ensure_enabled()
                _LOGGER.info("reconcile(%s): ENABLE — enable switch was off, "
                             "re-asserting — %s", self.charger_id, decision.reason)
            elif action.kind is ActionKind.REPORT_ENABLE_BLOCKED:
                # #536 — switch present but uncontrollable (locked/eco-smart).
                _LOGGER.warning(
                    "reconcile(%s): enable switch unavailable/locked — charging "
                    "cannot start until it's controllable (unlock the charger / "
                    "leave eco-smart mode) — %s", self.charger_id, decision.reason)
                report = getattr(adapter, "report_enable_blocked", None)
                if report is not None:
                    await report()
            elif action.kind is ActionKind.REPORT_STOP_WAR:
                # #763 — once per ONSET (the #700 pattern): the ceasefire
                # holds for half an hour and re-warning every 10 s cycle
                # would be its own flood. Re-armed below when any other
                # action lands (the war ended or the intent moved).
                if not self._stop_war_reported:
                    self._stop_war_reported = True
                    _LOGGER.warning(
                        "reconcile(%s): stop war detected — the charger keeps "
                        "restarting itself against SEM's stop (%d stop→redraw "
                        "round-trips). Standing down for %.0f min so the car "
                        "is not strobed into a charging fault; it may charge "
                        "at the box's stored minimum meanwhile. Two causes "
                        "look IDENTICAL from here. (1) The wallbox's own "
                        "auto-start/authorization re-closes the contactor on "
                        "the car's retry — disable charger-side auto-start, or "
                        "give SEM a stop mechanism the box respects. (2) "
                        "ANOTHER controller is commanding this same charger — "
                        "a second SEM instance (a test rig sharing the "
                        "hardware, with observer mode off), an HA automation, "
                        "or a vendor app. Check that first if one could "
                        "exist: it is cheap to rule out, and a stop that "
                        "starts holding the moment the other writer is "
                        "silenced is the proof. — %s",
                        self.charger_id, self._stop_war_rounds,
                        STOP_WAR_BACKOFF_S / 60.0, decision.reason)
                else:
                    _LOGGER.debug(
                        "reconcile(%s): stop-war ceasefire holding (%d rounds)",
                        self.charger_id, self._stop_war_rounds)
                continue
            elif action.kind is ActionKind.REPORT_FAILSAFE_SUSPECTED:
                # (#823) once, by construction (_failsafe_reported). SEM
                # cannot write failsafe registers on a generic charger and
                # must not guess register numbers — the fix is a one-time
                # change on the box, so the output is instruction, not war.
                _LOGGER.warning(
                    "reconcile(%s): the charger re-enabled itself %.0f s "
                    "after SEM's stop, twice, to the second — that is a "
                    "charger-side failsafe/controller-timeout fallback, not "
                    "a car retrying. SEM will not fight it (#763). Fix it on "
                    "the box: look for a failsafe/fallback current setting "
                    "(KEBA: 'Curr FS' / 'Tmo FS') and set the fallback "
                    "current to 0.", self.charger_id, action.interval_s)
                report = getattr(adapter, "report_failsafe_suspected", None)
                if report is not None:
                    await report(action.interval_s)
            elif action.kind is ActionKind.CLEAR_FAILSAFE_SUSPECTED:
                _LOGGER.info(
                    "reconcile(%s): a stop has held past the learned failsafe "
                    "interval — the box appears fixed; retiring the repair",
                    self.charger_id)
                clear = getattr(adapter, "clear_failsafe_suspected", None)
                if clear is not None:
                    await clear()
            elif action.kind is ActionKind.REPORT_STOP_UNENFORCEABLE:
                # #627 — the stop is structurally impossible on this config.
                # (#700) Once per ONSET, not per cycle: the condition persists
                # for as long as the config lacks a stop mechanism, and at a
                # 10 s cadence the repeat wiped out days of log history on a
                # real install (8000+ entries). The first occurrence carries
                # the full instruction at WARNING; repeats drop to debug; the
                # flag re-arms when any other action lands (the intent moved
                # or a mechanism appeared), so a NEW unenforceable episode
                # warns again.
                if not getattr(self, "_stop_unenforceable_warned", False):
                    self._stop_unenforceable_warned = True
                    _LOGGER.warning(
                        "reconcile(%s): STOP is unenforceable — no stop service, "
                        "no charge-mode select, no start/stop entity, no "
                        "<domain>.disable, and the current entity cannot express "
                        "0 A. The car keeps drawing %.0f W against SEM's intent "
                        "(and on a battery install that power comes out of the "
                        "house battery). Configure a start/stop switch for this "
                        "charger. (Logged once — repeats at debug level until "
                        "the condition clears.) — %s",
                        self.charger_id,
                        float(getattr(power, "power_w", 0.0) or 0.0),
                        decision.reason,
                    )
                else:
                    _LOGGER.debug(
                        "reconcile(%s): STOP still unenforceable (%.0f W) — %s",
                        self.charger_id,
                        float(getattr(power, "power_w", 0.0) or 0.0),
                        decision.reason,
                    )
                self._report_stop_unenforceable(adapter, power)
            elif action.kind is ActionKind.DISABLE:
                await adapter.command_disable()
                _LOGGER.info("reconcile(%s): DISABLE — %s",
                             self.charger_id, decision.reason)
            elif action.kind is ActionKind.PARK_OFF:
                await adapter.command_park_off()
                _LOGGER.info(
                    "reconcile(%s): PARK OFF — car disconnected, box left "
                    "disabled so the next plug-in cannot auto-start",
                    self.charger_id)
            elif action.kind is ActionKind.START_AND_WRITE:
                # arm_failsafe() is a no-op unless opted in (#546, evcc-style).
                await adapter.arm_failsafe()
                await adapter.command_current(action.amps)
                _LOGGER.info("reconcile(%s): START %dA — %s",
                             self.charger_id, action.amps, decision.reason)
            elif action.kind is ActionKind.WRITE_CURRENT:
                await adapter.command_current(action.amps)
                _LOGGER.debug("reconcile(%s): WRITE %dA — %s",
                              self.charger_id, action.amps, decision.reason)

    # ── #627 stop-unenforceable repair plumbing ──────────────────────────
    def _device_and_hass(self, adapter):
        dev = getattr(adapter, "_device", None)
        hass = getattr(dev, "hass", None)
        return dev, hass

    def _report_stop_unenforceable(self, adapter, power) -> None:
        dev, hass = self._device_and_hass(adapter)
        if dev is None or hass is None:
            return
        from .repair_issues import raise_charger_stop_unenforceable
        raise_charger_stop_unenforceable(
            hass, self.charger_id,
            name=str(getattr(dev, "name", self.charger_id)),
            power_w=float(getattr(power, "power_w", 0.0) or 0.0),
            entity=str(getattr(dev, "current_entity_id", "") or "—"),
        )

    def _clear_stop_unenforceable(self, adapter) -> None:
        dev, hass = self._device_and_hass(adapter)
        if dev is None or hass is None:
            return
        from .repair_issues import clear_charger_stop_unenforceable
        clear_charger_stop_unenforceable(hass, self.charger_id)


# ─────────────────────────────────────────────────────────────────
# Task 3 — effectful layer
# ─────────────────────────────────────────────────────────────────

def observe(adapter, power) -> ObservedState:
    """Read the observed state from the adapter (brand-agnostic)."""
    setpoint = int(round(float(getattr(getattr(adapter, "_device", None), "_current_setpoint", 0) or 0)))
    # #536 — actual enable-switch state. enable_state() returns
    # (enabled, controllable); default (None, True) for chargers with no
    # readable start/stop switch (KEBA / service / button control).
    enabled, controllable = None, True
    _enable_state = getattr(adapter, "enable_state", None)
    if _enable_state is not None:
        try:
            enabled, controllable = _enable_state()
        except Exception as exc:  # noqa: BLE001 — never let observe() throw
            _LOGGER.debug("enable_state() failed: %s", exc)
    # #627 — can ANY configured mechanism open the contactor? Unknown
    # (no device / probe raised) defaults True: a false alarm here would
    # raise a repair on every working install.
    stop_ok = True
    _can_stop = getattr(getattr(adapter, "_device", None), "can_stop_charging", None)
    if callable(_can_stop):
        try:
            stop_ok = bool(_can_stop())
        except Exception as exc:  # noqa: BLE001 — never let observe() throw
            _LOGGER.debug("can_stop_charging() failed: %s", exc)
    return ObservedState(
        charging=adapter.actual_charging(power),
        setpoint_a=setpoint,
        self_charging=adapter.is_self_charging(power),
        power_w=float(getattr(power, "power_w", 0.0) or 0.0),
        connected=bool(getattr(power, "connected", True)),
        enabled=enabled,
        enable_controllable=controllable,
        stop_controllable=stop_ok,
    )
