"""Lint: no backticks inside HTML comments in card sources (#488).

The card sources are LitElement templates — giant ``html`` tagged
template literals. A backtick inside an HTML comment within such a
template legally TERMINATES the template literal; the remainder
re-parses as a tagged-template chain that is **syntactically valid
JS** (rollup, node --check, and CI all pass) but throws
``TypeError: html(...) is not a function`` at render time, leaving the
card blank. Exactly this shipped in 26d4616 (RST-style
````_readWithHold```` in a comment) and blanked the system diagram on
TEST and PROD.

This is the FLEET-READ-style structural guard for the class: scan
every card source for backticks between ``<!--`` and ``-->``.
"""
import re
from pathlib import Path

CARD_SRC = Path(__file__).resolve().parent.parent / "dashboard" / "card" / "src"


def test_no_backticks_inside_html_comments():
    assert CARD_SRC.is_dir(), f"card src dir missing: {CARD_SRC}"
    offenders = []
    for path in sorted(CARD_SRC.rglob("*.js")):
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r"<!--.*?-->", src, re.S):
            if "`" in m.group(0):
                line = src[: m.start()].count("\n") + 1
                offenders.append(
                    f"{path.relative_to(CARD_SRC.parent.parent.parent)}:{line}: "
                    f"{m.group(0)[:80]!r}"
                )
    assert not offenders, (
        "Backtick inside an HTML comment in a lit template — this "
        "TERMINATES the template literal and the card renders blank "
        "at runtime while every syntax check stays green (#488):\n"
        + "\n".join(offenders)
    )
