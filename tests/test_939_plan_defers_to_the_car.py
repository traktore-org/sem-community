"""#939 — a SOC-target charger whose car reports its SOC: the plan asks the
car whether it is full, not the taper anchor.

Live (09.09.2026, Tesla reading 71 %, target "at least 80 %" by 06:00): a
false taper anchor made ``still_full`` True. The plan's car-full gate
dropped the car ("no overnight demands"), while the reactive layer — which
charges on ``target − the car's reading`` — saw 5.4 kWh owed and started it
for the deadline. The draw un-fulled the car (the N2 meter rule), the plan
covered it again and stopped it outside the cheap window, the draw ended,
and the anchor said "full" again: 60 s on, 20 s off, every evening.

The SOC-target night need already IS the car's answer
(``build_night_target_map`` → ``_calculate_remaining_need``); a car at its
target is skipped there. So for such a charger the anchor has nothing to
add — and nothing to disagree with.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
    EVTaperDetector,
)

from .test_638_shadow_mode import (  # noqa: F401 — fixtures come along
    _fake_self, _scheduler, freeze_targets,
)

SOC_ENTITY = "sensor.tesla_battery"


def _falsely_full_detector() -> EVTaperDetector:
    """What the 20:45:32 anchor left behind: anchored, nothing missing."""
    det = EVTaperDetector({"ev_battery_capacity_kwh": 60.0})
    det._soc_anchored = True
    det._energy_since_full = 0.0
    assert det.still_full is True
    return det


def _hass(state):
    return SimpleNamespace(states=SimpleNamespace(
        get=lambda eid: SimpleNamespace(state=state) if eid == SOC_ENTITY else None))


def _soc_charger(**extra) -> dict:
    cfg = {"id": "ev_charger", "ev_target_type": "soc", "ev_target_soc": 80,
           "vehicle_soc_entity": SOC_ENTITY, "ev_target_time": "06:00",
           "charge_mode": "solar_plus_cheap"}
    cfg.update(extra)
    return cfg


def _coord(cfg, soc_state="71"):
    c = SEMCoordinator.__new__(SEMCoordinator)
    c.config = {"ev_chargers": [cfg]}
    c.hass = _hass(soc_state)
    c._ev_taper_detectors = {"ev_charger": _falsely_full_detector()}
    c._charger_adapters = {}
    c._surplus_controller = SimpleNamespace(get_devices_sorted=lambda: [])
    c._tariff_provider = SimpleNamespace(
        get_tariff_data=lambda: SimpleNamespace(upcoming_prices=[]))
    return c


def _power(w):
    return SimpleNamespace(ev_connected=True, ev_connected_per_charger=None,
                           ev_power_per_charger={"ev_charger": w})


class TestTheCarAnswersForItself:
    def test_at_rest_the_anchor_does_not_skip_the_car(self) -> None:
        c = _coord(_soc_charger())
        assert SEMCoordinator._plan_car_full(c, "ev_charger", _power(0.0)) is None

    def test_drawing_it_is_the_same_answer(self) -> None:
        c = _coord(_soc_charger())
        assert SEMCoordinator._plan_car_full(c, "ev_charger", _power(1800.0)) is None

    def test_the_signature_no_longer_moves_with_the_draw(self) -> None:
        """The restamp trigger of the cycling: the car-full term read True
        with the charger off and False with it on, so each of SEM's own
        stops and starts re-planned the night."""
        c = _coord(_soc_charger())
        assert (c._energy_plan_demand_signature(_power(0.0))
                == c._energy_plan_demand_signature(_power(1800.0)))


class TestTheAnchorStillAnswersWhereTheNeedIsBlind:
    def test_a_dark_sensor_hands_the_question_back(self) -> None:
        """No reading → ``_resolve_charger_soc`` falls back to the anchored
        virtual SOC, so the need and the anchor agree again; #756 stands."""
        c = _coord(_soc_charger(), soc_state="unavailable")
        assert SEMCoordinator._plan_car_full(c, "ev_charger", _power(0.0)) is True

    def test_a_kwh_target_still_asks_the_anchor(self) -> None:
        """The calendar counter #756 was built for knows nothing of the car."""
        cfg = _soc_charger()
        cfg.pop("ev_target_type")
        c = _coord(cfg)
        assert SEMCoordinator._plan_car_full(c, "ev_charger", _power(0.0)) is True

    def test_a_non_numeric_reading_is_not_a_reading(self) -> None:
        c = _coord(_soc_charger(), soc_state="junk")
        assert SEMCoordinator._plan_car_full(c, "ev_charger", _power(0.0)) is True


class TestTheCollectorPlansTheCar:
    def test_the_night_keeps_the_car_its_own_sensor_says_is_short(
            self, freeze_targets) -> None:
        fake = _fake_self(devices=[])
        fake.config["ev_chargers"][0].update(
            {"ev_target_type": "soc", "vehicle_soc_entity": SOC_ENTITY})
        fake.hass = _hass("71")
        fake._ev_taper_detectors = {"ev_charger": _falsely_full_detector()}
        power = SimpleNamespace(battery_soc=80.0,
                                ev_power_per_charger={"ev_charger": 0.0})
        SEMCoordinator._shadow_energy_plan(
            fake, _scheduler(), energy=MagicMock(), power=power)
        plan = fake._energy_plan_shadow
        assert "ev:ev_charger" in {d["id"] for d in plan["demands"]}
        assert not any(n.get("why") == "car_full"
                       for n in plan.get("not_scheduled") or [])
