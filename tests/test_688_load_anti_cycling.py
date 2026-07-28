"""#688 — per-load anti-cycling: solid defaults + an editable surface.

Root cause (investigated, not the reporter's proposed workaround): the anti-cycle
mechanism already exists and is enforced every cycle by
``ControllableDevice.can_activate`` / ``can_deactivate`` (min_off / min_on /
activation_delay). But for a *generic* deferrable load (``SwitchDevice`` — a pool
pump) it defaulted to a twitchy ``min_off=60s`` with ``activation_delay=0`` (starts
on a passing-cloud surplus flash) AND had no config surface anywhere. So the pump
cycled and the user could not lengthen the window. Bug class 30 (a backend-honoured
control with no editable surface) — the same class as #627.

Fix: solid ``SwitchDevice`` defaults, and expose ``min_on_time_min`` /
``min_off_time_min`` as #620-style goals (applied live and on restart via
``_apply_goals``), placed on the load-priority card next to Min/Max/Mode. NO new
parallel anti-cycling system — that would duplicate the mechanism #644 unified.
"""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.devices.base import SwitchDevice
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)

_ROOT = Path(__file__).resolve().parents[1]


def _switch(**kw):
    return SwitchDevice(
        hass=MagicMock(),
        device_id=kw.get("device_id", "pump"),
        name=kw.get("name", "Pool Pump"),
        rated_power=kw.get("rated_power", 800),
        entity_id="switch.pump",
    )


@pytest.mark.unit
class TestSolidDefaults:
    def test_generic_switch_load_is_not_twitchy_by_default(self):
        """The knob that let a pool pump cycle — a 1-minute pause — is gone.
        min_on and min_off are both >= 5 min, so cycling caps at a ~10-min period
        and min_on holds the load through a passing cloud instead of stopping."""
        dev = _switch()
        assert dev.min_off_seconds >= 300, dev.min_off_seconds   # was 60
        assert dev.min_on_seconds >= 300, dev.min_on_seconds


class _FakeController:
    def __init__(self):
        self._devices = {}

    def register_device(self, d):
        self._devices[d.device_id] = d

    def unregister_device(self, did):
        self._devices.pop(did, None)

    def get_device(self, did):
        return self._devices.get(did)


@pytest.fixture
def registry():
    reg = UnifiedDeviceRegistry(MagicMock(), _FakeController(), MagicMock(), MagicMock())
    reg._store = AsyncMock()
    reg.async_refresh_devices = AsyncMock()
    return reg


@pytest.mark.asyncio
async def test_anti_cycle_goal_applies_in_minutes(registry):
    await registry.async_register_service_device({
        "device_id": "pump", "entity_id": "switch.pump", "name": "Pump",
        "rated_power": 800, "priority": 5,
    })
    await registry.async_update_device_goal("pump", "min_on_time_min", 10)
    await registry.async_update_device_goal("pump", "min_off_time_min", 8)
    dev = registry._surplus_controller.get_device("pump")
    assert dev.min_on_seconds == 10 * 60
    assert dev.min_off_seconds == 8 * 60
    assert registry._device_goals["pump"]["min_on_time_min"] == 10


@pytest.mark.asyncio
async def test_other_goals_never_disable_anti_cycle(registry):
    """A device with a runtime goal but NO anti-cycle override must keep its
    solid default window. An unconditional ``_apply_goals`` set with a 0 default
    would silently DISABLE anti-cycling — the exact bug being fixed."""
    await registry.async_register_service_device({
        "device_id": "pump", "entity_id": "switch.pump", "name": "Pump",
        "rated_power": 800, "priority": 5,
    })
    await registry.async_update_device_goal("pump", "daily_min_runtime_min", 240)
    dev = registry._surplus_controller.get_device("pump")
    assert dev.min_off_seconds >= 300      # not reset to 0
    assert dev.min_on_seconds >= 300       # not reset to 0


@pytest.mark.unit
class TestSurfaceExists:
    """Bug class 30 guard: a backend-honoured anti-cycle knob must be reachable —
    in the goal allowlist, the service schema, AND on the load config card."""

    def test_goal_properties_include_anti_cycle(self):
        assert "min_on_time_min" in UnifiedDeviceRegistry.GOAL_PROPERTIES
        assert "min_off_time_min" in UnifiedDeviceRegistry.GOAL_PROPERTIES

    def test_service_allowlist_accepts_anti_cycle(self):
        src = (_ROOT / "__init__.py").read_text()
        for key in ("min_on_time_min", "min_off_time_min"):
            # routing branch + schema vol.In (at least two occurrences)
            assert src.count(f'"{key}"') >= 2, f"{key} not wired into update_device_config"

    def test_load_card_has_anti_cycle_control(self):
        card = (_ROOT / "dashboard" / "card" / "src" / "cards"
                / "sem-load-priority-card.js").read_text()
        assert "min_on_time_min" in card, "no min-run control on the load card"
        assert "min_off_time_min" in card, "no min-pause control on the load card"
