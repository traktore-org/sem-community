"""#1362 — the plan keeps the pack where SEM keeps it.

@matekogon (G12w, two batteries, "keep the battery in cheap hours" on): on
26.11 SEM held the battery 13:00 – 15:00, the cheap midday hours. The house
bought from the grid and the hold select set the inverter to "Utility". The
Plan card showed "Battery to the house 13:00 – 19:00": the plan's battery walk
let the pack cover the house in every hour. The live rule
(``sink_verdicts``: the house sink HELD in a cheap hour, 0 W discharge) was
not in the plan.

Now ONE rule (``house_keeps_pack``) answers both. A kept slot: the house buys,
and the pack covers only what the meter may not buy over the peak limit (the
live #1003 cover). The plan keeps the pack only when every battery's mode
reaches the live hold (``plan_house_sink``).
"""
import ast
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import coordinator as coord_mod
from custom_components.solar_energy_management.coordinator.arbitrage import (
    arbitrage_advice,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.energy_planner import (
    Demand,
    LedgerSlot,
    battery_at_end,
    build_night_ledger,
    pack_night,
    takeover_of,
)
from custom_components.solar_energy_management.coordinator.price_signal import (
    is_cheap_name,
)
from custom_components.solar_energy_management.coordinator.sink_verdicts import (
    HELD,
    house_keeps_pack,
    plan_house_sink,
    sink_verdicts,
)
from custom_components.solar_energy_management.tariff.tariff_provider import PriceLevel

from .test_638_shadow_mode import (  # noqa: F401 — fixtures come along
    _fake_self, _power, _scheduler, freeze_targets,
)

PKG = Path(__file__).resolve().parent.parent
T0 = datetime(2026, 11, 26, 12, 0, tzinfo=coord_mod.dt_util.DEFAULT_TIME_ZONE)

#: the report's afternoon, G12w: 12–13 dear, 13–15 cheap, 15–18 dear
DAY = [(12, False), (13, True), (14, True), (15, False), (16, False), (17, False)]


def _slots(home_w=500.0, day=DAY, price_cheap=0.64, price_dear=1.25):
    return [LedgerSlot(start=T0.replace(hour=h), end=T0.replace(hour=h) + timedelta(hours=1),
                       price=price_cheap if cheap else price_dear,
                       level_cheap=cheap, tariff_cheap=cheap, home_w=home_w)
            for h, cheap in day]


def _ledger(on, slots=None, peak_w=0.0, soc=10.0, floor=0.0):
    return build_night_ledger(
        slots if slots is not None else _slots(), soc_kwh=soc, floor_kwh=floor,
        max_discharge_w=5000.0, peak_limit_w=peak_w, capacity_kwh=15.0,
        house_sink_enabled=on)


def _cheap_hours(ledger):
    return [s for s in ledger if s.level_cheap]


# ── the report ────────────────────────────────────────────────────────────

def test_the_report_cheap_midday_hours_keep_the_pack():
    """13:00 – 15:00: SEM held the pack; the plan now does too. The house
    buys there, and the pack covers it in the dear hours either side."""
    ledger = _ledger(True)
    for s in ledger:
        if s.level_cheap:
            assert s.pack_kept
            assert s.home_batt_kwh == 0.0, f"{s.start:%H}: the pack fed the house"
            assert s.home_grid_w == pytest.approx(500.0)
        else:
            assert not s.pack_kept
            assert s.home_batt_kwh == pytest.approx(0.5), f"{s.start:%H}"
            assert s.home_grid_w == pytest.approx(0.0)
    # the trajectory does not fall through the kept hours
    kept = _cheap_hours(ledger)
    assert kept[0].soc_kwh == pytest.approx(kept[-1].soc_kwh)


def test_switch_off_the_pack_covers_every_hour():
    """The old plan, unchanged with the switch off (the default)."""
    ledger = _ledger(False)
    assert not any(s.pack_kept for s in ledger)
    assert all(s.home_batt_kwh == pytest.approx(0.5) for s in ledger)


def test_the_kept_energy_is_spent_later():
    """What the kept hours save is in the pack at the end."""
    on = battery_at_end(_ledger(True), 0.0, 15.0)
    off = battery_at_end(_ledger(False), 0.0, 15.0)
    assert on["kwh"] == pytest.approx(off["kwh"] + 2 * 0.5)


# ── one rule, two readers ─────────────────────────────────────────────────

LEVELS = [lv.value for lv in PriceLevel] + [None, "", "flat", "no_prices", "unknown"]


def _live_held(level, on):
    v = sink_verdicts(
        now=T0, tariff_level=level, upcoming=None, export_rate=None,
        export_rate_known=False, export_guard_enabled=False,
        house_sink_enabled=on, morning_window_enabled=False, departure=None,
        morning_hours=2.0, forecast_refills_pack=False, pacing_horizon_end=None)
    return v["house"].state == HELD


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("on", [True, False])
@pytest.mark.parametrize("sun", [False, True])
def test_the_plan_keeps_the_pack_exactly_where_the_live_hold_does(level, on, sun):
    """The oracle: for every level word and both switch states, a slot at
    that level is kept iff the live verdict holds the house. A sun slot's
    ``level_cheap`` is the packer's True; its own word is ``import_cheap``."""
    cheap = is_cheap_name(level)
    s = LedgerSlot(start=T0, end=T0 + timedelta(hours=1), price=1.0,
                   level_cheap=True if sun else cheap, tariff_cheap=cheap,
                   home_w=0.0 if sun else 500.0,
                   cap_override_w=800.0 if sun else None,
                   import_cheap=cheap if sun else False)
    _ledger(on, slots=[s])
    assert s.pack_kept is _live_held(level, on)


def test_the_live_verdict_asks_the_shared_rule():
    """AST: the live house verdict calls ``house_keeps_pack`` — no second
    copy of the rule beside it."""
    tree = ast.parse((PKG / "coordinator/sink_verdicts.py").read_text())
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "sink_verdicts")
    calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
             and getattr(c.func, "id", None) == "house_keeps_pack"]
    assert calls, "the live house verdict no longer asks house_keeps_pack"
    assert house_keeps_pack(True, True) and not house_keeps_pack(False, True)
    assert not house_keeps_pack(True, False)


