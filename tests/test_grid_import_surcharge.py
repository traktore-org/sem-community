"""Grid import surcharge.

SEM optionally adds a constant per-kWh network-owner fee (for example
0.725 SEK/kWh) on top of the raw spot price for dynamic tariffs.

Requirements enforced here:

* ``grid_import_surcharge`` defaults to 0 (off) and is an explicit config
  value — never autodetected / never double-counted.
* It applies to every IMPORTED kWh: the current effective import rate and
  every forecast rate used for cost / optimisation / savings
  (``get_current_import_rate``, ``get_price_at``, ``get_charge_window_rate``,
  ``get_next_daytime_rate``).
* It is NEVER applied to export (``get_current_export_rate``).
* The raw spot series stays raw for classification, ordering, scheduling and
  raw display (``_read_prices_list``, ``PricePoint.price``,
  ``find_cheapest_hours``, ``get_schedule_for_day``, ``upcoming_prices``).
"""
import pytest
from datetime import datetime, timedelta

from unittest.mock import MagicMock, patch

from custom_components.solar_energy_management.tariff.tariff_provider import (
    DynamicTariffProvider,
    PriceLevel,
    PricePoint,
)
from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
    BatteryChargeScheduler,
    SchedulerConfig,
    SchedulerState,
)

DT_UTIL_PATH = "custom_components.solar_energy_management.tariff.tariff_provider.dt_util"


def _make_price_state(price, attributes=None):
    state = MagicMock()
    state.state = str(price)
    state.attributes = attributes or {}
    return state


def _provider_with_series(price_seq, surcharge=0.0, slot_minutes=60, start=None):
    """DynamicTariffProvider with a stubbed raw price series + surcharge."""
    if start is None:
        start = datetime(2026, 6, 10, 0, 0)
    prices = [
        PricePoint(
            timestamp=start + timedelta(minutes=slot_minutes * i),
            price=p,
            level=PriceLevel.NORMAL,
        )
        for i, p in enumerate(price_seq)
    ]
    prov = DynamicTariffProvider.__new__(DynamicTariffProvider)
    prov._read_prices_list = lambda: prices
    prov.grid_import_surcharge = surcharge
    prov._last_classifier_path = "unknown"
    return prov, start


# ---------------------------------------------------------------------------
# Current effective import rate
# ---------------------------------------------------------------------------

class TestCurrentImportRateSurcharge:
    def test_no_surcharge_defaults_to_raw(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=_make_price_state(0.30))
        provider = DynamicTariffProvider(mock_hass, price_entity="sensor.p")
        assert provider.grid_import_surcharge == 0.0
        assert provider.get_current_import_rate() == pytest.approx(0.30)

    def test_surcharge_added_to_current_rate(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=_make_price_state(0.50))
        provider = DynamicTariffProvider(
            mock_hass, price_entity="sensor.p", grid_import_surcharge=0.725,
        )
        assert provider.get_current_import_rate() == pytest.approx(1.225)

    def test_surcharge_zero_is_noop(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=_make_price_state(0.50))
        provider = DynamicTariffProvider(
            mock_hass, price_entity="sensor.p", grid_import_surcharge=0.0,
        )
        assert provider.get_current_import_rate() == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# Forecast helpers used for cost / optimisation / savings
# ---------------------------------------------------------------------------

