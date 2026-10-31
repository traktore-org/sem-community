"""(#1174) Stable reason codes — why a device's command changed, as a code.

Each decision family sets ONE of these where the decision is made
(``decide.py`` and ``charge_stability.py`` for chargers, ``decide_battery.py``
for batteries, ``surplus_controller.py`` and the load manager for loads).
The decision log carries the code and its few named numbers into every
record; the Why? card and the logbook turn it into a plain sentence from
ONE catalogue: the ``why_reason_<code>`` keys in
``dashboard/translations.json``, in every language.

The internal reason text stays beside the code, unchanged: it is what the
diagnostics and the observer surface read. A code changes no decision —
it is recorded, never read back by a decider.

Codes are part of the record's contract: rename one only together with
its catalogue key. ``PARAMS`` names the placeholders a code's sentence
uses; ``tests/test_1174_plain_reasons.py`` pins that every code here has a
sentence in all languages, that every sentence has a code, and that each
sentence uses exactly the placeholders listed.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Tuple

# ── chargers ─────────────────────────────────────────────────────────
CHARGER_OFF = "charger_off"
CHARGER_NO_CAR = "charger_no_car"
CHARGER_FULL = "charger_full"
CHARGER_MAX = "charger_max"
CHARGER_LOW_SUN = "charger_low_sun"
CHARGER_SUN = "charger_sun"
CHARGER_SUN_BATTERY = "charger_sun_battery"
CHARGER_BATTERY_FIRST = "charger_battery_first"
CHARGER_MIN_TODAY = "charger_min_today"
CHARGER_MIN_DONE = "charger_min_done"
CHARGER_PLAN_WAIT = "charger_plan_wait"
CHARGER_PLAN_WAIT_UNTIL = "charger_plan_wait_until"
CHARGER_DEADLINE = "charger_deadline"
CHARGER_TOP_UP = "charger_top_up"
CHARGER_NO_NIGHT = "charger_no_night"
CHARGER_PEAK_PAUSE = "charger_peak_pause"
CHARGER_PEAK_SLOW = "charger_peak_slow"
CHARGER_PEAK_STOP = "charger_peak_stop"
CHARGER_PHASE_SLOW = "charger_phase_slow"
CHARGER_PHASE_STOP = "charger_phase_stop"
CHARGER_INPUTS_MISSING = "charger_inputs_missing"
CHARGER_CAR_DECLINED = "charger_car_declined"
CHARGER_START = "charger_start"
CHARGER_WAIT_STEADY = "charger_wait_steady"
CHARGER_DIP_HOLD = "charger_dip_hold"
CHARGER_DIP_STOP = "charger_dip_stop"
CHARGER_PHASE_SWITCH = "charger_phase_switch"
CHARGER_GRID_EVENT = "charger_grid_event"
CHARGER_STOP_NOW = "charger_stop_now"
CHARGER_RAMP = "charger_ramp"
CHARGER_HOLD_STEADY = "charger_hold_steady"
CHARGER_PLAN_OVERRIDE_STOP = "charger_plan_override_stop"
CHARGER_PLAN_OVERRIDE_RUN = "charger_plan_override_run"

# ── batteries ────────────────────────────────────────────────────────
BATTERY_OFF = "battery_off"
BATTERY_MANUAL_SELL = "battery_manual_sell"
BATTERY_MANUAL_SELL_HOLD = "battery_manual_sell_hold"
BATTERY_MANUAL_CHARGE = "battery_manual_charge"
BATTERY_NEGATIVE_PRICE = "battery_negative_price"
BATTERY_PLAN_CHARGE = "battery_plan_charge"
BATTERY_PLAN_WAIT = "battery_plan_wait"
BATTERY_PLAN_NONE = "battery_plan_none"
BATTERY_SELL = "battery_sell"
BATTERY_SELL_FORECAST = "battery_sell_forecast"
BATTERY_SELL_HOLD = "battery_sell_hold"
BATTERY_SELL_STOP = "battery_sell_stop"
BATTERY_CHARGE_STOP = "battery_charge_stop"
BATTERY_FEEDS_CAR = "battery_feeds_car"
BATTERY_HOUSE_HELD = "battery_house_held"
BATTERY_HOUSE_HELD_PEAK = "battery_house_held_peak"
BATTERY_HOUSE_BLIND = "battery_house_blind"
BATTERY_CAR_NOT_ALLOWED = "battery_car_not_allowed"
BATTERY_CAR_LEVEL_UNKNOWN = "battery_car_level_unknown"
BATTERY_CAR_BELOW_FLOOR = "battery_car_below_floor"
BATTERY_CAR_BELOW_RESERVE = "battery_car_below_reserve"
BATTERY_CAR_LOW_SUN = "battery_car_low_sun"
BATTERY_CAR_SHARED = "battery_car_shared"
BATTERY_GRID_LOADS = "battery_grid_loads"
BATTERY_NORMAL = "battery_normal"
BATTERY_END_CHARGE = "battery_end_charge"
BATTERY_END_SELL = "battery_end_sell"
BATTERY_CHARGE_NO_ROOM = "battery_charge_no_room"
BATTERY_CHARGE_SLOWED = "battery_charge_slowed"

# ── loads ────────────────────────────────────────────────────────────
# The first values predate the catalogue (#1084) and keep their spelling:
# they are already in recorded events.
LOAD_START = "start"
LOAD_ADJUST = "adjust"
LOAD_STOP = "stop"
LOAD_SOLAR = "solar"
LOAD_TIER1_BATTERY = "tier1_battery"
LOAD_TIER2_BATTERY = "tier2_battery"
LOAD_CHEAP_GRID = "cheap_grid"
LOAD_SURPLUS = "surplus"
LOAD_SURPLUS_SHORT = "surplus_short"
LOAD_TEARDOWN = "teardown"
LOAD_OVERNIGHT_END = "overnight_end"
LOAD_TARGET_MET = "target_met"
LOAD_DEPENDENCY = "dependency"
LOAD_PHASE_GUARD = "phase_guard"
LOAD_PHASE_SHED = "phase_shed"
LOAD_PEAK_SHED = "peak_shed"
LOAD_PEAK_RESTORE = "peak_restore"
LOAD_DEADLINE = "deadline"
LOAD_PLAN_WINDOW = "plan_window"
LOAD_VACATION = "vacation"
LOAD_MODE_OFF = "mode_off"
LOAD_PLAN_CLOSED = "plan_closed"
LOAD_DAILY_MAX = "daily_max"
LOAD_STOP_CONDITION = "stop_condition"
LOAD_PLAN_WAIT = "plan_wait"
LOAD_NO_SOURCE = "no_source"

# ── the grid export limit (#1090) ────────────────────────────────────
EXPORT_NEGATIVE_PRICE = "export_negative_price"
EXPORT_NOT_WORTH = "export_not_worth"
EXPORT_RELEASED = "export_released"
EXPORT_GUARD_OFF = "export_guard_off"
EXPORT_PRICE_UNKNOWN = "export_price_unknown"

#: The placeholders a code's sentence fills, by name. A code not listed
#: takes none.
PARAMS: Dict[str, Tuple[str, ...]] = {
    CHARGER_PLAN_WAIT_UNTIL: ("time",),
    CHARGER_PLAN_OVERRIDE_STOP: ("time",),
    CHARGER_PLAN_OVERRIDE_RUN: ("time",),
    BATTERY_FEEDS_CAR: ("floor",),
    BATTERY_CAR_BELOW_FLOOR: ("floor",),
    EXPORT_NOT_WORTH: ("value", "threshold"),
}

#: Every code the code base can set.
ALL_CODES: FrozenSet[str] = frozenset(
    value for name, value in dict(globals()).items()
    if name.isupper()
    and name.split("_", 1)[0] in ("CHARGER", "BATTERY", "LOAD", "EXPORT")
    and isinstance(value, str)
)

#: The catalogue key of a code's sentence.
KEY_PREFIX = "why_reason_"


def catalogue_key(code: str) -> str:
    return f"{KEY_PREFIX}{code}"
