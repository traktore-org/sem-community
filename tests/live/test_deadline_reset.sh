#!/usr/bin/env bash
# tests/live/test_deadline_reset.sh — verify the EV daily counter resets at
# the per-charger Charge-by deadline, not sunrise. Codifies the experiment
# we ran on 2026-05-29 06:38 that locked in the #279 follow-up fix.
#
# Test shape:
#   1. Snapshot the current daily_ev_energy + target_time.
#   2. Set target_time to "now + 2 minutes" — boundary crossing soon.
#   3. Poll daily_ev_energy across the new boundary, capturing values.
#   4. Assert: counter HELD before the new target_time crossing.
#   5. Assert: counter RESET to 0 within one cycle after the crossing.
#   6. Restore the original target_time.
#
# This catches the bug class where a calendar-day / sunrise / midnight
# boundary differs from the configured deadline. Run before any release.

set -euo pipefail
source "$(dirname "$0")/lib.sh"

live_init
live_begin "test_deadline_reset"

# ──────────────────────────────────────────────────────────────────────
# 1. Snapshot baseline
# ──────────────────────────────────────────────────────────────────────

EV_DAILY="sensor.sem_daily_ev_energy"
PER_CHARGER="sensor.sem_charger_ev_charger_daily_energy"
TARGET_TIME="time.sem_charger_ev_charger_target_time"

baseline_global=$(get_state "$EV_DAILY")
baseline_charger=$(get_state "$PER_CHARGER")
baseline_target=$(get_state "$TARGET_TIME")

_log "baseline global=$baseline_global  per-charger=$baseline_charger  target=$baseline_target"

# We need a substantial non-zero baseline. Otherwise we can't tell a
# reset from natural sub-kWh drift from ongoing simulated EV draw, and
# the test flakes mid-day on HA-TEST. Skip cleanly if baseline is too small.
is_meaningful=$(python3 -c "
try:
    v = float('$baseline_global'); print(1 if v >= 1.0 else 0)
except Exception:
    print(0)
")
if [[ "$is_meaningful" != "1" ]]; then
    _log "SKIP: daily_ev_energy is ${baseline_global} kWh (< 1.0) — too small to"
    _log "      distinguish a real reset from cycle-by-cycle drift. Re-run"
    _log "      after an overnight charge has accumulated some energy."
    exit 0
fi

assert_numeric_gt "$baseline_global" "0" "baseline daily_ev_energy"

# ──────────────────────────────────────────────────────────────────────
# 2. Set target_time to a value 2 minutes from HA's local clock
# ──────────────────────────────────────────────────────────────────────

new_tt=$(ha_local_time_plus 2 ha-test)
_log "new target_time will be $new_tt (HA-TEST local clock + 2 min)"

set_state_time "$TARGET_TIME" "${new_tt}:00"

# Give the coordinator one cycle to pick up the change. The boundary
# isn't crossed yet, so the counter must still hold the baseline.
sleep 8
after_set=$(get_state "$EV_DAILY")
assert_equals "$after_set" "$baseline_global" "counter immediately after target_time change (boundary not yet crossed)"

# ──────────────────────────────────────────────────────────────────────
# 3. Poll across the boundary. Expect HOLD → RESET in one cycle.
# ──────────────────────────────────────────────────────────────────────

_log "polling across the $new_tt boundary…"

held=0
crossed=0
elapsed=0
max_seconds=180

while (( elapsed < max_seconds )); do
    t=$(ha_local_time)
    v_global=$(get_state "$EV_DAILY")
    v_charger=$(get_state "$PER_CHARGER")
    echo "    t=$t  global=$v_global  per-charger=$v_charger"

    if [[ "$v_global" == "$baseline_global" ]]; then
        # Still pre-boundary
        held=$((held + 1))
    else
        # The counter moved. A successful reset drops the value to (near) zero;
        # exact 0.0 is rare on a live system because EV draw between the reset
        # and the next read leaves a small residue. Accept anything ≤ baseline/10
        # (a true "reset" event) and reject larger deltas (a partial overwrite
        # would be a real bug).
        is_reset=$(python3 -c "
try:
    v = float('$v_global'); b = float('$baseline_global')
    print(1 if (v <= b / 10.0 or v <= 0.5) else 0)
except Exception:
    print(0)
")
        if [[ "$is_reset" == "1" ]]; then
            crossed=1
            break
        fi
        echo "✗ FAIL: counter changed to unexpected value '$v_global' (baseline was '$baseline_global')" >&2
        # Best-effort restore before bailing
        set_state_time "$TARGET_TIME" "$baseline_target" || true
        exit 1
    fi

    sleep 15
    elapsed=$((elapsed + 15))
done

if (( crossed == 0 )); then
    _log "✗ FAIL: counter did not reset within ${max_seconds}s after new target_time"
    set_state_time "$TARGET_TIME" "$baseline_target" || true
    exit 1
fi

assert_numeric_gt "$held" "0" "number of HOLD samples before the boundary"

# ──────────────────────────────────────────────────────────────────────
# 4. Verify the per-charger sensor reset in lockstep
# ──────────────────────────────────────────────────────────────────────

after_pc=$(get_state "$PER_CHARGER")
assert_equals "$after_pc" "$v_global" "per-charger counter mirrors global"

# ──────────────────────────────────────────────────────────────────────
# 5. Restore target_time to baseline
# ──────────────────────────────────────────────────────────────────────

restore_state_time "$TARGET_TIME" "$baseline_target"
_log "target_time restored to $baseline_target"

live_end
