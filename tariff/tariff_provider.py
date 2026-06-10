"""Dynamic electricity tariff providers for Solar Energy Management.

Supports:
- StaticTariffProvider: Fixed HT/NT rates (current behavior)
- DynamicTariffProvider: Reads from Tibber, Nordpool, or aWATTar HA integrations
- SpotMarketProvider: EPEX SPOT prices via Tibber/aWATTar HACS

Used by EnergyCalculator for accurate cost calculations and by
SurplusController for price-responsive device control.
"""
import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


def _as_local(timestamp: datetime) -> datetime:
    """Convert an aware ``timestamp`` to HA's local tz.

    Naive datetimes pass through unchanged (same contract as
    ``_local_date`` — old tests and call sites build naive clocks).
    """
    if timestamp.tzinfo is None:
        return timestamp
    return dt_util.as_local(timestamp)


def _local_date(timestamp: datetime):
    """Return the calendar date of ``timestamp`` in HA's local tz.

    #359: providers vary on what tz they emit — Tibber uses local,
    Nordpool is often UTC. A bare ``timestamp.date()`` on a UTC-tagged
    datetime returns the UTC date, which silently mismatches the local
    ``today`` (Europe/Amsterdam, +02:00 in summer) and empties the
    'today's prices' array → percentile breaks return None → static
    thresholds apply → €0.30 reported as ``normal`` (RienduPre).

    Naive datetimes (no tz info) pass through unchanged so old tests
    and call sites that build their own clocks aren't disturbed.
    """
    return _as_local(timestamp).date()


class PriceLevel(Enum):
    """Electricity price classification."""
    NEGATIVE = "negative"
    VERY_CHEAP = "very_cheap"
    CHEAP = "cheap"
    NORMAL = "normal"
    EXPENSIVE = "expensive"
    VERY_EXPENSIVE = "very_expensive"


@dataclass
class PricePoint:
    """A single price point."""
    timestamp: datetime
    price: float  # Price per kWh in local currency
    currency: str = "CHF"
    level: PriceLevel = PriceLevel.NORMAL


@dataclass
class TariffData:
    """Current tariff information."""
    current_import_rate: float = 0.0
    current_export_rate: float = 0.0
    price_level: PriceLevel = PriceLevel.NORMAL
    currency: str = "CHF"
    provider: str = "unknown"
    is_dynamic: bool = False

    # Price windows
    next_cheap_window_start: Optional[datetime] = None
    next_cheap_window_end: Optional[datetime] = None
    next_expensive_window_start: Optional[datetime] = None

    # Today's price range
    today_min_price: Optional[float] = None
    today_max_price: Optional[float] = None
    today_avg_price: Optional[float] = None

    # Upcoming prices
    upcoming_prices: List[PricePoint] = field(default_factory=list)

    # #359 follow-up — diagnostic: which classifier path produced the
    # current ``price_level``. Exposed as the ``tariff_classifier_path``
    # sensor attribute so users hitting RienduPre's
    # derivative-entity-without-prices_today scenario can see WHY their
    # classification is NORMAL instead of filing a duplicate bug.
    # Values:
    #   percentile_active(p10=0.14,p25=..,p75=..,p90=..)
    #   percentile_fallback_cache_empty
    #   percentile_fallback_too_few_prices(n=3)
    #   percentile_fallback_flat_day(spread=0.0008)
    #   static_fixed_cutoffs
    #   negative_price_shortcircuit
    classifier_path: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tariff_current_import_rate": round(self.current_import_rate, 4),
            "tariff_current_export_rate": round(self.current_export_rate, 4),
            "tariff_price_level": self.price_level.value,
            "tariff_currency": self.currency,
            "tariff_provider": self.provider,
            "tariff_is_dynamic": self.is_dynamic,
            "tariff_classifier_path": self.classifier_path,
            "tariff_next_cheap_start": (
                self.next_cheap_window_start.isoformat()
                if self.next_cheap_window_start else None
            ),
            "tariff_next_cheap_end": (
                self.next_cheap_window_end.isoformat()
                if self.next_cheap_window_end else None
            ),
            "tariff_today_min_price": (
                round(self.today_min_price, 4) if self.today_min_price is not None else None
            ),
            "tariff_today_max_price": (
                round(self.today_max_price, 4) if self.today_max_price is not None else None
            ),
            "tariff_today_avg_price": (
                round(self.today_avg_price, 4) if self.today_avg_price is not None else None
            ),
        }


class TariffProvider(ABC):
    """Base class for tariff providers."""

    @abstractmethod
    def get_current_import_rate(self) -> float:
        """Get current import price per kWh."""

    @abstractmethod
    def get_current_export_rate(self) -> float:
        """Get current export price per kWh."""

    @abstractmethod
    def get_price_level(self) -> PriceLevel:
        """Classify current price level."""

    @abstractmethod
    def get_tariff_data(self) -> TariffData:
        """Get complete tariff information."""

    @abstractmethod
    def get_price_at(self, when: datetime) -> Optional[float]:
        """Get price at a specific time (for planning)."""


