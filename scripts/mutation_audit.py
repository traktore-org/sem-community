#!/usr/bin/env python3
"""(#925) Attack the guards. A test that cannot fail is not a test.

WHY
---
SEM has 9681 tests and, until 07.09.2026, no way to answer the only
question that matters about any of them: *if the bug came back, would this
notice?* #924 is what that costs — a guard shipped with its fix, green for
a month, and structurally incapable of seeing three sibling call sites
carrying the defect it was written for.

Reviewing a guard cannot answer it. Running the suite cannot answer it.
The only way is to break the code and watch: revert a fix, run its guard,
and require the guard to FAIL. A guard that stays green over a reverted
fix is decorative, and decorative guards are worse than none — they spend
the credibility of the ones that work.

Run ad hoc on 07.09 over twelve fixes; every one bit, five so hard the
test could not import the constant its fix introduced. This makes that
routine instead of heroic.

USAGE
-----
    scripts/mutation_audit.py --issue 924
    scripts/mutation_audit.py --since 2026-08-24        # every bugfix since
    scripts/mutation_audit.py --commit e8c83e23 --tests test_920_....py

WHAT THE VERDICTS MEAN
----------------------
    GUARD-BITES        assertions fired, or the guard could not even import
                       the symbol the fix added. Load-bearing.
    GUARD-SILENT       the fix was reverted and nothing failed. A FINDING.
    INVALID-MUTATION   the revert left the tree unparseable, so nothing ran.
                       NOT a verdict — the harness earned this one the hard
                       way, by reporting five load-bearing fixes as silent
                       when a conflicted revert had left `<<<<<<< HEAD` in
                       the source and no test had executed at all.
    NO-SOURCE          the fix touched no production python (docs, tests).
    NO-BASELINE        the guard is not green on develop to begin with, so
                       breaking the code proves nothing about it.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PKG = "custom_components/solar_energy_management"


#: The suite needs 3.12+ (the `type` statement) and must import the package
#: through its namespaced path, so PYTHONPATH is not optional. Omitting it
#: made every guard "pass" by failing to import — this script's own first
#: run reported #924 and #910 as decorative, both of which had been proven
#: load-bearing by hand an hour earlier. Which is the joke: the mutation
#: harness reproduced, in itself, the exact defect class it exists to find.
PYTHON = shutil.which("python3.12") or sys.executable


def sh(cmd, cwd=None, check=False, env=None):
    r = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str),
                       capture_output=True, text=True, env=env)
    if check and r.returncode:
        raise RuntimeError(f"{cmd}\n{r.stderr[:400]}")
    return r


def _pytest(runroot: Path, paths: list) -> str:
    import os
    env = dict(os.environ, PYTHONPATH=str(runroot))
    return sh([PYTHON, "-m", "pytest", *paths, "-q", "-p", "no:randomly"],
              cwd=runroot, env=env).stdout


def fix_commits(issue: str) -> list:
    """Every conventional reference to this issue, oldest first.

    Oldest-first and ALL of them, because reverting only the newest can
    revert a follow-up while the main fix stands — which is exactly how
    #854 was first reported as a silent guard when it bites hard.
    """
    pat = rf"^(fix|feat|perf)\([^)]*#{issue}([^0-9]|$)"
    r = sh(["git", "log", "origin/develop", "--format=%h", "-E", "-i",
            f"--grep={pat}", f"--grep=(Fixes|Refs) #{issue}\\b", "--reverse"],
           cwd=REPO)
    return [c for c in r.stdout.split() if c]


def guards_for(issue: str) -> list:
    """Test files that name this issue — filename first, then content.

    Python only, and that is a KNOWN limit rather than an oversight: #903
    is a card fix whose guard is ``dashboard/card/test/soc-display.test.js``,
    run by a separate `node --test` job. This matcher cannot see it and
    reports NO-GUARD, which is honest — the guard exists and was verified
    by hand (reintroduce the 0% fallback, two JS tests fail). Mutating the
    JS side needs a second runner; until then NO-GUARD on a card fix means
    "not checked here", not "unguarded".
    """
    named = sorted(p.name for p in (REPO / "tests").glob(f"test_{issue}_*.py"))
    if named:
        return named
    r = sh(["grep", "-rlE", rf"#{issue}([^0-9]|$)", "tests/"], cwd=REPO)
    return sorted(Path(x).name for x in r.stdout.split()
                  if x.endswith(".py") and "__pycache__" not in x)


def mutate(issue: str, commits: list, tests: list) -> dict:
    if not commits:
        return {"issue": issue, "verdict": "NO-FIX", "detail": "-"}
    if not tests:
        js = list((REPO / "dashboard" / "card" / "test").glob("*.test.js"))
        hint = " (card fix? the JS suite is not mutated here)" if js and \
            any("dashboard/" in f for f in sh(
                ["git", "show", "--name-only", "--format=", commits[-1]],
                cwd=REPO).stdout.split()) else ""
        return {"issue": issue, "verdict": "NO-GUARD",
                "detail": f"{len(commits)} fix commit(s), no python test "
                          f"names it{hint}"}

    work = Path(tempfile.mkdtemp(prefix=f"sem-mut-{issue}-"))
    try:
        clone = work / "repo"
        sh(["git", "clone", "-q", "--no-hardlinks", str(REPO), str(clone)],
           check=True)
        sh(["git", "checkout", "-q", "develop"], cwd=clone)

        # Revert newest-first so earlier hunks still apply. Conflicts in
        # CHANGELOG/docs are noise — the source is what is being mutated.
        #
        # A CONFLICT IN SOURCE IS NOT NOISE, and the first version treated
        # it as such: it ran `git checkout --theirs .`, which does not
        # "resolve" a conflict so much as take one whole side of the file,
        # discarding every unrelated change in it. Reverting #897 that way
        # also removed #910's constant from consts/core.py, so the guard
        # could not import at all — and the tool called that GUARD-SILENT,
        # inventing a decorative guard that does not exist.
        #
        # So the two verdicts are NOT symmetric, and the tool must not
        # pretend they are. GUARD-BITES is positive evidence: the guard
        # failed, and it does not matter how tidy the mutation was.
        # GUARD-SILENT is an absence, and an absence only means something
        # when the mutation was CLEAN. A source conflict forfeits the
        # verdict rather than producing a finding.
        conflicted = []
        for c in reversed(commits):
            r = sh(["git", "revert", "--no-commit", "-n", c], cwd=clone)
            blob = (r.stdout or "") + (r.stderr or "")
            conflicted += [ln.split("in ", 1)[1].strip()
                           for ln in blob.splitlines()
                           if ln.startswith("CONFLICT") and " in " in ln]
            sh(["git", "checkout", "HEAD", "--",
                "tests/", "dashboard/", "CHANGELOG.md", "docs/"], cwd=clone)
            sh(["git", "checkout", "--theirs", "."], cwd=clone)
            sh(["git", "add", "-A"], cwd=clone)
        # prose conflicts are genuinely noise; source conflicts are not
        src_conflicts = sorted({f for f in conflicted if f.endswith(".py")})

        changed = [f for f in sh(["git", "diff", "--name-only", "HEAD", "--",
                                  "*.py"], cwd=clone).stdout.split()
                   if not f.startswith("tests/")]
        if not changed:
            return {"issue": issue, "verdict": "NO-SOURCE",
                    "detail": "revert changed no production python"}

        broken = []
        for f in changed:
            try:
                ast.parse((clone / f).read_text(encoding="utf-8"))
            except (SyntaxError, OSError):
                broken.append(f)
        if broken:
            return {"issue": issue, "verdict": "INVALID-MUTATION",
                    "detail": f"unparseable after revert: {broken[:3]}"}

        run = work / "run" / PKG
        run.mkdir(parents=True)
        paths = [f"{PKG}/tests/{t}" for t in tests]

        # BASELINE FIRST. A mutation verdict is meaningless unless the guard
        # was GREEN before the mutation: a guard that was already failing,
        # or that cannot be collected at all, would otherwise be reported as
        # "bites" (it failed!) or, worse, its collection error read as a
        # pass. Check the unmutated tree, then mutate the same clone.
        base = work / "base" / PKG
        base.mkdir(parents=True)
        sh(f"rsync -a --exclude=.git --exclude=node_modules "
           f"'{REPO}/' '{base}/'")
        base_out = _pytest(work / "base", paths)
        if not re.search(r"\d+ passed", base_out) or \
                re.search(r"\d+ (failed|errors?)", base_out):
            return {"issue": issue, "verdict": "NO-BASELINE",
                    "detail": "the guard is not green on develop — "
                              "nothing can be concluded from breaking it"}

        sh(f"rsync -a --exclude=.git --exclude=node_modules '{clone}/' '{run}/'")
        out = _pytest(work / "run", paths)

        if re.search(r"\d+ failed", out):
            n = re.search(r"(\d+) failed", out).group(1)
            return {"issue": issue, "verdict": "GUARD-BITES",
                    "detail": f"{n} assertion(s) fired over {len(changed)} file(s)"}
        m = re.search(r"cannot import name '([^']+)'", out)
        if m:
            return {"issue": issue, "verdict": "GUARD-BITES",
                    "detail": f"guard cannot load without '{m.group(1)}'"}
        if re.search(r"\d+ errors?", out):
            return {"issue": issue, "verdict": "INVALID-MUTATION",
                    "detail": "errored for a reason other than the fix"}
        if src_conflicts:
            return {"issue": issue, "verdict": "INVALID-MUTATION",
                    "detail": f"source conflicts, verdict forfeited: "
                              f"{src_conflicts[:3]}"}
        return {"issue": issue, "verdict": "GUARD-SILENT",
                "detail": f"reverted {len(changed)} file(s) cleanly; "
                          f"nothing failed"}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--issue", action="append", default=[])
    ap.add_argument("--since", help="audit every bug closed since YYYY-MM-DD")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    issues = list(a.issue)
    if a.since:
        r = sh(["gh", "issue", "list", "--state", "closed", "--label", "bug",
                "--limit", "60", "--search", f"closed:>={a.since}",
                "--json", "number", "--jq", ".[].number"], cwd=REPO)
        issues += r.stdout.split()
    if not issues:
        ap.error("give --issue N (repeatable) or --since YYYY-MM-DD")

    rows = [mutate(i, fix_commits(i), guards_for(i)) for i in issues]
    if a.json:
        print(json.dumps(rows, indent=2))
    else:
        print(f"{'issue':<8}{'verdict':<20}detail")
        print(f"{'-----':<8}{'-------':<20}------")
        for r in rows:
            print(f"#{r['issue']:<7}{r['verdict']:<20}{r['detail']}")
    silent = [r for r in rows if r["verdict"] == "GUARD-SILENT"]
    if silent:
        print(f"\n{len(silent)} DECORATIVE GUARD(S) — the fix was reverted "
              f"and the test stayed green: "
              f"{', '.join('#' + r['issue'] for r in silent)}")
    return 1 if silent else 0


if __name__ == "__main__":
    raise SystemExit(main())
