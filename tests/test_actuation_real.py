"""Real-HA framework tests for charger actuation (#462 follow-up).

The pure-mock tests in ``test_actuation_hardening.py`` verify the call
shapes; what they can NOT see is HA's actual service-schema rejection
and the Repair issue lifecycle in a real issue registry. These tests run
against a real ``HomeAssistant`` instance and:

* register a strict-schema ``number.set_value`` that mirrors the real
  one (``entity_id`` + ``value``, extra keys forbidden) — the exact
  schema RienduPre's install bounced off with
  ``extra keys not allowed @ data['current']``;
* register a strict per-integration service that rejects SEM's param to
  drive the failure → Repair → recovery → clear cycle through the REAL
  issue registry.

Framework-tier policy: any future rewrite of ``_set_current`` /
``_record_actuation_failure`` must keep these green.
"""
from __future__ import annotations

import pytest
import voluptuous as vol

from homeassistant.helpers import issue_registry as ir

from custom_components.solar_energy_management.const import DOMAIN
from custom_components.solar_energy_management.devices.base import (
    CurrentControlDevice,
)


def _register_strict_number_set_value(hass, calls: list) -> None:
    """Mirror the real ``number.set_value`` schema: extra keys forbidden."""
    schema = vol.Schema(
        {
            vol.Required("entity_id"): str,
            vol.Required("value"): vol.Coerce(float),
        },
        extra=vol.PREVENT_EXTRA,
    )

    async def _handler(call):
        calls.append(dict(call.data))

    hass.services.async_register("number", "set_value", _handler, schema=schema)


@pytest.mark.asyncio
async def test_number_set_value_service_shape_passes_real_schema(sem_real_hass):
    """service=number.set_value + number target must clear the REAL schema.

    Pre-fix this sent ``{current: X}`` and bounced with
    ``extra keys not allowed @ data['current']`` on every command —
    the charger was silently uncontrollable (#462).
    """
    calls: list = []
    _register_strict_number_set_value(sem_real_hass, calls)

    dev = CurrentControlDevice(
        hass=sem_real_hass,
        device_id="ev_charger_1",
        name="Laadpaal Rechts",
        min_current=6.0,
        max_current=32.0,
        phases=3,
        charger_service="number.set_value",
        current_entity_id="number.wallbox_rechts_max_charging_current_2",
    )
    consumed = await dev._set_current(16)
    await sem_real_hass.async_block_till_done()

    assert calls == [
        {
            "entity_id": "number.wallbox_rechts_max_charging_current_2",
            "value": 16.0,
        },
    ], (
        "#462 regression: the number.set_value service shape did not pass "
        "the real schema — charger would be uncontrollable."
    )
    assert consumed > 0  # 16 A × 3 × 230 V — the write counted as applied


@pytest.mark.asyncio
async def test_actuation_failures_raise_and_clear_real_repair(sem_real_hass):
    """3 schema rejections → Repair in the REAL issue registry; a later
    successful write clears it."""
    # A per-integration service whose schema rejects SEM's default
    # ``current`` param — the #462 failure shape, generalized.
    schema = vol.Schema(
        {vol.Required("amps"): vol.Coerce(float)}, extra=vol.PREVENT_EXTRA,
    )

    async def _handler(call):
        return None

    sem_real_hass.services.async_register(
        "testcharger", "set_max", _handler, schema=schema,
    )

    dev = CurrentControlDevice(
        hass=sem_real_hass,
        device_id="ev_charger_1",
        name="Laadpaal Rechts",
        min_current=6.0,
        max_current=32.0,
        phases=3,
        charger_service="testcharger.set_max",
    )

    issue_id = "charger_actuation_failed_ev_charger_1"
    registry = ir.async_get(sem_real_hass)

    # Three consecutive rejected commands → Repair raised.
    for amps in (10, 11, 12):
        await dev._set_current(amps)
    await sem_real_hass.async_block_till_done()
    issue = registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None, (
        "3 consecutive actuation failures must raise a user-visible Repair "
        "— pre-fix the evidence was buried in per-cycle ERROR log lines."
    )
    assert issue.severity == ir.IssueSeverity.ERROR
    assert issue.translation_key == "charger_actuation_failed"

    # Operator fixes the param name → next write succeeds → Repair clears.
    dev.service_param_name = "amps"
    await dev._set_current(13)
    await sem_real_hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, issue_id) is None, (
        "Repair must clear automatically on the next successful write."
    )
