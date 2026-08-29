"""#612 — the "bring your own price sensor" contract, pinned.

The SETUP_GUIDE ships a copy-paste Spanish 2.0TD template recipe (three
fixed price plateaus, ``raw_today`` + ``raw_tomorrow`` Nordpool-shaped
curve attributes). SEM ships ZERO code for it — the whole feature is the
existing DynamicTariffProvider custom-entity path + generic curve
parsing. These tests pin that contract against parser drift: if a
refactor stops parsing the recipe's attribute shape, the doc silently
breaks for every template/PVPC user — this suite makes that a CI
failure instead. Verified live on HA-TEST 2026-07-19 (classifier_path
``percentile_active(... n=25)``, next cheap window = tomorrow 00:00).
"""
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.tariff.tariff_provider import (
    DynamicTariffProvider,
    PriceLevel,
)

P1, P2, P3 = 0.182, 0.131, 0.092  # punta / llano / valle


def _hour_price(h: int) -> float:
    """The recipe's weekday schedule (peninsular 2.0TD)."""
    if h < 8:
        return P3
    if 10 <= h < 14 or 18 <= h < 22:
        return P1
    return P2


def _recipe_attributes() -> dict:
    """Build raw_today/raw_tomorrow exactly as the docs template renders
    them: list of {start, end, value} with local ISO timestamps."""
    midnight = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
    def day(base):
        return [
            {
                "start": (base + timedelta(hours=h)).isoformat(),
                "end": (base + timedelta(hours=h + 1)).isoformat(),
                "value": _hour_price(h),
            }
            for h in range(24)
        ]
    return {
        "raw_today": day(midnight),
        "raw_tomorrow": day(midnight + timedelta(days=1)),
        "unit_of_measurement": "EUR/kWh",
    }


def _provider_with_recipe(current_price: float) -> DynamicTariffProvider:
    hass = MagicMock()
    state = MagicMock()
    state.state = str(current_price)
    state.entity_id = "sensor.electricity_price_es_2_0td"
    state.attributes = _recipe_attributes()
    hass.states.get = MagicMock(return_value=state)
    hass.states.async_all = MagicMock(return_value=[])
    return DynamicTariffProvider(
        hass,
        price_entity="sensor.electricity_price_es_2_0td",
        currency="EUR",
        classification_mode="percentile",
    )


@pytest.mark.unit
class TestRecipeContract:
    def test_curve_parses_48_slots(self):
        p = _provider_with_recipe(P1)
        prices = p._read_prices_list()
        assert len(prices) == 48, (
            "the recipe's raw_today+raw_tomorrow shape stopped parsing — "
            "the SETUP_GUIDE Spain template is broken for users"
        )
        assert {round(pp.price, 3) for pp in prices} == {P1, P2, P3}

    # Classification goes through get_tariff_data() — the coordinator's
    # per-cycle entry point, which reads the curve (populating the
    # percentile cache) before classifying. A bare get_price_level() on a
    # cold provider hits percentile_fallback_cache_empty by design (#359).
    def test_punta_classifies_expensive(self):
        p = _provider_with_recipe(P1)
        level = p.get_tariff_data().price_level
        assert level in (PriceLevel.EXPENSIVE, PriceLevel.VERY_EXPENSIVE), level

    def test_valle_classifies_cheap(self):
        p = _provider_with_recipe(P3)
        level = p.get_tariff_data().price_level
        assert level in (PriceLevel.CHEAP, PriceLevel.VERY_CHEAP), level

    def test_llano_is_between(self):
        p = _provider_with_recipe(P2)
        assert p.get_tariff_data().price_level is PriceLevel.NORMAL

    def test_classifier_path_is_tou_tiers(self):
        """The ES 2.0TD is a genuine 3-tier fixed ToU (valle/llano/punta)
        — since #728's second round it classifies by its distinct value
        tiers, not the rolling percentile window. The intent of this pin
        is unchanged: the recipe curve must land on an ACTIVE classifier
        path, never a fallback_* one."""
        p = _provider_with_recipe(P1)
        data = p.get_tariff_data()
        assert data.classifier_path.startswith("tou_tiers"), (
            data.classifier_path
        )

    def test_provider_is_custom_authoritative(self):
        p = _provider_with_recipe(P1)
        assert p.detect_provider() == "custom"

    def test_cheap_window_found(self):
        """The planner sees a valle window (today's early hours or
        tomorrow 00:00 via raw_tomorrow — the live-verified gap that
        made the recipe include tomorrow's curve)."""
        p = _provider_with_recipe(P1)
        data = p.get_tariff_data()
        assert data.next_cheap_window_start is not None, (
            "no cheap window from the recipe curve — raw_tomorrow "
            "parsing regressed (planner blind to the midnight valle)"
        )

    def test_current_rate_reads_template_state(self):
        p = _provider_with_recipe(P2)
        assert p.get_current_import_rate() == pytest.approx(P2)
