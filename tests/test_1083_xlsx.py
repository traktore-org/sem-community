"""#1083 — session download as .xlsx: typed cells, no delimiter to guess.

A CSV opens split on ";" or "," by the reader's locale. The .xlsx writer
is standard library only; these tests read it back with zipfile + etree.
"""
import base64
import datetime as dt
import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock
from xml.etree import ElementTree as ET

from custom_components.solar_energy_management.session_history import (
    CSV_COLUMNS, WS_SESSION_HISTORY_XLSX, async_register_websocket,
    ws_session_history_xlsx,
)
from custom_components.solar_energy_management.utils.xlsx import (
    sheet_name, write_workbook,
)

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
PARTS = ("[Content_Types].xml", "_rels/.rels", "xl/workbook.xml",
         "xl/_rels/workbook.xml.rels", "xl/styles.xml")


def _col_index(ref):
    letters = "".join(ch for ch in ref if ch.isalpha())
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_workbook(data):
    """{sheet name: rows}; a cell is (type, value, style)."""
    z = zipfile.ZipFile(io.BytesIO(data))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    names = [s.get("name") for s in wb.find("m:sheets", NS)]
    styles = ET.fromstring(z.read("xl/styles.xml"))
    fmts = {int(f.get("numFmtId")): f.get("formatCode")
            for f in styles.find("m:numFmts", NS)}
    xfs = [int(x.get("numFmtId")) for x in styles.find("m:cellXfs", NS)]
    out = {}
    for i, name in enumerate(names, start=1):
        root = ET.fromstring(z.read(f"xl/worksheets/sheet{i}.xml"))
        rows = []
        for row in root.find("m:sheetData", NS):
            cells = {}
            for c in row:
                t = c.get("t", "n")
                fmt = fmts.get(xfs[int(c.get("s", "0"))])
                if t == "inlineStr":
                    cells[_col_index(c.get("r"))] = ("s", c.find("m:is/m:t", NS).text, fmt)
                else:
                    v = c.find("m:v", NS).text
                    val = bool(int(v)) if t == "b" else float(v)
                    cells[_col_index(c.get("r"))] = (t, val, fmt)
            width = max(cells) + 1 if cells else 0
            rows.append([cells.get(k) for k in range(width)])
        out[name] = rows
    return out


class TestWriter:
    def test_opens_and_every_part_parses(self):
        data = write_workbook([("A", [["x"], [1]]), ("B", [["y"]])])
        z = zipfile.ZipFile(io.BytesIO(data))
        assert z.testzip() is None
        names = z.namelist()
        for part in PARTS + ("xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml"):
            assert part in names
        for part in names:
            ET.fromstring(z.read(part))

    def test_cells_keep_their_type(self):
        when = dt.datetime(2026, 9, 30, 18, 0)
        rows = [["n", "f", "b", "d", "dt", "none", "s"],
                [3, 2.5, True, dt.date(2026, 9, 30), when, None, "keba"]]
        got = read_workbook(write_workbook([("S", rows)]))["S"]
        assert [c[1] for c in got[0]] == rows[0]
        n, f, b, d, ts, none, s = got[1]
        assert n == ("n", 3.0, None)
        assert f == ("n", 2.5, None)
        assert b == ("b", True, None)
        # 2026-09-30 is Excel day 46295; 18:00 is three quarters of a day.
        assert d == ("n", 46295.0, "yyyy-mm-dd")
        assert ts == ("n", 46295.75, "yyyy-mm-dd hh:mm")
        assert none is None
        assert s == ("s", "keba", None)

    def test_a_formula_stays_text(self):
        got = read_workbook(write_workbook([("S", [["=SUM(A1)", "+1", "@x"]])]))["S"]
        assert got[0] == [("s", "=SUM(A1)", None), ("s", "+1", None), ("s", "@x", None)]
        sheet = zipfile.ZipFile(io.BytesIO(write_workbook([("S", [["=SUM(A1)"]])]))) \
            .read("xl/worksheets/sheet1.xml").decode()
        assert "<f>" not in sheet

    def test_xml_chars_and_control_chars(self):
        got = read_workbook(write_workbook([("S", [["a<b>&\"c\x01\x1f"]])]))["S"]
        assert got[0][0][1] == 'a<b>&"c'

    def test_sheet_names_are_sanitised(self):
        assert sheet_name("2026/09") == "2026_09"
        assert sheet_name("a[b]:c*d?e\\f") == "a_b__c_d_e_f"
        assert len(sheet_name("x" * 40)) == 31
        assert sheet_name("") == "Sheet"
        data = write_workbook([("2026/09", [["x"]]), ("2026/09", [["y"]])])
        assert list(read_workbook(data)) == ["2026_09", "2026_09 (2)"]

    def test_same_input_same_bytes(self):
        rows = [["a", 1], [dt.datetime(2026, 1, 1), None]]
        assert write_workbook([("S", rows)]) == write_workbook([("S", rows)])

    def test_columns_past_z(self):
        got = read_workbook(write_workbook([("S", [list(range(28))])]))["S"]
        assert got[0][27] == ("n", 27.0, None)


