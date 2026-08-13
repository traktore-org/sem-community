# Simulating SEM — the standard workflow

SEM can be tested end to end **without touching any real hardware**, and
without waiting for real nights. This is how the project itself verifies
releases, and it works on any install. Written down 13.08.2026 so it never
has to be re-invented (the N2 campaign night).

## The one principle

**Observer mode is the simulation boundary.** With
`switch.sem_observer_mode` **on**, every layer of SEM runs for real —
sensors are read, plans are stamped, decisions are made, coverage is
judged — and only the final hardware command is cut. Instead of acting,
SEM *publishes what it would do*. Nothing else is mocked, so what you
observe is exactly what a live system would execute.

You never need observer mode off to test decisions, plans, or timing.
You only need it off to watch a physical contactor close — and that is
what a production soak is for, not a simulation.

## The WOULD surface (#764)

When observer mode is on, SEM publishes its would-be actions on two
standard surfaces (one source of truth — the execution seam itself):

1. **State — read it fresh anytime:**
   `switch.sem_observer_mode` carries a `would_decisions` attribute:

   ```yaml
   would_decisions:
     sim_heizband:
       name: Sim Heizband
       action: activate        # activate | deactivate | adjust | hold
       power_w: 1000.0
       source: tier2_battery   # solar | tier1_battery | tier2_battery | cheap_grid
       reason: "overnight battery — runtime deficit"
   ```

   `hold` means no command would be sent — the device is where SEM wants
   it. The attribute is empty while observer mode is off (a live system's
   map would be stale by definition).

2. **Events — subscribe for the edges:** every decision *transition*
   fires a `solar_energy_management_observer_decision` bus event with the
   same payload. Unchanged decisions do not repeat (a wobbling watt
   number is not a transition), so the stream is edges, not a heartbeat.

## Closing the loop: a sim actuator in five lines

A simulation is closed-loop when the "hardware" responds: the device
turns on, runtime accrues, deficits shrink, stop conditions fire, and the
outcome recorder measures a real draw. With the WOULD surface that is one
HA automation per simulated device:

```yaml
automation:
  - alias: "Sim actuator: heizband follows SEM's would-decisions"
    trigger:
      - platform: event
        event_type: solar_energy_management_observer_decision
        event_data: {device_id: sim_heizband}
    action:
      - service: >
          {{ 'input_boolean.turn_on'
             if trigger.event.data.action in ('activate', 'adjust')
             else 'input_boolean.turn_off' }}
        target: {entity_id: input_boolean.sim_heizband}
```

Give the sim device a power template sensor that follows its boolean
(rated watts when on, 0 when off) and the loop is fully closed — SEM's
own decisions drive the "hardware", and every downstream mechanism
(runtime targets, anti-cycling, the night ledger's outcome record) runs
exactly as it would live.

## Simulating the inputs

Every input SEM plans against can be a plain HA entity you control:

| Input | How to simulate |
|---|---|
| Dynamic prices | A template sensor with `raw_today`/`raw_tomorrow` (Nordpool shape) or `prices` (ENTSO-E shape). See `packages/sem_sim_dynamic_price.yaml` on the test rig — **generate `raw_tomorrow` too**, or night plans see only the dying hours of today. |
| Solar / grid / battery power | `input_number` or posted sensor states; SEM's sensor reader treats them like any hardware. |
| Battery SOC | An `input_number` wired as the SOC sensor. |
| Room temperature (comfort bands) | An `input_number` as `comfort_entity`; drift it with a small script to exercise willing/banked/forced. |
| EV connection | `input_boolean` as the plug sensor. |
| Loads | `input_boolean` as the control entity + a power template sensor. |

## Running cases back to back

The planner re-stamps within one cycle of any demand-shaping change
(prices, targets, connection, comfort, stop conditions), so a "scenario"
is: **set the inputs → wait two cycles (~20 s) → read the verdict** from
`sensor.sem_energy_plan` (demands, blocks, coverage, why-codes). A whole
night's worth of edge cases runs in an evening:

1. Post a price curve → assert cheap-hours blocks land in the valley.
2. Drop the sim SOC → assert the battery pre-charge packs.
3. Warm the sim room past target+offset → assert the load leaves the plan
   (`stop_condition_met` is a collector gate); cool it → it returns.
4. Flip the plug boolean → assert the EV demand appears/vanishes.
5. `solar_energy_management.replan` is the manual lever when you change
   something the demand signature does not watch (the honest test/ops
   restamp; the cause is recorded as `manual`).

Provocations: delete the stamp from storage while HA is stopped (the
next boot must say "no plan — the reactive layer decides alone" and
re-stamp); reboot mid-block (the stamp must survive with the same
`computed_at`); flip the actuation kill-switch (coverage must flip to
"actuation off" and back without a restamp).

## What this cannot test

The last centimeter: brand adapters talking to real firmware (Modbus
quirks, UDP blips, contactor behavior, a car's BMS). That is what the
production soak covers — everything above that seam is fully simulable.
