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
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
    EVTaperDetector,
)
from custom_components.solar_energy_management.coordinator.ev_availability import (
    plan_car_fullness,
)

from .test_638_shadow_mode import (  # noqa: F401 — fixtures come along
    _fake_self, _scheduler, freeze_targets,
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


class TestTheMeterOutranksTheAnchor:
    """(N2, .175 15.08) A car that is DRAWING is not a full car.

    ``still_full`` is anchored energy accounting: the deficit below full,
    which charging SUBTRACTS from and which clamps at 0. So the moment a
    real charge delivers the last of the deficit, the detector reads
    "anchored, nothing missing" — still_full — while the meter shows
    3.9 kW going into the pack. The #774 overdraw refutation only
    un-anchors 0.1 kWh later; at 3.9 kW that is a ~90 s window in which
    the plan was told the car was full and restamped the night around a
    demand that had just left it.

    The detector cannot close this itself: it sees energy increments, not
    duration, and a genuine trickle is numerically the same rate. Power
    is known one layer up — at the single fullness accessor — so that is
    where the meter gets its say. The handshake threshold is the one the
    adapters already use for "actually charging" (#739), so a real
    <500 W trickle still reads full and #756's contract is untouched.
    """

    def test_a_car_drawing_kilowatts_is_not_full(self) -> None:
        assert plan_car_fullness(_detector(True, 0.0), drawing_w=3900.0) is None

    def test_a_trickle_below_the_handshake_still_reads_full(self) -> None:
        assert plan_car_fullness(_detector(True, 0.0), drawing_w=120.0) is True

    def test_no_meter_reading_leaves_the_anchor_alone(self) -> None:
        assert plan_car_fullness(_detector(True, 0.0), drawing_w=None) is True

    def test_a_settled_cable_is_not_a_contradiction(self) -> None:
        assert plan_car_fullness(_detector(True, 0.0), drawing_w=0.0) is True

    def test_the_threshold_is_the_adapters_own(self) -> None:
        """A charger whose adapter declares a lower handshake gets that
        one — the accessor must not hardcode the generic 500 W."""
        assert plan_car_fullness(
            _detector(True, 0.0), drawing_w=200.0, handshake_w=110.0) is None

    def test_an_unreadable_meter_is_not_an_argument(self) -> None:
        """Only a NUMBER may contradict the anchor. Junk on the wire must
        not silently un-full a car (that would re-open #756 by accident)."""
        assert plan_car_fullness(_detector(True, 0.0), drawing_w="junk") is True

    def test_a_drawing_car_that_was_never_full_is_still_unknown(self) -> None:
        assert plan_car_fullness(_detector(False, 0.0), drawing_w=3900.0) is None


class TestTheOneFullnessAccessor:
    """One coordinator accessor, the ``_plan_ev_connected`` precedent: the
    demand collector and the demand signature must not be able to answer
    "is this car full?" differently."""

    def _coord(self, still_full: bool):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        c = SEMCoordinator.__new__(SEMCoordinator)
        c._ev_taper_detectors = {"keba": _detector(still_full, 0.0)}
        c._charger_adapters = {}
        return c

    def _power(self, w):
        return SimpleNamespace(ev_power_per_charger={"keba": w})

    def test_an_anchored_car_at_rest_is_full(self) -> None:
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        c = self._coord(True)
        assert SEMCoordinator._plan_car_full(c, "keba", self._power(0.0)) is True

    def test_an_anchored_car_that_is_drawing_is_not(self) -> None:
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        c = self._coord(True)
        assert SEMCoordinator._plan_car_full(c, "keba", self._power(3900.0)) is None

    def test_the_charger_s_own_adapter_sets_the_threshold(self) -> None:
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        c = self._coord(True)
        c._charger_adapters = {"keba": SimpleNamespace(handshake_power_w=110.0)}
        assert SEMCoordinator._plan_car_full(c, "keba", self._power(200.0)) is None

    def test_no_power_reading_at_all_is_survivable(self) -> None:
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        c = self._coord(True)
        assert SEMCoordinator._plan_car_full(c, "keba", None) is True


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
        before = c._energy_plan_demand_signature(power)
        c._ev_taper_detectors["keba"] = _detector(True, 0.0)
        assert c._energy_plan_demand_signature(power) != before

    def test_the_signature_believes_the_meter_over_the_anchor(self) -> None:
        """The restamp N2 caught came through THIS term: the deficit
        clamped to 0 mid-charge, the anchor read full, and the signature
        moved while the car was drawing 3.9 kW."""
        c = self._coord()
        c._ev_taper_detectors["keba"] = _detector(True, 0.0)
        at_rest = SimpleNamespace(ev_connected=True, ev_connected_per_charger=None,
                                  ev_power_per_charger={"keba": 0.0})
        drawing = SimpleNamespace(ev_connected=True, ev_connected_per_charger=None,
                                  ev_power_per_charger={"keba": 3900.0})
        assert (c._energy_plan_demand_signature(drawing)
                != c._energy_plan_demand_signature(at_rest))


class TestTheCollectorAsksTheSameQuestion:
    """The collector is the other half of the pair: the signature decides
    WHETHER to restamp, the collector decides what the restamped night
    contains. Both must read the meter, or the night flips between a plan
    with the car and a plan without it."""

    def test_a_drawing_car_still_gets_a_demand(self, freeze_targets) -> None:
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        fake = _fake_self(devices=[])
        fake._ev_taper_detectors = {"ev_charger": _detector(True, 0.0)}
        power = SimpleNamespace(battery_soc=80.0,
                                ev_power_per_charger={"ev_charger": 3900.0})
        SEMCoordinator._shadow_energy_plan(
            fake, _scheduler(), energy=MagicMock(), power=power)
        ids = {d["id"] for d in fake._energy_plan_shadow["demands"]}
        assert "ev:ev_charger" in ids

    def test_a_car_at_rest_is_still_skipped(self, freeze_targets) -> None:
        """#756 itself: the anchored, idle car is a phantom and must stay
        out of the pack."""
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        fake = _fake_self(devices=[])
        fake._ev_taper_detectors = {"ev_charger": _detector(True, 0.0)}
        power = SimpleNamespace(battery_soc=80.0,
                                ev_power_per_charger={"ev_charger": 0.0})
        SEMCoordinator._shadow_energy_plan(
            fake, _scheduler(), energy=MagicMock(), power=power)
        plan = fake._energy_plan_shadow
        ids = {d["id"] for d in plan["demands"]}
        assert "ev:ev_charger" not in ids
        assert any(n.get("id") == "ev:ev_charger" and n.get("why") == "car_full"
                   for n in plan.get("not_scheduled") or [])
