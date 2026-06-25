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
