"""(#1321) The dashboard's card sources, read as one text.

The classic cards are gone; the SEM dashboard's screens and their util files
are the only place a setting can have a field. Tests that asked "does the card
name this key" ask this instead.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "dashboard" / "card" / "src"
TEMPLATE = ROOT / "dashboard" / "sem_next_template.yaml"


@lru_cache(maxsize=None)
def dashboard_src() -> str:
    """Every card and util source, concatenated."""
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(SRC.rglob("*.js")))


def dashboard_names(text: str) -> bool:
    return text in dashboard_src()
