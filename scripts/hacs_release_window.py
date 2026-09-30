#!/usr/bin/env python3
"""#1012 — keep a full release inside the window HACS reads.

HACS asks GitHub for ONE page of releases — thirty — and skips every
pre-release unless the user has ticked "show beta versions". SEM cuts a beta
per fix, so once thirty betas stood above v2.0.0 the newest full release had
scrolled off that page. HACS then had no version to offer: it fell back to the
branch head's short commit sha, and because `hacs.json` declares
`zip_release` it asked GitHub for a release asset at a commit sha. No release
lives at a commit sha, so every plain install answered 404 — reported
27.09.2026 with 41 betas standing above v2.0.0.

The rule kept here: **the newest full release must sit inside the first
``PAGE`` releases GitHub lists.** When it does not, the oldest betas above it
go back to draft until it sits at index ``KEEP``, which leaves ``PAGE - KEEP``
spare slots for the betas still to come.

A draft keeps its tag and its release notes, and
``gh release edit <tag> --draft=false`` puts one back. It does NOT keep its
download: GitHub serves a draft's assets only to people with write access, so
anyone pinned to a retired beta must move to a live one. That is the price of
the plain install working at all.

Only a pre-release is ever touched. A full release is never touched.

Usage::

    python3 scripts/hacs_release_window.py --check
    python3 scripts/hacs_release_window.py --retire [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

#: What HACS asks GitHub for. `get_releases()` in HACS calls the releases
#: endpoint with no page size, so it gets GitHub's default: one page of 30.
PAGE = 30

#: How many betas may stand above the newest full release after a retire.
#: The 20 spare slots are the warning time if a run ever fails — at the
#: measured beta rate, about twelve days. #1012 itself went unseen for nine.
KEEP = 10

#: (#1028) How many full releases stay listed. HACS's version picker shows
#: every listed release, stables and betas mixed; the three newest stables
#: are the ones a user may reasonably step back to.
KEEP_STABLE = 3
#: Refuse to retire more than this in one run — a runaway guard, not a
#: working limit.
MAX_PER_RUN = 50

#: Read every page. This script's own drafts stay in ITS view (a token with
#: write access sees drafts), so a one-page read would fill up with them and
#: then report "no full release" — #1012 again, in the fix for #1012.
MAX_PAGES = 20

_REPO: str | None = None


def repo() -> str:
    """The repository to work on: the one Actions says we are in, else the
    one the checkout points at. Never a hardcoded name — a clone or a fork
    running this must not reach into somebody else's releases."""
    global _REPO
    if _REPO is None:
        _REPO = os.environ.get("GITHUB_REPOSITORY") or _gh(
            "repo", "view", "--json", "nameWithOwner", "-q",
            ".nameWithOwner").strip()
    return _REPO


def listed(releases: list[dict]) -> list[dict]:
    """The releases a reader without write access sees — drafts are hidden
    from everybody else, so they take up no slot in HACS's page."""
    return [r for r in releases if not r.get("draft")]


def full_release_index(releases: list[dict]) -> int | None:
    """Where the newest full release sits in the list HACS reads, or None
    when there is no full release at all."""
    for index, release in enumerate(listed(releases)):
        if not release.get("prerelease"):
            return index
    return None


def hacs_has_a_version(releases: list[dict]) -> bool:
    """True when a plain HACS install can find a version to download."""
    index = full_release_index(releases)
    return index is not None and index < PAGE


def to_retire(releases: list[dict], keep: int = KEEP) -> list[str]:
    """Tags of the oldest betas standing above the newest full release —
    enough of them to bring it down to index ``keep``. Empty when the window
    is already wide enough, and empty when there is no full release to save
    (retiring betas cannot conjure one).

    Oldest by `created_at`, not by position: GitHub's order is its own, and
    two releases in this repo are listed against their creation order. Taking
    the oldest by date also proves the release just published is the LAST one
    this could ever pick, so a publish can never retire itself.
    """
    index = full_release_index(releases)
    if index is None:
        return []
    shown = listed(releases)
    newest_full = max((r.get("created_at") or "" for r in shown
                       if not r.get("prerelease")), default="")
    betas = [r for r in shown if r.get("prerelease")]
    # (#1028) A beta older than the newest full release is superseded: the
    # stable carries it. It only crowds the picker — betas and stables
    # mixed — so it goes, whatever the window's width.
    superseded = [r for r in betas if (r.get("created_at") or "") <= newest_full]
    current = sorted((r for r in betas if (r.get("created_at") or "") > newest_full),
                     key=lambda r: r.get("created_at") or "", reverse=True)
    # The line in progress keeps its newest ``keep``.
    crowding = current[keep:]
    oldest_first = sorted(superseded + crowding,
                          key=lambda r: r.get("created_at") or "")
    return [r["tag_name"] for r in oldest_first[:MAX_PER_RUN]]


