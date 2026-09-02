"""Solar Energy Management Integration.

This integration provides comprehensive solar energy management with:
- Real-time energy flow monitoring and optimization
- EV charging control with solar priority
- Battery management and discharge protection
- Peak load management and demand control
- Energy dashboard integration
- Sankey flow visualization

Best Practices Implementation:
- Async-first with proper error handling
- Graceful degradation for optional features
- Non-blocking initialization for better startup performance
- Service registry checks to prevent conflicts
- Comprehensive logging and diagnostics
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any, Dict, List

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, SupportsResponse, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.util import dt as dt_util
import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    MIN_PEAK_LIMIT_KW,
    MAX_PEAK_LIMIT_KW,
)
from .coordinator.sensor_reader import GRID_TRIGGER_HINTS
from .coordinator import SEMCoordinator

if TYPE_CHECKING:
    from .devices.base import ControllableDevice

_LOGGER = logging.getLogger(__name__)


def _content_hash_cache_bust(card_root: str, base_url: str, version: str) -> str:
    """Compute ``{version}-{sha1(content)[:8]}`` for a dashboard card asset.

    Used by every Lovelace-resource registration path so the ``?v=`` query
    follows file content. A bare timestamp (the previous behaviour) stayed
    constant across rsync deploys and let browsers serve a stale cached
    ``sem-localize.js`` even after the on-disk file was updated — surfacing
    as raw translation keys on the EV charge-mode selector (#301).

    ``base_url`` is the ``/local/custom_components/.../card/<path>`` URL;
    the trailing relative path is resolved against ``card_root`` (the
    deployed copy under ``/config/www/...``). Falls back to a bare
    ``version`` if the file can't be read so a transient disk error still
    busts the cache once and never deregisters a resource.
    """
    import hashlib

    rel = base_url.split("/dashboard/card/", 1)[-1]
    try:
        with open(os.path.join(card_root, rel), "rb") as f:
            return f"{version}-{hashlib.sha1(f.read()).hexdigest()[:8]}"
    except OSError:
        return version


_VERSION_STORE_VERSION = 1
_VERSION_STORE_KEY_PREFIX = "sem_seen_version_"

# #656 — entry_id → the devices detached at unload, parked so
# ``async_remove_entry`` still has something to deactivate. HA runs unload
# FIRST and pops the coordinator out of ``hass.data``, so by remove time there
# is no other way back to the loads SEM is holding. The controller's registry
# is still cleared at unload (the reload-leak contract); only the detached
# device objects live here. A reload drops the stash in ``async_setup_entry``
# without deactivating anything.
_PENDING_LOAD_TEARDOWN: Dict[str, List["ControllableDevice"]] = {}


async def _maybe_emit_upgrade_notification(hass, entry) -> None:
    """Fire a one-shot persistent notification when SEM has upgraded.

    Compares the integration's current ``manifest.json`` version to a
    locally-stored "last seen" version from ``hass.helpers.storage.Store``
    (per config entry). On version change — and only on change — emits
    a persistent notification telling the user to hard-refresh the
    browser. First install is silent (stored=None → record current,
    skip notify) so the user doesn't see an upgrade banner on day one.

    The notification message names the specific cache-bust failure
    mode (raw translation keys like ``today_plan_title`` showing in
    the dashboard) so the user can correlate what they see with the
    advice to hard-refresh.

    Failure of any sub-step (Store read/write, ``async_get_integration``,
    notification service call) is non-fatal — the caller wraps this in
    a ``try/except`` because a transient frontend issue should never
    block coordinator setup. We log at DEBUG so a healthy install
    stays quiet.
    """
    from homeassistant.helpers.storage import Store
    from homeassistant.loader import async_get_integration

    integration = await async_get_integration(hass, DOMAIN)
    current_version = str(integration.version or "unknown")

    store = Store(
        hass,
        _VERSION_STORE_VERSION,
        f"{_VERSION_STORE_KEY_PREFIX}{entry.entry_id}",
    )
    stored = await store.async_load() or {}
    previous_version = stored.get("version")

    if previous_version == current_version:
        return  # No change.

    # Record the new version regardless of whether we notify, so the
    # next setup compares against today's version.
    await store.async_save({"version": current_version})

    if not previous_version:
        # First install — silent record.
        return

    # Upgrade path — fire the one-shot notification.
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": f"SEM updated to v{current_version}",
            "message": (
                f"Solar Energy Management was upgraded from "
                f"v{previous_version} to v{current_version}.\n\n"
                "**Please hard-refresh your browser** "
                "(Ctrl+Shift+R on Windows/Linux, Cmd+Shift+R on Mac, "
                "or Shift+reload on the HA companion app) so the "
                "updated dashboard cards and translations load.\n\n"
                "Without a hard refresh you may see raw translation "
                "keys (e.g. `today_plan_title`, `charge_mode_off`) "
                "in some cards — that's HA's frontend bootstrap "
                "loading from cache and not picking up the new "
                "asset URLs.\n\n"
                "[CHANGELOG]"
                "(https://github.com/traktore-org/sem-community/"
                "blob/main/CHANGELOG.md)"
            ),
            "notification_id": (
                f"sem_upgrade_{current_version.replace('.', '_')}"
            ),
        },
        blocking=False,
    )
    _LOGGER.info(
        "SEM upgraded from v%s to v%s — emitted hard-refresh notification.",
        previous_version, current_version,
    )


class _SEMYAMLModeSkip(Exception):
    """Sentinel: bail out of the Lovelace resource registration block
    when the user is running YAML-mode Lovelace (#283). YAML-mode
    resources are read-only; the user has to add SEM's bundle to
    ``configuration.yaml`` themselves. Logged with the exact URLs above
    the raise; the outer ``except`` clause swallows this quietly so it
    doesn't get reported as a generic "could not register" warning."""


type SEMConfigEntry = ConfigEntry[SEMCoordinator]

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.BUTTON,
    Platform.TIME,
]


# ─────────────────────────────────────────────────────────────────────
# set_option helpers (#462/#464)
# ─────────────────────────────────────────────────────────────────────

# Structural option keys — changes to these require re-instantiating
# controllers because they wire SEM to HA entities. Everything else
# (modes, thresholds, targets, tunables) is read each cycle from
# coordinator.config and can be hot-swapped without a reload.
#
# Conservative on ``ev_chargers``: any change to the list shape
# (charger added/removed/per-charger entity rewired) needs a reload
# so the actuator bindings get refreshed. Per-charger tunables inside
# the list (charge_mode, target_soc, daily_ev_target) go through the
# select.py / number.py paths instead of set_option, so they don't
# hit this list.
# #485 G5: how long an armed reload-skip snapshot stays valid. The
# listener fires within milliseconds of the runtime write that armed
# it; anything older is a leftover that must not mask a real reload.
_SKIP_RELOAD_SNAPSHOT_TTL_S = 60.0

_SET_OPTION_STRUCTURAL_KEYS: frozenset[str] = frozenset({
    # #529: manual override for the battery SOC sensor when autodetect can't
    # reach it (SOC on a different device than the power sensor, or a generic
    # template helper). Read at SensorReader construction → must reload.
    "battery_soc_sensor",
    # #592/#597 — the solar/battery/grid POWER sensor overrides are read at
    # SensorReader construction too (same as battery_soc_sensor), so a
    # set_option change must reload for it to take effect; without this the
    # override only applied on the next full restart.
    "solar_production_sensor", "battery_power_sensor", "grid_power_sensor",
    # #593: hardware battery lifetime-cycle sensor (preferred over the estimate).
    "battery_cycles_sensor",
    "heat_pump_relay1_entity", "heat_pump_relay2_entity",
    "heat_pump_climate_entity", "heat_pump_power_sensor",
    "heat_pump_temperature_sensor",
    # #600 — load-device kWh energy counters (derive power when no power sensor);
    # read at controller construction → reload on change.
    "heat_pump_energy_sensor", "hot_water_energy_sensor",
    # #602 — heat pump / hot water rated power (W), read at controller
    # construction; was config-flow-only, now settable from the dashboard.
    "heat_pump_rated_power", "hot_water_rated_power",
    # #523: read at HeatPumpController construction, so a change must reload
    # to rebuild the controller with the new relay polarity.
    "heat_pump_invert_sg_ready",
    "hot_water_entity", "hot_water_power_sensor",
    "hot_water_temperature_sensor",
    "ev_chargers",
    # #523 Tier 3: the forced-discharge entity is read at battery-adapter
    # construction, so changing it must reload to rebuild the adapter.
    "battery_force_discharge_control_entity",
    # #528: the discharge-LIMIT control entity (battery protection) is read
    # from the coordinator's config snapshot, so a change must reload to take
    # effect (the snapshot is rebuilt on reload).
    "battery_discharge_control_entity",
    # #528: the discharge-protection toggle has no runtime switch entity, so a
    # set_option would otherwise hit the "unrouted → reload" path silently.
    # Declare it structural so the reload is explicit (decide_battery reads it
    # from the config snapshot, which is rebuilt on reload). Rarely changed.
    "battery_discharge_protection_enabled",
    # #523 multi-battery: per-battery control-entity lists are read at
    # adapter construction too, so a change must reload.
    "battery_force_discharge_entities",
    "battery_discharge_control_entities",
    # #523 Sessy / AC-coupled: per-battery power-strategy selects, also read
    # at adapter construction.
    "battery_strategy_entities",
    "battery_strategy_control_entity",
    # #523 AC-coupled bidirectional setpoint (charge = negative on the
    # force-discharge entity) — read at adapter construction.
    "battery_setpoint_bidirectional",
})


def _warn_missing_charger_entities(hass, charger_name, charger_id, to_check):
    """Warn about configured charger entity_ids absent from the state
    registry — DEFERRED past HA's warm-up (#763 beta.7).

    At SEM's setup many upstream integrations have not loaded yet; the
    old registration-time check declared onkelfu's (perfectly healthy)
    wallbox switch missing and sent the diagnosis down a dead end. Run
    after warm-up: entities still missing warn exactly as before —
    that's the real #315/#357/#462 symptom — and entities that appeared
    in the meantime log the recovery at DEBUG only. Returns the
    still-missing pairs.
    """
    missing = []
    for _attr, _eid in to_check:
        if not _eid:
            continue
        if hass.states.get(_eid) is None:
            missing.append((_attr, _eid))
    if missing:
        _LOGGER.warning(
            "EV charger '%s' (%s): %d configured entity ID(s) "
            "missing from HA's state registry — SEM commands to "
            "these silently no-op. Likely cause: the upstream "
            "integration renamed entities after a version upgrade "
            "(common with Wallbox/KEBA/Easee on HA core upgrades). "
            "Affected: %s",
            charger_name, charger_id, len(missing),
            ", ".join(f"{a}={e}" for a, e in missing),
        )
    else:
        _LOGGER.debug(
            "EV charger '%s' (%s): all configured entity IDs present "
            "after warm-up", charger_name, charger_id,
        )
    return missing


def build_welcome_message(config: dict) -> str:
    """The first-run checklist, describing THIS install (#805 fix 2).

    The old text told everyone to "pick an EV charge mode on the EV tab",
    but #595 removes that tab when no charger is configured — so the one
    reader who most needed guidance (owns a wallbox, hasn't told SEM about
    it) was pointed into a void and concluded the controls were missing
    (#803, they uninstalled). Every line here is either about something
    this install HAS, or an invitation to add what it lacks.

    It also states plainly what SEM will and will not touch. The previous
    wording promised "sensible defaults" while SEM was about to manage
    auto-discovered devices; since #805 those are monitor-only, and saying
    so is how the user can consent to it.
    """
    has_ev = bool(config.get("ev_chargers")
                  or config.get("ev_charging_power_sensor"))
    has_battery = bool(config.get("battery_capacity_kwh")
                       or config.get("battery_soc_sensor")
                       or config.get("battery_power_sensor"))

    lines = ["1. Confirm solar is reporting on the Energy tab"]
    if has_ev:
        lines.append("2. Pick a charge mode on the EV tab "
                     "(solar only, min + solar, solar + cheap, always max)")
    else:
        lines.append("2. Add your EV charger to let SEM manage charging — "
                     "Settings → Devices & Services → SEM → Configure. "
                     "Until then SEM leaves it alone.")
    if has_battery:
        lines.append("3. Set your battery reserve on the Battery tab")
    else:
        lines.append("3. Add your home battery, if you have one — "
                     "same Configure screen")

    return (
        "👋 Welcome! Your SEM dashboard is ready at "
        "[Open the SEM Dashboard](/sem-dashboard/home).\n\n"
        "**First-day checklist:**\n"
        + "\n".join(lines)
        + "\n\n**What SEM does right now:** it watches, and it controls "
          "only what you have configured. Devices it discovers on its own "
          "are set to *monitor* until you give them a mode in the device "
          "list — nothing gets switched behind your back."
    )


# (#805) What "looks like a car charger" means when SEM has to guess.
# Word-ish matching on purpose: a bare substring test turns the guess into
# noise (#781 — "charge" would fire on recharge_reminder), so a marker must
# sit on a word boundary of the object_id.
CHARGER_NAME_MARKERS = (
    "wallbox", "keba", "easee", "goe", "go_e", "echarger", "evse",
    "zaptec", "ladefreigabe", "ladestrom", "chargepoint", "openevse",
    "openwb", "heidelberg", "peblar", "charger",
)


def charger_shaped_devices(entity_ids) -> list:
    """Entity ids that look like an EV charger (#805).

    A guess, and labelled as one wherever its result is shown: the point is
    to turn an invisible import into an offer the user can accept or ignore,
    never to act on the guess.
    """
    import re

    out = []
    for eid in entity_ids or []:
        obj = str(eid).split(".", 1)[-1].lower()
        words = [w for w in re.split(r"[^a-z0-9]+", obj) if w]
        if any(m in words or any(w.startswith(m) and len(w) - len(m) <= 2
                                 for w in words)
               for m in CHARGER_NAME_MARKERS):
            out.append(eid)
    return out


def unmanaged_charger_repair(config: dict, candidates: list):
    """Should SEM raise "found a charger it does not manage"? (#805)

    Replaces the blanket ``ev_charger_not_configured`` repair, which fired
    for every install without a charger — including solar-only homes that
    own no car — and named nothing. This one fires only when discovery
    actually found something charger-shaped, and says WHICH device, which
    is the line that would have prevented #803.

    Returns the repair's translation payload, or None for silence.
    """
    if config.get("ev_chargers") or config.get("ev_charging_power_sensor") \
            or config.get("ev_connected_sensor"):
        return None
    if not candidates:
        return None
    return {
        "translation_key": "unmanaged_charger_found",
        "placeholders": {"name": candidates[0], "count": str(len(candidates))},
    }


def yaml_mode_repair(yaml_mode: bool, urls) -> dict | None:
    """(#799) Should SEM raise "your Lovelace is YAML-mode"?

    #283 detected the case and logged the resource URLs — but a log line
    is not a surface: the reporter met a dashboard full of Configuration
    Error cards, reinstalled twice, and only recovered by finding that one
    WARNING himself. The Repair says the same thing where a user looks,
    with the block to paste.

    Returns the repair's translation payload, or None for silence.
    """
    if not yaml_mode or not urls:
        return None
    block = "\n".join(f"  - url: {u}\n    type: module" for u in urls)
    return {
        "translation_key": "lovelace_yaml_mode",
        "placeholders": {"resources": block},
    }


def _coerce_switch_on(value) -> bool:
    """Interpret a set_option value as a switch on/off intent.

    YAML service data arrives as strings — plain truthiness turned
    ``"off"`` / ``"false"`` / ``"0"`` into turn_on (#485 G3).
    """
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "off", "no")
    return bool(value)


def _merge_ev_chargers_by_id(
    existing: list, incoming: list,
) -> list:
    """Merge an ``ev_chargers`` list by ``id`` rather than full-replace.

    Built for the set_option service path so a partial submit from the
    Config card (one charger's worth of fields) can never drop sibling
    chargers from the persisted state — the bug class behind #464.

    Contract:

    * Each entry in ``incoming`` is merged INTO the matching entry in
      ``existing`` by ``id``, with incoming fields winning. Fields
      present in the existing entry but absent from the incoming entry
      are preserved (no key is silently removed).
    * Existing chargers whose ``id`` is NOT in the incoming list are
      kept verbatim. This is the actual fix for the cross-talk: a
      one-charger update never affects siblings.
    * Incoming chargers without a matching existing ``id`` (a fresh
      add) are appended verbatim.
    * Non-dict entries on either side are skipped (defensive).
    * Output preserves the existing order; new chargers are appended.

    Pure function — no I/O, no HA dependencies. Tested in
    ``tests/test_set_option_smart_merge.py``.
    """
    incoming_by_id: dict[str, dict] = {}
    new_ids: list[str] = []
    existing_ids = {
        c.get("id") for c in (existing or []) if isinstance(c, dict)
    }
    for inc in incoming or []:
        if not isinstance(inc, dict):
            continue
        cid = inc.get("id")
        if not cid:
            # Id-less entries are untargetable ghosts: per-charger writes
            # match on ``id``, and at registration a ghost gets assigned a
            # positional ``ev_charger_<idx>`` id that can collide with a
            # real sibling. The Config card's nested editors used to
            # materialize such entries (``newChargers[idx] = {}``) — drop
            # them instead of appending.
            _LOGGER.warning(
                "Dropping id-less ev_chargers entry from merge: %s",
                dict(inc),
            )
            continue
        if cid in incoming_by_id:
            incoming_by_id[cid].update(inc)
        else:
            incoming_by_id[cid] = dict(inc)
            if cid not in existing_ids:
                new_ids.append(cid)

    # EXISTING order is the output order (#485 G2): charger list order
    # is load-bearing — index 0 is the fleet primary for the strategy
    # sensors and default surplus priorities derive from the position.
    # The previous incoming-first iteration let a partial submit (or
    # the setup-time heal, whose ``incoming`` is the poisoned options
    # list) silently reorder the fleet.
    merged: list[dict] = []
    merged_ids: set[str] = set()
    for c in existing or []:
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        if not cid or cid in merged_ids:
            continue
        base = dict(c)
        if cid in incoming_by_id:
            base.update(incoming_by_id[cid])
        merged.append(base)
        merged_ids.add(cid)
    for cid in new_ids:
        merged.append(dict(incoming_by_id[cid]))
    return merged


def persist_per_charger_option(
    hass, entry, coordinator, charger_id: str, key: str, value,
) -> None:
    """Persist ONE per-charger option without an integration reload.

    Single write path for every per-charger entity platform (#485 K2 —
    select/number/time each carried a ~30-line copy of this hardening,
    and the time.py copy was missed by the original #469 patch round,
    clobbering ev_chargers until v1.7.3-beta.5):

    * Copies charger dicts — in-place mutation leaves entry.options
      unchanged, so async_update_entry never persists (#245).
    * Falls back to ``entry.data.ev_chargers`` when options lacks the
      key — otherwise ``[]`` is written back and the ``{**data,
      **options}`` merge hides every charger on the next reload.
    * Recovers THIS charger from entry.data when a partially poisoned
      options list dropped its id (#462/#464) instead of silently
      no-op'ing the write.
    * Mirrors into ``coordinator.config`` and arms the reload-skip
      snapshot before the entry write.
    """
    new_options = {**(entry.options or {})}
    data_chargers = (entry.data or {}).get("ev_chargers") or []
    source_chargers = new_options.get("ev_chargers") or data_chargers
    ev_chargers = [dict(c) for c in source_chargers if isinstance(c, dict)]
    for charger in ev_chargers:
        if charger.get("id") == charger_id:
            charger[key] = value
            break
    else:
        recovered = next(
            (dict(c) for c in data_chargers
             if isinstance(c, dict) and c.get("id") == charger_id),
            {"id": charger_id},
        )
        recovered[key] = value
        ev_chargers.append(recovered)
        _LOGGER.warning(
            "Charger '%s' was missing from the stored ev_chargers list "
            "(ids: %s) — recovered it from entry.data so the %s write "
            "isn't lost",
            charger_id,
            [c.get("id") for c in ev_chargers[:-1]],
            key,
        )
    new_options["ev_chargers"] = ev_chargers
    if isinstance(getattr(coordinator, "config", None), dict):
        coordinator.config.update({**(entry.data or {}), **new_options})
        _refresh_runtime_config(coordinator)  # #547: apply without reload
    coordinator._skip_options_reload = new_options
    hass.config_entries.async_update_entry(entry, options=new_options)


def _refresh_runtime_config(coordinator) -> None:
    """Push construction-cached scalars into live controllers (#547).

    The ``persist_*`` writers update ``coordinator.config`` in place and arm
    ``_skip_options_reload`` so the entry write does NOT trigger a reload —
    which means any knob cached on a controller at construction would stay
    stale until a manual reload. Mirror ``async_update_config``'s refresh so
    those no-reload writes apply immediately too. Defensive: never let a
    refresh hiccup break the option persist itself.
    """

    # (#637) a changed mobile_notification_service must re-run service
    # detection — the notifier caches validation on first send (#47).
    _nm = getattr(coordinator, "_notification_manager", None)
    if _nm is not None:
        _nm._mobile_service_checked = False
    fn = getattr(coordinator, "refresh_runtime_config", None)
    if callable(fn):
        try:
            fn()
        except Exception:  # noqa: BLE001 — refresh must never break persist
            _LOGGER.debug("refresh_runtime_config failed", exc_info=True)


def _seed_legionella_time(coordinator, hw_device) -> None:
    """(#640) Seed the hot-water legionella timestamp AT registration.

    The old first-refresh restore ran BEFORE the device was registered —
    always a no-op — so a None timestamp read as 999 h overdue and every
    restart forced a grid-powered 65°C disinfection cycle (audit class 14).
    Stored time → restore; fresh install / unparsable → seed NOW so the
    first cycle is ~interval_hours away, not immediate. Idempotent across
    reloads (re-seeds from the same persisted value)."""
    from homeassistant.util import dt as dt_util
    try:
        stored = coordinator._storage.get_legionella_time() \
            if getattr(coordinator, "_storage", None) else None
        ts = dt_util.parse_datetime(stored) if stored else None
        hw_device.record_legionella_cycle(ts or dt_util.now())
    except (ValueError, TypeError):
        hw_device.record_legionella_cycle(dt_util.now())


def persist_global_option(hass, entry, coordinator, key: str, value) -> None:
    """Persist ONE scalar option key without an integration reload (#523).

    Used by the SINGLE-battery mode/reserve entities (``select.sem_battery_mode``
    / ``number.sem_battery_reserve_soc``), which write the global
    ``battery_mode`` / ``battery_reserve_soc`` keys rather than the per-battery
    list. Same no-reload contract as the per-charger / per-battery paths.
    """
    new_options = {**(entry.options or {})}
    new_options[key] = value
    if isinstance(getattr(coordinator, "config", None), dict):
        coordinator.config.update({**(entry.data or {}), **new_options})
        _refresh_runtime_config(coordinator)  # #547: apply without reload
    coordinator._skip_options_reload = new_options
    hass.config_entries.async_update_entry(entry, options=new_options)


def persist_per_battery_option(
    hass, entry, coordinator, idx: int, list_key: str, value, count: int,
) -> None:
    """Persist ONE per-battery option without an integration reload (#523).

    The battery-side mirror of :func:`persist_per_charger_option`, but
    POSITIONAL — per-battery control lives in idx-aligned list keys
    (``battery_modes`` / ``battery_reserve_socs``) parallel to the Energy
    Dashboard ``battery_power_list`` order, not an id-keyed dict list. The
    list is padded to ``count`` so a write to battery 2 never drops
    battery 1, and the no-reload contract (copy options, mirror into
    ``coordinator.config``, arm the reload-skip snapshot) matches the
    charger path so a live mode flip doesn't bounce the integration.
    """
    new_options = {**(entry.options or {})}
    src = new_options.get(list_key)
    if not isinstance(src, list):
        src = (entry.data or {}).get(list_key)
    lst = list(src) if isinstance(src, list) else []
    while len(lst) < count:
        lst.append(None)
    if 0 <= idx < len(lst):
        lst[idx] = value
    new_options[list_key] = lst
    if isinstance(getattr(coordinator, "config", None), dict):
        coordinator.config.update({**(entry.data or {}), **new_options})
        _refresh_runtime_config(coordinator)  # #547: apply without reload
    coordinator._skip_options_reload = new_options
    hass.config_entries.async_update_entry(entry, options=new_options)


def _heal_ev_chargers_options(
    data_chargers: list | None, opts_chargers: list | None,
) -> list | None:
    """Reconcile a poisoned ``entry.options.ev_chargers`` against entry.data.

    v1.7.2 through v1.7.3-beta.3 builds could corrupt the options-side
    charger list in several ways: the naive set_option full-replace from a
    stale Config-card cache (#464), the pre-#469 ``[]`` clobber in the
    per-charger select/number writers, the pre-beta.4 smart-merge
    fall-through, and the setup-time auto-discovery reseed that plants a
    single ``id: "ev_charger"`` entry when the merged list comes up empty.
    Once poisoned, the merge ``{**data, **options}`` hides data-side
    chargers forever and per-charger writes for the missing ids silently
    no-op — the "charger 2 does nothing" symptom (#462/#464).

    Heals by union-by-id: options-side fields win per charger, chargers
    that only exist in ``entry.data`` are restored, id-less ghost entries
    are dropped. Returns the healed list, or ``None`` when the stored list
    is already complete (no write needed). Pure function — tested in
    ``tests/test_ev_chargers_storage_heal.py``.
    """
    cleaned = [
        c for c in (opts_chargers or [])
        if isinstance(c, dict) and c.get("id")
    ]
    healed = _merge_ev_chargers_by_id(data_chargers or [], cleaned)
    if healed == list(opts_chargers or []):
        return None
    return healed


#: (#876) The Energy-Dashboard ENERGY COUNTERS, and only those.
#: ``EnergyDashboardConfig.to_dict()`` also carries power sensors and
#: ``has_*`` flags; those are live steering inputs the coordinator resolves
#: itself every cycle, and a migration that silently rewrote them would be a
#: far larger promise than the one being made here.
_ENERGY_COUNTER_KEYS = (
    "solar_energy_sensor",
    "grid_import_energy_sensor",
    "grid_export_energy_sensor",
    "battery_charge_energy_sensor",
    "battery_discharge_energy_sensor",
)


