# Multi-device setup

Add a second EV charger, or a second load such as a pool pump or heat pump.
Read [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) first for what does not work.

## Where things are

| You want to | Go to |
|---|---|
| Add a charger, or change its entities and current | **System › Chargers** |
| Add a load that SEM switches | **Devices › Add a device** |
| Set a load's mode, goal or order | **Devices**, on the device's card |
| Check what a charger or load did | **Now** or **Insights** |

## Add a second charger

1. Open **System**, then **Chargers**. Tap **Add charger**. SEM adds a row named *New charger*.
2. Tap the row. Set the fields:

   | Field | Use |
   |---|---|
   | Current control entity | The `number` that sets the current. Use it or the start/stop entity, see below. |
   | Start/stop entity | The `switch` or `button` that starts and stops the charge. |
   | Connected sensor | The plug sensor. |
   | Power sensor | The charger's power in W. |
   | Car charge level sensor | Optional. Gives the real car SOC. |
   | Phase switch entity | Optional. Only for a charger that can switch 1 and 3 phases. |

3. Set the charger's phases and current limits. The row shows them as *N phases* and *min to max*.
4. Set *Target unit* to **kWh** or **car charge %**. Use kWh if two cars share the charger.

To remove a charger, tap **Remove** on its name, then confirm.

Each charger also gets its own entities. `<id>` is the charger's id:

| Entity | Meaning |
|---|---|
| `sensor.sem_charger_<id>_power` | Charging power (W) |
| `sensor.sem_charger_<id>_session_energy` | Energy in this session (kWh) |
| `sensor.sem_charger_<id>_session_solar_share` | Share of the session from solar (%) |
| `sensor.sem_charger_<id>_daily_energy` | Energy today (kWh) |
| `sensor.sem_charger_<id>_estimated_soc` | Estimated car SOC (%) |
| `number.sem_charger_<id>_daily_ev_target` | Night target (kWh) |
| `number.sem_charger_<id>_daily_ev_target_max` | Solar top-up ceiling (kWh) |
| `number.sem_charger_<id>_minimum_current` | Minimum current (A) |

Each charger has its own charge mode and targets. See [EV_CHARGING_LOGIC.md](EV_CHARGING_LOGIC.md#charge-modes).

With two chargers, each one is its own row on **Devices**. Drag the rows to set the order. The top row gets the surplus first.

## Add a second load

Use this for a switch, relay or plug: pool pump, boiler, dumb EV socket.

1. Open **Devices**. Tap **Add a device**.
2. Fill in the fields:

   | Field | Use |
   |---|---|
   | Field | Use |
   |---|---|
   | Name | Any name |
   | Switch SEM turns on and off | A switch entity |
   | Power sensor (optional) | Shows the watts |
   | Power when on, W (optional) | What the load draws when on |

3. Tap **Add**. The device starts in **Off**.
4. Open the device card and choose its mode.

Devices SEM can see but cannot switch are listed above the form, under *Measured, without a switch*. Tap **Control it** to give one a switch.

### Modes

| Mode | What SEM does |
|---|---|
| **Off** | Watches only. Never switches the load. |
| **Peak only** | Your own automations run the load. SEM sheds it at a grid peak. |
| **SEM runs it** | SEM starts and stops the load on solar surplus. |
| **SEM runs it, battery may help** | As above. By day the house battery may also help. |

### Goals for a SEM-run load

On a SEM-run device, set a goal:

- **At least** (`daily_min_runtime_min`): a daily floor, in minutes.
- **Up to** (`daily_max_runtime_min`): the daily cap, in minutes.
- **Stop when** (`stop_entity` and `stop_at`): a sensor and a value, for example a car SOC of 80.

On a dark day a load does not reach its floor. It draws grid power only if you allow it: **May SEM buy power for it?** or **Finish overnight from: Grid**.

### Order and dependencies

- Drag a device to change its order. The top device gets the surplus first.
- **Requires** on a device makes it wait for another device. The child starts only when its parent runs. Children stay under their parent and cannot be dragged out.
- Chain example: pump, then heater, then lights. Stopping the pump stops the children.

## Use the surplus signal in your own automation

Use this to keep your own schedule and start it on solar surplus.

- `binary_sensor.sem_surplus_available` turns on after the surplus stays above `number.sem_surplus_event_threshold` (default 1500 W) for 60 s. It turns off after the surplus stays below 80 % of the threshold for 120 s.
- The event `solar_energy_management_surplus` fires on each change. Its data includes `available`, `surplus_w` and `threshold_w`.

```yaml
automation:
  - alias: Pool pump on solar surplus
    triggers:
      - trigger: state
        entity_id: binary_sensor.sem_surplus_available
        to: "on"
    actions:
      - action: switch.turn_on
        target: { entity_id: switch.pool_pump }
```

Set the load's mode to **Peak only** so SEM does not also switch it.

## Register a load with a service

Use this to set up a load in a script or from YAML. It does the same as **Add a device**.

```yaml
service: solar_energy_management.register_surplus_device
data:
  device_id: pool_pump
  entity_id: switch.pool_pump
  name: Pool pump
  rated_power: 800          # W when on
  priority: 5               # starting slot; lower gets surplus first
  daily_min_runtime_min: 240
  daily_max_runtime_min: 480
  top_up_policy: solar_only # or cheap_hours
  stop_entity: sensor.car_soc
  stop_at: 80
```

| Field | Notes |
|---|---|
| `device_id` | Unique id |
| `entity_id` | The switch, or the `climate` entity |
| `device_type` | `switch` (default) or `climate` |
| `hvac_mode`, `target_temperature` | For `climate` only |
| `priority` | Only the starting slot. A drag on **Devices** wins later. |
| `control_mode` | `off`, `peak_only` or `surplus` |

To set a parent later:

```yaml
service: solar_energy_management.update_device_config
data:
  device_id: pool_heater
  property: depends_on
  value: pool_pump
```

Remove a load with `solar_energy_management.unregister_surplus_device`.

## Limits

See [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md#chargers) for the charger and load limits, and [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for fixes.

For developers, the rules for the per-charger loop are in [MULTI_CHARGER.md](MULTI_CHARGER.md).
