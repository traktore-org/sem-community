<p align="center">
  <img src="../brand/icon@2x.png" alt="SEM Logo" width="120">
</p>

# Solar Energy Management - Dashboard Guide

The SEM dashboard has five screens, one per question: *Now*, *Plan*,
*Devices*, *Insights*, *System*. It is the only SEM dashboard. It follows your
hardware: a card or row for something you do not have is left out.

![Now screen](images/sem_next_now.png)

---

## Table of Contents
1. [Quick Start](#quick-start)
2. [The five screens](#the-five-screens)
3. [Required HACS Cards](#required-hacs-cards)
4. [Bundled SEM Cards](#bundled-sem-cards)
5. [Coming from the classic dashboard](#coming-from-the-classic-dashboard)
6. [Visual Style](#visual-style)
7. [Multi-Language Support](#multi-language-support)
8. [Troubleshooting](#troubleshooting)

---

## Quick Start

The dashboard is generated automatically on first install. If you need to regenerate it:

1. Go to **Developer Tools** > **Services**
2. Search for `solar_energy_management.generate_dashboard`
3. Click **Call Service**. It builds the dashboard **SEM-dashboard** at
   `/sem-next`.
4. The dashboard appears in the sidebar. Hard-refresh your browser (Ctrl+Shift+R).

The cards find their own screens from the address you opened, so the links
between screens work whatever URL the dashboard has.

---

## The five screens

| Screen | Question it answers |
|--------|---------------------|
| **Now** | What is SEM doing right now, and why? Power bar, today's totals, the Today list, money, signals. |
| **Plan** | What will SEM do next? The day as a timeline with sun, price and every planned block, and the reason behind each. |
| **Devices** | How is each device set up and run? Battery, cars, heat pumps, tanks and other loads, each with its own settings. |
| **Insights** | How did it go? History, sessions per charger, costs, forecast accuracy, and the Simulation replay. |
| **System** | Is everything connected, and how do I change a setting? Setup check, sources, freshness, and the settings written as sentences. |

Every setting is on the System or the Devices screen. **Everyday** shows the
sentences that matter. **All settings** lists the rest. The choice is kept per
browser.

---

## Required HACS Cards

**None.** Everything on the dashboard is a bundled `sem-*` card and the styling
is built into the cards. No card install is needed.

---

## Bundled SEM Cards

All cards ship inside the integration. Each one registers itself with Home
Assistant's card picker with a name, a description and a **help link that
lands on its section below**.

Resource URLs include `?v={version}-{sha1}` for automatic cache busting.

### Card reference

Every card has its own section. The heading is the card's element tag, so
the card picker's help link lands on it.

#### sem-next-now-card

**SEM · Now** · *Now screen*

Opens with one line in words: what SEM does right now, the next planned
block and tonight's battery floor. Then the power bar (sources above, sinks
below; tap it for every number, tap a row for its history), today's totals
with hourly sparklines and the self-use and own-supply rings, the Today
list from `sensor.sem_charging_state` (solar peak, price windows, night,
car and battery ETAs), why each device does what it does, money with the
price now and the next cheap window, and the signals: tip, best surplus
window, peak, CO2, score, weather. Plan ›, Decisions › and Insights › open
the other screens. A sensor that is out leaves its row out.

Under the power bar a thin bar shows where the power comes from now, in
percent (sun, battery, grid); it stays visible when the list is folded. The
money section ends with the price for the next 24 hours as a coloured strip
(cheap, normal, expensive, by your own price levels) with a mark for now; a
one-rate tariff shows no strip. At the bottom one chip per device (battery
charge, each car, each heat pump or tank) opens the Devices screen.

#### sem-next-plan-card

**SEM · Plan** · *Plan screen*

Today or tomorrow as one strip from `sensor.sem_energy_plan`: hourly price
bars with the cheap and the expensive band, the sun forecast as a curve,
and the plan's blocks on three lanes (car, battery, loads); solid runs,
dashed is planned. Tap a block for its reason. *Show timeline per device*
opens one lane per charger and load. On a phone the strip fits the screen
width; it never scrolls sideways. **Why this plan**: one line per planned
device (at most four) — what, when and why, in plain words. **Per device**:
one row each with *Skip* and *Start now* for a car (`plan_override`, one
night), *Back to plan* (`plan_override_clear`), *Charge now* (Always max,
confirm step), *Charge plan* (opens the charger's charge plan on Devices)
and the battery's *Sell*. **Expected**: grid cost, saved by the plan, the
battery level at the end of the plan (when the plan publishes it), sun
tomorrow with its trust, arbitrage advice, the actuation switch, *Replan*. **Decisions
today**: the decision log with a device filter and an *Earlier* fold.
The planner's notes ("13 hours have no price yet", "no cheap hour before
07:00") are shown in your language.

A heater's *Keep at* run has its own row, named after the device with
*to 52 °C*. A heater that is below its start line with no hour planned is
listed with *is below 52 °C; no cheap hour before 07:00*, and the top line
says the same in place of "Nothing planned from the grid". A heater that buys no
power is not in the plan: it waits for sun.

#### sem-next-devices-card

**SEM · Devices** · *Devices screen*

One list, one order: every charger, the battery and every load as one card
(rank · name · state pill · live kW · ⚙ configure), sorted by priority.
*Reorder* moves cards by drag or ▲▼; *Done* writes the order. Above the
list: surplus, active devices, the 15-min peak, then the peak limit as one
question, *Limit grid draw to 5.0 kW · A limit / No limit*, with what it
does; slot budget, month peak and what SEM can shed.
Charger: *Off*, the mode group and *Always (max)* by the same names as
everywhere in SEM, target bar, *Charge by* (time and days), *Charge Target*
as *At least 10 · Up to 40 kWh*, pause, battery boost, phases, set-once
values, this month, lifetime. Battery: mode, a line that says what it does
now and next (*Giving 0.8 kW. Tonight it keeps 40 % for the morning.*),
zone bar, its levels, help for the car, charge pacing, sell window,
per-battery mode, reserve and size in kWh (tap to set), evidence and health. The battery's levels and
permissions are asked here only. Load: one mode control, *Off / Peak only /
SEM runs it / SEM runs it, battery may help*, and a *Boost for 30/60/120
min* button; goal, min run / pause, Requires, phase, comfort, tariff,
may-switch. Rows that do nothing for a load in Off or Peak only are hidden.
A heat pump shows what a kWh of heat costs, and under *All settings* its
COP by outdoor temperature as text (*-7:2.5, 12:4.2*; empty = one fixed
COP, #1081) and *COP used* (Fixed, My curve, Learned from the heat meter).
Every row needs its entity; controls are off in observer mode.

A heater with a thermometer says what it does and what comes next, in the
pill and as the first line of its open card:

| It says | It means |
|---|---|
| too cold · heating now | below *Never colder than*: it heats at any price |
| heating to 52 °C | its planned hour is open; it stops at *Keep it at* |
| heating on sun · up to 56 °C | spare sun heats up to *With spare sun, heat up to* |
| heats to 52 °C at 23:00 | it is below the start line; that hour is planned |
| below 52 °C · no hour planned yet | nothing is planned; the cause follows when SEM names one |
| below 52 °C · waits for sun | SEM may not buy power for it, so only the sun heats it |
| warm · heats again below 51 °C | just under *Keep it at*: no run starts for so little |
| warm · 52.4 °C | at or above *Keep it at* |
| Legionella run | its own heat-up runs to the Legionella temperature |
| no temperature reading | the band is set but its thermometer reads nothing |

Any other load that is off names the cause when SEM has one, such as
*off · not enough spare sun* or *off · ran long enough today*.

**A heater's four questions (#1349).** Under that line and a bar with the
three temperatures, the opened row asks: *Keep it at*, *Never colder than*,
*With spare sun, heat up to* and *May SEM buy power for it?* — the same
questions, in the same words, as the Load Priority card. A load without a
thermometer is asked *Run it each day for* and the buy question. The mode,
minimum run and pause, Requires, phase, *Stop when*, the thermometer and
Legionella show under **All settings**. See
[A heater's four questions](USER_GUIDE.md#a-heaters-four-questions).

Each charger card shows its charge plan in one line under the name, also
when folded: *Ready by 07:00 · 20–100 kWh · Mon–Sun*. The pencil opens the
charge plan. Every value you can change is underlined with dots; a pencil
shows on hover and always on a touch screen. The battery's level bar marks
its reserve and says how much is above it (*About 1.2 kWh above the 20 %
reserve*); with two batteries each gets its own level and power. A heat pump
shows what a kWh of heat costs and its next planned run. On a phone every
card starts folded, with its state pill as the one-line summary.

#### sem-next-insights-card

**SEM · Insights** · *Insights screen*

One period for every chart: Today, Yesterday, Week, Month, Year; today's bar
is highlighted. Seven tabs: Energy (house by source, where the energy went,
solar yields, strings, PV health, self-use and own-supply rings, CO₂),
Power (24 h curves), Battery (power and charge), Car (kWh per charger,
sessions by month with the .xlsx download, progress and lifetime), Money
(bought vs saved, payback, car economics, demand charge, tariff), Forecast
(actual vs expected sun, accuracy) and Replay (the simulation card). Tap or
arrow across a chart to read one bucket. Charts are hand-drawn SVG fed by
the recorder; a missing entity leaves its series or row out.

With a dynamic tariff, *Money* also shows the average price SEM paid per kWh
against the market's average, when SEM publishes it.

#### sem-next-system-card

**SEM · System** · *System screen*

Health first: a tile per source with its value and age (solar, grid,
battery, car, prices, forecast, each load) and, in small type, the entity SEM
really reads (for example the inverter's power sensor), which helps when a
setup reads the wrong sensor, the setup check with the grid and battery
signs, the hardware, what is unavailable, the version; buttons Copy
diagnostics, Diagnose (copies the report) and Observer on/off behind a
confirm step. Then what SEM held back. Then seven settings groups written
as sentences (How I pay · What SEM may do · Battery rules · Chargers · Heat
pump and hot water · What SEM reads · Notifications and more): tap a value,
change it, and apply every change at once from the bar at the bottom. The
"N more" line opens with All settings. *What SEM may do* asks the peak limit
as the same question as the Devices screen. *Battery rules* reads the
battery's levels back and links to the battery on the Devices screen, where
they are asked. Tax, VAT and grid-fee rows show only where they change the
price. Adding or removing a charger,
entity pickers and PV string names are on this screen too.

#### sem-setup-checklist-card

**SEM Setup Checklist** · *Now screen*

Top of Now. While SEM only watches it shows a banner and one button, **Let
SEM take control**. The button asks first ("SEM will start controlling your
battery and charger. Continue?") and only then turns watch-only off. Below it
a checklist: hardware found, car charger, solar forecast and electricity price
(both optional), and things to check (SEM's open Repairs). The charger row
opens the Devices screen. The forecast and price rows open **System > Setup
check**. Things to check opens **Settings > Repairs**. **Hide** folds the list
for this browser. Once SEM is in control and a charger it found is set up,
only a chip stays: "SEM is in control" and "Setup 5 of 5", which reopens the
list. It reads the same facts as the AI setup tool.

#### sem-simulation-card

**SEM Simulation Card** · *Insights screen*

Pick a recorded period (last 30 / 90 / 365 days, a month, or the *Most
recent days* slider), change battery size (up to 150 kWh), power, reserve,
peak limit, solar size or price — or tap a scenario — and replay it on your
own Home Assistant. The day types filter the result; tap a day to see why it
differs. Simulated costs are marked *est.*: numbers after a changed decision
are estimated, not measured.
The Insights screen shows it while the **Simulation tab** switch is on. No reload is needed.

#### sem-retired-card

**Retired SEM cards**

The classic dashboard's cards are gone. If you placed one of them on a
dashboard of your own, it shows one line, "This SEM card was retired. Use the
SEM dashboard.", with a link to the SEM dashboard, instead of a red error
card. Remove the card from your dashboard to clear the line.

---

## Coming from the classic dashboard

The classic dashboard (nine tabs, `/sem-dashboard`) is gone. On the first start
after the update SEM looks at it once:

- **You never edited it** and the SEM dashboard exists: it is removed.
- **You never edited it** and there is no SEM dashboard yet: it is rewritten in
  place with the SEM dashboard, so the address and the sidebar entry stay.
- **You edited it:** it stays as it is. A Repair, *Old SEM dashboard is still
  there*, offers to delete it. The SEM dashboard is created beside it.

SEM cannot see whether you edited a dashboard. It reads the stored one: if
every view is a classic one and every card is a SEM card, it counts as
unedited. The service `solar_energy_management.generate_dashboard` still takes
`template: classic`, as an alias for the SEM dashboard that logs a warning.
The option *System diagram style* is gone with the diagram card.

---

## Visual Style

The dashboard uses a unified glassmorphism dark theme with dot grid backgrounds, radial gradients, and glow effects:

```css
ha-card {
  background:
    radial-gradient(ellipse 70% 60% at 50% 40%, rgba(200,220,240,0.07) 0%, transparent 100%),
    radial-gradient(circle at 2px 2px, rgba(128,128,128,0.06) 0.7px, transparent 0.7px);
  background-size: 100% 100%, 50px 50px;
  backdrop-filter: blur(18px) saturate(160%);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 16px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.06);
  font-family: 'Segoe UI','Roboto',sans-serif;
}
```

### Color Palette

| Entity | Color | Hex |
|--------|-------|-----|
| Solar | Orange | `#ff9800` |
| Grid Import | Steel Blue | `#488fc2` |
| Grid Export | Purple | `#8353d1` |
| Battery Charge | Pink | `#f06292` |
| Battery Discharge | Teal | `#4db6ac` |
| Home | Cyan | `#5BC8D8` |
| EV | Soft Green | `#8DC892` |

---

## Multi-Language Support

SEM supports 16 languages: Czech, Danish, German, English, Spanish, Finnish, French, Hungarian, Italian, Dutch, Norwegian, Polish, Portuguese, Romanian, Swedish, and Simplified Chinese (`zh` — also used when Home Assistant reports `zh-Hans`).

### How Translation Works — Two Language Settings

Home Assistant has two independent language settings. SEM uses both:

| Setting | Where to change | What it affects in the dashboard |
|---------|----------------|----------------------------------|
| **System language** | Settings → General → Language | Section headers, native/optional card titles and all static YAML-based text baked in at dashboard generation |
| **User profile language** | Your profile → Language | SEM custom cards: flow card, chart card, battery card, EV status, period selector, solar summary, weather card |

#### What this means in practice

- **Same language for everyone:** If the system language is German, all generation-time text (section headers, static labels) appears in German for every user.
- **Per-user SEM cards:** If one user sets their profile to English and another to French, the SEM flow card, chart card, and other SEM cards will show each user's chosen language.
- **Mixed-language scenario:** System = German, user profile = English → generation-time text shows German, SEM cards show English. This is by design, not a bug.

#### How to ensure consistent language

For all text to appear in the same language:

1. Set the **system language** to your desired language (Settings → General)
2. Set every **user's profile language** to the same language
3. Call `solar_energy_management.generate_dashboard` to regenerate the dashboard with the new system language
4. Hard-refresh the browser (Ctrl+Shift+R)

> **No HA restart needed.** As of v1.5.16, `generate_dashboard` pushes the new config through Home Assistant's own Lovelace store — the running dashboard reloads live as soon as the service call returns. Older muscle memory ("regenerate, then restart HA") no longer applies; a hard-refresh is enough.

### Which parts translate when?

| Action | What changes |
|--------|-------------|
| Change **system language** + regenerate dashboard | Section headers, static labels, tab names (reloads live, no HA restart) |
| Change **user profile language** | SEM custom cards update immediately (no regeneration needed) |
| Add new translations to `translations.json` | Must regenerate `sem-localize.js` + redeploy + regenerate dashboard (hard-refresh after — browser-cached `sem-localize.js`) |

---

---

## Troubleshooting

### Dashboard not appearing
1. Call `solar_energy_management.generate_dashboard` from Developer Tools > Services
2. Hard-refresh your browser (Ctrl+Shift+R)

### Cards showing "Custom element doesn't exist"
If the element name starts with `sem-`, SEM's card bundle didn't register. Restart Home Assistant and hard-refresh.

### A card says it was retired
It is a card of the old classic dashboard that you placed on a dashboard of your own. Remove it, or open the SEM dashboard with the link on the card.

### Blank screen
Almost always a stale browser or service-worker cache after an update. Hard-refresh (Ctrl+Shift+R) or clear the Companion app's frontend cache.

### Entity not found errors
The dashboard references SEM sensors that may not exist yet. Wait for the first coordinator cycle (10 seconds after restart) and refresh.

### Cards not updating after SEM update
SEM adds `?v={version}` to every card URL. If cards still show old behavior, hard-refresh (Ctrl+Shift+R) to force a reload.

### Some cards in wrong language / mixed languages
This is expected if your system language and user profile language differ. See [Multi-Language Support](#multi-language-support) above. To fix: set both to the same language and regenerate the dashboard.

### Changed system language but dashboard still in old language
Regenerate the dashboard after changing the system language: call `solar_energy_management.generate_dashboard`, then hard-refresh. It takes effect at once, with no HA restart.
