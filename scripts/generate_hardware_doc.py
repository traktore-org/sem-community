#!/usr/bin/env python3
"""#814 — render docs/SUPPORTED_HARDWARE.md from consts/hardware_matrix.py.

Run after editing the matrix:  python3 scripts/generate_hardware_doc.py
CI fails (tests/test_814_hardware_matrix.py) when the doc drifts from a
regeneration — the table is the truth, the doc is a view.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))

# Import the matrix without triggering the package __init__ (needs HA).
import importlib.util
spec = importlib.util.spec_from_file_location(
    "hardware_matrix", ROOT / "consts" / "hardware_matrix.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

BADGE = {"tested-live": "✅ tested live", "implemented": "🧩 implemented",
         "requested": "📥 requested"}
ORDER = {"tested-live": 0, "implemented": 1, "requested": 2}


def _sorted(rows):
    return sorted(rows, key=lambda r: (ORDER[r["status"]], r["brand"].lower()))


def render() -> str:
    out = []
    out.append("# Supported Hardware\n")
    out.append("> **Generated** from `consts/hardware_matrix.py` by "
               "`scripts/generate_hardware_doc.py` — edit the matrix, not "
               "this file. CI enforces it (#814, asked for in #806).\n")
    out.append("**What the status means:** ✅ *tested live* = confirmed on "
               "real hardware by a reporter or on the maintainers' own "
               "systems (the evidence column cites the source). 🧩 "
               "*implemented* = code and CI tests exist, or someone names "
               "the device without a confirmation we can point at — no "
               "live proof yet. 📥 *requested* = an open issue asks for "
               "it.\n")
    out.append("**Reading the evidence column:** `#NNN` is a GitHub issue, "
               "`disc. NNN` a Discussion, and the name in brackets is the "
               "person whose system it ran on — thank you, all of you. "
               "Everything marked ✅ traces back to one of those threads.\n")
    out.append("**Sign patterns** (grid × battery conventions) are the "
               "families verified in `tests/test_split_grid_integration.py`; "
               "`ED` rows are handled generically through the HA Energy "
               "Dashboard mapping with automatic sign detection.\n")

    out.append("\n## Solar inverters / battery systems\n")
    out.append("| Brand | Integration | Pattern | Discharge control | Status | Evidence |")
    out.append("|---|---|---|---|---|---|")
    for r in _sorted(hm.INVERTERS):
        out.append("| {brand} | `{integration}` | {pattern} | {dc} | {st} | {ev} |".format(
            brand=r["brand"], integration=r["integration"], pattern=r["pattern"],
            dc="yes" if r["discharge_control"] else "—",
            st=BADGE[r["status"]], ev=r["evidence"] or "—"))

    out.append("\n## EV chargers\n")
    # (#915) The integration column: a reader with an Alfen Eve used to find
    # "number entity" here and no way to learn WHICH Home Assistant
    # integration SEM detects it through. The domains come from the row, so
    # they cannot drift from what detection actually scans.
    out.append("| Brand | Integration | Control method | Status | Evidence |")
    out.append("|---|---|---|---|---|")
    for r in _sorted(hm.CHARGERS):
        doms = [d for d in [r.get("domain_token")] if d]
        doms += list(r.get("also_domains") or ())
        out.append("| {brand} | {dom} | {control} | {st} | {ev} |".format(
            brand=r["brand"],
            dom=" / ".join(f"`{d}`" for d in doms) or "—",
            control=r["control"],
            st=BADGE[r["status"]], ev=r["evidence"] or "—"))

    out.append("\n## Vehicles\n")
    out.append("SEM does not talk to the car — it charges *towards* the car's "
               "state of charge. A row here means that vehicle's HA "
               "integration has been wired in as SEM's SOC/range source on a "
               "real install.\n")
    out.append("| Vehicle | SOC / range source | Status | Evidence |")
    out.append("|---|---|---|---|")
    for r in _sorted(hm.VEHICLES):
        out.append("| {brand} | {src} | {st} | {ev} |".format(
            brand=r["brand"], src=r["soc_source"],
            st=BADGE[r["status"]], ev=r["evidence"] or "—"))

    out.append("\n## Heat pumps, hot water, loads and meters\n")
    out.append("Everything else SEM reads or switches: the SG-Ready and "
               "hot-water path, metered loads, and the meter that supplies "
               "the grid signal when it does not come from the inverter.\n")
    out.append("| Device | Role | Integration | Status | Evidence |")
    out.append("|---|---|---|---|---|")
    for r in _sorted(hm.OTHER_DEVICES):
        out.append("| {brand} | {role} | `{integration}` | {st} | {ev} |".format(
            brand=r["brand"], role=r["role"], integration=r["integration"],
            st=BADGE[r["status"]], ev=r["evidence"] or "—"))

    out.append("\n## Upgrading a row to *tested live*\n")
    out.append("Run SEM with your hardware and tell us what happened — an "
               "issue with your brand, the config-flow result and a note "
               "that the first cycles worked is enough. Every confirmation "
               "is cited here.\n")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    target = ROOT / "docs" / "SUPPORTED_HARDWARE.md"
    target.write_text(render(), encoding="utf-8")
    print(f"wrote {target} ({len(render())} bytes)")
