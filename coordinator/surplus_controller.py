"""Surplus controller for Solar Energy Management.

SEM surplus control algorithm:
1. 10s control loop - evaluates surplus every coordinator update
2. Sequential priority activation - Priority 1 first, cascade down
3. Minimum power threshold per device
4. Regulation offset (default 50W) - always export small buffer to grid
5. Dynamic add/remove - LIFO deactivation on surplus decrease
6. Variable-power devices get proportional control
7. Manual loads reduce available surplus automatically

This replaces the EV-only surplus routing with a generic multi-device
surplus distribution system.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant

from ..devices.base import ControllableDevice, DeviceState, DeviceControlMode
from .plan_verdict import NO_OPINION, PlanVerdict

from ..utils.log_gate import log_on_change

_LOGGER = logging.getLogger(__name__)

# Defaults
DEFAULT_REGULATION_OFFSET = 50  # Watts - always keep small export
DEFAULT_MIN_SURPLUS_CHANGE = 100  # Watts - suppress adjustments below this


@dataclass(frozen=True)
class BatteryTierContext:
    """(#620/#625) Pure inputs for the device battery tiers, computed from
    config + live readings. Tier-1 assist budget is offered ONLY when the
    battery is above the Buffer SoC AND there is real surplus past the Solar
    Gate (the same gate the EV assist uses, #537) — so the battery tops loads
    up out of surplus it would otherwise export, never below the buffer.
    Reserve floor for Tier-2 is the load reclaim reserve
    (``battery_priority_soc``)."""
    soc: Optional[float]
    buffer_soc: float
    reserve_soc: float
    assist_budget_w: float


def build_battery_tier_context(config, battery_soc, true_surplus_w) -> BatteryTierContext:
    """(#625, extracted from the coordinator's update cycle) Pure computation
    of the battery-tier context handed to :meth:`SurplusController.update`."""
    from ..consts.core import (
        DEFAULT_BATTERY_ASSIST_MAX_POWER as _DEF_ASSIST,
        DEFAULT_BATTERY_BUFFER_SOC as _DEF_BUFFER,
        DEFAULT_BATTERY_ASSIST_MIN_SURPLUS as _DEF_GATE,
    )
    buffer_soc = float(config.get("battery_buffer_soc", _DEF_BUFFER) or _DEF_BUFFER)
    reserve_soc = float(config.get("battery_priority_soc", 30) or 30)
    solar_gate = float(config.get("battery_assist_min_surplus", _DEF_GATE) or _DEF_GATE)
    assist_budget = (
        float(config.get("battery_assist_max_power", _DEF_ASSIST) or _DEF_ASSIST)
        if (battery_soc is not None and battery_soc > buffer_soc
            and true_surplus_w >= solar_gate)
        else 0.0
    )
    return BatteryTierContext(
        soc=battery_soc, buffer_soc=buffer_soc,
        reserve_soc=reserve_soc, assist_budget_w=assist_budget,
    )


def effective_peak_state(load_manager_state, vpp_shed_loads: bool):
    """(#625, extracted) The peak posture handed to the surplus controller:
    the load-manager's state, escalated to EMERGENCY while a VPP export
    event wants discretionary loads shed (#580 → #508 W2 peak_shed_all)."""
    if vpp_shed_loads:
        from ..const import LoadManagementState
        return LoadManagementState.EMERGENCY
    return load_manager_state


def solar_bounded_surplus(
    grid_export_w: float,
    active_draw_w: float,
    solar_w: "Optional[float]" = None,
) -> float:
    """The feedback-free SOLAR surplus, physically bounded by production (#620).

    ``grid_export + active_draw`` reconstructs "the surplus that would exist if
    the controller's own loads were off" — the stable quantity to allocate from
    (without the add-back the signal chases its own tail as loads switch on).

    The result is then clamped to ``[0, solar]``: **you cannot have more SOLAR
    surplus than the sun is producing.** This one physical invariant is the whole
    guard — between sunset and sunrise ``solar_w`` is ~0, so the surplus is
    pinned to 0 no matter what the add-back, a noisy grid sensor, or a battery→
    grid discharge tries to fabricate (the phantom overnight "surplus" @onkelfu
    hit when a load ran off the battery at night). ``solar_w=None`` (sensor
    unavailable) skips the cap and falls back to the raw add-back.
    """
    surplus = float(grid_export_w) + float(active_draw_w)
    if solar_w is not None:
        surplus = min(surplus, float(solar_w))
    return max(0.0, surplus)


@dataclass(frozen=True)
class LoadIntent:
    """(desired-state, phase 1) The MANAGEMENT layer's decision for one load:
    what state it should be in, and why. Execution reconciles reality to this —
    it is the single source of truth for on/off, so a gate that yields ``on=False``
    stops a running load *by construction* (no separate deactivation path to
    forget). ``source`` derives the legacy force markers instead of hand-setting
    them (``_batt_overnight_forced == source == 'tier2_battery'`` etc.)."""
    on: bool
    power_w: float
    source: Optional[str]   # 'solar'|'tier1_battery'|'tier2_battery'|'cheap_grid'|None
    reason: str


def compute_load_intent(
    device: "ControllableDevice",
    *,
    remaining_surplus_w: float,
    tier1_headroom_w: float = 0.0,
    price_is_cheap: bool = False,
    peak_freeze: bool = False,
    is_shed_target: bool = False,
    soc_above_reserve: bool = False,
    is_night: bool = True,
    plan: "PlanVerdict" = NO_OPINION,
) -> LoadIntent:
    """(desired-state, phase 1) Pure precedence walk → the load's desired state.

    Faithful to ``SurplusController.update()``'s 7 passes, collapsed into one
    ordered decision (first match wins). ``remaining_surplus_w`` is the solar
    surplus left for THIS device after higher-priority loads (the caller's
    priority walk fills it); the battery/grid clauses don't consume it.
    Everything else is read off ``device`` so it works on a real device or a mock.
    """
    mode = getattr(device, "control_mode", DeviceControlMode.SURPLUS)
    active = bool(getattr(device, "is_active", False))
    held = device.get_current_consumption() if active else 0.0
    # (#638 Stage 3) Loads consult the same PlanVerdict the EV does —
    # the one gate, no side channels (the legacy plan_window bool died
    # in the C5 merge).
    plan_hold = plan.hold

    # 1. Not SEM-driven. Off = monitor only; Peak-only = user-managed, but SEM
    #    still SHEDS it under peak risk.
    if mode == DeviceControlMode.OFF:
        # Switching the mode to Off while SEM is DRIVING the load must release
        # it (stop once, clear ownership), not strand it running forever —
        # class-17 sibling caught live (PROD 2026-07-23: mode→off, load stayed
        # on and SEM never touched it again). A load the USER turned on
        # (not _sem_owned) is left exactly as-is.
        if active and getattr(device, "_sem_owned", False):
            return LoadIntent(False, 0.0, None, "mode off — releasing SEM-driven load")
        return LoadIntent(active, held, None, "off — monitor only")
    if mode == DeviceControlMode.PEAK_ONLY:
        # This controller never proactively sheds peak_only loads — the load
        # manager owns their peak shedding via shed_priority. Matches the old
        # peak-shed pass, which skipped non-SURPLUS devices (ruflo M1).
        return LoadIntent(active, held, None, "peak_only — user-managed")

    # --- SURPLUS mode below ---
    # 2. Peak shed wins over any run reason.
    if is_shed_target:
        return LoadIntent(False, 0.0, None, "peak shed")

    # 2b. (#638 Stage 3) The plan may STOP a paid run whose window closed —
    #     the hold is only ever raised while the remaining blocks can still
    #     deliver the deficit (load_verdict), so cutting here reclaims the
    #     energy for the planned block instead of letting the run bleed on.
    #     ONLY paid, plan-owned runs: solar runs are never plan-gated (the
    #     sun is spending itself), and user-started runs are not SEM's to cut.
    if (active and plan_hold
            and (getattr(device, "_batt_overnight_forced", False)
                 or getattr(device, "_offpeak_forced", False))):
        return LoadIntent(False, 0.0, None,
                          plan.reason or "joint energy plan: window closed")

    # 3. Done for the day — the hard stops (cap overrides the deficit).
    #    (#688) The daily MINIMUM is deliberately NOT one of them. It is a
    #    floor, not a stop: reaching it ends the PAID sources (clause 4), but
    #    free solar surplus may carry the load on up to the Maximum. Mirrors
    #    the EV floor/ceiling contract (#245) that this slider was built to
    #    mirror — treating Min as a stop made Max unreachable whenever Min > 0.
    if getattr(device, "daily_max_runtime_reached", False):
        return LoadIntent(False, 0.0, None, "daily max cap reached")
    if getattr(device, "stop_condition_met", False):
        return LoadIntent(False, 0.0, None, "stop condition met")

    # 3b. A ScheduleDevice past its deadline is a hard commitment — force it on
    #     regardless of surplus or peak posture (matches the old deadline pass,
    #     which was deliberately not peak-gated). ruflo B1.
    if getattr(device, "is_deadline_approaching", False) and not active:
        return LoadIntent(True, float(getattr(device, "rated_power", 0.0) or 0.0),
                          "solar", "deadline force")

    # 4. A source can power it. peak_freeze blocks *new* starts but keeps a
    #    running load on (only an explicit shed removes it, clause 2).
    rated = float(getattr(device, "rated_power", 0.0) or 0.0)
    threshold = float(getattr(device, "min_power_threshold", rated) or rated)
    can_start = active or not peak_freeze
    deficit = bool(getattr(device, "has_runtime_deficit", False))

    # (#688) Past the floor, only FREE surplus may extend the run — the
    # battery has nothing left to guarantee, so the Tier-1 assist stands down.
    # (Tier-2 and cheap-grid below are already deficit-gated, so they close
    # themselves at the floor; pinned by tests either way.)
    if getattr(device, "daily_targets_met", False):
        tier1_headroom_w = 0.0
    effective = float(remaining_surplus_w) + float(tier1_headroom_w)
    # (#688) the start RESERVE: a fresh start needs margin on top of the
    # threshold (600 W pump, 800 W ask), so the start itself plus the next
    # cloud doesn't flip the surplus negative and cycle the device. STARTS
    # only — a running load keeps the plain threshold; reserving against a
    # healthy run would CREATE the cycling this prevents.
    start_bar = threshold
    if not active:
        start_bar = threshold + max(
            0.0, float(getattr(device, "start_reserve_w", 0.0) or 0.0))
    if effective >= start_bar and can_start:
        battery_assisted = tier1_headroom_w > 0 and remaining_surplus_w < threshold
        src = "tier1_battery" if battery_assisted else "solar"
        return LoadIntent(True, rated, src, f"{src}: {effective:.0f}W ≥ {threshold:.0f}W")

    # (#638 C5) Comfort banking: a WILLING band inside its planned block.
    # The ONE sanctioned place the plan CREATES a run — banking has no
    # reactive run reason at all (a willing room otherwise only rides
    # free surplus). Forced rooms never land here: forcing lives on the
    # deficit paths, and a forced room's comfort_state is not "willing".
    if (plan.in_block and can_start
            and getattr(device, "comfort_state", "") == "willing"):
        return LoadIntent(True, rated, "cheap_grid",
                          plan.reason or "joint plan: comfort banking block open")

    # Overnight battery (Tier-2): finish a runtime deficit off the battery.
    # (#633) gated on night — "Finish overnight from: Battery" must not fire
    # in daytime (caught live at 09:10 in full sun).
    # (#638 G4) ``plan_hold`` = the joint energy plan placed this
    # load's blocks elsewhere tonight — an extra AND-gate on the start,
    # never a run reason. No trusted plan leaves behaviour untouched.
    if (deficit and can_start and is_night
            and not plan_hold
            and getattr(device, "battery_eligible_overnight", False)
            and soc_above_reserve):
        return LoadIntent(True, rated, "tier2_battery", "overnight battery — runtime deficit")

    # Cheap-hours grid: finish a runtime deficit off the grid in a cheap window.
    if (deficit and can_start and price_is_cheap
            and not plan_hold
            and getattr(device, "top_up_policy", "solar_only") == "cheap_hours"):
        return LoadIntent(True, rated, "cheap_grid", "cheap-hours grid — runtime deficit")

    # 5. No source → off. When a plan hold is what suppressed the paid
    #    sources, SAY SO — "no source available" with a block twenty
    #    minutes away reads as a bug; the plan's own words read as a plan.
    if plan_hold and deficit:
        detail = f" (until {plan.until:%H:%M})" if plan.until else ""
        return LoadIntent(False, 0.0, None,
                          (plan.reason or "joint energy plan: waiting for the planned window") + detail)
    return LoadIntent(False, 0.0, None, "no source available")


def _load_meter_day(device: "ControllableDevice"):
    """(#703) The load's OWN day boundary — the sunrise-held meter day its
    runtime/deficit live on, NOT the calendar date. The coordinator holds
    ``_load_meter_day`` through the night, so an overnight top-up keeps
    serving the day it started; a force stamped and expired against the
    CALENDAR date instead was killed at exactly 00:00 ("day rollover") while
    its deficit was still open, then re-forced a min_off later — a spurious
    contactor flap every midnight. Stamping AND staleness both read this one
    boundary, so expiry lands at sunrise — the same instant the deficit
    itself resets — by construction. Falls back to the calendar date before
    the first runtime tick stamps the device (fresh boot)."""
    day = getattr(device, "_daily_runtime_meter_day", None)
    if day is not None:
        return day
    from homeassistant.util import dt as dt_util
    return dt_util.now().date()


def _apply_source_markers(device: "ControllableDevice", intent: LoadIntent) -> None:
    """(desired-state, phase 2) The legacy force markers become a DERIVED VIEW of
    the intent's source — recomputed each reconcile, never hand-set — so they
    cannot leak (bug-class 18). Dates are stamped for the load's METER day
    (#703) — the same boundary its deficit lives on."""
    today = _load_meter_day(device)
    is_tier2 = intent.source == "tier2_battery"
    is_grid = intent.source == "cheap_grid"
    device._batt_overnight_forced = is_tier2
    device._batt_overnight_forced_date = today if is_tier2 else None
    device._offpeak_forced = is_grid
    device._offpeak_forced_date = today if is_grid else None


def _clear_source_markers(device: "ControllableDevice") -> None:
    device._batt_overnight_forced = False
    device._batt_overnight_forced_date = None
    device._offpeak_forced = False
    device._offpeak_forced_date = None


def _reconcile_load_observe(device: "ControllableDevice", intent: LoadIntent,
                            active: bool, controller=None) -> float:
    """OBSERVER mode = the layer-3 intercept, in one place.

    Management (layer 1) + decision (layer 2) already ran live against the real
    sensors and produced ``intent``. Here — the ONLY execution seam — we LOG the
    command we WOULD send and return the load's OBSERVED draw, without actuating
    or mutating any device state. The would-command log is the observation/test
    surface: HA-TEST runs the full real pipeline and audits these lines with zero
    hardware risk. This is why observer mode needs no separate ``observe_only``
    path — a clean layer cut makes it a one-line branch in the actuator.
    """
    # (#764) Record the would-decision on the controller's standard surface
    # BEFORE the log lines — the surface can never drift from what the log
    # says. Optional: bare callers keep the pure behavior.
    if controller is not None:
        try:
            controller.record_observer_decision(device, intent, active=active)
        except Exception:  # noqa: BLE001 — the surface must never break the seam
            pass
    # Deliberately NOTHING is mutated here — not even the surplus debounce timer
    # (the H2 reset in the actuating path). Observer is a pure shadow: each cycle
    # independently says "given reality now, I would do X". (Belief-sync via
    # reconcile_all at update()'s top is separate and permitted — see there.)
    observed = device.get_current_consumption() if active else 0.0
    name = getattr(device, "name", None) or getattr(device, "device_id", "?")
    # (#762) transition-gated: a WOULD that has not changed is not news —
    # ~950 INFO lines/day on .175 for decisions holding perfectly still.
    # One key per device: ACTIVATE→ADJUST→DEACTIVATE edges all log.
    _key = f"observer:{getattr(device, 'device_id', name)}"
    if intent.on and not active:
        log_on_change(_LOGGER, _key, logging.INFO,
                      "OBSERVER · WOULD ACTIVATE %s @ %.0fW [source=%s] — %s",
                      name, intent.power_w, intent.source, intent.reason)
    elif not intent.on and active:
        log_on_change(_LOGGER, _key, logging.INFO,
                      "OBSERVER · WOULD DEACTIVATE %s — %s", name, intent.reason)
    elif intent.on and active and intent.source is not None:
        log_on_change(_LOGGER, _key, logging.INFO,
                      "OBSERVER · WOULD ADJUST %s → %.0fW [source=%s] — %s",
                      name, intent.power_w, intent.source, intent.reason)
    # else: idle, or on-but-not-SEM-driven (source is None) → no command to log.
    return observed


async def _activate_owned(device: "ControllableDevice", watts: float) -> float:
    """Actuate ON **and** record ownership — the single choke point.

    Ownership follows from SEM having actuated the device, so it belongs next to
    the actuation, not in each activation pass. Pre-fix it was recorded at the
    call site and four of the five passes forgot it (Tier-2 overnight battery,
    cheap-hours grid, ScheduleDevice deadline) — no ``activate()`` implementation
    sets ``_sem_owned`` either, so those loads ran with ownership False while SEM
    was driving them. The mode→Off release (:func:`compute_load_intent` and the
    force-expiry pass) is gated on exactly that flag, so setting Mode → Off left
    the load running forever: bug class 17 again, instance 5. Caught live on PROD
    2026-07-26 — a towel heater started by the Tier-2 pass kept heating 5 minutes
    after Mode → Off. Guarded by ``tests/test_load_ownership_choke_point.py``.
    """
    consumed = await device.activate(watts)
    if consumed > 0:
        device.record_activated()
    return consumed


async def _deactivate_owned(device: "ControllableDevice") -> bool:
    """Actuate OFF **and** release ownership. Returns True if it stopped.

    Anti-flicker can refuse the stop, so ownership is only released once the
    device actually reports idle.
    """
    await device.deactivate()
    if device.is_active:
        return False
    device.record_deactivated()
    return True


async def reconcile_load(device: "ControllableDevice", intent: LoadIntent,
                         *, observer: bool = False, controller=None) -> float:
    """(desired-state, phase 2) The EXECUTION layer: make the load's reality match
    the management layer's ``intent``. This is the SINGLE place a load is actuated.

    Anti-cycle lives here (``can_activate`` / ``can_deactivate`` own min_on /
    min_off), so a stop can lag the intent by the anti-flicker window — but the
    *decision* has no separate stop path to forget. Returns the load's resulting
    consumption (for the caller's surplus accounting).

    ``observer=True`` cuts the trigger: layers 1+2 still ran for real, but the
    actuator only logs what it would do (see :func:`_reconcile_load_observe`).
    """
    active = bool(getattr(device, "is_active", False))

    if observer:
        return _reconcile_load_observe(device, intent, active,
                                       controller=controller)

    if intent.on and not active:
        if not device.can_activate():
            return 0.0
        consumed = await _activate_owned(device, intent.power_w)
        if consumed > 0:
            device.reset_surplus_timer()
            _apply_source_markers(device, intent)
        return consumed

    if not intent.on and active:
        if not device.can_deactivate():
            return device.get_current_consumption()   # anti-flicker holds it on
        if await _deactivate_owned(device):
            _clear_source_markers(device)
            return 0.0
        return device.get_current_consumption()

    if intent.on and active:
        # source is None ⇒ "not SEM-driven" (off / peak-only kept as observed):
        # never actuate it — SEM only re-tunes loads it is actually driving.
        if intent.source is None:
            return device.get_current_consumption()
        consumed = await device.adjust_power(intent.power_w)
        _apply_source_markers(device, intent)
        return consumed

    # not intent.on and not active — idle. Reset the sustained-surplus debounce
    # so a cloud-shadow gap restarts the activation delay, matching the old
    # activation pass's reset_surplus_timer (ruflo H2). Harmless for off/peak
    # loads (their timer is never consulted).
    device.reset_surplus_timer()
    return 0.0


@dataclass
class SurplusAllocation:
    """Allocation result for a single device."""
    device_id: str
    device_name: str
    priority: int
    allocated_watts: float
    actual_consumption_watts: float
    state: str


@dataclass
class SurplusAllocationData:
    """Complete surplus allocation state."""
    total_surplus_w: float = 0.0
    distributable_surplus_w: float = 0.0
    regulation_offset_w: float = DEFAULT_REGULATION_OFFSET
    allocated_w: float = 0.0
    unallocated_w: float = 0.0
    active_devices: int = 0
    total_devices: int = 0
    allocations: List[SurplusAllocation] = field(default_factory=list)
    last_update: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "surplus_total_w": round(self.total_surplus_w, 1),
            "surplus_distributable_w": round(self.distributable_surplus_w, 1),
            "surplus_regulation_offset_w": self.regulation_offset_w,
            "surplus_allocated_w": round(self.allocated_w, 1),
            "surplus_unallocated_w": round(self.unallocated_w, 1),
            "surplus_active_devices": self.active_devices,
            "surplus_total_devices": self.total_devices,
            "surplus_allocations": [
                {
                    "device": a.device_name,
                    "priority": a.priority,
                    "allocated_w": round(a.allocated_watts, 1),
                    "consuming_w": round(a.actual_consumption_watts, 1),
                    "state": a.state,
                }
                for a in self.allocations
            ],
            "surplus_last_update": self.last_update.isoformat() if self.last_update else None,
        }


async def deactivate_devices(devices, reason: str = "teardown") -> int:
    """Command every active device in ``devices`` back to normal (#656).

    Module-level so the teardown path can use it after the registry has been
    detached — at removal time there is no controller left to ask, only the
    devices themselves.

    Deliberately takes the RAW device collection rather than
    ``get_devices_sorted()``: that view hides ``is_enabled=False`` and
    ``managed_externally`` devices, both of which can be latched ON right now,
    and a teardown that skips them leaves exactly the strand this exists to
    prevent. Lowest priority first, so the log reads like a normal shed.

    Best-effort: one device failing must not abort the rest. The alternative
    to swallowing here is an unattended heating device left commanded on by an
    integration on its way out.
    """
    devices = sorted(
        devices, key=lambda d: getattr(d, "priority", 99) or 99, reverse=True,
    )
    stopped = 0
    for device in devices:
        if not getattr(device, "is_active", False):
            continue
        try:
            await _deactivate_owned(device)
            stopped += 1
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "Could not deactivate %s during %s (continuing): %s",
                getattr(device, "device_id", device), reason, e,
            )
    _LOGGER.info(
        "Deactivated %d of %d surplus-controlled devices (%s)",
        stopped, len(devices), reason,
    )
    return stopped


class SurplusController:
    """Controls surplus power distribution across multiple devices.

    Implements priority-based surplus routing:
    - Devices are sorted by priority (1=highest)
    - Each device has a minimum power threshold
    - Variable-power devices get proportional surplus
    - On/off devices get their full rated power or nothing
    - LIFO deactivation when surplus drops
    """

    def publish_observer_decision(self, *, key: str, name: str, action: str,
                                  power_w: float = 0.0, source=None,
                                  reason: str = "", kind: str = "load",
                                  **extra) -> None:
        """(#764) One WOULD decision, one surface — for EVERY family.

        Loads, chargers and batteries all land in the same
        ``observer_decisions`` map (keyed ``<device_id>`` / ``ev:<cid>`` /
        ``battery:<bid>``, with ``kind`` naming the family) so a simulation
        reads ONE attribute and gets the whole shadow cycle. The map always
        carries the CURRENT would-state — a fresh reader needs no history.
        The bus event fires only on decision TRANSITIONS, judged on the
        digit-stripped action/source/reason (the #762 rule: a wobbling watt
        number is not an edge).
        """
        import re as _re
        payload = {
            "device_id": key,
            "kind": kind,
            "name": name or key,
            "action": action,
            "power_w": float(power_w or 0.0),
            "source": source,
            "reason": reason,
        }
        payload.update(extra)
        self.observer_decisions[key] = payload
        edge_key = _re.sub(r"-?\d+(?:[.,]\d+)?", "#",
                           f"{action}|{source}|{reason}")
        if self._observer_decision_keys.get(key) == edge_key:
            return
        self._observer_decision_keys[key] = edge_key
        try:
            self.hass.bus.async_fire(
                "solar_energy_management_observer_decision", dict(payload))
        except Exception:  # noqa: BLE001 — the event must never break the seam
            pass

    def record_observer_decision(self, device, intent: "LoadIntent",
                                 *, active: bool) -> None:
        """(#764) A load's WOULD decision, mapped onto the shared surface.

        ``hold`` means no command would be sent — the device is already
        where SEM wants it.
        """
        if intent.on and not active:
            action = "activate"
        elif not intent.on and active:
            action = "deactivate"
        elif intent.on and active and intent.source is not None:
            action = "adjust"
        else:
            action = "hold"
        did = str(getattr(device, "device_id", "") or "")
        self.publish_observer_decision(
            key=did,
            name=str(getattr(device, "name", "") or did),
            action=action,
            power_w=float(intent.power_w or 0.0),
            source=intent.source,
            reason=intent.reason,
            kind="load",
        )

    def __init__(
        self,
        hass: HomeAssistant,
        regulation_offset: float = DEFAULT_REGULATION_OFFSET,
    ):
        self.hass = hass
        self.regulation_offset = regulation_offset
        # (#764) Observer mode's WOULD decisions, published as a standard
        # surface: this map rides the observer-mode switch's attributes
        # (a fresh session reads the current would-state instantly) and a
        # bus event fires on every decision TRANSITION — so a simulation
        # bridge is a five-line HA automation, not an SSH log scraper.
        self.observer_decisions: Dict[str, dict] = {}
        self._observer_decision_keys: Dict[str, str] = {}
        self.max_export_w: float = 0  # 0 = no limit. E.g., 10000 for 10kW export limit
        self._devices: Dict[str, ControllableDevice] = {}
        self._allocation_data = SurplusAllocationData()
        self._price_responsive_mode = False
        self._last_surplus = 0.0
        self._smoothed_surplus: Optional[float] = None
        # (#620) battery context, refreshed each update(); inert defaults so a
        # helper called before the first update() is a no-op.
        self._batt_soc: Optional[float] = None
        self._batt_buffer_soc: float = 100.0
        self._batt_reserve_soc: float = 100.0
        self._batt_assist_budget_w: float = 0.0
        self._tier1_budget_left: float = 0.0
        # (arc Phase 4) last raw surplus samples for the median-of-3 pre-filter
        self._surplus_samples: List[float] = []
        # (desired-state, phase 3) When True, update() delegates to the single
        # declarative decision + reconcile path instead of the 7 imperative
        # passes. Default OFF — the passes stay authoritative until a parity
        # corpus + a real-hardware soak prove the new path identical.
        self._use_desired_state: bool = False
        # (#638 G4) per-cycle window verdicts from the joint energy plan:
        # device_id → True (inside its planned block) / False (planned
        # elsewhere tonight — don't start now). Absent = the plan has no say.
        # Stamped by update() from the coordinator; empty when actuation is
        # off or no trusted plan exists.
        self._plan_windows: dict = {}

    @property
    def allocation_data(self) -> SurplusAllocationData:
        """Return current allocation state."""
        return self._allocation_data

    @property
    def price_responsive_mode(self) -> bool:
        return self._price_responsive_mode

    @price_responsive_mode.setter
    def price_responsive_mode(self, value: bool) -> None:
        self._price_responsive_mode = value

    # ``set_anticipated_surplus`` lived here until #659, together with the
    # ``_anticipated_surplus_w`` / ``_anticipated_deadline`` fields. It was
    # the #106 "pre-warm devices before the EV taper completes" promise, and
    # it was dead on both ends: nothing ever called it, and nothing ever read
    # the two fields it set. The docstring described behaviour ("will factor
    # this in 2 min before the deadline") that no code implemented — the kind
    # of spec-vs-reality gap that reads as a working feature to the next
    # person who greps for it.
    #
    # If pre-warming is wanted, it belongs in the surplus computation itself
    # (``_compute_surplus`` / the desired-state ``compute_load_intent`` path),
    # not in a setter that hopes someone downstream looks.

    # ``distribute_ev_budget`` lived here until #651: a priority cascade
    # that split the fleet EV budget across chargers, with its own 60 s /
    # 500 W reallocation hysteresis in ``_ev_last_realloc_time`` /
    # ``_ev_prev_allocation``. It ran every solar cycle and its result
    # reached exactly one place — ``PerChargerContext.budget_w`` — which
    # nothing read. Two allocators for one concept, one of them invisible:
    # a contributor fixing a multi-charger allocation bug would have edited
    # this one, watched its unit tests pass, and changed nothing on the
    # hardware. The surviving allocator is ``decide`` subtracting
    # ``fleet.solar_committed_w``, accumulated per charger in the
    # coordinator's priority loop from each charger's actual decision.

    # Volatile per-device CONTROL state that must survive a device-object
    # rebuild (config edit / rediscovery re-registers a FRESH object for the
    # same device_id). Lost markers are how the deficit-LIFO killed a running
    # Tier-2 load 23 min early on PROD (2026-07-22: rediscovery at 22:15:14
    # wiped Heizband's _batt_overnight_forced; the LIFO exemption no longer
    # matched). Bug class 14 (rebuilt device loses accrued state) × #620.
    _VOLATILE_CONTROL_FIELDS = (
        "_offpeak_forced", "_offpeak_forced_date",
        "_batt_overnight_forced", "_batt_overnight_forced_date",
        "_last_activated", "_last_deactivated",   # anti-cycle windows
        "_observed_off_since", "_external_off_until",
        "_surplus_since",                          # activation debounce
    )
    # _sem_owned is transplanted separately: only from an ACTIVE old object —
    # a stale False (reconciler cleared it while the entity flickered) must not
    # override adopt_if_running's re-own on the fresh object (ruflo M).

    def register_device(self, device: ControllableDevice) -> None:
        """Register a device for surplus control.

        Replacing an existing registration (same ``device_id``) transplants the
        volatile control state onto the new object — a rebuild must never reset
        force markers, anti-cycle timing, or ownership of a RUNNING load.
        """
        old = self._devices.get(device.device_id)
        if old is not None and old is not device:
            for f in self._VOLATILE_CONTROL_FIELDS:
                if hasattr(old, f) and hasattr(device, f):
                    setattr(device, f, getattr(old, f))
            # Belief: if the old object was ACTIVE and the fresh one defaults to
            # idle, carry the active state — the physical load is still on and
            # SEM is still driving it. Ownership travels with an active belief
            # only (see _VOLATILE_CONTROL_FIELDS note).
            if old.is_active:
                if not device.is_active:
                    device._status.state = old._status.state
                if hasattr(old, "_sem_owned"):
                    device._sem_owned = old._sem_owned
            if (getattr(old, "_offpeak_forced", False)
                    or getattr(old, "_batt_overnight_forced", False)):
                _LOGGER.info(
                    "Re-register %s: transplanted volatile control state "
                    "(offpeak=%s, overnight_batt=%s, active=%s)",
                    device.device_id,
                    getattr(old, "_offpeak_forced", False),
                    getattr(old, "_batt_overnight_forced", False),
                    device.is_active,
                )
        self._devices[device.device_id] = device
        device._controller = self  # Allow device to look up dependencies (#122)
        depends = getattr(device, 'depends_on', None) or "none"
        _LOGGER.info(
            "Registered device: %s (priority=%d, min=%dW, type=%s, depends_on=%s)",
            device.name, device.priority, device.min_power_threshold,
            device.device_type.value, depends,
        )

    def get_dependents(self, device_id: str) -> list:
        """Get all devices that depend on the given device (#122)."""
        return [d for d in self._devices.values()
                if device_id in getattr(d, 'depends_on', [])]

    # ``validate_dependencies`` lived here until #662. It was a cycle
    # detector with no production caller (only tests), and its walk
    # hard-coded ``dep_list[0]`` — so for a device requiring [a, b] with the
    # loop through ``b`` it followed the ``a``-chain, found nothing and
    # reported clean. A validator that can't see half the graph and that
    # nothing calls is not a safety net; it is a second, weaker
    # implementation of a concept the registry already owns correctly.
    #
    # Cycles are now prevented where they are created, not reported after
    # the fact: DeviceRegistry._dependency_would_cycle walks ALL parents
    # across BOTH persisted stores and rejects the write, on every path
    # (UI select, set_device_property, register_surplus_device), plus a
    # load-time sanitize for stores written before the guard existed.

    def unregister_device(self, device_id: str) -> None:
        """Remove a device from surplus control."""
        if device_id in self._devices:
            del self._devices[device_id]
            _LOGGER.info("Unregistered device: %s", device_id)

    def clear_devices(self) -> None:
        """Drop every registered device.

        Called from ``async_unload_entry`` so a HA-side reload doesn't
        leak the prior cycle's device registrations into the next setup.
        Pre-fix, reloads left the registered EV charger / heat pump /
        switch devices in ``self._devices`` — the new setup re-registered
        them on top, causing each reload to grow the dispatch list.
        """
        if self._devices:
            count = len(self._devices)
            self._devices.clear()
            _LOGGER.info("Cleared %d registered devices on unload", count)

    def detach_devices(self) -> List[ControllableDevice]:
        """Clear the registry and hand the devices back to the caller (#656).

        ``clear_devices()`` on its own is what stranded loads: unload dropped
        the references to devices SEM had switched ON, and nothing was left
        that could turn them off. Teardown needs both halves — the registry
        emptied (so a reload can't leak the prior cycle's registrations) AND
        something still holding the actuators, in case this unload turns out
        to be a removal rather than a reload.
        """
        devices = list(self._devices.values())
        self.clear_devices()
        return devices

    def get_device(self, device_id: str) -> Optional[ControllableDevice]:
        """Get a registered device by ID."""
        return self._devices.get(device_id)

    def get_devices_sorted(self) -> List[ControllableDevice]:
        """Get all devices sorted by priority (1=highest).

        Devices with managed_externally=True are excluded (e.g., EV charger
        during night mode when the coordinator manages it directly).
        """
        return sorted(
            [d for d in self._devices.values()
             if d.is_enabled and not d.managed_externally],
            key=lambda d: d.priority,
        )

    def active_surplus_draw_w(self) -> float:
        """Sum the current draw of the surplus devices this controller
        has activated (#508 W7).

        The coordinator builds a *feedback-free* true house surplus as
        ``grid_export + active_surplus_draw_w()``. Without the addback,
        every device the controller turns on shrinks the grid export it
        reads next cycle, so the surplus signal would chase its own tail
        and the device would oscillate. Adding back the controller's own
        active draw makes the input the surplus that WOULD exist if its
        devices were off — the stable quantity to allocate from.

        Externally-managed devices (the EV, driven by the decide/actuate
        path) are excluded — their draw is already reflected in grid
        export and must not be re-credited here.
        """
        return sum(
            d.get_current_consumption()
            for d in self.get_devices_sorted()
            if d.is_active
        )

    def grid_funded_draw_w(self) -> float:
        """(#620) Total draw of loads currently running on the cheap-hours GRID
        top-up (``_offpeak_forced``). Fed into ``BatteryView.grid_funded_load_w``
        so the battery discharge limit excludes them — the grid, not the
        battery, funds a "Finish overnight from: Grid" load. Tier-2
        (``_batt_overnight_forced``) loads are deliberately NOT counted: they
        run off the battery by design."""
        return sum(
            float(d.get_current_consumption() or 0.0)
            for d in self._devices.values()
            if d.is_active and getattr(d, "_offpeak_forced", False)
        )

    def _desired_intents(self, devices, *, remaining_surplus, reclaim_w,
                         battery_priority, price_level,
                         peak_freeze, peak_shed, peak_shed_all):
        """(desired-state, phase 3) The management-layer decision for the whole
        load set: the priority walk → one ``LoadIntent`` per device. Pure of
        actuation (``reconcile_load`` applies them); the shared cycle context
        (``self._batt_*`` / ``self._tier1_budget_left``) is already stamped by
        ``update()``. This is what REPLACES the 7 imperative passes."""
        price_is_cheap = price_level in ("cheap", "very_cheap", "negative")
        soc_above = (self._batt_soc is not None
                     and self._batt_soc > self._batt_reserve_soc)

        # Peak-shed targets: reverse priority; EMERGENCY sheds all, SHEDDING one.
        shed = set()
        if peak_shed:
            for d in reversed(devices):
                if d.control_mode == DeviceControlMode.SURPLUS and d.is_active:
                    shed.add(d.device_id)
                    if not peak_shed_all:
                        break

        remaining = float(remaining_surplus)
        reclaim_handed = False
        intents = {}
        for device in devices:
            # (#576) hand the reclaim back at the battery's slot
            if (not reclaim_handed and battery_priority is not None
                    and reclaim_w > 0 and device.priority >= battery_priority):
                remaining = max(0.0, remaining - reclaim_w)
                reclaim_handed = True
            tier1 = self._tier1_headroom_w(device)
            intent = compute_load_intent(
                device, remaining_surplus_w=remaining, tier1_headroom_w=tier1,
                price_is_cheap=price_is_cheap, peak_freeze=peak_freeze,
                is_night=getattr(self, "_is_night_cycle", True),
                is_shed_target=device.device_id in shed, soc_above_reserve=soc_above,
                # (#638 G4) the joint plan's per-device window verdict this
                # cycle; absent from the dict = the plan has no say.
                plan=self._plan_windows.get(device.device_id) or NO_OPINION)
            intents[device.device_id] = intent
            # solar/tier1-driven loads consume surplus for lower-priority ones
            if intent.on and intent.source in ("solar", "tier1_battery"):
                if intent.source == "tier1_battery":
                    batt = max(0.0, intent.power_w - max(0.0, remaining))
                    self._tier1_budget_left = max(0.0, self._tier1_budget_left - batt)
                remaining = max(0.0, remaining - intent.power_w)
        return intents

    async def _finish_via_desired_state(self, devices, *, remaining_surplus,
            reclaim_w, battery_priority, price_level, peak_state, peak_freeze,
            peak_shed, peak_shed_all, distributable, available_power_w,
            observer=False):
        """(desired-state, phase 3) Compute intents, reconcile every load (the
        single actuator), and assemble the same ``SurplusAllocationData`` the
        imperative ``update()`` returns.

        ``observer=True`` runs the exact same decision, but the reconcile step
        only logs what it would command — the read-only path for observer mode."""
        intents = self._desired_intents(
            devices, remaining_surplus=remaining_surplus, reclaim_w=reclaim_w,
            battery_priority=battery_priority, price_level=price_level,
            peak_freeze=peak_freeze, peak_shed=peak_shed,
            peak_shed_all=peak_shed_all)
        allocations: List[SurplusAllocation] = []
        active_count = 0
        for device in devices:
            await reconcile_load(device, intents[device.device_id],
                                 observer=observer, controller=self)
            active = bool(device.is_active)
            consumption = device.get_current_consumption() if active else 0.0
            if active:
                active_count += 1
            allocations.append(SurplusAllocation(
                device_id=device.device_id, device_name=device.name,
                priority=device.priority,
                allocated_watts=(device.status.allocated_power_w if active else 0.0),
                actual_consumption_watts=consumption,
                state=DeviceState.ACTIVE.value if active else DeviceState.IDLE.value))
        total_allocated = sum(a.actual_consumption_watts for a in allocations)
        self._allocation_data = SurplusAllocationData(
            total_surplus_w=available_power_w,
            distributable_surplus_w=distributable,
            regulation_offset_w=self.regulation_offset,
            allocated_w=total_allocated,
            unallocated_w=max(0.0, distributable - total_allocated),
            active_devices=active_count, total_devices=len(self._devices),
            allocations=allocations, last_update=datetime.now())
        return self._allocation_data

    async def update(
        self,
        available_power_w: float,
        price_level: Optional[str] = None,
        peak_state: Optional[str] = None,
        reclaim_w: float = 0.0,
        battery_priority: Optional[int] = None,
        # (#620) battery context for the two device battery tiers. Defaults
        # make the whole feature INERT: with no battery data and both
        # per-device flags off (their default), _tier1/_tier2 are no-ops and
        # allocation is byte-identical to pre-#620.
        battery_soc: Optional[float] = None,
        battery_buffer_soc: float = 100.0,
        battery_reserve_soc: float = 100.0,
        battery_assist_budget_w: float = 0.0,
        observer: bool = False,
        is_night: bool = True,
        # (#638 G4) device_id → True/False window verdicts from the joint
        # energy plan; None/empty = no trusted plan → today's behaviour.
        plan_windows: Optional[dict] = None,
    ) -> SurplusAllocationData:
        """Run the surplus allocation algorithm.

        This is called every coordinator update cycle (~10s).

        Args:
            available_power_w: Total available surplus power. Since #508 W7
                the coordinator passes the feedback-free TRUE house surplus
                (grid export + this controller's own active draw), not the
                EV charging budget — heat pump / hot water boost on what the
                house is actually exporting after the EV and battery take
                their share.
            price_level: Current price level (cheap/normal/expensive) for price-responsive mode.
            peak_state: Current ``LoadManagementState`` (#508 W2). When the
                grid-import peak is at risk (WARNING / SHEDDING / EMERGENCY)
                the controller stops ADDING discretionary load, and on
                SHEDDING / EMERGENCY proactively backs its own active
                devices off by reverse priority — so it complements the
                load manager instead of re-activating, next cycle, whatever
                the load manager just shed. ``None`` = no peak awareness
                (legacy behaviour).

        Returns:
            SurplusAllocationData with allocation results.
        """
        # (arc) Reconcile belief vs observed reality BEFORE allocating, so a
        # load that silently dropped off (failed turn_on) or was toggled by the
        # user isn't counted as active / credited runtime this cycle, and SEM
        # doesn't immediately re-fight a manual off. Scoped to on/off loads
        # (switch + climate); EV / heat-pump / setpoint keep their own handling.
        # NB: reconcile_all is belief-sync, not actuation — it corrects SEM's
        # view of reality (is_active, _sem_owned, off-grace) and NEVER issues a
        # service call. It runs in observer mode too (permitted + wanted): on
        # shared hardware the real decision needs accurate belief state.
        from ..devices.base import DeviceType
        from .device_reconciler import reconcile_all
        reconcile_all([
            d for d in self._devices.values()
            if getattr(d, "device_type", None) in (DeviceType.SWITCH, DeviceType.CLIMATE)
        ])

        # #508 W2 — peak posture. WARNING freezes new activation (don't add
        # load while the peak is climbing); SHEDDING/EMERGENCY additionally
        # sheds the controller's own discretionary devices. EMERGENCY sheds
        # all of them at once; SHEDDING sheds gently (one per cycle) so the
        # combined load-manager + surplus back-off doesn't overshoot.
        from ..const import LoadManagementState
        # (#620) stash the battery context for the tier helpers this cycle.
        self._batt_soc = battery_soc
        self._batt_buffer_soc = battery_buffer_soc
        self._batt_reserve_soc = battery_reserve_soc
        self._batt_assist_budget_w = max(0.0, float(battery_assist_budget_w or 0.0))
        # (#633) "Finish overnight from: Battery" is a NIGHT source — the
        # Tier-2 pass and its force-expiry both gate on this cycle flag.
        self._is_night_cycle = bool(is_night)
        # (#638 G4) stamp this cycle's joint-plan window verdicts for the
        # intent path AND the imperative passes below.
        self._plan_windows = dict(plan_windows or {})
        # (#766) Belief follows the switch, every cycle — the per-cycle twin
        # of adopt_if_running. Without it, a switch turned ON outside SEM's
        # own activate() (an external actuator, a user, a box self-start)
        # stays invisible: never seen active, never deactivated, runtime
        # never accrued (the N2 pool ran 00:00→07:50 on an idle belief).
        for _dev in self._devices.values():
            try:
                _sync = getattr(_dev, "sync_belief_to_observation", None)
                if callable(_sync):
                    _sync()
            except Exception:  # noqa: BLE001 — one device never stalls the walk
                continue
        peak_freeze = peak_state in (
            LoadManagementState.WARNING,
            LoadManagementState.SHEDDING,
            LoadManagementState.EMERGENCY,
        )
        peak_shed = peak_state in (
            LoadManagementState.SHEDDING,
            LoadManagementState.EMERGENCY,
        )
        peak_shed_all = peak_state == LoadManagementState.EMERGENCY
        # (arc Phase 4) Median-of-3 pre-filter: a SINGLE-cycle spike/dropout
        # (inverter glitch, sensor blip) still moves the EMA below by 30% of its
        # magnitude — enough to flap a marginal load. The median passes only
        # values seen in ≥2 of the last 3 cycles, so one bad sample never
        # reaches the EMA at all. Real trends (2+ consistent cycles) pass with
        # one cycle of extra latency, which the EMA's own inertia already dwarfs.
        self._surplus_samples.append(available_power_w)
        if len(self._surplus_samples) > 3:
            self._surplus_samples.pop(0)
        if len(self._surplus_samples) == 3:
            filtered_w = sorted(self._surplus_samples)[1]
        else:
            filtered_w = available_power_w  # warm-up (first 2 cycles): raw

        # EMA smoothing to reduce oscillation from cloud transients
        if self._smoothed_surplus is None:
            self._smoothed_surplus = filtered_w
        else:
            self._smoothed_surplus = 0.3 * filtered_w + 0.7 * self._smoothed_surplus

        # Apply regulation offset
        distributable = self._smoothed_surplus - self.regulation_offset
        self._last_surplus = distributable

        # Feed-in/export limitation: add virtual surplus when approaching limit
        if self.max_export_w > 0 and self._smoothed_surplus > self.max_export_w:
            excess_export = self._smoothed_surplus - self.max_export_w
            distributable += excess_export  # Force-route excess to devices

        # Price-responsive adjustments
        if self._price_responsive_mode and price_level:
            distributable = self._apply_price_adjustment(distributable, price_level)

        devices = self.get_devices_sorted()
        allocations: List[SurplusAllocation] = []
        # (#576) The home battery sits at ``battery_priority`` in this walk.
        # ``reclaim_w`` (the power that would charge it) is offered at the TOP;
        # when the walk crosses the battery's slot it is handed back to the
        # battery, so loads ABOVE the battery reclaim it and loads BELOW see
        # only the export surplus. ``max(0, …)`` yields exactly the export
        # surplus the higher-priority loads left unconsumed (see #576 tests).
        remaining_surplus = distributable + max(0.0, reclaim_w)
        _reclaim_handed_back = False
        active_count = 0
        # (#620) Tier-1 running budget — the battery can only supply its assist
        # budget ONCE, not once per device. Decremented as each battery-assist
        # load draws from it, so N loads can't each claim the full budget.
        self._tier1_budget_left = self._batt_assist_budget_w

        # (desired-state) Delegate to the single declarative path when enabled
        # for actuation (``_use_desired_state``) OR whenever we're observing.
        # OBSERVER always takes this path: it's the only one with a single
        # execution seam (``reconcile_load``) that can cut the trigger cleanly —
        # so observer mode runs the FULL real decision against live sensors and
        # merely logs what it would command. No separate ``observe_only`` path.
        if self._use_desired_state or observer:
            return await self._finish_via_desired_state(
                devices, remaining_surplus=remaining_surplus, reclaim_w=reclaim_w,
                battery_priority=battery_priority, price_level=price_level,
                peak_state=peak_state, peak_freeze=peak_freeze,
                peak_shed=peak_shed, peak_shed_all=peak_shed_all,
                distributable=distributable, available_power_w=available_power_w,
                observer=observer,
            )

        # Force expiry: a cheap-hours force ends with its reason (#559 review) —
        # the tariff left the cheap window, OR the day rolled over (the deficit
        # it served was YESTERDAY's — without the date check a device forced
        # into a cheap midnight window would re-fill the NEW day's target from
        # grid all night).
        from ..devices.base import DeviceControlMode
        for device in devices:
            if not device.is_active:
                continue
            # (#703) Staleness is judged against the load's OWN meter day —
            # the sunrise-held boundary its deficit lives on — never the
            # calendar date, which flips at 00:00 mid-top-up and produced a
            # spurious stop/restart flap every midnight.
            device_day = _load_meter_day(device)
            reason = None
            # (class-17 sibling, caught live 2026-07-23) Mode switched to Off
            # while SEM is DRIVING the load: release it — stop once, clear
            # markers/ownership — instead of stranding it running forever
            # (the activation pass just skips OFF devices; nothing else stops
            # them). A user-turned-on load (not _sem_owned) stays untouched:
            # Off means SEM keeps its hands off the user's own choices.
            if (device.control_mode == DeviceControlMode.OFF
                    and getattr(device, "_sem_owned", False)):
                reason = "mode off — releasing SEM-driven load"
            if reason is None and device._offpeak_forced:
                stale = (
                    device._offpeak_forced_date is not None
                    and device._offpeak_forced_date != device_day
                )
                if getattr(device, "top_up_policy", "solar_only") == "solar_only":
                    # (#620) the "Finish overnight from" picker moved off Grid
                    # (top_up_policy → solar_only). A load already running on the
                    # cheap-hours force must STOP, not keep importing until the
                    # window ends — the grid-path sibling of the battery-toggle
                    # fix (caught live on the picker's Off test).
                    reason = "cheap-hours disabled by user"
                elif stale:
                    reason = "cheap-hours force expired (day rollover)"
                elif price_level not in ("cheap", "very_cheap", "negative"):
                    reason = f"tariff now {price_level}"
            # (#620) Tier-2 overnight battery force expiry — its OWN terms: the
            # user turned the "Use battery overnight" toggle OFF, the Reserve
            # floor was crossed (battery must be protected), or the day rolled
            # over. NOT expired by tariff (it isn't tariff-driven). The
            # daily-target-met stop is handled by the goal gate below.
            if reason is None and getattr(device, "_batt_overnight_forced", False):
                soc = self._batt_soc
                _bo_date = getattr(device, "_batt_overnight_forced_date", None)
                if not getattr(device, "battery_eligible_overnight", False):
                    # The toggle gates ACTIVATION, but a load already running off
                    # the battery must also STOP the moment the user disables it —
                    # else it keeps draining until reserve/rollover (caught live
                    # on the Heizband toggle test).
                    reason = "overnight battery disabled by user"
                elif (_bo_date is not None and _bo_date != device_day):
                    reason = "overnight battery force expired (day rollover)"
                elif not getattr(self, "_is_night_cycle", True):
                    # (#633) the overnight window ended — a load still running
                    # off the battery must stop, not ride into the day
                    # (class-17: the gate alone only blocks re-activation).
                    reason = "overnight battery window ended (daytime)"
                elif soc is not None and soc <= self._batt_reserve_soc:
                    reason = "overnight battery force ended (reserve SoC reached)"
            if reason:
                if await _deactivate_owned(device):
                    device._offpeak_forced = False
                    device._offpeak_forced_date = None
                    device._batt_overnight_forced = False
                    device._batt_overnight_forced_date = None
                    _LOGGER.info(
                        "Force ended for %s (%s)", device.name, reason,
                    )
                else:
                    _LOGGER.debug(
                        "Force-end of %s blocked by anti-flicker", device.name,
                    )

        # Activation pass: iterate by priority, activate eligible devices
        # Only devices in "surplus" mode are candidates for activation (#49).
        # Devices in "peak_only" mode are tracked but never proactively turned on.
        # Devices in "off" mode are skipped entirely.
        for device in devices:
            # (#576) Cross the home battery's slot: hand the reclaim back so
            # every load from here down (lower priority than the battery) sees
            # only the export surplus and the battery charges first.
            if (not _reclaim_handed_back and battery_priority is not None
                    and reclaim_w > 0 and device.priority >= battery_priority):
                remaining_surplus = max(0.0, remaining_surplus - reclaim_w)
                _reclaim_handed_back = True
            # Skip devices in "off" mode — SEM never touches these
            if device.control_mode == DeviceControlMode.OFF:
                continue

            # (#559) Goal gates — a device that is DONE for the day (its
            # daily max cap reached, or the external stop condition like the
            # car's SOC target) is stopped and stays off until the day rolls
            # over. Only SURPLUS-mode devices: peak_only devices are
            # user-managed, SEM never proactively stops them.
            #
            # Ordering note (#688): the force-expiry pass above has already
            # run, so a device whose ``_batt_overnight_forced`` /
            # ``_offpeak_forced`` marker was cleared there (day rollover,
            # night ended) was deactivated by that pass. Anything still
            # carrying a marker HERE is a live PAID run — exactly what the
            # floor clause below must end, because a marked device is exempt
            # from the deficit LIFO and nothing else would ever stop it.
            if device.control_mode == DeviceControlMode.SURPLUS:
                done_reason = None
                if device.daily_max_runtime_reached:
                    # (#620) the hard cap must STOP a running device, not just
                    # block re-activation — otherwise a load already on when it
                    # crosses the cap keeps running past it (caught live on the
                    # Heizband PROD test). The cap overrides the min deficit.
                    done_reason = "daily max runtime cap reached"
                elif ((_pv := self._plan_windows.get(device.device_id)) is not None
                        and getattr(_pv, "hold", False)
                        and (device._offpeak_forced
                             or getattr(device, "_batt_overnight_forced", False))):
                    # (#638 Stage 3) the plan's window closed while a paid run
                    # was on — the hold is only raised while the remaining
                    # blocks can still deliver the deficit (load_verdict), so
                    # cutting here banks the energy for the planned block.
                    # Imperative twin of compute_load_intent clause 2b: PROD
                    # runs THESE passes, and a stop that lives only in the
                    # desired-state path is a stop that never happens.
                    done_reason = getattr(_pv, "reason", "") or \
                        "joint energy plan: window closed"
                elif (device.daily_targets_met
                        and (device._offpeak_forced
                             or getattr(device, "_batt_overnight_forced", False))):
                    # (#688) The floor ends the PAID run, not the load. A
                    # Tier-2 / cheap-grid device is EXEMPT from the deficit
                    # LIFO (it runs without surplus by design), so nothing else
                    # would ever end it — it would drain the battery or buy
                    # grid past its own target all night (class 18). A load
                    # riding free surplus is left alone: it may run on up to
                    # the Max cap, which is what the slider promises (#245
                    # EV floor/ceiling contract).
                    done_reason = "daily target met — ending battery/grid top-up"
                elif device.stop_condition_met:
                    done_reason = (
                        f"stop condition met ({device.stop_entity} >= "
                        f"{device.stop_at:g})"
                    )
                if done_reason:
                    if device.is_active and device.can_deactivate():
                        if await _deactivate_owned(device):
                            device._offpeak_forced = False
                            device._offpeak_forced_date = None
                            # (#620) done-for-the-day also ends any Tier-2
                            # overnight force — otherwise the marker leaks until
                            # day rollover and the LIFO exemption keeps shielding
                            # an already-finished device.
                            device._batt_overnight_forced = False
                            device._batt_overnight_forced_date = None
                            _LOGGER.info(
                                "%s: %s — deactivated for the rest of the day",
                                device.name, done_reason,
                            )
                    elif device.is_active:
                        _LOGGER.debug(
                            "%s: %s — deactivation waiting for anti-flicker",
                            device.name, done_reason,
                        )
                    allocations.append(SurplusAllocation(
                        device_id=device.device_id,
                        device_name=device.name,
                        priority=device.priority,
                        allocated_watts=0.0,
                        actual_consumption_watts=device.get_current_consumption() if device.is_active else 0.0,
                        state=DeviceState.ACTIVE.value if device.is_active else DeviceState.IDLE.value,
                    ))
                    continue

            # (#620) Tier 1 — daytime battery assist. A "Solar + battery"
            # device (battery_assist_enabled) sees the raw surplus PLUS the
            # battery-assist budget, but ONLY while the battery is above the
            # Buffer SoC — mirrors the EV Solar Gate (#537/#545): the battery
            # tops the device up out of the surplus-above-buffer it would
            # otherwise export, never below the buffer. Off-flag / below-buffer
            # → headroom is 0 and this is identical to pre-#620.
            effective_surplus = remaining_surplus + self._tier1_headroom_w(device)
            if effective_surplus >= device.min_power_threshold and not device.is_active:
                # Only activate if device is in "surplus" mode
                if device.control_mode != DeviceControlMode.SURPLUS:
                    continue  # peak_only: never proactively turn on
                if peak_freeze:
                    continue  # #508 W2: don't add load while peak is at risk
                if device.can_activate():
                    consumed = await _activate_owned(device, remaining_surplus)
                    assist = 0.0
                    if consumed > 0:
                        device.reset_surplus_timer()
                        # (#620) if the battery covered a shortfall for this
                        # assist device, subtract that from the running budget
                        # — capped by the actual headroom (enabled + above
                        # buffer + budget left), which is 0 for a plain load.
                        # (#688) Only the solar-funded remainder leaves the
                        # pool: debiting the battery's share too made the
                        # deficit LIFO below read it as a shortfall and kill
                        # the assist load the same cycle it activated.
                        headroom = self._tier1_headroom_w(device)
                        if headroom > 0:
                            shortfall = max(0.0, consumed - max(0.0, remaining_surplus))
                            assist = min(headroom, shortfall)
                            self._tier1_budget_left = max(
                                0.0, self._tier1_budget_left - assist)
                    remaining_surplus -= max(0.0, consumed - assist)
                    if consumed > 0:
                        active_count += 1

            elif not device.is_active and remaining_surplus < device.min_power_threshold:
                device.reset_surplus_timer()

            elif device.is_active:
                # Already active — adjust power level (applies to all modes)
                old_consumption = device.get_current_consumption()
                consumed = await device.adjust_power(remaining_surplus + old_consumption)
                # (#688) Debit the FULL draw, not just its change. The pool was
                # credited with every active device's draw (the feedback-free
                # add-back), so leaving the draw in after walking past the
                # device over-funds every lower-priority load by exactly that
                # amount — and, because the solar bound (#620) floors the pool
                # at 0, it kept ``remaining_surplus`` above the deficit-LIFO
                # trigger forever: a load that lost its surplus was never
                # stopped and ran to its Max cap on grid/battery (@onkelfu's
                # pool pump). The LIFO has always credited a shed device's
                # draw BACK — proof the walk was meant to debit it. Tier-1
                # battery assist covers its share of a shortfall first (only
                # the solar-funded remainder leaves the pool, mirroring the
                # activation branch); ``_tier1_headroom_w`` is 0 past the
                # daily floor, so a past-floor run is solar-funded only.
                assist = 0.0
                if consumed > 0:
                    headroom = self._tier1_headroom_w(device)
                    if headroom > 0:
                        shortfall = max(0.0, consumed - max(0.0, remaining_surplus))
                        assist = min(headroom, shortfall)
                        self._tier1_budget_left = max(
                            0.0, self._tier1_budget_left - assist)
                remaining_surplus -= max(0.0, consumed - assist)
                active_count += 1

            allocations.append(SurplusAllocation(
                device_id=device.device_id,
                device_name=device.name,
                priority=device.priority,
                allocated_watts=device.status.allocated_power_w,
                actual_consumption_watts=device.get_current_consumption(),
                state=device.status.state.value,
            ))

        # Deactivation pass (reverse priority — LIFO): if surplus is negative,
        # deactivate lowest-priority active devices first
        if remaining_surplus < -DEFAULT_MIN_SURPLUS_CHANGE:
            for device in reversed(devices):
                if remaining_surplus >= 0:
                    break
                # (#688) Only SURPLUS-mode loads are the LIFO's to stop —
                # peak_only and Off are user-managed (SEM never proactively
                # turns them off; same gate the peak-shed pass carries, and
                # what the desired-state twin's "user-managed" intents pin).
                # Latent before: the dead trigger meant the missing gate
                # never fired on anything.
                if device.control_mode != DeviceControlMode.SURPLUS:
                    continue
                # (#559) off-peak-forced devices run WITHOUT surplus by
                # design — the force-expiry section and the peak shed pass
                # own their lifecycle; the deficit LIFO must not flap them off.
                # (#620) same for a Tier-2 overnight-battery forced device: it
                # runs off the battery by design and is only ended by its OWN
                # terms (reserve SoC / day rollover), never by the deficit LIFO.
                if device._offpeak_forced or getattr(
                        device, "_batt_overnight_forced", False):
                    continue
                if device.is_active and device.can_deactivate():
                    consumption = device.get_current_consumption()
                    if await _deactivate_owned(device):
                        remaining_surplus += consumption
                        active_count -= 1
                        _LOGGER.info(
                            "Deactivated %s (priority %d) to recover %.0fW",
                            device.name, device.priority, consumption,
                        )
                        # Cascade: deactivate dependents (#122)
                        for dep in self.get_dependents(device.device_id):
                            if dep.is_active and dep.can_deactivate():
                                dep_consumption = dep.get_current_consumption()
                                if await _deactivate_owned(dep):
                                    remaining_surplus += dep_consumption
                                    active_count -= 1
                                    _LOGGER.info(
                                        "Cascade deactivated %s (depends on %s)",
                                        dep.name, device.name,
                        )
                        # Update allocation
                        for a in allocations:
                            if a.device_id == device.device_id:
                                a.allocated_watts = 0.0
                                a.actual_consumption_watts = 0.0
                                a.state = DeviceState.IDLE.value
                    else:
                        _LOGGER.debug(
                            "Deactivation of %s blocked by anti-flicker",
                            device.name,
                        )

        # #508 W2 — peak shed pass. On SHEDDING/EMERGENCY, back the
        # controller's own active discretionary (SURPLUS-mode) devices off
        # by reverse priority. EMERGENCY sheds every one this cycle;
        # SHEDDING sheds one per cycle so the load-manager + surplus
        # back-off don't overshoot together. Externally-managed devices
        # (the EV) are already excluded by ``get_devices_sorted``; the load
        # manager owns the EV's peak shedding via ``shed_priority`` (#470).
        # (#620) A Tier-2 overnight-battery device is NOT exempt here: the peak
        # limit is a HARD grid ceiling that overrides the battery tiers. Shedding
        # it relieves grid import; once peak clears the Tier-2 pass re-activates
        # it. We clear its force marker so the shed device carries no stale state.
        if peak_shed:
            for device in reversed(devices):
                if device.control_mode != DeviceControlMode.SURPLUS:
                    continue
                if not device.is_active or not device.can_deactivate():
                    continue
                consumption = device.get_current_consumption()
                if await _deactivate_owned(device):
                    device._batt_overnight_forced = False
                    device._batt_overnight_forced_date = None
                    active_count = max(0, active_count - 1)
                    remaining_surplus += consumption
                    _LOGGER.info(
                        "Peak %s: shed %s (priority %d) to relieve %.0fW",
                        peak_state, device.name, device.priority, consumption,
                    )
                    for a in allocations:
                        if a.device_id == device.device_id:
                            a.allocated_watts = 0.0
                            a.actual_consumption_watts = 0.0
                            a.state = DeviceState.IDLE.value
                    if not peak_shed_all:
                        break  # SHEDDING: gentle, one device per cycle
                else:
                    _LOGGER.debug(
                        "Peak shed of %s blocked by anti-flicker", device.name,
                    )

        # Check for scheduled devices that must start (deadline approaching).
        # #508 W2: deliberately NOT gated on peak_freeze — a deadline is a
        # hard commitment that must run regardless of peak posture (like a
        # critical device), and the one-cycle import is bounded by
        # rated_power. Do not add a peak gate here.
        from ..devices.base import ScheduleDevice
        for device in devices:
            if isinstance(device, ScheduleDevice) and device.is_deadline_approaching and not device.is_active:
                consumed = await _activate_owned(device, device.rated_power)
                if consumed > 0:
                    active_count += 1
                    remaining_surplus -= consumed
                    for a in allocations:
                        if a.device_id == device.device_id:
                            a.allocated_watts = consumed
                            a.actual_consumption_watts = consumed
                            a.state = DeviceState.ACTIVE.value
                _LOGGER.warning(
                    "Force-starting %s due to deadline (%.0fW)",
                    device.name, consumed,
                )

        # Off-peak activation pass: force-activate devices with runtime deficit
        # Only for "surplus" mode devices — off-peak is a form of proactive activation (#49).
        # #508 W2: suppressed while the peak is at risk — a cheap-tariff
        # runtime deficit must not push grid import over the limit.
        # (#638 C5) Comfort-banking pass — the imperative twin of the
        # willing+in_block clause in compute_load_intent. PROD runs THESE
        # passes: a run that lives only in the desired-state path is a run
        # that never happens. A WILLING band whose planned comfort block is
        # open banks now; forced rooms stay with the deficit passes.
        if not peak_freeze:
            for device in devices:
                if device.control_mode != DeviceControlMode.SURPLUS:
                    continue
                if device.is_active or device.stop_condition_met:
                    continue
                if getattr(device, "comfort_state", "") != "willing":
                    continue
                _pv = self._plan_windows.get(device.device_id)
                if _pv is None or not getattr(_pv, "in_block", False):
                    continue
                if not device.can_activate():
                    continue
                consumed = await _activate_owned(device, device.min_power_threshold)
                if consumed > 0:
                    device._offpeak_forced = True
                    device._offpeak_forced_date = _load_meter_day(device)
                    active_count += 1
                    remaining_surplus -= consumed
                    _LOGGER.info(
                        "Comfort banking: %s runs in its planned block (%.0fW)",
                        device.name, consumed,
                    )

        if price_level in ("cheap", "very_cheap", "negative") and not peak_freeze:
            for device in devices:
                if device.control_mode != DeviceControlMode.SURPLUS:
                    continue
                # (#559) solar_only devices NEVER grid-force — they accept
                # missing the target on a dark day (logged once per day).
                if device.top_up_policy == "solar_only":
                    continue
                if device.stop_condition_met:
                    continue
                # (#638 G4) the joint plan placed this load's blocks elsewhere
                # tonight — don't start it in THIS cheap hour. Gates the start
                # only; a run already going ends by its own terms (deficit /
                # expiry), matching the plan's min-run quantization.
                _pv = self._plan_windows.get(device.device_id)
                if _pv is not None and getattr(_pv, "hold", _pv is False):
                    continue
                # (arc) Respect can_activate() here too — otherwise a cheap-hours
                # top-up would re-activate a load the user just turned off,
                # bypassing the reconciler's user-respect cooldown (and the
                # device min_off anti-flicker).
                if device.needs_offpeak_activation and device.can_activate():
                    consumed = await _activate_owned(device, device.min_power_threshold)
                    if consumed > 0:
                        device._offpeak_forced = True
                        device._offpeak_forced_date = _load_meter_day(device)
                        active_count += 1
                        remaining_surplus -= consumed
                        # Update or add allocation entry
                        found = False
                        for a in allocations:
                            if a.device_id == device.device_id:
                                a.allocated_watts = consumed
                                a.actual_consumption_watts = consumed
                                a.state = DeviceState.ACTIVE.value
                                found = True
                                break
                        if not found:
                            allocations.append(SurplusAllocation(
                                device_id=device.device_id,
                                device_name=device.name,
                                priority=device.priority,
                                allocated_watts=consumed,
                                actual_consumption_watts=consumed,
                                state=DeviceState.ACTIVE.value,
                            ))
                        _LOGGER.info(
                            "Off-peak forced %s (%.0fW, deficit %.0fs)",
                            device.name, consumed, device.remaining_daily_runtime_sec,
                        )

        # (#620) Tier 2 — overnight battery pass. A device that opted into
        # "Use battery overnight" and still has a runtime deficit may run from
        # the home battery when there is no surplus, PRIORITY-ORDERED, while
        # the battery is above the hard Reserve SoC. Distinct from the cheap-
        # hours off-peak pass (grid-sourced): this spends stored house energy,
        # so it is gated on the explicit opt-in + the Reserve floor, not price.
        # Suppressed under peak risk (same as the off-peak pass). can_activate()
        # enforces the max cap + anti-cycle, so a capped or recently-toggled
        # device is skipped. Inert for every device with the flag off (default).
        if not peak_freeze:
            for device in devices:
                if device.control_mode != DeviceControlMode.SURPLUS:
                    continue
                if device.is_active or device.stop_condition_met:
                    continue
                if not device.needs_offpeak_activation:  # deficit + not capped
                    continue
                if not self._tier2_overnight_eligible(device):
                    continue
                # (#638 G4) same window gate as the cheap-hours pass: the plan
                # may defer a Tier-2 load to a later slot when the battery's
                # shared discharge budget is contested.
                _pv = self._plan_windows.get(device.device_id)
                if _pv is not None and getattr(_pv, "hold", _pv is False):
                    continue
                if not device.can_activate():
                    continue
                consumed = await _activate_owned(device, device.min_power_threshold)
                if consumed > 0:
                    device._batt_overnight_forced = True  # (#620) own marker
                    device._batt_overnight_forced_date = _load_meter_day(device)
                    active_count += 1
                    for a in allocations:
                        if a.device_id == device.device_id:
                            a.allocated_watts = consumed
                            a.actual_consumption_watts = consumed
                            a.state = DeviceState.ACTIVE.value
                            break
                    else:
                        allocations.append(SurplusAllocation(
                            device_id=device.device_id,
                            device_name=device.name,
                            priority=device.priority,
                            allocated_watts=consumed,
                            actual_consumption_watts=consumed,
                            state=DeviceState.ACTIVE.value,
                        ))
                    _LOGGER.info(
                        "#620 Tier 2: %s on battery (%.0fW, deficit %.0fs, "
                        "SoC %.0f%% > reserve %.0f%%)",
                        device.name, consumed, device.remaining_daily_runtime_sec,
                        self._batt_soc or 0.0, self._batt_reserve_soc,
                    )

        # (#559 beta.19) The deadline-critical pass was removed: it grid/
        # battery-forced with no SOC gate (HIGH-2) to hit a per-device
        # deadline. solar_only (the switch-load default) never grid-forces;
        # cheap_hours devices still top up via the off-peak pass above.

        # Build allocation data
        total_allocated = sum(a.actual_consumption_watts for a in allocations)
        self._allocation_data = SurplusAllocationData(
            total_surplus_w=available_power_w,
            distributable_surplus_w=distributable,
            regulation_offset_w=self.regulation_offset,
            allocated_w=total_allocated,
            unallocated_w=max(0, distributable - total_allocated),
            active_devices=active_count,
            total_devices=len(self._devices),
            allocations=allocations,
            last_update=datetime.now(),
        )

        return self._allocation_data

    def _tier1_headroom_w(self, device) -> float:
        """(#620) Tier 1 daytime battery-assist headroom for one device (W).

        Non-zero ONLY when the device opted into ``battery_assist_enabled``
        (the "Solar + battery" mode) AND the battery is above the Buffer SoC.
        Returns the assist budget the coordinator passed (the same
        surplus-above-buffer budget the EV assist uses, #537/#545) — so the
        device may activate on surplus + battery down to the buffer, never
        below it. Everything else → 0 (inert)."""
        if not getattr(device, "battery_assist_enabled", False):
            return 0.0
        # (#688) Past its daily floor the device has nothing left to guarantee,
        # so the battery stops paying for it — free surplus only from here to
        # the Max cap. Single point: both the imperative pass and the
        # desired-state intent builder read their headroom through here.
        if getattr(device, "daily_targets_met", False):
            return 0.0
        soc = self._batt_soc
        if soc is None or soc <= self._batt_buffer_soc:
            return 0.0
        # Running budget: shrinks as earlier (higher-priority) battery-assist
        # loads claim it this cycle, so the battery isn't multi-spent.
        return max(0.0, min(self._batt_assist_budget_w, self._tier1_budget_left))

    def _tier2_overnight_eligible(self, device) -> bool:
        """(#620) Tier 2 — may this device draw the battery BELOW the buffer,
        down to the Reserve SoC, to meet its runtime floor when there is no
        surplus? Opt-in flag + battery strictly above the hard Reserve SoC.
        The Reserve is never crossed."""
        if not getattr(device, "battery_eligible_overnight", False):
            return False
        # (#633) overnight means overnight — no Tier-2 activation in daytime
        # (caught live: a load fed "from the battery" at 09:10 in full sun).
        if not getattr(self, "_is_night_cycle", True):
            return False
        soc = self._batt_soc
        return soc is not None and soc > self._batt_reserve_soc

    def _apply_price_adjustment(self, distributable: float, price_level: str) -> float:
        """Adjust distributable surplus based on electricity price level.

        - cheap: Add virtual surplus to encourage consumption
        - expensive: Reduce surplus to minimize consumption
        - negative: Maximize consumption (add large virtual surplus)
        """
        if price_level == "negative":
            # Negative price — consume as much as possible
            return distributable + 10000  # Virtual 10kW surplus
        elif price_level == "cheap":
            # Cheap — encourage consumption even from grid
            return distributable + 3000  # Virtual 3kW surplus
        elif price_level == "expensive":
            # Expensive — only use real solar surplus, reduce buffer
            return max(0, distributable - 500)
        return distributable

    async def deactivate_all(self, reason: str = "emergency") -> None:
        """Deactivate all devices (emergency stop, or SEM going away).

        Iterates ``self._devices`` rather than ``get_devices_sorted()`` (#656).
        That view hides devices that are ``is_enabled=False`` or
        ``managed_externally`` — both of which can be latched ON right now, and
        a teardown that skips them leaves exactly the strand this exists to
        prevent. Lowest priority first, so the log reads like a normal shed.

        One device failing must not abort the rest: this runs on the
        unload/remove path, where the alternative to a best-effort loop is an
        unattended heating device left commanded on by an integration that is
        on its way out.

        ``reason`` only labels the log line, so an emergency stop doesn't read
        as a teardown in the journal.
        """
        await deactivate_devices(self._devices.values(), reason)