class StaticTariffProvider(TariffProvider):
    """Static HT/NT tariff rates.

    HT (high tariff): daytime rate (07:00-20:00 weekdays)
    NT (low tariff): nighttime/weekend rate
    """

    def __init__(
        self,
        peak_rate: float = 0.3387,   # /kWh daytime incl. VAT
        off_peak_rate: float = 0.3387,   # /kWh nighttime incl. VAT (default flat rate)
        export_rate: float = 0.075,  # /kWh feed-in
        peak_start: int = 7,   # Peak starts at 07:00
        peak_end: int = 20,    # Peak ends at 20:00
        currency: str = "CHF",
    ):
        self.peak_rate = peak_rate
        self.off_peak_rate = off_peak_rate
        self.export_rate = export_rate
        self.peak_start = peak_start
        self.peak_end = peak_end
        self.currency = currency

    def _is_high_tariff(self, when: Optional[datetime] = None) -> bool:
        """Check if current time is in high tariff period."""
        now = when or dt_util.now()
        # Weekend is always NT
        if now.weekday() >= 5:
            return False
        return self.peak_start <= now.hour < self.peak_end

    def get_current_import_rate(self) -> float:
        return self.peak_rate if self._is_high_tariff() else self.off_peak_rate

    def get_current_export_rate(self) -> float:
        return self.export_rate

    def get_price_level(self) -> PriceLevel:
        if self._is_high_tariff():
            return PriceLevel.NORMAL
        return PriceLevel.CHEAP

    def get_price_at(self, when: datetime) -> Optional[float]:
        return self.peak_rate if self._is_high_tariff(when) else self.off_peak_rate

    def get_tariff_data(self) -> TariffData:
        now = dt_util.now()
        data = TariffData(
            current_import_rate=self.get_current_import_rate(),
            current_export_rate=self.export_rate,
            price_level=self.get_price_level(),
            currency=self.currency,
            provider="static",
            is_dynamic=False,
            classifier_path="static_ht_nt",
            today_min_price=self.off_peak_rate,
            today_max_price=self.peak_rate,
            today_avg_price=(self.peak_rate + self.off_peak_rate) / 2,
        )

        # Calculate next cheap window (next NT period)
        if self._is_high_tariff():
            # Next NT starts at ht_end today
            next_off_peak = now.replace(hour=self.peak_end, minute=0, second=0, microsecond=0)
            data.next_cheap_window_start = next_off_peak
            # Off-peak ends at peak_start next day
            data.next_cheap_window_end = (next_off_peak + timedelta(days=1)).replace(
                hour=self.peak_start
            )

        return data


