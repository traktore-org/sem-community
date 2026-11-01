"""#1090 — below an export VALUE, SEM stops exporting; it never buys for it.

A Dutch tariff from 2027: the import price stays positive (energy tax), the
export value goes negative (spot export minus the feed-in fee). The decided
behaviour: the grid sink closes, so the battery and the loads take the sun
first. Grid charging still needs a negative IMPORT price.

One rule, ``value_layer.export_not_worth``: the export value is below the
threshold (default 0.0, the old ``< 0`` — zero still exports).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
    BatteryChargeScheduler, SchedulerConfig, SchedulerState,
)
from custom_components.solar_energy_management.coordinator.forecast_sell import (
    evaluate_forecast_sell,
)
from custom_components.solar_energy_management.coordinator.sink_verdicts import (
    CLOSED, HELD, OPEN, sink_verdicts,
)
from custom_components.solar_energy_management.tariff import value_layer as vl

from .test_873_cycle_executes import WIRED, _hass, _sensors, run_cycle, sealed_nights

KEY = vl.CONF_EXPORT_VALUE_THRESHOLD
NOW = datetime(2026, 6, 1, 12, 0)

#: A Dutch day: import 0.25 (energy tax keeps it positive), spot export 0.05,
#: a per-kWh feed-in fee of 0.07 — the export VALUE is -0.02.
DUTCH = {
    "tariff_mode": "dynamic",
    "dynamic_tariff_entity": "sensor.price",
    "dynamic_feedin_entity": "sensor.feedin",
    "feed_in_fee_model": vl.FEE_PER_KWH,
    "feed_in_fee": 0.07,
    "currency": "EUR",
    "export_guard_enabled": True,
}
SPOT = {k: v for k, v in DUTCH.items()
        if k not in ("feed_in_fee_model", "feed_in_fee")}


def _states(price=0.25, feedin=0.05):
    st = _sensors(6000, 3000, 0, 60)          # 3 kW leaving the house, SOC 60
    st["sensor.price"] = price
    st["sensor.feedin"] = feedin
    return st


async def _two_cycles(config, states):
    """Two real turns: the pacing state is published one cycle after the
    pacer ran, so the second turn shows what the first one decided."""
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    from custom_components.solar_energy_management.consts.core import (
        BATTERY_SOC_STEP_CONFIRM_READS,
    )
    coord = SEMCoordinator(_hass(states), dict(config))
    coord.config_entry = None
    nights = sealed_nights()
    coord._battery_night = SimpleNamespace(sealed=lambda: nights)
    # (#1284) the first SOC after a start counts once it has repeated; this
    # home is already running, as in run_cycle
    for _ in range(BATTERY_SOC_STEP_CONFIRM_READS - 1):
        coord._sensor_reader.read_power()
    await coord._async_update_data()
    return await coord._async_update_data()


def _verdicts(export_rate, threshold=vl.DEFAULT_EXPORT_VALUE_THRESHOLD, **kw):
    base = dict(now=NOW, tariff_level="normal", upcoming=[],
                export_rate=export_rate, export_rate_known=True,
                export_guard_enabled=True, house_sink_enabled=False,
                morning_window_enabled=False, departure=None, morning_hours=2.0,
                forecast_refills_pack=False, pacing_horizon_end=None,
                export_threshold=threshold)
    base.update(kw)
    return sink_verdicts(**base)


# ── the one rule ────────────────────────────────────────────────────────

class TestTheRule:
    def test_below_the_threshold_is_not_worth_it(self):
        assert vl.export_not_worth(-0.02) is True
        assert vl.export_not_worth(0.03, 0.05) is True
        assert vl.export_not_worth(0.05, 0.05) is False

    def test_zero_still_exports_at_the_default(self):
        """develop closed on ``< 0.0``: a zero price kept the meter open."""
        assert vl.export_not_worth(0.0) is False

    def test_an_unread_value_is_no_answer(self):
        for bad in (None, "unknown", float("nan"), True):
            assert vl.export_not_worth(bad) is None

    def test_the_threshold_reads_from_the_options(self):
        assert vl.export_value_threshold({}) == 0.0
        assert vl.export_value_threshold({KEY: "0.04"}) == 0.04
        assert vl.export_value_threshold({KEY: -0.01}) == -0.01   # a loss accepted
        for bad in (None, "x", float("inf"), True):
            assert vl.export_value_threshold({KEY: bad}) == 0.0


# ── the consumers ask it ────────────────────────────────────────────────

class TestTheGridSink:
    def test_a_negative_value_closes_the_meter(self):
        assert _verdicts(-0.02).state_of("grid_export") == CLOSED

    def test_default_keeps_the_old_reason_and_zero_open(self):
        v = _verdicts(-0.01)["grid_export"]
        assert v.reason == "export price negative — the meter is closed"
        assert _verdicts(0.0).state_of("grid_export") == OPEN

    def test_a_threshold_above_zero_closes_earlier(self):
        assert _verdicts(0.03).state_of("grid_export") == OPEN
        assert _verdicts(0.03, 0.05).state_of("grid_export") == CLOSED

    def test_the_closed_window_follows_the_value_per_slot(self):
        """A Dutch import curve never reads NEGATIVE; the value does. The
        battery keeps headroom for the window the value opens."""
        ups = [SimpleNamespace(timestamp=NOW + timedelta(hours=h), level="normal")
               for h in range(0, 6)]

        def value_at(ts):
            return -0.02 if 14 <= ts.hour < 16 else 0.05

        out = _verdicts(0.05, upcoming=ups, export_at=value_at,
                        pacing_horizon_end=NOW.replace(hour=20))
        assert out.state_of("grid_export") == OPEN
        assert out["grid_export"].until == NOW.replace(hour=14)
        assert out.state_of("battery") == HELD
        assert out["battery"].until == NOW.replace(hour=14)
        # without the value reader the window is the level's, as before
        assert _verdicts(0.05, upcoming=ups).state_of("battery") == OPEN


class TestNoSaleBelowTheThreshold:
    def _sell(self, rate, threshold=0.0):
        return evaluate_forecast_sell(
            NOW, enabled=True, in_block=True, block_w=3000.0, spendable_kwh=5.0,
            max_discharge_w=5000.0, dynamic_floor_pct=None, reserve_pct=20.0,
            export_rate=rate, export_rate_known=True, export_threshold=threshold)

    def test_forecast_sell(self):
        assert self._sell(0.03).state is SchedulerState.DISCHARGING_ARBITRAGE
        held = self._sell(0.03, 0.05)
        assert held.state is SchedulerState.IDLE
        assert "not worth exporting" in held.reason
        assert self._sell(0.0).state is SchedulerState.IDLE    # as before

    def test_arbitrage(self):
        s = BatteryChargeScheduler(MagicMock(), SchedulerConfig(
            arbitrage_enabled=True, arbitrage_min_export_price=0.20,
            arbitrage_reserve_soc=50.0, roundtrip_efficiency=0.9))
        assert (s.evaluate_arbitrage(80.0, 0.45, 0.10).state
                is SchedulerState.DISCHARGING_ARBITRAGE)
        d = s.evaluate_arbitrage(80.0, 0.45, 0.10, export_threshold=0.50)
        assert d.state is SchedulerState.NOT_PROFITABLE
        assert "not worth exporting" in d.reason


class TestGridChargingStillNeedsANegativeImport:
    def _evaluate(self, import_price):
        s = BatteryChargeScheduler(MagicMock(), SchedulerConfig(
            enabled=True, force_charge_on_negative_price=True))
        return s.evaluate(current_soc=50.0, forecast_tomorrow_kwh=30.0,
                          expected_consumption_kwh=10.0, off_peak_rate=0.20,
                          peak_rate=0.30, current_price=import_price)

    def test_a_dutch_hour_buys_nothing(self):
        assert self._evaluate(0.25).price_forced is False

    def test_a_negative_import_still_force_charges(self):
        d = self._evaluate(-0.01)
        assert d.price_forced is True and d.state is SchedulerState.SCHEDULED


# ── the whole cycle ─────────────────────────────────────────────────────

class TestADutchDayThroughTheCycle:
    @pytest.mark.asyncio
    async def test_the_grid_closes_and_the_pack_takes_the_sun(self):
        out = await _two_cycles({**WIRED, **DUTCH}, _states())
        assert out["tariff_current_import_rate"] == pytest.approx(0.25)
        assert out["tariff_current_export_rate"] == pytest.approx(-0.02)
        assert out["sink_verdicts"]["grid_export"]["state"] == "closed", out["sink_verdicts"]
        assert out["export_guard_state"] == "holding"      # engages after the hold
        # the pack is not paced away from the sun while the meter is shut
        assert out["charge_pacing"]["reason_code"] == "closed_meter"
        assert out["charge_pacing"]["cap_w"] is None

    @pytest.mark.asyncio
    async def test_without_the_fee_the_same_day_exports(self):
        """Spot export 0.05, no fee, default threshold: develop's answer."""
        out = await _two_cycles({**WIRED, **SPOT}, _states())
        assert out["sink_verdicts"]["grid_export"]["state"] == "open"
        assert out["charge_pacing"]["reason_code"] != "closed_meter"

    @pytest.mark.asyncio
    async def test_a_threshold_above_the_value_closes_it(self):
        out = await run_cycle(config={**WIRED, **SPOT, KEY: 0.08},
                              states=_states(), nights=sealed_nights())
        assert out["sink_verdicts"]["grid_export"]["state"] == "closed"
        assert "below 0.08" in out["sink_verdicts"]["grid_export"]["reason"]

    @pytest.mark.asyncio
    async def test_zero_still_exports_by_default(self):
        out = await run_cycle(config={**WIRED, **SPOT},
                              states=_states(feedin=0.0), nights=sealed_nights())
        assert out["sink_verdicts"]["grid_export"]["state"] == "open"