def test_every_plan_ledger_in_the_coordinator_reads_the_switch():
    """AST: each ``build_night_ledger`` call in the coordinator (tonight's
    plan, tomorrow's preview) passes ``house_sink_enabled`` from
    ``plan_house_sink`` — the switch and the battery modes, one reader."""
    src = (PKG / "coordinator/coordinator.py").read_text()
    tree = ast.parse(src)
    calls = [c for c in ast.walk(tree) if isinstance(c, ast.Call)
             and getattr(c.func, "id", None) == "build_night_ledger"]
    assert len(calls) >= 2, "a plan ledger moved; check this guard"
    for c in calls:
        kw = {k.arg: k for k in c.keywords}
        assert "house_sink_enabled" in kw, f"line {c.lineno}: no house_sink_enabled"
        assert ast.unparse(kw["house_sink_enabled"].value) == (
            "plan_house_sink(self.config, getattr(self, '_battery_adapters', None))")


# ── the cover and the loads under the hold ───────────────────────────────

def test_a_kept_hour_covers_only_what_the_meter_may_not_buy():
    """Live, the hold keeps a floor: the pack covers the house over the peak
    limit (#1003). The plan's kept hour does the same, and nothing more."""
    ledger = _ledger(True, slots=_slots(home_w=3000.0), peak_w=2000.0, soc=14.0)
    for s in _cheap_hours(ledger):
        assert s.home_batt_kwh == pytest.approx(1.0)
        assert s.home_grid_w == pytest.approx(2000.0)
    # under the limit: no cover at all
    ledger = _ledger(True, slots=_slots(home_w=1500.0), peak_w=2000.0)
    assert all(s.home_batt_kwh == 0.0 for s in _cheap_hours(ledger))


def _battery_load():
    return Demand(id="load:pump", kind="load", energy_kwh=0.5,
                  max_power_w=500.0, min_power_w=500.0, source="battery")


def test_a_battery_run_load_is_booked_as_before_in_a_kept_hour():
    """Live, the battery-run load rule does not ask the hold: the load runs
    (on grid power under the 0 W limit). Dropping it would tell the user it
    does not run. So the packer books it as before (left open: the plan
    draws it from the pack)."""
    only_cheap = [(13, True), (14, True)]
    booked = []
    for on in (True, False):
        ledger = _ledger(on, slots=_slots(day=only_cheap))
        plan = pack_night([_battery_load()], ledger, max_discharge_w=5000.0)
        booked.append(sorted((a.start, round(a.energy_kwh, 3))
                             for a in plan.allocations if a.demand_id == "load:pump"))
    assert booked[0], "the load was dropped from the kept hours"
    assert booked[0] == booked[1]


