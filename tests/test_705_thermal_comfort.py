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

    def test_a_bandless_device_carries_no_comfort_block(self):
        """Phase 2 gave switches the band, so THEY now report disengaged
        honestly — this pin moved to a class that genuinely has no band
        (SetpointDevice: it nudges a setpoint, it cannot hold a room)."""
        from custom_components.solar_energy_management.devices.base import (
            SetpointDevice,
        )
        dev = SetpointDevice(_hass_with({}), "sp1", "HP Setpoint", 2000)
        p = self._registry_with(dev, {})._goal_payload("sp1")
        assert "comfort" not in p

    def test_a_plain_switch_reports_a_disengaged_band(self):
        """Phase 2: the switch HAS a band now, dark until configured."""
        from custom_components.solar_energy_management.devices.base import (
            SwitchDevice,
        )
        dev = SwitchDevice(_hass_with({}), "sw1", "Switch", 500,
                           entity_id="switch.sw1")
        p = self._registry_with(dev, {})._goal_payload("sw1")
        assert p["comfort"]["state"] == "disengaged"

    def test_a_disengaged_band_still_reports_honestly(self):
        """The chip hides on 'disengaged' — but the payload says WHY the
        band is dark rather than omitting it (a climate device with goals
        set and a dead sensor must not look identical to one without)."""
        dev = _ac(_hass_with({}))  # sensor missing
        p = self._registry_with(dev, {})._goal_payload(dev.device_id)
        assert p["comfort"] == {"state": "disengaged", "reading_c": None, "hvac": "cool"}


class TestSetpointAnchoring:
    """(#705, Azlinon's review) The band rides the thermostat's OWN live
    setpoint: the user's schedule / presence logic / Ecobee-style native
    pre-cool moves the setpoint on the climate entity, and SEM's band must
    follow it instead of fighting it with a stale absolute. The typed
    values keep carrying the DELTAS (bank-by, run-now-past) and remain the
    anchor of last resort when the entity exposes no setpoint."""

    def _ac_with_setpoint(self, room, attrs, **kw):
        states = {
            "sensor.room_temp": room,
            "climate.ac_livingroom": ("cool", attrs),
        }
        return _ac(_hass_with(states), **kw)

    def test_the_limit_rides_the_live_setpoint(self):
        """Config 24/26 (delta +2) but the thermostat holds 25 → forced
        begins at 27, so 26.4 — forced on the absolute — is only willing."""
        dev = self._ac_with_setpoint("26.4", {"temperature": 25.0})
        assert dev.comfort_state == "willing"

    def test_past_the_anchored_limit_is_still_forced(self):
        dev = self._ac_with_setpoint("27.1", {"temperature": 25.0})
        assert dev.comfort_state == "forced"

    def test_a_schedule_change_moves_the_band_without_touching_sem(self):
        """Night setback: the thermostat drops to 23 → forced at 25."""
        dev = self._ac_with_setpoint("25.2", {"temperature": 23.0})
        assert dev.comfort_state == "forced"

    def test_the_banked_bound_rides_too(self):
        # anchor 25, offset 2 → banked at ≤ 23 (config target 24 would
        # have said willing at 22.9... no: 22.9 ≤ 22 is false → willing).
        dev = self._ac_with_setpoint("22.9", {"temperature": 25.0})
        assert dev.comfort_state == "banked"

    def test_cool_range_mode_anchors_on_target_temp_high(self):
        dev = self._ac_with_setpoint(
            "26.4", {"target_temp_high": 25.0, "target_temp_low": 20.0})
        assert dev.comfort_state == "willing"

    def test_heat_range_mode_anchors_on_target_temp_low(self):
        # heat config 21/18 (delta −3); range low 20 → forced below 17.
        states = {
            "sensor.room_temp": "17.5",
            "climate.ac_livingroom": (
                "heat", {"target_temp_high": 24.0, "target_temp_low": 20.0}),
        }
        dev = _ac(_hass_with(states), hvac_mode="heat",
                  target=21.0, offset=2.0, limit=18.0)
        assert dev.comfort_state == "willing"

    def test_no_setpoint_falls_back_to_the_typed_absolutes(self):
        dev = self._ac_with_setpoint("26.4", {"current_temperature": 24.0})
        assert dev.comfort_state == "forced"

    def test_a_fahrenheit_install_anchors_in_display_units(self):
        """Config 76/80 °F (delta 4 °F ≈ 2.22 °C), thermostat at 78 °F →
        forced at 82 °F. A room at 80 °F is forced on the raw absolute
        and willing on the anchored band — opposite answers, so this
        cannot pass by cancellation."""
        states = {
            "sensor.room_temp": ("80.0", {"unit_of_measurement": "°F"}),
            "climate.ac_livingroom": ("cool", {"temperature": 78.0}),
        }
        hass = _hass_with(states)
        hass.config.units.temperature_unit = "°F"
        dev = _ac(hass, target=76.0, offset=4.0, limit=80.0)
        assert dev.comfort_state == "willing"

    def test_the_misconfig_guard_judges_the_typed_delta(self):
        """A limit on the wrong side of the typed target stays disengaged
        even when a sane-looking setpoint exists — the delta carries the
        user's intent and a negative cool-delta is still nonsense."""
        dev = self._ac_with_setpoint(
            "26.4", {"temperature": 25.0}, target=26.0, limit=24.0)
        assert dev.comfort_state == "disengaged"

    def test_switch_devices_have_no_anchor(self):
        """Phase-2 heaters have no setpoint to ride — the mixin default
        answers None and the typed absolutes stay authoritative."""
        from custom_components.solar_energy_management.devices.base import (
            SwitchDevice,
        )
        dev = SwitchDevice(
            _hass_with({"sensor.cellar": "17.0"}), "sw1", "Heater",
            rated_power=800, entity_id="switch.heater")
        dev.comfort_entity = "sensor.cellar"
        dev.comfort_target = 21.0
        dev.comfort_offset = 1.0
        dev.comfort_limit = 18.0
        assert dev._comfort_anchor_c() is None
        assert dev.comfort_state == "forced"


