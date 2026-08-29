"""#829 — retention for SEM's own fire-and-forget entities.

Guido, 22.08: *"an option to have certain retention on sensors — for most of
SEM's sensors the history isn't even important, these are fire and forget."*

He is right, and the measurement says exactly which ones:

    with ``state_class``   179 entities   182,080 rows/24h   hourly stats FOREVER
    no   ``state_class``   129 entities    31,280 rows/24h   no statistics, ever

Home Assistant compiles hourly long-term statistics for every entity that
carries a ``state_class``, and keeps them indefinitely — the rig still holds
October 2024 while its oldest *state* row is seven days old. That is the
user's real energy history and it must never be purged. An entity with no
``state_class`` has no statistics at all: its rows are short-term status and
nothing else.

So the purge list is DERIVED from "has no state_class" rather than maintained
by hand. That is what makes this safe by construction instead of by care — a
future statistics-bearing sensor opts *itself* out, and the failure mode that
would actually matter (a well-meant button eating two years of solar yield)
cannot happen.

The recorder's global ``purge_keep_days`` lives in ``configuration.yaml`` and
is none of SEM's business. This module only ever feeds
``recorder.purge_entities`` with entities SEM created.
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence, Tuple

#: Retention disabled — Home Assistant's own policy applies, unchanged.
RETENTION_OFF: int = 0

#: The prefix every SEM-created entity carries in its object id.
_SEM_OBJECT_PREFIX = "sem_"

#: Domains SEM creates entities in. A domain SEM does not own is never purged
#: even if the object id looks like ours.
_SEM_DOMAINS = ("sensor", "binary_sensor", "switch", "number", "select", "button")


def _is_sem_entity(entity_id: str) -> bool:
    try:
        domain, object_id = entity_id.split(".", 1)
    except ValueError:
        return False
    return domain in _SEM_DOMAINS and object_id.startswith(_SEM_OBJECT_PREFIX)


def purgeable_entities(
    entities: Iterable[Tuple[str, Optional[str]]],
) -> list[str]:
    """SEM's own entities whose states carry no long-term statistics.

    ``entities`` is an iterable of ``(entity_id, state_class)`` — the caller
    reads ``state_class`` from the live attributes. Anything with a
    ``state_class`` is excluded: it has hourly statistics that survive
    purging, and those are history worth keeping.

    Returns a sorted list so callers, logs and tests are deterministic.
    """
    out: list[str] = []
    for entity_id, state_class in entities:
        if not entity_id or not _is_sem_entity(entity_id):
            continue
        if state_class:  # "" / None both mean "no statistics"
            continue
        out.append(entity_id)
    return sorted(out)


def retention_is_due(
    retention_days, last_run_day: Optional[str], today: str,
) -> bool:
    """Whether a purge should run now — at most once per calendar day.

    ``RETENTION_OFF`` (or any value that is not a positive whole number of
    days) means the feature is off and nothing is ever purged.
    """
    try:
        days = int(retention_days)
    except (TypeError, ValueError):
        return False
    if days <= RETENTION_OFF:
        return False
    return last_run_day != today


def describe(entities: Sequence[str], retention_days: int) -> str:
    """One line for the log / the card, so the user can see what it covers."""
    return (
        f"{len(entities)} SEM status entities, keeping {retention_days} day(s); "
        "entities with long-term statistics are never included"
    )


async def run_purge(hass, retention_days) -> list[str]:
    """Purge SEM's statistics-less entities, keeping ``retention_days`` days.

    Shared by the "clean up now" service and the daily job so both can only
    ever act on the same derived list. ``hass`` is duck-typed (``states`` and
    ``services``) so this stays testable without a running Home Assistant.

    Returns the entities that were purged — empty when the feature is off or
    when SEM owns nothing purgeable.
    """
    try:
        days = int(retention_days)
    except (TypeError, ValueError):
        return []
    if days <= RETENTION_OFF:
        return []

    entities = purgeable_entities(
        (st.entity_id, (st.attributes or {}).get("state_class"))
        for st in hass.states.async_all()
    )
    if not entities:
        return []

    await hass.services.async_call(
        "recorder", "purge_entities",
        {"entity_id": entities, "keep_days": days},
        blocking=False,
    )
    return entities