def test_the_takeover_hour_is_not_a_kept_hour():
    """``takeover_of`` names the hour the pack is done. A kept hour buys on
    purpose: the takeover stays where the pack really runs out."""
    assert takeover_of(_ledger(True)) is None
    assert takeover_of(_ledger(False)) is None
    # a small pack: it runs out in the dear evening, not at 13:00
    ledger = _ledger(True, soc=1.2)
    assert takeover_of(ledger) == T0.replace(hour=16)


# ── the battery modes ────────────────────────────────────────────────────

@pytest.mark.parametrize("cfg,want", [
    ({}, False),
    ({"battery_house_sink_enabled": False}, False),
    ({"battery_house_sink_enabled": True}, True),
    ({"battery_house_sink_enabled": True, "battery_mode": "self_consumption"}, True),
    ({"battery_house_sink_enabled": True, "battery_mode": "off"}, False),
    ({"battery_house_sink_enabled": True, "battery_mode": "force_charge"}, False),
    ({"battery_house_sink_enabled": True, "battery_mode": "force_discharge"}, False),
    # the report: two packs, both self-consumption
    ({"battery_house_sink_enabled": True,
      "battery_modes": ["self_consumption", "self_consumption"]}, True),
    # one pack left to the inverter: not held live, planned as before
    ({"battery_house_sink_enabled": True, "battery_modes": ["auto", "off"]}, False),
    # an empty slot reads the shared mode
    ({"battery_house_sink_enabled": True, "battery_mode": "off",
      "battery_modes": ["", None]}, False),
    ({"battery_house_sink_enabled": True, "battery_modes": ["", "auto"]}, True),
])
def test_the_plan_keeps_the_pack_only_where_every_mode_reaches_the_hold(cfg, want):
    """``decide_battery`` returns for "off" and the manual modes before the
    house sink: those packs are not held live."""
    assert plan_house_sink(cfg) is want


class _Ctl:
    """A battery control as ``discharge_limit_gap`` answers for 0 W."""

    def __init__(self, gap=None, boom=False):
        self.gap, self.boom = gap, boom

    def discharge_limit_gap(self, watts):
        assert watts == 0.0
        if self.boom:
            raise RuntimeError("cannot say")
        return self.gap


@pytest.mark.parametrize("adapters,want", [
    (None, True),                       # none built yet: as the switch says
    ({}, True),
    ({"b1": _Ctl(), "b2": _Ctl()}, True),
    # the report: a hold select on both packs answers no gap at 0 W
    ({"b1": _Ctl(None), "b2": _Ctl(None)}, True),
    # #1427: one pack with no way to cap is not held live
    ({"b1": _Ctl(), "b2": _Ctl("no discharge-limit entity set")}, False),
    ({"b1": _Ctl("hold refused lately")}, False),
    ({"b1": _Ctl(boom=True)}, False),
    ({"b1": object()}, True),           # a control with no such question
])
def test_the_plan_keeps_only_packs_sem_can_hold(adapters, want):
    """Live, a 0 W limit on a pack with no control caps nothing (#1427):
    the inverter covers the house. The plan does not keep such a pack."""
    assert plan_house_sink({"battery_house_sink_enabled": True}, adapters) is want


def test_the_real_generic_adapter_answers_for_the_report():
    """The reporter's control: no limit number, a hold select with an
    option. The real ``GenericBatteryAdapter`` says it can hold at 0 W, and
    without the hold pair it cannot."""
    from types import SimpleNamespace as NS

    from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
        GenericBatteryAdapter,
    )
    hass = MagicMock()
    hass.states.get = lambda eid: NS(state="SBU", attributes={
        "options": ["Utility", "Solar", "SBU"]})
    held = GenericBatteryAdapter(hass, {
        "battery_hold_select_entity": "select.output_source_priority",
        "battery_hold_select_option": "Utility"})
    bare = GenericBatteryAdapter(hass, {})
    on = {"battery_house_sink_enabled": True}
    assert plan_house_sink(on, {"b1": held, "b2": held}) is True
    assert plan_house_sink(on, {"b1": held, "b2": bare}) is False


def test_turning_the_switch_is_a_new_night():
    """The plan's change check reads the switch: turning it on re-plans."""
    from .test_638_demand_replan import _coord, _power as _p
    c = _coord(prices=())
    off = c._energy_plan_demand_signature(_p())
    c.config["battery_house_sink_enabled"] = True
    on = c._energy_plan_demand_signature(_p())
    assert ("keep_pack", False) in off and ("keep_pack", True) in on
    assert coord_mod.demand_signature_changed(off, on)


