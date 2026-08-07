"""#705 Thermal Comfort Loads — Phase 1: the comfort band on ClimateDevice.

The design lifts the proven HotWaterController pattern (min/solar-target/max
temperature, sensor decides done-ness) out of its one hardcoded device and
into the per-device goal model, mirrored for cooling:

- ``comfort_limit``  — past it, run NOW (the comfort floor; hot water's
  ``min_temperature`` analogue)
- ``comfort_target`` ± ``comfort_offset`` — surplus banks thermal mass past
  the target (hot water's ``solar_target_temp`` / the SG-Ready boost_offset)
- ``comfort_entity`` — the sensor; defaults to the climate entity's own
  ``current_temperature`` so most ACs need zero extra config

The band is expressed ENTIRELY through the generic device properties the
surplus controller already reads — ``stop_condition_met`` (banked ⇒ decline),
``has_runtime_deficit`` (forced ⇒ the deficit-driven paid passes engage per
the user's #620 source axis), ``daily_targets_met`` (a met runtime floor must
not stand the paid sources down while comfort is breached). No new controller
clauses; peak shed, anti-cycling, priority and LIFO all apply unchanged.

Fail-open: no sensor reading ⇒ DISENGAGED ⇒ byte-for-byte today's
ClimateDevice behaviour. An unavailable thermometer must never force a run
NOR park the device.
"""
import pytest
from unittest.mock import MagicMock

from custom_components.solar_energy_management.devices.base import (
    ClimateDevice,
    surplus_device_from_spec,
)


def _hass_with(states: dict):
    hass = MagicMock()
    def _get(eid):
        v = states.get(eid)
        if v is None:
            return None
        st = MagicMock()
        if isinstance(v, tuple):
            st.state, st.attributes = v
        else:
            st.state, st.attributes = v, {}
        return st
    hass.states.get.side_effect = _get
    return hass


def _ac(hass=None, *, hvac_mode="cool", target=24.0, offset=2.0, limit=26.0,
        comfort_entity="sensor.room_temp", **kw) -> ClimateDevice:
    return ClimateDevice(
        hass or _hass_with({}),
        "ac_livingroom", "AC Living Room", rated_power=1200,
        entity_id="climate.ac_livingroom",
        hvac_mode=hvac_mode,
        comfort_entity=comfort_entity,
        comfort_target=target,
        comfort_offset=offset,
        comfort_limit=limit,
        **kw,
    )


class TestTheBandCooling:
    """cool: force ABOVE the limit, bank DOWN to target − offset."""

    def test_past_the_limit_is_forced(self):
        dev = _ac(_hass_with({"sensor.room_temp": "26.4"}))
        assert dev.comfort_state == "forced"

    def test_inside_the_band_is_willing(self):
        dev = _ac(_hass_with({"sensor.room_temp": "24.5"}))
        assert dev.comfort_state == "willing"

    def test_pre_cooled_past_the_offset_is_banked(self):
        # target 24, offset 2 → banked at ≤ 22
        dev = _ac(_hass_with({"sensor.room_temp": "21.8"}))
        assert dev.comfort_state == "banked"

    def test_exactly_at_the_limit_is_forced(self):
        """The limit is a floor being crossed, not a strict inequality —
        matches hot water's ``temp < min_temperature`` force at the boundary."""
        dev = _ac(_hass_with({"sensor.room_temp": "26.0"}))
        assert dev.comfort_state == "forced"


class TestTheBandHeating:
    """heat: mirrored — force BELOW the limit, bank UP to target + offset."""

    def test_below_the_limit_is_forced(self):
        dev = _ac(_hass_with({"sensor.room_temp": "17.5"}),
                  hvac_mode="heat", target=21.0, offset=2.0, limit=18.0)
        assert dev.comfort_state == "forced"

    def test_banked_above_target_plus_offset(self):
        dev = _ac(_hass_with({"sensor.room_temp": "23.2"}),
                  hvac_mode="heat", target=21.0, offset=2.0, limit=18.0)
        assert dev.comfort_state == "banked"

    def test_between_is_willing(self):
        dev = _ac(_hass_with({"sensor.room_temp": "20.0"}),
                  hvac_mode="heat", target=21.0, offset=2.0, limit=18.0)
        assert dev.comfort_state == "willing"


