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
