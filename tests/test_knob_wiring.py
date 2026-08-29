"""Contract lint: every user-facing knob must reach a decision.

The 2026-06-25 wiring census found several `number` sliders that the dashboard
showed as live controls but no decision read — users changed them and nothing
happened (`maximum_grid_import`, `battery_resume_soc`, the legionella key
mismatch, …). This test fails CI if a NUMBER_TYPES knob's config key has no
reader anywhere in the logic layer, so a dead stepper can't ship again.

"Has a reader" = the config key (after CONFIG_KEY_MAP translation) appears as a
quoted string somewhere under the logic roots (coordinator/, features/,
devices/, tariff/, utils/, __init__.py). That's a deliberately loose proxy —
it proves the key is *referenced by logic*, not merely defined/persisted/shown.
"""
from pathlib import Path

import pytest

from custom_components.solar_energy_management.number import (
    NUMBER_TYPES,
    CONFIG_KEY_MAP,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LOGIC_ROOTS = ["coordinator", "features", "devices", "tariff", "utils"]

# Keys intentionally consumed somewhere the loose grep can't see (e.g. only
# through dynamic config dict iteration). Empty today — add with a reason.
_ALLOWED_NO_READER: set[str] = set()


def _logic_blob() -> str:
    files: list[Path] = []
    for root in _LOGIC_ROOTS:
        files.extend((_REPO_ROOT / root).rglob("*.py"))
    files.append(_REPO_ROOT / "__init__.py")
    return "\n".join(p.read_text() for p in files if p.exists())


@pytest.mark.unit
class TestEveryKnobHasAReader:
    def test_number_knobs_reach_a_decision(self):
        blob = _logic_blob()
        dead = []
        for desc in NUMBER_TYPES:
            entity_key = desc.key
            config_key = CONFIG_KEY_MAP.get(entity_key, entity_key)
            if config_key in _ALLOWED_NO_READER:
                continue
            if f'"{config_key}"' not in blob and f"'{config_key}'" not in blob:
                dead.append((entity_key, config_key))
        assert not dead, (
            "These user-facing number knobs have NO reader in the logic layer — "
            "a dead stepper (users set it, nothing happens). Wire it to a "
            "decision, or remove the entity:\n"
            + "\n".join(f"  {ek}  ->  config key {ck!r}" for ek, ck in dead)
        )

# ── #553 — the same contract for SWITCHES and SELECTS ────────────────────
# The #542 census class isn't number-specific: a switch/select the dashboard
# shows as live but no decision reads is the same silent no-op. The static
# TYPES lists are small (most switch/select surface is dynamic per-charger /
# per-battery); the dynamic keys are pinned explicitly below — update the
# map when adding one, and the test fails if its config key loses all readers.

from custom_components.solar_energy_management.switch import SWITCH_TYPES
from custom_components.solar_energy_management.select import SELECT_TYPES

# entity key (or dynamic pattern) → the config key the logic layer must read.
_DYNAMIC_SWITCH_SELECT_KEYS: dict[str, str] = {
    # select.py per-charger dynamics
    "charger_{cid}_ev_target_type": "ev_target_type",
    "charger_{cid}_charge_mode": "charge_mode",
    # (#804) phase mode — read by _phase_switch_tick (ev_control.py)
    "charger_{cid}_phase_mode": "phase_mode",
    # select.py per-battery dynamics + global battery mode
    "battery_{bid}_mode": "battery_mode",
    "battery_mode": "battery_mode",
}


@pytest.mark.unit
class TestSwitchSelectKnobsHaveReaders:
    def test_static_switch_select_keys_reach_a_decision(self):
        blob = _logic_blob()
        dead = []
        for desc in list(SWITCH_TYPES) + list(SELECT_TYPES):
            key = desc.key
            if key in _ALLOWED_NO_READER:
                continue
            if f'"{key}"' not in blob and f"'{key}'" not in blob:
                dead.append(key)
        assert not dead, (
            f"switch/select knobs with NO logic reader (silent no-ops): {dead}"
        )

    def test_dynamic_switch_select_keys_reach_a_decision(self):
        blob = _logic_blob()
        dead = []
        for pattern, config_key in _DYNAMIC_SWITCH_SELECT_KEYS.items():
            if f'"{config_key}"' not in blob and f"'{config_key}'" not in blob:
                dead.append((pattern, config_key))
        assert not dead, (
            f"dynamic switch/select knobs with NO logic reader: {dead}"
        )

    def test_dynamic_map_matches_source(self):
        """The pinned dynamic-key map must track select.py — if a new dynamic
        select/switch key appears in the source, add it to the map (with its
        config key) so the reader contract covers it."""
        import re
        src = (
            (_REPO_ROOT / "select.py").read_text()
            + (_REPO_ROOT / "switch.py").read_text()
        )
        found = set(re.findall(r'key\s*=\s*f"((?:charger|battery)_\{[a-z]+\}_[a-z_]+)"', src))
        pinned = {k for k in _DYNAMIC_SWITCH_SELECT_KEYS if "{" in k}
        missing = found - pinned
        assert not missing, (
            f"dynamic switch/select keys not covered by the wiring contract: "
            f"{missing} — add them to _DYNAMIC_SWITCH_SELECT_KEYS"
        )

