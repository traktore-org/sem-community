# Grid VPP dispatch (#580)

SEM can respond to **Virtual Power Plant (VPP) grid events** — dispatch
requests from an aggregator like [Axle Energy](https://axle.energy) that pays
you **per event** for delivering flexibility ("as much as possible"; there is
no requested power level). When an event fires, SEM re-purposes the controls
it already has:

| Event | Battery | EV charging | Surplus loads |
|---|---|---|---|
| **Export** (deliver to grid) | Force-discharge at max power, never below the **VPP reserve SOC** | Paused for the window | Shed (peak-shed gate) |
| **Import** (soak up grid power) | Force-charge at max accepted power | Boosted to max current (if connected) | May start (not shed) |
| **Pre-event** (export coming) | Topped up **from solar only** (EV paused so surplus flows to the battery — no grid top-up in v1) | Paused | — |

Everything routes through SEM's **existing** actuation machinery
(`decide_battery` → battery adapters, the single charge-mode read-point, the
surplus controller's peak posture). There is no second actuator to strand.

## Observer-first rollout

`vpp_observer_mode` defaults to **on**. While it is on, SEM computes the full
dispatch every cycle and:

- logs one INFO per phase transition — `VPP event started (export) — WOULD
  dispatch: force_discharge, pause_ev, shed_loads`,
- sends a notification at event start/end (if mobile notifications are
  enabled),
- publishes `sensor.sem_vpp_event` with the live accounting,

but **actuates nothing**. Run a few events like this, compare the log against
what your VPP portal expected, then disable observer mode.

## Entity wiring (Axle Energy)

Configure under **Config → Advanced → Grid VPP** on the dashboard:

| SEM option | Axle entity (typical) | Meaning |
|---|---|---|
| `vpp_event_active_entity` | `binary_sensor.axle_event_in_progress` | Event gate — active when state is `on` / `in_progress` |
| `vpp_direction_entity` | `sensor.axle_event_direction` | `export` or `import` (unknown → treated as export) |
| `vpp_event_end_entity` | `sensor.axle_event_end` (timestamp) | Optional sanity cap (see below) |
| `vpp_pre_event_entity` | `binary_sensor.axle_event_in_1_hour` | Optional pre-conditioning trigger |
| `vpp_enabled` | — | Master opt-in (default off) |
| `vpp_observer_mode` | — | Dry-run (default **on**) |
| `vpp_reserve_soc` | — | Export floor, default 20 % |

Any integration exposing this shape works — Axle is just the first wiring.

## Safety rails

- **Reserve floor**: export events never discharge the home battery below
  `vpp_reserve_soc`. The effective floor is `max(vpp_reserve_soc, the
  battery's own reserve)` — VPP can only tighten it. At/below the floor the
  discharge simply doesn't fire (and an *unavailable* SOC holds — never
  discharge blind).
- **Hands-off batteries stay hands-off**: a battery whose mode is `off` is
  never commanded by a VPP event.
- **Gate-stuck cap**: if the event gate stays active more than 30 minutes
  past the advertised end time (`vpp_event_end_entity`), SEM treats the event
  as over and logs a warning.
- **Event end / boot reconcile** (the #532 strand class): the force op is a
  *per-cycle* override — the moment the event ends (or SEM restarts with no
  active event) the override is gone, `decide_battery` returns to NORMAL and
  every adapter's `command_normal()` teardown zeroes forcible setpoints
  (Huawei additionally clears startup orphans). A VPP force op cannot outlive
  its window.
- **Per-cycle re-assertion**: nothing about an event is latched — every
  coordinator cycle re-reads the gate; a flap simply ends the event.

## Per-event energy accounting

Payment is per event, so SEM snapshots the grid import/export energy counters
at event start and computes the delivered kWh at event end (export events use
the export-counter delta; import events the import delta; a counter reset
mid-event — e.g. midnight rollover — banks the delivered energy and
re-baselines, never counts negative). The last 20 events are persisted across
restarts.

`sensor.sem_vpp_event`:

- **state**: `idle` / `pre_event` / `event_export` / `event_import`
- **attributes**: `direction`, `started`, `delivered_kwh_so_far`, `observer`,
  `reason`, `last_event` (`{start, end, direction, kwh, observer}`), `events`
  (last 5 records).

A restart mid-event resumes the open record if the gate is still active
(keeping the kWh delivered so far); otherwise the record is closed and marked
`reconciled`.

## Deliberately out of scope (v1)

- Pre-event **grid** top-up (solar only — simple and safe).
- A requested power level / setpoint following (Axle confirmed: none exists;
  events are "as much as possible").
- Forced starting of deferred loads on import events (they merely aren't
  shed; the surplus controller may start them on its own terms).
