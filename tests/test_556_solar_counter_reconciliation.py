"""#556 — daily solar reconciliation against hardware production counters.

Cloud-polled solar power sensors (Deye Cloud) sit at 0/unavailable
between polls, so power integration undercounts badly (reporter: SEM
6.2 kWh vs inverter 18.6 kWh). When production counters are configured
(``prefer_hardware_energy``), daily solar follows the counters —
upward-only, so integration stays the floor.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)

TODAY = date(2026, 7, 4)
MONTH = "2026_7"
YEAR = "2026"


def _state(value, unit="kWh"):
    return SimpleNamespace(state=str(value), attributes={"unit_of_measurement": unit})


def _hass_with(states: dict):
    hass = MagicMock()
    hass.states.get = lambda eid: states.get(eid)
    return hass


def _calc(states, entities=("sensor.pv_counter",), enabled=True, config=None):
    calc = EnergyCalculator(config=config or {"system_size_kwp": 15}, time_manager=MagicMock())
    calc.configure_solar_counters(_hass_with(states), list(entities), enabled)
    return calc


def _reconcile(calc):
    calc._reconcile_solar_energy(TODAY, MONTH, YEAR)


def _daily(calc):
    return calc._daily_accumulators.get(f"solar_{TODAY}", 0.0)


@pytest.mark.unit
class TestSolarCounterReconciliation:

    def test_lifetime_counter_tracks_daily(self):
        states = {"sensor.pv_counter": _state(5000.0)}
        calc = _calc(states)
        _reconcile(calc)  # baseline at 5000, integrated 0
        assert _daily(calc) == 0.0

        states["sensor.pv_counter"] = _state(5012.4)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(12.4)
        assert calc._monthly_accumulators[f"solar_{MONTH}"] == pytest.approx(12.4)
        assert calc._yearly_accumulators[f"solar_{YEAR}"] == pytest.approx(12.4)
        assert calc._lifetime_accumulators["lifetime_solar"] == pytest.approx(12.4)

    def test_wh_counter_is_unit_aware(self):
        states = {"sensor.pv_counter": _state(5_000_000, "Wh")}
        calc = _calc(states)
        _reconcile(calc)
        states["sensor.pv_counter"] = _state(5_012_400, "Wh")
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(12.4)

    def test_counter_tops_up_stalled_integration(self):
        # Integration stalls (cloud sensor at 0) while the counter moves →
        # the missed energy is credited on top of the anchor
        states = {"sensor.pv_counter": _state(5000.0)}
        calc = _calc(states)
        calc._daily_accumulators[f"solar_{TODAY}"] = 8.0
        _reconcile(calc)  # anchor = 8.0, baseline = 5000
        states["sensor.pv_counter"] = _state(5001.0)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(9.0)  # 8.0 anchor + 1.0 counter delta

    def test_integration_ahead_of_counter_is_floor(self):
        # Counter lags (cloud counters update slowly too) → the integrated
        # value is never reduced
        states = {"sensor.pv_counter": _state(5000.0)}
        calc = _calc(states)
        _reconcile(calc)  # anchor = 0, baseline = 5000
        calc._daily_accumulators[f"solar_{TODAY}"] = 6.0  # integrator ran ahead
        states["sensor.pv_counter"] = _state(5002.0)  # counter only +2
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(6.0)  # target 2.0 < integrated → floor

    def test_integrated_at_baseline_is_credited(self):
        # SEM integrated 3.0 before the counter first appeared
        states = {}
        calc = _calc(states, entities=("sensor.pv_counter",))
        calc._daily_accumulators[f"solar_{TODAY}"] = 3.0
        _reconcile(calc)  # counter unavailable → no-op
        assert _daily(calc) == 3.0
        states["sensor.pv_counter"] = _state(5000.0)
        _reconcile(calc)  # baseline 5000, anchor 3.0
        states["sensor.pv_counter"] = _state(5010.0)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(13.0)  # 3.0 + 10.0

    def test_daily_type_counter_reset_rebaselines(self):
        # A DailyActiveProduction-style counter drops to ~0 at midnight /
        # inverter reboot — value keeps, counting continues
        states = {"sensor.pv_counter": _state(0.0)}
        calc = _calc(states)
        _reconcile(calc)
        states["sensor.pv_counter"] = _state(10.0)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(10.0)
        states["sensor.pv_counter"] = _state(2.0)  # went backwards → re-baseline
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(10.0)  # nothing lost
        states["sensor.pv_counter"] = _state(5.0)  # +3 since re-baseline
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(13.0)

    def test_unavailable_counter_never_shrinks_day(self):
        states = {"sensor.pv_counter": _state(5000.0)}
        calc = _calc(states)
        _reconcile(calc)
        states["sensor.pv_counter"] = _state(5015.0)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(15.0)
        states["sensor.pv_counter"] = SimpleNamespace(
            state="unavailable", attributes={}
        )
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(15.0)

    def test_multi_counter_sum(self):
        states = {
            "sensor.pv1": _state(1000.0),
            "sensor.pv2": _state(2000.0),
        }
        calc = _calc(states, entities=("sensor.pv1", "sensor.pv2"))
        _reconcile(calc)
        states["sensor.pv1"] = _state(1004.0)
        states["sensor.pv2"] = _state(2006.0)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(10.0)
        assert calc._monthly_accumulators[f"solar_{MONTH}"] == pytest.approx(10.0)
        assert calc._yearly_accumulators[f"solar_{YEAR}"] == pytest.approx(10.0)
        assert calc._lifetime_accumulators["lifetime_solar"] == pytest.approx(10.0)

    def test_entity_list_change_reanchors(self):
        # ED re-read returns a different counter set mid-day — anchor must
        # be recalibrated, day value keeps
        states = {"sensor.pv1": _state(1000.0)}
        calc = _calc(states, entities=("sensor.pv1",))
        _reconcile(calc)
        states["sensor.pv1"] = _state(1008.0)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(8.0)
        states["sensor.pv2"] = _state(2000.0)
        calc.configure_solar_counters(
            calc._hass, ["sensor.pv1", "sensor.pv2"], True
        )
        _reconcile(calc)  # re-anchor at 8.0, fresh baselines
        assert _daily(calc) == pytest.approx(8.0)
        states["sensor.pv1"] = _state(1010.0)
        states["sensor.pv2"] = _state(2003.0)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(13.0)  # 8 + 2 + 3

    def test_disabled_knob_is_noop(self):
        states = {"sensor.pv_counter": _state(5000.0)}
        calc = _calc(states, enabled=False)
        _reconcile(calc)
        states["sensor.pv_counter"] = _state(5012.0)
        _reconcile(calc)
        assert _daily(calc) == 0.0

    def test_sanity_cap_ignores_unit_mismatch(self):
        # 15 kWp × 16h = 240 kWh cap
        states = {"sensor.pv_counter": _state(5000.0)}
        calc = _calc(states)
        _reconcile(calc)
        states["sensor.pv_counter"] = _state(5500.0)  # +500 kWh "today"
        _reconcile(calc)
        assert _daily(calc) == 0.0  # ignored, integrator stays authoritative

    def test_day_rollover_resets_baselines(self):
        states = {"sensor.pv_counter": _state(5000.0)}
        calc = _calc(states)
        _reconcile(calc)
        states["sensor.pv_counter"] = _state(5010.0)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(10.0)
        # Next day: fresh baselines, fresh anchor
        tomorrow = date(2026, 7, 5)
        calc._reconcile_solar_energy(tomorrow, MONTH, YEAR)
        states["sensor.pv_counter"] = _state(5013.0)
        calc._reconcile_solar_energy(tomorrow, MONTH, YEAR)
        assert calc._daily_accumulators.get(f"solar_{tomorrow}", 0.0) == pytest.approx(3.0)

    def test_baselines_survive_restart_and_credit_downtime(self):
        states = {"sensor.pv_counter": _state(5000.0)}
        calc = _calc(states)
        _reconcile(calc)
        states["sensor.pv_counter"] = _state(5005.0)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(5.0)

        # Restart: state round-trips; 7 kWh produced while SEM was down
        saved = calc.get_state()
        states["sensor.pv_counter"] = _state(5012.0)
        calc2 = _calc(states)
        calc2.restore_state(saved)
        _reconcile(calc2)
        assert _daily(calc2) == pytest.approx(12.0)  # downtime credited

    def test_no_double_count_with_live_integration(self):
        # Counter and integration both see the same energy → no adoption
        states = {"sensor.pv_counter": _state(5000.0)}
        calc = _calc(states)
        _reconcile(calc)
        # integration keeps up exactly
        calc._daily_accumulators[f"solar_{TODAY}"] = 10.0
        calc._monthly_accumulators[f"solar_{MONTH}"] = 10.0
        states["sensor.pv_counter"] = _state(5010.0)
        _reconcile(calc)
        assert _daily(calc) == pytest.approx(10.0)  # target == integrated → no delta
        assert calc._monthly_accumulators[f"solar_{MONTH}"] == pytest.approx(10.0)
