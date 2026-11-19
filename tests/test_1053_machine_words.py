"""#1053 — a word SEM made for its code reached a person as text.

RienduPre's Dutch dashboard (2.2.0-beta.10) read "Netmodus: manual",
"Netteken (auto): normal", "custom · Normaal", "normal · 2", "2 (number)",
a chart legend "actual", and in the energy plan "ev_charger_1" and "battery"
where a name belongs. Each is a backend word printed as it is: the System
card mapped two of the six grid modes (``combined``/``split``) and showed the
four the backend added later (#461 ``manual``, #947 ``split-*``) raw; the
Control and Config cards printed four more sensors without any map; the plan
card printed the part of a demand id after the colon.

The closure is one table per sensor in ``dashboard/card/src/util/state-label.js``
and one reader, ``_valLabel()``. These tests read each backend word from the
code that WRITES it, so a word added there without a row in the table (or a
row whose key has no translation) fails here, not on a user's screen.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
from types import SimpleNamespace

import pytest

from .test_638_shadow_mode import freeze_targets  # noqa: F401 — fixture by name

ROOT = pathlib.Path(__file__).resolve().parent.parent
CARD_SRC = ROOT / "dashboard" / "card" / "src"
STATE_LABEL = CARD_SRC / "util" / "state-label.js"
TRANSLATIONS = ROOT / "dashboard" / "translations.json"


# ── The card's tables, read from the JS ─────────────────────────────────────

def _js_tables() -> dict:
    src = STATE_LABEL.read_text(encoding="utf-8")
    tables = {}
    for name, body in re.findall(
            r"export const (\w+) = \{(.*?)\n\};", src, flags=re.S):
        rows = re.findall(
            r"^\s*(?:'([^']+)'|(\w+)):\s*'([^']*)',", body, flags=re.M)
        tables[name] = {(a or b): v for a, b, v in rows}
    vocab = re.search(r"export const VOCAB = \{(.*?)\n\};", src, flags=re.S)
    tables["VOCAB"] = dict(re.findall(r"^\s*(\w+):\s*(\w+),", vocab.group(1),
                                      flags=re.M))
    return tables


def _table_for(sensor: str) -> dict:
    t = _js_tables()
    return t[t["VOCAB"][sensor]]


# ── The backend's words, read from the code that writes them ────────────────

def _words(node, allow=()) -> set:
    """String constants an expression can EVALUATE to: dict values (not
    keys) and the default of a ``{...}.get(key, default)``, both arms of a
    conditional (not its test). Anything else — a variable, a call — is a
    word this scan cannot see, so it fails rather than reading nothing.
    ``allow`` names attributes that are themselves scanned elsewhere."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _words(node.body, allow) | _words(node.orelse, allow)
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Dict)):
        out: set = set()
        for v in node.func.value.values:
            out |= _words(v, allow)
        for a in node.args[1:]:
            out |= _words(a, allow)
        return out
    if isinstance(node, ast.Attribute) and node.attr in allow:
        return set()
    raise AssertionError(
        f"line {getattr(node, 'lineno', '?')}: a value the scan cannot read "
        f"({ast.dump(node)[:80]}) — a word from here would never be checked")


def _published(key: str) -> set:
    """Every value ``build_diagnostics`` can write to ``out[key]``."""
    tree = ast.parse((ROOT / "coordinator" / "publish_diag.py").read_text())
    found: set = set()
    for n in ast.walk(tree):
        if not isinstance(n, ast.Assign):
            continue
        for t in n.targets:
            if (isinstance(t, ast.Subscript)
                    and isinstance(t.slice, ast.Constant)
                    and t.slice.value == key):
                found |= _words(n.value)
    assert found, f"no producer of {key} found — did publish_diag move?"
    return found


