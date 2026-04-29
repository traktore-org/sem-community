# Test Coverage Documentation

## Overview

The Solar Energy Management integration has comprehensive test coverage across 20+ test files with 1,000+ test cases.

## Test Files Summary

| File | Tests | Purpose |
|------|-------|---------|
| **test_coordinator.py** | 72 | Core coordinator logic, state management, data processing |
| **test_ev_taper_detector.py** | 64 | EV Intelligence: taper detection, virtual SOC, consumption learning, skip logic, battery health |
| **test_hardware_detection.py** | 56 | Auto-discovery for 13+ integrations, confidence scoring |
| **test_hardware_compat.py** | 43 | End-to-end hardware combination verification (11 inverter+charger pairs) |
| **test_load_management.py** | 37 | Shed/restore operations, device prioritization, emergency handling |
| **test_hot_water.py** | 35 | Hot water control, Legionella prevention, temperature logic |
| **test_surplus_controller.py** | 34 | Multi-device surplus routing, price-responsive mode |
| **test_tariff_provider.py** | 32 | Static/dynamic tariffs, price level detection |
| **test_storage.py** | 32 | Persistent state, validation, migration |
| **test_soc_zone_strategy.py** | 31 | Four-zone battery model, hysteresis, zone transitions |
| **test_scenario.py** | 25 | Real-world usage scenarios (sunny day, cloudy, night) |
| **test_proportional_flows.py** | 25 | Flow distribution, energy balance validation |
| **test_integration.py** | 25 | End-to-end integration tests |
| **test_utility_signals.py** | 22 | Utility signal monitoring, ripple control |
| **test_pv_performance.py** | 21 | PV analytics, specific yield, degradation |
| **test_notifications.py** | 26 | KEBA display + mobile push, flap suppression, rest_command/notify service detection |
| **test_peak_aware_charging.py** | 18 | Peak-aware night charging, current limiting |
| **test_sensor.py** | 16 | Sensor entities, attributes, units, state reporting |
| **test_services.py** | 15 | Service calls, parameter validation, error handling |
| **test_multi_device_aggregation.py** | 15 | Multi-inverter/battery/tariff summing, SOC averaging |
| **test_energy_flow_balance.py** | 13 | Energy flow calculations, hardware/calculated fallback |
| **test_flow_accumulation.py** | 11 | Flow energy accumulation, daily resets |
| **test_switch.py** | 11 | Switch entities, toggle operations, state persistence |
| **test_config_flow.py** | 11 | Configuration UI, validation, setup wizard |
| **test_autarky.py** | 9 | Self-sufficiency calculations, grid independence |
| **test_yearly_seeding.py** | 7 | Yearly KPI seeding from HA recorder |
| **test_dual_state_machine.py** | 17 | Charging state machine, transitions, priority logic |
| **test_binary_sensor.py** | 4 | Binary sensors, on/off states, device classes |
| **conftest.py** | N/A | Shared fixtures, mocks, test utilities |

**Total: 1,032 tests**

---

## New Test Files Added

### 1. test_energy_flow_balance.py (13 tests)

Tests the energy flow calculation logic and intelligent fallback between hardware and calculated values.

**Test Classes:**
- `TestEnergyFlowBalance` (9 tests)
  - Hardware sensor availability and usage
  - Calculated value fallback when hardware is 0
  - Night time handling (both zero)
  - Energy conservation (sources = destinations)
  - Flow distribution priority
  - Day boundary resets
  - Unconfigured sensor fallback
  - Negative flow prevention
  - Small value threshold (< 10Wh)

- `TestEnergyFlowEdgeCases` (4 tests)
  - Simultaneous charge/discharge
  - Very large power values (100kW+)
  - Sensor unavailable fallback
  - Invalid sensor states

**Coverage:**
- Hardware vs calculated solar energy selection
- Energy balance validation
- Flow priority allocation (Home > Battery > EV > Grid)
- Edge cases and error handling

---

### 2. test_peak_aware_charging.py (18 tests)

Tests the peak-aware night charging feature that limits EV charging current based on target peak power.

**Test Classes:**
- `TestPeakAwareNightCharging` (10 tests)
  - Safe current calculation with low home load
  - Charging pause with high home load
  - Current EV power accounting
  - Non-charging mode returns 0
  - Disabled load management returns max current
  - Maximum current clamping (16A)
  - Buffer prevents oscillation (0.3kW)
  - Service call to charger
  - Skip when EV not connected
  - Skip when not night charging

- `TestPeakAwareEdgeCases` (5 tests)
  - Negative home power handling
  - Missing power value handling
  - Very high peak limits (commercial)
  - Battery protection integration
  - Load management sensor updates

- `TestPeakAwareRealWorldScenarios` (3 tests)
  - Washing machine starts during charging
  - Gradual home load increase
  - Overnight charging simulation (9 hours)

**Coverage:**
- Peak load management calculations
- Dynamic current limiting (6-16A range)
- KEBA charger service calls
- Real-world usage patterns
- Edge cases and error scenarios

---

