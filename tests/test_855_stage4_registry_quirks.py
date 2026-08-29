"""#855 stage 4 — the generic device layer learns brands from the REGISTRY,
never from its own code.

Stage 1 froze the count (ratchet), stage 3 gave observer mode the seam.
Stage 4 finishes the original plan: the brand knowledge that was CODE in
`devices/base.py` — the watchdog-refresh table and two log strings claiming
KEBA — moves out. The mechanics were already generic (they gate on
`has_service(domain, "set_failsafe")`); only the DATA was hardcoded. Its
home is the one brand registry the arc already built (#814/#848,
`consts/hardware_matrix.py`): a brand with a failsafe quirk adds a ROW, and
`devices/base.py` never changes again for a new brand.

Behavioral safety net: `tests/test_392_keba_heartbeat.py` pins the numbers
(KEBA 5.0 s, generic default, override wins) and must stay green untouched
through this move — this file pins only WHERE the knowledge lives.
"""
from __future__ import annotations

import ast
import pathlib

from custom_components.solar_energy_management.consts.hardware_matrix import (
    CHARGERS,
    charger_watchdog_refresh_map,
)

BASE_PY = pathlib.Path(__file__).resolve().parent.parent / "devices" / "base.py"


class TestTheRegistryCarriesTheQuirk:
    def test_keba_row_declares_its_watchdog_refresh(self):
        row = next(r for r in CHARGERS if "KEBA" in r["brand"])
        assert row.get("domain_token") == "keba"
        assert row.get("watchdog_refresh_s") == 5.0, (
            "the measured value — PROD showed the P30 reverting to its 6 A "
            "failsafe in well under 30 s, so the refresh sits below the "
            "~10 s coordinator cycle"
        )

    def test_the_map_is_built_from_rows_not_hardcoded(self):
        m = charger_watchdog_refresh_map()
        assert m.get("keba") == 5.0
        # Every entry must trace to a row that declares both fields.
        for token, seconds in m.items():
            row = next(r for r in CHARGERS if r.get("domain_token") == token)
            assert row["watchdog_refresh_s"] == seconds


class TestBaseKnowsNoBrandInCode:
    def test_no_brand_string_constants_outside_docstrings(self):
        """The stage-4 pin: comments and docstrings may keep their history
        (the ratchet watches their total), but CODE — string constants,
        dict keys, log messages — names no brand."""
        tree = ast.parse(BASE_PY.read_text())
        doc_positions = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", [])
                if body and isinstance(body[0], ast.Expr) and isinstance(
                        body[0].value, ast.Constant) and isinstance(
                        body[0].value.value, str):
                    doc_positions.add(id(body[0].value))
        offenders = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in doc_positions
                    and "keba" in node.value.lower()):
                offenders.append(f"L{node.lineno}: {node.value[:60]!r}")
        assert not offenders, (
            "brand names in devices/base.py CODE — move the knowledge to "
            "the hardware matrix (a row), not the generic layer:\n"
            + "\n".join(offenders)
        )

    def test_the_hardcoded_table_is_gone(self):
        src = BASE_PY.read_text()
        assert '_BRAND_WATCHDOG_REFRESH_S = {\n    "keba"' not in src, (
            "the table must be BUILT from the registry, not typed here"
        )
