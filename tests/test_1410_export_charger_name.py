"""#1410 — the session export names each charger by the name the user gave it.

The .xlsx download and the export service's CSV wrote the stored charger id
("goecharger_api2_d97c7a8d4f", "ev_charger") in the charger column and the
file name. The name is read from the saved charger list when the file is
made, so a rename shows; the id moves to a last column for scripts.
"""
import base64
import csv
import io
import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.session_history import (
    CSV_COLUMNS, WS_SESSION_HISTORY_XLSX, charger_names, sessions_csv,
    ws_session_history_xlsx,
)

from .test_1083_xlsx import read_workbook

# The reporter's shape: two go-e boxes, renamed. The data side still holds
# the names from setup; the options hold the rename (the live copy).
DATA = {"ev_chargers": [
    {"id": "goecharger_api2_d97c7a8d4f", "name": "Go-echarger Charger"},
    {"id": "ev_charger", "name": "Neues Ladegerät 2"},
]}
OPTIONS = {"ev_chargers": [
    {"id": "goecharger_api2_d97c7a8d4f", "name": "Go-e Charger BMW"},
    {"id": "ev_charger", "name": "Go-e Charger Cupra"},
]}

HISTORY = [
    {"timestamp": "2026-11-20T17:52:00+01:00", "charger_id": "goecharger_api2_d97c7a8d4f",
     "energy_kwh": 12.0},
    {"timestamp": "2026-11-19T17:52:00+01:00", "charger_id": "ev_charger", "energy_kwh": 8.0},
    {"timestamp": "2026-11-18T17:52:00+01:00", "charger_id": "old_box", "energy_kwh": 5.0},
    {"timestamp": "2026-11-17T17:52:00+01:00", "energy_kwh": 1.0},   # before ids
]

CHARGER = [name for name, _ in CSV_COLUMNS].index("charger")
CHARGER_ID = [name for name, _ in CSV_COLUMNS].index("charger_id")


def _hass(data=None, options=None, history=HISTORY, language="en"):
    hass = MagicMock()
    hass.data = {}
    hass.config.language = language
    coordinator = MagicMock()
    coordinator._storage.get_session_history.return_value = list(history)
    entry = SimpleNamespace(entry_id="entry-1", data=data or {}, options=options or {},
                            runtime_data=coordinator)
    hass.config_entries.async_entries.return_value = [entry]
    return hass


def _download(hass, **msg):
    connection = MagicMock()
    ws_session_history_xlsx(hass, connection, {"id": 1, "type": WS_SESSION_HISTORY_XLSX, **msg})
    payload = connection.send_result.call_args.args[1]
    return payload, read_workbook(base64.b64decode(payload["base64"]))["Sessions"]


def _text(cell):
    return cell[1] if cell else None


class TestXlsx:
    def test_the_charger_column_is_the_name_now(self):
        _, rows = _download(_hass(DATA, OPTIONS))
        assert [_text(r[CHARGER]) for r in rows[1:]] == [
            "Go-e Charger BMW", "Go-e Charger Cupra",
            "old_box",          # no longer set up: its id, never blank
            None,               # stored before SEM knew the charger
        ]

    def test_the_id_is_kept_in_the_last_column(self):
        _, rows = _download(_hass(DATA, OPTIONS))
        assert _text(rows[0][CHARGER_ID]) == "charger_id"
        assert CHARGER_ID == len(CSV_COLUMNS) - 1
        assert [_text(r[CHARGER_ID]) if len(r) > CHARGER_ID else None for r in rows[1:]] == [
            "goecharger_api2_d97c7a8d4f", "ev_charger", "old_box", None]

    def test_the_file_name_carries_the_name(self):
        payload, rows = _download(_hass(DATA, OPTIONS), charger_id="goecharger_api2_d97c7a8d4f")
        assert re.fullmatch(r"sem-sessions-go_e_charger_bmw-\d{4}-\d{2}-\d{2}\.xlsx",
                            payload["filename"])
        assert [_text(r[CHARGER]) for r in rows[1:]] == ["Go-e Charger BMW", None]

    def test_a_removed_charger_file_keeps_its_id(self):
        payload, _ = _download(_hass(DATA, OPTIONS), charger_id="old_box")
        assert payload["filename"].startswith("sem-sessions-old_box-")

    def test_two_chargers_with_one_name_keep_their_ids_in_the_file_name(self):
        same = {"ev_chargers": [{"id": "a", "name": "Garage"}, {"id": "b", "name": "garage"}]}
        payload, _ = _download(_hass(options=same), charger_id="b")
        assert payload["filename"].startswith("sem-sessions-b-")

    def test_a_name_with_no_letter_keeps_the_id(self):
        odd = {"ev_chargers": [{"id": "a", "name": "!!!"}]}
        payload, _ = _download(_hass(options=odd), charger_id="a")
        assert payload["filename"].startswith("sem-sessions-a-")

    def test_no_charger_asked_no_charger_in_the_file_name(self):
        payload, _ = _download(_hass(DATA, OPTIONS))
        assert re.fullmatch(r"sem-sessions-\d{4}-\d{2}-\d{2}\.xlsx", payload["filename"])


