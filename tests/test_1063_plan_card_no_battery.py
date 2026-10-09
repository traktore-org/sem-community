"""(#1063) The Energy Plan card drew a battery on a home without one.

@lostcontrol, 2.2.0-beta.11, Fronius, no battery (discussion #1057):

* Today: the sunny hours wore the "battery covers home" colour.
* Tomorrow: a "Battery" row filled from 0.0 to 7.4 kWh, legend "battery
  charging".

Two roots, one shape — a battery claimed without proof:

1. ``battery_capacity_kwh`` answered 15 kWh (the default) on an install
   whose battery module is ABSENT (#923). The tomorrow preview walked that
   pack and drew it. The settings step saves a capacity on every install,
   so the saved key does not prove a battery either.
2. The card read "no home draw on the meter" as "the battery covers the
   house". A sun slot has no net draw either (the ledger sets it to 0), so
   on every home the sunny hours were painted as battery. The plan now says
   per slot where the walk really drew the battery (``batt``; on the entity
   as index runs, ``batt_runs``) and the card paints the battery only there
   (``util/plan-cover.js``, its own test).

Swept on the same card: the morning review's battery row. With the battery
ABSENT every flow reads 0 and the SOC its 0.0 default, so the night
recorder sealed "trainable" nights and the review could say "drained 0.0
kWh overnight — the promised refill never came".
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.solar_energy_management.const import (
    DEFAULT_BATTERY_CAPACITY_KWH,
)
from custom_components.solar_energy_management.coordinator import coordinator as coord_mod
from custom_components.solar_energy_management.coordinator import ev_night_targets
from custom_components.solar_energy_management.coordinator.battery_night import (
    BatteryNightTracker, Sample,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.demand_review import (
    review_battery_night,
)
from custom_components.solar_energy_management.coordinator.install_modules import (
    Module, Presence,
)
from custom_components.solar_energy_management.sensor import _energy_plan_attrs

from .test_638_plan_surface import _synthetic_plan
from .test_638_shadow_mode import (  # noqa: F401 — fixtures come along
    _DayCapableTime, _fake_load, _fake_self, _idle_load, _power, _scheduler,
    freeze_targets,
)

REPO = Path(__file__).resolve().parent.parent
ABSENT = {Module.BATTERY: Presence.ABSENT}
PRESENT = {Module.BATTERY: Presence.PRESENT}


UNKNOWN = {Module.BATTERY: Presence.UNKNOWN}


def _coord_fake(presence, saved=None, detected=None, soc_read=None):
    """A minimal coordinator: the verdict, the saved size, what the
    reader could detect and the SOC it has read (None = never)."""
    def _detect():
        if presence == ABSENT:
            raise AssertionError("no battery: nothing to detect")
        return detected
    return SimpleNamespace(
        config={} if saved is None else {"battery_capacity_kwh": saved},
        setup_presence=presence,
        _detected_battery_capacity_kwh=None,
        _sensor_reader=SimpleNamespace(
            auto_detect_battery_capacity_kwh=_detect,
            _last_valid_soc=soc_read),
    )


def _capacity(presence, saved=None, detected=None, soc_read=None):
    """The REAL property over a minimal coordinator."""
    return SEMCoordinator.battery_capacity_kwh.fget(
        _coord_fake(presence, saved, detected, soc_read))


class TestNoBatteryHasNoCapacity:

    def test_absent_battery_is_zero_even_with_a_saved_size(self):
        # The settings step saved 15 kWh on the reporter's install.
        assert _capacity(ABSENT, saved=15.0) == 0.0
        assert _capacity(ABSENT) == 0.0

    def test_unknown_with_a_battery_read_keeps_the_old_answer(self):
        """A slow boot must never hide a real battery (#925): a SOC the
        reader has measured, or a pack it detected, is a battery."""
        assert _capacity(None, soc_read=55.0) == float(DEFAULT_BATTERY_CAPACITY_KWH)
        assert _capacity(None, saved=9.6, soc_read=55.0) == 9.6
        assert _capacity(UNKNOWN, detected=7.5) == 7.5

    def test_unknown_with_nothing_read_is_zero(self):
        """(#1063 round 2) The reporter's install was not ABSENT, so the
        first fix never reached it: UNKNOWN with no battery wired, none
        detected and no SOC ever read still answered 15 kWh, and the plan
        walked that pack. Nothing read, nothing detected — no battery."""
        assert _capacity(UNKNOWN, saved=15.0) == 0.0
        assert _capacity(UNKNOWN) == 0.0
        assert _capacity(None) == 0.0

    def test_present_battery_reads_as_before(self):
        assert _capacity(PRESENT, saved=10.0) == 10.0
        assert _capacity(PRESENT, detected=13.5) == 13.5
        assert _capacity(PRESENT) == float(DEFAULT_BATTERY_CAPACITY_KWH)


# ---------------------------------------------------------------------------
# Today: the plan says where the battery covered the house
# ---------------------------------------------------------------------------

def _stamp_at_14(monkeypatch, fake, *, soc, deficit=0.0):
    fixed = datetime(2026, 7, 29, 14, 0,
                     tzinfo=coord_mod.dt_util.DEFAULT_TIME_ZONE)
    monkeypatch.setattr(coord_mod.dt_util, "now", lambda *a, **k: fixed)
    SEMCoordinator._shadow_energy_plan(
        fake, _scheduler(deficit=deficit), energy=MagicMock(),
        power=_power(soc=soc))
    plan = fake._energy_plan_shadow
    assert isinstance(plan, dict) and plan["slots"], "no plan to judge"
    return plan


def _day_fake(capacity_kwh):
    fake = _fake_self(devices=[_fake_load()])
    fake.time_manager = _DayCapableTime()
    fake._forecast_reader = SimpleNamespace(forecast_data=SimpleNamespace(
        forecast_remaining_today_kwh=20.0))
    fake.battery_capacity_kwh = capacity_kwh
    return fake


def _sun_slots(plan):
    """Day slots with no net home draw: the sun runs the house."""
    return [s for s in plan["slots"]
            if s["home_w"] == 0 and s["start"][11:13] < "20"]


class TestTodayDrawsOnlyTheBatteryThePlanUsed:

    def test_no_battery_no_battery_slot(self, freeze_targets, monkeypatch):
        """The reporter's home: no slot says the battery covered the house,
        and the plan says it walked no battery."""
        plan = _stamp_at_14(monkeypatch, _day_fake(_capacity(ABSENT, 15.0)),
                            soc=0.0)
        assert plan["has_battery"] is False
        assert not any(s.get("batt") for s in plan["slots"])
        # The sunny hours are there — and nothing on the meter, so the card
        # draws them as sun (util/plan-cover.js), never as battery.
        sun = _sun_slots(plan)
        assert sun, "the 14:00 stamp must span sunny hours"
        assert all(s["home_grid_w"] == 0 for s in sun)
        # The night is on the grid.
        assert any(s["home_grid_w"] > 1 for s in plan["slots"])

    def test_a_battery_covers_the_evening_not_the_sun(
            self, freeze_targets, monkeypatch):
        """With a battery the evening wears it; the sunny hours still do
        not — before #1063 they read "battery covers home" on every
        install."""
        plan = _stamp_at_14(monkeypatch, _day_fake(10.0), soc=80.0)
        assert plan["has_battery"] is True
        batt = [s for s in plan["slots"] if s.get("batt")]
        assert batt, "an 8 kWh pack over a 400 W evening covers hours"
        # Marked only where the house drew something; the hand-over slot
        # is part battery, part grid, and the card draws it as grid.
        assert all(s["home_w"] > 0 for s in batt)
        # Every hour the house draws and the meter does not: the battery.
        covered = [s for s in plan["slots"]
                   if s["home_w"] > 0 and s["home_grid_w"] <= 1]
        assert covered and all(s.get("batt") for s in covered)
        sun = _sun_slots(plan)
        assert sun and not any(s.get("batt") for s in sun)

    def test_the_quiet_night_says_it_too(self, freeze_targets, monkeypatch):
        """One shape for both answers: a night with nothing to schedule
        carries the same flag."""
        monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                            lambda coord, energy: {})
        fake = _day_fake(_capacity(ABSENT, 15.0))
        fake._surplus_controller = SimpleNamespace(
            get_devices_sorted=lambda: [_idle_load()])
        plan = _stamp_at_14(monkeypatch, fake, soc=0.0)
        assert plan["demands"] == []
        assert plan["has_battery"] is False
        assert not any(s.get("batt") for s in plan["slots"])


def _slot(batt=False):
    s = {"start": "a", "end": "b", "price": 0.2, "cheap": False,
         "home_w": 400.0, "soc_kwh": 5.0, "home_grid_w": 0.0}
    if batt:
        s["batt"] = True
    return s


class TestTheEntityCarriesIt:

    def test_the_marks_ride_as_index_runs(self):
        attrs = _energy_plan_attrs({
            "demands": [{"id": "load:pump"}], "has_battery": True,
            "slots": [_slot(True), _slot(), _slot(True), _slot(True),
                      _slot()]})
        assert attrs["has_battery"] is True
        assert attrs["batt_runs"] == [[0, 0], [2, 3]]
        # The slots themselves carry no flag: runs are the whole answer.
        assert not any("batt" in s for s in attrs["slots"])

    def test_no_battery_no_runs(self):
        attrs = _energy_plan_attrs({
            "demands": [{"id": "load:pump"}], "has_battery": False,
            "slots": [_slot(), _slot()]})
        assert attrs["has_battery"] is False and attrs["batt_runs"] == []

    def test_a_plan_from_before_the_fix_says_nothing(self):
        """A stash restored after the update has no ``has_battery`` and no
        marks. ``None`` (not ``[]``) lets the card keep its old drawing
        instead of painting a battery home's night as sun."""
        attrs = _energy_plan_attrs({
            "demands": [{"id": "load:pump"}], "slots": [_slot(), _slot()]})
        assert attrs["batt_runs"] is None and attrs["has_battery"] is None

    def test_the_runs_cost_the_budget_almost_nothing(self):
        """A flag per slot cost 14 bytes each and pushed a 15-minute day
        over the recorder budget (review of #1063). Runs cost a few."""
        def size(mark):
            plan = _synthetic_plan(slots=96, demands=5, blocks_per_demand=10)
            plan["has_battery"] = True
            for i, s in enumerate(plan["slots"]):
                if mark and i >= 40:
                    s["batt"] = True
            attrs = _energy_plan_attrs(plan)
            assert not attrs.get("timeline_omitted")
            return len(json.dumps(attrs, default=str))
        assert size(True) - size(False) <= 12


# ---------------------------------------------------------------------------
# Tomorrow: no battery row
# ---------------------------------------------------------------------------

def _preview(capacity_kwh, soc=0.0, saved=None):
    fake = _fake_self(devices=[_fake_load()])
    if saved is not None:
        fake.config["battery_capacity_kwh"] = saved
    fake.time_manager = _DayCapableTime()
    # The reporter's tomorrow: 15.4 kWh of sun.
    fake._forecast_reader = SimpleNamespace(
        forecast_data=SimpleNamespace(forecast_tomorrow_kwh=15.4))
    fake.battery_capacity_kwh = capacity_kwh
    p = SEMCoordinator._compose_tomorrow_preview(fake, power=_power(soc=soc))
    assert p is not None and p.get("provisional") is not None, (
        "the provisional plan is what draws the battery row")
    return p["provisional"]


class TestTomorrowHasNoBatteryRow:

    def test_the_old_default_drew_a_battery(self, freeze_targets):
        """The mechanism: 15 kWh (what the property used to answer) and a
        sunny day give a rising curve — the reporter's 0.0 → 7.4 kWh row."""
        curve = _preview(float(DEFAULT_BATTERY_CAPACITY_KWH))["soc_curve"]
        assert len(curve) > 1 and curve[-1]["kwh"] > curve[0]["kwh"]

    def test_no_battery_no_curve(self, freeze_targets):
        prov = _preview(_capacity(ABSENT, 15.0))
        assert prov["soc_curve"] == []
        # The asks are still placed: only the battery row goes.
        assert prov["blocks"]

    def test_a_real_battery_keeps_its_row(self, freeze_targets):
        assert len(_preview(10.0, soc=50.0)["soc_curve"]) > 1


class TestThePlanReadsOneCapacity:
    """The saved key never said "no battery" (the settings step saves one
    everywhere). Both planner surfaces ask the property — with a saved
    15 kWh and no battery, neither walks one."""

    def test_today(self, freeze_targets, monkeypatch):
        fake = _day_fake(_capacity(ABSENT, 15.0))
        fake.config["battery_capacity_kwh"] = 15.0
        plan = _stamp_at_14(monkeypatch, fake, soc=0.0)
        assert plan["has_battery"] is False

    def test_tomorrow(self, freeze_targets):
        prov = _preview(_capacity(ABSENT, 15.0), saved=15.0)
        assert prov["soc_curve"] == []


# ---------------------------------------------------------------------------
# Round 2 (08.10.2026): an UNKNOWN battery is not a battery
# ---------------------------------------------------------------------------

class TestABatteryIsSeenOrItIsNotThere:
    """``battery_unseen``: the one question every battery surface asks."""

    def test_present_is_seen_absent_is_not(self):
        assert coord_mod.battery_unseen(_coord_fake(PRESENT)) is False
        assert coord_mod.battery_unseen(_coord_fake(ABSENT)) is True

    def test_unknown_is_seen_only_by_a_reading_or_a_detection(self):
        assert coord_mod.battery_unseen(_coord_fake(UNKNOWN, soc_read=12.0)) is False
        assert coord_mod.battery_unseen(_coord_fake(UNKNOWN, detected=5.0)) is False
        assert coord_mod.battery_unseen(_coord_fake(UNKNOWN)) is True
        assert coord_mod.battery_unseen(_coord_fake(None, saved=15.0)) is True

    def test_a_bare_double_is_unseen(self):
        """No reader at all (a test double) reads nothing."""
        assert coord_mod.battery_unseen(SimpleNamespace(config={})) is True


class TestAnUnseenBatteryIsNotWalked:

    def test_today_walks_no_pack_and_says_why(self, freeze_targets, monkeypatch):
        """The reporter's day on 08.10: hot water planned, no battery wired,
        the module UNKNOWN. The plan says it walked no battery, marks no
        slot and says why on the card."""
        monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                            lambda coord, energy: {})
        fake = _day_fake(_capacity(UNKNOWN, 15.0))
        fake.setup_presence = UNKNOWN
        fake._surplus_controller = SimpleNamespace(
            get_devices_sorted=lambda: [_idle_load()])
        plan = _stamp_at_14(monkeypatch, fake, soc=0.0)
        assert plan["has_battery"] is False
        assert not any(s.get("batt") for s in plan["slots"])
        assert "battery_unseen" in plan["why_codes"]

    def test_an_absent_battery_needs_no_explanation(self, freeze_targets, monkeypatch):
        """ABSENT is a plain answer: the card shows no battery and that is
        the whole story."""
        monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                            lambda coord, energy: {})
        fake = _day_fake(_capacity(ABSENT, 15.0))
        fake.setup_presence = ABSENT
        fake._surplus_controller = SimpleNamespace(
            get_devices_sorted=lambda: [_idle_load()])
        plan = _stamp_at_14(monkeypatch, fake, soc=0.0)
        assert plan["has_battery"] is False
        assert "battery_unseen" not in plan["why_codes"]

    def test_a_full_plan_on_an_unseen_battery_walks_none(
            self, freeze_targets, monkeypatch):
        fake = _day_fake(_capacity(UNKNOWN, 15.0))
        fake.setup_presence = UNKNOWN
        plan = _stamp_at_14(monkeypatch, fake, soc=0.0)
        assert plan["demands"], "a full plan, not the quiet answer"
        assert plan["has_battery"] is False
        assert not any(s.get("batt") for s in plan["slots"])

    def test_tomorrow_has_no_curve(self, freeze_targets):
        assert _preview(_capacity(UNKNOWN, 15.0), saved=15.0)["soc_curve"] == []

    def test_a_read_battery_on_an_unknown_install_keeps_its_curve(
            self, freeze_targets):
        """Not vacuous: UNKNOWN with a SOC read walks the pack as before."""
        assert len(_preview(_capacity(UNKNOWN, 10.0, soc_read=50.0),
                            soc=50.0)["soc_curve"]) > 1


