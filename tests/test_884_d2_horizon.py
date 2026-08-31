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
        # the unique_id is total_kwh_forecast_d3 — "d3", not "day_3", which
        # only the registry could tell us
        assert any("d3" in i for i in ids), (
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


class TestTheStateSurvivesTheAllowlist:
    """`_record_forecast_horizons` publishing a key is not enough: the
    battery sensor copies attributes through an EXPLICIT per-key allowlist,
    so a new field is computed and silently dropped unless it is added there
    too. That is precisely how #867's `*_path` telemetry was built and never
    reached anyone — and it happened again here, caught on the rig with
    `forecast_d2_state = None` while `forecast_d2_available` published fine.
    """

    def test_the_new_keys_survive_the_coordinator_copy(self):
        """The FIRST allowlist. Between the ledger dict and the sensor sits
        `result[...] = _pe.get(...)`, key by key. Both had to be edited, and
        finding that took two deploys — the field read None on the rig with
        no error anywhere."""
        import inspect
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        src = inspect.getsource(SEMCoordinator._async_update_data)
        for key in ("forecast_d1_state", "forecast_d2_state", "forecast_d2_path"):
            assert f'result["{key}"] = _pe.get("{key}")' in src, (
                f"{key} never leaves the planning-evidence dict"
            )

    def test_the_new_keys_are_in_the_attribute_allowlist(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parents[1] / "sensor.py").read_text()
        for key in ("forecast_d1_state", "forecast_d2_state", "forecast_d2_path"):
            assert f'"{key}": d.get("{key}")' in src, (
                f"{key} is computed but never copied to the sensor's "
                "attributes — the #867 inert-half pattern"
            )


class TestTheDisabledProbeActuallyRuns:
    """It read `self._hass`; the reader stores `self.hass`. The blanket
    `except Exception: return False` turned that AttributeError into a
    confident "not disabled", so Solcast's disabled day-3 sensor was reported
    as *unsupported* — the exact conflation the probe exists to prevent, and
    invisible because the error never surfaced.

    Second time today the same shape bit: an exception swallowed into a
    silence that reads as data.
    """

    def test_the_probe_uses_the_attribute_the_reader_has(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import (
            forecast_reader as fr,
        )
        src = inspect.getsource(fr.ForecastReader._d2_entity_disabled)
        # match the CALL, not prose — the fix's own comment names the wrong
        # attribute on purpose, to record what went wrong
        assert "er.async_get(self._hass)" not in src, (
            "reads self._hass, which does not exist — silently False forever"
        )
        assert "er.async_get(self.hass)" in src

    def test_a_disabled_solcast_day3_is_seen(self):
        from unittest.mock import MagicMock, patch
        from custom_components.solar_energy_management.coordinator import (
            forecast_reader as fr,
        )
        r = fr.ForecastReader.__new__(fr.ForecastReader)
        r.hass = MagicMock()
        entry = MagicMock()
        entry.disabled_by = "integration"
        entry.unique_id = "total_kwh_forecast_d3"
        entry.entity_id = "sensor.solcast_pv_forecast_forecast_day_3"
        reg = MagicMock()
        reg.entities.values.return_value = [entry]
        with patch("homeassistant.helpers.entity_registry.async_get",
                   return_value=reg):
            assert r._d2_entity_disabled() is True

    def test_an_enabled_entity_is_not_reported_disabled(self):
        from unittest.mock import MagicMock, patch
        from custom_components.solar_energy_management.coordinator import (
            forecast_reader as fr,
        )
        r = fr.ForecastReader.__new__(fr.ForecastReader)
        r.hass = MagicMock()
        entry = MagicMock()
        entry.disabled_by = None
        entry.unique_id = "total_kwh_forecast_d3"
        entry.entity_id = "sensor.solcast_pv_forecast_forecast_day_3"
        reg = MagicMock()
        reg.entities.values.return_value = [entry]
        with patch("homeassistant.helpers.entity_registry.async_get",
                   return_value=reg):
            assert r._d2_entity_disabled() is False
