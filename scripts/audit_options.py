#!/usr/bin/env python3
"""#830 — how many decisions does SEM push onto the user?

Every option is a decision SEM could not make for itself. The count is
therefore a measure of how much thinking we outsourced, and it only ever
went up. This makes it a NUMBER, re-runnable, so "simpler" can be proven
the way #828 proved "declared once" and #829 proved "quieter".

Run:  python3 scripts/audit_options.py [--json]
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def measure() -> dict:
    cf = (ROOT / "config_flow.py").read_text()
    decls = re.findall(r'vol\.(?:Optional|Required)\(\s*["\']([a-z0-9_]+)["\']', cf)
    fields = Counter(decls)
    steps = set(re.findall(r"async def async_step_([a-z0-9_]+)", cf))

    def count_keys(fname: str) -> int:
        p = ROOT / fname
        return p.read_text().count('key="') if p.exists() else 0

    # A field the user meets on several pages reads as several settings.
    repeated = {k: n for k, n in fields.items() if n > 1}
    return {
        "config_fields": len(fields),
        "config_pages": len(steps),
        "field_declarations": len(decls),
        "repeated_fields": len(repeated),
        "worst_repeats": dict(Counter(repeated).most_common(8)),
        "number_entities": count_keys("number.py"),
        "switch_entities": count_keys("switch.py"),
        "user_facing_controls": len(fields) + count_keys("number.py") + count_keys("switch.py"),
    }


def main() -> int:
    m = measure()
    if "--json" in sys.argv:
        print(json.dumps(m, indent=2))
        return 0
    print("SEM option surface")
    print(f"  config-flow fields        {m['config_fields']:4}  "
          f"(declared {m['field_declarations']}x across {m['config_pages']} pages)")
    print(f"  …met on more than one page{m['repeated_fields']:4}  "
          "— a user reads each occurrence as a separate setting")
    print(f"  number entities           {m['number_entities']:4}")
    print(f"  switch entities           {m['switch_entities']:4}")
    print(f"  TOTAL user-facing controls{m['user_facing_controls']:4}")
    if m["worst_repeats"]:
        print("\n  worst repeats:")
        for k, n in m["worst_repeats"].items():
            print(f"    {k}: {n}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
