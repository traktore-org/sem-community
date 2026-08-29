"""#820 — the branch's merge justification, proven at the wire (audit F4).

`paced_charge_cap_w` runs every cycle by design (recording-only). The ONE
line standing between its computed cap and a live `number.set_value` write
is `cap = decision.cap_w if (decision and enabled) else None` inside
`_run_charge_pacing` — and no test exercised that method. These do, with a
day the pacer genuinely wants to act on (a real decision, a configured
limit entity), asserting the wire stays silent while the flag is off — and,
so the test can discriminate, that the SAME day writes when it is on.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)


def _ledger(hours=8, solar_w=6800.0, home_w=800.0):
    t0 = datetime(2026, 8, 25, 8, 0)
    return [SimpleNamespace(
        start=t0 + timedelta(hours=i), end=t0 + timedelta(hours=i + 1),
        hours=1.0, soc_kwh=6.0, home_batt_kwh=0.0, solar_w=float(solar_w),
        cap_override_w=max(0.0, solar_w - home_w), grid_committed_w=0.0,
    ) for i in range(hours)]


def _coordinator(enabled: bool):
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states.get = MagicMock(return_value=SimpleNamespace(state="5000"))
    cfg = {
        "battery_charge_pacing_enabled": enabled,
        "battery_charge_power_limit_entity": "number.batt_charge_limit",
        "battery_max_target_soc": 100.0,
        "inverter_ac_limit_w": 20000.0,
        "battery_max_charge_power_w": 10000.0,
    }
    fake = SimpleNamespace(
        hass=hass,
        config=cfg,
        data={"battery_soc": 40.0},
        battery_capacity_kwh=21.0,
        _planning_evidence={"forecast_trust_d1": 0.9},
        _observer_mode=False,
        _charge_pacing_writer=None,
        _today_pacing_ledger=lambda: _ledger(),
    )
    return fake, hass


@pytest.mark.asyncio
class TestPacingInertUntilEnabled:
    async def test_flag_off_never_touches_the_wire(self):
        fake, hass = _coordinator(enabled=False)
        await SEMCoordinator._run_charge_pacing(fake)
        hass.services.async_call.assert_not_awaited()
        # ...while the recording half still worked: a real decision published.
        assert fake._charge_pacing_state["enabled"] is False
        assert fake._charge_pacing_state["cap_w"] is not None, (
            "the pacer had a real day to act on — if this is None the "
            "test went inert itself and proves nothing"
        )
        assert fake._charge_pacing_state["action"] == "idle"

    async def test_same_day_with_flag_on_writes(self):
        """The discriminator: identical inputs, flag on → the wire moves.
        Without this, the flag-off test would also pass on a pacer that
        simply never writes at all."""
        fake, hass = _coordinator(enabled=True)
        await SEMCoordinator._run_charge_pacing(fake)
        hass.services.async_call.assert_awaited()
        call = hass.services.async_call.await_args
        assert call.args[0] == "number" and call.args[1] == "set_value"
        assert call.args[2]["entity_id"] == "number.batt_charge_limit"
        assert fake._charge_pacing_state["action"] == "wrote"

    async def test_observer_outranks_the_flag(self):
        fake, hass = _coordinator(enabled=True)
        fake._observer_mode = True
        await SEMCoordinator._run_charge_pacing(fake)
        hass.services.async_call.assert_not_awaited()
        assert fake._charge_pacing_state["action"] == "observer"
