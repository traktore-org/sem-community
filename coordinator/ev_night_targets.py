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


def resolve_night_effective_state(base_state, charging_state, pc_target, plan,
                                  night_active_state, tariff_wait_state,
                                  target_reached_state):
    """(#629 slice 3) The per-charger NIGHT effective-state tri-state, pure.

    Given the off-override-adjusted ``base_state``: outside the two night
    states it passes through unchanged. Inside them: a met target (< 0.1 kWh)
    is NIGHT_TARGET_REACHED; otherwise the plan's tariff-wait flag picks
    TARIFF_WAITING_FOR_CHEAP vs NIGHT_CHARGING_ACTIVE (#247). The state
    enums are passed in so this module stays import-light."""
    if charging_state not in (night_active_state, tariff_wait_state):
        return base_state
    if pc_target is None or pc_target <= 0.1:
        return target_reached_state
    if plan is not None and plan.should_wait_for_cheap:
        return tariff_wait_state
    return night_active_state


def resolve_per_charger_mode(coord, cid, charger_cfg):
    """(#629 slice 4) Per-charger effective mode + the mismatch diagnostic.

    ``_effective_charge_mode_for`` corrects the primary-only mode for THIS
    charger (an OFF primary must not bleed its terminate into siblings).
    The warning fires only when an explicitly-set mode disagrees with the
    resolution — ``raw_mode = None`` is the legitimate default fallback."""
    per_mode = coord._effective_charge_mode_for(charger_cfg)
    raw_mode = charger_cfg.get("charge_mode") if isinstance(charger_cfg, dict) else None
    if raw_mode is not None and raw_mode != per_mode:
        _LOGGER.warning(
            "per-charger mode mismatch: cid=%s raw_cfg=%r per_mode=%r",
            cid, raw_mode, per_mode,
        )
    return per_mode
