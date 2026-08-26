"""#846 — measure the result of every command, prefer it to the assumption.

SEM chooses the charger's amps. Until now it also *assumed* what those amps
would buy: ``amps x phases x voltage``, both constants from config. Live on
PROD that assumption was 9 % wrong — 16 A commanded, 11.04 kW believed,
10.02 kW drawn — and the same figure feeds the surplus→amps conversion, the
night planner's block sizing, the peak guard and the phase guard. The error
was systemic, silent, and self-inflicted: SEM never asked what its own
command produced.

This is the EVCC move — fire, check, adjust — as a deliberately timid
learner. Every restriction below exists because the untimid version is
worse than no learner at all:

* **keyed per (charger, phase count)**: the same car at 16 A is ~11 kW on
  three phases and ~3.7 kW on one, so a single number is wrong by 3x the
  moment a phase switch lands;
* **only while the belief is confirmed and the setpoint steady**, with no
  switch in flight and no taper — every other sample is measuring a
  transient, not the car;
* **bounded, and the refusal is CLASSIFIED**: a draw that fits a different
  phase count is refused as ``phase_belief`` rather than absorbed as "this
  car is 33 % efficient". The band does the refusing (a mutation check showed
  a separate phase gate was redundant for 1φ/3φ); the classification is what
  points a reader at the contradiction cap instead of at this number;
* **bounded** to a narrow band around nameplate — outside it something else
  is wrong, and the honest answer is nameplate plus a diagnostic;
* **never widens a limit**: a measurement may lower what SEM believes it
  bought (freeing real headroom) but must never license exceeding a cap.

The phase belief is the ANCHOR and this learner is strictly dependent: the
belief is derived from nameplate voltage as before and never re-derived from
a learned W/A. The learner reads the belief; the belief never reads the
learner. That one-way rule is what keeps the two estimators from converging
on a consistent, wrong pair.
"""
from __future__ import annotations

import statistics
from typing import Dict, Optional, Tuple

#: Samples before a measurement is trusted over the nameplate. Small enough
#: to earn confidence within one charge, large enough that a single odd
#: cycle cannot move the answer (the median does the rest).
MIN_SAMPLES: int = 5

#: How far from nameplate a sample may sit and still be believable. The low
#: end admits real causes (voltage sag, a current-limited onboard charger, a
#: car that refuses the last amp); below it, the likelier explanation is a
#: wrong phase belief or a mis-mapped power sensor — both of which deserve a
#: diagnostic, not a fitted constant.
MIN_RATIO: float = 0.75
MAX_RATIO: float = 1.05

#: A sample is refused outright when its implied W/A sits closer to another
#: phase count than to the believed one.
_PHASE_COUNTS: Tuple[int, ...] = (1, 3)

#: Keep the window short: a car's real W/A does drift (temperature, state of
#: charge), and an old sample should not outvote today's.
_WINDOW: int = 20


