"""#910 — a one-report charger power blink is a dark read, not a measurement.

PROD 03.09 (two samples, both while ``binary_sensor.keba_p30_charging_state``
stayed ``on`` and the commanded current was unchanged):

    17:39:56  12 A  ->  sensor.keba_p30_charging_power 0.13 kW for ~10 s
    18:01:52  10 A  ->  0.13 kW for ~10 s          (diagram showed EV 120 W)

The 2026-07-10 median-of-3 absorbs a ONE-read blip; these spanned two SEM
reads, so the median let the low through (PROD monitor 18:02 local:
``ev=130W keba=5.05kW``) and the energy balance grew a phantom 5 kW house
spike for one cycle. The reader now holds the last accepted value while the
charger's own status says charging — at most two cycles, because the median
lags one cycle behind a two-read blink — and a real stop (status off) is never
masked. No status sensor → no hold: the median alone, exactly as before.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.consts.core import (
    EV_POWER_BLINK_HOLD_CYCLES,
)
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
)

DRAW_10A = 5050.0      # KEBA 3-phase, 10 A — the 18:01 sample
DRAW_12A = 8280.0      # 12 A — the 17:39 sample
BLINK = 130.0          # what the box reported for one report cycle


def _reader():
    hass = MagicMock()
    hass.states = MagicMock()
    return SensorReader(hass, {})


def _run(r, seq, charging, key="keba"):
    out = []
    for v in seq:
        rd = PowerReadings()
        out.append((r._smooth_ev_power(v, key=key, charging=charging,
                                       readings=rd), rd.ev_power_held))
    return out


@pytest.mark.unit
class TestTheBlinkIsHeld:
    def test_the_two_prod_samples_never_reach_ev_power(self):
        """The blink spans two reads; the median alone let the second
        through. With the status saying charging both are held."""
        for draw in (DRAW_10A, DRAW_12A):
            r = _reader()
            seq = [draw] * 3 + [BLINK, BLINK] + [draw] * 3
            out = _run(r, seq, charging=True)
            values = [v for v, _ in out]
            assert all(v == draw for v in values), values
            # and the two held cycles are marked, nothing else is
            held = [h for _, h in out]
            assert held == [False, False, False, False, True, True, False, False], held

    def test_the_held_value_is_the_last_accepted_read(self):
        r = _reader()
        seq = [4000.0, 4500.0, 5050.0, BLINK, BLINK, 5050.0]
        out = [v for v, _ in _run(r, seq, charging=True)]
        # median of (4500, 5050, 130) = 4500; median of (5050, 130, 130) =
        # 130 -> held at the accepted 4500, never at a number nobody read
        assert out[3] == 4500.0 and out[4] == 4500.0, out


@pytest.mark.unit
class TestARealStopIsNeverMasked:
    def test_status_off_ends_the_hold_on_the_next_read(self):
        """The hold lives on the status, not the clock: the moment the box
        says it is no longer charging the read passes unheld."""
        r = _reader()
        _run(r, [DRAW_10A] * 3, charging=True)
        out = _run(r, [0.0, 0.0], charging=False)
        # first read: median of (5050, 5050, 0) = 5050 (the median's own
        # one-read tolerance, unchanged since 2026-07-10); second: 0
        assert out[0] == (DRAW_10A, False)
        assert out[1] == (0.0, False)

    def test_a_stale_charging_status_bounds_the_hold(self):
        """Even if the status never flips, the hold is capped so a real
        stop shows within HOLD_CYCLES reads after the median's lag."""
        r = _reader()
        _run(r, [DRAW_10A] * 3, charging=True)
        out = [v for v, _ in _run(r, [0.0] * 6, charging=True)]
        # median passes one, the hold covers HOLD_CYCLES, then the truth
        assert out[0] == DRAW_10A
        assert all(v == DRAW_10A for v in out[1:1 + EV_POWER_BLINK_HOLD_CYCLES])
        assert out[1 + EV_POWER_BLINK_HOLD_CYCLES] == 0.0, out

    def test_the_hold_counter_resets_after_a_good_read(self):
        r = _reader()
        _run(r, [DRAW_10A] * 3, charging=True)
        _run(r, [BLINK, BLINK, DRAW_10A, DRAW_10A], charging=True)
        # a second blink later in the session is held again in full
        out = [v for v, _ in _run(r, [BLINK, BLINK, DRAW_10A], charging=True)]
        assert out == [DRAW_10A, DRAW_10A, DRAW_10A], out


@pytest.mark.unit
class TestWhereTheHoldMustNotEngage:
    def test_no_status_sensor_means_the_median_alone(self):
        """charging=None: nothing is known about the box, so the reader
        behaves exactly as before #910 — the median, no hold."""
        r = _reader()
        seq = [DRAW_10A] * 3 + [BLINK, BLINK, DRAW_10A]
        out = [v for v, _ in _run(r, seq, charging=None)]
        assert out[3] == DRAW_10A       # the median's one-read tolerance
        assert out[4] == BLINK          # and the second low passes, as before

    def test_the_start_ladder_is_not_a_blink(self):
        """A car negotiating at 6 A reads 100-300 W for real; drops from
        such a low accepted value are never held (MIN_W)."""
        r = _reader()
        out = [v for v, _ in _run(r, [250.0, 250.0, 250.0, 0.0, 0.0, 0.0],
                                  charging=True)]
        assert out[-2:] == [0.0, 0.0], out

    def test_a_partial_drop_is_a_measurement(self):
        """10 A -> 6 A is a real ramp-down (60 % of the previous read),
        far above the 5 % blink ratio — it passes."""
        r = _reader()
        _run(r, [DRAW_10A] * 3, charging=True)
        out = [v for v, _ in _run(r, [3030.0, 3030.0, 3030.0], charging=True)]
        assert out[-1] == 3030.0, out


@pytest.mark.unit
class TestItReachesTheFleetRead:
    """The per-charger read path passes the charger's own status sensor
    and marks the readings — the fleet sum and the per-charger map agree."""

    def test_fleet_read_holds_and_marks(self):
        r = _reader()
        states = {}

        def get(entity_id):
            v = states.get(entity_id)
            if v is None:
                return None
            st = MagicMock()
            st.state = str(v)
            st.attributes = {}
            return st

        r.hass.states.get = get
        r._raw_config = {"ev_chargers": [{
            "id": "keba", "ev_charging_power_sensor": "sensor.keba_power",
            "ev_charging_sensor": "binary_sensor.keba_charging",
        }]}
        states["binary_sensor.keba_charging"] = "on"
        chargers = r._raw_config["ev_chargers"]
        for v in (DRAW_10A, DRAW_10A, DRAW_10A, BLINK, BLINK):
            states["sensor.keba_power"] = v
            rd = PowerReadings()
            assert r._read_ev_fleet_power(rd, chargers)
        assert float(rd.ev_power) == DRAW_10A
        assert rd.ev_power_per_charger["keba"] == DRAW_10A
        assert rd.ev_power_held is True
        # the box stops: status off, the very next read is the truth
        states["binary_sensor.keba_charging"] = "off"
        states["sensor.keba_power"] = 0.0
        rd = PowerReadings()
        r._read_ev_fleet_power(rd, chargers)
        assert rd.ev_power_held is False
        rd = PowerReadings()
        r._read_ev_fleet_power(rd, chargers)
        assert float(rd.ev_power) == 0.0
