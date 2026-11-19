# Tariff models

SEM's price level (`sensor.sem_tariff_price_level`) answers one question:
is this hour cheaper or dearer than the others? A level needs two prices
that differ. If there is nothing to compare, SEM says so.

## What each model gets

| Model | What SEM compares | Level you get |
|---|---|---|
| **Flat / single rate** | Nothing. There is one price. | *No price difference* (`flat`) |
| **HT/NT (two rates, by clock)** | The two rates, on a day that has both | Cheap in NT, normal in HT. A weekend has one price, so no level. |
| **Multi-tier time-of-use** | The distinct tier prices | The tier's own level |
| **Dynamic / spot** (Nord Pool, Tibber, EPEX, ENTSO-e, aWATTar) | Today's price curve, by percentile | The five levels. *No prices available* (`no_prices`) if the curve is missing or too short. |
| **Critical peak** | Not modelled | See [limits](#not-modelled) |
| **Block by consumption** | Not modelled | See [limits](#not-modelled) |

The five levels are very cheap, cheap, normal, expensive and very expensive.
A negative price is always its own level.

### Not modelled

- **Critical peak events.** SEM does not know an event is coming. Event hours
  show as expensive once they are in the price curve.
- **Block tariffs.** The price depends on this month's total kWh, not on the
  hour. SEM classes the hours by their time structure only. Savings use the rate
  the price entity reports.

Neither is dangerous: SEM does not act on a level it does not have.

## Flat is measured relative to the day

A day is flat when its spread is less than 0.5 % of the day's average. This
works for any currency. A 1 ct HT/NT split on a 30 ct tariff is 3.3 %, so it
counts.

## Why there is no level, and what to do

| Sensor state | Card label | Meaning | What to do |
|---|---|---|---|
| `flat` | No price difference | The hours do not differ. | Nothing. This is the right answer for a flat contract. |
| `no_prices` | No prices available | Nothing to compare. The price entity is missing, empty or too short. | Check the price entity. |

The `classifier_path` attribute says how the level was reached.

## Negative prices

A negative price is handled on its own. It is not compared with other hours.

- The export guard closes on the export rate's own sign.
- A negative import price allows the battery to force-charge from the grid.

A negative hour is one you are paid for, so it always shows as negative, even
if the price entity publishes only the current state.

## ENTSO-e

Choose **Dynamic** and leave the price entity empty. SEM finds the
[ENTSO-e integration](https://github.com/JaccoR/hass-entso-e) and reads
the current price and the day-ahead curve.

- Set ENTSO-e's energy unit to kWh. SEM does not read per-MWh prices.
- ENTSO-e gives the wholesale price only: no tax, no grid fee, no margin.
  Add these in one place only, or they count twice:
  - in ENTSO-e's own setup (price modifier and VAT), or
  - in SEM's tax fields, with **price basis** set to **Spot price (no taxes)**
    (the options flow calls it **What your import price includes**).

## Tax is never added twice

**price basis** says what your price already has. It is a row in **How I pay** on **System**. The options flow calls it **What your import price includes**.

| Setting | Use it when | SEM adds |
|---|---|---|
| **All-in (taxes included)** (default) | A rate from your bill, Tibber, any price that already has tax | Nothing |
| **Spot price incl. VAT** | A market price with VAT, no energy tax | Markup and energy tax, each with VAT |
| **Spot price (no taxes)** | Nord Pool raw, ENTSO-e raw | Markup, energy tax, and VAT on the sum |

Markup, energy tax and VAT are only added to a spot price. SEM refuses them
next to All-in. With every field at 0, the prices are unchanged.

The preset **Netherlands from 2027** fills energy tax and 21 % VAT and sets
the price to **Spot price (no taxes)**. Check the tax rate against your bill.
The preset **None** adds nothing.

Tax moves every hour the same way, so the level (cheap, dear) does not change.

## Feed-in fee

| Model | What SEM uses | What the fees sensor counts |
|---|---|---|
| **Per kWh** | The fee | kWh exported × fee |
| **Tiers by kWh per year** | The fee of the tier this year's export is in | kWh × that fee |
| **Fixed per month** | Nothing. The month costs the same. | The monthly sum |

Tiers are written `kWh this year : fee`, for example `0:0, 1000:0.02, 3000:0.05`.
The yearly export counter starts at 0 on 1 January.

The sensors appear once a value field is set, daily and yearly:

- **Self-consumption value**: solar used at home or in the car, valued at
  the bought price minus the sold price.
- **Export value**: exported kWh at the export price, before fees.
- **Feed-in fees**: what the fee took. Export value minus fees is your export
  revenue.

## Stop exporting below

Field **Stop exporting below** (per kWh). When a sold kWh is worth less
than this, SEM stops exporting. The battery and the loads take the sun first.
SEM never buys to do this.

Default 0: the meter closes only below zero. It needs the **Export guard**
switch.

## A tariff per device

A device can have its own price, for example a heat pump on its own meter.
Nothing set means the house tariff.

| Field | Use |
|---|---|
| **Own rate** | A fixed price per kWh |
| **Own price entity** | A sensor with a price that changes by the hour |
| **Own meter (kWh)** | Optional. The device's own kWh counter |

Set it on the device, under **Device tariff**.

- The device's cheap and expensive hours follow its own price. A fixed rate
  is never cheap and never dear.
- Its cost sensor is the device's grid kWh × its own price. Without an own
  meter, SEM estimates the grid share.
- If the own price entity cannot be read, SEM uses the own rate. With no own
  rate, it uses the house tariff until the price reads again.
