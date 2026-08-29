"""#778 — what a battery is *allowed* to do, separately from its posture.

Guido, 23.08.2026, on adding a second sink for the forecast budget: the
existing mode enum cannot express it. Look at what it mixes:

    auto             -> posture
    self_consumption -> posture AND a permission (never sell)
    allow_arbitrage  -> a pure permission ("permit THIS battery to sell")
    force_charge     -> a manual command
    force_discharge  -> a manual command
    off              -> posture

Because it is single-select, *"self-consumption posture AND allowed to sell
when it is genuinely worth it"* is **inexpressible today**. Adding
``allow_ev_assist`` as a sixth value would not merely add a control — it could
not compose with the first. That is a shape problem, not a count problem, and
it already existed before the second sink exposed it.

So: **mode stays for posture, permissions become their own composable axis.**
Permissions answer *may this battery feed that sink*; the #576 device list
answers *who goes first*. They are different questions and must not be
conflated — a second ordering authority is the #780 two-axes trap.

Everything here preserves today's behaviour by default:

* ``may_export`` defaults **off**, and still sits under the global
  ``battery_grid_arbitrage_enabled`` kill switch. Selling someone's battery to
  the grid is not a thing to switch on for them.
* ``may_assist_ev`` defaults **on**, because the battery already assists the
  car today whenever the #537 surplus gate passes. Defaulting it off would
  silently remove a working feature. What it adds is the control that never
  existed: *"the house may use my battery, the car may not."*
"""
from __future__ import annotations

from typing import Any, Dict, Optional

#: Permission keys. ``None`` means UNSET — "no opinion, follow the legacy
#: rule for this mode" — and is the only default that preserves every existing
#: install. A plain ``False`` here would have silently stopped selling for
#: anyone on ``auto``, whose mode follows the global toggle today; SEM's own
#: #523 tests caught exactly that. Tri-state is not over-engineering here, it
#: is the difference between a refactor and a behaviour change.
PERMISSION_UNSET = None
PERMISSION_KEYS = ("may_export", "may_assist_ev")

#: What an UNSET permission resolves to when nothing legacy applies.
PERMISSION_FALLBACK: Dict[str, bool] = {
    # Follows the global arbitrage kill switch, as ``auto`` always has.
    "may_export": True,
    # The battery already assists the car when the #537 surplus gate passes;
    # defaulting this off would silently remove a working feature.
    "may_assist_ev": True,
}

#: The legacy mode value that was always a permission wearing a mode's clothes.
LEGACY_ARBITRAGE_MODE = "allow_arbitrage"


def _perm(permissions: Optional[dict], key: str):
    """The user's explicit choice, or ``None`` when they have not made one."""
    if not isinstance(permissions, dict) or permissions.get(key) is None:
        return PERMISSION_UNSET
    return bool(permissions[key])


def may_export(mode, permissions: Optional[dict], global_enabled: bool) -> bool:
    """May this battery sell to the grid this cycle?

    An explicit permission decides. When UNSET, the legacy rule for the mode
    applies unchanged, which is what keeps every existing install behaving
    identically: ``self_consumption`` never sold, ``allow_arbitrage`` always
    did, ``auto`` followed the global switch.

    The global kill switch is absolute either way — selling someone's battery
    to the grid is not a thing to switch on for them.
    """
    m = (mode or "auto").lower()
    if m == "off":
        return False
    if not global_enabled:
        return False

    explicit = _perm(permissions, "may_export")
    if explicit is not None:
        return explicit

    # UNSET → the legacy meaning of the mode, preserved exactly.
    if m == "self_consumption":
        return False
    if m == LEGACY_ARBITRAGE_MODE:
        return True
    return PERMISSION_FALLBACK["may_export"]


def may_assist_ev(mode, permissions: Optional[dict]) -> bool:
    """May this battery be spent on the car?

    Not gated by the arbitrage kill switch — that switch is about selling to
    the grid, and energy going into the car never leaves the house.
    """
    m = (mode or "auto").lower()
    if m == "off":
        return False
    explicit = _perm(permissions, "may_assist_ev")
    if explicit is not None:
        return explicit
    return PERMISSION_FALLBACK["may_assist_ev"]


def migrate_mode(mode) -> tuple:
    """Split a legacy mode value into ``(mode, permission_overrides)``.

    ``allow_arbitrage`` was a permission all along, so it becomes
    ``auto`` + ``may_export=True``. Everything else keeps its posture and takes
    the defaults. The old value stays *recognised* rather than rejected — the
    same care taken when it was pulled from the selector in v1.7.3, so an
    existing config never errors.
    """
    m = (mode or "auto").lower()
    if m == LEGACY_ARBITRAGE_MODE:
        return "auto", {"may_export": True}
    if m == "self_consumption":
        # Its old meaning included "never sell"; keep that promise explicitly
        # rather than relying on the posture to carry it.
        return m, {"may_export": False}
    return m, {}


def effective_permissions(mode, stored: Optional[dict]) -> Dict[str, Any]:
    """The permission map in force: the user's explicit choices, plus anything
    a legacy mode implies that they have not overridden.

    Values may be ``None`` (unset) — the resolvers above turn that into the
    legacy behaviour for the mode, which is what makes this a refactor rather
    than a behaviour change.
    """
    _, overrides = migrate_mode(mode)
    out: Dict[str, Any] = {k: PERMISSION_UNSET for k in PERMISSION_KEYS}
    if isinstance(stored, dict):
        for k in PERMISSION_KEYS:
            if stored.get(k) is not None:
                out[k] = bool(stored[k])
    for k, v in overrides.items():
        if out.get(k) is None:
            out[k] = v
    return out
