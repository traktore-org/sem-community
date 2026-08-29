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

That principle now holds for **every** family. Until 16.08.2026 it was
true of loads only: for EV chargers and batteries the cut sat *above* the
decision, so observing meant no adapter was built, `decide()` and
`decide_battery()` never ran, and there was nothing to publish — a
two-battery rig reported `adapters = {}` in diagnostics and read as a
misconfiguration. The cut is now at the write for all three (#764), so
the executor is simulable the same way the planner always was.

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

   The map is a **roster, not a ledger**: it carries exactly the devices
   that decided this cycle. One that stops deciding — a charger
   deregistered, a load taken out of surplus management, a startup-only
   code path that fired once — leaves the map at the end of that cycle
   rather than lingering as a ghost row. So a row's presence is itself a
   signal, and a count you read off the attribute is the live count.

   Deciding to leave a device alone is still deciding: a battery set to
   `off` keeps its row and reports `action: off` ("SEM hands-off — inverter
   self-manages"), and a charger set to `off` reports `action: disable`.
   The absence of a row means SEM has nothing to say about that device;
   `off` means SEM would deliberately do nothing.

   Chargers and batteries share the map, keyed `ev:<charger_id>` and
   `battery:<battery_id>`, with `kind` naming the family — one attribute
   carries the whole shadow cycle:

   ```yaml
   would_decisions:
     ev:keba_fa87f74cd3:
       kind: charger
       action: charge_at_amps  # idle | disable | charge_at_amps | charge_max
       amps: 10
       power_w: 6900.0         # what the box would actually pull
       source: min_plus_solar  # the resolved charge mode
       reason: "night floor — deadline 06:00"
     battery:b1:
       kind: battery
       action: force_charge    # normal | limit_discharge | force_charge |
                               # stop_force_charge | force_discharge | off
       power_w: 3000.0
       reason: "planned window 03:00–05:00 — deficit 3.0 kWh"
   ```

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

## Simulate the input, never the entity a real device owns

Point SEM at *simulated* entities (`input_boolean`, `input_number`,
template sensors) — those the harness owns outright. An entity a live
integration publishes cannot be held: the integration republishes its own
truth within a poll and wins. On the shared clone that is the KEBA plug
sensor — with a real cable connected, "the car went away" is not a state
the rig can enter, no matter how many `POST /api/states` calls the harness
makes.

So a harness check has **three** verdicts, not two: pass, fail, and
*untestable*. Probe first (hold the value, read it back, see whether it
sticks), and when the precondition is unreachable say so. A rig limit
reported as a failure trains you to skim past failures; reported as a pass
it hides untested surface. Both are worse than an honest "not testable
today, and here is what proves the same property instead".

## Observer mode survives a restart — and where it is recorded

Observer mode is a promise about hardware, so it has to hold across a
restart *from the first cycle*, not from whenever the switch entity happens
to attach. The flag is recorded in the config entry (options, or data from
the install flow) and setup reads it before the coordinator is built.

Installs older than the persisted toggles (before 18.07.2026) recorded it
only in Home Assistant's restore store — the switch entity's own last
state, which setup could not see. Those came up **armed** until the switch
attached, and lost the setting entirely if the machine stayed off past the
restore store's seven-day expiry. Since 16.08.2026 setup reads that store
too and writes what it finds into the config entry, so the recovery happens
once and the flag is explicit from then on. You will see it in the log:

```
Recovered observer_mode=on from the switch restore store — this install
predates the persisted toggles ...
```

To confirm an install is protected from the first cycle, look for
`Observer mode: hardware control disabled` on the coordinator's own
startup line, before any platform sets up. If observer is on and that line
is missing, the flag is not reaching setup — report it.

## What this cannot test

The last centimeter: brand adapters talking to real firmware (Modbus
quirks, UDP blips, contactor behavior, a car's BMS). That is what the
production soak covers — everything above that seam is fully simulable.
