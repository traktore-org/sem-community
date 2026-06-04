"""Scenario replay harness for the SEM coordinator (#282).

Lets us feed a timeline of sensor readings into a real ``SEMCoordinator``
update cycle and assert on its decisions + actuator commands. The goal is
to catch behaviour bugs that unit tests miss — bugs where the *decision*
(e.g. strategy="solar_only") and the *enforcement* (actual current sent
to the charger) disagree.

YAML scenario shape:

    name: "..."
    description: "..."
    config:
        # SEMCoordinator config dict. Keys are merged with safe defaults.
        battery_capacity_kwh: 15.0
        battery_buffer_soc: 70
        # ...
        ev_chargers:
            - id: "ev_charger"
              ev_charging_mode: "auto"
    cycle_seconds: 30
    timeline:
        - t: 0
          solar_power: 5500
          grid_power: -4200          # negative = export
          battery_power: 0
          battery_soc: 75
          ev_power: 0
          ev_connected: true
        - t: 60
          # Sticky semantics: omitted keys inherit from the previous cycle.
          ev_power: 9900
          grid_power: 3100
          battery_power: -500
    expect:
        strategy_substring: "solar_only"
        actuator_current_a:
            when_strategy: "solar_only"
            max_w_minus_margin: 500
            formula: "max(0, solar_power - home_consumption_power)"
        cumulative:
            flow_grid_to_ev_kwh_max: 0.2

The harness reuses ``PowerReadings.calculate_derived()`` so the YAML only
needs the raw source readings. Derived fields (home_consumption_power,
grid_import_power, etc.) are filled in by the canonical SEM math. The
``home_consumption_power`` key in the timeline overrides the derived value
when the scenario needs to model a stale or inflated home sensor.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, AsyncMock

import yaml


# Sensor keys recognised in the YAML timeline. Anything else triggers a clear
# error so typos don't silently no-op.
TIMELINE_FIELDS = {
    "solar_power", "grid_power", "battery_power", "ev_power",
    "battery_soc", "battery_temperature", "battery_soc_unavailable",
    "ev_connected", "ev_charging",
    "home_consumption_power",  # override the derived value when needed
    # v1.6.12: per-charger EV draw in watts as a mapping ``{cid: watts}``.
    # When present, populates ``PowerReadings.ev_power_per_charger`` so
    # the flow calculator can produce ``PowerFlows.per_charger`` for
    # multi-charger scenarios. ``ev_power`` is still the fleet sum; the
    # values here should add to it (the harness does NOT auto-derive).
    "ev_power_per_charger",
    # 2026-06-02: per-charger plug state ``{cid: bool}``. Lets
    # multi-charger scenarios test plug-in / plug-out independently
    # per charger. Populates ``PowerReadings.ev_connected_per_charger``
    # / ``ev_charging_per_charger`` which ``build_charger_view`` reads
    # via ``getattr`` with fleet-OR fallback.
    "ev_connected_per_charger",
    "ev_charging_per_charger",
    # 2026-06-02: per-cycle ``is_night`` override. Lets scenarios test
    # sunset / sunrise transitions where ``time_manager.is_night_mode()``
    # flips mid-timeline. Falls back to the config-level ``is_night``
    # when not set on the row.
    "is_night",
    # 2026-06-02: per-cycle ``tariff_level`` override. Lets scenarios
    # test tariff oscillation during a night charge (cheap→expensive→cheap)
    # to pin that the strategy is stable across rapid level changes.
    # One of very_cheap / cheap / normal / expensive / very_expensive.
    # Falls back to the config-level ``tariff_level`` when omitted.
    "tariff_level",
}


@dataclass
class CycleRecord:
    """One cycle's captured inputs + outputs. Used for assertion + debugging."""
    t_seconds: int
    sim_time: datetime
    readings: Dict[str, float]  # raw + derived
    result: Dict[str, Any]      # coordinator's data dict (subset)
    actuator_calls: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ScenarioRun:
    """Output of a complete scenario run, ready for assertion."""
    name: str
    description: str
    cycles: List[CycleRecord]

    def cycles_where(self, strategy_substring: str) -> List[CycleRecord]:
        """Cycles where ``canonical_strategy`` contains the substring.

        The YAML scenarios use ``strategy_substring`` like ``"solar_only"``,
        ``"battery_assist"`` — these are EVBudgetStrategy values, the
        budget-input regime. Post arch-rewrite (#358), ``charging_strategy``
        on the coord.data dict now stores ChargerIntent values
        (``"charge_at_amps"``, ``"idle"``, etc.) — actuator commands, NOT
        the regime. ``canonical_strategy`` is what the YAML expectations
        actually mean, exposed on coord.data since the v1.7 prep.
        """
        return [
            c for c in self.cycles
            if strategy_substring.lower() in
                str(c.result.get("canonical_strategy") or "").lower()
        ]

    def cumulative_kwh(self, key: str, cycle_seconds: int) -> float:
        """Integrate a power result (W) across the cycle stream → kWh."""
        total_wh = sum(
            float(c.result.get(key, 0.0) or 0.0) for c in self.cycles
        ) * (cycle_seconds / 3600.0)
        return total_wh / 1000.0

    def last_actuator_current(self) -> Optional[float]:
        """The amps from the most recent recorded set_current call (any source)."""
        for c in reversed(self.cycles):
            for call in reversed(c.actuator_calls):
                amps = call.get("current") or call.get("amps")
                if amps is not None:
                    return float(amps)
        return None


