#!/usr/bin/env bash
# tests/live/test_bundle_integrity.sh — verify the dashboard card
# bundle is present and not shadowed by a stale top-level vanilla file.
#
# Why this matters (#219 regression family): all cards now ship as a
# Lit bundle at `dashboard/card/dist/sem-cards.js`. The original
# top-level vanilla `sem-*-card.js` files were dead and removed in
# v1.5.11. A stray top-level `sem-cards.js` (from a botched manual
# deploy, an interrupted rsync, or a future code change) would shadow
# the dist bundle and silently break every dashboard card on every
# user's install — the failure mode reported in #219.
#
# This test runs over SSH on HA-TEST: HACS deploys the integration into
# /homeassistant/custom_components/solar_energy_management/ so the
# truth is there, not in the local repo.
#
# Test shape (passive — no mutations):
#   1. dist/sem-cards.js MUST exist and be non-empty.
#   2. No top-level dashboard/card/sem-cards.js (without dist/) — that
#      file path used to register first and shadow dist/.
#   3. dist/sem-cards.js must contain at least one custom element
#      registration ("customElements.define" or HA Lit equivalent) —
#      catches a truncated/corrupted bundle.

set -euo pipefail
source "$(dirname "$0")/lib.sh"

live_init
live_begin "test_bundle_integrity"

# Target host derived from LIVE_HOST so this works against PROD too with
# the appropriate ssh alias. Default ssh alias picks based on HOST.
case "$LIVE_HOST" in
    10.10.20.46)  SSH_ALIAS="ha-test" ;;
    10.10.20.150) SSH_ALIAS="ha-prod" ;;
    *)            SSH_ALIAS="${SSH_ALIAS_OVERRIDE:-ha-test}" ;;
esac
CARD_DIR="/homeassistant/custom_components/solar_energy_management/dashboard/card"
BUNDLE="$CARD_DIR/dist/sem-cards.js"
SHADOW="$CARD_DIR/sem-cards.js"

# 1. Bundle must exist and be non-empty.
size=$(ssh "$SSH_ALIAS" "stat -c %s '$BUNDLE' 2>/dev/null || echo 0" 2>/dev/null || echo 0)
size=${size:-0}
_log "$BUNDLE: ${size} bytes"

if (( size < 1000 )); then
    echo "✗ FAIL: $BUNDLE missing or suspiciously small (${size} bytes)" >&2
    echo "        Dashboard cards will not load. Expected the Lit bundle (≥ ~10 kB)." >&2
    echo "        Check that 'cd dashboard/card && npm run build' was run before deploy." >&2
    exit 1
fi
_log "✓ bundle present and non-trivial"

# 2. Top-level sem-cards.js (without dist/) MUST NOT exist — would shadow.
shadow_exists=$(ssh "$SSH_ALIAS" "test -f '$SHADOW' && echo yes || echo no" 2>/dev/null || echo no)
if [[ "$shadow_exists" == "yes" ]]; then
    shadow_size=$(ssh "$SSH_ALIAS" "stat -c %s '$SHADOW' 2>/dev/null" 2>/dev/null || echo "?")
    echo "✗ FAIL: stray top-level $SHADOW exists (${shadow_size} bytes)" >&2
    echo "        This was the #219 root cause: a top-level sem-cards.js" >&2
    echo "        registers before dist/sem-cards.js and shadows the real" >&2
    echo "        bundle. Delete it." >&2
    exit 1
fi
_log "✓ no top-level shadow file at $SHADOW"

# 3. Bundle must contain custom element registrations.
has_custom_el=$(ssh "$SSH_ALIAS" "grep -l 'customElements.define\|customElements\\[.define.\\]' '$BUNDLE' >/dev/null && echo yes || echo no" 2>/dev/null || echo no)
if [[ "$has_custom_el" != "yes" ]]; then
    echo "✗ FAIL: $BUNDLE has no customElements.define calls" >&2
    echo "        The bundle is present but appears truncated or corrupted —" >&2
    echo "        no cards will be registered." >&2
    exit 1
fi
_log "✓ bundle registers custom elements"

live_end