class TestFailOpen:
    """A silent thermometer is not a hot room — and not a cold one either."""

    def test_unavailable_sensor_disengages(self):
        dev = _ac(_hass_with({"sensor.room_temp": "unavailable"}))
        assert dev.comfort_state == "disengaged"

    def test_missing_sensor_disengages(self):
        dev = _ac(_hass_with({}))
        assert dev.comfort_state == "disengaged"

    def test_no_comfort_config_disengages(self):
        dev = _ac(_hass_with({"sensor.room_temp": "30.0"}),
                  target=0.0, limit=0.0)
        assert dev.comfort_state == "disengaged"

    def test_disengaged_is_byte_for_byte_legacy(self):
        """No deficit, no stop, no target-met change — the pre-#705 device."""
        dev = _ac(_hass_with({}))
        assert dev.has_runtime_deficit is False
        assert dev.stop_condition_met is False
        assert dev.daily_targets_met is False

    def test_falls_back_to_the_climate_entitys_own_thermometer(self):
        """Zero-config path: no comfort_entity, the climate entity's
        ``current_temperature`` attribute is the reading."""
        hass = _hass_with({
            "climate.ac_livingroom": ("cool", {"current_temperature": 27.1}),
        })
        dev = _ac(hass, comfort_entity="")
        assert dev.comfort_state == "forced"


class TestTheBandDrivesTheGenericProperties:
    """The controller must not need new clauses — the band speaks through
    the properties every pass already reads."""

    def test_forced_reads_as_a_deficit(self):
        """FORCED ⇒ the deficit-driven passes (off-peak cheap grid, Tier-2
        battery) engage exactly per the user's #620 source-axis choices."""
        dev = _ac(_hass_with({"sensor.room_temp": "27.0"}))
        assert dev.has_runtime_deficit is True
        assert dev.needs_offpeak_activation is True

    def test_banked_reads_as_stop_condition(self):
        dev = _ac(_hass_with({"sensor.room_temp": "21.0"}))
        assert dev.stop_condition_met is True

    def test_willing_is_neither(self):
        dev = _ac(_hass_with({"sensor.room_temp": "24.5"}))
        assert dev.has_runtime_deficit is False
        assert dev.stop_condition_met is False

    def test_a_met_runtime_floor_does_not_stand_down_a_forced_comfort_run(self):
        """Device has BOTH goals: 30 min runtime (met) + comfort. At 27 °C the
        paid sources must still serve the breach — ``daily_targets_met`` is
        the stand-down signal and must stay False while FORCED."""
        dev = _ac(_hass_with({"sensor.room_temp": "27.0"}),
                  daily_min_runtime_sec=1800)
        dev._daily_runtime_accumulated_sec = 1900.0
        assert dev.daily_targets_met is False

    def test_runtime_stop_entity_still_composes(self):
        """The existing one-directional stop override survives beside the
        band (they OR together)."""
        hass = _hass_with({"sensor.room_temp": "24.5",
                           "sensor.window_open_count": "2"})
        dev = _ac(hass)
        dev.stop_entity = "sensor.window_open_count"
        dev.stop_at = 1.0
        assert dev.stop_condition_met is True  # window stop, though WILLING


class TestSpecAndGoals:
    """The four fields travel the register/persist/rebuild pipeline."""

    def test_factory_builds_comfort_fields_from_spec(self):
        dev = surplus_device_from_spec(_hass_with({}), "ac1", {
            "device_type": "climate", "name": "AC",
            "entity_id": "climate.ac1", "rated_power": 1000,
            "hvac_mode": "cool",
            "comfort_entity": "sensor.room1",
            "comfort_target": 23.5, "comfort_offset": 1.5,
            "comfort_limit": 25.5,
        })
        assert dev.comfort_entity == "sensor.room1"
        assert dev.comfort_target == 23.5
        assert dev.comfort_offset == 1.5
        assert dev.comfort_limit == 25.5

    def test_goal_properties_accept_the_comfort_fields(self):
        from custom_components.solar_energy_management.features.device_registry import (
            UnifiedDeviceRegistry,
        )
        for prop in ("comfort_entity", "comfort_target",
                     "comfort_offset", "comfort_limit"):
            assert prop in UnifiedDeviceRegistry.GOAL_PROPERTIES, prop

    def test_apply_goals_writes_the_band_onto_a_live_device(self):
        from custom_components.solar_energy_management.features.device_registry import (
            UnifiedDeviceRegistry,
        )
        reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
        reg._device_goals = {"ac1": {
            "comfort_entity": "sensor.room1",
            "comfort_target": "23.5", "comfort_offset": "1.5",
            "comfort_limit": "25.5",
            "daily_min_runtime_min": 0,
        }}
        dev = _ac(_hass_with({}), comfort_entity="", target=0, offset=0, limit=0)
        dev.device_id = "ac1"
        reg._apply_goals(dev)
        assert dev.comfort_entity == "sensor.room1"
        assert dev.comfort_target == 23.5
        assert dev.comfort_offset == 1.5
        assert dev.comfort_limit == 25.5

    def test_apply_goals_on_a_switch_device_is_harmless(self):
        """Phase 2 opens the same fields to switch loads; until then a
        comfort goal stored against a non-climate device must not crash the
        rebuild (attributes just land unused)."""
        from custom_components.solar_energy_management.features.device_registry import (
            UnifiedDeviceRegistry,
        )
        from custom_components.solar_energy_management.devices.base import (
            SwitchDevice,
        )
        reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
        reg._device_goals = {"sw1": {"comfort_target": "22.0"}}
        dev = SwitchDevice(_hass_with({}), "sw1", "Switch", 500,
                           entity_id="switch.sw1")
        reg._apply_goals(dev)  # must not raise


