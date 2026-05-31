"""Integration tests for the EV deadline + tariff wiring (#246/#247).

Covers the pieces around the pure planner (tested in test_ev_tariff_planner):
- find_cheapest_hours(prefer_consecutive=...) block-wise selection
- _compute_night_plan gathering inputs from config/tariff/switch state
- the daytime tariff pause in _determine_charging_strategy
- the deadline current-floor applied in _execute_ev_control's night branch
"""
import logging
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.consts.states import ChargingState
from custom_components.solar_energy_management.coordinator import SEMCoordinator
from custom_components.solar_energy_management.coordinator.charging_control import (
    ChargingContext,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings
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
def _make_device(device_id="keba", max_current=32, session_active=False,
                 current_setpoint=0):
    dev = MagicMock()
    dev.device_id = device_id
    dev.max_current = max_current
    dev.min_current = 6
    dev.phases = 3
    dev.voltage = 230
    dev._session_active = session_active
    dev._current_setpoint = current_setpoint
    dev.managed_externally = False
    dev._set_current = AsyncMock()
    dev.start_session = AsyncMock()
    dev.stop_session = AsyncMock()
    return dev


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


# ---------------------------------------------------------------------------
# Daytime tariff pause in _determine_charging_strategy (#247)
# ---------------------------------------------------------------------------
class TestDaytimeTariffPause:
    def _power(self, battery_soc=50.0, **kw):
        return PowerReadings(solar_power=3000.0, battery_soc=battery_soc,
                             ev_connected=True, **kw)

    def test_solar_plus_cheap_pauses_when_expensive(self):
        """Post-#277 Phase C: ``solar_plus_cheap`` mode (the consolidated
        successor of legacy ``minpv + tariff_on``) falls back to pure
        self-consumption during EXPENSIVE windows. Previously this was
        ``minpv → pv fallthrough``; now it's ``solar_plus_cheap →
        self_consumption``."""
        coord = _build_coordinator(tariff_on=True, price_level=PriceLevel.EXPENSIVE)
        coord.time_manager.is_night_mode = MagicMock(return_value=False)
        cfg = {"id": "keba", "charge_mode": "solar_plus_cheap"}
        strategy, reason = coord._determine_charging_strategy(
            self._power(battery_soc=50), MagicMock(daily_ev=0.0), cfg)
        # solar_plus_cheap + EXPENSIVE → self_consumption strategy
        # (returns "solar_only" as the strategy string)
        assert strategy != "min_pv"
        assert strategy == "solar_only"

    def test_solar_plus_cheap_continues_when_price_normal(self):
        """At NORMAL price, ``solar_plus_cheap`` doesn't pause — falls
        through to zone logic. Pre-Phase-C this returned ``min_pv``
        for ``minpv + tariff_on + NORMAL``; Phase C's ``min_plus_solar``
        successor goes through zone logic instead.
        """
        coord = _build_coordinator(tariff_on=True, price_level=PriceLevel.NORMAL)
        coord.time_manager.is_night_mode = MagicMock(return_value=False)
        cfg = {"id": "keba", "charge_mode": "solar_plus_cheap"}
        strategy, reason = coord._determine_charging_strategy(
            self._power(battery_soc=50), MagicMock(daily_ev=0.0), cfg)
        # Zone-based with battery_soc=50 → Zone 2 (priority..buffer)
        # → solar_only strategy.
        assert strategy == "solar_only"

    def test_min_plus_solar_ignores_tariff_signal(self):
        """``min_plus_solar`` doesn't consult tariff — the tariff
        gate only fires for ``solar_plus_cheap`` post-Phase-C. The
        legacy ``minpv + tariff_off`` setup migrates to
        ``min_plus_solar``; daytime behaviour is now zone-based
        (per the maintainer's Phase C decision), so an EXPENSIVE
        price label doesn't pause anything."""
        coord = _build_coordinator(tariff_on=False, price_level=PriceLevel.EXPENSIVE)
        coord.time_manager.is_night_mode = MagicMock(return_value=False)
        cfg = {"id": "keba", "charge_mode": "min_plus_solar"}
        strategy, reason = coord._determine_charging_strategy(
            self._power(battery_soc=50), MagicMock(daily_ev=0.0), cfg)
        # Zone-based: SOC 50 → Zone 2 → solar_only
        assert strategy == "solar_only"


class TestTariffPauseWarningFlap:
    """``_tariff_pause_warned`` rate-limits the one-shot ``provider error''
    warning when the tariff provider raises while ``solar_plus_cheap`` is
    active. v1.6.3 review surfaced an unguarded code path: the original
    factoring cleared the flag in two places (the EXPENSIVE branch and the
    cheap-or-normal branch). The duplicated clear looked like a bug
    (reviewer flagged it), but the actual invariant is
    ``successful get_price_level() ⇒ flag cleared`` regardless of price.
    The refactor pulled the clear above the price-level branch so the
    invariant is local to one line. These tests pin that contract so a
    future split-by-branch doesn't silently restore the multi-warn loop.
    """

    def _power(self, battery_soc=50):
        return PowerReadings(
            solar_power=2000.0, grid_power=-500.0, home_consumption_power=1500.0,
            battery_power=0.0, battery_soc=battery_soc, ev_power=0.0,
            ev_connected=True, ev_charging=False,
        )

    def _drive(self, coord, n=1):
        """Run the daytime strategy ``n`` times for ``solar_plus_cheap``."""
        cfg = {"id": "keba", "charge_mode": "solar_plus_cheap"}
        coord.time_manager.is_night_mode = MagicMock(return_value=False)
        for _ in range(n):
            coord._determine_charging_strategy(
                self._power(battery_soc=50), MagicMock(daily_ev=0.0), cfg,
            )

    def test_warning_emitted_once_per_provider_outage(self, caplog):
        """A first provider error logs the warning; subsequent ticks
        during the same outage do not re-fire it."""
        coord = _build_coordinator(tariff_on=True)
        coord._tariff_provider.get_price_level = MagicMock(
            side_effect=RuntimeError("provider down"),
        )

        with caplog.at_level(logging.WARNING,
                             logger="custom_components.solar_energy_management.coordinator.coordinator"):
            self._drive(coord, n=5)

        msgs = [r.message for r in caplog.records
                if "Tariff-optimized daytime pause disabled" in r.message]
        assert len(msgs) == 1, (
            f"expected one warning across 5 ticks of a single outage; got {len(msgs)}"
        )
        assert coord._tariff_pause_warned is True

    def test_flag_cleared_on_successful_call_even_when_price_expensive(self):
        """Successful ``get_price_level()`` is the recovery signal — the
        flag must clear regardless of whether the returned price is
        CHEAP or EXPENSIVE. Pinning the v1.6.3 invariant: a provider
        recovery during an expensive window still re-arms the next
        warning rather than letting it silently re-fire."""
        coord = _build_coordinator(tariff_on=True)
        # Tick 1: provider errors → flag set
        coord._tariff_provider.get_price_level = MagicMock(
            side_effect=RuntimeError("provider down"),
        )
        self._drive(coord, n=1)
        assert coord._tariff_pause_warned is True

        # Tick 2: provider recovers but happens to return EXPENSIVE
        # → flag MUST clear (EXPENSIVE return is still a successful call).
        coord._tariff_provider.get_price_level = MagicMock(
            return_value=PriceLevel.EXPENSIVE,
        )
        self._drive(coord, n=1)
        assert coord._tariff_pause_warned is False, (
            "successful read with EXPENSIVE price must clear the flag; "
            "otherwise the next outage silently fails the rate-limit "
            "because the flag is already True"
        )

    def test_flag_cleared_on_successful_call_with_cheap_price(self):
        """Same invariant via the other branch — successful CHEAP read
        also clears the flag."""
        coord = _build_coordinator(tariff_on=True)
        coord._tariff_provider.get_price_level = MagicMock(
            side_effect=RuntimeError("provider down"),
        )
        self._drive(coord, n=1)
        assert coord._tariff_pause_warned is True

        coord._tariff_provider.get_price_level = MagicMock(
            return_value=PriceLevel.CHEAP,
        )
        self._drive(coord, n=1)
        assert coord._tariff_pause_warned is False

    def test_warning_re_fires_after_recovery_then_new_outage(self, caplog):
        """Recovery resets the rate-limit, so a fresh outage warns
        again. This is the user-visible behaviour the suppression
        wants: notify on transitions, not every tick of a continuous
        outage."""
        coord = _build_coordinator(tariff_on=True)

        # Outage 1
        coord._tariff_provider.get_price_level = MagicMock(
            side_effect=RuntimeError("provider down"),
        )
        with caplog.at_level(logging.WARNING,
                             logger="custom_components.solar_energy_management.coordinator.coordinator"):
            self._drive(coord, n=3)

            # Recovery
            coord._tariff_provider.get_price_level = MagicMock(
                return_value=PriceLevel.CHEAP,
            )
            self._drive(coord, n=2)

            # Outage 2
            coord._tariff_provider.get_price_level = MagicMock(
                side_effect=RuntimeError("provider down again"),
            )
            self._drive(coord, n=3)

        msgs = [r.message for r in caplog.records
                if "Tariff-optimized daytime pause disabled" in r.message]
        assert len(msgs) == 2, (
            f"expected one warning per outage across 2 outages; got {len(msgs)}"
        )


# ---------------------------------------------------------------------------
# Deadline floor in _execute_ev_control night branch (#246)
# ---------------------------------------------------------------------------
class TestDeadlineFloorApplied:
    @pytest.mark.asyncio
    async def test_fresh_start_uses_deadline_floor(self):
        coord = _build_coordinator(config_overrides={"target_peak_limit": 50.0})
        dev = _make_device(session_active=False)
        coord._ev_device = dev
        coord._night_target_per_charger = None
        ctx = ChargingContext(night_target_kwh=20.0, night_deadline_amps=20,
                              night_deadline_active=True)
        power = PowerReadings(home_consumption_power=500.0, ev_power=0.0,
                              ev_connected=True)
        await coord._execute_ev_control(
            ChargingState.NIGHT_CHARGING_ACTIVE, power, MagicMock(), ctx)
        # initial would be min(10, peak~32)=10; deadline floor 20 overrides it.
        dev._set_current.assert_awaited_with(20)

    @pytest.mark.asyncio
    async def test_dynamic_deadline_overrides_gentle_ramp(self):
        coord = _build_coordinator(config_overrides={"target_peak_limit": 50.0})
        dev = _make_device(session_active=True, current_setpoint=10)
        coord._ev_device = dev
        coord._night_target_per_charger = None
        coord._ev_last_change_time = None
        ctx = ChargingContext(night_target_kwh=20.0, night_deadline_amps=20,
                              night_deadline_active=True)
        power = PowerReadings(home_consumption_power=500.0, ev_power=6900.0,
                              ev_connected=True)
        await coord._execute_ev_control(
            ChargingState.NIGHT_CHARGING_ACTIVE, power, MagicMock(), ctx)
        # gentle ramp would cap at 12 (10+2); deadline floor 20 overrides.
        dev._set_current.assert_awaited_with(20)

    @pytest.mark.asyncio
    async def test_tariff_wait_state_stops_session(self):
        coord = _build_coordinator()
        dev = _make_device(session_active=True, current_setpoint=10)
        coord._ev_device = dev
        ctx = ChargingContext(night_target_kwh=10.0)
        power = PowerReadings(ev_connected=True)
        await coord._execute_ev_control(
            ChargingState.TARIFF_WAITING_FOR_CHEAP, power, MagicMock(), ctx)
        dev.stop_session.assert_awaited()


# ---------------------------------------------------------------------------
# #315 — off-mode terminal-state must also stop self-charging chargers (KEBA)
# ---------------------------------------------------------------------------
class TestOffModeTerminatesActiveCharge:
    """When ``charge_mode=off`` and the charger is physically drawing power
    that SEM doesn't own (typical for KEBA P30 which self-resumes from a
    stored setpoint), the actuator's terminal-state branch must still call
    ``stop_session()`` so the per-brand disable fires every cycle until the
    contactor opens. Pre-#315 fix the terminal block only stopped if
    ``ev._session_active`` was True — which it never is when KEBA self-
    started without SEM mediation.
    """

    @pytest.mark.asyncio
    async def test_off_with_self_charging_keba_calls_stop_session(self):
        """KEBA drawing 4140 W on plug-in + mode=off → stop_session called."""
        coord = _build_coordinator()
        # session_active=False is the load-bearing precondition — SEM never
        # owned the session because KEBA self-started.
        dev = _make_device(session_active=False, current_setpoint=0)
        coord._ev_device = dev
        ctx = ChargingContext(ev_connected=True, charging_strategy="disabled",
                              charging_strategy_reason="Charging disabled (mode=off)")
        power = PowerReadings(ev_connected=True, ev_power=4140.0)
        await coord._execute_ev_control(
            ChargingState.SOLAR_IDLE, power, MagicMock(), ctx)
        dev.stop_session.assert_awaited()

    @pytest.mark.asyncio
    async def test_off_with_handshake_only_no_stop_call(self):
        """KEBA at handshake idle (110 W) doesn't trigger the override —
        the 100 W threshold matches the actuator's existing 'actually
        charging vs handshake' cutoff so we don't spam stop_session every
        cycle while the EV is plugged in but parked."""
        coord = _build_coordinator()
        dev = _make_device(session_active=False, current_setpoint=0)
        coord._ev_device = dev
        ctx = ChargingContext(ev_connected=True, charging_strategy="disabled",
                              charging_strategy_reason="Charging disabled (mode=off)")
        power = PowerReadings(ev_connected=True, ev_power=110.0)
        await coord._execute_ev_control(
            ChargingState.SOLAR_IDLE, power, MagicMock(), ctx)
        dev.stop_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_off_with_inactive_session_and_no_ev_power_skips(self):
        """EV unplugged or fully off → terminal branch doesn't call stop_session
        (it was never started). Sanity check the override doesn't fire
        when there's nothing to stop."""
        coord = _build_coordinator()
        dev = _make_device(session_active=False, current_setpoint=0)
        coord._ev_device = dev
        ctx = ChargingContext(ev_connected=False, charging_strategy="disabled")
        power = PowerReadings(ev_connected=False, ev_power=0.0)
        await coord._execute_ev_control(
            ChargingState.SOLAR_IDLE, power, MagicMock(), ctx)
        dev.stop_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_session_active_path_still_works(self):
        """The original SEM-owned session → stop_session path is unchanged.
        Pinned so the new override doesn't accidentally shadow it."""
        coord = _build_coordinator()
        dev = _make_device(session_active=True, current_setpoint=10)
        coord._ev_device = dev
        ctx = ChargingContext(ev_connected=True, charging_strategy="disabled")
        power = PowerReadings(ev_connected=True, ev_power=4140.0)
        await coord._execute_ev_control(
            ChargingState.SOLAR_IDLE, power, MagicMock(), ctx)
        dev.stop_session.assert_awaited()

    @pytest.mark.asyncio
    async def test_idle_strategy_does_not_trigger_override(self):
        """Generic ``"idle"`` (Zone 1, solar<200W, target met) must NOT
        trigger the override — only the explicit-off ``"disabled"`` does.
        Pre-refinement check: prevents the #305 conflation from creeping
        back in via the actuator path."""
        coord = _build_coordinator()
        dev = _make_device(session_active=False, current_setpoint=0)
        coord._ev_device = dev
        ctx = ChargingContext(ev_connected=True, charging_strategy="idle")
        power = PowerReadings(ev_connected=True, ev_power=4140.0)
        await coord._execute_ev_control(
            ChargingState.SOLAR_IDLE, power, MagicMock(), ctx)
        dev.stop_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_multi_charger_uses_per_charger_power(self):
        """Multi-charger reviewer BLOCK: ``power.ev_power`` is the global
        sum across all chargers (sensor_reader.py:426-434). Charger[0]=off
        idle, charger[1]=solar_only charging at 4 kW: pre-fix the global
        sum 4000 > 500 would trigger stop_session on charger[0]'s idle
        KEBA every cycle. The fix reads THIS charger's individual
        ``ev_charging_power_sensor`` from HA state instead. This test
        pins that behaviour by giving charger[0]=idle a per-charger
        sensor value of 0 while the global ``power.ev_power`` is 4000.
        """
        coord = _build_coordinator()
        # Two chargers in config — charger[0]=off, charger[1]=solar_only.
        coord.config["ev_chargers"] = [
            {"id": "keba", "charge_mode": "off",
             "ev_charging_power_sensor": "sensor.keba_p30_charging_power"},
            {"id": "wallbox", "charge_mode": "solar_only",
             "ev_charging_power_sensor": "sensor.wallbox_charging_power"},
        ]
        dev = _make_device(device_id="keba", session_active=False, current_setpoint=0)
        coord._ev_device = dev

        # Mock HA states: THIS charger (keba) at 0W, OTHER (wallbox) at 4kW.
        def states_get(eid):
            sb = MagicMock()
            sb.state = "0" if eid == "sensor.keba_p30_charging_power" else "4140"
            return sb
        coord.hass.states.get = states_get

        # Global sum is 4140 (would trip the > 500 check with old code).
        ctx = ChargingContext(ev_connected=True, charging_strategy="disabled")
        power = PowerReadings(ev_connected=True, ev_power=4140.0)
        await coord._execute_ev_control(
            ChargingState.SOLAR_IDLE, power, MagicMock(), ctx)
        # Per-charger 0W → not drawing → no spurious stop on idle charger.
        dev.stop_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_kw_unit_conversion_from_native_charger_sensor(self):
        """KEBA's native ``sensor.keba_p30_charging_power`` reports in
        kW. The first cut of ``_this_charger_power`` did a raw
        ``float(state.state)`` and compared 4.14 (kW) to the 500 W
        threshold — silently failed every cycle. Confirmed on PROD
        2026-05-31 15:26 during the v1.6.5 soak.

        This test pins unit-aware reading: a state value of "4.14" with
        ``unit_of_measurement="kW"`` is converted to 4140 W BEFORE the
        threshold check, so the override fires correctly.
        """
        coord = _build_coordinator()
        coord.config["ev_chargers"] = [{
            "id": "keba", "charge_mode": "off",
            "ev_charging_power_sensor": "sensor.keba_p30_charging_power",
        }]
        dev = _make_device(device_id="keba", session_active=False, current_setpoint=0)
        coord._ev_device = dev

        def states_get(eid):
            if eid == "sensor.keba_p30_charging_power":
                s = MagicMock()
                s.state = "4.14"  # KEBA reports kW
                s.attributes = {"unit_of_measurement": "kW"}
                return s
            return None
        coord.hass.states.get = states_get

        ctx = ChargingContext(ev_connected=True, charging_strategy="disabled")
        # ``power.ev_power`` is the fallback (already in W); doesn't matter
        # here because the per-charger sensor read takes precedence.
        power = PowerReadings(ev_connected=True, ev_power=0.0)
        await coord._execute_ev_control(
            ChargingState.SOLAR_IDLE, power, MagicMock(), ctx)
        dev.stop_session.assert_awaited()

    @pytest.mark.asyncio
    async def test_w_unit_passes_through(self):
        """A charger that reports in W (most non-KEBA) is read raw."""
        coord = _build_coordinator()
        coord.config["ev_chargers"] = [{
            "id": "wallbox", "charge_mode": "off",
            "ev_charging_power_sensor": "sensor.wallbox_charging_power",
        }]
        dev = _make_device(device_id="wallbox", session_active=False)
        coord._ev_device = dev

        def states_get(eid):
            if eid == "sensor.wallbox_charging_power":
                s = MagicMock()
                s.state = "4140"  # Wallbox reports W
                s.attributes = {"unit_of_measurement": "W"}
                return s
            return None
        coord.hass.states.get = states_get

        ctx = ChargingContext(ev_connected=True, charging_strategy="disabled")
        power = PowerReadings(ev_connected=True, ev_power=0.0)
        await coord._execute_ev_control(
            ChargingState.SOLAR_IDLE, power, MagicMock(), ctx)
        dev.stop_session.assert_awaited()

    @pytest.mark.asyncio
    async def test_log_suppression_then_reset(self):
        """Per-charger ``_off_mode_stop_logged_for`` debounces the WARNING.

        Cycle 1: KEBA self-resumes, WARNING fires, flag set to device_id.
        Cycle 2: KEBA still resuming, stop_session called again but
                 WARNING is suppressed (flag matches device_id).
        Cycle 3: ev_power drops below threshold, flag cleared so the
                 next episode logs loudly again.
        """
        coord = _build_coordinator()
        dev = _make_device(session_active=False, current_setpoint=0)
        coord._ev_device = dev
        ctx = ChargingContext(ev_connected=True, charging_strategy="disabled")

        # Cycle 1: self-resume.
        power = PowerReadings(ev_connected=True, ev_power=4140.0)
        await coord._execute_ev_control(
            ChargingState.SOLAR_IDLE, power, MagicMock(), ctx)
        assert coord._off_mode_stop_logged_for == "keba"

        # Cycle 2: still resuming. stop_session called again, flag stays.
        dev.stop_session.reset_mock()
        await coord._execute_ev_control(
            ChargingState.SOLAR_IDLE, power, MagicMock(), ctx)
        dev.stop_session.assert_awaited()  # still called every cycle
        assert coord._off_mode_stop_logged_for == "keba"  # but flag prevents log

        # Cycle 3: KEBA finally stopped (ev_power below threshold).
        power = PowerReadings(ev_connected=True, ev_power=110.0)
        await coord._execute_ev_control(
            ChargingState.SOLAR_IDLE, power, MagicMock(), ctx)
        # Flag cleared so the next self-resume logs loudly again.
        assert coord._off_mode_stop_logged_for is None
