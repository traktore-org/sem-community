"""#638 G3c — the shadow plan's UI surface: sensor + ledger-strip card.

The planner has been correct and invisible: the only way to read a night's
plan was to grep the log for ``OVERNIGHT-PLAN`` or call the ``diagnose``
service. This module pins the contract that makes it visible:

* the stash carries a STRUCTURED payload (``demands``/``slots``/``blocks``)
  beside the log-shaped ``summary`` strings — the card must never have to
  parse a sentence like "ev:x: YIELDS 1.5 kWh" back apart;
* the "nothing needs the night" answer has the SAME keys, empty, so the card
  renders it from the shape rather than treating a missing key as an error;
* the sensor's STATE is a short verdict word (a dict there would stringify
  past HA's 255-char state limit and be rejected outright);
* every string the card localizes exists in all 16 dashboard languages.
"""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator import ev_night_targets
from custom_components.solar_energy_management.sensor import (
    _PLAN_ATTR_BUDGET_BYTES,
    _overnight_plan_attrs,
    _overnight_plan_state,
)

from .test_638_shadow_mode import (  # noqa: F401 — fixtures come along
    _fake_self, _fake_load, _idle_load, _power, _scheduler, _freeze_now,
    freeze_targets,
)

REPO = Path(__file__).resolve().parent.parent
CARD_SRC = REPO / "dashboard" / "card" / "src" / "cards" / "sem-energy-plan-card.js"

# Every key the card asks ``semLocalize`` for. Kept as a literal list rather
# than scraped from the source: a typo'd key in the card would otherwise
# "verify" itself.
CARD_KEYS = [
    "overnight_plan_title", "overnight_shadow", "overnight_fits",
    "overnight_yields", "overnight_idle", "overnight_takeover",
    "overnight_all_night", "overnight_all_night_short", "overnight_home",
    "overnight_est",
    "overnight_legend_battery", "overnight_legend_grid",
    "overnight_legend_cheap", "overnight_fleet_partial",
    "overnight_shadow_note", "overnight_kind_ev", "overnight_kind_load",
    "overnight_today", "overnight_tomorrow", "overnight_prices_final",
    "overnight_prices_preliminary", "overnight_prices_final_tip",
    "overnight_prices_preliminary_tip", "overnight_legend_surplus",
    "overnight_stamps_at", "overnight_tomorrow_asks",
    "overnight_provisional", "overnight_provisional_tip",
    "overnight_legend_battery_charge",
    "overnight_kind_battery", "overnight_kind_comfort",
    "overnight_comfort_tip", "overnight_arbitrage", "overnight_arbitrage_tip",
    "overnight_strip_omitted",
]


# ---------------------------------------------------------------------------
# The structured payload
# ---------------------------------------------------------------------------

def test_plan_carries_structured_rows_beside_the_prose(freeze_targets):
    fake = _fake_self(devices=[_fake_load()])
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(), energy=MagicMock(), phantom_ev_kwh=10.0,
        phantom_ev_w=11000.0, power=_power())
    plan = fake._overnight_shadow_plan

    # The prose the logs and the soak notes quote is UNCHANGED.
    assert plan["summary"] and plan["allocations"]

    demands = plan["demands"]
    assert demands, "expected one structured row per demand"
    ids = {d["id"] for d in demands}
    assert "ev:ev_charger" in ids and "load:pump" in ids
    for d in demands:
        assert set(d) >= {"id", "kind", "label", "status", "planned_kwh",
                          "needed_kwh", "est_cost", "note"}
        assert d["kind"] in ("ev", "load", "battery")
        assert d["status"] in ("fits", "partial", "yields")

    slots = plan["slots"]
    assert slots, "the ledger is the card's time axis — it must be published"
    for s in slots:
        assert set(s) >= {"start", "end", "price", "cheap", "home_w",
                          "soc_kwh", "home_grid_w"}
    # ``end`` is carried explicitly: the last slot has no successor to
    # infer it from, and 15-minute curves are not hourly.
    assert all(s["end"] > s["start"] for s in slots)

    for b in plan["blocks"]:
        assert set(b) >= {"id", "start", "end", "power_w", "price"}
        assert b["id"] in ids


def test_takeover_is_published_for_the_battery_row(freeze_targets):
    """The hour the battery stops covering the house alone is the one thing
    the ledger strip exists to show. It rides as ``takeover`` AND is
    re-derivable per slot from ``home_grid_w`` — the card shades from the
    latter, so the two must agree."""
    fake = _fake_self(devices=[_fake_load()])
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(), energy=MagicMock(), phantom_ev_kwh=10.0,
        phantom_ev_w=11000.0, power=_power())
    plan = fake._overnight_shadow_plan
    first_grid = next((s["start"] for s in plan["slots"]
                       if s["home_grid_w"] > 0), None)
    assert plan["takeover"] == first_grid


