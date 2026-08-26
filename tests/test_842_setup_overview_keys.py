"""#842 — the Setup overview could never tick four of its six rows.

@RienduPre: "Tarif & pricing seems not setup, but it is configured." He was
right and my first hypothesis was wrong: his tariff is a fully working
dynamic contract (provider `custom`, live prices, cheap windows). The fault
is in the overview's checklist, which tests OPTION KEYS THAT DO NOT EXIST.

`get_config` returns ``{**entry.data, **entry.options}`` — nothing else. The
three rows #830 ADDED to the overview (beta.15) test keys that never enter
that dict:

    tariff   electricity_rate / tariff_provider / tariff_entity   exist nowhere
             (real: tariff_mode + dynamic_tariff_entity | electricity_import_rate)
    battery  has_battery      an Energy-Dashboard reader flag, never an option
    loads    managed_devices  exists nowhere

So those three rows were permanently unticked on every install, however
well configured — the reporter's dynamic tariff is exactly the case. The
four PRE-#830 rows were right all along: ``hot_water_entity`` is a real
set-option key (``_SET_OPTION_STRUCTURAL_KEYS``), not declared with
``vol.Optional`` — which is why a first draft of this guard, built on the
flow-declared baseline alone, wrongly called it phantom too. The guard now
counts BOTH sources as real.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARD = (ROOT / "dashboard" / "card" / "src" / "cards" / "sem-config-card.js").read_text()
BASELINE = json.loads((ROOT / "tests" / "option_surface_baseline.json").read_text())
INIT = (ROOT / "__init__.py").read_text()


def _set_option_keys() -> set[str]:
    """Keys the dashboard writes through set_option — real options that
    are NOT declared with vol.Optional in the flow (hot_water_entity …)."""
    out: set[str] = set()
    for m in re.finditer(r"_SET_OPTION_[A-Z_]+\s*(?::[^=]+)?=\s*frozenset\(\{(.*?)\}\)", INIT, re.S):
        out.update(re.findall(r'"([a-z0-9_]+)"', m.group(1)))
    return out


REAL_KEYS = set(BASELINE["config_fields"]) | _set_option_keys()


def _done_conditions() -> list[tuple[str, str]]:
    """(row key, the done: expression) for every overview checklist row."""
    lines = CARD.split("\n")
    out, current = [], "?"
    for i, line in enumerate(lines):
        m = re.search(r"\{ key: '([a-z_]+)', labelKey:", line)
        if m:
            current = m.group(1)
        if line.strip().startswith("done:"):
            # read to the row's closing "}," — the expression may span lines
            j = i
            while j < len(lines) and "}," not in lines[j] and "}" not in lines[j].rstrip()[-2:]:
                j += 1
            expr = " ".join(lines[i:j + 1])
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

    def test_tariff_is_mode_aware(self):
        """Dynamic mode is configured by the price entity, static by the
        rate — the reporter is dynamic. A loose 'either key' test would call
        a static install with a stale entity, or a dynamic one with a stale
        rate, configured."""
        expr = dict(_done_conditions())["tariff"]
        assert "tariff_mode" in expr
        assert "dynamic_tariff_entity" in expr
        assert "electricity_import_rate" in expr

    def test_battery_uses_the_helper_the_card_already_has(self):
        expr = dict(_done_conditions())["battery"]
        assert "_hasBattery()" in expr, (
            "the card already knows how to detect a battery — _hasBattery() "
            "checks the per-battery count and the SOC/power sensors"
        )

    def test_the_pre_830_rows_are_untouched_and_loads_uses_its_flag(self):
        rows = dict(_done_conditions())
        assert "opts.hot_water_entity" in rows["hw"], (
            "hot_water_entity is a real set-option key — the pre-#830 row was right"
        )
        assert "hot_water_entity" in _set_option_keys()
        assert "load_management_enabled" in rows["loads"]
