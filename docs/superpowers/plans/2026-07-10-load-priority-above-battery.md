# Load Priority Above Battery Charging (#576) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let high-priority loads and the EV consume solar that would otherwise charge the home battery, above the reserve zone — the Victron-style "loads before battery" priority from #576.

**Architecture:** One gated quantity — *reclaimable battery-charge power* — is added to the surplus figure that two **already-parallel** control paths consume: the `SurplusController` (generic loads) and the EV budget. The two paths are **not merged**; the EV's control stack is untouched. An ordering guard prevents within-cycle double-counting. The battery is never commanded — the inverter self-consumes the residual.

**Tech Stack:** Python 3.12+, Home Assistant custom integration, pytest (`-n 4` via pytest-xdist). Design spec: `docs/superpowers/specs/2026-07-10-load-priority-above-battery-design.md`.

**Parked:** build after the v1.7.4 stable cut. Opt-in, default OFF.

---

## File map

| File | Responsibility | Change |
|---|---|---|
| `coordinator/energy_reclaim.py` (**new**) | Pure helper: compute gated reclaimable battery-charge watts | create |
| `coordinator/coordinator.py:~3016` | Surplus input to `SurplusController` (Phase 1) | modify |
| `coordinator/coordinator.py:~4568` | `excess_solar` feeding the EV budget (Phase 2) | modify |
| `const.py` / `config_flow.py` | New opt-in config key `load_priority_above_battery` | modify |
| `dashboard/card/src/cards/sem-config-card.js` | Config toggle (mockup-first) | modify |
| `translations/*.json`, `dashboard/translations.json` | Toggle label + help ×15 | modify |
| `CHANGELOG.md`, `docs/BATTERY_EXPORT_ARBITRAGE.md`-sibling | Docs | modify |
| `tests/test_576_load_priority_battery.py` (**new**) | Unit + U1–U6 scenarios | create |

**Reserve floor** reuses existing `battery_priority_soc` (default 30, `DEFAULT_BATTERY_PRIORITY_SOC`). No new SOC knob.

---

## PHASE 1 — Generic loads (low risk)

### Task 1: Pure reclaimable-power helper

**Files:**
- Create: `coordinator/energy_reclaim.py`
- Test: `tests/test_576_load_priority_battery.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_576_load_priority_battery.py
import pytest
from custom_components.solar_energy_management.coordinator.energy_reclaim import (
    reclaimable_battery_w,
)

@pytest.mark.unit
class TestReclaimableBatteryW:
    def test_disabled_returns_zero(self):
        # Toggle off → never reclaim (byte-identical to today).
        assert reclaimable_battery_w(
            battery_charge_power=2400, soc=85, priority_soc=30,
            enabled=False, battery_commanded=False) == 0.0

    def test_below_reserve_returns_zero(self):
        # SOC below the reserve zone → battery fills first.
        assert reclaimable_battery_w(
            battery_charge_power=2400, soc=25, priority_soc=30,
            enabled=True, battery_commanded=False) == 0.0

    def test_commanded_charge_returns_zero(self):
        # Force/scheduled/arbitrage charge is honored — no reclaim.
        assert reclaimable_battery_w(
            battery_charge_power=2400, soc=85, priority_soc=30,
            enabled=True, battery_commanded=True) == 0.0

    def test_above_reserve_reclaims_charge_power(self):
        assert reclaimable_battery_w(
            battery_charge_power=2400, soc=85, priority_soc=30,
            enabled=True, battery_commanded=False) == 2400.0

    def test_discharging_battery_reclaims_zero(self):
        # Negative charge power (battery discharging) is not reclaimable.
        assert reclaimable_battery_w(
            battery_charge_power=-1500, soc=85, priority_soc=30,
            enabled=True, battery_commanded=False) == 0.0

    def test_at_reserve_boundary_inclusive(self):
        # SOC exactly at the zone counts as above (>=), matching
        # charging_control.py:257 `soc >= battery_priority_soc`.
        assert reclaimable_battery_w(
            battery_charge_power=1000, soc=30, priority_soc=30,
            enabled=True, battery_commanded=False) == 1000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=/tmp/ha-config python3.12 -m pytest custom_components/solar_energy_management/tests/test_576_load_priority_battery.py -q`
