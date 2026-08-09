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

import pytest

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    EXPORT_LIMIT_KEYWORDS,
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
