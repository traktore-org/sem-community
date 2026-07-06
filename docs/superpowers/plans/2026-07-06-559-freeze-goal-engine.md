# #559 Freeze Goal Engine to Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Revert the beta.18 surplus-load "goal engine" over-build to its grounded core — delete the speculative energy-target / max-cap / deadline surface (which carries both HIGH bugs), fix the `rated_power` footgun, and simplify the device card to the EV-charger reference pattern.

**Architecture:** Surgical deletion. Keep the pre-#559 "Feature 2 daily runtime" mechanism (`daily_min_runtime_sec`, `needs_offpeak_activation`, off-peak pass, `top_up_policy` ∈ {solar_only, cheap_hours}) because the heat-pump and hot-water controllers depend on it. Delete only #559's HW/HP-independent additions: energy targets, max caps, the deadline-critical pass, and `top_up_policy=always`. Card surfaces only mode + hours target + stop-condition.

**Tech Stack:** Python 3.12 (HA custom integration), LitElement cards (Rollup bundle), pytest via the `/tmp/ha-config` namespaced layout.

**Spec:** `docs/superpowers/specs/2026-07-06-559-freeze-goal-engine-design.md`

**Test runner (used in every task):**
```bash
rsync -a --delete --exclude=.git --exclude=node_modules ./ /tmp/ha-config/custom_components/solar_energy_management/
cd /tmp/ha-config && PYTHONPATH=/tmp/ha-config python3.12 -m pytest custom_components/solar_energy_management/tests/test_559_goal_engine.py -q
```

---

### Task 1: Delete energy targets + runtime/energy max caps from the goal model

Removes HIGH-1 (un-persisted `daily_max_runtime_sec` cap). These fields have no HW/HP consumer.

**Files:**
- Modify: `devices/base.py` (goal-model block ~168-179, props ~330-359, `update_daily_runtime` ~301-307)
- Modify: `coordinator/surplus_controller.py` (skip-guards referencing the deleted `*_reached` props)
- Modify: `features/device_registry.py:192-220,657-664` (goal apply/serialize)
- Modify: `__init__.py:2726-2767,3133-3203` (service prop list + schema)
- Modify: `services.yaml` (register_surplus_device fields)
- Test: `tests/test_559_goal_engine.py`

- [ ] **Step 1: Write/adjust failing tests** — assert the deleted surface is gone and the core still works.

```python
# tests/test_559_goal_engine.py — add
def test_energy_and_max_cap_fields_removed():
    from custom_components.solar_energy_management.devices.base import SwitchDevice
    d = SwitchDevice(hass=None, device_id="x", name="X", rated_power=2300)
    for attr in ("daily_max_runtime_sec", "daily_target_energy_kwh",
                 "daily_max_energy_kwh", "daily_max_runtime_reached",
                 "daily_max_energy_reached", "deadline_pressure",
                 "target_deadline"):
        assert not hasattr(d, attr), f"{attr} should be deleted"

def test_daily_targets_met_runtime_only():
    from custom_components.solar_energy_management.devices.base import SwitchDevice
    d = SwitchDevice(hass=None, device_id="x", name="X", rated_power=2300)
    d.daily_min_runtime_sec = 3600
    assert d.daily_targets_met is False
    d._daily_runtime_accumulated_sec = 3600
    assert d.daily_targets_met is True
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest .../test_559_goal_engine.py::test_energy_and_max_cap_fields_removed -q`
Expected: FAIL (attrs still present).

- [ ] **Step 3: Delete the fields in `devices/base.py`**

Remove lines 170-173 (`daily_max_runtime_sec`, `daily_target_energy_kwh`, `daily_max_energy_kwh`, `_daily_energy_accumulated_kwh`). In `update_daily_runtime` remove the energy-integration block (the `try/except` computing `watts` and `self._daily_energy_accumulated_kwh += ...`, ~301-307) and the `self._daily_energy_accumulated_kwh = 0.0` reset at line 292. Delete the `daily_max_runtime_reached` (330-335) and `daily_max_energy_reached` (337-343) properties. In `daily_targets_met` (345-359) drop the `energy_open` branch and the `daily_target_energy_kwh` term of `has_target`:

```python
@property
def daily_targets_met(self) -> bool:
    """Runtime minimum target achieved. No target = False."""
    if self.daily_min_runtime_sec <= 0:
        return False
    return self._daily_runtime_accumulated_sec >= self.daily_min_runtime_sec
```

- [ ] **Step 4: Remove references to the deleted `*_reached` props** in `coordinator/surplus_controller.py`. In the off-peak activation pass (~639) change:

```python
if device.daily_max_runtime_reached or device.daily_max_energy_reached or device.stop_condition_met:
    continue
```
to:
```python
if device.stop_condition_met:
    continue
```

