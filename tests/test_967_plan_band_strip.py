"""#967 — Solar + cheapest hours booked the charge into the peak band.

@alexmc1510 (#966, same install as #939): Victron EVCS, 60 kWh Tesla,
``solar_plus_cheap``, At least 60 % / Up to 80 %, Charge by 06:00, car at
~29 %. Spanish 2.0TD — a FIXED three-period schedule (valle 0.07 from 00:00,
llano 0.11, punta 0.20 at 18–22) served as a dynamic price series, so every
hour through tomorrow is priced. ``target_peak_limit`` 3.5 kW. His 14:06
screenshot: the EV card's strip paints "charging" from **20:36** (the night
window open, sunset + 10) to **~21:40** — inside the punta band the same
strip paints pink — and the bar is far too short for the 19.8 kWh he needs.

This file is the diagnostics his download could not give (the plan shadow
is not exported — that is defect D4, fixed in the same branch). It builds
his night from his numbers and walks it through the SAME pure functions the
coordinator uses, in the same order, so the picture on his screen is
reproduced here rather than reasoned about:

  ledger → pack_night → the stamped dict → plan_gate → ev_overlay
         → plan_night_charge → compose_today_plan → the card's segment rule

Three defects it pins (the fourth is diagnostics):

* **D1** — with no per-charger night plan during the day, the composer's
  fallback re-derived the EV need from ``daily_ev_target`` (his: 4.5 kWh, a
  per-DAY knob) at a hard-coded 4.1 kW. 4.5 / 4.1 = 66 min: 20:36 + 1:06 =
  **21:42**. That is his bar. The one producer of the need is
  ``build_night_target_map`` → ``_calculate_remaining_need`` = 19.8 kWh.
* **D2** — the EV card paints ``night_open`` as *charging* unless a start row
  carries ``plan_ev_charge_tariff``; a joint-plan start never counts, and
  nothing emits ``ev_wait``. Even a plan that books the valle hours paints
  charging from the window open.
* **D3** — anything but ``fits`` leaves the gate UNCOVERED, and the reactive
  night layer it falls back to has had no tariff awareness since #638 C3: it
  starts at ``night_start``. Under 2.0TD that is the most expensive hour of
  the night, with nine hours of cheaper ones still ahead of a 06:00 deadline.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
    ev_overlay, plan_blocks, plan_gate,
)
from custom_components.solar_energy_management.coordinator.energy_planner import (
    Demand, LedgerSlot, build_night_ledger, pack_night,
)
from custom_components.solar_energy_management.coordinator.ev_control import (
    amps_from_headroom,
)
from custom_components.solar_energy_management.coordinator.ev_tariff_planner import (
    affordable_start, plan_night_charge,
)
from custom_components.solar_energy_management.coordinator.today_plan import (
    KIND_EV_CHARGE_START, KIND_EV_MIN_REACHED, KIND_NIGHT_OPEN, compose_today_plan,
)

TZ = ZoneInfo("Europe/Madrid")
DAY = datetime(2026, 9, 16, tzinfo=TZ)

# ── his install, from the diagnostics download and the restamp log line ──
SCREENSHOT_AT = DAY.replace(hour=14, minute=6)
NIGHT_OPEN = DAY.replace(hour=20, minute=36)          # sunset + 10 min
NIGHT_END = (DAY + timedelta(days=1)).replace(hour=7, minute=0)
DEADLINE = (DAY + timedelta(days=1)).replace(hour=6, minute=0)
NEED_KWH = 19.8            # ev_targets={'ev_charger': 19.8}: 60 kWh × (60 − 27) %
DAILY_EV_TARGET = 4.5      # the per-DAY knob the fallback read instead
PEAK_LIMIT_W = 3500.0
PLANNING_PEAK_W = PEAK_LIMIT_W - 200.0     # DEFAULT_PEAK_HYSTERESIS 0.2 kW
HOME_W = 800.0             # 19.3 kWh/day
WPA = 3 * 230.0            # no measured table → nameplate 690 W/A
MIN_A, MAX_A = 6, 32       # ev_min_current 6, ev_max_current unset → default 32
BATTERY_KWH, BATTERY_SOC_KWH = 16.0, 15.8

#: the 2.0TD schedule, hour → €/kWh (from the log's restamp signature)
_PERIOD = {**{h: 0.07 for h in range(0, 8)},
           **{h: 0.11 for h in (8, 9, 14, 15, 16, 17, 22, 23)},
           **{h: 0.20 for h in (10, 11, 12, 13, 18, 19, 20, 21)}}
_LEVEL = {0.07: "cheap", 0.11: "normal", 0.20: "expensive"}   # tou_tiers, 3 tiers


def price_at(t: datetime) -> float:
    return _PERIOD[t.hour]


def level_at(t: datetime) -> str:
    return _LEVEL[price_at(t)]


def his_night_ledger():
    """Hourly slots from the first full hour after the window open to the
    night end, exactly as ``_shadow_energy_plan`` builds them."""
    slots = []
    t = NIGHT_OPEN.replace(minute=0) + timedelta(hours=1)          # 21:00
    while t < NIGHT_END:
        end = min(t + timedelta(hours=1), NIGHT_END)
        slots.append(LedgerSlot(start=t, end=end, price=price_at(t),
                                level_cheap=(level_at(t) == "cheap"), home_w=HOME_W))
        t = end
    return build_night_ledger(slots, soc_kwh=BATTERY_SOC_KWH,
                              floor_kwh=BATTERY_KWH * 0.20, max_discharge_w=5000.0,
                              peak_limit_w=PLANNING_PEAK_W)


def his_ev_demand():
    return Demand(id="ev:ev_charger", kind="ev", energy_kwh=NEED_KWH,
                  max_power_w=MAX_A * WPA, min_power_w=MIN_A * WPA,
                  deadline=DEADLINE, priority=1, source="grid",
                  min_run_s=900, min_gap_s=900)


def stamped(plan, ledger, computed_at):
    """The dict ``_shadow_energy_plan`` stores — the shape ``plan_gate`` reads."""
    return {
        "computed_at": computed_at.isoformat(),
        "fits": plan.fits,
        "demands": [{"id": r.demand_id, "status": r.status,
                     "planned_kwh": round(r.planned_kwh, 2),
                     "needed_kwh": round(r.needed_kwh, 2), "note": r.note or None}
                    for r in plan.results],
        "slots": [{"start": s.start.isoformat(), "end": s.end.isoformat()} for s in ledger],
        "blocks": plan_blocks(plan.allocations),
    }


def peak_managed_amps():
    return amps_from_headroom(PLANNING_PEAK_W - HOME_W, WPA, MIN_A, MAX_A)


def card_segments(rows, now, end):
    """A Python mirror of ``sem-ev-status-card._renderPlanStrip`` as shipped:
    the five kinds it reads and its ``night_open → charging`` rule."""
    ev = [r for r in rows if r["kind"] in
          ("now", "night_open", "ev_charge_start", "ev_min_reached", "ev_deadline")]
    tariff_wait = any(r["kind"] == "ev_charge_start"
                      and r.get("detail") == "plan_ev_charge_tariff" for r in rows)
    segs, cursor, state = [], now, "idle"
    for r in sorted(ev, key=lambda r: r["when"]):
        t = datetime.fromisoformat(r["when"])
        if t > cursor:
            segs.append((cursor, t, state)); cursor = t
        if r["kind"] == "night_open":
            state = "wait" if tariff_wait else "charging"
        elif r["kind"] == "ev_charge_start":
            state = "charging"
        elif r["kind"] in ("ev_min_reached", "ev_deadline"):
            state = "done"
    if cursor < end:
        segs.append((cursor, end, state))
    return segs


def charging_segments(segs):
    return [(s, e) for s, e, st in segs if st == "charging"]


def card_segments_fixed(rows, now, end):
    """The mirror of ``evStripSegments`` AS FIXED (dashboard/card/src/util/
    ev-strip.js): the open is a charge only when a start sits AT it, and a
    preview start paints ``estimate`` rather than a booked bar."""
    ev = [r for r in rows if r["kind"] in
          ("now", "night_open", "ev_charge_start", "ev_min_reached", "ev_deadline")]
    ev.sort(key=lambda r: r["when"])
    starts = [r for r in ev if r["kind"] == "ev_charge_start"]
    def _state(r):
        return "estimate" if r.get("detail") == "plan_ev_charge_estimate" else "charging"
    segs, cursor, state = [], now, "idle"
    for r in ev:
        t = min(datetime.fromisoformat(r["when"]), end)
        if t > cursor:
            segs.append((cursor, t, state))
        cursor = max(cursor, t)
        if r["kind"] == "night_open":
            at_open = next((s for s in starts if abs(
                (datetime.fromisoformat(s["when"]) - datetime.fromisoformat(r["when"])
                 ).total_seconds()) <= 60), None)
            state = _state(at_open) if at_open else "wait"
        elif r["kind"] == "ev_charge_start":
            state = _state(r)
        elif r["kind"] in ("ev_min_reached", "ev_deadline"):
            state = "done"
    if cursor < end:
        segs.append((cursor, end, state))
    return segs


# ═══════════════════════════════════════════════════════════════════════
# What SEM actually computes for his night — the missing diagnostics
# ═══════════════════════════════════════════════════════════════════════

class TestWhatThePlannerSaysForHisNight:
    def test_his_charger_cannot_be_booked_at_all_under_his_peak_limit(self):
        """The finding the download could not show. The packer books a slot
        only if the headroom covers the charger's MINIMUM (6 A × 690 W/A =
        4.14 kW); his planning peak is 3.3 kW. So no slot is ever eligible,
        the EV yields, and the gate is UNCOVERED every night — not `partial`,
        not a price gap: the joint plan simply never speaks for this car."""
        ledger = his_night_ledger()
        plan = pack_night([his_ev_demand()], ledger, floor_kwh=BATTERY_KWH * 0.2,
                          max_discharge_w=5000.0, peak_limit_w=PLANNING_PEAK_W)
        row = next(r for r in plan.results if r.demand_id == "ev:ev_charger")
        assert row.status == "yields", (row.status, row.note)
        assert plan.allocations == ()
        assert max(s.headroom_w for s in ledger) < MIN_A * WPA

    def test_so_the_gate_never_covers_him_and_the_overlay_steps_aside(self):
        ledger = his_night_ledger()
        plan = pack_night([his_ev_demand()], ledger, floor_kwh=BATTERY_KWH * 0.2,
                          max_discharge_w=5000.0, peak_limit_w=PLANNING_PEAK_W)
        shadow = stamped(plan, ledger, computed_at=SCREENSHOT_AT)
        for when in (SCREENSHOT_AT, NIGHT_OPEN):
            gate = plan_gate(shadow, "ev:ev_charger", when)
            assert not gate.covered and gate.reason == "verdict yields"
            assert ev_overlay(gate, remaining_kwh=NEED_KWH, reachable=True,
                              deadline_active=False, watts_per_amp=WPA,
                              min_amps=MIN_A, max_amps=MAX_A) == (False, 0)

    def test_the_reactive_planner_is_not_forcing_and_the_floor_is_reachable(self):
        """So nothing senior to the tariff is asking for the peak band: the
        06:00 deadline needs ~2 A over 9.4 h, far below the 6 A minimum."""
        plan = plan_night_charge(
            now=NIGHT_OPEN, remaining_to_min_kwh=NEED_KWH, min_amps=MIN_A, max_amps=MAX_A,
            watts_per_amp=WPA, target_time="06:00", night_end="07:00",
            tariff_optimized=True, peak_managed_amps=peak_managed_amps())
        assert plan.deadline_active is False
        assert plan.reachable is True
        assert plan.should_wait_for_cheap is False, (
            "the reactive layer has no tariff opinion at all — that is D3")
        assert peak_managed_amps() == MIN_A          # 3300 − 800 = 2500 W → clamped to 6 A


# ═══════════════════════════════════════════════════════════════════════
# The picture on his screen, reproduced
# ═══════════════════════════════════════════════════════════════════════

class TestThePictureOnHisScreen:
    """14:06, car plugged in at ~29 %: no per-charger night plan exists by day,
    so the composer's fallback branch ran with ``daily_ev_target`` and 4.1 kW."""

    def _rows_as_shipped(self):
        return compose_today_plan(
            now=SCREENSHOT_AT, horizon_hours=24,
            night_start=NIGHT_OPEN, night_end=NIGHT_END,
            ev_min_remaining_kwh=DAILY_EV_TARGET,     # D1: the per-day knob, not 19.8
            ev_deadline=DEADLINE, ev_tariff_optimized=True,
            ev_tariff_waiting=False, ev_next_cheap_window=None,
            ev_plan_blocks=None,                       # gate uncovered → no blocks
            ev_effective_rate_kw=4.1,                  # D1: the literal
        )

    def test_the_bar_starts_at_the_window_open_inside_punta(self):
        rows = self._rows_as_shipped()
        start = next(r for r in rows if r["kind"] == KIND_EV_CHARGE_START)
        assert datetime.fromisoformat(start["when"]) == NIGHT_OPEN
        assert level_at(NIGHT_OPEN) == "expensive"
        assert start["detail"] == "plan_ev_charge_night"

    def test_the_bar_ends_at_21_41_because_it_was_sized_from_the_daily_knob(self):
        """4.5 kWh / 4.1 kW = 65.85 min → 21:41:51; ``PlanRow.to_dict`` strips
        seconds → **21:41**. He wrote "~21:40". The arithmetic is the bar."""
        rows = self._rows_as_shipped()
        done = next(r for r in rows if r["kind"] == KIND_EV_MIN_REACHED)
        assert datetime.fromisoformat(done["when"]) == DAY.replace(hour=21, minute=41)
        assert done["values"]["kwh"] == "4.5"          # not the 19.8 he needs

    def test_the_card_paints_charging_from_20_36(self):
        rows = self._rows_as_shipped()
        segs = card_segments(rows, SCREENSHOT_AT, SCREENSHOT_AT + timedelta(hours=12))
        charging = charging_segments(segs)
        assert charging and charging[0][0] == NIGHT_OPEN
        assert charging[0][1] == DAY.replace(hour=21, minute=41)

    def test_even_a_plan_that_books_the_valle_hours_would_paint_charging_from_the_open(self):
        """D2 on its own: give the card exactly what a covering plan emits —
        joint starts at 00:00 and min-reached at 05:00 — and it still turns
        the window open into 'charging' four hours before the first block."""
        blocks = [{"start": (DAY + timedelta(days=1)).replace(hour=h).isoformat(),
                   "end": (DAY + timedelta(days=1)).replace(hour=h + 1).isoformat(),
                   "power_w": 4140.0} for h in range(0, 5)]
        rows = compose_today_plan(
            now=SCREENSHOT_AT, horizon_hours=24, night_start=NIGHT_OPEN,
            night_end=NIGHT_END, ev_min_remaining_kwh=NEED_KWH, ev_deadline=DEADLINE,
            ev_tariff_optimized=True, ev_plan_blocks=blocks, ev_effective_rate_kw=4.14)
        assert any(r["detail"] == "plan_ev_charge_joint" for r in rows)
        segs = card_segments(rows, SCREENSHOT_AT, SCREENSHOT_AT + timedelta(hours=16))
        first = charging_segments(segs)[0]
        assert first[0] == NIGHT_OPEN, "the card ignores the joint start and paints from the open"


