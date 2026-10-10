"""(#923) What this install HAS — one answer, three states.

SEM is a core (solar, grid, home, energy balance, totals, forecast) plus
hardware modules: a home battery, an EV charger, a heat pump, a hot-water
tank. Every surface that depends on a module — its entities, its dashboard
tab, the cards that reference it, the welcome text — asks THIS module, so
they cannot disagree. Before #923 "has a battery" was decided in four
places, each slightly differently (#857).

(#996) The same table answers a second question: can this house USE a
control? A price threshold needs a dynamic tariff, the export guard needs
an export-limit entity, the forecast rows need a forecast, kWh-per-kWp
needs a plant size, ROI needs an investment. Those are the five
capabilities below the four hardware modules — same states, same
consumers, so a knob with nothing behind it is not created at all rather
than shown live with a plausible number.

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
    # (#996) Capabilities: not hardware, but what a control needs to do
    # anything here. A price knob on a flat tariff, an export guard with no
    # export-limit entity, forecast rows with no forecast — each reports a
    # plausible number and can change nothing. Same three states, same
    # consumers as the hardware modules.
    DYNAMIC_TARIFF = "dynamic_tariff"
    EXPORT_LIMIT = "export_limit"
    SOLAR_FORECAST = "solar_forecast"
    PV_SIZE = "pv_size"
    INVESTMENT = "investment"


class Presence(Enum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


# Only WIRING counts — a key through which SEM reads the module's power or
# state of charge, or drives it. ``battery_capacity_kwh`` is deliberately
# absent: the options flow's Settings step saves it with a default for every
# install that passes through it (config_flow.py, step "settings"), so it
# describes a battery without proving one. Heat-pump tunables (boost offset,
# rated power, priority) are left out for the same reason.
BATTERY_WIRING_KEYS: tuple[str, ...] = (
    "battery_soc_sensor",
    "battery_power_sensor",
    "battery_soc_entity",
    "battery_charge_energy_sensor",
    "battery_discharge_energy_sensor",
    "battery_energy_discharged_sensor",
    "battery_cycles_sensor",
    "battery_temperature_sensor",
    "battery_target_soc_entity",
    # (#923, ruflo) seeded by the config flow when it finds a battery-mode
    # select, and watched every cycle by the #845 BatteryModeWatch — a battery
    # SEM can watch but not yet drive is still a battery.
    "battery_operating_mode_entity",
    "battery_charge_power_limit_entity",
    "battery_discharge_control_entity",
    "battery_discharge_control_entities",
    "battery_force_discharge_control_entity",
    "battery_force_discharge_entities",
    "battery_strategy_control_entity",
    "battery_strategy_entities",
    # (#869) the charge/discharge direction select a direction_select
    # setpoint needs — wired, it is evidence of a battery like the rest.
    "battery_power_direction_entity",
    # An explicit platform is a choice; its default "auto" is not (see
    # _DEFAULT_VALUES below).
    "battery_charge_platform",
)
EV_WIRING_KEYS: tuple[str, ...] = (
    "ev_chargers",
    "ev_charging_power_sensor",
    "ev_power_sensor",
    # Legacy single-charger keys, still read by the coordinator.
    "ev_connected_sensor",
    "ev_plug_sensor",
    "ev_charging_sensor",
    "ev_current_sensor",
    "ev_energy_sensor",
    "ev_total_energy_sensor",
    "ev_daily_energy_sensor",
    "ev_session_energy_sensor",
    "ev_charger_service",
    "ev_start_service",
    "ev_stop_service",
    "ev_current_control_entity",
    "ev_start_stop_entity",
    "ev_charge_mode_entity",
    "ev_phase_switch_entity",
    "ev_departure_time_entity",
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
    "heat_pump_temperature_sensor",
)
HOT_WATER_WIRING_KEYS: tuple[str, ...] = (
    "hot_water_entity",
    "hot_water_power_sensor",
    "hot_water_energy_sensor",
    "hot_water_temperature_sensor",
)

# A wiring key holding its INSTALL DEFAULT says nothing: "auto" asks SEM to
# detect a battery platform, it does not declare that a battery exists.
_DEFAULT_VALUES: Mapping[str, tuple[str, ...]] = {
    "battery_charge_platform": ("auto",),
}

# (#996) The option keys a capability verdict reads. They are NOT reload
# keys (not in MODULE_EVIDENCE_KEYS): plant size and investment are sliders,
# and a reload per tweak is the #462 bug. A capability that turns PRESENT is
# caught by the coordinator's per-cycle growth check instead — one reload,
# only on the ABSENT → PRESENT edge. ``tariff_mode`` alone
# decides the dynamic tariff — a price entity without the mode drives
# nothing (the dynamic provider is built only when the mode says so).
# ``target_peak_limit`` is deliberately NOT a capability: the config flow
# saves its default for every install, so a value proves nothing (the
# battery_capacity_kwh lesson above).
CAPABILITY_KEYS: tuple[str, ...] = (
    "tariff_mode",
    "export_limit_entity",
    "dynamic_forecast_entity", "solar_forecast_source",
    "system_size_kwp",
    "system_investment_cost",
)

# Every key the oracle reads. Setting one through set_option must reload the
# entry, or the module's entities wait for the next restart — pinned by
# tests/test_923_structural_keys.py against _SET_OPTION_STRUCTURAL_KEYS.
MODULE_EVIDENCE_KEYS: frozenset[str] = frozenset(
    BATTERY_WIRING_KEYS + EV_WIRING_KEYS + HEAT_PUMP_WIRING_KEYS + HOT_WATER_WIRING_KEYS
)

_EMPTY: tuple[Any, ...] = (None, "", [], {}, ())


def _wired(config: Mapping[str, Any], keys: Iterable[str]) -> bool:
    for key in keys:
        value = config.get(key)
        if value in _EMPTY:
            continue
        # (#1089) A per-battery list with every slot empty (``[None, None]``,
        # what a click through Configure saves) wires nothing.
        if isinstance(value, (list, tuple)) and all(v in _EMPTY for v in value):
            continue
        if isinstance(value, str) and value.strip().lower() in _DEFAULT_VALUES.get(key, ()):
            continue
        return True
    return False


def _declared(ed_config: Any | None, attr: str) -> bool | None:
    """What the Energy Dashboard declares for ``attr`` — None when the
    object cannot say: an unexpected shape is not a "no" (#925)."""
    if ed_config is None:
        return False
    if isinstance(ed_config, Mapping):
        value = ed_config.get(attr)
    else:
        value = getattr(ed_config, attr, None)
    return value if isinstance(value, bool) else None


def has_managed_charger(config: Mapping[str, Any]) -> bool:
    """A charger SEM was TOLD about — the #595 rule for the EV tab and the
    welcome text's charge-mode line. Not the same question as "does this
    install have EV data": an Energy Dashboard EV consumer feeds
    ``sem_ev_power`` with no charger configured."""
    return bool(config.get("ev_chargers") or config.get("ev_charging_power_sensor"))


def _positive(value: Any) -> bool:
    """A number above zero — a plant size or an investment somebody typed."""
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _runtime_answer(runtime: Mapping[str, Any] | None, fact: str) -> bool | None:
    """What SEM found at runtime for ``fact``: True/False when it looked
    (a registry read), None when it has not asked or could not (#925)."""
    if not isinstance(runtime, Mapping):
        return None
    value = runtime.get(fact)
    return value if isinstance(value, bool) else None


def module_verdict(
    config: Mapping[str, Any],
    ed_config: Any | None,
    ed_answered: bool,
    runtime: Mapping[str, Any] | None = None,
) -> dict[Module, Presence]:
    """The module verdict for one install.

    (#996) ``runtime`` carries the two answers a capability can only get
    from the entity registry: ``solar_forecast`` (a forecast integration
    SEM found) and ``export_limit`` (an export-limit entity on the
    inverter). Each is True, False, or None for "not asked" — and None
    is UNKNOWN, never ABSENT, exactly like an unread Energy Dashboard.
    The three other capabilities read SEM's own options and are never
    UNKNOWN.

    ``ed_config`` is the parsed Energy Dashboard config (an
    ``EnergyDashboardConfig``) or None. ``ed_answered`` is whether the Energy
    Dashboard question got an answer at all — only the exact value ``True``
    counts as answered; anything else (a mock, a stray tuple) is "not
    answered", never guessed at. True means the preferences were parsed OR
    there are none — HA's energy manager holds none and no ``.storage/energy``
    exists (``read_energy_dashboard_config_outcome`` asks the manager first,
    because the file lags it by up to 60 s); anything else means the read
    failed or has not run yet.
    Battery and EV can be declared there, so for them no answer means
    UNKNOWN — and so does an ``ed_config`` whose shape can't say yes or no
    (#925: "I could not ask" is never "no"). Heat pump and hot water exist
    only in SEM's own options, which are always readable — they are never
    UNKNOWN.
    """
    answered = ed_answered is True
    battery_declared = _declared(ed_config, "has_battery")
    ev_declared = _declared(ed_config, "has_ev")

    def _config_or_dashboard(wired: bool, declared: bool | None) -> Presence:
        if wired or declared is True:
            return Presence.PRESENT
        if answered and declared is False:
            return Presence.ABSENT
        return Presence.UNKNOWN

    def _config_only(wired: bool) -> Presence:
        return Presence.PRESENT if wired else Presence.ABSENT

    def _config_or_runtime(wired: bool, found: bool | None) -> Presence:
        if wired or found is True:
            return Presence.PRESENT
        if found is False:
            return Presence.ABSENT
        return Presence.UNKNOWN

    tariff_mode = str(config.get("tariff_mode") or "static").strip().lower()

    return {
        Module.BATTERY: _config_or_dashboard(_wired(config, BATTERY_WIRING_KEYS), battery_declared),
        Module.EV: _config_or_dashboard(_wired(config, EV_WIRING_KEYS), ev_declared),
        Module.HEAT_PUMP: _config_only(_wired(config, HEAT_PUMP_WIRING_KEYS)),
        Module.HOT_WATER: _config_only(_wired(config, HOT_WATER_WIRING_KEYS)),
        Module.DYNAMIC_TARIFF: _config_only(tariff_mode == "dynamic"),
        Module.EXPORT_LIMIT: _config_or_runtime(
            _wired(config, ("export_limit_entity",)),
            _runtime_answer(runtime, "export_limit")),
        Module.SOLAR_FORECAST: _config_or_runtime(
            _wired(config, ("dynamic_forecast_entity",)),
            _runtime_answer(runtime, "solar_forecast")),
        Module.PV_SIZE: _config_only(_positive(config.get("system_size_kwp"))),
        Module.INVESTMENT: _config_only(_positive(config.get("system_investment_cost"))),
    }


_B = frozenset({Module.BATTERY})
_E = frozenset({Module.EV})
_BE = frozenset({Module.BATTERY, Module.EV})
_HP = frozenset({Module.HEAT_PUMP})
_HW = frozenset({Module.HOT_WATER})
# (#996) capabilities
_T = frozenset({Module.DYNAMIC_TARIFF})
_X = frozenset({Module.EXPORT_LIMIT})
_F = frozenset({Module.SOLAR_FORECAST})
_BF = frozenset({Module.BATTERY, Module.SOLAR_FORECAST})
_P = frozenset({Module.PV_SIZE})
_I = frozenset({Module.INVESTMENT})


def _rows(platform: str, modules: frozenset, keys: tuple[str, ...]) -> dict:
    return {(platform, key): modules for key in keys}


def _table(*groups: Mapping[tuple[str, str], frozenset]) -> dict:
    """Merge row groups; a (platform, key) defined twice is a bug, not an
    override."""
    table: dict = {}
    for group in groups:
        for row, modules in group.items():
            if row in table:
                raise ValueError(f"ENTITY_MODULES defines {row} twice")
            table[row] = modules
    return table


# (platform, description key) -> the modules that entity needs. A key that is
# not here is CORE and is always created. Cross-module entities list every
# module they need — battery→EV assist needs both. The dashboard generator
# and validate-sem.sh read this same table, rather than keeping their own
# copy of "does this install have a battery". The dynamic battery entities
# (``select.sem_battery_mode``, ``number.sem_battery_reserve_soc``) are not
# rows here — they follow the same verdict through ``select._has_battery``.
ENTITY_MODULES: Mapping[tuple[str, str], frozenset[Module]] = _table(
    _rows("sensor", _B, (
        "battery_capacity_drift_pct",
        "battery_charge_power", "battery_cycles_estimated",
        "battery_discharge_power",
        "battery_health_score", "battery_measured_capacity_kwh", "battery_power",
        "battery_priority_status", "battery_scheduler_deficit_kwh",
        "battery_scheduler_reason", "battery_scheduler_state",
        "battery_scheduler_target_soc", "battery_session_avg_power",
        "battery_session_cost", "battery_session_duration",
        "battery_session_energy", "battery_session_savings",
        "battery_session_solar_share", "battery_session_type", "battery_soc",
        "battery_status", "battery_stored_grid_share",
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
    _rows("number", _B, (
        "battery_morning_drain_floor_soc",   # arc #921 (#892): the pack's floor
        "battery_auto_start_soc", "battery_buffer_soc", "battery_capacity",
        "battery_max_discharge_power", "battery_priority_soc",
    )),
    _rows("switch", _B, (
        "battery_may_export",
        "battery_house_sink_enabled",   # arc #921 (#879)
    )),
    # (#996) Spending and pacing plan the battery against the forecast:
    # ``battery_spendable_kwh`` is the forecast budget, pacing runs only
    # while ``forecast_trust_d1`` exists. No forecast, no plan to switch on.
    _rows("switch", _BF, (
        "battery_charge_pacing_enabled", "forecast_spending_enabled",
    )),
    _rows("sensor", _BF, (
        "battery_charge_pacing", "battery_dynamic_floor_pct", "battery_spendable_kwh",
    )),
    _rows("binary_sensor", _B, (
        "battery_charging", "battery_discharging",
    )),
    _rows("button", _B, (
        "backfill_battery_nights",
    )),
    _rows("sensor", _BE, (
        "flow_battery_to_ev_energy", "flow_battery_to_ev_power",
        "lifetime_ev_battery_share",
    )),
    _rows("number", _BE, (
        "ev_morning_window_hours",           # arc #921 (#892): the pack AND the car
        "battery_assist_max_power", "battery_assist_min_surplus",
    )),
    _rows("switch", _BE, (
        "battery_may_assist_ev",
        "ev_morning_window_enabled",    # arc #921 (#892): the pack AND the car
    )),
    _rows("sensor", _E, (
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
    _rows("number", _E, (
        "ev_disable_delay_seconds", "ev_enable_delay_seconds",
    )),
    _rows("binary_sensor", _E, (
        "ev_charging", "ev_connected",
    )),
    # (#980) The shared pause duration. An install with no charger has
    # nothing to pause, so it should not carry the dropdown either. (The
    # per-charger Pause BUTTONS are built from the charger list itself, so
    # they cannot appear without one.)
    _rows("select", _E, (
        "pause_duration",
    )),
    _rows("sensor", _HP, (
        "heat_pump_energy_month", "heat_pump_energy_shifted_today",
        "heat_pump_energy_today", "heat_pump_energy_total", "heat_pump_energy_year",
        "heat_pump_mode", "heat_pump_registration_status",
        "heat_pump_sg_ready_state",
    )),
    _rows("number", _HP, (
        "heat_pump_boost_offset",
    )),
    _rows("binary_sensor", _HP, (
        "heat_pump_registered", "heat_pump_solar_boost",
    )),
    _rows("number", _HW, (
        "hot_water_solar_target",
        "legionella_interval_hours", "legionella_target_temp",
    )),
    # (#996) A dynamic tariff: the thresholds feed the dynamic provider
    # only; the next cheap window exists only when prices move.
    _rows("number", _T, (
        "cheap_price_threshold", "expensive_price_threshold",
    )),
    _rows("sensor", _T, (
        "tariff_next_cheap_start",
    )),
    # (#996) The export guard (#955) writes the inverter's export-limit
    # entity; without one its switches and holds change nothing.
    _rows("switch", _X, (
        "export_guard_enabled", "export_guard_override_external",
    )),
    _rows("number", _X, (
        "export_guard_engage_s", "export_guard_release_s",
    )),
    _rows("sensor", _X, (
        "export_guard_state",
    )),
    # (#996) Forecast rows. ``forecast_source`` and ``forecast_available``
    # stay: they are how "no forecast" is visible (CORE_BY_DECISION).
    _rows("sensor", _F, (
        "best_surplus_window", "forecast_corrected_today",
        "forecast_correction_factor", "forecast_dampening_factor",
        "forecast_history_days", "forecast_peak_power_today_w",
        "forecast_peak_time_today", "forecast_power_now_w",
        "forecast_remaining_today_kwh", "forecast_surplus_kwh",
        "forecast_today_kwh", "forecast_tomorrow_kwh", "forecast_trust_d1",
        "forecast_trust_d2", "pv_health", "pv_performance_vs_forecast",
    )),
    # (#996) kWh per kWp and the degradation trend divide by the plant
    # size; the analyzer's 10 kWp default is a made-up number.
    _rows("sensor", _P, (
        "pv_daily_specific_yield", "pv_degradation_trend",
        "pv_estimated_annual_degradation",
    )),
    # (#996) ROI divides by the investment; zero investment, no ROI.
    _rows("sensor", _I, (
        "roi_annual_savings", "roi_payback_years", "roi_percentage",
    )),
)

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
    # (#996) Every control chooses a side (tests/test_996_every_control_
    # has_a_need.py). These act on every install.
    ("number", "update_interval"): "how often SEM reads its inputs, on every install",
    ("select", "hints"): (
        "plain-word hints and a weekly note; they read what every install has, "
        "off by default"),
    ("number", "minimum_solar_power"): "the solar floor below which SEM counts no surplus",
    ("number", "surplus_event_threshold"): "the surplus event fires for user automations on every install",
    ("number", "electricity_import_rate"): "the flat import price — the tariff a static house has",
    ("number", "electricity_export_rate"): "the flat export price — every house that exports has one",
    ("number", "regulation_offset"): "the grid-balance offset SEM regulates every load to",
    ("number", "system_size_kwp"): "the input that makes the per-kWp rows exist — must stay to be set",
    ("number", "system_investment_cost"): "the input that makes the ROI rows exist — must stay to be set",
    ("number", "night_earliest_start"): "the night window bounds EV night charging and the battery plan",
    ("number", "night_latest_end"): "the night window bounds EV night charging and the battery plan",
    ("switch", "observer_mode"): "hands-off mode applies to every command SEM could send",
    ("switch", "vacation_mode"): "vacation lowers every target on every install",
    ("switch", "energy_plan_actuation"): "the night plan drives the EV as well as the battery",
    # (#996) Tell-tales: a flat tariff or a missing forecast stays visible.
    ("sensor", "forecast_source"): "says 'none' when there is no forecast — the tell-tale",
    ("binary_sensor", "forecast_available"): "off when there is no forecast — the tell-tale",
    ("sensor", "tariff_provider"): "says 'static' on a flat tariff — the tell-tale",
    ("binary_sensor", "tariff_is_dynamic"): "off on a flat tariff — the tell-tale",
    ("sensor", "tariff_price_level"): "reads 'no_prices' on a flat tariff (#994) — honest, not inert",
    ("sensor", "tariff_current_import_rate"): "the flat import rate is a real price",
    ("sensor", "tariff_current_export_rate"): "the flat export rate is a real price",
    ("sensor", "daily_grid_export_negative_kwh"): "a negative export rate can be static too (#871)",
    ("sensor", "daily_grid_export_negative_cost"): "a negative export rate can be static too (#871)",
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
    if isinstance(presence, Mapping) and presence and all(
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


def presence_from_summary(summary: Mapping[str, Any]) -> dict[Module, Presence]:
    """The inverse of ``presence_summary``, tolerant on purpose: a module or
    value this build does not know is ignored/UNKNOWN, never an error — the
    reader may be a different version than the install it reads."""
    presence = all_unknown()
    for key, value in summary.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        try:
            module = Module(key)
        except ValueError:
            continue
        try:
            presence[module] = Presence(value)
        except ValueError:
            continue
    return presence


# At most one module-driven reload per this many seconds, across reloads —
# a flickering detection must never become a reload loop.
MODULE_RELOAD_MIN_INTERVAL_S = 600.0


def modules_grown(
    at_setup: Mapping[Module, Presence], now: Mapping[Module, Presence],
) -> tuple[Module, ...]:
    """Modules that were ABSENT when the platforms were built and are PRESENT
    now — the only transition that needs new entities. ABSENT → UNKNOWN is a
    failed re-read, not hardware. PRESENT → ABSENT waits for the next
    restart or options change: removing a user's entities on a live re-read
    is exactly the false ABSENT this oracle exists to prevent."""
    return tuple(
        m for m in Module
        if at_setup.get(m) is Presence.ABSENT and now.get(m) is Presence.PRESENT
    )


def module_reload_due(
    at_setup: Mapping[Module, Presence],
    now: Mapping[Module, Presence],
    now_ts: float,
    last_reload_ts: float | None,
) -> tuple[Module, ...]:
    """The grown modules, if a reload may run now. Once per transition holds
    by construction — after the reload the new setup verdict is PRESENT. A
    growth refused by the interval is picked up by the next Energy Dashboard
    re-read, or at the next restart."""
    grown = modules_grown(at_setup, now)
    if not grown:
        return ()
    if last_reload_ts is not None and now_ts - last_reload_ts < MODULE_RELOAD_MIN_INTERVAL_S:
        return ()
    return grown