def _tariff_providers() -> set:
    found: set = set()
    for path in (ROOT / "tariff").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Attribute) and t.attr == "_provider_name":
                        found |= _words(n.value)
            elif isinstance(n, ast.keyword) and n.arg == "provider":
                found |= _words(n.value, allow=("_provider_name",))
    found |= _annotated_default("tariff_provider")
    return found


def _annotated_default(field: str) -> set:
    tree = ast.parse((ROOT / "coordinator" / "types.py").read_text())
    return {
        n.value.value for n in ast.walk(tree)
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
        and n.target.id == field and isinstance(n.value, ast.Constant)
    }


def _load_management_states() -> set:
    from custom_components.solar_energy_management.consts.states import (
        LoadManagementState,
    )
    words = {v for k, v in vars(LoadManagementState).items()
             if k.isupper() and isinstance(v, str)}
    return words | _annotated_default("load_management_status")


def _heat_pump_modes() -> set:
    from custom_components.solar_energy_management.devices.heat_pump_controller import (
        SGReadyState,
    )
    return {s.name.lower() for s in SGReadyState} | _annotated_default(
        "heat_pump_mode")


def _battery_sign_words() -> set:
    from custom_components.solar_energy_management.coordinator.publish_diag import (
        format_battery_sign_diag,
    )
    texts = [
        format_battery_sign_diag({}, {}),
        format_battery_sign_diag({"b1": True}, {"b1": True}),
        format_battery_sign_diag({"b1": False}, {}),
        format_battery_sign_diag({"b1": True, "b2": False}, {"b1": True}),
    ]
    words = set()
    for text in texts:
        words |= set(re.findall(r"[a-z_]+", text))
    return words - {"b"}


BACKEND = {
    "diag_grid_mode": lambda: _published("diag_grid_mode"),
    "diag_grid_sign": lambda: _published("diag_grid_sign"),
    "diag_charger_control": lambda: _published("diag_charger_control"),
    "diag_battery_sign": _battery_sign_words,
    "heat_pump_mode": _heat_pump_modes,
    "tariff_provider": _tariff_providers,
    "load_management_status": _load_management_states,
}


@pytest.mark.parametrize("sensor", sorted(BACKEND))
def test_every_word_the_backend_writes_has_a_row(sensor):
    words = BACKEND[sensor]()
    table = dict(_table_for(sensor))
    if sensor == "tariff_provider":
        table.update(_js_tables()["TARIFF_BRANDS"])
    missing = sorted(w for w in words if w not in table)
    assert not missing, (
        f"sensor.sem_{sensor} can publish {missing}, and the card has no "
        f"label for it — it would print the word as it is (#1053). Add a "
        f"row to util/state-label.js and a key to translations.json.")


def test_the_reader_finds_the_words_it_was_written_for():
    """The extraction above is the guard; prove it sees the words the
    reporter's screen showed, so it cannot pass by reading nothing."""
    assert _published("diag_grid_mode") == {
        "manual", "combined", "split", "split-declared",
        "split-declared-unverified", "split-lowconf"}
    assert {"normal", "negated"} <= _published("diag_grid_sign")
    assert {"number", "service", "none"} <= _published("diag_charger_control")
    assert {"custom", "static", "calendar", "tibber"} <= _tariff_providers()
    assert {"normal", "force_on"} <= _heat_pump_modes()
    assert {"learning", "negated", "normal"} <= _battery_sign_words()
    assert {"error", "idle"} <= _load_management_states()


def test_every_row_key_is_translated_in_every_language():
    data = json.loads(TRANSLATIONS.read_text(encoding="utf-8"))
    t = _js_tables()
    keys = {k for name in set(t["VOCAB"].values()) for k in t[name].values() if k}
    assert len(keys) > 15
    gaps = sorted(f"{lang}.{k}" for lang in data for k in keys
                  if not str(data[lang].get(k, "")).strip())
    assert not gaps, f"label keys with no translation: {gaps[:10]}"