def stale_stables(releases: list[dict], keep: int = KEEP_STABLE) -> list[str]:
    """(#1028) Full releases older than the newest ``keep`` — listed, they
    make the picker a history. Drafted like a beta: tag and notes stay.
    Never one of the newest ``keep``, never when there are fewer."""
    fulls = sorted((r for r in listed(releases) if not r.get("prerelease")),
                   key=lambda r: r.get("created_at") or "", reverse=True)
    stale = fulls[keep:]
    # Oldest first and bounded, like the betas: the daily run does the rest.
    return [r["tag_name"] for r in reversed(stale)][:MAX_PER_RUN]


def _gh(*args: str) -> str:
    """Run gh, and say what it said when it fails — a bare
    CalledProcessError prints the command and hides the reason."""
    done = subprocess.run(["gh", *args], capture_output=True, text=True)
    if done.returncode != 0:
        sys.stderr.write(done.stderr)
        raise SystemExit(f"gh {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def fetch_releases() -> list[dict]:
    """Every release, page by page. The `listed()` entries of this are the
    page HACS reads — same endpoint, same order — but this read also returns
    drafts, which HACS never sees."""
    releases: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        batch = json.loads(_gh(
            "api", f"repos/{repo()}/releases?per_page=100&page={page}"))
        releases += batch
        if len(batch) < 100:
            return releases
    raise SystemExit(
        f"more than {MAX_PAGES} pages of releases — raise MAX_PAGES rather "
        "than deciding from a partial list")


def release_by_tag(tag: str) -> dict | None:
    """The release GitHub still lists for this tag, or None when it lists
    none (it was retired already — drafts answer 404 here)."""
    done = subprocess.run(
        ["gh", "api", f"repos/{repo()}/releases/tags/{tag}"],
        capture_output=True, text=True)
    if done.returncode != 0:
        return None
    return json.loads(done.stdout)


def retire(tag: str, *, stale_stable: bool = False) -> str:
    """Send one release back to draft, after reading it again to be sure it
    is still a pre-release — or, with ``stale_stable``, a full release that
    ``stale_stables()`` named (never one of the newest KEEP_STABLE)."""
    release = release_by_tag(tag)
    if release is None:
        return f"{tag} is already retired"
    if not release.get("prerelease") and not stale_stable:
        raise SystemExit(f"refusing to retire {tag}: it is a full release")
    _gh("release", "edit", tag, "-R", repo(), "--draft=true")
    return f"retired {tag} — tag and notes kept, its zip is no longer public"


def _say(line: str) -> None:
    print(line)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _where(releases: list[dict]) -> str:
    index = full_release_index(releases)
    if index is None:
        return f"No full release in the {len(listed(releases))} GitHub lists."
    return f"Newest full release at index {index}; HACS reads {PAGE}."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="fail when HACS can see no version to install")
    parser.add_argument("--retire", action="store_true",
                        help="draft the oldest betas until the window fits")
    parser.add_argument("--dry-run", action="store_true",
                        help="with --retire: say what it would do")
    args = parser.parse_args(argv)
    if not (args.check or args.retire):
        parser.error("pass --check or --retire")

    releases = fetch_releases()
    _say(_where(releases))

    if args.retire:
        tags = to_retire(releases)
        old = stale_stables(releases)[:max(0, MAX_PER_RUN - len(tags))]
        if not tags and not old:
            _say("Nothing to retire.")
        for tag in tags:
            _say(f"would retire {tag}" if args.dry_run else retire(tag))
        for tag in old:
            _say(f"would retire old stable {tag}" if args.dry_run
                 else retire(tag, stale_stable=True))
        tags = tags + old
        if tags and not args.dry_run:
            releases = fetch_releases()
            _say(_where(releases))

    if hacs_has_a_version(releases):
        _say("A plain HACS install can find a version.")
        return 0
    if full_release_index(releases) is None:
        _say("HACS has nothing to offer at all. Cut a full release.")
    else:
        _say("Too many pre-releases stand above it, so a plain HACS install "
             "finds no version and answers 404. Retire some.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
