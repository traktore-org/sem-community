"""Calendar-based tariff provider for SEM (#25).

Allows users to define weekly HT/NT time windows (e.g., EKZ Zurich:
HT Mon-Fri 07:00-20:00, Sat 07:00-13:00, NT all other times).

Supports:
- Custom rules with per-day time windows
- Swiss provider presets (EKZ, BKW, CKW)
- Optional holiday entity (binary_sensor) for holiday-as-NT
- HA Schedule helper entity as alternative input
"""
import logging
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .tariff_provider import TariffProvider, TariffData, PriceLevel

_LOGGER = logging.getLogger(__name__)

# Swiss provider presets
TARIFF_PRESETS = {
    "flat": {
        "name": "Flat Rate (no HT/NT)",
        "rules": [],
    },
    "ekz": {
        "name": "EKZ (Zurich)",
        "rules": [
            {"days": [0, 1, 2, 3, 4], "start": "07:00", "end": "20:00", "tariff": "ht"},
            {"days": [5], "start": "07:00", "end": "13:00", "tariff": "ht"},
        ],
    },
    "bkw": {
        "name": "BKW (Bern)",
        "rules": [
            {"days": [0, 1, 2, 3, 4, 5, 6], "start": "07:00", "end": "21:00", "tariff": "ht"},
        ],
    },
    "ckw": {
        "name": "CKW (Luzern)",
        "rules": [
            {"days": [0, 1, 2, 3, 4], "start": "07:00", "end": "20:00", "tariff": "ht"},
        ],
    },
    "ewz": {
        "name": "ewz (Zurich City)",
        "rules": [
            {"days": [0, 1, 2, 3, 4], "start": "06:00", "end": "22:00", "tariff": "ht"},
            {"days": [5], "start": "06:00", "end": "13:00", "tariff": "ht"},
        ],
    },
}


