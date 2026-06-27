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


class ActionKind(Enum):
    """Minimal hardware action the reconciler may emit."""
    NONE = auto()           # already converged — issue nothing
    DISABLE = auto()        # open the contactor (brand disable service)
    WRITE_CURRENT = auto()  # set charging current (amps on the Action)
    START_AND_WRITE = auto()  # open a session + arm failsafe + write (amps)
    ENABLE = auto()         # re-assert the start/stop switch ON (#536 — Wallbox)
    REPORT_ENABLE_BLOCKED = auto()  # enable switch unavailable/locked — surface it (#536)


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    amps: int = 0


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


def desired_from_decision(decision: ChargerDecision) -> Tuple[DesiredState, int]:
    """Pure map: ChargerDecision → (DesiredState, amps).

    CHARGE_MAX returns amps=0 as a sentinel; the apply layer resolves
    the hardware max from the adapter (so this stays pure and the max
    isn't duplicated here)."""
    intent = decision.intent
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

    def reconcile(self, desired: DesiredState, amps: int,
                  observed: ObservedState, now: float) -> List[Action]:
        """Pure decision table (spec rows 1-8, first match wins)."""

        # OFF / IDLE share the convergence target (contactor open). The
        # only difference is the flicker grace, which OFF never gets.
        if desired in (DesiredState.OFF, DesiredState.IDLE):
            # Leaving CHARGE — the next CHARGE episode must START + re-arm,
            # and gets a fresh round of enable re-asserts (#536 backoff).
            self._charging_intent_active = False
            self._enable_attempts = 0
            self._enable_gave_up_at = 0.0
            drawing = observed.charging or observed.self_charging
            if not drawing:
                # Row 2 — already converged. THE spam fix: issue nothing.
                self._consecutive_idle_count = 0
                return [Action(ActionKind.NONE)]
            if desired is DesiredState.OFF:
                if not observed.enable_controllable:
                    # #548 — the contactor is app/cloud-locked (Wallbox
                    # Eco-Smart / Scheduled / Power-Sharing): SEM cannot
                    # open it. Issuing DISABLE every cycle is futile and
                    # hides the real cause from the user. Surface it.
                    return [Action(ActionKind.REPORT_ENABLE_BLOCKED)]
                # Row 1 — user-explicit OFF: open immediately, no grace.
                return [Action(ActionKind.DISABLE)]
            # IDLE + drawing — flicker hold then confirm (rows 3-4).
            self._consecutive_idle_count += 1
            self._consecutive_idle_count = min(self._consecutive_idle_count, self._idle_disable_threshold)
            if self._consecutive_idle_count < self._idle_disable_threshold:
                return [Action(ActionKind.NONE)]
            return [Action(ActionKind.DISABLE)]

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

        for action in actions:
            if action.kind is ActionKind.NONE:
                continue
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
            elif action.kind is ActionKind.DISABLE:
                await adapter.command_disable()
                _LOGGER.info("reconcile(%s): DISABLE — %s",
                             self.charger_id, decision.reason)
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
    return ObservedState(
        charging=adapter.actual_charging(power),
        setpoint_a=setpoint,
        self_charging=adapter.is_self_charging(power),
        power_w=float(getattr(power, "power_w", 0.0) or 0.0),
        enabled=enabled,
        enable_controllable=controllable,
    )
