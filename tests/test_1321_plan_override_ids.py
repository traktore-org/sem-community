"""#1321 — plan_override names a charger or a battery, nothing else.

A load id was stored and did nothing: no decider reads a load's override,
and the dashboard showed the button press as done.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator


def _coord():
    return SimpleNamespace(
        config={"ev_chargers": [{"id": "keba"}]},
        _known_battery_ids={"b1", "b2"},
        _plan_overrides={},
        _storage=MagicMock(),
    )


@pytest.mark.parametrize("device_id", ["keba", "b2", "primary"])
def test_a_charger_or_a_battery_is_taken(device_id):
    c = _coord()
    SEMCoordinator.set_plan_override(c, device_id, "skip", 60)
    assert device_id in c._plan_overrides


@pytest.mark.parametrize("device_id", ["load:boiler", "boiler", "ev:keba", ""])
def test_any_other_id_is_refused_and_nothing_is_stored(device_id):
    c = _coord()
    with pytest.raises(ValueError, match="not a charger or a battery"):
        SEMCoordinator.set_plan_override(c, device_id, "force", 60)
    assert c._plan_overrides == {}
    c._storage.set_plan_overrides.assert_not_called()
