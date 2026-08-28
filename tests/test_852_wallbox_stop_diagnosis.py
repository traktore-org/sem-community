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
