# Plan — Unify the three EV-budget calculations (#282 followup)

## Context

**Why now.** Tonight a user-reported PROD bug ("why is HA-PROD charging?")
opened a deeper inconsistency: the SEM coordinator has **three separate
"EV budget" calculations**, and they can — and routinely do — disagree.
Commit `1a9b3c9` installs a sensor-level guard that demotes the user-facing
label when the disagreement would otherwise show "Charging active" on a
non-charging car. That fix is honest about being cosmetic: the underlying
inconsistency is still there, and it will produce different bug shapes
the next time the gap widens.

This plan unifies the three paths into one source of truth.

**The three paths (today, on `develop`):**

| # | Where | Formula | Consumed by |
|---|---|---|---|
| **B1** | `coordinator.py:898` `available_power` | `max(0, solar − home − batt_charge) + batt_discharge_if_positive` | published as `sensor.sem_available_power`; published as `sensor.sem_calculated_current` (after `÷ 690`); passed to `_build_charging_context` and silently ignored there |
| **B2** | `coordinator.py:2589` `ev_budget` (in `_build_charging_context`) | `solar_only`: `max(0, solar − home − batt_charge) + battery_redirect`<br>`legacy`: `ev_power + grid_export + battery_redirect` | `ctx.available_power`; `ctx.calculated_current` (after `÷ 690`); fed to the **state machine**; fed to the **deadline/tariff plan** |
| **B3** | `ev_control.py:440-452` `budget_w` (in `_execute_ev_control`) | `auto`/`self_consumption`: `solar − home − (batt_charge if SOC < auto_start)` <br> `now`: `max_current * phases * voltage` <br> other: `_calculate_solar_ev_budget(state, power, context)` | the **actuator** (passed to `ev.set_current`) |

**Live evidence** captured in the session that birthed this plan: with
`solar=2025 W`, `home=100 W`, `batt_charge=1900 W`, `batt_soc=36 %`:

- B1: `available_power = max(0, 25) + 0 = 25 W` → `calculated_current = 0`.
- B2: `ev_budget = max(0, 25) + redirect`. If `redirect > 0`, this can
  be ~3 A in the state machine's view → state machine returns
  `SOLAR_CHARGING_ACTIVE`.
- B3: `budget_w = solar − home − batt_charge = 25 W` (SOC < 90 auto_start)
  → 0 A to the charger.

**Net.** State machine: "we are actively charging." Actuator: "do not
charge." Display: was showing "Charging active" until the guard in
`1a9b3c9` started demoting it.

**What we agreed.** Don't paper over this any further. There must be
one place that decides "the EV's budget right now is X watts" and the
state machine, the published sensors, and the actuator all read from
the same place.

**Intended outcome.** A single method on `FlowCalculator` returns a
canonical `EVBudget` value, all three consumers use it, and the
`charging_state` demotion guard in the sensor becomes redundant (can
be removed). At least two new scenario-harness scenarios exercise the
old disagreement regime to prove the unification holds across the
shapes that used to diverge.

---

## Approach

### Phase A — Define the canonical budget

**Goal.** One method returns one value. Everybody else reads it.

**Files to create / modify:**

- `coordinator/flow_calculator.py` — add:

  ```python
  @dataclass
  class EVBudget:
      """Single source of truth for what the EV is allowed to draw.

      All three former callers (sensor publish, state machine, actuator)
      read from instances of this. The decomposition exists so callers
      can introspect without re-deriving:

      - solar_surplus: max(0, solar - home - batt_charge). Always the
        "free" part — what solar could deliver without battery help.
      - battery_redirect: how much battery-charge power can be diverted
        to EV (forecast/SOC aware). 0 when the battery still needs it.
      - battery_assist:  how much the battery can actively discharge
        TO the EV when strategy=battery_assist (Zone 4).
      - net_w:           solar_surplus + battery_redirect + battery_assist,
                         clamped to >= 0. This is what flows to the EV.
      - current_a:       net_w expressed as charger current (floor, never
                         round-to-nearest — round-to-nearest was the source
                         of the 0.5 A grid-leak boundary issue, fixed in
                         calculate_charging_current's round_down path).
      """
      solar_surplus: float
      battery_redirect: float
      battery_assist: float
      net_w: float
      current_a: int
      strategy: str  # the strategy this budget was computed for

  def calculate_canonical_ev_budget(
      self,
      power: PowerReadings,
      strategy: str,
      battery_soc: float,
      battery_capacity_kwh: float,
      forecast_remaining_kwh: float = 0,
      voltage: float = 230,
      phases: int = 3,
  ) -> EVBudget:
      """The one method. Strategy-aware. Replaces all three legacy paths."""
  ```

  The method body is essentially today's `calculate_ev_budget` body
  rewritten to return the decomposed dataclass and to honour the
  `battery_assist` semantics that today's `_execute_ev_control` reaches
  for in a fourth, undocumented place. It is `solar_only`-by-default
  with explicit strategy gating; the legacy `ev_power + grid_export`
  base is dropped (it was the surplus-leak root, already eliminated in
  the `solar_only=True` path by commit `591956f`).

