"""#855, every layer — brand knowledge outside the adapters and the crawler
only shrinks.

The first ratchet watched ``devices/base.py`` alone. A tariff fix (#1162)
then taught the tariff provider two brand names (an Amber and an Octopus
forecast sibling) and nothing failed: SEM finds things through the crawler,
by role, and brands are test fixtures. Now every generic file is counted.
A file may lose brand mentions, never gain; a file that had none may not
start. The adapters (charger, battery), the crawler (``hardware_detection``
and ``consts/``) and the fixtures are exempt.

    python3 scripts/audit_brand_footprint.py --layers-baseline   # after a shrink
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from .ratchet_guard import assert_not_loosened

ROOT = Path(__file__).resolve().parents[1]


def _audit():
    spec = importlib.util.spec_from_file_location(
        "audit_brand_footprint", ROOT / "scripts" / "audit_brand_footprint.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


AUDIT = _audit()
BASELINE_PATH = ROOT / "tests" / "brand_footprint_layers_baseline.json"
BASELINE = json.loads(BASELINE_PATH.read_text())["per_file"]


def test_no_generic_file_starts_naming_a_brand():
    new = sorted(set(AUDIT.count_layers(ROOT)) - set(BASELINE))
    assert not new, (
        f"{new} now name a brand. Teach the crawler the ROLE instead "
        "(hardware_detection.py / consts/role_lexicon.py); brands are fixtures.")


def test_no_generic_file_names_more_brands():
    # (#1304) the baseline itself may not have been loosened quietly
    assert_not_loosened(BASELINE_PATH, lambda d: d["total"], "brand layers")
    grew = {f: (BASELINE[f], n) for f, n in AUDIT.count_layers(ROOT).items()
            if f in BASELINE and n > BASELINE[f]}
    assert not grew, (
        f"brand mentions grew (was, now): {grew}. Find it by role through the "
        "crawler, not by name.")


def test_the_baseline_describes_today():
    assert AUDIT.count_layers(ROOT) == BASELINE, (
        "the count fell — good. Record it: "
        "python3 scripts/audit_brand_footprint.py --layers-baseline")
