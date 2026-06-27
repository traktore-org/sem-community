"""#523 (RienduPre) — a junk ``charger_service`` must not crash control.

His Growatt + 2× Wallbox config carried a stray ``charger_service='0'``
(a leftover with no ``domain.service`` shape; it even propagated to a
sibling charger whose own config was ``None``). The old code reached the
service branch and crashed
``domain, service = self.charger_service.split('.', 1)`` with
"not enough values to unpack (expected 2, got 1)" on EVERY 10 s cycle —
``Failed to set current on Laadpaal Links/Rechts`` — even though both
chargers had a perfectly good ``number.wallbox_*_max_charging_current``
control entity.

Fix: a ``charger_service`` that is not ``domain.service`` is treated as
absent, so control falls through to the number entity.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.solar_energy_management.devices.base import (
    CurrentControlDevice,
)


def _number_state(min_a=6.0, max_a=32.0):
    state = MagicMock()
    state.attributes = {"min": min_a, "max": max_a, "step": 1.0}
    return state


def _device(**kwargs):
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states.get = MagicMock(return_value=_number_state())
    defaults = dict(
        hass=hass, device_id="wb", name="Laadpaal Links",
        min_current=6.0, max_current=32.0, phases=3,
    )
    defaults.update(kwargs)
    return CurrentControlDevice(**defaults)


@pytest.mark.unit
class TestInvalidChargerServiceSanitized:
    def test_dotless_service_nulled_at_construction(self):
        dev = _device(charger_service="0")
        assert dev.charger_service is None

    def test_empty_service_nulled(self):
        dev = _device(charger_service="")
        assert dev.charger_service is None

    def test_whitespace_service_nulled(self):
        dev = _device(charger_service="   ")
        assert dev.charger_service is None

    def test_valid_service_preserved(self):
        dev = _device(charger_service="keba.set_current")
        assert dev.charger_service == "keba.set_current"

    @pytest.mark.asyncio
    async def test_rien_case_writes_number_entity_no_crash(self):
        # Exactly RienduPre's shape: junk service + valid number entity.
        dev = _device(
            charger_service="0",
            current_entity_id="number.wallbox_links_max_charging_current",
        )
        consumed = await dev._set_current(10)
        # Must have written to the number entity — not crashed.
        call = dev.hass.services.async_call.await_args
        assert call.args[0] == "number"
        assert call.args[1] == "set_value"
        assert call.args[2]["entity_id"] == "number.wallbox_links_max_charging_current"
        assert call.args[2]["value"] == 10
        assert dev._current_setpoint == 10
        assert consumed > 0

    @pytest.mark.asyncio
    async def test_dotless_service_does_not_raise_unpack_error(self, caplog):
        dev = _device(
            charger_service="0",
            current_entity_id="number.wallbox_rechts_max_charging_current_2",
        )
        # The old bug logged "Failed to set current ... not enough values
        # to unpack". Assert that message never appears.
        await dev._set_current(8)
        assert not any(
            "not enough values to unpack" in r.message
            or "Failed to set current" in r.message
            for r in caplog.records
        )
