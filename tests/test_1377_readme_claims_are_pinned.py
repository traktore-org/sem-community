"""(#1377) README sentences that claim a capability are checked against code.

Each row of ``CLAIMS`` is a sentence pattern in README.md and a check that
reads the claim's number or names from the README and compares them with
data in the code: the manifest, the hardware matrix, the translations, the
entity descriptions, the dashboard template. A row whose sentence is gone
from the README fails too, so the table cannot rot. A claim that is false,
or a brand sentence that says "works automatically" for a brand the matrix
does not mark tested-live, fails here instead of reaching a user.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

from custom_components.solar_energy_management.consts.core import (
    DEFAULT_UPDATE_INTERVAL,
)
from custom_components.solar_energy_management.coordinator.storage import (
    SESSION_HISTORY_MAX,
)

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")

_spec = importlib.util.spec_from_file_location(
    "hardware_matrix", ROOT / "consts" / "hardware_matrix.py")
HM = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(HM)

ENTITY_FILES = ("sensor.py", "number.py", "switch.py", "select.py", "time.py",
                "button.py", "binary_sensor.py")


def _entity_count(files=ENTITY_FILES) -> int:
    return sum(len(re.findall(r'\bkey=f?"', (ROOT / f).read_text(encoding="utf-8")))
               for f in files)


def _rows(brand_token: str) -> list:
    return [r for r in HM.INVERTERS if r["brand"].startswith(brand_token)]


def _languages() -> int:
    return len(list((ROOT / "translations").glob("*.json")))


def _classic_views() -> int:
    text = (ROOT / "dashboard" / "sem_dashboard_template.yaml").read_text(encoding="utf-8")
    paths = re.findall(r"^  - title: (\w+)", text, re.MULTILINE)
    return len([p for p in paths if p != "Simulation"])  # shown only on a switch (#1083)


def _discharge_list_ok(names: str) -> list:
    bad = []
    for raw in names.split(","):
        token = re.split(r"[ (/]", raw.strip())[0]
        rows = _rows(token)
        if not rows or not any(r.get("discharge_control") in (True, "declared") for r in rows):
            bad.append(token)
    return bad


def _check_updates(m):
    return int(m.group(1)) == DEFAULT_UPDATE_INTERVAL, f"code default is {DEFAULT_UPDATE_INTERVAL} s"


def _check_cloud(_m):
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    return manifest["iot_class"].startswith("local"), f"iot_class is {manifest['iot_class']}"


def _check_entities(m):
    n = _entity_count()
    return n >= int(m.group(1).replace(",", "")), f"{n} entity descriptions"


def _check_sensors(m):
    n = _entity_count(("sensor.py",))
    return n >= int(m.group(1)), f"{n} sensor descriptions"


def _check_languages(m):
    return int(m.group(1)) == _languages(), f"{_languages()} translation files"


def _check_views(m):
    return int(m.group(1)) == _classic_views(), f"template has {_classic_views()} views"


def _check_ha_floor(m):
    floor = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))["homeassistant"]
    return m.group(1) == floor, f"hacs.json floor is {floor}"


def _check_sessions(m):
    return int(m.group(1)) == SESSION_HISTORY_MAX, f"store keeps {SESSION_HISTORY_MAX}"


def _check_live_trio(_m):
    brands = ("Sessy", "Huawei", "Sonnen")
    bad = [b for b in brands if not any(r["status"] == "tested-live" for r in _rows(b))]
    return not bad, f"not tested-live in the matrix: {bad}"


def _check_discharge(m):
    bad = _discharge_list_ok(m.group(1))
    return not bad, f"no discharge control in the matrix: {bad}"


def _check_powerwall(_m):
    row = _rows("Tesla Powerwall")[0]
    return row["status"] != "tested-live" and "setup" in row["evidence"], \
        "matrix must show Powerwall as not tested-live and name the setup step"


#: (name, README pattern, check(match) -> (ok, why))
CLAIMS = (
    ("update interval", r"every (\d+) seconds", _check_updates),
    ("no cloud", r"No cloud, no subscription", _check_cloud),
    ("entity count", r"\*\*([\d,]+)\+ sensors and entities\*\*", _check_entities),
    ("sensor count", r"SEM creates (\d+)\+ sensors", _check_sensors),
    ("languages", r"in (\d+) languages", _check_languages),
    ("classic views", r"classic dashboard\*\* keeps its (\d+) views", _check_views),
    ("HA floor", r"\*\*Home Assistant (2026\.\d+\.\d+)\*\* or newer", _check_ha_floor),
    ("session history", r"last (\d+) sessions per charger", _check_sessions),
    ("tested-live trio", r"Sessy \(NL\), Huawei LUNA2000 and Sonnen work automatically and are tested live", _check_live_trio),
    ("discharge list", r"\*\*Battery discharge control auto-detected for:\*\* ([^\n]+)", _check_discharge),
    ("powerwall", r"Tesla Powerwall reads automatically; its grid charge needs a setup step", _check_powerwall),
)

#: Claims in the README that no test can check from code. Listed, not pinned.
UNPINNABLE = (
    "SEM distributes surplus by priority (behaviour, covered by pipeline tests)",
    "'works with any inverter with HA sensors' (open-ended)",
    "'auto-detects both sign conventions' (per-brand pipeline tests, #129)",
    "battery capacity auto-detected from the inverter (depends on the integration)",
    "the 4 colour-named dashboard screenshots and their captions",
)


class TestReadmeClaims:

    def test_every_claim_is_still_in_the_readme(self):
        gone = [n for n, pat, _ in CLAIMS if not re.search(pat, README)]
        assert not gone, f"claim no longer in README, drop it from CLAIMS: {gone}"

    def test_every_claim_holds(self):
        failed = []
        for name, pat, check in CLAIMS:
            for m in re.finditer(pat, README):
                ok, why = check(m)
                if not ok:
                    failed.append(f"{name}: '{m.group(0)[:70]}' -> {why}")
        assert not failed, "README claims the code does not back:\n  " + "\n  ".join(failed)

    def test_newest_language_count_is_the_current_one(self):
        """Old release notes say '15 languages'; the newest number must be today's."""
        counts = [int(n) for n in re.findall(r"(\d+) languages", README)]
        assert max(counts) == _languages(), f"README's top language count {max(counts)} vs {_languages()}"


class TestAutomaticallyNeedsEvidence:
    """A sentence that says a brand 'works automatically' or is 'tested live'
    must name only brands the matrix marks tested-live (the Powerwall slip)."""

    def _brands(self):
        tokens = {}
        for row in HM.INVERTERS:
            token = re.split(r"[ (/]", row["brand"])[0]
            tokens.setdefault(token, []).append(row)
        return {t: rows for t, rows in tokens.items() if len(t) >= 4}

    def test_automatic_claims_name_only_tested_live_brands(self):
        brands = self._brands()
        offenders = []
        for sentence in re.split(r"(?<=[.!?])\s+|\n", README):
            if not re.search(r"works? automatically|are tested live|verified in CI", sentence):
                continue
            for token, rows in brands.items():
                if re.search(rf"\b{re.escape(token)}\b", sentence) and not any(
                        r["status"] == "tested-live" for r in rows):
                    offenders.append(f"{token}: {sentence.strip()[:90]}")
        assert not offenders, offenders

    def test_the_scan_sees_the_claim_it_guards(self):
        hits = [s for s in re.split(r"(?<=[.!?])\s+|\n", README)
                if re.search(r"works? automatically", s)]
        assert hits, "no 'work automatically' sentence left; delete this class or fix the regex"
