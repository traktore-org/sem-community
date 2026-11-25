"""#1199 — an idle plugged-in car does not hold the house battery.

PROD 24.–25.10: the car stayed plugged in overnight, charging had stopped
and night charging was off, yet SEM capped the battery's discharge at the
house load all night (a write every few minutes). The cap now holds only
while a car draws, or drew in the last 15 minutes (a car that pulses on and
off still drained the pack between bursts on 24.06).
"""
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator import coordinator as coord_mod
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
    BatteryRuntime,
    BatteryView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    decide_battery,
)


def _view(*, charging, connected=True, drew_recently=True, assist_ok=None):
    return BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=40.0),
        config={"battery_max_discharge_power": 5000,
                "battery_max_charge_power_w": 5000,
                "battery_mode": "auto",
                "battery_discharge_protection_enabled": True},
        fleet=FleetContext(solar_w=0.0, home_w=700.0, battery_soc=40.0,
                           battery_soc_known=True, buffer_soc=70.0,
                           battery_assist_min_surplus_w=1200.0),
        charging_state="idle",
        ev_charging=charging,
        ev_connected=connected,
        ev_drew_recently=drew_recently,
        home_consumption_w=700.0,
        ev_help_allowed=(assist_ok is not False),   # (#1381) the chargers' answer
    )


@pytest.mark.unit
class TestTheCapFollowsACarThatMayDraw:
    def test_an_idle_car_leaves_the_battery_alone(self):
        d = decide_battery(_view(charging=False, drew_recently=False))
        assert d.intent is not BatteryIntent.LIMIT_DISCHARGE, d.reason

    def test_a_car_that_drew_minutes_ago_is_still_covered(self):
        d = decide_battery(_view(charging=False, drew_recently=True))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE, d.reason

    def test_a_drawing_car_is_covered(self):
        d = decide_battery(_view(charging=True, drew_recently=False))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE, d.reason

    def test_a_battery_that_may_not_feed_the_car_holds_for_an_idle_car(self):
        """The #1066 setting is a plain no: it does not wait for a draw."""
        d = decide_battery(_view(charging=False, drew_recently=False, assist_ok=False))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE, d.reason

    def test_no_car_no_cap(self):
        d = decide_battery(_view(charging=False, connected=False, drew_recently=True))
        assert d.intent is not BatteryIntent.LIMIT_DISCHARGE, d.reason


@pytest.mark.unit
class TestTheDrawWindow:
    def _coord(self, devices=None):
        return SimpleNamespace(_ev_devices=devices or {})

    @staticmethod
    def _p(charging=False, draw=0.0):
        return SimpleNamespace(ev_charging=charging,
                               ev_power=SimpleNamespace(as_fleet_total=lambda _r: draw))

    def test_window_holds_then_releases(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(coord_mod, "_ev_draw_clock", lambda: now[0])
        c = self._coord()
        f = coord_mod.SEMCoordinator._ev_drew_recently
        assert f(c, self._p(charging=True))
        now[0] += coord_mod.EV_CLAMP_HOLD_S - 1
        assert f(c, self._p()), "inside the window"
        now[0] += 2
        assert not f(c, self._p()), "idle past the window"
        assert f(c, self._p(charging=True)), "a new draw opens it again"

    def test_a_restart_counts_as_a_draw(self, monkeypatch):
        now = [5.0]
        monkeypatch.setattr(coord_mod, "_ev_draw_clock", lambda: now[0])
        c = self._coord()
        f = coord_mod.SEMCoordinator._ev_drew_recently
        assert f(c, self._p()), "unknown history holds the cap first"
        now[0] += coord_mod.EV_CLAMP_HOLD_S + 1
        assert not f(c, self._p())

    def test_a_small_draw_keeps_the_cap(self, monkeypatch):
        now = [0.0]
        monkeypatch.setattr(coord_mod, "_ev_draw_clock", lambda: now[0])
        c = self._coord(); f = coord_mod.SEMCoordinator._ev_drew_recently
        f(c, self._p())
        now[0] += coord_mod.EV_CLAMP_HOLD_S + 1
        assert f(c, self._p(draw=300.0)), "300 W is a car drawing, below the 500 W flag"

    def test_a_started_session_rearms_before_any_draw(self, monkeypatch):
        now = [0.0]
        monkeypatch.setattr(coord_mod, "_ev_draw_clock", lambda: now[0])
        dev = SimpleNamespace(_session_active=False)
        c = self._coord({"ev": dev}); f = coord_mod.SEMCoordinator._ev_drew_recently
        f(c, self._p())
        now[0] += coord_mod.EV_CLAMP_HOLD_S + 1
        assert not f(c, self._p())
        dev._session_active = True
        assert f(c, self._p()), "SEM started a session: cover the car at once"
