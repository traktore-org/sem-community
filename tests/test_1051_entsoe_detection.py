"""#1051 — ENTSO-e as a dynamic tariff, found without the user naming it.

Proven on the integration's real output, not on shapes written for the
test: the rig's ``entsoe`` and ``entsoe_named_15m`` captures are
JaccoR/hass-entso-e v0.7.5 set up in a Home Assistant test instance and
answered with its own test datasets (tests/integrations_rig/PINS.md).

What the captures showed, and what the detection is built on:

* the price now sits on the sensor whose unique id ends in its
  ``current_price`` key, and that sensor carries no curve;
* the curve (``prices`` / ``prices_today`` / ``prices_tomorrow``) sits on
  its AVERAGE sensor, whose state is the day's average — not a price to pay
  now, though its id contains ``electricity_price`` like Tibber's;
* an entity name given in its setup goes into every entity id, so only the
  registry platform says "ENTSO-e".
"""
from __future__ import annotations

import logging
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from custom_components.solar_energy_management.tariff.tariff_provider import (
    DynamicTariffProvider,
)

from .integrations_rig.rig import load_capture, replay

CURRENT = "sensor.current_electricity_market_price"
AVERAGE = "sensor.average_electricity_price"


async def _provider(hass, *captures, **kwargs) -> DynamicTariffProvider:
    for name in captures:
        await replay(hass, load_capture(name))
    return DynamicTariffProvider(hass, **kwargs)


def _restate(hass, entity_id, *, drop=(), **extra):
    """Set ``entity_id`` again with some attributes taken away or added."""
    st = hass.states.get(entity_id)
    attrs = {k: v for k, v in st.attributes.items() if k not in drop}
    attrs.update(extra)
    hass.states.async_set(entity_id, st.state, attrs)


async def test_the_price_now_and_the_curve_come_from_two_sensors(hass):
    p = await _provider(hass, "entsoe")
    assert p.detect_provider() == "entsoe"
    assert p._provider_name == "entsoe"
    assert p._price_entity == CURRENT
    assert p._forecast_entity == AVERAGE
    # The price now is the current sensor's: -0.00001 EUR/kWh at 14:07 on a
    # sunny Sunday in DE-LU. The average sensor reads 0.06931.
    assert p.get_current_import_rate() == pytest.approx(-0.00001)

    curve = p._read_prices_list()
    assert len(curve) == 48  # today and tomorrow, hourly
    assert p._last_parsed_gap_seconds == 3600.0
    berlin = ZoneInfo("Europe/Berlin")
    assert curve[0].timestamp == datetime(2024, 10, 6, 0, 0, tzinfo=berlin)
    assert curve[-1].timestamp == datetime(2024, 10, 7, 23, 0, tzinfo=berlin)
    # One integration, one story: the curve's 14:00 slot is the price now.
    slot = next(c for c in curve
                if c.timestamp == datetime(2024, 10, 6, 14, 0, tzinfo=berlin))
    assert slot.price == pytest.approx(float(hass.states.get(CURRENT).state))


async def test_a_named_setup_with_quarter_hour_prices(hass):
    p = await _provider(hass, "entsoe_named_15m")
    assert p.detect_provider() == "entsoe"
    assert p._price_entity == "sensor.home_current_electricity_market_price"
    assert p._forecast_entity == "sensor.home_average_electricity_price"

    attrs = hass.states.get(p._forecast_entity).attributes
    published = {row["time"] for key in ("prices", "prices_today",
                                         "prices_tomorrow")
                 for row in attrs[key]}
    curve = p._read_prices_list()
    assert len(curve) == len(published)  # every slot once, none invented
    assert p._last_parsed_gap_seconds == 900.0


async def test_an_entity_id_alone_is_not_entsoe(hass):
    """The ids ENTSO-e would use, on sensors no ENTSO-e registered."""
    curve = load_capture("entsoe")["entities"]
    avg = next(e for e in curve if e["entity_id"] == AVERAGE)
    hass.states.async_set(CURRENT, "0.1", {"unit_of_measurement": "EUR/kWh"})
    hass.states.async_set(AVERAGE, "0.1", avg["attributes"])
    p = DynamicTariffProvider(hass)
    assert p.detect_provider() is None
    assert p._price_entity is None


async def test_no_curve_yet_is_not_found_yet(hass):
    """Before ENTSO-e has published, its average sensor carries no arrays.
    Nothing is detected, and the next read asks again."""
    p = await _provider(hass, "entsoe")
    _restate(hass, AVERAGE, drop=("prices", "prices_today", "prices_tomorrow"))
    assert p.detect_provider() is None
    assert p._price_entity is None and p._provider_name == "unknown"

    await replay(hass, load_capture("entsoe"))  # published
    p._read_current_price()  # an ordinary read looks again
    assert p._provider_name == "entsoe"
    assert p._price_entity == CURRENT


async def test_prices_per_mwh_are_refused_and_said_once(hass, caplog):
    p = await _provider(hass, "entsoe")
    _restate(hass, CURRENT, unit_of_measurement="EUR/MWh")
    with caplog.at_level(logging.WARNING):
        assert p.detect_provider() is None
        assert p.detect_provider() is None
    said = [r for r in caplog.records if "per MWh" in r.getMessage()]
    assert len(said) == 1
    assert p._price_entity is None


