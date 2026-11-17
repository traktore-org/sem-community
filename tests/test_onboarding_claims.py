"""(#1371) The first-run docs make claims. Pin them so they cannot drift.

A new user reads README and QUICK_START in order and then acts. Each claim
below is one a new user acts on: the Energy Dashboard is not required, SEM
starts watch-only and says how to switch that off, and no HACS card is
required. The default is read from code, not typed into the test.
"""
from __future__ import annotations

import re
from pathlib import Path

from custom_components.solar_energy_management.consts.core import (
    DEFAULT_OBSERVER_MODE,
)

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
QUICK_START = (ROOT / "docs" / "QUICK_START.md").read_text(encoding="utf-8")
SETUP_GUIDE = (ROOT / "docs" / "SETUP_GUIDE.md").read_text(encoding="utf-8")
DOCS = {
    "README.md": README,
    "docs/QUICK_START.md": QUICK_START,
    "docs/SETUP_GUIDE.md": SETUP_GUIDE,
}

SWITCH = "switch.sem_observer_mode"
CARDS = ("card-mod", "mushroom", "apexcharts")

# A line that says the Energy Dashboard must come first or is required.
# "No Energy Dashboard required" and "not required" are the allowed forms.
_DASHBOARD_REQUIRED = re.compile(
    r"Energy Dashboard[^.\n]{0,60}\b(required|first)\b", re.IGNORECASE)
_DASHBOARD_NOT_REQUIRED = re.compile(
    r"\b(no|not|no longer)\b[^.\n]{0,20}Energy Dashboard"
    r"|Energy Dashboard[^.\n]{0,20}\bnot required",
    re.IGNORECASE)


def test_readme_does_not_require_energy_dashboard():
    """The wizard falls through to sources when the dashboard is empty."""
    offenders = [
        line for line in README.splitlines()
        if _DASHBOARD_REQUIRED.search(line)
        and not _DASHBOARD_NOT_REQUIRED.search(line)
    ]
    assert offenders == [], offenders
    assert "asks you to set up the Energy Dashboard first" not in README


def test_quick_start_does_not_require_energy_dashboard():
    offenders = [
        line for line in QUICK_START.splitlines()
        if _DASHBOARD_REQUIRED.search(line)
        and not _DASHBOARD_NOT_REQUIRED.search(line)
    ]
    assert offenders == [], offenders


def test_readme_and_quick_start_say_watch_only_and_how_to_switch_off():
    for name in ("README.md", "docs/QUICK_START.md"):
        text = DOCS[name]
        assert "watch-only" in text.lower(), name
        assert SWITCH in text, name
        assert re.search(r"\boff\b", text, re.IGNORECASE), name


def test_watch_only_is_the_default_the_docs_describe():
    """Docs say the switch is ON for a new install; code must agree."""
    assert DEFAULT_OBSERVER_MODE is True
    assert "new install" in README.lower() or "new installs" in README
    assert "new installs" in QUICK_START


def test_no_doc_lists_required_hacs_cards():
    """Cards are bundled. A doc that names one as required is stale."""
    for name, text in DOCS.items():
        for line in text.splitlines():
            low = line.lower()
            for card in CARDS:
                if card not in low:
                    continue
                assert "required" not in low or re.search(
                    r"not required|no hacs|no extra|no .* required",
                    low), (name, line)


def test_setup_guide_forecast_is_optional():
    line = next(
        ln for ln in SETUP_GUIDE.splitlines()
        if ln.startswith("**Solar forecasts (optional)")
    )
    assert "Required" not in SETUP_GUIDE[
        SETUP_GUIDE.index(line):SETUP_GUIDE.index(line) + 300]
    assert "SEM installs without one" in SETUP_GUIDE


def test_readme_start_path_is_ten_numbered_steps():
    start = README.index("## Getting Started")
    end = README.index("\n---", start)
    steps = re.findall(r"^(\d+)\. ", README[start:end], flags=re.M)
    assert steps == [str(n) for n in range(1, 11)], steps


def test_charger_is_not_in_the_wizard_claim():
    """The charger is added after install, not in the wizard."""
    assert "does not ask for it" in README
    assert "not** in the setup wizard" in QUICK_START
