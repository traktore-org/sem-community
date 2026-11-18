"""(#846) Measured watts-per-amp — SEM checks the result of its own command.

26.08, watching PROD: *"the A to the charger is a choice of SEM,
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
  gates behaviour is not allowed to die at boot, the #638 night-2 rule);
* **says what its refusals mean** (#967) — the band is the only place in SEM
  that can see a wrong ``ev_phases``, because a draw on the wrong number of
  phases is exactly what it rejects. Refusing was all it did: the count went
  into a dict no Repair, no card and not even the diagnostics download ever
  read, while every amp SEM commanded went on being converted through a
  nameplate the meter had already refuted. ``phase_verdict`` turns those
  refusals into an answer — and only when they can honestly carry one.
"""
from __future__ import annotations

import math
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

# ── (#967) when refusals may be spent as a verdict about the CONFIG ──────
#: Steady, non-tapering, refused cycles before SEM will contradict the
#: owner's own configuration. Far above ``MIN_SAMPLES``: accepting a
#: measurement is cheap and reversible, accusing a setting is neither.
PHASE_VERDICT_REFUSALS: int = 20
#: Refused samples a single setpoint needs before its median is a number.
_REFUSED_MIN_PER_BUCKET: int = 3
#: Metering tolerance, the same 5 % ``estimate_active_phases`` allows.
_PHASE_TOLERANCE: float = 0.95
#: Two commanded setpoints must differ by at least this factor before a LOW
#: draw may be read as a phase count. A fixed power cap gives W/A ∝ 1/amps;
#: a phase count gives the SAME W/A at every setpoint. 1.4 clears the
#: smallest step the surplus ladder actually takes.
_SPREAD_MIN: float = 1.4
#: How far two setpoints' implied counts may sit apart and still be one
#: number.
_IMPLIED_AGREEMENT: float = 0.25
#: How close the agreed number must sit to a real phase count. An implied
#: 2.0 is nobody's answer and must stay unspoken.
_IMPLIED_TIGHTNESS: float = 0.35
#: Setpoints the agreeing top of the ladder needs (#1376).
_PLATEAU_MIN_POINTS: int = 3

Key = Tuple[str, int, int]