# ═══════════════════════════════════════════════════════════════════════
# What it must look like after the fix — red until Tasks 2–4 land
# ═══════════════════════════════════════════════════════════════════════

class TestAfterTheFix:
    def test_d1_the_preview_carries_his_real_need_at_the_rate_he_will_get(self):
        """The composer's EV preview must come from the one producer of the
        night need and the peak-managed rate — never a daily knob and a literal."""
        from custom_components.solar_energy_management.coordinator.today_plan import (
            ev_preview_inputs,
        )
        kwh, rate_kw, detail = ev_preview_inputs(
            night_need_kwh=NEED_KWH, peak_managed_amps=peak_managed_amps(),
            watts_per_amp=WPA, gate_covered=False)
        assert kwh == pytest.approx(NEED_KWH)
        assert rate_kw == pytest.approx(MIN_A * WPA / 1000.0)      # 4.14, not 4.1
        assert detail == "plan_ev_charge_estimate"

    def test_d3_the_fallback_waits_through_punta_when_the_cheap_hours_still_deliver(self):
        rate_kw = MIN_A * WPA / 1000.0
        start = affordable_start(NIGHT_OPEN, DEADLINE, NEED_KWH, rate_kw, level_at)
        # the packer's own order — cheapest level first, earliest first: the
        # first valle hour, with 1.2 h of slack before 06:00, not a
        # just-in-time 01:13 and not the 22:00 llano hour
        assert start == (DAY + timedelta(days=1)).replace(hour=0, minute=0)
        assert level_at(start) == "cheap"
        assert start + timedelta(hours=NEED_KWH / rate_kw) <= DEADLINE

    def test_d3_the_hold_boundary_when_the_cheapest_band_alone_is_too_short(self):
        """A need the valle hours cannot hold on their own takes the llano
        hour before them too — the LATEST start that still lands it, so it
        never waits itself into a missed floor."""
        rate_kw = MIN_A * WPA / 1000.0
        need = rate_kw * 6.5                                    # 6 h valle + 30 min llano
        start = affordable_start(NIGHT_OPEN, DEADLINE, need, rate_kw, level_at)
        assert start == DAY.replace(hour=23, minute=30)
        assert level_at(start) == "normal"

    def test_d3_only_expensive_hours_left_means_charge_now(self):
        rate_kw = MIN_A * WPA / 1000.0
        late = DAY.replace(hour=19, minute=0)                  # punta until 22:00
        assert affordable_start(late, DAY.replace(hour=21, minute=30),
                                5.0, rate_kw, level_at) is None

    def test_d3_the_night_plan_says_wait_at_20_36_for_a_cheap_hours_mode(self):
        plan = plan_night_charge(
            now=NIGHT_OPEN, remaining_to_min_kwh=NEED_KWH, min_amps=MIN_A, max_amps=MAX_A,
            watts_per_amp=WPA, target_time="06:00", night_end="07:00",
            tariff_optimized=True, peak_managed_amps=peak_managed_amps(),
            level_at=level_at)
        assert plan.should_wait_for_cheap is True
        assert plan.next_cheap_start is not None
        assert level_at(plan.next_cheap_start) != "expensive"

    def test_d3_but_never_when_the_deadline_is_forcing_or_the_floor_unreachable(self):
        late = DEADLINE - timedelta(hours=2)          # 04:00, 19.8 kWh left: forcing
        plan = plan_night_charge(
            now=late, remaining_to_min_kwh=NEED_KWH, min_amps=MIN_A, max_amps=MAX_A,
            watts_per_amp=WPA, target_time="06:00", night_end="07:00",
            tariff_optimized=True, peak_managed_amps=peak_managed_amps(),
            level_at=level_at)
        assert plan.should_wait_for_cheap is False

    def test_d3_a_mode_without_tariff_awareness_is_untouched(self):
        plan = plan_night_charge(
            now=NIGHT_OPEN, remaining_to_min_kwh=NEED_KWH, min_amps=MIN_A, max_amps=MAX_A,
            watts_per_amp=WPA, target_time="06:00", night_end="07:00",
            tariff_optimized=False, peak_managed_amps=peak_managed_amps(),
            level_at=level_at)
        assert plan.should_wait_for_cheap is False

    def test_the_strip_then_shows_the_wait_and_the_real_need(self):
        rate_kw = MIN_A * WPA / 1000.0
        start = affordable_start(SCREENSHOT_AT, DEADLINE, NEED_KWH, rate_kw, level_at)
        rows = compose_today_plan(
            now=SCREENSHOT_AT, horizon_hours=24, night_start=NIGHT_OPEN, night_end=NIGHT_END,
            ev_min_remaining_kwh=NEED_KWH, ev_deadline=DEADLINE, ev_tariff_optimized=True,
            ev_tariff_waiting=True, ev_next_cheap_window=start,
            ev_plan_blocks=None, ev_effective_rate_kw=rate_kw)
        first = next(r for r in rows if r["kind"] == KIND_EV_CHARGE_START)
        assert datetime.fromisoformat(first["when"]) == start
        assert first["detail"] == "plan_ev_charge_tariff"
        assert any(r["kind"] == KIND_NIGHT_OPEN for r in rows)
        segs = card_segments(rows, SCREENSHOT_AT, SCREENSHOT_AT + timedelta(hours=16))
        assert charging_segments(segs)[0][0] == start
        assert not any(s <= NIGHT_OPEN < e for s, e in charging_segments(segs))


