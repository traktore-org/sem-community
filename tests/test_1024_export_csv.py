"""#1024 — ``export_session_history`` returns the sessions as rows and as
CSV text, so a user can keep their own log from an automation."""
import csv
import io
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.session_history import (
    CSV_COLUMNS, sessions_csv,
)

ROWS = [
    {"timestamp": "2026-09-30T17:52:00+02:00", "end": "2026-09-30T18:20:00+02:00",
     "charger_id": "Garage, left", "energy_kwh": 2.1, "solar_share_pct": 40.0,
     "cost": 0.38, "currency": "CHF", "duration_min": 28.0, "taper_detected": False},
    {"timestamp": "2026-09-12T18:00:00+02:00", "energy_kwh": 1.0},
]


class TestCsv:
    def test_the_header_names_every_column(self):
        text = sessions_csv(ROWS)
        assert text.splitlines()[0] == (
            "start,end,charger,energy_kwh,solar_share_pct,cost,currency,duration_min,energy_source,co2_kg")
        assert len(CSV_COLUMNS) == 10   # (#1088) co2_kg added last

    def test_a_comma_in_a_name_is_quoted_and_a_missing_value_is_empty(self):
        rows = list(csv.reader(io.StringIO(sessions_csv(ROWS))))
        assert rows[1][2] == "Garage, left"
        assert rows[1][3] == "2.1"
        assert rows[2] == ["2026-09-12T18:00:00+02:00", "", "", "1.0", "", "", "", "", "", ""]

    def test_no_rows_is_a_header_alone(self):
        assert sessions_csv([]).splitlines() == [
            "start,end,charger,energy_kwh,solar_share_pct,cost,currency,duration_min,energy_source,co2_kg"]


def _capture(mock_hass):
    handlers = {}

    def capturing_register(domain, service_name, handler, **kwargs):
        handlers[service_name] = (handler, kwargs)

    mock_hass.services.async_register = MagicMock(side_effect=capturing_register)
    mock_hass.services.has_service = MagicMock(return_value=False)
    return handlers


class TestService:
    @pytest.mark.asyncio
    async def test_rows_and_csv_come_back_filtered(self, mock_hass, mock_coordinator):
        from custom_components.solar_energy_management import _async_register_phase_services
        from homeassistant.core import SupportsResponse

        handlers = _capture(mock_hass)
        await _async_register_phase_services(mock_hass, mock_coordinator)
        handler, kwargs = handlers["export_session_history"]
        assert kwargs.get("supports_response") is SupportsResponse.ONLY

        mock_coordinator._storage = MagicMock()
        mock_coordinator._storage.get_session_history.return_value = list(ROWS)
        entry = MagicMock()
        entry.entry_id = "entry-1"
        entry.runtime_data = mock_coordinator
        mock_hass.config_entries.async_entries.return_value = [entry]

        response = await handler(SimpleNamespace(data={"since": "2026-09-20"}))
        assert [r["energy_kwh"] for r in response["rows"]] == [2.1]
        assert response["csv"].splitlines()[0].startswith("start,end,charger")
        assert len(response["csv"].splitlines()) == 2

    @pytest.mark.asyncio
    async def test_no_entry_answers_empty(self, mock_hass, mock_coordinator):
        from custom_components.solar_energy_management import _async_register_phase_services

        handlers = _capture(mock_hass)
        await _async_register_phase_services(mock_hass, mock_coordinator)
        handler, _ = handlers["export_session_history"]
        mock_hass.config_entries.async_entries.return_value = []
        response = await handler(SimpleNamespace(data={}))
        assert response["rows"] == []
        assert response["csv"].count("\n") == 1


def test_a_text_cell_is_never_a_formula():
    from custom_components.solar_energy_management.session_history import sessions_csv
    text = sessions_csv([{"charger_id": "=HYPERLINK(1)", "energy_kwh": -1.5}])
    line = text.splitlines()[1]
    assert "'=HYPERLINK(1)" in line
    assert ",-1.5" in line or line.endswith("-1.5") or "-1.5," in line
