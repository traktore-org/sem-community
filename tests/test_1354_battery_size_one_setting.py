"""(#1354) The battery size is ONE stored setting.

``number.sem_battery_capacity`` and the options flow both write
``battery_capacity_kwh``; the engine reads it through
``coordinator.battery_capacity_kwh`` (the setting, else the detected size,
else 15). Unset, the entity used to show its own default while SEM planned
with the detected size, and its 5 kWh step could not hold a 12.7 kWh pack.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.consts.bounds import BOUNDS
from custom_components.solar_energy_management.number import NUMBER_TYPES, SEMNumberEntity


def _desc():
    return next(d for d in NUMBER_TYPES if d.key == "battery_capacity")


def _entity(stored, used):
    ent = SEMNumberEntity.__new__(SEMNumberEntity)
    ent.entity_description = _desc()
    ent.coordinator = SimpleNamespace(
        config={} if stored is None else {"battery_capacity_kwh": stored},
        battery_capacity_kwh=used)
    ent._attr_native_value = stored if stored is not None else 15
    return ent


@pytest.mark.unit
def test_the_entity_has_the_settings_one_range():
    d, b = _desc(), BOUNDS["battery_capacity_kwh"]
    assert (d.native_min_value, d.native_max_value, d.native_step) == (b.min, b.max, b.step)


@pytest.mark.unit
def test_unset_it_shows_the_size_sem_plans_with():
    assert _entity(None, 12.7).native_value == 12.7


@pytest.mark.unit
def test_set_it_shows_the_setting():
    assert _entity(10.0, 12.7).native_value == 10.0


@pytest.mark.unit
def test_nothing_known_keeps_its_own_value():
    assert _entity(None, 0.0).native_value == 15