async def async_migrate_entry(hass: HomeAssistant, entry: SEMConfigEntry) -> bool:
    """Migrate old config entry data to current schema.

    Migrations:
    - v1 → v2 (#98): `battery_priority_soc` semantics changed from
      legacy 3-zone "battery target before EV" (default 80) to 4-zone
      "Zone 1 floor: below this all solar → battery, EV blocked"
      (default 30). Existing entries that still carry the legacy 80%
      get remapped down to 30% so the 4-zone strategy actually leaves
      Zone 1 on a normally-charged battery.
    """
    _LOGGER.info(
        "Migrating SEM config entry from version %s.%s",
        entry.version, entry.minor_version
    )

    # Accumulators threaded across all migration steps. Each step starts
    # from these (not from ``entry.options`` / ``entry.data``) so a
    # multi-version upgrade (e.g. v3 → v5 in one call) doesn't lose the
    # earlier step's mutations. Pre-#277 each step read ``entry.options``
    # afresh; in real HA ``async_update_entry`` mutates the entry and the
    # next read picks up the change, but in tests (and in any harness
    # mocking the entry) the second step then overwrote the first. The
    # explicit accumulator makes the chain deterministic on both paths.
    accumulated_data = {**entry.data}
    accumulated_options = {**entry.options}

    if entry.version < 2:
        try:
            from .consts.core import (
                DEFAULT_BATTERY_BUFFER_SOC,
                DEFAULT_BATTERY_AUTO_START_SOC,
            )

            new_data = {**accumulated_data}
            new_options = {**accumulated_options}
            legacy_priority = max(
                new_options.get("battery_priority_soc") if new_options.get("battery_priority_soc") is not None else 0,
                new_data.get("battery_priority_soc") if new_data.get("battery_priority_soc") is not None else 0,
            )
            # Anything ≥ 50 is the legacy 3-zone meaning — remap.
            if legacy_priority >= 50:
                _LOGGER.warning(
                    "Migrating battery_priority_soc %s → 30 (4-zone semantics, see #98)",
                    legacy_priority,
                )
                new_data["battery_priority_soc"] = 30
                new_options.pop("battery_priority_soc", None)

            # Seed any 4-zone keys missing or null on legacy entries so the
            # number entities boot with sensible state.
            for key, default in (
                ("battery_buffer_soc", DEFAULT_BATTERY_BUFFER_SOC),
                ("battery_auto_start_soc", DEFAULT_BATTERY_AUTO_START_SOC),
            ):
                if new_data.get(key) is None:
                    new_data[key] = default

            hass.config_entries.async_update_entry(
                entry,
                data=new_data,
                options=new_options,
                version=2,
                minor_version=1,
            )
            accumulated_data, accumulated_options = new_data, new_options
        except Exception as e:
            _LOGGER.error(
                "Migration from v%s failed — keeping original config: %s",
                entry.version, e,
            )
            return False

    if entry.version < 3:
        try:
            # v2 → v3: Wrap flat ev_* keys into ev_chargers list for multi-charger support
            new_data = {**accumulated_data}
            new_options = {**accumulated_options}
            full = {**new_data, **new_options}

            # Only migrate if flat EV keys exist and ev_chargers doesn't
            if full.get("ev_charging_power_sensor") and "ev_chargers" not in full:
                _EV_FLAT_KEYS = [
                    "ev_connected_sensor", "ev_charging_sensor",
                    "ev_charging_power_sensor", "ev_charger_service",
                    "ev_charger_service_entity_id", "ev_current_control_entity",
                    "ev_current_sensor", "ev_total_energy_sensor",
                    "ev_session_energy_sensor", "ev_service_param_name",
                    "ev_service_device_id", "ev_start_stop_entity",
                    "ev_charge_mode_entity", "ev_charge_mode_start",
                    "ev_charge_mode_stop", "ev_start_service",
                    "ev_start_service_data", "ev_stop_service",
                    "ev_stop_service_data", "ev_charger_needs_cycle",
                    "ev_surplus_priority", "ev_load_priority",
                ]
                charger_0 = {"id": "ev_charger", "name": "EV Charger"}
                for k in _EV_FLAT_KEYS:
                    val = new_options.get(k) or new_data.get(k)
                    if val is not None:
                        charger_0[k] = val
                new_options["ev_chargers"] = [charger_0]
                _LOGGER.info(
                    "Migrated flat EV config to ev_chargers list (1 charger)"
                )

            hass.config_entries.async_update_entry(
                entry,
                data=new_data,
                options=new_options,
                version=3,
                minor_version=1,
            )
            accumulated_data, accumulated_options = new_data, new_options
        except Exception as e:
            _LOGGER.error(
                "Migration from v%s to v3 failed — keeping original config: %s",
                entry.version, e,
            )
            return False

    if entry.version < 4:
        try:
            # v3 → v4 (#255): per-charger entities are becoming the source of truth, so
            # the duplicate GLOBAL EV settings will be removed. Seed each charger's
            # per-charger value from the matching global where it's unset, so removing the
            # global later never silently resets a user's configured value. Behaviour-
            # neutral today (per-charger already falls back to the global at runtime).
            _SEED_KEYS = (
                "daily_ev_target", "daily_ev_target_max",
                "ev_target_soc", "ev_target_soc_max",
                # ``ev_night_initial_current`` is the LEGACY key name at
                # v3 time — v9→v10 (#441) renames it to ``initial_current``
                # later in the chain. Keep the legacy spelling here so a
                # v3 entry's global value is actually picked up.
                "ev_min_current", "ev_night_initial_current",
                "ev_kwh_per_100km", "ev_target_type",
                # #255 Phase 4 — also converted to per-charger
                "ev_charging_mode", "ev_phases",
                # #246 Phase 2 — per-charger charge-by deadline
                "ev_target_time",
            )
            new_data = {**accumulated_data}
            new_options = {**accumulated_options}
            full = {**new_data, **new_options}
            chargers = new_options.get("ev_chargers", new_data.get("ev_chargers"))
            if isinstance(chargers, list):
                seeded = []
                for c in chargers:
                    c = dict(c) if isinstance(c, dict) else c
                    if isinstance(c, dict):
                        for key in _SEED_KEYS:
                            gval = full.get(key)
                            # ev_target_type carries a legacy alias (ev_target_mode, #235)
                            if key == "ev_target_type" and gval is None:
                                gval = full.get("ev_target_mode")
                            if c.get(key) is None and gval is not None:
                                c[key] = gval
                    seeded.append(c)
                new_options["ev_chargers"] = seeded
            hass.config_entries.async_update_entry(
                entry, data=new_data, options=new_options,
                version=4, minor_version=1,
            )
            accumulated_data, accumulated_options = new_data, new_options
        except Exception as e:
            _LOGGER.error(
                "Migration from v%s to v4 failed — keeping original config: %s",
                entry.version, e,
            )
            return False

    if entry.version < 5:
        try:
            # v4 → v5 (#277 Phase A): seed per-charger ``charge_mode`` from
            # the existing toggle state. The new selector is the consolidated
            # user-intent layer that will replace the four-toggle UX in
            # Phase B; here we just derive the equivalent named mode so the
            # selector reflects the user's actual current behaviour on first
            # boot post-upgrade. Legacy toggles are kept unchanged — they
            # remain authoritative for the strategy machine until Phase B
            # makes ``charge_mode`` the source of truth.
            new_data = {**accumulated_data}
            new_options = {**accumulated_options}
            full = {**new_data, **new_options}
            chargers = new_options.get("ev_chargers", new_data.get("ev_chargers"))
            if isinstance(chargers, list):
                seeded = []
                for c in chargers:
                    c = dict(c) if isinstance(c, dict) else c
                    if isinstance(c, dict) and c.get("charge_mode") is None:
                        c["charge_mode"] = _derive_charge_mode(
                            c, full, hass,
                        )
                        _LOGGER.info(
                            "Charger %s: derived charge_mode=%s from legacy toggles",
                            c.get("id", "ev_charger"), c["charge_mode"],
                        )
                    seeded.append(c)
                new_options["ev_chargers"] = seeded

            hass.config_entries.async_update_entry(
                entry, data=new_data, options=new_options,
                version=5, minor_version=1,
            )
            accumulated_data, accumulated_options = new_data, new_options
        except Exception as e:
            _LOGGER.error(
                "Migration from v%s to v5 failed — keeping original config: %s",
                entry.version, e,
            )
            return False

    if entry.version < 6:
        try:
            # v5 → v6 (#277 Phase B fix-up): narrow re-derivation for the
            # pv/auto + tariff_on combinations that Phase A's derivation
            # silently dropped (was: ``if mode == "auto" and tariff``,
            # which missed the legacy ``mode=pv`` group).  Phase B fixed
            # the derivation in both ``_derive_charge_mode`` and
            # ``effective_charge_mode_for`` to also map
            # ``pv/self_consumption + tariff_on`` → ``solar_plus_cheap``;
            # this step propagates that fix to chargers that already
            # ran through Phase A's v4→v5 with the buggy derivation.
            #
            # Condition is unambiguous: stored mode is the catch-all
            # ``min_plus_solar``, legacy mode is one of the pv-family,
            # and the per-charger tariff switch is currently ON. That
            # combination can only be produced by Phase A's missing
            # tariff branch — a user who explicitly picked
            # ``min_plus_solar`` from the new selector AFTER Phase A
            # would also satisfy the condition, but their UI experience
            # is improved by the fix: the selector label finally matches
            # the tariff intent they expressed.
            new_data = {**accumulated_data}
            new_options = {**accumulated_options}
            full = {**new_data, **new_options}
            chargers = new_options.get("ev_chargers", new_data.get("ev_chargers"))
            if isinstance(chargers, list):
                fixed = []
                for c in chargers:
                    c = dict(c) if isinstance(c, dict) else c
                    if (
                        isinstance(c, dict)
                        and c.get("charge_mode") == "min_plus_solar"
                    ):
                        legacy_mode = (
                            c.get("ev_charging_mode")
                            or full.get("ev_charging_mode")
                            or "pv"
                        )
                        cid = c.get("id", "ev_charger")
                        tariff_on = hass.states.is_state(
                            f"switch.sem_charger_{cid}_tariff_optimized", "on",
                        )
                        if (
                            tariff_on
                            and legacy_mode in ("pv", "auto", "self_consumption")
                        ):
                            c["charge_mode"] = "solar_plus_cheap"
                            _LOGGER.info(
                                "Charger %s: corrected charge_mode "
                                "min_plus_solar → solar_plus_cheap "
                                "(tariff intent preserved)",
                                cid,
                            )
                    fixed.append(c)
                new_options["ev_chargers"] = fixed
            hass.config_entries.async_update_entry(
                entry, data=new_data, options=new_options,
                version=6, minor_version=1,
            )
            accumulated_data, accumulated_options = new_data, new_options
        except Exception as e:
            _LOGGER.error(
                "Migration from v%s to v6 failed — keeping original config: %s",
                entry.version, e,
            )
            return False

    if entry.version < 7:
        try:
            # v6 → v7 (#277 Phase C): drop the now-dead legacy
            # ``ev_charging_mode`` per-charger key. Phase C made the
            # named ``charge_mode`` the authoritative input to both
            # the strategy machine and ``_tariff_optimized_for``; the
            # legacy mode string is no longer read anywhere. Removing
            # it from the persisted config prevents stale values from
            # leaking back into the UI (the ``select.sem_charger_<id>
            # _ev_charging_mode`` entity is also retired in Phase C —
            # the entity registry's stale-cleanup in ``select.py``
            # purges the orphans).
            #
            # The corresponding legacy switches were removed from
            # ``switch.py`` in Phase C; the registry's stale-cleanup
            # in that file removes the per-charger night/smart/tariff
            # switch entries the same way.
            new_data = {**accumulated_data}
            new_options = {**accumulated_options}
            chargers = new_options.get("ev_chargers", new_data.get("ev_chargers"))
            if isinstance(chargers, list):
                cleaned = []
                for c in chargers:
                    c = dict(c) if isinstance(c, dict) else c
                    if isinstance(c, dict) and "ev_charging_mode" in c:
                        removed_value = c.pop("ev_charging_mode")
                        _LOGGER.info(
                            "Charger %s: dropped dead config key "
                            "ev_charging_mode=%s (Phase C — charge_mode "
                            "is authoritative)",
                            c.get("id", "ev_charger"), removed_value,
                        )
                    cleaned.append(c)
                new_options["ev_chargers"] = cleaned
            # Top-level ``ev_charging_mode`` (legacy global default) is
            # also gone now — nothing reads it. Same removal logic; the
            # top level only had it via #255 seeding, never the source
            # of truth post-v4.
            if "ev_charging_mode" in new_options:
                new_options.pop("ev_charging_mode")
            hass.config_entries.async_update_entry(
                entry, data=new_data, options=new_options,
                version=7, minor_version=1,
            )
            accumulated_data, accumulated_options = new_data, new_options
        except Exception as e:
            _LOGGER.error(
                "Migration from v%s to v7 failed — keeping original config: %s",
                entry.version, e,
            )
            return False

    if entry.version < 8:
        try:
            # v7 → v8 (#359): flip stored ``tariff_classification_mode``
            # from "static" to "percentile" when ``tariff_mode == "dynamic"``.
            # Background: percentile became the install default in beta.12
            # (#373) because the static 0.15/0.35 CHF cutoffs misclassify
            # dynamic-tariff prices across every non-Swiss market. Entries
            # created before that still carry "static" in storage even after
            # the install default changed, and the static branch in
            # ``tariff_provider._classify_price`` keeps firing — visible
            # symptom (#359): RienduPre's ``classifier_path`` attribute
            # reading ``static_fixed_cutoffs`` while the live price is well
            # outside any reasonable static band. Idempotent: a user who
            # explicitly wants static classification on a calendar/static
            # tariff is untouched (gated on dynamic mode).
            new_data = {**accumulated_data}
            new_options = {**accumulated_options}
            full = {**new_data, **new_options}
            if full.get("tariff_mode") == "dynamic":
                flipped = False
                if new_options.get("tariff_classification_mode") == "static":
                    new_options["tariff_classification_mode"] = "percentile"
                    flipped = True
                if new_data.get("tariff_classification_mode") == "static":
                    new_data["tariff_classification_mode"] = "percentile"
                    flipped = True
                if flipped:
                    _LOGGER.info(
                        "Migrated tariff_classification_mode static→percentile "
                        "for dynamic tariff (#359)"
                    )
            hass.config_entries.async_update_entry(
                entry, data=new_data, options=new_options,
                version=8, minor_version=1,
            )
            accumulated_data, accumulated_options = new_data, new_options
        except Exception as e:
            _LOGGER.error(
                "Migration from v%s to v8 failed — keeping original config: %s",
                entry.version, e,
            )
            return False

    if entry.version < 9:
        try:
            # v8 → v9 (#440 ADR 0010 #3): every ``ev_chargers`` entry
            # gets a ``vehicle_min_current`` field defaulting to ``None``
            # (= "use the loadpoint ``ev_min_current``"). Optional per-car
            # override letting users record handshake-floor minimums
            # (e.g. Renault Zoe ~9 A) without raising the SEM-side floor
            # other chargers in the fleet may want at 6 A. Forward-compat:
            # existing entries that already have the key are left alone.
            new_data = {**accumulated_data}
            new_options = {**accumulated_options}
            for bag in (new_data, new_options):
                chargers = bag.get("ev_chargers")
                if isinstance(chargers, list):
                    for c in chargers:
                        if isinstance(c, dict) and "vehicle_min_current" not in c:
                            c["vehicle_min_current"] = None
            hass.config_entries.async_update_entry(
                entry, data=new_data, options=new_options,
                version=9, minor_version=1,
            )
            accumulated_data, accumulated_options = new_data, new_options
        except Exception as e:
            _LOGGER.error(
                "Migration from v%s to v9 failed — keeping original config: %s",
                entry.version, e,
            )
            return False

    if entry.version < 10:
        try:
            # v9 → v10 (#441): rename ``ev_night_initial_current`` to
            # ``initial_current`` at both the top level (legacy global
            # key) and on each ``ev_chargers`` entry. The "night" prefix
            # was misleading — the value is the session-start ramp
            # current, applied whenever a session begins, not strictly
            # at nighttime. Display label moves from "Start Amps" to
            # "Vehicle Start Amps" to group with the new per-vehicle
            # Min Amps. The old ``number.sem_charger_<id>_night_initial_current``
            # entity is auto-removed by ``number.py:_cleanup_stale_entities``
            # on next setup (the description key is renamed so the old
            # key is no longer in the valid_keys set).
            new_data = {**accumulated_data}
            new_options = {**accumulated_options}
            for bag in (new_data, new_options):
                if "ev_night_initial_current" in bag and "initial_current" not in bag:
                    bag["initial_current"] = bag.pop("ev_night_initial_current")
                elif "ev_night_initial_current" in bag:
                    bag.pop("ev_night_initial_current")  # both present — drop stale
                chargers = bag.get("ev_chargers")
                if isinstance(chargers, list):
                    for c in chargers:
                        if not isinstance(c, dict):
                            continue
                        if "ev_night_initial_current" in c and "initial_current" not in c:
                            c["initial_current"] = c.pop("ev_night_initial_current")
                        elif "ev_night_initial_current" in c:
                            c.pop("ev_night_initial_current")
            hass.config_entries.async_update_entry(
                entry, data=new_data, options=new_options,
                version=10, minor_version=1,
            )
            accumulated_data, accumulated_options = new_data, new_options
        except Exception as e:
            _LOGGER.error(
                "Migration from v%s to v10 failed — keeping original config: %s",
                entry.version, e,
            )
            return False

    if entry.version < 11:
        # v10 → v11 (#446): pre-#446 the Configuration tab allowed users to
        # save ``ev_target_type="soc"`` without configuring a
        # ``vehicle_soc_entity``. The runtime then silently fell back to
        # the taper detector's ``estimated_soc`` to compute the kWh
        # budget — causing the PROD 2026-06-06 IDLE-stuck-at-120 W bug.
        # Going forward the GUI prevents the bad combination; here we
        # clean up the existing data so the runtime sees only valid
        # ``(ev_target_type, vehicle_soc_entity)`` pairs.
        try:
            new_data = {**accumulated_data}
            new_options = {**accumulated_options}
            cleaned = 0

            def _scrub(bag: dict) -> int:
                """Clean up a data/options bag in place. Returns scrubs."""
                scrubs = 0
                # Per-charger entries
                chargers = bag.get("ev_chargers")
                if isinstance(chargers, list):
                    for c in chargers:
                        if not isinstance(c, dict):
                            continue
                        if c.get("ev_target_type") == "soc" and not c.get("vehicle_soc_entity"):
                            c["ev_target_type"] = "kwh"
                            scrubs += 1
                # Integration-level legacy default (single-charger installs)
                if (
                    bag.get("ev_target_type") == "soc"
                    and not any(
                        c.get("vehicle_soc_entity")
                        for c in (bag.get("ev_chargers") or [])
                        if isinstance(c, dict)
                    )
                ):
                    bag["ev_target_type"] = "kwh"
                    scrubs += 1
                # Legacy field name ``ev_target_mode`` — same treatment
                if (
                    bag.get("ev_target_mode") == "soc"
                    and not any(
                        c.get("vehicle_soc_entity")
                        for c in (bag.get("ev_chargers") or [])
                        if isinstance(c, dict)
                    )
                ):
                    bag["ev_target_mode"] = "kwh"
                    scrubs += 1
                return scrubs

            cleaned += _scrub(new_data)
            cleaned += _scrub(new_options)

            hass.config_entries.async_update_entry(
                entry, data=new_data, options=new_options,
                version=11, minor_version=1,
            )
            accumulated_data, accumulated_options = new_data, new_options
            if cleaned:
                _LOGGER.info(
                    "#446 cleanup: %d ev_target_type field(s) reset from 'soc' "
                    "to 'kwh' (no vehicle_soc_entity configured)", cleaned,
                )
        except Exception as e:
            _LOGGER.error(
                "Migration from v%s to v11 failed — keeping original config: %s",
                entry.version, e,
            )
            return False

    if entry.version < 12:
        # v11 → v12 (#135): drop the stale top-level ``ev_session_energy_sensor``
        # left over from the v2 → v3 multi-charger migration. The per-charger
        # ``ev_chargers[].ev_session_energy_sensor`` has been the canonical
        # source since v3; the top-level copy was kept for back-compat but
        # is never read by any decision path. PROD 2026-06-07 surfaced a
        # case where it pointed at the wrong sensor (``keba_p30_energy_target``
        # — the user setpoint, always 0) and confused diagnostics. Drop it.
        try:
            new_data = {**accumulated_data}
            new_options = {**accumulated_options}
            # Combine chargers from BOTH bags — the chargers list lives in
            # one or the other depending on install age, and the stale
            # top-level key can live in either too. We need the union when
            # deciding whether to drop.
            chargers_union: list = []
            for bag in (new_data, new_options):
                bag_chargers = bag.get("ev_chargers")
                if isinstance(bag_chargers, list):
                    chargers_union.extend(c for c in bag_chargers if isinstance(c, dict))
            any_per_charger = any(
                c.get("ev_session_energy_sensor") for c in chargers_union
            )
            cleaned = 0
            if any_per_charger:
                for bag in (new_data, new_options):
                    if "ev_session_energy_sensor" in bag:
                        bag.pop("ev_session_energy_sensor", None)
                        cleaned += 1
            hass.config_entries.async_update_entry(
                entry, data=new_data, options=new_options,
                version=12, minor_version=1,
            )
            accumulated_data, accumulated_options = new_data, new_options
            if cleaned:
                _LOGGER.info(
                    "#135 cleanup: dropped stale top-level "
                    "ev_session_energy_sensor from %d bag(s); per-charger "
                    "value remains canonical", cleaned,
                )
        except Exception as e:
            _LOGGER.error(
                "Migration from v%s to v12 failed — keeping original config: %s",
                entry.version, e,
            )
            return False

    if entry.version < 13:
        # v12 → v13 (#470): split the conflated ``ev_surplus_priority`` into
        # a surplus-allocation order and a load-shed order. Seed each
        # charger's ``ev_shed_priority`` from its current
        # ``ev_surplus_priority`` (legacy alias ``ev_load_priority``) so the
        # decoupling is behaviour-neutral until the user deliberately
        # diverges them. Writing the value explicitly (rather than relying
        # on the runtime fallback) means a later flip of one field is an
        # obvious, isolated change in the config.
        try:
            new_data = {**accumulated_data}
            new_options = {**accumulated_options}
            full = {**new_data, **new_options}
            seeded = 0
            for bag in (new_data, new_options):
                chargers = bag.get("ev_chargers")
                if not isinstance(chargers, list):
                    continue
                rebuilt = []
                for c in chargers:
                    if isinstance(c, dict) and c.get("ev_shed_priority") is None:
                        c = dict(c)
                        src = c.get("ev_surplus_priority")
                        if src is None:
                            src = c.get("ev_load_priority")
                        if src is None:
                            src = full.get("ev_surplus_priority")
                        if src is not None:
                            c["ev_shed_priority"] = int(src)
                            seeded += 1
                    rebuilt.append(c)
                bag["ev_chargers"] = rebuilt
            hass.config_entries.async_update_entry(
                entry, data=new_data, options=new_options,
                version=13, minor_version=1,
            )
            accumulated_data, accumulated_options = new_data, new_options
            if seeded:
                _LOGGER.info(
                    "#470: seeded ev_shed_priority from ev_surplus_priority "
                    "for %d charger(s)", seeded,
                )
        except Exception as e:
            _LOGGER.error(
                "Migration from v%s to v13 failed — keeping original config: %s",
                entry.version, e,
            )
            return False

    if entry.version < 14:
        # v13 → v14 (#533): deactivate battery→grid arbitrage for the stable
        # release. A restart that stranded an in-flight Huawei forcible
        # discharge drained a real battery to its reserve floor (#532), so the
        # selling path is being held back until it has soaked. Force the global
        # toggle OFF on upgrade; the dashboard arbitrage section is hidden too,
        # so it can't be re-enabled from the UI. The decision code + per-battery
        # modes stay intact — arbitrage returns in a later release (#533).
        try:
            new_data = {**accumulated_data}
            new_options = {**accumulated_options}
            was_on = bool(
                new_options.get("battery_grid_arbitrage_enabled")
                or new_data.get("battery_grid_arbitrage_enabled")
            )
            new_data["battery_grid_arbitrage_enabled"] = False
            new_options["battery_grid_arbitrage_enabled"] = False
            hass.config_entries.async_update_entry(
                entry, data=new_data, options=new_options,
                version=14, minor_version=1,
            )
            accumulated_data, accumulated_options = new_data, new_options
            if was_on:
                _LOGGER.warning(
                    "#533: battery→grid arbitrage was enabled — forced OFF for "
                    "the stable release (re-enabled in a later version after "
                    "review/soak).",
                )
        except Exception as e:
            _LOGGER.error(
                "Migration from v%s to v14 failed — keeping original config: %s",
                entry.version, e,
            )
            return False

    if entry.version < 15:
        # v14 → v15 (#576): the per-charger ``ev_shed_priority`` knob is
        # retired. Surplus order AND shed order are now the single drag-list
        # position (shed = the reverse walk — latest-to-charge sheds first),
        # so the separate field is dead. Strip it from every stored charger so
        # upgraded installs don't carry an ignored value. ``ev_surplus_priority``
        # is kept — it seeds the drag order at boot.
        try:
            new_data = {**accumulated_data}
            new_options = {**accumulated_options}
            stripped = 0
            for bag in (new_data, new_options):
                chargers = bag.get("ev_chargers")
                if not isinstance(chargers, list):
                    continue
                rebuilt = []
                for c in chargers:
                    if isinstance(c, dict) and "ev_shed_priority" in c:
                        c = {k: v for k, v in c.items() if k != "ev_shed_priority"}
                        stripped += 1
                    rebuilt.append(c)
                bag["ev_chargers"] = rebuilt
            hass.config_entries.async_update_entry(
                entry, data=new_data, options=new_options,
                version=15, minor_version=1,
            )
            accumulated_data, accumulated_options = new_data, new_options
            if stripped:
                _LOGGER.info(
                    "#576: removed the retired ev_shed_priority from %d "
                    "charger(s) — shed order now follows the drag list", stripped,
                )
        except Exception as e:
            _LOGGER.error(
                "Migration from v%s to v15 failed — keeping original config: %s",
                entry.version, e,
            )
            return False

    if entry.version < 16:
        # v15 → v16 (#604): retire the remaining legacy EV priority flags.
        # ``ev_load_priority`` was a pre-#470 alias for the surplus priority —
        # map it into ``ev_surplus_priority`` where that is absent, then drop
        # it. ``ev_shed_priority`` (already stripped from chargers in v15) and
        # ``ev_priority_over_battery`` (fed a planner knob that was never
        # reachable from any UI, so it always held its default) are deleted
        # wherever they linger — top level AND per-charger entries. The ONE
        # drag list (#576) is the single priority axis; shed order stays the
        # reverse walk (#470 rule preserved by list position).
        _LEGACY_PRIO_KEYS = (
            "ev_load_priority", "ev_shed_priority", "ev_priority_over_battery",
        )
        try:
            new_data = {**accumulated_data}
            new_options = {**accumulated_options}
            mapped = removed = 0
            # Captured BEFORE any alias mapping: only an ORIGINAL global
            # canonical outranked the per-charger alias in the old fallback
            # chain (charger-surplus → global-surplus → charger-alias →
            # global-alias). A mapped global ALIAS ranked BELOW the
            # charger alias, so it must not block the per-charger mapping.
            _orig_global_surplus = (
                new_data.get("ev_surplus_priority")
                if new_data.get("ev_surplus_priority") is not None
                else new_options.get("ev_surplus_priority")
            )
            for bag in (new_data, new_options):
                # top-level: map alias → canonical, then delete legacy keys
                if new_data.get("ev_surplus_priority") is None \
                        and new_options.get("ev_surplus_priority") is None \
                        and bag.get("ev_load_priority") is not None:
                    try:
                        bag["ev_surplus_priority"] = int(bag["ev_load_priority"])
                        mapped += 1
                    except (TypeError, ValueError):
                        pass
                for k in _LEGACY_PRIO_KEYS:
                    if k in bag:
                        del bag[k]
                        removed += 1
                chargers = bag.get("ev_chargers")
                if not isinstance(chargers, list):
                    continue
                rebuilt = []
                for c in chargers:
                    if isinstance(c, dict):
                        c = dict(c)
                        if _orig_global_surplus is None \
                                and c.get("ev_surplus_priority") is None \
                                and c.get("ev_load_priority") is not None:
                            try:
                                c["ev_surplus_priority"] = int(c["ev_load_priority"])
                                mapped += 1
                            except (TypeError, ValueError):
                                pass
                        for k in _LEGACY_PRIO_KEYS:
                            if k in c:
                                del c[k]
                                removed += 1
                    rebuilt.append(c)
                bag["ev_chargers"] = rebuilt
            hass.config_entries.async_update_entry(
                entry, data=new_data, options=new_options,
                version=16, minor_version=1,
            )
            accumulated_data, accumulated_options = new_data, new_options
            if mapped or removed:
                _LOGGER.info(
                    "#604: retired legacy EV priority flags — mapped %d "
                    "ev_load_priority value(s) to ev_surplus_priority, "
                    "removed %d legacy key(s)", mapped, removed,
                )
        except Exception as e:
            _LOGGER.error(
                "Migration from v%s to v16 failed — keeping original config: %s",
                entry.version, e,
            )
            return False

    if entry.version < 17:
        # (#758) v1.8 turns the energy plan into an ACTUATOR: its blocks
        # drive the EV charger, the battery and the cheap-hours loads. The
        # kill switch is ``switch.sem_energy_plan_actuation``, and it defaults
        # to on — correct for a fresh install, where the user chose the
        # feature, and wrong for an UPGRADE, where nobody chose anything.
        # RestoreEntity cannot help: the switch is new, so there is no prior
        # state to restore and every upgrading install lands on the default.
        #
        # So the migration writes the value down. Not to change it — the
        # answer is the same True — but to turn an implied default into a
        # recorded decision, and to say so once, in the one place a user
        # reliably reads. An explicit False is never touched: someone who
        # already turned it off has decided, and a migration that overrides
        # a decision is worse than one that never ran.
        try:
            new_options = {**accumulated_options}
            announce = "energy_plan_actuation" not in new_options
            if announce:
                new_options["energy_plan_actuation"] = True
            hass.config_entries.async_update_entry(
                entry, data={**accumulated_data}, options=new_options,
                version=17, minor_version=1,
            )
            accumulated_options = new_options
        except Exception as e:
            _LOGGER.error(
                "Migration from v%s to v17 failed — keeping original "
                "config: %s", entry.version, e,
            )
            return False
        if announce:
            # Deliberately OUTSIDE the migration's try: the option is
            # already written and the entry already bumped. An
            # announcement that cannot be delivered (no notification
            # service in a minimal hass, a busy bus) is a missed message,
            # not a failed migration — failing here would roll a user
            # back over a notification.
            try:
                await hass.services.async_call(
                    "persistent_notification", "create",
                    {
                        "title": "SEM now plans your night",
                        "message": (
                            "This version lets the energy plan drive the "
                            "hardware: your EV charger, battery and "
                            "cheap-hours devices now run in the windows the "
                            "plan picks, instead of only being advised.\n\n"
                            "It is **on**. To go back to the purely reactive "
                            "behaviour, turn off "
                            "`switch.sem_energy_plan_actuation` — the plan "
                            "stays visible on the Energy Plan card either "
                            "way.\n\n"
                            "[How to read tonight's plan]"
                            "(https://github.com/traktore-org/sem-community/"
                            "blob/develop/docs/ENERGY_PLANNER.md)"
                        ),
                        "notification_id": "sem_energy_plan_actuation_v18",
                    },
                    blocking=False,
                )
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning(
                    "#758: energy-plan actuation notice not delivered (%s) — "
                    "the option is written; the switch is "
                    "switch.sem_energy_plan_actuation", e,
                )

    if entry.version < 18:
        # (#638) The planner was named for the night it started with, and it
        # outgrew the name — it plans the day too. Renaming the code is free.
        # Renaming a RECORDED DECISION is not: v17 wrote the actuation answer
        # under ``overnight_actuation``, and a user who turned actuation off
        # recorded their "no" there. Read only the new name and that "no"
        # becomes silence — and silence means the default, which is ON. The
        # rename would hand their hardware back to the planner.
        #
        # So carry the answer across, in both places ``_configured`` looks,
        # and retire the old key: two names for one decision is the next bug.
        try:
            new_data = {**accumulated_data}
            new_options = {**accumulated_options}
            carried = False
            for bag in (new_data, new_options):
                if "overnight_actuation" in bag:
                    bag["energy_plan_actuation"] = bag.pop("overnight_actuation")
                    carried = True
            hass.config_entries.async_update_entry(
                entry, data=new_data, options=new_options,
                version=18, minor_version=1,
            )
            accumulated_data, accumulated_options = new_data, new_options
            if carried:
                _LOGGER.info(
                    "#638: carried the actuation choice across the rename — "
                    "overnight_actuation is now energy_plan_actuation "
                    "(switch.sem_energy_plan_actuation)"
                )
        except Exception as e:
            _LOGGER.error(
                "Migration from v%s to v18 failed — keeping original "
                "config: %s", entry.version, e,
            )
            return False

    if entry.version == 18 and entry.minor_version < 2:
        # (#876) The Energy-Dashboard COUNTER keys are written by the config
        # flow when an entry is CREATED and by nothing else, so an entry that
        # predates that merge never acquires them — and no migration between
        # v1 and v18 added them.
        #
        # It hides in plain sight because the coordinator re-reads the Energy
        # Dashboard every cycle, so live operation is unaffected. Only code
        # that reads the ENTRY breaks, and there is one that matters:
        # ``night_backfill.py`` looks up ``battery_discharge_energy_sensor``
        # and, not finding it, answers "no battery discharge energy sensor
        # configured" and writes nothing. The service that exists to spare a
        # new install the five-night wait was dead on precisely the OLDEST
        # installs — the ones whose history was worth recovering. Measured:
        # PROD's entry (created 2025-11-10, never re-installed) carried 35
        # data keys against the branch rig's 40 on identical hardware, the
        # difference being exactly these five, with every counter present and
        # years deep in the recorder.
        #
        # Additive only. A key already set — in data OR in options, because
        # options shadow data and the coordinator reads the merged view — is
        # the user's own answer and is left alone.
        try:
            merged = {**accumulated_data, **accumulated_options}
            missing = [k for k in _ENERGY_COUNTER_KEYS if not merged.get(k)]
            new_data = {**accumulated_data}
            filled: dict = {}
            if missing:
                from .ha_energy_reader import read_energy_dashboard_config
                ed = await read_energy_dashboard_config(hass, quiet=True)
                if ed is not None:
                    found = ed.to_dict()
                    filled = {k: found[k] for k in missing if found.get(k)}
                    new_data.update(filled)
            hass.config_entries.async_update_entry(
                entry, data=new_data, options=accumulated_options,
                version=18, minor_version=2,
            )
            accumulated_data = new_data
            if filled:
                _LOGGER.info(
                    "#876: filled %d Energy-Dashboard counter(s) this entry "
                    "never received (%s) — battery-night backfill can now "
                    "read this install's own history",
                    len(filled), ", ".join(sorted(filled)),
                )
        except Exception as e:  # noqa: BLE001
            # Deliberately NOT a failed migration, and deliberately NOT
            # bumped: the Energy Dashboard may simply not be readable this
            # early. Leaving the entry at 18.1 means HA calls us again next
            # restart, which is the retry. Setup proceeds either way — an
            # install must never fail to load over a key it has lived
            # without for months.
            _LOGGER.warning(
                "#876: could not read the Energy Dashboard to fill the "
                "counter keys (will retry on next restart): %s", e,
            )

    _LOGGER.info("Migration to version %s.%s done", entry.version, entry.minor_version)
    return True


