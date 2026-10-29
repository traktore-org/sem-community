"""#1085 Part B — one-off plan overrides.

Modes persist by design (``battery_mode``, a charger's ``charge_mode``) —
nothing auto-reverts them. A user who says "don't charge tonight" wants
THAT NIGHT changed, not the standing mode, and wants it to still be true
after an HA restart (nobody re-sets it at 2am). This module is the
storage + expiry + per-device translation for that one-off: pure,
hass-free, unit-testable — the same contract as ``curtailment.py``.

One override per device at a time; setting a new one replaces the old.
``action`` is one of ``ACTIONS``. Only ``skip`` and ``force`` are acted on
today, by battery and charger alike, each riding the EXISTING manual-mode
road (``_decide_battery``'s ``mode == "off"/"force_charge"``, the same
``ChargerIntent.DISABLE``/``CHARGE_MAX`` #580's VPP pause and boost already
use) — no new decision logic, so no new hardware risk. ``cap`` and ``move``
are accepted and stored (so a later part never needs a storage migration)
but no decider reads them yet; they stay inert until a part that needs them
(``cap`` wants an amps-clamp path; ``move`` wants #1087's calendar data).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Mapping, Optional

from . import reason_codes as RC
from .charger_types import ChargerIntent, rewrite

#: The four action words a stored override may carry. Only "skip" and
#: "force" are consumed by a decider today — see the module docstring.
ACTIONS = ("skip", "cap", "move", "force")


@dataclass(frozen=True)
class PlanOverride:
    device_id: str
    action: str
    expires_at: datetime
    """Wall-clock, tz-aware — survives an HA restart (unlike the monotonic
    ``_cooldown_until``/``_giveup_backoff_until`` timers elsewhere)."""
    value: Optional[float] = None
    set_at: Optional[datetime] = None


def set_override(
    overrides: Mapping[str, PlanOverride], device_id: str, action: str,
    expires_at: datetime, now: datetime, value: Optional[float] = None,
) -> Dict[str, PlanOverride]:
    """A new dict with ``device_id``'s override set, replacing any prior
    one. Raises ``ValueError`` on a bad action or an expiry not in the
    future — the service handler turns that into a refusal the user
    reads, same shape as ``BoostRefused``."""
    if action not in ACTIONS:
        raise ValueError(f"not an action: {action!r} (one of {ACTIONS})")
    if expires_at <= now:
        raise ValueError("expiry must be in the future")
    out = dict(overrides)
    out[device_id] = PlanOverride(
        device_id=device_id, action=action, expires_at=expires_at,
        value=value, set_at=now)
    return out


def clear_override(
    overrides: Mapping[str, PlanOverride], device_id: str,
) -> Dict[str, PlanOverride]:
    """A new dict with ``device_id``'s override removed, if any."""
    out = dict(overrides)
    out.pop(device_id, None)
    return out


def active_override(
    overrides: Mapping[str, PlanOverride], device_id: str, now: datetime,
) -> Optional[PlanOverride]:
    """The device's override, or ``None`` when there is none or it has
    expired. A pure read — does not purge; ``purge_expired`` does that
    once per cycle so every reader this cycle sees the same answer."""
    rec = overrides.get(device_id)
    if rec is None or rec.expires_at <= now:
        return None
    return rec


def purge_expired(
    overrides: Mapping[str, PlanOverride], now: datetime,
) -> Dict[str, PlanOverride]:
    """A new dict with every expired entry dropped. Call once per cycle,
    before any ``active_override`` read, so a device whose override just
    lapsed is seen as clear everywhere this cycle — and so the persisted
    store does not grow forever."""
    return {k: v for k, v in overrides.items() if v.expires_at > now}


def serialize(overrides: Mapping[str, PlanOverride]) -> Dict[str, Dict[str, Any]]:
    """JSON-safe shape for ``SEMStorage.set_plan_overrides`` — datetimes
    as ISO strings."""
    out: Dict[str, Dict[str, Any]] = {}
    for device_id, rec in overrides.items():
        out[device_id] = {
            "action": rec.action,
            "expires_at": rec.expires_at.isoformat(),
            "value": rec.value,
            "set_at": rec.set_at.isoformat() if rec.set_at else None,
        }
    return out


