"""(#846) Measured watts-per-amp — SEM checks the result of its own command.

Guido, 26.08, watching PROD: *"the A to the charger is a choice of SEM,
therefore the math is not correcting itself. The idea is from EVCC: fire,
check, adjust."* SEM commanded 16 A, believed it had bought 11.04 kW
(16 × 3 × 230), and the car drew 10.02 kW — a 9 % error on SEM's own
decision, re-issued every cycle and never questioned.

The FIRST build kept one number per (charger, phase count). PROD's own
recorder disproved it the same evening — the car's draw is a function of
the SETPOINT, not a constant:

    8 A → 3.32 kW (415 W/A)  ·  10 A → 5.13 (513)  ·  12 A → 7.13 (594)
    14 A → 8.57 (612)        ·  16 A → 10.02 (626)

Learned at 8 A, a flat model predicts 6.6 kW for 16 A; the car takes 10.0.
That is a 3.4 kW error in the one direction that breaches a budget. So the
commanded amps are part of the key, and each bucket is its own fact.

Design:

* keyed by **(charger, phase count, commanded amps)** — the belief anchors
  the phase count; the learner never argues with it;
* **a median over a short window** per bucket — robust to one blip, and an
  old sample never outvotes today's;
* between two measured setpoints the draw is **bridged linearly in watts**
  — a bridge, not a fact: it lets SEM step onto a setpoint it has not
  measured yet, and the measurement replaces it the first time it stands
  there. Outside the measured range: nameplate;
* **refuses** what it cannot honestly explain — a sample outside a wide
  band around nameplate is a phase-belief question or a taper, and the
  honest answer is nameplate plus a diagnostic naming the reason;
* **never widens a limit** — a measurement may lower what SEM believes it
  bought (freeing headroom), never justify exceeding a configured cap;
  ``amps_for_watts`` walks the ladder DOWN and returns the largest setpoint
  that fits;
* **survives a restart** — ``as_state``/``restore`` (learned state that
  gates behaviour is not allowed to die at boot, the #638 night-2 rule).
"""
from __future__ import annotations

import statistics
from typing import Dict, Optional, Tuple

#: Samples a bucket needs before it is trusted.
MIN_SAMPLES: int = 5
#: Plausible band around nameplate. The floor is wide on purpose: a Zoe at
#: 8 A draws 0.60 of nameplate as a matter of course (PROD 26.08). A 1-phase
#: draw under a 3-phase belief lands at 0.33, a 3-phase draw under a 1-phase
#: belief at 3.0 — both still far outside.
MIN_RATIO: float = 0.5
MAX_RATIO: float = 1.05
#: Window per bucket — ten minutes of steady cycles; an old sample should
#: not outvote today's.
_WINDOW: int = 20
_PHASE_COUNTS = (1, 3)

Key = Tuple[str, int, int]


# ── the pure conversions ─────────────────────────────────────────────────
# Shared by the learner and by the PURE decide layer (which receives the
# table on the ChargerView and must not import the learner).
def predict_watts(table, amps: float, nominal_wpa: float) -> float:
    """What ``amps`` will really buy given a measured ``{amps: W/A}`` table:
    the bucket where one exists; bridged linearly in watts between the
    nearest measured setpoints; nameplate outside the measured range.
    Never MORE than nameplate."""
    a = int(round(float(amps)))
    if a < 1:
        return 0.0
    nominal = float(nominal_wpa)
    cap = a * nominal
    t = {int(k): float(v) for k, v in (table or {}).items()}
    if a in t:
        return min(cap, a * t[a])
    below = [x for x in t if x < a]
    above = [x for x in t if x > a]
    if not below or not above:
        return cap
    a1, a2 = max(below), min(above)
    w1, w2 = a1 * t[a1], a2 * t[a2]
    return min(cap, w1 + (w2 - w1) * (a - a1) / (a2 - a1))


