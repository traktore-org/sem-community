"""#523 (RienduPre, Nibe SG-Ready) — relay map matches the SG-Ready standard.

The old SG_READY_RELAY_MAP was a plain 2-bit count (00/01/10/11) that did NOT
match the SG-Ready standard truth table — so SEM's BOOST drove (1,0), which a
standard Nibe reads as EVU-block, turning the pump OFF on surplus instead of on
("the heat pump never got turned on"). The standard map is universal across EMS
vendors (alpha innotec / gridX / SMA / SolarEdge). This pins the corrected map.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.devices.heat_pump_controller import (
    HeatPumpController, SGReadyState, SG_READY_RELAY_MAP,
)


def _hass():
    h = MagicMock()
    h.services = MagicMock()
    h.services.async_call = AsyncMock()
    h.states = MagicMock()
    h.states.get = MagicMock(return_value=None)
    return h


def _hp(**kw):
    return HeatPumpController(
        hass=_hass(),
        relay1_entity_id="switch.sg_ready_a",
        relay2_entity_id="switch.sg_ready_b",
        **kw,
    )


@pytest.mark.unit
class TestStandardTruthTable:
    def test_map_matches_sg_ready_standard(self):
        # input1:input2, True = closed/active
        assert SG_READY_RELAY_MAP[SGReadyState.BLOCKED] == (True, False)   # 1:0
        assert SG_READY_RELAY_MAP[SGReadyState.NORMAL] == (False, False)   # 0:0
        assert SG_READY_RELAY_MAP[SGReadyState.BOOST] == (False, True)     # 0:1
        assert SG_READY_RELAY_MAP[SGReadyState.FORCE_ON] == (True, True)   # 1:1

    @pytest.mark.asyncio
    async def test_boost_does_not_block_the_pump(self):
        """The core RienduPre bug: BOOST must NOT drive the EVU-block pattern."""
        hp = _hp()
        await hp._set_sg_ready_state(SGReadyState.BOOST)
        by_entity = {}
        for c in hp.hass.services.async_call.await_args_list:
            by_entity[c.args[2]["entity_id"]] = c.args[1]
        # BOOST standard = (A off, B on): A=turn_off, B=turn_on
        assert by_entity["switch.sg_ready_a"] == "turn_off"
        assert by_entity["switch.sg_ready_b"] == "turn_on"

    @pytest.mark.asyncio
    async def test_normal_is_both_open(self):
        hp = _hp()
        await hp._set_sg_ready_state(SGReadyState.NORMAL)
        by_entity = {c.args[2]["entity_id"]: c.args[1]
                     for c in hp.hass.services.async_call.await_args_list}
        assert by_entity["switch.sg_ready_a"] == "turn_off"
        assert by_entity["switch.sg_ready_b"] == "turn_off"

    @pytest.mark.asyncio
    async def test_force_on_closes_both(self):
        hp = _hp()
        await hp._set_sg_ready_state(SGReadyState.FORCE_ON)
        by_entity = {c.args[2]["entity_id"]: c.args[1]
                     for c in hp.hass.services.async_call.await_args_list}
        assert by_entity["switch.sg_ready_a"] == "turn_on"
        assert by_entity["switch.sg_ready_b"] == "turn_on"
