"""#580 — Generic VPP grid-event dispatch (Axle Energy is the first wiring).

A Virtual Power Plant integration exposes a small set of entities:

* an **event gate** (binary_sensor / sensor, active = ``on`` / ``in_progress``)
* a **direction** entity (state ``export`` or ``import``)
* an optional **event end** timestamp sensor
* an optional **pre-event** signal (e.g. Axle's 1-hour-before binary)

SEM maps events onto its EXISTING controls only — no new actuation paths:

* export event → battery FORCE_DISCHARGE (through ``decide_battery`` via a
  per-cycle ``battery_mode`` override, bounded by ``vpp_reserve_soc``),
  EV charging paused (per-cycle charge-mode veto → ``off``), surplus loads
  shed (peak-shed gate → EMERGENCY posture for the surplus controller).
* import event → battery FORCE_CHARGE at max accepted power, EV boosted
  (charge-mode veto → ``always_max``).
* pre-event (export coming) → reserve solar for a battery top-up by pausing
  the EV (solar surplus then charges the battery under normal
  self-consumption; NO grid top-up in v1).

**Observer mode (the default)** computes everything, logs + notifies what it
WOULD do, publishes state — and actuates NOTHING. First-release behaviour
for every user.

Event end / boot reconcile (the #532 strand class): the force op is a
per-cycle mode override, so the moment the event ends the override drops and
``decide_battery`` falls back to NORMAL → each adapter's ``command_normal()``
is the sanctioned teardown primitive (zeroes forcible setpoints, Huawei
clears startup orphans). Nothing here can outlive its window.

The decision core (:func:`evaluate_vpp`) is pure; :class:`VppDispatcher`
holds the small amount of per-event state (phase edge detection + energy
accounting) and is hass-free so both are unit-testable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Mapping, Optional, Tuple

_LOGGER = logging.getLogger(__name__)

# Phases
PHASE_IDLE = "idle"
PHASE_PRE_EVENT = "pre_event"
PHASE_EVENT = "event"

# Directions
DIR_EXPORT = "export"
DIR_IMPORT = "import"

# Gate states that mean "event running" (Axle uses both spellings).
GATE_ACTIVE_STATES = ("on", "in_progress", "active", "true")

# Sanity cap: if the gate sticks active this long past the advertised end
# time, treat the event as over (a stuck gate must not run SEM forever).
GATE_STUCK_GRACE = timedelta(minutes=30)

# Bounded persisted history (payment reconciliation is per event).
MAX_EVENTS = 20


@dataclass(frozen=True)
class VppAction:
    """One dispatchable action. ``kind`` ∈ force_discharge / force_charge /
    pause_ev / boost_ev / shed_loads. Params carry bounds (e.g. reserve_soc)."""

    kind: str
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VppDecision:
    """Pure per-cycle verdict of :func:`evaluate_vpp`."""

    phase: str                      # idle | pre_event | event
    direction: Optional[str]        # export | import | None
    actions: Tuple[VppAction, ...]  # empty in idle / observer still lists them
    observer: bool                  # True → log/notify only, actuate nothing
    reason: str
    gate_stuck: bool = False        # gate active >30 min past advertised end


def _is_active(raw: Optional[str]) -> bool:
    return str(raw or "").strip().lower() in GATE_ACTIVE_STATES


def _parse_end(raw: Optional[str]) -> Optional[datetime]:
    """Parse the event-end timestamp sensor state (ISO 8601)."""
    if not raw or str(raw).lower() in ("unknown", "unavailable", "none", ""):
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def evaluate_vpp(
    config: Mapping[str, Any],
    states: Mapping[str, Optional[str]],
    battery_soc: Optional[float],
    now: datetime,
) -> VppDecision:
    """Compute this cycle's VPP decision. Pure — same input, same output.

    Args:
        config: merged SEM config (``vpp_*`` keys read per-cycle).
        states: snapshot of the wired entities' raw states, keyed
            ``event_active`` / ``direction`` / ``event_end`` / ``pre_event``.
        battery_soc: fleet battery SOC (%) or None when unavailable.
        now: current localized time (injected clock).
    """
    if not bool(config.get("vpp_enabled", False)):
        return VppDecision(
            phase=PHASE_IDLE, direction=None, actions=(),
            observer=True, reason="vpp disabled",
        )

    observer = bool(config.get("vpp_observer_mode", True))
    try:
        reserve = float(config.get("vpp_reserve_soc", 20) or 20)
    except (TypeError, ValueError):
        reserve = 20.0

    gate_active = _is_active(states.get("event_active"))

    # Sanity cap — a gate stuck active well past the advertised end time is
    # treated as over (log-once handled by the caller via ``gate_stuck``).
    if gate_active:
        end_ts = _parse_end(states.get("event_end"))
        if end_ts is not None:
            _now = now
            # Compare in a common awareness (naive sensor vs aware now).
            if end_ts.tzinfo is None and _now.tzinfo is not None:
                _now = _now.replace(tzinfo=None)
            elif end_ts.tzinfo is not None and _now.tzinfo is None:
                end_ts = end_ts.replace(tzinfo=None)
            if _now > end_ts + GATE_STUCK_GRACE:
                return VppDecision(
                    phase=PHASE_IDLE, direction=None, actions=(),
                    observer=observer, gate_stuck=True,
                    reason=(
                        f"event gate still active {GATE_STUCK_GRACE} past "
                        f"advertised end {end_ts.isoformat()} — treating event "
                        "as over"
                    ),
                )

    raw_dir = str(states.get("direction") or "").strip().lower()
    direction = DIR_IMPORT if raw_dir == DIR_IMPORT else DIR_EXPORT
    dir_note = "" if raw_dir in (DIR_EXPORT, DIR_IMPORT) else \
        f" (direction entity read {raw_dir!r} → defaulting to export)"

    if gate_active:
        if direction == DIR_EXPORT:
            actions: List[VppAction] = [
                VppAction("pause_ev", {"why": "VPP export event"}),
                VppAction("shed_loads", {"why": "VPP export event"}),
            ]
            if battery_soc is not None and battery_soc > reserve:
                # Power is resolved downstream by decide_battery from
                # battery_max_discharge_power ("as much as possible" — the
                # reporter confirmed there is no requested power level).
                actions.insert(0, VppAction(
                    "force_discharge", {"reserve_soc": reserve},
                ))
                soc_note = f"SOC {battery_soc:.0f}% > reserve {reserve:.0f}%"
            elif battery_soc is None:
                soc_note = "battery SOC unavailable — no discharge (hold)"
            else:
                soc_note = (
                    f"SOC {battery_soc:.0f}% ≤ reserve {reserve:.0f}% — "
                    "no discharge"
                )
            return VppDecision(
                phase=PHASE_EVENT, direction=DIR_EXPORT,
                actions=tuple(actions), observer=observer,
                reason=f"export event active ({soc_note}){dir_note}",
            )
        # Import event — soak up grid power: battery force-charges at max
        # accepted power, EV boosted to max if connected, deferred loads may
        # start (the surplus controller simply isn't shed).
        return VppDecision(
            phase=PHASE_EVENT, direction=DIR_IMPORT,
            actions=(
                VppAction("force_charge", {}),
                VppAction("boost_ev", {}),
            ),
            observer=observer,
            reason=f"import event active{dir_note}",
        )

    if _is_active(states.get("pre_event")):
        # Export coming — top the battery up from SOLAR (not grid, v1):
        # pausing the EV routes the solar surplus into the battery under
        # normal self-consumption. No force op before the event itself.
        return VppDecision(
            phase=PHASE_PRE_EVENT, direction=direction,
            actions=(VppAction(
                "pause_ev", {"why": "pre-event battery top-up from solar"},
            ),),
            observer=observer,
            reason="pre-event signal active — reserving solar for battery",
        )

    return VppDecision(
        phase=PHASE_IDLE, direction=None, actions=(),
        observer=observer, reason="no active VPP event",
    )


class VppDispatcher:
    """Thin stateful layer over :func:`evaluate_vpp` — phase-edge detection
    and per-event energy accounting. hass-free (the coordinator snapshots
    entity states and counters and feeds them in).

    Event records: ``{start, end, direction, kwh, observer}`` — ``end`` is
    None while the event is open (persisted so a restart mid-event is
    visible; a stale open record is reconciled on the first cycle after
    boot)."""

    def __init__(self, events: Optional[List[Dict[str, Any]]] = None) -> None:
        self._events: List[Dict[str, Any]] = [
            dict(e) for e in (events or []) if isinstance(e, dict)
        ][-MAX_EVENTS:]
        self._phase: str = PHASE_IDLE
        self._active: Optional[Dict[str, Any]] = None
        self._baseline_import_kwh: Optional[float] = None
        self._baseline_export_kwh: Optional[float] = None
        self._carried_kwh: float = 0.0
        self._boot_checked = False

    @property
    def events(self) -> List[Dict[str, Any]]:
        """Bounded event history (oldest → newest), open record included."""
        return list(self._events)

    @property
    def phase(self) -> str:
        return self._phase

    # ── per-cycle update ────────────────────────────────────────────

    def update(
        self,
        decision: VppDecision,
        *,
        grid_import_kwh: float,
        grid_export_kwh: float,
        now: datetime,
    ) -> Dict[str, Any]:
        """Advance the dispatcher one cycle.

        Returns ``{"transition": None|"start"|"end"|"boot_reconcile",
        "events_changed": bool, "event": <closed record on end>}``.
        """
        out: Dict[str, Any] = {"transition": None, "events_changed": False,
                               "event": None}

        # ── boot reconcile (the #532 class) ─────────────────────────
        # A restart mid-event leaves an open record (end=None) in the
        # persisted list. If the gate is STILL active, resume it (keep the
        # accumulated kWh, re-baseline the counters); otherwise close it —
        # a force op / its accounting must never outlive its window.
        if not self._boot_checked:
            self._boot_checked = True
            stale = self._events[-1] if self._events else None
            if stale is not None and stale.get("end") is None:
                if (decision.phase == PHASE_EVENT
                        and stale.get("direction") == decision.direction):
                    self._active = stale
                    self._phase = PHASE_EVENT
                    self._carried_kwh = float(stale.get("kwh", 0.0) or 0.0)
                    self._baseline_import_kwh = grid_import_kwh
                    self._baseline_export_kwh = grid_export_kwh
                else:
                    stale["end"] = now.isoformat()
                    stale["reconciled"] = True
                    out["transition"] = "boot_reconcile"
                    out["events_changed"] = True

        prev = self._phase

        if decision.phase == PHASE_EVENT and prev != PHASE_EVENT:
            # ── event start: snapshot counters ──────────────────────
            self._active = {
                "start": now.isoformat(),
                "end": None,
                "direction": decision.direction,
                "kwh": 0.0,
                "observer": decision.observer,
            }
            self._carried_kwh = 0.0
            self._baseline_import_kwh = grid_import_kwh
            self._baseline_export_kwh = grid_export_kwh
            self._events.append(self._active)
            self._events = self._events[-MAX_EVENTS:]
            out["transition"] = "start"
            out["events_changed"] = True

        elif decision.phase == PHASE_EVENT and self._active is not None:
            # ── event running: accumulate delivered kWh ─────────────
            self._accumulate(grid_import_kwh, grid_export_kwh)

        elif prev == PHASE_EVENT and decision.phase != PHASE_EVENT:
            # ── event end: finalize the record ──────────────────────
            if self._active is not None:
                self._accumulate(grid_import_kwh, grid_export_kwh)
                self._active["end"] = now.isoformat()
                out["event"] = dict(self._active)
                out["transition"] = "end"
                out["events_changed"] = True
            self._active = None
            self._baseline_import_kwh = None
            self._baseline_export_kwh = None
            self._carried_kwh = 0.0

        self._phase = decision.phase
        return out

    def _accumulate(self, grid_import_kwh: float, grid_export_kwh: float) -> None:
        """Delivered kWh = counter delta since event start (direction-keyed).

        A negative delta means the counter reset (midnight rollover of the
        daily accumulator, or a source reset) — treat the step as 0 and
        re-baseline so subsequent increments keep counting (#580 spec)."""
        if self._active is None:
            return
        if self._active.get("direction") == DIR_IMPORT:
            baseline, current = self._baseline_import_kwh, grid_import_kwh
        else:
            baseline, current = self._baseline_export_kwh, grid_export_kwh
        if baseline is None:
            delta = 0.0
        else:
            delta = current - baseline
        if delta < 0:
            # counter reset — bank what we had, restart the delta from here
            self._carried_kwh = float(self._active.get("kwh", 0.0) or 0.0)
            delta = 0.0
            if self._active.get("direction") == DIR_IMPORT:
                self._baseline_import_kwh = current
            else:
                self._baseline_export_kwh = current
        self._active["kwh"] = round(self._carried_kwh + max(0.0, delta), 3)

    # ── publish payload ─────────────────────────────────────────────

    def publish_state(self, decision: VppDecision) -> Dict[str, Any]:
        """Coordinator-data payload for ``sensor.sem_vpp_event``."""
        if decision.phase == PHASE_EVENT:
            state = f"event_{decision.direction or DIR_EXPORT}"
        else:
            state = decision.phase
        closed = [e for e in self._events if e.get("end") is not None]
        return {
            "vpp_event": state,
            "vpp_event_direction": decision.direction or "",
            "vpp_event_started": (
                self._active.get("start") if self._active else None
            ),
            "vpp_event_delivered_kwh": (
                float(self._active.get("kwh", 0.0)) if self._active else 0.0
            ),
            "vpp_event_observer": decision.observer,
            "vpp_event_reason": decision.reason,
            "vpp_last_event": dict(closed[-1]) if closed else None,
            "vpp_events": [dict(e) for e in self._events[-5:]],
        }
