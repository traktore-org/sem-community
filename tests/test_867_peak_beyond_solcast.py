"""#867 part 1 — the solar peak row is blank on every non-Solcast install.

``forecast_reader`` maps the peak to Solcast entities only:

    "peak_power_today": "sensor.solcast_pv_forecast_peak_forecast_today",
    "peak_time_today":  "sensor.solcast_pv_forecast_peak_time_today",

and the registry map for Forecast.Solar / Open-Meteo
(``FORECAST_SOLAR_UNIQUE_SUFFIXES``) carries no peak entries at all. So an
install running forecast_solar publishes ``forecast_peak_power_today_w =
0.0`` and ``forecast_peak_time_today = ""``, and the card shows a permanent
blank beside populated neighbours — which reads as broken rather than
unsupported.

Measured on the branch rig (a real forecast_solar install, 30.08.2026):

    sensor.power_highest_peak_time_today      2026-08-30T12:00:00+00
    sensor.power_highest_peak_time_tomorrow   2026-08-31T13:30:00+00
    sensor.power_production_now               0
    (no peak-power sensor, and no hourly series in any attribute)

So the two halves of the row have different answers, and conflating them is
what made the whole row look broken:

* the peak TIME is published and was simply being thrown away — map it;
* the peak POWER is genuinely not published by these integrations, and
  cannot be derived because they expose no series. Publishing 0.0 asserts
  "the peak is zero watts". It must say "this source does not provide it"
  instead, so the card can distinguish unsupported from broken.
"""
from __future__ import annotations

from custom_components.solar_energy_management.coordinator.forecast_reader import (
    FORECAST_SOLAR_UNIQUE_SUFFIXES,
    SOLCAST_UNIQUE_IDS,
)


class TestThePeakTimeIsMappedForEveryKnownSource:
    def test_forecast_solar_publishes_a_peak_time_and_it_is_mapped(self):
        """``power_highest_peak_time_today`` is on every Forecast.Solar
        install; it was the one number in this row we could already have
        shown."""
        assert "peak_time_today" in FORECAST_SOLAR_UNIQUE_SUFFIXES, (
            "Forecast.Solar publishes the peak time and SEM ignored it"
        )
        assert FORECAST_SOLAR_UNIQUE_SUFFIXES["peak_time_today"] == (
            "_power_highest_peak_time_today")

    def test_open_meteo_inherits_the_same_map(self):
        """Open-Meteo mirrors Forecast.Solar's sensor keys deliberately
        (#687), so mapping one maps both."""
        from custom_components.solar_energy_management.coordinator import (
            forecast_reader,
        )
        assert forecast_reader.OPEN_METEO_SOLAR_PLATFORM
        assert "peak_time_today" in FORECAST_SOLAR_UNIQUE_SUFFIXES

    def test_solcast_still_maps_both_halves(self):
        """Solcast publishes a real peak power and must keep it."""
        assert "peak_power_today" in SOLCAST_UNIQUE_IDS
        assert "peak_time_today" in SOLCAST_UNIQUE_IDS


class TestAnUnsupportedPeakSaysSoRatherThanClaimingZero:
    def test_peak_power_is_not_mapped_for_forecast_solar(self):
        """Pinning the fact, so a future reader does not 'fix' it by
        inventing a mapping to an entity that does not exist: Forecast.Solar
        exposes no peak-power sensor and no series to derive one from."""
        assert "peak_power_today" not in FORECAST_SOLAR_UNIQUE_SUFFIXES

    def test_the_telemetry_names_why_the_peak_power_is_absent(self):
        """``0.0`` asserts the peak is zero watts. The path says which of
        'no source', 'source cannot supply it' or 'read it' happened — the
        same shape as the pv_*_path telemetry added for the sibling fields.
        """
        from custom_components.solar_energy_management.coordinator.types import (
            ForecastSensorData,
        )
        # the READER's own data object carries it…
        from custom_components.solar_energy_management.coordinator import (
            forecast_reader as fr,
        )
        reader_data = fr.ForecastData()
        assert hasattr(reader_data, "peak_power_path")
        assert "forecast_peak_power_path" in reader_data.to_dict()
        # …and it must survive the copy into the PUBLISHED object, or the
        # card never sees it (two layers, and only the second is published).
        assert hasattr(ForecastSensorData(), "forecast_peak_power_path")
