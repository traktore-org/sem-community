# Load Priority Above Battery Charging (#576) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let high-priority loads and the EV consume solar that would otherwise charge the home battery, above the reserve zone — the Victron-style "loads before battery" priority from #576.

**Architecture:** One gated quantity — *reclaimable battery-charge power* — is added to the surplus figure that two **already-parallel** control paths consume: the `SurplusController` (generic loads) and the EV budget. The two paths are **not merged**; the EV's control stack is untouched. An ordering guard prevents within-cycle double-counting. The battery is never commanded — the inverter self-consumes the residual.

**Tech Stack:** Python 3.12+, Home Assistant custom integration, pytest (`-n 4` via pytest-xdist). Design spec: `docs/superpowers/specs/2026-07-10-load-priority-above-battery-design.md`.

**Parked:** build after the v1.7.4 stable cut. ~~Opt-in, default OFF.~~ Superseded:
the opt-in toggle was dropped — the concept is *device priority*, the battery is a
draggable sink in the one priority list. See the Clear Path below.

---

## CLEAR PATH (updated 2026-07-11) — supersedes the task bodies below where they conflict

**The whole point of #576:** one device-priority list, and where a device sits in it
decides how the solar surplus is shared — including the power that would otherwise
charge the home battery. The battery is a draggable **sink**; a device **above** it
reclaims that charge power, a device **below** it yields. Gated only by the reserve
floor (`battery_priority_soc`) and the commanded-charge guard. No toggle.

### Implementation architecture — build it via the 3-layer arc (decided — Guido 2026-07-11)

Implement #576 through the **management → process → integration** layered arc
(`coordinator/cycle_trace.py`, 1.7.5-beta.1). Each device in the priority list is a
`subsystem(key)` in the per-cycle `CycleTrace`, and its control is structured as the three
layers — so the whole allocation is self-explaining and gets the layer-mismatch health
signal for free:

- **Management** (what policy wanted): the device's **list position**, above/below the
  battery slot, reserve-zone state (SOC vs `battery_priority_soc`), battery mode, EV mode,
  its device mode (off/peak_only/surplus) + goal. `status`: `blocked` when a gate stops it.
- **Process** (what SEM decided + why): the `reclaim_w` and this device's **share** of the
  pre-battery surplus at its position, the allocated W, the `reason`. `status`: `idle` when
  surplus < its min, `ok` when it gets a share.
- **Integration** (what it commanded + observed): the setpoint (switch on / current A /
  battery charge-limit) vs the **observed** draw; `data["match"]` drives `has_mismatch`.