def test_the_arbitrage_advice_never_delivers_into_a_kept_hour():
    """The shadow advice pairs a buy with a later hour where the house buys.
    A kept hour buys on purpose: it is never a delivery hour. The dear hour
    after it still is, so the advice is not empty."""
    def slot(h, price, cheap):
        return LedgerSlot(start=T0.replace(hour=h),
                          end=T0.replace(hour=h) + timedelta(hours=1),
                          price=price, level_cheap=cheap, tariff_cheap=cheap,
                          home_w=500.0)
    ledger = _ledger(True, slots=[slot(1, 0.05, False), slot(13, 0.64, True),
                                  slot(15, 1.25, False)], soc=0.0)
    adv = arbitrage_advice(ledger, soc_kwh=0.0, capacity_kwh=15.0,
                           max_charge_w=5000.0, max_discharge_w=5000.0,
                           round_trip_efficiency=0.9, cycle_cost_per_kwh=0.0)
    hours = {r["start"].hour for r in adv.discharge_blocks}
    assert 15 in hours, "no delivery at all: the test proves nothing"
    assert 13 not in hours, "the advice spent the pack in a kept hour"


# ── the real planner ──────────────────────────────────────────────────────

class _G12Tariff:
    """Cheap 02:00 – 04:00 at the cheap LEVEL, dearer elsewhere."""

    def get_price_at(self, t):
        return 0.10 if t.hour in (2, 3) else 0.28

    def get_price_level_at(self, t):
        return "cheap" if t is not None and t.hour in (2, 3) else "normal"

    def get_price_level(self):
        return "normal"


def _real_plan(on):
    fake = _fake_self()
    fake._tariff_provider = _G12Tariff()
    fake.config["battery_house_sink_enabled"] = on
    SEMCoordinator._shadow_energy_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(), power=_power(soc=90.0))
    plan = fake._energy_plan_shadow
    assert isinstance(plan, dict) and plan["slots"], "the planner made no plan"
    return plan


def _at(slot, *hours):
    return datetime.fromisoformat(slot["start"]).hour in hours


def test_the_real_plan_shows_the_house_on_the_grid_in_kept_hours(freeze_targets):
    """``_shadow_energy_plan`` end to end: with the switch on, the published
    02:00 – 04:00 slots carry no battery mark and the house is on the grid;
    the other hours keep the mark.

    The plan runs from "now" to the night's end, so the clock is pinned to
    an evening: run after 04:00 the 02:00 – 04:00 hours are already past and
    the test found no cheap slot (it failed in the morning, passed at night).
    """
    from freezegun import freeze_time

    with freeze_time(T0.replace(hour=20)):
        on = _real_plan(True)
        off = _real_plan(False)
    cheap = [s for s in on["slots"] if _at(s, 2, 3)]
    dear = [s for s in on["slots"] if not _at(s, 2, 3)]
    assert cheap and dear
    assert not any(s.get("batt") for s in cheap)
    assert all(s["home_grid_w"] > 0 for s in cheap)
    assert all(s.get("batt") for s in dear)
    # the switch off: the same night marks every hour
    assert all(s.get("batt") for s in off["slots"])


# ── the cheap word from a real provider ──────────────────────────────────

def test_the_report_tariff_plan_and_live_agree_every_hour_of_a_week():
    """The reporter's G12w as a real ``CalendarTariffProvider``: for every
    hour of a week, the plan's word for that hour (``PriceView.cheap_at``,
    asked a day ahead) equals the live verdict's word at that hour
    (``compared_level`` of now). The oracle above checks the rule; this
    checks the two cheap words feeding it."""
    from freezegun import freeze_time

    from custom_components.solar_energy_management.coordinator.price_view import (
        PriceView, answer_for_level,
    )

    from .test_1310_one_rate_day_is_cheap import SAT, _g12w

    p = _g12w(peak=1.25, off_peak=0.64)
    start = SAT.replace(hour=0)
    seen = set()
    for n in range(7 * 24):
        t = start + timedelta(hours=n)
        with freeze_time(t - timedelta(days=1)):
            plan_word = PriceView(p).cheap_at(t)
        with freeze_time(t):
            live_word = answer_for_level(PriceView(p).compared_level()).is_cheap
        assert plan_word is live_word, f"{t:%a %H}:00"
        seen.add(plan_word)
    assert seen == {True, False}, "one word all week: the test proves nothing"
