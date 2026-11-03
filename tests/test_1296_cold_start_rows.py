"""#1296 — Solar and Grid blank for minutes after a restart.

At a cold start Home Assistant writes every registered sensor as
``unavailable`` with ``restored: True`` until its integration polls. The
declared tier skipped such a row as dead (a disabled or failing entry,
#1189 review), the name tier skipped it too (no ``state_class``), and a
name guess from any live sensor was held. With a guess held on both sides
SEM rescans only every 30 cycles, so the real meter was taken five minutes
after it came alive — and the guess steers nothing until the counters prove
it, which is the blank the reporter saw.

A restored row is could-not-ask, not "no": the declared tier asks again
every cycle until the dark grace has passed since its first miss, and the
30-cycle clock does not run while it waits.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.consts.core import (
    SENSOR_DARK_READ_GRACE_S,
)
from custom_components.solar_energy_management.coordinator import sensor_reader as sr_mod
from custom_components.solar_energy_management.tests.test_1189_dsmr_any_language import (
    _METER,
    _Meter,
    _state,
)


def _restored(unit="kW"):
    s = _state("unavailable", unit, device_class="power", state_class=None)
    s.attributes["restored"] = True
    return s


class _ColdStart:
    """A DSMR meter whose rows are still restored on the first cycle, and a
    heat pump whose live power sensors match the grid name patterns."""

    def __init__(self, monkeypatch):
        self.meter = _Meter(monkeypatch, "nl", import_kw=1.2, export_kw=0.0)
        self.live = {eid: self.meter.states[eid] for eid in (self.meter.imp, self.meter.exp)}
        for eid in self.live:
            self.meter.states[eid] = _restored()
        self.meter.states["sensor.heat_pump_power_consumption"] = _state(
            400, device_class="power")
        self.meter.states["sensor.heat_pump_power_production"] = _state(
            0, device_class="power")
        dsmr = set(self.meter.registry.entities)
        self.meter.reader._get_device_for_entity = lambda eid: (
            _METER if eid in dsmr else "heat_pump")
        self.clock = [1000.0]
        self.meter.reader._now_monotonic = lambda: self.clock[0]

    def cycle(self, seconds=10.0):
        self.clock[0] += seconds
        return self.meter.read()

    def wake(self):
        self.meter.states.update(self.live)


class TestTheMeterIsTakenWhenItComesAlive:
    def test_the_declared_pair_is_taken_on_the_cycle_it_comes_alive(self, monkeypatch):
        cold = _ColdStart(monkeypatch)
        cold.cycle()
        assert cold.meter.picks[2] != "declared"      # nothing to declare yet
        cold.wake()
        power = cold.cycle()
        assert cold.meter.picks == (cold.meter.imp, cold.meter.exp, "declared")
        assert power.grid_power == pytest.approx(-1200.0)

    def test_the_wait_is_not_charged_to_the_rescan_clock(self, monkeypatch):
        cold = _ColdStart(monkeypatch)
        for _ in range(3):
            cold.cycle()
        cold.wake()
        cold.cycle()
        assert cold.meter.picks[2] == "declared"

    def test_a_row_still_restored_after_the_grace_is_dead(self, monkeypatch):
        """The #1189 rule stands: an integration that never sets its rows
        up is not a meter, and the search moves on."""
        cold = _ColdStart(monkeypatch)
        cold.cycle()
        cold.cycle(SENSOR_DARK_READ_GRACE_S + 1)
        assert cold.meter.picks[2] == "any-device"
        assert not cold.meter.reader._declared_rows_waiting


class TestTheSingleCycleRuleStillHolds:
    def test_a_restored_row_is_skipped_within_one_read(self, monkeypatch):
        """Same read as #1189's test: with a working same-device pair beside
        the restored rows, that pair is taken at once."""
        meter = _Meter(monkeypatch, "nl", import_kw=1.2, export_kw=0.0)
        for eid in (meter.imp, meter.exp):
            meter.states[eid] = _restored()
        meter.states["sensor.p1_power_consumption"] = _state(800, device_class="power")
        meter.states["sensor.p1_power_production"] = _state(0, device_class="power")
        power = meter.read()
        assert meter.picks[:2] == ("sensor.p1_power_consumption",
                                   "sensor.p1_power_production")
        assert power.grid_power == pytest.approx(-800.0)


class TestDerivedPowerSeesARestoredRow:
    """The derived grid power (a meter with counters in the Energy Dashboard
    and no power link) already reads a restored row's registry record, so it
    needs no rebuild once the row comes alive."""

    def test_a_restored_power_row_on_the_counter_device_is_derived(self):
        from custom_components.solar_energy_management import ha_energy_reader as her

        hass = MagicMock()
        restored = _restored("W")
        hass.states.get = lambda eid: {"sensor.p1_power": restored}.get(eid)
        counter = MagicMock(entity_id="sensor.p1_energy_import", device_id="p1",
                            domain="sensor", disabled_by=None, platform="homewizard")
        power = MagicMock(entity_id="sensor.p1_power", device_id="p1",
                          domain="sensor", disabled_by=None, platform="homewizard",
                          translation_key="active_power_w",
                          unique_id="aabbcc_active_power_w",
                          original_device_class="power", unit_of_measurement="W")
        registry = MagicMock()
        registry.async_get = lambda eid: counter
        with patch.object(her.er, "async_get", return_value=registry), \
                patch.object(her.er, "async_entries_for_device", return_value=[counter, power]):
            found = her._find_power_sensor_on_device(
                hass, "sensor.p1_energy_import", her._POWER_DERIVE_RULES["grid"])
        assert found == "sensor.p1_power"