class TestPhase2SwitchLoads:
    """The same band on SwitchDevice — one mixin, no sibling copy.

    Differences from climate, each pinned: direction is HEAT (switch loads
    are heaters; a switch-cooler is a follow-up), the thermometer must be
    EXPLICIT (a relay has no current_temperature to fall back to), and the
    compressor min-off floor does NOT apply (resistive loads cycle safely)."""

    def _heater(self, hass, *, target=21.0, offset=2.0, limit=18.0):
        from custom_components.solar_energy_management.devices.base import (
            SwitchDevice,
        )
        dev = SwitchDevice(hass, "floor1", "Floor Heating", 500,
                           entity_id="switch.floor1", min_off_time=60)
        dev.comfort_entity = "sensor.room_temp"
        dev.comfort_target = target
        dev.comfort_offset = offset
        dev.comfort_limit = limit
        return dev

    def test_a_cold_room_forces_the_heater(self):
        dev = self._heater(_hass_with({"sensor.room_temp": "17.5"}))
        assert dev.comfort_state == "forced"
        assert dev.has_runtime_deficit is True

    def test_a_banked_room_stops_it(self):
        dev = self._heater(_hass_with({"sensor.room_temp": "23.5"}))
        assert dev.comfort_state == "banked"
        assert dev.stop_condition_met is True

    def test_between_is_willing(self):
        dev = self._heater(_hass_with({"sensor.room_temp": "20.0"}))
        assert dev.comfort_state == "willing"

    def test_no_explicit_sensor_disengages(self):
        """A relay has no thermometer of its own — nothing to fall back to."""
        dev = self._heater(_hass_with({"switch.floor1": "off"}))
        dev.comfort_entity = ""
        assert dev.comfort_state == "disengaged"
        assert dev.has_runtime_deficit is False

    def test_no_compressor_floor_on_switches(self):
        dev = self._heater(_hass_with({"sensor.room_temp": "20.0"}))
        assert dev.min_off_seconds == 60

    def test_the_payload_says_heat(self):
        """The chip must read pre-heating, not pre-cooling."""
        from custom_components.solar_energy_management.features.device_registry import (
            UnifiedDeviceRegistry,
        )
        dev = self._heater(_hass_with({"sensor.room_temp": "20.0"}))
        reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
        reg._device_goals = {"floor1": {}}
        ctrl = MagicMock(); ctrl.get_device.return_value = dev
        reg._surplus_controller = ctrl
        p = reg._goal_payload("floor1")
        assert p["comfort"] == {"state": "willing", "reading_c": 20.0,
                                "hvac": "heat"}

    def test_a_switch_without_comfort_goals_is_untouched(self):
        from custom_components.solar_energy_management.devices.base import (
            SwitchDevice,
        )
        dev = SwitchDevice(_hass_with({}), "sw", "Plain", 500,
                           entity_id="switch.sw")
        assert dev.comfort_state == "disengaged"
        assert dev.has_runtime_deficit is False
        assert dev.stop_condition_met is False