# ═══════════════════════════════════════════════════════════════════════
# The shape, made unrepresentable (#924/#925: over the tree, not the text)
# ═══════════════════════════════════════════════════════════════════════

class TestOneProducerOfTheNeed:
    """Bug classes 37 and 46: the composer's preview re-derived a quantity
    that has one owner. The contract is structural — the preview's inputs
    come through ``ev_preview_inputs`` from exactly one production site, and
    that site reads ``build_night_target_map`` rather than a daily knob."""

    def test_the_preview_inputs_have_exactly_one_production_call_site(self):
        from custom_components.solar_energy_management.tests.ast_contracts import call_sites
        sites = [(f, n) for f, n, _ in call_sites("ev_preview_inputs")
                 if not f.endswith("today_plan.py")]
        assert len(sites) == 1 and sites[0][0].endswith("coordinator/coordinator.py"), sites

    def test_the_composer_site_reads_the_one_producer(self):
        """``build_night_target_map`` is called from the demand collector and
        the night-target map — and now from the composer's preview. A third
        producer of the need would be a fourth call site's absence."""
        from custom_components.solar_energy_management.tests.ast_contracts import call_sites
        files = {f for f, _, _ in call_sites("build_night_target_map")}
        assert "coordinator/coordinator.py" in files

    def test_the_planner_fallback_is_wired_with_the_tariffs_own_levels(self):
        """``plan_night_charge`` receives ``level_at`` from its one caller —
        without it the D3 fix is dead code, exactly the shape a review of
        #939 caught ("the readback was never configured, so the refusal was
        dead code")."""
        from custom_components.solar_energy_management.tests.ast_contracts import call_kwargs
        from custom_components.solar_energy_management.coordinator import ev_control
        kw = call_kwargs(ev_control.EVControlMixin._compute_night_plan, "plan_night_charge")
        assert kw and all("level_at" in k for k in kw), kw