def test_no_demand_night_has_the_same_shape(freeze_targets, monkeypatch):
    """'Nothing needs the night' must be renderable from the SHAPE. If the
    empty answer dropped the keys, the card would have to treat a legitimate
    quiet night as a malformed plan."""
    monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                        lambda coord, energy: {})
    fake = _fake_self(devices=[_idle_load()])
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(), phantom_ev_kwh=0.0,
        phantom_ev_w=0.0, power=_power())
    plan = fake._overnight_shadow_plan
    assert isinstance(plan, dict)
    assert plan["demands"] == [] and plan["slots"] == [] and plan["blocks"] == []
    assert plan["summary"], "the quiet night still says so out loud"


# ---------------------------------------------------------------------------
# The sensor state
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("plan,expected", [
    (None, "pending"),
    ("not-a-dict", "pending"),
    ({}, "idle"),
    ({"demands": []}, "idle"),
    ({"demands": [{"id": "ev:x"}], "fits": True}, "fits"),
    ({"demands": [{"id": "ev:x"}], "fits": False}, "yields"),
    ({"demands": [{"id": "ev:x"}]}, "yields"),
])
def test_verdict_state_mapping(plan, expected):
    assert _overnight_plan_state(plan) == expected


def test_state_never_exceeds_has_limit(freeze_targets):
    """A dict in the state slot stringifies past 255 chars and HA REJECTS the
    write — the entity would go unavailable rather than merely look wrong."""
    fake = _fake_self(devices=[_fake_load()])
    SEMCoordinator._shadow_overnight_plan(
        fake, _scheduler(), energy=MagicMock(), phantom_ev_kwh=10.0,
        phantom_ev_w=11000.0, power=_power())
    state = _overnight_plan_state(fake._overnight_shadow_plan)
    assert isinstance(state, str) and 0 < len(state) <= 255


def test_sensor_description_is_registered():
    from custom_components.solar_energy_management.sensor import SENSOR_TYPES
    keys = {d.key for d in SENSOR_TYPES}
    assert "energy_plan" in keys


# ---------------------------------------------------------------------------
# The attribute projection
#
# HA's recorder stores NO attributes at all for a state whose attributes
# serialize above MAX_STATE_ATTRS_BYTES (16 KiB) — it logs a warning and drops
# the lot. A plan that silently vanished from history every night would be
# worse than one that visibly shows less, so the projection is budgeted.
# ---------------------------------------------------------------------------

def _synthetic_plan(*, slots, demands, blocks_per_demand, minutes=15):
    """A night of a given shape. 64 quarter-hour slots is a real 16-hour
    winter night on a 15-minute market, not a pathological case."""
    from datetime import datetime, timedelta, timezone
    t = datetime(2026, 1, 15, 16, 0, tzinfo=timezone(timedelta(hours=1)))
    step = timedelta(minutes=minutes)
    return {
        "computed_at": t.isoformat(),
        "fits": False,
        "total_cost": 4.56,
        "takeover": (t + 6 * step).isoformat(),
        "summary": ["OVERNIGHT-PLAN (shadow): " + "x" * 90] * 8,
        "allocations": ["ev:charger 22:00-23:00 4140 W @ 0.2345"] * 40,
        "demands": [{
            "id": f"load:device_{d}", "kind": "load",
            "label": "Warmwasser Wärmepumpe", "status": "partial",
            "planned_kwh": 3.21, "needed_kwh": 4.56, "est_cost": 1.23,
            "note": "peak cap reached at 03:00 — 1.4 kWh could not be placed",
        } for d in range(demands)],
        "slots": [{
            "start": (t + i * step).isoformat(),
            "end": (t + (i + 1) * step).isoformat(),
            "price": 0.2345, "cheap": bool(i % 3),
            "home_w": 451.7, "soc_kwh": 9.87, "home_grid_w": 451.7,
        } for i in range(slots)],
        # Per-slot allocations in the order the packer really emits them:
        # SLOT-major, every demand for a slot before moving to the next. A
        # demand's own consecutive blocks are therefore NOT neighbours here
        # — a demand-major fixture would let a broken merge look correct.
        "blocks": [{
            "id": f"load:device_{d}",
            "start": (t + i * step).isoformat(),
            "end": (t + (i + 1) * step).isoformat(),
            "power_w": 2300.0, "price": 0.2345,
        } for i in range(blocks_per_demand) for d in range(demands)],
    }


def _size(attrs):
    return len(json.dumps(attrs, default=str))