class TestForecastRatesSurcharge:
    def test_price_at_includes_surcharge(self):
        prov, start = _provider_with_series([0.10, 0.20, 0.30], surcharge=0.725)
        assert prov.get_price_at(start) == pytest.approx(0.825)
        assert prov.get_price_at(start + timedelta(hours=1)) == pytest.approx(0.925)
        assert prov.get_price_at(start + timedelta(hours=2)) == pytest.approx(1.025)

    def test_charge_window_rate_includes_surcharge(self):
        prov, start = _provider_with_series(
            [0.30, 0.10, 0.30, 0.12, 0.30, 0.14, 0.30, 0.16, 0.30, 0.30],
            surcharge=0.725,
        )
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = start
            mock_dt.as_local = lambda ts: ts
            rate = prov.get_charge_window_rate(hours=4.0, within_hours=12)
        # cheapest 4 raw slots 0.10,0.12,0.14,0.16 + surcharge each
        assert rate == pytest.approx((0.10 + 0.12 + 0.14 + 0.16) / 4 + 0.725)

    def test_next_daytime_rate_includes_surcharge(self):
        now = datetime(2026, 6, 9, 21, 0)
        points = (
            [(datetime(2026, 6, 9, 22 + i, 0), 0.05) for i in range(2)]
            + [(datetime(2026, 6, 10, 7 + i, 0), 0.30 + 0.01 * i) for i in range(3)]
            + [(datetime(2026, 6, 10, 21, 0), 0.05)]
        )
        prices = [
            PricePoint(timestamp=ts, price=p, level=PriceLevel.NORMAL)
            for ts, p in points
        ]
        prov = DynamicTariffProvider.__new__(DynamicTariffProvider)
        prov._read_prices_list = lambda: prices
        prov.grid_import_surcharge = 0.725
        prov._last_classifier_path = "unknown"
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.as_local = lambda ts: ts
            rate = prov.get_next_daytime_rate()
        # daytime avg (0.30+0.31+0.32)/3 + surcharge
        assert rate == pytest.approx((0.30 + 0.31 + 0.32) / 3 + 0.725)

    def test_today_statistics_use_effective_import_rate(self, mock_hass):
        """Import sensor state and its day statistics use one convention."""
        now = datetime(2026, 6, 10, 12, 0)
        prices_today = [
            {"start": (now.replace(hour=0) + timedelta(hours=h)).isoformat(), "total": p}
            for h, p in enumerate((0.10, 0.20, 0.30))
        ]
        mock_hass.states.get = MagicMock(
            return_value=_make_price_state(
                0.20, attributes={"prices_today": prices_today},
            ),
        )
        provider = DynamicTariffProvider(
            mock_hass, price_entity="sensor.p", grid_import_surcharge=0.725,
        )

        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.as_local = lambda ts: ts
            data = provider.get_tariff_data()

        assert data.current_import_rate == pytest.approx(0.20 + 0.725)
        assert data.today_min_price == pytest.approx(0.10 + 0.725)
        assert data.today_max_price == pytest.approx(0.30 + 0.725)
        assert data.today_avg_price == pytest.approx(0.20 + 0.725)


# ---------------------------------------------------------------------------
# Raw spot preserved for classification / order / schedule / display
# ---------------------------------------------------------------------------

class TestRawSpotPreserved:
    def test_read_prices_list_stays_raw(self, mock_hass):
        now = datetime(2026, 6, 10, 12, 0)
        prices_today = [
            {"start": (now + timedelta(hours=h)).isoformat(), "total": 0.10 + h * 0.1}
            for h in range(4)
        ]
        mock_hass.states.get = MagicMock(
            return_value=_make_price_state(0.10, attributes={"prices_today": prices_today}),
        )
        provider = DynamicTariffProvider(
            mock_hass, price_entity="sensor.p", grid_import_surcharge=0.725,
        )
        parsed = provider._read_prices_list()
        # raw spot values untouched — no surcharge mutates the cache
        assert parsed[0].price == pytest.approx(0.10)
        assert parsed[3].price == pytest.approx(0.40)
        assert provider.grid_import_surcharge == 0.725

    def test_find_cheapest_hours_returns_raw_prices(self):
        prov, start = _provider_with_series([0.3, 0.1, 0.3, 0.12, 0.3], surcharge=0.725)
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = start
            mock_dt.as_local = lambda ts: ts
            slots = prov.find_cheapest_hours(2, within_hours=12)
        # selection unchanged by a constant offset; values stay raw
        assert [s.price for s in slots] == pytest.approx([0.1, 0.12])

    def test_upcoming_prices_stay_raw(self, mock_hass):
        now = datetime(2026, 6, 10, 12, 0)
        prices_today = [
            {"start": (now + timedelta(hours=h)).isoformat(), "total": 0.10 + h * 0.1}
            for h in range(4)
        ]
        mock_hass.states.get = MagicMock(
            return_value=_make_price_state(0.10, attributes={"prices_today": prices_today}),
        )
        provider = DynamicTariffProvider(
            mock_hass, price_entity="sensor.p", grid_import_surcharge=0.725,
        )
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            data = provider.get_tariff_data()
        assert data.upcoming_prices[0].price == pytest.approx(0.10)
        # current_import_rate is the effective (surcharged) rate
        assert data.current_import_rate == pytest.approx(0.10 + 0.725)


# ---------------------------------------------------------------------------
# Export must NOT be affected
# ---------------------------------------------------------------------------

class TestExportUnaffected:
    def test_export_rate_unchanged_by_surcharge(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=_make_price_state(0.30))
        provider = DynamicTariffProvider(
            mock_hass, price_entity="sensor.p",
            grid_import_surcharge=0.725, export_rate=0.08,
        )
        # static export rate path: surcharge must not leak into export
        assert provider.get_current_export_rate() == pytest.approx(0.08)