## Test Coverage by Feature

### Core Functionality
| Feature | Test File | Test Count | Coverage |
|---------|-----------|------------|----------|
| Energy Flow Calculation | test_energy_flow_balance.py | 13 | ✅ Comprehensive |
| Flow Accumulation | test_flow_accumulation.py | 11 | ✅ Comprehensive |
| Coordinator Logic | test_coordinator.py | 72 | ✅ Extensive |
| State Machine | test_dual_state_machine.py | 17 | ✅ Comprehensive |

### Advanced Features
| Feature | Test File | Test Count | Coverage |
|---------|-----------|------------|----------|
| EV Intelligence | test_ev_taper_detector.py | 64 | ✅ Comprehensive |
| Multi-Device Aggregation | test_multi_device_aggregation.py | 15 | ✅ Comprehensive |
| Multi-Charger Control | test_multi_charger_control.py | 41 | ✅ Comprehensive |
| Hardware Compatibility | test_hardware_compat.py | 43 | ✅ Comprehensive |
| Hardware Detection | test_hardware_detection.py | 56 | ✅ Comprehensive |
| Load Management | test_load_management.py | 37 | ✅ Comprehensive |
| Hot Water Control | test_hot_water.py | 35 | ✅ Comprehensive |
| Surplus Controller | test_surplus_controller.py | 34 | ✅ Comprehensive |
| SOC Zone Strategy | test_soc_zone_strategy.py | 31 | ✅ Comprehensive |
| Peak-Aware Charging | test_peak_aware_charging.py | 18 | ✅ Comprehensive |
| Autarky Calculation | test_autarky.py | 9 | ✅ Good |

### User Interface
| Feature | Test File | Test Count | Coverage |
|---------|-----------|------------|----------|
| Config Flow | test_config_flow.py | 11 | ✅ Good |
| Sensors | test_sensor.py | 16 | ✅ Good |
| Binary Sensors | test_binary_sensor.py | 4 | ⚠️ Basic |
| Switches | test_switch.py | 13 | ✅ Good |
| Services | test_services.py | 15 | ✅ Good |

---

## Test Execution

### Run All Tests
```bash
pytest tests/
```

### Run Specific Test File
```bash
pytest tests/test_energy_flow_balance.py -v
pytest tests/test_peak_aware_charging.py -v
```

### Run Specific Test Class
```bash
pytest tests/test_energy_flow_balance.py::TestEnergyFlowBalance -v
pytest tests/test_peak_aware_charging.py::TestPeakAwareNightCharging -v
```

### Run Specific Test
```bash
pytest tests/test_energy_flow_balance.py::TestEnergyFlowBalance::test_uses_hardware_when_available_and_nonzero -v
```

### Run with Coverage Report
```bash
pytest tests/ --cov=custom_components.solar_energy_management --cov-report=html
```

### Run Only Fast Tests
```bash
pytest tests/ -m "not slow"
```

---

## Test Patterns Used

### 1. **Mocking Home Assistant**
```python
def mock_get_state(entity_id):
    state = Mock()
    state.state = sensor_values.get(entity_id, "0")
    return state

mock_hass.states.get = mock_get_state
```

### 2. **Time Freezing**
```python
with freeze_time("2025-11-12 14:00:00"):
    values = coordinator._get_hardware_sensor_values()
```

### 3. **Async Testing**
```python
@pytest.mark.asyncio
async def test_something(coordinator, mock_hass):
    await coordinator.async_config_entry_first_refresh()
```

### 4. **State Transitions**
```python
# Test state machine transitions
initial_state = coordinator.get_charging_state()
# ... trigger event ...
new_state = coordinator.get_charging_state()
assert new_state != initial_state
```

### 5. **Service Call Verification**
```python
mock_hass.services.async_call = AsyncMock()
await coordinator._apply_ev_charging_current(...)
mock_hass.services.async_call.assert_called_once()
```

---

## Test Data Patterns

### Realistic Sensor Values
```python
sensor_values = {
    "sensor.solar_total": "1020.5",      # 20.5 kWh today
    "sensor.solar_power": "5000",         # 5kW current
    "sensor.grid_import": "515.3",        # 15.3 kWh imported
    "sensor.grid_export": "303.2",        # 3.2 kWh exported
    "sensor.battery_charge": "208.7",     # 8.7 kWh charged
    "sensor.battery_discharge": "186.2",  # 6.2 kWh discharged
    "sensor.ev_charging_power": "9750",   # 9.75kW EV charging
}
```

### Edge Cases
```python
# Test extreme values
"sensor.solar_power": "150000"    # 150kW (commercial)
"sensor.grid_power": "-100000"    # Heavy export

# Test invalid states
"sensor.solar_total": "unavailable"
"sensor.solar_total": "unknown"
"sensor.solar_total": "-100"      # Negative

# Test zero/near-zero
"sensor.solar_total": "1000.005"  # 5Wh (< 10Wh threshold)
```

---

## Assertions and Validations

