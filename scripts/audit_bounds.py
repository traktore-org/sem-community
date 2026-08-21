#!/usr/bin/env python3
"""Bug-class 50 — measure, don't trust: how much of the bounds surface is guarded?

`tests/test_813_options_round_trip.py` calls itself "the systemic guard". On
21.08 it compared **5 distinct settings out of 48**, and could not tell —
its no-vacuous-pass floor is satisfied by duplicate matches of those same 5.

A guard's docstring is a claim. This prints the number.

    python3 scripts/audit_bounds.py

Exit code is 0 always: this is a measurement, not a gate. The gate is the
ledger entry it feeds (docs/BUG_CLASSES.md class 50) and, once built, the
one-source-of-truth table in #828.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def flow_fields() -> dict:
    """Every options-flow NUMBER field, with its bounds.

    Two traps, both of which this scan fell into before being fixed:

    1. NEVER search from the first mention of a key. These keys also appear in
       OPTIONS_FLOW_OWNED_KEYS and in copy-through loops thousands of lines
       earlier, and a lazy search happily reads a different field's bounds —
       exactly how #826's first test passed against the live bug.
    2. NEVER let the search cross a field boundary. Scanning from a key to
       "the next NumberSelectorConfig" walked straight past a BooleanSelector
       and reported `observer_mode` — a checkbox — as a number field with two
       contradictory ranges. An audit that invents findings is worse than no
       audit, because it gets believed.

    So: split the source at each field declaration and look only INSIDE the
    chunk that belongs to the key.
    """
    src = (ROOT / "config_flow.py").read_text()
    chunks = re.split(r'(?=vol\.(?:Optional|Required)\(\s*\n\s*")', src)
    out: dict = {}
    for chunk in chunks:
        m = re.match(r'vol\.(?:Optional|Required)\(\s*\n\s*"([a-z_0-9]+)"', chunk)
        if not m:
            continue
        b = re.search(r'NumberSelectorConfig\(\s*\n?\s*min=([\d.]+),\s*max=([\d.]+)',
                      chunk)
        if not b:
            continue                      # not a number field
        out.setdefault(m.group(1), set()).add(
            (float(b.group(1)), float(b.group(2))))
    return out


def entity_bounds() -> dict:
    src = (ROOT / "number.py").read_text()
    out: dict = {}
    for m in re.finditer(
            r'key=f?"(?:charger_\{cid\}_)?([a-z_0-9]+)",(?:.*\n){0,10}?'
            r'.*?native_min_value=([\d.]+), native_max_value=([\d.]+)', src):
        out.setdefault(m.group(1), (float(m.group(2)), float(m.group(3))))
    return out


def main() -> None:
    fields, ents = flow_fields(), entity_bounds()
    total_entities = (ROOT / "number.py").read_text().count("native_min_value=")
    paired = {k for k in fields if k in ents}

    print("── bounds surface ──")
    print(f"  options-flow number fields      : {len(fields)}")
    print(f"  number entities defined         : {total_entities}")
    print(f"  entity bounds this scan parses  : {len(ents)}")
    print(f"  fields WITH an entity twin      : {len(paired)}"
          "   <- all the page/entity guard can ever see")
    print(f"  fields with NO twin (unguarded) : {len(fields) - len(paired)}"
          "   <- #826 lived here")
    coverage = 100.0 * len(paired) / len(fields) if fields else 0.0
    print(f"  guard coverage                  : {coverage:.0f}% of fields")

    narrow = [(k, f, ents[k]) for k, fs in fields.items() if k in ents
              for f in fs if f[0] > ents[k][0] or f[1] < ents[k][1]]
    print("\n── page narrower than its entity (the #813 failure) ──")
    print("  none" if not narrow else "")
    for k, f, e in narrow:
        print(f"  {k}: page {f} vs entity {e}")

    wider = [(k, f, ents[k]) for k, fs in fields.items() if k in ents
             for f in fs if f[0] < ents[k][0] or f[1] > ents[k][1]]
    print("\n── page WIDER than its entity (the inverse drift) ──")
    print("  none" if not wider else "")
    for k, f, e in wider:
        print(f"  {k}: page {f} vs entity {e}")

    print("\n── same key, different bounds on different pages ──")
    multi = {k: v for k, v in fields.items() if len(v) > 1}
    print("  none" if not multi else "")
    for k, v in sorted(multi.items()):
        print(f"  {k}: {sorted(v)}")


if __name__ == "__main__":
    main()
