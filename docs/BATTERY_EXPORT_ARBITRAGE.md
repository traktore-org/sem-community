# Battery export arbitrage

On a dynamic tariff, the export price can be high in the evening and low
at night. Battery export arbitrage sells stored battery energy to the grid
in the high-price hours. It buys the energy back cheaper later.

It is **off by default**. SEM sells nothing until you turn it on.

## Check your grid contract first

Some grid operators allow only solar energy to be exported, not energy
from a battery. If your contract does not allow battery export:

- Keep arbitrage off.
- Do not use **Force discharge** for the battery.

Everything else in SEM, such as charging from surplus, self-consumption
and peak shaving, does not export battery energy.

The sensors `sensor.sem_flow_battery_to_grid_power` and
`sensor.sem_flow_battery_to_grid_energy` show how much battery energy went
to the grid. On a restricted contract, the energy should stay at zero.

## When SEM sells

SEM checks these four rules every cycle. All four must be true:

1. The energy plan has a sell window open now. See
   [Energy planner](ENERGY_PLANNER.md).
2. The export price is at least the minimum export price. Default
   0.20 per kWh.
3. The battery charge is above both reserves. The higher reserve applies:
   the battery reserve, or the arbitrage reserve (default 50 %). If the
   charge level is unknown, SEM does not sell.
4. Selling now pays more than buying back later. The check is:
   `export price > cheapest later import ÷ round-trip efficiency + cycle cost`.
   The round-trip efficiency defaults to 0.92.

If one rule is false, the battery uses its normal mode.

## Settings

| Setting | Where | Default |
|---|---|---|
| Global switch `battery_grid_arbitrage_enabled` | No screen row. Set it with the `solar_energy_management.set_option` service. | Off |
| May the battery sell to the grid? | Devices › battery | Off |
| Battery mode: Auto, Self-consumption only, Force charge, Force discharge, Off | Devices › battery | Auto |
| SEM sells down to no lower than (battery reserve) | Devices › battery | 20 % |
| Arbitrage reserve `battery_arbitrage_reserve_soc` | `set_option` service | 50 % |
| Minimum export price `battery_arbitrage_min_export_price` | `set_option` service | 0.20 per kWh |
| Round-trip efficiency `battery_roundtrip_efficiency` | System › Battery rules › More | 0.92 |
| Cycle cost (battery wear per kWh) | System › Battery rules › More | The field shows 0.02. Save it once; until then SEM uses 0 |
| Battery scheduler (must be on) | System › Battery rules › More › scheduler | Off |

Battery modes:

- **Auto**: the scheduler and the plan decide. This mode can sell.
- **Self-consumption only**: never sells to the grid.
- **Force charge**: charges to full now.
- **Force discharge**: sells to the grid now, down to the reserve.
  SEM asks first.
- **Off**: SEM does not command the battery.

## Battery brands

- **Huawei SUN2000 with LUNA2000**: SEM uses the `forcible_discharge_soc`
  service of the `huawei_solar` integration. The service discharges to the
  reserve. The integration must be installed. SEM finds it automatically.
- **Other brands**: SEM writes the discharge power to a discharge control
  entity. Set this entity in the setup flow. Without it, SEM does not sell.

## Turn it off

- Set `battery_grid_arbitrage_enabled` to `false` with `set_option`.
  The sale stops in the next cycle.
- Or set the battery mode to **Self-consumption only** or **Off** on
  Devices.
- To sell less, raise the battery reserve or the minimum export price.

## Limits

- A negative export price is a cost. SEM does not sell at a loss.
- In a flat price market, SEM finds no profitable sale and does nothing.
- The battery must accept a discharge command from SEM.
