"""Integration tests for the EV deadline + tariff wiring (#246/#247).

Covers the pieces around the pure planner (tested in test_ev_tariff_planner):
- find_cheapest_hours(prefer_consecutive=...) block-wise selection
- _compute_night_plan gathering inputs from config/tariff/switch state

(The deadline current-floor + off-mode self-resume actuator tests that
used to live here exercised the now-removed legacy ``_execute_ev_control``
path. Their behaviour is covered at the pure layer by
``test_decide.py`` (deadline floor, tariff-wait → idle) and
``test_charger_reconciler.py`` / ``test_keba_zero_amps_353.py``
(off/idle self-resume disable). Removed in Task 11 B.)
"""
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.consts.states import ChargingState
from custom_components.solar_energy_management.coordinator import SEMCoordinator
from custom_components.solar_energy_management.tariff.tariff_provider import (
    DynamicTariffProvider,
    PriceLevel,
    PricePoint,
)


# ---------------------------------------------------------------------------
# find_cheapest_hours — block-wise (#247)
# ---------------------------------------------------------------------------
def _provider_with_prices(price_seq):
    now = dt_util.now().replace(minute=0, second=0, microsecond=0)
    prices = [
        PricePoint(timestamp=now + timedelta(hours=i), price=p, level=PriceLevel.NORMAL)
        for i, p in enumerate(price_seq)
    ]
    prov = DynamicTariffProvider.__new__(DynamicTariffProvider)
    prov._read_prices_list = lambda: prices
    return prov, now


class TestFindCheapestHoursBlockwise:
    def test_consecutive_prefers_contiguous_block(self):
        # Alternating cheap/expensive: scattered would pick the 3 isolated dips,
        # block-wise picks the cheapest contiguous run of 3.
        prov, now = _provider_with_prices([0.3, 0.1, 0.3, 0.1, 0.3, 0.1])
        block = prov.find_cheapest_hours(3, within_hours=12, prefer_consecutive=True)
        starts = [p.timestamp for p in block]
        # contiguous → three consecutive hours
        deltas = [(starts[i + 1] - starts[i]).total_seconds() for i in range(len(starts) - 1)]
        assert all(d == 3600 for d in deltas)
        assert len(block) == 3

    def test_scattered_default_picks_globally_cheapest(self):
        prov, now = _provider_with_prices([0.3, 0.1, 0.3, 0.1, 0.3, 0.1])
        scattered = prov.find_cheapest_hours(3, within_hours=12, prefer_consecutive=False)
        # the three cheapest are the 0.1 dips — not contiguous
        assert len(scattered) == 3
        assert all(abs(p.price - 0.1) < 1e-9 for p in scattered)

    def test_block_returns_lowest_sum_window(self):
        # Cheapest contiguous pair is the last two (0.1, 0.1).
        prov, now = _provider_with_prices([0.5, 0.5, 0.5, 0.5, 0.1, 0.1])
        block = prov.find_cheapest_hours(2, within_hours=12, prefer_consecutive=True)
        assert [round(p.price, 2) for p in block] == [0.1, 0.1]