class TestWhenPlansRunIsUnchanged:
    """This fix changes what the card SHOWS, not when a plan runs. The
    ready check still reads the saved key: asking the module verdict there
    would start plans (and plan actuation) on battery-less homes that saved
    a size — a control change, left open on purpose (review of #1063)."""

    @staticmethod
    def _tick_tries_a_stamp(presence, saved):
        tried = []
        fake = MagicMock()
        fake.config = {} if saved is None else {"battery_capacity_kwh": saved}
        fake.setup_presence = presence
        fake._detected_battery_capacity_kwh = None
        fake._sensor_reader = SimpleNamespace(
            auto_detect_battery_capacity_kwh=lambda: None)
        fake._runtimes_restored = True
        fake._shadow_plan_date = None
        fake._plan_ev_conn_sig = None
        fake._manual_replan_requested = False
        fake._surplus_controller = None
        fake.time_manager.get_night_end_time.return_value = "07:00"
        fake._energy_plan_demand_signature.return_value = ("sig",)
        type(fake).battery_capacity_kwh = property(
            lambda s: SEMCoordinator.battery_capacity_kwh.fget(s))

        def _shadow(*a, **k):
            tried.append(1)
            return False
        fake._shadow_energy_plan.side_effect = _shadow
        # A home with no battery: the SOC reads unavailable every cycle.
        power = SimpleNamespace(battery_soc=0.0, battery_soc_unavailable=True)
        SEMCoordinator._energy_plan_tick(fake, power, MagicMock())
        return bool(tried)

    def test_a_saved_size_still_waits_for_a_soc(self):
        assert self._tick_tries_a_stamp(ABSENT, 15.0) is False
        assert self._tick_tries_a_stamp(None, 15.0) is False

    def test_no_saved_size_stamps_as_before(self):
        assert self._tick_tries_a_stamp(ABSENT, None) is True
        assert self._tick_tries_a_stamp(PRESENT, None) is True


