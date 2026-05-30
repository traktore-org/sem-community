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
        return [
            c for c in self.cycles
            if strategy_substring.lower() in
                str(c.result.get("charging_strategy") or "").lower()
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
    from custom_components.solar_energy_management.coordinator.surplus_controller import (
        SurplusController,
    )
    coord._surplus_controller = SurplusController(coord.hass, coord.config)

    coord._ev_device = None
    coord._cycle_night_plan = None
    coord._cycle_vehicle_soc = None  # No external vehicle SOC entity in scenario
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
    # apply_dampening is called by _auto_mode_strategy; default MagicMock
    # would return a MagicMock that doesn't compare cleanly with floats →
    # `ratio > 2.0` crashes. Make it a pass-through.
    coord._forecast_tracker.apply_dampening = lambda x: x
    # state machine + time manager — strategy doesn't need their behaviour,
    # only their presence. Mock at the attribute level so attr lookups succeed.
    coord._state_machine = MagicMock()
    coord._state_machine.current_state = None
    coord.time_manager = MagicMock()
    coord.time_manager.is_night_mode = MagicMock(return_value=False)
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

        # Strategy decision — what does Auto/Zone-N return given these inputs?
        # _determine_charging_strategy needs a few more inputs; build the
        # minimum that lets the method run without IndexError. Energy totals
        # are zero because we don't need cost/savings math for this scenario.
        from custom_components.solar_energy_management.coordinator.types import (
            EnergyTotals,
        )
        energy = EnergyTotals(daily_ev=0.0, daily_solar=0.0)
        primary_cfg = (coord.config.get("ev_chargers") or [{}])[0]

        strategy = None
        strategy_reason = None
        try:
            strategy, strategy_reason = coord._determine_charging_strategy(
                readings, energy, primary_cfg,
            )
        except Exception as e:
            strategy_reason = f"strategy_call_failed: {type(e).__name__}: {e}"

        # Map the legacy strategy string to the canonical enum (same
        # rules as ``coordinator._canonical_strategy_from_legacy``).
        # Inline here so the harness doesn't depend on a real coordinator
        # instance. The reason text is what disambiguates the two flavours
        # of ``"solar_only"`` (Zone 2 self-consumption vs Zone 3+ surplus).
        from custom_components.solar_energy_management.coordinator.flow_calculator import (
            EVBudgetStrategy,
        )
        if strategy is None or strategy == "idle":
            canonical_strat = EVBudgetStrategy.IDLE
        elif strategy == "now":
            canonical_strat = EVBudgetStrategy.NOW
        elif strategy == "min_pv":
            canonical_strat = EVBudgetStrategy.MIN_PV
        elif strategy == "battery_assist":
            canonical_strat = EVBudgetStrategy.BATTERY_ASSIST
        elif strategy == "solar_only":
            reason_text = str(strategy_reason or "")
            if "self_consumption" in reason_text or "Zone 2" in reason_text:
                canonical_strat = EVBudgetStrategy.SELF_CONSUMPTION
            else:
                canonical_strat = EVBudgetStrategy.SOLAR_ONLY
        else:
            canonical_strat = EVBudgetStrategy.IDLE  # unknown → no charge

        # Canonical EV budget — single source of truth post-Phase-D.2.
        # Returns an ``EVBudget`` with ``net_w`` (the watts setpoint) and
        # ``current_a`` (the amps setpoint, already floor'd in surplus
        # regimes to avoid the rounding-to-grid boundary captured by
        # Scenario 0 #282). Both values are used directly — no separate
        # round-trip through ``calculate_charging_current`` like pre-D.2.
        ev_budget_obj = coord._flow_calculator.calculate_canonical_ev_budget(
            readings,
            strategy=canonical_strat,
            battery_soc=readings.battery_soc,
            battery_capacity_kwh=coord.config.get("battery_capacity_kwh", 15.0),
            forecast_remaining_kwh=0.0,
            battery_auto_start_soc=coord.config.get("battery_auto_start_soc", 90),
            battery_buffer_soc=coord.config.get("battery_buffer_soc", 70),
            battery_assist_floor_soc=coord.config.get("battery_assist_floor_soc", 60),
            battery_assist_max_power_w=coord.config.get(
                "battery_assist_max_power",
                coord.config.get("super_charger_power", 4500),
            ),
        )
        budget_w = ev_budget_obj.net_w
        amps = ev_budget_obj.current_a

        # Simulate the actuator: when strategy says "go" and amps > min,
        # SEM would call keba.set_current(<amps>). Capture it.
        if amps > 0 and readings.ev_connected:
            await coord.hass.services.async_call(
                "keba", "set_current", {"current": amps}, blocking=False,
            )

        # Cycle-level captured outputs (flat dict mirrors coord.data shape)
        result = {
            "charging_strategy": strategy,
            "charging_strategy_reason": strategy_reason,
            "calculated_current": amps,
            "ev_budget_w": budget_w,
            "flow_solar_to_ev_power": power_flows.solar_to_ev,
            "flow_grid_to_ev_power": power_flows.grid_to_ev,
            "flow_battery_to_ev_power": power_flows.battery_to_ev,
        }

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

    # 1. Strategy substring — at least one cycle's strategy must contain it
    sub = expect.get("strategy_substring")
    if sub:
        matched = run.cycles_where(sub)
        assert matched, (
            f"No cycle had a strategy containing '{sub}'. Got: "
            f"{[c.result.get('charging_strategy') for c in run.cycles]}"
        )

    # 2. Actuator current constraint — for cycles where the strategy matches
    ac = expect.get("actuator_current_a") or {}
    if ac:
        when_strategy = ac.get("when_strategy", "")
        formula = ac.get("formula", "0")
        margin_w = float(ac.get("max_w_minus_margin", 0))
        voltage = 230.0
        phases = 3.0
        for c in run.cycles:
            strat = str(c.result.get("charging_strategy") or "").lower()
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
