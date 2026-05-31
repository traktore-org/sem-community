"""Tests for ``_this_charger_power`` cache shim (v1.6.14).

v1.6.14 lifts ``this_power_w`` onto ``PerChargerContext`` as a typed
field, computed once in ``__enter__``. ``_this_charger_power`` becomes
a cache shim — when ``coord._current_pcc`` points at an active context
for the same charger, return the cached value; otherwise fall through
to the legacy HA-state read.

These tests pin:

1. Cache HIT: inside a ``with`` block, the helper returns the value
   ``__enter__`` precomputed without re-reading HA state.
2. Cache MISS (different ev): if the helper is called with an
   ``ev_dev`` that doesn't match ``pcc.ev_dev``, the cache is bypassed.
3. Cache MISS (no pcc): outside any context, the helper reads HA
   state — the single-charger fallback path is unchanged.
4. Cache MISS (pcc but ``this_power_w`` is None): if the precompute
   failed in ``__enter__``, the helper falls through rather than
   returning ``None``.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.ev_control import (
    EVControlMixin,
)
from custom_components.solar_energy_management.coordinator.per_charger_context import (
    PerChargerContext,
)


def _make_mixin(state_value=None, state_unit="W"):
    """Build a minimal ``EVControlMixin`` stub.

    Provides ``self.hass.states.get(entity_id)`` returning a fake state
    with ``state`` and ``attributes`` so the legacy HA-read path works.
    Provides ``_get_active_charger_config`` returning a config dict
    pointing at the fake sensor.
    """
    mx = EVControlMixin.__new__(EVControlMixin)

    hass = MagicMock()
    if state_value is None:
        hass.states.get.return_value = None
    else:
        state = MagicMock()
        state.state = str(state_value)
        state.attributes = {"unit_of_measurement": state_unit}
        hass.states.get.return_value = state
    mx.hass = hass

    mx._get_active_charger_config = MagicMock(
        return_value={"ev_charging_power_sensor": "sensor.fake_charger_power"},
    )
    mx._current_pcc = None
    return mx


class TestCacheHit:
    """When ``coord._current_pcc`` matches the requested ``ev``,
    ``_this_charger_power`` returns the cached value without
    touching HA state."""

    def test_cache_hit_short_circuits_ha_read(self):
        mx = _make_mixin(state_value=999.0)  # HA-read would return 999
        ev_dev = SimpleNamespace(name="left")
        pcc = PerChargerContext(
            cid="left", ev_dev=ev_dev, charger_cfg={},
            this_power_w=4150.0,
        )
        mx._current_pcc = pcc

        # Helper returns the cached value, not the HA-state value.
        assert mx._this_charger_power(ev_dev, MagicMock(ev_power=0)) == 4150.0
        # HA state never consulted.
        mx.hass.states.get.assert_not_called()


class TestCacheMiss:
    """Cache misses fall through to the legacy read path."""

    def test_different_ev_dev_bypasses_cache(self):
        """Cache only matches when ``pcc.ev_dev is ev``. The "is"
        identity check matters: copying ev_dev into a different
        object shouldn't serve the cached value (would be a wrong-
        charger read)."""
        mx = _make_mixin(state_value=300.0)  # HA returns 300 W
        ev_dev_A = SimpleNamespace(name="A")
        ev_dev_B = SimpleNamespace(name="B")
        pcc = PerChargerContext(
            cid="left", ev_dev=ev_dev_A, charger_cfg={},
            this_power_w=4150.0,
        )
        mx._current_pcc = pcc

        # Called with B; cache is for A; helper reads HA state.
        assert mx._this_charger_power(ev_dev_B, MagicMock(ev_power=0)) == 300.0

    def test_no_pcc_uses_legacy_read(self):
        """Outside any per-charger iteration (single-charger fallback
        path at coordinator.py:1267) the helper falls through to the
        legacy direct-read."""
        mx = _make_mixin(state_value=2500.0)
        mx._current_pcc = None
        assert mx._this_charger_power(SimpleNamespace(), MagicMock(ev_power=0)) == 2500.0

    def test_pcc_with_none_this_power_w_falls_through(self):
        """``__enter__`` failure mode: pcc set, this_power_w None.
        Helper must not return ``None`` — fall through to legacy."""
        mx = _make_mixin(state_value=1234.0)
        ev_dev = SimpleNamespace(name="left")
        pcc = PerChargerContext(
            cid="left", ev_dev=ev_dev, charger_cfg={},
            this_power_w=None,
        )
        mx._current_pcc = pcc
        assert mx._this_charger_power(ev_dev, MagicMock(ev_power=0)) == 1234.0


class TestKwUnitConversion:
    """Legacy path's kW→W conversion stays in place when the cache
    is bypassed — pin the regression that bit PROD on 2026-05-31."""

    def test_kw_value_converted_to_watts(self):
        mx = _make_mixin(state_value=4.14, state_unit="kW")
        # No pcc → legacy read path. KEBA reports 4.14 kW = 4140 W.
        assert mx._this_charger_power(SimpleNamespace(), MagicMock(ev_power=0)) == 4140.0
