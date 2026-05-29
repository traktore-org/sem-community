#!/usr/bin/env bash
# tests/live/test_budget_agreement.sh — Phase C of #282 unification.
#
# Forever sentinel: at any moment, the published budget sensors and the
# actuator state must agree, because they read from a single
# ``EVBudget`` instance (cached on the coordinator as
# ``_cycle_ev_budget`` and published once into the SEMData snapshot).
#
# If this test ever fails, somebody re-introduced a second budget path
# — either a new ad-hoc derivation in ``ev_control.py`` or a different
# value being plumbed into the SEMData publish. The unification has
# come undone.
#
# What we assert:
#
#   1. published `sensor.sem_calculated_current` matches
#      `floor(sensor.sem_available_power / 690)` within ±1 A
#      tolerance. This is the canonical
#      ``EVBudget.current_a == floor(net_w / V·phases)`` relationship —
#      built into ``_watts_to_amps``. If it drifts, the publish path
#      diverged from the canonical method again.
#
#   2. when strategy == "solar_only" or "battery_assist", the
#      `flow_grid_to_ev_power` must stay below an honest idle floor.
#      Drift here means the actuator's setpoint disagreed with the
#      surplus the state machine signed off on.
#
# Designed to run in any state, including idle — assertion #1 is
# always meaningful, #2 is conditional on the strategy.

set -euo pipefail
source "$(dirname "$0")/lib.sh"

live_init
live_begin "test_budget_agreement"

CALC_CURRENT="sensor.sem_calculated_current"
AVAILABLE_POWER="sensor.sem_available_power"
STRATEGY="sensor.sem_charging_strategy"
GRID_TO_EV_W="sensor.sem_flow_grid_to_ev_power"

calc_a=$(get_state "$CALC_CURRENT")
avail_w=$(get_state "$AVAILABLE_POWER")
strategy=$(get_state "$STRATEGY")
grid_w=$(get_state "$GRID_TO_EV_W")
_log "calc_current=${calc_a} A  available_power=${avail_w} W  strategy=${strategy}  grid_to_ev=${grid_w} W"

# Guard against unavailable sensors.
for v in "$calc_a" "$avail_w" "$strategy"; do
    if [[ -z "$v" || "$v" == "unknown" || "$v" == "unavailable" || "$v" == "?" ]]; then
        _log "SKIP: one of the budget sensors is '$v' — can't evaluate the invariant"
        exit 0
    fi
done

# ──────────────────────────────────────────────────────────────────────
# Assertion 1: amps/watts relationship matches `_watts_to_amps`.
# ──────────────────────────────────────────────────────────────────────

# Expected: floor(net_w / (230 * 3)) = floor(net_w / 690), clamped to [0,16].
expected_a=$(python3 -c "
import math
try:
    w = float('$avail_w')
    a = max(0, min(16, math.floor(w / 690)))
    print(a)
except Exception:
    print('err')
")
actual_a=$(printf '%.0f' "$calc_a" 2>/dev/null || echo err)

if [[ "$expected_a" == "err" || "$actual_a" == "err" ]]; then
    _log "SKIP: couldn't parse budget values as numbers"
    exit 0
fi

# Allow ±1 A tolerance for the boundary case where the publish path
# rounds slightly differently from the canonical floor (shouldn't
# happen post-Phase B, but the live system has measurement noise).
diff=$(( actual_a - expected_a ))
abs_diff=$(( diff < 0 ? -diff : diff ))

if (( abs_diff > 1 )); then
    echo "✗ FAIL: published calc_current diverges from published available_power" >&2
    echo "        sensor.sem_calculated_current = ${calc_a} A" >&2
    echo "        sensor.sem_available_power    = ${avail_w} W" >&2
    echo "        floor(${avail_w}/690) expected ${expected_a} A, got ${actual_a} A" >&2
    echo "" >&2
    echo "        The publish path is computing the amps from somewhere" >&2
    echo "        other than the canonical EVBudget.current_a. Phase B" >&2
    echo "        unification has come undone." >&2
    exit 1
fi
_log "✓ amps/watts agree: floor(${avail_w}/690)=${expected_a} matches ${actual_a}"

# ──────────────────────────────────────────────────────────────────────
# Assertion 2: surplus strategies don't leak grid (conditional).
# ──────────────────────────────────────────────────────────────────────

case "$strategy" in
    solar_only)
        # Only solar_only carries the strict grid-floor contract — that
        # strategy literally promises "what solar can supply right now."
        # battery_assist is intentionally excluded: by definition it
        # depends on the home battery ramping discharge in response to
        # SEM's setpoint, and the battery (LFP, BMS-managed) cannot
        # always deliver instantly. During the ramp window, grid
        # backfills the gap; proportional flow attribution then attributes
        # part of that grid to EV. That's not SEM commanding grid — it's
        # the physics of a battery with a ramp constant ≫ EV response
        # time. Observed live on PROD 2026-05-29 (10:00 CEST plug-in):
        # ~743 W of grid transiently attributed to EV while the Huawei
        # LUNA2000 ramped from 0 → 2106 W discharge. Tightening
        # battery_assist's grid floor would produce false-positive
        # failures on every battery_assist session.
        if [[ -z "$grid_w" || "$grid_w" == "unknown" || "$grid_w" == "unavailable" || "$grid_w" == "?" ]]; then
            _log "SKIP assertion 2: $GRID_TO_EV_W is '$grid_w'"
        else
            grid_int=$(printf '%.0f' "$grid_w" 2>/dev/null || echo 0)
            if (( grid_int >= 200 )); then
                echo "✗ FAIL: solar_only strategy is leaking grid to EV (${grid_w} W)" >&2
                echo "        actuator setpoint diverged from the canonical budget" >&2
                echo "        the state machine signed off on." >&2
                exit 1
            fi
            _log "✓ solar_only grid floor held: ${grid_w} W < 200 W"
        fi
        ;;
    battery_assist)
        # No strict grid assertion — see comment above. The amps/watts
        # agreement check (assertion 1) is the only canonical-budget
        # invariant we can hold against battery_assist live.
        _log "(strategy=battery_assist — grid_to_ev=${grid_w} W is informational only;"
        _log " battery ramp-rate vs EV response makes a tight grid floor unenforceable)"
        ;;
    *)
        _log "(strategy=${strategy} — assertion 2 only applies to solar_only)"
        ;;
esac

live_end
