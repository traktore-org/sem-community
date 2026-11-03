#!/usr/bin/env python3
"""(#1304) What every shrink-only baseline says today, against what SEM ships.

    python3 scripts/ratchet_report.py

One line per baseline: the live count the test measures, the count in the
working-tree baseline, the count in the reference (origin/develop, or the
newest tag when on develop) and the change. A growth with no declaration in
``tests/<baseline>.loosen`` is marked ``UNDECLARED`` — that is what the test
fails on. Live reads that need the HA test layout print ``n/a`` and why.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(ROOT))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _guard():
    return _load("ratchet_guard", "tests/ratchet_guard.py")


def _live_options():
    return _load("audit_options", "scripts/audit_options.py").measure()["user_facing_controls"]


def _live_brand_base():
    audit = _load("audit_brand_footprint", "scripts/audit_brand_footprint.py")
    return sum(audit.count_brands((ROOT / "devices" / "base.py").read_text()).values())


def _live_brand_layers():
    audit = _load("audit_brand_footprint", "scripts/audit_brand_footprint.py")
    return sum(audit.count_layers(ROOT).values())


def _live_causal():
    cc = _load("causal_claims", "tests/causal_claims.py")
    return sum(1 for c in cc.claims() if not c.annotated)


def _live_source_strings():
    pat = re.compile(r"assert\s+[^\n=]*\bin\s+(src|source|_src)\b")
    return sum(len(pat.findall(p.read_text(encoding="utf-8"))) for p in TESTS.glob("test_*.py"))


def _live_gap():
    roster = _load("integration_roster", "consts/integration_roster.py")
    crawler = _load("crawler", "scripts/crawl_integration_roster.py")
    floor = json.loads((TESTS / "roster_coverage_baseline.json").read_text())["install_floor"]
    return sum(1 for row in crawler.backlog(roster.ROSTER, roster.ROLE_VOCAB) if row[2] >= floor)


# (baseline file, what, measure of the baseline, live reader, shrink-only?)
RATCHETS = [
    ("option_surface_baseline.json", "option surface", lambda d: d["total"], _live_options, True),
    ("brand_footprint_baseline.json", "brand words in devices/base.py", lambda d: d["total"], _live_brand_base, True),
    ("brand_footprint_layers_baseline.json", "brand words in generic files", lambda d: d["total"], _live_brand_layers, True),
    ("causal_claim_baseline.json", "unproven causal claims", lambda d: d["total"], _live_causal, True),
    ("source_string_guard_baseline.json", "source-string guards", lambda d: d["total"], _live_source_strings, True),
    ("roster_coverage_baseline.json", "unnamed brands over the floor", lambda d: d["unnamed_over_floor"], _live_gap, True),
    ("roster_roles_baseline.json", "roster roles (grows with coverage)", lambda d: len(d["roles"]), None, False),
]


def main() -> int:
    rg = _guard()
    rows = []
    bad = 0
    for name, what, measure, live_fn, shrink_only in RATCHETS:
        path = TESTS / name
        now = measure(json.loads(path.read_text(encoding="utf-8")))
        text, ref = rg.reference(path)
        before = measure(json.loads(text)) if text else None
        try:
            live = live_fn() if live_fn else "-"
        except Exception as e:  # noqa: BLE001 — a report never crashes on one row
            live = f"n/a ({type(e).__name__})"
        delta = "?" if before is None else f"{now - before:+d}"
        flag = ""
        if shrink_only and before is not None and now > before:
            covering = {n for n, to in rg.declared(path).items() if to == now}
            flag = f"declared #{min(covering)}" if covering else "UNDECLARED"
            bad += not covering
        rows.append((what, live, now, before if before is not None else "?", delta, flag, ref if text else ""))
    w = max(len(r[0]) for r in rows)
    print(f"{'baseline':<{w}}  {'live':>8}  {'file':>6}  {'ref':>6}  {'delta':>6}  note")
    for what, live, now, before, delta, flag, ref in rows:
        print(f"{what:<{w}}  {str(live):>8}  {now:>6}  {str(before):>6}  {delta:>6}  {flag} {('(' + ref + ')') if ref else ''}".rstrip())
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
