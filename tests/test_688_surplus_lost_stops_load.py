"""#688 — losing the surplus must STOP a running load (bug-class 17, instance 6).

@onkelfu's pool pump: Min 8 h reached (8.3/8), mode "Solar only", the sun went
down — and SEM kept the pump running toward the 11.5 h Max on grid/battery.

Root cause: the allocation walk debited an ACTIVE device only its power *delta*
(``remaining_surplus -= max(0, delta)`` — unchanged since v1.0.0), never its
held draw. The deficit LIFO below was designed for a fully-debited pool (it
credits a shed device's draw BACK), but with the draw left in — and the solar
bound (#620) flooring the pool at 0 — ``remaining_surplus`` bottomed out at
``-regulation_offset`` (−50 W), permanently above the −100 W LIFO trigger.
"Surplus lost" could therefore never stop anything: the only remaining stops
were the Max cap, mode Off, or the user.

The fix debits the full draw (minus what Tier-1 battery assist legitimately
covers), which restores the LIFO exactly as designed and matches the
desired-state twin (``compute_load_intent`` → "no source available").
"""
import pytest
from unittest.mock import MagicMock, AsyncMock

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.devices.base import DeviceControlMode


def _mock(**kw):
    d = MagicMock()
    d.device_id = kw.get("device_id", "d")
    d.name = kw.get("name", "D")
    d.priority = kw.get("priority", 5)
    d.min_power_threshold = kw.get("min_power", 800)
    d.rated_power = kw.get("draw", 800)
    d.is_enabled = True
    d.managed_externally = False
    d.is_active = kw.get("is_active", False)
    d.device_type = MagicMock(value="switch")
    d.activate = AsyncMock(return_value=kw.get("draw", 800))
    # switch semantics: while active, adjust_power holds the rated draw
    d.adjust_power = AsyncMock(return_value=kw.get("draw", 800))
    d.get_current_consumption = MagicMock(
        return_value=kw.get("draw", 800) if kw.get("is_active") else 0.0)
    d.can_activate = MagicMock(return_value=kw.get("can_activate", True))
    d.can_deactivate = MagicMock(return_value=True)
    d.record_activated = MagicMock()
    d.record_deactivated = MagicMock()
    d.reset_surplus_timer = MagicMock()
    d.status = MagicMock()
    d.control_mode = kw.get("control_mode", DeviceControlMode.SURPLUS)
    d._sem_owned = kw.get("sem_owned", True)
    d.is_deadline_approaching = False
    d._offpeak_forced = False
    d._offpeak_forced_date = None
    d._batt_overnight_forced = kw.get("_batt_overnight_forced", False)
    d._batt_overnight_forced_date = None
    d.needs_offpeak_activation = kw.get("needs_offpeak", False)
    d.remaining_daily_runtime_sec = kw.get("remaining_sec", 0)
    d.daily_min_runtime_sec = 0
    d.daily_targets_met = kw.get("daily_targets_met", False)
    d.daily_max_runtime_reached = kw.get("max_reached", False)
    d.stop_condition_met = False
    d.top_up_policy = kw.get("top_up_policy", "solar_only")
    d.battery_assist_enabled = kw.get("battery_assist_enabled", False)
    d.battery_eligible_overnight = kw.get("battery_eligible_overnight", False)
    d.stop_entity = ""
    d.stop_at = 0

    async def _deact():
        d.is_active = False
    d.deactivate = AsyncMock(side_effect=_deact)
    return d


@pytest.fixture
def mock_hass():
    return MagicMock()


@pytest.mark.asyncio
class TestSurplusLostStopsRunningLoad:
    """The missing stop gate: no surplus + no funding source → the load stops."""

    async def test_pump_past_min_stops_at_dusk(self, mock_hass):
        """@onkelfu's exact report: Min met, Solar-only mode, surplus gone —
        the pump must stop, not ride grid/battery to the Max cap."""
        sc = SurplusController(mock_hass)
        pump = _mock(device_id="pump", draw=2000.0, min_power=2000.0,
                     is_active=True, daily_targets_met=True,
                     top_up_policy="grid")  # "Finish overnight from: Grid"
        sc.register_device(pump)
        # dusk: solar-bounded surplus pinned to 0, tariff not cheap
        await sc.update(0.0, price_level="normal")
        pump.deactivate.assert_awaited()

    async def test_solar_only_load_stops_at_dusk_even_below_min(self, mock_hass):
        """A solar_only device accepts missing its target on a dark day — no
        funding source at dusk means stop, deficit or not."""
        sc = SurplusController(mock_hass)
        pump = _mock(device_id="pump", draw=2000.0, min_power=2000.0,
                     is_active=True, daily_targets_met=False,
                     remaining_sec=3600, top_up_policy="solar_only")
        sc.register_device(pump)
        await sc.update(0.0, price_level="normal")
        pump.deactivate.assert_awaited()

    async def test_funded_load_keeps_running(self, mock_hass):
        """Control: with the surplus still covering the draw, nothing stops."""
        sc = SurplusController(mock_hass)
        pump = _mock(device_id="pump", draw=2000.0, min_power=2000.0,
                     is_active=True, daily_targets_met=True)
        sc.register_device(pump)
        # pool (export + own-draw add-back, under the solar cap) covers the pump
        await sc.update(2400.0, price_level="normal")
        pump.deactivate.assert_not_awaited()

    async def test_marginal_shortfall_within_hysteresis_keeps_running(self, mock_hass):
        """A shortfall smaller than the 100 W LIFO threshold must not flap the
        load off — the hysteresis band survives the fix."""
        sc = SurplusController(mock_hass)
        pump = _mock(device_id="pump", draw=2000.0, min_power=2000.0,
                     is_active=True, daily_targets_met=True)
        sc.register_device(pump)
        # distributable = 1980 − 50 offset = 1930; debit 2000 → −70 > −100
        await sc.update(1980.0, price_level="normal")
        pump.deactivate.assert_not_awaited()

    async def test_lowest_priority_is_shed_first(self, mock_hass):
        """Two running loads, pool funds only one → LIFO takes the LOWER
        priority; the higher-priority load survives."""
        sc = SurplusController(mock_hass)
        pump = _mock(device_id="pump", name="Pump", priority=1,
                     draw=2000.0, min_power=2000.0, is_active=True)
        heater = _mock(device_id="heater", name="Heater", priority=8,
                       draw=1000.0, min_power=1000.0, is_active=True)
        sc.register_device(pump)
        sc.register_device(heater)
        # pool 2500 (−50 offset) funds the pump but not both
        await sc.update(2500.0, price_level="normal")
        heater.deactivate.assert_awaited()
        pump.deactivate.assert_not_awaited()


