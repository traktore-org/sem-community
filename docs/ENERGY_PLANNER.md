# Energy planner

The energy planner plans one energy day: the rest of today and the coming
night. It decides **when** flexible devices run, so they use cheap or free
energy. It does not decide **whether** a device runs. Safety rules still
apply.

## Plan drives devices

Plan screen › **Plan drives devices** (a switch, on by default).

- **On**: the plan's windows steer the car, the loads and the battery.
- **Off**: the plan is only computed and shown. The Plan screen shows the pill
  **shadow**. Each device uses its own rules. **Live** means the plan steers.
- Turning it on or off asks first.

## What the planner uses

| Input | Where you set it |
|---|---|
| Car connected, charge target, **Charge by** time | Devices › car |
| Load goal: **At least** and **Up to** (hours a day) | Devices › load |
| Battery charge level, reserve and discharge limit | Devices › battery |
| Comfort band of a room or heater | Devices |
| Prices (day-ahead, when published) | Tariff setup |
| Solar forecast | Forecast setup |
| Home use, learned per weekday and hour | Learned, no setting |
| Night start | System › Notifications and more |

A device is planned only if it has a need: a car that is connected and
has a target, or a load with an **At least** goal. A device with no goal
is not planned.

## What it decides

The planner fills each need into the cheapest hours it allows. It packs
the needs in the device priority order. Each need takes what the needs
before it left.

| Need | Source | Rule |
|---|---|---|
| Battery pre-charge | Grid | Cheapest priced hours. Asks only for the room the pack has left. A block with no cheaper hour left says "No cheaper hour left". |
| Car by its **Charge by** time | Grid | Cheapest hours before the time. Never from the home battery. |
| Load with an **At least** goal | Grid | Only hours with a cheap price level |
| Load finished overnight from the battery | Battery | Earliest hours. Uses only the battery energy above the floor, after the house. |
| Comfort run | Free or cheap hours | Never paid at the normal price |

The **floor** is the battery energy kept for the morning: the battery
reserve, or the battery scheduler's target if higher. The plan never uses
it tonight.

A device in **Off** or **Peak only** mode is not planned.

### When the plan does not cover a need

| Need | SEM does |
|---|---|
| Car | Charges at its deadline or minimum anyway. A missed minimum is worse than a high price. |
| Battery pre-charge | Does not force a charge. |
| Load | Uses its own rules for price, reserve and run times. |
| Comfort | Does not run for banking. |
| Battery sale | Does not sell. |

## When the plan is made

- Once per energy day, from the end of the night to the next end of the
  night. It is made again if the devices or battery are not ready yet.
- It is made again when the car connects or disconnects, when a target,
  deadline or mode changes, when a load goal changes, when the price curve
  is published, or when the solar forecast changes.
- The plan is saved, so a restart keeps it.
- A new plan replaces the old one only when the answer changes. The field
  `computed_at` shows when the current answer was made.
- A plan older than 24 hours does not steer devices.
- You can make a new plan at once with the `solar_energy_management.replan`
  service.

## Read the plan

**Plan screen › Price and plan**: the pill says **everything fits** or
**not everything fits**. For a shortfall it names the device and its kWh.

**Plan screen › Why this plan**:

- One row per need, with its time window and its kWh.
- **Not scheduled** lists the devices left out, with the reason. For
  example: "no car connected", "car is already full", "already at its
  target", "daytime only, does not run at night". A heat pump that is not in the plan
  says why on this screen and on its **Devices** row, for example that it has
  no comfort band or minimum run time.

Other places:

- `sensor.sem_energy_plan`. Its state is `fits`, `yields`, `idle` or
  `pending`. The attributes include `demands`, `blocks`, `takeover`,
  `total_cost`, `computed_at` and `replan_cause`.
- `solar_energy_management.diagnose` returns the latest plan in full.

Home Assistant stores at most 16 KiB of attributes for an entity. For a
very large night, the timeline is left out. The attribute
`timeline_omitted` is then `true`, and the card shows the list of needs
instead. Two small attributes take the timeline's place: `house_grid_hours`
(the house's grid kWh per hour, and when it draws) and `batt_times` (when the battery covers
the house).

## Comfort

A room or heater with a comfort band can bank energy in a free or cheap
hour. The planner learns how fast the room drifts and how fast it heats.
It plans a run only when it has enough data. Without data it plans
nothing.

## Battery arbitrage advice

The planner also shows whether buying cheap energy into the battery and
selling it in an expensive hour would pay. This is advice only. It does not
change the battery. See [Battery export arbitrage](BATTERY_EXPORT_ARBITRAGE.md).

## Settings a user changes

| Setting | Where |
|---|---|
| Plan drives devices | Plan screen |
| Car: **Charge by** time and charge mode | Devices › car |
| Load goal: **At least** and **Up to** | Devices › load |
| Battery reserve | Devices › battery |
| Night start: minutes after sunset (default 30, 0 to 400) | System › Notifications and more |

## Fail-safe rules

The plan does not turn off the safety rules. These stay active:

- The car's deadline and minimum charge.
- The battery reserve.
- The peak limit: a peak shed wins over any planned window.
- Minimum run and pause times.

The plan is trusted only when all of these are true: the plan is new, the
switch is on, the current time is inside the plan's night, and the need
has the verdict `fits`. Otherwise the device uses its own rules.
