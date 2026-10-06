"""#1023 / #1025 A6 — the EV card's departure and boost rows.

Guido approved the mockup on 06.10: inside Charge Target, a chip per weekday
under Charge by, "Charge in one block", "Top up before leaving" with what the
plan booked for it, the plan strip with the top-up hatched, and the battery
boost with its floor, its progress and how it ended.

What the card needs that it did not have:

* the top-up must be told apart from the rest of the night all the way to
  the strip — the packer marks it, the plan's blocks carry it, the merge
  keeps it a run of its own, and the today-plan composer gives it its own
  start row (detail ``plan_ev_charge_late``);
* every start row carries its window's end (``until``), so a night in two
  parts reads as charge · wait · top-up instead of one bar;
* one view per charger on the charging-state sensor — the default time, each
  weekday's own, the next departure, the two plan knobs, the stamped top-up
  and whether the battery may be boosted into this car (D5);
* a way to WRITE those knobs that does not reload SEM. ``set_option`` on
  ``ev_chargers`` is structural (it reloads the integration), and a reload
  ends a running boost: the card's clicks go through
  ``set_charger_departure``, the per-charger no-reload writer.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from custom_components.solar_energy_management.coordinator.energy_planner import (
    Demand,
    LedgerSlot,
    build_night_ledger,
    pack_night,
)
from custom_components.solar_energy_management.coordinator.today_plan import (
    KIND_EV_CHARGE_START,
    KIND_EV_MIN_REACHED,
    compose_today_plan,
)

ROOT = Path(__file__).resolve().parents[1]
ZRH = ZoneInfo("Europe/Zurich")
START = datetime(2026, 10, 9, 22, 0, tzinfo=ZRH)
DEPART = datetime(2026, 10, 10, 7, 0, tzinfo=ZRH)
NIGHT = [0.30, 0.30, 0.25, 0.20, 0.10, 0.10, 0.30, 0.35, 0.40]


def _ledger(prices):
    step = timedelta(hours=1)
    slots = [LedgerSlot(start=START + n * step, end=START + (n + 1) * step,
                        price=p) for n, p in enumerate(prices)]
    return build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0,
                              max_discharge_w=0.0, peak_limit_w=11000.0)


def _plan(late_min=30, kwh=10.0):
    ev = Demand(id="ev:keba", kind="ev", energy_kwh=kwh, max_power_w=7400.0,
                min_power_w=1400.0, deadline=DEPART, late_s=late_min * 60,
                min_run_s=900, min_gap_s=900)
    return pack_night([ev], _ledger(NIGHT), peak_limit_w=11000.0)


# ── The packer marks the top-up ──────────────────────────────────────────

def test_only_the_top_up_is_marked_late():
    plan = _plan()
    late = [a for a in plan.allocations if a.late]
    rest = [a for a in plan.allocations if not a.late]
    assert late and rest
    assert all(a.end <= DEPART and a.start >= DEPART - timedelta(minutes=30)
               for a in late)
    assert all(a.end <= DEPART - timedelta(minutes=30) for a in rest)


def test_without_a_top_up_nothing_is_marked():
    assert not any(a.late for a in _plan(late_min=0).allocations)


def _blocks(plan):
    """The coordinator's stash shape for the plan's allocations."""
    return [{"id": a.demand_id, "start": a.start.isoformat(),
             "end": a.end.isoformat(), "power_w": round(a.power_w, 0),
             "price": a.price, **({"late": True} if a.late else {})}
            for a in plan.allocations]


def test_the_stash_carries_the_mark():
    """The coordinator's block dicts are built inline in the shadow plan:
    its parsed tree must copy ``late`` off the allocation."""
    import ast
    tree = ast.parse((ROOT / "coordinator" / "coordinator.py")
                     .read_text(encoding="utf-8"))
    found = False
    for node in ast.walk(tree):
        if (isinstance(node, ast.Dict)
                and any(isinstance(k, ast.Constant) and k.value == "power_w"
                        for k in node.keys)
                and any(isinstance(k, ast.Constant) and k.value == "price"
                        for k in node.keys)):
            src = ast.unparse(node)
            if "a.late" in src and "'late'" in src:
                found = True
    assert found, "the plan's blocks lost the top-up mark"


def test_the_merge_keeps_the_top_up_a_run_of_its_own():
    from custom_components.solar_energy_management.sensor import (
        _merge_plan_blocks,
    )
    t = lambda h, m=0: datetime(2026, 10, 10, h, m, tzinfo=ZRH).isoformat()  # noqa: E731
    merged = _merge_plan_blocks([
        {"id": "ev:keba", "start": t(5), "end": t(6), "power_w": 7400.0},
        {"id": "ev:keba", "start": t(6), "end": t(6, 30), "power_w": 7400.0},
        {"id": "ev:keba", "start": t(6, 30), "end": t(7), "power_w": 7400.0,
         "late": True},
    ])
    assert merged == [
        {"id": "ev:keba", "start": t(5), "end": t(6, 30), "power_w": 7400.0},
        {"id": "ev:keba", "start": t(6, 30), "end": t(7), "power_w": 7400.0,
         "late": True},
    ]


# ── The plan rows the strip walks ────────────────────────────────────────

NOW = datetime(2026, 10, 9, 21, 0, tzinfo=ZRH)


def _ev_rows(blocks):
    rows = compose_today_plan(now=NOW, ev_min_remaining_kwh=10.0,
                              ev_plan_blocks=blocks)
    return [r for r in rows
            if r["kind"] in (KIND_EV_CHARGE_START, KIND_EV_MIN_REACHED)]


def test_the_top_up_gets_its_own_start_row():
    rows = _ev_rows(_blocks(_plan()))
    starts = [r for r in rows if r["kind"] == KIND_EV_CHARGE_START]
    assert [r["detail"] for r in starts] == [
        "plan_ev_charge_joint", "plan_ev_charge_late"]
    late = starts[-1]
    assert late["when"] == (DEPART - timedelta(minutes=30)).isoformat()
    assert late["until"] == DEPART.isoformat()


def test_every_start_says_where_its_window_ends():
    """Without ``until`` the strip drew one charging bar from 02:00 to
    07:00 across the four hours the car waits."""
    rows = _ev_rows(_blocks(_plan()))
    first = next(r for r in rows if r["kind"] == KIND_EV_CHARGE_START)
    assert first["until"] < (DEPART - timedelta(minutes=30)).isoformat()
    assert [r["when"] for r in rows if r["kind"] == KIND_EV_MIN_REACHED] == [
        DEPART.isoformat()]


def test_a_top_up_touching_the_rest_is_still_its_own_window():
    t = lambda h, m=0: datetime(2026, 10, 10, h, m, tzinfo=ZRH).isoformat()  # noqa: E731
    rows = _ev_rows([
        {"start": t(5), "end": t(6, 30)},
        {"start": t(6, 30), "end": t(7), "late": True},
    ])
    starts = [r for r in rows if r["kind"] == KIND_EV_CHARGE_START]
    assert [(r["when"], r["detail"]) for r in starts] == [
        (t(5), "plan_ev_charge_joint"), (t(6, 30), "plan_ev_charge_late")]


def test_a_row_without_a_window_has_no_until():
    rows = compose_today_plan(now=NOW, ev_min_remaining_kwh=10.0,
                              night_start=NOW + timedelta(minutes=30))
    assert rows and all("until" not in r for r in rows)


# ── One view per charger ─────────────────────────────────────────────────

def _coordinator(charger, config=None, blocks=None):
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    c = SEMCoordinator.__new__(SEMCoordinator)
    c.hass = None
    c.config = {"ev_chargers": [charger], **(config or {})}
    c._ev_blocks_for = lambda cid, now=None: blocks
    return c


def test_the_view_says_what_the_rows_show(monkeypatch):
    from custom_components.solar_energy_management.coordinator import (
        coordinator as mod,
    )
    sunday = datetime(2026, 10, 11, 20, 0, tzinfo=ZRH)
    monkeypatch.setattr(mod.dt_util, "now", lambda: sunday)
    cfg = {"id": "keba", "ev_target_time": "07:00",
           "ev_departure_by_weekday": {"mon": "06:15", "sat": ""},
           "ev_plan_one_block": True, "ev_late_charge_min": 30}
    view = _coordinator(cfg)._departure_view("keba", cfg)
    assert view == {
        "default": "07:00",
        "by_weekday": {"mon": "06:15"},
        "next": datetime(2026, 10, 12, 6, 15, tzinfo=ZRH).isoformat(),
        "one_block": True,
        "late_min": 30,
        "late": None,              # nothing stamped for it
        "boost_allowed": True,
    }


def test_the_view_sums_the_stamped_top_up(monkeypatch):
    from custom_components.solar_energy_management.coordinator import (
        coordinator as mod,
    )
    monkeypatch.setattr(mod.dt_util, "now", lambda: NOW)
    cfg = {"id": "keba", "ev_late_charge_min": 30}
    plan = _plan()
    view = _coordinator(cfg, blocks=_blocks(plan))._departure_view("keba", cfg)
    late = [a for a in plan.allocations if a.late]
    assert view["late"] == {
        "start": min(a.start for a in late).isoformat(),
        "end": DEPART.isoformat(),
        "kwh": pytest.approx(round(sum(a.energy_kwh for a in late), 2)),
        "cost": pytest.approx(round(sum(a.energy_kwh * a.price for a in late), 2)),
    }


def test_the_view_tells_the_card_when_the_battery_may_not_feed_this_car(
        monkeypatch):
    from custom_components.solar_energy_management.coordinator import (
        coordinator as mod,
    )
    monkeypatch.setattr(mod.dt_util, "now", lambda: NOW)
    cfg = {"id": "keba", "ev_battery_may_assist": False}
    view = _coordinator(cfg)._departure_view("keba", cfg)
    assert view["boost_allowed"] is False
    assert view["late_min"] == 0 and view["late"] is None


def test_the_charging_state_sensor_publishes_it_per_charger():
    from custom_components.solar_energy_management.sensor import (
        SEMSolarSensor,
    )
    me = MagicMock()
    me.entity_description.key = "charging_state"
    boost = {"active": True, "charger_id": "keba", "floor_soc": 40.0,
             "remaining_kwh": 2.6}
    me.coordinator.data = {
        "charger_keba_departure": {"default": "07:00", "late_min": 30},
        "charger_zoe_departure": {"default": "08:00", "late_min": 0},
        "battery_boost": boost,
        "battery_boost_preview": {"default_floor": 50.0, "capacity_kwh": 10.0},
    }
    attrs = SEMSolarSensor._extra_state_attributes_base(me)
    assert attrs["per_charger_departure"] == {
        "keba": {"default": "07:00", "late_min": 30},
        "zoe": {"default": "08:00", "late_min": 0},
    }
    assert attrs["battery_boost"] == boost
    assert attrs["battery_boost_preview"]["default_floor"] == 50.0


def test_the_card_helpers_stay_out_of_the_recorder():
    from custom_components.solar_energy_management.sensor import (
        SEMSolarSensor,
    )
    for name in ("per_charger_departure", "battery_boost",
                 "battery_boost_preview"):
        assert name in SEMSolarSensor._unrecorded_attributes, name


def test_the_coordinator_publishes_the_view_per_charger():
    from .ast_contracts import calls
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    assert calls(SEMCoordinator._async_update_data, "_departure_view")
    assert calls(SEMCoordinator._async_update_data, "_battery_boost_preview")


def test_the_boost_preview_has_the_default_floor_and_the_capacity():
    c = _coordinator({"id": "keba"},
                     config={"battery_morning_drain_floor_soc": 35,
                             "battery_capacity_kwh": 12.5})
    assert c._battery_boost_preview() == {"default_floor": 35.0,
                                          "capacity_kwh": 12.5}
    c = _coordinator({"id": "keba"}, config={"battery_capacity_kwh": 10.0})
    assert c._battery_boost_preview()["default_floor"] == 50.0


def test_the_boost_remembers_where_it_started():
    """The card's bar: how far from the start toward the floor."""
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    c = SEMCoordinator.__new__(SEMCoordinator)
    c.hass = None
    c.config = {"battery_capacity_kwh": 10.0,
                "ev_chargers": [{"id": "keba", "charge_mode": "min_plus_solar",
                                 "ev_connected_sensor": "binary_sensor.plug"}]}
    c._battery_boost = None
    c._battery_boost_ended = None
    power = SimpleNamespace(ev_connected_per_charger={"keba": True},
                            ev_connected=True, battery_soc=80.0,
                            battery_soc_known=True)
    c._tick_battery_boost(power)
    c.start_battery_boost("keba", 40)
    status = c.battery_boost_status(SimpleNamespace(battery_soc=60.0))
    assert status["start_soc"] == 80.0 and status["soc"] == 60.0


