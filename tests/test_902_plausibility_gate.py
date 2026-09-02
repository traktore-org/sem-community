"""#902 — a garbage sample out of a modbus dropout is not a measurement.

HA-PROD, 02.09.2026, ``sensor.battery_1_batterieladung`` (Huawei LUNA):

    09:46:35  soc 93 %      battery_power   5 000 W
    09:47:06  soc unavailable
    09:47:31  soc 0.0 %     battery_power  22 806 824 W     <- one cycle
    09:47:59  soc 93 %      battery_power   4 999 W

SEM published both. For that cycle the fleet read the pack as EMPTY (Zone 1,
"battery priority": car idled, discharge clamped) and 22.8 MW went into a
``state_class: measurement`` entity. #875 taught the reader that a SOC never
read is unknown; a SOC read as garbage was still taken at face value.

The rule: a value no battery can produce is treated exactly like a sensor
that did not answer — the existing dark-read path (hold the last valid SOC;
0.0 + the unavailable flags for power). Two gates, both physical:

* SOC may not move more than ``BATTERY_SOC_MAX_STEP_PCT`` between two reads.
  A LUNA moves single-digit percent per MINUTE at full power. But a level
  that PERSISTS is the truth (the pack really did change while the sensor
  was dark for hours) — so a rejected level is accepted once it has held for
  ``BATTERY_SOC_STEP_CONFIRM_READS`` consecutive reads.
* Battery power beyond ``BATTERY_POWER_PLAUSIBLE_MAX_W`` is not a home
  battery. 22.8 MW is 2 000x the hardware.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, Mock

import pytest

from custom_components.solar_energy_management.consts.core import (
    BATTERY_POWER_PLAUSIBLE_MAX_W,
    BATTERY_SOC_MAX_STEP_PCT,
    BATTERY_SOC_STEP_CONFIRM_READS,
)
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)


def _state(value, unit):
    import homeassistant.util.dt as dt_util
    s = Mock()
    s.state = str(value)
    s.attributes = {"unit_of_measurement": unit}
    s.last_updated = s.last_reported = dt_util.utcnow()
    return s


def _reader(soc, power):
    """``soc`` / ``power`` are one-element lists so a test can move them."""
    hass = MagicMock()
    hass.states = MagicMock()

    def _get(eid):
        if eid == "sensor.soc":
            return _state(soc[0], "%")
        if eid == "sensor.bp":
            return _state(power[0], "W")
        return None

    hass.states.get = _get
    r = SensorReader(hass, {
        "battery_soc_sensor": "sensor.soc",
        "battery_power_sensor": "sensor.bp",
    })
    r._energy_dashboard_config = None
    return r


class TestSocStepGate:
    def test_the_prod_trace_holds_93_through_the_zero(self):
        soc, power = ["93"], ["5000"]
        r = _reader(soc, power)
        r.read_power()
        soc[0] = "unavailable"
        r.read_power()
        soc[0] = "0.0"
        p = r.read_power()
        assert p.battery_soc == pytest.approx(93.0), "the 0 % lie was published"
        assert p.battery_soc_unavailable is True
        assert p.battery_soc_known is True
        soc[0] = "93"
        p = r.read_power()
        assert p.battery_soc == pytest.approx(93.0)
        assert p.battery_soc_unavailable is False

    def test_a_legitimate_move_inside_the_bound_is_accepted(self):
        soc, power = ["93"], ["5000"]
        r = _reader(soc, power)
        r.read_power()
        soc[0] = str(93 - BATTERY_SOC_MAX_STEP_PCT + 1)
        p = r.read_power()
        assert p.battery_soc == pytest.approx(93 - BATTERY_SOC_MAX_STEP_PCT + 1)
        assert p.battery_soc_unavailable is False

    def test_a_level_that_persists_is_the_truth(self):
        """The sensor was dark for hours and the pack really did drain: the
        first read after the gap is rejected as a step, but the same level
        on the following reads is accepted — a hold must never get stuck."""
        soc, power = ["93"], ["5000"]
        r = _reader(soc, power)
        r.read_power()
        soc[0] = "40"
        seen = []
        for _ in range(BATTERY_SOC_STEP_CONFIRM_READS + 1):
            seen.append(r.read_power().battery_soc)
        assert seen[0] == pytest.approx(93.0), "the first step was believed"
        assert seen[-1] == pytest.approx(40.0), (
            f"a level held for {BATTERY_SOC_STEP_CONFIRM_READS} reads was still "
            f"rejected: {seen}"
        )

    def test_a_flicker_between_two_levels_never_confirms(self):
        """0, 93, 0, 93 — the garbage never repeats itself, so it never
        becomes the truth."""
        soc, power = ["93"], ["5000"]
        r = _reader(soc, power)
        r.read_power()
        for v in ("0.0", "93", "0.0", "93", "0.0"):
            soc[0] = v
            p = r.read_power()
            assert p.battery_soc == pytest.approx(93.0), f"published {p.battery_soc} on {v}"

    def test_the_first_ever_read_is_taken_as_is(self):
        """No last value → nothing to step from. #875 owns the never-read
        window; this gate only compares against a value that exists."""
        soc, power = ["12"], ["5000"]
        p = _reader(soc, power).read_power()
        assert p.battery_soc == pytest.approx(12.0)
        assert p.battery_soc_known is True

    def test_the_rejection_is_logged_once_per_episode(self, caplog):
        from custom_components.solar_energy_management.utils.log_gate import reset_log_gate
        reset_log_gate()   # the #762 gate is process-global; earlier tests primed it
        soc, power = ["93"], ["5000"]
        r = _reader(soc, power)
        r.read_power()
        soc[0] = "0.0"
        with caplog.at_level(logging.WARNING):
            r.read_power()
            r.read_power()
        hits = [rec for rec in caplog.records if "902" in rec.message or "implausible" in rec.message.lower()]
        assert len(hits) == 1, [rec.message for rec in caplog.records]


class TestBatteryPowerBound:
    def test_22_megawatts_is_a_dark_read(self):
        soc, power = ["93"], ["5000"]
        r = _reader(soc, power)
        r.read_power()
        power[0] = "22806824"
        p = r.read_power()
        assert p.battery_power == 0.0, "22.8 MW was published as a measurement"
        assert p.battery_power_unavailable is True
        assert p.battery_power_all_unavailable is True, "the entity would show 0 W instead of unavailable"
        assert p.inputs_degraded is True, "a garbage cycle must not steer"

    def test_the_bound_is_generous_to_real_hardware(self):
        assert BATTERY_POWER_PLAUSIBLE_MAX_W >= 50_000

    def test_a_real_reading_is_untouched(self):
        soc, power = ["93"], ["-4800"]
        p = _reader(soc, power).read_power()
        assert p.battery_power == pytest.approx(-4800.0)
        assert p.battery_power_unavailable is False
        assert p.inputs_degraded is False

    def test_recovery_the_next_cycle(self):
        soc, power = ["93"], ["22806824"]
        r = _reader(soc, power)
        r.read_power()
        power[0] = "4999"
        p = r.read_power()
        assert p.battery_power == pytest.approx(4999.0)
        assert p.battery_power_unavailable is False


class TestBothReadPathsShareTheGate:
    def test_energy_dashboard_and_legacy_paths_call_one_helper(self):
        """Two read paths, one rule — the #901 lesson. If either path assigns
        ``readings.battery_soc`` straight from a read again, the gate is
        bypassed on that path."""
        import inspect
        from custom_components.solar_energy_management.coordinator import sensor_reader
        src = inspect.getsource(sensor_reader.SensorReader)
        assert src.count("self._accept_battery_soc(readings, soc_val)") == 2, (
            "expected exactly two call sites (Energy-Dashboard path + legacy path)"
        )
