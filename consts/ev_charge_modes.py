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
    migration or after a user picks one in the selector). When absent,
    derives the equivalent named mode from the legacy four-toggle
    state — same decision tree as ``_derive_charge_mode`` in
    ``__init__.py`` so migration and runtime agree.

    Stateless / hass-state-only — takes ``hass`` only to read switch
    states for the legacy fallback. Used both by ``SEMCoordinator``
    (whole-cycle reads) and ``ChargingStateMachine`` (per-tick night
    enablement vote) so there is one shared resolver and no
    duplicated derivation logic between coordinator and state
    machine.

    Returns one of ``EV_CHARGE_MODES`` keys; never raises.
    """
    if not isinstance(charger_cfg, dict):
        return DEFAULT_EV_CHARGE_MODE

    stored = charger_cfg.get("charge_mode")
    if stored in EV_CHARGE_MODES:
        return stored

    # No stored mode (pre-migration / partially-configured install) —
    # derive it on the fly from the same legacy toggles the migration
    # reads. The decision tree mirrors ``__init__._derive_charge_mode``
    # exactly so a user who never migrates sees the same effective
    # behaviour as one who did.
    cid = charger_cfg.get("id", "ev_charger")
    mode = (
        charger_cfg.get("ev_charging_mode")
        or full_config.get("ev_charging_mode")
        or "pv"
    )
    night_eid = f"switch.sem_charger_{cid}_night_charging"
    if hass.states.get(night_eid) is not None:
        night = hass.states.is_state(night_eid, "on")
    elif hass.states.get("switch.sem_night_charging") is not None:
        night = hass.states.is_state("switch.sem_night_charging", "on")
    else:
        night = True  # factory default
    tariff_eid = f"switch.sem_charger_{cid}_tariff_optimized"
    tariff = hass.states.is_state(tariff_eid, "on") if (
        hass.states.get(tariff_eid) is not None
    ) else False

    if mode == "now":
        return "always_max"
    if mode == "off":
        return "off"
    # Tariff-on expresses an explicit "use cheap windows" intent that
    # applies regardless of whether the user picked "auto" or "pv" in
    # the legacy mode field — both groups exist in PROD setups.
    # Capturing both was the equivalence the Phase B test sweep flagged
    # (test_tariff_wait_when_cheap_window_ahead).
    if mode in ("pv", "auto", "self_consumption") and tariff:
        return "solar_plus_cheap"
    if mode in ("pv", "auto", "self_consumption") and not night:
        return "solar_only"
    return DEFAULT_EV_CHARGE_MODE
