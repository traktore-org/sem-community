# Charger State Reconciler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SEM's per-cycle imperative charger actuator with a desired-vs-observed reconciliation loop so the KEBA (and every brand) holds its commanded state idempotently — no more 6 A reverts, no `keba.disable` spam, reliable across all modes.

**Architecture:** A new per-charger `ChargerReconciler` maps the existing `ChargerDecision` to a `DesiredState`, reads an `ObservedState` from the adapter, and emits the *minimum* set of `Action`s to converge — issuing zero service calls when already converged. `decide()` and `charge_stability` (which produce the stable target) and `_set_current`'s write-level heartbeat are unchanged; the reconciler only owns intent-level convergence (start/stop/idle) and failsafe arming.

**Tech Stack:** Python 3.12, Home Assistant custom component, pytest. Spec: `docs/superpowers/specs/2026-06-21-charger-reconciler-design.md`.

---

## Test runner (use for every "run tests" step)

```bash
rsync -a --delete --exclude=.git --exclude=node_modules ./ /tmp/ha-config/custom_components/solar_energy_management/
cd /tmp/ha-config && PYTHONPATH=/tmp/ha-config python3.12 -m pytest \
  custom_components/solar_energy_management/tests/test_charger_reconciler.py -q
```

Run from repo root for the rsync; the pytest must run from `/tmp/ha-config` (repo-root `select.py` shadows stdlib `select`).

## File structure

- **Create** `coordinator/charger_reconciler.py` — `DesiredState` enum, `ObservedState` dataclass, `ActionKind` enum, `Action` dataclass, `desired_from_decision()`, `observe()`, `ChargerReconciler`. The only new module. Brand-agnostic.
- **Create** `tests/test_charger_reconciler.py` — pure decision-table + regression tests.
- **Modify** `coordinator/actuate.py` — `actuate()` gains an optional `reconciler` param; when present it delegates to `reconciler.reconcile_and_apply()`, else runs the legacy dispatch (kept until Increment 3).
- **Modify** `coordinator/coordinator.py` — add a `_charger_reconcilers` per-charger cache (parallel to `_charger_adapters`) and pass the reconciler into both `actuate(...)` call sites (lines 1828, 1901).

---

## Increment 1 — reconciler skeleton + idempotent IDLE/OFF

Stops the live PROD chatter. CHARGE still emits a write every cycle (device dedups at the write level → no behaviour change); IDLE/OFF become idempotent.

### Task 1: Reconciler value types + pure mapping

