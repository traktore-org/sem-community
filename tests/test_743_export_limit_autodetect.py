"""#743 — export-limit autodetection across the supported brands.

The physics signature is brand-agnostic; brands that PUBLISH their
export limit sharpen it (Guido: "extend the autodetection on the other
supported inverters as well"). Two pieces, both here:

- the keyword scan (same #593 pattern as battery-cycles/SOC autodetect:
  entities on the solar anchor's device, curated keyword list), and
- the state parser: entity state → tri-state (True = ~0-export limit
  ACTIVE, False = not limiting, None = unreadable → physics decides).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    EXPORT_LIMIT_KEYWORDS,
    SensorReader,
    parse_export_limited,
)


class TestTheParser:
    @pytest.mark.parametrize("state,unit,expected", [
        # Huawei (wlcrs) active power control — string states
        ("Limited to 0.0 W", None, True),
        ("Limited to 5000 W", None, False),
        ("Unlimited", None, False),
        ("Zero export", None, True),
        # GoodWe core: number.goodwe_grid_export_limit (W)
        ("0", "W", True),
        ("6600", "W", False),
        # SolaX / modbus exports in kW
        ("0.0", "kW", True),
        ("5.0", "kW", False),
        # Percent variants (grid export limit %)
        ("0", "%", True),
        ("100", "%", False),
        # Bare numbers default to watts
        ("0", None, True),
        ("8000", None, False),
        # Unreadable → the physics signature decides
        ("unavailable", None, None),
        ("unknown", None, None),
        (None, None, None),
    ])
    def test_brand_shapes(self, state, unit, expected):
        assert parse_export_limited(state, unit) is expected


class TestTheKeywords:
    @pytest.mark.parametrize("name", [
        "inverter_active_power_control",       # Huawei (wlcrs)
        "goodwe_grid_export_limit",            # GoodWe core
        "solax_export_control_user_limit",     # SolaX modbus
        "victron_maximum_feed_in",             # Victron ESS
        "se_export_limitation",                # SolarEdge modbus packs
        "wr_einspeiselimit",                   # DE-named template
    ])
    def test_supported_brand_names_match(self, name):
        assert any(k in name for k in EXPORT_LIMIT_KEYWORDS), name

    @pytest.mark.parametrize("name", [
        "battery_1_soc",
        "inverter_eingangsleistung",
        "grid_power",
        "daily_export_energy",   # an ENERGY total, not a limit
    ])
    def test_unrelated_entities_do_not_match(self, name):
        assert not any(k in name for k in EXPORT_LIMIT_KEYWORDS), name


class _Stub:
    """The reader's autodetect, hosted on the two attributes it reads."""
    detect_export_limit_entity = SensorReader.detect_export_limit_entity
    _resolve_solar_anchor = SensorReader._resolve_solar_anchor

    def __init__(self, ed_config=None):
        self.hass = None          # registry lookup raises → best-effort None
        self._energy_dashboard_config = ed_config


class TestTheAnchor:
    """Live on HA-PROD 09.08.2026: SEM takes its solar sensor from the
    Energy Dashboard, so ``solar_production_sensor`` is not in config at
    all — the autodetect was handed None and never scanned, on the very
    Huawei install the feature was written for. The ED-resolved solar
    entity is the anchor of record when config has none.
    """

    def test_falls_back_to_the_energy_dashboard_solar_entity(self):
        ed = SimpleNamespace(
            solar_power="sensor.inverter_eingangsleistung", solar_energy=None,
        )
        s = _Stub(ed)
        assert s._resolve_solar_anchor(None) == "sensor.inverter_eingangsleistung"

    def test_falls_back_to_the_solar_energy_counter(self):
        """Power may be derived (stat_rate) with no power entity; the
        lifetime-yield counter sits on the same inverter device."""
        ed = SimpleNamespace(
            solar_power=None, solar_energy="sensor.inverter_gesamtenergieertrag",
        )
        s = _Stub(ed)
        assert (
            s._resolve_solar_anchor(None)
            == "sensor.inverter_gesamtenergieertrag"
        )

    def test_configured_sensor_still_wins(self):
        ed = SimpleNamespace(solar_power="sensor.ed_solar", solar_energy=None)
        s = _Stub(ed)
        assert s._resolve_solar_anchor("sensor.configured") == "sensor.configured"

    def test_no_anchor_anywhere_is_not_an_error(self):
        s = _Stub(None)
        assert s._resolve_solar_anchor(None) is None
        assert s.detect_export_limit_entity(None) is None