# ── The write path: no reload ────────────────────────────────────────────

def _seed(hass):
    for eid, val, unit in (
        ("sensor.test_grid_power", "0", "W"),
        ("sensor.test_battery_power", "0", "W"),
        ("sensor.test_battery_soc", "50", "%"),
        ("sensor.test_solar_power", "0", "W"),
        ("sensor.test_ev_total_energy", "0", "kWh"),
        ("sensor.test_ev_charging_power", "0", "W"),
        ("number.test_charger_current", "0", "A"),
    ):
        hass.states.async_set(eid, val, {"unit_of_measurement": unit})
    hass.states.async_set("binary_sensor.test_ev_connected", "off")
    hass.states.async_set("binary_sensor.test_ev_charging", "off")


async def _setup(hass, entry):
    _seed(hass)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _stored(entry):
    chargers = (entry.options.get("ev_chargers")
                or entry.data.get("ev_chargers"))
    return next(c for c in chargers if c["id"] == "ev_charger")


@pytest.mark.asyncio
async def test_the_card_writes_without_a_reload(sem_real_hass, sem_config_entry):
    from custom_components.solar_energy_management.const import DOMAIN
    await _setup(sem_real_hass, sem_config_entry)
    before = sem_config_entry.runtime_data
    await sem_real_hass.services.async_call(
        DOMAIN, "set_charger_departure",
        {"charger_id": "ev_charger", "one_block": True, "late_charge_min": 45,
         "by_weekday": {"mon": "6:15", "sat": "", "sun": None}},
        blocking=True)
    await sem_real_hass.async_block_till_done()
    assert sem_config_entry.runtime_data is before, (
        "a click on the EV card reloaded SEM — and ended any running boost")
    stored = _stored(sem_config_entry)
    assert stored["ev_plan_one_block"] is True
    assert stored["ev_late_charge_min"] == 45
    assert stored["ev_departure_by_weekday"] == {"mon": "06:15"}
    # the running coordinator sees it at once (the demand signature re-plans)
    cfg = before._charger_cfg_by_id("ev_charger")
    assert cfg["ev_late_charge_min"] == 45
    # and the card reads it back on the charging-state sensor
    await before.async_refresh()
    await sem_real_hass.async_block_till_done()
    state = sem_real_hass.states.get("sensor.sem_charging_state")
    dep = state.attributes["per_charger_departure"]["ev_charger"]
    assert dep["one_block"] is True and dep["late_min"] == 45
    assert dep["by_weekday"] == {"mon": "06:15"}


