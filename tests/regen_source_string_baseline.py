#!/usr/bin/env python3
"""(#925) Regenerate the source-string guard baseline.

Run this ONLY when the number goes DOWN — i.e. after converting guards to
``tests/ast_contracts.py`` — or when raising it deliberately for a guard
whose subject genuinely is text (a log line a user reads, a comment, an
annotation). Raising it to make a red test green is how a ratchet becomes
a rubber stamp.
"""
import json
import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
PATTERN = re.compile(r"assert\s+[^\n=]*\bin\s+(src|source|_src)\b")

per_file = {}
for p in sorted(TESTS.glob("test_*.py")):
    n = len(PATTERN.findall(p.read_text(encoding="utf-8")))
    if n:
        per_file[p.name] = n

old = {}
bl = TESTS / "source_string_guard_baseline.json"
if bl.exists():
    old = json.loads(bl.read_text(encoding="utf-8"))

data = {
    "_comment": ("(#925) Source-string guards — assertions coupled to the "
                 "SPELLING of the code rather than the code. Shrink-only. "
                 "Regenerate ONLY when converting downward, or when raising "
                 "deliberately for a guard whose subject genuinely is text."),
    "total": sum(per_file.values()),
    "files": len(per_file),
    "per_file": per_file,
}
bl.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
              encoding="utf-8")
was = old.get("total")
arrow = "" if was is None else f"  ({was} -> {data['total']})"
print(f"baseline: {data['total']} guards across {data['files']} files{arrow}")
if was is not None and data["total"] > was:
    print("  ⚠ the ledger GREW. That needs a stated reason, not a regen.")
