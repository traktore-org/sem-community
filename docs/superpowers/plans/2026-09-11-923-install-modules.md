# SEM as a core plus modules — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SEM creates a hardware module's entities, tab and dashboard references only when the install has that hardware (battery, EV, heat pump, hot water), decided by one oracle that answers PRESENT / ABSENT / UNKNOWN.

**Architecture:** A pure module `coordinator/install_modules.py` holds the verdict function, the `(platform, key) → modules` table for all 268 static entities, and the keep rules. The coordinator computes the verdict once, after the Energy Dashboard read and before the platforms load (`setup_presence`); every platform, the dashboard generator, the welcome text, the diagnostics and `validate-sem.sh` read that one answer. The platforms' existing stale-entity sweeps, fed the gated lists, remove an ABSENT module's leftovers; an Energy Dashboard update listener reloads once when a module appears.

**Tech Stack:** Home Assistant custom integration (Python 3.13/3.14), pytest + pytest-homeassistant-custom-component, Lit card bundle (rollup, `node --test`), bash tooling in `~/bin`.

**Spec:** `docs/superpowers/specs/2026-09-11-923-install-modules-design.md` (corrected 11.09 while planning — read §3–§7 first).
**Branch:** `feature/923-house-surface`. **Issue:** every commit says `(#923)`; #857 is the user-facing issue it implements.

---

## Conventions for every task

- **Run tests with `~/bin/semtest`** — it copies the repo into the CI layout (`/tmp/ha-config/custom_components/solar_energy_management/`) and runs pytest there; running from the repo root breaks because the root `select.py` shadows the stdlib. Paths are repo-relative:
  `~/bin/semtest tests/test_923_install_modules.py -v`
- Real-hass tests (the `hass` fixture) take 5–15 s each. That is normal.
- **Never pipe a long run through `tail`** — write it to a file and read the file (`-rf` lists every failure).
- Commit messages: `feat(#923): …` / `test(#923): …`. **No `Co-Authored-By` or any AI attribution line.**
- **Do not deploy anywhere until Task 17.** Build the whole thing, then test live once (CLAUDE.md, "Build complete, THEN test").
- **Do not merge to develop.** The branch merges only on Guido's word, with `SEM_FEAT_OK` (Task 17 ends by asking).

## File map

| File | Responsibility |
|---|---|
| `coordinator/install_modules.py` (new) | The oracle: `Module`, `Presence`, wiring keys, `install_modules()`, `has_managed_charger()`, `ENTITY_MODULES`, `CORE_BY_DECISION`, keep rules, reload guard. Pure stdlib — no HA import. |
| `ha_energy_reader.py` | `read_energy_dashboard_config_outcome()` — config **and** whether the question was answered. |
| `coordinator/coordinator.py` | Owns the verdict: `_ed_raw_config`, `_ed_answered`, `setup_presence`, `install_presence()`, `_check_module_growth()`. |
| `__init__.py` | Captures `setup_presence` before the platforms load; welcome text; structural keys; Energy Dashboard listener. |
| `sensor.py`, `number.py`, `switch.py`, `binary_sensor.py`, `button.py`, `select.py` | Build only kept descriptions; feed the same list to the stale sweep. |
| `features/dashboard_generator.py` | `_prune_absent_modules()` replaces `_prune_ev_view_if_no_charger()`; K-Flow flags from the oracle. |
| `dashboard/card/src/cards/sem-load-priority-card.js` | The one unguarded `states[x].state` read. |
| `diagnostics.py`, `sensor.py` (`diag_ed_config`) | Make the verdict visible. |
| `manifest.json` | `after_dependencies: energy` (we import its manager). |
| `~/bin/validate-sem.sh`, `~/bin/deploy-test.sh` | Module-aware validation; a minimal-install switch. Outside the repo. |
| Tests | `tests/test_923_*.py` (new), `tests/test_595_hide_ev_view.py` and `tests/test_805_welcome_reflects_install.py` (re-pinned). |
| Docs | `docs/USER_GUIDE.md`, `docs/DASHBOARD_GUIDE.md`, `CHANGELOG.md`. |

---

### Task 1: The oracle — one answer, three states

**Files:**
- Create: `coordinator/install_modules.py`
- Test: `tests/test_923_install_modules.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_923_install_modules.py`:

