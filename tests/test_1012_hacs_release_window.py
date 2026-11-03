"""#1012 — a plain HACS install must always find a version to download.

HACS asks GitHub for one page of releases — thirty — and skips every
pre-release unless the user ticked "show beta versions". SEM cuts a beta per
fix, so once thirty betas stood above v2.0.0 the newest full release had
scrolled off that page. HACS had no version to offer, fell back to the branch
head's short commit sha, and — `hacs.json` declares `zip_release` — asked
GitHub for a release asset at a commit sha:

    Got status code 404 when trying to download
    .../releases/download/45438ef/solar_energy_management.zip

Nobody could install SEM for nine days. `scripts/hacs_release_window.py`
retires the oldest betas standing above the newest full release until it is
back inside the page. These tests pin what it picks, and what it must never
touch.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load():
    """Load the script by path — `scripts/` is not an importable package in
    the CI layout. Same approach as #855's baseline test."""
    spec = importlib.util.spec_from_file_location(
        "hacs_release_window", ROOT / "scripts" / "hacs_release_window.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


window = _load()


def _beta(number: int) -> dict:
    return {"tag_name": f"v2.1.0-beta.{number}", "prerelease": True,
            "draft": False, "created_at": f"2026-09-01T00:{number:02d}:00Z"}


def _full(name: str = "v2.0.0") -> dict:
    return {"tag_name": name, "prerelease": False, "draft": False,
            "created_at": "2026-08-29T14:43:05Z"}


def _feed(betas: int, *, full: bool = True) -> list[dict]:
    """Newest first, the order GitHub lists releases in."""
    feed = [_beta(n) for n in range(betas, 0, -1)]
    return feed + ([_full()] if full else [])


# --- the window itself ------------------------------------------------------

def test_the_guard_can_still_bite():
    """Keeping more betas than HACS reads would make the retire pointless."""
    assert window.KEEP < window.PAGE


def test_a_full_release_inside_the_page_is_installable():
    assert window.hacs_has_a_version(_feed(29))


def test_a_full_release_at_the_page_edge_is_not():
    """Index 30 is the first one off the page — this is the reported bug."""
    assert not window.hacs_has_a_version(_feed(30))


def test_betas_only_is_not_installable():
    assert not window.hacs_has_a_version(_feed(41, full=False))


# --- what gets retired -----------------------------------------------------

def test_a_healthy_window_is_left_alone():
    assert window.to_retire(_feed(window.KEEP)) == []


def test_the_reported_state_retires_the_oldest_betas():
    """41 betas above v2.0.0 — what the reporter's install hit. Enough go
    back to draft to seat the full release at KEEP, oldest first."""
    tags = window.to_retire(_feed(41))
    assert len(tags) == 41 - window.KEEP
    assert tags[0] == "v2.1.0-beta.1"
    assert tags[-1] == f"v2.1.0-beta.{41 - window.KEEP}"


def test_retiring_seats_the_full_release_at_keep():
    feed = _feed(41)
    retired = set(window.to_retire(feed))
    left = [r for r in feed if r["tag_name"] not in retired]
    assert window.full_release_index(left) == window.KEEP
    assert window.hacs_has_a_version(left)


def test_a_full_release_is_never_retired():
    feed = _feed(41)
    tags = window.to_retire(feed)
    assert "v2.0.0" not in tags
    assert all(
        r["prerelease"] for r in feed if r["tag_name"] in set(tags))


def test_betas_only_retires_nothing():
    """Retiring betas cannot conjure a full release, so it must not try —
    it would delete the whole history and still answer 404."""
    assert window.to_retire(_feed(41, full=False)) == []


def test_one_run_is_bounded():
    """A literal on purpose: a bound that reads its own constant cannot
    notice the constant being raised to a number that bounds nothing."""
    assert len(window.to_retire(_feed(500))) <= 60


def test_a_draft_takes_up_no_slot():
    """Drafts are hidden from every reader without write access, so they are
    not in HACS's page. Counting them would retire betas for nothing."""
    feed = [_beta(n) for n in range(41, 0, -1)]
    for release in feed[:20]:
        release["draft"] = True
    feed.append(_full())
    assert window.full_release_index(feed) == 21
    tags = window.to_retire(feed)
    assert len(tags) == 21 - window.KEEP      # 41 - KEEP if drafts counted
    assert tags[0] == "v2.1.0-beta.1"


def test_an_older_full_release_does_not_count():
    """Only the NEWEST full release matters — an ancient one is already off
    the page and cannot save the install."""
    feed = _feed(41) + [_full("v1.7.9")]
    assert window.full_release_index(feed) == 41


def test_the_oldest_goes_first_whatever_the_listed_order():
    """GitHub lists releases in an order of its own — two in this repo are
    listed against their creation order. Pick by date, so the release just
    published is provably the last one this could ever touch."""
    feed = _feed(41)
    feed[35], feed[5] = feed[5], feed[35]      # GitHub's order, not ours
    tags = window.to_retire(feed)
    assert tags[0] == "v2.1.0-beta.1"
    assert "v2.1.0-beta.41" not in tags


# --- the exit code, which is the only thing CI reads ------------------------

class _Fake:
    """Stands in for GitHub: one fetch, one retire, no network."""

    def __init__(self, feed):
        self.feed = feed
        self.retired = []

    def fetch(self):
        return list(self.feed)

    def retire(self, tag):
        self.retired.append(tag)
        self.feed[:] = [r for r in self.feed if r["tag_name"] != tag]
        return f"retired {tag}"


@pytest.fixture
def github(monkeypatch):
    def install(feed):
        fake = _Fake(feed)
        monkeypatch.setattr(window, "fetch_releases", fake.fetch)
        monkeypatch.setattr(window, "retire", fake.retire)
        return fake
    return install


def test_the_reported_state_ends_green(github):
    """41 betas above v2.0.0 — the reporter's install. One run retires, and
    the run only passes because a plain install works afterwards."""
    fake = github(_feed(41))
    assert window.main(["--retire"]) == 0
    assert len(fake.retired) == 41 - window.KEEP


def test_a_healthy_window_passes_without_touching_anything(github):
    fake = github(_feed(window.KEEP))
    assert window.main(["--retire"]) == 0
    assert fake.retired == []


def test_betas_only_fails_the_run(github):
    """Nothing to retire and nothing to offer — the job must go red, not
    quietly pass."""
    fake = github(_feed(41, full=False))
    assert window.main(["--retire"]) == 1
    assert fake.retired == []


def test_a_dry_run_changes_nothing_and_still_reports_broken(github):
    fake = github(_feed(41))
    assert window.main(["--retire", "--dry-run"]) == 1
    assert fake.retired == []


def test_check_alone_fails_on_the_reported_state(github):
    github(_feed(41))
    assert window.main(["--check"]) == 1


def test_retiring_a_full_release_is_refused(monkeypatch):
    """The last guard before the only destructive call. It re-reads the
    release and stops if GitHub says it is not a pre-release."""
    monkeypatch.setattr(window, "release_by_tag", lambda tag: _full(tag))
    monkeypatch.setattr(window, "_gh", lambda *a: pytest.fail(
        "edited a full release"))
    with pytest.raises(SystemExit):
        window.retire("v2.0.0")


def test_an_already_retired_tag_is_left_alone(monkeypatch):
    """GitHub answers 404 for a draft's tag. That is done, not an error —
    two runs racing must not turn a release red."""
    monkeypatch.setattr(window, "release_by_tag", lambda tag: None)
    monkeypatch.setattr(window, "_gh", lambda *a: pytest.fail("edited it"))
    assert "already retired" in window.retire("v2.1.0-beta.1")


def test_the_fetch_reads_every_page(monkeypatch):
    """This script's own drafts stay in its view, so a one-page read would
    fill with them and then report no full release — #1012 inside the fix
    for #1012."""
    pages = {1: [_beta(n) for n in range(100, 0, -1)], 2: [_full()]}
    asked = []

    def fake_gh(*args):
        asked.append(args[-1])
        page = int(args[-1].rsplit("page=", 1)[1])
        import json as _json
        return _json.dumps(pages.get(page, []))

    monkeypatch.setattr(window, "_gh", fake_gh)
    monkeypatch.setattr(window, "repo", lambda: "owner/repo")
    releases = window.fetch_releases()
    assert len(asked) == 2
    assert window.full_release_index(releases) == 100


# --- the wiring ------------------------------------------------------------

@pytest.mark.parametrize("workflow", [
    "hacs-release-window.yml",   # every release cut with a user token
    "create-release.yml",        # the GITHUB_TOKEN path, which fires no event
])
def test_every_release_path_runs_the_retire(workflow):
    text = (ROOT / ".github" / "workflows" / workflow).read_text()
    assert "scripts/hacs_release_window.py --retire" in text


def test_the_release_event_triggers_it():
    spec = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "hacs-release-window.yml").read_text())
    triggers = spec.get("on", spec.get(True))   # YAML 1.1 reads `on:` as True
    assert "published" in triggers["release"]["types"]


