"""Calendar-based tariff provider for SEM (#25).

Allows users to define weekly HT/NT time windows (e.g., EKZ Zurich:
HT Mon-Fri 07:00-20:00, Sat 07:00-13:00, NT all other times).

Supports:
- Custom rules with per-day time windows
- Swiss provider presets (EKZ, BKW, CKW)
- Optional holiday entity (binary_sensor) for holiday-as-NT
- HA Schedule helper entity as alternative input — the one the options
  form offers (#1040); its blocks are the peak (HT) hours
"""
import logging
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .tariff_provider import (
    LEVEL_FLAT, LEVEL_NO_PRICES, TariffProvider, TariffData, PriceLevel,
)

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


def _day_numbers(value: object) -> List[int]:
    """A rule's weekday list as integers 0-6, silently dropping the rest.

    (#994) Storage and YAML both hand back ``["0", "1"]`` readily enough,
    and ``dow not in ["0"]`` is True for every day of the week — so the
    whole rule was ignored and the install lost its levels without a word.
    ``None`` used to raise TypeError out of the update loop.
    """
    out: List[int] = []
    for item in (value or []):
        try:
            day = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= day <= 6:
            out.append(day)
    return out


# The Schedule helper's day keys, in ``datetime.weekday()`` order.
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday")


def _block_edge(value: object) -> Optional[time]:
    """One edge of a Schedule helper block as a ``time``, or ``None``.

    (#1040) ``schedule.get_schedule`` hands back ``time`` objects in
    process and ISO strings over JSON. The end of the day is ``time.max``
    — ``"23:59:59.999999"`` in JSON — or ``"24:00:00"`` in YAML.
    """
    if isinstance(value, time):
        return value
    text = str(value or "").strip()
    if text.startswith("24:00") and not text[5:].strip(":0."):
        return time.max
    try:
        return time.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def timetable_from_schedule(week: object) -> Optional[List[tuple]]:
    """(#1040) A Schedule helper's week as ``(weekday, start, end)`` blocks.

    ``None`` when the answer is not a week we understand — not a dict, or
    a block we cannot read — so "could not read" is never mistaken for
    "no peak hours" (#925). A block the helper itself would refuse (end
    not after start) is skipped.
    """
    if not isinstance(week, dict):
        return None
    blocks: List[tuple] = []
    for day, key in enumerate(_WEEKDAYS):
        for block in (week.get(key) or []):
            if not isinstance(block, dict):
                return None
            start = _block_edge(block.get("from"))
            end = _block_edge(block.get("to"))
            if start is None or end is None:
                return None
            if end <= start:
                continue
            blocks.append((day, start, end))
    return blocks


