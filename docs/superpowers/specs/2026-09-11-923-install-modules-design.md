# SEM as a core plus modules — the surface follows what the install has

**Arc:** #923 · **Implements:** #857 · **Branch:** `feature/923-house-surface`
**Status:** design approved in conversation 11.09.2026 (Guido: *"go ahead"*). Delivery milestone decided later.

## 1. Problem

SEM creates its full entity set and dashboard regardless of what the install owns. Of the 221
global sensors, 52 belong to a home battery, 24 to an EV charger and 8 to a heat pump, so an
install with none of them carries 84 sensors — over a third — for hardware it does not have,
plus the numbers, switches, selects and cards that go with them. #857's reporter: *"I have no
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
| hardware | **EV charger** | configuration | EV |
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
| Battery | `battery_soc_sensor`, `battery_power_sensor` or `battery_capacity_kwh` is set, **or** the Energy Dashboard declares a battery | none of those **and** the Energy Dashboard config was read | UNKNOWN — Energy Dashboard not loaded yet |
| EV | `ev_chargers` non-empty or `ev_charging_power_sensor` set | neither | — |
| Heat pump | `heat_pumps` non-empty, or `heat_pump_climate_entity` / an SG-Ready relay entity set — the same inputs `heat_pump_registration_status` reads | none | — |
| Hot water | `hot_water_entity` is set — the one key that creates a `HotWaterController` today (`__init__.py`, #454) | not set | — |

The four existing "has a battery" checks are replaced by calls to this function. The battery
rule keeps the constraint the dashboard generator already documents: *a battery-less verdict
must never come from an incomplete config alone.*

## 4. Entity gating

Each entity description may declare the modules it needs:

```python
requires: frozenset[Module] = frozenset()   # empty = core
```

An entity is **created when every required module is PRESENT or UNKNOWN**, and skipped only when
one is definitively ABSENT. UNKNOWN always keeps — a slow boot must never hide a real battery.

Applies to every platform: sensor, number, switch, select, binary_sensor, button, time.
Cross-module entities list all their modules — battery→EV assist requires `{BATTERY, EV}`.

## 5. The dashboard moves in lockstep

`_prune_ev_view_if_no_charger` becomes a module-driven prune on the same oracle:

- an ABSENT module removes its tab (Battery, EV) and sets the diagram node flag
  (`show_battery`, `show_ev`) — the existing #595/#614 behaviour, generalised;
- any card whose entities all belong to an ABSENT module is removed from the other tabs — the
  generator maps an entity to its module through the same `requires` declarations (§4), so the
  dashboard and the entity set cannot disagree;
- every `sem-*` card tolerates a missing module without rendering an error card.

Hand-built user dashboards that reference removed entities cannot be fixed by SEM; the release
note says so.

## 6. Existing installs — a one-time cleanup

On setup, for each module that is **definitively ABSENT**, SEM removes its own registry entries
for that module (`platform == DOMAIN` and a `unique_id` from that module's set, `sem_<key>`).
Never on UNKNOWN. Logged with the count per module.

Long-term statistics of removed entities are left in place — Home Assistant keeps them after any
entity is removed (the same leftover Spook reported on #908). Offering to clear them is #935's job.

## 7. Adding hardware later

- A change on SEM's configure screen already triggers a reload (`_SET_OPTION_STRUCTURAL_KEYS`
  and the options flow), and the reload creates whatever is now PRESENT. No new code.
- Hardware SEM only **discovers** — a battery added to HA's Energy Dashboard — does not change
  SEM's options. The coordinator re-evaluates the oracle; a module that flips **ABSENT → PRESENT**
  schedules **one** reload. Guarded: once per transition, and at most one module-driven reload
  per 10 minutes, so a flickering detection cannot become a reload loop.

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
