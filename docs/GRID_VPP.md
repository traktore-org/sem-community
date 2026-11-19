# Grid VPP events

A virtual power plant (VPP) aggregator can send grid events and pay you for
each one. An event has no set power level: SEM aims for as much as possible.
SEM uses the battery, car and loads it already controls.

| Event | Battery | Car | Loads |
|---|---|---|---|
| **Export** (deliver to the grid) | Discharges at full power, never below the VPP reserve | Paused | Shed |
| **Import** (take power from the grid) | Charges at full power | Boosted to the maximum current | May start, not shed |
| **Pre-event** (export coming) | Tops up from solar only | Paused | No change |

## Set up

Open **System › What SEM may do › More**.

| Row | Meaning | Default |
|---|---|---|
| **VPP dispatch** | Turns VPP on | Off |
| **VPP dry run (log only)** | Computes events, sends no commands | On |
| **Event signal** | On while an event runs | |
| **Event direction** | `export` or `import`. Unknown counts as export. | |
| **Event end time** | When the event should end (optional) | |
| **Pre-event signal** | Announces an export event early (optional) | |
| **VPP battery reserve** | Lowest charge for a VPP export (5 to 80 %) | 20 % |

The signals come from your aggregator's integration.

## Dry run first

With **VPP dry run** on, SEM logs what it would do and publishes
`sensor.sem_vpp_event`, but sends no commands. Compare the log with your
aggregator's events. Then turn the dry run off.

## Safety rules

- An export never takes the battery below the VPP reserve or its own
  reserve, whichever is higher.
- A battery in **Off** mode is never commanded.
- If the event signal stays on 30 minutes after the event end time, SEM
  treats the event as over and logs a warning.
- Commands end with the event. When the event ends, or SEM starts with no
  event, the battery returns to its normal mode.

## Event record

`sensor.sem_vpp_event` state: `idle`, `pre_event`, `event_export` or
`event_import`. Its attributes include `delivered_kwh_so_far`,
`last_event` and `events` (the last 5). SEM keeps the last 20 events across
restarts.

The energy of an event is the change of the grid meter during the event.
If the meter resets during an event, SEM counts the energy up to the reset.

## Not included

- Grid energy to top up the battery before an export.
- A set power level.
- Starting deferred loads on an import event.
