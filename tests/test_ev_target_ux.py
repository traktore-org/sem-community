"""Tests for the simplified EV charge-target UX (#235).

Covers:
- DeviceControlMode enum reverted to 3 modes (off, peak_only, surplus)
- _calculate_remaining_need() with kWh and SOC target types
- ev_target_mode → ev_target_type rename (with back-compat read)
- soc_limit_active derivation: ev_limit_surplus switch AND target reached
- SurplusController activation/deactivation by control mode
- Per-charger overrides, target-type SOC gating, and edge cases
"""
import pytest
from unittest.mock import MagicMock, AsyncMock

from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode,
    SwitchDevice,
    CurrentControlDevice,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.select import (
    _target_type_options,
    SEMPerChargerSelect,
)
from custom_components.solar_energy_management.features.device_registry import (
    _migrate_control_modes,
)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_hass():
    hass = MagicMock()
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.services.has_service = MagicMock(return_value=False)
    return hass


def _make_switch(mock_hass, device_id="dev1", control_mode=DeviceControlMode.SURPLUS):
    """Create a SwitchDevice with the given control mode."""
    dev = SwitchDevice(
        hass=mock_hass,
        device_id=device_id,
        name=device_id,
        rated_power=2000,
        priority=5,
        entity_id=f"switch.{device_id}",
    )
    dev.control_mode = control_mode
    return dev


def _make_charger(mock_hass, device_id="ev1", control_mode=DeviceControlMode.SURPLUS, priority=5):
    """Create a CurrentControlDevice (EV charger) with the given control mode."""
    dev = CurrentControlDevice(
        hass=mock_hass,
        device_id=device_id,
        name=device_id,
        priority=priority,
        min_current=6.0,
        max_current=16.0,
        phases=3,
        voltage=230.0,
        current_entity_id=f"number.{device_id}_current",
    )
    dev.control_mode = control_mode
    return dev


def _make_coordinator(config=None):
    """Create a minimal SEMCoordinator with __new__ (no HA bus needed)."""
    coord = SEMCoordinator.__new__(SEMCoordinator)
    coord.config = config or {
        "ev_target_soc": 80,
        "ev_battery_capacity_kwh": 40,
        "daily_ev_target": 10,
    }
    return coord


def _make_energy(daily_ev=0.0):
    energy = MagicMock()
    energy.daily_ev = daily_ev
    return energy


def _soc_limit_active(coord, energy, vehicle_soc=None):
    """Reproduce the coordinator's surplus-stop derivation (#245).

    The ev_limit_surplus switch (#235) was folded into the Max ceiling: surplus
    stops when the remaining-to-Max <= 0.1. Max defaults to full (100), so with
    no Max configured surplus only stops at car-full.
    """
    remaining_max = coord._calculate_remaining_need(
        energy, vehicle_soc=vehicle_soc, bound="max"
    )
    return remaining_max <= 0.1


# ──────────────────────────────────────────────
# Mode switching (DeviceControlMode enum) — reverted to 3 modes
# ──────────────────────────────────────────────

class TestDeviceControlModeEnum:
    """The enum is reverted to off/peak_only/surplus (#235)."""

    def test_default_control_mode_is_peak_only(self):
        """Default mode on ControllableDevice is PEAK_ONLY — backward compatible."""
        hass = _make_hass()
        dev = SwitchDevice(hass=hass, device_id="d1", name="d1", rated_power=1000)
        assert dev.control_mode == DeviceControlMode.PEAK_ONLY

    def test_setting_mode_to_surplus(self):
        """Mode can be changed to SURPLUS."""
        hass = _make_hass()
        dev = _make_switch(hass, control_mode=DeviceControlMode.SURPLUS)
        assert dev.control_mode == DeviceControlMode.SURPLUS
        assert dev.control_mode.value == "surplus"

    def test_setting_mode_to_off(self):
        """Mode can be changed to OFF."""
        hass = _make_hass()
        dev = _make_switch(hass, control_mode=DeviceControlMode.OFF)
        assert dev.control_mode == DeviceControlMode.OFF
        assert dev.control_mode.value == "off"

    def test_enum_has_three_members(self):
        """Enum has exactly: OFF, PEAK_ONLY, SURPLUS — surplus_target removed (#235)."""
        values = {m.value for m in DeviceControlMode}
        assert values == {"off", "peak_only", "surplus"}

    def test_surplus_target_removed(self):
        """SURPLUS_TARGET no longer exists on the enum."""
        assert not hasattr(DeviceControlMode, "SURPLUS_TARGET")


