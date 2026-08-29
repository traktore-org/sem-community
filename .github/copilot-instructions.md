# AI Agent Guidelines for Solar Energy Management (SEM)

> **How to read this file.** It points at code and docs; it deliberately does **not**
> restate values that the code already states. The previous version of this file sat
> untouched from v1.0.0 (2026-04-12) through ~25 releases, and by the time anyone
> re-read it, it claimed `DEFAULT_UPDATE_INTERVAL = 300  # 5 minutes` when the real
> value is `10  # seconds`, and gave `DEFAULT_BATTERY_PRIORITY_SOC` both a wrong number
> and an inverted meaning. A doc that quotes a constant will drift from it; a doc that
> names the file the constant lives in cannot. See #671, and `docs/BUG_CLASSES.md` for
> the class. **If you add a number here, add a test for it or don't add it.**

## Project Overview

SEM is a Home Assistant integration that optimises solar self-consumption across battery
storage, EV charging, heat pumps, and generic switchable loads. It maximises own-use while
protecting battery levels and managing peak load.

Distribution is HACS with `content_in_root: true` — files live at the repo root, so this
repo has **no** wrapper directory (CI and the test runner create one).

## Before you change anything

- **`docs/README.md` is the documentation index.** Start there. Root-level guide files
  are stubs pointing into `docs/`.
- **`docs/BUG_CLASSES.md` is the bug-class ledger.** Before fixing a bug, find its class,
  sweep the siblings, and add a guard. A fix is instance-local; the class survives.
- **`docs/adr/`** holds the architecture decisions that are load-bearing —
  per-charger context, the unified EV budget, and the sign-convention boundary.
- **`docs/MULTI_CHARGER.md` is mandatory reading** before touching anything under
  `coordinator/` that participates in the multi-charger loop.

## Key architecture

### Core (`const.py`, `consts/`, `coordinator/`)

- Constants live in the `consts/` package and are re-exported by `const.py`. Read the
  values there; do not copy them into docs.
- Entity naming: every SEM sensor is `sensor.sem_{description.key}`, built by `SEMSensor`
  (`sensor.py`). The key in the `EntityDescription` **is** the entity id suffix.
- The coordinator pipeline is
  `SensorReader → PowerReadings.calculate_derived() → energy/flow/charging chain`.
- `home_consumption_power` is derived from the energy balance and clamped to `>= 0`. That
  clamp is intentional — do not make it report `unknown`.

### Sign conventions

Documented in `docs/adr/0003-sign-convention-boundary.md`. Summary: grid is
`− import / + export`, battery is `− discharge / + charge`, solar and EV are positive-only.
**Never negate a sensor "to follow HA convention" without checking the live source first** —
that has broken Huawei installs before.

### Device discovery (`hardware_detection.py`)

Pattern-based auto-discovery with confidence scoring. The pattern tables are per-domain
(`EV_INTEGRATION_PATTERNS`, `GENERIC_EV_PATTERNS`, `_PV_STRING_PATTERNS`, …) — read the
module rather than assuming a single flat table.

### Labels (`consts/labels.py`)

`SENSOR_LABEL_MAPPING` maps **full** entity-description keys to HA entity-registry labels;
`SEM_LABELS` is the label vocabulary. The lookup is exact-match, and a miss applies no
labels and reports nothing, so this registry cannot detect its own rot — it is guarded by
`tests/test_667_label_registry.py`. Per-device entities (`charger_<id>_*`,
`battery_<id>_*`) cannot be labelled by it at all; that is a design limit, not drift.

### Dashboard cards

All cards are LitElement sources under `dashboard/card/src/cards/`, built by Rollup into a
single bundle `dashboard/card/dist/sem-cards.js`. **Editing a card does nothing until
`cd dashboard/card && npm run build` regenerates the bundle** — deploy scripts only rsync,
they do not build. Never put a backtick inside a lit `html` template, including in HTML
comments; it terminates the template literal and blanks the card at render time while
passing every static check (guarded by `tests/test_card_template_lint.py`).

## Workflows

### Testing

Run from a replica of the CI layout, **not** from the repo root — a repo-root `select.py`
shadows the stdlib `select` module, and Python 3.13+ is required (the HA 2026.2 floor):

```bash
rsync -a --delete --exclude=.git --exclude=node_modules ./ /tmp/ha-config/custom_components/solar_energy_management/
cd /tmp/ha-config && PYTHONPATH=/tmp/ha-config python3 -m pytest custom_components/solar_energy_management/tests/ -q
```

CI runs the same layout on Python 3.13 and 3.14 (the HA floor and what PROD runs — #836 retired the 3.12 rung), plus Hassfest and HACS validation.

### Deploying

Never deploy to HA-PROD without testing on HA-TEST first, and never without explicit
approval. Deploy scripts rsync the **working tree**, not a git ref, so a feature branch can
be soaked on real hardware without merging — and un-soaked work must stay off `develop`.

### Git

Feature branches for anything non-trivial. Every commit references an issue. `main` is
PR-only with all CI checks green. Do not create release tags without being asked.

## Integration points

### Supported hardware

Inverters and chargers are listed in `README.md`. **Every supported brand must have a
pipeline test in `tests/test_split_grid_integration.py`** covering its grid/battery sign
pattern — adding a brand to the supported list means adding its test.

### Services

Registered services are declared in `services.yaml`; that file is the authoritative list.

## Common failure modes

1. **Flow-energy accumulation** — use `tests/test_flow_accumulation.py`; accumulation
   guards exist to prevent double counting.
2. **Fleet-vs-per-charger reads** — reading the fleet-summed `power.ev_power` inside a
   per-charger loop caused four hotfixes for one bug class. Use `_this_charger_power`, and
   annotate any deliberate fleet read with `# FLEET-READ: <reason>`; an AST lint enforces
   this (`tests/test_ev_control_fleet_reads.py`).
3. **A gate that blocks activation but does not stop an already-running device** — this
   class has recurred four times. Check both directions.
4. **Dead surface** — a key map, emit, or doc reference that nothing resolves. It fails
   silently by construction (missing dict key, `states.get` returning `None`), so it rots
   invisibly. Guards exist for the label registry, the `consts/` package, and doc anchors;
   extend them rather than adding an unguarded registry.
