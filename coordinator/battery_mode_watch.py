"""(#845) The inverter's operating-policy selector, watched — never written.

Every hybrid inverter has the setting that decides what the battery does
when nobody commands it (Huawei: ``select.…_betriebsmodus`` — adaptive /
fixed_charge_discharge / maximise_self_consumption / fully_fed_to_grid /
time_of_use_luna2000). SEM assumes a self-consumption-shaped mode and,
until now, never verified it: switch the inverter to ``fully_fed_to_grid``
and the battery follows ITS schedule underneath SEM while every plan,
overnight-need model and #778 budget keeps computing on a moved premise.

Scope, exactly as the issue states: **observe first, act never.**
* the mode is read and published beside the battery evidence;
* ONE Repair when it is a mode SEM's model does not expect — after the
  reading has held steadily, because this instrument sits behind a modbus
  link that drops out 137×/day on the reference install (5 % of wall
  time), and a dropout is not a mode change;
* no write path exists, enforced by test. A deliberate
  ``fully_fed_to_grid`` is a legitimate choice SEM must not fight —
  the user decides, the Repair only names the disagreement.
"""
from __future__ import annotations

from typing import Optional, Set

#: Consecutive UNEXPECTED reads before the Repair raises. At a 30 s cycle
#: this is three minutes — far above any sensor blip, far below a support
#: thread's reaction time.
CONFIRM_READS: int = 6

#: States that carry no information about the mode. They never count
#: toward the confirm streak and never clear it — a dropout mid-streak
#: must not reset the evidence (the 5 % blind time would make the Repair
#: unreachable), and a dropout mid-OK must not look like a change.
_NO_READING = {None, "", "unknown", "unavailable"}


class BatteryModeWatch:
    """Debounced verdict over a stream of mode readings.

    ``feed`` returns the current verdict; ``changed`` on the instance says
    whether this feed crossed a raise/clear edge (the coordinator raises or
    clears the Repair only on edges, never per cycle)."""

    def __init__(self, expected: Optional[Set[str]],
                 confirm_reads: int = CONFIRM_READS) -> None:
        self.expected = {str(e) for e in expected} if expected else None
        self._confirm = int(confirm_reads)
        self._streak = 0
        self._raised = False
        self.changed = False
        self.last_mode: Optional[str] = None

    def feed(self, state: Optional[str]) -> str:
        """One reading → ``"ok" | "unexpected" | "unknown"``.

        ``unexpected`` is only returned while RAISED — the streak in
        between reads as ``unknown`` (evidence accruing, nothing to act
        on yet)."""
        self.changed = False
        if self.expected is None:
            # publish-only install (brand without a known expectation)
            if state not in _NO_READING:
                self.last_mode = str(state)
            return "ok"
        if state in _NO_READING:
            return "unknown" if not self._raised else "unexpected"
        mode = str(state)
        self.last_mode = mode
        if mode in self.expected:
            self._streak = 0
            if self._raised:
                # Recovery edge: the repair clears and the change is noted.
                self._raised, self.changed = False, True
            return "ok"
        self._streak += 1
        if not self._raised and self._streak >= self._confirm:
            self._raised, self.changed = True, True
        return "unexpected" if self._raised else "unknown"

    @property
    def raised(self) -> bool:
        return self._raised
