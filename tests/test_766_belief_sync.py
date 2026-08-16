"""#766 — SEM's belief about a load follows the switch, every cycle.

N2 (.175): the pool pump's planned valley block started it at 00:00 — and
SEM never stopped it (ran to 07:50), because ``is_active`` is a BELIEF
(``_status.state``) that only ``activate()``/``deactivate()`` and the
one-shot ``adopt_if_running()`` at registration ever update. A switch
turning ON later — an external actuator, a user's hand, a box self-start
— is invisible: never seen active, never deactivated, runtime never
accrued, and the #755 recorder honestly wrote ``measured: false`` for a
2-hour run it could not see.

The fix is the per-cycle twin of ``adopt_if_running``: every update, each
on/off-domain load syncs belief to observation. Strictly on/off domains —
``observed_on``'s climate fallthrough returns True for any mode string,
and a charger's current-control number ("6.0") must never read as ON.
"""
from __future__ import annotations

from unittest.mock import MagicMock, Mock

import pytest

from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode, DeviceState, SwitchDevice,
)


def _dev(entity_id="input_boolean.pool", state="on", believes_active=False):
    d = SwitchDevice.__new__(SwitchDevice)
    d.hass = MagicMock()
    st = Mock()
    st.state = state
    d.hass.states.get = Mock(return_value=st if state is not None else None)
    d.entity_id = entity_id
    d.name = "Pool"
    d.rated_power = 1500.0
    # (#779) The pool pump is a SURPLUS load — that is the mode under which
    # adopting an external ON *with ownership* is the right call, and the
    # only one. This fake predates the gate and skipped __init__, so it had
    # no mode at all.
    d.control_mode = DeviceControlMode.SURPLUS
    # minimal status scaffolding
    from custom_components.solar_energy_management.devices.base import DeviceStatus
    d._status = DeviceStatus(state=(DeviceState.ACTIVE if believes_active
                                    else DeviceState.IDLE))
    d._sem_owned = believes_active
    d._last_activated = None
    d._last_deactivated = None
    return d


class TestBeliefFollowsTheSwitch:

    def test_an_external_on_is_adopted(self):
        d = _dev(state="on", believes_active=False)
        changed = d.sync_belief_to_observation()
        assert changed is True
        assert d.is_active is True

    def test_an_external_off_releases_the_belief(self):
        d = _dev(state="off", believes_active=True)
        changed = d.sync_belief_to_observation()
        assert changed is True
        assert d.is_active is False

    def test_agreement_is_a_noop(self):
        d = _dev(state="on", believes_active=True)
        assert d.sync_belief_to_observation() is False
        d2 = _dev(state="off", believes_active=False)
        assert d2.sync_belief_to_observation() is False

    def test_an_unreadable_entity_leaves_the_belief_alone(self):
        d = _dev(state="unavailable", believes_active=True)
        assert d.sync_belief_to_observation() is False
        assert d.is_active is True

    def test_a_non_onoff_domain_never_syncs(self):
        """A charger's current number reads "6.0" — observed_on's climate
        fallthrough would call that ON. The sync must refuse the domain."""
        d = _dev(entity_id="number.wallbox_current", state="6.0",
                 believes_active=False)
        assert d.sync_belief_to_observation() is False
        assert d.is_active is False
