"""Read sensor configuration from Home Assistant Energy Dashboard.

This module reads the Energy Dashboard configuration (HA's energy manager, or
.storage/energy when the energy integration is not loaded) to extract sensor
entity IDs for solar, grid, battery, and EV charger. This allows SEM to use the
same sensors the user has already configured in the HA Energy Dashboard.

Requires Home Assistant 2025.12+ for stat_power fields.
"""
import copy
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .coordinator.units import is_power_unit

_LOGGER = logging.getLogger(__name__)

# Per-type keyword rules for deriving a power sensor from the energy sensor's
# device when the Energy Dashboard has no stat_rate power link (issue #250).
# "include" = entity_id substrings that qualify a candidate; "prefer" = substrings
# that break ties (earlier = higher priority). Device-scoped search + device_class
# filtering keeps false positives low even when one device exposes every sensor
# (as SolaX solax-modbus does).
_POWER_DERIVE_RULES: Dict[str, Dict[str, Any]] = {
    "solar": {
        "include": ("pv_power", "solar_power", "production_power"),
        "prefer": ("total",),
        # (#1172) see the grid rule. A HomeWizard socket or kWh meter that
        # counts a solar inverter adds its power × −1 under this key, so it
        # reads positive while the panels produce — the sign SEM expects.
        "declared": {"homewizard": ("active_production_power_w",)},
    },
    "grid": {
        "include": (
            "measured_power", "grid_power", "meter_active_power",
            "active_power_total", "total_active_power", "power_meter",
            "grid_active_power",
        ),
        "prefer": ("measured", "total"),
        # (#1172) integration → the entity key it gives the meter's own net
        # power. Matched on the registry's unique_id / translation_key, which
        # do not change with the user's language — the entity_id does.
        # HomeWizard names this sensor by its device class alone, so a P1
        # meter's power is ``sensor.p1_meter_power`` in English and
        # ``sensor.p1_meter_vermogen`` in Dutch, and no word above fits.
        "declared": {"homewizard": ("active_power_w",)},
    },
    "battery": {
        # No "charge"/"discharge" preference on purpose: when a device exposes a
        # combined `battery_power` AND a `battery_power_charge`, the shortest-name
        # tie-break favours the combined (bidirectional) sensor. SolaX only has
        # `battery_power_charge` (which is itself signed), so it is still picked.
        #
        # #597 — the keyword list is brand/locale-specific (bug-class "power-derive
        # keyword gap"): Huawei Solar names its combined battery power
        # `..._charge_discharge_power` (EN) / `..._lade_entladeleistung` (DE), so
        # neither of the SolaX-shaped keywords matched and the sensor stayed null
        # with no manual override to fall back on. Multilingual coverage mirrors
        # the `_DISCHARGE_CONTROL_PATTERNS` approach in hardware_detection.py.
        "include": (
            "battery_power", "batt_power", "power_battery",
            "charge_discharge_power",   # Huawei Solar (EN combined)
            "lade_entladeleistung",     # Huawei Solar (DE combined)
        ),
        # #597 — when a Huawei device exposes BOTH the fleet-combined
        # (`batteries_…` / `batterien_…`, plural) and a per-battery
        # (`battery_1_…`, singular) power sensor, the two slugs are the same
        # length so the length tie-break is non-deterministic. The plural
        # "batteries"/"batterien" tokens name the combined fleet sensor and
        # never appear in the singular per-battery slug, so they pick the
        # combined deterministically (SolaX's `battery_power` vs
        # `battery_power_charge` still discriminates on length as before).
        "prefer": ("total", "batteries", "batterien"),
        # (#1172) the grid rule's twin: a HomeWizard Plug-In Battery, or a
        # HomeWizard meter counting a battery, gives its net power the same
        # key. Its sign is checked against the counters like any other.
        "declared": {"homewizard": ("active_power_w",)},
    },
    # #600 — generic LOAD device (heat pump / hot water / switch): find the
    # device's own power sensor to feed a kWh-only load. Broad power keywords
    # (EN+DE); the same-device scope keeps it specific. Extend as reported.
    "load": {
        "include": (
            "power", "leistung", "consumption", "verbrauch",
            "active_power", "current_power",
        ),
        "prefer": ("total", "current"),
        # (#1172) a HomeWizard socket's power is ``…_vermogen`` in Dutch
        "declared": {"homewizard": ("active_power_w",)},
    },
}
# Substrings that disqualify a candidate regardless of type (non-real power).
_POWER_DERIVE_EXCLUDE: tuple = ("reactive", "apparent", "factor")


