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
- Update translations (6 languages) for user-facing text

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

## Branch Strategy

- `main` — stable releases only
- `develop` — integration branch, CI must pass
- `feature/*` — work in progress, PR to develop when ready

## Questions?

Open a [discussion](https://github.com/traktore-org/sem-community/discussions) or ask in the [HA Community thread](https://community.home-assistant.io/t/solar-energy-management-sem-smart-solar-ev-battery-orchestration/1003701).