@pytest.mark.asyncio
async def test_a_field_left_out_is_kept(sem_real_hass, sem_config_entry):
    from custom_components.solar_energy_management.const import DOMAIN
    await _setup(sem_real_hass, sem_config_entry)
    for data in ({"late_charge_min": 30}, {"one_block": True}):
        await sem_real_hass.services.async_call(
            DOMAIN, "set_charger_departure",
            {"charger_id": "ev_charger", **data}, blocking=True)
    stored = _stored(sem_config_entry)
    assert stored["ev_late_charge_min"] == 30
    assert stored["ev_plan_one_block"] is True
    assert stored["ev_target_time"] == "07:00"


@pytest.mark.asyncio
@pytest.mark.parametrize("data, key", [
    ({"charger_id": "ghost", "one_block": True}, "charger_not_found"),
    ({"charger_id": "ev_charger", "by_weekday": {"mon": "25:00"}},
     "departure_bad_time"),
    ({"charger_id": "ev_charger", "by_weekday": {"monday": "06:15"}},
     "departure_bad_time"),
])
async def test_a_bad_write_is_refused_with_its_reason(
        sem_real_hass, sem_config_entry, data, key):
    from homeassistant.exceptions import ServiceValidationError

    from custom_components.solar_energy_management.const import DOMAIN
    await _setup(sem_real_hass, sem_config_entry)
    with pytest.raises(ServiceValidationError) as err:
        await sem_real_hass.services.async_call(
            DOMAIN, "set_charger_departure", data, blocking=True)
    assert err.value.translation_key == key
    assert "ev_departure_by_weekday" not in _stored(sem_config_entry)