# ---------------------------------------------------------------------------
# Coordinator wiring: config.grid_import_surcharge → provider
# ---------------------------------------------------------------------------

class TestCoordinatorWiring:
    def _coordinator(self, mock_hass, **overrides):
        from custom_components.solar_energy_management.coordinator import SEMCoordinator
        config = {
            "tariff_mode": "dynamic",
            "update_interval": 30,
            "grid_import_surcharge": 0.0,
        }
        config.update(overrides)
        return SEMCoordinator(mock_hass, config)

    def test_dynamic_provider_receives_surcharge(self, mock_hass):
        coord = self._coordinator(mock_hass, grid_import_surcharge=0.725)
        provider = coord._tariff_provider
        assert isinstance(provider, DynamicTariffProvider)
        assert provider.grid_import_surcharge == pytest.approx(0.725)

    def test_dynamic_provider_defaults_surcharge_zero(self, mock_hass):
        coord = self._coordinator(mock_hass)
        assert coord._tariff_provider.grid_import_surcharge == 0.0

    def test_upgraded_install_without_key_keeps_legacy_zero_cost(self, mock_hass):
        """A pre-#710 config entry has no key and must retain old behaviour."""
        from custom_components.solar_energy_management.coordinator import SEMCoordinator

        coord = SEMCoordinator(
            mock_hass, {"tariff_mode": "dynamic", "update_interval": 30},
        )
        assert coord._tariff_provider.grid_import_surcharge == 0.0


# ---------------------------------------------------------------------------
# effective_import_floor: surcharge applied exactly once, never double-counted
# ---------------------------------------------------------------------------

class TestEffectiveImportFloor:
    def _floor_provider(self, live_raw, curve_now, surcharge):
        prov = DynamicTariffProvider.__new__(DynamicTariffProvider)
        prov._read_current_price = lambda: live_raw
        prov._cached_price_for = lambda ts: curve_now
        prov.grid_import_surcharge = surcharge
        prov._last_classifier_path = "unknown"
        return prov

    def test_no_surcharge_keeps_legacy_floor(self):
        # State == curve (all-in provider): factor == 1.0 -> identity.
        prov = self._floor_provider(live_raw=0.30, curve_now=0.30, surcharge=0.0)
        assert prov.effective_import_floor(0.12) == pytest.approx(0.12)

    def test_raw_vs_all_in_mismatch_corrects_then_surcharges_once(self):
        # State all-in (0.30 with fees) vs raw curve (0.10): factor 3.0.
        prov = self._floor_provider(live_raw=0.30, curve_now=0.10, surcharge=0.725)
        # raw_min 0.05 -> 0.05*3.0 + 0.725 — NOT 0.05*(0.30+0.725)/0.10.
        assert prov.effective_import_floor(0.05) == pytest.approx(0.05 * 3.0 + 0.725)

    def test_surcharge_not_double_counted_on_all_in_provider(self):
        # All-in provider: state == curve (factor 1.0, identity path). The
        # surcharge must be added exactly once — the raw minimum must NOT be
        # scaled by the surcharge ratio. Because state (0.30) equals curve
        # (0.30) even after the surcharge is configured, if the factor used
        # the surcharged live rate (0.30+0.725)/0.30 ≈ 3.42 it would wrongly
        # multiply raw_min up AND add the surcharge — double counting.
        prov = self._floor_provider(live_raw=0.30, curve_now=0.30, surcharge=0.725)
        # raw_min 0.10 stays 0.10 (identity), then + 0.725 once = 0.825.
        assert prov.effective_import_floor(0.10) == pytest.approx(0.825)

    def test_surcharge_applied_when_curve_unknown(self):
        # No curve (None) -> identity path, but surcharge still applies once.
        prov = self._floor_provider(live_raw=0.30, curve_now=None, surcharge=0.725)
        assert prov.effective_import_floor(0.10) == pytest.approx(0.825)

    def test_surcharge_flips_real_arbitrage_decision(self):
        """The configured fee reaches the scheduler's economic decision."""
        provider = self._floor_provider(
            live_raw=0.10, curve_now=0.10, surcharge=0.0,
        )
        scheduler = BatteryChargeScheduler(
            MagicMock(),
            SchedulerConfig(
                arbitrage_enabled=True,
                arbitrage_min_export_price=0.20,
                arbitrage_reserve_soc=50.0,
                max_discharge_power_w=4000.0,
                roundtrip_efficiency=0.90,
                battery_cycle_cost=0.0,
            ),
        )

        without_fee = scheduler.evaluate_arbitrage(
            80.0, export_rate=0.45,
            import_forecast_min=provider.effective_import_floor(0.10),
        )
        provider.grid_import_surcharge = 0.725
        with_fee = scheduler.evaluate_arbitrage(
            80.0, export_rate=0.45,
            import_forecast_min=provider.effective_import_floor(0.10),
        )

        assert without_fee.state is SchedulerState.DISCHARGING_ARBITRAGE
        assert with_fee.state is SchedulerState.NOT_PROFITABLE


