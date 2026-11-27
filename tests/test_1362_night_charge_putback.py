"""#1362 — the night charge that never started, and the charge source left
on SEM's value.

@matekogon, 26.11.2026: an inverter with two packs and two MQTT selects (the
output mode, held on "Utility", and the charge source, "Solar and mains" for
a grid charge). His diagnostics at 22:00:

1. The plan booked the battery for every cheap hour 22:00–06:00 at 1300 W,
   10.4 of the 15 kWh it needed: verdict ``partial``. The gate trusted only
   ``fits``, so the battery path read "the plan does not cover the battery"
   and stopped every charge — the pack that needed the most got nothing.
2. Behind it, the hold select had used its 12 writes of the day, so even a
   booked charge could not set the mode it needs.
3. With the hold's charge-source guard (beta.29) and a select that shows a
   write a moment later, the second pack read the guard's "Only solar" as
   the user's value and started a charge of its own, dropping the first
   pack's record. The source then ended on "Only solar", not the user's.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.charge_record import (
    ForcedChargeRecord,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.force_charge import (
    GenericChargeAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.hold_select import (
    MAX_WRITES_PER_DAY,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
)
from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
    plan_gate,
)
from custom_components.solar_energy_management.tests.test_1362_hold_takes_no_grid import (  # noqa: F401
    MAINS, MODE, ONLY_SOLAR, SBU, SOURCE, SRC_SOLAR_FIRST, UTILITY, _Hass,
    _Store, _no_dwell)

TZ = timezone(timedelta(hours=1))
STAMP = datetime(2026, 11, 26, 22, 0, 53, tzinfo=TZ)


@pytest.fixture(autouse=True)
def _no_cloud_wait(monkeypatch):
    monkeypatch.setattr(GenericChargeAdapter, "SHOW_WITHIN_S", 0.0)
    monkeypatch.setattr(GenericChargeAdapter, "AWAY_FOR_S", 0.0)


# ── 1. a partial battery plan runs its hours ───────────────────────────────
def _his_plan(status="partial", demand="battery"):
    """His 22:00 plan: one block per cheap hour, 1300 W, 10.4 of 15 kWh."""
    hours = [STAMP.replace(minute=0, second=0) + timedelta(hours=h)
             for h in range(9)]
    hours[0] = STAMP
    return {
        "computed_at": STAMP.isoformat(),
        "slots": [{"start": hours[i].isoformat(), "end": hours[i + 1].isoformat()}
                  for i in range(8)],
        "demands": [{"id": demand, "status": status, "planned_kwh": 10.38,
                     "needed_kwh": 15.0}],
        "blocks": [{"id": demand, "start": hours[i].isoformat(),
                    "end": hours[i + 1].isoformat(), "power_w": 1300.0}
                   for i in range(8)],
    }


class TestPartialPlan:
    def test_his_plan_charges_the_battery_at_22(self):
        gate = plan_gate(_his_plan(), "battery", STAMP + timedelta(minutes=1))
        assert gate.covered and gate.in_block
        assert gate.block_power_w == 1300.0

    def test_a_partial_plan_of_another_demand_stays_uncovered(self):
        gate = plan_gate(_his_plan(demand="ev:ch1"), "ev:ch1",
                         STAMP + timedelta(minutes=1))
        assert not gate.covered and gate.reason == "verdict partial"

    def test_a_battery_plan_that_yields_stays_uncovered(self):
        plan = _his_plan(status="yields")
        plan["blocks"] = []
        assert not plan_gate(plan, "battery", STAMP + timedelta(minutes=1)).covered


# ── shared: his two packs on one inverter ──────────────────────────────────
def _packs(hass, hold_rec=None):
    hold_rec = hold_rec or ForcedChargeRecord(_Store())
    charge_rec = ForcedChargeRecord(_Store())
    return [GenericBatteryAdapter(hass, {
        "battery_hold_select_entity": MODE,
        "battery_hold_select_option": UTILITY,
        "battery_hold_record": hold_rec,
        "battery_charge_select_entity": SOURCE,
        "battery_charge_select_option": MAINS,
        "forced_charge_record": charge_rec,
        "battery_id": bid}) for bid in ("b1", "b2")]


HOLD = (BatteryIntent.LIMIT_DISCHARGE, {"discharge_limit_w": 0.0})
CHARGE = (BatteryIntent.FORCE_CHARGE, {"target_soc": 50.0,
                                       "charge_power_w": 1300.0,
                                       "duration_min": 60})
STOP = (BatteryIntent.STOP_FORCE_CHARGE, {})
NORMAL = (BatteryIntent.NORMAL, {})


async def _run(hass, packs, steps, cycles=4):
    for intent, kw in steps:
        for _ in range(cycles):
            for a, bid in zip(packs, ("b1", "b2"), strict=False):
                await actuate_battery(
                    BatteryDecision(battery_id=bid, intent=intent, **kw), a)
            tick = getattr(hass, "tick", None)
            if tick is not None:
                tick()


# ── 2. the day's write count does not block a booked charge ────────────────
class TestWriteCount:
    async def _used_up(self):
        hass = _Hass(mode=SBU, source=SRC_SOLAR_FIRST)
        rec = ForcedChargeRecord(_Store())
        day = datetime.now().date().isoformat()
        for _ in range(MAX_WRITES_PER_DAY):
            await rec.count_write(MODE, day)
        return hass, _packs(hass, rec)

    async def test_a_charge_still_sets_the_mode(self):
        hass, packs = await self._used_up()
        await _run(hass, packs, [CHARGE])
        assert (hass.read(MODE), hass.read(SOURCE)) == (UTILITY, MAINS)

    async def test_a_plain_hold_still_waits_for_tomorrow(self):
        hass, packs = await self._used_up()
        await _run(hass, packs, [HOLD])
        assert hass.read(MODE) == SBU


# ── 3. the source goes back to the user's value ────────────────────────────
class _SlowHass(_Hass):
    """An MQTT select: a write shows on the next cycle."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.pending: dict = {}

    async def _call(self, domain, service, data, **kw):
        self.calls.append((domain, service, dict(data)))
        if service == "select_option":
            self.pending[data["entity_id"]] = data["option"]

    def tick(self):
        for entity, value in self.pending.items():
            self.put(entity, value)
        self.pending = {}


