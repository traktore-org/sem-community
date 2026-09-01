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
    # (#885 matrix) The restored legacy ``pv`` mode: PV surplus plus the
    # home battery, and nothing else. #277 collapsed the pv /
    # self_consumption split and folded battery assist into
    # ``min_plus_solar`` alone — so letting the pack help the car ALSO
    # meant committing to a Min floor and grid backfill. Loads kept the
    # distinction (#620); this gives chargers the same choice back.
    "solar_plus_battery": "Solar + battery",
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
    "solar_plus_battery": "pv",   # (#885) literally the legacy mode it restores
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


def mode_allows_night_charging(
    full_config: Mapping[str, Any],
    charger_cfg: Any,
) -> bool:
    """Does this charger's mode permit night/grid charging at all? (#679)

    #634 settled the axis with Guido: the mode is the *daytime* axis and the
    "At least" floor is the overnight guarantee, in every mode — ``solar_only``
    included. The safety half of that deal is ``floor 0 = never``, which is how
    the #346 "solar_only never grids at night" contract survives as the default.

    The deal only holds if an *unset* floor reads as 0. It did not:

    * ``config_flow._install_defaults()`` persists ``daily_ev_target: 10`` into
      the entry on **every** install (``consts/core.py:DEFAULT_DAILY_EV_TARGET``).
    * An absent ``ev_target_soc`` resolves to **80** at read time.

    So the global value cannot distinguish "the user asked for an overnight
    guarantee" from "the installer filled the box in", and floor 0 was not a
    state a real install could be in. Every ``solar_only`` charger joined the
    night lane by default — which made it behaviourally identical to
    ``min_plus_solar``, i.e. not a distinct mode at all. onkelfu's install
    (#627) is the live case: charger 1 had no per-charger floor, inherited the
    seeded 10, and grid/battery-charged overnight under "Solar only".

    The floor therefore has to carry *intent*, so for ``solar_only`` it must be
    set **on this charger**, in the basis this charger actually targets — a
    global default is not an opt-in. The other night modes keep the global
    fallback: for them the overnight top-up is the point of the mode, not
    something to opt into, and reading a defaulted floor there is correct.

    Kept in ``consts/`` next to the mode resolver because
    ``SEMCoordinator._mode_allows_night_charging`` and
    ``ChargingStateMachine._night_capable`` were two hand-copied twins whose
    docstrings each said "keep in sync" — the standing invitation to drift that
    this module exists to remove.
    """
    mode = effective_charge_mode_for(None, full_config, charger_cfg)  # type: ignore[arg-type]
    if mode in MODE_NIGHT_ALLOWED:
        return True
    if mode not in ("solar_only", "solar_plus_battery"):
        return False
    # (#885) solar_plus_battery inherits solar_only's night contract
    # wholesale — never grids unless THIS charger carries an explicit
    # "At least" floor (#679: a seeded global default is not an opt-in).
    return solar_only_night_floor(charger_cfg) > 0.1


def solar_only_night_floor(charger_cfg: Any) -> float:
    """The explicitly-set overnight floor for a ``solar_only`` charger (#679).

    Per-charger only, and in the charger's own target basis — a ``%`` target
    stores its floor in ``ev_target_soc``, a kWh target in ``daily_ev_target``.
    The old gate read ``daily_ev_target`` regardless of ``ev_target_type``, so
    on an SOC-targeted charger it consulted a key the charger does not use.

    Returns 0.0 for anything unset or unparseable — the never-grids default.
    """
    if not isinstance(charger_cfg, dict):
        return 0.0
    target_type = str(charger_cfg.get("ev_target_type")
                      or charger_cfg.get("ev_target_mode") or "kwh").lower()
    key = "ev_target_soc" if target_type == "soc" else "daily_ev_target"
    raw = charger_cfg.get(key)
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0
