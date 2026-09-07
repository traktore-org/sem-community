"""(#932 audit, finding 4) The arbitrage config keys survive a null.

``config.get(key, default)`` hands the default back only when the key is
MISSING. An options file carrying ``"battery_arbitrage_reserve_soc": null``
— a hand edit, a migration — reached the scheduler as ``None``, and
``current_soc <= None`` raised a TypeError that the cycle's blanket except
swallowed: arbitrage silently off, no Repair. ``spendable_budget`` was
bitten by exactly this on ``battery_reserve_soc`` and grew a guard; the
scheduler's keys never got it.
"""

from __future__ import annotations

from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
    SchedulerConfig,
    _num,
)


class TestNoneIsAnAbsenceNotAZero:

    def test_none_takes_the_default(self):
        assert _num(None, 50.0) == 50.0

    def test_zero_is_a_choice_and_is_kept(self):
        assert _num(0, 50.0) == 0.0

    def test_a_string_number_is_a_number(self):
        assert _num("42", 50.0) == 42.0

    def test_garbage_takes_the_default(self):
        assert _num("fifty", 50.0) == 50.0


class TestTheSchedulerConfigReadsThemThroughIt:

    def test_a_null_reserve_does_not_reach_the_slot_math(self):
        cfg = SchedulerConfig.from_config({
            "battery_arbitrage_reserve_soc": None,
            "battery_arbitrage_min_export_price": None,
            "battery_max_discharge_power": None,
            "battery_max_grid_import_w": None,
        })
        assert cfg.arbitrage_reserve_soc == 50.0
        assert cfg.arbitrage_min_export_price == 0.20
        assert cfg.max_discharge_power_w == 5000.0
        assert cfg.max_grid_import_w == 0.0

    def test_a_missing_key_still_takes_the_default(self):
        cfg = SchedulerConfig.from_config({})
        assert cfg.arbitrage_reserve_soc == 50.0

    def test_an_explicit_zero_reserve_is_honoured(self):
        cfg = SchedulerConfig.from_config({"battery_arbitrage_reserve_soc": 0})
        assert cfg.arbitrage_reserve_soc == 0.0
