"""#618 — the GUI's docs links can never rot silently again.

The Config card's section headers deep-link into the docs (the #605 help
system). Before this guard, four of twelve sections pointed at generic or
wrong anchors and nothing would ever notice a heading rename. This test
parses every ``docs:`` URL out of the card source and verifies the target
file exists and the anchor matches a real heading (GitHub slug rules).
Rename a heading the GUI links to → CI fails naming the link.
"""
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_CARD = _ROOT / "dashboard" / "card" / "src" / "cards" / "sem-config-card.js"
_BASE = "https://github.com/traktore-org/sem-community/blob/main/docs/"


def _github_slug(heading: str) -> str:
    h = heading.strip().lower()
    h = re.sub(r"[^\w\s-]", "", h)          # drop punctuation (GitHub rule)
    return re.sub(r"\s", "-", h)


def _doc_slugs(path: Path) -> set:
    slugs = set()
    for m in re.finditer(r"^#{1,6}\s+(.+)$", path.read_text(), re.M):
        slugs.add(_github_slug(m.group(1)))
    return slugs


# (#638 G4) every card that carries a docs deep-link is guarded, not just
# the config card — the overnight plan card links its actuation and
# arbitrage anchors, the load-priority goal editor its comfort anchor.
_EXTRA_CARDS = [
    _ROOT / "dashboard" / "card" / "src" / "cards" / "sem-energy-plan-card.js",
    _ROOT / "dashboard" / "card" / "src" / "cards" / "sem-load-priority-card.js",
]


def _card_doc_links():
    src = _CARD.read_text()
    links = re.findall(r"docs:\s*'([^']+)'", src)
    for card in _EXTRA_CARDS:
        links += re.findall(r"docs:\s*'([^']+)'", card.read_text())
    return links


@pytest.mark.unit
class TestGuiDocsAnchors:
    def test_links_found(self):
        links = _card_doc_links()
        assert len(links) >= 12, (
            f"only {len(links)} docs links found in sem-config-card.js — "
            "the SECTIONS help-link surface shrank unexpectedly"
        )

    def test_every_link_resolves(self):
        problems = []
        for url in _card_doc_links():
            assert url.startswith(_BASE), f"unexpected docs URL base: {url}"
            rest = url[len(_BASE):]
            fname, _, anchor = rest.partition("#")
            fpath = _ROOT / "docs" / fname
            if not fpath.is_file():
                problems.append(f"{url} → docs/{fname} does not exist")
                continue
            if anchor and anchor not in _doc_slugs(fpath):
                problems.append(
                    f"{url} → no heading in docs/{fname} slugs to '#{anchor}'"
                )
        assert not problems, (
            "GUI help links point at missing docs targets "
            "(a heading was renamed or a file moved without updating "
            "sem-config-card.js SECTIONS):\n  " + "\n  ".join(problems)
        )

    def test_no_generic_options_flow_links_remain(self):
        """#618 — the lazy '#5-options-flow' catch-all is retired; every
        section links to its dedicated docs section."""
        generic = [u for u in _card_doc_links() if u.endswith("#5-options-flow")]
        assert not generic, generic


@pytest.mark.unit
class TestEveryRelativeMarkdownLinkResolves672:
    """#672 — the general case of the guard above.

    The class above checks 12 links from one JS file. #672 was the same rot one
    level out: ``docs/USER_GUIDE.md`` was moved from the repo root into ``docs/``
    by #618, but its **relative** links were not rebased, so every one of them
    pointed a directory too deep. Four screenshots rendered as broken-image icons
    on GitHub and the ⭐ cross-reference the guide itself calls "the canonical
    reference" 404'd — in the most-read document in the repo, for weeks.

    Nothing caught it because a broken markdown link fails silently by
    construction: no build step reads it, CI does not resolve it, and a reader
    skims past a broken-image icon. Same family as #667 / #669 / #671 — a
    reference nobody resolves.

    Scope is deliberately every ``.md`` in the repo, not just ``docs/``: the
    other instance was in ``.github/ISSUE_TEMPLATE/``, which a docs-only scan
    would have missed.
    """

    # Historical, deliberately frozen. Dated design plans and superseded guides
    # record what was true when written; rebasing their links would falsify the
    # record. Everything else is live and must resolve.
    _SKIP_PARTS = {".git", "node_modules", "archive"}

    # Gitignored, local-only, and deliberately links out of the repo into the
    # developer's own notes. It is not in a CI checkout at all, so excluding it
    # keeps a local run honest rather than green-by-absence.
    _SKIP_FILES = {"CLAUDE.md"}

    def _markdown_files(self):
        return [
            p for p in _ROOT.rglob("*.md")
            if not self._SKIP_PARTS & set(p.relative_to(_ROOT).parts)
            and p.name not in self._SKIP_FILES
        ]

    def test_the_scan_sees_the_docs(self):
        """Bug class 8: an empty file list would make the check below pass
        vacuously, which is exactly the failure mode being guarded against."""
        files = self._markdown_files()
        assert len(files) > 30, f"only {len(files)} markdown files — scan broke"

    def test_every_relative_link_resolves(self):
        broken = {}
        for md in self._markdown_files():
            for target in re.findall(r"\]\(([^)#\s]+)\)", md.read_text(errors="ignore")):
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                if not (md.parent / target).resolve().exists():
                    broken.setdefault(str(md.relative_to(_ROOT)), []).append(target)
        assert not broken, (
            "markdown links that resolve to nothing:\n  "
            + "\n  ".join(f"{k}: {sorted(set(v))}" for k, v in sorted(broken.items()))
            + "\nA moved file needs its relative links rebased — #618 moved the "
            "guides into docs/ and #672 found four broken screenshots still "
            "linked as if from the repo root."
        )

    def test_the_rule_can_actually_fire(self):
        """Both directions: it must reject the real #672 shape and accept a
        real link, or it is a green light with nothing behind it."""
        guide = _ROOT / "docs" / "USER_GUIDE.md"
        assert guide.is_file(), "USER_GUIDE.md moved again — retarget this test"
        # The exact broken form: docs/-prefixed, from a file already in docs/.
        assert not (guide.parent / "docs/images/sem_home_tab.png").resolve().exists()
        # The corrected form.
        assert (guide.parent / "images/sem_home_tab.png").resolve().exists()


