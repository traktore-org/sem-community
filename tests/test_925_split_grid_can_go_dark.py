"""(#925 audit) A split-grid meter must be able to report itself dark.

`grid_power_unavailable` gates every protection SEM built against a blind
meter: #906's peak-slot allowance, `grid_import_known` in the charger view,
the #925 surplus-controller clamp. It was computed as `_all_dark("grid")`.

A combined meter tags its reads "grid". A SPLIT pair — Growatt, Anker,
Senec, DSMR, and every manual import+export pair including the one #915
added — tags them "grid_import"/"grid_export" and never "grid" at all.
So the question was asked of a category those installs never write, found
zero reads, and answered False. Not "the meter is fine": structurally
always False, every cycle, for that whole hardware class.

The flag also decides whether HA sees `unavailable` or a number, so the
same gap booked a fabricated 0 W into long-term statistics.
"""

from __future__ import annotations

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    _DEGRADABLE_POWER_INPUTS,
    SensorReader,
)


def _reader(dark: dict, reads: dict) -> SensorReader:
    """A reader with the tallies PRE-FILLED — tests the arithmetic only."""
    r = SensorReader.__new__(SensorReader)
    r._input_dark = dict(dark)
    r._input_reads = dict(reads)
    return r


def _live_reader() -> SensorReader:
    """A reader whose tallies are filled by ``_read_sensor`` ITSELF — the
    product path. The first version of this file used only ``_reader``
    above, hand-filling the dicts, and so proved that summing two counters
    works while the counters were never written for the split names: the
    gate in ``_read_sensor`` records only names in ``_DEGRADABLE_POWER_INPUTS``,
    and ``grid_import``/``grid_export`` were not in it. A ruflo reviewer
    caught that the fix could not fire on the hardware it named, and that
    this test could not tell. Same fixture shape as test_818."""
    from unittest.mock import MagicMock
    hass = MagicMock()
    hass.states = MagicMock()
    return SensorReader(hass, {})


class TestTheSplitHalvesAreRecordedAtAll:
    """The half of the fix the first version skipped."""

    def test_the_split_names_are_degradable_inputs(self):
        assert {"grid_import", "grid_export"} <= _DEGRADABLE_POWER_INPUTS, (
            "the split halves are not in _DEGRADABLE_POWER_INPUTS, so "
            "_read_sensor never tallies them and _all_dark_any sums zero")

    def test_an_unavailable_import_half_is_tallied_dark(self):
        r = _live_reader()
        r.hass.states.get = lambda eid: None
        r._read_sensor("sensor.grid_import", "grid_import")
        assert r._input_dark.get("grid_import"), (
            "a dark split-grid read left no trace — the gate dropped it")

    def test_a_live_export_half_is_tallied_read(self):
        r = _live_reader()
        st = MagicMock_state("250")
        r.hass.states.get = lambda eid: st
        r._read_sensor("sensor.grid_export", "grid_export")
        assert r._input_reads.get("grid_export")

    def test_both_halves_dark_through_the_real_path_reads_dark(self):
        """End to end: two dark reads → the flag every blind-meter
        protection gates on says so. This is what could not happen."""
        r = _live_reader()
        r.hass.states.get = lambda eid: None
        r._read_sensor("sensor.grid_import", "grid_import")
        r._read_sensor("sensor.grid_export", "grid_export")
        assert r._all_dark_any("grid", "grid_import", "grid_export") is True

    def test_one_half_alive_through_the_real_path_is_not_dark(self):
        r = _live_reader()
        st = MagicMock_state("1200")
        r.hass.states.get = lambda eid: (st if "import" in eid else None)
        r._read_sensor("sensor.grid_import", "grid_import")
        r._read_sensor("sensor.grid_export", "grid_export")
        assert r._all_dark_any("grid", "grid_import", "grid_export") is False


def MagicMock_state(value: str):
    from unittest.mock import MagicMock
    st = MagicMock()
    st.state = value
    st.attributes = {}
    return st


class TestACombinedMeterStillBehaves:

    def test_all_dark_combined(self):
        r = _reader({"grid": 1}, {"grid": 0})
        assert r._all_dark_any("grid", "grid_import", "grid_export") is True

    def test_a_live_combined_meter_is_not_dark(self):
        r = _reader({"grid": 0}, {"grid": 1})
        assert r._all_dark_any("grid", "grid_import", "grid_export") is False


class TestASplitPairCanNowSayItIsDark:

    def test_both_halves_dark_reads_as_dark(self):
        """The reported case: both grid sensors unavailable for a cycle.
        Before this, the answer was False and SEM integrated a 0 W import
        as though it had measured it."""
        r = _reader({"grid_import": 1, "grid_export": 1},
                    {"grid_import": 0, "grid_export": 0})
        assert r._all_dark_any("grid", "grid_import", "grid_export") is True

    def test_one_half_alive_is_not_dark(self):
        """Export dark while import reports is a partial reading, not an
        absent one — the same rule `_all_dark` has always applied to three
        inverters with one offline."""
        r = _reader({"grid_import": 0, "grid_export": 1},
                    {"grid_import": 1, "grid_export": 0})
        assert r._all_dark_any("grid", "grid_import", "grid_export") is False

    def test_an_import_only_install_can_go_dark(self):
        """Some installs configure only the import half."""
        r = _reader({"grid_import": 1}, {"grid_import": 0})
        assert r._all_dark_any("grid", "grid_import", "grid_export") is True

    def test_nothing_configured_is_not_dark(self):
        """No grid sensor at all is a solar-only install, not a fault —
        `bool(dark)` keeps that answering False."""
        r = _reader({}, {})
        assert r._all_dark_any("grid", "grid_import", "grid_export") is False

    def test_the_old_single_category_question_was_the_bug(self):
        """Pin the defect itself: asked of "grid" alone, a fully dark split
        pair answers False. This is what made the fix necessary and what a
        regression would restore."""
        r = _reader({"grid_import": 1, "grid_export": 1},
                    {"grid_import": 0, "grid_export": 0})
        assert r._all_dark("grid") is False
        assert r._all_dark_any("grid", "grid_import", "grid_export") is True
