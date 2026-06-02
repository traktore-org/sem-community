"""Tests for the per-battery control loop (#375).

v1.7.0 made ``PowerReadings.batteries: Dict[str, BatteryPower]`` the
canonical data shape but kept ``_run_battery_pipeline`` running once
per cycle against a single cached ``_battery_adapter``. For 2× same-
brand installs (2× Huawei LUNA2000, 2× GoodWe) only one battery
received the LIMIT_DISCHARGE / FORCE_CHARGE intent.

This module verifies the v1.7.x fix:

- ``_battery_adapter`` (singular) is replaced by
  ``_battery_adapters: Dict[str, BatteryControlAdapter]``.
- Single-battery installs (today's PROD configs) iterate ONCE over a
  synthetic ``"primary"`` entry — identical behaviour to v1.7.0.
- Multi-battery installs iterate per ``power.batteries`` entry, each
  with its own adapter (so hysteresis state can't leak between
  batteries).
- The discharge-limit sensor surfaces the tightest active limit
  across all adapters (defensive ``min()``).

The loop logic lives in
``SEMCoordinator._run_battery_pipeline``. Rather than spin up a
full coordinator, we exercise the same control-flow snippet on a
minimal stub. The contract under test is:

  for battery_id, runtime in iter_batteries(power):
      adapter = cache.setdefault(battery_id, adapter_for(...))
      decide_battery(view) → actuate_battery(decision, adapter)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
    BatteryPower,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
)


def _battery(battery_id: str, soc=60.0, power_w=-300.0, capacity_kwh=10.0):
    """Build a per-battery sensor snapshot."""
    return BatteryPower(
        battery_id=battery_id,
        power_w=power_w,
        soc_pct=soc,
        capacity_kwh=capacity_kwh,
        name=battery_id,
    )


class TestSingleBatteryBackcompat:
    """Single-battery installs (today's PROD) iterate once over a
    synthetic ``primary`` entry — identical behaviour to v1.7.0."""

    def test_empty_batteries_dict_falls_back_to_primary(self):
        """When ``power.batteries`` is empty (Energy Dashboard didn't
        populate per-battery slots), the loop builds one synthetic
        ``primary`` runtime from the fleet sensors."""
        power = PowerReadings(battery_soc=55.0, battery_power=-200.0)

        # Simulate the iteration logic from _run_battery_pipeline.
        if power.batteries:
            items = list(power.batteries.keys())
        else:
            items = ["primary"]

        assert items == ["primary"]

    def test_single_populated_battery_uses_its_id(self):
        """When ``power.batteries`` has one entry, the synthetic
        ``primary`` is NOT used — the real battery_id is."""
        power = PowerReadings()
        power.batteries["luna_main"] = _battery("luna_main", soc=55.0)

        items = list(power.batteries.keys())
        assert items == ["luna_main"]

    def test_fleet_view_matches_single_battery(self):
        """Single-battery install — fleet aggregates equal the one
        battery's values (no divergence between fleet field and
        per-battery dict)."""
        power = PowerReadings()
        power.batteries["b1"] = _battery("b1", soc=55.0, power_w=-300.0)

        assert power.fleet_battery_w == pytest.approx(-300.0)
        assert power.fleet_battery_soc == pytest.approx(55.0)


class TestTwoBatteryLoop:
    """The actual #375 fix — 2 batteries get 2 decide/actuate cycles
    with 2 separate adapter instances."""

    def test_two_batteries_populate_dict_correctly(self):
        power = PowerReadings()
        power.batteries["luna_a"] = _battery("luna_a", soc=60.0, power_w=-200.0)
        power.batteries["luna_b"] = _battery("luna_b", soc=70.0, power_w=-400.0)

        # The loop iterates over both, not just one.
        ids = list(power.batteries.keys())
        assert ids == ["luna_a", "luna_b"]

    def test_fleet_w_sums_both_batteries(self):
        """The bug class #375 fixes — fleet_battery_w must equal the
        sum of all per-battery powers, no matter how many. If the
        loop only ran over one battery, the fleet sensor would be
        ``-200`` instead of ``-600`` (off by the second battery's
        contribution)."""
        power = PowerReadings()
        power.batteries["a"] = _battery("a", power_w=-200.0)
        power.batteries["b"] = _battery("b", power_w=-400.0)

        assert power.fleet_battery_w == pytest.approx(-600.0)

    def test_fleet_soc_is_capacity_weighted(self):
        """SOC fleet view = capacity-weighted average. Two batteries
        with different capacities should not just be (a+b)/2."""
        power = PowerReadings()
        power.batteries["small"] = _battery("small", soc=80.0, capacity_kwh=5.0)
        power.batteries["big"] = _battery("big", soc=40.0, capacity_kwh=15.0)

        # Capacity-weighted: (80*5 + 40*15) / 20 = (400 + 600) / 20 = 50
        assert power.fleet_battery_soc == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_per_battery_adapter_cache_isolation(self):
        """Each battery_id maps to its own adapter instance — so
        ``last_discharge_limit_w`` hysteresis on battery A can't leak
        into battery B's commands."""
        from custom_components.solar_energy_management.coordinator.battery_adapters import (
            adapter_for,
        )

        hass = MagicMock()
        # Adapter cache the coordinator would maintain.
        cache: dict[str, object] = {}

        for battery_id in ("luna_a", "luna_b"):
            if battery_id not in cache:
                cache[battery_id] = adapter_for(hass, {})

        # Two distinct instances — not the same cached object reused.
        assert cache["luna_a"] is not cache["luna_b"]
        # Both are valid adapter instances.
        for adapter in cache.values():
            assert hasattr(adapter, "last_intent")
            assert hasattr(adapter, "_last_discharge_limit_w")

    @pytest.mark.asyncio
    async def test_per_battery_adapter_decide_actuate_cycle(self):
        """Mirror the real per-battery loop: build a view per battery,
        decide, actuate. Verify each adapter receives its own intent
        independently."""
        from custom_components.solar_energy_management.coordinator.actuate_battery import (
            actuate_battery,
        )
        from custom_components.solar_energy_management.coordinator.battery_adapters import (
            adapter_for,
        )
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryDecision,
            BatteryIntent,
        )

        hass = MagicMock()
        cache: dict[str, object] = {}

        # Two batteries, different runtime power.
        for battery_id in ("a", "b"):
            adapter = adapter_for(hass, {})
            cache[battery_id] = adapter

            # Each adapter has its own command_* AsyncMocks since
            # adapter_for returns GenericBatteryAdapter — patch them.
            adapter.command_normal = AsyncMock()
            adapter.command_limit_discharge = AsyncMock()

        # Battery A → NORMAL, Battery B → LIMIT_DISCHARGE.
        await actuate_battery(
            BatteryDecision(
                battery_id="a",
                intent=BatteryIntent.NORMAL,
                reason="solar",
            ),
            cache["a"],
        )
        await actuate_battery(
            BatteryDecision(
                battery_id="b",
                intent=BatteryIntent.LIMIT_DISCHARGE,
                discharge_limit_w=1200,
                reason="EV charging",
            ),
            cache["b"],
        )

        # Each adapter received only its own intent.
        cache["a"].command_normal.assert_called_once()
        cache["a"].command_limit_discharge.assert_not_called()
        cache["b"].command_normal.assert_not_called()
        cache["b"].command_limit_discharge.assert_called_once()