# ---------------------------------------------------------------------------
# Coordinator harness
# ---------------------------------------------------------------------------
def _build_coordinator(config_overrides=None, tariff_on=False, price_level=PriceLevel.NORMAL):
    with patch.object(SEMCoordinator, "__init__", return_value=None):
        coord = SEMCoordinator.__new__(SEMCoordinator)
    # Post-#277 Phase C: tariff intent is carried by the named
    # ``charge_mode`` (``solar_plus_cheap`` ↔ tariff_on). The legacy
    # ``switch.sem_charger_<id>_tariff_optimized`` was removed.
    charger = {
        "id": "keba", "ev_min_current": 6, "ev_night_initial_current": 10,
        "charge_mode": "solar_plus_cheap" if tariff_on else "min_plus_solar",
    }
    coord.config = {
        "ev_chargers": [charger],
        "ev_max_current": 32,
        "target_peak_limit": 6.0,
        "ev_ramp_rate_amps": 2,
        "ev_stall_cooldown": 120,
    }
    if config_overrides:
        coord.config.update(config_overrides)

    coord._load_manager = None
    coord.time_manager = MagicMock()
    coord.time_manager.is_night_mode = MagicMock(return_value=True)
    coord.time_manager.get_night_end_time = MagicMock(return_value="07:00")

    # hass is unused by ``_tariff_optimized_for`` post-Phase-C (the
    # resolver is a pure ``charge_mode`` lookup), but provide a stub
    # for the few other code paths the strategy machine touches.
    coord.hass = MagicMock()
    coord.hass.states.is_state = MagicMock(return_value=False)

    # tariff provider
    coord._tariff_provider = MagicMock()
    coord._tariff_provider.get_price_level = MagicMock(return_value=price_level)
    coord._tariff_provider.find_cheapest_hours = MagicMock(return_value=[])

    # attrs read by _determine_charging_strategy
    coord._cycle_vehicle_soc = None
    coord._cycle_forecast = MagicMock(available=False)
    coord._forecast_reader = MagicMock()
    coord._forecast_reader.read_forecast = MagicMock(return_value=MagicMock(available=False))
    coord._forecast_tracker = MagicMock(dampening_factor=1.0)
    coord._state_machine = MagicMock()
    coord._state_machine.current_state = ChargingState.SOLAR_IDLE
    coord.config.setdefault("battery_capacity_kwh", 15)

    coord._ev_device = None
    return coord


# ---------------------------------------------------------------------------
# _compute_night_plan (#246/#247)
# ---------------------------------------------------------------------------
class TestComputeNightPlan:
    def test_short_deadline_sets_floor(self):
        coord = _build_coordinator()
        cfg = {"id": "keba", "ev_min_current": 6, "ev_target_time": "02:00"}
        with patch.object(dt_util, "now", return_value=dt_util.now().replace(
                hour=22, minute=0, second=0, microsecond=0)):
            plan = coord._compute_night_plan(cfg, remaining_to_min_kwh=20.0)
        assert plan.deadline_active
        assert plan.deadline_amps >= 7

    def test_no_tariff_no_wait(self):
        coord = _build_coordinator(tariff_on=False)
        cfg = {"id": "keba", "ev_target_time": "07:00"}
        plan = coord._compute_night_plan(cfg, remaining_to_min_kwh=10.0)
        assert not plan.should_wait_for_cheap

    def test_predictor_pattern_shrinks_top_up_rate(self):
        """(#274 kept half) The learned overnight load still shrinks the
        peak-managed top-up rate — that guarantee math survived the
        selector retirement (#638 one-gate C3)."""
        coord = _build_coordinator(tariff_on=True)
        base = dt_util.now().replace(hour=22, minute=0, second=0, microsecond=0)
        cfg = {"id": "keba", "ev_min_current": 6, "ev_target_time": "07:00",
               "charge_mode": "solar_plus_cheap"}
        coord.time_manager.get_night_window_hours = MagicMock(return_value=8.0)
        coord._predictor = MagicMock()
        coord._predictor.predict_consumption_24h = MagicMock(return_value=[400.0] * 24)
        with patch.object(dt_util, "now", return_value=base):
            light = coord._compute_night_plan(cfg, remaining_to_min_kwh=12.0)
        coord._predictor.predict_consumption_24h = MagicMock(return_value=[5000.0] * 24)
        with patch.object(dt_util, "now", return_value=base):
            heavy = coord._compute_night_plan(cfg, remaining_to_min_kwh=12.0)
        assert heavy.top_up_amps < light.top_up_amps


def test_spotmarket_provider_arg_order(monkeypatch):
    # H4 (#274): SpotMarketProvider must not land export_rate in the
    # forecast_entity positional slot.
    from custom_components.solar_energy_management.tariff.tariff_provider import (
        SpotMarketProvider,
    )
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    prov = SpotMarketProvider(hass, price_entity="sensor.spot", export_rate=0.09)
    assert prov._forecast_entity is None       # not the 0.09 float
    assert prov.export_rate == 0.09
