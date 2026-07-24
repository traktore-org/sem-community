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


class TestNightTopUpRate630:
    """(#630) The plain night top-up runs at the peak-managed headroom rate,
    bounded [min, max]; without peak info it keeps the legacy Min creep."""

    def _plan(self, **kw):
        from datetime import datetime
        from custom_components.solar_energy_management.coordinator.ev_tariff_planner import (
            plan_night_charge)
        args = dict(now=datetime(2026, 7, 24, 1, 0),
                    remaining_to_min_kwh=8.0, min_amps=10, max_amps=32,
                    watts_per_amp=690.0, night_end="06:00")
        args.update(kw)
        return plan_night_charge(**args)

    def test_top_up_uses_peak_managed_rate(self):
        p = self._plan(peak_managed_amps=16)
        assert p.top_up_amps == 16

    def test_top_up_clamped_to_charger_limits(self):
        assert self._plan(peak_managed_amps=64).top_up_amps == 32
        assert self._plan(peak_managed_amps=4).top_up_amps == 10

    def test_no_peak_info_keeps_legacy_floor(self):
        p = self._plan(peak_managed_amps=None)
        assert p.top_up_amps == 0                 # decide falls back to Min

    def test_decide_plain_topup_uses_rate(self):
        from custom_components.solar_energy_management.coordinator.decide import decide
        from custom_components.solar_energy_management.coordinator.charger_types import (
            ChargerView, ChargerPower, ChargerEnergy, FleetContext)
        view = ChargerView(
            power=ChargerPower(charger_id="c1", power_w=0.0, connected=True),
            energy=ChargerEnergy(charger_id="c1"),
            mode="min_plus_solar",
            config={"ev_min_current": 10, "ev_phases": 3, "ev_max_current": 32},
            fleet=FleetContext(solar_w=0.0, home_w=500.0, battery_soc=60.0,
                               is_night=True),
            target_kwh=8.0,
            top_up_amps=16,
        )
        d = decide(view)
        assert d.commanded_amps == 16
        assert "peak-managed" in d.reason

    def test_decide_no_topup_info_keeps_min(self):
        from custom_components.solar_energy_management.coordinator.decide import decide
        from custom_components.solar_energy_management.coordinator.charger_types import (
            ChargerView, ChargerPower, ChargerEnergy, FleetContext)
        view = ChargerView(
            power=ChargerPower(charger_id="c1", power_w=0.0, connected=True),
            energy=ChargerEnergy(charger_id="c1"),
            mode="min_plus_solar",
            config={"ev_min_current": 10, "ev_phases": 3, "ev_max_current": 32},
            fleet=FleetContext(solar_w=0.0, home_w=500.0, battery_soc=60.0,
                               is_night=True),
            target_kwh=8.0,
        )
        d = decide(view)
        assert d.commanded_amps == 10          # legacy Min creep preserved
