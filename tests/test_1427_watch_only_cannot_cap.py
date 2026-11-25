"""#1427 — the watch-only list said SEM would cap a battery it cannot cap.

In watch-only mode, System › "What SEM would do" listed the house battery as
"stop powering the car · discharge limited to 4.5 kW" while a car charged.
That battery had no discharge limit entity. With watch-only off SEM writes
nothing there: the brand writer only sets ``last_error`` and logs "cannot
keep this battery out of the car". The live decision log ("Why?") said the
same false thing: ``limit_discharge 4500 W``.

Root shape: both rows were written from the DECISION, before (watch-only:
instead of) asking the adapter whether it can carry it out. Each brand
answers that on its own (no entity, a select that only holds, a percent
control with no base, a brand with no limit at all).

What these tests pin:

* the adapter's ``discharge_limit_gap`` agrees with its own writer, for
  every brand and config (an oracle over the real adapters): a gap exactly
  when the writer records no limit, and the same text as ``last_error``;
* watch-only lists ``no_limit`` with no watts exactly when the live branch
  writes no limit — and writes nothing itself;
* the live decision log notes ``no_limit``, not a limit nobody wrote, and
  that row stays the battery's current reason;
* a forced charge or sale the adapter cannot run is no watch-only row, as
  the live branch drops it;
* the twins: a battery that can cap still lists its limit with the watts.
"""
from __future__ import annotations