@pytest.mark.asyncio
class TestTier1AssistFundsRunningLoad:
    """#620 Tier-1 semantics survive the debit: while the battery may assist,
    its share never counts as a deficit."""

    async def test_assist_covers_shortfall_keeps_running(self, mock_hass):
        """Solar+battery device below its floor: the battery covers the gap
        down to the Buffer SoC — no shed."""
        sc = SurplusController(mock_hass)
        d = _mock(device_id="hp", draw=2000.0, min_power=2000.0,
                  is_active=True, battery_assist_enabled=True,
                  daily_targets_met=False)
        sc.register_device(d)
        await sc.update(500.0, price_level="normal",
                        battery_soc=80.0, battery_buffer_soc=40.0,
                        battery_reserve_soc=20.0,
                        battery_assist_budget_w=3000.0)
        d.deactivate.assert_not_awaited()

    async def test_assist_stands_down_past_floor(self, mock_hass):
        """(#688 contract) Past the daily floor only FREE surplus extends the
        run — the battery stops paying, so the load stops with the sun."""
        sc = SurplusController(mock_hass)
        d = _mock(device_id="hp", draw=2000.0, min_power=2000.0,
                  is_active=True, battery_assist_enabled=True,
                  daily_targets_met=True)
        sc.register_device(d)
        await sc.update(500.0, price_level="normal",
                        battery_soc=80.0, battery_buffer_soc=40.0,
                        battery_reserve_soc=20.0,
                        battery_assist_budget_w=3000.0)
        d.deactivate.assert_awaited()

    async def test_assist_unavailable_below_buffer(self, mock_hass):
        """Below the Buffer SoC the battery never assists — unfunded load stops."""
        sc = SurplusController(mock_hass)
        d = _mock(device_id="hp", draw=2000.0, min_power=2000.0,
                  is_active=True, battery_assist_enabled=True,
                  daily_targets_met=False)
        sc.register_device(d)
        await sc.update(500.0, price_level="normal",
                        battery_soc=30.0, battery_buffer_soc=40.0,
                        battery_reserve_soc=20.0,
                        battery_assist_budget_w=3000.0)
        d.deactivate.assert_awaited()


@pytest.mark.asyncio
class TestActiveDrawDebited:
    """The walk must debit a running load's draw before offering the pool to
    lower-priority devices — the over-allocation sibling of the same root."""

    async def test_lower_priority_does_not_double_spend(self, mock_hass):
        sc = SurplusController(mock_hass)
        pump = _mock(device_id="pump", priority=1, draw=2000.0,
                     min_power=2000.0, is_active=True)
        heater = _mock(device_id="heater", priority=8, draw=1000.0,
                       min_power=1000.0, is_active=False)
        sc.register_device(pump)
        sc.register_device(heater)
        # pool 2450 after offset: pump holds 2000 → only 450 left; the heater
        # (needs 1000) must NOT be switched on against power already spent
        await sc.update(2500.0, price_level="normal")
        heater.activate.assert_not_awaited()

    async def test_forced_loads_stay_exempt_from_the_lifo(self, mock_hass):
        """A Tier-2 overnight load runs off the battery by design: the debit
        pulls the pool negative at night, but the LIFO still must not touch
        the forced load itself (its lifecycle has its own terms)."""
        sc = SurplusController(mock_hass)
        d = _mock(device_id="hw", draw=1500.0, min_power=1500.0,
                  is_active=True, _batt_overnight_forced=True,
                  battery_eligible_overnight=True, remaining_sec=3600)
        import homeassistant.util.dt as dt_util
        d._batt_overnight_forced_date = dt_util.now().date()
        sc.register_device(d)
        await sc.update(0.0, price_level="normal",
                        battery_soc=80.0, battery_buffer_soc=40.0,
                        battery_reserve_soc=20.0, is_night=True)
        d.deactivate.assert_not_awaited()