This makes the priority walk debuggable top-down ("why didn't the pump run? management:
below the battery, process: idle") and folds directly into the "all devices" observability
and the Today's-Plan feature. **Every build step below emits its layer records**; the trace
is read-only and never changes a decision. See
`docs/superpowers/specs/2026-07-11-sem-layered-trace-observability-design.md`.

### Where we are

- **Phase 1 — loads ↔ battery: BUILT** (branch `release/1.7.5-beta.1`, at `1.7.5-beta.2`).
  Pivoted from the original opt-in toggle to the battery-as-draggable-device model
  (`energy_reclaim.reclaimable_battery_w` + `SurplusController` reclaim/hand-back at the
  battery's slot + `device_registry` virtual battery row). Delivers U3/U4/U5/U6.
- **Phase 2 — EV ↔ battery/loads: NOT built. THIS IS THE KEY, not an optional follow-up.**
  Today the EV row is *in* the draggable list but its position is **inert**: the drag
  writes a dead `_priority_overrides[ev_id]` key while the EV budget reads
  `config.ev_surplus_priority`, and the EV's battery-charge reclaim is gated on
  `auto_start_soc` (90 % cliff), not on its list slot vs the battery. So the list makes a
  promise the backend ignores for the EV — the headline case (4 kW / 85 % SOC / car at 0 W).

### Step 0 — verify what's actually built (do LATER, before merge, not now)

The Phase-1 pivot diverged from the task bodies below and lacks a live-test record for
the battery-as-device UI. Before this ships: full suite green; live HA-TEST U3/U4/U6 with
the battery row rendering + drag persisting; confirm `battery_commanded` covers the
*scheduled* night charge (not just force_charge/force_discharge) or U6 leaks.

### Step 1 — P2.1 the device list is the SINGLE priority axis (retire multi-charger priority)

**Decision (Guido, 2026-07-11): put every EV charger in the device list and use its list
position as the priority — instead of the separate `ev_surplus_priority` knob.** One
draggable list (loads + every charger + battery) is the one true ordering. This subsumes
"unify the store" and goes further — it retires the parallel multi-charger priority as a
user-facing concept.

- **`_priority_overrides` becomes authoritative** for loads, the battery, AND each EV
  charger. The coordinator reads `registry.priority_for(charger_id)` instead of
  `config.ev_surplus_priority`.
- **`distribute_ev_budget`** (multi-charger cascade) sorts chargers by their **list
  position**, not `charger.priority` from config. Same cascade, one ordering source.
- **`ev_surplus_priority` → seed/default only.** On upgrade, seed each charger's list
  position from its current `ev_surplus_priority` so behaviour is byte-identical, then the
  list is authoritative. Needs a clean migration (config schema bump).
- **`ev_shed_priority` (#470) is RETIRED (decided).** No separate shed knob — shed order is
  simply the **reverse of the list** (LIFO, latest-to-charge sheds first), exactly like the
  loads' existing LIFO deactivation pass. One list order drives both charge order and shed
  order (its reverse). The #470 surplus/shed split collapses back into a single ordering.
  (The per-device peak-shaving `control_mode` off/peak_only/surplus from #470 is a separate
  concept and stays.) Update/remove the #470 shed-priority tests accordingly.
- **Boundary:** this shares the priority *number*, not the control stack. Chargers keep
  their EVBudget / state-machine / reconciler; the list is a shared *ordering* consumed by
  both the loads walk and the EV distribution — NOT a merge into `SurplusController.update()`.

**UI de-dup (decided):** RETIRE the Config-tab EV priority steppers (#514) — the drag list
is the single editor for priority. Confirm each charger row already drag-persists per-charger.

### Step 2 — P2.2 position-based reclaim gate (`decide.py`)

Replace the EV's `auto_start_soc` (90 %) redirect gate with the reserve-floor + position
rule, identical to the loads:

> reclaim battery-charge power to the EV **iff** `soc ≥ battery_priority_soc`
> **and** `ev_priority < battery_priority`.

Below the reserve zone → battery first (Zone 1, unchanged). A careful modification of the
battle-tested `battery_redirect_w`, **not** a second parallel reclaim (double-count).

**The two-mechanism reconciliation (discovered at build, 2026-07-11 — the crux):** the EV
surplus is built from TWO reclaim sources that must not double-count:
1. `self_consumption_surplus_w` (decide.py:103, ALL modes) subtracts `battery_charge_w`
   **iff `soc < auto_start_soc`** — the subtract-skip *is* the reclaim above 90%.
2. `SolarOnlyMode._decide_day` (decide.py:440) ADDS `battery_redirect_w` (forecast-scaled)
   **on top** of bare surplus — solar_only only.
Above ~80–90% both fire on the same watts (a latent overlap). Root-cause rule to replace
both with ONE position-based gate:
- Pure predicate `ev_reclaims_battery_charge(soc, priority_soc, ev_priority,
  battery_priority, battery_commanded)` — **BUILT + 7 tests green** (`energy_reclaim.py`).
- In `self_consumption_surplus_w`: subtract `battery_charge_w` **iff NOT `ev_reclaims`**
  (was `soc < auto_start_soc`). When reclaiming, bare surplus already carries the full
  battery-charge.
- In `SolarOnlyMode._decide_day`: `redirect_w = 0 when ev_reclaims else _redirect(...)` —
  so the forecast redirect only acts as the fallback when the position rule does NOT
  reclaim (EV below battery / below reserve). Prevents the double-count.
- **Scenario tests** (`2026-05-29_budget_unify_redirect.yaml`, `test_scenarios.py`
  `_XFAIL_DRIFT`) pin the OLD auto_start redirect values — they encode the superseded 90%
  behaviour. With the default order (EV above battery) the new rule is strictly MORE
  generous, so these get **updated to the new expected budgets** (root-cause, not worked
  around) — run them and re-pin deliberately.

**Wiring (view fields to add):** `f.priority_soc` already exists (= reserve floor).
Add `ev_priority` to `ChargerView` (per-charger, from `registry.priority_for(cid)`),
`battery_priority` + `battery_commanded` to `FleetView` (from
`registry.battery_surplus_priority()` and the battery decision intent). Set in
`_build_fleet_cycle_state`. Below the reserve zone → battery first (Zone 1, unchanged);
solar_only / min_plus_solar mechanics unchanged when the EV sits below the battery (only
the reclaim amount follows the new rule, which is the feature).

### Step 3 — P2.3 double-count coordination

The unified integer order (loads + EV + battery) **is** the ordering. When the EV and a
load both sit above the battery, walk in list order and share the one `reclaim_w`. Net the
EV's taken share out of the loads walk (`_ev_reclaimed_w`) — OR rely on the §7 cross-cycle
convergence if the rig shows the transient is negligible. **Decide with a live U2-with-a-
load-above-the-EV test, not by assertion.**

### Step 4 — acceptance (live HA-TEST, pre-merge)

- Drag EV **above** battery, SOC 85 %, ~7 kW solar, car connected → **car charges, battery
  takes the residual** (U2, the core win).
- Drag EV **below** battery → battery charges first, car waits.
- SOC < `battery_priority_soc` → battery first regardless of position (U4).
- Toggle-free — position is the only control.

### Default order & battery representation (decided with Guido 2026-07-11)

- **Default seed order: EV chargers → home battery → loads.** REVERSES the current Phase-1
  default (battery seeded at bottom, prio 100). Rationale: clearest mental model for new
  users, and **safe on upgrade** — existing users' battery keeps charging before their
  loads; "loads before battery" (the reporter's Victron ask) becomes **opt-in by dragging
  a load above the battery**, not a silent default-on behaviour change. Still safe against
  EV-hogs-all-solar because the reserve floor overrides order: below `battery_priority_soc`
  the battery fills to the zone first, then the EV wins above it. Build task: change the
  default seed so the battery slots just below the EV charger(s), loads below the battery.
- **One battery row per inverter (aggregate), never per module.** Two batteries on one
  inverter = ONE row — the list models the inverter-as-sink; packs fill together so their
  split is irrelevant to priority. Already consistent: the virtual row reads the aggregate
  `sensor.sem_battery_charge_power` / `sensor.sem_battery_soc` (SEM sums multi-battery
  installs upstream). No per-module rows.

### All controllable devices are first-class active participants (decided — Guido 2026-07-11)

The single priority list governs **every** controllable device with an **active role** —
not just the EV charger(s) and the battery. In scope, all in the one list, all allocated
surplus by list position (and all subject to the same battery-reclaim rule above the zone):

- EV charger(s) — modulating, own control stack (shared ordering only).
- Home battery — the sink (one row per inverter).
- Generic switches / pumps / heaters — discrete `SwitchDevice`.
- Modulating loads — `CurrentControlDevice`.
- Climate / AC — `ClimateDevice` (#569).
- Heat pump (SG-Ready) and hot water — today partly steered by the #508 W2 peak-aware
  path / their own controllers; they must become **positioned active participants** in the
  same walk, not a side channel.

**Requirement:** every device type appears as a draggable row (drag-persisted position) and
the surplus walk — including the reclaimed battery-charge power above the reserve zone —
allocates to it strictly by its list position. No device type is special-cased out of the
ordering (the EV/HP/HW keep their own *actuators*, but consume the *shared ordering*). This
is the generic-device arc's uniformity goal made concrete — see
[[project_generic_device_arc]].

**No double-add (Guido 2026-07-11 — critical):** if a device is ALREADY in the list —
auto-discovered from the Energy Dashboard, service-registered, or manually mapped as a
generic pump/switch — the HP/HW/climate integration must **not** add a second row or a
second controller for the same physical device (two controllers on one entity WILL fight).
Dedup by the underlying control entity (and power/energy sensor) — **reuse/extend the
existing machinery**: `_drop_discovered_duplicates`, the `_service_registrations`
entity-suppression in `_sync_to_surplus_controller` / `get_devices_for_sensor`. A heat pump
a user already mapped as a "pump" stays ONE row (its native HP behaviour attaches to the
existing row, it is not re-added). Add a regression test for the "already mapped as pump"
collision.

**Build task:** audit each device type's current path (esp. HP/HW SG-Ready and the W2 peak
path) and route its surplus claim through the list position; enforce the no-double-add
dedup; add a per-type acceptance case + the collision regression test.

### Extend "Today's Plan" to all devices (decided — Guido 2026-07-11)

The **Today's Plan** timeline (`coordinator/today_plan.py`, #282/#298 → `sensor.sem_charging_
state.attributes.today_plan` → `sem-today-plan-card`) already shows, forward-looking, **when
the home battery will be charged (full ETA) or drained (empty ETA)** and the EV rows
(charge-start / Min / target / deadline / wait) plus the tariff / solar-peak / night
transitions. **Guido wants the same "when will it be active" projection for the OTHER
surplus devices** — pool pump, heat pump, hot water, climate, generic loads.

**Requirement:** the plan composer emits forward-looking rows per surplus device — e.g.
"pool pump runs ~12:00", "heat pump boost 13:00–14:00", "hot water reaches target ~11:30" —
projected from the **solar forecast + the device's list position + its goal (daily_min_
runtime / stop condition) + tariff**. A device higher in the list gets surplus earlier / for
longer, so the plan is the *visible consequence* of the priority ordering across the day —
the natural companion to the #576 list.

- New `KIND_*` row kinds per device (e.g. `device_run_start` / `device_target_reached`),
  values carry the device name; card maps to icon/color + `semLocalize` labels ×15.
- Projection reuses the surplus forecast the battery/EV ETAs already use; ordering follows
  the same list position (Step 1). Cap stays glanceable (today: 8 rows) — dedupe/summarise
  when many devices qualify (log what's dropped, don't silently truncate).
- Observability feature — **read-only, no control change.** Distinct from the priority
  mechanics (Steps 1–3) but shares the ordering + surplus forecast.

**Build task (own step):** extend `compose_today_plan` inputs with a per-device projected
active window; wire the coordinator to compute it from forecast + position + goal; add
kinds + translations + card rendering; unit-test the composer per device type.

### Interaction rules (confirmed with Guido 2026-07-11 — build + test as acceptance cases)

Layered gate order: **battery reserve zone → list position → EV mode.**

- **Greedy top priority (U7).** A modulating device (EV) at the top of the list takes the
  surplus **first**, up to whatever it draws — even 11 kW. Everything below it (pumps,
  battery) sees only the remainder. To protect lower loads, the user **drags the EV down**.
  The list order is the only control — no fair-share carve-out.
- **EV mode is orthogonal to the list (U8).** List = *where* the EV sits in the queue;
  mode = *if/how* it charges within its slot:
  - `solar_only` — pure solar surplus, no grid, no battery-assist min. Off if the surplus
    reaching it < its start minimum (Case 1: 5 kW < ~5.5 kW → off).
  - `min_plus_solar` — **daytime**: minimum topped up by **battery discharge support**
    (#537 battery-assist), gated by battery **≥ reserve zone**; **never grid during the
    day**. Plus solar on top. (Grid-for-min is overnight charging only — out of scope here.)
- **Reserve zone is the absolute override.** Below `battery_priority_soc` the battery jumps
  to the top (charges first) regardless of drag position; and it will **not** discharge to
  assist an EV. The one reserve floor governs both directions (yield-charge above / protect
  below; assist-discharge above / protect below).

### Battery mode → position (upgrades the U6 guard)

The battery mode can override the dragged position. Full mapping (replaces the old
"commanded charge = no reclaim" U6 with the complete picture):

| Battery mode | Effect on the priority list |
|---|---|
| `auto` / `self_consumption`, SOC **≥** reserve zone | passive sink → **dragged position governs** |
| `auto` / `self_consumption`, SOC **<** reserve zone | **jumps to the top** — reserve-floor override |
| `force_charge` | **jumps to the top** — commanded charge gets solar first; loads/EV yield |
| `force_discharge` / `arbitrage` | **leaves the charging walk** — it's a source, not drawing; position irrelevant, nothing to reclaim |

Rule: **commanded-to-charge → top; commanded-to-discharge → out of the walk; passive →
dragged position** (with the reserve floor as the absolute top-override). The battery row
should reflect this — show **"charging first"** / **"discharging — feeding"** instead of a
position number when a mode/floor makes the drag moot, so the user sees why. `reclaimable_
battery_w`'s `battery_commanded` guard is extended to this full mapping (charge-commands →
reclaim 0 AND battery-to-top; discharge-commands → battery out of the surplus walk).

Worked example (6 kW solar, 1 kW house; list = EV(prio1, 8A/~5.5 kW min) → pump1(1.5 kW) →
pump2(1.5 kW) → battery):
- **5 kW surplus:** EV can't start (< 5.5 kW, `solar_only`) → pump1 on, pump2 on → battery 2 kW.
- **7 kW surplus:** EV starts and ramps greedily → pumps/battery get only what the EV leaves.

### Step 5 — docs + CHANGELOG + close the loop on #576

Update `docs/LOAD_PRIORITY.md` (EV now honours its slot), CHANGELOG (beta entry), and post
the resolved plan to #576.

### Open decisions (carry into build)

1. **Single priority axis — ALL DECIDED (Guido 2026-07-11):** device-list position replaces
   `ev_surplus_priority`.
   - ✅ **Migration** — seed each charger's list position from its current
     `ev_surplus_priority` on upgrade (config schema bump); byte-identical behaviour after.
   - ✅ **`ev_shed_priority` (#470) retired** — shed = reverse list position (LIFO), no knob.
   - ✅ **Config-tab EV priority steppers (#514) retired** — drag list is the only editor.
2. Confirm `battery_commanded` includes the scheduled night charge (Step 0).

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

## PHASE 2 — EV (DEFERRED — re-spec needed)

> **2026-07-11:** Tasks 5–7 below assumed `excess_solar` (coordinator ~4601)
> drives the EV budget. It does **not** — it only feeds a debug log (ruflo
> review B1). The real EV surplus is `decide.py:self_consumption_surplus_w`,
> which already reclaims battery charge above `auto_start_soc` and adds
> `flow_calculator.battery_redirect_w` in `solar_only`. Phase 2 must instead
> **raise that existing redirect to full above `battery_priority_soc` when the
> toggle is on** (not add a second reclaim — that double-counts). Tasks 5–7 as
> written are void; Phase 2 needs its own design pass. **Phase 1 (Tasks 1–4,
> 9–10) shipped standalone.**

## PHASE 2 — EV (careful, NOT a merge) — ORIGINAL PLAN (void, see note above)

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