class DynamicTariffProvider(TariffProvider):
    """Dynamic tariff provider reading from HA integrations.

    Supports:
    - Tibber (built-in HA integration)
    - Nordpool (HACS)
    - aWATTar (HACS)
    - Generic price sensor (any sensor with price as state)
    """

    # Known entity patterns per provider
    PROVIDER_ENTITIES = {
        "tibber": {
            "price": "sensor.electricity_price_{home}",
            "price_level": "sensor.electricity_price_{home}",
            "prices_today": "sensor.electricity_price_{home}",
        },
        "nordpool": {
            "price": "sensor.nordpool_kwh_{region}_eur_{precision}_{vat}",
            "fallback": "sensor.nordpool",
        },
        "awattar": {
            "price": "sensor.awattar",
        },
    }

    def __init__(
        self,
        hass: HomeAssistant,
        price_entity: Optional[str] = None,
        forecast_entity: Optional[str] = None,
        feedin_entity: Optional[str] = None,
        export_rate: float = 0.075,
        cheap_threshold: float = 0.15,
        expensive_threshold: float = 0.35,
        currency: str = "CHF",
        classification_mode: str = "percentile",
        fallback_price: float = 0.30,
    ):
        self.hass = hass
        self.export_rate = export_rate
        self.cheap_threshold = cheap_threshold
        self.expensive_threshold = expensive_threshold
        # Last-resort import rate when the price entity is unavailable
        # AND no cached curve covers the moment. 0.30 is CHF/EUR-shaped;
        # the coordinator passes the user's configured import rate so
        # SEK/NOK/HUF installs don't get billed a nonsense constant.
        self.fallback_price = fallback_price
        # #359: switch the default classification away from the static
        # 0.15 / 0.35 CHF thresholds (worthless on Tibber-style tariffs
        # ranging 0.10–0.80) to percentile-based bucketing over today's
        # 24-hour price array. ``static`` preserved as an opt-out for
        # users with flat tariffs / spike-prone markets.
        self.classification_mode = (
            classification_mode if classification_mode in ("static", "percentile")
            else "percentile"
        )
        self.currency = currency
        self._price_entity = price_entity
        self._provider_name = "unknown"
        self._forecast_entity: Optional[str] = forecast_entity
        self._feedin_entity: Optional[str] = feedin_entity
        self._prices_cache: List[PricePoint] = []
        self._last_cache_update: Optional[datetime] = None
        # Day-ahead curve fetched via a service action (official Nord
        # Pool core integration — no attribute arrays, core#132856).
        # Filled by ``async_refresh_service_prices`` from the
        # coordinator's async update loop; consumed by
        # ``_read_prices_list`` when attribute parsing yields nothing.
        self._service_prices: List[PricePoint] = []
        self._service_prices_fetched_at: Optional[datetime] = None
        # Cached percentile breakpoints, recomputed when the price
        # cache or the rolling window's slot changes.
        # Keys: ``p10``, ``p25``, ``p75``, ``p90``.
        self._percentile_breaks: Optional[Dict[str, float]] = None
        self._percentile_breaks_for: Optional[str] = None  # window key
        # #359 follow-up — surface which classifier path produced the most
        # recent ``price_level`` via the ``tariff_classifier_path`` sensor
        # attribute. Lets users see WHY their classification is what it
        # is (especially the cold-start / no-prices_today fallback paths
        # that produce NORMAL silently).
        self._last_classifier_path: str = "unknown"

    # Day-ahead curves don't change once published; re-fetch only to
    # pick up tomorrow's prices when they publish (~13:00 CET).
    SERVICE_PRICE_REFRESH = timedelta(minutes=30)

    async def async_refresh_service_prices(self) -> bool:
        """Fetch the day-ahead curve from the official Nord Pool core
        integration's ``get_prices_for_date`` action.

        The official integration (HA 2024.12+) exposes no price arrays
        as sensor attributes (core#132856) — unlike the HACS custom
        component's ``raw_today`` — so the curve has to be pulled via a
        service call. Must run on the event loop; the coordinator calls
        it once per update cycle and this method throttles itself.

        Returns True when fresh prices were stored.
        """
        services = getattr(self.hass, "services", None)
        if services is None or not services.has_service(
            "nordpool", "get_prices_for_date",
        ):
            return False

        now = dt_util.now()
        if (
            self._service_prices
            and self._service_prices_fetched_at is not None
            and now - self._service_prices_fetched_at < self.SERVICE_PRICE_REFRESH
        ):
            return False

        entries = self.hass.config_entries.async_entries("nordpool")
        if not entries:
            return False
        entry_id = entries[0].entry_id

        points: List[PricePoint] = []
        for day in (now.date(), now.date() + timedelta(days=1)):
            try:
                resp = await services.async_call(
                    "nordpool",
                    "get_prices_for_date",
                    {"config_entry": entry_id, "date": day.isoformat()},
                    blocking=True,
                    return_response=True,
                )
            except Exception as err:  # noqa: BLE001 — tomorrow not yet published, network, …
                _LOGGER.debug(
                    "Nord Pool get_prices_for_date(%s) failed: %s", day, err,
                )
                continue
            if not isinstance(resp, dict):
                continue
            # Response is keyed by area: {"CH": [{start, end, price}, …]}.
            # SEM is a single-home integration — use the first area.
            for area_prices in resp.values():
                if isinstance(area_prices, list):
                    for item in area_prices:
                        if not isinstance(item, dict):
                            continue
                        ts = item.get("start")
                        price = item.get("price")
                        if ts is None or price is None:
                            continue
                        try:
                            dt = (
                                datetime.fromisoformat(ts)
                                if isinstance(ts, str) else ts
                            )
                            points.append(PricePoint(
                                timestamp=dt,
                                # The action returns raw spot in
                                # currency/MWh ("All prices are returned
                                # in [Currency]/MWh" — integration docs);
                                # SEM works in currency/kWh.
                                price=float(price) / 1000.0,
                                currency=self.currency,
                            ))
                        except (ValueError, TypeError):
                            continue
                break

        if not points:
            return False
        self._service_prices = sorted(points, key=lambda p: p.timestamp)
        self._service_prices_fetched_at = now
        if self._provider_name == "unknown":
            self._provider_name = "nordpool_official"
        _LOGGER.debug(
            "Nord Pool service fetch: %d price points (%s … %s)",
            len(self._service_prices),
            self._service_prices[0].timestamp.isoformat(),
            self._service_prices[-1].timestamp.isoformat(),
        )
        return True

    def detect_provider(self) -> Optional[str]:
        """Auto-detect available price integration."""
        if self._price_entity:
            state = self.hass.states.get(self._price_entity)
            if state and state.state not in ("unknown", "unavailable"):
                self._provider_name = "custom"
                return "custom"

        # Try Tibber
        for state in self.hass.states.async_all("sensor"):
            entity_id = state.entity_id
            if "electricity_price" in entity_id and "tibber" in (
                state.attributes.get("integration", "")
            ):
                self._price_entity = entity_id
                self._provider_name = "tibber"
                _LOGGER.info("Detected Tibber price entity: %s", entity_id)
                return "tibber"

        # Try Amber Electric (Australia)
        for state in self.hass.states.async_all("sensor"):
            entity_id = state.entity_id
            if "amber" in entity_id and "general_price" in entity_id:
                self._price_entity = entity_id
                self._provider_name = "amber"
                # Try to find the forecast entity for price forecasts
                forecast_id = entity_id.replace("general_price", "general_forecast")
                forecast_state = self.hass.states.get(forecast_id)
                if forecast_state and forecast_state.state not in ("unknown", "unavailable"):
                    self._forecast_entity = forecast_id
                # Try to find the feed-in price entity for dynamic export rate
                feedin_id = entity_id.replace("general_price", "feed_in_price")
                feedin_state = self.hass.states.get(feedin_id)
                if feedin_state and feedin_state.state not in ("unknown", "unavailable"):
                    self._feedin_entity = feedin_id
                _LOGGER.info("Detected Amber Electric price entity: %s", entity_id)
                return "amber"

        # Try Octopus Energy (UK)
        for state in self.hass.states.async_all("sensor"):
            entity_id = state.entity_id
            if "octopus_energy" in entity_id and "current_rate" in entity_id:
                self._price_entity = entity_id
                self._provider_name = "octopus"
                # Discover event entities for today/tomorrow rate arrays
                base = entity_id.replace("sensor.", "event.").replace("_current_rate", "")
                for suffix in ("_current_day_rates", "_next_day_rates"):
                    event_id = base + suffix
                    event_state = self.hass.states.get(event_id)
                    if event_state and event_state.state not in ("unknown", "unavailable"):
                        self._forecast_entity = event_id
                        break
                # Try export rate sensor
                export_id = entity_id.replace("current_rate", "export_current_rate")
                export_state = self.hass.states.get(export_id)
                if export_state and export_state.state not in ("unknown", "unavailable"):
                    self._feedin_entity = export_id
                _LOGGER.info("Detected Octopus Energy price entity: %s", entity_id)
                return "octopus"

        # Try the official Nord Pool core integration (HA 2024.12+).
        # It exposes no price arrays as attributes (core#132856) — the
        # curve comes from the nordpool.get_prices_for_date action via
        # async_refresh_service_prices. Entity ids look like
        # sensor.nord_pool_<area>_current_price.
        for state in self.hass.states.async_all("sensor"):
            entity_id = state.entity_id
            if "nord_pool" in entity_id and entity_id.endswith("_current_price"):
                self._price_entity = entity_id
                self._provider_name = "nordpool_official"
                _LOGGER.info(
                    "Detected official Nord Pool price entity: %s "
                    "(day-ahead curve via get_prices_for_date action)",
                    entity_id,
                )
                return "nordpool_official"

        # Try Nordpool (HACS custom component — attribute arrays)
        for state in self.hass.states.async_all("sensor"):
            entity_id = state.entity_id
            if "nordpool" in entity_id:
                self._price_entity = entity_id
                self._provider_name = "nordpool"
                _LOGGER.info("Detected Nordpool price entity: %s", entity_id)
                return "nordpool"

        # Try aWATTar
        state = self.hass.states.get("sensor.awattar")
        if state and state.state not in ("unknown", "unavailable"):
            self._price_entity = "sensor.awattar"
            self._provider_name = "awattar"
            _LOGGER.info("Detected aWATTar price entity")
            return "awattar"

        return None

    def _read_current_price(self) -> float:
        """Read current price from the price entity.

        Fallback chain when the entity can't be read:
        1. cached day-ahead slot covering "now" (entity flaps,
           core#166742)
        2. average of the cached curve (slot lookup missed — e.g. the
           cache only holds yesterday after a long outage)
        3. ``fallback_price`` (configurable; defaults to 0.30)
        """
        if not self._price_entity:
            self.detect_provider()
        if not self._price_entity:
            return self._fallback_import_rate()

        state = self.hass.states.get(self._price_entity)
        if state and state.state not in ("unknown", "unavailable"):
            try:
                return float(state.state)
            except (ValueError, TypeError):
                pass

        # Entity temporarily unavailable: prefer the cached price curve
        # over the configured fallback. HA core's Tibber integration has
        # been flapping to ``unavailable`` between polls since the
        # 2026.1 OAuth2 migration (core#166742) — a constant here
        # would silently distort cost accumulation and classification
        # for most of every poll cycle, while the day-ahead curve in
        # the cache is still perfectly valid.
        cached = self._cached_price_for(dt_util.now())
        if cached is not None:
            return cached
        return self._fallback_import_rate()

    def _fallback_import_rate(self) -> float:
        """Best price guess without entity state or a current slot."""
        if self._prices_cache:
            vals = [p.price for p in self._prices_cache if p.price is not None]
            if vals:
                return sum(vals) / len(vals)
        return self.fallback_price

    def _cached_price_for(self, when: datetime) -> Optional[float]:
        """Price of the cached slot covering ``when``, if any."""
        cache = self._prices_cache
        if not cache:
            return None
        interval = self._detect_interval(cache)
        for p in cache:
            try:
                if p.timestamp <= when < p.timestamp + interval:
                    return p.price
            except TypeError:
                # naive/aware mismatch between cache and clock — treat
                # as a cache miss rather than blowing up the update loop
                return None
        return None

    def _read_prices_list(self) -> List[PricePoint]:
        """Read upcoming prices from entity attributes.

        Supports a range of provider attribute shapes:

        * **Tibber HA core**: ``today`` / ``tomorrow`` array of dicts
          with ``startsAt`` + ``total`` (full price incl. tax)
        * **Tibber API v2 / Tibber Pulse 15-min** (PROD: RienduPre,
          Discussion #432, 2026-06-07): same shape but 96 entries
          (15-min granularity).
        * **Nordpool**: ``raw_today`` / ``raw_tomorrow`` with
          ``start`` + ``value`` (raw spot, no taxes).
        * **EnergyZero NL** / **EasyEnergy NL**: ``prices_today``
          / ``prices_tomorrow`` with ``start`` + ``price`` (15-min
          shape on some installs).
        * **ENTSO-E** (15-min PROD use in NL/DE): often
          ``prices`` array with ``time`` + ``price``.
        * **Amber Electric** / **Octopus Energy**: ``forecasts`` /
          ``rates`` with ``start_time`` + ``per_kwh``.

        v1.7.2-beta.3 (2026-06-07): also tries ``prices`` (singular)
        + ``time`` / ``hour`` timestamp keys after seeing them in
        community-shared NL 15-min sensor templates. The diagnose
        surface exposes which attribute matched so an empty result
        for a non-listed shape is visible without a maintainer
        having to read the raw entity dump.
        """
        # v1.7.2-beta.3: clear the per-cycle diag fields so the
        # diagnose surface reflects THIS read, not the prior one.
        self._last_parsed_attribute: Optional[str] = None
        self._last_parsed_count: int = 0
        self._last_parsed_gap_seconds: Optional[float] = None

        state = (
            self.hass.states.get(self._price_entity)
            if self._price_entity else None
        )
        if state is None and not self._service_prices:
            return []

        prices = []
        attrs = state.attributes if state else {}

        # Tibber + NL EnergyZero/EasyEnergy + generic
        for key in ("prices_today", "prices_tomorrow", "today", "tomorrow", "prices"):
            price_list = attrs.get(key, [])
            if isinstance(price_list, list):
                for item in price_list:
                    if isinstance(item, dict):
                        # Expanded timestamp key vocabulary — v1.7.2-beta.3
                        # adds ``time`` (ENTSO-E) and ``hour`` (some NL
                        # template sensors) to the existing ``start`` /
                        # ``startsAt``.
                        ts = (
                            item.get("start")
                            or item.get("startsAt")
                            or item.get("time")
                            or item.get("hour")
                        )
                        # Expanded price key vocabulary — already covers
                        # most providers, kept verbatim.
                        price = item.get("total", item.get("price", item.get("value")))
                        if ts and price is not None:
                            try:
                                if isinstance(ts, str):
                                    dt = datetime.fromisoformat(ts)
                                else:
                                    dt = ts
                                prices.append(PricePoint(
                                    timestamp=dt,
                                    price=float(price),
                                    currency=self.currency,
                                    level=self._classify_price(float(price)),
                                ))
                            except (ValueError, TypeError):
                                continue
                if prices and not self._last_parsed_attribute:
                    self._last_parsed_attribute = key

        # Nordpool: raw_today, raw_tomorrow attributes
        for key in ("raw_today", "raw_tomorrow"):
            price_list = attrs.get(key, [])
            if isinstance(price_list, list):
                for item in price_list:
                    if isinstance(item, dict):
                        ts = item.get("start")
                        price = item.get("value")
                        if ts and price is not None:
                            try:
                                if isinstance(ts, str):
                                    dt = datetime.fromisoformat(ts)
                                else:
                                    dt = ts
                                prices.append(PricePoint(
                                    timestamp=dt,
                                    price=float(price),
                                    currency=self.currency,
                                    level=self._classify_price(float(price)),
                                ))
                            except (ValueError, TypeError):
                                continue
                if prices and not self._last_parsed_attribute:
                    self._last_parsed_attribute = key

        # Generic forecast: "forecasts" or "rates" attribute (Amber Electric,
        # Octopus Energy, or any provider that stores an array of price dicts).
        # Checks the price entity first, then the dedicated forecast entity if set.
        if not prices:
            forecast_sources = [attrs]
            if self._forecast_entity:
                fc_state = self.hass.states.get(self._forecast_entity)
                if fc_state:
                    forecast_sources.append(fc_state.attributes)
            for src_attrs in forecast_sources:
                for attr_key in ("forecasts", "rates"):
                    forecast_list = src_attrs.get(attr_key, [])
                    if isinstance(forecast_list, list) and forecast_list:
                        for item in forecast_list:
                            if not isinstance(item, dict):
                                continue
                            ts = item.get("start_time", item.get("start", item.get("startsAt")))
                            price = item.get("per_kwh", item.get("price", item.get("total",
                                    item.get("value", item.get("value_inc_vat")))))
                            if ts and price is not None:
                                try:
                                    if isinstance(ts, str):
                                        dt = datetime.fromisoformat(ts)
                                    else:
                                        dt = ts
                                    prices.append(PricePoint(
                                        timestamp=dt,
                                        price=float(price),
                                        currency=self.currency,
                                        level=self._classify_price(float(price)),
                                    ))
                                except (ValueError, TypeError):
                                    continue
                        if prices and not self._last_parsed_attribute:
                            self._last_parsed_attribute = attr_key
                        break  # Found data in this attribute, stop
                if prices:
                    break  # Found data in this source, stop

        # Official Nord Pool core integration: the curve was fetched via
        # the get_prices_for_date action (async_refresh_service_prices,
        # driven by the coordinator) — there are no attribute arrays to
        # parse (core#132856). Attribute shapes win when both exist.
        if not prices and self._service_prices:
            for sp in self._service_prices:
                prices.append(PricePoint(
                    timestamp=sp.timestamp,
                    price=sp.price,
                    currency=self.currency,
                    level=self._classify_price(sp.price),
                ))
            self._last_parsed_attribute = "service:nordpool.get_prices_for_date"

        # Mixed naive/aware timestamps (e.g. a template sensor emitting
        # naive ISO strings alongside an aware provider array) would make
        # the sort below raise TypeError. Tag naive entries with HA's
        # local tz; all-naive arrays (legacy tests / custom clocks) pass
        # through untouched.
        if any(p.timestamp.tzinfo is not None for p in prices) and any(
            p.timestamp.tzinfo is None for p in prices
        ):
            for p in prices:
                if p.timestamp.tzinfo is None:
                    p.timestamp = p.timestamp.replace(
                        tzinfo=dt_util.DEFAULT_TIME_ZONE,
                    )

        prices = sorted(prices, key=lambda p: p.timestamp)

        # Dedupe identical timestamps (keep first): entities that expose
        # the same curve under two recognised attribute names (e.g.
        # ``prices`` plus ``prices_today``, or Tibber ``today`` next to
        # Nordpool-style ``raw_today``) would otherwise double every
        # point and skew the percentile breaks and today's avg.
        if prices:
            seen: set = set()
            deduped: List[PricePoint] = []
            for p in prices:
                if p.timestamp in seen:
                    continue
                seen.add(p.timestamp)
                deduped.append(p)
            prices = deduped

        # v1.7.2-beta.3: record diagnostic info about the parse for
        # the tariff diagnose surface. Tells users (and us) which
        # attribute matched + the detected sample interval so a
        # 15-min vs hourly mismatch shows up cleanly.
        self._last_parsed_count = len(prices)
        if len(prices) >= 2:
            gap = (prices[1].timestamp - prices[0].timestamp).total_seconds()
            self._last_parsed_gap_seconds = gap if 0 < gap <= 3600 else None

        # Entity flap guard (HA core#166742: Tibber reads ``unavailable``
        # between polls since the 2026.1 OAuth2 migration, dropping its
        # attributes): an empty parse from an *unavailable* entity must
        # not wipe a previously good cache. Day-ahead prices don't go
        # stale within a poll cycle, and wiping would break percentile
        # classification, the cheap windows and the schedule card until
        # the next successful poll. An *available* entity with no
        # recognised shape still yields [] so the diagnose surface
        # reflects the truth.
        if (
            not prices
            and self._prices_cache
            and (state is None or state.state in ("unknown", "unavailable"))
        ):
            return self._prices_cache

        # #359: write back to the cache so ``_get_percentile_breaks``
        # can compute today's distribution. The classification done
        # in-line above used the cold cache (static fallback); now
        # reclassify with percentile breaks if there's enough data.
        # Single pass — cheap relative to the dozens of HA-state
        # reads above. The window key inside ``_get_percentile_breaks``
        # keeps the calculation to once per slot / cache change.
        self._prices_cache = prices
        self._percentile_breaks = None  # invalidate to force recompute
        self._percentile_breaks_for = None
        if self.classification_mode == "percentile" and prices:
            for p in prices:
                p.level = self._classify_price(p.price)

        return prices

    def _classify_price(self, price: float) -> PriceLevel:
        """Classify a price into levels.

        v1.7.0 / #359: when ``classification_mode == "percentile"``,
        bucket relative to a rolling ~24h price distribution (the slot
        in progress + the next 24h, padded backwards while tomorrow's
        prices aren't published yet — see ``_get_percentile_breaks``):

        - ``very_cheap`` — bottom 10%
        - ``cheap``      — bottom 25%
        - ``normal``     — 25 – 75%
        - ``expensive``  — top 25%
        - ``very_expensive`` — top 90%+

        That works on Tibber / Octopus / Amber / Nordpool where the
        absolute price range varies daily and the static 0.15 / 0.35
        CHF cutoffs flag everything as ``normal`` (UK summer) or
        ``very_expensive`` (winter peaks).

        ``static`` preserves the legacy fixed-cutoff behaviour for
        users with flat tariffs or unpredictable spike markets.

        #359 follow-up (beta.16): when the user picked ``percentile``
        but the breaks can't be computed (cold start, < 4 points, flat
        day), DO NOT silently fall through to the static cutoffs.
        Those thresholds are calibrated for CHF (0.15 / 0.35) and
        silently mis-classify any other currency — RienduPre's
        Tibber NL install reported €0.30 as ``normal`` for this exact
        reason. Return ``NORMAL`` instead: a neutral default that
        doesn't trigger cheap-window or expensive-window automation
        until we actually have data to classify against.
        """
        if price < 0:
            self._last_classifier_path = "negative_price_shortcircuit"
            return PriceLevel.NEGATIVE

        if self.classification_mode == "percentile":
            breaks = self._get_percentile_breaks()
            if breaks is not None:
                # _get_percentile_breaks sets the active-path string in
                # the happy case; just return the bucketed level.
                if price <= breaks["p10"]:
                    return PriceLevel.VERY_CHEAP
                if price <= breaks["p25"]:
                    return PriceLevel.CHEAP
                if price >= breaks["p90"]:
                    return PriceLevel.VERY_EXPENSIVE
                if price >= breaks["p75"]:
                    return PriceLevel.EXPENSIVE
                return PriceLevel.NORMAL
            # #359: percentile requested but no breaks available.
            # Return NORMAL as a safe default. NEVER apply the
            # CHF-calibrated static cutoffs here — they're wrong for
            # any non-CHF tariff and silently produce confusing
            # classifications that look like a SEM bug.
            # _last_classifier_path already set by _get_percentile_breaks
            # to one of the fallback_* values that explain why.
            _LOGGER.debug(
                "tariff/#359: percentile mode but no breaks (%s) — "
                "returning NORMAL (safe default).",
                self._last_classifier_path,
            )
            return PriceLevel.NORMAL

        # Static thresholds (legacy + explicit opt-in).
        # Only reached when classification_mode == "static" — the user
        # has explicitly chosen fixed cutoffs because their tariff is
        # flat or their CHF/EUR scale matches the defaults.
        self._last_classifier_path = "static_fixed_cutoffs"
        if price < self.cheap_threshold * 0.5:
            return PriceLevel.VERY_CHEAP
        if price < self.cheap_threshold:
            return PriceLevel.CHEAP
        if price > self.expensive_threshold * 1.5:
            return PriceLevel.VERY_EXPENSIVE
        if price > self.expensive_threshold:
            return PriceLevel.EXPENSIVE
        return PriceLevel.NORMAL

    def _get_percentile_breaks(self) -> Optional[Dict[str, float]]:
        """Compute percentile breakpoints over a rolling ~24h window.
        Returns ``None`` when there's not enough data (< 4 points) for
        percentiles to be meaningful.

        The window is the slot in progress plus the next 24 hours; when
        less than 24h of future data is cached (tomorrow publishes
        ~13:00 CET), it extends backwards over the most recent past
        slots so it always covers roughly a day of context.

        Rationale (evcc-style): per-calendar-day breaks ignored
        tomorrow's published prices, so at 22:00 a price was bucketed
        against this morning's peak instead of the night ahead — the
        window that actually matters for cheap-window automation.

        Cached per slot (and invalidated whenever the price cache is
        re-parsed) so the calculation stays cheap.

        Side-effect: sets ``self._last_classifier_path`` to a string
        explaining which path was taken so users see WHY their
        classification ended up where it did (#359 follow-up — exposed
        via the ``tariff_classifier_path`` sensor attribute).
        """
        if not self._prices_cache:
            self._last_classifier_path = "percentile_fallback_cache_empty"
            return None

        now = dt_util.now()
        interval = self._detect_interval(self._prices_cache)

        # #359 follow-up: tz-coerce timestamps before comparing with the
        # local clock. Providers vary on what tz they emit — Tibber is
        # local, Nordpool is often UTC — and naive/aware mismatches
        # either crash the comparison or silently shift the window.
        def _coerce(ts: datetime) -> datetime:
            if ts.tzinfo is None and now.tzinfo is not None:
                return ts.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            if ts.tzinfo is not None and now.tzinfo is None:
                return _as_local(ts).replace(tzinfo=None)
            return ts

        try:
            slot_epoch = int(now.timestamp() // interval.total_seconds())
        except (OSError, OverflowError, ValueError):
            slot_epoch = 0
        window_key = f"{slot_epoch}|{len(self._prices_cache)}"
        if (
            self._percentile_breaks is not None
            and self._percentile_breaks_for == window_key
        ):
            return self._percentile_breaks

        horizon = now + timedelta(hours=24)
        valid = [
            (p, _coerce(p.timestamp)) for p in self._prices_cache
            if p.price is not None
        ]
        future = [ts for _, ts in valid if now - interval < ts <= horizon]
        if future:
            future_span = max(timedelta(0), (max(future) + interval) - now)
        else:
            future_span = timedelta(0)
        # Pad backwards to ~24h of context when the future is short
        # (e.g. before tomorrow's prices publish, or late evening on a
        # today-only cache).
        lookback = max(timedelta(0), timedelta(hours=24) - future_span)
        window_start = now - interval - lookback

        window_prices = sorted(
            p.price for p, ts in valid
            if window_start < ts <= horizon
        )
        if len(window_prices) < 4:
            self._last_classifier_path = (
                f"percentile_fallback_too_few_prices(n={len(window_prices)})"
            )
            _LOGGER.debug(
                "tariff/#359: percentile fallback — rolling-24h window "
                "has %d / %d points (need ≥4); classifying as NORMAL",
                len(window_prices), len(self._prices_cache),
            )
            return None

        def _quantile(sorted_values: List[float], q: float) -> float:
            # Plain nearest-rank quantile — good enough for 24/48-point
            # arrays; avoids a numpy dependency.
            if not sorted_values:
                return 0.0
            idx = max(
                0,
                min(
                    len(sorted_values) - 1,
                    int(round(q * (len(sorted_values) - 1))),
                ),
            )
            return sorted_values[idx]

        breaks = {
            "p10": _quantile(window_prices, 0.10),
            "p25": _quantile(window_prices, 0.25),
            "p75": _quantile(window_prices, 0.75),
            "p90": _quantile(window_prices, 0.90),
        }
        # Degenerate distribution guard (M1 reviewer note): a flat or
        # near-flat day collapses every break to the same value, which
        # would classify every price as VERY_CHEAP and over-trigger
        # any cheap-window logic downstream. Threshold = 1 ct/kWh —
        # narrower than that is functionally flat, so classification
        # falls back to the NORMAL safe default.
        if (breaks["p90"] - breaks["p10"]) < 0.01:
            self._last_classifier_path = (
                f"percentile_fallback_flat_day("
                f"spread={breaks['p90'] - breaks['p10']:.4f})"
            )
            _LOGGER.debug(
                "tariff/#359: degenerate distribution — p90-p10=%.4f < 0.01 "
                "(%d window points); classifying as NORMAL",
                breaks["p90"] - breaks["p10"], len(window_prices),
            )
            return None
        self._last_classifier_path = (
            f"percentile_active("
            f"p10={breaks['p10']:.4f},p25={breaks['p25']:.4f},"
            f"p75={breaks['p75']:.4f},p90={breaks['p90']:.4f},"
            f"n={len(window_prices)})"
        )
        _LOGGER.debug(
            "tariff/#359: rolling-24h percentile breaks — p10=%.4f "
            "p25=%.4f p75=%.4f p90=%.4f (%d window points)",
            breaks["p10"], breaks["p25"], breaks["p75"],
            breaks["p90"], len(window_prices),
        )
        self._percentile_breaks = breaks
        self._percentile_breaks_for = window_key
        return breaks

    def get_current_import_rate(self) -> float:
        return self._read_current_price()

    def get_current_export_rate(self) -> float:
        """Read export rate from feed-in entity if available, else static."""
        if self._feedin_entity:
            state = self.hass.states.get(self._feedin_entity)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    # Feed-in prices may be negative (= earning), take abs
                    return abs(float(state.state))
                except (ValueError, TypeError):
                    pass
        return self.export_rate

    def get_price_level(self) -> PriceLevel:
        return self._classify_price(self._read_current_price())

    @staticmethod
    def _detect_interval(prices: List[PricePoint]) -> timedelta:
        """Slot length from the gap between the first two points.

        Hourly is the default; 15/30-min markets are detected from the
        data (gaps over an hour — e.g. a day boundary — are ignored).
        """
        if len(prices) >= 2:
            gap = (prices[1].timestamp - prices[0].timestamp).total_seconds()
            if 0 < gap <= 3600:
                return timedelta(seconds=gap)
        return timedelta(hours=1)

    def get_price_at(self, when: datetime) -> Optional[float]:
        prices = self._read_prices_list()
        if not prices:
            return None
        interval = self._detect_interval(prices)
        for p in prices:
            if p.timestamp <= when < p.timestamp + interval:
                return p.price
        return None

    def get_tariff_data(self) -> TariffData:
        current_price = self._read_current_price()
        prices = self._read_prices_list()

        # ``_classify_price`` (via ``_get_percentile_breaks``) sets
        # ``self._last_classifier_path`` as a side-effect describing
        # which path produced the level — surface it on TariffData so
        # the sensor attribute documents the path.
        price_level = self._classify_price(current_price)
        now = dt_util.now()
        # Genuinely upcoming slots: the one in progress plus the future,
        # capped at 48 points (covers two hourly days / half a 15-min
        # day). ``prices[:24]`` used to return the first 24 slots from
        # midnight — mostly the past by the afternoon, and never
        # tomorrow's curve.
        interval = self._detect_interval(prices)
        upcoming = [p for p in prices if p.timestamp + interval > now][:48]
        data = TariffData(
            # For SpotMarketProvider the effective rate adds grid fees +
            # taxes on top of the raw spot price — report the effective
            # rate (it feeds the cost accumulators), but classify the
            # raw price: the cached distribution is raw spot too.
            current_import_rate=self.get_current_import_rate(),
            current_export_rate=self.get_current_export_rate(),
            price_level=price_level,
            currency=self.currency,
            provider=self._provider_name,
            is_dynamic=True,
            classifier_path=self._last_classifier_path,
            upcoming_prices=upcoming,
        )

        if prices:
            # #359: use the timestamp's local-tz date — see _get_percentile_breaks
            # for the same UTC-vs-local pitfall.
            today = now.date()
            today_prices = [
                p.price for p in prices
                if _local_date(p.timestamp) == today
            ]
            if today_prices:
                data.today_min_price = min(today_prices)
                data.today_max_price = max(today_prices)
                data.today_avg_price = sum(today_prices) / len(today_prices)

            # Find next cheap window
            for p in prices:
                if p.timestamp > now and p.level in (PriceLevel.CHEAP, PriceLevel.VERY_CHEAP, PriceLevel.NEGATIVE):
                    data.next_cheap_window_start = p.timestamp
                    # Find end of cheap window
                    for p2 in prices:
                        if p2.timestamp > p.timestamp and p2.level not in (PriceLevel.CHEAP, PriceLevel.VERY_CHEAP, PriceLevel.NEGATIVE):
                            data.next_cheap_window_end = p2.timestamp
                            break
                    break

            # Find next expensive window
            for p in prices:
                if p.timestamp > now and p.level in (PriceLevel.EXPENSIVE, PriceLevel.VERY_EXPENSIVE):
                    data.next_expensive_window_start = p.timestamp
                    break

        return data

    def find_cheapest_hours(
        self,
        hours_needed: int,
        within_hours: int = 24,
        prefer_consecutive: bool = False,
    ) -> List[PricePoint]:
        """Find the cheapest price slots covering ``hours_needed`` hours.

        Args:
            hours_needed: Charging time to cover, in hours. On sub-hourly
                markets (Amber 30-min, Tibber Pulse 15-min) this selects
                proportionally more slots — ``hours_needed`` slots would
                only cover a half/quarter of the requested time and the
                EV/battery planners would silently under-schedule
                (#274/H2).
            within_hours: Time horizon to look ahead. (Used to be a slot
                count, which shrank the lookahead to 6h on 15-min data.)
            prefer_consecutive: When True, return the cheapest *contiguous*
                block (lowest summed price) instead of the globally-cheapest
                scattered slots. Block-wise scheduling (#247) avoids
                fragmenting a charge across the night and reduces
                start/stop cycling on the charger. Falls back to scattered
                selection when fewer slots than needed are available.
        """
        prices = self._read_prices_list()
        now = dt_util.now()
        interval = self._detect_interval(prices)
        # Include the slot currently in progress (started <= now <
        # start+interval) so "is now cheap?" works at the top of a slot,
        # but not slots that already ended (the old fixed 1-hour lookback
        # included up to 3 stale slots on 15-min markets).
        horizon = now + timedelta(hours=within_hours)
        future_prices = [
            p for p in prices
            if p.timestamp + interval > now and p.timestamp <= horizon
        ]

        slots_needed = (
            math.ceil(hours_needed * 3600 / interval.total_seconds())
            if hours_needed > 0 else 0
        )
        if not future_prices or len(future_prices) < slots_needed:
            return future_prices

        if prefer_consecutive and slots_needed > 0:
            ordered = sorted(future_prices, key=lambda p: p.timestamp)
            best_start, best_sum = 0, None
            for i in range(0, len(ordered) - slots_needed + 1):
                window = ordered[i:i + slots_needed]
                total = sum(p.price for p in window)
                if best_sum is None or total < best_sum:
                    best_sum, best_start = total, i
            return ordered[best_start:best_start + slots_needed]

        # Cheapest scattered slots (default, back-compat behaviour).
        sorted_by_price = sorted(future_prices, key=lambda p: p.price)
        return sorted(sorted_by_price[:slots_needed], key=lambda p: p.timestamp)

    def get_schedule_for_day(
        self, date: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Generate tariff schedule blocks from dynamic price forecast.

        Returns blocks with both the legacy ``tariff`` field (HT/NT, for the
        existing schedule card) and the richer ``level`` field (5-tier
        cheap/normal/expensive classification, for sem-today-plan-card and
        sem-price-card consumers — #282).

        Each block also carries ``avg_price`` so cards can show "0.10 CHF avg"
        without re-querying the curve.

        Returns:
            ``[{"start": "HH:MM", "end": "HH:MM", "tariff": "HT"|"NT",
                "level": "cheap"|..., "avg_price": float}, ...]``
        """
        prices = self._read_prices_list()
        target_date = (date or dt_util.now()).date()
        # #359-class bug: compare (and later label) in HA's local tz.
        # Nordpool emits UTC timestamps — a naked .date() shifts the
        # schedule by the UTC offset and drops the late-evening blocks.
        today_prices = sorted(
            [p for p in prices if _local_date(p.timestamp) == target_date],
            key=lambda p: p.timestamp,
        )
        if not today_prices:
            return []

        _CHEAP = (PriceLevel.NEGATIVE, PriceLevel.VERY_CHEAP, PriceLevel.CHEAP)

        def _coarse_level(level: PriceLevel) -> str:
            """Collapse the 5-tier scale into 3 user-facing bands.

            cheap-ish → ``cheap``; expensive-ish → ``expensive``; rest → ``normal``.
            """
            if level in _CHEAP:
                return "cheap"
            if level in (PriceLevel.EXPENSIVE, PriceLevel.VERY_EXPENSIVE):
                return "expensive"
            return "normal"

        schedule: List[Dict[str, Any]] = []
        current_level: Optional[str] = None
        block_start: Optional[str] = None
        block_prices: List[float] = []

        def _close_block(end_time_str: str) -> None:
            if current_level is not None and block_start is not None and block_prices:
                avg = sum(block_prices) / len(block_prices)
                schedule.append({
                    "start": block_start, "end": end_time_str,
                    "tariff": "NT" if current_level == "cheap" else "HT",
                    "level": current_level,
                    "avg_price": round(avg, 4),
                })

        for p in today_prices:
            lvl = _coarse_level(p.level)
            local_ts = _as_local(p.timestamp)
            time_str = f"{local_ts.hour:02d}:{local_ts.minute:02d}"
            if lvl != current_level:
                _close_block(time_str)
                block_start = time_str
                current_level = lvl
                block_prices = [p.price]
            else:
                block_prices.append(p.price)

        _close_block("24:00")
        return schedule


class SpotMarketProvider(DynamicTariffProvider):
    """EPEX SPOT market provider.

    Extends DynamicTariffProvider with spot-market specific features
    like negative price detection and day-ahead price availability.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        price_entity: Optional[str] = None,
        export_rate: float = 0.075,
        grid_fees: float = 0.10,
        taxes: float = 0.05,
        currency: str = "EUR",
    ):
        super().__init__(
            hass,
            price_entity=price_entity,
            # Keyword args: positional would land export_rate in the
            # forecast_entity slot and corrupt the price forecast (#274/H4).
            export_rate=export_rate,
            cheap_threshold=0.05,  # 5 ct/kWh
            expensive_threshold=0.25,  # 25 ct/kWh
            currency=currency,
        )
        self.grid_fees = grid_fees
        self.taxes = taxes

    def get_current_import_rate(self) -> float:
        """Spot price + grid fees + taxes."""
        spot_price = self._read_current_price()
        return max(0, spot_price + self.grid_fees + self.taxes)

    def has_negative_prices(self, hours: int = 24) -> bool:
        """Check if negative prices are expected in the next N hours."""
        prices = self._read_prices_list()
        now = dt_util.now()
        future = [p for p in prices if p.timestamp > now][:hours]
        return any(p.price < 0 for p in future)
