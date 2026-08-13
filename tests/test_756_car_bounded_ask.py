"""#756 — the night ask is bounded by the car, not by the calendar.

N1 (.175, 12→13.08): ``build_night_target_map`` computes
``max(0, target − daily)`` off the calendar counter, which rolls at
midnight. At 00:01 the ask for a car at estimated_soc=100 — which had
declined six start ladders — jumped to the FULL 20 kWh, and under the
peak cap the phantom displaced the real loads (sim_heizband fits→yields
at exactly 00:01). The morning unplug proved the displacement from the
other side: the moment the phantom left, everything else fit.

The collector already mirrors two execution gates (mode, plug). This is
the third, in the same style: only a DEFINITE "the car is full" skips —
an unknown car is planned (fail-visible, the mode-gate precedent).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
    EVTaperDetector,
)
from custom_components.solar_energy_management.coordinator.ev_availability import (
    plan_car_fullness,
)


def _detector(anchored: bool, since_full: float) -> EVTaperDetector:
    det = EVTaperDetector({"ev_battery_capacity": 52.0})
    det._soc_anchored = anchored
    det._energy_since_full = since_full
    return det


class TestStillFull:
    """One honest, public name for the state the detector already pins
    estimated_soc=100 on — anchored at a completed charge with nothing
    drawn since. The collector must not reach into privates for it."""

    def test_anchored_and_nothing_since_is_still_full(self) -> None:
        assert _detector(True, 0.0).still_full is True

    def test_the_threshold_matches_the_soc_pin(self) -> None:
        # The detector itself treats < 0.1 kWh as "still at 100%".
        assert _detector(True, 0.09).still_full is True
        assert _detector(True, 0.5).still_full is False

    def test_unanchored_is_never_full(self) -> None:
        """A detector with no completed-charge reference has no opinion —
        an empty history must never read as a full car."""
        assert _detector(False, 0.0).still_full is False


class TestPlanCarFullness:
    """Same tri-state contract as plan_connectivity: True = definitely
    full (skip), None = nothing to ask (plan it)."""

    def test_a_still_full_detector_answers_full(self) -> None:
        assert plan_car_fullness(_detector(True, 0.0)) is True

    def test_a_car_that_drew_since_answers_not_full(self) -> None:
        assert plan_car_fullness(_detector(True, 4.0)) is None

    def test_no_detector_is_unknown_not_full(self) -> None:
        assert plan_car_fullness(None) is None

    def test_a_broken_detector_is_unknown(self) -> None:
        class _Boom:
            @property
            def still_full(self):
                raise RuntimeError("no state")
        assert plan_car_fullness(_Boom()) is None


class TestEagerPerChargerRestore:
    """(P3 provocation, 13.08) The per-charger detectors were created and
    restored LAZILY inside the EV cycle block — so the first boot tick
    computed the signature's fullness term from an empty registry and
    restamped a warm restored plan with 'ask changed'. The primary
    detector already restores eagerly in the setup restore block; the
    per-charger fleet now restores beside it."""

    def test_stored_chargers_come_back_warm(self) -> None:
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        c = SEMCoordinator.__new__(SEMCoordinator)
        c.config = {}
        c._ev_taper_detectors = {}
        SEMCoordinator._restore_per_charger_detectors(c, {
            "chargers": {"keba": {
                "soc_anchored": True, "energy_since_full": 0.0,
            }},
        })
        assert "keba" in c._ev_taper_detectors
        assert c._ev_taper_detectors["keba"].still_full is True

    def test_a_warm_detector_is_never_clobbered(self) -> None:
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        c = SEMCoordinator.__new__(SEMCoordinator)
        c.config = {}
        live = _detector(True, 4.0)   # drew 4 kWh this session
        c._ev_taper_detectors = {"keba": live}
        SEMCoordinator._restore_per_charger_detectors(c, {
            "chargers": {"keba": {
                "soc_anchored": True, "energy_since_full": 0.0,
            }},
        })
        assert c._ev_taper_detectors["keba"] is live

    def test_garbage_state_restores_nothing_quietly(self) -> None:
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        c = SEMCoordinator.__new__(SEMCoordinator)
        c.config = {}
        c._ev_taper_detectors = {}
        SEMCoordinator._restore_per_charger_detectors(c, None)
        SEMCoordinator._restore_per_charger_detectors(c, {"chargers": "junk"})
        assert c._ev_taper_detectors == {}


class TestTheSignatureSeesTheCar:
    """Anchoring full happens mid-night with the plug still in — nothing
    else in the signature moves, so without this term the stamped plan
    keeps packing phantom blocks until an unrelated trigger fires."""

    def _coord(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        c = SEMCoordinator.__new__(SEMCoordinator)
        c.config = {"ev_chargers": [
            {"id": "keba", "daily_ev_target": 20.0,
             "ev_target_time": "07:00", "charge_mode": "min_plus_solar"},
        ]}
        c._surplus_controller = SimpleNamespace(get_devices_sorted=lambda: [])
        c._tariff_provider = SimpleNamespace(
            get_tariff_data=lambda: SimpleNamespace(upcoming_prices=[]))
        c._ev_taper_detectors = {"keba": _detector(False, 0.0)}
        return c

    def test_the_car_filling_up_changes_the_signature(self) -> None:
        c = self._coord()
        power = SimpleNamespace(ev_connected=True, ev_connected_per_charger=None)
        before = c._overnight_demand_signature(power)
        c._ev_taper_detectors["keba"] = _detector(True, 0.0)
        assert c._overnight_demand_signature(power) != before