class TestTheDefaultIsDevelop:
    @staticmethod
    def _active(config, settings):
        from custom_components.solar_energy_management.coordinator import SEMCoordinator
        coord = SimpleNamespace(config=config, _tariff_provider=SimpleNamespace(
            value_settings=settings))
        coord._export_value_threshold = (
            lambda: SEMCoordinator._export_value_threshold(coord))
        return SEMCoordinator._active_export_threshold(coord)

    def test_off_at_the_default(self):
        assert self._active({}, vl.NO_VALUE) is None

    def test_a_per_kwh_fee_or_a_threshold_turns_it_on(self):
        fee = vl.settings_from_config(
            {"feed_in_fee_model": vl.FEE_PER_KWH, "feed_in_fee": 0.07})
        assert self._active({}, fee) == 0.0
        assert self._active({KEY: 0.05}, vl.NO_VALUE) == pytest.approx(0.05)

    def test_a_fixed_monthly_fee_or_an_import_markup_alone_is_develop(self):
        """Neither changes what an exported kWh earns."""
        monthly = vl.settings_from_config(
            {"feed_in_fee_model": "fixed_monthly", "feed_in_fee": 5.0})
        markup = vl.settings_from_config(
            {"import_price_basis": "spot", "import_markup": 0.02})
        assert monthly.configured and markup.configured
        assert self._active({}, monthly) is None
        assert self._active({}, markup) is None

    @pytest.mark.asyncio
    async def test_fixed_monthly_only_cycle_is_develop(self):
        """A negative feed-in with only a monthly fee: the meter closes the
        old way and pacing keeps its pace."""
        cfg = {**WIRED, **SPOT, "feed_in_fee_model": "fixed_monthly",
               "feed_in_fee": 5.0}
        out = await _two_cycles(cfg, _states(feedin=-0.02))
        assert out["sink_verdicts"]["grid_export"]["state"] == "closed"
        assert "export price negative" in out["sink_verdicts"]["grid_export"]["reason"]
        assert out["charge_pacing"]["reason_code"] != "closed_meter"

    def test_forecast_sell_skips_the_value_check_while_off(self):
        d = evaluate_forecast_sell(
            NOW, enabled=True, in_block=True, block_w=3000.0, spendable_kwh=5.0,
            max_discharge_w=5000.0, dynamic_floor_pct=None, reserve_pct=20.0,
            export_rate=0.03, export_rate_known=True, export_threshold=None)
        assert d.state is SchedulerState.DISCHARGING_ARBITRAGE


