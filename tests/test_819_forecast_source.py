"""#819 — when several forecast integrations are installed, the user picks.

`ForecastReader.detect_source()` walks a fixed ladder — Solcast, then
Forecast.Solar, then Open-Meteo — and locks onto the first one it finds.
Someone running all three in parallel to compare accuracy (the reporter in
discussion #817) has no way to say which one SEM should read; the only
lever is deactivating the other integrations.

Worse, `docs/SETUP_GUIDE.md` already promised the override:

    | Forecast entity | Auto | ... set it manually if you run several
    | forecast integrations or a custom one. |

That field exists, but it is wired to the *price* forecast, not the solar
one. So the documentation described a setting that was never there.

The ladder stays exactly as it is for everyone who has not chosen — an
install with one forecast integration must not notice this change at all.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.forecast_reader import (
    FORECAST_SOLAR_PLATFORM,
    OPEN_METEO_SOLAR_PLATFORM,
    SOLCAST_PLATFORM,
    ForecastReader,
)


def _reader(preferred=None, *, installed=(), custom=None):
    """A reader whose registry contains exactly ``installed`` platforms."""
    r = ForecastReader(MagicMock(), custom_entities=custom,
                       preferred_source=preferred)
    r._locate_integration = lambda platform, _entities=None: (
        {"today": f"sensor.{platform}_today"} if platform in installed else {}
    )
    return r


ALL_THREE = (SOLCAST_PLATFORM, FORECAST_SOLAR_PLATFORM, OPEN_METEO_SOLAR_PLATFORM)


@pytest.mark.unit
class TestThePreferenceIsHonoured:

    def test_open_meteo_can_be_chosen_over_solcast(self):
        """The reporter's case: all three installed, Open-Meteo wanted."""
        r = _reader("open_meteo", installed=ALL_THREE)
        assert r.detect_source() == "open_meteo"

    def test_forecast_solar_can_be_chosen(self):
        r = _reader("forecast_solar", installed=ALL_THREE)
        assert r.detect_source() == "forecast_solar"

    def test_solcast_can_be_chosen(self):
        r = _reader("solcast", installed=ALL_THREE)
        assert r.detect_source() == "solcast"

    def test_the_choice_is_visible_in_the_telemetry(self):
        """#434 records which branch decided the source; a chosen source must
        not masquerade as an auto-detection."""
        r = _reader("open_meteo", installed=ALL_THREE)
        r.detect_source()
        assert "preferred" in r._last_source_detection_path


@pytest.mark.unit
class TestNobodyElseNotices:

    def test_auto_keeps_the_existing_ladder(self):
        r = _reader("auto", installed=ALL_THREE)
        assert r.detect_source() == "solcast"

    def test_unset_keeps_the_existing_ladder(self):
        r = _reader(None, installed=ALL_THREE)
        assert r.detect_source() == "solcast"

    def test_a_single_integration_install_is_unaffected(self):
        r = _reader(None, installed=(FORECAST_SOLAR_PLATFORM,))
        assert r.detect_source() == "forecast_solar"

    def test_an_unknown_preference_falls_back_to_auto(self):
        """A stale or hand-edited value must never break forecasting."""
        r = _reader("nonesuch", installed=ALL_THREE)
        assert r.detect_source() == "solcast"

    def test_custom_entities_still_win(self):
        """The existing escape hatch outranks a platform preference — it is
        the more specific statement."""
        r = _reader("open_meteo", installed=ALL_THREE,
                    custom={"today": "sensor.my_own"})
        assert r.detect_source() == "custom"


@pytest.mark.unit
class TestAMissingChoiceDoesNotBreakForecasting:

    def test_it_falls_back_to_the_ladder(self):
        """Chosen Solcast, Solcast uninstalled: forecasting must keep working
        rather than going dark on a stale preference."""
        r = _reader("solcast", installed=(FORECAST_SOLAR_PLATFORM,))
        assert r.detect_source() == "forecast_solar"

    def test_the_fallback_says_so(self):
        """Silent substitution is the thing this codebase keeps being bitten
        by — the miss has to be visible in diagnostics."""
        r = _reader("solcast", installed=(FORECAST_SOLAR_PLATFORM,))
        r.detect_source()
        assert "missing" in r._last_source_detection_path

    def test_nothing_installed_still_reports_none(self):
        r = _reader("solcast", installed=())
        assert r.detect_source() is None


