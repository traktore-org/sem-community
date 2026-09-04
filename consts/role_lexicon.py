"""#915 — what an integration's own vocabulary means, in SEM's terms.

This file is HAND-WRITTEN and is the judgement layer of the roster arc. The
crawler (``scripts/crawl_integration_roster.py``) supplies the corpus — every
``translation_key`` an integration declares in its own repository — and these
rules decide which of those keys is a role SEM can use.

**Why the rules match a translation key and never an entity_id.** A
``translation_key`` is the integration author's own semantic label for a
control: ``storage_maximum_discharging_power`` means that thing whatever the
user renamed the entity to, and in every language. An entity_id is the user's
rename. Matching the first is reading metadata Home Assistant already records;
matching the second is guessing — the distinction bug class 42 turns on
("does HA already record this as metadata?").

**What these rules may NOT decide.** A unit, a device class, or a sign
convention. Those are physical facts about one installation and are not
declared anywhere upstream; the crawl is structurally incapable of producing
them, which is what keeps the #530 door shut (web-research "support" is a
false-positive generator). A role proposed here is a candidate the local
entity registry must confirm and the user must accept — never a binding.

Adding a rule is a deliberate act: it widens what SEM will propose across
every mined brand at once. Prefer a ``not`` clause over a narrower ``any``
clause when excluding a near-miss, so the rule keeps reading as "this role,
except", which is the shape the next reader can extend.
"""

from __future__ import annotations

from typing import Any, Dict, Final

#: role -> matching rule. ``platform`` is the HA entity domain the role must
#: live in; ``any`` is a tuple of regexes of which one must match the declared
#: key; ``not`` disqualifies. Regexes are matched case-insensitively with
#: ``re.search`` against the translation key alone.
ROLE_RULES: Final[Dict[str, Dict[str, Any]]] = {
    # ── battery control ────────────────────────────────────────────────
    "battery_discharge_limit": {
        "platform": "number",
        "any": (r"max.*discharg.*power", r"discharg.*power.*(limit|max)",
                r"storage_maximum_discharging", r"discharge_power_limit"),
        # a current register is amperes: writing watts into it is the #749
        # bug this project already shipped once
        "not": (r"current", r"soc", r"percent", r"cutoff", r"voltage"),
    },
    "battery_charge_limit": {
        "platform": "number",
        "any": (r"max.*charg.*power", r"charg.*power.*(limit|max)",
                r"storage_maximum_charging", r"ac_charge_power"),
        "not": (r"discharg", r"current", r"soc", r"percent", r"voltage"),
    },
    "battery_target_soc": {
        "platform": "number",
        "any": (r"(target|charge|end).*soc", r"soc.*(limit|target)",
                r"minimum_soc", r"soc_cutoff", r"capacity_control"),
        "not": (r"power", r"current", r"voltage"),
    },
    "battery_strategy": {
        "platform": "select",
        "any": (r"working_mode", r"work_mode", r"operating_mode",
                r"operation_mode", r"battery_strategy", r"energy_pattern",
                r"ess_mode", r"power_strategy"),
        "not": (r"grid_code", r"phase"),
    },
    "battery_force_charge": {
        "platform": "switch",
        "any": (r"force.*charg", r"forcible.*charg", r"quick_charge",
                r"ac_charge(_enable)?$"),
        "not": (r"discharg",),
    },
    # ── EV charger control ────────────────────────────────────────────
    "ev_current_control": {
        "platform": "number",
        # Zaptec calls it ``charger_max_current`` and ``available_current``;
        # OCPP calls it ``maximum_current``. The ``min`` and ``phase``
        # exclusions matter: a minimum-current floor and Zaptec's
        # 1↔3-phase switch register are both currents and neither is the
        # control SEM writes (#804 learned the second one the hard way).
        "any": (r"charg(er|ing|e)?_(max_)?current", r"^maximum_current$",
                r"current_limit", r"^available_current$"),
        "not": (r"phase", r"offline", r"failsafe", r"voltage", r"power",
                r"\bmin\b", r"_min_", r"minimum"),
    },
    "ev_charge_mode": {
        "platform": "select",
        "any": (r"^ev_charg(e|ing)_mode", r"charger_mode",
                r"^charg(e|ing)_mode$"),
        "not": (r"battery", r"ctrl", r"inverter", r"output", r"^ac_", r"^dc_"),
    },
    # ── read-side specs (they widen _SPEC_REGISTRY_KEYS, nothing else) ─
    "battery_capacity_spec": {
        "platform": "sensor",
        "any": (r"(rated|usable|nominal|total).*capacity",
                r"capacity.*(rated|nominal)", r"^battery_capacity$"),
        "not": (r"remaining", r"percent", r"today", r"state_of"),
    },
    "system_size_spec": {
        "platform": "sensor",
        "any": (r"^(rated|nominal|maximum)_(active_)?power$", r"rated_power"),
        "not": (r"battery", r"today"),
    },
}

