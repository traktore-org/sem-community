# Enhancement — two device registries, one word: `is_controllable` reads as permission but means capability

*Drafted 16.08.2026 out of the #779 diagnosis. Not filed on GitHub — issue
creation is blocked for me; Guido to open it (or drop this file if it lands
as an issue body).*

## What

Two subsystems keep a row per appliance, and both expose a flag whose name
sounds like "may SEM touch this":

| | rows in onkelfu's diagnostics | flag | what it actually means |
|---|---|---|---|
| `LoadManager._devices` | **50** | `is_controllable` | **capability** — a control handle was discovered (`control is not None`) and the user hasn't set `controllable_override=False` (`features/device_registry.py:94`) |
| `SurplusController` device list | **17** | `DeviceControlMode` (`surplus` / `peak_only` / `off` / `manual`) | **permission** — whether SEM may drive it, and under which policy |

`is_controllable` is consumed by exactly one thing: the peak-shed loop
(`features/load_management.py:898, 1007, 1349, 1361`). It has nothing to do
with the surplus list.

## Why it matters

In #779 the reporter's diagnostics say:

```
energy_dashboard_spuelmaschine: is_controllable: true
```

on a device he had configured **Mode: Off** — and SEM was switching it off.
That line is *not* the bug (capability true, permission off, both correct),
but it reads exactly like the bug we were chasing. It cost real diagnosis
time on our side and the reporter drew the same wrong conclusion from it.

The axes are also not cleanly separated today: the shed loop's real
permission check is `control_mode != "off"` (`load_management.py:894`), so
the LoadManager row already carries both axes — and only one of them is named
honestly.

#650 is the earlier scar: it had to document why `controllable_override=True`
is *not* the symmetric case of `False`, because "controllable" was being read
as permission there too.

## The arc

Three steps, in order. Step 1 alone is worth it.

1. **Name the axes.** `is_controllable` → `has_control_handle`. `control_mode`
   stays the only permission word. Both registries then speak the same two
   words, and a diagnostics line answers its own question.
2. **One row, two consumers.** The LoadManager row and the surplus device are
   the same physical appliance with independently-maintained flags that can
   disagree. Derive the capability flag in `UnifiedDeviceRegistry` (which
   already re-derives — the #744 lesson) and have LoadManager *read* it
   instead of keeping a copy.
3. **Surface both**, under their real names, in diagnostics and on the load
   priority card — so "why didn't SEM shed X?" and "why did SEM start X?" are
   answerable from one line each.

## Compatibility

`is_controllable` is on several outward surfaces, so step 1 is a
read-both/write-new migration, not a rename in place:

- sensor attributes — `sensor.py:2789` (`"controllable"`) and `:2809`
- diagnostics payload — `diagnostics.py:200`
- the card — `dashboard/card/src/cards/sem-load-priority-card.js:390`
- the service — `__init__.py:3197`, `prop in ("critical", "controllable")`
- stored user overrides — `_controllable_overrides` (`device_registry.py:1815`)

## Priority

Low/none for correctness — nothing misbehaves today. The cost is diagnosis
time, and the odds that the next reader of the flag acts on the wrong meaning.
That has already happened once (#650) and nearly a second time (#779).
