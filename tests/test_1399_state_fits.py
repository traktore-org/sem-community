"""#1399 (found in the reporter's log) — a text state HA refuses.

While SEM yielded the charger to another party, every cycle logged::

    ERROR [homeassistant.core] State yields to another party (the charger's
    setting) — SEM holds its commands; SEM's own plan: idle, … for
    sensor.sem_charging_strategy is longer than 255, falling back to unknown

The coordinator clamps ``charging_strategy`` on the copy it hands the
notifications (``_clamp_state``), but the sensor reads the published
``SEMData`` copy, which nothing clamped. The fix sits where HA reads the
state: every text state of the sensor class.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.components.sensor import SensorEntityDescription

from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
)
from custom_components.solar_energy_management.coordinator.external_control import (
    yielded_charger_decision,
)
from custom_components.solar_energy_management.sensor import (
    MAX_STATE_LEN,
    SEMSolarSensor,
    _fit_state,
)

#: The reporter's own reason, word for word, before the yield was put in front.
LIVE_REASON = (
    "solar_plus_cheap day: tariff=expensive → pausing grid imports — "
    "solar_only: solar=400W < 1000W threshold [structural: below the solar "
    "minimum (solar 400W < 1000W)]")


def _yielded_text() -> str:
    d = ChargerDecision(charger_id="zaptec", mode="solar_plus_cheap",
                        intent=ChargerIntent.IDLE, reason=LIVE_REASON)
    return yielded_charger_decision(d).reason


def _sensor(coordinator, key):
    coordinator.data = {"last_update": "x"}
    coordinator.last_update_success = True
    return SEMSolarSensor(coordinator=coordinator,
                          description=SensorEntityDescription(key=key, name="x"),
                          entry_id="e")


@pytest.mark.unit
def test_the_live_text_is_over_the_limit():
    """The case is real: the yielded text the reporter's log shows is longer
    than HA takes. Without this the test below could pass on short input."""
    assert len(_yielded_text()) > MAX_STATE_LEN


@pytest.mark.unit
def test_the_strategy_sensor_state_fits(mock_coordinator):
    text = _yielded_text()
    s = _sensor(mock_coordinator, "charging_strategy")
    mock_coordinator.data = {"charging_strategy": text,
                             "charging_strategy_reason": text}
    s._update_from_coordinator()
    state = s._attr_native_value
    assert isinstance(state, str) and len(state) <= MAX_STATE_LEN
    assert state.endswith("…") and text.startswith(state[:-1])
    assert s._attr_available is True


@pytest.mark.unit
@pytest.mark.parametrize("value", [
    "short", "x" * MAX_STATE_LEN, 42, 3.5, None, True,
    SimpleNamespace(a=1),
])
def test_anything_already_fitting_passes_unchanged(value):
    assert _fit_state(value) is value


@pytest.mark.unit
def test_one_over_is_cut_to_the_limit():
    out = _fit_state("y" * (MAX_STATE_LEN + 1))
    assert len(out) == MAX_STATE_LEN and out.endswith("…")
