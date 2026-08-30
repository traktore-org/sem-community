"""#820 — charge pacing sized the day from LAST cycle's SOC, and from 0 % on
every restart.

Found by an independent review of the v2.0.0..develop diff (30.08.2026).

``_run_charge_pacing`` read ``self.data.get("battery_soc")``.
``self.data`` is HA's ``DataUpdateCoordinator`` attribute, and it is
reassigned only AFTER ``_async_update_data()`` returns — while pacing runs
INSIDE that method. So every cycle sized the pack's fill against the
previous cycle's SOC, with the current one sitting unused two frames up the
stack.

Worse at the boundary that matters: on the first cycle after any restart
``self.data`` is still ``_get_initial_data()``'s default dataclass, whose
``battery_soc`` is ``0.0``. So the first pacing decision after every restart
was computed against a battery reading of 0 %, whatever the pack really held
— and 0 % reads as "empty, fill it as fast as you can", the exact opposite
of pacing.

The fix hands the cycle's own ``power`` to the pacer, the way every other
consumer in the cycle already receives it.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)


def _coord(stale_soc, config=None):
    coord = SEMCoordinator.__new__(SEMCoordinator)
    coord.config = {"battery_capacity_kwh": 15.0, **(config or {})}
    coord.data = {"battery_soc": stale_soc}
    coord._planning_evidence = {}
    coord.hass = SimpleNamespace(states=SimpleNamespace(get=lambda *_: None))
    coord._observer_mode = True
    return coord


class TestPacingUsesTheCurrentCycle:
    @pytest.mark.asyncio
    async def test_this_cycles_soc_wins_over_the_published_one(self):
        """The published value is one cycle old by construction."""
        coord = _coord(stale_soc=10.0)
        await SEMCoordinator._run_charge_pacing(
            coord, SimpleNamespace(battery_soc=88.0))
        state = getattr(coord, "_charge_pacing_state", None) or {}
        assert state.get("soc") == pytest.approx(88.0), (
            "pacing sized the day from the PREVIOUS cycle's SOC while this "
            "cycle's reading was available to it"
        )

    @pytest.mark.asyncio
    async def test_the_first_cycle_after_a_restart_is_not_zero_percent(self):
        """``self.data`` starts as the default dataclass, battery_soc=0.0.
        A pacer told the pack is empty will not pace."""
        coord = _coord(stale_soc=0.0)
        await SEMCoordinator._run_charge_pacing(
            coord, SimpleNamespace(battery_soc=72.0))
        state = getattr(coord, "_charge_pacing_state", None) or {}
        assert state.get("soc") == pytest.approx(72.0)
        assert state.get("reason_code") != "no_soc"

    @pytest.mark.asyncio
    async def test_a_dark_soc_this_cycle_is_still_honest(self):
        """Rule 4 of the arc: an unknown input is not permission. A missing
        reading must say so rather than fall back to a stale number."""
        coord = _coord(stale_soc=55.0)
        await SEMCoordinator._run_charge_pacing(
            coord, SimpleNamespace(battery_soc=None))
        state = getattr(coord, "_charge_pacing_state", None) or {}
        assert state.get("soc") is None, (
            "an unknown SOC must be published as unknown, never quietly "
            "replaced by the previous cycle's number"
        )
        assert state.get("cap_w") is None, "and nothing may be paced on it"

    @pytest.mark.asyncio
    async def test_an_offline_soc_sensor_is_unknown_not_zero(self):
        """``PowerReadings.battery_soc`` is a plain ``float = 0.0`` with no
        sentinel — the twin flag ``battery_soc_unavailable`` carries the
        "sensor is dark" fact. Reading the number alone would reintroduce
        the very defect this argument removes, one layer along: a dark
        sensor sizing the day as an empty pack.
        """
        coord = _coord(stale_soc=80.0)
        await SEMCoordinator._run_charge_pacing(coord, SimpleNamespace(
            battery_soc=0.0, battery_soc_unavailable=True))
        state = getattr(coord, "_charge_pacing_state", None) or {}
        assert state.get("soc") is None, (
            "an offline SOC sensor reported 0 % — 'empty, fill fast', the "
            "exact reading pacing exists to avoid"
        )
        assert state.get("cap_w") is None

    @pytest.mark.asyncio
    async def test_a_genuine_zero_percent_is_still_a_reading(self):
        """A pack that really is flat must not be mistaken for a dark
        sensor — the flag is what separates them."""
        coord = _coord(stale_soc=80.0)
        await SEMCoordinator._run_charge_pacing(coord, SimpleNamespace(
            battery_soc=0.0, battery_soc_unavailable=False))
        state = getattr(coord, "_charge_pacing_state", None) or {}
        assert state.get("soc") == pytest.approx(0.0)
