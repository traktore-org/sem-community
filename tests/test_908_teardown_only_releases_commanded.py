"""#908 — removing SEM must not switch off a load SEM never commanded on.

markusschloesser installed SEM in **observer mode** to watch what it would do,
then removed the integration. Within four seconds HA logged explicit
``homeassistant.turn_off`` calls against five real Shelly relays — his fridge,
freezer, dishwasher, dryer and studio — none of which SEM had ever turned on,
and all of which were physically ON before SEM ran.

The mechanism is the #656 teardown release (``deactivate_devices``), added to
clear loads SEM had *commanded* on so a boosted heat pump / SG-Ready relay
does not strand when SEM goes away. It released every ``is_active`` device
with no ownership gate at all — so it also switched off loads SEM had merely
*adopted* (an external ON claimed under Surplus) or was only *observing*. That
is ledger class 17's own lesson (instance 7, #847): *a stop path must be able
to see whether the load is actually SEM's before it acts on it.*

The fix gives teardown the same ``_sem_commanded`` gate every other stop path
uses. SEM releases what it commanded; it leaves the user's own loads exactly
as they are. In observer mode SEM commands nothing, so removal is a no-op.

Real ``SwitchDevice`` objects here, not mocks: the whole bug is in what
``_sem_commanded`` reads as after an *adoption* vs an *activation*, and a mock
would paper over exactly that.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    deactivate_devices,
)
from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode,
    DeviceState,
    SwitchDevice,
)


def _switch(entity_id="switch.freezer", state="on"):
    """A physically-ON Shelly relay, exposed to SEM as a SwitchDevice."""
    hass = MagicMock()
    st = Mock()
    st.state = state
    hass.states.get = Mock(return_value=st)
    hass.services.async_call = AsyncMock()
    d = SwitchDevice(
        hass=hass,
        device_id=entity_id.split(".", 1)[1],
        name=entity_id.split(".", 1)[1].title(),
        rated_power=150.0,
        entity_id=entity_id,
    )
    d.control_mode = DeviceControlMode.SURPLUS
    return d


@pytest.mark.unit
class TestTeardownOnlyReleasesCommanded908:
    @pytest.mark.asyncio
    async def test_adopted_external_load_is_left_on(self):
        """markusschloesser's freezer: ON before SEM, adopted under Surplus so
        goal gates *could* stop it — but SEM never commanded it. Removal must
        not touch it."""
        freezer = _switch("switch.freezer")
        # The per-cycle belief sync adopts an observed-ON switch: belief goes
        # active and (under Surplus) ownership is claimed — but NOT commanded.
        assert freezer.sync_belief_to_observation() is True
        assert freezer.is_active is True
        assert freezer._sem_owned is True, "adopted under Surplus"
        assert freezer._sem_commanded is False, "SEM never issued the ON"

        stopped = await deactivate_devices([freezer], "integration removed")

        assert stopped == 0
        freezer.hass.services.async_call.assert_not_awaited()
        assert freezer.is_active is True, "the freezer stays on"

    @pytest.mark.asyncio
    async def test_commanded_load_is_still_released(self):
        """The #656 strand SEM *did* start — a forced boost — is still cleared,
        so the fix does not re-open the leak it closed."""
        boost = _switch("switch.hot_water_boost", state="off")
        boost.record_activated()               # SEM issued the ON (choke point)
        boost._status.state = DeviceState.ACTIVE
        boost.min_on_seconds = 0               # past the anti-flicker window
        assert boost.is_active is True
        assert boost._sem_commanded is True

        stopped = await deactivate_devices([boost], "integration removed")

        assert stopped == 1
        boost.hass.services.async_call.assert_awaited_once()
        args = boost.hass.services.async_call.await_args.args
        assert args[0] == "homeassistant" and args[1] == "turn_off"

    @pytest.mark.asyncio
    async def test_observer_install_releases_nothing(self):
        """The reporter's exact case: observer mode, so nothing was ever
        commanded. A mixed teardown touches none of the loads."""
        loads = [
            _switch("switch.kuhlmess"),
            _switch("switch.freezer"),
            _switch("switch.studio"),
            _switch("switch.trockner"),
            _switch("switch.spulmaschine"),
        ]
        for d in loads:
            d.sync_belief_to_observation()          # all adopted, none commanded
            assert d.is_active and not d._sem_commanded

        stopped = await deactivate_devices(loads, "integration removed")

        assert stopped == 0
        for d in loads:
            d.hass.services.async_call.assert_not_awaited()
            assert d.is_active is True
