"""#689 — battery power sliders must express real hardware.

The #680 range-bug class, power edition: an EG4 Flexboss 21 discharges
12 kW from battery (parallel stacks more), but the discharge and assist
sliders capped at 10 kW — the value a real system runs at was literally
un-enterable. Both surfaces matter: the options-flow NumberSelector AND
the number entity (the config-card knob mirrors the entity's min/max —
the #680 lesson). The charge-power slider already allowed 25 kW; the
three now share that ceiling. Commands are still clamped to the
hardware's real limits by the adapters (#678), so a generous slider can
never over-drive a smaller system.
"""
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_FLOW = (_ROOT / "config_flow.py").read_text()
_NUMBER = (_ROOT / "number.py").read_text()

_CEILING = 25000


def _flow_max(key: str) -> int:
    # Bounded window after the key; comments may contain parentheses, so
    # match the literal ``max=`` of the selector config, not a paren-free run.
    m = re.search(rf'"{key}".{{0,600}}?\bmax=(\d+)', _FLOW, re.S)
    assert m, f"{key} slider not found in config_flow"
    return int(m.group(1))


def _entity_max(key: str) -> int:
    m = re.search(
        rf'key="{key}".*?native_max_value=(\d+)', _NUMBER, re.S)
    assert m, f"{key} entity not found in number.py"
    return int(m.group(1))


@pytest.mark.unit
class TestBatteryPowerCeilings:
    @pytest.mark.parametrize("key", [
        "battery_max_discharge_power",
        "battery_assist_max_power",
        "battery_max_charge_power_w",
    ])
    def test_flow_slider_reaches_the_ceiling(self, key):
        assert _flow_max(key) >= _CEILING, (
            f"{key} flow slider caps below {_CEILING} W — real hardware "
            f"(12 kW+ battery inverters) becomes inexpressible (#689)")

    @pytest.mark.parametrize("key", [
        "battery_max_discharge_power",
        "battery_assist_max_power",
    ])
    def test_number_entity_reaches_the_ceiling(self, key):
        assert _entity_max(key) >= _CEILING, (
            f"{key} number entity caps below {_CEILING} W — the config-card "
            f"knob mirrors this (#680 lesson), so the card is capped too")
