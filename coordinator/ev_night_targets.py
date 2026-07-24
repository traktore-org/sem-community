"""Step-7.5a orchestration helpers (#629): night targets + solar budget.

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


def distribute_solar_budget(coord) -> Dict[str, float]:
    """(#629 slice 2) The per-charger solar-budget distribution (step 7.5a).

    Reads the canonical cycle ``EVBudget`` (#282 Phase B.5 — the ONE total,
    never the legacy ev_power+export base), excludes chargers whose effective
    mode is ``off`` (#351 M5 — the dashboard reads this output directly), and
    delegates the priority-weighted split to
    ``SurplusController.distribute_ev_budget``. Caller gates on the solar
    charging states."""
    cycle_budget = getattr(coord, "_cycle_ev_budget", None)
    if cycle_budget is None:
        # Phase D.2 cleanup (#282): set unconditionally every cycle by
        # _build_charging_context — this branch only fires on an init bug.
        _LOGGER.error(
            "Canonical EV budget not set in multi-charger distribution — "
            "coordinator init bug. Distributing 0 W to fail safe. "
            "Investigate _build_charging_context."
        )
        total_budget = 0.0
    else:
        total_budget = cycle_budget.net_w
    excluded_cids = {
        c["id"] for c in (coord.config.get("ev_chargers") or [])
        if isinstance(c, dict) and "id" in c
        and coord._effective_charge_mode_for(c) == "off"
    }
    return coord._surplus_controller.distribute_ev_budget(
        total_budget, coord._ev_devices,
        excluded_charger_ids=excluded_cids,
    )
