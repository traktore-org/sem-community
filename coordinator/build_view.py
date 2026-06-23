"""Build a :class:`ChargerView` from the coordinator's per-cycle data.

The bridge between the existing fleet-primary data model and the new
per-charger-primary architecture (Steps 1-4). Lives standalone so the
coordinator imports a single function and the construction details
stay together.

Step 6 will invert the data model so the coordinator HAS the
per-charger primaries natively; until then this module is the seam.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Optional

from .charger_types import (
    ChargerEnergy,
    ChargerPower,
    ChargerView,
    FleetContext,
    FleetCycleState,
)

if TYPE_CHECKING:  # pragma: no cover — type-only
    from .types import PowerReadings


def build_charger_view(
    fleet_state: FleetCycleState,
    *,
    charger_id: str,
    charger_cfg: Mapping[str, Any],
    mode: str,
    daily_ev_kwh: float,
    target_kwh: Optional[float] = None,
    target_soc: Optional[float] = None,
    deadline_amps: int = 0,
    tariff_wait: bool = False,
    solar_committed_w: float = 0.0,
    night_deliverable_kwh: float = float("inf"),
) -> ChargerView:
    """Construct a ChargerView from a per-cycle FleetCycleState +
    per-charger overrides.

    The :class:`FleetCycleState` is the single source of truth for
    fleet-level inputs (power readings, SOC thresholds, is_night,
    tariff_level, forecast_remaining_kwh). Every ``decide()`` for
    every charger in the same cycle sees the SAME ``fleet_state`` —
    eliminating the post-#358 plumbing-asymmetry class where some
    callers passed ``tariff_level`` / ``forecast_remaining_kwh`` /
    night-plan signals and others didn't.

    Per-charger fields stay as direct kwargs because they LEGITIMATELY
    vary across chargers in the same cycle:

      * ``target_kwh`` / ``target_soc`` — per-charger remaining need
      * ``deadline_amps`` — per-charger night-plan floor (#246)
      * ``tariff_wait`` — per-charger night-plan wait flag (#247)
      * ``solar_committed_w`` — solar already claimed by
        higher-priority chargers in the cascade

    Args:
        fleet_state: The cycle's fleet inputs. Built ONCE per cycle
            by ``coordinator._build_fleet_cycle_state``.
        charger_id: The charger's id (matches ``ev_chargers[i]["id"]``).
        charger_cfg: The per-charger config dict.
        mode: Resolved per-charger charge mode (from
            ``effective_charge_mode_for``).
        daily_ev_kwh: Per-charger calendar-reset kWh today.
        target_kwh: Per-charger remaining-to-Min kWh, or None.
        target_soc: Per-charger SOC target, or None.
        deadline_amps: Pre-computed deadline floor amps (#246), or 0.
        tariff_wait: Per-charger night-planner wait flag (#247).
        solar_committed_w: Solar already committed to higher-priority
            chargers in this cycle.

    Returns:
        An immutable :class:`ChargerView` for ``decide()``.
    """
    power_reading = fleet_state.power
    config = fleet_state.config

    # Per-charger power slice
    ev_power_per_charger = getattr(power_reading, "ev_power_per_charger", None) or {}
    this_charger_w = float(ev_power_per_charger.get(charger_id, 0.0))

    # Per-charger connected state — when no per-charger sensor is
    # configured, fall back to the fleet OR (the legacy behaviour).
    # Step 6 makes this per-charger native.
    connected_per_charger = getattr(power_reading, "ev_connected_per_charger", None) or {}
    if charger_id in connected_per_charger:
        connected = bool(connected_per_charger[charger_id])
    else:
        connected = bool(getattr(power_reading, "ev_connected", False))

    charging_per_charger = getattr(power_reading, "ev_charging_per_charger", None) or {}
    if charger_id in charging_per_charger:
        charging = bool(charging_per_charger[charger_id])
    else:
        charging = bool(getattr(power_reading, "ev_charging", False))

    cp = ChargerPower(
        charger_id=charger_id,
        power_w=this_charger_w,
        connected=connected,
        charging=charging,
    )

    ce = ChargerEnergy(charger_id=charger_id, day_kwh=daily_ev_kwh)

    # FleetContext — derived ENTIRELY from fleet_state. The ONLY
    # per-call variable is ``solar_committed_w`` (carries the
    # priority cascade state from higher-priority chargers).
    #
    # Adding a new fleet input is a ONE-PLACE change: add the field
    # to FleetCycleState (in charger_types.py) + read it here. The
    # AST lint at ``tests/test_fleet_state_completeness.py`` fails
    # CI if any ``build_charger_view`` call site bypasses this state
    # and passes a fleet-level kwarg directly.
    fleet = FleetContext(
        solar_w=float(getattr(power_reading, "solar_power", 0.0) or 0.0),
        home_w=float(getattr(power_reading, "home_consumption_power", 0.0) or 0.0),
        battery_charge_w=float(getattr(power_reading, "battery_charge_power", 0.0) or 0.0),
        battery_discharge_w=float(getattr(power_reading, "battery_discharge_power", 0.0) or 0.0),
        battery_soc=float(getattr(power_reading, "battery_soc", 0.0) or 0.0),
        grid_import_w=float(getattr(power_reading, "grid_import_power", 0.0) or 0.0),
        grid_export_w=float(getattr(power_reading, "grid_export_power", 0.0) or 0.0),
        is_night=fleet_state.is_night,
        tariff_level=fleet_state.tariff_level,
        auto_start_soc=float(config.get("battery_auto_start_soc", 90)),
        buffer_soc=float(config.get("battery_buffer_soc", 70)),
        priority_soc=float(config.get("battery_priority_soc", 30)),
        battery_assist_floor_soc=float(config.get("battery_assist_floor_soc", 60)),
        battery_capacity_kwh=float(config.get("battery_capacity_kwh", 15)),
        battery_assist_max_power_w=float(config.get(
            "battery_assist_max_power",
            config.get("super_charger_power", 4500),
        )),
        battery_assist_min_surplus_w=float(config.get(
            "battery_assist_min_surplus", 1200,
        )),
        solar_committed_w=float(solar_committed_w),
        forecast_remaining_kwh=fleet_state.forecast_remaining_kwh,
        # The user's "Minimum Solar Power" slider (number entity key
        # ``minimum_solar_power``) — the floor below which solar_only won't
        # charge and the deep-deficit guard treats solar as "none". Was never
        # wired in, so decide()/charge_stability always saw the 200 W default
        # regardless of the slider. Honour the configured value; keep the 200 W
        # fallback so a config without the key is unchanged.
        min_solar_w=float(
            config.get("minimum_solar_power",
                       config.get("min_solar_power", 200))
        ),
    )

    # Merge per-charger config with the tariff_wait flag so
    # SolarPlusCheapMode can consult it. Avoids extending the
    # ChargerView signature with an opaque kwarg.
    cfg_with_wait = dict(charger_cfg) if isinstance(charger_cfg, dict) else {}
    cfg_with_wait["_tariff_wait"] = tariff_wait

    return ChargerView(
        power=cp,
        energy=ce,
        mode=mode,
        config=cfg_with_wait,
        fleet=fleet,
        target_kwh=target_kwh,
        target_soc=target_soc,
        deadline_amps=deadline_amps,
        night_deliverable_kwh=night_deliverable_kwh,
    )
