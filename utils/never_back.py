"""(#1437) A counter that adds up over a period never steps back inside it.

#1382 held the meter-backed daily rows (grid, battery, house, flows). The
counters SEM derives from two rows are a difference: the day's base load is
the house minus the controlled loads, the CO₂ saved is solar minus export.
A step in the subtracted row pulls them back a little (PROD 26.11: base load
9.29 → 9.28 kWh eight times, CO₂ 0.02 → 0.01 kg twice). The same rule
therefore lives at the one place every counter is published: the sensor.

Every sensor with a TOTAL or TOTAL_INCREASING state class is named here,
either as a counter that never steps back or with the reason it may fall —
a test fails for a new counter that is in neither list.

Counters built per charger, per PV string or per device have a key with
an id in it; they are named by their family, the key with ``{}`` for the id.

The hold is bounded like #1382's: a published value is held by at most
``NEVER_BACK_MAX`` (in the sensor's own unit) above the new value, so a
larger drop shows, 0.1 above the new value. The period changing (a new
``last_reset``) ends the hold. A TOTAL_INCREASING counter has no
``last_reset``: a fall below ``RESET_SHARE`` of the last value is a new
cycle, as Home Assistant reads it, and shows as it is.
"""
from __future__ import annotations

import re
from typing import Optional

#: The most a published counter is held above a lower new value, in the
#: sensor's unit (kWh, kg, trees, sessions). The same 0.1 as #1382's
#: ``HOLD_MAX_KWH``; the PROD step-backs were 0.01.
NEVER_BACK_MAX = 0.1

#: A TOTAL_INCREASING counter that falls below this share of its last value
#: starts a new cycle: Home Assistant's own reset rule for that state class.
RESET_SHARE = 0.9

#: Counters that never step back inside their period.
NEVER_BACK_KEYS: frozenset[str] = frozenset({
    # day rows and the counters derived from them
    "daily_battery_charge_energy", "daily_battery_charge_grid",
    "daily_battery_charge_solar", "daily_battery_discharge_energy",
    "daily_co2_avoided", "daily_ev_energy", "daily_grid_export_energy",
    "daily_grid_export_negative_kwh", "daily_grid_import_energy",
    "daily_home_energy", "daily_solar_energy", "daily_total_consumption",
    "daily_true_baseload_energy",
    # the day's flows
    "flow_battery_to_ev_energy", "flow_battery_to_grid_energy",
    "flow_battery_to_home_energy", "flow_grid_to_battery_energy",
    "flow_grid_to_ev_energy", "flow_grid_to_home_energy",
    "flow_solar_to_battery_energy", "flow_solar_to_ev_energy",
    "flow_solar_to_grid_energy", "flow_solar_to_home_energy",
    # month and year
    "monthly_battery_charge_energy", "monthly_battery_discharge_energy",
    "monthly_ev_consumption_energy", "monthly_grid_export_energy",
    "monthly_grid_import_energy", "monthly_home_consumption_energy",
    "monthly_solar_yield_energy",
    "yearly_battery_charge_energy", "yearly_battery_discharge_energy",
    "yearly_co2_avoided", "yearly_ev_energy", "yearly_grid_export_energy",
    "yearly_grid_import_energy", "yearly_home_consumption_energy",
    "yearly_solar_yield_energy", "yearly_trees_equivalent",
    # device periods and sessions (their own last_reset)
    "heat_pump_energy_today", "heat_pump_energy_month",
    "heat_pump_energy_year", "heat_pump_energy_total",
    "heat_pump_energy_shifted_today",
    "session_energy", "battery_session_energy",
    # lifetime
    "lifetime_co2_avoided", "lifetime_ev_energy", "lifetime_ev_sessions",
    "lifetime_ev_solar", "lifetime_solar_yield_energy",
    "lifetime_trees_equivalent",
})

_MONEY = ("money: a refund, an export credit or a negative price can lower "
          "it inside its period")

#: Totals that may fall inside their period, with the reason.
MAY_FALL: dict[str, str] = {
    "forecast_today_kwh": "a forecast: each new forecast replaces the last",
    "forecast_tomorrow_kwh": "a forecast: each new forecast replaces the last",
    "forecast_remaining_today_kwh": "what is left of today's forecast falls as the day runs",
    "battery_cycles_estimated": "an estimate SEM recomputes from the battery's own counters",
    **{k: _MONEY for k in (
        "battery_session_cost", "battery_session_savings",
        "daily_battery_grid_cost", "daily_battery_savings", "daily_costs",
        "daily_export_revenue", "daily_export_value", "daily_feed_in_fees",
        "daily_grid_export_negative_cost", "daily_net_cost", "daily_savings",
        "daily_self_consumption_value",
        "monthly_battery_savings", "monthly_costs", "monthly_export_revenue",
        "monthly_net_cost", "monthly_savings",
        "yearly_battery_savings", "yearly_costs", "yearly_export_revenue",
        "yearly_export_value", "yearly_feed_in_fees", "yearly_net_cost",
        "yearly_savings", "yearly_self_consumption_value",
        "lifetime_ev_cost", "lifetime_grid_cost", "lifetime_total_savings",
        "power_charge_cost", "roi_annual_savings", "session_cost",
    )},
}


#: Counter families that never step back inside their period.
NEVER_BACK_FAMILIES: frozenset[str] = frozenset({
    "charger_{}_session_energy", "charger_{}_daily_energy",
    "charger_{}_flow_solar_to_ev_energy", "charger_{}_flow_grid_to_ev_energy",
    "charger_{}_flow_battery_to_ev_energy",
    "pv_string_{}_daily_energy",
})

#: Counter families that may fall inside their period, with the reason.
MAY_FALL_FAMILIES: dict[str, str] = {
    "charger_{}_session_energy_external": (
        "the charger's own counter, shown as the charger reads it; the "
        "charger resets it when it likes"),
    "daily_tariff_cost_{}": _MONEY,
}

_FAMILY_RES = tuple(
    (family, re.compile("(.+)".join(re.escape(p) for p in family.split("{}"))))
    for family in sorted(NEVER_BACK_FAMILIES | set(MAY_FALL_FAMILIES)))


def family_of(key: str) -> Optional[str]:
    """The family a per-charger / per-string / per-device key belongs to."""
    for family, pattern in _FAMILY_RES:
        if pattern.fullmatch(key):
            return family
    return None


def is_never_back(key: str) -> bool:
    """True for a counter that never steps back inside its period."""
    return key in NEVER_BACK_KEYS or family_of(key) in NEVER_BACK_FAMILIES


def never_back(value: float, floor: Optional[float]) -> float:
    """The value to publish: ``value``, held by at most ``NEVER_BACK_MAX``
    when it is below ``floor`` (the value published before in the same
    period). ``floor`` None — a new period, or nothing published yet —
    publishes the value as it is."""
    if floor is None or value >= floor:
        return value
    return value + min(floor - value, NEVER_BACK_MAX)
