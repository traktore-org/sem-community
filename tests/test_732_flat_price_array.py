"""#732 — the tariff parser must accept a FLAT numeric price array.

Reported by @bjpo-abelco (Growatt, DK): a ``dynamic_tariff_entity`` whose
attributes carry a valid 24-element float list under a *recognised* name
(``prices_today`` / ``today`` / ``raw_today``) was silently rejected —
``tariff_parsed_count: 0``, ``tariff_schedule_today: []``,
``classifier_path: percentile_fallback_cache_empty`` — and the #359
"no recognised price-array attribute" warning fired even though the name
WAS recognised. The scalar current price read fine; only the array was
dropped.

Root cause: ``_read_prices_list`` iterated each day-keyed attribute but
only parsed items that were ``dict`` (``{start, value}``-style). A bare
list of floats — which is Nordpool's OWN ``today`` / ``tomorrow`` shape
and the one nearly every template/derivative sensor copies — has ``float``
items, so the whole array was skipped. The warning listed NAMES while the
real gap was the element SHAPE.

Fix: the day-keyed attributes now accept both a list of dicts and a flat
numeric list, anchored at the day's local midnight with the granularity
read from the list length. This suite pins the reporter's exact shape and
guards the whole day-keyed vocabulary so a future refactor cannot re-narrow
it to dict-only without failing CI.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.tariff.tariff_provider import (
    DAY_KEYED_PRICE_ATTRS,
    DynamicTariffProvider,
    _flat_list_base,
    _flat_list_interval,
)


# The keys whose day is unambiguous from the name — those are the ones
# that accept a flat array. Derived from the real vocabulary (never a
# hand-retyped copy, per BUG_CLASSES class 24) so adding/removing a key in
# the parser automatically re-scopes every case below.
FLAT_KEYS = [k for k in DAY_KEYED_PRICE_ATTRS if _flat_list_base(k) is not None]
TOMORROW_KEYS = [k for k in FLAT_KEYS if "tomorrow" in k]
TODAY_KEYS = [k for k in FLAT_KEYS if k not in TOMORROW_KEYS]


def _provider(attributes: dict, current_price: float = 0.25) -> DynamicTariffProvider:
    hass = MagicMock()
    state = MagicMock()
    state.state = str(current_price)
    state.entity_id = "sensor.elpris_sem_inkl_tariffer_2"
    state.attributes = attributes
    hass.states.get = MagicMock(return_value=state)
    hass.states.async_all = MagicMock(return_value=[])
    return DynamicTariffProvider(
        hass,
        price_entity="sensor.elpris_sem_inkl_tariffer_2",
        currency="DKK",
        classification_mode="percentile",
    )


def _local_midnight():
    return dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# The reporter's exact symptom
# ---------------------------------------------------------------------------

class TestReporterSymptom:
    def test_flat_prices_today_now_parses(self):
        """#732: a 24-value flat float list under ``prices_today`` — the
        reporter's ``sensor.elpris_sem_inkl_tariffer_2`` — must populate."""
        values = [round(0.10 + 0.02 * i, 4) for i in range(24)]
        p = _provider({"prices_today": values})
        prices = p._read_prices_list()

        assert len(prices) == 24, (
            "the flat float array under prices_today was dropped — this is "
            "exactly the #732 regression (tariff_parsed_count: 0)"
        )
        assert p._last_parsed_count == 24
        assert p._last_parsed_attribute == "prices_today"
        # No #359 degradation warning when a valid array IS present.
        assert p._no_price_array_warned is False
        # The array is cached for percentile classification.
        assert len(p._prices_cache) == 24

    def test_flat_today_hourly_anchor_and_prices(self):
        """Index i maps to local-midnight + i hours; prices survive intact."""
        values = [round(0.10 + 0.01 * i, 4) for i in range(24)]
        p = _provider({"today": values})
        prices = p._read_prices_list()

        midnight = _local_midnight()
        assert len(prices) == 24
        assert prices[0].timestamp == midnight
        assert prices[1].timestamp == midnight + timedelta(hours=1)
        assert prices[23].timestamp == midnight + timedelta(hours=23)
        assert [pp.price for pp in prices] == values
        assert p._last_parsed_gap_seconds == 3600.0

    def test_warning_still_fires_for_a_genuinely_empty_array(self):
        """The #359 warning must survive for its real case: readable state,
        NO usable array. (A degenerate, non-day-keyed attribute.)"""
        p = _provider({"some_unrelated_attr": "not a curve"})
        prices = p._read_prices_list()
        assert prices == []
        assert p._no_price_array_warned is True


