"""(#1377) A setting the docs tell the user to set has a field in the GUI.

The docs name option keys in backticks (`battery_charge_select_entity`).
Each such key that is a real option must be settable from the SEM dashboard
(#1321: the one dashboard, its System and Devices screens): a field in the
card sources, a SEM number/select/switch/time entity that writes it, or it is
listed in ``GUI_EXEMPT`` with the reason. SETUP_GUIDE once said "set the
charge switch in the Configuration tab" with no field (#1362).

Second pin: the keys the System screen hides on a two-battery home are the
ones declared in ``SINGLE_BATTERY_ONLY`` with their reason, so hiding one by
accident fails.

Reading the sources here means reading their key lists: the helpers below are
the one declared parser. What the screens do with the keys is pinned by
``dashboard/card/test/next-system-settings.test.js``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from custom_components.solar_energy_management.number import CONFIG_KEY_MAP

ROOT = Path(__file__).resolve().parent.parent
DOC_FILES = ("README.md", "docs/SETUP_GUIDE.md", "docs/USER_GUIDE.md",
             "docs/QUICK_START.md")
CARD_SRC = ROOT / "dashboard" / "card" / "src"
SETTINGS = CARD_SRC / "util" / "next-settings.js"
ENTITY_FILES = ("number.py", "switch.py", "select.py", "time.py", "button.py")

# GUI-EXEMPT: key -> why it has no dashboard field. A key that gains a field
# fails the stale check below, so the table cannot rot.
GUI_EXEMPT = {
    "ev_charger_service": "options flow only: filled by the add-this-charger button (Detected hardware) or the flow",
    "ev_charger_service_entity_id": "options flow only: the target entity of a service-driven charger, auto-filled",
    "ev_charging_sensor": "options flow only: optional legacy charging flag, auto-filled at charger setup",
    "ev_current_sensor": "options flow only: optional amps readout, auto-filled at charger setup",
    "ev_total_energy_sensor": "options flow only: optional lifetime kWh readout, auto-filled at charger setup",
    "vehicle_range_entity": "options flow only: the user guide says so; no card picker yet",
}

# Keys the System screen shows for ONE battery and not for several, with why.
# (The four battery_strategy_*_value keys follow the single strategy select: set
# on one battery they show, on several there is no select to follow.)
SINGLE_BATTERY_ONLY = {
    "battery_force_discharge_control_entity": "replaced by one picker per battery (battery_force_discharge_entities)",
    "battery_strategy_control_entity": "replaced by one picker per battery (battery_strategy_entities)",
    "battery_force_charge_switch": "#1377: a stop by one pack puts it back while another still charges",
    "battery_target_soc_entity": "#1377: same shared target; one pack's stop undoes the other's charge",
}

# number.py pairs each per-charger entity with the option key it writes:
# ``), "ev_target_soc", full_config.get(...)``
_ENTITY_KEY = re.compile(
    r'key=f?"(?:charger_\{cid\}_)?([a-z][a-z0-9_]+)"|\),\s*"([a-z][a-z0-9_]+)",\s*(?:full_config|charger_cfg)')
# An option whose number entity has another name: the System screen binds the
# entity, so the entity id in the card sources is its field.
ENTITY_FIELD_OF = {"min_solar_power": "number.sem_minimum_solar_power"}
_QUOTED = re.compile(r"""['"`]([a-z][a-z0-9_]+)['"`]""")
# ``items.push(e('a'), e('b'))`` on the single-battery branch
_SINGLE_PUSH = re.compile(r"(?:if \(n < 2\)|else) items\.push\(([^;]*)\);")
_E_CALL = re.compile(r"\be\('([a-z][a-z0-9_]+)'\)")


def _source_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(CARD_SRC.rglob("*.js")))


def _card_keys() -> set:
    text = _source_text()
    named = {k for k, entity in ENTITY_FIELD_OF.items() if entity in text}
    return (set(_QUOTED.findall(text)) & _known_keys()) | named


def _entity_keys() -> set:
    keys = set()
    for name in ENTITY_FILES:
        for a, b in _ENTITY_KEY.findall((ROOT / name).read_text(encoding="utf-8")):
            keys |= {a or b}
    return keys | set(CONFIG_KEY_MAP.values())


def _option_keys() -> set:
    strings = json.loads((ROOT / "strings.json").read_text(encoding="utf-8"))
    keys = set()
    for block in ("config", "options"):
        for step in strings[block]["step"].values():
            keys |= set(step.get("data", {}))
    return keys


def _documented_keys() -> dict:
    options = _option_keys()
    found: dict = {}
    for name in DOC_FILES:
        text = (ROOT / name).read_text(encoding="utf-8")
        for key in set(re.findall(r"`([a-z][a-z0-9_]+)`", text)) & options:
            found.setdefault(key, []).append(name)
    return found


def _known_keys() -> set:
    return _option_keys() | {"battery_force_discharge_entities", "battery_strategy_entities"}


def _single_only_keys() -> set:
    """Keys the System screen draws only when there is one battery."""
    text = SETTINGS.read_text(encoding="utf-8")
    keys = set()
    for call in _SINGLE_PUSH.findall(text):
        keys |= set(_E_CALL.findall(call))
    return keys


class TestDocumentedSettingsHaveAField:

    def test_the_scan_finds_something(self):
        assert len(_documented_keys()) > 20, "docs scan matched almost nothing"
        assert len(_card_keys()) > 80, "card parser matched almost nothing"
        assert len(_entity_keys()) > 40, "entity parser matched almost nothing"

    def test_every_documented_option_has_a_gui_field(self):
        have = _card_keys() | _entity_keys()
        missing = {k: v for k, v in _documented_keys().items()
                   if k not in have and k not in GUI_EXEMPT}
        assert not missing, (
            "the docs name these options but no dashboard field sets them. "
            "Add a field, or list the key in GUI_EXEMPT with the reason:\n"
            + "\n".join(f"  {k}  (in {', '.join(v)})" for k, v in sorted(missing.items())))

    def test_no_exemption_is_stale(self):
        have = _card_keys() | _entity_keys()
        docs = _documented_keys()
        stale = [k for k in GUI_EXEMPT if k in have or k not in docs]
        assert not stale, f"drop from GUI_EXEMPT (now has a field or is undocumented): {stale}"


class TestTwoBatteryHomesKeepTheirFields:

    def test_hidden_on_two_batteries_means_declared(self):
        hidden = _single_only_keys()
        assert hidden, "parser found no single-battery keys; the card layout changed"
        assert hidden == set(SINGLE_BATTERY_ONLY), (
            "keys the card hides on a two-battery home differ from the table. "
            f"hidden but undeclared: {sorted(hidden - set(SINGLE_BATTERY_ONLY))}; "
            f"declared but shown: {sorted(set(SINGLE_BATTERY_ONLY) - hidden)}")

    def test_every_declaration_has_a_reason(self):
        assert all(len(r) > 15 for r in SINGLE_BATTERY_ONLY.values())
