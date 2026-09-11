"""#708 — one function for "how many kWh to reach the SOC target".

The effective-SOC-remaining math had two homes: the stop decision
(``_ev_charging_need_kwh``) and, re-derived by hand, the estimate-stop /
resume announcement. Two copies of one rule drift — change the stop and the
announcement would tell a user "the estimate stopped your charge" while the
decision no longer does. This is the single source both call.

It also makes the #708 contract structural instead of commented. Three
inputs, and what each is allowed to do:

  * ``vehicle_soc``  — the real sensor. The floor of truth; always primary.
  * ``ceiling_soc``  — ``EVTaperDetector.energy_accounted_soc()``: the anchor
                       (a real reading) plus MEASURED delivery since. A CAP on
                       the stop, never a replacement, and — because
                       ``effective = max(sensor, ceiling)`` — it can only pull
                       the stop EARLIER, never charge past the sensor.
  * the speculative virtual/estimated SOC (driving decay, temperature,
    self-heal) is deliberately NOT a parameter here (#440/#446): it must
    never touch a stop.

``None`` results mean "no SOC information" — the caller falls back to its
pre-#708 behaviour (charge to the hardware taper), never a fabricated 0.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple


@dataclass(frozen=True)
class SocRemaining:
    """kWh still owed to reach the SOC target, two ways.

    ``effective_kwh <= sensor_kwh`` always (when both are known): the measured
    cap can only shorten a charge, never lengthen it.
    """

    sensor_kwh: Optional[float]
    """From the real sensor alone. ``None`` when no sensor reading exists."""

    effective_kwh: Optional[float]
    """After the measured cap. ``None`` when there is no SOC info at all
    (no sensor and no anchor)."""


def soc_remaining_need(
    target_soc: float,
    vehicle_soc: Optional[float],
    ceiling_soc: Optional[float],
    capacity_kwh: float,
) -> SocRemaining:
    """Compute the remaining need to ``target_soc``.

    See the module docstring for the contract on each input.
    """
    try:
        cap = float(capacity_kwh or 0.0)
    except (TypeError, ValueError):
        cap = 0.0
    if cap <= 0:
        return SocRemaining(sensor_kwh=None, effective_kwh=None)

    def _need(soc: Optional[float]) -> Optional[float]:
        if soc is None:
            return None
        return max(0.0, (target_soc - soc) / 100.0 * cap)

    # effective SOC = the real sensor, capped up by the MEASURED ceiling.
    # max() is the whole point: the sensor stays primary, the cap only ever
    # raises the believed SOC (→ shortens the charge), never lowers it.
    if vehicle_soc is None:
        effective_soc = ceiling_soc
    elif ceiling_soc is None:
        effective_soc = vehicle_soc
    else:
        effective_soc = max(vehicle_soc, ceiling_soc)

    return SocRemaining(sensor_kwh=_need(vehicle_soc),
                        effective_kwh=_need(effective_soc))


def estimate_stop_step(
    latched_bound: Optional[str],
    bounds: Sequence[Tuple[str, float]],
    vehicle_soc: Optional[float],
    ceiling_soc: Optional[float],
    capacity_kwh: float,
) -> Tuple[Optional[str], Optional[str], Optional[float]]:
    """(#939) One cycle of the #708 estimate-stop / resume announcement.

    ``bounds`` is ``(name, target_soc)`` in evaluation order (``min`` then
    ``max``). Returns ``(latched_bound, event, target_soc)``: the latch to
    keep, ``"stop"`` / ``"resume"`` / ``None``, and the target the event is
    about.

    A stop is announced for the first bound the sensor alone has NOT reached
    but the measured cap has; a resume only when THAT bound's effective need
    re-opens — a fresh reading landing below it, or its target raised. The
    latch used to be a bare flag, so the resume ran against every bound:
    stopped at Min (90 %), it was released on the next cycle by Max (100 %),
    which the capped estimate had of course not reached — and the stop
    re-fired the cycle after. Live 10.09: the pair alternated several times
    a minute until the owner moved Min. With the bound kept, identical
    inputs cannot produce a second event.
    """
    for name, target in bounds:
        if latched_bound is not None and name != latched_bound:
            continue
        need = soc_remaining_need(target, vehicle_soc, ceiling_soc, capacity_kwh)
        sensor_rem = need.sensor_kwh or 0.0
        eff_rem = need.effective_kwh or 0.0
        if latched_bound is None and sensor_rem > 0.1 and eff_rem <= 0.1:
            return name, "stop", target
        if latched_bound is not None and eff_rem > 0.1:
            return None, "resume", target
    return latched_bound, None, None
