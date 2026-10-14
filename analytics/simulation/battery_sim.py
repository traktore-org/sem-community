"""(#1083) Replay one recorded day through SEM's real battery decisions.

Each hour builds the ``BatteryView`` SEM would have seen, calls the real
``decide_battery(view)`` and lets the hour's energy follow the decision.
Solar, the house and the car stay as recorded (v1 limit); the battery
and the grid are what change. Both the recorded and the simulated hours
are priced with the same prices and SEM's own cost rule (``balance``).

This module imports no Home Assistant itself and needs no hass. The SEM
modules it drives are the real ones.

What an hour cannot tell SEM is filled with a default and named in
``DayResult.indicative_reasons`` (``DEFAULTS_TAKEN``). A day is
``indicative`` when an hour is missing, a price or SOC hour was not
recorded, or the day carries the ``gap`` tag.

The night plan: SEM's scheduler is evaluated once per day, standing for
its evening run before the day — with the day's own forecast (that run's
"tomorrow"), the day's house kWh and the day's first SOC. Prices as the
coordinator reads them (``scheduler_rates``): off-peak = mean of the
cheapest 4 hours in the 12 after the trigger hour, peak = mean of the
07:00–20:00 hours, current = the trigger hour's price — this day's hours
stand in for the evening before. The night ledger covers 00:00 to sunrise
of the day; ``pack_night`` places the scheduler's deficit as SEM's
``battery`` demand, and the real ``plan_gate`` answers each night hour.

Where the pack ends the day counts. ``stored_energy_value`` = (simulated
end kWh − recorded end SOC × the new capacity) × √round-trip (what those
cell kWh give back at the plug) × the day's mean import rate. It is taken
off the simulated cost in ``delta``, so emptying a pack the recorded day
kept full is not a saving.

Hourly means: prices flat inside each hour are reproduced exactly;
15-minute prices and 15-minute peaks inside an hour are not seen, and
``kwh_over_limit`` is per hour.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date as _date, datetime, timedelta
from typing import Any, Dict, List, Mapping, Optional, Union

from ...consts.battery_modes import reserve_soc_of
from ...coordinator.battery_charge_scheduler import (
    BatteryChargeScheduler,
    SchedulerConfig,
)
from ...coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
    BatteryRuntime,
    BatteryView,
    FleetContext,
)
from ...coordinator.decide_battery import decide_battery
from ...coordinator.energy_plan_actuation import plan_gate
from ...coordinator.energy_planner import (
    Demand,
    LedgerSlot,
    build_night_ledger,
    pack_night,
)
from ...coordinator.peak_guard import clamp_import_command, slot_allowed_import_w
from .balance import balance_hour, cost_hour, one_way, summarise_day
from .hourly_day import HOURS, HourlyDay

#: what SEM's import rate is when the config has none (consts/core.py)
DEFAULT_IMPORT_RATE = 0.3387
DEFAULT_EXPORT_RATE = 0.075
#: an hour with less solar than this is still night (kWh)
SUNRISE_KWH = 0.05
#: when no hour of the day makes solar
DEFAULT_SUNRISE = 6

#: Inputs an hour of statistics cannot give SEM — the default each takes.
DEFAULTS_TAKEN = (
    "plan gate: none in daytime (no live plan); at night the plan packed "
    "from this day's own hours",
    "arbitrage and forecast sell: none (never sells to the grid)",
    "forecast spending: off",
    "battery permissions: none set (the install's legacy rules)",
    "export guard: off",
    "car plugged in only in hours it drew energy",
    "no grid-funded loads, no morning window, no battery boost",
    "every sink open (no house hold)",
    "night plan made once per day from that day's own forecast, house use "
    "and first SOC",
    "solar, house and car as recorded",
    "the car's mode does not offer the pack (ev_wants_pack off)",
    "forecast taken as recorded: no correction factor, not stale",
    "stored energy at the day's end valued at the day's mean import rate",
)

#: the coordinator's charge window and daytime hours (coordinator.py,
#: tariff_provider.get_charge_window_rate / get_next_daytime_rate)
CHARGE_WINDOW_H = 4
WINDOW_WITHIN_H = 12
DAYTIME = (7, 20)

Rate = Union[float, str]


@dataclass(frozen=True)
class SimParams:
    """The what-if. Rates are a flat number or ``"recorded"``."""

    capacity_kwh: float
    reserve_pct: float
    peak_limit_kw: Optional[float] = None
    import_rate: Rate = "recorded"
    export_rate: Rate = "recorded"
    max_charge_w: float = 5000.0
    max_discharge_w: float = 5000.0
    roundtrip: float = 0.92

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any], **changes) -> "SimParams":
        """The install as configured, with ``changes`` on top."""
        peak = cfg.get("target_peak_limit")
        base = cls(
            capacity_kwh=float(cfg.get("battery_capacity_kwh") or 10.0),
            reserve_pct=reserve_soc_of(cfg),
            peak_limit_kw=float(peak) if peak else None,
            max_charge_w=float(cfg.get("battery_max_charge_power_w")
                               or cfg.get("battery_max_charge_power")
                               or 5000.0),
            max_discharge_w=float(cfg.get("battery_max_discharge_power")
                                  or 5000.0),
            roundtrip=float(cfg.get("battery_roundtrip_efficiency") or 0.92),
        )
        return replace(base, **changes)


@dataclass
class SimState:
    """What carries from one simulated hour to the next."""

    soc_kwh: float
    #: SEM's sign: + charge, − discharge (W, the hour's mean)
    last_w: float = 0.0
    charge_w: float = 0.0
    discharge_w: float = 0.0
    grid_import_w: float = 0.0
    grid_export_w: float = 0.0
    #: forced ops SEM started and has not stopped (decide_battery #1066).
    #: False at the start: nothing was started.
    forced_charge: Optional[bool] = False
    forced_discharge: Optional[bool] = False
    scheduler_decision: Any = None
    plan: Optional[dict] = None


@dataclass(frozen=True)
class SimHour:
    """One hour's inputs, prices already resolved."""

    index: int
    start: datetime
    solar: float
    home: float
    ev: float
    import_rate: float
    export_rate: float


