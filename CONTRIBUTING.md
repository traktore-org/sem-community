# Contributing to SEM

Thanks for your interest in contributing to Solar Energy Management!

## How to Contribute

### Reporting Bugs

1. Check [existing issues](https://github.com/traktore-org/sem-community/issues) first
2. Include your HA version, SEM version, inverter/charger model
3. Include relevant log entries (`Logger: custom_components.solar_energy_management`, level: debug)
4. Describe what you expected vs what happened

### Hardware Testing

The most valuable contribution: **test SEM with your hardware and report results.** We support 8 EV chargers and 12 inverters, but can't test them all without community help.

If you have hardware not yet tested:
1. Install SEM on a test HA instance
2. Run through the config flow
3. Report: did auto-detection work? Did the first coordinator cycle succeed?
4. Share entity IDs and state values from your integration

### Feature Requests

Open an issue with the `enhancement` label. Describe the use case, not just the solution.

### Pull Requests

1. Fork the repo and create a feature branch: `feature/your-feature`
2. Make your changes
3. Ensure tests pass (see the namespaced test-runner note under [Development Setup](#development-setup) — a direct `pytest` from the repo root fails because `select.py` shadows the stdlib module)
4. Update documentation if your change affects user-facing behavior
5. Submit a PR to `develop` (not `main`) — the PR template's checklist mirrors
   exactly what the review will hold you to

**What to expect after you open a PR:**

- An **automated maintainer review** hard-challenges every PR against SEM's
  invariants (sign conventions, fail-closed control paths, translation
  parity, persisted-state round-trips, multi-charger rules — the template
  checklist). It requests changes with specific file-and-line findings, or
  formally approves. Either way you get substantive feedback, usually within
  the hour.
- **Merging is always a human maintainer decision** — an approval means
  "cleared for merge", not merged.
- During a **stabilization phase** (feature freeze before a stable release),
  feature PRs are parked with a friendly note and get their full review once
  the freeze lifts. Bug fixes are always reviewed immediately. The
  `parked: feature freeze` label marks this state.
- CI on a first-time contribution waits for a manual approval before running —
  GitHub policy for fork code, not distrust.

### Code Style

- Python: follow existing patterns in the codebase
- No new dependencies unless absolutely necessary
- Add tests for new features
- Update translations (15 languages: de, en, es, fr, it, nl, pt, pl, sv, cs, da, fi, hu, ro, no) for user-facing text

### Adding a charger or inverter brand (#814)

Support is DATA first. Adding a brand means three things, and CI checks two of them:

1. **A row in `consts/hardware_matrix.py`** — brand, integration, control method /
   sign pattern, and an honest status: `requested` (cite the issue),
   `implemented`, or `tested-live` (cite the reporter or system — no citation,
   no claim). Then `python3 scripts/generate_hardware_doc.py` regenerates
   `docs/SUPPORTED_HARDWARE.md`; CI fails on drift.
2. **The detection rules as data** — for a charger without quirks, a row in
   `_BRAND_HINTS` (`hardware_detection.py`): per SEM role the domain, optional
   device_class and name hints. The generic matcher applies it; no function
   needed. Quirky boxes keep a function, but say why in its docstring.
3. **The pipeline test** in `tests/test_split_grid_integration.py` (inverters)
   or the detection tests (chargers) — the matrix ratchet fails if an
   implemented brand has none. Never guess sign conventions: without a reporter
   export the row stays `requested` and the brand sits in the ratchet's
   shrink-only gap list.

Users see what detection did on the dashboard **Configuration → Detected
hardware** (evidence per role, near-misses named); when triaging a report, ask
for that section or the diagnostics download — the same report is in both.

#### Which brand next? Ask the roster (#915)

`consts/integration_roster.py` is a **generated** list of the energy-shaped
integrations the ecosystem actually runs — domain, display name, install count,
and, where the integration publishes one, the entity vocabulary it declares in
its own repository. Regenerate it with:

```bash
python3 scripts/crawl_integration_roster.py --refresh --write --baseline
python3 scripts/crawl_integration_roster.py --backlog     # the ranked gap
```

It answers "which brand is worth a row" with install counts instead of with
whoever filed the loudest issue, and for a brand that publishes a
`strings.json` it also answers "what does it call its discharge limit".

**It is not a support list and never becomes one.** A roster row is a claim
about the world, gated by a URL; a matrix row is a claim about SEM, gated by
evidence. Nothing crawled may carry a status, an evidence string or a sign
convention — `tests/test_915_roster_is_not_a_claim.py` makes that
structural. A crawled brand reaches `hardware_matrix.py` the same way every
other brand does: a human files an issue, and the row cites it.

`tests/test_915_roster_rediscovery.py` is the check that the mining is worth
trusting: it asserts the miner re-derives four things SEM learned from live
installs (Huawei's discharge-limit key and working-mode labels, Zaptec's
current register but *not* its phase-switch register, Sessy's strategy
values) and that it invents nothing where an integration exposes nothing
(Easee is service-driven and must mine no current control).

### Multi-charger correctness

SEM was originally single-charger; multi-charger support was added
incrementally. Between v1.6.0 and v1.6.6 we shipped four hotfixes for
variants of the same bug class: **per-charger context swaps with
fleet-level reads leaking through**. The structural fix landed in
v1.6.7 as `PerChargerContext` (see
[`docs/MULTI_CHARGER.md`](docs/MULTI_CHARGER.md) for the full invariant).

**Two rules of thumb when working on the coordinator:**

1. Inside a `with PerChargerContext.for_charger(...)` block (the
   multi-charger loop in `coordinator/coordinator.py`), never read
   `power.ev_power` directly — use the per-charger helper or annotate
   the read with `# FLEET-READ: <reason>`.
2. To add new per-charger state, edit
   [`coordinator/per_charger_context.py`](coordinator/per_charger_context.py)
   — don't add new ad-hoc `saved = {...}` swap dicts.

If you're not sure whether a code path runs inside the per-charger loop,
read the doc — the answer is there.

## Development Setup

```bash
# Clone
git clone https://github.com/traktore-org/sem-community.git
cd sem-community

# Install test dependencies
pip install -r tests/requirements_test.txt

# Run tests — IMPORTANT: run from a namespaced copy, NOT the repo root.
# The repo-root select.py shadows the stdlib `select` module, which breaks a
# direct `pytest` from the repo root. CI copies the repo into a package path
# and runs from there; replicate that layout locally:
rsync -a --delete --exclude=.git --exclude=node_modules \
  ./ /tmp/ha-config/custom_components/solar_energy_management/
cd /tmp/ha-config && PYTHONPATH=/tmp/ha-config \
  python3.12 -m pytest custom_components/solar_energy_management/tests/ -q

# Lint — runs from the repo root, config in ruff.toml
pip install ruff==0.16.3
ruff check .

# Deploy to test HA instance
rsync -av --delete --exclude='__pycache__' --exclude='.git' \
  ./ your-ha:/config/custom_components/solar_energy_management/
```

## Which Home Assistant the suite runs against

The CI matrix lists Python versions, but it is really a **Home Assistant**
matrix: `pytest-homeassistant-custom-component` pins exactly one HA per
release and each release has a Python floor, so the interpreter picks the HA.

| CI leg | phacc pin | Home Assistant | Blocking? |
|---|---|---|---|
| Python 3.13 | `0.13.316` | 2026.2.3 — the `hacs.json` floor | yes |
| Python 3.14 | `0.13.356` | 2026.8.2 — what HA-PROD runs | yes |

Both rungs block. There is no `continue-on-error` anywhere in the matrix and
there must not be again (#835): the 3.13 rung spent its entire life marked
advisory and never passed once, invisibly, because a rung that cannot fail the
board is a rung nobody reads.

A third rung — Python 3.12 → HA 2025.1.4 — was removed in #836 together with
the 2025.1 floor it verified. Of 62 issues stating an HA version the oldest
ever reported is 2026.4.3, and none is on 2025.x; since the old floor let such
users install and file, that is absence rather than sampling. Note that 2026.2
is the **last HA that runs on Python 3.13** — raising the floor further makes
every rung 3.14, at which point the interpreter can no longer select the HA and
the matrix has to be re-cut around the phacc version.

Until #787 this was two legs both installing 2025.1.4, and nothing said so:
every test was green against an HA nineteen months older than the one users
run. Anything SEM asserts about the entity registry, config-entry migration,
the recorder, statistics or service-call validation was being verified against
a copy of HA nobody has.

The rungs were added `continue-on-error` on purpose — on top of a release, with
a deprecation backlog that needed unhurried triage rather than a green-chase.
**Turning a rung blocking once it came clean was the actual close-out of
#787**, and both flips are now done (#791 for 3.14, #835 for 3.13), so the
exemption is gone. `tests/test_787_ha_version_matrix.py` guards the shape: it
fails if a leg loses its pin, if the rungs collapse back onto one HA, if the
floor `hacs.json` promises stops being tested, or if any rung is made
non-blocking again.

Locally, `pip install -r tests/requirements_test.txt` gives you the rung that
matches your interpreter — the markers do the selection.

## Lint: a floor, not a strategy

`ruff check .` is a CI check and must be clean. It selects `F` (pyflakes),
`E9`, `B` (bugbear) and `ASYNC` — and nothing else. What it deliberately does
**not** select, and why, is written at the top of `ruff.toml`: import order,
`pyupgrade`, `flake8-datetimez` and blanket-except are all either style churn
across a release or, in the case of `DTZ`, actively wrong for an integration
that reasons in the user's local time on purpose. There is **no formatter**.

The ruff version is pinned in `.github/workflows/lint.yml`. Bump it
deliberately, in its own commit, with the tree clean afterwards — an unpinned
linter reddens the board on a day nobody touched the code, and a gate that
reddens by itself is a gate that gets muted.

Ruff is the floor. Every bug class that has actually bitten SEM was caught by a
guard that knew something ruff cannot know — HA's blocking-call list, the
fleet-vs-per-charger read rule, that a lit `html` template must not contain a
backtick. Those live in `tests/test_*_lint.py` / `tests/test_*_astguard.py`,
run under the Tests job, and are documented in
[`docs/BUG_CLASSES.md`](docs/BUG_CLASSES.md). When ruff and a domain guard
disagree about one rule, the domain guard wins and ruff's rule gets ignored
with a comment pointing at it — two lints answering one question differently
is how both end up ignored.

## The four-layer test pyramid

SEM tests live at four layers, each catching a different bug class. Use the one that matches what you're verifying. See [ADR 0007](docs/adr/0007-real-hass-test-framework.md) for the choice rule and rationale.

| Layer | Where | Catches | Cost |
|---|---|---|---|
| **Unit tests** | `tests/test_*.py` (mock `hass`) | Pure logic / arithmetic bugs | Fast (seconds) |
| **Scenario harness** | `tests/scenarios/*.yaml` + `tests/scenario_harness.py` | Decision-vs-enforcement drift, replay of real traces through the coordinator pipeline | Medium (sub-second per scenario) |
| **Real-hass tests** | `tests/test_setup_entry_*.py`, `tests/test_unload_reload_cycle.py`, … (`hass` fixture from `pytest-homeassistant-custom-component`) | HA lifecycle — setup, unload, reload, `hass.data` slot lifecycle, frontend resource registration races | Medium (ms-to-seconds per test) |
| **Live tests** | `tests/live/*.sh` | Time-boundary effects, entity reactivity, persistence across HA restart, real coordinator update path | Slow (minutes per test) |

Each is necessary; none is sufficient. The Phase B EV-budget unification (#282) bug was invisible to unit tests because it required different code paths reading different formulas — only a scenario replay or live observation could surface the disagreement. The real-hass layer was added in v1.7.0-beta.10 after entry-setup/unload bugs slipped past every mock-hass test in the suite.

### Live tests (`tests/live/`)

Bash + `curl` against a real Home Assistant instance. Reach for these when:
- You're fixing a bug that involves a real time boundary, sensor reactivity, or coordinator-to-sensor round-trip
- A unit test would pass but the live behaviour is what you actually care about
- You want a forever sentinel against a regression class

Live tests run against `HA-TEST` by default and **refuse to mutate `HA-PROD`** (`10.10.20.150`) unless `TESTS_LIVE_ALLOW_PROD=1` is set explicitly. See `tests/live/README.md` for the helpers and conventions.

### Scenario harness (`tests/scenarios/*.yaml`)

YAML-driven replays of timeline-of-readings. Reach for these when:
- You have a real trace from a user's PROD that should never regress
- You're testing the coordinator's decision logic without needing a real HA process
- You want CI coverage of "what does SEM do given these inputs"

A scenario YAML has a `config:` block (which becomes `coordinator.config`), an `ev_chargers:` block (use 2+ entries to exercise multi-charger distribution), a `timeline:` of sensor rows (sticky semantics — values carry forward unless overridden), and an `expect:` block with assertions. See `tests/scenarios/2026-05-28_surplus_leak.yaml` for a worked example.

### Real-hass tests (`tests/test_setup_entry_*.py`, `tests/test_unload_reload_cycle.py`, …)

In-process `HomeAssistant` instance via the `hass` fixture from `pytest-homeassistant-custom-component`. Reach for these when:
- You're testing entry setup / unload / reload behaviour, `hass.data` slot lifecycle, or frontend resource registration
- A mock-hass unit test would pass but the real HA call path is what you actually care about
- You want CI coverage of an HA-lifecycle bug class without a deploy cycle

Real-hass tests run against a real (but in-process) HA instance, so they're fast enough for CI on every PR. See ADR 0007 for the layer-choice rule.

## Branch Strategy

- `main` — stable releases only
- `develop` — **the release train**: a job cuts a pre-release from it once a
  day, automatically, whenever there is something to ship
- `feature/*` — work in progress, PR to develop when it is *ready to ship*

### develop is a release train — merging is publishing

Because the daily job tags whatever is on `develop`, a merge reaches beta
users within 24 hours. There is no queue to hide in and no "I'll clean it up
before the release" — the merge **is** the release decision.

So a change is **ready to ship** only when all four hold:

1. **Green.** Full suite passes on the merge result, and CI is green on the
   pushed commit — every workflow, including the Home-Assistant rung that
   matches production.
2. **Documented.** A `CHANGELOG.md` entry lands in the same change. This is
   not politeness: the daily job refuses to cut a release when the
   `[Unreleased]` section is empty, so an undocumented change literally
   cannot ship.
3. **Verified against reality.** Anything touching the Home Assistant
   pipeline — entities, config entries, device control — is checked on a
   live instance before merge, not only in tests.
4. **Complete, or inert.** This is the gate that makes a train possible.
   Work that is not finished may still merge *provided it does nothing* to
   anyone who has not opted in: default-off switches, recording-only
   layers, opt-in probes. What must never merge is a half-wired live path —
   a feature that partly acts.

Gate 4 is how SEM has always shipped large work, now written down: battery
arbitrage landed complete but dormant behind a default-off switch; the
curtailment probe ships opt-in; the battery-night recorder measures for a
season before anything spends on its numbers. Build it whole, land it
asleep, wake it deliberately in its own release.

**If it cannot satisfy all four, it stays on its branch.** Long-lived
branches are fine. Half-awake features on `develop` are not.

### What the daily job will not do

It never cuts a **stable** release (those are gated on reporter confirms,
not the calendar), never deploys to hardware, and skips entirely when the
tree is dirty, CI is not green, a release already went out that day, or a
hold is in place.

## Architecture Decision Records

When a decision is worth keeping (new device class, invariant change, refactor that reshapes a subsystem), add a one-pager to [`docs/adr/`](docs/adr/README.md) using the Nygard format. Bugfixes and routine feature work do NOT need an ADR.

## Questions?

Open a [discussion](https://github.com/traktore-org/sem-community/discussions) or ask in the [HA Community thread](https://community.home-assistant.io/t/solar-energy-management-sem-smart-solar-ev-battery-orchestration/1003701).
