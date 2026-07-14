"""Counter-correlation audit shared logic (#589).

``CounterCorrelationAudit`` is the single extracted implementation of the
five-vote, warn-once pattern shared across:

- ``SensorReader._audit_manual_grid_sign``
- ``SensorReader._audit_autodetect_grid_sign``
- ``SensorReader._audit_battery_sign_lock``

Each instance owns its own baseline pair, vote counter, flagged state, and
warned guard — exactly replacing the 15 scattered ``_*_baseline /
_*_votes / _*_contradiction / _*_warned`` fields that previously lived
directly on ``SensorReader``.

Return value design
-------------------
``update()`` returns a string sentinel so the thin adapter methods can
handle context-rich logging without coupling this class to ``_LOGGER`` or
to SEM-specific entity names:

- ``"warn"``  — threshold just crossed; adapter must log WARNING once.
- ``"clear"`` — flag just cleared; adapter must log INFO.
- ``None``    — no notable transition this cycle.
"""
from __future__ import annotations

from typing import Callable, Optional


class CounterCorrelationAudit:
    """Five-vote, warn-once counter-vs-power contradiction detector.

    Parameters
    ----------
    threshold:
        Number of consecutive contradictions required before the flag
        is raised (default 5).
    """

    def __init__(self, threshold: int = 5) -> None:
        self._threshold = threshold

        # Mutable state — mirrors the old scattered fields.
        self.baseline_a: Optional[float] = None
        self.baseline_b: Optional[float] = None
        self.votes: int = 0
        self.flagged: bool = False
        self.warned: bool = False

    # ------------------------------------------------------------------
    # Core update — called once per coordinator cycle
    # ------------------------------------------------------------------

    def update(
        self,
        val_a: float,
        val_b: float,
        *,
        positive_power_means_a: bool,
        power_positive: bool,
        counter_deltas_fn: Callable[
            [Optional[float], Optional[float], float, float],
            Optional[tuple[float, float]],
        ],
    ) -> Optional[str]:
        """Run one cycle of the correlation check.

        Parameters
        ----------
        val_a:
            Current reading of counter A (e.g. grid-import or batt-charge).
        val_b:
            Current reading of counter B (e.g. grid-export or batt-discharge).
        positive_power_means_a:
            True  → power > 0 means counter-A should be the rising side.
            False → power > 0 means counter-B should be the rising side.
        power_positive:
            ``power > 0`` for this cycle (pre-computed by the caller to
            keep the predicate outside the class).
        counter_deltas_fn:
            The shared ``_counter_deltas`` helper (passed in to avoid
            coupling the class to ``SensorReader``).

        Returns
        -------
        ``"warn"`` when the flag was just raised (adapter should log WARNING);
        ``"clear"`` when the flag was just cleared (adapter should log INFO);
        ``None`` otherwise.
        """
        # Step 1 — prime baselines on first call.
        if self.baseline_a is None:
            self.baseline_a = val_a
            self.baseline_b = val_b
            return None

        # Step 2 — compute deltas; ``None`` means counter reset → skip.
        deltas = counter_deltas_fn(self.baseline_a, self.baseline_b, val_a, val_b)
        self.baseline_a = val_a
        self.baseline_b = val_b

        if deltas is None:
            return None

        delta_a, delta_b = deltas

        # Step 3 — classify which side is rising (must be unambiguous).
        if delta_a > 0.001 and delta_b < 0.001:
            counter_says_a_rising = True
        elif delta_b > 0.001 and delta_a < 0.001:
            counter_says_a_rising = False
        else:
            return None  # ambiguous — sit out

        # Step 4 — compare counter reading against power sign.
        power_says_a_rising = (
            power_positive if positive_power_means_a else not power_positive
        )
        if power_says_a_rising != counter_says_a_rising:
            # Step 5 — contradiction: increment votes.
            self.votes += 1
        else:
            # Step 6 — agreement: reset votes; optionally clear flag.
            self.votes = 0
            if self.flagged:
                self.flagged = False
                return "clear"
            return None

        # Step 7 — raise flag after threshold votes, warn once.
        if self.votes >= self._threshold and not self.flagged:
            self.flagged = True
            if not self.warned:
                self.warned = True
                return "warn"

        return None
