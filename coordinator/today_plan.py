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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "when": self.when.isoformat(),
            "kind": self.kind,
            "label": self.label,
            "detail": self.detail,
            "values": self.values,
        }


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
    gaps = [b["t"] - a["t"] for a, b in zip(points, points[1:])
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

        cheap_levels = ("cheap", "very_cheap", "negative")
        expensive_levels = ("expensive", "very_expensive")

        for block in _consecutive_blocks(future, cheap_levels, min_block_len=2):
            avg_price = sum(block["prices"]) / len(block["prices"])
            rows.append(PlanRow(
                when=block["start"], kind=KIND_CHEAP_START,
                label="plan_cheap_start",
                detail="plan_cheap_detail",
                values={"end": block["end"].strftime("%H:%M"),
                        "price": f"{avg_price:.2f}", "currency": currency},
            ))
        for block in _consecutive_blocks(future, expensive_levels, min_block_len=2):
            avg_price = sum(block["prices"]) / len(block["prices"])
            rows.append(PlanRow(
                when=block["start"], kind=KIND_EXPENSIVE_START,
                label="plan_expensive_start",
                detail="plan_expensive_detail",
                values={"end": block["end"].strftime("%H:%M"),
                        "price": f"{avg_price:.2f}", "currency": currency},
            ))

    # === Night window ===
    if night_start and now < night_start < horizon:
        rows.append(PlanRow(
            when=night_start, kind=KIND_NIGHT_OPEN, label="plan_night_open",
        ))

    # === EV-specific rows (only when there's actually charging to plan for) ===
    if ev_min_remaining_kwh and ev_min_remaining_kwh > 0.1:
        # (#742) waiting + a window is the honest display signal
        # REGARDLESS of who produced it: the legacy tariff mode
        # (solar_plus_cheap) or the joint plan's overlay, which holds
        # ALL night modes since #638 Stage 1. Gating on
        # ev_tariff_optimized left a min_plus_solar hold invisible —
        # the Energy Plan card said WAITS·00:00 while this strip drew
        # the reactive prediction (live, 08.08 23:10).
        if ev_tariff_waiting and ev_next_cheap_window:
            if now < ev_next_cheap_window < horizon:
                rows.append(PlanRow(
                    when=ev_next_cheap_window,
                    kind=KIND_EV_CHARGE_START,
                    label="plan_ev_charge_start",
                    detail="plan_ev_charge_tariff",
                ))
        elif night_start and night_start > now:
            # Will charge from night_start at peak-managed rate
            rows.append(PlanRow(
                when=night_start, kind=KIND_EV_CHARGE_START,
                label="plan_ev_charge_start",
                detail="plan_ev_charge_night",
            ))

        # Min-reached estimate
        if ev_effective_rate_kw and ev_effective_rate_kw > 0.3:
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