def amps_that_fit(table, watts: float, nominal_wpa: float, max_amps: int) -> int:
    """The largest setpoint (≤ ``max_amps``) whose predicted draw fits within
    ``watts``. Walks the ladder DOWN and rounds DOWN: handing out an amp the
    car then exceeds is the one direction that can breach a limit. 0 when
    nothing fits. Without a table this is the nameplate ``watts // W/A``."""
    budget = float(watts)
    for a in range(int(max_amps), 0, -1):
        if predict_watts(table, a, nominal_wpa) <= budget:
            return a
    return 0


class WattsPerAmpLearner:
    """Per (charger, phase count, commanded amps) watts-per-amp, learned
    from observation."""

    def __init__(self) -> None:
        self._samples: Dict[Key, list] = {}
        # refusals are about the (charger, phases) belief, not one setpoint
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
        if amps < 1 or watts <= 0 or nominal <= 0:
            return False
        bucket = int(round(amps))
        wpa = watts / bucket
        pkey = (str(charger_id), int(phases))

        # ONE refusal gate — the plausible band around nameplate — with TWO
        # reasons, because they mean different things to a person reading
        # the diagnostic: ``phase_belief`` means the draw fits a DIFFERENT
        # phase count (evidence about the belief, not the car).
        ratio = wpa / nominal
        if not (MIN_RATIO <= ratio <= MAX_RATIO):
            per_phase = nominal / float(phases)      # ≈ the voltage
            implied = wpa / per_phase                # ≈ the phase count drawn
            fits = min(_PHASE_COUNTS, key=lambda p: abs(implied - p))
            reason = ("phase_belief" if fits != int(phases) and
                      abs(implied - fits) < 0.35 else "implausible")
            self._refused[pkey] = self._refused.get(pkey, 0) + 1
            self._reasons.setdefault(pkey, {})
            self._reasons[pkey][reason] = self._reasons[pkey].get(reason, 0) + 1
            return False

        buf = self._samples.setdefault((pkey[0], pkey[1], bucket), [])
        buf.append(wpa)
        del buf[:-_WINDOW]
        return True

    # ── reading ─────────────────────────────────────────────────────────
    def watts_per_amp(self, charger_id: str, phases: int,
                      amps: float) -> Optional[float]:
        """This bucket's measured W/A, or None while confidence is unearned.
        A bucket fact — no bridging here."""
        buf = self._samples.get((str(charger_id), int(phases), int(round(float(amps)))))
        if not buf or len(buf) < MIN_SAMPLES:
            return None
        return statistics.median(buf)

    def measured(self, charger_id: str, phases: int) -> Dict[int, float]:
        """``{amps: W/A}`` for every trusted bucket of this (charger, phases)."""
        out: Dict[int, float] = {}
        for (cid, ph, amps), buf in self._samples.items():
            if cid == str(charger_id) and ph == int(phases) and len(buf) >= MIN_SAMPLES:
                out[amps] = statistics.median(buf)
        return out

    def refused(self, charger_id: str, phases: int) -> int:
        return self._refused.get((str(charger_id), int(phases)), 0)

    def refusal_reasons(self, charger_id: str, phases: int) -> dict:
        return dict(self._reasons.get((str(charger_id), int(phases)), {}))

    def is_cold(self, charger_id: str, phases: int) -> bool:
        """True when this charger has never been fed under THIS phase count
        — not one sample, not one refusal. A refusal is evidence of having
        been fed; a cold (charger, phases) pair is what a replay from
        history is for. Per phase count on purpose: PROD 26.08 ran a day on
        a mis-set ``ev_phases`` and every sample was (rightly) refused —
        correcting the count must let the same history teach again."""
        cid, ph = str(charger_id), int(phases)
        if any(k[0] == cid and k[1] == ph and buf for k, buf in self._samples.items()):
            return False
        return not self._refused.get((cid, ph))

    def watts_for_amps(self, charger_id: str, phases: int, amps: float,
                       nominal_wpa: float) -> float:
        """What ``amps`` will really buy on this charger — see
        :func:`predict_watts`."""
        return predict_watts(self.measured(charger_id, phases), amps, nominal_wpa)

    def amps_for_watts(self, charger_id: str, phases: int, watts: float,
                       nominal_wpa: float, max_amps: int) -> int:
        """The largest setpoint that fits — see :func:`amps_that_fit`."""
        return amps_that_fit(self.measured(charger_id, phases), watts,
                             nominal_wpa, max_amps)

    # ── persistence ─────────────────────────────────────────────────────
    def as_state(self) -> dict:
        """JSON-safe: flat ``"cid|phases|amps"`` keys."""
        return {
            "samples": {f"{c}|{p}|{a}": [round(x, 2) for x in buf]
                        for (c, p, a), buf in self._samples.items() if buf},
            "refused": {f"{c}|{p}": n for (c, p), n in self._refused.items() if n},
            "reasons": {f"{c}|{p}": dict(r) for (c, p), r in self._reasons.items() if r},
        }

    def restore(self, state) -> None:
        """Per-entry repair (the #563 rule): a corrupt entry is dropped
        alone, the rest restore. Nothing is a no-op."""
        if not isinstance(state, dict):
            return
        for key, buf in (state.get("samples") or {}).items():
            try:
                c, p, a = str(key).split("|")
                p, a = int(p), int(a)
                vals = [float(x) for x in buf]
            except (TypeError, ValueError, AttributeError):
                continue
            if p not in _PHASE_COUNTS or a < 1 or not vals:
                continue
            if any(v <= 0 for v in vals):
                continue
            self._samples[(c, p, a)] = vals[-_WINDOW:]
        for key, n in (state.get("refused") or {}).items():
            try:
                c, p = str(key).split("|")
                p, n = int(p), int(n)
            except (TypeError, ValueError):
                continue
            if p in _PHASE_COUNTS and n > 0:
                self._refused[(c, p)] = n
        for key, reasons in (state.get("reasons") or {}).items():
            try:
                c, p = str(key).split("|")
                p = int(p)
                r = {str(k): int(v) for k, v in dict(reasons).items()}
            except (TypeError, ValueError, AttributeError):
                continue
            if p in _PHASE_COUNTS and r:
                self._reasons[(c, p)] = r

    # ── surface ─────────────────────────────────────────────────────────
    def as_dict(self) -> dict:
        """Diagnostic shape per charger and phase count: the trusted table
        (``{amps: W/A}``), sample counts per bucket (so a bucket still
        earning confidence is visible), and the refusals with their reasons
        — "SEM has no measurement" and "SEM measured and refused" are
        different statements, and a reader deserves the difference."""
        out: Dict[str, Dict[str, dict]] = {}

        def row(cid: str, ph: int) -> dict:
            return out.setdefault(cid, {}).setdefault(str(ph), {
                "table": {}, "samples": {}, "nominal_ratio": {},
                "refused": self._refused.get((cid, ph), 0),
                "refusal_reasons": dict(self._reasons.get((cid, ph), {})),
            })

        for (cid, ph), n in self._refused.items():
            if n:
                row(cid, ph)
        for (cid, ph, amps), buf in sorted(self._samples.items()):
            if not buf:
                continue
            r = row(cid, ph)
            r["samples"][str(amps)] = len(buf)
            if len(buf) >= MIN_SAMPLES:
                r["table"][str(amps)] = round(statistics.median(buf), 1)
        return out

    def as_dict_with_nominal(self, nominal_for) -> dict:
        """``as_dict`` with each bucket's ratio to nameplate filled in."""
        d = self.as_dict()
        for cid, per in d.items():
            for ph, r in per.items():
                nom = nominal_for(cid, int(ph))
                if not nom:
                    continue
                for amps, wpa in r["table"].items():
                    r["nominal_ratio"][amps] = round(wpa / nom, 3)
        return d
