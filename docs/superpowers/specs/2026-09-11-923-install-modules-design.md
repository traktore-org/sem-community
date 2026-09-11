# SEM as a core plus modules — the surface follows what the install has

**Arc:** #923 · **Implements:** #857 · **Branch:** `feature/923-house-surface`
**Status:** design approved in conversation 11.09.2026 (Guido: *"go ahead"*). Delivery milestone decided later.

## 1. Problem

SEM creates its full entity set and dashboard regardless of what the install owns. Of the 221
global sensors, 51 belong to a home battery (3 of them shared with EV), 29 to an EV charger and
8 to a heat pump, so an install with none of them carries 88 sensors — two in five — for
hardware it does not have, plus 25 numbers, switches, binary sensors and buttons, and the cards
that go with them (113 static entities in all, classified in the plan). #857's reporter: *"I have no
heat pump, no home battery … would prefer to hide all related elements."*

EV already does this halfway (#595 removes the EV tab when no charger is configured); battery
only hides its diagram node (#614) and keeps its tab and every entity; heat pump has nothing.

"Has a battery" is decided in **four** places today, each slightly differently:
`__init__.py:378` (welcome text), `config_flow.py:601`, `select.py:_has_battery` (which reads
the registry for `sensor.sem_battery_soc` — circular once that entity can be absent), and
twice inside `features/dashboard_generator.py` (`:277` and `:636`). A rule with four copies
has four behaviours.

## 2. The module map

| kind | module | detected from | tab |
|---|---|---|---|
| core | solar, grid, home, energy balance, totals, forecast, notifications | always | Home, Energy, System, Config |
| hardware | **Battery** | configuration + Energy Dashboard | Battery |
| hardware | **EV charger** | configuration + Energy Dashboard | EV (tab needs a configured charger) |
| hardware | **Heat pump** | configuration | — |
| hardware | **Hot water** | configuration | — |
| feature | Load management · Dynamic tariff & costs · Peak guard · VPP | a user setting | Control, Costs |

**This spec covers the core and the four hardware modules.** The feature modules use the same
mechanism later, with one extra rule — their on/off switch must stay visible in Config while
the module is off, or the user can never turn it back on. #935 (clean uninstall) is a separate
spec in the same arc.

## 3. The capability oracle — one answer, three states

New pure module `coordinator/install_modules.py`:

```python
class Module(Enum): BATTERY, EV, HEAT_PUMP, HOT_WATER
class Presence(Enum): PRESENT, ABSENT, UNKNOWN

def install_modules(config: Mapping, ed_config: EnergyDashboardConfig | None,
                    ed_loaded: bool) -> dict[Module, Presence]
```

**The verdict comes from configuration, never from live sensor state.** A sensor that is
momentarily unavailable says nothing about whether the hardware exists — reading it as
"absent" is the #875 class ("unread is not zero") at module scale.

| module | PRESENT when | ABSENT when | otherwise |
|---|---|---|---|
| Battery | a battery **wiring** key is set (`battery_soc_sensor`, `battery_power_sensor`, a discharge/force-discharge/strategy control entity), **or** the Energy Dashboard declares a battery | none of those **and** the Energy Dashboard question was answered | UNKNOWN — Energy Dashboard unread or unreadable |
| EV | `ev_chargers` non-empty, `ev_charging_power_sensor` / `ev_power_sensor` set, **or** the Energy Dashboard declares an EV consumer | none of those **and** the Energy Dashboard question was answered | UNKNOWN |
| Heat pump | `heat_pumps` non-empty, or a heat-pump wiring key set (relay 1/2, climate entity, SG-Ready service or state entity, power or energy sensor) | none | — |
| Hot water | `hot_water_entity` is set — the one key that creates a `HotWaterController` today (`__init__.py`, #454) | not set | — |

Only **wiring** counts. `battery_capacity_kwh` is deliberately not evidence: the options
flow's Settings step saves it with a default for every install that passes through it
(`config_flow.py`, step `settings`), so it describes a battery without proving one. The same
goes for heat-pump tunables (boost offset, rated power, priority).

"Answered" is its own value (#925): a missing `.storage/energy` file is a definite "no
dashboard" (answered), a read or parse failure is not. `read_energy_dashboard_config` folds
both into `None`, so the oracle gets a sibling that keeps them apart.

The deciders that are replaced by calls to this function: `__init__.py:378` (welcome text),
`select.py:_has_battery` (shared with `number.py`), and `features/dashboard_generator.py`
`:277` and `:636`. (`config_flow.py:601` only *writes* a `has_battery` flag that nothing
reads — it is not a decider and is left alone.) The battery rule keeps the constraint the
dashboard generator already documents: *a battery-less verdict must never come from an
incomplete config alone.*

**The EV module is not the EV tab.** An Energy Dashboard EV consumer feeds `sem_ev_power` with
no charger configured (`sensor_reader.py`, the `ed.ev_power` branch), so that install has EV
*data* and keeps its EV entities. The EV *tab* is the control surface for a charger SEM was told
about and keeps #595's rule — a configured charger (`has_managed_charger`) — as does the
welcome text's charge-mode line.

## 4. Entity gating

Each entity declares the modules it needs in ONE keyed table beside the oracle:

```python
ENTITY_MODULES: Mapping[tuple[str, str], frozenset[Module]]   # (platform, key) -> modules; absent = core
```

A table rather than a field on each description: HA's `EntityDescription` classes are frozen
dataclasses, so a field means subclassing all 268 descriptions; the table leaves them untouched
and gives the dashboard generator the same lookup. A naming ratchet keeps it complete — any key
that *looks* like a module (`battery`, `ev_`, `heat_pump`, `hot_water`, `charg`, …) must be in
the table or in an explicit core-by-decision list with its reason.

An entity is **created when every required module is PRESENT or UNKNOWN**, and skipped only when
one is definitively ABSENT. UNKNOWN always keeps — a slow boot must never hide a real battery.

Applies to every static list: sensor, number, switch, binary_sensor, button (select and time
have per-device entities only, which already follow their config lists; the global battery
select follows the oracle through `_has_battery`). Cross-module entities list all their
modules — battery→EV assist requires `{BATTERY, EV}`.

**Core by decision:** `sensor.charging_state` stays core although it is named like EV — it
carries the Home tab's `today_plan` attribute (solar peak, price windows, night) and is the
Config tab's "set up" marker. `diag_charger_count` stays core — it is how "0 chargers found"
is visible.

## 5. The dashboard moves in lockstep

`_prune_ev_view_if_no_charger` becomes a module-driven prune on the same oracle:

- Battery ABSENT removes the Battery tab and sets `show_battery: false` (#614); no managed
  charger removes the EV tab and sets `show_ev: false` (#595, unchanged);
- every explicit reference to an ABSENT module's entity is removed from the remaining views —
  a sankey node or `children` link, a card whose `entity:` it is, a stack left empty — through
  the same `ENTITY_MODULES` table (§4), so the dashboard and the entity set cannot disagree.
  Most `sem-*` cards take `entity_prefix` and pick their entities internally, so they are not
  pruned but must tolerate absence;
- every `sem-*` card tolerates a missing module without rendering an error card — enforced by a
  lint on unguarded `states[x].prop` reads (one exists today, `sem-load-priority-card.js:403`)
  and checked live on the minimal install.

Hand-built user dashboards that reference removed entities cannot be fixed by SEM; the release
note says so.

## 6. Existing installs — a one-time cleanup

On setup, for each module that is **definitively ABSENT**, SEM removes its own registry entries
for that module. Never on UNKNOWN.

This needs no new remover: the sensor, number and switch platforms already sweep registry
entries whose key is not in their description list, so feeding them the *gated* list removes
exactly the ABSENT modules' entries (UNKNOWN keeps the description, so it stays valid). Two gaps
are closed: binary_sensor and button had no sweep, and number's legacy unique_id
(`battery_capacity` → `battery_capacity_kwh`) was valid unconditionally.

Long-term statistics of removed entities are left in place — Home Assistant keeps them after any
entity is removed (the same leftover Spook reported on #908). Offering to clear them is #935's job.

## 7. Adding hardware later

- A change on SEM's configure screen already triggers a reload (the options flow), and the
  reload creates whatever is now PRESENT. `set_option` reloads only for keys in
  `_SET_OPTION_STRUCTURAL_KEYS` — five module wiring keys were missing (`ev_charging_power_sensor`,
  `ev_power_sensor`, `heat_pumps`, `heat_pump_sg_ready_service`,
  `heat_pump_sg_ready_state_entity`); they are added and a ratchet keeps every wiring key there.
- Hardware SEM only **discovers** — a battery added to HA's Energy Dashboard — does not change
  SEM's options. SEM subscribes to HA's energy-prefs updates (ONE listener per hass: the
  EnergyManager has no unsubscribe, so it looks the live coordinators up when it fires) and
  re-reads the Energy Dashboard; a module that flips **ABSENT → PRESENT** schedules **one**
  reload. Guarded: once per transition (after the reload the setup verdict is PRESENT), and at
  most one module-driven reload per 10 minutes across reloads, so a flickering detection cannot
  become a reload loop. PRESENT → ABSENT never reloads — it applies at the next restart or
  options change, because removing entities on a live re-read is the false-ABSENT this whole
  design exists to prevent.
- The verdict is visible: `sensor.sem_diag_ed_config` carries an `install_modules` attribute
  and the downloadable diagnostics include it — support's first stop for "where is my battery
  tab", and what `validate-sem.sh` reads.

## 8. Failure modes and how they are contained

| failure | containment |
|---|---|
| false ABSENT removes a real user's entities | verdict from configuration only; UNKNOWN keeps; cleanup only on definite ABSENT |
| Energy Dashboard not loaded at boot | battery = UNKNOWN → everything kept; re-evaluated later |
| detection flickers | one reload per transition, rate-limited |
| a card references a removed entity | generator prunes in lockstep; cards tolerate absence |

## 9. Testing

- **Oracle unit tests** — every row of §3 including UNKNOWN, and the four replaced call sites
  all agreeing with it.
- **Gating tests** — for each module absent, the platform creates none of its entities and all
  core ones; cross-module entities follow their full `requires` set.
- **A minimal-install fixture** (pytest-homeassistant): solar + grid only, asserting the exact
  entity set and a dashboard with no Battery/EV tab and no error cards.
- **Cleanup + reload tests** — ABSENT removes, UNKNOWN does not; ABSENT→PRESENT reloads once.
- **`validate-sem.sh` becomes module-aware** — it currently asserts battery sensors on every install.
- **Live:** a fresh config-flow install on .46 with no battery, EV or heat pump configured
  (observer mode, as the clean-install routine already does), plus an unchanged full install
  on .175 proving nothing disappears where the hardware exists. **None of our three machines
  exercises the ABSENT path by default — this is why the minimal install is part of the work.**

## 10. Docs

A short "Modules" section in `USER_GUIDE.md` and `DASHBOARD_GUIDE.md` — what each module is, when
it appears, and that a missing entity on a small install is by design. CHANGELOG entry and a
release note about custom dashboards.

## 11. Delivery

Enhancement: built whole on `feature/923-house-surface`, ruflo challenge record for the structural
claim ("the four battery checks agree with the oracle, and no PRESENT/UNKNOWN module loses an
entity"), proven on .46 and .175, merged on Guido's word with `SEM_FEAT_OK`. Which release it
ships in is decided after it is built.
