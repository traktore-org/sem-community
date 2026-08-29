"""The backfill lookback must be clamped where it is USED, not only in the UI.

Both backfill services declare `min: 14, max: 730` in `services.yaml`, but a
selector is a UI hint: a script, an automation or the Developer Tools YAML
editor can call the service with any number at all, and the handlers passed it
straight through to `int(days)` and on into a recorder statistics query.

A declared bound that nothing enforces is not a bound. Clamping lives in the
backfill functions rather than the service handlers so it protects every
caller, and the value is clamped rather than rejected — someone asking for
"all of it" should get the maximum, not an error.
"""
from __future__ import annotations

from custom_components.solar_energy_management.coordinator.ledger_backfill import (
    MAX_LOOKBACK_DAYS,
    MIN_LOOKBACK_DAYS,
    clamp_lookback_days,
)


class TestClampLookbackDays:
    def test_absurd_value_is_capped_not_passed_through(self):
        assert clamp_lookback_days(10**9) == MAX_LOOKBACK_DAYS

    def test_negative_and_zero_come_up_to_the_floor(self):
        assert clamp_lookback_days(-5) == MIN_LOOKBACK_DAYS
        assert clamp_lookback_days(0) == MIN_LOOKBACK_DAYS

    def test_a_value_inside_the_declared_range_is_untouched(self):
        assert clamp_lookback_days(365) == 365
        assert clamp_lookback_days(MIN_LOOKBACK_DAYS) == MIN_LOOKBACK_DAYS
        assert clamp_lookback_days(MAX_LOOKBACK_DAYS) == MAX_LOOKBACK_DAYS

    def test_junk_falls_back_to_the_default_rather_than_raising(self):
        """A service must not die on a typo — `int('all')` would have."""
        from custom_components.solar_energy_management.coordinator.ledger_backfill import (
            DEFAULT_LOOKBACK_DAYS,
        )
        assert clamp_lookback_days("all") == DEFAULT_LOOKBACK_DAYS
        assert clamp_lookback_days(None) == DEFAULT_LOOKBACK_DAYS
        assert clamp_lookback_days(float("nan")) == DEFAULT_LOOKBACK_DAYS

    def test_the_bounds_match_what_services_yaml_promises(self):
        import pathlib
        import re
        root = pathlib.Path(__file__).resolve().parent.parent
        text = (root / "services.yaml").read_text()
        block = text.split("backfill_forecast_ledger:")[1].split("\nbackfill_battery_nights:")[0]
        assert int(re.search(r"min:\s*(\d+)", block).group(1)) == MIN_LOOKBACK_DAYS
        assert int(re.search(r"max:\s*(\d+)", block).group(1)) == MAX_LOOKBACK_DAYS
