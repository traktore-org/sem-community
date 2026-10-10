"""EV charger detection for SEM Solar Energy Management.

This module provides detection of EV charger control entities. Solar, grid, and
battery sensors are now read from the HA Energy Dashboard (HA 2025.12+).

EV charger sensors are still detected here because the Energy Dashboard only
provides power/energy sensors, not the control entities needed for:
- Checking if a car is connected (binary_sensor.*_plug_connected)
- Checking if charging is active (binary_sensor.*_charging)
- Controlling charging current (number.*_charging_current, service calls)

Detection is integration-aware:
1. **Integration-Aware Detection**: Recognizes entity naming conventions from
   KEBA, Easee, Wallbox, go-eCharger, OpenWB, Zaptec, ChargePoint, Heidelberg, etc.

2. **Priority-Based Matching**: Each pattern has a priority score (1-10):
   - 10: Integration-specific patterns (highest accuracy)
   - 8-9: Well-known manufacturer patterns
   - 3-5: Common generic patterns

"""
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry

from .consts.devices import (
    REBOOT_DEVICE_CLASS, names_a_charge_pause, names_a_reboot)
from .utils.select_option import pick_listed
from .utils.switch_sense import charge_pause_twin, integration_name

_LOGGER = logging.getLogger(__name__)

# EV charger integration-specific patterns
# (#1032) EV_INTEGRATION_PATTERNS — the glob matrix behind the config
# wizard's second prefill — is retired: the wizard reads ONE crawler (the
# roster and its roles). A field the roles cannot fill is left for the user.

# The three sensors every charger needs. (#990) The config flow reads this
# too: a home with no charger cannot fill them, so its pages must not
# require them.
EV_REQUIRED_SENSORS = (
    "ev_connected_sensor",
    "ev_charging_sensor",
    "ev_charging_power_sensor",
)


class EVChargerDetector:
    """(#1032) The config wizard's VALIDATOR for EV charger entities. Its
    glob-pattern detection is retired: suggestions come from one crawler
    (``discover_ev_charger_from_registry``), never from a second reader."""

    def __init__(self, hass: HomeAssistant):
        """Initialize EV charger detector."""
        self.hass = hass
        self._entity_registry = entity_registry.async_get(hass)

    def get_all_entities(self) -> List[str]:
        """Get all available entity IDs."""
        return list(self.hass.states.async_entity_ids())

    def _validate_entity(self, entity_id: str, sensor_type: str) -> bool:
        """Validate entity exists and has reasonable values."""
        state = self.hass.states.get(entity_id)
        if not state:
            return False

        if state.state in ("unknown", "unavailable", "None"):
            return False

        try:
            if sensor_type == "ev_charging_power":
                value = float(state.state)
                return -20000 <= value <= 20000

            elif sensor_type in ["ev_connected", "ev_charging"]:
                # (#1038) Ask the word list the reader uses (status_enum.py).
                # This check kept its own copy, which drifted: it had Ohme's
                # label "plugged in", never the state ``plugged_in`` HA
                # stores, and refused the sensor. "0"/"1" are a binary status
                # sent as a number; any other number (a voltage, a counter)
                # is not taken for a plug.
                from .coordinator.charger_adapters.status_enum import (
                    knows_status,
                )
                if knows_status(state.state) or state.state in ("0", "1"):
                    return True
                options = (getattr(state, "attributes", None) or {}).get(
                    "options")
                return _options_answer_both_ways(options, sensor_type)

            else:
                return True

        except (ValueError, TypeError):
            return False

    def validate_ev_configuration(self, config: Dict[str, str]) -> Dict[str, str]:
        """Validate EV charger configuration.

        Returns:
            Dict with validation errors (empty if all valid)
        """
        errors = {}

        for sensor_key in EV_REQUIRED_SENSORS:
            entity_id = config.get(sensor_key)
            if not entity_id:
                errors[sensor_key] = "Required sensor not configured"
                continue

            sensor_type = sensor_key.replace("_sensor", "")
            if not self._validate_entity(entity_id, sensor_type):
                errors[sensor_key] = f"Entity {entity_id} not found or invalid"

        return errors

# Backward compatibility alias
HardwareDetector = EVChargerDetector


def _options_answer_both_ways(options, sensor_type: str) -> bool:
    """(#1038) An ENUM sensor whose listed options let the reader answer yes
    AND no for this role is one SEM can read, whatever state it is in at
    setup (booting, a fault). One known word is not enough: Blue Current's
    ``vehicle_status`` lists ``ready``, but SEM cannot read its other states
    as plugged or not."""
    from .coordinator.charger_adapters.status_enum import (
        classify_charger_status,
        is_cable_present,
    )
    if not isinstance(options, (list, tuple)):
        return False
    if sensor_type == "ev_connected":
        return {True, False} <= {is_cable_present(o) for o in options}
    classes = {classify_charger_status(o) for o in options}
    return "charging" in classes and bool(classes & {"not_charging", "locked"})


# ============================================================
# Entity-registry-based EV charger discovery
# ============================================================
# Queries the entity registry for entities belonging to supported
# EV charger integrations and maps them to config keys.


def _online_current_control(offline_eid: str, entities) -> Optional[str]:
    """(#886) The ONLINE twin of an offline current-limit register, among the
    same device's ``number.*`` entities. Prefer the exact twin (``offline`` →
    ``online`` in the id), then any number naming ``online`` and not
    ``offline``. Returns None when the device exposes no live counterpart."""
    numbers = [str(e.entity_id) for e in entities
               if str(e.entity_id).startswith("number.")]
    twin = offline_eid.replace("offline", "online")
    if twin != offline_eid and twin in numbers:
        return twin
    for eid in numbers:
        low = eid.lower()
        if "online" in low and "offline" not in low:
            return eid
    return None


#: (#962, bug class 89) Object-id SEGMENTS that make a sensor a CAPABILITY the
#: charger ADVERTISES — a nameplate, an offer, a limit somebody set — rather
#: than a measurement of what the car is drawing. OCPP's ``Power.Offered`` is
#: the live case: it sits at the box's maximum the whole time nothing is
#: plugged in. Matched as whole SEGMENTS, never substrings (class 67):
#: "rated" also lives inside ``solar_generated_power``. English-only, which
#: is a known gap, not a claim: a German ``nennleistung`` is one word and no
#: segment rule can see it. That gap fails OPEN — see the no-swap rule below.
_CAPABILITY_SEGMENTS = frozenset({
    "offered", "offer", "limit", "limits", "max", "maximum", "maximal",
    "maximale", "rated", "nominal", "capacity", "available", "setpoint",
    "target", "allowed",
})

#: The wrong QUANTITY for a charger read role. A charger draws energy in —
#: OCPP fixes that by spec (``Import``), and ``Export`` is the V2G direction
#: flowing back out. ``reactive`` power is not charging power at all.
_WRONG_QUANTITY_SEGMENTS = frozenset({"export", "exported", "reactive"})

#: (#1034) A reading of ANOTHER circuit the box meters with its own clamps —
#: the house, the solar array, the home battery, the grid — not of the car.
#: The V2C Trydan publishes ``house_power``, ``photovoltaic_power`` (key
#: ``fv_power``: "fotovoltaica") and ``battery_power`` beside
#: ``charge_power``, all ``device_class: power``.
_OTHER_CIRCUIT_SEGMENTS = frozenset({
    "photovoltaic", "pv", "fv", "solar", "house", "home", "household",
    "grid", "mains", "utility", "evu", "battery", "akku", "ess", "inverter",
    "shaper",
})

#: (#1034) Words that name the CAR's side of the box. Among replacements
#: of equal rank, one that says it is about the charge wins over the
#: alphabet.
_CAR_SEGMENTS = frozenset({"charge", "charging", "ev", "car", "vehicle"})

#: (#1034) The words that make a current number one END of a range the
#: owner sets, not the set-point SEM writes every cycle.
_RANGE_FLOOR_SEGMENTS = frozenset({"min", "minimum", "minimal"})
_RANGE_CEILING_SEGMENTS = frozenset({"max", "maximum", "maximal"})

#: One LEG of a polyphase reading, never the charger's draw. Excluded from
#: the replacement search outright: a third of the truth is not a fallback
#: for the truth, and openWB, Alfen, Zaptec, go-e and KEBA all publish these
#: beside the total.
_PHASE_SEGMENTS = frozenset({"l1", "l2", "l3", "phase1", "phase2", "phase3"})

#: Which accumulation window each energy role asks for. An OCPP
#: ``…Interval`` is a metering-interval delta — neither a lifetime register
#: nor a session total, so it contradicts both.
_TOTAL_WINDOW = frozenset({"register", "total", "lifetime", "cumulative"})
_SESSION_WINDOW = frozenset({"session"})
_INTERVAL_WINDOW = frozenset({"interval"})

#: The read roles that are picked out of a measurand FAMILY.
_MEASURAND_ROLES = (
    "ev_charging_power_sensor",
    "ev_total_energy_sensor",
    "ev_session_energy_sensor",
)

#: Units grouped by what they measure, so a replacement can be required to
#: be COMMENSURABLE with what it replaces. An integration that omits
#: ``device_class`` (Zaptec's custom builds do) still publishes a unit, and
#: without this check the search happily swaps a power reading for a status
#: string from the same device.
_UNIT_FAMILY = {
    "w": "power", "kw": "power", "mw": "power", "va": "power", "kva": "power",
    "wh": "energy", "kwh": "energy", "mwh": "energy",
    "a": "current", "ma": "current",
    "v": "voltage",
}


def _id_segments(entity_id: str) -> frozenset:
    """The object-id's underscore-separated segments, lowercased.

    A rule written over SUBSTRINGS silently claims the brands that happen to
    own the letters (class 67): ``rated`` is the tail of
    ``solar_generated_power``, ``max`` the head of ``maximum``. Segments are
    what an entity id is actually made of, so that is what the rules read.
    """
    obj = entity_id.split(".", 1)[1] if "." in entity_id else entity_id
    return frozenset(str(obj).lower().split("_"))


def _measures_the_quantity(entity_id: str) -> bool:
    """(#962) Does this entity id claim to MEASURE, or only to advertise?

    False for a capability the box publishes about itself and for the wrong
    direction/quantity. Deliberately about the NAME only — the registry's
    ``device_class`` cannot tell ``Power.Offered`` from ``Power.Active.Import``
    (both are ``power``), which is exactly how the class survives.
    """
    segs = _id_segments(entity_id)
    return not (segs & _CAPABILITY_SEGMENTS) and not (segs & _WRONG_QUANTITY_SEGMENTS)


def _is_phase_leg(entity_id: str) -> bool:
    """One leg of a polyphase reading (``…_power_l2``, ``…_phase_3_power``).

    (#1035) The number must FOLLOW the word: ``phase_3`` is one leg, while
    ``3_phase_power`` is the sum of all three."""
    segs = _id_segments(entity_id)
    if segs & _PHASE_SEGMENTS:
        return True
    tokens = _name_tokens(entity_id)
    return any(word == "phase" and nxt in ("1", "2", "3")
               for word, nxt in zip(tokens, tokens[1:], strict=False))


def _without_phase(entity_id: str) -> tuple:
    """(#1035) An id with its phase taken out, and any "total" or "sum": the
    name the sum of the legs goes by. ``sensor.box_power_phase_3`` and
    ``sensor.box_power`` give the same answer; ``sensor.box_grid_power``
    does not."""
    tokens = [t for t in _name_tokens(entity_id) if t]
    out: List[str] = []
    skip = False
    for word, nxt in zip(tokens, tokens[1:] + [""], strict=True):
        if skip:
            skip = False
            continue
        if word == "phase" and nxt in ("1", "2", "3"):
            skip = True
            continue
        if word in _PHASE_SEGMENTS or word in ("total", "sum"):
            continue
        out.append(word)
    return (entity_id.split(".", 1)[0], *out)


def _own_words(entry, own: Dict[str, str]) -> List[str]:
    """(#1034) The words of an entity's own name — never the device name in
    front of it (class 115)."""
    eid = str(getattr(entry, "entity_id", "") or "")
    name = own.get(eid) or _object_id(eid)
    return [w for w in name.lower().split("_") if w]


def _key_words(entry) -> List[str]:
    """(#1034) The words of the integration's translation key. The key is
    the same in every language and survives an id its owner renamed: a
    German V2C's solar power is ``…_photovoltaik_leistung``, its key is
    still ``fv_power``."""
    key = getattr(entry, "translation_key", None)
    if not isinstance(key, str):
        return []
    return [w for w in key.lower().split("_") if w]


def _pauses_the_charge(entry) -> bool:
    """(#1042) A switch that pauses the CHARGE — and nothing else: V2C's
    "Pause dynamic control modulation" pauses the box's solar modulation.

    Read on the name the run time reads it by (``integration_name``: the
    translation key, the same in every language, then the integration's
    own name). A switch bound on any other name would be driven as
    on-while-charging — the bug."""
    return names_a_charge_pause(integration_name(entry))


def _what_it_is(entities) -> Dict[str, List[str]]:
    """(#1034) The words of each entity's own name, for reading WHAT it is:
    a minimum, the house, the car.

    ``_own_names`` keeps the device name where it must: on a transport,
    where it is the only mark of the brand, and on a small unit with one
    id renamed. To read what an entity is, those words are still the
    device's ("Min JuiceBox" is Swedish for "my JuiceBox"; "Home EVSE" is
    not the house). So where ``_own_names`` took nothing off, the LEADING
    words more than half of the unit's ids share come off here — in front
    only, so ``…_min_current`` keeps its "min". Three ids at least: on
    fewer, half is one id. One word always stays."""
    own = _own_names(entities)
    rows: Dict[str, List[str]] = {}
    whole = True
    for e in entities:
        eid = str(getattr(e, "entity_id", "") or "")
        rows[eid] = _own_words(e, own)
        whole = whole and rows[eid] == [
            w for w in _object_id(eid).lower().split("_") if w]
    prefix: List[str] = []
    while whole and len(rows) >= 3:
        at = len(prefix)
        counts: Dict[str, int] = {}
        for t in rows.values():
            if len(t) > at + 1 and t[:at] == prefix:
                counts[t[at]] = counts.get(t[at], 0) + 1
        if not counts:
            break
        word, carried = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
        if carried * 2 <= len(rows):
            break
        prefix.append(word)
    return {eid: t[len(prefix):] if (prefix and t[:len(prefix)] == prefix
                                     and len(t) > len(prefix)) else t
            for eid, t in rows.items()}


def _names_another_circuit(entry, words: Dict[str, List[str]]) -> bool:
    """(#1034) Is this reading about the house, the solar array, the home
    battery or the grid — a circuit the box meters beside the car?
    ``words`` is ``_what_it_is``: never the device name."""
    eid = str(getattr(entry, "entity_id", "") or "")
    found = set(words.get(eid, ())) | set(_key_words(entry))
    return bool(found & _OTHER_CIRCUIT_SEGMENTS)


def _device_words(rows: List[List[str]]) -> List[str]:
    """(#1035) The leading words of a unit's ids that name its DEVICE.

    A word joins when every id of the unit carries it at that place — or,
    on a unit of eight or more ids, all but a quarter of them, so one id
    its owner renamed (``sensor.ev_power``) does not stop the device's name
    being seen on the rest. A real charger publishes 15 to 40 entities; a
    small unit must agree in full, because there a word several entities
    start with (``charging_power``, ``charging_current``) is more likely
    their own than the device's."""
    words: List[str] = []
    while True:
        at = len(words)
        counts: Dict[str, int] = {}
        for t in rows:
            if len(t) > at and t[:at] == words:
                counts[t[at]] = counts.get(t[at], 0) + 1
        if not counts:
            return words
        word, carried = max(counts.items(), key=lambda kv: kv[1])
        if carried < len(rows) and (len(rows) < 8
                                    or carried * 4 < len(rows) * 3):
            return words
        words.append(word)


def _own_names(entities) -> Dict[str, str]:
    """(#1035) Each entity's OWN name: its object id without the device name
    in front of it.

    Home Assistant builds an entity id from the device name and the entity's
    name, so a word in the device name is in every id of that device. A
    brand rule that tests a word against the whole id therefore matches
    every entity of the device, and registry order picks among them. The
    Peblar's default device name is "Peblar EV Charger": "charge" was in
    ``switch.peblar_ev_charger_force_single_phase``, and SEM bound that
    switch to start and stop the charge.

    The device name is ``_device_words``. An id that does not carry it (its
    owner renamed it) keeps its whole name. An id that is the device name
    alone, or that plus Home Assistant's ``_2`` for a second box of the
    same name, is the device's main entity: its own name IS the device
    name, so it keeps it — GARO's start/stop is ``switch.garo_laddbox``.
    Nothing is removed for one entity alone, which shares with nobody, nor
    on a transport (mqtt, modbus, …), where the device name is the only
    mark of the brand, nor for a ``_WholeIds`` unit.

    Each value starts with ``_``, so a hint that carries its own boundary
    (``"_state"``) still matches the first word of the entity's own name.
    """
    tokens: Dict[str, List[str]] = {}
    platforms = set()
    for e in entities:
        eid = str(getattr(e, "entity_id", "") or "")
        if eid:
            tokens[eid] = _name_tokens(eid)
            platforms.add(str(getattr(e, "platform", "") or ""))
    device: List[str] = []
    if (len(tokens) > 1 and not platforms & _TRANSPORT_PLATFORMS
            and not isinstance(entities, _WholeIds)):
        device = _device_words(list(tokens.values()))
    out: Dict[str, str] = {}
    for eid, t in tokens.items():
        rest = t[len(device):] if device and t[:len(device)] == device else t
        if not rest or (len(rest) == 1 and rest[0].isdigit()):
            rest = t
        out[eid] = "_" + "_".join(rest)
    return out


class _WholeIds(list):
    """(#1035) A unit whose brand rules read the WHOLE entity id, device name
    included: the rule SEM used before #1035. ``_discover_unit`` asks it one
    thing only — see there."""


def _discover_unit(discover_fn, entities) -> Dict[str, str]:
    """(#1035) A brand function's answer for one unit.

    The brand rules read each entity's own name (``_own_names``). A word
    that only the device name holds tells no entity apart, so a control or
    a status it alone named is not bound: that pick was registry order.

    Two roles left empty by the own names keep the answer the whole id
    gives, unless another role already holds that entity:

    * a measurand READ role (power, total and session energy), for the
      reason bug class 89 swaps and never drops: a charger with no power
      reading is worse than one whose reading the device name picked, and
      the guards that run next still swap a capability or a single phase
      for the measurement;
    * the current control, when Home Assistant itself says what it is: the
      unit's only ``number`` of ``device_class: current``. Entity ids are
      built in the install's language — a German Peblar's limit is
      ``number.peblar_ev_charger_ladestrombegrenzung`` — so the device
      name was the only English word on it, and with no rival nothing was
      left to registry order (the review of this fix).

    The fallback only fills a charger the own names found: a unit that only
    its device name made a charger (a Zaptec installation its owner called
    "Carport Charger") stays out.
    """
    result = discover_fn(entities)
    if not result:
        return result
    roles = [r for r in _MEASURAND_ROLES if not result.get(r)]
    if not result.get("ev_current_control_entity"):
        roles.append("ev_current_control_entity")
    if not roles:
        return result
    whole = discover_fn(_WholeIds(entities)) or {}
    for role in roles:
        eid = whole.get(role)
        if not eid or eid in result.values():
            continue
        if role == "ev_current_control_entity" and not _the_current_number(
                eid, entities):
            continue
        result[role] = eid
    return result


def _the_current_number(eid: str, entities) -> bool:
    """Is ``eid`` the unit's one ``number`` of ``device_class: current``?"""
    numbers = [str(e.entity_id) for e in entities
               if str(e.entity_id).startswith("number.")
               and getattr(e, "original_device_class", None) == "current"]
    return numbers == [str(eid)]


def _unit_family(entry) -> Optional[str]:
    """What a registry entry's unit MEASURES — ``power``, ``energy``, … —
    or None when it publishes no unit SEM recognises."""
    unit = (getattr(entry, "original_unit_of_measurement", None)
            or getattr(entry, "unit_of_measurement", None))
    if unit is None:
        return None
    return _UNIT_FAMILY.get(str(unit).strip().lower())


def _rank_measurand(entity_id: str, role: str) -> tuple:
    """A STABLE order over one measurand family — lower is better.

    The whole bug is that registry ordering decided; every pick made here is
    therefore a function of the entity id alone, so the same install answers
    the same way whatever order its entities were created in. The WINDOW
    terms outweigh the direction term: a lifetime register in the session
    slot is a different mistake from the one this guard exists to fix, and
    must not be traded for a nicer-looking direction.
    """
    segs = _id_segments(entity_id)
    if role == "ev_total_energy_sensor":
        want, against = _TOTAL_WINDOW, _SESSION_WINDOW | _INTERVAL_WINDOW
    elif role == "ev_session_energy_sensor":
        want, against = _SESSION_WINDOW, _TOTAL_WINDOW | _INTERVAL_WINDOW
    else:
        want, against = frozenset(), frozenset()
    rank = 0
    if want and not (segs & want):
        rank += 4
    if against and (segs & against):
        rank += 4
    if "import" not in segs:
        rank += 1          # the direction a charger draws in, when named
    return (rank, entity_id)


def _measured_twin(bound_eid: str, entities, role: str, bound_entry,
                   taken=(), sum_of: Optional[str] = None) -> Optional[str]:
    """The sibling of ``bound_eid`` that measures what ``role`` asks about.

    Same device, same domain, same ``device_class`` AND the same unit
    FAMILY — commensurable with what it replaces, so the search cannot hand
    back a status string from a brand that omits device classes. Polyphase
    legs and entities already holding another role are excluded outright,
    and the winner is chosen by ``_rank_measurand`` rather than by whoever
    the loop happened to see last.

    ``sum_of`` (#1035) narrows the search to the sum of that phase leg —
    the sibling named like it without the phase. A device can publish its
    grid, solar or battery power beside the charger's; one phase of the
    charge is closer to the truth than any of those.

    (#1034) A reading of another circuit — house, solar, battery, grid — is
    never the replacement either.
    """
    want_dc = getattr(bound_entry, "original_device_class", None)
    want_unit = _unit_family(bound_entry)
    if want_dc is None and want_unit is None:
        # Nothing identifies the family. A swap here would be a guess of its
        # own — exactly the move that put us in #962.
        return None
    own = _own_names(entities)
    words = _what_it_is(entities)
    candidates = []
    car: Dict[str, bool] = {}
    for e in entities:
        eid = str(e.entity_id)
        if eid == bound_eid or eid in taken or not eid.startswith("sensor."):
            continue
        if getattr(e, "original_device_class", None) != want_dc:
            continue
        if _unit_family(e) != want_unit:
            continue
        if not _measures_the_quantity(eid) or _is_phase_leg(own.get(eid, eid)):
            continue
        if _names_another_circuit(e, words):
            continue
        if sum_of is not None and _without_phase(eid) != _without_phase(sum_of):
            continue
        candidates.append(eid)
        car[eid] = bool((set(words.get(eid, ())) | set(_key_words(e)))
                        & _CAR_SEGMENTS)
    if not candidates:
        return None
    return min(candidates, key=lambda c: (
        _rank_measurand(c, role)[0], not car[c], c))


def _reject_capability_sensor(result: Dict[str, str], entities) -> None:
    """(#962, bug class 89) Never read a charger's ADVERTISED capability as
    its measurement.

    An integration that names its sensors after protocol measurands publishes
    a whole family under one ``device_class``: OCPP's single device carries
    ``Power.Active.Import``, ``Power.Offered``, ``Power.Active.Export`` and
    ``Power.Reactive.Import`` all as ``device_class: power``. Every brand
    matcher binds the charging-power role on that device class alone and
    takes the first/last one it sees, so registry ORDER decided — and on
    @bgthb's Huawei SCharger 22-KT (#962) it decided ``power_offered``: the
    box's 22 kW nameplate, reported continuously with no car plugged in. SEM
    then infers a connection "from physics" (``sensor_reader``), so an empty
    charger reads as a charging car forever.

    SWAP ONLY, never drop. Removing the role looks like the fail-closed
    move and is not one in this tree: a charger with no power entity is
    still registered (``coordinator._retry_ev_device_setup`` gates on the
    service, not the sensor), KEBA's adapter decides ``actual_charging``
    from power alone so it would read "never charging", the 18-cycle
    ``ev_power < 50`` rule would anchor its SoC at 100 %, and in a
    multi-charger install the missing per-charger key falls back to the
    FLEET sum (class 3). So when the family offers no measured sibling the
    pre-#962 binding stands, and a name SEM merely finds suspicious can
    never cost a user their charger.

    (#1035) ONE PHASE of the reading is swapped too, but only for the sum
    of the legs. A matcher that keeps the last power sensor it sees took
    Peblar's ``…_power_phase_3`` over ``…_power``, so SEM saw a third of a
    three-phase charge. Whether a sensor is one phase is read from its own
    name, never from the device name in front of it.

    (#1034) ANOTHER CIRCUIT is swapped too. A box with its own clamps
    meters the house, the solar array or the home battery beside the car,
    all as ``device_class: power``: the V2C Trydan's rule kept the last one,
    ``…_photovoltaic_power``, so SEM would read the solar output as the
    car's charge. Read from the own name and the translation key, so the
    device name ("Solar Carport") never makes the charge look like one.

    Brand-agnostic on purpose: every read matcher, hand-written or hinted,
    funnels through the discovery choke point, so the class cannot recur
    unnoticed in the next brand.
    """
    by_id = {str(e.entity_id): e for e in entities}
    own = _own_names(entities)
    words = _what_it_is(entities)
    for role in _MEASURAND_ROLES:
        eid = result.get(role)
        if not eid:
            continue
        eid = str(eid)
        entry = by_id.get(eid)
        if entry is None:
            # Not a member of the family we were handed — nothing to reason
            # about, and a blind swap would be a guess of its own.
            continue
        measures = _measures_the_quantity(eid)
        circuit = _names_another_circuit(entry, words)
        one_phase = _is_phase_leg(own.get(eid, eid))
        if measures and not circuit and not one_phase:
            continue
        taken = {str(v) for k, v in result.items()
                 if k in _MEASURAND_ROLES and k != role}
        # one phase alone is swapped only for the sum of the legs
        sum_of = eid if measures and not circuit else None
        twin = _measured_twin(eid, entities, role, entry, taken=taken,
                              sum_of=sum_of)
        if twin:
            result[role] = twin


def _reject_offline_current_control(result: Dict[str, str], entities) -> None:
    """(#886, bug class 56) An ``*_offline_*`` current limit is a
    disconnected-mode FALLBACK — the register the charger honours only when it
    has lost its server — not the live surface SEM drives every cycle
    (Azlinon's JuiceBox: ``number.juicebox_max_current_offline_wanted`` was
    bound where the ONLINE twin belongs). ``ev_current_control_entity`` is an
    ACTUATION path, so a wrong bind is not a stale-read guess: SEM would write
    frequent current updates to a limited-write register that must not receive
    them. Never bind offline — swap to the online twin, else DROP the binding
    (monitor-only beats driving the wrong knob; the actuation-path rule of
    class 42). Brand-agnostic on purpose: every current matcher, hand-written
    or hinted, funnels through the discovery choke point, so the class cannot
    recur unnoticed in the next brand."""
    eid = result.get("ev_current_control_entity")
    if not eid or "offline" not in str(eid).lower():
        return
    online = _online_current_control(str(eid), entities)
    if online:
        result["ev_current_control_entity"] = online
    else:
        result.pop("ev_current_control_entity", None)


