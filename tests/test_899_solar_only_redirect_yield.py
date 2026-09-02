"""#899 — solar_only imports grid: the battery redirect is credited to the
car but nothing makes the battery yield.

koen71 (HA community, post #31), ABB Terra + Huawei SUN2000/LUNA2000:

    solar_only: surplus=1500W (bare=0W + redirect=1500W) → 6A
                (solar=3800W, home=1100W, batt_chg=2700W)

The redirect adds a share of the MEASURED battery charge power to the bare
surplus on the assumption that the inverter self-consumes the residual —
the car takes the amps and the battery gets less. That holds for an
inverter left alone. It fails whenever the pack keeps charging anyway (a
TOU window, a forced charge, SEM's OWN force_charge): the car draws the
redirected amps and the meter funds them. And SEM never checked.

Two closures:

1. Parity with ``reclaimable_battery_w``: a COMMANDED battery is honoured —
   its watts are never sold to the car.
2. Commit-then-measure: the redirect counts only while the meter agrees.
   Sustained grid import with a redirect in the budget means the pack did
   not yield — the redirect is dropped for that session.
"""
from __future__ import annotations


from custom_components.solar_energy_management.coordinator.build_view import (
    build_charger_view,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerEnergy,
    ChargerIntent,
    ChargerPower,
    ChargerView,
    FleetContext,
    FleetCycleState,
)
from custom_components.solar_energy_management.coordinator.decide import SolarOnlyMode
from custom_components.solar_energy_management.coordinator.energy_reclaim import (
    REDIRECT_IMPORT_TOLERANCE_W,
    REDIRECT_VETO_STRIKES,
    redirect_strikes,
)
from custom_components.solar_energy_management.coordinator.flow_calculator import (
    battery_redirect_w,
)
from custom_components.solar_energy_management.coordinator.per_charger_context import (
    PerChargerState,
    note_redirect_outcome,
)


def _view(*, battery_commanded=False, redirect_allowed=True,
          solar_w=3800.0, home_w=1100.0, battery_charge_w=2700.0,
          battery_soc=60.0, forecast_remaining_kwh=30.0):
    fleet = FleetContext(
        solar_w=solar_w, home_w=home_w, battery_charge_w=battery_charge_w,
        battery_soc=battery_soc, auto_start_soc=90.0,
        battery_capacity_kwh=15.0, forecast_remaining_kwh=forecast_remaining_kwh,
        battery_commanded=battery_commanded, min_solar_w=200.0,
    )
    return ChargerView(
        power=ChargerPower(charger_id="terra", power_w=0.0, connected=True),
        energy=ChargerEnergy(charger_id="terra", day_kwh=0.0),
        mode="solar_only",
        config={"ev_min_current": 6, "ev_phases": 1, "ev_voltage": 230,
                "ev_max_current": 16},
        fleet=fleet,
        redirect_allowed=redirect_allowed,
    )


class TestCommandedBatteryKeepsItsWatts:
    def test_helper_returns_zero_when_commanded(self):
        assert battery_redirect_w(2700.0, 60.0, 15.0, 30.0, battery_commanded=True) == 0
        assert battery_redirect_w(2700.0, 60.0, 15.0, 30.0) > 0

    def test_decide_credits_nothing_from_a_commanded_pack(self):
        d = SolarOnlyMode().decide(_view(battery_commanded=True))
        assert d.intent is ChargerIntent.IDLE, d.reason
        assert "redirect=0W" in d.reason, d.reason

    def test_the_report_itself_charges_without_the_closure(self):
        """koen71's numbers reproduce: bare 0 + redirect > min → 6 A."""
        d = SolarOnlyMode().decide(_view())
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS, d.reason
        assert "bare=0W" in d.reason


class TestTheMeterHasTheLastWord:
    def test_strikes_count_only_import_with_a_redirect_while_charging(self):
        n = redirect_strikes(0, redirect_w=1500.0,
                             grid_import_w=REDIRECT_IMPORT_TOLERANCE_W + 1,
                             charging=True)
        assert n == 1
        assert redirect_strikes(n, redirect_w=1500.0, grid_import_w=2000.0, charging=True) == 2

    def test_a_cycle_that_agrees_resets(self):
        assert redirect_strikes(2, redirect_w=1500.0, grid_import_w=0.0, charging=True) == 0
        assert redirect_strikes(2, redirect_w=0.0, grid_import_w=2000.0, charging=True) == 0
        assert redirect_strikes(2, redirect_w=1500.0, grid_import_w=2000.0, charging=False) == 0

    def test_the_veto_lands_on_the_state_and_gates_decide(self):
        st = PerChargerState()
        for _ in range(REDIRECT_VETO_STRIKES):
            note_redirect_outcome(st, redirect_w=1500.0, grid_import_w=2000.0, charging=True)
        assert st.redirect_vetoed is True
        d = SolarOnlyMode().decide(_view(redirect_allowed=not st.redirect_vetoed))
        assert d.intent is ChargerIntent.IDLE, d.reason
        assert "redirect=0W" in d.reason

    def test_a_vetoed_session_ends_at_unplug(self):
        st = PerChargerState(redirect_vetoed=True, redirect_strikes=3)
        st.reset_session()
        assert st.redirect_vetoed is False and st.redirect_strikes == 0

    def test_one_strike_short_keeps_the_redirect(self):
        st = PerChargerState()
        for _ in range(REDIRECT_VETO_STRIKES - 1):
            note_redirect_outcome(st, redirect_w=1500.0, grid_import_w=2000.0, charging=True)
        assert st.redirect_vetoed is False


class TestViewPlumbing:
    def test_build_charger_view_carries_the_flag(self):
        from unittest.mock import MagicMock
        power = MagicMock()
        power.solar_power = 3800.0; power.home_consumption_power = 1100.0
        power.battery_soc = 60.0; power.battery_soc_known = True
        power.battery_soc_unavailable = False; power.inputs_degraded = False
        power.ev_power_per_charger = {}; power.ev_connected_per_charger = {}
        power.ev_charging_per_charger = {}
        fs = FleetCycleState(power=power, config={})
        v = build_charger_view(fs, charger_id="terra", charger_cfg={},
                               mode="solar_only", daily_ev_kwh=0.0,
                               redirect_allowed=False)
        assert v.redirect_allowed is False
        v2 = build_charger_view(fs, charger_id="terra", charger_cfg={},
                                mode="solar_only", daily_ev_kwh=0.0)
        assert v2.redirect_allowed is True

    def test_the_loop_records_the_outcome_and_passes_the_flag(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import coordinator
        src = inspect.getsource(coordinator)
        assert "note_redirect_outcome(" in src
        assert "redirect_allowed=" in src
