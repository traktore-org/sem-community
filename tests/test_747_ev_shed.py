"""#747 — a shed-level peak throttles the EV, in EVERY mode.

Azlinon's live report: peak reached CRITICAL, the load manager shed his
chest freezers, and the EVSE — the single largest controllable load —
held 32 A untouched. The exclusion in load_management (#461-peak /
#649: two engines must not actuate one device) is right and stays; what
was missing is the OTHER half of its premise: decide() never saw the
peak state at all during the day.

The fix follows the fleet-state pattern: ``peak_state`` resolves once
per cycle into ``FleetCycleState``, rides into every ``FleetContext``,
and ``decide()`` applies a SENIOR clamp after mode dispatch — peak shed
is a guarantee, senior even to always_max:

* SHEDDING → clamp the commanded amps to the effective minimum
  (CHARGE_MAX becomes CHARGE_AT_AMPS at min — hardware max is exactly
  the 32 A this bug is about);
* EMERGENCY → IDLE, not bridgeable;
* NORMAL / WARNING → untouched, and an already-idle decision is never
  touched (no clamp noise on a charger that wasn't charging).

The EV throttles on the FIRST cycle of SHEDDING — before the load
manager's delayed progressive shed reaches anyone's freezer.
"""

import pytest

from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerIntent,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide import decide

from .test_decide import _view


@pytest.mark.unit
class TestFleetCarriesThePeakState:
    def test_fleet_context_has_the_field_defaulting_normal(self):
        f = FleetContext()
        assert f.peak_state == "normal"


def _mk(mode, peak_state, **kw):
    v = _view(mode, **kw)
    f = v.fleet
    object.__setattr__(f, "peak_state", peak_state)
    return v


@pytest.mark.unit
class TestSheddingClampsEveryMode:
    def test_min_plus_solar_surplus_clamps_to_min(self):
        # Plenty of surplus → the mode would offer well above min.
        v = _mk("min_plus_solar", "shedding", solar_w=9000, home_w=500)
        d = decide(v)
        assert d.intent == ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 6
        assert "peak" in d.reason.lower()

    def test_always_max_is_not_exempt(self):
        v = _mk("always_max", "shedding")
        d = decide(v)
        assert d.intent == ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 6

    def test_an_offer_already_at_or_below_min_is_untouched(self):
        v = _mk("solar_only", "shedding", solar_w=0.0, is_night=True)
        d = decide(v)
        assert d.intent == ChargerIntent.IDLE  # nothing to clamp

    def test_vehicle_min_floor_is_respected(self):
        v = _mk("always_max", "shedding",
                config={"ev_min_current": 6, "vehicle_min_current": 9,
                        "ev_phases": 3, "ev_voltage": 230,
                        "ev_max_current": 32})
        d = decide(v)
        assert d.commanded_amps == 9  # a Zoe's handshake floor survives


@pytest.mark.unit
class TestEmergencyIdlesTheCharger:
    @pytest.mark.parametrize("mode", ["always_max", "min_plus_solar",
                                      "solar_only", "solar_plus_cheap"])
    def test_every_mode_idles(self, mode):
        v = _mk(mode, "emergency", solar_w=9000, home_w=500)
        d = decide(v)
        assert d.intent == ChargerIntent.IDLE
        assert d.bridgeable is False
        assert "peak" in d.reason.lower()


@pytest.mark.unit
class TestNormalAndWarningAreUntouched:
    @pytest.mark.parametrize("peak_state", ["normal", "warning"])
    def test_the_offer_stands(self, peak_state):
        v = _mk("always_max", peak_state)
        d = decide(v)
        assert d.intent == ChargerIntent.CHARGE_MAX

    def test_disconnected_stays_disconnected(self):
        v = _mk("always_max", "shedding", connected=False)
        d = decide(v)
        assert d.intent == ChargerIntent.IDLE
        assert "disconnected" in d.reason


@pytest.mark.unit
class TestTheStateReachesTheView:
    def test_fleet_cycle_state_resolves_it_and_build_view_passes_it(self):
        import inspect
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        from custom_components.solar_energy_management.coordinator import build_view
        assert "peak_state" in inspect.getsource(
            SEMCoordinator._build_fleet_cycle_state)
        assert "peak_state" in inspect.getsource(build_view)