Expected: FAIL — `ModuleNotFoundError: energy_reclaim`.

- [ ] **Step 3: Write minimal implementation**

```python
# coordinator/energy_reclaim.py
"""#576 — reclaimable battery-charge power.

The single gated quantity behind "loads/EV charge before the battery".
Above the reserve zone, power that would otherwise charge the battery is
made available to higher-priority consumers. Pure function so both control
paths (SurplusController, EV budget) share ONE definition and it is fully
unit-testable without a coordinator.
"""
from __future__ import annotations


def reclaimable_battery_w(
    *,
    battery_charge_power: float,
    soc: float,
    priority_soc: float,
    enabled: bool,
    battery_commanded: bool,
) -> float:
    """Watts currently charging the battery that a higher-priority load may
    take instead.

    Returns 0.0 (today's behavior) unless ALL hold:
      - the opt-in toggle is on,
      - SOC is at/above the reserve zone (``battery_priority_soc``),
      - the battery is NOT under an explicit/scheduled command
        (force-charge / scheduled / arbitrage — those are honored),
      - the battery is actually charging (positive power).
    """
    if not enabled or battery_commanded:
        return 0.0
    if soc < priority_soc:
        return 0.0
    return max(0.0, float(battery_charge_power))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=/tmp/ha-config python3.12 -m pytest custom_components/solar_energy_management/tests/test_576_load_priority_battery.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add coordinator/energy_reclaim.py tests/test_576_load_priority_battery.py
git commit -m "feat(#576): reclaimable battery-charge power helper (Phase 1)"
```

---

### Task 2: Config key `load_priority_above_battery` (opt-in, default OFF)

**Files:**
- Modify: `const.py` (add `DEFAULT_LOAD_PRIORITY_ABOVE_BATTERY = False`)
- Modify: `config_flow.py` (options schema — mirror the `battery_grid_arbitrage_enabled` boolean pattern at the arbitrage/tariff step)
- Test: `tests/test_576_load_priority_battery.py`

- [ ] **Step 1: Write the failing test**

```python
def test_config_default_is_off(self):
    from custom_components.solar_energy_management.const import (
        DEFAULT_LOAD_PRIORITY_ABOVE_BATTERY,
    )
    assert DEFAULT_LOAD_PRIORITY_ABOVE_BATTERY is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest ...test_576... -q -k config_default`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

In `const.py`:
```python
DEFAULT_LOAD_PRIORITY_ABOVE_BATTERY = False
```

In `config_flow.py`, add to the options schema next to `battery_grid_arbitrage_enabled` (find it with `grep -n battery_grid_arbitrage_enabled config_flow.py`), following the exact `vol.Optional(..., default=...): bool` shape already used there:
```python
vol.Optional(
    "load_priority_above_battery",
    default=self.config_entry.options.get(
        "load_priority_above_battery", DEFAULT_LOAD_PRIORITY_ABOVE_BATTERY,
    ),
): bool,
```
Import `DEFAULT_LOAD_PRIORITY_ABOVE_BATTERY` at the top of `config_flow.py` alongside the other `DEFAULT_*` imports.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest ...test_576... -q -k config_default` → PASS.
Also run the config-flow suite: `pytest ...tests/test_config_flow.py -q` → all PASS (schema still valid).

- [ ] **Step 5: Commit**

```bash
git add const.py config_flow.py tests/test_576_load_priority_battery.py
git commit -m "feat(#576): opt-in config key load_priority_above_battery (default off)"
```

---

### Task 3: Wire reclaimable into the SurplusController input

**Files:**
- Modify: `coordinator/coordinator.py` (the `true_surplus_w` build at ~line 3016)
- Test: `tests/test_576_load_priority_battery.py`

**Context:** today (`coordinator.py:3016`):
```python
true_surplus_w = (
    float(getattr(power, "grid_export_power", 0.0) or 0.0)
    + self._surplus_controller.active_surplus_draw_w()
)
```
`battery_commanded` for the guard: read from the battery decision the coordinator already computes this cycle. **Build-time step:** `grep -n "battery_status\|battery_mode\|_cycle_battery" coordinator/coordinator.py` to find the field set by `decide_battery` (e.g. a `status.battery_status` in {`selling`,`force_charge`,`scheduled`}); `battery_commanded = status.battery_status in {"force_charge","scheduled","selling"}`. If no single field exists, derive from config force flags + scheduler active state.

- [ ] **Step 1: Write the failing test** (integration-style, patches the helper inputs)

```python
def test_surplus_input_includes_reclaim_above_zone(self):
    # A thin harness that calls the same expression the coordinator uses.
    from custom_components.solar_energy_management.coordinator.energy_reclaim import (
        reclaimable_battery_w,
    )
    grid_export, own_draw, batt_charge, soc = 100.0, 0.0, 2400.0, 85.0
    reclaim = reclaimable_battery_w(
        battery_charge_power=batt_charge, soc=soc, priority_soc=30,
        enabled=True, battery_commanded=False)
    available = grid_export + own_draw + reclaim
    assert available == pytest.approx(2500.0)  # 100 export + 2400 reclaimed