**Files:**
- Create: `coordinator/charger_reconciler.py`
- Test: `tests/test_charger_reconciler.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_charger_reconciler.py
"""Charger state reconciler — desired-vs-observed convergence (#392).

Replaces the per-cycle imperative actuator. These tests pin the pure
decision table: given a desired state, an observed state and a clock,
the reconciler emits the MINIMUM set of actions to converge — and
emits NONE when already converged (the root-cause fix for the 391×
keba.disable spam seen on PROD 2026-06-21).
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    ActionKind,
    DesiredState,
    ObservedState,
    desired_from_decision,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
)


def _decision(intent: ChargerIntent, amps: int = 0) -> ChargerDecision:
    return ChargerDecision(
        charger_id="ev_charger",
        intent=intent,
        commanded_amps=amps,
        reason="test",
        budget_w=0.0,
    )


def test_desired_from_decision_maps_every_intent():
    assert desired_from_decision(_decision(ChargerIntent.DISABLE)) == (DesiredState.OFF, 0)
    assert desired_from_decision(_decision(ChargerIntent.IDLE)) == (DesiredState.IDLE, 0)
    assert desired_from_decision(_decision(ChargerIntent.CHARGE_AT_AMPS, 10)) == (DesiredState.CHARGE, 10)
    # CHARGE_MAX maps to CHARGE with amps=0 sentinel — apply layer resolves max.
    assert desired_from_decision(_decision(ChargerIntent.CHARGE_MAX)) == (DesiredState.CHARGE, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run the test runner (Task header). Expected: `ModuleNotFoundError: ... charger_reconciler`.

- [ ] **Step 3: Write minimal implementation**

```python
# coordinator/charger_reconciler.py
"""Charger state reconciler — desired-vs-observed convergence (#392).

The per-cycle imperative actuator (``actuate.py``) re-issued a hardware
command EVERY coordinator cycle regardless of whether anything changed —
the root cause of the recurring KEBA 6 A reverts and the 391× repeated
``keba.disable`` seen on PROD 2026-06-21. This module replaces that with
a reconciliation loop: compute the desired state, read the observed
state, emit only the actions needed to converge, and emit nothing when
already converged.

Design: docs/superpowers/specs/2026-06-21-charger-reconciler-design.md
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Tuple

from .charger_types import ChargerDecision, ChargerIntent

_LOGGER = logging.getLogger(__name__)


class DesiredState(Enum):
    """What SEM wants the charger to BE doing this cycle."""
    OFF = auto()     # user-explicit OFF (ChargerIntent.DISABLE)
    IDLE = auto()    # temporary pause (ChargerIntent.IDLE)
    CHARGE = auto()  # charging (CHARGE_AT_AMPS / CHARGE_MAX)


class ActionKind(Enum):
    """Minimal hardware action the reconciler may emit."""
    NONE = auto()           # already converged — issue nothing
    DISABLE = auto()        # open the contactor (brand disable service)
    WRITE_CURRENT = auto()  # set charging current (amps on the Action)
    START_AND_WRITE = auto()  # open a session + arm failsafe + write (amps)


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    amps: int = 0


@dataclass(frozen=True)
class ObservedState:
    """What the charger is actually doing, read from the adapter."""
    charging: bool       # adapter.actual_charging(power) — power-based
    setpoint_a: int      # the value SEM last believes it set
    self_charging: bool  # adapter.is_self_charging(power)
    power_w: float


def desired_from_decision(decision: ChargerDecision) -> Tuple[DesiredState, int]:
    """Pure map: ChargerDecision → (DesiredState, amps).

    CHARGE_MAX returns amps=0 as a sentinel; the apply layer resolves
    the hardware max from the adapter (so this stays pure and the max
    isn't duplicated here)."""
    intent = decision.intent
    if intent is ChargerIntent.DISABLE:
        return DesiredState.OFF, 0
    if intent is ChargerIntent.IDLE:
        return DesiredState.IDLE, 0
    if intent is ChargerIntent.CHARGE_MAX:
        return DesiredState.CHARGE, 0
    if intent is ChargerIntent.CHARGE_AT_AMPS:
        return DesiredState.CHARGE, int(decision.commanded_amps)
    # Defensive: unknown intent → safest is IDLE (no draw, no spam).
    _LOGGER.error("desired_from_decision: unknown intent %r → IDLE", intent)
    return DesiredState.IDLE, 0
```

- [ ] **Step 4: Run test to verify it passes** — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add coordinator/charger_reconciler.py tests/test_charger_reconciler.py
git commit -m "feat(ev): charger reconciler value types + intent mapping (#392)"
```

### Task 2: The pure decision table (`reconcile`)

**Files:**
- Modify: `coordinator/charger_reconciler.py`
- Test: `tests/test_charger_reconciler.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_charger_reconciler.py
from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    Action, ActionKind, ChargerReconciler, ObservedState,
)

HEARTBEAT_S = 5.0  # KEBA refresh interval


def _rec() -> ChargerReconciler:
    return ChargerReconciler(charger_id="ev_charger", heartbeat_s=HEARTBEAT_S,
                             idle_disable_threshold=4)


def _obs(charging=False, setpoint=0, self_charging=False, power=0.0) -> ObservedState:
    return ObservedState(charging=charging, setpoint_a=setpoint,
                         self_charging=self_charging, power_w=power)


def test_idle_not_drawing_emits_nothing_every_cycle():
    """The PROD bug: IDLE + already-open contactor must NOT re-disable."""
    rec = _rec()
    for cycle in range(100):
        actions = rec.reconcile(DesiredState.IDLE, 0, _obs(charging=False), now=cycle * 10.0)
        assert actions == [Action(ActionKind.NONE)], f"cycle {cycle} spammed: {actions}"


def test_off_drawing_disables_immediately_no_flicker_grace():
    rec = _rec()
    actions = rec.reconcile(DesiredState.OFF, 0, _obs(charging=True, power=4000.0), now=0.0)
    assert actions == [Action(ActionKind.DISABLE)]


def test_idle_drawing_holds_then_disables_after_threshold():
    rec = _rec()
    # cycles 1..3 (< threshold 4): flicker hold → NONE
    for cycle in range(1, 4):
        actions = rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=6000.0),
                                now=cycle * 10.0)
        assert actions == [Action(ActionKind.NONE)], f"cycle {cycle}: {actions}"
    # cycle 4 (>= threshold): confirmed real → DISABLE
    actions = rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=6000.0), now=40.0)
    assert actions == [Action(ActionKind.DISABLE)]


def test_idle_resets_flicker_counter_when_box_stops():
    rec = _rec()
    rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=6000.0), now=10.0)  # count=1
    rec.reconcile(DesiredState.IDLE, 0, _obs(charging=False), now=20.0)  # stopped → NONE + reset
    # next drawing idle starts a fresh hold window, not an immediate disable
    actions = rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=6000.0), now=30.0)
    assert actions == [Action(ActionKind.NONE)]


def test_charge_not_charging_starts():
    rec = _rec()
    actions = rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=False), now=0.0)
    assert actions == [Action(ActionKind.START_AND_WRITE, 10)]


def test_charge_steady_writes_only_on_heartbeat():
    """Steady CHARGE(10): write on start, then only every heartbeat_s."""
    rec = _rec()
    rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=False), now=0.0)  # START
    writes = 0
    for cycle in range(1, 100):
        t = cycle * 1.0  # 1 s cycle to make heartbeat counting easy
        actions = rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=True, setpoint=10), now=t)
        if actions != [Action(ActionKind.NONE)]:
            writes += 1
            assert actions == [Action(ActionKind.WRITE_CURRENT, 10)]
    # 99 cycles over 1 s each, heartbeat 5 s → ~19 refreshes, not 99
    assert 15 <= writes <= 21, writes


def test_charge_target_change_writes_immediately():
    rec = _rec()
    rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=False), now=0.0)
    actions = rec.reconcile(DesiredState.CHARGE, 12, _obs(charging=True, setpoint=10), now=1.0)
    assert actions == [Action(ActionKind.WRITE_CURRENT, 12)]


def test_charge_drift_rewrites():
    """Box silently reverted to 6 A (failsafe) while we wanted 10 → re-assert."""
    rec = _rec()
    rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=False), now=0.0)
    actions = rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=True, setpoint=6), now=1.0)
    assert actions == [Action(ActionKind.WRITE_CURRENT, 10)]
```

- [ ] **Step 2: Run to verify failure** — Expected: `AttributeError`/`ImportError` (no `ChargerReconciler`).

- [ ] **Step 3: Implement `ChargerReconciler.reconcile`**

```python
# append to coordinator/charger_reconciler.py

class ChargerReconciler:
    """Per-charger convergence engine. One instance per charger, cached
    for the charger's lifetime (it holds transition state). Pure
    ``reconcile`` for decisions; effectful ``reconcile_and_apply`` (Task 3)
    executes them via the adapter.
    """

    def __init__(self, charger_id: str, heartbeat_s: float,
                 idle_disable_threshold: int = 4) -> None:
        self.charger_id = charger_id
        self._heartbeat_s = float(heartbeat_s)
        self._idle_disable_threshold = int(idle_disable_threshold)
        self._last_write_at: float = 0.0
        self._consecutive_idle_count: int = 0

    def reconcile(self, desired: DesiredState, amps: int,
                  observed: ObservedState, now: float) -> List[Action]:
        """Pure decision table (spec rows 1-8, first match wins)."""

        # OFF / IDLE share the convergence target (contactor open). The
        # only difference is the flicker grace, which OFF never gets.
        if desired in (DesiredState.OFF, DesiredState.IDLE):
            drawing = observed.charging or observed.self_charging
            if not drawing:
                # Row 2 — already converged. THE spam fix: issue nothing.
                self._consecutive_idle_count = 0
                return [Action(ActionKind.NONE)]
            if desired is DesiredState.OFF:
                # Row 1 — user-explicit OFF: open immediately, no grace.
                return [Action(ActionKind.DISABLE)]
            # IDLE + drawing — flicker hold then confirm (rows 3-4).
            self._consecutive_idle_count += 1
            if self._consecutive_idle_count < self._idle_disable_threshold:
                return [Action(ActionKind.NONE)]
            return [Action(ActionKind.DISABLE)]

        # desired is CHARGE — reset idle grace.
        self._consecutive_idle_count = 0
        if not observed.charging:
            # Row 5 — open a session, arm failsafe, write.
            self._last_write_at = now
            return [Action(ActionKind.START_AND_WRITE, amps)]
        if amps and observed.setpoint_a != amps:
            # Row 6 — target change or drift (failsafe revert) correction.
            self._last_write_at = now
            return [Action(ActionKind.WRITE_CURRENT, amps)]
        if (now - self._last_write_at) >= self._heartbeat_s:
            # Row 7 — refresh to feed the device failsafe watchdog.
            self._last_write_at = now
            return [Action(ActionKind.WRITE_CURRENT, amps)]
        # Row 8 — converged and fresh.
        return [Action(ActionKind.NONE)]
```

Note: `amps and observed.setpoint_a != amps` skips drift checks when `amps==0`
(CHARGE_MAX sentinel) — the apply layer resolves max and the heartbeat row keeps
it fed; a follow-up in Increment 3 resolves the max into `amps` before reconcile so
drift detection covers CHARGE_MAX too.

- [ ] **Step 4: Run to verify pass** — Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add coordinator/charger_reconciler.py tests/test_charger_reconciler.py
git commit -m "feat(ev): reconciler pure decision table (idempotent idle/off) (#392)"
```

### Task 3: `reconcile_and_apply` — execute actions via the adapter

**Files:**
- Modify: `coordinator/charger_reconciler.py`
- Test: `tests/test_charger_reconciler.py`

- [ ] **Step 1: Write the failing test (mock adapter)**

```python
# append to tests/test_charger_reconciler.py
from unittest.mock import AsyncMock, MagicMock
from custom_components.solar_energy_management.coordinator.charger_types import ChargerPower


def _mock_adapter(max_a=32):
    a = MagicMock()
    a.command_disable = AsyncMock()
    a.command_current = AsyncMock()
    a.command_max = AsyncMock()
    a.max_current_a = max_a
    return a


def _power(power_w=0.0):
    return ChargerPower(charger_id="ev_charger", power_w=power_w)


@pytest.mark.asyncio
async def test_apply_idle_idempotent_no_calls_when_open():
    rec = _rec()
    adapter = _mock_adapter()
    adapter.actual_charging = MagicMock(return_value=False)
    adapter.is_self_charging = MagicMock(return_value=False)
    for cycle in range(50):
        await rec.reconcile_and_apply(
            _decision(ChargerIntent.IDLE), adapter, _power(0.0), now=cycle * 10.0)
    adapter.command_disable.assert_not_called()
    adapter.command_current.assert_not_called()


@pytest.mark.asyncio
async def test_apply_charge_max_resolves_hardware_max():
    rec = _rec()
    adapter = _mock_adapter(max_a=32)
    adapter.actual_charging = MagicMock(return_value=True)
    adapter.is_self_charging = MagicMock(return_value=False)
    adapter._device = MagicMock(_current_setpoint=32)
    await rec.reconcile_and_apply(
        _decision(ChargerIntent.CHARGE_MAX), adapter, _power(22000.0), now=100.0)
    # heartbeat due (last_write_at=0) → a refresh write at max
    adapter.command_current.assert_called_once_with(32)
```

- [ ] **Step 2: Run to verify failure** — Expected: `AttributeError: reconcile_and_apply`.

- [ ] **Step 3: Implement `observe` + `reconcile_and_apply`**

```python
# append to coordinator/charger_reconciler.py — module-level helper

def observe(adapter, power) -> ObservedState:
    """Read the observed state from the adapter (brand-agnostic)."""
    setpoint = int(getattr(getattr(adapter, "_device", None), "_current_setpoint", 0) or 0)
    return ObservedState(
        charging=adapter.actual_charging(power),
        setpoint_a=setpoint,
        self_charging=adapter.is_self_charging(power),
        power_w=float(getattr(power, "power_w", 0.0) or 0.0),
    )
```

```python
# add as a method on ChargerReconciler

    async def reconcile_and_apply(self, decision, adapter, power, now) -> None:
        """Compute desired+observed, reconcile, execute the actions."""
        desired, amps = desired_from_decision(decision)
        if desired is DesiredState.CHARGE and amps == 0:
            # Resolve the CHARGE_MAX sentinel to the hardware max so the
            # adapter writes a real value and drift detection works.
            amps = int(getattr(adapter, "max_current_a", 0)) or amps
        observed = observe(adapter, power)
        actions = self.reconcile(desired, amps, observed, now)

        for action in actions:
            if action.kind is ActionKind.NONE:
                continue
            if action.kind is ActionKind.DISABLE:
                await adapter.command_disable()
                _LOGGER.info("reconcile(%s): DISABLE — %s",
                             self.charger_id, decision.reason)
            elif action.kind in (ActionKind.WRITE_CURRENT, ActionKind.START_AND_WRITE):
                # START_AND_WRITE failsafe arming is wired in Increment 2;
                # for now command_current opens the session itself (the
                # adapter's existing start_session-on-write behaviour).
                await adapter.command_current(action.amps)
                _LOGGER.debug("reconcile(%s): %s %dA — %s", self.charger_id,
                              action.kind.name, action.amps, decision.reason)
```

- [ ] **Step 4: Run to verify pass** — Expected: PASS. Run the FULL new test file.

- [ ] **Step 5: Commit**

```bash
git add coordinator/charger_reconciler.py tests/test_charger_reconciler.py
git commit -m "feat(ev): reconciler apply layer (observe + execute) (#392)"
```

### Task 4: Wire the reconciler into `actuate()` (opt-in, back-compatible)

**Files:**
- Modify: `coordinator/actuate.py:31-56` (signature + early delegation)
- Test: `tests/test_charger_reconciler.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_charger_reconciler.py
from custom_components.solar_energy_management.coordinator.actuate import actuate


@pytest.mark.asyncio
async def test_actuate_delegates_to_reconciler_when_provided():
    rec = _rec()
    adapter = _mock_adapter()
    adapter.actual_charging = MagicMock(return_value=False)
    adapter.is_self_charging = MagicMock(return_value=False)
    # IDLE + open contactor → reconciler issues nothing
    await actuate(_decision(ChargerIntent.IDLE), adapter, _power(0.0), reconciler=rec)
    adapter.command_disable.assert_not_called()


@pytest.mark.asyncio
async def test_actuate_legacy_path_unchanged_without_reconciler():
    adapter = _mock_adapter()
    adapter.is_self_charging = MagicMock(return_value=False)
    adapter.reset_idle_debounce = MagicMock()
    # CHARGE_MAX with no reconciler → legacy dispatch calls command_max
    await actuate(_decision(ChargerIntent.CHARGE_MAX), adapter, _power(0.0))
    adapter.command_max.assert_awaited_once()
```

- [ ] **Step 2: Run to verify failure** — Expected: `TypeError: actuate() got an unexpected keyword argument 'reconciler'`.

- [ ] **Step 3: Implement the delegation**

In `coordinator/actuate.py`, change the signature and add the delegation at the top of the body (before the self-resume guard):

```python
async def actuate(
    decision: ChargerDecision,
    adapter: ChargerAdapter,
    power: ChargerPower,
    reconciler=None,
) -> None:
    # Reconciler path (#392): when a per-charger reconciler is supplied,
    # it owns the full convergence decision (idempotent idle/off, drift,
    # heartbeat). The legacy per-cycle dispatch below is kept only for
    # callers/tests that don't pass one, and is retired in Increment 3.
    if reconciler is not None:
        import time
        await reconciler.reconcile_and_apply(decision, adapter, power, time.monotonic())
        return

    # === Self-resume guard ===  (existing legacy body unchanged)
    ...
```

Leave the rest of the function exactly as-is.

- [ ] **Step 4: Run to verify pass** — Expected: PASS. Then run the legacy actuator tests to confirm no regression:

```bash
cd /tmp/ha-config && PYTHONPATH=/tmp/ha-config python3.12 -m pytest \
  custom_components/solar_energy_management/tests/ -q -k "actuate or keba or 392 or 315 or 346 or 353"
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add coordinator/actuate.py tests/test_charger_reconciler.py
git commit -m "feat(ev): actuate() delegates to reconciler when provided (#392)"
```

### Task 5: Wire the reconciler cache into the coordinator

**Files:**
- Modify: `coordinator/coordinator.py` — near the `_charger_adapters` cache (≈1723-1730), add a `_charger_reconcilers` cache; pass it to both `actuate(...)` calls (lines 1828, 1901).

- [ ] **Step 1: Add the reconciler cache + lookup** (right after the adapter is resolved at ≈1730)

```python
# after: adapter_cache[cid] = adapter
rec_cache = getattr(self, "_charger_reconcilers", None)
if rec_cache is None:
    rec_cache = {}
    self._charger_reconcilers = rec_cache
reconciler = rec_cache.get(cid)
if reconciler is None or reconciler.charger_id != cid:
    from .charger_reconciler import ChargerReconciler
    reconciler = ChargerReconciler(
        charger_id=cid,
        heartbeat_s=float(getattr(ev_dev, "watchdog_refresh_interval_s", 5.0)),
        idle_disable_threshold=int(getattr(adapter, "IDLE_DEBOUNCE_THRESHOLD", 4)),
    )
    rec_cache[cid] = reconciler
```

- [ ] **Step 2: Pass it to both actuate calls**

Line 1828: `await actuate(decision, adapter, view.power, reconciler=reconciler)`
Line 1901: the second call site — resolve/create a reconciler the same way in that block and pass `reconciler=reconciler`. (Check whether 1901 is inside the same loop scope as the cache; if so, reuse the `reconciler` variable. If it's a separate code path with its own adapter resolution, replicate the cache lookup block there.)

- [ ] **Step 3: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('coordinator/coordinator.py').read())" && echo OK
```

- [ ] **Step 4: Run the full suite**

```bash
rsync -a --delete --exclude=.git --exclude=node_modules ./ /tmp/ha-config/custom_components/solar_energy_management/
cd /tmp/ha-config && PYTHONPATH=/tmp/ha-config python3.12 -m pytest \
  custom_components/solar_energy_management/tests/ -q
```

Expected: all green (existing + new reconciler tests).

- [ ] **Step 5: Commit**

```bash
git add coordinator/coordinator.py
git commit -m "feat(ev): wire per-charger reconciler into coordinator actuate path (#392)"
```

### Task 6: Live verify Increment 1 on HA-TEST (the chatter must stop)

Per `feedback_live_test_before_deploy` — backend pipeline change needs live verification, not just pytest.

- [ ] **Step 1: Build is not needed (no card change). Deploy code-only:**

```bash
~/bin/deploy-test.sh --code-only
```

- [ ] **Step 2: Drive an IDLE condition** — set EV mode to `min_plus_solar` (or `off`) with no surplus on HA-TEST so `decide()` returns IDLE. Then watch the log for 2 minutes:

```bash
ssh ha-test "ha core logs 2>/dev/null | grep -E 'keba.disable|reconcile|actuate.ev' | tail -40"
```

**Expected:** `keba.disable` fires **at most once** on the transition into idle, then **silence** (no per-cycle repeats). Before the fix it fired every 10 s.

- [ ] **Step 3: Drive a CHARGE condition** — set `always_max`, confirm the car charges and holds; confirm `set_current` writes only at the heartbeat cadence, not every cycle.

- [ ] **Step 4: Run `~/bin/validate-sem.sh`** — confirm integration healthy, no new errors.

- [ ] **Step 5: Update CHANGELOG** (`CHANGELOG.md`, top entry) + bump `manifest.json` beta, then commit:

```bash
git add CHANGELOG.md manifest.json
git commit -m "chore(ev): reconciler increment 1 — idempotent idle/off (beta.NN) (#392)"
```

---

## Increment 2 — CHARGE start-transition + failsafe arming through the reconciler

### Task 7: Add `ARM_FAILSAFE` to the start transition

**Files:**
- Modify: `coordinator/charger_reconciler.py` (apply layer)
- Modify: `devices/base.py` — extract a public `async def arm_failsafe(self)` from the inline block in `start_session` (lines 991-1009) so the reconciler can call it without opening a duplicate session.
- Test: `tests/test_charger_reconciler.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_charger_reconciler.py
@pytest.mark.asyncio
async def test_start_arms_failsafe_once():
    rec = _rec()
    adapter = _mock_adapter()
    adapter.actual_charging = MagicMock(side_effect=[False, True, True])
    adapter.is_self_charging = MagicMock(return_value=False)
    adapter._device = MagicMock(_current_setpoint=10)
    adapter.arm_failsafe = AsyncMock()
    # cycle 1: not charging → START arms failsafe
    await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_AT_AMPS, 10),
                                  adapter, _power(0.0), now=0.0)
    adapter.arm_failsafe.assert_awaited_once()
    # cycle 2: charging steady → no re-arm
    await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_AT_AMPS, 10),
                                  adapter, _power(7000.0), now=1.0)
    adapter.arm_failsafe.assert_awaited_once()
```

- [ ] **Step 2: Run to verify failure** — Expected: `arm_failsafe` not awaited (apply layer doesn't call it yet).

- [ ] **Step 3a: Extract `arm_failsafe` in `devices/base.py`**

Move the body of lines 991-1009 (the `set_failsafe` call) into:

```python
    async def arm_failsafe(self) -> None:
        """Set a benign device failsafe (timeout 30 s, fallback = charging
        floor) so a controller-death keeps the car at the floor instead of
        pausing, and per-cycle writes keep it from ever tripping (#392)."""
        domain = (self.charger_service or "").split(".", 1)[0]
        if not domain or not self.hass.services.has_service(domain, "set_failsafe"):
            return
        try:
            fallback_a = max(6, int(round(self.min_current)))
            await self.hass.services.async_call(
                domain, "set_failsafe",
                {"failsafe_timeout": 30, "failsafe_fallback": fallback_a,
                 "failsafe_persist": 0},
                blocking=True,
            )
            _LOGGER.info("%s: KEBA failsafe set benign (timeout=30s, fallback=%dA)",
                         self.name, fallback_a)
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("Failed to set charger failsafe: %s", e)
```

In `start_session`, replace the inline block with `await self.arm_failsafe()` (keeps the existing start path working).

- [ ] **Step 3b: Expose it on the adapter** — add to `charger_adapters/base.py` (default no-op) and `keba.py` (delegate to device):

```python
# base.py ChargerAdapter
    async def arm_failsafe(self) -> None:
        """Arm the device-side failsafe benignly. Default: no-op (most
        brands have no failsafe). KEBA overrides."""
        return None
```

```python
# keba.py KebaAdapter
    async def arm_failsafe(self) -> None:
        await self._device.arm_failsafe()
```

- [ ] **Step 3c: Call it from the apply layer** — in `reconcile_and_apply`, handle `START_AND_WRITE`:

```python
            elif action.kind is ActionKind.START_AND_WRITE:
                await adapter.arm_failsafe()
                await adapter.command_current(action.amps)
                _LOGGER.info("reconcile(%s): START %dA (failsafe armed) — %s",
                             self.charger_id, action.amps, decision.reason)
            elif action.kind is ActionKind.WRITE_CURRENT:
                await adapter.command_current(action.amps)
```

(Split the combined branch from Task 3 into the two cases above.)

- [ ] **Step 4: Run to verify pass** — Expected: PASS. Run full suite + `-k failsafe`.

- [ ] **Step 5: Commit**

```bash
git add coordinator/charger_reconciler.py devices/base.py coordinator/charger_adapters/base.py coordinator/charger_adapters/keba.py tests/test_charger_reconciler.py
git commit -m "feat(ev): reconciler arms benign failsafe on charge start (#392)"
```

### Task 8: Re-arm failsafe on observed device reset

**Files:**
- Modify: `coordinator/charger_reconciler.py`
- Test: `tests/test_charger_reconciler.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_rearms_failsafe_after_box_reset_midcharge():
    rec = _rec()
    adapter = _mock_adapter()
    adapter.is_self_charging = MagicMock(return_value=False)
    adapter._device = MagicMock(_current_setpoint=10)
    adapter.arm_failsafe = AsyncMock()
    # charging
    adapter.actual_charging = MagicMock(return_value=True)
    await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_AT_AMPS, 10),
                                  adapter, _power(7000.0), now=0.0)
    # box reset: stopped while we still want CHARGE → START again, re-arm
    adapter.actual_charging = MagicMock(return_value=False)
    await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_AT_AMPS, 10),
                                  adapter, _power(0.0), now=1.0)
    assert adapter.arm_failsafe.await_count == 1  # the re-START arms it
```

- [ ] **Step 2: Run to verify failure / pass** — With Task 7's logic, an observed `charging=False` while desired CHARGE already yields `START_AND_WRITE`, which arms. This test likely PASSES already → it's a guard test pinning the behaviour. If it fails, ensure the not-charging branch in `reconcile` always emits `START_AND_WRITE` (it does, Task 2 row 5).

- [ ] **Step 3: (only if failing) adjust** — none expected.

- [ ] **Step 4: Run to verify pass.**

- [ ] **Step 5: Commit**

```bash
git add tests/test_charger_reconciler.py
git commit -m "test(ev): pin failsafe re-arm on mid-charge device reset (#392)"
```

### Task 9: Live verify Increment 2 on HA-TEST

- [ ] **Step 1:** `~/bin/deploy-test.sh --code-only`
- [ ] **Step 2:** Start a charge on HA-TEST; confirm the log shows `KEBA failsafe set benign` exactly once on start, then steady charging.
- [ ] **Step 3:** `~/bin/validate-sem.sh` — healthy.
- [ ] **Step 4:** CHANGELOG + manifest beta bump; commit.

---

## Increment 3 — drift detection live + retire the scattered guards

### Task 10: Resolve CHARGE_MAX to amps before reconcile (drift covers max)

**Files:**
- Modify: `coordinator/charger_reconciler.py` — already resolves max in `reconcile_and_apply` (Task 3). Add a test that drift correction now fires for CHARGE_MAX too.
- Test: `tests/test_charger_reconciler.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_charge_max_drift_corrects():
    rec = _rec()
    adapter = _mock_adapter(max_a=32)
    adapter.is_self_charging = MagicMock(return_value=False)
    adapter.actual_charging = MagicMock(return_value=True)
    adapter.arm_failsafe = AsyncMock()
    adapter._device = MagicMock(_current_setpoint=6)  # reverted to failsafe floor
    await rec.reconcile_and_apply(_decision(ChargerIntent.CHARGE_MAX),
                                  adapter, _power(4000.0), now=1.0)
    adapter.command_current.assert_called_once_with(32)
```

- [ ] **Step 2-4:** Run — should PASS (Task 3 resolves max → drift row fires). If not, ensure the `amps and ...` drift guard uses the resolved max.

- [ ] **Step 5: Commit**

```bash
git add tests/test_charger_reconciler.py
git commit -m "test(ev): drift correction covers CHARGE_MAX (#392)"
```

### Task 11: Retire the legacy dispatch + idle debounce from `actuate.py`

**Files:**
- Modify: `coordinator/actuate.py` — once all call sites pass a reconciler, remove the legacy body (self-resume guard, idle debounce, intent dispatch) and keep only the reconciler delegation. The self-resume guard is now covered by reconcile rows 1/4 (drawing-against-intent → DISABLE).
- Modify: `coordinator/charger_adapters/base.py` + `keba.py` — remove `attempt_idle` / `reset_idle_debounce` / `_consecutive_idle_count` (now owned by the reconciler).
- Test: existing tests; update any that asserted the legacy debounce.

- [ ] **Step 1:** Search for legacy-debounce test references:

```bash
cd /tmp/ha-config && PYTHONPATH=/tmp/ha-config python3.12 -m pytest \
  custom_components/solar_energy_management/tests/ -q -k "debounce or idle" 2>&1 | tail
grep -rn "attempt_idle\|reset_idle_debounce\|_consecutive_idle_count\|IDLE_DEBOUNCE_THRESHOLD" coordinator/ tests/
```

- [ ] **Step 2:** Make every `actuate(...)` call site pass a reconciler (verify lines 1828 + 1901 both do after Task 5). Then reduce `actuate()` to:

```python
async def actuate(decision, adapter, power, reconciler) -> None:
    """Apply a per-charger decision through the reconciler. The reconciler
    owns convergence; brand quirks live in the adapter."""
    import time
    await reconciler.reconcile_and_apply(decision, adapter, power, time.monotonic())
```

(Make `reconciler` required now — no legacy fallback.)

- [ ] **Step 3:** Delete the idle-debounce machinery from the adapters; update/remove the tests that pinned it. Replace their coverage with the reconciler flicker-hold tests (Task 2 already covers rows 3-4).

- [ ] **Step 4:** Full suite green:

```bash
rsync -a --delete --exclude=.git --exclude=node_modules ./ /tmp/ha-config/custom_components/solar_energy_management/
cd /tmp/ha-config && PYTHONPATH=/tmp/ha-config python3.12 -m pytest \
  custom_components/solar_energy_management/tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add coordinator/actuate.py coordinator/charger_adapters/base.py coordinator/charger_adapters/keba.py tests/
git commit -m "refactor(ev): retire legacy actuate dispatch + idle debounce — reconciler owns it (#392)"
```

### Task 12: Final live soak + docs + release prep

- [ ] **Step 1:** `~/bin/deploy-test.sh` (full clean install — entity/registry safe) + `~/bin/validate-sem.sh`.
- [ ] **Step 2:** Verify all 5 EV modes live on HA-TEST (off, always_max, min_plus_solar, solar/solar_only, solar_plus_cheap) — each: no per-cycle command spam, holds its target.
- [ ] **Step 3:** Run `ruflo-core:reviewer` on the diff (per `feedback_reviewer_before_deploy`).
- [ ] **Step 4:** Update docs: `docs/MULTI_CHARGER.md` (reconciler is the convergence owner), `CHANGELOG.md`, `ARCHITECTURE` if present. Per `feedback_docs_per_release`.
- [ ] **Step 5:** Deploy PROD only after user approval; confirm the live log shows the chatter gone (`keba.disable`/`set_current` only on real transitions + heartbeat). Commit + (only on explicit user request) tag.

---

## Self-review notes

- **Spec coverage:** every spec section maps to a task — value types (T1), decision table (T2), apply/observe (T3), wiring (T4-5), failsafe arming (T7-8), drift (T2,T6/T10), retire guards (T11), tests incl. the live-bug regression (T2 `test_idle_not_drawing_emits_nothing_every_cycle`), live verify per increment (T6,T9,T12).
- **Type consistency:** `DesiredState`, `ObservedState`, `Action(ActionKind, amps)`, `ChargerReconciler(charger_id, heartbeat_s, idle_disable_threshold)`, `reconcile(desired, amps, observed, now)`, `reconcile_and_apply(decision, adapter, power, now)`, `observe(adapter, power)`, `arm_failsafe()` — names used consistently across all tasks.
- **Open item flagged for execution:** Task 5 Step 2 — confirm whether coordinator line 1901 shares loop scope with the cache (reuse `reconciler`) or needs its own lookup block. Resolve at implementation time by reading the surrounding scope.
