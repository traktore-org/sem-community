# Architecture

This document covers the internal architecture of Solar Energy Management (SEM) for developers and contributors.

> **v2.0 — one gate** (see [CHANGELOG](../CHANGELOG.md) `[2.0.0]` and
> [ENERGY_PLANNER.md](ENERGY_PLANNER.md)). The structural change of
> this release is that scheduled energy use has **one decision-maker**:
> - **The plan owns WHEN, the reactive layer owns WHETHER, the user owns MAY.**
>   The EV's private cheap-window pick and the battery scheduler's own window
>   pick are deleted; both now read the joint plan's blocks. An AST ratchet
>   (`tests/test_638_one_selector.py`) keeps `find_cheapest_hours` to its one
>   home in `tariff/tariff_provider.py`.
> - **`coordinator/energy_plan_actuation.py`** is the gate: one trust rule
>   (stamp freshness) feeding per-demand verdicts for EV, loads, comfort,
>   battery and arbitrage.
> - **Fail-open direction is per family and deliberate** — EV uncovered
>   charges at its floor, battery uncovered does not force-charge, and every
>   verdict change is logged once (`#638 coverage:`) and rendered as a
>   translated reason on the card.
> - **The plan is measured against reality** (#755): a per-demand outcome
>   recorder writes what each demand actually did, split inside/outside the
>   planned block, with a `measured` flag that refuses to let an estimate be
>   recorded as a measurement.
> - **The energy ledger closes** (#767–#776): every kWh SEM moves has a row,
>   including exported battery energy.

> **2.0 additions** (see [CHANGELOG](../CHANGELOG.md) `[2.0.0]`) — the 2.0
> line is about making existing behaviour *believable* rather than adding
> capability: the recorder footprint fell from 25 % to 6.1 % of HA's state
> rows, every numeric setting is declared once in `consts/bounds.py`, one
> plan gate owns WHEN, hardware detection matches registry `unique_id`s
> rather than entity names, and the stop-war ceasefire stops SEM fighting a
> charger it cannot win against. Repairs now carry a next step. The
> architecture below is unchanged in shape.
>
> **v1.7.3 additions** (see [CHANGELOG](../CHANGELOG.md) `[1.7.3]`):
> - **EV charger state reconciler** — `coordinator/charger_reconciler.py` is now the
>   sole actuation path. A pure desired-vs-observed decision table (DesiredState
>   OFF/IDLE/CHARGE → ActionKind) drives an observe/apply layer that issues the
>   minimum commands to converge, then leaves the charger alone (idempotent idle,
>   heartbeat re-writes, failsafe armed once, enable-switch reconciliation + backoff
>   #392/#536). It replaces the legacy per-cycle imperative `actuate()` *body* (the wrapper function remains as a thin delegation).
> - **Pure battery decision** — `coordinator/decide_battery.py`
>   (`decide_battery(view) → BatteryDecision`, precedence FORCE_CHARGE →
>   STOP_FORCE_CHARGE → LIMIT_DISCHARGE → NORMAL). The LIMIT_DISCHARGE clamp now
>   fires on a unified **Solar Gate**: `ev_charging AND max(0, solar−home) <
>   battery_assist_min_surplus_w` → clamp discharge to `home / battery_count`. This
>   replaces the old night-only / `hold_solar` triggers (#537).
> - **Solar Gate budget path** — `decide.battery_assist_budget_w` +
>   `flow_calculator.calculate_canonical_ev_budget` gate battery-assist on real solar
>   surplus; config key `battery_assist_min_surplus` (default 1200 W) is plumbed via
>   `FleetContext.battery_assist_min_surplus_w`.
> - Hysteresis stability (`coordinator/charge_stability.py`) sits between `decide()`
>   and the reconciler; per-battery views/decisions feed the canonical EV budget.

---

## Architectural principle — SEM is not an integration

**SEM is an energy-management layer that sits on top of Home Assistant integrations. It is NOT itself a device integration.**

What SEM does | What SEM does NOT do
---|---
Read sensor entities from `hass.states` | Talk Modbus / REST / cloud APIs to hardware
Write to `number` / `switch` / `select` / `climate` entities | Implement device protocols (KEBA, Nibe, Huawei, …)
Call services like `switch.turn_on`, `number.set_value`, `climate.set_temperature` | Bundle protocol libraries (pymodbus, paho-mqtt, vendor SDKs)
Express its logic in terms of HA entities | Replace HA's `nibe`, `keba`, `huawei_solar`, `wallbox`, etc. integrations
Add OptionsFlow fields like `heat_pump_relay1_entity` (entity pickers) | Add OptionsFlow fields like `nibe_modbus_host` / `keba_ip`

**Why this matters:** some HEMS tools ship built-in device drivers for specific brands (e.g. a Modbus template that talks directly to a Nibe S-Series heat pump). SEM intentionally takes a different shape — it stays in HA's entity-and-services world. The user runs HA's `nibe` / `modbus` / `keba` integration (which owns the protocol), then plugs the resulting entities into SEM via entity pickers.

**Practical consequence for Nibe-with-Modbus-SG-Ready:**
1. User installs HA's `nibe` integration → it exposes the heat pump's Modbus registers as entities.
2. User creates two HA `template switch` entities that write to the SG-Ready Modbus register bits when toggled.
3. User configures those template switches in SEM as `heat_pump_relay1_entity` / `heat_pump_relay2_entity`.
4. SEM never knows it's Modbus. It just sees two switches. Same code path as ESP relays, Shellies, or any other SG-Ready wiring.

**What this rules out** (each is a legitimate idea — just not for SEM):
- A "native Modbus SG-Ready path for Nibe S-Series" inside `HeatPumpController`. Belongs in HA's `nibe` integration or as a custom integration alongside SEM.
- KEBA / Wallbox / Huawei brand-specific drivers inside SEM. Belongs in HA's brand integrations.
- A SEM "cloud bridge" for any specific vendor. Same answer.

---

## v1.7.0 — Per-device primary pattern

Every multi-device data point in SEM flows through one shape:
**`Dict[str, X]` is the source of truth; fleet aggregates are
`@property` views**. The pattern applies uniformly to chargers,
inverters, batteries, and PV strings.

```python
class PowerReadings:
    # PRIMARY per-device dicts
    ev_power_per_charger: Dict[str, float]    # multi-charger
    inverters: Dict[str, InverterPower]       # multi-inverter
    batteries: Dict[str, BatteryPower]        # multi-battery
    solar_power_per_string: Dict[str, float]  # per-PV-string

    # COMPUTED fleet views (cannot drift from the dicts)
    @property
    def fleet_ev_w(self) -> FleetEvPower: ...
    @property
    def fleet_solar_w(self) -> float: ...
    @property
    def fleet_battery_w(self) -> float: ...

class SEMCoordinator:
    _per_charger: Dict[str, ChargerRuntime]   # consolidates ~8 legacy dicts
    _per_inverter: Dict[str, InverterRuntime] # multi-inverter installs
    _per_battery: Dict[str, BatteryRuntime]   # multi-battery installs
    _charger_adapters: Dict[str, ChargerAdapter]
    _battery_adapter: BatteryControlAdapter
```

### Decide → actuate → adapter (EV side)

```
PowerReadings + config
       │
       ▼
build_charger_view(charger_id) ──► ChargerView (frozen, pure input)
                                          │
                                          ▼
                                   decide(view)         ← pure function
                                          │
                                          ▼
                                  ChargerDecision (frozen, pure output)
                                          │
                                          ▼
                             actuate(decision, adapter, power, reconciler)
                                          │
                                          ▼
                          reconciler.reconcile_and_apply() → adapter.command_X()  ← brand-aware
                                          │
                                          ▼
                                    HA service call
```

- **`decide(view)`** is pure. No `self`, no HA calls, no clock reads.
  Each of the 5 charge modes (`off`, `solar_only`, `min_plus_solar`,
  `always_max`, `solar_plus_cheap`) has its own `ModeStrategy` class.
- **`ChargerAdapter`** encapsulates every brand-specific quirk.
  `KebaAdapter` knows about the 6 A IEC 61851 minimum, that
  `set_current(0)` is silently rejected (requires `keba.disable`),
  self-resume detection, and the ~5 s `charging_state` sensor lag.
  `GenericAdapter` covers brands whose firmware handles 0 A as stop
  (Wallbox, Easee, go-eCharger, OCPP).
- **`actuate(decision, adapter, power, reconciler)`** is a thin delegation:
  it hands the `ChargerDecision` to the **`ChargerReconciler`**, which owns
  convergence (desired-vs-observed) and is the sole actuation path (v1.7.3).
  The reconciler dispatches by intent — one adapter call per `ChargerIntent` —
  and the self-resume guard (#315/#346/#353) is one `adapter.is_self_charging()`
  check before applying the new intent.

### Decide → actuate → adapter (battery side)

Symmetric to the EV side. Batteries have observed-only and commanded
axes — `BatteryControlAdapter` unifies both:

```python
class BatteryControlAdapter(ABC):
    @abstractmethod async def command_normal(self): ...
    @abstractmethod async def command_limit_discharge(self, watts: float): ...
    @abstractmethod async def command_force_charge(
        self, target_soc, charge_power_w, duration_min): ...
    @abstractmethod async def command_stop_force_charge(self): ...
```

Three brand implementations: `HuaweiBatteryAdapter` (wraps the
existing `huawei_solar.forcible_charge_soc` service for force
charge + `number.set_value` for discharge limiting),
`GoodWeBatteryAdapter` (Eco Charge mode toggle), and
`GenericBatteryAdapter` (switch + number target).

`decide_battery(view) → BatteryDecision` produces one of four
intents (`NORMAL`, `LIMIT_DISCHARGE`, `FORCE_CHARGE`,
`STOP_FORCE_CHARGE`). The pure `BatteryChargeScheduler.evaluate()`
that pre-v1.7.0 lived alongside is preserved verbatim — it
produces the `SchedulerDecision` that feeds `BatteryView.scheduler_decision`.

### Compute intent → reconcile (load side)

Surplus loads (switches, climate, heat pump, hot water) follow the **same
decide → actuate shape**, expressed as three clean layers. This is the arc
every load feature docks onto — get the layer right and observer mode, the
tests, and the anti-cycle all come for free.

```
   sensors + config
         │
   ┌─────▼──────────────────────────────────┐
   │ 1. MANAGEMENT   compute_load_intent()   │  pure — decide policy for ONE device
   │    per device → LoadIntent(on, power_w, │  (never touches hardware or the clock)
   │                 source, reason)         │
   └─────┬──────────────────────────────────┘
   ┌─────▼──────────────────────────────────┐
   │ 2. DECISION     _desired_intents()      │  pure — the whole-set priority walk:
   │    surplus accounting, reclaim handoff, │  surplus/reclaim/peak-shed → one intent
   │    peak-shed set → {device_id: intent}  │  per device (no hardware, no clock)
   └─────┬──────────────────────────────────┘
   ┌─────▼──────────────────────────────────┐
   │ 3. EXECUTION    reconcile_load(intent)  │  THE ONLY place a load is actuated.
   │    activate / deactivate / adjust_power │  Anti-cycle (min_on/min_off) lives here.
   │    ── observer? → LOG "WOULD …", return │  ← the single trigger, cut in one branch
   └─────────────────────────────────────────┘
```

- **Layers 1 + 2 never touch hardware** — they read the live sensors and emit
  intents. On HA-TEST (shared real hardware, observer mode) they run *for real*
  against live data.
- **Layer 3 is the single seam.** `reconcile_load(device, intent, observer=)`
  is the *only* function that flips a load. Observer mode is one branch inside
  it: log the command it would send (`WOULD ACTIVATE …`), actuate nothing. There
  is **no separate `observe_only` path** — a clean layer cut makes observation a
  one-flag branch, so HA-TEST gets the full real decision trace with zero
  hardware risk. (The existence of a parallel "observe" implementation was the
  smell that the layers weren't cut; removed in the desired-state arc.)
- `compute_load_intent`'s `source` (`solar` / `tier1_battery` / `tier2_battery`
  / `cheap_grid` / `None`) is the whole vocabulary — it drives the anti-cycle
  markers (`_batt_overnight_forced`, `_offpeak_forced`) and the "not-SEM-driven"
  guard (`source is None` ⇒ never re-tune a load SEM isn't driving).

**Where the next extension docks** — attach at the layer that matches the change,
never spread across them:

| You are adding… | Dock at | Do NOT |
|---|---|---|
| a new reason a load turns on/off (deadline, price, comfort) | **layer 1** — a new precedence branch + `source` in `compute_load_intent` | add an `if` next to an `activate()` call |
| a new whole-set rule (a new shed policy, a fairness split) | **layer 2** — `_desired_intents` walk | mutate device state mid-walk |
| a new actuation target (a new device kind, a dimmer) | **layer 3** — one new branch in `reconcile_load` | add a second actuation site |
| observer/dry-run behaviour for the above | nothing — it's already free at the seam | re-add a parallel read-only path |

Rule of thumb: **if a change needs to touch both a decision and an `activate()`
call, it's docking at the wrong layer.** Decisions produce intents; only
`reconcile_load` acts. This is what keeps the "gate blocks activation but doesn't
stop a running device" bug class (BUG_CLASSES #17) structurally impossible — the
stop path *is* the intent, not a separate branch someone can forget.

### Invariant suite — the safety net

`tests/test_step8_invariants.py` pins 233 architectural contracts
parametrised across the operating envelope (mode × solar × SOC ×
home × is_night × num_chargers). Each invariant guarantees one
property the architecture is supposed to enforce by construction.
A breaking change fails CI immediately; no need to wait for HA-TEST.

`tests/test_surplus_charging_scenarios.py` adds 93 behavioural
scenarios that walk specific operating points (e.g. dawn → noon
→ dusk for solar_only mode) and verify the right intent comes out
at each step.

This replaces the pre-v1.7.0 verification cycle, which depended on
deploying to HA-TEST and watching log lines for the rare combination
that triggered a bug. The deterministic CI scenarios run in under a
second.

### Delivered during the v1.7.x line

- Per-inverter / per-battery dashboard sensors + flow attribution (#623,
  v1.7.2–v1.7.5) and the `sensor_reader` per-unit population
- `BatteryProtectionMixin` / `BatteryChargeAdapter` shells deleted (#624);
  `BatteryControlAdapter` is the only battery control surface
- Unit-safe, fail-closed battery power writes centralized in
  `power_control.py` (#702)

Still deferred: per-string-to-destination attribution (#312).

---

## Coordinator Module Structure

```
coordinator/
├── coordinator.py          — SEMCoordinator (DataUpdateCoordinator, 10s loop)
├── sensor_reader.py        — SensorReader (reads HA sensors → PowerReadings)
├── energy_calculator.py    — EnergyCalculator (power → energy integration)
├── flow_calculator.py      — FlowCalculator (power/energy flow distribution)
├── charger_types.py        — Frozen per-device types (ChargerPower, ChargerDecision,
│                             InverterRuntime, BatteryRuntime, BatteryDecision, …)
├── charger_adapters/       — Per-brand EV-charger control surface (KEBA, Generic)
├── battery_adapters/       — Per-brand battery control surface (Huawei, GoodWe, Generic)
├── decide.py               — Pure decide(view) → ChargerDecision (5 ModeStrategy classes)
├── decide_battery.py       — Pure decide_battery(view) → BatteryDecision
├── actuate.py              — Thin delegation of ChargerDecision to ChargerReconciler
├── actuate_battery.py      — Intent dispatch onto BatteryControlAdapter
├── power_control.py        — Unit-safe battery power setpoint writes (#702):
│                             fail-closed validation + W↔kW conversion; rejects
│                             current/percent/unitless-unknown/out-of-range controls
├── build_view.py           — Builds ChargerView from PowerReadings + config
├── charge_stability.py     — Stability filter between decide() and actuate():
│                             median smoothing, enable/disable delays, start-kick
│                             ladder, full-car backoff (#610), restart-safe timers
├── charger_reconciler.py   — Desired-vs-observed charger convergence (#392);
│                             minimum commands, enable-switch backoff
├── device_reconciler.py    — Observe-only reconcile for generic surplus devices
├── per_charger_context.py  — PerChargerContext/PerChargerState — per-charger state
│                             via property dispatch; swap surface fully retired (#589)
├── ev_control.py           — EVControlMixin: per-charger helpers (this-charger power,
│                             config resolution) under the FLEET-READ lint
├── battery_charge_scheduler.py — Cheap-window battery charging + (deactivated)
│                             export arbitrage (#523/#533)
├── cycle_trace.py          — Perception/trace layer: cross-checks, sign-contradiction
│                             audits, health alarms (#589/#590, docs/SEM_TRACE.md)
├── vpp_dispatch.py         — Grid/VPP event dispatch, observer-first (#580)
├── charging_control.py     — ChargingStateMachine (legacy; produces sensor display
│                             state, no longer authoritative for control)
├── ev_taper_detector.py    — EVTaperDetector (taper detection, virtual SOC, skip logic)
├── surplus_controller.py   — SurplusController (multi-device surplus routing)
├── forecast_reader.py      — ForecastReader (Solcast / Forecast.Solar)
├── notifications.py        — NotificationManager (KEBA display + mobile/REST/webhook)
├── storage.py              — SEMStorage (persistent state)
└── types.py                — Fleet dataclasses (PowerReadings, SessionData, SEMData, …)
```

The `SEMCoordinator` is a Home Assistant `DataUpdateCoordinator` that runs a 10-second update loop. Each cycle:

1. Reads sensors (`SensorReader`)
2. Calculates energy integration (`EnergyCalculator`)
3. Calculates costs & performance
4. Calculates power flows (`FlowCalculator`)
5. Updates session tracking
6. Calculates energy flows (daily Sankey totals)
7. Builds charging context and updates charging state machine
8. Executes EV control (night / solar / Min+PV)
9. Applies battery discharge protection
10. Runs load management
11. Reads forecast, tariff, surplus, PV analytics, energy assistant, utility signals
12. Builds `SEMData`, sends notifications, persists to storage

---

## Device Hierarchy

```
ControllableDevice (abstract base)
├── SwitchDevice           — on/off (hot water, smart plugs)
├── CurrentControlDevice   — variable current (EV chargers)
├── SetpointDevice         — numerical target (heat pump temp boost)
│   └── HeatPumpController — SG-Ready 4-state control
└── ScheduleDevice         — deadline-based (appliances)
```

---

## Hot Water Control

SEM acts as a solar boost layer for hot water — it supplements your existing heating system (boiler, heat pump) rather than replacing it. Your existing system continues its normal heating schedule. SEM only activates when solar surplus is available, heating the water further to store energy that would otherwise be exported.

Legionella prevention complies with DVGW W 551 (Germany), SIA 385/1 (Switzerland), and ÖNORM B 5019 (Austria).

### Supported Entity Types

Hot water devices are controlled through one of three HA entity types:

| Entity type | How SEM controls it |
|---|---|
| `water_heater` | Sets target temperature via `water_heater.set_temperature` |
| `climate` | Sets target temperature via `climate.set_temperature` |
| `switch` | Simple on/off — used for resistive heating elements |

### Temperature Logic

The `solar_target_temp` (Solar Boost Target) is the cutoff temperature for solar surplus heating. When the water reaches this temperature, SEM stops heating and releases surplus for other devices. There is no separate "max temperature" — the solar boost target is the ceiling for SEM-controlled heating.

If the solar boost target is set at or above 60°C, the Legionella requirement is naturally satisfied during sunny days without a forced cycle.

### Legionella Prevention Cycle

SEM tracks the number of hours since the water last reached the Legionella target temperature (60°C+). When the configured interval is exceeded, SEM forces a heating cycle regardless of solar surplus availability:

1. **Normal operation** — during solar surplus, SEM heats water to the solar boost target (e.g., 50-65°C)
2. **Legionella countdown** — a counter tracks hours since the last time the water temperature reached the Legionella target
3. **Forced disinfection** — when the interval expires (default 72 hours), SEM forces heating to the Legionella target temperature, using grid power if necessary
4. **Hold duration** — the system holds the disinfection temperature for a duration that auto-adjusts based on the actual temperature reached (shorter hold at higher temperatures, since thermal kill rate increases exponentially)

### Configuration Parameters

| Parameter | Range | Default | Where configured | Description |
|---|---|---|---|---|
| Solar Boost Target | 40-80°C | — | Dashboard slider | Solar surplus heating cutoff |
| Legionella Target | 60-80°C | 65°C | Dashboard slider | Forced heating temperature (legal minimum 60°C) |
| Disinfection interval | 24-168 h | 72 h | Options flow | Maximum hours between disinfection cycles (not on dashboard) |

---

## Surplus Distribution Algorithm

1. Read available surplus (solar - home - battery charge)
2. Subtract regulation offset (default 50W export buffer)
3. Iterate devices by priority (1=highest, 10=lowest)
4. Activate if surplus >= device minimum power threshold
5. Variable-power devices get proportional current allocation
6. When surplus drops: LIFO deactivation (lowest priority first)

The surplus controller is always-on and runs every coordinator update (~10s). Price-responsive mode is automatic when `tariff_mode == "dynamic"`.

---

## SOC Zone Strategy

SEM uses a four-zone SOC model to decide how the battery and EV share solar energy:

```
SOC 100% ─────────────────────────────
         │  Zone 4: FULL ASSIST       │  Battery assist always on
SOC 90%  ─── battery_auto_start_soc ──
         │  Zone 3: DISCHARGE ASSIST  │  Proportional battery assist
SOC 70%  ─── battery_buffer_soc ──────
         │  Zone 2: SURPLUS ONLY      │  EV gets pure solar surplus only
SOC 30%  ─── battery_priority_soc ────
         │  Zone 1: BATTERY PRIORITY  │  All solar → battery, EV blocked
SOC  0%  ─────────────────────────────
```

**Zone 1 — Battery Priority** (SOC < 30%): All solar goes to battery. EV blocked.

**Zone 2 — Surplus Only** (SOC 30-70%): EV gets only pure solar surplus (power that would be exported). Battery is not discharged.

**Zone 3 — Discharge Assist** (SOC 70-90%): Battery supplements solar for EV. The assist **potential** ramps from 50% at SOC 70% to 100% at SOC 90%.

**Zone 4 — Full Assist** (SOC >= 90%): Full battery assist (default 4500W). EV starts even without surplus.

**Assist offered (#545 — "max out till self-consumption"):** in the assist band (Zone 3/4, with real surplus past the Solar Gate) SEM offers the **full** potential — it raises the offered amps so the inverter discharges the battery **into the car down to the buffer SoC** (the self-consumption reserve floor), emptying a near-full battery into the car rather than leaving it idle. The potential ramp (above) self-tapers the discharge toward the buffer. This supersedes the older #501 cap that only topped the car up to the charger minimum. SEM commands no battery directly — it's pure offered amps; the inverter's self-consumption does the discharge.

**Assist floor**: Battery assist is off-limits below `battery_buffer_soc` (default 70%) — the buffer is the single assist floor and the discharge-into-car stops here. (A separate `battery_assist_floor_soc` knob was redundant — assist potential is already 0 below the buffer — and has been removed.)

### SOC Zone Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `battery_priority_soc` | 30% | Below: all solar to battery, EV blocked |
| `battery_buffer_soc` | 70% | Above: battery can discharge for EV (assist floor) |
| `battery_auto_start_soc` | 90% | Above: start EV without surplus |
| `battery_assist_max_power` | 4500W | Max battery discharge for EV |

---

## EV Charging Target (#215)

SEM calculates remaining EV charging need from a single unified helper (`_calculate_remaining_need()`), called from both `_build_charging_context()` and `_determine_charging_strategy()`:

The target is a **Min/Max range** (#245). `_calculate_remaining_need(bound=...)` resolves
either bound via `_resolve_target()`:
```
floor (Min, bound="min")  = ev_target_soc / daily_ev_target          (the guaranteed target)
ceiling (Max, bound="max") = ev_target_soc_max / daily_ev_target_max  (defaults to full=100; clamped >= Min)

if vehicle_soc is available:
    remaining = max(0, (target - vehicle_soc) / 100 × ev_battery_capacity_kwh)
else:
    remaining = max(0, target - daily_ev_energy)
```

- **Night/grid charging** tops up to the **floor (Min)** — `night_target_kwh = remaining(bound="min")`.
- **Surplus (solar) charging** stops at the **ceiling (Max)** — `soc_limit_active = remaining(bound="max") <= 0.1`.
  Max defaults to full, so by default surplus charges freely to car-full.

The old `ev_limit_surplus` switch (#235) was folded into Max (Max < full == limit on); a
setup-time migration sets Max = the prior target for users who had the switch on. All settings
(`ev_target_soc`, `*_max`, `ev_battery_capacity_kwh`) are per-charger; the multi-charger loop
patches `ChargingContext.soc_limit_active` / `night_target_kwh` per charger before calling
`_execute_ev_control()`.

---

## Battery Charge Scheduler (#6)

Forecast-aware grid-to-battery charging during cheap night hours. **Disabled by default** — enable via config flow.

### Decision Pipeline (rolling horizon)

The first evaluation of the night runs when the planning window opens
(trigger hour, default 21:00); the scheduler then re-evaluates every
`battery_replan_interval_min` (default 30 min) until the window closes
(`battery_planning_window_hours` later, default 06:00), picking up price
updates, forecast refreshes and SOC drift MPC-style.

1. **Forecast resolve** — 3-tier fallback: fresh Solcast → stale (doubled pessimism) → offline (conservative)
2. **Deficit calculation** — `expected_consumption - corrected_forecast × confidence × (1 - pessimism)`
3. **Negative tariff override** — force-charge to max SOC during negative prices regardless of forecast
4. **Threshold check** — skip if deficit < `min_deficit_kwh` (default 2 kWh)
5. **Break-even check** — `(off_peak_rate / efficiency) + (2 × cycle_cost) < peak_rate` — includes battery degradation
6. **Target SOC** — `anchor_soc + (deficit / usable_capacity × 100)`, capped at `max_target_soc`.
   The anchor is the SOC at the **first** evaluation of the night's window (#485):
   re-evaluations recompute the plan against fresh prices/forecasts but never stack
   the deficit on top of charging progress — anchoring on the live SOC would ratchet
   the target toward `max_target_soc` every profitable night.
The pipeline stops there. Steps 7–8 used to be the scheduler's own
time-slotted allocation and its own `find_cheapest_hours` pick; **v2.0
deleted both** (#638).

### Where the window comes from (v2.0)

The scheduler says **WHAT** — the deficit, the break-even verdict, the
anchored target SOC, the charge power. The joint energy planner says
**WHEN**: the battery enters the night ledger as a `battery` demand and the
packer places it against the EV, the deferrable loads and the comfort
bands under one shared peak and one price curve.

```
battery_charge_scheduler   →  WHAT   (deficit, economics, target SOC, power)
energy plan (#638)      →  WHEN   (the battery block, peak-aware, priced)
decide_battery             →  gate   (force-charge only inside the block)
```

Consequences worth knowing:

- `decide_battery` force-charges only while the plan's battery block is
  open, at `min(charge_power_w, block_power_w)`, and stops when it closes.
- An **uncovered** battery (no fresh plan) does **not** force-charge — a
  deliberate fail-closed with a named reason on the card, because
  pre-charging is an optimization, not a guarantee.
- The **negative-price override stays reactive** and bypasses the gate
  entirely (`price_forced`) — a paid-to-charge hour is not a planning
  question.
- The `battery_scheduler_schedule` entity is *derived* from the plan's
  battery blocks and keeps its old dict shape, so nothing downstream
  broke.
- The SCHEDULED verdict is persisted beside the plan (`battery_verdict`),
  so a reboot mid-block resumes instead of waiting for the next planning
  window.
- `find_cheapest_hours` now has exactly one home, `tariff/tariff_provider.py`,
  and an AST ratchet (`tests/test_638_one_selector.py`) fails CI on any new
  caller anywhere in the tree.

A mid-charge re-evaluation that lands on NOT_NEEDED / NOT_PROFITABLE stops the
active forced charge instead of leaving the inverter charging unsupervised.

Full walkthrough: [The joint energy planner](ENERGY_PLANNER.md).

### Re-plan Triggers

- Day-ahead price series updated (`price_series_fingerprint` changed) — fires
  **once per series update** (#485); the next evaluation runs when the planning
  window is open
- SOC deviation > 5% from evaluation time
- EV connects/disconnects

### Inverter Adapters

| Platform | Adapter | Control Method |
|----------|---------|---------------|
| Huawei SUN2000 | `HuaweiChargeAdapter` | `huawei_solar.forcible_charge_soc` service |
| GoodWe | `GoodWeChargeAdapter` | Work mode select + SOC target number |
| Generic | `GenericChargeAdapter` | Force-charge switch + SOC target number |
| Auto | Factory detection | Checks `hass.config.components` |

### Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `battery_charge_scheduler_enabled` | `false` | Feature toggle |
| `battery_capacity_kwh` | 10.0 | Usable battery capacity |
| `battery_max_charge_power_w` | 5000 | Inverter max charge rate |
| `battery_roundtrip_efficiency` | 0.92 | Round-trip efficiency |
| `battery_cycle_cost` | 0.0 | Degradation cost per kWh throughput (0 = check disabled; the config form suggests 0.02 for new setups) |
| `battery_precharge_trigger_hour` | 21 | Planning window opens (first evaluation) |
| `battery_replan_interval_min` | 30 | Rolling re-evaluation cadence inside the window |
| `battery_planning_window_hours` | 9 | Window length (21:00 → 06:00 by default) |
| `battery_prefer_consecutive_window` | `true` | Charge in one contiguous block vs scattered cheapest slots |
| `battery_max_target_soc` | 95% | Never plan above this |
| `battery_min_deficit_kwh` | 2.0 | Minimum deficit to bother charging |
| `battery_pessimism_weight` | 0.3 | Forecast pessimism (0=trust, 1=worst case) |
| `battery_force_charge_negative_price` | `true` | Charge during negative prices |
| `target_peak_limit` | 5.0 kW | House peak limit the night schedule respects (shared with load management, #693) |
| `battery_max_grid_import_w` | 0 | Max grid draw during charging |

### Sensors

| Sensor | Type | Description |
|--------|------|-------------|
| `battery_scheduler_state` | Diagnostic | idle/scheduled/charging/target_reached/not_needed/not_profitable |
| `battery_scheduler_target_soc` | % | Planned target SOC for tonight |
| `battery_scheduler_deficit_kwh` | kWh | Calculated energy deficit |
| `battery_scheduler_reason` | Diagnostic | Human-readable decision explanation |

The `battery_scheduler_state` sensor has a `schedule` attribute containing the full time-slotted plan (serialized via `NightChargeSchedule.as_dict()`).

---

## EV Control Flow

The coordinator owns all EV control (`ev.managed_externally = True`). The EV is never managed by the SurplusController due to unique requirements (session lifecycle, minimum 4140W cliff, charger-specific service calls).

### Night Charging
- Starts at 10A when night mode activates (after sunset+10min / 20:30)
- Dynamic peak-managed current each cycle (+-2A ramp, min 8A floor)
- W/A ratio calculated from actual readings (fallback 475 W/A)
- Stall detection with 120s cooldown re-enables charger
- Stops when daily EV target reached (sunrise-based tracking)

### Solar Charging
- Sets current with ramp limiting (+-2A/cycle)
- Hysteresis enable/disable delays (persistence timers)
- Budget from `FlowCalculator.calculate_ev_budget()` + optional battery assist

### Min+PV Mode
- Budget floored to `ev.min_power_threshold`
- Enable delay = 0 (guaranteed minimum from grid)

### Pause States
- Zero current, keep session alive (no stop/start cycling)

### Charger Abstraction

SEM abstracts charger-specific differences through per-integration service profiles:

- **Service profiles** — each supported charger integration has a `service_param_name` (e.g., `current` for KEBA, `charging_current` for Wallbox) and `service_device_id` mapping, so the coordinator can call the correct HA service with the right parameters.
- **Start/stop abstraction** — chargers that require explicit start/stop commands use `start_stop_entity`, `charge_mode_entity`, and `start_service` to manage session lifecycle. Chargers that only need current=0 to pause do not use these.
- **Supported chargers (auto-detected):** KEBA, Easee, Wallbox, go-eCharger (HTTP + MQTT), Zaptec, ChargePoint, Heidelberg, OpenWB 2.x, OCPP-compatible, Ohme, Peblar, V2C Trydan, Alfen Eve, Blue Current, OpenEVSE
- **Manual config:** Any charger exposing power/connected/charging sensors in HA can be configured manually via the integration options.

---

## EV Budget Calculation

### One canonical value, six strategies

Since **v1.6.0**, all "how many watts can the EV draw right now" decisions
read from a single canonical `EVBudget` value computed once per coordinator
cycle by `FlowCalculator.calculate_canonical_ev_budget()`.

Before v1.6.0, three separate paths each computed their own budget
independently (`coordinator.py:898` for the published sensors,
`coordinator.py:2589` for the state machine's input,
`ev_control.py:440-452` for the actuator). Under certain conditions they
disagreed — the symptom most users could see was the dashboard reporting
*"Charging active"* while the car drew 0 W (issue #282). v1.6.0 collapses
all three into one source of truth; the disagreement is now impossible by
construction.

### The dataclass

```python
@dataclass
class EVBudget:
    strategy: str           # one of EVBudgetStrategy.*
    solar_surplus: float    # max(0, solar − home − batt_charge)
    battery_redirect: float # forecast/SOC-aware battery-charge diversion
    battery_assist: float   # active battery discharge attributed to EV
    net_w: float            # solar_surplus + redirect + assist (or override)
    current_a: int          # floor(net_w / (voltage × phases)), clamped [0,16]
```

The decomposition exists so the dashboard can publish each component
as its own diagnostic — answering "where did this watt come from"
without re-deriving anything.

`current_a` always uses `math.floor` (not round-to-nearest) — round-
to-nearest could push the actuator 0.5 A over the surplus floor and
silently leak grid into the EV at the boundary. Locked in by the
591956f / `tests/scenarios/2026-05-28_surplus_leak.yaml` regression.

### The six strategies and their formulas

```python
class EVBudgetStrategy:
    IDLE             = "idle"             # 0
    SELF_CONSUMPTION = "self_consumption" # Zone 2: raw_surplus only,
                                          # NO redirect (battery has priority)
    SOLAR_ONLY       = "solar_only"       # Zone 3: raw_surplus + battery_redirect
    BATTERY_ASSIST   = "battery_assist"   # Zone 4: raw_surplus + redirect + assist
    MIN_PV           = "min_pv"           # max(min_power_floor, surplus+redirect)
                                          # — grid backfill accepted
    NOW              = "now"              # override_max_w (charger nameplate)
```

The dispatcher raises `ValueError` on any unknown strategy — silent
fallthrough was exactly the pre-1.6.0 disagreement root, so the
unifier is loud.

### Strategy selection (post-arch Step 7)

`_determine_charging_strategy` / `_canonical_strategy_from_legacy` and
the zone helpers (`_raw_zone`, `_get_zone`, `_debounce_zone`) were
removed in PR #358 (arch Step 7). Every per-charger strategy decision
now flows through `coordinator/decide.py:decide(view)` — a pure
function over a `ChargerView` snapshot. The old code returned
`"solar_only"` for both Zone-3 solar_only AND Zone-2 self_consumption,
distinguished only by substring matching on `charging_strategy_reason`
(brittle, root cause of #282); `decide()` selects strategies directly
from the charger's mode and the fleet state.

### Per-strategy details

**`SELF_CONSUMPTION`** — Zone 2 surplus-only. When `battery_soc ≥
auto_start_soc` (default 90 %), the battery doesn't need its share, so
the formula skips the `batt_charge` subtraction (`Z4-redirect`
sub-mode). Otherwise: `max(0, solar − home − batt_charge)`. No
battery_redirect — the battery keeps the charge it's receiving.

**`SOLAR_ONLY`** — Zone 3. Solar surplus PLUS the forecast-aware
`battery_redirect` from `_calculate_battery_redirect()`. When forecast
remaining exceeds the battery's remaining capacity-to-100 %, the
redirect proportionally diverts battery-charge power to the EV; without
a forecast, falls back to a SOC threshold (redirect-all at
`SOC ≥ 80 %`). The Phase C scenarios pin both branches.

**`BATTERY_ASSIST`** — Zone 4. Surplus + redirect + active battery
discharge. The assist component uses the measured discharge if the
battery is already discharging ≥ 100 W, otherwise estimates a
proportional ramp `(battery_soc − battery_buffer_soc) / (auto_start_soc
− battery_buffer_soc) × battery_assist_max_power_w` scaled to 50–100 %
of max. Below `battery_buffer_soc` (default 70 %) the assist is
zero. **Note**: proportional flow attribution may transiently show a
small `flow_grid_to_ev_power` during the battery's discharge ramp-up
window (LFP BMSes take seconds to ramp). That's the physics of the
proportional split, not SEM commanding grid — see
`KNOWN_LIMITATIONS.md`.

**`MIN_PV`** — User-asked guaranteed minimum. `max(min_power_floor_w,
surplus + redirect)`. Grid backfill is intentional in this mode; the
sentinel test `tests/live/test_solar_only_no_grid.sh` correctly skips
non-`solar_only` strategies because MIN_PV's whole purpose is to allow
grid.

**`NOW`** — User-asked maximum. Bypasses the surplus math entirely
and uses `override_max_w` (typically the charger's nameplate power).
The decomposition fields (`solar_surplus`, `redirect`, `assist`) stay
zero — they're honest about "this isn't from solar."

### How the consumers wire up

```
        ┌──────────────────────────────────────────────────────┐
        │ calculate_canonical_ev_budget(power, strategy, ...)  │
        │   → EVBudget(strategy, surplus, redirect, assist,    │
        │              net_w, current_a)                       │
        └────────────────┬─────────────────────────────────────┘
                         │ cached as self._cycle_ev_budget
                         │
       ┌─────────────────┼─────────────────────────────────────┐
       │                 │                                     │
       ▼                 ▼                                     ▼
   ChargingContext   SEMData publish              _execute_ev_control
   .available_power  .available_power             (single-charger)
   .calculated_      .calculated_current             budget_w =
   current               ↓                              cycle_budget.net_w
       ↓             sensor.sem_available_power
   state_machine     sensor.sem_calculated_       _surplus_controller.
   decision            current                    distribute_ev_budget
                                                  (multi-charger, Phase B.5)
                                                     total_budget =
                                                       cycle_budget.net_w
                                                     → per-charger split
                                                       by priority
```

### The forever sentinel

`tests/live/test_budget_agreement.sh` asserts the canonical relationship
`floor(sensor.sem_available_power / (230 × 3)) == sensor.sem_calculated_current`
on the live system. If a future refactor accidentally re-introduces a
second budget path that publishes a different number, the sentinel
fires. It runs in seconds against any HA instance and is the
operational guarantee that the unification holds.

### `_calculate_battery_redirect` — the forecast-aware diversion

When the home battery is charging and SOC is below the buffer, the
default behaviour is "all surplus to battery first." But if the
forecast says there's enough remaining solar today to fill the
battery anyway, some of that battery-bound power can be redirected
to the EV without slowing the battery's actual fill. The math:

```python
battery_need_kwh = max(0, (100 − battery_soc) / 100 × battery_capacity_kwh)

if forecast_remaining_kwh >= battery_need_kwh:
    ratio = max(0.05, 1 − battery_need_kwh / forecast_remaining_kwh)
    redirect = battery_charge_w × ratio
elif battery_need_kwh <= 0.5:  # battery nearly full
    redirect = battery_charge_w  # redirect all
else:
    redirect = 0  # forecast can't cover; keep battery filling
```

Without a forecast, the SOC threshold fallback gives `redirect =
battery_charge_w` when `SOC ≥ 80 %`, else `0`.

### Legacy methods (deprecated)

`FlowCalculator.calculate_ev_budget()`, `.calculate_available_power()`
and `.calculate_charging_current()` are kept callable in v1.6.0 for
backward compatibility (one fallback site in `ev_control.py` for
partial-init paths), but are no longer the source of truth. Phase D.2
removes them in v1.7.0 after additional soak.

---

## Energy Tracking — Sunrise-Based Meter Day

`EnergyCalculator` uses sunrise-based daily buckets, not midnight. Before sunrise = still "yesterday". This keeps night charging sessions (22:00-06:00) in a single bucket.

---

## Key Defaults

| Constant | Value | Location |
|----------|-------|----------|
| `DEFAULT_DAILY_EV_TARGET` | 10 kWh | `const.py` |
| `DEFAULT_EV_RAMP_RATE_AMPS` | 2 | config |
| `DEFAULT_EV_CHARGING_MODE` | `"auto"` | config |
| `battery_capacity_kwh` | auto-detected from inverter, fallback to config | coordinator |
| Update interval | 10s | coordinator |
| Regulation offset | 50W | surplus controller |
| Peak limit | 6 kW | load management |

---

## Hardware Compatibility Testing

SEM includes a comprehensive hardware compatibility test suite (v1.2.3) that verifies every supported inverter + charger combination works correctly end-to-end.

### Test Structure

The suite runs 110 end-to-end tests, each executing a 10-step verification sequence per hardware combination:

1. **Sensor discovery** — auto-detect inverter and charger entities
2. **Sign convention detection** — verify grid and battery sign auto-detection
3. **Power reading** — read solar, grid, battery, and EV power sensors
4. **Energy integration** — validate energy accumulation from power readings
5. **Flow calculation** — verify power flow distribution (solar-to-home, solar-to-EV, etc.)
6. **Charging control** — test EV charging state machine transitions
7. **Battery zone logic** — validate SOC zone strategy decisions
8. **Surplus distribution** — verify multi-device surplus allocation
9. **Service calls** — confirm charger service calls use correct parameters
10. **Round-trip validation** — end-to-end cycle from sensor read to hardware command

### Tested Combinations (11)

| Inverter | Charger |
|----------|---------|
| Huawei SUN2000 | KEBA P30 |
| Huawei SUN2000 | Wallbox Pulsar |
| Huawei SUN2000 | go-eCharger |
| SolarEdge | KEBA P30 |
| SolarEdge | Easee |
| Fronius | KEBA P30 |
| Fronius | go-eCharger |
| Growatt | Wallbox Pulsar |
| SolaX | go-eCharger |
| DEYE/Sunsynk | Zaptec |
| GoodWe | ChargePoint |

All 11 combinations are run in CI on every pull request and release. If your inverter and charger are in this list, SEM has been automatically verified against that exact pairing.

---

## EV Intelligence

The `EVTaperDetector` (coordinator/ev_taper_detector.py, ~590 lines) provides six capabilities integrated into the coordinator's 10-second update loop via `_update_ev_intelligence()`:

### Data Flow

```
SEMCoordinator._update_ev_intelligence()
  ├── EVTaperDetector.update_power_buffer(ev_power, setpoint)
  ├── EVTaperDetector.detect_taper() → EVTaperData
  ├── EVTaperDetector.update_virtual_soc(energy, vehicle_soc) → float
  ├── ConsumptionPredictor.update() / predict() → float
  ├── EVTaperDetector.should_skip_night_charge(...) → (bool, str)
  └── EVTaperDetector.update_battery_health(session) → float
```

### Key Dataclasses (coordinator/types.py)

```python
@dataclass
class EVTaperData:
    trend: str              # "declining", "stable", "rising", "unknown"
    taper_ratio_pct: float  # Current power / session peak × 100
    slope_w_per_min: float  # Linear regression slope
    minutes_to_full: float  # ETA to completion
    ev_full_detected: bool  # Taper reached 0W

@dataclass
class EVIntelligenceData:
    # Display/diagnostic fields only (#440: skip-decision fields removed)
    taper: EVTaperData
    estimated_soc_pct: float
    last_full_charge: Optional[str]       # ISO timestamp
    energy_since_full_kwh: float
    predicted_daily_ev_kwh: float
    ev_battery_health_pct: float
```

The fields `nights_until_charge`, `charge_needed`, and `charge_skip_reason` were removed in #440. Charge mode (`select.sem_charger_<id>_charge_mode`) is the sole authority on whether to charge — the skip-decision signals are diagnostic only and do not override the user's stated mode.

### Taper Detection

Uses a 20-minute circular power buffer. Linear regression on the buffer detects a declining trend. BMS-initiated reductions are discriminated from SEM setpoint changes via a settling window (samples after a SEM command are excluded). When power reaches 0W during a declining trend, `ev_full_detected` is set.

### Virtual SOC

Tracks cumulative energy since last known full charge. Calibrates from:
1. Taper detection (resets to 100%)
2. Vehicle SOC entity (proportional calibration)
3. Session bootstrapping (initial estimate from first session)

### Skip Logic

```
required_soc = predicted_daily_kwh × temp_correction × 1.3 (safety margin)
available_soc = estimated_soc - daily_decay
solar_credit  = forecast_tomorrow × 0.3
charge_needed = (available_soc - solar_credit) < required_soc
```

Consecutive skip counter enforces a 3-skip safety net.

### State Persistence

EV intelligence state (SOC estimate, last full charge, consumption history, skip counter) is persisted via `SEMStorage.set/get_ev_intelligence_state()` and restored on HA restart.

---

## Multi-Device Aggregation

SEM reads **all** energy sources from the HA Energy Dashboard instead of only the first entry. This is handled in `ha_energy_reader.py` and `coordinator/sensor_reader.py`.

### Energy Dashboard Config Fields

```python
# List fields (new in v1.3.0)
solar_power_list: list[str]              # Multiple inverter power sensors
solar_energy_list: list[str]             # Multiple inverter energy sensors
battery_power_list: list[str]            # Multiple battery power sensors
battery_charge_energy_list: list[str]    # Multiple battery charge sensors
battery_discharge_energy_list: list[str] # Multiple battery discharge sensors
grid_import_energy_list: list[str]       # Multiple grid import tariffs
grid_export_energy_list: list[str]       # Multiple grid export tariffs
grid_power_list: list[str]              # Multiple grid power sensors
```

### Aggregation Logic

- `SensorReader._read_sensors_sum(entity_list)` — sums numeric values from multiple sensors; skips unavailable/unknown
- `SensorReader._read_battery_soc_average()` — averages SOC across multiple battery units
- Primary (single) fields are set from the first source for backward compatibility

### Backward Compatibility

Single-device setups are unaffected. The list fields contain exactly one entry, and the primary field points to the same sensor. No configuration changes needed.

---

## Multi-EV Charger Control

v1.4.0 adds active control of multiple EV chargers via `coordinator._ev_devices: Dict[str, CurrentControlDevice]`.

### Architecture Pattern: PerChargerContext (#589, v1.7.5)

The coordinator iterates chargers in priority order using `PerChargerContext` as a context manager. The snapshot/restore "context swap" was retired in #589 — there is no `saved = {...}` dict and nothing to restore.

Durable per-charger state (stall timer, enable-delay timer, etc.) lives on `PerChargerState` objects stored in `coord._pcc_store[cid]` and held **by reference** on the context's `.state` field. The coordinator's `_ev_*` / `_ev_device` / `_cycle_vehicle_soc` names are **properties** that dispatch on `coord._current_pcc` — so a forgotten write-back (the #284/#315/#318 leak class) is structurally unrepresentable.

```python
for cid, ev_dev in sorted_chargers:
    with PerChargerContext.for_charger(coord, cid, ev_dev, power=power) as pcc:
        if pcc.skipped_for_night:
            continue
        view = build_charger_view(coord, cid, ev_dev, pcc, power)
        decision = decide(view)
        await actuate(decision, adapter, view.power, ...)
```

Cycle-scoped state (e.g. `vehicle_soc`) lives on the context object and dies with it — no write-back needed.

### Surplus Distribution

`SurplusController.distribute_ev_budget()` implements priority-based cascade:
1. Sort chargers by priority (lower = higher)
2. Highest-priority charger: `min(budget, max_power)`
3. Remainder cascades if ≥ `min_power_threshold` (4140W 3-phase / 1380W 1-phase)
4. 60s hysteresis between reallocations

### Config Migration

Config entry v2→v3: flat `ev_*` keys wrapped into `ev_chargers` list automatically. The `__init__.py` registration loop creates `CurrentControlDevice` per charger.

Config entry v3→v4 (#255): **per-charger is the source of truth for all EV settings**; the duplicate GLOBAL EV setting entities (`daily_ev_target[_max]`, `ev_target_soc[_max]`, `ev_min_current`, `ev_night_initial_current`, `ev_kwh_per_100km`, `ev_target_type`, `ev_charging_mode`, `ev_phases`, the `night_charging` / `smart_night_charging` switches) were removed. The migration seeds each charger's per-charger value from the matching global so nothing resets. Globals remain only as **read-only summary sensors**. The night-charging gate is now "any charger enabled" (`ChargingStateMachine._any_night_charging_enabled`); a one-time reconciliation forces per-charger night switches OFF if the removed global switch was last OFF (so a globally-disabled user isn't silently re-enabled). A few global-context consumers read the primary charger's values via `SEMCoordinator._mirror_primary_charger_to_global()` (exact for single-charger). `ev_stall_cooldown` stays global (tuning constant).

### Per-Charger State

Each charger has independent:
- `SessionData` (energy, cost, solar share)
- Stall detection timer
- Enable/disable delay timers
- `EVTaperDetector` instance (taper detection, virtual SOC)
- `ChargingStateMachine` shares mode (all chargers follow same solar/night strategy)

---

## Other Key Modules

```
tariff/tariff_provider.py       — StaticTariffProvider, DynamicTariffProvider
analytics/pv_performance.py     — PVPerformanceAnalyzer
analytics/energy_assistant.py   — EnergyAssistant (tips, optimization score)
utils/time_manager.py           — TimeManager (sunrise, night mode/end, meter day)
utils/helpers.py                — safe_float, safe_format, convert_power_to_watts
ha_energy_reader.py             — Read HA Energy Dashboard config
load_management.py              — LoadManagementCoordinator (peak tracking)
hardware_detection.py           — Auto-discover inverter/battery/charger
```

---

## Translation / i18n Architecture

SEM uses a **hybrid two-layer translation system** because Home Assistant has two different language settings that affect different parts of the UI.

### The Two Language Settings

| Setting | Where configured | Scope | Affects |
|---------|-----------------|-------|---------|
| **System language** | Settings → General → Language | One per HA instance | Config flow, entity names, mushroom card labels, dashboard template strings |
| **User language** | User profile → Language | Per user | SEM custom cards (sem-flow-card, sem-chart-card, etc.) |

A household may have the system set to German, but one user's profile set to English. In that case, mushroom card titles appear in German (system), while SEM custom cards appear in English (user profile).

### Layer 1: Server-Side Translation (System Language)

**When:** Dashboard generation (`generate_dashboard` service call)
**Source:** `hass.config.language` (system language)
**File:** `features/dashboard_generator.py` → `_translate_dashboard()`
**Translates:** All YAML-based card content — mushroom titles, labels, tab names, template strings

**How it works:**
1. Loads `dashboard/translations.json` (single source of truth, 1341 keys × 16 languages)
2. Builds a reverse lookup: English text → translated text
3. Walks the entire dashboard YAML tree
4. Replaces exact-match English strings in translatable fields: `title`, `subtitle`, `primary`, `secondary`, `name`, `label`, `content`
5. For Jinja-templated fields (containing `{{ }}` or `{% %}`): splits on Jinja blocks using regex, translates only the literal text between them
6. Writes the translated dashboard to Lovelace storage

**What this means for users:**
- Mushroom cards, section headers, and static labels are translated **once** at generation time
- All users see the **same language** for these elements (the system language)
- To change: update system language → re-run `generate_dashboard` service
- Third-party cards (mushroom, apexcharts, sankey) cannot use runtime translation — they only read stored YAML

### Layer 2: Runtime Per-User Translation (User Language)

**When:** Every render cycle in the browser
**Source:** `hass.language` (current user's profile language)
**File:** `dashboard/card/sem-localize.js` → `semLocalize(key, lang)`
**Translates:** All SEM custom card content (labels, status text, error messages)

**How it works:**
1. `sem-localize.js` is auto-generated from `translations.json` — contains all 1341 keys × 16 languages as a JS object
2. Loaded as a Lovelace resource, exposes `window.semLocalize(key, lang)`
3. Fires `sem-localize-ready` CustomEvent when loaded
4. SEM cards extend `SEMLitBase` (in `src/base/sem-lit-base.js`) which provides `_t(key)` → calls `semLocalize(key, hass.language)`
5. Cards re-render when the user's language changes (detected in `_checkLocaleChange()`)

**Placeholder pattern:** When Python sensor values contain translatable words (e.g. "tomorrow" in surplus window), the coordinator outputs `{tomorrow}` as a placeholder. Cards replace it with `this._t('tomorrow')` before display. This bridges the server→client translation gap without duplicating translation logic in Python.

**Fallback chain:** user language → English → raw key

**What this means for users:**
- Each user sees SEM custom cards in **their own profile language**
- Two users viewing the same dashboard can see different languages for SEM cards
- Language changes take effect immediately (no dashboard regeneration needed)

### Which Cards Use Which Layer?

| Card Type | Translation Layer | Language Source | Example |
|-----------|------------------|----------------|---------|
| Mushroom chips/entities | Server-side | System language | "Solar Power", "Battery SOC" |
| Mushroom template cards | Server-side | System language | "Peak Management", "Optimization Score" |
| Section titles (sem-title-card) | Runtime per-user | User profile | Tab headers with live Jinja subtitles |
| sem-flow-card | Runtime per-user | User profile | Node labels, status text |
| sem-chart-card | Runtime per-user | User profile | Chart titles, axis labels, legends |
| sem-battery-card | Runtime per-user | User profile | "Charging", "Discharging", "Idle" |
| sem-ev-status-card | Runtime per-user | User profile | Mode labels, session stats |
| sem-charger-status-card | Runtime per-user | User profile | Charger status, power labels |
| sem-period-selector-card | Runtime per-user | User profile | "Today", "This Week", "This Month" |
| sem-solar-summary-card | Runtime per-user | User profile | Production stats, forecast |
| sem-weather-card | Runtime per-user | User profile | Weather labels |
| Sankey chart (3rd party) | Server-side | System language | Node names in energy flow |
| ApexCharts (3rd party) | Server-side | System language | Chart titles, series names |

### Single Source of Truth

Both layers read from the same file: **`dashboard/translations.json`**

```
dashboard/translations.json          ← single source (1341 keys × 16 languages)
    │
    ├──→ dashboard_generator.py      reads at generation time (server-side)
    │
    └──→ sem-localize.js             auto-generated copy for browser (runtime)
```

**Important:** `sem-localize.js` must be regenerated whenever `translations.json` changes. It is a generated artifact — never edit it directly.

### Supported Languages

Czech (cs), Danish (da), German (de), English (en), Spanish (es), Finnish (fi), French (fr), Hungarian (hu), Italian (it), Dutch (nl), Norwegian (no), Polish (pl), Portuguese (pt), Romanian (ro), Swedish (sv)

### Adding a New Language

1. Add the language code and all 1341 keys to `dashboard/translations.json`
2. Create `translations/{lang}.json` with config flow and entity translations (mirror `strings.json` structure)
3. Regenerate `sem-localize.js` from `translations.json`
4. Deploy and call `generate_dashboard` to apply server-side translations

### Adding a New Translation Key

1. Add the key to **all 16 languages** in `translations.json`
2. Regenerate `sem-localize.js`
3. Use `_t('key_name')` in custom card JS, or use the English text directly in dashboard template YAML (server-side translation handles the lookup)