class TestReviewFindings:
    """The 2 HIGH + 2 MEDIUM findings from the pre-commit review, pinned."""

    def test_a_fahrenheit_sensor_is_converted_before_comparison(self):
        """H1 — 78.8 °F = 26.0 °C = exactly at the limit ⇒ forced. Unconverted,
        78.8 ≥ 26 would ALSO read forced — so pin the inverse too: 75.2 °F =
        24.0 °C is inside the band, though 75.2 ≥ 26 raw."""
        hass = MagicMock()
        st = MagicMock()
        st.state, st.attributes = "78.8", {"unit_of_measurement": "°F"}
        hass.states.get.return_value = st
        assert _ac(hass).comfort_state == "forced"
        st.state = "75.2"
        assert _ac(hass).comfort_state == "willing"

    def test_the_attribute_path_follows_the_install_display_unit(self):
        """H1, zero-config half: on a °F install BOTH sides are °F — the
        climate attribute reads °F and the user's thresholds mean °F.
        (This test originally pinned °C thresholds on a °F install; that
        contract was rejected — a °F user types °F.)"""
        hass = _hass_with({
            "climate.ac_livingroom": ("cool", {"current_temperature": 80.6}),
        })
        hass.config.units.temperature_unit = "°F"
        dev = _ac(hass, comfort_entity="", target=76.0, offset=4.0, limit=80.0)
        assert dev.comfort_state == "forced"      # 80.6 °F ≥ 80 °F
        hass2 = _hass_with({
            "climate.ac_livingroom": ("cool", {"current_temperature": 73.4}),
        })
        hass2.config.units.temperature_unit = "°F"
        dev2 = _ac(hass2, comfort_entity="", target=76.0, offset=4.0, limit=80.0)
        assert dev2.comfort_state == "willing"    # 72 °F < 73.4 °F < 80 °F

    def test_an_inverted_band_disengages_instead_of_forcing_forever(self):
        """H2 — cool with limit BELOW target would make the whole comfortable
        range read 'forced' and run the unit continuously on paid sources."""
        dev = _ac(_hass_with({"sensor.room_temp": "23.0"}),
                  target=24.0, limit=22.0)
        assert dev.comfort_state == "disengaged"
        assert dev.has_runtime_deficit is False

    def test_an_inverted_heat_band_disengages_too(self):
        dev = _ac(_hass_with({"sensor.room_temp": "20.0"}),
                  hvac_mode="heat", target=21.0, limit=23.0)
        assert dev.comfort_state == "disengaged"

    def test_the_daily_cap_outranks_the_comfort_force(self):
        """M2 — a unit that has run its configured max for the day is done,
        breach or no breach."""
        dev = _ac(_hass_with({"sensor.room_temp": "27.0"}),
                  daily_max_runtime_sec=3600)
        dev._daily_runtime_accumulated_sec = 3700.0
        assert dev.comfort_state == "forced"          # the room IS hot…
        assert dev.has_runtime_deficit is False       # …but the cap won

    def test_min_off_is_floored_at_180s_while_the_band_is_engaged(self):
        """M3 — the band makes cycling temperature-driven; 60 s is under the
        compressor safe-restart floor."""
        dev = _ac(_hass_with({"sensor.room_temp": "24.5"}), min_off_time=60)
        assert dev.min_off_seconds == 180

    def test_a_stricter_configured_window_still_wins(self):
        dev = _ac(_hass_with({"sensor.room_temp": "24.5"}), min_off_time=600)
        assert dev.min_off_seconds == 600

    def test_a_disengaged_band_keeps_the_configured_window(self):
        """No comfort config ⇒ the #569 default stands untouched."""
        dev = _ac(_hass_with({}), target=0.0, limit=0.0, min_off_time=60)
        assert dev.min_off_seconds == 60

    def test_solar_only_forced_without_surplus_does_not_run(self):
        """L2 — 'forced reads as a deficit' is necessary but NOT sufficient:
        the source axis still gates. A solar_only device past its limit with
        no sun and no paid opt-in stays off — honestly."""
        from custom_components.solar_energy_management.coordinator.surplus_controller import (
            compute_load_intent,
        )
        dev = _ac(_hass_with({"sensor.room_temp": "27.0"}))
        dev.top_up_policy = "solar_only"
        intent = compute_load_intent(
            dev, remaining_surplus_w=0.0, tier1_headroom_w=0.0,
            price_is_cheap=True, soc_above_reserve=True,
        )
        assert intent.on is False


