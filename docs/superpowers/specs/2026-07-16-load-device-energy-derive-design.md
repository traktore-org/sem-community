# Load-device power from a kWh energy counter (#600) — design

**Batch:** `batch:sensor-input` · **Branch:** `feature/batch-sensor-input`
**Reporter:** @tlinnet (Viessmann Vitocal 252-A / ViCare), discussion #599.

## Problem

Load devices (heat pump, hot water, generic switch) accept only a `device_class: power`
consumption sensor (`heat_pump_power_sensor` etc.). Users whose only per-device meter is a
`TOTAL_INCREASING` **energy** counter (kWh) — e.g. ViCare's "DHW energy consumption this year"
— can't feed it. Hand-rolling a template/derivative power helper spikes: a 0.1 kWh step landing
in a fixed 30 s window reads as ≈ 12 kW.

The power sensor is **optional** — control falls back to configured `rated_power`
(`devices/base.py::calibrate_rated_power`, `heat_pump_controller.py:213`). So this is about an
accurate **live consumption** signal (and auto-calibration), not enabling control.

## Why the existing derive path doesn't cover it

`ha_energy_reader.py::_derive_missing_power_sensors` + `_find_power_sensor_on_device` recover a
**companion power sensor on the same device** as an energy sensor (solar/grid/battery). A
kWh-only device has **no** companion power sensor, so that mechanism finds nothing. The issue's
"same capability" framing is only half-right: we must actually **derive** power from the counter.

## The core: a smoothed energy→power deriver

The spike comes from dividing a lumpy energy step by a *fixed* window. The fix is to divide by
the **actual elapsed time between counter changes**, and hold that value until the next change:

```
on reading (energy_kwh, t):
  if no baseline:                      power = 0; baseline = (energy, t)
  elif energy < baseline_energy:       # TOTAL_INCREASING reset / yearly rollover
       power = 0; baseline = (energy, t)
  elif energy == baseline_energy:      # unchanged → hold last (device steady) …
       if (t - baseline_t) > idle_timeout: power = 0   # … until it's clearly idle
  else:                                # a real step
       dt = t - baseline_t
       if dt >= min_dt: power = (energy - baseline_energy) * 3.6e6 / dt
                        baseline = (energy, t)
       # dt < min_dt → ignore (avoids the divide-by-tiny spike), hold last
  power = min(power, max_power)         # sane clamp (absurd-data guard)
```

- **`min_dt`** (~5 s): a step arriving faster than this is treated as noise → hold, don't spike.
- **`idle_timeout`** (~15 min): a yearly counter that hasn't moved that long → the device is off →
  decay to 0 rather than holding a stale positive.
- **`max_power`**: `2 × rated_power` when known, else a global cap (e.g. 30 kW) — the absurd-data
  backstop.
- Result is a **stair-stepped** signal (average power over each inter-change interval) — the best
  achievable from a lumpy counter, and never a false 12 kW spike.

Self-contained + pure (state = last baseline + last power), so unit-testable without HA.

## Exposure / wiring (phased)

1. **Deriver** (`coordinator/energy_rate_deriver.py`) + tests. ← this PR.
2. **Config flow**: add an optional `*_energy_sensor` field per load device (heat pump first, then
   hot water, generic), suggested from the Energy-Dashboard device when present. Manual power sensor
   still wins (override precedence, mirroring #597).
3. **Read path**: when a device has an energy sensor but no usable power sensor, feed the deriver
   each cycle; publish the derived power as that device's consumption. Auto-calibrate `rated_power`
   from the observed peak (existing `calibrate_rated_power`).
4. **Docs + CHANGELOG**; soak on `feature/batch-sensor-input` (real ViCare counter via @tlinnet).

## Principles / risks

- **Optional + additive**: absent an energy sensor, nothing changes. A power sensor always wins.
- **Honest about limits**: a yearly counter gives a laggy, stair-stepped signal — documented, not
  hidden. Don't fabricate smoothness the data doesn't have.
- **Reset-safe**: TOTAL_INCREASING resets and yearly rollovers must read 0, never a huge negative
  or a spike (the clamp + baseline-reset handle both).
- Bug-class note: this is the `batch:sensor-input` theme — extend SEM's input flexibility for
  energy-only / hardware-specific meters (siblings: #592 solar/battery power fields, #593 hardware
  cycles, #597 battery_power override).
