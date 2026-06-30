"""#528 — the Config card's STRUCTURAL_KEYS must mirror the backend.

The card stages entity-picker edits behind an Apply button ONLY for keys that
actually trigger an entry reload (the backend's _SET_OPTION_STRUCTURAL_KEYS).
If the card staged a key the backend treats as live, Apply would do nothing
visible (a silent "pending" that never reloads). Guard: every key the card
considers structural must be in the backend set.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_CARD = _ROOT / "dashboard" / "card" / "src" / "cards" / "sem-config-card.js"
_INIT = _ROOT / "__init__.py"


def _js_structural_keys() -> set[str]:
    src = _CARD.read_text(encoding="utf-8")
    m = re.search(r"const STRUCTURAL_KEYS = new Set\(\[(.*?)\]\)", src, re.S)
    assert m, "STRUCTURAL_KEYS Set literal not found in sem-config-card.js"
    return set(re.findall(r"'([^']+)'", m.group(1)))


def _py_structural_keys() -> set[str]:
    src = _INIT.read_text(encoding="utf-8")
    m = re.search(r"_SET_OPTION_STRUCTURAL_KEYS:[^=]*=\s*frozenset\(\{(.*?)\}\)", src, re.S)
    assert m, "_SET_OPTION_STRUCTURAL_KEYS frozenset literal not found in __init__.py"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def test_card_structural_keys_are_a_backend_subset():
    js = _js_structural_keys()
    py = _py_structural_keys()
    assert js, "card STRUCTURAL_KEYS is empty"
    extra = js - py
    assert not extra, (
        f"card stages keys the backend does NOT reload (Apply would no-op): {extra}. "
        "Add them to _SET_OPTION_STRUCTURAL_KEYS or remove from the card."
    )