class WattsPerAmpLearner:
    """Per-charger, per-phase-count watts-per-amp, learned from observation."""

    def __init__(self) -> None:
        self._samples: Dict[Tuple[str, int], list] = {}
        self._refused: Dict[Tuple[str, int], int] = {}
        self._reasons: Dict[Tuple[str, int], Dict[str, int]] = {}

    # ── learning ────────────────────────────────────────────────────────
    def record(self, charger_id: str, *, phases: int, commanded_amps: float,
               observed_w: float, nominal_wpa: float,
               belief_confirmed: bool = True, setpoint_steady: bool = True,
               switch_in_flight: bool = False, tapering: bool = False) -> bool:
        """Offer one observation. Returns True if it was accepted.

        Every gate is a refusal to learn from a moment that cannot teach."""
        if switch_in_flight or tapering or not setpoint_steady \
                or not belief_confirmed:
            return False
        if phases not in _PHASE_COUNTS:
            return False
        try:
            amps = float(commanded_amps)
            watts = float(observed_w)
            nominal = float(nominal_wpa)
        except (TypeError, ValueError):
            return False
        if amps <= 0 or watts <= 0 or nominal <= 0:
            return False

        wpa = watts / amps
        key = (str(charger_id), int(phases))

        # ONE refusal gate — the plausible band around nameplate — with TWO
        # reasons, because they mean different things to a person reading the
        # diagnostic.
        #
        # (A mutation check corrected the first draft: a separate
        # "fits another phase count" gate looked load-bearing and was not.
        # For the 1φ/3φ pair the band subsumes it — a 1-phase draw believed
        # to be 3-phase lands at 0.33x nominal, a 3-phase draw believed to be
        # 1-phase at 3.0x, both far outside 0.75-1.05. Keeping it as a second
        # gate would have been untestable dead code; keeping it as the REASON
        # gives it a real job.)
        ratio = wpa / nominal
        if not (MIN_RATIO <= ratio <= MAX_RATIO):
            per_phase = nominal / float(phases)      # ≈ the voltage
            implied = wpa / per_phase                # ≈ the phase count drawn
            fits = min(_PHASE_COUNTS, key=lambda p: abs(implied - p))
            reason = ("phase_belief" if fits != int(phases) and
                      abs(implied - fits) < 0.35 else "implausible")
            self._refused[key] = self._refused.get(key, 0) + 1
            self._reasons.setdefault(key, {})
            self._reasons[key][reason] = self._reasons[key].get(reason, 0) + 1
            return False

        buf = self._samples.setdefault(key, [])
        buf.append(wpa)
        del buf[:-_WINDOW]
        return True

    # ── reading ─────────────────────────────────────────────────────────
    def watts_per_amp(self, charger_id: str, phases: int) -> Optional[float]:
        """The measured W/A, or None while confidence is unearned."""
        buf = self._samples.get((str(charger_id), int(phases)))
        if not buf or len(buf) < MIN_SAMPLES:
            return None
        return statistics.median(buf)

    def refused(self, charger_id: str, phases: int) -> int:
        return self._refused.get((str(charger_id), int(phases)), 0)

    def refusal_reasons(self, charger_id: str, phases: int) -> dict:
        """Why samples were refused. ``phase_belief`` means the draw fits a
        DIFFERENT phase count — evidence about the belief, not about the car,
        and a hint to read the contradiction cap rather than this number."""
        return dict(self._reasons.get((str(charger_id), int(phases)), {}))

    def watts_for_amps(self, charger_id: str, phases: int, amps: float,
                       nominal_wpa: float) -> float:
        """What ``amps`` will really buy. Never MORE than nameplate: a
        measurement may free headroom, never license exceeding a cap."""
        wpa = self.watts_per_amp(charger_id, phases)
        eff = min(wpa, float(nominal_wpa)) if wpa is not None else float(nominal_wpa)
        return float(amps) * eff

    def amps_for_watts(self, charger_id: str, phases: int, watts: float,
                       nominal_wpa: float) -> int:
        """Amps that fit within ``watts``. Rounds DOWN: handing out an amp
        the car then exceeds is the one direction that can breach a limit."""
        wpa = self.watts_per_amp(charger_id, phases)
        eff = min(wpa, float(nominal_wpa)) if wpa is not None else float(nominal_wpa)
        if eff <= 0:
            return 0
        return int(float(watts) // eff)

    # ── surface ─────────────────────────────────────────────────────────
    def as_dict(self) -> dict:
        """Diagnostic shape: a person looking at '16 A' deserves to know
        SEM expects 10.0 kW, not 11.0 kW."""
        out: Dict[str, Dict[str, dict]] = {}
        for (cid, phases), buf in self._samples.items():
            if len(buf) < MIN_SAMPLES:
                continue
            med = statistics.median(buf)
            out.setdefault(cid, {})[str(phases)] = {
                "watts_per_amp": round(med, 1),
                "samples": len(buf),
                "refused": self._refused.get((cid, phases), 0),
                "nominal_ratio": None,
            }
        return out

    def as_dict_with_nominal(self, nominal_for) -> dict:
        """``as_dict`` with the nameplate ratio filled in, where the caller
        can supply the nominal per (charger, phases)."""
        d = self.as_dict()
        for cid, per in d.items():
            for ph, row in per.items():
                nom = nominal_for(cid, int(ph))
                if nom:
                    row["nominal_ratio"] = round(row["watts_per_amp"] / nom, 3)
        return d