async def test_a_disabled_current_price_sensor_is_not_used(hass):
    from homeassistant.helpers import entity_registry as er
    p = await _provider(hass, "entsoe")
    er.async_get(hass).async_update_entity(
        CURRENT, disabled_by=er.RegistryEntryDisabler.USER)
    assert p.detect_provider() is None


async def test_two_setups_are_never_mixed(hass):
    """Two areas side by side: the price now and the curve come from the
    same setup."""
    from homeassistant.helpers import entity_registry as er
    p = await _provider(hass, "entsoe", "entsoe_named_15m")
    assert p.detect_provider() == "entsoe"
    reg = er.async_get(hass)
    assert (reg.async_get(p._price_entity).config_entry_id
            == reg.async_get(p._forecast_entity).config_entry_id)


async def test_a_setup_without_its_curve_is_not_completed_by_another(hass):
    """One setup's price now with another setup's curve would mix two
    areas' prices. A setup that has not published is passed over."""
    p = await _provider(hass, "entsoe", "entsoe_named_15m")
    _restate(hass, AVERAGE, drop=("prices", "prices_today", "prices_tomorrow"))
    assert p.detect_provider() == "entsoe"
    assert p._price_entity == "sensor.home_current_electricity_market_price"
    assert p._forecast_entity == "sensor.home_average_electricity_price"


async def test_the_curve_on_the_current_sensor_itself(hass):
    """An integration version that puts the arrays on the current-price
    sensor needs no second entity."""
    p = await _provider(hass, "entsoe")
    arrays = {k: hass.states.get(AVERAGE).attributes[k]
              for k in ("prices", "prices_today", "prices_tomorrow")}
    _restate(hass, CURRENT, **arrays)
    _restate(hass, AVERAGE, drop=tuple(arrays))
    assert p.detect_provider() == "entsoe"
    assert p._price_entity == CURRENT
    assert p._forecast_entity is None
    assert len(p._read_prices_list()) == 48


async def test_prices_already_found_stay_where_they_are(hass):
    """ENTSO-e is tried last: an install that found Nord Pool keeps it."""
    p = await _provider(hass, "entsoe")
    hass.states.async_set("sensor.nord_pool_de_current_price", "0.07")
    assert p.detect_provider() == "nordpool_official"
    assert p._price_entity == "sensor.nord_pool_de_current_price"


async def test_a_chosen_price_entity_stays_the_users(hass):
    """#518 holds: a configured price entity is never swapped."""
    p = await _provider(hass, "entsoe", price_entity="sensor.my_price")
    assert p.detect_provider() == "custom"
    assert p._price_entity == "sensor.my_price"
    assert p._forecast_entity is None


async def test_a_price_entity_with_its_own_curve_keeps_reading_it(hass):
    """The forecast entity's arrays are read only when the price entity has
    none — an install whose price sensor carries its curve is unchanged."""
    berlin = ZoneInfo("Europe/Berlin")
    own = [{"start": datetime(2024, 10, 6, h, tzinfo=berlin).isoformat(),
            "value": 0.5} for h in range(24)]
    hass.states.async_set("sensor.my_price", "0.5", {"today": own})
    p = await _provider(hass, "entsoe", price_entity="sensor.my_price",
                        forecast_entity=AVERAGE)
    curve = p._read_prices_list()
    assert len(curve) == 24
    assert {c.price for c in curve} == {0.5}
    assert p._last_parsed_attribute == "today"


async def test_a_configured_forecast_entity_with_day_arrays_is_read(hass):
    """The same path serves a user who names both ENTSO-e sensors."""
    p = await _provider(hass, "entsoe", price_entity=CURRENT,
                        forecast_entity=AVERAGE)
    assert p.detect_provider() == "custom"
    assert len(p._read_prices_list()) == 48


async def test_an_unreadable_forecast_entity_gives_no_curve(hass):
    """#994's rule on the second entity too: arrays on an entity that does
    not read are what it last said, not what it says now."""
    p = await _provider(hass, "entsoe", price_entity=CURRENT,
                        forecast_entity=AVERAGE)
    st = hass.states.get(AVERAGE)
    hass.states.async_set(AVERAGE, "unavailable", dict(st.attributes))
    assert p._read_prices_list() == []


async def test_the_options_flow_leaves_entsoe_to_the_runtime(hass, config_entry):
    """The flow's auto-fill matched the AVERAGE sensor by its id (Tibber's
    ``electricity_price``) and saved it as the price entity: the day's
    average would have read as the price now. It now leaves the field empty
    and the runtime pairs the two sensors."""
    from custom_components.solar_energy_management.config_flow import (
        OptionsFlowHandler,
    )
    await replay(hass, load_capture("entsoe"))
    assert DynamicTariffProvider.is_price_entity_candidate(AVERAGE)

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    with patch.object(type(flow), "config_entry",
                      new_callable=lambda: property(lambda self: config_entry)), \
            patch.object(OptionsFlowHandler, "async_step_load_management",
                         AsyncMock(return_value={"type": "form"})):
        await flow.async_step_settings_tariff({"tariff_mode": "dynamic"})
    assert not flow._data.get("dynamic_tariff_entity")
