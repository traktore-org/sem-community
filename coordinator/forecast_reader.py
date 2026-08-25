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

    def _registry_entities(self, platform: str) -> Dict[str, str]:
        """Resolve a forecast integration's entities via the entity registry.

        (#562) Entity IDs are localized per HA language; the registry
        ``unique_id`` is not. Returns ``{role: entity_id}`` for every
        role whose unique_id matches; empty dict when the registry is
        unavailable (tests, early boot) or nothing matches.

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

        resolved: Dict[str, str] = {}
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
                    if unique_id in keys and role not in resolved:
                        resolved[role] = entity_id
            else:
                for role, suffix in FORECAST_SOLAR_UNIQUE_SUFFIXES.items():
                    if unique_id.endswith(suffix) and role not in resolved:
                        resolved[role] = entity_id
        self._registry_cache[platform] = (self._mono_time(), resolved)
        return resolved

    def _locate_integration(
        self, platform: str, fallback: Dict[str, str]
    ) -> Optional[Dict[str, str]]:
        """Find an integration's entities (registry first, hardcoded
        entity_ids second) and confirm ``forecast_today`` is usable."""
        for candidate in (self._registry_entities(platform), fallback):
            test_entity = candidate.get("forecast_today")
            if not test_entity:
                continue
            state = self.hass.states.get(test_entity)
            if state and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE, None):
                return candidate
        return None

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
                # Verify cached source is still valid (entity may have disappeared)
                test_entity = self._entities.get("forecast_today")
                if test_entity:
                    state = self.hass.states.get(test_entity)
                    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                        self._source = None
                        self.detect_source()
                        self._last_read_path = "cached_source_lost_redetected"
                    else:
                        self._last_read_path = "cached_source_valid"
                else:
                    self._last_read_path = "cached_source_valid"
        else:
            self._last_read_path = "cached_source_valid"

        if not self._source:
            self._last_read_path = "no_source_after_detect"
            return ForecastData()

        data = ForecastData(
            source=self._source,
            available=True,
            last_update=datetime.now(),
            # (#819) Registry probe behind the same 60 s cache the
            # locator uses (#562), so this is three dict lookups on a
            # warm cache rather than three scans per cycle.
            sources_available=self.available_sources(),
        )

        # Read forecast today
        data.forecast_today_kwh = self._read_float(
            self._entities.get("forecast_today"), 0.0
        )

        # Read forecast tomorrow
        data.forecast_tomorrow_kwh = self._read_float(
            self._entities.get("forecast_tomorrow"), 0.0
        )

        # Read remaining today
        remaining_entity = self._entities.get("forecast_remaining")
        if remaining_entity:
            data.forecast_remaining_today_kwh = self._read_float(remaining_entity, 0.0)
        else:
            # Estimate remaining from today total and current production
            # This is a rough estimate — actual remaining depends on time of day
            data.forecast_remaining_today_kwh = max(
                0, data.forecast_today_kwh * self._remaining_day_fraction()
            )

        # Read power now / next hour / peak — normalized to Watts off the
        # sensor's declared unit (see _read_power_w).
        data.power_now_w = self._read_power_w(
            self._entities.get("power_now"), 0.0
        )
        data.power_next_hour_w = self._read_power_w(
            self._entities.get("power_next_hour"), 0.0
        )
        data.peak_power_today_w = self._read_power_w(
            self._entities.get("peak_power_today"), 0.0
        )

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

    def _read_power_w(self, entity_id: Optional[str], default: float) -> float:
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