@pytest.mark.asyncio
async def test_more_than_two_hours_of_top_up_is_refused(
        sem_real_hass, sem_config_entry):
    import voluptuous as vol

    from custom_components.solar_energy_management.const import DOMAIN
    await _setup(sem_real_hass, sem_config_entry)
    with pytest.raises(vol.Invalid):
        await sem_real_hass.services.async_call(
            DOMAIN, "set_charger_departure",
            {"charger_id": "ev_charger", "late_charge_min": 180}, blocking=True)


def test_the_service_is_described_and_unloaded():
    import ast

    import yaml
    described = yaml.safe_load((ROOT / "services.yaml").read_text(encoding="utf-8"))
    assert "set_charger_departure" in described
    fields = set(described["set_charger_departure"]["fields"])
    assert fields == {"charger_id", "by_weekday", "one_block", "late_charge_min"}
    tree = ast.parse((ROOT / "__init__.py").read_text(encoding="utf-8"))
    unloaded = [n for n in ast.walk(tree) if isinstance(n, ast.Tuple)
                and any(isinstance(e, ast.Constant)
                        and e.value == "start_battery_boost" for e in n.elts)]
    assert unloaded and all(
        any(isinstance(e, ast.Constant) and e.value == "set_charger_departure"
            for e in n.elts) for n in unloaded)


