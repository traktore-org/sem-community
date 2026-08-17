"""#627 — every per-charger entity key the runtime honours has a writable surface.

**Bug class 30** — *backend-honoured config key with no editable surface.*

``__init__.py`` builds each ``CurrentControlDevice`` from the per-charger dict
via ``_cfg(...)``. ``hardware_detection`` auto-fills several of those keys at
install time. The failure mode is silent in both directions:

* the auto-detect guesses **wrong** and the user cannot correct it, or
* a charger **added after install** never gets the key at all, because the only
  place it was ever written was the install-time flow.

@onkelfu's #627 install hit the first shape: the box kept its contactor closed
at 0 A, ``ev_start_stop_entity`` was exactly the key that would have opened it,
``devices/base.py`` has honoured it since v1.0 — and nothing in the config card
or the options flow could write it. Same shape as #684 (a picker whose domain
list was narrower than the reader's contract).

This guard is the sweep, not the instance: it re-derives the key list from
``__init__.py`` on every run, so a *new* per-charger entity key that lands
without a surface fails here rather than in a user's log a release later.
"""
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_INIT = _ROOT / "__init__.py"
_FLOW = _ROOT / "config_flow.py"
_CARD = _ROOT / "dashboard" / "card" / "src" / "cards" / "sem-config-card.js"

# Steps a user can reach AFTER install. The install-time ``ev_charger`` step
# does not count: it is unreachable for a second charger and for a correction.
_POST_INSTALL_STEPS = ("ev_charger_add", "ev_charger_edit")

# Keys that name an HA entity SEM reads from or writes to. Matched by suffix so
# the list cannot go stale.
_ENTITY_SUFFIXES = ("_entity", "_sensor", "_entity_id")

# Deliberately not surfaced, with the reason. Anything else must have a form
# field. Shrinking this dict is progress; growing it needs a reason here.
_EXEMPT = {
    # Free-form service plumbing, not an entity reference; ``ev_charger_service``
    # (the service name) and its target entity ARE surfaced, which is the pair a
    # user actually configures.
    "ev_service_device_id": "device-registry id, resolved by hardware_detection",
}


def _percharger_cfg_keys() -> set[str]:
    """Keys read off the per-charger dict, from the source of truth."""
    src = _INIT.read_text()
    # Anchored on the name and its two meaningful parameters, NOT on the whole
    # signature: #786 bound the enclosing loop variable as a default argument
    # (``_this=charger_cfg``) and an exact-string anchor turned that into two
    # red tests. A keyword added to the helper is not the rename this guard
    # exists to catch — ``def _cfg`` disappearing is.
    start = src.index("def _cfg(key, default=None")
    # The per-charger registration block; generous window, the regex is anchored
    # on ``_cfg("...")`` which only exists inside it.
    region = src[start:start + 40000]
    return set(re.findall(r'_cfg\(\s*"([^"]+)"', region))


def _flow_fields_by_step() -> dict[str, set[str]]:
    src = _FLOW.read_text()
    bounds = [(m.start(), m.group(1))
              for m in re.finditer(r"async def async_step_(\w+)", src)]
    bounds.append((len(src), "__eof__"))
    out: dict[str, set[str]] = {name: set() for _, name in bounds}
    for m in re.finditer(r'vol\.(?:Optional|Required)\(\s*"([^"]+)"', src):
        for (s, name), (e, _) in zip(bounds, bounds[1:], strict=False):
            if s <= m.start() < e:
                out[name].add(m.group(1))
                break
    return out


def _card_nested_keys() -> set[str]:
    src = _CARD.read_text()
    return set(re.findall(
        r"_renderPickerNested\(\s*idx,\s*cid,\s*'([^']+)'", src))


@pytest.mark.unit
class TestPerChargerEntityKeysAreWritable:
    def test_premise_the_key_scan_finds_the_block(self):
        """Fail loudly if the ``_cfg`` block is renamed — otherwise an empty
        key set would make every assertion below vacuously pass."""
        keys = _percharger_cfg_keys()
        assert len(keys) > 15, keys
        assert "ev_current_control_entity" in keys
        assert "ev_start_stop_entity" in keys

    def test_every_entity_key_is_editable_after_install(self):
        flow = _flow_fields_by_step()
        reachable = set().union(*(flow.get(s, set()) for s in _POST_INSTALL_STEPS))
        card = _card_nested_keys()
        unreachable = []
        for key in sorted(_percharger_cfg_keys()):
            if not key.endswith(_ENTITY_SUFFIXES) or key in _EXEMPT:
                continue
            if key not in reachable and key not in card:
                unreachable.append(key)
        assert not unreachable, (
            "per-charger entity keys the runtime honours with no way to set "
            "them after install (bug class 30 — add a field to "
            f"async_step_ev_charger_add/_edit or a picker to the config card, "
            f"or exempt with a reason): {unreachable}"
        )

    def test_627_start_stop_is_on_the_card_not_only_in_the_flow(self):
        """The reported install needed it reachable from the dashboard — the
        options flow alone was not where the user was looking."""
        assert "ev_start_stop_entity" in _card_nested_keys()

    def test_add_and_edit_agree(self):
        """A key settable when ADDING a charger must be correctable later."""
        flow = _flow_fields_by_step()
        add = {k for k in flow.get("ev_charger_add", set())
               if k.endswith(_ENTITY_SUFFIXES)}
        edit = {k for k in flow.get("ev_charger_edit", set())
                if k.endswith(_ENTITY_SUFFIXES)}
        assert not (add - edit), f"settable on add, not on edit: {sorted(add - edit)}"


@pytest.mark.unit
class TestNewFlowFieldsAreLabelled:
    """An unlabelled voluptuous key renders as the raw key in HA's UI."""

    @pytest.mark.parametrize("key", [
        "ev_start_stop_entity",
        "ev_current_sensor",
        "ev_charge_mode_entity",
        "ev_charge_mode_start",
        "ev_charge_mode_stop",
    ])
    def test_label_and_description_exist_in_english(self, key):
        import json
        en = json.loads((_ROOT / "translations" / "en.json").read_text())
        for step in _POST_INSTALL_STEPS:
            block = en["options"]["step"][step]
            assert key in block["data"], f"{step}.data missing {key}"
            assert key in block["data_description"], \
                f"{step}.data_description missing {key}"
