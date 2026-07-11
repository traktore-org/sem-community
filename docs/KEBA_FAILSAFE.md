# KEBA failsafe & steady charging

## What the failsafe is

The **failsafe** is a safety watchdog **built into your KEBA charger** (not into
SEM). It's a dead-man's switch: *if the controller setting the charge current
goes silent (crash, network drop), fall back to a safe current after a timeout.*
Its built-in fallback default is **6 A**.

It exists to protect house wiring when a load-management controller disappears.
On a typical single-car installation it protects against very little.

## Why it can cause a problem

SEM dynamically sets the charge current. If the charger's own short failsafe is
active, the charger keeps **reverting to its 6 A fallback** between SEM's
commands while SEM re-asserts the target — producing a **6↔9 A oscillation**. A
steady-needing car (e.g. a Renault Zoe) sees the shaking offer and refuses to
charge, sitting in standby.

## How SEM handles it by default (you usually do nothing)

By default (`keba_arm_failsafe = true`), SEM uses **managed-neutralize**: it arms
its own **long, non-tripping** failsafe that overwrites the box's short built-in
one, and re-writes it every cycle so it never fires during normal operation. The
result is a steady offer and a smooth charge — **with no action required from
you**, and no Repair. This is the recommended default and needs nothing at the
charger.

> The real KEBA P30 built-in failsafe generally **cannot** be disabled over UDP
> or via Home Assistant's `keba.set_failsafe` service (it rejects a timeout of
> `0`), which is exactly why SEM neutralizes it by overwriting rather than trying
> to switch it off.

## The opt-out: "don't-arm" mode (evcc-style)

If you set `keba_arm_failsafe = false`, SEM leaves the box's failsafe alone (the
approach **evcc** uses). In that mode, if your charger's built-in failsafe reads
**on**, SEM raises the Repair *"KEBA failsafe is enabled"* to guide you to disable
it at the charger — because in don't-arm mode SEM won't neutralize it for you.
Only use this mode if your box **can** actually have its failsafe disabled at the
hardware level. The steps below are for that case.

`keba_arm_failsafe` has no UI toggle yet — it's a config-entry option for advanced
users. If you need to set it, ask in the project's issues for the current way.

## How to disable it at the charger (don't-arm mode only, timeout = 0)

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

## Which mode should I use?

For almost everyone, **leave the default** (`keba_arm_failsafe = true`): SEM
neutralizes the flap by managing a long non-tripping failsafe itself, so charging
is steady out of the box with nothing to configure. Only switch to don't-arm mode
(and disable the failsafe at the charger) if you specifically want the evcc-style
setup and your box supports disabling its failsafe at the hardware level.

---
References: [evcc — KEBA failsafe out-of-sync](https://github.com/evcc-io/evcc/discussions/21093) ·
[KEBA P30 Modbus/UDP programmers guide](https://www.keba.com)