```python
"""#923 — the install-modules oracle: one answer, three states.

SEM is a core plus hardware modules (battery, EV, heat pump, hot water).
Every surface that depends on a module asks ONE function whether the install
has it. The verdict comes from configuration, never live state, and "the
Energy Dashboard could not be read" is UNKNOWN — never ABSENT (#925)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.install_modules import (
    Module,
    Presence,
    has_managed_charger,
    install_modules,
)

ED_EMPTY = SimpleNamespace(has_battery=False, has_ev=False)
ED_BATTERY = SimpleNamespace(has_battery=True, has_ev=False)
ED_EV = SimpleNamespace(has_battery=False, has_ev=True)


class TestBattery:

    def test_a_wired_soc_sensor_is_present_before_the_dashboard_is_read(self):
        v = install_modules({"battery_soc_sensor": "sensor.soc"}, None, False)
        assert v[Module.BATTERY] is Presence.PRESENT

    def test_a_wired_control_entity_is_present(self):
        v = install_modules(
            {"battery_discharge_control_entity": "number.max_discharge"}, ED_EMPTY, True)
        assert v[Module.BATTERY] is Presence.PRESENT

    def test_the_energy_dashboard_alone_makes_it_present(self):
        assert install_modules({}, ED_BATTERY, True)[Module.BATTERY] is Presence.PRESENT

    def test_nothing_wired_and_the_dashboard_read_is_absent(self):
        assert install_modules({}, ED_EMPTY, True)[Module.BATTERY] is Presence.ABSENT

    def test_a_missing_dashboard_file_is_an_answer(self):
        # read_energy_dashboard_config_outcome() returns (None, True) when
        # .storage/energy does not exist: a definite "no dashboard".
        assert install_modules({}, None, True)[Module.BATTERY] is Presence.ABSENT

    def test_an_unread_dashboard_is_unknown_never_absent(self):
        # #925: "I could not ask" is not "no". UNKNOWN keeps every entity.
        assert install_modules({}, None, False)[Module.BATTERY] is Presence.UNKNOWN

    def test_capacity_alone_is_not_evidence(self):
        # The options flow's Settings step saves battery_capacity_kwh with a
        # default for every install that passes through it.
        v = install_modules({"battery_capacity_kwh": 10.0}, ED_EMPTY, True)
        assert v[Module.BATTERY] is Presence.ABSENT

    @pytest.mark.parametrize("value", [None, "", [], {}])
    def test_empty_values_are_not_wiring(self, value):
        v = install_modules({"battery_power_sensor": value}, ED_EMPTY, True)
        assert v[Module.BATTERY] is Presence.ABSENT


class TestEv:

    def test_a_charger_list_is_present(self):
        v = install_modules({"ev_chargers": [{"id": "ev_charger"}]}, ED_EMPTY, True)
        assert v[Module.EV] is Presence.PRESENT

    @pytest.mark.parametrize("key", ["ev_charging_power_sensor", "ev_power_sensor"])
    def test_the_legacy_single_charger_keys_are_present(self, key):
        assert install_modules({key: "sensor.wb"}, ED_EMPTY, True)[Module.EV] is Presence.PRESENT

    def test_an_energy_dashboard_ev_consumer_is_present_without_a_charger(self):
        # sensor_reader.py feeds sem_ev_power from ed.ev_power when no charger
        # is configured — that install HAS EV data.
        assert install_modules({}, ED_EV, True)[Module.EV] is Presence.PRESENT

    def test_nothing_and_the_dashboard_read_is_absent(self):
        assert install_modules({}, ED_EMPTY, True)[Module.EV] is Presence.ABSENT

    def test_an_unread_dashboard_is_unknown(self):
        assert install_modules({}, None, False)[Module.EV] is Presence.UNKNOWN


class TestHeatPump:

    @pytest.mark.parametrize("key", [
        "heat_pump_relay1_entity", "heat_pump_relay2_entity",
        "heat_pump_climate_entity", "heat_pump_sg_ready_service",
        "heat_pump_sg_ready_state_entity", "heat_pump_power_sensor",
        "heat_pump_energy_sensor",
    ])
    def test_any_wiring_key_is_present(self, key):
        assert install_modules({key: "x.y"}, ED_EMPTY, True)[Module.HEAT_PUMP] is Presence.PRESENT

    def test_an_additional_unit_list_is_present(self):
        v = install_modules({"heat_pumps": [{"id": "hp2"}]}, ED_EMPTY, True)
        assert v[Module.HEAT_PUMP] is Presence.PRESENT

    def test_tunables_alone_are_not_evidence(self):
        cfg = {"heat_pump_boost_offset": 2.0, "heat_pump_rated_power": 3000,
               "heat_pump_priority": 5}
        assert install_modules(cfg, ED_EMPTY, True)[Module.HEAT_PUMP] is Presence.ABSENT

    def test_config_only_so_never_unknown(self):
        assert install_modules({}, None, False)[Module.HEAT_PUMP] is Presence.ABSENT


class TestHotWater:

    def test_the_tank_entity_is_present(self):
        v = install_modules({"hot_water_entity": "water_heater.tank"}, ED_EMPTY, True)
        assert v[Module.HOT_WATER] is Presence.PRESENT

    def test_settings_alone_are_not_evidence(self):
        v = install_modules({"hot_water_max_temperature": 60}, None, False)
        assert v[Module.HOT_WATER] is Presence.ABSENT


class TestManagedCharger:
    """The #595 EV-TAB rule — not the same question as the EV module."""

    def test_no_charger(self):
        assert has_managed_charger({}) is False

    def test_charger_list(self):
        assert has_managed_charger({"ev_chargers": [{"id": "a"}]}) is True

    def test_legacy_power_sensor(self):
        assert has_managed_charger({"ev_charging_power_sensor": "sensor.wb"}) is True

    def test_dashboard_ev_alone_is_data_not_a_managed_charger(self):
        assert install_modules({}, ED_EV, True)[Module.EV] is Presence.PRESENT
        assert has_managed_charger({}) is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `~/bin/semtest tests/test_923_install_modules.py -v`
Expected: collection ERROR, `ModuleNotFoundError: ... coordinator.install_modules`.

- [ ] **Step 3: Write the oracle**

Create `coordinator/install_modules.py`:

```python
"""(#923) What this install HAS — one answer, three states.

SEM is a core (solar, grid, home, energy balance, totals, forecast) plus
hardware modules: a home battery, an EV charger, a heat pump, a hot-water
tank. Every surface that depends on a module — its entities, its dashboard
tab, the cards that reference it, the welcome text — asks THIS module, so
they cannot disagree. Before #923 "has a battery" was decided in four
places, each slightly differently (#857).

Two rules make the verdict safe to act on:

* It comes from CONFIGURATION, never from live sensor state. A sensor that
  is momentarily unavailable says nothing about whether the hardware exists
  — reading it as "absent" is #875 ("unread is not zero") at module scale.
* "I could not read the Energy Dashboard" is UNKNOWN, never ABSENT (#925).
  UNKNOWN keeps everything: a slow boot must never hide a real battery.

Pure stdlib on purpose — no Home Assistant import — so it can be tested
without an instance and loaded by ``~/bin/validate-sem.sh``.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Iterable, Mapping


class Module(Enum):
    BATTERY = "battery"
    EV = "ev"
    HEAT_PUMP = "heat_pump"
    HOT_WATER = "hot_water"


class Presence(Enum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


# Only WIRING counts — a key that connects SEM to a Home Assistant entity or
# service of that hardware. ``battery_capacity_kwh`` is deliberately absent:
# the options flow's Settings step saves it with a default for every install
# that passes through it (config_flow.py, step "settings"), so it describes a
# battery without proving one. Heat-pump tunables (boost offset, rated power,
# priority) are left out for the same reason.
BATTERY_WIRING_KEYS: tuple[str, ...] = (
    "battery_soc_sensor",
    "battery_power_sensor",
    "battery_discharge_control_entity",
    "battery_discharge_control_entities",
    "battery_force_discharge_control_entity",
    "battery_force_discharge_entities",
    "battery_strategy_control_entity",
    "battery_strategy_entities",
)
EV_WIRING_KEYS: tuple[str, ...] = (
    "ev_chargers",
    "ev_charging_power_sensor",
    "ev_power_sensor",
)
HEAT_PUMP_WIRING_KEYS: tuple[str, ...] = (
    "heat_pumps",
    "heat_pump_relay1_entity",
    "heat_pump_relay2_entity",
    "heat_pump_climate_entity",
    "heat_pump_sg_ready_service",
    "heat_pump_sg_ready_state_entity",
    "heat_pump_power_sensor",
    "heat_pump_energy_sensor",
)
HOT_WATER_WIRING_KEYS: tuple[str, ...] = ("hot_water_entity",)

# Every key the oracle reads. Setting one through set_option must reload the
# entry, or the module's entities wait for the next restart — pinned by
# tests/test_923_structural_keys.py against _SET_OPTION_STRUCTURAL_KEYS.
MODULE_EVIDENCE_KEYS: frozenset[str] = frozenset(
    BATTERY_WIRING_KEYS + EV_WIRING_KEYS + HEAT_PUMP_WIRING_KEYS + HOT_WATER_WIRING_KEYS
)

_EMPTY: tuple[Any, ...] = (None, "", [], {}, ())


def _wired(config: Mapping[str, Any], keys: Iterable[str]) -> bool:
    return any(config.get(key) not in _EMPTY for key in keys)


def has_managed_charger(config: Mapping[str, Any]) -> bool:
    """A charger SEM was TOLD about — the #595 rule for the EV tab and the
    welcome text's charge-mode line. Not the same question as "does this
    install have EV data": an Energy Dashboard EV consumer feeds
    ``sem_ev_power`` with no charger configured."""
    return bool(config.get("ev_chargers") or config.get("ev_charging_power_sensor"))


def install_modules(
    config: Mapping[str, Any],
    ed_config: Any | None,
    ed_answered: bool,
) -> dict[Module, Presence]:
    """The module verdict for one install.

    ``ed_config`` is the parsed Energy Dashboard config (an
    ``EnergyDashboardConfig``) or None. ``ed_answered`` is whether the Energy
    Dashboard question got an answer at all: True when the file was parsed
    OR provably does not exist, False when the read failed or has not run
    yet. Battery and EV can be declared there, so for them no answer means
    UNKNOWN. Heat pump and hot water exist only in SEM's own options, which
    are always readable — they are never UNKNOWN.
    """
    ed_battery = bool(getattr(ed_config, "has_battery", False)) if ed_config is not None else False
    ed_ev = bool(getattr(ed_config, "has_ev", False)) if ed_config is not None else False

    def _config_or_dashboard(wired: bool, declared: bool) -> Presence:
        if wired or declared:
            return Presence.PRESENT
        return Presence.ABSENT if ed_answered else Presence.UNKNOWN

    def _config_only(wired: bool) -> Presence:
        return Presence.PRESENT if wired else Presence.ABSENT

    return {
        Module.BATTERY: _config_or_dashboard(_wired(config, BATTERY_WIRING_KEYS), ed_battery),
        Module.EV: _config_or_dashboard(_wired(config, EV_WIRING_KEYS), ed_ev),
        Module.HEAT_PUMP: _config_only(_wired(config, HEAT_PUMP_WIRING_KEYS)),
        Module.HOT_WATER: _config_only(_wired(config, HOT_WATER_WIRING_KEYS)),
    }
```

- [ ] **Step 4: Run to verify they pass**

Run: `~/bin/semtest tests/test_923_install_modules.py -v`
Expected: all PASS (33 tests).

- [ ] **Step 5: Commit**

```bash
git add coordinator/install_modules.py tests/test_923_install_modules.py
git commit -m "feat(#923): the install-modules oracle — PRESENT/ABSENT/UNKNOWN from configuration"
```

---

### Task 2: The entity table and the keep rules

**Files:**
- Modify: `coordinator/install_modules.py` (append)
- Test: `tests/test_923_install_modules.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_923_install_modules.py` (add `import ast`, `import re`, `from collections import Counter`, `from pathlib import Path`, `from unittest.mock import MagicMock` to the imports at the top, and extend the `install_modules` import with the new names):

```python
from custom_components.solar_energy_management.coordinator.install_modules import (
    CORE_BY_DECISION,
    ENTITY_MODULES,
    absent_entity_ids,
    all_unknown,
    entity_kept,
    keeps,
    kept_descriptions,
    presence_of,
    presence_summary,
)

_ORACLE_SRC = Path(__file__).resolve().parents[1] / "coordinator" / "install_modules.py"
LOOKS_LIKE_A_MODULE = re.compile(
    r"battery|(^|_)ev(_|$)|heat_pump|hot_water|legionella|charg|session|vehicle")


def _static_lists():
    from custom_components.solar_energy_management.binary_sensor import BINARY_SENSOR_TYPES
    from custom_components.solar_energy_management.button import BUTTONS
    from custom_components.solar_energy_management.number import NUMBER_TYPES
    from custom_components.solar_energy_management.sensor import SENSOR_TYPES
    from custom_components.solar_energy_management.switch import SWITCH_TYPES
    return {"sensor": SENSOR_TYPES, "number": NUMBER_TYPES, "switch": SWITCH_TYPES,
            "binary_sensor": BINARY_SENSOR_TYPES, "button": BUTTONS}


def _static_keys():
    return {(p, d.key) for p, ds in _static_lists().items() for d in ds}


class TestTheTable:

    def test_every_row_names_an_entity_a_platform_creates(self):
        stale = sorted(set(ENTITY_MODULES) - _static_keys())
        assert not stale, f"rows for keys no platform creates: {stale}"

    def test_core_by_decision_rows_are_real_and_not_modules(self):
        assert set(CORE_BY_DECISION) <= _static_keys()
        assert not set(CORE_BY_DECISION) & set(ENTITY_MODULES)

    def test_every_module_look_alike_has_chosen(self):
        undecided = sorted(
            pk for pk in _static_keys()
            if LOOKS_LIKE_A_MODULE.search(pk[1])
            and pk not in ENTITY_MODULES and pk not in CORE_BY_DECISION
        )
        assert not undecided, (
            "an entity named like a module must be put in ENTITY_MODULES or, "
            f"with its reason, in CORE_BY_DECISION: {undecided}")

    def test_charging_state_is_core(self):
        # It carries the Home tab's today_plan and is the Config tab's
        # "set up" marker on EVERY install.
        assert ("sensor", "charging_state") not in ENTITY_MODULES

    @pytest.mark.parametrize("pk", [
        ("switch", "battery_may_assist_ev"),
        ("number", "battery_assist_max_power"),
        ("number", "battery_assist_min_surplus"),
        ("sensor", "flow_battery_to_ev_power"),
        ("sensor", "flow_battery_to_ev_energy"),
        ("sensor", "lifetime_ev_battery_share"),
    ])
    def test_battery_to_ev_needs_both(self, pk):
        assert ENTITY_MODULES[pk] == {Module.BATTERY, Module.EV}

    def test_the_counts_the_spec_states(self):
        by_module = Counter(frozenset(m) for m in ENTITY_MODULES.values())
        assert by_module[frozenset({Module.BATTERY})] == 59
        assert by_module[frozenset({Module.BATTERY, Module.EV})] == 6
        assert by_module[frozenset({Module.EV})] == 33
        assert by_module[frozenset({Module.HEAT_PUMP})] == 11
        assert by_module[frozenset({Module.HOT_WATER})] == 4
        assert len(ENTITY_MODULES) == 113

    def test_the_oracle_stays_importable_without_home_assistant(self):
        # validate-sem.sh loads this file by path on sem-dev, where HA is
        # not installed.
        tree = ast.parse(_ORACLE_SRC.read_text(encoding="utf-8"))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                roots.add((node.module or "").split(".")[0])
        assert roots <= {"__future__", "enum", "typing"}, roots


class TestKeepRules:
    ALL_ABSENT = {m: Presence.ABSENT for m in Module}

    def test_unknown_keeps(self):
        assert keeps(all_unknown(), [Module.BATTERY])

    def test_absent_drops(self):
        assert not keeps({Module.BATTERY: Presence.ABSENT}, [Module.BATTERY])

    def test_core_is_always_kept(self):
        assert entity_kept("sensor", "solar_power", self.ALL_ABSENT)
        assert entity_kept("sensor", "charging_state", self.ALL_ABSENT)

    def test_cross_module_drops_when_either_is_absent(self):
        p = {Module.BATTERY: Presence.PRESENT, Module.EV: Presence.ABSENT}
        assert not entity_kept("switch", "battery_may_assist_ev", p)
        assert entity_kept("sensor", "battery_soc", p)

    def test_kept_descriptions_filters_by_key(self):
        descs = [SimpleNamespace(key="battery_soc"), SimpleNamespace(key="solar_power")]
        kept = kept_descriptions("sensor", descs, {Module.BATTERY: Presence.ABSENT})
        assert [d.key for d in kept] == ["solar_power"]

    def test_absent_entity_ids_are_the_forced_ids(self):
        gone = absent_entity_ids({**all_unknown(), Module.BATTERY: Presence.ABSENT})
        assert "sensor.sem_battery_soc" in gone
        assert "switch.sem_battery_may_assist_ev" in gone
        assert "number.sem_battery_capacity" in gone
        assert "button.sem_backfill_battery_nights" in gone
        assert "sensor.sem_ev_power" not in gone
        assert "sensor.sem_solar_power" not in gone

    def test_nothing_is_absent_while_unknown(self):
        assert absent_entity_ids(all_unknown()) == frozenset()


class TestPresenceOf:

    def test_a_test_double_builds_everything(self):
        assert presence_of(MagicMock()) == all_unknown()

    def test_no_coordinator_builds_everything(self):
        assert presence_of(None) == all_unknown()

    def test_the_setup_verdict_is_returned_and_completed(self):
        p = presence_of(SimpleNamespace(setup_presence={Module.BATTERY: Presence.ABSENT}))
        assert p[Module.BATTERY] is Presence.ABSENT
        assert p[Module.EV] is Presence.UNKNOWN

    def test_summary(self):
        assert presence_summary({Module.BATTERY: Presence.ABSENT}) == {
            "battery": "absent", "ev": "unknown", "heat_pump": "unknown",
            "hot_water": "unknown"}
```

- [ ] **Step 2: Run to verify they fail**

Run: `~/bin/semtest tests/test_923_install_modules.py -v`
Expected: collection ERROR, `ImportError: cannot import name 'CORE_BY_DECISION'`.

- [ ] **Step 3: Append the table and rules to `coordinator/install_modules.py`**

```python
_B = frozenset({Module.BATTERY})
_E = frozenset({Module.EV})
_BE = frozenset({Module.BATTERY, Module.EV})
_HP = frozenset({Module.HEAT_PUMP})
_HW = frozenset({Module.HOT_WATER})


def _rows(platform: str, modules: frozenset, keys: tuple[str, ...]) -> dict:
    return {(platform, key): modules for key in keys}


# (platform, description key) -> the modules that entity needs. A key that is
# not here is CORE and is always created. Cross-module entities list every
# module they need — battery→EV assist needs both. The dashboard generator
# and validate-sem.sh read this same table, so the entity set, the dashboard
# and the validation cannot disagree.
ENTITY_MODULES: Mapping[tuple[str, str], frozenset[Module]] = {
    **_rows("sensor", _B, (
        "battery_capacity_drift_pct", "battery_charge_pacing",
        "battery_charge_power", "battery_cycles_estimated",
        "battery_discharge_power", "battery_dynamic_floor_pct",
        "battery_health_score", "battery_measured_capacity_kwh", "battery_power",
        "battery_priority_status", "battery_scheduler_deficit_kwh",
        "battery_scheduler_reason", "battery_scheduler_state",
        "battery_scheduler_target_soc", "battery_session_avg_power",
        "battery_session_cost", "battery_session_duration",
        "battery_session_energy", "battery_session_savings",
        "battery_session_solar_share", "battery_session_type", "battery_soc",
        "battery_spendable_kwh", "battery_status", "battery_stored_grid_share",
        "battery_temperature", "daily_battery_charge_energy",
        "daily_battery_charge_grid", "daily_battery_charge_solar",
        "daily_battery_discharge_energy", "daily_battery_grid_cost",
        "daily_battery_savings", "diag_battery_capacity", "diag_battery_sign",
        "flow_battery_to_grid_energy", "flow_battery_to_grid_power",
        "flow_battery_to_home_energy", "flow_battery_to_home_power",
        "flow_grid_to_battery_energy", "flow_grid_to_battery_power",
        "flow_solar_to_battery_energy", "flow_solar_to_battery_power",
        "monthly_battery_charge_energy", "monthly_battery_discharge_energy",
        "monthly_battery_savings", "yearly_battery_charge_energy",
        "yearly_battery_discharge_energy", "yearly_battery_savings",
    )),
    **_rows("number", _B, (
        "battery_auto_start_soc", "battery_buffer_soc", "battery_capacity",
        "battery_max_discharge_power", "battery_priority_soc",
    )),
    **_rows("switch", _B, (
        "battery_charge_pacing_enabled", "battery_may_export",
        "forecast_spending_enabled",
    )),
    **_rows("binary_sensor", _B, (
        "battery_charging", "battery_discharging",
    )),
    **_rows("button", _B, (
        "backfill_battery_nights",
    )),
    **_rows("sensor", _BE, (
        "flow_battery_to_ev_energy", "flow_battery_to_ev_power",
        "lifetime_ev_battery_share",
    )),
    **_rows("number", _BE, (
        "battery_assist_max_power", "battery_assist_min_surplus",
    )),
    **_rows("switch", _BE, (
        "battery_may_assist_ev",
    )),
    **_rows("sensor", _E, (
        "calculated_current", "charging_recommendation", "charging_strategy",
        "daily_ev_energy", "diag_charger_control", "energy_ev_solar_percentage",
        "ev_charger_count", "ev_power", "ev_remaining_range", "ev_taper_trend",
        "flow_grid_to_ev_energy", "flow_grid_to_ev_power",
        "flow_solar_to_ev_energy", "flow_solar_to_ev_power", "lifetime_ev_cost",
        "lifetime_ev_energy", "lifetime_ev_grid_share", "lifetime_ev_sessions",
        "lifetime_ev_solar", "lifetime_ev_solar_share",
        "monthly_ev_consumption_energy", "night_charging_status", "session_cost",
        "session_duration", "session_energy", "session_solar_share",
        "solar_charging_status", "vehicle_soc", "yearly_ev_energy",
    )),
    **_rows("number", _E, (
        "ev_disable_delay_seconds", "ev_enable_delay_seconds",
    )),
    **_rows("binary_sensor", _E, (
        "ev_charging", "ev_connected",
    )),
    **_rows("sensor", _HP, (
        "heat_pump_energy_month", "heat_pump_energy_shifted_today",
        "heat_pump_energy_today", "heat_pump_energy_total", "heat_pump_energy_year",
        "heat_pump_mode", "heat_pump_registration_status",
        "heat_pump_sg_ready_state",
    )),
    **_rows("number", _HP, (
        "heat_pump_boost_offset",
    )),
    **_rows("binary_sensor", _HP, (
        "heat_pump_registered", "heat_pump_solar_boost",
    )),
    **_rows("number", _HW, (
        "hot_water_max_temperature", "hot_water_solar_target",
        "legionella_interval_hours", "legionella_target_temp",
    )),
}

# Keys that LOOK like a module but are core on purpose. The naming ratchet in
# tests/test_923_install_modules.py makes every look-alike choose a side.
CORE_BY_DECISION: Mapping[tuple[str, str], str] = {
    ("sensor", "charging_state"): (
        "carries the Home tab's today_plan (solar peak, price windows, night) "
        "and is the Config tab's set-up marker — on every install"),
    ("sensor", "diag_charger_count"): (
        "how '0 chargers found' stays visible on an install without one"),
    ("sensor", "power_charge_cost"): (
        "the tariff's demand charge (load management), not EV charging"),
    ("number", "demand_charge_rate"): (
        "the tariff's demand-charge rate, not EV charging"),
}


def all_unknown() -> dict[Module, Presence]:
    return {module: Presence.UNKNOWN for module in Module}


def keeps(presence: Mapping[Module, Presence], required: Iterable[Module]) -> bool:
    """Something that needs ``required`` is kept unless one of them is
    definitively ABSENT — UNKNOWN keeps."""
    return all(presence.get(m, Presence.UNKNOWN) is not Presence.ABSENT for m in required)


def entity_kept(platform: str, key: str, presence: Mapping[Module, Presence]) -> bool:
    return keeps(presence, ENTITY_MODULES.get((platform, key), frozenset()))


def kept_descriptions(
    platform: str, descriptions: Iterable[Any], presence: Mapping[Module, Presence],
) -> list:
    """The static descriptions a platform creates for this install. The SAME
    list must feed the platform's stale-entity sweep: that sweep is what
    removes an ABSENT module's leftover registry entries (spec §6)."""
    return [d for d in descriptions if entity_kept(platform, d.key, presence)]


def presence_of(coordinator: Any) -> dict[Module, Presence]:
    """The verdict the platforms were built with (``setup_presence``). All
    UNKNOWN — build everything — when there is none: no coordinator, one
    from before the setup step, or a test double."""
    presence = getattr(coordinator, "setup_presence", None)
    if isinstance(presence, dict) and presence and all(
        isinstance(m, Module) and isinstance(p, Presence) for m, p in presence.items()
    ):
        return {**all_unknown(), **presence}
    return all_unknown()


def absent_entity_ids(presence: Mapping[Module, Presence]) -> frozenset[str]:
    """Entity ids of every module entity this install does NOT create —
    what the dashboard generator removes references to. SEM forces
    ``<platform>.sem_<key>`` for every static entity."""
    return frozenset(
        f"{platform}.sem_{key}"
        for (platform, key), modules in ENTITY_MODULES.items()
        if not keeps(presence, modules)
    )


