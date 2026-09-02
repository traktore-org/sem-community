"""#864 — the preventive half of peak defence: the 15-minute slot budget.

Demand tariffs bill the average grid import of a fixed CLOCK slot
(:00/:15/:30/:45). The load manager's reactive states (warning / shedding /
emergency, `features/load_management.py`) key off a rolling average — which
is the right instrument for restoring calm but structurally cannot protect
the billed metric: by the time the average crosses the target, the slot
average IS the peak. Live on PROD 29.08: an EV charged at 9.9 kW under a
6.0 kW target with the state reading `normal` throughout, and the month's
6.919 kW peak had already been set the day before by ordinary use.

This module is the bill's own arithmetic, kept pure for testability:

* :class:`PeakSlotTracker` integrates grid import over the CURRENT clock
  slot — aligned the way the utility aligns it, reset at the boundary.
* :func:`slot_allowed_import_w` answers "how much may the house import,
  on average, for the REST of this slot so the slot lands at the target".

`decide()` bounds the EV offer with that answer BEFORE writing it; the
reactive states stay untouched and senior (#747's emergency still idles
the charger outright).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

SLOT_S: float = 900.0

# Integration step cap. A cycle is ~10 s; a gap beyond this (restart,
# stalled loop) is UNKNOWN consumption, and unknown must not be backfilled
# as the last sample's worth of watts — over-counting the slot would clamp
# the EV for a fault of ours, not of the house.
_MAX_STEP_S: float = 60.0

# End-of-slot bound. The naive remaining-budget division explodes as the
# denominator approaches zero: with budget left and 5 s remaining it would
# "allow" hundreds of kW — mathematically fine for the slot, but a step the
# offer-steadiness layer should never even see, and the next slot begins at
# the target anyway. Allowing three targets caps the burst while still
# letting a slot that ran cold spend its remainder.
_ALLOWANCE_CAP_FACTOR: float = 3.0


def slot_allowed_import_w(
    target_kw: float, imported_kwh: float, elapsed_s: float,
    slot_s: float = SLOT_S, blind: bool = False,
) -> Optional[float]:
    """Average import (W) the rest of the slot may carry to land on target.

    ``None`` when no positive target is configured — absence of a ceiling
    is not a ceiling of zero (`peak_limit_unlimited` installs).

    ``blind`` (#906): the meter could not be read this cycle, so the
    integral is a held estimate. A slot SEM cannot see may never be
    allowed MORE than the target itself — the burst allowance is for a
    slot the tracker actually watched. Spent stays spent either way.
    """
    if target_kw is None or target_kw <= 0:
        return None
    budget_kwh = float(target_kw) * (slot_s / 3600.0)
    remaining_kwh = budget_kwh - max(0.0, float(imported_kwh))
    if remaining_kwh <= 0:
        return 0.0
    remaining_s = max(1.0, slot_s - max(0.0, float(elapsed_s)))
    allowed_w = remaining_kwh * 3600.0 * 1000.0 / remaining_s
    cap = float(target_kw) * 1000.0 * (1.0 if blind else _ALLOWANCE_CAP_FACTOR)
    return min(allowed_w, cap)


class PeakSlotTracker:
    """Import energy of the current billing slot, clock-aligned.

    ZOH integration of the previous sample over the elapsed step, split at
    the slot boundary so each slot owns exactly its own seconds. Negative
    import (export) accrues nothing — the bill never credits a slot.
    """

    def __init__(self) -> None:
        self._last_t: Optional[datetime] = None
        self._last_w: float = 0.0
        self._slot_start: Optional[datetime] = None
        self.imported_kwh: float = 0.0
        #: (#906) True while the latest sample was unreadable — the integral
        #: is carrying the last VALID import across the gap (ZOH), not a 0.
        self.blind: bool = False

    @staticmethod
    def _slot_of(t: datetime) -> datetime:
        return t.replace(minute=(t.minute // 15) * 15, second=0, microsecond=0)

    @property
    def elapsed_s(self) -> float:
        if self._last_t is None or self._slot_start is None:
            return 0.0
        return max(0.0, (self._last_t - self._slot_start).total_seconds())

    def update(self, now: datetime, grid_import_w: Optional[float]) -> None:
        """``grid_import_w=None`` (#906) is a BLIND sample: the meter was
        unreadable. The last valid import is held across the gap — an
        unread meter is not a meter reading zero, and for the budget that
        defends the bill, zero is the optimistic direction (PROD 02.09: two
        dropouts inside a slot averaging 8 kW manufactured enough headroom
        for the guard to release at 5.9/6.0 kW)."""
        slot = self._slot_of(now)
        if self._slot_start is None:
            self._slot_start = slot
        if self._last_t is not None:
            step = (now - self._last_t).total_seconds()
            if 0 < step:
                step = min(step, _MAX_STEP_S)
                w = max(0.0, self._last_w)
                if slot != self._slot_start:
                    # Split the step at the boundary: only the seconds
                    # inside the NEW slot survive the reset.
                    inside_new = min(step, (now - slot).total_seconds())
                    self.imported_kwh = w * max(0.0, inside_new) / 3600.0 / 1000.0
                    self._slot_start = slot
                else:
                    self.imported_kwh += w * step / 3600.0 / 1000.0
        self._last_t = now
        if grid_import_w is None:
            self.blind = True          # hold ``_last_w`` — ZOH over the gap
        else:
            self.blind = False
            self._last_w = float(grid_import_w or 0.0)


def clamp_import_command(
    desired_w: float,
    allowed_w: Optional[float],
    grid_import_w: float,
    own_grid_draw_w: float = 0.0,
) -> tuple:
    """Bound one import-creating command by the slot allowance.

    The security-layer contract (29.08): peak management sits ABOVE every
    mode of every device — the limit lives at the power meter, so every
    import SEM commands is bounded by the same slot budget. ``allowed_w``
    is the whole house's remaining slot allowance; what everyone ELSE is
    importing right now is spoken for; ``own_grid_draw_w`` is this
    command's own current share of the import, credited back so a running
    command is not ratcheted down by its own draw.

    Returns ``(watts, was_clamped)``. ``None`` allowance = no ceiling
    configured (or the guard switched off) → pass through untouched.
    """
    if allowed_w is None:
        return float(desired_w), False
    gi = max(0.0, float(grid_import_w or 0.0))
    others_w = max(0.0, gi - min(max(0.0, float(own_grid_draw_w or 0.0)), gi))
    headroom_w = max(0.0, float(allowed_w) - others_w)
    if float(desired_w) <= headroom_w:
        return float(desired_w), False
    return headroom_w, True
