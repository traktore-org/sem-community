"""SEM layered-trace observability (2026-07-11).

Guido's three-layer model — **Management** (what should happen: prios,
timeline, sun, tariff, goals), **Process** (what to do & why: decide,
cross-check), **Integration** (act & confirm: command devices, observe) —
made explicit as one linked, per-cycle trace.

The trace is an OBSERVABILITY layer *over* the existing control code. The
coordinator collects values the layers already compute each cycle
(decisions, ``reason`` strings, reconciler actions, observed power) into a
ring buffer that the ``diagnose`` service dumps on demand. It never changes
a decision, and it never writes a per-cycle recorder row (#581): the trace
lives in memory + ``_unrecorded_attributes``.

Spec: ``docs/superpowers/specs/2026-07-11-sem-layered-trace-observability-design.md``.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional


def battery_list_role(
    *,
    battery_priority,
    battery_commanded: bool,
    soc: float,
    priority_soc: float,
    discharge_w: float,
) -> str:
    """The home battery's role in the ONE priority walk, for the trace's
    management layer (#576). Pure so it's unit-testable.

    Precedence (matches the reclaim gates): an explicit command wins, then the
    reserve floor, then the drag position:
      * commanded + discharging → "discharging — feeding (out of the walk)"
      * commanded (charging)    → "charging first — commanded"
      * SOC < reserve floor     → "charging first — below reserve zone"
      * no battery in the list  → "no battery in the priority list"
      * otherwise               → "sink at list position N" (the drag slot)
    """
    if battery_commanded and discharge_w > 0:
        return "discharging — feeding (out of the walk)"
    if battery_commanded:
        return "charging first — commanded"
    if soc < priority_soc:
        return "charging first — below reserve zone"
    if battery_priority is None:
        return "no battery in the priority list"
    return f"sink at list position {battery_priority}"


def ev_layer_match(commanded_amps, observed_w, phases, voltage, connected,
                   threshold: float = 0.3):
    """Did the car actually draw what we commanded? The flap linchpin.

    ``None`` (nothing to verify) when we're not commanding a charge or the car
    is unplugged; else True iff observed draw is at least ``threshold`` of the
    commanded power (allows for ramp / a 1φ charger's lower nominal)."""
    if not (commanded_amps and commanded_amps > 0 and connected):
        return None
    return observed_w > commanded_amps * phases * voltage * threshold


def battery_layer_match(intent, charge_w: float, discharge_w: float):
    """Is an explicit battery COMMAND actually happening? ``None`` in normal /
    idle (nothing commanded). force_charge → must be charging; force_discharge
    → must be discharging.

    A freshly-commanded force_charge/discharge reads False for the cycle or two
    the inverter takes to ramp (charge_w still 0). That single-cycle blip is
    *intentionally* not suppressed here — ``TraceCollector.health`` debounces it
    (needs ≥3 consecutive mismatched cycles to alarm), so the ramp never trips
    the health signal while a genuinely stuck command still does after ~3."""
    if intent == "force_charge":
        return charge_w > 0
    if intent == "force_discharge":
        return discharge_w > 0
    return None


def heat_pump_layer_match(boost: bool, sg_ready_state: int):
    """Did the SG-Ready relay follow a commanded boost? ``None`` when not
    boosting; else True iff the relay reached BOOST (3) or FORCE_ON (4)."""
    if not boost:
        return None
    return sg_ready_state >= 3


def device_layer_match(desired_on: bool, observed_on):
    """Did a surplus device SEM turned on actually turn on? Uses the RELAY /
    mode reality (``observed_on``), NOT power — a thermostat-satisfied heater
    is legitimately on at 0 W and must not read as a fault.

    ``None`` when SEM isn't driving it (desired off) or it's unobservable;
    else False = SEM commanded it on but the relay is off (the real fault)."""
    if not desired_on or observed_on is None:
        return None
    return bool(observed_on)


class LayerStatus(str, Enum):
    """Shared status vocabulary across all three layers.

    Makes "why isn't SEM charging?" answerable top-down:
    ``management: blocked`` → done; ``process: idle`` → done; etc.
    """

    OK = "ok"            # did its job, nothing notable
    IDLE = "idle"        # deliberately not acting (surplus < min, EV off)
    BLOCKED = "blocked"  # cannot act — ``detail`` says why
    DEGRADED = "degraded"  # acting on stale/partial input (held last-good)
    ERROR = "error"      # exception / command failure — ``detail`` carries it


@dataclass
class LayerRecord:
    """One layer's state for one subsystem in one cycle."""

    status: LayerStatus = LayerStatus.OK
    detail: str = ""                    # human one-liner (an existing reason fits)
    data: Dict[str, Any] = field(default_factory=dict)  # few key numbers, flat

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "detail": self.detail,
            "data": dict(self.data),
        }


@dataclass
class SubsystemTrace:
    """The three-layer chain for one subsystem (a charger, the battery, …)."""

    management: LayerRecord = field(default_factory=LayerRecord)
    process: LayerRecord = field(default_factory=LayerRecord)
    integration: LayerRecord = field(default_factory=LayerRecord)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "management": self.management.to_dict(),
            "process": self.process.to_dict(),
            "integration": self.integration.to_dict(),
        }

    @property
    def has_mismatch(self) -> bool:
        """A layer-boundary fault: we decided to act, but the observed
        reality doesn't match what we commanded (the flap linchpin).

        Only fires when the process layer WANTED action (not idle/blocked)
        AND the integration layer explicitly reports ``match is False``.
        """
        acting = self.process.status in (LayerStatus.OK, LayerStatus.DEGRADED)
        return acting and self.integration.data.get("match") is False