def presence_summary(presence: Mapping[Module, Presence]) -> dict[str, str]:
    """``{"battery": "present", ...}`` — the diagnostic attribute and the
    downloadable diagnostics."""
    return {module.value: presence.get(module, Presence.UNKNOWN).value for module in Module}
```

- [ ] **Step 4: Run to verify they pass**

Run: `~/bin/semtest tests/test_923_install_modules.py -v`
Expected: all PASS. If `test_every_row_names_an_entity_a_platform_creates` fails, a key was renamed on develop — fix the row, never delete the test. If `test_every_module_look_alike_has_chosen` fails, a new entity landed since 11.09 — classify it.

- [ ] **Step 5: Commit**

```bash
git add coordinator/install_modules.py tests/test_923_install_modules.py
git commit -m "feat(#923): one table maps all 113 module entities; keep rules + naming ratchet"
```

---

### Task 3: The Energy Dashboard answer is its own value

**Files:**
- Modify: `ha_energy_reader.py:221-300` (`read_energy_dashboard_config`)
- Test: `tests/test_923_ed_outcome.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_923_ed_outcome.py`:

```python
"""#923 — "no Energy Dashboard" and "could not read it" are different answers.

read_energy_dashboard_config() returns None for both. That is fine for
reading sensors and wrong for deciding a battery is ABSENT (#925: "I could
not ask" is not "no"), so the oracle gets a sibling that keeps them apart."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management import ha_energy_reader
from custom_components.solar_energy_management.ha_energy_reader import (
    read_energy_dashboard_config,
    read_energy_dashboard_config_outcome,
)


def _hass(tmp_path):
    hass = MagicMock()
    hass.config.config_dir = str(tmp_path)

    async def _executor(func, *args):
        return func(*args)

    hass.async_add_executor_job = _executor
    return hass


def _write(tmp_path, text):
    (tmp_path / ".storage").mkdir(exist_ok=True)
    (tmp_path / ".storage" / "energy").write_text(text, encoding="utf-8")


@pytest.mark.asyncio
async def test_a_missing_file_is_a_definite_no(tmp_path):
    assert await read_energy_dashboard_config_outcome(_hass(tmp_path)) == (None, True)


@pytest.mark.asyncio
async def test_an_unparseable_file_is_unanswered(tmp_path):
    _write(tmp_path, "{not json")
    assert await read_energy_dashboard_config_outcome(_hass(tmp_path)) == (None, False)


@pytest.mark.asyncio
async def test_a_file_without_data_is_unanswered(tmp_path):
    _write(tmp_path, json.dumps({"version": 1}))
    assert await read_energy_dashboard_config_outcome(_hass(tmp_path)) == (None, False)


@pytest.mark.asyncio
async def test_a_parsed_file_answers_with_its_battery(tmp_path, monkeypatch):
    # The device-registry derivation needs a real hass; it is not what this
    # test is about.
    monkeypatch.setattr(ha_energy_reader, "_derive_missing_power_sensors",
                        lambda hass, config: None)
    _write(tmp_path, json.dumps({"data": {
        "energy_sources": [{"type": "battery",
                            "stat_energy_from": "sensor.bat_out",
                            "stat_energy_to": "sensor.bat_in"}],
        "device_consumption": [],
    }}))
    config, answered = await read_energy_dashboard_config_outcome(_hass(tmp_path))
    assert answered is True
    assert config is not None and config.has_battery is True


@pytest.mark.asyncio
async def test_the_old_reader_still_returns_only_the_config(tmp_path):
    assert await read_energy_dashboard_config(_hass(tmp_path)) is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `~/bin/semtest tests/test_923_ed_outcome.py -v`
Expected: ImportError, `cannot import name 'read_energy_dashboard_config_outcome'`.

- [ ] **Step 3: Split the reader**

In `ha_energy_reader.py`:

1. Rename the function and change its signature/docstring. Replace:

```python
async def read_energy_dashboard_config(
    hass: HomeAssistant, quiet: bool = False,
) -> Optional[EnergyDashboardConfig]:
    """Read sensor configuration from HA Energy Dashboard.

    Args:
        hass: Home Assistant instance
        quiet: Demote routine INFO logs to DEBUG. Used by the cold-start
            re-derivation retry (#274) so it doesn't spam the log each cycle.

    Returns:
        EnergyDashboardConfig with extracted sensor entity IDs, or None if not configured
    """
```

with:

```python
async def read_energy_dashboard_config_outcome(
    hass: HomeAssistant, quiet: bool = False,
) -> tuple[Optional[EnergyDashboardConfig], bool]:
    """Read the Energy Dashboard config AND whether the question got an answer.

    ``(config, True)`` — the file was read and parsed.
    ``(None, True)``   — the file does not exist: a definite "no dashboard".
    ``(None, False)``  — the read failed (malformed, no data section, I/O).

    (#923) The install-modules oracle may call a battery ABSENT only on an
    answer; ``read_energy_dashboard_config`` folds the last two cases into
    one ``None`` (#925: "I could not ask" is not "no").

    Args:
        hass: Home Assistant instance
        quiet: Demote routine INFO logs to DEBUG. Used by the cold-start
            re-derivation retry (#274) so it doesn't spam the log each cycle.
    """
```

2. Change exactly these five `return` statements inside it (leave the inner `read_file()`'s `return json.load(f)` alone):

| where | old | new |
|---|---|---|
| after `_info("Energy Dashboard not configured (file not found)")` | `return None` | `return None, True` |
| after `_LOGGER.warning("Energy Dashboard has no data section")` | `return None` | `return None, False` |
| end of the `try` body, after the `_info("Read Energy Dashboard config: ...")` call | `return config` | `return config, True` |
| `except json.JSONDecodeError` branch | `return None` | `return None, False` |
| `except Exception` branch | `return None` | `return None, False` |

3. Directly after the function, add the compatibility wrapper (every other caller keeps its name, and the tests that patch `<module>.read_energy_dashboard_config` keep working):

```python
async def read_energy_dashboard_config(
    hass: HomeAssistant, quiet: bool = False,
) -> Optional[EnergyDashboardConfig]:
    """Read sensor configuration from HA Energy Dashboard.

    Returns the EnergyDashboardConfig, or None when it is not configured OR
    not readable. Callers that must tell those apart use
    ``read_energy_dashboard_config_outcome`` (#923).
    """
    config, _answered = await read_energy_dashboard_config_outcome(hass, quiet=quiet)
    return config
```

- [ ] **Step 4: Run to verify they pass**

Run: `~/bin/semtest tests/test_923_ed_outcome.py -v`
then: `~/bin/semtest tests/test_e2e_hardware.py -k test_energy_dashboard_parsing -v`
Expected: all PASS (the second proves the wrapper still serves the old callers).

- [ ] **Step 5: Commit**

```bash
git add ha_energy_reader.py tests/test_923_ed_outcome.py
git commit -m "feat(#923): the Energy Dashboard read says whether it got an answer"
```

---

### Task 4: The coordinator owns the verdict

**Files:**
- Modify: `coordinator/coordinator.py:51` (import), `:539` (fields), `:1780-1790` (method + read)
- Modify: `__init__.py` (just before `# Setup platforms (critical - must succeed)`)
- Test: `tests/test_923_coordinator_presence.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_923_coordinator_presence.py`:

```python
"""#923 — the coordinator computes the module verdict once, after the Energy
Dashboard read and before any platform builds its entities."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator
from custom_components.solar_energy_management.coordinator.install_modules import (
    Module,
    Presence,
)

_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def test_install_presence_reads_the_raw_dashboard_and_its_answer():
    stub = SimpleNamespace(
        config={},
        _ed_raw_config=SimpleNamespace(has_battery=True, has_ev=False),
        _ed_answered=True,
    )
    presence = SEMCoordinator.install_presence(stub)
    assert presence[Module.BATTERY] is Presence.PRESENT
    assert presence[Module.EV] is Presence.ABSENT


def test_an_unanswered_dashboard_keeps_the_battery_unknown():
    stub = SimpleNamespace(config={}, _ed_raw_config=None, _ed_answered=False)
    assert SEMCoordinator.install_presence(stub)[Module.BATTERY] is Presence.UNKNOWN


def test_the_verdict_is_captured_between_the_dashboard_read_and_the_platforms():
    src = _INIT.read_text(encoding="utf-8")
    ed_read = src.index("await coordinator.async_initialize_energy_dashboard()")
    capture = src.index("coordinator.setup_presence = coordinator.install_presence()")
    forward = src.index("await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)")
    assert ed_read < capture < forward
```

- [ ] **Step 2: Run to verify they fail**

Run: `~/bin/semtest tests/test_923_coordinator_presence.py -v`
Expected: FAIL — `AttributeError: type object 'SEMCoordinator' has no attribute 'install_presence'`, and `ValueError: substring not found` for the capture line.

- [ ] **Step 3: Implement**

In `coordinator/coordinator.py`:

(a) Line 51, replace
```python
from ..ha_energy_reader import read_energy_dashboard_config, EnergyDashboardConfig
```
with
```python
from ..ha_energy_reader import read_energy_dashboard_config_outcome, EnergyDashboardConfig
from .install_modules import Module, Presence, module_verdict
```

(b) Directly after `self._energy_dashboard_config: Optional[EnergyDashboardConfig] = None` (line ~539), add:

```python
        # (#923) The Energy Dashboard as the install-modules oracle sees it:
        # the parsed config even when it is not "minimally configured", and
        # whether the question got an answer at all (#925 — unread ≠ no).
        self._ed_raw_config: Optional[EnergyDashboardConfig] = None
        self._ed_answered: bool = False
        # The verdict the platforms were built with — captured once in
        # async_setup_entry, after the Energy Dashboard read and before any
        # platform loads, so every platform gates on the SAME answer.
        self.setup_presence: Optional[Dict[Module, Presence]] = None
```

(c) Directly above `async def async_initialize_energy_dashboard(self, quiet: bool = False) -> bool:` add:

```python
    def install_presence(self) -> Dict[Module, Presence]:
        """(#923) What this install has right now — see install_modules.py."""
        return module_verdict(self.config, self._ed_raw_config, self._ed_answered)

```

(d) Inside `async_initialize_energy_dashboard`, replace
```python
            dashboard_config = await read_energy_dashboard_config(self.hass, quiet=quiet)
```
with
```python
            dashboard_config, answered = await read_energy_dashboard_config_outcome(
                self.hass, quiet=quiet)
            self._ed_raw_config = dashboard_config
            self._ed_answered = answered
```

In `__init__.py`, directly above the line `    # Setup platforms (critical - must succeed)`, add:

```python
    # (#923) ONE module verdict for every platform: captured here, after the
    # Energy Dashboard read above and before any platform builds entities —
    # so sensor, number, switch, the dashboard and the welcome text can never
    # disagree about what this install has.
    from .coordinator.install_modules import presence_summary
    coordinator.setup_presence = coordinator.install_presence()
    _LOGGER.info("Install modules: %s", presence_summary(coordinator.setup_presence))

```

- [ ] **Step 4: Run to verify they pass**

Run: `~/bin/semtest tests/test_923_coordinator_presence.py tests/test_setup_entry_lifecycle.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add coordinator/coordinator.py __init__.py tests/test_923_coordinator_presence.py
git commit -m "feat(#923): the coordinator owns the module verdict, captured before the platforms load"
```

---

### Task 5: The platforms build only what the install has

**Files:**
- Modify: `sensor.py:39` (import), `:1958-1970` (setup), `:2273-2280` (sweep list)
- Modify: `number.py:30` (import), `:325-335`, `:551`, `:585-592` (`_cleanup_stale_entities`)
- Modify: `switch.py:17` (import), `:128-180`
- Modify: `binary_sensor.py:19` (import), `:106-125`
- Modify: `button.py:16-37`
- Modify: `select.py:100-113` (`_has_battery`)
- Test: `tests/test_923_platform_gating.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_923_platform_gating.py`:

```python
"""#923 — each platform builds only the entities of modules the install has,
and its stale-entity sweep (fed the SAME gated list) removes an ABSENT
module's leftovers from the registry. UNKNOWN keeps everything.

Real registry (the ``hass`` fixture), test-double coordinator: the platform
setup is called directly, so nothing else of SEM needs to load."""
from __future__ import annotations

import importlib.util
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pytest_homeassistant_custom_component") is None,
    reason="pytest-homeassistant-custom-component not installed; CI runs these",
)

from homeassistant.helpers import entity_registry as er  # noqa: E402

from custom_components.solar_energy_management import (  # noqa: E402
    binary_sensor, button, number, select, switch,
)
from custom_components.solar_energy_management.const import DOMAIN  # noqa: E402
from custom_components.solar_energy_management.coordinator.install_modules import (  # noqa: E402
    Module, Presence,
)

ALL_ABSENT = {m: Presence.ABSENT for m in Module}
ALL_PRESENT = {m: Presence.PRESENT for m in Module}


def _entry(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={}, title="SEM #923")
    entry.add_to_hass(hass)
    return entry


def _coordinator(hass, entry, presence):
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.config_entry = entry
    coordinator.hass.config.currency = "EUR"
    coordinator.setup_presence = presence
    entry.runtime_data = coordinator
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    return coordinator


async def _run(platform_module, hass, entry):
    added: list = []
    await platform_module.async_setup_entry(hass, entry, lambda ents: added.extend(ents))
    return {e.entity_description.key for e in added}


def _seed(hass, entry, platform, unique_id):
    er.async_get(hass).async_get_or_create(
        platform, DOMAIN, unique_id, config_entry=entry)


def _exists(hass, platform, unique_id):
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id) is not None


@pytest.mark.asyncio
async def test_binary_sensor_builds_the_core_and_sweeps_an_absent_module(hass):
    entry = _entry(hass)
    _coordinator(hass, entry, ALL_ABSENT)
    _seed(hass, entry, "binary_sensor", "sem_battery_charging")
    _seed(hass, entry, "binary_sensor", "sem_solar_active")
    keys = await _run(binary_sensor, hass, entry)
    assert "solar_active" in keys
    assert not {"battery_charging", "ev_connected", "heat_pump_registered"} & keys
    assert not _exists(hass, "binary_sensor", "sem_battery_charging")
    assert _exists(hass, "binary_sensor", "sem_solar_active")


@pytest.mark.asyncio
async def test_binary_sensor_unknown_keeps_everything(hass):
    entry = _entry(hass)
    _coordinator(hass, entry, {m: Presence.UNKNOWN for m in Module})
    _seed(hass, entry, "binary_sensor", "sem_battery_charging")
    keys = await _run(binary_sensor, hass, entry)
    assert "battery_charging" in keys
    assert _exists(hass, "binary_sensor", "sem_battery_charging")


@pytest.mark.asyncio
async def test_number_drops_the_battery_and_its_legacy_unique_id(hass):
    entry = _entry(hass)
    _coordinator(hass, entry, ALL_ABSENT)
    _seed(hass, entry, "number", f"{entry.entry_id}_battery_capacity_kwh")
    keys = await _run(number, hass, entry)
    assert "battery_capacity" not in keys
    assert "hot_water_solar_target" not in keys
    assert "night_earliest_start" in keys
    # The legacy map used to keep this unique_id valid unconditionally.
    assert not _exists(hass, "number", f"{entry.entry_id}_battery_capacity_kwh")


@pytest.mark.asyncio
async def test_number_keeps_the_battery_when_present(hass):
    entry = _entry(hass)
    _coordinator(hass, entry, ALL_PRESENT)
    _seed(hass, entry, "number", f"{entry.entry_id}_battery_capacity_kwh")
    keys = await _run(number, hass, entry)
    assert {"battery_capacity", "battery_assist_max_power"} <= keys
    assert _exists(hass, "number", f"{entry.entry_id}_battery_capacity_kwh")


@pytest.mark.asyncio
async def test_switch_cross_module_follows_both(hass):
    entry = _entry(hass)
    _coordinator(hass, entry, {**ALL_PRESENT, Module.EV: Presence.ABSENT})
    _seed(hass, entry, "switch", "sem_battery_may_assist_ev")
    keys = await _run(switch, hass, entry)
    assert "battery_may_export" in keys
    assert "battery_may_assist_ev" not in keys
    assert not _exists(hass, "switch", "sem_battery_may_assist_ev")


@pytest.mark.asyncio
async def test_button_is_a_battery_entity_and_is_swept(hass):
    entry = _entry(hass)
    _coordinator(hass, entry, ALL_ABSENT)
    _seed(hass, entry, "button", "sem_backfill_battery_nights")
    keys = await _run(button, hass, entry)
    assert keys == set()
    assert not _exists(hass, "button", "sem_backfill_battery_nights")


def test_the_global_battery_select_asks_the_oracle():
    coordinator = MagicMock()
    coordinator.setup_presence = ALL_ABSENT
    assert select._has_battery(coordinator) is False
    coordinator.setup_presence = {m: Presence.UNKNOWN for m in Module}
    assert select._has_battery(coordinator) is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `~/bin/semtest tests/test_923_platform_gating.py -v`
Expected: FAIL — module entities still created (e.g. `battery_charging` in keys), legacy unique_id still present, `_has_battery` returns the old answer.

- [ ] **Step 3: Gate `sensor.py`**

After line 39 `from .coordinator import SEMCoordinator` add:
```python
from .coordinator.install_modules import kept_descriptions, presence_of
```

In `async_setup_entry`, replace:
```python
    coordinator: SEMCoordinator = entry.runtime_data
    _LOGGER.info("Got coordinator, creating %d sensors", len(SENSOR_TYPES))

    sensors = [
        SEMSolarSensor(coordinator, description, entry.entry_id)
        for description in SENSOR_TYPES
    ]
```
with:
```python
    coordinator: SEMCoordinator = entry.runtime_data
    # (#923) Only the sensors of modules this install has — UNKNOWN keeps.
    # The same list feeds the stale sweep below, which is what removes an
    # ABSENT module's leftovers from the registry.
    static_descriptions = kept_descriptions(
        "sensor", SENSOR_TYPES, presence_of(coordinator))
    _LOGGER.info("Got coordinator, creating %d sensors", len(static_descriptions))

    sensors = [
        SEMSolarSensor(coordinator, description, entry.entry_id)
        for description in static_descriptions
    ]
```

And in the sweep list near the end of the function replace `        list(SENSOR_TYPES)` with `        list(static_descriptions)`.

- [ ] **Step 4: Gate `number.py`**

After line 30 `from .coordinator import SEMCoordinator` add:
```python
from .coordinator.install_modules import kept_descriptions, presence_of
```

In `async_setup_entry` replace:
```python
    entities = [
        SEMNumberEntity(coordinator, description, entry)
        for description in NUMBER_TYPES
    ]
```
with:
```python
    # (#923) Only the numbers of modules this install has — UNKNOWN keeps.
    static_descriptions = kept_descriptions(
        "number", NUMBER_TYPES, presence_of(coordinator))
    entities = [
        SEMNumberEntity(coordinator, description, entry)
        for description in static_descriptions
    ]
```

Replace:
```python
    all_descriptions = list(NUMBER_TYPES) + per_charger_descriptions + per_battery_descriptions
```
with:
```python
    all_descriptions = list(static_descriptions) + per_charger_descriptions + per_battery_descriptions
```

In `_cleanup_stale_entities`, replace:
```python
        _LEGACY_UID_MAP = {"battery_capacity": "battery_capacity_kwh"}
        valid_keys.update(_LEGACY_UID_MAP.values())
```
with:
```python
        _LEGACY_UID_MAP = {"battery_capacity": "battery_capacity_kwh"}
        # (#923) A legacy unique_id is valid only while its entity is — the
        # unconditional add kept number.sem_battery_capacity alive on an
        # install whose battery module is ABSENT.
        valid_keys.update(v for k, v in _LEGACY_UID_MAP.items() if k in valid_keys)
```

- [ ] **Step 5: Gate `switch.py`**

After line 17 `from .coordinator import SEMCoordinator` add:
```python
from .coordinator.install_modules import kept_descriptions, presence_of
```

In `async_setup_entry` replace:
```python
    switches = [
        SEMSolarSwitch(coordinator, description, entry.entry_id)
        for description in SWITCH_TYPES
    ]
```
with:
```python
    # (#923) Only the switches of modules this install has — UNKNOWN keeps.
    static_descriptions = kept_descriptions(
        "switch", SWITCH_TYPES, presence_of(coordinator))
    switches = [
        SEMSolarSwitch(coordinator, description, entry.entry_id)
        for description in static_descriptions
    ]
```
Then in the same function replace `        for desc in SWITCH_TYPES:` with `        for desc in static_descriptions:` and replace `        valid_keys = {d.key for d in SWITCH_TYPES} | per_charger_keys` with `        valid_keys = {d.key for d in static_descriptions} | per_charger_keys`.

- [ ] **Step 6: Gate `binary_sensor.py` and give it a sweep**

After line 19 `from .coordinator import SEMCoordinator` add:
```python
from .coordinator.install_modules import kept_descriptions, presence_of
from .sensor import _cleanup_stale_entities
```

Replace the whole body of `async_setup_entry` (from `    coordinator: SEMCoordinator = entry.runtime_data` to `    async_add_entities(entities)`) with:

```python
    coordinator: SEMCoordinator = entry.runtime_data

    # (#923) Only the binary sensors of modules this install has — UNKNOWN keeps.
    static_descriptions = kept_descriptions(
        "binary_sensor", BINARY_SENSOR_TYPES, presence_of(coordinator))
    entities = [
        SEMSolarBinarySensor(coordinator, description, entry)
        for description in static_descriptions
    ]

    # Per-charger binary sensors (#193)
    full_config = {**entry.data, **entry.options}
    ev_chargers = full_config.get("ev_chargers", [])
    per_charger_descriptions = []
    for charger_cfg in ev_chargers:
        cid = charger_cfg.get("id", "ev_charger")
        description = BinarySensorEntityDescription(
            key=f"charger_{cid}_connected",
            device_class=BinarySensorDeviceClass.PLUG,
        )
        per_charger_descriptions.append(description)
        entities.append(SEMSolarBinarySensor(coordinator, description, entry))

    async_add_entities(entities)

    # (#923) binary_sensor had no stale sweep at all, so a removed or
    # module-gated key lingered in the registry forever. Same sweep the
    # sensor platform runs, same two unique_id formats.
    _cleanup_stale_entities(
        hass, entry, list(static_descriptions) + per_charger_descriptions,
        "binary_sensor")
```

- [ ] **Step 7: Gate `button.py` and give it a sweep**

Replace line 17 `from .sensor import _fix_entity_ids` with:
```python
from .coordinator.install_modules import kept_descriptions, presence_of
from .sensor import _cleanup_stale_entities, _fix_entity_ids
```

Replace:
```python
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(SEMButton(coordinator, d) for d in BUTTONS)
```
with:
```python
    coordinator = hass.data[DOMAIN][entry.entry_id]
    # (#923) The battery-night backfill is a battery entity.
    static_descriptions = kept_descriptions("button", BUTTONS, presence_of(coordinator))
    async_add_entities(SEMButton(coordinator, d) for d in static_descriptions)
```
and replace the last line `    _fix_entity_ids(hass, entry, list(BUTTONS), "button")` with:
```python
    _fix_entity_ids(hass, entry, static_descriptions, "button")
    _cleanup_stale_entities(hass, entry, static_descriptions, "button")
```

- [ ] **Step 8: `select._has_battery` asks the oracle**

In `select.py`, after line 16 `from .coordinator import SEMCoordinator` add:
```python
from .coordinator.install_modules import Module, keeps, presence_of
```

Replace the whole `_has_battery` function with:

```python
def _has_battery(coordinator: SEMCoordinator) -> bool:
    """Install has a battery — so the global battery mode selector (and, via
    number.py, the single-battery reserve number) is worth creating.

    (#923) Asks the install-modules oracle, like every other battery entity:
    kept unless the battery is definitively ABSENT. It used to look for
    ``sensor.sem_battery_soc`` in the registry — circular now that the oracle
    decides whether that sensor exists at all."""
    return keeps(presence_of(coordinator), (Module.BATTERY,))
```

Leave the `er` import: `_battery_slugs` (line ~87) and the stale sweep (line ~264) still use it.

- [ ] **Step 9: Run to verify they pass**

Run: `~/bin/semtest tests/test_923_platform_gating.py tests/test_746_max_current_field.py tests/test_switch.py tests/test_knob_wiring.py -v`
Expected: all PASS.

- [ ] **Step 10: Commit**

```bash
git add sensor.py number.py switch.py binary_sensor.py button.py select.py tests/test_923_platform_gating.py
git commit -m "feat(#923): platforms build only the modules the install has; the stale sweeps clear the rest"
```

---

### Task 6: The welcome text asks the oracle

**Files:**
- Modify: `__init__.py:361-393` (`build_welcome_message`), its call site (`"message": build_welcome_message(full_config),`)
- Modify: `tests/test_805_welcome_reflects_install.py`

- [ ] **Step 1: Re-pin and extend the tests**

In `tests/test_805_welcome_reflects_install.py`:

Add below the existing import:
```python
from custom_components.solar_energy_management.coordinator.install_modules import (
    Module, Presence,
)
```

Replace `test_a_battery_install_gets_its_reserve_line` and `test_the_dashboard_link_is_always_there` with:

```python
    def test_a_battery_install_gets_its_reserve_line(self):
        msg = build_welcome_message({"battery_soc_sensor": "sensor.soc"})
        assert "Battery tab" in msg
        assert "reserve" in msg.lower()

    def test_capacity_alone_does_not_claim_a_battery(self):
        # (#923) The Settings step saves battery_capacity_kwh with a default
        # for every install — it is not evidence, and a Battery tab it points
        # to would not exist on a battery-less install.
        assert "Battery tab" not in build_welcome_message({"battery_capacity_kwh": 10})

    def test_the_setup_verdict_wins(self):
        # A battery declared only in HA's Energy Dashboard: the config has no
        # battery key, the coordinator's verdict says PRESENT.
        verdict = {m: Presence.ABSENT for m in Module} | {Module.BATTERY: Presence.PRESENT}
        assert "Battery tab" in build_welcome_message({}, verdict)

    def test_an_unknown_battery_is_invited_not_directed(self):
        verdict = {m: Presence.UNKNOWN for m in Module}
        msg = build_welcome_message({}, verdict)
        assert "Battery tab" not in msg
        assert "Add your home battery" in msg

    def test_the_dashboard_link_is_always_there(self):
        for cfg in ({}, {"battery_soc_sensor": "sensor.soc"}):
            assert "/sem-dashboard/home" in build_welcome_message(cfg)
```

- [ ] **Step 2: Run to verify the new ones fail**

Run: `~/bin/semtest tests/test_805_welcome_reflects_install.py -v`
Expected: FAIL on `test_capacity_alone_does_not_claim_a_battery` and `test_the_setup_verdict_wins` (TypeError: takes 1 positional argument).

- [ ] **Step 3: Implement**

Change the signature line to:
```python
def build_welcome_message(config: dict, presence: dict | None = None) -> str:
```

Append to its docstring (before the closing `"""`):
```
    (#923) Both answers come from the install-modules oracle: the EV line
    from ``has_managed_charger`` (the #595 tab rule), the battery line from
    the setup verdict — PRESENT only, because an UNKNOWN battery must be
    invited, not sent to a tab.
```

Replace:
```python
    has_ev = bool(config.get("ev_chargers")
                  or config.get("ev_charging_power_sensor"))
    has_battery = bool(config.get("battery_capacity_kwh")
                       or config.get("battery_soc_sensor")
                       or config.get("battery_power_sensor"))
```
with:
```python
    from .coordinator.install_modules import (
        Module, Presence, has_managed_charger, module_verdict,
    )
    if presence is None:
        presence = module_verdict(config, None, False)
    has_ev = has_managed_charger(config)
    has_battery = presence.get(Module.BATTERY) is Presence.PRESENT
```

At the call site replace `"message": build_welcome_message(full_config),` with `"message": build_welcome_message(full_config, coordinator.setup_presence),`.

- [ ] **Step 4: Run to verify they pass**

Run: `~/bin/semtest tests/test_805_welcome_reflects_install.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add __init__.py tests/test_805_welcome_reflects_install.py
git commit -m "feat(#923): the welcome text asks the oracle; capacity alone no longer claims a battery"
```

---

### Task 7: Every module wiring key reloads when set

**Files:**
- Modify: `__init__.py:244-296` (`_SET_OPTION_STRUCTURAL_KEYS`)
- Test: `tests/test_923_structural_keys.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_923_structural_keys.py`:

```python
"""#923 — adding hardware through set_option must create its entities.

set_option reloads the entry only for _SET_OPTION_STRUCTURAL_KEYS. A module
wiring key outside that set would be stored and do nothing visible until the
next restart: the module's entities are created at platform setup."""
from custom_components.solar_energy_management import _SET_OPTION_STRUCTURAL_KEYS
from custom_components.solar_energy_management.coordinator.install_modules import (
    MODULE_EVIDENCE_KEYS,
)


def test_every_module_wiring_key_reloads_when_set():
    missing = sorted(MODULE_EVIDENCE_KEYS - _SET_OPTION_STRUCTURAL_KEYS)
    assert not missing, f"module wiring keys that would not reload: {missing}"
```

- [ ] **Step 2: Run to verify it fails**

Run: `~/bin/semtest tests/test_923_structural_keys.py -v`
Expected: FAIL listing `ev_charging_power_sensor, ev_power_sensor, heat_pump_sg_ready_service, heat_pump_sg_ready_state_entity, heat_pumps`.

- [ ] **Step 3: Implement**

In `__init__.py`, replace the closing lines of the set:
```python
    "battery_setpoint_bidirectional",
})
```
with:
```python
    "battery_setpoint_bidirectional",
    # (#923) Module wiring the install-modules oracle reads. Setting one
    # through set_option must reload, or the module's entities are not
    # created until the next restart. tests/test_923_structural_keys.py
    # keeps every MODULE_EVIDENCE_KEYS entry in this set.
    "ev_charging_power_sensor", "ev_power_sensor", "heat_pumps",
    "heat_pump_sg_ready_service", "heat_pump_sg_ready_state_entity",
})
```

- [ ] **Step 4: Run to verify it passes (and the #528 parity still holds)**

Run: `~/bin/semtest tests/test_923_structural_keys.py tests/test_528_structural_keys_parity.py tests/test_set_option_smart_merge.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add __init__.py tests/test_923_structural_keys.py
git commit -m "feat(#923): every module wiring key reloads the entry when set"
```

---

### Task 8: The dashboard prunes in lockstep

**Files:**
- Modify: `features/dashboard_generator.py:225-227` (call site), `:248-300` (replace `_prune_ev_view_if_no_charger`), `:630-639` (K-Flow flags)
- Modify: `tests/test_595_hide_ev_view.py` (re-pin — full replacement below)
- Test: `tests/test_923_dashboard_prune.py`

- [ ] **Step 1: Write the failing tests**

Replace `tests/test_595_hide_ev_view.py` entirely with:

```python
"""#595/#614/#923 — absent hardware is hidden.

The EV tab is removed when no charger is configured (#595 — the EV tab is
the control surface for a charger SEM was told about), the Battery tab when
the battery module is ABSENT (#923), and the diagram cards get show_ev /
show_battery flags so they don't draw ghost nodes (#614).

Since #923 the battery verdict is not recomputed here: the generator asks
the coordinator for the verdict its platforms were built with
(``setup_presence``), so the dashboard and the entity set cannot disagree.
Which configuration means "battery" is the oracle's to test
(tests/test_923_install_modules.py)."""

from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.install_modules import (
    Module, Presence,
)
from custom_components.solar_energy_management.features.dashboard_generator import (
    DashboardGenerator,
)

PRESENT = {m: Presence.PRESENT for m in Module}
ABSENT = {m: Presence.ABSENT for m in Module}
NO_BATTERY = {**PRESENT, Module.BATTERY: Presence.ABSENT}


def _generator(full_config, presence=None):
    hass = MagicMock()
    entry = MagicMock()
    entry.data = full_config
    entry.options = {}
    if presence is not None:
        entry.runtime_data.setup_presence = presence
    hass.config_entries.async_entries.return_value = [entry]
    hass.data = {}
    return DashboardGenerator(hass)


def _template():
    return {"views": [
        {"title": "Home", "path": "home"},
        {"title": "EV", "path": "ev"},
        {"title": "Battery", "path": "battery"},
    ]}


def test_ev_tab_removed_when_no_charger():
    gen = _generator({})  # no ev_chargers, no ev_charging_power_sensor
    tpl = _template()
    gen._prune_absent_modules(tpl)
    paths = [v["path"] for v in tpl["views"]]
    assert "ev" not in paths
    assert paths == ["home", "battery"]  # battery verdict UNKNOWN → kept


def test_ev_tab_kept_when_charger_configured():
    gen = _generator({"ev_chargers": [{"id": "ev_charger"}]})
    tpl = _template()
    gen._prune_absent_modules(tpl)
    assert "ev" in [v["path"] for v in tpl["views"]]


def test_ev_tab_kept_with_legacy_power_sensor():
    gen = _generator({"ev_charging_power_sensor": "sensor.keba_power"})
    tpl = _template()
    gen._prune_absent_modules(tpl)
    assert "ev" in [v["path"] for v in tpl["views"]]


def test_no_entries_is_a_noop():
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = []
    gen = DashboardGenerator(hass)
    tpl = _template()
    gen._prune_absent_modules(tpl)
    assert len(tpl["views"]) == 3  # unchanged


def test_battery_tab_removed_when_the_battery_is_absent():
    gen = _generator({"ev_chargers": [{"id": "ev_charger"}]}, NO_BATTERY)
    tpl = _template()
    gen._prune_absent_modules(tpl)
    assert [v["path"] for v in tpl["views"]] == ["home", "ev"]


def test_battery_tab_kept_while_the_verdict_is_unknown():
    gen = _generator({"ev_chargers": [{"id": "ev_charger"}]})
    tpl = _template()
    gen._prune_absent_modules(tpl)
    assert "battery" in [v["path"] for v in tpl["views"]]


def _template_with_diagram_cards():
    return {"views": [
        {"title": "Home", "path": "home", "cards": [
            {"type": "vertical-stack", "cards": [
                {"type": "custom:sem-system-diagram-card", "entity_prefix": "sensor.sem_"},
            ]},
        ]},
        {"title": "EV", "path": "ev", "cards": []},
        {"title": "Energy", "path": "energy", "cards": [
            {"type": "custom:sem-flow-card", "entity_prefix": "sensor.sem_"},
        ]},
    ]}


def test_diagram_cards_get_show_ev_false_when_no_charger():
    """#595 follow-up — the reporter's circled complaint: the system
    overview diagram still drew an EV node. Both SEM diagram cards must
    receive show_ev:false, including when nested in stacks."""
    gen = _generator({})
    tpl = _template_with_diagram_cards()
    gen._prune_absent_modules(tpl)
    diagram = tpl["views"][0]["cards"][0]["cards"][0]
    flow = tpl["views"][1]["cards"][0]  # EV view pruned → energy shifts up
    assert diagram["show_ev"] is False
    assert flow["show_ev"] is False


def test_diagram_cards_untouched_when_everything_is_present():
    gen = _generator({"ev_chargers": [{"id": "ev_charger"}]}, PRESENT)
    tpl = _template_with_diagram_cards()
    gen._prune_absent_modules(tpl)
    diagram = tpl["views"][0]["cards"][0]["cards"][0]
    assert "show_ev" not in diagram
    assert "show_battery" not in diagram


def test_battery_flag_injected_when_the_battery_is_absent():
    """#614 — battery sibling of the ghost-node class."""
    gen = _generator({"ev_chargers": [{"id": "ev_charger"}]}, NO_BATTERY)
    tpl = _template_with_diagram_cards()
    gen._prune_absent_modules(tpl)
    diagram = tpl["views"][0]["cards"][0]["cards"][0]
    assert diagram["show_battery"] is False
    assert "show_ev" not in diagram          # EV present → untouched
    assert "ev" in [v["path"] for v in tpl["views"]]


def test_battery_flag_not_injected_when_the_battery_is_present():
    gen = _generator({}, {**ABSENT, Module.BATTERY: Presence.PRESENT})
    tpl = _template_with_diagram_cards()
    gen._prune_absent_modules(tpl)
    diagram = tpl["views"][0]["cards"][0]["cards"][0]
    assert "show_battery" not in diagram
    assert diagram["show_ev"] is False       # no charger → EV hidden


def test_battery_flag_not_injected_while_unknown():
    """A battery-less verdict must never come from an incomplete read."""
    gen = _generator({})
    tpl = _template_with_diagram_cards()
    gen._prune_absent_modules(tpl)
    diagram = tpl["views"][0]["cards"][0]["cards"][0]
    assert "show_battery" not in diagram


def test_both_flags_when_solar_only_install():
    gen = _generator({}, ABSENT)
    tpl = _template_with_diagram_cards()
    gen._prune_absent_modules(tpl)
    diagram = tpl["views"][0]["cards"][0]["cards"][0]
    assert diagram["show_ev"] is False
    assert diagram["show_battery"] is False
```

Create `tests/test_923_dashboard_prune.py`:

```python
"""#923 — the real dashboard template, pruned for a minimal install, holds no
reference to an entity the install does not create; a full install loses
nothing; an unknown verdict prunes nothing."""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import yaml

from custom_components.solar_energy_management.coordinator.install_modules import (
    Module, Presence, absent_entity_ids,
)
from custom_components.solar_energy_management.features.dashboard_generator import (
    DashboardGenerator,
)

TEMPLATE = Path(__file__).resolve().parents[1] / "dashboard" / "sem_dashboard_template.yaml"
ABSENT = {m: Presence.ABSENT for m in Module}
PRESENT = {m: Presence.PRESENT for m in Module}


def _generator(full_config, presence=None):
    hass = MagicMock()
    entry = MagicMock()
    entry.data = full_config
    entry.options = {}
    if presence is not None:
        entry.runtime_data.setup_presence = presence
    hass.config_entries.async_entries.return_value = [entry]
    hass.data = {}
    return DashboardGenerator(hass)


def _template():
    return yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))


