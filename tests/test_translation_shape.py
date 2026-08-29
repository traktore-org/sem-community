"""Hassfest's translation rules, enforced locally.

Both rules below were broken by unreleased work on this branch and were caught
only when a PR finally ran CI — `feature/*` branches don't trigger the
workflows, so a direct merge to develop would have published the break. The
rules are cheap to check here, so CI should not be the first to know.

1. **An issue declares EITHER `description` OR `fix_flow`, never both.**
   HA treats them as an exclusion group: a fixable issue's text lives in its
   flow step, a non-fixable one's in its description. #831 added `fix_flow` to
   three issues that already had a `description`.

2. **No placeholder inside single quotes.** ICU message format treats `'` as
   an escape character, so `'{mode}'` does not render as the quoted value.
   Use typographic quotes.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FILES = [ROOT / "strings.json", *sorted((ROOT / "translations").glob("*.json"))]

# A placeholder wrapped in ASCII single quotes, e.g. '{mode}'.
QUOTED_PLACEHOLDER = re.compile(r"'\{[^}]+\}'")


def _ids(paths):
    return [p.name for p in paths]


@pytest.mark.parametrize("path", FILES, ids=_ids(FILES))
def test_issue_declares_description_or_fix_flow_but_not_both(path):
    issues = json.loads(path.read_text()).get("issues", {})
    both = [
        k for k, v in issues.items()
        if isinstance(v, dict) and "description" in v and "fix_flow" in v
    ]
    assert not both, (
        f"{path.name}: {both} declare both `description` and `fix_flow`. "
        "Hassfest rejects the pair — a fixable issue's text belongs in its "
        "flow step, so move the description there and drop it from the issue."
    )


@pytest.mark.parametrize("path", FILES, ids=_ids(FILES))
def test_no_placeholder_inside_single_quotes(path):
    offenders = []

    def walk(node, trail):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{trail}.{k}" if trail else k)
        elif isinstance(node, str):
            for hit in QUOTED_PLACEHOLDER.findall(node):
                offenders.append(f"{trail}: {hit}")

    walk(json.loads(path.read_text()), "")
    assert not offenders, (
        f"{path.name}: placeholders wrapped in ASCII single quotes — "
        + ", ".join(offenders[:6])
        + ". ICU reads `'` as an escape, so the value does not render. "
        "Use typographic quotes (“ ”) instead."
    )
