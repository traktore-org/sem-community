"""#915 — did the battery control write TAKE?

A declared key says what a register is CALLED. It cannot say whether the
register accepts a write, expires it after sixty minutes, needs an enable
switch first, or is a global setting the vendor says to leave alone —
@Azlinon named four such on one EG4. That answer exists only after the first
write, and a register that ignores a write raises nothing (#824, from the
other side of the wire). So the generic adapter — the one a roster proposal
lands on — records each write and judges it on the next cycle, in the
entity's own unit, and the coordinator turns three misses into a Repair.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator.battery_adapters.base import (
    BatteryControlAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)


def _hass(state=None):
    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.get = MagicMock(return_value=state)
    return hass


def _state(value, unit="W", **attrs):
    return SimpleNamespace(state=str(value),
                           attributes={"unit_of_measurement": unit, **attrs})


def _adapter(hass):
    return GenericBatteryAdapter(hass, {
        "battery_discharge_control_entity": "number.limit",
    })


@pytest.mark.unit
class TestTheGenericAdapterJudgesItsOwnWrite:

    def test_nothing_pending_is_no_verdict(self):
        assert _adapter(_hass()).verify_pending_write() is None

    def test_a_write_is_not_judged_before_the_grace(self):
        """Integrations poll; the entity cannot reflect a write instantly."""
        ad = _adapter(_hass(_state(2000)))
        ad._note_pending_write("number.limit", 3000.0)
        assert ad.verify_pending_write() is None

    def test_a_reflected_write_is_true_and_resets_strikes(self):
        ad = _adapter(_hass(_state(3000)))
        ad.write_not_taken_strikes = 2
        ad._note_pending_write("number.limit", 3000.0)
        with patch("time.monotonic", return_value=1e9):
            assert ad.verify_pending_write() is True
        assert ad.write_not_taken_strikes == 0
        assert ad.last_unverified_entity == ""

    def test_a_write_the_register_ignored_is_false_and_strikes(self):
        ad = _adapter(_hass(_state(5000)))
        ad._note_pending_write("number.limit", 1200.0)
        with patch("time.monotonic", return_value=1e9):
            assert ad.verify_pending_write() is False
        assert ad.write_not_taken_strikes == 1
        assert ad.last_unverified_entity == "number.limit"
        assert ad.last_unverified_wanted == "1200 W"
        assert ad.last_unverified_seen == "5000 W"
        assert "not reflected" in ad.last_error

    def test_kilowatts_are_compared_in_kilowatts(self):
        ad = _adapter(_hass(_state(3.0, unit="kW")))
        ad._note_pending_write("number.limit", 3000.0)
        with patch("time.monotonic", return_value=1e9):
            assert ad.verify_pending_write() is True

    def test_a_register_that_clamps_to_its_own_max_is_reflected(self):
        """Asking 6000 of a 5000-max register and reading 5000 is the
        register doing its job, not ignoring the write."""
        ad = _adapter(_hass(_state(5000, max=5000)))
        ad._note_pending_write("number.limit", 6000.0)
        with patch("time.monotonic", return_value=1e9):
            assert ad.verify_pending_write() is True

    def test_a_write_is_judged_once(self):
        ad = _adapter(_hass(_state(5000)))
        ad._note_pending_write("number.limit", 1200.0)
        with patch("time.monotonic", return_value=1e9):
            assert ad.verify_pending_write() is False
            assert ad.verify_pending_write() is None

    def test_an_entity_that_vanished_counts_as_not_reflected(self):
        ad = _adapter(_hass(None))
        ad._note_pending_write("number.limit", 1200.0)
        with patch("time.monotonic", return_value=1e9):
            assert ad.verify_pending_write() is False
        assert ad.last_unverified_seen == "missing"

    def test_other_adapters_are_untouched(self):
        """Deye has its own read-back; Huawei writes through its own path.
        The base default says 'nothing to judge' and carries zero strikes."""
        class Plain(BatteryControlAdapter):
            async def command_normal(self): ...
            async def command_limit_discharge(self, watts): ...
            async def command_force_charge(self, *a, **k): ...
            async def command_stop_force_charge(self): ...
            @property
            def max_charge_power_w(self): return 0.0
            @property
            def max_discharge_power_w(self): return 0.0
            @property
            def supports_forced_charge(self): return False
        ad = Plain(_hass(), {})
        assert ad.verify_pending_write() is None
        assert ad.write_not_taken_strikes == 0


@pytest.mark.unit
class TestThreeMissesBecomeARepairOnce:
    """Same three-strike shape as #824/#840, on the read-back side."""

    def _coord(self):
        c = SimpleNamespace(hass=MagicMock(),
                            BATTERY_WRITE_STRIKES=SEMCoordinator.BATTERY_WRITE_STRIKES)
        return c

    def _adapter(self, strikes, entity="number.limit"):
        return SimpleNamespace(write_not_taken_strikes=strikes,
                               last_unverified_entity=entity,
                               last_unverified_wanted="1200 W",
                               last_unverified_seen="5000 W")

    def test_two_misses_raise_nothing(self):
        c = self._coord()
        with patch("custom_components.solar_energy_management.coordinator.repair_issues"
                   ".raise_battery_control_write_not_taken") as raise_:
            SEMCoordinator._raise_or_clear_battery_write_repair(
                c, self._adapter(2), False)
        raise_.assert_not_called()

    def test_the_third_miss_raises_exactly_once(self):
        c = self._coord()
        with patch("custom_components.solar_energy_management.coordinator.repair_issues"
                   ".raise_battery_control_write_not_taken") as raise_:
            SEMCoordinator._raise_or_clear_battery_write_repair(
                c, self._adapter(3), False)
            SEMCoordinator._raise_or_clear_battery_write_repair(
                c, self._adapter(4), False)
        assert raise_.call_count == 1
        kw = raise_.call_args.kwargs
        assert kw["entity_id"] == "number.limit"
        assert kw["wanted"] == "1200 W" and kw["seen"] == "5000 W"

    def test_a_reflected_write_clears_it(self):
        c = self._coord()
        with patch("custom_components.solar_energy_management.coordinator.repair_issues"
                   ".raise_battery_control_write_not_taken"), \
             patch("custom_components.solar_energy_management.coordinator.repair_issues"
                   ".clear_battery_control_write_not_taken") as clear:
            SEMCoordinator._raise_or_clear_battery_write_repair(
                c, self._adapter(3), False)
            SEMCoordinator._raise_or_clear_battery_write_repair(
                c, self._adapter(0, entity=""), True)
        clear.assert_called_once()
        assert clear.call_args.args[1] == "number.limit"
        assert not c._battery_write_repair_raised

    def test_no_verdict_touches_nothing(self):
        c = self._coord()
        with patch("custom_components.solar_energy_management.coordinator.repair_issues"
                   ".raise_battery_control_write_not_taken") as raise_, \
             patch("custom_components.solar_energy_management.coordinator.repair_issues"
                   ".clear_battery_control_write_not_taken") as clear:
            SEMCoordinator._raise_or_clear_battery_write_repair(
                c, self._adapter(5), None)
        raise_.assert_not_called(); clear.assert_not_called()
