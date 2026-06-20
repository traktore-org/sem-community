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


def arbitrage_allowed_for_mode(mode: str, global_enabled: bool) -> bool:
    """Whether a battery in ``mode`` may act on a DISCHARGING_ARBITRAGE
    verdict this cycle.

    * ``self_consumption`` / ``off`` → never.
    * ``allow_arbitrage``  → always (per-battery opt-in).
    * ``auto`` / unknown   → follow the global arbitrage toggle.
    """
    m = (mode or "auto").lower()
    if m in ("self_consumption", "off"):
        return False
    if m == "allow_arbitrage":
        return True
    return bool(global_enabled)
