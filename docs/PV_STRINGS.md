# Per-string solar

If your inverter reports each PV string (roof side or tracker), SEM
shows each string's power and energy today.

## What you get

When SEM finds at least two strings, it creates two sensors per string,
up to four strings:

```
sensor.sem_pv_string_pv1_power         W
sensor.sem_pv_string_pv1_daily_energy  kWh, resets at midnight
sensor.sem_pv_string_pv2_power
sensor.sem_pv_string_pv2_daily_energy
...
```

With one string, SEM creates no string sensors.

Name a string under **System › All settings**. The name replaces *PV1*,
*PV2* on the sensors.

The number of strings shows on **System › Hardware**.

## How SEM finds the strings

SEM looks for strings in this order:

1. Strings you list yourself.
2. Sensors in the same integration as your solar sensor (from the HA
   Energy Dashboard), whose names match a known pattern.
3. Each inverter's own total, when there are several inverters and no
   per-string sensor.

Patterns SEM recognises:

| Brand | Pattern |
|---|---|
| Huawei, GoodWe, Growatt | `*_pv1_power`, `*_pv2_power` |
| Sungrow | `*_mppt1_power`, `*_mppt2_power` |
| Fronius, SolarEdge | `*_dc_power_1`, `*_dc_power_2` |
| Kostal Plenticore | `*_dc1_power`, `*_dc2_power` |
| Victron | `*_tracker_1_power`, `*_tracker_2_power` |
| Generic | `*_string_1_power`, `*_string_2_power` |

If your inverter uses another name, the strings are not found. Name them
by hand, or open an issue with the entity IDs.

## Voltage and current instead of power

Some integrations, often Modbus, give voltage and current per string but
no power. If SEM finds a voltage and a current for the same string, it
multiplies them to get the power.

Voltage and current names in English and German are recognised, for
example `*_pv1_voltage` or `*_pv_1_spannung`, and `*_pv1_current` or
`*_pv_1_strom`.

If a string has both a power sensor and a voltage and current pair, SEM uses
the power sensor.

## If you do not see your strings

Check these in order:

1. The solar sensor is set in the Energy Dashboard. SEM starts from it.
2. The string sensors are in the same integration as the solar sensor.
3. The sensor names match a pattern above. Look in **Developer tools › States**.
4. There are at least two strings.
5. The log has `Per-PV-string discovery: N direct power, M V+I pairs`. If
   the line is missing, nothing was found.

Also see [TROUBLESHOOTING.md](TROUBLESHOOTING.md#values-look-wrong).

## Notes

- The string totals add up to the solar total, within rounding.
- A string that goes quiet keeps its value until midnight.
- SEM does not split a string's power between the house, the battery and the
  car. It shows the string's own output.
