# Loads charge before the battery (#576)

*Added in 1.7.5. Opt-in, default OFF. Design:
`docs/superpowers/specs/2026-07-10-load-priority-above-battery-design.md`.*

By default, home-battery charging absorbs surplus solar **before** it becomes
grid export — so on a self-consumption inverter the battery silently outranks
your discretionary loads. If you'd rather run a pool pump, a heater, or another
surplus-managed load from that solar *instead of* topping the battery, this
setting flips the priority the way Victron systems do.

## What it does

When enabled **and** the battery is at or above the reserve zone
(`Battery priority SOC`, default 30 %), power that would otherwise **charge**
the battery is offered to your surplus loads first, in their normal priority
order. The battery becomes the **sink**: it absorbs whatever the loads don't
take. Nothing is force-commanded on the battery — on a self-consumption inverter
it simply charges from the leftover solar.

Below the reserve zone the battery still fills first, so your evening reserve is
protected.

## Turning it on

Settings → Devices & Services → SEM → **Configure** → the battery settings step →
**"Loads charge before the battery"**. Off by default; turning it off restores
the previous behavior exactly.

The reserve floor is the existing **`Battery priority SOC`** slider — no new
knob. Raise it to keep more battery headroom before loads start reclaiming;
lower it to let loads reclaim sooner.

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
| Any solar, SOC 25 % (below the zone) | battery fills first — loads see export-leftover only (unchanged) |
| Force-charge / scheduled / arbitrage battery charge active | honored — **no reclaim** |

## Guards & interactions

- **Reserve floor.** Below `Battery priority SOC`, behavior is byte-identical to
  today. This protects the evening.
- **Explicit battery commands win.** A force-charge, a scheduled night charge, or
  battery→grid arbitrage is never reclaimed — the load yields to it.
- **No oscillation.** The pool is `solar − home` (invariant to how it's shared
  out), and a device's own draw is added back to the signal, so consuming from
  the pool shrinks it by exactly what was consumed and converges. Existing
  median/EMA smoothing and anti-flicker guard the residual jitter.

## Scope

This first release covers **generic surplus loads** (switches / heaters / pumps
in `surplus` mode). Extending the same reserve-zone priority to **EV charging**
is a separate, carefully-specced follow-up — the EV already reclaims battery
charge above `auto_start_soc` via a forecast-scaled redirect, so lowering *that*
gate (rather than adding a second reclaim) is the correct EV mechanism. See the
design spec's Path B build-note.
