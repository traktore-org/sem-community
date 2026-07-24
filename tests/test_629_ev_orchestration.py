"""#629 — EV orchestration decomposition slices (behaviour pins)."""
from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.ev_night_targets import (
    build_night_target_map,
)


def _coord(chargers=None, config=None, fallback_logged=None,
           soc_need=5.5, daily_kwh=2.0):
    c = MagicMock()
    c.config = config or {}
    c._ev_devices = chargers or {}
    c._night_global_fallback_logged = (
        set() if fallback_logged is None else fallback_logged)
    c._resolve_charger_soc = MagicMock(return_value=80.0)
    c._calculate_remaining_need = MagicMock(return_value=soc_need)
    c._charger_daily_kwh = MagicMock(return_value=daily_kwh)
    return c


class TestNightTargetMap629:
    def test_kwh_mode_per_charger_target_minus_delivered(self):
        c = _coord(chargers={"a": object()},
                   config={"ev_chargers": [{"id": "a", "daily_ev_target": 8}]},
                   daily_kwh=3.0)
        assert build_night_target_map(c, MagicMock()) == {"a": 5.0}

    def test_kwh_mode_clamps_at_zero(self):
        c = _coord(chargers={"a": object()},
                   config={"ev_chargers": [{"id": "a", "daily_ev_target": 2}]},
                   daily_kwh=9.0)
        assert build_night_target_map(c, MagicMock()) == {"a": 0}

    def test_global_inheritance_logged_once(self):
        logged = set()
        c = _coord(chargers={"a": object()},
                   config={"ev_chargers": [{"id": "a"}], "daily_ev_target": 12},
                   fallback_logged=logged, daily_kwh=2.0)
        out = build_night_target_map(c, MagicMock())
        assert out == {"a": 10.0}
        assert logged == {"a"}                    # #259 surfaced once
        build_night_target_map(c, MagicMock())    # second cycle: no re-log
        assert logged == {"a"}

    def test_soc_mode_delegates_to_remaining_need(self):
        c = _coord(chargers={"a": object()},
                   config={"ev_chargers": [{"id": "a", "ev_target_type": "soc"}]},
                   soc_need=6.25)
        out = build_night_target_map(c, MagicMock())
        assert out == {"a": 6.25}
        c._calculate_remaining_need.assert_called_once()
        _, kwargs = c._calculate_remaining_need.call_args
        assert kwargs.get("bound") == "min"       # the #245 floor, not max

    def test_unconfigured_charger_uses_global_default(self):
        c = _coord(chargers={"x": object()}, config={}, daily_kwh=0.0)
        assert build_night_target_map(c, MagicMock()) == {"x": 10}   # default 10


class TestNightNotificationTruth631:
    """(#631) The night-start notification must quote the SAME remaining the
    decision consumed (the per-charger map), not the stale config snapshot."""

    def _messages(self, data, config=None):
        from custom_components.solar_energy_management.coordinator.notifications import (
            NotificationManager)
        nm = NotificationManager.__new__(NotificationManager)
        nm.config = config or {"daily_ev_target": 8}
        nm.hass = MagicMock()
        return NotificationManager._get_notification_messages(
            nm, "night_charging_active", data)

    def test_prefers_per_charger_map_value(self):
        m = self._messages({"daily_ev_energy": 0.0, "_charger_id": "ev_charger",
                            "night_remaining_map": {"ev_charger": 2.0}})
        assert "2.0" in m["mobile"]           # live map, not the config 8

    def test_fleet_fallback_sums_map(self):
        m = self._messages({"daily_ev_energy": 0.0, "_charger_id": None,
                            "night_remaining_map": {"a": 1.5, "b": 2.5}})
        assert "4.0" in m["mobile"]

    def test_no_map_falls_back_to_config(self):
        m = self._messages({"daily_ev_energy": 3.0, "_charger_id": None,
                            "night_remaining_map": {}})
        assert "5.0" in m["mobile"]           # 8 - 3 legacy path


class TestSolarBudgetDistribution629:
    """(#629 slice 2) The extracted canonical-budget distribution."""

    def _coord(self, net_w=3000.0, chargers_cfg=None, modes=None):
        from custom_components.solar_energy_management.coordinator.ev_night_targets import (
            distribute_solar_budget)
        c = MagicMock()
        c._cycle_ev_budget = MagicMock(net_w=net_w)
        c.config = {"ev_chargers": chargers_cfg or []}
        modes = modes or {}
        c._effective_charge_mode_for = lambda cfg: modes.get(cfg.get("id"), "solar_only")
        c._ev_devices = {"a": MagicMock(), "b": MagicMock()}
        c._surplus_controller.distribute_ev_budget = MagicMock(return_value={"a": 2000, "b": 1000})
        return c, distribute_solar_budget

    def test_uses_canonical_net_and_delegates(self):
        c, f = self._coord(net_w=3000.0)
        out = f(c)
        assert out == {"a": 2000, "b": 1000}
        args, kwargs = c._surplus_controller.distribute_ev_budget.call_args
        assert args[0] == 3000.0                       # the ONE canonical total
        assert kwargs["excluded_charger_ids"] == set()

    def test_off_mode_chargers_excluded(self):
        c, f = self._coord(chargers_cfg=[{"id": "a"}, {"id": "b"}],
                           modes={"b": "off"})
        f(c)
        _, kwargs = c._surplus_controller.distribute_ev_budget.call_args
        assert kwargs["excluded_charger_ids"] == {"b"}     # #351 M5

    def test_missing_budget_fails_safe_to_zero(self):
        c, f = self._coord()
        c._cycle_ev_budget = None
        f(c)
        args, _ = c._surplus_controller.distribute_ev_budget.call_args
        assert args[0] == 0.0                          # fail-safe, never legacy base