@dataclass
class EnergyDashboardConfig:
    """Configuration extracted from HA Energy Dashboard."""

    # Power sensors (for real-time flow calculations)
    solar_power: Optional[str] = None
    grid_import_power: Optional[str] = None
    grid_export_power: Optional[str] = None
    # Combined. HA's sign is + while discharging; SEM reads it as it is and
    # learns its sign (#1194).
    battery_power: Optional[str] = None
    ev_power: Optional[str] = None

    # #551 — battery ``power_config`` alternatives (HA ≥2026.x battery dialog).
    # Two-sensor mode has NO single combined entity: HA stores
    # ``power_config: {stat_rate_from, stat_rate_to}`` (from=discharge,
    # to=charge) and battery_power stays None — the reader computes
    # net = to − from. ``stat_rate_inverted`` is a combined sensor with the
    # other sign: + while charging, which is SEM's sign (#1194).
    battery_power_from: Optional[str] = None  # discharge power sensor
    battery_power_to: Optional[str] = None    # charge power sensor
    # #553 — grid two-sensor power_config (from=import, to=export). Consumed
    # by a dedicated reader branch with manual-override semantics
    # (grid_power = export − import, sign fixed by declaration).
    grid_power_from: Optional[str] = None
    grid_power_to: Optional[str] = None
    #: (#1194) Some combined battery sensor is marked "Inverted". Read as it
    #: is like any other; the flag only changes what an older store saved
    #: while the one-battery read still flipped it (one flag: only that
    #: read was). See ``SensorReader._move_lock_learned_on_flip``.
    battery_power_inverted: bool = False
    # #553 — ALL two-sensor pairs (multi-battery installs may configure more
    # than one battery in Two-sensor mode). Each entry: (from, to). The
    # scalar fields above stay = first pair (single-battery fast path).
    battery_power_pairs: List[tuple] = field(default_factory=list)

    # #551 — the battery SOC entity the USER configured in HA's Energy
    # Dashboard battery dialog (``stat_soc``). Deterministic — read it
    # instead of guessing via device-registry heuristics.
    battery_soc: Optional[str] = None
    battery_soc_list: List[str] = field(default_factory=list)

    # Energy sensors (for cumulative tracking)
    solar_energy: Optional[str] = None
    grid_import_energy: Optional[str] = None
    grid_export_energy: Optional[str] = None
    battery_charge_energy: Optional[str] = None
    battery_discharge_energy: Optional[str] = None
    ev_energy: Optional[str] = None

    # Multi-device lists (all sources, not just first)
    solar_power_list: List[str] = field(default_factory=list)
    solar_energy_list: List[str] = field(default_factory=list)
    battery_power_list: List[str] = field(default_factory=list)
    battery_charge_energy_list: List[str] = field(default_factory=list)
    battery_discharge_energy_list: List[str] = field(default_factory=list)
    #: (#1193) Each battery's own (charge, discharge) energy counters, by its
    #: ``battery_units`` entry. The two lists above follow the dashboard's
    #: battery order and skip a battery with no counter, so entry N of them
    #: is not battery bN. Read through ``unit_energy_counters``.
    battery_unit_counters: Dict[str, Tuple[Optional[str], Optional[str]]] = field(
        default_factory=dict)
    grid_import_energy_list: List[str] = field(default_factory=list)
    grid_export_energy_list: List[str] = field(default_factory=list)
    grid_power_list: List[str] = field(default_factory=list)

    # Additional device consumption entries (for EV detection)
    device_consumption: List[Dict[str, str]] = field(default_factory=list)

    # Validation flags
    has_solar: bool = False
    has_grid: bool = False
    has_battery: bool = False
    has_ev: bool = False

    # Power sensors that were derived from the energy sensor's device because the
    # Energy Dashboard had no stat_rate link (issue #250). Maps "solar"/"grid"/
    # "battery" → entity_id. Surfaced in diagnostics to distinguish stat_rate
    # power from auto-recovered power.
    derived_power: Dict[str, str] = field(default_factory=dict)

    #: (#1226) Each dashboard source with kWh counters and no power sensor,
    #: in dashboard order: a solar source by its counter, a battery source
    #: by its (charge, discharge) counters. The derive looks for a power
    #: sensor for every one of them. It looked only when the FIRST source
    #: had none, so a second inverter or battery read 0 W.
    solar_energy_only: List[str] = field(default_factory=list)
    battery_energy_only: List[Tuple[Optional[str], Optional[str]]] = field(
        default_factory=list)
    #: (#1226) Each linked solar power sensor → its own source's counter.
    solar_unit_counters: Dict[str, str] = field(default_factory=dict)
    #: (#1226) Every power sensor the derive found → the counter it was
    #: found from. ``derived_power`` names one per source type, and only
    #: when it is the one the scalar field holds.
    derived_units: Dict[str, str] = field(default_factory=dict)
    #: (#1226) The counters of the sources still read from no power sensor
    #: after the derive, by "solar" / "battery". The reader files the
    #: ``power_sensor_not_found`` Repair for them (#1188).
    unsourced_counters: Dict[str, List[str]] = field(default_factory=dict)
    #: (#1236) The counters of the sources the derive set aside and asked for
    #: nothing (their device is read already, or a link of the kind cannot be
    #: placed), by "solar" / "battery". They are not called missing. The
    #: reader only checks whether their kWh shows up in the power it reads.
    left_alone_counters: Dict[str, List[str]] = field(default_factory=dict)

    def is_minimally_configured(self) -> bool:
        """Check if Energy Dashboard has minimum required configuration.

        Requires at least solar and grid to be configured.
        """
        return self.has_solar and self.has_grid

    def power_resolution_incomplete(self) -> bool:
        """True when a source has an energy sensor but no resolved power sensor (#274).

        Real-time power sensors are derived from the energy sensor's *device*
        (``_derive_missing_power_sensors``). On a cold HA start SEM can run that
        derivation before the source integration (e.g. solax-modbus) has
        registered its entities, so nothing is found and SEM reads 0 until a
        manual reload re-derives. The coordinator re-derives each cycle while
        this is True, so the readings start on their own.

        Solar (always a single combined PV sensor) and battery are used as the
        canary. Grid is intentionally excluded — split-grid setups (Growatt,
        DSMR) resolve grid power via a separate runtime discovery, never here, so
        a missing ``grid_import_power`` is normal for them and must not trigger
        endless re-derivation. The source entities all register together, so
        fixing solar/battery implies the registry is ready and grid re-derives in
        the same pass.
        """
        if not self.is_minimally_configured():
            return False
        battery_energy = self.battery_charge_energy or self.battery_discharge_energy
        # #551 — a two-sensor power_config has NO combined battery_power by
        # design (from/to pair instead); that is fully resolved, not missing.
        battery_power_resolved = bool(self.battery_power or self.battery_power_from)
        return bool(
            (self.solar_energy and not self.solar_power)
            or (battery_energy and not battery_power_resolved)
            # (#1226) a second inverter or battery still read from nothing
            or unsourced_counters(self, "solar")
            or unsourced_counters(self, "battery")
        )

    def get_missing_components(self) -> List[str]:
        """Return list of missing required components."""
        missing = []
        if not self.has_solar:
            missing.append("Solar")
        if not self.has_grid:
            missing.append("Grid")
        return missing

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for use in coordinator."""
        return {
            # Power sensors
            "solar_power_sensor": self.solar_power,
            "grid_import_power_sensor": self.grid_import_power,
            "grid_export_power_sensor": self.grid_export_power,
            "battery_power_sensor": self.battery_power,
            "ev_power_sensor": self.ev_power,
            # Energy sensors
            "solar_energy_sensor": self.solar_energy,
            "grid_import_energy_sensor": self.grid_import_energy,
            "grid_export_energy_sensor": self.grid_export_energy,
            "battery_charge_energy_sensor": self.battery_charge_energy,
            "battery_discharge_energy_sensor": self.battery_discharge_energy,
            "ev_energy_sensor": self.ev_energy,
            # Flags
            "has_solar": self.has_solar,
            "has_grid": self.has_grid,
            "has_battery": self.has_battery,
            "has_ev": self.has_ev,
        }


#: (#1043) The Energy Dashboard's energy categories. Each one has a scalar
#: ``<category>_energy`` field and a ``<category>_energy_list`` field.
ENERGY_COUNTER_CATEGORIES: Tuple[str, ...] = (
    "solar", "grid_import", "grid_export", "battery_charge", "battery_discharge",
)


def energy_counters(ed_config: Any, category: str) -> List[str]:
    """Every counter HA's Energy Dashboard adds up for ``category`` (#1043).

    The scalar ``<category>_energy`` field is the FIRST source only. The second
    tariff of a dual-tariff meter, a second inverter or a second battery live
    only in the list, so a total read from the scalar is one part of the sum.
    The scalar is the fallback for a config that carries no list.
    """
    listed = getattr(ed_config, f"{category}_energy_list", None)
    if isinstance(listed, (list, tuple)) and listed:
        return [e for e in dict.fromkeys(listed) if isinstance(e, str) and e]
    single = getattr(ed_config, f"{category}_energy", None)
    return [single] if isinstance(single, str) and single else []


def unsourced_counters(ed_config: Any, kind: str) -> List[str]:
    """(#1226) The counters of the ``kind`` sources ("solar" / "battery")
    that the derive found no power sensor for, in dashboard order. Each of
    them reads 0 W, also beside other units that do read."""
    found = getattr(ed_config, "unsourced_counters", None)
    listed = found.get(kind) if isinstance(found, dict) else None
    if not isinstance(listed, (list, tuple)):
        return []
    return [c for c in dict.fromkeys(listed) if isinstance(c, str) and c]


def left_alone_counters(ed_config: Any, kind: str) -> List[str]:
    """(#1236) The counters of the ``kind`` sources ("solar" / "battery")
    that the derive set aside: no power sensor was asked for them, and none
    is read for them. Their kWh may or may not be inside the power SEM reads."""
    found = getattr(ed_config, "left_alone_counters", None)
    listed = found.get(kind) if isinstance(found, dict) else None
    if not isinstance(listed, (list, tuple)):
        return []
    return [c for c in dict.fromkeys(listed) if isinstance(c, str) and c]


def battery_units(ed_config: Any) -> List[str]:
    """One entity per battery, in the order of its slug ``b1``, ``b2`` … (#1171).

    A battery is a combined power sensor (``battery_power_list``) or a
    two-sensor pair (``battery_power_pairs``, #551/#553). The reader numbers
    the combined ones first, then the pairs; a pair is named by its charge
    sensor, the one its SOC is found from. Every battery count and every
    slug list is this list: counting ``battery_power_list`` alone gave a home
    of two-sensor batteries no sensors and no controls of their own.
    """
    combined = getattr(ed_config, "battery_power_list", None)
    pairs = getattr(ed_config, "battery_power_pairs", None)
    units = list(combined) if isinstance(combined, (list, tuple)) else []
    if isinstance(pairs, (list, tuple)):
        units += [to for _from, to in pairs]
    return units


def yield_found_units_to_picks(ed_config: Any, *, solar_pick: Any = None,
                               battery_pick: Any = None) -> None:
    """(#1226) A Config card pick that stands for all of solar (or the
    battery) beats the power sensors SEM found beside what a build before
    #1226 read.

    A pick stands for the whole source when it is none of that source's own
    unit sensors and the build before read at most one unit: then its
    reader read the pick (#623 sums two or more first). The units found
    since are taken out of the lists, here, before the reader and the
    per-battery entities read them, so both see the same batteries. What
    the build before read stays, so a one-unit home is read as before: a
    found string sensor beside a linked inverter must not beat a total the
    user chose, and a battery found alone keeps its SOC.
    """
    if ed_config is None:
        return
    found = getattr(ed_config, "derived_units", None)
    if not isinstance(found, dict) or not found:
        return
    if isinstance(solar_pick, str) and solar_pick:
        units = list(ed_config.solar_power_list)
        before = [u for u in units if u not in found] or [
            u for u in units if found.get(u) == ed_config.solar_energy][:1]
        if (solar_pick not in units and len(before) <= 1
                and len(before) < len(units)):
            ed_config.solar_power_list[:] = before
            for unit in set(units) - set(before):
                found.pop(unit, None)
            if ed_config.solar_power not in before:
                ed_config.solar_power = before[0] if before else None
                ed_config.derived_power.pop("solar", None)
            ed_config.unsourced_counters.pop("solar", None)
    if isinstance(battery_pick, str) and battery_pick:
        units = battery_units(ed_config)
        own = units + [e for pair in ed_config.battery_power_pairs for e in pair]
        before = battery_units_before_derive(ed_config)
        if (battery_pick not in own and len(before) <= 1
                and len(before) < len(units)):
            dropped = [u for u in ed_config.battery_power_list
                       if u in found and u not in before]
            ed_config.battery_power_list[:] = [
                u for u in ed_config.battery_power_list if u not in dropped]
            for unit in dropped:
                ed_config.battery_unit_counters.pop(unit, None)
                found.pop(unit, None)
            if ed_config.battery_power in dropped:
                ed_config.battery_power = (ed_config.battery_power_list[0]
                                           if ed_config.battery_power_list else None)
                ed_config.derived_power.pop("battery", None)
            ed_config.unsourced_counters.pop("battery", None)


def battery_units_before_derive(ed_config: Any) -> List[str]:
    """(#1226) ``battery_units`` as a build before #1226 had it.

    That build took a power sensor SEM found itself only when no battery
    had a power sensor of its own, and then only the first battery's. The
    battery slots saved by it follow this order, so a first slot record is
    taken by it: a battery found now beside others starts unset, and a
    two-sensor battery it pushed back keeps its own slot.
    """
    units = battery_units(ed_config)
    derived = getattr(ed_config, "derived_units", None)
    if not isinstance(derived, dict) or not derived:
        return units
    own = [u for u in units if u not in derived]
    if own:
        return own
    first = (getattr(ed_config, "battery_charge_energy", None)
             or getattr(ed_config, "battery_discharge_energy", None))
    return [u for u in units if derived.get(u) == first][:1]


def unit_energy_counters(
    ed_config: Any, unit: Optional[str],
) -> Optional[Tuple[Optional[str], Optional[str]]]:
    """This battery's own ``(charge, discharge)`` energy counters (#1193).

    ``unit`` is the battery's ``battery_units`` entry. The parser records the
    counters of the dashboard source that gave the battery its power sensor,
    so a battery is never judged by another battery's counters. ``None`` when
    nothing was recorded for it; ``(None, None)`` when its source had none.
    """
    counters = getattr(ed_config, "battery_unit_counters", None)
    if not unit or not isinstance(counters, dict):
        return None
    pair = counters.get(unit)
    if isinstance(pair, (list, tuple)) and len(pair) == 2:
        return pair[0] or None, pair[1] or None
    return None


def _parse_prefs(
    hass: HomeAssistant, data: Any, quiet: bool = False,
) -> EnergyDashboardConfig:
    """Parse Energy Dashboard preferences into an ``EnergyDashboardConfig``.

    ``data`` is the preferences dict — HA's energy manager's ``data``, or the
    ``data`` section of ``.storage/energy``; both have the same layout.

    Raises ``ValueError`` on a layout it does not recognise: the caller turns
    any exception into "not answered", never into "no battery" (#923/#925).
    """
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("energy_sources"), list)
        or not isinstance(data.get("device_consumption", []), list)
    ):
        raise ValueError("unrecognised Energy Dashboard layout")

    _info = _LOGGER.debug if quiet else _LOGGER.info
    config = EnergyDashboardConfig()

    # Extract energy sources
    energy_sources = data.get("energy_sources", [])
    for source in energy_sources:
        source_type = source.get("type")

        if source_type == "solar":
            _extract_solar_config(source, config)

        elif source_type == "grid":
            _extract_grid_config(source, config)

        elif source_type == "battery":
            _extract_battery_config(source, config)

    # Extract device consumption (for EV charger)
    device_consumption = data.get("device_consumption", [])
    config.device_consumption = device_consumption
    _extract_ev_from_devices(device_consumption, config, hass)

    # Derive any power sensors the Energy Dashboard left unset (no stat_rate).
    # HA 2025.12+ power links are configured manually and are frequently absent
    # (e.g. SolaX solax-modbus energy-only setups, issue #250). Without them SEM
    # has no real-time power and every entity reads 0. Recover by finding a power
    # sensor on the same device as the configured energy sensor.
    _derive_missing_power_sensors(hass, config)

    _info(
        "Read Energy Dashboard config: solar=%s (%d sources), grid=%s (%d import, %d export), battery=%s (%d units), ev=%s",
        config.has_solar, len(config.solar_power_list),
        config.has_grid, len(config.grid_import_energy_list), len(config.grid_export_energy_list),
        config.has_battery, len(battery_units(config)),
        config.has_ev,
    )

    return config


async def _loaded_energy_manager(hass: HomeAssistant) -> Any | None:
    """HA's energy manager when the energy integration is loaded, else None."""
    if "energy" not in hass.config.components:
        return None
    from homeassistant.components.energy.data import async_get_manager

    return await async_get_manager(hass)


def _energy_store_was_corrupt(config_dir: str) -> bool:
    """Whether ``.storage`` holds an ``energy.corrupt.*`` leftover (or that
    could not be determined) — sync, meant for the executor.

    HA's ``Store`` helper renames a corrupt ``.storage/energy`` file to
    ``energy.corrupt.<timestamp>`` and returns no data (see
    ``homeassistant/helpers/storage.py``), which looks identical to "no
    Energy Dashboard was ever configured" from both the energy manager
    (``manager.data is None``) and the raw file (absent). That is "could
    not read", never "no dashboard" (#925: "I could not ask" is not "no").
    """
    storage_dir = os.path.join(config_dir, ".storage")
    try:
        names = os.listdir(storage_dir)
    except FileNotFoundError:
        # No .storage directory at all: nothing was ever written there, so
        # there is definitely no corrupt leftover to find.
        return False
    except OSError as err:
        _LOGGER.warning(
            "Could not check %s for a corrupt Energy Dashboard store leftover "
            "(%s) — SEM keeps every module until it can check again",
            storage_dir, err,
        )
        return True

    corrupt = any(name.startswith("energy.corrupt.") for name in names)

    if corrupt:
        _LOGGER.warning(
            "HA found .storage/energy corrupt (energy.corrupt.* present) — SEM "
            "keeps every module until the Energy Dashboard is set up again and "
            "the corrupt file is removed"
        )
    return corrupt


async def read_energy_dashboard_config_outcome(
    hass: HomeAssistant, quiet: bool = False,
) -> tuple[Optional[EnergyDashboardConfig], bool]:
    """Read the Energy Dashboard config AND whether the question got an answer.

    ``(config, True)`` — the preferences were read and parsed.
    ``(None, True)``   — there are no preferences AND no corrupt leftover:
                         HA's energy manager holds none and no
                         ``.storage/energy`` file exists, and ``.storage``
                         holds no ``energy.corrupt.*`` from a quarantined
                         store — a definite "no dashboard".
    ``(None, False)``  — the read failed (unrecognised layout, parse error,
                         I/O), or HA quarantined a corrupt ``.storage/energy``
                         (or that could not be checked) — "could not read",
                         never "no dashboard" (#925).

    HA's energy manager is asked FIRST; the file only when the energy
    integration is not loaded (or its manager cannot be had). The manager
    updates its data in memory, runs its update listeners, and writes the
    file up to 60 s later (``async_delay_save``) — so right after a user adds
    a battery in the Energy Dashboard the file is missing or stale, and
    reading it would answer "no battery". At boot the manager loads from that
    very file, so there the two agree.

    (#923) The install-modules oracle may call a battery ABSENT only on an
    answer; ``read_energy_dashboard_config`` folds the last two cases into
    one ``None`` (#925: "I could not ask" is not "no").

    Args:
        hass: Home Assistant instance
        quiet: Demote routine INFO logs to DEBUG. Used by the cold-start
            re-derivation retry (#274) so it doesn't spam the log each cycle.
    """
    _info = _LOGGER.debug if quiet else _LOGGER.info
    _info("Reading Energy Dashboard config...")

    try:
        manager = await _loaded_energy_manager(hass)
    except Exception as err:  # noqa: BLE001 — the file is the fallback
        _LOGGER.debug("HA's energy manager unavailable, reading .storage/energy: %s", err)
        manager = None

    if manager is not None:
        try:
            if manager.data is None:
                # HA itself holds no Energy Dashboard: nothing was loaded from
                # disk at boot and nothing has been set since — unless HA's
                # Store quarantined a corrupt file (#923); check before
                # answering "no dashboard".
                if await hass.async_add_executor_job(
                    _energy_store_was_corrupt, hass.config.config_dir
                ):
                    return None, False
                _info("Energy Dashboard not configured (no energy preferences)")
                return None, True
            _info("Energy Dashboard config from HA's energy manager")
            # deepcopy: the config keeps references into these lists, and the
            # manager's data is HA's live state.
            return _parse_prefs(hass, copy.deepcopy(dict(manager.data)), quiet), True
        except Exception as e:
            _LOGGER.error("Failed to read Energy Dashboard config: %s", e, exc_info=True)
            return None, False

    try:
        energy_file = os.path.join(hass.config.config_dir, ".storage", "energy")
        _info("Energy Dashboard file path: %s", energy_file)

        # Read the energy configuration file. A missing file is an answer;
        # any other OSError (permissions, a directory in the way) is not,
        # and propagates to the except below.
        def read_file():
            try:
                with open(energy_file, "r", encoding="utf-8") as f:
                    return True, json.load(f)
            except FileNotFoundError:
                return False, None

        found, energy_config = await hass.async_add_executor_job(read_file)

        if not found:
            # The same corrupt-store rename that empties the manager's data
            # also leaves the plain file absent (#923) — check before
            # answering "no dashboard".
            if await hass.async_add_executor_job(
                _energy_store_was_corrupt, hass.config.config_dir
            ):
                return None, False
            _info("Energy Dashboard not configured (file not found)")
            return None, True

        if (
            not isinstance(energy_config, dict)
            or energy_config.get("version", 1) != 1
            or not isinstance(energy_config.get("data"), dict)
        ):
            _LOGGER.warning(
                "Energy Dashboard file %s has an unrecognised layout (version %s) — "
                "SEM keeps every module until it can read it",
                energy_file,
                energy_config.get("version") if isinstance(energy_config, dict) else None,
            )
            return None, False

        return _parse_prefs(hass, energy_config["data"], quiet), True

    except json.JSONDecodeError as e:
        _LOGGER.error("Failed to parse Energy Dashboard config: %s", e)
        return None, False
    except Exception as e:
        _LOGGER.error("Failed to read Energy Dashboard config: %s", e, exc_info=True)
        return None, False


async def read_energy_dashboard_config(
    hass: HomeAssistant, quiet: bool = False,
) -> Optional[EnergyDashboardConfig]:
    """Read sensor configuration from HA Energy Dashboard.

    Returns the EnergyDashboardConfig, or None when it is not configured OR
    not readable. Callers that must tell those apart use
    ``read_energy_dashboard_config_outcome`` (#923).
    """
    config, _answered = await read_energy_dashboard_config_outcome(hass, quiet=quiet)
    return config


def _extract_solar_config(source: Dict[str, Any], config: EnergyDashboardConfig) -> None:
    """Extract solar configuration from energy source.

    Called once per solar source in the Energy Dashboard. Appends to lists
    and sets the primary (single) field from the first source only.
    """
    energy = source.get("stat_energy_from")
    power = source.get("stat_rate") or source.get("stat_power")

    if energy:
        config.solar_energy_list.append(energy)
        if not config.solar_energy:
            config.solar_energy = energy
    if power:
        config.solar_power_list.append(power)
        if not config.solar_power:
            config.solar_power = power
        if energy:
            config.solar_unit_counters.setdefault(power, energy)   # (#1226)
    elif energy:
        config.solar_energy_only.append(energy)      # (#1226)

    config.has_solar = bool(config.solar_energy_list or config.solar_power_list)

    if energy or power:
        _LOGGER.debug(
            "Found solar source #%d: energy=%s, power=%s",
            len(config.solar_power_list),
            energy,
            power,
        )


def _extract_grid_config(source: Dict[str, Any], config: EnergyDashboardConfig) -> None:
    """Extract grid configuration from energy source.

    Grid uses separate flow_from (import) and flow_to (export) arrays for energy.
    Power is configured in a separate "power" array with "stat_rate" field.
    Arrays may contain multiple entries (e.g. dual-tariff metering in NL/BE).

    HA 2025.12 grid power convention:
    - Single combined sensor: positive=import, negative=export
    - Huawei Solar is OPPOSITE: positive=export, negative=import
    - User may have created a template sensor to invert the sign
    """
    # Grid import energy — collect ALL flow_from entries
    flow_from = source.get("flow_from", [])
    if flow_from:
        for entry in flow_from:
            eid = entry.get("stat_energy_from")
            if eid:
                config.grid_import_energy_list.append(eid)
                if not config.grid_import_energy:
                    config.grid_import_energy = eid
    elif source.get("stat_energy_from"):
        eid = source.get("stat_energy_from")
        config.grid_import_energy_list.append(eid)
        if not config.grid_import_energy:
            config.grid_import_energy = eid

    # Grid export energy — collect ALL flow_to entries
    flow_to = source.get("flow_to", [])
    if flow_to:
        for entry in flow_to:
            eid = entry.get("stat_energy_to")
            if eid:
                config.grid_export_energy_list.append(eid)
                if not config.grid_export_energy:
                    config.grid_export_energy = eid
    elif source.get("stat_energy_to"):
        eid = source.get("stat_energy_to")
        config.grid_export_energy_list.append(eid)
        if not config.grid_export_energy:
            config.grid_export_energy = eid

    # Grid power — collect ALL power entries
    # #553 — grid sources carry the same power_config as batteries (#551):
    # {stat_rate} | {stat_rate_inverted} | {stat_rate_from, stat_rate_to}.
    # Two-sensor grid (from=import, to=export) maps onto SEM's existing
    # split-grid support (Pattern E). An INVERTED combined sensor is read as
    # combined — the #461 sign-detection stack already resolves polarity
    # deterministically (brand > solar-anchored > counter), so no extra sign
    # plumbing is layered here.
    pc = source.get("power_config") or {}
    if isinstance(pc, dict) and (
        pc.get("stat_rate") or pc.get("stat_rate_inverted")
        or (pc.get("stat_rate_from") and pc.get("stat_rate_to"))
    ):
        if pc.get("stat_rate") or pc.get("stat_rate_inverted"):
            eid = pc.get("stat_rate") or pc.get("stat_rate_inverted")
            config.grid_power_list.append(eid)
            if not config.grid_import_power:
                config.grid_import_power = eid
        else:
            # Two sensors: from=import, to=export. Dedicated fields ONLY —
            # grid_import_power is consumed as a COMBINED sensor by the
            # reader, and grid_power_list feeds the multi-meter sum; putting
            # the import side there read import-only as combined (review B1).
            if not config.grid_power_from:
                config.grid_power_from = pc["stat_rate_from"]
                config.grid_power_to = pc["stat_rate_to"]
    else:
        power_config = source.get("power", [])
        if power_config:
            for entry in power_config:
                eid = entry.get("stat_rate")
                if eid:
                    config.grid_power_list.append(eid)
                    if not config.grid_import_power:
                        config.grid_import_power = eid
        elif source.get("stat_rate"):
            eid = source.get("stat_rate")
            config.grid_power_list.append(eid)
            if not config.grid_import_power:
                config.grid_import_power = eid

    config.has_grid = bool(
        config.grid_import_energy_list
        or config.grid_power_list
        or config.grid_export_energy_list
        or (config.grid_power_from and config.grid_power_to)  # #553 pair
    )

    if config.has_grid:
        _LOGGER.debug(
            "Found grid: %d import energy, %d export energy, %d power sensors",
            len(config.grid_import_energy_list),
            len(config.grid_export_energy_list),
            len(config.grid_power_list),
        )


def _extract_battery_config(source: Dict[str, Any], config: EnergyDashboardConfig) -> None:
    """Extract battery configuration from energy source.

    Called once per battery source in the Energy Dashboard. Appends to lists
    and sets the primary (single) field from the first source only.

    Battery uses:
    - stat_energy_from: discharge energy
    - stat_energy_to: charge energy
    - stat_rate/stat_power: combined power (HA: positive=discharge, negative=charge)
    - power_config (#551, HA ≥2026.x): {stat_rate} | {stat_rate_inverted} |
      {stat_rate_from, stat_rate_to} — the "Standard / Inverted / Two sensors"
      choices in HA's battery dialog. Two-sensor mode has NO combined entity.
      For Inverted, HA's top-level stat_rate is its own ``<sensor>_inverted``
      (the user's sensor × −1); SEM reads the user's sensor (#1194).
    - stat_soc (#551): the user's explicit battery state-of-charge sensor.
    """
    discharge_energy = source.get("stat_energy_from")
    charge_energy = source.get("stat_energy_to")
    power = source.get("stat_rate") or source.get("stat_power")

    # #551 — power_config is authoritative when present (HA duplicates the
    # combined stat_rate at top level for back-compat, but ONLY for the
    # Standard mode; Inverted and Two-sensor configs exist solely here).
    pc = source.get("power_config") or {}
    if isinstance(pc, dict):
        if pc.get("stat_rate"):
            power = pc["stat_rate"]
        elif pc.get("stat_rate_inverted"):
            power = pc["stat_rate_inverted"]
            config.battery_power_inverted = True
        elif pc.get("stat_rate_from") and pc.get("stat_rate_to"):
            # Two sensors: from=discharge, to=charge. No combined entity —
            # leave battery_power unset; the reader computes net = to − from.
            # #553: every pair is collected (multi-battery two-sensor
            # fleets); the scalars stay = first pair for the single path.
            config.battery_power_pairs.append(
                (pc["stat_rate_from"], pc["stat_rate_to"]),
            )
            if not config.battery_power_from:
                config.battery_power_from = pc["stat_rate_from"]
                config.battery_power_to = pc["stat_rate_to"]
            power = None

    # #551 — the explicit SOC entity from HA's battery dialog. Deterministic:
    # no device-registry guessing needed when the user already told HA.
    soc = source.get("stat_soc")
    if soc:
        config.battery_soc_list.append(soc)
        if not config.battery_soc:
            config.battery_soc = soc

    if discharge_energy:
        config.battery_discharge_energy_list.append(discharge_energy)
        if not config.battery_discharge_energy:
            config.battery_discharge_energy = discharge_energy
    if charge_energy:
        config.battery_charge_energy_list.append(charge_energy)
        if not config.battery_charge_energy:
            config.battery_charge_energy = charge_energy
    if power:
        config.battery_power_list.append(power)
        if not config.battery_power:
            config.battery_power = power

    # (#1193) The battery keeps its own counters, by the entry that names it
    # in ``battery_units``: the combined sensor, or the pair's charge sensor.
    # The same sensor listed twice is one battery; its first counters stay.
    unit = power or (pc.get("stat_rate_to") if isinstance(pc, dict)
                     and pc.get("stat_rate_from") else None)
    if unit:
        config.battery_unit_counters.setdefault(
            unit, (charge_energy or None, discharge_energy or None))
    elif charge_energy or discharge_energy:
        # (#1226) no power at all: the derive looks for one on its device
        config.battery_energy_only.append(
            (charge_energy or None, discharge_energy or None))

    config.has_battery = bool(
        config.battery_discharge_energy_list
        or config.battery_charge_energy_list
        or config.battery_power_list
        or config.battery_power_from  # #551 two-sensor power, no combined entity
    )

    if discharge_energy or charge_energy or power or config.battery_power_from:
        _LOGGER.debug(
            "Found battery source #%d: charge_energy=%s, discharge_energy=%s, power=%s",
            len(config.battery_power_list),
            charge_energy,
            discharge_energy,
            power,
        )


def _derive_battery_power_if_unrepresented(hass, config) -> None:
    """Derive a combined power sensor for each battery source that has no
    power representation at all (#761, #1226).

    A two-sensor ``power_config`` (#551) leaves ``battery_power`` unset BY
    DESIGN — the reader computes net = to − from from the pair. The
    original guard checked only ``battery_power``, so the derive added the
    device's combined sensor BESIDE the pair: two power representations of
    one physical battery, enumerated as units b1+b2 with identical values
    and summed — battery read 2× while charging and home followed
    (jappish84, #761; every two-sensor install since the derive shipped).
    A pair — or an inverted single (#551) — IS the power representation,
    and a source with one is never asked (``battery_energy_only``).

    (#1226) Each source is asked on its own. The derive used to run only
    when NO battery had power, so a second battery with counters alone
    read 0 W beside the first, and no Repair said so.
    """
    read = list(config.battery_power_list)
    read += [e for pair in config.battery_power_pairs for e in pair]
    read += [c for pair in config.battery_unit_counters.values() for c in pair]
    links = [((unit,), counters)
             for unit, counters in config.battery_unit_counters.items()]
    links += [(pair, config.battery_unit_counters.get(pair[1]) or ())
              for pair in config.battery_power_pairs]
    aside: List[str] = []
    for (charge, discharge), found in _derive_unit_power(
            hass, "battery", config.battery_energy_only, read, links, aside):
        if not found:
            config.unsourced_counters.setdefault("battery", []).append(
                charge or discharge)
            continue
        # The first battery's field, only when no battery has its own sensor
        # (as before #1226): setup saves it as the battery pick (``to_dict``).
        if not config.battery_power and not config.battery_power_pairs:
            config.battery_power = found
            config.derived_power["battery"] = found
        config.battery_power_list.append(found)
        config.derived_units[found] = charge or discharge
        # (#1193) found on this battery's counter device: its counters
        config.battery_unit_counters.setdefault(found, (charge, discharge))
        _LOGGER.info(
            "Derived battery power sensor %s from energy device of %s "
            "(no stat_rate in Energy Dashboard)", found, charge or discharge,
        )
    _record_left_alone(config, "battery", aside)


def _record_left_alone(config: "EnergyDashboardConfig", kind: str,
                       counters: List[str]) -> None:
    """(#1236) What the derive set aside THIS run replaces what an earlier
    run set aside: the derive runs again until every source resolves."""
    if counters:
        config.left_alone_counters[kind] = list(dict.fromkeys(counters))
    else:
        config.left_alone_counters.pop(kind, None)


def _derive_unit_power(
    hass, kind: str, sources: List[Tuple[Optional[str], ...]],
    read: List[Optional[str]], links: Any = (),
    left_alone: Optional[List[str]] = None,
) -> List[Tuple[Tuple[Optional[str], ...], Optional[str]]]:
    """(#1226) Look for a power sensor for each ``kind`` source in
    ``sources`` (its kWh counters; it has no power sensor), in dashboard
    order. ``read`` holds the power sensors and counters of the units of
    this kind that SEM already reads.

    A source whose counter sits on a device one of those units uses is
    left alone: that device's power sensor may hold this source too (an
    inverter's string counters, a fleet sensor beside a pack's own), and a
    second sensor from it would count the same watts twice. It is not
    called missing either. Returns ``(counters, found)`` for each source
    asked; ``found`` is None when its device has no power sensor.

    ``links`` pairs each linked unit's power sensors with its own counters.
    A link that is not on its own counter's device (a template, a site
    meter's total) may hold the other sources too, and nothing says which:
    then no source of this kind is asked, and none is called missing. Two
    sensors for the same watts read high, and a high surplus starts loads
    on grid power.

    (#1236) The counters of every source set aside are added to
    ``left_alone``, so the reader can check their kWh against the power it
    reads. Nothing here adds power.
    """
    def _set_aside(counters) -> None:
        if left_alone is not None:
            left_alone.extend(c for c in counters if c)

    def _devices(entities) -> set:
        return {d for d in (_registry_device_id(hass, e)
                            for e in entities if e) if d}

    if sources:
        for powers, counters in links:
            if not _devices(powers) or not _devices(powers) <= _devices(counters):
                _LOGGER.info(
                    "SEM cannot tell what %s measures (not on the device of "
                    "%s), so it looks for no %s power sensor for %s (#1226)",
                    ", ".join(p for p in powers if p),
                    ", ".join(c for c in counters if c) or "no counter",
                    kind, ", ".join(c for src in sources for c in src if c))
                for src in sources:
                    _set_aside(src)
                return []
    used = _devices(read)
    asked: List[Tuple[Tuple[Optional[str], ...], Optional[str]]] = []
    for counters in sources:
        counter = next((c for c in counters if c), None)
        if counter is None:
            continue
        own = _devices(counters)
        if own & used:
            _LOGGER.debug(
                "%s counter %s is on a device SEM already reads power from; "
                "no second power sensor is taken from it (#1226)",
                kind, counter)
            _set_aside(counters)
            continue
        found = _find_power_sensor_on_device(
            hass, counter, _POWER_DERIVE_RULES[kind])
        if found:
            used |= own
        asked.append((counters, found))
    return asked


#: (#1051) Words that make an Energy Dashboard device the EV — matched as
#: WHOLE words of the entity id, never as letters inside one: "ev" is in
#: "device", and a bed-heating smart plug became a home's EV charger.
_EV_NAME_TOKENS = frozenset({"ev", "evse", "charger", "keba", "wallbox",
                             "easee", "zappi", "juicebox"})
_EV_NAME_PHRASES = ("tesla_wall", "wall_connector")


def _ev_by_name(entity_id: Optional[str]) -> bool:
    import re
    low = (entity_id or "").lower().split(".", 1)[-1]
    if any(p in low for p in _EV_NAME_PHRASES):
        return True
    return any(t in _EV_NAME_TOKENS for t in re.split(r"[^a-z0-9]+", low))


def _charger_integrations() -> frozenset:
    """Integrations the crawler knows as chargers: those it has a discovery
    walk for, those it proves by roles, and the roster's charger rows."""
    from .hardware_detection import (  # cycle-free here
        ROLE_PROVEN_PLATFORMS, _roster, known_charger_domains,
    )
    found = set(known_charger_domains()) | set(ROLE_PROVEN_PLATFORMS)
    try:
        r = _roster()
        rows = (getattr(r, "ROSTER", {}) or {}) if r else {}
        found |= {d for d, row in rows.items()
                  if isinstance(row, dict) and row.get("kind") == "charger"}
    except Exception:  # noqa: BLE001 — the roster is a hint, never required
        pass
    return frozenset(found)


def is_ev_device(hass: Optional[HomeAssistant], energy: Optional[str],
                 power: Optional[str]) -> bool:
    """(#1051) Is this Energy Dashboard individual device the EV?

    Yes when the entity registry says either entity belongs to an
    integration the crawler knows as a charger. Otherwise the entity id's
    WHOLE words decide (``sensor.keba_total_energy`` yes,
    ``sensor.bedverwarming_device_power`` no) — kept so a charger behind a
    template or utility-meter sensor stays the EV it always was."""
    if hass is not None:
        try:
            reg = er.async_get(hass)
            chargers = _charger_integrations()
            for eid in (energy, power):
                entry = reg.async_get(eid) if eid else None
                platform = str(getattr(entry, "platform", "") or "")
                if platform and (platform in chargers
                                 or (platform.startswith("zaptec")
                                     and "zaptec" in chargers)):
                    return True
        except Exception:  # noqa: BLE001 — fall back to the name
            pass
    return _ev_by_name(energy) or _ev_by_name(power)


def _extract_ev_from_devices(
    device_consumption: List[Dict[str, Any]], config: EnergyDashboardConfig,
    hass: Optional[HomeAssistant] = None,
) -> None:
    """Pick the EV charger from the Energy Dashboard's individual devices
    (first match, ``is_ev_device``).

    HA 2025.12 uses "stat_rate" for power sensors in device consumption.
    """
    for device in device_consumption:
        stat_consumption = device.get("stat_consumption") or ""
        stat_power = device.get("stat_rate") or device.get("stat_power")
        if not is_ev_device(hass, stat_consumption, stat_power):
            continue
        config.ev_energy = stat_consumption or None
        config.ev_power = stat_power
        config.has_ev = True
        _LOGGER.debug("Found EV charger in devices: energy=%s, power=%s",
                      config.ev_energy, config.ev_power)
        break


def _declared_power_entry(hass: HomeAssistant, entry) -> bool:
    """(#1172) A declared power sensor still has to measure power.

    Its live state answers when it has one. Before its integration has
    loaded — a cold start, where SEM often sets up first — the registry's
    own record answers, so the meter is not missed for the whole run: the
    grid has no retry, because a split meter never resolves here at all.
    """
    state = hass.states.get(entry.entity_id)
    if state is not None:
        return (state.attributes.get("device_class") == "power"
                or is_power_unit(state))
    dc = getattr(entry, "device_class", None) or getattr(
        entry, "original_device_class", None)
    return dc == "power"


def _registered_as_power(entry) -> bool:
    """(#1226) A sensor with no state yet is judged by the registry's own
    record, as ``_declared_power_entry`` does (#1172). On a cold start SEM
    often sets up before the inverter's integration has loaded. A second
    battery found only once its integration had loaded moved the battery
    list between starts, and with it each battery's saved settings."""
    dc = getattr(entry, "device_class", None) or getattr(
        entry, "original_device_class", None)
    unit = getattr(entry, "unit_of_measurement", None)
    return dc == "power" or (isinstance(unit, str) and is_power_unit(unit))


def _find_power_sensor_on_device(
    hass: HomeAssistant, energy_entity: str, rule: Dict[str, Any],
) -> Optional[str]:
    """Find a power sensor on the same device as ``energy_entity``.

    Mirrors the device-registry strategy used by
    ``SensorReader._auto_detect_battery_soc``: resolve the energy sensor's
    device, then scan its sensor entities for a power sensor whose entity_id
    matches the rule's ``include`` keywords. Ties are broken by ``prefer``
    keyword order, then by shortest entity_id (favours the "total"/parent over
    per-string variants like pv_power_1).

    (#1172) A sensor whose integration DECLARES it as this power — the
    rule's ``declared`` keys, matched on its unique_id / translation_key —
    wins over any name match, and needs no English word in its entity_id.

    Returns the entity_id, or None if no suitable candidate exists.
    """
    if not energy_entity:
        return None
    try:
        from .hardware_detection import _entry_matches_declared

        registry = er.async_get(hass)
        energy_entry = registry.async_get(energy_entity)
        if not energy_entry or not energy_entry.device_id:
            return None

        declared = rule.get("declared") or {}
        keyed: List[str] = []
        candidates: List[str] = []
        for entry in er.async_entries_for_device(registry, energy_entry.device_id):
            if entry.domain != "sensor" or entry.disabled_by is not None:
                continue
            eid = entry.entity_id
            keys = declared.get(str(getattr(entry, "platform", "") or ""), ())
            if keys and _entry_matches_declared(entry, keys) is not None:
                if _declared_power_entry(hass, entry):
                    keyed.append(eid)
                continue
            eid_lower = eid.lower()
            if any(x in eid_lower for x in _POWER_DERIVE_EXCLUDE):
                continue
            if not any(kw in eid_lower for kw in rule["include"]):
                continue
            # Must look like a power sensor. #641 — asking units.py instead
            # of re-listing the suffixes, so a MW/GW-labelled sensor is
            # recognised as power here too.
            state = hass.states.get(eid)
            if state is not None:
                dc = state.attributes.get("device_class")
                if dc != "power" and not is_power_unit(state):
                    continue
            elif not _registered_as_power(entry):
                continue
            candidates.append(eid)

        if keyed:
            return sorted(keyed)[0]
        if not candidates:
            return None

        def _rank(eid: str) -> tuple:
            low = eid.lower()
            prefer = rule.get("prefer", ())
            pref_rank = next(
                (i for i, kw in enumerate(prefer) if kw in low), len(prefer),
            )
            return (pref_rank, len(eid))

        candidates.sort(key=_rank)
        return candidates[0]
    except Exception as e:  # noqa: BLE001 — best-effort, never block setup
        # Surface at warning (#259): a failure here is the #250 class — power can't be
        # derived, so the affected source silently reads 0 everywhere. Make it visible.
        _LOGGER.warning("Power sensor derivation failed for %s: %s", energy_entity, e)
        return None


# (#744) Object-id suffixes stripped to compare a load's energy and power
# sensors for SAME-appliance affinity (a Shelly 2PM's ``channel_a_energy`` must
# map to ``channel_a_power``, never the other channel's).
_LOAD_STEM_SUFFIXES = (
    "_total_energy", "_energy_total", "_energy", "_consumption", "_verbrauch",
    "_active_power", "_power", "_leistung",
)


def _load_object_stem(entity_id: str) -> str:
    """The object_id of ``entity_id`` with a trailing energy/power token removed,
    so an energy sensor and its companion power sensor on the same appliance
    share a stem (``sensor.channel_a_energy`` / ``sensor.channel_a_power`` →
    ``channel_a``).

    Covers the mainstream shape where a channel index PRECEDES the measurement
    token (``switch_0_power`` / ``phase_a_energy``). It does NOT match a trailing
    index AFTER the token (``shellyem_power_2`` / ``shellyem_energy_2`` → distinct
    stems): those simply lose affinity and fall back to the shortest-name pick —
    the same result as before #744, never worse. Stripping the index too would
    collapse ALL of a device's channels to one stem and defeat the affinity, so
    it is intentionally left alone."""
    obj = entity_id.split(".", 1)[1] if "." in entity_id else entity_id
    obj = obj.lower()
    for suffix in _LOAD_STEM_SUFFIXES:
        if obj.endswith(suffix):
            return obj[: -len(suffix)]
    return obj


def _find_load_power_sensor(
    hass: Optional[HomeAssistant], energy_entity: str
) -> Optional[str]:
    """(#744) Companion power sensor for an Energy-Dashboard LOAD row.

    Same device-scoped, ``device_class=power`` scan as
    :func:`_find_power_sensor_on_device`, but tuned for loads: it PREFERS the
    candidate whose object_id shares the energy sensor's stem, so a multi-channel
    device (a Shelly 2PM's ``channel_a`` / ``channel_b``) maps each energy sensor
    to its OWN channel's power sensor instead of whichever the registry lists
    first — the wrong-channel mis-pick the plain scan is prone to. Ties fall back
    to the shortest name.

    This is a DISPLAY / live-power read helper: it feeds ``UnifiedDevice.power_sensor``,
    the surplus sync and the load-manager sync, and is called AFTER control
    discovery so the derived sensor never widens brand-based control/shed
    eligibility (control keys off the ED-configured ``stat_rate`` only). It does
    no brand matching for the same reason.
    """
    if not energy_entity or hass is None:
        return None
    try:
        registry = er.async_get(hass)
        energy_entry = registry.async_get(energy_entity)
        if not energy_entry or not energy_entry.device_id:
            return None

        want_stem = _load_object_stem(energy_entity)
        candidates: List[str] = []
        for entry in er.async_entries_for_device(registry, energy_entry.device_id):
            if entry.domain != "sensor" or entry.disabled_by is not None:
                continue
            eid = entry.entity_id
            if any(x in eid.lower() for x in _POWER_DERIVE_EXCLUDE):
                continue
            state = hass.states.get(eid)
            if not state:
                continue
            dc = state.attributes.get("device_class")
            if dc != "power" and not is_power_unit(state):
                continue
            candidates.append(eid)

        if not candidates:
            return None

        # Same-appliance stem first, then shortest name (favours the device's
        # own/total power over a per-phase variant).
        candidates.sort(
            key=lambda eid: (0 if _load_object_stem(eid) == want_stem else 1, len(eid))
        )
        return candidates[0]
    except Exception as e:  # noqa: BLE001 — best-effort, never block discovery
        _LOGGER.warning("Load power derivation failed for %s: %s", energy_entity, e)
        return None


def _derive_missing_power_sensors(
    hass: Optional[HomeAssistant], config: EnergyDashboardConfig,
) -> None:
    """Recover power sensors not linked in the Energy Dashboard (issue #250).

    SEM reads real-time power from the Energy Dashboard ``stat_rate`` links
    (HA 2025.12+). Those are configured manually and are frequently absent —
    the standard SolaX solax-modbus setup wires only energy sensors. Without
    power links SEM reads 0 for everything. When a source has an energy sensor
    but no power sensor, derive the power sensor from the same device. (#1226)
    Each solar and battery source is asked on its own; one with nothing found
    is kept in ``unsourced_counters`` for its Repair.

    Sign conventions are intentionally NOT handled here — the runtime
    ``SensorReader._detect_grid_sign`` / ``_detect_battery_sign`` auto-detection
    corrects direction from the energy counters (SolaX = grid Pattern D).
    """
    if hass is None:
        return

    # Solar: pv_power_total etc. — (#1226) for every inverter whose source
    # has a counter and no power sensor, not only when the first has none.
    powered = [c for c in config.solar_energy_list
               if c not in config.solar_energy_only]
    aside: List[str] = []
    for (counter,), found in _derive_unit_power(
            hass, "solar", [(c,) for c in config.solar_energy_only],
            list(config.solar_power_list) + powered,
            [((p,), (c,)) for p, c in config.solar_unit_counters.items()],
            aside):
        if not found:
            config.unsourced_counters.setdefault("solar", []).append(counter)
            continue
        if not config.solar_power:
            config.solar_power = found
            config.derived_power["solar"] = found
        config.solar_power_list.append(found)
        config.derived_units[found] = counter
        _LOGGER.info(
            "Derived solar power sensor %s from energy device of %s "
            "(no stat_rate in Energy Dashboard)", found, counter,
        )
    _record_left_alone(config, "solar", aside)

    # Grid: combined meter power (measured_power etc.). Sign auto-detected later.
    if not config.grid_import_power and config.grid_import_energy:
        found = _find_power_sensor_on_device(
            hass, config.grid_import_energy, _POWER_DERIVE_RULES["grid"],
        )
        if found:
            config.grid_import_power = found
            config.grid_power_list.append(found)
            config.derived_power["grid"] = found
            _LOGGER.info(
                "Derived grid power sensor %s from energy device "
                "(no stat_rate in Energy Dashboard)", found,
            )

    # Battery: battery_power* (positive=charge per SEM; sign auto-detected later).
    _derive_battery_power_if_unrepresented(hass, config)


# (#698) Same-measurement variant tokens: two energy sensors whose object_ids
# differ only by one of these trailing tokens are the SAME physical load
# counted two ways (a JuiceBox ships energy_lifetime AND energy_session; heat
# pumps often ship _total and _daily). Ordered by preference — the monotonic
# lifetime/total counter beats a resetting daily/session one. A missing token
# ranks between them ("" = the plain _energy sensor).
_VARIANT_RANK = {"lifetime": 0, "total": 1, "": 2, "today": 3, "daily": 4,
                 "session": 5}


def _variant_stem(entity_id: str) -> Tuple[str, int]:
    """Split ``sensor.juicebox_x_energy_lifetime`` → (``juicebox_x_energy``, rank).

    Only a trailing token from ``_VARIANT_RANK`` is stripped — a Shelly 2PM's
    ``channel_a_energy`` / ``channel_b_energy`` keep distinct stems and are
    never treated as variants of each other.
    """
    object_id = entity_id.split(".", 1)[-1].lower()
    parts = object_id.rsplit("_", 1)
    if len(parts) == 2 and parts[1] in _VARIANT_RANK:
        return parts[0], _VARIANT_RANK[parts[1]]
    return object_id, _VARIANT_RANK[""]


def _registry_device_id(hass, entity_id: str) -> Optional[str]:
    """The entity registry's device_id for an entity — None when unknowable.

    Defensive: discovery must keep working on a hass (or registry state) that
    can't answer, so any failure reads as "unknown", never as a crash.
    """
    if hass is None:
        return None
    try:
        entry = er.async_get(hass).async_get(entity_id)
        did = getattr(entry, "device_id", None)
        return did if isinstance(did, str) else None
    except Exception:
        return None


def get_all_individual_devices(config: EnergyDashboardConfig, hass=None) -> List[Dict[str, Any]]:
    # NOTE: pass hass= — without it the (#698) registry veto can't tell two
    # stem-alike sensors on DIFFERENT devices apart and would fold them.
    """Return all individual devices from Energy Dashboard for load management.

    These are devices listed in the Energy Dashboard's "Individual devices" section
    (device_consumption). Each device can be used for peak management if a
    corresponding switch entity is found for control.

    (#698) Same-measurement variants are folded to ONE device: HA auto-suggests
    every ``total_increasing`` energy sensor into the dashboard, so a charger
    exposing both a lifetime and a session counter otherwise becomes two load
    rows. The fold is vetoed when the entity registry proves the two sensors
    live on different devices.

    Args:
        config: EnergyDashboardConfig from read_energy_dashboard_config()

    Returns:
        List of device dicts with energy_sensor, power_sensor, name, is_ev
    """
    devices = []

    for device in config.device_consumption:
        energy_sensor = device.get("stat_consumption", "")
        power_sensor = device.get("stat_rate") or device.get("stat_power")
        name = device.get("name", "")

        # (#1051) the one EV rule, shared with the EV pick
        is_ev = is_ev_device(hass, energy_sensor, power_sensor)

        # Derive a name: prefer the entity's friendly_name (user-set description)
        if not name and hass:
            state = hass.states.get(energy_sensor)
            if state and state.attributes.get("friendly_name"):
                name = state.attributes["friendly_name"]

        # Fallback: extract from entity ID
        if not name:
            if "." in energy_sensor:
                name_part = energy_sensor.split(".", 1)[1]
                for suffix in ["_energy", "_total_energy", "_power", "_consumption"]:
                    if name_part.endswith(suffix):
                        name_part = name_part[:-len(suffix)]
                        break
                name = name_part.replace("_", " ").title()

        devices.append({
            "energy_sensor": energy_sensor,
            "power_sensor": power_sensor,
            "name": name,
            "is_ev": is_ev,
        })

    # (#698) Fold same-measurement variants (lifetime/session/total/daily/…)
    # into one device. Grouped by stem; a group whose members the entity
    # registry places on DIFFERENT devices is left un-folded (two real loads
    # that merely share a naming shape).
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    order: List[str] = []
    for dev in devices:
        stem, rank = _variant_stem(dev["energy_sensor"])
        dev["_variant_rank"] = rank
        if stem not in grouped:
            order.append(stem)
        grouped.setdefault(stem, []).append(dev)

    folded: List[Dict[str, Any]] = []
    for stem in order:
        group = grouped[stem]
        reg_ids = {
            rid for rid in (
                _registry_device_id(hass, d["energy_sensor"]) for d in group
            ) if rid is not None
        }
        if len(group) == 1 or len(reg_ids) > 1:
            folded.extend(group)          # solo, or registry veto — keep all
            continue
        keep = min(group, key=lambda d: d["_variant_rank"])
        # the folded siblings may carry what the kept entry lacks
        keep["power_sensor"] = keep["power_sensor"] or next(
            (d["power_sensor"] for d in group if d["power_sensor"]), None)
        keep["is_ev"] = any(d["is_ev"] for d in group)
        dropped = [d["energy_sensor"] for d in group if d is not keep]
        _LOGGER.info(
            "Folded %d Energy Dashboard variants of the same load into %s "
            "(dropped: %s) — one physical device, one load row (#698)",
            len(group), keep["energy_sensor"], ", ".join(dropped),
        )
        folded.append(keep)
    for dev in folded:
        dev.pop("_variant_rank", None)
    devices = folded

    _LOGGER.debug("Found %d individual devices in Energy Dashboard", len(devices))
    return devices


async def validate_energy_dashboard_sensors(
    hass: HomeAssistant, config: EnergyDashboardConfig
) -> Dict[str, bool]:
    """Validate that the sensors from Energy Dashboard actually exist in HA.

    Args:
        hass: Home Assistant instance
        config: EnergyDashboardConfig to validate

    Returns:
        Dictionary mapping sensor names to their validity (True if exists)
    """
    sensors_to_check = {
        "solar_power": config.solar_power,
        "solar_energy": config.solar_energy,
        "grid_import_power": config.grid_import_power,
        "grid_import_energy": config.grid_import_energy,
        "grid_export_power": config.grid_export_power,
        "grid_export_energy": config.grid_export_energy,
        "battery_power": config.battery_power,
        "battery_charge_energy": config.battery_charge_energy,
        "battery_discharge_energy": config.battery_discharge_energy,
        "ev_power": config.ev_power,
        "ev_energy": config.ev_energy,
    }

    results = {}
    for name, entity_id in sensors_to_check.items():
        if entity_id:
            state = hass.states.get(entity_id)
            results[name] = state is not None
            if not results[name]:
                _LOGGER.warning("Sensor from Energy Dashboard not found: %s", entity_id)
        else:
            results[name] = False  # Not configured

    return results
