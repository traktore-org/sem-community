"""Full-day scenario tests for Solar Energy Management.

Simulates realistic day patterns and verifies cumulative behavior:
state transitions, energy totals, and device commands.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime, date

from custom_components.solar_energy_management.coordinator.energy_calculator import EnergyCalculator
from custom_components.solar_energy_management.coordinator.types import PowerReadings
from custom_components.solar_energy_management.utils.time_manager import TimeManager


def _make_power(**kwargs) -> PowerReadings:
    p = PowerReadings(**kwargs)
    p.calculate_derived()
    return p


@pytest.fixture
def time_manager():
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    return TimeManager(hass)


@pytest.fixture
def energy_calc(time_manager):
    return EnergyCalculator({"update_interval": 10}, time_manager)


class TestEnergyAccumulation:
    """Test energy accumulates correctly over simulated cycles."""

    def test_solar_accumulates_over_cycles(self, energy_calc):
        """10 cycles at 5000W solar = ~0.014 kWh."""
        for _ in range(10):
            power = _make_power(solar_power=5000)
            energy = energy_calc.calculate_energy(power)
        assert energy.daily_solar >= 0.01

    def test_ev_accumulates_separately(self, energy_calc):
        """EV energy uses sunrise-based key (ev_daily_sun)."""
        for _ in range(10):
            power = _make_power(ev_power=4800, solar_power=5000)
            energy = energy_calc.calculate_energy(power)
        assert energy.daily_ev >= 0.01
        # Verify it's using ev_daily_sun key
        keys = [k for k in energy_calc._daily_accumulators if k.startswith("ev_daily_sun")]
        assert len(keys) > 0

    def test_midnight_rollover_preserves_ev(self, energy_calc):
        """EV accumulator survives midnight rollover."""
        # Simulate charging before midnight
        for _ in range(5):
            power = _make_power(ev_power=4800)
            energy_calc.calculate_energy(power)

        ev_before = energy_calc._get_daily("ev_daily_sun", date.today())

        # Simulate rollover (different date for non-EV)
        from datetime import timedelta
        tomorrow = date.today() + timedelta(days=1)
        energy_calc._check_rollover(tomorrow, f"{tomorrow.year}_{tomorrow.month}")

        # EV should survive
        ev_after = energy_calc._get_daily("ev_daily_sun", date.today())
        assert ev_after == ev_before

    def test_midnight_rollover_resets_others(self, energy_calc):
        """Solar/home/grid reset at midnight."""
        for _ in range(5):
            power = _make_power(solar_power=5000, ev_power=0)
            energy_calc.calculate_energy(power)

        solar_before = energy_calc._get_daily("solar", date.today())
        assert solar_before > 0

        from datetime import timedelta
        tomorrow = date.today() + timedelta(days=1)
        energy_calc._check_rollover(tomorrow, f"{tomorrow.year}_{tomorrow.month}")

        solar_after = energy_calc._get_daily("solar", date.today())
        assert solar_after == 0  # Reset


class TestYearlyAccumulators:
    """Test yearly energy accumulators and environmental impact."""

    def test_yearly_solar_accumulates(self, energy_calc):
        """Yearly solar should accumulate across cycles."""
        for _ in range(10):
            power = _make_power(solar_power=5000)
            energy = energy_calc.calculate_energy(power)
        assert energy.yearly_solar >= 0.01

    def test_yearly_costs_calculated(self, energy_calc):
        """Yearly costs should be derived from yearly grid import."""
        for _ in range(500):
            power = _make_power(solar_power=0, grid_power=-10000)
            energy = energy_calc.calculate_energy(power)
        costs = energy_calc.calculate_costs(energy)
        # Yearly grid import should accumulate (first cycle uses config interval)
        assert energy.yearly_grid_import > 0
        # Cost = import × rate; may round to 0.01 at minimum
        assert costs.yearly_costs >= 0
        # Verify the formula works: costs = import × rate
        expected = round(energy.yearly_grid_import * 0.3387, 2)
        assert costs.yearly_costs == expected

    def test_yearly_survives_daily_rollover(self, energy_calc):
        """Yearly accumulators should NOT reset on midnight rollover."""
        for _ in range(5):
            power = _make_power(solar_power=5000)
            energy_calc.calculate_energy(power)

        year_key = f"{date.today().year}"
        solar_before = energy_calc._get_yearly("solar", year_key)
        assert solar_before > 0

        # Simulate daily rollover
        from datetime import timedelta
        tomorrow = date.today() + timedelta(days=1)
        energy_calc._check_rollover(
            tomorrow,
            f"{tomorrow.year}_{tomorrow.month}",
            f"{tomorrow.year}",
        )

        solar_after = energy_calc._get_yearly("solar", year_key)
        assert solar_after == solar_before  # NOT reset

    def test_co2_avoided_calculated(self, energy_calc):
        """CO2 avoided should be based on self-consumed solar."""
        for _ in range(500):
            # 8kW solar, 2kW export → 6kW self-consumed
            power = _make_power(solar_power=8000, grid_power=2000)
            energy = energy_calc.calculate_energy(power)
        costs = energy_calc.calculate_costs(energy)
        # Self-consumed = solar - export
        self_consumed = energy.daily_solar - energy.daily_grid_export
        assert self_consumed > 0
        # CO2 = self_consumed × 0.128
        expected_co2 = round(self_consumed * 0.128, 2)
        assert costs.daily_co2_avoided_kg == expected_co2
        assert costs.yearly_co2_avoided_kg >= costs.daily_co2_avoided_kg

    def test_trees_equivalent(self, energy_calc):
        """Trees equivalent should scale with CO2 avoided."""
        for _ in range(20):
            power = _make_power(solar_power=5000, home_consumption_power=5000)
            energy = energy_calc.calculate_energy(power)
        costs = energy_calc.calculate_costs(energy)
        assert costs.yearly_trees_equivalent >= 0
        # Trees = co2 / 22
        if costs.yearly_co2_avoided_kg > 0:
            expected = costs.yearly_co2_avoided_kg / 22
            assert abs(costs.yearly_trees_equivalent - round(expected, 1)) < 0.2

    def test_lifetime_never_resets(self, energy_calc):
        """Lifetime accumulators should survive year rollover."""
        for _ in range(5):
            power = _make_power(solar_power=5000)
            energy_calc.calculate_energy(power)

        lifetime_before = energy_calc._get_lifetime("solar")
        assert lifetime_before > 0

        # Simulate year rollover
        from datetime import timedelta
        next_year = date.today().replace(year=date.today().year + 1, month=1, day=1)
        energy_calc._check_rollover(
            next_year,
            f"{next_year.year}_{next_year.month}",
            f"{next_year.year}",
        )

        lifetime_after = energy_calc._get_lifetime("solar")
        assert lifetime_after == lifetime_before  # Never resets

    def test_state_persistence_includes_yearly(self, energy_calc):
        """get_state/restore_state should include yearly + lifetime."""
        for _ in range(5):
            power = _make_power(solar_power=5000)
            energy_calc.calculate_energy(power)

        state = energy_calc.get_state()
        assert "yearly_accumulators" in state
        assert "lifetime_accumulators" in state
        assert len(state["yearly_accumulators"]) > 0
        assert len(state["lifetime_accumulators"]) > 0

        # Restore into fresh calculator
        from custom_components.solar_energy_management.utils.time_manager import TimeManager
        from unittest.mock import MagicMock
        tm = TimeManager(MagicMock())
        calc2 = EnergyCalculator({"update_interval": 10}, tm)
        calc2.restore_state(state)

        year_key = f"{date.today().year}"
        assert calc2._get_yearly("solar", year_key) > 0
        assert calc2._get_lifetime("solar") > 0


class TestChargingStrategyScenarios:
    """Test strategy decisions for typical day scenarios."""

    def test_morning_low_solar_no_charge(self):
        """Early morning, 200W solar — should idle."""
        from tests.test_soc_zone_strategy import _build_coordinator, _make_power as _mp, _MockEnergy
        coord = _build_coordinator()
        strategy, reason = coord._determine_charging_strategy(
            _mp(solar_power=150, battery_soc=60), _MockEnergy()
        )
        assert strategy == "idle"
        assert "200W" in reason  # Below threshold

    def test_midday_surplus_charges(self):
        """Midday, 5kW solar, battery 90% — battery assist."""
        from tests.test_soc_zone_strategy import _build_coordinator, _make_power as _mp, _MockEnergy
        coord = _build_coordinator()
        strategy, _ = coord._determine_charging_strategy(
            _mp(solar_power=5000, battery_soc=95), _MockEnergy()
        )
        assert strategy == "battery_assist"

    def test_evening_night_mode_charges(self):
        """Evening, night mode, target not reached — night grid."""
        from tests.test_soc_zone_strategy import _build_coordinator, _make_power as _mp, _MockEnergy
        coord = _build_coordinator()
        coord.time_manager.is_night_mode.return_value = True
        strategy, _ = coord._determine_charging_strategy(
            _mp(battery_soc=50), _MockEnergy(daily_ev=3.0)
        )
        assert strategy == "night_grid"

    def test_night_target_reached_stops(self):
        """Night mode, target reached — idle."""
        from tests.test_soc_zone_strategy import _build_coordinator, _make_power as _mp, _MockEnergy
        coord = _build_coordinator()
        coord.time_manager.is_night_mode.return_value = True
        strategy, _ = coord._determine_charging_strategy(
            _mp(battery_soc=50), _MockEnergy(daily_ev=10.0)
        )
        assert strategy == "idle"

    def test_solar_continues_past_target(self):
        """Daytime, target reached, surplus available — solar continues."""
        from tests.test_soc_zone_strategy import _build_coordinator, _make_power as _mp, _MockEnergy
        coord = _build_coordinator()
        strategy, _ = coord._determine_charging_strategy(
            _mp(solar_power=5000, battery_soc=95), _MockEnergy(daily_ev=15.0)
        )
        assert strategy != "idle"  # Solar always charges

    def test_now_mode_overrides(self):
        """Now mode — charge at max regardless."""
        from tests.test_soc_zone_strategy import _build_coordinator, _make_power as _mp, _MockEnergy
        coord = _build_coordinator()
        coord.config["ev_charging_mode"] = "now"
        strategy, _ = coord._determine_charging_strategy(
            _mp(solar_power=100, battery_soc=30), _MockEnergy()
        )
        assert strategy == "now"

    def test_low_battery_blocks_ev(self):
        """Battery below priority SOC — should idle (Zone 1)."""
        from tests.test_soc_zone_strategy import _build_coordinator, _make_power as _mp, _MockEnergy
        coord = _build_coordinator()
        strategy, reason = coord._determine_charging_strategy(
            _mp(solar_power=3000, battery_soc=20), _MockEnergy()
        )
        assert strategy == "idle"
        assert "Zone 1" in reason


class TestDeviceAntiCycling:
    """Test min on/off time and activation delay."""

    def test_can_activate_respects_min_off(self):
        from custom_components.solar_energy_management.devices.base import SwitchDevice
        hass = MagicMock()
        device = SwitchDevice(hass, "heater", "Heater", rated_power=2000, entity_id="switch.heater")
        device.min_off_seconds = 300

        # Just deactivated — should not activate
        device.record_deactivated()
        assert device.can_activate() is False

    def test_can_deactivate_respects_min_on(self):
        from custom_components.solar_energy_management.devices.base import SwitchDevice
        hass = MagicMock()
        device = SwitchDevice(hass, "heater", "Heater", rated_power=2000, entity_id="switch.heater")
        device.min_on_seconds = 300

        # Just activated — should not deactivate
        device.record_activated()
        assert device.can_deactivate() is False

    def test_activation_delay_requires_sustained_surplus(self):
        from custom_components.solar_energy_management.devices.base import SwitchDevice
        hass = MagicMock()
        device = SwitchDevice(hass, "heater", "Heater", rated_power=2000, entity_id="switch.heater")
        device.activation_delay_seconds = 60

        # First call starts timer
        assert device.can_activate() is False
        assert device._surplus_since is not None

        # Reset when surplus drops
        device.reset_surplus_timer()
        assert device._surplus_since is None


class TestPhaseSwitching:
    """Test 1p/3p phase switching."""

    @pytest.mark.asyncio
    async def test_switch_down_on_low_surplus(self):
        from custom_components.solar_energy_management.devices.base import CurrentControlDevice
        hass = MagicMock()
        hass.services.async_call = AsyncMock()

        device = CurrentControlDevice(hass, "ev", "EV", charger_service="keba.set_current")
        device.min_phases = 1
        device.max_phases = 3
        device.phases = 3
        device.phase_switch_entity = "switch.phase_relay"

        # Surplus below 3-phase min
        await device.check_phase_switch(2000)  # < 4140 - 200
        assert device.phases == 1

    @pytest.mark.asyncio
    async def test_no_switch_without_entity(self):
        from custom_components.solar_energy_management.devices.base import CurrentControlDevice
        hass = MagicMock()
        device = CurrentControlDevice(hass, "ev", "EV", charger_service="keba.set_current")
        device.phases = 3

        # No phase_switch_entity — should not switch
        await device.check_phase_switch(2000)
        assert device.phases == 3  # Unchanged


class TestLifetimeStats:
    """Test lifetime EV statistics."""

    def test_lifetime_stats_accumulate(self):
        from custom_components.solar_energy_management.coordinator.storage import SEMStorage
        hass = MagicMock()
        storage = SEMStorage(hass, "test")
        storage._energy_data = {}

        storage.update_lifetime_ev_stats(10.0, 7.0, 2.5, 0.5, 0.85)
        stats = storage.get_lifetime_ev_stats()
        assert stats["total_energy_kwh"] == 10.0
        assert stats["total_solar_kwh"] == 7.0
        assert stats["total_sessions"] == 1

        storage.update_lifetime_ev_stats(8.0, 6.0, 1.5, 0.5, 0.51)
        stats = storage.get_lifetime_ev_stats()
        assert stats["total_energy_kwh"] == 18.0
        assert stats["total_solar_kwh"] == 13.0
        assert stats["total_sessions"] == 2
        assert stats["total_cost"] == 1.36


class TestSessionPersistence:
    """Test EV session state persistence."""

    def test_session_state_roundtrip(self):
        from custom_components.solar_energy_management.coordinator.storage import SEMStorage
        hass = MagicMock()
        storage = SEMStorage(hass, "test")
        storage._daily_data = {}

        storage.set_ev_session_state({
            "session_active": True,
            "current_setpoint": 10.0,
        })

        state = storage.get_ev_session_state()
        assert state["session_active"] is True
        assert state["current_setpoint"] == 10.0