@dataclass
class DayResult:
    date: str
    tags: List[str]
    actual: Dict[str, float]
    simulated: Dict[str, float]
    actual_cost: float
    simulated_cost: float
    delta: float
    kwh_over_limit: float
    actual_kwh_over_limit: float
    start_soc_pct: Optional[float]
    end_soc_pct: Optional[float]
    indicative: bool
    indicative_reasons: List[str]
    stored_energy_value: float = 0.0
    hours: List[dict] = field(default_factory=list)
    modelled: bool = True

    def as_dict(self) -> dict:
        return {
            "date": self.date, "tags": list(self.tags),
            "modelled": True,
            "actual": dict(self.actual), "simulated": dict(self.simulated),
            "actual_cost": self.actual_cost,
            "simulated_cost": self.simulated_cost, "delta": self.delta,
            "kwh_over_limit": self.kwh_over_limit,
            "actual_kwh_over_limit": self.actual_kwh_over_limit,
            "start_soc_pct": self.start_soc_pct,
            "end_soc_pct": self.end_soc_pct,
            "stored_energy_value": self.stored_energy_value,
            "indicative": self.indicative,
            "indicative_reasons": list(self.indicative_reasons),
            "hours": [dict(h) for h in self.hours],
        }


def sim_config(cfg: Mapping[str, Any], params: SimParams) -> Dict[str, Any]:
    """The install's config with the what-if laid over it."""
    out = dict(cfg)
    old_cap = float(cfg.get("battery_capacity_kwh") or 0.0)
    usable = cfg.get("battery_usable_capacity_kwh")
    # Usable capacity keeps its share of the nameplate on a new size.
    share = (float(usable) / old_cap) if usable and old_cap > 0 else 0.95
    out.update({
        "battery_capacity_kwh": float(params.capacity_kwh),
        "battery_usable_capacity_kwh": float(params.capacity_kwh) * share,
        "battery_reserve_soc": float(params.reserve_pct),
        "battery_max_charge_power_w": float(params.max_charge_w),
        "battery_max_charge_power": float(params.max_charge_w),
        "battery_max_discharge_power": float(params.max_discharge_w),
        "battery_roundtrip_efficiency": float(params.roundtrip),
    })
    if params.peak_limit_kw:
        out["target_peak_limit"] = float(params.peak_limit_kw)
    else:
        out.pop("target_peak_limit", None)
    return out


def _allowed_w(params: SimParams) -> Optional[float]:
    """The hour's import allowance: the slot rule over one hour."""
    if not params.peak_limit_kw:
        return None
    return slot_allowed_import_w(float(params.peak_limit_kw), 0.0, 0.0,
                                 slot_s=3600.0)