NIGHTS = {
    "hold, charge, stop, hold": [HOLD, CHARGE, STOP, HOLD, NORMAL],
    "charge, hold, charge again": [CHARGE, STOP, HOLD, CHARGE, STOP, NORMAL],
    "charge, then normal": [CHARGE, NORMAL],
}


class TestPutBack:
    @pytest.mark.parametrize("night", list(NIGHTS))
    @pytest.mark.parametrize("slow", [False, True], ids=["at once", "a cycle late"])
    async def test_both_selects_end_on_the_users_values(self, night, slow):
        hass = (_SlowHass if slow else _Hass)(mode=SBU, source=SRC_SOLAR_FIRST)
        packs = _packs(hass)
        await _run(hass, packs, NIGHTS[night])
        assert (hass.read(MODE), hass.read(SOURCE)) == (SBU, SRC_SOLAR_FIRST)

    async def test_the_charge_puts_back_the_users_value_not_the_guards(self):
        hass = _SlowHass(mode=SBU, source=SRC_SOLAR_FIRST)
        packs = _packs(hass)
        await _run(hass, packs, [HOLD])
        assert hass.read(SOURCE) == ONLY_SOLAR          # the hold's guard
        await _run(hass, packs, [CHARGE])
        prior = await packs[0]._config["forced_charge_record"].prior_of(SOURCE)
        assert prior == SRC_SOLAR_FIRST

    async def test_a_restart_mid_charge_puts_both_back(self):
        hass = _Hass(mode=SBU, source=SRC_SOLAR_FIRST)
        packs = _packs(hass)
        await _run(hass, packs, [CHARGE])
        hold_rec = ForcedChargeRecord(packs[0]._config["battery_hold_record"]._store)
        charge_rec = ForcedChargeRecord(
            packs[0]._config["forced_charge_record"]._store)
        new = [GenericBatteryAdapter(hass, {
            **packs[i]._config, "battery_hold_record": hold_rec,
            "forced_charge_record": charge_rec}) for i in range(2)]
        for a in new:
            await a.async_adopt_hold()
            await a.async_adopt_running_charge()
        await _run(hass, new, [STOP, NORMAL])
        assert (hass.read(MODE), hass.read(SOURCE)) == (SBU, SRC_SOLAR_FIRST)
