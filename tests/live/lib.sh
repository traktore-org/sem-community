#!/usr/bin/env bash
# tests/live/lib.sh — helpers for live HA-TEST integration tests (#282).
#
# This is the "third layer" of the test pyramid: real Home Assistant
# instance + real coordinator + real sensors, driven by curl against the
# HA REST API. It catches the bug class that unit tests and the YAML
# scenario harness can't — time-boundary effects, entity reactivity,
# coordinator-to-sensor round-trips, persistence across restart.
#
# Convention: live tests target HA-TEST. HA-PROD is read-only — every
# mutating helper short-circuits with a hard error when the host looks
# like the prod box (10.10.20.150), unless TESTS_LIVE_ALLOW_PROD=1.
#
# Usage in a test script:
#
#     #!/usr/bin/env bash
#     set -euo pipefail
#     source "$(dirname "$0")/lib.sh"
#     live_init                                 # picks up HA_TEST_TOKEN + URL
#
#     baseline=$(get_state sensor.sem_X)
#     set_state_time time.sem_Y "06:40:00"
#     poll_until_value sensor.sem_X "0.0" 180   # max 3 min
#     assert_equals "$(get_state sensor.sem_X)" "0.0"
#     restore_state_time time.sem_Y "07:00:00"  # clean up

set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────
# Config — token + URL come from ~/.config/sem/tokens.env
# Use HA-TEST as the default host (10.10.20.46).
# Tests assert HOST != PROD before any mutation.
# ──────────────────────────────────────────────────────────────────────────

LIVE_HOST="${LIVE_HOST:-10.10.20.46}"
LIVE_PORT="${LIVE_PORT:-8123}"
LIVE_TOKEN_FILE="${LIVE_TOKEN_FILE:-$HOME/.config/sem/tokens.env}"
LIVE_TOKEN_VAR="${LIVE_TOKEN_VAR:-HA_TEST_TOKEN}"
LIVE_PROD_HOST="10.10.20.150"

# Internal state populated by live_init.
LIVE_URL=""
LIVE_TOKEN=""

# ──────────────────────────────────────────────────────────────────────────
# live_init — load token + verify HA is up. MUST be called first.
# ──────────────────────────────────────────────────────────────────────────

live_init() {
    if [[ ! -f "$LIVE_TOKEN_FILE" ]]; then
        echo "ERROR: token file $LIVE_TOKEN_FILE not found" >&2
        return 1
    fi
    # shellcheck disable=SC1090
    source "$LIVE_TOKEN_FILE"
    LIVE_TOKEN="${!LIVE_TOKEN_VAR:-}"
    if [[ -z "$LIVE_TOKEN" ]]; then
        echo "ERROR: $LIVE_TOKEN_VAR not set in $LIVE_TOKEN_FILE" >&2
        return 1
    fi
    LIVE_URL="http://${LIVE_HOST}:${LIVE_PORT}"

    # Sanity-check HA is responding
    local v
    v=$(curl -sk -H "Authorization: Bearer $LIVE_TOKEN" --max-time 5 \
        "$LIVE_URL/api/" 2>/dev/null || true)
    if [[ "$v" != *"API running"* ]]; then
        echo "ERROR: HA at $LIVE_URL not responding (got: $v)" >&2
        return 1
    fi
    _log "✓ live_init: $LIVE_URL responding"
}

# ──────────────────────────────────────────────────────────────────────────
# Safety: refuse mutations against PROD host unless explicitly allowed.
# ──────────────────────────────────────────────────────────────────────────

_assert_not_prod() {
    if [[ "$LIVE_HOST" == "$LIVE_PROD_HOST" && "${TESTS_LIVE_ALLOW_PROD:-0}" != "1" ]]; then
        echo "REFUSING to mutate state against PROD ($LIVE_HOST)." >&2
        echo "Set TESTS_LIVE_ALLOW_PROD=1 if you really mean it." >&2
        return 1
    fi
}

# ──────────────────────────────────────────────────────────────────────────
# get_state ENTITY_ID
#   echoes the state string, or '?' on error.
# ──────────────────────────────────────────────────────────────────────────

get_state() {
    local eid="$1"
    curl -sk -H "Authorization: Bearer $LIVE_TOKEN" --max-time 5 \
        "$LIVE_URL/api/states/$eid" 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin); print(d['state'])
except Exception:
    print('?')
" 2>/dev/null
}

# ──────────────────────────────────────────────────────────────────────────
# get_attr ENTITY_ID ATTR_NAME
#   echoes a named attribute, or '?' on error.
# ──────────────────────────────────────────────────────────────────────────

get_attr() {
    local eid="$1" attr="$2"
    curl -sk -H "Authorization: Bearer $LIVE_TOKEN" --max-time 5 \
        "$LIVE_URL/api/states/$eid" 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('attributes', {}).get('$attr', '?'))