def synth_view(hour: SimHour, state: SimState, params: SimParams,
               cfg: Mapping[str, Any]) -> BatteryView:
    """The ``BatteryView`` SEM would have built for this hour.

    ``cfg`` is already the what-if config (``sim_config``)."""
    cap = float(params.capacity_kwh)
    soc_pct = 100.0 * state.soc_kwh / cap if cap > 0 else 0.0
    home_w = hour.home * 1000.0
    ev_w = hour.ev * 1000.0
    ev_charging = hour.ev > 0.0
    fleet = FleetContext(
        solar_w=hour.solar * 1000.0,
        home_w=home_w,
        battery_charge_w=state.charge_w,
        battery_discharge_w=state.discharge_w,
        battery_soc=soc_pct,
        battery_soc_known=True,
        grid_import_w=state.grid_import_w,
        grid_export_w=state.grid_export_w,
        battery_count=1,
        sink_verdicts={},
        export_command=None,
        export_guard_enabled=False,
        battery_capacity_kwh=cap,
        buffer_soc=float(cfg.get("battery_buffer_soc", 70)),
        battery_assist_min_surplus_w=float(
            cfg.get("battery_assist_min_surplus", 1200)),
        peak_slot_allowed_w=_allowed_w(params),
        # The car is offered first; a forced charge takes what is left.
        peak_committed_w=ev_w,
        # A replay reads recorded hours: no input is dark, no residual clamped.
        inputs_degraded=False,
        dark_inputs=(),
        home_residual_clamped_w=0.0,
    )
    runtime = BatteryRuntime(
        battery_id="sim", last_known_soc=soc_pct, last_known_w=state.last_w,
        capacity_kwh=cap, available=True,
    )
    gate = None
    if state.plan is not None:
        gate = plan_gate(state.plan, "battery", hour.start)
    return BatteryView(
        runtime=runtime,
        config=cfg,
        fleet=fleet,
        charging_state="charging_active" if ev_charging else "idle",
        ev_charging=ev_charging,
        ev_connected=ev_charging,
        ev_wants_pack=False,
        home_consumption_w=home_w,
        scheduler_decision=state.scheduler_decision,
        plan_gate=gate,
        arbitrage_sell=None,
        forecast_sell=None,
        forecast_spending_enabled=False,
        battery_permissions=None,
        sink_verdicts={},
        sem_forced_charge=state.forced_charge,
        sem_forced_discharge=state.forced_discharge,
    )


def _sunrise(day: HourlyDay) -> int:
    return next((h for h in range(HOURS) if day.solar[h] >= SUNRISE_KWH),
                DEFAULT_SUNRISE)


def scheduler_rates(hours: List[SimHour], trigger_hour: int = 21):
    """``(off_peak, peak, current)`` as the coordinator feeds the scheduler.

    off_peak: mean of the cheapest ``CHARGE_WINDOW_H`` hours in the
    ``WINDOW_WITHIN_H`` hours from the trigger hour (wrapping past midnight
    into this day's early hours). peak: mean of the ``DAYTIME`` hours.
    current: the trigger hour's price."""
    t = int(trigger_hour) % HOURS
    window = [hours[(t + i) % HOURS].import_rate for i in range(WINDOW_WITHIN_H)]
    cheapest = sorted(window)[:CHARGE_WINDOW_H]
    day = [h.import_rate for h in hours if DAYTIME[0] <= h.index < DAYTIME[1]]
    return (sum(cheapest) / len(cheapest), sum(day) / len(day),
            hours[t].import_rate)


