"""#838 — one Forecast.Solar entry per string must be summed, not sampled.

Reporter @HorizonKane on 2.0.0-beta.15: Forecast.Solar detected correctly, but
one config entry per PV string, and SEM used a single one of them.

That is how the integration is meant to be used. Home Assistant's
``forecast_solar`` takes one azimuth and one declination per config entry, so a
roof with an east plane and a west plane is TWO entries, and each publishes its
own ``energy_production_today``. Their unique_ids are ``{entry_id}_{key}``, so
they differ only by the entry.

``_registry_entities`` resolved a role with ``role not in resolved``, i.e. the
first match wins and the rest are dropped. A two-plane install therefore
forecast one plane; a three-plane install forecast a third of its roof.

The direction matters. This UNDER-states the sun, and every consumer reads it
as "less free energy is coming": the battery holds more back, EV surplus
charging starts later, and #778 would size its budget against a roof that does
not exist. It is silent — the picker says Forecast.Solar and the number looks
like a forecast, just a small one.

Solcast is not affected: its unique_ids are fixed strings
(``total_kwh_forecast_today``), so Home Assistant permits only one entry
producing them, and the integration sums its own sites internally.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import forecast_reader as fr
from custom_components.solar_energy_management.coordinator.forecast_reader import (
    ForecastReader,
)

PLATFORM = fr.FORECAST_SOLAR_PLATFORM


def _entry(entry_id: str, key: str, entity_id: str):
    return SimpleNamespace(
        platform=PLATFORM, disabled_by=None,
        unique_id=f"{entry_id}_{key}", entity_id=entity_id,
    )


def _reader(planes: dict, values: dict):
    """`planes` = {entry_id: suffix_label}; `values` = {entity_id: state}."""
    registry_entries = []
    for entry_id in planes:
        for key, label in (
            ("energy_production_today", "today"),
            ("energy_production_tomorrow", "tomorrow"),
            ("power_production_now", "now"),
        ):
            registry_entries.append(
                _entry(entry_id, key, f"sensor.{entry_id}_{label}"))

    hass = MagicMock()
    states = {
        eid: SimpleNamespace(state=str(v),
                             attributes={"unit_of_measurement": "kWh"})
        for eid, v in values.items()
    }
    hass.states.get = lambda eid: states.get(eid)
    hass.states.async_all.return_value = []

    r = ForecastReader(hass, custom_entities=None, preferred_source="forecast_solar")
    r._registry_cache = {}
    fake_registry = SimpleNamespace(
        entities=SimpleNamespace(values=lambda: registry_entries))
    r._entity_registry_for_test = fake_registry
    return r, fake_registry


@pytest.fixture(autouse=True)
def _patch_registry(monkeypatch):
    """Serve our fake registry to _registry_entities without a real HA."""
    import homeassistant.helpers.entity_registry as er
    monkeypatch.setattr(
        er, "async_get",
        lambda hass: getattr(hass, "_sem_test_registry", None) or MagicMock(
            entities=SimpleNamespace(values=lambda: [])),
        raising=False,
    )


def _wire(r, registry):
    r.hass._sem_test_registry = registry


class TestThePlanesAreSummed:
    def test_three_planes_sum_instead_of_one_winning(self):
        r, reg = _reader(
            {"east": None, "south": None, "west": None},
            {"sensor.east_today": 4.0, "sensor.south_today": 10.0,
             "sensor.west_today": 6.0},
        )
        _wire(r, reg)
        groups = r._registry_groups(PLATFORM)
        assert len(groups.get("forecast_today", [])) == 3, groups
        total = r._sum_float(groups["forecast_today"], 0.0)
        assert total == pytest.approx(20.0), (
            f"summed {total}, expected 20.0 — a plane was dropped (#838)"
        )

    def test_tomorrow_is_summed_too(self):
        r, reg = _reader(
            {"east": None, "west": None},
            {"sensor.east_tomorrow": 7.5, "sensor.west_tomorrow": 2.5},
        )
        _wire(r, reg)
        groups = r._registry_groups(PLATFORM)
        assert r._sum_float(groups["forecast_tomorrow"], 0.0) == pytest.approx(10.0)

    def test_a_single_plane_is_unchanged(self):
        """The overwhelmingly common install must behave exactly as before."""
        r, reg = _reader({"only": None}, {"sensor.only_today": 12.25})
        _wire(r, reg)
        groups = r._registry_groups(PLATFORM)
        assert r._sum_float(groups["forecast_today"], 0.0) == pytest.approx(12.25)

    def test_an_unavailable_plane_does_not_poison_the_others(self):
        """Under-stating by one plane beats reporting nothing at all."""
        r, reg = _reader(
            {"east": None, "west": None},
            {"sensor.east_today": 5.0, "sensor.west_today": "unavailable"},
        )
        _wire(r, reg)
        groups = r._registry_groups(PLATFORM)
        assert r._sum_float(groups["forecast_today"], 0.0) == pytest.approx(5.0)


class TestPeakIsNotAdditive:
    def test_peak_power_takes_the_largest_plane_not_the_sum(self):
        """Two planes peak at different times of day, so their peaks do not
        add. Summing would invent a peak the roof never reaches."""
        r, reg = _reader({"east": None, "west": None}, {})
        _wire(r, reg)
        assert r._peak_of([], 0.0) == 0.0
        r.hass.states.get = lambda eid: SimpleNamespace(
            state={"a": "3000", "b": "2500"}[eid],
            attributes={"unit_of_measurement": "W"})
        assert r._peak_of(["a", "b"], 0.0) == pytest.approx(3000.0)


class TestBackwardsCompatibility:
    def test_registry_entities_still_returns_one_id_per_role(self):
        """The single-entity map is still what detection compares against."""
        r, reg = _reader({"east": None, "west": None}, {})
        _wire(r, reg)
        resolved = r._registry_entities(PLATFORM)
        assert isinstance(resolved.get("forecast_today"), str), resolved