@dataclass
class CrossCheck:
    """A Perception-layer two-view reality check for one input signal (#589).

    Unlike ``SubsystemTrace`` (a control chain that decides → acts → confirms),
    a cross-check compares a sign-corrected *reading* against ground truth
    (the energy counters) with NO actuation — it's a two-view check, not the
    three-layer act-and-confirm. ``data["agree"] is False`` is a *perception*
    fault (the sign is wrong, or the counters are swapped) — the class the
    control layers structurally cannot catch, because Management → Process →
    Integration all cohere on a mis-signed input. Foldes into the same
    mismatch/streak/health engine as the control faults (see ``commit``), so
    ``binary_sensor.sem_layer_mismatch`` becomes a true "is SEM's whole view of
    reality sound?" signal — perception + control.
    """

    signal: str                                # "grid_sign" | "battery_sign"
    status: LayerStatus = LayerStatus.OK
    detail: str = ""
    data: Dict[str, Any] = field(default_factory=dict)  # {"agree": bool|None, …}
    # #590 — the SOURCE already debounced this signal (the counter audit's
    # 5-vote threshold). The trace health engine then alarms on the FIRST
    # faulted cycle instead of stacking its ≥3-cycle streak on top: ONE
    # debounce, not two (pre-fold, a real contradiction only surfaced after
    # 5 votes + 3 streak cycles ≈ 8 cycles ≈ 80 s).
    pre_debounced: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal": self.signal,
            "status": self.status.value,
            "detail": self.detail,
            "data": dict(self.data),
            "pre_debounced": self.pre_debounced,
        }

    @property
    def is_fault(self) -> bool:
        """A perception fault: judging (not idle) AND the reading disagrees
        with the counters. ``agree is None`` (nothing to judge this cycle)
        never faults."""
        judging = self.status in (LayerStatus.OK, LayerStatus.DEGRADED)
        return judging and self.data.get("agree") is False


@dataclass
class CycleTrace:
    """All subsystems' three-layer chains for one coordinator cycle."""

    seq: int
    wall_iso: str = ""
    subsystems: Dict[str, SubsystemTrace] = field(default_factory=dict)
    # #589 — Perception-layer two-view checks (sign/counter integrity),
    # peers of the three-layer subsystems, keyed by signal.
    cross_checks: Dict[str, CrossCheck] = field(default_factory=dict)

    def subsystem(self, key: str) -> SubsystemTrace:
        """Get-or-create the trace for ``key`` (e.g. ``"ev:keba"``,
        ``"battery"``, ``"loads"``). Callers write ``.management`` /
        ``.process`` / ``.integration`` on the returned object."""
        st = self.subsystems.get(key)
        if st is None:
            st = self.subsystems[key] = SubsystemTrace()
        return st

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seq": self.seq,
            "wall": self.wall_iso,
            "subsystems": {k: v.to_dict() for k, v in self.subsystems.items()},
            "cross_checks": {k: v.to_dict() for k, v in self.cross_checks.items()},
        }


