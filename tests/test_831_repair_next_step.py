"""#831 — a repair card is the one moment SEM has the user's attention WITH
the context in hand. Today that context dies on the card: 1 of 15 repairs
sets learn_more_url, and the user reconstructs a GitHub form from memory.

Two kinds of repair, two kinds of next step (mixing them would flood the
tracker with user-side misconfigurations):

  * "your setup needs attention" → a TROUBLESHOOTING.md docs anchor;
  * "this looks like SEM's fault" → a bug-report form with the context
    already filled in (GitHub issue forms accept per-field prefill by id).

Both failsafe repairs deliberately go DOCS-side — their fix is a box setting
the card already names, not a SEM change (deviation from the issue's table,
flagged and approved at plan review).

Privacy is load-bearing: versions, repair key and reason travel; entity ids
and diagnostics NEVER do — URLs are logged by proxies and truncate ~8 KB.
Nothing is sent anywhere without the user pressing the button.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPAIR_ISSUES_PY = (
    Path(__file__).resolve().parent.parent / "coordinator" / "repair_issues.py"
)
TROUBLESHOOTING = Path(__file__).resolve().parent.parent / "docs" / "TROUBLESHOOTING.md"

DOCS_SIDE = {
    "split_grid_guessed",   # (#911) set the two grid power entities
    "battery_platform_pinned_generic",   # (#900) the wizard pinned it — docs say how to unpin
    "battery_operating_mode_unexpected",
    "sensor_unavailable", "sensor_stale", "no_forecast_integration",
    "no_recorder", "heat_pump_relay_unavailable", "hot_water_entity_unavailable",
    "hot_water_temperature_sensor_unavailable", "heat_pump_partial_sg_ready",
    "charger_control_entity_broken", "keba_failsafe_active",
    "charger_failsafe_suspected", "battery_force_discharge_unsupported",
    # (#872) The same raiser files a second, different story when the
    # evidence says the ENTITY is flaky rather than the device unable.
    "battery_force_discharge_entity_unstable",
    # (#877) The rebuild button's two ways of coming back short. Both are
    # "your setup needs attention" — a sensor to add, not a SEM bug.
    "battery_night_backfill_blocked",
    "battery_night_backfill_incomplete",
    # (#882) a load pointed at the wrong kind of entity — the fix is a
    # setting the card names, not a SEM change.
    "load_current_control_wrong_unit",
    "deye_system_work_mode_invalid",
    # (#896) the peak is somebody else's load — the next step is giving
    # SEM that load or raising the target, both settings, not a SEM bug.
    "load_shed_futile",
}
REPORT_SIDE = {
    "charger_actuation_failed", "charger_stop_unenforceable",
    "soc_cap_unenforceable",
}


def _raisers():
    tree = ast.parse(REPAIR_ISSUES_PY.read_text())
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name.startswith("raise_"):
            out[node.name] = ast.get_source_segment(
                REPAIR_ISSUES_PY.read_text(), node)
    return out


class TestEveryRaiserOffersANextStep:
    def test_every_raiser_passes_learn_more_url(self):
        missing = [n for n, src in _raisers().items()
                   if "learn_more_url" not in src]
        assert not missing, (
            f"{len(missing)} repair(s) still dead-end the user: "
            f"{sorted(missing)} (#831)"
        )

    def test_the_split_is_total_and_disjoint(self):
        keys = set()
        for src in _raisers().values():
            # (#872) findall, not search: a raiser may file more than one
            # story. One repair covering two faults — and asserting the
            # wrong one in its text — is exactly the defect Rien hit.
            keys.update(re.findall(r'translation_key=[^\n]*?"([a-z0-9_]+)"', src))
            keys.update(re.findall(r'_key = "([a-z0-9_]+)"', src))
        assert keys == DOCS_SIDE | REPORT_SIDE, (
            f"unclassified repair keys: {keys ^ (DOCS_SIDE | REPORT_SIDE)} — "
            "every repair needs a docs-or-report decision (#831)"
        )


class TestTheUrlBuilder:
    def _mod(self):
        from custom_components.solar_energy_management.coordinator import (
            repair_issues,
        )
        return repair_issues

    def test_report_url_carries_context_and_never_entities(self):
        url = self._mod().next_step_url(
            "report", "charger_stop_unenforceable",
            reason="no stop mechanism on this config",
            sem_version="2.1.0-beta.1", ha_version="2026.8.2",
            brand="KEBA P30",
        )
        assert "template=bug_report.yml" in url
        assert "sem-version=2.1.0-beta.1" in url
        assert "ha-version=2026.8.2" in url
        assert "charger_stop_unenforceable" in url
        assert "KEBA" in url
        assert "sensor." not in url and "binary_sensor." not in url

    def test_report_url_prefills_only_free_text_fields(self):
        """inverter/charger are DROPDOWNS — a prefill that does not exactly
        match an option renders empty and the report loses the brand. Brand
        rides the description instead."""
        url = self._mod().next_step_url(
            "report", "charger_actuation_failed", reason="x",
            sem_version="1", ha_version="2", brand="Wallbox Pulsar")
        assert "charger=" not in url and "inverter=" not in url

    def test_an_entity_id_passed_in_context_is_refused(self):
        url = self._mod().next_step_url(
            "report", "charger_actuation_failed",
            reason="write to number.keba_p30_charging_current failed",
            sem_version="1", ha_version="2")
        assert "number.keba" not in url, (
            "an entity id leaked into a logged URL (#831 privacy rule)"
        )

    def test_docs_url_is_an_anchor_into_troubleshooting(self):
        url = self._mod().next_step_url("docs", "sensor_stale")
        assert "docs/TROUBLESHOOTING.md#" in url

    def test_every_docs_anchor_resolves(self):
        """The #219 lesson shape: a deep link that 404s teaches the user the
        links are decoration."""
        text = TROUBLESHOOTING.read_text()
        # GitHub's slug rule: lowercase, punctuation REMOVED (apostrophes
        # vanish, they do not become dashes), spaces to dashes.
        def slug(h):
            h = h.strip("# ").strip().lower()
            h = re.sub(r"[^\w\- ]", "", h)
            return re.sub(r"\s+", "-", h)
        anchors = {slug(h) for h in re.findall(r"^#+ .+$", text, re.M)}
        for key in sorted(DOCS_SIDE):
            url = self._mod().next_step_url("docs", key)
            if "#" not in url:
                # a dedicated whole doc (KEBA) — existence is checked below
                assert url.endswith(".md"), url
                continue
            anchor = url.split("#", 1)[1]
            assert anchor in anchors, (
                f"docs anchor #{anchor} for {key} resolves to nothing in "
                f"TROUBLESHOOTING.md (#831)"
            )

    def test_dedicated_docs_exist(self):
        """A full-URL mapping must point at a file that exists in the repo."""
        mod = self._mod()
        root = TROUBLESHOOTING.parent.parent
        for key, target in mod._DOCS_ANCHORS.items():
            if target.startswith("http"):
                rel = target.split("/blob/develop/")[-1].split("/blob/main/")[-1]
                assert (root / rel).exists(), f"{key} → {target} (missing file)"


class TestTheCopyFlow:
    """The 'copy them in' half: one confirm step, context as selectable text,
    nothing sent anywhere, confirm dismisses."""

    def test_the_flow_shows_context_then_dismisses(self):
        import asyncio
        from unittest.mock import MagicMock
        from custom_components.solar_energy_management.repairs import (
            SEMContextCopyFlow,
        )
        flow = SEMContextCopyFlow({"copy_context": "Repair: x\nSEM: 1"})
        flow.hass = MagicMock()
        form = asyncio.run(flow.async_step_init())
        assert form["type"] == "form" and form["step_id"] == "confirm"
        assert form["description_placeholders"]["context"] == "Repair: x\nSEM: 1"
        done = asyncio.run(flow.async_step_confirm({}))
        assert done["type"] == "create_entry"

    def test_copy_context_scrubs_entity_ids(self):
        from custom_components.solar_energy_management.coordinator.repair_issues import (
            copy_context,
        )
        txt = copy_context("charger_actuation_failed",
                           reason="write to number.keba_p30_current failed",
                           brand="KEBA P30", sem_version="2.1", ha_version="2026.8")
        assert "number.keba" not in txt and "(entity)" in txt
        assert "KEBA P30" in txt and "2.1" in txt

    def test_only_report_side_repairs_are_fixable(self):
        src = REPAIR_ISSUES_PY.read_text()
        import re as _re
        for m in _re.finditer(
                r'is_fixable=True.*?translation_key="([a-z0-9_]+)"', src, _re.S):
            assert m.group(1) in REPORT_SIDE, (
                f"{m.group(1)} is fixable but not report-side — the copy flow "
                "is for SEM-fault repairs only (#831)"
            )