def _dump(tpl):
    return json.dumps(tpl, sort_keys=True)


def test_a_minimal_install_references_no_absent_entity():
    tpl = _template()
    _generator({}, ABSENT)._prune_absent_modules(tpl)
    assert {"battery", "ev"}.isdisjoint(v.get("path") for v in tpl["views"])
    dumped = _dump(tpl)
    leftovers = sorted(
        eid for eid in absent_entity_ids(ABSENT)
        if re.search(rf"(?<![a-z0-9_.]){re.escape(eid)}(?![a-z0-9_])", dumped))
    assert not leftovers, leftovers


def test_the_sankey_keeps_its_core_nodes():
    tpl = _template()
    _generator({}, ABSENT)._prune_absent_modules(tpl)
    dumped = _dump(tpl)
    for core in ("sensor.sem_daily_solar_energy", "sensor.sem_flow_solar_to_home_energy",
                 "sensor.sem_daily_home_energy", "sensor.sem_daily_grid_export_energy"):
        assert core in dumped


def test_a_full_install_loses_nothing():
    tpl = _template()
    before = _dump(tpl)
    _generator({"ev_chargers": [{"id": "ev_charger"}]}, PRESENT)._prune_absent_modules(tpl)
    assert _dump(tpl) == before


def test_an_unknown_verdict_prunes_nothing():
    tpl = _template()
    before = _dump(tpl)
    _generator({"ev_chargers": [{"id": "ev_charger"}]})._prune_absent_modules(tpl)
    assert _dump(tpl) == before


