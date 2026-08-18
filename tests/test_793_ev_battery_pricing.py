"""#793 — EV energy drawn from the battery must not be priced at zero.

PROD showed lifetime_ev_cost = 7.00 CHF over 162.47 kWh (0.043 CHF/kWh) at a
66.4 % solar share: only the DIRECT grid increments were ever priced. The
~19 % of the car's energy that arrived via the battery — a battery that is
grid-charged most nights — was recorded as free, and it sat in the solar-share
denominator without appearing in either displayed number.

The battery savings path already answers "what did stored energy cost" through
the provenance pool (#770). The EV session simply never asked. The fix is one
rate — ``implied_cost_rate`` — the exact dual of ``implied_savings_rate``:
what one discharged kWh COSTS is the import rate minus what it SAVES.
"""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.battery_provenance import (
    BatteryProvenance,
)
from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.ev_control import (
    EVControlMixin,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerFlows, SessionData,
)


# ──────────────────────────────────────────────
# The rate itself
# ──────────────────────────────────────────────

@pytest.mark.unit
class TestImpliedCostRate:
    def test_a_grid_charged_pool_costs_what_was_paid(self):
        p = BatteryProvenance()
        p.charge("b1", solar_kwh=0.0, grid_kwh=5.0, import_rate=0.30)
        assert p.implied_cost_rate() == pytest.approx(0.30)

    def test_a_solar_pool_costs_nothing(self):
        p = BatteryProvenance()
        p.charge("b1", solar_kwh=5.0, grid_kwh=0.0, import_rate=0.30)
        assert p.implied_cost_rate() == 0.0

    def test_a_mixed_pool_costs_pro_rata(self):
        p = BatteryProvenance()
        p.charge("b1", solar_kwh=5.0, grid_kwh=5.0, import_rate=0.30)
        # 1.50 CHF tied up in 10 kWh — every discharged kWh carries 0.15.
        assert p.implied_cost_rate() == pytest.approx(0.15)

    def test_an_empty_pool_has_no_opinion_and_stays_free(self):
        # Silence is not a measurement (#755 contract 1) — and for a COST the
        # legacy answer is zero, exactly as before this rate existed.
        assert BatteryProvenance().implied_cost_rate() == 0.0

    def test_cost_and_savings_rates_are_duals(self):
        # What a discharged kWh costs + what it saves == the import rate:
        # the two views split one number, they never overlap or leave a gap.
        p = BatteryProvenance()
        p.charge("b1", solar_kwh=3.0, grid_kwh=7.0, import_rate=0.28)
        rate = 0.30
        assert p.implied_cost_rate() + p.implied_savings_rate(rate) == (
            pytest.approx(rate)
        )


@pytest.mark.unit
class TestCalculatorAccessor:
    def test_the_calculator_exposes_the_rate_publicly(self):
        calc = EnergyCalculator({"update_interval": 30}, MagicMock())
        calc._battery_provenance.charge(
            "b1", solar_kwh=0.0, grid_kwh=4.0, import_rate=0.25)
        assert calc.ev_battery_cost_rate() == pytest.approx(0.25)


# ──────────────────────────────────────────────
# The session pricing (production pair, production order — #753 harness)
# ──────────────────────────────────────────────

def _host(*, import_rate=0.30, battery_cost_rate=0.0):
    h = SimpleNamespace()
    h.config = {"update_interval": 3600}          # 1 h cycles: W == kWh×1000
    h._boot_monotonic = time.monotonic() - 9999.0
    h._last_ev_connected = True
    h._ev_conn_confirmed = {"": True}
    h._ev_conn_streak = {}
    h._session_data = SessionData(
        active=True, start_time="2026-08-18T08:00:00+02:00")
    h._storage = MagicMock()
    h._ev_device = None
    h._this_charger_power = lambda ev, p: float(getattr(p, "ev_power", 0.0))
    h._energy_calculator = SimpleNamespace(
        _import_rate=import_rate,
        ev_battery_cost_rate=lambda: battery_cost_rate,
    )
    return h


def _tick(h, flows):
    p = SimpleNamespace(ev_connected=True, ev_power=4000.0,
                        ev_connected_per_charger=None)
    EVControlMixin._confirm_ev_connection(h, p)
    EVControlMixin._update_session_tracking(h, p, flows)


@pytest.mark.unit
class TestSessionPricesBatteryEnergy:
    def test_battery_energy_from_a_grid_charged_pool_is_priced(self):
        # THE regression: 4 kWh via the battery, pool fully grid-charged at
        # 0.30 — today this session costs 0.00.
        h = _host(battery_cost_rate=0.30)
        _tick(h, PowerFlows(battery_to_ev=4000.0))
        assert h._session_data.battery_energy_kwh == pytest.approx(4.0)
        assert h._session_data.cost_chf == pytest.approx(4.0 * 0.30)

    def test_battery_energy_from_a_solar_pool_stays_free(self):
        h = _host(battery_cost_rate=0.0)
        _tick(h, PowerFlows(battery_to_ev=4000.0))
        assert h._session_data.cost_chf == 0.0

    def test_direct_grid_energy_still_prices_at_the_import_rate(self):
        h = _host(import_rate=0.30, battery_cost_rate=0.30)
        _tick(h, PowerFlows(grid_to_ev=2000.0))
        assert h._session_data.cost_chf == pytest.approx(2.0 * 0.30)

    def test_the_issue_headline_mixed_session(self):
        # 66.4 % solar / 19 % battery (grid-charged) / 14.6 % grid — the PROD
        # split. Cost must reflect BOTH non-solar fifths, not just one.
        h = _host(import_rate=0.30, battery_cost_rate=0.30)
        _tick(h, PowerFlows(solar_to_ev=6640.0, battery_to_ev=1900.0,
                            grid_to_ev=1460.0))
        expected = (1.9 + 1.46) * 0.30
        assert h._session_data.cost_chf == pytest.approx(expected)
        assert h._session_data.cost_chf > 0.6    # NOT the old 1.46×0.30 alone
        assert h._session_data.solar_share_pct == pytest.approx(66.4)


# ──────────────────────────────────────────────
# The missing fifth is visible
# ──────────────────────────────────────────────

@pytest.mark.unit
class TestLifetimeSharesAreAThreeWaySplit:
    def test_battery_and_grid_shares_published_beside_solar(self):
        # storage already holds all three kWh; the coordinator must derive
        # all three shares, not just solar.
        from custom_components.solar_energy_management.coordinator.coordinator import (
            _lifetime_ev_shares,
        )
        shares = _lifetime_ev_shares({
            "total_energy_kwh": 162.47, "total_solar_kwh": 107.88,
            "total_battery_kwh": 30.87, "total_grid_kwh": 23.72,
        })
        assert shares["lifetime_ev_solar_share"] == pytest.approx(66.4, abs=0.1)
        assert shares["lifetime_ev_battery_share"] == pytest.approx(19.0, abs=0.1)
        assert shares["lifetime_ev_grid_share"] == pytest.approx(14.6, abs=0.1)

    def test_an_empty_lifetime_publishes_zeros(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            _lifetime_ev_shares,
        )
        shares = _lifetime_ev_shares({})
        assert shares == {
            "lifetime_ev_solar_share": 0,
            "lifetime_ev_battery_share": 0,
            "lifetime_ev_grid_share": 0,
        }
