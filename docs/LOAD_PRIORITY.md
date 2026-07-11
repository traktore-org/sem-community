# Loads charge before the battery (#576)

*Added in 1.7.5. Design:
`docs/superpowers/specs/2026-07-10-load-priority-above-battery-design.md`.*

Your surplus-managed loads (pool pump, heaters, …) now outrank home-battery
charging above the reserve zone — the Victron-style priority order. This isn't a
mode you turn on; it's simply how device priority relates to the battery: the
battery is the **sink** at the bottom of the priority walk.

## What it does

Above the reserve zone (`Battery priority SOC`, default 30 %), power that would
otherwise **charge** the battery is added to the surplus pool, and SEM shares it
across your surplus devices in their normal priority order. Whatever the loads
don't take flows to the battery — on a self-consumption inverter the battery
simply charges from the leftover solar (nothing is force-commanded on it).

Below the reserve zone the battery still fills first, so your evening reserve is
protected.

## Set the order by dragging the battery

The **home battery appears as a device in the Control-tab priority list** (the
"Drag to reorder" card), right alongside the EV charger and your loads. Its
position is the control:

- Loads **above** the battery **reclaim** its charge power (they charge first).
- Loads **below** the battery **yield** — the battery charges first.

Drag the battery up to protect it (fewer loads outrank it); drag it down to let
more loads charge before it. By default it sits at the **bottom**, so every
surplus load outranks it until you move it. The battery row shows its SOC and
current charge power; it has no on/off or mode selector — its only control is
where you put it.

The **`Battery priority SOC`** slider (Settings → SEM → Configure → battery step)
is still an **absolute floor**: below it the battery jumps to the top and charges
first no matter where you dragged it, protecting your evening reserve.

## How the priority walk works

The allocatable pool becomes the **pre-battery** surplus. SEM walks your surplus
devices by priority and gives each its share if enough is available:

| Device | "Minimum" | Consumes |
|---|---|---|
| Heater / switch (discrete) | its rated power — all-or-nothing | exactly its rating, or nothing |
| Battery (the sink) | 0 | whatever is left |

A discrete load only switches on when the available surplus meets its full rated
power; otherwise it yields and that power flows to the battery.

## Worked examples

Reserve zone = 30 %, two 1 kW heaters at priorities 2 and 3.

| Situation | Result |
|---|---|
| 3.5 kW spare solar, SOC 85 % | both heaters ON (2 kW), battery absorbs the remaining ~1.5 kW |
| 0.8 kW spare, one 1 kW heater, SOC 85 % | heater stays OFF (0.8 < 1.0 kW), 0.8 kW → battery |
| Any solar, SOC 25 % (below the zone) | battery fills first — loads see export-leftover only |
| Force-charge / scheduled / arbitrage battery charge active | honored — **no reclaim** |

## Guards & interactions

- **Reserve floor.** Below `Battery priority SOC`, behavior is identical to
  before. This protects the evening.
- **Explicit battery commands win.** A force-charge, a scheduled night charge, or
  battery→grid arbitrage is never reclaimed — the load yields to it.
- **No oscillation.** The pool is `solar − home` (invariant to how it's shared
  out), and a device's own draw is added back to the signal, so consuming from
  the pool shrinks it by exactly what was consumed and converges. Existing
  median/EMA smoothing and anti-flicker guard the residual jitter.

## Scope

This covers **generic surplus loads** (switches / heaters / pumps in `surplus`
mode). Extending the same reserve-zone priority to **EV charging** is a separate,
carefully-specced follow-up — the EV already reclaims battery charge above
`auto_start_soc` via a forecast-scaled redirect, so lowering *that* gate (rather
than adding a second reclaim) is the correct EV mechanism. See the design spec's
Path B build-note.