def test_dashboard_ev_data_keeps_ev_entities_but_not_the_ev_tab():
    tpl = _template()
    _generator({}, {**ABSENT, Module.EV: Presence.PRESENT})._prune_absent_modules(tpl)
    assert "ev" not in [v.get("path") for v in tpl["views"]]
    assert "sensor.sem_flow_solar_to_ev_energy" in _dump(tpl)


def test_an_emptied_stack_is_removed():
    tpl = {"views": [{"path": "home", "cards": [
        {"type": "vertical-stack", "cards": [
            {"type": "custom:sem-gauge-card", "entity": "sensor.sem_battery_soc"},
        ]},
        {"type": "custom:sem-gauge-card", "entity": "sensor.sem_autarky_rate"},
    ]}]}
    _generator({}, ABSENT)._prune_absent_modules(tpl)
    assert tpl["views"][0]["cards"] == [
        {"type": "custom:sem-gauge-card", "entity": "sensor.sem_autarky_rate"}]
```

- [ ] **Step 2: Run to verify they fail**

Run: `~/bin/semtest tests/test_595_hide_ev_view.py tests/test_923_dashboard_prune.py -v`
Expected: FAIL — `AttributeError: 'DashboardGenerator' object has no attribute '_prune_absent_modules'`.

- [ ] **Step 3: Implement in `features/dashboard_generator.py`**

(a) At the call site replace:
```python
            # #595 — drop the EV tab entirely on installs with no EV charger, so
            # battery/solar-only setups don't get a cluttered empty EV section.
            self._prune_ev_view_if_no_charger(template)
```
with:
```python
            # #595/#923 — the dashboard shows what this install has: no tab,
            # node or reference for hardware the platforms did not build.
            self._prune_absent_modules(template)
```

(b) Replace the whole `_prune_ev_view_if_no_charger` method (from `    def _prune_ev_view_if_no_charger` down to the end of its `if flags:` block, just before `    async def _substitute_sankey_if_missing`) with:

```python
    def _install_presence(self) -> Dict[Any, Any]:
        """(#923) The module verdict the platforms were built with — asked of
        the coordinator, never recomputed here, so the dashboard and the
        entity set cannot disagree. All UNKNOWN (prune nothing) when no
        coordinator is loaded."""
        from ..const import DOMAIN
        from ..coordinator.install_modules import all_unknown, presence_of

        entries = self.hass.config_entries.async_entries(DOMAIN)
        if not entries:
            return all_unknown()
        return presence_of(getattr(entries[0], "runtime_data", None))

    def _prune_absent_modules(self, template: Dict[str, Any]) -> None:
        """#595/#614/#923 — the dashboard shows what this install has.

        * No managed charger → the ``ev`` view is removed (#595, unchanged:
          the EV tab is the CONTROL surface for a charger SEM was told
          about) and the diagram cards get ``show_ev: false``.
        * Battery ABSENT → the ``battery`` view is removed (#923) and the
          diagram cards get ``show_battery: false`` (#614).
        * Any module ABSENT → every explicit reference to one of its
          entities leaves the remaining views: a sankey node or children
          link, a card whose ``entity`` it is, a stack left empty.

        UNKNOWN prunes nothing — a battery-less verdict must never come from
        an incomplete read (the #614 rule, now the oracle's). Most SEM cards
        take ``entity_prefix`` and pick entities themselves; they are not
        pruned here and must tolerate absence (tests/test_923_cards_*)."""
        from ..const import DOMAIN
        from ..coordinator.install_modules import (
            Module, Presence, absent_entity_ids, has_managed_charger,
        )

        entries = self.hass.config_entries.async_entries(DOMAIN)
        if not entries:
            return
        full = {**entries[0].data, **entries[0].options}
        presence = self._install_presence()
        managed_charger = has_managed_charger(full)
        battery_absent = presence.get(Module.BATTERY) is Presence.ABSENT

        drop_paths = set()
        if not managed_charger:
            drop_paths.add("ev")
        if battery_absent:
            drop_paths.add("battery")
        views = template.get("views", [])
        kept = [v for v in views if v.get("path") not in drop_paths]
        if len(kept) != len(views):
            template["views"] = kept
            views = kept
            _LOGGER.info("#595/#923 — removed tab(s) for absent hardware: %s",
                         sorted(drop_paths))

        flags = {}
        if not managed_charger:
            flags["show_ev"] = False
        if battery_absent:
            flags["show_battery"] = False
        if flags:
            hidden = self._set_node_flags(views, flags)
            if hidden:
                _LOGGER.info(
                    "#595/#614 — hid absent-hardware node(s) %s on %d diagram card(s)",
                    sorted(flags), hidden,
                )

        gone = absent_entity_ids(presence)
        if gone:
            removed = self._drop_entity_refs(views, gone)
            if removed:
                _LOGGER.info(
                    "#923 — removed %d dashboard reference(s) to entities this "
                    "install does not have", removed)

    @staticmethod
    def _entity_ref(item: Any) -> Optional[str]:
        """The entity an item stands for: a bare id string, or the
        ``entity_id`` / ``entity`` of a dict (sankey node, card config)."""
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            ref = item.get("entity_id", item.get("entity"))
            return ref if isinstance(ref, str) else None
        return None

    def _drop_entity_refs(self, node: Any, gone: frozenset) -> int:
        """Remove, recursively, every list item that references an entity in
        ``gone`` — then any card whose ``cards`` list ended up empty.
        Returns the number of items removed."""
        removed = 0
        if isinstance(node, dict):
            for value in node.values():
                removed += self._drop_entity_refs(value, gone)
        elif isinstance(node, list):
            keep = []
            for item in node:
                if self._entity_ref(item) in gone:
                    removed += 1
                    continue
                removed += self._drop_entity_refs(item, gone)
                if (isinstance(item, dict) and "type" in item
                        and isinstance(item.get("cards"), list) and not item["cards"]):
                    removed += 1
                    continue
                keep.append(item)
            node[:] = keep
        return removed
