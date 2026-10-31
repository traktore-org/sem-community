"""#1274 — a restart while SEM holds an export cut must not lose the saved prior.

The adopt runs on the first tick, before any battery adapter exists (they are
built later in the battery pipeline). The saved recipe was handed to nobody,
so a generic battery's limit stayed at 0 W and a Huawei inverter was reset to
"Unlimited". The recipe now waits for its battery's adapter.
"""
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator

RECIPE = {"domain": "number", "service": "set_value",
          "data": {"entity_id": "number.inv_export_limit", "value": 9000.0}}


class _Store:
    def __init__(self, rec):
        self.rec = rec

    async def async_load(self):
        return self.rec

    async def async_save(self, data):
        self.rec = data


def _fresh(rec):
    fake = SimpleNamespace(
        hass=MagicMock(), config={"export_guard_enabled": True},
        _export_guard=None, _export_guard_adopted=False,
        _battery_adapters={}, _export_guard_store=lambda: _Store(rec))
    for name in ("_export_guard_adopt", "_ensure_export_guard",
                 "_adopt_pending_export_prior"):
        setattr(fake, name, partial(getattr(SEMCoordinator, name), fake))
    return fake


def _generic():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states.get = MagicMock(return_value=SimpleNamespace(state="11000"))
    return GenericBatteryAdapter(hass, {"export_limit_entity": "number.inv_export_limit"})


@pytest.mark.asyncio
class TestThePriorWaitsForItsAdapter:
    async def test_an_adapter_built_after_the_adopt_gets_its_prior(self):
        fake = _fresh({"engaged": True, "since": "t", "recipes": {"b1": RECIPE}})
        await fake._ensure_export_guard()          # first tick: no adapter yet
        gen = _generic()
        fake._battery_adapters["b1"] = gen         # built later in the pipeline
        fake._adopt_pending_export_prior("b1", gen)
        assert gen.holds_export_cut() is True
        assert gen._export_prior == 9000.0

    async def test_a_battery_the_store_never_named_gets_nothing(self):
        fake = _fresh({"engaged": True, "since": "t", "recipes": {"b1": RECIPE}})
        await fake._ensure_export_guard()
        other = _generic()
        fake._adopt_pending_export_prior("b2", other)
        assert other.holds_export_cut() is False

    async def test_a_prior_is_handed_over_once(self):
        fake = _fresh({"engaged": True, "since": "t", "recipes": {"b1": RECIPE}})
        await fake._ensure_export_guard()
        first, again = _generic(), _generic()
        fake._adopt_pending_export_prior("b1", first)
        fake._adopt_pending_export_prior("b1", again)
        assert first.holds_export_cut() is True
        assert again.holds_export_cut() is False

    async def test_a_store_that_says_not_engaged_leaves_nothing_waiting(self):
        fake = _fresh({"engaged": False})
        await fake._ensure_export_guard()
        gen = _generic()
        fake._adopt_pending_export_prior("b1", gen)
        assert gen.holds_export_cut() is False


def test_the_pipeline_asks_for_the_prior_wherever_it_stores_an_adapter():
    import inspect
    src = inspect.getsource(SEMCoordinator._run_battery_pipeline)
    stores = src.count("self._battery_adapters[battery_id] = adapter")
    asks = src.count("_adopt_pending_export_prior(battery_id, adapter)")
    assert stores >= 2 and asks == stores