#: READ roles — the three sensors SEM cannot run without, and the SOC.
#: These identify WHICH entity plays a role, never which way it counts: a sign
#: convention is a fact about one installation and SEM already auto-detects it
#: (``sensor_reader``). A read guess the user confirms costs a wrong number on
#: a screen; that is the side of bug class 42 where guessing is allowed.
READ_ROLE_RULES: Final[Dict[str, Dict[str, Any]]] = {
    "solar_power": {
        "platform": "sensor",
        "any": (r"^(pv|solar|input)_power$", r"^power_pv", r"pv_active_power",
                r"^solar_generation", r"^inverter_input_power$"),
        "not": (r"total", r"today", r"daily", r"yesterday", r"month",
                r"forecast", r"string", r"pv\d", r"mppt"),
    },
    "grid_power": {
        "platform": "sensor",
        "any": (r"^grid_(active_)?power$", r"^power_meter_active_power$",
                r"grid_exchange", r"^meter_active_power$", r"^grid_net_power$"),
        "not": (r"today", r"daily", r"total", r"phase", r"l1", r"l2", r"l3",
                r"import_energy", r"export_energy"),
    },
    "battery_power": {
        "platform": "sensor",
        "any": (r"^battery_(active_)?power$", r"^storage_.*charge_discharge_power$",
                r"^battery_charge_discharge_power$"),
        "not": (r"today", r"daily", r"total", r"soc", r"percent"),
    },
    "battery_soc": {
        "platform": "sensor",
        "any": (r"^(battery_)?state_of_(capacity|charge)$", r"^battery_soc$",
                r"^storage_state_of_capacity$"),
        "not": (r"target", r"limit", r"min", r"max", r"12v"),
    },
}

#: Vehicle roles. SEM never controls a car — it charges *towards* the car's
#: state (``vehicle_soc_entity`` / ``vehicle_range_entity``), so a car
#: integration's vocabulary is worth reading even though nothing is written.
VEHICLE_ROLE_RULES: Final[Dict[str, Dict[str, Any]]] = {
    "vehicle_soc": {
        "platform": "sensor",
        # NOT bare ``battery_level``: every phone, sensor and pet feeder
        # declares one. A car says state-of-charge or ev-battery.
        "any": (r"state_of_charge", r"^soc$", r"^ev_battery_level$",
                r"^ev_soc", r"charge_state_of"),
        "not": (r"target", r"limit", r"12v", r"aux", r"minimum", r"profile"),
    },
    "vehicle_range": {
        "platform": "sensor",
        "any": (r"(ev_)?range$", r"remaining_range", r"electric_range",
                r"range_(electric|total)"),
        "not": (r"fuel", r"gas"),
    },
}

#: An integration earns the right to contribute ANY role only if its declared
#: vocabulary contains at least one of these. It is the two-signal rule from
#: ``_census_energy_shaped()`` applied to a repository instead of a registry:
#: a lone ``battery_level`` is a laptop, a pet feeder or a door sensor — the
#: first pass of this crawler put all three in the roster. An energy anchor is
#: a key no non-energy device declares.
ENERGY_ANCHORS: Final[tuple] = (
    "solar", "pv_", "_pv", "photovolt", "inverter", "grid_", "_grid",
    "battery_power", "battery_charge", "battery_discharge", "charge_power",
    "discharge_power", "state_of_charge", "_soc", "soc_", "import_energy",
    "export_energy", "feed_in", "self_consumption", "wallbox", "charging_power",
    "battery_system", "battery_strategy", "p1_", "modbus_state",
)

