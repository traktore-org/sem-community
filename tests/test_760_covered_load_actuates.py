"""#760 — a covered load inside its open block must actually start.

N1 (.175, 12→13.08): ``load:sim_heizband`` (2.0 kWh deficit,
battery-sourced) was packed 23:31–01:31, verdict fits, coverage COVERED,
is_night true, SOC 65 > reserve 30 — and the switch never turned on. Two
independent pathways failed: covered+in-block, and (after the #756
phantom displaced it) the plain uncovered reactive tier-2.

This is the in-process oracle in exactly the N1 shape. If it goes green
against the shipped controller, the live failure is in the layer above
(the coordinator's window plumbing or the rig) — either way, the property
"covered + in-block + every tier-2 gate green ⇒ the device starts" gets
pinned here so it can never regress silently again.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController, compute_load_intent,
)
from custom_components.solar_energy_management.coordinator.plan_verdict import (
    PlanVerdict,
)
from custom_components.solar_energy_management.devices.base import DeviceControlMode


def _heizband(**kw):
    """The N1 device, faithfully: 1 kW switch load, 2 h deficit,
    'Finish overnight from: Battery', idle since 17:54."""
    d = MagicMock()
    d.device_id = "sim_heizband"
    d.name = "Sim Heizband"
    d.priority = 2
    d.min_power_threshold = 800
    d.rated_power = 1000.0
    d.is_enabled = True
    d.managed_externally = False
    d.is_active = False
    d.device_type = MagicMock(value="switch")
    d.activate = AsyncMock(return_value=1000.0)
    d.adjust_power = AsyncMock(return_value=1000.0)
    d.get_current_consumption = MagicMock(return_value=0.0)
    d.can_activate = MagicMock(return_value=True)
    d.can_deactivate = MagicMock(return_value=True)
    d.record_activated = MagicMock()
    d.record_deactivated = MagicMock()
    d.reset_surplus_timer = MagicMock()
    d.status = MagicMock()
    d.control_mode = DeviceControlMode.SURPLUS
    d._sem_owned = False
    d.is_deadline_approaching = False
    d._offpeak_forced = False
    d._offpeak_forced_date = None
    d._batt_overnight_forced = False
    d._batt_overnight_forced_date = None
    d.needs_offpeak_activation = True
    d.has_runtime_deficit = True
    d.remaining_daily_runtime_sec = 7200
    d.daily_min_runtime_sec = 7200
    d._daily_runtime_accumulated_sec = 0
    d.daily_targets_met = False
    d.daily_max_runtime_reached = False
    d.stop_condition_met = False
    d.top_up_policy = "solar_only"
    d.battery_assist_enabled = False
    d.battery_eligible_overnight = True
    d.comfort_state = ""
    d.stop_entity = ""
    d.stop_at = 0

    async def _deact():
        d.is_active = False
    d.deactivate = AsyncMock(side_effect=_deact)
    for k, v in kw.items():
        setattr(d, k, v)
    return d


N1_KW = dict(
    # 23:40 on the rig: no sun, price level cheap, peak normal (defaults),
    # battery 65 % against a 30 % reserve — every tier-2 gate green.
    battery_soc=65, battery_reserve_soc=30, battery_buffer_soc=70,
    is_night=True, price_level="cheap",
)


@pytest.mark.asyncio
class TestTheN1Shape:

    async def test_covered_in_block_starts(self):
        """The plan said fits+COVERED with the block open. The device
        must start — a 'covered' that cannot start is a lie the card
        repeats all night."""
        sc = SurplusController(MagicMock())
        d = _heizband()
        sc.register_device(d)
        await sc.update(
            0.0, **N1_KW,
            plan_windows={"sim_heizband": PlanVerdict(
                in_block=True, reason="joint overnight plan: in planned block")},
        )
        d.activate.assert_called()

    async def test_uncovered_reactive_tier2_starts(self):
        """After the #756 phantom displaced the demand (yields →
        uncovered), the plain reactive tier-2 path owns the night and
        must start it too."""
        sc = SurplusController(MagicMock())
        d = _heizband()
        sc.register_device(d)
        await sc.update(0.0, **N1_KW, plan_windows={})
        d.activate.assert_called()

    async def test_a_hold_verdict_does_wait(self):
        """The inverse — blocks elsewhere tonight hold the start. Pinned
        so the two greens above are proven to come from the verdict, not
        from a controller that ignores plan_windows entirely."""
        sc = SurplusController(MagicMock())
        d = _heizband()
        sc.register_device(d)
        await sc.update(
            0.0, **N1_KW,
            plan_windows={"sim_heizband": PlanVerdict(
                hold=True, reason="joint overnight plan: blocks later")},
        )
        d.activate.assert_not_called()

    async def test_the_intent_alone_says_run(self):
        """The pure decision, isolated from the walk: covered in-block,
        every gate green → tier2_battery run."""
        d = _heizband()
        intent = compute_load_intent(
            d, remaining_surplus_w=0.0, soc_above_reserve=True,
            is_night=True, plan=PlanVerdict(in_block=True, reason="in block"),
        )
        assert intent.on, intent.reason
        assert intent.source == "tier2_battery"
