"""#1377 (beta.21 retest) — the reserve's "no" is read, not dropped.

With the operating mode already on "autonomous", a Powerwall charges from
the grid only with the permit ON and the backup reserve raised: the reserve
is what starts the charge. The reporter saw mode Autonomous, permit On and
the reserve still at 0 % while the Plan page said the battery charged.

``ChargeTargetHold.write`` answers False when it wrote nothing (a number it
cannot read, a record it cannot read or save, a lost old value). The join
dropped that answer: it turned the permit on, said "set: reserve, permit"
and counted a charge. Every later cycle took the joined branch, so the
reserve was never asked again for the whole block (class 192).

Now, for every select setup with a charge target (SEM cannot tell a
reserve from an upper limit, review):

* a target or a permit that cannot be read writes nothing and starts
  nothing; the next cycle asks again, with no record written meanwhile;
* a target the hold would not write ends the attempt: nothing is left on,
  the diagnostics say why, and the block's end (Off or a stop) clears it;
* the message names only what was written.

Twin: a select setup with no target is unchanged.
"""
from __future__ import annotations

import json

from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.charge_record import (
    ForcedChargeRecord,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.charge_target import (
    ChargeTargetHold,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
)

from .test_1377_powerwall_charge import (
    MODE, PERMIT, RESERVE, _adapter, _charge, _Hass, _stop, _Store,
)


class _BadStore(_Store):
    """A hold record that cannot be read: the hold writes no target."""

    async def async_load(self):
        raise OSError("disk")


def _running(store) -> dict:
    return json.loads(store.raw).get("running", {}) if store.raw else {}


class TestTheJoinReadsTheReserveFirst:
    async def test_an_unreadable_reserve_writes_and_saves_nothing(self):
        hass, rec = _Hass(mode="autonomous", reserve="unavailable"), _Store()
        a = _adapter(hass, rec, _Store())
        for _ in range(3):
            await actuate_battery(_charge(), a)
        assert hass.calls == [], "no permit without the reserve"
        assert rec.raw is None, "nothing saved while the reserve is out"
        assert a.last_error and RESERVE in a.last_error
        assert a.last_intent is not BatteryIntent.FORCE_CHARGE
        assert a._charge_adapter.is_active is False

    async def test_the_charge_starts_once_the_reserve_reads(self):
        hass = _Hass(mode="autonomous", reserve="unavailable")
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        hass.put(RESERVE, "0")
        await actuate_battery(_charge(), a)
        assert float(hass.read(RESERVE)) == 100
        assert hass.read(PERMIT) == "on"
        assert a.last_intent is BatteryIntent.FORCE_CHARGE
        assert a.last_error is None


class TestTheJoinReadsTheHoldsAnswer:
    async def test_a_reserve_the_hold_will_not_write_starts_nothing(self):
        hass, rec = _Hass(mode="autonomous", reserve="0"), _Store()
        a = _adapter(hass, rec, _BadStore())
        await actuate_battery(_charge(), a)
        assert hass.calls == [], "the permit is not turned on"
        assert hass.read(PERMIT) == "off"
        assert _running(rec) == {}, "no record is left behind"
        assert a._charge_adapter.is_active is False
        assert a.last_intent is not BatteryIntent.FORCE_CHARGE
        assert a.last_error and RESERVE in a.last_error

    async def test_the_attempt_is_given_up_not_retried_each_cycle(self):
        hass, rec = _Hass(mode="autonomous", reserve="0"), _Store()
        a = _adapter(hass, rec, _BadStore())
        await actuate_battery(_charge(), a)
        saved = rec.raw
        for _ in range(5):
            await actuate_battery(_charge(), a)
        assert hass.calls == []
        assert rec.raw == saved, "no record churn on later cycles"
        assert a._charge_adapter._sel_spent

    async def test_the_end_of_the_block_clears_the_attempt(self):
        hass = _Hass(mode="autonomous", reserve="0")
        a = _adapter(hass, _Store(), _BadStore())
        await actuate_battery(_charge(), a)
        assert a._charge_adapter._sel_spent
        await a.command_normal()
        assert not a._charge_adapter._sel_spent

    async def test_a_stop_clears_the_attempt_too(self):
        # blocks mostly end with STOP_FORCE_CHARGE, not with NORMAL
        hass = _Hass(mode="autonomous", reserve="0")
        a = _adapter(hass, _Store(), _BadStore())
        await actuate_battery(_charge(), a)
        assert a._charge_adapter._sel_spent
        await actuate_battery(_stop(), a)
        assert not a._charge_adapter._sel_spent
        assert hass.calls == [], "the stop writes nothing SEM never set"

    async def test_the_message_names_only_what_was_written(self):
        hass = _Hass(mode="autonomous", reserve="0")
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        assert a._last_charge_message.endswith("set: reserve, permit")
        mine = _Hass(mode="autonomous", reserve="0", permit="on")
        b = _adapter(mine, _Store(), _Store())
        await actuate_battery(_charge(), b)
        assert b._last_charge_message.endswith("set: reserve"), "the permit was the user's"
        no = _Hass(mode="autonomous", reserve="0")
        c = _adapter(no, _Store(), _BadStore())
        await actuate_battery(_charge(), c)
        assert "set:" not in (c._last_charge_message or "")
        assert "failed" in c._last_charge_message


class TestWritingTheModeWithAPermit:
    """The mode was self_consumption: SEM writes reserve, permit and mode.
    With a permit beside the select the reserve starts the charge too."""

    async def test_an_unreadable_reserve_writes_nothing(self):
        hass, rec = _Hass(reserve="unavailable"), _Store()
        a = _adapter(hass, rec, _Store())
        await actuate_battery(_charge(), a)
        assert hass.calls == []
        assert rec.raw is None
        assert a.last_error and RESERVE in a.last_error

    async def test_a_reserve_the_hold_will_not_write_writes_nothing(self):
        hass, rec = _Hass(reserve="0"), _Store()
        a = _adapter(hass, rec, _BadStore())
        await actuate_battery(_charge(), a)
        assert hass.calls == []
        assert hass.read(MODE) == "self_consumption"
        assert _running(rec) == {}
        assert a.last_intent is not BatteryIntent.FORCE_CHARGE


class TestOneRuleWithoutAPermit:
    """(review) The same setup must not get two rules: a Powerwall with grid
    charging left on (no permit set up), mode at self_consumption, took the
    write path and was counted charging with the reserve at 0 %."""

    def _no_permit(self, hass, hold_store):
        return GenericBatteryAdapter(hass, {
            "battery_charge_select_entity": MODE,
            "battery_charge_select_option": "autonomous",
            "battery_target_soc_entity": RESERVE,
            "forced_charge_record": ForcedChargeRecord(_Store()),
            "charge_target_hold": ChargeTargetHold(
                hass, hold_store, configured=(RESERVE,)),
            "battery_id": "b1"})

    async def test_writing_the_mode_with_an_unreadable_target_starts_nothing(self):
        hass = _Hass(reserve="unavailable")
        a = self._no_permit(hass, _Store())
        await actuate_battery(_charge(), a)
        assert hass.calls == []
        assert hass.read(MODE) == "self_consumption"
        assert a.last_intent is not BatteryIntent.FORCE_CHARGE

    async def test_writing_the_mode_with_a_hold_no_starts_nothing(self):
        hass = _Hass(reserve="0")
        a = self._no_permit(hass, _BadStore())
        await actuate_battery(_charge(), a)
        assert hass.calls == []
        assert a.last_intent is not BatteryIntent.FORCE_CHARGE

    async def test_joining_with_an_unreadable_target_starts_nothing(self):
        hass = _Hass(mode="autonomous", reserve="unavailable")
        a = self._no_permit(hass, _Store())
        await actuate_battery(_charge(), a)
        assert hass.calls == []
        assert a.last_intent is not BatteryIntent.FORCE_CHARGE

    async def test_a_readable_target_is_written_then_the_mode(self):
        hass = _Hass(reserve="20")
        a = self._no_permit(hass, _Store())
        await actuate_battery(_charge(), a)
        assert [c[0] for c in hass.calls] == ["number", "select"]
        assert a.last_intent is BatteryIntent.FORCE_CHARGE


class TestTwinNoTarget:
    async def test_a_select_with_no_target_is_unchanged(self):
        hass = _Hass()
        a = GenericBatteryAdapter(hass, {
            "battery_charge_select_entity": MODE,
            "battery_charge_select_option": "autonomous",
            "forced_charge_record": ForcedChargeRecord(_Store()),
            "battery_id": "b1"})
        await actuate_battery(_charge(), a)
        assert hass.read(MODE) == "autonomous"
        assert a.last_intent is BatteryIntent.FORCE_CHARGE


class TestAnUnreadablePermitSavesNothing:
    """(review) The permit was checked after the select's record was saved,
    then the record dropped again: two store writes every cycle."""

    async def test_join(self):
        hass, rec = _Hass(mode="autonomous", permit="unavailable"), _Store()
        a = _adapter(hass, rec, _Store())
        for _ in range(3):
            await actuate_battery(_charge(), a)
        assert hass.calls == [] and rec.raw is None
        assert PERMIT in a.last_error

    async def test_writing_the_mode(self):
        hass, rec = _Hass(permit="unavailable"), _Store()
        a = _adapter(hass, rec, _Store())
        for _ in range(3):
            await actuate_battery(_charge(), a)
        assert hass.calls == [] and rec.raw is None