- [ ] **Step 5: Trim goal keys in `features/device_registry.py`** — in `_GOAL_KEYS` (192-195) delete `"daily_max_runtime_min"`, `"daily_target_energy_kwh"`, `"daily_max_energy_kwh"`. In the apply block (203-220) delete the `daily_max_runtime_sec`, `daily_target_energy_kwh`, `daily_max_energy_kwh` assignments. In the serialize block (657-664) delete those three keys.

- [ ] **Step 6: Trim service surface** — in `__init__.py` remove `"daily_max_runtime_min"`, `"daily_target_energy_kwh"`, `"daily_max_energy_kwh"` from the prop lists (2726-2728, 2765-2767, 3133-3135) and delete the `vol.Optional("daily_max_runtime_min"…)`, `daily_target_energy_kwh`, `daily_max_energy_kwh` schema entries (3193-3199). In `services.yaml` delete the matching `register_surplus_device`/`update_device_config` fields.

- [ ] **Step 7: Run tests to verify pass**

Run: full test_559 file. Expected: the two new tests PASS; adjust/delete any old tests asserting energy-target/max-cap behavior (they reference deleted attrs).

- [ ] **Step 8: Commit**

```bash
git add devices/base.py coordinator/surplus_controller.py features/device_registry.py __init__.py services.yaml tests/test_559_goal_engine.py
git commit -m "fix(#559): delete energy targets + daily-max caps from goal engine

Removes the un-persisted daily_max_runtime cap (HIGH-1) and the unrequested
energy-target surface. HW/HP-independent. Refs #559"
```

---

### Task 2: Delete the deadline-critical pass and deadline machinery

Removes HIGH-2 (un-gated battery drain) and `top_up_policy=always`.

**Files:**
- Modify: `coordinator/surplus_controller.py:672-720` (the deadline-critical pass)
- Modify: `devices/base.py` (`target_deadline` 174, `_deadline_forced` 185, `_seconds_until_deadline` 376-384, `_goal_now` 386-390, `deadline_pressure` 392-408, `daily_energy_budget_kwh` 410-414, `_solar_only_miss_logged` 176 + its reset 293)
- Test: `tests/test_559_goal_engine.py`

- [ ] **Step 1: Write failing test** — a device past its runtime target near end-of-day must NOT force from grid (no deadline pass left).

```python
async def test_no_deadline_force_pass(monkeypatch):
    # A surplus switch with a runtime deficit and NO solar must stay OFF —
    # there is no deadline/always grid-force path anymore.
    from custom_components.solar_energy_management.coordinator.surplus_controller import SurplusController
    # (use the existing controller test harness in this file; assert the
    # device is never activated when remaining_surplus <= 0 regardless of time)
    ...
    assert device.is_active is False
```

- [ ] **Step 2: Run to verify failure** — FAIL if the deadline pass still activates it. (If the harness makes this hard, assert `not hasattr(device, "deadline_pressure")` as the guard instead.)

- [ ] **Step 3: Delete the deadline-critical pass** in `surplus_controller.py` — the entire `if not peak_freeze:` block commented "(#559) Deadline-critical pass" (from ~672 through the closing of that `for` loop ~720, ending before `# Build allocation data`).

- [ ] **Step 4: Delete deadline machinery in `base.py`** — remove `target_deadline` (174), `_solar_only_miss_logged` (176) and its reset (293), `_deadline_forced` (185), `_seconds_until_deadline` (376-384), `_goal_now` (386-390), `deadline_pressure` (392-408), `daily_energy_budget_kwh` (410-414). Keep `stop_condition_met`.

- [ ] **Step 5: Remove `always` from `top_up_policy`** — in `__init__.py` validation (`prop == "top_up_policy" and str(value) not in (...)`, ~2737) and the schema `vol.Optional("top_up_policy"): vol.In(...)` (~3203) reduce the allowed set to `("solar_only", "cheap_hours")`. Same in `services.yaml`. In `device_registry.py:216-218` the default stays `solar_only`.

- [ ] **Step 6: Run tests** — Expected: PASS; delete old tests referencing `deadline_pressure` / `always` / `target_deadline` (e.g. `test_deadline_force_suppressed_by_peak`, `test_solar_only_deadline_miss_logged_not_forced`).

- [ ] **Step 7: Commit**

```bash
git add coordinator/surplus_controller.py devices/base.py __init__.py services.yaml tests/test_559_goal_engine.py
git commit -m "fix(#559): delete deadline-force pass + always policy (HIGH-2 battery drain)

The deadline-critical pass grid/battery-forced with no SOC gate. Removed with
target_deadline, deadline_pressure and top_up_policy=always. solar_only (default)
and cheap_hours (HW/HP off-peak) remain. Refs #559"
```

---

### Task 3: rated_power auto-calibrate footgun fix