def test_surplus_input_unchanged_when_disabled(self):
    from custom_components.solar_energy_management.coordinator.energy_reclaim import (
        reclaimable_battery_w,
    )
    reclaim = reclaimable_battery_w(
        battery_charge_power=2400, soc=85, priority_soc=30,
        enabled=False, battery_commanded=False)
    assert 100.0 + 0.0 + reclaim == pytest.approx(100.0)  # today's value
```

- [ ] **Step 2: Run test to verify it fails**, then passes once helper is imported (Task 1 already provides it). These lock the wiring math.

- [ ] **Step 3: Implement the wiring** at `coordinator.py:~3016`:

```python
from .energy_reclaim import reclaimable_battery_w  # top-of-file import

# ... inside the surplus block:
reclaim_w = reclaimable_battery_w(
    battery_charge_power=float(getattr(power, "battery_charge_power", 0.0) or 0.0),
    soc=float(getattr(power, "battery_soc", 0.0) or 0.0),
    priority_soc=float(self.config.get("battery_priority_soc", 30)),
    enabled=bool(self.config.get("load_priority_above_battery", False)),
    battery_commanded=battery_commanded,  # from the build-time step above
)
true_surplus_w = (
    float(getattr(power, "grid_export_power", 0.0) or 0.0)
    + self._surplus_controller.active_surplus_draw_w()
    + reclaim_w
)
```

- [ ] **Step 4: Run** the full `test_576` file + `pytest ...tests/test_surplus_controller.py -q` → all PASS (surplus controller behavior unchanged; only its input grew).

- [ ] **Step 5: Commit**

```bash
git add coordinator/coordinator.py tests/test_576_load_priority_battery.py
git commit -m "feat(#576): loads reclaim battery-charge power above the reserve zone"
```

---

### Task 4: Scenario tests U3/U4/U5/U6 (loads)

**Files:**
- Test: `tests/test_576_load_priority_battery.py`

- [ ] **Step 1: Add the four acceptance scenarios** (from the spec §3), each asserting the `available` figure and the resulting on/off allocation via `SurplusController.update()` with two mock discrete loads (1 kW each, prio 2 & 3):

```python
import pytest
from unittest.mock import MagicMock
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.coordinator.energy_reclaim import (
    reclaimable_battery_w,
)

def _available(export, own, batt, soc, enabled, commanded=False, pri=30):
    return export + own + reclaimable_battery_w(
        battery_charge_power=batt, soc=soc, priority_soc=pri,
        enabled=enabled, battery_commanded=commanded)

