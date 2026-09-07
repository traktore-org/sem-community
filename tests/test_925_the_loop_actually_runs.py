"""(#925) The per-charger loop, executed — not inspected.

Nine of the eleven bugs found on real hardware in September live inside
``_async_update_data``'s per-charger loop, and no test has ever run it.
The loop is reached only when ``self._ev_devices`` is non-empty, and the
one file that executes the cycle (#873) configures no chargers.

These tests are deliberately about REACH, not about clever assertions:
each one proves a specific piece of machinery is now executed, so a
regression in it can be seen at all. Depth comes after reach — a sharp
assertion over code that never runs is the thing this arc exists to stop.
"""

from __future__ import annotations

import pytest

from .cycle_rig import CycleRig

WIRED = {
    "solar_production_sensor": "sensor.solar",
    "grid_power_sensor": "sensor.grid",
    "battery_power_sensor": "sensor.batt",
    "battery_soc_sensor": "sensor.soc",
    "ev_power_sensor": "sensor.ev",
    "battery_capacity_kwh": 15.0,
    "battery_reserve_soc": 20,
}

CHARGER = {
    "id": "keba1",
    "name": "KEBA P30",
    "ev_min_current": 6,
    "ev_max_current": 16,
    "ev_phases": 3,
    "ev_voltage": 230,
    "charger_service": "keba.set_current",
    "ev_power_sensor": "sensor.ev",
    "charge_mode": "solar_only",
}


def _states(**over):
    s = {"sensor.solar": 5000, "sensor.grid": 2000, "sensor.batt": 0,
         "sensor.soc": 60, "sensor.ev": 0}
    s.update(over)
    return s


@pytest.mark.asyncio
class TestTheLoopIsReached:

    async def test_a_configured_charger_gives_the_cycle_a_loop_to_run(self):
        """The precondition everything else depends on. ``_ev_devices`` must
        be populated with a REAL device — #873 has none, so its cycle skips
        the loop entirely and every September bug with it."""
        rig = CycleRig(config=dict(WIRED), chargers=[CHARGER],
                       states=_states())
        assert rig.coord._ev_devices, "no charger — the loop cannot run"
        dev = rig.coord._ev_devices["keba1"]
        # A MagicMock would answer truthily to every one of these and route
        # to the KEBA adapter no matter what the config said.
        assert dev.charger_service == "keba.set_current"
        assert dev.min_current == 6 and dev.max_current == 16
        assert isinstance(dev.charger_service, str)

    async def test_the_cycle_completes_with_a_charger_wired(self):
        """A whole real turn, chargers included. If this raises, nothing
        below it means anything."""
        rig = CycleRig(config=dict(WIRED), chargers=[CHARGER],
                       states=_states())
        result = await rig.tick()
        assert isinstance(result, dict) and result, "the cycle produced nothing"

    async def test_the_durable_per_charger_state_exists_and_persists(self):
        """``_pcc_store`` is created by the real ``__init__`` and is where
        the redirect veto's strikes and the phase tick's timers live. The
        YAML harness's ``__new__``-built coordinator has no such attribute,
        which is precisely why those three bugs are unreplayable there.

        Persistence across cycles is the load-bearing half: a rig that
        rebuilt the coordinator each turn would show zero strikes forever
        and look perfectly green while observing nothing."""
        rig = CycleRig(config=dict(WIRED), chargers=[CHARGER],
                       states=_states())
        await rig.tick()
        st = rig.charger_state("keba1")
        assert st is not None, (
            "no PerChargerState for a configured charger — the redirect "
            "veto (#899) and the phase tick have nowhere to count")
        first = id(st)
        await rig.tick()
        assert id(rig.charger_state("keba1")) == first, (
            "the per-charger state was rebuilt between cycles — anything "
            "that counts (strikes, blink cycles, gap timers) can never "
            "reach its threshold, and every such guard silently passes")

    async def test_many_cycles_run_on_one_coordinator(self):
        """The other half of the same property, at the cycle level."""
        rig = CycleRig(config=dict(WIRED), chargers=[CHARGER],
                       states=_states())
        for _ in range(4):
            await rig.tick()
        assert len(rig.results) == 4
        assert all(isinstance(r, dict) for r in rig.results)
