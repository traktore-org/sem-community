# Loads, the battery and the priority list

SEM runs your surplus loads (pool pump, heater, hot water, heat pump) on solar.
Their order in the priority list decides who gets the sun and the battery
first. The list is on the **Devices** screen: drag a card, or use **Reorder**.

## The battery is in the list

The home battery is a row in the same list as the EV charger and your loads.
Its position is the only control it has.

- A load **above** the battery takes the battery's charge power first.
- A load **below** the battery yields. The battery charges first.
- Default order: **EV → battery → loads**. Loads wait for the battery until you
  drag one above it.

**Below this the battery fills first** (default 30 %, on the battery card on
**Devices**) is an absolute floor. Below it the battery charges first,
wherever it sits in the list. This keeps the evening reserve.

## How the walk works

SEM walks the list from the top. Each device gets its share if enough surplus
is left.

| Device | Minimum | Uses |
|---|---|---|
| Switch or heater (on/off) | Its rated power, all or nothing | Its rating to start. Once running, what its power sensor reads |
| Battery (the sink) | 0 | Whatever is left |

- A running load counts what it draws, not its rating. If a heater lowers its
  own power, the spare goes to the next load.
- **Rating.** If you enter a rated power, SEM uses it. Otherwise SEM uses 1 kW
  until the load runs once, then uses the measured draw. The rating can go
  down or up. After that it only rises, to the largest draw seen.
- A load with no power sensor keeps the 1 kW placeholder. SEM does not start
  such a load on a small surplus.

**Requires.** A load can require another, for example a towel rail that runs
only when the pool pump runs. A required device sits directly below its parent
and moves with it. SEM refuses a link that makes a loop.

**EV row.** The EV row shows its minimum power as its rating. While charging, it
shows the live draw.

## Who spends the battery and the sun

The battery can discharge into the house and the cars. SEM uses one allowance,
spent in list order.

- A device above a charger gets its share before the charger. The next device
  down uses solar and grid.
- Only devices that allow battery help take part. A load takes part when its
  Mode includes battery help. A charger takes part unless you turn off
  *Battery may charge the car* for it.
- A load set to *Finish overnight from: Battery* reserves nothing against a
  car. It runs below the Buffer SOC, where the car may not go.
- Solar works the same way. A load above a charger gets its share of the sun
  first, so the charger may get less sun than before.
- A running load keeps its battery reservation, but not its sun reservation.
  Without that, a battery-backed load would switch off and on again.

### Mode and battery mode

| Battery mode | Effect on the list |
|---|---|
| Auto or self-consumption, above the reserve | Passive. Your position counts |
| Auto or self-consumption, below the reserve | Moves to the top |
| Force charge | Moves to the top. Loads and the EV yield |
| Force discharge or arbitrage | Leaves the list. It feeds the grid, not the house |

## Load modes

Each load has a **Mode** on the **Devices** screen.

