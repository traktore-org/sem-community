"""Dynamic electricity tariff providers for Solar Energy Management.

Supports:
- StaticTariffProvider: Fixed HT/NT rates (current behavior)
- DynamicTariffProvider: Reads from Tibber, Nordpool, or aWATTar HA integrations
- SpotMarketProvider: EPEX SPOT prices via Tibber/aWATTar HACS

Used by EnergyCalculator for accurate cost calculations and by
SurplusController for price-responsive device control.
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tariff_current_import_rate": round(self.current_import_rate, 4),
            "tariff_current_export_rate": round(self.current_export_rate, 4),
            "tariff_price_level": self.price_level.value,
            "tariff_currency": self.currency,
            "tariff_provider": self.provider,
            "tariff_is_dynamic": self.is_dynamic,
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
        ht_rate: float = 0.3387,   # /kWh daytime incl. VAT
        nt_rate: float = 0.3387,   # /kWh nighttime incl. VAT (default flat rate)
        export_rate: float = 0.075,  # /kWh feed-in
        ht_start: int = 7,   # HT starts at 07:00
        ht_end: int = 20,    # HT ends at 20:00
        currency: str = "CHF",
    ):
        self.ht_rate = ht_rate
        self.nt_rate = nt_rate
        self.export_rate = export_rate
        self.ht_start = ht_start
        self.ht_end = ht_end
        self.currency = currency

    def _is_high_tariff(self, when: Optional[datetime] = None) -> bool:
        """Check if current time is in high tariff period."""
        now = when or dt_util.now()
        # Weekend is always NT
        if now.weekday() >= 5:
            return False
        return self.ht_start <= now.hour < self.ht_end

    def get_current_import_rate(self) -> float:
        return self.ht_rate if self._is_high_tariff() else self.nt_rate

    def get_current_export_rate(self) -> float:
        return self.export_rate

    def get_price_level(self) -> PriceLevel:
        if self._is_high_tariff():
            return PriceLevel.NORMAL
        return PriceLevel.CHEAP

    def get_price_at(self, when: datetime) -> Optional[float]:
        return self.ht_rate if self._is_high_tariff(when) else self.nt_rate

    def get_tariff_data(self) -> TariffData:
        now = dt_util.now()
        data = TariffData(
            current_import_rate=self.get_current_import_rate(),
            current_export_rate=self.export_rate,
            price_level=self.get_price_level(),
            currency=self.currency,
            provider="static",
            is_dynamic=False,
            today_min_price=self.nt_rate,
            today_max_price=self.ht_rate,
            today_avg_price=(self.ht_rate + self.nt_rate) / 2,
        )

        # Calculate next cheap window (next NT period)
        if self._is_high_tariff():
            # Next NT starts at ht_end today
            next_nt = now.replace(hour=self.ht_end, minute=0, second=0, microsecond=0)
            data.next_cheap_window_start = next_nt
            # NT ends at ht_start next day
            data.next_cheap_window_end = (next_nt + timedelta(days=1)).replace(
                hour=self.ht_start
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
        export_rate: float = 0.075,
        cheap_threshold: float = 0.15,
        expensive_threshold: float = 0.35,
        currency: str = "CHF",
    ):
        self.hass = hass
        self.export_rate = export_rate
        self.cheap_threshold = cheap_threshold
        self.expensive_threshold = expensive_threshold
        self.currency = currency
        self._price_entity = price_entity
        self._provider_name = "unknown"
        self._prices_cache: List[PricePoint] = []
        self._last_cache_update: Optional[datetime] = None

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

        # Try Nordpool
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
        """Read current price from the price entity."""
        if not self._price_entity:
            self.detect_provider()
        if not self._price_entity:
            return 0.30  # Fallback to default

        state = self.hass.states.get(self._price_entity)
        if state and state.state not in ("unknown", "unavailable"):
            try:
                return float(state.state)
            except (ValueError, TypeError):
                pass
        return 0.30

    def _read_prices_list(self) -> List[PricePoint]:
        """Read upcoming prices from entity attributes."""
        if not self._price_entity:
            return []

        state = self.hass.states.get(self._price_entity)
        if not state:
            return []

        prices = []
        attrs = state.attributes

        # Tibber: prices_today, prices_tomorrow attributes
        for key in ("prices_today", "prices_tomorrow", "today", "tomorrow"):
            price_list = attrs.get(key, [])
            if isinstance(price_list, list):
                for item in price_list:
                    if isinstance(item, dict):
                        ts = item.get("start", item.get("startsAt"))
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

        return sorted(prices, key=lambda p: p.timestamp)

    def _classify_price(self, price: float) -> PriceLevel:
        """Classify a price into levels."""
        if price < 0:
            return PriceLevel.NEGATIVE
        if price < self.cheap_threshold * 0.5:
            return PriceLevel.VERY_CHEAP
        if price < self.cheap_threshold:
            return PriceLevel.CHEAP
        if price > self.expensive_threshold * 1.5:
            return PriceLevel.VERY_EXPENSIVE
        if price > self.expensive_threshold:
            return PriceLevel.EXPENSIVE
        return PriceLevel.NORMAL

    def get_current_import_rate(self) -> float:
        return self._read_current_price()

    def get_current_export_rate(self) -> float:
        return self.export_rate

    def get_price_level(self) -> PriceLevel:
        return self._classify_price(self._read_current_price())

    def get_price_at(self, when: datetime) -> Optional[float]:
        prices = self._read_prices_list()
        for p in prices:
            if p.timestamp <= when < p.timestamp + timedelta(hours=1):
                return p.price
        return None

    def get_tariff_data(self) -> TariffData:
        current_price = self._read_current_price()
        prices = self._read_prices_list()

        data = TariffData(
            current_import_rate=current_price,
            current_export_rate=self.export_rate,
            price_level=self._classify_price(current_price),
            currency=self.currency,
            provider=self._provider_name,
            is_dynamic=True,
            upcoming_prices=prices[:24],  # Next 24 hours
        )

        if prices:
            today_prices = [p.price for p in prices if p.timestamp.date() == dt_util.now().date()]
            if today_prices:
                data.today_min_price = min(today_prices)
                data.today_max_price = max(today_prices)
                data.today_avg_price = sum(today_prices) / len(today_prices)

            # Find next cheap window
            now = dt_util.now()
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
    ) -> List[PricePoint]:
        """Find the cheapest consecutive or non-consecutive hours.

        Useful for scheduling night charging at cheapest times.
        """
        prices = self._read_prices_list()
        now = dt_util.now()
        future_prices = [p for p in prices if p.timestamp > now][:within_hours]

        if not future_prices or len(future_prices) < hours_needed:
            return future_prices

        # Find cheapest non-consecutive hours
        sorted_by_price = sorted(future_prices, key=lambda p: p.price)
        return sorted(sorted_by_price[:hours_needed], key=lambda p: p.timestamp)


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
            hass, price_entity, export_rate,
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
