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
from homeassistant.core import HomeAssistant, callback
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, issue_registry as ir
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

    # Fold the removed ev_limit_surplus switch (#235) into the Max ceiling (#245).
    # Idempotent; only acts while the legacy key is present.
    _migrate_limit_surplus_to_max(hass, entry)

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
    # Background. ``add_extra_js_url`` URLs include a content-hash
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

        for idx, charger_cfg in enumerate(ev_chargers_config):
            charger_id = charger_cfg.get("id", f"ev_charger_{idx}")
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

            # Also auto-fill sensor reader config from first charger
            if idx == 0:
                for key in ("ev_connected_sensor", "ev_charging_sensor", "ev_total_energy_sensor"):
                    if not full_config.get(key) and charger_cfg.get(key):
                        full_config[key] = charger_cfg[key]

            if not ev_power_entity or not (ev_charger_service or ev_current_entity):
                _LOGGER.debug("Charger %s missing power sensor or control method, skipping", charger_id)
                continue

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

            # Also register in load management for peak shedding
            if coordinator._load_manager:
                await coordinator._load_manager.register_ev_charger(
                    current_control_entity=ev_current_entity,
                    power_entity=ev_power_entity,
                    priority=ev_priority,
                    is_critical=False,
                    charger_service=ev_charger_service,
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
        if hp_relay1 and hp_relay2:
            from .devices.heat_pump_controller import HeatPumpController
            hp_device = HeatPumpController(
                hass=hass,
                device_id="heat_pump",
                name=full_config.get("heat_pump_name", "Heat Pump"),
                rated_power=float(full_config.get("heat_pump_rated_power", 2000)),
                priority=int(full_config.get("heat_pump_priority", 4)),
                relay1_entity_id=hp_relay1,
                relay2_entity_id=hp_relay2,
                climate_entity_id=full_config.get("heat_pump_climate_entity"),
                power_entity_id=full_config.get("heat_pump_power_sensor"),
                temperature_entity_id=full_config.get("heat_pump_temperature_sensor"),
                boost_offset=float(full_config.get("heat_pump_boost_offset", 2.0)),
                max_setpoint=float(full_config.get("heat_pump_max_setpoint", 55.0)),
                force_on_threshold=float(full_config.get("heat_pump_force_on_threshold", 5000)),
            )
            coordinator._surplus_controller.register_device(hp_device)
            _LOGGER.info(
                "Heat pump registered as SG-Ready device "
                "(priority %d, relay1=%s, relay2=%s)",
                hp_device.priority, hp_relay1, hp_relay2,
            )
        else:
            _LOGGER.debug("Heat pump not configured (no relay entities)")

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
    (``_skip_options_reload`` holds that snapshot), and is consumed once. A
    bare boolean used to leak — a stale flag from an earlier stepper could
    swallow a later options-FLOW save (e.g. ``vehicle_soc_entity``), which then
    only took effect after a full restart (#245 review #1). Comparing against
    the snapshot makes a flow change (different options) always reload.
    """
    coordinator = entry.runtime_data if hasattr(entry, "runtime_data") else None
    snapshot = getattr(coordinator, "_skip_options_reload", None) if coordinator else None
    if coordinator is not None:
        coordinator._skip_options_reload = None  # always consume — no leak
    if isinstance(snapshot, dict) and dict(entry.options) == snapshot:
        _LOGGER.debug("Options update from runtime tweak — skipping reload")
        return

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

        # Load semLocalize via add_extra_js_url — must be available before cards
        add_extra_js_url(hass, localize_url)

        # Legacy base URLs to clean up (migrated to single Lit bundle)
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
                    "  - url: %s\n    type: module",
                    cards_bundle_url, f"{static_path}/card/sem-system-diagram-card.js?v={asset_v['diagram']}",
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
