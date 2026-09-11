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