@pytest.mark.unit
class TestTheSettingIsActuallyWired:
    """A picker nothing reads is an inert half — the shape #804 Phase A
    shipped as. Pin the whole path: config -> reader, and a GUI the user
    can actually reach (Guido: every setting lives on the dashboard too)."""

    def test_the_coordinator_passes_the_config_value(self):
        import ast
        from pathlib import Path
        src = Path(__file__).resolve().parent.parent / "coordinator" / "coordinator.py"
        tree = ast.parse(src.read_text())
        calls = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", None) == "ForecastReader"
        ]
        assert calls, "premise: the coordinator builds a ForecastReader"
        kwargs = {k.arg for c in calls for k in c.keywords}
        assert "preferred_source" in kwargs, (
            "the coordinator never passes the chosen source — the picker "
            "would be a setting that does nothing"
        )

    def test_the_options_flow_offers_the_field(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "config_flow.py").read_text()
        assert "solar_forecast_source" in src, (
            "no options-flow field for the chosen forecast source"
        )

    def test_the_dashboard_offers_it_too(self):
        from pathlib import Path
        card = (Path(__file__).resolve().parent.parent / "dashboard" / "card"
                / "src" / "cards" / "sem-config-card.js").read_text()
        assert "solar_forecast_source" in card, (
            "Guido's standing rule: every setting is reachable on the SEM "
            "dashboard, not only in the options flow"
        )

    def test_the_guide_names_every_supported_source_and_no_others(self):
        """The root cause of #819 was a doc claim with nothing behind it
        ("or a compatible sensor"). Tie the guide to the code so the claim
        cannot drift again: every source SEM supports must be named, and the
        phantom must not come back."""
        from pathlib import Path

        from custom_components.solar_energy_management.coordinator.forecast_reader import (
            FORECAST_SOURCES,
        )
        doc = (Path(__file__).resolve().parent.parent / "docs"
               / "SETUP_GUIDE.md").read_text()
        human = {"solcast": "Solcast", "forecast_solar": "Forecast.Solar",
                 "open_meteo": "Open-Meteo"}
        for key in FORECAST_SOURCES:
            assert human[key] in doc, (
                f"SEM supports {key} but the setup guide never names it"
            )
        assert "or a\ncompatible sensor" not in doc and "or a compatible sensor" not in doc, (
            "the guide is claiming support for naming an arbitrary forecast "
            "sensor again — there is no such feature"
        )

    def test_the_setup_guide_no_longer_misdescribes_it(self):
        from pathlib import Path
        doc = (Path(__file__).resolve().parent.parent / "docs"
               / "SETUP_GUIDE.md").read_text()
        assert "solar_forecast_source" in doc or "Solar forecast source" in doc, (
            "#819 was filed because the guide promised an override that did "
            "not exist — the guide has to describe the one that now does"
        )


@pytest.mark.unit
class TestTheGuiShowsWhatIsActuallyInstalled:
    """Guido, 21.08: *"if the user has meteo or an other solar forecast option
    installed he can just switch in the gui"*. A dropdown that offers all four
    regardless lets someone pick a source that is not there and then wonder why
    nothing changed — the choice would silently fall back. The picker has to
    say which ones exist on THIS install."""

    def test_it_reports_the_installed_sources(self):
        r = _reader(installed=(SOLCAST_PLATFORM, OPEN_METEO_SOLAR_PLATFORM))
        assert set(r.available_sources()) == {"solcast", "open_meteo"}

    def test_none_installed_reports_nothing(self):
        assert _reader(installed=()).available_sources() == []

    def test_all_three_installed_reports_all_three(self):
        r = _reader(installed=ALL_THREE)
        assert set(r.available_sources()) == {
            "solcast", "forecast_solar", "open_meteo"}

    def test_it_does_not_disturb_the_chosen_source(self):
        """Asking what is available is a read — it must not re-point SEM."""
        r = _reader("open_meteo", installed=ALL_THREE)
        assert r.detect_source() == "open_meteo"
        r.available_sources()
        assert r.source == "open_meteo"

    def test_the_card_reads_it_from_somewhere_it_can_actually_see(self):
        """This nearly shipped inert. The card's ``_val(suffix)`` resolves
        ``sensor.sem_<suffix>.state`` — there is no entity for a list, so it
        returned '' and the picker silently offered every source again. The
        list has to ride an ATTRIBUTE of a real entity, and the test has to
        check HOW it is read, not merely that the name appears somewhere."""
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        card = (root / "dashboard" / "card" / "src" / "cards"
                / "sem-config-card.js").read_text()
        assert "attributes?.sources_available" in card, (
            "the card is not reading the list from an entity attribute"
        )
        assert "_val('forecast_sources_available')" not in card, (
            "_val() reads an entity STATE — for a list it always returns '' "
            "and the guard silently passes"
        )
        sensors = (root / "sensor.py").read_text()
        assert 'attrs["sources_available"]' in sensors, (
            "nothing puts the list on an entity, so the card reads nothing"
        )


@pytest.mark.unit
class TestChangingItDoesNotNeedAReload:
    """#637's guard: a key consumed only at construction must stay on the
    reload path, because live-applying it would be the #462 lie — the
    setting looks applied and nothing moves. Rather than reload the entry
    for a dropdown, the choice is re-applied every cycle and a real change
    drops the cached source."""

    def test_switching_re_detects(self):
        r = _reader("solcast", installed=ALL_THREE)
        assert r.detect_source() == "solcast"

        r.set_preferred_source("open_meteo")
        assert r.detect_source() == "open_meteo"

    def test_switching_back_to_auto_restores_the_ladder(self):
        r = _reader("open_meteo", installed=ALL_THREE)
        assert r.detect_source() == "open_meteo"

        r.set_preferred_source("auto")
        assert r.detect_source() == "solcast"

    def test_re_applying_the_same_value_is_a_no_op(self):
        """The coordinator calls this every cycle; it must not churn the
        cached source or log on a normal cycle."""
        r = _reader("open_meteo", installed=ALL_THREE)
        r.detect_source()
        r.set_preferred_source("open_meteo")
        assert r.source == "open_meteo", "an unchanged value dropped the cache"

    def test_the_key_is_routed_live_not_to_a_reload(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "__init__.py").read_text()
        i = src.index("_SET_OPTION_LIVE_CONFIG_KEYS")
        assert "solar_forecast_source" in src[i:i + 900], (
            "the picker would reload the whole entry on every change"
        )

    def test_the_coordinator_re_applies_it_on_the_cycle_path(self):
        """Live simulation caught this: the call existed, but on a rarely-run
        path, so switching the source on the rig changed the stored option and
        nothing else. Asserting the call merely EXISTS passes while the
        feature does nothing — it has to guard the read that runs each
        cycle."""
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "coordinator"
               / "coordinator.py").read_text()
        i = src.index("self._cycle_forecast = self._forecast_reader.read_forecast()")
        window = src[max(0, i - 600):i]
        assert "set_preferred_source(" in window, (
            "the per-cycle forecast read does not re-apply the chosen source, "
            "so the picker would only take effect on a reload"
        )