class TestComfortSampling:
    """(#638 Phase 3) The drift learners eat samples SEM already takes —
    one reading per cycle, split by whether the device was running."""

    def _now(self, minutes=0):
        from datetime import datetime, timedelta, timezone
        return (datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
                + timedelta(minutes=minutes))

    def _run(self, dev, running):
        from custom_components.solar_energy_management.devices.base import (
            DeviceState,
        )
        dev._status.state = (DeviceState.ACTIVE if running
                             else DeviceState.IDLE)

    def test_samples_split_by_activity(self):
        dev = _ac(_hass_with({"sensor.room_temp": "24.0"}))
        self._run(dev, False)
        dev.record_comfort_sample(self._now(0))
        self._run(dev, True)
        dev.record_comfort_sample(self._now(1))
        assert len(dev._comfort_off_samples) == 1
        assert len(dev._comfort_on_samples) == 1

    def test_a_silent_thermometer_is_not_a_sample(self):
        dev = _ac(_hass_with({}))
        dev.record_comfort_sample(self._now(0))
        assert not getattr(dev, "_comfort_off_samples", None)

    def test_a_disengaged_band_does_not_sample(self):
        dev = _ac(_hass_with({"sensor.room_temp": "24.0"}),
                  target=0.0, limit=0.0)
        dev.record_comfort_sample(self._now(0))
        assert not getattr(dev, "_comfort_off_samples", None)

    def test_old_samples_age_out(self):
        dev = _ac(_hass_with({"sensor.room_temp": "24.0"}))
        dev.record_comfort_sample(self._now(0))
        dev.record_comfort_sample(self._now(300))  # 5 h later
        assert len(dev._comfort_off_samples) == 1

    def test_two_devices_do_not_share_buffers(self):
        """The class-level-mutable-default trap: buffers must be per
        instance, or one room's history poisons every room's model."""
        a = _ac(_hass_with({"sensor.room_temp": "24.0"}))
        b = ClimateDevice(
            _hass_with({"sensor.room_temp": "20.0"}), "ac2", "AC 2",
            rated_power=900, entity_id="climate.ac2", hvac_mode="cool",
            comfort_entity="sensor.room_temp",
            comfort_target=24.0, comfort_offset=2.0, comfort_limit=26.0)
        a.record_comfort_sample(self._now(0))
        assert not getattr(b, "_comfort_off_samples", None)


class TestComfortPlanDemand:
    """(#638 Phase 3) The band's plannable ask: 'the room hits the limit
    at T, banking back to target costs E kWh' — or None when the model
    cannot say. This is what the day planner packs into surplus windows."""

    def _warming_ac(self, room="24.5", off_rate=0.5, on_rate=-1.0):
        """An AC whose room warms at ``off_rate`` °C/h while off and
        cools at ``on_rate`` while running, fed 30 min of samples each."""
        from datetime import datetime, timedelta, timezone
        dev = _ac(_hass_with({"sensor.room_temp": room}))
        t0 = datetime(2026, 8, 8, 11, 0, tzinfo=timezone.utc)
        for i in range(7):
            ts = t0 + timedelta(minutes=5 * i)
            h = 5 * i / 60.0
            dev._ensure_comfort_buffers()
            dev._comfort_off_samples.append((ts, 23.0 + off_rate * h))
            dev._comfort_on_samples.append((ts, 25.0 + on_rate * h))
        self.now = t0 + timedelta(minutes=35)
        return dev

    def test_a_drifting_room_produces_the_ask(self):
        dev = self._warming_ac()
        ask = dev.comfort_plan_demand(self.now)
        assert ask is not None
        # 24.5 → 26 at 0.5 °C/h = 3 h to the limit
        hours = (ask["deadline"] - self.now).total_seconds() / 3600.0
        assert 2.5 < hours < 3.5
        # 0.5 °C back to target at 1 °C/h active = 0.5 h × 1.2 kW
        assert ask["energy_kwh"] == pytest.approx(0.6, abs=0.01)

    def test_a_room_holding_itself_is_no_ask(self):
        dev = self._warming_ac(off_rate=-0.1)
        assert dev.comfort_plan_demand(self.now) is None

    def test_a_forced_room_is_the_reactive_layers_problem(self):
        dev = self._warming_ac(room="26.5")
        assert dev.comfort_plan_demand(self.now) is None

    def test_no_active_model_is_no_ask(self):
        dev = self._warming_ac()
        dev._comfort_on_samples.clear()
        assert dev.comfort_plan_demand(self.now) is None

    def test_an_already_banked_room_asks_nothing(self):
        dev = self._warming_ac(room="21.5")
        assert dev.comfort_plan_demand(self.now) is None