import itertools
import json
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from custom_components.solar_energy_management.coordinator import reason_codes as RC
from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery, quantise_discharge_limit_w, unsent_why,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.base import (
    BatteryControlAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.charge_record import (
    ForcedChargeRecord,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.deye import (
    DeyeBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.goodwe import (
    GoodWeBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.huawei import (
    HuaweiBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision, BatteryIntent,
)
from custom_components.solar_energy_management.coordinator.decision_log import (
    KIND_BATTERY, NO_LIMIT_VERB, current,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.utils.log_gate import reset_log_gate

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

W_ENT = "number.battery_max_discharge"
PCT_ENT = "number.battery_discharge_limit_pct"
HOLD = "select.battery_output_mode"


@pytest.fixture(autouse=True)
def _gate():
    reset_log_gate()
    yield
    reset_log_gate()


# ─────────────────────────────────────────────────────────────────
# Builders
# ─────────────────────────────────────────────────────────────────

def _num(value, lo=0.0, hi=5000.0, unit="W"):
    st = Mock()
    st.state = str(value)
    st.attributes = {"min": lo, "max": hi, "unit_of_measurement": unit}
    return st


def _hass():
    """Every control a case can name; each write lands; every call kept."""
    table = {
        W_ENT: _num(5000.0),
        PCT_ENT: _num(100.0, 0.0, 100.0, "%"),
        HOLD: Mock(state="SBU", attributes={"options": ["SBU", "Utility"]}),
    }
    hass = MagicMock()
    hass.states.get = Mock(side_effect=lambda e: table.get(e))
    hass.states.async_all = Mock(return_value=[])

    async def _call(domain, service, data=None, **kw):
        ent = str((data or {}).get("entity_id", "") or "")
        if service == "set_value" and ent in table:
            old = table[ent].attributes
            table[ent] = _num(data["value"], old["min"], old["max"],
                              old["unit_of_measurement"])
        if service == "select_option" and ent in table:
            table[ent] = Mock(state=data["option"],
                              attributes=table[ent].attributes)
        return None

    hass.services.async_call = AsyncMock(side_effect=_call)
    hass.table = table
    return hass


class _Store:
    def __init__(self):
        self.raw = None

    async def async_load(self):
        return None if self.raw is None else json.loads(self.raw)

    async def async_save(self, data):
        self.raw = json.dumps(data)


def _deye(hass):
    ad = DeyeBatteryAdapter(hass, {"battery_platform": "deye"})
    ad._observer_mode = False
    ad._actuation_enabled = True
    return ad


#: (name, build(hass)) — every adapter, each way it can or cannot cap.
_CASES = [
    ("generic, no limit entity",
     lambda h: GenericBatteryAdapter(h, {"battery_max_discharge_power": 5000})),
    ("generic, a watt control",
     lambda h: GenericBatteryAdapter(h, {"battery_max_discharge_power": 5000,
                                         "battery_discharge_control_entity": W_ENT})),
    ("generic, percent with no maximum",
     lambda h: GenericBatteryAdapter(h, {"battery_discharge_control_entity": PCT_ENT})),
    ("generic, percent with a maximum",
     lambda h: GenericBatteryAdapter(h, {"battery_max_discharge_power": 5000,
                                         "battery_discharge_control_entity": PCT_ENT})),
    ("generic, a hold select",
     lambda h: GenericBatteryAdapter(h, {
         "battery_max_discharge_power": 5000,
         "battery_hold_select_entity": HOLD,
         "battery_hold_select_option": "Utility",
         "battery_hold_record": ForcedChargeRecord(_Store())})),
    ("goodwe, no limit entity",
     lambda h: GoodWeBatteryAdapter(h, {"battery_max_discharge_power": 5000})),
    ("goodwe, a watt control",
     lambda h: GoodWeBatteryAdapter(h, {"battery_max_discharge_power": 5000,
                                        "battery_discharge_control_entity": W_ENT})),
    ("goodwe, percent with no maximum",
     lambda h: GoodWeBatteryAdapter(h, {"battery_discharge_control_entity": PCT_ENT})),
    # (review) GoodWe and Huawei send watts only: a maximum does not help
    ("goodwe, percent with a maximum",
     lambda h: GoodWeBatteryAdapter(h, {"battery_max_discharge_power": 5000,
                                        "battery_discharge_control_entity": PCT_ENT})),
    ("huawei, no limit entity",
     lambda h: HuaweiBatteryAdapter(h, {"battery_max_discharge_power": 5000})),
    ("huawei, a watt control",
     lambda h: HuaweiBatteryAdapter(h, {"battery_max_discharge_power": 5000,
                                        "battery_discharge_control_entity": W_ENT})),
    ("huawei, percent with no maximum",
     lambda h: HuaweiBatteryAdapter(h, {"battery_discharge_control_entity": PCT_ENT})),
    ("huawei, percent with a maximum",
     lambda h: HuaweiBatteryAdapter(h, {"battery_max_discharge_power": 5000,
                                        "battery_discharge_control_entity": PCT_ENT})),
    ("deye", _deye),
]
#: a hold caps nothing but 0 W, so 0 W is its own case below; the rest of
#: the watts here are above 0 for the hold
_WATTS = [1500.0, 4500.0]


def _build(build):
    hass = _hass()
    ad = build(hass)
    if isinstance(ad, HuaweiBatteryAdapter):
        ad._startup_orphan_checked = True
    return hass, ad


def _limit(watts, **kw):
    return BatteryDecision(battery_id="b1", intent=BatteryIntent.LIMIT_DISCHARGE,
                           discharge_limit_w=watts,
                           reason="ev charging, no sun → battery limited to the house",
                           reason_code=RC.BATTERY_CAR_NOT_ALLOWED,
                           reason_params={"floor": 20.0}, **kw)


def _sc():
    sc = SurplusController(MagicMock())
    sc.hass.bus.async_fire = MagicMock()
    return sc


def _calls(hass):
    return [c for c in hass.services.async_call.await_args_list
            if c.args[1] in ("set_value", "select_option")]


# ─────────────────────────────────────────────────────────────────
# 1. The reporter's battery
# ─────────────────────────────────────────────────────────────────

class TestTheReportersBattery:
    """A car charges, the decision is a 4.5 kW limit, and the battery has no
    discharge limit entity."""

    async def test_watch_only_says_sem_cannot_cap_it(self):
        hass, ad = _build(_CASES[0][1])
        sc = _sc()
        await actuate_battery(_limit(4500.0), ad, observer=True, controller=sc)
        row = sc.observer_decisions["battery:b1"]
        assert row["action"] == NO_LIMIT_VERB, "the list still says SEM caps it"
        assert row["power_w"] == 0.0, "a cap nobody can write has no watts"
        assert row["reason_code"] == RC.BATTERY_NO_LIMIT
        assert row["reason"] == BatteryControlAdapter.NO_DISCHARGE_LIMIT_ERROR
        rec = sc.decision_log.records()[0]
        assert rec["new"] == NO_LIMIT_VERB and rec["observer"] is True
        assert rec["reason_code"] == RC.BATTERY_NO_LIMIT
        assert rec["params"] == {}, "the limit's numbers do not ride along"
        assert _calls(hass) == [], "watch-only wrote to the inverter"

    async def test_the_live_log_says_the_same(self):
        hass, ad = _build(_CASES[0][1])
        sc = _sc()
        await actuate_battery(_limit(4500.0), ad, controller=sc)
        rec = sc.decision_log.records()[0]
        assert rec["new"] == NO_LIMIT_VERB, "the log noted a limit nobody wrote"
        assert rec["reason_code"] == RC.BATTERY_NO_LIMIT
        # the command itself is unchanged: the writer says the gap
        assert ad.last_intent is BatteryIntent.LIMIT_DISCHARGE
        assert ad.last_error == BatteryControlAdapter.NO_DISCHARGE_LIMIT_ERROR
        assert ad.last_discharge_limit_w == -1.0

    async def test_the_row_stays_the_batterys_current_reason(self):
        """The decision is still ``limit_discharge``: the row that says SEM
        cannot cap must count as current, or "Why?" falls back to the
        engine text of the limit."""
        _hass_, ad = _build(_CASES[0][1])
        sc = _sc()
        await actuate_battery(_limit(4500.0), ad, controller=sc)
        coord = MagicMock()
        coord.decision_log = sc.decision_log
        coord._last_battery_decisions = {"b1": {
            "intent": "limit_discharge", "reason": "ev charging"}}
        now = current(KIND_BATTERY, "b1", coord)
        assert now.get("live") is not True
        assert now["new"] == NO_LIMIT_VERB
        # …and a row of another command is not current against it
        coord._last_battery_decisions["b1"]["intent"] = "normal"
        assert current(KIND_BATTERY, "b1", coord).get("live") is True

    async def test_twin_a_battery_with_a_limit_lists_its_watts(self):
        hass, ad = _build(_CASES[1][1])
        sc = _sc()
        await actuate_battery(_limit(4500.0), ad, observer=True, controller=sc)
        row = sc.observer_decisions["battery:b1"]
        assert row["action"] == "limit_discharge"
        assert row["power_w"] == 4500.0
        assert row["reason_code"] == RC.BATTERY_CAR_NOT_ALLOWED
        assert sc.decision_log.records()[0]["new"] == "limit_discharge 4500 W"
        assert _calls(hass) == []


# ─────────────────────────────────────────────────────────────────
# 2. Oracle: the question and the writer agree, on every adapter
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,build,watts", [
    (n, b, w) for (n, b), w in itertools.product(_CASES, _WATTS)])
async def test_the_gap_is_what_the_writer_does(name, build, watts):
    _h, ad = _build(build)
    gap = ad.discharge_limit_gap(watts)
    await ad.command_limit_discharge(watts)
    capped = ad.last_discharge_limit_w >= 0
    assert (gap is None) == capped, (
        f"{name}: the gap says {gap!r}, the writer recorded "
        f"{ad.last_discharge_limit_w} W")
    if gap is not None:
        assert ad.last_error == gap, f"{name}: two texts for one gap"


@pytest.mark.parametrize("name,build,watts", [
    (n, b, w) for (n, b), w in itertools.product(_CASES, _WATTS)])
async def test_watch_only_lists_what_live_sends(name, build, watts):
    """Two homes, the same battery: one live, one in watch-only. The
    watch-only row is the live row, and says no cap exactly when the live
    writer wrote none."""
    _lh, live_ad = _build(build)
    live = _sc()
    await actuate_battery(_limit(watts), live_ad, controller=live)
    live_verb = live.decision_log.records()[0]["new"].split(" ")[0]
    capped = live_ad.last_discharge_limit_w >= 0
    assert (live_verb == NO_LIMIT_VERB) == (not capped), name

    obs_hass, obs_ad = _build(build)
    obs = _sc()
    await actuate_battery(_limit(watts), obs_ad, observer=True, controller=obs)
    row = obs.observer_decisions["battery:b1"]
    assert row["action"] == live_verb, name
    if capped:
        assert row["power_w"] == quantise_discharge_limit_w(watts, -1.0)
    else:
        assert row["power_w"] == 0.0
        assert row["reason"] == live_ad.last_error, name
    assert _calls(obs_hass) == [], f"{name}: watch-only wrote"


class TestTheHoldSelect:
    """A select holds the battery at 0 W and caps nothing above it."""

    def _ad(self):
        return _build(_CASES[4][1])[1]

    def test_it_holds_at_zero(self):
        assert self._ad().discharge_limit_gap(0.0) is None

    def test_it_caps_nothing_above_zero(self):
        ad = self._ad()
        assert ad.discharge_limit_gap(1.0) == ad.NO_PARTIAL_HOLD_ERROR

    async def test_a_refused_hold_is_not_listed_as_one(self):
        """…and its text is the one the hold itself sets (review)."""
        ad = self._ad()
        ad._hold.refused, ad._hold._why = True, "the inverter left Utility"
        gap = ad.discharge_limit_gap(0.0)
        ad._hold._read_refusal = AsyncMock()       # keep the refusal as set
        await ad.command_limit_discharge(0.0)
        assert ad.last_discharge_limit_w == -1.0
        assert gap == ad.last_error
        assert "the inverter left Utility" in gap

    async def test_watch_only_lists_the_zero_hold(self):
        hass, ad = _build(_CASES[4][1])
        sc = _sc()
        await ad.async_adopt_running_charge(observer=True)
        await actuate_battery(_limit(0.0), ad, observer=True, controller=sc)
        assert sc.observer_decisions["battery:b1"]["action"] == "limit_discharge"
        assert _calls(hass) == []

    @pytest.mark.parametrize("age_h,listed", [(1.0, NO_LIMIT_VERB),
                                              (25.0, "limit_discharge")])
    async def test_watch_only_reads_a_refusal_from_live(self, age_h, listed):
        """(review) The inverter refused SEM's hold while SEM was live; the
        user then turned watch-only on. Watch-only never tries a hold, so it
        reads the refusal before the list shows one — and an old one
        (over 24 h) no longer counts."""
        import time as _time
        hass = _hass()
        record = ForcedChargeRecord(_Store())
        await record.refuse(HOLD)
        record._refused[HOLD] = _time.time() - age_h * 3600
        ad = GenericBatteryAdapter(hass, {
            "battery_max_discharge_power": 5000,
            "battery_hold_select_entity": HOLD,
            "battery_hold_select_option": "Utility",
            "battery_hold_record": record})
        assert ad.hold_refused is False            # a new lifetime knows nothing yet
        sc = _sc()
        await ad.async_adopt_running_charge(observer=True)
        await actuate_battery(_limit(0.0), ad, observer=True, controller=sc)
        assert sc.observer_decisions["battery:b1"]["action"] == listed
        assert _calls(hass) == []


# ─────────────────────────────────────────────────────────────────
# 3. A forced op the adapter cannot run is no row
# ─────────────────────────────────────────────────────────────────

class TestForcedOpsTheAdapterCannotRun:

    def _bare(self):
        return GenericBatteryAdapter(_hass(), {"battery_max_discharge_power": 5000})

    async def test_no_forced_charge_is_listed_as_one(self):
        ad = self._bare()
        assert ad.supports_forced_charge is False
        d = BatteryDecision(battery_id="b1", intent=BatteryIntent.FORCE_CHARGE,
                            target_soc=90.0, charge_power_w=3000.0, duration_min=60)
        for observer in (False, True):
            sc = _sc()
            await actuate_battery(d, ad, observer=observer, controller=sc)
            assert "battery:b1" not in sc.observer_decisions
            assert len(sc.decision_log) == 0, observer

    async def test_no_sale_is_listed_as_one(self):
        ad = self._bare()
        assert ad.supports_forced_discharge is False
        d = BatteryDecision(battery_id="b1", intent=BatteryIntent.FORCE_DISCHARGE,
                            discharge_power_w=3000.0, floor_soc=20.0)
        for observer in (False, True):
            sc = _sc()
            await actuate_battery(d, ad, observer=observer, controller=sc)
            assert "battery:b1" not in sc.observer_decisions
            assert len(sc.decision_log) == 0, observer

    async def test_twin_a_pack_that_can_charge_is_listed(self):
        hass = _hass()
        hass.table["number.setpoint"] = _num(0.0, -2200.0, 2200.0)
        ad = GenericBatteryAdapter(hass, {
            "battery_force_discharge_control_entity": "number.setpoint",
            "battery_setpoint_bidirectional": True,
            "battery_max_discharge_power": 2200})
        assert ad.supports_forced_charge is True
        d = BatteryDecision(battery_id="b1", intent=BatteryIntent.FORCE_CHARGE,
                            target_soc=90.0, charge_power_w=2000.0, duration_min=60)
        sc = _sc()
        await actuate_battery(d, ad, observer=True, controller=sc)
        assert sc.observer_decisions["battery:b1"]["action"] == "force_charge"
        assert _calls(hass) == []

    def test_a_stub_adapter_reads_as_able(self):
        """An adapter that gives no text (a test double) can act: the rule
        never turns a row into no_limit on an answer it cannot read."""
        stub = MagicMock()
        for intent in (BatteryIntent.LIMIT_DISCHARGE, BatteryIntent.FORCE_CHARGE,
                       BatteryIntent.FORCE_DISCHARGE):
            assert unsent_why(BatteryDecision(battery_id="b1", intent=intent),
                              stub, 1000.0) is None

    def test_an_adapter_that_does_not_say_it_can_force_cannot(self):
        """(review) The forced-op gate sends hardware commands: an adapter
        with no answer is not taken as able."""
        bare = object()
        for intent in (BatteryIntent.FORCE_CHARGE, BatteryIntent.FORCE_DISCHARGE):
            assert unsent_why(BatteryDecision(battery_id="b1", intent=intent),
                              bare) is not None


# ─────────────────────────────────────────────────────────────────
# 4. The words
# ─────────────────────────────────────────────────────────────────

_NEW_KEYS = ("next_act_no_limit", "why_verb_no_limit",
             f"why_reason_{RC.BATTERY_NO_LIMIT}")


def test_every_language_has_the_new_words():
    tr = json.loads((ROOT / "dashboard" / "translations.json").read_text("utf-8"))
    assert len(tr) == 16
    for key in _NEW_KEYS:
        english = tr["en"][key]
        for lang, table in tr.items():
            assert table.get(key), f"{lang} has no {key}"
            if lang != "en":
                assert table[key] != english, f"{lang} {key} is English"
    # the limit's own words are not reused: they say the battery is kept out
    assert tr["en"]["next_act_no_limit"] != tr["en"]["next_act_limit_discharge"]


def test_the_built_card_reads_only_a_real_limit_as_one():
    """(review) The bundle that ships carries the new rule: ``no_limit``
    contains "limit", so the old ``/limit/`` showed a figure for it."""
    bundle = (ROOT / "dashboard" / "card" / "dist" / "sem-cards.js").read_text("utf-8")
    assert "/^limit_/.test(" in bundle
    assert "/limit/.test(" not in bundle
