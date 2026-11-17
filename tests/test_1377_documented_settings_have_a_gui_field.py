"""(#1377) A setting the docs tell the user to set has a field in the GUI.

The docs name option keys in backticks (`battery_charge_select_entity`).
Each such key that is a real option must be settable from the dashboard:
a field on the Configuration card, a SEM number/select/switch/time entity
that writes it, or it is listed in ``GUI_EXEMPT`` with the reason. SETUP_GUIDE
once said "set the charge switch in the Configuration tab" with no field (#1362).

Second pin: a key the card hides on a two-battery home must be declared in
``SINGLE_BATTERY_ONLY`` with its reason, so hiding one by accident fails.

Reading the card here means reading its field list, not asserting on text
of code: the helper below is the one declared parser of the card.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from custom_components.solar_energy_management.number import CONFIG_KEY_MAP

ROOT = Path(__file__).resolve().parent.parent
DOC_FILES = ("README.md", "docs/SETUP_GUIDE.md", "docs/USER_GUIDE.md",
             "docs/QUICK_START.md")
CARD = ROOT / "dashboard" / "card" / "src" / "cards" / "sem-config-card.js"
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

# Keys the card shows for ONE battery and not for several, with why.
SINGLE_BATTERY_ONLY = {
    "battery_force_discharge_control_entity": "replaced by one picker per battery (battery_force_discharge_entities)",
    "battery_strategy_control_entity": "replaced by one picker per battery (battery_strategy_entities)",
    "battery_strategy_active_value": "GAP: shown only beside the single strategy select; none on two batteries",
    "battery_strategy_idle_value": "GAP: shown only beside the single strategy select; none on two batteries",
    "battery_strategy_self_consume_value": "GAP: shown only beside the single strategy select; none on two batteries",
    "battery_strategy_off_value": "GAP: shown only beside the single strategy select; none on two batteries",
    "battery_force_charge_switch": "#1377: a stop by one pack puts it back while another still charges",
    "battery_target_soc_entity": "#1377: same shared target; one pack's stop undoes the other's charge",
}

# the first 160 characters after a render call hold its key, which may be the
# 1st-3rd argument (_renderPickerNested(idx, cid, 'key', ...),
# _renderStepper('number.x', 'key')); only quoted words that are real option
# keys count, so labels and domains are ignored.
_RENDER_CALL = re.compile(r"_render\w+\(([^\n]{0,160}(?:\n[^\n]{0,160})?)")
_QUOTED = re.compile(r"'([a-z][a-z0-9_]+)'")
_OPT_ID = re.compile(r"'opt:([a-z][a-z0-9_]+)'")
# number.py pairs each per-charger entity with the option key it writes:
# ``), "ev_target_soc", full_config.get(...)``
_ENTITY_KEY = re.compile(
    r'key=f?"(?:charger_\{cid\}_)?([a-z][a-z0-9_]+)"|\),\s*"([a-z][a-z0-9_]+)",\s*(?:full_config|charger_cfg)')


def _card_text() -> str:
    return CARD.read_text(encoding="utf-8")


_DOMAINS = {"number", "select", "switch", "sensor", "binary_sensor", "button",
            "input_number", "input_select", "input_boolean", "text", "time"}


def _render_keys(region: str, only_known: bool = True) -> set:
    found = set()
    for call in _RENDER_CALL.findall(region):
        found |= set(_QUOTED.findall(call))
    if only_known:
        return found & _known_keys()
    return {k for k in found if not k.startswith(("config_", "opt_"))} - _DOMAINS


def _card_keys() -> set:
    card_text = _card_text()
    return _render_keys(card_text) | (set(_OPT_ID.findall(card_text)) & _known_keys())


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


def _branch_keys(region: str) -> set:
    return _render_keys(region, only_known=False)


def _single_only_keys() -> set:
    """Keys the card renders only when there is one battery."""
    card_text = _card_text()
    start = card_text.index("const n = this._batteryCount();\n"
                            "                    if (n > 1) {")
    block = card_text[start:card_text.index("})()", start)]
    multi, _, single = block.partition("\n                    }\n")
    keys = _branch_keys(single) - _branch_keys(multi)
    fn = card_text[card_text.index("_renderBatteryChargeFields(opts, n) {"):]
    fn = fn[:fn.index("\n    }\n")]
    keys |= _branch_keys(fn.split("nothing) : html`", 1)[1])
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