def _range_twins(bound, entities,
                 words: Dict[str, List[str]]) -> Tuple[set, set]:
    """(#1034) The numbers named like ``bound`` but for its min/max word,
    as (set-points, ceilings): ``…_intensity`` and ``…_max_intensity`` for
    ``…_min_intensity``. Compared only on the side that holds the word:
    the own name (``_what_it_is``) or the translation key, which holds in
    every language. Same device class and unit family.
    """
    ends = _RANGE_FLOOR_SEGMENTS | _RANGE_CEILING_SEGMENTS
    sides = []
    if set(words.get(str(bound.entity_id), ())) & ends:
        sides.append(lambda e: words.get(str(e.entity_id), []))
    if set(_key_words(bound)) & ends:
        sides.append(_key_words)
    want_dc = getattr(bound, "original_device_class", None)
    want_unit = _unit_family(bound)
    bound_eid = str(bound.entity_id)
    numbers = [e for e in entities
               if str(e.entity_id) != bound_eid
               and str(e.entity_id).startswith("number.")
               and getattr(e, "original_device_class", None) == want_dc
               and _unit_family(e) == want_unit]
    set_points: set = set()
    ceilings: set = set()
    for words_of in sides:
        base = [w for w in words_of(bound) if w not in ends]
        if not base:
            continue
        for e in numbers:
            these = words_of(e)
            if [w for w in these if w not in ends] != base:
                continue
            hit = set(these) & ends
            if not hit:
                set_points.add(str(e.entity_id))
            elif not hit & _RANGE_FLOOR_SEGMENTS:
                ceilings.add(str(e.entity_id))
    return set_points, ceilings


def _reject_range_end_current_control(result: Dict[str, str],
                                      entities) -> None:
    """(#1034, bug class 56) A ``min`` or ``max`` current is one END of the
    range the owner sets, not the set-point SEM writes every cycle.

    The V2C Trydan publishes three current numbers: ``intensity`` (the
    set-point), ``min_intensity`` and ``max_intensity``. Its rule kept the
    last one, so registry order bound the floor: every SEM write would move
    the floor and leave the charge where it was.

    A range end swaps to its one set-point twin. Without one, a ceiling
    STAYS — on Alfen, Wallbox, Zaptec and OCPP the "max current" number is
    the only one, and it is the control — and a floor goes to its ceiling
    twin, so the order of the two never decides. A floor with neither is
    DROPPED: monitor-only beats driving the wrong knob, the rule the
    offline register follows. Two set-points are a choice this guard does
    not make. The words are read from the own name and the translation
    key, never from the device name.
    """
    eid = result.get("ev_current_control_entity")
    if not eid:
        return
    entry = next((e for e in entities if str(e.entity_id) == str(eid)), None)
    if entry is None:
        return
    words = _what_it_is(entities)
    found = set(words.get(str(eid), ())) | set(_key_words(entry))
    floor = bool(found & _RANGE_FLOOR_SEGMENTS)
    if not floor and not found & _RANGE_CEILING_SEGMENTS:
        return
    set_points, ceilings = _range_twins(entry, entities, words)
    if len(set_points) == 1:
        result["ev_current_control_entity"] = set_points.pop()
        return
    if not floor:
        return
    if not set_points and len(ceilings) == 1:
        result["ev_current_control_entity"] = ceilings.pop()
        return
    _LOGGER.info(
        "discovery: %s is a minimum, not the current set-point, and no "
        "set-point was found — not adopting it as the control (#1034)", eid)
    result.pop("ev_current_control_entity", None)


#: (#804) The roles SEM COMMANDS. A reboot entity in any of them is a
#: power-cycle wearing a control's name.
_CONTROL_ROLES = (
    "ev_start_stop_entity",
    "ev_charge_mode_entity",
    "ev_current_control_entity",
    "ev_phase_switch_entity",
)


def _reject_reboot_control(result: Dict[str, str], entities=None) -> None:
    """(#804) Drop a device-RESTART entity from any control role.

    @HorizonKane's Wattpilot published ``button.…_neustart`` and the brand
    row's "start" hint matched the letters inside it, so SEM adopted the
    reboot button as the charger's start/stop control: every enable
    rebooted the box, and the stop that rides the current write was
    skipped below the number's 6 A minimum. The word rule lives here, at
    the choke point every registry path funnels through, so it holds for
    the hand-written brands and the generic prober too — not only for the
    row whose hint was wrong.

    HA's own ``restart`` device class is asked first: it says the same
    thing in every language, which a word list can never do — "Neu
    starten", "Starta om" and "Start på nytt" all begin a word with
    "start" and would otherwise pass.
    """
    classes = {str(getattr(e, "entity_id", "")):
               getattr(e, "original_device_class", None)
               for e in (entities or [])}
    for role in _CONTROL_ROLES:
        eid = result.get(role)
        if eid and names_a_reboot(eid, classes.get(eid)):
            _LOGGER.info(
                "discovery: %s names a device restart — not adopting it as "
                "%s (#804)", eid, role)
            result.pop(role, None)


def apply_charger_discovery_guards(result: Dict[str, str], entities) -> None:
    """Every brand-agnostic correction a freshly discovered charger config
    gets, at the one place all four REGISTRY discovery paths funnel through —
    the config path, the diagnostics report, the generic prober and the
    near-miss offer. A guard added here closes its class for every brand,
    hinted or hand-written, and for the next one nobody has written yet.

    (#1032) The glob matrix that was a fifth path is retired; the wizard's
    prefill comes from these paths only."""
    _reject_offline_current_control(result, entities)
    _reject_range_end_current_control(result, entities)
    _reject_capability_sensor(result, entities)
    _reject_reboot_control(result, entities)


#: (#1036) The roles only a charger fills: a car that is there, a charge
#: that runs, a session, or a way to steer the box. A meter fills none of
#: them — it measures power and energy, nothing else.
_CHARGER_ONLY_ROLES = (
    "ev_connected_sensor", "ev_charging_sensor", "ev_session_energy_sensor",
    "ev_current_control_entity", "ev_start_stop_entity",
    "ev_charge_mode_entity",
)


def meters_beside_chargers(platform: str, units, disabled=()) -> set:
    """(#1036) The units of ONE integration that are meters next to its
    charger — never chargers themselves.

    A brand function admits a unit on a power reading alone, so a meter the
    integration ships beside its charger became a second charger. Easee's
    Equalizer measures the house's grid import: SEM offered it as a charger
    with that import as its charging power — and, because its entities came
    first, as the PRIMARY charger that setup saves and drives.

    A unit is a meter here when its guarded mapping binds no role in
    ``_CHARGER_ONLY_ROLES``, AND a sibling unit of the same integration does
    bind one. The sibling is the evidence: the integration publishes those
    roles for its chargers, and this unit has none of them. Without that
    sibling nothing is dropped — a box whose status sensor the user disabled
    must not lose its only charger to a guess. Only a bound role makes a
    unit the evidence.

    Two things keep a unit that the roles alone would call a meter, each
    looked for on the WHOLE device — its live entities and its disabled ones
    (``disabled``: the platform's disabled registry entries):

    * a charger mark (a plug binary or a current control, #814);
    * an entity with the same translation key as one the evidence bound to
      a charger role. The key is the integration's own name for the entity
      and survives the user renaming its id, which the brand functions read.
      A second Easee with its status disabled, or renamed to
      ``sensor.carport_toestand``, is still a charger.

    That second check needs the keys. Where the evidence's charger roles
    carry none, nothing is dropped: SEM cannot tell a meter from a second
    box whose roles are switched off, and the heal at setup acts on this
    answer.

    ``mqtt`` and the other transports are not integrations: the devices on
    them are not neighbours.

    ``units`` is ``{unit_key: (mapping, entities)}`` with each mapping
    already through ``apply_charger_discovery_guards``. Returns the keys of
    the units that are meters.
    """
    if platform in _TRANSPORT_PLATFORMS:
        return set()

    def _binds_charger_role(mapping) -> bool:
        return any(mapping.get(role) for role in _CHARGER_ONLY_ROLES)

    evidence = [(mapping, ents) for mapping, ents in units.values()
                if mapping and _binds_charger_role(mapping)]
    if not evidence:
        return set()
    charger_keys = set()
    for mapping, ents in evidence:
        by_id = {str(e.entity_id): e for e in ents}
        for role in _CHARGER_ONLY_ROLES:
            bound = by_id.get(str(mapping.get(role) or ""))
            key = getattr(bound, "translation_key", None)
            if isinstance(key, str) and key:
                charger_keys.add(key)
    if not charger_keys:
        return set()

    def _whole_device(ents) -> list:
        devices = {e.device_id for e in ents if getattr(e, "device_id", None)}
        return list(ents) + [d for d in disabled
                             if getattr(d, "device_id", None) in devices]

    meters = set()
    for key, (mapping, ents) in units.items():
        if not mapping or _binds_charger_role(mapping):
            continue
        whole = _whole_device(ents)
        if any(_charger_mark(e) for e in whole):
            continue
        if any(getattr(e, "translation_key", None) in charger_keys
               for e in whole):
            continue
        meters.add(key)
    return meters


# ============================================================
# (#964) One physical unit, one bucket — the grouping every registry
# discovery path shares. ``device_id`` is the registry's own answer and
# is OPTIONAL; using it as the whole key makes "no device" an identity,
# and every device-less box of a platform lands in the same bucket.
# ============================================================

def _object_id(entity_id: str) -> str:
    return entity_id.split(".", 1)[1] if "." in entity_id else entity_id


def _entity_id_prefix(entity_id: str, tokens: int = 2) -> str:
    """The first ``tokens`` object-id tokens — ``sensor.keba_p30_power`` → ``keba_p30``.

    A NAME, not an identity: it is one of the axes ``group_entities_by_unit``
    tries, and a split it proposes is only ever adopted with evidence.
    """
    return "_".join(_object_id(entity_id).split("_")[:tokens])


def _entity_id_through_number(entity_id: str) -> str:
    """The name up to and including its first purely numeric token —
    ``sensor.garage_2_charging_power`` → ``garage_2``, and ``garage``'s own
    ``sensor.garage_charging_power`` → ``garage``. When Home Assistant
    disambiguates a second box by its DEVICE name rather than by suffixing
    each entity, the digit sits in the middle of the id, where neither a
    prefix of fixed width nor the trailing-``_<n>`` axis can see it."""
    tokens = _name_tokens(entity_id)
    for i, token in enumerate(tokens):
        if token.isdigit():
            return "_".join(tokens[:i + 1])
    return tokens[0] if tokens else ""


def _entity_id_suffix(entity_id: str) -> str:
    """Home Assistant's OWN disambiguator for a second identically named box:
    a trailing ``_<n>`` (``sensor.juicebox_power_2``). The one axis a prefix
    cannot see, and the only thing that separates two boxes on one config
    entry that their owner named the same."""
    last = _object_id(entity_id).split("_")[-1]
    return last if last.isdigit() else ""


def _charger_mark(entity) -> Optional[str]:
    """The two entities only a CHARGER has, by domain + device class: the
    plug binary that says a car is there, and the current control that
    steers it (#814's rule). Never a name."""
    eid = str(getattr(entity, "entity_id", "") or "")
    dom = eid.split(".", 1)[0]
    dc = getattr(entity, "original_device_class", None)
    if dom == "binary_sensor" and dc == "plug":
        return "plug"
    if dom == "number" and dc == "current":
        return "current"
    return None


def _shows_charger_shape(entities, require_plug: bool = False) -> bool:
    """Does this group of entities describe a charger ON ITS OWN?

    The same structural rule ``probe_charger_candidates`` admits a candidate
    by (#814): a power READING plus one of the two marks only a charger has
    — a plug binary or a current control. A power sensor alone is a smart
    plug, a toaster, or a site total; a plug binary alone is half a box.

    ``require_plug`` narrows that to the plug binary alone, and the grouping
    below turns it on wherever the platform publishes ANY plug — because a
    current control is not unique to a box within one box. Three per-phase
    ``number.*_current`` legs beside three per-phase power sensors each pass
    the loose rule, so a name axis "found" three chargers in one wallbox and
    shed the single plug they share (the review of this fix). A plug binary
    is what a phase leg, a site total and a sub-meter never have.

    Used by the grouping to answer one question and no other: did a name
    axis find a second BOX, or only a second naming convention?
    """
    has_power = False
    marks = set()
    for e in entities:
        eid = str(getattr(e, "entity_id", "") or "")
        dom = eid.split(".", 1)[0]
        dc = getattr(e, "original_device_class", None)
        if dom == "sensor" and dc == "power":
            has_power = True
            continue
        mark = _charger_mark(e)
        if mark:
            marks.add(mark)
    if not has_power:
        return False
    return "plug" in marks if require_plug else bool(marks)


def _is_ha_numbering(names) -> bool:
    """Do these names look like Home Assistant numbering a SECOND box?

    HA keeps the first box's name and appends ``_2`` — so every numbered
    name here must be an unnumbered name of this same set plus its number,
    and the numbers start at 2. ``garage`` beside ``garage_2`` passes.
    Numbered SUB-STRUCTURE does not: three legs named ``wb_garage_phase_1``
    …``_3`` have nothing in the set they were numbered from (the review of
    this fix split a three-phase wallbox into three chargers that way), and
    a set that is numbered all the way down never had a first box.
    """
    names = set(names)
    numbered = [n for n in names if n.split("_")[-1].isdigit()]
    if not numbered or len(numbered) == len(names):
        return False
    for name in numbered:
        tokens = name.split("_")
        if int(tokens[-1]) < 2 or "_".join(tokens[:-1]) not in names:
            return False
    return not any(t.isdigit() for n in names if n not in numbered
                   for t in n.split("_"))


#: The name axes tried on a device-less platform, FINEST FIRST — with the
#: extra evidence an axis needs before it may be adopted at all, and whether
#: it can land COARSER than the two-token prefix the prober floors on. Each
#: is paired with the config entry first (a box is one entry) and then
#: without it (one box can span several: a rig's template helpers are one
#: entry per entity). Nothing here is an identity — the evidence rules are
#: what turn an axis into a boundary.
_UNIT_NAME_AXES = (
    (lambda eid: _entity_id_prefix(eid, 3), None, False),
    (lambda eid: _entity_id_prefix(eid, 2), None, False),
    (lambda eid: _entity_id_prefix(eid, 1), None, True),
    (_entity_id_through_number, _is_ha_numbering, True),
    (lambda eid: "#_" + _entity_id_suffix(eid) if _entity_id_suffix(eid)
     else "#", _is_ha_numbering, False),
)


def _name_tokens(entity_id: str) -> List[str]:
    return _object_id(entity_id).split("_")


def _shared_leading_tokens(a: List[str], b: List[str]) -> int:
    shared = 0
    # strict=False is the point: the shorter name ends the comparison.
    for left, right in zip(a, b, strict=False):
        if left != right:
            break
        shared += 1
    return shared


def _attach_leftovers(shaped: Dict[Any, List[Any]],
                      leftovers: List[List[Any]]) -> List[List[Any]]:
    """Give an unshaped group back to the box it belongs to.

    "Shows no charger shape" is not the same as "belongs to no box": two
    boxes can shatter the SAME way at the very axis that separated them.
    Two KEBAs named Garage and Carport publish ``<box>_charging_power`` and
    ``<box>_charging_current`` under one name and ``<box>_plug_connected``
    under another — the split is real and evidenced twice over, yet
    dropping everything it left behind costs BOTH owners their plug binary,
    and with it the ``keba.set_current`` target. So a leftover joins the
    shaped group whose entity ids it shares the most leading name tokens
    with, and only where exactly one group is closest. A leftover equally
    close to both boxes is what "belongs to neither" actually looks like —
    openWB's ``openwb_global_*`` site totals sit one token from every
    loadpoint — and it stays out: returned as unplaced, for the caller to
    judge and for ``build_detection_report`` to list as ``unattributed``.
    """
    tokens: Dict[str, List[str]] = {}

    def _tok(entity) -> List[str]:
        eid = str(getattr(entity, "entity_id", "") or "")
        if eid not in tokens:
            tokens[eid] = _name_tokens(eid)
        return tokens[eid]

    unplaced: List[List[Any]] = []
    for group in leftovers:
        # A group that shows the charger shape on its own is a BOX this axis
        # could not place, not a spare part of somebody else's: attaching it
        # by name distance merged a plugless third wallbox into its neighbour
        # (the review of this fix). It goes back unplaced, and the mark it
        # carries then refuses the axis.
        if _shows_charger_shape(group):
            unplaced.append(group)
            continue
        closest, best, tied = None, 0, False
        for key, members in shaped.items():
            score = max(_shared_leading_tokens(_tok(left), _tok(member))
                        for left in group for member in members)
            if score > best:
                closest, best, tied = key, score, False
            elif score == best and best > 0 and key != closest:
                tied = True
        if closest is not None and not tied:
            shaped[closest].extend(group)
        else:
            unplaced.append(group)
    return unplaced


def _split_deviceless(platform: str, plat_entities: List[Any],
                      unproven_split: str) -> Dict[Any, List[Any]]:
    """The device-less half of ``group_entities_by_unit`` — see its docstring."""
    def _keyed(name_of, with_entry: bool) -> Dict[Any, List[Any]]:
        out: Dict[Any, List[Any]] = {}
        for e in plat_entities:
            cid = getattr(e, "config_entry_id", None)
            # A registry entry carries a str or None; anything else (a test
            # double's auto-attribute) is not an identity to split on.
            cid = cid if (with_entry and isinstance(cid, str)) else ""
            out.setdefault(
                ("unit", platform, cid, name_of(str(e.entity_id))), []
            ).append(e)
        return out

    # Which mark makes a group a BOX here. A current control is not unique
    # to a box WITHIN one box — per-phase legs carry one each — so wherever
    # this platform publishes any plug binary at all, that is the mark, and
    # a group without one is a phase, a total or a sub-meter. A platform
    # that publishes none (a JuiceBox over plain MQTT) keeps the loose rule,
    # which is the only mark it has left.
    require_plug = any(_charger_mark(e) == "plug" for e in plat_entities)

    def _floor(groups: Dict[Any, List[Any]]) -> Dict[Any, List[Any]]:
        """The prober's partition is never COARSER than the two-token prefix
        it has split on since #814 — a one-token axis, or the terminal merge,
        is wider than that, and merging a rig's template platform is what
        offered a garage door as a charger's start/stop. Applied only to
        those: an axis already finer than the prefix (three tokens, or HA's
        own numbering) must not be re-cut by it, which would shatter a box
        the axis had just separated correctly."""
        if unproven_split != "prefix":
            return groups
        refined: Dict[Any, List[Any]] = {}
        for key, members in groups.items():
            for e in members:
                refined.setdefault(
                    key + (_entity_id_prefix(str(e.entity_id), 2),), []
                ).append(e)
        return refined

    for with_entry in (True, False):
        for name_of, accepts, coarse in _UNIT_NAME_AXES:
            groups = _keyed(name_of, with_entry)
            if accepts is not None and not accepts([k[3] for k in groups]):
                continue
            shaped = {k: v for k, v in groups.items()
                      if _shows_charger_shape(v, require_plug)}
            # TWO boxes or none: a split that finds ONE box is not separating
            # anything, it is only shedding the entities it left behind.
            if len(shaped) >= 2:
                unplaced = _attach_leftovers(
                    shaped,
                    [g for k, g in groups.items() if k not in shaped])
                # A mark left over belongs to a box this axis cut through —
                # it is the plug or the control of one of them, and no box
                # may be steered by a cut. Refuse the axis, try the next.
                if any(_charger_mark(e) for g in unplaced for e in g):
                    continue
                return _floor(shaped) if coarse else shaped
    return _floor({("unit", platform, "", ""): list(plat_entities)})


def group_entities_by_unit(entities, *,
                           unproven_split: str = "merge") -> Dict[Any, List[Any]]:
    """Partition registry entries into the PHYSICAL units they describe.

    ``device_id`` wins wherever it exists: it is the registry's own answer.
    But it is optional — KEBA's UDP integration registers no device, and
    manually configured MQTT entities have none either — and two of the
    three discovery sites used it as the WHOLE key (#964). ``None`` is not
    an identity: every device-less box of a platform collapsed into one
    bucket, so a per-device role pick (and, since #962, a sibling RANKING
    that searches that whole bucket for the best-named entity) could hand
    one charger the other charger's power sensor.

    For the device-less remainder there is no identity left, only NAMES —
    the entity-id prefix at three widths, and the trailing ``_<n>`` Home
    Assistant itself appends to a second box of the same name — each tried
    against the config entry first and then without it. Finest first.

    **A name axis becomes a boundary only on evidence: at least TWO of its
    groups must show the charger shape on their own.** That is the whole
    safety argument, and the reason this can ride a release with no live
    device-less box to prove it on. Splitting on a name alone changes the
    charger COUNT — a KEBA whose device is called "Keba" publishes
    ``sensor.keba_charging_power``, ``number.keba_charging_current`` and
    ``binary_sensor.keba_plug``: three prefixes, ONE box, and a split would
    hand its owner a charger with no plug and a ``keba.set_current`` with no
    target. A split that finds only ONE box separates nothing, so it is
    refused; where there is one box the grouping is byte-identical to the
    pre-#964 one.

    When two boxes ARE found, the groups that show no shape are dropped:
    they belong to neither box, and a brand function fed one box's leftovers
    invents a second, partial charger out of them (openWB's per-loadpoint
    MQTT entities are two real boxes; its ``openwb_global_*`` site totals are
    neither). ``build_detection_report`` lists them under ``unattributed``,
    so the drop is visible, never silent.

    ``unproven_split`` is what a device-less platform gets when the names
    propose a split the evidence does not carry:

    * ``"merge"`` — one bucket, the pre-#964 behaviour, for the paths that
      BIND: a split nobody proved must never shed a box's entities.
    * ``"prefix"`` — keep the two-token name split, the prober's behaviour
      since #814: it binds nothing, an unproven fragment simply fails its
      own shape test, and merging a rig's template platform into "one
      device" is what handed a mock charger an SG-Ready switch for
      start/stop.

    Returns ``{unit_key: [entities]}`` in first-appearance order; a unit key
    is the ``device_id`` string where there was one, and an opaque tuple
    otherwise.
    """
    entities = list(entities)
    position: Dict[str, int] = {}
    for i, e in enumerate(entities):
        position.setdefault(str(getattr(e, "entity_id", "")), i)

    units: Dict[Any, List[Any]] = {}
    deviceless: Dict[str, List[Any]] = {}
    for e in entities:
        device_id = getattr(e, "device_id", None)
        if device_id is None or device_id == "":
            deviceless.setdefault(
                str(getattr(e, "platform", "") or ""), []).append(e)
        else:
            units.setdefault(device_id, []).append(e)

    for platform, plat_entities in deviceless.items():
        units.update(_split_deviceless(platform, plat_entities, unproven_split))

    # First-appearance order, for the units and inside each of them: a unit's
    # place is its earliest entity, so which charger is "primary" (the first
    # entry the config path returns) does not depend on whether a box happens
    # to carry a device id — and a re-attached leftover takes its registry
    # place rather than the end of the list, which is what a brand function
    # that binds first- or last-wins reads.
    def _place(entity) -> int:
        return position.get(str(getattr(entity, "entity_id", "")), 0)

    return {key: sorted(members, key=_place)
            for key, members in sorted(units.items(),
                                       key=lambda kv: min(_place(e)
                                                          for e in kv[1]))}


def unit_label(unit_key) -> str:
    """A stable, readable token for a unit — the device id where there is
    one, else ``platform/entry/name``. Report data: never parsed back."""
    if isinstance(unit_key, str):
        return unit_key
    return "/".join(str(part) for part in tuple(unit_key)[1:])


def unit_device_id(unit_key) -> Optional[str]:
    """The ``device_id`` a unit key carries, or ``None`` for a device-less
    unit. Report data and migration metadata alike: an opaque grouping key
    is never written out as if it were a registry device id."""
    return unit_key if isinstance(unit_key, str) else None