class CalendarTariffProvider(TariffProvider):
    """Tariff provider with user-defined weekly HT/NT schedule.

    Rules are evaluated top-to-bottom; first match wins.
    If no rule matches, `default_tariff` is used (default: "nt").
    """

    def __init__(
        self,
        hass: HomeAssistant,
        peak_rate: float = 0.35,
        off_peak_rate: float = 0.22,
        export_rate: float = 0.075,
        rules: Optional[List[Dict[str, Any]]] = None,
        default_tariff: str = "off_peak",
        holiday_entity: Optional[str] = None,
        schedule_entity: Optional[str] = None,
        currency: str = "CHF",
        # Backward compat kwargs
        ht_rate: float = None,
        nt_rate: float = None,
    ):
        self.hass = hass
        self.peak_rate = ht_rate if ht_rate is not None else peak_rate
        self.off_peak_rate = nt_rate if nt_rate is not None else off_peak_rate
        self.export_rate = export_rate
        self.default_tariff = default_tariff
        self.holiday_entity = holiday_entity
        self.schedule_entity = schedule_entity
        self.currency = currency

        # Parse rules into (days, start_time, end_time, tariff) tuples
        self._rules: List[tuple] = []
        for rule in (rules or []):
            days = rule.get("days", [])
            start = self._parse_time(rule.get("start", "00:00"))
            end = self._parse_time(rule.get("end", "00:00"))
            tariff = rule.get("tariff", "peak")
            self._rules.append((days, start, end, tariff))

        if self._rules:
            _LOGGER.info(
                "Calendar tariff: %d rules, peak=%.4f, off_peak=%.4f %s",
                len(self._rules), self.peak_rate, self.off_peak_rate, currency,
            )
        elif schedule_entity:
            _LOGGER.info(
                "Calendar tariff using schedule entity: %s", schedule_entity,
            )

    @staticmethod
    def _parse_time(s: str) -> time:
        """Parse "HH:MM" string to time object."""
        parts = s.split(":")
        return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)

    def _is_holiday(self) -> bool:
        """Check if today is a holiday (via binary_sensor)."""
        if not self.holiday_entity:
            return False
        state = self.hass.states.get(self.holiday_entity)
        if state and state.state == "on":
            return True
        return False

    def _get_tariff_at(self, when: datetime) -> str:
        """Determine tariff (ht/nt) at a given time.

        Returns "ht" or "nt".
        """
        # Holiday override
        if self.holiday_entity and self._is_holiday():
            return "nt"

        # HA Schedule helper mode
        if self.schedule_entity:
            state = self.hass.states.get(self.schedule_entity)
            if state:
                # Schedule helper: "on" = HT period, "off" = NT period
                return "ht" if state.state == "on" else "nt"
            return self.default_tariff

        # Rule-based evaluation
        dow = when.weekday()  # 0=Mon, 6=Sun
        current_time = when.time()

        for days, start, end, tariff in self._rules:
            if dow not in days:
                continue
            # Handle same-day windows (start < end)
            if start <= end:
                if start <= current_time < end:
                    return tariff
            else:
                # Overnight window (e.g., 22:00-06:00)
                if current_time >= start or current_time < end:
                    return tariff

        return self.default_tariff

    def _is_high_tariff(self, when: Optional[datetime] = None) -> bool:
        """Check if given time is in high tariff period."""
        now = when or dt_util.now()
        return self._get_tariff_at(now) == "ht"

    def get_current_import_rate(self) -> float:
        return self.peak_rate if self._is_high_tariff() else self.off_peak_rate

    def get_current_export_rate(self) -> float:
        return self.export_rate

    def get_price_level(self) -> PriceLevel:
        return PriceLevel.NORMAL if self._is_high_tariff() else PriceLevel.CHEAP

    def get_price_at(self, when: datetime) -> Optional[float]:
        return self.peak_rate if self._is_high_tariff(when) else self.off_peak_rate

    def get_tariff_data(self) -> TariffData:
        now = dt_util.now()
        is_ht = self._is_high_tariff(now)

        data = TariffData(
            current_import_rate=self.peak_rate if is_ht else self.off_peak_rate,
            current_export_rate=self.export_rate,
            price_level=PriceLevel.NORMAL if is_ht else PriceLevel.CHEAP,
            currency=self.currency,
            provider="calendar",
            is_dynamic=False,
            today_min_price=self.off_peak_rate,
            today_max_price=self.peak_rate,
            today_avg_price=(self.peak_rate + self.off_peak_rate) / 2,
        )

        # Calculate next tariff transition
        if is_ht:
            # Find when current HT period ends (= next NT start)
            next_change = self._find_next_transition(now, "nt")
            if next_change:
                data.next_cheap_window_start = next_change
        else:
            # Find when current NT period ends (= next HT start)
            next_change = self._find_next_transition(now, "ht")
            if next_change:
                data.next_expensive_window_start = next_change

        return data

    def _find_next_transition(self, from_dt: datetime, to_tariff: str) -> Optional[datetime]:
        """Find the next time the tariff changes to the specified type."""
        # Check every 15 minutes for the next 48 hours
        check = from_dt
        current = self._get_tariff_at(check)
        for _ in range(192):  # 48h * 4 per hour
            check += timedelta(minutes=15)
            new_tariff = self._get_tariff_at(check)
            if new_tariff == to_tariff and new_tariff != current:
                return check
            current = new_tariff
        return None

    def get_schedule_for_day(self, date: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Get the complete schedule for a given day.

        Returns list of blocks: [{"start": "07:00", "end": "20:00", "tariff": "ht"}, ...]
        Used by the dashboard schedule card for visualization.
        """
        day = date or dt_util.now()
        blocks = []
        current_tariff = None
        block_start = None

        for hour in range(24):
            for minute in (0, 30):
                check_time = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
                tariff = self._get_tariff_at(check_time)
                if tariff != current_tariff:
                    if current_tariff is not None:
                        blocks.append({
                            "start": block_start.strftime("%H:%M"),
                            "end": check_time.strftime("%H:%M"),
                            "tariff": current_tariff,
                        })
                    current_tariff = tariff
                    block_start = check_time

        # Close last block
        if current_tariff is not None and block_start is not None:
            blocks.append({
                "start": block_start.strftime("%H:%M"),
                "end": "24:00",
                "tariff": current_tariff,
            })

        return blocks
