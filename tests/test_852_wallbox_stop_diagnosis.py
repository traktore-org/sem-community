"""#852 — when a Wallbox stop cannot work, the log must say so.

RienduPre: "I set it to off and it keeps on charging." On Wallbox the
real stop is the ``switch.*pause_resume`` entity; without it SEM falls
back to ``set_current(0)``, which some Pulsar firmware latches at the
last setpoint. Two ways discovery fails — no switch on the device (a
WARNING already), and no resolvable DEVICE at all, which returned
silently. Same broken outcome, and only one of them was diagnosable.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.charger_adapters.wallbox import (
    WallboxAdapter,
)


def _adapter(**over):
    dev = MagicMock()
    dev.name = "Pulsar"
    dev.start_stop_entity = over.get("start_stop", None)
    dev.charger_current_entity = over.get("current_entity", "number.pulsar_current")
    dev.charger_service_entity_id = None
    dev.hass = MagicMock()
    a = WallboxAdapter.__new__(WallboxAdapter)
    a._device = dev
    a._pause_switch_entity = None
    a._pause_switch_searched = False
    return a


def test_an_unresolvable_device_is_named_not_silent(caplog, monkeypatch):
    """The path that used to return None without a word (#852)."""
    import custom_components.solar_energy_management.coordinator.charger_adapters.wallbox as wb
    reg = SimpleNamespace(async_get=lambda eid: None, entities={})
    monkeypatch.setattr(wb.er, "async_get", lambda hass: reg)
    a = _adapter()
    with caplog.at_level(logging.WARNING):
        assert a._discover_pause_switch() is None
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "#852" in joined
    assert "ev_start_stop_entity" in joined      # the actionable next step
    assert "number.pulsar_current" in joined     # what it actually looked at


def test_a_configured_switch_still_wins_without_touching_the_registry():
    a = _adapter(start_stop="switch.wallbox_abc_pause_resume")
    assert a._discover_pause_switch() == "switch.wallbox_abc_pause_resume"


# ── the reporter's scenario, modelled on the .46 Wallbox sim ─────────
#
# The rig's sim is a faithful Pulsar: `input_number.sim_wb_current` is
# written freely and ignored, while power follows the ENABLE switch alone
# ("SIM Wallbox draws when enabled", 11 kW on / 0 off). That is precisely
# the firmware behaviour behind #852 — SEM writes 0 A, the box latches at
# its last setpoint and keeps charging.

class _LatchingPulsar:
    """Current writes land and change nothing; only the pause stops it."""

    def __init__(self):
        self.name = "Pulsar"
        self.hass = MagicMock()
        self.setpoint_a = 16
        self.enabled = True
        self.start_stop_entity = None
        self.charger_current_entity = "input_number.sim_wb_current"
        self.charger_service_entity_id = None

    @property
    def power_w(self):
        return 11000.0 if self.enabled else 0.0


@pytest.mark.asyncio
async def test_off_does_not_stop_a_latching_pulsar_without_a_pause_switch(
    monkeypatch, caplog,
):
    """#852 reproduced: mode Off leaves the car charging.

    With no pause switch discoverable, ``command_disable`` reaches the box
    as ``set_current(0)`` only — and this firmware ignores it. SEM has
    said no; 11 kW keeps flowing. The user sees a setting that looks
    obeyed and a car that never stops.
    """
    import custom_components.solar_energy_management.coordinator.charger_adapters.wallbox as wb
    monkeypatch.setattr(wb.er, "async_get",
                        lambda hass: SimpleNamespace(async_get=lambda e: None,
                                                     entities={}))
    box = _LatchingPulsar()
    a = WallboxAdapter.__new__(WallboxAdapter)
    a._device = MagicMock()
    a._device.name = box.name
    a._device.hass = box.hass
    a._device.start_stop_entity = None
    a._device.charger_current_entity = box.charger_current_entity
    a._device.charger_service_entity_id = None
    a._pause_switch_entity = None
    a._pause_switch_searched = False

    async def _set_current(amps):
        box.setpoint_a = amps          # accepted, and ignored by the firmware
    a._device._set_current = _set_current
    a._device.stop_session = MagicMock(side_effect=lambda *a, **k: None)

    with caplog.at_level(logging.WARNING):
        await a._toggle_pause_switch(turn_on=False)   # the stop half that matters

    assert box.power_w == 11000.0, (
        "the sim must keep drawing — that IS the bug being reproduced"
    )
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "#852" in joined, (
        "and SEM must now say why its stop cannot work — pre-fix this "
        "returned None in silence"
    )
