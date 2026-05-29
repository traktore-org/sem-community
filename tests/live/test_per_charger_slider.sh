#!/usr/bin/env bash
# tests/live/test_per_charger_slider.sh — verify that changing a
# per-charger Number entity propagates to the per-charger sensors.
#
# Why this matters: the per-charger entities (`number.sem_charger_<id>_*`)
# are backed by entries inside ``config["ev_chargers"][i]`` rather than
# top-level config keys. They use a different write path
# (SEMPerChargerNumberEntity.async_set_native_value, number.py:712)
# from the global Number entities, which itself does:
#
#     ev_chargers = [dict(c) for c in new_options.get("ev_chargers", [])]
#     for charger in ev_chargers:
#         if charger.get("id") == self._charger_id:
#             charger[self._config_key] = value
#     ...
#     self.coordinator.config.update({**self._entry.data, **new_options})
#
# That ``config.update({...})`` REPLACES ``ev_chargers`` with a fresh
# list of fresh dicts. Anything holding a reference to the OLD
# per-charger dict (multi-charger state, ev_control caches, EvTaperDetector)
# silently sees the OLD target. This mirrors the bug class fixed in
# `async_update_config` (bea4ecc) for global config — but for per-charger
# state. If any future component captures a per-charger dict reference
# at init, this invariant flushes it out.
#
# Test shape:
#   1. Snapshot the per-charger daily target + the downstream
#      `daily_ev_target` mirror sensor that other paths read.
#   2. Bump the target.
#   3. Confirm BOTH update on the next coordinator cycle.
#   4. Restore baseline.

set -euo pipefail
source "$(dirname "$0")/lib.sh"

live_init
live_begin "test_per_charger_slider"

CID="ev_charger"  # the default single-charger id on HA-TEST
TARGET_NUM="number.sem_charger_${CID}_daily_ev_target"

baseline_target=$(get_state "$TARGET_NUM")
_log "baseline per-charger=${baseline_target}"

# Sanity guard.
if [[ -z "$baseline_target" || "$baseline_target" == "unknown" \
      || "$baseline_target" == "unavailable" || "$baseline_target" == "?" ]]; then
    _log "SKIP: $TARGET_NUM is '$baseline_target' — can't test"
    exit 0
fi

# Pick a bump that is clearly different. The number entity is bounded;
# pick +0.5 unless we're already near max, otherwise -0.5.
bump=$(python3 -c "
b = float('$baseline_target')
b_int = round(b * 2) / 2  # snap to 0.5 step
if b_int >= 95:
    print(b_int - 0.5)
else:
    print(b_int + 0.5)
")
_log "bumping per-charger target → $bump"

_assert_not_prod
call_service number set_value \
    "{\"entity_id\":\"$TARGET_NUM\",\"value\":$bump}"
sleep 14  # one coordinator cycle + persistence flush

after_target=$(get_state "$TARGET_NUM")
_log "after bump: per-charger=$after_target"

# The per-charger Number itself MUST move — proves the write reached the entity.
case "$after_target" in
    "$bump"|"${bump}.0")
        _log "✓ per-charger Number accepted the new value"
        ;;
    *)
        echo "✗ FAIL: per-charger $TARGET_NUM did not update" >&2
        echo "        expected '$bump', got '$after_target'" >&2
        call_service number set_value \
            "{\"entity_id\":\"$TARGET_NUM\",\"value\":$baseline_target}" || true
        exit 1
        ;;
esac

# Verify the integration didn't crash on the change — `ev_chargers`
# replacement via `config.update({...})` is a common stumble point for
# components that captured a charger-dict reference at init. A traceback
# in the recent log means something didn't survive the swap.
log_errors=$(ssh ha-test "ha core logs 2>/dev/null | tail -200 | grep -E 'ERROR.*solar_energy_management|solar_energy_management.*ERROR|solar_energy_management.*Traceback' | head -5" 2>/dev/null || echo "")
if [[ -n "$log_errors" ]]; then
    echo "✗ FAIL: integration logged errors after per-charger slider change" >&2
    echo "$log_errors" >&2
    call_service number set_value \
        "{\"entity_id\":\"$TARGET_NUM\",\"value\":$baseline_target}" || true
    exit 1
fi
_log "✓ no integration errors logged after the change"

# Restore baseline
call_service number set_value \
    "{\"entity_id\":\"$TARGET_NUM\",\"value\":$baseline_target}"
sleep 8
restored=$(get_state "$TARGET_NUM")
_log "restored: $TARGET_NUM = $restored"

live_end