# ---------------------------------------------------------------------------
# Granularity is read from the list length
# ---------------------------------------------------------------------------

class TestGranularity:
    def test_96_values_is_15_minute(self):
        values = [0.20 + 0.001 * i for i in range(96)]
        p = _provider({"prices_today": values})
        prices = p._read_prices_list()
        midnight = _local_midnight()
        assert len(prices) == 96
        assert prices[1].timestamp == midnight + timedelta(minutes=15)
        assert prices[95].timestamp == midnight + timedelta(minutes=45, hours=23)
        assert p._last_parsed_gap_seconds == 900.0

    def test_48_values_is_30_minute(self):
        values = [0.20 + 0.001 * i for i in range(48)]
        p = _provider({"today": values})
        prices = p._read_prices_list()
        assert len(prices) == 48
        assert prices[1].timestamp == _local_midnight() + timedelta(minutes=30)
        assert p._last_parsed_gap_seconds == 1800.0

    @pytest.mark.parametrize("n,expected", [
        (23, timedelta(hours=1)),   # DST short day
        (24, timedelta(hours=1)),
        (25, timedelta(hours=1)),   # DST long day
        (48, timedelta(minutes=30)),
        (96, timedelta(minutes=15)),
    ])
    def test_interval_bands(self, n, expected):
        assert _flat_list_interval(n) == expected


# ---------------------------------------------------------------------------
# Null / gap padding
# ---------------------------------------------------------------------------

class TestNullPadding:
    def test_none_padding_is_skipped_without_shifting_slots(self):
        """Nordpool pads unpublished hours with ``None``. Those slots drop
        out but the surviving slots keep their real timestamps."""
        values = [0.10, 0.11, None, 0.13, None, 0.15] + [None] * 18
        p = _provider({"today": values})
        prices = p._read_prices_list()

        midnight = _local_midnight()
        assert len(prices) == 4  # 4 real values, 20 None
        assert prices[0].timestamp == midnight              # index 0
        assert prices[1].timestamp == midnight + timedelta(hours=1)   # index 1
        assert prices[2].timestamp == midnight + timedelta(hours=3)   # index 3, NOT 2
        assert prices[3].timestamp == midnight + timedelta(hours=5)   # index 5
        assert [pp.price for pp in prices] == [0.10, 0.11, 0.13, 0.15]


# ---------------------------------------------------------------------------
# Day anchoring
# ---------------------------------------------------------------------------