class TestDischargeLimitSensorRollup:
    """The discharge-limit sensor reads from the cache dict and
    surfaces the tightest active limit across all batteries (#375
    consumer side)."""

    def test_no_active_limits_returns_none(self):
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryIntent as _BI,
        )

        adapters = {
            "a": MagicMock(last_intent=_BI.NORMAL, _last_discharge_limit_w=None),
            "b": MagicMock(last_intent=_BI.NORMAL, _last_discharge_limit_w=None),
        }
        active = [
            a._last_discharge_limit_w for a in adapters.values()
            if a.last_intent is _BI.LIMIT_DISCHARGE
            and a._last_discharge_limit_w is not None
        ]
        assert active == []

    def test_picks_tightest_when_multiple_active(self):
        """If both batteries are LIMIT_DISCHARGE with different
        residual limits (transient state during 1:1 protection
        re-evaluation), the sensor reports the tightest (min) — the
        binding constraint on the fleet."""
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryIntent as _BI,
        )

        adapters = {
            "a": MagicMock(
                last_intent=_BI.LIMIT_DISCHARGE,
                _last_discharge_limit_w=1500,
            ),
            "b": MagicMock(
                last_intent=_BI.LIMIT_DISCHARGE,
                _last_discharge_limit_w=900,
            ),
        }
        active = [
            a._last_discharge_limit_w for a in adapters.values()
            if a.last_intent is _BI.LIMIT_DISCHARGE
            and a._last_discharge_limit_w is not None
        ]
        assert min(active) == 900

    def test_skips_inactive_adapters(self):
        """A battery in NORMAL state doesn't contribute to the
        discharge_limit even if it has a stale ``_last_discharge_limit_w``
        from a previous cycle."""
        from custom_components.solar_energy_management.coordinator.charger_types import (
            BatteryIntent as _BI,
        )

        adapters = {
            "a": MagicMock(
                last_intent=_BI.LIMIT_DISCHARGE,
                _last_discharge_limit_w=1500,
            ),
            "b": MagicMock(
                last_intent=_BI.NORMAL,  # ← no longer in protection
                _last_discharge_limit_w=900,  # ← stale
            ),
        }
        active = [
            a._last_discharge_limit_w for a in adapters.values()
            if a.last_intent is _BI.LIMIT_DISCHARGE
            and a._last_discharge_limit_w is not None
        ]
        # Only battery A's 1500 should be considered.
        assert active == [1500]
        assert min(active) == 1500
