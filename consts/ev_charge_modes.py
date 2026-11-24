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
    # (#1411) Shown as "Solar + tariff": it follows the prices on ANY tariff
    # — the cheap hours of a dynamic or two-rate one, and on every tariff
    # the thin-sun rule (``coordinator/thin_sun.py``). The key stays.
    "solar_plus_cheap": "Solar + tariff",
    "min_plus_solar": "Min + Solar",
    "always_max": "Always (max)",
    "off": "Off",
}

# ─────────────────────────────────────────────────────────────────
# (#1381 charger owner S9) The four modes the user sees
# ─────────────────────────────────────────────────────────────────
#
# Six stored strategies stay the engine's vocabulary — 285 production reads
# and every replayed day speak them, so storing anything else would make the
# change a data migration with no behaviour to gain. The user picks one of
# FOUR modes plus one switch, "May the battery help the car?". The pair maps
# onto exactly one stored strategy, so an existing install reads the same
# strategy before and after the update (neutral by construction):
#
#   Sun          + help off → solar_only        + help on → solar_plus_battery
#   Sun + tariff + help off → solar_plus_cheap  + help on → min_plus_solar
#   Now                     → always_max (no end: "until full"; a timed Now is
#                             the plan override "force", which ends by itself)
#   Off                     → off
USER_MODES: dict[str, str] = {
    "sun": "Sun",
    "sun_tariff": "Sun + tariff",
    "now": "Now",
    "off": "Off",
}
#: The per-charger memory of the battery-help switch. The strategy carries it
#: for the four sun strategies; Now and Off cannot, so it is kept here too and
#: a return from Now/Off picks the same help as before.
BATTERY_HELP_KEY = "ev_battery_help"

_STRATEGY_USER_MODE: dict[str, str] = {
    "solar_only": "sun",
    "solar_plus_battery": "sun",
    "solar_plus_cheap": "sun_tariff",
    "min_plus_solar": "sun_tariff",
    "always_max": "now",
    "off": "off",
}
_HELP_OF_STRATEGY: dict[str, bool] = {
    "solar_only": False,
    "solar_plus_battery": True,
    "solar_plus_cheap": False,
    "min_plus_solar": True,
}
_STRATEGY_FOR: dict[tuple, str] = {
    ("sun", False): "solar_only",
    ("sun", True): "solar_plus_battery",
    ("sun_tariff", False): "solar_plus_cheap",
    ("sun_tariff", True): "min_plus_solar",
}


def user_mode_of(strategy: Any) -> str:
    """The mode the user sees for a stored strategy (or a user mode)."""
    s = str(strategy or "")
    if s in USER_MODES:
        return s
    return _STRATEGY_USER_MODE.get(s, _STRATEGY_USER_MODE[DEFAULT_EV_CHARGE_MODE])


def battery_help_of(charger_cfg: Any) -> bool:
    """Does this charger's battery-help switch read ON?

    The stored strategy answers for the four sun strategies; Now and Off
    keep the remembered switch (``BATTERY_HELP_KEY``), else ON — the
    new-install default (Sun + tariff with help) carries it. A per-charger
    "never" (``ev_battery_may_assist: False``, #885) always reads OFF: the
    switch shows what the battery may really do.
    """
    if not isinstance(charger_cfg, Mapping):
        return True
    if charger_cfg.get("ev_battery_may_assist") is False:
        return False
    stored = str(charger_cfg.get("charge_mode") or "")
    if stored in _HELP_OF_STRATEGY:
        return _HELP_OF_STRATEGY[stored]
    remembered = charger_cfg.get(BATTERY_HELP_KEY)
    return True if remembered is None else bool(remembered)


def strategy_for(user_mode: str, battery_help: bool) -> str:
    """The one stored strategy for a (mode, battery help) pair."""
    if user_mode == "now":
        return "always_max"
    if user_mode == "off":
        return "off"
    return _STRATEGY_FOR[(user_mode, bool(battery_help))]