def _heat_pump_rows(full_config: dict) -> list[dict]:
    """#685: one row per heat pump — flat keys are the PRIMARY unit
    (device_id "heat_pump", full back-compat), the ``heat_pumps`` list
    holds additional units with the same key names."""
    rows: list[dict] = [{
        "id": "heat_pump",
        "name": full_config.get("heat_pump_name", "Heat Pump"),
        **{k: full_config.get(k) for k in (
            "heat_pump_relay1_entity", "heat_pump_relay2_entity",
            "heat_pump_climate_entity", "heat_pump_power_sensor",
            "heat_pump_energy_sensor", "heat_pump_temperature_sensor",
            "heat_pump_rated_power", "heat_pump_priority",
            "heat_pump_boost_offset", "heat_pump_max_setpoint",
            "heat_pump_force_on_threshold", "heat_pump_invert_sg_ready",
            "heat_pump_sg_ready_service", "heat_pump_sg_ready_service_data",
            "heat_pump_sg_ready_state_entity",
        ) if full_config.get(k) not in (None, "")},
    }]
    for _i, _row in enumerate(full_config.get("heat_pumps") or []):
        if isinstance(_row, dict):
            rows.append({"id": _row.get("id") or f"heat_pump_{_i + 2}",
                         "name": _row.get("name") or f"Heat Pump {_i + 2}",
                         **_row})
    return rows


def _heat_pump_row_controllable(row: dict) -> bool:
    """A row is registrable when it has a control path: both SG-Ready
    relays, a climate entity, or a service call (#801)."""
    r1 = row.get("heat_pump_relay1_entity")
    r2 = row.get("heat_pump_relay2_entity")
    cl = row.get("heat_pump_climate_entity")
    svc = (row.get("heat_pump_sg_ready_service") or "").strip()
    return bool(r1 and r2) or bool(cl) or bool(svc)


def _derive_charge_mode(
    charger_cfg: dict,
    full_config: dict,
    hass: HomeAssistant,
) -> str:
    """Derive a Charge mode (#277) from the legacy four-toggle state.

    Decision tree (matches ``docs/plans/2026-05-30_ev_charge_mode_consolidation.md``):
        ev_charging_mode == "now"             → always_max
        ev_charging_mode == "off"             → off
        ev_charging_mode == "auto" + tariff   → solar_plus_cheap
        ev_charging_mode in (pv, auto) + no night → solar_only
        otherwise                              → min_plus_solar  (catch-all default)

    Reads the per-charger switch state where available (the canonical
    location since #255) and falls back to the global / config dict
    for legacy installs. The two switches we consult are
    ``switch.sem_charger_<id>_night_charging`` and
    ``switch.sem_charger_<id>_tariff_optimized``. If a switch hasn't
    been created yet (cold migration before the platform sets up),
    we default to ON for night (the factory default) and OFF for
    tariff (the factory default).
    """
    cid = charger_cfg.get("id", "ev_charger")

    # ev_charging_mode is canonical per-charger as of v4 (#255).
    mode = (
        charger_cfg.get("ev_charging_mode")
        or full_config.get("ev_charging_mode")
        or "pv"
    )

    # Night switch — per-charger canonical, fall back to global, then
    # to the factory default (ON).
    night_eid = f"switch.sem_charger_{cid}_night_charging"
    if hass.states.get(night_eid) is not None:
        night = hass.states.is_state(night_eid, "on")
    elif hass.states.get("switch.sem_night_charging") is not None:
        night = hass.states.is_state("switch.sem_night_charging", "on")
    else:
        night = True  # factory default

    # Tariff switch — per-charger only; the global was never created.
    # Default OFF when missing (the factory default).
    tariff_eid = f"switch.sem_charger_{cid}_tariff_optimized"
    if hass.states.get(tariff_eid) is not None:
        tariff = hass.states.is_state(tariff_eid, "on")
    else:
        tariff = False

    if mode == "now":
        return "always_max"
    if mode == "off":
        return "off"
    # Tariff-on expresses cheap-hour intent regardless of which legacy
    # mode the user picked (auto / pv / self_consumption all preserve
    # it). Migrating those users to solar_only would silently lose
    # their tariff preference.
    if mode in ("pv", "auto", "self_consumption") and tariff:
        return "solar_plus_cheap"
    if mode in ("pv", "auto", "self_consumption") and not night:
        return "solar_only"
    # Catch-all — covers minpv (which always pulls Min from grid, so
    # never maps to solar_only regardless of night flag) and any
    # unrecognised mode value.
    from .consts.ev_charge_modes import DEFAULT_EV_CHARGE_MODE
    return DEFAULT_EV_CHARGE_MODE


def _migrate_limit_surplus_to_max(hass: HomeAssistant, entry: SEMConfigEntry) -> None:
    """Fold the removed ev_limit_surplus switch (#235) into the Max ceiling (#245).

    Users who had limit-surplus ON get Max set to their current target so surplus
    still stops there; the legacy key is then dropped. Idempotent — only acts while
    the key is present. Default-OFF users (the norm) get no change: Max stays unset
    → full → "charge freely from sun", exactly as before.
    """
    opts = {**entry.options}
    data = entry.data
    changed = False

    # Global scope (the switch persisted to options, but read data too for safety).
    # `entry.data` is read-only here, so a key living only in data can't be removed;
    # skip it once Max is already populated to avoid re-running (and log spam) forever.
    if "ev_limit_surplus" in opts or (
        "ev_limit_surplus" in data
        and opts.get("daily_ev_target_max") is None
        and opts.get("ev_target_soc_max") is None
    ):
        if bool(opts.get("ev_limit_surplus", data.get("ev_limit_surplus"))):
            cur_kwh = opts.get("daily_ev_target", data.get("daily_ev_target"))
            if cur_kwh is not None and opts.get("daily_ev_target_max") is None:
                opts["daily_ev_target_max"] = cur_kwh
            cur_soc = opts.get("ev_target_soc", data.get("ev_target_soc"))
            if cur_soc is not None and opts.get("ev_target_soc_max") is None:
                opts["ev_target_soc_max"] = cur_soc
        opts.pop("ev_limit_surplus", None)
        changed = True

    # Per-charger scope.
    chargers = opts.get("ev_chargers")
    if isinstance(chargers, list):
        new_chargers = []
        per_changed = False
        for c in chargers:
            if isinstance(c, dict) and "ev_limit_surplus" in c:
                c = dict(c)
                if bool(c.pop("ev_limit_surplus")):
                    if c.get("daily_ev_target") is not None and c.get("daily_ev_target_max") is None:
                        c["daily_ev_target_max"] = c["daily_ev_target"]
                    if c.get("ev_target_soc") is not None and c.get("ev_target_soc_max") is None:
                        c["ev_target_soc_max"] = c["ev_target_soc"]
                per_changed = True
            new_chargers.append(c)
        if per_changed:
            opts["ev_chargers"] = new_chargers
            changed = True

    if changed:
        hass.config_entries.async_update_entry(entry, options=opts)
        _LOGGER.info("Folded ev_limit_surplus into the Max charge ceiling (#245)")


def stable_discovered_charger_id(discovered: Dict[str, Any]) -> str:
    """Build a deterministic, storage-safe ID from registry identity."""
    import hashlib
    import re

    platform = str(discovered.get("_platform") or "ev_charger").lower()
    platform = re.sub(r"[^a-z0-9_]+", "_", platform).strip("_") or "ev_charger"
    identity = str(
        discovered.get("_device_id")
        or discovered.get("ev_current_control_entity")
        or discovered.get("ev_charging_power_sensor")
        or platform
    )
    digest = hashlib.sha256(f"{platform}:{identity}".encode()).hexdigest()[:10]
    return f"{platform}_{digest}"


