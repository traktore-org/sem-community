"""arc #921 — the surface: four switches default OFF and persisted, four numbers, the state sensor.

20.08: every setting reachable on the SEM dashboard — the options flow
alone is never enough. And every switch ships OFF (gate 4: complete and
inert), which the persisted-flag table must say too, or the coordinator
resolves it differently at setup than the switch does at runtime.
"""
from pathlib import Path

from custom_components.solar_energy_management import number as number_mod
from custom_components.solar_energy_management import sensor as sensor_mod
from custom_components.solar_energy_management import switch as switch_mod
from custom_components.solar_energy_management.persisted_flags import PERSISTED_FLAG_DEFAULTS

SWITCHES = ("export_guard_enabled", "export_guard_override_external",
            "battery_house_sink_enabled", "ev_morning_window_enabled")
NUMBERS = ("export_guard_engage_s", "export_guard_release_s",
           "ev_morning_window_hours", "battery_morning_drain_floor_soc")


class TestSwitches:
    def test_all_four_exist(self):
        keys = {d.key for d in switch_mod.SWITCH_TYPES}
        assert set(SWITCHES) <= keys

    def test_all_four_are_persisted_and_default_off(self):
        for k in SWITCHES:
            assert PERSISTED_FLAG_DEFAULTS[k] is False, k

    def test_all_four_are_config_category(self):
        for d in switch_mod.SWITCH_TYPES:
            if d.key in SWITCHES:
                assert d.entity_category is not None and d.entity_category.value == "config", d.key


class TestNumbers:
    def test_all_four_exist_with_sane_bounds(self):
        by_key = {d.key: d for d in number_mod.NUMBER_TYPES}
        for k in NUMBERS:
            assert k in by_key, k
        assert by_key["ev_morning_window_hours"].native_min_value == 0.5
        assert by_key["battery_morning_drain_floor_soc"].native_max_value == 90
        assert by_key["export_guard_engage_s"].native_min_value >= 30
        assert by_key["export_guard_release_s"].native_min_value >= 60

    def test_the_defaults_match_what_the_code_falls_back_to(self):
        """The coordinator's ``config.get(key, default)`` fallbacks and the
        number entities' defaults must be the same numbers, or a fresh install
        and a reconfigured one behave differently."""
        from custom_components.solar_energy_management.consts.core import (
            DEFAULT_EXPORT_GUARD_ENGAGE_S, DEFAULT_EXPORT_GUARD_RELEASE_S,
            DEFAULT_EV_MORNING_WINDOW_HOURS, DEFAULT_BATTERY_MORNING_DRAIN_FLOOR_SOC,
        )
        assert (DEFAULT_EXPORT_GUARD_ENGAGE_S, DEFAULT_EXPORT_GUARD_RELEASE_S,
                DEFAULT_EV_MORNING_WINDOW_HOURS, DEFAULT_BATTERY_MORNING_DRAIN_FLOOR_SOC) == (120, 300, 2.0, 50)


class TestSensor:
    def test_the_guard_state_is_a_diagnostic_sensor(self):
        d = next(d for d in sensor_mod.SENSOR_TYPES if d.key == "export_guard_state")
        assert d.entity_category is not None and d.entity_category.value == "diagnostic"


class TestTheDashboardCarriesThem:
    """Every setting in the GUI (20.08): the System screen renders the
    toggles and numbers (#1321). Checked against the parsed entity ids, not
    free text (#925)."""
    ROOT = Path(__file__).resolve().parent.parent

    @staticmethod
    def _registered(card: str) -> set:
        import re
        from ._dashboard_src import dashboard_src
        text = dashboard_src()
        return set(re.findall(r"'((?:switch|number|sensor|select)\.sem_[a-z0-9_]+)'", text))

    def test_every_new_entity_is_on_the_dashboard(self):
        registered = self._registered("dashboard")
        for k in SWITCHES:
            assert f"switch.sem_{k}" in registered, k
        for k in NUMBERS:
            assert f"number.sem_{k}" in registered, k


class TestTheVerdictsReachTheCard:
    """Live on .46: the coordinator published them and the CARD saw nothing —
    charging_state's attributes are a curated dict, not all of ``data``."""

    def _attrs(self, data):
        from unittest.mock import MagicMock
        from custom_components.solar_energy_management.sensor import SEMSolarSensor
        s = SEMSolarSensor.__new__(SEMSolarSensor)
        s.coordinator = MagicMock(); s.coordinator.data = data
        s.entity_description = next(
            d for d in sensor_mod.SENSOR_TYPES if d.key == "charging_state")
        return s.extra_state_attributes or {}

    def test_charging_state_carries_the_verdicts_and_the_guard(self):
        a = self._attrs({"charging_state": "idle",
                         "sink_verdicts": {"grid_export": {"state": "closed", "reason": "r", "until": None}},
                         "export_guard": {"state": "engaged", "reason": "r"}})
        assert a["sink_verdicts"]["grid_export"]["state"] == "closed"
        assert a["export_guard"]["state"] == "engaged"

    def test_absent_is_an_empty_dict_not_a_crash(self):
        a = self._attrs({"charging_state": "idle"})
        assert a["sink_verdicts"] == {} and a["export_guard"] == {}

    def test_both_are_unrecorded(self):
        """#581: live-card helpers must not dominate the recorder."""
        from custom_components.solar_energy_management.sensor import SEMSolarSensor
        assert {"sink_verdicts", "export_guard"} <= SEMSolarSensor._unrecorded_attributes
