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
from .plan_verdict import NO_OPINION, PlanVerdict

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
    top_up_amps: int = 0,
    plan: PlanVerdict = NO_OPINION,
    solar_committed_w: float = 0.0,
    night_deliverable_kwh: float = float("inf"),
    soc_ceiling_reached: bool = False,
    ev_priority: int = 999,
    hardware_max_a: Optional[float] = None,
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
      * ``plan`` — the planning layer's verdict for this charger (#638)
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
        plan: The planning layer's verdict for this charger this
            cycle (#638) — a hold placed by the energy planner (or
            the #247 tariff planner, which speaks through the same
            type). Defaults to no opinion, meaning "behave as though no
            planner exists".
        solar_committed_w: Solar already committed to higher-priority
            chargers in this cycle.

    Returns:
        An immutable :class:`ChargerView` for ``decide()``.
    """
    power_reading = fleet_state.power
    config = fleet_state.config

    # Per-charger power slice. ``ev_power_per_charger`` is populated by
    # ``_read_ev_fleet_power`` for every charger that has its own power sensor
    # — single-charger installs included (#642 removed the old ``len > 1``
    # split). It is empty only when no charger carries a nested sensor; then
    # the fleet ``ev_power`` IS this charger's draw, in watts. Without this
    # fallback ``this_charger_w`` was always 0 on such setups, so
    # ``actual_charging`` never saw the car drawing and the start escalation
    # never settled (#536).
    ev_power_per_charger = getattr(power_reading, "ev_power_per_charger", None) or {}
    if charger_id in ev_power_per_charger:
        this_charger_w = float(ev_power_per_charger[charger_id])
    else:
        # FLEET-READ: single-charger fallback — the fleet sum is this one
        # charger's draw (W). Multi-charger always has a per-charger entry above.
        this_charger_w = float(getattr(power_reading, "ev_power", 0.0) or 0.0)

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
        # #743 — the curtailment probe's grant rides the same one-place
        # thread as every other fleet input.
        curtailment_grant_w=float(
            getattr(fleet_state, "curtailment_grant_w", 0.0) or 0.0,
        ),
        home_w=float(getattr(power_reading, "home_consumption_power", 0.0) or 0.0),
        battery_charge_w=float(getattr(power_reading, "battery_charge_power", 0.0) or 0.0),
        battery_discharge_w=float(getattr(power_reading, "battery_discharge_power", 0.0) or 0.0),
        battery_soc=float(getattr(power_reading, "battery_soc", 0.0) or 0.0),
        grid_import_w=float(getattr(power_reading, "grid_import_power", 0.0) or 0.0),
        grid_export_w=float(getattr(power_reading, "grid_export_power", 0.0) or 0.0),
        is_night=fleet_state.is_night,
        tariff_level=fleet_state.tariff_level,
        # (#747) the peak posture rides the one-place thread.
        peak_state=getattr(fleet_state, "peak_state", "normal"),
        auto_start_soc=float(config.get("battery_auto_start_soc", 90)),
        buffer_soc=float(config.get("battery_buffer_soc", 70)),
        priority_soc=float(config.get("battery_priority_soc", 30)),
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
        # charge and the deep-deficit guard treats solar as "none". The
        # fallback matches the seeded default (DEFAULT_MIN_SOLAR_POWER =
        # 1000 W) so a legacy config missing the key gates the same as a
        # fresh install — fixes the old 200-vs-1000 inconsistency where a
        # keyless config silently used 200 W.
        min_solar_w=float(
            config.get("minimum_solar_power",
                       config.get("min_solar_power", 1000))
        ),
        # #576 — the one priority list: the battery's slot + command state
        # (fleet-level; one home battery). The per-charger ``ev_priority``
        # is compared against ``battery_priority`` in decide's reclaim gate.
        battery_priority=fleet_state.battery_priority,
        battery_commanded=fleet_state.battery_commanded,
    )

    # A working copy of the per-charger config, filled in below with the
    # hardware keys the entry does not carry (#678).
    #
    # (#638) This dict used to smuggle the planner's verdict too, as
    # ``_tariff_wait`` — "avoids extending the ChargerView signature with
    # an opaque kwarg", said the comment that lived here. The opacity was
    # the problem: an untyped key is invisible to a reader of ``decide()``,
    # so two of the three night modes never consulted it. It is a typed
    # ``plan`` field on the view now.
    cfg_resolved = dict(charger_cfg) if isinstance(charger_cfg, dict) else {}

    # #678 — fill the hardware keys the per-charger dict does not carry.
    #
    # ``decide()`` reads all four of these off ``view.config``, i.e. the
    # raw ``ev_chargers[i]`` entry. Nothing writes ``ev_max_current`` or
    # ``ev_voltage`` into that entry — there is no config-flow field for
    # either, and ``__init__._SEED_KEYS`` covers only ``ev_min_current``
    # and ``ev_phases``, and only for entries migrated from schema v3.
    # A fresh install carries NONE of them, so decide fell back to its
    # own literals: 32 A, 230 V, 6 A, 3 phases. Verified live on HA-TEST
    # — all four read as None on a normally-installed entry, top-level
    # config included.
    #
    # The adapters clamp before the write (``min(amps, max_current_a)``),
    # so no over-current ever reached hardware — which is exactly why
    # this stayed invisible. What it DID do is over-credit the priority
    # cascade: a 16 A charger commanded at 32 claims 22 kW of solar it
    # cannot draw, and the difference is taken off what the next charger
    # in the list is allowed to see.
    for _key in ("ev_max_current", "ev_min_current", "ev_phases", "ev_voltage"):
        if cfg_resolved.get(_key) is None:
            _fleet_val = config.get(_key)
            if _fleet_val is not None:
                cfg_resolved[_key] = _fleet_val

    # ``hardware_max_a`` is the adapter's ``max_current_a`` — the SAME
    # value the adapter clamps every command to, and the only ceiling
    # that is true regardless of whether anyone filled in a config key.
    # For an entity-controlled charger it already folds in the control
    # number's own max (``devices.base.effective_max_current``, #536).
    #
    # Take the MINIMUM of it and any configured value: a config key can
    # ask for less than the hardware allows (a user throttling a shared
    # supply), never for more. Deciding above the clamp is precisely the
    # drift that over-credits the cascade — same principle as #627's
    # ``can_stop_charging``, where the probe ends at the predicate the
    # action dispatches on so the two cannot disagree.
    if hardware_max_a is not None:
        try:
            _hw = float(hardware_max_a)
        except (TypeError, ValueError):
            _hw = None
        if _hw is not None and _hw > 0:
            _cfg_max = cfg_resolved.get("ev_max_current")
            try:
                _hw = min(_hw, float(_cfg_max)) if _cfg_max is not None else _hw
            except (TypeError, ValueError):
                pass
            cfg_resolved["ev_max_current"] = int(_hw)

    return ChargerView(
        power=cp,
        energy=ce,
        mode=mode,
        config=cfg_resolved,
        fleet=fleet,
        plan=plan,
        target_kwh=target_kwh,
        target_soc=target_soc,
        deadline_amps=deadline_amps,
        top_up_amps=top_up_amps,
        night_deliverable_kwh=night_deliverable_kwh,
        soc_ceiling_reached=soc_ceiling_reached,
        ev_priority=ev_priority,
    )