class TestControlModeMigration:
    """Existing installs: persisted 'surplus_target' is migrated to 'surplus' (#235)."""

    def test_migrates_surplus_target_to_surplus(self):
        modes = {"ev_charger": "surplus_target", "boiler": "peak_only", "pump": "surplus"}
        migrated = _migrate_control_modes(modes)
        assert migrated == ["ev_charger"]
        assert modes == {"ev_charger": "surplus", "boiler": "peak_only", "pump": "surplus"}

    def test_noop_when_no_surplus_target(self):
        modes = {"a": "off", "b": "surplus", "c": "peak_only"}
        assert _migrate_control_modes(modes) == []
        assert modes == {"a": "off", "b": "surplus", "c": "peak_only"}

    def test_migrated_value_is_valid_enum(self):
        modes = {"ev": "surplus_target"}
        _migrate_control_modes(modes)
        # The migrated value must construct a valid (3-member) DeviceControlMode
        assert DeviceControlMode(modes["ev"]) == DeviceControlMode.SURPLUS


# ──────────────────────────────────────────────
# kWh target type via _calculate_remaining_need
# ──────────────────────────────────────────────

class TestKwhTargetType:
    """_calculate_remaining_need with ev_target_type='kwh' (or default)."""

    def test_remaining_equals_target_minus_delivered(self):
        coord = _make_coordinator({"daily_ev_target": 10, "ev_battery_capacity_kwh": 40, "ev_target_soc": 80})
        energy = _make_energy(daily_ev=3.0)
        assert coord._calculate_remaining_need(energy, vehicle_soc=None) == pytest.approx(7.0)

    def test_target_reached_when_delivered_equals_target(self):
        coord = _make_coordinator({"daily_ev_target": 10})
        energy = _make_energy(daily_ev=10.0)
        assert coord._calculate_remaining_need(energy, vehicle_soc=None) == 0.0

    def test_partial_delivery_correct_remaining(self):
        coord = _make_coordinator({"daily_ev_target": 15})
        energy = _make_energy(daily_ev=6.5)
        assert coord._calculate_remaining_need(energy, vehicle_soc=None) == pytest.approx(8.5)

    def test_zero_target_always_reached(self):
        coord = _make_coordinator({"daily_ev_target": 0})
        energy = _make_energy(daily_ev=0.0)
        assert coord._calculate_remaining_need(energy, vehicle_soc=None) == 0.0


# ──────────────────────────────────────────────
# SOC target type via _calculate_remaining_need
# ──────────────────────────────────────────────

class TestSocTargetType:
    """_calculate_remaining_need with ev_target_type='soc'."""

    def test_soc_remaining_is_gap_times_capacity(self):
        coord = _make_coordinator({
            "ev_target_type": "soc",
            "ev_target_soc": 80,
            "ev_battery_capacity_kwh": 40,
            "daily_ev_target": 10,
        })
        energy = _make_energy()
        # 75% SOC, 80% target, 40 kWh → (80-75)/100*40 = 2.0 kWh
        assert coord._calculate_remaining_need(energy, vehicle_soc=75.0) == pytest.approx(2.0)

    def test_soc_at_target_remaining_is_zero(self):
        coord = _make_coordinator({
            "ev_target_type": "soc",
            "ev_target_soc": 80,
            "ev_battery_capacity_kwh": 40,
        })
        energy = _make_energy()
        assert coord._calculate_remaining_need(energy, vehicle_soc=80.0) == 0.0

    def test_soc_above_target_clamped_to_zero(self):
        coord = _make_coordinator({
            "ev_target_type": "soc",
            "ev_target_soc": 80,
            "ev_battery_capacity_kwh": 40,
        })
        energy = _make_energy()
        assert coord._calculate_remaining_need(energy, vehicle_soc=95.0) == 0.0

    def test_soc_type_without_sensor_falls_back_to_kwh(self):
        """Without vehicle_soc (None), SOC type falls back to kWh calculation."""
        coord = _make_coordinator({
            "ev_target_type": "soc",
            "ev_target_soc": 80,
            "ev_battery_capacity_kwh": 40,
            "daily_ev_target": 10,
        })
        energy = _make_energy(daily_ev=4.0)
        assert coord._calculate_remaining_need(energy, vehicle_soc=None) == pytest.approx(6.0)


