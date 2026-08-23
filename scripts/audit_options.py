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


#: Steps that are lifecycle variants of ONE object, or entry points into the
#: whole flow. A field declared across these is ONE setting a user meets once —
#: adding a charger, editing that charger and reconfiguring the integration are
#: the same question at different moments, never three settings.
#:
#: This distinction is why the raw repeat count misleads. It reported 33
#: "duplicates", of which only 3 are pages a user meets in one pass. Retiring
#: the other 30 would have been work against a measurement artifact — and
#: "retire the duplicates first" was the plan until this was measured.
STEP_FAMILY = {
    "ev_charger": "ev_charger",
    "ev_charger_add": "ev_charger",
    "ev_charger_edit": "ev_charger",
    "ev_charger_menu": "ev_charger",
    "ev_charger_remove": "ev_charger",
    # entry points into the flow, not pages of their own
    "user": None,
    "init": None,
    "reconfigure": None,
    "integration_discovery": None,
}


#: Human verdicts on the shortlist ``STEP_FAMILY`` produces.
#:
#: Automation can only ever shortlist: it sees the same key on two pages and
#: cannot tell a duplicate from a global default with a per-object override.
#: Three candidates is a five-minute human review, which is the right output —
#: so the verdicts are recorded here rather than the heuristic being tuned
#: until it agrees with them.
NOT_DUPLICATE = {
    # settings_ev holds the GLOBAL default; the charger pages hold that
    # charger's value and default FROM the global. Two real settings.
    "daily_ev_target": "global default + per-charger override, not duplication",
}


def _declaring_steps(cf: str) -> dict:
    """field -> the set of config-flow steps that declare it."""
    steps = [(m.start(), m.group(1))
             for m in re.finditer(r"async def async_step_([a-z0-9_]+)", cf)]

    def owner(pos: int) -> str:
        name = "(module)"
        for start, n in steps:
            if start < pos:
                name = n
            else:
                break
        return name

    out: dict = {}
    for m in re.finditer(r'vol\.(?:Optional|Required)\(\s*["\']([a-z0-9_]+)["\']', cf):
        out.setdefault(m.group(1), set()).add(owner(m.start()))
    return out


def measure() -> dict:
    cf = (ROOT / "config_flow.py").read_text()
    decls = re.findall(r'vol\.(?:Optional|Required)\(\s*["\']([a-z0-9_]+)["\']', cf)
    fields = Counter(decls)
    steps = set(re.findall(r"async def async_step_([a-z0-9_]+)", cf))

    def entity_keys(fname: str) -> list:
        """The entity keys a platform declares.

        Names, not just a count: a ratchet that only knows "158" can say the
        surface grew but not WHAT grew, which is the one thing the person who
        grew it needs to hear.
        """
        p = ROOT / fname
        if not p.exists():
            return []
        return sorted(set(re.findall(r'key="([a-z0-9_]+)"', p.read_text())))

    def count_keys(fname: str) -> int:
        return len(entity_keys(fname))

    # Genuine duplication: the same field on two pages a user meets in ONE
    # pass. Everything else is the same question at a different moment.
    by_step = _declaring_steps(cf)
    genuine = {}
    for _field, _sts in by_step.items():
        _fams = {STEP_FAMILY.get(st, st) for st in _sts}
        _fams.discard(None)
        if len(_fams) > 1 and _field not in NOT_DUPLICATE:
            genuine[_field] = sorted(_sts)

    # A field the user meets on several pages reads as several settings.
    repeated = {k: n for k, n in fields.items() if n > 1}
    return {
        "config_fields": len(fields),
        "config_pages": len(steps),
        "field_declarations": len(decls),
        "repeated_fields": len(repeated),
        "worst_repeats": dict(Counter(repeated).most_common(8)),
        # The number that should drive the work — see STEP_FAMILY.
        "duplicate_fields": len(genuine),
        "duplicates": genuine,
        "number_entities": count_keys("number.py"),
        "switch_entities": count_keys("switch.py"),
        "user_facing_controls": len(fields) + count_keys("number.py") + count_keys("switch.py"),
        # The inventory the #830 ratchet compares against.
        "inventory": {
            "config_fields": sorted(fields),
            "number_entities": entity_keys("number.py"),
            "switch_entities": entity_keys("switch.py"),
        },
    }


def write_baseline(path: Path) -> dict:
    """Freeze today's inventory as the ceiling."""
    m = measure()
    payload = {
        "_comment": [
            "#830 shrink-only ratchet. Every entry is a decision SEM could not",
            "make for itself. ADDING one is a deliberate act that needs a",
            "reason; removing one is the point of the issue.",
            "Regenerate:  python3 scripts/audit_options.py --baseline",
        ],
        "total": m["user_facing_controls"],
        **m["inventory"],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def main() -> int:
    m = measure()
    if "--baseline" in sys.argv:
        out = ROOT / "tests" / "option_surface_baseline.json"
        p = write_baseline(out)
        print(f"wrote {out.relative_to(ROOT)} — {p['total']} controls")
        return 0
    if "--json" in sys.argv:
        print(json.dumps(m, indent=2))
        return 0
    print("SEM option surface")
    print(f"  config-flow fields        {m['config_fields']:4}  "
          f"(declared {m['field_declarations']}x across {m['config_pages']} pages)")
    print(f"  …declared on >1 step      {m['repeated_fields']:4}  "
          "— mostly lifecycle variants of one object")
    print(f"  …GENUINE duplicates       {m['duplicate_fields']:4}  "
          "— same field on two pages a user meets in one pass")
    print(f"  number entities           {m['number_entities']:4}")
    print(f"  switch entities           {m['switch_entities']:4}")
    print(f"  TOTAL user-facing controls{m['user_facing_controls']:4}")
    if m["duplicates"]:
        print("\n  genuine duplicates (a user can set these in two places):")
        for k, sts in sorted(m["duplicates"].items()):
            print(f"    {k}: {', '.join(sts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
