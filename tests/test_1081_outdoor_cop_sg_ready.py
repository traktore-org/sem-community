"""(#1081) A reporter's pump: SG-Ready relays, no climate entity, an outdoor
sensor at 8.8 C picked in the options. The cost-of-heat sensor must show that
temperature, and a COP curve must be used with it. The plan must say why a
heat pump asked it for nothing."""
from datetime import datetime, timezone
from functools import partial
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.devices.heat_pump_controller import (
    HeatPumpController,
)

OUTDOOR = "sensor.weerstation_temperatuur"


def _hass(temp=8.8, room=None):
    hass = MagicMock()
    now = datetime.now(timezone.utc)

    def _get(eid):
        vals = {OUTDOOR: temp, "sensor.room": room}
        v = vals.get(eid)
        if v is None:
            return None
        return SimpleNamespace(
            entity_id=eid, state=str(v), last_updated=now, last_reported=now,
            attributes={"unit_of_measurement": "°C",
                        "device_class": "temperature"})
    hass.states.get.side_effect = _get
    hass.states.async_all.return_value = []
    hass.config.units.temperature_unit = "°C"
    return hass


def _pump(hass, **kw):
    return HeatPumpController(hass, relay1_entity_id="switch.sg1",
                              relay2_entity_id="switch.sg2",
                              rated_power=2000.0, **kw)


def _coord(hass):
    c = SimpleNamespace(hass=hass, config={"outdoor_temperature_entity": OUTDOOR},
                        _OUTDOOR_TEMP_RESCAN_S=600.0)
    c._outdoor_temperature_or_none = partial(
        SEMCoordinator._outdoor_temperature_or_none, c)
    c._heat_pump_cop_view = partial(SEMCoordinator._heat_pump_cop_view, c)
    return c


def test_no_curve_flat_cop_but_the_outdoor_reading_is_shown():
    c = _coord(_hass())
    cop, source, outdoor = c._heat_pump_cop_view(_pump(c.hass))
    assert (cop, source, outdoor) == (3.0, "flat", 8.8)


def test_with_a_curve_the_cop_follows_the_outdoor_temperature():
    c = _coord(_hass())
    hp = _pump(c.hass)
    hp.cop_curve = [(-7.0, 2.5), (2.0, 3.2), (12.0, 4.2)]
    cop, source, outdoor = c._heat_pump_cop_view(hp)
    assert source == "curve" and outdoor == 8.8
    assert 3.2 < cop < 4.2


def test_no_pump_no_view():
    assert _coord(_hass())._heat_pump_cop_view(None) == (None, None, None)


# ── why the plan holds no ask ────────────────────────────────────────────

def test_blocker_no_band():
    assert "No comfort band" in _pump(_hass()).comfort_plan_blocker()


def _banded(hass, **kw):
    hp = _pump(hass, **kw)
    hp.comfort_entity, hp.comfort_target = "sensor.room", 21.0
    hp.comfort_offset, hp.comfort_limit = 1.0, 18.0
    return hp


def test_blocker_grid_not_allowed_for_a_cool_room():
    hp = _banded(_hass(room=19.5))
    assert hp.top_up_policy == "solar_only"
    assert "Grid power is not allowed" in hp.comfort_plan_blocker()


def test_blocker_warm_room():
    hp = _banded(_hass(room=23.0))
    assert "warm enough" in hp.comfort_plan_blocker()


def test_blocker_none_when_it_asks():
    hp = _banded(_hass(room=19.0))
    hp.top_up_policy = "cheap_hours"
    assert hp.comfort_plan_demand(None, goal=True) is not None
    assert hp.comfort_plan_blocker() is None


def test_coverage_why_names_only_the_uncovered_pump():
    hp = _pump(_hass())
    ctl = SimpleNamespace(get_devices_sorted=lambda: [hp])
    c = SimpleNamespace(_surplus_controller=ctl)
    c._plan_coverage_view = lambda: {"comfort:heat_pump": "not in plan",
                                     "load:heat_pump": "not in plan"}
    why = SEMCoordinator._plan_coverage_why(c)
    assert list(why) == ["comfort:heat_pump"]
    assert "No comfort band" in why["comfort:heat_pump"]