# ──────────────────────────────────────────────
# Back-compat: old ev_target_mode key still honoured (#235)
# ──────────────────────────────────────────────

class TestTargetTypeBackCompat:
    """The renamed key reads the legacy ev_target_mode value if present."""

    def test_legacy_ev_target_mode_soc_still_works(self):
        coord = _make_coordinator({
            "ev_target_mode": "soc",  # legacy key
            "ev_target_soc": 80,
            "ev_battery_capacity_kwh": 40,
            "daily_ev_target": 10,
        })
        energy = _make_energy()
        # legacy key still triggers SOC calc: (80-75)/100*40 = 2.0
        assert coord._calculate_remaining_need(energy, vehicle_soc=75.0) == pytest.approx(2.0)

    def test_new_key_wins_over_legacy(self):
        coord = _make_coordinator({
            "ev_target_type": "kwh",   # new key wins
            "ev_target_mode": "soc",   # legacy, ignored
            "ev_target_soc": 80,
            "ev_battery_capacity_kwh": 40,
            "daily_ev_target": 10,
        })
        energy = _make_energy(daily_ev=4.0)
        # kWh path: 10 - 4 = 6 (vehicle_soc ignored)
        assert coord._calculate_remaining_need(energy, vehicle_soc=75.0) == pytest.approx(6.0)


# ──────────────────────────────────────────────
# Surplus stop = Max ceiling reached (#245; folds ev_limit_surplus #235)
# ──────────────────────────────────────────────

class TestSurplusLimit:
    """Surplus stops when the Max ceiling is reached; Max defaults to full."""

    def test_max_set_and_reached_is_active(self):
        coord = _make_coordinator({"daily_ev_target": 10, "daily_ev_target_max": 10})
        coord._cycle_vehicle_soc = None
        assert _soc_limit_active(coord, _make_energy(daily_ev=10.0)) is True

    def test_no_max_charges_freely_until_full(self):
        # No Max → ceiling defaults to 100 kWh; 10 kWh delivered → not reached.
        coord = _make_coordinator({"daily_ev_target": 10})
        coord._cycle_vehicle_soc = None
        assert _soc_limit_active(coord, _make_energy(daily_ev=10.0)) is False

    def test_max_set_but_not_reached_is_inactive(self):
        coord = _make_coordinator({"daily_ev_target": 10, "daily_ev_target_max": 20})
        coord._cycle_vehicle_soc = None
        # 10 of 20 kWh ceiling → not reached → surplus continues
        assert _soc_limit_active(coord, _make_energy(daily_ev=10.0)) is False

    @pytest.mark.asyncio
    async def test_off_mode_device_never_activated(self):
        hass = _make_hass()
        ctrl = SurplusController(hass, regulation_offset=0)
        dev = _make_switch(hass, device_id="off_dev", control_mode=DeviceControlMode.OFF)
        ctrl.register_device(dev)
        await ctrl.update(available_power_w=10000)
        assert not dev.is_active


# ──────────────────────────────────────────────
# Per-charger configuration overrides
# ──────────────────────────────────────────────