| Mode | What SEM does |
|---|---|
| **Off** | Monitors only. SEM never switches it, and the peak guard never sheds it |
| **Peak only** | Your automations run it. SEM never starts it. It switches it off while the grid peak is at risk, and on again when the peak falls |
| **SEM runs it** | Starts on spare sun. Stops when the house buys power from the grid for it, or when the sun makes less than the load draws. It never starts on the battery |
| **SEM runs it, battery may help** | As *SEM runs it*. By day the battery may help, down to the Buffer SOC (or tonight's floor if that is higher). The help starts only when at least the **Spare sun before the battery helps** (1200 W default) goes to the grid |

- A load that SEM started on sun stops when the sun stops, even if its power
  sensor reads 0 W. A load you switched on yourself stays on.
- **Evening.** A running *SEM runs it* load keeps going while the sun makes at
  least what the load draws. If the house needs more, the battery covers the
  gap and the grid reads 0 W. SEM does not stop the load in that case.
- **Battery help while the battery charges.** Spare sun is measured at the grid
  meter. While the battery still charges from spare sun, little reaches the
  grid. So the battery help waits until the battery is full.
- Battery help does not start a load at night. That is the *Finish overnight*
  setting.

## Minimum and maximum run time

Each load has a daily run-time slider with two handles.

- **Minimum** is a floor, not a stop. Below it SEM may buy power for the load:
  from the battery or the cheap grid. Once it is met, free surplus can keep the
  load on up to the **Maximum**. Set 0 for no target.
- **Maximum** is the hard stop for the day. *Uncapped* means "run as long as the
  sun lasts". If the load runs when it hits the cap, SEM switches it off.
- The day counter resets after sunrise, not at midnight. A battery load is not
  reset in the night and drained again.

If both handles land on the same spot, use the split button to move them apart.

## Anti-cycling: minimum run and minimum pause

**Min run / pause** (minutes) stops a load from flapping on a passing cloud.
Once on, it stays on for the minimum run. Once off, it stays off for the
minimum pause. The window range is 0 to 120 min.

These apply only to the two *SEM runs it* modes. A hot water tank stops at its
top or at your stop, even inside its minimum run.

| Device | Minimum run | Minimum pause |
|---|---|---|
| Switch load (pump, heater, plug) | 5 min | 5 min |
| Hot water controller | 10 min | 5 min |
| Heat pump controller | 10 min | 5 min |

A value you type is kept and applied again after every restart.

## Finish overnight from

When the sun is gone and the day target is not met, **Finish overnight from**
decides what finishes the runtime. It applies to both *SEM runs it* modes.

| Choice | What happens |
|---|---|
| **Off** | Nothing. The load waits for the sun. It may miss its target on a dark day |
| **Battery** | At night, while runtime is still owed, it runs on the home battery. It stops at the reserve (*Below this the battery fills first*, default 30 %) and does not start again below it. It stops at daybreak |
| **Grid** | While runtime is owed and the rest of the day is too short for it, it runs on the grid in cheap-price hours only. It needs a tariff with price levels. It never runs in a morning the sun can still cover |

- The mode sets the daytime source. This setting sets the no-sun source.
- Switching the picker also stops a load that runs on the source you moved
  away from. You do not have to wait for the reserve or the cheap window to end.

## Stop condition

A load can stop early when a sensor reaches a value. Set **Stop when** with
the sensor picker. Examples: tank level full, water at 28 °C, car at 80 %.
Clear it with the picker's clear button.

## Why there are no deadlines

SEM does not force a grid top-up by a deadline. A high-priority car can sit
at the peak limit for hours. A deadline would then push a heat pump to import
from the grid all at once. Other HEMS tools throttle by priority in the same
way. Use **Finish overnight from** instead. It finishes the runtime from the
battery or the cheap grid, and never forces an import.

## A phase over its limit

On a three-phase house, each phase can have its own limit. With enforcement on,
SEM keeps its chargers inside what each phase has left. If stopping the car is
not enough, SEM also sheds loads. The phase guard reads the phases each
coordinator cycle, every 10 seconds by default.

**Set the phase of each load.** The row has a **Phase** select: **L1**, **L2**,
**L3**, **3-phase** or **unknown** (the default). A charger's phase is measured
from its own current.

**Shed order** on a cycle where a phase is over its limit:

1. **Chargers first.** The guard stops them as soon as a phase is over. If a
   car was charging, loads are asked only if the phase is still over on the
   next cycle.
2. **Loads on that phase**, or three-phase loads, highest priority number first.
   A load on that line frees all of its current. A three-phase load frees a
   third on each line.
3. **Loads of unknown phase** after those, one per cycle. SEM lets the meter
   answer before it takes the next.

**Never shed:** critical loads, loads you keep hands-off, loads in *Off* mode,
and the chargers (the guard handles them). Load shedding needs load management
on. Without it, the guard acts on chargers only.

**When loads come back.** Not when the phase is merely under its limit. When the
guard's recovery latch clears: every phase back at the recovery margin (2 A) for
3 cycles. Then the loads return one at a time, so they do not flap.

**After a restart,** SEM waits for the meter's phase readings to settle before
it sends a notice. If a reading is still missing, you get one. In watch-only
mode, SEM says the reading is unavailable. It does not say a phase is over.

SEM never switches the grid operator's relay (SG-Ready state 1, *EVU-Sperre*) of
a heat pump. The phase guard switches loads only.