def build_discovered_charger_storage(
    entry_data: Dict[str, Any],
    entry_options: Dict[str, Any],
    discovered: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Return matching data/options payloads for one discovered charger."""
    charger = {
        key: value
        for key, value in discovered.items()
        if not key.startswith("_") and value is not None
    }
    charger["id"] = stable_discovered_charger_id(discovered)
    platform = str(discovered.get("_platform") or "EV").split("_", 1)[0]
    charger["name"] = f"{platform.title()} Charger"
    chargers = [charger]
    return (
        {**dict(entry_data or {}), "ev_chargers": chargers},
        {**dict(entry_options or {}), "ev_chargers": chargers},
        chargers,
    )


def _online_twin_from_registry(hass, offline_eid: str):
    """(#886) The online current-control twin of a persisted offline register,
    resolved through the entity registry (same device). ``None`` when the
    device is gone or exposes no live counterpart. The registry is persisted,
    so the twin is found regardless of the charger integration's load order."""
    from homeassistant.helpers import entity_registry as er
    from .hardware_detection import _online_current_control
    reg = er.async_get(hass)
    ent = reg.async_get(offline_eid)
    if ent is None or not getattr(ent, "device_id", None):
        return None
    siblings = [e for e in reg.entities.values()
                if e.device_id == ent.device_id]
    return _online_current_control(offline_eid, siblings)


def _heal_offline_current_control_in_list(hass, chargers):
    """(#886, bug class 56) Repair chargers already PERSISTED with an offline
    fallback register as ``ev_current_control_entity`` — bound by pre-fix
    detection. Detection only re-runs when NO charger is configured, so an
    adopted install never self-corrects; this heals the stored list once, at
    setup, idempotently. Returns a new list if anything changed, else ``None``.

    Unlike the detection-time guard (which may drop the binding — it is only
    choosing whether to configure control at all), the heal ONLY swaps to a
    found online twin. It never drops: silently disabling an already-working
    charger's control on a registry read would be a heavier, harder-to-notice
    change than the mis-binding it repairs. In practice the twin is always
    present (the reporter's JuiceBox exposes both), so the swap is clean."""
    if not chargers:
        return None
    changed = False
    healed = []
    for c in chargers:
        if not isinstance(c, dict):
            healed.append(c)
            continue
        eid = c.get("ev_current_control_entity")
        if not eid or "offline" not in str(eid).lower():
            healed.append(c)
            continue
        online = _online_twin_from_registry(hass, str(eid))
        if online:
            new_c = dict(c)
            new_c["ev_current_control_entity"] = online
            healed.append(new_c)
            changed = True
        else:
            _LOGGER.warning(
                "Charger %s binds an offline current-control register (%s) and "
                "no online twin was found in the registry — leaving it in place; "
                "re-run charger auto-detection to fix (#886).",
                c.get("id", "?"), eid,
            )
            healed.append(c)
    return healed if changed else None


# (#638) The kill-switch's unique_id is ``sem_{key}``, so renaming the
# planner mints a new identity. Left alone HA would register a SECOND
# switch and strand the first as an unavailable orphan — the user would
# see two kill-switches, one of them inert, and the history would stop at
# the upgrade. Carry the registry entry instead.
_ACTUATION_UID_WAS = "sem_overnight_actuation"
_ACTUATION_UID_NOW = "sem_energy_plan_actuation"


def _async_rename_actuation_switch(registry) -> None:
    """Move the actuation switch's registry entry onto its new name."""
    old = registry.async_get_entity_id("switch", DOMAIN, _ACTUATION_UID_WAS)
    if not old:
        return
    changes = {"new_unique_id": _ACTUATION_UID_NOW}
    # The entity_id only moves if it is still the one WE picked. A user who
    # renamed the switch chose that name; carrying the identity keeps their
    # entity alive, and renaming it anyway would break the automations the
    # carry was for.
    if old == f"switch.{_ACTUATION_UID_WAS}":
        changes["new_entity_id"] = f"switch.{_ACTUATION_UID_NOW}"
    _LOGGER.info(
        "#638: carrying the actuation switch across the rename — %s → %s",
        old, changes.get("new_entity_id", old),
    )
    registry.async_update_entity(old, **changes)


async def async_setup_entry(hass: HomeAssistant, entry: SEMConfigEntry) -> bool:
    """Set up Solar Energy Management from a config entry.

    This follows Home Assistant best practices:
    1. Fast initialization - non-blocking operations deferred
    2. Proper error handling with ConfigEntryNotReady
    3. Graceful degradation for optional features
    4. Service registry checks to prevent conflicts
    """
    _LOGGER.info(
        "Starting Solar Energy Management setup (entry_id: %s, version: %s)",
        entry.entry_id,
        entry.version
    )

    # Initialize domain data storage (kept for backward compatibility with services)
    hass.data.setdefault(DOMAIN, {})

    # #656 — we're setting up, so the preceding unload was a reload (or an
    # HA start), not a removal. Drop the teardown stash WITHOUT deactivating:
    # the devices it holds are about to be re-registered on a fresh controller,
    # and bouncing a running heat pump on every options change is not a safety
    # improvement.
    _PENDING_LOAD_TEARDOWN.pop(entry.entry_id, None)

    # In-memory SEM log ring buffer for the diagnose surface (#461/#462
    # triage gap on Supervisor installs — no flat log file to tail).
    # Idempotent across reloads. Stored under its own key so code that
    # treats hass.data[DOMAIN] values as coordinators is unaffected.
    from .utils.log_buffer import ensure_attached as _attach_log_buffer
    hass.data[f"{DOMAIN}_log_buffer"] = _attach_log_buffer()

    # Warm the blocking-I/O caches off the event loop (caught live as
    # "Detected blocking call to open" on RienduPre's install): the
    # dashboard translations file and the manifest version are both
    # lazily opened from sync code inside the loop on first use.
    from .utils.translate import preload_translations as _preload_translations
    await hass.async_add_executor_job(_preload_translations)
    await hass.async_add_executor_job(SEMCoordinator._get_version)

    # Fold the removed ev_limit_surplus switch (#235) into the Max ceiling (#245).
    # Idempotent; only acts while the legacy key is present.
    _migrate_limit_surplus_to_max(hass, entry)

    # Heal a poisoned ``options.ev_chargers`` list (#462/#464 follow-up).
    # v1.7.2..v1.7.3-beta.3 builds could leave options with a partial or
    # ghost-ridden charger list that shadows entry.data on the merge below;
    # writer fixes alone don't repair already-corrupted storage. Idempotent:
    # after one healing write the reconcile returns None on every later boot.
    #
    # Ordering note (#476): the heal deliberately runs BEFORE full_config is
    # built and therefore before the EV auto-discovery reseed further down.
    # Heal-first means an options-side ``[]`` clobber is repaired from
    # entry.data before the merged config is evaluated, so the reseed (which
    # only fires when the merged config has no chargers at all) never plants
    # its single ``id: "ev_charger"`` entry on top of a heal-able install.
    if "ev_chargers" in (entry.options or {}):
        _healed = _heal_ev_chargers_options(
            (entry.data or {}).get("ev_chargers"),
            entry.options.get("ev_chargers"),
        )
        if _healed is not None:
            _LOGGER.warning(
                "Healed ev_chargers options list: stored ids %s -> healed ids %s "
                "(data-side ids: %s). See #462/#464.",
                [c.get("id") for c in (entry.options.get("ev_chargers") or [])
                 if isinstance(c, dict)],
                [c.get("id") for c in _healed],
                [c.get("id") for c in ((entry.data or {}).get("ev_chargers") or [])
                 if isinstance(c, dict)],
            )
            hass.config_entries.async_update_entry(
                entry, options={**entry.options, "ev_chargers": _healed},
            )

    # (#886) Repair a charger persisted with its OFFLINE fallback register as
    # ev_current_control_entity (pre-fix JuiceBox detection bound
    # number.*_max_current_offline_* where the online twin belongs). Detection
    # re-runs only when NO charger is configured, so an already-adopted install
    # never self-corrects — swap to the online twin here, once, idempotently.
    try:
        _off_data = _heal_offline_current_control_in_list(
            hass, (entry.data or {}).get("ev_chargers"))
        _off_opts = _heal_offline_current_control_in_list(
            hass, (entry.options or {}).get("ev_chargers"))
        if _off_data is not None or _off_opts is not None:
            _new_data = dict(entry.data or {})
            _new_options = dict(entry.options or {})
            if _off_data is not None:
                _new_data["ev_chargers"] = _off_data
            if _off_opts is not None:
                _new_options["ev_chargers"] = _off_opts
            _LOGGER.warning(
                "Healed offline EV current-control binding(s) to the online "
                "twin (see #886).",
            )
            hass.config_entries.async_update_entry(
                entry, data=_new_data, options=_new_options,
            )
    except Exception as exc:  # noqa: BLE001 — a heal must never block setup
        _LOGGER.debug("Offline current-control heal skipped: %s", exc)

    # Remove orphaned per-charger set-default button entities — the
    # button itself was retired in v1.7.0-beta.11 (#355 follow-up).
    # Idempotent; only fires on installs that still have the registry
    # entry from a previous version.
    try:
        from homeassistant.helpers import entity_registry as er
        registry = er.async_get(hass)
        for ent in list(er.async_entries_for_config_entry(registry, entry.entry_id)):
            if ent.domain == "button" and (ent.unique_id or "").endswith(
                "_set_default_target",
            ):
                _LOGGER.info(
                    "Removing retired set-default button %s", ent.entity_id,
                )
                registry.async_remove(ent.entity_id)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("Set-default button cleanup skipped: %s", exc)

    # (#638) Carry the kill-switch across the planner's rename. Idempotent;
    # only fires on installs that still hold the pre-rename registry entry.
    try:
        from homeassistant.helpers import entity_registry as er
        _async_rename_actuation_switch(er.async_get(hass))
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("Actuation switch rename skipped: %s", exc)

    # Merge entry.data and entry.options for complete configuration
    full_config = {**entry.data, **entry.options}
    _LOGGER.debug("Configuration keys: %s", list(full_config.keys()))

    # The persisted toggles must be resolved BEFORE the coordinator exists.
    # A legacy install records observer/vacation/actuation only in the
    # switch's restore store, which the coordinator cannot see — so it was
    # built on the armed default and stayed armed until the switch platform
    # attached (the 2026-07-18 unprotected-window class, #777). Reading the
    # store here and promoting it into the entry closes that window and
    # ends the install's dependence on a store HA prunes after 7 days.
    from .persisted_flags import promote_persisted_flags
    promote_persisted_flags(hass, entry, full_config)

    # Create coordinator with error handling
    try:
        coordinator = SEMCoordinator(hass, full_config)
        coordinator.config_entry = entry
        _LOGGER.debug("SEMCoordinator created successfully")
    except Exception as err:
        _LOGGER.error("Failed to create coordinator: %s", err, exc_info=True)
        raise ConfigEntryNotReady(f"Coordinator creation failed: {err}") from err

    # Try to initialize from HA Energy Dashboard (HA 2025.12+)
    # This reads sensor configuration from the Energy Dashboard instead of manual config
    _LOGGER.info("Attempting to read sensors from HA Energy Dashboard...")
    try:
        result = await coordinator.async_initialize_energy_dashboard()
        if result:
            _LOGGER.info("Successfully using sensors from HA Energy Dashboard")
        else:
            _LOGGER.info("Energy Dashboard not available or incomplete, using legacy sensor config")
    except Exception as err:
        _LOGGER.warning("Failed to read Energy Dashboard, using legacy config: %s", err, exc_info=True)

    # Fetch initial data - this is critical for setup
    _LOGGER.debug("Fetching initial data from coordinator")
    try:
        await coordinator.async_config_entry_first_refresh()
        _LOGGER.info("Initial data fetch successful")
    except Exception as err:
        _LOGGER.error(
            "Failed to fetch initial data. This may indicate missing sensors or "
            "connectivity issues: %s",
            err,
            exc_info=True
        )
        raise ConfigEntryNotReady(
            f"Could not fetch initial data. Check that all required sensors exist: {err}"
        ) from err

    # Store coordinator in runtime_data (quality scale: runtime-data)
    entry.runtime_data = coordinator
    # Also store in hass.data for backward compatibility with platform setup
    hass.data[DOMAIN][entry.entry_id] = coordinator
    # (#814) detection evidence report — built once here, refreshed on
    # late discovery, published every cycle.
    coordinator.refresh_detection_report()

    # Version-change detection (v1.6.14): on first setup after an upgrade
    # — HACS pulled new code, HA restarted with it — fire a one-shot
    # persistent notification telling the user to hard-refresh.
    # Background. Lovelace resource URLs include a content-hash
    # cache-bust (``?v={version}-{sha1}``) but the browser's loaded
    # frontend bootstrap still references the OLD URL until the page
    # is hard-reloaded. Soft reload (F5) hits cached bootstrap → loads
    # old sem-localize.js → raw translation keys appear in cards.
    # HA-TEST 2026-05-31 repro: after v1.6.14 deploy the user saw
    # ``TODAY_PLAN_TITLE`` / ``plan_strip_idle`` etc. until Ctrl+Shift+R.
    # Failure here is non-fatal — fire-and-forget the version check.
    try:
        await _maybe_emit_upgrade_notification(hass, entry)
    except Exception as err:  # noqa: BLE001 — defensive: never fail setup over this
        _LOGGER.debug("Version-change notification skipped: %s", err)

    # (#805) Name the charger SEM found but does not manage — and stay
    # quiet on a solar-only install. The old blanket
    # ``ev_charger_not_configured`` nagged every install without a charger
    # and named nothing, so the one reader who owned a wallbox (#803) got
    # no usable signal from it. Retired here; its id is deleted so an
    # upgrading install loses the stale warning.
    ir.async_delete_issue(hass, DOMAIN, "ev_charger_not_configured")
    try:
        _cands = charger_shaped_devices(
            [st.entity_id for st in hass.states.async_all("switch")]
            + [st.entity_id for st in hass.states.async_all("number")]
        )
        _repair = unmanaged_charger_repair(full_config, _cands)
    except Exception:  # noqa: BLE001 — a repair never costs a setup
        _repair = None
    if _repair:
        ir.async_create_issue(
            hass,
            DOMAIN,
            "unmanaged_charger_found",
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=_repair["translation_key"],
            translation_placeholders=_repair["placeholders"],
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, "unmanaged_charger_found")

    # Initialize load management (optional feature - don't fail setup if it fails)
    try:
        await coordinator.async_initialize_load_management(entry)
        _LOGGER.info("Load management initialized successfully")

        # Initialize unified device registry (reads Energy Dashboard, syncs to both systems)
        try:
            from .device_registry import UnifiedDeviceRegistry
            from .load_device_discovery import LoadDeviceDiscovery
            discovery = LoadDeviceDiscovery(hass)
            registry = UnifiedDeviceRegistry(
                hass, coordinator._surplus_controller, coordinator._load_manager, discovery
            )
            # (#622) Let every device rebuild (incl. the 35 s delayed
            # re-discovery inside async_initialize) re-apply persisted accrued
            # runtime from storage, so a late-arriving auto-discovered load
            # doesn't reset its daily-target progress to 0 and re-run. Set
            # BEFORE async_initialize so the first refresh already benefits.
            registry._runtime_restore_hook = coordinator._restore_device_runtimes
            await registry.async_initialize()
            coordinator._device_registry = registry
            # (#586) Restore each device's accrued daily runtime NOW — the
            # registry has just (re-)registered the surplus devices, so
            # get_device() can find them. Doing this during
            # async_config_entry_first_refresh (above) was too early: no
            # device existed yet, so on a mid-day restart the accrued
            # "X/Y u op zon vandaag" progress reset to 0 while the target
            # (applied at registration via _apply_goals) survived.
            # (#622) The registry now also re-runs this via _runtime_restore_hook
            # after every async_refresh_devices (incl. the 35 s delayed
            # re-discovery), so this explicit call is belt-and-suspenders: the
            # idempotent restore is a no-op for any device the hook already
            # filled, and it still guarantees a restore for devices present at
            # setup even if the hook wiring changes.
            coordinator._restore_device_runtimes()
            # Tell load manager to skip its own discovery — registry owns the device list
            if coordinator._load_manager:
                coordinator._load_manager._unified_registry_active = True
            _LOGGER.info("Unified device registry initialized with %d devices", len(registry.devices))
        except Exception as err:
            _LOGGER.warning("Unified device registry init failed (non-critical): %s", err)
            coordinator._device_registry = None

        # Register EV charger(s) as CurrentControlDevice for unified control
        # Solar mode: SurplusController manages by priority
        # Night mode: coordinator manages directly with grid headroom budget
        #
        # Multi-charger support (#112): ev_chargers list in config
        # Backward compat: flat ev_* keys wrapped into list by v2→v3 migration

        # Build charger config list from config + auto-discovery
        ev_chargers_config = list(full_config.get("ev_chargers") or [])

        # Auto-discover if no chargers configured
        if not ev_chargers_config:
            ev_auto = {}
            if coordinator._device_registry:
                ev_auto = coordinator._device_registry.discover_ev_charger()
                if ev_auto:
                    _LOGGER.info("Auto-discovered EV charger config: %s", list(ev_auto.keys()))
                    new_data, new_options, ev_chargers_config = (
                        build_discovered_charger_storage(
                            dict(entry.data or {}),
                            dict(entry.options or {}),
                            ev_auto,
                        )
                    )
                    # Persist the same stable list on both sides. Options are
                    # the live source; data is the recovery source used by the
                    # existing storage-healing path if options is clobbered.
                    hass.config_entries.async_update_entry(
                        entry,
                        data=new_data,
                        options=new_options,
                    )
                    full_config["ev_chargers"] = ev_chargers_config
            # Fallback: check flat keys (pre-migration installs)
            if not ev_chargers_config:
                ev_power = full_config.get("ev_charging_power_sensor")
                ev_svc = full_config.get("ev_charger_service")
                ev_ctl = full_config.get("ev_current_control_entity")
                if ev_power and (ev_svc or ev_ctl):
                    ev_chargers_config = [{
                        "id": "ev_charger", "name": "EV Charger",
                        **{k: full_config[k] for k in full_config
                           if k.startswith("ev_") and full_config[k] is not None},
                    }]

        # Register each charger
        from .devices.base import CurrentControlDevice, resolve_max_current
        coordinator._ev_devices = {}

        # Charger-id sanity (#476): every per-charger write path matches on
        # ``id``, and a missing id gets a POSITIONAL fallback below that can
        # collide with a real sibling (two id-less entries both become
        # untargetable; an id-less entry at index 1 collides with a real
        # "ev_charger_1"). Surface both shapes loudly — they are config
        # corruption, not normal states.
        _seen_charger_ids: set[str] = set()
        for idx, charger_cfg in enumerate(ev_chargers_config):
            if not charger_cfg.get("id"):
                _LOGGER.warning(
                    "EV charger at index %d has no 'id' — assigning positional "
                    "fallback 'ev_charger_%d'. Per-charger settings writes can "
                    "misbehave until the entry gets a stable id.",
                    idx, idx,
                )
            # ``or`` (not a get-default) so empty-string/None ids take the
            # positional fallback too — must stay in sync with the
            # coordinator's ``primary_charger_id()`` (#485 H1).
            charger_id = charger_cfg.get("id") or f"ev_charger_{idx}"
            if charger_id in _seen_charger_ids:
                _LOGGER.warning(
                    "Duplicate EV charger id '%s' at index %d — per-charger "
                    "entities and settings writes will target only the first "
                    "charger with this id. Fix the ev_chargers list.",
                    charger_id, idx,
                )
            _seen_charger_ids.add(charger_id)
            charger_name = charger_cfg.get("name", f"EV Charger {idx + 1}")

            # Resolve config: charger-specific keys, fall back to global config.
            # ``_this`` binds the loop variable at definition time — today every
            # call happens inside the same iteration, but a closure over a loop
            # variable reads whatever the loop last assigned, so deferring one
            # of these calls (into a task, a callback, a comprehension consumed
            # later) would silently resolve the LAST charger's config for every
            # charger. Bound, that failure is impossible rather than merely
            # currently-absent.
            def _cfg(key, default=None, _this=charger_cfg):
                v = _this.get(key)
                if v is not None:
                    return v
                v = full_config.get(key)
                return v if v is not None else default

            ev_power_entity = _cfg("ev_charging_power_sensor")
            ev_charger_service = _cfg("ev_charger_service")
            ev_service_entity = _cfg("ev_charger_service_entity_id")
            ev_current_entity = _cfg("ev_current_control_entity")
            # #604: ``ev_surplus_priority`` is the ONE priority axis (#576).
            # The legacy ``ev_load_priority`` alias is mapped into it by the
            # v15→v16 migration, so the construction-time alias fallback is
            # gone; ``ev_shed_priority`` stays retired (shed = reverse walk,
            # #470 rule preserved by list position).
            ev_priority = int(_cfg("ev_surplus_priority", 3 + idx))

            # Also auto-fill sensor reader config from first charger
            if idx == 0:
                for key in ("ev_connected_sensor", "ev_charging_sensor", "ev_total_energy_sensor"):
                    if not full_config.get(key) and charger_cfg.get(key):
                        full_config[key] = charger_cfg[key]

            if not ev_power_entity or not (ev_charger_service or ev_current_entity):
                _LOGGER.debug("Charger %s missing power sensor or control method, skipping", charger_id)
                continue

            # #462 follow-up (generalized in #485 K1): an entity-platform
            # service (number/input_number/select) configured as the
            # charger SERVICE needs a matching writable entity to target.
            # With a wrong-domain target (RienduPre's old config pointed
            # at a SENSOR), every set-current command bounces off the
            # service schema and the charger is silently uncontrollable.
            _svc_domain = str(ev_charger_service or "").strip().lower().split(".", 1)[0]
            if "." in str(ev_charger_service or "") and _svc_domain in (
                "number", "input_number", "select",
            ):
                _svc_target = ev_current_entity or ev_service_entity
                if not _svc_target or not str(_svc_target).startswith(f"{_svc_domain}."):
                    _LOGGER.warning(
                        "Charger '%s': ev_charger_service=%s needs a %s.* "
                        "target entity, but got %s — current commands will "
                        "fail. Set ev_current_control_entity to the "
                        "charger's max-current entity.",
                        charger_id, ev_charger_service, _svc_domain, _svc_target,
                    )

            ev_device = CurrentControlDevice(
                hass=hass,
                device_id=charger_id,
                name=charger_name,
                priority=ev_priority,
                min_current=float(_cfg("ev_min_current", 6)),
                # (#746) one resolver, not a literal per site — see
                # devices.base.resolve_max_current.
                max_current=resolve_max_current(_cfg),
                phases=int(_cfg("ev_phases", 3)),
                voltage=230.0,
                power_entity_id=ev_power_entity,
                charger_service=ev_charger_service,
                charger_service_entity_id=ev_service_entity,
                current_entity_id=ev_current_entity,
            )
            ev_device.needs_pilot_cycle = _cfg("ev_charger_needs_cycle", False)
            # #546 — failsafe: managed-neutralize by default — SEM arms a LONG
            # non-tripping persisted failsafe that overwrites the box's short
            # built-in one (real P30s won't let it be disabled over UDP). Set
            # keba_arm_failsafe False for boxes that CAN disable it (evcc-style),
            # then a Repair guides the user.
            ev_device.arm_failsafe_enabled = bool(_cfg("keba_arm_failsafe", True))
            ev_device.steady_failsafe = bool(_cfg("keba_steady_failsafe", True))
            # #546 — live offered-current sensor for the EV-OFFER-PROBE.
            ev_device.current_sensor_entity_id = str(_cfg("ev_current_sensor", "") or "")
            # #548 — charger STATUS enum (Wallbox: sensor.*_status). The
            # WallboxAdapter reads this as the authoritative "actually
            # charging?" signal (cloud power lags ~90 s) and to detect
            # app-lock (Eco-Smart / Scheduled / Power-Sharing) so SEM can
            # surface "can't stop" instead of silently failing OFF mode.
            ev_device.charging_status_entity = str(_cfg("ev_charging_sensor", "") or "")
            # Per-integration charger profile (#82)
            if _cfg("ev_service_param_name"):
                ev_device.service_param_name = _cfg("ev_service_param_name")
            if _cfg("ev_service_device_id"):
                ev_device.service_device_id = _cfg("ev_service_device_id")
            if _cfg("ev_start_stop_entity"):
                ev_device.start_stop_entity = _cfg("ev_start_stop_entity")
            if _cfg("ev_charge_mode_entity"):
                ev_device.charge_mode_entity = _cfg("ev_charge_mode_entity")
                ev_device.charge_mode_start = _cfg("ev_charge_mode_start")
                ev_device.charge_mode_stop = _cfg("ev_charge_mode_stop")
            if _cfg("ev_start_service"):
                ev_device.start_service = _cfg("ev_start_service")
                ev_device.start_service_data = json.loads(_cfg("ev_start_service_data", "{}"))
            if _cfg("ev_stop_service"):
                ev_device.stop_service = _cfg("ev_stop_service")
                ev_device.stop_service_data = json.loads(_cfg("ev_stop_service_data", "{}"))

            coordinator._surplus_controller.register_device(ev_device)
            coordinator._ev_devices[charger_id] = ev_device
            ev_device.managed_externally = True
            _LOGGER.info(
                "EV charger '%s' registered as CurrentControlDevice "
                "(priority %d, max %dA, service: %s)",
                charger_name, ev_priority,
                int(ev_device.max_current),
                ev_charger_service or ev_current_entity,
            )

            # Defensive: surface dead entity_ids at registration. Each of
            # these configured entities is something SEM will try to write
            # to or read from during the cycle. HA's service calls succeed
            # silently against non-existent entity_ids, so a stale id (e.g.
            # after a Wallbox/KEBA HA-integration upgrade renamed entities
            # under the user) results in SEM commanding nothing and the
            # charger continuing on its own last setpoint — the symptom of
            # #315 / #357 / #462. Logging at WARNING here makes the gap
            # visible in any diagnostics dump or log query.
            _to_check = [
                ("ev_charging_power_sensor", ev_power_entity),
                ("ev_current_control_entity", ev_current_entity),
                ("ev_charger_service_entity_id", ev_service_entity),
                ("ev_start_stop_entity", _cfg("ev_start_stop_entity")),
                ("ev_charge_mode_entity", _cfg("ev_charge_mode_entity")),
            ]
            # (#763 beta.7) Deferred past warm-up: at setup time the
            # upstream integration may simply not have loaded yet, and a
            # false "will silently no-op" here sent a real diagnosis down
            # a dead end. 120 s is comfortably past integration setup.
            def _deferred_entity_check(_now, _name=charger_name,
                                       _cid=charger_id,
                                       _chk=tuple(_to_check)):
                _warn_missing_charger_entities(hass, _name, _cid, _chk)

            from homeassistant.helpers.event import async_call_later
            async_call_later(hass, 120, _deferred_entity_check)

            # Also register in load management for peak shedding (#436:
            # pass per-charger id + name so each ev_chargers[i] gets its
            # own ``load_device_<id>`` entry in self._devices instead of
            # all chargers colliding on a hardcoded ``ev_charger`` key).
            if coordinator._load_manager:
                await coordinator._load_manager.register_ev_charger(
                    current_control_entity=ev_current_entity,
                    power_entity=ev_power_entity,
                    # #576: shed order = the ONE list position. The retired
                    # ``ev_shed_priority`` knob is gone; ``refresh_runtime_config``
                    # already overwrites this every cycle with the drag slot, so
                    # seed it with the same list position here (was a boot-only
                    # discrepancy). Latest-to-charge (highest number) sheds first.
                    priority=ev_priority,
                    is_critical=False,
                    charger_service=ev_charger_service,
                    charger_id=charger_id,
                    charger_name=charger_name,
                    # (#748) hand the stop switch + status sensor to load
                    # management so pattern discovery excludes them instead of
                    # rediscovering the stop switch as a smart plug (the third
                    # duplicate row). Reuse the device's already-resolved values.
                    start_stop_entity=ev_device.start_stop_entity,
                    status_entity=(ev_device.charging_status_entity or None),
                )

        # Backward compat: _ev_device points to primary (first) charger
        if coordinator._ev_devices:
            coordinator._ev_device = next(iter(coordinator._ev_devices.values()))
            _LOGGER.info(
                "Registered %d EV charger(s). Primary: %s",
                len(coordinator._ev_devices),
                coordinator._ev_device.name,
            )
        else:
            _LOGGER.debug("EV charger not configured (no power sensor or control method)")

        # Register heat pump SG-Ready controller(s) if configured.
        # (#685) The flat heat_pump_* keys are the PRIMARY unit (device_id
        # "heat_pump", untouched compat); additional units come from the
        # ``heat_pumps`` list, same key names per row.
        hp_rows = _heat_pump_rows(full_config)
        hp_registered = 0
        for _row in hp_rows:
            if not _heat_pump_row_controllable(_row):
                continue
            _r1 = _row.get("heat_pump_relay1_entity")
            _r2 = _row.get("heat_pump_relay2_entity")
            _cl = _row.get("heat_pump_climate_entity")
            _svc = (_row.get("heat_pump_sg_ready_service") or "").strip()
            from .config_flow import _parse_service_data
            from .devices.heat_pump_controller import HeatPumpController
            _svc_data = _parse_service_data(
                _row.get("heat_pump_sg_ready_service_data")) or {}
            hp_extra = HeatPumpController(
                hass=hass,
                device_id=str(_row["id"]),
                name=str(_row.get("name") or "Heat Pump"),
                rated_power=float(_row.get("heat_pump_rated_power", 2000)),
                priority=int(_row.get("heat_pump_priority", 4)),
                relay1_entity_id=_r1,
                relay2_entity_id=_r2,
                climate_entity_id=_cl,
                power_entity_id=_row.get("heat_pump_power_sensor"),
                energy_entity_id=_row.get("heat_pump_energy_sensor"),
                temperature_entity_id=_row.get("heat_pump_temperature_sensor"),
                boost_offset=float(_row.get("heat_pump_boost_offset", 2.0)),
                max_setpoint=float(_row.get("heat_pump_max_setpoint", 55.0)),
                force_on_threshold=float(_row.get("heat_pump_force_on_threshold", 5000)),
                invert_sg_ready=bool(_row.get("heat_pump_invert_sg_ready", False)),
                sg_ready_service=_svc or None,
                sg_ready_service_data=_svc_data,
                sg_ready_state_entity=_row.get("heat_pump_sg_ready_state_entity"),
            )
            coordinator._surplus_controller.register_device(hp_extra)
            hp_registered += 1
            _LOGGER.info(
                "Heat pump '%s' registered (id=%s, priority=%d, relay1=%s, "
                "relay2=%s, climate=%s, service=%s)",
                hp_extra.name, _row["id"], hp_extra.priority,
                _r1 or "—", _r2 or "—", _cl or "—", _svc or "—",
            )
        if hp_registered > 1:
            _LOGGER.info("#685: %d heat pumps active", hp_registered)

        # Primary-row visibility (kept from the single-unit era, #432/#437)
        hp_relay1 = full_config.get("heat_pump_relay1_entity")
        hp_relay2 = full_config.get("heat_pump_relay2_entity")
        hp_climate = full_config.get("heat_pump_climate_entity")
        if hp_registered == 0:
            # #432: promote from DEBUG to INFO so users self-diagnosing
            # heat-pump setup see this in the standard log view. Mirrors
            # the success-path INFO above. The detailed config values are
            # the load-bearing diagnostic — if the user expects the heat
            # pump to register but sees this line with all None values,
            # the problem is upstream (config-flow save / migration);
            # if they see real entity ids, the problem is the entity not
            # existing in HA.
            _LOGGER.info(
                "Heat pump NOT registered: relay1=%r relay2=%r climate=%r "
                "(needs either BOTH relays OR a climate entity)",
                hp_relay1, hp_relay2, hp_climate,
            )

        # ── Hot water controller (#454) ─────────────────────────────
        # Mirrors the heat-pump pattern: when user has configured a
        # boiler control entity (water_heater / climate / switch),
        # instantiate HotWaterController + register with SurplusController.
        # Without this block, the dashboard Config tab Hot Water section
        # collects settings that the runtime never reads.
        hw_entity = full_config.get("hot_water_entity") or None
        if hw_entity:
            from .devices.hot_water_controller import HotWaterController
            hw_device = HotWaterController(
                hass=hass,
                device_id="hot_water",
                name=full_config.get("hot_water_name", "Hot Water"),
                rated_power=float(full_config.get("hot_water_rated_power", 2500)),
                priority=int(full_config.get("hot_water_priority", 6)),
                entity_id=hw_entity,
                power_entity_id=full_config.get("hot_water_power_sensor"),
                energy_entity_id=full_config.get("hot_water_energy_sensor"),  # #600
                temperature_entity_id=full_config.get("hot_water_temperature_sensor"),
                max_temperature=float(full_config.get("hot_water_max_temperature", 70.0)),
                min_temperature=float(full_config.get("hot_water_minimum_temperature", 40.0)),
                solar_target_temp=float(full_config.get("hot_water_solar_target", 50.0)),
                legionella_target_temp=float(full_config.get("hot_water_legionella_target", 65.0)),
                legionella_interval_hours=float(full_config.get("hot_water_legionella_interval_hours", 168.0)),
            )
            coordinator._surplus_controller.register_device(hw_device)
            _seed_legionella_time(coordinator, hw_device)
            _LOGGER.info(
                "Hot water registered (entity=%s, priority=%d, "
                "temp_sensor=%s, solar_target=%.0f°C, max=%.0f°C)",
                hw_entity, hw_device.priority,
                hw_device.temperature_entity_id or "—",
                hw_device.solar_target_temp, hw_device.max_temperature,
            )
        else:
            _LOGGER.debug(
                "Hot water NOT registered: hot_water_entity not set"
            )

    except Exception:
        # Optional feature — keep setup alive so SEM still loads with
        # solar / EV / battery control. Use ``exception`` so the full
        # stack trace is captured in the log; the previous ``warning``
        # printed only the str() of the error, which made
        # post-incident debugging hard. Downstream code guards every
        # ``coordinator._load_manager`` access with an ``if`` check —
        # leaving it None is a supported state.
        _LOGGER.exception(
            "Load management initialization failed (non-critical). "
            "Load management features will be unavailable."
        )

    # Setup platforms (critical - must succeed)
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        _LOGGER.info("Platforms setup completed: %s", PLATFORMS)
    except Exception as err:
        _LOGGER.error("Failed to setup platforms: %s", err, exc_info=True)
        # Cleanup coordinator data
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise ConfigEntryNotReady(f"Platform setup failed: {err}") from err

    # Register services (with duplicate check)
    try:
        await _async_register_services(hass, coordinator)
        await _async_register_phase_services(hass, coordinator)
        _LOGGER.debug("Services registered successfully")
    except Exception as err:
        _LOGGER.warning(
            "Service registration failed (non-critical): %s. "
            "Services may not be available.",
            err
        )

    # Register frontend resources (optional - don't fail setup)
    try:
        await _async_register_frontend_resources(hass)
        _LOGGER.debug("Frontend resources registered successfully")
    except Exception as err:
        _LOGGER.warning(
            "Frontend resource registration failed (non-critical): %s. "
            "Custom cards may not be available.",
            err
        )

    # Auto-install card JS files to /config/www/ on startup (#55)
    # Only runs if dashboard was previously generated. On HACS updates,
    # this ensures new cards are available after restart without manual action.
    try:
        await _async_install_card_assets(hass, entry)
    except Exception as err:
        _LOGGER.debug("Card asset installation skipped: %s", err)

    # Register options update listener
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    # #397 first-run welcome: fire a one-shot persistent notification with a
    # link to the dashboard so the user has a starting point instead of
    # bouncing on the 263-entity registry. Gated by the same options-flag
    # pattern the install-dashboard one-shot uses just below — survives HA
    # restarts and never re-fires after the user dismisses it. Skipped on
    # observer mode (test installs don't want notification spam) — read from
    # the RESOLVED config, not entry.data alone: the flag can equally live in
    # options or, on a legacy install, only in the switch's restore store.
    _welcome_fired = entry.options.get("_welcome_notification_fired", False)
    if not _welcome_fired and not full_config.get("observer_mode"):
        try:
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "notification_id": "sem_first_install_welcome",
                    "title": "Solar Energy Management installed",
                    "message": build_welcome_message(full_config),
                },
                blocking=False,
            )
            hass.config_entries.async_update_entry(
                entry,
                options={**entry.options, "_welcome_notification_fired": True},
            )
            _LOGGER.info("SEM first-run welcome notification fired")
        except Exception as err:
            # Non-critical — never fail the setup over a notification.
            _LOGGER.debug("Welcome notification skipped: %s", err)

    # Schedule post-startup tasks (non-blocking)
    _schedule_post_startup_tasks(hass, entry, full_config, coordinator)

    # One-shot: if the user opted in during the install flow, generate the
    # SEM dashboard right after first setup. The dashboard service schedules
    # an HA restart 5s after success, so we set a marker in entry.options
    # *before* calling the service. The reload triggered by setting the
    # marker will see it on the second setup_entry pass and skip; the same
    # marker survives the HA restart and prevents a third regeneration.
    install_flag = entry.data.get("generate_dashboard_on_install")
    already_generated = entry.options.get("_install_dashboard_generated", False)
    if install_flag and not already_generated:
        _LOGGER.info(
            "Install flow opted in to dashboard generation — scheduling one-shot"
        )

        async def _run_once_install_dashboard(_now=None) -> None:
            try:
                await hass.services.async_call(
                    DOMAIN, "generate_dashboard", {}, blocking=True
                )
                hass.config_entries.async_update_entry(
                    entry,
                    options={
                        **entry.options,
                        "_install_dashboard_generated": True,
                    },
                )
            except Exception as gen_err:
                _LOGGER.error(
                    "Post-install dashboard generation failed: %s", gen_err
                )

        from homeassistant.helpers.event import async_call_later as _acl
        _acl(hass, 2, _run_once_install_dashboard)

    _LOGGER.info("Solar Energy Management integration setup completed successfully")
    return True


