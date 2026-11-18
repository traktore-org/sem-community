"""(#1321) A car size typed in the options flow counts as the owner's, and the
flag a card write left on the charger survives an options-flow save."""
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.config_flow import (
    OptionsFlowHandler,
    _mark_owner_values,
)

FLAG = "ev_battery_capacity_kwh_by_owner"


@pytest.mark.unit
class TestMarkOwnerValues:
    def test_a_changed_capacity_sets_the_flag(self):
        charger = {"id": "c1", "ev_battery_capacity_kwh": 60}
        _mark_owner_values({"id": "c1"}, {"ev_battery_capacity_kwh": 60}, charger)
        assert charger[FLAG] is True

    def test_the_untouched_factory_value_does_not(self):
        charger = {"id": "c1", "ev_battery_capacity_kwh": 40}
        _mark_owner_values({"id": "c1"}, {"ev_battery_capacity_kwh": 40}, charger)
        assert FLAG not in charger

    def test_an_earlier_flag_stays_when_the_value_is_the_default(self):
        before = {"id": "c1", "ev_battery_capacity_kwh": 40, FLAG: True}
        charger = dict(before)
        _mark_owner_values(before, {"ev_battery_capacity_kwh": 40}, charger)
        assert charger[FLAG] is True

    def test_a_form_without_the_field_changes_nothing(self):
        charger = {"id": "c1"}
        _mark_owner_values({"id": "c1"}, {"name": "x"}, charger)
        assert FLAG not in charger


def _flow(chargers):
    entry = MagicMock()
    entry.data, entry.options = {}, {}
    flow = OptionsFlowHandler(entry)
    flow.hass = MagicMock()
    flow.hass.data = {}
    flow._data = {"ev_chargers": chargers}
    flow._edit_charger_id = "c1"
    return flow, entry


@pytest.mark.asyncio
async def test_editing_a_charger_keeps_the_flag_and_sets_it_for_a_typed_size():
    chargers = [{"id": "c1", "name": "Box", "ev_connected_sensor": "binary_sensor.x",
                 "ev_battery_capacity_kwh": 40, FLAG: True, "some_future_key": 7}]
    flow, entry = _flow(chargers)
    with patch.object(type(flow), "config_entry", new_callable=lambda: property(lambda s: entry)):
        await flow.async_step_ev_charger_edit({"charger_name": "Box", "ev_battery_capacity_kwh": 40})
    after = flow._data["ev_chargers"][0]
    assert after[FLAG] is True and after["some_future_key"] == 7

    fresh = [{"id": "c1", "name": "Box", "ev_connected_sensor": "binary_sensor.x"}]
    flow, entry = _flow(fresh)
    with patch.object(type(flow), "config_entry", new_callable=lambda: property(lambda s: entry)):
        await flow.async_step_ev_charger_edit({"charger_name": "Box", "ev_battery_capacity_kwh": 58})
    assert flow._data["ev_chargers"][0][FLAG] is True
