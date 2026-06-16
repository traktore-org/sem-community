# Battery export arbitrage — selling stored energy when export is high

On a dynamic / spot tariff (EPEX, Tibber, Nord Pool, aWATTar, …) the price you
are paid to export swings hard — often **negative** (you pay to export) and
sometimes **far above** the cost of charging. SEM's battery charge scheduler
already buys low (it charges in the cheapest hours). **Export arbitrage** adds
the other half of *buy low, sell high*: it discharges the home battery **to the
grid** when the export price beats the cost of recharging it later.

> **Opt-in. Default OFF.** SEM never force-discharges your battery unless you
> turn this on.

![Battery card showing the Selling to grid state](screenshots/battery-export-arbitrage-selling.png)

*The Battery card shows a distinct gold **“Selling to grid”** state with the live
export price while SEM is exporting the battery.*

---

## When SEM decides to sell

It is the mirror of the scheduler's charge-on-cheap decision, using the **same
economics**, so it can never sell at a loss. Every cycle, while arbitrage is on
and no charge is planned, SEM sells only when **all** of these hold:

1. **Export price ≥ your “min export price to sell”** — worth cycling the
   battery for.
2. **SOC > your reserve floor** — your backup capacity is never sold.
3. **The sale beats recharging it later:**

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

The forced-discharge command is **brand-agnostic** — SEM writes the discharge
power to the **number entity you configure**. It works with any battery whose
integration exposes such an entity:

- **Huawei LUNA2000** — the *huawei_solar* “Forcible discharge power” number.
- **GoodWe**, and the **generic** path that covers **Victron, SolaX, Growatt,
  Sessy, Powerwall, …** — point it at that integration's discharge-power
  setpoint number (or a small `template`/`script`-backed `number`).

If no forcible-discharge entity is configured, the decision is **safely
dropped** — SEM logs that it *would* sell but takes no action.

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
