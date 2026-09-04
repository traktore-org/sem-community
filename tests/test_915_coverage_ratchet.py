"""#915 — the coverage ratchet: how many energy-shaped integrations can SEM
not even NAME?

`unnamed_over_floor` is the number this arc exists to move. It shrinks when
SEM learns a brand and grows only when the ecosystem does — and a refresh
commit has to say which. The number is computed from the COMMITTED roster,
never from the live network, so CI never depends on the internet and the
board can never go red on a day nobody touched the code.

Same shape as the other shrink-only ratchets in this repo
(`tests/brand_footprint_baseline.json`, `tests/option_surface_baseline.json`):
a shrink also fails, because a win that nobody records is a win nobody can
see.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASELINE = json.loads((ROOT / "tests" / "roster_coverage_baseline.json").read_text())


def _load(name: str, relpath: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


roster = _load("integration_roster", "consts/integration_roster.py")
crawler = _load("crawler", "scripts/crawl_integration_roster.py")


def _gap() -> list:
    return crawler.backlog(roster.ROSTER, roster.ROLE_VOCAB)


@pytest.mark.unit
class TestTheRatchet:
    def test_the_baseline_describes_the_committed_roster(self):
        assert BASELINE["roster_rows"] == len(roster.ROSTER)
        assert BASELINE["domains_with_roles"] == len(roster.ROLE_VOCAB)
        assert BASELINE["roles_mined"] == sum(
            len(v) for v in roster.ROLE_VOCAB.values())

    def test_the_unnamed_count_matches_the_roster(self):
        floor = BASELINE["install_floor"]
        live = sum(1 for row in _gap() if row[2] >= floor)
        assert live == BASELINE["unnamed_over_floor"], (
            f"the gap is {live}, the baseline says "
            f"{BASELINE['unnamed_over_floor']} — regenerate with "
            "`python3 scripts/crawl_integration_roster.py --refresh --baseline` "
            "and say in the commit whether SEM learned a brand or the "
            "ecosystem grew one"
        )

    def test_the_top_gap_is_still_unknown_to_sem(self):
        """Every domain the backlog names must genuinely be one SEM cannot
        place — if one of them became supported, the ratchet is stale."""
        known = crawler.sem_known_domains()
        still_unknown = [d for d in BASELINE["top_gap"] if d not in known]
        assert still_unknown == BASELINE["top_gap"], (
            f"{set(BASELINE['top_gap']) - set(still_unknown)} is supported now "
            "— regenerate the baseline, the ratchet shrank"
        )

    def test_the_backlog_is_not_a_roadmap(self):
        """It is developer output: a ranked question, never a promise. It is
        printed on demand and only the count is committed — there is no
        generated docs page for it."""
        assert not (ROOT / "docs" / "COVERAGE_BACKLOG.md").exists()
        assert "shrink-only" in " ".join(BASELINE["_comment"]).lower()


@pytest.mark.unit
class TestTheCrawlerNeverRunsInCI:
    def test_offline_is_the_default_for_every_reader(self):
        """Nothing in the test suite may reach the network. The crawler's
        network calls live behind `_get(..., offline=...)`, and every test
        here reads the committed artefact instead."""
        src = (ROOT / "scripts" / "crawl_integration_roster.py").read_text()
        assert "urlopen" in src, "premise: the crawler is the networked file"
        net = ("urlopen", "requests.", "aiohttp", "httpx")
        for path in ("tests/test_915_roster_rediscovery.py",
                     "tests/test_915_roster_is_not_a_claim.py"):
            text = (ROOT / path).read_text()
            assert not any(t in text for t in net), path
            assert "fetch_sources" not in text, path
