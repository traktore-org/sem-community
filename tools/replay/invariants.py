"""(#1083) Named checks on a replayed day.

Every check says what kind it is, because only some may block a merge:

* ``exact`` — decided on the branch's own output from recorded inputs.
  Blocks a merge when it fails on a day that is not a gap day.
* ``relative`` — compares the branch with a base tree (develop) over the
  same day: a branch may not ADD a fault the base did not have. Blocks a
  merge when the branch is worse.
* ``modelled`` — would need the house's answer to a different decision
  (the counterfactual). Never blocks; none is built yet.

A check that cannot fail is a bug (class: the vacuous pass): every check
here has a test that makes it fail on a real recorded fault.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .engine import DayRun

#: corrected_remaining_kwh rounds to 2 dp
ROUNDING_KWH = 0.011
#: a one-cycle spike: this much higher than the cycle before …
SPIKE_RATIO = 1.8
SPIKE_MIN_W = 1000.0
#: … and back near where it was within this many cycles
SPIKE_BACK_CYCLES = 6
SPIKE_BACK_RATIO = 1.3
SPIKE_BACK_SLACK_W = 300.0


@dataclass
class Result:
    name: str
    kind: str                 # exact / relative / modelled
    ok: bool
    detail: str = ""
    evidence: List[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "ok": self.ok,
                "detail": self.detail, "evidence": self.evidence[:10]}


def forecast_overshoot(run: DayRun) -> Result:
    """(#1104) Before noon the plan's corrected rest-of-day solar is never
    above the provider's raw remainder."""
    bad = [{"hour": round(h, 2), "raw": round(raw, 2), "corrected": round(cor, 2)}
           for _, h, raw, cor in run.forecast if h < 12.0 and cor > raw + ROUNDING_KWH]
    if not run.forecast:
        return Result("forecast_overshoot", "exact", True, "no forecast recorded")
    worst = max(bad, key=lambda b: b["corrected"] - b["raw"]) if bad else None
    return Result("forecast_overshoot", "exact", not bad,
                  f"{len(bad)} steps above raw; worst {worst}" if bad else "never above raw",
                  bad)


def home_spikes(run: DayRun) -> List[dict]:
    """One-cycle spikes in the SHOWN home: a jump of at least
    ``SPIKE_RATIO`` × and ``SPIKE_MIN_W`` that falls back within
    ``SPIKE_BACK_CYCLES``. A real load stays; a counted-twice battery or a
    late register comes straight back (#1047, #1105)."""
    out = []
    home = run.home
    i = 1
    while i < len(home) - 1:
        before, now = home[i - 1][1], home[i][1]
        if now >= SPIKE_RATIO * before and now - before >= SPIKE_MIN_W:
            for k in range(1, SPIKE_BACK_CYCLES + 1):
                if i + k >= len(home):
                    break
                if home[i + k][1] <= SPIKE_BACK_RATIO * before + SPIKE_BACK_SLACK_W:
                    out.append({"t": round(home[i][0]), "before_w": round(before),
                                "spike_w": round(now), "cycles": k})
                    i += k
                    break
        i += 1
    return out


def home_spike_regression(run: DayRun, base: Optional[DayRun]) -> Result:
    """(#1047/#1105) The branch shows no one-cycle home spike the base did
    not show. Spikes the base also shows are listed, never blamed on the
    branch."""
    mine = home_spikes(run)
    if base is None:
        return Result("home_spike", "relative", True,
                      f"{len(mine)} spikes (no base to compare)", mine)
    theirs = {s["t"] for s in home_spikes(base)}
    new = [s for s in mine if s["t"] not in theirs]
    fixed = len(theirs) - (len(mine) - len(new))
    return Result("home_spike", "relative", not new,
                  f"{len(new)} new, {fixed} fixed, {len(mine) - len(new)} shared",
                  new or mine)


def no_writes(run: DayRun) -> Result:
    """Replay never writes: the replayed code made no service call."""
    return Result("no_writes", "exact", run.writes == 0, f"{run.writes} service calls")


DEFAULT = ("forecast_overshoot", "home_spike", "no_writes")


def check(run: DayRun, base: Optional[DayRun] = None,
          names=DEFAULT) -> Dict[str, Result]:
    out: Dict[str, Result] = {}
    for n in names:
        if n == "forecast_overshoot":
            out[n] = forecast_overshoot(run)
        elif n == "home_spike":
            out[n] = home_spike_regression(run, base)
        elif n == "no_writes":
            out[n] = no_writes(run)
        else:
            raise ValueError(f"unknown check {n!r}")
    return out


def blocking(results: Dict[str, Result], tags: List[str],
             base_results: Optional[Dict[str, Result]] = None) -> List[Result]:
    """The failures that refuse a merge: exact or relative, on a day that
    is not a gap day. A modelled check never blocks. An exact check that
    fails on the BASE too is inherited, not the branch's doing: it is
    reported, never blamed (otherwise every branch is refused until a
    base bug is fixed)."""
    if "gap" in (tags or []):
        return []
    out = []
    for name, r in results.items():
        if r.ok or r.kind not in ("exact", "relative"):
            continue
        if r.kind == "exact" and base_results is not None \
                and name in base_results and not base_results[name].ok:
            continue
        out.append(r)
    return out
