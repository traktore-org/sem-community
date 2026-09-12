"""#923 — the coordinator computes the module verdict once, after the Energy
Dashboard read and before any platform builds its entities."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator
from custom_components.solar_energy_management.coordinator.install_modules import (
    BATTERY_WIRING_KEYS,
    Module,
    Presence,
)

from .test_873_energy_dashboard_init import _coordinator, _dashboard, _run

_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def test_install_presence_reads_the_raw_dashboard_and_its_answer():
    stub = SimpleNamespace(
        config={},
        _ed_raw_config=SimpleNamespace(has_battery=True, has_ev=False),
        _ed_answered=True,
    )
    presence = SEMCoordinator.install_presence(stub)
    assert presence[Module.BATTERY] is Presence.PRESENT
    assert presence[Module.EV] is Presence.ABSENT


def test_an_unanswered_dashboard_keeps_the_battery_unknown():
    stub = SimpleNamespace(config={}, _ed_raw_config=None, _ed_answered=False)
    assert SEMCoordinator.install_presence(stub)[Module.BATTERY] is Presence.UNKNOWN


def test_the_verdict_is_captured_between_the_dashboard_read_and_the_platforms():
    src = _INIT.read_text(encoding="utf-8")
    ed_read = src.index("await coordinator.async_initialize_energy_dashboard()")
    capture = src.index("coordinator.setup_presence = coordinator.install_presence()")
    forward = src.index("await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)")
    assert ed_read < capture < forward



def _no_battery_wiring(coord):
    """The verdicts below must come from the dashboard, not from a default."""
    assert not any(coord.config.get(key) for key in BATTERY_WIRING_KEYS)


class TestTheInitialiseRunFeedsTheVerdict:
    """RUN ``async_initialize_energy_dashboard`` and then ask the verdict —
    the stubs above prove install_presence() reads two attributes, not that
    the dashboard read ever fills them."""

    @pytest.mark.asyncio
    async def test_a_dashboard_too_thin_to_adopt_still_declares_its_battery(self):
        """Not minimally configured (no solar + grid pair), so SEM does not
        read its sensors — but the battery it declares is still a battery."""
        ed = _dashboard(minimal=False)
        ed.has_battery = True
        ed.has_ev = False
        coord = _coordinator()
        _no_battery_wiring(coord)

        assert await _run(coord, result=ed) is False
        assert coord._energy_dashboard_config is None
        assert coord.install_presence()[Module.BATTERY] is Presence.PRESENT

    @pytest.mark.asyncio
    async def test_an_unread_dashboard_keeps_the_battery_unknown(self):
        coord = _coordinator()
        _no_battery_wiring(coord)

        await _run(coord, result=None, answered=False)

        assert coord._ed_answered is False
        assert coord.install_presence()[Module.BATTERY] is Presence.UNKNOWN

    @pytest.mark.asyncio
    async def test_no_dashboard_at_all_makes_the_battery_absent(self):
        coord = _coordinator()
        _no_battery_wiring(coord)

        await _run(coord, result=None, answered=True)

        assert coord._ed_answered is True
        assert coord.install_presence()[Module.BATTERY] is Presence.ABSENT


class TestNoBatteryModuleNoBatteryControl:
    """(#923, found live on .175) With the battery ABSENT the coordinator
    must not pick an adapter or decide for a battery it cannot see."""

    async def test_absent_battery_skips_the_pipeline(self):
        from unittest.mock import MagicMock
        stub = MagicMock()
        stub.setup_presence = {m: Presence.ABSENT for m in Module}
        await SEMCoordinator._run_battery_pipeline(stub, MagicMock(), MagicMock(), MagicMock())
        assert stub._last_battery_decisions == {}
        # nothing past the gate ran
        stub.time_manager.is_night_mode.assert_not_called()
        stub._per_battery_config.assert_not_called()

    async def test_unknown_battery_still_runs_it(self):
        from unittest.mock import MagicMock
        stub = MagicMock()
        stub.setup_presence = {m: Presence.UNKNOWN for m in Module}
        try:
            await SEMCoordinator._run_battery_pipeline(stub, MagicMock(), MagicMock(), MagicMock())
        except Exception:  # noqa: BLE001 — the double cannot carry a real cycle
            pass
        # it went past the gate into the real pipeline
        assert stub.method_calls, "UNKNOWN must not be gated"
