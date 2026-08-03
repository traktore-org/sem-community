"""Sensor-contradiction audits (#589, #661).

Two observe-only detectors live here. Both are five-vote, warn-once, and both
return the same ``"warn"``/``"clear"``/``None`` sentinel so the adapter methods
on ``SensorReader`` own the logging and the SEM-specific entity names.

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


class SplitSensorExclusivityAudit:
    """Five-vote, warn-once detector for a split sensor pair that contradicts
    itself — both sides reporting real power at the same instant (#661).

    Why this can't live downstream of the netting
    ---------------------------------------------
    Every split pair in SEM is immediately netted into ONE signed scalar
    (``grid_power = export − import``, ``battery_power = charge − discharge``),
    and ``PowerReadings.calculate_derived`` re-derives the two directional
    fields from that scalar with ``max(0, ±x)``. That derivation makes "both
    sides above zero" *unrepresentable*: whichever side is smaller becomes
    exactly 0.0 W.

    ``health_check`` nonetheless carried a mutual-exclusivity check on those
    derived fields. It could never fire in production — the netting had already
    destroyed the evidence — and its unit test passed only because it built a
    ``PowerReadings`` by hand, bypassing ``calculate_derived``. A check that
    cannot fail is worse than no check: it reads as coverage. (Bug class 8.)

    So the audit has to run at the netting site, on the RAW pair, which is the
    only moment both readings still exist. A real 3 kW import together with a
    real 3 kW export is not a physical state for one meter — it means swapped
    roles, a stale sensor, or two sensors pointed at different meters — and the
    netted 0 W it produces looks exactly like a balanced house.

    Vote semantics
    --------------
    * both sides genuinely active → contradiction, vote
    * exactly one side active     → agreement, reset votes (and clear)
    * neither side active         → sit out; a quiet house is not evidence
      either way, and must not reset an accumulating vote count.

    "Genuinely active" is deliberately stricter than ``> threshold_w`` on BOTH
    sides. Real meters bleed: an export sensor idling at 15 W while the house
    imports 3 kW is standby noise, not a meter claiming to do both at once. So
    the smaller side must additionally be worth ``min_ratio`` of the larger.
    Without that floor this warns at the *first* install with a slightly noisy
    idle sensor — which is how #461 ended up with 69 spurious "violations" in
    one dump. A detector nobody trusts is not a detector.

    Repeat episodes
    ---------------
    The WARNING fires once per lifetime, as everywhere else in this module —
    a genuinely miswired pair contradicts continuously and does not need the
    log every cycle. But a pair that contradicts, recovers, and contradicts
    again must not go permanently dark, or this becomes the very thing #661 is
    about: a detector that reads as coverage while saying nothing. Each later
    episode therefore returns ``"reflag"``, which the adapter logs at INFO with
    the episode number. That is bounded by construction — an episode costs five
    contradicting cycles plus an exclusive one.
    """

    def __init__(
        self, threshold: int = 5, threshold_w: float = 10.0,
        min_ratio: float = 0.05,
    ) -> None:
        self._threshold = threshold
        self._threshold_w = threshold_w
        self._min_ratio = min_ratio

        self.votes: int = 0
        self.flagged: bool = False
        self.warned: bool = False
        self.episodes: int = 0
        # Kept for the diagnostic line the adapter logs / the trace surfaces.
        self.last_a: float = 0.0
        self.last_b: float = 0.0

    def update(self, val_a: float, val_b: float) -> Optional[str]:
        """Run one cycle against the raw, pre-netting pair.

        Parameters
        ----------
        val_a, val_b:
            The two always-positive sides of the pair, in watts
            (import/export, or charge/discharge).

        Returns
        -------
        ``"warn"`` when the flag was raised for the first time, ``"reflag"``
        when a later episode raised it again, ``"clear"`` when it was just
        cleared, ``None`` otherwise.
        """
        self.last_a = val_a
        self.last_b = val_b

        a_active = val_a > self._threshold_w
        b_active = val_b > self._threshold_w

        both = a_active and b_active
        if both:
            # The smaller side must be a real share of the larger, not bleed.
            larger = max(val_a, val_b)
            both = min(val_a, val_b) >= larger * self._min_ratio

        if both:
            self.votes += 1
        elif a_active or b_active:
            self.votes = 0
            if self.flagged:
                self.flagged = False
                return "clear"
            return None
        else:
            # Both quiet — no information. Deliberately NOT a reset.
            return None

        if self.votes >= self._threshold and not self.flagged:
            self.flagged = True
            self.episodes += 1
            if not self.warned:
                self.warned = True
                return "warn"
            return "reflag"

        return None