#: A CAR, identified only by vocabulary no house has. Weak markers (``door``,
#: ``gear``, ``trip``, ``window``) put a Bosch smart-home controller and a pet
#: feeder in the vehicle bucket, so they are deliberately absent.
VEHICLE_MARKERS: Final[tuple] = (
    "odometer", "mileage", "vin_", "ignition", "parking_brake", "combustion",
    "adblue", "engine_", "tyre_pressure", "tire_pressure", "fuel_level",
)

#: Not an energy system, whatever else it declares.
APPLIANCE_MARKERS: Final[tuple] = (
    "feeder", "litter", "vacuum", "mower", "washer", "dryer", "dishwasher",
    "oven", "kettle", "humidifier", "purifier", "camera", "cadence",
    "pedal", "ebike", "printer", "cpu_", "ram_", "disk_", "toothbrush",
)

#: role -> the TOP-LEVEL SEM option key it fills. A role listed here can be
#: accepted with one click: the Config card writes this key through
#: ``set_option``, which is the same path its own pickers use. A role absent
#: from this map cannot be written that way and must say so instead of
#: showing a button that would put an entity in the wrong place.
SEM_CONFIG_KEY_FOR_ROLE: Final[Dict[str, str]] = {
    "battery_discharge_limit": "battery_discharge_control_entity",
    "battery_charge_limit": "battery_charge_power_limit_entity",
    "battery_target_soc": "battery_target_soc_entity",
    "battery_strategy": "battery_strategy_control_entity",
    "battery_force_charge": "battery_force_charge_switch",
    # the read side — SensorReader's own key names (#915: writing the
    # dashboard-shaped names instead read 0 W from a live inverter)
    "solar_power": "solar_production_sensor",
    "grid_power": "grid_power_sensor",
    "battery_power": "battery_power_sensor",
    "battery_soc": "battery_soc_sensor",
}

#: Roles that live INSIDE a charger's own config, not at the top level.
#: Offering a one-click accept for these would write a charger's entity into
#: an install-wide key, so they are reported with a pointer to the EV
#: chargers section instead of a button.
PER_CHARGER_ROLES: Final[frozenset] = frozenset({
    "ev_current_control", "ev_charge_mode",
})

#: Roles SEM already resolves by itself every time it looks
#: (``config_flow._spec_from_registry`` reads these by translation key).
#: Nothing to confirm — showing them as proposals would invent a chore.
AUTO_RESOLVED_ROLES: Final[frozenset] = frozenset({
    "battery_capacity_spec", "system_size_spec",
})

#: Platforms whose entity names are chosen by the USER, not the integration
#: author. A declared-key match is meaningless there — the official ``modbus``
#: integration names entities from the user's own YAML (#869 Anker), and
#: everything on ``mqtt`` is one transport carrying many brands (#887 OnStar).
#: The shape prober is their path; the roster must never carry them.
OPAQUE_PLATFORMS: Final[frozenset] = frozenset({
    "modbus", "mqtt", "esphome", "template", "sql", "rest", "command_line",
    "knx", "tasmota", "shell_command", "input_number", "input_select",
})


#: Every rule set the crawler may apply, by kind.
ALL_RULE_SETS: Final[tuple] = ("ROLE_RULES", "READ_ROLE_RULES",
                               "VEHICLE_ROLE_RULES")


def role_for(platform: str, key: str) -> str | None:
    """The SEM role a declared ``translation_key`` on ``platform`` plays, or
    ``None``. First matching rule wins; rules are ordered by specificity in
    ``ROLE_RULES`` above."""
    import re
    for role, rule in {**ROLE_RULES, **READ_ROLE_RULES}.items():
        if rule["platform"] != platform:
            continue
        if any(re.search(p, key, re.I) for p in rule.get("not", ())):
            continue
        if any(re.search(p, key, re.I) for p in rule["any"]):
            return role
    return None
