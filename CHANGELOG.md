# Changelog

All notable changes to SEM are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> From v1.7.0-beta.14 onward, release entries follow the
> [music-assistant addon](https://github.com/music-assistant/home-assistant-addon)
> style: DD.MM.YYYY dates, emoji-prefixed sections, one-liner bullets with
> `(by @author in #PR)` attribution. Older entries (≤ beta.13) stay in the
> prose-paragraph style they were written in.

# [Unreleased]


# [2.0.0] — 29.08.2026

> **Stable release.** Consolidates the 2.0 beta line (beta.1 → beta.21,
> detailed below). The milestone was named *Trustworthy* and that is what it
> spent itself on: SEM saying what it will do, doing that and nothing else,
> and admitting what it does not know.

SEM 2.0 adds almost nothing you have to learn. It makes what SEM already did
**believable**: the same decisions, no longer changing their mind for reasons
nobody can see.

## 🔇 SEM stops shouting

- Its recorder footprint fell from **25 % to 6.1 %** of Home Assistant's state
  writes (#829) — SEM was a quarter of everything your database recorded.
- At the default log level SEM is quiet (#762). A stop repeated 1800 times, a
  debug firehose, and a battery setpoint your inverter refuses (#840) are gone.
- You can tell SEM how long to keep its own status history.

## 🧮 The numbers reconcile

- The energy diagram balances, per-device breakdowns agree with the fleet
  total, and the Costs tab's year and months agree.
- **An estimate is never recorded as a measurement.** Exported battery energy
  is attributed and paid once; a bought kWh does not become free by sitting in
  the battery; EV charging cost stops pretending the battery is free.
- Every controlled load counts its own kWh, and the residual is audited.

## 🤝 SEM stops fighting your hardware

- The stop-war ceasefire holds even against slow-retrying cars (#763), a
  charger that undoes SEM's stop on a timer is **named rather than fought**
  (#823), and a missed poll is no longer read as an unplug.
- Hardware detection matches what integrations actually publish, so a charger
  named in your own language is still found (#804). Fronius / go-e Wattpilot,
  GARO and JuiceBox 48 are auto-detected (#802, #816).

## 🔌 The charger does what you told it

The last stretch of the line was spent on one question: does SEM's "stop"
actually stop the car?

- **A stop no longer starts the charger** (#854). On a KEBA, SEM's stop used to
  *enable* the box with a 1 kWh energy target so it would charge into a stop —
  which put roughly **1 kWh into the car on every plug-in** even with the daily
  target at 0. The stop is now a single `keba.disable`.
- **Mode = Off leaves your own devices alone** (#847). Setting a device to Off
  used to switch it off there and then, including a load *you* had running.
- **The box is parked when the car leaves** (#846), so the next plug-in cannot
  auto-start behind SEM's back.
- **A Wallbox whose stop cannot work now says why** (#852) — if the
  `pause_resume` switch cannot be found, SEM names the entities it inspected
  and the setting that fixes it, instead of falling back silently to a 0 A
  write that some firmware ignores.

## 🧭 Setup tells the truth

- Every setting has an explanation, ranges are declared once, and the
  first-run welcome describes **your** install (#830).
- The setup checklist can actually be completed (#842).
- **Repairs offer the next step** (#831): each notice links either the exact
  troubleshooting section or a bug report with your versions already filled
  in — and a copy-out dialog for anyone without a GitHub account. Nothing is
  ever sent without you pressing the button.

## 🌤️ Forecast and planning

- Multiple solar forecasts, one per PV string, are added together instead of
  read as one (#838), and you can see the forecast per string (#841).
- Choosing your forecast source now sticks (#819).
- One plan gate owns *when*; the battery scheduler owns *what* (#638).

## ⚠️ Upgrade notes

- **Nothing switches on silently on upgrade**, and a fresh install no longer
  wakes up observing (#777).
- **EV phase switching is off by default** while the 1/3-phase model is
  reworked (#804) — it paused chargers that never resumed on some brands.
  Enable it per charger under *Configuration → EV chargers → Phase switching*.
- Battery → grid arbitrage remains **off on every default** (#533). Check your
  grid connection agreement before enabling it.
- `switch.sem_overnight_actuation` is now `switch.sem_energy_plan_actuation`.

## Requirements

Home Assistant **2026.2.0** or newer (Python 3.13+).

### Also in this release




# [2.0.0-beta.21] — 29.08.2026

- 🛑 **A stop no longer starts the charger** (#854): telling a KEBA to stop
  used to mean *enabling* it with a 1 kWh energy target so it would charge
  into the target and suspend itself. On a box that was already idle that
  is a start, not a stop — which is why "Min = 0" still put ~1 kWh into the
  car on every plug-in, and why SEM appeared to be fighting a charger that
  was only doing what SEM told it. The stop is now a single
  `keba.disable` — the automation the reporter has run on this hardware for
  two years — with no energy target, no current write and no failsafe
  around it. Disconnect handling (#846) is unchanged.

- 🔎 **A Wallbox that can't be stopped now says why** (#852): when SEM
  cannot resolve the charger's registry device it could not find the
  `pause_resume` switch either, and fell back to `set_current(0)` — which
  some Pulsar firmware latches, so "Off" didn't stop the car and nothing
  in the log explained it. That path now names the entities it looked at
  and the setting that fixes it. (Diagnosis aid; the underlying report is
  still open.)


# [2.0.0-beta.20] — 27.08.2026

- 🙈 **Mode = Off leaves your own devices alone** (#847): setting a
  peak-management device to Mode = Off used to switch it off there and then,
  even a device you had running yourself — because the immediate release fired
  for any device that was on, not just one SEM was driving. It now only lets go
  of loads SEM actually started, matching the rest of the control loop, so
  "hands off this device" no longer touches it. Reported by @hoyte.

# [2.0.0-beta.19] — 27.08.2026


- 🔌 **The charger is parked when the car leaves** (park-on-disconnect):
  SEM now disables the charger once, cleanly, on the settled disconnect
  edge — so a KEBA (which auto-starts any plug-in when left enabled) can no
  longer begin a charge SEM never asked for. Previously an unwanted plug-in
  ran to the ~1 kWh quota-hold floor before SEM caught it. Debounced past a
  UDP unplug blip, re-armed on reconnect, and a plain disable (never a quota
  the next plug-in would inherit). Generic across brands; a later charge
  re-enables normally.
# [2.0.0-beta.18] — 26.08.2026

- 🧭 **The setup checklist can be completed** (#842): three of its rows —
  tariff, battery and load management — tested for settings that do not
  exist, so they stayed unticked however well you had configured them.
  Reported by a user whose dynamic tariff was working perfectly while
  SEM's overview insisted it was not set up.

# [2.0.0-beta.17] — 25.08.2026

- ⏸️ **EV phase switching is switched off by default while it is reworked**
  (#804): real-world testing found the shipped model harmful on two charger
  brands — a Wattpilot is left paused after every switch because it needs an
  explicit start signal SEM never sends, and a Zaptec has no phase command at
  all, so SEM stopped the charger, switched nothing, and retried. If you use
  phase switching and want to keep testing it, set
  `ev_phase_switching_enabled` on your charger; for everyone else the phase
  selector disappears and SEM leaves your phases alone. The rework — a proper
  start signal per brand, the Zaptec model, and a per-phase current guard so
  switching down cannot overload one phase of your grid connection — is the
  2.1 arc.

# [2.0.0-beta.16] — 25.08.2026

- 🔇 **A battery setpoint your inverter cannot accept no longer floods the log**
  (#840): if the entity picked for forcible discharge is readable but not
  writable on your hardware, SEM retried it on **every cycle** — one reporter's
  log had **2,364 warnings in nineteen hours**, burying everything else. Two
  things were wrong. SEM was writing a zero to that setpoint on every ordinary
  cycle to clear a value it had never set, which is pure cost and guaranteed to
  fail on such a device; it no longer does. And when a write really is refused,
  SEM now stops after three attempts, says so once in plain language, and
  raises a repair notice explaining exactly what is and is not affected —
  charging, discharge limits and everyday operation are untouched. A restart
  re-tries, so a firmware update or a corrected entity is picked up on its own.

- ☀️ **Peak solar power is no longer over-stated on a multi-string roof**
  (#841): summing each string's forecast was right for the day's energy, but
  it was also applied to peak power — and peaks do not add. An east-facing and
  a west-facing array reach their maxima hours apart, so adding them claimed
  an instantaneous output your roof can never reach (an 8 kWp + 8 kWp install
  would have shown 16 kW). SEM now reports the largest string's peak, which is
  a figure the system can actually produce.
- ☀️ **You can see the forecast per string** (#841): the Configuration tab's
  Forecast section lists today's forecast for each string with the total
  beneath it — so a string that has stopped reporting is visible, instead of
  quietly shrinking the total.

- 🔭 **Multiple solar forecasts, one per PV string, are now added together
  instead of read as one** (#838): if you run a separate Forecast.Solar or
  Open-Meteo forecast per string, SEM counted only the first one — so its
  forecast ran far below your real array. It now sums every string's forecast
  (today, tomorrow, remaining and current power), and one string being
  momentarily unavailable no longer hides the rest. Solcast, which already
  publishes a single combined total, is unchanged.
- 🔋 **The battery charge scheduler works again** (#839): if you had it
  switched on, it crashed on every cycle and never once decided anything —
  SEM compared two timestamps that were not comparable. Nothing looked broken
  from outside: the integration kept running and the dashboard looked healthy,
  while the feature quietly did nothing and wrote a warning to the log every
  ten seconds. Found in a diagnostics download sent about something else
  entirely, reproduced here, and fixed.

- 🔭 **A forecast source that is still loading is no longer reported as "not
  installed"** (#819): after choosing a source, diagnostics could show a
  warning claiming the integration was missing — while that same integration
  was selected, working, and supplying the forecast values on screen. SEM
  checks for your chosen source the moment it starts, which can be before a
  slower forecast integration has finished loading; it already retried and
  recovered, but the alarming line was written and the recovery was not. It
  now stays quiet while it retries, says something only if the source really
  never appears, and records when it does turn up.

- ⬆️ **SEM now requires Home Assistant 2026.2.0 or newer** (#836): the old
  minimum was 2025.1.0, a version no SEM user has ever reported running — of
  62 issues that state a Home Assistant version, the oldest is 2026.4.3 and
  none is on 2025.x. If you are on an older Home Assistant, HACS will stop
  offering SEM updates until you upgrade; your existing install keeps working
  and nothing is removed. Everything SEM supports is now covered by a test
  run that can block a release, which was the point.

- 🧪 **SEM is now actually tested against three Home Assistant versions**
  (#835): the middle rung of the test ladder — HA 2026.2.3 — had never passed
  a single run. It was marked advisory, so the board stayed green and nobody
  saw it. The cause was one line in a test dependency, not in SEM; it is fixed,
  all three versions now run clean, and none of them can go red without
  blocking a release any more.

- 🔌 **A charger that reports its state as text is no longer read as "no car"
  while it sits idle** (#833): if you point SEM's connection field at a status
  sensor rather than a plug binary sensor, states like `Paused` and `Locked` —
  a Wallbox's normal idle and its must-unlock-first state — were not
  recognised as "cable is in", so SEM decided no car was present and never
  started a session. Both the connection and charging readers now share the
  same cross-brand status vocabulary the rest of SEM already used, so they
  cannot disagree again; several brands' charging states (Zaptec, Easee,
  Alfen, V2G discharge) are now recognised too.
- 📦 **Releases now carry a downloadable archive** (#834): SEM's HACS entry
  showed no download count, because that column counts a release's attached
  files and SEM published none. Every release now ships
  `solar_energy_management.zip`. Your installs also get tidier — HACS
  previously copied the whole repository into your config directory, test
  suite and documentation included; now it installs only what SEM needs to
  run.

# [2.0.0-beta.15] — 24.08.2026

- ☀️ **Choosing your solar forecast source now sticks** (#819): if you had
  Solcast installed alongside another forecast integration, picking that other
  one appeared to work and then silently went back to Solcast on the next
  update — every time. SEM had a rule from an earlier release that upgraded to
  Solcast whenever it appeared, written before the source picker existed, and
  it overrode your choice one cycle after you made it. It now leaves an
  explicit choice alone, and still upgrades automatically for installations
  that never picked one.

- 🔎 **The forecast sensor now says which source was asked for and whether it
  was used** (#819): when SEM cannot use your chosen integration it falls back,
  which is correct — but it used to do so in silence, so "SEM cannot find your
  integration" and "your setting did not save" looked identical from the
  outside. `sensor.sem_forecast_source` now carries `requested_source` and
  `source_honoured` beside the list of what is installed.


- 🧭 **The Configuration tab now shows what you need, with everything else one
  switch away** (#830): SEM had grown to around ninety controls on that tab, and
  a new install needs about eight of them. The default view shows the setup
  guide, your tariff, your chargers and your battery floors — plus any
  subsystem you have already configured, because hiding something you set up
  is not simplification. An **Advanced** switch reveals the rest and hides
  nothing: every setting stays one click away, and the choice is remembered per
  browser.

- 🏷️ **Settings are named for what they do** (#830): *"Night charge target"*
  read like a ceiling and is a floor — the maintainer misread his own setting
  while testing on production and reported correct behaviour as a bug. It is
  now **"Guarantee at least (kWh)"**, with **"Never charge past"** for the
  ceiling, matching names for the SOC versions, and descriptions that say which
  kind of number each one is.

- 💡 **Every setting has an explanation** (#830): ten controls had no help text
  — the per-charger targets, phase count, consumption figure and the VPP
  entities. All ninety now explain what they do when you turn on *Explain
  settings*.

- 🐛 **The SOC Zones card now appears at all**: it has never rendered. A code
  error made it throw on every attempt, and because a card that fails silently
  just looks absent, it read as "not configured" rather than broken. Present in
  every 2.0 beta so far.

- 🧹 **Two settings that appeared on two pages now appear on one** (#830), and
  one of them was also a bug: opening the hardware page reset your chosen
  system-diagram style back to the default.


- 🧹 **You can now tell SEM how long to keep its own status history** (#829):
  SEM writes a lot of short-lived rows — charging state, strategy, diagnostics
  — that carry no long-term statistics, so keeping them for weeks only grows
  your database. **Config tab → Advanced → "SEM status history"** sets the
  retention (default **off**), and **"Clean up now"** applies it immediately.
  **Your energy history cannot be affected**: the clean-up list is derived
  from "has no `state_class`", so every charted sensor — energy, power,
  anything with long-term statistics — is excluded automatically, including
  sensors added in future versions. Also available as the
  `solar_energy_management.purge_status_history` action.

- 🔧 **The EV charge-stop and the message about it can no longer disagree**
  (#708): the "remaining kWh to your SOC target" maths existed twice — once in
  the stop decision, once hand-copied in the notification that announces it.
  They are now one function, so SEM cannot tell you "the estimate stopped your
  charge" about a stop it did not make. No behaviour change.

- 🧱 **Settings ranges are declared once** (#828): four reported bugs (#717,
  #746, #813, #826) were one structure — every number's range was written
  twice, once for the options page and once for the entity, with nothing
  binding them. Seven settings now come from a single table and cannot
  drift; a build-time ratchet refuses any new field that hardcodes its own
  bounds. One user-visible correction fell out: **Battery capacity** was
  offered with different minimums and steps on two pages (5 kWh/1 kWh vs
  1 kWh/0.5 kWh), so a small pack saved on one page was refused by the
  other — both now allow 1–100 kWh in 0.5 kWh steps.
- 🧹 **SEM writes far fewer recorder rows** (#829, Guido: *"SEM is gathering a
  lot of information and cluttering HA"*): measured on a production system,
  SEM wrote **25 % of all state rows with 13 % of the entities** — not from
  recording too much, but from a handful of entities writing a row every
  10 s cycle: a daily energy published at 1 Wh, session durations in tenths
  of a minute, averages as raw floats, live per-device watts riding the
  attributes of a device *count*, a per-cycle counter on the mismatch flag,
  and the energy tip rotating every cycle. Each now publishes on change at
  the precision a human reads: 10 Wh energies, whole-minute durations, 10 W
  averages, whole-watt powers, a 100 W-coarse device map (cards read live
  watts from each device's own entity), a tip that rotates every five
  minutes. Nothing you see changes; what the database stores shrinks.

- 🔧 **Deye grid-charge current can be set above 100 A** (#826, reported by
  @ab-elco-clal): the field that tells SEM how much current it may write
  ("Maks. ladestrøm (A)") refused anything over 100 with *"Value X.0 is too
  large"*, while the BMS-ceiling field beside it accepted up to 200 — so you
  could describe a battery SEM was then forbidden to drive. Raised to match.
  The effective write is still `min(entity max, your ceiling, BMS ceiling)`,
  so a higher setting grants nothing the hardware has not already agreed to.

# [2.0.0-beta.14] — 21.08.2026

- 📊 **A consumption figure you can actually compare with the Energy
  Dashboard** (#825): `sensor.sem_daily_home_energy` excludes the EV on
  purpose — every charging decision SEM makes depends on telling the house
  and the car apart — while HA's Energy Dashboard "Home" *includes* it and
  draws tracked devices as a slice of that total. Both are right, nothing
  said so, and the only comparison a user could make was the misleading
  one. It cost one reporter a wrong-looking house tile (#802) and another
  a month of investigation (#628). SEM already computed the number
  internally for the autarky rate; it now publishes it as
  **`sensor.sem_daily_total_consumption`** (house + car, named in all 16
  languages), and the troubleshooting guide states plainly which of the
  two matches the Energy Dashboard.
- 🔌 **A charger control entity that never loaded is now reported, not
  written to in silence** (#824, found by @onkelfu in #763): one
  unsupported `mode: slider` line meant Home Assistant never properly
  loaded his template `number` — it existed only as `restored` — so every
  charging-current command SEM sent vanished, for days, while the
  dashboard kept showing a commanded current. SEM's existing
  "charger rejects commands" repair could not catch it: that one needs
  three commands that *failed*, and these never failed. SEM now checks the
  entities it commands **before** trusting them, and raises a Repair
  naming the charger, the entity and what was lost ("SEM cannot set the
  charging current") — in 16 languages, after the same five-minute grace a
  dead sensor gets, so a restart's warm-up stays quiet.
- 🌤️ **Pick which solar-forecast integration SEM reads** (#819, reported by
  @ArneGollin1987): running Solcast, Forecast.Solar and Open-Meteo side by
  side to compare them meant the first one on SEM's ladder always won, and
  the only way to reach another was to deactivate the others. There is now
  a **Solar forecast source** setting — in the options flow and on the
  dashboard's *Configuration → Forecast* section — offering the
  integrations **actually installed** on your system, so you cannot pick
  one that isn't there. Switching takes effect immediately, without
  reloading the integration. A choice that later disappears falls back to
  auto-detection rather than taking the forecast down with it, and the
  fallback is recorded in diagnostics instead of happening silently. The
  setup guide caused this one: it promised the override on the **Forecast
  entity** field, which is the *price* forecast — that field is now
  labelled **Price forecast entity** in all 16 languages so the two stop
  being confusable.

- 🔇 **A sensor that goes quiet no longer reads as "the sun stopped"**
  (#818, found on a production install): when a source is unavailable the
  reader falls back to 0 W — and on a Huawei modbus system, which blips
  8–15 % of the time, that fabricated zero reached the surplus maths about
  **50 times a day** on each of solar, grid and battery. SEM now separates
  two questions it had been answering with one number. A cycle where *any*
  steering input was dark no longer **steers**: the charger keeps the
  command it already had (clamped, so #741's below-floor freeze cannot
  recur), and the battery's EV-protection clamp does not flip — everything
  else, including stops, disconnects, `always_max`, forced modes and the
  scheduler, passes through untouched. A reading where *every* source was
  dark no longer **publishes** a number either: the entity reports
  unavailable, exactly as `battery_soc` always has, instead of booking a
  false zero into long-term statistics. One dark inverter among three
  still publishes the total. Nothing anywhere substitutes a value — the
  display hold that rides out these blips stays where it belongs, in the
  card.

# [2.0.0-beta.13] — 21.08.2026

- 📋 **The support matrix now credits what users have actually proven**
  (#814): the *tested live* column mostly held the maintainer's own
  hardware. A full sweep of the issue and discussion corpus found far more —
  **live rows doubled, 9 → 18** (SMA, SolarEdge, Enphase, GoodWe, Sonnen and
  Easee move up on real citations; FENECON Home, GARO and JuiceBox 48 are
  new), and the rows that were already live now name their reporters. Two
  tables join them: the **vehicles** people use as SEM's SOC source and the
  **heat pumps, hot-water relays, metered loads and grid meters** SEM reads
  or switches — 66 rows in all, 31 of them proven on somebody's real system.
  Every ✅ cites the issue or discussion it was proven in, and the
  no-citation-no-claim rule now covers every table, including ones added
  later. #802's FENECON figures became a pipeline regression test.

- 💶 **The Costs card no longer invites a double count** (#797): savings and
  net cost sat in one column as parallel rows, so they read as summable —
  but avoided cost is *why* the net cost is low, not money on top of it. The
  card now shows two labelled blocks, **Money moved** (import, export, net)
  and **Money avoided** (solar, battery), each with its own subtotal and one
  line saying the two must not be added.
- 🎛️ **The device list says what SEM may actually do** (#798): the column
  said "Controllable" — one permission word in front of the two things
  #780 split apart, so a device could show a tick while SEM was not allowed
  to touch it. Each device row now states both plainly: *SEM may act*,
  *Off — SEM won't act*, or *No control* (16 languages). The Grid card's
  device count follows the same wording, since it already counted what SEM
  may act on rather than what it could.

- 🩹 **Settings pages no longer refuse the values SEM itself saved** (#813,
  found while configuring a production install): a charge target above
  100 kWh could not be re-saved — the runtime sliders span 0–200 kWh but the
  options pages capped the field at 100, so the form rejected its own stored
  value. And raising the **target peak** past the emergency level left the
  stored peak ladder inverted: the shedding logic quietly repaired it in
  memory, but the Load Management page then refused to save, complaining
  about a level the user never touched. The target writer now carries the
  ladder with it (same ratios the runtime repair uses), and a new guard test
  fails the build whenever an options field is narrower than the entity that
  writes it — the drift that caused both.

- 🌅 **A night that has ended cannot reopen** (#811 round 2, caught on the
  verification rig's first clean night): the sunrise fix shipped in
  beta.12 vetoed the phantom night via the sun's own state, but the rig
  still re-entered night one minute after sunrise — because neither the
  `HH:MM` compare nor the datetime path can close the gap (`next_rising`
  rolls to *tomorrow* at sunrise, and the existing correction derives
  today's sunrise from tomorrow's — they differ by exactly that minute).
  The recorder sealed a clean 12 kWh night and the morning verdict then
  described the phantom one-minute record instead (0.0 kWh drained). A
  night now ends **once per day**: once SEM has seen today's night end,
  only the evening window opens a new one.

# [2.0.0-beta.12] — 20.08.2026

- 🩹 **YAML-mode Lovelace now tells you what to do** (#799, @RonaldHass):
  on a YAML-mode install SEM cannot register its dashboard cards, so the
  dashboard came up full of "Configuration Error" cards — with the fix
  sitting in a single log line the reporter only found after reinstalling
  twice. That case now raises a **Repair** in Settings carrying the exact
  `lovelace.resources` block to paste (16 languages), and clears itself
  once the resources load.
- 🔌 **Fronius / go-e Wattpilot auto-detected** (#802, @HorizonKane): SEM
  used to match a lookalike Energy-Dashboard device instead, leaving the EV
  tile pointed at the wrong thing. Added as the first brand supported
  purely as a #814 data row — no per-brand code.

- 🔌 **1↔3-phase switching for EV chargers** (#804): name your wallbox's
  phase-switch entity (go-e `psm`, KEBA X-series, openWB — select/number/
  switch, with the 1p/3p values in the entity's own vocabulary) and SEM
  gives you the full ladder: a measured **active-phase estimate** from
  watts-per-amp on `sensor.sem_charging_state` and in diagnostics; a
  per-charger **Phase Mode select** (Auto / 1-phase / 3-phase) whose manual
  positions run the one safe sequence — **stop → switch → settle → start**,
  never under load, minimum 2 minutes between switches; and **Auto**, which
  scales the charger to fit the surplus (down after 10 sustained starved
  minutes, up after 5 sustained minutes of headroom + margin) under hard
  caps: one automatic switch per 30 minutes, four per session. The estimate
  independently confirms every switch physically took — and never lies
  below the physical floor (one phase carries at most amps × 230 W; a car
  drawing less than the offer reads the honest lower bound — found on the
  first real charge). All three settings live on the dashboard
  Configuration tab's charger block as well as the options flow, and the
  Phases row on the EV card carries the selector and live status. Without
  a named entity nothing exists — no knob, no writes, no behavior change.
- 🔎 **Auto-detection that shows its work, and a hardware matrix that can't
  lie** (#814, from the onboarding round #803/#802 and #806/#808/#809/#810):
  the Config tab gains a **Detected hardware** section listing every charger
  SEM found with the evidence per role (which entity, what it is) and what it
  could *not* place — near-misses (a brand's entities present, no role
  matched) are shown instead of silently becoming "no charger"; the same
  report rides the diagnostics download. A generic prober now runs beside
  the brand profiles (classifying devices by what their entities are, never
  by name) and reports what it sees — observation only for now. And
  `docs/SUPPORTED_HARDWARE.md` is generated from one data table with an
  honest status per brand (tested live with citation / implemented /
  requested); CI fails if the doc drifts, a README claim lacks a row, or
  pipeline-test coverage shrinks. Sungrow and Tesla Powerwall gained the
  pipeline tests the ratchet showed missing.
- 🌅 **The night no longer double-flips at sunrise** (#811, caught live by
  the #800 recorder's seal counter): at the moment of sunrise `sun.sun`
  rolls `next_rising` over to tomorrow — 1–2 minutes later on the clock in
  the shrinking half of the year — and the minute-granular night check
  re-entered night for that sliver (day at 06:22, night seconds later, day
  at 06:23). Every consumer of night mode saw the flap; the battery-night
  recorder sealed the real record on the phantom re-entry and the morning
  verdict read a garbage one-minute night. A risen sun now vetoes the
  post-midnight night claim (`post_midnight_sun_already_up` on the #424
  telemetry surface); the winter early-end ceiling is untouched. Phase
  flips now also log their inputs at INFO — one line, transitions only.

# [2.0.0-beta.11] — 20.08.2026

- 🔧 **Deye program-slot time picker now offers `time.*` entities** (#807,
  @ab-elco-clal): each Deye `deye_program_groups` slot's setup field offered a
  `select` entity picker while the adapter requires — and writes via
  `time.set_value` to — a Home-Assistant `time.*` entity, so no slot could ever
  be configured to work. The picker now offers `time.*` (matching the validator
  and the corrected docstring + field labels in all 16 languages), and reopening
  the Deye options no longer shows the six slots blank — they re-read from the
  saved program groups instead of the never-persisted flat keys.
- 🔌 **Phase awareness, observation layer** (#804 Phase A, inert by design):
  SEM now estimates each charger's *actually used* phases from measured
  watts-per-amp (draw ÷ commanded amps ÷ ~230 V) — a 3-phase box feeding a
  1-phase car reads 1 — surfaced as `per_charger_phases` on
  `sensor.sem_charging_state` and in the diagnostics download. A new
  optional per-charger **Phase Switch Entity** setting (16 languages) lets
  you name the select/number/switch that performs a 1↔3-phase change
  (go-e `psm`, KEBA X-series, openWB); SEM validates the declaration and
  surfaces the verdict but never writes to it — automatic switching builds
  on this in a later release, per the plan on the issue.
- 🔋 **Sensor blips no longer poison the battery-night record** (#800
  round 4, found live on the verification rig): the battery power sensor on
  a modbus rig drops out for 40–90 s every few minutes (807 s over one
  observed evening) — each blip both zero-counted real drain *and* priced
  gap, so every rig night would have been refused as untrainable and the
  #778 learner starved on the exact hardware it exists for. An unmeasured
  streak up to 5 minutes is now bridged with the last measured flows
  (zero-order hold, reported honestly as `held_s` on the record); longer
  silence and restart holes still price as gap and refuse the night. Also
  found arming the live test: the morning battery verdict refreshed only at
  the demand ledger's own seal — which runs *before* the recorder's
  night→day tick in the same sunrise pass — so the card's battery row would
  have shown the previous night, one night stale, all day. A phase flip now
  refreshes the verdict itself.
- 🔋 **The battery night now actually reaches disk mid-run** (#800 round 3,
  found live on the verification rig 35 minutes into a real night) — the
  "persist every cycle" fix wrote memory only: the energy store's delayed
  save re-arms on every call under the continuous update loop, so it fires
  only at a *graceful* stop — and a record whose whole point is surviving an
  unclean reboot cannot be written by a mechanism that only runs at clean
  ones (this store's own docstrings document the trap, now three times). A
  throttled real write lands the open night on disk at most every 5 minutes,
  bounding what a power cut can take to that window. And a night with a
  restart in it stays *trainable*: the warm-up holes are priced honestly but
  up to five minutes of them no longer refuse a whole night — zero tolerance
  plus the rig's daily automated restart would have refused every night,
  forever. A real outage still refuses.
# [2.0.0-beta.10] — 19.08.2026

- 🔋 **The battery recorder actually survives, and tells you in the morning**
  (#800 follow-up, found verifying beta.9 on live hardware) — two gaps in the
  night recorder's wiring: it persisted the open night **only when the record
  sealed**, so a restart mid-night dropped everything accumulated (the exact
  silent regression its own `to_dict`/`from_dict` exists to prevent — it now
  persists every cycle); and the morning verdict read **sealed records only**,
  but a record seals when the *next* night begins — so last night's battery
  row would have appeared on the card in the evening. The verdict now reads
  the open record as soon as the night half is complete, which is what makes
  a morning verdict readable in the morning.

- 🔌 **SEM tells you when it finds a charger it is not managing** (#805) —
  the old repair warned *every* install without a charger, including
  solar-only homes that own no car, and named nothing. It is replaced by one
  that fires only when discovery actually found something charger-shaped and
  says **which device**: *"{name} looks like an EV charger, but none is
  configured — so SEM is leaving it alone."* That single line is what would
  have prevented the whole episode behind #803. It arrives in your Home
  Assistant language like everything else, and if the guess is wrong you can
  ignore it — SEM does not control the device either way.

- 👋 **The first-run welcome describes YOUR install** (#805) — it told
  everyone to "pick an EV charge mode on the EV tab", but that tab is
  deliberately absent until a charger is configured: the one reader who most
  needed guidance (owns a wallbox, hasn't told SEM about it) was pointed at
  something that isn't there and concluded the controls were broken. Each
  line is now either about something this install has, or an invitation to
  add what it lacks — and it states plainly that SEM controls only what you
  configured, with discovered devices left on *monitor* until you give them
  a mode.

- 🔒 **SEM no longer acts on devices you never configured** (#805, from a
  first-install report) — a device SEM discovered by itself defaulted to
  "peak only", an *acting* mode: load management could switch it off. A
  wallbox merely visible in Home Assistant's Energy Dashboard was therefore
  imported as a generic load and shed to protect the peak limit, while its
  owner — who had never configured an EV charger, and so had no EV tab and
  no charge-mode selector — could see no reason and no control. He
  uninstalled to get his car charging (#803). Discovery is a suggestion,
  not consent: a device SEM found on its own is now **monitored only** until
  you opt it in. **Existing installs do not change**: the upgrade writes
  explicit "peak only" entries for every device already in the roster, so
  whatever is being shed today keeps being shed — verified against a live
  19-device install where 12 devices were riding the implicit default.

# [2.0.0-beta.9] — 19.08.2026

- 🔋 **The battery's night is written down** (#800, the #778 groundwork) —
  the #755 learner records what each *demand* did; nothing recorded the
  battery's night as a supply story, so the "how much may tonight spend"
  question had no training data. A new recorder seals one record per
  night+day pair: overnight drain (flow-attributed — `battery_to_home` only,
  so evening EV assist and export can never poison the series), EV-assist
  and export kWh beside it, reserve-hit (which censors the drain from
  *below* — the mirror of the demand learner's ceilings), the morning
  refill time against the dampened forecast's captured promise, the grid's
  overnight supply to the house beside the drain (`night_grid_kwh` — the
  house's true overnight *need* is the sum; drain alone under-observes it
  whenever the battery sat at reserve) and the day's house consumption
  (`day_home_kwh` — so a missed refill promise decomposes into PV-wrong vs
  consumption-wrong), clipping
  hours (pack full while export runs — the direct evidence that more could
  have been spent for free), and covariate stamps (date, outdoor
  temperature) for later season bucketing. Holes refuse the night rather
  than being integrated across; a restart prices its own outage as a gap.
  The morning verdict gained the battery's sentence — *drained X kWh
  overnight · full again by HH:MM / the promised refill never came ·
  clipped Z h at full: more was spendable* — on the Energy Plan card in all
  16 languages, with the same restraint rules as the demand rows (an
  untrainable night says nothing, a trivial one is not worth the morning's
  attention). Recording + telling only: the budget consumer is #778 in 2.1,
  and by then weeks of real nights exist. (#800)

# [2.0.0-beta.8] — 18.08.2026

- 🚗 **One stop command per minute, not six per burst** (#763 round 3,
  measured against evcc) — while a self-started charge persisted, the
  reconciler re-issued its stop every 10-second cycle: redundant writes
  through the user's charger bridge, each a fresh chance to abort the car's
  handshake mid-negotiation. evcc floors every corrective contactor command
  at 60 s (`chargerSwitchDuration`) — its sync layer logs a self-start,
  re-syncs its own belief, and lets the next control tick act. SEM now does
  the same: the first DISABLE is immediate, re-asserts come once per 60 s
  dwell, and the war accounting (rounds, ceasefire, escalating backoff — all
  of which evcc lacks; it fights forever) is unaffected. Two war-round test
  timings updated from their fast-KEBA-era 20-second spacing to the honest
  timescale.

- 🩹 **The dashboard renders again on HA 2025.7+ — every card was "Custom
  element doesn't exist"** (#799, @HorizonKane, HA 2026.8.2) — a fresh install
  showed nothing but Konfigurationsfehler tiles: `sem-price-card`,
  `sem-solar-card`, `sem-tab-header` and every other sem-* card failed to load.
  SEM served its card bundle by registering a static path with
  `hass.http.register_static_path`, a blocking sync call HA **removed in
  2025.7**. On any HA at or past that the call raised `AttributeError`, which a
  bare `except: pass` swallowed as "already registered from a previous load" —
  so the route serving `sem-cards.js` was never created, its URL 404'd, and no
  card could define. Now registered through the current
  `async_register_static_paths`, with the swallow split so a real failure logs
  a warning instead of vanishing. New bug class #48 (a removed host API called
  past its removal, its failure hidden by a too-broad `except`) with a source
  lint that keeps the removed call form out of the tree. (by @traktore-org in #799)

- 🧪 **The HA-2026.8 CI rung is now blocking — green means the HA you
  actually run** (developer-facing) — #787 built the ladder; this flips its
  top rung. The 3.14 → HA 2026.8.2 leg (what HA-PROD runs) had 37 failures
  that turned out to be two causes, not thirty-seven: HA 2026.x's
  DataUpdateCoordinator reports usage through the frame helper, which raises
  in every test that builds a real coordinator on a mock hass (36 of the 37
  — one autouse conftest shim no-ops `report_usage` only when nothing has
  set the helper up; real-hass tests keep the real guard, and the 2025.1
  floor never calls it); and `label_entities` moved into the template
  engine's LabelExtension (the #670 test's oracle now goes through a
  rendered template — the public surface — on both HAs). The rung's
  blocking state is pinned by a guard so it cannot silently go advisory
  again; 3.13 stays advisory until its pytest-asyncio pin is right. Local
  3.14 run: 7476 passed, 1 skipped. (#791)

- 🚗 **The stop-war ceasefire stops losing to slow-retrying cars** (#763,
  beta.7 recurrence) — the ceasefire counted stop→redraw rounds but forgot
  them after 10 quiet minutes, on the theory that quiet means the box gave
  up. onkelfu's Mercedes retries every ~12 minutes: slower than the reset,
  so every burst counted from zero, the ceasefire never engaged, and the
  car latched its charging fault again. Quiet is exactly what a
  slow-retrying car looks like between attempts — the horizon is now an
  hour, a disconnect ends the war outright (the handshake partner left),
  and a war that survives its first ceasefire doubles each following
  stand-down (capped ×8) so the handshake-abort rate decays instead of
  settling at one abort per half-hour forever. Two side gaps closed with
  it: the reconciler's war state now rides the diagnostics download (the
  dump showed only the — empty, unrelated — charge-stability give-up
  fields, which read as "the machinery never engaged"), and the startup
  "entities missing, commands will silently no-op" warning is deferred
  120 s past warm-up — it fired on a healthy wallbox whose integration
  simply hadn't loaded yet, and sent the diagnosis down a dead end.

- ☀️ **The curtailment probe stops measuring its own blindness** — two holes
  found auditing the shipped probe against #743's own worked example (5 kW
  forecast, 1 kW delivered, 0 export). First, suspicion used the *dampened*
  forecast — but the dampening factor learns from today's measured
  production, which a curtailed day clamps to consumption, so on exactly the
  day the probe exists for, its yardstick sank toward what the inverter
  showed. The 1.8 half fixed this class one layer up ("every dampened
  consumer under-plans exactly the hidden kilowatts the probe reveals") and
  the probe is also a dampened consumer; suspicion now reads the raw sky.
  Second, the hidden-room test refused to probe unless the hidden power
  covered the charger's whole minimum — a cost guard in the one scenario
  where the cost sign is inverted. On a 3-phase 6 A charger the reporter's
  literal example (4000 W hidden vs 4140 W needed) was vetoed over 140 W,
  even when the inverter explicitly reported its export limit active. The
  probe may now overdraw the hidden room by up to 10 % of the charger floor
  — importing ~140 W to unlock 4 kW of otherwise-curtailed solar, worst
  case ~4 ct/h, bounded by design. Deliberately no new mode and no new
  knob: the probe's opt-in is the consent, and the trade is equally right
  at negative prices and on zero-feed-in installs at any price. (#743)

# [2.0.0-beta.7] — 18.08.2026

- 📈 **ROI stops presenting a guessed install date as a measurement** —
  when install-date autodetection has not succeeded, payback and annual
  savings silently assumed "installed January 1 of this year". The figures
  still compute (detection retries every cycle and a degraded answer beats
  none), but both sensors now carry `install_date_estimated: true` until
  the real date is found, so an estimate reads as one. (#796)

- 💰 **Reconciliation drift is priced at the day it happened** — when a
  hardware counter proves the integrator missed (or over-counted) energy,
  the correction used to be priced at the tariff of the moment the counter
  was READ; the drift itself accumulated across the day. On a dynamic tariff
  that priced 0.15-CHF kWh at a 0.32 spike (#416's write-time class). The
  delta is now booked at today's realized average — `daily cost ÷ daily
  energy` for the same category, the mean of exactly what the live path
  booked — with the instantaneous rate kept only when nothing has
  accumulated yet. Static tariffs are unchanged, and downward corrections
  give back what was actually booked. (#795)

- 🚗 **EV charging cost stops pretending the battery is free** — the session
  accounting split the car's energy three ways (solar / grid / battery) and
  then priced only the direct-grid slice: energy that reached the car via the
  house battery cost nothing, even when that battery had been filled from the
  grid at 03:00. On an install that grid-charges most nights this was most of
  the story — PROD showed 0.043 CHF/kWh at a 66.4 % solar share, where the
  non-solar remainder alone implies ~0.10. Battery-sourced energy is now
  priced through the same provenance pool the battery savings already use:
  a new `implied_cost_rate` (the exact dual of the savings rate — what a
  discharged kWh costs plus what it saves is the import rate) charges the
  stored grid energy at what was actually paid for it, and solar-charged or
  unknown-origin energy stays free. The split is also finally visible: two
  new sensors (`lifetime_ev_battery_share`, `lifetime_ev_grid_share`, all 16
  languages) and the EV Charging Economics card now show solar / battery /
  grid side by side, so "not solar" and "charged for" stop reading as the
  same number. `lifetime_ev_cost` is an accumulator — the rate is correct
  going forward; the kWh already recorded are not re-priced. (#793)

- 📊 **Chart legends total what the chart shows** — under a "This Year" filter
  the savings chart's legend read "Solar Savings: 105 CHF" while the bars above
  it plotted a year that sums to ~979: the legend always showed the *newest
  bucket* (August, mid-month at that), labeling a year-long chart with one of
  its data points. Legends now SUM accumulating series (money, kWh — where
  each bucket is a per-period total) and keep the latest sample for
  instantaneous ones (W, %, where a sum would be a quantity of nothing). The
  sum-vs-sample choice is made where the hourly-vs-daily/monthly series choice
  is made and travels with each dataset, so it survives Chart.js reordering
  legend items — the same pairing bug #574 fixed — and the #585 cash-flow sign
  convention carries through unchanged. Same fix, same screen: the Costs
  chart's legend showed the current month's import beside year-spanning bars.
  (#792)
- 💰 **The year and the months on the Costs tab now agree** — the yearly cost
  figures were never measured, they were *estimated once*: yearly energy ×
  a 7-day average rate, written a single time behind a flag that is saved to
  disk. Live on PROD that put the year's grid-import cost at 112.81 against
  458.97 actually accumulated across the same year's monthly buckets, and
  flipped the year's net cost sign — the yearly sensor said the house had
  earned 168 CHF while the monthly buckets on the same screen said it had spent
  222. The seed now sums SEM's **own recorded monthly cost statistics**, at the
  prices that were really in force, and falls back to the energy × average-rate
  estimate only for months with no cost record at all — so yearly = Σ monthly
  by construction, which is the property you are checking the moment you put
  both on one screen. Three smaller things went with it: the estimate no longer
  subtracts grid-charged battery from solar savings (charging the battery off
  the grid consumes no solar, but it was being deducted as if it had); a floor
  re-check now lifts a year that sits below its own recorded months, so an
  install that seeded badly self-heals instead of staying wrong until January;
  and because both seed flags are persisted, the startup gate had to stop
  asking them and ask whether the reconcile is still owed — otherwise the heal
  would have been unreachable on precisely the installs that need it.
  Corrects the figures going forward and re-derives the year from what was
  recorded; it does not rewrite per-month history. (#794)

# [2.0.0-beta.6] — 17.08.2026

- 🔧 **`manifest.json` key order follows Home Assistant's current rule**
  (developer-facing) — hassfest tightened `domain`, `name`, *then* alphabetical
  between two CI runs thirty-nine minutes apart, on a day nobody touched the
  file. Key order only; every value is unchanged. Two things surfaced while
  verifying it and are worth more than the fix: the Hassfest job carries
  `continue-on-error` for ghcr rate limits, so the Validate workflow had been
  reporting green while the check inside it failed — and the rest of that red
  board was GitHub's own outage, not ours, which a re-run of the identical
  commit proved. (#790)
- 🧪 **The test suite now runs against the Home Assistant you actually have**
  (developer-facing) — for nineteen months every one of SEM's 7,400+ tests ran
  against Home Assistant 2025.1.4 while users ran 2026.8.x, and nothing said so:
  the CI matrix listed two Python versions, both installed the same
  `pytest-homeassistant-custom-component` pin, and that pin — not the matrix —
  chose the HA. Green meant "works on 2025.1", which is not a claim anyone
  needed. The matrix is now an HA ladder: 3.12 → HA 2025.1.4 (the supported
  floor, still blocking), 3.13 → HA 2026.2.3, 3.14 → HA 2026.8.2, the version
  HA-PROD runs. The two upper rungs are non-blocking to start — nineteen months
  of deprecations will not land clean, and that triage should not happen as a
  green-chase on top of a release. A guard pins the shape so the blind spot
  cannot silently reopen. The declared floor in `hacs.json` does not move.
  (#787)
- 🧹 **A lint floor, and the cruft it swept out from under it** (developer-
  facing; nothing you configured changes) — SEM had no linter at all, so cruft
  accumulated invisibly: 314 unused imports, 70 assignments nobody read, three
  `raise` statements inside `except` that dropped the original error from the
  traceback, and two closures that captured a loop variable by reference.
  `ruff check .` is now a fifth CI check, pinned, selecting only what earns its
  place — pyflakes, bugbear, async-blocking — with a config that documents what
  it refuses to select and why (import order and `pyupgrade` are churn across a
  release; `flake8-datetimez` is actively *wrong* for an integration that
  reasons in local time on purpose). No formatter. The floor found real things
  on its first pass: a variable deleted three lines above its last live use, and
  a test that asserted a repair sweep *returned* "2" without ever checking it
  deleted anything. The domain guards in `tests/test_*_lint.py` remain the
  primary defence — where they and ruff answer one question differently, the
  guard that knows HA wins. (#786)
- 🔍 **Diagnostics stopped answering the wrong question about your loads** — a
  load row carried one flag, `is_controllable`, whose name reads as *"may SEM
  touch this"* but which actually meant *"a switch was found for it, and you
  haven't opted it out"*. The permission SEM really enforces lives in a
  different field (`control_mode`). In #779 that cost a full round of diagnosis:
  the reporter's diagnostics said `is_controllable: true` for a device he had
  set to **Mode: Off**, which was correct and looked exactly like the bug we
  were chasing. Capability and permission are now separate fields with separate
  names, and each load row in diagnostics prints both plus the verdict
  (`may_actuate`) — so *"why didn't SEM shed X?"* and *"why did SEM start X?"*
  are answerable from one line. Nothing you configured changes meaning; the old
  field is still emitted, derived. One real over-report fell out of the split:
  the "how much can we shed?" counters used to include loads set to **Off**,
  which shedding would never have touched. (#780)
- ⚡ **Chargers get a Max Amps setting — every EVSE was silently capped at
  32 A** — SEM has shipped a per-charger *Min Amps* slider since #193 and never
  a maximum. The ceiling came from `max_charging_current`, a config key that no
  setup step and no entity ever wrote: the dashboard's *add charger* button
  minted it as a hardcoded `32`, and nothing could change it afterwards. A 48 A
  wallbox therefore charged at two thirds of its rating with nothing in the UI
  to explain why. There is now a **Max Amps** slider (6–80 A) beside Min Amps on
  the Config tab, writing `ev_max_current` — the key the decision layer already
  read. Existing installs keep the ceiling they had: the slider seeds from the
  old key, and the three places that build a charger's ceiling now resolve it
  through one function instead of three literals, so raising the slider actually
  raises the commanded current rather than being flattened back to 32 A by the
  hardware clamp. (#746)
- 📝 **The docs stopped teaching controls that were deleted four releases
  ago** — a release-prep audit found the `night_charging`,
  `smart_night_charging` and `tariff_optimized` switches still documented as
  live user controls across README, USER_GUIDE, TROUBLESHOOTING, SETUP_GUIDE
  and EV_CHARGING_LOGIC. #277 Phase C removed all of them in v1.6.3 and folded
  their intent into one `select.sem_charger_<id>_charge_mode`, but the prose
  never followed. The worst of it inverted the actual behaviour: USER_GUIDE
  told users night charging was "opt-in (off by default)" and to enable it via
  a switch that does not exist — when the shipped default is `Min + Solar`,
  which charges overnight by design. Every instance is now written against the
  mode selector, with an explicit per-mode table, and the `Solar only` +
  "At least" floor contract (#634/#679) spelled out where it decides the
  outcome. (#783)
- 📝 **Every dashboard card now carries a description and a help link** — the
  31 bundled cards split 15 correct / 14 with a doubled `custom:` prefix in
  their `type` (HA prepends it, so the picker built `custom:custom:sem-…` and
  could not instantiate them) and 2 with no `type` at all — one of which was
  `sem-energy-plan-card`, the headline card of 2.0. None of the 31 carried a
  `documentationURL`, so no card had a route from "I am looking at this" to
  "here is what it does". `docs/DASHBOARD_GUIDE.md` gains a full card
  reference — one section per card, named, placed and described — and each
  card's editor help link now lands on its own section. Pinned by
  `tests/test_card_registry_metadata.py`, which derives the anchor from the
  tag and verifies both ends, so the next card cannot ship without one. (#783)
- 🗑️ **The old system diagram card is gone; 2.0 keeps only the one the
  dashboard renders** — `sem-system-diagram-card` was defined by two files
  holding two *different* implementations: a 983-line vanilla standalone and
  the 1814-line Lit version in the bundle. Both were registered as Lovelace
  resources, and `semDefineCard` is first-wins, so which card you got came
  down to resource load order. The bundle always won in practice — it defines
  at module evaluation while the standalone waited on a `semReady` queue — so
  the vanilla copy had not rendered for anyone in a long time. It is deleted,
  along with the `sem-shared.js` / `sem-reactive-base.js` base layer it was
  the last consumer of; all three URLs are cleaned up from existing installs
  on the next restart. An 11 KB `sem-system-diagram.svg` that shipped and got
  copied into `/config/www/sem/` on every dashboard generation went with it —
  nothing in the repo's history ever referenced it, not even the card that was
  just deleted. Copies already on disk are left where they are. (#784)
- 🐛 **Generating the dashboard no longer stalls Home Assistant** — the
  `generate_dashboard` service read `manifest.json` and listed the card
  directory directly on the event loop. HA guards both calls and logs
  "Detected blocking call … by custom integration solar_energy_management";
  on a Pi with an SD card or a network-mounted `/config`, every other
  integration on the box waits out the syscall. A third one hid behind two
  call hops: the per-file cache-bust hash, opened once per registered card,
  from a helper the service reached through a nested function. All three now
  run in the executor — the pattern the same handler already used three times
  over — and the cache-bust hashes are read in a single hop before they are
  needed. An AST lint (`tests/test_no_blocking_open_in_event_loop.py`) walks
  every shipped module against HA's real guard list, following calls out of
  the coroutine rather than only what is written inside one, so the next one
  is caught in CI rather than in someone's log. (#785)
- 🐛 **The energy diagram draws a balance that adds up again** — #699 gave the
  cards an atomic per-cycle snapshot so the arrows can't pair a stale solar
  reading with a fresh EV one. The diagram card's half of that fix was written
  into the standalone copy — the one that never rendered — so on screen the
  diagram had been reading each term off its own entity the whole time, and
  during a source-cadence skew the flows visibly failed to close. Ported to
  the card that actually ships. The Huawei modbus flicker hold (#455/#488)
  stays in front of the battery reads, which the snapshot deliberately does
  not hold, and a test now pins both halves so neither fix can silently
  displace the other. (#784, #699)
- 🔍 **Two new entries in the bug-class ledger** (`docs/BUG_CLASSES.md`) —
  **44**, two implementations answering to one name under a first-wins
  registry, where load order picks the winner and the loser can collect
  maintenance for months without a symptom; and **45**, a guard whose boundary
  is lexical while the runtime's is reachability — the reason a green lint sat
  next to a live log naming the line it had just cleared. Each ships with the
  sweep question and the guard that fails CI. (#784, #785)
- 📝 **Assorted doc corrections** — minimum HA version (2024.1.0 → the
  2025.1.0 that `hacs.json` actually requires), `min_solar_power` default
  (500 W → 1000 W), translation-system size (1166/1116 keys → the real 1341 ×
  16 languages), the config-flow step count (3 → the 2 that remain after the
  #442 slim install), per-battery control entities (`number.sem_battery_<id>_mode`
  → `select.…`; a `_force_discharge_power` entity that never existed → the
  fleet-wide `number.sem_battery_max_discharge_power`), "Allow arbitrage"
  listed as a battery mode it is deliberately not (#533), a TROUBLESHOOTING
  log line no longer emitted anywhere (the charger reconciler owns that path
  since #392), and stale ARCHITECTURE/MULTI_CHARGER sections still teaching
  the #589-retired context swap, the PR #358 strategy machine, the #440
  `EVIntelligenceData` skip fields and a `budget_w` that moved to
  `ChargerDecision` in #651. (#783)
- 🐛 **A second heat pump is drawn as a heat pump, not as an anonymous plug**
  — more than one climate unit has been supported since the one-device-list
  work: `register_surplus_device` with `device_type: climate` persists the
  kind, the device is rehydrated, prioritised and controlled correctly. What
  was wrong is the row the sensor hands the frontend: the service-registration
  branch wrote `"device_type": "service_device"` as a literal, throwing away
  the kind the caller passed. The card's icon map knows `climate` and
  `heat_pump` but not `service_device`, so every service-registered device
  fell through to the generic socket — and a working second heat pump that
  renders as a plug reads, reasonably, as "my heat pump was not added". The
  row now reports the stored kind, with the old literal kept only as the
  fallback for registrations persisted before the kind was stored. (#788,
  found in #685)
- 🐛 **The night is planned and sized from the same charger** — nothing
  writes `ev_max_current`: there is no field for it anywhere in the config
  flow (#746), so every read of it is a read of its default. The defaults
  disagreed — six sites said 32 A and five said 16 A — and `ev_control.py`
  disagreed with itself forty lines apart, planning the night-charge ceiling
  at 32 A and then sizing how much energy the night can deliver at 16 A. On a
  32 A charger the night looked half as deliverable as it is, so SEM believed
  it had to start earlier and book more cheap hours than the night needed. No
  over-current ever reached hardware — the adapters clamp every command to the
  charger's own rating — which is why this sat unnoticed: the damage was to
  the arithmetic. All thirteen sites now import `DEFAULT_MAX_CHARGING_CURRENT`
  (32 A, in `consts/core.py` since the first release, with two importers), and
  an AST lint fails CI on the next bare number. (#789, found in #746)
- 🔍 **Bug-class ledger gains 46** (`docs/BUG_CLASSES.md`) — a value with one
  source of truth restated as a literal at the site that uses it, in its two
  shapes: the duplicated default that drifts (#789) and the payload branch
  that hardcodes what its sibling derives (#788). The lesson recorded with it
  is #716's: fixing one call site does not fix a duplicated default, so the
  guard is an AST lint over the package rather than an assertion about two
  functions. (#789, #788)

# [2.0.0-beta.5] — 17.08.2026

- 🐛 **A device's settings are no longer managed as if they were loads**
  (#781) — 24 of one user's 50 Load-Management rows were WLED *settings*:
  "reverse", "freeze", "night light", "sync send". Each landed controllable
  with 0 W, so a peak event could flip an LED strip's reverse setting looking
  for watts that were never there. The cause is that discovery asked only
  "is this a switch I can pair with a power sensor" — and one
  `sensor.wled_*_power` pairs with every sibling switch, because the name
  match is a substring test. Home Assistant already answers the question SEM
  wasn't asking: an entity marked *configuration* or *diagnostic* is a
  device's own knob, never its primary control. SEM now reads that mark
  everywhere the class lives — pattern discovery, the per-device control
  pick (an appliance's child-lock is not its actuator), and the light-fixture
  filter, which a strip's setting switches used to defeat. An entity the
  registry doesn't know is still kept, not guessed at. And because rows a
  previous version already wrote are never re-derived, they now retire
  themselves on the next refresh — leaving hand-registered devices and
  charger rows alone.
- 🐛 **A multi-channel relay can no longer be bound to its neighbour's
  channel** (#781, the control half) — the same digit-stripping name match
  that paired one WLED power sensor with every sibling also ran on the
  *control* side, where being wrong is worse: a misbound meter reports the
  wrong watts, a misbound relay **switches the wrong circuit** — SEM shedding
  the freezer believing it is the towel heater. On a Shelly Pro the digit IS
  the channel, so `kanal_1` and `kanal_2` cleaned to the same name, and a
  bare substring test fails one character later (`kanal_1` is inside
  `kanal_10`). Control matching now requires the digits to survive: the exact
  name, or the same name extended at a word boundary (`_relay` names the
  channel, it doesn't renumber it). A looser candidate is refused outright —
  "no control found", monitoring only, is the honest answer when the
  alternative is actuating someone else's circuit.
- 🐛 **A meter that reboots no longer books its whole lifetime as today's
  energy** (#782) — one heat pump reported 15,508.51 kWh *today* against a
  house total of 33.47. Its counter had reset to 0 and come back: SEM caught
  the drop and re-based, then read the lifetime total against a baseline of
  zero and booked the difference — 5.6 GW in one ten-second cycle. Two
  changes. A delta is now checked against what its window could physically
  deliver: no single house load draws 100 kW, so the bound only ever catches
  counter pathology, never usage — and it is *not* the device's rated power,
  which is an estimate and must never overrule a meter. And a counter that
  falls now remembers what it fell *from*, so when it comes back SEM books
  the genuine consumption across the outage instead of everything or nothing.
  The window is measured from when the counter's value last changed, so an
  hourly utility meter, a sensor that was unavailable for half an hour, and a
  baseline restored across a restart all still book their real energy.

# [2.0.0-beta.4] — 16.08.2026

- 🐛 **"Mode: Off" now means SEM keeps its hands off, including its books**
  (#779) — a dishwasher, heat pump and network switch all configured Off were
  switched off by SEM anyway, reproducibly within seconds of a restart: turn
  it back on, SEM takes it away again. One flag, written by a path that
  couldn't know what it means. SEM records whether it *started* a load, and
  exactly one rule acts on that: *the mode moved to Off while SEM was driving
  this — so stop it once and let go.* That rule is right. But the per-cycle
  check that lets SEM notice a switch someone else turned on was adopting
  **ownership** along with the observation, at every mode — and a switch
  being on cannot tell you who switched it. So a load the user turned on
  under Mode = Off was claimed by SEM on the next cycle, and the release rule
  read that claim and stopped it. After a restart the first cycle does it,
  which is why it looked like the restart. SEM still *watches* the load at
  every mode — Off is monitoring, and the runtime and energy books stay
  honest — but it only claims a load it is actually allowed to drive. Closed
  structurally rather than patched: all three paths that adopt a running load
  now go through one writer that holds the mode check, the two duplicated
  checks at the call sites are gone, and a lint fails the build if a fourth
  path ever claims ownership on its own.
- 💡 **Small loads report their real draw instead of "~1 kW"** (#744) — a
  discovered load is built from its power sensor, which reads 0 W for as long
  as the load is *off*; SEM turned that 0 into a 1 kW placeholder and then
  had no way to tell the placeholder from a measurement. Every learning path
  is up-only — right for a measured peak, and the reason a shower light on a
  Shelly PM drawing 8 W was pinned at exactly 1 kW forever: the calibrator
  refused a smaller number, the store kept only ratings above 1 kW, and the
  7-day history seed threw away anything below it. The placeholder now
  carries a label, so the first real reading replaces it in **either**
  direction and only then does the up-only ratchet apply. Three consequences
  go with it: the priority card shows `~8 W` instead of `~1.0 kW`, the load's
  surplus-activation threshold stops demanding a kilowatt before an 8 W bulb
  is ever offered, and a house of 47 small loads stops presenting 47 kW of
  phantom demand to the planner. Estimates still never teach the model — a
  load with no power sensor keeps the honest placeholder. Fixed on the
  service-registration path in the same pass: no rating given is no longer
  stored as 1 kW, and those rows read the live calibrated rating like every
  other row already did.
- 🧹 **A config field you empty now stays empty** (#627) — Home Assistant
  leaves a cleared optional field out of the submitted form altogether, and
  every page merged what it received with `update(user_input)`. That merge
  cannot tell "left alone" from "emptied", so **41 fields across 8 pages**
  could be re-pointed but never taken back: the twelve `phase_guard_*`
  current/power/voltage sensors, the tariff entities, the heat-pump relays,
  the battery discharge control entity, and the per-charger entities #627
  gave a surface to in the first place. Mis-pick one at setup and the only
  recorded cure was deleting the integration. Every page now merges through
  one helper that asks the form it just showed which fields it offered, and
  records a cleared field explicitly — so the clear also survives the merge
  with whatever initial setup wrote. An AST guard fails CI if a page goes
  back to merging by hand.
- 🔌 **A second EV charger no longer starts life as a copy of the first**
  (#627) — the add-charger page filtered already-installed boxes out of its
  suggestions by `_device_id`, a key auto-discovery puts on a *discovery* and
  that nothing ever writes onto the *stored* charger. The filter therefore
  never matched, every discovery always looked new, and charger #2 came up
  pre-filled with charger #1's sensors and its control service. Accept the
  suggestions and SEM held two configs for one box: the first was driven
  twice, the second never moved. Chargers are now recognised by the entities
  they point at — what actually gets stored, for every charger, including the
  one the initial setup flow creates and which can never carry a
  `_device_id`.
- 🛡️ **A hands-off install now boots hands-off** (#777) — the persisted
  toggles (`observer_mode`, `vacation_mode`, `energy_plan_actuation`) can be
  recorded in three places: the config entry's options, its data, or — on an
  install predating the persisted toggles — only in the switch entity's own
  restore store. The switch reads all three. Setup read the first two and
  built the coordinator from the default, so on such an install SEM came up
  **armed** and only learned it was supposed to be observing when the switch
  platform attached, minutes later on a busy start. Live-hit on a test box
  wired to a real charger and battery. Setup now resolves the flags from the
  same three sources, in the same order, *before* the coordinator exists, and
  writes what it recovers into the config entry — so the answer stops
  depending on a store Home Assistant prunes after seven days. Nothing
  changes for an install that has ever toggled a switch or been created by
  the current setup flow: those already carry an explicit record.

# [2.0.0-beta.3] — 16.08.2026

- 🔭 **Observer mode now cuts at the write, not before the decision** (#764) —
  simulating SEM was supposed to mean "every layer runs for real, only the
  final hardware command is cut". That held for loads. For EV chargers and
  batteries the cut sat *above* the decision: observing skipped the whole
  block, so no adapter was built, `decide()` and `decide_battery()` never
  ran, and there was nothing to observe. A two-battery rig reported
  `adapters = {}` / `last_decisions = {}` in diagnostics and read as a
  misconfiguration. All three families now branch in the same place — inside
  the actuator — and publish what they WOULD command on the standard
  `would_decisions` surface (keyed `ev:<id>` / `battery:<id>`, with the same
  transition-gated bus event loads use). The #740 police pass — which stops
  a charger that self-started outside its mode — goes through the same seam,
  so observing a rogue draw now reports it instead of opening a real
  contactor. Startup recovery, the one real write left in the battery
  pipeline, stays skipped while observing, the #536 setpoint zeroing is
  untouched, and an AST lint fails CI if any `actuate` / `actuate_battery`
  call site forgets the flag. Live behavior is unchanged: with observer off,
  every path is exactly what it was.

- 🧹 **The WOULD surface retires devices that stop deciding** (#764) — the
  map is a roster, not a ledger: it answers "what would SEM do right now",
  so a device that no longer decides leaves it at the end of the cycle,
  edge state included. Caught within a cycle of the fix going live — the
  legacy single-charger fallback decides once at startup, before the fleet
  is populated, and its row then sat on a one-charger rig reading as a
  second charger. Same class as #744. Deciding to leave a device alone is
  still deciding: a battery or charger set to `off` keeps its row and
  reports the hands-off command, so an absent row means SEM has no opinion
  about that device rather than an opinion of "do nothing".

- 🩺 **Diagnostics report the charger adapter again** (#764) — the dump read
  `coordinator._ev_adapters`, an attribute production has never had (the
  cache is `_charger_adapters`), so `adapter_class` came back `null` on
  every dump since #357 and the Wallbox pause-switch discovery block below
  it — the entire reason #357 exists — was unreachable on real hardware.
  The tests missed it because each one assigned the invented name to its
  own mock; they now use the name the coordinator writes, and a pin fails
  if the two ever drift apart again.

- 💡 **The arbitrage line only appears where arbitrage can actually happen**
  (#533 / #638) — the advisor runs on every plan by design: it is the one
  reader of *every* page of the ledger, so an economically absurd verdict is
  the first symptom of books that lie. But its readout was printed on the
  plan card of installs where trading is switched off, so a battery quietly
  sitting in `auto` on a flat tariff got told *"no room to buy into: battery
  6.3/15.0 kWh full…"* — which reads as though SEM wanted to trade tonight
  and the battery was in the way. Nothing was ever going to trade. The plan
  now carries **whether arbitrage is open** (a battery in *allow arbitrage*,
  or the scheduler toggle) next to the verdict, and the card prints the line
  only then. The audit is untouched: the verdict still rides on the
  `arbitrage` attribute and the `ENERGY-PLAN … arbitrage:` log line on every
  install. The mode scan behind it now lives in exactly one accessor instead
  of an expression the card had no way to ask.

- 🔌 **A device set to Mode = Off was still switched off** (#779, @onkelfu) —
  after upgrading to 2.0, appliances the user set to Mode = Off (a
  dishwasher, and reportedly a heat pump and network gear) kept getting
  switched off by SEM. The same physical device appeared **twice**: the
  registry's Energy-Dashboard row (`energy_dashboard_<slug>`, which carries
  the user's Mode setting) and a stale `load_device_<slug>` smart-switch row
  left over from a pre-2.0 version's pattern discovery. With the unified
  registry active that legacy discovery is turned off, so the ghost is never
  rebuilt — but the sync's prune spared every `load_device_*` key (to protect
  EV chargers), so it survived every restart. The ghost carried no mode, so
  Mode = Off on the visible row never reached it and the peak-shed loop
  actuated the appliance behind the user's back. SEM now folds the ghost at
  the data layer when it shares the same on/off control as an
  Energy-Dashboard device — dedup on the control surface, not the name, and
  never on a power or energy sensor, which a derived or multi-channel device
  can legitimately share — and de-persists it so the duplicate is gone for
  good after the upgrade. A smart plug with no Energy-Dashboard twin is
  untouched. Sixth instance of bug class 12, and the non-charger twin of the
  #748 fold.

# [2.0.0-beta.2] — 16.08.2026

> The first night of 2.0 on real hardware, read off one dashboard card.
> Four of these five are the same shape: something written, tested and
> believed — but asked at a place the running code never reaches, or
> asked before the question that decides whether it applies at all.

- 💡 **Lights really are skipped now** (#744) — the beta.17 rule that keeps
  light fixtures out of SEM's device roster was added to a code path no live
  install reaches: the unified device registry re-derives the roster from the
  Energy Dashboard on every refresh and never learned it, so the lights came
  straight back. The rule now runs at that one authoritative boundary — which
  means an already-imported light retires itself on the next refresh, no
  reset needed. A metering plug feeding a lamp is still kept, and an
  explicitly registered device is still never touched.
- 🧹 **A device the registry no longer knows leaves Load Management too**
  (#744) — `energy_dashboard_*` rows were spared from the prune because the
  prefix means "registry-managed", which stops being true the moment the
  registry stops deriving it. Such a row survived in Load Management's own
  store forever: shed-eligible, in diagnostics, invisible to the fix that
  removed it.
- 🧹 **"Not scheduled tonight" lists candidates, not the whole roster**
  (#744) — a device that was never asked for guaranteed runtime cannot be
  a night demand in any mode, so it no longer prints a why-not row. The
  mode gate used to answer first, which made an Energy-Dashboard roster
  publish its own default state every night (`control_mode` defaults to
  peak-only): 9 rows of "device mode excludes surplus control" on a
  12-device install, ~45 on a 47-device one. A device that *does* ask for
  runtime and is excluded by its mode still says so — that answer was
  never the noise.
- 🏷️ **Left-out rows carry the device's name** (#744) — the card fell back
  to the raw id (`energy_dashboard_shellyplus1pm_441793d5470c`) because
  the label was only assigned after every gate passed, so exactly the rows
  that needed a name never got one. The slug's width also pushed each
  reason into a wrapped ribbon on a phone.
- 🏷️ **The log tag is the honest mode of the stamp** — six planner lines
  written in the shadow soak still said `(shadow #638)` on actuating
  installs; they now carry the real mode, guarded by a source test.

# [2.0.0-beta.1] — 15.08.2026

> **Why 2.0 and not 1.8.** This release changes what an existing install does
> without the user changing anything:
>
> - **Night actuation is on by default.** The migration writes the value down
>   explicitly and tells you where the kill-switch is (#758) — the answer is
>   recorded rather than implied, and an install that had already turned it
>   off is never touched. But an install that never made the choice now has
>   SEM driving hardware overnight.
> - **The private cheap-window pickers are deleted.** A `solar_plus_cheap`
>   install's night timing now comes from the joint plan, not from the code
>   path it has been running. Same intent, different decision-maker.
> - **An uncovered battery no longer force-charges** — deliberate, with a
>   named reason on the card rather than silence.
> - **The phantom-EV model is gone** (#652), so the battery scheduler no
>   longer sizes its window against a car it invented.
> - **The overnight planner is now the energy planner**, and the kill-switch
>   moved with it: `switch.sem_overnight_actuation` →
>   `switch.sem_energy_plan_actuation`. SEM renames the entity for you and
>   carries your on/off answer across, so nothing changes behaviour — but an
>   **automation or dashboard that names the old entity must be updated**.
>
> Any one of those is a major bump. Calling it 1.8 would invite people to
> upgrade expecting minor-release behavior. The number is about
> compatibility, not size.

### ✨ The one-gate unification (#638)
- 🎯 **One selector left.** The EV's private cheap-window pick and the battery
  scheduler's own window pick are DELETED — the joint plan's blocks are the
  only WHEN for scheduled energy use. A CI ratchet fails any new
  `find_cheapest_hours` caller forever.
- 🔋 **Battery: scheduler says WHAT, plan says WHEN.** `decide_battery`
  force-charges only inside the plan's battery block; the SCHEDULED verdict
  survives reboots beside the plan; the schedule entity derives from the
  plan's blocks (same shape). The negative-price override stays reactive and
  bypasses the gate. Closes the #652 phantom-EV model.
- 🌡️ **Comfort banking actuates.** `comfort:` demands merge with `load:`
  demands per device (the ID mismatch that kept banking runs from ever
  firing); a WILLING band runs inside its planned block — the one sanctioned
  place the plan creates a run.
- 💱 **Arbitrage sell path wired, valve closed** (#533 stands): plan says
  WHEN, live economics say WHETHER, per-battery mode says MAY; power capped
  at the block-implied watts and fleet-split.
- 🛡️ **Fail-open, per family, visibly:** EV uncovered → charges at the floor;
  battery → no force-charge; every verdict change logged once
  (`#638 coverage:`) and shown on the card as a translated "reactive — why"
  chip. 12 new i18n keys ×16 languages.
- 📇 **"Not scheduled tonight"** on the Energy Plan card: every deliberate
  exclusion named with its why (mode / no car connected).
- ⚙️ **`energy_plan_actuation` defaults ON** — with the selectors retired,
  default-off would silently remove cheap-window timing; the switch remains
  the kill-switch.
- 📏 **One planning peak** — the EV's peak-managed rate now sizes against the
  same hysteresis-adjusted level the ledger plans with (night top-up amps
  drop by one hysteresis band: intended).

### 🏷️ The overnight planner is the energy planner (#638)

It was named for the night it started with, and it outgrew the name: it
packs the daytime surplus window, comfort banking in a free hour and the
cheap-hours loads as readily as it packs the night. A name that says
"overnight" tells a user their daytime devices are somebody else's problem.

- 🔀 **`switch.sem_overnight_actuation` → `switch.sem_energy_plan_actuation`.**
  SEM renames the registry entry on upgrade — one entity, one history, no
  unavailable orphan — and carries your on/off answer across so nothing
  changes behaviour. **Update any automation or dashboard that names the old
  entity.** A switch you had renamed yourself keeps the name you gave it.
- 💾 **Tonight's stamped plan survives the upgrade.** The stored plan is read
  under its old key once and rewritten under the new one, so upgrading at
  23:50 does not reshuffle the night the plan is steering.
- 📖 `docs/OVERNIGHT_PLANNER.md` → `docs/ENERGY_PLANNER.md`; the log prefix
  `OVERNIGHT-PLAN` → `ENERGY-PLAN`; the card, its ~85 translated strings and
  every internal symbol follow. The genuinely night-shaped settings keep
  their names — "Finish overnight from", "Use battery overnight" and the
  night-charging window all still mean *the night*.

### 🧠 The learning layer (#755) — the plan learns what it got wrong

- 📓 **The third number.** The plan recorded what each demand ASKED and what
  the packer PROMISED; what it actually DID was never written down. A
  per-demand outcome recorder now integrates real power across the night —
  one unit, straight through midnight, in the durable store — and splits it
  two ways: inside the planned block vs. outside, and covered by the gate
  vs. not. "Fits" is now a claim somebody checks.
- 🚫 **An estimate may never be recorded as a measurement.** Every sample
  carries a `measured` flag; one estimated sample marks the whole night
  untrainable, silence is not a measurement of zero, and a gap in the record
  (restart, dead sensor) is refused rather than integrated across. This is
  the #743/#744/#753 bug class nailed shut at the recorder's door — and
  again at the learner's.
- ☀️ **Self-consumption is an objective now, not a side effect.** The night
  ledger prices a surplus slot at the feed-in revenue it costs to consume it
  (`electricity_export_rate`, default 0.075) instead of at zero. Solar used
  to win by fiat; now it wins on the numbers — and a genuinely cheaper night
  hour is allowed to beat it. With no export tariff the rate is 0 and the sun
  really is free. Each night also records its predicted vs. achieved solar
  share.
- 📈 **The learner reads only the nights that can teach.** A night may LOWER
  an ask only if the demand got its full grant and stopped on its own;
  everything else is censored from above and can only raise a floor. The
  suggestion is a high percentile of the teaching nights (never a mean —
  interruption noise runs one direction), gated behind a cold-start minimum,
  and it never writes anything: it suggests.
- 🗣️ **The morning verdict, on the card, in 16 languages.** "What the record
  shows" gives every demand one line — *still learning · the ask matches
  what it uses · usually needs about 7.4 kWh of the 10.0 kWh asked · uses the
  full ask every night, it may need more* — plus the night's solar-share
  line. It rides its own attribute so it survives the daytime hours, which is
  exactly when it gets read.

### 🌙 What the first actuation night taught (#756, #759, #760)

N1 (12→13.08 on the .175 rig) ran the whole machine end-to-end — zero
errors, clean hand-back — and caught three ways a plan can describe a
night that cannot happen. All three are the same lesson: **the collector
must mirror every gate the executor enforces**, and every input that
shapes the demand set must ride the re-plan signature.

- 🚗 **The ask is bounded by the car, not the calendar** (#756) — the night
  target is `target − daily` off a counter that rolls at midnight, so at
  00:01 a car at 100 % was asked for its full 20 kWh — and under the peak
  cap the phantom displaced the real loads (the heizband went fits→yields
  at exactly 00:01; the morning unplug flipped it straight back). The
  taper detector's "still full" — anchored at a completed charge with
  nothing drawn since — is now the collector's third mirrored gate, the
  card lists the car under "not scheduled tonight — car is already full"
  (×16 languages), and the fullness flag rides the signature so the car
  filling up mid-night re-plans.
- 🌤️ **A forecast wiggle is not a changed night** (#759) — the raw solar
  forecast sat in the demand signature, and a value living at a bucket
  edge (66.9↔67.1 around the 67 boundary) re-planned the night four times
  in 110 seconds, flipping every demand's coverage each time. The term now
  anchors with 3 kWh hysteresis: jitter orbits the anchor forever, a real
  provider revision re-anchors once, and a transient forecast outage keeps
  the anchor instead of flapping to zero and back.
- 🔥 **A stopped load is not a demand** (#760) — the heizband's comfort
  band read the room at 22.01 °C (past target+offset → banked), which is
  a hard stop the intent enforces ABOVE the tier-2 clause — the executor
  rightly refused all night, while the plan packed 2.0 kWh and said
  fits+COVERED. The stop condition is now the fourth mirrored gate, and
  it rides the signature so the room cooling back into the band re-plans
  and re-admits the demand within a cycle. An in-process oracle now pins
  the whole property: covered + in-block + every tier-2 gate green ⇒ the
  device starts.

### 🌙 What the second campaign night taught (#765, #766)

- 🕰️ **Time passing is not the night changing** (#765) — the price term
  fingerprinted the *sliding* upcoming-prices window, so a past slot
  dropping off the front restamped the plan every hour on the hour (10
  restamps in a night with prices at absolute timestamps identical
  throughout). The term now carries (absolute timestamp, price) pairs and
  the comparison knows one rule: a shared timestamp's price changing
  replans, tomorrow's curve landing replans, a past slot expiring is
  silence. An old-format stored signature replans once after upgrade,
  never crashes. Second sighting the same day, next term over: a RUNNING
  load's shrinking deficit crossed a 0.1 h bucket every 6 minutes — one
  replan per bucket for as long as it ran. Shrinking-but-nonzero is now
  silence too (the plan working is not the ask changing); a deficit
  growing, a demand appearing or vanishing, or the stop flag flipping
  stays news.
- 👁️ **Belief follows the switch, every cycle** (#766) — `is_active` was a
  belief only SEM's own activate/deactivate (plus one-shot adoption at
  registration) ever updated, so a switch turned ON outside SEM — an
  external actuator, a user's hand, a box self-start — stayed invisible:
  never seen active, never deactivated, runtime never accrued (the N2 pool
  ran 00:00→07:50 against an idle belief, honestly flagged unmeasurable by
  the outcome recorder). Every load now syncs belief to observation each
  cycle — the per-cycle twin of the restart adoption, strictly for
  on/off-domain control entities so a charger's current number can never
  read as ON.

### 🌞 What the third campaign night taught (#759)

- ☀️ **Watch what the plan reads, and let production explain the rest**
  (#759, second sighting) — the supply term watched the forecast's *day
  total*, a number the plan builder consumes nowhere. What it does consume
  is the hours still **ahead** and **tomorrow's** day. With live dampening
  the total is rewritten every half hour as the correction re-prices hours
  that have **already been produced**: 11 restamps in 7.3 hours on the rig,
  one of which (16:42:05, 42 → 38 kWh) rebuilt byte-identical blocks — the
  plan proving, in its own output, that nothing had changed. Tomorrow's
  forecast — the sunrise floor and the room arbitrage may buy into — was
  watched by nothing at all. Now: the term is the hours ahead plus
  tomorrow, and the day burning down is explained by **measured
  production** (expected remaining = anchored remaining − produced since
  the anchor), so a day going to plan is one signature from dawn to dusk
  while clouds, or a genuine revision, still re-anchor once. Without a
  production reading — or with a frozen counter (#681) — it degrades to the
  plain 3 kWh deadband: never worse than before.
- 🚪 **A term behind a closed gate cannot re-plan anything** (#759, third
  sighting — same rule, three more instances). The demand collector stops at
  the charge **mode** before it ever asks the plug or the car, and at a
  load's control **mode** (then night-eligibility) before it asks the deficit
  or the room — but the signature asked anyway. So a plug blip on an `off`
  charger, a car filling up on one, a deficit ticking down on a `peak_only`
  or day-only heater each restamped a night that could not possibly change:
  on the rig the mode sat at `off`, the shared charger's plug flickered for
  one cycle, and the plan restamped **twice**, both times emitting
  byte-identical blocks. The signature now mirrors those gates exactly,
  including their fail-**visible** direction — an unevaluable gate still
  watches the term.
- 🔁 **A revision re-plans; only a changed answer re-stamps** (#775).
  Forecast.Solar re-publishes hourly, and on a weather-volatile night each
  revision is real — ±10–16 kWh, past any honest deadband — so PROD
  re-planned at 00:14, 01:14 and 02:14 without a single packed block
  moving. The night still re-plans on every revision, but the rebuilt
  answer is now compared against the stamped **decision** (blocks,
  verdicts, why-nots, cost, the arbitrage actionables) and an identical
  repack keeps its stamp: `computed_at` marks a decision, and an identical
  repack is free. Manual re-plans always stamp — "decide again, now" must
  visibly answer, even with "same answer".

### 🧪 Simulation is a standard feature now (#764)

- 👁️ **Observer mode publishes its WOULD decisions** — the per-device map
  rides `switch.sem_observer_mode`'s `would_decisions` attribute (fresh
  reads, no history needed), and every decision *transition* fires a
  `solar_energy_management_observer_decision` bus event (edges, never a
  heartbeat — a wobbling watt is not a transition). A closed-loop
  simulation of any device is now a five-line HA automation instead of an
  SSH log scraper.
- 📖 **`docs/SIMULATION.md`** — the standard workflow, written down: observer
  mode as the simulation boundary, simulating every input with plain HA
  entities, running scenario cases back to back in minutes, and the
  provocation set (stamp loss, reboot survival, kill-switch). Born from the
  N2 campaign night, where the whole edge-case matrix ran in one evening on
  the dedicated rig.

### 🔍 A silently skipped reconciliation now says so (#628)

- 👁️ **Counter-backing is visible.** The all-or-nothing rule (a partial
  counter read must never adopt) is correct — but the skip was invisible,
  so a category with an unreadable counter ran as a pure stopwatch
  indefinitely and the first symptom was a numbers-don't-match report
  weeks later. Now: one transition-gated line when a category flips
  counter-backed ↔ unbacked (a healthy boot stays silent; a counter dead
  *from* boot logs, because that is exactly the invisible case), and the
  diagnostics download carries per-category backed/skipped cycle counts —
  "was export ever reconciled on this install?" becomes one look.

### 🪵 A log line is a transition, not a heartbeat (#762)

- 📉 **The debug firehose is off.** Measured on the test rig: a *steady*
  system repeated the same six decision lines ~8,000 times a day
  (`decide_battery → normal` 1423×, `Charging strategy: idle` 1792×,
  `Scheduled delayed save` 1930×, …), which shrank the host's log ring to
  ~2 minutes — burying the once-per-night lines that matter — and drowned
  the excerpt HA's native "Enable debug logging" toggle hands you. Every
  measured offender now goes through one shared gate: an unchanged
  decision is silent, every change logs, a flap logs each edge. Wobbling
  measurements inside a reason (`limit 594 W` → `602 W`) don't count as
  change — the decision does. The zero-information delayed-save heartbeat
  is deleted outright; sensor outages log one line going silent and one
  coming back.
- 🤫 **At default log level SEM stays quiet** (0 INFO lines in a measured
  2-minute PROD window) — nothing changes for normal installs. Debug is
  the standard HA flow: the integration page's *Enable debug logging*
  button (the manifest declares its loggers), which now produces a
  readable story instead of a heartbeat dump.

### 🐛 Found by auditing the branch as a whole (#757, #758)

- ⛔ **A stop repeated 1800 times is not a stop** (#757) — the one-gate build
  changed the *shape* of the battery decision: `decide_battery` now returns
  STOP_FORCE_CHARGE on every cycle a SCHEDULED battery sits outside its
  block, so a 21:00 verdict with an 02:00 window asked the inverter to stop
  a charge it was not doing, all evening, on the same serial Modbus link the
  read coordinator uses. Every adapter's stop is now a no-op when nothing is
  being forced — the #538 idempotency treatment, one layer up. A stop that
  fails still leaves the intent alone, so the next cycle retries.
- 🔔 **Nothing switches on silently on upgrade** (#758) — night actuation
  drives real hardware and defaults to on, which is right for a fresh
  install (the user chose the feature) and wrong for an upgrade (nobody
  chose anything). The migration writes the value down — same answer,
  recorded instead of implied — and posts one notification naming the
  kill-switch. An install that had already turned it off is never touched.
- 🕳️ **A dead battery meter is no longer recorded as an idle battery**
  (#758) — `battery_power` falls back to 0.0 W when its sensor cannot be
  read, and the night ledger recorded that as a measured zero, which is
  exactly the "silence is not a measurement" contract the learning layer is
  built on. The reading now carries whether anyone actually looked.
- 📦 **The plan's byte budget counts everything that lands on the entity**
  (#758) — the trim ran before `tomorrow` and the morning `review` were
  appended, and HA's recorder drops *all* attributes above 16 KiB. Going
  over did not truncate the plan; it erased it from history. One place adds,
  one place counts, and a second pass drops the extras (saying so) if
  dropping the timeline was not enough.
- 🔌 **The kill-switch is asked by every caller** (#758) — the arbitrage sell
  gate reached the plan directly, so a user who turned night actuation off
  still had the plan discharging their battery to the grid.
- 👻 **A fresh install no longer wakes up in observer mode** (#777) — the
  observer switch has a forced-stable entity id and HA's restore-state
  store outlives the config entry, so a fresh installation on a machine
  that ever ran observer-ON restored the dead install's state over this
  install's explicit config — and silently never controlled hardware as
  its first impression. Explicit config now beats ghost restore: the
  switch seeds from options (every flip persists there immediately), then
  entry data (the install flow records all three toggles now), then the
  default; a restored state is honored only when no config record exists
  at all — a legacy install upgrading, the one case it still serves. Same
  precedence for the vacation and night-actuation switches, and the
  install-time observer choice finally reaches the switch face (it was
  written to data but read from options — checked-at-install showed OFF
  while the coordinator observed).
- 💱 **Exported battery energy is attributed and paid once** (#776) — the
  flow ledger deliberately disallowed the battery→grid-export pair ("SEM
  doesn't support battery-to-grid arbitrage"), which stopped being true the
  moment `Force discharge` shipped and the plan-gated sell was wired: during
  any battery export the exported watts vanished from the flow attribution,
  while the savings math booked the **raw** discharge — an exported kWh
  earned avoided-import savings it never delivered *and* export revenue at
  the meter. One kWh, two credits. Now a `battery_to_grid` flow (new sensor
  pair `Battery to Grid` W / kWh, ×16 languages) receives what solar's
  export claim leaves, and discharge savings are scaled by the
  home-delivered share — exported kWh earn exactly their export revenue,
  once. A cycle without flow attribution keeps the legacy full credit
  (silence is not a measurement of "all exported"). The new sensor doubles
  as the compliance witness for installs whose grid contract prohibits
  selling stored energy: it must read zero there, and the arbitrage doc now
  says so up front.
- 🛡️ **An arbitrage sell respects BOTH reserve floors** (#638) — the sell
  branch took the user's backup reserve *or* the verdict's
  `arbitrage_reserve_soc`, never both, so any install with a nonzero backup
  reserve (all of them) silently lost the arbitrage floor: a 20 % backup
  reserve overrode the 50 % "never sell below" promise, and the hardware
  actuator (Huawei end-SOC, setpoint batteries) was handed the lower number
  to enforce on its own between SEM cycles — the #532 drain class one seam
  later. Both floors now bind and the higher wins. Found by the arbitrage
  scenario sweep; the full mode × gate × floor matrix is pinned in
  `test_638_c6_arbitrage_sell.py`.
- 🧹 **The planner entry point the tests used does not ship** (#758) — a
  flat-slot "compat" adapter with no production caller, and two test corpora
  pointed at it, proving things about a night that cannot happen (every slot
  cheap, no house load, an infinite battery, no peak limit). Moved to
  `tests/synthetic_night.py` with its four fictions written down; the tests
  that matter now drive the real `build_night_ledger` + `pack_night` pair.
  The #653 orphan guard, which had only ever walked class bodies, now reads
  module scope too — and immediately found a second one.

### ⚖️ Closing the energy balance (#767)

- 🔌 **Every controlled load now counts its own kWh** (#768) — SEM accrued
  *seconds* per device and nothing else, so a pool pump, heizband or heat pump
  disappeared into the `home` residual, which is computed as a leftover and
  therefore can never complain. Each device now books a daily energy figure
  every cycle, in a fixed order of evidence: its energy counter's delta first,
  then its power sensor integrated over the cycle, and only if it has neither,
  `rated_power` × runtime — the last flagged as an ESTIMATE that may never be
  fed back as a measurement (#755). A sensor that can't be read is recorded as
  blind seconds, not as a device drawing zero watts. Persisted per meter day,
  counter baseline included, so a same-day restart books the energy the meter
  saw while HA was down instead of losing it.
- 🌡️ **The heat pump gets a ledger row** (#769) — on a heat-pump house the
  largest controllable load in the building had no kWh anywhere. It now has
  the same four horizons every other consumer has (today / month / year /
  total), keyed off the **sunrise** meter day the device itself rolls on, so
  there is one day boundary in the system rather than two that disagree every
  morning. Alongside them: **Shifted today** — the part SEM actually caused,
  counted only while SG-Ready was asking for BOOST or FORCE_ON. Energy the
  pump's own thermostat would have taken anyway is kept out of that number,
  which is what turns "SG-Ready shifted X kWh" from a claim into a
  measurement. The split mechanism is generic (a device names its own
  bucket), so the additional heat pumps of #685 arrive with it already
  working.
- 🔋 **A bought kWh does not become free by sitting in the battery** (#770) —
  every discharge was credited at the full import price as if the battery
  only ever held sunshine. On a house that charges in the cheap valley that
  is not a saving, it is a purchase moved a few hours; and the one-gate
  build just made grid charging routine, so the error was about to grow.
  The battery is now inventory with a cost basis: each charge is filed as
  solar or grid by the flow that caused it (fleet-split by per-battery
  charge power), each discharge draws proportionally, and savings pay only
  the difference between what a kWh cost and what it displaced. Energy of
  unknown origin keeps the old full credit — it is not punished for a
  measurement SEM doesn't have (#755). The pool is pinned to the measured
  SOC every cycle so integration drift can't invent stored energy, and an
  offline SOC sensor pins nothing, because silence is not a measurement of
  an empty battery. The stored-grid-share sensor shows **no value, not 0 %**,
  until the pool holds energy whose origin SEM actually watched arrive — a
  freshly restarted install claiming "nothing was bought" off an empty pool
  was the same contract violation one layer up (caught on the .175 soak's
  first night). **Autarky is corrected with it**: battery discharge is
  own supply only for the solar-charged share; the rest is grid supply that
  was time-shifted. Four new sensors make the number auditable — today's
  charge from solar, from grid, what the grid part cost, and the grid share
  of what is stored right now. (Self-consumption was checked and is already
  correct — it is measured against solar, not against the battery, so it
  was never affected.)
- 🧮 **The per-device breakdowns now reconcile against the fleet identity**
  (#771) — SEM publishes per-charger daily kWh, a per-charger origin split
  and per-PV-string energy, and none of them was ever checked against the
  fleet row it decomposes: a renamed charger's stale bucket kept being
  published and the sum double-counted (the #761 shape) with every total
  still agreeing. A health check now reconciles all three — over-count only,
  because shortfall has three *legitimate* causes (the 4-string discovery
  cap, per-charger deadline rollover, upward counter reconcile) and a check
  that fires on healthy hardware gets muted. A violation names every member
  and marks the one that is no longer configured. The per-battery breakdown
  in the issue's table was **deleted, not reconciled**: it had no producer —
  `EnergyTotals.per_inverter`/`per_battery`, `InverterRuntime`, and the
  `InverterFlows`/`BatteryFlows` slices (whose comment claimed a
  conservation invariant "holds by construction" over code that never
  constructed them) were data-shaped surface with nothing behind it, and a
  checker over a dict nothing fills can only ever say "verified". Ratchet
  tests keep the surface deleted.
- 🌡️ **Comfort energy exists now, split by plan placement** (#772) — comfort
  is the one demand family where the plan *creates* runs, and it left no
  energy trace at all. A zone's kWh (accrued like any device, #768) now
  files under "inside its planned block" or "outside", derived at the filing
  seam from the same `comfort:` gate the actuation layer consults. The
  in/out ratio is the first honest answer to "is banking working here" — a
  pre-cool that ran the AC at 03:00 *and again at 17:00* books the same
  in-block energy as one that banked four hours of coasting; the difference
  lives entirely in the out bucket. A disengaged band files no claim, and
  "no plan tonight" files as *out*, so an idle planner cannot look like a
  perfect one. This is the feedback #705 Ph3 decides blind without.
- 🏠 **The residual is audited: True Baseload** (#773) — with every
  controlled load carrying a kWh, `home` stops being a black box and becomes
  a subtraction: `home − Σ(controlled loads)` = the house SEM does *not*
  touch, whose defining property is that it is boring. Two new sensors
  (`True Baseload` W + `True Baseload Today` kWh) publish it — **negative
  values included**, because a negative baseload is the sharpest possible
  finding (a double-count or a sign error) and clamping it would hide
  exactly the fault the number exists to expose. Its day-to-day drift is a
  free sensor-health check with the #628 discipline: a day without a home
  row is a refused gap (never a zero), and a breach names its suspect — the
  device or the home row whose own day-over-day move explains the step.
  Each sealed day records the *size* of its estimated portion, and the
  drift check accepts a day whose estimate is too small to move a verdict
  (≤ 0.5 kWh against the 2 kWh band) — gating on "no estimate anywhere"
  would let one meterless pool pump silence the check forever, which is
  dormancy wearing discipline's clothes. Days with a larger estimate stay
  gaps: they display but never train or compare. The
  controlled-loads subtrahend is a midnight-keyed mirror booked at the
  filing seam, because device days roll at sunrise and subtracting across
  that boundary is the #703/#704 bug class.

### 🐛 Found on PROD hardware (#774)

- 🔌 **A car drawing 8.7 kW is not a full car** (#774) — the Energy Plan card
  read "not scheduled tonight: car is already full" while the charger pushed
  8760 W into it. The virtual-SOC deficit is only ever *raised* by a vehicle-SOC
  reading or the daily driving decay, and that decay runs at midnight rollover
  **while the car is disconnected** — so charge-to-full → unplug → drive →
  replug the *same day* leaves the "full" reference standing, and the deficit,
  clamped at zero, can never move off the floor no matter how many kWh flow in.
  Energy delivered beyond what the reference says the pack was missing now
  refutes that reference: SEM drops it and reports the SOC as unknown until a
  real reading, a taper anchor, or the session bootstrap re-arms it. How far
  the car was actually driven is unknowable — only that it was further than we
  thought — and inventing the replacement number is what caused this.

### 🐛 Found by the simulation campaign (#638, #753)

- 🔌 **A missed poll is not an unplug** (#638) — SEM's own entities
  contradicted each other inside one update: `binary_sensor.sem_ev_connected`
  read `off` in the very cycle `binary_sensor.sem_charger_<id>_connected` read
  `on`, both projected from the same `coordinator.data`. One question, two
  authorities: the session layer counted a disconnect only after three
  confirmed cycles (the UDP-blip absorber, #35/#595/#753), while everyone
  else read the raw plug sensor. A single dropped KEBA poll therefore
  restamped the night with the car dropped from the plan and the blip
  clearing restamped it back (two re-plans against #638's one-stop/one-start
  guarantee), and — the sighting that showed how wide the class was —
  `sensor.sem_charging_state` fell to *System ready* three times in three
  minutes while the charger reported the car connected throughout, which on
  real hardware also ends the session and sends the charger a `disable`.

  The debounce now runs **once, at the source**: the cycle's plug reading is
  confirmed the moment it is read, before the plan, the state machine, the
  per-charger decisions, session tracking or any entity sees it. There is no
  raw answer left in the cycle for a consumer to disagree with, so the fix is
  structural rather than a patch per call site (fourteen of them). A
  *connect* stays immediate — a plug-in still stamps within the cycle — and
  the boot warm-up still never counts (#753). Measured on the clone with the
  plug held continuously connected for three minutes: **5 plan-membership
  flips and 5 re-stamps before the fix, 0 and 0 after.**

- 🌙 **"Nothing to schedule" is an answer, not an error** (#638) — on a night
  where nothing needs the night (battery full, EV at target, no load asking),
  the plan is stamped with its lists deliberately empty and says why. The
  actuation gate read that empty shape as a plan with no period and answered
  *no span* for every device — a reason the card has no sentence for, so it
  fell through to **"plan unreadable"**. Live on production 15.08 12:10:51:
  the battery, ten loads and the comfort demand all told the user the plan
  was unreadable while the plan was perfectly readable and simply idle. The
  gate now names the quiet plan honestly (*nothing to schedule tonight*, in
  all 16 languages), and a test pins the whole class: every reason the gate
  can emit must have a card sentence, or be declared one of the three where
  "unreadable" is the truthful answer.

- 💱 **A quiet night is still a night** (#638) — on the same "nothing to
  schedule" night, the plan came back with no price axis, no
  self-consumption expectation and **no arbitrage verdict at all**. Not a
  missing advisor: an ordering bug. The quiet answer was returned *before*
  the night ledger was built, so everything derived from that ledger was
  absent exactly in the regime where the arbitrage verdict is the only
  thing left to say — and the shadow arbitrage demand, which is the whole
  plan on such a night, could never be created. Two runs of the same
  campaign script showed it: with one unrelated pool pump asking for the
  night the card read *buy 0.4 kWh @ ~0.10, deliver 0.3 kWh @ ~0.20 — est
  +0.01*; with nothing asking, the same battery, the same prices, the same
  hour — nothing. The books are now opened first and the quiet answer
  speaks after them: it carries the hour strip, the battery trajectory,
  the expected self-consumption share and the arbitrage verdict, with only
  the scheduling empty. The advisor's contract — *advice always, because an
  absurd advice is the first symptom of books that lie* — is true in every
  regime again, and the opt-in sell path (still off by default, #533) can
  see its blocks on such a night at all. One consequence had to move with
  it: the gate told a deliberately empty plan apart from an unreadable one
  by *no demands **and** no hours* — true only while the quiet plan showed
  no hours. Publishing the ledger made every device read *not in plan* —
  the sentence for "the plan left YOU out", on a night it left everyone
  out on purpose. The quiet regime is the empty demand list; the hours are
  the books, not the schedule.

- 🛑 **The kill-switch now takes hold on the card too** (#638) — with night
  actuation switched off, the plan's coverage list still showed loads as
  *covered* while the EV row correctly read *actuation off* (clone, 15.08).
  The card was reading the transition **log's memory** rather than asking the
  gate: a demand is written into that memory only when somebody evaluates it,
  and the load gates are evaluated from a pass that returns early the moment
  actuation is off — so every load kept displaying the answer from before the
  switch was flipped. The one surface a user checks to confirm the
  kill-switch took hold was contradicting the kill-switch. The verdict is now
  **evaluated per publish** by a single shared evaluator that both the log
  line and the card go through; a test pins that the "is actuation on?" rule
  exists exactly once in the coordinator, because two copies is how they came
  to disagree.

- 🔇 **Every load left out of the plan now says why** (#638) — since the
  legibility work, an EV the planner skipped explained itself on the card
  (*mode excludes night charging*, *no car connected*, *car is already
  full*). Loads had no such answer: the collector dropped them in five
  different places — mode, no runtime left, already at target, daytime-only,
  no measured power — and every one of them was silent, so *"why isn't my
  heater in tonight's plan?"* had nowhere to be answered. On the clone four
  devices vanished from the plan with no explanation anywhere. Each skip now
  emits a machine reason that rides the plan payload beside the EV ones and
  renders in all 16 languages, on both the busy and the quiet plan. A test
  pins the class: a reason with no translation fails the suite.

- 🚗 **A car that is charging is not a full car** (#756) — the planner asks
  the taper detector whether the car is still full, so a phantom EV cannot
  eat the night's peak budget. But "still full" is anchored energy
  accounting: it is the deficit below full, charging *subtracts* from it,
  and it clamps at zero. So the instant a real charge delivered the last of
  the deficit, the detector reported a full car while the meter showed
  3.9 kW going into the pack — and stayed there until the pack had
  overdrawn the anchor by 0.1 kWh, about 90 seconds later. In that window
  the night was re-stamped around a car that had just been dropped from it,
  and re-stamped back when the anchor gave way (production, 15.08
  11:50:52). The fullness question is now asked in **one** place — a single
  accessor shared by the demand collector and the re-plan trigger, so they
  cannot answer it differently — and that place also reads the charger's
  own meter: a car drawing above its charger's handshake threshold is never
  answered as full. A genuine sub-handshake trickle still reads full, so
  the phantom-EV fix (#756) is untouched.

### 📚 Documentation

- 📖 **README, ARCHITECTURE, SETUP_GUIDE and EV_CHARGING_LOGIC now describe
  the seam that actually exists.** Four places still taught the retired
  machinery — the battery scheduler "picks the cheapest hours", the EV's
  night step 5 doing its own cheap-window arithmetic, `find_cheapest_hours`
  listed as a live pipeline step, and a co-scheduling "Night Charge Schedule"
  whose classes were deleted in this release. Each now names the real
  decision-maker (plan owns WHEN, reactive owns WHETHER) and what changes for
  the user — including that with the kill-switch off there is no planned
  pre-charge at all.
- ⚠️ **KNOWN_LIMITATIONS no longer says arbitrage is "deactivated in v1.7.3"**
  — it is wired and shipped in 2.0, dormant on every default, and the entry
  now leads with the grid-connection-agreement warning and names
  `sensor.sem_flow_battery_to_grid_power` as the compliance witness.

### 🙏 Thanks

SEM is built and maintained by one person. 2.0 took a long build and a longer
soak on real hardware, and the people below paid for the time it took —
thank you.

- 💛 **[@praun](https://github.com/praun)**, **[@RienduPre](https://github.com/RienduPre)**,
  **[@Azlinon](https://github.com/Azlinon)** and **[@onkelfu](https://github.com/onkelfu)**
  for sponsoring the project. (Sponsors who chose to stay private aren't
  named here — the thanks is the same.)
- 🐞 **@RienduPre** and **@onkelfu** again, on the other side of the tracker:
  a large share of the bugs fixed on the road to 2.0 exist as fixes because
  they were reported precisely.
- 🙌 Everyone who filed an issue, posted a diagnose dump, or answered a
  question on the forum. A single-maintainer project sees exactly as many
  hardware combinations as its users show it.

If SEM saves you money, a [monthly sponsorship](https://github.com/sponsors/traktore-org)
keeps it maintained.

# [1.7.6-beta.19] — 16.08.2026

### 🐛 Fixes
- 🔌 **A device set to Mode = Off was still switched off** (#779,
  @onkelfu) — after upgrading to 2.0, appliances the user set to
  Mode = Off (a dishwasher, and reportedly a heat pump and network gear)
  kept getting switched off by SEM. The same physical device appeared
  **twice**: the registry's Energy-Dashboard row
  (`energy_dashboard_<slug>`, which carries the user's Mode setting) and
  a stale `load_device_<slug>` smart-switch row left over from a pre-2.0
  version's pattern discovery. With the unified registry active, that
  legacy discovery is turned off, so the ghost row is never rebuilt — but
  the sync's prune spared every `load_device_*` key (to protect EV
  chargers), so it survived every restart. The ghost carried no mode, so
  Mode = Off on the visible row never reached it and the peak-shed loop
  actuated the appliance behind the user's back. SEM now folds the ghost
  at the data layer when it shares the same on/off control as an
  Energy-Dashboard device (dedup on the control surface, not the name),
  and de-persists it so the duplicate is gone for good after upgrade. A
  smart plug with no Energy-Dashboard twin is untouched.

> Last release of the 1.7.x line. Development continues on 2.0.

# [1.7.6-beta.18] — 14.08.2026

### 🐛 Fixes
- 🔋 **One battery counted twice — home read ~2× while charging** (#761,
  @jappish84) — a two-sensor battery `power_config` (the #551 "Two
  sensors" mode) leaves the combined `battery_power` unset *by design*
  (net = charge − discharge from the pair). The battery power deriver
  only checked that field, so it added the device's combined power sensor
  BESIDE the pair: two power representations of one physical battery,
  enumerated as units b1+b2 with identical values and summed. Battery
  read double while charging, and home — derived from the balance —
  followed (12.7 kW against a real 1.1 kW). Affects every two-sensor
  battery install since the deriver shipped; the derive now runs only
  when the battery has **no power representation at all** (pair and
  inverted-single count as representations). The sign-inversion half of
  the report was resolved live with the one-tap battery-sign flip.

# [1.7.6-beta.17] — 14.08.2026

### 🐛 Fixes
- 💡 **Lights are filtered out at the Energy Dashboard import** (#744,
  @Azlinon) — lighting has no energy-management use case: not shiftable,
  not a surplus sink, and shedding a 30 W dimmer is user-hostile for
  savings that round to zero. Lights only ever entered SEM as a side
  effect of ED consumption monitoring, and then displayed wrong on/off
  state (Matter dimmers reading On while off — a dimmer idling below its
  power sensor's floor is exactly the shape the power heuristic cannot
  judge). Auto-import now skips any ED device whose only on/off surface
  is ``light.*``, with one log line saying so. A metering smart plug
  feeding a lamp keeps its row (the plug is a real control), and the
  explicit ``register_surplus_device`` path stays unfiltered for the
  rare relay-exposed-as-light case. HA's dashboard is a consumption
  ledger; SEM's device list is a control roster — the two are no longer
  conflated.

# [1.7.6-beta.16] — 13.08.2026

### 🐛 Fixes
- 🚗 **A stop war strobed a Mercedes into a latched charging fault** (#763,
  @onkelfu) — on a Modbus-integrated KEBA P30 (generic number+switch
  control), SEM's stop works, but the box re-closes the contactor on the
  car's retry at its stored 6 A; SEM stopped it again every 10 s cycle, and
  ~2 h of aborted handshakes latched the car's charging fault (physical
  replug required). The reconciler now counts stop→redraw round-trips and
  after three declares a **ceasefire**: it stands down for 30 min and warns
  once — a strobing contactor is worse for the car than a few kWh of
  unplanned minimum-current charge. The mirror of the #536 enable backoff;
  a charge episode or a quiet spell ends the war. The durable-stop
  refinement for this wiring follows once the reporter's ena-register data
  answers who re-closes the contactor.

# [1.7.6-beta.15] — 13.08.2026

### 🐛 Fixes
- 🔋 **Battery STOP flooded the Modbus bus between charge blocks** (#757, from
  Guido's release/1.8 audit) — while the scheduler is idle/target-reached it
  repeats a STOP_FORCE_CHARGE verdict every cycle, and each brand adapter
  re-issued the inverter stop each time (~1800 writes/night on the single
  serial link, colliding with the huawei_solar read coordinators — the #538
  failure one layer up). The stop now fires once, on the transition, and stays
  silent afterwards (the command_off pattern), with honest retry so a failed
  stop still retries instead of stranding the charge. Swept across Huawei,
  generic and GoodWe; Deye was already safe.
- 📏 **A 24 W load calibrated itself to ~1 kW** (#744, @Azlinon) — for loads
  without a power sensor, the energy-tick estimate (0.01 kWh over a short
  window ≈ 1 kW instant) fed the up-only rated-power ratchet, which re-based
  its own cap on every adoption and climbed geometrically. Calibration now
  requires a real power sensor; the energy deriver stays a display/runtime
  estimate — a guessed number never teaches the model (the #743/#753 class).
- 🔍 **EV stop-decision internals reach the diagnostics download** (#708,
  promised to @Azlinon) — the taper latch, session peak, SOC anchor (+ its
  timestamp) and the stability give-up streak/backoff are now in the
  download; no more guessing from source. The "SOC anchored at 100%"
  announcement now reports the observation: the charge completed.


# [1.7.6-beta.14] — 11.08.2026

### 🐛 Fixes
- 🔌 **A restart mid-charge silently rewrote the session** (#753, spotted
  live by Guido: top chip 1.6 kWh vs the charger's own 6.0 kWh) — the #282
  session persistence worked, but the restart's sensor warm-up published a
  false "disconnected", the end-detection finalized the session and a fresh
  one started when charging resumed — amputating session cost and solar
  share. A disconnect now only counts once CONFIRMED: never in the first
  two minutes after boot, and only after three consecutive disconnected
  cycles (which also absorbs the KEBA UDP blip family).
- ⚡ **Load shedding never throttled the EV charger** (#747, reported by
  @Azlinon) — peak reached CRITICAL, the freezers shed, and the EVSE held
  32 A: the load manager's deliberate charger exclusion assumed decide()
  peak-manages the EV, but the peak state never reached the daytime
  decision at all. The peak posture now resolves once per cycle into the
  fleet state and decide() applies a senior clamp in EVERY mode
  (always_max included): SHEDDING clamps to the effective minimum current,
  EMERGENCY idles the charger. The EV throttles before anyone's freezer.
- 🔋 **"Forcible-discharge power entity" wrote raw watts with no unit
  validation** (#749, reported by @praun) — a kW-native setpoint received
  3000 (full tilt after its range clamp) and a current-native number would
  take watts as amperes. The write now shares the discharge-limit path's
  one validation rule: non-power units refuse loudly, kW scales at the
  service-call boundary, and the de-dup threshold stays honest watts.
- 🔌 **The charger-duplicate fold never reached the surplus roster** (#748
  follow-up, found by audit) — beta.11 removed a duplicate charger row from
  the card and from load management, but the registry syncs to **two** systems
  and `_sync_to_surplus_controller` had no charger-identity fold at all. So an
  Energy-Dashboard row whose *control* entity is a configured charger's
  start/stop switch was still registered as an independent surplus device: the
  daytime surplus loop could reach for the charger's stop switch behind the EV
  controller's back — the exact hazard beta.11 set out to close — while the
  card showed nothing, because the display fold hid the row it could not
  remove. The energy planner (#638) packs its load demands from that same
  roster, so a duplicate carrying a minimum-runtime goal could additionally
  enter the night ledger twice — once as the charger, once as a load. The fold
  now runs where the device is **registered**, not only where it is read, and
  the three rosters share one predicate so they cannot drift apart again. It
  also runs the moment the charger roster arrives, closing the ~35 s window
  after every restart in which the registry has synced but does not yet know
  which entities belong to a charger.

# [1.7.6-beta.13] — 11.08.2026

### 🐛 Fixes
- 🔌 **Power-only loads still read "Off" and showed ~1 kW** (#744, reported by
  @Azlinon) — the follow-up to beta.12. That fix taught the priority card to
  read a load's **switch**, but a load with **no** on/off entity (a Shelly Plus
  PM mini at a sustained 400 W, a furnace blower at 250 W, a Powercalc-backed
  light) still read "Off" and showed the 1 kW placeholder. Root cause: SEM took
  a load's live-power sensor only from the Energy Dashboard's `stat_rate` link,
  which HA's individual-device UI never collects — so `power_sensor` was empty,
  live watts read `0`, and the power fallback said "Off". Solar/grid/battery
  already recover this by finding the companion power sensor on the energy
  sensor's own device; loads now do too. On a multi-channel device (a Shelly
  2PM) each channel maps to its own power sensor. The derivation is display-only
  — it never changes which loads SEM can control or shed. (by @traktore-org in #744)

# [1.7.6-beta.12] — 10.08.2026

### 🐛 Fixes
- 🔌 **A device that is ON read "Off" in the Device priority list** (#745,
  reported by @Azlinon via #744) — load-management on/off in the card payload
  was inferred from **power alone**, so a switch-controlled load whose own power
  sensor idles below its reporting floor (a Shelly PM, or a Powercalc-backed
  `light.*` drawing under a watt, publishes `0 W`) rendered "Off" while
  `switch.x` / `light.x` said `on`. The control layer already reads the switch
  authoritatively; only the display payload had diverged to a power-only copy,
  so the two on/off predicates drifted. The card row now prefers the device's
  **own control-entity state** — a `switch` / `light` / `input_boolean` is
  authoritative — and falls back to power only when there is no readable on/off
  entity (a current `number.*`, an integration service, an unavailable switch).
  The control path is unchanged; this is purely the displayed state.

# [1.7.6-beta.11] — 10.08.2026

### 🐛 Fixes
- 🔌 **One physical EV charger produced three rows in the Device priority list**
  (#748, reported by @jappish84 via #628) — #700's charger-identity fold that
  was meant to collapse the duplicate ran only in the card payload, so it
  never removed the row from load management: the duplicates stayed live,
  `controllable`, and could act on the charger's own start/stop switch behind
  the EV controller's back. Three defects, all fixed at the identity/data
  layer. (1) A charger is now identified by *every* entity it declares — its
  start/stop switch, current-limit number, status sensor and control entities,
  not only its power sensor — so the fold finally catches an Energy-Dashboard
  row (e.g. a Swedish "Billaddare") keyed on the stop switch. (2) Smart-switch
  auto-discovery no longer rediscovers a switch already wired as a charger's
  start/stop as if it were a separate smart plug — which is what *added* the
  third row when the user configured start/stop. (3) A new data-layer reconcile
  drops any load-management row that shares a configured charger's entity —
  keeping only the authoritative per-charger row — and **de-persists** it, so
  existing installs shed the stale duplicate on upgrade instead of carrying it
  forever. It runs even on installs with no Energy-Dashboard individual devices,
  and fails safe if a charger is missing its id.

# [1.7.6-beta.10] — 10.08.2026

### ✨ Enhancements
- ☀️ **The curtailment probe — harvesting solar an export limit hides** (#743,
  opt-in, default off) — inverters that cap grid export (permanently, or
  dropping to 0 W at negative prices) clamp production to local consumption,
  so the measured surplus honestly reads ~0 while the array could deliver
  kilowatts more. Raising consumption is the only instrument that reveals the
  hidden power, so the probe IS the measurement: when the forecast says far
  more than the array delivers, export is pinned at ~0 and production ≈
  consumption, SEM starts the EV at minimum amps — and keeps charging only if
  production rises to follow within the window (a failed probe backs off for
  15 minutes and costs ~2 minutes of minimum-amps draw). In harvest, one
  ladder step of headroom keeps the climb alive toward the forecast, and
  every step must be followed by production or the climb stops at the array's
  real potential — no step is ever taken on faith. Brands that publish their
  export limit sharpen the detection: the limit entity is auto-detected on
  the inverter's device (Huawei active power control, GoodWe grid export
  limit, SolaX export control, Victron max feed-in, …) — "limit active"
  fast-tracks the probe, "no limit" suppresses false probes entirely; a
  manual **Export-limit entity** field overrides for exotic setups. Options →
  EV Settings, both fields labelled across all 16 languages. Requires a solar
  forecast integration ("power now"). Every tick records the terms it judged
  into the per-cycle trace (`diagnose` service) — a probe that DECLINES leaves
  no mark in the meters, so without that record "why didn't it fire?" has six
  indistinguishable answers.

### 🐛 Fixes
- 🔌 **The "can't enforce the SOC cap" repair fired for chargers with no car
  on them** (#708, reported by @Azlinon) — the gate asked whether *the fleet*
  was charging, so with one car on a SOC target and a second EVSE idle, both
  boxes raised the repair and the empty one announced its own target. It now
  asks whether **this** charger has a vehicle connected
  (`_last_ev_connected_per_charger`, the same map the virtual-SOC decay uses);
  a charger the map hasn't seen yet defaults to connected, so missing tracking
  can never silence a warning that matters. An AST guard now walks every
  per-charger repair raiser and fails CI on a fleet-scoped gate. The repair's
  own text was wrong too, and is rewritten in all 16 languages: SEM does **not**
  simply charge to taper — from the last real reading of the session it counts
  delivered energy and stops on the measured total; the taper fallback applies
  only when no reading has arrived at all.
- 🚗 **A stop SEM commanded read as "the car is full"** (#708, reported by
  @Azlinon) — the taper-to-full anchor fires on "declining, then under 50 W for
  ~30 s". A car finishing and a charger SEM just switched off produce the
  identical reading, so a mid-session stop pinned virtual SOC at 100 % and the
  night's charge was skipped on it. The anchor now requires that SEM has not
  **withdrawn** an offer it made — withdrawal, not absence: observer mode zeroes
  every setpoint and an uncontrolled box never had one, and taper-to-full must
  keep working there. Second door closed at the same time: the declining phase
  was a one-way latch, so a car that dipped and came back to full tilt was still
  remembered as tapering; it now clears when the draw returns to ≥ 70 % of
  session peak (`TAPER_RATIO_DETECTED` read backwards) and re-latches on the
  next real decline.
- 🕐 **The SOC provenance line vanished exactly when it was needed** (#708,
  reported by @Azlinon) — "Car: 63 % (12 min ago) · est. now ~71 %" dropped the
  moment the vehicle-SOC sensor went unavailable, which is the same moment the
  card promotes the *estimate* to the main gauge: the estimate took over the
  display precisely when its provenance disappeared. Both keyed off the same
  live mirror going null. Underneath sat a measurement bug — an unavailable
  entity writes a NEW state, so `last_changed` dated the **outage**, not the
  reading, and a sensor dead for half an hour reported "0 min ago". SEM now
  remembers the last usable reading and the instant it was taken and publishes
  both as attributes, so the line survives the sensor it describes. Published as
  a timestamp rather than an age on purpose: an age attribute moves every minute
  and would re-arm the #581 recorder churn — the card ticks the clock itself.
- 🔍 **Export-limit autodetect had no anchor on Energy-Dashboard installs**
  (#743) — SEM takes its solar sensor from HA's Energy Dashboard on most
  setups, leaving `solar_production_sensor` empty; that empty key was the only
  anchor the device scan got, so the brand sharpening never ran on the very
  Huawei install it was written for. The ED-resolved solar power (or the
  lifetime-yield counter, when solar power is derived) now anchors the scan.
  Found live on HA-PROD.

# [1.7.6-beta.9] — 09.08.2026

### 🐛 Fixes
- 🔋 **The charging badge honors the 500 W actual-charging floor** (#739,
  live on PROD 08.08.2026) — `binary_sensor.sem_ev_charging` said
  "Charging" at 140 W standby with the charger disabled: the published
  badge was the raw brand charging boolean (the signal the codebase itself
  documents to distrust — KEBA's lags ~5 s, numeric state codes read truthy
  at idle), and the plug-sensor physics inference's 100 W threshold sat
  BELOW the box's own standby draw, inferring a phantom connection. Both
  now use the one floor every adapter's `actual_charging` already applies
  (500 W — a real ≥6 A charge is ≥1.38 kW, so no genuine charge is ever
  suppressed), whenever a power source is configured; installs with only a
  charging boolean keep the raw signal. Per-charger entries are judged on
  their own power reading and the fleet flag follows the gated map.
- 💶 **Fixed Time-of-Use plans now classify by their tiers, not by a
  rolling window** (#728, second round — @Azlinon's weekend test) — a
  fixed-tier plan's cheap/normal/expensive are structural (the plan's 2–5
  named rates), and the rolling percentile window leaked exactly where the
  reporter predicted: Saturday's flat publish flooded it (the ordinary mid
  rate outranked into *expensive*), the genuine 3× peak collapsed into the
  flat-day guard (all four breakpoints landed inside the flooded tier,
  spread 0.0000 → *normal*), and 55 steady weekend hours converged to
  all-NORMAL. When the curve is a small set of repeating discrete values —
  detected, not configured — SEM now classifies by distinct value tier
  (cheapest → cheap, middle → normal, highest → expensive), stable across
  any window and any publish event; a 7-day tier ledger carries the weekday
  rates through the flat weekend. The percentile window remains for
  genuinely continuous curves (Nordpool / Tibber / Amber untouched). And a
  level once displayed for a past hour is never rewritten — the price
  history is append-only in both modes.
- 🔌 **The quota-stop: the wallbox's own language for "no"** (#553/#545,
  live-proven on the real P30) — `keba.disable` invites the war: the box
  auto-starts, the car begs, SEM kills, every ~90 s, all night. And the old
  1 kWh guard's `set_energy` AFTER disable never persisted — the register
  read 0.0 all evening, a silent no-op since #553 shipped. The KEBA-shape
  stop is now the quota-hold (the user's own proven script order): park the
  current at the viable minimum, write `session + 0.3 kWh`, enable — the
  box charges the small remainder, suspends itself natively, and refuses
  the car with SEM's hands off (ten unpoliced minutes of silence in the
  live test, the evening's first). Legacy disable remains the fallback when
  the box's session register is undiscoverable. A fresh plug-in resets the
  session and wakes SEM to re-decide.
- ⚡ **Min is a floor — enforced at the wire** (#545, reopened) — the start
  ladder offered 6/8/9 A below a configured 10 A minimum, the stability hold
  froze 8 A, and a Zoe (whose onboard charger cuts out below ~10 A) flapped
  to 0 W and stayed there with an active mode and a hungry car. A nonzero
  command now never reaches the charger below the configured minimum —
  commanded ∈ {0} ∪ [min, max], clamped in the one emit seam beneath every
  ladder, zone and hold. Zero stays zero (the stop intent). The wallbox was
  innocent: its registers mirrored every command faithfully.
- 🔌 **A stopped KEBA now locks itself off — the dead-man's OFF** (#740) —
  an Off-mode P30 kept feeding the car in ~3 kW bites through a SEM restart:
  masterless, the box's failsafe watchdog re-authorised its *charging*
  fallback, and firmware auto-start retries defeated repeated `keba.disable`
  calls for ~13 minutes. The watchdog cannot be turned off over UDP (#546,
  live-tested) — so SEM now points it at **0 A** after every stop
  (`set_failsafe timeout=10s fallback=0 persist=1`; fallback 0 is documented
  as "disables the running charging process completely"): the box itself
  enforces *off means off* across restarts, UDP loss and auto-start retries,
  until the next SEM start sequence re-arms the charging failsafe. Mid-charge
  behavior unchanged (a dead controller still lands the car on the charging
  floor, never on 0). Same `keba_arm_failsafe` opt-out as before.
- 🌙 **The night gate skips participation, not supervision** (#740, the
  latent night sibling) — in the two night states an `off` / `solar_only`
  charger was `continue`d out of the per-charger loop before its reconciler
  ever ran, so a box auto-starting masterless at night drew unpoliced until
  a day state returned (the gate-blocks-activation-but-doesn't-stop-the-
  running-device class, 5th sighting). An opted-out charger now gets a
  minimal reconcile pass before the skip: a rogue draw converges to DISABLE
  immediately, a converged charger emits nothing (no churn against the
  quota-hold).

# [1.7.6-beta.8] — 08.08.2026

### 🐛 Fixes
- 🏷️ **Options-flow fields now show real labels instead of raw keys** (#737) —
  six options steps rendered 37 `snake_case` schema keys as their labels (the
  whole **Deye forced-grid-charge** step, **EV charger add/edit**, **battery
  scheduler**, the #550 **Invert grid sign** toggle and the **tariff
  classification mode**) because the keys had no `strings.json` entry, and HA
  reads only `translations/<lang>.json` at runtime. All are labelled and
  translated across the 16 languages — including the 18 `deye_program_*` slots
  the original audit undercounted. A new guard
  (`test_737_options_flow_label_coverage.py`) walks every `async_step_*` schema
  and fails if any field ships without a label, so bug class 24 cannot regrow.
- 🌡️ **Comfort section no longer hides right after registering a device**
  (#705, reported by @onkelfu on beta.7) — the goal editor's Comfort section
  was gated on the live device payload, which only exists once the surplus
  controller has materialized the device; right after `register_surplus_device`
  (or a restart) the section hid and then "appeared later by itself". Every
  non-EV/non-battery load now shows the section immediately; the live chip
  still waits for real data.

### ✨ Enhancements
- 🌍 **sem-localize split per language** (#738) — the translation bundle had
  grown to 1.2 MB, parsed by every browser to use exactly one language. It is
  now a 68 KB loader with English inline as the fallback floor plus one lazy
  `sem-localize.<lang>.js` per language, injected on demand and re-dispatching
  `sem-localize-ready` so cards upgrade seamlessly. Cache tokens follow
  `translations.json`, the `/local` www mirror carries the siblings, and the
  documented `scripts/regenerate_localize.py` entry point now delegates to the
  split generator so the monolith cannot silently come back.
- 🔌 **Charger efficiency is now a setting, not a hidden storage key** (#735) —
  **Options → EV Charger → Charger efficiency (%)**, default 92 %. SEM converts
  the kWh your charger meters into kWh that actually landed in the pack, and
  that conversion drives every number it reports about charge state: the SOC
  estimate on the EV card, the virtual SOC for installs with no vehicle sensor,
  and the first-session bootstrap. 92 % suits a warm pack on a three-phase
  charger; single-phase at 3.7 kW or a cold start in winter runs several points
  below it, and until now the only way to say so was to hand-edit
  `.storage/core.config_entries`. Lower it if the estimate runs ahead of what
  the car reports, raise it if it lags. The field offers 50–100 % — exactly the
  range the estimator will honour, so a value that saves is a value that takes
  effect. What you type is a percentage and what is stored stays the fraction
  everything downstream reads, converted in one place rather than at each end;
  a value already in storage that the estimator was ignoring now shows as the
  default instead of as a figure outside the field's own range, which the
  dialog would have refused to close on. The stop guard from #708 is unaffected
  and stays on a fixed 0.92 by design — it decides when to *stop*, where erring
  low charges longer and puts energy in the pack that cannot be taken back out.

# [1.7.6-beta.7] — 07.08.2026

### ✨ Features

- 🌡️ **Thermal comfort loads (Phases 1+2)** — climate devices AND switch-controlled heaters gain a comfort band: `Keep at` / `Bank by` / `Run now past` temperatures on the per-device goals, driven by any temperature sensor (climate units default to their own thermometer). Surplus pre-conditions the room into thermal mass; past the limit the device runs from the sources you allow; a pre-conditioned room declines further energy. Thresholds are typed in your display unit (°F installs type °F); °F/K sensors convert automatically. Compressor-safe 3-min restart floor on climate units. Row chip + band editor on the Load Priority card. (#705, requested by @onkelfu)

# [1.7.6-beta.6] — 06.08.2026

### 🐛 Fixes
- 🔋 **Estimated EV SOC walked *down* while the car was charging**
  (#708, reported by @Azlinon) — with the vehicle-SOC sensor quiet, SEM tracks
  the pack against an internal "how far below full is it" figure. Every path
  treated that as a deficit — driving raises it, a real reading recalibrates it,
  reaching full zeroes it, a finished session subtracts what it delivered —
  except the one that runs each cycle *during* a charge, which **added** the
  delivered kWh instead. The estimate fell by exactly what went into the pack:
  11.5 kWh into a blinded 85 kWh pack read 24 % where the car was near 50 %. It
  stayed hidden because a session that reaches full resets the figure anyway; it
  takes a charge that stops short **and** a sensor that goes quiet to leave the
  inverted value on screen. Charging now subtracts, with the 0.92 charge
  efficiency, so the big "SOC (EST.)" number and the "est. now ~54 %" hint beside
  it are the same arithmetic by two routes instead of two answers. The disconnect
  step no longer re-applies the finished session on top of what the live path
  already booked — subtracting it there had been quietly cancelling half the
  error, which is why the number looked plausible again once the car was
  unplugged. A charger's lifetime total-energy counter still anchors the taper
  but no longer feeds this figure at all: it measures what was put back **in**,
  never how far the car was driven, and that mismatch is what made it the sign
  error — on a charger exposing such a counter it could override a fresh real
  SOC reading outright, showing 94 % for a pack the car had just reported at
  38 %. An install with no reference yet still reports "unknown" rather than a
  guess (#245), and the 0 %-recovery path now anchors the value it writes so it
  keeps tracking for the rest of the charge instead of freezing.
- 🔋 **A hand-set charge efficiency can no longer reach the SOC estimate
  unchecked** (#735) — `ev_charger_efficiency` overrides the 0.92 AC→DC default
  used to convert metered energy into pack energy. It has no settings field yet,
  so the only way to set it is by editing stored configuration by hand, and
  whatever was typed went straight into the arithmetic: `3.0` claimed the pack
  absorbed three times what the charger measured, `0` froze the estimate, and a
  stray word raised an error mid-cycle. Values outside the physical range now
  fall back to the default. The two places that book delivered energy — every
  cycle during a charge, and the first-session bootstrap for installs with no
  SOC sensor — now resolve the setting through one accessor rather than
  separately; #708 was precisely two halves of one calculation drifting apart.
  The stop guard added in #708 deliberately keeps the fixed 0.92 and is now
  pinned as such: it feeds a *ceiling*, so a lowered efficiency would charge
  **longer**, and stopping late puts energy in the pack that cannot be taken
  back out, where stopping early is corrected by the next sensor reading.

# [1.7.6-beta.5] — 06.08.2026

### 🐛 Fixes
- 💵 **Tariff sensors that expose a flat price list now populate the schedule**
  (#732, reported by @bjpo-abelco) — a `dynamic_tariff_entity` whose attributes
  carried a valid 24- or 96-value price array under a recognised name
  (`prices_today` / `today` / `raw_today`) was silently rejected: the schedule
  stayed empty, percentile classification fell back to "normal", cheap-window
  planning was off, and the log warned about a missing array that was right there.
  The parser recognised the attribute *names* but its inner loop only accepted a
  list of `{start, value}` dicts — so a bare list of numbers, which is Nordpool's
  *own* `today` / `tomorrow` shape and the one nearly every template/derivative
  sensor copies, fell straight through. Those attributes now accept both shapes:
  a flat list is anchored at local midnight with the granularity read from its
  length (24 hourly / 48 30-min / 96 15-min), `null` gaps are skipped without
  shifting the remaining slots, and a list longer than one day is declined rather
  than mis-dated. The current-price read was never affected — only the day-ahead
  array, which is why only the schedule looked broken.

# [1.7.6-beta.4] — 06.08.2026

### 🐛 Fixes
- 🔌 **Overnight charging read the wrong charger's hardware limits**
  (#716, reported by @Azlinon) — the night planner sizes the charge rate as
  `(peak limit − house load) ÷ watts-per-amp`, and it was assembling those limits
  from the wrong places. `watts_per_amp` hardcoded 230 V, while `ev_voltage` is
  read by seven other watts-per-amp conversions in the codebase — three in
  `decide.py`, two in the coordinator, one in the energy calculator, and one in
  `_night_deliverable_kwh` further down this very file.
  `max_amps` read the *fleet* `ev_max_current`, while the line directly below it
  read `ev_phases` per-charger — so in a mixed fleet the 16 A box was planned as
  the 32 A one, over-claiming budget the next charger in the list then never saw.
  Both now resolve per-charger-then-fleet like the rest of the planner, and a
  non-positive voltage falls back to the default instead of reaching
  `amps_from_headroom`'s 1 W/A floor, which would have saturated the charger to
  max current on a junk config value. The charger's own reported rating still has
  the last word over config. **Note for North American installs:** the reporter's
  1.6 kW clamp came from `Phases` defaulting to 3 on single-phase 240 V hardware —
  a believed 690 W/A against a measured 244. Setting the per-charger **Phases**
  number entity to 1 is the fix for that today; a declared voltage / Max-Amps
  surface and measured watts-per-amp learning are still queued on #716.

# [1.7.6-beta.3] — 06.08.2026

### 🐛 Fixes
- 💵 **Time-of-Use tariffs got their middle rate back — "normal" was unreachable**
  (#728, reported by @Azlinon) — on a plan with a handful of fixed rates rather than a
  continuous hourly curve, SEM classified the day as *only* cheap and expensive. The
  reporter's Consumers Energy "Nighttime Savers" plan has three prices; his twelve
  mid-peak hours — half the day — all read **expensive**, so anything waiting for a
  normal-or-better price sat out the afternoon. Root cause: the percentile classifier
  picks its breakpoints by nearest rank, which on a discrete plan lands the p75 break
  *exactly on* one of the tier prices; the comparison `price >= p75` then swallowed that
  whole tier. Whenever the top tier covers less than about a quarter of the day the
  middle tier disappears into it — and the flat-day guard never fires, so it failed
  silently. Classification now compares **positions in the sorted price window** instead
  of the prices themselves, so a tier is judged by where its hours sit in the day rather
  than by which single number a quantile happened to land on. Continuous curves
  (Nordpool, Tibber, Amber, aWATTar) are untouched: wherever a price occurs at most once
  the two comparisons are equivalent, and #359's boundaries are pinned by test to prove
  it. The mirror case is fixed too — a small *off*-peak block was pulling the middle tier
  down into "very cheap".
- 🕐 **Today's-plan windows read an hour short** (#729, spotted by @Azlinon in #686) — a
  cheap window covering the slots 00:00 through 05:00 announced itself as "open until
  **05:00**", quietly disclaiming the last hour of itself. The two endpoints were not the
  same kind of thing: `start` was the moment the window opens, but `end` was the *start
  stamp of the final slot*. It now names the closing boundary — the same window reads
  "until **06:00**" — and the slot length is measured off the price curve rather than
  assumed hourly, so 15-minute markets close on the quarter. The EV strip's cheap/expensive
  tint, which drew from the same value, stops stopping one slot early too.

# [1.7.6-beta.2] — 05.08.2026

### 🐛 Fixes
- 🌡️ **Inverter/battery temperature no longer shows the wrong number *and* the wrong unit
  on °F installs** (#727, reported by @Azlinon) — a US user's Home-view power-flow diagram
  read "118°C", a plausible-but-nonsensical value. Two bugs compounded: SEM read the source
  temperature sensor with `float(state.state)`, **ignoring its `°F` unit**, and then the card
  concatenated a **hardcoded `°C`** onto a value HA had already converted to the user's display
  unit. The reading is now converted from the source's unit to `°C` before republish
  (`units.temperature_state_to_celsius` — the one place that decides a sensor's magnitude, now
  covering temperature as it already did power/energy), and both the diagram and battery cards
  label with the unit HA actually attached, never a fixed `°C`. Metric installs are unchanged
  (a `°C`/unitless source passes through). A source that is itself mislabelled upstream (the
  reporter's SolarAssistant bridge sends the Celsius value with a `°F` unit) will now match
  whatever that source shows in HA, rather than being converted a second time. Sibling flagged
  for a follow-up: the heat-pump/hot-water control path still assumes `°C` for its setpoint
  comparisons.
- 🌙 **The night sky got a real moon — with the right phase, moving the right way**
  (#711) — the diagram card's static full-moon placeholder is now the actual lunar phase
  (from `sensor.moon`, folded into the card's dirty-check key so a phase change re-renders),
  and the moon walks the sun's arc through the night, sunset (right) → sunrise (left).
  Two rounds of hardening on the arc position: the dawn/dusk *slivers* — the few minutes
  where the card's elevation-gated night disagrees with HA's limb-crossing
  `next_rising`/`next_setting` — put the moon back near mid-arc at 06:05 with an 06:03
  sunrise (caught live on PROD). The first fix keyed on elapsed time and would have broken
  real 20–22 h high-latitude nights (Tromsø, Murmansk — caught in review); the shipped fix
  detects slivers by **proximity to the flip event**, needs no assumption about night
  length, and falls back *directionally* (nearest arc end, never a frozen mid-arc) in the
  degenerate polar-onset case. Extracted to `dashboard/card/src/util/night-arc.js` with a
  7-case regression suite (`dashboard/card/test/night-arc-sliver.test.js`).

- 📅 **Moving the *Charge by* time no longer re-buckets the EV day that is already running**
  (#724) — the fleet EV daily counter's day is deadline-based (#279), and the bucket key was
  re-derived from the live config on every cycle. Move the deadline from 07:00 to 23:00 at
  midday and `sensor.sem_daily_ev_energy` instantly showed *yesterday's* total (a plausible
  wrong number, not an obviously-broken zero), with every further watt merging into
  yesterday's bucket; the reverse move orphaned the day's accrual. The boundary that opened
  the running day now **owns it until it rolls** — a changed deadline takes effect at the
  next rollover, and the memo persists across restarts (a boundary memo that dies on reboot
  just reinstates the bug, #645 rule 2). Upgrades are seamed the same way: the first start on
  this version continues the running day under the old rule and switches at its natural
  rollover, so no install sees a one-time jump.
- 🚗🚗 **Multi-charger fleets with different *Charge by* times: the fleet EV total now
  resets at midnight** (#724) — the fleet counter was bucketed on `max(deadlines)`, one
  charger's clock standing in for the whole fleet: with Car A on 06:00 and Car B on 22:00,
  Car A's own counter rolled at 06:00 while the fleet figure waited until 22:00 — a number
  describing none of its members. Once deadlines diverge there is no such thing as "the
  fleet deadline day", so the fleet total falls back to **calendar midnight**, the only
  boundary every charger shares (and the one every other daily figure already uses). Fleets
  that agree on one deadline — including every single-charger install — keep the #279
  deadline-to-deadline behaviour unchanged, and each charger's own counter always rolls at
  its own deadline. Side effect: the 20:00 daily-summary notification's EV figure now sits
  on the same day as the solar/home/cost figures beside it on mixed-deadline fleets.
  Docs: [USER_GUIDE.md → Energy Sensors](docs/USER_GUIDE.md#energy-sensors-kwh),
  [EV_CHARGING_LOGIC.md → When does the daily target counter
  reset?](docs/EV_CHARGING_LOGIC.md#when-does-the-daily-target-counter-reset),
  [KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md#sunrise-based-meter-day),
  [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

### 🧪 Guards

- 🌡️ **A converted sensor may no longer be labelled with a hardcoded unit** (#727) — the
  #641 units AST-lint now also bans an inline `unit == "°C"/"°F"` comparison outside
  `coordinator/units.py` (temperature joined power/energy as a one-place-decides rule), and
  `dashboard/card/test/temperature-unit.test.js` pins that a `°F` entity can only ever be
  labelled `°F`. New bug class #33 (display-unit mislabel) in `docs/BUG_CLASSES.md`.
- ⚖️ **A view that must balance may no longer mix SEM's day boundaries** (#723) — the
  Energy tab's Sankey — a conservation diagram whose arrows are supposed to add up — drew six
  calendar-day figures next to an EV node bucketed on the Charge-by deadline, so between
  midnight and the deadline the EV branch still carried last night's charge while every source
  it is drawn from had already reset: out by roughly an overnight charge, every night. The
  producer side of this class was closed by #645's boundary registry, but nothing governed a
  view that COMPOSES several individually-correct figures. New guard
  (`tests/test_723_view_day_boundary.py`) derives each entity's boundary from production
  source and fails any balancing card that mixes two; the current Sankey instance carries a
  self-expiring exemption that trips the moment a calendar-day EV sensor lands half-finished
  (PR #722 delivers the sensor + template swap together and passes cleanly). The same class
  in COMPUTED form — the 2026-06-01 PROD autarky bug, 9 % instead of ~42 % from
  deadline-day EV divided into calendar-day flows — is pinned too: production may never call
  `calculate_performance` without flow attribution.

# [1.7.6-beta.1] — 04.08.2026

### 🐛 Fixes

- ⚡ **The peak limit now goes up to 80 kW — and lives on one slider, not five ceilings**
  (#717, reported by @Azlinon) — the target peak limit was capped at 15 kW in the options flow
  (20 kW at install, 20 kW on the `update_target_peak` service, 15/20 kW on two dashboard
  cards — five different ceilings across ten controls). A 200 A North-American service is
  about 38 kW, so those installs could not enter their real grid ceiling and SEM sized every
  load against a limit far below the truth. All ten controls now share one range,
  **1–80 kW at 0.1 kW steps**, from single constants (`MIN_PEAK_LIMIT_KW` /
  `MAX_PEAK_LIMIT_KW` / `PEAK_LIMIT_STEP_KW`) — a test scans each surface and fails if any
  one of them hard-codes a ceiling again. The install wizard no longer asks for a peak limit
  at all — every install starts at the 5 kW default (byte-identical to before) and you tune it
  afterward from a single live control: a drag slider on the Control tab's Load Management
  card, which reaches **"Uncapped"** at the top of its range (the #716 opt-out, below). The
  same value is also editable as a precise kW number on the Configuration tab. Warning and
  emergency are no longer separate entry fields — they're derived from the target at read
  time (90 % / 120 %, unchanged ratios) and tucked behind an **"Advanced"** disclosure on the
  Configuration tab, since almost nobody needs to touch them. The options flow still rejects
  an out-of-order ladder (warning ≥ target, or emergency ≤ target) with a localized message in
  all 16 languages instead of silently storing a configuration where emergency fires before
  warning. Docs: [USER_GUIDE.md → Load Management
  Settings](docs/USER_GUIDE.md#load-management-settings), [SETUP_GUIDE.md → Step
  3](docs/SETUP_GUIDE.md#step-3-hardware-and-dashboard-settings),
  [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md#peak-load-management-not-working).
- 🔌 **New "No grid limit" switch — peak management can now be turned off outright**
  (#716, reported by @Azlinon) — raising the cap to 80 kW is not enough for a connection no
  household load can threaten. Turning *Enable Load Management* off was never the answer: it
  stops the shedding, but the target peak limit stays a **sizing** ceiling, so the EV charger
  still capped its current against it. That is deliberate — "leave my loads alone" must not
  silently mean "there is no limit" — so opting out is now its own explicit switch, reachable
  either as a Configuration-tab toggle or by dragging the Control-tab slider to its top edge
  (both flip the same `peak_limit_unlimited` flag). With it on, the EV controller sizes from
  surplus alone, load management never escalates, and the kW fields disappear from the Config
  card; your numbers stay in config and come back untouched when you turn it off. The flag is
  a **boolean**, never `target_peak_limit == 0`: a zero
  sentinel fails open, and a key nothing writes reads as zero and hands the EV the whole house
  (that exact failure surfaced during the #638 shadow soak). A test scans the codebase and
  fails if the sentinel is reintroduced. Two hardening fixes came with it — the
  headroom→amps conversion saturates **before** rounding (`round(float('inf'))` raises
  `OverflowError`), and an out-of-order peak ladder is repaired at read time: a stored
  `emergency ≤ target` made the emergency branch win at the target itself, dumping every load
  the instant the limit was touched, and the options flow is not the only writer
  (`set_option` writes any key unvalidated). Docs: [USER_GUIDE.md → No grid
  limit](docs/USER_GUIDE.md#no-grid-limit), [SETUP_GUIDE.md → Step
  3](docs/SETUP_GUIDE.md#step-3-hardware-and-dashboard-settings),
  [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md#peak-load-management-not-working).
- 🔧 **The "no grid limit" opt-out could lag a full restart behind the slider, in both
  directions** (#716, found in review) — dragging the Control-tab slider to "Uncapped" writes
  straight into the live load manager and deliberately skips a config-entry reload (a full
  rebuild on every drag would be too heavy), so the EV controller's own copy of the flag —
  read from the un-reloaded config — could still see the old value. Dragging to "Uncapped"
  left the EV sizing against the old ceiling until a restart; dragging back down to a real
  number left it sizing as if nothing constrained it, ignoring the limit just set. The EV
  controller now reads the flag from the live load manager first, the same way it already
  read the target kW value, falling back to config only when no load manager is wired up yet.
- 🔧 **The shed ladder's own telemetry could publish an inverted warning/emergency pair**
  (#717, found in review) — `get_load_management_data()` returned the raw stored
  `warning_level`/`emergency_level`, not the ladder `_effective_levels()` repairs at read
  time before `_monitor_and_shed()` acts on it. Nothing consumed those two keys from the dict
  yet, so this was inert, but any future card or sensor reading them would have shown a ladder
  that didn't match what shedding actually used. Now returns the repaired pair.
- 🧪 **`services.yaml`'s peak-limit selector had no test tying it to the shared range**
  (#717, found in review) — the `update_target_peak` service's Developer Tools selector
  hardcodes `1.0`/`80.0` because YAML can't import `MIN_PEAK_LIMIT_KW`/`MAX_PEAK_LIMIT_KW`,
  the same drift shape that caused #717 in the first place (five different hard-coded
  ceilings, nobody comparing them). Added a guard that fails CI if the YAML ever falls out of
  sync with the constants.
- 🌐 **Six options-flow error messages rendered as raw keys** (found while fixing #717) —
  HA resolves options-flow errors under `options.error`, not `config.error`
  (`show-dialog-options-flow.ts` falls back to the bare key), and all of SEM's options-flow
  errors were declared only in the config block. Two of them
  (`deye_work_mode_mapping_not_distinct`, `deye_force_charge_work_mode_invalid`) were
  declared nowhere at all — the #674 parity guard's regex could not see them because the
  assignment is parenthesised. All seven now live in the right block in all 17 string files,
  and the #674 guard was rewritten as an AST walk that attributes each error to the flow
  class that assigns it, so a message declared in the wrong block now fails CI.
- 🚗 **EV no longer overshoots the SOC target on slow/polled car sensors** (#708, reported by
  @Azlinon) — OnStar-class integrations poll the vehicle SOC as rarely as every 30 minutes, and
  SEM steered on the last value as if it were live: overshoot = sensor lag × charge power (60 %
  target → 67 % on an 85 kWh pack at 11.5 kW). The stop decision now uses an energy-accounted
  ceiling beside the sensor: the pack cannot be emptier than the last reading plus what the
  session measurably delivered (× 0.92 charge efficiency), so the charge stops at the target even
  while the sensor sleeps. The sensor stays primary — every fresh reading re-anchors and wins,
  and if it lands below target SEM auto-resumes for the difference (resumes are spaced by the
  sensor's own update interval and shrink each round). A mobile notification and a card info line
  ("Car: 55 % (28 min ago) · est. now ~59 %") explain both the early stop and any resume. The
  virtual/estimated SOC display is untouched, and the #446 wall (no speculative SOC in budgets)
  is re-pinned by an extended AST guard. Zero new config keys. Docs:
  [USER_GUIDE.md → Slow-polling SOC sensors (energy-accounted
  ceiling)](docs/USER_GUIDE.md#slow-polling-soc-sensors-energy-accounted-ceiling).
- 🌐 **Phase-guard topology setup step was untranslated in 15 of 16 languages** (by
  @tintinz in #718, follow-up to #712) — the topology selector and its options rendered
  in English regardless of profile language; now localized across all 16, with regression
  coverage that fails CI if a non-English translation falls back to English copy. Silent-install
  defaults stay fail-closed (an explicit valid topology is still required before the guard can
  enforce), and a docstring now records that power-derived charger current can lag writes and
  must not be read as an authoritative command floor. No control-path or actuation changes.

### ✨ Features

- ⚡ **Dual-source phase guard now enforces in the EV write path** (by @tintinz in #712) —
  the read-only per-phase diagnostics from #707 gain an opt-in enforcement mode: every
  non-DISABLE charging intent is clamped to the measured per-phase headroom before it
  reaches the charger, fail-closed on missing/stale/invalid readings, fully gated in
  observer mode, wired into both the multi-charger and legacy single actuation paths.
  All five config keys editable in the options flow; disabled by default.
- 💶 **Variable grid import surcharge for dynamic tariffs** (by @tintinz in #710) — a
  configurable surcharge (grid fees, taxes) is added on top of the raw dynamic price at
  every import-cost site, applied exactly once (the `effective_import_floor` double-count
  trap is test-pinned), export/feed-in untouched. Translations complete across all 16
  languages.

# [1.7.5] — 03.08.2026

> **Stable release.** Consolidates the 1.7.5 beta line (beta.1 → beta.38, detailed
> below). Headline: the **#628 meter-reconciliation arc** — SEM's seven daily
> numbers now ADD UP, each pinned to your own hardware counters and home derived
> as their exact residual — plus the **per-charger state retirement** (#589), the
> **device goal model** for surplus loads (#620), a **zero-HACS-prerequisites
> dashboard** (#617), a full **docs overhaul** (#618), and fail-closed community
> hardware support for Deye, Zaptec and per-phase grid limits (by @tintinz).

### 📏 Daily numbers that add up (#628)
- ✨ **Daily home consumption is now the reconciled residual, not a stopwatch.**
  Home is the one row nothing meters; SEM used to evaluate the energy balance
  instantaneously in watts and integrate it, which magnifies every sensor's
  small error into ±3–15 % on the home row (confirmed on two independent
  installs). The daily row is now derived from the day's reconciled counters —
  `solar + import − export + discharge − charge − EV` — exactly as lifetime and
  yearly home always were. The integrator stays as the fallback whenever a
  flowing term is not counter-backed. On the day you upgrade, the row keeps the
  old behaviour for one calendar day (the EV midnight mirror needs a full day of
  history first); it derives from the following midnight. (reported by
  @jappish84 in #628)
- ✨ **Solar, grid and battery daily rows reconcile against your own counters**
  (beta.13 →): daily totals are cross-checked and corrected against the hardware
  counters configured in your Energy Dashboard, so polling gaps and power blips
  no longer drift the day. Night-time yield-counter movement on DC-coupled
  hybrids is ignored (#681) — battery discharge in the dark is not solar.
- 🛠️ **Sensor overrides on the Config card** (#628/#696): battery, grid and
  solar power sources can be overridden per-install when autodetection picks the
  wrong entity.

### ⚡ EV charging: structural per-charger state (#589 arc)
- 🏗️ Per-charger state lives on `PerChargerState` by reference — the legacy
  snapshot/restore swap is gone, closing the whole reads-fleet-total-instead-of-
  this-charger bug class structurally (beta.15). Ghost EV rows no longer appear
  after a charger is removed (#595), and a charger that gives up re-offers on a
  countdown instead of silently never trying again (#610, live-proven).
- 🐛 KEBA UDP resilience: lost-datagram guard, ~1 Wh idle-session guard, and a
  median-of-3 `ev_power` pre-filter absorb transport blips instead of flapping
  the charger (beta.11 →).

### 🎛️ Surplus loads: the device goal model (#620)
- ✨ Every managed load gets Min/Max daily runtime, a daytime Mode, and a
  "Finish overnight from" picker (Off / Battery / Grid) — live-proven on real
  hardware (beta.22). The loads' day rolls on the same meter-day class the EV
  uses (#704), and the goal engine is pinned by an invariant harness over the
  full contract (#703).

### 🖥️ Dashboard: zero HACS prerequisites (#617) + config redesign (#605/#606)
- ✨ SEM's dashboard no longer requires mushroom, apexcharts, card-mod or
  sankey-chart — glass styling is baked in, Chart.js is vendored, and the energy
  flow falls back to the native sankey. Fresh installs render complete with zero
  HACS cards.
- ✨ Configuration tab redesigned around grouped cards with per-key help anchors
  (#605/#606, reported by @tlinnet); device names localize per-user in the
  system diagram (#615).

### 🧹 Coherence audit + dead code (16 confirmed findings)
- 🏗️ A systematic audit of decision coherence closed #639–#655: dead features
  that could never run were removed (#651/#659/#664), the EV orchestration was
  decomposed (#629), and the second (dead) EV surplus allocator was deleted with
  coverage restored on the one that runs (#665).

### 🔌 Community hardware (by @tintinz, @onkelfu and reporters)
- ✨ Fail-closed Deye battery adapter with transactional TOU-register writes
  (#709); read-only per-phase grid diagnostics with sign-safe current derivation
  (#707, freshness fix in beta.38); Zaptec discovery persistence + phantom-plan
  suppression (#706); JuiceBox EVSE no longer double-detected (#698); Open-Meteo
  Solar Forecast autodetected (#687); fail-closed battery discharge controls
  from the #702 review; Enphase IQ battery temperature (#583).

### 🧪 Correctness & hardening across the line
- 🐛 Atomic `power_snapshot` for coherent card rendering (#699), rate-limited
  STOP-unenforceable warnings (#700), load-management day-boundary fixes
  (#703/#704), pool-filter/load goal fixes from live soaks, and the full
  pipeline-test matrix extended to every newly supported brand.

# [1.7.5-beta.38] — 02.08.2026

### 🐛 Fixes

- 📐 **Phase guard: a flat-but-alive sensor is fresh, not stale** (#707 follow-up) — freshness
  keyed on `last_updated`, which HA only moves when a value actually *changes*; a healthy sensor
  holding a constant reading (grid voltage rounding to 230 for minutes, a quiet phase at 0 W all
  night) only bumps `last_reported`, so the guard declared it stale and failed closed on a healthy
  install. Caught by the HA-TEST sim gauntlet within a day of the beta.37 merge. Freshness now
  reads `last_reported` with `last_updated` as the fallback for older cores. The rest of the
  gauntlet passed live: export sign-safety (−1153 W → 5.0 A), stale/invalid-unit/over-limit all
  fail closed with per-phase stop reasons. (by @traktore-org)

# [1.7.5-beta.37] — 01.08.2026

### ✨ Features

- 🔌 **Fail-closed Deye battery support** (by @tintinz in #709) — explicit `battery_charge_platform:
  deye` adapter with a transactional snapshot/restore protocol over the six-slot TOU register model:
  every write is verified by read-back, any failure rolls the inverter back to its pre-session state,
  a tampered or stale snapshot is never replayed, and a persisted unsafe latch survives restarts.
  Zero effect unless Deye is explicitly selected. Maintainer review hardened the contract: the
  restore path now honours the observer/actuation gates (the #702 class), a re-issued force charge
  is the session heartbeat instead of a per-cycle error, a store-less config no longer latches
  unsafe, and read-back waits 2 s for the Modbus poll instead of racing it.
- 📐 **Read-only per-phase grid diagnostics** (by @tintinz in #707) — opt-in phase guard for
  grid-only and hybrid Load/EPS topologies: per-phase current and margin sensors from direct RMS
  entities when available, else `abs(power)/voltage` (sign-safe for import AND export), with
  missing/stale/invalid readings failing closed. Diagnostics are disabled-by-default in the entity
  registry, so unconfigured installs see no new entities. Also fixes the `minimum_solar_power`
  config label, which was missing on every install (key rename never reached the translations).

### 🐛 Fixes

- 🚗 **Zaptec discovery persists and phantom plans are suppressed** (by @tintinz in #706) — a
  failed first discovery no longer leaves legacy flat sensors driving charging logic with no
  registered charger: discovery persists under a stable per-device ID, night plans are suppressed
  until a controllable charger exists, and vehicle range readings without a unit are dropped
  instead of guessed (metres-as-km would inflate 1000×). Maintainer review extended the
  operational gate to the battery view and scheduler re-plan — no more discharge protection held
  for a phantom EV — and Zaptec identity now requires a state sensor, not just a resume button.

# [1.7.5-beta.36] — 01.08.2026

### 🐛 Fixes

- 🌅 **The loads' day now comes from the same meter-day class the EV uses** (#704) — the loads
  carried their own inline, stateful day-boundary latch; on a mid-night restart it fell back to
  the calendar date, resetting every runtime target hours early and re-arming exactly the
  overnight battery drain the boundary exists to prevent. The latch is gone: the sunrise meter
  day is computed statelessly by the shared TimeManager class — restart-proof by construction,
  and in winter the day now rolls at actual sunrise instead of the 07:00 night-window cap.
  (by @traktore-org, root-caused by Guido's review question)
- 🕛 **Overnight top-ups no longer flap at midnight** (#703) — the grid/battery top-up force was
  stamped and expired against the *calendar* date while a load's runtime day is held to **sunrise**,
  so every load running an overnight top-up was stopped at exactly 00:00 ("day rollover") and
  restarted a minute later — one spurious contactor cycle per night. One boundary authority now:
  stamps and expiry both read the load's own sunrise-held meter day, so a "Finish overnight" run
  sails through midnight and ends exactly when its day does. Found while answering @onkelfu's
  day-boundary question on #688, which is now also documented (sunrise boundary, no carry-over).
  (by @traktore-org)

### 🧪 Hardening

- 🎯 **The load goal engine is now invariant-guarded** — a simulated multi-day walk through the
  real allocation engine asserts the whole contract at every cycle (midnight crossing, every paid
  source's start/stop symmetry, floor/ceiling, marker hygiene, sunrise-only deficit reset, a full
  48-hour scenario). The bug class that produced eight instances across #559/#620/#633/#688/#703
  now fails in CI instead of on a reporter's pool pump.

# [1.7.5-beta.35] — 31.07.2026

### 🐛 Fixes

- 🛡️ **Battery discharge controls now fail closed** (#702) — two real risks closed: the startup
  discharge-limit restore actuated even in Observer Mode (observer's contract is *zero* actuation),
  and control auto-discovery trusted the entity *name* without proving its unit — on Deye/
  ha-solarman it could select an **amperes** register (max 350 A) and feed it watt values. Now:
  Observer Mode makes the startup restore a hard no-op, discovery requires a live, explicitly
  W/kW-labelled entity, and every discharge-limit write (Generic / GoodWe / Huawei / startup) goes
  through one fail-closed validator with W↔kW conversion — an unavailable, wrong-domain, A/%,
  out-of-range or non-finite control produces **no service call**. Explicitly configured unitless
  `input_number` helpers keep working as legacy watt controls.
  (by @tintinz in #701 — thank you for the exceptionally thorough contribution)

- 🔇 **The STOP-unenforceable warning no longer floods the log** (#700) — the (correct, important)
  warning that a charger config has no way to open the contactor fired every reconcile cycle while
  the condition persisted: 8000+ entries on a real install, crowding out the entire log history.
  It now fires once per episode with the full instruction, repeats at debug, and re-arms when the
  situation genuinely changes. (by @traktore-org, reported by @jappish84)
- 🌍 **A configured charger's duplicate Energy-Dashboard row is now folded regardless of language**
  (#700) — the suppression relied on an English-only name guess (`ev`, `charger`, `wallbox`, …),
  so a Swedish "Billaddare" row for the same physical Garo survived and Load Management showed the
  charger twice. Suppression now tests identity — the row's sensor being a configured charger's
  entity, or living on the charger's own HA device — so it works in every language.
  (by @traktore-org, reported by @jappish84)

# [1.7.5-beta.34] — 31.07.2026

### 🐛 Fixes

- ⚖️ **The system diagram's books now always add up** (#699) — two layers, both closed. The
  balance tiles (solar / grid / battery / EV / home) were read from five separate entities, each
  committing to HA's state machine on its own — and worse, during a source-cadence skew the
  home-consumption hold (#237/#444) *deliberately* substitutes home while grid/EV carry the raw
  skewed reads, so the published set violates its own equation for a few cycles by design (live
  on PROD: a 15-second wallbox burst showed 4.8 kW grid import against an EV tile still reading
  0 — ~5 kW missing from the view). The whole balance set is now published as ONE atomic
  per-cycle snapshot on the home sensor (recorder-excluded), and when a cycle is known-incoherent
  the snapshot ships the **last self-consistent set** (flagged `held`, SOC kept fresh) instead of
  a mix of fresh and substituted values. A misattribution guard covers the case the balance can't
  see: an EV start with a lagging charger power sensor would land the car's draw on the *home*
  node once the books re-close around it — the charger's fast charging *binary* disambiguates
  (charging on + power ~0 = sensor lag → keep the coherent set, bounded at ~2 min so a genuinely
  paused charge is believed). The system-diagram + flow cards render from it — coherent at every
  instant by construction; custom `entities:` configs and older backends keep the per-entity
  path. (by @traktore-org, reported by @traktore-org from PROD)

# [1.7.5-beta.33] — 31.07.2026

### ✨ Enhancements

- 🗼 **New "Sensor sources" section on the Configuration card** (#628, #696) — the grid / solar /
  battery power override keys have existed since #592/#597, but grid had no UI at all and
  solar/battery hid in unrelated sections. All three pickers now live in one section: blank = auto
  (Energy Dashboard), the collapsed header shows "all auto" vs "N overridden", sign detection runs
  against the override source, and an override that goes unavailable shows a warning instead of a
  silent fallback. For the off-grid / dead-CT case (EG4 FlexBOSS → Shelly EM) and any install that
  wants SEM on a different meter than the HA-wide Energy Dashboard uses.
  (by @traktore-org, requested by @Azlinon / @jappish84)

### 📚 Documentation

- 📖 **The EV daily counter's deadline-based day boundary is now documented** (#628) — it rolls at
  the charger's *Charge by* time (default 07:00), not midnight, so an overnight charge lands in
  one bucket; the mid-session restart at the deadline read as a bug because nothing said so.
  (by @traktore-org, reported by @jappish84)

# [1.7.5-beta.32] — 31.07.2026

### 🐛 Fixes

- 🌇 **Losing the surplus now stops a running load** (#688) — the allocation walk debited an active
  device only its power *delta*, never its held draw; with the solar-bounded pool floored at 0 the
  deficit trigger (−100 W) was unreachable, so a load that lost its sun ran on grid/battery all the
  way to its daily **Max** cap (live: pool pump, Min 8 h met, still heading for 11.5 h). Active
  loads are now debited in full — minus the share Tier-1 battery assist legitimately covers, which
  still stands down past the daily floor — and the lowest-priority unfunded load is shed first,
  with the ±100 W hysteresis, spike filter and anti-flicker windows unchanged. Also closes both
  known imperative↔desired-state parity gaps. (by @traktore-org, reported by @onkelfu)
- 🔌 **One charger, one Load Management row** (#698) — a JuiceBox exposes both a *lifetime* and a
  *session* energy counter on the same device; HA's Energy Dashboard auto-suggests both, and SEM
  built a load row per sensor, so every EVSE appeared twice. Same-measurement variants
  (lifetime/session/total/today/daily) now fold into one device preferring the monotonic counter;
  genuinely distinct loads (e.g. a Shelly 2PM's two channels) are never folded, and the entity
  registry vetoes the fold when the sensors live on different devices. JuiceBox also joins the EV
  charger detection patterns. (by @traktore-org, reported by @Azlinon)
- 💬 **The Mode tooltip now describes the four modes the field actually offers** (#697) — it still
  explained a retired three-mode set ("Surplus = …"); rewritten ×16 languages for Off / Peak only /
  Solar only / Solar + battery, and the *Solar only* / *Solar + battery* / battery-hint labels —
  previously English in 12 of 16 languages — are now translated everywhere.
  (by @traktore-org, reported by @Azlinon)

# [1.7.5-beta.31] — 30.07.2026

### ✨ Enhancements

- ☀️ **Open-Meteo Solar Forecast is now auto-detected** (#687) — the HACS integration
  ([rany2/ha-open-meteo-solar-forecast](https://github.com/rany2/ha-open-meteo-solar-forecast))
  mirrors Forecast.Solar's sensor scheme but under its own platform with device-prefixed entity
  names, so SEM's detection never saw it. It's now a first-class source (priority: Solcast >
  Forecast.Solar > Open-Meteo), resolved via the entity registry so renamed/localized/prefixed
  entities all work — including multi-orientation setups, which it aggregates natively in one
  config entry. (by @traktore-org, requested by @Azlinon)

### 🐛 Fixes

- 💾 **A config-dialog save no longer erases settings the dialog doesn't own** (#690) — the options
  dialog's final save replaced the entry's options wholesale, wiping every option written outside
  its own pages: the *Fix grid sign* flip (`grid_sign_user_flip` — the reported "Grid Sign Always
  Changes Back"), the battery-sign flip, battery mode/reserve selectors, vacation mode, price
  thresholds, EV delay knobs and more (18 dashboard/service-owned settings). The save now carries
  forward everything outside `OPTIONS_FLOW_OWNED_KEYS`; a guard test recomputes the owned set from
  the flow source so a new form field can't silently change class. (by @traktore-org, reported by
  @hrdilshan)
- 🔋 **The battery discharge clamp no longer splits the home budget with batteries it doesn't
  control** (#691) — the protective `home/N` split counted *configured* batteries: a unit set to
  **Off** (SEM hands-off) still ate a share, so a 2-battery house with one disabled clamped the
  active battery to *half* the home load and imported the rest all evening (live: home 1.0 kW,
  battery 520 W, grid 552 W on SolarEdge). Batteries sharing one discharge-limit entity (e.g.
  SolarEdge's single inverter-level *Storage Discharge Limit*) now also count as ONE consumer with
  the full budget. Bonus gap closed: the startup restore-to-max now covers per-battery discharge
  entities, not just the global one. (by @traktore-org, reported by @onkelfu)

# [1.7.5-beta.30] — 30.07.2026

### 🐛 Fixes

- ⚡ **Your configured peak limit is now actually enforced** (#692) — load management read its
  settings (`target_peak_limit`, warning/emergency levels, hysteresis, on/off) from the entry's
  *options* surface, but the install flow writes them to *data*. On any install that never re-saved
  through the options dialog, the shedder silently ran the 5.0 kW default instead of the configured
  limit (live: config 6.0 kW, enforced 5.0). It now reads the merged view, options winning — the
  same view the coordinator has always used. Found chasing a #638 scenario-battery discrepancy.
  (by @traktore-org)
- 🌙 **The night charge schedule's peak cap was dead on every install** (#693) — the scheduler read
  `peak_limit_w`, a config key **nothing writes**, so its peak-aware slot distribution ran with
  "no limit" everywhere. It now reads `target_peak_limit` (kW, the key installs carry — shared with
  load management). Same dead-key class as the #638 shadow-planner finding; the unit test had kept
  it green by feeding the phantom key directly. `docs/ARCHITECTURE.md` row corrected.
  (by @traktore-org)
- 🔋 **A warming battery no longer reports 0 %** (#694) — after a restart, a modbus battery's SOC
  can take minutes to publish; the per-battery sensor showed **0.0** in that window — an "empty
  battery" claim nothing could distinguish from the real thing — and the fleet average was dragged
  toward 0 by the fabricated value. Unresolved units now publish *unknown* and are excluded from
  the fleet average until they report. (by @traktore-org)
- 🚗 **A wallbox's car SOC can no longer be adopted as the house battery** (#695) — the
  last-resort global SOC scan (#529) excluded `ev`/`car`/`vehicle` names but not `charger`/
  `wallbox`; a charger exposing the vehicle's SOC (Easee, Zaptec, OpenWB) could win the scan as
  the *house* battery. #250 wrong-entity class. (by @traktore-org)

# [1.7.5-beta.29] — 29.07.2026

### 🐛 Fixes

- ⏱️ **A load's daily *Minimum* is a floor, not a stop — *Maximum* is now reachable** (#688,
  reported by @onkelfu) — a pool pump set to *at least 8 h, up to 11.5 h, solar only* stopped dead
  at 8 h with sun still on the roof. The card promised a range; the engine could never traverse it.
  `daily_targets_met` goes true **at** the minimum and was wired as a hard stop, so whenever a Min
  was set, **any Max above it was unreachable by construction** — dead configuration behind a live
  slider. The floor now ends only the **paid** sources: battery assist stands down, and an overnight
  battery or cheap-hours grid run is stopped explicitly (those are exempt from the load-shedding
  ladder by design, so nothing else would ever end them — the load would drain the battery past its
  own target all night). **Free solar surplus carries the load on up to the Max**, which stays the
  only hard stop and still stops a load that is already running. This is the same floor/ceiling
  contract the EV has had since #245, which the load slider was built to mirror. *Today's Plan* also
  stops calling a still-running load "done" the moment it passes its floor, and a latent crash on
  its solar-peak parse (an unimported `datetime`, uncatchable by the handler around it — new bug
  class 31) is fixed. Guarded by `tests/test_688_runtime_floor_ceiling.py`. (by @traktore-org)
- 🔌 **A grid sign you set yourself no longer flips back on its own** (#690, reported by
  @hrdilshan) — after correcting the grid direction, SEM silently undid it about every 3 minutes:
  *"it automatically changes back."* SEM watches the energy balance and auto-corrects a persistently
  negative one by flipping the grid sign — but a negative balance only proves the inputs disagree,
  not **which** sensor is wrong, and this check always blames the grid. With the manual invert set it
  was worse than useless: that setting short-circuits the auto-detection entirely, so the flag being
  toggled was never even read, the balance could never improve, and it toggled again forever. Two
  guards: an explicit user decision (manual invert **or** the one-tap flip) stands the self-heal
  down completely, and the self-heal now gets **one** attempt — a flip that doesn't fix the balance
  is reverted and latched off instead of oscillating for the rest of the day. Confirming a good flip
  needs the same ~3 minutes of healthy balance that tripped it, so an intermittent non-grid fault
  can't reopen the loop on a longer period. `reset_sign_detection` clears the latch — it *is* the
  manual retry. Verified live on the test rig by A/B: same −2.75 kW balance, unguarded it flips at
  3 minutes, guarded it stands down. Guarded by `tests/test_690_grid_sign_self_heal.py`.
  (by @traktore-org)

# [1.7.5-beta.28] — 29.07.2026

### 🐛 Fixes

- 🔋 **Battery power sliders now reach 25 kW** (#689, reported by @Azlinon) — the *Battery total
  discharge limit* and *Battery → EV assist limit* sliders capped at 10 kW, so a system that
  discharges 12 kW from battery (EG4 Flexboss 21; parallel stacks go higher) literally could not
  enter its real capability — the same range-bug class as #680, in watts. Both the options-flow
  sliders and the number entities (which the config-card knobs mirror) now share the charge-power
  slider's 25 kW ceiling. Safe by construction: every command is still clamped to the hardware's
  real limits by the adapters, so a generous slider can never over-drive a smaller system. Guarded
  by `tests/test_689_battery_power_caps.py`. (by @traktore-org)

# [1.7.5-beta.27] — 28.07.2026

### 🐛 Fixes

- 🔁 **Deferrable loads no longer short-cycle — and the window is now yours to tune** (#688,
  reported by @onkelfu) — a pool pump (or any switch load) could flick on and off as the available
  surplus wobbled with passing clouds, other appliances starting, or the home battery charging. The
  root cause was **not** a missing feature: SEM already enforces a per-load minimum run and minimum
  pause every cycle. But for a generic load that window defaulted to a twitchy **1-minute pause**,
  and — being a backend value with no surface anywhere — you could neither see nor lengthen it (bug
  class 30, the same shape as #627's start/stop entity). Two changes: the default pause is now **5
  minutes** (matching the 5-minute minimum run), which caps cycling at a ~10-minute period and lets a
  load ride *through* a passing cloud instead of stopping and restarting; and **Minimum run time /
  Minimum pause time** are now editable per load on the Control-tab priority card, right next to the
  Min/Max runtime and Mode controls, applied live and across restarts via the same goal engine
  (#620). Full i18n ×16. Guarded by `tests/test_688_load_anti_cycling.py`. (by @traktore-org)

# [1.7.5-beta.26] — 27.07.2026

### 🐛 Fixes

- 🔌 **The "configure a start/stop entity" repair now has somewhere to go** (#627, reported by
  @onkelfu) — beta.25 taught SEM to notice when it holds no mechanism that can open a charger's
  contactor and to file a repair naming the missing `ev_start_stop_entity`. But that entity had no
  editable surface anywhere in the UI: `__init__.py` has read it off the per-charger config since
  v1.0 and `hardware_detection` auto-fills it for some brands, yet neither the config card nor the
  options flow could ever *write* it — so the repair pointed a user straight at a dead end. The
  per-charger section of the config card now offers a start/stop picker (`switch`/`button`), and
  the add- and edit-charger options-flow steps gain `ev_start_stop_entity`, `ev_current_sensor`,
  `ev_charge_mode_entity` and the charge-mode start/stop values — every per-charger entity key the
  runtime honours is now settable *after* install, not only in the unreachable install-time step,
  and correctable later on the exact same fields it was set with. This is bug class 30 (a
  backend-honoured config key with no editable surface), the same shape as #684; `hardware_detection`
  guesses are now suggestions the user can override rather than silent commitments. Guarded by
  `tests/test_627_charger_config_surface.py`, which re-derives the key list from `__init__.py` on
  every run so a *new* per-charger entity key that lands without a surface fails there rather than in
  a user's log a release later. (by @traktore-org)
- 🌙 **"No overnight charging" is now expressible in % — not just kWh** (#680, follow-up to
  #679/#634, and the layer @onkelfu's #627 install actually sat on) — the overnight floor is the
  *single* night-charge control: SEM tops up the gap between surplus and your "At least" target, and
  a floor of **0 means no night charge**. That worked in kWh — the slider reached 0 — but not in %:
  the SOC "At least" slider was pinned at `min=50` on the config-card knob and all three options-flow
  steps, so a %-targeted *Solar-only* charger could not be told "never grid overnight" and topped up
  to at least 50 % from the grid every night (onkelfu's charger sat at 100 %). Both the floor **and**
  the Max solar ceiling now span **0–100 %** — the whole SOC range is settable, matching the kWh
  target. The runtime clamps the effective ceiling `>= floor`, and daytime charging follows the
  ceiling, so `At least = 0` removes only the overnight grid guarantee, not daytime solar charging. No
  new toggle — the floor you already set is the control, it just needed to reach 0. Guarded by
  `tests/test_680_soc_floor_reaches_zero.py`. (by @traktore-org)

# [1.7.5-beta.25] — 27.07.2026

### ✨ Enhancements

- 🔌 **Daily grid and battery energy now follow your meter, not SEM's stopwatch** (#628, reported
  by @jappish84) — you declare your P1/utility meter and BMS counters in HA's Energy Dashboard,
  and until now SEM read those registers exactly **once**, at startup, to seed lifetime totals.
  Every daily row you actually compare against the Energy Dashboard was pure power integration:
  SEM sampling a power sensor every 10 seconds and adding up the rectangles. Any sample the
  sensor drops or mis-signs is gone for the rest of the day. On our own Huawei install 17 of 520
  grid samples in three hours were isolated dropouts and one read −229 W, which books real import
  as export — and the reporter's numbers show the same signature, his import short by 3.2 kWh and
  his export long by 2.9 kWh, the same energy filed on the wrong side. Grid import, grid export,
  battery charge and battery discharge now reconcile against those counters every cycle, using the
  same baseline/anchor/delta model as solar (#556) and EV (#658), under the same
  `prefer_hardware_energy` option. Three deliberate differences: the correction is **bidirectional**
  (solar can only ever have been under-counted; a meter can prove the integrator counted energy
  that never flowed, which is the reporter's export row), a category reconciles only when **every**
  one of its counters is reporting (a two-tariff meter with one register unavailable must not look
  like the day shrank), and there is **no sun gate** — #681 keeps the solar *yield* counter out of
  the night because it does not measure PV production, whereas a grid import register measures grid
  import at 03:00 exactly as it does at noon. (by @traktore-org)

### 🐛 Fixes

- 🚗 **Two chargers, one instrumented car — and that car's SOC showed on both tiles** (#683, reported
  by @Azlinon) — with a second EVSE added and only the first one wired to a vehicle battery sensor,
  the second charger's card displayed the first car's state of charge. Two separate, individually
  sensible behaviours composed into it: when no *global* vehicle SOC sensor is configured SEM
  promotes the first per-charger reading it finds into the fleet-wide `sem_vehicle_soc` sensor, and
  each charger tile fell back to that fleet sensor whenever its own reading was missing — which is
  exactly the situation of a charger with no SOC sensor of its own. The fallback exists for older
  single-charger installs and stays for them; it is now switched off the moment a second charger
  exists, where the fleet value provably belongs to somebody else. Such a tile now falls back to its
  own estimated SOC, or shows none at all. (by @traktore-org)
- 🔌 **A charger that reports "Plugged In" as text could not be selected at all** (#684, reported by
  @Azlinon) — the Connected Sensor picker on the Configuration card only offered `binary_sensor`
  entities, while the setup wizard for the same field has always accepted a plain status `sensor`
  and SEM already understands the words those chargers publish (`Plugged In`, `Connected`,
  `Charging`, `Preparing`, …). A JuiceBox 48 talking to Home Assistant through the community
  JuiceBoxProxy — states `Unplugged` / `Plugged In` / `Charging` — was therefore impossible to
  configure from the dashboard even though it would have worked once configured. The picker now
  matches the wizard. No new sensor contract: any `binary_sensor`, or any `sensor` whose state is
  one of the known status words. (by @traktore-org)
- 🔥 **Switching a device to "Off" did not stop it if SEM had started it overnight** (caught on our
  own production hardware) — a load started by the overnight-battery pass, the cheap-hours grid
  pass or a deadline top-up kept running after you set its mode to Off. SEM stopped managing it and
  never stopped it: on PROD a towel heater was still drawing 648 W five minutes after the switch to
  Off, and would have gone on heating until the household's own 2-hour safety automation cut it.
  The release only ever fires for a load SEM *owns* — the flag that separates "SEM turned this on"
  from "you turned this on", so that Off leaves your own manual switch-ons alone. That flag was set
  by the code that turned the device on, and only two of the five places that turn a device on
  remembered to set it; the three overnight/top-up paths did not, so Off reached the right decision
  and then declined to act on it. Ownership now lives with the actuation itself instead of being a
  thing each path has to remember, and a CI guard fails the build if a new path is ever added that
  bypasses it. This is the fifth time this class of bug has shipped (a gate that blocks a device
  from starting but does not stop one already running) — the new variant is written up in
  `docs/BUG_CLASSES.md`. (by @traktore-org)
- 🔌 **Re-registering an auto-detected device by service dropped its energy counter** — the
  `register_surplus_device` service accepts an `energy_entity_id` (#600) but discarded it when
  building the device row, so a device that had been auto-discovered *with* an energy sensor lost
  it the moment it was re-registered through the service. (by @traktore-org)
- 🚗 **A full car could still be woken mid-backoff, once every couple of minutes** (#682, follow-up
  to #610) — #610 stops SEM re-offering current to a car that has already refused three start
  ladders, and the 20-minute backoff was verified live. It leaked anyway: the gate sat inside the
  "we want to charge" branch, and the amps that decision is built from are a 5-cycle median. Three
  quiet cycles pull the median under the minimum, so a cycle whose *raw* decision is a real CHARGE
  falls through the other branch, which hands the caller's decision straight back unfiltered. On
  PROD five commands escaped a single armed window — recognisable in the log because their reason
  carries no `stability:` prefix. The gate is now evaluated on the raw state above the split. This
  is the **second** time this exact escape has been fixed on this exact gate (the first was the
  ladder block bypassing a fresh-start-only check), so it is now written up as bug class 29 —
  *a guard sits inside one branch of a split; the other branch passes the input through
  unguarded* — with the sweep question and a cheap detector in `docs/BUG_CLASSES.md`.
  (by @traktore-org)
- 🌙 **Daily solar counted the battery discharging overnight as production** (#681, caught on our
  own production hardware) — on a DC-coupled hybrid the inverter's total-yield counter measures AC
  *output*, and at night that output is the battery serving the house. SEM's hardware-counter
  reconciliation credited every tick of it as solar: on a live Huawei SUN2000 + LUNA2000 the
  counter climbed +3.55 kWh between 22:00 and 05:30 with PV power flat at 0 W, and SEM duly
  reported **3.06 kWh of solar produced before sunrise**. Because adoption is upward-only the
  phantom was banked while integration was still ~0 and the real day accumulated on top of it, so
  it never washed out — daily solar ran ~15% high, and monthly, yearly, lifetime, self-consumption,
  autarky, savings and ROI all inherited it. The mirror error (the counter *under*-reports by day,
  since PV routed DC→battery never leaves as AC yield) would have cancelled it, but keeping only
  the maximum made the two ratchet instead. Counter movement is now ignored while the sun is below
  the horizon — no production exists to recover in the dark. The case #556 was built for is
  untouched: a cloud-polled inverter whose *power* sensor sits at 0 **during the day** still gets
  its counter delta credited. (by @traktore-org)
- ☀️ **"Solar only" grid-charged at night on every install — the never-grids default was
  unreachable** (#679, found while diagnosing @onkelfu's #627) — #634 settled the axis: the mode
  is the *daytime* axis, the "At least X" floor is the overnight guarantee, and leaving that
  floor at 0 is what keeps the "Solar only never charges from the grid" promise. The floor was
  never 0. Setup writes a default daily target of 10 kWh into every entry, and an unset SOC
  target reads as 80% — so the gate that asks "did you ask for an overnight guarantee?" was
  reading a number the installer had filled in, and answered yes for every Solar-only charger
  ever configured. Solar only therefore behaved exactly like Min + Solar, which makes it not a
  separate mode at all. It also read the kWh target even on a charger targeting %, so an
  SOC-targeted charger was opted in by a box it does not use. Now the overnight floor only
  counts as an opt-in when it is set **on that charger**, in **the unit that charger targets**;
  the other modes are unchanged, because for them the overnight top-up is the point of the mode.
  If you had set a per-charger "At least" value under Solar only, nothing changes — if you had
  not, your Solar-only chargers stop at sundown, as documented. The two copies of this gate
  (coordinator + state machine) were hand-kept in sync and are now one function. Guarded by
  `tests/test_679_solar_only_night_default.py`, which builds every case from a real install's
  defaults rather than a hand-written config — the reason the existing contract test passed
  while the contract was broken in the field.
- 🔌 **A charger set to *off* kept charging out of the house batteries, and SEM's stop
  could never have worked** (#627, reported by @onkelfu) — the diagnostics showed the mode
  was right (`charge_mode: "off"`), the intent was right (`last_desired: "OFF"`) and the
  command was issued 130 consecutive times (`last_actions: ["DISABLE"]`) while the car
  pulled 4.1 kW, 3.5 kW of it out of the house batteries, at night. The stop was correct
  and unenforceable: on a charger configured with only a current `number.*` entity, two
  layers each delegated the stop to the other. `_set_current(0)` skips the write when that
  entity's minimum is above 0 A — HA core rejects out-of-range writes (#487) — on the
  understanding that "the actual stop is the adapter's job"; and the adapter's
  `stop_session()`, finding no stop service, no charge-mode select, no start/stop switch
  and no `<domain>.disable`, logged that it was "relying on `_set_current(0)` alone" — the
  write that had just been skipped. Composed, nothing stopped the car at all. SEM now
  *computes* whether it holds any mechanism that can open the contactor, from the same
  fields the stop actually dispatches on, and surfaces it as a repair naming the charger,
  the power still flowing and the missing entity — instead of counting failed stops into a
  warning that fired three times and then went quiet. A capability that is asserted rather
  than checked is the same shape as the bug. The DISABLE is still issued (it costs nothing
  and starts working the moment you configure a start/stop entity), and — deliberately —
  the charging path is untouched: a charger SEM can start but not stop keeps charging
  normally while the un-stoppability is reported, because conflating the two signals would
  have cost every such install its surplus charging. Guarded by
  `tests/test_627_stop_unenforceable.py`.
- 🔢 **On a multi-charger install, every charger decided against 32 A / 230 V regardless of
  what it actually is** (#678, found by #665's new coverage) — `decide()` reads
  `ev_max_current`, `ev_min_current`, `ev_phases` and `ev_voltage` off the per-charger
  config entry, and **nothing ever writes the first or the last of them into it**: there is
  no config-flow field for either, and the seed keys cover only min-current and phases, only
  for entries migrated from schema v3. Verified live on a normally-installed entry: all four
  read `None`, top-level config included, so decide silently used its own literals. No
  over-current ever reached hardware — the adapters clamp every command to the charger's
  real ceiling, which is exactly why this stayed invisible for so long. What it *did* break
  is the priority cascade: a 16 A charger commanded at 32 A claims 22 kW of solar it cannot
  physically draw, and that phantom claim is subtracted from what the next charger in the
  priority list is allowed to see — the second car quietly gets nothing, or gets started on
  watts the sun never produced. The view now fills those keys from the fleet config and
  clamps them to the adapter's own `max_current_a` (which already folds in the control
  entity's maximum, #536). A configured value may ask for *less* than the hardware allows,
  never for more: the computation ends at the same ceiling the command is clamped to, so
  probe and production cannot drift — the same principle as #627 above.
- 🌙 **A restart just after midnight no longer swallows the day's EV virtual-SOC decay**
  (#645, coherence-audit) — while a car is away SEM can't watch it being driven, so each
  day rollover advances the estimated-SOC by the predicted daily consumption. That decay
  rode on an in-memory date that is re-initialised to *today* on every start, so a restart
  spanning midnight (nightly backup, HA update, power blip) made SEM believe the rollover
  had already been handled and skip it. Not cosmetic: when the real SOC entity is offline
  the night-charge planner falls back to the virtual SOC, reads "still nearly full", and
  silently skips a charge the car needed. The date the decay *last ran* is now persisted
  separately from the hour-bucket tracker, so "already decayed today" and "never decayed
  today" stop being the same state — restart later the same day still decays exactly once,
  and a multi-day outage catches up one decay per missed day (bounded).
- 🕐 **Four places asked the container what day it is instead of asking Home Assistant**
  (#645, coherence-audit) — swept while fixing the above. `date.today()` and
  `datetime.now().date()` read the *operating system's* timezone, which on a supervised or
  Docker install is routinely UTC while `hass.config.time_zone` is the user's. Near
  midnight the two name different days. Affected: the energy-assistant daily trend key
  (a day's stats could land on the wrong key or overwrite the previous day's), its
  "best time to run appliances" tips (which quote a wall-clock hour to the user and were
  off by the whole UTC offset), the PV month-to-date divisor, and the appliance
  "completed/missed today" counters. All now use HA-local time. Duration arithmetic on
  `datetime.now()` is untouched — both ends use the same clock, so it was never wrong.
  Guarded by `tests/test_645_day_boundary_registry.py`, which also **declares** SEM's four
  intentional day boundaries (calendar midnight, EV deadline, sunrise-EV, sunrise-load) so
  the next contributor adding a daily counter has to answer "what happens if HA restarts
  across your boundary?" — the question this whole issue turned out to be.

- ⚡ **Yearly EV charging energy was frozen at zero while daily EV energy counted normally**
  (#666, coherence-audit) — `sensor.sem_yearly_ev_energy` never moved, and neither did
  lifetime EV. The cause is a one-word disagreement: EV energy was *written* under the
  accumulator category `ev_daily_sun`, but four independent places — both yearly reads, the
  year-start seeding from the recorder, and the hardware-counter reconcile — each read
  plain `ev`. Since one call increments daily, monthly and yearly together, PROD showing
  daily 10.77 kWh next to yearly 0.0 is only possible if the read and write keys differ.
  It hid for so long because a restart re-seeds the year from HA's recorder, so the sensor
  looks right for one cycle and then freezes again until the next restart. The category is
  now plain `ev` — the sunrise/deadline reset lives in the day *key*, which is where a
  boundary belongs; a name containing "daily" was wrong for three of the four periods it
  actually wrote. Existing stores are migrated in place on first load (values summed, never
  dropped), so your EV history carries over. **New:** `sensor.sem_monthly_ev_consumption_energy`
  — the monthly EV accumulator has been written since day one and was the only period with
  no sensor to surface it. Guarded by `tests/test_666_ev_accumulator_keys.py`, which runs
  one real integration cycle and asserts daily/monthly/yearly move together for *every*
  category, so the next read/write drift fails without anyone remembering to add a case.
- 🏷️ **38% of SEM's entity labels named entities that don't exist — including every
  `sem_monthly` one** (#667, found while fixing #666) — labels are applied with an
  exact-match lookup on the entity key, and a miss applies nothing and reports nothing, so
  the registry could not tell you it had rotted. Filtering the HA entity list by
  `sem_monthly` returned *nothing* while all six monthly sensors existed and held data.
  Eleven keys were pure suffix drift (the label key was the entity key minus its `_energy`
  suffix) and are fixed — every monthly sensor now actually carries its label (live-checked
  on HA-TEST). On its own that does **not** restore the filtering: live verification turned
  up a second, independent cause — SEM never registered its labels with HA at all, so every
  reverse lookup returned nothing even for correctly-attached labels. That is #670, fixed
  below; you need both. The remaining 33 orphans were then triaged
  individually and came back as one class rather than 33 judgement calls: **the sensor was
  deleted and the label was left behind.** `sensor.py` names 26 of them outright in its own
  `# Removed:` comments, so the file that dropped the entities is the file that says which
  labels went stale — nobody had re-read it. Two were live entities under a drifted name
  (`battery_cycles` → `battery_cycles_estimated`, `battery_health` →
  `battery_health_score`) and are repointed; the other 31 are deleted, including the
  near-misses of a *working* label (`daily_solar_yield` vs `daily_solar_energy`), which
  would have double-labelled one entity if repointed. The registry is 116 → 85 keys with
  **zero** orphans, and `tests/test_667_label_registry.py` now bans them outright instead of
  ratcheting — plus a guard that the scan covers every platform SEM forwards to, since a
  missed platform makes real entities look like orphans and invites allowlisting them.
- 🏷️ **Filtering or automating by a SEM label now actually works — the labels had never
  been registered with Home Assistant** (#670, found while live-verifying #667) — SEM wrote
  label *ids* straight onto its entities, and `async_update_entity(labels=...)` stores them
  verbatim: it neither validates nor creates them. So all 19 SEM labels were inert strings.
  The forward direction looked fine (`labels('sensor.sem_monthly_solar_yield_energy')`
  returned all four), but `label_entities('sem_monthly')` returned **0** and
  `label_id('sem_monthly')` returned `None` — and the reverse lookup is the entire point:
  it is what the entity-list label filter, label-scoped automations and auto-entities
  dashboards use. SEM now creates each label in HA's label registry before applying it,
  **create-only** — an id that already exists is left completely alone, so renames, colours
  and your own labels are never touched. This is also why #667's drift survived for years:
  with the registry side missing, a correct label and a typo'd one behaved identically.
  `sem_exclude` is retired in the same pass (attached to nothing, read by nothing) — now
  that these become real labels in your registry, a dead one would show up promising to
  hide entities and do nothing.
- 🧹 **A 180-line map of entity IDs that mostly didn't exist is gone** (#669,
  coherence-audit) — `consts/sensors.py` held a 64-entry `key → entity_id` map that **no
  production code ever read**, and 29 of those 64 (45%) named no entity: `home_consumption`
  (the real one is `home_consumption_power`), all ten `solar_to_*` / `grid_to_*` flow keys
  renamed to `flow_*_energy` long ago, and the same `_energy`-suffix drift #667 just fixed
  in the *other* registry — uncaught here because this one is never looked up. Its only
  test asserted a dict literal against itself, so it read as covered while being dead. The
  danger was never the dead weight, it was that anyone reaching for it got a plausible
  `sensor.sem_home_consumption` that has never existed. Deleted, and the one real guarantee
  its test was reaching for (primary charger sensors keep unsuffixed names) is now checked
  against the platform file that actually creates the entity, so it can fail. Also removed:
  four values the coordinator emitted every cycle for no reader — two of them,
  `solar_efficiency` and `battery_efficiency`, were **hardcoded constants wearing the name
  of a measurement** (`85.0 if solar_power > 0`), which would have shown a made-up number
  as a real one had anything ever surfaced them. A new guard checks that *every*
  `sensor.sem_*` reference under `consts/` names an entity some platform actually declares.
- 🤖 **The file every AI agent reads first had been wrong since v1.0.0** (#671,
  coherence-audit) — `.github/copilot-instructions.md` sat untouched from April through
  ~25 releases. Six file paths, five constants and one service it named no longer existed,
  and it documented the registry deleted in #669. The dangerous part wasn't the dead
  references though: it stated `DEFAULT_UPDATE_INTERVAL = 300  # 5 minutes` when the real
  value is `10` **seconds** (30× off, with the wrong unit spelled out), and gave
  `DEFAULT_BATTERY_PRIORITY_SOC` a wrong number *and* an inverted meaning. An agent has no
  reason to re-derive a number a doc states, so those produce broken code rather than
  confusion. Rewritten to point at the modules constants live in instead of quoting them —
  a quoted number drifts, a file reference can't — and guarded: every path it names must
  exist, every symbol it names must appear in the tree, and restating a numeric constant
  now fails CI outright. No user-facing change; it protects everything downstream of it.
- 🖼️ **Every screenshot in the user guide was a broken-image icon on GitHub** (#672,
  coherence-audit) — when #618 moved the guides into `docs/`, the files moved but their
  *relative* links didn't, so `docs/USER_GUIDE.md` still linked as if it sat at the repo
  root and every target resolved one directory too deep. Four tab screenshots rendered
  broken, and the ⭐ cross-reference the guide calls "the canonical reference"
  (EV Charging Logic, linked from three places) 404'd. Every target existed the whole
  time — only the prefix was wrong. The issue-template's playbook link was broken the
  same way. Now guarded: **every** relative markdown link in the repo must resolve, not
  just the 12 config-card help links #618 covered.
- 🚦 **A new install with no Energy Dashboard failed with a bare error code instead of an
  explanation** (#674, coherence-audit) — SEM reads your solar/grid/battery sensors from
  Home Assistant's Energy Dashboard, so it aborts setup if that isn't configured yet. The
  abort *reason* was raised correctly and the code even passed a link to `/config/energy`
  — but the message it referred to had never been written, so HA rendered the raw key and
  the very first thing SEM said to a new user was the literal string
  `energy_dashboard_not_configured`. Both abort messages now exist, in all 16 languages,
  and name exactly what to add and where.
- 🌡️ **The whole Heat Pump settings screen showed raw field names instead of labels**
  (#674, coherence-audit) — and so did the EV-charger add/remove menu. `strings.json` and
  `translations/` are a hand-maintained mirror of each other, and they had drifted **50
  keys one way and 35 the other, identically in all 16 languages**. The trap is worth
  naming: `strings.json` is where a developer naturally edits — it is HA's documented
  source file, and the one hassfest validates — but **HA never reads it at runtime for a
  custom integration**; it loads `translations/<lang>.json` and nothing else. So the file
  that looked authoritative was the one with no effect. Opening Configure → Heat Pump gave
  you no title, no description, and eight rows reading `heat_pump_relay1_entity`,
  `heat_pump_climate_entity` … because the frontend falls back to the key name when a
  label is missing. The `soc_cap_unenforceable` repair (the one that explains SEM won't
  trust an *estimated* SOC for a hard charge limit) had no title or description at all.
  Everything is now translated in all 16 languages and the two files are held at exact
  parity by CI.
- 🔤 **Two error messages printed `{entity_id}` and `{service}` literally, and twelve more
  could never appear** (#674, coherence-audit) — swept while fixing the above.
  "Entity {entity_id} was not found" was shown verbatim, braces and all, because no call
  site ever supplies that placeholder; five of the 16 language files carried the broken
  wording and two carried a correct one, with nothing able to tell them apart. Twelve
  further `config.error` entries — per-sensor validation messages left over from the
  design the #397 setup slim-down replaced — were translated into every language for code
  paths that no longer set them. Removed, and CI now checks three things it never did:
  every error key is both declared and reachable, every abort reason has a message, and no
  string names a placeholder the flow never passes.
- 🧽 **A test that allowed "up to 10" dead translation keys was carrying exactly 10**
  (#676, coherence-audit) — 170 strings across 17 files for number entities that stopped
  existing in #255, when they became per-charger. The comment said "keys used by other
  systems"; nothing was using any of them. The allowance had been sized to the debt, so a
  full load passed. Deleted, and the threshold is now zero — a tolerance on a correctness
  check is the same shape as the bug it hides. Two keys that *looked* dead turned out to be
  live (the per-charger selects assign their translation key at runtime, which no static
  scan can see), so each was checked against the code rather than trusted to the grep.
- 🌍 **Nine per-charger sliders read English on every install, in every language** (#677,
  coherence-audit) — the mirror image of the #674 bug above: there a translation had no
  entity to reach it, here an entity had no translation to reach. When these settings
  became per-charger in #255 their entity key started carrying the charger id
  (`charger_keba_target_soc`), which no `strings.json` can declare — so Home Assistant
  looked the key up, missed, and fell back to a hardcoded English name. Nothing raised,
  because falling back renders *something*. Night Target, Min Amps, Vehicle Min Amps,
  Target SOC, Solar Max, Solar Max SOC, Battery Capacity, Consumption and Phases are now
  translated in all 16 languages. The two per-charger dropdowns had the opposite half of
  the same split — properly translated, but with no charger in the name, so a two-charger
  install showed two identically-labelled selects that only differed by entity_id. Both
  fixed by one mechanism: the charger name is now a `{charger}` placeholder inside the
  translated name. **Entity IDs are unchanged** — this renames nothing you have automated
  against, it only makes the label follow your language. Guarded by
  `tests/test_677_per_charger_names.py`, which derives the live key list from the platform
  source instead of mirroring it by hand — and that derivation replaced the two-entry
  exemption list #676 had just added, before it could grow into the next tolerance.
- 🌐 **4,554 strings said to be translated were still English** (#675, coherence-audit) —
  the last of the translation findings, and the only one no test can catch: every key
  existed in every language file, so the parity guards were satisfied — the *values* had
  simply been copied from English and never translated. It hid because "identical to
  English" is not a defect signal (`OK` is `OK` in Danish, `kWh` is `kWh` everywhere), so
  the only honest closure was to do the work rather than add a rule. Setup and options
  screens, repair issues, error messages and the long help texts under each field are now
  genuinely translated in **cs, da, de, es, fi, fr, hu, it, nl, no, pl, pt, ro and sv** —
  Finnish, Hungarian, Norwegian, Polish, Portuguese, Romanian and Swedish were close to
  fully English before this. Every string was checked back against its source for
  placeholder, markdown and line-structure parity before it was written, so the
  `{charger}`-style substitutions and the `**bold**` in help text survive intact.
- 🎛️ **Four services SEM registers had no UI at all, including the one the docs tell you
  to call** (#673, coherence-audit) — `services.yaml` declared 14 of the 18 services
  `__init__.py` registers. An undeclared service is still fully callable, so nothing ever
  raised and no test failed; what it loses is its entire affordance in
  **Developer Tools → Actions** — no description, no field pickers, no validation, so you
  had to already know the parameter names and hand-write the YAML. That landed hardest on
  `diagnose`: `docs/SEM_TRACE.md` tells users to call it with `section: trace`, and anyone
  following that instruction met an action with no `section` field and no hint that `trace`
  was one of *twelve* valid values. `remove_charger`, `get_config` and `set_option` were
  undeclared too. All four now ship full descriptions, fields and selectors — `diagnose`
  gets a proper dropdown of all twelve sections — and a guard asserts the two lists agree
  in **both** directions, so a service registered without a declaration (or advertised in
  the UI without an implementation) fails CI.
- 🌍 **288 translated strings in 16 languages described a settings step that has never
  existed** (#673, coherence-audit) — found by running the sweep question this issue added
  to the bug-class ledger rather than leaving it rhetorical. Every language file carried a
  complete `options.step.dashboard_options` block — title, description, eight field labels
  and eight field descriptions — for a config-flow step no `async_step_dashboard_options`
  has ever existed to show. Harmless at runtime (HA only looks up steps it is asked for),
  which is exactly why it survived: it read as a fully-localised feature. The cost was
  translator effort spent on a screen nobody can open. Removed from all 16 files, and a
  guard now rejects any translated step with no matching flow method.
- 💰 **Nine energy-accounting values were being thrown away on every restart** (#668,
  coherence-audit) — the calculator hands 20 values to the store on shutdown, but the
  store's hand-written whitelist carried only 11 through. The nine it dropped were read
  back with a default, so they reset silently: the seven `accumulated_*` running totals
  (savings, battery savings, cost, export revenue, grid import, self-consumed, export),
  the 30-day rate history, and the "yearly cost already seeded" flag. Two visible effects.
  With the accumulators at zero, `pre_sem_*` swallowed your whole lifetime and **Lifetime
  Total Savings became 100% a 7-day-average-rate estimate** instead of the rate-weighted
  figure SEM had actually accumulated — it moved every restart. And with the seeded flag
  reset, the yearly-cost seeding re-ran on every start and **overwrote** the live yearly
  accumulators with an estimate, discarding exact numbers in favour of approximate ones.
  Both directions now read ONE shared key list, so they cannot drift apart again — they had
  already done so twice (#351 M1 found the cost accumulators missing from both; this found
  nine more still missing after it), and a test asserts both functions use that same list.
  Restored scalars are also coerced now: a corrupt value used to be wiped by the drop, and
  once these actually persist it would otherwise survive every restart forever.
- 🔌 **EV charging that happened while SEM wasn't running is now recovered from the wallbox
  counter** (#658, coherence-audit) — SEM builds daily EV energy by integrating the
  charger's power sensor every cycle, so anything charged while it wasn't integrating —
  an HA restart, a core update, a power blip, a session started from the charger's own app
  while HA was asleep — was simply never counted. The wallbox counted all of it, which is
  why the two numbers disagreed. A reconciliation for this was written years ago and then
  parked, disabled, with six of its tests born skipped: it compared the counter's *absolute*
  value against the daily bucket, and the two don't share a day boundary (a KEBA counter
  resets at midnight, SEM's EV day rolls at your Charge-by time), so at the rollover it
  would have credited a whole night's charging to a freshly-reset day and told the planner
  the target was already met. It now works on counter *deltas* — the same model daily solar
  has used since #556 — which makes the boundary question disappear: a counter reset is just
  a reset. Multi-charger installs sum every charger's counter, because the bucket being
  corrected is the fleet total. Adoption stays upward-only, so an unavailable, stale or
  partial counter can never shrink your day, and a counter SEM is seeing for the first time
  is only a baseline — it is never claimed as today's charging. The baselines persist with
  the accumulators, which is the whole point: the gap being recovered is exactly the one
  where SEM was off. On by default, on the same `prefer_hardware_energy` setting that governs
  solar, and it needs a charger energy counter to be configured (SEM's hardware detection
  fills one in for most brands). Guarded by `tests/test_658_ev_counter_reconcile.py`,
  including the deadline-rollover and midnight-reset cases that parked the original.
- 🔗 **A circular "Requires" link between two loads can no longer be created — from any
  path** (#662, coherence-audit) — the drag-and-drop UI already refused to close a loop,
  but `register_surplus_device` (SEM's *only* multi-dependency write path) had no guard at
  all, and the guard the UI used walked just one of the two stores dependency links live
  in: service-registers-A→B then UI-sets-B→A slipped through. Under the default
  `must_active` mode both loads then wait on each other and neither ever starts. The walk
  now covers both stores and every write path, and a cycle already sitting in storage
  (written before the guard existed, or hand-edited) is broken at load with a warning
  naming the dropped link. **Removed:** `SurplusController.validate_dependencies` — a
  cycle *report* with no production caller whose walk hard-coded `deps[0]`, so a loop
  through a device's second dependency was reported clean. Nothing consumed the report,
  so neither limitation ever surfaced. Prevention at the write path replaces detection
  nobody read.

### 🧹 Feature removed by decision (#664 — ripple control / Sperrzeiten)

- 🗑️ **SEM does not support utility ripple control, and now says so** (#664, decided by
  @traktore-org) — the utility-signal surface was never reachable: `utility_signal_entity`
  had no config-flow step, no card picker, no `strings.json` entry and no docs, so on
  **every** install the monitor read nothing while three diagnostic entities
  (`utility_signal_active` / `_source` / `_count_today`) reported `false` / `"none"` / `0`
  forever. #654 had already amputated the half that *lied* (a WARNING claiming loads were
  being shed); #664 asked whether to build the shedding for real and the answer was no.
  Removed: the module, the three entities and their names/icons in all 16 languages, the
  coordinator wiring, and `HeatPumpController.block()`/`unblock()` — SG-Ready state 1, an
  actuator that had no caller for its entire life. `config_flow` no longer advertises a
  "4-state protocol" SEM cannot drive; it documents NORMAL / BOOST / FORCE_ON and says
  state 1 belongs to the grid operator's own lock. The **relay truth table keeps its
  BLOCKED row** — it is the SG-Ready standard, and installers verify their wiring against
  the full table (#523/#655). A guard test pins each way the surface could creep back.
  *Upgrade note:* the three entities were diagnostic and **disabled by default**, so on a
  normal install nothing changes — verified on the test rig, where the live entity count was
  identical before and after. Their disabled entity-registry rows survive the upgrade
  (Home Assistant does not reap registry entries for entities it never re-adds); they are
  invisible unless you browse disabled entities, and can be deleted there. If you had
  enabled one, it will read unavailable until you remove it.

### 🧹 Dead code removed (#659 — four features that could never run)

- 🗑️ **Dynamic 1p/3p charger phase switching was unreachable on two independent axes**
  (#659, coherence-audit) — `check_phase_switch` had no production caller since the legacy
  `_execute_ev_control` was deleted in `561e28a` (2026-06-22), *and* its
  `phase_switch_entity` config key was written nowhere: not in the config flow, not in
  `services.yaml`, not in the config card. It was always `None`, so the very first line
  returned early even if something had called it. Deleted, with a tombstone spelling out
  what wiring it would actually take. No user-visible change — it never ran. (Docs never
  promised the feature; the only mentions are two design docs listing it as future work.)
- 🗑️ **`set_anticipated_surplus` — the #106 "pre-warm devices before the EV taper
  completes" promise** (#659) — never called, and the two fields it set were never read.
  Its docstring described behaviour ("will factor this in 2 min before the deadline") that
  no code implemented, which is exactly what makes this shape dangerous: it reads as a
  working feature to the next person who greps for it.
- 🗑️ **A second battery force-charge brand factory** (#659) — `create_charge_adapter` ran
  the same platform key and the same auto-detect order as the live
  `battery_adapters.adapter_for`, in parallel and invisibly; nothing in production called
  it, only its own six unit tests did. Same shape as #651. The brand *classes* are
  untouched and still live. `should_stop` went with it — the real target-reached verdict
  is the scheduler's own SOC comparison, not a method on an object it never consults.
- 🧪 The orphan-method ratchet (`tests/test_653_orphan_methods.py`) shrank by three
  names. A fifth orphan found in the same sweep, `force_charge.get_status`, was
  deliberately **kept** and re-labelled *triaged* rather than *untriaged*: deleting an
  adapter's read-back surface is an interface decision, not a cleanup.

### 🧹 Dead code removed (#651 — the second EV surplus allocator)

- 🗑️ **SEM had two EV-surplus allocators; only one of them ran** (#651, coherence-audit) —
  `SurplusController.distribute_ev_budget` was a full priority cascade with its own
  60 s / 500 W hysteresis, a caller in the coordinator, 25 tests, five scenario YAMLs, two
  coverage-matrix cells and a three-refactoring history. Its output was written to
  `PerChargerContext.budget_w` — and **no consumer ever read that field**. The allocator
  that actually decides how surplus is shared is `decide.self_consumption_surplus_w`
  (`solar − home − solar_committed`), fed by `_solar_committed_w_per_cycle`, which the
  per-charger loop accumulates from each charger's *real* decision. The dead path, its
  field, its caller and its tests are gone. No behaviour change on any install: nothing
  read the value being computed.
- 🛡️ **The #351 M5 invariant was kept and retargeted, not deleted** — "an off-mode charger
  must not consume surplus its sibling could use" was a genuinely valuable contract that
  happened to be pinned on the dead path. It now drives the live one: an `off` charger
  decides `DISABLE`, commits 0 W, and the next charger in priority order sees the full
  undiminished surplus.
- 🐛 **Correction to the #629 entry below**: its "canonical solar-budget distribution
  (#282 B.5 total, #351 M5 off-exclusion)" slice and the "budget threading" it named as
  remaining loop architecture were both part of this dead path. The decomposition was
  real work on unreachable code — slice 2 made the dead path *cleaner*, which reads as
  progress. **Structure is not reachability.**
- 🔍 **Bug class 8 gained a test-side twin** (`docs/BUG_CLASSES.md`) — the scenario
  harness's `priority_order` assertion had a loop body of a bare `pass` under a comment
  saying it "can't reliably check from this side": a named, documented,
  scenario-selected assertion that could not fail. `test_multi_charger_canonical_budget`
  hand-copied the production branch into the test file and asserted it against itself —
  it stayed green through the branch being wrong *and* through it being deleted. New
  sweep question: **does this test call production code, or a local restatement of it?
  If you deleted the production function, would this test go red?**

### 🧪 Coverage restored (#665 — the allocator that does run)

- ✅ **The multi-charger scenarios now assert the cascade they are named after** (#665,
  coherence-audit) — #651 above removed assertions over a dead allocator and left two
  scenario files describing a priority cascade they had never verified. The harness now
  drives the live one for real: `build_charger_view` → `decide` → the running
  `solar_committed_w` total, per charger, in priority order. Three new expectations are
  available to any scenario — `per_charger_intents` (what each charger decided),
  `solar_commitment_cascade` (each charger saw exactly the sum of its seniors' claims, no
  more and no less) and `solar_committed_total_max` (a solar-funded ceiling, opt-in per
  scenario because `always_max` claims its nameplate on purpose, grid-funded if need be).
- 🔒 **The arithmetic moved into `charger_types.solar_commitment_w`** — one function, one
  caller in production, one in the harness. A test-side *re-implementation* of a formula
  is free to drift from the original and assert nothing while staying green; sharing the
  function makes any regression break both sides at once. This is the fix for the test-side
  twin of bug class 8 that #651 named.
- 🛡️ **AST guards for the half no harness can cover** (`tests/test_665_allocator_coverage.py`)
  — a harness driving its own copy of the loop stays green while the coordinator drops the
  per-cycle reset, drops the accumulation, or stops threading the total into each view.
  Deleting any of the three now fails CI with a message saying what breaks in the field.
- 🔍 **It found a live bug on its first run** — see #678 above. The scenario charger
  configured at 16 A came back commanded at 22 A.

### 🏗️ Code quality (#629 — EV orchestration decomposition, complete)

- 🧩 **Step 7.5a decomposed in four slices** (#629): per-charger night-target map,
  canonical solar-budget distribution (#282 B.5 total, #351 M5 off-exclusion), the pure
  night tri-state resolution (#247), and per-charger mode resolution — all in
  `ev_night_targets.py` with 18 behaviour-pinning tests. What remains in the loop
  (PerChargerContext lifecycle, build_view → decide → actuate, budget threading) is the
  reconciler architecture by design. Slice 1 was live-proven by the 23.07 night session.
  *(Superseded in part by #651 above — the budget-distribution slice and the budget
  threading were dead code; both are now deleted.)*
- 🔋 **Retired the deprecated coordinator-level battery shells** (#624, surfaced by the
  knowledge-graph audit) — `BatteryProtectionMixin` deleted (its one job, the startup
  discharge-limit restore, relocated to the battery pipeline module), and the standalone
  `BatteryChargeAdapter` instance + the scheduler's dead adapter dependency removed
  (provably vestigial: its `is_active` could never be true). The brand force-charge
  implementations moved into `battery_adapters/force_charge.py` where their real
  consumers live. Pure structural cleanup — zero behaviour change, guarded by
  module-gone + pure-planner + no-import-outside-package tests.

### ✨ Features

- 🔋 **The EV card's estimated SOC no longer blanks after a restart** (#635) — the boot
  restore has always read per-charger intelligence from `ev_intelligence.chargers.<id>`,
  but no save path ever wrote that key, and the primary save *replaced* the whole dict
  each cycle (also silently wiping the bounded session history). Saves now merge and the
  per-charger taper/SOC state persists — the battery graphic keeps its last-known value
  across restarts and between sessions. Display-only: charging decisions never use the
  estimate (they read the real vehicle SOC exclusively).
- 🔋 **Per-charger installs no longer double-feed the primary EV taper detector** (#639,
  coherence-audit) — the fleet energy block ran unconditionally alongside the per-charger
  feeder, so `energy_since_full` accrued at ~2× (virtual SOC read LOW → night over-charging,
  delayed "nearly full") and a sibling charger's draw could land on the primary's detector.
  The fleet block is now legacy-only (the #589 W2/W3 gate, completed on the energy path),
  with a top-level-counter fallback for the primary so legacy configs keep their drift-free
  hardware anchor. Shape-guarded so the gate can't be lost again.
- 🔥 **No more forced 65 °C disinfection cycle after every restart** (#640, coherence-audit) —
  the legionella-timestamp restore ran at first refresh, BEFORE the hot-water device was
  registered — a silent no-op, so every restart read "999 h overdue" and grid-heated the
  boiler to the legionella target. The seed now happens at the registration site (stored
  time restored; fresh installs seed "now"), and a guard keeps the dead parallel restore out.
- 🔁 **One anti-cycle clock, rebuild-proof** (#644, coherence-audit) — switch and climate
  devices kept a SECOND min-on/min-off timer on `_status.last_*`, wiped on every
  rediscovery rebuild, so a compressor could restart seconds after stopping. The legacy
  `min_on_time`/`min_off_time` knobs now map onto the base-layer
  `min_on_seconds`/`min_off_seconds`, whose epochs are rebuild-transplanted
  (`_VOLATILE_CONTROL_FIELDS`) — one clock, one enforcement, and a grep-lint guard
  keeps the `_status` clock from creeping back in as a gate.
- 🚗 **Every charger reads its OWN draw, on both read paths** (#642 + #643, coherence-audit) —
  the legacy (non-Energy-Dashboard) sensor path had drifted from its twin: it smoothed the
  fleet SUM and never filled the per-charger map, so on a multi-charger install every charger
  was told it was drawing the *whole fleet's* power — a second charger's session could make
  the first look "already at target". Both paths now share one `_read_ev_fleet_power` read
  (the #616 precedent applied to its `ev_power` sibling), so the median-of-3 blip filter is
  per charger too. Coordinator-side consumers (session attribution, diagnostics, taper feed,
  the priority rows) go through one sanctioned accessor — which also fixes a kW-reporting
  charger showing ~0 W in the device-priority list. AST-linted so the raw shape can't return.
- 🔋 **The battery sign cross-check now actually runs on multi-battery installs** (#647,
  coherence-audit) — the observe-only check that catches a battery reporting charge as
  discharge was gated on the *fleet* sign lock, which only single/combined-battery installs
  ever set. On a multi-battery install — the exact shape where one inverter can be signed
  differently from another — it was a permanent no-op reporting a healthy perception layer
  it had never tested (ledger class 8). And had it run, it compared SUMMED counters against
  SUMMED power, so one battery signed wrong and one signed right cancel to ≈0 W and get
  skipped as "idle". Each battery is now audited against its own charge/discharge counters,
  and the health surface names the offending unit (`b2`) instead of just "the battery".
  Two-sensor pair batteries are untouched — their direction is user-declared, so there is
  no lock to contradict.
- 📏 **A sensor reporting in kW is now read as kW everywhere** (#641, coherence-audit) — the
  "sensor value → watts" conversion was copy-pasted into eight places and every copy had
  picked its own rule for what counts as a kilowatt: exact-case `kW`, lowercase `kw`, the
  long spellings, or no check at all. So the *same* sensor could be read at 1000× different
  magnitudes by two subsystems in the same cycle — a charger sensor labelled `kw` (common on
  template and MQTT sensors) counted as 11 kW by the energy balance and 11 **watts** by the
  per-charger budget math. Worse, generic devices did no conversion at all: a heat pump or
  pool pump on a kW power sensor taught SEM a ~3 W rated power, which quietly wrecked its
  activation threshold, its solar-runtime credit and its shed decisions. There is now one
  rule, in one file, covering W/kW/MW/GW and Wh/kWh/MWh/GWh — and a CI lint that fails the
  build if anyone writes a ninth copy. One behaviour change worth naming: a power sensor with
  **no** unit at all is now read as watts everywhere, including the charging-history
  bootstrap, which used to assume kilowatts and so disagreed with the live reader by 1000×
  about the very same sensor.
- 🧯 **Removing SEM no longer leaves your heating latched on** (#656, coherence-audit) — if you
  removed the integration while it was holding a hot-water boost temperature, an SG-Ready
  relay or a surplus-controlled switch, teardown dropped its references to those devices
  without ever turning them off. The device stayed commanded on indefinitely, with nothing
  left in the system that could expire it — and reinstalling didn't help either: the
  reconciler sees a load that is on but not SEM-owned, calls it externally controlled and
  deliberately refuses to fight it. The purpose-built cleanup method for this existed and
  had never been called from anywhere. It is now, with the distinctions that matter: a
  **removal** or a **disable** releases every load SEM was holding, while a **reload** (any
  options change) and an **HA restart** deliberately do not — bouncing a running heat pump
  every time you change a setting is not a safety improvement.
- ⚖️ **A miswired import/export sensor pair is now caught instead of averaged away** (#661,
  coherence-audit) — installs without a single signed grid sensor (Growatt and friends) give
  SEM two always-positive sensors, and SEM nets them into one number. If those two are
  swapped, stale, or pointed at different meters they can both report power at the same
  instant — 3.0 kW in *and* 2.8 kW out — which nets to 200 W and looks exactly like a quiet,
  balanced house. Every downstream number then absorbs the error silently, because home
  consumption is derived from the balance. There *was* a mutual-exclusivity check for this,
  but it sat downstream of the netting, where "both directions at once" is not merely absent
  but unrepresentable: the two directional figures are re-derived from the single netted
  value, so the smaller side is always exactly zero (ledger class 8 — its test only passed by
  hand-building the impossible state). The check now runs at the netting site, on the raw
  pair, while both readings still exist, and covers the declared two-sensor battery
  charge/discharge pairs as well. It warns once after five consecutive contradicting cycles
  and reports recovery, and it ignores meter bleed — an export sensor idling at 15 W under a
  3 kW import is noise, not a contradiction.
- 🔍 **"Why is my car not charging?" is answerable again** (#657, coherence-audit) — the EV
  charging-status sensor exposes `battery_too_low`, `battery_needs_priority` and
  `solar_sufficient` attributes, and all three were permanently empty: the coordinator
  decided them every cycle and the sensor formatted them, but the value was never written
  onto the data the sensor reads. The one surface designed to explain a blocked charge
  explained nothing, so the support thread went in circles. Eight attributes across four
  sensors were wired to keys no code has ever published — the available-power sensor's
  house-consumption, battery-allowance and excess-solar breakdown, and the load-management
  card's device table (which the load manager had been computing all along) are back too.
  The top-5 peak history was removed instead: no producer for it was ever written, and a
  real one means querying long-term statistics — a feature, not a bug fix. The suite had
  been *masking* this, because the test fixtures injected exactly these keys; a new contract
  test now reads the actual producers and fails CI for any attribute wired to a phantom key.
- 🩺 **"Health check: 0 violations" now means something was actually checked** (#660,
  coherence-audit) — nearly every check verified a value against a constraint its own
  producer had enforced three lines earlier: `0 ≤ autarky ≤ 100` on a number assigned
  `max(0, min(100, …))`, "cost is not negative" on `max(0, …)` fields, "solar is not
  over-allocated" and "no flow is negative" on the output of a greedy allocator that
  hands out `min(available, needed)`. Those are theorems, not tests. They could not fail,
  so the diagnostic reported a clean bill of health straight through the autarky bug that
  sat pinned at 0 % while self-consumption read 98 % — an in-range wrong number, which is
  the only kind a range check cannot see. The instrument is now **clamp engagement**: the
  clamped output is clean by definition, so what gets recorded is how much each guard had
  to *remove*. One engaged cycle is a transient; the same clamp engaged for five straight
  minutes is a wrong formula being held inside the valid range, and that is the violation.
  The negative house-consumption residual is reported the same way, and the remaining flow
  check is the one that spans two independent producers (per-string sensors vs the inverter
  total, over-count direction only — string discovery caps at four slots, so a legitimate
  under-count must not fire). Two thresholds were retuned off real hardware while we were
  in here: the −1 W floor called an inverter's overnight standby draw a fault every night,
  and the savings floor is deliberately left *un*instrumented because a negative raw saving
  is correct behaviour under a negative import price. A standing test now requires every
  surviving check to be demonstrated firing on a deliberately violating input built through
  the real derivation, and an AST guard stops clamped fields from drifting back into the
  non-negative list.
- 🔥 **The setup guide's SG-Ready table told installers to invert a correct heat-pump
  install** (#655, coherence-audit) — the relay table in `SETUP_GUIDE.md` still showed the
  mapping SEM used *before* #523 fixed it: a plain 2-bit count (Blocked `0:0`, Normal
  `0:1`, Boost `1:0`) instead of the SG-Ready standard the pumps implement (Blocked `1:0`,
  Normal `0:0`, Boost `0:1`). Following it does real damage, because the user is the
  actuator: you wire the contacts, ask SEM for Boost, watch relay **2** close while the
  guide promises relay 1, conclude your install is inverted, and switch on *Invert
  SG-Ready* — which inverts a correct install and makes SEM drive Boost as `1:0`, which a
  standard pump reads as EVU-block. Your heat pump then switches **off** on solar surplus.
  That is #523 exactly — RienduPre's Nibe report — reintroduced by the documentation while
  the code was right the whole time. The table is corrected and now names the trap that
  caused it (the four states look like they should count in binary and don't), the
  README's four-state line carried the same stale count and is fixed, and a new test
  parses the shipped table and compares it row-by-row against `SG_READY_RELAY_MAP` so the
  guide and the code can never disagree again.
- ⚡ **SEM no longer claims to obey your utility's ripple-control signal** (#654,
  coherence-audit) — on a ripple-control (*Rundsteuerung*) signal, SEM logged a WARNING
  reading "shedding non-critical loads", turned on a binary sensor, and then shed
  precisely nothing: the function that chose which devices to block had no caller, and
  the heat pump and every surplus load carried on. For a user with a contractual block
  window, that log line was confirmation of compliance they did not have — the kind of
  discrepancy that only surfaces on the utility's meter. Nothing acts on the signal
  today, so SEM now says so: the log reports the signal and states plainly that no loads
  are being shed, the module and class docstrings describe what the code does instead of
  a SurplusController integration that grep proves absent, and the dead selection code is
  gone along with a diagnostic field that could only ever read "nothing blocked" — which
  reads as *the block ran and matched nothing* rather than *there is no block*. Building
  the real thing is #664, which first has to settle a question SEM cannot infer: whether
  a load running on your own PV is inside the block, which depends on your operator and
  contract. The heat pump's SG-Ready `block()`/`unblock()` were deliberately **kept**
  even though nothing calls them — they implement state 1 of the 4-state protocol SEM
  advertises during setup, and deleting them would make that promise unkeepable.
- 🍽️ **A finished dishwasher stops hogging the surplus for the rest of the day** (#653,
  coherence-audit) — the appliance scheduler's lifecycle half was never wired up.
  `update_schedules()` — the code that moves a run scheduled → running → completed and
  releases the appliance — carried a docstring reading "called during coordinator update"
  and had **zero** production callers. That is not a cosmetic status bug: a scheduled
  appliance deliberately refuses to be switched off mid-cycle and claims its full rated
  power while it believes it is running, and nothing ever told it the run had ended. So a
  dishwasher that finished at 15:00 held 2 kW of the allocation against every
  lower-priority load until the next restart, and neither LIFO shed nor peak shed could
  take it back. The cycle now ticks the scheduler *before* allocating, so a run that ended
  this cycle has released its claim by the time the surplus is shared out. Cancelling is
  reachable for the first time via a new `cancel_appliance_schedule` service (previously a
  mistyped deadline could only be undone by restarting HA), the #426 transition telemetry
  is finally readable in the diagnostics download, and a timezone-aware template deadline
  (`{{ today_at('18:00') }}`) is normalised at the service boundary — it would otherwise
  have thrown on every cycle now that something actually runs the comparison. A new AST
  ratchet fails CI on any new public method with no production call site, which is the
  class this belongs to: designed, unit-tested, and unreachable. It found one more on its
  first run (#663).
- 🚗 **A second car's charge estimate no longer freezes at "full from last Sunday"** (#648,
  coherence-audit) — while a car is away SEM can't watch it being driven, so each day
  rollover advances the taper detector's virtual state of charge by the predicted daily
  consumption. That decay only ever reached the PRIMARY charger's detector, and it was gated
  on the *fleet* "an EV is plugged in" flag (ledger class 3). So a second car charged full on
  Sunday, drove all week, and its estimate still read ~100 % — and any one car sitting plugged
  in overnight froze the decay for every other car too. This is load-bearing when the real
  SOC entity is offline: the night-target planner falls back to the virtual SOC, sees
  "nothing to charge", and silently skips a charge that was needed. Each detector is now
  decayed on its own connection state. Single-charger installs are unaffected.
- 🔌 **A surplus load is no longer switched back on at dusk by the peak manager** (#649,
  coherence-audit) — peak shed/restore for surplus-mode loads ran in TWO engines with
  separate state, anti-flicker and restore criteria. Shedding twice was survivable;
  restoring was not: when the peak receded after sunset the load manager turned the switch
  back ON — zero surplus, surplus intent OFF — and the reconciler then read it as
  "the user turned this on" and left it running on grid all night. Surplus-mode loads the
  surplus controller actually drives are now excluded from load-manager shedding, restore
  and the "available reduction" figure, exactly as EV chargers already were (#461-peak).
  The load manager keeps sole ownership of *Peak-only* devices, and a load nothing else
  drives stays its responsibility — so no load ends up owned by nobody.
- 🛡️ **"Critical" and "hands off" survive the next rebuild** (#650, coherence-audit) — both
  toggles were written ONLY into the load manager's device dict, which the registry sync
  REPLACES wholesale on every rebuild (a drag, the 35 s re-discovery, a config change, a
  restart). So marking the freezer critical or a pond pump un-controllable reverted to the
  defaults within ~35 s and the next peak event shed the device anyway — ledger class 14,
  the same shape as the #122 dependency wipe. The flags now live in registry override stores
  next to priority / control-mode / dependencies, are re-applied at device build, and flow
  back into the load manager. Toggles set before this release are adopted once on upgrade,
  so nobody has to re-click them.
- 🎚️ **Five more config-card options now apply live, no reload** (#637) — hot-water
  min/legionella temperatures, heat-pump max setpoint, VPP reserve SoC and the mobile
  notification service route through the in-place config path (their consumers re-read
  every cycle; the notifier's service-detection cache resets on change). Options backed
  by differently-named number entities (the #542 map) now entity-route too — ending the
  legionella dual-path confusion. Construction-only keys (tariff mode, battery scheduler
  params) deliberately keep the reload. A classification guard test makes every card
  option declare its routing — nothing can silently join the reload-per-tweak set again.
- 🎚️ **The config card's peak sliders now apply live** (#636) — `target_peak_limit` /
  `warning_peak_level` / `emergency_peak_level` had no number entities, so `set_option`
  dropped them to the entry-write + reload path: a slider change during a charge session
  never reached the running planner (caught live when a mid-charge peak change didn't step
  the EV night rate). The three keys now route through the load manager's live updaters —
  applied within one cycle, persisted, no reload.
- ⚡ **The peak-managed night rate now actually engages** (#630 follow-up) — the
  always-present window deadline shadowed the new rate entirely (it computes first and
  clamps tiny requirements up to Min, so `top_up_amps` was never consulted). The night
  amps are now `max(deadline-required, peak-managed)`, so a lazy deadline no longer
  pins the session at the floor; a tight deadline still forces the required rate.
- ☀️🌙 **The "At least" floor is now the overnight guarantee in every mode — Solar only
  included** (#634, Guido's design) — the charge mode is the *daytime* axis; if the day's
  solar charging delivered less than the "At least" floor, the DIFFERENCE tops up overnight
  from grid by the Charge-by time (deadline-sized, peak-managed #630). On good-solar days it
  never runs; floor 0 keeps the classic "Solar only never grids at night" contract exactly.
  Internally mirrors the loads' three-source design (auto-derived, no new UI) — and the home
  battery is never used for the EV.

### 🐛 Fixes (#646 — stable-line field report, by @michelangelomonako-cmyk)

- 📊 **Valid state_class on 4 sensors** (#646) — `roi_annual_savings` (monetary) moves to
  `total`; `forecast_corrected_today`, `battery_scheduler_deficit_kwh` and
  `forecast_surplus_kwh` (found by the new whole-table sweep guard) drop the `energy`
  device_class — predictions/deficits fluctuate, so the pairing was invalid and broke
  long-term statistics. Warnings on every restart are gone.
- 💰 **ROI payback no longer claims "0.0 years" on fresh installs** (#646) — with too
  little savings history to estimate, the sensor now reads *unknown* instead of the 0.0
  default that looked like "already paid off" next to ~0 € annual savings.
- 📈 **Chart date adapter loads even when another card ships Chart.js** (#646) — the
  loader short-circuited when `window.Chart` already existed (defined by some other
  card's internal bundle) and never loaded the date-fns adapter, so time-scale presets
  (energy "Last 7 Days") rendered empty with "a complete date adapter" errors. The
  adapter now loads in that path too.
- 🎨 **System diagram readable on light themes** (#646) — sunrise/sunset, forecast-kWh
  and inverter-status labels were hardcoded pale dark-theme fills inside the SVG (out of
  card_mod's reach); they now switch to darker, higher-opacity variants via the theme
  helper when the active theme is light.

### 🐛 Fixes (from live testing, 24.07)

- 🌙 **"Finish overnight from: Battery" now only runs at night** (#633) — the Tier-2
  battery source had no time gate and fed a load "from the battery" at 09:10 in full sun.
  Gated on night in both control paths, and a load still running at daybreak is stopped
  (the class-17 pair: gate + stop). "Overnight" now means overnight.

### 🐛 Fixes (from the #629 overnight soak)

- ⚡ **Night top-up now runs at the peak-managed headroom rate** (#630, Guido) — the plain
  `min_plus_solar` night top-up crept at the Min floor even with kilowatts of peak headroom
  free. It now charges at the #274/C1 peak-managed rate (peak limit − expected home −
  higher-priority chargers − **live cheap-hours load draw**, so a running #620 load is never
  squeezed), finishing early and freeing the window for lower-priority loads. Installs
  without peak info keep the legacy Min-floor behaviour unchanged.
- 🔔 **Night-start notification now quotes the value the decision actually used** (#631) —
  it read the config snapshot (stale the moment you edit the target entity) instead of the
  live per-charger night-target map: the push said "8.0 kWh remaining" while SEM correctly
  charged 2.0. Both now come from the same map.
- 📖 **KEBA post-stop auto-start retries documented as bounded known behaviour** (#632) —
  the vehicle re-requests every ~11 min, the KEBA auto-authorizes, SEM kills each rogue
  session within one cycle (#552 guard) under the 1 kWh runaway cap (#553). Deliberately
  NOT "fixed" via the auth lock (a failure while locked would strand the car). See
  KEBA_FAILSAFE.md.

# [1.7.5-beta.24] — 22.07.2026

### 🐛 Fixes (caught in the live #620 overnight test, PROD 22.07)

- 🛑 **Switching a device's mode to Off now releases a load SEM was driving** — the Off mode
  only blocked new activations; a load SEM had already turned on stayed on forever ("SEM does
  not touch the device any more"). Mode → Off now stops a SEM-driven load once (markers and
  ownership cleared), then leaves it strictly alone. A load *you* turned on yourself is never
  touched — Off still means SEM keeps its hands off your own choices.

- 🔁 **A config edit no longer resets running loads' protection state** — editing any device's
  goals triggers a rediscovery that rebuilds the device objects, and the rebuilt objects lost
  their volatile control state (overnight-battery/cheap-hours force markers, anti-flicker
  timers, ownership). Live consequence: a second load starting on the cheap-hours window made
  the deficit cleanup shut down a running battery-overnight load 23 minutes before its Min
  runtime (the marker that exempts it had been silently wiped at 22:15:14). Re-registration now
  transplants the volatile state onto the new object; regression test replays the exact
  sequence.
- 🔌 **"Finish overnight from: Grid" is now actually grid-fed** — on a battery install the
  inverter's self-consumption logic covered cheap-hours loads from the battery, so the Battery
  and Grid picker choices were physically identical (identical discharge either way, confirmed
  live). While cheap-hours loads run, SEM now limits battery discharge to the rest of the home
  load — the same protection mechanism the EV already uses — so the grid feeds exactly those
  loads and the battery keeps serving the house.

### 🏗️ Architecture — one clean cut for load control

- 🔭 **Observer mode now runs the *full* real decision and just logs what it would do.**
  On a monitoring / secondary install (or HA-TEST on shared hardware), SEM used to fall
  back to a separate, dumber read-only path. Now it runs the exact same three-layer load
  pipeline — management → decision → **one** execution seam — against your live sensors,
  and at the seam it logs the command it *would* send (`OBSERVER · WOULD ACTIVATE Heizband
  @ 800W [source=solar]`) instead of actuating. You can watch precisely what SEM would do,
  and verify it's right, before handing it control — with zero hardware risk.
- 🧹 The parallel `observe_only()` implementation is **deleted** — observation is now a
  single flag at the one actuator (`reconcile_load`). A cleaner arc: the next load feature
  docks at exactly one layer (see `docs/ARCHITECTURE.md` → *Compute intent → reconcile*),
  and the "gate blocks activation but doesn't stop a running device" bug class becomes
  structurally impossible on the desired-state path (`docs/BUG_CLASSES.md` #17/#18).

# [1.7.5-beta.23] — 22.07.2026

### 🐛 Fixes

- 🌙 **Surplus is now physically bounded by solar production** (#620, reported by @onkelfu) — a load
  running overnight off the **battery** made SEM show a phantom ~1.6 kW of "surplus" at night (its own
  draw was added back into the feedback-free surplus signal, a daytime convergence trick). Fixed with a
  single invariant — *you cannot have more solar surplus than the sun is producing* — so the surplus is
  clamped to the live solar power: pinned to 0 between sunset and sunrise no matter what the add-back, a
  noisy grid sensor, or a battery→grid discharge tries to fabricate.

# [1.7.5-beta.22] — 21.07.2026

### ✨ Features

- 🎯 **Daily runtime goals for household loads** (#620, requested by @onkelfu) — a load's
  🎯 target editor gives it a **Min / Max runtime** dual-slider (Max is a persisted hard cap
  that overrides the Min), a daytime **Mode** (Off / Peak-only / Solar only / **Solar + battery**
  assist), a **"Finish overnight from"** picker (**Off / Battery / Grid**) for completing the
  runtime when the sun runs short, and an optional **stop condition** picked with an entity
  search. Two independent axes — daytime source vs overnight source — bounded by the grid peak
  limit and the battery reserve floor; no forced-grid deadlines by design.

### 🐛 Fixes (all caught on the real-hardware Heizband soak)

- 🛑 **Daily-max cap stops a running load** — the cap only blocked re-activation, so a load
  already on when it crossed the cap kept running past it.
- 🌙 **Overnight source change stops a running load** — moving the picker off Battery (or off
  Grid) now ends an in-progress battery drain / cheap-hours grid import, instead of running until
  the reserve floor or the cheap window ends.
- 🎚️ **Min/Max slider fixes** — handles were undraggable (`pointer-events:none`); added a split
  (⬍) affordance for when Min and Max overlap (mirrors the EV slider, #355).
- 🔎 **Stop-condition entity search** — the stop-sensor field is an `ha-entity-picker` with a
  working clear (✕) button, instead of free text.
- 🔒 **Atomic goal writes** — serialized goal-config writes so two rapid field changes can't drop one.


# [1.7.5-beta.21] — 21.07.2026

### 🐛 Fixes

- 🔋 **Individual battery sensors returned on multi-battery installs** (#623, reported by
  @RienduPre) — a fleet of two or more batteries that *also* set the combined
  *battery power sensor* override lost every per-battery sensor (`sensor.sem_battery_b1_power`,
  `…_soc`, `…_status`, `…_capacity` — all `unavailable`) partway through the 1.7.5 betas. The
  #597 override was placed above the per-battery read loop, so it short-circuited before the
  individual batteries were ever read. Per-battery (and per-inverter) readings are now populated
  independently of which sensor supplies the fleet total, so the individual figures come back
  while the combined override still wins the fleet scalar exactly where it should. The same latent
  coupling on the solar per-inverter path was swept in the same change.

# [1.7.5-beta.20] — 20.07.2026

### 🐛 Fixes

- 🎛️ **Load config card showed the wrong device's control** (#621, by @alexmc1510) — opening the
  *Configure* dialog for one load (e.g. a "car socket") could display a sibling load's switch (the
  "pool pump"). The dialog re-resolved the row by its energy sensor, which is empty for devices with
  no Energy-Dashboard energy counter (service-registered loads, heat pump / hot water, the battery
  row), so they all collided onto the first empty-key row. It now resolves by the row's unique id
  like every other card action — data and shedding behaviour were already correct; this was UI-only.

# [1.7.5-beta.19] — 20.07.2026

### ✨ Features

- 🌍 **Localized device names on the overview** (#615, by @RienduPre) — SEM's own heat pump and
  hot water now show their translated name on the system diagram (a Dutch dashboard shows
  *Warmtepomp* / *Warm water* instead of the English defaults), per user profile language.
  Custom-named or non-SEM devices keep their name. New device-name translations across all 16
  languages.

- 📚 **Docs truth & structure overhaul + GUI help anchors** (#618) — the EV charging guide is
  rewritten around the current 5-mode selector (the pre-v1.6.3 toggle reference moved to an
  archive with an old→new migration map); a docs index landed and the stray root-level guides
  moved into `docs/`; **every** Config-card section's docs link now lands on a dedicated,
  CI-guarded anchor (a renamed heading fails the build instead of silently stranding the GUI's
  help links); three parallel audits purged stale claims everywhere (wrong tab counts,
  card-mod/mushroom ghosts, advice referencing removed options); tab screenshots recaptured
  from the live dashboard.

- 🧳 **Zero required HACS cards** (#617) — the dashboard no longer needs any HACS frontend card.
  The glass styling is baked into the SEM cards themselves (card-mod retired), mushroom and
  apexcharts-card had no remaining uses, sankey-chart became optional (HA's native `energy-sankey`
  is substituted when it isn't installed), and Chart.js is vendored and served locally — charts now
  work on offline installs. Existing setups with the old cards are unaffected. Re-run
  *generate dashboard* after updating.


### 🐛 Fixes

- ♻️ **A load's daily solar-runtime target no longer restarts on every reboot** (#622, reported by
  @alexmc1510) — an auto-discovered load's "X/Y h on solar today" progress (the accrued runtime
  toward its daily-minimum goal, e.g. the pool pump) reset to 0 on every Home Assistant restart, so
  the load re-ran its whole target. The runtime restore ran once at setup, but a load whose switch
  entity isn't ready yet is only created by the 35 s delayed re-discovery — after that one-shot
  restore already found no device — and the rebuild refilled runtime only from an in-memory snapshot
  that was empty for a never-loaded device. The restore is now idempotent and re-applied from storage
  on every device rebuild, so a late-arriving load keeps its progress (extends the #586 fix).

### 🧹 Housekeeping

- 📝 **README household-load claims aligned with what ships** (#620) — the advertised EV-style
  dual slider / kWh goals / cheap-hours / guaranteed-by-deadline for switch loads were removed in
  #559; the README now describes the shipped minimum-runtime surface and tracks the rest in #620.
  Enhancement requests now surface a monthly-sponsorship link (feature-request template footer,
  issue chooser, and an auto-note when an issue is labelled *enhancement*).

**Full Changelog**: [v1.7.5-beta.18...v1.7.5-beta.19](https://github.com/traktore-org/sem-community/compare/v1.7.5-beta.18...v1.7.5-beta.19)

# [1.7.5-beta.18] — 19.07.2026

### 🐛 Fixes
- 🔌🚗 **Single generic/manual EV charger now actually starts charging** (#616) — a charger
  configured through the config-flow stores its plug, charging and current-control entities inside
  its own charger entry, not the old flat top-level keys. SEM's EV connection read only consulted
  those per-charger entities when *two or more* chargers were configured; with a single charger it
  fell back to the (empty) legacy top-level plug sensor. The result: SEM's own per-charger
  `charger_..._connected` correctly read *connected*, but the global `ev_connected` stayed *false*,
  so the charging policy reported *"min_plus_solar but EV disconnected"* and commanded **0 A**
  forever — the car never charged even with the cable plugged in. SEM now reads each charger's own
  plug/charging sensor whenever any charger defines one (matching how EV power was already handled),
  so a lone config-flow charger drives the fleet state correctly. Thanks @onkelfu for the precise
  diagnostics that pinned the exact mismatch.

### ✨ Features

- 📱 **Controllable devices are finally visible on mobile** (#614) — the compact layout gets a
  chip row below the system diagram: up to 3 house-load devices with glyph, name and live power;
  active in the device accent color, idle dimmed, tap for more-info. Desktop keeps the satellite
  strip; both views now share one muted accent (`#86A9B4`) instead of the old positional palette
  that read as fake semantics next to the flow colors.
- 💶 **Bring your own price sensor — documented tariff contract + Spanish 2.0TD recipe** (#612,
  proposed by @alexmc1510) — the setup guide now documents that ANY entity whose state is the
  current €/kWh works as the Dynamic price sensor, with a `raw_today`/`raw_tomorrow` curve
  attribute unlocking price levels, cheap windows and the planners. Includes a ready-to-paste
  Spanish 2.0TD three-period template (live-verified end-to-end) and a PVPC pointer. Zero new
  runtime code; 8 CI tests pin the sensor contract.

### 🐛 Fixes (cont.)

- 👻🔋 **Battery ghost node swept** (#614) — battery-less installs no longer show a permanent
  *"— W / sensor unavailable"* battery on the system diagram (all three variants; Energy-Dashboard-
  detected batteries protected from false hiding). Hidden nodes also drop out of the render
  dirty-check. Re-run *generate dashboard* after updating.

**Full Changelog**: [v1.7.5-beta.17...v1.7.5-beta.18](https://github.com/traktore-org/sem-community/compare/v1.7.5-beta.17...v1.7.5-beta.18)

# [1.7.5-beta.17] — 19.07.2026

### 🐛 Fixes

- 🔥♨️ **Heat pump / hot water no longer shows up twice in the overview** (#615) — a heat pump
  configured in SEM *and* also added to Home Assistant's own Energy Dashboard as an individual
  device appeared as two rows in the flow overview / priority list: once under your Dashboard name
  (e.g. *"warmtepomp"*) and once under SEM's control row. The device list deduped by internal id,
  but the auto-discovered Energy-Dashboard row and SEM's control row carry different ids, so both
  slipped through. SEM now dedups on the *shared underlying entity* (power / energy / switch), the
  same way it already does for service devices and EV chargers — the managed control row wins and
  the duplicate is dropped. Distinct devices are untouched.

**Full Changelog**: [v1.7.5-beta.16...v1.7.5-beta.17](https://github.com/traktore-org/sem-community/compare/v1.7.5-beta.16...v1.7.5-beta.17)

# [1.7.5-beta.16] — 19.07.2026

### 🐛 Fixes

- 🚗💤 **The full-car backoff now actually quiets the charger** (#610) — beta.15's backoff armed
  correctly after 3 declined ladders but never gated: the charger's last commanded intent stays
  *charge* across a give-up (the idle actuation is debounced), so the very next cycle re-entered
  the start ladder and kept climbing — caught within 30 seconds by live provocation on real
  hardware. The gate now sits above the charging split and holds whenever a backoff is armed and
  the car isn't actually drawing. Live-proven end-to-end on PROD: three declined ladders →
  *"next offer in 20 min"* counting down with the charger silent. If you installed beta.15,
  update — the backoff there is log-cosmetic only.

**Full Changelog**: [v1.7.5-beta.15...v1.7.5-beta.16](https://github.com/traktore-org/sem-community/compare/v1.7.5-beta.15...v1.7.5-beta.16)

# [1.7.5-beta.15] — 19.07.2026

### ✨ Features

- 🚗💤 **Full-car offer backoff** (#610) — a plugged-in car whose battery is genuinely full used to
  receive a fresh start-offer ladder every time solar surplus persisted, producing continuous
  charger commands all afternoon against a BMS that kept declining. After 3 consecutive declined
  ladders SEM now goes quiet for 20 minutes — ended instantly by a real draw (e.g. after cabin
  preconditioning frees headroom), an unplug, or a mode change, and the backoff survives HA
  restarts. The estimated SOC still never gates charging (#440 truth model) — this tunes the retry
  cadence only. The strategy sensor explains it plainly: *"full-car backoff — next offer in N min"*.

### 🐛 Fixes

- 👻 **The system diagram no longer draws a ghost EV node on installs without a charger**
  (#595, by @hrdilshan) — beta.11 hid the EV *tab*, but the reporter's actual circled complaint
  was the EV charger node on the system overview diagram. All three diagram variants now hide
  their EV branch (node, flow path, labels, availability tracking) when no charger is configured:
  the illustrated Lit diagram card, the schematic flow card (whose prefix mode previously ignored
  EV gating entirely), and the legacy vanilla card. The dashboard generator injects the flag using
  the same no-charger test that prunes the EV tab; K-Flow was already gated. Re-run
  *generate dashboard* after updating to pick it up.

### 🏗️ Architecture

- 🧱 **The multi-charger state-leak bug class is now structurally impossible** (#589) — the
  per-charger context's snapshot/restore swap (the mechanism behind four historical
  "charger B behaves like charger A" hotfixes, #284/#289/#315/#318) has been deleted entirely.
  All per-charger state lives on a durable per-charger store or the context object, and the
  legacy coordinator attributes are properties that dispatch on the active context — there is no
  write-back left to forget. Two long-dead swap fields were removed outright, and a CI guard now
  fails on any reintroduced swap. Verified by 4685 tests including a production-loop-shaped
  two-charger isolation oracle, plus live single-charger operation on real hardware.

**Full Changelog**: [v1.7.5-beta.14...v1.7.5-beta.15](https://github.com/traktore-org/sem-community/compare/v1.7.5-beta.14...v1.7.5-beta.15)

# [1.7.5-beta.14] — 18.07.2026

### 🐛 Fixes (all root-caused and provoked live on real hardware)

- 🧊 **No more false "Sensor frozen" warnings on split power sensors** (#611, by @ebnerjoh) — the
  frozen-sensor audit measured staleness from `last_updated`, which Home Assistant only advances
  when a sensor's *value* changes. A split discharge-power sensor (Fronius exposes separate charge
  **and** discharge power sensors) sits at a constant 0 W for well over 10 minutes while the
  battery charges — so it looked "frozen" though it was reporting fine every poll. Same false
  alarm hit `grid_export` while importing and solar overnight. Freshness now keys off
  `last_reported`, which advances on every state-machine write even when the value is unchanged; a
  genuine upstream stall (modbus/cloud) still freezes it and is still caught.

# [1.7.5-beta.13] — 18.07.2026

### ✨ Features

- 🏖️ **Vacation mode** (#594, by @tlinnet) — `switch.sem_vacation_mode` plus an optional external
  vacation-signal entity (point it at a ViCare-style holiday sensor, an input_boolean, or a
  calendar). While active SEM stops all comfort heating encouragement (no SG-Ready boost, no
  setpoint boost, no DHW solar heating — the pump's own program and frost protection run
  untouched); legionella pauses and runs promptly on return. Optional: let the DHW tank absorb
  free surplus at the minimum target only. EV/battery/loads unaffected.
- ⚡ **Grid-VPP event dispatch** (#580, by @blackpatina) — generic virtual-power-plant support,
  Axle Energy first: wire the event gate/direction/window entities and SEM dispatches export
  events (battery force-discharge above a reserve floor, EV pause, load shed) and import events
  (force-charge, EV boost) through its existing controls, reverting automatically at event end
  or restart. **Observer mode ships ON**: SEM logs and notifies what it *would* do — watch a few
  events, compare the per-event kWh accounting against your VPP's payout, then arm it.
  Docs: `docs/GRID_VPP.md`.
- 🇨🇳 **Simplified Chinese dashboard** (#608, glossary by @waphbs from #607) — all ~1200 dashboard
  strings in zh, with proper `zh-Hans`/`zh-CN` language-code resolution; 16 dashboard languages.

### 🐛 Fixes (all root-caused and provoked live on real hardware)

- 🛡️ **Observer mode survives config reloads** — the toggle previously lived only in the switch
  entity: every reload booted an unprotected coordinator until the switch re-synced (minutes).
  The observer and vacation toggles now persist into the config entry, and a hands-off install
  boots protected from its first cycle. Global observer also outranks the VPP's own observer flag.
- 🔌 **KEBA runaway-cap guard is self-healing** — the ~1 kWh box-level energy target could stay
  armed after a lost UDP release, killing every session ("box starts, dies in seconds, retries").
  The release is now reconciled on every charge command, with sensor discovery that works for
  KEBA's device-less integration (name-derived) and never caches a boot-time failure. Live test:
  guard armed mid-charge → self-released in 8 seconds, charge uninterrupted.
- 🚨 **Sign-contradiction alarm fires in one cycle** (#590) — `sem_layer_mismatch` now alarms on
  the counter audit's own 5-vote debounce instead of stacking a second streak on top (proven
  live: battery sign flipped → alarm on the first post-vote cycle, zero misbehavior meanwhile).
- 🧹 **Legacy EV priority flags retired** (#604) — `ev_load_priority` / `ev_shed_priority` /
  `ev_priority_over_battery` are migrated (v16 schema) into the ONE device-priority list;
  the old fallback-chain semantics are preserved exactly.
- 🔋 **Estimated SOC is marked honestly** — without a vehicle SOC sensor the EV card shows
  `~N%` with an "SOC (est.)" label and an explanatory hint, so the dead-reckoned estimate is
  never mistaken for the car's own reading.

# [1.7.5-beta.12] — 18.07.2026

### ✨ Configuration tab redesign (#605 + #606, by @tlinnet's reports)

- 📝 **Staged changes with Apply/Revert per section** — steppers, sliders, selects and
  toggles no longer save on touch: a changed row is highlighted (● badge on the section
  header too) and commits only on **✓ Apply changes**, or **↩ Revert** undoes it. Kills
  the mobile scroll-flick that silently changed values; option keys commit as ONE batched
  write per section.
- ⓘ **Help on every setting** — a per-row info button opens that setting's explanation
  with its factory **Default** and a one-tap **↺ Reset to default** (stages through Apply,
  so a reset is previewable and revertable). The global toggle is now a labeled
  **Explain settings** pill instead of a bare (?) icon.
- 📖 **Docs links per section** — every section header links straight to its exact chapter
  in the guides (anchored), and the guides got a freshness pass to match the new surface.
- 🧾 **Config change history** — every settings write is now an INFO log line with the
  changed keys and values, visible in the section's 🩺 Diagnose panel ("what did I
  change?").
- 🖼️ README Configuration description + screenshot refreshed from the live card.

# [1.7.5-beta.11] — 17.07.2026

> ⚠️ **beta.10 was recalled** — it shipped with the single-charger EV power regression fixed
> below. If you installed beta.10, update to this release.

### 🐛 Fixes (both root-caused live on real hardware)

- ⚡ **EV power read 0 for a single charger — start/stop flap on the real wallbox** — the fleet
  EV-power aggregation only summed per-charger power sensors for *multi*-charger setups
  (`len > 1`); a single charger configured through the modern `ev_chargers` list fell through to
  legacy fallbacks that resolve to nothing. SEM was blind to the car's draw: the EV's kW showed up
  as a phantom *home consumption spike*, the surplus budget oscillated, and the "car not drawing"
  start-escalation churned the contactor every ~10 s. Now the per-charger sum runs whenever any
  charger carries a nested power sensor (1 or N chargers), feeding both the fleet total and the
  per-charger view.
- 🔌 **KEBA: a lost UDP release left the box killing every session** (#553 follow-up) — the ~1 kWh
  runaway-cap energy target armed at session stop is released with a single fire-and-forget
  `set_energy 0`; KEBA speaks lossy UDP, and a dropped release left the box terminating every new
  charge within seconds (session energy already ≥ target) while SEM kept writing currents into
  sessions the box kept killing. The guard register is now **reconciled on every charge command** —
  SEM's own armed flag and the box's `energy_target` sensor are checked, and the release is
  re-sent until it takes.

### ✨ Dashboard & device priority

- 🚗 **EV tab hides when no charger is configured** (#595) — installs without an EV charger no
  longer get an empty EV dashboard tab.
- 🔥 **Heat pump + hot water are draggable rows in the ONE priority list** (#602/#576) — their
  surplus priority is now their position in the device-priority list (seeded from the old config
  values on upgrade), and the standalone Heat-Pump/Hot-Water priority sliders are retired. Their
  rated power is settable on the dashboard Config tab.

# [1.7.5-beta.10] — 16.07.2026 *(recalled)*

### ✨ Sensor-input flexibility (autodetect-first, manual override as fallback)

- ☀️ **Solar power on energy-only installs** (#592) — a SolarEdge/Sonnen (etc.) setup whose
  Energy Dashboard exposes only solar *energy* read solar power as 0, which clamped Home
  consumption to 0. SEM now honours a `solar_production_sensor` override on the Energy-Dashboard
  path (the same way the battery/grid overrides already work), and those power overrides now
  reload live when changed.
- 🔋 **Real battery cycle count** (#593) — SEM's throughput estimate only counts what it has seen
  since install and can't match the manufacturer's counter (e.g. Sonnenbatterie 249 vs SEM 165).
  SEM now **autodetects** a lifetime-cycle sensor on the battery device (EN + DE names), with an
  optional `battery_cycles_sensor` override; the estimate remains the last-resort fallback.
- 🔥 **Load-device power from a kWh counter** (#600, from @tlinnet's Viessmann ViCare) — a heat
  pump / hot-water / generic load whose only meter is a cumulative kWh counter can now feed it:
  SEM first **autodetects a companion power sensor** on the device, and otherwise derives a smooth
  power signal from the counter (dividing each step by the real elapsed time, so a slow yearly
  counter never produces the ~12 kW spike a fixed-window derivative would).

# [1.7.5-beta.9] — 16.07.2026

### 🐛 Fixes

- 🔋 **`battery_power_sensor` override now works on Energy-Dashboard setups** (#597, by
  @tsaligerseidl) — installs whose Home Assistant Energy Dashboard exposes only battery
  charge/discharge *energy* (no combined power sensor) could configure `battery_power_sensor`
  to point at a real power sensor, but SEM ignored it and reported battery power as null
  (SOC worked, power didn't). The override is now honoured on the Energy-Dashboard path,
  the same way the SOC override already was.

# [1.7.5-beta.8] — 16.07.2026

### 🐛 Fixes

- ☀️ **Forecast "Remaining" tile no longer contradicts "Forecast today"** (#598, by @ebnerjoh) —
  in the morning the Home-tab Forecast Details tile could show e.g. "Forecast today 70.8 kWh"
  beside "Remaining 35 kWh" with almost nothing produced yet. The remaining figure was being
  multiplied by the real-time dampening factor (which sits near its 0.5 clamp floor at dawn)
  while today's figure stayed raw — two different bases side by side. "Remaining" now stays on
  the same raw basis as "Forecast today" (remaining = forecast − production). Internal
  surplus/charging planning still uses the dampened value, unchanged.

# [1.7.5-beta.7] — 15.07.2026

### 🐛 Fixes

- 📱 **EV flow-dot animation now runs on iOS** (#591, by @hrdilshan) — the System Diagram
  card's animated power-flow dots were dead in the iOS companion app and every iOS browser
  (all WebKit). Replaced the SMIL `<mpath href>` reference with an inline `animateMotion path=`,
  which WebKit renders.
- 🌙 **Night/solar charging status no longer stuck on "Active" after the target is reached**
  (#596) — on a single-charger install the fleet charging state kept reporting the pre-target
  state ("Night charging active") while the charger had actually reached target and gone idle,
  so `night_charging_status` read `active`. It now reflects the charger's real state
  (`target_reached`). Multi-charger installs keep the master state, with per-charger states
  exposed separately.
- 🔔 **Honest "night charging complete" notification** (#596) — the completion push compared
  what was charged against the *daily* kWh target (e.g. "1.9/8.0 kWh"), which read like a
  shortfall when the car had simply reached its SOC target. It now shows only what was charged.

# [1.7.5-beta.6] — 14.07.2026

### 🐛 Fixes

- 🔋 **Home battery no longer duplicated in the house-load tiles** (#587, by @RienduPre) — since 1.7.5
  the battery is a first-class device in the priority list (#576), which also made it show up as a
  house-load device tile on the flow diagram even though it already has its own battery node right
  beside it. It's now excluded from those tiles (same as the EV charger already is) while staying in
  the Control-tab priority list.

# [1.7.5-beta.5] — 13.07.2026

### 📊 Enhancements

- 🔋 **Battery sign auto-detection + one-tap fix, at parity with grid** (#588, by @uberberben) —
  the battery charge/discharge polarity now gets the same hardening the grid sign got in #461/#476:
  - **Brand seed (soft)** — for known inverters (Huawei, SMA, GoodWe, Tesla Powerwall, Enphase, SolaX)
    the convention is seeded from the battery **power sensor's** integration, so a fresh install is
    right from the first cycle instead of waiting for counter movement. It's a *soft* default: the
    counter-correlation voter can still confirm or **override** it, so a brand-deviant install (e.g. a
    Huawei battery whose Energy-Dashboard mapping is reversed — the reporter's exact case) self-heals
    from the counters instead of being pinned to the wrong default.
  - **`Fix battery sign` button** (Config → Advanced) + **`flip_battery_sign`** service — one tap flips
    the polarity and copies a paste-ready report to the clipboard for a GitHub issue.
  - **`Reset`** now re-learns and clears **both** the grid and battery user flips.
  - **Magnitude-weighted voter** — a lock needs ≥ 3 samples and ≥ 0.75 confidence, so a come-up jitter
    burst can no longer flip the sign the way the old ±1 counter could.
  - **`diag_battery_sign`** sensor mirrors `diag_grid_sign`; per-battery on multi-battery installs.
  - The user flip is applied to **both** the fleet total and every per-battery reading, so the
    arbitrage / force-discharge actuator never sees a desynced sign on multi-battery installs.

# [1.7.5-beta.4] — 13.07.2026

### 📊 Enhancements

- 💶 **Energy Costs chart now reads as cash-flow** (#585, follow-up to #574 by @ebnerjoh) — spending
  (Import) is drawn **below** the axis and earnings (Export) **above**, and the **Net** line is signed
  so a profitable period reads **positive/up** instead of dipping below zero. Money in = up, money out
  = down. Chart-only; legend totals stay consistent.

### 🐛 Fixes

- 🕒 **Daily-runtime goal survives an HA restart** (#586, by @RienduPre) — a load's "day target"
  progress (accrued minutes toward its minimum-runtime goal) reset to 0 on every restart while the
  target itself survived. The restore ran before the device registry was initialised, so no devices
  existed to restore into; it now runs after registration. (autopilot fix)
- 🔤 **"Home battery" name is now translated** (#587, by @RienduPre) — the synthetic battery device
  added in 1.7.5 (#576) showed a hardcoded English tile; its name is localized to your language now.

# [1.7.5-beta.3] — 12.07.2026

> The **EV and every device** now honour the one priority list — not just the loads and the battery.

### 🐛 Fixes

- 🔌 **No more phantom "solar charging started" push for a car-less charger** (#584, by @RienduPre) —
  in a multi-charger setup a charger without a car looked "connected" whenever a *sibling* had one
  (it inherited the fleet-wide plug flag), so it entered solar-charging and fired a push. Each
  charger now uses its **own** plug/charging sensor, and the notification dispatcher skips any
  charger SEM doesn't see connected. (A charger with no plug sensor still falls back to the fleet.)

### 📖 Docs

- 🕒 **Pool pump "4 h/day on solar only"** is answered by the goal engine (#559, by @alexmc1510):
  register the pump as a surplus device with `daily_min_runtime_min: 240` + `top_up_policy: solar_only`
  — it runs on surplus toward the 4 h target any time of day and never grid-forces. See
  `docs/MULTI_DEVICE_GUIDE.md` → "Daily targets — the goal engine".

### ⚡ The EV charges before the battery when you put it there (#576 Phase 2)
- ✨ **The EV charger is now a first-class device in the priority list**, keyed by its own
  control id. Drag it above the home battery and it reclaims the solar that would otherwise
  charge the battery (above the reserve zone); drag it below and it yields — the same rule
  the loads follow. This replaces the old fixed 90 % SOC gate with your list position.
- ✨ **One priority axis for everything.** The list position now drives the multi-charger
  distribution order too; `ev_surplus_priority` becomes the seeded default. Out of the box
  the order is **EV → battery → loads** (loads yield to the battery until you drag one above
  it), with the **`Battery priority SOC`** reserve floor still an absolute override.
- ✨ **Every device type participates by position** — surplus switches, modulating loads,
  climate/AC, heat pump (SG-Ready) and hot water are all walked by their list slot and share
  the reclaimed battery-charge power accordingly.
- 🔎 **Self-explaining trace.** The layered trace now reports each device's list role
  ("sink at list position 2", "charging first — below reserve", "discharging — feeding") and
  how much battery-charge power the loads reclaimed — so "why did the pump stop early?" is
  answerable top-down.
- 🗓️ **Today's Plan covers every device** — the pool pump / heat pump / hot water now appear
  in the same forward timeline as the battery and EV ("expected to run", "done for today").
- 🖱️ **Rock-solid drag-and-drop.** The priority list was rebuilt on Lit-native pointer-drag
  (no more SortableJS fighting the render): the badge number always equals the position, a
  drop line shows where a card will land, and dependency ("Requires") children stay attached
  to their parent across any reorder — the number/order desync and the "connection got lost"
  bugs can't recur (locked by 43 drag/reorder unit tests).
- 🔗 **"Requires" links are loop-proof.** A dependency that would form a cycle (a device
  requiring itself, directly or transitively) is rejected and logged — two devices can never
  deadlock each other waiting to start. Links now persist across every rebuild and restart.
- 🩹 **Fixes from a full review:** the EV/battery/load/heat-pump power readouts on the card
  are back to correct units (a 2 kW charge no longer showed as "2 W"); the EV row's rating is
  its start threshold (min amps), not the misleading 22 kW theoretical max; mid-drag tab
  navigation no longer leaks the card.
- 🧹 **Retired the old per-charger priority knobs.** The Config-tab **Surplus Priority** and
  **Shed Priority** steppers (and their number entities) are gone — the drag list is the one
  editor now (surplus order = list position, shed order = the reverse walk). `ev_shed_priority`
  is removed entirely and stripped from existing configs on upgrade (schema v15); the
  `ev_surplus_priority` value is kept as the seed for a charger's initial list slot.
- 🔌 **Sensor-equipped loads show their real rating, not a 1 kW placeholder.** A switch/plug
  with a power sensor now **remembers** the draw it self-calibrated to (it survives restarts and
  the periodic device rebuild instead of resetting to the 1 kW default), and a freshly-added one
  is **seeded from its power sensor's recent history** so it shows its true rating right away.
  Loads that really draw under 1 kW keep the conservative 1 kW surplus-activation floor.
- ✅ Full test suite green (4300+ Python + 43 card tests); every new guard mutation-tested;
  force-charge / scheduled / arbitrage battery commands are honored (never reclaimed).

# [1.7.5-beta.2] — 12.07.2026

> **Pre-release.** Forecast chart no longer spikes at dawn/dusk.

### ☀️ Forecast power spikes fixed on "Forecast vs Production" chart (#575)
- 🐛 The forecast series spiked to ~80 kW at dawn and dusk while real midday
  solar peaked at ~8 kW. `forecast_reader` converted Solcast power kW→W using
  a magnitude heuristic (`< 100 → ×1000`), but Solcast publishes Watts — so
  every genuine sub-100 W dawn/dusk reading was inflated 1000×. Conversion is
  now driven by the sensor's declared unit, not its magnitude. (by @traktore-org in #575)

# [1.7.5-beta.1] — 11.07.2026

> **Pre-release.** Enphase IQ Battery temperature now auto-detected.

### 🔋 Battery temperature detected on Enphase IQ Batteries (#583)
- 🐛 SEM showed no battery temperature on Enphase installs. The `enphase_envoy`
  integration exposes each IQ Battery (e.g. IQ 5P) as a child "Encharge
  {serial}" device whose cell-temperature sensor is
  `encharge_<serial>_temperature` — a name with no `battery`/`cell`/`bms` token,
  so every auto-detect pattern missed it. Added an `encharge` temperature
  pattern (and guarded the inverter-temp fallback so it can never mis-claim an
  Encharge temp), so the battery temperature is now discovered automatically.
  (reported by @nicoziptous)

# [1.7.4] — 11.07.2026

> **Stable release.** Consolidates the 1.7.4 beta line (beta.1 → beta.35, detailed
> below). Headline: the **generic-device control arc** (#559) — a belief-vs-observed
> reconciler, desired-state observability and observed-runtime credit that bring
> every surplus load up to the same discipline the EV controller already had —
> plus **rock-steady EV charging on UDP-polled chargers** (#573's KEBA
> median-of-3 flap fix), **config-on-the-dashboard** (settings apply live, no
> reload), a **lifetime solar production sensor** (#573), and a **recorder-DB
> diet** so SEM's per-cycle sensors no longer bloat history (#581). Battery→grid
> arbitrage stays **deactivated** for stable (migration v14; tracked in #533).

### 🧩 Generic-device control arc (#559)
- ✨ **Surplus loads now get the same control discipline as the EV.** A
  `DeviceReconciler` tracks belief-vs-observed per device, a desired-state model
  makes ownership observable, and runtime is credited from *observed* on-time,
  not assumed. A median-of-3 pre-filter smooths the surplus input the same way
  the EV path is smoothed. Explicit device `rated_power` shows on the Control
  card (was shadowed by autodiscovery), and Energy-Dashboard re-discovery no
  longer destroys service-registered devices. (by @guidoeberle in #559)

### 🔌 EV charger no longer flaps on/off (KEBA UDP power blips, #573)
- 🐛 On a KEBA P30 in `min_plus_solar`, the charger cycled on/off every ~15 s —
  a single-cycle UDP power blip to ~0 W spiked computed home consumption, crashed
  the EV surplus below the battery-assist gate and collapsed the budget. A
  median-of-3 filter on `ev_power` absorbs the blip at the source. PROD-confirmed
  steady across solar_only ↔ min_plus_solar mode switches. (reported by Guido)

### ⚙️ Config on the dashboard — settings apply live
- ✨ PV-string rename, EV charge target / range / phases, and structural config
  keys are reachable and editable from the dashboard Config card, applied without
  an integration reload. (#550, #551, #566, #568)

### ☀️ Lifetime solar production sensor (#573)
- ✨ New `sensor.sem_lifetime_solar_yield_energy` reconciled against the
  inverter's own lifetime counter, localized across all 15 languages.
  (reported by @hrdilshan)

### 🗃️ Recorder-DB diet (#581)
- 🐛 SEM's high-frequency diagnostic sensors are no longer written to the HA
  recorder database every cycle — they were dominating history rows. Now
  in-memory / `_unrecorded_attributes` only. (autopilot)

### 🌡️ Honest sensors & dashboard polish
- ✨ Dedicated inverter-temperature sensor (the diagram had shown battery temp in
  the inverter slot, #564), climate-device surplus type (#569), restored
  Forecast-vs-Actual chart series (#575), dimmed rated power when a load is off
  (#577), Home header hero + quick-controls (#572), and a UI pattern guide (#565).

# [1.7.4-beta.35] — 10.07.2026

> **Pre-release.** Rock-steady EV charging on UDP-polled chargers (KEBA).

### 🔌 EV charger no longer flaps on/off (KEBA UDP power blips)
- 🐛 On a KEBA P30 in `min_plus_solar`, the charger cycled on/off every ~15 s.
  Root cause: the KEBA reports charging power over UDP and blips to ~0 for a
  single cycle while the car is really drawing ~10 kW. That reading feeds the
  home energy balance, so while the (fast) grid meter still shows the import, a
  0-blip momentarily spikes computed home consumption → the EV solar surplus
  crashes below the battery-assist gate → the charge budget collapses to 0 →
  the charger idles → the contactor opens → recovers → repeat. Fix: a
  median-of-3 filter on `ev_power` in the reader absorbs the single-cycle blip
  at the source (a genuine start/stop is 2+ cycles and still tracks within
  one), so the budget stays steady and the car charges flat. (reported by Guido)

### ☀️ Lifetime solar production sensor (#573)
- ✨ New `sensor.sem_lifetime_solar_yield_energy` ("Lifetime Solar Production")
  surfaces SEM's all-time solar total — seeded from and reconciled against your
  inverter's own energy counter (e.g. Deye `TotalActiveProduction`, Huawei
  `Gesamtenergieertrag`), so it lines up with the hardware figure. The existing
  **Monthly** and **Yearly** sensors stay period-scoped (they only cover
  production since SEM started tracking), which is why they can read lower than
  the inverter's lifetime counter — this gives you an apples-to-apples number to
  compare. Names localized across all 15 languages. (reported by @hrdilshan)

# [1.7.4-beta.33] — 09.07.2026

> **Pre-release.** SEM sensors no longer bloat the Home Assistant recorder database.

### 💾 SEM entities dominated the recorder database (#581)
- 🐛 On a 10 s refresh, SEM entities produced ~70% of all recorder state rows and
  grew the database to ~9.6 GB in ~10 days. Two causes: (1) a per-cycle
  `last_update` timestamp was stamped onto **all ~177 SEM entities** every tick,
  forcing a recorder write for every entity every cycle — even sensors whose
  value never changed; and (2) large UI-only maps (the ~9 KiB `devices` map on
  `sem_controllable_devices_count` alone = 816 MiB of payload) were recorded on
  every cycle. The volatile base attributes are removed, and the heavy UI-helper
  maps are now marked `_unrecorded_attributes` — they stay on the live entity so
  dashboard cards keep working, but are excluded from the recorder.
  (reported by @Edsol)

# [1.7.4-beta.32] — 08.07.2026

> **Pre-release.** Registered surplus devices survive device re-discovery.

### 🔌 A registered surplus load could silently stop being controlled (#559)
- 🐛 A device registered via `register_surplus_device` under an
  `energy_dashboard_…` id was **destroyed by every device re-discovery** —
  including the one that runs ~35 s after each restart: the discovery sync wiped
  all `energy_dashboard_*` devices, and the rebuild then (correctly) refused to
  recreate one whose switch is service-owned — so the load vanished from control
  entirely while the Control tab still showed its row. Reporter's pool pump never
  ran despite 1.6 kW of export. Service registrations now **survive discovery
  syncs by construction** — the live device object (with its accrued daily
  runtime) is left untouched, and discovery can't shadow or overwrite it.
  (reported by @alexmc1510)

# [1.7.4-beta.31] — 08.07.2026

> **Pre-release.** The "Forecast vs Actual" chart shows the forecast again.

### 📈 "Forecast vs Actual" chart restored (#575)
- 🐛 The **Forecast vs Actual** dashboard chart showed no forecast — just actual
  solar/home/grid power under a misleading title. The LitElement card migration
  had quietly repointed it at the plain power preset, dropping the forecast
  series; a later sensor cleanup then removed `forecast_power_now_w` as "dead"
  (dead only because the migration had already orphaned it). The forecast power
  sensor is restored (its value was always computed, just no longer published)
  and the card now plots **forecast vs actual solar** on a dedicated preset.
  (reported by @ebnerjoh in #575)

# [1.7.4-beta.30] — 08.07.2026

> **Pre-release.** The device arc, completed: honest runtime, spike-proof surplus, visible ownership.

### 🧭 Generic-device arc, phases 3+4 (completes the beta.29 foundation)
- ⏱️ **Daily-runtime goals now count reality, not belief.** A load whose switch
  actually reads *off* no longer accrues runtime toward its daily target while
  SEM's record catches up — so a goal can't be "met" by a load that wasn't
  actually running. Devices without a readable entity behave exactly as before.
- 🛡️ **Single-cycle spikes can't flap loads anymore.** A one-cycle inverter
  glitch or sensor blip used to nudge the smoothed surplus by 30% of its size;
  a median pre-filter now drops any value not seen in at least 2 of the last 3
  cycles before it reaches the smoothing, so marginal loads stop twitching on
  glitches. Real changes pass with one extra cycle of latency.
- 👁️ **You can now see *why* a load is on.** Every managed device reports its
  intent (`off` / `idle` / `on`), its observed state, and **`sem_owned`** —
  whether SEM turned it on or something external did — on the Control-tab data
  and in diagnostics.

# [1.7.4-beta.29] — 07.07.2026

> **Pre-release.** SEM no longer fights a manually-toggled surplus load.

### 🧭 Generic surplus loads: SEM now tracks reality, not just its own belief
- ✨ Switch and climate surplus loads gained a **reconciliation layer** (the same
  desired-vs-observed idea the EV charger already uses). Each cycle SEM now checks
  what the load is *actually* doing, instead of trusting its own record:
  - If a load SEM turned on is **switched off** (by you, another automation, or a
    failed command), SEM notices, updates its state (so daily-runtime isn't
    credited to a load that isn't running), and — importantly — **won't
    immediately turn it back on and fight you**; it waits a short cool-off first.
  - If a load is running that SEM didn't turn on, SEM leaves it alone rather than
    claiming or cutting it.
- This is **additive** — the tuned surplus-allocation logic is unchanged; SEM just
  keeps its picture of each load in sync with the real world. (foundation for
  bringing generic devices up to the EV charger's robustness)

# [1.7.4-beta.28] — 07.07.2026

> **Pre-release.** A device's rated power now shows correctly on the Control tab.

### 🔌 Explicit device rated power now shows (not 0 W) (#559)
- 🐛 When you registered a surplus device with an explicit `rated_power` for a
  switch SEM had *also* auto-discovered from the Energy Dashboard, the Control tab
  showed the auto-discovered row (the live sensor = 0 W while the load is off)
  instead of your value, and the explicit entry was dropped as a duplicate. The
  explicit registration now always wins for that switch, so your rated power
  shows. Auto-discovered devices also now show their self-calibrating rated power
  rather than a bare 0 W when off. (reported by @alexmc1510)

# [1.7.4-beta.27] — 07.07.2026

> **Pre-release.** More setup lives on the dashboard Config tab now.

### ⚙️ Rename PV strings & set the EV charge target on the Config tab
- ☀️ **Rename PV strings on the dashboard.** A new **PV Strings** section on the
  Configuration tab (shown when SEM detects ≥2 strings) lets you name each string
  (East, South, …) with an inline field — no need to open Home Assistant's
  integration settings. (#566)
- 🚗 **Set the EV charge target on the card.** The per-charger block let you pick
  the target *type* (kWh vs SOC) but not the actual value — now the target, its
  ceiling, kWh/100 km and phase count are editable inline (the right pair shows for
  the selected type). This continues moving setup out of the options flow onto the
  dashboard, where most of it already lives.

### ☀️ "Rename PV strings" is now easy to find (#566)
- 🧭 Custom PV-string names shipped in beta.21, but the step was buried at the
  very end of the options flow — you had to click **Submit** through seven
  forms to reach it, so most people never found it. There's now a **"Rename PV
  strings"** entry right on the first screen of **Configure** (shown when SEM
  detects ≥2 strings) that jumps straight to the naming step. Saving from there
  preserves all your other settings. (follow-up to @-reported #566)

# [1.7.4-beta.25] — 07.07.2026

> **Pre-release.** The Energy Costs chart legend now matches the summary card.

### 💶 Energy Costs chart legend showed the wrong series' totals (#574)
- 🐛 On the **Energy Costs** chart the legend printed numbers that
  contradicted the costs summary card — e.g. `Import: 1.8` while the import
  bars sat at ~0, and `Net: 0.1` while the net line was at −1.8. The bars and
  the summary were right; only the legend text was wrong. The legend paired
  each label with the wrong series because it indexed the datasets by the
  legend item's *position*, but Chart.js sorts legend items by each series'
  draw `order` — so on the mixed line+bar cost chart (net line before the
  import/export bars) the order didn't line up and the values rotated by one.
  It now indexes by the item's real dataset, so each label shows its own
  series' latest value. Savings/energy charts were unaffected. (reported by
  @ebnerjoh)

# [1.7.4-beta.24] — 06.07.2026

> **Pre-release.** The system diagram now shows the *inverter's* temperature.

### 🌡️ Inverter temperature is the inverter's own, not the battery's (#564)
- 🐛 On the Home system diagram the **inverter** node showed the *battery*
  temperature — a Fronius user saw a constant ~25 °C in the inverter slot while
  the real inverter ran at 40 °C. The card read `battery_temperature` for the
  inverter label. Now there's a dedicated **`sensor.sem_inverter_temperature`**
  (autodetected from your inverter's own temperature sensor, or *unknown* when
  there's no source — never fabricated), and the diagram reads it.
- 🔎 Inverter-temperature **autodetection now covers far more brands** — Fronius,
  GoodWe, DEYE/Solis/Sofar, SolaX, KSTAR, FoxESS, SolarEdge-modbus, SENEC, GivTCP
  and others that name the sensor without an "inverter" token (bare
  `…_temperature`, `radiator_temperature`, `tempsink`, `invtemp`, …), with a
  guarded fallback that won't mistake a battery/cell/ambient probe for the
  inverter. Battery-temperature detection also gained `temperature_cell`
  (Fronius core), `bmu_temp` (BYD) and `bms_bat_temperature` (GoodWe).
  (reported by @ebnerjoh)

# [1.7.4-beta.23] — 06.07.2026

> **Pre-release.** Control air-conditioners from solar surplus, and a Home-tab cleanup.

### ❄️ Drive `climate.*` air-conditioners / heat pumps from surplus (#569)
- ✨ New **climate** surplus-device type: an AC or heat pump exposed only as a
  `climate.*` entity (no switch, no `number`) can now be managed by SEM. On solar
  surplus it sets the unit's `hvac_mode` (e.g. `cool`) and an optional comfort
  target temperature; when the surplus is gone it turns the unit off. Same
  priority / peak-shed / daily-goal handling as every other surplus load, and the
  registration survives restarts (it re-owns a running unit after a reboot).
  Register it with `device_type: climate` on
  `solar_energy_management.register_surplus_device` — pick `hvac_mode: heat` to
  drive a heat pump the same way in winter. (requested by @Edsol)

### 🏠 Home tab: removed the leftover "Quick Controls" section (#572)
- 🧹 The Home status card carried a **Quick Controls** heading with nothing left
  to control — the observer-mode toggle moved to the **Config** card (#492, "Config
  is the single settings home"), leaving only a read-only forecast-provider chip
  under a controls heading. Removed the dead section (and its unused code/CSS); the
  forecast provider is still shown on the Solar tab. (reported by @RienduPre)

# [1.7.4-beta.22] — 06.07.2026

> **Pre-release.** Two consistency/telemetry bug fixes.

### 🌤️ Forecast numbers now match across pages (#568)
- 🐛 The Home tab's system-diagram showed a *different* "Today's Forecast"
  than the Solar tab (e.g. 23 vs 33.2 kWh). The Home glance was showing SEM's
  **performance-corrected** estimate (Solcast × how your array actually performs
  — ~0.69× on a cloudy day) while every other card shows the **raw** provider
  forecast. Both were correct but sharing one label was confusing. The Home
  glance now shows the same raw daily forecast as the Solar tab; the corrected
  estimate stays on its own sensor. (reported by @hrdilshan)

### 🔥 Heat-pump SG-Ready mode now reflects reality (#570)
- 🐛 With a Nibe SG-Ready heat pump, the **Mode sensor was stuck at
  "normal · 2"** even while SEM was correctly driving the SG-Ready relays into
  BOOST. The relays flipped fine — only the telemetry was dead: the coordinator
  never copied the controller's live SG-Ready state into its sensors. Now
  `heat_pump_mode` / `_sg_ready_state` / `_solar_boost` track the real state,
  and Boost / Force-on / Blocked modes are labelled in all 15 languages.
  (reported by @RienduPre)

# [1.7.4-beta.21] — 06.07.2026

> **Pre-release.** Name your PV strings, and an Off-mode timer fix.

### ☀️ Custom PV-string names (#566)
- 🏷️ Your solar strings no longer have to read **PV1 / PV2 / PV3** — a new
  **"Name your PV strings"** step in the integration options lets you call them
  **East / South / West**. Each field shows its source sensor and live power so
  you can tell which slot is which physical panel (the numbering follows your
  Energy-Dashboard solar list, not compass order). The names flow through the
  solar card chips, the system diagram, the flow card, and the entity names
  themselves (so they also show in HA history / the Energy Dashboard).
  (requested by @RienduPre)

### ⚙️ Load management (#559)
- 🐛 **Off-mode timer fix**: a surplus device switched to **Off** no longer keeps
  showing — and counting — its daily solar-runtime timer. The row hides and the
  counter freezes once SEM stops managing the device. (reported by @alexmc1510)

# [1.7.4-beta.20] — 06.07.2026

> **Pre-release.** Battery temperature autodetect reaches the Fronius
> Reserva / BYD naming.

### 🌡️ Battery temperature — finds the bare `cell_temperature` (#564)
- 🐛 **Fronius Reserva / BYD batteries showed *unknown*** after the beta.18
  honest-temperature fix. Their cell-temperature sensor is named without a
  `battery`/`1` token (e.g. `sensor.reserva_cell_temperature`), so the
  autodetect matched nothing. SEM now recognises the bare `cell_temperature`
  shape and picks up the real sensor (~24.5 °C) with no configuration —
  guarded so it can't hijack a secondary `cell_temperature_2`.
  (reported by @ebnerjoh)

# [1.7.4-beta.19] — 06.07.2026

> **Pre-release.** #559 load management — the goal engine, frozen to its
> honest core.

### ⚙️ Generic surplus loads — simpler, safer (#559)
- 🎯 The device **goal engine is back to its grounded core**: a mode ladder
  (Off / Peak only / **Surplus**) plus one *"run up to N hours today"* solar
  budget and an optional stop-condition (e.g. car SOC ≥ 80 %). Surplus loads
  are **solar-only** — they never import from grid.
- 🐛 **Removed two latent hazards** that shipped in the beta.18 engine: a
  daily-runtime *safety cap* that reset on every restart, and a *finish-by
  deadline* force that could drain the house battery at night with no
  state-of-charge gate. Both are gone with the speculative surface (energy
  targets, kWh caps, deadline ramp, "always" top-up) they lived in.
- 🔧 **Auto-discovered switch footgun fixed**: an unconfigured socket that
  read 0 W while off could switch on at almost any surplus and pull the rest
  from grid. SEM now **auto-calibrates the device's rated power** from its
  power sensor the first time it runs.
- 🎨 **Card simplified to the EV-charger pattern**: the mode picker sits in
  the goal panel (shown only in Surplus mode), a single hours slider replaces
  the dual-handle min/kWh slider, the stop condition is a clean row, and each
  mode has inline help. (requested by @alexmc1510)
- 🏷️ **Honest label**: the runtime target reads *"Run up to N h"* — it's a
  daily solar budget (the device rests once it hits N), not a guaranteed
  minimum, so the old *"at least"* wording was misleading.
- 📱 **Mobile fix**: the goal panel's "Stop when" row no longer overflows /
  wraps its label on phone widths.
- 💾 **Daily counters survive an unclean reboot**: device-runtime progress
  (and the rest of SEM's daily state) is now written to disk every ~2 min
  during runtime, not only on a graceful stop — a crash/power-loss reboot
  loses at most a couple of minutes instead of the whole day.

# [1.7.4-beta.18] — 05.07.2026

> **Pre-release.** Honest temperatures and a cleaner Home header.

### 🌡️ Battery temperature — never fabricated (#564)
- 🐛 **Installs without a temperature source showed a constant 25 °C** —
  that was an internal default published as if measured. The sensor now
  honestly shows *unknown* when there is no source (cards hide it), and
  SEM **autodetects the battery's real temperature sensor** via the same
  brand-aware hardware discovery the System diagram uses — most setups
  get their true cell temperature with zero configuration.
  (reported by @ebnerjoh)

### 🏠 Home header — the hero, once (maintainer UI review)
- 🎨 The Home tab header chips (Solar/Autarky/Today) duplicated the
  Today's-Production card right below it. The header itself is now the
  hero: big orange production value + live solar power chip; the
  separate KPI card is gone from the generated dashboard (it remains
  available as a card for manual dashboards). Autarky/Self-Use stay on
  the solar and home-status cards.

### 🧪 Hardening
- ✅ Regression lint: entity pickers can never again receive an empty
  domain filter (the #560 class).

# [1.7.4-beta.17] — 05.07.2026

> **Pre-release.** Load management grows up: daily targets for any
> household load, persisted registrations, a surplus event for your own
> automations — plus counter-accurate daily solar and a Home-tab
> production KPI.

### 🎯 Load management — daily targets for household loads (#559)
- ✨ **Give any switch a daily goal** — e.g. *pool pump at least 4 h/day*
  (runtime) or *5 kWh/day* (energy), set on an EV-charger-style
  dual-handle slider with a min ↔ kWh unit picker. The green *At least*
  handle is the target, the orange *Up to* handle a safety cap (far
  right = no cap ∞). (requested by @alexmc1510)
- ✨ **One 5-step mode per device**: Off · Peak only · Surplus — solar
  only · Surplus + cheap top-up · Surplus + finish by deadline. Solar
  only never draws grid; cheap top-up completes the target in cheap
  tariff windows; finish-by-deadline force-runs in time to meet it.
  Peak protection always outranks the goal.
- ✨ **Stop condition** — end a device's day early when an external
  sensor reaches a value (charge a PHEV on a dumb socket, stop at the
  car's 80 % SOC).
- ✨ **Finish by** deadline per device (default: end of day); progress
  bar on the Control tab; progress survives restarts.
- 🐛 **Registrations now persist** — devices registered via
  `register_surplus_device` used to silently vanish on every restart.
  One call now does everything (defaults to surplus mode, returns a
  response summary); new `unregister_surplus_device` service; explicit
  registrations own their switch (auto-discovery duplicates are
  dropped).
- ✨ **Surplus event for your own automations** —
  `binary_sensor.sem_surplus_available` (debounced: 60 s above the
  threshold → on, 120 s below 80 % of it → off; threshold knob) plus a
  `solar_energy_management_surplus` bus event on transitions. Built for
  peak-only devices that keep their own schedules.
- 🛡️ **Never orphaned ON**: a restart re-owns running surplus devices;
  forces end with their reason (deadline passed target met, tariff left
  the cheap window, day rollover).
- 📖 The Control-tab device card gained a **? help panel** explaining
  every option — modes, priority/shedding order, requires, configure,
  target peak, daily targets — in all 15 languages.

### ☀️ Daily solar — counter-accurate (#556)
- 🐛 **Cloud-polled inverters (Deye Cloud & co.) undercounted daily solar
  ~3×** — the power sensor sits at 0/unavailable between polls. SEM's
  daily solar now reconciles against the inverter's own production
  counters (upward-only; unit-aware; handles counter resets and
  multi-string sums) and credits production while HA was restarting.
  The previously inert *prefer hardware energy* option is the gate.
  (reported by @hrdilshan)
- ✨ **Today's Solar Production KPI** — a prominent hero card at the top
  of the Home tab (large orange kWh + live power chip), ×15 languages.
  (requested by @hrdilshan)

### 🌍 Forecast — localized entity IDs (#562)
- 🐛 **Solcast was never detected on non-English installs** — the
  integration names its entities in your HA language
  (`…_forecast_heute` on German), while SEM looked for the hardcoded
  English IDs. Detection now resolves through the entity registry's
  language-independent IDs, for Solcast and Forecast.Solar alike.
  (reported by @ebnerjoh)

### 🗄️ Storage — no more all-or-nothing (#563)
- 🐛 **One bad value could wipe the whole energy store** — a single
  out-of-range accumulator (e.g. a pre-beta.14 ×1000-inflated lifetime
  counter) discarded ALL daily/monthly/cost data on the upgrade
  restart. Validation now repairs per entry and keeps the rest; the
  daily store (where the real accumulators live) is now validated at
  all. (reported by @ebnerjoh)

### 💰 Costs & grid polish (#557, #555, #560, #561)
- ✨ System Investment Cost accepts direct numeric entry. (requested by @hrdilshan)
- 🩹 Missing optional HACS cards (e.g. `sankey-chart`) show a friendly
  translated install notice instead of a red error banner. (reported by @hrdilshan and @ebnerjoh)
- 🐛 Entity pickers: hot-water accepts switch/input_boolean/water_heater/climate;
  heat-pump relays accept input_boolean bridges (card + config flow). (reported by @covuser)
- 🐛 Grid card "Net" row states its direction: **Net import** / **Net export**, ×15 languages.

Thanks to @alexmc1510, @hrdilshan, @ebnerjoh and @covuser for the reports and ideas! 🙏

# [1.7.4-beta.16] — 04.07.2026

> **Pre-release.** Config-picker fixes, friendly missing-card notice, typed
> investment input, unambiguous Net labels.

### 🛠️ Configuration pickers (#560)
- 🐛 **Hot-water switch (and several other entities) could not be selected** —
  the dashboard Config card's entity pickers passed a broken domain filter
  that excluded *every* entity when no domain was set. The hot-water picker
  now accepts `switch`, `input_boolean`, `water_heater` and `climate`
  entities. (reported by @covuser)
- 🐛 Heat-pump relay 1/2 pickers (Config card **and** the native config flow)
  only accepted `switch` — SG-Ready setups bridged through `input_boolean`
  helpers couldn't be configured. Both now accept `input_boolean` too.

### 🧩 Dashboard — friendly missing-card notice (#555, #558)
- 🩹 A missing optional HACS card (e.g. `sankey-chart`) no longer shows a red
  "Configuration Error" banner — a new wrapper renders a friendly, translated
  notice naming the missing card and how to install it, and renders the real
  card as soon as it's available. (reported by @hrdilshan and @ebnerjoh)

### 💰 Costs — typed System Investment Cost (#557)
- ✨ The System Investment Cost stepper now accepts **direct numeric entry**
  (keyboard input next to the ± buttons), and the accepted range is wide
  enough for any real installation. (requested by @hrdilshan)

### ☀️ Forecast — Solcast no longer misses the bus (#562)
- 🐛 **SEM latched onto Forecast.Solar even when Solcast was installed** — if
  the Solcast integration finished loading after SEM's first source
  detection, the cache stuck until the next restart. SEM now upgrades to
  Solcast (its preferred source) as soon as the Solcast entities appear.
  (reported by @ebnerjoh)

### 📊 Grid card — Net direction spelled out (#561 follow-up)
- 🐛 The grid card's "Net" row showed `|import − export|` with the direction
  conveyed only by color. The label now states it: **Net import** /
  **Net export** — translated in all 15 languages. (follow-up to @ebnerjoh's
  report)

# [1.7.4-beta.15] — 04.07.2026

> **Pre-release.** Deye grid direction out-of-the-box.

### ⚡ Grid — Deye brand sign seed (#554)
- 🎯 **Deye installs (hass-deyecloud) get the correct grid import/export
  direction from the first cycle** — the platform is now in SEM's brand sign
  map (`totalgridpower` reports +=import, verified from reporter diagnostics),
  so no Fix-grid-sign button or detection wait is needed. (thanks @hrdilshan)

# [1.7.4-beta.14] — 04.07.2026

> **Pre-release.** Feedback-round fixes: Wh counters + consistent Net display.

### 🔋 Energy statistics — unit-aware hardware counters (#551)
- 🐛 **Fronius (and any Wh-reporting) lifetime counters inflated the lifetime
  statistics ×1000** — a 2-day-old install showed 21,350 battery "cycles" and
  a health score pinned at 70% (real value: ~21). Counter reads are now
  unit-aware (Wh/kWh/MWh), covering lifetime seeding and the EV daily-energy
  reconciliation. (reported by @ebnerjoh)
- 🩹 **Self-healing**: installs that already seeded the inflated values are
  detected and re-seeded from the corrected counters automatically on the
  first restart after updating — no manual cleanup.

### 💰 Costs — consistent Net framing (#554)
- 🐛 The Costs hero said "+1.71 net saving" while the Today/Month/Year rows
  printed "−1.71" — the same cost-signed value in two contradictory framings.
  All Costs surfaces now use the savings-positive framing ('+' and green when
  earning; plain pink when a net cost). The math was always consistent:
  Net = import cost − export revenue. (reported by @hrdilshan)

# [1.7.4-beta.13] — 04.07.2026

> **Pre-release.** Observability + contract-test pass (#553 wrap-up).

### 🔎 Diagnostics & guardrails
- 🧭 The `diagnose` action's `ev_actuation` block now reports
  **`idle_guard_armed`** — SEM's belief that the KEBA runaway-cap energy
  target is armed (stop arms, start releases). One service call to triage.
- 🧪 **Silent-no-op contract extended to switches and selects**: the wiring
  test that already guards number knobs now covers switch/select entities —
  including a source-scan that fails CI when a new dynamic per-charger /
  per-battery key isn't covered. (No dead knobs found today.)
- 📖 Audit playbook: hardware-facing values require one live device
  round-trip before tagging (the 1 Wh-vs-1 kWh KEBA lesson).

# [1.7.4-beta.12] — 03.07.2026

> **Pre-release.** KEBA guard correction — beta.11's tagged build carried a
> silent no-op guard value.

### 🔌 KEBA — runaway cap corrected (#553)
- 🐛 beta.11 tagged the guard at ~1 Wh, which the KEBA library **rejects**
  (minimum 1 kWh; the error is swallowed as a log line) — caught by a live
  layer-check on a real P30. The guard now arms **1 kWh**: a runaway cap that
  bounds a firmware auto-start session when SEM is down or restarting
  (previously unbounded). Per-retry policing while SEM is alive is #552's job
  and unchanged. Authorization-based approaches are explicitly out of scope.

# [1.7.4-beta.11] — 03.07.2026

> **Pre-release.** Improvement batch (#553): KEBA idle-guard, full grid schema, cleanup.

### 🔌 KEBA — box-level runaway cap (#315)
- 🛡️ **A KEBA auto-start that SEM isn't policing now stops itself at the box
  after 1 kWh.** The firmware retries a stored session every ~10 min when a
  hungry car is plugged; SEM kills each within a cycle (#552) — this guard
  bounds the damage when SEM is down or restarting (previously unbounded).
  SEM arms a 1 kWh session-energy target on every stop and releases it on
  every start. (1 kWh is the KEBA library minimum — live-verified on the
  real P30; the originally announced ~1 Wh value is rejected by the library.)

### ⚡ Grid — full Energy-Dashboard schema (#551 sibling)
- 🐛 Grid sources support the same `power_config` modes as batteries; the
  Two-sensor mode is now consumed correctly as import/export split
  (review-caught: the first draft read the import side as a combined sensor —
  permanent phantom export). Inverted combined sensors defer to the #461
  sign-detection stack.
- 🔋 **Multiple two-sensor batteries** are now summed per-battery (previously
  only the first pair fed real-time power).

### 🧹 Cleanup & clarity
- 🚀 A draw found at boot while SEM wants idle is disabled on the first cycle
  (no wind-down grace for a session SEM never commanded).
- 🏷️ **"Assist Max" → "Battery → EV assist limit"**, **"Max discharge power" →
  "Battery total discharge limit"** — new help text explains the containment
  (assist is a sub-limit of the total), 15 languages.
- 🪦 Retired: the write-only "Vehicle Start Amps" knob (the start-kick
  auto-discovers the latch current since beta.57), three dead legacy consts
  maps, and the unused mid-session energy-target updater.

# [1.7.4-beta.10] — 03.07.2026

> **Pre-release.** Battery readings for every Energy-Dashboard battery mode.

### 🔋 Battery — full Energy-Dashboard schema support (#551)
- 🐛 **Batteries configured with HA's "Two sensors" power mode showed
  "sensor unavailable" and SOC 0%** (reported with a Fronius Verto 15.0 Plus).
  SEM only read the top-level `stat_rate` — which HA writes only for the
  Standard mode — and never read the dialog's SOC field at all.
- ✅ SEM now parses the complete battery `power_config` (**Standard /
  Inverted / Two sensors**) and the explicit **`stat_soc`** state-of-charge
  entity: real-time power is computed as charge − discharge for two-sensor
  setups, inverted sensors are flipped on read, and SOC comes deterministically
  from what you configured in HA — the auto-detect heuristics remain only as
  fallback. No SEM-side reconfiguration needed. (reported by @ebnerjoh)
- 🧪 Live-verified with the reporter's exact configuration shape; 9 new
  regression tests including the full Fronius pipeline; 4016 tests green.

# [1.7.4-beta.9] — 02.07.2026

> **Pre-release.** Root-cause fix: SEM never starts or holds a charge it didn't command.

### 🔋 EV charging — session ownership (#552)
- 🐛 **`solar_only` no longer drains the home battery at night.** When a KEBA
  auto-started at its stored setpoint (car retry, #315), the charge-stability
  deficit-hold engaged for the un-owned draw — rewriting decide()'s correct
  IDLE into a 10 A charge command and formally STARTing a session nobody
  decided, pulling ~4.9 kW from the battery in 90 s–4 min bursts every ~10
  minutes after sunset (~2 kWh per evening, observed on PROD 01.+02.07).
- 🛡️ **Fix = session ownership**: the stability layer only bridges/holds
  sessions it started itself, and the reconciler's idle grace applies only
  while winding down SEM's own stop — a draw appearing after idle has settled
  is disabled immediately, every cycle it persists.
- ✅ **Live-verified on PROD**: 30-min watch, two box auto-starts on the old
  cadence, both killed in ≤10 s with zero SEM starts (was 90–240 s each).
  ruflo-reviewed (0 blocker/0 high); 10 new regression tests; 4007 tests green.

# [1.7.4-beta.8] — 02.07.2026

> **Pre-release.** Documentation overhaul — no code changes.

### 📚 Documentation
- 🏬 **README reworked for the HACS default store** — the competitor comparison
  is gone (SEM speaks for itself), install instructions reflect the default
  store with an "Open in HACS" button.
- 📸 **All 8 dashboard tab screenshots recaptured** chrome-free (no side panel,
  no header) — including the previously missing **Configuration tab** shot.
- 🧹 **fold-entity-row retired from the required HACS cards** (zero uses since
  the onboarding banner became a bundled card) — required set is now card-mod,
  mushroom, apexcharts-card, sankey-chart.
- 🛠️ **Repo-wide accuracy pass, every fix verified against code**: the KEBA
  failsafe doc had its default inverted (managed-neutralize IS the default);
  retired battery knobs removed from the User Guide; EV-intelligence sensor
  list rewritten to the real per-charger entities; stale entity names,
  defaults, ADR field names and broken links fixed across 14 files.

# [1.7.4-beta.7] — 01.07.2026

> **Pre-release.** Dashboard config reachability + dormant arbitrage hardening.

### ⚙️ Configuration on the dashboard (#550)
- 🔋 **Battery SOC sensor picker** on the Config tab — if SEM didn't auto-detect
  your battery state-of-charge (e.g. Deye + Seplos: SOC is in the Energy
  Dashboard but shows unavailable), you can now point SEM at the SOC entity
  directly. No device-class filter, so any sensor is selectable. (reported by @praun)
- 🔌 **Heat-pump temperature-sensor picker** and **Invert SG-Ready toggle** added
  to the Config tab — both were structural settings with no UI (the toggle was
  reachable only via the native options flow).
- 🧭 **Structural toggles now batch through the Apply bar** like the entity
  pickers, so flipping one no longer fires its own reload and discards a staged
  edit. Full 15-language labels + help. ruflo-reviewed.

### 🔧 Internal — battery→grid arbitrage hardening (#533, still DEACTIVATED)
- 🛡️ The dormant arbitrage path was hardened ahead of a future v1.7.4 activation
  (view-plumbed market signals, a peak-aware export cap, and a clean cross-brand
  `STOP_FORCE_DISCHARGE` stop). **No behaviour change** — three gates keep it off
  (`_any_allow_arb=False`, migration v14 forces the toggle off, `allow_arbitrage`
  out of the selector). ruflo-reviewed; re-enable checklist documented.

# [1.7.4-beta.6] — 30.06.2026

> **Pre-release.** Completes the dashboard-first configuration work (#528).

### ⚙️ Configuration on the dashboard — completion (#528)
- 🔋 **Battery discharge-protection settings** now on the Config tab (Battery
  zones): protection toggle, max-discharge-power knob, and the discharge-limit
  entity picker — no more options-flow trip for these.
- 🔌 **Add / remove EV chargers from the dashboard.** A "+ Add charger" button
  appends a new charger (then wire it with the per-charger pickers), and each
  charger has a "✕" with an inline confirm (new `remove_charger` service,
  preserves siblings). The main reason to open the native flow is gone.
- 🧭 The native options flow stays as a headless fallback and now **points to
  the dashboard Config tab** (translated, 15 languages).
- ruflo-reviewed; full suite green; add/remove live-verified on HA-TEST.

# [1.7.4-beta.5] — 30.06.2026

> **Pre-release.** Currency fix for high-denomination currencies.

### 💱 Tariff — currency-agnostic price bounds (#549)
- 🐛 **Price entities were unusable for high-denomination currencies.** With HA
  currency set to LKR (or IDR/VND/JPY/…), the import/export rate, cheap/expensive
  threshold and demand-charge entities showed the right unit (`LKR/kWh`) but kept
  EUR/CHF-scale caps (export max 0.5), so a real 22 LKR/kWh tariff couldn't be
  entered. The ceilings are now currency-agnostic (rates/thresholds 10000,
  demand 100000) across all three surfaces — number entities, the Config-tab
  inputs, and the OptionsFlow selectors. Fine steps kept, so decimal currencies
  (CHF/EUR) are unchanged. (by @hrdilshan in #549)

# [1.7.4-beta.4] — 30.06.2026

> **Pre-release.** Dashboard-first configuration — the Config tab, made colorful and easy (#528).

### ⚙️ Configuration on the dashboard (#528)
- 🎨 **The Config tab is now the home for post-setup configuration, in the colorful
  battery-card design language** — accent sliders with value chips, an SOC-zone
  strip, and per-section accent theming across every section (no more flat
  stepper rows). You rarely need HA's Settings → Devices → Configure flow.
- 🔌 **Batched Apply for entity wiring** — entity pickers that reload the entry
  now stage their edits and commit in **one** reload via a sticky Apply bar,
  instead of a reload per field. Tunables still save live.
- 🧭 **First-run completeness guide** — the Setup overview shows a progress bar +
  "Set up →" chips that jump to the unconfigured section, and recedes to a green
  "All set up" when done.
- 🌍 Full **15-language** translations for the new UI; added the missing
  hot-water power-sensor picker. ruflo-reviewed.

# [1.7.4-beta.3] — 28.06.2026

> **Pre-release.** Adds per-charger actuation diagnostics for the "SEM says stop but the box keeps charging" class (#548).

### 🔌 EV — actuation diagnostics + stop-not-taking signal (#548)
- 🔍 **The Diagnose button now shows the actuation truth.** A new per-charger
  `ev_actuation` block reports the adapter, the status sensor's raw value +
  classification, the enable-switch entity + state, whether SEM can drive it
  (`enable_state`), the `actual_charging`/`is_self_charging` verdicts, the
  believed setpoint vs live power, and the reconciler's last desired state +
  actions + a `stop_commanded_while_drawing` counter. One screenshot now tells
  "SEM never issued the stop" apart from "SEM issued it but the box ignored it"
  — no more multi-round triage.
- ⚠️ The reconciler now **logs a warning** ("commanded STOP N× but charger still
  drawing") when a stop isn't taking, so an ignored stop is no longer silent.
- Note: the decision/stop arc itself is verified sound — a max-SOC ceiling stops
  promptly on a responsive charger (HA-TEST mock: 6 A → 0 A in ~20 s). When a
  real charger keeps drawing, the cause is downstream of SEM (HA↔charger link or
  the charger ignoring the stop), which this diagnostic now pinpoints.

# [1.7.4-beta.2] — 27.06.2026

> **Pre-release.** Generalises the Wallbox status-enum fix to every charger brand.

### 🔌 EV — cross-brand status-enum classifier (#548)
- ✨ **Every charger brand now uses its STATUS enum (authoritative) instead of the
  cloud-lagged power reading** to decide "is it charging?" and "can SEM stop it?".
  The Wallbox #548 fix is generalised into one shared classifier
  (`coordinator/charger_adapters/status_enum.py`) mapping each brand's real
  HA-integration status strings — Easee, Zaptec, go-e, Ohme, OCPP, Alfen,
  Heidelberg, Wallbox — to charging / not_charging / locked. `GenericAdapter`
  reads it over the already-configured status sensor; KEBA stays power-based.
  Strictly additive: no status sensor / unrecognised string → unchanged
  power-based behaviour. App/cloud-locked states (Eco-Smart, Easee smart-start,
  Ohme pending-approval, Alfen in-operative) now surface "can't stop — leave
  eco-smart" instead of spinning silently.
- 📝 `docs/MULTI_CHARGER.md` gains a per-brand reference table (verified against
  each HA integration source) + actuation caveats (Easee/Zaptec/go-e set-0≠stop;
  Ohme is on/off only; Heidelberg reg-261 reboot revert).
- ✅ Verified: per-brand classifier tests, every-mode KEBA parity, control-pattern
  coverage, and a live HA-TEST mock walk (Zaptec/Alfen charging strings detected
  over 0 W; Eco-Smart lock surfaced). Full suite 3986 green.

# [1.7.4-beta.1] — 27.06.2026

> **Pre-release.** Opens the 1.7.4 line. Headline: Wallbox now stops reliably in
> OFF mode (and every other mode reacts exactly as KEBA does). Battery→grid
> arbitrage remains **deactivated** (still tracked for 1.7.4 stable in #533).

### 🔌 EV — Wallbox status-enum adapter (#548)
- 🐛 **Wallbox kept charging in OFF mode.** The reconciler judged "still drawing?"
  from the power reading, but Wallbox power arrives over a ~90 s cloud poll — so
  OFF mode read "already stopped" on the first cycle and quit re-issuing the stop
  while the box kept charging. The firmware **status enum** is now authoritative
  for the Wallbox (evcc-connector concept, no cloud transport needed):
  `actual_charging` trusts `Charging`/`Paused`/… over the lagging power, and
  app-locked states (Eco-Smart / Scheduled / Power-Sharing / Locked) surface a
  clear "can't stop — leave eco-smart" repair instead of spinning silently.
  Strictly additive: no status sensor ⇒ unchanged power-based behaviour; KEBA
  untouched.
- ✅ **Parity:** all four charge modes (off / solar_only / min_plus_solar /
  always_max) now react on the Wallbox exactly as they do on KEBA — verified by
  `tests/test_548_mode_parity.py` and a live HA-TEST mock-Wallbox walk.
- 📝 `docs/MULTI_CHARGER.md` documents the status-enum road for the next brands
  to migrate (Easee / go-e / OCPP / Ohme / Alfen).

# [1.7.3] — 27.06.2026

> **Stable release.** Consolidates the 1.7.3 beta line (beta.1 → beta.65, detailed
> below) plus the final hardening below. Headline: a big EV-charging reliability
> pass (steady offer, clean stops, max-SOC ceiling, battery-assist), the
> single-source EV decision architecture, multi-battery + per-battery modes,
> grid-sign auto-detection, the audit-telemetry program, and a large census /
> dead-code cleanup. Battery→grid arbitrage remains **deactivated** (tracked for
> v1.7.4 in #533).

### 🔌 EV — single-source stability bridge (#461)
- 🐛 **The EV could grid-hold at low battery SoC and never settle.** The anti-flap
  "disable bridge" re-derived solar/surplus/SoC/tariff and held minimum current
  after `decide()` had already structurally idled, then re-engaged in a loop —
  importing grid indefinitely (PROD-confirmed via the strategy-sensor history).
  `decide()` is now the single source of truth: it classifies each IDLE as
  transient (hold) vs structural (stop) on `ChargerDecision.bridgeable`, and the
  stability layer simply honours the flag — no re-derivation — plus a durable
  stop and a post-stop settle so a winding-down car can't re-open the hold.
  (by @guidoeberle in #461)

### ⚙️ Config — knobs apply without a reload (#547)
- ✨ **Changing a setting now takes effect live.** Scalars cached on a controller
  at construction (regulation offset, heat-pump / hot-water tunables, per-charger
  EV priority + min/max current + shed priority, tariff rates) used to need a full
  integration reload. `refresh_runtime_config()` now pushes them into the live
  controllers on every config change — a refresh, not a rebuild, so timers, cost
  accumulators and smoothing windows are preserved. (by @guidoeberle in #547)

### 🔌 EV / Load management — single-writer peak control (#461)
- 🐛 **Load management could fight the EV controller (or silently fail to shed it).**
  The EV is now removed from load-management's per-cycle device shedding entirely:
  daytime EV charging is solar-driven (no grid peak) and the night grid top-up is
  already peak-managed by the night planner — both through the single
  `decide()`/reconciler writer. The old side-channel (`number.set_value 0` /
  `keba.set_current 0`) fought the reconciler heartbeat on KEBA and mis-read
  number-entity Wallbox chargers, so it could only flap or fail. (by @guidoeberle in #461)

# [1.7.3-beta.65] — 26.06.2026

> Hardens the battery-protection limit against an EV-ramp sensor-lag spike.

### 🔋 Battery — spike-proof the discharge-protection limit (#536)
- 🐛 **A fast EV load ramp could briefly over-allow battery discharge.** When the car ramps hard (e.g. `always_max` to 10 kW), the grid meter registers the import a cycle before the KEBA `ev_power` sensor reports the draw, so the energy-balance `home_consumption_power` transiently inflates by ~the car's draw (seen on PROD: spiked to 9213 W). Since the discharge-protection clamp limits the battery to the home load, that spike briefly raised the limit and let the inverter feed a little battery into the car below the buffer. `_smooth_home_consumption` now has a **symmetric upward-spike guard** (it already held the *dip* direction): a one-cycle jump above the last value + 2 kW is treated as the EV/grid sensor lag and the last good value is held for up to 2 cycles; a genuine, persistent rise (an appliance) is accepted once the short window expires. (by @guidoeberle in #536)

# [1.7.3-beta.64] — 26.06.2026

> The battery now stops feeding the EV at the buffer SoC floor — cleanly.

### 🔋 Battery — enforce the buffer SoC floor (#536 follow-up to #545)
- 🐛 **The battery drained into the EV below the buffer SoC.** With #545's aggressive assist, a high house load kept surplus just above the gate while SoC fell below the buffer (PROD: 83% with an 85% buffer), and the discharge clamp — which keyed only on `surplus < gate`, never on SoC — let the inverter keep feeding the car well below the user's reserve. The clamp now also fires when **`SoC < buffer_soc`**, so below the buffer the battery is reserved for the house **in every zone, regardless of surplus**. Above the buffer the #545 assist is unchanged. (A zone-by-zone audit confirmed the EV engine was already correct in all four zones — the gap was isolated to the battery clamp.) (by @guidoeberle in #536)
- 🐛 **The EV stop-bridge never fired with a bursty car.** The disable-bridge stop timer only accumulated while the car drew continuously, and the draw-latch was wiped every deficit cycle — so a Renault Zoe blipping between pulses reset the timer each cycle (170→99→20 s, never reaching 180 s) and the contactor never opened. The latch now persists through the bridge (refreshed on each real draw, cleared only on a genuine stop), so the car stops cleanly instead of grid-charging indefinitely. (by @guidoeberle in #536)

# [1.7.3-beta.63] — 26.06.2026

> Cleanup: retire the EV-charging diagnostic instrumentation now that #545/#546 are fixed.

### 🧹 Instrumentation retired (#545 / #546)
- 🧹 The `EV-OFFER-PROBE` reconciler log is **downgraded to DEBUG** (and gated on DEBUG, so it does no per-cycle work on a normal INFO PROD) — it served its purpose pinning the KEBA 6↔9 A flap (#546, fixed). Re-enable with debug logging if a future flap needs re-diagnosing.
- 🗑️ Removed the observe-only **`sensor.sem_diag_ev_assist_headroom`** diagnostic and its per-cycle computation — instrumentation for the #545 chicken-and-egg, now fixed and closed. (Swept the sensor description + population + strings/15 translations.)

# [1.7.3-beta.62] — 26.06.2026

> The home battery now empties into the EV at high SoC instead of sitting idle.

### 🔋 EV — max out the battery into the car (#545)
- ⚡ **"Max out till self-consumption":** when the home battery is in the assist band (SoC ≥ the Buffer SoC) and there's real solar surplus past the Solar Gate, SEM now offers the **full** battery-assist potential — it raises the offered amps so the inverter discharges the battery **into the car, down to the Buffer SoC** (the self-consumption reserve floor), instead of only topping the car up to the charger minimum. This fixes the chicken-and-egg where a **full battery sat idle while the EV grid-charged** (observed live: at 100% SoC, SEM offered only ~8 A, the car drew ~3 kW from solar, the battery never assisted, and a grid night-charge was still needed). The assist self-tapers as SoC falls toward the Buffer and is off-limits below it, so the battery is never drained past the floor. Solar-gated; pure amps — SEM commands no battery directly, the inverter's self-consumption does the discharge. Aligned across both budget layers (`decide.battery_assist_budget_w` + the canonical `calculate_canonical_ev_budget`) so they agree (#282). Docs updated (EV_CHARGING_LOGIC, ARCHITECTURE). (by @guidoeberle in #545)

# [1.7.3-beta.61] — 26.06.2026

> Fixes EV charging running past the configured max SOC during solar charging.

### 🔌 EV — stop at max SOC (#548)
- 🐛 **The EV charged past its configured max SOC** in solar/surplus charging (reported by @RienduPre, Wallbox Pulsar Plus). The max-SOC ceiling (`soc_limit_active`) only reached the retired ChargingStateMachine (→ `SOLAR_TARGET_REACHED`), and that state was then **overwritten by the per-charger decision** — while the `decide()` day path has no max-SOC check of its own, charging whenever surplus ≥ min. So nothing actually stopped the charge at the ceiling. Now the ceiling is plumbed into `ChargerView.soc_ceiling_reached` (from the value the coordinator already computes) and **guarded in `decide()` before mode dispatch**, so **every** mode (`solar_only`/`min_plus_solar`/`always_max`/`solar_plus_cheap`) stops at the max SOC. kWh-target users are unaffected (their max is effectively unlimited). The stop now reads as **"Target reached"**. (by @guidoeberle in #548)

# [1.7.3-beta.60] — 26.06.2026

> Census cleanup, continued: removed dead published sensors and added a CI guard
> so the dead-surface class can't regrow. Each removal re-verified live (3 of 19
> candidates turned out to have a consumer and were kept).

### 🧹 Dead sensors removed (#544)
- 🗑️ **Removed 16 orphan sensors** — published, enabled-by-default, but read by no card, generator, or decision (pure entity clutter): the fleet EV-intelligence cluster (`ev_taper_ratio`, `ev_taper_minutes_to_full`, `ev_estimated_soc`, `ev_last_full_charge`, `ev_energy_since_full`, `ev_predicted_daily_consumption`, `ev_battery_health`), the forecast-accuracy cluster (`forecast_accuracy_today`, `forecast_accuracy_7d`, `forecast_deviation_kwh`, `forecast_corrected_tomorrow`, `forecast_power_now_w`, `forecast_power_next_hour_w`), and the predictor outputs (`predicted_consumption_next_hour`, `predicted_consumption_today_kwh`, `predicted_solar_next_hour`). Swept descriptions + population + metadata across `strings.json`/`icons.json`/15 translations. **Breaking** for any custom dashboard/automation that referenced these. Kept (verified live): `ev_taper_trend` (diagnostic), `forecast_correction_factor` & `forecast_history_days` (read by the dampening/correction sensor attributes). (by @guidoeberle in #544)

### 🔒 Census cleanup closed (#543)
- ✅ With #544 done, the census cleanup (#543) is complete — the knob-reader contract lint (`tests/test_knob_wiring.py`) was already in place from the 2026-06-25 chunk and confirms all 26 NUMBER knobs are wired. The one remaining item (knobs read only at controller construction don't apply until reload) is a behavioral fix, split to #547.

# [1.7.3-beta.59] — 26.06.2026

> EV-decision coherence: the overnight battery-drain root cause is fixed, and a
> verify-first audit retired/clarified the confusing knobs around it. Live-confirmed
> on PROD (KEBA P30 + Renault Zoe) across all four charging modes.

### 🔋 Battery — overnight drain root cause (#536)
- 🐛 **The home battery drained overnight to feed the EV** (PROD 93→41 %). The discharge-protection clamp gated on the *instantaneous* draw flag (`ev_charging`), which a bursty car (Renault Zoe) toggles on/off every few seconds — so the clamp dropped in the gaps, the battery discharged freely, and that energy fed the next pull. The clamp now gates on **`ev_connected`** (vehicle plugged in), so it **holds steady** through the car's pulses. Live-verified: `battery→ev = 0 W` in every solar mode all afternoon. (by @guidoeberle in #536)

### 🧹 Config — verify-first knob cleanup (#536)
- 🧹 **Removed three dead/redundant battery knobs** after auditing each live (two of the original four turned out to be live and were handled, not blindly cut): `battery_minimum_soc` (labelled "hard stop" but never gated discharge — its only live use, the empty-ETA, now references the real floor `battery_priority_soc`), `battery_assist_floor_soc` (shadowed by `buffer_soc` — folded in as the single assist floor), and the comment-only `battery_hold_solar_ev`. (by @guidoeberle in #536)
- 🐛 **Fixed the `minimum_solar_power` default inconsistency** — a legacy config missing the key silently used 200 W while a fresh install seeded 1000 W; the fallback now matches the seeded default. (by @guidoeberle in #536)
- 📝 **Corrected the misleading "Surplus floor" help text** — `minimum_solar_power` gates **raw PV production** ("is the sun up"), distinct from `battery_assist_min_surplus` (export surplus); clarified in English + 15 translations. The two were *not* collapsed — they measure different quantities and both feed the #461 deep-deficit logic. (by @guidoeberle in #536)

### 🗑️ Internal — legacy retirement, stage 1 (#536)
- 🗑️ Removed the deprecated proportional `FlowCalculator.calculate_energy_flows` (zero production callers since #282; the timing-aware `integrate_energy_flows` is canonical). (by @guidoeberle in #536)

**Thanks** to @guidoeberle for the PROD live-testing across all four charging modes.

# [1.7.3-beta.58] — 26.06.2026

> Steady EV charging — live-confirmed on a real KEBA P30 + Renault Zoe: the
> offered current went from **366 changes/evening** (6↔9 A sawtooth, car in
> standby) to **0 changes in 25 min** (rock-steady 8 A, car drawing ~3.1 kW).

### 🔌 EV charging — steady offer (neutralize the failsafe, then track like evcc)
- 🐛 **The offered current flapped 6↔9 A every few seconds**, so a steady-needing car (Renault Zoe) sat in standby. Root cause: the KEBA reverts to its built-in **6 A failsafe** between SEM's writes and SEM re-wrote 9 A every 5 s — a sawtooth the car can't charge through. Live testing on a real P30 showed the failsafe **can't be disabled** over UDP (the box keeps it — likely a safety design). So SEM now **neutralizes** it: it arms a **long (10-min) non-tripping, persisted** failsafe with the fallback at your **charging floor** — it overwrites the box's short built-in one, the per-cycle writes keep it from ever tripping, and a genuine controller-death lands the car on the floor (not 6 A). No more flap. (#546)
- ⚡ With the offer steady, the current tracks surplus **evcc-style** — a ≈30 s cadence with a 2 A deadband (not a multi-minute freeze), with evcc-aligned **1 min start / 3 min stop** delays (disable delay 300→180 s). (#546)
- ⚙️ `keba_arm_failsafe` (default **on** = managed-neutralize). Set it **off** for boxes that *can* disable the failsafe at the charger (evcc-style); SEM then leaves it alone and raises a **Repair** (Settings → Repairs) guiding you to disable it, with a step-by-step link. (#546)
- 🔭 The `EV-OFFER-PROBE` diagnostic now reads the **live** offered-current sensor (`ev_current_sensor`) instead of the static config cap, so it can actually show hardware drift. (#546)

### 🛡️ Observer mode / wiring
- 🐛 **The observer-mode switch was a silent no-op.** Its entity-id constant held the `domain.object` form and the coordinator re-prefixed it (`f"switch.{…}"`) into a dead three-segment id, so the lookup always returned `None` and toggling the switch never made SEM hands-off. On a test bench that shares the *same physical* inverter/battery as production, this meant the test instance kept driving the real hardware while the switch showed "on". Fixed the lookup, made the switch push its state straight onto the coordinator, and guarded the per-cycle pull so a transient `unavailable` switch state can't clobber it back on. Two follow-on bugs surfaced once the switch finally engaged — most notably the read-only setpoint-zeroing iterated the multi-charger **dict keys** (crashing the whole update cycle) — and are fixed. Contract tests lock the class: every entity-id constant must be a valid 2-segment id, the coordinator must not re-prefix one, and observer mode must hold across transient unavailability. (#542)

### 💰 Costs
- 🐛 **Monthly and Yearly costs were identical.** The yearly seeding backfilled the year's *energy* from the recorder but never the *cost* accumulators, so yearly cost only held the live (this-month) portion and equalled the monthly figure. Now the yearly cost is seeded from the seeded yearly energy × the average rate — and an already-seeded install (where only the cost was missing) is backfilled too. The pre-tracking backfill is an **estimate** on a dynamic tariff (the recorder has historical energy, not historical hourly prices); the live portion stays exact. Confirmed the live per-cycle cost is already tariff-correct (static/dynamic/calendar all priced at the current rate each cycle). (#536)

# [1.7.3-beta.57] — 25.06.2026

> Stable (1.7.3) stays **on hold** — the EV-charging rework below needs PROD soak.

### 🔌 EV charging — steady, unified, honest
- 🚗 **Rock-steady charging.** A Renault Zoe R that oscillated 5 kW↔0 now holds a flat 5 kW. Four root causes: single-charger **draw-detection** bug (`build_view` now falls back to the fleet `ev_power`, so SEM actually sees the car drawing); **latch hysteresis** (hold the current through transient 0 W dips instead of re-starting); **steadier guards** (90 s change interval / 2 A deadband / 5-cycle median); and the config insight that this Zoe's *sustain* floor is **~10 A, not 6** (it drops at 6 A). The oscillation was SEM *changing* the current, not the level. (#536)
- ☀️🌙 **Day + night unified.** One charging behaviour (latch → hold → auto-escalate) across solar and night, with a **bounded** start-escalation (caps at `max(target, 10 A)`, gives up after 90 s on a refusing car — no more climbing to 32 A). (#536)
- 🔢 **Night-target counter fix.** The planner over-charged past the target after restarts (it used a restart-volatile per-charger integrator); it now uses the persisted `daily_ev` — the figure the dashboard shows. (#536)
- 🛑 **Observer mode now hands-off for the EV too.** Zeroes the published commanded current so an external bridge automation or a second SEM instance can't drive the charger while observing. (#536)

### 📊 Dashboard
- ⚡ EV card shows the **commanded current** next to CHARGING (e.g. `CHARGING (8 A)`) — what SEM transmitted vs the car's real draw. (#536)
- 🩹 Header and EV-card power/state no longer contradict (both derive from the same per-charger power). (#536)

### 🧹 Cleanup
- Removed dead Advanced settings `current_delta` / `power_delta` / `soc_delta` and the dead `ev_stall_cooldown` entity, plus the orphaned solar-stability layer. (#536)

> **Known / open:** a self-starting KEBA still auto-tops a not-full car past the kWh target (proper fix: `keba.set_energy` so the box enforces its own stop); a test instance must never point at production hardware.

# [1.7.3] — STABLE

> Rolls up the 1.7.3 beta line (beta.2 → beta.56 + stable prep). The dated
> `beta.*` sections below are the detailed per-build history; this is the headline
> summary of what changed since **1.7.2**. The biggest themes: EV charging is
> reliable in every mode, the home battery is protected from feeding the car
> without sun, and multi-battery + grid-sign + dashboard all got a major pass.

## ⚡ EV charging — rock-solid in every mode
- **Charger state reconciler (#392).** The per-cycle imperative actuator (which
  spammed `keba.disable` 391× and dropped KEBA to 6 A) is replaced by a
  desired-vs-observed reconciler: it issues the *minimum* commands to converge and
  then leaves the charger alone. Idempotent idle, heartbeat re-writes, failsafe
  armed once per session.
- **Enable-switch reconciliation + backoff (#536).** For switch-driven chargers
  (Wallbox etc.) SEM reconciles the enable switch and backs off (stops fighting +
  surfaces a repair) if something keeps toggling it.
- **No more expensive-grid / dead-solar charging (#461, #524).** The EV no longer
  drains the battery to hold a dead solar session, and stops pulling from grid after
  a cheap window ends.
- **Charge modes:** `solar_only`, `min_plus_solar`, `solar_plus_cheap`,
  `always_max`, `off` — each with a one-line dashboard hint.
- **EV target type:** daily **kWh** target or **vehicle SOC %** (when a vehicle SOC
  sensor is configured). Per-vehicle minimum current (#440), independent **surplus
  vs shed** priority per charger (#470).

## 🔋 Battery protection & control
- **Solar Gate (#537).** The home battery only assists the EV when there's real
  solar surplus ≥ a configurable gate (default **1200 W**) — in *any* mode. Set it
  to **0 W** to allow battery support everywhere, including overnight. Fixes the
  overnight battery-drain-into-the-car class of bug.
- **Multi-battery control + per-battery modes (#523).** Per-battery control entities
  and five modes — `auto`, `self-consumption`, `force-charge`, `force-discharge`,
  `off` — plus zero-config Huawei forcible discharge and a corrected SG-Ready relay
  map for heat pumps.
- **Idempotent Huawei discharge-limit write (#538).** Stopped re-writing the
  unchanged discharge limit every cycle, which had been flooding the serial Modbus.
- **Battery → grid export arbitrage (#523)** shipped in beta but is **deactivated in
  this stable** pending more soak (#533, re-enable targeted v1.7.4).

## 🧭 Grid sign, heat pump, tariffs
- **Robust grid-sign autodetection + one-tap fix (#461).** Solar-anchored detector
  with a `Fix grid sign` / `Reset` button and a `flip_grid_sign` service; locks
  survive restarts (#476).
- **Heat pump / hot water (#508).** Surplus activation fires, boosts on the *true*
  house surplus, stands down under peak; relay-failure safety.
- **Tibber Grid Reward price arrays (#491)** + forecast dampening with the correct
  sun window (#416).

## 🖥️ Dashboard & i18n
- **Solar Gate** stepper, per-charger **plan strip**, price card, config-card
  cleanups; system-diagram and 7-day-chart fixes.
- **Time labels render in HA's home timezone**, DST-aware, not the viewer's browser
  (#539).
- **Time charts roll the day boundary** (#541) — a long-open app no longer shows
  *yesterday's* data in *today's* chart; the relative window auto-refreshes on a
  timer and on app resume / tab focus.
- **EV Power chart no longer magnifies standby noise** (#541) — a plugged-in idle
  car's ~130 W standby used to auto-scale to fill the whole chart and read like a
  real charge; the axis now has a 2 kW floor so standby renders flat near zero while
  real charges still scale up.
- **Full 15-locale dashboard translations** — every runtime card string is now
  translated (previously ~35 keys fell back to English outside en/de/nl), guarded by
  a new parity test.

## 🔍 Stability & review
- Pre-stable review batches (#485, #531, #535) — forced-charge restored, per-battery
  edge cases, robustness; cold-start/restart hardening (#532). Final ruflo pass:
  today-plan HA-tz day classification, chart tz try/catch, `decide_battery` /
  `#538` comments, and a default-gate test.

# [1.7.3-beta.56] - 23.06.2026

## 🕐 Time labels show HA's timezone, not the browser's (#539)

Every time label on the dashboard rendered in the **viewer's browser timezone**.
A browser/OS stuck on standard time (CET) showed summer-time data **one hour
early** (a 12:00 CEST chart bucket displayed as 11:00). Fixed across the board —
all now format via HA's configured home timezone (`hass.config.time_zone`, IANA
zone → DST-aware), correct regardless of the viewing device. Display-only; the
underlying data timestamps were already right.

- **Time-series charts** (`sem-chart-card`: EV power, solar, battery, flows…) —
  x-axis labels **and** tooltip times.
- **Shared `semFormatTime`** helper → fixes the today-plan times and the system
  diagram's sunrise/sunset.
- **Price card** tariff-window times, **EV status card** (axis ticks + next-cheap
  window), **weather card** clock + forecast days.

# [1.7.3-beta.55] - 23.06.2026

## ⚡ Idempotent Huawei discharge-limit write (#538)

PROD modbus was throwing read **timeouts and out-of-order responses** because
SEM rewrote the Huawei battery discharge limit (`5000 W`, the unclamped NORMAL
default) **every coordinator cycle** even though it never changed — a redundant
write that collided with the huawei_solar read coordinators on the single serial
connection and ballooned cycle times to 13–28 s.

- `HuaweiBatteryAdapter._apply_discharge_limit` now **skips the write when the
  control entity is already at the target** (compared against the live entity
  state, so an external change is still re-asserted; writes when the state is
  unknown/unavailable). The per-cycle NORMAL spam is gone.

*(PROD-side, separate from the release: the `Huawei … Abfrage` polling
automation was slowed 10 s → 15 s to further cut modbus read pressure — the
native huawei_solar update interval is hardcoded at 30 s and not configurable.)*

# [1.7.3-beta.54] - 23.06.2026

## 🧹 UI polish

- **Removed all `evcc` references** from the dashboard help texts and the code —
  the surplus enable/disable delays are now described in plain terms (hysteresis
  enable/disable timers, deficit-persistence) without the external project name.
- **Added the missing help text** for **Regulation Offset** in the Advanced section
  (a small power buffer kept as grid export so SEM doesn't risk importing while
  regulating surplus charging).

# [1.7.3-beta.53] - 23.06.2026

## 🔋 Battery only assists the EV when the sun is out (#537)

The home battery was draining into the car overnight in `min_plus_solar` (PROD,
~6.5 kWh in one evening) — and in `always_max` — because battery-assist ran on a
sunset clock, not on actual solar. A single **Solar Gate** now governs it, in
**every** charging mode:

- **New "Solar Gate" knob** (`battery_assist_min_surplus`, default **1200 W**) on
  the Control tab and in the integration options. Below this much real solar
  surplus the battery is reserved for the house and the car draws from grid + solar.
- **Set it to 0 W** to let the battery support the EV everywhere, including
  overnight (opt-in — the previous behaviour).
- Enforced in two places so it can't leak: the EV budget (`min_plus_solar` /
  canonical battery-assist) and the battery discharge clamp (`decide_battery`),
  which now protects the battery in **any** mode incl. `always_max` and replaces
  the old night-only / `hold_solar` protection (gate = 0 restores it everywhere).

Verified on HA-TEST (deployed decision table correct incl. `always_max`); full
suite 3797 green.

# [1.7.3-beta.52] - 22.06.2026

## 🔌 EV charger reliability hardening (#536) — verified live on HA-TEST

A focused pass on the EV charger control, all confirmed live against a KEBA and a
switch-controlled Wallbox sim on HA-TEST:

- **Enable-switch backoff.** When a charger keeps flipping its *own* enable switch
  back off (Wallbox Eco-Smart / Autostart, or a conflicting integration), SEM no
  longer fights it forever — it re-asserts a few times, then **stops and surfaces a
  repair** ("charger auto-pausing — disable Autostart/eco-smart"), probing again
  periodically. This kills the start/stop oscillation.
- **`input_boolean` start/stop entities** are now driven like `switch.*` ones, so
  `off`/`idle` reliably open the contactor (previously enable worked but disable
  didn't).
- **No more `CHARGE_MAX` clamp-drift.** `always_max` resolves to the charger's
  *effective* max (config max clamped to the control entity's max) instead of the
  hardware max, so it stops spamming `WRITE 32A` + `clamping 32 A → 16 A` every
  cycle and converges cleanly.
- **Honest charger state.** When SEM is commanding a charge but the car isn't
  actually drawing (full / not ready), the dashboard now reads **"ready"** instead
  of "charging at 0 W" (power-based, debounced — never changes the command).

KEBA is unaffected by all of the above (no enable switch). The #392 idempotency
(no `keba.disable` spam) and the battery "discharge clamped to home load during EV
charging" protection were both re-verified live.

## 🧹 Internal: charger reconciler is now the sole actuation path

Removed the dead legacy EV-control code (`_execute_ev_control`, the legacy
`actuate()` body, the unused adapter idle-debounce) now that the desired-vs-observed
**reconciler** owns all charger actuation — net **−1073 lines**, with the self-resume
behavior moved to reconciler-native test coverage. No behavior change.

# [1.7.3-beta.51] - 22.06.2026

## 🔌 Wallbox "commanded but 0 W" — SEM now reconciles the enable switch (#536)

A Wallbox (and any charger controlled by a current **number** + a separate
**enable switch**) could sit at *Connected, Always-max, commanded 16 A, **0 W***
and never start, in any mode. Cause: SEM turned the enable switch on **once** at
session start and then never checked it again — if the switch later went off
(Wallbox auto-pause, locked, eco-smart mode, or an external toggle), SEM kept
writing the current to a charger whose contactor was open.

The charger reconciler (from beta.50) now treats the **enable switch as observed
state**: every cycle it reads the switch's *actual* state and re-asserts it when
charging is wanted and it's off — idempotent, and keyed on the switch state (not
power) so a full-but-plugged car never causes switch churn. A switch that's
**unavailable/locked** (e.g. eco-smart mode) is now surfaced as a repair instead
of silently swallowing every charge command.

> This was **not** the `ev_charger_service: "0"` value some configs show — that's
> been harmless since beta.43 (it's normalised to "use the number entity"). The
> real gap was the un-reconciled enable switch.

# [1.7.3-beta.50] - 21.06.2026

## ⚡ EV charging is now rock-solid in every mode — charger state reconciler

The KEBA kept dropping to 6 A / pausing, and we'd shipped five separate patches
chasing it. They all treated symptoms of one root cause: **SEM re-issued a
hardware command to the charger every ~10 s cycle**, whether or not anything had
changed. PROD logs caught it doing `keba.disable` **391 times in a row** on an
already-open contactor.

This replaces the per-cycle imperative actuator with a **desired-vs-observed
reconciler** that issues the *minimum* commands needed to converge, then leaves
the charger alone:

- **Idle / off issue zero redundant commands** — the contactor is opened once,
  not re-disabled every cycle (the 391× spam is gone).
- **Holds your commanded current** like a fixed-current charge, but solar-aware.
- **Drift correction** — if the box silently reverts to its 6 A failsafe floor,
  SEM re-asserts your target on the next cycle.
- **Failsafe armed once per charge episode** (not re-armed every cycle), kept fed
  by the per-cycle write heartbeat.
- **Same convergence path for all modes** (off / always_max / min_plus_solar /
  solar / solar_plus_cheap) — no mode-specific surprises.

Live-verified on HA-TEST across charge and off; full suite 3791 green. (#392)

> Note: a fixed-3-phase KEBA P30 still can't physically charge below ~4.1 kW, so
> in solar modes it will still *pause* when surplus is genuinely below the
> 3-phase floor — but now it pauses cleanly and predictably instead of bouncing.

# [1.7.3-beta.49] - 21.06.2026

## 📊 EV charging-power chart: no more phantom 11 kW peaks

The "EV Charging Power" chart (solar + battery + grid → EV, stacked) showed
impossible peaks — an ~11 kW "grid" spike while the EV only ever drew ~4.4 kW.
Cause: the chart plotted each source's per-hour **maximum** and then stacked
them. The three sources are complementary (when solar peaks, grid is 0), so
their maxes occur at different moments and stacking them triple-counts — the
stacked maxes far exceed the real instantaneous total. (There was never a real
11 kW; the grid genuinely peaked at ~4.9 kW, so peak management was unaffected.)

Stacked power charts now plot the per-bucket **mean**, so the components sum to
the real total and the area integrates to real energy. Non-stacked charts keep
the max so peaks stay visible.


# [1.7.3-beta.48] - 21.06.2026

## 🔧 Restore the second EV minimum + fix the solar-power config key

- **"Vehicle Min Amps" is back as a tile** (beta.47 hid it when equal to "Min
  Amps"). A charger legitimately has TWO minimums and both should be visible:
  **Min Amps** is your own floor (lowest current SEM bothers charging at);
  **Vehicle Min Amps** is your car's floor (some cars won't charge below ~8–9 A).
  The effective floor is the higher of the two. Only the genuinely-dead "Vehicle
  Start Amps" tile stays hidden.
- **Solar-power config key aligned.** The setup/options flow wrote `min_solar_power`
  while the runtime slider and the decision read `minimum_solar_power` — so a value
  set during setup never reached the runtime. The flow now writes the same key;
  existing `min_solar_power` values are still honoured.


# [1.7.3-beta.47] - 21.06.2026

## 🧹 EV current knobs cleaned up + two correctness fixes

Following the KEBA failsafe fix, a review of the EV current path (the user's
"three values, such a mess") and two confirmed bugs:

- **Removed the dead "Vehicle Start Amps" tile.** `initial_current` (10 A) is
  not read by the live charging path — the start ramp uses the Min Amps floor —
  so it was a settable tile that did nothing but confuse. Hidden from the card.
- **"Vehicle Min Amps" only shows when it differs from "Min Amps."** It defaults
  equal to the min, so it was a redundant second 9 A; now it only appears once
  you actually raise it to override a car that ignores the min (or in help mode).
- **The "Minimum Solar Power" slider now works.** Its value (`minimum_solar_power`)
  was never wired into the decision — the solar floor / deep-deficit guard always
  saw the 200 W default regardless of the slider. Now honoured (200 W fallback
  when unset).
- **1-phase chargers: amps↔watts floor fixed.** The MIN_PV / BATTERY_ASSIST / NOW
  power floors hardcoded 3 phases × 230 V, so a 1-phase charger's floor was 3× too
  high. Now uses the configured `ev_phases` / `ev_voltage` (3-phase unchanged).

Plus a recorded `min_plus_solar` steady-hold scenario pinning that the commanded
current doesn't flicker on steady surplus.


# [1.7.3-beta.46] - 21.06.2026

## ⚡ The real fix: KEBA stops reverting to 6 A (failsafe was misconfigured by SEM)

Root cause of the 6 A drops (car pausing to ~120 W mid-charge): on session start
SEM called `keba.set_failsafe(timeout=0, fallback=6)` to "disable" the failsafe —
but the HA service rejects `timeout=0` (its minimum is 1), so the call **failed
silently** and the box kept an active failsafe with a **6 A fallback** that
tripped during charging. SEM was, in effect, arming the gun it thought it had
unloaded (confirmed against evcc's KEBA handling — evcc never sets a 6 A
fallback).

SEM now sets a **benign** failsafe instead: a valid 30 s timeout that the
per-cycle `curr` writes keep resetting (so it never trips in normal operation),
and a fallback at the **charging floor** (your configured min, not 6 A) — so even
a genuine controller-death trip keeps the car charging at the floor instead of
pausing. Combined with the per-cycle refresh (beta.45), the offered current now
holds at the commanded value.


# [1.7.3-beta.45] - 21.06.2026

## ⚡ KEBA watchdog refresh — now per-cycle (beta.44 follow-up)

beta.44 cut the KEBA refresh to 30 s, but a PROD box still reverted to its 6 A
failsafe in under 30 s (offered current oscillating 6↔9 A, pausing the car to
~120 W). The KEBA refresh interval is now set **below the ~10 s coordinator
cycle**, so a steady command is re-asserted **every cycle** — outrunning any
failsafe with a timeout of at least one cycle. A box that reverts sub-cycle is a
device-side failsafe-config problem (disable failsafe or lengthen its timeout in
the KEBA app) that no write rate can out-run.

# [1.7.3-beta.44] - 21.06.2026

## ⚡ KEBA stops dropping to 6 A mid-solar-charge (watchdog refresh)

On a steady solar surplus a KEBA could oscillate its offered current between
~6 A and the commanded value about once a minute — charging at ~3.5 kW while
several kW exported to the grid. Cause: SEM holds a steady command and refreshes
the charger every **60 s**, but a KEBA's failsafe watchdog can trip near 60 s, so
the refresh *raced* the watchdog — the box kept falling back to its failsafe
current between refreshes.

The refresh interval is now a **per-charger device capability** instead of a
single global constant: a KEBA refreshes every **30 s** (comfortably under its
failsafe), while chargers without a short failsafe keep the 60 s default. An
explicit `_watchdog_refresh_override_s` wins for unusual failsafe settings. SEM's
command logic is unchanged — only the keep-alive cadence — so a steady command
now actually holds and the full surplus goes to the car.

# [1.7.3-beta.43] - 20.06.2026

## 🔋 Battery modes now map to the right Sessy strategy (#523)

RienduPre's beta.42 testing showed that on a Sessy (AC-coupled) every non-force
mode left the battery in `eco` — which isn't self-consumption — so `Auto` /
`Self-consumption` "didn't charge or discharge" and `Off` sat in `eco` too.
Each per-battery mode now drives the correct power strategy:

- **Auto / Self-consumption** → `nom` (zero-on-meter self-consumption), so the
  battery actually charges from surplus and powers the house — not `eco`.
- **Off** → `idle` (battery does nothing), with the setpoint zeroed.
- **Force charge / Force discharge** → `api` (SEM setpoint control) — unchanged.

After a force op ends (or the battery hits its reserve), it returns to `nom`
self-consumption instead of `eco`. The strategy values are configurable for
other AC-coupled brands (`battery_strategy_self_consume_value` /
`battery_strategy_off_value`). Huawei/DC batteries are unaffected (no strategy
select).

# [1.7.3-beta.42] - 20.06.2026

## 🐛 Pre-stable review fixes — forced charge restored (#535)

A full ruflo-core review of the battery subsystem ahead of stable 1.7.3 found a
blocker and three high-severity issues, all confirmed from code and now fixed:

- **Forced charging was silently broken on every brand.** The battery adapters
  built the internal charge command with the wrong field names
  (`charge_power_w`/`duration_min` vs the dataclass's
  `max_power_w`/`duration_minutes`), which raised a `TypeError` that the outer
  handler swallowed — so the **`Force charge` mode and the night-charge
  scheduler did nothing**. Fixed on Huawei, GoodWe, and the generic adapter, and
  the scheduler now carries a real charge power (it would otherwise have charged
  at 0 W). **(BLOCKER)**
- **Scheduled charging no longer fires at the wrong time.** A planned night
  charge used to start at *evaluation* time (e.g. 21:00) instead of inside the
  cheapest slot, because the schedule had no "is it active now?" check. It now
  respects the real slot boundaries.
- **Restart orphan-stop hardening (#532):** if the cancel command doesn't land
  (flaky Modbus) SEM now retries instead of giving up, and a multi-battery
  fleet sharing one inverter issues a single stop per device instead of two
  back-to-back (which the inverter would block).

# [1.7.3-beta.41] - 20.06.2026

## ⏸️ "Allow arbitrage" mode removed from the selector for stable 1.7.3 (#533)

- Automatic battery→grid arbitrage is fully deactivated for the stable release.
  On top of the global toggle being off (beta.40), the **`Allow arbitrage`
  per-battery mode is removed from the mode selector**, and the coordinator no
  longer evaluates arbitrage for a per-battery `allow_arbitrage` opt-in — a
  stale config goes dormant (behaves like `Auto`, no selling) instead of
  quietly selling to grid.
- **Kept** (tested, safe): `Auto`, `Self-consumption only`, `Force charge`,
  `Force discharge`, `Off`. Automatic arbitrage returns in **v1.7.4** after
  review + soak (#533).

# [1.7.3-beta.40] - 20.06.2026

## ⏸️ Battery→grid arbitrage deactivated for the stable release (#533)

- After the incident below, the **selling-to-grid feature is held back** for a
  stable release. The global arbitrage toggle is **forced off on upgrade**
  (config migration v13→v14) and its **section is hidden from the dashboard
  config card**, so it can't be enabled from the UI. The decision code and the
  per-battery modes stay intact — arbitrage returns in a later release once it
  has been reviewed and soaked (tracked in #533).

## 🛡️ A SEM restart no longer strands a Huawei battery force-discharge (#532)

- **Critical fix.** Huawei battery→grid arbitrage uses the
  `huawei_solar.forcible_discharge_soc` service, which the inverter then runs
  **autonomously until its target SOC**. A SEM restart or config reload while a
  discharge was in flight gave the fresh adapter no record of it, so SEM never
  sent the stop — the inverter kept discharging the battery to the reserve floor
  **unsupervised** (a dev/observer test drained a real LUNA2000 from 80% to 20%,
  exporting to the grid for ~1h40m before it self-terminated at the floor).
- SEM now detects an active forcible op via the integration's status sensor on
  the first cycle after startup and issues one `stop_forcible_charge` to cancel
  anything it didn't start — waiting for the integration to load and for the
  sensor to report a real value (no false stops, no missed ops). Resuming
  arbitrage after a restart re-asserts the sell instead of stopping it.

# [1.7.3-beta.39] - 19.06.2026

## 🔋 New battery mode: "Off (SEM hands-off)" (#523)

- **A sixth per-battery mode, `Off`, that tells SEM to leave a battery completely
  alone.** Requested by @RienduPre. On the transition into `Off`, SEM does a
  one-time clean handoff (clears any force command, releases the power strategy
  it took, un-limits the discharge) so the battery isn't stranded in a
  SEM-imposed state — then issues **nothing** further: no protection, no
  scheduler, no arbitrage. The inverter runs the battery on its own. Highest
  precedence, so it overrides every other decision branch. Available in the
  per-battery mode selector and translated in all 15 languages.

# [1.7.3-beta.38] - 19.06.2026

## 🔋 Battery arbitrage / per-battery review batch (#531)

A holistic review of the arbitrage / per-battery / AC-coupled (Sessy) subsystem
after a string of reactive #523 fixes. Three independent reviewers, every finding
confirmed from code, fixed and tested as **one batch**.

- **Charge-first: never sell stored energy while free solar surplus could charge
  the battery.** Storing surplus avoids a future import (~full retail price),
  worth far more than the export price — SEM now suppresses the sell verdict
  while storable surplus exists and the battery isn't full. (#531)
- **Arbitrage break-even now uses the all-in import rate, not raw spot.** The
  upcoming-price curve is raw spot for Nord Pool / ENTSO-E but all-in for Tibber;
  selling against raw spot lost money for spot-tariff users. SEM scales the
  forecast minimum up to the live all-in rate (no-op for all-in providers). (#531)
- **SOC unavailable → SEM holds instead of selling blind.** A setpoint battery
  (Sessy) has no hardware reserve-stop, so an unavailable SOC could drain it past
  the backup reserve. When in doubt, hold — the live SOC self-heals next cycle. (#531)
- **A stale global battery mode no longer bleeds into a multi-battery fleet.**
  After a single→multi upgrade the UI showed `auto` while a leftover global
  `force_discharge` drove every battery; multi-battery slots now default to
  `auto` and only the single-battery selector reads the global key. (#531)
- **EV-night protection splits the home budget across the fleet.** Two batteries
  each told to inject the *full* home load over-injected 2× and leaked surplus to
  the EV — each now gets `home / N`. (#531)
- **Strategy no longer stranded in API after a reload.** If SEM restarts
  mid-episode with the strategy already in API, the fresh adapter adopts control
  so the next idle cycle hands it back instead of leaving the battery
  setpoint-controlled forever. (#531)
- **Mixed-brand fleets: an AC-coupled battery stays on the generic adapter.** A
  Sessy in a Huawei fleet is no longer promoted to the Huawei adapter (whose
  service calls would never reach it) just because the Huawei integration is
  loaded for a sibling. (#531)
- **Arbitrage exit is explicit.** A non-firing arbitrage verdict now propagates a
  clean STOP rather than falling back to a possibly-stale night-charge decision —
  without ever overriding an active or planned charge. (#531)

## 🛟 Robustness (#531)

- The discharge-limit write is domain-aware (`input_number` helpers work, not
  just `number`), matching the force-discharge path.
- A setpoint clamped to the control entity's range now logs a WARNING instead of
  silently capping — surfacing a fleet-power-vs-unit-rating mismatch.
- Two batteries accidentally sharing one control entity now log a collision
  warning instead of silently fighting over the setpoint.

# [1.7.3-beta.37] - 19.06.2026

## 🔋 Battery charges from surplus again — SEM stops clobbering the power strategy (#523)

- **The battery no longer sits idle while solar surplus is exported.** SEM's
  strategy-release path forced the configured idle value (`eco`) onto the
  battery's power-strategy select **even when SEM had never taken control** —
  clobbering the user's self-consumption mode (e.g. Sessy `nom` = zero-on-meter)
  and stopping the battery charging from surplus (RienduPre: battery idle at
  20 % SOC while ~1 kW of surplus exported to grid). SEM now **only restores a
  strategy it actually changed**; if it never switched to API it leaves the
  user's mode alone. When it *did* take control it restores the captured prior
  mode (or the idle fallback if unreadable — never stranded in API).

## 💶 Battery arbitrage holds without an import-price forecast (#523)

- **No more selling on the export floor alone.** When there's no upcoming
  import-price forecast, SEM can't prove that selling now beats buying back
  later, so it **no longer fires** (the break-even check was previously skipped,
  making it sell too eagerly). Conservative default; pairs with the export floor.

## 🔧 A repair when a %-SOC charge cap can't be enforced (#526)

- **No more silent overshoot past the SOC limit.** A `%` charge target needs a
  readable vehicle SOC to stop at the cap; when the car isn't reporting SOC
  (asleep / no real sensor), SEM keeps charging until the car tapers — which
  surprised users ("car went past 80 %"). SEM now files a **repair**
  (Settings → Repairs) explaining the cap can't be enforced and how to fix it
  (wire a real vehicle SOC sensor); the dashboard's *estimated* SOC is
  deliberately ignored for the hard limit. Clears automatically when a real SOC
  reading returns.

# [1.7.3-beta.36] - 19.06.2026

## 🔋 Battery setpoint is clamped to the control entity's range (#523)

- **Force-charge / force-discharge no longer get rejected for being
  out-of-range.** SEM wrote the raw charge/discharge power to the setpoint
  number — but a Sessy unit's setpoint maxes at ~±2200 W, so a fleet
  `battery_max_charge_power_w` of 4400 W written to a single 2200 W unit was
  **−4400 W**, which Home Assistant rejects as out of range. The write failed
  silently and the setpoint stayed at **0**, so the battery never charged
  (RienduPre: strategy flipped to API, setpoint stuck at 0). SEM now **clamps
  the setpoint to the entity's `min`/`max`** before writing (mirrors the EV
  #487 fix) — −4400 → −2200, and it charges.

# [1.7.3-beta.35] - 19.06.2026

## 🔋 Battery control config is reachable without enabling arbitrage (#523)

- **The force-discharge entity, power-strategy entity, and "Bidirectional
  setpoint" toggle now appear in a "Battery control" section whenever a battery
  exists** — previously they were hidden behind the *battery arbitrage* toggle
  (itself only on a dynamic tariff). A user who wants `force_charge` or
  per-battery modes (not arbitrage) couldn't find them, so `supports_forced_charge`
  stayed False and the decision was dropped every cycle (RienduPre). Now they're
  always available, and a **new power-strategy entity picker** lets you wire the
  Sessy `select.*_power_strategy` from the UI (was config-only before).
- **Battery SOC autodetect also matches by signature** (`device_class: battery`
  + `%`), so a localized name like the Dutch `sensor.*_batterijpercentage` is
  found even without an English SOC keyword (#529, DavidVM1982).

# [1.7.3-beta.34] - 18.06.2026

## 🔋 Battery SOC: reachable when it lives off the power sensor's device (#529)

- **A battery SOC sensor that autodetect couldn't reach is now found.** Some
  installs (e.g. a Huawei Luna with a generic `sensor.battery_state_of_charge`,
  or a template helper) expose the SOC on a *different* device than the battery
  power sensor — so neither the name-prefix nor the same-device scan could find
  it, and SEM showed no SOC even though the HA Energy Dashboard read it fine. A
  **guarded global last-resort scan** now finds the lone home-battery SOC sensor
  (a SOC-keyword name + `%` unit, excluding EV/phone batteries) — only when
  **exactly one** unambiguous candidate exists, never a guess (#529).
- **Manual override:** `battery_soc_sensor` is now a settable option (structural
  → reloads), so when autodetect still can't decide, you can point SEM at the
  right sensor explicitly via the `set_option` service.

# [1.7.3-beta.33] - 18.06.2026

## 🔋 AC-coupled batteries (Sessy) can now force-CHARGE (#523)

- **SEM can now force-charge a Sessy-style battery.** These batteries have no
  charge *switch* — they charge by writing a **negative** value to the same
  bidirectional power setpoint that discharge writes a positive value to. SEM's
  switch-based charge path couldn't drive them, so `force_charge` (and scheduled
  night charging) silently did nothing. New opt-in **"Bidirectional setpoint"**
  toggle (Configuration → Battery, next to the forcible-discharge entity): when
  on, force-charge writes `-power` to the setpoint, gated by the power-strategy
  → API switch. Verified live on HA-TEST (force_charge → −2200 W setpoint +
  strategy `api`; release → 0 W).
- **SEM restores the battery's prior power-strategy instead of forcing `eco`.**
  Researching the ha-sessy integration showed the real strategy options are
  lowercase `api`/`nom`/`roi`/`idle`/`eco`. SEM now **captures** the user's
  strategy (e.g. `nom`/`roi` self-consumption) before taking control and
  **restores** it on release — so it no longer clobbers their normal mode.
- **Fixed force-charge commanding 0 W** when `battery_max_charge_power_w` is
  present-as-`None` (a `.get(key, default)` returns `None`, not the default).
  The charge power now falls through `battery_max_charge_power_w` →
  `battery_max_charge_power` → 5000 W. Harmless before (the charge switch
  ignored power); surfaced by the new bidirectional setpoint path.

# [1.7.3-beta.32] - 18.06.2026

## 🔥 Heat pump: restore the SG-Ready invert toggle (#523)

- **Brought back the opt-in "Invert SG-Ready contacts" toggle** (Configuration →
  Heat Pump) that beta.31 removed. It's inert by default and costs nothing, but
  it's the one-click safety net for an install wired normally-closed (NC) — so a
  pump that boosts-as-block can be corrected without a second release round-trip.
  The corrected standard map remains the default.

# [1.7.3-beta.31] - 17.06.2026

## 🔥 Heat pump: drop the speculative invert toggle (#523)

- The SG-Ready truth table is **universal across EMS vendors** (verified against
  alpha innotec / gridX / SMA / SolarEdge), so the corrected map from beta.30 is
  right for everyone. The opt-in "Invert SG-Ready contacts" toggle was a
  speculative knob for a normally-closed-wiring case no one has actually
  reported — removed to keep the config surface lean. It can come back later if
  a real inverted-wiring install turns up. The corrected standard map stays.

# [1.7.3-beta.30] - 17.06.2026

## 🔥 Heat pump: SG-Ready relay map corrected to the standard (#523)

- **Fixes "the heat pump never got turned on" on SG-Ready pumps (RienduPre,
  Nibe).** SEM's `SG_READY_RELAY_MAP` was a plain 2-bit count, not the SG-Ready
  standard truth table — so when SEM wanted to **boost** the pump on surplus it
  drove `(relay1=on, relay2=off)`, which a standard pump (Nibe et al.) reads as
  **EVU-block** and turns *off* instead of on. Corrected to the SG-Ready
  standard: BLOCKED `1:0`, NORMAL `0:0`, BOOST `0:1`, FORCE_ON `1:1`.
- **New opt-in "Invert SG-Ready contacts" toggle** (Configuration → Heat Pump)
  for installs whose contacts are wired **normally-closed (NC)** — it flips both
  relays so the standard map still drives the right physical state. Default off
  (NO wiring, the common case).
- The Control-tab "not configured" label for a correctly-registered heat pump
  was already fixed in beta.19 — update past beta.19 to clear it.

# [1.7.3-beta.29] - 17.06.2026

## 🩹 Wallbox: a junk `charger_service` no longer blocks current control (#523)

- **Fixes "Failed to set current … not enough values to unpack" spamming
  every 10 s on both Wallboxes (RienduPre).** A leftover `charger_service='0'`
  (no `domain.service` shape — and it even propagated to a sibling charger whose
  own config was empty) hit the service branch and crashed the
  `charger_service.split(".", 1)` unpack, so SEM could never set the charge
  current — even though both chargers had a valid
  `number.wallbox_*_max_charging_current` control entity. SEM now **treats any
  `charger_service` that isn't a real `domain.service` as absent** and falls
  through to the number entity. Guards all three actuation paths (set-current /
  start / stop) at once.

# [1.7.3-beta.28] - 17.06.2026

## 🔋 AC-coupled batteries (Sessy) honour the power setpoint (#523)

- **A generic AC-coupled battery (e.g. Sessy) now actually force-discharges and
  sells.** These batteries ignore their power setpoint unless their *power
  strategy* select (`select.sessy_*_power_strategy`) is in the API/active mode —
  in eco/NOM they just self-consume. SEM now **switches the strategy to the
  active value before writing a force/arbitrage setpoint** and **back to the idle
  (self-consumption) value** when returning to NORMAL / limit / stop. Configure
  it per battery via the new `battery_strategy_entities` (or the single-battery
  `battery_strategy_control_entity`); active/idle values default to `api`/`eco`
  and are overridable. Inert on batteries without a strategy select (Huawei,
  GoodWe) — no behaviour change there.

## 🔌 Huawei battery: zero-config forcible discharge (#523)

- **A Huawei battery's force / arbitrage modes now work with no manual
  config.** The `huawei_solar.forcible_discharge_soc` service targets the
  battery *device*; previously you had to set `inverter_device_id` by hand or
  the command was dropped. SEM now **auto-detects the Huawei battery device**
  from the device registry (the `connected_energy_storage` device), so
  `supports_forced_discharge` is true out of the box. A manually-set
  `inverter_device_id` still wins.

# [1.7.3-beta.26] - 17.06.2026

## 🔧 Battery adapter self-heals a startup race (#523)

- **A Huawei/GoodWe battery no longer gets stuck on the Generic adapter.** If
  the brand integration (e.g. `huawei_solar`) finishes loading *after* SEM's
  first battery cycle on boot, SEM used to cache a Generic fallback for the
  whole session — so brand-specific control (Huawei forcible discharge) silently
  never engaged. SEM now **re-detects once the brand integration is loaded** and
  upgrades the adapter in place. Surfaced by the new beta.25 `battery_control`
  diagnostics, which showed a real Huawei battery reporting `GenericBatteryAdapter`.

# [1.7.3-beta.25] - 17.06.2026

## 🩺 Battery + surplus observability in diagnostics (#523)

The one-click **Download Diagnostics** now answers the two questions that
previously needed a back-and-forth (or a DB dump):

- **`battery_control`** — is the battery controllable at all (adapter class,
  `supports_forced_charge` / `supports_forced_discharge`, the wired control
  entities + whether an inverter device is set), what **mode + reserve** it's
  in, and the **last per-battery decision + reason** — so *"is the EV draining
  the battery?"* is a single readable line (`LIMIT_DISCHARGE — ev_charging →
  1200 W`).
- **`surplus`** — the live surplus allocation snapshot (distributable surplus,
  who won it, active vs total devices) — which, with the existing `heat_pump`
  block, explains *"why didn't the heat pump turn on?"* (not enough surplus,
  lost priority, or not wired).

No new data collection or DB dump needed — it's all in the existing
diagnostics payload.

# [1.7.3-beta.24] - 17.06.2026

## 🔋 Battery mode selector on single-battery installs (#523)

- **The Battery card mode selector now appears on single-battery installs too.**
  beta.23 only created the per-battery Mode + Reserve-SOC controls for
  multi-battery setups, so a single-battery install (the common case) had no way
  to pick **Auto / Self-consumption / Allow arbitrage / Force charge / Force
  discharge**. There's now a global `select.sem_battery_mode` +
  `number.sem_battery_reserve_soc`, shown on the battery hero card.

# [1.7.3-beta.23] - 16.06.2026

## 🔋🎛️ Per-battery control + Huawei forcible-discharge fix (#523)

Multi-battery installs (e.g. Growatt + Sessy, or two LUNA2000s) can now be
controlled **per battery**, and battery → grid arbitrage actually works on a
real Huawei battery — verified live on a Huawei SUN2000 + LUNA2000.

- **Per-battery Mode selector on the Battery card** — each battery gets its
  own mode: **Auto** (today's behaviour), **Self-consumption only** (never
  sells to grid), **Allow arbitrage** (sell when export beats recharge cost,
  even with the global toggle off), **Force charge**, **Force discharge**
  (manual sell to grid). Plus a per-battery **Reserve SOC** floor — a battery
  never discharges below it, on every mode. One battery can sell while its
  sibling holds, gated purely by mode. (`select.sem_battery_<id>_mode` +
  `number.sem_battery_<id>_reserve_soc`, live — no reload.)
- **EV-card-style battery tiles** — each battery now shows the filled battery
  glyph with SOC %, a flow-coloured status badge, power, and (when capacity is
  known) stored energy + time-to-full/empty, matching the EV charger card.
- **Per-battery force-discharge entity pickers** in Configuration → Tariff, so
  each battery's sell setpoint is wired from the dashboard, not YAML.
- **Huawei forcible discharge now actually works.** Huawei has no
  forcible-discharge *number* entity — it's the `huawei_solar.forcible_discharge_soc`
  *service*. SEM previously wrote to a non-existent number, so battery → grid
  selling silently did nothing on every real Huawei (including the beta.22
  arbitrage feature). It now drives the service (discharge to the reserve SOC,
  which self-terminates there as a safety floor). Force-discharge writes are
  also domain-aware (real `number.*` setpoints **and** `input_number.*` helpers).
- **Anti-block hardening.** The LUNA2000 locks up if it gets `stop_forcible_charge`
  plus another Modbus write back-to-back in one cycle. The Huawei adapter is now
  a clean state machine — exactly one command per transition, the rest deferred
  to the next cycle — and a dropped stop self-heals by re-issuing on the next
  cycles. Battery-brand detection also no longer misses a modern `huawei_solar`
  install (config-entry check, not just `hass.data`).
- **Per-battery SOC fix** — on multi-battery installs the per-battery tiles
  could read 0 % because SOC auto-detect only matched 2-part sensor names; it
  now matches indexed devices (e.g. `…battery_2_soc`).
- Removed the dead legacy `BatteryChargeScheduler.update()` path.

# [1.7.3-beta.22] - 16.06.2026

## 🔋💶 Dynamic export-price optimisation — sell the battery when export is high (#523)

- **Signed export price.** On an EPEX/Tibber/Nord Pool dynamic contract the export price *is* the spot price and is regularly negative (you pay to export). SEM no longer `abs()`-es the feed-in price, so a negative export is correctly a cost — fixing export revenue/ROI and unlocking export-aware decisions. (Auto-detected Amber keeps its sign-inverted convention.)
- **Battery → grid arbitrage, built into the charge scheduler.** Discharge-to-grid is the mirror of the scheduler's charge-on-cheap logic, so it lives **inside `BatteryChargeScheduler`** and reuses the same economics (round-trip efficiency + cycle cost): SEM sells stored energy to the grid only when the export price beats the cost of recharging it later (cheapest upcoming import ÷ efficiency + degradation). Opt-in (**default off**), never sells below a configurable reserve SOC, and never runs while a charge is planned. Flip the toggle off mid-sale and the next cycle stops it cleanly.
- **Works across battery brands.** The forcible-discharge command is brand-agnostic (base adapter), driven by a configurable discharge-power entity — Huawei LUNA, GoodWe, and the generic catch-all (Victron / SolaX / Growatt / Sessy / Powerwall / …). A battery without a discharge-power entity safely has the decision dropped.
- **"Selling to grid" on the Battery card** — a distinct gold state with the live export price while SEM is exporting the battery.
- **New Configuration → Tariff settings** (dynamic mode): *Sell battery to grid on high export*, *Min export price to sell*, *Arbitrage reserve SOC*, and the *Forcible-discharge power entity*.

# [1.7.3-beta.21] - 16.06.2026

## 🎨 Dashboard polish — battery glyph + EV status spacing

- **System diagram: the charging bolt no longer sits on top of the SOC number** — when the battery was charging, the ⚡ was drawn centred over the "58%", making it hard to read. The bolt now sits in the upper part of the battery and the percentage drops just below it, so both are clearly legible.
- **Battery card now shows the filled battery glyph** — the small icon in the SOC ring was a flat outline; it is now a filled, SOC-level battery (tinted with the charge/discharge colour, with a charging bolt) matching the system diagram.
- **EV card: "Status" label and value no longer touch** — in the centred hero the row shrink-wrapped so it read "StatusDisconnected"; a minimum gap keeps the label and value apart.

# [1.7.3-beta.20] - 15.06.2026

## 🔌 EV no longer keeps charging from expensive grid after the cheap window (#524)

- **Tariff awareness restored to the EV decision layer** — the fleet cycle read a non-existent `provider.current_level` attribute, so `tariff_level` was *always* `None`. Every tariff-aware EV decision was silently dead: `solar_plus_cheap` / `min_plus_solar` never saw their expensive windows, so the daytime "pause on expensive tariff" never engaged. Now read via `provider.get_price_level()` (by @RienduPre in #524)
- **The charge-stability bridge no longer imports expensive grid** — when solar surplus dips below the minimum, the layer holds minimum current for up to 5 minutes to ride out a passing cloud. In a **not-cheap** tariff window that meant importing expensive grid for the whole bridge. It now stops on the short (~45 s) grace during normal/expensive/very-expensive windows, while cheap / very-cheap (and static tariffs) keep the full cloud-bridge (by @RienduPre in #524)

## 💶 Clearer export-rate / feed-in help for dynamic tariffs (#523)

- Export-rate and Feed-in-entity help text now explains how to value exports on a dynamic/spot contract (a flat average, or a live feed-in sensor) — so export revenue and ROI populate instead of staying at 0 (by @RienduPre in #523)

# [1.7.3-beta.19] - 15.06.2026

## 🔧 Control-tab heat-pump card + Home 7-day chart fixes (#523)

- **Heat pump no longer shows "not configured" while clearly configured** — the Control-tab Heat Pump section read the `heat_pump_registered` *binary* sensor through a helper that only resolves `sensor.sem_*` entities, so it always evaluated false and showed the "not configured" notice, while the section header still rendered "normal · 2" (sg-ready state defaults to 2). Both the body and the header now read the binary sensor correctly, so the card is consistent (by @RienduPre in #523)
- **Home "Last 7 days" chart no longer collapses to a single bar on Mondays** — the energy summary used a "this week" (Monday→now) window, which on Mondays is a single day and rendered as one stray bar, contradicting the card's "Last 7 days" title. It now uses a rolling 7-day window (always 7 day-buckets) (by @RienduPre in #523)

# [1.7.3-beta.18] - 14.06.2026

## 🏷️ Deterministic grid-sign by meter brand (#461)

- **Known meter integrations now seed the grid sign instantly** — for well-tested brands (Huawei, SMA, Fronius, Enphase, SolarEdge, Kostal, Powerwall, GoodWe, SolaX) SEM reads the grid-power sensor's own integration and applies that brand's known import/export convention immediately, so a fresh install is correct from the first cycle without waiting for solar swings or counter deltas. A separate P1/CT meter (unknown integration) simply falls through to the solar/counter detectors, and the solar co-movement signal can still override a brand seed if it ever disagrees (#461)

# [1.7.3-beta.17] - 14.06.2026

## 🧭 Robust grid-sign autodetection + one-tap fix (#461)

- **Solar-anchored detection is now the authoritative primary** — solar production has no sign ambiguity, so SEM now learns the grid import/export convention from how the raw grid reading *co-moves with solar* (grid rises with solar → `+export` meter; grid falls as solar rises → `+import` meter). This is completely independent of the Energy-Dashboard import/export counters, so a mis-mapped or swapped counter (the root cause of the Sessy-P1 wrong lock) can no longer corrupt the result. It can also self-heal a wrong existing lock once it is highly confident and sustained — and because a correctly-signed install computes the *same* sign it already has, a working install is never disturbed (#461)
- **Counter-correlation hardened** — the fallback path (grid-only installs, no solar) replaced the old "3 consecutive votes" lock, which a mixed/transient counter burst could slip through, with magnitude-weighted evidence scored by *confidence*: it only locks when the dominant direction holds ≥75% of all accumulated evidence, so an inconsistent meter stays in passthrough instead of locking the wrong sign (#461)
- **One-tap "Fix grid sign" button in Configuration → Advanced** — flips the convention instantly (via the new `flip_grid_sign` service) and copies a ready-to-paste diagnostics report (raw meter value, configured counters, both correlation streams) to the clipboard for a GitHub issue. The neighbouring "Reset sign detection" re-learns from scratch and now also clears a prior manual flip so the re-learn starts clean (#461)

# [1.7.3-beta.16] - 14.06.2026

## 🌍 More Dutch translations on the diagnostic dashboard (#515)

- Expanded `nl` coverage across the diagnostic dashboard (by @RienduPre in #515)

## 💶 A configured dynamic price sensor no longer silently flips to Nord Pool (#518)

- **Your chosen price entity stays the source, even on a momentary blip** — when a user configures a dynamic price sensor (`dynamic_tariff_entity`, e.g. a Tibber sensor with VAT/fees), SEM used to *fall through* to auto-detecting another integration whenever that sensor read `unavailable`/`unknown` for a cycle. With the Nord Pool integration also installed, the provider silently switched to `nordpool_official` — a different source with different (tax-free spot) prices and percentile levels, so the schedules/price-levels appeared to flip back and forth (RienduPre, #518). A user-configured price entity is now authoritative: the provider stays `custom` and the cached curve / fallback price covers a transient gap. Auto-detection only runs when no price entity is configured (#518)

## 🌤️ Weather tile no longer shows "?" / "—°C" when the picked entity has no data (#516)

- **The weather tile now finds a weather entity that actually has current data** — RienduPre's tile showed a "?" condition and "—°C / — % / — km/h" because the dashboard generator picked a `weather.*` entity that carried no `temperature` (a `weather.forecast_*` subentity, or one that was unavailable when the dashboard was generated). The generator now prefers a non-forecast entity that actually has a current temperature, and the card falls back at render time to any usable `weather.*` entity if its configured one is missing / unavailable / data-less — so the tile self-heals without regenerating the dashboard (#516)

## 🔢 Per-charger "today" energy now resets at midnight even when idle (#517)

- **A charger that didn't draw power all day no longer carries yesterday's energy forward** — RienduPre (dual Wallbox) saw "Vandaag" (today) = 81.5 kWh on a charger that wasn't even connected, while the fleet total correctly showed 0. The per-charger daily *rollover/reset* was nested inside the `if charger_power > 0` accumulation guard, so an idle/unplugged charger never executed it and its counter grew across idle days. The reset now runs every cycle for every charger (only the increment stays gated on power); a stored stale value self-heals on the next cycle after update. Single-charger installs were unaffected (they report the correctly-resetting fleet total) (#517)

# [1.7.3-beta.15] - 14.06.2026

## 🏷️ Config-tab label audit + clearer forecast/EV-priority controls (#514)

- **The EV charger "Min Amps" stepper was mislabelled "Minimum SOC"** — the Config tab's per-charger minimum-current control (in Amps) showed the battery-SOC label. Fixed to "Min Amps". The battery section's legitimate "Minimum SOC" is untouched (#514)
- **Surplus Priority + Shed Priority steppers now appear on each EV charger** in the Config tab, alongside Min Amps / Start current / Capacity (matching how Hot water and Heat pump show "Priority"). The #470 entities existed but weren't surfaced on the card (#514)
- **Raw translation keys no longer leak onto the dashboard** — Hot water's "Max temperature" row and the Max-Grid-Import help text rendered their raw keys (`hot_water_max_temperature`, `tile_help_max_grid_import`); both now show proper labels (#514)
- **Forecast source shows its brand name** — the Config tab showed the raw id (`forecast_solar` / `FORECAST_SOLAR`) while the Home hero already showed "Forecast.Solar". Both now share one base helper so they agree and can't drift (#514)

## 📊 EV "Today's plan" strip no longer renders empty when the next charge is >12h away (#512)

- **The 12h plan strip now shows a full "nothing scheduled" idle bar instead of blanking** — when the next EV charging event was beyond the strip's 12h window (e.g. a morning view with night charging set for 21:35), the segment builder advanced its cursor past the window end and skipped the idle-fill, producing zero segments and an empty strip (title/axis/legend showed, but no timeline). Each transition is now clamped to the horizon so the visible time is always painted. Not mobile-specific — desktop blanked in the same state too (#512)

## ☀️ Heat pump / hot water boost on the TRUE house surplus, and stand down under peak (#508 phase 2)

- **They now see real spare solar, not the EV's budget (W7)** — the surplus controller was fed the EV charging *budget*, so heat pump / hot water effectively competed for the EV's allocation. It now receives the true house surplus: `grid_export + its own active device draw`. The add-back is what makes it stable — without it, every device the controller switches on shrinks the grid export it reads next cycle, so the signal would chase its own tail and the device would flap. With it, the input is the surplus that *would* exist if its devices were off — the right quantity to allocate from. Net effect: discretionary loads boost only on genuine spare solar, after the EV and battery have taken their share (#508)
- **They back off when the grid-import peak is at risk (W2)** — the load manager and the surplus controller used to fight: the load manager would shed a heat pump to protect the 15-minute peak, then the surplus controller (running later in the same cycle) would see surplus and switch it straight back on. The surplus controller now receives the load manager's peak posture — on `WARNING` it stops *adding* discretionary load; on `SHEDDING` it backs its own devices off one per cycle (gentlest first by reverse priority); on `EMERGENCY` it sheds them all at once. The EV stays owned by the load manager's shed path (#508)

## 🔀 Independent surplus vs shed priority per EV charger (#470)

- **`ev_shed_priority` splits off from `ev_surplus_priority`** — a single number used to drive two unrelated decisions: who gets solar surplus first (cooperative, every cycle) and who gets throttled first when grid import nears the peak limit (emergency). A mixed fleet can't express both — e.g. a long-range EV should charge *first* on surplus (big battery soaks watts) yet shed *first* under peak (range cushion absorbs a throttle). Surplus order stays on `ev_surplus_priority`; shed order moves to the new per-charger `ev_shed_priority`, exposed in the options flow, the setup flow, and as a per-charger number entity. A v12→v13 migration seeds `ev_shed_priority = ev_surplus_priority` for every existing charger, so the decoupling is behaviour-neutral until you deliberately diverge them (#470)
## 🔌 EV no longer drains the battery to hold a dead solar session (#461)

- **The disable hold now distinguishes a transient dip from genuine darkness** — the 300 s disable delay exists to BRIDGE a passing cloud (solar drops 8 kW → 3 kW for a minute while the car wants 4) by holding minimum current instead of cycling the contactor. But when solar is genuinely ~0 W — dusk, heavy overcast, or the `is_night` flag not yet flipped — there is nothing to bridge *to*: that held minimum current is pulled entirely from the home battery and the grid. RienduPre's PROD logs caught it live: solar = 0 W, the hold commanding 9 A, the car flapping 4.35 kW ↔ 0.12 kW while the battery drained at 5 kW and the grid imported 1.7 kW — every 300 s window. A deficit while solar is below `min_solar_w` (the same "no meaningful solar" threshold `solar_only` idles on) is now a **deep deficit** and stops after a short grace (`ev_deep_deficit_grace_sec`, default 45 s) instead of the full window. A genuine transient dip — solar still meaningful — keeps the full bridge unchanged. The grace rides out a single-cycle inverter flicker to 0 W so a momentary zero never ends a real daytime session (#461)

## 🔥 Heat pump / hot water: surplus activation actually fires + relay-failure safety (#508)

First phase of wiring the dedicated heat-pump and hot-water controllers into the surplus pipeline they were bypassing.

- **They actually activate on solar surplus now** — both controllers defaulted to `PEAK_ONLY`, and the surplus controller never proactively turns on a non-`SURPLUS` device, so surplus boosting was silently inert. Both now default to `SURPLUS` (still overridable via `set_device_control_mapping`) (#508)
- **A failed SG-Ready relay write no longer credits phantom power** — the heat pump used to mark itself `ACTIVE` and deduct `rated_power` from the surplus pool even when the relay call failed, starving the EV/battery of watts that weren't being drawn. It now returns 0 W and reports `ERROR`; a partial (relay2) failure restores relay1 to its prior state instead of leaving a stray curtail signal (#508)
- **Legionella prevention runs** — `check_legionella_cycle()` had no production caller (the disinfection cycle never ran, `hours_since_legionella` was pinned at 999). It's now driven every cycle, and the last-cycle timestamp persists across restarts so a reboot doesn't force a disinfection run (#508)
- **Heat-pump compressor anti-cycling** — `min_on`/`min_off` guards (10 min run / 5 min rest) so a 10 s coordinator cycle can't short-cycle the compressor (#508)
- Follow-up phase (tracked in #508): route them through the load-manager dual-sync for peak shedding, and feed the true house surplus rather than the EV budget

# [1.7.3-beta.14] - 13.06.2026

## 🏠 System-diagram Home no longer flickers to 0 W while the EV charges (#506)

- **The diagram card reads the published `home_consumption_power` sensor instead of re-deriving it client-side** — Home was recomputed from the raw source sensors, which update on wildly different cadences (Huawei inverter ~17–30 s modbus vs KEBA EV ~2 s). With the EV charging hard, a fresh EV reading paired with a stale solar reading drove the residual briefly negative → clamped Home to 0, on and off. The coordinator's #237/#444 hold already rides out that skew (the sensor itself never flickers); the card now uses it, with the residual kept only as a fallback when the sensor is unavailable (#506)


# [1.7.3-beta.13] - 13.06.2026

## 🔮 Forecast dampening: morning jitter smoothed + correct sun window (#416)

Closes the two remaining sub-findings of the #416 forecast-correction audit (the other three — shrinkage naming, telemetry surface, write-time weather snapshot — shipped earlier and are soak-verified on PROD).

- **The live dampening signal is EMA-smoothed (τ ≈ 5 min)** — at 7–9 AM the expected-production fraction is tiny, so the normalized live ratio amplified the actual-sensor noise floor (cloud transits, inverter sampling) into large cycle-to-cycle swings of `forecast_dampening_factor`. The blend now consumes a time-based EMA of the ratio; genuine weather trends still pass with little lag. Raw and smoothed values are both on the sensor's diagnostic attributes (`normalized_ratio` / `smoothed_ratio`) (#416)
- **`_get_sun_hours` no longer mixes tomorrow's sunrise with today's sunset** — `next_rising`/`next_setting` are NEXT events; tomorrow-dated ones now roll back a day, fixing the skewed daylight window (~1 min average, worse near solstices/high latitudes) (#416)

## 🧭 Sign-detection locks survive restarts (#476)

The grid/battery sign autodetect locks were RAM-only — every reload re-learned the sign from possibly ambiguous low-power samples, and three bad votes right after a reboot could lock the WRONG sign until the next reload (the 2026-06-11 PROD flip).

- **Locked signs now persist** in SEM's storage and restore at setup — the warmup/vote machinery runs once per install, not once per restart; only LOCKED state persists (votes and half-learned guesses never do), and a restored lock survives the Energy Dashboard being reconfigured away (#476)
- **Manual `grid_sign_invert` still wins** — it short-circuits before the autodetect, so a restored lock can never fight a manual override
- **New `solar_energy_management.reset_sign_detection` service** — the escape hatch: forgets all sign locks (RAM + storage) and re-learns from scratch, since a wrong lock no longer clears itself on restart
- Closes the last open item of the #476 robustness batch — items 1–4 and 6–9 already landed across the #485/#486/#487 review batches


## 🖼️ System diagram card: explicit `entities:` config (#455)

- **`sem-system-diagram-card` now accepts the same `entities:` map as `sem-flow-card`** — point the illustrated diagram at any HA install's sensors (combined or split battery/grid sensors, `reverse`/`invert` flags, optional explicit home sensor instead of the derived balance). `entity_prefix` stays the default and wins when both are set, so existing dashboards are untouched (#455)
- In entities mode, intentionally unmapped nodes (e.g. no EV) no longer count toward the "sensor unavailable" warning
- Schema documented for both cards in `DASHBOARD_GUIDE.md`

## ☀️ `min_plus_solar` daytime is self-consumption-maximizing again (#501)

Daytime `min_plus_solar` in battery Zone 3/4 was draining the home battery into the EV and importing from the grid when it should maximize self-consumption — a cloudy afternoon at 70–90% SOC got ground into the car.

- **The daytime min-current floor is now need-gated** — it engages only when the remaining daily Min can no longer be delivered by tonight's charging window (new per-charger `night_deliverable_kwh`). Otherwise daytime is pure surplus + capped battery assist, and idles below the charger minimum. Restores the documented "Min comes from the night top-up, not a forced grid pull at noon" promise; `always_max` stays the "just charge" escape hatch (#501)
- **One shared, capped battery-assist formula** — `decide` and `flow_calculator` had diverged (ADR 0002 regression); both now use the same SOC-based *potential* (capped by `battery_assist_max_power`, zeroed below the assist-floor SOC, bounded to the surplus→min gap). No more measured-discharge branch, so a home-load spike can't ratchet the EV current upward, and #439's chicken-and-egg stays structurally fixed (#501)
- Amends ADR 0010 pattern 1; `EV_CHARGING_LOGIC.md` mode table corrected

## 🙏 Contributors

Backlog sweep after the beta.12 retest round — four audited issues (#416, #455, #476, #501) closed end-to-end. Thanks to @RienduPre for the reports and reviews that surfaced the charging and dashboard gaps.

# [1.7.3-beta.12] - 12.06.2026

## 🎨 Plan-strip legend always-visible + tariff colours (#464 follow-up)

- **The full plan-strip legend is now always shown** — no need to open the `?` help. The four bar states (idle / waiting / charging / done) plus the two tariff-window colours (cheap / peak), which previously were only explained behind `?`, are all labelled inline; swatches enlarged and text contrast raised (reported by @RienduPre in #464)
- **Cheap-tariff colour split from the charging green** — the cheap-tariff overlay used the same `#8DC892` as the "charging" segment; it's now a distinct deeper green and the tariff entries render as thin lines, mirroring how they appear on the strip's top edge (reported by @RienduPre in #464)

# [1.7.3-beta.11] - 12.06.2026

## ⚡ Surplus start/stop flapping: enable/disable delays reconnected (#461)

The v1.7 `decide() → actuate()` rewrite silently orphaned the v1.7.1-beta.14 stability layer: `ev_enable_delay_seconds` / `ev_disable_delay_seconds` still existed as config keys but were only read by the legacy `_execute_ev_control` path the new pipeline no longer calls. Result in RienduPre's beta.10 logs: solar hovering around the 6 A minimum cycled the contactor every ~20 s (±4.5 kW demand swings between consecutive health-check lines).

- **The delays are enforced again** — a new `charge_stability` filter sits between `decide()` and `actuate()` in both pipeline branches: a surplus charge only **starts** after the surplus has held for `ev_enable_delay_seconds` (default 60 s), and only **stops** after the deficit has persisted `ev_disable_delay_seconds` (default 300 s), holding minimum current meanwhile. Applied before state display, so the strategy sensor names the active hold instead of contradicting the measured power
- **Stop semantics upgraded to evcc's deficit-persistence** ([evcc-io/evcc](https://github.com/evcc-io/evcc) `enable.delay`/`disable.delay`) — the legacy implementation measured from session start (a minimum-run-time), so a session older than the window still died on a single-cycle cloud dip. The deficit timer protects the contactor for the whole session
- **Night floors, `always_max`, OFF/DISABLE and unplugs are never delayed** — safety and user-intent transitions bypass the filter; timers are independent per charger
- **Both settings are now real entities** (`number.sem_ev_enable_delay_seconds` / `number.sem_ev_disable_delay_seconds`) on the Config tab's **Advanced** section with ?-help texts — previously they were raw config keys with no UI surface
- **Mid-session setpoint smoothing restored too** — the same rewrite orphaned Layers 1-3 + the ramp limiter, so the commanded current bounced cycle-by-cycle until some cars declared the supply unreliable and ended the session themselves. The filter now median-smooths the target stream (`ev_surplus_smooth_window`, 3 cycles — a 1-cycle inverter flicker never reaches the car), moves at most `ev_ramp_rate_amps` (2 A) per change, suppresses sub-`ev_min_change_amps` changes, allows one change per `ev_min_change_interval_sec` (30 s), starts sessions gently at minimum current (the 2026-05-31 grid-overshoot fix), and ramps down to minimum instead of jumping during the disable hold

## 🗓️ Per-charger plan strip + help text (#464)

RienduPre's follow-up: "why is this bar the same for both chargers, and what is it for?" The bar is the 12-hour plan strip (#282) — and it was identical because only one fleet-level plan existed, composed from the primary charger's night plan/target/deadline, then rendered inside every charger section.

- **Each charger now gets its own plan** — `today_plan` is composed per charger from ITS night plan, target, deadline, charge mode and live-session ETA; surfaced as `per_charger_plans` on `sensor.sem_charging_state` (fleet `today_plan` stays the primary's plan for the Today-plan card and as the card-side fallback) (reported by @RienduPre in #464)
- **Stale night plans can no longer leak into day plans** — the per-charger night-plan map was write-only and never cleared; it now resets every cycle
- **The strip explains itself** — it has a title ("Today's plan · next 12 h") and, with the card's ?-help toggle on, a legend explanation (grey = idle, purple = waiting for a cheaper hour, green = charging, teal = target reached; the thin top line marks cheap/expensive tariff windows). Translated in all 15 languages; bar slightly taller and the legend more legible
- **Waiting-for-cheap is read per charger** — the strip derives the wait state from its own charger's plan rows instead of the primary-scoped `ev_tariff_waiting` attribute

## 🧪 Health-check & strategy-label triage from the #461 beta.10 dump

RienduPre's 2026-06-12 dump showed the flows finally coherent, but 69 "Energy balance" violations and a `charging_strategy` claiming `solar_only` on chargers configured `solar_plus_cheap`.

- **Energy-balance "violations" during the home-consumption hold are demoted to debug** — `home_consumption_power` is derived as the residual of the other readings, so supply≈demand is an identity; a gap can only appear when the residual went negative (one input sensor stale, e.g. a Growatt solar reading frozen for ~5 min) and the #237/#444 hold bridged it. Those cycles re-reported a known, already-handled inconsistency every 10 s and inflated `diag_health_violations`. A gap that *outlives* the hold window still warns, now naming the likely cause (stale power sensor) (reported by @RienduPre in #461)
- **Delegated day strategies keep their configured mode label** — `solar_plus_cheap` (day, normal/cheap tariff) and `min_plus_solar` (day, Zone 2) delegate to the solar_only math but no longer report `mode="solar_only"`/`"solar_only: …"` verbatim; the strategy string now reads `solar_plus_cheap day: tariff=normal — solar_only: …`, so the Config card's mode and the live strategy can't appear to contradict each other (reported by @RienduPre in #461)

## 🎨 Dashboard typography, spacing & mobile fixes (#498)

- **Minimum text size raised across all cards** — 11px floor for regular text, 10px for uppercase micro-labels (was down to 9px); fractional sizes normalized; em-based charger labels 0.7/0.75em → 0.8em, hierarchy preserved (by @traktore-org in #500)
- **Hero card padding aligned** — system, home-status and solar-summary now share the same `16px 20px` container padding as the other hero cards; cramped metric-row paddings normalized (by @traktore-org in #500)
- **Mobile fixes from viewport testing** — `sem-tab-header` wraps instead of crushing the title to zero width on phones; `sem-battery-zones-card` clamps zone markers to 0–100% so an out-of-range sensor can't stretch the card; `sem-schedule-card` SVG labels bumped for legibility (by @traktore-org in #500)

## 💶 Cost/ROI: battery savings + volume-weighted tariff history (#499)

- **Battery discharge savings now count toward lifetime ROI** — the midnight snapshot accumulates `cost_batt_savings` into a persisted `_accumulated_battery_savings` folded into `lifetime_total_savings`; the pre-SEM solar-through-battery share already inside `lifetime_self_consumed` is deliberately not re-estimated (no double-count, pinned by a regression test) (by @traktore-org in #500)
- **Dynamic-tariff rate history is volume-weighted** — snapshots store the day's `cost ÷ kWh` instead of the midnight rate (systematically among the cheapest spot hours), removing the low bias in the 7-day average used for the pre-SEM ROI estimate; falls back to the current rate on days without positive cost data (by @traktore-org in #500)
- **Negative-price consistency** — battery savings clamped `max(0, …)` at daily/monthly/yearly read, matching solar savings (by @traktore-org in #500)

---

# [1.7.3-beta.10] - 11.06.2026

## 💶 Tibber Grid Reward price arrays (#491)

Tibber Pulse accounts where the core Tibber integration provisions no `electricity_price` forecast sensor (upstream core#153312) get their only day-ahead curve from the HACS [tibber_grid_reward](https://github.com/JohNan/homeassistant-tibber_grid_rewards) `sensor.current_price`.

- **`today_raw` / `tomorrow_raw` price arrays are now parsed** — the `{time, price}` item keys were already known; only the two attribute names were missing. Configure the sensor via *Tariff settings → Dynamic tariff entity*; its id is too generic to auto-detect (reported by @RienduPre in #491, fixed in #495)
- The Grid Reward sensor's `today`/`tomorrow` attributes are comma-joined *strings* — skipped by the list guard, so the curve is never double-counted

## 🔋 Battery scheduler crash with saved options (#493)

- **Scheduler evaluation no longer dies on every cycle for users who ever saved the battery-scheduler options page** — the options-flow slider stores the trigger hour as a float (`21.0`) and `datetime.replace(hour=21.0)` raised `TypeError`, killing nightly planning entirely; trigger hour/minute are now coerced (`int(float(...))`, surviving string-shaped storage too). Untouched configs keep the int default, which is why soaks missed it (reported by @RienduPre on #487, fixed in #496)

---

# [1.7.3-beta.9] - 11.06.2026

## 🔌 Wallbox actuation: entity-range bounds + working stop path (#487)

RienduPre's error log exposed the real "keeps charging in off mode" mechanism: SEM wrote 0 A (stop) and >entity-max amps to the Wallbox max-current number entity — HA core rejects both with `out_of_range` **before anything reaches the charger** (167× per charger in the log).

- **Current writes are bounded into the target entity's own min/max** — a charger whose entity allows 6–16 A gets 16 A when SEM wants 32, instead of a rejected command (by @traktore-org in #490)
- **0 A stop intents skip the structurally impossible number write** — the stop goes through the adapter's pause-switch / stop_session path (Wallbox min=6 A, IEC 61851)
- **`ev_start_stop_entity` is now actually honored** as the Wallbox pause/resume switch — the adapter's own WARNING recommended it as the workaround but never read the field (RienduPre's #462 finding)
- **Health-check violation WARNINGs are rate-limited** — after 6 consecutive violating cycles they drop to debug until they clear (413 identical lines flooded the log + the diagnose ring buffer)

## 🧭 Grid-sign restart hardening (live PROD flip, #487 follow-up)

A restart locked `grid_sign_inverted=True` on a Huawei install whose convention needs NO correction — 3 sign votes cast while HA's recorder was still replaying counter states (#476 items 5/6 gap, observed live 2026-06-11).

- **Sign votes are ignored for the first 12 cycles after startup** (~2 min) — baselines stay fresh, nothing locks
- **The sign-lock log line now names the voting counter entities**, so a wrong lock is diagnosable after the fact

## 🖼️ Diagram card blank on Home tab (#488)

- **Backticks inside a lit-template HTML comment terminated the template literal** — the remainder re-parsed as a tagged-template chain: syntactically valid JS (rollup/CI green) that threw at render time, blanking the system diagram. Fixed + a lint test forbidding backticks in card-template comments (by @traktore-org in #489)

## 🔍 Pre-stable review batch (#485)

A full 7-angle review of everything on develop since v1.7.2 surfaced 23 verified findings — two of them stable-release blockers in this release's headline features. All fixed in one batch.

### 🚨 Blockers

- **Rolling-horizon scheduler no longer ratchets the charge target** — `evaluate()` re-anchored the target on the live SOC every 30-min re-plan, stacking the deficit on top of charging progress until the battery grid-charged to ~95% every profitable night. The target is now anchored on the SOC at the first evaluation of the night's window, and a mid-charge re-evaluation that lands on NOT_NEEDED/NOT_PROFITABLE stops the active forced charge (by @traktore-org in #485)
- **`set_option` on construction-time keys reloads again** — keys like `tariff_mode` and the `battery_*` scheduler params persisted + mirrored into a config dict nothing re-reads, so the live Config-card select "succeeded" while the constructed provider/scheduler kept the old value until restart (the #462 silent-no-op class) (by @traktore-org in #485)

### 🛠️ Fixes

- **Re-plan trigger fires once per price update** — day-ahead prices publishing ~13:00 used to log two INFO lines every ~10 s cycle until the 21:00 window opened (thousands/day), evicting everything useful from the 300-line diagnose ring buffer built for #461/#462 triage
- **15-min markets: slot length comes from the provider** — gap inference over *selected* slots booked 2–4× oversized slots for scattered selections, corrupting the night plan's energy accounting
- **`battery_cycle_cost` runtime default back to 0.0** — the silent 0.0→0.02 flip tightened the break-even on upgrade and stopped thin-margin night charging with no config change; 0.02 stays as the *visible* form default for new configs
- **Nord Pool fetch failure backoff** — an API outage used to trigger two blocking service calls every cycle (~17k/day); failures now back off 5 minutes
- **`_merge_ev_chargers_by_id` preserves charger order** — a partial submit (or the setup heal) could reorder the fleet, silently swapping the index-0 primary and default surplus priorities
- **set_option mixed payloads are atomic** — tunables route through entities first, then ONE direct write + ONE reload (the structural write used to fire a listener reload racing the still-running tunable calls, dropping values mid-payload)
- **set_option switch routing coerces YAML strings** — `"off"`/`"false"`/`"0"` were truthy and turned the switch ON
- **Split-grid: a late-loading export sensor now completes a one-sided pick** — including the same-device case that blocked re-discovery until restart; the held import side is never re-rolled
- **Dual-tariff auto sign vote** — `_detect_grid_sign` sums the NL DSMR tarief-1/2 counter lists (beta.8 fixed only the manual-audit path)
- **Deterministic split-grid discovery** — candidates scan sorted by entity_id, so import/export roles can't re-roll across restarts
- **Stale actuation Repair clears after a reload** — the persistent ERROR Repair raised before a config fix stayed in the UI forever because the new device instance's flags started fresh
- **Canonical primary-charger id** — the fleet-strategy gate's `"ev_charger"` fallback disagreed with registration's `"ev_charger_0"` for id-less chargers, freezing the strategy sensor on exactly the corrupted configs this release hardens against
- **Entity-domain charger services generalized** — `input_number.set_value` / `select.select_option` configured as the charger service bounced off their schemas exactly like the beta.8 `number.set_value` case
- **Configured 0.0 electricity rates are respected** — `config.get(...) or 0.30` treated a real zero rate as missing
- **Reload-skip snapshots expire after 60 s** — a lingering snapshot could swallow a legitimate reload on a future data/title-only entry update

### ⚡ Performance

- **Price curve parse memoized** — the full parse (isoformat + classify + sort + dedupe) ran 3–5× per coordinator cycle; now keyed on entity-state identity + service-fetch timestamp + percentile slot epoch
- **Split-grid sensor scan throttled** — with healthy two-sided picks held, the full `hass.states` scan runs every 30 cycles instead of per cycle with the result discarded; the per-cycle INFO log only fires when the result changes

### 🧹 Cleanup

- `persist_per_charger_option()` — single write path replaces the ~30-line copies in select/number/time (the time.py copy was the writer #469 missed); `_saveChargerField` dedups the config-card's nested editors; `semFormatTime` unifies the dashboard's two clashing time formats; tariff auto-detect shares the provider's candidate matcher (the flow missed Octopus/Amber); dead `_set_option_needs_reload` helper removed; shared `_counter_deltas` reset guard for the three sign voters

### 🧪 Tests

- ~60 new tests: target-SOC anchor + mid-charge stop, replan one-shot, slot-hours hint, fetch backoff, parse memo, falsy-zero rates, merge order contract, switch coercion, unrouted-key reload (real-hass), late-export adoption, scan throttle, dual-tariff vote, deterministic discovery, entity-domain service routing, stale-Repair clear, primary-charger id contract

---

# [1.7.3-beta.8] - 10.06.2026

## 🔌 Actuation hardening + triage surfaces (#462 follow-up batch)

RienduPre's attached error log revealed the final #462 mechanism: with `ev_charger_service: number.set_value`, SEM sent `{current: X}` through the service path — `number.set_value` only accepts `value`, so **every current command on both chargers failed** (`extra keys not allowed @ data['current']`), including the 0 A for off-mode, with the evidence buried in per-cycle ERROR log lines.

### 🛠️ Fixes

- **`number.set_value` as charger service is now mapped to the number-entity write it was meant to be** (`value` + entity_id) — the misconfigured-but-recoverable shape can no longer leave a charger silently uncontrollable
- **Repair issue on repeated actuation failure**: 3 consecutive rejected set-current commands raise a user-visible Repair naming the charger and the error (severity ERROR, translated EN/NL/DE + EN fallback for the rest); clears automatically on the next successful write
- **Registration WARNING** when `ev_charger_service=number.set_value` has no `number.*` target entity
- **Fleet `charging_strategy` / `charging_strategy_reason` are now consistent** — the per-charger loop let the *last* charger overwrite `charging_strategy` while `charging_strategy_reason` kept the primary's value ("always_max …" next to "off mode …" in the same dump); only the primary charger writes both now (per-charger detail lives in `charger_<id>_charging_state`)

### 🔍 Triage surfaces

- **In-memory SEM log ring buffer** — the diagnose payload's `recent_logs` now carries the last ~300 INFO+ SEM log lines on EVERY install type; Supervisor installs (journald, no flat log file) previously got a "please run `ha core logs`" placeholder, which left the whole #461/#462 triage blind
- **Manual-grid audit is dual-tariff aware** — the sign cross-check sums the import/export counter *lists*, so NL DSMR tarief-1/2 splits no longer blind it during one tariff's hours
- **Blocking `open()` calls removed from the event loop** ("Detected blocking call" in RienduPre's log): translations and the manifest version are warmed off-loop at setup and cached (`diag_version` no longer re-opens manifest.json every cycle)
- TROUBLESHOOTING: manual grid entity checklist (import vs export roles, power-not-energy, both-or-neither) + Dutch dual-tariff Energy-Dashboard guidance

### 🧪 Tests

- New framework tier `tests/test_actuation_real.py`: real-HA schema-strict `number.set_value` shape test + the failure → Repair → recovery → clear cycle through the real issue registry
- `test_services_real.py`: diagnose `recent_logs` served from the ring buffer (Supervisor parity) + cached version
- Unit: actuation routing/param contracts, Repair threshold/idempotence/intermittent-flap behavior, log-buffer capture/capacity/idempotence, dual-tariff audit summing

---

# [1.7.3-beta.7] - 10.06.2026

## 🔎 Manual grid override validation + sign audit (#461 follow-up)

v1.7.3-beta.6's pick-stability fix addressed the auto-discovery path — but an install with `grid_import_power_entity` / `grid_export_power_entity` set explicitly bypasses ALL sign machinery, so a swapped, one-sided, or wrong-kind (energy counter as power sensor) configuration produces a statically inverted grid with zero feedback. Exactly the verified #461 shape: explicit entities configured, no discovery log lines, grid shows export while importing, house consumption 0, surplus invisible to every controller.

### 🛠️ Fixes

- **Manual grid config validation** (warn-once): an ENERGY counter (kWh) configured in a POWER field; only one side configured while the Energy Dashboard tracks both flows (the missing side reads a hard 0 W — "always exporting")
- **Observe-only sign audit**: the manual-computed grid sign is cross-checked against the Energy Dashboard import/export counters every cycle; 5 consecutive contradictions log a WARNING naming both configured entities ("most likely SWAPPED") and set `diag_grid_manual_mismatch` in the diagnostics — SEM never silently overrides manual config, it makes the misconfiguration loud
- Counter-reset and ambiguous-delta cycles are excluded from the audit (same guards as the autodetect path)

## 🧰 Robustness batch (#476, part 1)

Soundness/stability items from the 2026-06-10 review. No behavior changes on the happy path.

### 🛠️ Fixes

- **Back-to-back runtime writes no longer trigger a spurious reload** — the options-update listener consumed the `_skip_options_reload` snapshot on first match, so the second of two quick entity writes found no snapshot and reloaded the integration. Snapshot is now kept on match and cleared on mismatch — provably leak-free (HA only fires the listener when options actually change)
- **Energy-counter reset guard** — Growatt-style daily counters can reset at midnight in *different* update cycles; the surviving side's increment could cast a wrong grid/battery sign vote. Negative delta on either side now re-baselines and skips the vote (grid + per-battery variants)
- **`set_option` mixed payloads** — the skip snapshot is no longer armed when structural keys force a reload anyway (stale state on a discarded coordinator)
- **Charger-id sanity at registration** — WARNING on id-less entries (positional fallback can collide with a real sibling) and on duplicate ids (writes target only the first match)
- **Config card**: per-charger rows with no resolvable id are skipped instead of rendering `…_undefined_…` entity lookups; save-status timers cancelled on disconnect (same for the diagnose button's copy timer)

### 📝 Notes

- Heal-vs-auto-discovery ordering documented as intentionally heal-first (prevents the reseed from firing on heal-able installs)
- Deliberately deferred from #476: sign-state persistence (persisting a wrongly-locked sign would make bad locks permanent — needs a validation design first) and vote-threshold changes (3-vote lock-in is pinned as contract by the #352 test suite; the dominant reset windows are already closed)

---

# [1.7.3-beta.6] - 10.06.2026

## 🩹 2026-06-10 review fixes — P1 batch

Top findings from the full-codebase review (the unfixed remainder is tracked in #475 / #476):

### 🛠️ Bug fixes

- **#461 root cause: split-grid pick stability** — any-device split-grid discovery re-ran every cycle and adopted the result unconditionally, so a flicker in HA's state-list iteration order could swap which sensor plays import vs export, inverting the computed `grid_power` sign ("sometimes works, sometimes inverted", Growatt). New adoption gate: held picks win unless there's no pick yet, the new match is a same-device upgrade, or a held pick went unavailable. Late-loading DSMR discovery (#166) preserved
- **`time.py` per-charger writer hardened** — the deadline writer was missed by the #469 patch round: it still clobbered `ev_chargers` to `[]` when options lacked the key, and silently no-op'd on a partial list. Now identical to the select.py / number.py contract (data fallback + recovery-append + WARNING)
- **`sem-chart-card` empty-state crash (second instance of the #457 class)** — the card lit-bound `${this._t('loading')}` AND overwrote the same node via `.textContent` in `_showEmpty()`, destroying lit's text part so the next `requestUpdate()` threw and froze the card. Empty-state and canvas visibility are now fully lit-rendered (bundle rebuilt)

### 🧪 Tests

- `TestSplitGridPickStability` (4 tests): flipped re-discovery is not adopted; same-device upgrade is; unavailable pick reopens adoption; late-loading meter still discovered
- `time.py` recovery + data-fallback contract tests in `test_ev_chargers_storage_heal.py`

---

# [1.7.3-beta.5] - 10.06.2026

## 🩹 Storage heal for poisoned `options.ev_chargers` (#462/#464 follow-up #3)

The writer fixes shipped in beta.1–beta.4 (#467/#468/#469 + the smart-merge
fall-through) stopped **new** corruption of the options-side charger list, but
none of them repaired storage that the v1.7.2 .. v1.7.3-beta.3 builds had
already corrupted. Once `entry.options.ev_chargers` is a *partial* list
(e.g. charger 1 only — the auto-discovery reseed plants exactly that shape
after a `[]` clobber), the `{**data, **options}` merge hides the data-side
sibling forever and every per-charger write targeting the missing id
silently no-ops: the persistent "changing charger 2 does nothing at all"
report on #462/#464 that survived all three betas. The #469 `or`-fallback
only fires for missing/empty lists, not partial ones.

### 🛠️ Bug fixes

- **Setup-time storage heal** — `async_setup_entry` reconciles a poisoned `options.ev_chargers` against `entry.data` by id-union (options fields win per charger, data-only siblings restored, id-less ghost entries dropped). Idempotent: one healing write, then quiet. Logs a WARNING naming the before/after ids so support can see it happened
- **Per-charger writers never silently no-op** — `SEMPerChargerSelect.async_select_option` / `SEMPerChargerNumber.async_set_native_value` recover a charger missing from the stored list out of `entry.data` (full dict, or a minimal `{"id": ...}` stub) and append it, with a WARNING — instead of dropping the write on the floor
- **`_merge_ev_chargers_by_id` drops id-less entries** — they're untargetable by every write path and at registration get assigned a positional `ev_charger_<idx>` id that can collide with a real sibling (ghost charger)
- **Config card stamps the charger `id`** — the nested per-charger editors (`sem-config-card.js`) now always carry `id` on the entries they submit, so a partial submit can never produce an id-less ghost

### 🔍 Diagnostics

- `diagnose` payload for the `ev_chargers` (and `all`) section now includes `ev_chargers_storage_split` — the per-side `entry.data` vs `entry.options` charger lists (id / name / charge_mode). The merged `config` block hid exactly the fact that mattered during the #462/#464 triage

### 🧪 Tests

- `tests/test_ev_chargers_storage_heal.py` — heal contract, writer recovery (select + number), ghost-drop contract
- `tests/test_services_real.py::test_setup_heals_poisoned_options_ev_chargers` — real-HA boot with RienduPre-shaped poisoned storage: asserts the options list heals, charger 2 registers, and a charger-2 mode flip lands

---

# [1.7.3-beta.4] - 09.06.2026

## 🧪 Framework tests + caught third instance of #469 fall-through

While writing the real-HA integration tests for the `set_option` service path, the test against `sem_multi_wallbox_config_entry` (a fresh-install fixture with chargers only in `entry.data`) caught the **same `entry.options.get("ev_chargers", [])` fall-through pattern** PR #469 fixed for the per-charger setters — but this time in the `__init__.py` smart-merge itself. A fresh-install multi-charger user opening the Config card for the first time and editing one charger's field would hit it: the merge appends the partial submit as a stray entry (no matching id in the empty existing list) and the next reload clobbers `entry.data.ev_chargers` with the partial-options-side list. Same symptom as #464 but on the fresh-install path — patched in the same PR as the test that caught it.

### 🛠️ Bug fix

- **#464 follow-up #2** `set_option` smart-merge falls back to `entry.data.ev_chargers` when `entry.options` doesn't have the key. Latent since v1.7.2-beta.2 (`set_option` rework). Affected: fresh-install multi-charger users editing per-charger fields via the Config card before any prior write had populated `entry.options.ev_chargers` (by @traktore-org in [#471](https://github.com/traktore-org/sem-community/pull/471))

### 🧪 Test infrastructure

- `tests/test_services_real.py` — four real-HA integration tests that drive `solar_energy_management.set_option` through the service registry and assert on `hass.states.get(...).state`. The test layer that would have caught the v1.7.3-beta.1 number-entity staleness regression (by @traktore-org in [#471](https://github.com/traktore-org/sem-community/pull/471))
- `sem_multi_wallbox_config_entry` fixture — seeded from RienduPre's diagnose dump, reusable for any multi-charger contract test (by @traktore-org in [#471](https://github.com/traktore-org/sem-community/pull/471))
- `sem_config_entry` fixture bumped from schema v7 → v12.1 (stale since the #135 v11→v12 migration) (by @traktore-org in [#471](https://github.com/traktore-org/sem-community/pull/471))
- `tests/scenarios/2026-06-09_rienduPre_dual_wallbox.yaml` — YAML scenario replay of RienduPre's dual-Wallbox setup running through the existing scenario harness; locks the `solar_plus_cheap`-outside-cheap-window mode-isolation contract (by @traktore-org in [#472](https://github.com/traktore-org/sem-community/pull/472))

### 🩹 Process retirement

The `[live-test-before-deploy]` policy memo from earlier today is now backed by a mechanical CI gate via `test_services_real.py`. Future PRs touching `__init__.py` / `select.py` / `number.py` set_option paths have the same green-or-red signal pytest already gives for pure-helper bugs.

---

# [1.7.3-beta.3] - 09.06.2026

## 🛠️ Per-charger options-fallback fix (#464 follow-up)

Follow-up to v1.7.3-beta.2 for the **asymmetric multi-charger symptom** RienduPre reported under #464 — *"change on charger 1 works, change on charger 2 does nothing"*. Investigation of his diagnostic dump traced the asymmetry to a latent bug in **both** per-charger setters:

```python
# select.py:async_select_option  and  number.py:async_set_native_value
new_options = {**self._entry.options}
ev_chargers = [dict(c) for c in new_options.get("ev_chargers", [])]   # ← [] when missing
for charger in ev_chargers:                                            # ← iterates nothing
    if charger.get("id") == self._charger_id:
        charger[self._config_key] = value
        break
new_options["ev_chargers"] = ev_chargers                               # ← writes [] back
```

When `entry.options.ev_chargers` doesn't exist (fresh install where the user has never opened the Config card), the setter writes `entry.options["ev_chargers"] = []`. On the next reload, the merge `{**entry.data, **entry.options}` overrides the data-side chargers with the empty options-side list — **every charger disappears**, all per-charger entities go unavailable. Latent since the multi-charger arc landed.

### 🛠️ Bug fix

- **#464 follow-up** Per-charger select + number setters now fall back to `entry.data.ev_chargers` when `entry.options` doesn't have the key (by @traktore-org in [#469](https://github.com/traktore-org/sem-community/pull/469))

### 🙏 Thanks

- **@RienduPre** for the full diagnose dump on v1.7.3-beta.1 — without it the asymmetric pattern would have stayed buried.

---

# [1.7.3-beta.2] - 09.06.2026

## 🩺 RienduPre v1.7.2 bug-response release

> v1.7.3-beta.1 was tagged and immediately retracted today — live HA-TEST verification (post-merge, pre-soak) caught that the skip-reload optimization left number entities stale at their old value after `set_option`. The full pytest suite was green but mocks don't model HA's entity lifecycle. Hotfix in [#468](https://github.com/traktore-org/sem-community/pull/468) routes tunable changes through each entity's own write path, which updates `_attr_native_value` + writes state synchronously. The post-incident `[live-test-before-deploy]` memory was added so backend changes touching HA's config-entry / entity-state pipeline now require live entity-state verification BEFORE merge, not just pytest.

Four bug reports landed on v1.7.2 within five hours this morning ([#460](https://github.com/traktore-org/sem-community/issues/460), [#461](https://github.com/traktore-org/sem-community/issues/461), [#462](https://github.com/traktore-org/sem-community/issues/462), [#464](https://github.com/traktore-org/sem-community/issues/464)) — all from the same reporter on the same install. Root-cause analysis traced the three logic bugs to a single change in v1.7.2-beta.2: the `set_option` service was switched to always-reload the integration so heat-pump entity rewires (#448) would take effect. Side effect was that every Config-card tunable tweak destroyed the SensorReader's split-grid discovery state and the per-charger context across the multi-charger loop — the candidate root cause for all three logic bugs. The fix scopes the reload to structural keys only, routes tunables through their matching entity's write path, and adds smart-merge for `ev_chargers` to prevent partial submits from dropping sibling chargers.

Also unblocks #453 by structurally fixing #457 in the same release: the diagram card was the one card in the bundle that mixed Lit declarative bindings with imperative DOM mutation on the same node, crashing `requestUpdate()` whenever late translations triggered a re-render. Pure-reactive rewrite brings it in line with the other 21 bundled cards.

### 🛠️ Bug fixes

- **#457** Diagram card pure-reactive rewrite — eliminates the lit-html `TypeError: Cannot set properties of null` crash on `requestUpdate()`. Source -202 LOC, zero imperative writes on lit-bound nodes (by @traktore-org in [#459](https://github.com/traktore-org/sem-community/pull/459))
- **#453** Single-channel sem-localize delivery — drops the dual-channel `add_extra_js_url` hack that masked #457 (by @traktore-org in [#463](https://github.com/traktore-org/sem-community/pull/463))
- **#460** Clipboard copy works on plain-HTTP installs — execCommand fallback for `navigator.clipboard` (which requires HTTPS / localhost), pattern mirrors `sem-system-card._writeClipboard` from #285 (by @traktore-org in [#465](https://github.com/traktore-org/sem-community/pull/465))
- **#462 / #464** `set_option` service: smart-merge `ev_chargers` by id (so a partial Config-card submit can never drop sibling chargers) + scope reload to structural entity-wiring keys only + route tunable changes through each entity's own write path (`number.set_value` / `switch.turn_on/off` / `select.select_option`), so the entity state refreshes synchronously without reloading the integration. Pure-function helpers extracted to module scope with 20 contract tests. Strong candidate fix for #461 too (eliminates the reload-driven split-grid re-discovery) (by @traktore-org in [#467](https://github.com/traktore-org/sem-community/pull/467) + hotfix [#468](https://github.com/traktore-org/sem-community/pull/468))

### 🩺 Defensive instrumentation

- Charger entity-id validation at registration — logs WARNING when configured `ev_charging_power_sensor` / `ev_current_control_entity` / `ev_charger_service_entity_id` / `ev_start_stop_entity` / `ev_charge_mode_entity` no longer exist in HA's state registry. Catches the historical bug class (#315 KEBA, #357 Wallbox) where HA-integration upgrades silently rename entities (by @traktore-org in [#466](https://github.com/traktore-org/sem-community/pull/466))
- Wallbox pause-switch discovery surfaces a WARNING when no `switch.*pause_resume` is found on the device — explains the exact consequence (generic `set_current(0)` fallback, which some Wallbox firmware latches per #357) and the workaround (by @traktore-org in [#466](https://github.com/traktore-org/sem-community/pull/466))
- Split-grid sensor change-detection logs WARNING with before→after IDs when the discovered import/export sensors change between cycles. Surfaces the "any-device" confidence flip behind #461 (by @traktore-org in [#466](https://github.com/traktore-org/sem-community/pull/466))

### 🌐 i18n

- Dutch translation update for the new configuration strings, contributed by the affected reporter (by @RienduPre in [#458](https://github.com/traktore-org/sem-community/pull/458))

### 🙏 Thanks

- **@RienduPre** for the four detailed bug reports with video evidence and for the Dutch translation contribution while we were debugging his install.

---

# [1.7.2] - 08.06.2026

## 🎉 Stable Release

_Consolidates [1.7.2-beta.1](https://github.com/traktore-org/sem-community/releases/tag/v1.7.2-beta.1) through [1.7.2-beta.7](https://github.com/traktore-org/sem-community/releases/tag/v1.7.2-beta.7). 19 commits since [1.7.1](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1). 24 hours of HA-PROD soak with zero errors._

### 🔥 New: Hot Water boiler control (#454)

The `HotWaterController` class existed from day one but was never instantiated — setting `hot_water_entity` in the Config tab Hot Water section did nothing at runtime. This release closes that gap end-to-end:

- Registration in setup mirrors the heat-pump pattern (entity + temp sensor + targets + Legionella interval + priority).
- Live runtime state (`hot_water_current_temperature`, `hours_since_legionella`, the 5 `_last_*_path` audit recorders from #420) populated every cycle into `coordinator.data`.
- Live-status block on the Hot Water section shows current temp, Legionella tracking, and decision paths when the controller is registered.
- Two Repair issues fire when configured entities go unavailable: `hot_water_entity_unavailable` (boiler control) and `hot_water_temperature_sensor_unavailable` (with #420 fail-safe semantics — boiler is NOT activated on surplus when the temp sensor is broken).
- Orphan-repair sweep handles user reconfiguring the boiler entity.
- Diagnose modal surfaces the full state via `_DIAGNOSE_HOT_WATER_STATE`.
- 7 new wire-up tests + 7 new repair tests. (by @traktore-org in #454)

### 🔥 New: Tariff price + 15-min provider support (Discussion #432)

The bottom-of-dashboard "Today's Schedule" tariff timeline was lying. Saturday on Tibber NL showed a solid "Goedkoop" bar for all 24 hours when the current price card next to it correctly showed "Normaal" at 0.31 EUR/kWh. Two unrelated code paths; one was misleading.

- **JS fallback no longer lies on weekends.** Mirrors the current `tariff_price_level` across the day with a dashed/translucent indicator showing "best-effort, not real per-hour data".
- **Parser accepts 15-min ENTSO-E + Tibber Pulse shapes.** Added `prices` (singular) attribute key + `time` / `hour` timestamp keys to the parser vocabulary. NL ENTSO-E users now get correct per-hour data SEM-side.
- **New diagnostic fields** on the Tariff diagnose surface: `tariff_parsed_attribute`, `tariff_parsed_count`, `tariff_parsed_interval_seconds`, `tariff_today_level_counts`, `tariff_today_first_price`, `tariff_today_last_price`. One Diagnose paste tells us in one read which failure mode hit (no parser match / timezone filter / genuinely-all-cheap / percentile-fallback). (by @traktore-org)

### 🩺 Heat-pump UX + diagnostics

- **Configuration tab subtitle now reflects actual registration state** — was reading `sensor.sem_heat_pump_registered` (doesn't exist) instead of `binary_sensor.sem_heat_pump_registered`. New `_bin()` helper fixes 3 use sites. RienduPre #448. (by @traktore-org)
- **Orphan heat-pump Repair issues now auto-clear** — repairs from a prior config (e.g. user switched from ESP relays to Modbus template switches) used to stay in the registry indefinitely. New sweep enumerates `heat_pump_relay{1,2}_unavailable_*` issues and clears any whose entity is no longer in current config. RienduPre #448. (by @traktore-org)
- **Heat-pump runtime path telemetry now visible** — the #421 audit shipped `_last_*_path` recorders in `v1.7.0-beta.24` but never wired them through to a user-visible surface. All 5 paths + current temperature now publish through `coordinator.data` into the Diagnose slicer.
- **Repair issues survive reload** — replaced in-memory `_raised` flag with idempotent always-raise/always-clear pattern. The flag was per-coordinator-instance, so reloads reset it, and stuck repairs never auto-cleared. Reported by RienduPre + caught in live testing.

### 🩺 Forecast write-time-weather fix (#416)

PROD telemetry on 2026-06-05 showed 42% of forecast records had `weather_category=unknown`. Root cause: weather was captured at day-rollover post-sunset when the entity is unreliable.

- **Eager weather snapshot** in `update()` — any daylight cycle with a non-unknown weather value updates the snapshot. The existing `blended_live` capture still wins on confident mid-day cycles.
- **Unknown-guard on the `blended_live` capture** — a transient `unknown` at noon no longer locks the day's record to unknown.
- **Defensive log formatting** — the day-record info log no longer crashes on `None` dampening factor.
- 3 new tests pin the gap-closing paths. (by @traktore-org in #416)

### 🩺 Hot-water fail-safe (#420)

`is_temperature_safe()` returned `True` whenever `get_current_temperature()` returned `None`. That conflated "no sensor configured" (trust thermostat) with "sensor configured but broken" (silent failure).

- Split the two paths via `_last_temperature_reading_path`: `no_source_configured` → `no_sensor_configured` → `True`; everything else → `configured_sensor_broken` → `False` (fail-safe). (by @traktore-org)
- 5 new tests pin the fixed branches. Closes #420.

### 🌐 Mobile sem-localize.js delivery

Beta.1 moved `sem-localize.js` from Lovelace resources onto `add_extra_js_url` only. Desktop browsers load both reliably; mobile Companion app does NOT. RienduPre #448: almost every translation key rendering raw on iOS.

- **Dual-channel registration**: now registered as BOTH an `add_extra_js_url` URL AND a Lovelace resource. Same hash-suffixed URL on both channels — browser fetches once. (by @traktore-org)
- **IIFE guard** in `sem-localize.js`: `(function() { if (window.semLocalize) return; ... })()` — defensive second load is a clean no-op.
- Follow-up architectural cleanup tracked in #453 (drop `add_extra_js_url` once `sem-localize-ready` event ergonomics are verified).

### 🩺 Per-section Diagnose surface

- Heat pump diagnose now exposes `heat_pump_activation_path`, `heat_pump_deactivation_path`, `heat_pump_relay_path`, `heat_pump_temperature_reading_path`, `heat_pump_offpeak_path`, `heat_pump_current_temperature`.
- Hot water diagnose now exposes 14 keys covering config + live state + #420 telemetry.
- Tariff diagnose now exposes parser-shape + per-hour distribution counts + first/last price (see Tariff section above).
- Modal opacity fix (beta.2) — was rendering at 6% opacity with cards bleeding through; now solid `--ha-card-background` with `backdrop-filter: blur(6px)`.

### 🐛 Other fixes

- `set_option` service now always reloads (was being swallowed by the skip-reload optimization for runtime stepper tweaks).
- KEBA session_energy pass-through (#449) — new `sensor.sem_charger_<id>_session_energy_external` surfaces the charger's own session counter alongside SEM's internal integration.
- Chart "Today" window now uses HA's timezone (#450) — was browser-local-midnight, drifted on TZ mismatch.
- 3 missing translation keys added (`charger_status`, `forecast_source`, `load_management_status`).
- Dutch translations for 5 new Repair issues (cherry-picked from RienduPre's PR #446 contribution).

### 📚 Docs

- `docs/SETUP_GUIDE.md` section 10 now has a dedicated "Hot water boiler (separate from heat pump)" subsection: config table, two operating modes (with/without temp sensor), fail-safe behaviour, Repair surfaces, and Diagnose troubleshooting.
- `docs/ARCHITECTURE.md` "SEM is not an integration" principle.

### Contributors

Thanks to **@RienduPre** for the persistent reporting on #448 + Discussion #432 — most of the fixes in this release came from his diagnose dumps + Dutch translation contribution.

### Verification

- **3273 tests pass**, 0 fail.
- 24h HA-PROD soak on `1.7.2-beta.7` — zero SEM errors, zero warnings, zero stuck Repairs.
- Live-tested every fix on HA-TEST: heat pump partial-SG-Ready scenario, hot water configure-and-clear flow, tariff parser with synthetic 15-min ENTSO-E sensor, orphan repair sweep with injected stale entry.

# [1.7.2-beta.7] - 08.06.2026

## 🧪 Beta Release

_#454 Phase 2-4: Hot water Repair issues + live-status block + translations + docs._

### 🩺 Hot water Repair issues

Two new self-diagnostic surfaces in Settings → System → Repairs:

- **`hot_water_entity_unavailable`** — fires when the configured boiler-control entity has been `unavailable` / `unknown` / missing for >5 min. SEM stops issuing on/off commands (they'd silently no-op anyway); the Repair surfaces the broken state with a clear "check the upstream integration" message. (by @traktore-org)
- **`hot_water_temperature_sensor_unavailable`** — distinct from the boiler Repair because the safety semantics differ. When a configured temp sensor breaks, `is_temperature_safe()` returns False (post-#420 fail-safe), which means SEM stops activating the boiler entirely. This Repair makes that visible to the user.

Both auto-clear when the entity recovers. Both use the idempotent always-raise/always-clear pattern (no in-memory flags — lesson from beta.2/5).

**Orphan sweep** (new function `clear_orphan_hot_water_repairs`): runs once per coordinator instance, enumerates all `hot_water_*_unavailable_*` issues in the registry, clears any whose entity is no longer in current config. Mirror of beta.5's heat-pump orphan sweep — handles the "user reconfigured the boiler entity, old Repair stuck forever" case.

7 new tests pin: per-Repair raise + clear, distinct issue ids, registry-error defensiveness, orphan sweep with reconfigured entity, orphan sweep with no config at all.

### 🩺 Live-status block on Config tab Hot Water section

Pre-wire-up the Hot Water section was config-only (entity pickers + sliders). Now when the controller IS registered, the section also shows live state:

- Current temperature (formatted to 1 decimal)
- Solar target
- Hours since the last Legionella cycle (or "Never run" / "Cycle running")
- `temperature_reading_path` (which source the controller is reading from: `separate_sensor`, `entity_attribute`, `no_source_configured`, etc.)
- `temperature_safety_path` (when something interesting — initial `uninitialized` hidden)
- `activation_path` (when SEM has actually activated the boiler at least once)

The path attributes surface the #420 audit's runtime telemetry directly in the UI — users can see WHY the boiler activated or didn't on the last cycle without opening the Diagnose modal.

### 🌍 Translations

- 7 new dashboard translation keys for the live-status labels (EN + DE polished; 13 other languages with EN fallback).
- 2 new Repair-issue translation keys in `strings.json` + propagated to all 15 language files. EN polished, DE + NL polished (NL credited to RienduPre's prior translation work).

### 📚 Docs

`docs/SETUP_GUIDE.md` section 10 now has a dedicated "Hot water boiler (separate from heat pump)" subsection covering:

- Config field reference table
- The two operating modes (with vs without temp sensor)
- What happens when the temp sensor breaks (fail-safe behaviour)
- What happens when the boiler-control entity breaks (Repair surfaces it)
- How to use the Diagnose surface for troubleshooting

3273 tests pass. **#454 closes with this release** — all 4 phases shipped:
1. Controller wire-up (beta.6)
2. Repair issues (beta.7)
3. Live-status block (beta.7)
4. Translations + docs (beta.7)

# [1.7.2-beta.6] - 08.06.2026

## 🧪 Beta Release

_Two follow-ups on top of beta.5: the Config tab subtitle bug from #448 + the HotWaterController wire-up (#454)._

### 🐛 Config tab subtitle bug (#448 follow-up)

Looking at RienduPre's diagnose dump, his heat pump IS registered (`registered_sg_ready` + `heat_pump_registered: true`). But the Config tab Heat Pump section subtitle showed "Not configured". Bug class: every card method that read `binary_sensor.sem_heat_pump_registered` was actually doing `_val('heat_pump_registered')` which prepends `sensor.sem_` — the lookup always returned an empty string because the entity is a *binary* sensor.

- New `_bin(suffix)` helper on `sem-config-card.js` reads from `binary_sensor.sem_<suffix>`. (by @traktore-org)
- Converted 3 prior `_val('heat_pump_registered') === 'on'` use sites: subtitle, overview chips bar, Setup overview body.
- Heat Pump section subtitle now correctly reads "configured" when the controller is registered.

### 🔥 HotWaterController is now actually instantiated in setup (#454)

The class existed in `devices/hot_water_controller.py` with full unit-test coverage, the Config tab Hot Water section collected settings, and the dashboard expected the live state — but **the controller was never instantiated**. Setting `hot_water_entity` did nothing at runtime; the boiler was never controlled.

This release closes that loop:

- **`__init__.py` registration block** mirrors the heat-pump pattern. When `hot_water_entity` is set, SEM instantiates `HotWaterController` with the saved options (entity, temp sensor, solar target, max temp, Legionella target/interval, min temp, priority, optional power sensor) and registers it with the `SurplusController`. (by @traktore-org)
- **`HotWaterSensorData`** new dataclass in `coordinator/types.py` with 14 fields covering registration state, current temperature, Legionella tracking, and all 5 `_last_*_path` telemetry recorders from the #420 audit.
- **`coordinator.py:_update_analytics_phases`** populates `hot_water_data` from the registered controller — `get_current_temperature()`, `hours_since_legionella`, the `_legionella_cycle_active` flag, and the runtime decision-branch paths.
- **`CoordinatorSensorData.to_dict()`** publishes all 14 keys into `coordinator.data` so the Diagnose modal + future UI surfaces can read them.
- **`_DIAGNOSE_HOT_WATER_STATE`** in the diagnose slicer now lists actual runtime keys instead of the prior placeholder. Hitting the 🩺 Diagnose button on the Hot Water section returns a payload with concrete state.
- 7 new tests pin: lazy-import presence, `register_device` call, gate keyed on `hot_water_entity`, dataclass field surface, default-unregistered state, `to_dict()` plumbing, diagnose slicer coverage.

**Live-tested on HA-TEST** with `input_boolean` boiler + temp-sensor stand-in: registration fired, temperature read OK (`temperature_reading_path: "separate_sensor"` per #420), all config + state surfaces populated in the diagnose dump.

3266 tests pass.

### What's still pending under #454

- **Repair issues** for boiler entity unavailable / temp sensor unavailable (mirror the heat-pump repair pattern). Not blocking the wire-up but improves the diagnostic surface.
- **Live-status block** on the Hot Water section in `sem-config-card.js` (currently only the intro shows when not configured; needs a registered-state body showing live temp + Legionella status).
- **Translations** for the new hot_water_* state keys + helper labels.
- **Docs**: `docs/USER_GUIDE.md` section + README "Supported devices".

These ship in follow-up betas — #454 stays open until they all land.

# [1.7.2-beta.5] - 08.06.2026

## 🧪 Beta Release

_Hotfix for stuck heat-pump Repair issues from prior config (RienduPre, #448)._

### 🐛 Orphan heat-pump relay repairs now auto-clear (#448)

RienduPre reported (2026-06-08, post-beta.4 upgrade): 2 stuck Repair issues for OLD entity names (`switch.zolder_comfoair_*`) that he'd long since replaced with new ones (`switch.bijkeuken_nibe_sg_ready_*`). The new entities work correctly + the heat pump IS registered (`registered_sg_ready` per his diagnose dump), but the old repairs stayed in the registry indefinitely.

Root cause: beta.2's per-cycle clear path only addresses CURRENTLY-configured entities. Repairs from prior config — whose entity_ids are no longer in `heat_pump_relay1_entity` / `heat_pump_relay2_entity` — were never enumerated, so they sat orphaned.

- **New `clear_orphan_heat_pump_relay_repairs()` sweep** in `coordinator/repair_issues.py`. Enumerates all `heat_pump_relay1_unavailable_*` and `heat_pump_relay2_unavailable_*` issues in the registry and clears any whose entity_id is NOT in the currently-configured set. (by @traktore-org)
- **One-time per coordinator instance** — runs in the heat-pump repair tracking block, guarded by `_heat_pump_orphan_sweep_done` so it doesn't repeat every 10 s. Re-runs after each reload (which creates a fresh coordinator).
- **Idempotent** — safe to invoke against an empty config (sweeps ALL relay repairs), safe to invoke with no orphans (no-op), defensive against issue-registry exceptions.

4 new tests cover the orphan sweep, empty-config sweep, no-orphan idempotency, and registry-error defensiveness. 3259 tests pass.

# [1.7.2-beta.4] - 08.06.2026

## 🧪 Beta Release

_Mobile-only hotfix: translations were rendering as raw keys on the Companion app._

### 🐛 sem-localize.js now loads on mobile (#448 follow-up)

RienduPre reported (2026-06-08, iOS Companion app): almost every translation key on the dashboard rendering as the raw key (`today_plan_title`, `home_sub`, `plan_now`, etc.), not just the new beta-introduced ones. Root cause: beta.1 moved `sem-localize.js` off the Lovelace-resource channel onto `add_extra_js_url`-only. Desktop browsers load both channels reliably; mobile Companion app does NOT pick up `add_extra_js_url` scripts in many cases.

- **Dual-channel registration**: `sem-localize.js` is now registered as BOTH an `add_extra_js_url` (desktop-friendly, loads before Lovelace modules) AND a Lovelace resource (mobile-friendly). Same hash-suffixed URL on both channels — browser fetches once. (by @traktore-org)
- **IIFE guard**: `sem-localize.js` is now wrapped in `(function(){ if (window.semLocalize) return; ... })()` so a defensive second load is a clean no-op. Without the guard, a second `<script>` execution would throw on the second `const _semTranslations = {...}` declaration.
- **Generator updated**: `scripts/regenerate_localize.py` produces the guarded output. The IIFE shape is now self-documenting in the generated file's header.

After upgrade + restart, **clear the Companion app cache** (Settings → App Configuration → Reset frontend cache). The new Lovelace resource registration causes a fresh fetch, and the IIFE-guarded file works whether one or both channels load it.

3255 tests pass.

# [1.7.2-beta.3] - 07.06.2026

## 🧪 Beta Release

_Hotfix on top of [1.7.2-beta.2](https://github.com/traktore-org/sem-community/releases/tag/v1.7.2-beta.2). Tariff timeline + 15-min provider support + diagnostic surface._

### 🐛 Tariff timeline no longer lies on weekends with missing schedule (Discussion #432)

RienduPre reported (2026-06-06, Saturday, Tibber NL dynamic): the bottom "Schema vandaag" timeline showed a solid "Goedkoop" bar for all 24 hours — but the current-classifier card above it correctly showed "Normaal" with 0.3142 EUR/kWh between the configured 0.1/0.3 thresholds. Two code paths, one was lying.

Root cause: `_getTariffSchedule()` in `sem-schedule-card.js` had a hardcoded fallback when `schedule_today` wasn't published:
- Weekday → `[NT 0-7, HT 7-20, NT 20-24]` (CH-shape, wrong for NL)
- Weekend → `[{0..24h, cheap}]` (just labels the whole day cheap)

That weekend branch is exactly what RienduPre's Saturday screenshot showed.

- **New JS fallback**: when `schedule_today` is unavailable, mirror the current `tariff_price_level` across the day instead of pretending we know per-hour data.
- **Visual fallback indicator**: fallback blocks now render at reduced opacity (35%) with a dashed border — users can see at a glance the chart is showing best-effort, not real data. (by @traktore-org)
- Tooltip changes to `<level> (no per-hour data — showing current level)` so the lie is structurally impossible.

### 🌍 Parser now accepts 15-min ENTSO-E + Tibber Pulse shapes (Discussion #432)

RienduPre's prompt — *"his tariff changes every 15 min"* — sent us deep into the parser. Two real gaps:

1. **ENTSO-E attribute shape**: Day Ahead Prices integration uses `prices` (singular) array with `time` + `price` fields. The old parser only checked `prices_today` / `prices_tomorrow` / `today` / `tomorrow` with `start` / `startsAt`. Now adds `prices` + `time` + `hour` to the attribute / timestamp vocabulary.
2. **15-min granularity gap detection**: the parser now records the detected sample interval. Tibber Pulse 15-min API + ENTSO-E 15-min zones (NL, DE) both produce 96 entries/day; the diagnostic surface now reports `tariff_parsed_interval_seconds: 900` so a 15-min vs hourly mismatch is visible at a glance.

5 new tests pin these shapes — Tibber Pulse 96-entry, ENTSO-E `prices` array, `hour` key for template sensors, empty-attribute zero-diag verification, 15-min block-collapsing into chart blocks.

### 🩺 New tariff diagnose fields (#448 follow-up)

The `tariff` diagnose section now exposes WHAT THE PARSER ACTUALLY SAW:

- `tariff_parsed_attribute` — which attribute key matched (e.g. `today`, `prices`, `raw_today`). `null` if nothing matched.
- `tariff_parsed_count` — total PricePoints parsed from the entity.
- `tariff_parsed_interval_seconds` — 900 for 15-min, 3600 for hourly, etc.
- `tariff_today_prices_count` — points for today specifically (after timezone filtering).
- `tariff_today_level_counts` — distribution: `{"cheap": 25, "normal": 50, "expensive": 21}`.
- `tariff_today_first_price` / `tariff_today_last_price` — sanity-check the parsed values.

For RienduPre / anyone hitting "all day cheap": hit the 🩺 Diagnose button on Tariff & pricing, paste the JSON. The fields tell us in one read whether (a) parser didn't recognise the attribute shape, (b) shape matched but timestamps in wrong timezone, (c) shape matched and prices are genuinely all cheap, or (d) percentile mode hit a flat-distribution fallback.

### Research that informed the fix

- [Home Assistant Tibber integration](https://www.home-assistant.io/integrations/tibber/) — official `today` / `tomorrow` with `startsAt` + `total`. 15-min native as of HA 2025.10.0.
- [JaccoR/hass-entso-e](https://github.com/JaccoR/hass-entso-e) — uses `prices` (singular) + `time` + `price`. 15-min for NL/DE zones.
- [jpawlowski/hass.tibber_prices](https://github.com/jpawlowski/hass.tibber_prices) — 100+ sensors, quarter-hourly precision.
- [OdynBrouwer/HomeAssistantTibber](https://github.com/OdynBrouwer/HomeAssistantTibber) — Advanced fork with quarter-hourly + NL solar support.

3255 tests pass, 0 fail.

# [1.7.2-beta.2] - 07.06.2026

## 🧪 Beta Release

_Second beta on top of [1.7.1](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1) stable. Two structural bug fixes found during live testing on HA-TEST, plus newly-wired telemetry surfaces for heat-pump + hot-water diagnostics._

### 🐛 `set_option` service must always reload (live-test finding)

Configuring `heat_pump_relay2_entity` via `solar_energy_management.set_option` updated the saved options but did NOT re-register the heat-pump controller. The `async_update_options` listener has a skip-reload optimization for runtime number/switch tweaks (intentional, ~1 s downtime saved per slider click) which was accidentally swallowing the `set_option` write too. Result: status sensor showed `not_configured` despite both relay entities being saved, until the next full HA restart. (by @traktore-org)

- `set_option` now explicitly calls `async_reload` after `async_update_entry` so the new config is always picked up. The merge skip stays (no reload when nothing actually changed).
- Caller's next read sees the new state immediately — service awaits the reload.

### 🐛 Repair issues now auto-clear across reloads (also caught live + RienduPre)

`heat_pump_partial_sg_ready` and `heat_pump_relay_unavailable` Repair issues used an in-memory `_raised` flag to track "have we raised this already?" That flag is per-coordinator-instance — reset on every reload. So the moment a user fixed their config (e.g. added the second SG-Ready relay), the new coordinator's flag was False, the `clear_*` call never fired, and the stale Repair stuck in the registry indefinitely. RienduPre also reported the symptom on #432 / #448. (by @traktore-org)

- Removed both in-memory flags. Now always calls `raise_*` / `clear_*` based on current state — both `async_create_issue` and `async_delete_issue` are idempotent so the duplicate calls are harmless.
- Clears any prior issue when a slot's entity is removed from config (was only clearing when the entity was present-but-broken-then-fixed).
- Result: Repair issues correctly mirror live config state across any number of reloads.

### 🩺 Heat-pump runtime path telemetry now visible (#421 follow-up)

The #421 audit shipped `_last_activation_path` / `_last_deactivation_path` / `_last_relay_path` / `_last_temperature_reading_path` / `_last_offpeak_path` recorders on `HeatPumpController` in `v1.7.0-beta.24` (`494fdf9`) — but never wired them through to a user-visible surface. The audit was effectively half-done; the recordings were just internal Python attributes nothing read.

- All 5 path recorders now publish through `coordinator.data` into the diagnose slicer for `heat_pump`. (by @traktore-org)
- New `heat_pump_current_temperature` published too — the live reading the controller uses for safety decisions.
- Diagnose modal on the Heat Pump section now shows every branch the controller took on the last cycle. Concrete vocabulary: `force_on`, `boost`, `boost+climate`, `normal`, `blocked`, `parent_declines`, `already_warm_skip`, etc.

### 🩺 New Hot Water section + diagnose surface

Configuration tab now has a dedicated Hot Water section with entity pickers (boiler control + temperature sensor) and the existing Solar / Max temperature steppers. New `hot_water` diagnose slicer exposes the config so support can see what's set. (by @traktore-org)

- Hot Water section + diagnose button live on every install. (No runtime status block yet — the `HotWaterController` isn't wired into the production surplus loop; that's the next beta.)
- 20 new translation keys (EN + DE polished, 13 other languages with EN fallback).

### Notes for testers

- After upgrade, re-check any stuck Repair issues in HA → Settings → Repairs. They'll auto-clear on the next coordinator cycle if the underlying condition is no longer true. Pre-fix orphaned issues may need a one-time manual dismiss.
- The `set_option` reload fix means structural option changes (entity pickers, mode selects) take effect in ~3 s instead of "next restart" — much better for the Configuration tab editing flow.

# [1.7.2-beta.1] - 07.06.2026

## 🧪 Beta Release

_First beta on top of [1.7.1](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1) stable._

### 🐛 EV session-energy pass-through + stale-global cleanup (#449)

User report on PROD 2026-06-07: KEBA's `sensor.keba_p30_session_energy` showed **14.61 kWh** but the SEM-published `sensor.sem_charger_ev_charger_session_energy` showed only **0.97 kWh**. Structural disagreement — SEM integrates its own session counter internally (load-bearing for solar-share / cost calcs) while KEBA's is a hardware truth that survives reloads + midnight rollovers.

- **New `sensor.sem_charger_<id>_session_energy_external`** sensor per charger. Passes through the charger's own `ev_session_energy_sensor` (e.g. KEBA's session counter) directly to the dashboard. Auto-converts Wh → kWh based on the source unit. Surfaces the charger's truth alongside SEM's internal integration so users see both numbers and can interpret the difference. (by @traktore-org in #135)
- **v11 → v12 schema migration.** Drops the stale top-level `ev_session_energy_sensor` key left over from the v2 → v3 multi-charger migration. The per-charger value in `ev_chargers[].ev_session_energy_sensor` has been canonical since v3; the top-level copy was harmless but on PROD it pointed at the wrong sensor (`keba_p30_energy_target` — a user setpoint, always 0) and confused diagnostics. Defensive: only drops the top-level when at least one charger has its own value. (by @traktore-org in #135)
- **`config_flow.py` `VERSION` bumped 11 → 12.**

### 🌍 Chart "Today" window now uses HA's timezone (#450)

`sem-chart-card.js:_setDefaultPeriod` previously used `new Date(now.getFullYear(), now.getMonth(), now.getDate())` to compute "Today's midnight" — but that's the **browser's** local midnight, not HA's. When the browser timezone differs from the HA server's (Companion app on a phone roaming across timezones, desktop on a different DST schedule), the "Today" window shifted by 1+ hours. User-reported as the chart timing being "off like an hour or so".

- **New `_startOfDayInHaTz(now)` helper.** Uses `hass.config.time_zone` + `Intl.DateTimeFormat` to compute the absolute Date pointing at HA-local-midnight, regardless of browser TZ. Falls back to browser-local-midnight when `hass.config.time_zone` is unavailable. (by @traktore-org in #136)
- Both call sites in `_setDefaultPeriod` (the `wantToday` start + the `week` Monday-of-week start) updated to use the helper.

### 🩺 Per-section Diagnose slicers (#432 polish)

Beta.17 wired Diagnose buttons into every Configuration tab section but only **Overview** and **Heat Pump** had dedicated key slicers; the other 8 sections used a generic prefix-match. This release adds curated state + option slicers per section so the JSON payload RienduPre (or anyone) pastes back is signal-rich, not noisy. (by @traktore-org in #432)

Dedicated slicers landed for: **EV chargers** (per-charger nested entries via prefix-match on `charger_<id>_*`), **Tariff** (classifier_path + percentile breaks + price curves), **Battery zones** (zone settings + live SOC + health), **Battery scheduler** (capacity / efficiency / pessimism), **Load management** (peak levels + shedding status), **Forecast** (today/tomorrow kWh + source + dampening factor), **Notifications** (toggles + service), **Advanced** (deltas + observer mode).

### 🧪 Tests

- **`tests/test_config_flow_migration.py`** — 2 new v11 → v12 cases: (a) stale top-level dropped when per-charger value exists; (b) defensive — top-level preserved when no per-charger value (don't silently drop a sensor mapping the user may rely on). Existing migration tests updated for the new v12 target.
- **`tests/test_per_charger_seed_migration.py`** + **`tests/test_277_charge_mode_phase_a.py`** + **`tests/test_277_charge_mode_phase_b.py`** — version assertions bumped 11 → 12 (chain still ends at the latest version).
- Full suite: **3 241 pass, 9 skipped, 0 fail** (was 3 239 at 1.7.1).

### 📦 Schema migration

- **v11 → v12** (#449) — drops stale top-level `ev_session_energy_sensor` when at least one charger has its own value. No data loss; per-charger value remains canonical.

# [1.7.1] - 07.06.2026

## 🎉 Stable Release

_Consolidates the 1.7.1-beta.1 through 1.7.1-beta.17 chain into a single stable cut. Soaked overnight on HA-PROD on real hardware (Huawei SUN2000 + LUNA2000 + KEBA P30); no regression vs 1.7.0._

> **Note — issue-reference correction (2026-06-07):** the entry below cites `#446` for the EV `ev_target_type` / estimated_soc fix, but that number is actually an open issue titled "Extra Dutch translations" (unrelated). The retroactive issue for the fix is [#451](https://github.com/traktore-org/sem-community/issues/451). Same applies for the `#135` / `#136` references that originally appeared in the 1.7.2-beta.1 entry — corrected to [#449](https://github.com/traktore-org/sem-community/issues/449) and [#450](https://github.com/traktore-org/sem-community/issues/450). Going forward, GitHub issues are filed BEFORE the fix lands so commit messages cite real numbers.

### 🚀 Headline features

* **Slim install flow** (#442) — 3 steps → 2. EV charger is moved off the install path entirely; users without an EV configured can now finish setup without lying or quitting.
* **In-dashboard Configuration tab** (#442) — every OptionsFlow setting is now editable inline. 10 accordion sections (Setup overview, EV chargers, Battery zones, Tariff, Heat pump, Battery scheduler, Load management, Forecast, Notifications, Advanced), `(?)` help-toggle pattern on every field, auto-save via `solar_energy_management.set_option` + read-back via `solar_energy_management.get_config`.
* **Per-section Diagnose buttons** (#432) — every Configuration tab section gets a 🩺 button that opens a focused JSON modal with **Copy to clipboard**. The user pastes on the discussion → maintainer gets a signal-rich payload instead of the 5 MB full diagnostics dump.
* **One-time onboarding banner** (`sem-onboarding-banner`) — points existing users at the new Configuration tab; localStorage-gated, never shown to new installs.

### 🐛 Stable-quality bug fixes

* **EV charging logic now strictly honours per-charger `ev_target_type`** (#446) — no silent fallback to `estimated_soc` when the SOC sensor isn't configured. v10 → v11 migration auto-resets bad-state entries on first restart; Configuration tab GUI gate prevents new ones. AST lint pins the invariant. Fixes the PROD 2026-06-06 IDLE-stuck-at-120W stall.
* **Reliable home consumption — two-tier hold** (#444) — `_smooth_home_consumption` now uses a 10-cycle transient hold (was 2) plus a separate 30-cycle inconsistency hold triggered when the raw balance goes strongly negative (i.e. physically impossible → guaranteed sensor staleness). Measured on PROD: zero-clamp rate drops from 37 % → 3 % during active charging at variable solar.
* **Bulletproof EV solar-path stability** (#443) — evcc-style stability layer around `_set_current` on the daytime `min_plus_solar` Zone 3/4 path: rolling-median smoothing on `budget_w`, delta guard, time debounce, heartbeat. Stops the KEBA-side current oscillation that aborted EV sessions for Huawei+KEBA users on cloudy days.
* **HA Repairs — graceful unavailability** (#440 / beta.10) — persistent sensor / forecast / recorder problems now surface in Settings → System → Repairs instead of growing the log. Transient sub-5-minute flaps stay completely silent.

### 🔍 Heat-pump observability (#432)

Discussion #432 surfaced a class of bug we couldn't reproduce on our hardware: heat-pump-controller registration silently fails for users with non-standard SG-Ready wiring. **1.7.1 ships the observability tools so users can self-diagnose remotely:**

* **`sensor.sem_heat_pump_registration_status`** — six-string diagnostic sensor + attributes exposing the resolved entity ids + their live HA state (including `entity_missing` when the entity id is set but doesn't exist).
* **Two new Repair issues** — `heat_pump_relay_unavailable_<slot>_<entity_id>` (per-relay, 5 min threshold) + `heat_pump_partial_sg_ready` (singleton, half-config detection).
* **`heat_pump` block in the diagnostics dump.**
* **Failure-path log promoted DEBUG → INFO** at `__init__.py:1137` so users see it in standard HA logs without enabling SEM debug logging.

### 📐 Architectural principle codified (`docs/ARCHITECTURE.md`)

**SEM is not an integration. SEM is an energy-management layer that sits on top of HA integrations.** Kills the temptation to add brand-specific drivers inside SEM. For Nibe SG-Ready specifically, `docs/EV_CHARGING_LOGIC.md §12` now documents both valid wiring paths (physical relays vs HA Modbus template switches) — SEM treats both the same way.

### 🧪 Tests

* **3 239 pass, 9 skipped, 0 fail** (was 3 186 at 1.7.0 — net **+53 tests** across the 1.7.1 betas).
* AST lints locking key invariants: `decide.py` never reads SOC fields (#446), `_calculate_remaining_need` never touches `estimated_soc` (#446), heat-pump failure log stays at INFO (#432).
* New scenario YAML `2026-06-06_target_soc_no_sensor_must_use_kwh` replays the PROD 2026-06-06 setup through the scenario harness.

### 🌍 Translations

* `dashboard/translations.json`: **1 007 keys × 15 languages** (EN + DE polished, others EN fallback).
* `strings.json` + 15 `translations/*.json`: every new OptionsFlow field, Repair issue, and entity name covered.

### 📦 Schema migration

* **v10 → v11** (#446) — entries with `ev_target_type="soc"` on a charger lacking `vehicle_soc_entity` are reset to `"kwh"`. No data loss; existing `target_soc` values sit idle in `entry.options` for users who later wire up a real SOC sensor.

### 🙏 Thanks

Massive thanks to @RienduPre for the persistent #432 reports — they directly drove the observability investment that lets us debug heat-pump issues remotely from now on.

# [1.7.1-beta.17] - 07.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.16](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.16)_

### 🔍 Heat-pump observability — diagnose silent registration failures remotely (#432)

Discussion #432 surfaced a class of bug we couldn't reproduce on our hardware: heat-pump-controller registration silently fails for users with non-standard SG-Ready wiring (ESP relay boards, Shellies, Modbus-bridged template switches for Nibe S-Series). Pre-#432 the user saw "No heat pump configured" on the dashboard with no clue why. The maintainer was guessing at fixes each round-trip. **Beta.17 ships observability tools so users can diagnose remotely — the maintainer reads one screenshot or one diagnostics dump and knows exactly which condition is failing.**

#### What's new

- **`sensor.sem_heat_pump_registration_status`** — diagnostic sensor publishing one of six strings (`registered_sg_ready`, `registered_climate_only`, `registered_sg_ready_and_climate`, `not_configured`, `partial_sg_ready_only_relay1`, `partial_sg_ready_only_relay2`). Attributes expose the resolved entity ids + their live HA state (including `entity_missing` when the entity id is set but doesn't exist in `hass.states`). One screenshot tells the maintainer if the gate logic is wrong OR the entity wiring is broken. (by @traktore-org in #432)
- **Two new Repair issues** at Settings → System → Repairs:
  - `heat_pump_relay_unavailable_<slot>_<entity_id>` — fires when a configured relay entity has been unavailable/unknown/missing for 5+ minutes, naming the specific relay (1 or 2) and entity id. Auto-clears on recovery. Mirrors the `sensor_unavailable` pattern from beta.10.
  - `heat_pump_partial_sg_ready` — fires when exactly one of `(relay1, relay2)` is set without a climate fallback. The SG-Ready protocol encodes its four states as a 2-bit binary across BOTH relays; a single relay can't drive it. Singleton issue (one fix per misconfig), auto-clears when the config becomes valid. (by @traktore-org in #432)
- **`heat_pump` block in the diagnostics dump.** Settings → SEM → ⋮ → Download Diagnostics now includes a `heat_pump` block with `registered`, `registration_status`, `mode`, `sg_ready_state`, `solar_boost`, plus nested `config` (entity ids) and `live` (their HA states). One-click payload for sharing on the discussion. (by @traktore-org in #432)
- **Failure-path log promoted from DEBUG to INFO** at `__init__.py:1137`. Pre-#432 the "Heat pump not configured" line was DEBUG-only, so users never saw it in their normal HA log view. Now it's INFO and includes the actual `relay1` / `relay2` / `climate` config values, symmetric with the success-path INFO. If the user expects registration but sees `None` values, the problem is in the config-flow save; if they see real entity ids, the problem is the entities themselves. (by @traktore-org in #432)

### 🩺 Per-section Diagnose buttons in the Configuration tab (#432)

Built on top of the heat-pump observability above. Every section of the Configuration tab gets a **Diagnose** button next to the section title. Click it → a modal opens with a focused JSON payload (the section's config + live state + last ~20 SEM log lines matching the section's keywords) + a **Copy to clipboard** button. The user pastes the result on the discussion or issue tracker; the maintainer gets a signal-rich payload instead of having to ask for a full 5 MB diagnostics dump.

- **`solar_energy_management.diagnose` service** (`__init__.py`, `supports_response=ONLY`). Takes an optional `section` parameter (defaults to `all`). Returns `{section, payload: {version, entry_id, entry_version, config, state, recent_logs}}`. Phase 1 has dedicated slicers for `all` (Overview) and `heat_pump`; the other 8 sections use a generic prefix-match slice (per-section slicers land in a follow-up beta — the button shell + modal + copy flow are wired everywhere so the user surface is consistent). (by @traktore-org in #432)
- **`<sem-diagnose-button>` Lit element** (`dashboard/card/src/cards/sem-diagnose-button.js`). Self-contained: button + modal + clipboard-write + busy/error states. Pluggable via `section` + `label` props. The Configuration tab's `_renderSectionHeader` mounts one per section with `@click.stop` so opening the modal doesn't toggle the accordion. (by @traktore-org in #432)
- **Architectural design note for follow-up betas:** generic prefix-match slicers stay; we'll add dedicated slicers for the high-value sections (EV chargers, tariff, battery zones) in 1.7.2-beta.1. Each new section just needs a one-liner key set added to `__init__.py`'s slicer map — no extra UI work.

#### Architectural principle codified (`docs/ARCHITECTURE.md`)

**SEM is not an integration. SEM is an energy-management layer that sits on top of HA integrations.** evcc and similar tools bundle brand-specific device drivers (e.g. evcc's `nibe-s-series` template speaks Modbus directly to register 3032). SEM intentionally takes a different shape: it stays in HA's entity-and-services world. The user runs HA's `nibe` / `modbus` / `keba` integration (which owns the protocol), then plugs the resulting entities into SEM via entity pickers.

For Nibe SG-Ready specifically, `docs/EV_CHARGING_LOGIC.md` now documents both valid paths (Path A: physical relays wired to AUX inputs; Path B: HA `template switch` entities backed by Modbus registers via the user's `nibe`/`modbus` integration). SEM treats both the same way — as two `switch` entities — so no protocol code lands in SEM regardless of which the user picks. (by @traktore-org in #432)

### 🧪 Tests

- `tests/test_heat_pump_registration_status_sensor.py` (new, 8 tests) — pins the 6-string state machine plus attribute behaviour for entity-missing and unavailable cases.
- `tests/test_heat_pump_repair_issues.py` (new, 7 tests) — verifies the two new repair types fire with the right issue ids + translation placeholders, are idempotent across relay slots, and swallow registry exceptions without crashing cycles.
- `tests/test_diagnostics_dump_heat_pump.py` (new, 4 tests) — AST-walks `diagnostics.py` to lock the `heat_pump` block + nested `config` / `live` subblocks. Cross-checks `coordinator/types.py` emits the diagnostic fields the dump reads.
- `tests/test_heat_pump_failure_log_is_info.py` (new, 1 test) — AST lint on `__init__.py` to assert the NOT-registered branch logs INFO, not DEBUG. Pins the regression boundary.

Full suite: **3239 pass, 9 skipped, 0 fail** (was 3217 — net +22 after the heat-pump tests).

### 🌍 Translations

- 70 new entries (5 keys × 14 languages): the `heat_pump_registration_status` entity name + the two new Repair issue title/description pairs. EN + DE polished, other 13 languages on EN fallback per the existing convention.

# [1.7.1-beta.16] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.15](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.15)_

### 🐛 EV charging logic strictly honours `ev_target_type` per charger (#446)

**PROD report 2026-06-06:** EV connected, SEM showing *"Charging active"* with `commanded_current = 9 A`, but real KEBA draw stalled at **120 W** with no progress against the day's kWh counter. The user (correctly) called this out as a charging-logic bug rather than a GUI / display problem.

**Root cause traced to `coordinator/coordinator.py:_calculate_remaining_need` (the kWh budget feeding `decide.py:369`).** Pre-#446 logic:

```python
if ev_target_type == "soc" and vehicle_soc is None:          # ← rescue path
    if detector and detector._soc_anchored:
        vehicle_soc = detector.get_virtual_soc(None)         # ← leaks estimated_soc

use_soc = ev_target_type == "soc" and vehicle_soc is not None
if use_soc:
    return max(0, (target_soc - vehicle_soc) / 100 * ev_capacity)   # → view.target_kwh
```

PROD had `ev_target_type="soc"` saved but no `vehicle_soc_entity` configured (a combination the Configuration tab let users save before this release). The rescue path silently substituted the taper detector's `estimated_soc = 89.6 %` into the kWh budget. With `target_soc = 80 %`, `(80 − 89.6) / 100 × 40 kWh` clamped to **0 kWh** → `decide.py:369` returned `IDLE` → KEBA got pilot-off → real draw collapsed to ~120 W. The user's daily kWh counter still had 3 kWh of headroom, but SEM didn't know it.

**Three-part fix per the user's architectural rule "if SOC, then SOC; if kWh, then kWh — no mixing":**

1. **Runtime trusts the saved config (no override).** `_calculate_remaining_need` is now a clean `if ev_target_type == "soc": … else: kwh …` branch. The rescue path is gone — `estimated_soc` never enters the budget. If a real `vehicle_soc` reading is momentarily `None` while in SOC mode, the SOC branch returns the full capacity so SEM keeps charging until taper detection trips (taper is the hard "full" stop). (by @traktore-org in #446)
2. **v10 → v11 schema migration cleans existing bad state.** On the first restart after upgrade, any entry that has `ev_target_type="soc"` (or the legacy `ev_target_mode` field) on a charger without a `vehicle_soc_entity` gets reset to `"kwh"`. Logged via `_LOGGER.info` with a count of fields scrubbed. Bad combinations on disk become structurally impossible. (by @traktore-org in #446)
3. **Configuration tab GUI gate prevents future bad state.** A new "Target type" select widget per charger. The "Vehicle SOC %" option is `disabled` when `vehicle_soc_entity` is empty; help text says *"requires SOC sensor"*. Users with a real sensor can pick either kWh or SOC; users without a sensor can only see kWh. (by @traktore-org in #446)

### 🧪 Tests

- **`tests/test_calculate_remaining_need_no_estimated_soc.py`** (new) — AST lint over `_calculate_remaining_need`. Banned names: `_estimated_soc`, `estimated_soc`, `get_virtual_soc`, `_ev_taper_detector`, `_ev_taper_detectors`. Any future refactor that reintroduces a SOC leak fails CI. (by @traktore-org in #446)
- **`tests/test_decide_no_soc_reads.py`** (new) — AST lint over `coordinator/decide.py`. Banned attribute reads: `target_soc`, `estimated_soc`, `vehicle_soc`. The "decision logic is pure kWh" invariant has been true since #440 but was unpinned; now it's locked. (by @traktore-org in #446)
- **`tests/test_config_flow_migration.py`** — added 3 v10 → v11 cases: per-charger bad-combo reset, legacy `ev_target_mode` cleanup, and the kWh-mode-preserved noop case. Updated 7 existing intermediate-hop assertions to expect version 11 (the new target). (by @traktore-org in #446)
- **`tests/test_minmax_targets.py`** + **`tests/test_ev_target_ux.py`** — deleted 3 tests that pinned the removed rescue-path behaviour; added 2 replacement tests for the new "real sensor + unavailable reading = full capacity" SOC-branch contract. (by @traktore-org in #446)
- **`tests/scenarios/2026-06-06_target_soc_no_sensor_must_use_kwh.yaml`** (new) — replays the PROD 2026-06-06 setup through the scenario harness. Asserts `canonical_strategy` is `battery_assist` (not `idle`) when `ev_target_type="soc"` + no SOC sensor + kWh headroom. (by @traktore-org in #446)
- **Full unit suite: 3217 pass, 9 skipped, 0 fail** (was 3214 — net +5 after the test cleanup).

### 📐 Why this is safe to deploy

- The runtime change is a code-path simplification, not a behaviour change for any user with a sensible config. Installs in pure kWh mode (the default) are unaffected. Installs with a real SOC sensor + SOC mode are unaffected — the SOC math is unchanged.
- The migration is idempotent. v11 entries are noops; v10 entries with kWh mode are noops; only the PROD-2026-06-06-class bad state gets cleaned.
- The GUI gate is purely a UX guardrail. Saved values are still honoured by the runtime; the migration handles legacy data.

### 🌍 Translations

- 5 new dashboard keys for the Configuration tab Target-type select (`config_ev_target_type`, `config_ev_target_type_kwh`, `config_ev_target_type_soc`, `config_ev_target_type_requires_sensor`, `config_help_ev_target_type`). EN + DE polished; other 13 languages on EN fallback. `sem-localize.js` regenerated: 1003 keys × 15 languages.

# [1.7.1-beta.15] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.14](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.14)_

### 🐛 Reliable home consumption — two-tier hold against sensor-staleness skew (#444)

**PROD report:** the system-diagram + energy panels occasionally show `Home = 0 W` for a single-cycle blip during active EV charging, then snap back to a real value. Recorded the behavior live on PROD on 2026-06-06: **16 % of cycles** clamped home consumption to 0 during a 10-min `min_plus_solar` charging window at ~4.25 kW with variable solar (clouds).

Root cause confirmed from the recording: the Huawei modbus inverter + grid meter update every ~13 s (p95 30 s), but the LUNA2000 battery sensor and the KEBA P30 EV sensor both have p95 staleness over **60 s** (max 82 s and 86 s respectively). When solar drops while grid hasn't yet caught up, the raw energy balance briefly goes physically negative (e.g. solar 4 348 W − stale grid_export 4 901 W − stale EV 120 W = **−700 W**). The existing 2-cycle hold (`HOME_HOLD_MAX_CYCLES = 2`) covered ~20 s of these gaps; the slower KEBA + LUNA2000 push gaps blew right past it.

**Fix.** Two-tier hold in `_smooth_home_consumption` (`coordinator/coordinator.py`):

  * **Inconsistency hold (~5 min):** when the raw balance is strongly negative (below the new `SENSOR_INCONSISTENCY_THRESHOLD_W = −100 W` gate), the inputs are guaranteed inconsistent — energy can't actually flow out faster than in. Hold the last positive value for up to `HOME_HOLD_INCONSISTENT_MAX = 30` cycles (~5 min @ 10 s coordinator cycle) while the slow sensor catches up.
  * **Transient hold (~100 s):** when the raw balance is at or near zero (sensor noise around a real low load), keep a shorter hold via the existing `HOME_HOLD_MAX_CYCLES` knob, now bumped from `2` to `10`. A genuinely sustained zero past that window is still reported as real.

Simulated against the 2026-06-06 PROD recording (200 samples × 3 s = 600 s wall, with all four raw upstream sensors + their `last_changed` timestamps captured): drops the zero-clamp rate from **37 %** (single-tier 2-cycle baseline replay) → **3 %** with the two-tier defaults. By @traktore-org in #444

### 🧪 Tests

- `tests/test_home_consumption_smoothing.py` extended to 9 tests (was 5). New coverage: strongly-negative raw balance triggers the inconsistency tier (`test_strongly_negative_raw_balance_uses_inconsistent_hold`), inconsistency tier eventually releases at the cap (`test_inconsistent_hold_eventually_releases`), mild negative raw balance stays on the transient tier (`test_mild_negative_raw_balance_uses_transient_hold`), and recovery resets the counter when sensors agree again (`test_inconsistency_tier_recovers_when_balance_returns_to_zero`). All 5 pre-existing tests still pass with no behavior change for raw-balance ≈ 0 cases. (by @traktore-org in #444)
- Full unit suite: **3214 pass, 9 skipped, 0 fail** (was 3186 — net +28 tests across the recent beta cluster).

### 📐 Why this is safe

The inconsistency tier only fires when the raw balance is strongly negative — a physically impossible state that can only come from sensor disagreement. It does NOT mask real sustained-zero states (no one home, all loads off): those keep `raw_balance` ≈ 0 W, which falls under the transient tier, which still releases the zero after 10 cycles. Equally important, **`HOME_HOLD_INCONSISTENT_MAX` is finite** — even an integration-level outage that holds the raw balance pathologically negative is accepted as real after 5 minutes, so the energy total doesn't get permanently inflated.

# [1.7.1-beta.14] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.13](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.13)_

### 🐛 Stop KEBA solar-path current oscillation that aborts EV sessions

**PROD report (HA-PROD, Huawei SUN2000 + KEBA P30):** EV charging current "goes up and down" so often the car closes the session and stops charging. Worked fine "a few changes ago, like last week". Traced to commit `c30a140` (the #438 commit-then-measure fix): the `min_plus_solar` Zone 3/4 day path was tightened to unconditionally command `max(min_amps, surplus_amps)` every cycle. Correct intent (the EV must draw min to bootstrap battery-assist), but the solar-path `_set_current` call at `coordinator/ev_control.py:519` had no delta or time guard (unlike the night-path call at `:440`). Huawei modbus jitter on PROD (`8 kW → 0 W → 8 kW` across cycles) propagated straight into a new `set_current` value every 10 s — KEBA P30 couldn't handshake fast enough and the car aborted.

This release adds an evcc-style stability layer around the solar-path `_set_current` call. (by @traktore-org in #443)

- **Layer 1 — rolling-median smoothing on `budget_w`.** Window 3 cycles (~30 s), tunable via `ev_surplus_smooth_window`. Drops single-cycle inverter flickers before they reach the amps calculation. Median (not mean) so the outlier is dropped, not averaged in.
- **Layer 2 — delta guard.** Skip `_set_current` when `|target - last_setpoint| < ev_min_change_amps` (default 1 A). The missing parity with the night-path guard at `ev_control.py:440`.
- **Layer 3 — time debounce.** Skip when less than `ev_min_change_interval_sec` (default 30 s) has elapsed since the last issued call. evcc's `guardduration` discipline, applied per-loadpoint.
- **Layer 5 — heartbeat.** After `ev_state_refresh_sec` (default 300 s) of no commands, force a re-send even if Layers 2 / 3 would suppress. Defends against lost commands on transient network blips and stale per-charger state across restarts.
- **Bypass.** `cold_start`, `mode_switch`, `stop`, `stall_recovery`, `deadline` always go through regardless of guards. Safety-critical transitions are never debounced.
- **Audit trail.** Every suppressed call logs a structured `solar set_current suppressed layer=... charger=... target=... last=... dt_since_last_set=... reason=...` line at INFO, so PROD soak can verify the guards are firing with sensible counts.
- **Multi-charger safe.** State lives on `PerChargerContext` (`last_set_amps_ts` + `budget_history` swap surface) so a fleet of N chargers keeps independent guards per loadpoint — `docs/MULTI_CHARGER.md` invariants preserved.

Layer 4 (threshold-time-windows on enable/disable transitions) is the pre-existing `ev_enable_delay_seconds` (60 s) and `ev_disable_delay_seconds` (300 s) at `ev_control.py:495-496` — kept as-is.

### 🧪 Tests

- **`tests/test_ev_solar_stability.py` — 23 new tests** covering: Huawei flicker smoothed (5), delta guard suppress/pass-through (3), debounce window suppress/pass-through (3), heartbeat re-send + reset (2), every bypass reason (4), multi-charger swap correctness (1), audit logging (3), regression guards for #438 + the PROD pattern (2). (by @traktore-org in #443)
- Existing EV-control tests untouched and green: `test_ev_control_fleet_reads`, `test_canonical_ev_budget`, `test_ev_stall_gate_commanded_amps`, `test_multi_charger_canonical_budget` (35/35). The FLEET-READ AST lint still passes.

### 📊 Tunables (config defaults; can be overridden via `ConfigEntry.options` in current beta — a Configuration-tab UI is planned for a follow-up beta)

| Key | Default | Why |
|---|---|---|
| `ev_min_change_amps` | `1` | Matches the night-path floor at `ev_control.py:440`. |
| `ev_min_change_interval_sec` | `30` | evcc-equivalent of guardduration, scaled to per-cycle adjusts. |
| `ev_surplus_smooth_window` | `3` | ~30 s rolling median; drops single-cycle modbus flickers. |
| `ev_state_refresh_sec` | `300` | Heartbeat floor; never let a charger sit without a fresh command for longer. |

### ✅ HA-PROD verification — Configuration tab save pipeline (beta.13 fix)

8/8 fields persisted on PROD via SSH-tunneled service calls (`solar_energy_management.set_option` writes, `solar_energy_management.get_config` reads back). Confirms beta.13's fix for the silent-reject bug in beta.12 holds on real hardware:

| Section | Field | Type | Before | After | Result |
|---|---|---|---|---|---|
| tariff | electricity_export_rate | number | 0.075 | 0.087 | ✓ |
| tariff | tariff_mode | select | static | static | ✓ |
| heat_pump | heat_pump_priority | slider | 4.0 | 5 | ✓ |
| battery_scheduler | battery_capacity_kwh | number | 15.0 | 12.5 | ✓ |
| battery_scheduler | battery_force_charge_negative_price | toggle | True | False | ✓ |
| load_management | warning_peak_level | slider | 4.5 | 4.0 | ✓ |
| load_management | critical_device_protection | toggle | True | False | ✓ |
| notifications | enable_charger_notifications | toggle | (default) | False | ✓ |

All values reverted to their original state after the test. PROD is clean.

### ✅ HA-PROD verification — EV charge-mode walk

Walked every available charge mode on PROD (target raised from 2 kWh → 10 kWh because the daily counter was already at 1.93 kWh, leaving SEM with no headroom; with 10 kWh target the modes had room to actually pull current):

| Mode | Commanded | EV power | State | Verdict |
|---|---:|---:|---|---|
| off | 0 A | 0 W | Solar mode – Charging allowed | ✓ |
| solar_only | 0 A | 0 W | Solar mode – Charging allowed | ⚠ |
| min_plus_solar | 9 A | 3 330 W | Solar mode – Charging active | ✓ |
| always_max | 32 A | 10 480 W | Solar mode – Charging active | ✓ |

3/4 green on real PROD hardware (Huawei SUN2000 + LUNA2000 + KEBA P30). The `solar_only` row is the open question: SEM showed `Charging allowed` but commanded 0 A even with ~6.5 kW solar and battery at 100 %. Most likely the rapid `off → solar_only` transition hit a stall-cooldown window before SEM had a clean surplus reading — `min_plus_solar` (forced 6 A floor) immediately afterward pulled 3.3 kW and `always_max` pulled the full 10.5 kW (32 A × 3 phase). Worth digging into in a follow-up but not a blocker for either the save-pipeline fix or the #443 KEBA stability work.

`solar_plus_cheap` is correctly hidden on PROD because no dynamic tariff is configured.

# [1.7.1-beta.13] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.12](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.12)_

### 🐛 Configuration tab save pipeline — actually works now (#442)

Beta.12 wired up inline editors for every OptionsFlow field, but the underlying `config_entries/update` WebSocket call **silently rejected every option write**: HA reserves the `options` field on that endpoint exclusively for OptionsFlow walks. The UI flashed "✓ Saved" because the client believed the write succeeded; in reality `voluptuous` rejected the payload server-side with `extra keys not allowed @ data['options']` and the value never landed in `entry.options`. None of the inline editors in beta.12 actually persisted anything.

Two new services close the loop:

- **`solar_energy_management.set_option`** (`__init__.py`) — accepts an `options` dict, merges it into the SEM ConfigEntry's `entry.options`, and lets HA's `update_listener` decide whether to reload (the same path the OptionsFlow takes). The Configuration tab now calls this service instead of `config_entries/update`. (by @traktore-org in #442)
- **`solar_energy_management.get_config`** (`supports_response=ONLY`) — returns the merged `data + options` dict the OptionsFlow uses internally. HA's public `config_entries/get` strips `data` and `options` for security, leaving the dashboard with no way to display current values for option-only fields. The card now reads via this service and displays the actual saved values, not just defaults. (by @traktore-org in #442)

### 🧪 Save round-trip harness — 8/8 green

New Playwright harness writes a value to one field per section, asserts:
- save status flashes from "saving" → "✓ Saved" within 400 ms
- new value is readable via `get_config` within 1 s
- revert restores the original value cleanly

Sections covered: tariff (export rate + mode select), heat pump (priority slider), battery scheduler (capacity number + force-charge toggle), load management (warning peak slider + critical-protection toggle), notifications (charger toggle). **8/8 GREEN, zero console errors.**

### 🧪 Unit tests

3186 pass, 9 skipped, 0 fail (unchanged from beta.12).

# [1.7.1-beta.12] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.11](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.11)_

### ✨ Every OptionsFlow step now inline in the Configuration tab (#442)

Beta.11 shipped the Configuration tab framework; beta.12 finishes the migration. **Every field from every OptionsFlow step is now editable directly in the dashboard** — entity pickers, sliders, toggles, selects, text/number inputs. No more page-by-page wizard for any setup task.

- **Heat pump inline setup.** 4 `<ha-entity-picker>` widgets (SG-Ready relays, climate entity, power sensor) + 3 sliders (boost offset, max setpoint, priority). Auto-saves on each change via `config_entries/update` → SEM's `update_listener` reloads the coordinator → `binary_sensor.sem_heat_pump_registered` flips on within ~1s once relays (or just climate) are set. Live status block (mode + SG-ready state) appears above the form once registered. (by @traktore-org in #442)
- **Tariff & pricing inline setup.** Tariff mode select (static/dynamic/calendar) + classification mode select (percentile/static) + 3 dynamic-provider pickers (price/forecast/feedin entity, conditionally rendered only when mode=dynamic) + 4 currency-aware number inputs (import/off-peak/export/demand-charge) + 2 grid-sensor pickers (override the Energy-Dashboard auto-pick) + 2 threshold steppers backed by runtime entities. Single source of truth: `entry.options`. (by @traktore-org in #442)
- **Battery scheduler inline setup.** All 10 fields: enable toggle, capacity number input, max charge power number input, roundtrip efficiency slider, cycle cost number input, pre-charge trigger hour slider, max target SOC slider, min deficit number input, pessimism weight slider, force-charge-on-negative-price toggle. (by @traktore-org in #442)
- **Load management inline setup.** Enable toggle + 3 peak-level sliders (target/warning/emergency) + critical-device-protection toggle + max grid import stepper. (by @traktore-org in #442)
- **Notifications inline setup.** 2 toggles (per-charger + mobile push) + notification-service dropdown built from `hass.services.notify` / `hass.services.rest_command`. (by @traktore-org in #442)
- **Per-charger inline setup.** Each existing EV charger now exposes 4 inline entity pickers (connected sensor, charging power sensor, current control entity, vehicle SOC sensor) plus the existing min/start/capacity steppers. Writes use the nested-list path `ev_chargers[index][key]` via `config_entries/update`. Add/remove a charger still deep-links to HA settings — schema migration on first-charger setup is too nuanced for inline-add in v1. (by @traktore-org in #442)
- **Auto-fetched ConfigEntry id.** Card runs one `config_entries/get` WebSocket call on connect to find the SEM entry; no need to pass `entry_id` via the dashboard YAML config. Caches `entry.data + entry.options` (the same merge the OptionsFlow uses) and re-renders on every save. (by @traktore-org in #442)
- **Save status flash.** Every editable field shows a "Saving…" → "✓ Saved" flash on write, or an error string if `config_entries/update` rejects. Errors stick until cleared. (by @traktore-org in #442)
- **New primitives.** `_renderPicker`, `_renderPickerNested`, `_renderOptionToggle`, `_renderOptionSelect`, `_renderOptionNumberInput`, `_renderOptionSlider` — six small render helpers that any future card can reuse for option-only fields. (by @traktore-org in #442)

### 🌍 Translations

- **73 new dashboard translation keys** for the inline form labels + help text (config_tariff_*, config_bs_*, config_lm_*, config_notif_*, config_ev_*, config_hp_*, config_help_*). EN + DE polished, other 13 languages on EN fallback. `sem-localize.js` regenerated: **998 keys × 15 languages**. (by @traktore-org in #442)

### 🧪 Tests

- Per-section verification harness (Playwright) walks the dashboard, expands every section, counts pickers/sliders/toggles/selects/number-inputs per section, asserts zero JS errors during traversal. Result: 10/10 sections render clean. (by @traktore-org in #442)
- Unit suite: **3186 pass, 9 skipped, 0 fail** (no change from beta.11). (by @traktore-org in #442)

# [1.7.1-beta.11] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.10](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.10)_

### ✨ Slim install flow + new in-dashboard Configuration tab (#442)

Fresh installs now take **2 forms instead of 3**, and every later tweak lives **inside the dashboard** — no more digging through Settings → Devices & Services → SEM → Configure.

- **Install flow stripped to 2 steps.** `async_step_user` (welcome + observer toggle) → `async_step_hardware` (peak limit + diagram style + install dashboard). The EV-charger step is gone from the install path entirely — most users don't have an EV configured on day one and were forced to lie or quit. EV setup now happens **after** SEM is up and running, via the new Configuration tab or HA settings. `_install_defaults()` seeds an empty `ev_chargers: []` list so downstream code is identical. (by @traktore-org in #442)
- **New "Configuration" tab** (`mdi:cog-outline`) sits between Control and Costs. Single `sem-config-card` with 10 accordion sections: Setup overview, EV chargers, Battery zones, Tariff & pricing, Heat pump, Battery scheduler, Load management, Forecast, Notifications, Advanced. Same look + (?) help-toggle pattern as the Control card from beta.7 — every setting carries a one-line explanation that toggles on with one click. (by @traktore-org in #442)
- **Inline edits for everything backed by a runtime entity.** Battery-zone steppers, tariff thresholds, observer-mode toggle, per-charger min/start amps, heat pump boost offset — all live-write to `number.sem_*` / `switch.sem_*` / `select.sem_*` so the change is immediate, no entry reload required. Sections that need entity-pickers (vehicle SOC sensor, tariff entity, heat pump relays, etc.) carry a one-click deep-link to the legacy OptionsFlow as a v1 fallback while the new `<sem-entity-picker>` rolls in. (by @traktore-org in #442)
- **`<sem-entity-picker>` Lit element** (`dashboard/card/src/elements/sem-entity-picker.js`). Thin wrapper around HA's stable `<ha-entity-picker>` that writes selections back via the public `config_entries/update` WebSocket command. Supports both flat options keys and nested `ev_chargers[index][key]` paths. Used by the Configuration tab; ready for power-user cards to compose against. (by @traktore-org in #442)
- **One-time welcome banner** (`sem-onboarding-banner`) shows up on the Home tab for existing users on first dashboard open after the update. Dismissable, persisted via `localStorage` (`sem-config-tab-introduced-v1`), points one click at the new Configuration tab. New installs never see it. (by @traktore-org in #442)
- **OptionsFlow stays intact for power users.** All 9 steps still register so the legacy "Settings → SEM → Configure" path keeps working for anyone who prefers it — and the Configuration tab's "Open in HA settings" buttons deep-link straight to it. (by @traktore-org in #442)

### 🌍 Translations

- **52 new dashboard translation keys** for the Configuration tab + onboarding banner (config_tab_title, config_section_*, config_help_*, onboarding_banner_*). EN + DE polished; other 13 languages use EN as placeholder pending native-speaker review (same convention as beta.6/7/10). `dashboard/translations.json` regenerated to `sem-localize.js`: **910 keys × 15 languages**. (by @traktore-org in #442)
- Install-flow `strings.json` user-step description rewritten across all 15 languages to mention the new Configuration tab instead of "next two steps". (by @traktore-org in #442)

### 🧪 Tests

- New `tests/test_config_flow_slim_install.py` pins (a) the install flow is exactly 2 steps, (b) `_install_defaults()` seeds an empty ev_chargers list, (c) all 9 OptionsFlow power-user steps stay registered so Configuration-tab deep-links never 404. (by @traktore-org in #442)
- `tests/test_dashboard_generator.py` updated for the new tab count (7 → 8) + Configuration path. Full suite: **3186 pass, 9 skipped, 0 fail** (was 3182). (by @traktore-org in #442)

# [1.7.1-beta.10] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.9](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.9)_

### 🚀 HA Repairs — graceful unavailability channel

Honors the HA quality-check feedback "should handle unavailability gracefully instead of spamming". Persistent problems now surface in **Settings → System → Repairs** instead of growing the log.

- **Persistent sensor unavailable** (`coordinator/sensor_reader.py`). New `_sensor_unavailable_since: dict[str, float]` tracks per-entity outage start in monotonic time. After `UNAVAILABLE_REPAIR_THRESHOLD_S = 300` seconds (5 min) the outage stops being "transient flap" territory and a Repair issue files — one entry per sensor in Settings → System → Repairs, severity WARNING, auto-cleared on first successful read. Transient sub-5 min flaps (Huawei modbus over WiFi commonly bouncing every 10-30 s) stay completely silent. (by @traktore-org)
- **No forecast integration** (`coordinator/forecast_reader.py`). Pre-fix, `detect_source()` logged INFO every cycle (~10 s) when no Forecast.Solar / Solcast / custom forecast was detected — log spam. Now: INFO logs once per outage, plus a Repair issue files after **1 hour** of continuous detection failure (gives a legitimate first-boot config window). Both clear automatically when SEM detects a forecast integration. (by @traktore-org)
- **Recorder integration unavailable** (`coordinator/ev_taper_detector.py:async_seed_from_history`). When the HA recorder isn't available, EV intelligence can't warm-start from history. Files a one-time Repair so the user has something actionable in the UI; auto-clears on next successful recorder read. (by @traktore-org)

### 🌍 Translations

- 3 new `issues.*` blocks (sensor_unavailable / no_forecast_integration / no_recorder) added to `strings.json` + 15 language translation files. EN + DE polished; other 13 use EN as placeholder until native-speaker review. (by @traktore-org)

### 🧪 Tests

- New `tests/test_repair_issues.py` (8 tests): threshold gate, recovery clears Repair, idempotent helper exceptions, forecast log-once-per-outage, forecast Repair-after-1h-threshold latching. (by @traktore-org)

# [1.7.1-beta.9] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.8](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.8)_

### 🐛 Bugfix — quiet sensor-recovery log spam (HA quality-check feedback)

- **`Sensor X recovered — now reading Y` demoted from INFO to DEBUG** in `coordinator/sensor_reader.py:1028`. When the upstream hardware flaps (Huawei modbus over WiFi commonly bounces every 10-30 s), the per-sensor recovery line previously fired at INFO for each of the 6+ tracked sensors on every cycle that recovered, spamming the HA log. Now symmetric with the existing DEBUG-level "Sensor X unavailable" log a few lines above — recovery is not user-actionable. Honors community feedback "should handle the unavailability gracefully instead of spamming". No behaviour change: the `_sensor_unavailable` transition tracking still fires, only the log channel changed. (by @traktore-org)

# [1.7.1-beta.8] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.7](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.7)_

### 🐛 Bugfix — #416 forecast records the wrong weather category

- **Mid-day weather snapshot for day-rollover writes** (`coordinator/forecast_tracker.py`). Pre-fix, `_save_day_record()` wrote `self._weather_today` into history at calendar rollover — which fires post-midnight when the HA weather entity reports `clear-night` / `unknown`, not the day's actual weather. Live PROD telemetry on 2026-06-05 confirmed **42 % of forecast records had `weather_category=unknown`**, so the correction cascade kept falling through from `weather × month` → `weather only` → `month only` → `weather=unknown bucket` (last resort). Fix mirrors the existing `_dampening_snapshot` pattern: capture `_weather_today` inside the `_calculate_dampening_factor` confident `blended_live` branch (snapshot taken during the day's actual daylight cycles), then have `_save_day_record()` prefer the snapshot over the live value. Backward-compat: if the day never entered the confident branch (forecast always below `MIN_FORECAST_KWH`, or HA restarted late), falls through to the live value as before. 4 new regression tests in `tests/test_forecast_tracker.py` (`test_416_*`) lock the snapshot + fallback paths. (by @traktore-org, fixes #416 write-time-weather)

# [1.7.1-beta.7] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.6](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.6)_

### 🎨 Inline help toggles — one mechanism across three cards

Discoverable `?` icon on cards where settings benefit from a one-line explanation. Off by default keeps the surface clean; tap to reveal italic descriptions next to each setting.

- **SOC Zones card** (`sem-battery-zones-card.js`) — (?) in the section header. Reveals one-line descriptions for Auto-start / Buffer / Assist Floor / Priority SOC, each with a color-coded left stripe matching its zone marker dot. (by @traktore-org)
- **EV charger card** (`sem-ev-status-card.js`) — (?) in the bottom settings row. Toggles two things together: (1) the 3-line Surplus/Overnight/House-battery mode hint that previously was always visible, (2) per-tile descriptions for Vehicle Start Amps / Min Amps / Vehicle Min Amps / Capacity / kWh-per-100km. Off = compact (selector + deadline + plan strip only). The "Next cheap window" timing line stays visible regardless when in `solar_plus_cheap` (operational info). (by @traktore-org)
- **Control card** (`sem-control-card.js`) — (?) at the top right. Globally toggles inline help for the two eligible sections: Battery Management (Priority / Min / Resume SOC) and Tariff & Pricing (Cheap / Expensive threshold). Other sections unchanged for now. (by @traktore-org)

### 🌍 Translations

- 15 new help strings × 15 languages = **225 entries**. EN + DE polished, other 13 follow the same template (native-speaker review welcome).

# [1.7.1-beta.6] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.5](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.5)_

### 🌍 Translations

- **Heat pump dashboard keys filled in for 14 languages**. `heat_pump_title`, `heat_pump_mode`, `heat_pump_sg_ready_state`, `heat_pump_boost_offset`, and `heat_pump_not_configured` were authored in English in beta.1 but never propagated to the other languages. Users on de/nl/fr/es/it/pt/pl/sv/cs/da/fi/hu/ro/no saw raw translation keys ("heat_pump_title", "heat_pump_not_configured") in the Control tab's Heat Pump section. 70 entries added (5 keys × 14 languages). Native-speaker review welcome. (by @traktore-org)

### 🎨 Polish — Control tab consistency with the EV card

- **Color-accent stripe on expanded sections.** Each Control-card section now shows an inset color-coded left stripe when expanded, matching the section icon (orange = surplus/solar/peak, teal = battery/heat_pump, pink = hot_water, blue = tariff/system). Ties the multi-section settings hub to the EV card's hint-row aesthetic. (by @traktore-org)
- **Typography bumped to match the EV / Battery card tier.** Section titles 14→15px with 0.1px letter-spacing; subtitles 12→13px; body labels (steppers, toggles, select rows) 13→14px; stepper/readonly values 13→14px. Tighter visual rhythm; readable at arm's length on phones. (by @traktore-org)
- **Surrounding cards bumped to the same tier** so the Control tab feels coherent: `sem-load-priority-card.js` (em-based sizes scaled from 0.75-0.9em up to 0.9-1em), `sem-grid-card.js`, `sem-price-card.js`, `sem-costs-card.js`, `sem-energy-impact-card.js`, `sem-battery-zones-card.js` (10→11px and 11→12px label sizes). Same pattern as the solar-card font-polish in beta.5. (by @traktore-org)

# [1.7.1-beta.5] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.4](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.4)_

### 🚀 Renames + polish

- **`night_initial_current` renamed to `initial_current` ("Vehicle Start Amps")** (#441). The "night" prefix on the per-charger session-start ramp current was misleading — the value is applied whenever a charging session begins, not strictly at nighttime. Renamed config key `ev_night_initial_current` → `initial_current` (top-level + per-charger), entity key `number.sem_charger_<id>_night_initial_current` → `number.sem_charger_<id>_initial_current`, display name "Start Amps" → "Vehicle Start Amps" (groups with the new "Vehicle Min Amps" tile from beta.4). Schema migration v9 → v10 renames the field on existing entries; the old number entity is auto-removed by `number.py:_cleanup_stale_entities` on next setup. New `number.py` icon `mdi:car-clock`. Translation strings updated across 15 languages. (by @traktore-org)
- **Solar card font sizes bumped to match other cards** — the PV1/PV2 / Solar Flows Today / Per String / Forecast & Performance card was rendering at 10-11px labels and 11-12px values vs the battery card's 12-13px. Section titles, flow labels, flow values, metric labels/values, and chip labels/values all bumped one tier up for readability. (by @traktore-org)

# [1.7.1-beta.4] - 06.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.3](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.3)_

### 🚀 Architectural — charge mode is the sole authority on charging (BREAKING)

- **EV intelligence no longer overrides charge mode.** Pre-#440, `coordinator/ev_control.py:_calculate_forecast_night_target` had two override paths that could zero the user's Min target: a SOC-based skip (`estimated_soc > target_soc → return 0`) and a solar-forecast-based reduction. The mode + Min slider therefore did NOT decide whether to charge — EV intelligence did. Post-#440 the function is a thin pass-through (`max(0, daily_target - daily_delivered)`); the user's mode + sliders are the sole authority. The `%` (SOC) target type is already structurally gated on a real `vehicle_soc_entity` in `select.py:63-65`, so estimated SOC never enters the decision. **Behaviour change**: users in `min_plus_solar` with a sunny forecast tomorrow will now charge the full Min target tonight, where pre-#440 SEM would have skipped some/all of it. (by @traktore-org, fixes #440)
- **Skip-decision wiring deleted.** `calculate_nights_until_charge`, `record_skip`, `reset_skips`, `_consecutive_skips`, the `_skip_recorded_tonight_per_charger` latch, the `notify_ev_charge_skip` / `notify_ev_charge_recommended` notification methods, the `nights_until_charge` / `charge_needed` / `charge_skip_reason` sensor entities (both global and per-charger), and the corresponding "Charge Tonight" / "Nights Until Charge" rows on the EV card are all gone. Existing user automations referencing these entities will break — `binary_sensor.sem_charger_<id>_charge_tonight` and `sensor.sem_charger_<id>_nights_until_charge` become unavailable. The features were never reliable in the absence of a real vehicle SOC; removing is honest. The `EVTaperDetector` now serves display only: `estimated_soc`, `last_full_timestamp`, `energy_since_full`, taper trend, `battery_health_pct`. (by @traktore-org, refs #440)
- **Per-vehicle minimum current** (ADR 0010 pattern 3). New optional per-charger `vehicle_min_current` field captures the car's handshake-floor minimum (e.g. Renault Zoe ~9 A). Effective floor at the decision layer is `max(ev_min_current, vehicle_min_current or 0)` via the new `decide.effective_min_amps()` helper, applied to all `MinPlusSolarMode` / `SolarOnlyMode` branches plus `ev_control._night_initial_amps`. Config-flow charger-edit step gains a slider; the EV card gains a "Vehicle Min Amps" tile in the bottom settings row. Schema migration v8→v9 seeds the field to `None` (= "use the loadpoint `ev_min_current`") for existing entries. (by @traktore-org, refs ADR 0010 #3)

### 🐛 Bugfixes (already on this branch from earlier work)

- **#438 false-full taper anchor.** Pre-fix, an 11-minute handshake-floor oscillation totalling 0.19 kWh satisfied `peak > 3 kW + 3 low samples → _full_detected=True`, anchoring SOC=100 % until physical unplug. Fix: trapezoidal energy integration in `EVTaperDetector.update()` plus a per-vehicle session-energy floor `min(1.0 kWh, capacity × 0.025)` — a 24 kWh LEAF arriving at 99 % SOC can still anchor full (~0.6 kWh threshold); a 0.19 kWh oscillation never can. 6 new regression tests in `TestPerVehicleEnergyFloor` (by @traktore-org, fixes #438)
- **#439 daytime `min_plus_solar` idled instead of supplementing.** Pre-fix, `MinPlusSolarMode._decide_day` gated Zone 3/4 charging on `budget_w < min_w → IDLE`. The budget read `battery_assist_budget_w() = surplus + battery_discharge_w`, but `battery_discharge_w` is the inverter's *currently-flowing* discharge — zero when no EV demand has been commanded yet. Chicken-and-egg deadlock. Fix: commit-then-measure pattern from evcc — drop the gate, offer `min_amps` unconditionally, let the next cycle's sensor readings reflect the actual battery/grid split. `coordinator/decide.py` Zone 3/4 branch now matches the `min_plus_solar` UI promise verbatim. (by @traktore-org, fixes #439)

### 🌍 i18n — structured 3-line mode hints

- **`charge_mode_hint_*` rewritten to 3 structured rows per mode.** The old single-line `charge_mode_hint_solar_only` / `min_plus_solar` / etc. shipped one short clause each — users couldn't tell what a mode actually did for solar, the house battery, and overnight charging. Replaced with `charge_mode_hint_<mode>_surplus` / `_overnight` / `_battery` (15 new keys per language × 15 languages = 225 strings) plus 3 row labels (`hint_label_surplus` / `_overnight` / `_battery`). The battery row substitutes `{buffer}` and `{priority}` placeholders with the user's actual SOC zone values (read from `number.sem_battery_buffer_soc` / `number.sem_battery_priority_soc`) so the hint reads "Drains for EV when home battery SOC ≥ 70 % (buffer). Below 70 % … Below 30 % (priority floor) …" — concrete, not abstract. EN + DE polished manually; other 13 languages follow the same template structure with native-speaker review welcome. Card rendering moves to `.ct-hint-row` flex layout in `sem-ev-status-card.js`. (by @traktore-org)

### 📝 Documentation

- **ADR 0010 — evcc pattern adoption.** Records the architectural choice informing #438, #439, and the per-vehicle min-current pattern. Three patterns adopted in order: commit-then-measure for `min_plus_solar` budget (the #439 fix), pilot-state-gated session lifecycle with a session-energy floor for taper-to-full (the #438 fix), per-vehicle minimum current with three-way max (the new feature this beta). Cites the exact evcc source locations for each. (by @traktore-org)

# [1.7.1-beta.3] - 05.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.2](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.2)_

### 🐛 Bugfixes

- **`binary_sensor.sem_heat_pump_registered` was always `off`** — pre-fix, `coordinator/coordinator.py` populated `heat_pump_registered` via `any(getattr(d, "device_id", "") == "heat_pump" for d in self._surplus_controller._devices)`. `_devices` is a `Dict[str, ControllableDevice]` keyed by device_id, so iterating it yields **keys (strings)**, never devices — and `getattr(string, "device_id", "")` always returns `""`. The check was wired to always be False, so the v1.7.1-beta.1 dashboard auto-hide kept the Heat Pump section hidden even on correctly registered climate-only installs (the exact path RienduPre would have hit). Replaced with the trivial `"heat_pump" in self._devices` dict-membership check. 4 new regression cases in `tests/test_437_heat_pump_climate_only.py` lock the new code and pin the old buggy expression as a counter-example (by @traktore-org, fixes the v1.7.1-beta.1 follow-up surfaced while reproducing discussion #432)

### 📝 Documentation

- **Nibe SG-Ready misconfig demo screenshots** — `docs/screenshots/nibe-sim/` adds 4 reproducible screenshots for discussion #432: config flow heat pump step + Control tab dashboard, under both Path 3 (the broken Nibe enable-flag-switches-as-relays config the other Claude recommended) and Path A (the v1.7.1-beta.1 climate-only config). Reproducible via `/config/packages/sem_sim_nibe.yaml` on HA-TEST (template switches mirroring `switch.sg_ready_heating_48282` / `switch.sg_ready_hot_water_48284` / `climate.vvm_320_heating_circuit` so the demo doesn't need real Nibe hardware) (by @traktore-org, refs #432)

# [1.7.1-beta.2] - 05.06.2026

## 🧪 Beta Release

_Changes since [1.7.1-beta.1](https://github.com/traktore-org/sem-community/releases/tag/v1.7.1-beta.1)_

### 🐛 Bugfixes

- **Multi-charger Load Priority collision** — pre-fix, `LoadManagementCoordinator.register_ev_charger()` hardcoded `device_id = "load_device_ev_charger"`. The per-charger loop in `__init__.py` called it N times for N chargers — each call overwrote the previous entry in `self._devices`, so the Control tab's Load Priority card showed only ONE EV row even with multiple chargers configured, and peak-shedding only acted on the LAST registered charger. `register_ev_charger()` now accepts `charger_id` + `charger_name` kwargs (defaults preserve single-charger backward compat: `load_device_ev_charger` key unchanged for `ev_chargers[0].id == "ev_charger"`); device dict gains a `charger_id` field for downstream mapping. Reviewer-caught: `features/device_registry.py:_populate_load_manager()` had a hardcoded `!= "load_device_ev_charger"` exclusion that would have silently pruned the new `load_device_ev_charger_1` entries on every registry sync — widened to `startswith("load_device_")`. 7 new tests in `tests/test_436_multi_charger_load_priority.py` covering single-charger legacy key preservation, multi-charger distinct entries, friendly-name fallback chain, idempotent re-registration, and the device_registry prune-survival regression (by @traktore-org, fixes #436)

# [1.7.1-beta.1] - 05.06.2026

## 🧪 Beta Release — first v1.7.1 beta

_Changes since [1.7.0](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0)_

First feature release on top of v1.7.0 stable. Closes the heat pump integration gap surfaced by discussion #432.

### 🚀 Features and enhancements

- **Heat pump climate-only registration** — `__init__.py` registration gate widened from `(relay1 AND relay2)` to `(relay1 AND relay2) OR climate_entity`. Nibe, Mitsubishi, Daikin, and any HA-controlled heat pump that exposes a `climate.*` entity but no SG-Ready relays can now configure SEM's heat pump boost automation. The `HeatPumpController` itself already supported the climate-only path internally (the #421 audit telemetry's `relay_path = no_relays_configured` branch was the proof). Config flow gains explicit two-path description (SG-Ready relays vs climate-only setpoint boost) plus form validation that rejects half-configured SG-Ready (one relay without the other AND no climate fallback). New `error.heat_pump_partial_relays` translation key. Reported by @RienduPre in discussion #432 (by @traktore-org, fixes #437)
- **Heat pump dashboard section** — `sem-control-card` gets a new "Heat Pump" section with mode (SG-Ready+climate / SG-Ready only / climate-only), current SG-Ready state, and the boost offset stepper. Auto-hides when no heat pump is registered using a new `binary_sensor.sem_heat_pump_registered` presence flag (needed because `heat_pump_sg_ready_state` defaults to `2 (NORMAL)` even when no controller exists). New translation keys: `heat_pump_title`, `heat_pump_mode`, `heat_pump_sg_ready_state`, `heat_pump_boost_offset`, `heat_pump_not_configured` (by @traktore-org, refs #437)

# [1.7.0] - 04.06.2026

## 🚀 Stable Release

First stable cut of the 1.7 line. Consolidates the work from 26 beta
releases since [v1.6.17](https://github.com/traktore-org/sem-community/releases/tag/v1.6.17).
Each beta's release notes remain below for the per-fix detail; this
block summarises the themes.

### 🏗️ Architecture

- **FleetCycleState refactor** (beta.7) — single source of truth for fleet-level coordinator inputs; eliminates an entire class of fleet-vs-per-charger read bugs that produced four hotfixes between v1.6.0 and v1.6.6
- **9 Architecture Decision Records** committed under `docs/adr/` (PerChargerContext, EVBudget, sign-convention boundary, home_consumption clamp, per-brand pipeline test, FleetCycleState, real-hass test framework, FleetEvPower newtype, multi-charger priority cascade)
- **`v7 → v8` config schema migration** (#359) — auto-flips stored `tariff_classification_mode` from legacy `static` to `percentile` for dynamic-tariff users on first restart after upgrade

### 🔍 Audit telemetry surfaces — 10 modules instrumented

Following the `classifier_path` pattern introduced in #359, **10 stale modules** now publish decision-path enums as sensor attributes so users can self-diagnose without us reading a debug log. Modules covered: `forecast_tracker` (#416), `hot_water_controller` (#420), `heat_pump_controller` (#421), `pv_performance` (#422), `time_manager` (#424), `consumption_predictor` (#425), `appliance_scheduler` (#426), `utility_signals` (#427), `load_management` (#433), `forecast_reader` (#434). Plus 4 modules audited and closed as no-change (pure data registries + stateless helpers: #423 #428 #429 #430 #431). Pure additive observability — zero behavior change in any of the published numeric outputs. Full framework lives in `docs/AUDIT_PLAYBOOK.md` and `tools/audit_candidates.py`. v1.7.1 then opens for the algorithmic improvements step once 2–4 weeks of real-world PROD telemetry accumulates.

### 🐛 User-reported fixes

- **#359** `tariff_classification_mode` stuck on `static` for dynamic-tariff users → v7→v8 schema migration (beta.21)
- **#384** missing `vehicle_range_entity` + `ev_kwh_per_100km` fields in the Add/Edit Charger flow (beta.21)
- **#404** per-battery power sign + SOC ring readability (beta.18-20)
- **#417** `cheap_price_threshold` / `expensive_price_threshold` max bumped 1.0 → 5.0 to cover high-priced markets (beta.21)
- **#356** ghost charger discovery (per-charger `_flow_` sensors matched as chargers) (beta.10)
- **#378** PV strings i18n fix (beta.8)
- **#383** per-charger `vehicle_soc` sensor (beta.19)
- **#392** KEBA failsafe watchdog heartbeat (beta.14)
- **#400** native `ev_current_control_entity` translations for 12 languages (beta.16, beta.20)
- **#405** battery session hysteresis (1-hour discharge → 2-min bug) (beta.16)

### 🎨 UX

- **Slim config flow** (#397) — 5 essential fields at install; advanced options moved to OptionsFlow. ~30 second setup
- **First-run welcome notification** (beta.15)
- **Per-battery sensors + fleet/per-battery card** (#404)
- **KEBA flicker debounce** (beta.8) — eliminates the on/off oscillation on edge-of-surplus
- **Multi-charger SOC clobber fix** (#383) — per-charger SOC sensor surfaces independent values

### 🙇 Thanks to our contributors

- @RienduPre for the precise `classifier_path` diagnosis on #359, the Add/Edit charger flow gap on #384, the multi-battery sign issue on #404, and weeks of high-signal beta reports
- @zlakes01 for the high-tariff-market signal on #417 and the multi-Easee dashboard report on #415 (under continued investigation)
- Everyone else who filed an issue this cycle — the user reports are what made the audit telemetry necessary AND useful

---

> **Per-beta detail follows. The notes for each `1.7.0-beta.N` below remain unchanged and may be consulted for the granular per-fix changes that rolled up into this stable.**

# [1.7.0-beta.26] - 04.06.2026

## 🧪 Beta Release — v1.7.1 audit batch 4

_Changes since [1.7.0-beta.25](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.25)_

Two more modules audited beyond the original Top-12, picked up by widening the staleness cutoff from 30 days to 2 weeks. Big-module focus on highest-leverage decisions, medium-module full coverage.

### 🔍 Diagnostics

- **#433 `LoadManagementCoordinator`** (1056 LOC, 118 branches — biggest module on the backlog) — **focused** telemetry on the highest-leverage decision points rather than exhaustive attribution. Four new keys on `sensor.sem_load_management_status`: `state_decision_path` (`emergency` / `above_target_shedding` / `warning_zone_keep_shedding` / `warning_zone_clean` / `below_restore_threshold_normal` / `in_hysteresis_band_with_shed_devices_restore` / `in_hysteresis_band_clean_normal`), `process_path` (`disabled_skip` / `state_changed:<old>_to_<new>` / `state_stable:<state>` / `error_caught`), `action_path` (`emergency_shedding` / `progressive_shedding` / `restore` / `no_action:<state>`), plus `last_error` (truncated catch-all exception message — previously this was log-only with no sensor surface) (by @traktore-org, refs #433)
- **#434 `ForecastReader`** — new `get_diagnostics()` method exposing: `source_detection_path` (`custom` / `solcast` / `forecast_solar` / **`none_available`** silent-failure surface — no forecast integration detected), `read_path` (`cold_detect` / `cached_source_valid` / `cached_source_lost_redetected` / `no_source_after_detect` / `read_complete`), `recommendation_path` (`target_reached` / `no_forecast` / `solar_only` / `solar_plus_cheap` / `immediate`), plus `unit_conversion_count` — counts how many of the 3 Solcast kW→W magic-number conversions fired this cycle (by @traktore-org, refs #434)

### 📁 Audit findings

- **Dead-code branch surfaced**: the `in_hysteresis_band_with_shed_devices_restore` path in `_determine_load_management_state` is **unreachable with default config** (target=5.0, hysteresis=0.3, warning=4.5 → restore_threshold=4.7 > warning_level=4.5). Inline comment documents this; future audit can fix the inverted-band config or remove the branch (reviewer-flagged on #433)

# [1.7.0-beta.25] - 04.06.2026

## 🧪 Beta Release — v1.7.1 audit batch 3

_Changes since [1.7.0-beta.24](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.24)_

Third batch of v1.7.1 audit telemetry. Closes the rest of the Top-12 backlog: two modules get telemetry surfaces, four close as no-change (pure data registries + a stateless translation helper that doesn't fit the path-attribute pattern). Pure additive observability, zero behavior change.

### 🔍 Diagnostics

- **#426 `ApplianceScheduler`** — `update_schedules()` now records per-device transition paths on `self._last_transitions[device_id]`, surfaced via `get_schedule_summary()["appliance_transitions"]`. Branches: `no_op` / `device_missing` / `scheduled_to_running` / `running_completed_by_runtime` / `running_completed_by_low_consumption` / **`running_too_short_skip`** (silent-failure surface — fast-cycle appliance under 5 min is treated as transient blip and skipped) / `scheduled_to_missed`. The `scheduled_to_running` branch is preserved when both it and `running_too_short_skip` could fire in the same cycle (caught in testing — `elif not fired` gate). New summary key `appliance_missed_today` (by @traktore-org, refs #426)
- **#427 `UtilitySignalMonitor`** — three new path strings on `UtilitySignalData.to_dict`: `utility_signal_read_path` (**`no_entity_configured`** silent-failure surface — when no entity is configured SEM treats utility-signal as permanently inactive / `entity_missing` / `active` / `inactive`), `utility_update_path` (`signal_started` / `signal_ended` / `signal_continues_active` / `signal_continues_inactive`), `utility_block_path` (`signal_inactive_no_block` / `solar_exempt_partial:N` / `all_blocked`) (by @traktore-org, refs #427)

### 📁 Audit framework

- Closed #428 (`utils/translate.py`) as no-change — pure stateless translation function. The `_load_translations` exception path already logs; the language-fallback and format-error paths are silent-but-benign. Same audit pattern as #423 helpers (by @traktore-org, closes #428)
- Closed #429 (`consts/devices.py`), #430 (`consts/labels.py`), #431 (`consts/sensors.py`) as no-change — pure data registries with 0 decision branches. No behavior to instrument; the audit's structural value for data registries is the data review itself, no findings. Top-12 backlog complete (by @traktore-org, closes #429 #430 #431)

# [1.7.0-beta.24] - 04.06.2026

## 🧪 Beta Release — v1.7.1 audit batch 2

_Changes since [1.7.0-beta.23](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.23)_

Second batch of v1.7.1 audit telemetry — four modules in one beta because they don't share state. Pure additive observability, zero behavior change in published return values.

### 🔍 Diagnostics

- **#421 `HeatPumpController`** — five decision-path attributes on `to_dict` → surfaces via `sensor.sem_load_management_status.devices.<heat_pump_id>`: `activation_path` (boost / force_on, with `+climate` suffix when climate boost composes), `deactivation_path` (normal / blocked / unblocked, with `+climate` suffix), `relay_path` (both_relays / relay1_only / relay2_only / **no_relays_configured** / relay1_failed / relay2_failed — the no_relays_configured branch is the audit's biggest silent-failure surface: SG-Ready state mutates internally but no physical relay actuates), `temperature_reading_path` (sensor / sensor_unavailable / sensor_invalid / sensor_missing / no_sensor_configured), `offpeak_path` (parent_declines / already_warm_skip / activate) (by @traktore-org, refs #421)
- **#422 `PVPerformanceAnalyzer`** — five decision-path fields on `PVPerformanceData.to_dict`: `pv_yield_path` (**no_system_size_configured** silent-failure surface — yield = 0 because size not configured, not because production was zero / computed_with_annual_projection / computed_no_annual), `pv_performance_path` (computed / no_forecast), `pv_clipping_path` (idle / clipping_active / post_clipping_idle), `pv_degradation_path` (insufficient_history / normal / warning / critical), `pv_system_age_path` (computed / no_install_date / install_date_invalid) (by @traktore-org, refs #422)
- **#425 `ConsumptionPredictor`** — new `get_diagnostics()` method exposing five prediction-path enums: `consumption_prediction_path` and `solar_prediction_path` (cold_start_empty / trained_full / trained_with_fallback:N / trained_all_fallback), `surplus_window_path` (no_data / no_surplus / found_window / no_contiguous_window), `ev_prediction_path` (no_data / weekday_match / hour_fallback), `observation_path` (recorded / deduplicated). Plus training-status and sample-count counters (by @traktore-org, refs #425)
- **#424 `TimeManager`** — new `get_diagnostics()` method exposing seven time-of-day paths: `sunrise_source` and `sunset_source` (sun_integration / fallback_default — silent-failure surface when sun.sun is unavailable and TimeManager falls back to hardcoded 06:00/20:30), `sunrise_correction` (none / **next_rising_was_tomorrow** — same class of bug as #416 forecast_tracker, tracking how often it fires / fallback_default_06_00), `night_window_path` (pre_midnight_in_night / post_midnight_in_night / outside_night_window), `night_hours_path` (crosses_midnight / same_day / **parse_failed_fallback_8h**), `meter_day_path`, `offset_parse_path` (by @traktore-org, refs #424)

### 📁 Audit framework

- Closed #423 (`utils/helpers.py`) as no-change. Pure stateless utility functions are an appropriate exception to the telemetry-first rule. The audit playbook explicitly recognizes "current behavior is correct, telemetry surface is sufficient" as a valid audit outcome (Step 7). Future audits of similar pure-helper modules can follow the same default (by @traktore-org, closes #423)

# [1.7.0-beta.23] - 04.06.2026

## 🧪 Beta Release — first v1.7.1 audit

_Changes since [1.7.0-beta.22](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.22)_

First behavioral audit of the v1.7.1 stabilization program (umbrella #419). Pure additive observability on `HotWaterController` — zero behavior change.

### 🔍 Diagnostics

- `HotWaterController` now publishes five decision-path strings on every call, all surfaced via `sensor.sem_load_management_status.devices.<hot_water_id>` — mirrors the #359 / #416 `classifier_path` pattern. New attributes per device: `legionella_path` (idle / natural_achievement / hold_reached_target / hold_in_progress / hold_complete / heating_to_target / overdue_start / overdue_no_sensor), `temperature_safety_path` (no_sensor_assume_safe / in_legionella_cycle_below_target / in_legionella_cycle_at_target / normal_below_solar_target / normal_at_solar_target), `temperature_reading_path` (entity_attribute / entity_attribute_invalid / separate_sensor / separate_sensor_invalid / separate_sensor_unavailable / separate_sensor_missing / no_source_configured), `activation_path` (blocked_unsafe / water_heater / climate / switch_fallback), `deactivation_path` (water_heater / climate / switch_fallback). The biggest silent-failure surface the audit identified — temperature sensor breaks → SEM keeps heating, relying only on the device's internal thermostat — is now visible as `temperature_safety_path = no_sensor_assume_safe` (by @traktore-org, refs #420)
- New `legionella_hold_elapsed_minutes` property — surfaces `5/30 min` style progress against the legionella hold target rather than a binary `legionella_cycle_active` flag. `None` when no hold is in progress (by @traktore-org, refs #420)
- New `hours_since_legionella_or_none` property — disambiguates the existing `999.0` sentinel (which means "never run") from a genuinely very-stale reading. Returns `None` cleanly when no legionella cycle has been recorded yet (by @traktore-org, refs #420)

# [1.7.0-beta.22] - 04.06.2026

## 🧪 Beta Release

_Changes since [1.7.0-beta.21](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.21)_

### 🔍 Diagnostics

- Forecast correction and dampening pipeline now publish their decision path as sensor attributes — mirrors the #359 `classifier_path` pattern. `sensor.sem_forecast_dampening_factor` carries `dampening_path` (one of `outside_daylight` / `no_forecast` / `early_morning_floor` / `blended_live`, with `+clamped_high` / `+clamped_low` suffix when the bound fires) plus `confidence`, `live_ratio`, `normalized_ratio`, `pre_clamp`, and `correction_factor_historical`. `sensor.sem_forecast_correction_factor` carries `correction_path` (one of `no_history` / `weather_month_bucket` / `weather_only_bucket` / `month_only_bucket` / `rolling_7d_fallback`, with the same clamp suffix) plus `bucket_size`, `weather_category`, and `history_days`. Lets installs hitting an unexpected ceiling self-diagnose without a maintainer reading the debug log. PROD telemetry on 2026-06-04 showed 35 % of historical correction factors pinned at the post-shrinkage ceiling with no visible signal — this attribute is the signal (by @traktore-org, refs #416)
- Daily history records now persist `dampening_factor`, `confidence`, and `live_ratio` alongside the existing `forecast / actual / weather / factor` fields, captured during the last confident mid-day cycle of each day. Pre-beta.22 records that lack these fields restore as `None` so downstream consumers can distinguish "never recorded" from "recorded as zero" (by @traktore-org, refs #416)

### 🧹 Code hygiene

- Replaced the misleading `Decay toward neutral: 25 % per day — converges in ~7 days` comment with accurate one-shot-shrinkage prose. The historical correction factor is recomputed fresh each ~10 s coordinator cycle — there is no recursive state to decay; the 0.75 weight is a one-shot ridge-regression pull toward neutral 1.0 so noisy short histories don't publish a wild correction. Numeric behaviour unchanged; constant renamed `DECAY` → `SHRINKAGE` (by @traktore-org, refs #416)

# [1.7.0-beta.21] - 04.06.2026

## 🧪 Beta Release

_Changes since [1.7.0-beta.20](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.20)_

### 🐛 Bugfixes

- Auto-migrate stored `tariff_classification_mode` from `static` → `percentile` for dynamic-tariff users on schema bump v7 → v8. Percentile became the install default in beta.12 (#373), but entries created before that still carried `static` in storage and silently fired the static-CHF-cutoff branch — visible symptom: `sensor.sem_tariff_price_level` attribute reading `classifier_path=static_fixed_cutoffs` while the live price sat well outside any reasonable static band. Calendar / explicit-static users are untouched (migration gated on `tariff_mode == "dynamic"`). Reported by @RienduPre (by @traktore-org, fixes #359)
- Cheap and expensive price-threshold number entities now accept values up to `5.00` (was `1.00`) to cover high-priced markets — Slovak prices around 1.69 €/kWh were rejected by the upper bound. Reported by @zlakes01 (by @traktore-org, fixes #417)
- Add the missing `vehicle_range_entity` and `ev_kwh_per_100km` fields to the Add Charger and Edit Charger options-flow steps. Both fields existed on the primary `ev_charger` step but were never carried over to the per-charger Add/Edit forms when #397 split the install flow in beta.16 — secondary chargers couldn't configure their own range sensor or vehicle consumption. Reported by @RienduPre (by @traktore-org, fixes #384)

## :bow: Thanks to our contributors

- @RienduPre for the precise `classifier_path` diagnosis on #359 and the Add/Edit charger flow gap on #384
- @zlakes01 for the high-tariff-market signal on #417

# [1.7.0-beta.20] - 04.06.2026

## 🧪 Beta Release

_Changes since [1.7.0-beta.19](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.19)_

### 🐛 Bugfixes

- Per-battery power tile no longer strips the sign via `Math.abs()`. The fleet tile shows `−65 W` (signed) while the per-battery tile was showing `65 W` (unsigned magnitude) — same direction badge but contradictory numbers. The underlying `power_w` values agreed (beta.19's per-battery autodetect is doing its job); the display layer was the inconsistency. Now both tiles render the raw signed value end-to-end (by @traktore-org in commit `ad198f1`, refs #404)
- Per-battery SOC ring text was `fill="white"` against the white per-battery section background → invisible on light themes. Now uses the battery accent color with a subtle dark stroke for legibility on both light and dark themes. Reported by @RienduPre (by @traktore-org in commit `ad198f1`, refs #404)

### 🚀 Features and enhancements

- Native `ev_current_control_entity` translations for the 12 remaining languages: fr, es, it, pt, pl, cs, da, fi, hu, ro, sv, no. Closes the last #400 gap — every translation file now carries the field in its own language, joining de + nl from beta.16 (by @traktore-org in #414, closes #400)

## :bow: Thanks to our contributors

- @RienduPre for catching both card-render quirks immediately after the beta.19 deploy — the sign mismatch and the unreadable SOC ring

# [1.7.0-beta.19] - 04.06.2026

## 🧪 Beta Release

_Changes since [1.7.0-beta.18](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.18)_

### 🐛 Bugfixes

- Per-battery sign autodetect: when ≥ 2 batteries are configured, each battery now runs the sign-convention detection independently using its own `battery_charge_energy_list[i]` / `discharge_energy_list[i]` counters from the Energy Dashboard. Fleet `battery_power` is rebuilt as the sum of corrected per-battery values, guaranteeing fleet ↔ per-battery agreement by construction. Supersedes the same-flip-for-all approach from #408 which would have broken dual-brand installs (e.g., Sessy + Huawei) where each battery needs an independent flip decision. Single-battery / combined-sensor installs fall back to the legacy fleet-level path via a `_FLEET_BID` sentinel — behaviour identical to today (by @traktore-org in #413, closes #404)

### 🧰 Maintenance and dependency bumps

- 7 new tests in `TestPerBatterySignAutoDetect404` covering independent per-battery state, dual-brand asymmetric flip, both-invert, neither-inverts, fallback without counters, voting threshold, and fleet/per-battery isolation. 4 existing pipeline-test monkeypatches in `test_split_grid_integration.py` updated to use the new dict-keyed state shape (by @traktore-org in #413)

## :bow: Thanks to our contributors

- @RienduPre for the careful diagnostic screenshots that exposed the fleet-vs-per-battery sign asymmetry on his Sessy install

# [1.7.0-beta.18] - 04.06.2026

## 🧪 Beta Release

_Changes since [1.7.0-beta.17](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.17)_

### ⏪ Reverts

- Revert PR #408 from beta.17. The fix was based on the assumption that SEM's `_detect_battery_sign` autodetect was flipping the fleet field but leaving the per-battery dict un-flipped — RienduPre's diagnostic screenshots on #404 show the opposite: per-battery is already canonical (`Battery b1 Power = +712 W` → charging ✓) while the fleet sensor (`Batterijvermogen = −712 W`) is the one being wrongly negated. PR #408 would have broken the already-correct per-battery tiles on Sessy installs. Re-investigating the actual root cause as a follow-up (by @traktore-org in #411, refs #404)

### 🚀 Features and enhancements

- Carries forward the temperature-row hide on multi-battery (#409) and the `classifier_path` diagnostic attribute (#410) from beta.17 — both unaffected by the #408 revert

## Known limitation

The #404 per-battery direction bug on Sessy installs is **not fixed yet** in this build — beta.18 only undoes the wrong-direction fix from beta.17. A properly-targeted fix is in flight; see [#404](https://github.com/traktore-org/sem-community/issues/404).

## :bow: Thanks to our contributors

- @RienduPre for the careful screenshots that made the revert obvious

# [1.7.0-beta.17] - 04.06.2026

## 🧪 Beta Release

_Changes since [1.7.0-beta.16](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.16)_

### 🐛 Bugfixes

- Battery card top tile no longer shows the temperature of one arbitrary battery on multi-battery installs — temperature row only renders when exactly one battery is configured. The per-battery list below already shows the correct values; the top-tile temperature was confusing because it was a fleet `max()`. Reported by @RienduPre with a 2-Sessy-battery install where the top tile temperature stayed pinned at one battery's reading (by @traktore-org in #409, closes #404)
- Battery-sign autodetect now flips each battery in the per-battery `PowerReadings.batteries` dict, not just the fleet-summed `battery_power` field — fixes a 2-Sessy regression where the per-battery list showed the wrong charge/discharge direction even though the fleet sensor was correct. Brand-agnostic fix in `sensor_reader.py` (by @traktore-org in #408, closes #404)

### 🚀 Features and enhancements

- New `classifier_path` attribute on `sensor.sem_tariff_price_level` documents WHICH branch of the tariff classifier produced the current `price_level`. Path string is one of: `percentile_active(p10=..,p25=..,p75=..,p90=..,n=..)` (happy path), `percentile_fallback_cache_empty`, `percentile_fallback_too_few_prices(n=..)`, `percentile_fallback_flat_day(spread=..)`, `static_fixed_cutoffs`, `static_ht_nt`, `calendar_schedule`, or `negative_price_shortcircuit`. Lets users in cold-start / wrong-attribute-shape / derivative-template setups self-diagnose why their level stays on `normal` (by @traktore-org in #410, refs #359)

### 🧰 Maintenance and dependency bumps

- 4 regression-lock tests in `test_per_battery_loop_375.py::TestPerBatteryDirectionStatus404` pin down the per-battery direction/status logic in `coordinator/types.py:1077-1087` (by @traktore-org in #407, refs #404)
- 4 regression-lock tests in `test_battery_sign_detect.py::TestPerBatteryDictGetsAutodetectFlip404` prove the per-battery dict gets flipped alongside the fleet field on negate-detected installs (by @traktore-org in #408, refs #404)
- 10 new tests in `test_tariff_percentile_359.py::TestClassifierPathDiagnostic` cover all 9 classifier-path strings + the end-to-end TariffData → coordinator → sensor round-trip (by @traktore-org in #410, refs #359)

## :bow: Thanks to our contributors

- @RienduPre for the multi-battery temperature-row report (#404) — exactly the kind of "looks wrong on 2 batteries" feedback that's hard to catch on a 1-battery test install

# [1.7.0-beta.16] - 04.06.2026

## 🧪 Beta Release

_Changes since [1.7.0-beta.15](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.15)_

### 🐛 Bugfixes

- Percentile tariff classifier no longer silently falls back to the CHF-calibrated static cutoffs (`< €0.15 = cheap`, `> €0.35 = expensive`) when today's price array is empty (cold start), too small (< 4 prices), or perfectly flat — returns `NORMAL` instead. RienduPre's Tibber NL install was reporting €0.30 as `normal` for hours after restart because €0.30 < €0.35 in the silent fallback. Validated via the synthetic-data reproduction script (`/tmp/sem-359-repro.py`, 5 scenarios) (by @traktore-org in #403, closes #359)
- Battery session hysteresis: a 1-hour continuous discharge no longer rolls over to a fresh 2-minute session every time the inverter rebalances. `POWER_THRESHOLD` 50 W → 200 W (dead-band wider than inverter idle drift); `IDLE_CYCLES_TO_END` 3 → 18 cycles (~3 min — covers cloud transits and sunset transitions); single-cycle opposite-direction blips no longer end the session (requires 3 consecutive opposite cycles) (by @traktore-org in #406, closes #405)
- `de.json` ev_charger config-flow step translated to native German end-to-end — title, description, 8 labels, 8 descriptions. Closes the PR #388 "out of scope" deferred sweep (by @traktore-org in #402, refs #400)
- `nl.json` `ev_current_control_entity` label + description translated to native Dutch — closes the PR #390 English-placeholder gap that hit RienduPre's Wallbox setup directly (by @traktore-org in #402, refs #400)

### 🚀 Features and enhancements

- Slim config-flow screenshots embedded in `docs/SETUP_GUIDE.md` step 1 / 2 / 3, plus a new "First-run welcome notification" subsection documenting the `_welcome_notification_fired` one-shot behaviour from #397 (by @traktore-org in #401)
- `docs/SETUP_GUIDE.md` gains a "Price classification" subsection under Tariff and Pricing settings — explains percentile vs static modes + the cold-start NORMAL behaviour so users on non-CHF tariffs see the documented behaviour first instead of filing #359 again (by @traktore-org in #403)

### 🧰 Maintenance and dependency bumps

- 7 tests in `tests/test_tariff_provider.py` updated to pass `classification_mode="static"` explicitly — they were asserting the static-cutoff bucketing but constructing a percentile-default provider, only passing because of the silent CHF fallback we just removed (by @traktore-org in #403)

## Known follow-ups under #400

13 other languages (fr, es, it, pt, pl, cs, da, fi, hu, no, ro, sv) still carry English placeholders for `ev_current_control_entity`. Native translations welcome on a per-language basis.

## :bow: Thanks to our contributors

Special thanks to the following users who helped with this release:

@traktore-org, @RienduPre (for the diagnostic-data thread that exposed the percentile classifier's cold-start path)

# [1.7.0-beta.15] - 04.06.2026

## 🧪 Beta Release

_Changes since [1.7.0-beta.14](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.14)_

### 🐛 Bugfixes

- Config flow step 2 (EV charger) slimmed from 16 fields back to 5: 8 per-charger tunables from PR #390 reverted to OptionsFlow where they belong by design. `ev_current_control_entity` stays for Wallbox-style chargers (by @traktore-org in #398, closes #397)

### 🚀 Features and enhancements

- First-run persistent notification with dashboard deep-link + 3-item checklist; gated to one-shot per install via `_welcome_notification_fired` options flag; skipped on `observer_mode` (by @traktore-org in #398, refs #397)
- ADR 0002 split into 0002 (data-model: `EVBudget` unification) + 0009 (distribution: multi-charger allocation) — each ADR now accurate to its scope (by @traktore-org in `aca2a00`)
- ADRs 0006-0008 added: real-hass test framework, dashboard bundle architecture, and the architecture-record meta-decision (by @traktore-org in #396)
- `CONTRIBUTING.md` test pyramid updated from 3 layers to 4 (unit / scenario / **real-hass** / live), referencing ADR 0007 (by @traktore-org in `aca2a00`)

### 🧰 Maintenance and dependency bumps

- ADR code-link drift fixed in 0002 + 0004 — references the actual function/file anchors now (by @traktore-org in #396)
- First 5 ADRs (0001-0005) added in `docs/adr/` — PerChargerContext, EVBudget unification, sign convention boundary, home_consumption_power clamp, pipeline-test-per-brand mandate (by @traktore-org in #394, kept in #395)

## :bow: Thanks to our contributors

Special thanks to the following users who helped with this release:

@traktore-org

# [1.7.0-beta.14] - 04.06.2026

## 🧪 Beta Release

_Changes since [1.7.0-beta.13](https://github.com/traktore-org/sem-community/releases/tag/v1.7.0-beta.13)_

### 🐛 Bugfixes

- KEBA failsafe watchdog drop after steady-state charging: same-value `set_current` writes now refresh past a 60 s heartbeat window so the device watchdog stays alive. Generalised to all current-controlled chargers (by @traktore-org in #393, closes #392)
- Same-value heartbeat write also re-converges device-side and SEM-side state after silent device resets (replug fallback, KEBA reboot, failsafe trip) — no more "SEM thinks 16 A, KEBA at 6 A, stuck forever" mode (by @traktore-org in #393)

## :bow: Thanks to our contributors

Special thanks to the following users who helped with this release:

@traktore-org

## [1.7.0-beta.13] — 2026-06-03

The **#359 percentile classifier follow-up**.

### Fixed

- **#359** (PR #391) — RienduPre reopened #359 with screenshots showing
  €0.30 still labelled `normal` / `cheap` after the percentile fix
  shipped in beta.3. Root cause: `_get_percentile_breaks` and
  `get_tariff_data` filtered today's prices with a bare
  `p.timestamp.date()`. Providers differ on the tz they emit — Tibber
  is local, Nordpool-class integrations (incl. several Dutch dynamic-
  tariff implementations) are often UTC. On +02:00 (Europe/Amsterdam
  summer), a UTC-tagged price at 22:00 UTC = 00:00 local-next-day,
  and a bare `.date()` returns the UTC date. Today's filtered array
  dropped below the 4-point minimum, percentile breaks returned
  `None`, and the classifier silently fell back to the static
  €0.15 / €0.35 cutoffs — where €0.30 < 0.35 = `normal`. Exactly the
  symptom.

  Fix: new `_local_date(timestamp)` helper converts via
  `dt_util.as_local` for tz-aware datetimes and passes naive
  datetimes through unchanged (keeps the existing tariff tests, which
  mock `dt_util` and build naive clocks, green without modification).

### Added

- **Tariff diagnostics** (PR #391) — three DEBUG log lines under the
  `tariff/#359` tag so a repro is now trivial:
  - `percentile fallback — today's price array has X/Y points` when
    the array drops below the 4-point minimum (the typical failure
    mode pre-fix).
  - `degenerate distribution — p90-p10=X` when the M1 flat-day guard
    trips.
  - `percentile breaks for <date> — p10/p25/p75/p90` on the happy
    path so users can sanity-check the math against their tariff.

## [1.7.0-beta.12] — 2026-06-03

Per-charger refinements + EV config-flow parity. Bundles the
undocumented beta.11 (#355 affordance) so the changelog is complete from
beta.10 to beta.12.

### Fixed

- **#383** (PR #385) — In multi-charger installs every per-charger card
  showed the same vehicle SOC. The coordinator was overwriting one
  shared `_cycle_vehicle_soc` from each charger's `vehicle_soc_entity`
  inside the per-charger loop; the global sensor reported whichever
  charger ran last, and the card's `_val('charger_<id>_vehicle_soc') ??
  _val('vehicle_soc')` lookup chain always fell through to the global.
  Now publishes per-charger SOC via `charger_<cid>_vehicle_soc`, with
  the unconfigured case returning `None` (not a fabricated zero).

- **#384** Part 1 (PR #388) — The "Add EV Charger" options-flow step had
  translation coverage for only two fields (Solar charge limit kWh /
  SOC%); the rest of the form fell back to the raw key on non-English
  installs. Mirrored `ev_charger_edit` `data` / `data_description` into
  `ev_charger_add` for all 15 languages.

- **#384** Part 2 (PR #390) — The initial setup flow couldn't configure
  Wallbox-style chargers (number entity for current control) because it
  lacked `ev_current_control_entity`. The user had to finish setup with
  a partial config and then drop into Options → Edit. Initial flow now
  exposes the full per-charger override set: `ev_current_control_entity`,
  `ev_surplus_priority`, `daily_ev_target` + `_max`,
  `ev_night_initial_current`, `ev_min_current`, `ev_target_soc` + `_max`,
  `ev_battery_capacity_kwh`. `_EV_KEYS` bridge extended so they migrate
  into `ev_chargers[0]`. `vehicle_soc_entity` deliberately stays in
  OptionsFlow only — asking on install creates a dead input for users
  without a vehicle SOC sensor.

- **EV stall detector** (PR #389) — Detector was anchoring SOC=100% even
  in cycles where SEM had never commanded charge, producing false-stall
  alerts when the EV was simply sitting fully-charged with the cable
  plugged in. The anchor now requires a SEM-issued charge command.

### Added

- **Per-battery sensors + fleet/per-battery card** (PR #386 — Phase A + B)
  — first cut of a multi-battery model. Adds per-battery state, energy
  and power sensors, plus a dashboard card that shows fleet totals and
  per-battery detail.

- **Battery card session duration** (PR #387) — sessions over 90 minutes
  are shown as hours (`2h 15m`) instead of `135m`, matching how users
  think about long battery discharges.

- **#355 split affordance on stacked range handles** (PR #380) — a
  tappable split (↔) icon appears whenever the Min/Max handles of the
  EV target range slider visually overlap (within 2 % of the slider
  span). One tap drops Min by 2 % so the stacked handles become
  individually grabbable. Works in kWh and SOC % modes.

- **`per_charger: true` on `sem-chart-card` EV preset** — optional
  per-charger color breakdown driven by discovered
  `sensor.sem_charger_<id>_power` entities.

### Changed

- **EV chart "today" period** (in PR #380) — was rolling 24h, which
  painted yesterday-evening charges as a phantom second event. Now
  anchored at local midnight to match `daily_ev_energy`.

### Removed

- Per-charger **"Set target as default"** button (PR #380). HA's
  number-entity state restoration already persists slider values across
  restarts; the button's "copy to global defaults" workflow was niche on
  installs that grow new chargers later. Existing entries are
  auto-cleaned on the next setup.

## [1.7.0-beta.10] — 2026-06-02

The **#356 ghost-charger** fix.

### Fixed

* **#356** — EV / charger status cards rendered ghost sections per real
  charger, appearing as duplicate cards titled `<Charger Name> Solar → EV`,
  `<Charger Name> Grid → EV`, `<Charger Name> Battery → EV`. Each ghost
  duplicated the SOC gauge, charge target slider, mode dropdown and
  `Klaar om` timer — only the power value differed, matching the per-flow
  attribution.

  Root cause: the charger auto-discovery regex in both
  `dashboard/card/src/cards/sem-ev-status-card.js` and
  `sem-charger-status-card.js` was greedy:

  ```javascript
  const match = eid.match(/^sensor\.sem_charger_(.+)_power$/);
  ```

  It matched both real charger sensors (`sensor.sem_charger_<id>_power`)
  AND the per-charger flow sensors
  (`sensor.sem_charger_<id>_flow_solar_to_ev_power` etc.). The flow
  sensors were added in v1.6.9 (`feature/169-per-charger-flows`) for the
  flow card — they were never meant to register as chargers. Every
  multi-charger install where `sensor.py:1633-1695` emits flow sensors
  (gated on `len(ev_chargers) > 1`) got 3 ghost sections per real charger.

  Fix: `if (eid.includes('_flow_')) continue;` guard before the regex
  match in both card files. Bundle rebuilt — content-hashed resource URL
  invalidates browser cache on upgrade.

  Earlier #356 fixes (`e733212` PR #371 hero-collapse, `68cee34` M3
  bottom-bar gate) targeted a different (real but smaller) duplication
  pattern inside one card; they couldn't address the ghost-section
  cascade because the source was upstream in the discovery loop.

### Tests

`tests/test_356_charger_discovery_filter.py` — source-level lint
asserting both card files contain the `_flow_` guard inside the
discovery window, plus a property-style test feeding sample entity IDs
through the regex+guard combination to confirm flow sensors are rejected
and real charger IDs (including those with legitimate underscores like
`laadpaal_links`, `ev_charger`, `keba_p30`) still resolve correctly.

**Total suite: 2904 passed, 0 failed, 0 xfailed.**

## [1.7.0-beta.9] — 2026-06-02

**Hotfix on top of beta.8.** No SEM logic changes — purely a dashboard
card render bug + a missing translation. Users who installed beta.8 saw
an invisible `sem-solar-card` (the bug below) and a raw key
`PV_STRINGS_TODAY` in the per-string section.

### Fixed

* **sem-solar-card was rendering as a 0x0 element on every viewport.**
  The `html\`...\`` Lit template at `sem-solar-card.js:406` contained
  literal backticks (markdown-quoted `nothing`). JavaScript read those
  as terminating the outer template literal — Lit's minified `html` tag
  threw `H(...) is not a function` at parse time. HA's lovelace renderer
  swallowed the console error and left an empty shadowRoot, so the card
  was conspicuously missing on mobile.
* **Missing `pv_strings_today` translation.** The per-PV-string section
  title rendered as the raw key `PV_STRINGS_TODAY` (CSS upper-casing the
  missing key) instead of the translated string. Added to all 15
  supported languages.

Both fixes target the bundled card (`dashboard/card/dist/sem-cards.js`
was rebuilt) — they take effect after the next browser cache-bust on
upgrade.

## [1.7.0-beta.8] — 2026-06-02

The **disagreement-audit close-out + KEBA solar-flicker resilience** release.
Lands every remaining item from the post-#349 umbrella audit (#351 — 13/13
closed), the KEBA actuator IDLE debounce that prevents transient solar-sensor
dropouts from cascading into "authorization rejected", and a multi-inverter
PV-strings discovery fix surfaced by @RienduPre's #378 dump.

### Fixed

* **#351 H1** — Per-charger `_calculate_remaining_need` now reads
  `self._daily_ev_per_charger.get(cid, energy.daily_ev)` when `charger_cfg`
  is set. Pre-fix charger B's "target reached" check was polluted by
  charger A's energy.
* **#351 H2** — Forecast night-target reduction applied per-charger inside
  the multi-charger loop, gated on `_mode_uses_smart_night(cfg)`. Secondary
  chargers no longer ignore the "tomorrow is sunny → skip tonight" decision.
* **#351 M1** — Cost accumulators (daily / monthly / yearly) now round-trip
  through `Storage.export_energy_calculator_state`. Pre-fix `daily_savings`
  silently reset to 0 mid-day after every HA restart while
  `daily_solar` resumed from disk.
* **#351 M2** — `CostData.daily_total_savings` (+ monthly / yearly variants)
  now computed as the headline number spanning solar + battery savings.
  Pre-fix `daily_savings` (solar-only) was the only surfaced number and
  understated savings on battery-assist days.
* **#351 M3** — Per-charger session reads `power_flows.per_charger[cid]`
  directly when populated, preserving the priority-correct attribution.
  Pre-fix the proportional re-split discarded the priority signal that the
  flow calculator just computed.
* **#351 M4** — Per-charger effective states surface as
  `charger_<id>_charging_state` on `coord.data` and as the
  `per_charger_states` dict on the `sem_charging_state` sensor. Mixed-mode
  fleets now show the disagreement explicitly instead of hiding behind the
  fleet headline.
* **#351 M5** — `SurplusController.distribute_ev_budget` accepts an
  `excluded_charger_ids` set; chargers in `charge_mode=off` get 0 W
  allocation (dashboard still sees the entry).
* **#351 M6** — `notify_ev_nearly_full` gates on this charger's
  `power.ev_power_per_charger.get(cid)` instead of the fleet `ev_charging`
  flag.
* **#351 M7** — Per-charger session-end falls back to
  `power.ev_connected_per_charger.get(cid)` when no per-charger plug
  sensor is configured. Pre-fix per-charger sessions could never end while
  another charger was plugged in.
* **#351 M8** — `_skip_recorded_tonight` converted to
  `Dict[str, bool]` keyed by charger_id; per-charger intel builder
  records skips per-charger so charger A's skip no longer masks
  charger B's independent counter.
* **#351 M9** — Eliminated mutable-attr-read pattern in
  `_build_charging_context` and the per-charger loop. Both call sites
  now capture `self._cycle_vehicle_soc` into a local before the two
  `_calculate_remaining_need` calls.
* **#351 M10** — `SOLAR_PAUSE_STATES` clears `_ev_charge_started_at`.
  Pre-fix the disable-delay timer was consumed during a battery-priority
  pause and the very next cycle's terminal branch fired stop_session
  even though we just resumed.
* **#351 M11** — Night-skip notification gates on
  `_mode_allows_night_charging(cfg)`. Modes `off` / `solar_only` no longer
  get spurious "skipped night charge" pushes.
* **#351 L1** — `_update_battery_session_tracking` integrates against
  `self.update_interval.total_seconds()` (the actual cycle time) not
  `config["update_interval"]` (the requested one). Under HA load the two
  diverge and the battery-session counter drifted.
* **#351 L2** — `FlowCalculator.calculate_energy_flows` emits
  `DeprecationWarning` from the body. The proportional-allocation path is
  un-canonical; `integrate_energy_flows` is the timing-aware production
  path.
* **#378** — `discover_pv_strings_from_registry` now honours the explicit
  `solar_power_list` from the HA Energy Dashboard when it has ≥2 entries.
  Pre-fix the discoverer scoped sibling-scan to the seed's `config_entry`,
  silently dropping cross-inverter MPPTs and leaking entities not in the
  user's dashboard. @RienduPre's multi-inverter setup (3 entries in
  `solar_power_list`) now surfaces all 3 as `pv1`/`pv2`/`pv3`.

### Added — KEBA solar-flicker resilience

* **IDLE debounce in the actuator** (`coordinator/actuate.py` +
  `ChargerAdapter.attempt_idle` + `reset_idle_debounce`). When a transient
  solar-sensor reading triggers a 1-cycle `intent=idle`, the actuator
  holds the previous setpoint instead of immediately calling `keba.disable`.
  Default threshold = 4 cycles (~40 s grace). Catches the pattern observed
  live on PROD 2026-06-02: Huawei sensor flicker 8 kW → 0 W → 8 kW within
  10 s → `keba.disable` → KEBA stuck in "authorization rejected" until
  physical replug. Real cloud passes (>40 s) still cross the threshold and
  `command_idle` fires normally.
* Debounce state lives on `ChargerAdapter` (per-charger, not a module-level
  dict) so multi-charger fleets count independently per charger.
* INFO-level log on both branches:
  `actuate(<cid>): IDLE — count=N/4 — <reason>` (fired) or
  `actuate(<cid>): IDLE DEBOUNCED — count=N/4, holding previous setpoint`
  (absorbed).

### Tests

* `test_351_umbrella_regression.py` — 23 tests covering every umbrella
  item (per-fix assertions + structural anchor lint).
* `test_379_growatt_pv_strings.py` — 3 new tests for #378 (multi-inverter
  list wins, single-entry falls through, empty list preserves legacy).
* 3 new edge-case scenarios + harness extensions for per-cycle
  `tariff_level` and the negative `strategy_not_substring` assertion.

**Total suite: 2900 passed, 0 failed, 0 xfailed.**

### Known not-fixed

* **#356** — duplicate tiles in the EV dashboard. @RienduPre confirms the
  symptom persists on beta.6 (which has the hero-collapse + bottom-bar
  fixes). Needs a UI screenshot to identify the remaining duplication
  source — replied on the issue asking for one. Target beta.9.
* **Solar sensor flicker root cause** — the actuator debounce is a
  band-aid. The Huawei inverter's intermittent 0 W readings should be
  EMA-smoothed in `coordinator/sensor_reader.py`. Separate issue worth
  filing.

## [1.7.0-beta.7] — 2026-06-02

The v1.7 arch capstone — the **FleetCycleState refactor** that
structurally retires the gap class behind the three production fixes
shipped in beta.5 (SOLAR_ONLY redirect, tariff_level, night-plan
ordering). Plus 4 more transition-class scenarios.

### Production refactor — FleetCycleState as single source of truth

The three beta.5 production fixes were tactical patches for one
structural smell: `build_charger_view` had each call site
re-resolving fleet-level inputs (forecast, tariff, is_night, etc.)
independently. The primary view in `_build_charging_context` and
the multi-charger loop each handled this differently — and any
new fleet input added would land in only one of them.

The fix: **`FleetCycleState`** — an immutable per-cycle struct
holding every fleet-level input that any charger's `decide()` could
need. Built ONCE per cycle by
`coordinator._build_fleet_cycle_state`. `build_charger_view` now
takes it as the first positional arg and derives the per-view
`FleetContext` from it. Per-charger overrides (`target_kwh`,
`deadline_amps`, `tariff_wait`, `solar_committed_w`) stay as direct
kwargs because they legitimately vary across chargers in the same
cycle.

What this eliminates:

* The 3 separate inline blocks resolving forecast/tariff/is_night
  per call site
* The asymmetry where multi-charger loop saw `tariff_level` but
  primary didn't (and similar for other fields)
* The "did I remember to plumb the new field?" mental load every
  PR that touches fleet state

The structural guarantee: any future fleet-level input is a
**one-place change** (add the field to `FleetCycleState`).

### Enforcement — AST lint as a CI gate

`tests/test_fleet_state_completeness.py` walks `coordinator/` AST
and fails CI if any `build_charger_view` caller:

  * Forgets the `fleet_state` positional, OR
  * Passes any of the deprecated fleet-level kwargs (`power_reading`,
    `is_night`, `config`, `tariff_level`, `forecast_remaining_kwh`)

Catches the regression class on PR review, not at runtime. Same
shape as the existing FLEET-READ AST lint at
`tests/test_ev_control_fleet_reads.py`.

### Invariant tests

`tests/test_fleet_cycle_state.py` pins the behavioural contract:

  * `FleetCycleState` is frozen — instances cannot mutate
  * Equal inputs produce equal instances (value-type semantics)
  * Two views built from the same `FleetCycleState` in the same
    cycle agree on every fleet-level field (only
    `solar_committed_w` differs per view, by design)

### Transition-class scenarios

Four new YAML scenarios in `tests/scenarios/` covering state
transitions that steady-state scenarios miss:

* `sunset_transition` — solar drops + `is_night` flips false→true.
  solar_only must IDLE on the night-mode flip.
* `sunrise_transition` — mirror: `is_night` true→false + solar
  rising. min_plus_solar transitions cleanly out of MIN_PV.
* `multi_charger_plug_events` — two solar_only chargers, one
  unplugs mid-timeline. Pins per-charger budget conservation
  under plug-state changes.
* `full_day_replay` — 24h walkthrough on 10-min cycles (144
  cycles, runs <1s). Catches daily-integrator drift, state
  machine blips on zone boundaries.

Plus two harness extensions enabling these:
`ev_connected_per_charger` / `ev_charging_per_charger` (per-charger
plug state) and a per-row `is_night` override (for sunset/sunrise
walks).

### Verification

2879 tests passing, 7 skipped, 0 failed, 0 xfailed (~35s runtime).
+16 tests since beta.6 (4 scenarios + 7 FleetCycleState contract
tests + 4 misc + the AST lint's 3).

22 scenarios total now.

---

## [1.7.0-beta.6] — 2026-06-02

Diagnostic surface expansion for two more reported issues — same
pattern as beta.5's `per_source_lists` (one-shot triage from the
diagnostics dump alone).

### Diagnostics

- **#379 — PV string discovery state.** New
  `pv_strings_discovery` top-level block surfaces what the
  `_sensor_reader` resolved from both the direct-power-pattern
  scan and the V+I synthesis pair scan. Lets a "PV2 is empty"
  report be triaged in one shot: empty dict → discovery missed
  entirely; partial dict → one pattern matched but others didn't;
  full dict → bug is downstream in the card rendering.

- **#357 — Per-charger adapter state.** New `charger_adapters`
  top-level block surfaces the resolved adapter class +
  brand-specific discovery state per charger. For `WallboxAdapter`
  specifically:
  `wallbox.pause_switch_searched`, `pause_switch_entity`,
  `pause_switch_discovered`. Lets a "Wallbox keeps charging
  despite mode=off" report point at the failing step on the
  first dump: false → the discovery couldn't find a
  `switch.*pause_resume` entity for this Wallbox model;
  true → adapter wired right, problem is downstream.

### Verification

2863 tests passing, 7 skipped, 0 failed, 0 xfailed (~35s runtime).
4 new tests in ``tests/test_357_wallbox_diagnostics.py``.

---

## [1.7.0-beta.5] — 2026-06-02

Testing-framework adoption + three structural arch fixes + diagnostic
surface for fleet-aggregation bug triage. Built on top of beta.4.

### Production fixes (post-#358 arch follow-up)

- **`SOLAR_ONLY` forecast-aware battery redirect restored.** Post-arch
  `decide.py::SolarOnlyMode` was checking bare surplus against the
  charger min (4140W), returning IDLE, and the canonical strategy
  chain collapsed to IDLE — so the redirect branch in
  `flow_calculator.calculate_canonical_ev_budget` was unreachable.
  Fix: extracted `battery_redirect_w` as a module-level helper,
  plumbed `forecast_remaining_kwh` through `FleetContext` +
  `build_charger_view`, made `SolarOnlyMode.decide()` add redirect
  to its surplus calculation BEFORE the min check. Caught by
  scenario `tests/scenarios/2026-05-29_budget_unify_redirect.yaml`.

- **`tariff_level` plumbed into primary view.**
  `SolarPlusCheapMode.decide()` reads `view.fleet.tariff_level` for
  the expensive-window pause (#247), but the primary view was being
  built without it (was `None`). Fix: pull `current_level` from
  `_tariff_provider` and pass to `build_charger_view`.

- **Night-plan ordering — hoisted before primary view.**
  `_compute_night_plan` was computed AFTER the primary view's
  `decide()` ran, so `tariff_wait` (#247) and `deadline_amps`
  (#246) didn't reach `SolarPlusCheapMode` / `MinPlusSolarMode`
  for the primary charger. Fix: hoisted the plan to before the
  primary view in `_build_charging_context`.

All three are the same class — info the legacy
`_determine_charging_strategy` had access to wasn't fully plumbed
into the new `decide.py` path. A structural refactor to eliminate
the gap class (single `FleetCycleState` builder + AST lint) is
planned for v1.8.

### Diagnostics — #378 triage support

- `diagnostics.py` now captures `energy_dashboard.per_source_lists`
  (`solar_power_list` / `battery_power_list` / `grid_power_list`
  from the Energy Dashboard config) AND
  `energy_dashboard.per_source_readings` (each entity's current
  state, or `{"state": "missing"}` if it disappeared from
  `hass.states`). For multi-inverter / multi-battery / multi-grid
  setups, this makes "fleet sensor underreports" reports one-shot
  triagable from the diagnostics dump alone.

  Triage flow: open `per_source_lists.battery_power_list`, compare
  against what the user reports they have. If the list is missing
  an entity → bug is in discovery / HA Energy Dashboard config. If
  the list has the entity but reading is `"missing"` or
  `"unavailable"` → bug is in the sensor source itself.

### Testing framework adoption

Adopted `pytest-homeassistant-custom-component==0.13.205` (the
official HA test framework — used by HACS itself, ~30 of Frenck's
integrations, required by Quality Scale Silver+). SEM is already
declared `quality_scale: platinum`; this work validates that claim
structurally.

- Real `HomeAssistant` fixture for config-flow, services, migrations,
  and the scenario harness — replaces dict-mock approach where it
  matters for end-to-end correctness.
- Legacy `hass` fixture renamed to `mock_hass` via AST-aware libcst
  rewrite (35 files, 419 test signatures). No behaviour change in
  existing tests; the framework's `hass` fixture is now usable.
- Migration chain (`async_migrate_entry` v1→v7) now has 8 real-hass
  tests covering every hop + the full chain composition.

### Scenario suite — wired into CI for the first time

The 5 scenario YAMLs in `tests/scenarios/` had been silently broken
since PR #358: the harness called the deleted
`_determine_charging_strategy` inside a bare `try/except: pass`, so
every cycle produced `strategy=None`, `budget=0`, `amps=0` — and the
scenarios "passed" on the null outputs. The harness now drives the
real production decision path (`coord._build_charging_context`),
raises loudly on `AttributeError`, and is wired into pytest
discovery via `tests/test_scenarios.py`.

Eight new YAML scenarios mined from closed bug issues — one per
EV-charge-mode × regime cell:

- `solar_only/night_must_idle` (#346)
- `solar_only/zone3_day_redirect` (#282)
- `min_plus_solar/zone3_day_battery_assist` (#282)
- `min_plus_solar/night_top_up_at_min` (#268)
- `min_plus_solar/night_deadline_floor` (#246)
- `solar_plus_cheap/day_normal_tariff` (#247)
- `solar_plus_cheap/night_cheap_window_charges` (#247)
- `always_max/ignores_zone_and_tariff`
- `multi_charger/priority_cascade_with_mixed_modes`

Plus `tests/test_scenario_coverage.py` — a matrix test that fails
listing missing cells with their issue hints. New EV-charge modes or
regimes that land without scenario coverage fail CI with a clear
to-do.

### Property-based invariants

`tests/test_budget_invariants.py` — 10 `hypothesis`-driven tests over
the canonical EV budget math. Invariants: `net_w >= 0` and finite
across all 6 strategies, IDLE always zero, NOW returns override,
`SELF_CONSUMPTION` never includes redirect, `SOLAR_ONLY net_w ==
solar_surplus + battery_redirect`, amps floored not rounded.

### User-reported regression guards

- **#378** (multi-battery aggregation) — 6 tests pinning
  `PowerReadings` + `fleet_battery_w` so future arch changes can't
  silently drop a battery from the sum.
- **#379** (Growatt PV-string discovery) — 5 tests pinning Growatt
  naming patterns + the "missing entity" diagnostic path.
- **#307** (pool heat pump as surplus device) — 7 tests verifying
  `SurplusController` dispatch to non-EV devices.
- **#49** (surplus controller restart safety) — 5 tests pinning that
  `ControllableDevice` defaults to `PEAK_ONLY` (so SEM never
  proactively activates a device the user didn't opt into).
- **#353** (KEBA 0A self-charge) — 19 adapter-unit tests pinning that
  `command_current(<6A)` always routes to `command_idle()` (=
  `keba.disable`), never `set_current(0)`.

### Internal

- 2859 tests passing, 7 skipped, 0 failed, 0 xfailed (~34s runtime).
- Release workflow now installs from `tests/requirements_test.txt`
  (was a hardcoded list missing `pytest-homeassistant-custom-component`).

---

## [1.7.0-beta.4] — 2026-06-02

Private beta (not published to HACS) — bundles the multi-device
architecture follow-up on top of beta.3 for an internal PROD soak.

### Fixed
- **#375** — True per-battery control loop. `_battery_adapter`
  (singular) → `_battery_adapters: Dict[str, BatteryControlAdapter]`;
  `_run_battery_pipeline` iterates `power.batteries`, dispatching
  `decide_battery` / `actuate_battery` per battery with its own
  cached adapter. Closes the architectural gap the v1.7.0 rebuild
  left behind for 2× same-brand installs (2× Huawei LUNA2000,
  2× GoodWe). Single-battery installs see zero behavioural change
  (PR #376).

## [1.7.0-beta.3] — 2026-06-01

Beta batch addressing 5 open user-reported issues + dead-code cleanup
from #351's audit deferred list.

### Fixed
- **#352** — Manual `grid_sign_invert` config option for Enphase and
  other inverters where the energy-counter auto-detect can't
  stabilise on the grid power polarity (PR #370).
- **#355** — Bumped EV target slider max from 100 to 200 kWh so the
  Min and Max handles have drag-room when both sit at the previous
  cap (PR #368).
- **#356** — Collapsed the duplicated hero metrics on the EV status
  card when per-charger sections render — the gate was `> 1`
  instead of `>= 1`, so 1-charger installs saw both layers. Hero
  now shows only Status + Power when ≥1 charger sections will
  render below (PR #371).
- **#357** — New dedicated `WallboxAdapter` that auto-discovers the
  Wallbox `pause_resume` switch from the HA entity registry and
  toggles it explicitly on `command_idle` / `command_disable` in
  addition to `_set_current(0)` + `stop_session()`. Closes the
  v1.6.17 reporter's bug where mode=off didn't stop the Pulsar
  (PR #372).
- **#359** — Percentile-based tariff price classification (default
  for dynamic tariffs). The legacy static 0.15/0.35 CHF cutoffs
  mis-bucketed everything on Tibber/Octopus/Amber/Nordpool where
  daily ranges span €0.05–€0.80. Buckets now compute relative to
  today's 24h distribution. Static mode preserved as opt-out
  (PR #373).

### Removed
- `coordinator._execute_battery_charge_scheduler` (91 LOC) and
  `coordinator.BatteryProtectionMixin._apply_battery_discharge_protection`
  (66 LOC) — both retired by the v1.7.0 per-device-primary
  rebuild; zero live callers since the `_run_battery_pipeline`
  flip. `BatteryProtectionMixin` survives this release with only
  `_restore_battery_discharge_limit_on_startup` (planned full
  retirement in v1.7.1) (PR #369).

## [1.7.0] — 2026-06-01

Major release. Two headline themes:

1. **Multi-device architecture rebuild** — every multi-device data
   point in SEM (chargers, inverters, batteries, PV strings) now
   flows through the same per-device-primary pattern: `Dict[str, X]`
   is the source of truth, fleet aggregates are `@property` views.
   Brand hardware quirks (KEBA's 6 A minimum, set_current(0)
   rejection, self-resume detection, Huawei/GoodWe battery force-
   charge) are encapsulated in dedicated adapter modules. EV
   control flows through one pure `decide(view) → ChargerDecision`
   → `actuate(decision, adapter)` pipeline; batteries get the same
   `decide_battery / actuate_battery / BatteryControlAdapter`
   treatment. The strategy/state-machine disagreement class that
   produced the 14-bug cluster between v1.6.0 and v1.6.17
   (#243, #284, #289, #290, #291, #308, #315, #316, #318, #344,
   #345, #346, #349, #353) is **structurally retired** — those
   disagreements cannot exist by construction because there's only
   one decision authority per device per cycle.

2. **Per-PV-string visibility (#312)** — Sunsynk-style per-string
   display on three SEM cards, plus V+I synthesis for inverters
   that expose voltage and current but no per-string power.

The architecture work shipped as four PRs into develop (#358 EV
rebuild, #360 inverter+battery PowerReadings dicts, #361 battery
decide/actuate/adapter, #362 EnergyTotals @property views, #363
93 surplus-charging scenario tests). The per-PV-string work
shipped as three PRs (#337 data layer, #338 cards, #339 docs).
All consolidated under one release tag.

### Architecture rebuild — what changed structurally

**Per-charger primary** (PR #358, 8 steps):
- New frozen types in `coordinator/charger_types.py`: `ChargerPower`,
  `ChargerEnergy`, `ChargerIntent`, `ChargerDecision`, `ChargerView`,
  `FleetContext`, `FleetView`, plus the symmetric inverter/battery
  types (PR #360/#361).
- `ChargerAdapter` ABC + `KebaAdapter` + `GenericAdapter` in
  `coordinator/charger_adapters/`. Every KEBA quirk that bit
  production (6 A min, set_current(0) rejection, self-resume on
  plug-in, charging_state lag, 500 W handshake cutoff) is one
  method on this protocol. New brands subclass; the actuator never
  changes.
- Pure `decide(view) → ChargerDecision` in `coordinator/decide.py`
  with one `ModeStrategy` class per charge mode (`off`,
  `solar_only`, `min_plus_solar`, `always_max`, `solar_plus_cheap`).
  No `self`, no HA calls — same input always produces the same
  output.
- `actuate(decision, adapter)` in `coordinator/actuate.py` — pure
  intent dispatch. One branch per `ChargerIntent`. The
  #315/#346/#353 self-resume guards collapse into one
  `adapter.is_self_charging()` check before the new intent is
  applied.
- Coordinator `_per_charger: Dict[str, ChargerRuntime]` consolidates
  what used to be 8 parallel `_*_per_charger` dicts.
- The legacy `_determine_charging_strategy`,
  `_self_consumption_strategy`, `_zone_based_strategy`,
  `_canonical_strategy_from_legacy`, and the `_raw_zone`/`_get_zone`/
  `_debounce_zone` helpers — **deleted** (−354 lines in
  `coordinator.py`). The new pipeline is the only control path.
- Per-charger native priority flow attribution in
  `flow_calculator.py`: when multiple chargers consume from the
  same surplus, the priority allocator splits sources in order
  (higher-priority chargers get first claim on solar, fall back to
  battery, fall back to grid). Replaces the pre-#349 proportional
  fraction-of-fleet split.

**Per-inverter + per-battery primary** (PR #360, #361, #362):
- `PowerReadings.inverters: Dict[str, InverterPower]` and
  `PowerReadings.batteries: Dict[str, BatteryPower]` — populated by
  `sensor_reader` for multi-device installs (`len(...list) > 1`).
- `@property fleet_solar_w`, `fleet_battery_w`, `fleet_battery_soc`
  on `PowerReadings` — sum / capacity-weighted-average from the
  dicts. Empty dict on single-device installs → falls back to the
  legacy `solar_power` / `battery_power` / `battery_soc` fields.
  Zero churn for existing consumers.
- `EnergyTotals.per_inverter` / `per_battery` dicts plus
  `daily_solar_view` / `daily_battery_charge_view` /
  `daily_battery_discharge_view` `@property` accessors. Same
  fallback discipline.
- New `coordinator/battery_adapters/` module unifies what used to
  live in two separate places: discharge limiting (the legacy
  `BatteryProtectionMixin`) and forced charging (the legacy
  `BatteryChargeAdapter`). `BatteryControlAdapter` is one ABC with
  four methods (`command_normal`, `command_limit_discharge`,
  `command_force_charge`, `command_stop_force_charge`); each maps
  1:1 to a `BatteryIntent`. Huawei, GoodWe, and Generic adapter
  implementations wrap the existing brand-specific service calls.
- `decide_battery(view) → BatteryDecision` and
  `actuate_battery(decision, adapter)` — same pure-pipeline shape
  as the EV side. Replaces the dual-axis legacy split
  (`BatteryProtectionMixin._apply_battery_discharge_protection` +
  `BatteryChargeScheduler.update`).
- The pure planner `BatteryChargeScheduler.evaluate()` is preserved
  verbatim — it produces a `SchedulerDecision` that feeds
  `BatteryView.scheduler_decision`. Only the dispatch path changed.

**Invariant test suite** (PR #358 + #363):
- `tests/test_step8_invariants.py` — **233 architectural contracts**
  parametrised across `(mode × solar × battery_soc × home ×
  is_night × num_chargers)`. Each invariant pins one property the
  architecture is supposed to guarantee by construction. A breaking
  change in any module surfaces immediately at CI time, not in
  production.
- `tests/test_surplus_charging_scenarios.py` — **93 behavioural
  scenarios** walking every (mode × battery SOC zone × time-of-day
  × solar level) combination through `decide → actuate → adapter`.
  Includes a full-day timeline (`dawn → morning → noon → afternoon
  → evening → dusk`) with realistic numbers.
- `tests/test_inverter_battery_arch.py` — **27 tests** pinning the
  inverter/battery types, adapter dispatch, hysteresis, factory
  selection.
- `tests/test_multi_inverter_battery_primary.py` — **23 tests** for
  the PowerReadings dicts + fleet `@property` accessors.

Full suite: **2733 passed**, 7 skipped (was 2337 at v1.6.14
baseline → **+396 new tests**). The simulation-driven verification
approach replaces the previous "deploy and watch logs" cycle —
hardware test windows are scarce; deterministic CI scenarios run
in under a second and gate every PR.

### Compatibility notes

- **Zero user-visible behaviour change for single-device installs.**
  The fleet `solar_power` / `battery_power` / `ev_power` fields stay
  populated as cached sums; every existing sensor and dashboard
  card continues to read them unchanged. The new `@property` views
  are additive.
- **Multi-device installs see better-quality flow attribution.**
  A two-charger setup where one is in `solar_only` and the other in
  `min_plus_solar` previously got a proportional split that
  attributed grid to the solar-only charger; now the priority
  allocator correctly routes solar to the higher-priority charger
  first.
- **`charge_mode = solar_only` no longer charges from grid at night.**
  Fixed in v1.6.17 (#346) and structurally retired by the new
  decide-time mode gate in v1.7.0.
- **Storage format: backward-compatible.** Pre-v1.7.0 snapshots
  restore unchanged (no new keys present → empty dicts → fallback
  to legacy fields).
- **Legacy code paths retired:** `_determine_charging_strategy`,
  `_self_consumption_strategy`, `_zone_based_strategy`,
  `_canonical_strategy_from_legacy`, `_raw_zone`, `_get_zone`,
  `_debounce_zone`. `BatteryProtectionMixin` and the per-brand
  `BatteryChargeAdapter` subclasses (`HuaweiChargeAdapter`,
  `GoodWeChargeAdapter`, `GenericChargeAdapter`) are still in the
  tree as backward-compat shells — the new `BatteryControlAdapter`
  wraps them internally. They can be deleted in v1.7.1 after the
  PROD soak window.

### What's queued for v1.7.1

- Per-inverter / per-battery dashboard sensors (gated on
  `len(...) >= 2`).
- Per-inverter / per-battery flow attribution in `flow_calculator`
  (the destination-side view of "which inverter's solar fed where").
- `sensor_reader` migration to populate
  `EnergyTotals.per_inverter` / `per_battery` each cycle (so
  `daily_solar_view` becomes authoritative on multi-inverter
  installs).
- Delete `BatteryProtectionMixin` + `BatteryChargeAdapter` shells
  after PROD soak proves the new pipeline.
- Per-string-to-destination attribution (#312 originally deferred —
  now buildable on top of the per-inverter flow work).

---

### Per-PV-string visibility (#312)

Closes the long-standing @MRAK96 request for Sunsynk-style per-string
display: SEM had the auto-discovery (`hardware_detection.discover_pv_strings_from_registry`,
8 inverter brands) for the optional HACS K-Flow card since v1.5.x
but never promoted per-string to SEM's own surface. v1.7.0 ships
the full stack: data layer, sensor entities, card rendering, and
user docs — internally implemented as three discrete phases so
each piece could be reviewed and tested independently on HA-TEST,
but published as one user-visible release.

### Added

- **Per-PV-string power + daily-energy sensors** (gated on
  `len(strings) >= 2`):
  - `sensor.sem_pv_string_<slot>_power` (W, MEASUREMENT)
  - `sensor.sem_pv_string_<slot>_daily_energy` (kWh, TOTAL,
    daily-reset)
  where `<slot>` is the normalised label `pv1`, `pv2`, … (max 4
  per discovery's slot cap). Single-string installs see no
  change.
- `PowerReadings.solar_power_per_string: Dict[str, float]` — the
  source-side mirror of v1.6.9's `ev_power_per_charger`. Sum
  invariant: `sum(values) ≈ solar_power` within rounding.
- `EnergyFlows.per_string: Dict[str, StringEnergy]` — daily kWh
  per string, integrated by `FlowCalculator.integrate_energy_flows`
  alongside the fleet and per-charger accumulators.
- `PowerFlows.solar_per_string: Dict[str, float]` — pass-through
  carrier from readings to the integrator (strings are sources,
  no destination attribution math required).
- `StringEnergy` dataclass (1 field: `energy_kwh`).
- `SensorReader.set_pv_strings(...)` registers the discovered
  per-string sensors; the per-cycle read loops in both the
  Energy-Dashboard and legacy paths populate
  `readings.solar_power_per_string` when the gate trips.
- Auto-discovery wired through coordinator: the existing
  `hardware_detection.discover_pv_strings_from_registry`
  (Huawei / GoodWe / Growatt / Kostal / Sungrow / Fronius /
  SolarEdge / Victron) now also feeds SEM's own sensors.
- **V+I synthesis fallback**
  `hardware_detection.discover_pv_string_vi_pairs` — when an
  inverter exposes per-string voltage + current but no
  per-string power sensor (Huawei Solar Modbus, generic
  Modbus drivers, Solarman bridges), SEM detects sibling
  `pv_N_voltage` + `pv_N_current` pairs and multiplies V × I
  at read time to synthesise the per-string watts. Surfaces
  the same `sensor.sem_pv_string_<slot>_power` entities as
  the direct-power path; downstream consumers (cards, energy
  accumulator, sum invariant) don't know which way the value
  was sourced. Voltage / current patterns accept English
  (`voltage` / `current` / `volt` / `amp`) and German
  (`spannung` / `strom`) suffixes. When the same slot has
  BOTH a direct power sensor AND a V+I pair, the direct
  sensor wins (slightly more accurate — accounts for the
  inverter's MPPT efficiency math). Confirmed on HA-PROD
  2026-06-01: Huawei `inverter_pv_1_spannung` +
  `..._strom` pair now feeds `sensor.sem_pv_string_pv1_power`
  via this path.
- **Per-PV-string chip strip** on three cards, auto-shown when
  ≥ 2 strings are present. Each chip shows `PVn N.NN kW` and
  links to the underlying sensor entity on tap.
  - `sem-flow-card`: chips above the SVG flow diagram.
  - `sem-solar-card`: chips above the hero arc ring.
  - `sem-system-diagram-card`: chips above the illustrated
    diagram as a compact HUD.
- `semDiscoverPVStrings(hass, prefix)` shared card helper —
  reads `sensor.{prefix}pv_string_pv1_power` … `pv4_power`,
  returns `[]` when fewer than 2 present so callers can pass
  the result straight to a Lit `html` template.
- `semPVStringsCSS` shared style block.
- **New user reference doc**
  [`docs/PV_STRINGS.md`](docs/PV_STRINGS.md) — what sensors get
  created, supported inverter brands with regex pattern table,
  how discovery works, "what if I don't see my strings"
  troubleshooting flow, internals pointer table, and the
  out-of-scope list (per-string-to-destination attribution,
  per-string cost, Solcast multi-plane — file-an-issue links).

### Fixed

- **Flow attribution: priority-based instead of proportional (#349)** —
  HA-PROD 2026-06-01 dashboard showed `flow_grid_to_ev_energy =
  6.633 kWh` on a day when the actuator's `session_solar_share` said
  the car was 91 % solar. Root cause: SEM split every source across
  every destination by demand percentage, attributing grid to the EV
  whenever the home battery was simultaneously charging (the battery
  was actually the grid-paid consumer; EV was on solar). The model
  also overshot destinations when supply ≠ demand exactly.

  New model: sources drain in priority `solar → battery_discharge →
  grid_import`; destinations served in priority `home → ev →
  battery_charge → grid_export`. Each watt is attributed to exactly
  one (source, destination) pair. The conservation invariants hold:
  for each destination, sum of (source→destination) flows = demand;
  for each source, sum of (source→destination) flows = supply. 14
  new tests in `tests/test_349_flow_priority_attribution.py` pin
  both. The previously misleading `flow_grid_to_ev` should now match
  user intent — solar covers EV first when there's enough.

- **EV charges overnight in `charge_mode=solar_only` (#346)** —
  also shipped as the v1.6.17 hotfix. `_determine_charging_strategy`
  returned `"night_grid"` unconditionally when `is_night_mode()` was
  True, ignoring the per-charger `charge_mode`. Strategy now consults
  `MODE_NIGHT_ALLOWED` first: `solar_only` at night → `idle`; `off` →
  `disabled`; other modes unchanged. Defence in depth: actuator self-
  resume guard extended from `{"disabled"}` to `{"disabled", "idle"}`
  so future strategy disagreements land safely.
- **Autarky reported 0% when battery overnight-charged from grid
  (#344, #345)** — fleet-summed `daily_grid_import` was treated as
  unconditional autarky penalty, including the grid-to-battery slice
  that doesn't displace home consumption. Then a second pass (#345)
  switched the formula to fully flow-attributed accumulators
  (`solar_to_home + solar_to_ev + battery_to_home + battery_to_ev`
  over total consumption) so the temporal mismatch between sunrise-
  reset `daily_ev` and calendar-reset `flow_grid_to_ev` no longer
  drowns the numerator.

### Changed

- Day rollover in `FlowCalculator.integrate_energy_flows` now
  also clears `_per_string_accumulators` alongside fleet and
  per-charger.
- Snapshot persistence (`get_flow_accumulator_state` /
  `restore_flow_accumulator_state`) gains a `per_string` key,
  emitted only when non-empty. Pre-v1.7.0 snapshots restore
  bit-for-bit identical (no `per_string` key → no per-string
  state).

### Tests (18 new)

`tests/test_per_string_energy.py`:
- Back-compat: empty per_string dict in single-string setups.
- Sum invariant: 2-string and 4-string splits.
- Multi-cycle accumulation.
- Day rollover clears per-string accumulator.
- Persistence round-trip (4 tests, incl. legacy snapshot
  back-compat).
- Bad-snapshot defence (3 tests: non-dict per_string, non-dict
  per-slot entry, non-numeric values).
- Idle-string preservation (clouded string keeps its surfaced
  kWh — no regression to 0 on the user-visible counter).
- `SEMData.to_dict` emission (key present when populated,
  omitted when empty).
- `SensorReader` gate (1 string → no pollution; ≥2 → populated).

Full suite 2281 green on Python 3.12 (2263 v1.6.14 baseline +
18 new). Bundle (`dist/sem-cards.js`) rebuilt with the chip
strip rendering for all three cards.

### Phase trail (internal)

Implementation shipped to develop as three feature PRs for
focused review, then consolidated to one user-visible v1.7.0
release per maintainer policy:
- PR #337 — data layer (sensors, types, sensor reader,
  flow calculator persistence).
- PR #338 — card rendering (3 cards, shared helper, bundle).
- PR #339 — user reference doc.

Manifest stays at 1.7.0.

## [1.6.14] — 2026-05-31

Multi-charger debt closeout. Bundles four pieces of work into one
release (the maintainer-set rule "no v1.7 until every multi-charger
follow-up is closed" pulled deferred ``v1.7+`` items back into
v1.6.x; this is them, packaged as one release rather than four
separate HACS bumps).

### Fixed

- **Surplus tracker jump-from-0 spike (#8)** —
  ``_apply_ramp_limit`` used to short-circuit on ``current < 1`` and
  return ``target_current`` directly, so a cold-start cycle handed
  KEBA a 14 A command from 0 A. KEBA's ~30 s physical actuator lag
  then caused a ~4.4 kW grid-import overshoot during the ramp
  (confirmed live on PROD 2026-05-31 at 10:43). Cold start now hands
  KEBA ``min_current`` (typically 6 A ≈ 4140 W on 3-phase EU);
  subsequent cycles climb via the existing ``±ramp_rate`` clamp at
  the user-configured ``ev_ramp_rate_amps`` (default 2 A/cycle, so
  target reached in ~4 cycles for a 14 A request). The stop-fast
  branch is preserved: ``target_current < 1`` still returns 0
  immediately so explicit-off / disable stays snappy. 13 new unit
  tests in ``tests/test_ramp_limit_8.py`` pin every branch.

### Changed

- **``effective_state`` and ``charger_name`` migrated onto
  ``PerChargerContext``** instead of writing the parallel
  ``_effective_states_per_charger`` dict from inside the loop body.
  The loop body assigns ``pcc.effective_state = …``; ``__exit__``
  persists ``(state, name)`` into the coordinator's dict so the
  post-loop ``_send_notifications`` dispatcher continues reading
  from a single map. The dict is the storage; pcc is the write
  path. Lets a future AST lint enforce field access at type level
  (no callsite outside the loop touches the dict directly).
- **``this_power_w`` precomputed in ``PerChargerContext.__enter__``**
  via ``coord._this_charger_power(ev_dev, power)`` and exposed as a
  typed field. The coordinator stashes the active pcc on
  ``coord._current_pcc``; ``_this_charger_power`` becomes a cache
  shim — when invoked with the same ``ev_dev`` it returns
  ``pcc.this_power_w`` instead of re-reading HA state. Replaces
  the three per-method ``this_power_w = self._this_charger_power(…)``
  local-var caches in ``coordinator/ev_control.py`` without
  changing the callsites. Helper exceptions in the precompute fall
  through to the legacy read path so a transient HA-state issue
  can't half-apply the swap.

### Added

- ``PerChargerContext.power``, ``this_power_w``, ``effective_state``,
  ``charger_name`` dataclass fields.
- ``SEMCoordinator._current_pcc`` short-lived pointer to the active
  context (``None`` outside any per-charger iteration).
- ``# FLEET-READ:`` annotation on the documented multi-charger
  fallback in ``_this_charger_power`` (only reached when a charger
  config omits ``ev_charging_power_sensor`` — rare).
- 47 new tests across three areas (13 ramp-limit + 14 pcc-field +
  20 per-charger flow):
  - ``tests/test_ramp_limit_8.py``: cold-start, near-zero,
    steady-state ramp, stop-fast, custom ``min_current``,
    end-to-end multi-cycle climb.
  - ``tests/test_per_charger_context.py``: effective_state
    persistence, this_power_w precompute, current-pcc-pointer
    lifecycle.
  - ``tests/test_this_charger_power_cache.py``: cache HIT, three
    MISS variants, kW→W conversion regression from #315.
  - ``tests/test_per_charger_energy_flows.py``: sum invariant,
    multi-cycle accumulation, day rollover, persistence
    round-trip (incl. legacy snapshot back-compat), edge cases
    (charger appears mid-day, charger idle in cycle,
    zero-interval), bad-snapshot defence, sensor-description
    generation gate.

- **Per-charger flow sensors (gated on ``len(ev_chargers) > 1``)**:
  ``sensor.sem_charger_<id>_flow_solar_to_ev_power``,
  ``..._grid_to_ev_power``, ``..._battery_to_ev_power`` (W,
  MEASUREMENT) plus matching ``..._energy`` (kWh, TOTAL, daily-
  reset). The Sankey card + HA Energy dashboard can now show
  per-charger EV sourcing instead of a fleet-proportional split —
  closes the @RienduPre observation on #316. Single-charger setups
  unchanged (fleet ``sensor.sem_flow_*_to_ev_*`` is authoritative).
  - ``ChargerEnergyFlows`` dataclass + ``EnergyFlows.per_charger``
    field.
  - ``FlowCalculator._per_charger_accumulators`` (kWh) integrated
    over time alongside the fleet accumulator; sum invariant
    pinned in tests.
  - Day rollover clears both fleet AND per-charger accumulators.
  - Snapshot persistence round-trip: new ``per_charger`` key
    under the existing snapshot dict; pre-v1.6.15 snapshots
    (without the key) restore bit-for-bit identical.
  - Accumulator semantic: once a charger appears, its kWh stays
    surfaced until the day rollover, even on cycles where the
    charger is idle (the user-visible counter must not regress
    to 0 just because the car unplugs).

- **``FleetEvPower`` newtype + global AST lint (v1.6.16 work)**.
  ``PowerReadings.ev_power`` is now typed as ``FleetEvPower`` — a
  ``float`` subclass that exposes ``.as_fleet_total(reason: str)``.
  Two equivalent ways to acknowledge a fleet read:
  - Comment form (v1.6.8 idiom, still valid):
    ``# FLEET-READ: <reason>`` on the same line or up to 5 lines
    above (walking back through ``#``-comment lines only).
  - Method form (preferred for new code):
    ``power.ev_power.as_fleet_total("<reason>")`` — the reason
    rides in the bytecode (mypy / IDE hover / ``git blame``)
    instead of an adjacent comment.

  Lint expanded to every module under ``coordinator/`` (was
  ``ev_control.py`` only). Exempt files: ``types.py`` (defines the
  field) and ``per_charger_context.py`` (docstrings only). The
  ~15 legitimate fleet reads got explicit ``# FLEET-READ:``
  reasons; one ``coordinator.py:3459`` stall-detection site
  migrated to the new method form as the in-tree demo.

  Sensor reader (the only writer) constructs ``FleetEvPower``
  instances at the assignment sites. Single-charger setups
  unchanged — ``FleetEvPower(value)`` reduces to a tagged float.

  12 new tests in ``tests/test_fleet_ev_power_reads_global.py``:
  - ``TestGlobalFleetEvPowerLint`` (6): every read acknowledged
    across coordinator/; exempt-list minimality; synthetic-code
    sanity (method form detected, bare read flagged, comment
    form still accepted).
  - ``TestFleetEvPowerNewtype`` (6): is float subclass,
    arithmetic works (no migration cost), ``.as_fleet_total``
    returns plain float, reason arg is documentation-only,
    default ``PowerReadings.ev_power`` is the newtype, repr
    includes class name.

### Why

Senior reviewer on the v1.6.7→v1.6.10 arc flagged ``effective_state``
and ``this_power_w`` as "works correctly; not on the context object."
Both shipped working — but the docs claimed "pcc is the single source
of truth for per-charger data" while these two lived in a parallel
dict and method-local vars. This release makes the doc honest.

The ``#8`` surplus-tracker spike fix bundled in here was confirmed
live on PROD 2026-05-31 during the v1.6.3 soak — held with the
refactor rather than shipped standalone so PROD users get one
soak window instead of four staggered HACS updates.

@RienduPre's #316 observation ("Sankey shows charger 2 sourcing
from grid even in solar_only") was the user-visible gap behind the
flow-sensor work. v1.6.9 fixed the underlying data (proportional
W-level split was honest); v1.6.15 ships the entity surface so the
dashboard + Energy dashboard actually render the per-charger split.

### Polish (HA-TEST soak findings folded into v1.6.14)

- **PR #333** — initialise ``SEMCoordinator._current_charger_budget``.
  Missed in the v1.6.7 PerChargerContext refactor; ``__enter__``
  snapshotted the attribute but ``__init__`` never set it, so every
  multi-charger setup blew up its first cycle with
  ``AttributeError``. Single-charger setups (HA-PROD) never tripped
  it; HA-TEST today was the first multi-charger clean install since
  v1.6.7. New regression test ``test_coordinator_swap_attrs_initialized.py``
  AST-walks ``SEMCoordinator.__init__`` to assert every attribute
  ``PerChargerContext.__enter__`` snapshots is initialised.

- **PR #334** — per-charger notification ``NoneType`` coerce + flow
  sensor zero-fill. ``intel.get(k, default)`` returns the default
  only when the KEY is missing — mock chargers without upstream
  data have the key set to ``None``, so ``est_soc > 0`` raised
  ``TypeError`` every cycle (DEBUG noise). Fix: ``intel.get(k) or 0``.
  Plus: ``flow_calculator`` now zero-fills per-charger flows when
  the fleet is idle so the v1.6.15 flow sensors stay AVAILABLE at
  0 W instead of going ``unavailable`` whenever no charger draws.

- **PR #335** — upgrade-notification helper. After a HACS update +
  HA restart, the browser's loaded frontend bootstrap still
  references the OLD ``sem-localize.js`` URL until hard-refreshed
  — soft reload serves the cached bootstrap → loads stale
  translations → raw keys like ``today_plan_title`` /
  ``plan_strip_idle`` appear in cards. HA-TEST 2026-05-31 confirmed.
  New ``_maybe_emit_upgrade_notification`` helper detects a SEM
  version change at setup (via a per-entry
  ``hass.helpers.storage.Store``) and fires a one-shot
  ``persistent_notification`` instructing users to hard-refresh
  (Ctrl+Shift+R / Cmd+Shift+R). First install is silent. Failure
  is non-fatal. 5 new tests pin the contract (first-install,
  same-version, upgrade, per-version notification-id, per-entry
  storage key).

2263 tests pass on Python 3.12 (2210 v1.6.12 baseline + 13 #8 +
14 v1.6.14 + 20 v1.6.15 + 12 v1.6.16 + 2 v1.6.14-hotfix +
5 v1.6.14-polish = 66 new tests in this release). Manifest at 1.6.14.

## [1.6.12] — 2026-05-31

Closes the last open senior-reviewer item on the v1.6.7 → v1.6.11
multi-charger cleanup arc — the missing end-to-end scenario covering
``charger A = off + charger B = solar_only`` mixed-mode. No
behaviour change for any user.

### Added

- **New scenario test** ``tests/scenarios/2026-05-31_off_plus_solar_only.yaml``
  exercises the senior-reviewer-flagged hole in coverage:
  - **Per-charger effective state isolation** (v1.6.4
    ``_apply_per_charger_off_override``). Charger ``off`` mode →
    ``SOLAR_IDLE`` (terminate); sibling ``solar_only`` →
    ``SOLAR_CHARGING_ACTIVE`` (untouched). Pins the #315 mitigation
    at the unit-pipeline level — would have mechanically caught the
    v1.6.3 regression at PR-review time.
  - **Per-charger flow attribution** (v1.6.9
    ``PowerFlows.per_charger``). With per-charger draw set to
    ``{left: 4000, right: 0}``, the per-charger split must give
    ``right`` zero EV-side flow — the user-visible attribution
    @RienduPre asked for in #316.
  - **Distribution sum invariant** (Phase B.5 / #284) re-asserted on
    top of the mixed-mode case.

- **Scenario harness extensions** in ``tests/scenario_harness.py``:
  - ``TIMELINE_FIELDS`` accepts ``ev_power_per_charger: {cid: watts}``
    so multi-charger flow attribution can be driven from YAML.
  - Cycle results now include ``per_charger_effective_states`` and
    ``per_charger_flows`` when the scenario has 2+ chargers.
  - Two new ``expect.multi_charger`` assertion blocks:
    ``per_charger_effective_states`` (exact match or
    ``{cid}_contains: substring``) and ``per_charger_flow_max`` for
    per-charger upper-bound caps.

### Docs

- ``docs/MULTI_CHARGER.md`` roadmap updated: the off + solar_only
  scenario gap is now closed (was a senior-reviewer FIX-BEFORE-MERGE
  on the v1.6.7-v1.6.10 arc).
- CHANGELOG entry per the
  ``feedback_docs_per_release`` rule — docs are part of every
  release, not a follow-up.

## [1.6.11] — 2026-05-31

Diagnostics improvement + doc polish closing the senior-engineer
review NITs on the v1.6.7 → v1.6.10 multi-charger cleanup arc. No
behaviour change.

### Added

- **Recent SEM log lines in the Copy diagnostics dump** —
  ``diagnostics.py::_get_recent_sem_logs`` reads the last 2 MB of
  ``home-assistant.log``, filters for
  ``solar_energy_management`` mentions, and includes up to 80 matching
  lines as ``recent_logs`` in the diagnostics output. Bug reports now
  come pre-loaded with the surrounding log context so we don't have
  to ask reporters for a separate ``ha core logs`` dump. Supervisor
  installs (no flat log file, journald-based) get a one-line
  placeholder explaining how to attach logs manually.

### Docs

- ``CLAUDE.md`` — new "Multi-charger correctness" pointer to
  [``docs/MULTI_CHARGER.md``](docs/MULTI_CHARGER.md) so future AI
  sessions can find the invariant doc without needing to grep.
- ``docs/MULTI_CHARGER.md`` — updated the roadmap to reflect what
  **actually shipped** vs what was planned. Specifically: the original
  v1.6.7 design proposed migrating ``effective_state``,
  ``this_power_w``, ``night_plan`` onto ``PerChargerContext`` in
  v1.6.8/v1.6.9 — none of those landed. The current dataclass has
  ``cid`` / ``ev_dev`` / ``charger_cfg`` / ``budget_w`` /
  ``skipped_for_night`` only. Per-charger flow **sensors** (data is on
  ``PowerFlows.per_charger`` but no top-level HA entities yet) were
  also descoped. Both are deferred to v1.7+ in the roadmap so the doc
  no longer oversells the abstraction.

## [1.6.10] — 2026-05-31

Code-quality cleanup release. Closes the three follow-up issues filed
during the v1.6.4 → v1.6.6 review cycle (#308, #309, #310). **Zero
behaviour change** for any user.

### Refactored

- **#308 — dead ``now`` / ``min_pv`` consumer branches dropped from
  ``coordinator/charging_control.py``.** Post-#305 the strategy
  producer ``_determine_charging_strategy`` only emits ``solar_only`` /
  ``battery_assist`` / ``night_grid`` / ``idle`` / ``disabled`` —
  neither ``"now"`` nor ``"min_pv"`` was reachable in production. The
  unreachable branches are gone; ``ChargingState.SOLAR_MIN_PV`` is
  still alive via the ``night_grid`` → ``EVBudgetStrategy.MIN_PV``
  producer mapping. The two synthetic-context tests
  (``test_min_pv_mode``, ``test_now_mode``) that exercised the dead
  branches are removed.

- **#309 — global-select cleanup block in ``select.py`` folded into
  the registry-key sweep added by #304.** The 12-line explicit
  ``async_remove`` block for ``{entry_id}_ev_target_type``,
  ``{entry_id}_ev_target_mode``, ``{entry_id}_ev_charging_mode`` was
  redundant with the sweep at the bottom of ``async_setup_entry``:
  each of those unique IDs has the ``{entry_id}_`` prefix and a key
  that's not in ``valid_keys``, so the sweep removes them just as
  cleanly. Per-charger values were seeded from the globals by the
  v3→v4 migration; no data is lost.

- **#310 — gravestone comments in ``tests/test_soc_zone_strategy.py``
  consolidated** into a single ``Removed tests`` block at the top of
  the module. Three multi-line tombstones (one each from #277 Phase C,
  Phase D.2 / #282, and #305) collapsed to a three-bullet list with
  ``git log -S`` as the pointer for full history.

## [1.6.9] — 2026-05-31

Third and final of the multi-charger cleanup arc (v1.6.7 → v1.6.9).
Adds per-charger flow attribution and per-charger notification flap
suppression so multi-charger users finally get correct downstream
visibility — closes the @RienduPre #316 family of complaints. **Zero
behaviour change** for single-charger users.

See [`docs/MULTI_CHARGER.md`](docs/MULTI_CHARGER.md).

### Added

- **Per-charger flow attribution** in
  [`coordinator/flow_calculator.py`](coordinator/flow_calculator.py).
  When ``PowerReadings.ev_power_per_charger`` is populated (multi-charger
  installs), ``calculate_power_flows`` now also produces
  ``PowerFlows.per_charger[cid] = ChargerFlows(solar_to_ev, grid_to_ev,
  battery_to_ev)``. Sum invariant: ``sum(per_charger[c].solar_to_ev) ==
  solar_to_ev`` (within < 0.1 W from float rounding). Closes the
  long-standing @RienduPre #284 / #316 complaint family — the dashboard
  can now show which charger drank from grid vs solar instead of the
  fleet-aggregated proportional split.

- **``PowerReadings.ev_power_per_charger``** populated by
  ``sensor_reader`` for multi-charger installs (each charger's
  ``ev_charging_power_sensor`` value, keyed by charger id).
  Single-charger installs leave the dict empty.

- **Per-charger notification flap suppression** in
  [`coordinator/notifications.py`](coordinator/notifications.py).
  ``notify_state_change`` accepts new ``charger_id`` + ``charger_name``
  kwargs; the flap-suppression ``_last_notified_state`` /
  ``_pending_state`` / ``_pending_state_since`` storage is now
  per-charger, keyed by ``charger_id`` (or the ``"_fleet"`` sentinel
  for back-compat). A state change on charger A no longer suppresses
  one on charger B. Mobile messages get a ``[Charger Name]`` prefix
  when ``charger_name`` is provided. The HA event payload now carries
  ``charger_id`` and ``charger_name`` keys so automations can route
  per charger.

### Back-compat

- v1.6.8 callers that read ``_last_notified_state``,
  ``_pending_state``, or ``_pending_state_since`` as scalars continue
  to work via property shims that target the ``"_fleet"`` sentinel
  slot.
- Single-charger setups behave identically to v1.6.8 — the
  per-charger split skips when no per-charger data is provided.

## [1.6.8] — 2026-05-31

Second of the three-release multi-charger cleanup arc (v1.6.7 → v1.6.9).
**Zero behaviour change** for single-charger users; multi-charger users
get correctness fixes for 12 fleet-power-sum reads that were silently
returning the wrong value inside per-charger code paths. Sets up the
structural enforcement that makes the bug class impossible to
re-introduce.

See [`docs/MULTI_CHARGER.md`](docs/MULTI_CHARGER.md) for the full
developer-facing invariant.

### Fixed

- **12 fleet-power-sum reads swept in
  [`coordinator/ev_control.py`](coordinator/ev_control.py)** — every
  ``power.ev_power`` read inside the per-charger code path (8 in
  ``_execute_ev_control``, 3 in ``_should_reenable_charger``, 1 in
  ``_update_session_tracking``) now uses
  ``self._this_charger_power(ev, power)`` cached as
  ``this_power_w`` at the top of the method. In multi-charger setups
  these reads were returning the fleet sum — exactly the bug class
  that caused #284, #289, #315 (terminator) and #318 (SOC isolation).
  Each fix was reactive; this sweep closes them all.

### Added

- **AST lint test** ([`tests/test_ev_control_fleet_reads.py`](tests/test_ev_control_fleet_reads.py))
  — walks the AST of ``ev_control.py`` on every CI run and fails if
  any ``power.ev_power`` read is missing a ``# FLEET-READ:`` annotation
  (outside the sanctioned ``_this_charger_power`` helper). Catches the
  bug class on PR review, not after release.

- **``# FLEET-READ: <reason>`` annotation convention** — documented in
  ``docs/MULTI_CHARGER.md``. Same-line or previous-line comment opts
  a deliberate fleet-level read out of the lint with a required
  human-readable reason.

## [1.6.7] — 2026-05-31

First of a three-release multi-charger cleanup arc dedicated to v1.6.x.
**Zero user-visible behaviour change** for single-charger users; multi-charger
users see the same outputs but with the underlying swap mechanism now
typed and unit-tested.

The cleanup arc addresses a recurring bug class found in v1.6.0–v1.6.6
(#284, #289, #315, #318): per-charger context swaps with fleet-level
reads leaking through. This release lifts the swap mechanism; v1.6.8
sweeps the fleet-power reads in `ev_control.py` and adds per-charger
strategy; v1.6.9 adds per-charger flow attribution + notifications
(closes the #316 family).

See [`docs/MULTI_CHARGER.md`](docs/MULTI_CHARGER.md) for the full
developer-facing invariant.

### Refactored

- **`PerChargerContext`** — new
  [`coordinator/per_charger_context.py`](coordinator/per_charger_context.py)
  module that owns the per-charger swap lifecycle. The ad-hoc
  ``saved = {...}`` dict at `coordinator.py:1136-1258` that swapped
  eight coordinator attributes per iteration (and was easy to miss
  when adding new per-charger fields) is now a typed context manager
  with unit tests pinning every swap invariant. Adding a new
  per-charger field is now one place to edit instead of three.

### Docs

- **New `docs/MULTI_CHARGER.md`** — developer-facing invariant doc
  covering the bug class, the `PerChargerContext` contract, how to
  add new per-charger fields, and the v1.6.7-v1.6.9 roadmap.
- **`CONTRIBUTING.md`** — new "Multi-charger correctness" section
  pointing future contributors at the invariant.

## [1.6.6] — 2026-05-31

Same-day hotfix for v1.6.5 — the per-charger power read at
``_this_charger_power`` did a unit-naive ``float(state.state)`` and
compared a kW value to a 500 W threshold. KEBA's native
``sensor.keba_p30_charging_power`` reports in kW; the comparison
``4.14 < 500`` was always False so the v1.6.5 off-mode stop never
fired on KEBA, even when the firmware self-resumed. Confirmed live
on PROD 2026-05-31 15:26 — KEBA self-resumed and ran uncontrolled
for ~2 min until a manual ``keba.disable`` stopped it.

### Fixed

- **Unit-aware per-charger power reading** — ``_this_charger_power``
  now reads the sensor's ``unit_of_measurement`` attribute and
  converts kW → W before the 500 W threshold check. Tests pin both
  KEBA-style (kW) and Wallbox-style (W) sensors so the next charger
  integration doesn't introduce the same trap.

- **Per-charger SOC isolation in multi-charger setups** (#318) —
  ``_update_ev_intelligence`` was only calling ``update_energy()`` on
  the PRIMARY taper detector at line ~3326; every per-charger detector
  in ``_ev_taper_detectors`` stayed at ``_energy_since_full=0``,
  giving every charger the same default SOC. Confirmed by @RienduPre
  on a multi-charger Wallbox Pulsar + Growatt setup. Fix: also call
  ``update_energy(per_increment, per_hw_total)`` inside the
  per-charger loop, using each charger's own ``ev_total_energy_sensor``
  hardware counter for drift-free tracking when configured.

## [1.6.5] — 2026-05-31

Same-day follow-up to v1.6.4. Closes the second half of the off-mode
problem: KEBA P30 self-resumes from a stored setpoint on plug-in events
or after internal firmware events, completely independent of SEM. The
v1.6.4 fix only stopped SEM-owned sessions; if SEM never started the
session (because mode was already off when the EV plugged in, or KEBA
restarted on its own), the contactor stayed closed and KEBA drew power
SEM never knew about.

### Fixed

- **off-mode now stops charger-initiated charging** (#315) — the
  actuator's terminal-state branch in ``ev_control.py`` now also calls
  ``stop_session()`` when ``charging_strategy == "disabled"`` and
  ``ev_power > 500W``, regardless of ``ev._session_active``. Every
  coordinator cycle (10 s) re-asserts the per-brand disable (e.g.
  ``keba.disable``) until ev_power drops below the 500 W threshold.
  Idempotent — safe to call on an already-disabled charger.

  Threshold rationale: KEBA's handshake idle draws 100–200 W
  continuously while plugged in (control-pilot duty cycle). Real
  charging starts at 4140 W minimum (3 phases × 6 A × 230 V). The
  500 W cutoff cleanly separates "actually pulling current" from
  "plugged in, parked" so SEM doesn't spam stop_session every cycle
  while the car is idle at the charger.

## [1.6.4] — 2026-05-31

Hotfix on top of v1.6.3 plus the cleanup follow-ups #304/#305 that
shipped to develop the same day.

### Fixed

- **`charge_mode=off` did not stop EV charging** — surfaced during the
  v1.6.3 PROD soak. Setting the per-charger Charge mode to ``Off`` while
  the EV was actively charging left the KEBA contactor closed; SEM
  reported "Charging allowed" with budget 0 but the charger kept drawing
  power, requiring a manual ``keba.disable`` call to stop. The state
  machine fell through to ``SOLAR_CHARGING_ALLOWED`` instead of a
  terminal stop, so ``stop_session()`` was never invoked.

  Fix: introduce a distinct ``"disabled"`` strategy string for explicit-off
  (separate from transient ``"idle"``). The state machine routes it to
  ``SOLAR_IDLE``, which the actuator treats as terminal → calls
  ``stop_session()`` → ``keba.disable``. The canonical EV budget enum
  collapses ``"disabled"`` back to ``IDLE`` (same 0 W shape, distinct
  upstream).

  Multi-charger correctness: a static helper
  ``_apply_per_charger_off_override`` runs in the dispatch loop so a
  primary charger's ``off`` cannot bleed its terminate into siblings
  with active ``solar_only``/``min_plus_solar`` modes.

### Cleanup (from develop merge)

- **#304** — ``select.py`` orphan removal now uses a registry-key sweep
  matching ``switch.py``. Catches stale entries from previously-removed
  chargers (rather than only those currently in the config).
- **#305** — drop dead ``_auto_mode_strategy`` and the unreachable
  ``min_pv`` branch in ``_canonical_strategy_from_legacy``. Both were
  Phase C leftovers documented as deferred.

## [1.6.3] — 2026-05-30

The **EV charge UX consolidation** release (#277). Replaces the
four-toggle soup (``ev_charging_mode`` × ``night_charging`` ×
``smart_night_charging`` × ``tariff_optimized``) with one named
per-charger ``Charge mode`` selector. Three-phase arc shipped across
five PRs (A + B + B.2 + C + #298 today-plan ETAs).

### New

- **Per-charger ``Charge mode`` selector** with five modes:
  ``Solar only`` / ``Solar + cheapest hours`` / ``Min + Solar``
  (default) / ``Always (max)`` / ``Off``. ``Solar + cheapest hours``
  is dynamically hidden when no dynamic tariff is configured.
- **Per-mode help line** in the EV card explains what each mode
  actually does — cuts the toggle-soup mystery the #247 review
  flagged.
- **Today's plan timeline** gains three ETA rows (#298): "Battery
  full at HH:MM" while charging, "Battery reaches floor at HH:MM"
  while discharging, "EV reaches target at HH:MM" while a charging
  session is in progress.

### ⚠️ Behavioural change — explicit-``minpv`` legacy users

A small population of users explicitly set the legacy
``ev_charging_mode`` to ``minpv`` (the "force Min from grid + solar
to Max" mode). The Phase A migration mapped them to
``min_plus_solar``, which in v1.6.x kept their daytime behaviour
unchanged (the strategy machine still read the legacy field). v1.6.3
Phase C makes ``min_plus_solar`` **zone-adaptive during the day** —
the Min guarantee now comes from NIGHT charging top-up only, not
from forced grid pull at noon. The Min target itself is unchanged;
the daytime path now matches what most installs (``pv + night=on``)
were always doing.

If you want strict "Min from grid at all times" behaviour, pick
``always_max`` from the new selector — it charges at maximum
regardless of source. Otherwise the new ``min_plus_solar`` default
adapts to your battery SOC zone (battery priority when low, surplus
when high, battery-assist in Zone 4) — generally more efficient
than forced grid pull.

### Migrations (automatic on first load post-upgrade)

- **v4 → v5** (Phase A): Each charger gets a ``charge_mode`` derived
  from its existing toggle state. The legacy fields stay in place.
- **v5 → v6** (Phase B fix-up): Re-derives ``charge_mode`` for
  installs whose Phase A derivation silently lost the
  ``tariff_optimized`` signal (``pv/auto/self_consumption + tariff_on``
  → ``solar_plus_cheap``).
- **v6 → v7** (Phase C): Drops the now-dead ``ev_charging_mode`` per-
  charger config key. The legacy ``select.sem_charger_<id>_ev_charging_mode``
  entity is removed from the registry automatically.

### Removed

- **Per-charger switches** ``switch.sem_charger_<id>_night_charging``,
  ``...smart_night_charging``, ``...tariff_optimized`` — the named
  ``charge_mode`` selector carries all three intents now. Existing
  automations that read these switches will need to read the
  ``charge_mode`` select state instead.
- **Per-charger select** ``select.sem_charger_<id>_ev_charging_mode``
  — superseded by the new ``charge_mode`` selector.
- **Global switches** ``switch.sem_night_charging`` and
  ``switch.sem_smart_night_charging`` — same; ``observer_mode`` is
  the only remaining global switch.
- **Config-flow toggle** ``smart_night_charging`` — the named modes
  carry the intent.
- **Strategy machine legacy reads**: ``ev_charging_mode`` is no
  longer consulted anywhere; ``_tariff_optimized_for`` derives from
  the named mode.

### Fixed

- **Stale Lovelace cache-bust on sem-localize.js (#301)** — the legacy
  ``generate_dashboard`` service path used ``int(time.time())`` as the
  ``?v=`` for card resources, so a plain rsync deploy that rewrote
  ``sem-localize.js`` left the registered URL unchanged and browsers
  served the cached pre-Phase-B.2 file. Symptom on first install of
  this release: the new charge-mode selector renders raw translation
  keys (``charge_mode``, ``charge_mode_min_plus_so…``,
  ``charge_mode_hint_min_plus_solar``) instead of localized labels.
  Fix: per-file ``{version}-{sha1(content)[:8]}`` cache-bust, matching
  the format ``_async_register_frontend_resources`` already uses for
  the Lit bundle. Both paths now produce identical URLs for the same
  file content; any deploy that changes content auto-flips the URL on
  the next ``generate_dashboard`` call and the browser cache-misses
  through to the fresh copy.

### Internal

- New ``consts/ev_charge_modes.py`` — shared constants
  (``EV_CHARGE_MODES``, ``MODE_NIGHT_ALLOWED``, ``MODE_USES_TARIFF``,
  ``MODE_USES_SMART_NIGHT``, ``MODE_TO_LEGACY_CHARGING_MODE``,
  ``DEFAULT_EV_CHARGE_MODE``) and the ``effective_charge_mode_for``
  resolver. Single source of truth for the mode taxonomy across
  ``SEMCoordinator``, ``ChargingStateMachine``, ``EVControlMixin``,
  the dashboard cards.
- ``async_migrate_entry`` accumulator refactor — each step reads
  from / writes back to threaded ``accumulated_{data,options}``
  accumulators. Fixes a pre-existing bug exposed by chaining 4
  migration steps (each was re-reading the original entry options on
  test harnesses).
- New module-level ``_content_hash_cache_bust`` helper — extracted
  from the legacy ``generate_dashboard`` registration path so the
  cache-bust behaviour is directly unit-testable. Replaces a closure
  buried inside ``async_generate_dashboard_service``.
- 15-language translations updated; legacy entries cleaned from
  ``strings.json`` + 15 per-language files.
- Suite: 2136 / 2136 tests passing (6 new regression tests guard
  the #301 cache-bust contract).

### Issues addressed

- Closes #277 (EV charge UX consolidation arc)
- Closes #298 (Today's plan battery / EV ETA rows)
- Closes #301 (Stale Lovelace cache-bust on sem-localize.js)

---

## [1.6.2] — 2026-05-30

The **Phase D.2 cleanup + EV-power realtime** patch.

Two changes ship together:

1. **Phase D.2 architectural cleanup (#282)** — completes the EV-budget
   unification arc by removing the legacy fallbacks that the v1.6.0
   canonical path left side-by-side as a safety net. Carrying two budget
   formulas alive was exactly the duplication that produced the
   disagreement bug class in the first place; with three weeks of clean
   v1.6.0/v1.6.1 PROD soak the fallbacks are dead code, and keeping them
   invited the next regression.

2. **#289** — `sensor.sem_ev_power` now updates within one HA dispatch
   of the upstream KEBA / Wallbox sensor instead of waiting up to 10 s
   for the next coordinator cycle. The dashboard reads at 1 s
   resolution and observably benefits; the energy-balance derivations
   (`home_consumption_power`, sankey flows) stay on cycle granularity
   and self-heal on the next tick.

No behavioural changes outside the named removals + the sub-cycle
passthrough. Same upgrade path as any 1.6.x.

### Removed

- **`flow_calculator.calculate_ev_budget`** — superseded by
  `calculate_canonical_ev_budget` since v1.6.0 (Phase A). Zero
  production callers as of v1.6.1.
- **`flow_calculator.calculate_available_power`** — superseded by the
  canonical EVBudget's per-strategy resolution. Zero production
  callers as of v1.6.1.
- **`flow_calculator.calculate_charging_current`** — both production
  call sites (night charge sizing + actuator ramp) now go through
  `EVControlMixin._watts_to_amps` which carries the per-charger
  watts-per-amp + round-down policy directly.
- **`EVControlMixin._calculate_solar_ev_budget`** — 74-line legacy
  fallback that the actuator used when `_cycle_ev_budget` wasn't
  populated. Removed; the path now logs an error and emits 0 W
  (fail-safe = no charge) if the invariant is ever violated. This
  catches coordinator init bugs loudly instead of silently masking
  them with a divergent budget formula.
- **Multi-charger distribution legacy fallback** in
  `coordinator.py` — same fail-safe pattern applied: missing
  `_cycle_ev_budget` → log error + distribute 0 W.
- **`sensor._format_charging_state` demotion guard** — the cosmetic
  SOLAR_CHARGING_ACTIVE → SOLAR_CHARGING_ALLOWED downgrade (commit
  `1a9b3c9`) that papered over the pre-D.2 budget disagreement. The
  canonical unification eliminated the disagreement by construction,
  so the guard is now dead code — verified across daytime
  battery_assist and nighttime MIN_PV soak in v1.6.0/v1.6.1.

### Added

- **#289 — sub-cycle `sem_ev_power` passthrough** — the `ev_power`
  sensor now subscribes to its upstream EV-power entities via
  `async_track_state_change_event` (single-charger: top-level
  `ev_power_sensor`; multi-charger: every charger's
  `ev_charging_power_sensor`). On any upstream change SEM re-sums and
  pushes the new value immediately. Eliminates the 1-cycle gap that
  showed up live on PROD 2026-05-29 as a 4.7 kW dashboard
  discrepancy. 11 unit tests + the resolution / callback / cleanup
  invariants.

### Internal

- **Test sweep** — removed the unit tests that pinned the deleted
  primitives directly (`TestAvailablePower`, `TestEvBudget`,
  `TestAvailablePowerIncludesBatteryDischarge`, `TestEVBudgetSemantics`,
  `TestAvailablePowerInvariants`, `TestCalculateSolarEvBudget`, the
  budget/current rows from `TestEVControlInvariants`). Their physical
  invariants (non-negative budget, 16 A clamp, battery-discharge
  inclusion, Zone-3 proportional ramp, measured-discharge override)
  are now exercised against `calculate_canonical_ev_budget` and the
  scenario harness (`tests/scenarios/2026-05-29_*`).
- **Scenario harness rewired** — `tests/scenario_harness.py` was
  calling the deleted `calculate_ev_budget` / `calculate_charging_current`
  inside a bare `except Exception: pass`. Caught in review before
  deploy: every scenario was vacuously passing (`calculated_current`
  fell silently to 0). Rewrote to compute the canonical EVBudget
  directly and read `EVBudget.net_w` + `EVBudget.current_a`, so
  scenario regressions now fail loudly. 4 / 4 scenarios still pass
  with real values.
- **`test_multi_charger_canonical_budget.py` rewrite** — the test
  mirrored the pre-D.2 production branch with the legacy fallback;
  post-D.2 the branch logs an error and distributes 0 W instead.
  New `test_missing_cycle_budget_fails_safe_to_zero` pins the fail-
  safe; `test_legacy_method_attribute_does_not_exist_post_d2`
  prevents accidental re-introduction.
- **16 A clamp coverage gap closed** —
  `TestEVControlInvariants.test_canonical_budget_current_a_clamped_to_16`
  sweeps extreme solar / battery inputs across every non-IDLE
  strategy (including `BATTERY_ASSIST` which can blow past the
  surplus ceiling by design) and verifies `EVBudget.current_a`
  stays in [0, 16].
- **Docstring rot** — `ChargingContext.available_power` docstring
  was still referencing `FlowCalculator.calculate_ev_budget()`;
  updated to point at `calculate_canonical_ev_budget().net_w`.

**Suite is 2054 / 2054 green** (was 2042 in v1.6.1 — 12 new tests).

---

## [1.6.1] — 2026-05-30

Patch release with fixes driven by the v1.6.0 PROD soak. No behavioural
changes outside the named fixes — same upgrade path as any 1.6.x.

### Fixed

- **#288** — Night peak management formula switched from the
  sensor-lag-sensitive derived `home_consumption_power` to
  `sensor.sem_consecutive_peak_15min` (the same 15-min rolling
  grid-import average most demand-charge tariffs bill on).
  Self-balancing: as EV ramps the rolling rises and headroom shrinks
  naturally; settles at the equilibrium where rolling ≈ peak limit.
  Falls back to the legacy formula during the cold-start window when
  the load manager hasn't accumulated samples yet, so peak protection
  is never absent. Caught live on PROD 2026-05-29 with a 7.9 kW grid
  spike during EV ramp because `sem_ev_power` lagged by ~5 kW for
  several seconds, deflating the derived home value toward 0 and
  giving the EV the full peak limit as headroom. 6 unit tests +
  forever live sentinel.
- **#290** — Night state machine no longer blips through
  `NIGHT_DISABLED` for one cycle during config slider writes.
  Observed live on PROD 2026-05-29: a per-charger Number slider
  write triggered a race in `hass.states.is_state` for the per-charger
  night switch, returning False for one ~10 s cycle before
  recovering. SEM now requires 2 consecutive cycles of disagreement
  before flipping the cached state — trades 10 s of responsiveness
  for race immunity. 7 unit tests covering first-call commit, blip
  suppression, sustained change, and pending-counter reset.

### Internal

- **Test infra** — fixed the pre-existing flaky
  `test_lookahead_uncapped_when_no_deadline_resolvable` that had been
  intermittently red since the defensive `night_end` fallback at
  `ev_control.py:119-122` was added. The test now patches
  `DEFAULT_EV_TARGET_TIME` to None so the original "no deadline
  resolvable" path it was written to guard is actually exercised.
  Suite is now 2091 / 2091 fully green — first time this release.
- **Live test layer** — new sentinel `tests/live/test_night_peak_rolling.sh`
  pins the #288 fix as a regression guard.
- **Documentation** — design plan for #277 (EV Charge mode
  consolidation) committed at `docs/plans/2026-05-30_ev_charge_mode_consolidation.md`.
  No code yet; awaiting maintainer decisions on the four design
  questions listed there before any implementation. Tracked for v1.7.0.

---

## [1.6.0] — 2026-05-30

The **EV-budget unification** release. SEM historically had three separate
"how many watts can the EV draw right now" calculations — one for the
published dashboard sensors, one for the state machine's decision, and one
for the actuator. Under certain conditions they disagreed: the dashboard
could read *"Charging active"* while the car drew 0 W, or surplus-only
mode could let grid backfill the EV's draw without telling the user.

v1.6.0 collapses all three into one canonical `EVBudget` value computed
once per cycle. Every consumer now reads from the same dataclass — the
dashboard, the state machine, the actuator, and the multi-charger
distribution all see the same number, by construction.

### ⚠️ Behavioural change — published sensors

`sensor.sem_available_power` and `sensor.sem_calculated_current` now
publish the **canonical** EV budget instead of the raw solar surplus.
The canonical value is strategy-aware (includes battery-redirect on
`solar_only`, includes the battery-assist contribution on
`battery_assist`, applies the floor on `min_pv`) — it's the more
accurate number and matches what the state machine actually decides
with.

If you have automations or template sensors that read either of these
two values directly, you may see different numbers than under
1.5.x. The canonical value is the honest one; the pre-1.6.0 value
could be misleadingly low when battery redirect was active.

### Added

- **Canonical `EVBudget` dataclass and `EVBudgetStrategy` enum** in
  `coordinator/flow_calculator.py`. Six strategies are first-class:
  `IDLE`, `SELF_CONSUMPTION`, `SOLAR_ONLY`, `BATTERY_ASSIST`, `MIN_PV`,
  `NOW`. Each has a single well-defined formula; the dispatcher raises
  `ValueError` on unknown strategies (no silent fallthrough, which was
  the #282 disagreement root). See [ARCHITECTURE.md → EV Budget
  Calculation](docs/ARCHITECTURE.md#ev-budget-calculation).
- **Live test layer** under `tests/live/` — seven bash scripts that
  exercise SEM against a real Home Assistant instance:
  `test_budget_agreement.sh`, `test_charging_state_consistency.sh`,
  `test_solar_only_no_grid.sh`, `test_overnight_window.sh`,
  `test_deadline_reset.sh`, `test_per_charger_slider.sh`,
  `test_bundle_integrity.sh`, `test_surplus_charging.sh`.
- **Scenario harness scenarios** locking the canonical math through
  the coordinator pipeline:
  `tests/scenarios/2026-05-29_budget_unify_redirect.yaml`,
  `tests/scenarios/2026-05-29_budget_unify_battery_assist.yaml`,
  `tests/scenarios/2026-05-29_multi_charger_split.yaml`.
- 17 unit tests for the canonical method covering every strategy plus
  the regimes that historically disagreed.
- 4 unit tests for the multi-charger Phase B.5 distribution path.
- 4 unit tests for the YAML-mode Lovelace guard.
- `copy_failed` translation key across all 15 languages.

### Changed

- `coordinator.async_update_config` now mutates `self.config` in place
  rather than rebinding to a new dict. Multiple components
  (`TimeManager`, `EnergyCalculator`, `ChargingStateMachine`,
  `BatteryChargeAdapter`) hold references to the original dict; the
  pre-fix rebind left them stale, so the next slider change reached
  `coordinator.config` but never propagated. Caught by
  `tests/live/test_overnight_window.sh`.
- The multi-charger distribution at `coordinator.py:966` now reads the
  canonical `EVBudget.net_w` instead of calling the legacy
  `_calculate_solar_ev_budget`. Same #282 disagreement mode, just for
  fleets of 2+ chargers (Phase B.5).
- The `sem-system-card` "Copy diagnostics" button now uses a
  cross-context clipboard helper that falls back to
  `document.execCommand('copy')` on HTTP installs where the modern
  Clipboard API is blocked. Always shows user feedback — success or
  failure — so the button is never silent again.
- Deploy scripts (`~/bin/deploy-test.sh`, `~/bin/deploy-prod.sh`) now
  strip `__pycache__` before `ha core restart`. `ha core restart` does
  not clear the bytecode cache, so signature changes in committed
  code could still execute the cached `.pyc` and produce confusing
  `NameError`s. (Operational; not in the integration itself.)

### Fixed

- **#279** — Global `daily_ev_energy` counter resets at the configured
  `Charge by` time, not at sunrise. The summer-sunrise race condition
  (sunrise earlier than the deadline → counter wiped while night
  charging still in progress → double-charge) is closed.
- **#283** — Dashboard no longer fails to register on YAML-mode
  Lovelace installs. The integration feature-detects the mutating
  resource-collection methods; when YAML mode is detected, it logs a
  single actionable warning with the exact `lovelace.resources:` YAML
  the user has to paste, instead of an unhelpful "Could not register"
  warning. Storage-mode users see no behavioural change.
- **#284** — Multi-charger setups (e.g. dual Wallbox Pulsar) no longer
  pull from grid while strategy reports `solar_only`. The distribution
  path now reads from the canonical `EVBudget`.
- **#285** — "Copy diagnostics" button in the System Information card
  now works on HTTP installs. Reported on macOS Chrome.
- **Charger plug-sensor physics defence** — caught live on PROD
  2026-05-29 with a KEBA P30. Across an HA restart with a connected
  car, `binary_sensor.keba_p30_plug` reported "off" for 67 minutes
  while `binary_sensor.keba_p30_charging_state` cycled on/off through
  15 transitions and `sensor.keba_p30_charging_power` peaked at 8 kW.
  SEM correctly trusted the lying plug sensor, returned "EV
  disconnected", and stopped supervising the car. The KEBA kept its
  last commanded current; the car drew ~6 kWh past the configured
  Max ceiling because SEM wasn't watching. The root cause is upstream
  (the charger integration's plug sensor), but SEM now defends
  against it: if `ev_charging` is True OR `ev_power > 100 W`,
  `ev_connected` is inferred True regardless of what the plug sensor
  says. Current cannot flow without a connection. Locked in by
  `tests/test_ev_connected_physics_defence.py` (5 truth-table corners)
  and `tests/live/test_ev_connected_physics.sh` (forever sentinel).
- Display-honesty guard at `sensor.py:_format_charging_state` is now
  redundant after the unification (canonical is the single source of
  truth) but kept as defence-in-depth for one release; will be removed
  in v1.7.0.

### Internal

- `coordinator/coordinator.py` — `_build_charging_context`'s
  `available_power` and `calculated_current` parameters dropped (dead
  since Phase B). Step 6's bare-variable computation removed (also dead
  since Phase B).
- New `_canonical_strategy_from_legacy` helper in `coordinator.py`
  maps the legacy strategy-string returns of `_determine_charging_strategy`
  to canonical `EVBudgetStrategy` constants.

### Community contributions

Thanks to **@RienduPre** for [PR #286](https://github.com/traktore-org/sem-community/pull/286)
— two native-speaker Dutch translation polishes (`notif_low_forecast`
grammar; `notif_daily_summary` replaces the loanword "autarkie" with the
idiomatic "zelfvoorzienend").

---

## [1.5.15] — 2026-05-27

Single hotfix release for a SolaX-pattern cold-start regression.

### Fixed

- **#274** — Inverter / battery / grid readings no longer stay at 0
  after an HA restart on SolaX-pattern installs (Pattern E: split
  grid). Forced a sensor-reader reinitialization on coordinator
  restart instead of relying on the lazy first-cycle path.

---

## [1.5.14] — 2026-05-27

Documentation, sensor-naming hardening, and the #255 per-charger
config cleanup.

### Added

- Per-charger night charging gate (`switch.sem_charger_<id>_night_charging`,
  default ON) — multi-charger fleets can now schedule night charging
  per car.

### Changed

- Removed the redundant global EV configuration entities — per-charger
  entities are the canonical source of truth after #255. The integration
  migrates existing setups transparently.
- Energy Dashboard config summary on the System tab now lists actual
  entity names instead of the compact "X sources, Y units" string (#250).

### Fixed

- **#245** — Surplus EV charging now stops at the Max ceiling
  (`daily_ev_target_max`) instead of running until the per-cycle
  remaining-need flips negative. The Min target gates night charging;
  Max gates day surplus. Both are honored independently.
- **#256** — Zero-config installs no longer adopt the global target as
  the per-charger night floor without the user's explicit consent.
- **#259** — Vehicle SOC reads that come back as `unknown` or
  `unavailable` no longer crash the strategy decision.

---

## [1.5.13] — 2026-05-25

Beta-only iterations; release notes consolidated into the next stable.

---

## [1.5.12] — 2026-05-25

### Fixed

- Dashboard regenerate ("Generate Dashboard" service) no longer
  triggers an HA core restart. Live-reload via the storage API
  replaces the legacy "write + restart" pattern.
- Removed a stray top-level `sem-cards.js` left over from a botched
  manual deploy that was shadowing the real `dist/sem-cards.js`
  bundle and breaking every dashboard card (#219 regression class).

---

## [1.5.11] — 2026-05-25

### Changed

- All ~23 dashboard cards now ship as a single Lit bundle at
  `dashboard/card/dist/sem-cards.js`. The legacy top-level vanilla
  `sem-*-card.js` files were removed.
- Lovelace resource URLs now include `?v={version}-{sha1[:8]}` for
  cache busting; plain `rsync + restart` deploys now bust the browser
  service-worker cache without a manifest bump (#240).

---

For the full pre-1.5.11 history, see the [git tag log](https://github.com/traktore-org/sem-community/tags).

[1.6.0]: https://github.com/traktore-org/sem-community/releases/tag/v1.6.0
[1.5.15]: https://github.com/traktore-org/sem-community/releases/tag/v1.5.15
[1.5.14]: https://github.com/traktore-org/sem-community/releases/tag/v1.5.14
[1.5.13]: https://github.com/traktore-org/sem-community/releases/tag/v1.5.13
[1.5.12]: https://github.com/traktore-org/sem-community/releases/tag/v1.5.12
[1.5.11]: https://github.com/traktore-org/sem-community/releases/tag/v1.5.11