def plan_night(day: HourlyDay, hours: List[SimHour], soc_kwh: float,
               params: SimParams, cfg: Mapping[str, Any]):
    """SEM's scheduler and night packer for the night the day starts with.

    Returns ``(scheduler_decision, plan_dict)``, both None when the install
    has night charging off."""
    if not cfg.get("battery_charge_scheduler_enabled", False):
        return None, None
    sched_cfg = SchedulerConfig.from_config(dict(cfg))
    sched = BatteryChargeScheduler(None, sched_cfg)
    off_peak, peak, current = scheduler_rates(hours, sched_cfg.trigger_hour)
    cap = float(params.capacity_kwh)
    decision = sched.evaluate(
        current_soc=100.0 * soc_kwh / cap if cap > 0 else 0.0,
        forecast_tomorrow_kwh=float(day.forecast_kwh or 0.0),
        expected_consumption_kwh=day.total("home"),
        off_peak_rate=off_peak,
        peak_rate=peak,
        correction_factor=1.0,
        forecast_available=day.forecast_kwh is not None,
        forecast_age_hours=0.0,
        current_price=current,
    )
    sunrise = _sunrise(day)
    peak_w = float(params.peak_limit_kw or 0.0) * 1000.0
    floor_kwh = cap * float(params.reserve_pct) / 100.0
    slots = [LedgerSlot(start=h.start, end=h.start + timedelta(hours=1),
                        price=h.import_rate, home_w=h.home * 1000.0)
             for h in hours[:max(1, sunrise)]]
    ledger = build_night_ledger(
        slots, soc_kwh=soc_kwh, floor_kwh=floor_kwh,
        max_discharge_w=float(params.max_discharge_w), peak_limit_w=peak_w)
    demands = []
    deficit = float(getattr(decision, "deficit_kwh", 0.0) or 0.0)
    # The coordinator's own battery demand (coordinator.py, #638).
    if deficit > 0.1:
        demands.append(Demand(
            id="battery", kind="battery", energy_kwh=deficit,
            max_power_w=float(params.max_charge_w), source="grid"))
    packed = pack_night(demands, ledger, floor_kwh=floor_kwh,
                        max_discharge_w=float(params.max_discharge_w),
                        peak_limit_w=peak_w)
    plan = {
        "computed_at": hours[0].start.isoformat(),
        "demands": [{"id": r.demand_id, "status": r.status}
                    for r in packed.results],
        "slots": [{"start": s.start.isoformat(), "end": s.end.isoformat()}
                  for s in ledger],
        "blocks": [{"id": a.demand_id, "start": a.start.isoformat(),
                    "end": a.end.isoformat(), "power_w": a.power_w}
                   for a in packed.allocations],
    }
    return decision, plan


@dataclass
class _Flow:
    grid_import: float = 0.0
    grid_export: float = 0.0
    battery_charge: float = 0.0
    battery_discharge: float = 0.0


def _self_consume(hour: SimHour, soc: float, floor_kwh: float, cap: float,
                  eff: float, params: SimParams, limit_kwh: float) -> _Flow:
    """The pack covers the house and car and soaks up the surplus."""
    net = hour.solar - hour.home - hour.ev
    f = _Flow()
    if net >= 0:
        room_ac = max(0.0, cap - soc) / eff
        f.battery_charge = min(net, params.max_charge_w / 1000.0, room_ac)
        f.grid_export = net - f.battery_charge
    else:
        need = -net
        avail_ac = max(0.0, soc - floor_kwh) * eff
        f.battery_discharge = min(need, params.max_discharge_w / 1000.0,
                                  avail_ac, max(0.0, limit_kwh))
        f.grid_import = need - f.battery_discharge
    return f


def _dispatch(decision: BatteryDecision, hour: SimHour, soc: float,
              params: SimParams):
    """Let the hour's energy follow the decision.

    Returns ``(flow, note)``; ``note`` names an hour the model could not
    follow exactly."""
    cap = float(params.capacity_kwh)
    eff = one_way(params.roundtrip)
    reserve_kwh = cap * float(params.reserve_pct) / 100.0
    intent = decision.intent
    inf = float("inf")
    if intent in (BatteryIntent.NORMAL, BatteryIntent.OFF,
                  BatteryIntent.STOP_FORCE_CHARGE,
                  BatteryIntent.STOP_FORCE_DISCHARGE):
        return _self_consume(hour, soc, reserve_kwh, cap, eff, params, inf), None
    if intent is BatteryIntent.LIMIT_DISCHARGE:
        return _self_consume(hour, soc, reserve_kwh, cap, eff, params,
                             float(decision.discharge_limit_w) / 1000.0), None
    if intent is BatteryIntent.FORCE_CHARGE:
        target = float(decision.target_soc or 100.0)
        top_kwh = cap * min(100.0, target) / 100.0
        room_ac = max(0.0, top_kwh - soc) / eff
        want = min(float(decision.charge_power_w) / 1000.0,
                   params.max_charge_w / 1000.0, room_ac)
        surplus = max(0.0, hour.solar - hour.home - hour.ev)
        house_import = max(0.0, hour.home + hour.ev - hour.solar)
        from_sun = min(want, surplus)
        from_grid = want - from_sun
        allowed = _allowed_w(params)
        if allowed is not None and from_grid > 0:
            grid_w, _ = clamp_import_command(
                from_grid * 1000.0, allowed, house_import * 1000.0, 0.0)
            from_grid = grid_w / 1000.0
        f = _Flow(battery_charge=from_sun + from_grid,
                  grid_import=house_import + from_grid,
                  grid_export=surplus - from_sun)
        return f, None
    if intent is BatteryIntent.FORCE_DISCHARGE:
        floor_kwh = cap * max(float(params.reserve_pct),
                              float(decision.floor_soc or 0.0)) / 100.0
        dis = min(float(decision.discharge_power_w) / 1000.0,
                  params.max_discharge_w / 1000.0,
                  max(0.0, soc - floor_kwh) * eff)
        net = hour.solar - hour.home - hour.ev
        if net >= 0:
            return _Flow(battery_discharge=dis, grid_export=net + dis), None
        need = -net
        return _Flow(battery_discharge=dis,
                     grid_import=max(0.0, need - dis),
                     grid_export=max(0.0, dis - need)), None
    note = f"intent {getattr(intent, 'value', intent)} run as normal"
    return _self_consume(hour, soc, reserve_kwh, cap, eff, params, inf), note