- `coordinator/flow_calculator.py` — mark `calculate_ev_budget`,
  `calculate_available_power`, and `calculate_charging_current` as
  legacy via docstring + `@deprecated`-style log warning the first time
  each is called. Keep them callable until Phase D removes the call
  sites, so the change can land in two reviewable commits without
  breaking the world.

### Phase B — Switch the three consumers

**Goal.** Each former budget path reads from `EVBudget` instead.

**Files to modify:**

- **`coordinator/coordinator.py:_async_update_data` (~line 898)** —
  compute the canonical budget once per cycle, BEFORE `_build_charging_context`:

  ```python
  # Step 5.5: Canonical EV budget — single source of truth (#282 followup).
  strategy, reason = self._determine_charging_strategy(power, energy, _primary_cfg)
  ev_budget = self._flow_calculator.calculate_canonical_ev_budget(
      power, strategy=strategy, battery_soc=power.battery_soc,
      battery_capacity_kwh=self.battery_capacity_kwh,
      forecast_remaining_kwh=self._cycle_forecast_remaining_kwh(),
  )
  self._cycle_ev_budget = ev_budget  # available to ev_control via the coordinator ref
  ```

  Publish via SEMData:
  - `sensor.sem_available_power` ← `ev_budget.net_w`
  - `sensor.sem_calculated_current` ← `ev_budget.current_a`
  - new diagnostic: `sensor.sem_ev_budget_solar` ← `ev_budget.solar_surplus`
  - new diagnostic: `sensor.sem_ev_budget_redirect` ← `ev_budget.battery_redirect`
  - new diagnostic: `sensor.sem_ev_budget_assist` ← `ev_budget.battery_assist`

  The diagnostic sensors are the key: future "where did this watt
  come from" questions become "look at the three sensors."

