# v2.0.0 — Trustworthy

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

## 💛 Sponsors

SEM is built and maintained by one person, and these five chose to fund that:

**[@praun](https://github.com/praun) · [@RienduPre](https://github.com/RienduPre) · [@Azlinon](https://github.com/Azlinon) · [@onkelfu](https://github.com/onkelfu) · [@coppe218](https://github.com/coppe218)**

What is striking about that list is that not one of them is only a sponsor.
Every single one is in the issue threads of this release, testing on their own
hardware: praun's Deye Sun12k over ESPHome Modbus, RienduPre's Growatt and
Sessy multi-battery work, Azlinon's heat-pump configuration, onkelfu's
SolarEdge discharge clamp and thermal comfort, coppe218's 1↔3-phase switching.
They paid for the work *and* did some of it.
(Sponsors who chose to stay private aren't named here — the thanks is the same.)

Thank you — and thank you equally to everyone who reported something broken and
then patiently re-tested a fix on a real house. The ✅ column of the
[supported hardware table](docs/SUPPORTED_HARDWARE.md) is entirely made of
those people.

## Requirements

Home Assistant **2026.2.0** or newer (Python 3.13+).
