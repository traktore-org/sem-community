#!/usr/bin/env python3
"""#855 — count brand knowledge sitting in the generic device layer.

``devices/base.py`` is supposed to know about DEVICES; the adapters in
``coordinator/charger_adapters/`` exist to hold brand quirks. Today the
generic layer carries the actual mechanics for a dozen brands, which is
why a one-idea fix (#854, "a stop must not enable the charger") had to be
made in two layers, and why observer mode — which cuts above the adapter —
cannot see the commands SEM would really send.

This is the measuring stick for the move. It counts, it does not judge:
the ratchet test decides whether a number is allowed to have changed.

    python3 scripts/audit_brand_footprint.py             # report
    python3 scripts/audit_brand_footprint.py --baseline  # rewrite the baseline
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = ROOT / "devices" / "base.py"
BASELINE = ROOT / "tests" / "brand_footprint_baseline.json"

# Every brand SEM speaks to. Kept explicit rather than inferred: a new
# brand must be ADDED here consciously, which is itself the moment to ask
# whether its code belongs in the generic layer at all.
BRANDS = (
    "keba", "wallbox", "zaptec", "easee", "go-e", "wattpilot", "heidelberg",
    "openwb", "ocpp", "ohme", "peblar", "v2c", "alfen", "openevse",
    "chargepoint", "juicebox", "garo", "tesla", "deye", "huawei", "fronius",
    "solaredge", "sma", "solax", "goodwe", "sungrow", "growatt", "enphase",
    "powerwall", "kostal", "sonnen", "victron", "marstek", "nibe", "buderus",
)


def count_brands(text: str) -> dict[str, int]:
    """Brand mentions, comments and docstrings included — deliberately.

    A comment explaining KEBA's firmware in the generic layer is brand
    knowledge living in the wrong file just as much as the code it
    explains; when the mechanics move, the explanation moves with them.
    """
    out: dict[str, int] = {}
    for brand in BRANDS:
        hits = re.findall(
            rf"(?<![a-z0-9_]){re.escape(brand)}(?![a-z0-9])", text, re.I)
        if hits:
            out[brand] = len(hits)
    return dict(sorted(out.items()))


def main() -> int:
    counts = count_brands(TARGET.read_text())
    total = sum(counts.values())
    if "--baseline" in sys.argv:
        old = json.loads(BASELINE.read_text())
        old["total"] = total
        old["per_brand"] = counts
        BASELINE.write_text(json.dumps(old, indent=2) + "\n")
        print(f"baseline rewritten: {total} brand mentions in {TARGET.name}")
        return 0
    print(f"{total} brand mentions in {TARGET.relative_to(ROOT)}")
    for brand, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {brand:14} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