- **`coordinator/coordinator.py:_build_charging_context`** — replace the
  duplicate `calculate_ev_budget` + `calculate_charging_current` call
  pair with `self._cycle_ev_budget`. `ctx.calculated_current = ev_budget.current_a`,
  `ctx.available_power = ev_budget.net_w`. The unused `available_power`
  and `calculated_current` parameters into this method come out (dead
  code since #245).

- **`coordinator/ev_control.py:_execute_ev_control`** — replace the
  ad-hoc `budget_w` computation in lines 440-452 with the canonical
  value. The `now` mode still overrides to `max_current * phases * voltage`
  (that's a user-asked override, not a calculation disagreement); same
  for `SOLAR_MIN_PV`'s floor at `min_power_threshold`. These overrides
  go into the canonical method as explicit strategy clauses, not
  scattered as caller-local branches:

  ```python
  if strategy == "now":
      net_w = max_current * phases * voltage
  elif strategy == "min_pv":
      net_w = max(min_power_threshold, raw_surplus_w)
  ```

  so even the override is visible in the same place as the rest of
  the logic.

### Phase C — Lock the unification with scenario tests

**Goal.** Two scenarios exercise the regimes that used to diverge.

**Files to create:**

- `tests/scenarios/2026-05-29_budget_unify_redirect.yaml` — the regime
  from tonight's evidence: `solar=2025`, `home=100`, `batt_charge=1900`,
  `batt_soc=36`, forecast `remaining=30 kWh`. Pre-fix B2 says current=3,
  B3 says current=0. Post-fix `ev_budget.current_a == 0` AND
  `ctx.calculated_current == ev_budget.current_a` AND the actuator gets
  the same number. The scenario `expect` block asserts all three equal.

- `tests/scenarios/2026-05-29_budget_unify_battery_assist.yaml` — Zone 4
  (`batt_soc < battery_assist_floor`): `solar=800`, `home=600`,
  `batt_soc=58`, `batt_discharging`. Pre-fix B3 returns `200 W` (solar−home),
  B2 returns `200 + battery_assist`. The fact that B3 ignores
  `battery_assist` was a separate latent bug — never reported, never
  caught, but visible the moment you put them side-by-side. Scenario
  asserts both agree on the assist-inclusive total.

- `tests/live/test_budget_agreement.sh` — a sentinel: at any moment, read
  the three diagnostic sensors (`ev_budget_solar`, `ev_budget_redirect`,
  `ev_budget_assist`), sum them, compare against `sem_available_power`,
  assert equality (within 1 W rounding). If this fails, the budget is
  being computed twice somewhere again. The test is cheap and exists
  forever to catch regressions.

### Phase D — Remove the legacy paths

**Goal.** Delete the dead code.

**Files to modify:**

- `coordinator/flow_calculator.py` — remove `calculate_ev_budget`,
  `calculate_available_power`, `calculate_charging_current`. The
  deprecation warnings from Phase A make any forgotten call site loud.

- `sensor.py` — remove the `_format_charging_state` demotion guard
  installed in `1a9b3c9`. The state machine and the actuator now agree,
  so the guard is dead code. Leave a comment pointing at this plan as
  the unification record.

- `coordinator/coordinator.py:_build_charging_context` — drop the
  `available_power` and `calculated_current` parameters from the
  signature (they were already dead).

- `tests/live/test_charging_state_consistency.sh` — keep, because
  defence-in-depth, but loosen the SKIP heuristic (since the invariant
  it tests is now guaranteed by construction, not by the demotion guard).

---

## Files

| File | Change | Why |
|---|---|---|
| `coordinator/flow_calculator.py` | new method + `EVBudget` dataclass; deprecation warnings on legacy methods (A); remove legacy methods (D) | The single source of truth |
| `coordinator/coordinator.py` | compute canonical budget pre-context; publish decomposed sensors; drop dead params (B, D) | Sensor publish path uses the canonical value |
| `coordinator/ev_control.py` | replace `budget_w` derivation with the canonical value; document overrides explicitly (B) | Actuator uses the canonical value |
| `sensor.py` | new diagnostic sensor descriptions; remove the demotion guard at end (B, D) | New sensors visible; old hack gone |
| `tests/scenarios/2026-05-29_budget_unify_redirect.yaml` | new | Locks redirect regime |
| `tests/scenarios/2026-05-29_budget_unify_battery_assist.yaml` | new | Locks battery_assist regime |
| `tests/live/test_budget_agreement.sh` | new | Forever sentinel against re-divergence |

No other files. Dashboard, translations, manifest, deploy scripts: all
untouched.

---

## Verification

1. **Scenario harness** — both new scenarios pass; Scenario 0 still
   passes (the original surplus-leak regression).
2. **Unit tests** — full `pytest` suite passes (`2022/2023` pre-existing,
   plus the new path's tests). The `_build_charging_context` signature
   change touches `tests/test_coordinator.py:test_async_update_config`'s
   surroundings; expect 1-2 fixture updates.
3. **Live tests** — full `tests/live/` suite passes on HA-TEST including
   the new `test_budget_agreement.sh`. The `test_charging_state_consistency`
   test continues to pass (now by construction, not by demotion).
4. **PROD soak** — after deploy, watch `flow_grid_to_ev_power` for 24 h
   across at least one EV plug-in. Pre-unification, this could spike
   above 200 W under solar_only because B3 disagreed with B2. Post-
   unification, the new sentinel test guarantees it can't.

---

## Deferred (won't do here, but adjacent)

- The strategy-zone naming sprawl (`solar_only` vs `self_consumption`
  vs `min_pv` etc. — see the live trace's `auto (ratio=6.3→self_consumption)`
  → published as `solar_only`). The strategy reason and the strategy
  value disagree on terminology. Separate plan.
- Trace recorder on PROD (opt-in NDJSON dump per cycle). Originally
  deferred in the surplus-leak plan; still deferred. When this lands,
  it'll consume the canonical `EVBudget` cleanly.
- The PROD "auto-disable Keba at 07:00" behaviour (already documented
  as intentional in CLAUDE.md). Not in scope here.

---

## Risk assessment

- **Touches the critical control loop.** The actuator branch in
  `ev_control.py` is the most consequential. Mitigation: do Phase A + B
  with deprecation logging, run the scenario harness on every regime,
  soak on HA-TEST overnight, soak on PROD across one plug-in window
  before Phase D removes the legacy paths.
- **B2 → B1 means the published sensor goes from "raw surplus" to
  "budget including redirect."** That's a visible change for users
  reading `sensor.sem_available_power` directly in their automations.
  Mitigation: the three new diagnostic sensors expose the components,
  and a CHANGELOG entry calls it out.
- **`battery_assist` arithmetic.** If any consumer was implicitly
  assuming `available_power` excludes battery discharge, unifying
  could change behaviour in Zone 4. Mitigation: scenarios cover this
  regime; no Zone 4 user complaints in the issue tracker today.