def _schedule_post_startup_tasks(
    hass: HomeAssistant,
    entry: ConfigEntry,
    full_config: Dict[str, Any],
    coordinator: SEMCoordinator
) -> None:
    """Schedule non-critical tasks to run after Home Assistant has started.

    This prevents blocking the startup process while still ensuring
    these tasks run when the system is ready.
    """
    from homeassistant.helpers.event import async_track_state_added_domain

    @callback
    def _async_post_startup_init(event) -> None:
        """Force a fresh split-grid discovery once HA has finished starting.

        Catches the case where another integration's energy sensor was not yet
        in the registry during async_config_entry_first_refresh(), leaving the
        cache pinned on an any-device pick (issue #166).
        """
        _LOGGER.debug("Running post-startup initialization tasks")
        reader = getattr(coordinator, "_sensor_reader", None)
        if reader is not None:
            reader.invalidate_split_grid_cache()
            hass.async_create_task(coordinator.async_request_refresh())

    @callback
    def _on_new_sensor(event) -> None:
        """Re-run split-grid discovery when a grid-shaped sensor appears.

        Triggered for entity additions (old_state is None). Pre-filters by
        substring so the typical firehose of new temperature/humidity/etc.
        sensors does not schedule a coordinator refresh. The authoritative
        pattern check still happens inside _discover_split_grid_power.
        """
        reader = getattr(coordinator, "_sensor_reader", None)
        if reader is None:
            return
        # Only relevant for split-grid setups. Combined-grid users (with
        # ed.grid_import_power set) never enter discovery, so skip them.
        if not getattr(reader, "_uses_split_grid", False):
            return
        disc = getattr(reader, "_split_grid_discovery", None)
        if disc is None or disc.get("confidence") == "same-device":
            return  # already locked in, nothing to upgrade
        eid = event.data.get("entity_id", "")
        if not any(hint in eid for hint in GRID_TRIGGER_HINTS):
            return
        _LOGGER.info(
            "New grid-shaped sensor %s appeared — re-running split-grid discovery",
            eid,
        )
        reader.invalidate_split_grid_cache()
        hass.async_create_task(coordinator.async_request_refresh())

    # Schedule tasks to run when Home Assistant is fully started
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _async_post_startup_init)

    # React live to new sensor entities from other integrations (e.g. DSMR loading
    # after SEM's first refresh). Cheap: only fires on entity creation, not state
    # changes. See plan for issue #166.
    entry.async_on_unload(
        async_track_state_added_domain(hass, "sensor", _on_new_sensor)
    )


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update.

    Skips reload when the change came from a number/switch entity (runtime
    config tweak): those updates already mirrored the value into the
    coordinator's in-memory config, so a full reload (which destroys all
    entities for ~1 s) is wasteful.

    The skip is keyed to the *exact* options payload the entity persisted
    (``_skip_options_reload`` holds that snapshot). A bare boolean used to
    leak — a stale flag from an earlier stepper could swallow a later
    options-FLOW save (e.g. ``vehicle_soc_entity``), which then only took
    effect after a full restart (#245 review #1). Comparing against the
    snapshot makes a flow change (different options) always reload.

    Consumption semantics (#476): the snapshot is kept on a MATCH and
    cleared on a MISMATCH. Two back-to-back runtime writes fire one
    listener invocation each, and both invocations see the final merged
    options — clearing on the first match made the second invocation
    reload spuriously (the exact disruption this mechanism avoids). Keeping
    the snapshot is leak-free: the snapshot always equals the LAST runtime
    write's payload, and HA only fires this listener when options actually
    change, so any externally-saved options either differ from the snapshot
    (→ mismatch → reload + clear) or never produce an event at all.
    """
    coordinator = entry.runtime_data if hasattr(entry, "runtime_data") else None
    snapshot = getattr(coordinator, "_skip_options_reload", None) if coordinator else None
    # #485 G5: only honor a recently-armed snapshot. HA fires this
    # listener for data/title-only entry updates too — there options
    # still equal a snapshot lingering from the last runtime tweak,
    # and matching it would silently swallow a legitimate reload.
    # Non-numeric armed_at (legacy writers, mocks) is treated as fresh.
    # NB: stdlib ``time`` is shadowed by this package's time.py
    # platform under pytest's path insertion — use dt_util timestamps.
    armed_at = getattr(coordinator, "_skip_options_reload_armed_at", None)
    snapshot_fresh = (
        not isinstance(armed_at, (int, float))
        or (dt_util.utcnow().timestamp() - armed_at) <= _SKIP_RELOAD_SNAPSHOT_TTL_S
    )
    if isinstance(snapshot, dict) and snapshot_fresh and dict(entry.options) == snapshot:
        _LOGGER.debug("Options update from runtime tweak — skipping reload")
        return

    if coordinator is not None:
        coordinator._skip_options_reload = None  # stale — clear before reload
    _LOGGER.info("Config options updated, reloading integration")
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: SEMConfigEntry,
    device_entry: "dr.DeviceEntry",
) -> bool:
    """Allow removal of stale devices (quality scale: stale-devices)."""
    return True


async def _async_deactivate_surplus_loads(devices, reason: str) -> None:
    """Command every SEM-controlled load back to normal (#656).

    Best-effort and never raises: this runs on teardown paths where the
    alternative to swallowing an error is an unattended heating device left
    latched on by an integration that no longer exists.
    """
    if not devices:
        return
    try:
        from .coordinator.surplus_controller import deactivate_devices

        await deactivate_devices(devices, reason)
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning(
            "Could not deactivate SEM-controlled loads on %s "
            "(non-blocking): %s", reason, e,
        )


async def async_remove_entry(hass: HomeAssistant, entry: SEMConfigEntry) -> None:
    """Release any load SEM was still holding when it was removed (#656).

    ``async_unload_entry`` has already run and taken the coordinator out of
    ``hass.data``, so it detached the devices and parked them for us. Without
    this, a hot-water boost temperature, an SG-Ready relay or a SEM-forced
    switch stays commanded indefinitely with nothing left to expire it — and a
    re-install won't fix it either: ``DeviceReconciler`` classifies a
    leftover-ON load as ``external_on`` and deliberately refuses to fight it.
    """
    devices = _PENDING_LOAD_TEARDOWN.pop(entry.entry_id, None)
    if not devices:
        return
    await _async_deactivate_surplus_loads(devices, "integration removed")


async def async_unload_entry(hass: HomeAssistant, entry: SEMConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # Clear the SurplusController's registered device list so a
        # subsequent setup doesn't see the prior cycle's EV / heat-pump
        # / switch devices still in the dispatch table. Each reload
        # would otherwise grow the list. Guarded — coordinator may be
        # missing if setup never completed.
        if coordinator is not None:
            # Part B (#589): clear any active force-op before dropping adapters.
            # Prevents a reload mid-force-op stranding the inverter in a
            # forced charge/discharge mode that SEM will no longer manage.
            # Only issues a STOP (command_normal) — never a new command.
            # Failures are swallowed so a flaky Modbus never blocks unload.
            _battery_adapters = getattr(coordinator, "_battery_adapters", {}) or {}
            for _bid, _adapter in _battery_adapters.items():
                try:
                    await _adapter.command_normal()
                    _LOGGER.debug(
                        "Battery adapter %s: command_normal on unload", _bid,
                    )
                except Exception as _e:  # noqa: BLE001
                    _LOGGER.debug(
                        "Battery adapter %s: command_normal on unload failed "
                        "(non-blocking): %s", _bid, _e,
                    )

            # #656 — loads must not be stranded ON when SEM goes away.
            #
            # HA calls this for a reload, a disable AND a removal, and the
            # right answer differs per case:
            #
            # * reload — SEM is coming back in seconds. Turning the hot-water
            #   boost or the SG-Ready relay off here would bounce a running
            #   heating device on every options change (and trip its
            #   compressor anti-short-cycle timer), so don't.
            #   (An HA shutdown/restart never reaches this function at all —
            #   HA fires EVENT_HOMEASSISTANT_STOP → ConfigEntries.
            #   _async_shutdown → entry.async_shutdown(), which does not
            #   unload entries. So no stash is created on that path, and the
            #   load simply stays as it was until SEM comes back up.)
            # * disabled — nothing is coming back. Deactivate now.
            # * removed — HA runs THIS first and then ``async_remove_entry``,
            #   by which point the coordinator is out of ``hass.data``. So the
            #   controller is stashed here and deactivated there. The stash is
            #   dropped by the next ``async_setup_entry`` (i.e. a reload), so a
            #   device list only lingers between an unload and whatever
            #   follows it.
            sc = getattr(coordinator, "_surplus_controller", None)
            if sc is not None:
                # detach_devices() clears the registry AND hands the devices
                # back, so the reload-leak contract holds on every path below.
                devices = sc.detach_devices()
                if entry.disabled_by is not None:
                    await _async_deactivate_surplus_loads(devices, "disabled")
                elif devices:
                    _PENDING_LOAD_TEARDOWN[entry.entry_id] = devices

        hass.data[DOMAIN].pop(entry.entry_id, None)

        # Remove all registered services (quality scale: config-entry-unloading)
        for service_name in (
            "generate_dashboard",
            "sync_priorities_from_dashboard",
            "set_device_control_mapping",
            "update_device_priorities",
            "update_device_config",
            "update_target_peak",
            "register_surplus_device",
            "schedule_appliance",
            "cancel_appliance_schedule",
        ):
            hass.services.async_remove(DOMAIN, service_name)

    return unload_ok


async def _async_register_services(
    hass: HomeAssistant,
    coordinator: SEMCoordinator,
) -> None:
    """Register services for the integration.

    Implements best practices:
    - Checks for existing services to prevent conflicts
    - Proper error handling for each service
    - Schema validation for all services
    - Clear logging for debugging
    """

    async def async_replan_service(call) -> None:
        """(#638) Force a fresh energy-day plan on the next cycle."""
        coordinator.request_replan()
        _LOGGER.info("Service replan: fresh plan requested")

    async def async_purge_status_history_service(call) -> None:
        """(#829) Purge SEM's statistics-less status entities.

        Safe by construction: the list is DERIVED from "has no state_class",
        so anything carrying long-term statistics — every energy and power
        sensor — is excluded automatically, including sensors added later.
        """
        from .coordinator.retention import run_purge
        days = call.data.get("keep_days")
        if days is None:
            days = coordinator.config.get("status_retention_days", 3)
        purged = await run_purge(hass, days)
        _LOGGER.info(
            "Service purge_status_history: %d SEM status entities, keeping "
            "%s day(s); statistics-bearing sensors untouched",
            len(purged), days,
        )

    async def async_backfill_forecast_ledger_service(call) -> None:
        """(#778) Recover forecast accuracy from history the install already has.

        The ledger normally learns forward, seven settled days before it will
        offer a trust figure. An install that has been running for months has
        already proven how good its forecast is — the statistics are sitting
        there — so this reads them and settles the ledger in one pass. Days the
        coordinator recorded live are never overwritten.
        """
        from .coordinator.ledger_backfill import DEFAULT_LOOKBACK_DAYS, run_backfill

        days = call.data.get("days") or DEFAULT_LOOKBACK_DAYS
        ledger = getattr(coordinator, "_forecast_ledger", None)
        if ledger is None:
            _LOGGER.warning(
                "backfill_forecast_ledger: no ledger on the coordinator yet — "
                "try again once SEM has completed a cycle")
            return
        try:
            report = await run_backfill(hass, ledger, days=int(days))
        except Exception as err:  # noqa: BLE001 — a service must not kill setup
            _LOGGER.error("backfill_forecast_ledger failed: %s", err)
            return

        try:
            coordinator._storage.set_forecast_ledger_state(ledger.to_dict())
            await coordinator._storage.async_save_energy_now()
        except (AttributeError, TypeError, ValueError) as err:
            _LOGGER.warning("backfilled ledger not persisted: %s", err)

        _LOGGER.info(
            "Service backfill_forecast_ledger: %d actual day(s) in history; "
            "added d1=%s d0=%s; trust now d1=%s d0=%s",
            report.get("actual_days", 0),
            report.get("added", {}).get(1), report.get("added", {}).get(0),
            report.get("trust", {}).get(1), report.get("trust", {}).get(0),
        )
        await coordinator.async_request_refresh()

    try:
        hass.services.async_register(
            DOMAIN, "backfill_forecast_ledger",
            async_backfill_forecast_ledger_service)
        _LOGGER.debug("Registered service: %s.backfill_forecast_ledger", DOMAIN)
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Failed to register backfill_forecast_ledger: %s", err)

    async def async_backfill_battery_nights_service(call) -> None:
        """(#815) Recover the battery's night history from statistics.

        #778's need envelope wants five trainable nights and live recording
        produces one a day, so a fresh install waits a working week to learn
        what its own database usually already proves. This reads the pack's
        cumulative discharge counter and reconstructs the nights in one pass.

        Sounder as well as faster: live recording integrates POWER, so a
        dropped sample loses that energy for good (#837). A counter keeps
        counting while nobody is looking, so missing hours between the
        endpoints cost nothing. Nights SEM measured live are never
        overwritten — live separates house drain from EV assist and export,
        and this cannot.
        """
        from .coordinator.night_backfill import run_backfill as _night_backfill

        days = call.data.get("days") or 365
        tracker = getattr(coordinator, "_battery_night", None)
        if tracker is None:
            _LOGGER.warning(
                "backfill_battery_nights: no night tracker on the coordinator "
                "yet — try again once SEM has completed a cycle")
            return
        try:
            report = await _night_backfill(
                hass, tracker, coordinator.config, days=int(days))
        except Exception as err:  # noqa: BLE001 — a service must not kill setup
            _LOGGER.error("backfill_battery_nights failed: %s", err)
            return

        if report.get("error"):
            # (#877) The user asked a direct question by pressing a button
            # and the answer outlives the moment: a notification is dismissed
            # and gone, the missing sensor is not. So the refusal goes where
            # unfinished setup lives, naming the sensor and linking the docs
            # section that says why it is needed.
            _LOGGER.warning("backfill_battery_nights: %s", report["error"])
            try:
                from .coordinator.repair_issues import (
                    raise_battery_night_backfill_blocked,
                )
                raise_battery_night_backfill_blocked(
                    hass,
                    missing=", ".join(report.get("missing_counters")
                                      or ["battery discharge energy"]),
                )
            except Exception:  # noqa: BLE001 — a repair never fails a service
                pass
            return

        try:
            coordinator._storage.set_battery_night_state(tracker.to_dict())
            await coordinator._storage.async_save_energy_now()
        except (AttributeError, TypeError, ValueError) as err:
            _LOGGER.warning("backfilled nights not persisted: %s", err)

        # (#877) How many reconstructed nights could close the energy
        # balance. A shortfall is not an error — it is a meter this install
        # does not keep — but it is the difference between a night comparable
        # to a measured one and a night that under-reports the house, so it
        # is said out loud rather than left in a service response nobody
        # reads.
        _recovered = report.get("recovered", 0)
        _balanced = report.get("with_grid_term", 0)
        # (#877) What matters is the history SEM KEEPS. A 365-day rebuild
        # recovers several times ``max_nights``; counting the whole haul
        # reports a shortfall about nights that were pruned seconds later.
        _unbalanced = int(report.get("kept_without_grid_term", 0) or 0)
        _missing = report.get("missing_counters") or []
        _LOGGER.info(
            "Service backfill_battery_nights: %d hour(s) of history from %s; "
            "recovered %d night(s) (%d trainable, %d with the grid's share); "
            "history now %d night(s), %d usable",
            report.get("hours_of_history", 0), report.get("statistic"),
            _recovered, report.get("trainable_recovered", 0), _balanced,
            report.get("nights_total", 0), report.get("usable_total", 0),
        )
        try:
            from .coordinator.repair_issues import (
                clear_battery_night_backfill,
                raise_battery_night_backfill_incomplete,
            )
            if _unbalanced and _missing:
                # A counter this install does not keep — actionable, so it
                # gets the card and names the sensor.
                _LOGGER.warning(
                    "backfill_battery_nights: %d KEPT night(s) could not "
                    "account for the grid's share, so they report only what "
                    "the BATTERY gave and under-state what the house took. "
                    "Missing: %s. The overnight-need estimate reads low "
                    "until those exist.",
                    _unbalanced, ", ".join(_missing),
                )
                raise_battery_night_backfill_incomplete(
                    hass, missing=", ".join(_missing),
                    unbalanced=_unbalanced,
                    recovered=report.get("nights_total", _recovered),
                )
            elif _unbalanced:
                # Every counter exists; those particular nights had a gap in
                # the statistics or a counter reset inside their window.
                # Nothing to add and nothing to fix — raising a card that
                # says "add a sensor" would name a cause we have not
                # established and hand the user an instruction that does not
                # apply (#872's lesson). Say it once, at INFO, and clear any
                # stale card.
                _LOGGER.info(
                    "backfill_battery_nights: %d of the %d kept night(s) "
                    "have no grid share — every counter is configured, so "
                    "those nights had a gap or a counter reset in their "
                    "window. They are treated as the battery's share alone.",
                    _unbalanced, report.get("nights_total", 0),
                )
                clear_battery_night_backfill(hass)
            else:
                # Every leg accounted for — retract any earlier complaint,
                # including one raised before the user added the sensor.
                clear_battery_night_backfill(hass)
        except Exception:  # noqa: BLE001
            pass
        # (2.1 audit, item 8) the result where a person looks, not the log
        try:
            from homeassistant.components import persistent_notification
            persistent_notification.async_create(
                hass,
                (f"Recovered {_recovered} night(s) "
                 f"({report.get('trainable_recovered', 0)} trainable) from "
                 f"{report.get('hours_of_history', 0)} hour(s) of history. "
                 f"Battery-night history now holds "
                 f"{report.get('nights_total', 0)} night(s), "
                 f"{report.get('usable_total', 0)} usable."
                 + ("" if not _unbalanced else
                    f"\n\n⚠️ {_unbalanced} of them could only measure what "
                    f"the battery gave, not what the grid added, so they "
                    f"under-state what your house took overnight — and the "
                    f"spendable-battery figure will read low. Add "
                    f"grid-import and battery-charge energy sensors (and "
                    f"your charger's, if you charge a car) to the Energy "
                    f"Dashboard, then press the button again.")),
                title="SEM: battery-night history rebuilt",
                notification_id="sem_backfill_battery_nights",
            )
        except Exception:  # noqa: BLE001 — a notice never fails the service
            pass
        await coordinator.async_request_refresh()

    try:
        hass.services.async_register(
            DOMAIN, "backfill_battery_nights",
            async_backfill_battery_nights_service)
        _LOGGER.debug("Registered service: %s.backfill_battery_nights", DOMAIN)
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Failed to register backfill_battery_nights: %s", err)

    try:
        hass.services.async_register(
            DOMAIN, "purge_status_history", async_purge_status_history_service)
        _LOGGER.debug("Registered service: %s.purge_status_history", DOMAIN)
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Failed to register purge_status_history service: %s", err)

    try:
        hass.services.async_register(DOMAIN, "replan", async_replan_service)
        _LOGGER.debug("Registered service: %s.replan", DOMAIN)
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Failed to register replan service: %s", err)

    # Check if services are already registered (prevents conflicts on reload)
    services_already_registered = hass.services.has_service(DOMAIN, "sync_priorities_from_dashboard")
    if services_already_registered:
        _LOGGER.debug(
            "Services already registered for domain '%s', skipping re-registration",
            DOMAIN
        )
        return

    # Dashboard generation service
    async def async_generate_dashboard_service(call) -> None:
        """Generate and install the SEM dashboard with all assets."""
        dashboard_title = call.data.get("dashboard_title", "Solar Energy Management")
        dashboard_path = call.data.get("dashboard_path", "sem-dashboard")

        try:
            from .dashboard_generator import DashboardGenerator
            from homeassistant.helpers.storage import Store
            import shutil

            # Step 1: Install card JS files to /config/www/
            # All filesystem ops run in an executor to avoid blocking the event loop.
            #
            # (#784) A sem-system-diagram.svg used to be copied here too. It
            # was dead weight from the original import — no card, template or
            # doc ever referenced it in the repo's whole history, and the
            # diagram cards draw inline SVG. Already-installed copies under
            # /config/www/sem/ are left alone; _cleanup_stale_www only sweeps
            # sem-*.js from the www root, so nobody's custom card breaks.
            component_dir = os.path.dirname(__file__)
            card_src_dir = os.path.join(component_dir, "dashboard", "card")
            card_www_dir = os.path.join(
                hass.config.config_dir, "www",
                "custom_components", DOMAIN, "dashboard", "card",
            )

            # Top-level JS files we install as Lovelace resources. The
            # canonical card bundle is at dashboard/card/dist/sem-cards.js
            # (registered by _async_register_frontend_resources via its hashed
            # URL) — a top-level sem-cards.js is ALWAYS a stale rsync artifact
            # and would shadow the dist bundle by winning the
            # customElements.define race (#282 / user-reported regression
            # where the EV card kept reappearing on the Control tab after
            # being removed in code).
            CANONICAL_TOP_LEVEL = {
                "sem-localize.js",
            }
            def _install_assets() -> list[str]:
                """Sync top-level dashboard assets to /config/www/. Runs in executor."""
                # (#738) the per-language tables the loader lazily injects —
                # the mirror must carry them or the legacy /local channel 404s
                # (the #617 vendor/ class). Computed, not hardcoded: a new
                # language in translations.json rides along automatically.
                # Computed HERE rather than in the caller because os.listdir
                # is one of the calls HA's loop guard patches, and the caller
                # is a coroutine.
                canonical = CANONICAL_TOP_LEVEL | {
                    f for f in os.listdir(card_src_dir)
                    if f.startswith("sem-localize.") and f.endswith(".js")
                }
                os.makedirs(card_www_dir, exist_ok=True)
                cards: list[str] = []
                shadow_removed: list[str] = []
                if os.path.isdir(card_src_dir):
                    for fname in os.listdir(card_src_dir):
                        if not fname.endswith(".js"):
                            continue
                        # Hard whitelist: never install a top-level
                        # sem-cards.js (it shadows the dist bundle) or any
                        # other unrecognised top-level *.js that isn't part
                        # of the canonical set.
                        if fname not in canonical:
                            stale_target = os.path.join(card_www_dir, fname)
                            if os.path.exists(stale_target):
                                os.remove(stale_target)
                                shadow_removed.append(fname)
                            continue
                        shutil.copy2(
                            os.path.join(card_src_dir, fname),
                            os.path.join(card_www_dir, fname),
                        )
                        cards.append(fname)
                # Also nuke any pre-existing /config/www/ shadow of the
                # bundle from earlier bad installs — the dist bundle is the
                # only valid sem-cards.js.
                stale_top_cards = os.path.join(card_www_dir, "sem-cards.js")
                if os.path.exists(stale_top_cards):
                    os.remove(stale_top_cards)
                    shadow_removed.append("sem-cards.js (top-level shadow)")
                if shadow_removed:
                    _LOGGER.info(
                        "Removed %d shadow card file(s) from %s: %s",
                        len(shadow_removed), card_www_dir, shadow_removed,
                    )
                return cards

            installed_cards = await hass.async_add_executor_job(_install_assets)
            if installed_cards:
                _LOGGER.info("Installed %d card(s) to %s: %s", len(installed_cards), card_www_dir, installed_cards)

            # Step 1b: Clean up stale card copies in /config/www/ root
            # Old standalone installs may leave files that conflict with
            # the component-managed copies (double customElements.define).
            def _cleanup_stale_www():
                www_dir = os.path.join(hass.config.config_dir, "www")
                removed = []
                for fname in os.listdir(www_dir) if os.path.isdir(www_dir) else []:
                    if fname.startswith("sem-") and fname.endswith(".js"):
                        stale = os.path.join(www_dir, fname)
                        os.remove(stale)
                        removed.append(fname)
                return removed

            stale_removed = await hass.async_add_executor_job(_cleanup_stale_www)
            if stale_removed:
                _LOGGER.info("Removed %d stale card(s) from /config/www/: %s", len(stale_removed), stale_removed)

            # Step 1c: Register cards as Lovelace resources (idempotent)
            # Compare by base URL (without ?v= query) to avoid duplicates
            # when _async_register_frontend_resources already added versioned URLs.
            # Also remove stale /local/sem-*.js entries (old standalone installs).
            resources_store = Store(hass, 1, "lovelace_resources")
            resources_data = await resources_store.async_load() or {"items": []}
            if "items" not in resources_data:
                resources_data["items"] = []

            # Remove stale standalone resource entries (/local/sem-*.js) AND
            # any top-level sem-cards.js shadow (the canonical bundle is at
            # /dist/sem-cards.js — a top-level one is always a stale rsync
            # artifact and shadows the dist bundle by winning the
            # customElements.define race, leaving users with the OLD bundle
            # rendered even after a clean redeploy). See #282 regression.
            component_prefix = f"/local/custom_components/{DOMAIN}/"
            shadow_url = f"{component_prefix}dashboard/card/sem-cards.js"
            before_count = len(resources_data["items"])
            resources_data["items"] = [
                item for item in resources_data["items"]
                if not (
                    item.get("url", "").startswith("/local/sem-")
                    and component_prefix not in item.get("url", "")
                )
                and item.get("url", "").split("?")[0] != shadow_url
            ]
            stale_count = before_count - len(resources_data["items"])
            if stale_count:
                _LOGGER.info(
                    "Removed %d stale Lovelace resource(s) (incl. any sem-cards.js shadow)",
                    stale_count,
                )

            # Cache-busting: per-file content hash + manifest version (#301).
            # See _content_hash_cache_bust at module level.
            #
            # (#785) Every hash is read in ONE executor hop, before either
            # loop below asks for one. Calling a helper runs its body right
            # here on the event loop no matter which module the helper lives
            # in — HA's guard named __init__.py line 64 (the `open` inside
            # _content_hash_cache_bust) while this coroutine looked clean,
            # because the read was two calls away. Only handing work to an
            # executor moves it off the loop.
            manifest_path_l = os.path.join(component_dir, "manifest.json")

            installed_bases = {
                f"/local/custom_components/{DOMAIN}/dashboard/card/{fname}"
                for fname in installed_cards
            }
            # The Lit bundle lives under dist/ so it never appears in the
            # root-level listdir above; whitelist it explicitly or the orphan
            # cleanup below would deregister it on every generate_dashboard call.
            installed_bases.add(
                f"/local/custom_components/{DOMAIN}/dashboard/card/dist/sem-cards.js"
            )
            existing_bases = {item.get("url", "").split("?")[0] for item in resources_data["items"]}
            # Both loops below bust exactly these: the files we install, plus
            # the SEM resources already registered that survive the orphan
            # sweep. Same filter as the sweep itself.
            bust_urls = set(installed_bases) | {
                base
                for base in existing_bases
                if f"/custom_components/{DOMAIN}/" in base and base.endswith(".js")
            }

            def _read_asset_versions() -> tuple[str, dict[str, str]]:
                """Runs in an executor — ``open`` is loop-guarded by HA."""
                try:
                    with open(manifest_path_l) as f:
                        version = json.load(f).get("version", "0")
                except Exception:
                    version = "0"
                return version, {
                    url: _content_hash_cache_bust(card_www_dir, url, version)
                    for url in bust_urls
                }

            _mver, _busts = await hass.async_add_executor_job(_read_asset_versions)

            def _cache_bust_for(base_url: str) -> str:
                # Bare version if a URL appeared after the hashes were read —
                # same fallback _content_hash_cache_bust uses for a bad read.
                return _busts.get(base_url, _mver)

            added_resources = []
            updated_resources = 0
            for fname in installed_cards:
                base_url = f"/local/custom_components/{DOMAIN}/dashboard/card/{fname}"
                if base_url not in existing_bases:
                    import uuid as _uuid
                    resources_data["items"].append({
                        "id": _uuid.uuid4().hex,
                        "url": f"{base_url}?v={_cache_bust_for(base_url)}",
                        "type": "module",
                    })
                    added_resources.append(base_url)

            # Update ?v= on existing SEM resources and remove orphaned ones.
            # installed_bases is built above, with the cache-bust set.
            cleaned = []
            kept_items = []
            for item in resources_data["items"]:
                url = item.get("url", "")
                base = url.split("?")[0]
                if f"/custom_components/{DOMAIN}/" in base and base.endswith(".js"):
                    if base not in installed_bases:
                        # Card file no longer exists — remove orphaned resource
                        cleaned.append(base)
                        continue
                    new_url = f"{base}?v={_cache_bust_for(base)}"
                    if item["url"] != new_url:
                        item["url"] = new_url
                        updated_resources += 1
                kept_items.append(item)
            resources_data["items"] = kept_items
            if cleaned:
                _LOGGER.info("Removed %d orphaned card resource(s): %s", len(cleaned), cleaned)

            if added_resources or stale_count or updated_resources:
                await resources_store.async_save(resources_data)
                if added_resources:
                    _LOGGER.info("Registered %d new Lovelace resource(s): %s", len(added_resources), added_resources)
                if updated_resources:
                    _LOGGER.info("Updated cache-bust on %d Lovelace resource(s) (content-hash)", updated_resources)

            # Step 2: Generate dashboard config
            generator = DashboardGenerator(hass)
            dashboard_config = await generator.generate_dashboard(
                dashboard_title=dashboard_title,
                dashboard_path=dashboard_path,
            )

            if not dashboard_config:
                raise ValueError("Dashboard generator returned empty configuration")

            views = dashboard_config.get("views", [])
            if not views:
                raise ValueError("Dashboard config has no views")

            # Save dashboard to storage. Prefer HA's running LovelaceStorage
            # (writes storage AND updates the in-memory cache AND fires
            # `lovelace_updated`) so the regenerated dashboard reloads live —
            # no HA restart needed. Falls back to a direct Store write for the
            # first-install case, where HA hasn't registered the dashboard yet.
            storage_key = f"lovelace.{dashboard_path}"
            config_payload = {"views": views}
            reloaded_live = False
            try:
                ll_data = hass.data.get("lovelace")
                dashboards = getattr(ll_data, "dashboards", None)
                if dashboards is None and isinstance(ll_data, dict):
                    dashboards = ll_data.get("dashboards")
                live_dash = dashboards.get(dashboard_path) if isinstance(dashboards, dict) else None
                if live_dash is not None and hasattr(live_dash, "async_save"):
                    await live_dash.async_save(config_payload)
                    reloaded_live = True
                    _LOGGER.info(
                        "Dashboard '%s' regenerated and reloaded live (%d views, no restart needed)",
                        dashboard_path, len(views),
                    )
            except Exception as live_err:
                _LOGGER.warning(
                    "Live Lovelace reload failed, falling back to direct write: %s",
                    live_err,
                )

            if not reloaded_live:
                dashboard_store = Store(hass, 1, storage_key)
                storage_data = {"config": config_payload}
                await dashboard_store.async_save(storage_data)
                _LOGGER.info(
                    "Dashboard config saved to .storage/%s with %d views "
                    "(restart HA to apply — first install or HA Lovelace API unavailable)",
                    storage_key, len(views),
                )

            # Register dashboard in lovelace_dashboards storage
            dashboards_store = Store(hass, 1, "lovelace_dashboards")
            dashboards_data = await dashboards_store.async_load()
            if dashboards_data is None:
                dashboards_data = {"items": []}

            dashboard_exists = False
            for item in dashboards_data.get("items", []):
                if item.get("id") == dashboard_path:
                    item["mode"] = "storage"
                    item["title"] = dashboard_title
                    item["icon"] = "mdi:solar-power"
                    item["show_in_sidebar"] = True
                    item["require_admin"] = False
                    dashboard_exists = True
                    break

            if not dashboard_exists:
                dashboards_data["items"].append({
                    "id": dashboard_path,
                    "mode": "storage",
                    "title": dashboard_title,
                    "icon": "mdi:solar-power",
                    "show_in_sidebar": True,
                    "require_admin": False,
                    "url_path": dashboard_path,
                })

            await dashboards_store.async_save(dashboards_data)

            # Restart only when the live-reload path didn't fire — that's the
            # first-install case where HA hasn't yet registered the dashboard
            # in its in-memory Lovelace registry, so the on-disk write alone
            # won't surface the new dashboard until next startup. When live-
            # reload succeeded (#257 / 1.5.15+), the in-memory cache and the
            # `lovelace_updated` event already pushed the new config to every
            # connected client — a browser hard-refresh is enough, and the
            # forced restart was both unnecessary and surprising (#282/UX).
            if reloaded_live:
                await hass.services.async_call(
                    "persistent_notification", "create",
                    {
                        "title": "SEM Dashboard Updated",
                        "message": (
                            f"Dashboard **{dashboard_title}** regenerated with {len(views)} views.\n\n"
                            f"Changes are live now — refresh the browser if cards look stale.\n\n"
                            f"Access at: /lovelace/{dashboard_path}"
                        ),
                        "notification_id": "sem_dashboard_success",
                    },
                )
                _LOGGER.info(
                    "Dashboard updated live: %s at /%s — no restart needed",
                    dashboard_title, dashboard_path,
                )
            else:
                await hass.services.async_call(
                    "persistent_notification", "create",
                    {
                        "title": "SEM Dashboard Created",
                        "message": (
                            f"Dashboard **{dashboard_title}** created with {len(views)} views.\n\n"
                            f"Access at: /lovelace/{dashboard_path}\n\n"
                            f"Home Assistant will restart in 5 seconds to apply the first install."
                        ),
                        "notification_id": "sem_dashboard_success",
                    },
                )
                _LOGGER.info(
                    "Dashboard created: %s at /%s — scheduling first-install restart",
                    dashboard_title, dashboard_path,
                )

                async def _delayed_restart(_now):
                    _LOGGER.info("Restarting Home Assistant to apply first-install dashboard")
                    await hass.services.async_call("homeassistant", "restart")

                from homeassistant.helpers.event import async_call_later
                async_call_later(hass, 5, _delayed_restart)

        except Exception as e:
            _LOGGER.error("Dashboard generation failed: %s", e, exc_info=True)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="dashboard_generation_failed",
            ) from e

    try:
        hass.services.async_register(
            DOMAIN,
            "generate_dashboard",
            async_generate_dashboard_service,
            schema=vol.Schema({
                vol.Optional("dashboard_title", default="Solar Energy Management"): cv.string,
                vol.Optional("dashboard_path", default="sem-dashboard"): cv.string,
            }),
        )
        _LOGGER.debug("Registered service: %s.generate_dashboard", DOMAIN)
    except Exception as err:
        _LOGGER.error("Failed to register generate_dashboard service: %s", err)

    # Load management priority sync service
    async def async_sync_priorities_from_dashboard_service(call) -> None:
        """Sync device priorities from dashboard card order."""
        import re

        dashboard_storage_key = call.data.get("dashboard_storage_key", "lovelace.dashboard_test")
        view_path = call.data.get("view_path", "peak-load-management")

        if not coordinator._load_manager:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="load_management_not_initialized",
            )

        try:
            # Load dashboard configuration
            dashboard_file = os.path.join(hass.config.config_dir, ".storage", dashboard_storage_key)

            def _read_dashboard():
                if not os.path.exists(dashboard_file):
                    return None
                with open(dashboard_file, "r", encoding="utf-8") as f:
                    return json.load(f)

            dashboard_data = await hass.async_add_executor_job(_read_dashboard)
            if dashboard_data is None:
                _LOGGER.error("Dashboard file not found: %s", dashboard_file)
                return

            # Find the specified view
            views = dashboard_data.get("data", {}).get("config", {}).get("views", [])
            target_view = next((v for v in views if v.get("path") == view_path), None)

            if not target_view:
                _LOGGER.error("View with path '%s' not found in dashboard", view_path)
                return

            # Find the Device Priority Management section
            sections = target_view.get("sections", [])
            device_section = None
            for section in sections:
                cards = section.get("cards", [])
                for card in cards:
                    if isinstance(card, dict):
                        title = card.get("title", "")
                        if "Device Priority Management" in title:
                            device_section = section
                            break
                if device_section:
                    break

            if not device_section:
                _LOGGER.error("Device Priority Management section not found")
                return

            # Extract device IDs from card order
            cards = device_section.get("cards", [])
            device_updates = []

            for index, card in enumerate(cards):
                if not isinstance(card, dict):
                    continue

                # Skip title cards
                card_type = card.get("type", "")
                if "title" in card_type:
                    continue

                # Extract device_id from Jinja template
                secondary_template = card.get("secondary", "")
                match = re.search(r"'load_device_[^']+", secondary_template)

                if match:
                    device_id = match.group(0).strip("'")
                    # Position starts at 1 (skip title card at index 0)
                    priority = index  # Since we skip title cards, first device card becomes priority 1
                    device_updates.append((device_id, priority))
                    _LOGGER.debug("Found device %s at position %d", device_id, priority)

            # Update priorities
            updated_count = 0
            for device_id, priority in device_updates:
                if device_id in coordinator._load_manager._devices:
                    await coordinator._load_manager.update_device_priority(device_id, priority)
                    updated_count += 1
                    _LOGGER.info("Updated %s priority to %d (from card position)", device_id, priority)
                else:
                    _LOGGER.warning("Device %s found in dashboard but not in load manager", device_id)

            _LOGGER.info("Synced priorities for %d devices from dashboard card order", updated_count)

        except Exception as e:
            _LOGGER.error("Failed to sync priorities from dashboard: %s", e, exc_info=True)

    # Register priority sync service
    try:
        hass.services.async_register(
            DOMAIN,
            "sync_priorities_from_dashboard",
            async_sync_priorities_from_dashboard_service,
            schema=vol.Schema({
                vol.Optional("dashboard_storage_key", default="lovelace.dashboard_test"): cv.string,
                vol.Optional("view_path", default="peak-load-management"): cv.string,
            })
        )
        _LOGGER.debug("Registered service: %s.sync_priorities_from_dashboard", DOMAIN)
    except Exception as err:
        _LOGGER.error(
            "Failed to register sync_priorities_from_dashboard service: %s",
            err
        )

    # ── set_device_control_mapping service ──

    async def async_set_device_control_mapping(call) -> None:
        """Manually map a control entity for an Energy Dashboard device."""
        registry = getattr(coordinator, '_device_registry', None)
        if not registry:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_registry_not_initialized",
            )

        energy_sensor = call.data.get("energy_sensor")
        control_entity = call.data.get("control_entity", "")
        control_type = call.data.get("control_type", "switch")
        service = call.data.get("service")

        # Validate per control type: entity types need an entity; service needs a service.
        if control_type == "service":
            if not service:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="mapping_service_required",
                )
        elif not control_entity:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="mapping_entity_required",
            )

        await registry.async_set_manual_mapping(
            energy_sensor,
            control_entity,
            control_type,
            service=service,
            param=call.data.get("param"),
            shed_value=call.data.get("shed_value"),
            restore_value=call.data.get("restore_value"),
        )
        _LOGGER.info(
            "Manual mapping set: %s → %s (%s)",
            energy_sensor, service if control_type == "service" else control_entity, control_type,
        )

    try:
        hass.services.async_register(
            DOMAIN,
            "set_device_control_mapping",
            async_set_device_control_mapping,
            schema=vol.Schema({
                vol.Required("energy_sensor"): cv.string,
                vol.Optional("control_entity", default=""): cv.string,
                vol.Optional("control_type", default="switch"): vol.In(
                    ["switch", "current", "service", "input_boolean"]
                ),
                vol.Optional("service"): cv.string,
                vol.Optional("param"): cv.string,
                vol.Optional("shed_value"): vol.Coerce(float),
                vol.Optional("restore_value"): vol.Coerce(float),
            }),
        )
        _LOGGER.debug("Registered service: %s.set_device_control_mapping", DOMAIN)
    except Exception as err:
        _LOGGER.error("Failed to register set_device_control_mapping service: %s", err)

    # ── remove_device_control_mapping service (#219) ──

    async def async_remove_device_control_mapping(call) -> None:
        """Remove a manual mapping; device reverts to auto-discovery."""
        registry = getattr(coordinator, '_device_registry', None)
        if not registry:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_registry_not_initialized",
            )
        await registry.async_remove_manual_mapping(call.data.get("energy_sensor"))

    try:
        hass.services.async_register(
            DOMAIN,
            "remove_device_control_mapping",
            async_remove_device_control_mapping,
            schema=vol.Schema({
                vol.Required("energy_sensor"): cv.string,
            }),
        )
        _LOGGER.debug("Registered service: %s.remove_device_control_mapping", DOMAIN)
    except Exception as err:
        _LOGGER.error("Failed to register remove_device_control_mapping service: %s", err)

    # ── Drag-and-drop priority card services ──

    async def async_update_device_priorities(call) -> None:
        """Batch update device priorities from drag-and-drop reorder."""
        priorities = call.data.get("priorities", [])

        # Update via unified registry if available
        registry = getattr(coordinator, '_device_registry', None)
        if registry:
            await registry.async_update_priority_overrides(priorities)
            _LOGGER.info("Updated priorities for %d devices via registry", len(priorities))
            return

        if not coordinator._load_manager:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="load_management_not_initialized",
            )

        updated = 0
        for item in priorities:
            device_id = item.get("device_id")
            priority = item.get("priority")
            if device_id and priority is not None:
                await coordinator._load_manager.update_device_priority(device_id, int(priority))
                updated += 1
        _LOGGER.info("Updated priorities for %d devices via drag-and-drop", updated)

    try:
        hass.services.async_register(
            DOMAIN,
            "update_device_priorities",
            async_update_device_priorities,
            schema=vol.Schema({
                vol.Required("priorities"): list,
            }),
        )
        _LOGGER.debug("Registered service: %s.update_device_priorities", DOMAIN)
    except Exception as err:
        _LOGGER.error("Failed to register update_device_priorities service: %s", err)

    async def async_update_device_config(call) -> None:
        """Update a single device property (controllable or critical)."""
        if not coordinator._load_manager:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="load_management_not_initialized",
            )

        device_id = call.data.get("device_id")
        prop = call.data.get("property")
        value = call.data.get("value")

        if prop in ("critical", "controllable", "hands_off"):
            # (#650) Persist via the REGISTRY. Writing only into the
            # LoadManagement dict — as this did pre-fix — lost the flag on the
            # next `_sync_to_load_manager`, which replaces that entry wholesale
            # (drag / 35 s re-discovery / config change / restart). The registry
            # re-applies its overrides at device build, so the toggle sticks.
            # The LoadManagement write stays: it takes effect this cycle and it
            # is the ONLY store for devices the registry doesn't build
            # (per-charger `load_device_*` entries, service registrations).
            #
            # (#780) ``controllable`` / ``hands_off`` are the SAME toggle under
            # two names, and ``value`` keeps the card's polarity throughout:
            # True = "SEM may touch this load".
            if prop == "critical":
                await coordinator._load_manager.update_device_critical_status(device_id, bool(value))
            else:
                await coordinator._load_manager.async_set_hands_off(device_id, not bool(value))
            reg = getattr(coordinator, "_device_registry", None)
            if reg is not None:
                await reg.async_set_device_flag(device_id, prop, bool(value))
        elif prop == "control_mode":
            # Update device control mode: off / peak_only / surplus (#49)
            registry = getattr(coordinator, '_device_registry', None)
            if registry:
                await registry.update_device_control_mode(device_id, str(value))
            else:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="device_registry_not_initialized",
                )
        elif prop == "depends_on":
            # Update device dependency (#122). Persist via the REGISTRY so a
            # rebuild (drag / re-discovery / restart) re-applies it — pre-fix it
            # lived only on the transient device and got wiped ("separated all
            # the time"). #576.
            reg = getattr(coordinator, "_device_registry", None)
            device = coordinator._surplus_controller.get_device(device_id)
            if reg is not None and (device or value):
                await reg.async_set_dependency(device_id, [str(value)] if value else [])
                _LOGGER.info("Updated %s depends_on = %s", device_id,
                             [str(value)] if value else [])
            elif device:
                device.depends_on = [str(value)] if value else []
                _LOGGER.info("Updated %s depends_on = %s (no registry)", device_id,
                             device.depends_on)
            else:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="device_not_found",
                    translation_placeholders={"device_id": device_id},
                )
        elif prop in (
            "daily_min_runtime_min", "top_up_policy", "stop_entity", "stop_at",
            # (#620) max cap + battery tiers
            "daily_max_runtime_min", "battery_assist_enabled",
            "battery_eligible_overnight",
            # (#688) per-load anti-cycling (minutes)
            "min_on_time_min", "min_off_time_min",
            # (#705) thermal comfort band
            "comfort_entity", "comfort_target", "comfort_offset", "comfort_limit",
        ):
            # (#559/#620) goal engine — persisted + applied live
            registry = getattr(coordinator, "_device_registry", None)
            if not registry:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="device_registry_not_initialized",
                )
            if prop == "top_up_policy" and str(value) not in (
                "solar_only", "cheap_hours"
            ):
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_device_property",
                    translation_placeholders={"property": f"{prop}={value}"},
                )
            # (#620) normalize the two battery flags to a canonical bool string
            # so the stored dict + live apply agree regardless of "true"/"1"/"on".
            if prop in ("battery_assist_enabled", "battery_eligible_overnight"):
                value = str(str(value).strip().lower() in ("true", "1", "on", "yes"))
            # (#688) anti-cycle windows are non-negative minutes.
            if prop in ("min_on_time_min", "min_off_time_min"):
                try:
                    if float(value) < 0:
                        raise ValueError
                except (TypeError, ValueError) as err:
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="invalid_device_property",
                        translation_placeholders={"property": f"{prop}={value}"},
                    ) from err
            # (#705) comfort temperatures are numbers; the offset is also
            # non-negative (a negative offset would silently widen the band).
            # Without this a value like "twenty-six" would store, then
            # _apply_goals' defensive parse would write 0.0 — disabling the
            # band with no error ever reaching the caller.
            if prop in ("comfort_target", "comfort_offset", "comfort_limit"):
                try:
                    _fv = float(value)
                    if prop == "comfort_offset" and _fv < 0:
                        raise ValueError
                except (TypeError, ValueError) as err:
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="invalid_device_property",
                        translation_placeholders={"property": f"{prop}={value}"},
                    ) from err
            await registry.async_update_device_goal(device_id, prop, value)
        else:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_device_property",
                translation_placeholders={"property": prop},
            )
        _LOGGER.info("Updated %s.%s = %s", device_id, prop, value)
        await coordinator.async_request_refresh()

    try:
        hass.services.async_register(
            DOMAIN,
            "update_device_config",
            async_update_device_config,
            schema=vol.Schema({
                vol.Required("device_id"): cv.string,
                vol.Required("property"): vol.In([
                    "controllable", "critical", "control_mode", "depends_on",
                    # (#559) goal engine — grounded core
                    "daily_min_runtime_min", "top_up_policy",
                    "stop_entity", "stop_at",
                    # (#620) max cap + battery tiers
                    "daily_max_runtime_min", "battery_assist_enabled",
                    "battery_eligible_overnight",
                    # (#688) per-load anti-cycling
                    "min_on_time_min", "min_off_time_min",
                    # (#705) thermal comfort band
                    "comfort_entity", "comfort_target", "comfort_offset", "comfort_limit",
                ]),
                vol.Required("value"): cv.string,
            }),
        )
        _LOGGER.debug("Registered service: %s.update_device_config", DOMAIN)
    except Exception as err:
        _LOGGER.error("Failed to register update_device_config service: %s", err)

    async def async_update_target_peak(call) -> None:
        """Update target peak limit."""
        if not coordinator._load_manager:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="load_management_not_initialized",
            )

        target = call.data.get("target_peak_limit")
        unlimited = call.data.get("peak_limit_unlimited")
        await coordinator._load_manager.update_target_peak_limit(
            float(target), unlimited=unlimited
        )
        _LOGGER.info(
            "Updated target peak limit to %.1f kW%s", target,
            "" if unlimited is None else f" (unlimited={unlimited})",
        )

    try:
        hass.services.async_register(
            DOMAIN,
            "update_target_peak",
            async_update_target_peak,
            schema=vol.Schema({
                # (#717) Same range as the config flow. A hard-coded 20 kW
                # here silently rejected any service larger than a European
                # fuse box even once the form allowed it.
                vol.Required("target_peak_limit"): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=MIN_PEAK_LIMIT_KW, max=MAX_PEAK_LIMIT_KW),
                ),
                # (#717 redesign) Optional: the Control-tab slider sends this
                # alongside the target in one atomic write when the drag
                # lands on the MAX notch. Omitted by callers that only ever
                # touch the numeric ceiling (e.g. an automation).
                vol.Optional("peak_limit_unlimited"): cv.boolean,
            }),
        )
        _LOGGER.debug("Registered service: %s.update_target_peak", DOMAIN)
    except Exception as err:
        _LOGGER.error("Failed to register update_target_peak service: %s", err)


