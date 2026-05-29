#!/usr/bin/env bash
# tests/live/test_solar_only_no_grid.sh — invariant: whenever
# charging_strategy == "solar_only", the integrated grid → EV flow
# must stay near zero. Solar_only promises "the car charges only from
# what solar can supply right now"; any non-trivial flow_grid_to_ev_power
# while this strategy is active is a contract violation.
#
# Locks in the surplus-leak fix from commit 591956f (#282). Before
# that fix, calculate_ev_budget(solar_only=True) was inheriting the
# legacy base of `ev_power + grid_export` — so once the car had ramped,
# SEM never asked it to ramp DOWN when surplus dropped, silently letting
# grid backfill the gap. That regression should not come back.
#
# Test shape (passive invariant — no mutations):
#   1. Read sensor.sem_charging_strategy.
#   2. If not "solar_only", SKIP (we only have an opinion when this
#      strategy is active).
#   3. Read sensor.sem_flow_grid_to_ev_power.
#   4. Assert < 200 W. 200 W ≈ 1 A * 230 V — comfortably below the
#      minimum real charging draw, leaves headroom for noise.

set -euo pipefail
source "$(dirname "$0")/lib.sh"

live_init
live_begin "test_solar_only_no_grid"

STRATEGY="sensor.sem_charging_strategy"
GRID_TO_EV_W="sensor.sem_flow_grid_to_ev_power"
EV_POWER="sensor.sem_ev_power"

GRID_FLOOR_W=200  # see header comment

strategy=$(get_state "$STRATEGY")
grid_w=$(get_state "$GRID_TO_EV_W")
ev_w=$(get_state "$EV_POWER")
_log "strategy=$strategy  grid_to_ev=${grid_w}W  ev_power=${ev_w}W"

# Only assert when solar_only is actually the active strategy.
if [[ "$strategy" != "solar_only" ]]; then
    _log "SKIP: charging_strategy is '$strategy', not 'solar_only' — invariant doesn't apply"
    exit 0
fi

# Numeric guard: bail if we can't read the flow sensor.
if [[ -z "$grid_w" || "$grid_w" == "unknown" || "$grid_w" == "unavailable" || "$grid_w" == "?" ]]; then
    _log "SKIP: $GRID_TO_EV_W is '$grid_w' — can't evaluate"
    exit 0
fi

# Convert to int (drop decimals) and compare. Bash-only — no python dep.
grid_int=$(printf '%.0f' "$grid_w" 2>/dev/null || echo 0)
if (( grid_int >= GRID_FLOOR_W )); then
    echo "✗ FAIL: solar_only strategy is leaking grid power to EV" >&2
    echo "        $STRATEGY = '$strategy'" >&2
    echo "        $GRID_TO_EV_W = ${grid_w} W (threshold ${GRID_FLOOR_W} W)" >&2
    echo "        $EV_POWER     = ${ev_w} W" >&2
    echo "" >&2
    echo "        The solar_only contract: the EV must only charge from" >&2
    echo "        what solar can supply right now. Any non-trivial grid" >&2
    echo "        flow during this strategy means the surplus-leak fix" >&2
    echo "        (#282 / 591956f) has regressed." >&2
    exit 1
fi

_log "✓ solar_only is holding the grid floor: ${grid_w}W < ${GRID_FLOOR_W}W"
live_end
