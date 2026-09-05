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
        # ``soc`` must be a whole SEGMENT. Unanchored, it matched SENEC's
        # ``sockets_1_upper_limit`` and ``sockets_1_time_limit`` — the
        # letters s-o-c inside "sockets" — and offered a switchable wall
        # socket's schedule as the battery's charge target.
        "any": (r"(target|charge|end).*(?:^|_)soc(?:_|$)",
                r"(?:^|_)soc(?:_|$).*(limit|target)",
                r"capacity_control"),
        # (#810, @Azlinon on real EG4 hardware) A declared key is not
        # automatically a key SEM may WRITE. He named three that look like a
        # target SOC and are not: ``system_charge_soc_limit`` is the global
        # ceiling for the battery bank ("recommended 101 for EG4 batteries",
        # not a per-cycle target), ``soc_cutoff`` belongs to the on/off-grid
        # transition, and ``ac_couple_end_soc`` configures an AC-coupled
        # grid-tie inverter. Proposing any of them behind a one-click button
        # would hand a user a register the vendor says to leave alone.
        "not": (r"power", r"current", r"voltage", r"^system_", r"cutoff",
                r"couple", r"backup", r"global", r"off_?grid", r"eps",
                # a smart-load threshold decides when a SECOND load runs,
                # not how full the pack should be
                r"smart_load", r"generator", r"grid_peak",
                # A protection FLOOR is not a target, and confusing the two
                # is not a near miss — it inverts the knob. Write "charge to
                # 80" into "never discharge below" and the pack stops
                # discharging at 80 %, which is the opposite of the request.
                # Growatt, Sigen, Solis, Sungrow and Sunsynk each declare
                # both halves under names one word apart.
                r"(?:^|_)(min|minimum|lower)", r"discharg",
                # `charge_state_*` is Tesla's VEHICLE API namespace: the
                # Fleet/Tessie/Teslemetry integrations speak for the car AND
                # the Powerwall through one vocabulary, and
                # `charge_state_charge_limit_soc` is how full the CAR should
                # be (bug class 68 wearing a house's clothes).
                r"^charge_state_"),
    },
    "battery_strategy": {
        "platform": "select",
        "any": (r"working_mode", r"work_mode", r"operating_mode",
                r"operation_mode", r"battery_strategy", r"energy_pattern",
                r"ess_mode", r"power_strategy"),
        # Viessmann's ``dhw_operating_mode`` is domestic hot water: a heat
        # pump's operating mode reads exactly like a battery's and drives
        # something else entirely.
        "not": (r"grid_code", r"phase", r"dhw", r"water", r"heating",
                r"room", r"circuit", r"holiday", r"comfort", r"ventilat"),
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
        # A CHARGER's current control, and nothing else that happens to be a
        # current. Written as known control names plus an EV/charger context
        # rather than as "anything with current in it", because the loose
        # form matched an INVERTER's AC input limits — Victron's
        # ``ac1_input_current_limit`` and ``remote_panel_current_limit`` were
        # being offered as an EV charger control (found sweeping the open
        # hardware requests, #809). A battery's ``charge_current`` is the
        # same trap from the other side.
        "any": (r"^charger_(max_)?current$", r"^charge_current_limit$",
                r"^charging_current_(set|limit|max)$", r"ac_charger_.*current",
                r"^(ev|evse)_.*current", r"ev.?charg.*current",
                r"^maximum_current$", r"^available_current$",
                r"^current_set$", r"^set_current$", r"^current_setpoint$"),
        "not": (r"phase", r"offline", r"failsafe", r"voltage", r"power",
                r"\bmin\b", r"_min_", r"minimum", r"energy",
                r"input", r"^ac\d", r"aes", r"remote_panel", r"bulk",
                r"absorption", r"grid"),
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
        # ``rated_power`` unanchored is inside "solar_gene|rated_power" —
        # SENEC's live production sensor was being offered as the system's
        # nameplate size. Same class as the "sockets"/"soc" collision above.
        "any": (r"^(rated|nominal|maximum)_(active_)?power$",
                r"(?:^|_)rated_power"),
        # Huawei declares ``charger_rated_power`` beside
        # ``inverter_rated_power``: the optional EV charger's nameplate, not
        # the system's. Picked first by sort order, it would have reported a
        # 7 kW house on a 10 kW inverter.
        "not": (r"battery", r"today", r"generated", r"charger"),
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
    # Some brands never publish a combined grid sensor — they publish the
    # two directions as separate positive magnitudes, which is why SEM
    # carries IMPORT_PATTERNS / EXPORT_PATTERNS and a split-pair reader at
    # all (pattern E, Growatt). Those lists are entity-id guesses; these are
    # the same question asked of the integration's own declared names.
    # Anker's official integration is the case in hand (#869): it declares
    # ``grid_import_power`` and ``grid_export_power`` and no combined one.
    "grid_import_power": {
        "platform": "sensor",
        "any": (r"^grid_import_power$", r"^import_from_grid", r"^import_power$",
                r"^grid_imported_power$", r"^from_grid_power$",
                r"^consumption_from_grid", r"^pac_to_user"),
        "not": (r"energy", r"today", r"daily", r"total", r"month", r"year",
                r"cumulative", r"phase", r"l1", r"l2", r"l3"),
    },
    "grid_export_power": {
        "platform": "sensor",
        "any": (r"^grid_export_power$", r"^export_to_grid", r"^export_power$",
                r"^grid_exported_power$", r"^to_grid_power$", r"^pac_to_grid"),
        "not": (r"energy", r"today", r"daily", r"total", r"month", r"year",
                r"cumulative", r"phase", r"l1", r"l2", r"l3", r"limit"),
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
        # ``added_range`` is what THIS session put in, not what the car has
        # left — a charger's odometer, not its fuel gauge. SEM asks the
        # second question and would read the first as an almost-empty car.
        "not": (r"fuel", r"gas", r"added", r"session", r"charged"),
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
#: What says "this box charges a CAR" rather than "this box runs a house".
#: The distinction matters because both declare ``state_of_charge`` and
#: ``battery_power``, and on a charger those belong to the vehicle — feeding
#: them into SEM's house reads would corrupt the energy balance every cycle.
CHARGER_MARKERS: Final[tuple] = (
    "evse", "charge_point", "chargepoint", "charging_cable", "cable_",
    "connector_", "charging_session", "session_energy", "rfid", "authoriz",
    "charger_max_current", "available_current", "charge_current_limit",
)

#: …and what says the same box ALSO runs the house, so it is not merely a
#: charger. Anker Solix declares ``max_evcharge_current`` next to a real PV
#: input and a real pack: it is a generator with a socket, not a wallbox.
GENERATOR_MARKERS: Final[tuple] = (
    "pv_power", "solar_power", "input_power", "inverter", "photovolt",
    "storage_", "grid_active_power", "meter_active_power",
)

APPLIANCE_MARKERS: Final[tuple] = (
    "feeder", "litter", "vacuum", "mower", "washer", "dryer", "dishwasher",
    "oven", "kettle", "humidifier", "purifier", "camera", "cadence",
    "pedal", "ebike", "printer", "cpu_", "ram_", "disk_", "toothbrush",
    # A fitness watch charges from the SUN and reports a battery — two
    # genuine energy anchors on a device that is not energy hardware
    # (Garmin declares `solar` and `battery_charge` beside `avg_spo2` and
    # `bedtime`). The health vocabulary is what tells them apart.
    # NOT a bare "sleep_": Ohme's `sleep_when_inactive` and Enphase's
    # `ac_battery_sleep_mode` are power states, not sleep tracking.
    "spo2", "heart_rate", "calories", "bedtime", "stress",
    "steps", "fitness", "badges", "workout",
    # …and a lighting/media cloud: `hdmi`, scenes, light zones
    "hdmi", "light_zone", "dreamview", "scene_select", "lightbar",
    # A UPS is a battery that is not a HOME battery: its `input_power` is
    # the mains feed, and reading it as solar would have told SEM the sun
    # shines out of a wall socket (Network UPS Tools, 23568 installs).
    # …and NOT "ups_": Victron's VE.Bus declares `ups_function`, which is a
    # real inverter's real setting.
    "battery_runtime",
    # NOTHING ELSE GOES IN THIS TUPLE WITHOUT BEING RUN AGAINST THE ROSTER
    # FIRST. Every marker here is a substring of a real vocabulary, and the
    # obvious ones are wrong: `brightness` matched the LED on Zaptec, Peblar,
    # SMA's EV charger and Anker; `load_percent` matched Growatt's
    # `storage_load_percentage`; `cloud_cover` and `precip` matched Sunsynk's
    # own solar FORECAST sensors. Each of those silently deleted a working
    # brand's roles. A marker must be a word only a non-energy device says.
)

#: A battery role needs a BATTERY in the vocabulary. Midea's air conditioners
#: are "inverter" units and declare `work_mode`; Qvantum's heat pump declares
#: `operation_mode`. Read as a battery strategy those are nonsense, and no
#: key-level pattern can tell them apart — `work_mode` is `work_mode`. The
#: context is what differs: neither integration mentions a battery anywhere.
BATTERY_CONTEXT: Final[tuple] = (
    "battery", "state_of_charge", "_soc", "soc_", "storage_", "ess_",
    "_ess", "accu", "pack_",
)

#: What only a BUILDING says. No car declares a grid connection, a PV input,
#: an MPPT tracker or an AC input — so a vocabulary carrying these is energy
#: hardware however much it also knows about a vehicle. Victron's GX declares
#: `ev_odometer` for the car plugged into it, one key out of 465, and that
#: single word reclassified the whole system controller as "a vehicle" —
#: throwing away 464 keys of inverter and battery vocabulary.
HOUSE_MARKERS: Final[tuple] = (
    # NOT "ac_input"/"ac_output": to an air conditioner, AC is the appliance
    # (Midea's cloud integration claimed the house on it).
    "grid_", "pv_", "photovolt", "inverter", "mppt", "_grid_", "solar_yield",
)

#: The anchors strong enough to admit a NAME-ONLY row — one that mined a
#: vocabulary, passed the anchor test, but matched no SEM role. Deliberately
#: narrower than ENERGY_ANCHORS and written as prefixes: the loose `_grid`
#: matched a Formula 1 integration's starting grid, and `_soc` matched a
#: lighting cloud. Bug class 67 from the other side.
STRONG_ENERGY_ANCHORS: Final[tuple] = (
    "solar", "photovolt", "pv_power", "inverter", "grid_", "evse",
    "wallbox", "charging_power", "state_of_charge", "battery_power",
    "battery_charge_", "battery_discharge", "session_energy",
    "charge_current", "export_power", "import_power", "feed_in",
)

#: …and the shape of an ELECTRICAL measurement. A brand that declares two of
#: these alongside a strong anchor is reporting watts, amps or kilowatt-hours,
#: which no watch and no light strip does.
import re as _re
UNIT_SHAPED_KEY: Final = _re.compile(
    r"(^|_)(w|kw|kwh|wh|a|v|hz)$|_(power|current|voltage|energy)(_|$)"
    r"|^(power|current|voltage|energy)_", _re.I)

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
    # the split pair — SEM's own manual override keys, treated as explicit
    # intent by the reader (no sign autocorrect), which is exactly what a
    # confirmed proposal is
    "grid_import_power": "grid_import_power_entity",
    "grid_export_power": "grid_export_power_entity",
}

#: Roles that only mean anything TOGETHER. A brand that declares one half of
#: the split grid pair and not the other is describing something else — a
#: single-direction meter reading, a load. SEM's own split reader audits the
#: pair for exclusivity (#661); the roster refuses to propose half of it.
PAIRED_ROLES: Final[tuple] = (("grid_import_power", "grid_export_power"),)

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
    # (#915) A TRANSPORT, like the rest of this list: what a HomeKit device
    # is called is the accessory's business, so a key match under it would
    # be pure guessing. 79831 installs, and every one of them a different
    # vocabulary.
    "homekit_controller", "homekit",
    # Tuya is a MARKETPLACE, not a device: one vocabulary covering inverters,
    # IP cameras, kettles and cat litter boxes. Its `work_mode` keys were
    # offered as a battery strategy — `cat_litter_box_work_mode` among them.
    "tuya", "xtend_tuya", "localtuya",
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