async def _async_register_frontend_resources(hass: HomeAssistant) -> None:
    """Register frontend resources for the SEM dashboard cards."""
    try:
        import os

        component_path = os.path.dirname(__file__)
        dashboard_path = os.path.join(component_path, "dashboard")
        # Sentinel: the Lit bundle is the file that must exist for the cards to
        # load. The individual vanilla card files were removed once they were
        # migrated into dist/sem-cards.js (see _legacy_bases below); don't point
        # this guard at a per-card file or registration silently stops working.
        card_file_path = os.path.join(dashboard_path, "card", "dist", "sem-cards.js")

        if not os.path.exists(card_file_path):
            return

        static_path = f"/local/custom_components/{DOMAIN}/dashboard"

        # Serve the component's dashboard dir so the Lovelace resource URLs
        # below (the sem-cards.js bundle + sem-localize.js) actually resolve.
        # MUST be async_register_static_paths: the sync hass.http static-path
        # register did blocking I/O on the event loop and HA *removed* it in
        # 2025.7 (deprecated 2024.7). On 2025.7+ the old call raised
        # AttributeError, the bare ``except Exception: pass`` below swallowed it
        # as "already registered", the bundle URL went unserved, and EVERY sem-*
        # card rendered "Custom element doesn't exist" — the whole dashboard was
        # nothing but Konfigurationsfehler tiles (#799, reporter on HA 2026.8.2).
        try:
            # Imported inside this try (not above it) so a future symbol
            # rename surfaces at WARNING here rather than being swallowed at
            # debug by the outer handler — the class-48 shape this fix closes.
            from homeassistant.components.http import StaticPathConfig

            await hass.http.async_register_static_paths(
                [StaticPathConfig(static_path, dashboard_path, False)]
            )
        except (RuntimeError, ValueError) as err:
            # Benign: a reload re-runs setup and the path is already registered
            # from the previous load.
            _LOGGER.debug(
                "SEM static path already registered: %s (%s)", static_path, err
            )
        except Exception as err:  # noqa: BLE001
            # The #799 lesson: never silently swallow a static-path failure as
            # "already registered" — surface it. But a hiccup here must not
            # block the Lovelace-resource registration below.
            _LOGGER.warning("SEM static path registration failed: %s", err)

        # Register the JS as Lovelace resources (not add_extra_js_url) so they
        # load into HA's scoped custom-element registry. add_extra_js_url loads
        # as a plain <script> in the global scope, which conflicts with the
        # Lovelace resource load and leaves the element in the wrong registry —
        # symptom: "Custom element doesn't exist: sem-system-diagram-card".
        # Read version from manifest for cache-busting query param.
        # Without this, browsers cache the old JS indefinitely even with
        # cache_headers=False, because Lovelace resources are fetched once
        # and kept in the service worker cache.
        manifest_path = os.path.join(component_path, "manifest.json")
        card_dir = os.path.join(dashboard_path, "card")

        def _asset_versions():
            """Per-asset cache-bust tokens: manifest version + short content hash.

            A plain rsync+restart deploy does NOT bump the manifest version, so a
            bare ``?v={version}`` stayed constant and browsers kept serving stale
            JS from the service-worker cache — notably a stale ``sem-localize.js``,
            which surfaced as stale dashboard translations on PROD (#240). Hashing
            the on-disk file makes ``?v=`` follow the actual content, busting the
            cache on any real change while staying stable across unrelated restarts.
            """
            import hashlib

            try:
                with open(manifest_path) as f:
                    base = json.load(f).get("version", "0")
            except Exception:
                base = "0"

            def _token(*rel_parts):
                try:
                    with open(os.path.join(card_dir, *rel_parts), "rb") as f:
                        return f"{base}-{hashlib.sha1(f.read()).hexdigest()[:8]}"
                except OSError:
                    return base

            return {
                # (#738) hash the SOURCE, not the loader: the loader's bytes
                # don't move on a German-only change, but the German sibling
                # must still be cache-busted — the loader propagates this
                # token onto every injected sem-localize.<lang>.js URL.
                "localize": _token("..", "translations.json"),
                "bundle": _token("dist", "sem-cards.js"),
            }

        asset_v = await hass.async_add_executor_job(_asset_versions)

        localize_base = f"{static_path}/card/sem-localize.js"
        # Single Lit bundle replaces all individual card JS files
        cards_bundle_base = f"{static_path}/card/dist/sem-cards.js"
        localize_url = f"{localize_base}?v={asset_v['localize']}"
        cards_bundle_url = f"{cards_bundle_base}?v={asset_v['bundle']}"

        # sem-localize.js is delivered as a Lovelace resource only
        # (registered below alongside the bundle and diagram card).
        # Cards constructed before the script finishes parsing wait
        # for the ``sem-localize-ready`` event dispatched at the end
        # of sem-localize.js — handled by every card's base class,
        # ``dashboard/card/src/base/sem-lit-base.js`` (#453, v1.7.3).
        # Earlier versions registered on a second channel via
        # ``add_extra_js_url`` to work around a perceived first-render
        # race; the ready-event mechanism in the base class makes
        # that unnecessary.

        # Legacy base URLs to clean up. Migrated to the single Lit
        # bundle. ``sem-localize.js`` is NOT in this list — it's
        # actively re-registered below as a Lovelace resource.
        _legacy_bases = [
            f"{static_path}/card/sem-shared.js",
            f"{static_path}/card/sem-reactive-base.js",
            f"{static_path}/card/sem-load-priority-card.js",
            # (#784) The standalone vanilla diagram card and the SEMBaseCard /
            # semReady layer it was the last consumer of. Both the standalone
            # and the bundle defined sem-system-diagram-card, and semDefineCard
            # is first-wins, so which implementation the user saw came down to
            # resource load order. 2.0 keeps only the bundled Lit version — the
            # one the dashboard actually renders. Listed here so upgrading
            # installs drop the now-404 resource instead of keeping it forever.
            f"{static_path}/card/sem-system-diagram-card.js",
            f"{static_path}/card/sem-period-selector-card.js",
            f"{static_path}/card/sem-chart-card.js",
            f"{static_path}/card/sem-solar-summary-card.js",
            f"{static_path}/card/sem-weather-card.js",
            f"{static_path}/card/sem-flow-card.js",
            f"{static_path}/card/sem-tab-header.js",
            f"{static_path}/card/sem-battery-card.js",
            f"{static_path}/card/sem-ev-status-card.js",
            f"{static_path}/card/sem-charger-status-card.js",
            f"{static_path}/card/sem-title-card.js",
            f"{static_path}/card/sem-dashboard-translator.js",
            f"{static_path}/card/sem-schedule-card.js",
            f"{static_path}/card/sem-solar-card.js",
            f"{static_path}/card/sem-costs-card.js",
            f"{static_path}/card/sem-grid-card.js",
            f"{static_path}/card/sem-control-card.js",
            f"{static_path}/card/sem-energy-impact-card.js",
            f"{static_path}/card/sem-battery-zones-card.js",
            f"{static_path}/card/sem-ev-progress-card.js",
            f"{static_path}/card/sem-costs-detail-card.js",
            f"{static_path}/card/sem-system-card.js",
            f"{static_path}/card/sem-home-status-card.js",
        ]

        try:
            resources = hass.data["lovelace"].resources
            if not resources.loaded:
                await resources.async_load()

            # YAML-mode Lovelace exposes a ``ResourceYAMLCollection`` whose
            # resource list is sourced from ``configuration.yaml`` and is
            # read-only — it doesn't implement ``async_create_item`` /
            # ``async_update_item`` / ``async_delete_item``. We can't
            # programmatically register the bundle there. Feature-detect via
            # the methods we'd need, and surface the URLs the user has to
            # add manually so the dashboard can actually load. Without this
            # branch the dashboard came up blank with only an unhelpful
            # warning in the log (#283 — Brkie, YAML-mode Lovelace).
            yaml_mode = not hasattr(resources, "async_create_item")
            if yaml_mode:
                _LOGGER.warning(
                    "SEM detected YAML-mode Lovelace; SEM card resources cannot be "
                    "registered automatically. Add the following to "
                    "configuration.yaml under `lovelace.resources` and restart:\n"
                    "  - url: %s\n    type: module\n"
                    "  - url: %s\n    type: module",
                    cards_bundle_url,
                    localize_url,
                )
                # (#799) …and SAY it where a user looks. The log line has
                # existed since #283; the reporter still met a dashboard of
                # Configuration Error cards and reinstalled twice before
                # finding it. A Repair carries the same URLs into Settings.
                _repair = yaml_mode_repair(True, [cards_bundle_url, localize_url])
                if _repair:
                    ir.async_create_issue(
                        hass, DOMAIN, "lovelace_yaml_mode",
                        is_fixable=False, is_persistent=True,
                        severity=ir.IssueSeverity.ERROR,
                        translation_key=_repair["translation_key"],
                        translation_placeholders=_repair["placeholders"],
                    )
                # Skip the rest of the registration block — none of the
                # mutating methods below are callable in YAML mode.
                raise _SEMYAMLModeSkip()
            # Storage mode: clear a stale repair from a previous YAML setup.
            ir.async_delete_issue(hass, DOMAIN, "lovelace_yaml_mode")

            # Build lookup: base URL (without query) → resource item
            existing_by_base = {}
            for item in resources.async_items():
                base = item["url"].split("?")[0]
                existing_by_base[base] = item

            # Remove legacy individual card resources (now bundled)
            for legacy_base in _legacy_bases:
                legacy_item = existing_by_base.get(legacy_base)
                if legacy_item:
                    await resources.async_delete_item(legacy_item["id"])
                    _LOGGER.info("Removed legacy SEM resource (now in Lit bundle): %s", legacy_base)

            # Register single Lit bundle
            bundle_item = existing_by_base.get(cards_bundle_base)
            if bundle_item is None:
                await resources.async_create_item({"res_type": "module", "url": cards_bundle_url})
                _LOGGER.info("Registered SEM Lit bundle: %s", cards_bundle_url)
            elif bundle_item["url"] != cards_bundle_url:
                await resources.async_update_item(
                    bundle_item["id"], {"res_type": "module", "url": cards_bundle_url}
                )
                _LOGGER.info("Updated SEM Lit bundle: %s → %s", bundle_item["url"], cards_bundle_url)

            # (#784) The diagram card used to be registered here as a second,
            # standalone resource. It now ships inside the bundle like every
            # other card; the retired URL is cleaned up via _legacy_bases.

            # Register sem-localize.js as a Lovelace resource (single
            # delivery channel; see #453). Cards constructed before
            # this script parses listen for ``sem-localize-ready`` in
            # ``sem-lit-base.js`` and re-render once the global is
            # available.
            localize_item = existing_by_base.get(localize_base)
            if localize_item is None:
                await resources.async_create_item({"res_type": "module", "url": localize_url})
                _LOGGER.info("Registered SEM localize: %s", localize_url)
            elif localize_item["url"] != localize_url:
                await resources.async_update_item(
                    localize_item["id"], {"res_type": "module", "url": localize_url}
                )
                _LOGGER.info("Updated SEM localize: %s → %s", localize_item["url"], localize_url)
        except _SEMYAMLModeSkip:
            # Already logged the "manual config needed" warning above.
            pass
        except Exception as e:
            _LOGGER.warning("Could not register SEM Lovelace resources: %s", e)

    except Exception as e:
        _LOGGER.debug("Frontend resource registration skipped: %s", e)