def _top_plateau(implied: Dict[int, float]) -> Optional[list]:
    """(#1376) The implied phase counts of the HIGH setpoints that agree,
    or None when they do not make a ladder.

    A car that is slow to follow a new current reads LOW at the setpoints
    SEM has only just stepped onto (a Go 2 with an e-Niro: 0.49 at 8 A,
    0.80-0.88 from 12 A up). Lag only ever lowers a draw, so walk down
    from the highest setpoint and keep every one within
    ``_IMPLIED_AGREEMENT`` of it. Three guards against a power cap, whose
    ``W/A ∝ 1/amps`` curve rises as the offer falls:

    * when setpoints are left out, at least ``_PLATEAU_MIN_POINTS`` agree,
      spread ``_SPREAD_MIN`` apart;
    * every setpoint left out reads BELOW the plateau — a ramp does, a cap
      reads above it."""
    top = max(implied)
    anchor = implied[top]
    kept = {a: v for a, v in implied.items()
            if abs(v - anchor) <= _IMPLIED_AGREEMENT}
    dropped = {a: v for a, v in implied.items() if a not in kept}
    # A ladder that agrees all the way down needs no more than two points
    # (the rule before #1376); leaving points out asks for three.
    if dropped and len(kept) < _PLATEAU_MIN_POINTS:
        return None
    if len(kept) < 2 or top / min(kept) < _SPREAD_MIN:
        return None
    mean = sum(kept.values()) / len(kept)
    if any(v >= mean for v in dropped.values()):
        return None
    return list(kept.values())


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
        # (#967) The refusals' own CONTENT, per setpoint — what separates a
        # phase count from a car that simply declines part of the offer.
        # Windowed like ``_samples``: the evidence a verdict quotes must be
        # evidence it still holds.
        self._refused_wpa: Dict[Key, list] = {}
        #: nameplate per (charger, phases) — the learner is told it, so it
        #: can recover the per-phase voltage without being handed config.
        self._nominal: Dict[Tuple[str, int], float] = {}

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
            # (#967) Both reasons are kept: which of the two ``record``
            # prints is a naming call made one sample at a time, and the
            # question "how many phases is this?" is answered over the whole
            # ladder. A 2-phase-looking draw under a 1-phase belief reads
            # ``implausible`` here and still refutes the belief outright.
            rbuf = self._refused_wpa.setdefault((pkey[0], pkey[1], bucket), [])
            rbuf.append(wpa)
            del rbuf[:-_WINDOW]
            self._nominal[pkey] = nominal
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

    def _implied_per_setpoint(self, cid: str, ph: int) -> Dict[int, float]:
        """(#967) ``{commanded amps: phases the draw implies}`` over the
        refused setpoints that hold enough samples to have a median."""
        nominal = self._nominal.get((cid, ph))
        if not nominal or nominal <= 0:
            return {}
        per_phase = float(nominal) / float(ph)     # ≈ the voltage
        if per_phase <= 0:
            return {}
        out: Dict[int, float] = {}
        for (c, p, amps), buf in self._refused_wpa.items():
            if c == cid and p == ph and len(buf) >= _REFUSED_MIN_PER_BUCKET:
                out[amps] = statistics.median(buf) / per_phase
        return out

    def phase_verdict(self, charger_id: str, phases: int) -> Optional[dict]:
        """(#967) How many phases the MEASUREMENTS say this charger draws on,
        when they can say it — else ``None``.

        The physics is asymmetric, and the answer has to be too.

        **More phases than believed is determinate.** One phase carries at
        most ``amps × voltage`` watts, so a draw above that REFUTES the belief
        outright, at any single setpoint — the #804 estimator's own floor
        (``ceil(implied × 0.95)``), reused here. This is the direction that
        matters: believing 1 where 3 are wired makes SEM command three times
        the watts it thinks it bought, through a peak limit.

        **Fewer phases than believed is under-determined.** A car taking a
        third of the offer and a car on one of three phases look identical at
        one setpoint (PROD: a Zoe at a 32 A offer read "1 phase" at 10.15 kW,
        which is impossible at 7.36 kW per phase). What separates them is the
        LADDER: a fixed power cap gives ``W/A ∝ 1/amps``, a phase count gives
        the same W/A at every setpoint. So this direction needs two setpoints
        at least ``_SPREAD_MIN`` apart whose implied counts agree — and where
        SEM never moved the setpoint, it says nothing, which is the honest
        answer rather than a guess that costs the owner 7 kW.

        Two further conditions, both about not crying wolf:
        ``PHASE_VERDICT_REFUSALS`` steady non-tapering cycles behind it, and
        **no bucket under this belief having ever earned trust** — a belief
        that explains real draw is not on trial.

        Returns ``{"believed", "measured", "samples", "watts_per_amp",
        "setpoints"}``; ``samples`` counts only evidence still held, so the
        number a Repair quotes never drifts from the median beside it.
        """
        cid, ph = str(charger_id), int(phases)
        if ph not in _PHASE_COUNTS:
            return None
        for (c, p, _a), buf in self._samples.items():
            if c == cid and p == ph and len(buf) >= MIN_SAMPLES:
                return None
        held = [(a, buf) for (c, p, a), buf in self._refused_wpa.items()
                if c == cid and p == ph]
        total = sum(len(buf) for _a, buf in held)
        implied = self._implied_per_setpoint(cid, ph)
        if total < PHASE_VERDICT_REFUSALS or not implied:
            return None
        nominal = float(self._nominal[(cid, ph)])
        per_phase = nominal / float(ph)

        measured = None
        # ── determinate: the draw does not fit on this many phases ──
        bound = min(math.ceil(v * _PHASE_TOLERANCE) for v in implied.values())
        if bound > ph:
            measured = next((p for p in _PHASE_COUNTS if p >= bound), None)
        # ── under-determined: only the ladder can answer ──
        elif len(implied) >= 2:
            vals = _top_plateau(implied)
            if vals is not None:
                mean = sum(vals) / len(vals)
                near = min(_PHASE_COUNTS, key=lambda p: abs(mean - p))
                if near < ph and abs(mean - near) < _IMPLIED_TIGHTNESS:
                    measured = near
        if measured is None or measured == ph:
            return None
        wpa = [x for _a, buf in held for x in buf]
        return {
            "believed": ph,
            "measured": int(measured),
            "samples": int(total),
            "watts_per_amp": round(statistics.median(wpa), 1),
            "setpoints": sorted(int(a) for a in implied),
            "nominal_wpa": round(per_phase * ph, 1),
        }

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
            # (#967) the refusals' content. A verdict that died at boot would
            # re-earn its 20 cycles every restart — or never reach them on a
            # car that charges in short bursts.
            "refused_wpa": {f"{c}|{p}|{a}": [round(x, 2) for x in buf]
                            for (c, p, a), buf in self._refused_wpa.items() if buf},
            "nominal": {f"{c}|{p}": round(n, 2)
                        for (c, p), n in self._nominal.items() if n > 0},
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
        for key, buf in (state.get("refused_wpa") or {}).items():
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
            self._refused_wpa[(c, p, a)] = vals[-_WINDOW:]
        for key, n in (state.get("nominal") or {}).items():
            try:
                c, p = str(key).split("|")
                p, n = int(p), float(n)
            except (TypeError, ValueError):
                continue
            if p in _PHASE_COUNTS and n > 0:
                self._nominal[(c, p)] = n

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
                # (#967) the refusals' own content, so the download answers
                # "is the phase count right?" instead of needing a screenshot
                # and a multiplication.
                "implied_phases": {},
                "phase_verdict": None,
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
        for (cid, ph, _a) in list(self._refused_wpa):
            row(cid, ph)
        # Once per row, not once per ``setdefault`` (the diagnostic rides the
        # per-cycle sensor-attribute path).
        for cid, per in out.items():
            for ph, r in per.items():
                r["implied_phases"] = {
                    str(a): round(v, 2)
                    for a, v in self._implied_per_setpoint(cid, int(ph)).items()}
                r["phase_verdict"] = self.phase_verdict(cid, int(ph))
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