class TestNames:
    def test_the_options_win_over_the_data(self):
        assert charger_names(_hass(DATA, OPTIONS)) == {
            "goecharger_api2_d97c7a8d4f": "Go-e Charger BMW",
            "ev_charger": "Go-e Charger Cupra",
        }

    def test_data_alone_is_read_when_there_are_no_options(self):
        assert charger_names(_hass(DATA))["ev_charger"] == "Neues Ladegerät 2"

    def test_an_unnamed_charger_gets_the_default_in_the_language(self):
        cfg = {"ev_chargers": [{"id": "a", "name": "Garage"}, {"id": "b", "name": "EV Charger 2"},
                               {"id": "c"}]}
        names = charger_names(_hass(options=cfg, language="de"))
        assert names == {"a": "Garage", "b": "EV-Ladegerät 2", "c": "EV-Ladegerät 3"}

    def test_an_id_less_charger_takes_the_setup_fallback_id(self):
        cfg = {"ev_chargers": [{"id": "a", "name": "A"}, {"name": "Shed"}]}
        assert charger_names(_hass(options=cfg)) == {"a": "A", "ev_charger_1": "Shed"}

    def test_a_doubled_id_keeps_the_first_name(self):
        cfg = {"ev_chargers": [{"id": "a", "name": "First"}, {"id": "a", "name": "Second"}]}
        assert charger_names(_hass(options=cfg)) == {"a": "First"}

    def test_no_list_is_the_legacy_charger(self):
        assert charger_names(_hass()) == {"ev_charger": "EV Charger"}

    def test_no_entry_no_names(self):
        hass = MagicMock()
        hass.config_entries.async_entries.return_value = []
        assert charger_names(hass) == {}

    def test_the_entry_asked_for_is_the_one_read(self):
        hass = _hass(options=OPTIONS)
        other = SimpleNamespace(entry_id="entry-2", data={},
                                options={"ev_chargers": [{"id": "ev_charger", "name": "Other"}]},
                                runtime_data=None)
        hass.config_entries.async_entries.return_value.append(other)
        assert charger_names(hass, "entry-2") == {"ev_charger": "Other"}


def _capture(mock_hass):
    handlers = {}

    def capturing_register(domain, service_name, handler, **kwargs):
        handlers[service_name] = (handler, kwargs)

    mock_hass.services.async_register = MagicMock(side_effect=capturing_register)
    mock_hass.services.has_service = MagicMock(return_value=False)
    return handlers


class TestCsv:
    def test_names_fill_the_charger_column(self):
        names = {"goecharger_api2_d97c7a8d4f": "Go-e Charger BMW", "ev_charger": "=Cupra"}
        rows = list(csv.reader(io.StringIO(sessions_csv(HISTORY, names))))
        assert [r[CHARGER] for r in rows[1:]] == ["Go-e Charger BMW", "'=Cupra", "old_box", ""]
        assert [r[CHARGER_ID] for r in rows[1:]] == [
            "goecharger_api2_d97c7a8d4f", "ev_charger", "old_box", ""]

    @pytest.mark.asyncio
    async def test_the_export_service_writes_names(self, mock_hass, mock_coordinator):
        from custom_components.solar_energy_management import _async_register_phase_services

        handlers = _capture(mock_hass)
        await _async_register_phase_services(mock_hass, mock_coordinator)
        handler, _ = handlers["export_session_history"]
        mock_coordinator._storage = MagicMock()
        mock_coordinator._storage.get_session_history.return_value = list(HISTORY)
        entry = SimpleNamespace(entry_id="entry-1", data=DATA, options=OPTIONS,
                                runtime_data=mock_coordinator)
        mock_hass.config_entries.async_entries.return_value = [entry]

        response = await handler(SimpleNamespace(data={}))
        rows = list(csv.reader(io.StringIO(response["csv"])))
        assert [r[CHARGER] for r in rows[1:3]] == ["Go-e Charger BMW", "Go-e Charger Cupra"]
        # the rows for scripts keep the stored id, unchanged
        assert response["rows"][0]["charger_id"] == "goecharger_api2_d97c7a8d4f"
        assert "charger_name" not in response["rows"][0]
