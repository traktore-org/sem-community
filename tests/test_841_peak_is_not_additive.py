"""#841 — a peak is not additive across PV planes.

Follow-up to #838, which taught SEM to sum a multi-string roof's forecast
instead of reading one string and calling it the roof. That was right for
energies and right for instantaneous power. It was applied to ONE role where
it is wrong:

    data.peak_power_today_w = self._read_role_power_w("peak_power_today", 0.0)

``_read_role_power_w`` sums across planes. Peaks do not add. An east-facing
array and a west-facing array reach their maxima hours apart, so their peaks
are never simultaneous — adding them claims an instantaneous output the roof
cannot physically produce. An 8 kWp east + 8 kWp west install would report a
16 kW peak against a true system peak nearer 9-10 kW.

The direction is the opposite of #838's, and that is what makes it worth its
own fix rather than a footnote: #838 corrected an UNDER-statement, and this
correction prevents an OVER-statement. Over-stating the peak is the more
dangerous of the two — anything sizing headroom, a peak-shaving threshold or
an export limit against it plans for a spike that never comes.

The largest single plane is used instead. It under-states a co-planar split
(two arrays at the same azimuth really do peak together), but it is a number
the system can actually reach, and of the two ways to be wrong that is the one
that cannot cause SEM to plan for phantom power.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.forecast_reader import (
    ForecastReader,
)


def _reader(peaks: dict):
    states = {
        eid: SimpleNamespace(state=str(v), attributes={"unit_of_measurement": "W"})
        for eid, v in peaks.items()
    }
    hass = MagicMock()
    hass.states.get = lambda eid: states.get(eid)
    hass.states.async_all.return_value = []
    r = ForecastReader(hass, custom_entities=None, preferred_source=None)
    r._source = "forecast_solar"
    r._entities = {"peak_power_today": next(iter(peaks))}
    r._entity_groups = {"peak_power_today": list(peaks)}
    return r


class TestPeakTakesTheLargestPlane:
    def test_two_planes_do_not_add_their_peaks(self):
        r = _reader({"sensor.east_peak": 8000.0, "sensor.west_peak": 7500.0})
        peak = r._read_role_peak_w("peak_power_today", 0.0)
        assert peak == pytest.approx(8000.0), (
            f"got {peak} — summing plane peaks claims an output the roof "
            "never produces, because east and west peak hours apart (#841)"
        )

    def test_a_single_plane_is_unchanged(self):
        r = _reader({"sensor.only_peak": 6200.0})
        assert r._read_role_peak_w("peak_power_today", 0.0) == pytest.approx(6200.0)

    def test_an_unavailable_plane_is_skipped_not_zeroing(self):
        r = _reader({"sensor.east_peak": 8000.0, "sensor.west_peak": "unavailable"})
        assert r._read_role_peak_w("peak_power_today", 0.0) == pytest.approx(8000.0)

    def test_all_unavailable_returns_the_default(self):
        r = _reader({"sensor.east_peak": "unavailable"})
        assert r._read_role_peak_w("peak_power_today", -1.0) == pytest.approx(-1.0)


class TestTheAdditiveRolesStillAdd:
    """#838's summing was right for these and must stay."""

    @pytest.mark.parametrize("role", ["power_now", "power_next_hour"])
    def test_instantaneous_power_is_additive(self, role):
        states = {
            "sensor.a": SimpleNamespace(state="3000", attributes={"unit_of_measurement": "W"}),
            "sensor.b": SimpleNamespace(state="2000", attributes={"unit_of_measurement": "W"}),
        }
        hass = MagicMock()
        hass.states.get = lambda eid: states.get(eid)
        hass.states.async_all.return_value = []
        r = ForecastReader(hass, custom_entities=None, preferred_source=None)
        r._entities = {role: "sensor.a"}
        r._entity_groups = {role: ["sensor.a", "sensor.b"]}
        assert r._read_role_power_w(role, 0.0) == pytest.approx(5000.0), (
            "two arrays produce the sum of their watts AT THE SAME MOMENT — "
            "that one is genuinely additive and #838 got it right"
        )


class TestTheReadPathUsesIt:
    def test_peak_does_not_go_through_the_summing_reader(self):
        """Guard the wiring, not just the helper — the bug was which function
        the read path called, and a correct helper nobody calls fixes
        nothing."""
        import inspect
        src = inspect.getsource(ForecastReader.read_forecast)
        assert "_read_role_peak_w(\"peak_power_today\"" in src, (
            "peak_power_today is still routed through the summing reader"
        )
