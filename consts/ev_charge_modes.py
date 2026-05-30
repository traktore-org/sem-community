"""Canonical EV Charge mode names + mode-derivation helpers (#277).

The five consolidated user-intent modes that replace the four-toggle
soup (``ev_charging_mode`` × ``night_charging`` × ``tariff_optimized``
× ``smart_night_charging``). See
``docs/plans/2026-05-30_ev_charge_mode_consolidation.md`` for the
mapping table and migration semantics.

Lives in ``consts/`` so any caller (entity layer, coordinator,
state machine) can import the constants AND the
``effective_charge_mode_for`` resolver without circular dependencies.
Both ``SEMCoordinator`` and ``ChargingStateMachine`` use the same
resolver — there is one source of truth for "what mode is this
charger in?".
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:  # pragma: no cover — type-only
    from homeassistant.core import HomeAssistant


# Order matters: it's the order shown in the HA select UI.
EV_CHARGE_MODES: dict[str, str] = {
    "solar_only": "Solar only",
    "solar_plus_cheap": "Solar + cheapest hours",
    "min_plus_solar": "Min + Solar",
    "always_max": "Always (max)",
    "off": "Off",
}

# The new-install default. Q4 resolved 2026-05-30 — matches today's
# factory defaults (mode=pv + night=on + smart=on + tariff=off).
DEFAULT_EV_CHARGE_MODE: str = "min_plus_solar"


# ─────────────────────────────────────────────────────────────────
# Mode-driven effective-state predicates — #277 Phase B
# ─────────────────────────────────────────────────────────────────

MODE_NIGHT_ALLOWED: frozenset[str] = frozenset({
    "solar_plus_cheap", "min_plus_solar", "always_max",
})
MODE_USES_TARIFF: frozenset[str] = frozenset({
    "solar_plus_cheap",
})
MODE_USES_SMART_NIGHT: frozenset[str] = frozenset({
    "solar_plus_cheap", "min_plus_solar",
})
MODE_TO_LEGACY_CHARGING_MODE: dict[str, str] = {
    "solar_only":       "auto",
    "solar_plus_cheap": "auto",
    "min_plus_solar":   "minpv",
    "always_max":       "now",
    "off":              "off",
}


def effective_charge_mode_for(
    hass: "HomeAssistant",
    full_config: Mapping[str, Any],
    charger_cfg: Any,
) -> str:
    """Resolve the user-intent Charge mode for one charger.

    Reads ``charger_cfg["charge_mode"]`` when present (post-v5
    migration or after a user picks one in the selector). When absent
    — corrupted config, hand-edited storage — fall back to the
    new-install default.

    Pre-#277 Phase C this had a long legacy-derivation fallback that
    read ``switch.sem_charger_<id>_night_charging`` /
    ``..._tariff_optimized`` for installs that somehow skipped the
    Phase A migration. Phase C removed those switches, and the
    migration is mandatory on every config-entry load, so the
    derivation was dead code by the time it would have fired.

    The ``hass`` and ``full_config`` parameters are kept for call-site
    compatibility — they're no longer read but the four current
    callers ([SEMCoordinator], [ChargingStateMachine],
    [_tariff_optimized_for], [today_plan]) pass them as part of a
    stable signature.

    Returns one of ``EV_CHARGE_MODES`` keys; never raises.
    """
    if not isinstance(charger_cfg, dict):
        return DEFAULT_EV_CHARGE_MODE
    stored = charger_cfg.get("charge_mode")
    if stored in EV_CHARGE_MODES:
        return stored
    return DEFAULT_EV_CHARGE_MODE
