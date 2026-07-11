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
class CycleTrace:
    """All subsystems' three-layer chains for one coordinator cycle."""

    seq: int
    wall_iso: str = ""
    subsystems: Dict[str, SubsystemTrace] = field(default_factory=dict)

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

    def begin(self, wall_iso: str = "") -> CycleTrace:
        """Open a fresh trace for this cycle. Returns it for capture writes."""
        self._seq += 1
        self._current = CycleTrace(seq=self._seq, wall_iso=wall_iso)
        return self._current

    def current(self) -> Optional[CycleTrace]:
        """The in-progress trace (None outside a begin/commit window)."""
        return self._current

    def commit(self) -> None:
        """Push the in-progress trace into the ring buffer."""
        if self._current is not None:
            self._buf.append(self._current)
            self._current = None

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
        return None
