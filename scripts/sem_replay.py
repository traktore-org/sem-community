#!/usr/bin/env python3
"""sem-replay (#1083) — replay real recorded days through a branch and its base.

    scripts/sem_replay.py --branch /home/sem/sem-1104 \\
        --corpus ~/sem-replay-corpus --since 30 --report ~/claude-jobs/replay-fix-1104.json

Both trees replay the SAME days (picked by tag, gap days skipped unless
asked); each check says pass/fail per day; a branch is refused when an
``exact`` check fails, or a ``relative`` check shows it worse than the
base, on any day that is not a gap day. Exit code 1 = refused.

The replay code itself always comes from THIS tree (it is laid over each
tree under test), so a branch older than the tool can still be replayed.
Offline, read-only, one day in memory at a time.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

TOOL_TREE = Path(__file__).resolve().parent.parent
PY = os.environ.get("SEM_PY", os.path.expanduser("~/.venvs/sem-314/bin/python"))
LAYOUTS = Path(os.environ.get("SEM_REPLAY_LAYOUTS",
                              os.path.expanduser("~/claude-jobs/replay-layouts")))
PKG = "custom_components/solar_energy_management"


def layout(tree: Path, name: str) -> Path:
    # one folder per tree: two replays of different branches never share
    import hashlib
    root = LAYOUTS / f"{name}-{hashlib.sha1(str(tree).encode()).hexdigest()[:8]}"
    dst = root / PKG
    dst.mkdir(parents=True, exist_ok=True)
    subprocess.run(["rsync", "-a", "--delete", "--exclude=.git", "--exclude=node_modules",
                    f"{tree}/", f"{dst}/"], check=True)
    subprocess.run(["rsync", "-a", "--delete", f"{TOOL_TREE}/tools/replay/",
                    f"{dst}/tools/replay/"], check=True)
    return root


#: per tree; a day takes ~0.2 s, so this is room for hundreds of days.
#: The autopilot runs this before a merge — a hang must not hold it up.
TREE_TIMEOUT_S = int(os.environ.get("SEM_REPLAY_TIMEOUT_S", "600"))


class ReplayTimeout(Exception):
    pass


def run_tree(root: Path, days: list) -> dict:
    out = {}
    try:
        proc = subprocess.run(
            [PY, "-m", f"{PKG.replace('/', '.')}.tools.replay.run_tree", *map(str, days)],
            cwd=root, env={**os.environ, "PYTHONPATH": str(root)},
            capture_output=True, text=True, timeout=TREE_TIMEOUT_S)
    except subprocess.TimeoutExpired as err:
        raise ReplayTimeout(f"replay timed out after {TREE_TIMEOUT_S} s in {root}") from err
    if proc.returncode != 0:
        raise SystemExit(f"replay failed in {root}:\n{proc.stderr[-3000:]}")
    for line in proc.stdout.splitlines():
        if line.startswith("{"):
            d = json.loads(line)
            out[d["date"]] = d
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--branch", required=True, type=Path)
    ap.add_argument("--base", type=Path, default=Path("/home/sem/sem-community"),
                    help="the tree to compare with (default: the develop checkout)")
    ap.add_argument("--corpus", type=Path, default=Path.home() / "sem-replay-corpus")
    ap.add_argument("--since", type=int, default=30, help="days back (pinned days always run)")
    ap.add_argument("--tags", default="", help="comma list, e.g. sunny or grey,car")
    ap.add_argument("--date", action="append", default=[])
    ap.add_argument("--include-gap", action="store_true")
    ap.add_argument("--report", type=Path)
    a = ap.parse_args()

    tool_root = layout(TOOL_TREE, "tool")
    sys.path.insert(0, str(tool_root))
    from custom_components.solar_energy_management.tools.replay import invariants as inv
    from custom_components.solar_energy_management.tools.replay.engine import DayRun
    from custom_components.solar_energy_management.tools.replay.recorded_day import corpus_days

    tags = [t for t in a.tags.split(",") if t]
    days = corpus_days(a.corpus.expanduser(), tags=tags, include_gap=a.include_gap,
                       dates=a.date)
    cutoff = (date.today() - timedelta(days=a.since)).isoformat()
    days = [p for p in days if "pinned" in p.parts or p.name[:10] >= cutoff or a.date]
    if not days:
        print("sem-replay: no days in the corpus match — nothing proven", file=sys.stderr)
        return 2

    try:
        branch = run_tree(layout(a.branch.resolve(), "branch"), days)
        base = run_tree(layout(a.base.resolve(), "base"), days) if a.base else {}
    except ReplayTimeout as err:
        # fail closed: a replay that did not finish proves nothing
        print(f"REFUSED: {err}")
        if a.report:
            a.report.expanduser().write_text(json.dumps(
                {"branch": str(a.branch), "base": str(a.base), "days": [],
                 "refused": True, "error": str(err)}, indent=1))
        return 1

    def _run(d):
        return DayRun(date=d["date"], tags=d["tags"], writes=d["writes"], notes=d["notes"],
                      home=[(t, s, None, False) for t, s in d["home"]],
                      forecast=[tuple(x) for x in d["forecast"]],
                      cost=tuple(d["cost"]) if d.get("cost") else None)

    report = {"branch": str(a.branch), "base": str(a.base), "days": [], "refused": False}
    lines = []
    for day in sorted(branch):
        b = _run(branch[day])
        bb = _run(base[day]) if day in base else None
        res = inv.check(b, bb)
        base_res = inv.check(bb, None) if bb is not None else None
        block = inv.blocking(res, b.tags, base_res)

        def _mark(k, r, base_res=base_res, block=block):
            if r.ok:
                fixed = base_res is not None and k in base_res and not base_res[k].ok \
                    and r.kind == "exact"
                return f"{k} ✓{' FIXED vs base' if fixed else ''} {r.detail}"
            inherited = r not in block and base_res is not None and k in base_res \
                and not base_res[k].ok
            return f"{k} ✗{' (inherited from base)' if inherited else ''} {r.detail}"

        report["days"].append({
            "date": day, "tags": b.tags,
            "checks": {k: r.as_dict() for k, r in res.items()},
            "base": {k: r.as_dict() for k, r in (base_res or {}).items()},
            "blocking": [r.name for r in block]})
        report["refused"] |= bool(block)
        mark = "REFUSED" if block else "ok"
        lines.append(f"{day} [{','.join(b.tags) or '-'}] {mark}: " +
                     "; ".join(_mark(k, r) for k, r in res.items()))
    print("\n".join(lines))
    print(f"\n{len(branch)} days — {'REFUSED' if report['refused'] else 'all checks pass'}")
    if a.report:
        a.report.expanduser().write_text(json.dumps(report, indent=1))
    return 1 if report["refused"] else 0


if __name__ == "__main__":
    sys.exit(main())
