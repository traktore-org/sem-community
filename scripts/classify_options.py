#!/usr/bin/env python3
"""#830 step 2 — classify every config field by whether SEM could answer it.

**Every option is a decision SEM could not make for itself.** So the way to
shrink the surface is not to reorganise the menu, it is to work out which
decisions SEM can now make on its own — and SEM already owns three machines
that do exactly that: autodetection (#814), the learning layer (#755) and the
one plan (#638).

Four buckets:

``autodetected``  something already writes this key without asking. The field
                  is a fallback for when detection fails, and can be hidden
                  behind it rather than presented to everyone.
``flow_action``   not a setting at all — a choice made inside the flow, like
                  which charger to delete. Counting these inflates the number
                  a user is told they face.
``read``          consumed by the logic layer. A real decision, statically or
                  through a constructed key.
``unread``        declared and consumed by nothing. Retire on sight.

The dynamic-key handling is the part that matters. A first pass called twelve
phase-guard fields dead; all twelve are read through f-string keys in
``dual_phase_guard.py``. A classifier that cannot see those would recommend
deleting live configuration, so it looks for the constructed form too and says
which fields it could only match that way.

Run:  python3 scripts/classify_options.py [--json]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LOGIC_GLOBS = ("coordinator/**/*.py", "features/**/*.py", "devices/**/*.py",
               "tariff/**/*.py", "utils/**/*.py", "consts/**/*.py", "*.py",
               "dashboard/card/src/**/*.js")

#: Steps whose fields are decisions made INSIDE the flow, not stored settings.
FLOW_ACTIONS = {
    # which charger to delete — an action, gone the moment it is answered
    "charger_to_remove",
    # (#830) "show me the pickers anyway" on the detection confirmation. The
    # user answers it, so it counts toward the first-run number they feel; it
    # is never stored, so it is not a setting and cannot be "dead".
    "review_details",
}

#: Modules that ANSWER a config question rather than consume it. Only keys
#: these write count as "SEM already knows" — the whole point of the bucket is
#: fields a user need not be shown, and getting it wrong hides a real setting.
DETECTOR_SOURCES = (
    "coordinator/phase_current_discovery.py",
    "features/load_device_discovery.py",
    "features/device_registry.py",
    "coordinator/sensor_reader.py",
    "coordinator/forecast_reader.py",
    "detection.py",
    "coordinator/detection.py",
)


def _logic_blob() -> str:
    out = []
    for pat in LOGIC_GLOBS:
        for f in ROOT.glob(pat):
            if "/tests/" in str(f) or "node_modules" in str(f):
                continue
            if f.name == "config_flow.py":
                continue
            try:
                out.append(f.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                pass
    return "\n".join(out)


def _dynamic_pattern(field: str) -> re.Pattern:
    """Match a key built by interpolation, e.g. phase_guard_grid_l{n}_current.

    Any run of digits in the name is the part a loop varies, so it becomes a
    wildcard that also accepts an f-string placeholder.
    """
    parts = re.split(r"\d+", field)
    return re.compile(r"[\"']" + r"(?:\{[^}]*\}|\d+)".join(re.escape(p) for p in parts) + r"[\"']")


def classify() -> dict:
    cf = (ROOT / "config_flow.py").read_text()
    fields = sorted(set(re.findall(
        r'vol\.(?:Optional|Required)\(\s*["\']([a-z0-9_]+)["\']', cf)))
    blob = _logic_blob()

    # Keys a DETECTOR fills in without asking. Scoped to the modules that
    # actually detect, because "appears as a dict key somewhere" matches every
    # publish site and every defaults table — a first version of this scan
    # reported 42 autodetected fields including battery_capacity_kwh and
    # electricity_import_rate, which no machine can know. A wrong number here
    # would send the retirement work at settings that must stay.
    detect_blob = []
    for rel in DETECTOR_SOURCES:
        f = ROOT / rel
        if f.exists():
            detect_blob.append(f.read_text(encoding="utf-8"))
    detect_blob = "\n".join(detect_blob)
    written = set(re.findall(r'["\']([a-z0-9_]+)["\']\s*:', detect_blob))
    detected_dyn = [m.group(0) for m in re.finditer(
        r'f["\'][a-z0-9_]*\{[^}]*\}[a-z0-9_]*["\']\s*:', detect_blob)]

    out = {"autodetected": [], "flow_action": [], "read": [],
           "read_dynamically": [], "unread": []}
    for f in fields:
        if f in FLOW_ACTIONS:
            out["flow_action"].append(f)
            continue
        static = f'"{f}"' in blob or f"'{f}'" in blob
        dyn = bool(re.search(_dynamic_pattern(f), blob)) if re.search(r"\d", f) else False
        auto = f in written or (dyn and any(
            re.search(_dynamic_pattern(f), d) for d in detected_dyn))
        if auto:
            out["autodetected"].append(f)
        elif static:
            out["read"].append(f)
        elif dyn:
            out["read_dynamically"].append(f)
        else:
            out["unread"].append(f)
    out["total"] = len(fields)
    return out


def main() -> int:
    c = classify()
    if "--json" in sys.argv:
        print(json.dumps(c, indent=2))
        return 0
    print("SEM config fields — can SEM answer this itself?")
    print(f"  total                      {c['total']:4}")
    for k, label in (("autodetected", "already filled by SEM"),
                     ("flow_action", "not a setting (flow action)"),
                     ("read", "a real decision"),
                     ("read_dynamically", "read via a constructed key"),
                     ("unread", "READ BY NOTHING — retire")):
        print(f"  {k:<26} {len(c[k]):4}  — {label}")
    for k in ("autodetected", "unread", "flow_action"):
        if c[k]:
            print(f"\n  {k}:")
            for f in c[k]:
                print(f"    {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