class TestTheSetting:
    def test_everywhere_a_setting_must_be(self):
        import json
        from pathlib import Path
        from custom_components.solar_energy_management.config_flow import (
            OPTIONS_FLOW_OWNED_KEYS,
        )
        from custom_components.solar_energy_management.consts.bounds import BOUNDS
        root = Path(__file__).resolve().parent.parent
        assert KEY in OPTIONS_FLOW_OWNED_KEYS
        assert BOUNDS[KEY].min < 0 < BOUNDS[KEY].max
        assert f'"{KEY}"' in (root / "__init__.py").read_text(encoding="utf-8")
        card = (root / "dashboard" / "card" / "src" / "cards"
                / "sem-config-card.js").read_text(encoding="utf-8")
        assert f"'{KEY}'" in card
        for f in [root / "strings.json", *sorted((root / "translations").glob("*.json"))]:
            step = json.loads(f.read_text(encoding="utf-8"))["options"]["step"]["settings_tariff"]
            assert step["data"].get(KEY) and step["data_description"].get(KEY), f.name
        d = json.loads((root / "dashboard" / "translations.json").read_text(encoding="utf-8"))
        for lang, table in d.items():
            for k in ("config_export_value_threshold",
                      "config_help_export_value_threshold", "pacing_closed_meter"):
                assert table.get(k), (lang, k)


