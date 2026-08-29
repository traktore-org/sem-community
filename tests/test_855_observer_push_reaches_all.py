"""#855 — the observer push must reach EVERY charger device, however it
was discovered (2.1 coverage-audit finding 3).

``_retry_ev_device_setup`` — the late-discovery fallback for a charger
integration that loads after SEM at HA startup — sets ``self._ev_device``
and never touches ``self._ev_devices``. The observer push iterated only
``_ev_devices``, so a late-discovered charger's ``observer_mode`` kept its
constructor default (False) forever.

Nothing failed live because ``actuate()`` still carries its own older
decision-level observe gate — the exact pattern #855 exists to retire. The
moment that "redundant" gate is cleaned up, this reintroduces #854 on
precisely the late-discovery path. Same single-vs-dict shape as
``_zero_charger_setpoints``, whose tests cover both; these mirror them.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)


def _device():
    return SimpleNamespace(observer_mode=False, withheld_commands=["stale"])


@pytest.mark.unit
class TestObserverPushReachesAllChargers:
    def test_multi_charger_dict_is_pushed(self):
        a, b = _device(), _device()
        fake = SimpleNamespace(
            _ev_devices={"a": a, "b": b}, _ev_device=None, _observer_mode=True,
        )
        SEMCoordinator._push_observer_mode_to_devices(fake)
        assert a.observer_mode is True and b.observer_mode is True
        assert a.withheld_commands == [] and b.withheld_commands == []

    def test_late_discovered_single_charger_is_pushed_too(self):
        """The retry path's shape: _ev_device set, _ev_devices empty."""
        single = _device()
        fake = SimpleNamespace(
            _ev_devices={}, _ev_device=single, _observer_mode=True,
        )
        SEMCoordinator._push_observer_mode_to_devices(fake)
        assert single.observer_mode is True, (
            "a charger discovered late must not keep observer_mode=False "
            "while the install is observing — that is #854's shape"
        )
        assert single.withheld_commands == []

    def test_same_object_in_both_is_pushed_once_harmlessly(self):
        d = _device()
        fake = SimpleNamespace(
            _ev_devices={"a": d}, _ev_device=d, _observer_mode=False,
        )
        SEMCoordinator._push_observer_mode_to_devices(fake)
        assert d.observer_mode is False
        assert d.withheld_commands == []
