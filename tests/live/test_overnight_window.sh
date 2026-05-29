#!/usr/bin/env bash
# tests/live/test_overnight_window.sh — verify the night charging window
# end boundary moves correctly when night_latest_end is changed at
# runtime. Mirrors the deadline-reset test but for the night-window-end
# boundary instead of the per-charger Charge-by deadline.
#
# Why this matters: night_latest_end (default 7.0 = 07:00 local) is the
# UPPER cap on when the night window closes. The sensor.sem_night_end_time
# is derived from min(sunrise, night_latest_end). A bug in the derivation
# would either delay or clip the window incorrectly.
#
# Test shape:
#   1. Snapshot night_latest_end + the derived night_end_time sensor.
#   2. Set night_latest_end to (current_local_hour + 0.1) — about 6 min
#      ahead. Choosing a small bump keeps the test quick.
#   3. Wait for one coordinator cycle (~10s) to let the derivation refresh.
#   4. Verify night_end_time shifted to roughly the new value.
#   5. Restore the baseline.

set -euo pipefail
source "$(dirname "$0")/lib.sh"

live_init
live_begin "test_overnight_window"

NIGHT_LATEST_END="number.sem_night_latest_end"
NIGHT_END_TIME_SENSOR="sensor.sem_night_end_time"

# ──────────────────────────────────────────────────────────────────────
# 1. Snapshot
# ──────────────────────────────────────────────────────────────────────

baseline_latest_end=$(get_state "$NIGHT_LATEST_END")
baseline_end_time=$(get_state "$NIGHT_END_TIME_SENSOR")
_log "baseline latest_end=$baseline_latest_end  derived end_time=$baseline_end_time"

# Sanity: a real number, not 'unknown' / 'unavailable'.
case "$baseline_latest_end" in
    ''|unknown|unavailable|?)
        echo "✗ FAIL: $NIGHT_LATEST_END is '$baseline_latest_end' — can't test" >&2
        exit 1
        ;;
esac

# ──────────────────────────────────────────────────────────────────────
# 2. Pick a bump value that we KNOW will be the binding constraint.
#    The derived sensor is min(sunrise, latest_end); only when latest_end
#    is BELOW sunrise does it actually drive the result. The entity has
#    range [5.0, 9.0] so we use 5.0 — works as long as sunrise > 05:00,
#    which it is for all of Europe May-Sept (after which a different
#    season-dependent test value would need picking; document the date).
# ──────────────────────────────────────────────────────────────────────

bump=5.0
expected_end_time="05:00"
_log "bumping night_latest_end → $bump (entity min, before sunrise so it becomes the binding cap)"

# Verify our assumption: sunrise > 05:00. Read the derived end_time from
# baseline — if it's already 05:00, latest_end is already binding at min
# and we can't test the cap change here.
if [[ "$baseline_end_time" == "$expected_end_time" || "$bump" == "$baseline_latest_end" ]]; then
    _log "SKIP: baseline already at the cap value — pick a different test approach"
    exit 0
fi
# Also verify sunrise is actually after 05:00 — otherwise our cap won't bind.
case "$baseline_end_time" in
    "0"[0-4]:*)
        _log "SKIP: HA-TEST sunrise is before 05:00 today ($baseline_end_time) — cap=5.0 wouldn't bind."
        _log "      Use a winter test approach when running before Mar 21 / after Sep 21."
        exit 0
        ;;
esac

# ──────────────────────────────────────────────────────────────────────
# 3. Set the new value via number.set_value service.
# ──────────────────────────────────────────────────────────────────────

_assert_not_prod
call_service number set_value \
    "{\"entity_id\":\"$NIGHT_LATEST_END\",\"value\":$bump}"

# Give the coordinator a couple of cycles to pick it up. The night_end_time
# sensor is derived per-cycle.
sleep 15

after_latest_end=$(get_state "$NIGHT_LATEST_END")
after_end_time=$(get_state "$NIGHT_END_TIME_SENSOR")
_log "after bump: latest_end=$after_latest_end  derived end_time=$after_end_time"

# Verify the number entity itself accepted the change.
case "$after_latest_end" in
    "$bump"|"${bump}.0")
        _log "✓ night_latest_end accepted the new value"
        ;;
    *)
        echo "✗ FAIL: $NIGHT_LATEST_END did not move (got '$after_latest_end', expected '$bump')" >&2
        call_service number set_value \
            "{\"entity_id\":\"$NIGHT_LATEST_END\",\"value\":$baseline_latest_end}" || true
        exit 1
        ;;
esac

# Verify the derived sensor reflects the new latest_end. With bump=3.0
# (well below any sunrise), min(sunrise, 3.0) = 3.0, so the sensor must
# read "03:00".
if [[ "$after_end_time" != "$expected_end_time" ]]; then
    echo "✗ FAIL: derived $NIGHT_END_TIME_SENSOR did not follow" >&2
    echo "        expected '$expected_end_time' (=bump), got '$after_end_time'" >&2
    echo "        Baseline was '$baseline_end_time' (the sunrise constraint)." >&2
    call_service number set_value \
        "{\"entity_id\":\"$NIGHT_LATEST_END\",\"value\":$baseline_latest_end}" || true
    exit 1
fi
_log "✓ derived night_end_time followed the cap: $baseline_end_time → $after_end_time"

# ──────────────────────────────────────────────────────────────────────
# 4. Restore baseline.
# ──────────────────────────────────────────────────────────────────────

call_service number set_value \
    "{\"entity_id\":\"$NIGHT_LATEST_END\",\"value\":$baseline_latest_end}"
sleep 8

restored=$(get_state "$NIGHT_LATEST_END")
_log "restored: $NIGHT_LATEST_END = $restored"

live_end
