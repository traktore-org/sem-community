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
3. Ensure tests pass: `python -m pytest tests/ -v`
4. Update documentation if your change affects user-facing behavior
5. Submit a PR to `develop` (not `main`)

### Code Style

- Python: follow existing patterns in the codebase
- No new dependencies unless absolutely necessary
- Add tests for new features
- Update translations (15 languages: de, en, es, fr, it, nl, pt, pl, sv, cs, da, fi, hu, ro, no) for user-facing text

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

# Run tests
python -m pytest tests/ -v

# Deploy to test HA instance
rsync -av --delete --exclude='__pycache__' --exclude='.git' \
  ./ your-ha:/config/custom_components/solar_energy_management/
```

## The three-layer test pyramid

SEM tests live at three layers, each catching a different bug class. Use the one that matches what you're verifying:

| Layer | Where | Catches | Cost |
|---|---|---|---|
| **Unit tests** | `tests/test_*.py` | Pure logic / arithmetic bugs | Fast (seconds) |
| **Scenario harness** | `tests/scenarios/*.yaml` + `tests/scenario_harness.py` | Decision-vs-enforcement drift, replay of real traces through the coordinator pipeline | Medium (sub-second per scenario) |
| **Live tests** | `tests/live/*.sh` | Time-boundary effects, entity reactivity, persistence across HA restart, real coordinator update path | Slow (minutes per test) |

Each is necessary; none is sufficient. The Phase B EV-budget unification (#282) bug was invisible to unit tests because it required different code paths reading different formulas — only a scenario replay or live observation could surface the disagreement.

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

## Branch Strategy

- `main` — stable releases only
- `develop` — integration branch, CI must pass
- `feature/*` — work in progress, PR to develop when ready

## Review Flow

Lightweight by design — single maintainer, fast beta cadence.

| Trigger | What runs | Cost |
|---|---|---|
| Every commit | Pre-commit hooks (Ruff format + lint, YAML/JSON/TOML check, `hassfest-lite`) | seconds, local |
| Every PR | CI gates (Hassfest, HACS validation, pytest 3.12/3.13, card-test) + CodeRabbit AI review per [`.coderabbit.yaml`](.coderabbit.yaml) | ~15 min, no human time |
| Optional second opinion on non-trivial PRs | `/codex review` for an independent AI take — useful when author = reviewer | ~2 min |
| Crossing a complexity threshold (new device class, sign-convention change, new fitness function) | Write a 1-page [ADR](docs/adr/README.md) | 15–30 min, one-time |
| Before each release | Soak on HA-TEST + `~/bin/validate-sem.sh` | already in the deploy script |

### Setup pre-commit (one-time)

```bash
pip install pre-commit
pre-commit install --hook-type pre-commit --hook-type pre-push
```

Now every `git commit` runs Ruff + sanity checks locally before CI burns 15 min. Skip with `--no-verify` only if you really mean it.

### Architecture Decision Records

When a decision is worth keeping (new device class, invariant change, refactor that reshapes a subsystem), add a one-pager to [`docs/adr/`](docs/adr/README.md) using the Nygard format. Bugfixes and routine feature work do NOT need an ADR.

## Questions?

Open a [discussion](https://github.com/traktore-org/sem-community/discussions) or ask in the [HA Community thread](https://community.home-assistant.io/t/solar-energy-management-sem-smart-solar-ev-battery-orchestration/1003701).
