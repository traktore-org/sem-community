# Tariff models — what SEM claims, per model

SEM's price **level** (`sensor.sem_tariff_price_level`) answers one question:
*is this hour better or worse than the others?* It is a **comparison**, and a
comparison needs two prices that differ.

The vocabulary is Tibber's. Tibber classifies each hour against a **3-day
moving average** — ≤ 60 % `very_cheap`, 60–90 % `cheap`, 90–115 % `normal`,
115–140 % `expensive`, ≥ 140 % `very_expensive` — and its own enum carries a
**"missing data"** state beside the five words. SEM had kept the words and
dropped both the reference and the absence, which is how a flat tariff came
to be published as `cheap` and a battery came to be held all night for an
expensive hour that could not arrive (#994).

So: **when nothing was compared, SEM says `unknown`.** Everything that would
have waited for a better hour acts now instead — the same rule the export
side has followed since #921: *an unknown price is OPEN, never CLOSED*.

## What each model gets

| model | what SEM compares | the level you get |
|---|---|---|
| **Flat / single rate** | nothing — there is one price | **`unknown`**. Nothing waits, nothing holds, no cheap blocks are drawn. |
| **HT/NT (two rates, a clock)** | the two configured rates, *on a day that contains both* | `cheap` in NT, `normal` in HT — **only when the rates differ**. A weekend, which is NT all day, has one price and therefore no level. |
| **Multi-tier ToU** (Spanish 2.0TD, US "Nighttime Savers") | the distinct tier prices (#728) | the tier's own level; tier detection is unchanged. |
| **Dynamic / spot** (Nord Pool, Tibber, EPEX, ENTSO-e, aWATTar…) | today's own curve, by percentile | the five words; `unknown` when the curve is missing, has fewer than four points, or is flat. |
| **Variable peak (VPP)** | today's curve — it *is* a curve | as dynamic. |
| **Critical peak (CPP)** | **not modelled** | an announced critical event is not a percentile of today. See *Known limitations*. |
| **Block / tiered by consumption** (e.g. 31 ct → 42 ct past a monthly baseline) | **not modelled** | the price depends on the month's cumulative kWh, not on the hour. A level cannot express it. |
| **Demand charge** (highest 15-min average) | not a price level at all | untouched — the peak guard (#864) owns that axis, on its own units. |

## Why "flat" is measured relatively

A flat test written as "the two rates differ by less than 0.001/kWh" is the
#359 defect in miniature: an absolute cutoff calibrated for one currency. It
was re-fixed twice on the configuration surface alone — for a Slovak tariff
at 1.69/kWh (#417) and a Sri Lankan one three orders of magnitude away
(#549). SEM therefore asks whether the spread is at least **0.5 % of the
day's own average**, which keeps a 1 ct HT/NT split on a 30 ct tariff (3.3 %)
and rejects float noise, in any currency.

## Where the level comes from, and how to check

`sensor.sem_tariff_price_level` carries `classifier_path` — *how* the level
was reached (`percentile_active`, `tou_tiers(...)`, `static_ht_nt`,
`calendar_schedule`, `negative_price_shortcircuit`, and the fallbacks). Since
#994 it also reports when there was nothing to classify:
`static_no_comparison`, `calendar_no_comparison`,
`percentile_fallback_flat_day`, `percentile_fallback_cache_empty`,
`percentile_fallback_too_few_prices`.

When the sensor shows no comparative level it says which of two things
happened, because they are not the same and only one of them is yours to fix:

| state | card label | meaning |
|---|---|---|
| `flat` | No price difference | the comparison WAS made and the hours do not differ — a single rate, two equal rates, a weekend under HT/NT, a day with no spread. On a flat contract this is the correct and final answer. |
| `no_prices` | No prices available | the comparison could NOT be made — nothing cached yet, fewer than four points, a price entity that will not read. Worth a look at your price entity. |

Neither is the word `unknown`, which in Home Assistant reads as a broken
sensor and hid the difference between a contract and a fault.

The path always describes the **same** answer the level came from. It did not
always: the string was set as a side-effect and read back afterwards, and
because every read of the price curve classifies all of today's slots, a day
with one negative slot could publish `normal` beside
`negative_price_shortcircuit` (seen on the test rig, 20.09). If you ever see a
path that cannot explain the level beside it, that is a bug worth reporting —
not a quirk of your tariff.

## Negative prices are not a comparison

A negative price is an **absolute** fact and is handled as one: the export
guard closes the meter on the *export* rate's own sign (#921/#955), and the
battery's negative-price force charge reads the raw import price. Neither
goes through the comparative path, so a flat tariff changes neither.

`NEGATIVE` is also the one level the comparative vocabulary passes through
without a spread behind it. Being paid to consume says nothing about any
other hour and needs nothing from one, so a spot entity that publishes only
its current state — no curve, nothing to compute a spread from — still holds
the pack for the house in a negative hour.

## ENTSO-e: a market price (#1051)

SEM finds the [ENTSO-e integration](https://github.com/JaccoR/hass-entso-e)
by itself: choose Dynamic and leave the price entity empty. It reads two of
ENTSO-e's sensors, because ENTSO-e splits what SEM needs over two: the price
now from *Current electricity market price*, and the day-ahead curve from
*Average electricity price*, which is where ENTSO-e keeps it. The average
sensor's own value is the day's average, so it is never read as the price
now. An entity name given in the ENTSO-e setup changes nothing.

- **Per kWh.** ENTSO-e can report per MWh. SEM reads prices per kWh, so it
  does not take a per-MWh setup and says so in the log. Set the ENTSO-e
  energy scale to kWh.
- **A market price is not what you pay.** ENTSO-e publishes the wholesale
  day-ahead price: no tax, no grid fee, no supplier margin. The level does
  not mind — adding a fee to every hour, or VAT on every hour, keeps the
  hours in the same order. The cost figures do mind. Add the rest in one of
  two places, not both, or it counts twice:
  - in ENTSO-e's own setup (advanced options: a price modifier template
    and VAT). Every price SEM reads is then what you pay, and a negative
    hour is one you are paid for.
  - as SEM's *Variable network-owner fee* (Tariff & Advanced). SEM adds it
    to every imported kWh. VAT on the market price cannot be expressed this
    way, and the level keeps reading the market price: a negative market
    hour reads `negative` even when the fee makes your price positive.