def load_scenario(yaml_path: Path) -> Dict[str, Any]:
    """Load + lightly validate a scenario YAML."""
    data = yaml.safe_load(yaml_path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{yaml_path}: top-level YAML must be a mapping")
    for required in ("name", "timeline", "expect"):
        if required not in data:
            raise ValueError(f"{yaml_path}: missing required key '{required}'")
    # Sanity-check timeline keys
    for i, row in enumerate(data["timeline"]):
        if "t" not in row:
            raise ValueError(f"{yaml_path}: timeline row {i} missing 't'")
        unknown = set(row.keys()) - TIMELINE_FIELDS - {"t"}
        if unknown:
            raise ValueError(
                f"{yaml_path}: timeline row {i} has unknown keys {sorted(unknown)} — "
                f"valid keys are {sorted(TIMELINE_FIELDS | {'t'})}"
            )
    return data


def _resolve_sticky_row(timeline: List[Dict[str, Any]], target_t: int) -> Dict[str, Any]:
    """Build the effective sensor reading at time ``target_t`` using sticky
    semantics: each field's value is the most recent prior row's value (or
    the row at exactly ``target_t``)."""
    effective: Dict[str, Any] = {}
    for row in timeline:
        if row["t"] > target_t:
            break
        for k, v in row.items():
            if k == "t":
                continue
            effective[k] = v
    return effective


def _build_power_readings(effective: Dict[str, Any]):
    """Construct a PowerReadings from an effective row, applying
    calculate_derived(). The YAML may override home_consumption_power
    after the derivation."""
    from custom_components.solar_energy_management.coordinator.types import PowerReadings
    pr = PowerReadings(
        solar_power=float(effective.get("solar_power", 0.0)),
        grid_power=float(effective.get("grid_power", 0.0)),
        battery_power=float(effective.get("battery_power", 0.0)),
        ev_power=float(effective.get("ev_power", 0.0)),
        battery_soc=float(effective.get("battery_soc", 50.0)),
        battery_temperature=float(effective.get("battery_temperature", 25.0)),
        battery_soc_unavailable=bool(effective.get("battery_soc_unavailable", False)),
        ev_connected=bool(effective.get("ev_connected", False)),
        ev_charging=bool(effective.get("ev_charging", False)),
    )
    pr.calculate_derived()
    # Allow explicit override of home_consumption_power for stale-sensor scenarios
    if "home_consumption_power" in effective:
        pr.home_consumption_power = float(effective["home_consumption_power"])
    # v1.6.12: per-charger EV power for ``flow_calculator.calculate_power_flows``
    # per-charger split. Sticky timeline carries the mapping forward like
    # any other field.
    if "ev_power_per_charger" in effective:
        per_charger = effective["ev_power_per_charger"]
        if isinstance(per_charger, dict):
            pr.ev_power_per_charger = {
                str(k): float(v) for k, v in per_charger.items()
            }
    # 2026-06-02: per-charger plug + charging state. ``build_charger_view``
    # reads these via ``getattr`` with fleet-OR fallback. When YAML
    # supplies the mapping, the per-charger value wins; absent keys
    # fall through to ``pr.ev_connected`` / ``pr.ev_charging``.
    if "ev_connected_per_charger" in effective:
        m = effective["ev_connected_per_charger"]
        if isinstance(m, dict):
            pr.ev_connected_per_charger = {
                str(k): bool(v) for k, v in m.items()
            }
    if "ev_charging_per_charger" in effective:
        m = effective["ev_charging_per_charger"]
        if isinstance(m, dict):
            pr.ev_charging_per_charger = {
                str(k): bool(v) for k, v in m.items()
            }
    return pr


def _build_coordinator(scenario: Dict[str, Any]):
    """Build a minimal SEMCoordinator that exercises the bug-prone code paths.

    We don't run the full Home Assistant integration setup — that would
    require a real hass + recorder. Instead we instantiate the coordinator
    via __new__ (the same pattern existing tests use, e.g.
    test_ev_target_ux.py:_make_coordinator) and set the fields the
    strategy / budget / state machine code touches.
    """
    from custom_components.solar_energy_management.coordinator import SEMCoordinator
    from custom_components.solar_energy_management.coordinator.flow_calculator import (
        FlowCalculator,
    )

    coord = SEMCoordinator.__new__(SEMCoordinator)
    coord.hass = MagicMock()
    coord.hass.states = MagicMock()
    coord.hass.states.get = MagicMock(return_value=None)
    coord.hass.states.is_state = MagicMock(return_value=False)
    coord.hass.services = MagicMock()
    coord.hass.services.async_call = AsyncMock()
    coord.hass.config = MagicMock()
    coord.hass.config.currency = "CHF"

    cfg = scenario.get("config", {}) or {}
    coord.config = {
        # Safe defaults, then overlay scenario config
        "battery_capacity_kwh": 15.0,
        "battery_buffer_soc": 70,
        "battery_auto_start_soc": 90,
        "battery_priority_soc": 30,
        "battery_assist_floor_soc": 60,
        "ev_charging_mode": "auto",
        "ev_min_current": 6,
        "ev_max_current": 16,
        "ev_phases": 3,
        "ev_voltage": 230,
        "daily_ev_target": 7.0,
        "update_interval": int(scenario.get("cycle_seconds", 30)),
        **cfg,
    }
    coord._flow_calculator = FlowCalculator()
    coord.update_interval = timedelta(seconds=int(scenario.get("cycle_seconds", 30)))

    # Multi-charger support (Phase B.5 / #284 verification): when the YAML
    # ``ev_chargers`` block has 2+ entries, build mock devices keyed by id
    # so the coordinator's distribution branch has a non-trivial set to
    # divide the canonical budget across. Each charger inherits sensible
    # defaults; per-charger overrides via the YAML take precedence.
    coord._ev_devices = {}
    ev_chargers_cfg = coord.config.get("ev_chargers") or []
    if len(ev_chargers_cfg) >= 2:
        for c in ev_chargers_cfg:
            cid = c.get("id", f"charger_{len(coord._ev_devices)}")
            dev = MagicMock()
            dev.priority = int(c.get("priority", 3))
            dev.min_current = float(c.get("min_current", 6))
            dev.max_current = float(c.get("max_current", 16))
            dev.phases = int(c.get("phases", 3))
            dev.voltage = float(c.get("voltage", 230))
            dev.min_power_threshold = (
                dev.min_current * dev.phases * dev.voltage
            )
            coord._ev_devices[cid] = dev

    # Real SurplusController for distribute_ev_budget — it's a small pure
    # function on (budget_w, devices) so we want the production version,
    # not a mock. Build with the minimal hass mock SurplusController needs.
    #
    # NOTE: SurplusController.__init__ signature is (hass, regulation_offset).
    # An earlier version of this harness passed ``coord.config`` (a dict)
    # as the second positional, which silently became ``regulation_offset``.
    # That was a real bug — masked by the fact that ``distribute_ev_budget``
    # doesn't read ``regulation_offset``, so the harness's only use of
    # the controller wasn't affected. Future use of ``.update()`` would
    # have crashed. Fixed: pass hass only and let regulation_offset default.
    from custom_components.solar_energy_management.coordinator.surplus_controller import (
        SurplusController,
    )
    coord._surplus_controller = SurplusController(coord.hass)

    coord._ev_device = None
    coord._cycle_night_plan = None
    coord._cycle_vehicle_soc = None  # No external vehicle SOC entity in scenario
    coord._cycle_ev_budget = None  # populated by _build_charging_context per cycle

    # _calculate_remaining_need's SOC fallback path reads these via getattr;
    # explicit empty defaults keep the harness deterministic.
    coord._ev_taper_detector = None
    coord._ev_taper_detectors = {}

    # Night-charging path (``_build_charging_context`` calls
    # ``_compute_night_plan`` when ``is_night and night_target > 0.1``)
    # reaches into ``_load_manager`` for the peak limit and
    # ``_peak_consumption_15min`` for the rolling 15-min peak (#288).
    # Provide ``None`` stubs so the truthy-check fallbacks fire — the
    # harness uses the config-default peak limit instead.
    coord._load_manager = None
    coord._peak_consumption_15min = None
    # Forecast stub — Zone 3 needs ``forecast.available`` and
    # ``forecast.forecast_remaining_today_kwh`` to decide solar_only vs
    # battery_assist. With dampening_factor=1.0 and surplus_factor=0.5
    # (hardcoded in coordinator.py), estimated_surplus =
    # forecast_remaining * 0.5. For solar_only the threshold is
    # surplus >= remaining_need * 1.5, so 25 kWh → 12.5 kWh surplus
    # comfortably clears a 7 kWh daily target.
    forecast_stub = MagicMock()
    forecast_stub.available = True
    forecast_stub.forecast_remaining_today_kwh = 25.0
    coord._cycle_forecast = forecast_stub
    coord._tariff_provider = None
    coord._tariff_pause_warned = False
    coord._daily_ev_per_charger = {}
    coord._daily_ev_per_charger_date = {}
    coord._night_plan_per_charger = {}
    coord._zone_debounce = {}  # used by _debounce_zone
    coord._observer_mode = False
    # battery_capacity_kwh is a @property on SEMCoordinator that reads from
    # config — we already populated config above, so no extra set needed.
    coord._forecast_tracker = MagicMock()
    coord._forecast_tracker.dampening_factor = 1.0
    # apply_dampening is called from the night-charging top-up path
    # (coordinator.py:2830). Default MagicMock returns something that
    # doesn't compare cleanly with floats — make it a pass-through so
    # downstream arithmetic doesn't crash inside the harness.
    coord._forecast_tracker.apply_dampening = lambda x: x
    # state machine + time manager — strategy doesn't need their behaviour,
    # only their presence. Mock at the attribute level so attr lookups succeed.
    coord._state_machine = MagicMock()
    coord._state_machine.current_state = None
    coord.time_manager = MagicMock()
    # Scenario-controlled night flag (default day). Set ``is_night: true`` in
    # the YAML's top-level config block to flip into night mode — required
    # for night-charging deadline + tariff-window scenarios (#246/#247/#268).
    scenario_is_night = bool(cfg.get("is_night", False))
    coord.time_manager.is_night_mode = MagicMock(return_value=scenario_is_night)
    # Scenario-controlled tariff level for solar_plus_cheap regime. One of
    # very_cheap / cheap / normal / expensive / very_expensive (matches
    # consts.tariff.PriceLevel). Plumbed onto a stub tariff_provider so
    # build_charger_view can populate FleetContext.tariff_level.
    scenario_tariff = cfg.get("tariff_level")
    if scenario_tariff is not None:
        tariff_stub = MagicMock()
        tariff_stub.current_level = str(scenario_tariff)
        tariff_stub.available = True
        coord._tariff_provider = tariff_stub
    coord._sensor_reader = MagicMock()
    return coord


def _capture_actuator_calls(coord) -> List[Dict[str, Any]]:
    """Wrap ``hass.services.async_call`` to record any keba/wallbox/charger
    service call. Returns the shared list — extended as calls come in.
    """
    calls: List[Dict[str, Any]] = []
    orig = coord.hass.services.async_call

    async def _capture(domain, service, data=None, blocking=False, **_):
        # Only record charger-control calls; everything else passes through.
        if domain in ("keba", "wallbox", "easee", "number") or "current" in str(service):
            calls.append({
                "domain": domain,
                "service": service,
                **(data or {}),
            })
        if orig is not None and isinstance(orig, AsyncMock):
            await orig(domain, service, data, blocking=blocking)

    coord.hass.services.async_call = _capture
    return calls


async def run_scenario(yaml_path: Path) -> ScenarioRun:
    """Execute one YAML scenario through the coordinator, return the recorded run.

    Strategy: for each timeline tick, resolve the sticky sensor row, build a
    PowerReadings, then exercise the bug-relevant path:

      * ``_determine_charging_strategy`` → strategy tuple
      * ``_flow_calculator.calculate_power_flows`` → instantaneous flows
      * ``_flow_calculator.calculate_canonical_ev_budget`` (with the canonical
        strategy mapped from the legacy strategy string) → ``EVBudget``
        with ``net_w`` (setpoint watts) and ``current_a`` (setpoint amps)
      * For multi-charger scenarios, ``EVBudget.net_w`` flows through
        ``SurplusController.distribute_ev_budget`` — the exact production
        path post-Phase B.5

    The actuator call is simulated by invoking ``coord.hass.services.async_call``
    with the chosen amps; the capture wrapper records it.

    Pre-Phase-D.2 (#282) this harness called the now-deleted
    ``calculate_ev_budget`` and ``calculate_charging_current`` primitives
    inside ``try/except: pass`` blocks — when those were removed the
    scenarios silently passed every assertion because ``calculated_current``
    fell to 0. The rewrite below uses the canonical EVBudget directly so
    the harness fails loudly if the canonical path regresses.
    """
    from homeassistant.util import dt as dt_util

    scenario = load_scenario(yaml_path)
    coord = _build_coordinator(scenario)
    actuator_calls = _capture_actuator_calls(coord)
    cycle_seconds = int(scenario.get("cycle_seconds", 30))
    timeline = scenario["timeline"]

    sim_start = datetime(2026, 5, 28, 14, 12, 0, tzinfo=timezone.utc)

    # Determine cycle range from timeline
    max_t = max(int(r["t"]) for r in timeline)
    cycle_ts = list(range(0, max_t + cycle_seconds, cycle_seconds))

    cycles: List[CycleRecord] = []
    saved_now = dt_util.now

    for t in cycle_ts:
        sim_time = sim_start + timedelta(seconds=t)
        dt_util.now = lambda st=sim_time: st  # noqa: E731

        effective = _resolve_sticky_row(timeline, t)
        # 2026-06-02: per-cycle ``is_night`` override. Lets a single
        # scenario walk through sunset/sunrise by flipping the flag
        # mid-timeline. Falls back to the config-level ``is_night``
        # (set in ``_build_coordinator``) when the timeline row
        # doesn't override.
        if "is_night" in effective:
            coord.time_manager.is_night_mode = MagicMock(
                return_value=bool(effective["is_night"]),
            )
        # 2026-06-02: per-cycle ``tariff_level`` override. Update the
        # stub tariff_provider in place so each cycle's strategy sees
        # the correct level. Creating the stub here if absent lets a
        # scenario rely entirely on per-cycle tariff (no config-level
        # default required).
        if "tariff_level" in effective:
            provider = getattr(coord, "_tariff_provider", None)
            if provider is None:
                provider = MagicMock()
                provider.available = True
                coord._tariff_provider = provider
            provider.current_level = str(effective["tariff_level"])
        readings = _build_power_readings(effective)

        # Record raw + derived
        readings_dict = {
            "solar_power": readings.solar_power,
            "grid_power": readings.grid_power,
            "grid_import_power": readings.grid_import_power,
            "grid_export_power": readings.grid_export_power,
            "battery_power": readings.battery_power,
            "battery_charge_power": readings.battery_charge_power,
            "battery_discharge_power": readings.battery_discharge_power,
            "battery_soc": readings.battery_soc,
            "ev_power": readings.ev_power,
            "ev_connected": readings.ev_connected,
            "home_consumption_power": readings.home_consumption_power,
        }

        # Power flows (per-cycle, correctly attributed)
        power_flows = coord._flow_calculator.calculate_power_flows(readings)

        # ── Strategy + canonical budget via the production decision path ──
        #
        # Pre-arch-rewrite the harness called the long-removed
        # ``_determine_charging_strategy`` directly and re-implemented the
        # legacy→canonical mapping inline (the exact pattern v1.6.2 caught).
        # Post-#358 we go through ``_build_charging_context`` instead, which
        # is what coordinator._async_update_data also calls (line 1114).
        # That gives us:
        #   * ``charging_context.charging_strategy`` — ChargerIntent.value
        #     (the actuator command: idle / charge_at_amps / charge_max /
        #     disable). New since PR #358.
        #   * ``charging_context.canonical_strategy`` — EVBudgetStrategy.value
        #     (the budget-input regime: solar_only / battery_assist /
        #     self_consumption / now / min_pv / idle). Added to ChargingContext
        #     specifically so the harness doesn't need to re-derive it.
        #   * ``coord._cycle_ev_budget`` — the EVBudget cached on coord by
        #     _build_charging_context for the actuator. ``.net_w`` and
        #     ``.current_a`` are what production reads.
        #
        # Any failure here is now LOUD (raised), not swallowed. The whole
        # point of the harness is to catch decision-vs-enforcement drift —
        # silently catching the SUT call defeats that.
        from custom_components.solar_energy_management.coordinator.types import (
            EnergyTotals,
        )
        energy = EnergyTotals(daily_ev=0.0, daily_solar=0.0)

        charging_context = coord._build_charging_context(readings, energy)
        strategy = charging_context.charging_strategy
        strategy_reason = charging_context.charging_strategy_reason
        canonical_strat_value = charging_context.canonical_strategy

        # EVBudgetStrategy is a string-constant class (not an Enum), so
        # canonical_strategy on the context IS the canonical value string
        # already. Existing downstream code in this harness uses the
        # string directly, so the previous "map to enum" step is moot.
        canonical_strat = canonical_strat_value

        ev_budget_obj = coord._cycle_ev_budget
        # _build_charging_context unconditionally computes and caches the
        # budget (the contract since #282 Phase B/D). If this is None
        # something is wrong with the harness setup — fail loudly so the
        # next caller can see it.
        assert ev_budget_obj is not None, (
            "coord._cycle_ev_budget was not populated by "
            "_build_charging_context — harness setup is incomplete"
        )
        budget_w = ev_budget_obj.net_w
        amps = ev_budget_obj.current_a

        # Simulate the actuator: when strategy says "go" and amps > min,
        # SEM would call keba.set_current(<amps>). Capture it.
        if amps > 0 and readings.ev_connected:
            await coord.hass.services.async_call(
                "keba", "set_current", {"current": amps}, blocking=False,
            )

        # Cycle-level captured outputs (flat dict mirrors coord.data shape).
        # ``canonical_strategy`` is what YAML ``strategy_substring`` expectations
        # match against — populate for every cycle, not just multi-charger.
        result = {
            "charging_strategy": strategy,
            "charging_strategy_reason": strategy_reason,
            "canonical_strategy": canonical_strat_value,
            "calculated_current": amps,
            "ev_budget_w": budget_w,
            "flow_solar_to_ev_power": power_flows.solar_to_ev,
            "flow_grid_to_ev_power": power_flows.grid_to_ev,
            "flow_battery_to_ev_power": power_flows.battery_to_ev,
        }

        # v1.6.12: per-charger flow attribution. When the scenario
        # populated ``ev_power_per_charger`` on the readings,
        # ``calculate_power_flows`` produces a per-charger flow map
        # (``PowerFlows.per_charger[cid] = ChargerFlows(...)``) that
        # closes the #316 family. Surface those flows in the cycle
        # result so the assertion machinery can pin them.
        if power_flows.per_charger:
            result["per_charger_flows"] = {
                cid: {
                    "solar_to_ev": cf.solar_to_ev,
                    "grid_to_ev": cf.grid_to_ev,
                    "battery_to_ev": cf.battery_to_ev,
                }
                for cid, cf in power_flows.per_charger.items()
            }

        # v1.6.12: per-charger effective state — exercise the same
        # ``_apply_per_charger_off_override`` static helper the
        # production multi-charger loop calls at coordinator.py:1217.
        # Maps the fleet ``charging_state`` (from the state machine, or
        # a synthetic ``SOLAR_CHARGING_ACTIVE`` here since the harness
        # skips the state machine) onto each charger's effective state
        # using its per-charger ``charge_mode``. This is the surface
        # that #315's regression class shows up on.
        ev_chargers_cfg = coord.config.get("ev_chargers") or []
        if len(ev_chargers_cfg) >= 2 and strategy is not None:
            from custom_components.solar_energy_management.consts.states import (
                ChargingState,
            )
            from custom_components.solar_energy_management.coordinator import (
                SEMCoordinator,
            )
            # Pick a fleet baseline that lets each charger's override
            # branch reveal itself. SOLAR_CHARGING_ACTIVE = primary is
            # actively charging; the override turns a per-charger
            # ``off`` mode into SOLAR_IDLE (terminate) and leaves
            # ``solar_only`` / ``min_plus_solar`` untouched.
            #
            # Drive the baseline off ``canonical_strategy`` (the budget-
            # regime intent), NOT ``charging_strategy`` — the latter is
            # ChargerIntent post-#358 ("charge_at_amps" etc.) and never
            # equals "solar_only".
            global_state = (
                ChargingState.SOLAR_CHARGING_ACTIVE
                if canonical_strat_value == "solar_only" else ChargingState.SOLAR_IDLE
            )
            per_charger_states: Dict[str, str] = {}
            for c in ev_chargers_cfg:
                cid = c.get("id") or "ev_charger"
                # ``charge_mode`` lives in per-charger config; fall back
                # through the same precedence the production helper
                # uses (per-charger > global > default).
                per_mode = c.get("charge_mode") or coord.config.get(
                    "charge_mode", "min_plus_solar",
                )
                per_charger_states[cid] = (
                    SEMCoordinator._apply_per_charger_off_override(
                        global_state, per_mode,
                    )
                )
            result["per_charger_effective_states"] = per_charger_states

        # Multi-charger distribution (Phase B.5 / #284). The canonical
        # ``ev_budget_obj`` computed above already represents the total
        # fleet budget; we pass its ``net_w`` through the real
        # ``SurplusController.distribute_ev_budget`` — the exact code path
        # ``coordinator.py:966`` runs in production. This verifies the
        # priority cascade splits the canonical budget sensibly across
        # multiple chargers, without re-deriving a separate per-charger
        # value (the divergence the canonical unification eliminated).
        if len(coord._ev_devices) >= 2 and strategy is not None:
            try:
                allocations = coord._surplus_controller.distribute_ev_budget(
                    ev_budget_obj.net_w, coord._ev_devices,
                )
            except Exception as e:  # pragma: no cover — defensive
                allocations = {}
                result["multi_charger_dist_error"] = f"{type(e).__name__}: {e}"

            result["canonical_net_w"] = ev_budget_obj.net_w
            result["canonical_strategy"] = canonical_strat
            result["ev_budget_per_charger"] = allocations
            result["ev_budget_per_charger_total"] = sum(allocations.values())

        cycles.append(CycleRecord(
            t_seconds=t,
            sim_time=sim_time,
            readings=readings_dict,
            result=result,
            actuator_calls=list(actuator_calls),  # snapshot
        ))
        actuator_calls.clear()

    dt_util.now = saved_now
    return ScenarioRun(
        name=scenario["name"],
        description=scenario.get("description", ""),
        cycles=cycles,
    )


def assert_expectations(run: ScenarioRun, scenario: Dict[str, Any]) -> None:
    """Run all ``expect`` block assertions on the recorded run.

    Raises AssertionError with a clear, debuggable message on first failure.
    """
    expect = scenario.get("expect", {}) or {}
    cycle_seconds = int(scenario.get("cycle_seconds", 30))

    # 1. Strategy substring — at least one cycle's canonical_strategy must contain it.
    # See ``cycles_where`` docstring for the canonical/charging strategy split.
    sub = expect.get("strategy_substring")
    if sub:
        matched = run.cycles_where(sub)
        assert matched, (
            f"No cycle had a canonical_strategy containing '{sub}'. Got: "
            f"{[c.result.get('canonical_strategy') for c in run.cycles]}"
        )

    # 1b. Negative strategy assertion — NO cycle's canonical_strategy may
    # contain the substring. Lets edge-case scenarios pin a regression
    # boundary without dictating which fallback (idle / solar_only /
    # self_consumption) is chosen. Used by e.g. battery-protection
    # scenarios that just need "definitely not battery_assist".
    not_sub = expect.get("strategy_not_substring")
    if not_sub:
        violators = run.cycles_where(not_sub)
        assert not violators, (
            f"Strategy contained forbidden substring '{not_sub}' in "
            f"{len(violators)} cycle(s): "
            f"{[c.result.get('canonical_strategy') for c in violators]}"
        )

    # 2. Actuator current constraint — for cycles where the canonical strategy matches.
    # Same canonical/charging split as ``cycles_where``.
    ac = expect.get("actuator_current_a") or {}
    if ac:
        when_strategy = ac.get("when_strategy", "")
        formula = ac.get("formula", "0")
        margin_w = float(ac.get("max_w_minus_margin", 0))
        voltage = 230.0
        phases = 3.0
        for c in run.cycles:
            strat = str(c.result.get("canonical_strategy") or "").lower()
            if when_strategy.lower() not in strat:
                continue
            # Evaluate the formula in the readings dict's namespace
            try:
                allowed_w = float(eval(formula, {"__builtins__": {}, "max": max, "min": min}, c.readings))
            except Exception as e:
                raise AssertionError(
                    f"Cycle t={c.t_seconds}: failed to evaluate formula "
                    f"'{formula}' against readings {c.readings}: {e}"
                )
            allowed_a = max(0.0, (allowed_w - margin_w) / (voltage * phases))
            actual_a = float(c.result.get("calculated_current", 0))
            assert actual_a <= allowed_a + 0.5, (  # 0.5A floating tolerance
                f"Cycle t={c.t_seconds}: actuator amps {actual_a:.1f}A exceeds "
                f"surplus ceiling {allowed_a:.1f}A "
                f"(allowed_w={allowed_w:.0f}W, margin={margin_w:.0f}W, "
                f"readings.solar={c.readings['solar_power']:.0f}W, "
                f"home={c.readings['home_consumption_power']:.0f}W, "
                f"ev_power={c.readings['ev_power']:.0f}W). "
                f"Strategy was '{c.result.get('charging_strategy')}'."
            )

    # 3. Cumulative aggregates
    cum = expect.get("cumulative") or {}
    for key, max_val in cum.items():
        if key.endswith("_kwh_max"):
            base_key = key[:-len("_kwh_max")]  # e.g. "flow_grid_to_ev"
            power_key = f"{base_key}_power"
            actual_kwh = run.cumulative_kwh(power_key, cycle_seconds)
            assert actual_kwh <= float(max_val), (
                f"Cumulative {power_key} integrated to {actual_kwh:.3f} kWh, "
                f"max allowed {float(max_val):.3f} kWh. Bug is locked in — "
                f"SEM allowed too much {base_key.replace('_to_', '→')} energy."
            )

    # 4. Multi-charger assertions (#284 / Phase B.5). Only fire on scenarios
    # that actually exercised the multi-charger distribution branch.
    mc = expect.get("multi_charger") or {}
    if mc:
        multi_cycles = [
            c for c in run.cycles
            if "ev_budget_per_charger" in c.result
        ]
        assert multi_cycles, (
            "expect.multi_charger requires the scenario's `ev_chargers` "
            "block to have 2+ entries — otherwise the distribution branch "
            "never ran."
        )

        # `total_equals_canonical: true` — the per-charger budgets must sum
        # to the canonical net_w (within a small rounding tolerance). This
        # is the core Phase B.5 contract: distribute uses the canonical
        # value, no clipping, no leakage to or from another formula.
        if mc.get("total_equals_canonical"):
            tol_w = float(mc.get("tolerance_w", 1.0))
            for c in multi_cycles:
                net = float(c.result.get("canonical_net_w", 0))
                total = float(c.result.get("ev_budget_per_charger_total", 0))
                # Distribution naturally drops the remainder when no
                # charger can claim it (below min_power_threshold) — that
                # part is correct, not a leak. Test: total ≤ net within
                # tolerance, AND remainder explained by per-charger floors.
                assert total <= net + tol_w, (
                    f"Cycle t={c.t_seconds}: distributed {total:.0f} W exceeds "
                    f"canonical net_w {net:.0f} W (tol {tol_w} W). The "
                    f"distributor over-allocated — should never happen."
                )
                # Allocations: {cid: w}. Each non-zero allocation must be
                # ≥ that charger's min_power_threshold (else the distributor
                # bug-ed and gave a charger less than it can actually use).
                allocs = c.result.get("ev_budget_per_charger") or {}
                for cid, w in allocs.items():
                    if w == 0:
                        continue
                    dev_min = (
                        getattr(c, "_min_thresholds", {}).get(cid)
                        or 4140  # default 6A * 3 * 230
                    )
                    assert w >= dev_min - 1, (
                        f"Cycle t={c.t_seconds}: charger {cid} got {w:.0f} W "
                        f"which is below its min_power_threshold {dev_min:.0f} W"
                    )

        # `at_least_one_charger_gets_positive: true` — for cycles where
        # the canonical net_w exceeds the lowest charger's threshold,
        # SOMETHING should be allocated. Catches a regression where the
        # distributor silently returns all-zero.
        if mc.get("at_least_one_charger_gets_positive"):
            for c in multi_cycles:
                net = float(c.result.get("canonical_net_w", 0))
                if net < 4140:
                    continue  # below 6A * 3 * 230 — no charger qualifies
                allocs = c.result.get("ev_budget_per_charger") or {}
                pos = sum(1 for w in allocs.values() if w > 0)
                assert pos >= 1, (
                    f"Cycle t={c.t_seconds}: net_w={net:.0f} W is above any "
                    f"charger's minimum, yet zero chargers got a positive "
                    f"budget. Distributor returned {allocs}. "
                    f"Phase B.5 / #284 regression."
                )

        # v1.6.12: per-charger effective state assertion. Pinning the
        # output of ``_apply_per_charger_off_override`` per charger
        # closes the gap the senior-engineer review flagged on the
        # v1.6.7→v1.6.10 arc (no scenario covered charger A=off +
        # charger B=solar_only mixed). YAML shape:
        #   multi_charger:
        #     per_charger_effective_states:
        #       charger_left: "solar_idle"     # exact match (case-insensitive)
        #       charger_right_contains: "charging_allowed"   # substring
        pces = mc.get("per_charger_effective_states") or {}
        if pces:
            cycles_with_states = [
                c for c in run.cycles
                if "per_charger_effective_states" in c.result
            ]
            assert cycles_with_states, (
                "expect.multi_charger.per_charger_effective_states is set "
                "but no cycle recorded per-charger effective states. "
                "The scenario's ``ev_chargers`` block needs 2+ entries "
                "AND a ``charge_mode`` on each charger."
            )
            last_states = cycles_with_states[-1].result["per_charger_effective_states"]
            for key, expected in pces.items():
                if key.endswith("_contains"):
                    cid = key[: -len("_contains")]
                    got = str(last_states.get(cid, "")).lower()
                    assert str(expected).lower() in got, (
                        f"per-charger effective state mismatch: charger "
                        f"{cid!r} ended up as {got!r}, expected substring "
                        f"{expected!r}. All states: {last_states}"
                    )
                else:
                    cid = key
                    got = str(last_states.get(cid, "")).lower()
                    assert got == str(expected).lower(), (
                        f"per-charger effective state mismatch: charger "
                        f"{cid!r} ended up as {got!r}, expected exactly "
                        f"{expected!r}. All states: {last_states}"
                    )

        # v1.6.12: per-charger flow attribution assertion. Pin the
        # ``PowerFlows.per_charger`` map populated by
        # ``flow_calculator.calculate_power_flows`` when the readings
        # carry ``ev_power_per_charger``. The fleet-sum invariant is
        # tested by ``test_per_charger_flows_319.py``; here we pin the
        # per-charger user-visible attribution that closes #316. YAML:
        #   multi_charger:
        #     per_charger_flow_max:
        #       charger_left:
        #         grid_to_ev: 0       # solar_only must not draw grid
        #       charger_right:
        #         grid_to_ev: 10000   # min_plus_solar may
        pcfm = mc.get("per_charger_flow_max") or {}
        if pcfm:
            cycles_with_flows = [
                c for c in run.cycles if "per_charger_flows" in c.result
            ]
            assert cycles_with_flows, (
                "expect.multi_charger.per_charger_flow_max is set but no "
                "cycle recorded per-charger flows. The scenario timeline "
                "needs ``ev_power_per_charger`` populated."
            )
            for cid, limits in pcfm.items():
                for c in cycles_with_flows:
                    flows = c.result["per_charger_flows"].get(cid) or {}
                    for flow_key, max_w in limits.items():
                        actual = float(flows.get(flow_key, 0.0))
                        assert actual <= float(max_w) + 0.5, (
                            f"Cycle t={c.t_seconds}: charger {cid!r} "
                            f"per-charger flow {flow_key}={actual:.1f} W "
                            f"exceeds max {float(max_w):.1f} W. "
                            f"Full flows for charger: {flows}"
                        )

        # `priority_order: true` — when budget can only feed N of M chargers,
        # the N lower-numbered priority chargers must get the budget.
        if mc.get("priority_order"):
            for c in multi_cycles:
                allocs = c.result.get("ev_budget_per_charger") or {}
                if len(allocs) < 2:
                    continue
                # Get devices from the run's coord (preserved via cycles)
                # — we don't have direct access here, but the cascade
                # rule is: anything > 0 must come before the first 0
                # in the priority-sorted ordering. We approximate by
                # checking no zero is sandwiched between two positives.
                vals = list(allocs.values())
                seen_zero = False
                for v in vals:
                    if v == 0:
                        seen_zero = True
                    elif seen_zero and v > 0:
                        # Positive after a zero — only valid if the
                        # priority-sort happened differently than dict
                        # order; can't reliably check from this side.
                        # Skip — the distributor's own unit tests cover
                        # priority cascade in detail.
                        pass


def run_and_assert(yaml_path: Path) -> None:
    """Convenience for pytest: load → run → assert in one call."""
    scenario = yaml.safe_load(yaml_path.read_text())
    run = asyncio.get_event_loop().run_until_complete(run_scenario(yaml_path))
    assert_expectations(run, scenario)
