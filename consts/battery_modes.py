"""Canonical per-battery control-mode names (#523 multi-battery).

One named intent per battery, the battery-side mirror of the EV
``charge_mode`` selector. Lives in ``consts/`` so the entity layer
(``select.py``) and the pure decision (``coordinator/decide_battery.py``)
import the same source of truth — no duplicated tuple.

Mode semantics (all map to EXISTING ``BatteryIntent`` values — no new
adapter commands):

* ``auto``             — today's behaviour: the scheduler / arbitrage /
  protection logic decides. No override.
* ``self_consumption`` — charge from surplus + discharge to the house as
  normal, but NEVER sell to grid (suppresses the arbitrage verdict for
  this battery even when arbitrage is globally on).
* ``allow_arbitrage``  — permit THIS battery to sell to grid when export
  beats recharge cost. **Removed from the selector in v1.7.3** (automatic
  battery→grid arbitrage is deactivated for the stable release — #533;
  returns in v1.7.4). The value + its handling stay so an existing config
  doesn't error, but it's no longer offered and the coordinator never
  evaluates arbitrage for it.
* ``force_charge``     — manual FORCE_CHARGE to full now.
* ``force_discharge``  — manual FORCE_DISCHARGE (sell to grid) down to the
  battery's reserve SOC now.
* ``off``              — SEM is fully hands-off this battery (RienduPre
  request). One-time clean handoff on entry (clear force, release strategy,
  un-limit), then SEM issues NOTHING — no protection, no scheduler, no
  arbitrage. The inverter manages the battery on its own.
"""
from __future__ import annotations

# Order matters: it's the order shown in the HA select UI.
# NOTE: ``allow_arbitrage`` is intentionally absent in v1.7.3 — automatic
# battery→grid arbitrage is deactivated for the stable release (#533, returns
# in v1.7.4). ``arbitrage_allowed_for_mode`` still recognises the value so an
# existing/stale config is handled gracefully, but it isn't offered here.
BATTERY_MODES: dict[str, str] = {
    "auto": "Auto",
    "self_consumption": "Self-consumption only",
    "force_charge": "Force charge",
    "force_discharge": "Force discharge",
    "off": "Off (SEM hands-off)",
}

DEFAULT_BATTERY_MODE: str = "auto"

# Default reserve-SOC floor (%) for force/allow discharge — the battery
# never sells below this. Conservative so a fresh install can't drain a
# battery flat by accident.
DEFAULT_BATTERY_RESERVE_SOC: float = 20.0


def arbitrage_allowed_for_mode(
    mode: str, global_enabled: bool, permissions: dict = None,
) -> bool:
    """Whether a battery in ``mode`` may act on a DISCHARGING_ARBITRAGE
    verdict this cycle.

    * ``self_consumption`` / ``off`` → never.
    * ``allow_arbitrage``  → always (per-battery opt-in).
    * ``auto`` / unknown   → follow the global arbitrage toggle.
    """
    # (#778) The permission axis now owns this question. The mapping below
    # keeps every existing install behaving exactly as it did — the legacy
    # values migrate to the permissions they always were — while making
    # "self-consumption posture AND permitted to sell" expressible, which a
    # single-select enum never could. See consts/battery_permissions.py.
    from .battery_permissions import (
        LEGACY_ARBITRAGE_MODE, effective_permissions, may_export,
    )

    m = (mode or "auto").lower()

    # ``allow_arbitrage`` stays a short-circuit. It is a per-battery opt-in
    # that overrides the global switch in SHIPPED behaviour, pinned by
    # tests/test_638_c6_arbitrage_sell.py, and routing it through may_export
    # would make the global kill switch absolute for it — a real behaviour
    # change on existing installs, and not the one this fix is for. The two
    # functions genuinely disagree about whether a per-battery opt-in beats
    # the master switch; that is worth settling deliberately, not here.
    if m == LEGACY_ARBITRAGE_MODE:
        return True

    # Everything else routes through the permission axis — INCLUDING
    # self_consumption, which used to short-circuit to False and so could
    # never be granted an explicit may_export. That contradicted the comment
    # above: "self-consumption posture AND permitted to sell" was the one
    # thing this arc existed to make expressible, and it was the one
    # combination still impossible. may_export preserves the legacy meaning
    # for UNSET (self_consumption never sold), so no existing install moves.
    return may_export(m, effective_permissions(m, permissions), bool(global_enabled))
