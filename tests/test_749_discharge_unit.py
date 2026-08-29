"""#749 — the forcible-discharge setpoint validates its UNIT before writing.

praun's report: the "Forcible-discharge power entity" write sent a raw W
value with no unit validation — a kW-native number got 3000 (read: 3000 kW,
clamped to its max = full tilt), and a current-native number would take
watts as amperes. The sibling "Discharge limit entity" path already runs
``_native_power_scale`` (reject non-power units, scale kW, block
current-register names); the setpoint write now consults the SAME helper —
one validation rule, not two.

Refusal is loud and honest: no service call, ``False`` back to the caller
(so intent is never recorded — the #589 honesty contract), and a warning
naming the entity and its unit, once per adapter.
"""
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from custom_components.solar_energy_management.coordinator.battery_adapters.base import (
    BatteryControlAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
)


class _Adapter(BatteryControlAdapter):
    @property
    def max_charge_power_w(self) -> float:
        return 5000.0

    @property
    def max_discharge_power_w(self) -> float:
        return 5000.0

    @property
    def supports_forced_charge(self) -> bool:
        return False

    async def command_normal(self) -> None:
        self._last_intent = BatteryIntent.NORMAL

    async def command_limit_discharge(self, limit_w: float) -> None:  # pragma: no cover
        pass

    async def command_force_charge(self, power_w, target_soc, duration_min) -> None:  # pragma: no cover
        pass

    async def command_stop_force_charge(self) -> None:  # pragma: no cover
        pass


def _hass(state) -> MagicMock:
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=state)
    hass.services.async_call = AsyncMock()
    return hass


def _state(value: str, unit, lo: float, hi: float) -> Mock:
    st = Mock()
    st.state = value
    attrs = {"min": lo, "max": hi}
    if unit is not None:
        attrs["unit_of_measurement"] = unit
    st.attributes = attrs
    return st


def _adapter(hass, entity="number.fd_power") -> _Adapter:
    return _Adapter(
        hass, {"battery_force_discharge_control_entity": entity})


@pytest.mark.asyncio
async def test_kw_entity_gets_the_scaled_native_value():
    """3000 W on a kW-native setpoint must write 3.0, not 3000."""
    hass = _hass(_state("0.0", "kW", -5.0, 5.0))
    await _adapter(hass).command_force_discharge(3000.0, 20.0)
    call = hass.services.async_call.call_args
    assert call is not None
    assert call.args[2]["value"] == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_kw_entity_clamps_in_native_units():
    """A 4400 W ask on a ±2.2 kW setpoint clamps at 2.2 (native), and the
    #531 clamp warning still fires on the mismatch."""
    hass = _hass(_state("0.0", "kW", -2.2, 2.2))
    await _adapter(hass).command_force_discharge(4400.0, 20.0)
    call = hass.services.async_call.call_args
    assert call.args[2]["value"] == pytest.approx(2.2)


@pytest.mark.asyncio
async def test_an_ampere_unit_is_refused():
    hass = _hass(_state("0.0", "A", 0.0, 32.0))
    adapter = _adapter(hass, "number.battery_discharge_current")
    await adapter.command_force_discharge(3000.0, 20.0)
    assert not hass.services.async_call.called
    assert adapter.last_intent is None
    assert adapter.last_error is not None


@pytest.mark.asyncio
async def test_a_current_named_unitless_entity_is_refused():
    hass = _hass(_state("0.0", None, 0.0, 100.0))
    adapter = _adapter(hass, "number.maximum_battery_discharge_current")
    await adapter.command_force_discharge(3000.0, 20.0)
    assert not hass.services.async_call.called
    assert adapter.last_intent is None


@pytest.mark.asyncio
async def test_an_unavailable_entity_is_refused_not_written():
    hass = _hass(_state("unavailable", "W", 0.0, 5000.0))
    adapter = _adapter(hass)
    await adapter.command_force_discharge(3000.0, 20.0)
    assert not hass.services.async_call.called
    assert adapter.last_intent is None


@pytest.mark.asyncio
async def test_a_plain_unitless_number_stays_watts():
    """The historical contract: an explicitly-selected unitless helper
    means watts — unchanged."""
    hass = _hass(_state("0.0", None, 0.0, 10000.0))
    await _adapter(hass).command_force_discharge(3000.0, 20.0)
    assert hass.services.async_call.call_args.args[2]["value"] == pytest.approx(3000.0)


@pytest.mark.asyncio
async def test_dedup_still_works_across_scaled_writes():
    hass = _hass(_state("0.0", "kW", -5.0, 5.0))
    adapter = _adapter(hass)
    await adapter.command_force_discharge(3000.0, 20.0)
    await adapter.command_force_discharge(3010.0, 20.0)  # within 100 W
    assert hass.services.async_call.call_count == 1
