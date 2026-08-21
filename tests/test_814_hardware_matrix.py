"""#814 — the hardware matrix is the truth, the doc is a view, and the
coverage gap can only shrink.

Three pins:
1. docs/SUPPORTED_HARDWARE.md equals a fresh regeneration — the doc can
   never drift from the matrix (#806's complaint was a README reference
   to a matrix nobody could find; a stale one is worse than none).
2. Every brand the README's Supported Hardware section claims has a
   matrix row — a claim without a row is a claim without a status.
3. Every implemented/tested inverter pattern appears in the pipeline
   test file, and rows WITHOUT pipeline coverage live in a shrinking
   allowlist (the house ratchet shape): removals forced, additions
   impossible.
"""
import re
from pathlib import Path

import importlib.util

_ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "hardware_matrix", _ROOT / "consts" / "hardware_matrix.py")
_hm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_hm)

_gen_spec = importlib.util.spec_from_file_location(
    "generate_hardware_doc", _ROOT / "scripts" / "generate_hardware_doc.py")


def _render():
    gen = importlib.util.module_from_spec(_gen_spec)
    _gen_spec.loader.exec_module(gen)
    return gen.render()


class TestDocIsAView:

    def test_doc_matches_regeneration(self):
        doc = (_ROOT / "docs" / "SUPPORTED_HARDWARE.md").read_text()
        assert doc == _render(), (
            "docs/SUPPORTED_HARDWARE.md drifted from the matrix — run "
            "python3 scripts/generate_hardware_doc.py and commit the result")

    def test_readme_links_the_doc(self):
        readme = (_ROOT / "README.md").read_text()
        assert "SUPPORTED_HARDWARE.md" in readme, (
            "#806: the README must link the generated matrix")


class TestEveryClaimHasARow:
    """Brand names the README claims, mapped to matrix rows. The README
    keeps its prose; this test keeps it honest."""

    def test_readme_inverter_claims_have_rows(self):
        readme = (_ROOT / "README.md").read_text()
        rows = " ".join(r["brand"] for r in _hm.INVERTERS)
        for claim in ("Huawei", "SolaX", "DEYE", "Growatt", "Sofar", "Solis",
                      "Fronius", "SMA", "SolarEdge", "Enphase", "GoodWe",
                      "Powerwall", "Kostal", "Sungrow", "Victron", "Sonnen",
                      "E3DC", "GivEnergy", "Fox ESS", "Alpha ESS", "Senec",
                      "RCT", "KSTAR", "Sessy"):
            assert claim in readme, f"premise: README stopped claiming {claim}"
            assert claim in rows, (
                f"README claims {claim} but the matrix has no row — "
                "a claim without a status")

    def test_readme_charger_claims_have_rows(self):
        rows = " ".join(r["brand"] for r in _hm.CHARGERS)
        for claim in ("KEBA", "Wallbox", "go-eCharger", "Easee", "Zaptec",
                      "ChargePoint", "Heidelberg", "OpenWB", "OCPP", "Ohme",
                      "Peblar", "V2C", "Alfen", "Blue Current", "OpenEVSE"):
            assert claim in rows, f"README claims {claim}, no matrix row"


class TestEvidenceRules:
    """The rules apply to EVERY table, including tables added later — the
    corpus sweep (21.08) grew the matrix from 2 tables to 4, and a new
    table that quietly escaped the citation rule would be exactly the #530
    false-positive door reopening."""

    def test_every_table_obeys_the_rules(self):
        """No table may exist outside _hm.TABLES: the rules below iterate
        ALL_ROWS, so an unregistered table would be unchecked."""
        loose = {
            name for name, val in vars(_hm).items()
            if name.isupper() and isinstance(val, list) and val
            and isinstance(val[0], dict) and name != "ALL_ROWS"
        }
        assert loose == set(_hm.TABLES), (
            f"tables not registered in TABLES (so unchecked): "
            f"{loose - set(_hm.TABLES)}")
        assert len(_hm.ALL_ROWS) == sum(len(t) for t in _hm.TABLES.values())

    def test_every_row_has_the_common_fields(self):
        for r in _hm.ALL_ROWS:
            assert r.get("brand"), f"row without a brand: {r}"
            assert r["status"] in ("tested-live", "implemented", "requested"), \
                f"{r['brand']}: unknown status {r['status']!r}"
            assert "evidence" in r, f"{r['brand']}: no evidence field"

    def test_tested_live_requires_citation(self):
        for r in _hm.ALL_ROWS:
            if r["status"] == "tested-live":
                assert r["evidence"].strip(), (
                    f"{r['brand']}: tested-live without evidence — the #530 "
                    "lesson: no citation, no claim")

    def test_tested_live_evidence_names_a_source(self):
        """A live claim points at something a reader can open: an issue, a
        discussion, or our own system. Prose alone is not a citation."""
        ref = re.compile(r"#\d+|disc\. \d+|SEM production|SEM's own")
        for r in _hm.ALL_ROWS:
            if r["status"] == "tested-live":
                assert ref.search(r["evidence"]), (
                    f"{r['brand']}: tested-live evidence names no source "
                    f"(issue #, disc. N, or SEM production): "
                    f"{r['evidence']!r}")

    def test_requested_cites_the_issue(self):
        for r in _hm.ALL_ROWS:
            if r["status"] == "requested":
                assert "#" in r["evidence"], (
                    f"{r['brand']}: requested without an issue reference")

    def test_doc_shows_every_row(self):
        doc = (_ROOT / "docs" / "SUPPORTED_HARDWARE.md").read_text()
        for r in _hm.ALL_ROWS:
            assert r["brand"] in doc, (
                f"{r['brand']} is in the matrix but not in the rendered doc "
                "— the generator is dropping a table")


# Inverter rows with NO brand-named pipeline test yet. All three are
# ha-solarman brands whose sign conventions we have not seen from a real
# install — writing a "pipeline test" with guessed signs would be the #530
# false-positive mistake in test form. Shrink only: a reporter export turns
# a row into a test and out of this set.
_PIPELINE_GAP_ALLOWLIST = {
    "DEYE / Sunsynk",
    "Sofar",
    "Solis",
}


def _brand_key(brand: str) -> str:
    return brand.split()[0].split("/")[0].replace("-", "").lower()


class TestPipelineCoverageRatchet:
    """Every implemented/tested inverter brand is exercised by the pipeline
    file — either a brand-named test class, or (for the A-F sign families)
    the pattern family class plus the brand named in the file. ED rows have
    no family to hide behind: they need a brand-named class, which is where
    the documented shrink-only gap lives."""

    def test_every_implemented_brand_has_a_pipeline_test(self):
        import re
        src = (_ROOT / "tests" / "test_split_grid_integration.py").read_text()
        low = src.lower()
        classes = " ".join(re.findall(r"^class Test(\w+)", src, re.M)).lower()
        missing = set()
        for r in _hm.INVERTERS:
            if r["status"] == "requested":
                continue
            key = _brand_key(r["brand"])
            if key in classes:
                continue
            if r["pattern"] in ("A", "B", "C", "D", "E", "F") and \
               f"pattern {r['pattern'].lower()}" in low and key in low:
                continue
            missing.add(r["brand"])
        gap = missing - _PIPELINE_GAP_ALLOWLIST
        assert not gap, (
            f"matrix claims these brands but the pipeline file neither names "
            f"a class for them nor covers their pattern family: {gap}")
        stale = _PIPELINE_GAP_ALLOWLIST - missing
        assert not stale, (
            f"allowlist entries now covered — remove them: {stale}")
