"""#1304 — a ratchet baseline may only be loosened on purpose.

The shrink-only tests compared live against the baseline file and nothing
else, so regenerating the file with the feature was the pass: the option
surface went 158 → 221 in 38 bumps. ``tests/ratchet_guard.py`` now also
compares the baseline with the one SEM ships; growth needs a declaration
with the exact new count and the issue in the commit.
"""
from __future__ import annotations

import json

import pytest

from custom_components.solar_energy_management.tests import ratchet_guard as rg

TOTAL = lambda d: d["total"]  # noqa: E731


def _baseline(tmp_path, total):
    p = tmp_path / "thing_baseline.json"
    p.write_text(json.dumps({"total": total}))
    return p


def _git_ref(monkeypatch, before):
    monkeypatch.setattr(rg, "reference",
                        lambda path: (json.dumps({"total": before}), "origin/develop"))


def test_no_growth_passes_without_a_word(tmp_path, monkeypatch):
    _git_ref(monkeypatch, 221)
    rg.assert_not_loosened(_baseline(tmp_path, 221), TOTAL, "thing")
    rg.assert_not_loosened(_baseline(tmp_path, 200), TOTAL, "thing")


def test_growth_without_a_declaration_fails_and_says_how(tmp_path, monkeypatch):
    _git_ref(monkeypatch, 221)
    with pytest.raises(AssertionError) as e:
        rg.assert_not_loosened(_baseline(tmp_path, 225), TOTAL, "thing")
    msg = str(e.value)
    assert "221 → 225" in msg and "to=225" in msg and "thing_baseline.json.loosen" in msg


def test_a_declaration_for_the_exact_count_passes_while_uncommitted(tmp_path, monkeypatch):
    _git_ref(monkeypatch, 221)
    p = _baseline(tmp_path, 225)
    (tmp_path / "thing_baseline.json.loosen").write_text(
        f"{rg.LOOSEN_TAG} #1300 to=225 — a sign lock the meter cannot carry\n")
    monkeypatch.setattr(rg, "modified_in_worktree", lambda path: True)
    rg.assert_not_loosened(p, TOTAL, "thing")


def test_an_old_declaration_does_not_cover_a_new_growth(tmp_path, monkeypatch):
    _git_ref(monkeypatch, 221)
    p = _baseline(tmp_path, 230)
    (tmp_path / "thing_baseline.json.loosen").write_text(
        f"{rg.LOOSEN_TAG} #1300 to=225 — last time\n")
    monkeypatch.setattr(rg, "modified_in_worktree", lambda path: True)
    with pytest.raises(AssertionError, match="no declaration"):
        rg.assert_not_loosened(p, TOTAL, "thing")


def test_a_committed_growth_needs_the_issue_in_the_commit(tmp_path, monkeypatch):
    _git_ref(monkeypatch, 221)
    p = _baseline(tmp_path, 225)
    (tmp_path / "thing_baseline.json.loosen").write_text(
        f"{rg.LOOSEN_TAG} #1300 to=225 — why\n")
    monkeypatch.setattr(rg, "modified_in_worktree", lambda path: False)
    monkeypatch.setattr(rg, "committed_issues", lambda path: {1299})
    with pytest.raises(AssertionError, match="names none"):
        rg.assert_not_loosened(p, TOTAL, "thing")
    monkeypatch.setattr(rg, "committed_issues", lambda path: {1300})
    rg.assert_not_loosened(p, TOTAL, "thing")


def test_no_git_reference_skips_with_a_message(tmp_path, monkeypatch):
    monkeypatch.setattr(rg, "reference", lambda path: (None, "no git here"))
    with pytest.raises(pytest.skip.Exception, match="no git here"):
        rg.assert_not_loosened(_baseline(tmp_path, 225), TOTAL, "thing")


def test_the_real_baselines_are_guarded():
    """Every shrink-only baseline is wired into the guard."""
    import re
    from pathlib import Path
    tests = Path(__file__).resolve().parent
    wired = set()
    for p in tests.glob("test_*.py"):
        if p.name == Path(__file__).name:
            continue
        for m in re.finditer(r"assert_not_loosened\(\s*([A-Z_]+)", p.read_text()):
            wired.add((p.name, m.group(1)))
    assert {n for n, _ in wired} >= {
        "test_830_option_surface_ratchet.py",
        "test_855_brand_footprint_ratchet.py",
        "test_855_brand_footprint_layers.py",
        "test_998_causal_claims_ratchet.py",
        "test_925_source_string_guards_shrink.py",
        "test_915_coverage_ratchet.py",
    }, wired
