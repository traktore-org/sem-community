"""Today's plan composer (#282): rolling forward-looking schedule.

Composes a single forward-looking plan list from the four data sources we
already have per cycle:

* **Tariff curve** — ``upcoming_prices`` (24-48 hourly points with cheap/normal/
  expensive level classification)
* **Solar forecast** — Solcast peak time + remaining today + tomorrow total
* **EV state** — Min, Max, deadline, tariff opt-in, remaining-to-Min
* **Night window** — start (sunset+10 / 20:30 floor) and end (07:00 default)

The composer is a pure function so the coordinator can call it directly and
expose the result on ``sensor.sem_charging_state.attributes.today_plan``. The
card consumes it without re-running any of the underlying calculations.

The plan is **time-keyed** (not minute-precise): each row is a notable
*transition* — when does charging start, when does a cheap window open, when
will Min be reached, when does the deadline land. Users scan it left-to-right,
not as a Gantt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from .price_signal import CHEAP_LEVELS, EXPENSIVE_LEVELS


# Row kinds — keyed strings the card maps to icons + colors.
KIND_NOW = "now"
KIND_SOLAR_PEAK = "solar_peak"
KIND_SOLAR_END = "solar_end"
KIND_CHEAP_START = "cheap_start"
KIND_CHEAP_END = "cheap_end"
KIND_EXPENSIVE_START = "expensive_start"
KIND_EXPENSIVE_END = "expensive_end"
KIND_NIGHT_OPEN = "night_open"
KIND_NIGHT_END = "night_end"
KIND_EV_CHARGE_START = "ev_charge_start"
KIND_EV_MIN_REACHED = "ev_min_reached"
KIND_EV_TARGET_REACHED = "ev_target_reached"  # #298: live "reach Max/SOC target" ETA
KIND_EV_DEADLINE = "ev_deadline"
KIND_EV_WAIT = "ev_wait"
KIND_BATTERY_FULL = "battery_full"   # #298: home battery charging → full ETA
KIND_BATTERY_EMPTY = "battery_empty"  # #298: home battery discharging → floor ETA
KIND_DEVICE_RUN = "device_run"       # #576: a surplus device's expected run window
KIND_DEVICE_DONE = "device_done"     # #576: a surplus device met its daily goal
KIND_EXPORT_CLOSED = "export_closed"   # arc #921: the meter closes (export price negative)
KIND_EXPORT_REOPENS = "export_reopens" # arc #921: the meter reopens


@dataclass
class PlanRow:
    """One forward-looking transition.

    Attributes:
        when: Absolute time (ISO) — card formats to HH:MM.
        kind: Stable key (one of KIND_*) for icon/color lookup.
        label: Translation key for the row label (resolved by the card via
            semLocalize).
        detail: Translation key for the secondary text. ``None`` if the row
            is single-line.
        values: Substitutions for the label/detail format strings, e.g.
            ``{"kwh": "8.5", "price": "0.10"}``.
    """
    when: datetime
    kind: str
    label: str
    detail: Optional[str] = None
    values: Dict[str, Any] = field(default_factory=dict)
    #: (#1023) where a charge window ends — the EV strip draws the gap after
    #: it as waiting, not as one bar to the last block's end
    until: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        out = {
            # (#829) Minute resolution. A plan is a minute-grained promise and
            # the card renders it with an hours:minutes formatter, but the raw
            # stamp carried seconds AND microseconds — so rows whose ``when``
            # is "now" (or a jittering projection) re-serialised every 10 s
            # cycle and made sensor.sem_charging_state write a recorder row
            # each time, with nothing a human could see having changed.
            "when": self.when.replace(second=0, microsecond=0).isoformat(),
            "kind": self.kind,
            "label": self.label,
            "detail": self.detail,
            "values": self.values,
        }
        if self.until is not None:
            out["until"] = self.until.replace(second=0, microsecond=0).isoformat()
        return out


_DEFAULT_SLOT = timedelta(hours=1)


def _slot_duration(points: List[Dict[str, Any]]) -> timedelta:
    """How long one price point covers, read off the curve's own cadence.

    Most markets post hourly, but 15-minute curves exist, so measure rather
    than assume. The cadence is the SMALLEST positive gap: a missing slot
    leaves a double-width gap that must not be read as a wider slot, and a
    duplicated timestamp leaves a zero gap that would collapse every window
    onto its own start. One lone point has nothing to measure — fall back to
    the common case (#729).

    A curve that changes cadence half-way (an hourly day followed by a
    quarter-hourly one, as markets moving to 15-minute settlement briefly
    post) is measured by its finer half. No single number describes such a
    curve; providers post one cadence, and reading the window slightly
    short beats reading it long.
    """
    gaps = [b["t"] - a["t"] for a, b in zip(points, points[1:], strict=False)
            if b["t"] > a["t"]]
    return min(gaps) if gaps else _DEFAULT_SLOT


def _consecutive_blocks(
    points: List[Dict[str, Any]],
    levels: tuple,
    min_block_len: int = 1,
) -> List[Dict[str, Any]]:
    """Group consecutive `upcoming` points whose level ∈ levels into blocks.

    ``end`` is the block's **closing boundary** — one slot past the last
    matching point, not that point's own timestamp. Cheap slots 00:00
    through 05:00 mean cheap power until 06:00, and that is what the user
    needs to read (#729).
    """
    blocks: List[Dict[str, Any]] = []
    slot = _slot_duration(points)
    cur_start = None
    cur_prices: List[float] = []
    last_t = None
    for p in points:
        if p.get("level") in levels:
            if cur_start is None:
                cur_start = p["t"]
            cur_prices.append(p.get("price", 0.0))
            last_t = p["t"]
        else:
            if cur_start and len(cur_prices) >= min_block_len:
                blocks.append({"start": cur_start, "end": last_t + slot,
                               "prices": list(cur_prices)})
            cur_start = None
            cur_prices = []
    if cur_start and len(cur_prices) >= min_block_len:
        blocks.append({"start": cur_start, "end": last_t + slot,
                       "prices": list(cur_prices)})
    return blocks


def _merge_touching(
    blocks: List[tuple],
    join_gap: timedelta = timedelta(minutes=1),
) -> List[tuple]:
    """(#963) Collapse ``(start, end)`` pairs that touch into single windows.

    The joint plan hands out one block per pricing slot, but a user reads the
    plan for *transitions*: a run of adjacent slots is ONE charge that starts
    once. Only genuinely adjacent blocks merge — ``join_gap`` absorbs slot
    arithmetic (an end at 14:59:59.999 against a start at 15:00), never a real
    pause. A gap means SEM stops and starts again, and that second start is a
    transition the user wants to see.

    Assumes ``blocks`` is sorted by start, which is the caller's contract.
    """
    windows: List[tuple] = []
    for start, end in blocks:
        if windows and start <= windows[-1][1] + join_gap:
            windows[-1] = (windows[-1][0], max(windows[-1][1], end))
        else:
            windows.append((start, end))
    return windows


def ev_preview_inputs(*, night_need_kwh: float, peak_managed_amps: int,
                      watts_per_amp: float, gate_covered: bool):
    """(#967) What the strip's EV preview is allowed to be drawn from.

    ``(kwh, rate_kw, detail)`` for the daytime preview — the hours before the
    per-charger night plan exists. The kWh is the ONE producer's answer
    (``build_night_target_map`` → ``_calculate_remaining_need``): for a
    SOC-target charger that is ``target − the car's own reading``, never the
    per-day ``daily_ev_target`` knob. The rate is the peak-managed current the
    reactive night charge will actually run at, never a literal. And until the
    joint plan's gate covers the car the row is an ESTIMATE and says so —
    @alexmc1510's strip promised a 4.5 kWh / 4.1 kW bar (20:36–21:41) for a
    19.8 kWh need, drawn as if booked.
    """
    kwh = max(0.0, float(night_need_kwh or 0.0))
    rate_kw = max(0.0, float(peak_managed_amps or 0) * float(watts_per_amp or 0.0) / 1000.0)
    detail = "plan_ev_charge_night" if gate_covered else "plan_ev_charge_estimate"
    return kwh, rate_kw, detail


def compose_today_plan(
    *,
    now: datetime,
    horizon_hours: int = 24,
    upcoming_prices: Optional[List[Dict[str, Any]]] = None,
    solar_peak_time: Optional[str] = None,
    solar_remaining_kwh: Optional[float] = None,
    night_start: Optional[datetime] = None,
    night_end: Optional[datetime] = None,
    ev_min_remaining_kwh: Optional[float] = None,
    ev_deadline: Optional[datetime] = None,
    ev_tariff_optimized: bool = False,
    ev_tariff_waiting: bool = False,
    ev_next_cheap_window: Optional[datetime] = None,
    ev_plan_blocks: Optional[list] = None,
    ev_effective_rate_kw: Optional[float] = None,
    # #298 — live ETAs while a session is actually charging / discharging.
    # Pass ``None`` to suppress the row (e.g. when SOC is already at the
    # boundary or the rate is too small to make a useful estimate).
    ev_target_eta: Optional[datetime] = None,
    ev_target_kwh: Optional[float] = None,
    battery_full_eta: Optional[datetime] = None,
    battery_empty_eta: Optional[datetime] = None,
    # #576 — the OTHER surplus devices (pump / heat pump / hot water / climate)
    # in the same forward timeline as the battery/EV. Each dict:
    #   {"name": str, "when": datetime, "done": bool, "detail": str|None}
    # ``done`` → the device met its daily goal (a KIND_DEVICE_DONE row); else a
    # KIND_DEVICE_RUN "expected to run" row. The coordinator computes ``when``
    # from the solar forecast + the device's list position; this pure function
    # just formats them so it stays unit-testable.
    device_runs: Optional[List[Dict[str, Any]]] = None,
    currency: str = "",
    # arc #921 — from the grid verdict's ``until``: an OPEN verdict carries the
    # next closing, a CLOSED one the reopening. The grid stops being a sink.
    export_closes_at: Optional[datetime] = None,
    export_reopens_at: Optional[datetime] = None,
    ev_row_detail: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Build the forward-looking plan as a list of row dicts.

    Args:
        now: Current time (tz-aware).
        horizon_hours: How far ahead to look (default 24).
        upcoming_prices: List of ``{"t": iso, "price": float, "level": str}``.
        solar_peak_time: Solcast peak forecast time today (iso) or HH:MM.
        solar_remaining_kwh: Solcast forecast_remaining_today.
        night_start / night_end: Resolved night-window endpoints.
        ev_min_remaining_kwh: kWh still owed to reach Min on the primary
            charger; ``None`` or 0 ⇒ no EV rows emitted.
        ev_deadline: Resolved ``Charge by`` time for primary charger.
        ev_tariff_optimized: True if tariff-optimized switch is ON.
        ev_tariff_waiting: True if the planner is currently waiting.
        ev_next_cheap_window: When the next cheap slot opens.
        ev_plan_blocks: (#742) THIS charger's blocks from the stamped joint
            plan, passed only when the gate covers the demand. When present
            the EV rows come from the blocks — one start per future block,
            min-reached at the last block's end — and the reactive
            prediction below becomes the uncovered fallback it always
            should have been. One data source, every surface.
        ev_effective_rate_kw: Realistic peak-managed charge rate, used to
            estimate when Min will be reached.
        currency: Currency suffix for price values.

    Returns:
        A list of plan row dicts ordered by ``when``, clipped to the horizon.
    """
    rows: List[PlanRow] = []
    horizon = now + timedelta(hours=horizon_hours)

    # === Always anchor with "now" ===
    rows.append(PlanRow(
        when=now, kind=KIND_NOW, label="plan_now",
        values={"time": now.strftime("%H:%M")},
    ))

    # === Solar peak + remaining ===
    if solar_peak_time and solar_remaining_kwh and solar_remaining_kwh > 0.5:
        try:
            if "T" in solar_peak_time:
                peak_dt = datetime.fromisoformat(solar_peak_time.replace("Z", "+00:00"))
                if peak_dt.tzinfo and now.tzinfo:
                    peak_dt = peak_dt.astimezone(now.tzinfo)
            else:
                # "HH:MM" → today
                h, m = solar_peak_time.split(":")
                peak_dt = now.replace(hour=int(h), minute=int(m),
                                      second=0, microsecond=0)
            if now < peak_dt < horizon:
                rows.append(PlanRow(
                    when=peak_dt, kind=KIND_SOLAR_PEAK,
                    label="plan_solar_peak",
                    values={"kwh": f"{solar_remaining_kwh:.1f}"},
                ))
        except (ValueError, TypeError):
            pass

    # === Tariff blocks (cheap + expensive) — show start of each block ===
    if upcoming_prices:
        # Filter to horizon + future
        future = []
        for p in upcoming_prices:
            try:
                t = datetime.fromisoformat(p["t"].replace("Z", "+00:00"))
                if now.tzinfo:
                    t = t.astimezone(now.tzinfo)
                if t >= now and t < horizon:
                    future.append({**p, "t": t})
            except (ValueError, TypeError, KeyError):
                continue

        # (#994) one vocabulary, and a flat tariff draws neither block.
        cheap_levels = tuple(lv.value for lv in CHEAP_LEVELS)
        expensive_levels = tuple(lv.value for lv in EXPENSIVE_LEVELS)

        for block in _consecutive_blocks(future, cheap_levels, min_block_len=2):
            avg_price = sum(block["prices"]) / len(block["prices"])
            rows.append(PlanRow(
                when=block["start"], kind=KIND_CHEAP_START,
                label="plan_cheap_start",
                detail="plan_cheap_detail",
                values={"end": block["end"].strftime("%H:%M"),
                        "price": f"{avg_price:.2f}", "currency": currency},
            ))
        # (#992, class 99) The expensive row used to promise "Min+PV grid
        # pauses" on every expensive block in the curve — on installs with no
        # EV at all, on chargers past their Min, on Always-Max and Off. It is
        # a claim about a charger, so it is made only when there is a charge
        # still to make: the same gate the EV rows below use. Its cheap-block
        # sibling never claimed anything of the sort.
        #
        # …and only when the charger's MODE pauses for price at all. Gating
        # on the Min shortfall alone still promised a pause for Always-Max,
        # which charges through every expensive hour by definition — and an
        # unmet Min is close to the default state, since every install gets
        # a daily target whatever its mode. ``ev_tariff_optimized`` is the
        # resolver for exactly this question (only solar_plus_cheap defers),
        # and the composer was already being handed it.
        _pause_claim = bool(ev_tariff_optimized
                            and ev_min_remaining_kwh
                            and ev_min_remaining_kwh > 0.1)
        for block in _consecutive_blocks(future, expensive_levels, min_block_len=2):
            avg_price = sum(block["prices"]) / len(block["prices"])
            rows.append(PlanRow(
                when=block["start"], kind=KIND_EXPENSIVE_START,
                label="plan_expensive_start",
                detail=("plan_expensive_detail" if _pause_claim
                        else "plan_expensive_detail_plain"),
                values={"end": block["end"].strftime("%H:%M"),
                        "price": f"{avg_price:.2f}", "currency": currency},
            ))

    # === arc #921: the meter closes / reopens (the grid stops being a sink) ===
    if export_closes_at and now < export_closes_at < horizon:
        rows.append(PlanRow(when=export_closes_at, kind=KIND_EXPORT_CLOSED,
                            label="plan_export_closed"))
    if export_reopens_at and now < export_reopens_at < horizon:
        rows.append(PlanRow(when=export_reopens_at, kind=KIND_EXPORT_REOPENS,
                            label="plan_export_reopens"))

    # === Night window ===
    if night_start and now < night_start < horizon:
        rows.append(PlanRow(
            when=night_start, kind=KIND_NIGHT_OPEN, label="plan_night_open",
        ))

    # === EV-specific rows (only when there's actually charging to plan for) ===
    if ev_min_remaining_kwh and ev_min_remaining_kwh > 0.1:
        # (#742) When the joint plan covers this charger, its BLOCKS are the
        # rows — the live 08.08 regression was this strip painting the
        # reactive prediction while the Energy Plan card said WAITS·00:00.
        parsed_blocks = []
        late_blocks = set()
        for b in (ev_plan_blocks or []):
            try:
                bs = datetime.fromisoformat(str(b["start"]))
                be = datetime.fromisoformat(str(b["end"]))
            except (KeyError, TypeError, ValueError):
                parsed_blocks = []
                break  # one malformed block distrusts the set (gate rule)
            parsed_blocks.append((bs, be))
            if b.get("late"):
                late_blocks.add((bs, be))
        if parsed_blocks:
            parsed_blocks.sort()
            # (#963, @HorizonKane: "scheduler full of events that won't
            # happen") The joint plan is expressed in hourly BLOCKS, so a
            # charge running 14:00–17:00 arrives here as three of them. One
            # row per block announced "EV charging starts" three times for a
            # single start — and since the composer caps at 8 rows, six such
            # rows evicted the solar peak, the night window and the deadline,
            # leaving a plan made almost entirely of events that never happen.
            # Merge blocks that TOUCH into windows and announce each window's
            # start once. A real gap stays a real second start: his 17:00 hole
            # is SEM stopping and starting again, which is worth a row.
            #
            # (#1023) The top-up before departure is its own window even when
            # it touches the rest: it runs whatever the price, and the row
            # says so. Each start carries its window's end, so the strip draws
            # a gap as waiting instead of one bar to the last block's end.
            windows = sorted(
                [(ws, we, False) for ws, we in _merge_touching(
                    [p for p in parsed_blocks if p not in late_blocks])]
                + [(ws, we, True) for ws, we in _merge_touching(
                    [p for p in parsed_blocks if p in late_blocks])])
            for bs, be, is_late in windows:
                if now < bs < horizon:
                    # Two literal keys, so the translation guard sees both.
                    rows.append(
                        PlanRow(when=bs, kind=KIND_EV_CHARGE_START,
                                label="plan_ev_charge_start",
                                detail="plan_ev_charge_late", until=be)
                        if is_late else
                        PlanRow(when=bs, kind=KIND_EV_CHARGE_START,
                                label="plan_ev_charge_start",
                                detail="plan_ev_charge_joint", until=be))
            # The last WINDOW's end, not the last block's: for touching,
            # non-overlapping allocations (what pack_night emits) these are
            # the same instant; for a block contained in an earlier one it is
            # the honest answer where the old value was the inner block's.
            last_end = max(we for _ws, we, _late in windows)
            if now < last_end < horizon:
                # The plan's own promise — not a rate estimate.
                rows.append(PlanRow(
                    when=last_end, kind=KIND_EV_MIN_REACHED,
                    label="plan_ev_min_reached",
                ))
        # (#742) waiting + a window is the honest display signal
        # REGARDLESS of who produced it: the legacy tariff mode
        # (solar_plus_cheap) or the joint plan's overlay, which holds
        # ALL night modes since #638 Stage 1. Gating on
        # ev_tariff_optimized left a min_plus_solar hold invisible —
        # the Energy Plan card said WAITS·00:00 while this strip drew
        # the reactive prediction (live, 08.08 23:10).
        if parsed_blocks:
            pass  # the blocks above are the rows — no reactive prediction
        elif ev_tariff_waiting and ev_next_cheap_window:
            if now < ev_next_cheap_window < horizon:
                rows.append(PlanRow(
                    when=ev_next_cheap_window,
                    kind=KIND_EV_CHARGE_START,
                    label="plan_ev_charge_start",
                    # (#967) By day this branch is reached by the PREVIEW's
                    # own affordable start, and a preview is an estimate
                    # wherever its time came from — the caveat belongs to the
                    # row, not to the branch that produced the hour.
                    detail=ev_row_detail or "plan_ev_charge_tariff",
                ))
        elif night_start and night_start > now:
            # Will charge from night_start at peak-managed rate. (#967) By
            # day this is a PREVIEW of a night the planner has not seen yet;
            # the coordinator says so through ``ev_row_detail`` so the card
            # draws an estimate, not a booking.
            rows.append(PlanRow(
                when=night_start, kind=KIND_EV_CHARGE_START,
                label="plan_ev_charge_start",
                detail=ev_row_detail or "plan_ev_charge_night",
            ))

        # Min-reached estimate (legacy fallback — with blocks the last
        # block's end above is the plan's own promise)
        if not parsed_blocks and ev_effective_rate_kw and ev_effective_rate_kw > 0.3:
            charge_start = ev_next_cheap_window if (
                ev_tariff_waiting and ev_next_cheap_window
            ) else night_start
            if charge_start and charge_start > now:
                hours_to_min = ev_min_remaining_kwh / ev_effective_rate_kw
                min_reached = charge_start + timedelta(hours=hours_to_min)
                if min_reached < horizon:
                    rows.append(PlanRow(
                        when=min_reached, kind=KIND_EV_MIN_REACHED,
                        label="plan_ev_min_reached",
                        values={"kwh": f"{ev_min_remaining_kwh:.1f}"},
                    ))

        if ev_deadline and now < ev_deadline < horizon:
            rows.append(PlanRow(
                when=ev_deadline, kind=KIND_EV_DEADLINE,
                label="plan_ev_deadline",
            ))

    # === Live ETAs (#298) — only emitted when an actual session is in
    # progress. The caller computes them from current power + remaining
    # capacity; this module just renders them as plan rows.

    # EV target reached — when the car is actively charging right now and
    # an ETA to the Max/SOC target is within the horizon. Distinct from
    # ``plan_ev_min_reached`` above which is a NIGHT planner estimate
    # (when will the deadline-floor be hit). This row tracks the LIVE
    # session's projected completion.
    if ev_target_eta and now < ev_target_eta < horizon:
        rows.append(PlanRow(
            when=ev_target_eta, kind=KIND_EV_TARGET_REACHED,
            label="plan_ev_target_reached",
            values=(
                {"kwh": f"{ev_target_kwh:.1f}"}
                if ev_target_kwh is not None else {}
            ),
        ))

    # Home battery — full or empty ETA. Mutually exclusive in practice
    # (a battery is either charging or discharging), so the caller
    # passes one or the other based on the current ``battery_power``
    # sign. We accept both for defensive clarity; if both are passed
    # we emit both rows.
    if battery_full_eta and now < battery_full_eta < horizon:
        rows.append(PlanRow(
            when=battery_full_eta, kind=KIND_BATTERY_FULL,
            label="plan_battery_full",
        ))
    if battery_empty_eta and now < battery_empty_eta < horizon:
        rows.append(PlanRow(
            when=battery_empty_eta, kind=KIND_BATTERY_EMPTY,
            label="plan_battery_empty",
        ))

    # === #576 — the other surplus devices (pump / heat pump / hot water /
    # climate) in the same forward timeline. A "done" device shows a
    # goal-met row; the rest show an "expected to run" row at the projected
    # time. ``when`` is clamped into the horizon by the caller; we guard here.
    for dev in device_runs or []:
        when = dev.get("when")
        if not isinstance(when, datetime) or not (now <= when < horizon):
            continue
        done = bool(dev.get("done"))
        rows.append(PlanRow(
            when=when,
            kind=KIND_DEVICE_DONE if done else KIND_DEVICE_RUN,
            label="plan_device_done" if done else "plan_device_run",
            detail=dev.get("detail"),
            values={"name": str(dev.get("name", ""))},
        ))

    # Sort + return as dicts. Cap at 8 rows so the card stays glanceable.
    rows.sort(key=lambda r: r.when)
    return [r.to_dict() for r in rows[:8]]
