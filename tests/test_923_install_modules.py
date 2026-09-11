"""#923 — the install-modules oracle: one answer, three states.

SEM is a core plus hardware modules (battery, EV, heat pump, hot water).
Every surface that depends on a module asks ONE function whether the install
has it. The verdict comes from configuration, never live state, and "the
Energy Dashboard could not be read" is UNKNOWN — never ABSENT (#925)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.install_modules import (
    Module,
    Presence,
    has_managed_charger,
    install_modules,
)

ED_EMPTY = SimpleNamespace(has_battery=False, has_ev=False)
ED_BATTERY = SimpleNamespace(has_battery=True, has_ev=False)
ED_EV = SimpleNamespace(has_battery=False, has_ev=True)


class TestBattery:

    def test_a_wired_soc_sensor_is_present_before_the_dashboard_is_read(self):
        v = install_modules({"battery_soc_sensor": "sensor.soc"}, None, False)
        assert v[Module.BATTERY] is Presence.PRESENT

    def test_a_wired_control_entity_is_present(self):
        v = install_modules(
            {"battery_discharge_control_entity": "number.max_discharge"}, ED_EMPTY, True)
        assert v[Module.BATTERY] is Presence.PRESENT

    def test_the_energy_dashboard_alone_makes_it_present(self):
        assert install_modules({}, ED_BATTERY, True)[Module.BATTERY] is Presence.PRESENT

    def test_nothing_wired_and_the_dashboard_read_is_absent(self):
        assert install_modules({}, ED_EMPTY, True)[Module.BATTERY] is Presence.ABSENT

    def test_a_missing_dashboard_file_is_an_answer(self):
        # read_energy_dashboard_config_outcome() returns (None, True) when
        # .storage/energy does not exist: a definite "no dashboard".
        assert install_modules({}, None, True)[Module.BATTERY] is Presence.ABSENT

    def test_an_unread_dashboard_is_unknown_never_absent(self):
        # #925: "I could not ask" is not "no". UNKNOWN keeps every entity.
        assert install_modules({}, None, False)[Module.BATTERY] is Presence.UNKNOWN

    def test_capacity_alone_is_not_evidence(self):
        # The options flow's Settings step saves battery_capacity_kwh with a
        # default for every install that passes through it.
        v = install_modules({"battery_capacity_kwh": 10.0}, ED_EMPTY, True)
        assert v[Module.BATTERY] is Presence.ABSENT

    @pytest.mark.parametrize("value", [None, "", [], {}])
    def test_empty_values_are_not_wiring(self, value):
        v = install_modules({"battery_power_sensor": value}, ED_EMPTY, True)
        assert v[Module.BATTERY] is Presence.ABSENT


class TestEv:

    def test_a_charger_list_is_present(self):
        v = install_modules({"ev_chargers": [{"id": "ev_charger"}]}, ED_EMPTY, True)
        assert v[Module.EV] is Presence.PRESENT

    @pytest.mark.parametrize("key", ["ev_charging_power_sensor", "ev_power_sensor"])
    def test_the_legacy_single_charger_keys_are_present(self, key):
        assert install_modules({key: "sensor.wb"}, ED_EMPTY, True)[Module.EV] is Presence.PRESENT

    def test_an_energy_dashboard_ev_consumer_is_present_without_a_charger(self):
        # sensor_reader.py feeds sem_ev_power from ed.ev_power when no charger
        # is configured — that install HAS EV data.
        assert install_modules({}, ED_EV, True)[Module.EV] is Presence.PRESENT

    def test_nothing_and_the_dashboard_read_is_absent(self):
        assert install_modules({}, ED_EMPTY, True)[Module.EV] is Presence.ABSENT

    def test_an_unread_dashboard_is_unknown(self):
        assert install_modules({}, None, False)[Module.EV] is Presence.UNKNOWN


class TestHeatPump:

    @pytest.mark.parametrize("key", [
        "heat_pump_relay1_entity", "heat_pump_relay2_entity",
        "heat_pump_climate_entity", "heat_pump_sg_ready_service",
        "heat_pump_sg_ready_state_entity", "heat_pump_power_sensor",
        "heat_pump_energy_sensor",
    ])
    def test_any_wiring_key_is_present(self, key):
        assert install_modules({key: "x.y"}, ED_EMPTY, True)[Module.HEAT_PUMP] is Presence.PRESENT

    def test_an_additional_unit_list_is_present(self):
        v = install_modules({"heat_pumps": [{"id": "hp2"}]}, ED_EMPTY, True)
        assert v[Module.HEAT_PUMP] is Presence.PRESENT

    def test_tunables_alone_are_not_evidence(self):
        cfg = {"heat_pump_boost_offset": 2.0, "heat_pump_rated_power": 3000,
               "heat_pump_priority": 5}
        assert install_modules(cfg, ED_EMPTY, True)[Module.HEAT_PUMP] is Presence.ABSENT

    def test_config_only_so_never_unknown(self):
        assert install_modules({}, None, False)[Module.HEAT_PUMP] is Presence.ABSENT


class TestHotWater:

    def test_the_tank_entity_is_present(self):
        v = install_modules({"hot_water_entity": "water_heater.tank"}, ED_EMPTY, True)
        assert v[Module.HOT_WATER] is Presence.PRESENT

    def test_settings_alone_are_not_evidence(self):
        v = install_modules({"hot_water_max_temperature": 60}, None, False)
        assert v[Module.HOT_WATER] is Presence.ABSENT


class TestManagedCharger:
    """The #595 EV-TAB rule — not the same question as the EV module."""

    def test_no_charger(self):
        assert has_managed_charger({}) is False

    def test_charger_list(self):
        assert has_managed_charger({"ev_chargers": [{"id": "a"}]}) is True

    def test_legacy_power_sensor(self):
        assert has_managed_charger({"ev_charging_power_sensor": "sensor.wb"}) is True

    def test_dashboard_ev_alone_is_data_not_a_managed_charger(self):
        assert install_modules({}, ED_EV, True)[Module.EV] is Presence.PRESENT
        assert has_managed_charger({}) is False
