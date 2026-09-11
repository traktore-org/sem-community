"""(#923) What this install HAS — one answer, three states.

SEM is a core (solar, grid, home, energy balance, totals, forecast) plus
hardware modules: a home battery, an EV charger, a heat pump, a hot-water
tank. Every surface that depends on a module — its entities, its dashboard
tab, the cards that reference it, the welcome text — asks THIS module, so
they cannot disagree. Before #923 "has a battery" was decided in four
places, each slightly differently (#857).

Two rules make the verdict safe to act on:

* It comes from CONFIGURATION, never from live sensor state. A sensor that
  is momentarily unavailable says nothing about whether the hardware exists
  — reading it as "absent" is #875 ("unread is not zero") at module scale.
* "I could not read the Energy Dashboard" is UNKNOWN, never ABSENT (#925).
  UNKNOWN keeps everything: a slow boot must never hide a real battery.

Pure stdlib on purpose — no Home Assistant import — so it can be tested
without an instance and loaded by ``~/bin/validate-sem.sh``.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Iterable, Mapping


class Module(Enum):
    BATTERY = "battery"
    EV = "ev"
    HEAT_PUMP = "heat_pump"
    HOT_WATER = "hot_water"


class Presence(Enum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


# Only WIRING counts — a key that connects SEM to a Home Assistant entity or
# service of that hardware. ``battery_capacity_kwh`` is deliberately absent:
# the options flow's Settings step saves it with a default for every install
# that passes through it (config_flow.py, step "settings"), so it describes a
# battery without proving one. Heat-pump tunables (boost offset, rated power,
# priority) are left out for the same reason.
BATTERY_WIRING_KEYS: tuple[str, ...] = (
    "battery_soc_sensor",
    "battery_power_sensor",
    "battery_discharge_control_entity",
    "battery_discharge_control_entities",
    "battery_force_discharge_control_entity",
    "battery_force_discharge_entities",
    "battery_strategy_control_entity",
    "battery_strategy_entities",
)
EV_WIRING_KEYS: tuple[str, ...] = (
    "ev_chargers",
    "ev_charging_power_sensor",
    "ev_power_sensor",
)
HEAT_PUMP_WIRING_KEYS: tuple[str, ...] = (
    "heat_pumps",
    "heat_pump_relay1_entity",
    "heat_pump_relay2_entity",
    "heat_pump_climate_entity",
    "heat_pump_sg_ready_service",
    "heat_pump_sg_ready_state_entity",
    "heat_pump_power_sensor",
    "heat_pump_energy_sensor",
)
HOT_WATER_WIRING_KEYS: tuple[str, ...] = ("hot_water_entity",)

# Every key the oracle reads. Setting one through set_option must reload the
# entry, or the module's entities wait for the next restart — pinned by
# tests/test_923_structural_keys.py against _SET_OPTION_STRUCTURAL_KEYS.
MODULE_EVIDENCE_KEYS: frozenset[str] = frozenset(
    BATTERY_WIRING_KEYS + EV_WIRING_KEYS + HEAT_PUMP_WIRING_KEYS + HOT_WATER_WIRING_KEYS
)

_EMPTY: tuple[Any, ...] = (None, "", [], {}, ())


def _wired(config: Mapping[str, Any], keys: Iterable[str]) -> bool:
    return any(config.get(key) not in _EMPTY for key in keys)


def has_managed_charger(config: Mapping[str, Any]) -> bool:
    """A charger SEM was TOLD about — the #595 rule for the EV tab and the
    welcome text's charge-mode line. Not the same question as "does this
    install have EV data": an Energy Dashboard EV consumer feeds
    ``sem_ev_power`` with no charger configured."""
    return bool(config.get("ev_chargers") or config.get("ev_charging_power_sensor"))


def install_modules(
    config: Mapping[str, Any],
    ed_config: Any | None,
    ed_answered: bool,
) -> dict[Module, Presence]:
    """The module verdict for one install.

    ``ed_config`` is the parsed Energy Dashboard config (an
    ``EnergyDashboardConfig``) or None. ``ed_answered`` is whether the Energy
    Dashboard question got an answer at all: True when the file was parsed
    OR provably does not exist, False when the read failed or has not run
    yet. Battery and EV can be declared there, so for them no answer means
    UNKNOWN. Heat pump and hot water exist only in SEM's own options, which
    are always readable — they are never UNKNOWN.
    """
    ed_battery = bool(getattr(ed_config, "has_battery", False)) if ed_config is not None else False
    ed_ev = bool(getattr(ed_config, "has_ev", False)) if ed_config is not None else False

    def _config_or_dashboard(wired: bool, declared: bool) -> Presence:
        if wired or declared:
            return Presence.PRESENT
        return Presence.ABSENT if ed_answered else Presence.UNKNOWN

    def _config_only(wired: bool) -> Presence:
        return Presence.PRESENT if wired else Presence.ABSENT

    return {
        Module.BATTERY: _config_or_dashboard(_wired(config, BATTERY_WIRING_KEYS), ed_battery),
        Module.EV: _config_or_dashboard(_wired(config, EV_WIRING_KEYS), ed_ev),
        Module.HEAT_PUMP: _config_only(_wired(config, HEAT_PUMP_WIRING_KEYS)),
        Module.HOT_WATER: _config_only(_wired(config, HOT_WATER_WIRING_KEYS)),
    }


_B = frozenset({Module.BATTERY})
_E = frozenset({Module.EV})
_BE = frozenset({Module.BATTERY, Module.EV})
_HP = frozenset({Module.HEAT_PUMP})
_HW = frozenset({Module.HOT_WATER})


def _rows(platform: str, modules: frozenset, keys: tuple[str, ...]) -> dict:
    return {(platform, key): modules for key in keys}


# (platform, description key) -> the modules that entity needs. A key that is
# not here is CORE and is always created. Cross-module entities list every
# module they need — battery→EV assist needs both. The dashboard generator
# and validate-sem.sh read this same table, so the entity set, the dashboard
# and the validation cannot disagree.
ENTITY_MODULES: Mapping[tuple[str, str], frozenset[Module]] = {
    **_rows("sensor", _B, (
        "battery_capacity_drift_pct", "battery_charge_pacing",
        "battery_charge_power", "battery_cycles_estimated",
        "battery_discharge_power", "battery_dynamic_floor_pct",
        "battery_health_score", "battery_measured_capacity_kwh", "battery_power",
        "battery_priority_status", "battery_scheduler_deficit_kwh",
        "battery_scheduler_reason", "battery_scheduler_state",
        "battery_scheduler_target_soc", "battery_session_avg_power",
        "battery_session_cost", "battery_session_duration",
        "battery_session_energy", "battery_session_savings",
        "battery_session_solar_share", "battery_session_type", "battery_soc",
        "battery_spendable_kwh", "battery_status", "battery_stored_grid_share",
        "battery_temperature", "daily_battery_charge_energy",
        "daily_battery_charge_grid", "daily_battery_charge_solar",
        "daily_battery_discharge_energy", "daily_battery_grid_cost",
        "daily_battery_savings", "diag_battery_capacity", "diag_battery_sign",
        "flow_battery_to_grid_energy", "flow_battery_to_grid_power",
        "flow_battery_to_home_energy", "flow_battery_to_home_power",
        "flow_grid_to_battery_energy", "flow_grid_to_battery_power",
        "flow_solar_to_battery_energy", "flow_solar_to_battery_power",
        "monthly_battery_charge_energy", "monthly_battery_discharge_energy",
        "monthly_battery_savings", "yearly_battery_charge_energy",
        "yearly_battery_discharge_energy", "yearly_battery_savings",
    )),
    **_rows("number", _B, (
        "battery_auto_start_soc", "battery_buffer_soc", "battery_capacity",
        "battery_max_discharge_power", "battery_priority_soc",
    )),
    **_rows("switch", _B, (
        "battery_charge_pacing_enabled", "battery_may_export",
        "forecast_spending_enabled",
    )),
    **_rows("binary_sensor", _B, (
        "battery_charging", "battery_discharging",
    )),
    **_rows("button", _B, (
        "backfill_battery_nights",
    )),
    **_rows("sensor", _BE, (
        "flow_battery_to_ev_energy", "flow_battery_to_ev_power",
        "lifetime_ev_battery_share",
    )),
    **_rows("number", _BE, (
        "battery_assist_max_power", "battery_assist_min_surplus",
    )),
    **_rows("switch", _BE, (
        "battery_may_assist_ev",
    )),
    **_rows("sensor", _E, (
        "calculated_current", "charging_recommendation", "charging_strategy",
        "daily_ev_energy", "diag_charger_control", "energy_ev_solar_percentage",
        "ev_charger_count", "ev_power", "ev_remaining_range", "ev_taper_trend",
        "flow_grid_to_ev_energy", "flow_grid_to_ev_power",
        "flow_solar_to_ev_energy", "flow_solar_to_ev_power", "lifetime_ev_cost",
        "lifetime_ev_energy", "lifetime_ev_grid_share", "lifetime_ev_sessions",
        "lifetime_ev_solar", "lifetime_ev_solar_share",
        "monthly_ev_consumption_energy", "night_charging_status", "session_cost",
        "session_duration", "session_energy", "session_solar_share",
        "solar_charging_status", "vehicle_soc", "yearly_ev_energy",
    )),
    **_rows("number", _E, (
        "ev_disable_delay_seconds", "ev_enable_delay_seconds",
    )),
    **_rows("binary_sensor", _E, (
        "ev_charging", "ev_connected",
    )),
    **_rows("sensor", _HP, (
        "heat_pump_energy_month", "heat_pump_energy_shifted_today",
        "heat_pump_energy_today", "heat_pump_energy_total", "heat_pump_energy_year",
        "heat_pump_mode", "heat_pump_registration_status",
        "heat_pump_sg_ready_state",
    )),
    **_rows("number", _HP, (
        "heat_pump_boost_offset",
    )),
    **_rows("binary_sensor", _HP, (
        "heat_pump_registered", "heat_pump_solar_boost",
    )),
    **_rows("number", _HW, (
        "hot_water_max_temperature", "hot_water_solar_target",
        "legionella_interval_hours", "legionella_target_temp",
    )),
}

# Keys that LOOK like a module but are core on purpose. The naming ratchet in
# tests/test_923_install_modules.py makes every look-alike choose a side.
CORE_BY_DECISION: Mapping[tuple[str, str], str] = {
    ("sensor", "charging_state"): (
        "carries the Home tab's today_plan (solar peak, price windows, night) "
        "and is the Config tab's set-up marker — on every install"),
    ("sensor", "diag_charger_count"): (
        "how '0 chargers found' stays visible on an install without one"),
    ("sensor", "power_charge_cost"): (
        "the tariff's demand charge (load management), not EV charging"),
    ("number", "demand_charge_rate"): (
        "the tariff's demand-charge rate, not EV charging"),
}


def all_unknown() -> dict[Module, Presence]:
    return {module: Presence.UNKNOWN for module in Module}


def keeps(presence: Mapping[Module, Presence], required: Iterable[Module]) -> bool:
    """Something that needs ``required`` is kept unless one of them is
    definitively ABSENT — UNKNOWN keeps."""
    return all(presence.get(m, Presence.UNKNOWN) is not Presence.ABSENT for m in required)


def entity_kept(platform: str, key: str, presence: Mapping[Module, Presence]) -> bool:
    return keeps(presence, ENTITY_MODULES.get((platform, key), frozenset()))


def kept_descriptions(
    platform: str, descriptions: Iterable[Any], presence: Mapping[Module, Presence],
) -> list:
    """The static descriptions a platform creates for this install. The SAME
    list must feed the platform's stale-entity sweep: that sweep is what
    removes an ABSENT module's leftover registry entries (spec §6)."""
    return [d for d in descriptions if entity_kept(platform, d.key, presence)]


def presence_of(coordinator: Any) -> dict[Module, Presence]:
    """The verdict the platforms were built with (``setup_presence``). All
    UNKNOWN — build everything — when there is none: no coordinator, one
    from before the setup step, or a test double."""
    presence = getattr(coordinator, "setup_presence", None)
    if isinstance(presence, dict) and presence and all(
        isinstance(m, Module) and isinstance(p, Presence) for m, p in presence.items()
    ):
        return {**all_unknown(), **presence}
    return all_unknown()


def absent_entity_ids(presence: Mapping[Module, Presence]) -> frozenset[str]:
    """Entity ids of every module entity this install does NOT create —
    what the dashboard generator removes references to. SEM forces
    ``<platform>.sem_<key>`` for every static entity."""
    return frozenset(
        f"{platform}.sem_{key}"
        for (platform, key), modules in ENTITY_MODULES.items()
        if not keeps(presence, modules)
    )


def presence_summary(presence: Mapping[Module, Presence]) -> dict[str, str]:
    """``{"battery": "present", ...}`` — the diagnostic attribute and the
    downloadable diagnostics."""
    return {module.value: presence.get(module, Presence.UNKNOWN).value for module in Module}