def _rate(choice: Rate, recorded: Optional[float], flat: float):
    """``(rate, was_missing)`` for one hour."""
    if choice != "recorded":
        return float(choice), False
    if recorded is None:
        return float(flat), True
    return float(recorded), False


def _over(import_kwh: float, params: SimParams) -> float:
    if not params.peak_limit_kw:
        return 0.0
    return max(0.0, import_kwh - float(params.peak_limit_kw))


def simulate_day(day: HourlyDay, params: SimParams,
                 cfg: Mapping[str, Any]) -> DayResult:
    """Replay one day hour by hour through ``decide_battery``."""
    reasons: List[str] = list(DEFAULTS_TAKEN)
    marks: List[str] = []
    the_cfg = sim_config(cfg, params)
    flat_in = float(cfg.get("electricity_import_rate") or DEFAULT_IMPORT_RATE)
    flat_out = float(cfg.get("electricity_export_rate")
                     if cfg.get("electricity_export_rate") is not None
                     else DEFAULT_EXPORT_RATE)
    midnight = datetime.combine(_date.fromisoformat(day.date),
                                datetime.min.time())
    hours: List[SimHour] = []
    price_missing = False
    for h in range(HOURS):
        rin, miss_in = _rate(params.import_rate, day.import_rate[h], flat_in)
        rout, miss_out = _rate(params.export_rate, day.export_rate[h], flat_out)
        price_missing = price_missing or miss_in or miss_out
        hours.append(SimHour(index=h, start=midnight + timedelta(hours=h),
                             solar=day.solar[h], home=day.home[h], ev=day.ev[h],
                             import_rate=rin, export_rate=rout))
    if price_missing:
        marks.append("a price hour was not recorded — the flat rate stands in")
    if any(s is None for s in day.soc_pct):
        marks.append("a SOC hour was not recorded")
    if day.missing_hours:
        marks.append(f"{len(day.missing_hours)} hour(s) missing in the "
                     "recorder — counted as 0")
    marks.extend(day.notes)
    if day.gap:
        marks.append("the day carries the gap tag")

    cap = float(params.capacity_kwh)
    eff = one_way(params.roundtrip)
    reserve_kwh = cap * float(params.reserve_pct) / 100.0
    first = day.first_soc()
    if first is None:
        soc = reserve_kwh
        marks.append("no SOC recorded — the pack starts at its reserve")
    else:
        soc = cap * float(first) / 100.0
        if soc < reserve_kwh or soc > cap:
            soc = min(cap, max(reserve_kwh, soc))
            marks.append("the recorded start SOC is outside the new "
                         "[reserve, capacity] — the pack starts at the edge")
    start_soc = soc
    state = SimState(soc_kwh=soc)
    sunrise = _sunrise(day)
    sched, plan = plan_night(day, hours, soc, params, the_cfg)

    actual_rows: List[dict] = []
    sim_rows: List[dict] = []
    for hour in hours:
        h = hour.index
        night = h < sunrise
        state.scheduler_decision = sched if night else None
        state.plan = plan if night else None
        view = synth_view(hour, state, params, the_cfg)
        decision = decide_battery(view)
        flow, note = _dispatch(decision, hour, state.soc_kwh, params)
        if note:
            marks.append(f"{hour.start:%H}:00 {note}")
        soc_start = state.soc_kwh
        soc_end = (soc_start + flow.battery_charge * eff
                   - flow.battery_discharge / eff)
        soc_end = min(cap, max(0.0, soc_end))
        bal = balance_hour(
            solar=hour.solar, grid_import=flow.grid_import,
            grid_export=flow.grid_export, battery_charge=flow.battery_charge,
            battery_discharge=flow.battery_discharge, ev=hour.ev,
            roundtrip=params.roundtrip)
        cost = cost_hour(flow.grid_import, flow.grid_export, hour.import_rate,
                         export_rate=hour.export_rate, home_kwh=hour.home,
                         ev_kwh=hour.ev, solar_kwh=hour.solar)
        sim_rows.append({
            "hour": h, "intent": decision.intent.value,
            "reason": decision.reason,
            "soc_start_pct": round(100.0 * soc_start / cap, 6) if cap else None,
            "soc_end_pct": round(100.0 * soc_end / cap, 6) if cap else None,
            "solar": hour.solar, "home": bal.home_kwh, "ev": hour.ev,
            "grid_import": flow.grid_import, "grid_export": flow.grid_export,
            "battery_charge": flow.battery_charge,
            "battery_discharge": flow.battery_discharge,
            "loss_kwh": bal.loss_kwh,
            "over_limit_kwh": _over(flow.grid_import, params),
            "import_rate": hour.import_rate, "export_rate": hour.export_rate,
            "indicative": note or (
                "missing in the recorder" if h in day.missing_hours else None),
            **cost.as_dict(),
        })
        rec = day.flows(h)
        rec_cost = cost_hour(rec["grid_import"], rec["grid_export"],
                             hour.import_rate,
                             export_rate=hour.export_rate,
                             home_kwh=rec["home"], ev_kwh=rec["ev"],
                             solar_kwh=rec["solar"])
        actual_rows.append({**rec, "over_limit_kwh": _over(rec["grid_import"], params),
                            **rec_cost.as_dict()})
        # Carry the hour into the next one.
        state.soc_kwh = soc_end
        state.charge_w = flow.battery_charge * 1000.0
        state.discharge_w = flow.battery_discharge * 1000.0
        state.last_w = state.charge_w - state.discharge_w
        state.grid_import_w = flow.grid_import * 1000.0
        state.grid_export_w = flow.grid_export * 1000.0
        intent = decision.intent
        if intent is BatteryIntent.FORCE_CHARGE:
            state.forced_charge = True
        elif intent is BatteryIntent.STOP_FORCE_CHARGE:
            state.forced_charge = False
        elif intent is BatteryIntent.FORCE_DISCHARGE:
            state.forced_discharge = True
        elif intent is BatteryIntent.STOP_FORCE_DISCHARGE:
            state.forced_discharge = False

    actual = summarise_day(actual_rows)
    simulated = summarise_day(sim_rows)
    actual_cost = round(actual["net_cost"], 4)
    simulated_cost = round(simulated["net_cost"], 4)
    # The pack's end of day against the recorded end, at the new size.
    last = next((x for x in reversed(day.soc_pct) if x is not None), None)
    stored_value = 0.0
    if last is not None:
        mean_rate = sum(h.import_rate for h in hours) / len(hours)
        diff_kwh = state.soc_kwh - cap * float(last) / 100.0
        stored_value = diff_kwh * eff * mean_rate
    return DayResult(
        date=day.date, tags=list(day.tags),
        actual=actual, simulated=simulated,
        actual_cost=actual_cost, simulated_cost=simulated_cost,
        delta=round(simulated_cost - stored_value - actual_cost, 4),
        stored_energy_value=round(stored_value, 4),
        kwh_over_limit=round(simulated["over_limit_kwh"], 6),
        actual_kwh_over_limit=round(actual["over_limit_kwh"], 6),
        start_soc_pct=round(100.0 * start_soc / cap, 3) if cap else None,
        end_soc_pct=round(100.0 * state.soc_kwh / cap, 3) if cap else None,
        indicative=bool(marks),
        indicative_reasons=marks + reasons,
        hours=sim_rows,
    )
