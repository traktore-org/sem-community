"""#923 — the coordinator computes the module verdict once, after the Energy
Dashboard read and before any platform builds its entities."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator
from custom_components.solar_energy_management.coordinator.install_modules import (
    Module,
    Presence,
)

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