def _tariff_word(value: object) -> str:
    """A rule's tariff word, normalised: ``ht`` or ``nt``.

    (#994) Readers disagreed about case and about which spellings count,
    so the table now holds one of two words and nothing downstream guesses.
    """
    return "ht" if str(value or "").strip().lower() in ("ht", "peak") else "nt"


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
        self.default_tariff = _tariff_word(default_tariff)
        self.holiday_entity = holiday_entity
        self.schedule_entity = schedule_entity
        self.currency = currency
        # (#1040) The Schedule helper's state only says what NOW is. The
        # day strip, the next change and the battery break-even ask about
        # other hours, so the helper's week is read into this table by
        # ``async_refresh_service_prices``. ``None`` = not read yet.
        self._timetable: Optional[List[tuple]] = None
        self._timetable_stamp: Any = None
        self._timetable_read_at: Optional[datetime] = None
        self._timetable_failed_at: Optional[datetime] = None

        # Parse rules into (days, start_time, end_time, tariff) tuples
        self._rules: List[tuple] = []
        for rule in (rules or []):
            # (#994) Normalise HERE, once. `_get_tariff_at` returned the
            # rule's word verbatim and `_is_high_tariff` compared it with a
            # case-SENSITIVE ``== "ht"``, so a rule written ``"HT"`` was
            # never high tariff at the decision site while every other
            # reader lower-cased and thought it was — a level of CHEAP,
            # forever, on a day that does have a peak window. And a
            # ``"days": null`` raised TypeError out of the update loop.
            days = _day_numbers(rule.get("days"))
            start = self._parse_time(rule.get("start", "00:00"))
            end = self._parse_time(rule.get("end", "00:00"))
            tariff = _tariff_word(rule.get("tariff", "peak"))
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

    # How often the helper's week is read again when nothing signals a change.
    TIMETABLE_REFRESH = timedelta(minutes=15)

    async def async_refresh_service_prices(self) -> bool:
        """(#1040) Read the Schedule helper's week via ``schedule.get_schedule``.

        Same hook as the Nord Pool curve: the coordinator calls it on the
        event loop once per cycle and this method throttles itself. It
        reads again when the helper's state was written (an edit, or an
        on/off change) and every ``TIMETABLE_REFRESH`` otherwise.

        Returns True when a fresh week was stored. A failed read keeps the
        last good week.
        """
        if not self.schedule_entity or self.hass is None:
            return False
        # Only a Schedule helper has a week. A hand-written binary_sensor
        # or input_boolean answers by state alone.
        if not str(self.schedule_entity).startswith("schedule."):
            return False
        services = getattr(self.hass, "services", None)
        if services is None or not services.has_service("schedule", "get_schedule"):
            return False
        state = self.hass.states.get(self.schedule_entity)
        if state is None:
            return False
        now = dt_util.now()
        stamp = getattr(state, "last_updated", None)
        if (
            self._timetable is not None
            and stamp == self._timetable_stamp
            and self._timetable_read_at is not None
            and now - self._timetable_read_at < self.TIMETABLE_REFRESH
        ):
            return False
        if (
            self._timetable_failed_at is not None
            and now - self._timetable_failed_at < self.TIMETABLE_REFRESH
        ):
            return False
        try:
            resp = await services.async_call(
                "schedule", "get_schedule",
                {"entity_id": self.schedule_entity},
                blocking=True, return_response=True,
            )
        except Exception as err:  # noqa: BLE001 — a helper we cannot read must not stop the cycle
            self._timetable_failed_at = now
            _LOGGER.warning(
                "Calendar tariff: cannot read schedule %s: %s",
                self.schedule_entity, err,
            )
            return False
        week = timetable_from_schedule(
            resp.get(self.schedule_entity) if isinstance(resp, dict) else None)
        if week is None:
            self._timetable_failed_at = now
            _LOGGER.warning(
                "Calendar tariff: schedule %s returned no week",
                self.schedule_entity,
            )
            return False
        self._timetable = week
        self._timetable_stamp = stamp
        self._timetable_read_at = now
        self._timetable_failed_at = None
        return True

    @staticmethod
    def _parse_time(s: str) -> time:
        """Parse "HH:MM" string to time object."""
        parts = s.split(":")
        return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)

    def _holiday_readable(self) -> bool:
        """(#994) Can the holiday question be ASKED right now?

        Configured-but-unreadable is its own answer (#925). A holiday is
        off-peak from midnight to midnight, so while SEM cannot tell, it
        cannot tell whether a peak hour is reachable today either — and
        ``_is_holiday`` answering a flat False turned "I could not ask"
        into "it is a normal working day", complete with a level.
        """
        if not self.holiday_entity:
            return True
        state = self.hass.states.get(self.holiday_entity)
        return bool(state) and state.state not in ("unknown", "unavailable")

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
            word = self._schedule_word(when)
            # (#994) A helper that will not read is not a helper saying NT.
            # It used to answer "off" → NT → CHEAP, all day, on an input
            # nobody could see. Readers ask ``_known_at`` before trusting
            # this fallback.
            return word if word is not None else self.default_tariff

        # Rule-based evaluation
        dow = when.weekday()  # 0=Mon, 6=Sun
        current_time = when.time()

        for days, start, end, tariff in self._rules:
            if dow not in days:
                continue
            if start == end:
                # A zero-width window can never contain a moment. It used
                # to be counted as a reachable HT period all the same.
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

    # How far a caller's "now" may lag ours and still be "now".
    _NOW_SLACK = timedelta(seconds=60)

    def _state_covers(self, when: datetime, state: Any) -> bool:
        """(#1040) Does the helper's state speak for ``when``?

        "on"/"off" is true from now until the helper's ``next_event``; it
        says nothing about any other hour.
        """
        now = dt_util.now()
        try:
            nxt = (getattr(state, "attributes", None) or {}).get("next_event")
            if isinstance(nxt, str):
                nxt = dt_util.parse_datetime(nxt)
            if not isinstance(nxt, datetime):
                nxt = None
            if nxt is not None and when >= nxt:
                return False    # past the next edge, the state is old news
            # A caller's "now" was taken a moment before ours, never after.
            if timedelta(0) <= now - when <= self._NOW_SLACK:
                return True
            return nxt is not None and now <= when
        except (TypeError, ValueError):     # naive vs aware, bad timestamp
            return False

    def _schedule_word(self, when: datetime) -> Optional[str]:
        """(#1040) ``ht``/``nt`` from the Schedule helper, or ``None``.

        The state answers for its own window, the helper's week for every
        other hour. Before the week is read, other hours are unknown — the
        state copied to every hour gave one block all day on the strip and
        no spread for the battery break-even (class 86).
        """
        state = self.hass.states.get(self.schedule_entity)
        if not state or state.state in ("unknown", "unavailable"):
            return None
        if self._state_covers(when, state):
            return "ht" if state.state == "on" else "nt"
        if self._timetable is not None:
            return self._timetable_word(when)
        return None

    def _known_at(self, when: datetime) -> bool:
        """(#1040) Can this calendar say anything about ``when``?"""
        if not self.schedule_entity:
            return True
        return self._schedule_word(when) is not None

    def _timetable_word(self, when: datetime) -> str:
        """(#1040) ``ht`` inside one of the helper's blocks, else ``nt``.

        Same rule as the helper itself: start included, end excluded, and
        a block ending at 24:00 runs to midnight.
        """
        dow = when.weekday()
        now_t = when.time()
        for day, start, end in (self._timetable or []):
            if day != dow or now_t < start:
                continue
            if now_t < end or end == time.max:
                return "ht"
        return "nt"

    def _is_high_tariff(self, when: Optional[datetime] = None) -> bool:
        """Check if given time is in high tariff period."""
        now = when or dt_util.now()
        return _tariff_word(self._get_tariff_at(now)) == "ht"

    def get_current_import_rate(self) -> float:
        # (#1077) as a value; all value fields at 0 = the rate itself
        return self._import_value(
            self.peak_rate if self._is_high_tariff() else self.off_peak_rate)

    def get_current_export_rate(self) -> float:
        return self._export_value(self.export_rate)

    def get_current_spot_export_rate(self) -> float:
        return self.export_rate

    def _rates_differ(self) -> bool:
        """(#994) Is there anything to compare? Relative, so the answer is
        the same in CHF, in cents and in rupees (#359/#417/#549)."""
        hi, lo = float(self.peak_rate), float(self.off_peak_rate)
        mean = (abs(hi) + abs(lo)) / 2.0
        if mean <= 0.0:
            return abs(hi - lo) > 1e-9
        return (abs(hi - lo) / mean) > 0.005

    def _ht_can_occur(self, when: Optional[datetime] = None) -> bool:
        """(#994) …and can this calendar be in high tariff ON THAT DAY?

        With no rules — which is every install today, because
        ``coordinator.py`` never passed a schedule, and also the deliberate
        "Flat Rate (no HT/NT)" preset — ``_get_tariff_at`` always returns
        the ``off_peak`` default, so this provider answered CHEAP
        unconditionally, forever, whatever rates the owner configured. A
        level with no reachable alternative is not a comparison.

        The DAY matters, and the first version of this check forgot it:
        asking whether an HT rule exists anywhere in the weekly table is not
        asking whether one can arrive today. Three of the five shipped
        presets have days with no HT rule at all — EKZ and ewz cover Mon–Sat
        morning, CKW only Mon–Fri — so on a Sunday they reproduced exactly
        the incident this issue is named for, through the calendar instead
        of the clock. ``StaticTariffProvider._both_rates_occur`` got this
        right from the start; this is the same question, asked of a rule
        table instead of a weekday constant.
        """
        now = when or dt_util.now()
        # A holiday is NT from midnight to midnight, whatever the table
        # says — ``_get_tariff_at`` checks it first and the rule scan never
        # knew, so a holiday published a peak/off-peak spread it could not
        # reach.
        if self.holiday_entity and not self._holiday_readable():
            return False        # cannot ask → cannot claim a peak hour
        if self.holiday_entity and self._is_holiday():
            return False
        # A Schedule helper install has no rules at all, so reading the
        # rule table silenced this entire input mode. Until its week is
        # read, the helper's existence is the claim that high tariff
        # happens.
        if self.schedule_entity:
            st = self.hass.states.get(self.schedule_entity)
            if not st or st.state in ("unknown", "unavailable"):
                return False
            # The state is the freshest word on its own window — a week read
            # before an edit must not say "no peak today" while it is on.
            if st.state == "on" and self._state_covers(now, st):
                return True
            if self._timetable is None:
                return True     # ``_known_at`` limits it to the state's window
            # (#1040) With the week read, ask about THIS day (class 104):
            # a helper with no block on Sunday has one price on Sunday.
            # The week, not the state, is what decides every hour but now —
            # and a probe a few seconds before a block starts must not read
            # the state's "off" as "no block today".
            return any(dow == now.weekday() for dow, _s, _e in self._timetable)
        if not self._rules:
            return self.default_tariff == "ht"
        # Otherwise: ask the function that DECIDES, at every boundary the
        # rules name, instead of re-deriving the answer from the table.
        # Re-deriving is what produced the defect this method exists to
        # fix (bug class 104), one level down: a mis-cased word, a
        # zero-width window and a holiday each made the two disagree.
        # A half-open window always contains its own start, so probing
        # every rule's start plus midnight is exact, not a sample.
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        probes = {day}
        for _days, start, end, _t in self._rules:
            probes.add(day.replace(hour=start.hour, minute=start.minute))
            probes.add(day.replace(hour=end.hour, minute=end.minute))
        return any(_tariff_word(self._get_tariff_at(p)) == "ht"
                   for p in probes)

    def _comparison_stands(self, when: Optional[datetime] = None) -> bool:
        now = when or dt_util.now()
        return (self._rates_differ() and self._known_at(now)
                and self._ht_can_occur(now))

    def get_price_level(self) -> Optional[PriceLevel]:
        """(#994) ``None`` when nothing was compared."""
        if not self._comparison_stands():
            return None
        return PriceLevel.NORMAL if self._is_high_tariff() else PriceLevel.CHEAP

    def get_price_at(self, when: datetime) -> Optional[float]:
        # (#1040) An hour nobody can speak for has no price; the battery
        # break-even falls back to the configured rates.
        if not self._known_at(when):
            return None
        return self._import_value(
            self.peak_rate if self._is_high_tariff(when) else self.off_peak_rate)

    def get_price_level_at(self, when: datetime) -> "PriceLevel | None":
        # Same calendar rule get_price_level applies now: NT = CHEAP (#638),
        # and the same refusal when nothing distinguishes the hours (#994)
        # — asked of the day BEING classified, not of today.
        if not self._comparison_stands(when):
            return None
        return (PriceLevel.NORMAL if self._is_high_tariff(when)
                else PriceLevel.CHEAP)

    def _ht_occurs_in_week(self, when: datetime) -> bool:
        """(#1310) Can a peak hour come on any day of the week from ``when``?

        The same question ``_ht_can_occur`` asks of one day, asked of seven.
        """
        return any(self._ht_can_occur(when + timedelta(days=d))
                   for d in range(7))

    def get_rate_level_at(self, when: datetime) -> "PriceLevel | None":
        # (#1310) Asked of the week, not of the day. A weekend with no peak
        # block is all at the off-peak rate, the same rate as Monday 03:00.
        # ``get_price_level_at`` refuses that day on purpose (#994), and the
        # plan card drew Monday 00:00 as cheap and Sunday 22:00 not.
        if not (self._rates_differ() and self._known_at(when)
                and self._ht_occurs_in_week(when)):
            return None
        return (PriceLevel.NORMAL if self._is_high_tariff(when)
                else PriceLevel.CHEAP)

    def get_tariff_data(self) -> TariffData:
        now = dt_util.now()
        is_ht = self._is_high_tariff(now)

        # (#1077) the same values the current rate is published in
        peak_v = self._import_value(self.peak_rate)
        off_v = self._import_value(self.off_peak_rate)
        data = TariffData(
            current_import_rate=peak_v if is_ht else off_v,
            current_export_rate=self.get_current_export_rate(),
            price_level=self.get_price_level(),
            currency=self.currency,
            provider="calendar",
            is_dynamic=False,
            classifier_path=("calendar_schedule" if self._comparison_stands()
                             else "calendar_no_comparison"),
            # A calendar always HAS its two rates and its rule table; when
            # it declines, the day simply holds one price. (#1040) A
            # Schedule helper that cannot be read is not one price — it is
            # no answer.
            level_absence=(LEVEL_FLAT if self._known_at(now)
                           else LEVEL_NO_PRICES),
            # (#994) with no HT rule REACHABLE TODAY the day has ONE price;
            # reporting the rate table's two would tell every consumer —
            # and ``variation_known``, which reads exactly these two fields
            # — to wait for an hour this day can never reach.
            today_min_price=(off_v if self._comparison_stands()
                             else self.get_current_import_rate()),
            today_max_price=(peak_v if self._comparison_stands()
                             else self.get_current_import_rate()),
            today_avg_price=((peak_v + off_v) / 2
                             if self._comparison_stands()
                             else self.get_current_import_rate()),
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

        self._value_fields(data)
        return data

    def _find_next_transition(self, from_dt: datetime, to_tariff: str) -> Optional[datetime]:
        """Find the next time the tariff changes to the specified type."""
        # Check every 15 minutes for the next 48 hours, on the quarter
        # hours where windows begin. (#1040) Stepping from an odd minute
        # reported a 05:00 change as 05:13.
        current = self._get_tariff_at(from_dt)
        check = from_dt.replace(minute=from_dt.minute - from_dt.minute % 15,
                                second=0, microsecond=0)
        for _ in range(192):  # 48h * 4 per hour
            check += timedelta(minutes=15)
            if not self._known_at(check):
                return None     # (#1040) past what the helper can tell
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
        # (#994) A day with nothing to compare is ONE block with no level.
        # This method never asked, so a flat calendar — equal rates, or a
        # preset with no peak window today — still handed the card a full
        # day of alternating NT/HT stripes to paint, right beside a sensor
        # correctly reading `flat`. The strip is the picture users check
        # first, and it was telling the older story.
        # (#1040) …and a Schedule helper whose week is not read yet says
        # nothing about the rest of the day: no stripes, and not "flat".
        unread = bool(self.schedule_entity) and self._timetable is None
        if unread or not self._comparison_stands(day):
            return [{
                "start": "00:00", "end": "24:00", "tariff": None,
                "level": (LEVEL_NO_PRICES
                          if unread or not self._known_at(day)
                          else LEVEL_FLAT),
                "avg_price": round(self.get_current_import_rate(), 4),
            }]

        blocks = []
        current_tariff = None
        block_start = None

        def _close(end_str: str) -> None:
            blocks.append({
                "start": block_start.strftime("%H:%M"),
                "end": end_str,
                "tariff": current_tariff,
                # The card reads `level` first and falls back to the
                # legacy HT/NT word; give it both so it never has to.
                "level": "normal" if current_tariff == "ht" else "cheap",
                "avg_price": round(self._import_value(
                    self.peak_rate if current_tariff == "ht"
                    else self.off_peak_rate), 4),
            })

        for hour in range(24):
            for minute in (0, 30):
                check_time = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
                tariff = self._get_tariff_at(check_time)
                if tariff != current_tariff:
                    if current_tariff is not None:
                        _close(check_time.strftime("%H:%M"))
                    current_tariff = tariff
                    block_start = check_time

        # Close last block
        if current_tariff is not None and block_start is not None:
            _close("24:00")

        return blocks
