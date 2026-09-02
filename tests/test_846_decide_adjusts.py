"""#846 — the ADJUST leg: the pure decision converts watts to amps with the
measured table, not nameplate.

Without this the learner is a diagnostic. `decide()` is pure — no
coordinator, no learner — so the table travels on the ChargerView as a
typed field (the #638 lesson: a key smuggled through ``config`` is
invisible to a reader of decide()), filled by ``build_charger_view`` from
the coordinator's learner for the phase count SEM believes.

On the PROD Zoe: a 4.0 kW surplus is BELOW the 5.5 kW nameplate minimum
(8 A × 690) — solar_only idled on it — while the car charges happily at
3.3 kW on 8 A. And 5.5 kW of surplus buys 10 A on this car (5.13 kW), not
the 7 → 8 A nameplate arithmetic hands out.
"""
from __future__ import annotations

import inspect
from dataclasses import replace

import pytest

from custom_components.solar_energy_management.coordinator import decide as dm
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerIntent,
)
from custom_components.solar_energy_management.coordinator.decide import (
    amps_from_watts,
    decide,
)
from custom_components.solar_energy_management.coordinator.watts_per_amp import (
    amps_that_fit,
    predict_watts,
)
from custom_components.solar_energy_management.tests.test_decide import _view

NOMINAL_3P = 690.0
ZOE = {8: 415.0, 16: 626.25}          # W/A, the two buckets PROD learned first
CFG = {"ev_min_current": 8, "ev_max_current": 16, "ev_phases": 3, "ev_voltage": 230}


class TestThePureHelpers:
    def test_predict_is_nameplate_without_a_table(self):
        assert predict_watts({}, 10, NOMINAL_3P) == pytest.approx(6900)
        assert predict_watts(None, 10, NOMINAL_3P) == pytest.approx(6900)

    def test_predict_reads_the_bucket_and_bridges_between(self):
        assert predict_watts(ZOE, 8, NOMINAL_3P) == pytest.approx(3320)
        assert predict_watts(ZOE, 12, NOMINAL_3P) == pytest.approx(6670)
        assert predict_watts(ZOE, 20, NOMINAL_3P) == pytest.approx(20 * 690)

    def test_amps_that_fit_walks_the_ladder(self):
        assert amps_that_fit(ZOE, 5500.0, NOMINAL_3P, 16) == 10
        assert amps_that_fit({}, 5500.0, NOMINAL_3P, 16) == 7
        assert amps_that_fit(ZOE, 100.0, NOMINAL_3P, 16) == 0

    def test_amps_from_watts_keeps_its_nameplate_contract_without_a_table(self):
        assert amps_from_watts(5500.0, 3, 230) == 7
        assert amps_from_watts(5500.0, 3, 230, {}) == 7
        assert amps_from_watts(5500.0, 3, 230, ZOE) == 10


class TestSolarOnlyAdjusts:
    def _v(self, surplus_w, table=None):
        v = _view("solar_only", solar_w=surplus_w + 500.0, home_w=500.0, config=dict(CFG))
        return replace(v, wpa_table=dict(table or {}))

    def test_nameplate_idles_on_four_kilowatts(self):
        d = decide(self._v(4000.0))
        assert d.intent is ChargerIntent.IDLE

    def test_the_measured_car_charges_on_four_kilowatts(self):
        d = decide(self._v(4000.0, ZOE))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 8

    def test_five_and_a_half_kilowatts_buys_ten_amps_not_idle(self):
        # nameplate: 5500 W < 8 A × 690 = 5520 W minimum → the car sits idle
        assert decide(self._v(5500.0)).intent is ChargerIntent.IDLE
        # measured: 10 A takes 5.13 kW on this car — charge, and at 10 A
        d = decide(self._v(5500.0, ZOE))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS and d.commanded_amps == 10

    def test_the_ceiling_still_holds(self):
        assert decide(self._v(30000.0, ZOE)).commanded_amps == 16


class TestTheTableTravelsAsATypedField:
    def test_the_view_carries_it_and_defaults_empty(self):
        v = _view("solar_only")
        assert v.wpa_table == {}
        assert replace(v, wpa_table=ZOE).wpa_table == ZOE

    def test_every_conversion_in_decide_reads_the_view(self):
        src = inspect.getsource(dm)
        code = "\n".join(l.split("#", 1)[0] for l in src.split("\n"))
        # both amps conversions and every "minimum charge" threshold
        assert code.count("view.wpa_table") >= 5
        assert "amps_from_watts(surplus_w, phases, voltage, view.wpa_table)" in code
        assert "amps_from_watts(budget_w, phases, voltage, view.wpa_table)" in code
        # no bare nameplate minimum survives
        assert "min_amps * phases * voltage" not in code
        assert "min_amps * max(1, phases) * max(1, voltage)" not in code

    def test_build_view_and_every_coordinator_site_pass_it(self):
        from custom_components.solar_energy_management.coordinator import build_view as bv
        from custom_components.solar_energy_management.coordinator import coordinator as cm
        assert "wpa_table=dict(wpa_table or {})" in inspect.getsource(bv)
        src = inspect.getsource(cm)
        # Every view build passes the table — and since #904 so does every
        # plan-overlay call (block watts → amps by the same ladder).
        assert src.count("wpa_table=self._wpa_table_for(") == (
            src.count("build_charger_view(") + src.count("ev_overlay("))

    def test_the_coordinator_hands_over_the_believed_phase_table(self):
        from custom_components.solar_energy_management.tests.test_846_measured_wpa import (
            _drive, _prod_coordinator,
        )
        c = _prod_coordinator()
        assert c._wpa_table_for("keba_prod") == {}
        _drive(c)
        assert c._wpa_table_for("keba_prod") == {16: pytest.approx(626.25)}
        # a disputed belief hands over nothing — nameplate, never a guess
        d = _prod_coordinator(switching=True, believed=3, contradictions=1)
        _drive(d)
        assert d._wpa_table_for("keba_prod") == {}