except Exception:
    print('?')
" 2>/dev/null
}

# ──────────────────────────────────────────────────────────────────────────
# set_state_time ENTITY_ID HH:MM:SS
#   For time.* entities. Refuses if HOST == PROD without override.
# ──────────────────────────────────────────────────────────────────────────

set_state_time() {
    _assert_not_prod
    local eid="$1" t="$2"
    curl -sk -H "Authorization: Bearer $LIVE_TOKEN" -H "Content-Type: application/json" \
        --max-time 10 \
        -X POST "$LIVE_URL/api/services/time/set_value" \
        -d "{\"entity_id\":\"$eid\",\"time\":\"$t\"}" > /dev/null
    _log "set $eid → $t"
}

restore_state_time() {
    # Alias for readability; functionally identical to set_state_time.
    set_state_time "$@"
}

# ──────────────────────────────────────────────────────────────────────────
# call_service DOMAIN SERVICE JSON_DATA
#   Generic service call. Refuses if HOST == PROD without override.
# ──────────────────────────────────────────────────────────────────────────

call_service() {
    _assert_not_prod
    local domain="$1" service="$2" data="${3:-{}}"
    curl -sk -H "Authorization: Bearer $LIVE_TOKEN" -H "Content-Type: application/json" \
        --max-time 30 \
        -X POST "$LIVE_URL/api/services/$domain/$service" \
        -d "$data" > /dev/null
    _log "called $domain.$service"
}

# ──────────────────────────────────────────────────────────────────────────
# ha_local_time
#   echoes HH:MM:SS of the HA host's local clock (via ssh). Used to
#   compute "current + N minutes" inputs in a timezone-correct way.
#   Requires an ssh alias matching the host (ha-test, ha-prod).
# ──────────────────────────────────────────────────────────────────────────

ha_local_time() {
    local ssh_alias="${1:-ha-test}"
    ssh "$ssh_alias" "python3 -c \"from datetime import datetime; print(datetime.now().strftime('%H:%M:%S'))\"" 2>/dev/null
}

# Returns HH:MM N minutes from HA's local clock. e.g. ha_local_time_plus 2 ha-test → "06:40"
ha_local_time_plus() {
    local minutes="$1" ssh_alias="${2:-ha-test}"
    ssh "$ssh_alias" "python3 -c \"
from datetime import datetime, timedelta
t = datetime.now() + timedelta(minutes=$minutes)
print(t.strftime('%H:%M'))
\"" 2>/dev/null
}

# ──────────────────────────────────────────────────────────────────────────
# poll_until_value ENTITY_ID EXPECTED MAX_SECONDS [INTERVAL_SEC]
#   Polls ENTITY_ID until its state equals EXPECTED, or MAX_SECONDS pass.
#   Records the timeline of (timestamp, state) for the test report.
#   Returns 0 if the value was reached, 1 if timeout.
# ──────────────────────────────────────────────────────────────────────────

poll_until_value() {
    local eid="$1" expected="$2" max="$3" interval="${4:-10}"
    local elapsed=0
    while (( elapsed < max )); do
        local v
        v=$(get_state "$eid")
        local t
        t=$(ha_local_time)
        echo "    t=$t  $eid = $v"
        if [[ "$v" == "$expected" ]]; then
            return 0
        fi
        sleep "$interval"
        elapsed=$(( elapsed + interval ))
    done
    return 1
}

# ──────────────────────────────────────────────────────────────────────────
# Assertions — fail loudly with explanation, exit non-zero.
# ──────────────────────────────────────────────────────────────────────────

assert_equals() {
    local actual="$1" expected="$2" what="${3:-value}"
    if [[ "$actual" != "$expected" ]]; then
        echo "✗ FAIL: expected $what = '$expected', got '$actual'" >&2
        exit 1
    fi
    _log "✓ $what == '$expected'"
}

assert_numeric_gt() {
    local actual="$1" threshold="$2" what="${3:-value}"
    if ! python3 -c "exit(0 if float('$actual') > float('$threshold') else 1)" 2>/dev/null; then
        echo "✗ FAIL: expected $what > $threshold, got '$actual'" >&2
        exit 1
    fi
    _log "✓ $what ($actual) > $threshold"
}

# ──────────────────────────────────────────────────────────────────────────
# Pretty logging — prefix every line with the test name + a ✓ marker.
# ──────────────────────────────────────────────────────────────────────────

_log() {
    local prefix="${LIVE_TEST_NAME:-live}"
    echo "[$prefix] $*"
}

# Convenience: announce test start / end
live_begin() {
    LIVE_TEST_NAME="$1"
    echo
    echo "════════════════════════════════════════════════════════════════════"
    echo "▶  $1"
    echo "════════════════════════════════════════════════════════════════════"
}

live_end() {
    _log "✓ PASS"
    echo "════════════════════════════════════════════════════════════════════"
}