Unknown `rated_power` → default threshold → device switches on at low surplus and imports the deficit. Self-heal from the first observed ON draw.

**Files:**
- Modify: `devices/base.py` (`SwitchDevice`: add calibration in `update_daily_runtime` or a dedicated hook; adjust `min_power_threshold` derivation)
- Test: `tests/test_559_goal_engine.py`

- [ ] **Step 1: Write failing test**

```python
def test_rated_power_autocalibrates_from_observed_draw():
    from custom_components.solar_energy_management.devices.base import SwitchDevice
    hass = _fake_hass_with_power_sensor("sensor.pool_w", 2300)  # helper in file
    d = SwitchDevice(hass=hass, device_id="pool", name="Pool", rated_power=1000,
                     entity_id="switch.pool", power_entity_id="sensor.pool_w")
    d._status.state = DeviceState.ACTIVE
    d.calibrate_rated_power()          # new method, reads power_entity while ON
    assert d.rated_power == 2300
    assert d.min_power_threshold == 2300
```

- [ ] **Step 2: Run to verify failure** — FAIL (`calibrate_rated_power` undefined).

- [ ] **Step 3: Implement `calibrate_rated_power`** on `SwitchDevice`:

```python
def calibrate_rated_power(self) -> None:
    """(#559) Self-heal an unknown rated_power. Auto-discovered switches
    snapshot the power sensor's reading at discovery (often 0 W when off),
    which makes min_power_threshold tiny and imports the deficit. When the
    switch is ON and its power sensor reports a real draw, adopt it as the
    rated power + surplus threshold."""
    if not self.power_entity_id or not self.hass or not self.is_active:
        return
    st = self.hass.states.get(self.power_entity_id)
    if not st or st.state in ("unknown", "unavailable", None):
        return
    try:
        observed = float(st.state)
    except (ValueError, TypeError):
        return
    if observed > self.rated_power:
        _LOGGER.info("%s: calibrated rated_power %.0fW -> %.0fW from %s",
                     self.name, self.rated_power, observed, self.power_entity_id)
        self.rated_power = observed
        self.min_power_threshold = observed
```

Call it once per cycle from `update_daily_runtime` when active (or from the controller loop where devices are iterated). Add the `_fake_hass_with_power_sensor` helper to the test file if absent.

- [ ] **Step 4: Run test** — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add devices/base.py tests/test_559_goal_engine.py
git commit -m "fix(#559): auto-calibrate switch rated_power from observed ON draw

An auto-discovered socket left at default rated_power switched on at ~1kW
surplus and imported the rest. Self-heals from the power sensor's real draw. Refs #559"
```

---

### Task 4: Registry loads stale/removed keys without error

beta.18 persisted devices may carry `daily_max_*`, `target_deadline`, etc. The load path must ignore unknown keys.

**Files:**
- Modify: `features/device_registry.py` (goal apply loop — iterate known keys only, ignore extras)
- Test: `tests/test_559_goal_engine.py`

- [ ] **Step 1: Write failing test**

```python
async def test_loads_goal_with_removed_keys(tmp_registry):
    # a stored goal dict carrying deleted keys must apply cleanly
    goals = {"daily_min_runtime_min": 240, "top_up_policy": "solar_only",
             "daily_max_runtime_min": 120, "target_deadline": "21:00",
             "daily_target_energy_kwh": 5.0, "stop_entity": "", "stop_at": 0}
    dev = _apply_goals(goals)     # must not raise
    assert dev.daily_min_runtime_sec == 240 * 60
```

- [ ] **Step 2: Run to verify failure/regression** — confirm current apply either raises or sets deleted attrs.

- [ ] **Step 3: Make apply key-tolerant** — the apply block already uses `goals.get(...)`; ensure it only touches surviving attributes and never `setattr`s a removed key. If a generic `for k in _GOAL_KEYS: setattr(...)` loop exists, keep it bounded to the trimmed `_GOAL_KEYS`. Add a defensive comment.

- [ ] **Step 4: Run test** — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add features/device_registry.py tests/test_559_goal_engine.py
git commit -m "fix(#559): registry ignores removed goal keys from beta.18-persisted devices. Refs #559"
```

---

### Task 5: Simplify the device card to the EV-charger pattern

**Files:**
- Modify: `dashboard/card/src/cards/sem-load-priority-card.js` (mode strip ~438-467, goal editor ~475-690, unit picker 653-661, hardcoded `min`/`kwh` 658-659, stop_entity text field ~680)
- Modify: `dashboard/translations.json` (remove deleted keys, add per-mode help + hours label; ×15)
- Regenerate: `dashboard/card/sem-localize.js`; rebuild `dashboard/card/dist/sem-cards.js`
- Reference: `dashboard/card/src/cards/sem-ev-status-card.js:681-755`, `docs/UI_PATTERNS.md`
- Mockup (approved): `/tmp/sem-559-mockup.html`

