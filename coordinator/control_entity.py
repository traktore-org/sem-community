"""#824 — is the entity SEM is about to command actually there?

A dead SENSOR makes SEM's numbers look wrong, which people notice and
report. A dead CONTROL entity makes SEM look like it is working — a
commanded current on the dashboard, a strategy that explains itself, a
clean log — while the car does whatever it likes.

@onkelfu lost days to exactly that: one unsupported ``mode: slider`` line
in a template number meant HA never loaded the entity properly (it existed
only as ``restored: true``), so every write SEM made landed nowhere. He
found it by instrumenting the Modbus proxy himself.

SEM already had ``raise_charger_actuation_failed``, and it did not fire —
that Repair is driven by three consecutive writes that RAISED, and his
writes never raised. **The failure produces no error**, which is why this
check is a pre-flight look at the entity rather than error handling around
the write.

Pure and injectable, deliberately: no HA imports, ``state_of`` supplied by
the caller. Same shape as #814's ``validate_phase_switch_entity``, which
this generalises — that one only needed to know whether an entity existed,
and existence is precisely what is NOT the question here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

# Domains SEM can actually command. The ``input_*`` twins are first class:
# they are what people build when their charger exposes no native control,
# and #804 had to learn that lesson separately for phase switching.
CONTROL_ENTITY_DOMAINS = (
    "number", "input_number",
    "switch", "input_boolean",
    "select", "input_select",
)

# States that mean "this entity is not currently commandable". ``restored``
# entities — HA loaded a name from the registry but the platform never
# produced the entity — report exactly this.
_DEAD_STATES = ("unavailable", "unknown", "none", "")


@dataclass(frozen=True)
class ControlEntityVerdict:
    """What SEM believes about one configured control entity."""

    configured: Optional[str]
    """The entity_id the user named, or None when the capability is simply
    not configured."""

    valid: Optional[bool]
    """True when commandable, False when declared-but-broken, None when
    nothing was configured — absence of a capability is not a fault."""

    reason: Optional[str] = None
    """``wrong_domain`` / ``missing`` / ``unavailable``. Stable strings, so
    the Repair and the card can key off them rather than parse prose."""


def validate_control_entity(
    entity_id: Optional[str],
    state_of: Callable[[str], Optional[str]],
) -> ControlEntityVerdict:
    """Judge one configured control entity.

    ``state_of(entity_id)`` returns the entity's state string, or None when
    the entity does not exist. The state — not mere existence — is the
    question: a restored entity exists and cannot be commanded.
    """
    if not entity_id:
        return ControlEntityVerdict(None, None, None)

    domain = str(entity_id).split(".", 1)[0]
    if domain not in CONTROL_ENTITY_DOMAINS:
        return ControlEntityVerdict(entity_id, False, "wrong_domain")

    state = state_of(entity_id)
    if state is None:
        return ControlEntityVerdict(entity_id, False, "missing")
    if str(state).strip().lower() in _DEAD_STATES:
        return ControlEntityVerdict(entity_id, False, "unavailable")
    return ControlEntityVerdict(entity_id, True, None)