### Energy Balance
```python
# Verify energy conservation
total_sources = solar + grid_import + battery_discharge
total_destinations = home + grid_export + battery_charge
assert abs(total_sources - total_destinations) < 0.1
```

### Flow Values
```python
# Verify non-negative flows
for flow_key in flow_keys:
    assert values.get(flow_key, 0) >= 0

# Verify flow accumulation
assert flow_2 > flow_1
```

### Current Limits
```python
# Verify current within bounds
assert 0 <= safe_current <= 16  # KEBA range: 0 or 6-16A
assert safe_current in [0] + list(range(6, 17))
```

---

## Coverage Gaps & Future Tests

### Areas Needing More Coverage

1. **Load Management** ⚠️
   - Shed/restore load operations
   - Multiple device prioritization
   - Emergency peak handling
   - **Status**: Basic coverage in peak_aware tests

2. **Hardware Detection** ⚠️
   - Autodiscovery for 13+ integrations
   - Confidence scoring
   - Fallback patterns
   - **Status**: No dedicated tests yet

3. **Energy Dashboard Integration** ⚠️
   - Statistics entity creation
   - Long-term statistics
   - Energy flow card data
   - **Status**: Not tested

4. **Error Recovery** ⚠️
   - Network failures
   - Sensor unavailability mid-day
   - Configuration migration
   - **Status**: Partial coverage

5. **Performance** ⚠️
   - Update cycle timing
   - Memory usage
   - Large data volumes
   - **Status**: No performance tests

---

## Suggested Additional Tests

### Priority 1: Critical Features
```python
# tests/test_hardware_detection.py
- test_huawei_solar_autodiscovery()
- test_goodwe_autodiscovery()
- test_keba_charger_detection()
- test_confidence_scoring()

# tests/test_load_management.py
- test_shed_load_on_peak_warning()
- test_restore_load_below_threshold()
- test_emergency_peak_handling()
- test_device_priority_order()
```

### Priority 2: Error Handling
```python
# tests/test_error_recovery.py
- test_sensor_unavailable_recovery()
- test_network_timeout_retry()
- test_invalid_sensor_data()
- test_configuration_migration()
```

### Priority 3: Integration
```python
# tests/test_energy_dashboard.py
- test_statistics_entity_creation()
- test_long_term_statistics()
- test_energy_flow_card_compatibility()
```

---

## Running Tests in CI/CD

### GitHub Actions Workflow
```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements_test.txt
      - run: pytest tests/ --cov --cov-report=xml
      - uses: codecov/codecov-action@v3
```

### Test Requirements
```text
# requirements_test.txt
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-cov>=4.1.0
pytest-homeassistant-custom-component>=0.13.0
freezegun>=1.2.0
```

---

## Test Maintenance

### Adding New Tests
1. Identify feature to test
2. Create test file or add to existing
3. Use established patterns (see above)
4. Include edge cases
5. Add docstrings
6. Run pytest locally
7. Update this documentation

### Test Naming Convention
```python
# Good test names (descriptive)
test_uses_hardware_when_available_and_nonzero()
test_calculates_safe_current_with_low_home_load()
test_scenario_washing_machine_starts_during_charging()

# Bad test names (vague)
test_energy()
test_charging()
test_case_1()
```

### Test Organization
```
tests/
├── conftest.py                      # Shared fixtures
├── test_*.py                        # Test modules
│   ├── TestFeatureName              # Test class
│   │   ├── test_normal_case()      # Normal operation
│   │   ├── test_edge_case()        # Edge cases
│   │   └── test_error_case()       # Error handling
│   └── TestFeatureEdgeCases         # Edge case class
└── TEST_COVERAGE.md                 # This file
```

---

## Test Metrics

### Current Status (v1.3.0)
- **Total Tests**: 1,073 tests
- **Test Files**: 28 files
- **Coverage**: ~90% (estimated)
- **Pass Rate**: 100%

### Recent Improvements (v1.3.0)
1. ✅ Added 64 EV Intelligence tests (taper, virtual SOC, skip logic, battery health)
2. ✅ Added 15 multi-device aggregation tests
3. ✅ Added hardware compatibility and detection suites (99 tests)
4. ✅ Added hot water, surplus controller, SOC zone, tariff, storage tests
5. ✅ Total test count grew from 199 to 1,032

### Goals
- **1,000+ tests**: ✅ Achieved!
- **90% coverage**: ✅ Achieved (estimated)
- **Performance tests**: ❌ Not yet
- **Integration tests**: ✅ Comprehensive

---

## Contributing Tests

When contributing new features, please include:
1. **Unit tests** for core logic
2. **Integration tests** for HA components
3. **Edge case tests** for error scenarios
4. **Real-world scenario tests** for usage patterns
5. **Documentation** in this file

Example PR checklist:
- [ ] Tests added for new feature
- [ ] All existing tests pass
- [ ] Coverage maintained or improved
- [ ] TEST_COVERAGE.md updated
- [ ] Test docstrings added

---

*Last updated: 2026-04-26*
*Version: 1.3.0*
*Total Tests: 1,073*
