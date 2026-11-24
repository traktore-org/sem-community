# Known limitations

What SEM does not do today, and the way around it. Problems with a fix
are in [TROUBLESHOOTING.md](TROUBLESHOOTING.md). EV charge rules are in
[EV_CHARGING_LOGIC.md](EV_CHARGING_LOGIC.md).

## Setup

| Limit | Way around |
|---|---|
| One SEM entry per Home Assistant instance. | Change settings on the one entry. |
| No Energy Dashboard means no automatic sensor list. | Pick the solar, grid and battery sensors by hand. |
| A system with no recognised sensors gets plain entity pickers only. | Pick the entities by hand. |
| A recognised brand is a proposal. Nothing is bound until you confirm it. | Confirm it on System. |
| A service SEM cannot fill in is listed, not offered. | Wire it by hand, as the note says. |
| Brands added from their source are "implemented", not "tested live". | See [SUPPORTED_HARDWARE.md](SUPPORTED_HARDWARE.md). |

## Chargers

| Limit | Way around |
|---|---|
| A charger with no current entity and no start/stop entity is monitored only. | Add the entities on System › Chargers. |
| Tesla Wall Connector is monitored only, with no power sensor or current control. | See [TROUBLESHOOTING.md](TROUBLESHOOTING.md#car-charging). |
| Easee sensors not found. | See [TROUBLESHOOTING.md](TROUBLESHOOTING.md#car-charging). |
| One car per charger. Two cars on one charger make % targets and the virtual SOC wrong. | Use a kWh target. Taper detection still stops a full car. |
| Without a car charge-level sensor, the % target uses an estimate. | Set the car charge-level sensor on the charger. |
| In **Sun + tariff**, the thin-sun rule (thin sun plus grid by day when cheaper) runs only with battery help off. With battery help on, the grid tops up by day only when the night is too short. | Turn battery help off on that charger to use the thin-sun rule. The two day rules will become one. |
| Now from **Charge now** ends at the plan's next block. With no plan, it ends after 2 hours. | Pick a time or **until full** on the charger. |
| Phase switching is off by default. | Turn on "Phase switching" for that charger on System › Chargers. |
| A plug sensor that says off while the charger draws power. SEM treats the car as connected and logs it. | Fix the plug sensor in the charger's integration. |
| KEBA restarts itself about 10 minutes after a stop, at its fallback current. | See [TROUBLESHOOTING.md](TROUBLESHOOTING.md#car-charging). |
| KEBA can start by itself after plug-in. SEM stops it within one cycle (about 10 s). | Unplug the car when you do not want charging. |

## Battery and inverter

| Limit | Way around |
|---|---|
| Discharge limit needs a writable `number` entity. Without it SEM cannot cap discharge. | Pick the discharge entity on System › Battery rules. |
| Battery assist needs a surplus of 0 to 5000 W (default 1200 W). A large array cannot require more than 5000 W. | Set a lower value. |
| The battery can give the car energy that the grid then refills, for a few seconds while it ramps. | Normal. The daily total stays small. |
| Export guard refuses a fixed feed-in tariff. It works only with a dynamic feed-in price. | Pick the dynamic feed-in entity. |
| Export guard needs a control. Deye uses its System Work Mode select. Other brands need a writable export-limit `number`. | Enable the control. A brand with neither is refused with a reason. |
| Battery export arbitrage is off by default. It sells stored energy, which some contracts forbid. | Check your contract first. See [BATTERY_EXPORT_ARBITRAGE.md](BATTERY_EXPORT_ARBITRAGE.md). |
| With arbitrage off, `sensor.sem_flow_battery_to_grid_power` must stay at 0 W. | If it is not 0 W, check the battery mode. |
| Charge pacing writes one charge-power limit entity. A second inverter is not paced. | Pace the inverter that owns the entity. |

## Forecast and spending

| Limit | Way around |
|---|---|
| Forecast features need a forecast source: Solcast, Forecast.Solar, Open-Meteo or Helios. | Install one. "Auto" uses the installed one. |
| Forecast-led battery spending shows *Learning* until 5 nights of battery history exist. | Use *Rebuild from history* on the battery card. |
| Prices come from one tariff model: fixed, dynamic or by schedule. SEM does not read the tariff from the utility. | Type the rates, or the price entity. |
| Critical peak events and block tariffs are not modelled. | See [TARIFF_MODELS.md](TARIFF_MODELS.md#what-each-model-gets). |
| The simulation on Insights is an estimate. | Read it as a trend, not a bill. |

## Loads and peak

| Limit | Way around |
|---|---|
| Peak guard controls only the loads SEM controls. Other loads still draw. | Add the load as a device with a switch. |
| The peak guard stops at the charger's minimum current. A slot can overrun if the house alone is above the limit. | Set a higher grid limit on Devices. |
| A load that needs a switch is monitored only if it has none. | Add a switch, or use *Control it* on Devices. |
| A surplus device runs only on solar. On a dark day its daily target is missed. | Use *Peak only* and your own automation with `binary_sensor.sem_surplus_available`. See [MULTI_DEVICE_GUIDE.md](MULTI_DEVICE_GUIDE.md#use-the-surplus-signal-in-your-own-automation). |
| The grid operator's relay is the hard stop. SEM follows its limit, but only for loads it controls. | Mark a device *Behind the grid operator's relay*. |
</content>
