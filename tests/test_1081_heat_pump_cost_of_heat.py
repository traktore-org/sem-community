"""#1081 Slice A/B — the heat pump's own COP, cost_of_heat, and the
comfort band wired onto it via ``ComfortBandMixin``."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.heat_cost import (
    cost_of_heat,
    heat_pump_price,
)
from custom_components.solar_energy_management.devices.base import (
    ComfortBandMixin,
)
from custom_components.solar_energy_management.devices.heat_pump_controller import (
    HeatPumpController,
)


# ── cost_of_heat() — pure function ──────────────────────────────────────

def test_cost_of_heat_divides_price_by_cop():
    assert cost_of_heat(0.30, 3.0) == pytest.approx(0.10)


def test_cost_of_heat_is_cheaper_at_a_higher_cop():
    mild = cost_of_heat(0.30, 4.0)
    cold = cost_of_heat(0.30, 2.0)
    assert mild < cold


def test_cost_of_heat_none_price_is_none():
    assert cost_of_heat(None, 3.0) is None


def test_cost_of_heat_none_cop_is_none():
    assert cost_of_heat(0.30, None) is None


def test_cost_of_heat_zero_cop_is_none():
    assert cost_of_heat(0.30, 0.0) is None


def test_cost_of_heat_negative_cop_is_none():
    assert cost_of_heat(0.30, -1.0) is None


def test_cost_of_heat_bad_cop_type_is_none():
    assert cost_of_heat(0.30, "not a number") is None


# ── HeatPumpController.cop ──────────────────────────────────────────────

def _controller(**kwargs) -> HeatPumpController:
    hass = MagicMock()
    hass.states.get.return_value = None
    return HeatPumpController(hass=hass, **kwargs)


def test_cop_defaults_to_3():
    assert _controller().cop == 3.0


def test_cop_takes_the_configured_value():
    assert _controller(cop=4.2).cop == 4.2


def test_cop_rejects_zero_and_falls_back():
    assert _controller(cop=0.0).cop == 3.0


def test_cop_rejects_negative_and_falls_back():
    assert _controller(cop=-2.0).cop == 3.0


def test_cop_is_in_to_dict():
    assert _controller(cop=3.5).to_dict()["cop"] == 3.5


# ── ComfortBandMixin wiring (Slice B) ───────────────────────────────────

def test_heat_pump_is_a_comfort_band_device():
    assert isinstance(_controller(), ComfortBandMixin)


def test_heat_pump_has_comfort_plan_demand():
    hp = _controller()
    assert callable(getattr(hp, "comfort_plan_demand", None))
    assert callable(getattr(hp, "record_comfort_sample", None))


def test_a_heat_pump_nobody_set_a_goal_on_is_disengaged():
    """Byte-for-byte today's behaviour: no goal, no band."""
    assert _controller().comfort_state == "disengaged"


def test_vacation_disengages_the_band_even_with_a_goal():
    hp = _controller()
    hp.comfort_target, hp.comfort_offset, hp.comfort_limit = 20.0, 1.0, 22.0
    hp.vacation = True
    assert hp.comfort_state == "disengaged"


def test_fallback_reading_is_the_pumps_own_temperature():
    hp = _controller(temperature_entity_id="sensor.hp_temp")
    hp.hass.states.get.return_value = MagicMock(
        state="19.5", attributes={"unit_of_measurement": "°C"})
    assert hp._comfort_fallback_reading() == 19.5


# ── heat_pump_price() — own tariff first, else the house's ──────────────
_NOW = datetime(2026, 11, 6, 18, 0)


class _House:
    def get_current_import_rate(self):
        return 0.42


def test_own_tariff_wins_over_the_house():
    own = MagicMock()
    own.price_at.return_value = 0.18
    assert heat_pump_price(own, _House(), _NOW) == 0.18
    own.price_at.assert_called_once_with(_NOW)


def test_no_own_tariff_uses_the_house_rate():
    # A heat pump without its own tariff got no cost of heat at all.
    assert heat_pump_price(None, _House(), _NOW) == 0.42
    assert cost_of_heat(heat_pump_price(None, _House(), _NOW), 3.0) == pytest.approx(0.14)


def test_no_tariff_anywhere_is_no_price():
    assert heat_pump_price(None, None, _NOW) is None
    assert heat_pump_price(None, object(), _NOW) is None


def test_a_non_number_rate_is_no_price():
    house = MagicMock()  # a MagicMock rate is not a price
    assert heat_pump_price(None, house, _NOW) is None
