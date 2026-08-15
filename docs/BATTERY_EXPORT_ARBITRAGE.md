# Battery export arbitrage — selling stored energy when export is high

> ## 🔒 Wired, tested, and OFF by default (v2.0)
>
> The selling machinery is fully built into the energy plan (the same
> one-gate that schedules EV and load windows) and covered by a dedicated
> scenario test matrix — but **every default keeps it dormant** (#533): the
> global toggle ships off, and the UI opt-ins are still held back until the
> feature has soaked. Nothing sells unless you deliberately turn it on.

On a dynamic / spot tariff (EPEX, Tibber, Nord Pool, aWATTar, …) the price you
are paid to export swings hard — often **negative** (you pay to export) and
sometimes **far above** the cost of charging. SEM's battery charge scheduler
already buys low (it charges in the cheapest hours). **Export arbitrage** adds
the other half of *buy low, sell high*: it discharges the home battery **to the
grid** when the export price beats the cost of recharging it later.

> **Opt-in. Default OFF.** SEM never force-discharges your battery unless you
> turn this on.

> ## ⚠️ Check your grid connection agreement first
>
> Some grid operators and feed-in schemes **prohibit exporting stored
> (battery) energy** — the feed-in contract covers PV production only, and
> exporting from the battery can violate the connection agreement or void a
> feed-in tariff. **If that applies to you: leave arbitrage OFF and do not
> use the `Force discharge` battery mode** — both deliberately push battery
> energy to the grid. Everything else in SEM (charge scheduling,
> self-consumption, peak shaving, EV solar charging) never exports your
> battery and is unaffected by such restrictions.
>
> The `sensor.sem_flow_battery_to_grid_power` / `…_energy` pair (v2.0)
> shows exactly how much battery energy went to the grid — on a restricted
> install it is also your evidence that the answer is **zero**.

## What the mode does — one day in two pictures

The price curve decides everything. SEM charges the battery in the cheapest
night hours (that part is the normal charge scheduler) and sells stored
energy back to the grid only inside the **evening price peak**, and only when
the peak out-earns refilling the battery later:

```text
 €/kWh   (day-ahead spot price)
 0.45 ┤                                            ╭───╮
 0.40 ┤                                          ╭─╯▒▒▒╰╮      ▒ SELL block
 0.35 ┤                                        ╭─╯▒▒▒▒▒▒╰╮       (18–21 h,
 0.30 ┤─╮                                    ╭─╯▒▒▒▒▒▒▒▒▒╰─╮      price peak)
 0.25 ┤ ╰─╮                               ╭──╯             ╰───
 0.20 ┤   ╰──╮                         ╭──╯
 0.15 ┤      ╰──╮                  ╭───╯
 0.10 ┤         ╰──╮███████╭───────╯          █ CHARGE block
 0.05 ┤            ╰███████╯                    (02–05 h, price valley)
      └─┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬──→
        00  02  04  06  08  10  12  14  16  18  20  22   hour
```

What the battery's state of charge does across that same day:

```text
 SOC %
 100 ┤                 ╭──────────────────────╮
  80 ┤             ╭───╯   (solar tops up      ╰─╮
  60 ┤         ╭───╯        during the day)      ╰──╮   selling STOPS at the
  50 ┤─────────╯                                    ╰────────  arbitrage
     ┤                                                         reserve (50 %)
  20 ┤ ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  backup reserve (20 %)
     └─┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬──→
       00  02  04  06  08  10  12  14  16  18  20  22   hour
```

Three things the pictures show:

- **The sell only happens inside a planned block.** The energy plan packs
  the sell window from the price curve the evening before, next to the EV and
  load windows, so everything competes for the same night under the same
  peak-load cap. No block on the plan — no selling, whatever the live price
  does.
- **Two reserve floors, and the higher one wins.** Your **backup reserve**
  (the emergency capacity, default 20 %) is never touched by anything. The
  **arbitrage reserve** (default 50 %) is the deeper floor selling stops at —
  so an evening sale keeps half the battery for the normal evening household
  use that follows it.
- **The sale must beat the refill.** Selling at 0.40 only makes sense because
  tomorrow's valley refills at ~0.10. If the spread doesn't cover round-trip
  losses (~10 %) plus battery wear, the block is simply not planned.

### The three questions every sell answers

| Question | Who answers it | What it checks |
|---|---|---|
| **WHEN?** | The stamped energy plan | Is a sell block open *right now*? (Stale or missing plan = closed.) |
| **WHETHER?** | Live economics, re-checked every cycle | Does the export price *still* beat recharge cost + wear? A price that moved kills the sale mid-block. |
| **MAY?** | Your settings | Global toggle, this battery's mode (`Self-consumption` never sells), both reserve floors, and the night-actuation kill-switch. |

All three must say yes, every ~10 s cycle. Any single "no" stops the
discharge cleanly on the next cycle.

![Battery card showing the Selling to grid state](screenshots/battery-export-arbitrage-selling.png)

*The Battery card shows a distinct gold **“Selling to grid”** state with the live
export price while SEM is exporting the battery.*

---

## When SEM decides to sell

It is the mirror of the scheduler's charge-on-cheap decision, using the **same
economics**, so it can never sell at a loss. Every cycle, while arbitrage is on
and no charge is planned, SEM sells only when **all** of these hold:

1. **A sell block on the energy plan is open right now** — the plan owns
   the WHEN (see the pictures above).
2. **Export price ≥ your “min export price to sell”** — worth cycling the
   battery for.
3. **SOC > both reserve floors** — the higher of your backup reserve and the
   arbitrage reserve. Your backup capacity is never sold, and the arbitrage
   reserve keeps a working charge for the evening household. An unavailable
   SOC sensor **holds** — SEM never discharges blind.
4. **The sale beats recharging it later:**

   ```
   export_now  >  cheapest_upcoming_import ÷ round-trip_efficiency  +  battery_cycle_cost
   ```

   i.e. selling now must out-earn buying the same kWh back later, after
   round-trip losses (~10 %) and battery wear.

If any condition fails, the battery stays in its normal mode.

## The economics

At the same moment a dynamic tariff can pay €0.45/kWh to export while the
cheapest overnight refill is €0.10/kWh:

| | €/kWh |
|---|---|
| Export price (evening peak) | 0.45 |
| Recharge cost (spot 0.10 ÷ 0.90 efficiency) | 0.111 |
| Battery wear (≈ €8k / 10 kWh / 6000 cycles) | 0.067 |
| **Net profit per kWh sold** | **≈ 0.27** |

Selling a few kWh down to the reserve on such an evening captures roughly
**€1–2 per event**, on the order of **€100–300/year** on a typical home battery —
*on top of* the self-consumption savings the battery already provides. The win
grows with how volatile your tariff is, and matters more as net-metering
(e.g. the Dutch *salderingsregeling*) is phased out.

It is structurally safe: the break-even gate (including `battery_cycle_cost`)
stops it from cycling the battery for a spread that doesn't cover the wear, and
it never touches your reserve SOC.

## Enabling it

Configuration tab → **Tariff & pricing** (visible only on a *dynamic* tariff):

![Battery export arbitrage settings](screenshots/battery-export-arbitrage-config.png)

| Setting | What it does |
|---|---|
| **Sell battery to grid on high export** | Master on/off. Default off. |
| **Min export price to sell** | Floor price (per kWh) worth cycling the battery for. |
| **Arbitrage reserve SOC** | Never discharge to grid below this SOC — your backup reserve. |
| **Forcible-discharge power entity** | The `number.*` entity that sets your battery's forced discharge-to-grid power (see below). |

### Battery brand support

- **Huawei SUN2000 + LUNA2000** — SEM uses the *huawei_solar*
  **`forcible_discharge_soc` service** (Huawei has **no** forcible-discharge
  *number* entity). It discharges to your **reserve SOC**, which the inverter
  self-terminates at — so the reserve is a true floor even if a stop is delayed.
  Requires the *huawei_solar* integration; SEM auto-detects it and uses the
  battery device. Verified live on a real LUNA2000.
- **GoodWe, Victron, SolaX, Growatt, Sessy, Powerwall, …** — the **generic**
  path writes the discharge power to a **number entity you configure** (the
  integration's discharge-power setpoint, or a small `template`/`script`-backed
  `number` / `input_number` — SEM drives whichever domain you point it at).

If no forcible-discharge path is available (no Huawei service and no number
entity), the decision is **safely dropped** — SEM logs that it *would* sell but
takes no action.

> **Huawei note (anti-block):** the LUNA2000 locks up if it gets a stop plus a
> second Modbus write in the same ~10 s cycle. SEM issues **one** command per
> transition and defers the rest to the next cycle, and re-issues a dropped stop
> automatically. Because mode decisions are stable (a mode stays until you change
> it), normal operation never toggles faster than the inverter can keep up.

### Per-battery control (multi-battery installs)

On installs with **two or more batteries** (e.g. Growatt + Sessy, or two
LUNA2000s) each battery is controlled independently from the **Battery card**:

| Mode | What it does |
|---|---|
| **Auto** | Today's behaviour — scheduler / arbitrage / protection decide. |
| **Self-consumption only** | Charge + power the house, but **never** sell to grid. |
| **Allow arbitrage** | Sell to grid when profitable, even with the global toggle off. |
| **Force charge** | Charge to full now. |
| **Force discharge** | Sell to grid now, down to the **Reserve SOC**. |

Each battery also has its own **Reserve SOC** floor (never discharged below it),
and — for multi-battery installs — its own **forcible-discharge entity picker**
in Configuration → Tariff. One battery can sell while a sibling holds.

## Turning it off

- **Toggle off** in Configuration → Tariff & pricing. The entire path is gated
  on it; nothing is force-discharged when off.
- Flip it off **mid-sale** and the next ~10 s cycle stops cleanly — the next
  battery command zeroes the forcible-discharge (the modes are mutually
  exclusive), so the battery never silently keeps selling.
- **Softer dials** short of off: raise the **reserve SOC** (sell only a thin
  slice), raise the **min export price** (sell only at genuine peaks), or simply
  leave the discharge entity unset.

## Notes & limits

- **Negative export is a cost.** SEM reads the *signed* export price, so a
  negative spot price is correctly treated as a cost (not a credit) for revenue,
  ROI, and the never-sell-at-a-loss gate.
- **Market-dependent.** In a flat / low-volatility market the break-even gate
  simply won't fire — there's nothing to gain, so SEM does nothing.
- **Hardware-dependent.** Your battery must accept a forced discharge-to-grid
  command via a controllable number entity.
- **Curtailment on negative export** (turning down solar when export is negative)
  needs inverter export-limit control and is a separate, future enhancement.

---

## Current state on the 2.0 line (maintainers)

The path is **fully wired through the one-gate plan** (#638 C6) and pinned by
a dedicated scenario matrix (`tests/test_638_c6_arbitrage_sell.py` — mode ×
gate × floor, plus the economics honest-bounds suite). What the v1.7.3
checklist asked for is done:

- ✅ **Plan-gated WHEN** — `arbitrage_sell_gate` reads the stamped plan's
  `discharge_blocks` under the same trust rule as every gate (stale stamp =
  closed); power is capped at the block-implied watts (avoided-import, never
  export-at-max), and the kill-switch gates the whole computation (#758).
- ✅ **N× over-export fixed** — the pipeline splits the block power across
  the fleet (`effective_battery_count`, the #531/#691 treatment); the
  `_any_allow_arb=False` v1.7.3 hardcode is gone (per-battery opt-in scan is
  real again).
- ✅ **Both reserve floors bind, the higher wins** — the user's backup
  reserve AND the verdict's `arbitrage_reserve_soc`; the actuator is handed
  the higher floor (hardware end-SOC / setpoint batteries enforce it on
  their own between cycles). An unavailable SOC holds, never sells blind
  (#531).
- ✅ **Clean brand-agnostic stop** — `STOP_FORCE_DISCHARGE` routed by
  `from_arbitrage`; a block closing mid-sell falls through to NORMAL, whose
  idempotent `command_normal()` zeroes the setpoint (#538).

Still deliberately held back (the #533 decision):

1. `allow_arbitrage` stays **out of the battery-mode selector** and the
   global toggle has **no config-flow section** — enabling today is the
   expert route (`solar_energy_management.set_option` →
   `battery_grid_arbitrage_enabled: true`, batteries in `auto` mode).
2. Migration v14 forces the toggle off **once** on upgrade from ≤ v13; a
   deliberate re-enable afterwards sticks.
3. Before re-exposing the UI: a live two-battery arbitrage night on the sim
   rig — **never a first soak on the shared PROD battery** (#532 was a real
   LUNA2000 drain).
