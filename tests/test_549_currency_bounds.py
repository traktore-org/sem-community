"""#549 — monetary number bounds must fit any currency (no CHF/EUR-only cap).

A hardcoded max like 0.5 or 5.0 made the price entities unusable for
high-denomination currencies (LKR ~70/kWh, IDR/VND ~2500/kWh). Guard that the
backend entity descriptions AND the OptionsFlow selectors keep a
currency-agnostic ceiling so this can't regress.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_NUMBER = _ROOT / "number.py"
_FLOW = _ROOT / "config_flow.py"

# per-kWh rate/threshold entities need a high ceiling; demand charge higher.
_RATE_KEYS = (
    "electricity_import_rate", "electricity_export_rate",
    "cheap_price_threshold", "expensive_price_threshold",
)
_MIN_RATE_MAX = 1000.0   # must comfortably exceed any currency's per-kWh price


def _desc_max(src: str, key: str) -> float:
    # find the NumberEntityDescription block for ``key`` and its native_max_value
    m = re.search(rf'key="{key}".*?native_max_value=([0-9.]+)', src, re.S)
    assert m, f"native_max_value not found for {key}"
    return float(m.group(1))


def test_number_entity_rate_bounds_are_currency_agnostic():
    src = _NUMBER.read_text(encoding="utf-8")
    for key in _RATE_KEYS:
        mx = _desc_max(src, key)
        assert mx >= _MIN_RATE_MAX, f"{key} max {mx} too low for high-denomination currencies (#549)"
    # demand charge (per kW/month) needs an even higher ceiling
    assert _desc_max(src, "demand_charge_rate") >= 10000.0


def test_config_flow_rate_selectors_are_currency_agnostic():
    src = _FLOW.read_text(encoding="utf-8")
    # every per-kWh NumberSelectorConfig must allow a high max
    kwh_maxes = re.findall(
        r"NumberSelectorConfig\(min=0\.0, max=([0-9.]+), step=[0-9.]+, "
        r'unit_of_measurement=f"\{currency\}/kWh"', src)
    assert kwh_maxes, "no currency/kWh selectors found in config_flow"
    for mx in kwh_maxes:
        assert float(mx) >= _MIN_RATE_MAX, f"config_flow /kWh selector max {mx} too low (#549)"
