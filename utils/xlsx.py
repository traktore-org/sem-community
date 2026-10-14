"""(#1083) A small .xlsx writer, standard library only.

A CSV opens wrong in half of Europe: Excel splits on ``;`` or ``,`` by the
system locale. An .xlsx has no delimiter, and its cells carry their type.

Limits: one header row plus data rows per sheet; no formulas, merged cells,
fonts or colours. Numbers, booleans, dates and text only.
"""
from __future__ import annotations

import datetime as dt
import io
import re
import zipfile
from xml.sax.saxutils import escape

_ZIP_TIME = (2000, 1, 1, 0, 0, 0)   # fixed, so the same rows give the same bytes
_EPOCH = dt.datetime(1899, 12, 30)  # Excel's day 0 (with its 1900 leap-year quirk)
_BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")
# XML 1.0 refuses these; a stray one would make Excel call the file broken.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")

# Style index in cellXfs: 0 = plain, 1 = date, 2 = date + time.
_STYLE_DATE = 1
_STYLE_DATETIME = 2

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def sheet_name(name: str, taken: set[str] | None = None) -> str:
    """A name Excel accepts: no []:*?/\\, at most 31 chars, not empty, unique."""
    clean = _BAD_SHEET_CHARS.sub("_", _CONTROL.sub("", str(name or ""))).strip("'")
    clean = clean[:31] or "Sheet"
    if taken is not None:
        base, n = clean, 2
        while clean.lower() in {t.lower() for t in taken}:
            suffix = f" ({n})"
            clean = base[: 31 - len(suffix)] + suffix
            n += 1
        taken.add(clean)
    return clean


def _col(index: int) -> str:
    """0 → A, 25 → Z, 26 → AA."""
    out = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def _text(value: str) -> str:
    return escape(_CONTROL.sub("", value))


def _serial(value: dt.date) -> float:
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            value = value.replace(tzinfo=None)   # keep the wall-clock time
        delta = value - _EPOCH
        return delta.days + delta.seconds / 86400 + delta.microseconds / 86400e6
    return float((value - _EPOCH.date()).days)


def _cell(ref: str, value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"><v>{int(value)}</v></c>'
    if isinstance(value, (int, float)):
        if value != value or value in (float("inf"), float("-inf")):
            return ""   # NaN / inf have no cell form
        # plain int/float: an IntEnum's repr is not a number
        value = int(value) if isinstance(value, int) else float(value)
        return f'<c r="{ref}" t="n"><v>{value!r}</v></c>'
    if isinstance(value, dt.datetime):
        return f'<c r="{ref}" s="{_STYLE_DATETIME}"><v>{_serial(value)!r}</v></c>'
    if isinstance(value, dt.date):
        return f'<c r="{ref}" s="{_STYLE_DATE}"><v>{_serial(value)!r}</v></c>'
    # An inline string is text, never parsed: "=SUM(A1)" can not run.
    text = _text(str(value))
    space = ' xml:space="preserve"' if text != text.strip() else ""
    return f'<c r="{ref}" t="inlineStr"><is><t{space}>{text}</t></is></c>'


def _width(value) -> int:
    if value is None:
        return 0
    if isinstance(value, dt.datetime):
        return 16
    if isinstance(value, dt.date):
        return 10
    return len(str(value))


def _sheet_xml(rows: list[list]) -> str:
    widths: dict[int, int] = {}
    body = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            cells.append(_cell(f"{_col(c)}{r}", value))
            widths[c] = max(widths.get(c, 0), _width(value))
        body.append(f'<row r="{r}">{"".join(cells)}</row>')
    cols = "".join(
        f'<col min="{c + 1}" max="{c + 1}" width="{min(max(w, 6), 60) + 2}" customWidth="1"/>'
        for c, w in sorted(widths.items())
    )
    return (
        f'{_HEAD}<worksheet xmlns="{_NS}" xmlns:r="{_NS_R}">'
        + (f"<cols>{cols}</cols>" if cols else "")
        + f'<sheetData>{"".join(body)}</sheetData></worksheet>'
    )


_STYLES = (
    f'{_HEAD}<styleSheet xmlns="{_NS}">'
    '<numFmts count="2">'
    '<numFmt numFmtId="164" formatCode="yyyy-mm-dd"/>'
    '<numFmt numFmtId="165" formatCode="yyyy-mm-dd hh:mm"/>'
    "</numFmts>"
    '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="3">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    "</cellXfs>"
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)


def write_workbook(sheets: list[tuple[str, list[list]]]) -> bytes:
    """The sheets as .xlsx bytes. Each sheet is (name, rows), the first row
    the header. Same input, same bytes."""
    if not sheets:
        sheets = [("Sheet", [])]
    taken: set[str] = set()
    names = [sheet_name(name, taken) for name, _ in sheets]
    n = len(sheets)

    content_types = (
        f'{_HEAD}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, n + 1)
        )
        + "</Types>"
    )
    root_rels = (
        f'{_HEAD}<Relationships xmlns="{_NS_PKG}">'
        f'<Relationship Id="rId1" Type="{_NS_R}/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook = (
        f'{_HEAD}<workbook xmlns="{_NS}" xmlns:r="{_NS_R}"><sheets>'
        + "".join(
            f'<sheet name="{escape(name, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>'
            for i, name in enumerate(names, start=1)
        )
        + "</sheets></workbook>"
    )
    workbook_rels = (
        f'{_HEAD}<Relationships xmlns="{_NS_PKG}">'
        + "".join(
            f'<Relationship Id="rId{i}" Type="{_NS_R}/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, n + 1)
        )
        + f'<Relationship Id="rId{n + 1}" Type="{_NS_R}/styles" Target="styles.xml"/>'
        "</Relationships>"
    )

    parts = [
        ("[Content_Types].xml", content_types),
        ("_rels/.rels", root_rels),
        ("xl/workbook.xml", workbook),
        ("xl/_rels/workbook.xml.rels", workbook_rels),
        ("xl/styles.xml", _STYLES),
    ] + [
        (f"xl/worksheets/sheet{i}.xml", _sheet_xml([list(r) for r in rows]))
        for i, (_, rows) in enumerate(sheets, start=1)
    ]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, xml in parts:
            info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            # a lone surrogate in a name cannot be UTF-8: replace, never raise
            zf.writestr(info, xml.encode("utf-8", "replace"))
    return buf.getvalue()
