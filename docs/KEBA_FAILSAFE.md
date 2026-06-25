# Disabling the KEBA failsafe (for steady charging)

If SEM raised the Repair *"KEBA failsafe is enabled"*, this page explains what
it is and how to turn it off.

## What the failsafe is

The **failsafe** is a safety watchdog **built into your KEBA charger** (not into
SEM). It's a dead-man's switch: *if the controller setting the charge current
goes silent (crash, network drop), fall back to a safe current after a timeout.*
Its fallback default is **6 A**.

It exists to protect house wiring when a load-management controller disappears.
On a typical single-car installation it protects against very little.

## Why it causes a problem with SEM (and evcc)

SEM dynamically sets the charge current. While the failsafe is on, the charger
keeps **reverting to its 6 A fallback** between SEM's commands, and SEM re-asserts
the target — producing a **6↔9 A oscillation**. A steady-needing car (e.g. a
Renault Zoe) sees the shaking offer and refuses to charge, sitting in standby.

This is a known issue: **evcc** (the widely-used reference EV charge controller)
also recommends **disabling the KEBA failsafe** for exactly this reason — with it
on, evcc gets recurring "out of sync" errors. SEM follows the same approach: it
**no longer arms the failsafe**, and holds the current it sets, like a simple
script. But the charger keeps its *own* failsafe until you turn it off, and Home
Assistant's `keba.set_failsafe` service **cannot** disable it (it rejects a
timeout of `0`). So you disable it once, at the charger.

## How to disable it (timeout = 0)

Pick whichever you can do:

### Option A — KEBA UDP command (most direct)
The KEBA P30 accepts a UDP command on port **7090** (requires DIP switch **1.3 =
ON** for full UDP control). Send a failsafe command with **timeout 0**, persisted:

```
failsafe 0 0 1
```

(`timeout=0` disables it, `fallback=0`, `persist=1` so it survives a reboot.)
You can send this from any machine on the network, e.g.:

```bash
echo -n "failsafe 0 0 1" | nc -u -w1 <charger-ip> 7090
```

### Option B — KEBA KeContact tooling
Use KEBA's own configuration tool / KeContact portal for your P30/P40 model to
set the **failsafe timeout to 0**.

## After disabling

Once the charger reports the failsafe **off**, this Repair clears automatically,
SEM holds a steady offer, and the car charges smoothly. No SEM restart needed.

## If you'd rather SEM manage it instead

If you can't disable it at the charger, set the SEM option `keba_arm_failsafe`
on: SEM will then arm a **managed** failsafe that drops to your **charging floor**
(not 6 A) and persists, so it can't cause the flap. This keeps a controller-death
safety net at the cost of the extra moving part. The default (off) matches evcc.

---
References: [evcc — KEBA failsafe out-of-sync](https://github.com/evcc-io/evcc/discussions/21093) ·
[KEBA P30 Modbus/UDP programmers guide](https://www.keba.com)
