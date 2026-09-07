"""#919 — the Repair that should have told PROD's owner, and could not.

PROD's battery is pinned to `battery_charge_platform: generic` (the old
options-wizard default #900 describes). On a Huawei install that means no
forced-discharge path, so the #778 sell block opened every evening at 20:05
and was dropped every cycle — six log lines a minute and no pack sold.

#900 built the Repair for exactly this. It never fired, on any install: the
check ran ONCE, inside the branch that builds the adapter, during SEM's
first refresh — while `huawei_solar` was still loading. `_integration_loaded`
was False, so the check took its `else` branch, CLEARED the Repair, and was
never asked again. A question asked before the thing it asks about exists
(the #166 / detection-report shape).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)

RI = ("custom_components.solar_energy_management.coordinator.repair_issues"
      ".{}_battery_platform_pinned_generic")


def _coord(is_running=True, pinned="huawei"):
    c = SimpleNamespace(hass=SimpleNamespace(is_running=is_running))
    c._battery_adapter_context = lambda *a: {"battery_charge_platform": "generic"}
    return c


@pytest.mark.unit
class TestThePinRepairIsAskedEveryCycle:

    def test_nothing_is_decided_before_ha_is_running(self):
        """The bug: at boot the brand integration is not loaded yet, so the
        honest answer is 'not yet' — never a clear."""
        c = _coord(is_running=False)
        with patch(RI.format("raise")) as raise_, patch(RI.format("clear")) as clear:
            SEMCoordinator._check_battery_platform_pin(c, "primary", 0, 1)
        raise_.assert_not_called()
        clear.assert_not_called()

    def test_a_pinned_brand_install_raises_once(self):
        c = _coord()
        with patch("custom_components.solar_energy_management.coordinator"
                   ".battery_adapters.pinned_generic_brand", return_value="huawei"), \
             patch(RI.format("raise")) as raise_:
            for _ in range(5):          # five cycles
                SEMCoordinator._check_battery_platform_pin(c, "primary", 0, 1)
        assert raise_.call_count == 1, "raised once, not once per cycle"
        assert raise_.call_args.kwargs["brand"] == "huawei"

    def test_it_clears_when_the_user_fixes_the_setting(self):
        c = _coord()
        with patch("custom_components.solar_energy_management.coordinator"
                   ".battery_adapters.pinned_generic_brand", return_value="huawei"), \
             patch(RI.format("raise")):
            SEMCoordinator._check_battery_platform_pin(c, "primary", 0, 1)
        with patch("custom_components.solar_energy_management.coordinator"
                   ".battery_adapters.pinned_generic_brand", return_value=None), \
             patch(RI.format("clear")) as clear:
            SEMCoordinator._check_battery_platform_pin(c, "primary", 0, 1)
            SEMCoordinator._check_battery_platform_pin(c, "primary", 0, 1)
        assert clear.call_count == 1, "cleared once on the change, not every cycle"

    def test_it_is_asked_after_the_adapter_is_already_cached(self):
        """The whole point: the check must NOT live inside the branch that
        builds the adapter, because that branch runs once and early."""
        # the call site sits beside the cache lookup, not inside the build
        from pathlib import Path
        body = (Path(__file__).resolve().parent.parent
                / "coordinator" / "coordinator.py").read_text()
        i = body.index("self._check_battery_platform_pin(battery_id")
        j = body.index("adapter = self._battery_adapters.get(battery_id)")
        assert i < j, "the pin check must run before/beside the cache lookup"
        assert "if adapter is None" not in body[i:j], (
            "the check is back inside the build-once branch")

    def test_a_broken_context_never_costs_a_cycle(self):
        c = _coord()
        c._battery_adapter_context = MagicMock(side_effect=RuntimeError("boom"))
        with patch(RI.format("raise")) as raise_, patch(RI.format("clear")) as clear:
            SEMCoordinator._check_battery_platform_pin(c, "primary", 0, 1)
        raise_.assert_not_called(); clear.assert_not_called()
