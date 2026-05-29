#!/usr/bin/env bash
# tests/live/test_surplus_charging.sh — verify ev_charging_mode changes
# propagate end-to-end: select widget → coordinator config → strategy
# decision → charging_state. This catches the bug class where the select
# silently doesn't accept user input (#282: SEMPerChargerSelect was
# hardcoded to target_type behaviour and the dropdown looked fine but the
# state never moved) AND the bug class where the strategy doesn't
# react to a mode change (e.g. cached config not invalidated).
#
# Test shape:
#   1. Snapshot baseline mode + strategy.
#   2. Set mode to "off" → strategy should become idle-like.
#   3. Set mode to "now" → strategy should become "now".
#   4. Set mode back to "auto" → strategy should return to solar_only.
#   5. Restore.

set -euo pipefail
source "$(dirname "$0")/lib.sh"

live_init
live_begin "test_surplus_charging"

MODE_SELECT="select.sem_charger_ev_charger_ev_charging_mode"
STRATEGY="sensor.sem_charging_strategy"
DAILY_TARGET="number.sem_charger_ev_charger_daily_ev_target"
DAILY_EV="sensor.sem_daily_ev_energy"

# ──────────────────────────────────────────────────────────────────────
# 1. Snapshot baseline + sanity-check the select options.
#    Bump the daily EV target above the current daily so target is UNMET —
#    Auto mode returns "idle" when target is met (correct, but breaks the
#    surplus-class check at step 4). With target unmet, Auto falls into
#    a zone-based surplus strategy.
# ──────────────────────────────────────────────────────────────────────

baseline_mode=$(get_state "$MODE_SELECT")
baseline_strategy=$(get_state "$STRATEGY")
baseline_target=$(get_state "$DAILY_TARGET")
daily=$(get_state "$DAILY_EV")
_log "baseline mode=$baseline_mode  strategy=$baseline_strategy  target=$baseline_target  daily=$daily"

# Precondition: EV must be connected. Otherwise _determine_charging_strategy
# short-circuits to ("idle", "ev disconnected") regardless of mode and the
# strategy assertions below would all read "idle". HA-TEST's simulator can
# drop the connection across restarts — skip cleanly when that happens.
ev_connected=$(get_state "binary_sensor.sem_ev_connected")
if [[ "$ev_connected" != "on" ]]; then
    _log "SKIP: binary_sensor.sem_ev_connected is '$ev_connected' — strategy"
    _log "      decisions only fire with EV connected. Plug the simulated EV"
    _log "      back in (or wait for the simulator to recover) and re-run."
    exit 0
fi

# Bump target to current daily + 5 kWh so it's clearly unmet.
new_target=$(python3 -c "print(round(float('$daily') + 5.0, 1))" 2>/dev/null || echo "20")
call_service number set_value \
    "{\"entity_id\":\"$DAILY_TARGET\",\"value\":$new_target}"
sleep 4
_log "bumped daily target → $new_target (was $baseline_target) to ensure target is unmet"

# Select options must include the full mode set — locks in the #282 select
# generalisation fix (the bug was: options returned ['kwh'] instead).
options=$(get_attr "$MODE_SELECT" options)
_log "select options: $options"
for required in auto minpv now off; do
    if [[ "$options" != *"$required"* ]]; then
        echo "✗ FAIL: $MODE_SELECT options missing '$required' (got: $options)" >&2
        echo "        This is the #282 SEMPerChargerSelect hardcoded-to-target_type bug" >&2
        exit 1
    fi
done
_log "✓ all four charging modes present in select options"

# ──────────────────────────────────────────────────────────────────────
# 2. Set mode → "off" and verify strategy follows.
#    'off' should produce an idle-class strategy (idle / Solar disabled).
# ──────────────────────────────────────────────────────────────────────

_assert_not_prod
call_service select select_option \
    "{\"entity_id\":\"$MODE_SELECT\",\"option\":\"off\"}"
sleep 12  # let the coordinator pick up the new config

after_off_mode=$(get_state "$MODE_SELECT")
after_off_strategy=$(get_state "$STRATEGY")
_log "after mode=off: mode=$after_off_mode  strategy=$after_off_strategy"

assert_equals "$after_off_mode" "off" "mode propagation to select state"

# Strategy should NOT remain solar_only when EV charging is disabled. We
# don't pin the exact string (coordinator may report different idle
# variants) but it must not be the surplus-charging string.
if [[ "$after_off_strategy" == "solar_only" || "$after_off_strategy" == "battery_assist" ]]; then
    echo "✗ FAIL: strategy stuck on '$after_off_strategy' after mode=off" >&2
    echo "        Mode change isn't invalidating the strategy decision." >&2
    call_service select select_option \
        "{\"entity_id\":\"$MODE_SELECT\",\"option\":\"$baseline_mode\"}" || true
    exit 1
fi
_log "✓ strategy moved off the surplus path when mode=off"

# ──────────────────────────────────────────────────────────────────────
# 3. Set mode → "now" and verify strategy becomes "now".
# ──────────────────────────────────────────────────────────────────────

call_service select select_option \
    "{\"entity_id\":\"$MODE_SELECT\",\"option\":\"now\"}"
sleep 12

after_now_mode=$(get_state "$MODE_SELECT")
after_now_strategy=$(get_state "$STRATEGY")
_log "after mode=now: mode=$after_now_mode  strategy=$after_now_strategy"

assert_equals "$after_now_mode" "now" "mode=now propagation"
assert_equals "$after_now_strategy" "now" "strategy=now after mode=now"

# ──────────────────────────────────────────────────────────────────────
# 4. Set mode → "auto" and verify the original surplus path returns.
#    We expect strategy to settle back to solar_only (the path the
#    fresh-restart HA-TEST naturally lands on with SOC > buffer).
# ──────────────────────────────────────────────────────────────────────

call_service select select_option \
    "{\"entity_id\":\"$MODE_SELECT\",\"option\":\"auto\"}"
sleep 12

after_auto_mode=$(get_state "$MODE_SELECT")
after_auto_strategy=$(get_state "$STRATEGY")
_log "after mode=auto: mode=$after_auto_mode  strategy=$after_auto_strategy"

assert_equals "$after_auto_mode" "auto" "mode=auto propagation"

# Auto should return to one of the surplus-class strategies — solar_only
# (Zone 2/3 with surplus), battery_assist (Zone 3/4 wanting battery), or
# similar. Anything non-surplus here means the auto path is broken.
case "$after_auto_strategy" in
    solar_only|battery_assist|self_consumption|min_pv)
        _log "✓ auto returned to a surplus-class strategy: $after_auto_strategy"
        ;;
    *)
        echo "✗ FAIL: auto did not return to a surplus strategy (got '$after_auto_strategy')" >&2
        call_service select select_option \
            "{\"entity_id\":\"$MODE_SELECT\",\"option\":\"$baseline_mode\"}" || true
        exit 1
        ;;
esac

# ──────────────────────────────────────────────────────────────────────
# 5. Restore baseline mode + daily target.
# ──────────────────────────────────────────────────────────────────────

if [[ "$baseline_mode" != "$after_auto_mode" ]]; then
    call_service select select_option \
        "{\"entity_id\":\"$MODE_SELECT\",\"option\":\"$baseline_mode\"}"
    sleep 4
    _log "mode restored to $baseline_mode"
fi

call_service number set_value \
    "{\"entity_id\":\"$DAILY_TARGET\",\"value\":$baseline_target}"
sleep 4
_log "daily target restored to $baseline_target"

live_end
