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

    def test_tariff_wait_when_cheap_window_ahead(self):
        coord = _build_coordinator(tariff_on=True)
        base = dt_util.now().replace(hour=22, minute=0, second=0, microsecond=0)
        # Two consecutive cheap hours ahead. Peak-managed rate here is
        # (6 kW peak - ~0.75 kW home)/690 ≈ 7 A ≈ 4.8 kW; 2 h * 4.8 ≈ 9.6 kWh,
        # which covers an 8 kWh need at the realistic rate → wait is viable.
        cheap = [
            PricePoint(timestamp=base.replace(hour=1) + timedelta(days=1), price=0.1, level=PriceLevel.CHEAP),
            PricePoint(timestamp=base.replace(hour=2) + timedelta(days=1), price=0.1, level=PriceLevel.CHEAP),
        ]
        coord._tariff_provider.find_cheapest_hours = MagicMock(return_value=cheap)
        # #277 Phase C: tariff intent now carried by charge_mode.
        cfg = {"id": "keba", "ev_min_current": 6, "ev_target_time": "07:00",
               "charge_mode": "solar_plus_cheap"}
        with patch.object(dt_util, "now", return_value=base):
            plan = coord._compute_night_plan(cfg, remaining_to_min_kwh=8.0)
        assert plan.should_wait_for_cheap

    def test_peak_limited_declines_unfillable_wait(self):
        # C1 regression (#274): one cheap hour cannot deliver 10 kWh at the
        # peak-limited rate (~4.8 kW), so the planner must NOT wait — it charges
        # now (using all hours) to guarantee Min, instead of waiting then missing.
        coord = _build_coordinator(tariff_on=True)
        base = dt_util.now().replace(hour=22, minute=0, second=0, microsecond=0)
        cheap = [PricePoint(timestamp=base.replace(hour=1) + timedelta(days=1),
                            price=0.1, level=PriceLevel.CHEAP)]
        coord._tariff_provider.find_cheapest_hours = MagicMock(return_value=cheap)
        # #277 Phase C: tariff intent now carried by charge_mode.
        cfg = {"id": "keba", "ev_min_current": 6, "ev_target_time": "07:00",
               "charge_mode": "solar_plus_cheap"}
        with patch.object(dt_util, "now", return_value=base):
            plan = coord._compute_night_plan(cfg, remaining_to_min_kwh=10.0)
        assert not plan.should_wait_for_cheap

    def test_predictor_pattern_sizes_peak_rate(self):
        # Predictor-based path (#274): a high learned overnight load shrinks the
        # peak headroom, so even a generous cheap window can't fill Min → no wait.
        coord = _build_coordinator(tariff_on=True)
        coord._predictor = MagicMock()
        # 5500 W learned night load → headroom 6000-5500=500 W → clamps to min (6A,
        # ~4.1 kW)... so use a load that drops realistic rate below the need.
        coord._predictor.predict_consumption_24h = MagicMock(return_value=[5500.0] * 24)
        coord.time_manager.get_night_window_hours = MagicMock(return_value=8.0)
        base = dt_util.now().replace(hour=22, minute=0, second=0, microsecond=0)
        cheap = [PricePoint(timestamp=base.replace(hour=h) + timedelta(days=1),
                            price=0.1, level=PriceLevel.CHEAP) for h in (1, 2)]
        coord._tariff_provider.find_cheapest_hours = MagicMock(return_value=cheap)
        # #277 Phase C: tariff intent now carried by charge_mode.
        cfg = {"id": "keba", "ev_min_current": 6, "ev_target_time": "07:00",
               "charge_mode": "solar_plus_cheap"}
        with patch.object(dt_util, "now", return_value=base):
            plan = coord._compute_night_plan(cfg, remaining_to_min_kwh=12.0)
        # 2 cheap h at min-clamped ~4.1 kW ≈ 8.3 kWh < 12 → must not wait
        assert not plan.should_wait_for_cheap

    def test_no_tariff_no_wait(self):
        coord = _build_coordinator(tariff_on=False)
        cfg = {"id": "keba", "ev_target_time": "07:00"}
        plan = coord._compute_night_plan(cfg, remaining_to_min_kwh=10.0)
        assert not plan.should_wait_for_cheap

    def test_lookahead_capped_at_hours_to_deadline(self):
        # #281/D1, S1: caller MUST NOT ask the tariff provider for slots past
        # the deadline. Otherwise a post-deadline price dip can be returned as
        # "the cheap window", silently dropping the real pre-deadline option.
        coord = _build_coordinator(tariff_on=True)
        # 22:00 with deadline 07:00 → 9 hours horizon, must clamp the 12h
        # global lookahead down to 9.
        base = dt_util.now().replace(hour=22, minute=0, second=0, microsecond=0)
        coord._tariff_provider.find_cheapest_hours = MagicMock(return_value=[])
        # #277 Phase C: tariff intent now carried by charge_mode.
        cfg = {"id": "keba", "ev_min_current": 6, "ev_target_time": "07:00",
               "charge_mode": "solar_plus_cheap"}
        with patch.object(dt_util, "now", return_value=base):
            coord._compute_night_plan(cfg, remaining_to_min_kwh=8.0)
        # The provider was queried — assert the lookahead is the deadline horizon.
        call = coord._tariff_provider.find_cheapest_hours.call_args
        assert call is not None, "find_cheapest_hours must be called when tariff is on"
        # within_hours is a kwarg
        within_hours = call.kwargs.get("within_hours")
        assert within_hours is not None
        assert within_hours <= 10, (
            f"lookahead must be capped at ~9h to deadline, got {within_hours}h "
            "— the global 12h lookahead is leaking through (#281/D1)"
        )

    def test_lookahead_uncapped_when_no_deadline_resolvable(self):
        # Fallback path: when target_time / night_end are both unresolvable,
        # the global EV_DEADLINE_LOOKAHEAD_HOURS still bounds the query.
        #
        # The defensive fallback at ev_control.py:119-122 makes ``night_end``
        # default to ``DEFAULT_EV_TARGET_TIME`` ("07:00") when
        # ``get_night_end_time`` raises — so in practice the "truly
        # unresolvable" path is unreachable from production code. To exercise
        # this fallback path's regression guard, we patch the default to
        # None so ``resolve_deadline(now, night_end=None)`` correctly returns
        # None and the code falls through to the bare ``EV_DEADLINE_LOOKAHEAD_HOURS``.
        coord = _build_coordinator(tariff_on=True)
        coord.time_manager.get_night_end_time = MagicMock(side_effect=ValueError("bust"))
        coord._tariff_provider.find_cheapest_hours = MagicMock(return_value=[])
        # #277 Phase C: tariff intent now carried by charge_mode.
        cfg = {"id": "keba", "ev_min_current": 6, "ev_target_time": None,
               "charge_mode": "solar_plus_cheap"}
        with patch(
            "custom_components.solar_energy_management.coordinator.ev_control."
            "DEFAULT_EV_TARGET_TIME",
            None,
        ):
            coord._compute_night_plan(cfg, remaining_to_min_kwh=8.0)
        call = coord._tariff_provider.find_cheapest_hours.call_args
        # Falls back to EV_DEADLINE_LOOKAHEAD_HOURS (12) — both deadlines unresolvable
        within_hours = call.kwargs.get("within_hours")
        assert within_hours == 12, f"expected global fallback 12h, got {within_hours}"

    def test_tariff_hysteresis_holds_decision_within_dwell(self):
        # M4 (#274): once charging (now cheap), a brief flip to "wait" within the
        # dwell must be held → no stop/start contactor cycling.
        coord = _build_coordinator(tariff_on=True)
        coord.config["ev_tariff_dwell_seconds"] = 600
        base = dt_util.now().replace(hour=22, minute=0, second=0, microsecond=0)
        # #277 Phase C: tariff intent now carried by charge_mode.
        cfg = {"id": "keba", "ev_min_current": 6, "ev_target_time": "07:00",
               "charge_mode": "solar_plus_cheap"}

        # Call 1: now IS cheap → charge now (should_wait False), records the decision.
        coord._tariff_provider.find_cheapest_hours = MagicMock(
            return_value=[PricePoint(timestamp=base, price=0.1, level=PriceLevel.CHEAP)])
        with patch.object(dt_util, "now", return_value=base):
            p1 = coord._compute_night_plan(cfg, remaining_to_min_kwh=8.0)
        assert not p1.should_wait_for_cheap

        # Call 2, 60 s later (within dwell): cheap window now ahead → raw says wait,
        # but the dwell holds the previous "charging" decision.
        cheap_ahead = [PricePoint(timestamp=base.replace(hour=h) + timedelta(days=1),
                                  price=0.1, level=PriceLevel.CHEAP) for h in (1, 2, 3)]
        coord._tariff_provider.find_cheapest_hours = MagicMock(return_value=cheap_ahead)
        with patch.object(dt_util, "now", return_value=base + timedelta(seconds=60)):
            p2 = coord._compute_night_plan(cfg, remaining_to_min_kwh=8.0)
        assert not p2.should_wait_for_cheap  # held — not flipped to wait


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
