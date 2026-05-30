#!/usr/bin/env bash
# tests/live/test_ev_connected_physics.sh — physics-based connection
# invariant.
#
# Reported on PROD 2026-05-29: the KEBA plug binary_sensor reported
# "off" while the contactor was closed and the car was drawing 8 kW.
# SEM correctly trusted the lying sensor → strategy "idle — ev
# disconnected" → no control commanded → 67 minutes of unsupervised
# charging through five separate sessions, 6 kWh overshoot past the
# Max ceiling. Root cause: an upstream charger-integration quirk
# during HA restart with a connected car.
#
# Fix: SensorReader now treats ``ev_charging=True`` OR
# ``ev_power>100W`` as physics-proof of connection, regardless of
# what the plug sensor says. This sentinel locks the invariant live.
#
# Assertion: at any moment, if ``sensor.sem_ev_power > 100 W`` then
# ``binary_sensor.sem_ev_connected`` MUST read "on". A current can't
# flow without a connection — if it does the integration has lost
# track and a regression has reopened the 2026-05-29 PROD class.

set -euo pipefail
source "$(dirname "$0")/lib.sh"

live_init
live_begin "test_ev_connected_physics"

EV_POWER="sensor.sem_ev_power"
EV_CONNECTED="binary_sensor.sem_ev_connected"

ev_power=$(get_state "$EV_POWER")
ev_connected=$(get_state "$EV_CONNECTED")
_log "ev_power=${ev_power} W  ev_connected=${ev_connected}"

# Guard: skip if either sensor is unavailable.
for v in "$ev_power" "$ev_connected"; do
    if [[ -z "$v" || "$v" == "unknown" || "$v" == "unavailable" || "$v" == "?" ]]; then
        _log "SKIP: one of the inputs is '$v' — can't evaluate the invariant"
        exit 0
    fi
done

# Numeric parse the EV power.
ev_w=$(printf '%.0f' "$ev_power" 2>/dev/null || echo 0)

# The invariant only fires when there's real charging current.
# Under the 100 W floor we're seeing KEBA standby / contactor noise,
# not actual charging — so we don't ask about the plug.
if (( ev_w < 100 )); then
    _log "(ev_power=${ev_w} W < 100 W — physics defence doesn't apply)"
    live_end
    exit 0
fi

# The actual invariant: current is flowing, so the plug MUST report on.
if [[ "$ev_connected" != "on" ]]; then
    echo "✗ FAIL: $EV_POWER reports ${ev_w} W but $EV_CONNECTED reports '$ev_connected'" >&2
    echo "        Current cannot flow without a connection — this is exactly the" >&2
    echo "        2026-05-29 PROD regime (KEBA plug sensor lying across restart)." >&2
    echo "        SEM has lost track of the EV; the physics-defence in SensorReader" >&2
    echo "        is not catching it. Investigate sensor_reader._read_binary_sensor" >&2
    echo "        and the override block." >&2
    exit 1
fi

_log "✓ physics holds: ${ev_w} W flowing and plug reports connected"
live_end
