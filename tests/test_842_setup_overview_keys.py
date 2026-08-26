"""#842 — the Setup overview could never tick four of its six rows.

@RienduPre: "Tarif & pricing seems not setup, but it is configured." He was
right and my first hypothesis was wrong: his tariff is a fully working
dynamic contract (provider `custom`, live prices, cheap windows). The fault
is in the overview's checklist, which tests OPTION KEYS THAT DO NOT EXIST.

Proven against PROD's own `get_config` payload (103 keys):

    electricity_rate    ABSENT   (the real key is electricity_import_rate)
    tariff_provider     ABSENT   (that is a SENSOR, never an option)
    tariff_entity       ABSENT   (the real key is dynamic_tariff_entity)
    hot_water_entity    ABSENT   (hot water reports through a binary sensor)
    has_battery         ABSENT   (the card already has _hasBattery())
    managed_devices     ABSENT   (load management has its own flag)

So `done` was permanently false for tariff, hot water, battery and loads —
on every install, however well configured. A checklist that cannot be
completed is worse than no checklist: it tells a correctly-set-up user they
did something wrong.

The guard below is the general fix: every option key the overview tests must
exist in the option surface. Runtime facts (sensors, helper methods) are
fine — they are simply not `opts.*`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARD = (ROOT / "dashboard" / "card" / "src" / "cards" / "sem-config-card.js").read_text()
BASELINE = json.loads((ROOT / "tests" / "option_surface_baseline.json").read_text())
REAL_KEYS = set(BASELINE["config_fields"])


def _done_conditions() -> list[tuple[str, str]]:
    """(row key, the done: expression) for every overview checklist row."""
    lines = CARD.split("\n")
    out, current = [], "?"
    for i, line in enumerate(lines):
        m = re.search(r"\{ key: '([a-z_]+)', labelKey:", line)
        if m:
            current = m.group(1)
        if line.strip().startswith("done:"):
            expr = " ".join(lines[i:i + 2])
            out.append((current, expr))
    return out


class TestTheChecklistCanActuallyBeCompleted:
    def test_every_option_key_it_tests_exists(self):
        bad = []
        for row, expr in _done_conditions():
            for key in re.findall(r"opts\.([a-z_0-9]+)", expr):
                if key not in REAL_KEYS:
                    bad.append(f"{row}: opts.{key}")
        assert not bad, (
            "Setup overview rows testing option keys that do not exist — the "
            f"row can never tick, on any install (#842): {sorted(bad)}"
        )

    def test_every_row_still_has_a_done_test(self):
        rows = dict(_done_conditions())
        assert set(rows) == {"energy", "ev", "hp", "hw", "tariff", "battery", "loads"}, rows

    def test_tariff_accepts_either_shape(self):
        """A tariff is configured by a static rate OR a dynamic price entity —
        the reporter has the dynamic one."""
        expr = dict(_done_conditions())["tariff"]
        assert "electricity_import_rate" in expr
        assert "dynamic_tariff_entity" in expr

    def test_battery_uses_the_helper_the_card_already_has(self):
        expr = dict(_done_conditions())["battery"]
        assert "_hasBattery()" in expr, (
            "the card already knows how to detect a battery — _hasBattery() "
            "checks the per-battery count and the SOC/power sensors"
        )

    def test_hot_water_and_devices_use_runtime_truth(self):
        rows = dict(_done_conditions())
        assert "_bin('hot_water_registered')" in rows["hw"]
        assert "load_management_enabled" in rows["loads"]