# ── value rules off = develop's behaviour (review, 23.10) ───────────────

class TestValueRulesActiveIsOneTest:
    def test_off_with_no_field_and_the_default_threshold(self):
        assert vl.value_rules_active(vl.NO_VALUE, 0.0) is False
        assert vl.value_rules_active(None, vl.DEFAULT_EXPORT_VALUE_THRESHOLD) is False

    def test_on_with_a_field_or_a_threshold(self):
        assert vl.value_rules_active(SimpleNamespace(changes_export=True), 0.0)
        assert vl.value_rules_active(None, 0.05)
        assert vl.value_rules_active(None, -0.02)

    def test_the_coordinator_passes_none_while_off(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        off = SimpleNamespace(config={}, _tariff_provider=SimpleNamespace(
            value_settings=vl.NO_VALUE))
        off._export_value_threshold = lambda: SEMCoordinator._export_value_threshold(off)
        assert SEMCoordinator._active_export_threshold(off) is None
        on = SimpleNamespace(config={KEY: 0.05}, _tariff_provider=None)
        on._export_value_threshold = lambda: SEMCoordinator._export_value_threshold(on)
        assert SEMCoordinator._active_export_threshold(on) == pytest.approx(0.05)


class TestArbitrageDefaultIsDevelop:
    def _s(self):
        return BatteryChargeScheduler(MagicMock(), SchedulerConfig(
            arbitrage_enabled=True, arbitrage_min_export_price=-0.05,
            arbitrage_reserve_soc=50.0, roundtrip_efficiency=0.9))

    def test_a_rate_between_a_negative_floor_and_zero_is_not_refused_by_value(self):
        # develop: only the floor (-0.05) judged -0.01; no value rule
        d = self._s().evaluate_arbitrage(80.0, -0.01, -0.30)
        assert "not worth exporting" not in d.reason
        assert d.state is SchedulerState.DISCHARGING_ARBITRAGE

    def test_with_the_value_rules_on_it_is(self):
        d = self._s().evaluate_arbitrage(80.0, -0.01, -0.30, export_threshold=0.0)
        assert d.state is SchedulerState.NOT_PROFITABLE
        assert "not worth exporting" in d.reason


class TestPacingKeepsItsPaceOnTheOldClose:
    @pytest.mark.asyncio
    async def test_a_negative_price_without_value_rules_still_paces(self):
        """No value field, default threshold, a negative feed-in PRICE: the
        meter closes the old way, and pacing behaves as on develop."""
        out = await _two_cycles({**WIRED, **SPOT}, _states(feedin=-0.02))
        assert out["sink_verdicts"]["grid_export"]["state"] == "closed"
        assert out["charge_pacing"]["reason_code"] != "closed_meter"