def test_the_refusals_are_translated():
    for lang in sorted((ROOT / "translations").glob("*.json")):
        ex = json.loads(lang.read_text(encoding="utf-8"))["exceptions"]
        for key, ph in (("charger_not_found", {"charger"}),
                        ("departure_bad_time", {"day", "time"})):
            msg = ex[key]["message"]
            assert {p for p in ph if "{" + p + "}" in msg} == ph, (lang.name, key)


# ── The card's strings ───────────────────────────────────────────────────

CARD_KEYS = (
    "ev_dep_most_days", "ev_dep_next", "ev_dep_tap_hint", "ev_dep_use_default",
    "ev_dep_one_block", "ev_dep_late_charge", "ev_dep_late_off",
    "ev_dep_minutes", "ev_dep_late_hint", "ev_dep_late_hint_plan",
    "ev_dep_help_days", "ev_dep_help_one_block", "ev_dep_help_late",
    "ev_boost_title", "ev_boost_down_to", "ev_boost_start", "ev_boost_stop",
    "ev_boost_hint", "ev_boost_left", "ev_boost_ends", "ev_boost_not_permitted",
    "ev_boost_last_end", "ev_boost_end_unplugged", "ev_boost_end_mode_changed",
    "ev_boost_end_permission_off", "ev_boost_end_floor", "ev_boost_end_stopped",
    "ev_boost_end_charger_removed", "ev_boost_help", "plan_strip_late",
    "plan_ev_charge_late",
)


def test_every_card_key_the_rows_use_is_in_every_language():
    import re
    src = (ROOT / "dashboard" / "card" / "src" / "cards"
           / "sem-ev-status-card.js").read_text(encoding="utf-8")
    used = set(re.findall(r"'((?:ev_dep|ev_boost)_[a-z_]+)'", src))
    assert used and used <= set(CARD_KEYS), used - set(CARD_KEYS)
    tables = json.loads((ROOT / "dashboard" / "translations.json")
                        .read_text(encoding="utf-8"))
    en = tables["en"]
    for lang, table in tables.items():
        for key in CARD_KEYS:
            assert table.get(key), (lang, key)
            want = set(re.findall(r"\{(\w+)\}", en[key]))
            assert set(re.findall(r"\{(\w+)\}", table[key])) == want, (lang, key)


def test_the_boost_end_reasons_the_card_translates_are_the_ones_it_gets():
    """The card maps the coordinator's end reasons to sentences; a reason it
    does not know would print the raw English words."""
    import ast
    import re
    reasons = set()
    for path in ("coordinator/battery_boost.py", "coordinator/coordinator.py"):
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "attr", None) == "stop_battery_boost"
                    and node.args and isinstance(node.args[0], ast.Constant)):
                reasons.add(node.args[0].value)
            if (isinstance(node, ast.FunctionDef)
                    and node.name in ("boost_end_reason", "stop_battery_boost")):
                for r in ast.walk(node):
                    if (isinstance(r, (ast.Return, ast.arg))
                            and isinstance(getattr(r, "value", None), ast.Constant)
                            and isinstance(r.value.value, str)):
                        reasons.add(r.value.value)
    reasons.add("stopped")       # stop_battery_boost's default, the service's
    src = (ROOT / "dashboard" / "card" / "src" / "cards"
           / "sem-ev-status-card.js").read_text(encoding="utf-8")
    block = src[src.index("const REASONS = {"):]
    block = block[:block.index("};")]
    mapped = set(re.findall(r"'([a-z ]+)': 'ev_boost_end_", block))
    assert reasons == mapped, reasons ^ mapped
