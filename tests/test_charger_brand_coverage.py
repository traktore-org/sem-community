"""Every supported charger control-pattern is reachable through the NEW
architecture (adapter_for → ChargerReconciler → device actuation).

The decide/reconcile/bridgeable rework + the #548 status-enum work were
shaped around KEBA and Wallbox. This test proves the *other* brands still
"stand a chance to get triggered" — i.e. the reconciler, driving the
brand's adapter, fires an effective charge command and an effective stop
command for each control pattern SEM supports:

  * service-call current   (KEBA → KebaAdapter; Easee/Zaptec → Generic)
  * number-entity current  (Wallbox/go-e/OCPP/Ohme/Alfen/Heidelberg → Generic/Wallbox)
  * start/stop variants     (keba.disable / stop_service / switch / button / select)

A pattern that fires nothing here is a brand that the new architecture
would silently never actuate.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.charger_adapters import (
    GenericAdapter,
    KebaAdapter,
    WallboxAdapter,
    adapter_for,
)
from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    ChargerReconciler,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
    ChargerPower,
)
from custom_components.solar_energy_management.devices.base import (
    CurrentControlDevice,
)


def _device(**attrs):
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.services.has_service = MagicMock(return_value=True)
    hass.states = MagicMock()
    # Enable switches (#536) read their live state; a real switch is "on"
    # while charging. Return an "on" state for any switch/input_boolean so
    # the reconciler doesn't (correctly) refuse to charge an unavailable one.
    _on = MagicMock()
    _on.state = "on"
    hass.states.get = lambda eid: _on if str(eid).startswith(("switch.", "input_boolean.")) else None
    dev = CurrentControlDevice(
        hass=hass, device_id="ev", name=attrs.get("name", "ev"),
        priority=1, min_current=6, max_current=32, phases=3, voltage=230,
        power_entity_id="sensor.ev_power",
        charger_service=attrs.get("charger_service"),
        charger_service_entity_id=attrs.get("charger_service_entity_id"),
        current_entity_id=attrs.get("current_entity_id"),
    )
    for k in ("start_stop_entity", "charge_mode_entity", "charge_mode_start",
              "charge_mode_stop", "start_service", "start_service_data",
              "stop_service", "stop_service_data", "service_param_name",
              "global_services"):
        if k in attrs:
            setattr(dev, k, attrs[k])
    return dev


def _calls(dev):
    return [
        (c.args[0], c.args[1], (c.args[2] if len(c.args) > 2 else {}))
        for c in dev.hass.services.async_call.call_args_list
    ]


def _fired(dev, domain, service):
    return any(d == domain and s == service for d, s, _ in _calls(dev))


async def _charge(dev, adapter):
    rec = ChargerReconciler(charger_id="ev", heartbeat_s=5.0)
    dec = ChargerDecision(charger_id="ev", mode="solar_only",
                          intent=ChargerIntent.CHARGE_AT_AMPS,
                          commanded_amps=10, reason="t", budget_w=0.0)
    await rec.reconcile_and_apply(dec, adapter, ChargerPower(charger_id="ev", power_w=0.0), now=1.0)


async def _stop(dev, adapter):
    rec = ChargerReconciler(charger_id="ev", heartbeat_s=5.0)
    dev._session_active = True
    dec = ChargerDecision(charger_id="ev", mode="off",
                          intent=ChargerIntent.DISABLE,
                          commanded_amps=0, reason="t", budget_w=0.0)
    # OFF + drawing → DISABLE (power above handshake so "drawing" is true).
    await rec.reconcile_and_apply(dec, adapter, ChargerPower(charger_id="ev", power_w=4000.0), now=1.0)


# ── adapter selection ─────────────────────────────────────────────────

class TestAdapterSelection:
    def test_keba_service(self):
        assert isinstance(adapter_for(_device(charger_service="keba.set_current")), KebaAdapter)

    def test_easee_service_is_generic(self):
        a = adapter_for(_device(charger_service="easee.set_charger_dynamic_limit"))
        assert isinstance(a, GenericAdapter) and not isinstance(a, WallboxAdapter)

    def test_zaptec_service_is_generic(self):
        assert type(adapter_for(_device(charger_service="zaptec.stop_charging"))) is GenericAdapter

    def test_wallbox_number_is_wallbox(self):
        a = adapter_for(_device(current_entity_id="number.wallbox_max_current",
                                charger_service_entity_id="number.wallbox_max_current"))
        assert isinstance(a, WallboxAdapter)

    def test_ocpp_number_is_generic(self):
        assert type(adapter_for(_device(current_entity_id="number.ocpp_current"))) is GenericAdapter

    def test_goe_select_is_generic(self):
        assert type(adapter_for(_device(current_entity_id="number.goe_current",
                                        charge_mode_entity="select.goe_mode"))) is GenericAdapter


# ── charge + stop fire for each control pattern ───────────────────────

class TestPatternsTrigger:
    @pytest.mark.asyncio
    async def test_keba_service(self):
        dev = _device(charger_service="keba.set_current",
                      charger_service_entity_id="binary_sensor.keba_plug")
        a = adapter_for(dev)
        await _charge(dev, a)
        assert _fired(dev, "keba", "set_current")
        await _stop(dev, a)
        assert _fired(dev, "keba", "disable")

    @pytest.mark.asyncio
    async def test_easee_service_with_stop_service(self):
        dev = _device(charger_service="easee.set_charger_dynamic_limit",
                      service_param_name="current",
                      start_service="easee.action_command",
                      start_service_data={"action_command": "resume"},
                      stop_service="easee.action_command",
                      stop_service_data={"action_command": "pause"})
        a = adapter_for(dev)
        await _charge(dev, a)
        assert _fired(dev, "easee", "set_charger_dynamic_limit")
        await _stop(dev, a)
        assert _fired(dev, "easee", "action_command")

    @pytest.mark.asyncio
    async def test_number_plus_switch_heidelberg(self):
        dev = _device(current_entity_id="number.heidelberg_current",
                      start_stop_entity="switch.heidelberg_enable")
        a = adapter_for(dev)
        await _charge(dev, a)
        assert _fired(dev, "number", "set_value")
        await _stop(dev, a)
        assert _fired(dev, "switch", "turn_off")

    @pytest.mark.asyncio
    async def test_number_only_ocpp(self):
        dev = _device(current_entity_id="number.ocpp_current")
        a = adapter_for(dev)
        await _charge(dev, a)
        assert _fired(dev, "number", "set_value")
        await _stop(dev, a)
        # No brand stop method → set_current(0) fallback is the stop.
        zero = [v for d, s, v in _calls(dev) if d == "number" and s == "set_value" and v.get("value") == 0]
        assert zero, "OCPP stop must write 0 A via number.set_value"

    @pytest.mark.asyncio
    async def test_select_charge_mode_goe(self):
        dev = _device(current_entity_id="number.goe_current",
                      charge_mode_entity="select.goe_mode",
                      charge_mode_start="now", charge_mode_stop="off")
        a = adapter_for(dev)
        await _charge(dev, a)
        assert _fired(dev, "number", "set_value")          # current
        assert _fired(dev, "select", "select_option")      # start mode
        await _stop(dev, a)
        stop_opt = [v for d, s, v in _calls(dev) if d == "select" and s == "select_option" and v.get("option") == "off"]
        assert stop_opt, "go-e stop must select the stop mode"

    @pytest.mark.asyncio
    async def test_button_start_stop_zaptec(self):
        dev = _device(charger_service="zaptec.set_current",
                      start_stop_entity="button.zaptec_resume_charging")
        a = adapter_for(dev)
        await _stop(dev, a)
        assert _fired(dev, "button", "press")
