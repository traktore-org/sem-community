"""#744 (continued) — the rated-power ratchet must not learn from kWh ticks.

Azlinon's live report: a Shelly PM with 24 W of bulbs shows ~1.0 kW, greyed.
Mechanism: for a load with no power sensor, ``observed_power_w`` derives
watts from the energy counter — and a 0.01 kWh tick over a short window
reads as a ~1 kW instant. ``calibrate_rated_power`` (an up-only ratchet)
adopts it; the deriver's cap is 2× rated and re-bases on every adoption,
so the rating climbs geometrically toward absurdity — and the poisoned
value persists across restarts via the calibrated-ratings snapshot.

The rule: CALIBRATION ONLY FROM A REAL POWER SENSOR. The energy deriver
stays what it is — a display/runtime-credit estimate — and estimates
must never teach the model (the same class as #743's curtailed days
and #753's warm-up disconnects: a guessed number is not a measurement).
"""

import time as _time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.devices.base import (
    ControllableDevice, SwitchDevice,
)


def _dev(*, power_entity=None, energy_entity="sensor.bulbs_energy",
         rated=24.0):
    hass = MagicMock()
    dev = SwitchDevice(
        hass, "bulbs", "Bulbs", rated_power=rated,
        entity_id="switch.bulbs", power_entity_id=power_entity,
        energy_entity_id=energy_entity)
    return dev


@pytest.mark.unit
class TestCalibrationNeedsARealSensor:
    def test_an_energy_tick_spike_does_not_ratchet(self):
        dev = _dev(power_entity=None, rated=24.0)
        from custom_components.solar_energy_management.devices.base import DeviceState
        dev._status.state = DeviceState.ACTIVE
        # The deriver hands back a tick spike — 1 kW "instant".
        dev.observed_power_w = lambda: 1000.0
        dev.calibrate_rated_power()
        assert dev.rated_power == 24.0  # not adopted

    def test_a_power_sensor_still_calibrates(self):
        dev = _dev(power_entity="sensor.bulbs_power", rated=24.0)
        from custom_components.solar_energy_management.devices.base import DeviceState
        dev._status.state = DeviceState.ACTIVE
        dev.observed_power_w = lambda: 60.0
        dev.calibrate_rated_power()
        assert dev.rated_power == 60.0  # the real ratchet stays
