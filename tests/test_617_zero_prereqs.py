"""#617 — zero required HACS cards.

Pins the three mechanical guarantees behind the "install SEM, done"
promise:

1. The template itself references NO retired HACS card (mushroom,
   apexcharts, card-mod) — the docs said "required" for two cards with
   zero uses and a card-mod whose absence allegedly blanked every tab.
2. The generator substitutes HA's native ``energy-sankey`` for
   ``custom:sankey-chart`` when the HACS card isn't installed (k-flow
   style optionality for the last genuinely load-bearing card).
3. The chart card loads Chart.js from SEM's own static path first (the
   CDN is only a fallback) — no undocumented internet dependency.
"""
import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.features.dashboard_generator import (
    DashboardGenerator,
)

_ROOT = Path(__file__).resolve().parents[1]


def _generator(tmp_path, sankey_dir: str | None = None):
    hass = MagicMock()
    hass.config.config_dir = str(tmp_path)
    if sankey_dir:
        (tmp_path / "www" / "community" / sankey_dir).mkdir(parents=True)

    def _executor(fn, *args):
        fut = asyncio.get_event_loop().create_future()
        fut.set_result(fn(*args))
        return fut

    hass.async_add_executor_job = _executor
    return DashboardGenerator(hass)


def _template():
    return {"views": [
        {"path": "energy", "cards": [
            {"type": "vertical-stack", "cards": [
                {"type": "custom:sankey-chart", "sections": ["s"], "height": 280},
            ]},
        ]},
    ]}


@pytest.mark.unit
class TestSankeyOptional:
    def test_replaced_with_native_when_not_installed(self, tmp_path):
        gen = _generator(tmp_path)
        tpl = _template()
        asyncio.get_event_loop().run_until_complete(
            gen._substitute_sankey_if_missing(tpl)
        )
        card = tpl["views"][0]["cards"][0]["cards"][0]
        assert card == {"type": "energy-sankey"}, card

    @pytest.mark.parametrize("dirname", ["sankey-chart", "ha-sankey-chart"])
    def test_kept_when_installed(self, tmp_path, dirname):
        gen = _generator(tmp_path, sankey_dir=dirname)
        tpl = _template()
        asyncio.get_event_loop().run_until_complete(
            gen._substitute_sankey_if_missing(tpl)
        )
        card = tpl["views"][0]["cards"][0]["cards"][0]
        assert card["type"] == "custom:sankey-chart"
        assert card["height"] == 280  # config untouched


@pytest.mark.unit
class TestTemplateHasNoRetiredCards:
    def test_no_retired_hacs_cards_in_template(self):
        body = (_ROOT / "dashboard" / "sem_dashboard_template.yaml").read_text()
        # Strip comment lines — the header documents the retirement.
        code = "\n".join(
            l for l in body.splitlines() if not l.lstrip().startswith("#")
        )
        for needle in ("custom:mushroom", "custom:apexcharts", "card_mod",
                       "glass_card", "custom:power-flow", "custom:bubble",
                       "custom:button-card", "custom:mini-graph"):
            assert needle not in code, (
                f"retired HACS dependency {needle!r} crept back into the "
                "dashboard template — #617 made the dashboard zero-prerequisite"
            )


@pytest.mark.unit
class TestChartJsVendored:
    def test_vendor_files_exist(self):
        vendor = _ROOT / "dashboard" / "card" / "vendor"
        for f in ("chart.umd.min.js", "chartjs-adapter-date-fns.bundle.min.js"):
            path = vendor / f
            assert path.is_file() and path.stat().st_size > 10_000, (
                f"vendored chart library missing: {f} — sem-chart-card would "
                "silently depend on the CDN again"
            )

    def test_chart_card_prefers_local_source(self):
        src = (_ROOT / "dashboard" / "card" / "src" / "cards" / "sem-chart-card.js").read_text()
        local = "/local/custom_components/solar_energy_management/dashboard/card/vendor/chart.umd.min.js"
        cdn = "https://cdn.jsdelivr.net/npm/chart.js"
        assert local in src and cdn in src
        assert src.index(local) < src.index(cdn), (
            "local vendored Chart.js must be tried BEFORE the CDN fallback"
        )
        # The built bundle must carry the same ordering.
        dist = (_ROOT / "dashboard" / "card" / "dist" / "sem-cards.js").read_text()
        assert local in dist, "bundle not rebuilt after the #617 loader change"
