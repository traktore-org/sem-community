# Solar Energy Management - Test Suite

This directory contains comprehensive tests for the Solar Energy Management integration, ensuring calculation accuracy and preventing bugs before deployment.

## Test Categories

### 1. Flow Accumulation Tests (`test_flow_accumulation.py`)

**Purpose**: Prevent calculation bugs like the flow energy accumulation issue (where flows showed 3x actual values).

**What it tests**:
- ✅ Flow accumulation guard prevents duplicate accumulation
- ✅ Values accumulate correctly across different time windows
- ✅ Accumulation trackers reset properly on new day
- ✅ Flow energy matches total solar energy
- ✅ Home consumption calculation accuracy
- ✅ Energy balance equation holds
- ✅ TOTAL sensors never decrease within a day
- ✅ Multiple rapid updates don't cause overflow

### 2. Sensor Tests (`test_*.py`)

**Purpose**: Verify sensor definitions, attributes, and basic functionality.

**What it tests**:
- Sensor entity creation
- Correct attributes, units, device classes
- Static value assignments
- Sensor availability

## Running Tests

### Quick Run (All Tests)

```bash
cd custom_components/solar_energy_management
./run_tests.sh
```

### Run Specific Test File

```bash
pytest tests/test_flow_accumulation.py -v
```

### Run Specific Test Class

```bash
pytest tests/test_flow_accumulation.py::TestFlowAccumulationGuard -v
```

### Run Calculation Verification Only

```bash
pytest tests/test_flow_accumulation.py::TestFlowEnergyCalculations -v
pytest tests/test_flow_accumulation.py::TestEnergyBalanceEquation -v
```

## Pre-Deployment Checklist

**Before deploying to TEST or PROD, ensure**:

1. ✅ All tests pass: `./run_tests.sh`
2. ✅ No calculation errors in flow tests
3. ✅ Energy balance equation satisfied
4. ✅ GitHub Actions tests pass (if enabled)

## Installation

Install test dependencies:

```bash
pip install -r tests/requirements_test.txt
```

## Test Coverage

These tests would have **caught the flow accumulation bug** we fixed:

```python
# This test would have FAILED before the fix
async def test_prevents_duplicate_accumulation_same_5min_window():
    # First update
    flow_1 = get_flow_energy()  # 5.0 kWh

    # Second update (same 5-min window) - WITHOUT guard
    flow_2 = get_flow_energy()  # 10.0 kWh ❌ BUG!

    assert flow_2 == flow_1  # FAILS - catches the bug!
```

## Continuous Integration

GitHub Actions automatically runs tests on:
- Every push to `develop` or `main`
- Every pull request
- Manual trigger via workflow dispatch

See `.github/workflows/tests.yml` for configuration.

## Test Philosophy

**Integration over Unit**: These tests verify real-world behavior, not just isolated functions.

**Time-based Testing**: Uses `freezegun` to test time-dependent accumulation logic.

**Energy Balance**: Validates fundamental physics: energy can't be created or destroyed.

**Realistic Data**: Uses actual sensor values from production logs.

## Adding New Tests

When adding new calculations:

1. Add a test in `test_flow_accumulation.py` for the calculation
2. Add a test for edge cases (negative values, overflow, etc.)
3. Add a test for state persistence across updates
4. Run `./run_tests.sh` to verify

## Troubleshooting

**Tests fail with "fixture not found"**:
```bash
pip install pytest-homeassistant-custom-component
```

**Tests fail with "freezegun not found"**:
```bash
pip install freezegun
```

**Tests hang or timeout**:
- Check for infinite loops in coordinator logic
- Verify mock setup is correct
- Use `-x` flag to stop on first failure: `pytest -x`

## Future Improvements

- [ ] Add performance benchmarks
- [ ] Add stress tests (1000+ rapid updates)
- [ ] Add battery state-of-charge calculation tests
- [ ] Add EV charging logic tests
- [ ] Add cost calculation accuracy tests