def test_the_window_matters_because_of_zip_release():
    """Without `zip_release` a missing version reads differently. This pins
    the premise the script's reasoning rests on."""
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert hacs["zip_release"] is True
    assert hacs["filename"] == "solar_energy_management.zip"


# --- the owner's view: old drafts are purged, fresh ones and full ones kept --

def _draft(name, created, prerelease=True):
    return {"tag_name": name, "id": hash(name) & 0xFFFF, "draft": True,
            "prerelease": prerelease, "created_at": created}


def test_old_beta_drafts_are_purged():
    feed = [_draft("v2.1.0-beta.30", "2026-09-18T17:17:00Z"),
            _draft("v2.2.0-beta.19", "2026-10-15T19:46:00Z")]
    out = window.drafts_to_purge(feed, "2026-11-03T18:00:00Z")
    assert [r["tag_name"] for r in out] == ["v2.1.0-beta.30", "v2.2.0-beta.19"]


def test_a_fresh_draft_is_left_alone():
    feed = [_draft("v2.3.0-beta.5", "2026-11-03T17:30:00Z")]
    assert window.drafts_to_purge(feed, "2026-11-03T18:00:00Z") == []


def test_a_draft_full_release_is_never_purged():
    feed = [_draft("v2.3.0", "2026-10-01T00:00:00Z", prerelease=False)]
    assert window.drafts_to_purge(feed, "2026-11-03T18:00:00Z") == []


def test_a_published_beta_is_not_a_draft_to_purge():
    feed = [{"tag_name": "v2.3.0-beta.4", "id": 1, "draft": False,
             "prerelease": True, "created_at": "2026-10-01T00:00:00Z"}]
    assert window.drafts_to_purge(feed, "2026-11-03T18:00:00Z") == []


def test_retire_deletes_and_never_drafts():
    """The owner's HACS reads drafts first; a retire must not make one."""
    import inspect
    src = inspect.getsource(window.retire)
    assert '"delete"' in src and "--draft" not in src
