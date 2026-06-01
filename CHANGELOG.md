# Changelog

All notable changes to SEM are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.6.17] — 2026-06-01

Hotfix release. Single bug fix for #346 — `solar_only` charge mode
was silently importing grid + draining the home battery overnight.

### Fixed

- **EV charges overnight in `charge_mode=solar_only` (#346)** — PROD
  incident 2026-05-31: a KEBA configured with `charge_mode =
  solar_only` drew ~4 kWh from battery + grid between 22:07 → 00:48
  despite solar being 0 W since 21:19. `sensor.sem_charging_state`
  correctly read "Night charging disabled" the entire window, so the
  bug was invisible from the dashboard.

  Root cause: `_determine_charging_strategy` returned `"night_grid"`
  unconditionally when `is_night_mode()` was True, ignoring the
  per-charger `charge_mode`. The named-mode dispatch (`mode ==
  "solar_only"`) only ran in the day branch. The legacy mapper then
  converted `night_grid` → `EVBudgetStrategy.MIN_PV` (≈1380 W floor).
  In parallel `_night_state_machine` correctly returned
  `NIGHT_DISABLED`, but the actuator's terminal branch could not kill
  a session SEM didn't own. Latent since April 2026 — any HACS user
  on `solar_only` mode has been affected.

  Fix is two layers:
  1. **Strategy mode-gate** — consult `MODE_NIGHT_ALLOWED` before the
     `is_night_mode()` branch. `solar_only` at night → `idle`; `off`
     → `disabled`. Other modes unchanged.
  2. **Defence in depth** — extend the #315 self-resume actuator
     guard from `{"disabled"}` to `{"disabled", "idle"}` so future
     strategy disagreements land safely.

  6 new tests in `tests/test_346_solar_only_night.py` pin both
  layers. The pre-existing `test_idle_strategy_does_not_trigger_
  override` (which pinned the OLD restrictive actuator behaviour
  that made this bug possible) was inverted to assert the new
  contract.

## [1.6.14] — 2026-05-31

Multi-charger debt closeout. Bundles four pieces of work into one
release (the maintainer-set rule "no v1.7 until every multi-charger
follow-up is closed" pulled deferred ``v1.7+`` items back into
v1.6.x; this is them, packaged as one release rather than four
separate HACS bumps).

### Fixed

- **Surplus tracker jump-from-0 spike (#8)** —
  ``_apply_ramp_limit`` used to short-circuit on ``current < 1`` and
  return ``target_current`` directly, so a cold-start cycle handed
  KEBA a 14 A command from 0 A. KEBA's ~30 s physical actuator lag
  then caused a ~4.4 kW grid-import overshoot during the ramp
  (confirmed live on PROD 2026-05-31 at 10:43). Cold start now hands
  KEBA ``min_current`` (typically 6 A ≈ 4140 W on 3-phase EU);
  subsequent cycles climb via the existing ``±ramp_rate`` clamp at
  the user-configured ``ev_ramp_rate_amps`` (default 2 A/cycle, so
  target reached in ~4 cycles for a 14 A request). The stop-fast
  branch is preserved: ``target_current < 1`` still returns 0
  immediately so explicit-off / disable stays snappy. 13 new unit
  tests in ``tests/test_ramp_limit_8.py`` pin every branch.

### Changed

- **``effective_state`` and ``charger_name`` migrated onto
  ``PerChargerContext``** instead of writing the parallel
  ``_effective_states_per_charger`` dict from inside the loop body.
  The loop body assigns ``pcc.effective_state = …``; ``__exit__``
  persists ``(state, name)`` into the coordinator's dict so the
  post-loop ``_send_notifications`` dispatcher continues reading
  from a single map. The dict is the storage; pcc is the write
  path. Lets a future AST lint enforce field access at type level
  (no callsite outside the loop touches the dict directly).
- **``this_power_w`` precomputed in ``PerChargerContext.__enter__``**
  via ``coord._this_charger_power(ev_dev, power)`` and exposed as a
  typed field. The coordinator stashes the active pcc on
  ``coord._current_pcc``; ``_this_charger_power`` becomes a cache
  shim — when invoked with the same ``ev_dev`` it returns
  ``pcc.this_power_w`` instead of re-reading HA state. Replaces
  the three per-method ``this_power_w = self._this_charger_power(…)``
  local-var caches in ``coordinator/ev_control.py`` without
  changing the callsites. Helper exceptions in the precompute fall
  through to the legacy read path so a transient HA-state issue
  can't half-apply the swap.

### Added

- ``PerChargerContext.power``, ``this_power_w``, ``effective_state``,
  ``charger_name`` dataclass fields.
- ``SEMCoordinator._current_pcc`` short-lived pointer to the active
  context (``None`` outside any per-charger iteration).
- ``# FLEET-READ:`` annotation on the documented multi-charger
  fallback in ``_this_charger_power`` (only reached when a charger
  config omits ``ev_charging_power_sensor`` — rare).
- 47 new tests across three areas (13 ramp-limit + 14 pcc-field +
  20 per-charger flow):
  - ``tests/test_ramp_limit_8.py``: cold-start, near-zero,
    steady-state ramp, stop-fast, custom ``min_current``,
    end-to-end multi-cycle climb.
  - ``tests/test_per_charger_context.py``: effective_state
    persistence, this_power_w precompute, current-pcc-pointer
    lifecycle.
  - ``tests/test_this_charger_power_cache.py``: cache HIT, three
    MISS variants, kW→W conversion regression from #315.
  - ``tests/test_per_charger_energy_flows.py``: sum invariant,
    multi-cycle accumulation, day rollover, persistence
    round-trip (incl. legacy snapshot back-compat), edge cases
    (charger appears mid-day, charger idle in cycle,
    zero-interval), bad-snapshot defence, sensor-description
    generation gate.

- **Per-charger flow sensors (gated on ``len(ev_chargers) > 1``)**:
  ``sensor.sem_charger_<id>_flow_solar_to_ev_power``,
  ``..._grid_to_ev_power``, ``..._battery_to_ev_power`` (W,
  MEASUREMENT) plus matching ``..._energy`` (kWh, TOTAL, daily-
  reset). The Sankey card + HA Energy dashboard can now show
  per-charger EV sourcing instead of a fleet-proportional split —
  closes the @RienduPre observation on #316. Single-charger setups
  unchanged (fleet ``sensor.sem_flow_*_to_ev_*`` is authoritative).
  - ``ChargerEnergyFlows`` dataclass + ``EnergyFlows.per_charger``
    field.
  - ``FlowCalculator._per_charger_accumulators`` (kWh) integrated
    over time alongside the fleet accumulator; sum invariant
    pinned in tests.
  - Day rollover clears both fleet AND per-charger accumulators.
  - Snapshot persistence round-trip: new ``per_charger`` key
    under the existing snapshot dict; pre-v1.6.15 snapshots
    (without the key) restore bit-for-bit identical.
  - Accumulator semantic: once a charger appears, its kWh stays
    surfaced until the day rollover, even on cycles where the
    charger is idle (the user-visible counter must not regress
    to 0 just because the car unplugs).

- **``FleetEvPower`` newtype + global AST lint (v1.6.16 work)**.
  ``PowerReadings.ev_power`` is now typed as ``FleetEvPower`` — a
  ``float`` subclass that exposes ``.as_fleet_total(reason: str)``.
  Two equivalent ways to acknowledge a fleet read:
  - Comment form (v1.6.8 idiom, still valid):
    ``# FLEET-READ: <reason>`` on the same line or up to 5 lines
    above (walking back through ``#``-comment lines only).
  - Method form (preferred for new code):
    ``power.ev_power.as_fleet_total("<reason>")`` — the reason
    rides in the bytecode (mypy / IDE hover / ``git blame``)
    instead of an adjacent comment.

  Lint expanded to every module under ``coordinator/`` (was
  ``ev_control.py`` only). Exempt files: ``types.py`` (defines the
  field) and ``per_charger_context.py`` (docstrings only). The
  ~15 legitimate fleet reads got explicit ``# FLEET-READ:``
  reasons; one ``coordinator.py:3459`` stall-detection site
  migrated to the new method form as the in-tree demo.

  Sensor reader (the only writer) constructs ``FleetEvPower``
  instances at the assignment sites. Single-charger setups
  unchanged — ``FleetEvPower(value)`` reduces to a tagged float.

  12 new tests in ``tests/test_fleet_ev_power_reads_global.py``:
  - ``TestGlobalFleetEvPowerLint`` (6): every read acknowledged
    across coordinator/; exempt-list minimality; synthetic-code
    sanity (method form detected, bare read flagged, comment
    form still accepted).
  - ``TestFleetEvPowerNewtype`` (6): is float subclass,
    arithmetic works (no migration cost), ``.as_fleet_total``
    returns plain float, reason arg is documentation-only,
    default ``PowerReadings.ev_power`` is the newtype, repr
    includes class name.

### Why

Senior reviewer on the v1.6.7→v1.6.10 arc flagged ``effective_state``
and ``this_power_w`` as "works correctly; not on the context object."
Both shipped working — but the docs claimed "pcc is the single source
of truth for per-charger data" while these two lived in a parallel
dict and method-local vars. This release makes the doc honest.

The ``#8`` surplus-tracker spike fix bundled in here was confirmed
live on PROD 2026-05-31 during the v1.6.3 soak — held with the
refactor rather than shipped standalone so PROD users get one
soak window instead of four staggered HACS updates.

@RienduPre's #316 observation ("Sankey shows charger 2 sourcing
from grid even in solar_only") was the user-visible gap behind the
flow-sensor work. v1.6.9 fixed the underlying data (proportional
W-level split was honest); v1.6.15 ships the entity surface so the
dashboard + Energy dashboard actually render the per-charger split.

### Polish (HA-TEST soak findings folded into v1.6.14)

- **PR #333** — initialise ``SEMCoordinator._current_charger_budget``.
  Missed in the v1.6.7 PerChargerContext refactor; ``__enter__``
  snapshotted the attribute but ``__init__`` never set it, so every
  multi-charger setup blew up its first cycle with
  ``AttributeError``. Single-charger setups (HA-PROD) never tripped
  it; HA-TEST today was the first multi-charger clean install since
  v1.6.7. New regression test ``test_coordinator_swap_attrs_initialized.py``
  AST-walks ``SEMCoordinator.__init__`` to assert every attribute
  ``PerChargerContext.__enter__`` snapshots is initialised.

- **PR #334** — per-charger notification ``NoneType`` coerce + flow
  sensor zero-fill. ``intel.get(k, default)`` returns the default
  only when the KEY is missing — mock chargers without upstream
  data have the key set to ``None``, so ``est_soc > 0`` raised
  ``TypeError`` every cycle (DEBUG noise). Fix: ``intel.get(k) or 0``.
  Plus: ``flow_calculator`` now zero-fills per-charger flows when
  the fleet is idle so the v1.6.15 flow sensors stay AVAILABLE at
  0 W instead of going ``unavailable`` whenever no charger draws.

- **PR #335** — upgrade-notification helper. After a HACS update +
  HA restart, the browser's loaded frontend bootstrap still
  references the OLD ``sem-localize.js`` URL until hard-refreshed
  — soft reload serves the cached bootstrap → loads stale
  translations → raw keys like ``today_plan_title`` /
  ``plan_strip_idle`` appear in cards. HA-TEST 2026-05-31 confirmed.
  New ``_maybe_emit_upgrade_notification`` helper detects a SEM
  version change at setup (via a per-entry
  ``hass.helpers.storage.Store``) and fires a one-shot
  ``persistent_notification`` instructing users to hard-refresh
  (Ctrl+Shift+R / Cmd+Shift+R). First install is silent. Failure
  is non-fatal. 5 new tests pin the contract (first-install,
  same-version, upgrade, per-version notification-id, per-entry
  storage key).

2263 tests pass on Python 3.12 (2210 v1.6.12 baseline + 13 #8 +
14 v1.6.14 + 20 v1.6.15 + 12 v1.6.16 + 2 v1.6.14-hotfix +
5 v1.6.14-polish = 66 new tests in this release). Manifest at 1.6.14.

## [1.6.12] — 2026-05-31

Closes the last open senior-reviewer item on the v1.6.7 → v1.6.11
multi-charger cleanup arc — the missing end-to-end scenario covering
``charger A = off + charger B = solar_only`` mixed-mode. No
behaviour change for any user.

### Added

- **New scenario test** ``tests/scenarios/2026-05-31_off_plus_solar_only.yaml``
  exercises the senior-reviewer-flagged hole in coverage:
  - **Per-charger effective state isolation** (v1.6.4
    ``_apply_per_charger_off_override``). Charger ``off`` mode →
    ``SOLAR_IDLE`` (terminate); sibling ``solar_only`` →
    ``SOLAR_CHARGING_ACTIVE`` (untouched). Pins the #315 mitigation
    at the unit-pipeline level — would have mechanically caught the
    v1.6.3 regression at PR-review time.
  - **Per-charger flow attribution** (v1.6.9
    ``PowerFlows.per_charger``). With per-charger draw set to
    ``{left: 4000, right: 0}``, the per-charger split must give
    ``right`` zero EV-side flow — the user-visible attribution
    @RienduPre asked for in #316.
  - **Distribution sum invariant** (Phase B.5 / #284) re-asserted on
    top of the mixed-mode case.

- **Scenario harness extensions** in ``tests/scenario_harness.py``:
  - ``TIMELINE_FIELDS`` accepts ``ev_power_per_charger: {cid: watts}``
    so multi-charger flow attribution can be driven from YAML.
  - Cycle results now include ``per_charger_effective_states`` and
    ``per_charger_flows`` when the scenario has 2+ chargers.
  - Two new ``expect.multi_charger`` assertion blocks:
    ``per_charger_effective_states`` (exact match or
    ``{cid}_contains: substring``) and ``per_charger_flow_max`` for
    per-charger upper-bound caps.

### Docs

- ``docs/MULTI_CHARGER.md`` roadmap updated: the off + solar_only
  scenario gap is now closed (was a senior-reviewer FIX-BEFORE-MERGE
  on the v1.6.7-v1.6.10 arc).
- CHANGELOG entry per the
  ``feedback_docs_per_release`` rule — docs are part of every
  release, not a follow-up.

## [1.6.11] — 2026-05-31

Diagnostics improvement + doc polish closing the senior-engineer
review NITs on the v1.6.7 → v1.6.10 multi-charger cleanup arc. No
behaviour change.

### Added

- **Recent SEM log lines in the Copy diagnostics dump** —
  ``diagnostics.py::_get_recent_sem_logs`` reads the last 2 MB of
  ``home-assistant.log``, filters for
  ``solar_energy_management`` mentions, and includes up to 80 matching
  lines as ``recent_logs`` in the diagnostics output. Bug reports now
  come pre-loaded with the surrounding log context so we don't have
  to ask reporters for a separate ``ha core logs`` dump. Supervisor
  installs (no flat log file, journald-based) get a one-line
  placeholder explaining how to attach logs manually.

### Docs

- ``CLAUDE.md`` — new "Multi-charger correctness" pointer to
  [``docs/MULTI_CHARGER.md``](docs/MULTI_CHARGER.md) so future AI
  sessions can find the invariant doc without needing to grep.
- ``docs/MULTI_CHARGER.md`` — updated the roadmap to reflect what
  **actually shipped** vs what was planned. Specifically: the original
  v1.6.7 design proposed migrating ``effective_state``,
  ``this_power_w``, ``night_plan`` onto ``PerChargerContext`` in
  v1.6.8/v1.6.9 — none of those landed. The current dataclass has
  ``cid`` / ``ev_dev`` / ``charger_cfg`` / ``budget_w`` /
  ``skipped_for_night`` only. Per-charger flow **sensors** (data is on
  ``PowerFlows.per_charger`` but no top-level HA entities yet) were
  also descoped. Both are deferred to v1.7+ in the roadmap so the doc
  no longer oversells the abstraction.

## [1.6.10] — 2026-05-31

Code-quality cleanup release. Closes the three follow-up issues filed
during the v1.6.4 → v1.6.6 review cycle (#308, #309, #310). **Zero
behaviour change** for any user.

### Refactored

- **#308 — dead ``now`` / ``min_pv`` consumer branches dropped from
  ``coordinator/charging_control.py``.** Post-#305 the strategy
  producer ``_determine_charging_strategy`` only emits ``solar_only`` /
  ``battery_assist`` / ``night_grid`` / ``idle`` / ``disabled`` —
  neither ``"now"`` nor ``"min_pv"`` was reachable in production. The
  unreachable branches are gone; ``ChargingState.SOLAR_MIN_PV`` is
  still alive via the ``night_grid`` → ``EVBudgetStrategy.MIN_PV``
  producer mapping. The two synthetic-context tests
  (``test_min_pv_mode``, ``test_now_mode``) that exercised the dead
  branches are removed.

- **#309 — global-select cleanup block in ``select.py`` folded into
  the registry-key sweep added by #304.** The 12-line explicit
  ``async_remove`` block for ``{entry_id}_ev_target_type``,
  ``{entry_id}_ev_target_mode``, ``{entry_id}_ev_charging_mode`` was
  redundant with the sweep at the bottom of ``async_setup_entry``:
  each of those unique IDs has the ``{entry_id}_`` prefix and a key
  that's not in ``valid_keys``, so the sweep removes them just as
  cleanly. Per-charger values were seeded from the globals by the
  v3→v4 migration; no data is lost.

- **#310 — gravestone comments in ``tests/test_soc_zone_strategy.py``
  consolidated** into a single ``Removed tests`` block at the top of
  the module. Three multi-line tombstones (one each from #277 Phase C,
  Phase D.2 / #282, and #305) collapsed to a three-bullet list with
  ``git log -S`` as the pointer for full history.

## [1.6.9] — 2026-05-31

Third and final of the multi-charger cleanup arc (v1.6.7 → v1.6.9).
Adds per-charger flow attribution and per-charger notification flap
suppression so multi-charger users finally get correct downstream
visibility — closes the @RienduPre #316 family of complaints. **Zero
behaviour change** for single-charger users.

See [`docs/MULTI_CHARGER.md`](docs/MULTI_CHARGER.md).

### Added

- **Per-charger flow attribution** in
  [`coordinator/flow_calculator.py`](coordinator/flow_calculator.py).
  When ``PowerReadings.ev_power_per_charger`` is populated (multi-charger
  installs), ``calculate_power_flows`` now also produces
  ``PowerFlows.per_charger[cid] = ChargerFlows(solar_to_ev, grid_to_ev,
  battery_to_ev)``. Sum invariant: ``sum(per_charger[c].solar_to_ev) ==
  solar_to_ev`` (within < 0.1 W from float rounding). Closes the
  long-standing @RienduPre #284 / #316 complaint family — the dashboard
  can now show which charger drank from grid vs solar instead of the
  fleet-aggregated proportional split.

- **``PowerReadings.ev_power_per_charger``** populated by
  ``sensor_reader`` for multi-charger installs (each charger's
  ``ev_charging_power_sensor`` value, keyed by charger id).
  Single-charger installs leave the dict empty.

- **Per-charger notification flap suppression** in
  [`coordinator/notifications.py`](coordinator/notifications.py).
  ``notify_state_change`` accepts new ``charger_id`` + ``charger_name``
  kwargs; the flap-suppression ``_last_notified_state`` /
  ``_pending_state`` / ``_pending_state_since`` storage is now
  per-charger, keyed by ``charger_id`` (or the ``"_fleet"`` sentinel
  for back-compat). A state change on charger A no longer suppresses
  one on charger B. Mobile messages get a ``[Charger Name]`` prefix
  when ``charger_name`` is provided. The HA event payload now carries
  ``charger_id`` and ``charger_name`` keys so automations can route
  per charger.

### Back-compat

- v1.6.8 callers that read ``_last_notified_state``,
  ``_pending_state``, or ``_pending_state_since`` as scalars continue
  to work via property shims that target the ``"_fleet"`` sentinel
  slot.
- Single-charger setups behave identically to v1.6.8 — the
  per-charger split skips when no per-charger data is provided.

## [1.6.8] — 2026-05-31

Second of the three-release multi-charger cleanup arc (v1.6.7 → v1.6.9).
**Zero behaviour change** for single-charger users; multi-charger users
get correctness fixes for 12 fleet-power-sum reads that were silently
returning the wrong value inside per-charger code paths. Sets up the
structural enforcement that makes the bug class impossible to
re-introduce.

See [`docs/MULTI_CHARGER.md`](docs/MULTI_CHARGER.md) for the full
developer-facing invariant.

### Fixed

- **12 fleet-power-sum reads swept in
  [`coordinator/ev_control.py`](coordinator/ev_control.py)** — every
  ``power.ev_power`` read inside the per-charger code path (8 in
  ``_execute_ev_control``, 3 in ``_should_reenable_charger``, 1 in
  ``_update_session_tracking``) now uses
  ``self._this_charger_power(ev, power)`` cached as
  ``this_power_w`` at the top of the method. In multi-charger setups
  these reads were returning the fleet sum — exactly the bug class
  that caused #284, #289, #315 (terminator) and #318 (SOC isolation).
  Each fix was reactive; this sweep closes them all.

### Added

- **AST lint test** ([`tests/test_ev_control_fleet_reads.py`](tests/test_ev_control_fleet_reads.py))
  — walks the AST of ``ev_control.py`` on every CI run and fails if
  any ``power.ev_power`` read is missing a ``# FLEET-READ:`` annotation
  (outside the sanctioned ``_this_charger_power`` helper). Catches the
  bug class on PR review, not after release.

- **``# FLEET-READ: <reason>`` annotation convention** — documented in
  ``docs/MULTI_CHARGER.md``. Same-line or previous-line comment opts
  a deliberate fleet-level read out of the lint with a required
  human-readable reason.

## [1.6.7] — 2026-05-31

First of a three-release multi-charger cleanup arc dedicated to v1.6.x.
**Zero user-visible behaviour change** for single-charger users; multi-charger
users see the same outputs but with the underlying swap mechanism now
typed and unit-tested.

The cleanup arc addresses a recurring bug class found in v1.6.0–v1.6.6
(#284, #289, #315, #318): per-charger context swaps with fleet-level
reads leaking through. This release lifts the swap mechanism; v1.6.8
sweeps the fleet-power reads in `ev_control.py` and adds per-charger
strategy; v1.6.9 adds per-charger flow attribution + notifications
(closes the #316 family).

See [`docs/MULTI_CHARGER.md`](docs/MULTI_CHARGER.md) for the full
developer-facing invariant.

### Refactored

- **`PerChargerContext`** — new
  [`coordinator/per_charger_context.py`](coordinator/per_charger_context.py)
  module that owns the per-charger swap lifecycle. The ad-hoc
  ``saved = {...}`` dict at `coordinator.py:1136-1258` that swapped
  eight coordinator attributes per iteration (and was easy to miss
  when adding new per-charger fields) is now a typed context manager
  with unit tests pinning every swap invariant. Adding a new
  per-charger field is now one place to edit instead of three.

### Docs

- **New `docs/MULTI_CHARGER.md`** — developer-facing invariant doc
  covering the bug class, the `PerChargerContext` contract, how to
  add new per-charger fields, and the v1.6.7-v1.6.9 roadmap.
- **`CONTRIBUTING.md`** — new "Multi-charger correctness" section
  pointing future contributors at the invariant.

## [1.6.6] — 2026-05-31

Same-day hotfix for v1.6.5 — the per-charger power read at
``_this_charger_power`` did a unit-naive ``float(state.state)`` and
compared a kW value to a 500 W threshold. KEBA's native
``sensor.keba_p30_charging_power`` reports in kW; the comparison
``4.14 < 500`` was always False so the v1.6.5 off-mode stop never
fired on KEBA, even when the firmware self-resumed. Confirmed live
on PROD 2026-05-31 15:26 — KEBA self-resumed and ran uncontrolled
for ~2 min until a manual ``keba.disable`` stopped it.

### Fixed

- **Unit-aware per-charger power reading** — ``_this_charger_power``
  now reads the sensor's ``unit_of_measurement`` attribute and
  converts kW → W before the 500 W threshold check. Tests pin both
  KEBA-style (kW) and Wallbox-style (W) sensors so the next charger
  integration doesn't introduce the same trap.

- **Per-charger SOC isolation in multi-charger setups** (#318) —
  ``_update_ev_intelligence`` was only calling ``update_energy()`` on
  the PRIMARY taper detector at line ~3326; every per-charger detector
  in ``_ev_taper_detectors`` stayed at ``_energy_since_full=0``,
  giving every charger the same default SOC. Confirmed by @RienduPre
  on a multi-charger Wallbox Pulsar + Growatt setup. Fix: also call
  ``update_energy(per_increment, per_hw_total)`` inside the
  per-charger loop, using each charger's own ``ev_total_energy_sensor``
  hardware counter for drift-free tracking when configured.

## [1.6.5] — 2026-05-31

Same-day follow-up to v1.6.4. Closes the second half of the off-mode
problem: KEBA P30 self-resumes from a stored setpoint on plug-in events
or after internal firmware events, completely independent of SEM. The
v1.6.4 fix only stopped SEM-owned sessions; if SEM never started the
session (because mode was already off when the EV plugged in, or KEBA
restarted on its own), the contactor stayed closed and KEBA drew power
SEM never knew about.

### Fixed

- **off-mode now stops charger-initiated charging** (#315) — the
  actuator's terminal-state branch in ``ev_control.py`` now also calls
  ``stop_session()`` when ``charging_strategy == "disabled"`` and
  ``ev_power > 500W``, regardless of ``ev._session_active``. Every
  coordinator cycle (10 s) re-asserts the per-brand disable (e.g.
  ``keba.disable``) until ev_power drops below the 500 W threshold.
  Idempotent — safe to call on an already-disabled charger.

  Threshold rationale: KEBA's handshake idle draws 100–200 W
  continuously while plugged in (control-pilot duty cycle). Real
  charging starts at 4140 W minimum (3 phases × 6 A × 230 V). The
  500 W cutoff cleanly separates "actually pulling current" from
  "plugged in, parked" so SEM doesn't spam stop_session every cycle
  while the car is idle at the charger.

## [1.6.4] — 2026-05-31

Hotfix on top of v1.6.3 plus the cleanup follow-ups #304/#305 that
shipped to develop the same day.

### Fixed

- **`charge_mode=off` did not stop EV charging** — surfaced during the
  v1.6.3 PROD soak. Setting the per-charger Charge mode to ``Off`` while
  the EV was actively charging left the KEBA contactor closed; SEM
  reported "Charging allowed" with budget 0 but the charger kept drawing
  power, requiring a manual ``keba.disable`` call to stop. The state
  machine fell through to ``SOLAR_CHARGING_ALLOWED`` instead of a
  terminal stop, so ``stop_session()`` was never invoked.

  Fix: introduce a distinct ``"disabled"`` strategy string for explicit-off
  (separate from transient ``"idle"``). The state machine routes it to
  ``SOLAR_IDLE``, which the actuator treats as terminal → calls
  ``stop_session()`` → ``keba.disable``. The canonical EV budget enum
  collapses ``"disabled"`` back to ``IDLE`` (same 0 W shape, distinct
  upstream).

  Multi-charger correctness: a static helper
  ``_apply_per_charger_off_override`` runs in the dispatch loop so a
  primary charger's ``off`` cannot bleed its terminate into siblings
  with active ``solar_only``/``min_plus_solar`` modes.

### Cleanup (from develop merge)

- **#304** — ``select.py`` orphan removal now uses a registry-key sweep
  matching ``switch.py``. Catches stale entries from previously-removed
  chargers (rather than only those currently in the config).
- **#305** — drop dead ``_auto_mode_strategy`` and the unreachable
  ``min_pv`` branch in ``_canonical_strategy_from_legacy``. Both were
  Phase C leftovers documented as deferred.

## [1.6.3] — 2026-05-30

The **EV charge UX consolidation** release (#277). Replaces the
four-toggle soup (``ev_charging_mode`` × ``night_charging`` ×
``smart_night_charging`` × ``tariff_optimized``) with one named
per-charger ``Charge mode`` selector. Three-phase arc shipped across
five PRs (A + B + B.2 + C + #298 today-plan ETAs).

### New

- **Per-charger ``Charge mode`` selector** with five modes:
  ``Solar only`` / ``Solar + cheapest hours`` / ``Min + Solar``
  (default) / ``Always (max)`` / ``Off``. ``Solar + cheapest hours``
  is dynamically hidden when no dynamic tariff is configured.
- **Per-mode help line** in the EV card explains what each mode
  actually does — cuts the toggle-soup mystery the #247 review
  flagged.
- **Today's plan timeline** gains three ETA rows (#298): "Battery
  full at HH:MM" while charging, "Battery reaches floor at HH:MM"
  while discharging, "EV reaches target at HH:MM" while a charging
  session is in progress.

### ⚠️ Behavioural change — explicit-``minpv`` legacy users

A small population of users explicitly set the legacy
``ev_charging_mode`` to ``minpv`` (the "force Min from grid + solar
to Max" mode). The Phase A migration mapped them to
``min_plus_solar``, which in v1.6.x kept their daytime behaviour
unchanged (the strategy machine still read the legacy field). v1.6.3
Phase C makes ``min_plus_solar`` **zone-adaptive during the day** —
the Min guarantee now comes from NIGHT charging top-up only, not
from forced grid pull at noon. The Min target itself is unchanged;
the daytime path now matches what most installs (``pv + night=on``)
were always doing.

If you want strict "Min from grid at all times" behaviour, pick
``always_max`` from the new selector — it charges at maximum
regardless of source. Otherwise the new ``min_plus_solar`` default
adapts to your battery SOC zone (battery priority when low, surplus
when high, battery-assist in Zone 4) — generally more efficient
than forced grid pull.

### Migrations (automatic on first load post-upgrade)

- **v4 → v5** (Phase A): Each charger gets a ``charge_mode`` derived
  from its existing toggle state. The legacy fields stay in place.
- **v5 → v6** (Phase B fix-up): Re-derives ``charge_mode`` for
  installs whose Phase A derivation silently lost the
  ``tariff_optimized`` signal (``pv/auto/self_consumption + tariff_on``
  → ``solar_plus_cheap``).
- **v6 → v7** (Phase C): Drops the now-dead ``ev_charging_mode`` per-
  charger config key. The legacy ``select.sem_charger_<id>_ev_charging_mode``
  entity is removed from the registry automatically.

### Removed

- **Per-charger switches** ``switch.sem_charger_<id>_night_charging``,
  ``...smart_night_charging``, ``...tariff_optimized`` — the named
  ``charge_mode`` selector carries all three intents now. Existing
  automations that read these switches will need to read the
  ``charge_mode`` select state instead.
- **Per-charger select** ``select.sem_charger_<id>_ev_charging_mode``
  — superseded by the new ``charge_mode`` selector.
- **Global switches** ``switch.sem_night_charging`` and
  ``switch.sem_smart_night_charging`` — same; ``observer_mode`` is
  the only remaining global switch.
- **Config-flow toggle** ``smart_night_charging`` — the named modes
  carry the intent.
- **Strategy machine legacy reads**: ``ev_charging_mode`` is no
  longer consulted anywhere; ``_tariff_optimized_for`` derives from
  the named mode.

### Fixed

- **Stale Lovelace cache-bust on sem-localize.js (#301)** — the legacy
  ``generate_dashboard`` service path used ``int(time.time())`` as the
  ``?v=`` for card resources, so a plain rsync deploy that rewrote
  ``sem-localize.js`` left the registered URL unchanged and browsers
  served the cached pre-Phase-B.2 file. Symptom on first install of
  this release: the new charge-mode selector renders raw translation
  keys (``charge_mode``, ``charge_mode_min_plus_so…``,
  ``charge_mode_hint_min_plus_solar``) instead of localized labels.
  Fix: per-file ``{version}-{sha1(content)[:8]}`` cache-bust, matching
  the format ``_async_register_frontend_resources`` already uses for
  the Lit bundle. Both paths now produce identical URLs for the same
  file content; any deploy that changes content auto-flips the URL on
  the next ``generate_dashboard`` call and the browser cache-misses
  through to the fresh copy.

### Internal

- New ``consts/ev_charge_modes.py`` — shared constants
  (``EV_CHARGE_MODES``, ``MODE_NIGHT_ALLOWED``, ``MODE_USES_TARIFF``,
  ``MODE_USES_SMART_NIGHT``, ``MODE_TO_LEGACY_CHARGING_MODE``,
  ``DEFAULT_EV_CHARGE_MODE``) and the ``effective_charge_mode_for``
  resolver. Single source of truth for the mode taxonomy across
  ``SEMCoordinator``, ``ChargingStateMachine``, ``EVControlMixin``,
  the dashboard cards.
- ``async_migrate_entry`` accumulator refactor — each step reads
  from / writes back to threaded ``accumulated_{data,options}``
  accumulators. Fixes a pre-existing bug exposed by chaining 4
  migration steps (each was re-reading the original entry options on
  test harnesses).
- New module-level ``_content_hash_cache_bust`` helper — extracted
  from the legacy ``generate_dashboard`` registration path so the
  cache-bust behaviour is directly unit-testable. Replaces a closure
  buried inside ``async_generate_dashboard_service``.
- 15-language translations updated; legacy entries cleaned from
  ``strings.json`` + 15 per-language files.
- Suite: 2136 / 2136 tests passing (6 new regression tests guard
  the #301 cache-bust contract).

### Issues addressed

- Closes #277 (EV charge UX consolidation arc)
- Closes #298 (Today's plan battery / EV ETA rows)
- Closes #301 (Stale Lovelace cache-bust on sem-localize.js)

---

## [1.6.2] — 2026-05-30

The **Phase D.2 cleanup + EV-power realtime** patch.

Two changes ship together:

1. **Phase D.2 architectural cleanup (#282)** — completes the EV-budget
   unification arc by removing the legacy fallbacks that the v1.6.0
   canonical path left side-by-side as a safety net. Carrying two budget
   formulas alive was exactly the duplication that produced the
   disagreement bug class in the first place; with three weeks of clean
   v1.6.0/v1.6.1 PROD soak the fallbacks are dead code, and keeping them
   invited the next regression.

2. **#289** — `sensor.sem_ev_power` now updates within one HA dispatch
   of the upstream KEBA / Wallbox sensor instead of waiting up to 10 s
   for the next coordinator cycle. The dashboard reads at 1 s
   resolution and observably benefits; the energy-balance derivations
   (`home_consumption_power`, sankey flows) stay on cycle granularity
   and self-heal on the next tick.

No behavioural changes outside the named removals + the sub-cycle
passthrough. Same upgrade path as any 1.6.x.

### Removed

- **`flow_calculator.calculate_ev_budget`** — superseded by
  `calculate_canonical_ev_budget` since v1.6.0 (Phase A). Zero
  production callers as of v1.6.1.
- **`flow_calculator.calculate_available_power`** — superseded by the
  canonical EVBudget's per-strategy resolution. Zero production
  callers as of v1.6.1.
- **`flow_calculator.calculate_charging_current`** — both production
  call sites (night charge sizing + actuator ramp) now go through
  `EVControlMixin._watts_to_amps` which carries the per-charger
  watts-per-amp + round-down policy directly.
- **`EVControlMixin._calculate_solar_ev_budget`** — 74-line legacy
  fallback that the actuator used when `_cycle_ev_budget` wasn't
  populated. Removed; the path now logs an error and emits 0 W
  (fail-safe = no charge) if the invariant is ever violated. This
  catches coordinator init bugs loudly instead of silently masking
  them with a divergent budget formula.
- **Multi-charger distribution legacy fallback** in
  `coordinator.py` — same fail-safe pattern applied: missing
  `_cycle_ev_budget` → log error + distribute 0 W.
- **`sensor._format_charging_state` demotion guard** — the cosmetic
  SOLAR_CHARGING_ACTIVE → SOLAR_CHARGING_ALLOWED downgrade (commit
  `1a9b3c9`) that papered over the pre-D.2 budget disagreement. The
  canonical unification eliminated the disagreement by construction,
  so the guard is now dead code — verified across daytime
  battery_assist and nighttime MIN_PV soak in v1.6.0/v1.6.1.

### Added

- **#289 — sub-cycle `sem_ev_power` passthrough** — the `ev_power`
  sensor now subscribes to its upstream EV-power entities via
  `async_track_state_change_event` (single-charger: top-level
  `ev_power_sensor`; multi-charger: every charger's
  `ev_charging_power_sensor`). On any upstream change SEM re-sums and
  pushes the new value immediately. Eliminates the 1-cycle gap that
  showed up live on PROD 2026-05-29 as a 4.7 kW dashboard
  discrepancy. 11 unit tests + the resolution / callback / cleanup
  invariants.

### Internal

- **Test sweep** — removed the unit tests that pinned the deleted
  primitives directly (`TestAvailablePower`, `TestEvBudget`,
  `TestAvailablePowerIncludesBatteryDischarge`, `TestEVBudgetSemantics`,
  `TestAvailablePowerInvariants`, `TestCalculateSolarEvBudget`, the
  budget/current rows from `TestEVControlInvariants`). Their physical
  invariants (non-negative budget, 16 A clamp, battery-discharge
  inclusion, Zone-3 proportional ramp, measured-discharge override)
  are now exercised against `calculate_canonical_ev_budget` and the
  scenario harness (`tests/scenarios/2026-05-29_*`).
- **Scenario harness rewired** — `tests/scenario_harness.py` was
  calling the deleted `calculate_ev_budget` / `calculate_charging_current`
  inside a bare `except Exception: pass`. Caught in review before
  deploy: every scenario was vacuously passing (`calculated_current`
  fell silently to 0). Rewrote to compute the canonical EVBudget
  directly and read `EVBudget.net_w` + `EVBudget.current_a`, so
  scenario regressions now fail loudly. 4 / 4 scenarios still pass
  with real values.
- **`test_multi_charger_canonical_budget.py` rewrite** — the test
  mirrored the pre-D.2 production branch with the legacy fallback;
  post-D.2 the branch logs an error and distributes 0 W instead.
  New `test_missing_cycle_budget_fails_safe_to_zero` pins the fail-
  safe; `test_legacy_method_attribute_does_not_exist_post_d2`
  prevents accidental re-introduction.
- **16 A clamp coverage gap closed** —
  `TestEVControlInvariants.test_canonical_budget_current_a_clamped_to_16`
  sweeps extreme solar / battery inputs across every non-IDLE
  strategy (including `BATTERY_ASSIST` which can blow past the
  surplus ceiling by design) and verifies `EVBudget.current_a`
  stays in [0, 16].
- **Docstring rot** — `ChargingContext.available_power` docstring
  was still referencing `FlowCalculator.calculate_ev_budget()`;
  updated to point at `calculate_canonical_ev_budget().net_w`.

**Suite is 2054 / 2054 green** (was 2042 in v1.6.1 — 12 new tests).

---

## [1.6.1] — 2026-05-30

Patch release with fixes driven by the v1.6.0 PROD soak. No behavioural
changes outside the named fixes — same upgrade path as any 1.6.x.

### Fixed

- **#288** — Night peak management formula switched from the
  sensor-lag-sensitive derived `home_consumption_power` to
  `sensor.sem_consecutive_peak_15min` (the same 15-min rolling
  grid-import average most demand-charge tariffs bill on).
  Self-balancing: as EV ramps the rolling rises and headroom shrinks
  naturally; settles at the equilibrium where rolling ≈ peak limit.
  Falls back to the legacy formula during the cold-start window when
  the load manager hasn't accumulated samples yet, so peak protection
  is never absent. Caught live on PROD 2026-05-29 with a 7.9 kW grid
  spike during EV ramp because `sem_ev_power` lagged by ~5 kW for
  several seconds, deflating the derived home value toward 0 and
  giving the EV the full peak limit as headroom. 6 unit tests +
  forever live sentinel.
- **#290** — Night state machine no longer blips through
  `NIGHT_DISABLED` for one cycle during config slider writes.
  Observed live on PROD 2026-05-29: a per-charger Number slider
  write triggered a race in `hass.states.is_state` for the per-charger
  night switch, returning False for one ~10 s cycle before
  recovering. SEM now requires 2 consecutive cycles of disagreement
  before flipping the cached state — trades 10 s of responsiveness
  for race immunity. 7 unit tests covering first-call commit, blip
  suppression, sustained change, and pending-counter reset.

### Internal

- **Test infra** — fixed the pre-existing flaky
  `test_lookahead_uncapped_when_no_deadline_resolvable` that had been
  intermittently red since the defensive `night_end` fallback at
  `ev_control.py:119-122` was added. The test now patches
  `DEFAULT_EV_TARGET_TIME` to None so the original "no deadline
  resolvable" path it was written to guard is actually exercised.
  Suite is now 2091 / 2091 fully green — first time this release.
- **Live test layer** — new sentinel `tests/live/test_night_peak_rolling.sh`
  pins the #288 fix as a regression guard.
- **Documentation** — design plan for #277 (EV Charge mode
  consolidation) committed at `docs/plans/2026-05-30_ev_charge_mode_consolidation.md`.
  No code yet; awaiting maintainer decisions on the four design
  questions listed there before any implementation. Tracked for v1.7.0.

---

## [1.6.0] — 2026-05-30

The **EV-budget unification** release. SEM historically had three separate
"how many watts can the EV draw right now" calculations — one for the
published dashboard sensors, one for the state machine's decision, and one
for the actuator. Under certain conditions they disagreed: the dashboard
could read *"Charging active"* while the car drew 0 W, or surplus-only
mode could let grid backfill the EV's draw without telling the user.

v1.6.0 collapses all three into one canonical `EVBudget` value computed
once per cycle. Every consumer now reads from the same dataclass — the
dashboard, the state machine, the actuator, and the multi-charger
distribution all see the same number, by construction.

### ⚠️ Behavioural change — published sensors

`sensor.sem_available_power` and `sensor.sem_calculated_current` now
publish the **canonical** EV budget instead of the raw solar surplus.
The canonical value is strategy-aware (includes battery-redirect on
`solar_only`, includes the battery-assist contribution on
`battery_assist`, applies the floor on `min_pv`) — it's the more
accurate number and matches what the state machine actually decides
with.

If you have automations or template sensors that read either of these
two values directly, you may see different numbers than under
1.5.x. The canonical value is the honest one; the pre-1.6.0 value
could be misleadingly low when battery redirect was active.

### Added

- **Canonical `EVBudget` dataclass and `EVBudgetStrategy` enum** in
  `coordinator/flow_calculator.py`. Six strategies are first-class:
  `IDLE`, `SELF_CONSUMPTION`, `SOLAR_ONLY`, `BATTERY_ASSIST`, `MIN_PV`,
  `NOW`. Each has a single well-defined formula; the dispatcher raises
  `ValueError` on unknown strategies (no silent fallthrough, which was
  the #282 disagreement root). See [ARCHITECTURE.md → EV Budget
  Calculation](docs/ARCHITECTURE.md#ev-budget-calculation).
- **Live test layer** under `tests/live/` — seven bash scripts that
  exercise SEM against a real Home Assistant instance:
  `test_budget_agreement.sh`, `test_charging_state_consistency.sh`,
  `test_solar_only_no_grid.sh`, `test_overnight_window.sh`,
  `test_deadline_reset.sh`, `test_per_charger_slider.sh`,
  `test_bundle_integrity.sh`, `test_surplus_charging.sh`.
- **Scenario harness scenarios** locking the canonical math through
  the coordinator pipeline:
  `tests/scenarios/2026-05-29_budget_unify_redirect.yaml`,
  `tests/scenarios/2026-05-29_budget_unify_battery_assist.yaml`,
  `tests/scenarios/2026-05-29_multi_charger_split.yaml`.
- 17 unit tests for the canonical method covering every strategy plus
  the regimes that historically disagreed.
- 4 unit tests for the multi-charger Phase B.5 distribution path.
- 4 unit tests for the YAML-mode Lovelace guard.
- `copy_failed` translation key across all 15 languages.

### Changed

- `coordinator.async_update_config` now mutates `self.config` in place
  rather than rebinding to a new dict. Multiple components
  (`TimeManager`, `EnergyCalculator`, `ChargingStateMachine`,
  `BatteryChargeAdapter`) hold references to the original dict; the
  pre-fix rebind left them stale, so the next slider change reached
  `coordinator.config` but never propagated. Caught by
  `tests/live/test_overnight_window.sh`.
- The multi-charger distribution at `coordinator.py:966` now reads the
  canonical `EVBudget.net_w` instead of calling the legacy
  `_calculate_solar_ev_budget`. Same #282 disagreement mode, just for
  fleets of 2+ chargers (Phase B.5).
- The `sem-system-card` "Copy diagnostics" button now uses a
  cross-context clipboard helper that falls back to
  `document.execCommand('copy')` on HTTP installs where the modern
  Clipboard API is blocked. Always shows user feedback — success or
  failure — so the button is never silent again.
- Deploy scripts (`~/bin/deploy-test.sh`, `~/bin/deploy-prod.sh`) now
  strip `__pycache__` before `ha core restart`. `ha core restart` does
  not clear the bytecode cache, so signature changes in committed
  code could still execute the cached `.pyc` and produce confusing
  `NameError`s. (Operational; not in the integration itself.)

### Fixed

- **#279** — Global `daily_ev_energy` counter resets at the configured
  `Charge by` time, not at sunrise. The summer-sunrise race condition
  (sunrise earlier than the deadline → counter wiped while night
  charging still in progress → double-charge) is closed.
- **#283** — Dashboard no longer fails to register on YAML-mode
  Lovelace installs. The integration feature-detects the mutating
  resource-collection methods; when YAML mode is detected, it logs a
  single actionable warning with the exact `lovelace.resources:` YAML
  the user has to paste, instead of an unhelpful "Could not register"
  warning. Storage-mode users see no behavioural change.
- **#284** — Multi-charger setups (e.g. dual Wallbox Pulsar) no longer
  pull from grid while strategy reports `solar_only`. The distribution
  path now reads from the canonical `EVBudget`.
- **#285** — "Copy diagnostics" button in the System Information card
  now works on HTTP installs. Reported on macOS Chrome.
- **Charger plug-sensor physics defence** — caught live on PROD
  2026-05-29 with a KEBA P30. Across an HA restart with a connected
  car, `binary_sensor.keba_p30_plug` reported "off" for 67 minutes
  while `binary_sensor.keba_p30_charging_state` cycled on/off through
  15 transitions and `sensor.keba_p30_charging_power` peaked at 8 kW.
  SEM correctly trusted the lying plug sensor, returned "EV
  disconnected", and stopped supervising the car. The KEBA kept its
  last commanded current; the car drew ~6 kWh past the configured
  Max ceiling because SEM wasn't watching. The root cause is upstream
  (the charger integration's plug sensor), but SEM now defends
  against it: if `ev_charging` is True OR `ev_power > 100 W`,
  `ev_connected` is inferred True regardless of what the plug sensor
  says. Current cannot flow without a connection. Locked in by
  `tests/test_ev_connected_physics_defence.py` (5 truth-table corners)
  and `tests/live/test_ev_connected_physics.sh` (forever sentinel).
- Display-honesty guard at `sensor.py:_format_charging_state` is now
  redundant after the unification (canonical is the single source of
  truth) but kept as defence-in-depth for one release; will be removed
  in v1.7.0.

### Internal

- `coordinator/coordinator.py` — `_build_charging_context`'s
  `available_power` and `calculated_current` parameters dropped (dead
  since Phase B). Step 6's bare-variable computation removed (also dead
  since Phase B).
- New `_canonical_strategy_from_legacy` helper in `coordinator.py`
  maps the legacy strategy-string returns of `_determine_charging_strategy`
  to canonical `EVBudgetStrategy` constants.

### Community contributions

Thanks to **@RienduPre** for [PR #286](https://github.com/traktore-org/sem-community/pull/286)
— two native-speaker Dutch translation polishes (`notif_low_forecast`
grammar; `notif_daily_summary` replaces the loanword "autarkie" with the
idiomatic "zelfvoorzienend").

---

## [1.5.15] — 2026-05-27

Single hotfix release for a SolaX-pattern cold-start regression.

### Fixed

- **#274** — Inverter / battery / grid readings no longer stay at 0
  after an HA restart on SolaX-pattern installs (Pattern E: split
  grid). Forced a sensor-reader reinitialization on coordinator
  restart instead of relying on the lazy first-cycle path.

---

## [1.5.14] — 2026-05-27

Documentation, sensor-naming hardening, and the #255 per-charger
config cleanup.

### Added

- Per-charger night charging gate (`switch.sem_charger_<id>_night_charging`,
  default ON) — multi-charger fleets can now schedule night charging
  per car.

### Changed

- Removed the redundant global EV configuration entities — per-charger
  entities are the canonical source of truth after #255. The integration
  migrates existing setups transparently.
- Energy Dashboard config summary on the System tab now lists actual
  entity names instead of the compact "X sources, Y units" string (#250).

### Fixed

- **#245** — Surplus EV charging now stops at the Max ceiling
  (`daily_ev_target_max`) instead of running until the per-cycle
  remaining-need flips negative. The Min target gates night charging;
  Max gates day surplus. Both are honored independently.
- **#256** — Zero-config installs no longer adopt the global target as
  the per-charger night floor without the user's explicit consent.
- **#259** — Vehicle SOC reads that come back as `unknown` or
  `unavailable` no longer crash the strategy decision.

---

## [1.5.13] — 2026-05-25

Beta-only iterations; release notes consolidated into the next stable.

---

## [1.5.12] — 2026-05-25

### Fixed

- Dashboard regenerate ("Generate Dashboard" service) no longer
  triggers an HA core restart. Live-reload via the storage API
  replaces the legacy "write + restart" pattern.
- Removed a stray top-level `sem-cards.js` left over from a botched
  manual deploy that was shadowing the real `dist/sem-cards.js`
  bundle and breaking every dashboard card (#219 regression class).

---

## [1.5.11] — 2026-05-25

### Changed

- All ~23 dashboard cards now ship as a single Lit bundle at
  `dashboard/card/dist/sem-cards.js`. The legacy top-level vanilla
  `sem-*-card.js` files were removed.
- Lovelace resource URLs now include `?v={version}-{sha1[:8]}` for
  cache busting; plain `rsync + restart` deploys now bust the browser
  service-worker cache without a manifest bump (#240).

---

For the full pre-1.5.11 history, see the [git tag log](https://github.com/traktore-org/sem-community/tags).

[1.6.0]: https://github.com/traktore-org/sem-community/releases/tag/v1.6.0
[1.5.15]: https://github.com/traktore-org/sem-community/releases/tag/v1.5.15
[1.5.14]: https://github.com/traktore-org/sem-community/releases/tag/v1.5.14
[1.5.13]: https://github.com/traktore-org/sem-community/releases/tag/v1.5.13
[1.5.12]: https://github.com/traktore-org/sem-community/releases/tag/v1.5.12
[1.5.11]: https://github.com/traktore-org/sem-community/releases/tag/v1.5.11
