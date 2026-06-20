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
from typing import Any, Dict

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, SupportsResponse, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.util import dt as dt_util
import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator.sensor_reader import GRID_TRIGGER_HINTS
from .coordinator import SEMCoordinator

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
    "heat_pump_relay1_entity", "heat_pump_relay2_entity",
    "heat_pump_climate_entity", "heat_pump_power_sensor",
    "heat_pump_temperature_sensor",
    # #523: read at HeatPumpController construction, so a change must reload
    # to rebuild the controller with the new relay polarity.
    "heat_pump_invert_sg_ready",
    "hot_water_entity", "hot_water_power_sensor",
    "hot_water_temperature_sensor",
    "ev_chargers",
    # #523 Tier 3: the forced-discharge entity is read at battery-adapter
    # construction, so changing it must reload to rebuild the adapter.
    "battery_force_discharge_control_entity",
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
    coordinator._skip_options_reload = new_options
    hass.config_entries.async_update_entry(entry, options=new_options)


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
                DEFAULT_BATTERY_ASSIST_FLOOR_SOC,
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
                ("battery_assist_floor_soc", DEFAULT_BATTERY_ASSIST_FLOOR_SOC),
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

    _LOGGER.info("Migration to version %s.%s done", entry.version, entry.minor_version)
    return True


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

    # Merge entry.data and entry.options for complete configuration
    full_config = {**entry.data, **entry.options}
    _LOGGER.debug("Configuration keys: %s", list(full_config.keys()))

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

    # Create repair issue if EV charger is not configured (quality scale: repair-issues)
    if not full_config.get("ev_connected_sensor") and not full_config.get("ev_charging_power_sensor"):
        ir.async_create_issue(
            hass,
            DOMAIN,
            "ev_charger_not_configured",
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="ev_charger_not_configured",
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, "ev_charger_not_configured")

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
            await registry.async_initialize()
            coordinator._device_registry = registry
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
                    ev_auto["id"] = "ev_charger"
                    ev_auto["name"] = "EV Charger"
                    ev_chargers_config = [ev_auto]
                    # Persist discovered config
                    new_options = dict(entry.options)
                    new_options["ev_chargers"] = ev_chargers_config
                    hass.config_entries.async_update_entry(entry, options=new_options)
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
        from .devices.base import CurrentControlDevice
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

            # Resolve config: charger-specific keys, fall back to global config
            def _cfg(key, default=None):
                v = charger_cfg.get(key)
                if v is not None:
                    return v
                v = full_config.get(key)
                return v if v is not None else default

            ev_power_entity = _cfg("ev_charging_power_sensor")
            ev_charger_service = _cfg("ev_charger_service")
            ev_service_entity = _cfg("ev_charger_service_entity_id")
            ev_current_entity = _cfg("ev_current_control_entity")
            ev_priority = int(_cfg("ev_surplus_priority", _cfg("ev_load_priority", 3 + idx)))
            # #470: shed priority is independent of surplus priority. A
            # mixed fleet wants e.g. the long-range EV to charge FIRST on
            # surplus (big battery soaks watts) yet shed FIRST under peak
            # (range cushion absorbs a throttle). ``ev_shed_priority``
            # carries the load-manager order; it falls back to the surplus
            # priority so single-charger / homogeneous installs are
            # behaviour-identical (the v12→v13 migration seeds it
            # explicitly per charger so flips are deliberate).
            ev_shed_priority = int(_cfg("ev_shed_priority", ev_priority))

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
                max_current=float(_cfg("max_charging_current", 32)),
                phases=int(_cfg("ev_phases", 3)),
                voltage=230.0,
                power_entity_id=ev_power_entity,
                charger_service=ev_charger_service,
                charger_service_entity_id=ev_service_entity,
                current_entity_id=ev_current_entity,
            )
            ev_device.needs_pilot_cycle = _cfg("ev_charger_needs_cycle", False)
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
            _missing = []
            for _attr, _eid in _to_check:
                if not _eid:
                    continue
                if hass.states.get(_eid) is None:
                    _missing.append((_attr, _eid))
            if _missing:
                _LOGGER.warning(
                    "EV charger '%s' (%s): %d configured entity ID(s) "
                    "missing from HA's state registry — SEM commands to "
                    "these silently no-op. Likely cause: the upstream "
                    "integration renamed entities after a version upgrade "
                    "(common with Wallbox/KEBA/Easee on HA core upgrades). "
                    "Affected: %s",
                    charger_name, charger_id, len(_missing),
                    ", ".join(f"{a}={e}" for a, e in _missing),
                )

            # Also register in load management for peak shedding (#436:
            # pass per-charger id + name so each ev_chargers[i] gets its
            # own ``load_device_<id>`` entry in self._devices instead of
            # all chargers colliding on a hardcoded ``ev_charger`` key).
            if coordinator._load_manager:
                await coordinator._load_manager.register_ev_charger(
                    current_control_entity=ev_current_entity,
                    power_entity=ev_power_entity,
                    priority=ev_shed_priority,  # #470: shed order, not surplus order
                    is_critical=False,
                    charger_service=ev_charger_service,
                    charger_id=charger_id,
                    charger_name=charger_name,
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

        # Register heat pump SG-Ready controller if configured
        hp_relay1 = full_config.get("heat_pump_relay1_entity")
        hp_relay2 = full_config.get("heat_pump_relay2_entity")
        hp_climate = full_config.get("heat_pump_climate_entity")
        has_sg_ready = bool(hp_relay1 and hp_relay2)
        has_climate = bool(hp_climate)
        # #437: registration was gated on (relay1 AND relay2) — too
        # strict for non-SG-Ready heat pumps (Nibe, Mitsubishi, Daikin
        # etc.) that only expose a ``climate`` entity. The controller
        # itself already handles climate-only mode internally (the
        # ``_set_sg_ready_state`` ``no_relays_configured`` branch is
        # exercised by the #421 audit telemetry tests). Widen the gate
        # to (relays) OR (climate) so climate-only installs get
        # automatic setpoint boost on surplus.
        if has_sg_ready or has_climate:
            from .devices.heat_pump_controller import HeatPumpController
            hp_device = HeatPumpController(
                hass=hass,
                device_id="heat_pump",
                name=full_config.get("heat_pump_name", "Heat Pump"),
                rated_power=float(full_config.get("heat_pump_rated_power", 2000)),
                priority=int(full_config.get("heat_pump_priority", 4)),
                relay1_entity_id=hp_relay1,
                relay2_entity_id=hp_relay2,
                climate_entity_id=hp_climate,
                power_entity_id=full_config.get("heat_pump_power_sensor"),
                temperature_entity_id=full_config.get("heat_pump_temperature_sensor"),
                boost_offset=float(full_config.get("heat_pump_boost_offset", 2.0)),
                max_setpoint=float(full_config.get("heat_pump_max_setpoint", 55.0)),
                force_on_threshold=float(full_config.get("heat_pump_force_on_threshold", 5000)),
                invert_sg_ready=bool(full_config.get("heat_pump_invert_sg_ready", False)),
            )
            coordinator._surplus_controller.register_device(hp_device)
            mode_label = (
                "SG-Ready+climate" if has_sg_ready and has_climate
                else "SG-Ready only" if has_sg_ready
                else "climate-only setpoint boost"
            )
            _LOGGER.info(
                "Heat pump registered (mode=%s, priority=%d, "
                "relay1=%s, relay2=%s, climate=%s)",
                mode_label, hp_device.priority,
                hp_relay1 or "—", hp_relay2 or "—", hp_climate or "—",
            )
        else:
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
                temperature_entity_id=full_config.get("hot_water_temperature_sensor"),
                max_temperature=float(full_config.get("hot_water_max_temperature", 70.0)),
                min_temperature=float(full_config.get("hot_water_minimum_temperature", 40.0)),
                solar_target_temp=float(full_config.get("hot_water_solar_target", 50.0)),
                legionella_target_temp=float(full_config.get("hot_water_legionella_target", 65.0)),
                legionella_interval_hours=float(full_config.get("hot_water_legionella_interval_hours", 168.0)),
            )
            coordinator._surplus_controller.register_device(hw_device)
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
    # observer mode (test installs don't want notification spam).
    _welcome_fired = entry.options.get("_welcome_notification_fired", False)
    if not _welcome_fired and not entry.data.get("observer_mode"):
        try:
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "notification_id": "sem_first_install_welcome",
                    "title": "Solar Energy Management installed",
                    "message": (
                        "👋 Welcome! Your SEM dashboard is ready at "
                        "[Open the SEM Dashboard](/sem-dashboard/home).\n\n"
                        "**First-day checklist:**\n"
                        "1. Confirm solar is reporting on the Energy tab\n"
                        "2. Pick an EV charge mode on the EV tab\n"
                        "3. Set your battery reserve on the Battery tab\n\n"
                        "Everything else has sensible defaults — tune later "
                        "via Settings → Devices & Services → SEM → Configure."
                    ),
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
            sc = getattr(coordinator, "_surplus_controller", None)
            if sc is not None and hasattr(sc, "clear_devices"):
                sc.clear_devices()

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

            # Step 1: Install SVG system diagram + card JS files to /config/www/
            # All filesystem ops run in an executor to avoid blocking the event loop.
            component_dir = os.path.dirname(__file__)
            svg_source = os.path.join(component_dir, "dashboard", "www", "sem-system-diagram.svg")
            www_target_dir = os.path.join(hass.config.config_dir, "www", "sem")
            svg_target = os.path.join(www_target_dir, "sem-system-diagram.svg")
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
                "sem-reactive-base.js",
                "sem-shared.js",
                "sem-system-diagram-card.js",
            }

            def _install_assets() -> tuple[bool, list[str]]:
                """Sync top-level dashboard assets to /config/www/. Runs in executor."""
                os.makedirs(www_target_dir, exist_ok=True)
                svg_installed = False
                if os.path.exists(svg_source):
                    shutil.copy2(svg_source, svg_target)
                    svg_installed = True

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
                        if fname not in CANONICAL_TOP_LEVEL:
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
                return svg_installed, cards

            svg_installed, installed_cards = await hass.async_add_executor_job(_install_assets)
            if svg_installed:
                _LOGGER.info("Installed SVG diagram to %s", svg_target)
            else:
                _LOGGER.warning("SVG diagram not found at %s", svg_source)
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
            # See _content_hash_cache_bust at module level. Inlined into a
            # closure here so the resolved card_www_dir + manifest version
            # are captured once per service call.
            manifest_path_l = os.path.join(component_dir, "manifest.json")
            try:
                with open(manifest_path_l) as f:
                    _mver = json.load(f).get("version", "0")
            except Exception:
                _mver = "0"

            def _cache_bust_for(base_url: str) -> str:
                return _content_hash_cache_bust(card_www_dir, base_url, _mver)

            existing_bases = {item.get("url", "").split("?")[0] for item in resources_data["items"]}
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

            # Update ?v= on existing SEM resources and remove orphaned ones
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

        if prop == "critical":
            await coordinator._load_manager.update_device_critical_status(device_id, bool(value))
        elif prop == "controllable":
            await coordinator._load_manager.update_device_controllable_status(device_id, bool(value))
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
            # Update device dependency (#122)
            device = coordinator._surplus_controller.get_device(device_id)
            if device:
                device.depends_on = [str(value)] if value else []
                _LOGGER.info("Updated %s depends_on = %s", device_id, device.depends_on)
                # Persist to storage
                if coordinator._load_manager and hasattr(coordinator._load_manager, '_store'):
                    try:
                        store_data = await coordinator._load_manager._store.async_load() or {"devices": {}}
                        dev_data = store_data.setdefault("devices", {}).setdefault(device_id, {})
                        dev_data["depends_on"] = device.depends_on
                        await coordinator._load_manager._store.async_save(store_data)
                    except Exception as e:
                        _LOGGER.debug("Could not persist dependency: %s", e)
            else:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="device_not_found",
                    translation_placeholders={"device_id": device_id},
                )
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
                vol.Required("property"): vol.In(["controllable", "critical", "control_mode", "depends_on"]),
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
        await coordinator._load_manager.update_target_peak_limit(float(target))
        _LOGGER.info("Updated target peak limit to %.1f kW", target)

    try:
        hass.services.async_register(
            DOMAIN,
            "update_target_peak",
            async_update_target_peak,
            schema=vol.Schema({
                vol.Required("target_peak_limit"): vol.All(
                    vol.Coerce(float), vol.Range(min=1.0, max=20.0)
                ),
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

        # Register static path (may fail on reload if already registered)
        try:
            hass.http.register_static_path(
                static_path, dashboard_path, cache_headers=False
            )
        except Exception:
            pass  # Already registered from previous load

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
                "localize": _token("sem-localize.js"),
                "bundle": _token("dist", "sem-cards.js"),
                "diagram": _token("sem-system-diagram-card.js"),
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
            # sem-system-diagram-card.js is NOT in the Lit bundle — keep it registered
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
                    "  - url: %s\n    type: module\n"
                    "  - url: %s\n    type: module",
                    cards_bundle_url,
                    f"{static_path}/card/sem-system-diagram-card.js?v={asset_v['diagram']}",
                    localize_url,
                )
                # Skip the rest of the registration block — none of the
                # mutating methods below are callable in YAML mode.
                raise _SEMYAMLModeSkip()

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

            # Register standalone diagram card (vanilla JS, not in Lit bundle)
            diagram_base = f"{static_path}/card/sem-system-diagram-card.js"
            diagram_url = f"{diagram_base}?v={asset_v['diagram']}"
            diagram_item = existing_by_base.get(diagram_base)
            if diagram_item is None:
                await resources.async_create_item({"res_type": "module", "url": diagram_url})
                _LOGGER.info("Registered SEM diagram card: %s", diagram_url)
            elif diagram_item["url"] != diagram_url:
                await resources.async_update_item(
                    diagram_item["id"], {"res_type": "module", "url": diagram_url}
                )
                _LOGGER.info("Updated SEM diagram card: %s → %s", diagram_item["url"], diagram_url)

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
        # Copy Lit bundle from dist/ subdirectory
        dist_src_dir = os.path.join(card_src_dir, "dist")
        dist_www_dir = os.path.join(card_www_dir, "dist")
        if os.path.isdir(dist_src_dir):
            os.makedirs(dist_www_dir, exist_ok=True)
            for fname in os.listdir(dist_src_dir):
                if fname.endswith(".js"):
                    src = os.path.join(dist_src_dir, fname)
                    dst = os.path.join(dist_www_dir, fname)
                    if not os.path.exists(dst) or os.path.getmtime(src) > os.path.getmtime(dst):
                        shutil.copy2(src, dst)
                        cards.append(f"dist/{fname}")
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
    async def async_register_surplus_device(call) -> None:
        """Register a device for surplus control."""
        from .devices.base import SwitchDevice
        device_id = call.data.get("device_id")
        entity_id = call.data.get("entity_id")
        name = call.data.get("name", device_id)
        priority = call.data.get("priority", 5)
        rated_power = call.data.get("rated_power", 1000)
        power_entity = call.data.get("power_entity_id")

        device = SwitchDevice(
            hass=hass,
            device_id=device_id,
            name=name,
            rated_power=rated_power,
            priority=priority,
            entity_id=entity_id,
            power_entity_id=power_entity,
        )
        coordinator._surplus_controller.register_device(device)
        _LOGGER.info("Registered surplus device: %s (priority %d)", name, priority)

    hass.services.async_register(
        DOMAIN,
        "register_surplus_device",
        async_register_surplus_device,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Required("entity_id"): cv.string,
            vol.Optional("name"): cv.string,
            vol.Optional("priority", default=5): vol.All(int, vol.Range(min=1, max=10)),
            vol.Optional("rated_power", default=1000): vol.Coerce(float),
            vol.Optional("power_entity_id"): cv.string,
        }),
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
        except (ValueError, TypeError):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_deadline_format",
                translation_placeholders={"deadline": str(deadline_str)},
            )

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

    _LOGGER.debug("Phase services registered: register_surplus_device, schedule_appliance")

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
        unrouted: list[str] = []
        for key in tunable_keys:
            value = options[key]
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

        _LOGGER.debug(
            "set_option wrote %d key(s) to entry %s "
            "(structural=%s tunable=%s unrouted=%s reload=%s)",
            len(options), target_entry.entry_id,
            structural_keys, tunable_keys, unrouted,
            bool(direct_keys),
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
        if requested and len(sem_entries) > 1:
            for e in sem_entries:
                if e.entry_id == requested:
                    target = e
                    break
        coordinator = getattr(target, "runtime_data", None)
        if coordinator is None:
            _LOGGER.warning("reset_sign_detection: no coordinator on entry %s", target.entry_id)
            return
        reader = getattr(coordinator, "_sensor_reader", None)
        if reader is not None:
            reader.reset_sign_state()
        storage = getattr(coordinator, "_storage", None)
        if storage is not None:
            storage.set_sign_state({})
            await storage.async_save_energy_delayed()
        # A re-learn must start clean: drop any prior one-tap user flip
        # (#461) so the freshly-learned sign isn't silently re-inverted on
        # top. Only touches the entry — and reloads — when a flip was
        # actually set, so the common reset path stays reload-free.
        if bool((target.options or {}).get("grid_sign_user_flip", False)):
            cleared = {**(target.options or {}), "grid_sign_user_flip": False}
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
        if requested and len(sem_entries) > 1:
            for e in sem_entries:
                if e.entry_id == requested:
                    target = e
                    break
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
        "battery_assist_floor_soc", "battery_minimum_soc", "battery_resume_soc",
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
        "critical_device_protection", "maximum_grid_import",
    }
    _DIAGNOSE_LOAD_MGMT_STATE = {
        "load_management_status", "load_management_recommendation",
        "loads_currently_shed", "controllable_devices_count",
        "consecutive_peak_15min", "monthly_consecutive_peak",
        "current_vs_peak_percentage", "available_load_reduction",
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
        "observer_mode", "update_interval", "power_delta",
        "current_delta", "soc_delta", "minimum_solar_power",
    }
    _DIAGNOSE_ADVANCED_STATE = {
        "observer_mode", "update_interval", "power_delta",
        "current_delta", "soc_delta", "minimum_solar_power",
        "last_update", "delta_triggered",
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
