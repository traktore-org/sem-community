#!/usr/bin/env bash
# tests/live/test_night_peak_rolling.sh — forever sentinel for the #288
# fix.
#
# Background: pre-#288, ``_night_peak_managed_amps`` sized EV current
# from the *derived* ``power.home_consumption_power``. When upstream
# sensors lagged (notably ``sem_ev_power``, observed up to a 5 kW lag),
# the derived home value was wildly wrong and the per-cycle throttle
# made bad decisions. v1.6.0 (commit 1c5a44c) routes the formula through
# ``sensor.sem_consecutive_peak_15min`` instead — the same 15-min
# rolling grid-import average most demand-charge tariffs bill on.
#
# This sentinel pins the invariant that catches a regression toward
# the derived-home formula:
#
#     During NIGHT_CHARGING_ACTIVE, when the 15-min rolling already
#     exceeds the configured peak limit, the actuator MUST be at
#     the min_amps floor. The rolling-based formula naturally
#     produces this (headroom <= 0 → clamp to min_amps); a regression
#     toward the derived home_consumption_power formula could let the
#     EV ramp up despite the rolling violation because home_consumption
#     gets deflated by EV's own lagged draw.
#
# Why a SKIP-heavy sentinel: NIGHT_CHARGING_ACTIVE + rolling-over-limit
# is a narrow state to hit on a real install. The test correctly
# SKIPS when the conditions don't apply; when they DO apply, the
# assertion is sharp and unambiguous. Run on demand or via cron at
# any moment a night charge is in flight.

set -euo pipefail
source "$(dirname "$0")/lib.sh"

live_init
live_begin "test_night_peak_rolling"

STATE="sensor.sem_charging_state"
ROLLING_KW="sensor.sem_consecutive_peak_15min"
PEAK_LIMIT_KW="sensor.sem_target_peak_limit"
CALC_CURRENT="sensor.sem_calculated_current"
EV_MIN_CURRENT="number.sem_charger_ev_charger_ev_min_current"

state_label=$(get_state "$STATE")
rolling_kw=$(get_state "$ROLLING_KW")
limit_kw=$(get_state "$PEAK_LIMIT_KW")
calc_a=$(get_state "$CALC_CURRENT")
_log "state=${state_label}  rolling_15min=${rolling_kw} kW  peak_limit=${limit_kw} kW  calc=${calc_a} A"

# ──────────────────────────────────────────────────────────────────────
# Precondition 1 — sensors readable.
# ──────────────────────────────────────────────────────────────────────
for v in "$state_label" "$rolling_kw" "$limit_kw" "$calc_a"; do
    if [[ -z "$v" || "$v" == "unknown" || "$v" == "unavailable" || "$v" == "?" ]]; then
        _log "SKIP: an input is '$v' — can't evaluate the invariant"
        exit 0
    fi
done

# ──────────────────────────────────────────────────────────────────────
# Precondition 2 — must be in night-charging-active state. The throttle
# only runs in this branch; other states have their own logic.
# ──────────────────────────────────────────────────────────────────────
case "$state_label" in
    *"Night charging active"*)
        _log "✓ in NIGHT_CHARGING_ACTIVE — invariant applies"
        ;;
    *)
        _log "SKIP: state is '$state_label', not NIGHT_CHARGING_ACTIVE"
        exit 0
        ;;
esac

# ──────────────────────────────────────────────────────────────────────
# Precondition 3 — rolling must be at or above the limit. Below the
# limit, headroom is positive; the actuator legitimately ramps up.
# The invariant only bites in the over-limit regime.
# ──────────────────────────────────────────────────────────────────────
should_clamp=$(python3 -c "
try:
    r = float('$rolling_kw'); l = float('$limit_kw')
    print(1 if r >= l else 0)
except Exception:
    print(0)
")

if [[ "$should_clamp" != "1" ]]; then
    _log "(rolling=${rolling_kw} < limit=${limit_kw} — headroom positive, invariant doesn't apply)"
    live_end
    exit 0
fi

# ──────────────────────────────────────────────────────────────────────
# The assertion: rolling is over limit AND we're in night charging.
# Calc_current MUST be at min_amps. A regression toward
# home_consumption_power would let the EV ramp up here because the
# EV's own (lagged) draw would deflate the derived home value.
# ──────────────────────────────────────────────────────────────────────
min_a=$(get_state "$EV_MIN_CURRENT")
if [[ -z "$min_a" || "$min_a" == "?" || "$min_a" == "unknown" || "$min_a" == "unavailable" ]]; then
    min_a="6"  # SEM default; KEBA-class min current
    _log "(min_amps not readable from $EV_MIN_CURRENT — using SEM default 6)"
fi

calc_int=$(printf '%.0f' "$calc_a" 2>/dev/null || echo 99)
min_int=$(printf '%.0f' "$min_a" 2>/dev/null || echo 6)

if (( calc_int > min_int )); then
    echo "✗ FAIL: rolling 15-min peak (${rolling_kw} kW) >= limit (${limit_kw} kW)" >&2
    echo "        but calculated_current = ${calc_a} A > min_amps (${min_int} A)" >&2
    echo "" >&2
    echo "        Under #288's rolling-based formula, headroom = limit − rolling = ${limit_kw} − ${rolling_kw}" >&2
    echo "        ≤ 0 → result MUST clamp to min_amps. A higher current means SEM is" >&2
    echo "        sizing from a different (broken) signal — most likely the pre-#288" >&2
    echo "        derived ``power.home_consumption_power`` got deflated by EV's lagged draw." >&2
    echo "" >&2
    echo "        Investigate ``coordinator/ev_control.py:_night_peak_managed_amps`` and" >&2
    echo "        ``_get_peak_15min_w`` — confirm the rolling path is firing, not the" >&2
    echo "        legacy fallback. The fallback is only meant to fire when" >&2
    echo "        ``_load_manager`` is None or has no samples (cold start)." >&2
    exit 1
fi

_log "✓ rolling over limit AND calc_current clamped to min_amps as expected"
live_end
