"""(#1304) A ratchet baseline may only be loosened on purpose, visibly.

Every shrink-only test compares the live count with its baseline file. That
alone does not bite: regenerating the file together with the feature is the
pass, and the option surface went 158 → 221 that way. This guard adds the
second half of the rule — the baseline in the working tree may not be larger
than the one SEM already ships, unless the loosening is declared.

Reference: ``origin/develop`` (or ``develop``); on develop itself, the newest
``v*`` tag, so growth since the last beta still needs a declaration. No git,
no reference → the test is skipped with a message, never failed.

Declaration: a line in ``tests/<baseline>.loosen``::

    # RATCHET-LOOSENED: #1234 to=225 — why this control has to exist

``to=`` must equal the new count, so an old declaration never covers a new
growth, and the issue must be named in the newest commit that touched the
baseline (an uncommitted change is accepted on the declaration alone; CI
sees it committed).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable

import pytest

LOOSEN_TAG = "# RATCHET-LOOSENED:"
_DECL = re.compile(r"#\s*RATCHET-LOOSENED:\s*#(\d+)\s+to=(\d+)")
_ISSUE = re.compile(r"#(\d{2,5})\b")
ROOT = Path(__file__).resolve().parent.parent


def _repo() -> Path:
    """The git checkout that holds tests/. CI copies the checkout (with .git)
    into the HA layout; semtest rsyncs it without .git, so fall back to the
    source tree it was copied from."""
    if (ROOT / ".git").exists():
        return ROOT
    for var in ("GITHUB_WORKSPACE", "SEM_SRC"):
        p = os.environ.get(var)
        if p and (Path(p) / ".git").exists():
            return Path(p)
    for parent in ROOT.parents:
        if (parent / ".git").exists():
            return parent
    return ROOT


def _git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=_repo(), capture_output=True,
                           text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _on_develop() -> bool:
    for ref in ("origin/develop", "develop"):
        head = _git("rev-parse", "HEAD")
        tip = _git("rev-parse", ref)
        if head and tip and head.strip() == tip.strip():
            return True
    return False


def reference(path: Path) -> tuple[str, str] | tuple[None, str]:
    """(text, ref) of the baseline SEM already ships, or (None, why not)."""
    rel = path.resolve().relative_to(ROOT).as_posix()
    refs = []
    if _on_develop():
        tag = _git("describe", "--tags", "--abbrev=0", "--match", "v*", "HEAD~1")
        if tag:
            refs.append(tag.strip())
    refs += ["origin/develop", "develop"]
    for ref in refs:
        text = _git("show", f"{ref}:{rel}")
        if text is not None:
            return text, ref
    return None, "no git reference (origin/develop, develop or a v* tag) holds %s" % rel


def declared(path: Path) -> dict[int, int]:
    """{issue: to} from the baseline's .loosen sidecar."""
    side = path.with_name(path.name + ".loosen")
    if not side.exists():
        return {}
    return {int(n): int(to) for n, to in _DECL.findall(side.read_text(encoding="utf-8"))}


def modified_in_worktree(path: Path) -> bool:
    rel = path.resolve().relative_to(ROOT).as_posix()
    out = _git("status", "--porcelain", "--", rel)
    return bool(out and out.strip())


def committed_issues(path: Path) -> set[int]:
    rel = path.resolve().relative_to(ROOT).as_posix()
    out = _git("log", "-1", "--format=%s%n%b", "--", rel) or ""
    return {int(n) for n in _ISSUE.findall(out)}


def assert_not_loosened(path: Path, measure: Callable[[dict], int], what: str) -> None:
    text, ref = reference(path)
    if text is None:
        pytest.skip(f"ratchet reference for {what} unavailable: {ref}")
    before = measure(json.loads(text))
    now = measure(json.loads(path.read_text(encoding="utf-8")))
    if now <= before:
        return
    side = path.name + ".loosen"
    how = (f"\nA baseline may only be loosened on purpose: add\n"
           f"    {LOOSEN_TAG} #NNN to={now} — why\n"
           f"to tests/{side} and name #NNN in the commit that changes the baseline.")
    decl = declared(path)
    covering = {n for n, to in decl.items() if to == now}
    assert covering, (
        f"the {what} baseline grew {before} → {now} since {ref} "
        f"with no declaration." + how)
    if modified_in_worktree(path):
        return
    linked = covering & committed_issues(path)
    assert linked, (
        f"the {what} baseline grew {before} → {now} since {ref}; "
        f"tests/{side} declares {sorted(covering)} but the newest commit "
        f"touching the baseline names none of them." + how)