class TestPerChargerConfig:
    """Per-charger target_type and target values override global config."""

    def test_per_charger_kwh_type_independent_of_soc_type_charger(self):
        coord_a = _make_coordinator({
            "ev_target_type": "kwh", "daily_ev_target": 10,
            "ev_target_soc": 80, "ev_battery_capacity_kwh": 40,
        })
        coord_b = _make_coordinator({
            "ev_target_type": "soc", "daily_ev_target": 10,
            "ev_target_soc": 80, "ev_battery_capacity_kwh": 40,
        })
        energy = _make_energy(daily_ev=5.0)
        assert coord_a._calculate_remaining_need(energy, vehicle_soc=60.0) == pytest.approx(5.0)
        assert coord_b._calculate_remaining_need(energy, vehicle_soc=60.0) == pytest.approx(8.0)

    def test_per_charger_target_soc_overrides_global(self):
        coord = _make_coordinator({
            "ev_target_type": "soc", "ev_target_soc": 80,
            "ev_battery_capacity_kwh": 40, "daily_ev_target": 10,
        })
        energy = _make_energy()
        charger_cfg = {"ev_target_soc": 90, "ev_battery_capacity_kwh": 40, "ev_target_type": "soc"}
        # per-charger: (90-75)/100*40 = 6.0 kWh
        assert coord._calculate_remaining_need(energy, vehicle_soc=75.0, charger_cfg=charger_cfg) == pytest.approx(6.0)

    def test_per_charger_daily_target_overrides_global(self):
        coord = _make_coordinator({"ev_target_type": "kwh", "daily_ev_target": 10})
        energy = _make_energy(daily_ev=5.0)
        charger_cfg = {"daily_ev_target": 20, "ev_target_type": "kwh"}
        assert coord._calculate_remaining_need(energy, vehicle_soc=None, charger_cfg=charger_cfg) == pytest.approx(15.0)


# ──────────────────────────────────────────────
# Target-type SOC gating (#235)
# ──────────────────────────────────────────────

class TestTargetTypeSocGating:
    """SOC % is only offered when a vehicle SOC entity is configured."""

    def test_helper_offers_kwh_only_without_vehicle_soc(self):
        assert _target_type_options(has_vehicle_soc=False) == ["kwh"]

    def test_helper_offers_both_with_vehicle_soc(self):
        assert _target_type_options(has_vehicle_soc=True) == ["kwh", "soc"]

    def _make_per_charger_select(self, charger_cfg, config_key="ev_target_type", value="kwh"):
        sel = SEMPerChargerSelect.__new__(SEMPerChargerSelect)
        sel._charger_id = charger_cfg.get("id", "ev_charger")
        # _config_key is required since the #282 generalisation — the class
        # now branches on it to decide target-type vs charging-mode options.
        sel._config_key = config_key
        sel._value = value
        sel.entity_description = MagicMock(options=[value])
        coord = MagicMock()
        coord.config = {"ev_chargers": [charger_cfg]}
        sel.coordinator = coord
        return sel

    def test_select_hides_soc_when_no_vehicle_entity(self):
        sel = self._make_per_charger_select({"id": "c1"})
        assert sel.options == ["kwh"]

    def test_select_offers_soc_when_vehicle_entity_set(self):
        sel = self._make_per_charger_select({"id": "c1", "vehicle_soc_entity": "sensor.car_soc"})
        assert sel.options == ["kwh", "soc"]

    def test_select_clamps_soc_value_when_unavailable(self):
        sel = self._make_per_charger_select({"id": "c1"})
        sel._value = "soc"  # stale value, but SOC not offered
        assert sel.current_option == "kwh"


class TestChargingModeSelect:
    """Per-charger ev_charging_mode select (#255, generalised in #282).

    The previous class hardcoded target-type behaviour everywhere; the
    charging-mode select silently inherited kwh/soc options, locking users
    to whatever mode was in the config dict because they couldn't actually
    change it from the UI.
    """

    def _make_select(self, *, initial_value="auto"):
        from custom_components.solar_energy_management.select import (
            EV_CHARGING_MODES, SEMPerChargerSelect,
        )
        sel = SEMPerChargerSelect.__new__(SEMPerChargerSelect)
        sel._charger_id = "c1"
        sel._config_key = "ev_charging_mode"
        sel._value = initial_value
        sel.entity_description = MagicMock(options=list(EV_CHARGING_MODES.keys()))
        coord = MagicMock()
        coord.config = {"ev_chargers": [{"id": "c1"}]}
        sel.coordinator = coord
        return sel

    def test_options_returns_charging_modes_not_target_types(self):
        sel = self._make_select()
        # Authoritative: should be the EV_CHARGING_MODES set, NOT kwh/soc.
        assert set(sel.options) == {"auto", "minpv", "now", "off"}
        assert "kwh" not in sel.options

    def test_current_option_preserves_charging_mode_value(self):
        sel = self._make_select(initial_value="minpv")
        # Previously this would silently clamp to "kwh" because the options
        # property hardcoded the target-type options. The fix unblocks the
        # actual mode from being displayed.
        assert sel.current_option == "minpv"

    def test_unknown_initial_value_falls_back_to_first_option(self):
        sel = self._make_select(initial_value="garbage_mode")
        # current_option clamps to options[0] when _value isn't in options.
        assert sel.current_option in sel.options


