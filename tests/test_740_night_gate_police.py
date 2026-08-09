"""The night gate skips participation, not supervision (#740's night sibling).

The #193 gate `continue`s chargers whose mode opts out of night charging
(`off`, `solar_only`) in NIGHT_CHARGING_ACTIVE / TARIFF_WAITING_FOR_CHEAP
— before the adapter, the reconciler, decide() or actuate() ever run for
that charger. "Skip" silently meant "no supervision": a KEBA that
auto-starts masterless at night (the exact #740 war, live on PROD
08.08.2026) draws unpoliced until a day state returns, because the one
component whose job is stopping rogue sessions — the reconciler — is
gated out with the budget.

This is the recurring class (gate-blocks-activation-but-doesn't-stop-
the-running-device, 5th sighting — see docs/BUG_CLASSES.md): the gate
must withhold the night BUDGET, not the policing. An opted-out charger
now gets a minimal reconcile pass (OFF for `off`, IDLE for `solar_only`)
before the `continue` — drawing converges to DISABLE, idle emits nothing.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.ev_control import (
    EVControlMixin,
)


class _RecordingAdapter:
    """The hardware boundary: real reconciler above, recorder below."""

    def __init__(self, device):
        self._device = device
        self.disables = 0
        self.currents: list[int] = []

    def actual_charging(self, power) -> bool:
        return float(getattr(power, "power_w", 0.0) or 0.0) > 500

    def is_self_charging(self, power) -> bool:
        return False

    async def command_disable(self):
        self.disables += 1

    async def command_current(self, amps):
        self.currents.append(amps)


def _make_coord(cid: str, draw_w: float):
    coord = EVControlMixin.__new__(EVControlMixin)
    coord.hass = MagicMock()
    coord._charger_adapters = {}
    coord._charger_reconcilers = {}
    ev_dev = SimpleNamespace(_current_setpoint=0)
    adapter = _RecordingAdapter(ev_dev)
    coord._charger_adapters[cid] = adapter
    power = SimpleNamespace(
        ev_power=draw_w,
        ev_power_per_charger={cid: draw_w},
        ev_connected_per_charger={cid: True},
        ev_charging_per_charger={cid: draw_w > 500},
        ev_connected=True,
        ev_charging=draw_w > 500,
    )
    return coord, ev_dev, adapter, power


class TestTheGateStillPolices:
    def test_a_drawing_off_charger_is_stopped(self):
        """Mode `off`, box auto-started at 3 kW during another charger's
        night window: the police pass must open the contactor."""
        coord, ev_dev, adapter, power = _make_coord("b", 3000.0)

        asyncio.run(coord._police_opted_out_charger(
            "b", ev_dev, {"id": "b", "charge_mode": "off"}, power,
        ))

        assert adapter.disables == 1

    def test_a_rogue_start_on_solar_only_is_stopped(self):
        """`solar_only` at night has no surplus to wait for — a fresh
        draw is a rogue self-start and gets the #552 immediate DISABLE."""
        coord, ev_dev, adapter, power = _make_coord("b", 4100.0)

        asyncio.run(coord._police_opted_out_charger(
            "b", ev_dev, {"id": "b", "charge_mode": "solar_only"}, power,
        ))

        assert adapter.disables == 1

    def test_an_idle_charger_is_left_alone(self):
        """Converged means silent — the reconciler's spam-fix contract
        holds on the police path too (no churn against the quota-hold,
        which leaves the box enabled but suspended at 0 W)."""
        coord, ev_dev, adapter, power = _make_coord("b", 0.0)

        asyncio.run(coord._police_opted_out_charger(
            "b", ev_dev, {"id": "b", "charge_mode": "off"}, power,
        ))

        assert adapter.disables == 0
        assert adapter.currents == []

    def test_the_reconciler_is_cached_like_the_loop_does(self):
        """One reconciler per charger for its lifetime — it holds
        transition state (idle grace, enable backoff)."""
        coord, ev_dev, adapter, power = _make_coord("b", 3000.0)

        asyncio.run(coord._police_opted_out_charger(
            "b", ev_dev, {"id": "b", "charge_mode": "off"}, power,
        ))
        first = coord._charger_reconcilers["b"]
        asyncio.run(coord._police_opted_out_charger(
            "b", ev_dev, {"id": "b", "charge_mode": "off"}, power,
        ))

        assert coord._charger_reconcilers["b"] is first

    def test_a_charger_without_its_own_reading_uses_the_fleet_fallback(self):
        """Single-charger setups have no per-charger dict — the fleet
        sum IS this charger's draw (build_view's own resolution)."""
        coord, ev_dev, adapter, power = _make_coord("b", 0.0)
        power.ev_power_per_charger = {}
        power.ev_power = 3000.0

        asyncio.run(coord._police_opted_out_charger(
            "b", ev_dev, {"id": "b", "charge_mode": "off"}, power,
        ))

        assert adapter.disables == 1


class TestTheGateCallsThePolice:
    """Source pin: the #193 night gate must run the police pass before
    its `continue` — the fix is structural, not a test-side emulation."""

    def test_the_night_gate_polices_before_continue(self):
        src = Path(__file__).resolve().parent.parent.joinpath(
            "coordinator", "coordinator.py",
        ).read_text()
        gate = re.search(
            r"if not self\._mode_allows_night_charging\(per_cfg\):"
            r"(.{0,1200}?)continue",
            src, re.DOTALL,
        )
        assert gate, "the #193 night gate block has moved — update this pin"
        assert "_police_opted_out_charger" in gate.group(1), (
            "the night gate continues without policing the opted-out "
            "charger — the #740 night sibling is back"
        )
