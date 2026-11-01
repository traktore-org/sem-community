"""#1269 — a held solar read never covers what live sources already cover.

The inverter reads dark; its last solar watts are booked for the grace
(#1177). If the sun drops in that time and the battery starts to discharge,
the held 3 kW still "covered" the house in the split, and the live battery
was paid as a second source: the house was saved twice.

The books now cap a held supply at the demand the live supplies leave open.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.tests.test_1177_dark_read_integral import (  # noqa: E501
    _kwh,
    clock,  # noqa: F401 — the frozen-noon fixture
)
from custom_components.solar_energy_management.tests.test_1185_dark_read_flows import (  # noqa: E501
    LIVE,
    RATE,
    _calc,
    _savings,
    _turn,
)

BATTERY_SAVES = "cost_batt_savings"


def _batt_savings(calc) -> float:
    from custom_components.solar_energy_management.tests.test_1177_dark_read_integral import (  # noqa: E501
        DAY,
    )
    return calc._daily_cost_accumulators.get(f"{BATTERY_SAVES}_{DAY}", 0.0)


# The sun drops: solar reads dark (held 3 kW), the battery gives 2 kW, the
# house takes 1 kW and 1 kW goes out to the grid.
SUN_DROPS = dict(solar_power=0.0, solar_power_unavailable=True,
                 battery_power=-2000.0, grid_power=1000.0,
                 home_shown_w=1000.0)


@pytest.mark.unit
@pytest.mark.usefixtures("clock")
class TestHeldSolarBesideALiveBattery:
    def test_the_house_is_saved_once(self):
        calc, _ = _calc()
        calc._import_rate = RATE
        _turn(calc, **LIVE)                       # 1 kW of solar saved
        before = _savings(calc)
        _turn(calc, **SUN_DROPS)
        assert _savings(calc) - before == pytest.approx(0.0), (
            "the held solar covers nothing the battery does not already cover")

    def test_the_battery_keeps_its_share(self):
        calc, _ = _calc()
        calc._import_rate = RATE
        _turn(calc, **LIVE)
        _turn(calc, **SUN_DROPS)
        # 2 kW out: 1 kW to the house (saved), 1 kW to the grid (paid at the meter)
        assert _batt_savings(calc) == pytest.approx(_kwh(1000.0, 1) * RATE)

    def test_the_flows_balance(self):
        calc, _ = _calc()
        _turn(calc, **LIVE)
        _turn(calc, **SUN_DROPS)
        f = calc.book_flows
        assert f.solar_to_home == pytest.approx(0.0)
        assert f.battery_to_home == pytest.approx(1000.0)
        assert f.battery_to_grid == pytest.approx(1000.0)

    def test_a_held_solar_that_fits_is_kept(self):
        """Solar held at 3 kW, battery live at 500 W out, house 1 kW and
        export 2.5 kW: the demand has room, so the held read stays whole."""
        calc, _ = _calc()
        calc._import_rate = RATE
        _turn(calc, **LIVE)
        _turn(calc, solar_power=0.0, solar_power_unavailable=True,
              battery_power=-500.0, grid_power=2500.0, home_shown_w=1000.0)
        assert calc.book_flows.solar_to_home == pytest.approx(1000.0)
        assert calc.book_power.solar_power == pytest.approx(3000.0)

    def test_the_rows_still_book_the_held_watts(self):
        """Only the split changes; the solar row keeps the held read."""
        from custom_components.solar_energy_management.tests.test_1177_dark_read_integral import (  # noqa: E501
            _row,
        )
        calc, _ = _calc()
        _turn(calc, **LIVE)
        _turn(calc, **SUN_DROPS)
        assert _row(calc, "solar") == pytest.approx(_kwh(3000.0, 2))
