"""#939 — on a SOC-target charger the plan asks the car whether it is full,
not the taper anchor.

Live (09.09.2026, Tesla reading 71 %, target "at least 80 %" by 06:00): a
false taper anchor made ``still_full`` True. The plan's car-full gate
dropped the car ("no overnight demands"), while the reactive layer — which
charges on ``target − the car's reading`` — saw 5.4 kWh owed and started it
for the deadline. The draw un-fulled the car (the N2 meter rule), the plan
covered it again and stopped it outside the cheap window, the draw ended,
and the anchor said "full" again: 60 s on, 20 s off, every evening.

A SOC-target night need is car-derived either way — the sensor, else the
anchored virtual SOC ``_resolve_charger_soc`` falls back to, which is the
anchor's own answer — so the gate has nothing to add but a disagreement.
It is keyed on the target TYPE, not on whether the sensor reads this cycle:
a gate that changed hands with sensor availability restamps on every blink.
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


def _ev_term(sig):
    terms = [t for t in sig if t and t[0] == "ev"]
    assert terms, "the ev term must be present, or the comparison is vacuous"
    return terms


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
        at_rest = c._energy_plan_demand_signature(_power(0.0))
        drawing = c._energy_plan_demand_signature(_power(1800.0))
        assert _ev_term(at_rest) == _ev_term(drawing)
        assert at_rest == drawing

    def test_the_signature_does_not_move_when_the_sensor_blinks(self) -> None:
        """Review catch: keyed on "reads a number now", the gate changed
        hands on every 71 ↔ unavailable edge and restamped the night."""
        reading = _coord(_soc_charger(), soc_state="71")
        dark = _coord(_soc_charger(), soc_state="unavailable")
        assert (_ev_term(reading._energy_plan_demand_signature(_power(0.0)))
                == _ev_term(dark._energy_plan_demand_signature(_power(0.0))))


class TestADarkSensorStillHearsTheAnchor:
    """The gate defers even with no reading — because the need then IS the
    anchor's answer, and #756's skip arrives through ``kwh <= 0.05``."""

    def test_the_gate_defers_without_a_reading(self) -> None:
        for state in ("unavailable", "unknown", "junk"):
            c = _coord(_soc_charger(), soc_state=state)
            assert SEMCoordinator._plan_car_full(c, "ev_charger", _power(0.0)) is None

    def test_the_need_falls_back_to_the_anchor_and_reads_nothing_owed(self) -> None:
        cfg = _soc_charger()
        c = _coord(cfg, soc_state="unavailable")
        soc = SEMCoordinator._resolve_charger_soc(c, "ev_charger", cfg)
        assert soc == 100.0
        need = SEMCoordinator._calculate_remaining_need(
            c, None, soc, cfg, bound="min")
        assert need <= 0.05


class TestAKwhTargetStillAsksTheAnchor:
    def test_the_calendar_counter_knows_nothing_of_the_car(self) -> None:
        """#756 was built for this need — the anchor keeps its say here."""
        cfg = _soc_charger()
        cfg.pop("ev_target_type")
        c = _coord(cfg)
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