def deserialize(raw: Any) -> Dict[str, PlanOverride]:
    """The reverse of ``serialize``. A malformed entry is dropped, never
    raised — a bad stash loses that one override, not the whole cycle
    (the ``_restore_energy_plan`` discipline: ``tests/test_...`` aside,
    this is read on every HA start, so it must never crash startup)."""
    out: Dict[str, PlanOverride] = {}
    if not isinstance(raw, dict):
        return out
    for device_id, entry in raw.items():
        try:
            if not isinstance(entry, dict):
                continue
            action = str(entry.get("action"))
            if action not in ACTIONS:
                continue
            expires_at = datetime.fromisoformat(str(entry["expires_at"]))
            set_at_raw = entry.get("set_at")
            set_at = datetime.fromisoformat(str(set_at_raw)) if set_at_raw else None
            value = entry.get("value")
            out[str(device_id)] = PlanOverride(
                device_id=str(device_id), action=action, expires_at=expires_at,
                value=float(value) if value is not None else None, set_at=set_at)
        except (KeyError, TypeError, ValueError):
            continue
    return out


# ─── Per-device translation — where the override dictates the action ───

def apply_to_battery_config(
    overrides: Mapping[str, PlanOverride], battery_id: str,
    pbc: Mapping[str, Any], now: datetime,
) -> Dict[str, Any]:
    """Rewrite this battery's config BEFORE ``BatteryView`` is built, the
    same shape ``_vpp_apply_battery_override`` already uses (#580): the
    override rides the existing ``battery_mode`` road, so
    ``_decide_battery`` needs no new branch. A battery already ``off``
    stays hands-off — a standing user opt-out outranks a one-off. Returns
    a NEW dict; the input is never mutated."""
    rec = active_override(overrides, battery_id, now)
    if rec is None:
        return dict(pbc)
    if str(pbc.get("battery_mode", "auto") or "auto").lower() == "off":
        return dict(pbc)
    new_mode = {"skip": "off", "force": "force_charge"}.get(rec.action)
    if new_mode is None:
        return dict(pbc)  # cap / move: not yet consumed for batteries
    return {**pbc, "battery_mode": new_mode}


def apply_to_charger_decision(
    overrides: Mapping[str, PlanOverride], charger_id: str,
    decision: Any, now: datetime,
) -> Any:
    """Rewrite this charger's decision right after ``decide(view)``, the
    same call shape as #580's ``vpp_pause_override``. ``skip`` mirrors
    the VPP export-pause DISABLE exactly (the adapter's existing
    dead-man/self-resume handling already covers it); ``force`` mirrors
    the VPP import-boost CHARGE_MAX. ``cap``/``move``: not yet consumed —
    passed through unchanged."""
    rec = active_override(overrides, charger_id, now)
    if rec is None:
        return decision
    until = f"{rec.expires_at:%H:%M}"
    if rec.action == "skip":
        return rewrite(
            decision, intent=ChargerIntent.DISABLE, commanded_amps=0,
            budget_w=0.0, bridgeable=False, safety_stop=True,
            reason=f"plan override — stopped until {until} — {decision.reason}",
            reason_code=RC.CHARGER_PLAN_OVERRIDE_STOP,
            reason_params={"time": until},
        )
    if rec.action == "force":
        return rewrite(
            decision, intent=ChargerIntent.CHARGE_MAX,
            reason=f"plan override — forced to charge until {until} — {decision.reason}",
            reason_code=RC.CHARGER_PLAN_OVERRIDE_RUN,
            reason_params={"time": until},
        )
    return decision  # cap / move: not yet consumed


def status_payload(
    overrides: Mapping[str, PlanOverride], device_id: str, now: datetime,
) -> Optional[Dict[str, Any]]:
    """Diagnose/card data for a device with an active override, or
    ``None``: ``{"action", "until"}``, ``until`` in the ``%H:%M``
    convention ``decide_battery.py`` and the pacing-reason chain already
    use. Structured, not a sentence — the card turns ``action`` into its
    own ``why_reason_charger_plan_override_<stop|run>`` text; Diagnose
    reads the two fields directly."""
    rec = active_override(overrides, device_id, now)
    if rec is None:
        return None
    return {"action": rec.action, "until": f"{rec.expires_at:%H:%M}"}