```

(`Optional`, `Dict` and `Any` are already imported at line 9.)

(c) In `_inject_kflow_card` replace:
```python
        # Determine has_battery / has_ev from config entry
        entries = self.hass.config_entries.async_entries(DOMAIN)
        has_battery = False
        has_ev = False
        if entries:
            full_config = {**entries[0].data, **entries[0].options}
            has_battery = bool(full_config.get("battery_soc_sensor")) or (
                ed_config and getattr(ed_config, "has_battery", False)
            )
            has_ev = bool(full_config.get("ev_chargers") or full_config.get("ev_charging_power_sensor"))
```
with:
```python
        # Determine has_battery / has_ev — (#923) the battery from the one
        # oracle (UNKNOWN keeps the section), the EV section from the #595
        # managed-charger rule, same as the EV tab.
        from ..coordinator.install_modules import Module, Presence, has_managed_charger
        entries = self.hass.config_entries.async_entries(DOMAIN)
        has_battery = False
        has_ev = False
        if entries:
            full_config = {**entries[0].data, **entries[0].options}
            has_battery = self._install_presence().get(Module.BATTERY) is not Presence.ABSENT
            has_ev = has_managed_charger(full_config)
```

- [ ] **Step 4: Run to verify they pass**

Run: `~/bin/semtest tests/test_595_hide_ev_view.py tests/test_923_dashboard_prune.py -v`
Expected: all PASS. If `test_a_minimal_install_references_no_absent_entity` lists leftovers, read where each sits in the template: a new reference shape (a Jinja string, an `entities:` row with a different key) needs `_entity_ref` extended — never an entry in the test's allow-list.

- [ ] **Step 5: Commit**

```bash
git add features/dashboard_generator.py tests/test_595_hide_ev_view.py tests/test_923_dashboard_prune.py
git commit -m "feat(#923): the dashboard prunes absent modules in lockstep with the entity set"
```

---

### Task 9: Cards tolerate a missing module

**Files:**
- Modify: `dashboard/card/src/cards/sem-load-priority-card.js:403`
- Regenerate: `dashboard/card/dist/sem-cards.js`
- Test: `tests/test_923_cards_tolerate_absent.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_923_cards_tolerate_absent.py`:

```python
"""#923 — a card must survive a module's entities not existing.

On a battery-less install ``hass.states['sensor.sem_battery_soc']`` is
``undefined``. ``states[x].state`` then throws inside render and Lovelace
paints an error card. Every read goes through ``?.``."""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "dashboard" / "card" / "src"
UNGUARDED = re.compile(r"states\[[^\]]+\]\.[A-Za-z_]")


def test_no_card_dereferences_a_state_lookup_unguarded():
    hits = []
    for js in sorted(SRC.rglob("*.js")):
        for n, line in enumerate(js.read_text(encoding="utf-8").splitlines(), 1):
            if UNGUARDED.search(line):
                hits.append(f"{js.relative_to(SRC)}:{n}: {line.strip()}")
    assert not hits, "unguarded state reads (use ?.):\n" + "\n".join(hits)
```

- [ ] **Step 2: Run to verify it fails**

Run: `~/bin/semtest tests/test_923_cards_tolerate_absent.py -v`
Expected: FAIL naming `cards/sem-load-priority-card.js:403`.

- [ ] **Step 3: Fix and rebuild**

In `dashboard/card/src/cards/sem-load-priority-card.js` line 403 replace
```js
                        ? (parseFloat(this._hass.states[info.power_entity].state) || 0)
```
with
```js
                        ? (parseFloat(this._hass.states[info.power_entity]?.state) || 0)
```

Then:
```bash
cd dashboard/card && npm run build && npm test && cd ../..
```
Expected: rollup writes `dist/sem-cards.js`; `node --test` all pass.

- [ ] **Step 4: Run to verify it passes**

Run: `~/bin/semtest tests/test_923_cards_tolerate_absent.py tests/test_card_template_lint.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/card/src/cards/sem-load-priority-card.js dashboard/card/dist/sem-cards.js tests/test_923_cards_tolerate_absent.py
git commit -m "fix(#923): the load-priority card survives a missing power entity; lint every state read"
```

---

### Task 10: The verdict is visible

**Files:**
- Modify: `sensor.py` (`diag_ed_config` attribute block, ~line 3290)
- Modify: `diagnostics.py:13-15` (import), `:506-507` (return dict)
- Test: `tests/test_923_verdict_visible.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_923_verdict_visible.py`:

```python
"""#923 — "where is my battery tab?" is answered on the install itself: the
verdict rides on sensor.sem_diag_ed_config and in the diagnostics download."""
from unittest.mock import MagicMock

from homeassistant.components.sensor import SensorEntityDescription

from custom_components.solar_energy_management.coordinator.install_modules import (
    Module, Presence,
)
from custom_components.solar_energy_management.sensor import SEMSolarSensor


def _diag_sensor(presence):
    coord = MagicMock()
    coord.data = {"last_update": "x"}
    coord.last_update_success = True
    coord.get_ed_config_detail.return_value = {}
    coord.setup_presence = presence
    return SEMSolarSensor(
        coordinator=coord,
        description=SensorEntityDescription(key="diag_ed_config", name="x"),
        entry_id="e",
    )


def test_the_diagnostic_sensor_carries_the_verdict():
    s = _diag_sensor({m: Presence.ABSENT for m in Module} | {Module.EV: Presence.PRESENT})
    assert s.extra_state_attributes["install_modules"] == {
        "battery": "absent", "ev": "present", "heat_pump": "absent", "hot_water": "absent"}


def test_no_verdict_no_attribute():
    s = _diag_sensor(None)
    assert "install_modules" not in s.extra_state_attributes
```

- [ ] **Step 2: Run to verify it fails**

Run: `~/bin/semtest tests/test_923_verdict_visible.py -v`
Expected: FAIL — `KeyError: 'install_modules'`.

- [ ] **Step 3: Implement**

In `sensor.py`, replace:
```python
        if self.entity_description.key == "diag_ed_config":
            try:
                detail = self.coordinator.get_ed_config_detail()
                if detail:
                    attrs["energy_dashboard"] = detail
            except Exception:
                pass
```
with:
```python
        if self.entity_description.key == "diag_ed_config":
            try:
                detail = self.coordinator.get_ed_config_detail()
                if detail:
                    attrs["energy_dashboard"] = detail
            except Exception:
                pass
            # (#923) What this install has — the verdict every platform and
            # the dashboard were built on. Support's first stop for "where is
            # my battery tab"; validate-sem.sh reads it too.
            presence = getattr(self.coordinator, "setup_presence", None)
            if isinstance(presence, dict):
                attrs["install_modules"] = presence_summary(presence)