async def _async_install_card_assets(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Auto-install card JS files to /config/www/ on startup (#55).

    Only runs if the SEM dashboard was previously generated, detected by:
    1. Config entry flag `_install_dashboard_generated` (set by install flow)
    2. Dashboard storage file `.storage/lovelace.sem-dashboard` (set by service)

    On first install (no dashboard yet): skip — generate_dashboard handles it.
    On HACS update: auto-copy new/changed cards so restart is sufficient.
    Self-healing: recreates www dir if deleted but dashboard still exists.
    """
    import shutil

    component_dir = os.path.dirname(__file__)
    card_src_dir = os.path.join(component_dir, "dashboard", "card")
    card_www_dir = os.path.join(
        hass.config.config_dir, "www",
        "custom_components", DOMAIN, "dashboard", "card",
    )

    # Check if dashboard was ever generated
    dashboard_generated = False

    # Method 1: Config entry flag (set during install flow)
    if entry.options.get("_install_dashboard_generated"):
        dashboard_generated = True

    # Method 2: Dashboard storage file (set by generate_dashboard service)
    dashboard_storage = os.path.join(
        hass.config.config_dir, ".storage", "lovelace.sem-dashboard"
    )
    if os.path.exists(dashboard_storage):
        dashboard_generated = True

    if not dashboard_generated:
        _LOGGER.debug(
            "SEM dashboard not yet generated — skipping card auto-install. "
            "Run the generate_dashboard service after setup."
        )
        return

    def _copy_cards() -> list:
        os.makedirs(card_www_dir, exist_ok=True)
        cards = []
        # Copy root-level JS files (sem-localize.js, etc.)
        if os.path.isdir(card_src_dir):
            for fname in os.listdir(card_src_dir):
                if fname.endswith(".js"):
                    src = os.path.join(card_src_dir, fname)
                    dst = os.path.join(card_www_dir, fname)
                    if not os.path.exists(dst) or os.path.getmtime(src) > os.path.getmtime(dst):
                        shutil.copy2(src, dst)
                        cards.append(fname)
        # Copy Lit bundle from dist/ + vendored chart libs from vendor/
        # (#617 — sem-chart-card loads Chart.js from the local vendor path
        # first; without this sync the file 404s under HA's /local→www
        # route and the CDN fallback silently reintroduces the internet
        # dependency).
        for sub in ("dist", "vendor"):
            sub_src_dir = os.path.join(card_src_dir, sub)
            sub_www_dir = os.path.join(card_www_dir, sub)
            if os.path.isdir(sub_src_dir):
                os.makedirs(sub_www_dir, exist_ok=True)
                for fname in os.listdir(sub_src_dir):
                    if fname.endswith(".js"):
                        src = os.path.join(sub_src_dir, fname)
                        dst = os.path.join(sub_www_dir, fname)
                        if not os.path.exists(dst) or os.path.getmtime(src) > os.path.getmtime(dst):
                            shutil.copy2(src, dst)
                            cards.append(f"{sub}/{fname}")
        # Also copy translations.json for sem-localize.js (#60)
        dashboard_dir = os.path.dirname(card_src_dir)
        translations_src = os.path.join(dashboard_dir, "translations.json")
        translations_dst = os.path.join(os.path.dirname(card_www_dir), "translations.json")
        if os.path.exists(translations_src):
            if not os.path.exists(translations_dst) or os.path.getmtime(translations_src) > os.path.getmtime(translations_dst):
                os.makedirs(os.path.dirname(translations_dst), exist_ok=True)
                shutil.copy2(translations_src, translations_dst)
                cards.append("translations.json")
        return cards

    updated = await hass.async_add_executor_job(_copy_cards)
    if updated:
        _LOGGER.info("Auto-installed %d updated card(s): %s", len(updated), updated)
    else:
        _LOGGER.debug("All card assets up to date")


async def _async_register_phase_services(
    hass: HomeAssistant,
    coordinator: SEMCoordinator,
) -> None:
    """Register services for new phases (surplus control, scheduling, etc.)."""
    from datetime import datetime

    # Skip if already registered
    if hass.services.has_service(DOMAIN, "schedule_appliance"):
        return

    # Phase 0: Register/unregister surplus devices
    async def async_register_surplus_device(call):
        """Register a device for surplus control (#559 Phase 0).

        One call does everything: persisted across restarts, defaults to
        control_mode=surplus (that's what you register a device FOR;
        auto-discovered devices keep peak_only), and returns a summary.
        """
        spec = {
            "device_id": call.data.get("device_id"),
            "entity_id": call.data.get("entity_id"),
            "name": call.data.get("name") or call.data.get("device_id"),
            "priority": call.data.get("priority", 5),
            # (#744) No rating named means no rating — not 1 kW. The device
            # layer applies (and labels) the placeholder, so the first real
            # measurement can still replace it downward.
            "rated_power": call.data.get("rated_power"),
            "power_entity_id": call.data.get("power_entity_id"),
            # #600 — optional kWh energy counter; SEM autodetects a companion
            # power sensor on the device first, else derives power from this.
            "energy_entity_id": call.data.get("energy_entity_id"),
            # (#847) New devices start UNMANAGED — the user opts them in.
            # Same principle as #805's DEFAULT_DISCOVERED_CONTROL_MODE: on a
            # fresh install SEM must not adopt (and later actuate) loads
            # nobody handed it. hoyte's report: mode→Off on just-added
            # devices switched them OFF, because "surplus" was the silent
            # default and running loads were adopted under it.
            "control_mode": call.data.get("control_mode", "off"),
            "depends_on": call.data.get("depends_on") or [],
            # (#569) climate device support
            "device_type": call.data.get("device_type", "switch"),
            "hvac_mode": call.data.get("hvac_mode", "cool"),
            "target_temperature": call.data.get("target_temperature"),
        }
        goal_fields = {
            k: call.data[k]
            for k in (
                "daily_min_runtime_min", "top_up_policy",
                "stop_entity", "stop_at",
                # (#620) max cap + battery tiers
                "daily_max_runtime_min", "battery_assist_enabled",
                "battery_eligible_overnight",
                # (#705) thermal comfort band
                "comfort_entity", "comfort_target", "comfort_offset", "comfort_limit",
            )
            if k in call.data
        }
        registry = getattr(coordinator, "_device_registry", None)
        if registry:
            if goal_fields:
                registry.seed_goals(spec["device_id"], goal_fields)
            summary = await registry.async_register_service_device(spec)
            if goal_fields:
                summary["goals"] = goal_fields
        else:
            # Registry not up (very early call) — register unpersisted so
            # the call still works; the user can re-run to persist.
            from .devices.base import surplus_device_from_spec, DeviceControlMode
            device = surplus_device_from_spec(hass, spec["device_id"], spec)
            try:
                device.control_mode = DeviceControlMode(spec["control_mode"])
            except ValueError:
                device.control_mode = DeviceControlMode.OFF  # (#847) creation default
            coordinator._surplus_controller.register_device(device)
            summary = {**spec, "persisted": False,
                       "total_devices": len(coordinator._surplus_controller._devices)}
        _LOGGER.info(
            "Registered surplus device: %s (priority %d, mode %s)",
            spec["name"], spec["priority"], spec["control_mode"],
        )
        if call.return_response:
            return summary
        return None

    hass.services.async_register(
        DOMAIN,
        "register_surplus_device",
        async_register_surplus_device,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Required("entity_id"): cv.string,
            vol.Optional("name"): cv.string,
            vol.Optional("priority", default=5): vol.All(int, vol.Range(min=1, max=10)),
            # (#744) NO default — a voluptuous default is always filled in, so
            # every call would arrive carrying 1 kW and the handler could never
            # see that the caller named no rating at all.
            vol.Optional("rated_power"): vol.Coerce(float),
            vol.Optional("power_entity_id"): cv.string,
            vol.Optional("energy_entity_id"): cv.string,  # #600
            # (#847) default "off" — devices are opted IN, never pre-owned
            vol.Optional("control_mode", default="off"): vol.In(
                ["off", "peak_only", "surplus"]
            ),
            vol.Optional("depends_on"): vol.All(cv.ensure_list, [cv.string]),
            # (#569) climate device support
            vol.Optional("device_type", default="switch"): vol.In(
                ["switch", "climate"]
            ),
            vol.Optional("hvac_mode", default="cool"): vol.In(
                ["cool", "heat", "heat_cool", "dry", "fan_only", "auto"]
            ),
            vol.Optional("target_temperature"): vol.Coerce(float),
            # (#559) goal engine — grounded core (runtime target + policy)
            vol.Optional("daily_min_runtime_min"): vol.All(
                vol.Coerce(float), vol.Range(min=0, max=1440)
            ),
            vol.Optional("top_up_policy"): vol.In(
                ["solar_only", "cheap_hours"]
            ),
            vol.Optional("stop_entity"): cv.string,
            vol.Optional("stop_at"): vol.Coerce(float),
            # (#620) max cap + battery tiers — must be in the schema too, else
            # voluptuous rejects them as extra keys (400) even though the
            # handler reads them into goal_fields.
            vol.Optional("daily_max_runtime_min"): vol.All(
                vol.Coerce(float), vol.Range(min=0, max=1440)
            ),
            vol.Optional("battery_assist_enabled"): cv.boolean,
            vol.Optional("battery_eligible_overnight"): cv.boolean,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def async_unregister_surplus_device(call):
        """Remove a service-registered surplus device (#559 Phase 0)."""
        device_id = call.data.get("device_id")
        registry = getattr(coordinator, "_device_registry", None)
        removed = False
        if registry:
            removed = await registry.async_unregister_service_device(device_id)
        elif coordinator._surplus_controller.get_device(device_id):
            coordinator._surplus_controller.unregister_device(device_id)
            removed = True
        if not removed:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_not_found",
                translation_placeholders={"device_id": device_id},
            )
        _LOGGER.info("Unregistered surplus device: %s", device_id)
        if call.return_response:
            return {
                "device_id": device_id,
                "removed": True,
                "total_devices": len(coordinator._surplus_controller._devices),
            }
        return None

    hass.services.async_register(
        DOMAIN,
        "unregister_surplus_device",
        async_unregister_surplus_device,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )

    # Phase 4: Schedule appliance
    async def async_schedule_appliance(call) -> None:
        """Schedule an appliance to run before a deadline."""
        device_id = call.data.get("device_id")
        entity_id = call.data.get("entity_id")
        name = call.data.get("name", device_id)
        deadline_str = call.data.get("deadline")
        runtime_minutes = call.data.get("estimated_runtime_minutes", 120)
        energy_kwh = call.data.get("estimated_energy_kwh", 1.0)
        rated_power = call.data.get("rated_power", 1000)
        priority = call.data.get("priority", 7)

        try:
            deadline = datetime.fromisoformat(deadline_str)
        except (ValueError, TypeError) as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_deadline_format",
                translation_placeholders={"deadline": str(deadline_str)},
            ) from err

        # (#653) Normalise to LOCAL-naive. The scheduler compares deadlines
        # against ``datetime.now()``, which is naive, and an HA template
        # deadline — ``{{ today_at('18:00') }}``, the obvious way to write
        # this in an automation — is timezone-AWARE. Comparing the two
        # raises TypeError. That was harmless while nothing ticked the
        # scheduler; now that the coordinator cycle does, it would raise
        # every cycle and the run would never complete or release its
        # allocation, silently reinstating the very bug #653 fixes.
        # ``as_local`` first, so an explicit offset lands on the right wall
        # clock instead of being truncated.
        if deadline.tzinfo is not None:
            deadline = dt_util.as_local(deadline).replace(tzinfo=None)

        # Lazy-init appliance scheduler
        if not hasattr(coordinator, '_appliance_scheduler'):
            from .devices.appliance_scheduler import ApplianceScheduler
            coordinator._appliance_scheduler = ApplianceScheduler(hass)

        scheduler = coordinator._appliance_scheduler

        # Register if not already known
        if device_id not in scheduler._devices:
            device = scheduler.register_appliance(
                device_id=device_id,
                name=name,
                rated_power=rated_power,
                entity_id=entity_id,
                priority=priority,
            )
            # Also register with surplus controller
            coordinator._surplus_controller.register_device(device)

        scheduler.schedule_appliance(
            device_id=device_id,
            deadline=deadline,
            estimated_runtime_minutes=runtime_minutes,
            estimated_energy_kwh=energy_kwh,
        )

    hass.services.async_register(
        DOMAIN,
        "schedule_appliance",
        async_schedule_appliance,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Required("entity_id"): cv.string,
            vol.Required("deadline"): cv.string,
            vol.Optional("name"): cv.string,
            vol.Optional("estimated_runtime_minutes", default=120): vol.Coerce(int),
            vol.Optional("estimated_energy_kwh", default=1.0): vol.Coerce(float),
            vol.Optional("rated_power", default=1000): vol.Coerce(float),
            vol.Optional("priority", default=7): vol.All(int, vol.Range(min=1, max=10)),
        }),
    )

    async def async_cancel_appliance_schedule(call) -> None:
        """Cancel a pending appliance schedule (#653).

        ``ApplianceScheduler.cancel_schedule`` existed from the start with
        no way to reach it: no service, no button, no automation hook. The
        only way to undo a mis-typed deadline was to restart HA (which drops
        the in-memory scheduler entirely).
        """
        device_id = call.data.get("device_id")
        scheduler = getattr(coordinator, "_appliance_scheduler", None)
        # Raise only when the device is genuinely unknown. For a KNOWN
        # device with no pending entry, ``cancel_schedule`` still clears the
        # device's deadline and returns False — a real state change. Raising
        # there would report a failure after having done the work, on
        # exactly the path someone uses to unstick a device.
        known = scheduler is not None and device_id in scheduler._devices
        cancelled = scheduler.cancel_schedule(device_id) if scheduler else False
        if not cancelled and not known:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_appliance_schedule",
                translation_placeholders={"device_id": str(device_id)},
            )

    hass.services.async_register(
        DOMAIN,
        "cancel_appliance_schedule",
        async_cancel_appliance_schedule,
        schema=vol.Schema({vol.Required("device_id"): cv.string}),
    )

    _LOGGER.debug(
        "Phase services registered: register_surplus_device, "
        "schedule_appliance, cancel_appliance_schedule"
    )

    # #442: in-dashboard option writes. The Configuration tab card
    # writes one key at a time via this service rather than walking the
    # OptionsFlow programmatically — the OptionsFlow has 7 steps and
    # would require the card to know which step owns each key, which is
    # the very coupling the dashboard tab is meant to avoid. The HA
    # public ``config_entries/update`` WebSocket call rejects the
    # ``options`` field (it's reserved for the OptionsFlow round-trip),
    # so this service is the supported escape hatch.
    async def async_set_option(call) -> None:
        """Write one or more keys into the SEM ConfigEntry options.

        Two behaviors based on key kind (#462/#464 fix):

        * **Structural keys** (entity wiring — heat pump relays, hot
          water entity, ev_chargers list shape): force an integration
          reload so controllers get re-instantiated against the new
          wiring. This preserves the #448 heat-pump-relay fix that
          motivated the v1.7.2-beta.2 always-reload behavior.

        * **Tunable keys** (everything else — modes, thresholds,
          targets, switches): mirror the new value into
          ``coordinator.config`` in place and suppress the listener's
          reload via ``_skip_options_reload``. Matches the per-charger
          ``select.py`` / ``number.py`` runtime-tweak pattern that
          existed in v1.7.1 and earlier. Avoids destroying + recreating
          the coordinator (with all attendant per-charger / split-grid
          state) on every tunable change.

        Plus: when ``ev_chargers`` is in the payload, **merge by id**
        instead of full-replace so a partial submit from the Config
        card can never drop a sibling charger (#464 cross-talk).
        """
        options = call.data.get("options")
        if not isinstance(options, dict):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="set_option_invalid_payload",
            )
        # Identify the SEM entry (single-instance integration).
        sem_entries = hass.config_entries.async_entries(DOMAIN)
        if not sem_entries:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="set_option_no_entry",
            )
        target_entry = sem_entries[0]
        if len(sem_entries) > 1:
            for e in sem_entries:
                if e.entry_id == call.data.get("entry_id"):
                    target_entry = e
                    break

        # Smart-merge ``ev_chargers`` by id (#464) — see
        # ``_merge_ev_chargers_by_id`` for the contract.
        #
        # Fall back to ``entry.data.ev_chargers`` when entry.options
        # doesn't have the key — same foot-gun as the per-charger
        # select / number setters in #469. A fresh install has its
        # chargers in entry.data only; the smart-merge needs to see
        # them so a partial submit doesn't append a stray ghost entry
        # and lose the existing chargers on next reload. Caught by
        # ``test_set_option_ev_chargers_partial_submit_preserves_sibling``
        # in the test_services_real.py framework tests.
        if isinstance(options.get("ev_chargers"), list):
            existing_list = (
                (target_entry.options or {}).get("ev_chargers")
                or (target_entry.data or {}).get("ev_chargers")
                or []
            )
            options = {
                **options,
                "ev_chargers": _merge_ev_chargers_by_id(
                    existing_list, options["ev_chargers"],
                ),
            }

        merged = {**(target_entry.options or {}), **options}
        if merged == (target_entry.options or {}):
            _LOGGER.debug(
                "set_option no-op (values unchanged): %s",
                list(options.keys()),
            )
            return

        # Split keys: structural (reload required) vs tunable (route
        # through the matching ``number`` / ``switch`` / ``select``
        # entity so the entity's own write path runs — that's the
        # path that updates ``_attr_native_value`` + writes state,
        # and it already snapshots ``_skip_options_reload`` so the
        # listener short-circuits. Routing through the entity is the
        # only way to avoid the cached-``_attr_native_value`` bug
        # caught live on HA-TEST: setting a tunable directly via
        # ``async_update_entry`` updates the persisted options but
        # leaves the displayed entity stale until the next reload.
        structural_keys = [
            k for k in options if k in _SET_OPTION_STRUCTURAL_KEYS
        ]
        tunable_keys = [
            k for k in options if k not in _SET_OPTION_STRUCTURAL_KEYS
        ]

        # Route each tunable through its per-entity write path FIRST
        # (#485 G4): the direct entry write below triggers a reload,
        # and routing entities while that reload tears them down made
        # mixed payloads drop tunable values mid-loop. Each entity's
        # write path updates entity state, persists to entry.options,
        # and snapshots _skip_options_reload — so no reload, AND
        # entity state is fresh. Unrecognized keys fall through to
        # the direct write.
        # (#637) Keys that the runtime re-reads from coordinator.config every
        # cycle (hw/hp refresh block, vpp_dispatch, the notifier) — route via
        # persist_global_option: in-place config update + _refresh_runtime_
        # config + snapshot, NO reload. Keys consumed only at construction
        # (tariff_mode, battery scheduler params) deliberately stay on the
        # reload path — live-applying them would be the #462 lie.
        _SET_OPTION_LIVE_CONFIG_KEYS = {
            "hot_water_minimum_temperature", "hot_water_legionella_target",
            "heat_pump_max_setpoint", "vpp_reserve_soc",
            "mobile_notification_service",
            # (#819) The coordinator re-applies this to the forecast
            # reader every cycle (set_preferred_source), so it is a
            # genuinely live key rather than a construction-time one.
            "solar_forecast_source",
            # (#829) The coordinator reads this fresh from config on every
            # daily-rollover check (retention_is_due), so changing it takes
            # effect without a reload — a genuinely live key.
            "status_retention_days",
        }
        # (#637) Some options are backed by number entities under a DIFFERENT
        # name (number.py CONFIG_KEY_MAP, #542) — the naive number.sem_<key>
        # check missed them (the legionella dual-path confusion). Reverse-map
        # option key → entity suffix so they entity-route like any other.
        from .number import CONFIG_KEY_MAP as _NUM_MAP
        _OPTION_TO_ENTITY = {v: k for k, v in _NUM_MAP.items()}

        # (#636) Load-management peaks have LIVE updaters but no number
        # entities — pre-fix they fell to the unrouted → entry-write →
        # RELOAD path, so a card slider change never reached the running
        # planner mid-session (the #462 silent-no-op class, caught live
        # when a mid-charge peak change didn't step the EV night rate).
        _LM_LIVE_KEYS = {
            "target_peak_limit": "update_target_peak_limit",
            "warning_peak_level": "update_warning_peak_level",
            "emergency_peak_level": "update_emergency_peak_level",
        }
        unrouted: list[str] = []
        for key in tunable_keys:
            value = options[key]
            _coord = getattr(target_entry, "runtime_data", None)
            if (key in _LM_LIVE_KEYS and _coord is not None
                    and getattr(_coord, "_load_manager", None)):
                await getattr(_coord._load_manager, _LM_LIVE_KEYS[key])(
                    float(value))
                continue
            if key in _SET_OPTION_LIVE_CONFIG_KEYS:
                _c2 = getattr(target_entry, "runtime_data", None)
                if _c2 is not None:
                    persist_global_option(hass, target_entry, _c2, key, value)
                    continue
            _ent_suffix = _OPTION_TO_ENTITY.get(key, key)
            if hass.states.get(f"number.sem_{_ent_suffix}") is not None:
                await hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": f"number.sem_{_ent_suffix}", "value": value},
                    blocking=True,
                )
                continue
            if hass.states.get(f"number.sem_{key}") is not None:
                await hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": f"number.sem_{key}", "value": value},
                    blocking=True,
                )
            elif hass.states.get(f"switch.sem_{key}") is not None:
                svc = "turn_on" if _coerce_switch_on(value) else "turn_off"
                await hass.services.async_call(
                    "switch", svc,
                    {"entity_id": f"switch.sem_{key}"},
                    blocking=True,
                )
            elif hass.states.get(f"select.sem_{key}") is not None:
                await hass.services.async_call(
                    "select", "select_option",
                    {"entity_id": f"select.sem_{key}", "option": str(value)},
                    blocking=True,
                )
            else:
                unrouted.append(key)

        # ONE direct entry write for everything that didn't go through
        # an entity (structural wiring + unrouted keys), then ONE
        # reload. Unrouted keys reload too (#485 G1): keys like
        # ``tariff_mode`` or the ``battery_*`` scheduler params are
        # consumed at coordinator construction only — the previous
        # mirror into ``coordinator.config`` looked successful in
        # diagnostics while the constructed provider/scheduler kept
        # the old value until the next restart (the #462 silent-no-op
        # class). The skip snapshot is armed so the update listener
        # doesn't schedule a SECOND reload racing the explicit one.
        direct_keys = structural_keys + unrouted
        if direct_keys:
            direct_merged = {
                **(target_entry.options or {}),
                **{k: options[k] for k in direct_keys},
            }
            if direct_merged != (target_entry.options or {}):
                coordinator = getattr(target_entry, "runtime_data", None)
                if coordinator is not None:
                    coordinator._skip_options_reload = dict(direct_merged)
                hass.config_entries.async_update_entry(
                    target_entry, options=direct_merged,
                )
                await hass.config_entries.async_reload(target_entry.entry_id)

        # #605 — INFO, not debug: these lines ARE the config change history.
        # The Config tab's Diagnose panel surfaces recent SEM log lines, so a
        # user who fat-fingered a value can see exactly which keys changed and
        # when (values included; the bulky ev_chargers list is elided).
        _LOGGER.info(
            "set_option wrote %d key(s) to entry %s: %s "
            "(structural=%s reload=%s)",
            len(options), target_entry.entry_id,
            {k: options[k] for k in list(options)[:8] if k != "ev_chargers"},
            structural_keys, bool(direct_keys),
        )

    hass.services.async_register(
        DOMAIN,
        "set_option",
        async_set_option,
        schema=vol.Schema({
            vol.Required("options"): dict,
            vol.Optional("entry_id"): cv.string,
        }),
    )

    # #528 Phase 4 — remove an EV charger from the dashboard. ``set_option``
    # smart-merges ``ev_chargers`` (additive, keeps siblings — #464), so it
    # can't express a removal. This service drops the charger by id and
    # reloads. Explicit-intent + id-keyed so it can never accidentally clobber
    # a sibling the way a full-list replace could.
    async def async_remove_charger(call):
        charger_id = (call.data.get("charger_id") or "").strip()
        if not charger_id:
            return
        sem_entries = hass.config_entries.async_entries(DOMAIN)
        if not sem_entries:
            return
        target_entry = sem_entries[0]
        if len(sem_entries) > 1 and call.data.get("entry_id"):
            for e in sem_entries:
                if e.entry_id == call.data["entry_id"]:
                    target_entry = e
                    break
        existing = (
            (target_entry.options or {}).get("ev_chargers")
            or (target_entry.data or {}).get("ev_chargers")
            or []
        )
        dicts = [c for c in existing if isinstance(c, dict)]
        kept = [c for c in dicts if c.get("id") != charger_id]
        if len(kept) == len(dicts):
            _LOGGER.warning("remove_charger: id %s not found — nothing removed", charger_id)
            return
        new_options = {**(target_entry.options or {}), "ev_chargers": kept}
        coordinator = getattr(target_entry, "runtime_data", None)
        if coordinator is not None:
            coordinator._skip_options_reload = dict(new_options)
        hass.config_entries.async_update_entry(target_entry, options=new_options)
        await hass.config_entries.async_reload(target_entry.entry_id)
        _LOGGER.info("Removed EV charger '%s' (%d remain)", charger_id, len(kept))

    hass.services.async_register(
        DOMAIN,
        "remove_charger",
        async_remove_charger,
        schema=vol.Schema({
            vol.Required("charger_id"): cv.string,
            vol.Optional("entry_id"): cv.string,
        }),
    )

    # #442: Configuration-tab read-back service. HA's public
    # ``config_entries/get`` WS call strips ``data`` and ``options``
    # for security, so the dashboard has no way to display current
    # values for option-only fields (entity pickers, slot toggles,
    # etc.). This service returns the merged config dict the
    # OptionsFlow uses internally.
    async def async_get_config(call):
        """Return the merged ``data + options`` for the SEM entry.

        Uses ``supports_response=ONLY`` so the frontend can call this
        via ``hass.callService('solar_energy_management', 'get_config',
        {}, undefined, undefined, true)`` and receive the dict in the
        response.
        """
        sem_entries = hass.config_entries.async_entries(DOMAIN)
        if not sem_entries:
            return {"config": {}}
        target = sem_entries[0]
        requested = call.data.get("entry_id") if call.data else None
        if requested and len(sem_entries) > 1:
            for e in sem_entries:
                if e.entry_id == requested:
                    target = e
                    break
        merged = {**(target.data or {}), **(target.options or {})}
        return {"config": merged, "entry_id": target.entry_id}

    hass.services.async_register(
        DOMAIN,
        "get_config",
        async_get_config,
        schema=vol.Schema({
            vol.Optional("entry_id"): cv.string,
        }),
        supports_response=SupportsResponse.ONLY,
    )

    # #476 item 5 escape hatch: sign-detection locks now PERSIST across
    # restarts, so a wrongly-learned lock no longer clears itself on
    # reboot. This service forgets grid + battery sign locks (RAM and
    # storage) and re-arms the warmup so the signs re-learn cleanly.
    async def async_reset_sign_detection(call):
        """Reset persisted sign-detection state on the SEM entry."""
        sem_entries = hass.config_entries.async_entries(DOMAIN)
        if not sem_entries:
            return
        target = sem_entries[0]
        requested = call.data.get("entry_id") if call.data else None
        # #588 L1 — fix the entry_id guard: the old ``len > 1`` condition
        # silently fell through to entry[0] when requested was set but the
        # install only had one entry (stale/wrong entry_id). Now ANY non-None
        # requested must match, else fail loudly.
        if requested:
            matched = next((e for e in sem_entries if e.entry_id == requested), None)
            if matched is None:
                _LOGGER.warning(
                    "reset_sign_detection: requested entry_id %r not found "
                    "(known: %s)",
                    requested, [e.entry_id for e in sem_entries],
                )
                return
            target = matched
        coordinator = getattr(target, "runtime_data", None)
        if coordinator is None:
            _LOGGER.warning("reset_sign_detection: no coordinator on entry %s", target.entry_id)
            return
        reader = getattr(coordinator, "_sensor_reader", None)
        if reader is not None:
            reader.reset_sign_state()
        # (#690) A reverted auto-correction latches the balance self-heal off so
        # it can't oscillate. This service IS the manual retry, so clear it.
        coordinator._sign_flip_latched = False
        coordinator._sign_flip_attempted = False
        coordinator._negative_balance_count = 0
        coordinator._positive_balance_count = 0
        storage = getattr(coordinator, "_storage", None)
        if storage is not None:
            storage.set_sign_state({})
            await storage.async_save_energy_delayed()
        # A re-learn must start clean: drop any prior one-tap user flip
        # (#461 / #588) so the freshly-learned sign isn't silently re-inverted
        # on top. Only touches the entry — and reloads — when a flip was
        # actually set, so the common reset path stays reload-free.
        opts = target.options or {}
        grid_flip = bool(opts.get("grid_sign_user_flip", False))
        batt_flip = bool(opts.get("battery_sign_user_flip", False))  # #588 H3
        if grid_flip or batt_flip:
            cleared = {**opts, "grid_sign_user_flip": False, "battery_sign_user_flip": False}
            if coordinator is not None:
                coordinator._skip_options_reload = dict(cleared)
            hass.config_entries.async_update_entry(target, options=cleared)
            await hass.config_entries.async_reload(target.entry_id)
        _LOGGER.info("reset_sign_detection: cleared sign locks on entry %s", target.entry_id)

    hass.services.async_register(
        DOMAIN,
        "reset_sign_detection",
        async_reset_sign_detection,
        schema=vol.Schema({
            vol.Optional("entry_id"): cv.string,
        }),
    )

    # #461 one-tap sign flip + support payload. When the auto-detect or a
    # genuinely undecidable meter (swapped / net-only counters) lands the
    # wrong import/export convention, the user taps the Control-tab button:
    # this toggles the persisted ``grid_sign_user_flip`` option (which sits
    # on TOP of the auto/manual decision in sensor_reader), reloads so the
    # corrected sign takes effect immediately, and returns a diagnostics
    # dict the button copies into a pre-filled GitHub issue. The captured
    # payload is what lets us improve the autodetect for that meter class.
    async def async_flip_grid_sign(call):
        """Flip the grid-power sign and return a #461 support payload."""
        sem_entries = hass.config_entries.async_entries(DOMAIN)
        if not sem_entries:
            return {"ok": False, "error": "no_entry"}
        target = sem_entries[0]
        requested = call.data.get("entry_id") if call.data else None
        # #588 L1 — same entry_id fix as reset/flip_battery
        if requested:
            matched = next((e for e in sem_entries if e.entry_id == requested), None)
            if matched is None:
                _LOGGER.warning(
                    "flip_grid_sign: requested entry_id %r not found", requested,
                )
                return {"ok": False, "error": "entry_not_found"}
            target = matched
        coordinator = getattr(target, "runtime_data", None)
        # Snapshot diagnostics BEFORE the flip — captures the state the
        # user is reporting as wrong (raw meter value, counters, evidence).
        diag = {}
        reader = getattr(coordinator, "_sensor_reader", None) if coordinator else None
        if reader is not None:
            try:
                diag = reader.grid_sign_diagnostics()
            except Exception:  # noqa: BLE001 — diag must never block the flip
                _LOGGER.debug("flip_grid_sign: diagnostics snapshot failed", exc_info=True)

        current = bool((target.options or {}).get("grid_sign_user_flip", False))
        new_flip = not current
        new_options = {**(target.options or {}), "grid_sign_user_flip": new_flip}
        # Suppress the update-listener reload; we issue one explicit reload
        # so the new sign is live without a double tear-down (set_option
        # pattern).
        if coordinator is not None:
            coordinator._skip_options_reload = dict(new_options)
        hass.config_entries.async_update_entry(target, options=new_options)
        await hass.config_entries.async_reload(target.entry_id)
        _LOGGER.info(
            "flip_grid_sign: user_flip %s -> %s on entry %s",
            current, new_flip, target.entry_id,
        )
        diag["user_flip_now"] = new_flip
        return {"ok": True, "user_flip": new_flip, "diagnostics": diag}

    hass.services.async_register(
        DOMAIN,
        "flip_grid_sign",
        async_flip_grid_sign,
        schema=vol.Schema({
            vol.Optional("entry_id"): cv.string,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )

    # #588 B1 — battery sign flip, mirrors async_flip_grid_sign exactly.
    # When the battery charge/discharge appears inverted and the auto-detect
    # or brand seed locked the wrong sign, the user taps "Fix battery sign"
    # on the Config tab: this toggles the persisted ``battery_sign_user_flip``
    # option, reloads so the corrected sign takes effect immediately, and
    # returns a diagnostics dict for a GitHub issue.
    async def async_flip_battery_sign(call):
        """Flip the battery-power sign and return a #588 support payload."""
        sem_entries = hass.config_entries.async_entries(DOMAIN)
        if not sem_entries:
            return {"ok": False, "error": "no_entry"}
        target = sem_entries[0]
        requested = call.data.get("entry_id") if call.data else None
        # #588 L1 — entry_id must match exactly (not silently fall through)
        if requested:
            matched = next((e for e in sem_entries if e.entry_id == requested), None)
            if matched is None:
                _LOGGER.warning(
                    "flip_battery_sign: requested entry_id %r not found", requested,
                )
                return {"ok": False, "error": "entry_not_found"}
            target = matched
        coordinator = getattr(target, "runtime_data", None)
        # Snapshot diagnostics BEFORE the flip — captures the state the
        # user is reporting as wrong (raw battery value, counters, evidence).
        diag = {}
        reader = getattr(coordinator, "_sensor_reader", None) if coordinator else None
        if reader is not None:
            try:
                diag = reader.battery_sign_diagnostics()
            except Exception:  # noqa: BLE001 — diag must never block the flip
                _LOGGER.debug("flip_battery_sign: diagnostics snapshot failed", exc_info=True)

        current = bool((target.options or {}).get("battery_sign_user_flip", False))
        new_flip = not current
        new_options = {**(target.options or {}), "battery_sign_user_flip": new_flip}
        # Suppress the update-listener reload; one explicit reload issued below.
        if coordinator is not None:
            coordinator._skip_options_reload = dict(new_options)
        hass.config_entries.async_update_entry(target, options=new_options)
        await hass.config_entries.async_reload(target.entry_id)
        _LOGGER.info(
            "flip_battery_sign: user_flip %s -> %s on entry %s",
            current, new_flip, target.entry_id,
        )
        diag["user_flip_now"] = new_flip
        return {"ok": True, "user_flip": new_flip, "diagnostics": diag}

    hass.services.async_register(
        DOMAIN,
        "flip_battery_sign",
        async_flip_battery_sign,
        schema=vol.Schema({
            vol.Optional("entry_id"): cv.string,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )

    # #432: per-section Diagnose payload. The Configuration tab's
    # ``<sem-diagnose-button>`` Lit element calls this service with a
    # ``section`` name, gets back a focused JSON slice + recent log
    # lines, then shows it in a modal with a "Copy to clipboard"
    # button. The user pastes the result on the discussion → maintainer
    # gets a signal-rich payload instead of the 5 MB diagnostics dump.
    #
    # Phase 1 (this beta): supports ``all`` + ``heat_pump`` cleanly.
    # Other sections return a generic slice for now; their dedicated
    # slicers land in a follow-up beta. The button shell + modal +
    # copy flow are wired everywhere so the user surface is consistent.
    # Per-section diagnose slicers. Each section's tuple is
    # ``(state_keys, option_keys_or_prefix_predicate)``. State keys are
    # SEM-published ``coordinator.data`` keys. Option key predicates
    # are either an explicit set or a callable that selects keys from
    # ``merged_cfg``. Heat-pump uses the explicit-set form because it
    # has a small, stable surface; other sections use predicates so
    # they pick up per-charger entries inside ``ev_chargers`` lists.
    _DIAGNOSE_HEAT_PUMP_STATE = {
        "heat_pump_registered", "heat_pump_registration_status",
        "heat_pump_mode", "heat_pump_sg_ready_state", "heat_pump_solar_boost",
        "heat_pump_relay1_entity", "heat_pump_relay2_entity",
        "heat_pump_climate_entity",
        "heat_pump_relay1_state", "heat_pump_relay2_state",
        "heat_pump_climate_state",
        # v1.7.2-beta.2: #421 audit's runtime path recorders, now
        # surfaced through coordinator.data so users can see WHY the
        # heat pump did/didn't activate on the last cycle.
        "heat_pump_activation_path", "heat_pump_deactivation_path",
        "heat_pump_relay_path", "heat_pump_temperature_reading_path",
        "heat_pump_offpeak_path", "heat_pump_current_temperature",
    }
    _DIAGNOSE_HEAT_PUMP_OPTION = {
        "heat_pump_relay1_entity", "heat_pump_relay2_entity",
        "heat_pump_climate_entity", "heat_pump_boost_offset",
        "heat_pump_max_setpoint", "heat_pump_priority",
        "heat_pump_power_sensor", "heat_pump_temperature_sensor",
        "heat_pump_rated_power", "heat_pump_force_on_threshold",
        "heat_pump_sg_ready_service", "heat_pump_sg_ready_service_data",
        "heat_pump_sg_ready_state_entity", "heat_pumps",
    }
    # Hot water — config visibility (controller not currently wired
    # into the production path; v1.7.2-beta.2 surfaces config so
    # support can verify settings, and reserves the state keys for
    # when the controller is hooked up).
    _DIAGNOSE_HOT_WATER_OPTION = {
        "hot_water_entity", "hot_water_temperature_sensor",
        "hot_water_solar_target", "hot_water_max_temperature",
        "hot_water_legionella_target", "hot_water_minimum_temperature",
        "hot_water_priority", "hot_water_rated_power",
    }
    _DIAGNOSE_HOT_WATER_STATE = {
        # v1.7.2-beta.6 (#454): wire-up complete. HotWaterController
        # is now registered with the SurplusController when
        # ``hot_water_entity`` is set, so the runtime state surface
        # populates these keys.
        "hot_water_registered", "hot_water_entity",
        "hot_water_temperature_sensor",
        "hot_water_current_temperature",
        "hot_water_solar_target", "hot_water_max_temperature",
        "hot_water_legionella_target", "hot_water_hours_since_legionella",
        "hot_water_legionella_cycle_active",
        "hot_water_activation_path", "hot_water_deactivation_path",
        "hot_water_temperature_safety_path",
        "hot_water_temperature_reading_path",
        "hot_water_legionella_path",
    }
    # EV chargers — fleet aggregates + per-charger nested entries
    _DIAGNOSE_EV_OPTION_TOP = {
        "ev_chargers",  # whole list — most useful for diagnose
        "ev_min_current", "ev_max_current", "ev_phases", "ev_voltage",
        "daily_ev_target", "daily_ev_target_max",
        "ev_target_type", "ev_target_soc", "ev_target_soc_max",
        "ev_battery_capacity_kwh", "ev_kwh_per_100km",
        "ev_enable_delay_seconds", "ev_disable_delay_seconds",
    }
    _DIAGNOSE_EV_STATE_PREFIXES = ("ev_", "charger_", "daily_ev", "session_")
    # Tariff — pricing config + classifier diagnostics
    _DIAGNOSE_TARIFF_OPTION = {
        "tariff_mode", "tariff_classification_mode",
        "dynamic_tariff_entity", "dynamic_forecast_entity", "dynamic_feedin_entity",
        "electricity_import_rate", "electricity_off_peak_rate",
        "electricity_export_rate", "demand_charge_rate",
        "cheap_price_threshold", "expensive_price_threshold",
    }
    _DIAGNOSE_TARIFF_STATE = {
        "tariff_provider", "tariff_is_dynamic", "tariff_currency",
        "tariff_price_level", "tariff_classifier_path",
        "tariff_current_import_rate", "tariff_current_export_rate",
        "tariff_today_min_price", "tariff_today_max_price", "tariff_today_avg_price",
        "tariff_next_cheap_start", "tariff_next_cheap_end",
        "tariff_upcoming", "tariff_schedule_today",
        # v1.7.2-beta.3: classifier visibility for the "all day cheap"
        # class of misclassifications. ``tariff_today_prices_count``
        # of 0 means SEM isn't seeing per-hour data — JS card will
        # fall back to mirroring the current price level for the chart.
        # ``tariff_parsed_interval_seconds`` exposes 15-min vs hourly
        # detection so we can spot a NL Tibber Pulse / ENTSO-E shape
        # mismatch (RienduPre, Discussion #432).
        "tariff_today_prices_count", "tariff_today_level_counts",
        "tariff_today_first_price", "tariff_today_last_price",
        "tariff_parsed_attribute", "tariff_parsed_count",
        "tariff_parsed_interval_seconds",
    }
    # Battery zones
    _DIAGNOSE_BATTERY_ZONES_OPTION = {
        "battery_priority_soc", "battery_buffer_soc", "battery_auto_start_soc",
        "battery_capacity_kwh",
    }
    _DIAGNOSE_BATTERY_ZONES_STATE = {
        "battery_soc", "battery_power", "battery_charge_power",
        "battery_discharge_power", "battery_status",
        "battery_health_score", "battery_temperature",
    }
    # Battery scheduler
    _DIAGNOSE_BATTERY_SCHEDULER_OPTION = {
        "battery_charge_scheduler_enabled", "battery_capacity_kwh",
        "battery_max_charge_power_w", "battery_roundtrip_efficiency",
        "battery_cycle_cost", "battery_precharge_trigger_hour",
        "battery_max_target_soc", "battery_min_deficit_kwh",
        "battery_pessimism_weight", "battery_force_charge_negative_price",
        "battery_replan_interval_min", "battery_prefer_consecutive_window",
    }
    _DIAGNOSE_BATTERY_SCHEDULER_STATE = {
        "battery_scheduler_active", "battery_scheduler_target_soc",
        "battery_scheduler_target_kwh", "battery_scheduler_window_start",
        "battery_scheduler_window_end", "battery_scheduler_reason",
    }
    # Load management
    _DIAGNOSE_LOAD_MGMT_OPTION = {
        "load_management_enabled", "target_peak_limit",
        "warning_peak_level", "emergency_peak_level",
    }
    _DIAGNOSE_LOAD_MGMT_STATE = {
        "load_management_status", "load_management_recommendation",
        "loads_currently_shed", "controllable_devices_count",
        "consecutive_peak_15min", "monthly_consecutive_peak",
        "current_vs_peak_percentage", "available_load_reduction",
        # (#433, #896) why: the state machine's paths and the shed verdict
        "state_decision_path", "process_path", "action_path", "last_error",
        "shed_path", "shed_need_w", "shed_sheddable_w", "shed_futile",
        "uncontrolled_w",
    }
    # Forecast
    _DIAGNOSE_FORECAST_OPTION = {
        "forecast_dampening_factor",  # the one config knob that exists
    }
    _DIAGNOSE_FORECAST_STATE = {
        "forecast_today_kwh", "forecast_tomorrow_kwh",
        "forecast_source", "forecast_available",
        "forecast_dampening_factor", "forecast_remaining_today_kwh",
        "best_surplus_window",
    }
    # Notifications
    _DIAGNOSE_NOTIFICATIONS_OPTION = {
        "enable_charger_notifications", "enable_mobile_notifications",
        "mobile_notification_service",
    }
    _DIAGNOSE_NOTIFICATIONS_STATE = set()  # notifications are fire-and-forget; no state surface
    # Advanced
    _DIAGNOSE_ADVANCED_OPTION = {
        "observer_mode", "update_interval", "minimum_solar_power",
    }
    _DIAGNOSE_ADVANCED_STATE = {
        "observer_mode", "update_interval", "minimum_solar_power",
        # ``last_update`` still lives in coordinator.data (this reads from there,
        # not entity attributes). ``delta_triggered`` was never populated and is
        # gone as of #581 — dropped here too rather than leave a dead key.
        "last_update",
    }

    _DIAGNOSE_SLICERS = {
        "heat_pump": (_DIAGNOSE_HEAT_PUMP_OPTION, _DIAGNOSE_HEAT_PUMP_STATE),
        "hot_water": (_DIAGNOSE_HOT_WATER_OPTION, _DIAGNOSE_HOT_WATER_STATE),
        "ev_chargers": (_DIAGNOSE_EV_OPTION_TOP, _DIAGNOSE_EV_STATE_PREFIXES),
        "tariff": (_DIAGNOSE_TARIFF_OPTION, _DIAGNOSE_TARIFF_STATE),
        "battery_zones": (_DIAGNOSE_BATTERY_ZONES_OPTION, _DIAGNOSE_BATTERY_ZONES_STATE),
        "battery_scheduler": (_DIAGNOSE_BATTERY_SCHEDULER_OPTION, _DIAGNOSE_BATTERY_SCHEDULER_STATE),
        "load_management": (_DIAGNOSE_LOAD_MGMT_OPTION, _DIAGNOSE_LOAD_MGMT_STATE),
        "forecast": (_DIAGNOSE_FORECAST_OPTION, _DIAGNOSE_FORECAST_STATE),
        "notifications": (_DIAGNOSE_NOTIFICATIONS_OPTION, _DIAGNOSE_NOTIFICATIONS_STATE),
        "advanced": (_DIAGNOSE_ADVANCED_OPTION, _DIAGNOSE_ADVANCED_STATE),
    }

    _DIAGNOSE_LOG_NEEDLES = {
        "all": (),  # no filter — caller wants every recent SEM line
        "heat_pump": ("heat_pump", "heatpump", "sg_ready", "HeatPumpController"),
        "hot_water": ("hot_water", "hot water", "HotWaterController", "boiler", "dhw"),
        "ev_chargers": ("ev_control", "ev_charger", "keba", "wallbox", "charger_"),
        "battery_zones": ("battery_soc", "zone", "battery_priority"),
        "tariff": ("tariff", "classifier", "percentile", "nordpool", "tibber"),
        "battery_scheduler": ("battery_charge_scheduler", "precharge"),
        "load_management": ("load_management", "peak_management"),
        "forecast": ("forecast",),
        "notifications": ("notification", "notify"),
        "advanced": (),
        "overview": (),
    }

    def _charger_actuation_diag(hass, coordinator) -> dict:
        """Per-charger actuation truth for the #548 stop-not-taking class.

        For each live charger: the adapter type, the status sensor + raw value
        + classification, the enable switch + its state + whether SEM can drive
        it (``enable_state``), the actual_charging / self_charging verdicts, the
        live power vs the believed setpoint, and the reconciler's last desired
        state + actions + the stop-not-taking counter. This is exactly what's
        needed to tell "SEM never issued the stop" from "SEM issued it but the
        box ignored it" without another round-trip.
        """
        from .coordinator.charger_types import ChargerPower
        from .coordinator.charger_adapters import adapter_for

        out: dict = {}
        devs = getattr(coordinator, "_ev_devices", {}) or {}
        adapters = getattr(coordinator, "_charger_adapters", {}) or {}
        recs = getattr(coordinator, "_charger_reconcilers", {}) or {}

        def _state(eid):
            if not eid:
                return None
            st = hass.states.get(eid)
            return st.state if st else "<missing>"

        for cid, dev in devs.items():
            adapter = adapters.get(cid)
            rec = recs.get(cid)
            # In observer mode (or before the first per-charger cycle) the
            # adapter isn't cached — build a transient one so the status /
            # enable / actual_charging verdicts are still reported. The
            # reconciler memory (last_actions) only exists when cached.
            adapter_cached = adapter is not None
            if adapter is None:
                try:
                    adapter = adapter_for(dev)
                except Exception:  # noqa: BLE001
                    adapter = None
            entry = {
                "adapter": type(adapter).__name__ if adapter else None,
                "adapter_cached": adapter_cached,
                "charger_service": getattr(dev, "charger_service", None),
                "current_entity": getattr(dev, "current_entity_id", None),
                "current_entity_state": _state(getattr(dev, "current_entity_id", None)),
                "start_stop_entity": getattr(dev, "start_stop_entity", None),
                "start_stop_state": _state(getattr(dev, "start_stop_entity", None)),
                "status_entity": getattr(dev, "charging_status_entity", None),
                "status_raw": _state(getattr(dev, "charging_status_entity", None)),
                "believed_setpoint_a": getattr(dev, "_current_setpoint", None),
                "session_active": getattr(dev, "_session_active", None),
                # #553 — SEM's belief that the KEBA runaway-cap energy target
                # is armed (stop arms, start releases).
                "idle_guard_armed": getattr(dev, "_idle_guard_armed", None),
                "power_entity": getattr(dev, "power_entity_id", None),
                "power_w": _state(getattr(dev, "power_entity_id", None)),
            }
            # Adapter verdicts (status class, enable_state, actual_charging).
            if adapter is not None:
                try:
                    if hasattr(adapter, "_status_class"):
                        entry["status_class"] = adapter._status_class()
                except Exception as e:  # noqa: BLE001
                    entry["status_class"] = f"err:{e}"
                try:
                    en, ctrl = adapter.enable_state()
                    entry["enable_state"] = {"enabled": en, "controllable": ctrl}
                except Exception as e:  # noqa: BLE001
                    entry["enable_state"] = f"err:{e}"
                try:
                    pw = float(entry["power_w"])
                except (TypeError, ValueError):
                    pw = 0.0
                try:
                    p = ChargerPower(charger_id=cid, power_w=pw)
                    entry["actual_charging"] = adapter.actual_charging(p)
                    entry["is_self_charging"] = adapter.is_self_charging(p)
                except Exception as e:  # noqa: BLE001
                    entry["actual_charging"] = f"err:{e}"
            # Reconciler memory: what SEM last decided + did, and the
            # stop-not-taking counter (the smoking gun for #548).
            if rec is not None:
                entry["reconciler"] = {
                    "last_desired": getattr(rec, "_last_desired", None),
                    "last_actions": getattr(rec, "_last_actions", None),
                    "consecutive_idle": getattr(rec, "_consecutive_idle_count", None),
                    "charging_intent_active": getattr(rec, "_charging_intent_active", None),
                    "enable_attempts": getattr(rec, "_enable_attempts", None),
                    "stop_commanded_while_drawing": getattr(rec, "_stop_commanded_while_drawing", None),
                }
            out[cid] = entry
        return out

    async def async_diagnose(call):
        """Return a focused diagnose payload for a section.

        Used by the Configuration tab Diagnose buttons. The output is a
        dict ``{section, payload}`` where ``payload`` has three sub-blocks:

          * ``config``  — the configured option keys for the section
          * ``state``   — the live SEM-published state for the section
          * ``recent_logs`` — last few SEM log lines matching the section

        The frontend renders this as monospace JSON in a modal with a
        Copy-to-clipboard button.
        """
        section = (call.data.get("section") if call.data else None) or "all"
        sem_entries = hass.config_entries.async_entries(DOMAIN)
        if not sem_entries:
            return {"section": section, "payload": {"error": "no_sem_entry"}}
        target = sem_entries[0]
        merged_cfg = {**(target.data or {}), **(target.options or {})}
        coordinator = target.runtime_data
        live = (coordinator.data or {}) if coordinator else {}

        # Slice the config + state to the section's keys via the
        # dedicated-slicer map. ``state`` is either an explicit key set
        # OR a tuple of prefixes (used by ``ev_chargers`` where the
        # state surface is broad — every per-charger sensor key starts
        # with ``charger_<id>_``).
        if section == "all" or section == "overview":
            config = dict(merged_cfg)
            state = dict(live)
        elif section in _DIAGNOSE_SLICERS:
            opt_keys, state_keys = _DIAGNOSE_SLICERS[section]
            config = {k: merged_cfg.get(k) for k in opt_keys if k in merged_cfg}
            if isinstance(state_keys, tuple):
                # Prefix tuple — match any key starting with one of them.
                state = {
                    k: v for k, v in live.items()
                    if any(k.startswith(p) for p in state_keys)
                }
            else:
                state = {k: live.get(k) for k in state_keys if k in live}
        else:
            # Unknown section name — return empty payload rather than
            # the whole dump (which the user gets via section=all).
            config = {}
            state = {}

        # Last ~20 SEM log lines (or filtered) — reuse the diagnostics
        # log tail logic so behaviour stays consistent.
        try:
            from .diagnostics import _get_recent_sem_logs
            all_logs = await _get_recent_sem_logs(hass)
        except Exception:  # noqa: BLE001
            all_logs = []
        needles = _DIAGNOSE_LOG_NEEDLES.get(section, ())
        if needles:
            recent_logs = [
                ln for ln in all_logs
                if any(n.lower() in ln.lower() for n in needles)
            ][-20:]
        else:
            recent_logs = list(all_logs)[-20:]

        # Read SEM integration version — cached classmethod, warmed off-loop
        # at setup (the previous inline open() was a blocking call in the
        # event loop on every diagnose invocation).
        sem_version = SEMCoordinator._get_version()

        payload = {
            "version": sem_version,
            "entry_id": target.entry_id,
            "entry_version": f"{target.version}.{getattr(target, 'minor_version', 0)}",
            "config": config,
            "state": state,
            "recent_logs": recent_logs,
        }

        # (#638 G3) Tonight's shadow plan — the 22:00 answer, inspectable on
        # demand (journals rotate; this doesn't). None until the first
        # night-window trigger after startup.
        shadow_plan = (getattr(coordinator, "_energy_plan_shadow", None)
                       if coordinator else None)
        if shadow_plan is not None:
            payload["energy_plan_shadow"] = shadow_plan

        # Layered-trace health summary (1.7.5) — tiny, so EVERY Diagnose
        # button surfaces "is a control layer disagreeing right now?" at a
        # glance. The FULL per-cycle chain is added to the trace / ev_chargers
        # sections below. Best-effort, never raises.
        try:
            payload["trace_health"] = {
                "health": coordinator.trace_health(),
                "mismatch": coordinator.trace_latest_mismatch(),
            }
        except Exception as exc:  # noqa: BLE001
            payload["trace_health"] = {"error": str(exc)}

        # ev_chargers storage split (#462/#464 follow-up). The merged
        # ``config`` block hides whether a charger entry lives in
        # entry.data or entry.options — the load-bearing fact when a
        # per-charger write silently no-ops because the options-side
        # list is partial. Surface both sides so the next triage round
        # doesn't need .storage access.
        if section in ("all", "ev_chargers"):
            def _chargers_brief(side: dict | None):
                lst = (side or {}).get("ev_chargers")
                if not isinstance(lst, list):
                    return "absent"
                return [
                    {
                        "id": c.get("id"),
                        "name": c.get("name"),
                        "charge_mode": c.get("charge_mode"),
                    }
                    if isinstance(c, dict)
                    else {"invalid_entry": type(c).__name__}
                    for c in lst
                ]
            payload["ev_chargers_storage_split"] = {
                "data": _chargers_brief(target.data),
                "options": _chargers_brief(target.options),
            }

            # #548 actuation truth — the load-bearing facts for "SEM says
            # stop but the charger keeps charging": per charger, the adapter's
            # status read + classification, the enable-switch state SEM sees,
            # whether SEM thinks it can control it, the actual_charging verdict,
            # and what the reconciler last DID. Without this every triage round
            # needs another screenshot. Computed live from the cached
            # adapters/reconcilers/devices — never raises (best-effort).
            try:
                payload["ev_actuation"] = _charger_actuation_diag(hass, coordinator)
            except Exception as exc:  # noqa: BLE001
                payload["ev_actuation"] = {"error": str(exc)}

        if section in ("all", "trace", "ev_chargers"):
            # Layered-trace observability (1.7.5) — the recent
            # management→process→integration chain per cycle, plus the current
            # layer-boundary mismatch (acted but observed disagrees) if any.
            # This is the "pull the last 30 cycles and read the chain" tool
            # that would have made the 2026-07-10 EV flap a minutes-long
            # debug. Included on the EV Diagnose button (the primary debug
            # case) as well as the dedicated trace section. Read-only,
            # best-effort, never raises.
            try:
                payload["trace"] = {
                    "health": coordinator.trace_health(),
                    "mismatch": coordinator.trace_latest_mismatch(),
                    "recent": coordinator.trace_recent(30),
                }
            except Exception as exc:  # noqa: BLE001
                payload["trace"] = {"error": str(exc)}

        return {"section": section, "payload": payload}

    hass.services.async_register(
        DOMAIN,
        "diagnose",
        async_diagnose,
        schema=vol.Schema({
            vol.Optional("section", default="all"): cv.string,
        }),
        supports_response=SupportsResponse.ONLY,
    )