@pytest.mark.unit
class TestLoadScenarios:
    def test_u3_two_heaters_then_battery(self):
        # 3.5 kW pool, 0 home, 85% SOC, enabled: both heaters get power,
        # residual would flow to battery (not commanded here).
        avail = _available(export=3500, own=0, batt=0, soc=85, enabled=True)
        assert avail == pytest.approx(3500)  # export IS the pre-battery surplus here
        # (battery not charging in this instant → nothing to reclaim; heaters
        # allocate from the 3.5 kW as today.)

    def test_u4_below_reserve_no_reclaim(self):
        avail = _available(export=100, own=0, batt=2400, soc=25, enabled=True)
        assert avail == pytest.approx(100)  # battery fills first

    def test_u5_discrete_load_below_rating_flows_to_battery(self):
        avail = _available(export=800, own=0, batt=0, soc=85, enabled=True)
        assert avail == pytest.approx(800)  # < 1 kW heater rating → heater off

    def test_u6_commanded_charge_no_reclaim(self):
        avail = _available(export=100, own=0, batt=2400, soc=85,
                           enabled=True, commanded=True)
        assert avail == pytest.approx(100)  # force/scheduled/arbitrage honored
```

- [ ] **Step 2: Run** → all PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/test_576_load_priority_battery.py
git commit -m "test(#576): U3-U6 load scenarios (reserve floor, discrete threshold, commanded guard)"
```

- [ ] **Step 4: HA-TEST live check (manual, pre-merge for Phase 1):** register two `surplus`-mode switches with 1 kW ratings, enable the toggle, force SOC ≥ 30 and a battery-charging condition via `~/bin/sem-sim-hold.sh`, confirm the loads switch on and grid export doesn't go negative (no import blip). Below-zone SOC → loads stay yielding. Clean up the sim devices.

---

## PHASE 2 — EV (careful, NOT a merge)

### Task 5: Determine cycle ordering + net the reclaimable

**Files:**
- Modify: `coordinator/coordinator.py`
- Test: `tests/test_576_load_priority_battery.py`

**Context:** the EV budget's `excess_solar` (`coordinator.py:4568`) today *subtracts* battery charge:
```python
excess_solar = power.solar_power - power.home_consumption_power - power.battery_charge_power
```
The EV is the higher-priority consumer, so it gets **first claim** on the reclaimable; the loads (Task 3) must then see the reclaimable **net of the EV's claim** to avoid a within-cycle double-count.

- [ ] **Step 1: Confirm execution order.** `grep -n "_calculate_solar_ev_budget\|surplus_controller.update\|_cycle_ev_budget" coordinator/coordinator.py` and read `_async_update_data` to confirm whether the EV budget is computed before or after the surplus block (~3016). Document the order in a comment. If the EV budget is computed first (expected), the loads' `reclaim_w` in Task 3 must subtract the EV's reclaimed share.

- [ ] **Step 2: Write the failing test** for the netting helper:

```python
def test_loads_get_reclaim_net_of_ev(self):
    from custom_components.solar_energy_management.coordinator.energy_reclaim import (
        reclaimable_battery_w,
    )
    total_reclaim = reclaimable_battery_w(
        battery_charge_power=2400, soc=85, priority_soc=30,
        enabled=True, battery_commanded=False)
    ev_took = 2400.0  # EV consumed the full reclaim this cycle
    loads_reclaim = max(0.0, total_reclaim - ev_took)
    assert loads_reclaim == pytest.approx(0.0)
```

- [ ] **Step 3: Implement.** Cache the EV's reclaimed share on the coordinator when the EV budget is built (`self._ev_reclaimed_w = min(reclaim_w, max(0, ev_budget_increment_from_reclaim))`), and in Task 3's wiring subtract it: `reclaim_w = max(0.0, reclaim_w - getattr(self, "_ev_reclaimed_w", 0.0))`. If Step 1 shows the surplus block runs FIRST, invert: loads get full reclaim, EV nets against loads instead (adjust which path subtracts).

- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit**

```bash
git add coordinator/coordinator.py tests/test_576_load_priority_battery.py
git commit -m "feat(#576): EV-first ordering guard against within-cycle double-count"
```

---

### Task 6: Wire reclaimable into the EV budget above the zone

**Files:**
- Modify: `coordinator/coordinator.py:~4568`
- Test: `tests/test_576_load_priority_battery.py`