class TestNoSizeNoRedirect:

    def test_a_zero_size_keeps_the_charge(self):
        """0 kWh is the ABSENT answer. A battery added since reads as
        charging until the reload takes it in; a need of 0 must not read as
        "full" and hand its whole charge to the car (review of #1063)."""
        from custom_components.solar_energy_management.coordinator.flow_calculator import (
            battery_redirect_w,
        )
        assert battery_redirect_w(2700.0, 90.0, 0.0, 30.0) == 0
        assert battery_redirect_w(2700.0, 90.0, 0.0, 0.0) == 0
        # Not vacuous: a known size still redirects.
        assert battery_redirect_w(2700.0, 90.0, 15.0, 30.0) > 0


# ---------------------------------------------------------------------------
# Swept: last night's battery row
# ---------------------------------------------------------------------------

def _empty_sample(soc=0.0):
    """What a home with no battery feeds the recorder: zeros and the
    reader's 0.0 SOC default."""
    return Sample(
        battery_to_home_w=0.0, battery_to_ev_w=0.0, battery_to_grid_w=0.0,
        battery_discharge_w=None, battery_charge_w=0.0, grid_to_home_w=400.0,
        home_w=400.0, soc=soc, soc_available=True, export_w=0.0,
        measured=True)


class TestNoBatteryNoBatteryNight:

    def test_without_the_gate_a_phantom_row_appears(self):
        """Why the recorder must not run: a battery-less night with a
        forecast seals as trainable and earns a row."""
        tr = BatteryNightTracker(reserve_soc=20.0, capacity_kwh=15.0)
        t = 1_000_000.0
        tr.start("2026-10-05", outdoor_temp_c=None)
        for i in range(60):
            tr.tick(t + i * 600, True, _empty_sample())
        for i in range(60, 70):
            tr.tick(t + i * 600, False, _empty_sample())
        tr.set_forecast_kwh(15.4)
        rec = tr.current_record()
        assert rec is not None
        row = review_battery_night(rec)
        assert row is not None and row["drained"] == 0.0, row

    def _recorder_fake(self, presence):
        return SimpleNamespace(
            config={}, setup_presence=presence, _storage=None,
            time_manager=SimpleNamespace(
                is_night_mode=lambda: True,
                get_night_window=lambda: ("21:00", "07:00")),
            _outdoor_temp_c=lambda: None,
        )

    async def test_absent_battery_records_nothing(self):
        fake = self._recorder_fake(ABSENT)
        await SEMCoordinator._record_battery_night(
            fake, SimpleNamespace(battery_soc=0.0, battery_power=None),
            SimpleNamespace())
        assert getattr(fake, "_battery_night", None) is None

    async def test_an_unseen_battery_records_nothing(self):
        """(round 2) UNKNOWN with nothing read is the reporter's home."""
        fake = self._recorder_fake(UNKNOWN)
        await SEMCoordinator._record_battery_night(
            fake, SimpleNamespace(battery_soc=0.0, battery_power=None),
            SimpleNamespace())
        assert getattr(fake, "_battery_night", None) is None

    async def test_an_unknown_battery_being_read_still_records(self):
        fake = self._recorder_fake(UNKNOWN)
        fake._sensor_reader = SimpleNamespace(_last_valid_soc=60.0)
        await SEMCoordinator._record_battery_night(
            fake, SimpleNamespace(battery_soc=60.0, battery_power=-500.0),
            SimpleNamespace(battery_to_home=500.0))
        assert getattr(fake, "_battery_night", None) is not None

    async def test_a_battery_still_records(self):
        """Not vacuous: the same call with a battery opens a night."""
        fake = self._recorder_fake(PRESENT)
        await SEMCoordinator._record_battery_night(
            fake, SimpleNamespace(battery_soc=60.0, battery_power=-500.0),
            SimpleNamespace(battery_to_home=500.0))
        assert getattr(fake, "_battery_night", None) is not None