def test_projection_leaves_the_prose_and_the_trajectory_behind():
    attrs = _overnight_plan_attrs(
        _synthetic_plan(slots=8, demands=2, blocks_per_demand=2))
    assert "summary" not in attrs and "allocations" not in attrs
    for s in attrs["slots"]:
        assert set(s) == {"start", "end", "price", "cheap", "home_grid_w"}
    # The card needs the verdict context even when the strip is intact.
    assert set(attrs) >= {"computed_at", "fits", "total_cost", "takeover",
                          "demands", "slots", "blocks"}


def test_the_projection_carries_the_arbitrage_advice():
    """(#638, the last string) The advisor's verdict must reach the
    entity — the morning plan-vs-Sankey audit reads it there."""
    attrs = _overnight_plan_attrs(
        {"arbitrage": {"opportunity": False, "reason": "no priced market"},
         "demands": [], "slots": [], "blocks": []})
    assert attrs["arbitrage"]["reason"] == "no priced market"


def test_the_idle_answer_carries_its_why():
    """(Guido, 08-08: uncapping a device made the plan 'disappear') — the
    quiet answer was CORRECT but unexplained on the card: the why lived
    only in diagnose. The projection now carries it."""
    attrs = _overnight_plan_attrs(
        {"why": "ev_targets={}, loads_eligible=0", "demands": [],
         "slots": [], "blocks": []})
    assert attrs["why"] == "ev_targets={}, loads_eligible=0"


def test_the_projection_carries_the_replan_cause():
    """Night-3 finding 3: a re-stamped night must be distinguishable from
    the first answer on the entity, not only in container logs (which
    rotate too fast to serve as evidence)."""
    attrs = _overnight_plan_attrs(
        {"replan_cause": "ask changed", "demands": [], "slots": [],
         "blocks": []})
    assert attrs["replan_cause"] == "ask changed"


def test_contiguous_allocations_merge_into_one_run():
    """The packer allocates per market slot; the strip draws a run. Merging is
    invisible to the card and is what keeps a 15-minute night chartable.

    Note the fixture is SLOT-major (see ``_synthetic_plan``): merging has to
    group by demand first. A version that only compared each block with its
    predecessor merged nothing live and still passed a demand-major test."""
    attrs = _overnight_plan_attrs(
        _synthetic_plan(slots=16, demands=2, blocks_per_demand=4))
    assert len(attrs["blocks"]) == 2, "4 back-to-back slots are one bar"
    for b in attrs["blocks"]:
        assert b["start"].endswith("16:00:00+01:00")
        assert b["end"].endswith("17:00:00+01:00")
        # A merged run spans slots that may differ in price — quoting one
        # would be a lie, so the projection carries none. diagnose has them.
        assert "price" not in b


def test_merge_handles_the_shape_ha_test_actually_published():
    """Verbatim from ``sensor.sem_overnight_plan`` on HA-TEST, 2026-08-04
    04:58 — two demands over two contiguous hours. The first merge shipped
    green against a demand-major fixture and collapsed NOTHING here."""
    live = [
        {"id": "ev:keba_fa87f74cd3", "start": "2026-08-04T05:00:00+02:00",
         "end": "2026-08-04T06:00:00+02:00", "power_w": 5800.0, "price": 0.3387},
        {"id": "load:sim_pool_pump", "start": "2026-08-04T05:00:00+02:00",
         "end": "2026-08-04T06:00:00+02:00", "power_w": 1500.0, "price": 0.3387},
        {"id": "ev:keba_fa87f74cd3", "start": "2026-08-04T06:00:00+02:00",
         "end": "2026-08-04T06:01:00+02:00", "power_w": 5800.0, "price": 0.3387},
        {"id": "load:sim_pool_pump", "start": "2026-08-04T06:00:00+02:00",
         "end": "2026-08-04T06:01:00+02:00", "power_w": 1500.0, "price": 0.3387},
    ]
    merged = _overnight_plan_attrs({"demands": [1], "blocks": live})["blocks"]
    assert len(merged) == 2
    assert {b["id"] for b in merged} == {"ev:keba_fa87f74cd3",
                                         "load:sim_pool_pump"}
    for b in merged:
        assert b["start"] == "2026-08-04T05:00:00+02:00"
        assert b["end"] == "2026-08-04T06:01:00+02:00"


def test_a_gap_between_allocations_is_not_merged_away():
    plan = _synthetic_plan(slots=16, demands=1, blocks_per_demand=4)
    del plan["blocks"][2]  # the pump pauses for a quarter-hour
    blocks = _overnight_plan_attrs(plan)["blocks"]
    assert len(blocks) == 2, "an anti-cycle pause must stay visible"