- [ ] **Step 1: Move the mode picker into the goal panel**, above the slider (mirror `charge-target-group`). Gate the whole goal editor render on `control_mode === 'surplus'`.

- [ ] **Step 2: Replace the dual-handle slider + unit picker** with a single "at least" slider labelled in **hours** (`0 = no target`, max 12 h → store `daily_min_runtime_min = hours*60`). Remove the `min`/`kwh` unit picker and the orange "up to" ceiling handle. Remove the deadline row and the `top_up_policy` select from this card.

- [ ] **Step 3: Replace the `stop_entity` free-text field** with an `ha-entity-picker` (or the card's existing entity-select pattern) + numeric value; fix the `sensor.car_soc` placeholder to a generic localized hint.

- [ ] **Step 4: Add the progress bar** (green `#8DC892`) — "X.X h / Y h on solar today" when a runtime target is set; hidden otherwise.

- [ ] **Step 5: Add per-mode help** under the existing `?` toggle (Off / Peak only / Surplus), via `semLocalize` keys (`help_device_mode_off/peak_only/surplus`). Route all remaining literals (incl. the old hardcoded `min`/`kwh`) through `semLocalize`.

- [ ] **Step 6: Update translations + regenerate + build**

```bash
# remove deleted keys, add new keys in dashboard/translations.json (×15),
# then regenerate sem-localize.js and rebuild the bundle:
cd dashboard/card && npm run build
```

- [ ] **Step 7: Card lint + parity tests**

Run: `pytest .../tests/test_card_template_lint.py .../tests/test_translation_parity.py -q`
Expected: PASS (no backticks in lit templates; ×15 parity).

- [ ] **Step 8: Commit**

```bash
git add dashboard/card/src/cards/sem-load-priority-card.js dashboard/card/dist/sem-cards.js dashboard/card/sem-localize.js dashboard/translations.json
git commit -m "feat(ui,#559): simplify surplus-device card to EV-charger pattern

Mode picker in the panel, single hours target, entity-picker stop condition,
per-mode help, progress bar. Removes unit picker, ceiling handle, deadline,
policy select. Refs #559"
```

---

### Task 6: Full suite green + review + deploy + live-verify

- [ ] **Step 1: Run the FULL suite** via the `/tmp/ha-config` layout:

```bash
rsync -a --delete --exclude=.git --exclude=node_modules ./ /tmp/ha-config/custom_components/solar_energy_management/
cd /tmp/ha-config && PYTHONPATH=/tmp/ha-config python3.12 -m pytest custom_components/solar_energy_management/tests/ -q
```
Expected: all green. Fix any FLEET-READ lint / scenario fallout.

- [ ] **Step 2: Reviewer** — run `ruflo-core:reviewer` on the branch diff; fix findings.

- [ ] **Step 3: Deploy to HA-TEST** — `~/bin/deploy-test.sh` (full, since entities/services + card changed), then `~/bin/validate-sem.sh`.

- [ ] **Step 4: Live-verify alex's flow on HA-TEST** — register/adopt a switch as surplus + solar_only; set a 0.1h runtime target; confirm: (a) it switches on only when unallocated surplus ≥ the auto-calibrated draw (force sim surplus up/down); (b) `stop_at` on a sim SOC sensor stops it; (c) no grid-force at night; (d) the card shows mode-in-panel + hours slider + progress. Screenshot the card.

- [ ] **Step 5: Commit any fixes; leave the branch ready for PR.** Do NOT tag/deploy PROD without user say-so (memory: no auto release tags). Update CHANGELOG (beta.19 entry) + `docs/MULTI_DEVICE_GUIDE.md` + `docs/UI_PATTERNS.md`.

```bash
git add -A && git commit -m "chore(#559): CHANGELOG beta.19 + docs for goal-engine freeze. Refs #559"
```

---

## Self-review

- **Spec coverage:** survives-list (mode ladder, min-runtime, solar_only, stop-condition, SurplusAvailability, persistence, dedupe, adopt) untouched ✓; deleted-list (energy, max caps → T1; deadline+always → T2) ✓; footgun (T3); migration/stale-keys (T4); card (T5); tests/deploy (T6). ✓
- **HW/HP constraint honored:** `daily_min_runtime_sec`, `needs_offpeak_activation`, off-peak pass, `top_up_policy` field kept; only `always` removed. ✓
- **Placeholders:** the deadline-pass test harness detail in T2/S1 is marked as "use existing harness" — acceptable (the file has a controller harness); fall back to the `hasattr` guard if wiring is heavy.
- **Type consistency:** `calibrate_rated_power`, `daily_targets_met`, `daily_min_runtime_sec`, `min_power_threshold` used consistently across tasks. ✓