def _hass(history):
    hass = MagicMock()
    hass.data = {}
    coordinator = MagicMock()
    coordinator._storage.get_session_history.return_value = list(history)
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.runtime_data = coordinator
    hass.config_entries.async_entries.return_value = [entry]
    return hass


HISTORY = [
    {"timestamp": "2026-09-30T17:52:00+02:00", "end": "2026-09-30T18:20:00+02:00",
     "charger_id": "keba", "energy_kwh": 2.1, "solar_share_pct": 88, "cost": 0.31,
     "currency": "CHF", "duration_min": 28, "energy_source": "meter"},
    {"timestamp": "2026-09-05T18:00:00+02:00", "charger_id": "wall2", "energy_kwh": 7.0},
    {"timestamp": "2026-09-02T18:00:00+02:00", "charger_id": "=HYPERLINK(1)", "energy_kwh": 2.0},
]


class TestCommand:
    def test_the_command_name(self):
        assert WS_SESSION_HISTORY_XLSX == "solar_energy_management/session_history/xlsx"

    def test_base64_decodes_to_the_session_columns(self):
        connection = MagicMock()
        ws_session_history_xlsx(_hass(HISTORY), connection,
                                {"id": 4, "type": WS_SESSION_HISTORY_XLSX})
        msg_id, payload = connection.send_result.call_args.args
        assert msg_id == 4
        assert payload["filename"].startswith("sem-sessions-")
        assert payload["filename"].endswith(".xlsx")
        assert len(payload["filename"]) == len("sem-sessions-YYYY-MM-DD.xlsx")
        sheets = read_workbook(base64.b64decode(payload["base64"]))
        rows = sheets["Sessions"]
        assert [c[1] for c in rows[0]] == [name for name, _ in CSV_COLUMNS]
        assert len(rows) == 1 + len(HISTORY)
        first = rows[1]
        assert first[0] == ("n", first[0][1], "yyyy-mm-dd hh:mm")   # start = a date
        # 2026-09-30 17:52 wall clock, as stored.
        assert abs(first[0][1] - (46295 + (17 * 60 + 52) / 1440)) < 1e-6
        assert first[3] == ("n", 2.1, None)
        assert first[4] == ("n", 88.0, None)
        assert first[6] == ("s", "CHF", None)
        assert rows[3][2] == ("s", "=HYPERLINK(1)", None)

    def test_charger_filter(self):
        connection = MagicMock()
        ws_session_history_xlsx(_hass(HISTORY), connection,
                                {"id": 1, "type": WS_SESSION_HISTORY_XLSX,
                                 "charger_id": "wall2"})
        rows = read_workbook(base64.b64decode(
            connection.send_result.call_args.args[1]["base64"]))["Sessions"]
        assert [r[2][1] for r in rows[1:]] == ["wall2"]

    def test_no_sem_entry_is_an_error(self):
        hass = MagicMock()
        hass.config_entries.async_entries.return_value = []
        connection = MagicMock()
        ws_session_history_xlsx(hass, connection, {"id": 1, "type": WS_SESSION_HISTORY_XLSX})
        connection.send_error.assert_called_once()
        connection.send_result.assert_not_called()

    def test_registered_beside_the_list_command(self):
        hass = MagicMock()
        hass.data = {}
        async_register_websocket(hass)
        assert WS_SESSION_HISTORY_XLSX in hass.data["websocket_api"]


def test_utils_ships_in_the_release_zip():
    """verify_release_zip excludes dev dirs only; utils/xlsx.py ships."""
    src = (Path(__file__).resolve().parent.parent / "scripts" / "verify_release_zip.py").read_text()
    excl = src[src.index("excl_dirs = ("):src.index(")", src.index("excl_dirs = ("))]
    assert "utils/" not in excl
    must_not = src[src.index("MUST_NOT_SHIP = ("):src.index(")", src.index("MUST_NOT_SHIP = ("))]
    assert "utils/" not in must_not
    assert (Path(__file__).resolve().parent.parent / "utils" / "xlsx.py").is_file()


def test_no_third_party_import():
    src = (Path(__file__).resolve().parent.parent / "utils" / "xlsx.py").read_text()
    imports = {line.split()[1].split(".")[0] for line in src.splitlines()
               if line.startswith(("import ", "from "))}
    assert imports <= {"__future__", "datetime", "io", "re", "zipfile", "xml"}