class TestDayAnchoring:
    @pytest.mark.parametrize("key", TOMORROW_KEYS)
    def test_tomorrow_keys_anchor_to_tomorrow(self, key):
        values = [0.30 + 0.01 * i for i in range(24)]
        p = _provider({key: values})
        prices = p._read_prices_list()
        tomorrow_midnight = _local_midnight() + timedelta(days=1)
        assert len(prices) == 24
        assert prices[0].timestamp == tomorrow_midnight

    def test_over_one_day_flat_list_is_not_guessed(self):
        """A flat list longer than one day's finest granularity (>96)
        concatenates multiple days or is malformed. The length→granularity
        heuristic can't disambiguate it, so it is refused rather than
        silently packed into a single day at the wrong spacing (#732
        review). Dict items in an over-long list still parse."""
        # 192 hourly values = today+tomorrow crammed under one key.
        values = [0.10 + 0.001 * i for i in range(192)]
        p = _provider({"today": values})
        assert p._read_prices_list() == []

        # But a 192-entry list of real {start,value} dicts (2 days of
        # 15-min ENTSO-E) still parses — dicts carry their own timestamps.
        midnight = _local_midnight()
        dicts = [
            {"start": (midnight + timedelta(minutes=15 * i)).isoformat(),
             "value": 0.10 + 0.001 * i}
            for i in range(192)
        ]
        p2 = _provider({"today": dicts})
        assert len(p2._read_prices_list()) == 192

    def test_96_is_the_flat_ceiling(self):
        """Exactly 96 (15-min single day) is still accepted; 97 is not."""
        assert len(_provider({"today": [0.2] * 96})._read_prices_list()) == 96
        assert _provider({"today": [0.2] * 97})._read_prices_list() == []

    def test_bare_prices_is_ambiguous_and_not_flat_parsed(self):
        """``prices`` has no day reference — guessing a day would mis-date
        the whole percentile distribution, so the flat shape is rejected
        for it (dict shape with real timestamps still works)."""
        assert _flat_list_base("prices") is None
        p = _provider({"prices": [0.10, 0.20, 0.30]})
        assert p._read_prices_list() == []


# ---------------------------------------------------------------------------
# The dict shape must still parse (regression for the merged loop)
# ---------------------------------------------------------------------------

class TestDictShapeStillWorks:
    def test_raw_today_dicts_still_parse(self):
        """Nordpool ``raw_today`` = list of {start, value} dicts — the merge
        of the two former loops must not drop it."""
        midnight = _local_midnight()
        raw = [
            {
                "start": (midnight + timedelta(hours=h)).isoformat(),
                "end": (midnight + timedelta(hours=h + 1)).isoformat(),
                "value": 0.10 + 0.01 * h,
            }
            for h in range(24)
        ]
        p = _provider({"raw_today": raw})
        prices = p._read_prices_list()
        assert len(prices) == 24
        assert p._last_parsed_attribute == "raw_today"

    def test_tibber_today_dicts_still_parse(self):
        """Tibber ``today`` = list of {startsAt, total} dicts."""
        midnight = _local_midnight()
        today = [
            {
                "startsAt": (midnight + timedelta(hours=h)).isoformat(),
                "total": 0.20 + 0.01 * h,
            }
            for h in range(24)
        ]
        p = _provider({"today": today})
        prices = p._read_prices_list()
        assert len(prices) == 24
        assert p._last_parsed_attribute == "today"


# ---------------------------------------------------------------------------
# Structural guard: every day-keyed name accepts the flat shape
# ---------------------------------------------------------------------------

class TestFlatShapeParityGuard:
    @pytest.mark.parametrize("key", FLAT_KEYS)
    def test_every_flat_key_accepts_a_flat_list(self, key):
        """The whole recognised day-keyed vocabulary must accept a flat
        numeric list. Derived from ``DAY_KEYED_PRICE_ATTRS`` so a refactor
        that re-narrows any key to dict-only (the #732 root cause) fails
        CI here rather than silently degrading one provider's users."""
        values = [0.15 + 0.01 * i for i in range(24)]
        p = _provider({key: values})
        prices = p._read_prices_list()
        assert len(prices) == 24, f"flat list under {key!r} was rejected"
        assert p._last_parsed_attribute == key
        assert p._no_price_array_warned is False

    def test_flat_keys_are_non_empty(self):
        """Vacuity floor: if the derivation ever yields nothing, the guard
        above would pass by testing zero keys."""
        assert len(FLAT_KEYS) >= 6

    def test_bool_items_are_not_treated_as_prices(self):
        """``isinstance(True, int)`` is True in Python — a bool must not be
        coerced to a 1.0/0.0 price."""
        p = _provider({"today": [True, False, 0.20]})
        prices = p._read_prices_list()
        # only the genuine float survives
        assert [pp.price for pp in prices] == [0.20]