class TraceCollector:
    """Per-cycle trace assembly + a bounded ring buffer for ``diagnose``.

    Lives on the coordinator. ``begin()`` at cycle top, write captures onto
    the returned ``CycleTrace``, ``commit()`` at cycle end. ``recent()`` is
    the on-demand dump. Bounded — never grows, never touches the recorder.
    """

    def __init__(self, maxlen: int = 30) -> None:
        self._buf: Deque[CycleTrace] = deque(maxlen=maxlen)
        self._seq: int = 0
        self._current: Optional[CycleTrace] = None
        # subsystem → consecutive cycles with a layer-boundary mismatch.
        # Debounces the health signal so a single-cycle blip doesn't alarm.
        self._streak: Dict[str, int] = {}
        # #590 — mismatch keys whose SOURCE already debounced (pre_debounced
        # cross-checks): health() alarms these at streak ≥1, not ≥threshold.
        self._pre_debounced: set = set()

    def begin(self, wall_iso: str = "") -> CycleTrace:
        """Open a fresh trace for this cycle. Returns it for capture writes."""
        self._seq += 1
        self._current = CycleTrace(seq=self._seq, wall_iso=wall_iso)
        return self._current

    def current(self) -> Optional[CycleTrace]:
        """The in-progress trace (None outside a begin/commit window)."""
        return self._current

    def commit(self) -> None:
        """Push the in-progress trace into the ring buffer + update the
        per-subsystem mismatch streaks (the debounce behind ``health()``)."""
        if self._current is None:
            return
        mismatched = {
            k for k, st in self._current.subsystems.items() if st.has_mismatch
        }
        # #589 — perception cross-check faults ride the SAME streak/health
        # engine as control faults, tagged ``perception:<signal>``. A persistent
        # sign/counter contradiction now trips binary_sensor.sem_layer_mismatch,
        # closing the blind spot where all three control layers cohere on a
        # mis-signed input.
        mismatched |= {
            f"perception:{cc.signal}"
            for cc in self._current.cross_checks.values()
            if cc.is_fault
        }
        # #590 — remember which faulted keys arrived pre-debounced so
        # health() can alarm them without stacking a second streak delay.
        self._pre_debounced = {
            f"perception:{cc.signal}"
            for cc in self._current.cross_checks.values()
            if cc.is_fault and cc.pre_debounced
        }
        # reset streaks that recovered this cycle; increment the ones still bad
        for k in list(self._streak):
            if k not in mismatched:
                del self._streak[k]
        for k in mismatched:
            self._streak[k] = self._streak.get(k, 0) + 1
        self._buf.append(self._current)
        self._current = None

    def health(self, threshold: int = 3) -> Dict[str, Any]:
        """Health summary: is a layer-boundary mismatch PERSISTENT?

        ``ok`` unless some subsystem has mismatched for ≥ ``threshold``
        consecutive cycles (a one-cycle blip never alarms). This is what the
        ``binary_sensor.sem_layer_mismatch`` / ``diagnose`` health surface
        read — it would have flagged the 2026-07-10 flap within ~3 cycles.
        """
        # #590 — pre-debounced keys (source already vote-debounced, e.g. the
        # counter audit) alarm at the first cycle; everything else keeps the
        # streak threshold. One debounce per signal, never two stacked.
        persistent = {
            k: v for k, v in self._streak.items()
            if v >= (1 if k in self._pre_debounced else threshold)
        }
        if not persistent:
            return {"ok": True, "subsystem": None, "cycles": 0, "mismatch": None}
        worst = max(persistent, key=persistent.get)
        return {
            "ok": False,
            "subsystem": worst,
            "cycles": persistent[worst],
            "mismatch": self.latest_mismatch(),
        }

    def recent(self, n: Optional[int] = None) -> List[Dict[str, Any]]:
        """Serialised last ``n`` cycles (all if ``n`` is None) for diagnose."""
        items = list(self._buf)
        if n is not None:
            items = items[-n:]
        return [t.to_dict() for t in items]

    def latest_mismatch(self) -> Optional[Dict[str, Any]]:
        """The most recent cycle's first layer-boundary fault, if any.

        Phase-2 health signal reads this: ``{subsystem, cycle, integration}``
        when a subsystem decided to act but observed reality disagrees.
        """
        if not self._buf:
            return None
        trace = self._buf[-1]
        for key, st in trace.subsystems.items():
            if st.has_mismatch:
                return {
                    "subsystem": key,
                    "cycle": trace.seq,
                    "process": st.process.to_dict(),
                    "integration": st.integration.to_dict(),
                }
        # #589 — surface a perception fault too, so the health detail names the
        # mis-signed input rather than staying silent while the control layers
        # all read green.
        for cc in trace.cross_checks.values():
            if cc.is_fault:
                return {
                    "subsystem": f"perception:{cc.signal}",
                    "cycle": trace.seq,
                    "cross_check": cc.to_dict(),
                }
        return None
