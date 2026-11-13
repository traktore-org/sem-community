"""#1077 — what a kWh is worth, bought and sold.

When net metering ends (NL, 1 Jan 2027) a bought kWh costs
``(spot + markup + energy tax) × (1 + VAT) + surcharge`` and a sold kWh earns
``spot − feed-in fee``. Every field defaults to 0, and then every price must
be what it was before — to the bit, in every tariff mode.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from custom_components.solar_energy_management.tariff.calendar_provider import (
    CalendarTariffProvider,
)
from custom_components.solar_energy_management.tariff.tariff_provider import (
    DynamicTariffProvider,
    PriceLevel,
    PricePoint,
    StaticTariffProvider,
)
from custom_components.solar_energy_management.tariff import value_layer as vl
from custom_components.solar_energy_management.tariff.value_layer import (
    ValueSettings,
    apply_value_preset,
    parse_tiers,
    settings_from_config,
)

ROOT = Path(__file__).resolve().parent.parent
DT_UTIL_PATH = "custom_components.solar_energy_management.tariff.tariff_provider.dt_util"

# Option keys as variables, never retyped below.
PRESET = vl.CONF_VALUE_PRESET
BASIS = vl.CONF_IMPORT_PRICE_BASIS
MARKUP = vl.CONF_IMPORT_MARKUP
TAX = vl.CONF_IMPORT_ENERGY_TAX
VAT = vl.CONF_IMPORT_VAT_PERCENT
MODEL = vl.CONF_FEED_IN_FEE_MODEL
FEE = vl.CONF_FEED_IN_FEE
TIERS = vl.CONF_FEED_IN_FEE_TIERS
VALUE_SENSORS = (
    "daily_self_consumption_value", "yearly_self_consumption_value",
    "daily_export_value", "yearly_export_value",
    "daily_feed_in_fees", "yearly_feed_in_fees",
)

NL = ValueSettings(basis=vl.BASIS_SPOT, markup=0.02, energy_tax=0.0916,
                   vat_percent=21.0, fee_model=vl.FEE_PER_KWH, fee=0.03)


# ── The formulas ─────────────────────────────────────────────────────────

class TestTheFormulas:
    def test_import_value_on_bare_spot(self):
        assert NL.import_value(0.10) == pytest.approx((0.10 + 0.02 + 0.0916) * 1.21)

    def test_surcharge_comes_after_vat(self):
        assert NL.import_value(0.10, 0.05) == pytest.approx(
            (0.10 + 0.02 + 0.0916) * 1.21 + 0.05)

    def test_spot_incl_vat_puts_vat_on_markup_and_tax_only(self):
        s = ValueSettings(basis=vl.BASIS_SPOT_INCL_VAT, markup=0.02,
                          energy_tax=0.0916, vat_percent=21.0)
        assert s.import_value(0.121) == pytest.approx(0.121 + (0.02 + 0.0916) * 1.21)

    def test_all_in_adds_nothing_so_tax_is_never_counted_twice(self):
        s = ValueSettings(basis=vl.BASIS_ALL_IN, markup=0.02,
                          energy_tax=0.0916, vat_percent=21.0)
        assert s.import_value(0.31, 0.05) == 0.31 + 0.05

    def test_negative_spot_gets_vat_too(self):
        s = ValueSettings(basis=vl.BASIS_SPOT, vat_percent=21.0)
        assert s.import_value(-0.10) == pytest.approx(-0.121)

    def test_export_value_takes_the_fee_off(self):
        assert NL.export_value(0.08) == pytest.approx(0.05)
        assert NL.export_value(-0.02) == pytest.approx(-0.05)

    def test_all_zero_is_the_price_itself(self):
        s = ValueSettings()
        for p in (0.0, 0.3387, -0.07, 1.69, 123.456):
            assert s.import_value(p) == p
            assert s.import_value(p, 0.725) == p + 0.725
            assert s.export_value(p) == p

    def test_bad_input_is_off_not_a_credit(self):
        s = settings_from_config({TAX: -1, VAT: float("nan"), MARKUP: "x",
                                  BASIS: "bogus", MODEL: "bogus", FEE: True})
        assert s == ValueSettings()
        assert settings_from_config({VAT: 210}).vat_percent == 0.0


# ── Fee models ───────────────────────────────────────────────────────────

class TestFeeModels:
    def test_per_kwh(self):
        s = ValueSettings(fee_model=vl.FEE_PER_KWH, fee=0.03)
        assert s.fee_rate(0) == 0.03
        assert s.fee_rate(99999) == 0.03
        assert s.fixed_monthly_fee() == 0.0

    def test_fixed_monthly_is_zero_at_the_margin(self):
        s = ValueSettings(fee_model=vl.FEE_FIXED_MONTHLY, fee=12.0)
        assert s.fee_rate(500) == 0.0
        assert s.export_value(0.08) == 0.08
        assert s.fixed_monthly_fee() == 12.0

    def test_tiers_parse(self):
        assert parse_tiers("1000:0.02, 0:0; 3000:0.05, junk, 5:-1") == (
            (0.0, 0.0), (1000.0, 0.02), (3000.0, 0.05))
        assert parse_tiers([{"from_kwh": 0, "fee": 0.01}, (500, 0.02)]) == (
            (0.0, 0.01), (500.0, 0.02))
        assert parse_tiers("") == ()

    def test_tier_crossing(self):
        s = settings_from_config({MODEL: vl.FEE_TIERED,
                                  TIERS: "0:0, 1000:0.02, 3000:0.05"})
        assert s.fee_rate(999.9) == 0.0
        assert s.fee_rate(1000.0) == 0.02
        assert s.fee_rate(2999) == 0.02
        assert s.fee_rate(3000) == 0.05
        assert s.next_tier_kwh(999.9) == 1000.0
        assert s.next_tier_kwh(1500) == 3000.0
        assert s.next_tier_kwh(3000) is None
        assert s.export_value(0.08, 1500) == pytest.approx(0.06)

    def test_tiers_below_the_first_step_are_free(self):
        s = settings_from_config({MODEL: vl.FEE_TIERED, TIERS: "1000:0.02"})
        assert s.fee_rate(10) == 0.0

    def test_provider_reads_this_years_export(self):
        p = StaticTariffProvider(export_rate=0.08)
        p.value_settings = settings_from_config(
            {MODEL: vl.FEE_TIERED, TIERS: "0:0, 1000:0.02"})
        assert p.get_current_export_rate() == 0.08
        p.export_ytd_kwh = 1200.0
        assert p.get_current_export_rate() == pytest.approx(0.06)
        assert p.get_current_spot_export_rate() == 0.08
        data = p.get_tariff_data()
        assert data.feed_in_fee_rate == 0.02
        assert data.next_fee_tier_kwh is None
        assert data.current_export_spot_rate == 0.08


# ── All zero = today's prices, in every mode ─────────────────────────────

def _price_state(price, attributes=None):
    state = MagicMock()
    state.state = str(price)
    state.attributes = attributes or {}
    return state


class TestAllZeroIsTodaysPrices:
    def test_static(self):
        p = StaticTariffProvider(peak_rate=0.3387, off_peak_rate=0.2211,
                                 export_rate=0.075)
        p.value_settings = settings_from_config({})
        ref = StaticTariffProvider(peak_rate=0.3387, off_peak_rate=0.2211,
                                   export_rate=0.075)
        assert p.get_current_import_rate() == ref.get_current_import_rate()
        assert p.get_current_export_rate() == 0.075
        when = datetime(2026, 10, 21, 3, 0)
        assert p.get_price_at(when) == 0.2211
        assert p.get_price_at(when.replace(hour=12)) == 0.3387
        d = p.get_tariff_data()
        assert (d.today_min_price, d.today_max_price, d.current_export_rate) == (
            ref.get_tariff_data().today_min_price,
            ref.get_tariff_data().today_max_price, 0.075)
        assert d.value_layer_on is False

    def test_calendar(self):
        hass = MagicMock()
        hass.states.get = lambda _e: None
        kw = dict(peak_rate=0.36, off_peak_rate=0.22, export_rate=0.09, rules=[
            {"days": list(range(7)), "start": "07:00", "end": "20:00", "tariff": "ht"}])
        p = CalendarTariffProvider(hass, **kw)
        p.value_settings = settings_from_config({TIERS: "", MODEL: "none"})
        assert p.get_current_import_rate() in (0.36, 0.22)
        assert p.get_current_export_rate() == 0.09
        now = datetime.now()
        assert p.get_price_at(now.replace(hour=3)) == 0.22
        assert p.get_price_at(now.replace(hour=12)) == 0.36

    def test_dynamic(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=_price_state(0.2034))
        p = DynamicTariffProvider(mock_hass, price_entity="sensor.p",
                                  grid_import_surcharge=0.725, export_rate=0.08)
        p.value_settings = settings_from_config({})
        assert p.get_current_import_rate() == 0.2034 + 0.725
        assert p.get_current_export_rate() == 0.08

    def test_dynamic_curve_helpers(self):
        start = datetime(2026, 6, 10, 0, 0)
        prices = [PricePoint(timestamp=start + timedelta(hours=i), price=v,
                             level=PriceLevel.NORMAL)
                  for i, v in enumerate((0.10, 0.20, 0.30))]
        p = DynamicTariffProvider.__new__(DynamicTariffProvider)
        p._read_prices_list = lambda: prices
        p.grid_import_surcharge = 0.5
        p._last_classifier_path = "unknown"
        assert p.get_price_at(start + timedelta(hours=1)) == 0.20 + 0.5
        p.value_settings = NL
        assert p.get_price_at(start + timedelta(hours=1)) == pytest.approx(
            (0.20 + 0.02 + 0.0916) * 1.21 + 0.5)


class TestTheValueReachesEveryConsumer:
    def test_dynamic_spot_gets_tax_and_vat(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=_price_state(0.10))
        p = DynamicTariffProvider(mock_hass, price_entity="sensor.p",
                                  export_rate=0.08)
        p.value_settings = NL
        assert p.get_current_import_rate() == pytest.approx((0.10 + 0.02 + 0.0916) * 1.21)
        assert p.get_current_export_rate() == pytest.approx(0.05)

    def test_static_on_spot_basis_gets_tax(self):
        p = StaticTariffProvider(peak_rate=0.10, off_peak_rate=0.10, export_rate=0.08)
        p.value_settings = NL
        assert p.get_current_import_rate() == pytest.approx((0.10 + 0.02 + 0.0916) * 1.21)
        assert p.get_tariff_data().value_layer_on is True

    def test_level_is_unchanged_by_the_value(self):
        p = StaticTariffProvider(peak_rate=0.30, off_peak_rate=0.20)
        before = p.get_price_level()
        p.value_settings = NL
        assert p.get_price_level() == before


# ── This year's export and New Year ──────────────────────────────────────

def _calc():
    from custom_components.solar_energy_management.coordinator.energy_calculator import (
        EnergyCalculator,
    )
    from custom_components.solar_energy_management.utils.time_manager import TimeManager
    hass = Mock()
    hass.data = {}
    hass.config = Mock()
    hass.config.config_dir = "/config"
    hass.states.get = lambda _eid: None
    return EnergyCalculator({"update_interval": 3600}, TimeManager(hass))


class TestExportYearToDate:
    def test_reads_the_yearly_export_counter(self):
        calc = _calc()
        calc._yearly_accumulators["grid_export_2026"] = 1234.5
        assert calc.export_year_to_date_kwh(datetime(2026, 12, 31, 23, 59)) == 1234.5

    def test_new_year_starts_at_zero(self):
        calc = _calc()
        calc._yearly_accumulators["grid_export_2026"] = 1234.5
        assert calc.export_year_to_date_kwh(datetime(2027, 1, 1, 0, 1)) == 0.0

    def test_tier_resets_at_new_year(self):
        calc = _calc()
        calc._yearly_accumulators["grid_export_2026"] = 1500.0
        s = settings_from_config({MODEL: vl.FEE_TIERED, TIERS: "0:0, 1000:0.02"})
        assert s.fee_rate(calc.export_year_to_date_kwh(datetime(2026, 12, 31))) == 0.02
        assert s.fee_rate(calc.export_year_to_date_kwh(datetime(2027, 1, 1))) == 0.0


# ── The books and the sensors ────────────────────────────────────────────

class TestTheBooks:
    def _hour(self, settings, power):
        from custom_components.solar_energy_management.coordinator.types import (
            EnergyTotals,
        )
        calc = _calc()
        p = StaticTariffProvider(peak_rate=0.40, off_peak_rate=0.40, export_rate=0.08)
        p.value_settings = settings
        t = p.get_tariff_data()
        calc._import_rate = t.current_import_rate
        calc._export_rate = t.current_export_rate
        calc.set_value_rates(t)
        calc._last_update = None
        calc.calculate_energy(power)
        return calc.calculate_costs(EnergyTotals())

    def test_per_kwh_fee(self):
        from custom_components.solar_energy_management.coordinator.types import (
            PowerReadings,
        )
        s = ValueSettings(fee_model=vl.FEE_PER_KWH, fee=0.03)
        costs = self._hour(s, PowerReadings(
            solar_power=3000.0, home_consumption_power=1000.0,
            grid_export_power=2000.0))
        assert costs.daily_export_value == pytest.approx(0.16)    # 2 kWh × 0.08
        assert costs.daily_feed_in_fees == pytest.approx(0.06)    # 2 kWh × 0.03
        assert costs.daily_export_revenue == pytest.approx(0.10)  # 2 kWh × 0.05
        # 1 kWh used at home, worth 0.40 − 0.05 over selling it
        assert costs.daily_self_consumption_value == pytest.approx(0.35)
        assert costs.yearly_feed_in_fees == pytest.approx(0.06)

    def test_fixed_monthly_fee_is_owed_by_the_hour(self):
        from custom_components.solar_energy_management.coordinator.types import (
            PowerReadings,
        )
        s = ValueSettings(fee_model=vl.FEE_FIXED_MONTHLY, fee=31 * 24 * 0.01)
        with patch("custom_components.solar_energy_management.coordinator."
                   "energy_calculator.dt_util.now",
                   return_value=datetime(2026, 10, 21, 12, 0)):
            costs = self._hour(s, PowerReadings(home_consumption_power=500.0))
        assert costs.daily_feed_in_fees == pytest.approx(0.01)

    def test_nothing_set_books_nothing(self):
        from custom_components.solar_energy_management.coordinator.types import (
            PowerReadings,
        )
        costs = self._hour(ValueSettings(), PowerReadings(
            solar_power=3000.0, home_consumption_power=1000.0,
            grid_export_power=2000.0))
        assert (costs.daily_export_value, costs.daily_feed_in_fees,
                costs.daily_self_consumption_value) == (0.0, 0.0, 0.0)
        assert costs.daily_export_revenue == pytest.approx(0.16)


class TestTheSensors:
    def test_declared(self):
        from custom_components.solar_energy_management.sensor import SENSOR_TYPES
        keys = {d.key for d in SENSOR_TYPES}
        assert set(VALUE_SENSORS) <= keys

    def test_published(self):
        from custom_components.solar_energy_management.coordinator.types import (
            CostData,
        )
        fields = set(CostData.__dataclass_fields__)
        assert set(VALUE_SENSORS) <= fields

    def test_they_exist_only_once_a_value_field_is_set(self):
        from custom_components.solar_energy_management.coordinator.install_modules import (
            Module, Presence, entity_kept, module_verdict,
        )
        plain = module_verdict({}, None, True)
        nl = module_verdict({TAX: 0.0916}, None, True)
        fee = module_verdict({MODEL: vl.FEE_TIERED}, None, True)
        assert plain[Module.VALUE_TARIFF] is Presence.ABSENT
        assert nl[Module.VALUE_TARIFF] is Presence.PRESENT
        assert fee[Module.VALUE_TARIFF] is Presence.PRESENT
        for key in VALUE_SENSORS:
            assert not entity_kept("sensor", key, plain), key
            assert entity_kept("sensor", key, nl), key

    def test_named_in_every_language(self):
        files = [ROOT / "strings.json", *sorted((ROOT / "translations").glob("*.json"))]
        assert len(files) == 17
        for f in files:
            d = json.loads(f.read_text(encoding="utf-8"))
            for key in VALUE_SENSORS:
                assert d["entity"]["sensor"][key]["name"], (f.name, key)


# ── The preset ───────────────────────────────────────────────────────────

class TestThePreset:
    def test_nl_fills_tax_vat_and_the_fee_model(self):
        out = apply_value_preset({PRESET: vl.PRESET_NL_2027}, {})
        assert out[TAX] == pytest.approx(0.0916)
        assert out[VAT] == 21.0
        assert out[MODEL] == vl.FEE_PER_KWH
        assert out[BASIS] == vl.BASIS_SPOT     # tax and VAT go on a spot price
        assert MARKUP not in out and FEE not in out   # supplier's own numbers

    def test_none_clears_everything(self):
        stored = {PRESET: vl.PRESET_NL_2027, TAX: 0.0916, VAT: 21.0,
                  MODEL: vl.FEE_PER_KWH, FEE: 0.03}
        out = apply_value_preset({PRESET: vl.PRESET_NONE}, stored)
        assert settings_from_config({**stored, **out}) == ValueSettings()

    def test_the_form_sends_everything_back_unchanged(self):
        stored = {PRESET: vl.PRESET_NL_2027, TAX: 0.0916, VAT: 21.0,
                  MODEL: vl.FEE_PER_KWH, FEE: 0.0}
        sent = {**stored, FEE: 0.03}          # the user typed the fee
        assert apply_value_preset(sent, stored)[PRESET] == vl.PRESET_NL_2027

    def test_changing_a_preset_field_makes_it_custom(self):
        stored = {PRESET: vl.PRESET_NL_2027, TAX: 0.0916, VAT: 21.0,
                  MODEL: vl.FEE_PER_KWH}
        assert apply_value_preset({VAT: 9.0}, stored)[PRESET] == vl.PRESET_CUSTOM

    def test_other_countries_leave_everything_zero(self):
        assert settings_from_config(vl.PRESET_FIELDS[vl.PRESET_NONE]) == ValueSettings()


# ── The settings, in the options flow AND on the card ────────────────────

def _flow(mock_hass, config_entry, options):
    from custom_components.solar_energy_management.config_flow import (
        OptionsFlowHandler,
    )
    config_entry.options = options
    flow = OptionsFlowHandler(config_entry)
    flow.hass = mock_hass
    return flow


async def _step(flow, config_entry, user_input=None):
    with patch.object(type(flow), "config_entry",
                      new_callable=lambda: property(lambda self: config_entry)):
        return await flow.async_step_settings_tariff(user_input)


class TestTheSettings:
    @pytest.mark.asyncio
    async def test_the_tariff_page_has_every_field(self, mock_hass, config_entry):
        result = await _step(_flow(mock_hass, config_entry, {}), config_entry)
        keys = {m.schema for m in result["data_schema"].schema}
        assert set(vl.VALUE_OPTION_KEYS) <= keys
        for m in result["data_schema"].schema:
            if m.schema in (PRESET, BASIS, MODEL, MARKUP, TAX, VAT, FEE):
                assert m.default() == vl.VALUE_DEFAULTS[m.schema], m.schema

    @pytest.mark.asyncio
    async def test_the_preset_fills_on_save(self, mock_hass, config_entry):
        flow = _flow(mock_hass, config_entry, {})
        result = await _step(flow, config_entry, {
            "tariff_mode": "static", PRESET: vl.PRESET_NL_2027,
            BASIS: vl.BASIS_ALL_IN, TAX: 0.0, VAT: 0.0, MODEL: vl.FEE_NONE})
        assert result["step_id"] == "load_management"
        assert flow._data[TAX] == pytest.approx(0.0916)
        assert flow._data[VAT] == 21.0
        assert flow._data[MODEL] == vl.FEE_PER_KWH
        # the form still showed "all-in"; picking the preset sets spot
        assert flow._data[BASIS] == vl.BASIS_SPOT

    def test_owned_and_in_the_diagnose_dump(self):
        from custom_components.solar_energy_management.config_flow import (
            OPTIONS_FLOW_OWNED_KEYS,
        )
        assert set(vl.VALUE_OPTION_KEYS) <= OPTIONS_FLOW_OWNED_KEYS
        init = (ROOT / "__init__.py").read_text(encoding="utf-8")
        for key in vl.VALUE_OPTION_KEYS:
            assert f'"{key}"' in init, key

    def test_the_card_offers_every_field(self):
        card = (ROOT / "dashboard" / "card" / "src" / "cards"
                / "sem-config-card.js").read_text(encoding="utf-8")
        for key in vl.VALUE_OPTION_KEYS:
            assert f"'{key}'" in card, key

    def test_the_card_has_words_in_every_language(self):
        d = json.loads((ROOT / "dashboard" / "translations.json").read_text(
            encoding="utf-8"))
        for lang, table in d.items():
            for key in ("config_value_preset", "config_price_basis_spot",
                        "config_fee_model_tiered", "config_help_feed_in_fee_tiers"):
                assert table.get(key), (lang, key)

    def test_the_page_has_words_in_every_language(self):
        files = [ROOT / "strings.json", *sorted((ROOT / "translations").glob("*.json"))]
        for f in files:
            d = json.loads(f.read_text(encoding="utf-8"))
            step = d["options"]["step"]["settings_tariff"]
            for key in vl.VALUE_OPTION_KEYS:
                assert step["data"].get(key), (f.name, key)
                assert step["data_description"].get(key), (f.name, key)
            for sel, options in ((PRESET, vl.PRESETS), (BASIS, vl.PRICE_BASES),
                                 (MODEL, vl.FEE_MODELS)):
                assert set(d["selector"][sel]["options"]) == set(options), (f.name, sel)


class TestTheCoordinatorHandsItOver:
    @pytest.mark.parametrize("mode", ["static", "dynamic", "calendar"])
    def test_every_mode_gets_the_settings(self, mock_hass, mode):
        from custom_components.solar_energy_management.coordinator import SEMCoordinator
        coord = SEMCoordinator(mock_hass, {"tariff_mode": mode, "update_interval": 30,
                                           TAX: 0.0916, VAT: 21.0})
        s = coord._tariff_provider.value_settings
        assert (s.energy_tax, s.vat_percent) == (0.0916, 21.0)

    def test_nothing_set_is_no_value(self, mock_hass):
        from custom_components.solar_energy_management.coordinator import SEMCoordinator
        coord = SEMCoordinator(mock_hass, {"tariff_mode": "static", "update_interval": 30})
        assert coord._tariff_provider.value_settings == ValueSettings()


# ─── review, 23.10 ──────────────────────────────────────────────────────────

def test_a_decimal_comma_in_a_tier_fee_is_one_number():
    assert vl.parse_tiers("0:0, 1000:0,02, 3000:0,05") == (
        (0.0, 0.0), (1000.0, 0.02), (3000.0, 0.05))
    assert vl.parse_tiers("0:0; 1000:0.02") == ((0.0, 0.0), (1000.0, 0.02))


def test_the_year_count_starts_at_zero_on_new_year():
    from custom_components.solar_energy_management.coordinator.energy_calculator import (
        EnergyCalculator,
    )
    calc = EnergyCalculator({}, MagicMock())
    calc._yearly_accumulators = {"grid_export_2026": 2400.0}
    assert calc.export_year_to_date_kwh(datetime(2026, 12, 31, 23, 59)) == 2400.0
    assert calc.export_year_to_date_kwh(datetime(2027, 1, 1, 0, 1)) == 0.0


def test_a_failing_log_row_never_stops_the_charger_write():
    from custom_components.solar_energy_management.coordinator import charger_reconciler as cr
    rec = cr.ChargerReconciler.__new__(cr.ChargerReconciler)
    rec.decision_log = object()
    action = MagicMock(kind=cr.ActionKind.WRITE_CURRENT, amps=10)
    with patch("custom_components.solar_energy_management.coordinator."
               "decision_log.record_charger", side_effect=RuntimeError("boom")):
        rec._log_write(action, MagicMock(), MagicMock())   # must not raise


# ── An all-in price takes no markup, tax or VAT ──────────────────────────
# An all-in price adds nothing, so those amounts would be ignored without a
# word. The flow and set_option refuse the clash through one check.

ERR_KEY = "value_needs_spot_basis"


class TestTheBasisCheck:
    @pytest.mark.parametrize("key", [MARKUP, TAX, VAT])
    def test_all_in_with_an_amount_clashes(self, key):
        assert vl.basis_contradiction({BASIS: vl.BASIS_ALL_IN, key: 0.02})
        assert vl.basis_contradiction({key: 0.02})          # all-in is the default

    @pytest.mark.parametrize("basis", [vl.BASIS_SPOT, vl.BASIS_SPOT_INCL_VAT])
    def test_a_spot_basis_never_clashes(self, basis):
        assert not vl.basis_contradiction({BASIS: basis, MARKUP: 0.02, VAT: 21.0})

    def test_nothing_set_never_clashes(self):
        assert not vl.basis_contradiction({})
        assert not vl.basis_contradiction(None)

    def test_a_partial_write_is_judged_on_what_it_changes(self):
        clash = {BASIS: vl.BASIS_ALL_IN, MARKUP: 0.02, TAX: 0.09}
        assert vl.basis_contradiction(clash, {MARKUP: 0.02})
        assert vl.basis_contradiction(clash, {BASIS: vl.BASIS_ALL_IN})
        # Zeroing one amount is always allowed, even while another remains.
        assert not vl.basis_contradiction({**clash, MARKUP: 0.0}, {MARKUP: 0.0})
        # A write that touches no value field is not refused.
        assert not vl.basis_contradiction(clash, {"tariff_mode": "static"})

    def test_the_error_has_words_in_every_language(self):
        files = [ROOT / "strings.json", *sorted((ROOT / "translations").glob("*.json"))]
        for f in files:
            d = json.loads(f.read_text(encoding="utf-8"))
            assert d["options"]["error"].get(ERR_KEY), f.name
            assert d["exceptions"][ERR_KEY]["message"], f.name
        cards = json.loads((ROOT / "dashboard" / "translations.json").read_text(
            encoding="utf-8"))
        for lang, table in cards.items():
            assert table.get("config_value_needs_spot_basis"), lang

    def test_the_card_greys_the_amounts_on_all_in(self):
        card = (ROOT / "dashboard" / "card" / "src" / "cards"
                / "sem-config-card.js").read_text(encoding="utf-8")
        # (#1354) on all-in the three fields are not asked at all
        assert "taxesApply(basis)" in card
        assert "config_value_needs_spot_basis" in card


class TestTheFlowRefusesTheClash:
    @pytest.mark.asyncio
    async def test_refused_then_accepted_on_a_spot_basis(self, mock_hass, config_entry):
        flow = _flow(mock_hass, config_entry, {})
        sent = {"tariff_mode": "static", BASIS: vl.BASIS_ALL_IN, MARKUP: 0.02}
        result = await _step(flow, config_entry, sent)
        assert result["step_id"] == "settings_tariff"
        assert result["errors"] == {BASIS: ERR_KEY}
        assert MARKUP not in flow._data

        result = await _step(flow, config_entry, {**sent, BASIS: vl.BASIS_SPOT})
        assert result["step_id"] == "load_management"
        assert flow._data[MARKUP] == 0.02

    @pytest.mark.asyncio
    async def test_the_nl_preset_sets_spot_so_it_is_never_a_clash(
            self, mock_hass, config_entry):
        """The preset owns the basis: choosing it on an all-in form saves."""
        flow = _flow(mock_hass, config_entry, {})
        result = await _step(flow, config_entry, {
            "tariff_mode": "static", PRESET: vl.PRESET_NL_2027})
        assert result["step_id"] == "load_management"
        assert flow._data[BASIS] == vl.BASIS_SPOT


@pytest.mark.asyncio
async def test_set_option_refuses_the_clash_both_ways(sem_real_hass, sem_config_entry):
    from homeassistant.exceptions import ServiceValidationError

    from custom_components.solar_energy_management.const import DOMAIN

    from .test_services_real import _seed_sem_input_sensors

    hass, entry = sem_real_hass, sem_config_entry
    _seed_sem_input_sensors(hass)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    async def save(options):
        await hass.services.async_call(
            DOMAIN, "set_option", {"options": options}, blocking=True)
        await hass.async_block_till_done()

    # A markup beside the default all-in basis.
    with pytest.raises(ServiceValidationError) as err:
        await save({MARKUP: 0.02})
    assert err.value.translation_key == ERR_KEY
    assert MARKUP not in entry.options

    await save({BASIS: vl.BASIS_SPOT, MARKUP: 0.02})
    assert entry.options[MARKUP] == 0.02

    # Back to all-in while the markup is set.
    with pytest.raises(ServiceValidationError):
        await save({BASIS: vl.BASIS_ALL_IN})
    assert entry.options[BASIS] == vl.BASIS_SPOT

    # Zeroing is always allowed; then all-in is fine again.
    await save({MARKUP: 0.0})
    await save({BASIS: vl.BASIS_ALL_IN})
    assert entry.options[BASIS] == vl.BASIS_ALL_IN
