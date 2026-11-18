# Test SEM without real hardware

You can test SEM's plans, decisions and timing with simulated inputs.
Use **Watch only** so that no device receives a command.

## Watch only

Watch only is the one name for observer mode. Its switch is
`switch.sem_observer_mode`.

- Turn it on or off on **System › Health › Watch only**.
- With Watch only on, SEM runs in full. It reads the sensors, makes
  plans and makes decisions. Only the last step, the command to the
  device, is not sent.
- SEM's own settings stay editable. Device actions are blocked.
- The setting is saved, so it holds from the first cycle after a restart.

Keep Watch only on when a real charger or battery is shared with a live
system. Two controllers on one device cause conflicts.

## What SEM publishes in Watch only

| Where | What you read |
|---|---|
| `switch.sem_observer_mode`, attribute `would_decisions` | One row per device SEM decided on this cycle: `action`, `power_w`, `source`, `reason`. Keys look like `ev:<charger_id>` and `battery:<battery_id>`. Empty when Watch only is off. |
| `switch.sem_observer_mode`, attribute `withheld_commands` | The exact service call and data a device would have received. |
| Event `solar_energy_management_observer_decision` | Fires when a decision changes. Unchanged decisions do not fire. |

Judge a charger on `withheld_commands`. The reason text alone does not
show what would reach the device.

## Simulate the inputs

Every input that SEM plans with can be a Home Assistant entity that you
control.

| Input | How to simulate |
|---|---|
| Prices | A template sensor with `raw_today` and `raw_tomorrow` (Nord Pool style) or `prices` (ENTSO-E style). Set tomorrow's prices too. Without them the night plan sees only the rest of today. |
| Solar, grid and battery power | `input_number`, or a sensor you post states to. |
| Battery charge level | `input_number` set as the charge level sensor. |
| Room temperature | `input_number` set as the comfort sensor. |
| Car connected | `input_boolean` set as the plug sensor. |
| Devices | `input_boolean` as the control entity, plus a power template sensor. |

Simulate the input, never an entity that a real integration updates. The
integration writes its own value again within one poll.

## Run a test case

1. Change the inputs, for example post a price curve.
2. Wait 20 seconds for two cycles.
3. Read `sensor.sem_energy_plan`. Its state is `fits`, `yields`, `idle`
   or `pending`. Its attributes `demands`, `blocks`, `takeover` and
   `computed_at` hold the detail.

To make SEM plan again at once, call `solar_energy_management.replan`.
The plan survives a restart, so `computed_at` does not change after one.

Useful checks:

- Cheap price hours give battery or EV blocks in the cheapest hours.
- A lower battery charge level gives a battery pre-charge block.
- Connecting a car adds an EV demand. Disconnecting it removes the demand.
- A restart in the middle of a block keeps the same block.

For a full list of diagnostics, call `solar_energy_management.diagnose`.

## Compress time: test an evening in minutes

SEM starts the night at sunset plus an offset. The offset is
`number.sem_night_start_offset_min`, from 0 to 400 minutes in steps of
5, with a default of 30. Sunset comes from `sun.sun`.

To test the evening now:

1. Set `sun.sun` so that `next_setting` is a few minutes in the past.
   Post the state again often, so that the real sun integration does
   not overwrite it.
2. Set the offset so that sunset plus offset is the evening you want.
3. Watch `would_decisions` and `withheld_commands`.
4. When you finish, stop the hold and restore the offset.

## Test a hardware write

Use this when you must see a write on the device, not only the decision.

1. Replace the grid sensors with simulated split sensors, one for import
   and one for export, and hold them at fixed values.
2. Run with Watch only on. Check that `withheld_commands` shows the call
   you expect.
3. Before you turn Watch only off, check that no other device has a
   withheld command for a charge that is due now.
4. Turn Watch only off for a short, fixed time. Watch the car's charging
   sensor. Turn Watch only on again as soon as the car starts to draw.
5. Read the device register from a second Home Assistant host, or force an
   update of the sensor with `homeassistant.update_entity`. A sensor
   can show a stale value for a while after a write.

## Replay recorded days on the Insights screen

Insights has a **Replay** topic. It replays past days with another setting.
The topic is shown only when **System › Notifications and more › simulation
tab** is on.

1. Open **Insights › Replay**.
2. Pick a period, or a day type such as sunny or car charged.
3. Set a **What if** value: battery size, battery reserve, peak limit,
   import price or export value. Or pick a scenario.
4. Run the simulation and read the difference.

SEM tags each day after midnight. Results after a changed decision are
estimates, not measurements.

## What a simulation cannot test

The last part of the device path is not simulated: the brand adapter
against real firmware, Modbus behaviour, contactor timing and the car's
battery system. A live soak test covers this. Use Watch only on a live
system until that test is done.