# ── (stable-prep 2026-08-01) the classes the original guard missed ──────────
#
# The pre-stable link sweep found 5 broken references CI never saw: anchor rot
# in RELATIVE markdown links (the guard only checked file existence), a broken
# HTML <img src> (not markdown-link syntax at all), and ISSUE_TEMPLATE
# ``?template=`` params pointing at renamed files. Three guards close those
# classes for good.

_DOCS_DIR = _ROOT / "docs"


def _md_files():
    # CLAUDE.md is gitignored local context — its links point at machine-local
    # paths outside the repo and must not gate CI.
    out = [p for p in _ROOT.glob("*.md") if p.name != "CLAUDE.md"]
    out += [p for p in _DOCS_DIR.rglob("*.md")]
    return out


@pytest.mark.unit
class TestRelativeDocLinks:
    def test_relative_markdown_anchors_resolve(self):
        """Every ``[text](path.md#anchor)`` and same-page ``(#anchor)`` link in
        every tracked markdown file must slug-match a real heading."""
        problems = []
        for md in _md_files():
            text = md.read_text(encoding="utf-8")
            # strip fenced code blocks — sample links inside them aren't real
            text = re.sub(r"```.*?```", "", text, flags=re.S)
            for m in re.finditer(r"\]\(([^)\s]+)\)", text):
                target = m.group(1)
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                path_part, _, anchor = target.partition("#")
                if path_part:
                    tpath = (md.parent / path_part).resolve()
                    if not tpath.exists():
                        problems.append(f"{md.relative_to(_ROOT)} → {target}: file missing")
                        continue
                    if anchor and tpath.suffix == ".md":
                        if anchor not in _doc_slugs(tpath):
                            problems.append(
                                f"{md.relative_to(_ROOT)} → {target}: no such heading")
                elif anchor:  # same-page link
                    if anchor not in _doc_slugs(md):
                        problems.append(
                            f"{md.relative_to(_ROOT)} → #{anchor}: no such heading")
        assert not problems, "broken relative doc links:\n  " + "\n  ".join(problems)

    def test_html_img_and_href_paths_resolve(self):
        """HTML <img src>/<a href> with relative paths — the syntax the
        markdown-link guard can't see (the broken USER_GUIDE logo class)."""
        problems = []
        for md in _md_files():
            text = md.read_text(encoding="utf-8")
            for m in re.finditer(r'(?:src|href)="([^"]+)"', text):
                target = m.group(1)
                if target.startswith(("http://", "https://", "mailto:", "#", "data:")):
                    continue
                if not (md.parent / target.partition("#")[0]).resolve().exists():
                    problems.append(f"{md.relative_to(_ROOT)} → {target}")
        assert not problems, "broken HTML src/href paths:\n  " + "\n  ".join(problems)


@pytest.mark.unit
class TestIssueTemplateReferences:
    def test_template_params_name_real_files(self):
        """GitHub's ``?template=`` must match a filename in ISSUE_TEMPLATE
        exactly — a rename silently degrades the link to a blank issue."""
        tdir = _ROOT / ".github" / "ISSUE_TEMPLATE"
        if not tdir.is_dir():
            pytest.skip("no ISSUE_TEMPLATE dir")
        real = {p.name for p in tdir.iterdir()}
        problems = []
        for f in tdir.glob("*.yml"):
            for m in re.finditer(r"template=([\w.\-]+)", f.read_text(encoding="utf-8")):
                if m.group(1) not in real:
                    problems.append(f"{f.name}: template={m.group(1)} (have: {sorted(real)})")
        assert not problems, "\n".join(problems)
