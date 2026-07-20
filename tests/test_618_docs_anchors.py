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


def _card_doc_links():
    src = _CARD.read_text()
    return re.findall(r"docs:\s*'([^']+)'", src)


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
