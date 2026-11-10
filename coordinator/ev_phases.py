"""#804 Phase A — the observe-only phase model. Pure: values in, values out.

evcc's field history (researched on the issue) says phase handling fails
in two places: capability INFERENCE (their #30143 — a wallbox running 3p
at boot was inferred "can't switch" from its current state) and
mid-charge switching quirks. SEM's answer to the first is here: the
capability is an ENTITY THE USER NAMES (``ev_phase_switch_entity``), and
this module only validates the declaration — it never probes and never
infers.

The active-phase ESTIMATE is the #716 measured-W/A model made
phase-aware: a charger's real draw over its commanded amps is
volts-actually-in-use, and that over the per-phase voltage ≈ active
phases. It both detects the car's actual phase use (a 3p wallbox feeding
a 1p car reads 1) and confirms a commanded switch physically took —
evcc needs a separate GetPhases poll for the same fact.

Phase A ships INERT (gate 4): nothing here — or in its callers — writes
to the named entity. Phases B-D (manual select, reactive auto, planner
block-boundary switching) build on this observation layer.
"""

from __future__ import annotations

import math as _math

from typing import Callable, Optional, Tuple

from ..utils.select_option import listed_option

# Below this draw the reading is ramp-up or trickle, not a measurement —
# same floor the W/A EMA uses (#638).
PHASE_MIN_WATTS = 400.0

# A phase estimate needs a commanded current to divide by.
PHASE_MIN_AMPS = 1

# The only domains that can PERFORM a phase switch. go-e exposes a
# select (``psm``), KEBA's X-series a number via Modbus, openWB a
# switch. A sensor is a reading, not an actuator — naming one is a
# config error worth surfacing.
PHASE_SWITCH_DOMAINS = ("select", "number", "switch",
                        "input_select", "input_number", "input_boolean")


def estimate_active_phases(
    watts: Optional[float],
    amps: Optional[int],
    voltage: float,
) -> Optional[int]:
    """Active phases from measured draw, or None when not measurable.

    Clamped to 1..3: a wrong amps reading must not invent a five-phase
    charger, and efficiency losses must not read as zero phases.
    """
    if watts is None or amps is None:
        return None
    if float(watts) < PHASE_MIN_WATTS or int(amps) < PHASE_MIN_AMPS:
        return None
    if voltage <= 0:
        return None
    ratio = float(watts) / float(amps) / float(voltage)
    # One phase carries at most ``amps × voltage`` watts, so the draw sets
    # a hard LOWER bound on the phase count. A car using less than the
    # offer drags the bare ratio down — live on PROD a Zoe at a 32 A offer
    # drew 10.15 kW (~15 A × 3 phases) and the ratio read "1-phase",
    # physically impossible at 7.36 kW per phase. The floor makes partial
    # draw read the honest lower bound (an ambiguous 2 keeps the auto
    # planner quiet); the ratio converges to exact truth whenever the car
    # actually uses the offer. 5% metering tolerance keeps a full-offer
    # 1-phase car from reading as 2. At deep partial draw the count is
    # fundamentally under-determined from watts+offer alone — the bound
    # is the most the physics can honestly say.
    floor = _math.ceil(ratio * 0.95)
    return max(1, min(3, max(round(ratio), floor)))


# Per-domain default values for the 1p/3p positions. select has NO
# default: its option strings are the device's own vocabulary (go-e's
# psm speaks numbers-as-modes, others speak words) — never guessed.
_SWITCH_VALUE_DEFAULTS = {
    "number": ("1", "3"),
    "input_number": ("1", "3"),
    "switch": ("off", "on"),
    "input_boolean": ("off", "on"),
}


def resolve_switch_values(entity_id: str, cfg: dict):
    """The (value_1p, value_3p, ready) triple for the named entity.

    Explicit ``ev_phase_switch_value_1p``/``_3p`` config wins (go-e's
    psm number uses 2 for 3-phase, so even number defaults are only
    defaults). ready=False when a required value is missing.
    """
    domain = str(entity_id or "").split(".", 1)[0]
    d1, d3 = _SWITCH_VALUE_DEFAULTS.get(domain, (None, None))
    v1 = cfg.get("ev_phase_switch_value_1p") or d1
    v3 = cfg.get("ev_phase_switch_value_3p") or d3
    return v1, v3, bool(v1 and v3)


def phase_switch_command(entity_id: str, value: str, hass):
    """The one service call a phase switch turns into, or None.

    (domain, service, service_data) — the caller owns the actual call,
    behind the same observer seam as every actuation. (#1039) ``hass`` is
    required, not optional: a select gets the option it LISTS for ``value``,
    never a label, and a caller that left it out would skip that silently.
    """
    domain = str(entity_id or "").split(".", 1)[0]
    if domain in ("select", "input_select"):
        return domain, "select_option", {
            "entity_id": entity_id,
            "option": listed_option(hass, entity_id, str(value))}
    if domain in ("number", "input_number"):
        return domain, "set_value", {
            "entity_id": entity_id, "value": float(value)}
    if domain in ("switch", "input_boolean"):
        service = "turn_on" if str(value).lower() == "on" else "turn_off"
        return domain, service, {"entity_id": entity_id}
    return None


def validate_phase_switch_entity(
    entity_id: Optional[str],
    entity_exists: Callable[[str], bool],
) -> Tuple[Optional[str], Optional[bool]]:
    """Validate the user-named switch entity: (configured, valid).

    Unconfigured is (None, None) — absence of the capability is not an
    error. Configured-but-missing or a non-actuator domain is
    (entity_id, False): the declaration is surfaced as broken instead of
    silently accepted.
    """
    if not entity_id:
        return None, None
    domain = str(entity_id).split(".", 1)[0]
    if domain not in PHASE_SWITCH_DOMAINS:
        return entity_id, False
    return entity_id, bool(entity_exists(entity_id))


# ── (#1015) Phases set by one current per phase ─────────────────────────
#
# Some chargers have no phase switch to name. They take one current PER
# PHASE through a service, and a phase at 0 A is off. The phase choice and
# the current are then ONE command: 1-phase at N A is (N, 0, 0), 3-phase is
# (N, N, N). Pure: the caller owns the call, behind the device's one seam.

def phase_currents(amps: float, phases: int) -> Optional[Tuple[int, int, int]]:
    """The three per-phase currents for ``amps`` on ``phases`` (1 or 3).

    None for anything else — and for a current that is not positive: a stop
    is never (0, 0, 0) on this path. A limit a box keeps would lock it
    (#976); the stop stays the charger's own stop.
    """
    try:
        a = int(round(float(amps)))
    except (TypeError, ValueError):
        return None
    if a <= 0 or phases not in (1, 3):
        return None
    return (a, a, a) if phases == 3 else (a, 0, 0)


def phases_from_readback(attributes, endings=("p1", "p2", "p3")) -> Optional[int]:
    """Phases the box says it took, from a per-phase read-back's attributes.

    1 or 3 when it can be read; None when it cannot (no attributes, a value
    that is not a number, two phases on, all off). None is "could not read",
    never "not switched" — the caller compares a number, not an absence.
    """
    if not isinstance(attributes, dict):
        return None
    values = []
    for end in endings:
        hit = [v for k, v in attributes.items()
               if str(k).lower().endswith(str(end).lower())]
        if len(hit) != 1:
            return None
        try:
            values.append(float(hit[0]))
        except (TypeError, ValueError):
            return None
    on = sum(1 for v in values if v > 0)
    if on == 3:
        return 3
    if on == 1 and values[0] > 0:
        return 1
    return None