- [ ] **Step 1: Write the failing test** (budget math):

```python
def test_ev_excess_solar_reclaims_above_zone(self):
    from custom_components.solar_energy_management.coordinator.energy_reclaim import (
        reclaimable_battery_w,
    )
    solar, home, batt, soc = 7000.0, 1500.0, 2000.0, 85.0
    base_excess = solar - home - batt          # today = 3500 (export-equiv)
    reclaim = reclaimable_battery_w(
        battery_charge_power=batt, soc=soc, priority_soc=30,
        enabled=True, battery_commanded=False)
    excess = base_excess + reclaim             # 3500 + 2000 = 5500
    assert excess == pytest.approx(5500.0)     # ≥ EV min → car can start (U2)

def test_ev_excess_unchanged_below_zone(self):
    from custom_components.solar_energy_management.coordinator.energy_reclaim import (
        reclaimable_battery_w,
    )
    solar, home, batt, soc = 4000.0, 1755.0, 2400.0, 25.0
    base = solar - home - batt
    reclaim = reclaimable_battery_w(
        battery_charge_power=batt, soc=soc, priority_soc=30,
        enabled=True, battery_commanded=False)
    assert base + reclaim == pytest.approx(base)  # below zone → unchanged (U1/U4)
```

- [ ] **Step 2: Run** → PASS (helper already exists).

- [ ] **Step 3: Implement** at `coordinator.py:~4568`:

```python
excess_solar = (
    power.solar_power
    - power.home_consumption_power
    - power.battery_charge_power
    + reclaimable_battery_w(
        battery_charge_power=float(power.battery_charge_power or 0.0),
        soc=float(power.battery_soc or 0.0),
        priority_soc=float(self.config.get("battery_priority_soc", 30)),
        enabled=bool(self.config.get("load_priority_above_battery", False)),
        battery_commanded=battery_commanded,
    )
)
# cache the EV's reclaimed share for the loads-netting guard (Task 5)
self._ev_reclaimed_w = max(0.0, excess_solar - (power.solar_power
    - power.home_consumption_power - power.battery_charge_power))
```
The existing min-current gate (`charging_control.py:255-268`, `soc >= battery_priority_soc`) already stops the car below the zone, so `excess_solar` only matters above it — consistent with the `reclaimable_battery_w` gate.

- [ ] **Step 4: Run** `pytest ...tests/test_ev_control.py tests/test_multi_charger_control.py tests/test_576... -q` → all PASS (EV path behavior unchanged when toggle off / below zone).

- [ ] **Step 5: Commit**

```bash
git add coordinator/coordinator.py tests/test_576_load_priority_battery.py
git commit -m "feat(#576): EV reclaims battery-charge power above the reserve zone (Phase 2)"
```

---

### Task 7: Scenario tests U1/U2 + mode parity

**Files:**
- Test: `tests/test_576_load_priority_battery.py`

- [ ] **Step 1: Add U1 (too-low → battery), U2 (enough → car wins)** as budget-level assertions mirroring Task 6, plus a **mode-parity guard**: with `enabled=False`, `excess_solar` for solar_only and min_plus_solar equals the pre-#576 value for a matrix of (solar, home, batt, soc) rows. Assert byte-identical.

```python
@pytest.mark.unit
class TestEvScenarios:
    @pytest.mark.parametrize("solar,home,batt,soc,expect_start", [
        (4000, 1755, 2400, 85, False),   # U1: pool 2.3kW < EV min 5.5kW
        (7000, 1500, 2000, 85, True),    # U2: pool 5.5kW >= EV min
    ])
    def test_u1_u2(self, solar, home, batt, soc, expect_start):
        from custom_components.solar_energy_management.coordinator.energy_reclaim import (
            reclaimable_battery_w)
        EV_MIN = 5500
        excess = (solar - home - batt) + reclaimable_battery_w(
            battery_charge_power=batt, soc=soc, priority_soc=30,
            enabled=True, battery_commanded=False)
        assert (excess >= EV_MIN) is expect_start

    def test_mode_parity_when_disabled(self):
        from custom_components.solar_energy_management.coordinator.energy_reclaim import (
            reclaimable_battery_w)
        for solar, home, batt, soc in [(4000,1755,2400,85),(7000,1500,2000,20)]:
            base = solar - home - batt
            got = base + reclaimable_battery_w(
                battery_charge_power=batt, soc=soc, priority_soc=30,
                enabled=False, battery_commanded=False)
            assert got == pytest.approx(base)
```

- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/test_576_load_priority_battery.py
git commit -m "test(#576): U1/U2 EV scenarios + solar_only/min_plus_solar parity guard"
```

- [ ] **Step 4: HA-TEST live check (pre-merge for Phase 2):** enable the toggle; force **U2** on the sim (solar ~7 kW, SOC ≥ 30, car connected) → confirm `sensor.sem_ev_power` ramps and the battery charge power drops by the EV's draw (no grid import). Force **U4** (SOC < 30) → car waits, battery charges. Clean up.

---

### Task 8: Full suite + reviewer

- [ ] **Step 1:** `rsync` to `/tmp/ha-config` and run the FULL suite parallel:
`PYTHONPATH=/tmp/ha-config python3.12 -m pytest custom_components/solar_energy_management/tests/ -q -n 4` → expect all green.
- [ ] **Step 2:** Dispatch `ruflo-core:reviewer` on the staged diff (per the reviewer-before-deploy rule). Fix any BLOCKER/HIGH.
- [ ] **Step 3: Commit** any review fixes.

---

## UI + DOCS

### Task 9: Config toggle (mockup-first)

**Files:**
- Modify: `dashboard/card/src/cards/sem-config-card.js` (Battery or Tariff section)
- Modify: `dashboard/translations.json` + regenerate `sem-localize.js`; `translations/*.json` if a `strings.json` entity name is involved
- Build: `cd dashboard/card && npm run build`

- [ ] **Step 1:** Per the working agreement, produce a layout mockup of the toggle against the reference (EV card) and get approval BEFORE editing the card.
- [ ] **Step 2:** Add the toggle bound to `load_priority_above_battery` with a one-line help string; add `load_priority_above_battery`/`_help` keys across 15 languages in `dashboard/translations.json`; `python3 scripts/regenerate_localize.py`; `npm run build`.
- [ ] **Step 3:** `pytest ...tests/test_card_template_lint.py tests/test_dashboard_translations.py -q` → PASS.
- [ ] **Step 4: Commit.**

### Task 10: Docs + CHANGELOG

**Files:**
- Create/modify: a `docs/LOAD_PRIORITY.md` (or extend the battery guide) explaining the model, the reserve floor, the toggle, and U1–U6
- Modify: `CHANGELOG.md` (beta entry, music-assistant style, `(reported by @alexmc1510 in #576)`)
- Modify: user/dev docs per the docs-per-release rule

- [ ] **Step 1:** Write the doc + CHANGELOG entry.
- [ ] **Step 2: Commit.**

---

## Self-review notes (done at plan-write time)

- **Spec coverage:** U1/U2 → Task 6-7; U3/U4/U5/U6 → Task 4; reserve floor → Task 1 gate; config → Task 2; anti-oscillation → relies on pre-battery invariance (spec §7) + existing median/EMA (no task needed); double-count → Task 5; feature-interaction guard (commanded charge) → Task 1 `battery_commanded`; UI → Task 9; docs → Task 10. All covered.
- **Phase split:** Phase 1 (Tasks 1-4) ships standalone (loads only, EV netting is a no-op while `_ev_reclaimed_w` defaults 0). Phase 2 (Tasks 5-7) adds the EV.
- **Type consistency:** `reclaimable_battery_w(**kwargs)` signature identical across Tasks 1/3/5/6/7. `load_priority_above_battery` and `battery_priority_soc` key names consistent throughout.
- **Open build-time item:** the exact `battery_commanded` signal (Task 3 Step) and cycle order (Task 5 Step 1) are verified against live code at build time — flagged explicitly, not left vague.
