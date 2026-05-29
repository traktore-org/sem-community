#!/usr/bin/env bash
# tests/live/test_charging_state_consistency.sh — verify the SEM display
# sensors agree with the actuator. If SEM is commanding 0 amps AND the
# car is drawing ~no power, the display MUST NOT say "Charging active".
#
# Why this matters (PROD 2026-05-29):
#   sensor.sem_calculated_current = 0
#   sensor.sem_ev_power           = 120 W (KEBA standby, not real charging)
#   binary_sensor.keba_p30_charging_state = off
#   sensor.sem_charging_state     = "Solar mode - Charging active"  ← wrong
#
# The user, looking at the dashboard, asked "why is HA-PROD charging?"
# The car wasn't — the display label was lying. A passive invariant
# test catches this without needing to drive any state: at any moment,
# command zero + draw zero must read as "idle", never "Charging active".
#
# This is a one-shot invariant — no mutations, no cleanup required.

set -euo pipefail
source "$(dirname "$0")/lib.sh"

live_init
live_begin "test_charging_state_consistency"

CALC_CURRENT="sensor.sem_calculated_current"
EV_POWER="sensor.sem_ev_power"
CHARGING_STATE="sensor.sem_charging_state"

# Idle threshold: anything below ~500 W is below the 6 A * 3-phase * 230 V
# minimum (~4140 W) for any real charging session. Even a 1-phase 6 A
# session would be ~1380 W, so 500 W is comfortably "definitely not
# charging" while leaving headroom for KEBA standby + measurement noise.
IDLE_THRESHOLD_W=500

current=$(get_state "$CALC_CURRENT")
ev_w=$(get_state "$EV_POWER")
state_label=$(get_state "$CHARGING_STATE")
_log "calculated_current=$current A  ev_power=$ev_w W  state='$state_label'"

# Sanity guard: bail if anything is unavailable (we can't make a claim
# about consistency if we can't read the inputs). Use string-equality so
# the '?' fallback from get_state isn't interpreted as a glob.
for v in "$current" "$ev_w" "$state_label"; do
    if [[ -z "$v" || "$v" == "unknown" || "$v" == "unavailable" || "$v" == "?" ]]; then
        _log "SKIP: one of the inputs is '$v' — can't evaluate the invariant"
        exit 0
    fi
done

# Only assert when we're actually in the "command 0 + drawing nothing"
# regime. If SEM is commanding > 0 A or the car is drawing real power,
# "Charging active" might be correct — this test isn't the place to
# adjudicate that.
is_idle=$(python3 -c "
try:
    c = float('$current'); w = float('$ev_w')
    print(1 if (c == 0 and w < $IDLE_THRESHOLD_W) else 0)
except Exception:
    print(0)
")

if [[ "$is_idle" != "1" ]]; then
    _log "SKIP: not in the idle regime (command=$current A, draw=$ev_w W)"
    _log "      Need calculated_current=0 AND ev_power<${IDLE_THRESHOLD_W}W to check the invariant"
    exit 0
fi

# THE INVARIANT: idle on the actuator side → label must not claim charging.
case "$state_label" in
    *"Charging active"*|*"charging active"*)
        echo "✗ FAIL: charging_state lies about reality" >&2
        echo "        calculated_current=0 A, ev_power=$ev_w W (below ${IDLE_THRESHOLD_W} W floor)" >&2
        echo "        → SEM is commanding 0 A and the car is drawing nothing." >&2
        echo "        But sensor.sem_charging_state says '$state_label'" >&2
        echo "        Expected: an idle-class label (e.g. 'Solar mode - Idle')" >&2
        echo "" >&2
        echo "        Source-of-truth sensors (the dashboard ignores these):" >&2
        echo "          sensor.sem_calculated_current = $current" >&2
        echo "          sensor.sem_ev_power           = $ev_w" >&2
        echo "" >&2
        echo "        The user-facing label is what people read on the dashboard." >&2
        echo "        It must match the actuator state, not lag it." >&2
        exit 1
        ;;
esac

_log "✓ display matches actuator: idle and labeled as such ('$state_label')"
live_end