def test_the_new_words_are_not_left_in_english():
    """A key copied into a language untranslated passes the parity test."""
    data = json.loads(TRANSLATIONS.read_text(encoding="utf-8"))
    for key in ("grid_manual", "sign_negated", "tariff_static", "actual"):
        assert data["nl"][key] != data["en"][key], key
        assert data["de"][key] != data["en"][key], key


# ── Cards read these sensors through the label, not raw ─────────────────────

_RAW_READ = re.compile(r"_val(?:Str|Num)?\(\s*'(\w+)'\s*\)")


def test_no_card_prints_a_word_sensor_raw():
    sensors = set(_js_tables()["VOCAB"])
    hits = []
    for path in sorted((CARD_SRC / "cards").glob("*.js")):
        for no, line in enumerate(path.read_text().splitlines(), 1):
            if "#1053: raw for support" in line:
                continue
            for key in _RAW_READ.findall(line):
                if key in sensors:
                    hits.append(f"{path.name}:{no}: {line.strip()}")
    assert not hits, (
        "read these sensors with _valLabel(), so the word is translated:\n"
        + "\n".join(hits))


# The card checks below read JavaScript as text on purpose: the Python suite
# has no JS parser, and what they pin is the call the card makes.


# ── The chart's own words ───────────────────────────────────────────────────


# ── The energy plan's names ─────────────────────────────────────────────────

from custom_components.solar_energy_management.coordinator.demand_labels import (  # noqa: E402
    demand_label,
    ev_not_scheduled,
    labelled_review,
)

_CONFIG = {"ev_chargers": [
    {"id": "ev_charger", "name": "Wallbox Pulsar"},
    {"id": "ev_charger_1", "name": "  "},
]}


class _Ctrl:
    def __init__(self, *devs):
        self._devs = {d.device_id: d for d in devs}

    def get_device(self, did):
        return self._devs.get(did)


def test_a_charger_left_out_of_the_night_carries_its_name():
    rows = ev_not_scheduled(_CONFIG, [], ["ev_charger", "ev_charger_1"], [])
    assert rows == [
        {"id": "ev:ev_charger", "why": "disconnected", "label": "Wallbox Pulsar"},
        # a blank name is no name: the card shows the kind, never the id
        {"id": "ev:ev_charger_1", "why": "disconnected", "label": None},
    ]


def test_the_order_and_the_whys_are_kept():
    rows = ev_not_scheduled(_CONFIG, ["a"], ["b"], ["c"])
    assert [(r["id"], r["why"]) for r in rows] == [
        ("ev:a", "mode"), ("ev:b", "disconnected"), ("ev:c", "car_full")]


def test_a_demand_id_resolves_to_the_name_a_person_gave():
    ctrl = _Ctrl(SimpleNamespace(device_id="pool", name="Zwembadpomp"))
    assert demand_label(_CONFIG, ctrl, "ev:ev_charger") == "Wallbox Pulsar"
    assert demand_label(_CONFIG, ctrl, "load:pool") == "Zwembadpomp"
    assert demand_label(_CONFIG, ctrl, "comfort:pool") == "Zwembadpomp"
    assert demand_label(_CONFIG, ctrl, "load:gone") is None
    assert demand_label(_CONFIG, ctrl, "arbitrage:battery") is None
    assert demand_label(_CONFIG, ctrl, "ev:unknown") is None
    assert demand_label(_CONFIG, None, "load:pool") is None
    assert demand_label(None, None, "") is None


def test_a_controller_with_only_the_sorted_list_still_answers():
    devs = [SimpleNamespace(device_id="pool", name="Pomp")]
    ctrl = SimpleNamespace(get_devices_sorted=lambda: devs)
    assert demand_label(_CONFIG, ctrl, "load:pool") == "Pomp"


