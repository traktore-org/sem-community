# ClimateDevice — surplus control for `climate.*` entities (#569)

**Date:** 2026-07-06
**Issue:** #569 (Edsol) — "unable to control device via climate entity"
**Status:** approved (two design decisions confirmed by Guido)

## Problem

SEM's surplus engine drives three device kinds:

- `SwitchDevice` — on/off relays, smart plugs (`homeassistant.turn_on/off`)
- `CurrentControlDevice` — EV chargers (amps)
- `SetpointDevice` — heat-pump / hot-water temperature **nudge** (`climate.set_temperature`, boosts the setpoint *up* on surplus)

Generic loads are added by the `register_surplus_device` service (the dashboard
"priority devices" path). It only accepts `switch` / `input_boolean` entities and
always builds a `SwitchDevice`.

A `climate.*`-only air-conditioner (Edsol has two) therefore cannot be managed:
there is no generic **climate** device type. `SetpointDevice` is the closest thing
but it is heating-oriented — it never sets `hvac_mode` and never turns the unit
off, which is wrong for an AC you want SEM to switch on/off with the sun.

## Approved decisions

1. **Actuation = on/off.** On surplus, set the working `hvac_mode` + a comfort
   target temperature (turn the AC ON). When surplus drops, `hvac_mode: off`.
   Behaves like a switch load, so it plugs into the existing priority /
   peak-shed / daily-goal machinery unchanged. (Not a setpoint-nudge — that is
   what `SetpointDevice` already does for heat pumps.)
2. **Configurable mode.** The user picks the active `hvac_mode`
   (`cool` / `heat` / `heat_cool` / `dry` / `fan_only` / `auto`) and the target
   temperature at registration. Default `cool`. One device type covers both
   AC-cooling and heating — no cooling-vs-heating guesswork in code.

## Design

### New `ClimateDevice(ControllableDevice)` in `devices/base.py`

Mirrors `SwitchDevice` (its on/off template) with climate actuation:

- `__init__(..., entity_id=<climate.*>, hvac_mode="cool", target_temperature=None,
  min_on_time=300, min_off_time=60)`.
- `device_type` → new `DeviceType.CLIMATE`.
- `activate(available_watts)`:
  - honour `min_off_time` anti-flicker (mirror `SwitchDevice`);
  - `climate.set_hvac_mode {entity_id, hvac_mode: self.hvac_mode}`;
  - if `target_temperature is not None`: `climate.set_temperature {entity_id, temperature}`;
  - status → ACTIVE, consumption/allocated → `rated_power`, `activation_count += 1`;
  - return `rated_power` (0.0 on no-entity / on exception → ERROR state, like `SwitchDevice`).
- `deactivate()`:
  - honour `min_on_time` anti-flicker;
  - `climate.set_hvac_mode {entity_id, hvac_mode: "off"}`;
  - status → IDLE.
- `adjust_power(available_watts)` → `rated_power` if active else `0.0` (on/off).
- `adopt_if_running()` — re-own after restart when the climate entity's state is
  **not** `off`/`unavailable`/`unknown` (SEM was IDLE but the AC is running).
- `to_dict()` adds `hvac_mode`, `target_temperature`.

No `SurplusController` change: it calls `activate/deactivate/adjust_power`
polymorphically.

### Spec → device factory (DRY the 3 build sites)

Three sites build a service device from a spec, all hardcoded to `SwitchDevice`:

- `features/device_registry.py:248` (restart rehydrate)
- `features/device_registry.py:300` (register)
- `__init__.py:3146` (early-call fallback)

Add a `device_type` key to the stored spec (default `"switch"`). A small factory
`_surplus_device_from_spec(hass, device_id, spec)` (in `devices/base.py`, imported
by both files) returns a `ClimateDevice` when `spec["device_type"] == "climate"`
(reads `hvac_mode`, `target_temperature`), else a `SwitchDevice`. All three sites
call the factory. `device_type` is persisted in `service_registrations` so climate
devices survive restarts.

### `register_surplus_device` service

- `entity_id` selector: add the `climate` domain.
- New optional `device_type` select: `switch` (default) / `climate`.
- New optional `hvac_mode` select (`cool`/`heat`/`heat_cool`/`dry`/`fan_only`/`auto`,
  default `cool`) and `target_temperature` number (°C).
- Handler forwards these into the spec; ignored for `switch` devices.

### Translations / docs

- `services.yaml` field descriptions (English source strings).
- No dashboard-card change required — the device shows in the existing priority /
  Control list like any other service device (`device_type: service_device` in
  diagnostics). Its status flows through the same `to_dict()` path.
- `docs/USER_GUIDE` / `README` supported-load list: add "climate (AC / heat pump
  via `climate.*`)".

## Testing

- `tests/test_devices.py`: `ClimateDevice` fixture + tests mirroring the
  `SwitchDevice` set — activate (calls `set_hvac_mode` with the configured mode +
  `set_temperature`), no-entity → 0, min_off anti-flicker, deactivate sets
  `hvac_mode: off`, deactivate min_on block, adjust_power on/off, error handling,
  `adopt_if_running` when the entity is in a non-off state.
- Factory test: a spec with `device_type: "climate"` builds a `ClimateDevice`;
  default/absent builds a `SwitchDevice`.
- Persistence test (registry): a registered climate device round-trips through
  `service_registrations` and rehydrates as a `ClimateDevice` after restart.

## Out of scope (follow-ups)

- Setpoint-nudge-while-active hybrid (rejected option).
- Per-mode automatic setpoint curves.
- A dedicated config-flow step (the service path matches the reporter's workflow;
  a UI step can come later if demand appears).
