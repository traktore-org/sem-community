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

from typing import Callable, Optional, Tuple

# Below this draw the reading is ramp-up or trickle, not a measurement —
# same floor the W/A EMA uses (#638).
PHASE_MIN_WATTS = 400.0

# A phase estimate needs a commanded current to divide by.
PHASE_MIN_AMPS = 1

# The only domains that can PERFORM a phase switch. go-e exposes a
# select (``psm``), KEBA's X-series a number via Modbus, openWB a
# switch. A sensor is a reading, not an actuator — naming one is a
# config error worth surfacing.
PHASE_SWITCH_DOMAINS = ("select", "number", "switch")


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
    return max(1, min(3, round(ratio)))


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