# ---------------------------------------------------------------------------
# The new legend word
# ---------------------------------------------------------------------------

LEGEND_SUN = "energy_plan_legend_sun"
WHY_BATTERY_UNSEEN = "energy_plan_whyc_battery_unseen"


def test_sun_legend_in_every_language():
    data = json.loads((REPO / "dashboard" / "translations.json")
                      .read_text(encoding="utf-8"))
    assert len(data) == 16
    for lang, table in data.items():
        assert table.get(LEGEND_SUN), lang
        # (round 2) the quiet face's "no battery found" sentence
        assert table.get(WHY_BATTERY_UNSEEN), lang
    for lang in data:
        name = ("sem-localize.js" if lang == "en"
                else f"sem-localize.{lang}.js")
        js = (REPO / "dashboard" / "card" / name).read_text(encoding="utf-8")
        assert f'"{LEGEND_SUN}"' in js, name
        assert f'"{WHY_BATTERY_UNSEEN}"' in js, name


def test_the_bundle_carries_the_fix():
    """The card ships as the built bundle; a source fix without a rebuild
    changes nothing on a dashboard."""
    dist = (REPO / "dashboard" / "card" / "dist" / "sem-cards.js").read_text(
        encoding="utf-8")
    assert "energy_plan_legend_sun" in dist
    assert "mdi:home-battery" in dist and "has_battery" in dist
    assert "batt_runs" in dist