# ──────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_soc_exactly_at_target_is_zero(self):
        coord = _make_coordinator({
            "ev_target_type": "soc", "ev_target_soc": 80, "ev_battery_capacity_kwh": 40,
        })
        result = coord._calculate_remaining_need(_make_energy(), vehicle_soc=80.0)
        assert result == 0.0 and result >= 0.0

    def test_very_large_capacity_correct_calculation(self):
        coord = _make_coordinator({
            "ev_target_type": "soc", "ev_target_soc": 80, "ev_battery_capacity_kwh": 200,
        })
        # (80-30)/100*200 = 100 kWh
        assert coord._calculate_remaining_need(_make_energy(), vehicle_soc=30.0) == pytest.approx(100.0)

    def test_very_small_kwh_target(self):
        coord = _make_coordinator({"daily_ev_target": 1})
        assert coord._calculate_remaining_need(_make_energy(daily_ev=0.3), vehicle_soc=None) == pytest.approx(0.7)

    def test_zero_battery_capacity_no_division_by_zero(self):
        coord = _make_coordinator({
            "ev_target_type": "soc", "ev_target_soc": 80, "ev_battery_capacity_kwh": 0,
        })
        # (80-50)/100 * 0 = 0 → no ZeroDivisionError
        assert coord._calculate_remaining_need(_make_energy(), vehicle_soc=50.0) == 0.0

    def test_soc_never_negative_even_when_well_above_target(self):
        coord = _make_coordinator({
            "ev_target_type": "soc", "ev_target_soc": 50, "ev_battery_capacity_kwh": 60,
        })
        assert coord._calculate_remaining_need(_make_energy(), vehicle_soc=95.0) == 0.0

    def test_remaining_never_negative_for_kwh_type(self):
        coord = _make_coordinator({"daily_ev_target": 5})
        assert coord._calculate_remaining_need(_make_energy(daily_ev=20.0), vehicle_soc=None) == 0.0


# ──────────────────────────────────────────────
# Surplus controller mode filtering
# ──────────────────────────────────────────────

class TestSurplusControllerModeFiltering:
    """SurplusController correctly filters devices by control mode."""

    @pytest.mark.asyncio
    async def test_peak_only_device_not_activated_on_surplus(self):
        hass = _make_hass()
        ctrl = SurplusController(hass, regulation_offset=0)
        dev = _make_switch(hass, device_id="peak_dev", control_mode=DeviceControlMode.PEAK_ONLY)
        ctrl.register_device(dev)
        await ctrl.update(available_power_w=10000)
        assert not dev.is_active

    @pytest.mark.asyncio
    async def test_surplus_device_activated(self):
        hass = _make_hass()
        ctrl = SurplusController(hass, regulation_offset=0)
        dev_s = _make_switch(hass, device_id="dev_surplus", control_mode=DeviceControlMode.SURPLUS)
        ctrl.register_device(dev_s)
        await ctrl.update(available_power_w=10000)
        assert dev_s.is_active

    @pytest.mark.asyncio
    async def test_off_device_excluded_from_allocation(self):
        hass = _make_hass()
        ctrl = SurplusController(hass, regulation_offset=0)
        dev = _make_switch(hass, device_id="off_dev", control_mode=DeviceControlMode.OFF)
        ctrl.register_device(dev)
        result = await ctrl.update(available_power_w=10000)
        assert not dev.is_active
        device_ids_in_alloc = [a.device_id for a in result.allocations]
        assert "off_dev" not in device_ids_in_alloc
