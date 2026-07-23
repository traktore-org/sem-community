"""Per-charger night-target computation (#629 slice 1, from step 7.5a).

Extracted from the coordinator's multi-charger orchestration block: the
per-charger kWh-remaining map used for night charging (#193). Pure READ
computation over config + delivered energy — the only side effect is the
log-once inheritance notice (#259) tracked on the coordinator.

The night-state gating (NIGHT_CHARGING_ACTIVE / TARIFF_WAITING_FOR_CHEAP,
#247) stays at the call site — this module only answers "how much does each
charger still need tonight".
"""
from __future__ import annotations

import logging
from typing import Any, Dict

_LOGGER = logging.getLogger(__name__)


def build_night_target_map(coord, energy) -> Dict[str, float]:
    """Per-charger remaining night-charge need, in kWh (#193/#245/#464).

    - ``soc`` target type: kWh to reach the PER-CHARGER SOC floor (#245
      propagation fix) — not the kWh daily_ev_target.
    - ``kwh`` target type: per-charger daily target − this charger's
      delivered energy, on the display-consistent basis (the ONE accessor,
      #536 + the 2026-07-17 night-idle basis-mismatch fix). A charger with
      no own target inherits the global floor, surfaced once per charger
      (#259; behaviour change deferred to #255).
    """
    out: Dict[str, float] = {}
    ev_chargers_cfg = coord.config.get("ev_chargers", [])
    charger_cfg_by_id: Dict[str, Any] = {c.get("id"): c for c in ev_chargers_cfg}

    for cid in coord._ev_devices:
        cfg = charger_cfg_by_id.get(cid, {})
        ttype = (cfg.get("ev_target_type") or cfg.get("ev_target_mode")
                 or coord.config.get("ev_target_type", "kwh"))
        if ttype == "soc":
            per_soc = coord._resolve_charger_soc(cid, cfg)
            out[cid] = coord._calculate_remaining_need(
                energy, per_soc, cfg, bound="min",
            )
        else:
            target = cfg.get("daily_ev_target")
            if target is None:
                target = coord.config.get("daily_ev_target", 10)
                if cid not in coord._night_global_fallback_logged:
                    _LOGGER.info(
                        "Charger %s has no per-charger night target; "
                        "inheriting global %.1f kWh", cid, target,
                    )
                    coord._night_global_fallback_logged.add(cid)
            daily = coord._charger_daily_kwh(cid, energy)
            out[cid] = max(0, target - daily)
    return out
