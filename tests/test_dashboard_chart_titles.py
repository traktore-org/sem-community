"""A chart's title says WHAT it plots; its subtitle says WHEN.

Found on PROD 30.08 by walking the live dashboard: the Home tab's chart
rendered "Last 7 Days" as BOTH title and subtitle, and the Energy tab's
promised "Self-Consumption — 30 Day Trend" above a chart the `energy`
preset fixes at `defaultPeriod: '7d'` — a title that described 30 days of
data over 7 days of bars.

`sem-chart-card` derives the subtitle from the preset's period, so a title
naming a period is at best duplication and at worst a false claim. This
pins both: no template chart title may name a period.
"""
from __future__ import annotations

import pathlib
import re

import pytest
import yaml

TEMPLATE = (pathlib.Path(__file__).resolve().parent.parent
            / "dashboard" / "sem_dashboard_template.yaml")

# "7 day", "30-day", "last 24h", "this week", "today" … in a chart TITLE.
PERIOD_IN_TITLE = re.compile(
    r"\b(\d+\s*[-–]?\s*day|last\s+\d|last\s+week|this\s+week|this\s+month|"
    r"24h|7d|30d|today|yesterday)\b", re.I)


def _chart_titles():
    """Every ``custom:sem-chart-card`` title in the template."""
    text = TEMPLATE.read_text()
    # The template carries Jinja; strip it so yaml can parse the structure.
    safe = re.sub(r"\{[%{].*?[%}]\}", "''", text, flags=re.S)
    try:
        docs = yaml.safe_load(safe)
    except yaml.YAMLError:
        docs = None
    out = []
    if docs:
        def walk(n):
            if isinstance(n, dict):
                if n.get("type") == "custom:sem-chart-card" and n.get("title"):
                    out.append(n["title"])
                for v in n.values():
                    walk(v)
            elif isinstance(n, list):
                for v in n:
                    walk(v)
        walk(docs)
    if not out:  # fall back to a line scan if the Jinja strip defeated yaml
        block = None
        for line in text.splitlines():
            if "custom:sem-chart-card" in line:
                block = True
            elif block and line.strip().startswith("title:"):
                out.append(line.split("title:", 1)[1].strip())
                block = None
            elif block and line.strip() and not line.strip().startswith("#"):
                if not line.strip().startswith(("preset:", "series:",
                                                "entity", "default_period:")):
                    block = None
    return out


def test_there_are_chart_titles_to_check():
    assert _chart_titles(), "the scan found no sem-chart-card titles — fix the scan"


@pytest.mark.parametrize("title", _chart_titles())
def test_a_chart_title_never_names_a_period(title):
    hit = PERIOD_IN_TITLE.search(title)
    assert not hit, (
        f"chart title {title!r} names a period ({hit.group(0)!r}). The card "
        "renders the period as its SUBTITLE from the preset, so a title "
        "naming one duplicates it — or contradicts it, as "
        "'Self-Consumption — 30 Day Trend' did over a 7-day preset on PROD."
    )
