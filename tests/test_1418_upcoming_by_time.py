"""(#1418) The price chart stopped 12 h after now on a 15-minute market.

@RVallen78 (SolarEdge + Zaptec, NL, 2.3.0-beta.25) at 21:52: the plan
card's "Next 24 h" drew prices until about 09:45 and then a hatched "prices
for tomorrow ~13:00", though tomorrow's prices were out since the afternoon.
The window moved with the clock.

Root cause: ``upcoming_prices`` was cut to 48 POINTS — two days of an hourly
market, 12 h of a 15-minute one (the Dutch day-ahead market is 15-minute).
The coordinator cut the sensor's ``upcoming`` to 48 again, and the plan's
change check cut its copy to 96, which never took effect behind the first
cut. The list now ends by TIME: the slot in progress plus 48 h. An hourly
list is the same as before.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from freezegun import freeze_time
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.tariff.tariff_provider import (
    UPCOMING_PRICES_HORIZON,
    DynamicTariffProvider,
)

#: 23.11.2026, 21:52 — the reporter's screenshot (the test zone's clock).
AT = "2026-11-23 21:52:00"


def _provider(attributes: dict) -> DynamicTariffProvider:
    hass = MagicMock()
    state = MagicMock()
    state.state = "0.416"
    state.entity_id = "sensor.price"
    state.attributes = attributes
    hass.states.get = MagicMock(return_value=state)
    hass.states.async_all = MagicMock(return_value=[])
    return DynamicTariffProvider(hass, price_entity="sensor.price",
                                 currency="EUR",
                                 classification_mode="percentile")


def _midnight():
    return dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)


def _quarter_days():
    """Today and tomorrow, 96 quarter-hour prices each (Nordpool's flat shape)."""
    return {"today": [round(0.30 + 0.001 * i, 4) for i in range(96)],
            "tomorrow": [round(0.40 + 0.001 * i, 4) for i in range(96)]}


@pytest.mark.unit
def test_a_quarter_hour_market_reaches_the_end_of_tomorrow():
    with freeze_time(AT, tz_offset=0):
        now = dt_util.now()
        ups = _provider(_quarter_days()).get_tariff_data().upcoming_prices
        mid = _midnight()
    # the slot in progress first
    assert ups[0].timestamp <= now < ups[0].timestamp + timedelta(minutes=15)
    # tomorrow's last quarter is there: 48 points ended 12 h from now
    assert ups[-1].timestamp == mid + timedelta(days=1, hours=23, minutes=45)
    assert ups[-1].timestamp - now > timedelta(hours=12)
    assert len(ups) > 48
    # every quarter in between, none missing
    gaps = {b.timestamp - a.timestamp for a, b in zip(ups, ups[1:], strict=False)}
    assert gaps == {timedelta(minutes=15)}


@pytest.mark.unit
def test_an_hourly_market_keeps_its_list():
    with freeze_time(AT, tz_offset=0):
        now = dt_util.now()
        ups = _provider({"today": [0.3] * 24, "tomorrow": [0.4] * 24}
                        ).get_tariff_data().upcoming_prices
        mid = _midnight()
    assert ups[0].timestamp == now.replace(minute=0, second=0, microsecond=0)
    assert ups[-1].timestamp == mid + timedelta(days=1, hours=23)
    assert len(ups) == (24 - now.hour) + 24     # the rest of today, all of tomorrow


def _forecasts(step: timedelta, days: int):
    """A provider that publishes more than two days (an Amber/Octopus shape)."""
    t0 = datetime(2026, 11, 23, 0, 0, tzinfo=timezone.utc)
    n = int(timedelta(days=days) / step)
    return {"forecasts": [{"start_time": (t0 + i * step).isoformat(),
                           "per_kwh": 0.3} for i in range(n)]}


@pytest.mark.unit
@pytest.mark.parametrize("step", [timedelta(hours=1), timedelta(minutes=30),
                                  timedelta(minutes=15)])
def test_the_list_ends_48_hours_after_the_slot_in_progress(step):
    """The bound is time on every grain; an hourly list holds 48 points,
    as it did under the old count."""
    with freeze_time(AT, tz_offset=0):
        ups = _provider(_forecasts(step, 4)).get_tariff_data().upcoming_prices
    assert ups[-1].timestamp == ups[0].timestamp + UPCOMING_PRICES_HORIZON - step
    assert len(ups) == UPCOMING_PRICES_HORIZON / step
    if step == timedelta(hours=1):
        assert len(ups) == 48


@pytest.mark.unit
def test_no_prices_is_an_empty_list():
    with freeze_time(AT, tz_offset=0):
        assert _provider({}).get_tariff_data().upcoming_prices == []


# ── the plan's change check: time passing is not news ──

def _sig(points):
    from types import SimpleNamespace as NS

    from .test_638_demand_replan import _coord, _power
    c = _coord(prices=())
    c._tariff_provider = NS(get_tariff_data=lambda: NS(upcoming_prices=points))
    return c._energy_plan_demand_signature(_power())


@pytest.mark.unit
def test_a_long_quarter_hour_list_slides_without_a_replan():
    """With the whole of tomorrow in the list (well over 96 points), a cut
    at 96 would let a new point in at the end every 15 minutes, and a new
    point reads as tomorrow's prices landing: a re-plan each quarter."""
    from types import SimpleNamespace as NS

    from custom_components.solar_energy_management.coordinator.coordinator import (
        demand_signature_changed,
    )
    t0 = datetime(2026, 11, 23, 21, 45, tzinfo=timezone.utc)
    pts = [NS(price=0.3 + 0.001 * (i % 40), timestamp=t0 + i * timedelta(minutes=15))
           for i in range(105)]
    old, new = _sig(pts), _sig(pts[1:])
    assert demand_signature_changed(old, new) is False
    # and a price that moves at the far end of tomorrow is still news
    moved = list(pts[1:])
    moved[-1] = NS(price=0.9, timestamp=moved[-1].timestamp)
    assert demand_signature_changed(new, _sig(moved)) is True


# ── the real coordinator and the real sensor, as on the install ──

async def _setup(hass, base, **options):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(domain=base.domain, version=base.version,
                            minor_version=base.minor_version,
                            data=dict(base.data), options=options,
                            title=base.title)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


@pytest.mark.asyncio
async def test_the_price_sensor_carries_tomorrow_of_a_quarter_hour_market(
        sem_real_hass, sem_config_entry):
    sem_real_hass.states.async_set(
        "sensor.test_spot_price", "0.416",
        {"unit_of_measurement": "EUR/kWh", **_quarter_days()})
    await _setup(sem_real_hass, sem_config_entry, tariff_mode="dynamic",
                 dynamic_tariff_entity="sensor.test_spot_price")
    st = sem_real_hass.states.get("sensor.sem_tariff_current_import_rate")
    assert st is not None, "no price sensor"
    up = st.attributes["upcoming"]
    last = datetime.fromisoformat(up[-1]["t"])
    assert last == _midnight() + timedelta(days=1, hours=23, minutes=45)
    assert len(up) > 48
    assert up[-1]["price"] == pytest.approx(0.40 + 0.001 * 95)