def test_a_real_fifteen_minute_night_keeps_its_timeline():
    """The case that made this budget necessary: a 16-hour winter night on a
    quarter-hour market, six demands. Before merging this was 18 KB and the
    card lost its chart entirely."""
    attrs = _overnight_plan_attrs(_synthetic_plan(
        slots=64, demands=6, blocks_per_demand=10))
    assert not attrs.get("timeline_omitted"), (
        f"a normal 15-min night lost its chart ({_size(attrs)} bytes)")
    assert attrs["slots"] and attrs["blocks"]
    assert _size(attrs) <= _PLAN_ATTR_BUDGET_BYTES


def test_an_oversized_night_drops_the_chart_not_the_answer():
    """The backstop. Losing the strip is a visible, explained degradation;
    losing the attributes is a silent hole in the recorder."""
    plan = _synthetic_plan(slots=96, demands=12, blocks_per_demand=1)
    # Every block on its own island, so merging cannot save this one.
    for i, b in enumerate(plan["blocks"]):
        b["power_w"] = 100.0 + i
    plan["demands"] = plan["demands"] * 4
    attrs = _overnight_plan_attrs(plan)
    assert attrs["timeline_omitted"] is True
    assert attrs["slots"] == [] and attrs["blocks"] == []
    # The demands ARE the answer — they survive, and so does the verdict.
    assert attrs["demands"] and attrs["takeover"]
    assert _size(attrs) <= _PLAN_ATTR_BUDGET_BYTES


def test_projection_of_a_missing_plan_is_empty():
    assert _overnight_plan_attrs(None) == {}
    assert _overnight_plan_attrs("not-a-dict") == {}


# ---------------------------------------------------------------------------
# The card
# ---------------------------------------------------------------------------

def test_card_is_in_the_bundle_entry():
    entry = (REPO / "dashboard" / "card" / "src" / "sem-cards.js").read_text()
    assert "./cards/sem-energy-plan-card.js" in entry
    dist = (REPO / "dashboard" / "card" / "dist" / "sem-cards.js").read_text()
    assert "sem-energy-plan-card" in dist, (
        "dist/ is stale — run 'cd dashboard/card && npm run build'. The "
        "deploy scripts only rsync; they do NOT build.")


def test_card_is_placed_on_the_control_tab_above_loads():
    """(#638 G4 + consolidation 2026-08-08) The Energy Plan card IS the
    Control tab's timeline now — the old Today's Schedule card retired
    into it (night shading, now marker, Today|Tomorrow all render from
    the plan entity). Pin the ORDER above Load Management and pin the
    retirement: a schedule card creeping back is a second data path."""
    tpl = (REPO / "dashboard" / "sem_dashboard_template.yaml").read_text()
    assert tpl.count("custom:sem-energy-plan-card") == 1, (
        "the plan card must live in exactly one place")
    assert "custom:sem-schedule-card" not in tpl, (
        "the schedule card retired into the Energy Plan card — one "
        "timeline, one data source")
    card = tpl.index("custom:sem-energy-plan-card")
    loads = tpl.index("title: Load Management")
    assert card < loads


def test_card_localization_keys_exist_in_every_language():
    data = json.loads(
        (REPO / "dashboard" / "translations.json").read_text(encoding="utf-8"))
    missing = [(lang, key) for lang in data for key in CARD_KEYS
               if key not in data[lang]]
    assert not missing, f"untranslated card strings: {missing}"


def test_generated_localize_bundle_is_in_sync():
    """``sem-localize.js`` is GENERATED from translations.json. A key added to
    the source and not regenerated ships a card that renders raw key names."""
    js = (REPO / "dashboard" / "card" / "sem-localize.js").read_text(
        encoding="utf-8")
    for key in CARD_KEYS:
        assert f'"{key}"' in js, (
            f"{key} missing from sem-localize.js — run "
            f"scripts/regenerate_localize.py")


def test_card_asks_only_for_keys_that_exist():
    """The inverse guard: any ``_t('...')`` in the card source must be a key
    we actually ship. Catches a typo the CARD_KEYS list would otherwise
    happily bless."""
    import re
    src = CARD_SRC.read_text(encoding="utf-8")
    asked = set(re.findall(r"_t\(\s*'([a-z0-9_]+)'\s*\)", src))
    asked |= set(re.findall(r"_format\(\s*'([a-z0-9_]+)'", src))
    data = json.loads(
        (REPO / "dashboard" / "translations.json").read_text(encoding="utf-8"))
    unknown = sorted(k for k in asked if k not in data["en"])
    assert not unknown, f"card asks for keys that do not exist: {unknown}"