```
and extend the Task 5 import line in `sensor.py` to
```python
from .coordinator.install_modules import kept_descriptions, presence_of, presence_summary
```

In `diagnostics.py`, after line 14 `from .coordinator import SEMCoordinator` add:
```python
from .coordinator.install_modules import presence_of, presence_summary
```
and in the returned dict replace
```python
    return {
        "detection": detection,
```
with
```python
    return {
        "detection": detection,
        # (#923) the module verdict the platforms and the dashboard were built on
        "install_modules": presence_summary(presence_of(coordinator)),
```

- [ ] **Step 4: Run to verify it passes**

Run: `~/bin/semtest tests/test_923_verdict_visible.py tests/test_diagnostics.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sensor.py diagnostics.py tests/test_923_verdict_visible.py
git commit -m "feat(#923): the module verdict is on sem_diag_ed_config and in the diagnostics"
```

---

### Task 11: Hardware added later gets its entities

**Files:**
- Modify: `coordinator/install_modules.py` (append the guard)
- Modify: `coordinator/coordinator.py` (import, `_check_module_growth`, call at the end of `async_initialize_energy_dashboard`)
- Modify: `__init__.py` (listener function + call after the platforms load)
- Modify: `manifest.json` (`after_dependencies`)
- Test: `tests/test_923_module_growth.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_923_module_growth.py`:

```python
"""#923 — a module that appears after setup (a battery added to HA's Energy
Dashboard changes no SEM option) gets its entities through ONE reload.

Guarded: only ABSENT → PRESENT counts, once per transition, and at most one
module-driven reload per 10 minutes across reloads."""
from __future__ import annotations

import importlib.util
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.const import DOMAIN
from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator
from custom_components.solar_energy_management.coordinator.install_modules import (
    MODULE_RELOAD_MIN_INTERVAL_S, Module, Presence, module_reload_due, modules_grown,
)

ABSENT = {m: Presence.ABSENT for m in Module}
BATTERY_NOW = {**ABSENT, Module.BATTERY: Presence.PRESENT}


class TestTheGuard:

    def test_absent_to_present_is_growth(self):
        assert modules_grown(ABSENT, BATTERY_NOW) == (Module.BATTERY,)

    def test_absent_to_unknown_is_not_growth(self):
        # A failed re-read is not new hardware.
        assert modules_grown(ABSENT, {**ABSENT, Module.BATTERY: Presence.UNKNOWN}) == ()

    def test_present_to_absent_never_reloads(self):
        assert modules_grown(BATTERY_NOW, ABSENT) == ()

    def test_first_reload_is_due(self):
        assert module_reload_due(ABSENT, BATTERY_NOW, 1000.0, None) == (Module.BATTERY,)

    def test_a_second_within_the_interval_is_not(self):
        assert module_reload_due(ABSENT, BATTERY_NOW, 1000.0, 1000.0 - 60) == ()

    def test_after_the_interval_it_is_again(self):
        last = 1000.0 - MODULE_RELOAD_MIN_INTERVAL_S - 1
        assert module_reload_due(ABSENT, BATTERY_NOW, 1000.0, last) == (Module.BATTERY,)


def _stub(setup_presence, now_presence):
    stub = MagicMock()
    stub.setup_presence = setup_presence
    stub.install_presence.return_value = now_presence
    stub.config_entry = SimpleNamespace(entry_id="e923")
    stub.hass.data = {}
    return stub


class TestTheCoordinatorAsksOnce:

    def test_growth_schedules_one_reload(self):
        stub = _stub(ABSENT, BATTERY_NOW)
        SEMCoordinator._check_module_growth(stub)
        SEMCoordinator._check_module_growth(stub)   # rate-limited
        stub.hass.config_entries.async_schedule_reload.assert_called_once_with("e923")

    def test_no_verdict_yet_means_still_setting_up(self):
        stub = _stub(None, BATTERY_NOW)
        SEMCoordinator._check_module_growth(stub)
        stub.hass.config_entries.async_schedule_reload.assert_not_called()

    def test_nothing_grown_nothing_done(self):
        stub = _stub(BATTERY_NOW, BATTERY_NOW)
        SEMCoordinator._check_module_growth(stub)
        stub.hass.config_entries.async_schedule_reload.assert_not_called()


_PHACC = importlib.util.find_spec("pytest_homeassistant_custom_component") is not None


@pytest.mark.skipif(not _PHACC, reason="pytest-homeassistant-custom-component not installed")
@pytest.mark.asyncio
async def test_an_energy_dashboard_edit_rereads_it_once(hass):
    from homeassistant.components.energy.data import async_get_manager
    from homeassistant.config_entries import ConfigEntryState
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.solar_energy_management import _async_listen_energy_prefs

    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    coordinator = MagicMock()
    coordinator.async_initialize_energy_dashboard = AsyncMock()
    entry.runtime_data = coordinator
    entry.mock_state(hass, ConfigEntryState.LOADED)

    await _async_listen_energy_prefs(hass)
    await _async_listen_energy_prefs(hass)   # a reload must not add a second listener

    manager = await async_get_manager(hass)
    await manager.async_update({"device_consumption": []})
    await hass.async_block_till_done()
    coordinator.async_initialize_energy_dashboard.assert_awaited_once_with(quiet=True)
```

- [ ] **Step 2: Run to verify they fail**

Run: `~/bin/semtest tests/test_923_module_growth.py -v`
Expected: ImportError — `cannot import name 'MODULE_RELOAD_MIN_INTERVAL_S'`.

- [ ] **Step 3: Append the guard to `coordinator/install_modules.py`**

```python
# At most one module-driven reload per this many seconds, across reloads —
# a flickering detection must never become a reload loop.
MODULE_RELOAD_MIN_INTERVAL_S = 600.0


def modules_grown(
    at_setup: Mapping[Module, Presence], now: Mapping[Module, Presence],
) -> tuple[Module, ...]:
    """Modules that were ABSENT when the platforms were built and are PRESENT
    now — the only transition that needs new entities. ABSENT → UNKNOWN is a
    failed re-read, not hardware. PRESENT → ABSENT waits for the next
    restart or options change: removing a user's entities on a live re-read
    is exactly the false ABSENT this oracle exists to prevent."""
    return tuple(
        m for m in Module
        if at_setup.get(m) is Presence.ABSENT and now.get(m) is Presence.PRESENT
    )


def module_reload_due(
    at_setup: Mapping[Module, Presence],
    now: Mapping[Module, Presence],
    now_ts: float,
    last_reload_ts: float | None,
) -> tuple[Module, ...]:
    """The grown modules, if a reload may run now. Once per transition holds
    by construction — after the reload the new setup verdict is PRESENT. A
    growth refused by the interval is picked up by the next Energy Dashboard
    re-read, or at the next restart."""
    grown = modules_grown(at_setup, now)
    if not grown:
        return ()
    if last_reload_ts is not None and now_ts - last_reload_ts < MODULE_RELOAD_MIN_INTERVAL_S:
        return ()
    return grown
```

- [ ] **Step 4: The coordinator asks after every Energy Dashboard read**

In `coordinator/coordinator.py`, extend the Task 4 import to:
```python
from .install_modules import Module, Presence, module_reload_due, module_verdict
```

Directly below `install_presence` (Task 4), add:

```python
    def _check_module_growth(self) -> None:
        """(#923) Hardware SEM only DISCOVERS — a battery added to HA's Energy
        Dashboard — changes no SEM option, so no options reload creates its
        entities. When a module the platforms were built without is PRESENT
        now, reload once (see install_modules.module_reload_due)."""
        at_setup = self.setup_presence
        if not isinstance(at_setup, dict) or self.config_entry is None:
            return  # still setting up: the platforms read the fresh verdict
        key = f"{DOMAIN}_module_reload_at"
        now_ts = dt_util.utcnow().timestamp()
        grown = module_reload_due(
            at_setup, self.install_presence(), now_ts, self.hass.data.get(key))
        if not grown:
            return
        self.hass.data[key] = now_ts
        _LOGGER.info(
            "#923 — %s appeared since setup; reloading once to create its entities",
            ", ".join(m.value for m in grown))
        self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
```

At the end of `async_initialize_energy_dashboard`, replace the final
```python
        return self._energy_dashboard_config is not None
```
with
```python
        self._check_module_growth()
        return self._energy_dashboard_config is not None
```

- [ ] **Step 5: One Energy Dashboard listener per hass**

In `__init__.py`, directly above `async def async_setup_entry(` add:

```python
# (#923) HA's EnergyManager.async_listen_updates has no unsubscribe, so SEM
# registers ONE listener per hass and looks the live coordinators up when it
# fires — binding it to a coordinator would leak a stale listener per reload.
_ENERGY_PREFS_LISTENER = f"{DOMAIN}_energy_prefs_listener"


async def _async_listen_energy_prefs(hass: HomeAssistant) -> None:
    """Re-read the Energy Dashboard when the user edits it, so a battery or
    EV consumer added there reaches SEM without a restart (#923)."""
    if hass.data.get(_ENERGY_PREFS_LISTENER):
        return
    try:
        from homeassistant.components.energy.data import async_get_manager
        manager = await async_get_manager(hass)
    except Exception as err:  # noqa: BLE001 — no energy manager: re-read on restart
        _LOGGER.debug("Energy Dashboard listener not installed: %s", err)
        return

    async def _on_energy_prefs_updated() -> None:
        from homeassistant.config_entries import ConfigEntryState
        for sem_entry in hass.config_entries.async_entries(DOMAIN):
            if sem_entry.state is not ConfigEntryState.LOADED:
                continue
            coordinator = getattr(sem_entry, "runtime_data", None)
            if coordinator is None:
                continue
            try:
                await coordinator.async_initialize_energy_dashboard(quiet=True)
            except Exception as err:  # noqa: BLE001 — never raise into HA's energy save
                _LOGGER.debug("Energy Dashboard re-read after an edit failed: %s", err)

    manager.async_listen_updates(_on_energy_prefs_updated)
    hass.data[_ENERGY_PREFS_LISTENER] = True


```

In `async_setup_entry`, directly after
```python
        _LOGGER.info("Platforms setup completed: %s", PLATFORMS)
```
add
```python
        await _async_listen_energy_prefs(hass)
```

In `manifest.json` replace
```json
  "after_dependencies": [
    "recorder"
  ],
```
with
```json
  "after_dependencies": [
    "energy",
    "recorder"
  ],
```

- [ ] **Step 6: Run to verify they pass**

Run: `~/bin/semtest tests/test_923_module_growth.py tests/test_923_coordinator_presence.py tests/test_setup_entry_lifecycle.py tests/test_unload_reload_cycle.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add coordinator/install_modules.py coordinator/coordinator.py __init__.py manifest.json tests/test_923_module_growth.py
git commit -m "feat(#923): a module added in the Energy Dashboard creates its entities with one guarded reload"
```

---

### Task 12: Real installs, end to end

**Files:**
- Test: `tests/test_923_real_installs.py`

This is the proof the spec asks for in §9: a minimal install builds the core and nothing else; a battery+EV install loses nothing it has; removing hardware removes its entities on reload; an unreadable dashboard hides nothing.

- [ ] **Step 1: Write the tests**

Create `tests/test_923_real_installs.py`:

```python
"""#923 — real Home Assistant, real SEM setup, real registry.

None of our three machines runs the ABSENT path by default, which is why a
minimal install is part of the work (spec §9)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pytest_homeassistant_custom_component") is None,
    reason="pytest-homeassistant-custom-component not installed; CI runs these",
)

import yaml  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402

from custom_components.solar_energy_management.const import DOMAIN  # noqa: E402
from custom_components.solar_energy_management.coordinator.install_modules import (  # noqa: E402
    BATTERY_WIRING_KEYS, ENTITY_MODULES, Module, Presence,
)

COORDINATOR_MODULE = "custom_components.solar_energy_management.coordinator.coordinator"
TEMPLATE = Path(__file__).resolve().parents[1] / "dashboard" / "sem_dashboard_template.yaml"

MINIMAL_DATA = {
    "grid_power_sensor": "sensor.test_grid_power",
    "solar_power_sensor": "sensor.test_solar_power",
    "min_solar_power": 1000,
    "peak_load": 6000,
    "update_interval": 30,
    "electricity_import_rate": 0.30,
    "electricity_export_rate": 0.08,
}


def _static_lists():
    from custom_components.solar_energy_management.binary_sensor import BINARY_SENSOR_TYPES
    from custom_components.solar_energy_management.button import BUTTONS
    from custom_components.solar_energy_management.number import NUMBER_TYPES
    from custom_components.solar_energy_management.sensor import SENSOR_TYPES
    from custom_components.solar_energy_management.switch import SWITCH_TYPES
    return {"sensor": SENSOR_TYPES, "number": NUMBER_TYPES, "switch": SWITCH_TYPES,
            "binary_sensor": BINARY_SENSOR_TYPES, "button": BUTTONS}


def _dashboard(monkeypatch, config=None, answered=True):
    monkeypatch.setattr(
        f"{COORDINATOR_MODULE}.read_energy_dashboard_config_outcome",
        AsyncMock(return_value=(config, answered)))


def _minimal_entry():
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    return MockConfigEntry(domain=DOMAIN, version=12, minor_version=1,
                           data=dict(MINIMAL_DATA), options={},
                           title="SEM minimal (#923)")


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _uid(entry, platform, key):
    if platform == "number":
        return f"{entry.entry_id}_{'battery_capacity_kwh' if key == 'battery_capacity' else key}"
    return f"sem_{key}"


def _registered(hass, entry, platform, key):
    return er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, _uid(entry, platform, key)) is not None


@pytest.mark.asyncio
async def test_a_minimal_install_builds_the_core_and_nothing_else(
        hass, enable_custom_integrations, monkeypatch):
    _dashboard(monkeypatch)
    entry = _minimal_entry()
    coordinator = await _setup(hass, entry)
    assert coordinator.setup_presence == {m: Presence.ABSENT for m in Module}
    wrong = []
    for platform, descriptions in _static_lists().items():
        for d in descriptions:
            is_module = (platform, d.key) in ENTITY_MODULES
            if _registered(hass, entry, platform, d.key) is is_module:
                wrong.append((platform, d.key, "exists" if is_module else "missing"))
    assert not wrong, wrong


@pytest.mark.asyncio
async def test_the_minimal_dashboard_has_no_battery_or_ev_tab(
        hass, enable_custom_integrations, monkeypatch):
    from custom_components.solar_energy_management.features.dashboard_generator import (
        DashboardGenerator,
    )
    _dashboard(monkeypatch)
    await _setup(hass, _minimal_entry())
    tpl = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    DashboardGenerator(hass)._prune_absent_modules(tpl)
    assert {"battery", "ev"}.isdisjoint(v.get("path") for v in tpl["views"])


@pytest.mark.asyncio
async def test_the_diagnostics_carry_the_verdict(
        hass, enable_custom_integrations, monkeypatch):
    from custom_components.solar_energy_management.diagnostics import (
        async_get_config_entry_diagnostics,
    )
    _dashboard(monkeypatch)
    entry = _minimal_entry()
    await _setup(hass, entry)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["install_modules"] == {
        "battery": "absent", "ev": "absent", "heat_pump": "absent", "hot_water": "absent"}


@pytest.mark.asyncio
async def test_a_battery_and_ev_install_loses_nothing_it_has(
        hass, enable_custom_integrations, monkeypatch, sem_config_entry):
    _dashboard(monkeypatch)
    await _setup(hass, sem_config_entry)
    wrong = []
    for (platform, key), modules in ENTITY_MODULES.items():
        expected = modules <= {Module.BATTERY, Module.EV}
        if _registered(hass, sem_config_entry, platform, key) is not expected:
            wrong.append((platform, key, "expected" if expected else "unexpected"))
    assert not wrong, wrong


@pytest.mark.asyncio
async def test_removing_the_battery_removes_its_entities_on_reload(
        hass, enable_custom_integrations, monkeypatch, sem_config_entry):
    _dashboard(monkeypatch)
    await _setup(hass, sem_config_entry)
    assert _registered(hass, sem_config_entry, "sensor", "battery_soc")

    def _without_battery(d):
        return {k: v for k, v in d.items() if k not in BATTERY_WIRING_KEYS}

    hass.config_entries.async_update_entry(
        sem_config_entry,
        data=_without_battery(sem_config_entry.data),
        options=_without_battery(sem_config_entry.options))
    await hass.async_block_till_done()
    await hass.config_entries.async_reload(sem_config_entry.entry_id)
    await hass.async_block_till_done()

    assert sem_config_entry.runtime_data.setup_presence[Module.BATTERY] is Presence.ABSENT
    for platform, key in [("sensor", "battery_soc"), ("number", "battery_capacity"),
                          ("binary_sensor", "battery_charging"),
                          ("button", "backfill_battery_nights"),
                          ("switch", "battery_may_assist_ev")]:
        assert not _registered(hass, sem_config_entry, platform, key), (platform, key)
    assert _registered(hass, sem_config_entry, "sensor", "ev_power")


@pytest.mark.asyncio
async def test_an_unreadable_dashboard_hides_nothing(
        hass, enable_custom_integrations, monkeypatch):
    _dashboard(monkeypatch, None, answered=False)
    entry = _minimal_entry()
    coordinator = await _setup(hass, entry)
    assert coordinator.setup_presence[Module.BATTERY] is Presence.UNKNOWN
    assert _registered(hass, entry, "sensor", "battery_soc")
    assert _registered(hass, entry, "sensor", "ev_power")
    # Heat pump lives only in SEM's options — never UNKNOWN.
    assert not _registered(hass, entry, "sensor", "heat_pump_mode")
```

- [ ] **Step 2: Run them**

Run: `~/bin/semtest tests/test_923_real_installs.py -v`
Expected: all PASS. These exercise Tasks 1–11 together; a failure here is a real integration bug — find it with the failing assertion's list, fix it in the task's file, re-run. Typical causes: a platform setup path that builds an entity outside the static list you gated (check its loop), or a migration step that writes a wiring key into the minimal entry (read `entry.data` after setup).

- [ ] **Step 3: Commit**

```bash
git add tests/test_923_real_installs.py
git commit -m "test(#923): real installs — minimal builds only the core, full loses nothing, removal sweeps"
```

---

### Task 13: The whole suite, lint, and the fallout

**Files:** whatever the suite names.

- [ ] **Step 1: Run everything to a file**

```bash
S=/tmp/claude-1000/-home-sem-sem-community/dbb8e6b5-9824-4167-bce2-a8d1e4b5c3a8/scratchpad
~/bin/semtest tests/ -n auto -rf > $S/suite-923.txt 2>&1; echo "exit $?"
grep -E "^(FAILED|ERROR)" $S/suite-923.txt | sort | uniq > $S/suite-923-failures.txt
wc -l < $S/suite-923-failures.txt; tail -3 $S/suite-923.txt
```
Expected: `N passed` and ideally 0 failures. Read `$S/suite-923-failures.txt` in full.

- [ ] **Step 2: Fix the fallout by rule, not by weakening the gate**

Expected kinds of failure and the ONLY acceptable fix for each:

| failure | fix |
|---|---|
| A real-hass test asserts a heat-pump / hot-water / battery / EV entity on a fixture that does not configure that hardware | Add the hardware to THAT test's config (e.g. `"hot_water_entity": "water_heater.test"`), with a one-line comment `# (#923) the module must be configured for its entities to exist`. |
| A test counts entities (e.g. `len(entities) == N`) | Recompute N from the fixture's modules; comment why it changed. |
| A test drives a platform with a MagicMock coordinator and expects a battery entity to be ABSENT because the config lacks battery keys | Set `coordinator.setup_presence = {...BATTERY: Presence.ABSENT...}` on the double — the platform no longer reads config. |
| `test_653_orphan_methods.py::test_the_orphan_set_does_not_grow` lists an install_modules function | By Task 13 every public function in `install_modules.py` has a production caller (coordinator, platforms, generator, diagnostics, welcome). If one is still listed, wire it or delete it — never add it to `_BASELINE`. `presence_from_summary`'s caller is validate-sem.sh (outside the repo): if it is listed, keep it and add it to `_BASELINE` with the comment `# (#923) read by ~/bin/validate-sem.sh, outside the package`. |
| Anything in production code | Treat as a bug in this branch: diagnose, fix, add a test. |

Never add a `(platform, key)` to `CORE_BY_DECISION` just to make an old test pass — that entry needs a real reason a user can read.

- [ ] **Step 3: Lint and the card suite**

```bash
/tmp/venv-ci/bin/ruff check .
cd dashboard/card && npm test && cd ../..
python3 -c "import json; json.load(open('manifest.json'))"
```
Expected: ruff `All checks passed!`, node tests pass, manifest parses.

- [ ] **Step 4: Re-run until clean, then commit**

Re-run Step 1 after the fixes; commit only when the failure file is empty:

```bash
git add -A tests/
git commit -m "test(#923): fixtures configure the modules their assertions need"
```

---

### Task 14: `validate-sem.sh` and the minimal install switch (outside the repo)

**Files:**
- Modify: `~/bin/validate-sem.sh` (sections 2 and 3, new 2b)
- Modify: `~/bin/deploy-test.sh` (step 6)

- [ ] **Step 1: Back up both**

```bash
cp ~/bin/validate-sem.sh ~/bin/validate-sem.sh.bak-20260911
cp ~/bin/deploy-test.sh ~/bin/deploy-test.sh.bak-20260911
```

- [ ] **Step 2: Read the verdict once, at the top of section 2**

In `~/bin/validate-sem.sh`, directly below `section "2. Entity Count & Naming"` insert:

```bash
# (#923) The install's module verdict — what SEM built and what it did not.
# Empty on a pre-#923 build: every module check below then stands down.
MODULES_JSON=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/states/sensor.sem_diag_ed_config" 2>/dev/null | python3 -c "
import sys, json
try:
    print(json.dumps(json.load(sys.stdin).get('attributes', {}).get('install_modules') or {}))
except Exception:
    print('{}')
" 2>/dev/null)
[ -n "$MODULES_JSON" ] || MODULES_JSON='{}'
MIN_ENTITIES=180
if echo "$MODULES_JSON" | grep -q '"absent"'; then MIN_ENTITIES=150; fi
```

Replace
```bash
if [ "$TOTAL" -ge 180 ]; then
    pass "Entity count: $TOTAL (sensors=$SENSORS, numbers=$NUMBERS, switches=$SWITCHES, binary=$BINARY)"
else
    fail "Entity count: $TOTAL (expected ≥180)"
fi
```
with
```bash
if [ "$TOTAL" -ge "$MIN_ENTITIES" ]; then
    pass "Entity count: $TOTAL (sensors=$SENSORS, numbers=$NUMBERS, switches=$SWITCHES, binary=$BINARY)"
else
    fail "Entity count: $TOTAL (expected ≥$MIN_ENTITIES for this install's modules)"
fi
```

- [ ] **Step 3: Section 2b — nothing of an ABSENT module, everything of a PRESENT one**

Directly above `section "3. Critical Sensors"` insert:

```bash
# =============================================================
# 2b. INSTALL MODULES (#923)
# =============================================================
section "2b. Install Modules"

if [ "$MODULES_JSON" = "{}" ]; then
    warn "No install_modules verdict on sensor.sem_diag_ed_config (pre-#923 build) — module checks skipped"
else
    curl -s -H "Authorization: Bearer $TOKEN" "$API/states" 2>/dev/null | \
    MODULES_JSON="$MODULES_JSON" SEM_REPO="${SEM_REPO:-/home/sem/sem-community}" python3 -c "
import sys, json, os, importlib.util
path = os.path.join(os.environ['SEM_REPO'], 'coordinator', 'install_modules.py')
spec = importlib.util.spec_from_file_location('install_modules', path)
im = importlib.util.module_from_spec(spec); spec.loader.exec_module(im)
verdict = json.loads(os.environ['MODULES_JSON'])
presence = im.presence_from_summary(verdict)  # tolerant: the checkout may know other modules than the build
ids = {s['entity_id'] for s in json.load(sys.stdin)}
print('INFO|Verdict: ' + ', '.join(f'{k}={v}' for k, v in sorted(verdict.items())))
leftover = sorted(e for e in im.absent_entity_ids(presence) if e in ids)
if leftover:
    print(f'FAIL|{len(leftover)} entities of ABSENT modules still exist: ' + ', '.join(leftover[:8]))
else:
    print('PASS|No entity of an ABSENT module exists')
missing = sorted(
    f'{p}.sem_{k}' for (p, k), mods in im.ENTITY_MODULES.items()
    if p in ('sensor', 'binary_sensor', 'switch', 'number')
    and all(presence.get(m) is im.Presence.PRESENT for m in mods)
    and f'{p}.sem_{k}' not in ids)
if missing:
    print(f'WARN|{len(missing)} entities of PRESENT modules are missing: ' + ', '.join(missing[:8]))
else:
    print('PASS|Every entity of a PRESENT module exists')
" 2>&1 | while IFS='|' read status msg; do
        case "$status" in PASS) pass "$msg" ;; FAIL) fail "$msg" ;; WARN) warn "$msg" ;; INFO) echo "  $msg" ;; *) echo "  $status $msg" ;; esac
    done
fi
```

- [ ] **Step 4: Section 3 — battery rows only where there is a battery**

In section 3 change the pipe from `... | python3 -c "` to `... | MODULES_JSON="$MODULES_JSON" python3 -c "`, add `import os` to that script's first line (`import sys, json, os`), and directly after the `checks = [ ... ]` list add:

```python
if json.loads(os.environ.get('MODULES_JSON') or '{}').get('battery') == 'absent':
    checks = [c for c in checks if 'battery' not in c[0]]
```

- [ ] **Step 5: Minimal install switch in `deploy-test.sh`**

In step 6 replace:
```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"ev_connected_sensor":"binary_sensor.keba_p30_plug","ev_charging_sensor":"binary_sensor.keba_p30_charging_state","ev_charging_power_sensor":"sensor.keba_p30_charging_power"}' \
    "$API/config/config_entries/flow/$FLOW_ID" > /dev/null 2>&1
```
with:
```bash
# (#923) SEM_MINIMAL_INSTALL=1 skips the charger: the ABSENT path none of our
# machines exercises by default. Pair it with an Energy Dashboard that has
# no battery and no EV consumer to get a core-only install.
if [ "${SEM_MINIMAL_INSTALL:-0}" = "1" ]; then
    EV_STEP='{}'
    log "Minimal install: no EV charger"
else
    EV_STEP='{"ev_connected_sensor":"binary_sensor.keba_p30_plug","ev_charging_sensor":"binary_sensor.keba_p30_charging_state","ev_charging_power_sensor":"sensor.keba_p30_charging_power"}'
fi
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "$EV_STEP" "$API/config/config_entries/flow/$FLOW_ID" > /dev/null 2>&1
```

- [ ] **Step 6: Check both scripts parse and still pass against the current rig**

```bash
bash -n ~/bin/validate-sem.sh && bash -n ~/bin/deploy-test.sh && echo syntax-ok
~/bin/validate-sem.sh test > /tmp/claude-1000/-home-sem-sem-community/dbb8e6b5-9824-4167-bce2-a8d1e4b5c3a8/scratchpad/validate-46-before.txt 2>&1; echo "exit $?"
grep -E "2b|Install Modules|skipped|Entity count" /tmp/claude-1000/-home-sem-sem-community/dbb8e6b5-9824-4167-bce2-a8d1e4b5c3a8/scratchpad/validate-46-before.txt
```
Expected: `syntax-ok`; .46 still runs the pre-#923 build, so section 2b says "module checks skipped" and the count threshold is 180 — same verdict as before the edit.

---

### Task 15: Docs and CHANGELOG

**Files:**
- Modify: `docs/USER_GUIDE.md` (TOC + new section before `## Configuration Options`)
- Modify: `docs/DASHBOARD_GUIDE.md` (`## Dashboard Tabs`)
- Modify: `CHANGELOG.md` (`# [Unreleased]`)

- [ ] **Step 1: USER_GUIDE — a Modules section**

Add a TOC line `- [Modules — SEM shows what you have](#modules--sem-shows-what-you-have)` above the Configuration Options entry, and directly above `## Configuration Options` insert:

```markdown
## Modules — SEM shows what you have

SEM is a **core** — solar, grid, home consumption, energy balance, costs,
forecast — plus **modules** for the hardware you own:

| Module | Appears when | What it adds |
|---|---|---|
| Home battery | a battery sensor or control entity is set in SEM, or HA's Energy Dashboard has a battery | the Battery tab, ~60 battery entities (SOC, power, sessions, savings, zones) |
| EV charger | a charger is configured in SEM, or HA's Energy Dashboard has an EV consumer | EV entities (power, sessions, lifetime); the EV **tab** needs a configured charger |
| Heat pump | an SG-Ready relay, climate entity, SG-Ready service or heat-pump power/energy sensor is set | heat-pump status and energy entities |
| Hot water | a hot-water entity is set | the tank's temperature and legionella settings |

A small install therefore has fewer entities, by design — a solar-only SEM
has no `sensor.sem_battery_soc`. Add the hardware and its entities appear:
through SEM's Configure screen at once, and for a battery you add to HA's
Energy Dashboard with one automatic reload.

When SEM cannot tell — HA's Energy Dashboard could not be read at start-up —
it keeps everything rather than guess. What SEM decided is on
`sensor.sem_diag_ed_config` (attribute `install_modules`) and in the
diagnostics download.

A **custom** dashboard that references an entity of a module you do not have
shows it as unavailable; SEM's own dashboard is updated in step.
```

- [ ] **Step 2: DASHBOARD_GUIDE — tabs follow the modules**

Directly below the `## Dashboard Tabs` heading insert:

```markdown
> **The tabs follow your hardware (#923).** The **Battery** tab appears only
> when SEM knows of a home battery, the **EV** tab only when a charger is
> configured, and cards on the other tabs drop the parts that belong to
> hardware you do not have (the sankey's battery and EV nodes, for example).
> See [Modules](USER_GUIDE.md#modules--sem-shows-what-you-have).
```

- [ ] **Step 3: CHANGELOG**

Under `# [Unreleased]` insert:

```markdown
- ✨ **SEM shows what your install has** (#923, #857). SEM is now a core
  (solar, grid, home, costs, forecast) plus modules — home battery, EV
  charger, heat pump, hot water — and creates a module's entities, tab and
  dashboard references only when that hardware is configured, or declared in
  HA's Energy Dashboard. A solar-only install drops the 113 entities it never
  used. Add the hardware later and they appear: from SEM's Configure screen
  at once, for a battery added to the Energy Dashboard with one automatic
  reload. When SEM cannot tell, it keeps everything. The verdict is on
  `sensor.sem_diag_ed_config` (`install_modules`) and in the diagnostics.
  ⚠️ A custom dashboard that references a removed entity shows it as
  unavailable — SEM's own dashboard is updated in step.
```

- [ ] **Step 4: Check the anchor resolves and commit**

```bash
grep -n "## Modules — SEM shows what you have" docs/USER_GUIDE.md
~/bin/semtest tests/test_card_registry_metadata.py -q
git add docs/USER_GUIDE.md docs/DASHBOARD_GUIDE.md CHANGELOG.md
git commit -m "docs(#923): modules — what appears depends on what you have"
```

---

### Task 16: ruflo challenge and preflight

**Files:**
- Create: `~/claude-jobs/challenge-feature-923-house-surface.md`

- [ ] **Step 1: Ask a ruflo reviewer to REFUTE the branch's claim**

Call the `Agent` tool directly (never through the autopilot) with `subagent_type: "ruflo-core:reviewer"` and this prompt:

```
Repo /home/sem/sem-community, branch feature/923-house-surface, spec
docs/superpowers/specs/2026-09-11-923-install-modules-design.md.

CLAIM (falsifiable): "Every surface that depends on a hardware module asks one
oracle (coordinator/install_modules.py); no module that is PRESENT or UNKNOWN
loses an entity, tab or card; and an ABSENT module leaves no entity, tab or
dashboard reference behind."

Your job is to REFUTE it, not review it. Find a concrete case where it is
false: a surface that decides "has a battery/EV/heat pump/hot water" without
the oracle (grep the whole repo, cards included); a platform path that
creates a module entity outside the gated lists; a registry entry the sweeps
miss; a way to reach ABSENT without an answered Energy Dashboard; a card that
throws on a missing entity; a reload loop. For each finding give file:line
and a scenario (inputs → wrong output). Say CONFIRMED only if you tried and
failed to break it, and list what you tried.
```

- [ ] **Step 2: Act on the verdict**

For each finding: reproduce it in a test, fix it, re-run Task 13 Step 1. Then write the record:

```
CLAIM:    Every surface that depends on a hardware module asks one oracle; no PRESENT or UNKNOWN module loses an entity, tab or card; an ABSENT module leaves no entity, tab or dashboard reference behind.
AGENT:    ruflo-core:reviewer
VERDICT:  <CONFIRMED | REFUTED | OVERSTATED> — <what it found, what changed as a result, commit ids>
```

- [ ] **Step 3: Preflight**

Run: `~/bin/sem-ready.sh`
Expected: every gate passes except the ones that wait on live proof / Guido's word; gate 2b finds the challenge record.

---

### Task 17: Live proof — .175 full install, .46 minimal install — then stop

Build is complete; this is the one deploy-and-verify pass. **Observer mode stays ON on both rigs** (they share Guido's real KEBA and Huawei). PROD is not touched.

- [ ] **Step 1: .175 — nothing disappears where the hardware exists**

```bash
S=/tmp/claude-1000/-home-sem-sem-community/dbb8e6b5-9824-4167-bce2-a8d1e4b5c3a8/scratchpad
source ~/.config/sem/tokens.env
curl -s -H "Authorization: Bearer $HA_TEST_TOKEN" http://10.10.20.175:8123/api/states \
  | python3 -c "import sys,json; print('\n'.join(sorted(s['entity_id'] for s in json.load(sys.stdin) if '.sem_' in s['entity_id'])))" > $S/175-before.txt
~/bin/sem-deploy-175.sh
```
(If it refuses because `.handover-active` exists, stop and ask — do not pass `--force`.) After HA is back:
```bash
curl -s -H "Authorization: Bearer $HA_TEST_TOKEN" http://10.10.20.175:8123/api/states \
  | python3 -c "import sys,json; print('\n'.join(sorted(s['entity_id'] for s in json.load(sys.stdin) if '.sem_' in s['entity_id'])))" > $S/175-after.txt
curl -s -H "Authorization: Bearer $HA_TEST_TOKEN" http://10.10.20.175:8123/api/states/sensor.sem_diag_ed_config \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['attributes'].get('install_modules'))"
comm -23 $S/175-before.txt $S/175-after.txt > $S/175-gone.txt; wc -l < $S/175-gone.txt
```
Expected: verdict `battery=present, ev=present`; every line in `175-gone.txt` belongs to a module the verdict calls absent (check with `absent_entity_ids`), and none is a battery or EV entity. Check the log for `Install modules:` and zero new errors.

- [ ] **Step 2: .46 — the minimal install**

1. Save .46's Energy Dashboard preferences with the `mcp__ha-test__ha_manage_energy_prefs` tool (read) to `$S/46-energy-prefs.json`.
2. With the same tool, write them back **without** the `battery` entry in `energy_sources` and without any `device_consumption` entry that is an EV/charger sensor.
3. Deploy the minimal install: `SEM_MINIMAL_INSTALL=1 ~/bin/deploy-test.sh` (full clean install from this branch). Expected: `Install result: create_entry`, `observer_mode: on`.
4. Verify: `~/bin/validate-sem.sh` → section 2b `Verdict: battery=absent, ev=absent, heat_pump=absent, hot_water=absent`, `PASS|No entity of an ABSENT module exists`, count ≥150. If the verdict still says battery=present, SEM's config holds a battery wiring key — read which one from the diagnostics download (`config_entry.data`/`options`). `battery_discharge_control_entity` is auto-discovered at install (config_flow.py ~1037) and can be filled on a hybrid inverter WITHOUT a battery (discovery falls back to solar/grid devices, hardware_detection.py ~2477) — if that is the key, record it as a finding for the #857 audience (a harmless false PRESENT that defeats the feature for them) before clearing it on SEM's Configure screen, never by editing storage.
5. Scan every dashboard view for error cards with the headless playwright pattern in CLAUDE.md ("Dashboard verification workflow"): walk shadow roots for `HUI-ERROR-CARD` on `/sem-dashboard/home`, `/energy`, `/control`, `/config`, `/costs`, `/system`. Expected: zero; and no Battery or EV tab. Screenshot Home and Energy to `$S/46-minimal-*.png`.

- [ ] **Step 3: .46 — a battery added later appears with one reload**

1. Restore the `battery` source (only that) with `mcp__ha-test__ha_manage_energy_prefs` from `$S/46-energy-prefs.json`.
2. Within ~1 min the log shows `#923 — battery appeared since setup; reloading once` exactly once; then `sensor.sem_battery_soc` exists and the verdict says `battery=present`. Regenerate the dashboard (`solar_energy_management.generate_dashboard`) and confirm the Battery tab is back.

- [ ] **Step 4: Restore .46 to the standard rig**

Restore the full saved preferences (EV consumer included) with the same tool, then `~/bin/deploy-test.sh` (standard clean install) and `~/bin/validate-sem.sh` → green, verdict `battery=present, ev=present`.

- [ ] **Step 5: Record and stop**

Write the evidence (verdicts, entity diffs, the reload log line, error-card scan result, screenshots) into `~/claude-jobs/challenge-feature-923-house-surface.md` under a `LIVE:` heading. Push the branch (`git push -u origin feature/923-house-surface`). **Do not merge.** Report to Guido in a few lines — what was proven where, what the release note says about custom dashboards — and ask whether and when it ships (merge needs his word and `SEM_FEAT_OK="#923 …" git push origin develop`).

---

## Not in this plan

- **#935 (clean uninstall)** — its own spec in the same arc.
- **Feature modules** (load management, dynamic tariff, peak guard, VPP) — same mechanism later, plus the rule that their on/off switch stays visible while off.
- `features/device_registry.py` `_has_battery` (the device-priority row, set each cycle from live SOC) — a UI row, not entity creation; left as is.