def discover_all_ev_chargers_from_registry(
    hass: HomeAssistant, *, meters_out: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    """Auto-discover ALL EV chargers from known integrations via entity registry.

    Returns a list of charger configs, one per detected charger. Each dict
    contains the same keys as discover_ev_charger_from_registry().
    The first entry is the "primary" charger for backward compatibility.

    For charger integrations that expose multiple devices (e.g., 2 Wallbox
    Pulsars), each device produces a separate entry grouped by device_id.

    (#1036) A meter beside a charger is not returned. ``meters_out``, when
    given, receives each such meter in the shape it was returned in before
    — so setup can find a meter it saved as the charger back then.
    """
    entity_reg = entity_registry.async_get(hass)
    chargers: List[Dict[str, str]] = []

    for platform, discover_fn in _EV_CHARGER_PLATFORMS:
        def _matches_platform(entry_platform: str, _this=platform) -> bool:
            # Some HACS/custom Zaptec builds expose a domain such as
            # ``zaptec_custom`` while keeping the same entity model. Restrict
            # the tolerant match to the Zaptec prefix; every other integration
            # remains exact to avoid broad accidental charger discovery.
            # ``_this`` binds the loop variable: an unbound closure would match
            # against whichever platform the loop reached last, so the day this
            # predicate is passed anywhere instead of called in place, every
            # brand would be tested against the final one.
            if _this == "zaptec":
                return entry_platform == "zaptec" or entry_platform.startswith("zaptec_")
            return entry_platform == _this

        entities = [
            e for e in entity_reg.entities.values()
            if _matches_platform(str(e.platform or "")) and not e.disabled_by
        ]
        if not entities:
            continue
        disabled = [
            e for e in entity_reg.entities.values()
            if _matches_platform(str(e.platform or "")) and e.disabled_by
        ]

        # Group entities by the physical unit they belong to: device_id
        # where the registry has one (e.g., 2 Wallbox Pulsars), and the
        # evidenced fallback where it has none (#964 — KEBA registers no
        # device, and one bucket for "no device" mixes two boxes).
        devices = group_entities_by_unit(entities)

        found = {}
        for unit_key, device_entities in devices.items():
            result = _discover_unit(discover_fn, device_entities)
            if result:
                # (#886) never drive a charger through its offline fallback
                # register; (#962) never read its advertised capability as a
                # measurement.
                apply_charger_discovery_guards(result, device_entities)
            found[unit_key] = (result, device_entities)
        # (#1036) a meter the integration ships beside its charger is not a
        # second charger — and must never be the first one.
        meters = meters_beside_chargers(platform, found, disabled)

        for unit_key, (result, device_entities) in found.items():
            device_id = unit_device_id(unit_key)
            if unit_key in meters:
                _LOGGER.info(
                    "Not a charger: %s device %s is a meter beside a charger "
                    "(#1036)", platform, device_id or unit_label(unit_key))
                if meters_out is not None:
                    was = dict(result)
                    was["_platform"] = str(device_entities[0].platform or platform)
                    if device_id:
                        was["_device_id"] = device_id
                    meters_out.append(was)
                continue
            if result and not any(result.get(k) for k in _CHARGER_SIGNS):
                # (#1054) a brand mapping that found only a meter — no power
                # reading, no plug, no charging state, no control — has not
                # found a charger. Leave the device to the roles, which read
                # what the integration really offers: go-e's ``goecharger``
                # brand path matched only a total-energy sensor. (A Zaptec
                # with a plug and a resume button but no power stays: #804.)
                _LOGGER.debug(
                    "%s device %s: brand path found only a meter — left to "
                    "the roles", platform, device_id or unit_label(unit_key))
                continue
            if result:
                # Preserve the registry's real domain for diagnostics/stable
                # migration metadata (e.g. zaptec_custom), not just the
                # canonical matcher name.
                result["_platform"] = str(device_entities[0].platform or platform)
                if device_id:
                    result["_device_id"] = device_id
                # (#804 B4c) Zaptec's phase selector lives on the
                # INSTALLATION device as a current threshold (EVCC's Go2
                # path: 32 A → 1-phase, 0 A → 3-phase) — a sibling device
                # this per-device loop never hands to the discover fn. When
                # this platform's registry carries one, SUGGEST it: entity +
                # values, underscore-keyed (report data, not a config role),
                # never auto-configured — the user confirms it in the flow.
                if platform == "zaptec":
                    for _e in entities:
                        _uid = str(getattr(_e, "unique_id", "") or "").lower()
                        if (str(_e.entity_id).startswith("number.")
                                and _uid.endswith(
                                    "three_to_one_phase_switch_current")):
                            result["_suggested_phase_switch"] = {
                                "entity": str(_e.entity_id),
                                "value_1p": "32", "value_3p": "0",
                            }
                            break
                _LOGGER.info(
                    "Auto-discovered EV charger from %s (device %s): %s",
                    platform,
                    device_id or "default",
                    {k: v for k, v in result.items() if not k.startswith("_")},
                )
                chargers.append(result)

    # (#1032) the roster's roles find a charger on any integration the brand
    # list does not name — the same offer the detection report shows as a
    # near miss. Only for discovery: a charger already saved keeps its
    # mapping (nothing here rewrites saved config; setup and the add-charger
    # step offer it, and the user confirms).
    try:
        chargers.extend(_role_discovered_chargers(hass, entity_reg, chargers))
    except Exception:  # noqa: BLE001 — a new reader never costs discovery
        _LOGGER.debug("role discovery failed", exc_info=True)
    return chargers


#: (#1054) What makes a brand mapping a charger rather than a meter.
_CHARGER_SIGNS = ("ev_charging_power_sensor", "ev_connected_sensor",
                  "ev_charging_sensor", "ev_current_control_entity",
                  "ev_charger_service", "ev_start_stop_entity",
                  "ev_charge_mode_entity", "ev_start_service")

#: Every per-charger key that names an ENTITY — what says something about
#: the physical box rather than about the car or about how to talk to it.
#: Service names are deliberately absent: two KEBAs both answer to
#: ``keba.set_current``, so a service is not an identity. The ONE
#: fingerprint of a charger: the config flow's "already installed" check,
#: the set_option merge (#1054 follow-up: a second "create" of the same
#: box folds into the first) and the detection report all read it.
CHARGER_ENTITY_KEYS = frozenset({
    "ev_charge_mode_entity",
    "ev_charger_service_entity_id",
    "ev_charging_power_sensor",
    "ev_charging_sensor",
    "ev_connected_sensor",
    "ev_current_control_entity",
    "ev_current_sensor",
    "ev_session_energy_sensor",
    "ev_start_stop_entity",
    "ev_total_energy_sensor",
})


#: The keys a configured charger's report row shows: its entities and how
#: SEM talks to it. Modes, targets and priorities are settings, not roles.
_CONFIGURED_ROW_KEYS = CHARGER_ENTITY_KEYS | frozenset({
    "ev_charger_service", "ev_service_param_name", "ev_charger_service_data",
    "ev_start_service", "ev_start_service_data",
    "ev_stop_service", "ev_stop_service_data",
    "ev_charge_mode_start", "ev_charge_mode_stop", "ev_phase_switch_entity",
})


def charger_entity_ids(charger: Any) -> set:
    """The entities a charger config points at — its fingerprint."""
    if not isinstance(charger, dict):
        return set()
    return {str(v) for k, v in charger.items() if k in CHARGER_ENTITY_KEYS and v}


def power_sensor_ids(hass) -> List[str]:
    """(#1054 follow-up) Every sensor the crawler reads as a POWER reading:
    device_class ``power``, or — when the integration set no class — a unit
    in W/kW (``_roles_dc``'s rule, the one that found go-e's ``p_all``).
    The power pickers offer this list; a picker that filtered on the device
    class alone could not show the very sensor the crawler had matched."""
    out: set = set()
    if hass is None:
        return []
    try:
        registry = entity_registry.async_get(hass)
        for e in registry.entities.values():
            eid = str(e.entity_id)
            if eid.startswith("sensor.") and not e.disabled_by \
                    and _roles_dc(e) == "power":
                out.add(eid)
    except Exception:  # noqa: BLE001 — the registry half stands alone
        pass
    try:
        for st in hass.states.async_all("sensor"):
            attrs = getattr(st, "attributes", None) or {}
            dc = attrs.get("device_class")
            unit = attrs.get("unit_of_measurement")
            if dc == "power" or (not dc and isinstance(unit, str)
                                 and _UNIT_CLASS.get(unit.strip().lower()) == "power"):
                out.add(str(st.entity_id))
    except Exception:  # noqa: BLE001 — the states half stands alone
        pass
    return sorted(out)


def _role_discovered_chargers(hass, registry, found) -> List[Dict[str, Any]]:
    """(#1032) Complete role offers for units no brand path claimed, in the
    shape discovery returns (``_platform`` / ``_device_id`` instead of the
    near miss's ``id`` / ``name``)."""
    running = bool(getattr(hass, "is_running", True)) if hass is not None else False
    state_of = ((lambda eid: hass.states.get(eid))
                if (hass is not None and running and hasattr(hass, "states"))
                else None)
    taken = {str(v) for c in found for k, v in c.items()
             if not k.startswith("_") and isinstance(v, str) and "." in v}
    report: Dict[str, Any] = {"chargers": [], "near_misses": [], "vehicles": []}
    _roles_pass(report, registry, [], taken, _services_of(hass), state_of,
                device_ident_of=_device_ident_of(hass),
                include_brand_platforms=True)
    out: List[Dict[str, Any]] = []
    for n in report["near_misses"]:
        offer = dict(n.get("suggested_charger") or {})
        if not offer:
            continue
        offer.pop("id", None)
        offer.pop("name", None)
        offer["_platform"] = n["platform"]
        if n.get("device_id"):
            offer["_device_id"] = n["device_id"]
        offer["_found_by"] = "roles"
        _LOGGER.info("Role-discovered EV charger on %s (device %s): %s",
                     n["platform"], n.get("device_id") or "default",
                     {k: v for k, v in offer.items() if not k.startswith("_")})
        out.append(offer)
    return out


def probe_charger_candidates(hass: Optional[HomeAssistant] = None,
                             registry=None) -> List[Dict[str, Any]]:
    """(#814 Pillar A, land-asleep) Generic charger prober.

    Classifies registry DEVICES from what their entities ARE — domain +
    device_class — never from brand or entity names (the #684/#627
    lesson, and evcc's #30143: never infer from a name or a momentary
    state). A device is a charger candidate when it has a power reading
    AND a plug/charging binary AND some way to be controlled (a current
    ``number``, or a start/stop ``switch``).

    Runs BESIDE the brand functions: ``build_detection_report`` carries
    its candidates and any disagreement; nothing acts on it until the
    comparison window is clean. Pure over registry entries.
    """
    if registry is None:
        registry = entity_registry.async_get(hass)
    # SEM's own entities mirror the charger they describe — never a
    # candidate (live on the rig the prober "found" sem_charger_* sensors).
    entries = [e for e in registry.entities.values()
               if not e.disabled_by
               and str(e.platform or "") != "solar_energy_management"]
    # Group by device; entities without a device (KEBA's UDP integration
    # registers none) group per platform instead of being skipped —
    # ``group_entities_by_unit`` is the shared rule (#964), the same one the
    # config path and the diagnostics report now use: keba_p30_* is one box;
    # a rig's template platform is not one device (live: a mock charger got
    # an SG-Ready switch for "start/stop").
    # The prober BINDS nothing, so where the evidence does not carry a split
    # it keeps the name split rather than merging a platform into one device.
    devices = group_entities_by_unit(entries, unproven_split="prefix")

    out: List[Dict[str, Any]] = []
    for device_key, dev_entities in devices.items():
        device_id = unit_device_id(device_key)
        roles: Dict[str, str] = {}
        evidence: List[str] = []
        for e in dev_entities:
            eid = str(e.entity_id)
            dom = eid.split(".", 1)[0]
            dc = getattr(e, "original_device_class", None)
            if dom == "sensor" and dc == "power" and "ev_charging_power_sensor" not in roles:
                roles["ev_charging_power_sensor"] = eid
                evidence.append(f"{eid}: sensor/power → charging power")
            elif dom == "binary_sensor" and dc == "plug" and "ev_connected_sensor" not in roles:
                roles["ev_connected_sensor"] = eid
                evidence.append(f"{eid}: binary_sensor/plug → connected")
            elif dom == "binary_sensor" and dc in ("power", "battery_charging") \
                    and "ev_charging_sensor" not in roles:
                roles["ev_charging_sensor"] = eid
                evidence.append(f"{eid}: binary_sensor/{dc} → charging")
            elif dom == "number" and dc == "current" and "ev_current_control_entity" not in roles:
                roles["ev_current_control_entity"] = eid
                evidence.append(f"{eid}: number/current → current control")
            elif dom == "switch" and "ev_start_stop_entity" not in roles:
                roles["ev_start_stop_entity"] = eid
                evidence.append(f"{eid}: switch → start/stop (candidate)")
            elif dom == "sensor" and dc == "energy":
                evidence.append(f"{eid}: sensor/energy → metered energy (not a charger mark)")
        # (#886) the prober is advisory, but must not suggest an offline
        # fallback register as the control the config path will bind — nor
        # (#962) a ``Power.Offered``-shaped capability as the power reading
        # its own charger shape is then judged on.
        apply_charger_discovery_guards(roles, dev_entities)
        has_power = "ev_charging_power_sensor" in roles
        # Live on the rig: smart plugs (Shelly-class, kitchen toaster, carport
        # light) expose power + a binary with device_class=power — the same
        # class KEBA uses for "charging" — plus a switch. What only a charger
        # has is a PLUG/connected binary or a CURRENT control; a power-binary
        # alone is an input state. Require one of those two.
        has_plug = "ev_connected_sensor" in roles
        charger_marks = (has_plug or "ev_current_control_entity" in roles)
        # Control is reported, not required: a service-controlled box (KEBA)
        # shows no number/switch on the device yet is plainly a charger.
        # Power + a plug/charging binary IS the charger shape; what can
        # drive it is a separate, named fact.
        has_control = ("ev_current_control_entity" in roles
                       or "ev_start_stop_entity" in roles)
        if has_power and charger_marks:
            out.append({
                "platform": str(dev_entities[0].platform or ""),
                "device_id": device_id,
                # (#964) the grouping key, so two DEVICE-LESS boxes stay two
                # when the report pairs prober and brand findings — a pair of
                # ``None`` device ids collapses into one.
                "unit": unit_label(device_key),
                "roles": roles,
                "evidence": evidence,
                "control_visible": has_control,
            })
    return out


# ============================================================
# (#848) Installed-integration census — detection asks what EXISTS
# before it matches anything. Core and HACS integrations are the same
# thing here: a domain in the config-entry list, a platform on registry
# entities. The glob matrix never asked; the census always does.
# ============================================================

def known_charger_domains() -> frozenset:
    """Charger domains SEM has a discovery function for. ``mqtt`` is
    excluded from census bookkeeping on purpose: it is a transport, not a
    brand — its presence proves nothing and its "row" (JuiceBox) is
    identity-gated. A function, not a constant: ``_EV_CHARGER_PLATFORMS``
    is defined further down the module."""
    return frozenset(p for p, _ in _EV_CHARGER_PLATFORMS if p != "mqtt")

#: Inverter/battery integration domains SEM has read patterns or adapters
#: for. Deliberately curated and incomplete — the census reports what it
#: KNOWS; a brand missing here shows up as unknown_energy_domains, which
#: is the line that files the next detection row.
KNOWN_INVERTER_DOMAINS = frozenset({
    "huawei_solar", "fronius", "solaredge", "solaredge_modbus", "sma",
    "solax", "solax_modbus", "goodwe", "sungrow", "sungrow_modbus",
    "growatt_server", "growatt", "enphase_envoy", "powerwall", "tesla",
    "kostal_plenticore", "sonnen", "sonnenbatterie", "victron",
    "victron_gx", "deye", "solarman", "sun2000", "saj_modbus",
    "solis", "solis_modbus",
})

#: Domains that are infrastructure, never hardware brands.
_CENSUS_IGNORED = frozenset({
    "solar_energy_management", "mqtt", "sun", "template", "input_boolean",
    "input_number", "input_select", "automation", "script", "scene",
    "person", "zone", "schedule",
    # #848 live finding (.175): companion-app phones report battery class
    # + occasional power sensors and census as ENERGY-shaped. A phone is
    # never SEM-drivable hardware.
    "mobile_app",
})


def _census_energy_shaped(dev_entities) -> bool:
    """Does this domain's entity set look like ENERGY HARDWARE?

    Needs two independent signals: a power/energy sensor alone is any
    smart plug; the second signal (battery SOC, a controllable current or
    power number, a plug sensor) is what separates hardware SEM could
    drive from things that merely measure."""
    has_power = any(
        str(e.entity_id).startswith("sensor.")
        and getattr(e, "original_device_class", None) in ("power", "energy")
        for e in dev_entities)
    if not has_power:
        return False
    return any(
        (str(e.entity_id).startswith("sensor.")
         and getattr(e, "original_device_class", None) == "battery")
        or (str(e.entity_id).startswith("number.")
            and getattr(e, "original_device_class", None) in ("current", "power"))
        or (str(e.entity_id).startswith("binary_sensor.")
            and getattr(e, "original_device_class", None) == "plug")
        for e in dev_entities)


#: Platforms that carry many brands at once. A device here is not a brand,
#: so "entities present, no role matched" is only news when the device looks
#: like energy hardware.
_TRANSPORT_PLATFORMS = frozenset({"mqtt", "modbus", "esphome", "tasmota",
                                  "template", "rest", "command_line"})


def _roster():
    """(#915) The generated roster, or ``None``. Imported lazily and never
    at module scope: it is a 30 KB data module that only the census and the
    proposal path need, and a missing or broken roster must degrade to
    today's behaviour rather than break a detection run."""
    try:
        from .consts import integration_roster as _r
        return _r
    except Exception:  # noqa: BLE001 — a prior is never load-bearing
        return None


def roster_provenance() -> Dict[str, Any]:
    """When the roster was generated and from where — a prior with no
    provenance is a rumour."""
    r = _roster()
    if r is None:
        return {}
    meta = getattr(r, "ROSTER_META", {}) or {}
    return {"schema": getattr(r, "SCHEMA", None),
            "generated_at": meta.get("generated_at"),
            "rows": meta.get("kept")}


def describe_domain(domain: str) -> Optional[Dict[str, Any]]:
    """(#915) What the ecosystem says an integration IS — name, kind and how
    many people run it — or ``None`` when the roster has never heard of it.

    This is the ONLY thing the roster is allowed to assert on its own: a
    name. It is not a claim that SEM supports the brand, and nothing here
    reads a user's entities."""
    r = _roster()
    if r is None:
        return None
    row = (getattr(r, "ROSTER", {}) or {}).get(str(domain))
    if not row:
        return None
    return {"domain": str(domain), "name": row.get("name"),
            "kind": row.get("kind"), "installs": row.get("installs"),
            "known_vocabulary": bool(
                (getattr(r, "ROLE_VOCAB", {}) or {}).get(str(domain)))}


def roster_role_vocab(domain: str, role: str) -> Dict[str, tuple]:
    """What an integration DECLARES for a SEM role, from its own repository:
    ``{"keys": (...), "exact_only": (...)}``. ``exact_only`` names the keys
    that may be matched by translation_key alone — each is a segment-suffix
    of a LONGER key the same brand declares (``max_discharge_power`` beside
    ``system_max_discharge_power``), so a unique_id suffix cannot tell them
    apart. Every consumer must carry it; ``roster_role_keys`` below dropped
    it, and the discovery rung that auto-binds the discharge control was
    matching on the stripped list (found by the 06.09 audit)."""
    r = _roster()
    if r is None:
        return {"keys": (), "exact_only": ()}
    body = ((getattr(r, "ROLE_VOCAB", {}) or {}).get(str(domain)) or {}).get(role)
    if not body:
        return {"keys": (), "exact_only": ()}
    return {"keys": tuple(body.get("keys", ())),
            "exact_only": tuple(body.get("exact_only", ()))}


def roster_role_keys(domain: str, role: str) -> tuple:
    """The entity keys an integration DECLARES for a SEM role. Empty when the
    roster has no vocabulary for it. Callers that MATCH must use
    ``_entry_matches_declared`` with ``roster_role_vocab``, never a bare
    ``endswith`` over this list."""
    return roster_role_vocab(domain, role)["keys"]


def _entry_matches_declared(entry, keys, exact_only=()) -> Optional[str]:
    """The ONE matcher every consumer of the roster uses. translation_key is
    the integration's own word and matches exactly. unique_id is a
    convention (``<serial>_<key>``): it matches at a ``_`` segment boundary
    only — a bare ``endswith`` is bug class 67 — and never for an
    ``exact_only`` key. Returns the matched key or None."""
    tk = str(getattr(entry, "translation_key", "") or "")
    uid = str(getattr(entry, "unique_id", "") or "")
    exact = set(exact_only or ())
    for k in keys:
        if tk == k:
            return k
        if k not in exact and (uid == k or uid.endswith("_" + k)):
            return k
    return None


_CURRENT_FIELDS = ("current", "max_current", "charging_current", "amps",
                   "ampere", "amp", "current_a")


def _current_field(fields) -> Optional[str]:
    """(#956) The one field of a current-setting service SEM writes the
    amperes into — by the integration's own word, or the only field there
    is. None when the service has no such field."""
    for want in _CURRENT_FIELDS:
        if want in fields:
            return want
    # (ruflo pass 2) a lone field is the current only if it SAYS so —
    # set_energy(energy) has one field and it is not amperes.
    if len(fields) == 1 and any(w in fields[0] for w in ("current", "amp")):
        return fields[0]
    return None


def _services_of(hass):
    """(#956) A callback answering "which services does this domain offer
    right now", or None when that cannot be asked (no hass, not running).
    None is an UNKNOWN: the caller proposes nothing and says why, never
    "no". Read live from HA's own registry — never guessed from a roster."""
    if hass is None or not bool(getattr(hass, "is_running", True)):
        return None
    services = getattr(hass, "services", None)
    if services is None or not hasattr(services, "async_services"):
        return None

    def _of(domain: str) -> "_ServiceNames":
        """The domain's service names (a set, as before); (#1032) each
        name's fields ride along in ``.fields``, read from the service's own
        schema, so a role can be read from what a service TAKES."""
        out: Dict[str, list] = {}
        try:
            for name, svc in ((services.async_services() or {})
                              .get(str(domain), {}) or {}).items():
                fields: list = []
                inner = getattr(getattr(svc, "schema", None), "schema", None)
                if isinstance(inner, dict):
                    fields = sorted(str(getattr(k, "schema", k)) for k in inner)
                if not fields:
                    # (#1054) a service registered with NO schema (go-e's
                    # set_max_current) tells its fields only through its
                    # services.yaml — Home Assistant's description cache
                    fields = _described_fields(hass, str(domain), str(name))
                out[str(name)] = fields
        except Exception:  # noqa: BLE001
            return _ServiceNames()
        return _ServiceNames(out)
    return _of


def _described_fields(hass, domain: str, service: str) -> list:
    """The fields of ``domain.service`` from Home Assistant's cached service
    descriptions (filled from services.yaml; SEM primes it after start)."""
    try:
        from homeassistant.helpers.service import (
            async_get_cached_service_description,
        )
        desc = async_get_cached_service_description(hass, domain, service) or {}
    except Exception:  # noqa: BLE001
        return []
    fields = desc.get("fields") if isinstance(desc, dict) else None
    return sorted(str(f) for f in fields) if isinstance(fields, dict) else []


def _device_ident_of(hass):
    """(#1054) A callback answering "what does this integration call this
    device": the registry identifier ``(domain, <name>)`` of the entities'
    device. go-e's services take that name in ``charger_name``. None when it
    cannot be asked or the device carries no identifier of that domain."""
    if hass is None:
        return None
    try:
        from homeassistant.helpers import device_registry as _dr
        dreg = _dr.async_get(hass)
    except Exception:  # noqa: BLE001
        return None

    def _of(ents, domain: str):
        ids = {getattr(e, "device_id", None) for e in ents or ()} - {None}
        if len(ids) != 1:
            return None
        dev = dreg.async_get(next(iter(ids)))
        names = [v for d, v in (getattr(dev, "identifiers", None) or ())
                 if d == domain and isinstance(v, str) and v]
        return names[0] if len(names) == 1 else None
    return _of


class _ServiceNames(set):
    """A set of service names that also knows each one's fields."""

    def __init__(self, fields: Optional[Dict[str, list]] = None) -> None:
        super().__init__(fields or ())
        self.fields: Dict[str, list] = dict(fields or {})

    def get(self, name, default=None):
        return self.fields.get(name, default)


def propose_roles_from_roster(dev_entities, domain: str, *,
                              state_of=None,
                              strategy_values=None,
                              services_of=None,
                              device_ident=None) -> Dict[str, Any]:
    """(#915) Role proposals for ONE device, as an INTERSECTION.

    The roster says what an integration calls things; ``dev_entities`` is
    what this install actually has. Only entities present in BOTH are
    proposed, so this can never invent hardware — the entity is physically
    in the user's registry, under that integration. It can still be a wrong
    ROLE, which is why every consumer treats the result as a proposal the
    user confirms and never as a binding (bug class 42: read paths may
    guess, actuation paths may not).

    Matching is on ``translation_key`` (or a ``unique_id`` suffix), never on
    the entity_id: a translation key is the integration author's own
    semantic label, an entity_id is the user's rename.
    """
    r = _roster()
    if r is None:
        return {}
    vocab = (getattr(r, "ROLE_VOCAB", {}) or {}).get(str(domain))
    if not vocab:
        return {}
    out: Dict[str, Any] = {}
    for role, body in vocab.items():
        keys = tuple(body.get("keys", ()))
        want_domain = str(body.get("platform") or "")
        if want_domain == "service":
            # (#956) a service-shaped capability: intersected with HA's live
            # service registry, the way entities are intersected with the
            # entity registry. Unaskable → nothing, and nothing invented.
            if services_of is None:
                # (ruflo, 24.09) an UNKNOWN is a value the card can show,
                # not an empty dict indistinguishable from "absent".
                out[role] = {"service": None, "matched_key": None,
                             "source": "roster", "config_key": None,
                             "action": "unaskable",
                             "reason": "the service registry could not be "
                                       "asked yet (HA still starting)",
                             "candidates": list(keys), "judged": False}
                continue
            live = services_of(domain)
            for key in keys:
                name = key.split(".", 1)[1] if "." in key else key
                if name in live:
                    try:
                        from .consts import role_lexicon as _lex
                        pck = _lex.SERVICE_CONFIG_KEY_FOR_ROLE.get(role)
                    except Exception:  # noqa: BLE001
                        pck = None
                    meta = (body.get("services") or {}).get(key) or {}
                    fields = tuple(meta.get("fields") or ())
                    target = meta.get("target")
                    param = _current_field(fields)
                    extra = [f for f in fields if f != param]
                    # (#1054) a field that names the box is filled with the
                    # device's own identifier — the integration's word for it
                    named = _device_name_data(extra, device_ident)
                    extra = [f for f in extra if f not in named]
                    prop = {"service": key, "matched_key": key,
                            "source": "roster", "config_key": None,
                            "action": "per_charger",
                            "per_charger_key": pck, "judged": True,
                            "param": param, "fields": list(fields),
                            "target": target}
                    if named:
                        prop["data"] = named
                    # (ruflo, 24.09) go-eCharger's set_max_current wants a
                    # charger_name SEM cannot fill; a targeted service wants
                    # an entity_id the charger factory does not pass. Either
                    # is a proposal SEM must not turn into a one-click add.
                    why = []
                    if not param:
                        why.append("no field SEM can send the current in")
                    if extra:
                        why.append("fields SEM cannot fill: " + ", ".join(extra))
                    if target:
                        why.append(f"the service targets a {target}")
                    if why:
                        prop["action"] = "needs_hand_wiring"
                        prop["reason"] = "; ".join(why)
                    out[role] = prop
                    break
            continue
        # (#810) Collect EVERY match, then choose deterministically. Taking
        # the first entity the registry happened to yield meant that a brand
        # declaring four target-SOC keys got whichever one iteration order
        # produced — a different answer on two boxes with the same hardware.
        # The roster's key order is stable (sorted at generation), so it is
        # the tie-break, and the runners-up ride along instead of vanishing.
        matches = []
        for entry in dev_entities:
            eid = str(getattr(entry, "entity_id", ""))
            if want_domain and not eid.startswith(f"{want_domain}."):
                continue
            hit = _entry_matches_declared(
                entry, keys, body.get("exact_only", ()))
            if hit:
                matches.append((keys.index(hit), eid, hit))
        if not matches:
            continue
        matches.sort()
        rank, eid, hit = matches[0]
        out[role] = {"entity": eid, "matched_key": hit,
                     "source": "roster",
                     # (#915) What the user can DO about it. A proposal that
                     # says "unconfirmed" and offers no way to confirm is a
                     # chore, not an offer: ``config_key`` is the option the
                     # card writes with one click, and its absence says why
                     # there is no button.
                     **_role_action(role)}
        if len(matches) > 1:
            out[role]["alternatives"] = [
                {"entity": e, "matched_key": k} for _, e, k in matches[1:]
            ]
        # (#915) The button is offered only when the entity can actually
        # take what SEM will write. Three things the registry cannot tell:
        # whether the entity is LOADED, what it MEASURES, and — for a
        # strategy select — whether it lists the options SEM would send.
        # Before this, discovery's explicit-unit gate never ran on this path
        # (the button writes the option directly), so a key named like a
        # power limit and measured in amps got a button.
        out[role]["judged"] = state_of is not None
        if out[role]["action"] == "set_option" and state_of is not None:
            _gate_proposal(out[role], role, state_of, strategy_values)
    # (#915, 06.09 audit) Half a split pair is not a proposal — PER DEVICE.
    # The crawler enforces PAIRED_ROLES on the whole declared vocabulary, but
    # a firmware or model variant may expose only one of the two sensors on
    # THIS box; accepting that one alone writes grid_import_power_entity
    # with no export half, and the reader then reads "always importing,
    # never exporting" with no warning. The button is withheld and the row
    # says which half is missing.
    try:
        from .consts import role_lexicon as _lex
        pairs = getattr(_lex, "PAIRED_ROLES", ())
    except Exception:  # noqa: BLE001
        pairs = ()
    for pair in pairs:
        present = [r for r in pair if r in out]
        if 0 < len(present) < len(pair):
            for r in present:
                if out[r].get("action") == "set_option":
                    out[r]["action"] = "pair_incomplete"
                    out[r]["missing_role"] = [x for x in pair if x not in out]
    return out


def _gate_proposal(prop: Dict[str, Any], role: str, state_of,
                   strategy_values) -> None:
    """Downgrade ``action`` from ``set_option`` when the live entity cannot
    take the write. Mutates ``prop``; every branch leaves a reason the card
    can render, never a bare refusal."""
    try:
        from .consts import role_lexicon as _lex
    except Exception:  # noqa: BLE001
        return
    st = None
    try:
        st = state_of(prop["entity"])
    except Exception:  # noqa: BLE001
        st = None
    if st is None:
        # registry knows it, HA never produced it (#824's ``restored``)
        prop["action"] = "not_loaded"
        return
    attrs = getattr(st, "attributes", None) or {}
    want = _lex.ROLE_EXPECTED_UNIT.get(role)
    if want:
        unit = str(attrs.get("unit_of_measurement") or "").strip()
        accepted = _lex.UNIT_CLASSES.get(want, frozenset())
        if not unit:
            prop["action"] = "no_unit"
            prop["unit_wanted"] = "/".join(sorted(accepted))
            return
        if unit not in accepted:
            prop["action"] = "unit_mismatch"
            prop["unit_seen"] = unit
            prop["unit_wanted"] = "/".join(sorted(accepted))
            return
    if role == "battery_power_strategy":
        options = [str(o) for o in (attrs.get("options") or [])]
        values = dict(_lex.STRATEGY_VALUE_KEYS)
        for key, default in _lex.STRATEGY_VALUE_KEYS:
            values[key] = str((strategy_values or {}).get(key) or default)
        # (#1039) the runtime's matcher, without HA's labels: a value names
        # an option when it maps to one. Stricter than the runtime, never
        # looser — a translated label still reads as unmapped here.
        missing = sorted({v for v in values.values()
                          if pick_listed(options, v) not in options})
        if missing:
            prop["action"] = "options_unmapped"
            prop["options"] = options[:12]
            prop["values_missing"] = missing
            return


# ============================================================
# (#1032) Charger roles read from ANY integration's own words — the roster
# learning what a charger, or a car that charges, offers beside a current
# number. SEM connects to integrations; it does not cover hardware (Guido,
# 01.10.2026). The rule tables live in consts/role_lexicon.py; nothing below
# names an integration. Report data only, never a binding.
# ============================================================

def _role_words(entry) -> List[str]:
    """An entity's own words: its translation key and its unique id."""
    return [w for w in (getattr(entry, "translation_key", None),
                        getattr(entry, "unique_id", None))
            if isinstance(w, str) and w]


def _rule_hits(entry, rule) -> bool:
    if not str(getattr(entry, "entity_id", "")).startswith(f"{rule['platform']}."):
        return False
    words = _role_words(entry)
    if any(re.search(p, w, re.I) for p in rule.get("not", ()) for w in words):
        return False
    return any(re.search(p, w, re.I) for p in rule["any"] for w in words)


def _first_hit(entries, rule) -> Optional[str]:
    hits = sorted(str(e.entity_id) for e in entries if _rule_hits(e, rule))
    return hits[0] if hits else None


_UNIT_CLASS = {"w": "power", "kw": "power", "mw": "power",
               "wh": "energy", "kwh": "energy", "mwh": "energy"}


def _declared_dc(entry) -> str:
    """The device class the integration itself set — no unit fallback."""
    dc = getattr(entry, "original_device_class", None)
    dc = getattr(dc, "value", dc)
    return dc if isinstance(dc, str) else ""


def _roles_dc(entry) -> str:
    """The entity's device class; (#1054) when the integration set none, the
    class its unit says — a sensor in kW IS a power reading (go-e's
    ``p_all``), a sensor in kWh an energy one."""
    dc = getattr(entry, "original_device_class", None)
    dc = getattr(dc, "value", dc)
    if isinstance(dc, str) and dc:
        return dc
    unit = getattr(entry, "unit_of_measurement", None)
    if isinstance(unit, str):
        return _UNIT_CLASS.get(unit.strip().lower(), "")
    return ""


def _speaks_vehicle(entries) -> bool:
    """A CAR's vocabulary: a vehicle marker, and none of a building's."""
    from .consts import role_lexicon as lex
    words = " ".join(w.lower() for e in entries for w in _role_words(e))
    return (any(m in words for m in lex.VEHICLE_MARKERS)
            and not any(m in words for m in lex.HOUSE_MARKERS))


def _select_options(entry, state_of) -> List[str]:
    opts = None
    if state_of is not None:
        st = state_of(str(entry.entity_id))
        if st is not None:
            opts = (getattr(st, "attributes", None) or {}).get("options")
    if not opts:
        caps = getattr(entry, "capabilities", None)
        opts = caps.get("options") if isinstance(caps, dict) else None
    return [str(o) for o in opts] if isinstance(opts, (list, tuple)) else []


def _pick_option(options: List[str], wanted) -> Optional[str]:
    """The option to WRITE, matched by meaning: ``max_charge`` (Ohme's real
    option value, shown translated as "Max charge") is ``max charge``."""
    low: Dict[str, str] = {}
    for o in options:
        low.setdefault(o.lower(), o)
        low.setdefault(o.lower().replace("_", " ").replace("-", " "), o)
    for w in wanted:
        if w in low:
            return low[w]
    return None


def _charging_power(entries, *, vehicle: bool) -> Optional[str]:
    """The charging power reading: a power sensor that is not one phase leg
    or a clamp on something else; on a car it must say it is the charger's."""
    cands = []
    unit_only = []
    for e in entries:
        eid = str(e.entity_id)
        if not eid.startswith("sensor.") or _roles_dc(e) != "power":
            continue
        words = " ".join(_role_words(e)).lower() + " " + eid.lower()
        if vehicle and "charg" not in words:
            continue
        if re.search(r"(reactive|export|import|generation|generator|grid|"
                     r"battery|photovolt|solar|_pv_|\bpv\b|monitor)", words):
            continue
        leg = (bool(re.search(r"(?:_|-)(l[123]|phase_?[123]|ct[1-9]|[123]|n)$", eid))
               or bool(re.search(r"phase_[123]", eid)))
        # (#1054) "all" is the box's total over its phases (go-e ``p_all``)
        named = bool(re.search(r"charg|total|session|(?:^|_)all$", words))
        # a reading that says "power" over one that only shares the class
        # (NRGkick's ``charging_rate`` carries the power class)
        says_power = "power" in " ".join(_role_words(e)).lower() + eid.lower()
        row = (leg, not says_power, not named, eid)
        if _declared_dc(e) == "power":
            cands.append(row)
        else:
            unit_only.append(row)
    if cands:
        # what the integration itself calls power wins; the unit fallback
        # never competes with it (#1054 review)
        cands.sort()
        return cands[0][-1]
    # (#1054 review) a power class read from the unit alone is a guess the
    # integration did not make. Pick only when it is unambiguous: exactly
    # one whole-box reading, or exactly one that names itself (charg, total,
    # session, all). Otherwise the user chooses — never alphabetical luck.
    whole = [r for r in unit_only if not r[0]]
    if len(whole) == 1:
        return whole[0][-1]
    hinted = [r for r in whole if not r[2]]
    if len(hinted) == 1:
        return hinted[0][-1]
    return None


def _plugged(entries) -> Optional[str]:
    plugs = sorted(str(e.entity_id) for e in entries
                   if str(e.entity_id).startswith("binary_sensor.")
                   and _roles_dc(e) == "plug")
    if plugs:
        return plugs[0]
    cables = sorted(str(e.entity_id) for e in entries
                    if str(e.entity_id).startswith("binary_sensor.")
                    and _roles_dc(e) == "connectivity"
                    and re.search(r"cable|plug", " ".join(_role_words(e)), re.I))
    return cables[0] if cables else None


def _charging_now(entries) -> Optional[str]:
    hits = sorted(
        str(e.entity_id) for e in entries
        if str(e.entity_id).startswith("binary_sensor.")
        and (_roles_dc(e) == "battery_charging"
             or (_roles_dc(e) == "running"
                 and re.search(r"charg|contactor", " ".join(_role_words(e)), re.I))))
    return hits[0] if hits else None


def _current_number_role(entries) -> Optional[str]:
    from .consts import role_lexicon as lex
    rule = lex.ROLE_RULES["ev_current_control"]
    hits = []
    for e in entries:
        eid = str(e.entity_id)
        if not eid.startswith("number."):
            continue
        for w in _role_words(e):
            key = w.rsplit("-", 1)[-1]
            if "ev_current_control" in (lex.role_for("number", key),
                                        lex.role_for("number", w)):
                hits.append(eid)
                break
            # ``amp``, ``charge_rate`` — a current only on a charger
            if (any(re.search(p, key, re.I) for p in rule.get("charger_only_any", ()))
                    and not any(re.search(p, key, re.I) for p in rule.get("not", ()))):
                hits.append(eid)
                break
    return sorted(hits)[0] if hits else None


def _is_stored_setting(entries, eid: Optional[str]) -> bool:
    """A number filed under the CONFIG category is a stored setting (a box's
    own maximum), not a live control: rewriting it every cycle wears the
    box's memory and changes what the owner set."""
    for e in entries:
        if str(e.entity_id) == eid:
            cat = getattr(e, "entity_category", None)
            return str(getattr(cat, "value", cat) or "") == "config"
    return False


def _device_name_data(fields, device_ident) -> Dict[str, Any]:
    """(#1054) The service fields that name WHICH box, filled with the
    device's own identifier. Empty when there is no identifier."""
    from .consts import role_lexicon as lex
    if not device_ident:
        return {}
    return {f: device_ident for f in fields if f in lex.DEVICE_NAME_FIELDS}


def _service_current_role(domain: str, services: Dict[str, list], *,
                          device_ident=None) -> Optional[Dict[str, Any]]:
    """(#956 rule, read live) a current-setting service with a current field
    is a CONTROL — a service-driven charger is never read-only."""
    from .consts import role_lexicon as lex
    rule = lex.SERVICE_ROLE_RULES.get("ev_current_control") or {}
    for name in sorted(services or {}):
        fields = list((services or {}).get(name) or [])
        full = f"{domain}.{name}"
        param = _current_field(fields)
        if (rule and param
                and any(re.search(p, full, re.I) for p in rule.get("any", ()))
                and not any(re.search(p, full, re.I) for p in rule.get("not", ()))):
            out = {"service": full, "param": param, "fields": fields}
            named = _device_name_data([f for f in fields if f != param],
                                      device_ident)
            if named:
                out["data"] = named
            return out
    return None


def _service_field_roles(domain: str, services: Dict[str, list]) -> Dict[str, Any]:
    """R6 — services read by their FIELDS (report data)."""
    from .consts import role_lexicon as lex
    out: Dict[str, Any] = {}
    for name in sorted(services or {}):
        fields = list((services or {}).get(name) or [])
        if all(f in fields for f in lex.SERVICE_PHASE_FIELDS):
            out.setdefault("phase_service", {"service": f"{domain}.{name}",
                                             "fields": fields})
        cur = [f for f in fields if f in lex.SERVICE_SITE_CURRENT_FIELDS]
        if cur:
            out.setdefault("site_service", {"service": f"{domain}.{name}",
                                            "param": cur[0], "fields": fields})
    return out


def read_charger_roles(dev_entities, domain: str, *, services_of=None,
                       state_of=None, device_ident=None) -> Dict[str, Any]:
    """(#1032) Every charger role ONE device carries, by its own words:
    R2 start/stop buttons, R3 a car's charge control, R5 a select read by its
    options, R6 services by their fields (plus the #956 current service)."""
    from .consts import role_lexicon as lex
    roles: Dict[str, Any] = {}
    vehicle = _speaks_vehicle(dev_entities)
    if vehicle:
        roles["vehicle"] = True
        for role, rule in lex.VEHICLE_CONTROL_RULES.items():
            hit = _first_hit(dev_entities, rule)
            if hit:
                roles[role] = hit
    else:
        cur = _current_number_role(dev_entities)
        if cur:
            roles["current_number"] = cur
            if _is_stored_setting(dev_entities, cur):
                roles["current_is_setting"] = True
        sw = _first_hit(dev_entities, lex.CHARGER_SWITCH_RULES["ev_charge_switch"])
        if sw:
            roles["charge_switch"] = sw
        start = _first_hit(dev_entities, lex.CHARGER_BUTTON_RULES["ev_start_button"])
        stop = _first_hit(dev_entities, lex.CHARGER_BUTTON_RULES["ev_stop_button"])
        if start and stop:
            roles["start_stop_buttons"] = [start, stop]
        for e in sorted(dev_entities, key=lambda x: str(x.entity_id)):
            if not str(e.entity_id).startswith("select."):
                continue
            opts = _select_options(e, state_of)
            go = _pick_option(opts, lex.SELECT_CHARGE_OPTIONS)
            from .coordinator.charger_adapters.status_enum import SELECT_STOP_WORDS
            halt = _pick_option(opts, tuple(sorted(SELECT_STOP_WORDS)))
            if go and halt and "charge_mode" not in roles:
                roles["charge_mode"] = {"entity": str(e.entity_id),
                                        "start": go, "stop": halt}
            elif (all(p in opts for p in lex.SELECT_PHASE_OPTIONS)
                  and "phase_select" not in roles):
                roles["phase_select"] = {"entity": str(e.entity_id),
                                         "value_1p": "1", "value_3p": "3"}
        # a phase COUNT number that takes 1 and 3 is a phase switch
        for e in sorted(dev_entities, key=lambda x: str(x.entity_id)):
            if not str(e.entity_id).startswith("number.") or "phase_select" in roles:
                continue
            if not any(re.search(r"(?:^|_)phase_count$|(?:^|_)phases$", w.rsplit("-", 1)[-1])
                       for w in _role_words(e)):
                continue
            caps = getattr(e, "capabilities", None)
            caps = caps if isinstance(caps, dict) else {}
            lo, hi = caps.get("min"), caps.get("max")
            # a range that excludes 1 or 3 is not a phase switch; no range
            # published is taken at the key's word (the values are offered,
            # never written without the user)
            if lo is None or hi is None or (
                    isinstance(lo, (int, float)) and isinstance(hi, (int, float))
                    and lo <= 1 and hi >= 3):
                roles["phase_select"] = {"entity": str(e.entity_id),
                                         "value_1p": "1", "value_3p": "3"}
        live = services_of(domain) if services_of else None
        if live:
            svc = _service_current_role(domain, live,
                                        device_ident=device_ident)
            if svc:
                roles["current_service"] = svc
            roles.update(_service_field_roles(domain, live))
    power = _charging_power(dev_entities, vehicle=vehicle)
    if power:
        roles["power"] = power
    plug = _plugged(dev_entities)
    if plug:
        roles["plug"] = plug
    charging = _charging_now(dev_entities)
    if charging:
        roles["charging"] = charging
    # a status SENSOR read by its options with the charger-status vocabulary
    # SEM's reader already uses (status_enum): options that say "cable in"
    # and "cable out" make it the plug; one that says "charging", the
    # charging state (Ohme's unplugged / plugged_in / charging)
    if not vehicle and ("plug" not in roles or "charging" not in roles):
        from .coordinator.charger_adapters.status_enum import (
            classify_charger_status, is_cable_present,
        )
        for e in sorted(dev_entities, key=lambda x: str(x.entity_id)):
            if not str(e.entity_id).startswith("sensor."):
                continue
            opts = [o.lower() for o in _select_options(e, state_of)]
            if len(opts) < 2:
                # (#1054) no options listed (go-e's ``car_status`` is a plain
                # text sensor). When the device has NO other plug or charging
                # source, a sensor that says it is the CAR's status, whose
                # current state the shared vocabulary knows, is both. A box
                # with a plug sensor keeps it (OpenEVSE's charging_status is
                # not trusted for "charging"); a plain "status" (a diverter's)
                # does not say it is about a car.
                if "plug" in roles or "charging" in roles:
                    continue
                st = state_of(str(e.entity_id)) if state_of else None
                now = str(getattr(st, "state", "") or "").lower()
                says = [w.lower() for w in _role_words(e)] + [str(e.entity_id).lower()]
                car_status = any(re.search(r"(?:^|_)(?:car|vehicle|ev)_?(?:status|state)$", w)
                                 for w in says)
                if now and car_status and is_cable_present(now) is not None:
                    roles["plug"] = str(e.entity_id)
                    roles["charging"] = str(e.entity_id)
                continue
            cable = {is_cable_present(o) for o in opts}
            if "plug" not in roles and True in cable and False in cable:
                roles["plug"] = str(e.entity_id)
            if ("charging" not in roles
                    and any(classify_charger_status(o) == "charging" for o in opts)):
                roles["charging"] = str(e.entity_id)
    # the session and lifetime meters, by their own words (a car's lifetime
    # energy is what it DROVE, not what a charger delivered)
    for e in ([] if vehicle else sorted(dev_entities, key=lambda x: str(x.entity_id))):
        eid = str(e.entity_id)
        if not eid.startswith("sensor.") or _roles_dc(e) != "energy":
            continue
        words = " ".join(_role_words(e)).lower() + " " + eid.lower()
        if re.search(r"day|week|month|year|hour|today|target|added", words):
            continue
        # "session" wins: Zaptec's ``total_charge_power_session`` is a
        # session meter; NRGkick's ``charged_energy`` is this session's and
        # its ``total_charged_energy`` the lifetime one
        if "session" in words:
            roles.setdefault("session_energy", eid)
        elif re.search(r"total|lifetime", words):
            roles.setdefault("total_energy", eid)
        elif re.search(r"(?:^|_)charged_energy\b", words):
            roles.setdefault("session_energy", eid)
    return roles


#: (#1032) the roles that can DRIVE a charger (not the #804 config keys)
_CHARGER_DRIVE_ROLES = ("current_number", "start_stop_buttons", "charge_mode",
                        "charge_switch",
                        "vehicle_charge_current", "vehicle_charge_switch",
                        "current_service")


def _roles_offer(roles: Dict[str, Any]) -> Dict[str, Any]:
    """The charger config these roles fill — the keys the charger pickers
    and the coordinator already use."""
    o: Dict[str, Any] = {}
    if roles.get("power"):
        o["ev_charging_power_sensor"] = roles["power"]
    if roles.get("plug"):
        o["ev_connected_sensor"] = roles["plug"]
    if roles.get("charging"):
        o["ev_charging_sensor"] = roles["charging"]
    if roles.get("session_energy"):
        o["ev_session_energy_sensor"] = roles["session_energy"]
    if roles.get("total_energy"):
        o["ev_total_energy_sensor"] = roles["total_energy"]
    if roles.get("current_number") and not (
            roles.get("current_is_setting")
            and (roles.get("start_stop_buttons") or roles.get("charge_mode"))):
        o["ev_current_control_entity"] = roles["current_number"]
    if roles.get("vehicle_charge_current"):
        o["ev_current_control_entity"] = roles["vehicle_charge_current"]
    if roles.get("vehicle_charge_switch"):
        o["ev_start_stop_entity"] = roles["vehicle_charge_switch"]
    if roles.get("charge_switch"):
        o["ev_start_stop_entity"] = roles["charge_switch"]
    if roles.get("charge_mode"):
        cm = roles["charge_mode"]
        o["ev_charge_mode_entity"] = cm["entity"]
        o["ev_charge_mode_start"] = cm["start"]
        o["ev_charge_mode_stop"] = cm["stop"]
    if roles.get("start_stop_buttons"):
        start, stop = roles["start_stop_buttons"]
        o["ev_start_service"] = "button.press"
        o["ev_start_service_data"] = json.dumps({"entity_id": start})
        o["ev_stop_service"] = "button.press"
        o["ev_stop_service_data"] = json.dumps({"entity_id": stop})
    if roles.get("current_service") and "ev_current_control_entity" not in o:
        o["ev_charger_service"] = roles["current_service"]["service"]
        o["ev_service_param_name"] = roles["current_service"]["param"]
        if roles["current_service"].get("data"):
            o["ev_charger_service_data"] = json.dumps(
                roles["current_service"]["data"], sort_keys=True)
    if roles.get("phase_select"):
        o["_suggested_phase_switch"] = dict(roles["phase_select"])
    return o


def _offer_missing(offer: Dict[str, Any]) -> List[str]:
    missing = []
    if "ev_charging_power_sensor" not in offer:
        missing.append("power reading")
    if not any(k in offer for k in ("ev_current_control_entity",
                                     "ev_start_stop_entity",
                                     "ev_charge_mode_entity",
                                     "ev_start_service",
                                     "ev_charger_service")):
        missing.append("control")
    return missing


def charger_from_near_miss(dev_entities, platform: str,
                          proposed: Optional[Dict[str, Any]] = None, *,
                          roles: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """(#915) The charger config a near miss is one click away from.

    "Entities present, no role matched — please report" is the right thing to
    say when SEM has nothing better. It is the wrong thing to say when SEM
    has just worked out which entity is the current control: then the answer
    is not a bug report, it is *add this charger*.

    So: take the role the roster proposed (the integration's own declared
    key for its charging current), fill the rest from the plain SHAPE of the
    same device's entities — a power sensor, a plug binary_sensor, a
    charging one — and hand back something the user can accept. Returns
    ``{}`` when the essentials are missing, which is when "please report"
    is still the honest line.
    """
    proposed = proposed or {}
    control = proposed.get("ev_current_control") or {}
    current = control.get("entity")
    service = control.get("service")
    # (#1032) a current number that is the box's stored SETTING is not the
    # control when the box offers a live one (start/stop, a charge mode)
    if current and roles and roles.get("current_is_setting") and \
            current == roles.get("current_number") and \
            (roles.get("start_stop_buttons") or roles.get("charge_mode")):
        current = None
    if not current and not service:
        # (#1032) no declared current key: the roles the device's own words
        # carry (start/stop buttons, a charge-mode select, a current service)
        if not roles:
            return {}
        out = _roles_offer(roles)
        apply_charger_discovery_guards(out, dev_entities)
        if _offer_missing(out):
            return {}
        out["id"] = f"{platform}_{str(getattr(dev_entities[0], 'device_id', '') or 'device')}"[:48]
        out["name"] = (describe_domain(platform) or {}).get("name") or platform
        return out
    if current:
        out: Dict[str, Any] = {"ev_current_control_entity": current}
    else:
        # (#956) the control may be a service — KEBA's shape, SEM's own
        # wallbox. (ruflo, 24.09) Offered ONLY as the charger factory can
        # drive it: a global service with the one field the current goes
        # in. Anything else is a proposal to wire by hand, and the
        # proposal row says why.
        if control.get("action") != "per_charger" or not control.get("param"):
            return {}
        out = {"ev_charger_service": service,
               "ev_service_param_name": control["param"]}
        if control.get("data"):
            out["ev_charger_service_data"] = json.dumps(control["data"],
                                                        sort_keys=True)
    own = _own_names(dev_entities)
    # (#1032) the charging power is the whole box's reading, not one phase
    # leg or a clamp on something else (the rig: NRGkick's first power
    # sensor is L1)
    best_power = _charging_power(dev_entities, vehicle=False)
    if best_power:
        out["ev_charging_power_sensor"] = best_power
    for e in dev_entities:
        eid = str(e.entity_id)
        dc = str(getattr(e, "original_device_class", "") or "")
        if eid.startswith("sensor.") and dc == "power":
            out.setdefault("ev_charging_power_sensor", eid)
        elif eid.startswith("binary_sensor.") and dc == "plug":
            out.setdefault("ev_connected_sensor", eid)
        elif eid.startswith("binary_sensor.") and dc in ("power", "running",
                                                         "battery_charging"):
            out.setdefault("ev_charging_sensor", eid)
        elif eid.startswith("sensor.") and dc == "energy" and "session" in own.get(eid, ""):
            out.setdefault("ev_session_energy_sensor", eid)
    # (#1054) what the shape walk above cannot see, the device's roles can:
    # a status sensor read by its state (plug, charging), the charge switch,
    # the lifetime meter. The control the offer was built around stays.
    if roles:
        for k, v in _roles_offer(roles).items():
            if k.startswith("_") or k in ("ev_current_control_entity",
                                          "ev_charger_service",
                                          "ev_service_param_name",
                                          "ev_charger_service_data"):
                continue
            out.setdefault(k, v)
    # (#886/#962) the offer must name the entities SEM would actually use —
    # the same guards the config path applies, or the near miss proposes a
    # charger whose power reading is the box's nameplate.
    apply_charger_discovery_guards(out, dev_entities)
    # Without a power reading SEM cannot see what the car is drawing, and a
    # charger it cannot measure is one it must not steer. Same for the
    # control the offer is built around, if a guard just took it away.
    if "ev_charging_power_sensor" not in out:
        return {}
    if "ev_current_control_entity" not in out and "ev_charger_service" not in out:
        return {}
    out["id"] = f"{platform}_{str(getattr(dev_entities[0], 'device_id', '') or 'device')}"[:48]
    out["name"] = (describe_domain(platform) or {}).get("name") or platform
    return out


def _role_action(role: str) -> Dict[str, Any]:
    """How a proposed role can be accepted: a settable option key, a pointer
    to the charger section, or nothing because SEM resolves it itself."""
    try:
        from .consts import role_lexicon as _lex
    except Exception:  # noqa: BLE001
        return {"config_key": None, "action": "none"}
    if role in getattr(_lex, "OBSERVE_ONLY_ROLES", ()):
        # (#845) a policy selector: SEM names it, watches it, never writes it
        return {"config_key": None, "action": "observe_only"}
    key = _lex.SEM_CONFIG_KEY_FOR_ROLE.get(role)
    if key:
        return {"config_key": key, "action": "set_option"}
    if role in _lex.PER_CHARGER_ROLES:
        return {"config_key": None, "action": "per_charger"}
    if role in _lex.AUTO_RESOLVED_ROLES:
        return {"config_key": None, "action": "automatic"}
    return {"config_key": None, "action": "none"}


def propose_for_installed(registry, *, limit_per_domain: int = 8,
                          configured_entities=None, state_of=None,
                          strategy_values=None, services_of=None,
                          device_ident_of=None) -> list:
    """(#915) Every INSTALLED integration the roster has vocabulary for, with
    the controls it declares matched against this box's own entities.

    The near-miss path (below) only walks ``_EV_CHARGER_PLATFORMS``, so it
    answers the question for chargers and for nothing else: an inverter or a
    battery SEM has no row for was named and then dropped. This walk asks the
    same question of everything installed — "you are running Sigenergy; its
    own repository says it creates a discharge-power limit; here is the
    entity of yours that carries that name".

    Still an INTERSECTION, and still report data: an entity appears only
    because it is in this registry, and nothing here is written anywhere.
    Grouped per domain, not per device — the roles a battery integration
    declares are install-wide, and a per-device split would show the same
    answer once per MPPT string.
    """
    r = _roster()
    if r is None or registry is None:
        return []
    vocab = getattr(r, "ROLE_VOCAB", {}) or {}
    by_domain: Dict[str, list] = {}
    for e in registry.entities.values():
        if e.disabled_by:
            continue
        dom = str(e.platform or "")
        if dom in vocab:
            by_domain.setdefault(dom, []).append(e)
    # (#915) An entity SEM already drives is not news. Without this the
    # Config card told a working Huawei install about six "proposals" for
    # controls it was already using — clutter wearing the shape of help.
    used = {str(e) for e in (configured_entities or ()) if e}
    out = []
    for dom, ents in sorted(by_domain.items()):
        roles = {r: b for r, b in propose_roles_from_roster(
                     ents[:400], dom, state_of=state_of,
                     strategy_values=strategy_values,
                     services_of=services_of,
                     device_ident=(device_ident_of(ents[:400], dom)
                                   if device_ident_of else None)).items()
                 # An entity SEM already drives is not news; nor is a role SEM
                 # resolves by itself every time it looks.
                 if (b.get("entity") or b.get("service")) not in used
                 and b.get("action") != "automatic"}
        if not roles:
            continue
        out.append({
            "domain": dom,
            "roster": describe_domain(dom),
            "proposed_roles": dict(list(roles.items())[:limit_per_domain]),
        })
    return out


#: The four reads a first install cannot start without, and the SEM config
#: key each fills. ``grid_power`` fills the IMPORT slot: SEM's reader
#: auto-detects the sign, so one signed meter is the normal shape.
_SOURCE_ROLE_TO_KEY = {
    "solar_power": "solar_power_sensor",
    "grid_power": "grid_import_power_sensor",
    "battery_power": "battery_power_sensor",
    # The battery's state of charge rides along: without it the four SOC
    # zones that decide every battery behaviour have nothing to read, and a
    # manual install would come up with a working pack and no strategy.
    "battery_soc": "battery_soc_sensor",
    # (#915) …and the two-sided answer, for the brands that give no other:
    # the step accepts either a combined grid sensor or this pair.
    "grid_import_power": "grid_import_power_entity",
    "grid_export_power": "grid_export_power_entity",
}


def propose_energy_sources(hass=None, registry=None) -> Dict[str, Any]:
    """(#915) The solar / grid / battery power sensors, proposed from the
    integrations this box already runs.

    SEM's install has always started at Home Assistant's Energy Dashboard: it
    reads that mapping, and when it is missing or half-filled the install
    ABORTS and sends the user off to configure a different page first. That
    was the only anchor available — until the census could say which
    integrations are installed and the roster could say what each one calls
    its own entities.

    So this is the second anchor, and it points the other way: what do you
    already run, and what does it call the three things SEM needs? Two rungs,
    strongest first — the integration's own declared key, then the plain
    shape of the entity (a power sensor on an energy integration). Both are
    proposals the user confirms in the flow; nothing is bound silently, and
    no sign convention is claimed here (``sensor_reader`` detects that from
    live values, as it always has).

    Returns ``{config_key: {"entity", "why", "domain"}}`` — never a bare
    entity id, because a suggestion the user cannot interrogate is one they
    cannot correct.
    """
    if registry is None and hass is not None:
        try:
            registry = entity_registry.async_get(hass)
        except Exception:  # noqa: BLE001 — a proposal never breaks a flow
            return {}
    if registry is None:
        return {}
    r = _roster()
    vocab = (getattr(r, "ROLE_VOCAB", {}) or {}) if r is not None else {}

    by_domain: Dict[str, list] = {}
    for e in registry.entities.values():
        if e.disabled_by:
            continue
        dom = str(e.platform or "")
        if dom and dom not in _CENSUS_IGNORED:
            by_domain.setdefault(dom, []).append(e)

    out: Dict[str, Any] = {}

    # Rung 1 — the integration's own declared key. Prefer a domain SEM
    # already knows about, then any domain the roster calls energy-shaped.
    def _domain_rank(dom: str) -> tuple:
        row = (getattr(r, "ROSTER", {}) or {}).get(dom, {}) if r else {}
        return (0 if dom in KNOWN_INVERTER_DOMAINS else 1,
                -int(row.get("installs") or 0), dom)

    for dom in sorted(by_domain, key=_domain_rank):
        roles = vocab.get(dom)
        if not roles:
            continue
        proposed = propose_roles_from_roster(by_domain[dom], dom)
        for role, key in _SOURCE_ROLE_TO_KEY.items():
            if key in out or role not in proposed:
                continue
            # (07.09 re-audit) A role the gates DOWNGRADED is not a
            # suggestion: `pair_incomplete` (half a split pair on this
            # device) would otherwise be pre-filled into the install form
            # looking confirmed. Only a role still offering the button.
            if proposed[role].get("action") not in ("set_option", None):
                continue
            out[key] = {"entity": proposed[role]["entity"], "domain": dom,
                        "why": f"declared as {proposed[role]['matched_key']}"}

    # Rung 2 — shape. An entity that is a power sensor on an integration the
    # census calls energy-shaped is a candidate even when nothing declared
    # it, which is how a brand that publishes no vocabulary still gets help.
    for dom in sorted(by_domain, key=_domain_rank):
        ents = by_domain[dom]
        if not _census_energy_shaped(ents):
            continue
        for e in ents:
            eid = str(e.entity_id)
            if not eid.startswith("sensor."):
                continue
            if str(getattr(e, "original_device_class", "")) != "power":
                continue
            low = eid.lower()
            for token, key in (("solar", "solar_power_sensor"),
                               ("pv", "solar_power_sensor"),
                               ("grid", "grid_import_power_sensor"),
                               ("meter", "grid_import_power_sensor"),
                               ("batter", "battery_power_sensor")):
                if key in out or token not in low:
                    continue
                if any(bad in low for bad in ("today", "daily", "total",
                                              "forecast", "l1", "l2", "l3")):
                    continue
                out[key] = {"entity": eid, "domain": dom,
                            "why": "a power sensor on an energy integration"}
                break
    return out


def build_integration_census(hass=None, registry=None, config_domains=None,
                             matched_charger_platforms=None) -> Dict[str, Any]:
    """The census: what is installed, what SEM knows, and the two gaps.

    ``rows_matched_nothing`` — a KNOWN charger platform with registry
    entities but no discovered charger: a detection bug this install just
    surfaced. ``unknown_energy_domains`` — an integration with
    energy-shaped devices SEM has no row for: the next brand row, named
    by the install instead of waiting for an issue."""
    if registry is None and hass is not None:
        registry = entity_registry.async_get(hass)
    entries = [e for e in (registry.entities.values() if registry else [])
               if not e.disabled_by]
    by_domain: Dict[str, list] = {}
    for e in entries:
        dom = str(e.platform or "")
        if dom and dom not in _CENSUS_IGNORED:
            by_domain.setdefault(dom, []).append(e)

    installed = set(by_domain)
    if config_domains:
        installed |= {str(d) for d in config_domains
                      if str(d) not in _CENSUS_IGNORED}
    elif hass is not None:
        try:
            installed |= {
                str(en.domain) for en in hass.config_entries.async_entries()
                if str(en.domain) not in _CENSUS_IGNORED}
        except Exception:  # noqa: BLE001 — the registry half stands alone
            pass

    def _canon(dom: str) -> str:
        # the zaptec_custom tolerance, same rule as the discovery walk
        return "zaptec" if dom.startswith("zaptec") else dom

    known_chargers = known_charger_domains()
    chargers_present = sorted(
        {_canon(d) for d in by_domain if _canon(d) in known_chargers})
    inverters_present = sorted(d for d in installed
                               if d in KNOWN_INVERTER_DOMAINS)

    matched = {_canon(str(x)) for x in (matched_charger_platforms or set())}
    rows_matched_nothing = sorted(d for d in chargers_present
                                  if d not in matched)

    known = known_chargers | KNOWN_INVERTER_DOMAINS
    unknown_energy = sorted(
        dom for dom, ents in by_domain.items()
        if _canon(dom) not in known and _census_energy_shaped(ents))

    return {
        "installed": sorted(installed),
        "known_charger_platforms_present": chargers_present,
        "known_inverter_domains_present": inverters_present,
        "rows_matched_nothing": rows_matched_nothing,
        "unknown_energy_domains": unknown_energy,
        # (#915) The same gap, with a name on it. "eg4_web_monitor" tells the
        # user nothing; "EG4 Web Monitor, 412 installs" tells them what to
        # report and tells us what it would be worth. Additive on purpose —
        # every existing key above is byte-identical, so nothing that reads
        # this census had to change.
        "unknown_energy_domains_named": [
            d for d in (describe_domain(dom) for dom in unknown_energy)
            if d is not None
        ],
        "roster": roster_provenance(),
    }


#: (#887) OnStar2MQTT's own EV vocabulary (src/mqtt.js, read 24.09.2026):
#: the diagnostic elements EV_BATTERY_LEVEL / EV_RANGE / EV_CHARGE_STATE /
#: EV_PLUG_STATE and their ``ev_charging_`` metrics twins. Matched as
#: entity-id TAILS, never by make or model — a 2019 Traverse (ICE) carries
#: none of them, which is exactly how the reporter tells the two apart.
_VEHICLE_TAILS = {
    "vehicle_soc_entity": ("sensor", ("_ev_battery_level", "_ev_charging_battery_level")),
    "vehicle_range_entity": ("sensor", ("_ev_range", "_ev_charging_range")),
    "ev_connected_sensor": ("binary_sensor", ("_ev_plug_state", "_ev_charging_plug_state")),
    "ev_charging_sensor": ("binary_sensor", ("_ev_charge_state", "_ev_charging_charge_state")),
}


def vehicle_from_device(dev_entities) -> Dict[str, Any]:
    """(#887) A CAR on a transport platform, named as a car. Azlinon's
    OnStar vehicles came up as "entities present, no role matched — please
    report": SEM had no idea of a vehicle over MQTT, and the one thing it
    could say was wrong. Identity is the bridge's own EV vocabulary with at
    least a state of charge or a range; the answer is the SOC/range/plug
    sources SEM charges TOWARDS (``vehicle_soc_entity`` & co.). Report data
    and a proposal — never bound by itself. ``{}`` when this is not a car."""
    out: Dict[str, Any] = {}
    for role, (domain, tails) in _VEHICLE_TAILS.items():
        for tail in tails:                       # the plain element first
            for e in dev_entities:
                eid = str(getattr(e, "entity_id", ""))
                if eid.startswith(f"{domain}.") and eid.endswith(tail):
                    out.setdefault(role, eid)
                    break
            if role in out:
                break
    if "vehicle_soc_entity" not in out:
        # (#887, 29.09) Azlinon's bridge publishes the charge level as a
        # SENSOR ``…_charge_state`` in percent, not as ``…_ev_battery_level``.
        # The same word on a BINARY sensor means "charging now", so the
        # sensor counts only when it says it is a level: unit % or device
        # class battery. No unit, no claim.
        for e in dev_entities:
            eid = str(getattr(e, "entity_id", ""))
            if not (eid.startswith("sensor.") and eid.endswith("_charge_state")):
                continue
            unit = (getattr(e, "original_unit_of_measurement", None)
                    or getattr(e, "unit_of_measurement", None))
            dclass = (getattr(e, "original_device_class", None)
                      or getattr(e, "device_class", None))
            if str(unit or "").strip() == "%" or dclass == "battery":
                out["vehicle_soc_entity"] = eid
                break
    if "vehicle_soc_entity" not in out and "vehicle_range_entity" not in out:
        return {}
    # the name is the bridge's own stem: sensor.2024_chevrolet_blazer_ev_ev_range
    # — cut by the tail of the ROLE the entity was found under, so the
    # ``…_charge_state`` level is not cut as ``…_ev_charge_state`` (#887).
    role = "vehicle_range_entity" if "vehicle_range_entity" in out else "vehicle_soc_entity"
    stem = out[role].split(".", 1)[1]
    for tail in [*_VEHICLE_TAILS[role][1], "_charge_state"]:
        if stem.endswith(tail):
            stem = stem[: -len(tail)]
            break
    out["name"] = stem.replace("_", " ").strip().title() or "vehicle"
    return out


def _roles_pass(report, registry, brand_units, configured_entities,
                services_of, state_of, *, include_brand_platforms=False,
                device_ident_of=None) -> None:
    """(#1032) The near-miss walk for the integrations ``_EV_CHARGER_PLATFORMS``
    does not list, then R1 (companion devices) and R4 (a read-only charger
    driven through the one car) across ALL near misses. Mutates ``report``."""
    from .consts import role_lexicon as lex
    brand_platforms = {p for p, _ in _EV_CHARGER_PLATFORMS}
    skip = set(lex.OPAQUE_PLATFORMS) | set(_TRANSPORT_PLATFORMS) | {
        "solar_energy_management"}
    taken = {str(e) for e in (configured_entities or ()) if e}
    for u in brand_units:
        taken |= set(u["entities"])
    entries = [e for e in registry.entities.values() if not e.disabled_by]
    def _brand_or_fork(p: str) -> bool:
        # a fork of a brand integration (``<brand>_custom``) is that brand
        return p in brand_platforms or any(p.startswith(f"{b}_")
                                           for b in brand_platforms)
    # The detection report's own brand walk reports a brand device it could
    # not map as a near miss; discovery has no such walk, so it reads those
    # devices here (a unit a brand path DID map is in ``taken``).
    units = group_entities_by_unit(
        [e for e in entries
         if str(e.platform or "") not in skip
         and (include_brand_platforms
              or not _brand_or_fork(str(e.platform or "")))])
    entry_of: Dict[Any, Optional[str]] = {}
    roles_of: Dict[Any, Dict[str, Any]] = {}
    for key, ents in units.items():
        entry_of[key] = next((e.config_entry_id for e in ents
                              if isinstance(getattr(e, "config_entry_id", None), str)), None)
        if taken & {str(e.entity_id) for e in ents}:
            continue
        platform = str(ents[0].platform or "")
        _ident = device_ident_of(ents, platform) if device_ident_of else None
        roles = read_charger_roles(ents, platform, services_of=services_of,
                                   state_of=state_of, device_ident=_ident)
        roles_of[key] = roles
        offer = _roles_offer(roles)
        if roles.get("vehicle"):
            if roles.get("vehicle_charge_current"):
                report["vehicles"].append({
                    "platform": platform, "device_id": unit_device_id(key),
                    "note": "vehicle", "charge_control": offer,
                })
            continue
        has_control = any(k in roles for k in _CHARGER_DRIVE_ROLES)
        if not (roles.get("power") and (roles.get("plug") or has_control)):
            continue
        # a device that also speaks for a GENERATOR (PV, an inverter) is
        # energy hardware with a charger's word in it — Tesla's energy site
        # reports its wall connector's state — not a charger itself
        words = " ".join(w.lower() for e in ents for w in _role_words(e))
        if any(m in words for m in lex.GENERATOR_MARKERS):
            continue
        apply_charger_discovery_guards(offer, ents)
        missing = _offer_missing(offer)
        nm = {
            "platform": platform, "device_id": unit_device_id(key),
            "entities": [{"entity": str(e.entity_id),
                          "domain": str(e.entity_id).split(".", 1)[0],
                          "device_class": getattr(e, "original_device_class", None)}
                         for e in ents],
            "note": "a charger SEM has no row for",
            "roster": describe_domain(platform),
            "proposed_roles": propose_roles_from_roster(
                ents, platform, services_of=services_of, device_ident=_ident),
            "suggested_charger": {},
            "charger_roles": sorted(k for k in roles
                                    if k not in ("vehicle", "current_is_setting")),
            "missing": missing,
        }
        if not missing:
            offer["id"] = f"{platform}_{unit_device_id(key) or 'device'}"[:48]
            offer["name"] = (describe_domain(platform) or {}).get("name") or platform
            nm["suggested_charger"] = offer
        report["near_misses"].append(nm)

    # R1 — a device with no power reading of its own, on the same config
    # entry as a charger near miss, is that charger's companion; its live
    # current number replaces a charger's stored setting.
    dev_entry: Dict[Optional[str], Optional[str]] = {}
    dev_entities: Dict[Optional[str], list] = {}
    for ukey, uents in group_entities_by_unit(entries).items():
        did = unit_device_id(ukey)
        if did:
            dev_entities[did] = uents
            dev_entry[did] = next(
                (e.config_entry_id for e in uents
                 if isinstance(getattr(e, "config_entry_id", None), str)), None)
    chargerish = [n for n in report["near_misses"]
                  if n.get("suggested_charger") or n.get("charger_roles")]
    companions = set()
    for n in chargerish:
        my_entry = dev_entry.get(n.get("device_id"))
        if not my_entry:
            continue
        offered = {o.get("device_id") for o in report["near_misses"]
                   if o.get("suggested_charger")}
        for did, ents in sorted(dev_entities.items()):
            # every device of the same config entry, not only those already
            # reported: discovery's own pass sees the installation too
            if (did == n.get("device_id") or dev_entry.get(did) != my_entry
                    or did in offered):
                continue
            # a companion measures no power at all: a device with power
            # sensors is a meter or another machine (a Harvi, an Eddi)
            if any(str(e.entity_id).startswith("sensor.")
                   and _roles_dc(e) == "power" for e in ents):
                continue
            n.setdefault("companions", []).append(
                {"device_id": did, "entities": len(ents)})
            companions.add(did)
            live = _current_number_role(ents)
            sc = n.get("suggested_charger") or {}
            if (live and not _is_stored_setting(ents, live) and sc
                    and "ev_current_control_entity" not in sc):
                sc["ev_current_control_entity"] = live
    report["near_misses"] = [n for n in report["near_misses"]
                             if n.get("device_id") not in companions]

    # R4 — a charger that only reports, driven through the one car that has
    # its own charge control; two cars are a question, not a guess
    cars = [v for v in report["vehicles"] if v.get("charge_control")]
    for n in report["near_misses"]:
        if n.get("suggested_charger") or n.get("missing") != ["control"]:
            continue
        if len(cars) == 1:
            ents = [e for e in entries if str(e.entity_id) in
                    {x["entity"] for x in n.get("entities", ())}]
            roles = read_charger_roles(ents, n["platform"], services_of=None,
                                       state_of=state_of)
            offer = _roles_offer(roles)
            cc = cars[0]["charge_control"]
            for k in ("ev_current_control_entity", "ev_start_stop_entity"):
                if cc.get(k):
                    offer[k] = cc[k]
            if not _offer_missing(offer):
                offer["id"] = f"{n['platform']}_{n.get('device_id') or 'device'}"[:48]
                offer["name"] = (describe_domain(n["platform"]) or {}).get("name") \
                    or n["platform"]
                n["suggested_charger"] = offer
                n["paired_vehicle"] = cars[0].get("device_id")
                n["missing"] = []
        elif len(cars) > 1:
            n["choose_vehicle"] = sorted(str(c.get("device_id")) for c in cars)


def build_detection_report(hass: Optional[HomeAssistant] = None,
                           registry=None, configured_entities=None,
                           strategy_values=None,
                           configured_chargers=None) -> Dict[str, Any]:
    """(#814 Pillar B) Detection that shows its work.

    (#1054 follow-up) ``configured_chargers`` — the charger dicts SEM
    drives. A unit one of them points at is a CONFIGURED charger row
    (``configured: True``), never a near miss and never an offer: weindler's
    go-e sat on the card as "entities present, no role matched" with a
    "create this charger" button beside the charger SEM was already driving.

    The same walk as ``discover_all_ev_chargers_from_registry`` — platform
    by platform, device by device, the same brand functions — but the
    answer carries EVIDENCE: which entity took which role (and what it
    is: domain + device_class), which entities on that device were left
    unmapped, and the class #803/#802 made visible: platforms whose
    entities were present but no role matched (near-misses). Today those
    detect silently as "no charger"; in the report the user sees the gap
    instead of broken behavior.

    JSON-serialisable; read-only; brand logic untouched.
    """
    from datetime import datetime, timezone

    if registry is None:
        registry = entity_registry.async_get(hass)
    entries = list(registry.entities.values())

    def _describe(e) -> Dict[str, Any]:
        eid = str(e.entity_id)
        return {
            "entity": eid,
            "domain": eid.split(".", 1)[0],
            "device_class": getattr(e, "original_device_class", None),
        }

    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scanned_platforms": [p for p, _ in _EV_CHARGER_PLATFORMS],
        "chargers": [],
        "near_misses": [],
        # (#887) cars found on a transport platform, named as cars
        "vehicles": [],
        "disabled_ignored": [],
        # (#964) entities of a device-less platform that no unit could claim
        # — dropped from the role walk on purpose, never silently.
        "unattributed": [],
        # (#1036) devices an integration ships beside its charger that only
        # measure — Easee's Equalizer — named here instead of offered as a
        # second charger.
        "meters": [],
    }

    # (#964) the entities behind each charger row — the pairing key the
    # prober comparison uses, never written into the report itself.
    brand_units: List[Dict[str, Any]] = []
    # (#1032) what the role reader needs: live select options once HA runs,
    # and each service's fields
    _hass_running = (bool(getattr(hass, "is_running", True))
                     if hass is not None else False)
    _roles_state_of = ((lambda eid: hass.states.get(eid))
                       if (hass is not None and _hass_running
                           and hasattr(hass, "states")) else None)
    _roles_services = _services_of(hass)

    # (#1054 follow-up) What SEM drives, first. The unit behind each
    # configured charger is reported as that charger — the brand walk and
    # the role pass below never see it, so it cannot come back as a near
    # miss with a button to create it again.
    _live_units = group_entities_by_unit([e for e in entries if not e.disabled_by])
    _unit_of_entity: Dict[str, Any] = {
        str(e.entity_id): key for key, ents in _live_units.items() for e in ents}
    _by_eid = {str(e.entity_id): e for e in entries}
    configured_charger_entities: set = set()
    for cfg in (configured_chargers or ()):
        if not isinstance(cfg, dict) or not cfg.get("id"):
            continue
        mine = charger_entity_ids(cfg)
        if not mine:
            continue
        configured_charger_entities |= mine
        unit_key = next((_unit_of_entity[eid] for eid in sorted(mine)
                         if eid in _unit_of_entity), None)
        first = next((_by_eid[eid] for eid in sorted(mine) if eid in _by_eid), None)
        mapped: Dict[str, Any] = {}
        for key, val in cfg.items():
            # the wiring only — a mode or a priority is a setting, not a role
            if key not in _CONFIGURED_ROW_KEYS or not val:
                continue
            e = _by_eid.get(str(val))
            mapped[key] = _describe(e) if e is not None else {"value": val}
        control = cfg.get("ev_charger_service")
        control = (f"service: {control}" if control
                   else "number entity" if cfg.get("ev_current_control_entity")
                   else "start/stop only" if cfg.get("ev_start_stop_entity")
                   else "see mapping")
        row = {
            "platform": str(cfg.get("_platform")
                            or (first.platform if first is not None else "")
                            or "configured"),
            "device_id": unit_device_id(unit_key) if unit_key is not None
            else (str(getattr(first, "device_id", "") or "") or None),
            "unit": unit_label(unit_key) if unit_key is not None else None,
            "mapped": mapped,
            "unmapped": [],
            "control": control,
            "configured": True,
            "charger_id": str(cfg["id"]),
            "name": cfg.get("name"),
        }
        report["chargers"].append(row)
        brand_units.append({
            "platform": row["platform"], "unit": row["unit"],
            "device_id": row["device_id"], "entities": set(mine),
        })
    configured_entities = set(configured_entities or ()) | configured_charger_entities

    def _same_brand(a: str, b: str) -> bool:
        """(#915) ``zaptec_sim`` and ``zaptec_custom`` are the brand
        ``zaptec`` — the tolerance the discovery walk and the census apply."""
        a, b = str(a or ""), str(b or "")
        return a == b or a.startswith(f"{b}_") or b.startswith(f"{a}_")

    for platform, discover_fn in _EV_CHARGER_PLATFORMS:
        def _matches(ep: str, _this=platform) -> bool:
            if _this == "zaptec":
                return ep == "zaptec" or ep.startswith("zaptec_")
            return ep == _this
        plat_entities = [e for e in entries if _matches(str(e.platform or ""))]
        if not plat_entities:
            continue
        for e in plat_entities:
            if e.disabled_by:
                report["disabled_ignored"].append(str(e.entity_id))
        live = [e for e in plat_entities if not e.disabled_by]
        # (#964) the same unit grouping as the config path — a device-less
        # platform is not one charger just because the registry has no
        # device id for it.
        devices = group_entities_by_unit(live)
        attributed = {str(e.entity_id) for g in devices.values() for e in g}
        for e in live:
            if str(e.entity_id) not in attributed:
                report["unattributed"].append(_describe(e))
        found = {}
        for unit_key, dev_entities in devices.items():
            mapping = _discover_unit(discover_fn, dev_entities) or {}
            # (#886/#962) mirror the config path's guards so the
            # diagnostics report shows the entities SEM will actually use.
            apply_charger_discovery_guards(mapping, dev_entities)
            found[unit_key] = (mapping, dev_entities)
        # (#1036) the config path's rule, so the report shows what the flow
        # will offer: a meter beside a charger is listed as a meter.
        meters = meters_beside_chargers(
            platform, found, [e for e in plat_entities if e.disabled_by])
        # (#1036) near misses wait for the whole platform: whether this brand
        # has a charger is known only once every unit has been mapped.
        pending_near: List[Dict[str, Any]] = []
        for unit_key, (mapping, dev_entities) in found.items():
            device_id = unit_device_id(unit_key)
            # (#1054 follow-up) a unit SEM already drives was reported above
            if configured_charger_entities & {str(e.entity_id) for e in dev_entities}:
                continue
            # (#1054) the config path's rule: a brand mapping with no charger
            # sign — no power, no plug, no charging state, no control — found
            # a meter, not a charger. The report said "charger — see mapping"
            # for go-e's lone total-energy sensor; leave it to the roles.
            if mapping and not any(mapping.get(k) for k in _CHARGER_SIGNS):
                mapping = {}
            if unit_key in meters:
                report["meters"].append({
                    "platform": str(dev_entities[0].platform or platform),
                    "device_id": device_id,
                    "unit": unit_label(unit_key),
                    "entities": [_describe(e) for e in dev_entities],
                    "note": "a meter beside a charger, not a charger",
                })
                continue
            # (ruflo, 24.09 / #956) a hand-written brand function that finds
            # sensors but NO control claimed the device and the roster never
            # got to speak — go-eCharger's box has no current number, only a
            # service. When the roster can name a control, this is a near
            # miss with an offer, not a charger with "see mapping".
            # (ruflo pass 2) …and a mapping that carries a START/STOP control
            # is a deliberate, honest charger — Zaptec reports its resume
            # button ALONE when the only current-like number is the site's
            # available_current (#804: never SEM's throttle). Wiping that
            # would let the roster offer the wrong-scope number one click
            # away. Only a sensors-only mapping falls through.
            if (mapping and not mapping.get("ev_current_control_entity")
                    and not mapping.get("ev_charger_service")
                    and not mapping.get("ev_start_stop_entity")):
                _ctl = propose_roles_from_roster(
                    dev_entities, platform, services_of=_services_of(hass)
                ).get("ev_current_control") or {}
                if _ctl.get("entity") or _ctl.get("service"):
                    mapping = {}
            # (#804 B4c) the report path re-runs discovery per DEVICE, so the
            # installation-sibling threshold scan from the config path never
            # fires here — attach the same suggestion so the diagnostics
            # show what the flow will suggest.
            if mapping and platform == "zaptec":
                for _e in live:
                    _uid = str(getattr(_e, "unique_id", "") or "").lower()
                    if (str(_e.entity_id).startswith("number.")
                            and _uid.endswith(
                                "three_to_one_phase_switch_current")):
                        mapping["_suggested_phase_switch"] = {
                            "entity": str(_e.entity_id),
                            "value_1p": "32", "value_3p": "0",
                        }
                        break
            by_id = {str(e.entity_id): e for e in dev_entities}
            if not mapping:
                # (#915) A near miss is meant to read "a brand we almost
                # support — please report". On the shared ``mqtt`` transport
                # it was reading that over a Zigbee coordinator: the .46 rig
                # showed 24 near-misses, most of them zigbee2mqtt bridge
                # buttons, each asking the user to file an issue about a
                # device SEM would never drive. A transport-platform device
                # earns the line only if something about it is actually
                # energy-shaped — a power sensor with a plug or a current
                # control (the census rule), or a role the roster proposed.
                # (#887) a CAR is not a near miss and not unknown hardware
                _vehicle = vehicle_from_device(dev_entities)
                if _vehicle:
                    report["vehicles"].append({
                        "platform": platform,
                        "device_id": device_id,
                        "note": "vehicle",
                        **_vehicle,
                    })
                    continue
                _ident = _device_ident_of(hass)
                _ident = _ident(dev_entities, platform) if _ident else None
                _proposed = propose_roles_from_roster(
                    dev_entities, platform, services_of=_services_of(hass),
                    device_ident=_ident)
                _roles = read_charger_roles(
                    dev_entities, platform, services_of=_roles_services,
                    state_of=_roles_state_of, device_ident=_ident)
                if (platform in _TRANSPORT_PLATFORMS and not _proposed
                        and not _census_energy_shaped(dev_entities)):
                    continue
                # (#915) An integration whose charger SEM already drives is
                # not "almost supported". A brand commonly ships a second,
                # installation-level device — Zaptec's carries the site's
                # available-current and phase registers — and on the .46 rig
                # that device was the last near miss standing, telling the
                # owner of a fully detected charger to report it.
                # ``zaptec_sim`` and ``zaptec_custom`` are the same brand as
                # ``zaptec`` — the tolerance the discovery walk and the census
                # already apply, applied here too. Comparing the raw platform
                # left the fork's installation device on the card as the last
                # near miss (.46). (#1036) Asked once the platform is done,
                # below: asked here, it only saw the chargers mapped BEFORE
                # this device, so a site device listed first still read as
                # "almost supported". A transport is not a brand: there the
                # per-device answer stays as it was.
                near = {
                    "platform": platform,
                    "device_id": device_id,
                    "entities": [_describe(e) for e in dev_entities],
                    "note": "entities present, no role matched",
                    # (#915) "a near miss is a brand we almost support" — so
                    # say which brand, and which of its own declared keys
                    # these entities match. REPORT DATA ONLY: never merged
                    # into ``mapping``, never written anywhere. The user
                    # confirms a proposal in the pickers; SEM binds nothing
                    # it guessed.
                    "roster": describe_domain(platform),
                    "proposed_roles": _proposed,
                    # (#915) What the user can DO about this near miss.
                    # A charger SEM can describe well enough to drive is an
                    # offer, not a bug report.
                    "suggested_charger": charger_from_near_miss(
                        dev_entities, platform, _proposed, roles=_roles),
                    "charger_roles": sorted(k for k in _roles
                                            if k not in ("vehicle",
                                                         "current_is_setting")),
                    "missing": _offer_missing(_roles_offer(_roles)),
                }
                if platform not in _TRANSPORT_PLATFORMS:
                    pending_near.append(near)
                elif not any(_same_brand(c.get("platform"), platform)
                             for c in report["chargers"]):
                    report["near_misses"].append(near)
                continue
            mapped: Dict[str, Any] = {}
            used = set()
            for key, val in mapping.items():
                if key.startswith("_"):
                    continue
                e = by_id.get(str(val))
                if e is not None:
                    mapped[key] = _describe(e)
                    used.add(str(val))
                else:
                    mapped[key] = {"value": val}   # a service name, param, …
            control = mapping.get("ev_charger_service")
            control = (f"service: {control}" if control
                       else "number entity" if mapping.get("ev_current_control_entity")
                       # (ruflo pass 2) a start/stop-only charger is a known
                       # shape, not an unknown control — say so
                       else "start/stop only" if mapping.get("ev_start_stop_entity")
                       else "see mapping")
            row = {
                "platform": str(dev_entities[0].platform or platform),
                "device_id": device_id,
                "unit": unit_label(unit_key),
                "mapped": mapped,
                "unmapped": [_describe(e) for e in dev_entities
                             if str(e.entity_id) not in used],
                "control": control,
                "configured": False,
            }
            # (#804 B4c) the one underscore key that IS report data.
            if mapping.get("_suggested_phase_switch"):
                row["suggested_phase_switch"] = mapping["_suggested_phase_switch"]
            report["chargers"].append(row)
            # (#964) what this unit is made of, for the prober pairing below
            brand_units.append({
                "platform": row["platform"], "unit": row["unit"],
                "device_id": device_id,
                "entities": {str(e.entity_id) for e in dev_entities},
            })
        if not any(_same_brand(c.get("platform"), platform)
                   for c in report["chargers"]):
            report["near_misses"].extend(pending_near)

    # (#1032) the same near-miss question asked of every integration the
    # brand walk does not cover — by the roles its own words carry. A charger
    # SEM has no row for lands in ``near_misses`` with its offer; a car that
    # charges lands in ``vehicles`` with its charge control. Units holding an
    # entity SEM already binds or the user configured are not news (the KEBA
    # lesson, .175 02.10: a device-less box has no device id to match on).
    try:
        _roles_pass(report, registry, brand_units, configured_entities,
                    _roles_services, _roles_state_of,
                    device_ident_of=_device_ident_of(hass))
    except Exception:  # noqa: BLE001 — a new reader never costs the report
        _LOGGER.debug("charger role pass failed", exc_info=True)

    # (#814 Pillar A) the prober runs beside the brand walk. A candidate on
    # a device no brand function claimed = "prober_only" (a shape we could
    # support but have no brand row for); a brand-detected device the
    # prober cannot see = "brand_only" (a brand function knows something
    # the generic rules don't — or the rules are wrong). Both are data.
    try:
        cands = probe_charger_candidates(registry=registry)
    except Exception:  # noqa: BLE001 — the prober must never cost the report
        cands = []
    report["prober_candidates"] = cands
    # (#964) Pair the two findings by the ENTITIES they claim, the way
    # ``config_flow._charger_already_installed`` fingerprints a charger.
    # The device id cannot do it — two device-less boxes both report
    # ``None`` — and neither can the grouping key: the prober and the
    # binding paths deliberately group an unproven split differently, so
    # keying on it would report a disagreement on every device-less install
    # SEM has, which is exactly the population this section is watching.
    # One to one, largest overlap first: a brand row that happens to span
    # two boxes must not absorb both candidates and report agreement where
    # the two sides plainly disagree.
    overlaps = sorted(
        ((len({str(v) for v in cand.get("roles", {}).values()}
              & unit["entities"]), bi, ci)
         for bi, unit in enumerate(brand_units)
         for ci, cand in enumerate(cands)),
        key=lambda t: (-t[0], t[1], t[2]))
    paired_brand, paired_prober = set(), set()
    for shared, bi, ci in overlaps:
        if shared and bi not in paired_brand and ci not in paired_prober:
            paired_brand.add(bi)
            paired_prober.add(ci)
    report["disagreements"] = (
        [{"kind": "prober_only", "platform": c["platform"], "unit": c["unit"],
          "device_id": c["device_id"]}
         for ci, c in sorted(enumerate(cands), key=lambda t: str(t[1]["unit"]))
         if ci not in paired_prober]
        + [{"kind": "brand_only", "platform": u["platform"], "unit": u["unit"],
            "device_id": u["device_id"]}
           for bi, u in sorted(enumerate(brand_units),
                               key=lambda t: str(t[1]["unit"]))
           if bi not in paired_brand]
    )
    # (#848) the census rides every report — what is installed, what SEM
    # knows, and the two gap lines that turn installs into detection
    # findings.
    try:
        # (#1054 follow-up) a near miss whose offer is complete IS a match —
        # the roles named every part; weindler's census listed go-e under
        # "matched nothing" beside the offer that drove his box.
        report["census"] = build_integration_census(
            hass=hass, registry=registry,
            matched_charger_platforms=(
                {c.get("platform") for c in report["chargers"]}
                | {n.get("platform") for n in report["near_misses"]
                   if n.get("suggested_charger") and not n.get("missing")}))
    except Exception:  # noqa: BLE001 — a census never costs the report
        report["census"] = None
    # (#915) The same question asked of EVERYTHING installed, not only of the
    # charger platforms the near-miss walk covers: which controls does each
    # installed integration's own repository say it creates, and which of
    # this box's entities carry those names. Report data, intersection only.
    try:
        # (#915) Judge the live state only once HA has finished starting:
        # before that, an absent state means "not loaded YET", and refusing
        # every button on a fresh boot is worse than offering them unjudged
        # — the post-startup hook rebuilds this report with the states in.
        _running = bool(getattr(hass, "is_running", True)) if hass is not None else False
        _state_of = (
            (lambda eid: hass.states.get(eid)) if (hass is not None and _running)
            else None)
        report["roster_proposals"] = propose_for_installed(
            registry, configured_entities=configured_entities,
            state_of=_state_of, strategy_values=strategy_values,
            services_of=_services_of(hass),
            device_ident_of=_device_ident_of(hass))
        # (#915) whether proposals were judged against live states, so the
        # coordinator can rebuild an unjudged (boot-time) report once HA is up
        report["judged"] = bool(_state_of is not None)
        report["not_loaded"] = sum(
            1 for p in report["roster_proposals"]
            for v in p.get("proposed_roles", {}).values()
            if v.get("action") == "not_loaded")
    except Exception:  # noqa: BLE001 — a prior never costs the report
        report["roster_proposals"] = []
    return report


def discover_ev_charger_from_registry(hass: HomeAssistant, *,
                                      include_roles: bool = False) -> Dict[str, str]:
    """Auto-discover EV charger config from known integrations via entity registry.

    Backward-compatible wrapper: returns the first detected charger.

    (#1032) A charger found only by the roster's roles is returned only when
    ``include_roles`` — a form the user confirms. Setup's silent reseed and
    the coordinator's late retry keep to the brand paths: a role-found
    charger is never saved or driven without the user accepting it.

    Returns:
        Dict with config keys (ev_connected_sensor, ev_charging_sensor, etc.)
        Only includes keys where entities were found.
    """
    all_chargers = discover_all_ev_chargers_from_registry(hass)
    if not include_roles:
        all_chargers = [c for c in all_chargers if c.get("_found_by") != "roles"]
    return all_chargers[0] if all_chargers else {}


def _discover_keba(entities) -> Dict[str, str]:
    """Discover EV charger config from KEBA integration entities."""
    result: Dict[str, str] = {}

    own = _own_names(entities)
    for entry in entities:
        eid = entry.entity_id
        name = own.get(str(eid), "")
        dc = entry.original_device_class

        if eid.startswith("binary_sensor.") and dc == "plug":
            result["ev_connected_sensor"] = eid
        if eid.startswith("binary_sensor.") and dc == "power":
            result["ev_charging_sensor"] = eid
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "total" in name:
            result["ev_total_energy_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "session" in name:
            result["ev_session_energy_sensor"] = eid
        if eid.startswith("sensor.") and dc == "current":
            result["ev_current_sensor"] = eid

    if result:
        result["ev_charger_service"] = "keba.set_current"
        result["ev_service_param_name"] = "current"
        target = result.get("ev_connected_sensor")
        if target:
            result["ev_charger_service_entity_id"] = target

    return result


def _discover_easee(entities) -> Dict[str, str]:
    """Discover EV charger config from Easee integration."""
    result: Dict[str, str] = {}
    device_id = None
    own = _own_names(entities)
    for entry in entities:
        eid = entry.entity_id
        name = own.get(str(eid), "")
        dc = entry.original_device_class
        # Easee uses sensor (not binary_sensor) for status (#68)
        if eid.startswith("sensor.") and "status" in name and dc is None:
            result.setdefault("ev_connected_sensor", eid)
            result.setdefault("ev_charging_sensor", eid)
            if entry.device_id:
                device_id = entry.device_id
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
            if entry.device_id:
                device_id = entry.device_id
        if eid.startswith("sensor.") and dc == "energy" and "total" in name:
            result["ev_total_energy_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "session" in name:
            result["ev_session_energy_sensor"] = eid
    if result:
        # Use dynamic limit (preferred, no flash wear) over max_limit
        result["ev_charger_service"] = "easee.set_charger_dynamic_limit"
        result["ev_service_param_name"] = "current"
        if device_id:
            result["ev_service_device_id"] = device_id
        # Start/stop via action_command service
        result["ev_start_service"] = "easee.action_command"
        result["ev_start_service_data"] = '{"action_command": "resume"}'
        result["ev_stop_service"] = "easee.action_command"
        result["ev_stop_service_data"] = '{"action_command": "pause"}'
    return result


def _discover_goecharger(entities) -> Dict[str, str]:
    """Discover EV charger config from go-eCharger integration."""
    result: Dict[str, str] = {}
    own = _own_names(entities)
    for entry in entities:
        eid = entry.entity_id
        name = own.get(str(eid), "")
        dc = entry.original_device_class
        if eid.startswith("binary_sensor.") and dc == "plug":
            result["ev_connected_sensor"] = eid
        if eid.startswith("binary_sensor.") and "charg" in name:
            result["ev_charging_sensor"] = eid
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "total" in name:
            result["ev_total_energy_sensor"] = eid
        if eid.startswith("number.") and ("amp" in name or "current" in name):
            result["ev_current_control_entity"] = eid
    return result


def _discover_wallbox(entities) -> Dict[str, str]:
    """Discover EV charger config from Wallbox integration."""
    result: Dict[str, str] = {}
    own = _own_names(entities)
    for entry in entities:
        eid = entry.entity_id
        name = own.get(str(eid), "")
        dc = entry.original_device_class
        if eid.startswith("binary_sensor.") and "plug" in name:
            result["ev_connected_sensor"] = eid
        if eid.startswith("binary_sensor.") and "charg" in name:
            result["ev_charging_sensor"] = eid
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "total" in name:
            result["ev_total_energy_sensor"] = eid
        if eid.startswith("number.") and "current" in name:
            result["ev_current_control_entity"] = eid
        # Wallbox pause/resume switch
        if eid.startswith("switch.") and "pause" in name:
            result["ev_start_stop_entity"] = eid
    return result


def _discover_zaptec(entities) -> Dict[str, str]:
    """Discover one control-capable Zaptec charger device.

    Zaptec also exposes installation/site aggregate devices. Those may have a
    total-power sensor but are not chargers and must not seed ``ev_chargers``.
    Some custom integration versions omit ``original_device_class``; only
    Zaptec-scoped, explicit entity-id patterns are used as fallback.
    """
    result: Dict[str, str] = {}
    device_id = None
    own = _own_names(entities)
    for entry in entities:
        eid = entry.entity_id
        if entry.device_id and not device_id:
            device_id = entry.device_id
        dc = entry.original_device_class
        # (#1035) the words the integration wrote, not the device name
        name = own.get(str(eid), "").lower()
        # (#804/#562) unique_id first, entity-id substring as fallback:
        # entity ids are localised (a Dutch install says kabel/laden, not
        # cable/charging) while the integration's unique_ids keep fixed
        # English keys in every language.
        _uid = str(getattr(entry, "unique_id", "") or "").lower()
        if eid.startswith("binary_sensor.") and (
            _uid.endswith("cable_connected") or _uid.endswith("_connected")
            or "cable" in name or "connect" in name
        ):
            result["ev_connected_sensor"] = eid
        if eid.startswith("binary_sensor.") and (
            _uid.endswith("_charging") or "charg" in name
        ):
            result["ev_charging_sensor"] = eid
        if eid.startswith("sensor.") and (
            dc == "power" or _uid.endswith("charge_power")
            or ("power" in name and "energy" not in name and "kwh" not in name)
        ):
            result["ev_charging_power_sensor"] = eid
            if entry.device_id:
                device_id = entry.device_id
        if eid.startswith("sensor.") and (
            (dc == "energy" and ("total" in name or "session" in name))
            or "meter_value_kwh" in name
            or "signed_meter_value_kwh" in name
            or "total_charge_energy" in name
        ):
            if "session" in name:
                result["ev_session_energy_sensor"] = eid
            else:
                result["ev_total_energy_sensor"] = eid
        # (#804) Roles by registry unique_id FIRST — the #562 lesson.
        # Entity ids are localised and owner-renameable: @coppe218's Dutch
        # install names its numbers ``…_beschikbare_stroom`` and
        # ``…_maximale_laadstroom``, so "current" appears in none of them and
        # the substring fallbacks below see nothing. The integration builds
        # unique_ids as ``{object_id}_{key}`` with fixed English keys, so the
        # suffix identifies the role in every language.
        uid = _uid
        if eid.startswith("number."):
            # The throttle is the CHARGER-level max current — measured on the
            # reporter's hardware: writing 0 is a soft pause and raising it
            # resumes automatically (his half-hour hold test), which is
            # exactly SEM's stop=0/start=N model and how EVCC drives the
            # brand. The INSTALLATION's available_current is deliberately
            # NOT a candidate: that is the user's per-phase grid guard
            # (3×25 A on the reporting install), and a write there
            # constrains every charger on the installation.
            if uid.endswith("charger_max_current"):
                result["ev_current_control_entity"] = eid
            elif ("ev_current_control_entity" not in result
                    and "current" in name
                    and "available_current" not in uid
                    and "min_current" not in uid
                    and not uid.endswith("charger_min_current")):
                # entity-id fallback for integration builds whose unique_ids
                # differ — still never the installation limit or the min bound
                result["ev_current_control_entity"] = eid
        if eid.startswith("button.") and (
            "resume" in name or uid.endswith("resume_charging")
        ):
            result["ev_start_stop_entity"] = eid

    # Site/installation aggregates commonly contain only power/energy. A real
    # charger must expose at least one charger-identity/control entity — and
    # at least one STATE sensor: a resume button alone would register a
    # charger SEM can command but never read (#695/#698 discovery class).
    identity_keys = {
        "ev_connected_sensor",
        "ev_charging_sensor",
        "ev_current_control_entity",
        "ev_start_stop_entity",
    }
    state_keys = {"ev_connected_sensor", "ev_charging_sensor"}
    if not identity_keys.intersection(result):
        return {}
    if not state_keys.intersection(result):
        return {}

    # (#804, 25.08) NO service fallback. ``zaptec.limit_current`` writes the
    # INSTALLATION's available_current — the user's per-phase grid guard
    # (3×25 A on the reporting install), shared by every charger on the
    # installation and, per the reporter's EVCC layering, never SEM's
    # throttle. A charger without its charger-level max-current number is
    # honestly reported without control rather than silently steered through
    # a limit that constrains the whole site. #695/#698: a charger SEM can
    # command but not read was the discovery class; one SEM commands through
    # the WRONG SCOPE is worse.
    return result


# ── (#814 Pillar A) brands as DATA ─────────────────────────────────────
# A brand row names, per SEM role, the (domain, device_class-or-None,
# name-hints) an entity must match. The generic matcher below applies it.
# Two existing functions (ChargePoint, Heidelberg) were identical rule
# sets and are now rows; others follow as their quirks allow. A new brand
# with no quirks is a row plus the mandatory pipeline test — no function.
_ROLE = Dict[str, Any]

_BRAND_HINTS: Dict[str, List[_ROLE]] = {
    "chargepoint": [
        {"role": "ev_connected_sensor", "domain": "binary_sensor",
         "names": ("connect", "plug")},
        {"role": "ev_charging_sensor", "domain": "binary_sensor",
         "names": ("charg",)},
        {"role": "ev_charging_power_sensor", "domain": "sensor",
         "device_class": "power"},
        {"role": "ev_total_energy_sensor", "domain": "sensor",
         "device_class": "energy", "names": ("total",)},
        {"role": "ev_session_energy_sensor", "domain": "sensor",
         "device_class": "energy", "names": ("session",)},
        {"role": "ev_current_control_entity", "domain": "number",
         "names": ("amperage", "current")},
    ],
    # (#802) Fronius / go-e Wattpilot. SEM used to match a lookalike
    # Energy-Dashboard device instead, so the EV tile pointed at the wrong
    # thing until the reporter repaired it by hand. First brand added as a
    # pure data row — no function (#814).
    # (#816) GARO — proven live in #700/#748 through the generic path; the
    # entity names below are the reporter's own. The 6 A floor is carried by
    # the wrapper (_discover_garo), not a rule: it is a hardware constant,
    # not an entity.
    "garo": [
        {"role": "ev_start_stop_entity", "domain": "switch",
         "names": ("laddbox", "charging", "on_off")},
        {"role": "ev_current_control_entity", "domain": "number",
         "device_class": "current"},
        {"role": "ev_charging_power_sensor", "domain": "sensor",
         "device_class": "power"},
        {"role": "ev_charging_sensor", "domain": "sensor",
         "names": ("status",)},
        {"role": "ev_total_energy_sensor", "domain": "sensor",
         "device_class": "energy"},
    ],
    # (#816) JuiceBox 48 over JuiceBoxProxy/MQTT (#683/#698). Rides the
    # generic ``mqtt`` platform, so EVERY rule requires the juicebox naming —
    # without that, any Shelly plug publishing power over MQTT could become a
    # charger. Both energy counters are declared; ha_energy_reader already
    # de-duplicates the pair (#698) and detection must not re-introduce it.
    "juicebox": [
        {"role": "ev_charging_power_sensor", "domain": "sensor",
         "device_class": "power", "names": ("juicebox",)},
        {"role": "ev_total_energy_sensor", "domain": "sensor",
         "device_class": "energy", "names": ("juicebox",), "names2": ("lifetime",)},
        {"role": "ev_session_energy_sensor", "domain": "sensor",
         "device_class": "energy", "names": ("juicebox",), "names2": ("session",)},
        {"role": "ev_charging_sensor", "domain": "sensor",
         "names": ("juicebox",), "names2": ("status",)},
        # (#886) the control must actually name a current limit — a bare
        # ``names=("juicebox",)`` would bind ANY juicebox number as the control.
        # The online/offline split among these is resolved by
        # _reject_offline_current_control at the discovery choke point.
        {"role": "ev_current_control_entity", "domain": "number",
         "names": ("juicebox",), "names2": ("current", "amp")},
    ],
    # (#917) NRGkick, core integration. Keys are core's own translation keys
    # (strings.json), so the row survives any rename of the device. The box
    # publishes a dozen power-class sensors (per phase, apparent, peak) and
    # two numbers: every rule NAMES the key it wants.
    # (#808) ABL eMH1 through matfroh/ABL_emh1_modbus. The integration
    # names entities in plain English with the user's device name in front,
    # so the rules match the tail the source writes, never the head.
    "ev_charger_modbus": [
        {"role": "ev_current_control_entity", "domain": "number",
         "names": ("charging_current",)},
        {"role": "ev_start_stop_entity", "domain": "switch",
         "names": ("charging_enable",)},
        {"role": "ev_charging_power_sensor", "domain": "sensor",
         "device_class": "power"},
        {"role": "ev_charging_sensor", "domain": "sensor",
         "names": ("_state",)},
    ],
    # (#984/#985) Wallbox Pulsar behind the community MQTT bridge — the
    # native ``wallbox`` platform is a different row. Every rule requires
    # the wallbox naming (the JuiceBox rule for a shared platform), and the
    # bridge publishes per-phase power, power-boost power and nine
    # ``*_status`` sensors beside the ones SEM wants: hence the "not"s.
    "wallbox_mqtt": [
        {"role": "ev_charging_power_sensor", "domain": "sensor",
         "device_class": "power", "names": ("wallbox",),
         "names2": ("charging_power",), "not": ("_l1", "_l2", "_l3", "boost")},
        {"role": "ev_total_energy_sensor", "domain": "sensor",
         "device_class": "energy", "names": ("wallbox",),
         "names2": ("cumulative_added_energy",), "not": ("boost", "ecosmart")},
        {"role": "ev_session_energy_sensor", "domain": "sensor",
         "device_class": "energy", "names": ("wallbox",),
         "names2": ("added_energy",),
         "not": ("cumulative", "boost", "ecosmart", "internal_meter")},
        {"role": "ev_charging_sensor", "domain": "sensor",
         "names": ("wallbox",), "names2": ("_status",),
         "not": ("ocpp", "powerboost", "ecosmart", "connectivity", "schedule",
                 "mid_", "external_meter", "control_pilot", "m2w")},
        {"role": "ev_connected_sensor", "domain": "binary_sensor",
         "device_class": "plug", "names": ("wallbox",)},
        {"role": "ev_current_control_entity", "domain": "number",
         "device_class": "current", "names": ("wallbox",),
         "names2": ("max_charging_current",)},
        {"role": "ev_start_stop_entity", "domain": "switch",
         "names": ("wallbox",), "names2": ("charging_enable",)},
    ],
    "wattpilot": [
        {"role": "ev_charging_power_sensor", "domain": "sensor",
         "device_class": "power"},
        {"role": "ev_connected_sensor", "domain": "binary_sensor",
         "device_class": "plug"},
        {"role": "ev_charging_sensor", "domain": "binary_sensor",
         "device_class": "battery_charging"},
        {"role": "ev_current_control_entity", "domain": "number",
         "device_class": "current"},
        {"role": "ev_total_energy_sensor", "domain": "sensor",
         "device_class": "energy", "names": ("total",)},
        {"role": "ev_session_energy_sensor", "domain": "sensor",
         "device_class": "energy", "names": ("session",)},
        # (#804 B4b) The go-e firmware family's force-state select — the
        # surface that latches this box (HorizonKane: every SEM stop left it
        # paused, no current write clears it). Mirrored from goecharger_mqtt.
        # Option VALUES stay unconfigured on purpose: the integration's
        # labels vary by version, and a guessed label is the mangler bug in
        # select form — the entity is surfaced, the reporter confirms.
        {"role": "ev_charge_mode_entity", "domain": "select",
         "names": ("frc", "force_state")},
        # (#804 B4a/B4b) a start/resume button rides the new press path.
        {"role": "ev_start_stop_entity", "domain": "button",
         "names": ("start", "resume")},
    ],
    "heidelberg_energy_control": [
        {"role": "ev_connected_sensor", "domain": "binary_sensor",
         "names": ("connect", "plug")},
        {"role": "ev_charging_sensor", "domain": "binary_sensor",
         "names": ("charg", "active")},
        {"role": "ev_charging_power_sensor", "domain": "sensor",
         "device_class": "power"},
        {"role": "ev_total_energy_sensor", "domain": "sensor",
         "device_class": "energy", "names": ("total",)},
        {"role": "ev_session_energy_sensor", "domain": "sensor",
         "device_class": "energy", "names": ("session",)},
        {"role": "ev_current_control_entity", "domain": "number",
         "names": ("current",)},
    ],
}


def _discover_garo(entities) -> Dict[str, str]:
    """(#816) GARO — a data row plus one hardware constant.

    The 6 A floor is why #700 existed: SEM issued stops the hardware cannot
    honour. It is a property of the brand, not of any entity, so the row
    carries it into the charger config the same way KEBA's service name
    travels."""
    result = _discover_from_hints(entities, _BRAND_HINTS["garo"])
    if not result.get("ev_current_control_entity")             and not result.get("ev_start_stop_entity"):
        return {}
    result["ev_min_current"] = 6
    return result


def _discover_juicebox(entities) -> Dict[str, str]:
    """(#816) JuiceBox 48 over the generic mqtt platform.

    Identity is deliberately strict: power AND an energy counter, both
    juicebox-named. The mqtt platform is everyone's platform, and a lone
    power sensor is an input state, not a charger (#695/#698)."""
    result = _discover_from_hints(entities, _BRAND_HINTS["juicebox"])
    if "ev_charging_power_sensor" not in result:
        return {}
    if ("ev_total_energy_sensor" not in result
            and "ev_session_energy_sensor" not in result):
        return {}
    return result


def _discover_wallbox_mqtt(entities) -> Dict[str, str]:
    """(#984/#985) Wallbox behind the community MQTT bridge. Identity:
    power AND an energy counter AND the current control, all wallbox-named
    — a plug publishing power over mqtt is not a charger, and a unit
    without its control is a meter SEM cannot drive."""
    result = _discover_from_hints(entities, _BRAND_HINTS["wallbox_mqtt"])
    if not {"ev_charging_power_sensor", "ev_current_control_entity"} <= result.keys():
        return {}
    if not ({"ev_total_energy_sensor", "ev_session_energy_sensor"} & result.keys()):
        return {}
    return result


def _discover_mqtt_brands(entities) -> Dict[str, str]:
    """The mqtt platform is everyone's platform: each brand row on it has
    its own identity gate, and the first gate that opens names the box."""
    for fn in (_discover_juicebox, _discover_wallbox_mqtt):
        found = fn(entities)
        if found:
            return found
    return {}


def _discover_abl_emh1(entities) -> Dict[str, str]:
    """(#808) ABL eMH1 through ev_charger_modbus — a data row, gated on the
    current control like the other brand rows SEM can drive."""
    result = _discover_from_hints(entities, _BRAND_HINTS["ev_charger_modbus"])
    if "ev_current_control_entity" not in result:
        return {}
    return result


def _name_hit(eid: str, hint: str) -> bool:
    """Does ``hint`` name a SEGMENT of this entity id?

    (#804) An entity id is a sequence of words, not a bag of letters, and a
    plain ``in`` claims every longer word that happens to contain the hint.
    The live catch: @HorizonKane's go-e box publishes
    ``button.carport_wattpilot_91114903_neustart`` — the German RESTART
    button — and the Wattpilot row's ``("start", "resume")`` matched it, so
    SEM adopted a device reboot as the charging start/stop control. Every
    language has one: restart, neustart, herstart, redemarrer.

    A hit must therefore begin a word: at the start of the id, or right
    after a separator. A hint that already begins with a separator
    (``"_state"``) carries its own boundary and is matched as written.
    """
    if not hint:
        return False
    if hint[0] in "._-":
        return hint in eid
    start = 0
    while True:
        at = eid.find(hint, start)
        if at < 0:
            return False
        if at == 0 or eid[at - 1] in "._-":
            return True
        start = at + 1


def _discover_wattpilot(entities) -> Dict[str, str]:
    """(#802/#804) The data row, plus the box's own force buttons: stop is the
    ``-frc1`` button through ``button.press``, start the ``-frc2`` one. Matched
    by unique id because the names are localised ("Laden stoppen")."""
    result = _discover_from_hints(entities, _BRAND_HINTS["wattpilot"])
    btn: Dict[str, str] = {}
    for e in entities:
        eid = str(getattr(e, "entity_id", "") or "")
        uid = str(getattr(e, "unique_id", "") or "")
        if eid.startswith("button."):
            for suffix in ("-frc0", "-frc1", "-frc2"):
                if uid.endswith(suffix):
                    btn[suffix] = eid
    if "-frc1" in btn:
        result["ev_stop_service"] = "button.press"
        result["ev_stop_service_data"] = json.dumps({"entity_id": btn["-frc1"]})
        start = btn.get("-frc2") or btn.get("-frc0")
        if start:
            result["ev_start_stop_entity"] = start
    return result


def _discover_from_hints(entities, hints: List[_ROLE]) -> Dict[str, str]:
    """Apply a brand's data rows: each role takes the LAST matching entity
    (the same last-wins the hand-written loops had), a rule matches on
    domain, optional device_class, and optional any-of name hints.

    Name hints match on WORD boundaries (``_name_hit``); the ``not`` list
    stays a plain substring, because a negative may be broad."""
    result: Dict[str, str] = {}
    own = _own_names(entities)
    for entry in entities:
        eid = str(entry.entity_id)
        dom = eid.split(".", 1)[0]
        dc = getattr(entry, "original_device_class", None)
        # (#1035) the hints read the entity's own name; the device name in
        # front of it is in every id of the device and tells none apart.
        name = own.get(eid, "")
        for rule in hints:
            if dom != rule["domain"]:
                continue
            if "device_class" in rule and dc != rule["device_class"]:
                continue
            # (#804) HA labels a reboot button ``restart`` in every
            # language. A rule that did not ask for that class never wants
            # it — the word hints are what matched it before.
            if dc == REBOOT_DEVICE_CLASS and rule.get("device_class") != dc:
                continue
            names = rule.get("names")
            if names and not any(_name_hit(name, n) for n in names):
                continue
            # (#816) an optional SECOND any-of set, ANDed with the first —
            # "juicebox" AND "lifetime" — because brands on the shared mqtt
            # platform need conjunctions a single any-of cannot express.
            names2 = rule.get("names2")
            if names2 and not any(_name_hit(name, n) for n in names2):
                continue
            # (#917/#984) a NEGATIVE any-of, for siblings that share the
            # positive words: ``total_charged_energy`` beside
            # ``charged_energy``, ``charging_power_l1`` beside
            # ``charging_power``. Substring rules cannot say "not" otherwise.
            not_names = rule.get("not")
            if not_names and any(n in name for n in not_names):
                continue
            result[rule["role"]] = eid
    return result


def _discover_chargepoint(entities) -> Dict[str, str]:
    """ChargePoint — a data row (#814); see _BRAND_HINTS."""
    return _discover_from_hints(entities, _BRAND_HINTS["chargepoint"])


def _discover_heidelberg(entities) -> Dict[str, str]:
    """Heidelberg Energy Control — a data row (#814); see _BRAND_HINTS."""
    return _discover_from_hints(entities, _BRAND_HINTS["heidelberg_energy_control"])


def _discover_goecharger_mqtt(entities) -> Dict[str, str]:
    """Discover EV charger config from go-eCharger MQTT integration.

    HACS: syssi/homeassistant-goecharger-mqtt
    Uses number entities for current control (amp, ama).
    Start/stop via select entity (frc: 0=neutral, 1=off, 2=on).
    """
    result: Dict[str, str] = {}
    own = _own_names(entities)
    for entry in entities:
        eid = entry.entity_id
        name = own.get(str(eid), "")
        dc = entry.original_device_class
        if eid.startswith("binary_sensor.") and dc == "plug":
            result["ev_connected_sensor"] = eid
        if eid.startswith("binary_sensor.") and "car" in name:
            result.setdefault("ev_charging_sensor", eid)
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "total" in name:
            result["ev_total_energy_sensor"] = eid
        # Requested current (amp) — primary control
        if eid.startswith("number.") and ("requested_current" in name or eid.endswith("_amp")):
            result["ev_current_control_entity"] = eid
        # Force state select (frc) — start/stop control
        if eid.startswith("select.") and ("frc" in name or "force_state" in name):
            result["ev_charge_mode_entity"] = eid
            result["ev_charge_mode_start"] = "2"  # force ON
            result["ev_charge_mode_stop"] = "1"   # force OFF
    return result


def _discover_openwb(entities) -> Dict[str, str]:
    """Discover EV charger config from OpenWB 2.x MQTT integration.

    HACS: a529987659852/openwb2mqtt
    Uses select entity for charge mode, number entity for current.
    """
    result: Dict[str, str] = {}
    own = _own_names(entities)
    for entry in entities:
        eid = entry.entity_id
        name = own.get(str(eid), "")
        dc = entry.original_device_class
        if eid.startswith("binary_sensor.") and ("plug" in name or "connect" in name):
            result["ev_connected_sensor"] = eid
        if eid.startswith("binary_sensor.") and "charg" in name:
            result["ev_charging_sensor"] = eid
        if eid.startswith("sensor.") and dc == "power" and "charg" in name:
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "total" in name:
            result["ev_total_energy_sensor"] = eid
        if eid.startswith("number.") and "current" in name:
            result["ev_current_control_entity"] = eid
        # Charge mode select — start/stop control
        if eid.startswith("select.") and "chargemode" in name:
            result["ev_charge_mode_entity"] = eid
            result["ev_charge_mode_start"] = "Instant Charging"
            result["ev_charge_mode_stop"] = "Stop"
    return result


def _discover_ocpp(entities) -> Dict[str, str]:
    """Discover EV charger config from OCPP integration.

    OCPP chargers use sensor entities for status (not binary_sensor).
    Status values: Available, Preparing, Charging, SuspendedEV, Finishing, etc.

    (#962) The integration names its sensors after the PROTOCOL's measurands,
    so one charge point publishes a whole family under ``device_class: power``
    and another under ``device_class: energy``. Only one member of each
    answers SEM's question. ``Power.Offered`` is the capability the charge
    point ADVERTISES — pinned at the box's maximum the whole time nothing is
    plugged in (@bgthb's Huawei SCharger 22-KT reported 22 kW with no car);
    ``…Export…`` is the V2G direction; ``…Interval`` is a window delta, not a
    register. Binding on the device class alone let registry ORDER pick among
    them, so the family is filtered and then ranked by name.
    """
    result: Dict[str, str] = {}
    powers: list = []
    energies: list = []
    all_powers: list = []
    all_energies: list = []
    own = _own_names(entities)
    for entry in entities:
        eid = str(entry.entity_id)
        name = own.get(eid, "")
        dc = entry.original_device_class
        if eid.startswith("sensor.") and "status" in name and "connector" in name:
            result.setdefault("ev_connected_sensor", eid)
            result.setdefault("ev_charging_sensor", eid)
        if eid.startswith("sensor.") and dc == "power":
            all_powers.append(eid)
            if _measures_the_quantity(eid):
                powers.append(eid)
        if eid.startswith("sensor.") and dc == "energy":
            all_energies.append(eid)
            if _measures_the_quantity(eid):
                energies.append(eid)
        if eid.startswith("number.") and ("current" in name or "limit" in name):
            result["ev_current_control_entity"] = eid
        # (#1035) never the availability switch — the rule the manual path
        # (``ocpp_charge_control_switch``) already applies
        if (eid.startswith("switch.") and "charge" in name
                and "availab" not in name):
            result["ev_start_stop_entity"] = eid
    # Swap-only, like the choke-point guard: a charge point that publishes
    # nothing but capabilities keeps the pre-#962 answer rather than losing
    # the role, because a missing power entity is not a safe state here
    # (see _reject_capability_sensor).
    for role, family, whole in (("ev_charging_power_sensor", powers, all_powers),
                                ("ev_total_energy_sensor", energies, all_energies)):
        pick = family or whole
        if pick:
            result[role] = min(pick, key=lambda e: _rank_measurand(e, role))
    return result


def _discover_ohme(entities) -> Dict[str, str]:
    """Discover EV charger config from Ohme integration.

    Ohme uses sensor for status (``plugged_in``, ``charging``, ``unplugged``
    — #1038: the states HA stores, not the labels it shows).
    Charge mode via select entity. (#1039) Its options are ``max_charge``,
    ``paused`` and ``smart_charge``; "Max charge" and "Paused" are only the
    labels HA shows, and the select refuses a label.
    """
    result: Dict[str, str] = {}
    own = _own_names(entities)
    for entry in entities:
        eid = entry.entity_id
        name = own.get(str(eid), "")
        dc = entry.original_device_class
        if eid.startswith("sensor.") and "status" in name:
            result.setdefault("ev_connected_sensor", eid)
            result.setdefault("ev_charging_sensor", eid)
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy":
            result.setdefault("ev_total_energy_sensor", eid)
        if eid.startswith("sensor.") and "current" in name:
            result.setdefault("ev_current_sensor", eid)
        if eid.startswith("select.") and "charge_mode" in name:
            result["ev_charge_mode_entity"] = eid
            result["ev_charge_mode_start"] = "max_charge"
            result["ev_charge_mode_stop"] = "paused"
    return result


def _discover_peblar(entities) -> Dict[str, str]:
    """Discover EV charger config from Peblar integration.

    Peblar uses sensor for state (``suspended``, ``charging``,
    ``no_ev_connected`` — #1038: the states HA stores, not the labels).
    Current control via number entity (charge_limit).
    """
    result: Dict[str, str] = {}
    own = _own_names(entities)
    for entry in entities:
        eid = entry.entity_id
        name = own.get(str(eid), "")
        dc = entry.original_device_class
        if eid.startswith("sensor.") and "state" in name and dc is None:
            result.setdefault("ev_connected_sensor", eid)
            result.setdefault("ev_charging_sensor", eid)
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "session" in name:
            result.setdefault("ev_session_energy_sensor", eid)
        if eid.startswith("sensor.") and dc == "energy" and "lifetime" in name:
            result.setdefault("ev_total_energy_sensor", eid)
        if eid.startswith("number.") and ("charge" in name or "limit" in name):
            result["ev_current_control_entity"] = eid
        if eid.startswith("switch.") and "charge" in name:
            result["ev_start_stop_entity"] = eid
    return result


def _discover_v2c(entities) -> Dict[str, str]:
    """Discover EV charger config from V2C Trydan integration.

    V2C uses binary_sensor for connected/charging status.
    Current control via number entity (intensity). Start/stop is the
    session pause, which is ON while paused (#1042).
    """
    result: Dict[str, str] = {}
    own = _own_names(entities)
    for entry in entities:
        eid = entry.entity_id
        name = own.get(str(eid), "")
        dc = entry.original_device_class
        if eid.startswith("binary_sensor.") and "connect" in name:
            result["ev_connected_sensor"] = eid
        if eid.startswith("binary_sensor.") and "charg" in name:
            result["ev_charging_sensor"] = eid
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy":
            result.setdefault("ev_total_energy_sensor", eid)
        if eid.startswith("number.") and ("intensity" in name or "current" in name):
            result["ev_current_control_entity"] = eid
        # (#1042) The session pause ("Pause session", key ``paused``), on
        # while paused. "Pause dynamic control modulation" is registered
        # after it and also says "pause"; the last-wins test bound it.
        if eid.startswith("switch.") and _pauses_the_charge(entry):
            result["ev_start_stop_entity"] = eid
    return result


def _discover_alfen(entities) -> Dict[str, str]:
    """Discover EV charger config from Alfen Eve wallbox integration.

    Alfen uses sensor for main state (EV Connected, Charging Power On, Available).
    Current control via number entity (max_current).
    """
    result: Dict[str, str] = {}
    own = _own_names(entities)
    for entry in entities:
        eid = entry.entity_id
        name = own.get(str(eid), "")
        dc = entry.original_device_class
        if eid.startswith("sensor.") and "main_state" in name:
            result.setdefault("ev_connected_sensor", eid)
            result.setdefault("ev_charging_sensor", eid)
        if eid.startswith("sensor.") and dc == "power" and "active_power" in name:
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy" and "meter_reading" in name:
            result.setdefault("ev_total_energy_sensor", eid)
        if eid.startswith("number.") and "max_current" in name:
            result["ev_current_control_entity"] = eid
    return result


def _discover_blue_current(entities) -> Dict[str, str]:
    """Discover EV charger config from Blue Current integration.

    Blue Current uses sensor for vehicle_status and activity.
    No dedicated current control entity — power-only monitoring.
    """
    result: Dict[str, str] = {}
    own = _own_names(entities)
    for entry in entities:
        eid = entry.entity_id
        name = own.get(str(eid), "")
        dc = entry.original_device_class
        if eid.startswith("sensor.") and "vehicle_status" in name:
            result["ev_connected_sensor"] = eid
        if eid.startswith("sensor.") and "activity" in name:
            result.setdefault("ev_charging_sensor", eid)
        if eid.startswith("sensor.") and dc == "power":
            result["ev_charging_power_sensor"] = eid
        if eid.startswith("sensor.") and dc == "energy":
            result.setdefault("ev_total_energy_sensor", eid)
        if eid.startswith("sensor.") and ("avg_current" in name or "max_usage" in name):
            result.setdefault("ev_current_sensor", eid)
    return result


# Platform → discovery function mapping (must be after all _discover_* functions)
#: (#1032) Charger integrations whose brand path folded into the roster's
#: roles — each proven by the crawler rig on the integration's real output
#: (tests/integrations_rig, tests/test_rig_correct_picks.py). Data only: the
#: role reader never reads this list; the coverage tests do.
ROLE_PROVEN_PLATFORMS = (
    "openevse",
    "nrgkick",
)

_EV_CHARGER_PLATFORMS = [
    ("keba", _discover_keba),
    ("easee", _discover_easee),
    ("goecharger", _discover_goecharger),
    ("goecharger_mqtt", _discover_goecharger_mqtt),
    ("goecharger_api2", _discover_goecharger_mqtt),
    ("wallbox", _discover_wallbox),
    ("zaptec", _discover_zaptec),
    ("chargepoint", _discover_chargepoint),
    ("heidelberg_energy_control", _discover_heidelberg),
    ("openwb2mqtt", _discover_openwb),
    ("openwbmqtt", _discover_openwb),
    ("ocpp", _discover_ocpp),
    ("ohme", _discover_ohme),
    ("peblar", _discover_peblar),
    ("v2c", _discover_v2c),
    ("alfen_wallbox", _discover_alfen),
    # (#1032) openevse: found by the roster's roles (rig: core 2026.8.2)
    ("blue_current", _discover_blue_current),
    # (#802/#814) data-row brands need no function — the generic matcher
    # applies their _BRAND_HINTS rows.
    ("wattpilot", lambda ents: _discover_wattpilot(ents)),
    # (#917/#1032) nrgkick: found by the roster's roles
    # (#808) ABL eMH1 through matfroh/ABL_emh1_modbus.
    ("ev_charger_modbus", _discover_abl_emh1),
    # (#816) GARO's custom integration domain.
    ("garo_wallbox", _discover_garo),
    # (#816) JuiceBoxProxy publishes over plain MQTT — the discover fn's
    # identity gate is what keeps this from claiming unrelated mqtt devices.
    # (#984) …and Wallbox's bridge. Both gates live in _discover_mqtt_brands.
    ("mqtt", _discover_mqtt_brands),
]


# ============================================================
# Inverter / battery discharge-control discovery
# ============================================================
# Seeded from a sensor we already learned from the HA Energy Dashboard
# (battery_power / solar_power / etc.). We look that entity up in the
# entity registry, read its `platform`, then iterate sibling entities
# from the same integration to find a `number.*` entity that controls
# battery discharge power. Multilingual patterns (English + German)
# cover the common Huawei Solar / Sungrow / SolarEdge naming.

# Compiled at import time so the discovery loop is hot-path friendly.
_DISCHARGE_CONTROL_PATTERNS = [
    # Huawei Solar (English)
    re.compile(r"max.*discharg.*power", re.IGNORECASE),
    re.compile(r"discharg.*max.*power", re.IGNORECASE),
    re.compile(r"battery.*max.*discharg", re.IGNORECASE),
    re.compile(r"battery.*discharg.*limit", re.IGNORECASE),
    # Huawei Solar (German locale, e.g. number.batteries_maximale_entladeleistung)
    re.compile(r"maximale.*entlade", re.IGNORECASE),
    re.compile(r"max.*entlade", re.IGNORECASE),
    re.compile(r"entlade.*maximum", re.IGNORECASE),
    # SolAX (solax-modbus)
    re.compile(r"solax.*discharg.*power", re.IGNORECASE),
    re.compile(r"solax.*battery.*discharg", re.IGNORECASE),
    # Solarman / DEYE / Sunsynk (ha-solarman)
    re.compile(r"(solarman|deye|sunsynk).*discharg", re.IGNORECASE),
    # Growatt (solax-modbus / growatt integration)
    re.compile(r"growatt.*discharg.*power", re.IGNORECASE),
    re.compile(r"growatt.*battery.*discharg", re.IGNORECASE),
    # Sofar
    re.compile(r"sofar.*discharg.*power", re.IGNORECASE),
    # Solis
    re.compile(r"solis.*discharg.*power", re.IGNORECASE),
    # GoodWe
    re.compile(r"goodwe.*discharg.*power", re.IGNORECASE),
    re.compile(r"goodwe.*battery.*discharg", re.IGNORECASE),
    # SolarEdge Modbus Multi (solaredge-modbus-multi HACS)
    re.compile(r"solaredge.*storage.*discharg", re.IGNORECASE),
    re.compile(r"solaredge.*discharg.*limit", re.IGNORECASE),
    # Enphase Envoy (IQ Battery reserve)
    re.compile(r"envoy.*reserve.*battery", re.IGNORECASE),
    re.compile(r"enphase.*reserve.*battery", re.IGNORECASE),
    re.compile(r"enpower.*reserve.*battery", re.IGNORECASE),
    # Tesla Powerwall (backup reserve %)
    re.compile(r"powerwall.*backup.*reserve", re.IGNORECASE),
    # Victron (ESS SOC limit)
    re.compile(r"victron.*ess.*soclimit", re.IGNORECASE),
    re.compile(r"victron.*minimum.*soc", re.IGNORECASE),
    re.compile(r"victron.*discharg", re.IGNORECASE),
    # Kostal Plenticore (battery DC power control)
    re.compile(r"kostal.*battery.*dc.*power", re.IGNORECASE),
    re.compile(r"plenticore.*battery.*dc.*power", re.IGNORECASE),
    re.compile(r"kostal.*discharg", re.IGNORECASE),
    # Sungrow (max discharge power)
    re.compile(r"sungrow.*discharg.*power", re.IGNORECASE),
    re.compile(r"sungrow.*battery.*discharg", re.IGNORECASE),
    re.compile(r"sungrow.*max.*discharg", re.IGNORECASE),
    # Generic fallback (any integration with standard naming)
    re.compile(r"discharg.*power.*limit", re.IGNORECASE),
    re.compile(r"backup.*reserve", re.IGNORECASE),
]


def discover_inverter_from_registry_verbose(
    hass: HomeAssistant,
    energy_dashboard_config,
) -> Tuple[Optional[str], str]:
    """Auto-discover the battery discharge control number entity.

    Walks the entity registry from a sensor we already know (from the HA
    Energy Dashboard config) to find the integration responsible for the
    battery, then looks for a sibling ``number.*`` entity matching one of
    the discharge-power name patterns.

    Args:
        hass: Home Assistant instance.
        energy_dashboard_config: ``EnergyDashboardConfig`` returned by
            ``ha_energy_reader.read_energy_dashboard_config``.

    Returns:
        ``(entity_id, rung)`` — the discovered control entity or ``None``,
        and WHICH rung answered: ``translation_key`` (the integration's own
        declared key, #915), ``entity_id_pattern`` (the name regexes), or a
        reason for the miss. The rung is what makes the #915 rung's arrival
        observable: the headline live assertion is the SAME entity for a
        better reason. ``discover_inverter_from_registry`` below drops it,
        so no existing caller changed.
    """
    if energy_dashboard_config is None:
        return None, "no_energy_dashboard"

    # Try battery sensors first (most likely to be on the same integration
    # as the discharge control), fall back to solar/grid.
    seed_candidates = [
        getattr(energy_dashboard_config, "battery_power", None),
        getattr(energy_dashboard_config, "battery_charge_energy", None),
        getattr(energy_dashboard_config, "battery_discharge_energy", None),
        getattr(energy_dashboard_config, "solar_power", None),
        getattr(energy_dashboard_config, "solar_energy", None),
        getattr(energy_dashboard_config, "grid_import_power", None),
    ]
    seed_candidates = [s for s in seed_candidates if s]
    if not seed_candidates:
        return None, "no_seed"

    entity_reg = entity_registry.async_get(hass)

    seed_entry = None
    for seed in seed_candidates:
        entry = entity_reg.async_get(seed)
        if entry is not None:
            seed_entry = entry
            break

    if seed_entry is None or not seed_entry.platform:
        return None, "no_registry_entry"

    platform = seed_entry.platform
    config_entry_id = seed_entry.config_entry_id
    _LOGGER.info("Detected inverter platform: %s (seed: %s)", platform, seed_entry.entity_id)

    # Collect candidate number entities from the same integration. Prefer
    # the same config_entry_id (for installs with multiple inverters).
    same_integration: List[str] = []
    for entry in entity_reg.entities.values():
        if entry.platform != platform:
            continue
        if entry.disabled_by:
            continue
        if not entry.entity_id.startswith("number."):
            continue
        if config_entry_id and entry.config_entry_id != config_entry_id:
            # Skip number entities from a different inverter, but only when
            # we know the seed's config entry — avoids cross-contamination.
            continue
        same_integration.append(entry.entity_id)

    if not same_integration:
        return None, "no_candidates"

    # A name match is not sufficient: Deye/ha-solarman exposes e.g.
    # ``number.inverter_battery_max_discharging_current`` in amperes. Older
    # discovery treated that as a watt setpoint and startup could write a
    # configured watt maximum into a 0..350 A register. Auto-detection must
    # therefore require a live W/kW control entity.
    from .coordinator.power_control import is_valid_power_control_entity

    same_integration = [
        eid for eid in same_integration
        if is_valid_power_control_entity(
            hass, eid, require_explicit_unit=True
        )
    ]
    if not same_integration:
        return None, "no_power_control_entity"

    # (#915) FIRST RUNG — ask the registry the semantic question before
    # regexing entity ids. The integration declared this control's
    # translation_key in its own repository; SEM mined that offline. A key
    # match is what HA already records as metadata, which bug class 42's
    # sweep question asks for by name. The unit gate below is unchanged, so
    # this rung is strictly safer than the name match it precedes — and when
    # it finds nothing, the regex rung runs exactly as before.
    _vocab = roster_role_vocab(platform, "battery_discharge_limit")
    _keys = _vocab["keys"]
    if _keys:
        # (06.09 audit) The SAME matcher the card path uses — segment
        # boundary, exact_only honoured. This rung auto-binds the entity
        # SEM writes a power setpoint to every cycle; a bare ``endswith``
        # here picked Marstek's fleet ceiling (``system_max_discharge_power``)
        # for the per-unit key it ends with.
        _by_key = []
        for entry in entity_reg.entities.values():
            if entry.entity_id not in same_integration:
                continue
            hit = _entry_matches_declared(entry, _keys, _vocab["exact_only"])
            if hit:
                # ranked by the roster's key ORDER, as the card path is (#810):
                # Marstek declares the per-unit `max_discharge_power` before
                # the fleet ceiling `system_max_discharge_power`; sorting by
                # entity id picked whichever name came first alphabetically —
                # the ceiling, on the audit's rig.
                _by_key.append((_keys.index(hit), entry.entity_id))
        if _by_key:
            chosen = sorted(_by_key)[0][1]
            _LOGGER.info(
                "Auto-discovered battery discharge control entity: %s "
                "(platform=%s, declared key — roster #915)", chosen, platform)
            return chosen, "translation_key"

    # Score each candidate against the patterns; first hit wins. Prefer
    # entity IDs containing "batter" when multiple match the same pattern.
    def _score(eid: str) -> int:
        return 1 if "batter" in eid.lower() else 0

    for pattern in _DISCHARGE_CONTROL_PATTERNS:
        matches = [eid for eid in same_integration if pattern.search(eid)]
        if matches:
            matches.sort(key=lambda e: (-_score(e), e))
            chosen = matches[0]
            _LOGGER.info(
                "Auto-discovered battery discharge control entity: %s "
                "(platform=%s, pattern=%s)",
                chosen,
                platform,
                pattern.pattern,
            )
            return chosen, "entity_id_pattern"

    return None, "no_match"



def discover_inverter_from_registry(
    hass: HomeAssistant,
    energy_dashboard_config,
) -> Optional[str]:
    """The entity only — every existing caller's contract, unchanged."""
    return discover_inverter_from_registry_verbose(
        hass, energy_dashboard_config)[0]


# ============================================================
# PV string / MPPT discovery
# ============================================================
# Detects individual PV string power sensors from the same integration
# as the solar_power seed entity. Falls back to using individual
# inverter totals from solar_power_list for multi-inverter setups.

_PV_STRING_PATTERNS: List[re.Pattern] = [
    # Huawei, GoodWe, Growatt, Kostal: sensor.*_pv1_power, sensor.*_pv2_power
    re.compile(r"pv[_\s]*(\d+)[_\s]*(?:power|watt)", re.IGNORECASE),
    # Sungrow: sensor.*_mppt1_power, sensor.*_mppt2_power
    re.compile(r"mppt[_\s]*(\d+)[_\s]*(?:power|watt)", re.IGNORECASE),
    # Fronius, SolarEdge: sensor.*_dc_power_1, sensor.*_dc_power_2
    re.compile(r"dc[_\s]*power[_\s]*(\d+)", re.IGNORECASE),
    # Kostal Plenticore: sensor.*_dc1_power, sensor.*_dc2_power
    re.compile(r"dc[_\s]*(\d+)[_\s]*(?:power|watt)", re.IGNORECASE),
    # Victron: sensor.*_tracker_1_power, sensor.*_tracker_2_power
    re.compile(r"tracker[_\s]*(\d+)[_\s]*(?:power|watt)", re.IGNORECASE),
    # Generic: sensor.*_string_1_power, sensor.*_string_2_power
    re.compile(r"string[_\s]*(\d+)[_\s]*(?:power|watt)", re.IGNORECASE),
]

# v1.7.0 V+I synthesis: some integrations (Huawei Solar Modbus, several
# Modbus-only inverter brands) expose ``pv_N_voltage`` and
# ``pv_N_current`` per string but no ``pv_N_power``. When these pairs
# are discovered, SEM multiplies V × I at read time in
# ``sensor_reader`` to synthesise the per-string power. Same slot
# scheme (``pv1``, ``pv2``, …) and same len ≥ 2 gate as direct-power
# discovery.
#
# Voltage / current names vary by integration locale:
#   English: voltage / current
#   German:  spannung / strom         (e.g. huawei_solar)
#   Volt/Amp short forms also accepted
_PV_VOLTAGE_PATTERNS: List[re.Pattern] = [
    re.compile(r"pv[_\s]*(\d+)[_\s]*(?:voltage|spannung|volt)\b", re.IGNORECASE),
    re.compile(r"mppt[_\s]*(\d+)[_\s]*(?:voltage|spannung|volt)\b", re.IGNORECASE),
    re.compile(r"string[_\s]*(\d+)[_\s]*(?:voltage|spannung|volt)\b", re.IGNORECASE),
]
_PV_CURRENT_PATTERNS: List[re.Pattern] = [
    re.compile(r"pv[_\s]*(\d+)[_\s]*(?:current|strom|amp)\b", re.IGNORECASE),
    re.compile(r"mppt[_\s]*(\d+)[_\s]*(?:current|strom|amp)\b", re.IGNORECASE),
    re.compile(r"string[_\s]*(\d+)[_\s]*(?:current|strom|amp)\b", re.IGNORECASE),
]


def discover_pv_strings_from_registry(
    hass: HomeAssistant,
    energy_dashboard_config,
) -> Dict[str, str]:
    """Auto-discover PV string power entities from the entity registry.

    Uses the solar_power sensor from the HA Energy Dashboard config as seed
    to find sibling sensor entities matching PV string naming patterns.

    Falls back to individual inverter totals from ``solar_power_list`` when
    no per-string entities are found but multiple inverters are configured.

    Args:
        hass: Home Assistant instance.
        energy_dashboard_config: ``EnergyDashboardConfig`` from
            ``ha_energy_reader.read_energy_dashboard_config``.

    Returns:
        Dict mapping K-Flow slot names to entity IDs, e.g.
        ``{"pv1_power": "sensor.inverter_pv1_power", ...}``.
        Empty dict if nothing found. Max 4 entries.
    """
    if energy_dashboard_config is None:
        return {}

    # --- Phase 0: explicit user list wins (#378) ---
    #
    # If the user configured ≥2 entities in ``solar_power_list`` on
    # the HA Energy Dashboard, that's an explicit signal — they want
    # those exact entities tracked, not whatever Phase 1's
    # config_entry-scoped sibling scan happens to find. Pre-fix,
    # a multi-inverter user with per-MPPT entities (e.g. two Growatt
    # inverters with pv1/pv2 each) would see Phase 1 return only
    # *one* inverter's siblings — siblings on a second config_entry
    # were filtered out by the ``entry.config_entry_id ==
    # config_entry_id`` test, and the slot-number dedup
    # (``string_num not in found``) silently dropped the cross-
    # inverter overlap. RienduPre's 2026-06-02 diagnostic dump
    # showed this exact pattern: 3 entries in solar_power_list, only
    # 2 surfaced via discovered_direct, both from a different
    # inverter than the user's primary one.
    solar_power_list = getattr(energy_dashboard_config, "solar_power_list", [])
    if isinstance(solar_power_list, list) and len(solar_power_list) > 1:
        result = {}
        for i, inverter_entity in enumerate(solar_power_list[:4], start=1):
            result[f"pv{i}_power"] = inverter_entity
            _LOGGER.info(
                "PV slot %d (from solar_power_list, user-configured): %s",
                i, inverter_entity,
            )
        return result

    # --- Phase 1: single-inverter PV string detection from entity registry ---
    seed_candidates = [
        getattr(energy_dashboard_config, "solar_power", None),
        getattr(energy_dashboard_config, "solar_energy", None),
    ]
    seed_candidates = [s for s in seed_candidates if s]

    entity_reg = entity_registry.async_get(hass)

    seed_entry = None
    for seed in seed_candidates:
        entry = entity_reg.async_get(seed)
        if entry is not None:
            seed_entry = entry
            break

    if seed_entry is not None and seed_entry.platform:
        platform = seed_entry.platform
        config_entry_id = seed_entry.config_entry_id

        # Collect sibling sensor entities from the same integration
        sibling_sensors: List[str] = []
        for entry in entity_reg.entities.values():
            if entry.platform != platform:
                continue
            if entry.disabled_by:
                continue
            if not entry.entity_id.startswith("sensor."):
                continue
            if config_entry_id and entry.config_entry_id != config_entry_id:
                continue
            sibling_sensors.append(entry.entity_id)

        # Match against PV string patterns
        # Collect (string_number, entity_id) pairs
        found: Dict[int, str] = {}
        for eid in sibling_sensors:
            for pattern in _PV_STRING_PATTERNS:
                m = pattern.search(eid)
                if m:
                    string_num = int(m.group(1))
                    if 1 <= string_num <= 4 and string_num not in found:
                        found[string_num] = eid
                        _LOGGER.info(
                            "PV string %d detected: %s (pattern=%s, platform=%s)",
                            string_num, eid, pattern.pattern, platform,
                        )
                    break  # first matching pattern wins for this entity

        if found:
            return {
                f"pv{n}_power": eid
                for n, eid in sorted(found.items())
            }

    # --- Phase 2: multi-inverter fallback ---
    #
    # Now unreachable for the multi-entry case (Phase 0 above handles
    # it). Kept as a safety-net for the single-entry case where Phase 1
    # found nothing AND the list has exactly 1 item.
    if len(solar_power_list) > 1:
        result = {}
        for i, inverter_entity in enumerate(solar_power_list[:4], start=1):
            result[f"pv{i}_power"] = inverter_entity
            _LOGGER.info(
                "PV slot %d (multi-inverter fallback): %s", i, inverter_entity,
            )
        return result

    return {}


def discover_pv_string_vi_pairs(
    hass: "HomeAssistant",
    energy_dashboard_config,
) -> Dict[str, Tuple[str, str]]:
    """Auto-discover per-string voltage+current sensor pairs (v1.7.0).

    Companion to ``discover_pv_strings_from_registry``. Some integrations
    (Huawei Solar Modbus, generic Modbus drivers, several other
    Modbus-only inverter brands) expose ``pv_N_voltage`` and
    ``pv_N_current`` per string but DO NOT publish a pre-multiplied
    ``pv_N_power`` sensor. Detected on HA-PROD 2026-06-01:
    ``sensor.inverter_pv_1_spannung`` + ``..._strom`` are there, but
    no ``pv_1_power`` — direct-power discovery comes back empty.

    This function fills the gap. The caller (coordinator) calls BOTH
    functions; ``sensor_reader`` reads either form at runtime. When V
    and I pair are stored, SEM multiplies them every cycle to
    synthesise the per-string watts.

    Args:
        hass: Home Assistant instance.
        energy_dashboard_config: ``EnergyDashboardConfig`` (same seed
            as the direct-power discovery).

    Returns:
        Dict mapping slot label (``"pv1"``, ``"pv2"``, …) to a tuple
        ``(voltage_entity_id, current_entity_id)``. Empty dict when
        no pairs are found, fewer than 2 complete pairs are found, or
        the seed is unavailable. Max 4 entries.

    Why fewer-than-2 returns empty:
        The downstream sensor surface is gated on ``len(strings) >= 2``
        anyway (single-string users see no per-string entities — the
        fleet ``sensor.sem_solar_power`` is authoritative there).
        Returning ``{}`` early keeps the coordinator path consistent
        with the direct-power discovery's gate semantics.
    """
    if energy_dashboard_config is None:
        return {}

    seed_candidates = [
        getattr(energy_dashboard_config, "solar_power", None),
        getattr(energy_dashboard_config, "solar_energy", None),
    ]
    seed_candidates = [s for s in seed_candidates if s]
    if not seed_candidates:
        return {}

    entity_reg = entity_registry.async_get(hass)
    seed_entry = None
    for seed in seed_candidates:
        entry = entity_reg.async_get(seed)
        if entry is not None:
            seed_entry = entry
            break

    if seed_entry is None or not seed_entry.platform:
        return {}

    platform = seed_entry.platform
    config_entry_id = seed_entry.config_entry_id

    # Collect candidate sibling sensors. Same scoping rule as
    # ``discover_pv_strings_from_registry`` — same integration, same
    # config entry — so cross-integration entities can't false-pair.
    siblings: List[str] = []
    for entry in entity_reg.entities.values():
        if entry.platform != platform:
            continue
        if entry.disabled_by:
            continue
        if not entry.entity_id.startswith("sensor."):
            continue
        if config_entry_id and entry.config_entry_id != config_entry_id:
            continue
        siblings.append(entry.entity_id)

    # Match voltage candidates per string number.
    voltages: Dict[int, str] = {}
    for eid in siblings:
        for pat in _PV_VOLTAGE_PATTERNS:
            m = pat.search(eid)
            if m:
                n = int(m.group(1))
                if 1 <= n <= 4 and n not in voltages:
                    voltages[n] = eid
                break

    # Match current candidates per string number.
    currents: Dict[int, str] = {}
    for eid in siblings:
        for pat in _PV_CURRENT_PATTERNS:
            m = pat.search(eid)
            if m:
                n = int(m.group(1))
                if 1 <= n <= 4 and n not in currents:
                    currents[n] = eid
                break

    # Intersect — only strings with BOTH V and I get returned.
    paired = {n: (voltages[n], currents[n]) for n in voltages if n in currents}
    if len(paired) < 2:
        return {}

    result = {
        f"pv{n}": pair
        for n, pair in sorted(paired.items())
    }
    for slot, (v_eid, c_eid) in result.items():
        _LOGGER.info(
            "PV string %s V+I pair detected: V=%s I=%s (platform=%s) "
            "— SEM will synthesise power = V × I at read time",
            slot, v_eid, c_eid, platform,
        )
    return result


# ============================================================
# Battery / inverter detail sensor discovery (for K-Flow)
# ============================================================
# Detects optional detail sensors (temperature, voltage, current, cell
# voltages) from the same integration as the battery/solar seed entity.
# Each key maps to a K-Flow config field.

_BATTERY_DETAIL_PATTERNS: Dict[str, List[re.Pattern]] = {
    # Inverter temperature. Brand naming varies wildly (#564) — the specific
    # shapes below are unambiguous; a guarded bare-``temperature`` fallback in
    # discover_battery_details_from_registry() covers Fronius/GoodWe/Solis/
    # Sofar/DEYE which expose the inverter temp as a plain ``*_temperature``.
    "inv_temp": [
        re.compile(r"inverter[_\s]*temp", re.IGNORECASE),
        re.compile(r"inverter.*internal.*temp", re.IGNORECASE),
        re.compile(r"inverter.*interne.*temp", re.IGNORECASE),  # Huawei DE: inverter_interne_temperatur
        re.compile(r"inverter.*radiator.*temp", re.IGNORECASE),  # KSTAR: inverter_radiator_temperature
        re.compile(r"invertor[_\s]*temp", re.IGNORECASE),  # GivTCP spelling: invertor_temperature
        re.compile(r"inv[_\s]*temp", re.IGNORECASE),  # FoxESS: invtemp (abbrev)
        re.compile(r"internal[_\s]*temp", re.IGNORECASE),
        re.compile(r"device[_\s]*temp", re.IGNORECASE),
        re.compile(r"radiator[_\s]*temp", re.IGNORECASE),  # SolaX/Sunsynk/DEYE: radiator_temperature
        re.compile(r"heat[_\s]*sink[_\s]*temp", re.IGNORECASE),
        re.compile(r"temp[_\s]*sink", re.IGNORECASE),  # SolarEdge modbus: tempsink
        re.compile(r"igbt[_\s]*temp", re.IGNORECASE),
        re.compile(r"dc[_\s]*transformer[_\s]*temp", re.IGNORECASE),  # Sunsynk
        re.compile(r"case[_\s]*temp", re.IGNORECASE),  # SENEC
        re.compile(r"mcu[_\s]*temp", re.IGNORECASE),  # SENEC
    ],
    # Battery temperature (primary)
    "battery_temp1": [
        re.compile(r"battery[_\s]*1[_\s]*temp", re.IGNORECASE),  # battery_1_temperature (Huawei EN/DE)
        re.compile(r"batter.*temp.*1", re.IGNORECASE),  # battery_temperature_1 (JK BMS)
        re.compile(r"batter(?!.*2).*temp(?!.*2)", re.IGNORECASE),  # battery_temperature (single, not "2")
        re.compile(r"cell[_\s]*temp.*1", re.IGNORECASE),
        # Battery brands that name the cell-temperature sensor WITHOUT a
        # "battery"/"1" token — Fronius Reserva / BYD expose it as
        # ``reserva_cell_temperature`` (#564). Match a bare cell temperature
        # but keep the "2" out so it can't steal battery_temp2's sensor.
        re.compile(r"cell[_\s]*temp(?!.*2)", re.IGNORECASE),
        # Reversed word order — Fronius core storage: ``temperature_cell`` (#564).
        re.compile(r"temp\w*[_\s]*cell(?!.*2)", re.IGNORECASE),
        # BYD battery-management-unit temperature: ``bmu_temp`` (#564).
        re.compile(r"bmu[_\s]*temp", re.IGNORECASE),
        # Enphase IQ Battery — each IQ Battery is exposed by the enphase_envoy
        # integration as a child "Encharge {serial}" device whose cell-temp
        # sensor is ``encharge_<serial>_temperature`` (#583). It carries no
        # battery/cell/bms token, so the patterns above miss it entirely.
        re.compile(r"encharge.*temp", re.IGNORECASE),
    ],
    # Battery temperature (secondary)
    "battery_temp2": [
        re.compile(r"battery[_\s]*2[_\s]*temp", re.IGNORECASE),  # battery_2_temperature (Huawei)
        re.compile(r"batter.*temp.*2", re.IGNORECASE),  # battery_temperature_2 (JK BMS)
        re.compile(r"cell[_\s]*temp.*2", re.IGNORECASE),
    ],
    # BMS / MOS temperature
    "battery_mos": [
        re.compile(r"mos[_\s]*temp", re.IGNORECASE),
        re.compile(r"bms[_\s]*temp", re.IGNORECASE),
        re.compile(r"bms[_\s]*bat[_\s]*temp", re.IGNORECASE),  # GoodWe: bms_bat_temperature
    ],
    # Battery voltage (pack voltage, exclude cell voltages)
    "battery_voltage": [
        re.compile(r"batter(?!.*cell).*voltage", re.IGNORECASE),  # battery_voltage but NOT battery_min_cell_voltage
        re.compile(r"batter.*bus[_\s]*voltage", re.IGNORECASE),
        re.compile(r"batter.*busspannung", re.IGNORECASE),  # Huawei DE: batteries_busspannung
        re.compile(r"batter.*spannung(?!.*pv)(?!.*netz)", re.IGNORECASE),  # DE: generic battery voltage
    ],
    # Battery current
    "battery_current": [
        re.compile(r"batter.*current", re.IGNORECASE),
        re.compile(r"batter.*busstrom", re.IGNORECASE),  # Huawei DE: batteries_busstrom
        re.compile(r"batter.*strom(?!.*netz)", re.IGNORECASE),  # DE: generic battery current (not grid)
    ],
    # Min cell voltage
    "battery_min_cell": [
        re.compile(r"min.*cell.*volt", re.IGNORECASE),
        re.compile(r"cell.*min.*volt", re.IGNORECASE),
        re.compile(r"lowest.*cell.*volt", re.IGNORECASE),
    ],
    # Max cell voltage
    "battery_max_cell": [
        re.compile(r"max.*cell.*volt", re.IGNORECASE),
        re.compile(r"cell.*max.*volt", re.IGNORECASE),
        re.compile(r"highest.*cell.*volt", re.IGNORECASE),
    ],
}


def discover_battery_details_from_registry(
    hass: HomeAssistant,
    energy_dashboard_config,
) -> Dict[str, str]:
    """Auto-discover battery and inverter detail sensors for K-Flow.

    Finds temperature, voltage, current, and cell voltage sensors from the
    same integration as the battery/solar seed entity.

    Args:
        hass: Home Assistant instance.
        energy_dashboard_config: ``EnergyDashboardConfig`` from
            ``ha_energy_reader.read_energy_dashboard_config``.

    Returns:
        Dict mapping K-Flow field names to entity IDs, e.g.
        ``{"inv_temp": "sensor.inverter_temperature", ...}``.
        Empty dict if nothing found.
    """
    if energy_dashboard_config is None:
        return {}

    # Use battery sensors as seed (most likely to share integration with
    # detail sensors), fall back to solar.
    seed_candidates = [
        getattr(energy_dashboard_config, "battery_power", None),
        getattr(energy_dashboard_config, "battery_charge_energy", None),
        getattr(energy_dashboard_config, "solar_power", None),
    ]
    seed_candidates = [s for s in seed_candidates if s]
    if not seed_candidates:
        return {}

    entity_reg = entity_registry.async_get(hass)

    seed_entry = None
    for seed in seed_candidates:
        entry = entity_reg.async_get(seed)
        if entry is not None:
            seed_entry = entry
            break

    if seed_entry is None or not seed_entry.platform:
        return {}

    platform = seed_entry.platform
    config_entry_id = seed_entry.config_entry_id

    # Collect sibling sensor entities from the same integration
    sibling_sensors: List[str] = []
    for entry in entity_reg.entities.values():
        if entry.platform != platform:
            continue
        if entry.disabled_by:
            continue
        if not entry.entity_id.startswith("sensor."):
            continue
        if config_entry_id and entry.config_entry_id != config_entry_id:
            continue
        sibling_sensors.append(entry.entity_id)

    # Match each K-Flow field against its patterns — first match wins
    result: Dict[str, str] = {}
    for kflow_field, patterns in _BATTERY_DETAIL_PATTERNS.items():
        for pattern in patterns:
            matches = [eid for eid in sibling_sensors if pattern.search(eid)]
            if matches:
                chosen = matches[0]
                result[kflow_field] = chosen
                _LOGGER.info(
                    "Battery detail %s detected: %s (pattern=%s, platform=%s)",
                    kflow_field, chosen, pattern.pattern, platform,
                )
                break

    # (#564) Guarded bare-``temperature`` fallback for the inverter temp.
    # Fronius/GoodWe/Solis/Sofar/DEYE name it as a plain ``*_temperature`` with
    # no inverter/internal/device token, so the patterns above miss it. Claim
    # such a sensor as inv_temp ONLY when it's a real temperature sensor (by
    # device_class/unit), not already used by another field, and its name
    # carries none of the non-inverter tokens below — so it can't steal a
    # battery/cell/ambient/water sensor.
    if "inv_temp" not in result:
        already = set(result.values())
        fallback = _bare_temperature_inverter_sensor(hass, sibling_sensors, already)
        if fallback:
            result["inv_temp"] = fallback
            _LOGGER.info(
                "Inverter temp detected via bare-temperature fallback: %s "
                "(platform=%s)", fallback, platform,
            )

    return result


# Tokens that disqualify a bare ``*_temperature`` sensor from being claimed as
# the INVERTER temperature (they belong to the battery, a cell, an ambient/room
# probe, water/boiler, the grid meter, or a PV string).
_NON_INVERTER_TEMP_TOKENS = re.compile(
    r"batter|\bbat\b|_bat_|encharge|cell|bms|bmu|\bmos\b|\bair\b|ambient|environ|indoor|"
    r"outdoor|outside|room|water|boiler|hot[_\s]*water|weather|dew|humid|grid|"
    r"meter|\bpv\d|string|module|panel|heatpump|heat[_\s]*pump|cpu|freezer|fridge",
    re.IGNORECASE,
)


def _bare_temperature_inverter_sensor(hass, sibling_sensors, exclude):
    """Pick a plain ``*temperature`` sensor as the inverter temp (#564).

    A candidate must (a) not already be claimed, (b) carry no non-inverter
    token, and (c) be a CONFIRMED temperature sensor (device_class temperature
    or a °C/°F unit). Because this fallback has no anchoring name pattern, we
    require a loaded state and refuse to guess: if the state isn't up yet we
    skip and let the 5-minute autodetect throttle retry once entities load —
    a wrong pick here would be cached permanently. First confirmed hit wins.
    """
    for eid in sibling_sensors:
        if eid in exclude:
            continue
        if "temp" not in eid.lower():
            continue
        if _NON_INVERTER_TEMP_TOKENS.search(eid):
            continue
        state = hass.states.get(eid) if hass else None
        if state is None:
            continue  # not loaded yet — don't guess; retry next probe
        dc = state.attributes.get("device_class")
        # #727 — ask units.py (the one place that knows temperature units) rather
        # than an inline literal list, so °C/°F/K stay in a single source.
        # Local import keeps this module from eagerly pulling in the coordinator
        # package (hardware_detection is imported very early).
        from .coordinator.units import is_temperature_unit
        if dc == "temperature" or is_temperature_unit(state):
            return eid
    return None


# ── (#976) OCPP: the charge-control switch is the stop verb ─────────────
def entity_platform(hass, entity_id: str):
    """The integration that owns ``entity_id`` (registry platform), or None."""
    try:
        from homeassistant.helpers import entity_registry as er
        entry = er.async_get(hass).async_get(entity_id)
        return str(entry.platform) if entry is not None and entry.platform else None
    except Exception:  # noqa: BLE001 — a lookup that fails is "unknown", never a crash
        return None


def ocpp_charge_control_switch(hass, number_entity_id: str):
    """(#976) The ``switch.<charge point>_charge_control`` sibling of an OCPP
    maximum-current number — the entity that ends a transaction (RemoteStop).

    A charger configured by hand with the current number alone had no stop
    mechanism, so SEM's generic stop wrote 0 A — which on OCPP becomes a
    persisted 0 A charging profile that the charge point keeps: it then
    accepts every start and ends it a second later (@bgthb's Huawei
    SCharger, 18.09). Same device, platform ``ocpp``, a switch whose id
    carries ``charge`` and not ``availability`` — the rule ``_discover_ocpp``
    already applies on auto-detection, made reachable for the manual path.
    """
    try:
        from homeassistant.helpers import entity_registry as er
        reg = er.async_get(hass)
        entry = reg.async_get(number_entity_id)
        if entry is None or str(entry.platform or "") != "ocpp":
            return None
        dev = getattr(entry, "device_id", None)
        device = [e for e in reg.entities.values()
                  if str(getattr(e, "platform", "") or "") == "ocpp"
                  and (dev is None or getattr(e, "device_id", None) == dev)]
        # (#1035) the switch's own name: a charge point left at the
        # integration's default name "charger" puts "charge" in every id.
        own = _own_names(device)
        for e in device:
            eid = str(getattr(e, "entity_id", "") or "")
            name = own.get(eid, "")
            if (eid.startswith("switch.") and "charge" in name
                    and "availab" not in name):
                return eid
    except Exception:  # noqa: BLE001
        return None
    return None


def wattpilot_force_buttons(hass, number_entity_id: str) -> Dict[str, str]:
    """(#804) The Wattpilot's own start and stop, found on the same device as
    its current number.

    ruaan-deysel/ha-wattpilot (the fork @HorizonKane runs) has no stop switch:
    it writes the box's force state ``frc`` through three buttons whose
    unique ids end ``-frc0`` (neutral: the box's own logic decides),
    ``-frc1`` (off) and ``-frc2`` (on). Their names are localised — "Laden
    stoppen", "Laden erzwingen" — so they are matched by unique id, the same
    in every language.

    ``stop`` is ``-frc1``. ``start`` is ``-frc2``: neutral would hand the box
    back to its own Eco / PV-surplus regulation, which then overrides the
    current SEM writes (evcc drives go-e boxes with frc 1/2 for the same
    reason). ``{}`` when the number is not a Wattpilot or no stop exists.
    """
    try:
        from homeassistant.helpers import entity_registry as er
        reg = er.async_get(hass)
        entry = reg.async_get(number_entity_id)
        if entry is None or str(entry.platform or "") != "wattpilot" \
                or not getattr(entry, "device_id", None):
            return {}
        found: Dict[str, str] = {}
        disabled: List[str] = []
        # (review) include disabled buttons: they did nothing for SEM before
        # this fix, so a user may well have switched them off — finding none
        # would leave the box as unstoppable as before, silently.
        for e in er.async_entries_for_device(
                reg, entry.device_id, include_disabled_entities=True):
            eid = str(getattr(e, "entity_id", "") or "")
            uid = str(getattr(e, "unique_id", "") or "")
            if not eid.startswith("button."):
                continue
            for suffix, role in (("-frc1", "stop"), ("-frc2", "start"),
                                 ("-frc0", "neutral")):
                if uid.endswith(suffix):
                    if getattr(e, "disabled_by", None):
                        disabled.append(eid)
                    else:
                        found[role] = eid
        if "stop" not in found:
            return {"disabled": ",".join(sorted(disabled))} if disabled else {}
        out = {"stop": found["stop"]}
        start = found.get("start") or found.get("neutral")
        if start:
            out["start"] = start
        out["frc_buttons"] = ",".join(sorted(found.values()))
        return out
    except Exception:  # noqa: BLE001 — a lookup that fails finds nothing
        return {}


def _wire_wattpilot(hass, device, charger_id: str, current_entity_id) -> None:
    """(#804) A Wattpilot SEM could not stop. Its stop is a button, and a
    button-started charger's only stop was a 0 A write — below the box's 6 A
    minimum, so it was skipped: Off, Solar only and every phase switch did
    nothing, and the box's own neutral start left its Eco / PV-surplus logic
    in charge of the current. A saved stop service wins; a start the user
    chose that is not one of the box's own force buttons is kept."""
    ctl = wattpilot_force_buttons(hass, current_entity_id)
    if ctl.get("disabled") and "stop" not in ctl:
        _LOGGER.warning(
            "Charger '%s': Wattpilot — its stop button is disabled in Home "
            "Assistant (%s). Enable it so SEM can stop this charger (#804)",
            charger_id, ctl["disabled"])
        return
    if not ctl:
        _LOGGER.warning(
            "Charger '%s': Wattpilot %s — no stop button found on the device; "
            "SEM cannot stop this charger (#804)", charger_id, current_entity_id)
        return
    current = getattr(device, "start_stop_entity", None)
    ours = set(ctl["frc_buttons"].split(","))
    if ctl.get("start") and (not current or current in ours):
        device.start_stop_entity = ctl["start"]
    if not getattr(device, "stop_service", None):
        device.stop_service = "button.press"
        device.stop_service_data = {"entity_id": ctl["stop"]}
    _LOGGER.info(
        "Charger '%s': Wattpilot — start %s, stop %s (the box's own force "
        "buttons, #804)", charger_id, getattr(device, "start_stop_entity", None),
        ctl["stop"])


def wire_current_entity(hass, device, charger_id: str, current_entity_id) -> None:
    """(#976) What the current entity's PLATFORM implies for control, applied
    to a freshly built charger device — the ONE producer, called by every
    builder (the setup-time builder in ``__init__`` and the coordinator's
    late retry).

    * ``zero_amps_parks_a_limit`` — on the OCPP integration the maximum-
      current number is a charging profile the charge point KEEPS, so a
      0 A write is a lockout, not a pause; the device refuses it.
    * the charge-control switch is adopted as the start/stop surface when
      the user configured the number alone, so the stop is a RemoteStop;
      without one SEM says so, and the #627 Repair follows.

    Two construction sites once carried this unevenly — the retry path had
    none of it — which is the shape that hid the export guard's silent
    no-op (bug class 93): a second producer without the field.

    * (#1042) a saved start/stop switch that pauses something other than
      the charge is swapped for the device's one pause of the charge
      (``charge_pause_twin``).
    """
    saved = getattr(device, "start_stop_entity", None)
    twin = charge_pause_twin(hass, saved) if saved else None
    if twin:
        device.start_stop_entity = twin
        _LOGGER.warning(
            "Charger '%s': the saved start/stop switch %s pauses something "
            "other than the charge; SEM uses %s, the same device's pause of "
            "the charge. Save %s under Configuration → EV chargers to stop "
            "this message (#1042)", charger_id, saved, twin, twin)
    if not current_entity_id:
        return
    platform = entity_platform(hass, current_entity_id)
    device.zero_amps_parks_a_limit = (platform == "ocpp")
    if platform == "wattpilot":
        _wire_wattpilot(hass, device, charger_id, current_entity_id)
        return
    if platform != "ocpp" or getattr(device, "start_stop_entity", None):
        return
    sw = ocpp_charge_control_switch(hass, current_entity_id)
    if sw:
        device.start_stop_entity = sw
        _LOGGER.info(
            "Charger '%s': OCPP charge point — adopted %s as the start/stop "
            "switch (a 0 A limit would lock it, #976)", charger_id, sw)
    else:
        _LOGGER.warning(
            "Charger '%s': OCPP current number %s with no charge-control "
            "switch found — SEM cannot stop this charger; set "
            "ev_start_stop_entity (#976)", charger_id, current_entity_id)
