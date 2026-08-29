"""Solar forecast reader for Solar Energy Management.

Reads forecast data from existing HA integrations:
- Solcast PV Solar (HACS) — sensor.solcast_pv_forecast_*
- Forecast.Solar (built-in) — sensor.energy_production_*
- Open-Meteo Solar Forecast (HACS, #687) — same sensor scheme as
  Forecast.Solar under platform ``open_meteo_solar_forecast``
- Custom sensors via configuration

Provides remaining-today and tomorrow forecasts for:
- Charging planning (enough solar to skip night charging?)
- Device scheduling (when will surplus be available?)
- PV performance analysis (actual vs expected)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant
from homeassistant.const import STATE_UNKNOWN, STATE_UNAVAILABLE
from homeassistant.util import dt as dt_util

from .units import power_state_to_watts, power_unit_scale

_LOGGER = logging.getLogger(__name__)

# Known forecast entity patterns
SOLCAST_ENTITIES = {
    "forecast_today": "sensor.solcast_pv_forecast_forecast_today",
    "forecast_tomorrow": "sensor.solcast_pv_forecast_forecast_tomorrow",
    "forecast_remaining": "sensor.solcast_pv_forecast_forecast_remaining_today",
    "power_now": "sensor.solcast_pv_forecast_power_now",
    "power_next_hour": "sensor.solcast_pv_forecast_power_next_hour",
    "peak_power_today": "sensor.solcast_pv_forecast_peak_forecast_today",
    "peak_time_today": "sensor.solcast_pv_forecast_peak_time_today",
}

FORECAST_SOLAR_ENTITIES = {
    "forecast_today": "sensor.energy_production_today",
    "forecast_tomorrow": "sensor.energy_production_tomorrow",
    "power_now": "sensor.energy_production_now",
}

# (#562) Entity IDs are LOCALIZED — a German install names the Solcast
# sensor ``sensor.solcast_pv_forecast_forecast_heute``, so the hardcoded
# English entity_ids above never match. The entity registry's
# ``unique_id`` is language-independent, so resolution goes registry
# first (platform + unique_id), hardcoded entity_id second (fallback for
# renamed/odd registries). Unique IDs verified against the upstream
# sources: BJReplay/ha-solcast-solar const.py and HA core
# forecast_solar/sensor.py (``{entry_id}_{key}``).
SOLCAST_PLATFORM = "solcast_solar"
# Known limitation: multi-rooftop Solcast installs also emit PER-SITE
# sensors with prefixed unique_ids ("<site>_total_kwh_forecast_today").
# Those are deliberately NOT matched — a single site's value would be
# wrong for the fleet. If a user disabled the fleet-total sensors and
# kept only per-site ones, detection falls back to the hardcoded
# entity_ids (and may fail); re-enabling the totals is the fix.
SOLCAST_UNIQUE_IDS = {
    "forecast_today": ("total_kwh_forecast_today",),
    "forecast_tomorrow": ("total_kwh_forecast_tomorrow",),
    # unique_id kept its pre-rename value upstream; match both to be safe
    "forecast_remaining": ("get_remaining_today", "forecast_remaining_today"),
    "power_now": ("power_now",),
    "power_next_hour": ("power_next_hour",),
    "peak_power_today": ("peak_w_today",),
    "peak_time_today": ("peak_w_time_today",),
}
FORECAST_SOLAR_PLATFORM = "forecast_solar"
FORECAST_SOLAR_UNIQUE_SUFFIXES = {
    "forecast_today": "_energy_production_today",
    "forecast_tomorrow": "_energy_production_tomorrow",
    "forecast_remaining": "_energy_production_today_remaining",
    "power_now": "_power_production_now",
}
# (#687) Open-Meteo Solar Forecast (rany2/ha-open-meteo-solar-forecast)
# deliberately mirrors core Forecast.Solar: unique_id = ``{entry_id}_{key}``
# with the SAME sensor keys (verified against its sensor.py), so the
# suffix map above is reused verbatim. Only the platform differs. Its
# entity_ids are device-prefixed (``sensor.<device>_energy_production_
# today``), so there is NO reliable hardcoded entity fallback — the
# registry path is the only detection route (an empty fallback dict is
# passed to _locate_integration).
OPEN_METEO_SOLAR_PLATFORM = "open_meteo_solar_forecast"

# (#819) The ladder below is an ORDER, not a preference. Someone running
# several forecast integrations side by side to compare accuracy could
# only reach the second one by deactivating the first — and the setup
# guide already described an override that did not exist for solar.
# ``solar_forecast_source`` names one of these; anything else (unset,
# "auto", a stale value) leaves the ladder exactly as it was.
#: (#819) How many detection attempts a chosen source gets to appear before
#: SEM says anything alarming about it. Detection runs at coordinator
#: construction and after a config reload, either of which can precede a
#: slower forecast integration registering its entities — so the FIRST miss
#: is the expected case, not the exceptional one, and ``should_retry_preference``
#: already exists to resolve it. At the 10 s default cycle this is about a
#: minute of quiet before we conclude anything.
PREFERRED_GRACE_CYCLES: int = 6

FORECAST_SOURCES: dict = {
    "solcast": (SOLCAST_PLATFORM, "SOLCAST_ENTITIES"),
    "forecast_solar": (FORECAST_SOLAR_PLATFORM, "FORECAST_SOLAR_ENTITIES"),
    # Open-Meteo is registry-only: device-prefixed entity_ids, so there
    # is no hardcoded fallback map to hand the locator (#687).
    "open_meteo": (OPEN_METEO_SOLAR_PLATFORM, None),
}


@dataclass
class ForecastData:
    """Solar forecast data."""
    # Energy forecasts (kWh)
    forecast_today_kwh: float = 0.0
    forecast_tomorrow_kwh: float = 0.0
    forecast_remaining_today_kwh: float = 0.0

    # Power forecasts (W)
    power_now_w: float = 0.0
    power_next_hour_w: float = 0.0
    peak_power_today_w: float = 0.0
    peak_time_today: Optional[str] = None

    # Source info
    source: str = "none"
    available: bool = False
    # (#819) Which forecast integrations exist on this install, so the
    # picker can offer what is actually there instead of all four.
    sources_available: list = field(default_factory=list)
    last_update: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "forecast_today_kwh": round(self.forecast_today_kwh, 2),
            "forecast_tomorrow_kwh": round(self.forecast_tomorrow_kwh, 2),
            "forecast_remaining_today_kwh": round(self.forecast_remaining_today_kwh, 2),
            # (#575) forecast_power_now_w restored — consumed by the "Forecast vs
            # Actual" chart. forecast_power_next_hour_w stays removed (orphan).
            "forecast_power_now_w": round(self.power_now_w, 0),
            "forecast_peak_power_today_w": round(self.peak_power_today_w, 0),
            "forecast_peak_time_today": self.peak_time_today,
            "forecast_source": self.source,
            "forecast_available": self.available,
        }


class ForecastReader:
    """Reads solar production forecasts from HA integrations."""

    def __init__(
        self,
        hass: HomeAssistant,
        custom_entities: Optional[Dict[str, str]] = None,
        preferred_source: Optional[str] = None,
    ):
        self.hass = hass
        self._custom_entities = custom_entities or {}
        # (#819) ``auto``/None/unknown all mean "walk the ladder".
        _pref = (preferred_source or "").strip().lower()
        # (#819) Keep the raw request. The normalised one drives detection;
        # this one is what the user is TOLD, so a name SEM does not know is
        # visible as a rejected request instead of vanishing.
        self._requested_raw = _pref
        self._preferred_source = _pref if _pref in FORECAST_SOURCES else None
        # (#819) Set when a chosen source was asked for and not found.
        # Rides along in the detection path so "why is it reading
        # Solcast when I chose Open-Meteo" is answerable from
        # diagnostics alone.
        self._preferred_missing: Optional[str] = None
        # (#819) Consecutive detection attempts in which the chosen source
        # was not found. Survives across detect_source() runs — unlike
        # _preferred_missing, which is per-run — because that is the only
        # way to tell "not loaded YET" from "not there".
        self._preferred_miss_streak: int = 0
        self._preferred_warned: bool = False
        self.__detection_path: Optional[str] = None
        self._source: Optional[str] = None
        self._entities: Dict[str, str] = {}
        # (#838) Forecast.Solar / Open-Meteo model a multi-string array as
        # one config entry PER PLANE, each with its own energy_production_*
        # sensor. ``_entities`` keeps the representative (first) entity per
        # role — used for detection, validity checks and peak-time parsing
        # — while ``_entity_groups`` holds ALL of a role's plane entities so
        # the fleet forecast is their SUM, not a single string. Empty (→ read
        # the single ``_entities`` value) for single-plane, Solcast (already a
        # total), custom and hardcoded-fallback installs. Built in the SAME
        # scan as the primary, so the two cannot drift.
        self._entity_groups: Dict[str, list] = {}
        self._last_data = ForecastData()

        # (HA Repairs, 2026-06-06) Log-once + Repair gating. Pre-fix
        # ``_detect_source`` logged INFO every cycle (~10 s) when no
        # integration was found — spam. Now: log INFO once on the
        # first detection failure, file a Repair issue after the
        # threshold so the user has something actionable in
        # Settings → System → Repairs, and clear both on detection
        # success.
        import time as _time
        self._no_forecast_logged: bool = False
        self._no_forecast_since_mono: Optional[float] = None
        self._no_forecast_repair_raised: bool = False
        self._mono_time = _time.monotonic
        # (#562) 60 s cache for entity-registry scans: {platform: (mono_ts, entities)}
        self._registry_cache: Dict[str, tuple] = {}

        # #434 — telemetry surface mirroring classifier_path /
        # dampening_path. Each public method sets the corresponding
        # ``*_path`` string so users can see which branch produced
        # the current forecast / recommendation.
        self._last_source_detection_path: str = "uninitialized"
        self._last_read_path: str = "uninitialized"
        self._last_recommendation_path: str = "uninitialized"
        self._last_unit_conversion_count: int = 0  # kW→W conversions (by declared unit)

    @property
    def forecast_data(self) -> ForecastData:
        return self._last_data

    @property
    def source(self) -> Optional[str]:
        return self._source

    def _clear_no_forecast_repair(self) -> None:
        """Reset detection-failure state + drop the Repair issue when
        a forecast integration appears after a previous absence."""
        self._no_forecast_logged = False
        self._no_forecast_since_mono = None
        if self._no_forecast_repair_raised:
            try:
                from . import repair_issues as _ri
                _ri.clear_no_forecast_integration(self.hass)
            except Exception as e:  # noqa: BLE001
                _LOGGER.debug("Could not clear no_forecast Repair: %s", e)
            self._no_forecast_repair_raised = False

    def _registry_entity_groups(self, platform: str) -> Dict[str, list]:
        """All matching entities per role for a platform (registry scan).

        (#562) Entity IDs are localized per HA language; the registry
        ``unique_id`` is not, so resolution keys off the unique_id.

        (#838) Forecast.Solar and Open-Meteo model a multi-string array
        as one CONFIG ENTRY PER PLANE — each plane emits its own
        ``energy_production_*`` sensor (unique_id ``{entry_id}_{key}``,
        entity_id disambiguated with ``_2``/``_3``). Every plane's
        unique_id ends in the SAME suffix, so a role maps to a LIST and
        the fleet forecast is their SUM, not any single plane. Solcast
        matches on an exact unique_id that is ALREADY the site/account
        total (per-site Solcast sensors are deliberately not matched —
        see SOLCAST_UNIQUE_IDS), so its roles stay single-element.

        Returns ``{role: [entity_id, ...]}``; empty dict when the
        registry is unavailable (tests, early boot) or nothing matches.

        Results are cached for 60 s — the upgrade peek in
        ``read_forecast`` runs every coordinator cycle (~10 s) while a
        lower-priority source is active; a full registry scan per cycle
        would be wasteful on large installs.
        """
        cached = self._registry_cache.get(platform)
        if cached is not None and (self._mono_time() - cached[0]) < 60:
            return cached[1]
        try:
            from homeassistant.helpers import entity_registry as er
            registry = er.async_get(self.hass)
            entries = list(registry.entities.values())
        except Exception:  # noqa: BLE001 — registry absent/mocked; may be
            # transient at boot, so this path is deliberately NOT cached
            return {}

        resolved: Dict[str, list] = {}
        for entry in entries:
            try:
                if entry.platform != platform or entry.disabled_by is not None:
                    continue
                unique_id = str(entry.unique_id)
                entity_id = str(entry.entity_id)
            except Exception:  # noqa: BLE001
                continue
            if platform == SOLCAST_PLATFORM:
                for role, keys in SOLCAST_UNIQUE_IDS.items():
                    # Exact-match total sensor: keep the first, never sum.
                    if unique_id in keys and role not in resolved:
                        resolved[role] = [entity_id]
            else:
                for role, suffix in FORECAST_SOLAR_UNIQUE_SUFFIXES.items():
                    # Suffix-match per-plane sensor: collect EVERY plane so
                    # the read path can sum them (#838).
                    if unique_id.endswith(suffix) and entity_id not in resolved.get(role, ()):
                        resolved.setdefault(role, []).append(entity_id)
        self._registry_cache[platform] = (self._mono_time(), resolved)
        return resolved

    def _registry_entities(self, platform: str) -> Dict[str, str]:
        """Representative (first) entity per role — the one used for source
        detection, validity checks and peak-time parsing.

        The full per-role plane set (which the fleet forecast SUMS across)
        lives in ``_registry_entity_groups`` (#838); this returns each
        role's first entity, which is byte-for-byte the pre-#838 result.
        """
        return {
            role: ents[0]
            for role, ents in self._registry_entity_groups(platform).items()
            if ents
        }

    def _entity_state_ok(self, entity_id: Optional[str]) -> bool:
        """True when an entity exists and holds a usable (non-unknown,
        non-unavailable) state."""
        if not entity_id:
            return False
        state = self.hass.states.get(entity_id)
        return bool(
            state and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE, None)
        )

    def _locate_integration(
        self, platform: str, fallback: Dict[str, str]
    ) -> Optional[Dict[str, str]]:
        """Find an integration's entities (registry first, hardcoded
        entity_ids second) and confirm ``forecast_today`` is usable.

        (#838) For a multi-plane source the role is usable if ANY plane's
        ``forecast_today`` is available — so one dark string does not hide
        an otherwise-working array (detection used to key off the first
        plane alone, which would drop the whole forecast). The returned
        dict is still the representative (first) entity per role; the full
        plane set is captured separately in ``_entity_groups``.
        """
        groups = self._registry_entity_groups(platform)
        if any(self._entity_state_ok(e) for e in groups.get("forecast_today", ())):
            return {role: ents[0] for role, ents in groups.items() if ents}
        if self._entity_state_ok(fallback.get("forecast_today")):
            return fallback
        return None

    def _capture_entity_groups(self, platform: str) -> None:
        """(#838) Record the active source's full per-role plane entities so
        a multi-string Forecast.Solar / Open-Meteo install is SUMMED rather
        than read as one plane.

        Only adopt the registry groups when the ACTIVE entities are the
        registry ones: if detection fell back to the hardcoded entity_ids
        (registry primary unusable), there are no discoverable sibling
        planes to sum and the groups must stay empty so the read path keeps
        using the single fallback entity. Matching on the ``forecast_today``
        primary guarantees the groups and ``_entities`` describe the same
        source — they cannot drift.
        """
        groups = self._registry_entity_groups(platform)
        primary = groups.get("forecast_today") or []
        if primary and self._entities.get("forecast_today") == primary[0]:
            self._entity_groups = groups
        else:
            self._entity_groups = {}

    def set_preferred_source(self, name: Optional[str]) -> None:
        """(#819) Apply a changed forecast-source choice WITHOUT a reload.

        #637's guard is explicit that a key consumed only at
        construction must stay on the reload path, because live-applying
        it would be the #462 lie — the setting looks applied and nothing
        moves. Rather than reload the whole entry for a dropdown, the
        coordinator re-applies the choice each cycle through here, and a
        real change drops the cached source so the next read re-detects.
        """
        norm = (name or "").strip().lower()
        norm = norm if norm in FORECAST_SOURCES else None
        self._requested_raw = (name or "").strip().lower()
        if norm == self._preferred_source:
            return                      # idempotent: no cache churn
        self._preferred_source = norm
        self._source = None
        self._entities = {}
        self._entity_groups = {}
        _LOGGER.info("Solar forecast source changed to %s — re-detecting",
                     norm or "auto")

    def available_sources(self) -> list:
        """(#819) Which forecast integrations are installed RIGHT NOW.

        The picker needs this: offering all four regardless lets someone
        choose a source that is not there, which then silently falls back
        to auto — a setting that looks like it did nothing. A read-only
        registry probe; it never re-points the reader.
        """
        found = []
        for name, (platform, entity_map) in FORECAST_SOURCES.items():
            if self._locate_integration(platform, globals().get(entity_map) or {}):
                found.append(name)
        return found

    @property
    def _last_source_detection_path(self) -> Optional[str]:
        """(#434) Which branch decided the source — and (#819) whether a
        chosen one was missing when it did. A property so the ladder
        branches keep assigning a plain name and the miss is folded in
        at one place."""
        path = self.__detection_path
        if self._preferred_missing and path:
            return f"{self._preferred_missing}_missing_then_{path}"
        return path

    @_last_source_detection_path.setter
    def _last_source_detection_path(self, value: Optional[str]) -> None:
        self.__detection_path = value

    @property
    def requested_source(self) -> Optional[str]:
        """What the user asked for, whether or not it could be used.

        (#819) Deliberately NOT normalised away: a stored name SEM does not
        recognise is a real misconfiguration and the user needs to see that it
        was asked for and rejected, rather than watching SEM behave as though
        nothing was set.
        """
        raw = (self._requested_raw or "").strip().lower()
        # "auto" is the absence of a request, not a request for a source
        # named auto — reporting it would put a non-source in a field the
        # card renders as one.
        if not raw or raw == "auto":
            return None
        return raw

    @property
    def honoured(self) -> bool:
        """Whether the requested source is the one actually in use.

        True when nothing was requested — nothing was asked for, so nothing
        was denied, and a 'not honoured' flag on every auto install would be
        noise that teaches people to ignore it.
        """
        want = self.requested_source
        if want is None or want == "auto":
            return True
        if self._preferred_missing:
            return False
        return self._source == want

    @property
    def should_retry_preference(self) -> bool:
        """Is a chosen source still waiting to be found?

        (#819) ``detect_source`` runs at coordinator construction, which can be
        before a slower forecast integration has registered its entities — and
        the fallback it picks was then cached forever, because ``read_forecast``
        only re-detects when the CURRENT source's entities vanish. A user's
        choice could therefore lose a startup race once and never get another
        chance, which reads as "it always goes back to Solcast".

        Cheap to answer and self-limiting: it stops the moment the preference
        is honoured, so a correctly-resolved install never re-detects.

        The condition is simply "what was asked for is not what is in use".
        A first version keyed on ``_preferred_missing`` alone and did NOT fix
        the live case, because that flag is only set when the preferred BRANCH
        runs and finds nothing — it says nothing about a preference that never
        got that far. Asking the honest question covers both.
        """
        return not self.honoured

    def detect_source(self) -> Optional[str]:
        """Auto-detect available forecast integration.

        Records the branch on
        ``self._last_source_detection_path`` (#434):
        ``custom`` / ``solcast`` / ``forecast_solar`` / ``none_available``.
        """
        self._preferred_missing = None      # (#819) fresh run

        # Check custom entities first.
        # (#819) NOTE: nothing constructs the reader with these — the
        # coordinator passes custom_entities=None — so this branch is
        # currently unreachable. It is the seam a 'name your own
        # forecast sensor' feature would use, and it needs a MAP of
        # entities (today / tomorrow / power now), not one sensor, which
        # is why a single entity picker was never enough to wire it.
        # Kept deliberately, and documented as unsupported in
        # SETUP_GUIDE rather than half-claimed.
        if self._custom_entities:
            self._entities = self._custom_entities
            self._entity_groups = {}   # (#838) custom map is single-entity per role
            self._source = "custom"
            self._last_source_detection_path = "custom"
            _LOGGER.info("Using custom forecast entities")
            self._clear_no_forecast_repair()
            return self._source

        # (#819) A chosen source outranks the ladder — but only when it
        # is actually there. A stale preference (integration removed)
        # must not take forecasting down with it, so a miss falls
        # through to the ladder and SAYS SO in the detection path:
        # silent substitution is the failure mode this codebase keeps
        # relearning (#741/#758/#774).
        if self._preferred_source:
            platform, entity_map = FORECAST_SOURCES[self._preferred_source]
            entities = self._locate_integration(
                platform, globals().get(entity_map) or {},
            )
            if entities:
                self._entities = entities
                self._capture_entity_groups(platform)   # (#838)
                self._source = self._preferred_source
                self._last_source_detection_path = (
                    f"preferred_{self._preferred_source}")
                if self._preferred_miss_streak:
                    # Say so explicitly. The diagnostics buffer keeps the
                    # alarm and would otherwise lose the resolution, which is
                    # exactly how the reporter ended up looking at a warning
                    # about an integration that was working (#819).
                    _LOGGER.info(
                        "Chosen solar forecast source %s is available now "
                        "(after %d attempt(s)) — using it",
                        self._preferred_source, self._preferred_miss_streak,
                    )
                else:
                    _LOGGER.info(
                        "Using the chosen solar forecast source: %s",
                        self._preferred_source,
                    )
                self._preferred_miss_streak = 0
                self._preferred_warned = False
                self._clear_no_forecast_repair()
                return self._source
            self._preferred_miss_streak += 1
            if self._preferred_miss_streak < PREFERRED_GRACE_CYCLES:
                # The expected case: detection outran the integration's
                # entity registration. Visible to us, silent to the user.
                _LOGGER.debug(
                    "Chosen solar forecast source %s not visible yet "
                    "(attempt %d/%d) — using auto-detection meanwhile",
                    self._preferred_source, self._preferred_miss_streak,
                    PREFERRED_GRACE_CYCLES,
                )
            elif not self._preferred_warned:
                # Once, not per cycle: a 10 s loop would write 8,640 lines a
                # day and teach people to ignore the log (#762).
                self._preferred_warned = True
                _LOGGER.warning(
                    "Chosen solar forecast source %s has not appeared after "
                    "%d attempts — check that its integration is installed "
                    "and loading. Using auto-detection meanwhile.",
                    self._preferred_source, self._preferred_miss_streak,
                )
            self._preferred_missing = self._preferred_source

        # Check Solcast
        entities = self._locate_integration(SOLCAST_PLATFORM, SOLCAST_ENTITIES)
        if entities:
            self._entities = entities
            self._capture_entity_groups(SOLCAST_PLATFORM)   # (#838)
            self._source = "solcast"
            self._last_source_detection_path = "solcast"
            _LOGGER.info("Detected Solcast PV Solar integration")
            self._clear_no_forecast_repair()
            return self._source

        # Check Forecast.Solar
        entities = self._locate_integration(
            FORECAST_SOLAR_PLATFORM, FORECAST_SOLAR_ENTITIES
        )
        if entities:
            self._entities = entities
            self._capture_entity_groups(FORECAST_SOLAR_PLATFORM)   # (#838)
            self._source = "forecast_solar"
            self._last_source_detection_path = "forecast_solar"
            _LOGGER.info("Detected Forecast.Solar integration")
            self._clear_no_forecast_repair()
            return self._source

        # Check Open-Meteo Solar Forecast (#687) — registry-only: its
        # entity_ids are device-prefixed, so no hardcoded fallback exists.
        entities = self._locate_integration(OPEN_METEO_SOLAR_PLATFORM, {})
        if entities:
            self._entities = entities
            self._capture_entity_groups(OPEN_METEO_SOLAR_PLATFORM)   # (#838)
            self._source = "open_meteo"
            self._last_source_detection_path = "open_meteo"
            _LOGGER.info("Detected Open-Meteo Solar Forecast integration")
            self._clear_no_forecast_repair()
            return self._source

        self._last_source_detection_path = "none_available"
        # Log once per outage; subsequent cycles stay silent.
        if not self._no_forecast_logged:
            _LOGGER.info("No solar forecast integration detected")
            self._no_forecast_logged = True
        # Track the first detection-failure timestamp; escalate to a
        # Repair issue if still missing after 1 hour (gives a
        # legitimate first-boot install window before complaining).
        now_mono = self._mono_time()
        if self._no_forecast_since_mono is None:
            self._no_forecast_since_mono = now_mono
        elif (
            not self._no_forecast_repair_raised
            and (now_mono - self._no_forecast_since_mono) >= 3600
        ):
            try:
                from . import repair_issues as _ri
                _ri.raise_no_forecast_integration(self.hass)
                self._no_forecast_repair_raised = True
            except Exception as e:  # noqa: BLE001
                _LOGGER.debug("Could not raise no_forecast Repair: %s", e)
        return None

    def read_forecast(self) -> ForecastData:
        """Read current forecast data from detected source.

        Caches the detected source — only re-detects if source becomes
        unavailable (#26).

        Records the read path on ``self._last_read_path`` (#434):
        ``cold_detect`` (first call) / ``cached_source_valid`` /
        ``cached_source_lost_redetected`` / ``upgraded_to_solcast`` /
        ``no_source_after_detect`` / ``read_complete``.
        """
        # Reset unit-conversion counter per read so we can see how
        # many magic-number kW→W bumps fired this cycle.
        self._last_unit_conversion_count = 0

        if not self._source:
            self.detect_source()
            self._last_read_path = "cold_detect"
        elif self._source != "custom":
            # (#562) Source priority is Solcast > Forecast.Solar, but the
            # cache used to be sticky: if Solcast loaded after SEM's first
            # detection (integration start order is arbitrary), SEM latched
            # onto Forecast.Solar until the next restart. Upgrade as soon
            # as the preferred source's entity becomes available.
            upgraded = False
            # (#819) An upgrade is only an upgrade if nobody asked for
            # something else. #562 added this for installs that never chose —
            # Solcast loading after SEM's first detection used to leave the
            # cache latched on a lesser source until a restart. It predates the
            # user preference and never learned about it, so it handed an
            # explicit choice straight back to Solcast on the very next read:
            # the choice applied, then reverted a cycle later, forever. That is
            # the whole of the reported bug.
            if self._source != "solcast" and not self._preferred_source:
                solcast_entities = self._locate_integration(
                    SOLCAST_PLATFORM, SOLCAST_ENTITIES
                )
                if solcast_entities:
                    _LOGGER.info(
                        "Solcast PV Solar became available — upgrading "
                        "forecast source from %s to solcast",
                        self._source,
                    )
                    self._entities = solcast_entities
                    self._capture_entity_groups(SOLCAST_PLATFORM)   # (#838)
                    self._source = "solcast"
                    self._last_source_detection_path = "solcast"
                    self._last_read_path = "upgraded_to_solcast"
                    upgraded = True
            if not upgraded and self.should_retry_preference:
                # (#819) The chosen source was missing when we last looked.
                # Look again — it may simply have been slower to load than SEM
                # was to ask. Ends as soon as it is found.
                self._source = None
                self.detect_source()
                self._last_read_path = "preference_retried"
                upgraded = True
            if not upgraded:
                # Verify cached source is still valid (entity may have
                # disappeared). (#838) A multi-plane source stays valid while
                # ANY plane is available — matching plane-aware detection, so
                # a dark representative plane does not force a redetect churn
                # every cycle while siblings keep producing.
                group = self._entity_groups.get("forecast_today")
                candidates = group or [self._entities.get("forecast_today")]
                if not any(candidates):
                    # No forecast_today entity at all → nothing to re-validate.
                    self._last_read_path = "cached_source_valid"
                elif any(self._entity_state_ok(e) for e in candidates):
                    self._last_read_path = "cached_source_valid"
                else:
                    self._source = None
                    self.detect_source()
                    self._last_read_path = "cached_source_lost_redetected"
        else:
            self._last_read_path = "cached_source_valid"

        if not self._source:
            self._last_read_path = "no_source_after_detect"
            return ForecastData()

        data = ForecastData(
            source=self._source,
            available=True,
            # (#839) AWARE, not naive. The battery scheduler computes
            # `dt_util.now() - last_update`, and dt_util.now() is
            # timezone-aware — a naive stamp here raised TypeError on
            # every evaluation and the scheduler never ran once.
            last_update=dt_util.now(),
            # (#819) Registry probe behind the same 60 s cache the
            # locator uses (#562), so this is three dict lookups on a
            # warm cache rather than three scans per cycle.
            sources_available=self.available_sources(),
        )

        # Read forecast today (summed across planes for a multi-string
        # Forecast.Solar / Open-Meteo install, single otherwise — #838)
        data.forecast_today_kwh = self._read_role_energy("forecast_today", 0.0)

        # Read forecast tomorrow
        data.forecast_tomorrow_kwh = self._read_role_energy("forecast_tomorrow", 0.0)

        # Read remaining today
        remaining_entity = self._entities.get("forecast_remaining")
        if remaining_entity:
            data.forecast_remaining_today_kwh = self._read_role_energy(
                "forecast_remaining", 0.0
            )
        else:
            # Estimate remaining from today total and current production
            # This is a rough estimate — actual remaining depends on time of day
            data.forecast_remaining_today_kwh = max(
                0, data.forecast_today_kwh * self._remaining_day_fraction()
            )

        # Read power now / next hour / peak — normalized to Watts off the
        # sensor's declared unit (see _read_power_w). power_now is summed
        # across planes for a multi-string install (#838); next-hour and
        # peak are Solcast-only (single-element groups) so they read the
        # single entity unchanged.
        data.power_now_w = self._read_role_power_w("power_now", 0.0)
        data.power_next_hour_w = self._read_role_power_w("power_next_hour", 0.0)
        # (#841) NOT _read_role_power_w: that sums, and peaks do not add.
        data.peak_power_today_w = self._read_role_peak_w("peak_power_today", 0.0)

        # Peak time — Solcast exposes a full ISO datetime; coordinator
        # and dashboard consumers expect "HH:MM" local time.
        peak_time_entity = self._entities.get("peak_time_today")
        if peak_time_entity:
            state = self.hass.states.get(peak_time_entity)
            if state and state.state not in ("unknown", "unavailable"):
                raw = state.state
                try:
                    parsed = dt_util.parse_datetime(raw)
                    if parsed is not None:
                        data.peak_time_today = dt_util.as_local(parsed).strftime("%H:%M")
                    else:
                        data.peak_time_today = raw
                except (ValueError, TypeError):
                    data.peak_time_today = raw

        self._last_data = data
        self._last_read_path = "read_complete"
        return data

    def _read_role_energy(self, role: str, default: float) -> float:
        """Read an energy role, summing across planes when the source
        exposes more than one (#838).

        A multi-string Forecast.Solar / Open-Meteo install registers one
        ``energy_production_*`` sensor per plane; the fleet forecast is
        their sum. For every other source the group is single (or empty),
        so this reads the single ``_entities`` value exactly as before.
        """
        group = self._entity_groups.get(role)
        if group and len(group) > 1:
            return self._sum_floats(group, default)
        return self._read_float(self._entities.get(role), default)

    def _read_role_power_w(self, role: str, default: float) -> float:
        """Read a power role in Watts, summing across planes when the
        source exposes more than one (#838). Single otherwise."""
        group = self._entity_groups.get(role)
        if group and len(group) > 1:
            return self._sum_power_w(group, default)
        return self._read_power_w(self._entities.get(role), default)

    @staticmethod
    def _role_ids(groups: Dict[str, list], fallback: Dict[str, str],
                  role: str) -> list:
        """Registry group for a role, or the hardcoded fallback's single id
        (#822)."""
        found = groups.get(role) or []
        if found:
            return list(found)
        single = fallback.get(role)
        return [single] if single else []

    def peek_sources(self) -> Dict[str, Dict[str, float]]:
        """(#822) What EVERY installed forecast integration says right now.

        Read-only: it never re-points the reader, so the source in use is
        unaffected by being compared. Each entry is that source's own total —
        summed across its planes exactly as the active path sums them (#838),
        so a two-plane Forecast.Solar is compared as one roof and not as one
        of its planes.

        This exists because the obvious comparison is the wrong one. Two
        integrations disagreeing does NOT mean one forecasts badly: on the
        dev rig Solcast said 125.6 kWh, Forecast.Solar 47.2 and Open-Meteo
        20.0 for the same day — a 6x spread that turned out to be three
        DIFFERENT CONFIGURED ARRAYS (8 kWp against a 15 kW inverter against a
        cloud site), not three opinions about one roof. SEM cannot see how a
        third-party integration was configured, so it cannot normalise them
        and must not pretend to.

        What it CAN do is score each against what the roof actually produced,
        which is what the #778 ledger already does for the active source. A
        source configured for the wrong array simply scores badly and says
        so — no normalisation required, and the answer is measured rather
        than assumed.
        """
        out: Dict[str, Dict[str, float]] = {}
        for name, (platform, entity_map) in FORECAST_SOURCES.items():
            fallback = globals().get(entity_map) or {}
            if not self._locate_integration(platform, fallback):
                continue
            groups = self._registry_entity_groups(platform)
            today_ids = self._role_ids(groups, fallback, "forecast_today")
            today = self._sum_floats(today_ids, None)
            if today is None:
                continue
            entry = {"today_kwh": round(today, 3), "planes": len(today_ids)}
            tomorrow = self._sum_floats(
                self._role_ids(groups, fallback, "forecast_tomorrow"), None)
            if tomorrow is not None:
                entry["tomorrow_kwh"] = round(tomorrow, 3)
            out[name] = entry
        return out

    def plane_breakdown(self) -> list:
        """(#841) Today's forecast per PLANE, for the card.

        #838 made the TOTAL right. The total is what SEM plans on, but it is
        not what the owner recognises — they built the roof one string at a
        time and think of it that way. It is also the cheapest possible check
        on the total: a string reading zero, or one carrying the whole roof,
        is obvious in a list and invisible in a sum.

        Named from the entity's friendly name, because a plane's identity
        lives in the third-party integration's config entry and SEM only ever
        sees its entities.
        """
        group = self._entity_groups.get("forecast_today")
        ids = group if group else [self._entities.get("forecast_today")]
        out = []
        for entity_id in ids:
            if not entity_id:
                continue
            state = self.hass.states.get(entity_id)
            if not state:
                continue
            try:
                value = float(state.state)
            except (ValueError, TypeError):
                continue
            name = (state.attributes or {}).get("friendly_name") or entity_id
            for suffix in (" Energy production today",
                           " Estimated energy production - today"):
                if name.endswith(suffix):
                    name = name[: -len(suffix)]
                    break
            out.append({"entity_id": entity_id, "name": name,
                        "today_kwh": round(value, 3)})
        out.sort(key=lambda r: r["name"])
        return out

    def _read_role_peak_w(self, role: str, default: float) -> float:
        """Read a PEAK power role — the largest plane, never the sum (#841).

        #838 taught the reader to sum a multi-string roof, which is right for
        energies and right for instantaneous power: two arrays really do
        produce the sum of their watts at the same moment. A peak is different.
        An east-facing array and a west-facing one reach their maxima hours
        apart, so their peaks are never simultaneous, and adding them claims
        an output the roof cannot physically produce — an 8 kWp east plus
        8 kWp west install would report 16 kW against a true system peak
        nearer 9-10 kW.

        Note the direction. #838 corrected an UNDER-statement; this prevents an
        OVER-statement, which is the more dangerous of the two: anything
        sizing headroom, a shaving threshold or an export limit against this
        figure would be planning for a spike that never arrives.

        The largest plane under-states a co-planar split — two arrays at the
        same azimuth do peak together — but it is a number the system can
        actually reach.
        """
        group = self._entity_groups.get(role)
        candidates = group if group else [self._entities.get(role)]
        peaks = []
        for entity_id in candidates:
            if not entity_id:
                continue
            value = self._read_power_w(entity_id, None)
            if value is not None:
                peaks.append(value)
        return max(peaks) if peaks else default

    def _sum_floats(self, entity_ids: list, default: float) -> float:
        """Sum the numeric states of several entities (#838).

        Unavailable/non-numeric planes contribute nothing; if EVERY plane
        is unavailable the caller's default is returned, matching the
        single-entity ``_read_float`` contract. A partially-available
        multi-plane install therefore under-reports rather than reading 0
        — the pragmatic choice, since the plane sensors update together in
        practice.
        """
        total = 0.0
        any_available = False
        for entity_id in entity_ids:
            state = self.hass.states.get(entity_id)
            if state and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE, None):
                try:
                    total += float(state.state)
                    any_available = True
                except (ValueError, TypeError):
                    pass
        return total if any_available else default

    def _sum_power_w(self, entity_ids: list, default: float) -> float:
        """Sum several power sensors, each normalized to Watts off its
        declared unit (see _read_power_w), keeping the unit-conversion
        counter accurate across planes (#838)."""
        total = 0.0
        any_available = False
        for entity_id in entity_ids:
            state = self.hass.states.get(entity_id)
            if not state or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, None):
                continue
            try:
                float(state.state)
            except (ValueError, TypeError):
                continue
            if power_unit_scale(state) != 1.0:
                self._last_unit_conversion_count += 1
            total += power_state_to_watts(state, default=0.0)
            any_available = True
        return total if any_available else default

    def _read_float(self, entity_id: Optional[str], default: float) -> float:
        """Read a float value from a HA entity."""
        if not entity_id:
            return default
        state = self.hass.states.get(entity_id)
        if state and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE, None):
            try:
                return float(state.state)
            except (ValueError, TypeError):
                pass
        return default

    def _read_power_w(self, entity_id: Optional[str], default):
        """Read a forecast power sensor and normalize it to Watts.

        Solcast (``UnitOfPower.WATT``) and Forecast.Solar both publish their
        power sensors in Watts natively. SEM historically assumed Solcast was
        kW and multiplied any reading < 100 by 1000 (a magnitude heuristic).
        That silently inflated every genuine sub-100 W value — most visibly the
        near-zero dawn/dusk readings, which it blew up into ~80 kW spikes on the
        "Forecast vs Actual" chart (#575). Convert off the *declared* unit
        instead: only kW → ×1000; W (or a missing/other unit) passes through
        unchanged, so a real 80 W dawn reading stays 80 W.
        """
        if not entity_id:
            return default
        state = self.hass.states.get(entity_id)
        if not state or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, None):
            return default
        try:
            # Load-bearing: a non-numeric state must return the CALLER's
            # default, which units.py can't know. Once this succeeds the
            # ``default=`` below is unreachable (#641).
            value = float(state.state)
        except (ValueError, TypeError):
            return default
        # #641 — this rule (strip + lower + long-form synonyms) was the most
        # robust of the five inline copies, so it became the shared one in
        # units.py. The conversion counter is kept: it is the diagnostic that
        # proved #575.
        if power_unit_scale(state) != 1.0:
            self._last_unit_conversion_count += 1
        return power_state_to_watts(state, default=value)

    def _remaining_day_fraction(self) -> float:
        """Estimate fraction of daylight remaining (rough)."""
        now = dt_util.now()
        # Assume daylight 06:00-20:00
        sunrise_hour = 6
        sunset_hour = 20
        total_hours = sunset_hour - sunrise_hour
        current_hour = now.hour + now.minute / 60

        if current_hour <= sunrise_hour:
            return 1.0
        elif current_hour >= sunset_hour:
            return 0.0
        else:
            remaining = sunset_hour - current_hour
            return remaining / total_hours

    def get_charging_recommendation(
        self,
        daily_ev_target_kwh: float,
        current_ev_energy_kwh: float,
    ) -> str:
        """Recommend a charging strategy based on forecast.

        Returns:
            "solar_only" — enough solar expected
            "solar_plus_cheap" — partial solar, fill gap with cheap grid
            "immediate" — insufficient solar, charge now

        The return string is the same as
        ``self._last_recommendation_path`` (#434) — keep both for
        backward compat (callers expect the return string) and so the
        path can also be read off the audit telemetry surface.
        """
        remaining_need = daily_ev_target_kwh - current_ev_energy_kwh
        if remaining_need <= 0:
            self._last_recommendation_path = "target_reached"
            return "target_reached"

        forecast = self._last_data
        if not forecast.available:
            self._last_recommendation_path = "no_forecast"
            return "no_forecast"

        # Rough estimate: available surplus = remaining forecast * self-consumption factor
        # Assume ~50% of remaining forecast is available as surplus for EV
        estimated_surplus_kwh = forecast.forecast_remaining_today_kwh * 0.5

        if estimated_surplus_kwh >= remaining_need:
            self._last_recommendation_path = "solar_only"
            return "solar_only"
        elif estimated_surplus_kwh >= remaining_need * 0.5:
            self._last_recommendation_path = "solar_plus_cheap"
            return "solar_plus_cheap"
        else:
            self._last_recommendation_path = "immediate"
            return "immediate"

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return the audit telemetry surface (#434).

        Used by the coordinator to expose ``*_path`` strings on the
        existing forecast sensors. Mirrors the ``get_data`` pattern
        in ``forecast_tracker.py`` from #416.
        """
        return {
            # (#819) What was asked for and whether it was honoured. The
            # silent fallback was the whole complaint: SEM logged a warning
            # nobody reads and showed a source nobody chose.
            "requested_source": self.requested_source,
            "honoured": self.honoured,
            "source_detection_path": self._last_source_detection_path,
            "read_path": self._last_read_path,
            "recommendation_path": self._last_recommendation_path,
            "unit_conversion_count": self._last_unit_conversion_count,
            "source": self._source,
        }
