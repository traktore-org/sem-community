"""The three persisted switch flags — one record, one resolution order.

``observer_mode``, ``vacation_mode`` and ``energy_plan_actuation`` are the
toggles whose value must outlive a restart, because each one is a promise
about what SEM will do to real hardware while nobody is watching.

Each can be recorded in three places, and until this module they were read
by two different readers that disagreed:

  ``entry.options``  a runtime flip (``switch._persist_flag``, 2026-07-18)
  ``entry.data``     the install-flow choice
  restore store      the switch entity's own last state — the ONLY record a
                     legacy install has, and invisible to the coordinator

The switch reads all three (#777). Setup read the first two and built the
coordinator from ``config.get(key, default)``, so on a legacy install the
coordinator booted on the DEFAULT — armed — and only learned the truth when
the switch platform attached, minutes later on a busy start. That window is
the 2026-07-18 unprotected-window class, still open for exactly the installs
#777 left relying on restore.

So: resolve here, once, from the same three sources in the same order, and
PROMOTE what only the restore store knows into ``entry.options``. Promotion
matters as much as the read — HA prunes the restore store after
``STATE_EXPIRATION`` (7 days), so a read-only fix would quietly lapse on any
install that stayed off for a fortnight, and revert to the armed default.

Silence is not False. A key nobody ever recorded resolves to ``None``, and
the caller's own default decides — collapsing the two is how "unset" came to
mean "armed" in the first place.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Final, Optional

_LOGGER = logging.getLogger(__name__)

# What silence means per flag, on a genuinely fresh install. Observer and
# vacation off; actuation ON since the one-gate build (#638 C8 — the switch
# is the kill-switch, and a default-off would leave a solar_plus_cheap
# install with no cheap-window timing at all).
PERSISTED_FLAG_DEFAULTS: Final[Dict[str, bool]] = {
    "observer_mode": False,
    "vacation_mode": False,
    "energy_plan_actuation": True,
}


def switch_entity_id(key: str) -> str:
    """The restore store is keyed by entity_id, and the switch forces a
    stable one (``switch.py``: ``self.entity_id = f"switch.sem_{key}"``)
    precisely so it survives a language change. Same construction here —
    if the two ever drift the read goes silent, and silence means armed."""
    return f"switch.sem_{key}"


def _restored_switch_state(hass: Any, entity_id: str) -> Optional[str]:
    """This entity's state from the previous run, or None.

    Read straight from the restore-state helper's loaded cache. HA's
    bootstrap awaits ``restore_state.async_load`` in the same gather that
    initializes the config entries, both well before any entry is set up,
    so the cache is populated by the time this runs. If it somehow is not,
    the miss is indistinguishable from "no record" and the caller falls
    back to today's behaviour — never worse.
    """
    try:
        from homeassistant.helpers import restore_state

        stored = restore_state.async_get(hass).last_states.get(entity_id)
    except Exception as exc:  # noqa: BLE001 — a setup path must never die here
        _LOGGER.debug("Restore-store read failed for %s: %s", entity_id, exc)
        return None
    if stored is None:
        return None
    state = getattr(stored, "state", None)
    return getattr(state, "state", None)


def resolve_persisted_flag(hass: Any, entry: Any, key: str) -> Optional[bool]:
    """The recorded value of ``key``, or None if it was never recorded.

    options, then data, then the switch's own restore state — the exact
    order ``switch._configured`` / ``_apply_restored_state`` use, so the
    coordinator and its switch can no longer answer differently.
    """
    from collections.abc import Mapping

    for src in (getattr(entry, "options", None), getattr(entry, "data", None)):
        if isinstance(src, Mapping) and key in src:
            return bool(src[key])

    # Only a DEFINITE on/off is a record. The switch is a CoordinatorEntity
    # whose availability flaps, so ``unavailable``/``unknown`` reached the
    # store as easily as a real value; reading those as "off" is how a
    # hands-off install would re-arm itself (same contract as the
    # coordinator's per-cycle ``_sync_observer_mode_from_switch``).
    restored = _restored_switch_state(hass, switch_entity_id(key))
    if restored in ("on", "off"):
        return restored == "on"
    return None


def promote_persisted_flags(
    hass: Any, entry: Any, config: Dict[str, Any],
) -> Dict[str, bool]:
    """Close the window before the coordinator opens it.

    For every flag the config does not carry, take what the restore store
    knows, put it in ``config`` (so the coordinator is built with it) and
    write it into ``entry.options`` (so nothing has to ask the store again).
    Returns what was promoted — empty on any install that already has an
    explicit record, which is every install created by the current flow.

    The options write is deliberately done here, BEFORE
    ``entry.add_update_listener`` attaches later in setup: there is no
    listener yet, so it cannot trigger a reload and needs none of the
    ``_skip_options_reload`` machinery.
    """
    promoted: Dict[str, bool] = {}
    for key in PERSISTED_FLAG_DEFAULTS:
        if key in config:
            continue  # already explicit — options or data spoke
        value = resolve_persisted_flag(hass, entry, key)
        if value is None:
            continue  # nobody ever said; the per-key default decides
        config[key] = value
        promoted[key] = value

    if promoted:
        _LOGGER.warning(
            "Recovered %s from the switch restore store — this install "
            "predates the persisted toggles, so the setting was invisible "
            "to the coordinator until its switch attached. Written to the "
            "config entry; it will be read directly from now on.",
            ", ".join(f"{k}={'on' if v else 'off'}"
                      for k, v in sorted(promoted.items())),
        )
        try:
            hass.config_entries.async_update_entry(
                entry, options={**(getattr(entry, "options", None) or {}),
                                **promoted},
            )
        except Exception as exc:  # noqa: BLE001 — the in-memory fix still stands
            _LOGGER.warning("Could not persist recovered flags: %s", exc)

    return promoted