class TestThresholdsFollowTheInstallUnit:
    """A °F user types °F. The thresholds are interpreted in the install's
    display unit (HA's own convention for every temperature input), and the
    comparison happens in °C internally. The OFFSET is a temperature
    DIFFERENCE — it converts linearly (Δ°F × 5/9), never affinely."""

    def _f_install(self, states):
        hass = _hass_with(states)
        hass.config.units.temperature_unit = "°F"
        return hass

    def test_a_fahrenheit_install_types_fahrenheit(self):
        # target 76 °F (24.4 °C), offset 4 °F (Δ2.2 °C), limit 80 °F (26.7 °C)
        hass = self._f_install({"sensor.room_temp": ("80.6", {"unit_of_measurement": "°F"})})
        dev = _ac(hass, target=76.0, offset=4.0, limit=80.0)
        assert dev.comfort_state == "forced"       # 80.6 °F ≥ 80 °F

    def test_the_offset_converts_as_a_difference(self):
        # banked bound = 76 − 4 = 72 °F = 22.2 °C. Room 71 °F (21.7 °C) → banked.
        # An affine (wrong) offset conversion would put the bound at ≈ 40 °F.
        hass = self._f_install({"sensor.room_temp": ("71.0", {"unit_of_measurement": "°F"})})
        dev = _ac(hass, target=76.0, offset=4.0, limit=80.0)
        assert dev.comfort_state == "banked"

    def test_between_is_willing_on_a_f_install(self):
        hass = self._f_install({"sensor.room_temp": ("74.0", {"unit_of_measurement": "°F"})})
        dev = _ac(hass, target=76.0, offset=4.0, limit=80.0)
        assert dev.comfort_state == "willing"

    def test_a_celsius_sensor_on_a_f_install_still_works(self):
        # Both sides normalize to °C independently: °C sensor reading 27,
        # °F thresholds 76/80 → 27 ≥ 26.7 → forced.
        hass = self._f_install({"sensor.room_temp": ("27.0", {"unit_of_measurement": "°C"})})
        dev = _ac(hass, target=76.0, offset=4.0, limit=80.0)
        assert dev.comfort_state == "forced"

    def test_metric_installs_are_untouched(self):
        hass = _hass_with({"sensor.room_temp": "24.5"})
        hass.config.units.temperature_unit = "°C"
        dev = _ac(hass)   # 24/2/26 °C as everywhere else in this file
        assert dev.comfort_state == "willing"


class TestThePayloadIsTheSingleSource:
    """The card must never re-derive the band — a frontend copy of the
    band logic is how state-contradicts-action bugs are born. The devices
    payload publishes the goals (pre-fill) AND the live verdict (chip)."""

    def _registry_with(self, dev, goals):
        from custom_components.solar_energy_management.features.device_registry import (
            UnifiedDeviceRegistry,
        )
        reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
        reg._device_goals = {dev.device_id: goals}
        ctrl = MagicMock()
        ctrl.get_device.return_value = dev
        reg._surplus_controller = ctrl
        return reg

    def test_comfort_goals_ride_the_payload(self):
        dev = _ac(_hass_with({"sensor.room_temp": "24.5"}))
        p = self._registry_with(dev, {
            "comfort_entity": "sensor.room_temp", "comfort_target": "24",
            "comfort_offset": "2", "comfort_limit": "26",
        })._goal_payload(dev.device_id)
        g = p["goals"]
        assert g["comfort_entity"] == "sensor.room_temp"
        assert g["comfort_target"] == "24"
        assert g["comfort_limit"] == "26"

    def test_the_live_verdict_rides_beside_the_goals(self):
        dev = _ac(_hass_with({"sensor.room_temp": "27.0"}))
        p = self._registry_with(dev, {})._goal_payload(dev.device_id)
        assert p["comfort"] == {"state": "forced", "reading_c": 27.0, "hvac": "cool"}

    def test_a_non_climate_device_carries_no_comfort_block(self):
        from custom_components.solar_energy_management.devices.base import (
            SwitchDevice,
        )
        dev = SwitchDevice(_hass_with({}), "sw1", "Switch", 500,
                           entity_id="switch.sw1")
        p = self._registry_with(dev, {})._goal_payload("sw1")
        assert "comfort" not in p

    def test_a_disengaged_band_still_reports_honestly(self):
        """The chip hides on 'disengaged' — but the payload says WHY the
        band is dark rather than omitting it (a climate device with goals
        set and a dead sensor must not look identical to one without)."""
        dev = _ac(_hass_with({}))  # sensor missing
        p = self._registry_with(dev, {})._goal_payload(dev.device_id)
        assert p["comfort"] == {"state": "disengaged", "reading_c": None, "hvac": "cool"}
