"""#855 — the withheld commands must reach a surface someone can read
(2.1 coverage-audit finding 7).

The CHANGELOG promises: "SEM's dry run now reports the exact service calls
it withheld — not just the decision it reached." Until this file the seam
APPENDED to `withheld_commands` and the observer push CLEARED it, and
nothing anywhere read it — the promise was false as shipped. The observer
switch's attributes are the standing simulation surface (#764's
would_decisions), so the withheld list rides there, keyed by device.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)


def _dev(device_id, cmds):
    return SimpleNamespace(device_id=device_id, withheld_commands=list(cmds))


CMD = {"service": "keba.disable", "data": {}, "why": "stop"}


@pytest.mark.unit
class TestWithheldSurface:
    def test_collects_from_every_charger_shape(self):
        a = _dev("keba_1", [CMD])
        b = _dev("zaptec_2", [])
        late = _dev("ev_charger", [CMD])
        fake = SimpleNamespace(_ev_devices={"keba_1": a, "zaptec_2": b},
                               _ev_device=late)
        out = SEMCoordinator.observer_withheld_commands(fake)
        assert out == {"keba_1": [CMD], "ev_charger": [CMD]}, (
            "every device with a withheld command appears; empty lists "
            "are dropped (they are noise, not information)"
        )

    def test_dedupes_the_fallback_alias(self):
        d = _dev("keba_1", [CMD])
        fake = SimpleNamespace(_ev_devices={"keba_1": d}, _ev_device=d)
        assert SEMCoordinator.observer_withheld_commands(fake) == {"keba_1": [CMD]}

    def test_empty_when_nothing_withheld(self):
        fake = SimpleNamespace(_ev_devices={}, _ev_device=None)
        assert SEMCoordinator.observer_withheld_commands(fake) == {}

    def test_a_device_without_the_attribute_is_skipped(self):
        bare = SimpleNamespace(device_id="old")
        fake = SimpleNamespace(_ev_devices={"old": bare}, _ev_device=None)
        assert SEMCoordinator.observer_withheld_commands(fake) == {}