# ═══════════════════════════════════════════════════════════════════════
# His second report: the plan was right, the WINDOW could not show it
# ═══════════════════════════════════════════════════════════════════════

MORNING = DAY.replace(hour=9, minute=37)         # his 17.09 screenshot


def card_window(rows, now):
    """A Python mirror of ``evStripWindow``: the strip ends where the EV's
    own plan ends, floored at 12 h and capped at the composer's 24 h."""
    hour = timedelta(hours=1)
    last = None
    for r in rows:
        if r["kind"] not in ("ev_charge_start", "ev_min_reached", "ev_deadline"):
            continue
        t = datetime.fromisoformat(r["when"])
        if last is None or t > last:
            last = t
    end = now + timedelta(hours=12)
    if last is not None and last > now:
        wanted = (last + timedelta(seconds=1)).replace(minute=0, second=0, microsecond=0)
        if wanted <= last:
            wanted += hour
        end = max(end, wanted)
    return min(end, now + timedelta(hours=24))


class TestTheWindowReachesTheNight:
    """17.09, @alexmc1510: *"unfortunately 'wait' status start around 9pm,
    not 00:00."* By then D3 was holding his charge through punta correctly —
    the composer books 00:00 → 05:39 for a 06:00 deadline. But he read the
    card at 09:37 and the strip is a fixed 12 h: it ended at 21:37, so the
    only thing on it was a wait band opening at 20:26 and running off the
    right edge. A night plan needs a window that reaches the night."""

    def _his_morning_rows(self):
        rate_kw = MIN_A * WPA / 1000.0
        start = affordable_start(NIGHT_OPEN, DEADLINE, NEED_KWH, rate_kw, level_at)
        return start, compose_today_plan(
            now=MORNING, horizon_hours=24, night_start=NIGHT_OPEN, night_end=NIGHT_END,
            ev_min_remaining_kwh=NEED_KWH, ev_deadline=DEADLINE, ev_tariff_optimized=True,
            ev_tariff_waiting=True, ev_next_cheap_window=start, ev_plan_blocks=None,
            ev_effective_rate_kw=rate_kw, ev_row_detail="plan_ev_charge_estimate")

    def test_the_plan_itself_is_right_it_books_the_first_valle_hour(self):
        start, rows = self._his_morning_rows()
        assert start == (DAY + timedelta(days=1)).replace(hour=0, minute=0)
        got = next(r for r in rows if r["kind"] == KIND_EV_CHARGE_START)
        assert datetime.fromisoformat(got["when"]) == start
        assert any(r["kind"] == "ev_deadline" for r in rows)

    def test_a_fixed_twelve_hour_window_shows_him_only_the_wait(self):
        """The bug, reproduced: every EV row he cares about is past the edge."""
        _, rows = self._his_morning_rows()
        edge = MORNING + timedelta(hours=12)              # 21:37
        beyond = [r for r in rows if datetime.fromisoformat(r["when"]) >= edge]
        assert {r["kind"] for r in beyond} == {
            KIND_EV_CHARGE_START, KIND_EV_MIN_REACHED, "ev_deadline"}
        segs = card_segments_fixed(rows, MORNING, edge)
        assert [st for _, _, st in segs] == ["idle", "wait"]
        assert segs[-1][1] == edge, "the wait runs off the right edge, with no end"

    def test_the_window_now_reaches_past_his_deadline(self):
        _, rows = self._his_morning_rows()
        end = card_window(rows, MORNING)
        assert end > DEADLINE
        assert end == (DAY + timedelta(days=1)).replace(hour=7, minute=0)
        assert end - MORNING <= timedelta(hours=24)

    def test_and_then_the_strip_says_wait_until_midnight_then_charge(self):
        start, rows = self._his_morning_rows()
        end = card_window(rows, MORNING)
        segs = card_segments_fixed(rows, MORNING, end)
        # min-reached and the deadline both say "done", so the tail is two
        # abutting bands of one colour — collapse the runs to read the story.
        story = [st for i, (_, _, st) in enumerate(segs)
                 if i == 0 or st != segs[i - 1][2]]
        assert story == ["idle", "wait", "estimate", "done"]
        wait = next((s, e) for s, e, st in segs if st == "wait")
        assert wait == (NIGHT_OPEN, start), (
            "the wait he saw — now bounded by the hour it is waiting FOR")
        booked = next((s, e) for s, e, st in segs if st == "estimate")
        assert booked[0] == start, "and the charge that was past his right edge"

    def test_a_plan_that_fits_inside_twelve_hours_keeps_the_old_window(self):
        """No regression for the common evening read: nothing stretches."""
        evening = DAY.replace(hour=19, minute=0)
        rows = compose_today_plan(
            now=evening, horizon_hours=24, night_start=NIGHT_OPEN, night_end=NIGHT_END,
            ev_min_remaining_kwh=4.0, ev_deadline=DAY.replace(hour=23, minute=0),
            ev_tariff_optimized=False, ev_effective_rate_kw=MIN_A * WPA / 1000.0)
        assert card_window(rows, evening) == evening + timedelta(hours=12)
