"""#827 follow-up — the System Work Mode writes must be idempotent.

``actuate_battery`` re-issues ``FORCE_DISCHARGE`` on EVERY coordinator cycle
(~10-30 s) for as long as the spend decision holds, which can be hours. The
first #827 build always wrote, so a Deye owner in a long spend window got the
same Modbus-backed ``select_option`` re-issued every cycle for the whole
window.

That is bug class #538 — "rewriting the same modbus register every cycle →
transaction-ID collisions" — and this adapter's own siblings already guard
against it: ``command_force_charge`` documents that a re-issue is a no-op,
and ``command_stop_force_charge`` returns early because "a repeat is pure
cost". The Huawei adapter is blunter still: "re-hammering the inverter blocks
the LUNA2000".

Also pinned here: the stop must not discard the captured prior mode until the
restore write has actually landed. Clearing it first means one failed write
permanently forgets the user's real configuration (e.g. Zero Export To CT)
and silently downgrades them to Zero Export To Load forever.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from custom_components.solar_energy_management.coordinator.battery_adapters.deye import (
    DeyeBatteryAdapter,
)

OPTIONS = ["Selling First", "Zero Export To Load", "Zero Export To CT"]


def _hass_with_select(options, current="Zero Export To Load"):
    hass = MagicMock()
    st = MagicMock()
    st.state = current
    st.attributes = {"options": list(options)}
    hass.states.get.return_value = st
    hass.services.async_call = AsyncMock()
    return hass


def _cfg(**over):
    cfg = {
        "battery_platform": "deye",
        "deye_system_work_mode_control": True,
        "deye_system_work_mode_entity": "select.deye_system_work_mode",
        "deye_system_work_mode_selling_option": "Selling First",
        "deye_system_work_mode_zero_load_option": "Zero Export To Load",
        "deye_system_work_mode_zero_ct_option": "Zero Export To CT",
    }
    cfg.update(over)
    return cfg


def _adapter(hass=None, cfg=None):
    a = DeyeBatteryAdapter(hass or _hass_with_select(OPTIONS), cfg or _cfg())
    a._observer_mode = False
    a._actuation_enabled = True
    return a


class TestForceDischargeIsIdempotent:
    def test_repeat_while_already_selling_writes_nothing(self):
        """The spend window holds for hours; the write must happen once."""
        hass = _hass_with_select(OPTIONS, current="Zero Export To CT")
        a = _adapter(hass=hass)
        a._write_and_verify = AsyncMock(return_value=True)

        assert asyncio.run(a.command_force_discharge(3000.0, floor_soc=20.0))
        assert a._write_and_verify.await_count == 1

        # The inverter is now in Selling First — every later cycle re-asks.
        hass.states.get.return_value.state = "Selling First"
        for _ in range(5):
            assert asyncio.run(a.command_force_discharge(3000.0, floor_soc=20.0))

        assert a._write_and_verify.await_count == 1, (
            "re-issuing the same select every cycle is bug class #538"
        )

    def test_a_repeat_still_reports_success(self):
        """A no-op is a satisfied intent, not a failure — the caller must not
        read it as 'the adapter cannot sell' and drop the decision."""
        hass = _hass_with_select(OPTIONS, current="Selling First")
        a = _adapter(hass=hass)
        a._write_and_verify = AsyncMock(return_value=True)
        assert asyncio.run(a.command_force_discharge(3000.0, floor_soc=20.0)) is True
        assert a._write_and_verify.await_count == 0

    def test_a_mode_knocked_off_selling_is_rewritten(self):
        """Idempotence must not become blindness: if something else moved the
        inverter out of Selling First mid-window, SEM writes again."""
        hass = _hass_with_select(OPTIONS, current="Selling First")
        a = _adapter(hass=hass)
        a._write_and_verify = AsyncMock(return_value=True)
        asyncio.run(a.command_force_discharge(3000.0, floor_soc=20.0))
        hass.states.get.return_value.state = "Zero Export To Load"
        asyncio.run(a.command_force_discharge(3000.0, floor_soc=20.0))
        assert a._write_and_verify.await_count == 1


class TestStopIsIdempotentAndKeepsThePrior:
    def test_repeat_stop_while_already_restored_writes_nothing(self):
        hass = _hass_with_select(OPTIONS, current="Zero Export To CT")
        a = _adapter(hass=hass)
        a._write_and_verify = AsyncMock(return_value=True)
        asyncio.run(a.command_force_discharge(3000.0, floor_soc=20.0))
        hass.states.get.return_value.state = "Selling First"
        asyncio.run(a.command_stop_force_discharge())
        writes_after_stop = a._write_and_verify.await_count

        hass.states.get.return_value.state = "Zero Export To CT"
        for _ in range(3):
            asyncio.run(a.command_stop_force_discharge())
        assert a._write_and_verify.await_count == writes_after_stop

    def test_a_failed_restore_keeps_the_prior_for_the_retry(self):
        """Clearing the prior before the write lands loses the user's real
        configuration permanently on one transient failure."""
        hass = _hass_with_select(OPTIONS, current="Zero Export To CT")
        a = _adapter(hass=hass)
        a._write_and_verify = AsyncMock(return_value=True)
        asyncio.run(a.command_force_discharge(3000.0, floor_soc=20.0))

        hass.states.get.return_value.state = "Selling First"
        a._write_and_verify = AsyncMock(return_value=False)   # the write fails
        assert asyncio.run(a.command_stop_force_discharge()) is False

        a._write_and_verify = AsyncMock(return_value=True)    # retry succeeds
        assert asyncio.run(a.command_stop_force_discharge()) is True
        assert a._write_and_verify.await_args_list[-1].args[1] == "Zero Export To CT", (
            "a transient failure must not downgrade the user to Zero Export To Load"
        )
