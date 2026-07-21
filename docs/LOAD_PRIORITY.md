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

## The EV and every device honour the same list (1.7.5-beta.3, #576 Phase 2)

The priority list is now the **single control for everything** — not just the loads
and the battery:

- **The EV charger is a first-class row**, keyed by its own control id. Above the
  battery → it reclaims the battery-charge power (charges first, above the reserve
  zone); below → it yields. This replaced the old fixed 90 % SOC gate. Your list
  position also drives the **multi-charger distribution order** (the old
  `ev_surplus_priority` is now just the seeded default).
- **Every device type participates by position** — surplus switches, modulating
  loads, climate/AC, the heat pump (SG-Ready) and hot water are all walked by their
  list slot and share the reclaimed battery-charge power the same way.
- **Heat pump & hot water are draggable rows too (v1.7.5-beta.11, #602)** — they
  appear with their own glyphs (heat-pump / water-boiler) and their surplus
  priority is their list position, seeded once from the old
  `heat_pump_priority` / `hot_water_priority` values on upgrade. The separate
  priority sliders were retired; the legacy EV flags
  (`ev_load_priority`, `ev_shed_priority`, `ev_priority_over_battery`) are
  cleaned from stored configs by the v16 schema migration (#604).
- **Default order is EV → battery → loads.** Loads yield to battery charging until
  you drag one above the battery; the `Battery priority SOC` reserve floor stays an
  absolute override (below it, the battery charges first regardless of position).

### How position interacts with battery mode

| Battery mode | Effect |
|---|---|
| `auto` / `self_consumption`, SOC ≥ reserve | passive sink — your dragged position governs |
| `auto` / `self_consumption`, SOC < reserve | jumps to the top (reserve floor) |
| `force_charge` | jumps to the top — commanded charge, loads/EV yield |
| `force_discharge` / arbitrage | leaves the walk — it's feeding, not drawing |

### "Requires" links (dependency chains)

A device can **require** another (the "Requires" link on its Configure dialog): a
towel rail that should only run when the pool pump does, for example. A required
child always sits **immediately below its parent** in the list and moves with it —
drag the parent and the child follows, so the chain never separates. The link is
persisted, so it survives a drag, the periodic re-discovery, and a restart.

SEM **rejects a link that would form a loop** — a device can't require itself, and
it can't require something that (directly or transitively) already requires it.
A rejected link is logged and the previous link is kept, so two devices can never
deadlock each other waiting to start.

### The EV row's rating

The EV charger row shows its **minimum** power (min amps × phases × voltage) as its
rating — the surplus *threshold* to start charging — not the theoretical 32 A × 3-phase
maximum (which read as "the EV draws 22 kW"). While charging it shows the live draw;
idle, it shows that start threshold.

### Seeing the plan

The layered trace (`diagnose`, `section: trace`) reports each device's list role
— e.g. *"sink at list position 2"*, *"charging first — below reserve"* — so you can
see who charges before whom each cycle. **Today's Plan** shows the pool pump / heat
pump / hot water in the same forward timeline as the battery and EV.

---

# Daily runtime goals for a load (#620)

*Added in 1.7.5. Design:
`docs/superpowers/specs/2026-07-20-620-device-goal-model-design.md`.*

The priority list decides **who gets surplus first**; the per-device **goal
editor** (the 🎯 target button on a load's row) decides **how much that load
should run and from what source**. It's the load-side analogue of the EV
charge-target: continuous priority allocation bounded by two hard ceilings — the
**grid peak limit** and the battery **reserve SoC** — and deliberately **no
device deadlines** (see "Why no deadlines" below).

## Mode — how SEM drives the load

Each load's row has a **Mode** selector:

| Mode | What SEM does |
|---|---|
| **Off** | Monitor only — SEM never turns it on or off. |
| **Peak only** | Your automations run it; SEM only *sheds* it to protect the grid peak. |
| **Solar only** | Runs on PV surplus; never force-imports and never touches the battery. |
| **Solar + battery** | Runs on PV surplus **and** lets the home battery assist above the buffer (Tier 1); optionally down to the reserve overnight (Tier 2). |

## Min / Max runtime (the dual slider)

Under the 🎯 target button, a **dual-handle slider** sets the daily runtime
window (shown only in the two solar modes):

- **Minimum** (green handle) — the daily target. SEM keeps the load running
  until it has accrued this much, then **stops it for the rest of the day**
  (the *daily-target-met* stop). Set to 0 for "no target — just take surplus".
- **Maximum** (orange handle) — a **hard cap**. The load **never runs past this
  in a day**, even if the minimum isn't met and surplus is available. Full-scale
  = *Uncapped*. The cap is **persisted across restarts** and **overrides the
  minimum** — if a load is running when it hits the cap, SEM switches it off.

If both handles land on the same spot, tap the **split button** (⬍) that appears
to nudge them apart so each is grabbable again.

The counter resets **after sunrise**, not at midnight — so a battery-eligible
load isn't reset mid-night and re-drained before the new day's surplus arrives.

## The two battery tiers ("Solar + battery" mode)

| Tier | When | Source | Opt-in |
|---|---|---|---|
| **Tier 1 — daytime assist** | Solar surplus present, battery **above the Buffer SoC** | The above-buffer surplus that would otherwise export — mirrors the EV assist (Solar Gate, `battery_assist_min_surplus`) | Automatic in Solar+battery mode |
| **Tier 2 — overnight** | No surplus, battery **above the Reserve SoC** | Stored house energy, down to the hard reserve floor | The **"Use battery overnight"** toggle |

Tier 2 lets a load **finish its remaining runtime overnight off the battery**
instead of missing the target on a short solar day. It stops at the reserve floor
(`Battery priority SOC`, default 30 %) — the battery is never drained past it.

## Optional stop condition

Any load can also **end its run early** when a sensor crosses a value — pick the
sensor with the **entity search** (the *Stop when ≥* picker: e.g. tank-level ≥
full, water-temp ≥ 28 °C, car SOC ≥ 80 %). Clear it with the picker's ✕.

## Why no deadlines (and no forced grid top-up)

The originally-requested "guarantee the minimum by a deadline using grid" was
**deliberately not built**. In winter, a high-priority load (the EV) can sit on
the peak ceiling for hours, so a *deadline* would force lower-priority devices
(the heat pump) to grid-import all at once against that ceiling — the exact
contention we avoid. Field research (evcc, Solarmanager) confirmed neither ships
generic-device deadlines; both throttle continuously by priority. #620 instead
gives you the **battery tiers** to finish overnight from stored energy, and the
`cheap_hours` top-up policy (heat pump / hot water) for tariff-window grid top-up
— never a hard forced-import deadline.
