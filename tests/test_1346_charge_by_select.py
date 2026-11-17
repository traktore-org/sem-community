"""#1346 — a grid charge started by a select, stopped by putting it back.

An inverter with no charge switch, but a select ("Solar and mains" against
"Solar only"). Two settings, the select and its charge option; with either
unset nothing changes. The option the select showed before SEM changed it is
kept in the same record the switch path uses, so the stop, an abort and a
restart mid-charge all put it back, and a choice made by hand is left alone.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.base import (
    async_release_batteries_on_unload,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.charge_record import (
    ForcedChargeRecord,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
)

from .test_1367_plan_only_sendable_charge import _battery_row, _plan

SELECT = "select.charge_source"
CHARGE = "Solar and mains"
SOLAR = "Solar only"
OPTIONS = [SOLAR, CHARGE, "Utility first"]
SWITCH = "switch.force_charge"


class _Hass:
    """A select that lists options; each write lands, every call recorded."""

    def __init__(self, state=SOLAR):
        self._states = {SELECT: SimpleNamespace(
            state=state, attributes={"options": list(OPTIONS)})}
        self.calls: list[tuple] = []
        self.raise_on = False
        self.refuse = False         # the call succeeds, the select stays
        self.states = SimpleNamespace(get=self._states.get)
        self.services = SimpleNamespace(async_call=self._call)

    def set(self, value, options=None):
        old = self._states[SELECT]
        self._states[SELECT] = SimpleNamespace(
            state=value, attributes={"options": options if options is not None
                                     else old.attributes["options"]})

    def read(self):
        return self._states[SELECT].state

    async def _call(self, domain, service, data, **kw):
        if self.raise_on:
            raise RuntimeError("bus timeout")
        self.calls.append((domain, service, dict(data)))
        if service == "select_option" and not self.refuse:
            self.set(data["option"])

    def writes(self):
        return [c for c in self.calls if c[1] == "select_option"]


class _Store:
    def __init__(self):
        self.raw = None

    async def async_load(self):
        return None if self.raw is None else json.loads(self.raw)

    async def async_save(self, data):
        self.raw = json.dumps(data)


def _adapter(hass, store, record=None, **extra):
    cfg = {"battery_charge_select_entity": SELECT,
           "battery_charge_select_option": CHARGE,
           "forced_charge_record": record or ForcedChargeRecord(store),
           "battery_id": "b1", **extra}
    return GenericBatteryAdapter(hass, cfg)


def _charge(soc=60.0):
    return BatteryDecision(battery_id="b1", intent=BatteryIntent.FORCE_CHARGE,
                           target_soc=soc, charge_power_w=3000.0, duration_min=60)


def _stop():
    return BatteryDecision(battery_id="b1", intent=BatteryIntent.STOP_FORCE_CHARGE)


# ── asleep ──────────────────────────────────────────────────────────────
class TestAsleep:
    def test_nothing_configured_is_as_before(self):
        a = GenericBatteryAdapter(_Hass(), {"battery_id": "b1"})
        assert a.supports_forced_charge is False
        assert a.charge_command_configured is False

    def test_either_setting_alone_wakes_nothing(self):
        for cfg in ({"battery_charge_select_entity": SELECT},
                    {"battery_charge_select_option": CHARGE}):
            a = GenericBatteryAdapter(_Hass(), {"battery_id": "b1", **cfg})
            assert a.supports_forced_charge is False

    async def test_a_switch_beside_the_pair_is_a_permit_not_the_start(self):
        # (#1377) it used to win; now the select starts and the switch permits
        hass = _Hass()
        hass._states[SWITCH] = SimpleNamespace(state="off", attributes={})
        a = _adapter(hass, _Store(), battery_force_charge_switch=SWITCH,
                     battery_target_soc_entity="number.t")
        await actuate_battery(_charge(), a)
        assert ("switch", "turn_on", {"entity_id": SWITCH}) in hass.calls
        assert len(hass.writes()) == 1

    async def test_no_target_entity_is_needed_for_the_select_path(self):
        assert _adapter(_Hass(), _Store()).supports_forced_charge is True


# ── start ───────────────────────────────────────────────────────────────
class TestStart:
    async def test_writes_the_charge_option_once_and_a_second_start_nothing(self):
        hass = _Hass()
        a = _adapter(hass, _Store())
        await actuate_battery(_charge(), a)
        await actuate_battery(_charge(), a)
        assert hass.writes() == [("select", "select_option",
                                  {"entity_id": SELECT, "option": CHARGE})]
        assert a.last_intent is BatteryIntent.FORCE_CHARGE

    async def test_the_prior_option_is_on_disk_before_the_write(self):
        hass, store = _Hass(), _Store()
        seen = []
        orig = hass._call

        async def spy(domain, service, data, **kw):
            seen.append(json.loads(store.raw))
            await orig(domain, service, data, **kw)
        hass.services = SimpleNamespace(async_call=spy)
        await actuate_battery(_charge(), _adapter(hass, store))
        assert seen[0]["prior"] == {SELECT: SOLAR}

    async def test_an_option_the_select_does_not_list_writes_nothing(self):
        hass = _Hass()
        a = _adapter(hass, _Store(), battery_charge_select_option="Grid only")
        await actuate_battery(_charge(), a)
        assert hass.calls == []
        assert "does not list" in a.last_error
        assert a.last_intent is not BatteryIntent.FORCE_CHARGE

    async def test_an_unavailable_select_cannot_start(self):
        for state in ("unavailable", "unknown"):
            hass = _Hass(state)
            a = _adapter(hass, _Store())
            await actuate_battery(_charge(), a)
            assert hass.calls == []
            assert "unavailable" in a.last_error
            assert a.last_intent is not BatteryIntent.FORCE_CHARGE

    async def test_a_failed_write_drops_the_name_and_says_so(self):
        hass, store = _Hass(), _Store()
        hass.raise_on = True
        a = _adapter(hass, store)
        await actuate_battery(_charge(), a)
        assert "start failed" in a.last_error
        assert json.loads(store.raw).get("running", {}) == {}

    async def test_a_record_that_cannot_be_saved_means_no_start(self):
        hass, store = _Hass(), _Store()

        async def boom(data):
            raise OSError("disk")
        store.async_save = boom
        await actuate_battery(_charge(), _adapter(hass, store))
        assert hass.calls == []

    async def test_a_select_already_on_the_option_is_not_taken_over(self):
        hass, store = _Hass(CHARGE), _Store()
        a = _adapter(hass, store)
        await actuate_battery(_charge(), a)
        await actuate_battery(_stop(), a)
        assert hass.calls == []             # nothing written, nothing put back
        assert store.raw is None


# ── stop ────────────────────────────────────────────────────────────────
class TestStop:
    async def test_the_stop_restores_what_the_select_showed(self):
        hass = _Hass("Utility first")
        a = _adapter(hass, _Store())
        await actuate_battery(_charge(), a)
        await actuate_battery(_stop(), a)
        assert hass.read() == "Utility first"
        assert [w[2]["option"] for w in hass.writes()] == [CHARGE, "Utility first"]

    async def test_a_second_stop_writes_nothing(self):
        hass = _Hass()
        a = _adapter(hass, _Store())
        await actuate_battery(_charge(), a)
        await actuate_battery(_stop(), a)
        n = len(hass.calls)
        await actuate_battery(_stop(), a)
        assert len(hass.calls) == n

    async def test_a_hand_change_during_the_charge_is_not_written_over(self):
        hass, store = _Hass(), _Store()
        a = _adapter(hass, store)
        await actuate_battery(_charge(), a)
        hass.set("Utility first")           # the user chose by hand
        n = len(hass.calls)
        await actuate_battery(_stop(), a)
        assert len(hass.calls) == n and hass.read() == "Utility first"
        assert json.loads(store.raw).get("running", {}) == {}   # name dropped

    async def test_an_unreadable_select_is_retried_not_forgotten(self):
        hass, store = _Hass(), _Store()
        a = _adapter(hass, store)
        await actuate_battery(_charge(), a)
        hass.set("unavailable")
        await actuate_battery(_stop(), a)
        assert "unavailable" in a.last_error
        assert a.last_intent is BatteryIntent.FORCE_CHARGE      # not "stopped"
        hass.set(CHARGE)
        await actuate_battery(_stop(), a)
        assert hass.read() == SOLAR

    async def test_the_unload_abort_puts_it_back(self):
        hass = _Hass()
        a = _adapter(hass, _Store())
        await actuate_battery(_charge(), a)
        await async_release_batteries_on_unload(
            SimpleNamespace(_observer_mode=False, _battery_adapters={"b1": a}))
        assert hass.read() == SOLAR

    async def test_off_puts_it_back(self):
        hass = _Hass()
        a = _adapter(hass, _Store())
        await actuate_battery(_charge(), a)
        await a.command_normal()
        assert hass.read() == SOLAR


# ── restart ─────────────────────────────────────────────────────────────
class TestRestart:
    async def test_the_prior_survives_a_restart_and_the_stop_restores_it(self):
        hass, store = _Hass("Utility first"), _Store()
        await actuate_battery(_charge(), _adapter(hass, store))
        fresh = _adapter(hass, store)       # a new lifetime, same store
        await fresh.async_adopt_running_charge()
        await actuate_battery(_stop(), fresh)
        assert hass.read() == "Utility first"

    async def test_a_hand_change_before_the_restart_is_not_fought(self):
        hass, store = _Hass(), _Store()
        await actuate_battery(_charge(), _adapter(hass, store))
        hass.set("Utility first")
        fresh = _adapter(hass, store)
        await fresh.async_adopt_running_charge()
        n = len(hass.calls)
        await actuate_battery(_stop(), fresh)
        assert len(hass.calls) == n and hass.read() == "Utility first"

    async def test_an_old_record_without_a_prior_still_loads(self):
        store = _Store()
        store.raw = json.dumps({"running": {SWITCH: ["b1"]}})
        rec = ForcedChargeRecord(store)
        assert await rec.running(SWITCH, "b1") is True
        assert await rec.prior_of(SWITCH) is None


# ── observer ────────────────────────────────────────────────────────────
class TestObserver:
    async def test_observer_sends_nothing_and_records_the_would(self):
        hass, store = _Hass(), _Store()
        seen = []
        controller = SimpleNamespace(
            publish_observer_decision=lambda **kw: seen.append(kw))
        await actuate_battery(_charge(), _adapter(hass, store),
                              observer=True, controller=controller)
        assert hass.calls == [] and store.raw is None
        assert seen and seen[0]["action"] == "force_charge"


# ── the plan ────────────────────────────────────────────────────────────
class TestPlan:
    def test_the_plan_keeps_the_charge_when_the_select_is_set(self, monkeypatch):
        plan = _plan(monkeypatch, {"b1": _adapter(_Hass(), _Store())})
        assert _battery_row(plan) is not None
        assert not [r for r in plan["not_scheduled"] if r["id"] == "battery"]

    def test_the_plan_still_marks_no_charge_control_without_it(self, monkeypatch):
        plan = _plan(monkeypatch, {"b1": GenericBatteryAdapter(_Hass(), {})})
        assert _battery_row(plan) is None
        assert {"id": "battery", "why": "no_charge_control",
                "label": None} in plan["not_scheduled"]


# ── (#1346 review) a select that refuses, or flips back ─────────────────
class TestRefusal:
    async def test_a_refusing_select_gets_two_writes_in_ten_cycles(self):
        hass, store = _Hass(), _Store()
        hass.refuse = True
        a = _adapter(hass, store)
        for _ in range(10):
            await actuate_battery(_charge(), a)
        assert len(hass.writes()) == 2
        assert "did not take" in a.last_error
        assert a.last_intent is not BatteryIntent.FORCE_CHARGE
        assert a._charge_adapter.is_active is False
        assert json.loads(store.raw).get("running", {}) == {}

    async def test_a_new_attempt_after_the_stop_may_try_again(self):
        hass = _Hass()
        hass.refuse = True
        a = _adapter(hass, _Store())
        for _ in range(5):
            await actuate_battery(_charge(), a)
        await actuate_battery(_stop(), a)
        for _ in range(5):
            await actuate_battery(_charge(), a)
        assert len(hass.writes()) == 4          # 2 per attempt, never more

    async def test_a_select_that_takes_it_late_is_a_charge(self):
        hass = _Hass()
        hass.refuse = True
        a = _adapter(hass, _Store())
        await actuate_battery(_charge(), a)
        hass.refuse = False
        hass.set(CHARGE)                        # slow to show it
        await actuate_battery(_charge(), a)
        assert len(hass.writes()) == 1 and a.last_error is None
        assert a.last_intent is BatteryIntent.FORCE_CHARGE

    async def test_a_select_the_inverter_flips_back_is_not_fought(self):
        hass, store = _Hass(), _Store()
        a = _adapter(hass, store)
        await actuate_battery(_charge(), a)
        await actuate_battery(_charge(), a)     # reads the option: it took
        hass.set(SOLAR)                         # the inverter's own logic
        for _ in range(5):
            await actuate_battery(_charge(), a)
        assert len(hass.writes()) == 1          # no rewrite
        assert "by itself" in a.last_error
        assert a.last_intent is not BatteryIntent.FORCE_CHARGE
        assert json.loads(store.raw).get("running", {}) == {}


# ── a prior the select no longer lists ──────────────────────────────────
class TestRefusalRound2:
    """(#1346 review, second round)"""

    async def test_the_next_block_may_try_again_without_a_stop(self):
        """A refused start, the block ends (NORMAL), a new block: two more
        writes at most — the planner need not send a STOP between."""
        hass = _Hass()
        hass.refuse = True
        a = _adapter(hass, _Store())
        for _ in range(50):
            await actuate_battery(_charge(), a)
        assert len(hass.writes()) == 2
        for _ in range(5):
            await actuate_battery(BatteryDecision(battery_id="b1", intent=BatteryIntent.NORMAL), a)
        for _ in range(50):
            await actuate_battery(_charge(), a)
        assert len(hass.writes()) == 4

    async def test_a_refusal_is_remembered_for_the_plan_and_cleared_by_a_start(self):
        hass = _Hass()
        hass.refuse = True
        a = _adapter(hass, _Store())
        assert a.charge_refused is False
        for _ in range(3):
            await actuate_battery(_charge(), a)
        assert a.charge_refused is True
        await actuate_battery(_stop(), a)
        assert a.charge_refused is True            # the plan still knows
        hass.refuse = False
        await actuate_battery(_charge(), a)        # this one is taken
        await actuate_battery(_charge(), a)
        assert a.charge_refused is False

    def test_the_plan_says_refused_not_no_control(self, monkeypatch):
        import types
        from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator
        ad = types.SimpleNamespace(charge_command_configured=True, charge_refused=True)
        coord = types.SimpleNamespace(_live_battery_adapters=lambda: [("b1", ad)])
        share, unable = SEMCoordinator._charge_command_share(coord, None)
        assert share == 0 and unable == ["b1"] and coord._charge_refused_ids == {"b1"}
        ok = types.SimpleNamespace(charge_command_configured=True, charge_refused=False)
        coord2 = types.SimpleNamespace(_live_battery_adapters=lambda: [("b1", ok)])
        assert SEMCoordinator._charge_command_share(coord2, None)[1] == []

    def test_the_refused_text_exists_in_every_language(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        d = json.loads((root / "dashboard" / "translations.json").read_text())
        key = "energy_plan_why_" + "charge_refused"
        assert all(d[lang].get(key) for lang in d)


class TestOldRecord:
    async def test_a_record_older_than_two_days_is_dropped_without_a_write(self):
        hass, store = _Hass("Utility first"), _Store()
        await actuate_battery(_charge(), _adapter(hass, store))
        assert hass.read() == CHARGE
        rec = json.loads(store.raw)
        assert rec["since"][SELECT] > 0
        rec["since"][SELECT] -= 49 * 3600
        store.raw = json.dumps(rec)
        n = len(hass.calls)
        fresh = GenericBatteryAdapter(hass, {
            "forced_charge_record": ForcedChargeRecord(store), "battery_id": "b1"})
        await fresh.async_adopt_running_charge()
        assert len(hass.calls) == n and hass.read() == CHARGE     # left as it is
        assert json.loads(store.raw).get("running", {}) == {}

    async def test_a_record_without_a_time_is_still_restored(self):
        hass, store = _Hass("Utility first"), _Store()
        await actuate_battery(_charge(), _adapter(hass, store))
        rec = json.loads(store.raw)
        rec.pop("since", None)
        store.raw = json.dumps(rec)
        fresh = GenericBatteryAdapter(hass, {
            "forced_charge_record": ForcedChargeRecord(store), "battery_id": "b1"})
        await fresh.async_adopt_running_charge()
        assert hass.read() == "Utility first"


class TestPriorGone:
    def _spy(self, monkeypatch):
        from custom_components.solar_energy_management.coordinator import (
            repair_issues as ri)
        seen = {"raised": [], "cleared": []}
        monkeypatch.setattr(ri, "raise_charge_select_stuck",
                            lambda hass, **kw: seen["raised"].append(kw))
        monkeypatch.setattr(ri, "clear_charge_select_stuck",
                            lambda hass, eid: seen["cleared"].append(eid))
        return seen

    async def test_three_failed_stops_raise_a_repair_and_write_nothing(
            self, monkeypatch):
        seen = self._spy(monkeypatch)
        hass = _Hass()
        a = _adapter(hass, _Store())
        await actuate_battery(_charge(), a)
        hass.set(CHARGE, options=[CHARGE, "Utility first"])    # SOLAR is gone
        for n in range(1, 6):
            await actuate_battery(_stop(), a)
            assert bool(seen["raised"]) == (n >= 3)     # the third, not before
        assert seen["raised"][0] == {"entity": SELECT, "option": CHARGE}
        assert len(hass.writes()) == 1          # only the start

    async def test_a_changed_list_starts_the_count_again(self, monkeypatch):
        seen = self._spy(monkeypatch)
        hass = _Hass()
        a = _adapter(hass, _Store())
        await actuate_battery(_charge(), a)
        hass.set(CHARGE, options=[CHARGE])
        await actuate_battery(_stop(), a)
        await actuate_battery(_stop(), a)
        hass.set(CHARGE, options=[CHARGE, "Other"])
        await actuate_battery(_stop(), a)
        assert seen["raised"] == []

    async def test_the_list_getting_it_back_restores_and_clears(
            self, monkeypatch):
        seen = self._spy(monkeypatch)
        hass = _Hass()
        a = _adapter(hass, _Store())
        await actuate_battery(_charge(), a)
        hass.set(CHARGE, options=[CHARGE])
        for _ in range(3):
            await actuate_battery(_stop(), a)
        hass.set(CHARGE, options=list(OPTIONS))
        await actuate_battery(_stop(), a)
        assert hass.read() == SOLAR and seen["cleared"] == [SELECT]

    async def test_a_hand_change_drops_the_record_and_the_repair(
            self, monkeypatch):
        seen = self._spy(monkeypatch)
        hass, store = _Hass(), _Store()
        a = _adapter(hass, store)
        await actuate_battery(_charge(), a)
        hass.set(CHARGE, options=[CHARGE])
        for _ in range(3):
            await actuate_battery(_stop(), a)
        hass.set("Utility first", options=[CHARGE, "Utility first"])
        await actuate_battery(_stop(), a)
        assert json.loads(store.raw).get("running", {}) == {}
        assert seen["cleared"] == [SELECT] and len(hass.writes()) == 1


# ── a crash, then the setting is cleared ────────────────────────────────
class TestSettingClearedBeforeRestart:
    def _fresh(self, hass, store):
        return GenericBatteryAdapter(hass, {
            "forced_charge_record": ForcedChargeRecord(store),
            "battery_id": "b1"})

    async def test_the_select_is_put_back_and_the_record_dropped(self):
        hass, store = _Hass("Utility first"), _Store()
        await actuate_battery(_charge(), _adapter(hass, store))
        assert hass.read() == CHARGE
        await self._fresh(hass, store).async_adopt_running_charge()
        assert hass.read() == "Utility first"
        assert json.loads(store.raw).get("running", {}) == {}

    async def test_observer_mode_sends_nothing_and_keeps_the_record(self):
        hass, store = _Hass(), _Store()
        await actuate_battery(_charge(), _adapter(hass, store))
        n = len(hass.calls)
        fresh = self._fresh(hass, store)
        await fresh.async_adopt_running_charge(observer=True)
        assert len(hass.calls) == n and hass.read() == CHARGE
        assert json.loads(store.raw)["running"] == {SELECT: ["b1"]}
        await fresh.async_adopt_running_charge()       # observer left
        assert hass.read() == SOLAR

    async def test_a_select_changed_by_hand_is_left_and_the_record_dropped(self):
        hass, store = _Hass(), _Store()
        await actuate_battery(_charge(), _adapter(hass, store))
        hass.set("Utility first")
        n = len(hass.calls)
        await self._fresh(hass, store).async_adopt_running_charge()
        assert len(hass.calls) == n and hass.read() == "Utility first"
        assert json.loads(store.raw).get("running", {}) == {}

    async def test_an_unreadable_select_waits(self):
        hass, store = _Hass(), _Store()
        await actuate_battery(_charge(), _adapter(hass, store))
        hass.set("unavailable")
        fresh = self._fresh(hass, store)
        await fresh.async_adopt_running_charge()
        assert json.loads(store.raw)["running"] == {SELECT: ["b1"]}
        hass.set(CHARGE)
        await fresh.async_adopt_running_charge()
        assert hass.read() == SOLAR


# ── two packs, one select ───────────────────────────────────────────────
class TestSharedSelect:
    def _stop_of(self, bid):
        return BatteryDecision(battery_id=bid,
                               intent=BatteryIntent.STOP_FORCE_CHARGE)

    async def test_the_prior_goes_back_only_when_the_last_pack_leaves(self):
        hass, store = _Hass("Utility first"), _Store()
        rec = ForcedChargeRecord(store)
        a = _adapter(hass, store, record=rec)
        b = _adapter(hass, store, record=rec, battery_id="b2")
        await actuate_battery(_charge(), a)
        await actuate_battery(BatteryDecision(
            battery_id="b2", intent=BatteryIntent.FORCE_CHARGE, target_soc=60.0,
            charge_power_w=3000.0, duration_min=60), b)
        await actuate_battery(_stop(), a)
        assert hass.read() == CHARGE            # b2 still charges
        await actuate_battery(self._stop_of("b2"), b)
        assert hass.read() == "Utility first"
        assert json.loads(store.raw).get("running", {}) == {}


# ── the card: a half-filled pair says so ────────────────────────────────
def test_the_half_pair_hint_keys_exist_in_every_language():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "dashboard"
    data = json.loads((root / "translations.json").read_text(encoding="utf-8"))
    for lang, table in data.items():
        for key in ("config_charge_select_need_option",
                    "config_charge_select_need_select"):
            assert table.get(key), f"{lang}: {key}"