def test_last_nights_review_rows_carry_names_and_the_store_is_untouched():
    review = {
        "demands": [
            {"demand_id": "ev:ev_charger", "kind": "ev", "code": "learning"},
            {"demand_id": "arbitrage:battery", "kind": "battery",
             "code": "learning"},
        ],
        "self_consumption": {"code": "sc_beat"},
    }
    out = labelled_review(review, lambda d: demand_label(_CONFIG, None, d))
    assert [r["label"] for r in out["demands"]] == ["Wallbox Pulsar", None]
    assert out["self_consumption"] == {"code": "sc_beat"}
    assert "label" not in review["demands"][0]
    assert labelled_review(None, lambda d: "x") is None


def test_the_real_plan_names_a_charger_it_leaves_out(freeze_targets):
    """The quiet face and the planned face both build their rows through
    ``ev_not_scheduled``; run the real planner with a named charger."""
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    from unittest.mock import MagicMock
    from .test_638_shadow_mode import _fake_load, _fake_self, _power, _scheduler
    fake = _fake_self(devices=[_fake_load()])
    fake.config["ev_chargers"][0]["name"] = "Wallbox Pulsar"
    fake._mode_allows_night_charging = lambda cfg: False
    SEMCoordinator._shadow_energy_plan(
        fake, _scheduler(), energy=MagicMock(), power=_power())
    rows = fake._energy_plan_shadow["not_scheduled"]
    assert {"id": "ev:ev_charger", "why": "mode",
            "label": "Wallbox Pulsar"} in rows


def test_the_coordinator_publishes_the_review_with_names():
    """The real publish step, with a named charger and a named load."""
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    stored = {"demands": [
        {"demand_id": "ev:ev_charger", "kind": "ev", "code": "learning"},
        {"demand_id": "load:pool", "kind": "load", "code": "learning"},
        {"demand_id": "arbitrage:battery", "kind": "battery", "code": "learning"},
    ]}
    fake = SimpleNamespace(
        config=_CONFIG, _demand_review=stored,
        _surplus_controller=_Ctrl(SimpleNamespace(device_id="pool",
                                                  name="Zwembadpomp")))
    out = SEMCoordinator._published_review(fake)
    assert [r["label"] for r in out["demands"]] == [
        "Wallbox Pulsar", "Zwembadpomp", None]
    assert all("label" not in r for r in stored["demands"])
    assert SEMCoordinator._published_review(
        SimpleNamespace(config={}, _demand_review=None)) is None


def test_every_plan_row_and_the_review_go_through_the_names():
    from .ast_contracts import call_sites
    rows = [(f, n) for f, n, _ in call_sites("ev_not_scheduled")]
    assert len(rows) == 2 and all(f.endswith("coordinator.py") for f, _ in rows)
    published = [f for f, _, _ in call_sites("_published_review")]
    assert published == [str(pathlib.Path("coordinator") / "coordinator.py")]
    # No not-scheduled row is built by hand without a name any more.
    tree = ast.parse((ROOT / "coordinator" / "coordinator.py").read_text())
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict):
            keys = {k.value for k in n.keys if isinstance(k, ast.Constant)}
            if {"id", "why"} <= keys:
                assert "label" in keys, f"line {n.lineno}: a row with no name"


def test_tomorrows_asks_send_no_name_rather_than_an_id_or_english():
    """Tomorrow's view named an unnamed load by its device id and an
    unnamed charger "EV" (English; German reads "E-Auto")."""
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    from .test_638_shadow_mode import TestTomorrowPreviewComposer, _fake_load
    fake = TestTomorrowPreviewComposer()._fake()
    fake.config["ev_chargers"][0]["daily_ev_target"] = 6.0
    unnamed = _fake_load(did="energy_dashboard_shelly_441793")
    named = _fake_load(did="pool")
    named.name = "Zwembadpomp"
    fake._surplus_controller = SimpleNamespace(
        get_devices_sorted=lambda: [unnamed, named])
    asks = SEMCoordinator._compose_tomorrow_preview(fake)["known_asks"]
    assert sorted((a["kind"], a["label"] or "") for a in asks) == [
        ("ev", ""), ("load", ""), ("load", "Zwembadpomp")]