# ---------------------------------------------------------------------------
# Corrupt-config normalization: NaN / negative must never reach runtime cost
# ---------------------------------------------------------------------------

class TestCorruptSurchargeNormalized:
    def test_bool_surcharge_clamped_to_zero(self, mock_hass):
        provider = DynamicTariffProvider(
            mock_hass, price_entity="sensor.p", grid_import_surcharge=True,
        )
        assert provider.grid_import_surcharge == 0.0

    def test_nan_surcharge_clamped_to_zero(self, mock_hass):
        provider = DynamicTariffProvider(
            mock_hass, price_entity="sensor.p", grid_import_surcharge=float("nan"),
        )
        assert provider.grid_import_surcharge == 0.0

    def test_negative_surcharge_clamped_to_zero(self, mock_hass):
        provider = DynamicTariffProvider(
            mock_hass, price_entity="sensor.p", grid_import_surcharge=-0.5,
        )
        assert provider.grid_import_surcharge == 0.0

    def test_inf_surcharge_clamped_to_zero(self, mock_hass):
        provider = DynamicTariffProvider(
            mock_hass, price_entity="sensor.p", grid_import_surcharge=float("inf"),
        )
        assert provider.grid_import_surcharge == 0.0


# ---------------------------------------------------------------------------
# Options flow: wizard field present, owned-key persistence
# ---------------------------------------------------------------------------

class TestOptionsFlow:
    def test_grid_import_surcharge_is_owned_key(self):
        from custom_components.solar_energy_management.config_flow import (
            OPTIONS_FLOW_OWNED_KEYS,
        )
        assert "grid_import_surcharge" in OPTIONS_FLOW_OWNED_KEYS

    @pytest.mark.asyncio
    async def test_wizard_offers_surcharge_field(self, mock_hass, config_entry):
        from custom_components.solar_energy_management.config_flow import (
            OptionsFlowHandler,
        )

        config_entry.options = {"tariff_mode": "dynamic"}
        flow = OptionsFlowHandler(config_entry)
        flow.hass = mock_hass
        with patch.object(
            type(flow),
            "config_entry",
            new_callable=lambda: property(lambda self: config_entry),
        ):
            result = await flow.async_step_settings_tariff()

        schema_keys = {key.schema for key in result["data_schema"].schema}
        assert "grid_import_surcharge" in schema_keys

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tariff_mode", ["static", "calendar"])
    async def test_wizard_hides_surcharge_outside_dynamic_mode(
        self, mock_hass, config_entry, tariff_mode,
    ):
        from custom_components.solar_energy_management.config_flow import (
            OptionsFlowHandler,
        )

        config_entry.options = {"tariff_mode": tariff_mode}
        flow = OptionsFlowHandler(config_entry)
        flow.hass = mock_hass
        with patch.object(
            type(flow),
            "config_entry",
            new_callable=lambda: property(lambda self: config_entry),
        ):
            result = await flow.async_step_settings_tariff()

        schema_keys = {key.schema for key in result["data_schema"].schema}
        assert "grid_import_surcharge" not in schema_keys

    @pytest.mark.asyncio
    async def test_hidden_surcharge_survives_static_mode_save(
        self, mock_hass, config_entry,
    ):
        """Mode-gating must not silently erase the dynamic-mode setting."""
        from custom_components.solar_energy_management.config_flow import (
            OptionsFlowHandler,
        )

        config_entry.options = {
            "tariff_mode": "dynamic",
            "grid_import_surcharge": 0.725,
        }
        flow = OptionsFlowHandler(config_entry)
        flow.hass = mock_hass
        with patch.object(
            type(flow),
            "config_entry",
            new_callable=lambda: property(lambda self: config_entry),
        ):
            await flow.async_step_settings_tariff({"tariff_mode": "static"})

        assert flow._data["grid_import_surcharge"] == pytest.approx(0.725)
