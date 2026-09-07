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
    SensorReader,
)


def _reader(dark: dict, reads: dict) -> SensorReader:
    r = SensorReader.__new__(SensorReader)
    r._input_dark = dict(dark)
    r._input_reads = dict(reads)
    return r


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
