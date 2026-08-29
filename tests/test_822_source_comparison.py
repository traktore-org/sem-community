"""#822 — score every installed forecast source against reality.

Guido, 21.08: *"maybe we can also integrate these in sem if the integration
are installed in ha"*. People install two or three forecast integrations for
one reason — to find out which is right for their roof — and SEM picked one
and ignored the rest.

**The obvious feature is the wrong one.** Putting their numbers side by side
looks like the answer and is not. Measured on the dev rig, one day, one roof:

    Solcast          125.62 kWh
    Forecast.Solar    47.25 kWh
    Open-Meteo        19.95 kWh      <- the source SEM had chosen

A 6x spread that is NOT three opinions about a roof. Checking their config
entries showed three DIFFERENT CONFIGURED ARRAYS — Open-Meteo at 8 kWp,
Forecast.Solar against a 15 kW inverter, Solcast a cloud site whose size is
not local at all. SEM cannot see how a third-party integration was set up, so
it cannot normalise them, and a "comparison" that ignores this would confidently
declare a correctly-working integration wrong.

What SEM *can* do is score each against what the roof actually produced. That
is precisely what #778's ledger already does for the active source, so #822 is
one ledger per source and the same trust maths — no new statistics, and the
verdict is measured rather than assumed. A source configured for the wrong
array scores badly and says so.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.forecast_ledger import (
    ForecastLedger,
)


class TestOneLedgerPerSourceScoresThemHonestly:
    """The heart of it: two sources, one roof, one truth."""

    def _ledger(self, forecasts, actuals):
        led = ForecastLedger()
        for day, kwh in forecasts.items():
            led.record(day, 1, kwh)
        for day, kwh in actuals.items():
            led.settle(day, kwh)
        return led

    def test_the_source_that_matches_reality_scores_higher(self):
        days = [f"2026-06-{d:02d}" for d in range(1, 15)]
        actual = dict.fromkeys(days, 20.0)
        good = self._ledger(dict.fromkeys(days, 20.0), actual)
        bad = self._ledger(dict.fromkeys(days, 60.0), actual)   # 3x oversized array

        assert good.trust(1) is not None and bad.trust(1) is not None
        assert good.trust(1) > bad.trust(1), (
            f"good={good.trust(1)} bad={bad.trust(1)} — a source forecasting "
            "three times the roof must not score as well as one that is right"
        )

    def test_an_oversized_source_is_visibly_untrustworthy(self):
        """The misconfigured-array case, which is what the 6x spread was."""
        days = [f"2026-06-{d:02d}" for d in range(1, 15)]
        bad = self._ledger(dict.fromkeys(days, 60.0), dict.fromkeys(days, 20.0))
        assert bad.trust(1) < 0.5, bad.trust(1)

    def test_thin_evidence_refuses_to_score(self):
        """A refusal must reach the user rather than be rendered as a
        confident number — the same rule the active ledger follows."""
        led = self._ledger({"2026-06-01": 20.0}, {"2026-06-01": 20.0})
        assert led.trust(1) is None


class TestPeekIsReadOnly:
    """Comparing a source must never change which one is in use."""

    def _reader(self):
        from custom_components.solar_energy_management.coordinator import (
            forecast_reader as fr,
        )
        hass = MagicMock()
        hass.states.async_all.return_value = []
        hass.states.get.return_value = None
        r = fr.ForecastReader(hass, custom_entities=None,
                              preferred_source="forecast_solar")
        return r, fr

    def test_peek_does_not_repoint_the_reader(self):
        r, _ = self._reader()
        r._source = "solcast"
        r._entities = {"forecast_today": "sensor.kept"}
        r.peek_sources()
        assert r._source == "solcast"
        assert r._entities == {"forecast_today": "sensor.kept"}

    def test_peek_with_nothing_installed_is_empty_not_an_error(self):
        r, _ = self._reader()
        assert r.peek_sources() == {}


class TestASourceIsComparedAsAWholeRoof:
    """#838 and #822 meet here: a multi-plane source must be compared by its
    TOTAL, or the comparison penalises it for the planes SEM dropped."""

    def test_planes_are_summed_before_comparison(self):
        from custom_components.solar_energy_management.coordinator import (
            forecast_reader as fr,
        )
        registry = [
            SimpleNamespace(platform=fr.FORECAST_SOLAR_PLATFORM, disabled_by=None,
                            unique_id=f"{p}_energy_production_today",
                            entity_id=f"sensor.{p}_today")
            for p in ("east", "west")
        ]
        states = {"sensor.east_today": SimpleNamespace(state="6.0", attributes={}),
                  "sensor.west_today": SimpleNamespace(state="4.0", attributes={})}
        hass = MagicMock()
        hass.states.get = lambda eid: states.get(eid)
        hass.states.async_all.return_value = []
        r = fr.ForecastReader(hass, custom_entities=None, preferred_source=None)

        import homeassistant.helpers.entity_registry as er
        real = er.async_get
        er.async_get = lambda _h: SimpleNamespace(
            entities=SimpleNamespace(values=lambda: registry))
        try:
            seen = r.peek_sources()
        finally:
            er.async_get = real

        assert "forecast_solar" in seen, seen
        assert seen["forecast_solar"]["today_kwh"] == pytest.approx(10.0), seen
        assert seen["forecast_solar"]["planes"] == 2
