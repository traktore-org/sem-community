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
  beats recharge cost, even if the global arbitrage toggle is off.
* ``force_charge``     — manual FORCE_CHARGE to full now.
* ``force_discharge``  — manual FORCE_DISCHARGE (sell to grid) down to the
  battery's reserve SOC now.
"""
from __future__ import annotations

# Order matters: it's the order shown in the HA select UI.
BATTERY_MODES: dict[str, str] = {
    "auto": "Auto",
    "self_consumption": "Self-consumption only",
    "allow_arbitrage": "Allow arbitrage",
    "force_charge": "Force charge",
    "force_discharge": "Force discharge",
}

DEFAULT_BATTERY_MODE: str = "auto"

# Default reserve-SOC floor (%) for force/allow discharge — the battery
# never sells below this. Conservative so a fresh install can't drain a
# battery flat by accident.
DEFAULT_BATTERY_RESERVE_SOC: float = 20.0


def arbitrage_allowed_for_mode(mode: str, global_enabled: bool) -> bool:
    """Whether a battery in ``mode`` may act on a DISCHARGING_ARBITRAGE
    verdict this cycle.

    * ``self_consumption`` → never.
    * ``allow_arbitrage``  → always (per-battery opt-in).
    * ``auto`` / unknown   → follow the global arbitrage toggle.
    """
    m = (mode or "auto").lower()
    if m == "self_consumption":
        return False
    if m == "allow_arbitrage":
        return True
    return bool(global_enabled)