def apply_user_mode_write(charger: dict, key: str, value: Any) -> None:
    """Write one per-charger key, in place; ``charge_mode`` and the
    battery-help switch become the stored pair. THE one place both config writers (the per-charger
    entity path and ``set_option``'s merge) go through.

    * ``charge_mode`` = a user mode (sun, sun_tariff, now, off) → the stored
      strategy for it with this charger's current help.
    * ``charge_mode`` = an old strategy name → stored as it is (an alias:
      automations and the six old names keep working), help remembered.
    * ``ev_battery_help`` = bool → remembered; in Sun / Sun + tariff the
      strategy follows. Turning help ON also lifts a per-charger "never"
      (#885 ``ev_battery_may_assist``): the switch is the user's word.
    """
    if not isinstance(charger, dict):
        return
    if key == "charge_mode":
        v = str(value or "") if value is not None else value
        prev = str(charger.get("charge_mode") or "")
        help_now = battery_help_of(charger)    # read BEFORE the write
        if (isinstance(v, str) and v in USER_MODES and v not in EV_CHARGE_MODES
                and prev in EV_CHARGE_MODES and user_mode_of(prev) == v):
            # (#1381 D21) Re-picking the mode the select already shows is a
            # no-op: the strategy behind it stays. Mapping it again through
            # the switch rewrote min_plus_solar to solar_plus_cheap for a
            # charger with a per-charger "never" (the switch reads off there)
            # and so dropped its Min floor.
            v = prev
        elif isinstance(v, str) and v in USER_MODES and v not in EV_CHARGE_MODES:
            v = strategy_for(v, help_now)
        charger["charge_mode"] = v if isinstance(v, str) else value
        # The strategy carries the switch for the four sun strategies, so
        # nothing is stored for them (a write of the same mode changes no
        # key: the startup heal and set_option stay no-ops). Leaving a sun
        # strategy for Now or Off is the one moment the switch must be
        # remembered, because the new strategy cannot carry it.
        if v not in _HELP_OF_STRATEGY and prev in _HELP_OF_STRATEGY:
            charger[BATTERY_HELP_KEY] = help_now
        return
    if key == BATTERY_HELP_KEY:
        on = bool(value)
        charger[BATTERY_HELP_KEY] = on
        if on and charger.get("ev_battery_may_assist") is False:
            charger["ev_battery_may_assist"] = True
        mode = user_mode_of(charger.get("charge_mode") or DEFAULT_EV_CHARGE_MODE)
        if mode in ("sun", "sun_tariff"):
            charger["charge_mode"] = strategy_for(mode, on)
        return
    charger[key] = value


# The new-install default. Q4 resolved 2026-05-30 — matches today's
# factory defaults (mode=pv + night=on + smart=on + tariff=off).
DEFAULT_EV_CHARGE_MODE: str = "min_plus_solar"


# ─────────────────────────────────────────────────────────────────
# Mode-driven effective-state predicates — #277 Phase B
# ─────────────────────────────────────────────────────────────────

MODE_NIGHT_ALLOWED: frozenset[str] = frozenset({
    "solar_plus_cheap", "min_plus_solar", "always_max",
})
#: (#1381 D23) The two stored strategies behind "Sun + tariff": both run
#: the one tariff day rule (deadline floor, peak pause, cheap-hour top-up,
#: thin sun) — battery help is the only difference between them.
MODE_SUN_TARIFF_DAY: frozenset[str] = frozenset({
    "solar_plus_cheap", "min_plus_solar",
})
MODE_USES_TARIFF: frozenset[str] = frozenset({
    "solar_plus_cheap",
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

    (#1020) A charger may take ``schedule_entity`` (a Home Assistant
    Schedule helper) and ``schedule_mode``: while the helper is on, that is
    the mode. Substituted here, at read time — the stored ``charge_mode`` is
    never written, so a restart, an unavailable helper or a deleted one
    needs no restore. Without ``hass`` there is no schedule to see.

    Returns one of ``EV_CHARGE_MODES`` keys; never raises.
    """
    if not isinstance(charger_cfg, dict):
        return DEFAULT_EV_CHARGE_MODE
    scheduled = scheduled_charge_mode(hass, charger_cfg)
    if scheduled is not None:
        return scheduled
    stored = charger_cfg.get("charge_mode")
    if stored in EV_CHARGE_MODES:
        return stored
    if stored in USER_MODES:   # (#1381 S9) a user mode written by hand
        return strategy_for(stored, battery_help_of(
            {**charger_cfg, "charge_mode": None}))
    return DEFAULT_EV_CHARGE_MODE


def scheduled_charge_mode(hass: Any, charger_cfg: Any) -> "str | None":
    """(#1020) The charger's scheduled mode while its helper is ON, else
    None. A helper that is unavailable, unknown or gone is no schedule; an
    unknown mode is no mode."""
    if hass is None or not isinstance(charger_cfg, dict):
        return None
    entity = charger_cfg.get("schedule_entity") or ""
    mode = charger_cfg.get("schedule_mode") or ""
    if mode in USER_MODES and mode not in EV_CHARGE_MODES:   # (#1381 S9)
        mode = strategy_for(mode, battery_help_of(
            {**charger_cfg, "charge_mode": None}))
    if not entity or mode not in EV_CHARGE_MODES:
        return None
    try:
        state = hass.states.get(entity)
    except Exception:  # noqa: BLE001 — no state machine, no schedule
        return None
    if state is None or getattr(state, "state", None) != "on":
        return None
    return mode


def mode_allows_night_charging(
    full_config: Mapping[str, Any],
    charger_cfg: Any,
    hass: Any = None,
) -> bool:
    """Does this charger's mode permit night/grid charging at all? (#679)

    #634 settled the axis: the mode is the *daytime* axis and the
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
    # (#1020) ``hass`` so a schedule's mode is seen here too.
    mode = effective_charge_mode_for(hass, full_config, charger_cfg)
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
