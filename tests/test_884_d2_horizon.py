"""#884 — "this provider does not publish this horizon", said to everyone.

@ArneGollin1987 on v2.1.0-beta.1:

    In battery tab, open-meteo in two days it says "no source — this provider
    does not publish this horizon - nothing to learn from". Open meteo
    provides up to 7 days forecast. I also tested with forecast.solar and
    solcast, the system always says the same "no source...".

He is right, and a verdict that fires for every provider is not a verdict.
Checked against a rig with all three integrations installed:

    Open-Meteo   sensor.<device>_energy_production_d2      ENABLED, publishing
    Solcast      sensor.solcast_pv_forecast_forecast_day_3 disabled_by=integration
    Forecast.Solar  — none, stops at tomorrow

So ONE sentence covered three different states — unread, disabled by the
integration, genuinely unpublished — and asserted the worst for all of them.
Same family as #867 (an unread value shown as unsupported) and #872 (one
message covering two faults and naming the wrong one).

Note the off-by-one that makes Solcast easy to get wrong: it counts
``day_1`` as TODAY, so ``forecast_day_3`` is SEM's **d2**.
"""
from __future__ import annotations

from custom_components.solar_energy_management.coordinator.forecast_reader import (
    FORECAST_SOLAR_UNIQUE_SUFFIXES,
    OPEN_METEO_UNIQUE_SUFFIXES,
    SOLCAST_UNIQUE_IDS,
)
from custom_components.solar_energy_management.coordinator.forecast_ledger import (
    ForecastLedger,
)


class TestTheReaderAsksForDayTwo:
    def test_open_meteo_maps_the_d2_entity_it_publishes(self):
        """The pure miss: enabled, publishing, never read."""
        assert OPEN_METEO_UNIQUE_SUFFIXES.get("forecast_d2") == \
            "_energy_production_d2"

    def test_solcast_maps_day_3_because_it_counts_today_as_day_1(self):
        ids = SOLCAST_UNIQUE_IDS.get("forecast_d2") or ()
        assert any("day_3" in i for i in ids), (
            "Solcast's day_1 is TODAY, so its day_3 is our d2 — mapping "
            f"day_2 would silently read TOMORROW instead. got {ids}"
        )

    def test_forecast_solar_declares_no_d2_because_it_has_none(self):
        """It genuinely stops at tomorrow, so 'unsupported' is the TRUE
        answer there and must stay available to be said."""
        assert "forecast_d2" not in FORECAST_SOLAR_UNIQUE_SUFFIXES


class TestAnEmptyLedgerIsLearningNotUnsupported:
    """`has_horizon` answered False for two unrelated reasons, and the card
    rendered the harsher one. A fresh install has no records at ANY horizon —
    concluding "your provider cannot supply this" from that is the bug."""

    def test_a_fresh_ledger_does_not_claim_the_source_lacks_the_horizon(self):
        led = ForecastLedger()
        assert led.horizon_state(2) == "learning", (
            "a brand-new install was told its provider does not publish d2"
        )

    def test_records_that_never_carry_the_horizon_are_unsupported(self):
        led = ForecastLedger()
        for day in ("2026-08-20", "2026-08-21", "2026-08-22"):
            led.record(day, 0, 10.0)
            led.record(day, 1, 11.0)
        assert led.horizon_state(2) == "unsupported", (
            "days recorded, none ever at d2 — that IS the source lacking it"
        )

    def test_a_recorded_horizon_is_present(self):
        led = ForecastLedger()
        led.record("2026-08-20", 2, 9.0)
        assert led.horizon_state(2) == "present"

    def test_has_horizon_keeps_its_old_meaning_for_existing_callers(self):
        led = ForecastLedger()
        assert led.has_horizon(2) is False
        led.record("2026-08-20", 2, 9.0)
        assert led.has_horizon(2) is True


class TestThePathReachesTheSurface:
    """A `getattr(wrong_name, ..., default)` returns the default forever and
    looks like working code. The first draft of this fix read `forecast`
    where the parameter is `forecast_data`, which would have published
    'unsupported_by_source' on every install — the exact bug, reintroduced
    inside its own fix."""

    def test_the_publisher_reads_the_parameter_that_exists(self):
        import inspect
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        src = inspect.getsource(SEMCoordinator._record_forecast_horizons)
        sig = src.split("\n")[1]
        assert "forecast_data" in sig, sig
        assert 'getattr(\n                forecast_data, "forecast_d2_path"' in src \
            or 'forecast_data, "forecast_d2_path"' in src, (
            "the d2 path is read off a name that is not in scope — it would "
            "silently publish the default on every install"
        )

    def test_all_three_states_are_published(self):
        import inspect
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        src = inspect.getsource(SEMCoordinator._record_forecast_horizons)
        for key in ("forecast_d2_state", "forecast_d2_path", "forecast_d1_state"):
            assert f'"{key}"' in src, f"{key} never reaches the surface"
