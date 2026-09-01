"""#893 — a passing cloud must not hard-stop a solar session on a priced grid.

DigitalOptics (Fronius, number-entity charger, SEM 2.0.0): solar-mode
charging "ignores buffer times for switching off … switches rapidly because
of clouds". Root cause: ``_idle_bridgeable``'s tariff clause applied to EVERY
mode, so any daytime dip during a not-cheap window was classed STRUCTURAL and
took the short grace instead of the 180 s bridge — for most tariffs, most of
the day. The clause is now scoped to the modes that actually price their grid
use (``MODE_USES_TARIFF``); everyone else is judged by the FUNDING clause,
which now also treats a battery forbidden from assisting like one below its
buffer, so #524's real case (a hold that would knowingly import grid) is
still caught.
"""
from __future__ import annotations

from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerEnergy,
    ChargerPower,
    ChargerView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide import (
    _idle_bridgeable,
)


def _view(mode="solar_only", *, solar_w=3500.0, home_w=600.0,
          battery_soc=80.0, buffer_soc=70.0, tariff_level="expensive",
          may_assist=True, min_solar_w=1000.0):
    return ChargerView(
        power=ChargerPower(charger_id="c1", power_w=0.0,
                           connected=True, charging=False),
        energy=ChargerEnergy(charger_id="c1"),
        mode=mode,
        config={"ev_min_current": 6, "ev_phases": 3, "ev_voltage": 230},
        fleet=FleetContext(
            solar_w=solar_w, home_w=home_w, battery_soc=battery_soc,
            buffer_soc=buffer_soc, tariff_level=tariff_level,
            battery_may_assist_ev=may_assist, min_solar_w=min_solar_w,
        ),
    )


class TestTheCloudCase:
    def test_a_solar_dip_on_an_expensive_tariff_bridges(self):
        """THE reported case: real sun (3.5 kW), surplus momentarily under
        the 6 A minimum, battery above buffer, price expensive. The hold is
        funded by the user's own surplus + pack — the price is nobody's
        business, and the bridge must engage."""
        ok, why = _idle_bridgeable(_view())
        assert ok is True, f"cloud dip classed structural: {why}"

    def test_every_non_tariff_mode_gets_the_same_answer(self):
        for mode in ("solar_only", "solar_plus_battery", "min_plus_solar",
                     "always_max", "off"):
            ok, why = _idle_bridgeable(_view(mode=mode))
            assert ok is True, (mode, why)

    def test_the_tariff_mode_keeps_524(self):
        """solar_plus_cheap PRICES its grid — an expensive window is still a
        structural stop there."""
        ok, why = _idle_bridgeable(_view(mode="solar_plus_cheap"))
        assert ok is False and "not-cheap" in why


class TestTheFundingClauseStillGuards:
    def test_sun_gone_is_structural(self):
        ok, why = _idle_bridgeable(_view(solar_w=200.0))
        assert ok is False and "sun gone" in why

    def test_below_buffer_with_no_surplus_is_structural(self):
        """#524's REAL case: the hold could only be grid-fed."""
        ok, why = _idle_bridgeable(
            _view(battery_soc=50.0, solar_w=1500.0, home_w=1400.0))
        assert ok is False and "no battery assist" in why

    def test_permission_off_counts_as_no_assist(self):
        """New with the scoping: a pack the user forbade from assisting must
        not fund the hold either — otherwise removing the blanket tariff
        clause would have opened a grid-funded hold for exactly the installs
        that opted their battery out."""
        ok, why = _idle_bridgeable(
            _view(battery_soc=90.0, may_assist=False,
                  solar_w=1500.0, home_w=1400.0))
        assert ok is False and "no battery assist" in why

    def test_permission_off_but_surplus_sufficient_still_bridges(self):
        ok, why = _idle_bridgeable(
            _view(battery_soc=90.0, may_assist=False,
                  solar_w=6000.0, home_w=500.0))
        assert ok is True, why
