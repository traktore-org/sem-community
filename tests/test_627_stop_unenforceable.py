"""#627 — EV keeps charging in 'off' mode because nothing can stop it.

onkelfu's diagnostics: ``charge_mode: "off"`` on both chargers,
``last_desired: "OFF"``, ``last_actions: ["DISABLE"]``,
``stop_commanded_while_drawing: 130`` — while the car pulled 4068 W with
3477 W of it coming out of the house batteries, at night.

The mode was right and the stop WAS commanded. It just could not land.
Two layers each deferred the stop to the other:

  * ``_set_current(0)`` skips the write when the control number's ``min``
    is above 0 (#487) — "the actual stop is the adapter's job".
  * ``stop_session()`` finds no brand mechanism configured and warns that
    it is "relying on ``_set_current(0)`` alone" — the write that was
    skipped.

On a charger configured with ONLY a ``number.*`` current entity whose min
is 6 A, that composes to: nothing stops it at all. These tests pin the
capability probe (``can_stop_charging``), its propagation into
``ObservedState``, the reconciler row that surfaces it, and — the
regression this design deliberately avoids — that CHARGE is untouched.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    ActionKind,
    ChargerReconciler,
    DesiredState,
    ObservedState,
    observe,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
    ChargerPower,
)
from custom_components.solar_energy_management.devices.base import CurrentControlDevice


def _number_state(min_a=6.0, max_a=16.0):
    state = MagicMock()
    state.attributes = {"min": min_a, "max": max_a, "step": 1.0}
    return state


# Set post-construction (they are plain attributes, not ctor kwargs).
_ATTRS = ("start_stop_entity", "charge_mode_entity", "charge_mode_stop",
          "stop_service", "charger_service")


def _device(min_a=6.0, **kwargs):
    """onkelfu's shape: a GenericAdapter with only a current number entity."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.services.has_service = MagicMock(return_value=False)
    attrs = {k: kwargs.pop(k) for k in _ATTRS if k in kwargs}
    defaults = dict(
        hass=hass, device_id="wb_einfahrt", name="Wallbox Einfahrt",
        min_current=6.0, max_current=16.0, phases=3,
        current_entity_id="number.wb_einfahrt_ladestrom",
    )
    defaults.update(kwargs)
    dev = CurrentControlDevice(**defaults)
    for key, value in attrs.items():
        setattr(dev, key, value)
    dev.hass.states.get = MagicMock(return_value=_number_state(min_a, 16.0))
    return dev


@pytest.mark.unit
class TestCapabilityProbe:
    def test_number_only_min6_cannot_stop(self):
        # THE reported install. No stop_service, no charge-mode entity, no
        # start/stop switch, no <domain>.disable — and 0 A is unwritable.
        assert _device(min_a=6.0).can_stop_charging() is False

    def test_number_min0_can_stop(self):
        # Same charger, entity that can express 0 A: the 0 A write lands.
        assert _device(min_a=0.0).can_stop_charging() is True

    def test_start_stop_switch_can_stop(self):
        dev = _device(min_a=6.0, start_stop_entity="switch.wb_einfahrt_charging")
        assert dev.can_stop_charging() is True

    def test_charge_mode_entity_needs_a_stop_value(self):
        # A mode entity with no configured stop option is not a mechanism.
        assert _device(min_a=6.0, charge_mode_entity="select.wb_mode").can_stop_charging() is False
        dev = _device(min_a=6.0, charge_mode_entity="select.wb_mode", charge_mode_stop="Off")
        assert dev.can_stop_charging() is True

    def test_stop_service_can_stop(self):
        assert _device(min_a=6.0, stop_service="wallbox.pause").can_stop_charging() is True

    def test_keba_disable_service_can_stop(self):
        # KEBA has no current entity at all — it stops via keba.disable.
        dev = _device(min_a=6.0, current_entity_id=None, charger_service="keba.set_current")
        dev.hass.services.has_service = MagicMock(
            side_effect=lambda d, s: d == "keba" and s == "disable"
        )
        assert dev.can_stop_charging() is True

    def test_no_control_at_all_cannot_stop(self):
        assert _device(min_a=6.0, current_entity_id=None).can_stop_charging() is False

    def test_unreadable_entity_does_not_cry_wolf(self):
        # Unknown bounds → assume the stop works. A false repair on every
        # charger whose entity is briefly unavailable would be worse than
        # the bug: it trains users to ignore the issue that matters.
        dev = _device(min_a=6.0)
        dev.hass.states.get = MagicMock(return_value=None)
        assert dev.can_stop_charging() is True


def _adapter(device, power_w):
    a = MagicMock()
    a._device = device
    a.actual_charging = MagicMock(return_value=power_w > 500)
    a.is_self_charging = MagicMock(return_value=False)
    a.enable_state = MagicMock(return_value=(True, True))
    a.max_current_a = 16
    a.command_disable = AsyncMock()
    a.command_current = AsyncMock()
    a.command_idle = AsyncMock()
    a.command_max = AsyncMock()
    a.arm_failsafe = AsyncMock()
    a.ensure_enabled = AsyncMock()
    return a


def _power(w=4068.0):
    return ChargerPower(charger_id="wb_einfahrt", power_w=w)


@pytest.mark.unit
class TestObservePropagation:
    def test_observe_carries_the_capability(self):
        assert observe(_adapter(_device(min_a=6.0), 4068), _power()).stop_controllable is False
        assert observe(_adapter(_device(min_a=0.0), 4068), _power()).stop_controllable is True

    def test_adapter_without_the_method_is_assumed_stoppable(self):
        # Back-compat: every adapter predating #627, and every MagicMock
        # device in the existing suite, keeps the old behaviour.
        a = _adapter(_device(min_a=6.0), 4068)
        a._device = object()  # no can_stop_charging attribute
        assert observe(a, _power()).stop_controllable is True

    def test_probe_raising_is_assumed_stoppable(self):
        a = _adapter(_device(min_a=6.0), 4068)
        a._device.can_stop_charging = MagicMock(side_effect=RuntimeError("boom"))
        assert observe(a, _power()).stop_controllable is True


def _observed(stop_controllable, charging=True):
    return ObservedState(
        charging=charging,
        setpoint_a=6,
        self_charging=False,
        power_w=4068.0 if charging else 0.0,
        enabled=True,
        enable_controllable=True,
        stop_controllable=stop_controllable,
    )


@pytest.mark.unit
class TestReconcilerRow:
    def test_off_and_drawing_and_unstoppable_reports(self):
        rec = ChargerReconciler(charger_id="wb_einfahrt", heartbeat_s=5.0)
        actions = rec.reconcile(DesiredState.OFF, 0, _observed(False), now=1.0)
        kinds = [a.kind for a in actions]
        # DISABLE still issued — it costs nothing and starts working the
        # moment a stop entity is configured — but no longer silently.
        assert kinds == [ActionKind.DISABLE, ActionKind.REPORT_STOP_UNENFORCEABLE]

    def test_idle_and_drawing_and_unstoppable_reports(self):
        # The battery drains identically whether the reason is OFF or IDLE.
        rec = ChargerReconciler(charger_id="wb_einfahrt", heartbeat_s=5.0)
        actions = rec.reconcile(DesiredState.IDLE, 0, _observed(False), now=1.0)
        assert [a.kind for a in actions] == [
            ActionKind.DISABLE, ActionKind.REPORT_STOP_UNENFORCEABLE,
        ]

    def test_stoppable_charger_is_unchanged(self):
        rec = ChargerReconciler(charger_id="wb", heartbeat_s=5.0)
        actions = rec.reconcile(DesiredState.OFF, 0, _observed(True), now=1.0)
        assert [a.kind for a in actions] == [ActionKind.DISABLE]

    def test_not_drawing_never_reports(self):
        # Converged is converged. An unstoppable charger that is not
        # charging is not a problem anyone needs a red repair about.
        rec = ChargerReconciler(charger_id="wb", heartbeat_s=5.0)
        actions = rec.reconcile(DesiredState.OFF, 0, _observed(False, charging=False), now=1.0)
        assert [a.kind for a in actions] == [ActionKind.NONE]

    def test_charge_rows_are_untouched(self):
        # THE regression this design avoids. Reusing enable_controllable for
        # the #627 signal would have short-circuited the CHARGE rows to
        # REPORT — every number-entity-only charger would have lost surplus
        # charging entirely to fix a stop bug.
        rec = ChargerReconciler(charger_id="wb_einfahrt", heartbeat_s=5.0)
        actions = rec.reconcile(DesiredState.CHARGE, 10, _observed(False), now=1.0)
        kinds = [a.kind for a in actions]
        assert ActionKind.REPORT_STOP_UNENFORCEABLE not in kinds
        assert kinds != [ActionKind.NONE]


def _off():
    return ChargerDecision(charger_id="wb_einfahrt", mode="off",
                           intent=ChargerIntent.DISABLE, commanded_amps=0,
                           reason="off", budget_w=0.0)


@pytest.mark.unit
class TestRepairIssue:
    @pytest.mark.asyncio
    async def test_repair_raised_while_drawing_and_cleared_when_stopped(self):
        rec = ChargerReconciler(charger_id="wb_einfahrt", heartbeat_s=5.0)
        dev = _device(min_a=6.0)
        a = _adapter(dev, 4068)
        raised, cleared = [], []
        mod = "custom_components.solar_energy_management.coordinator.repair_issues"
        import importlib
        ri = importlib.import_module(mod)

        def _raise(hass, device_id, **kw):
            raised.append((device_id, kw))

        def _clear(hass, device_id):
            cleared.append(device_id)

        real_raise = ri.raise_charger_stop_unenforceable
        real_clear = ri.clear_charger_stop_unenforceable
        ri.raise_charger_stop_unenforceable = _raise
        ri.clear_charger_stop_unenforceable = _clear
        try:
            await rec.reconcile_and_apply(
                _off(), a, ChargerPower(charger_id="wb_einfahrt", power_w=4068.0), now=1.0)
            assert raised, "no repair filed while the car drew 4 kW against a stop"
            device_id, kw = raised[0]
            assert device_id == "wb_einfahrt"
            assert kw["name"] == "Wallbox Einfahrt"
            assert kw["power_w"] == pytest.approx(4068.0)
            assert kw["entity"] == "number.wb_einfahrt_ladestrom"

            a.actual_charging = MagicMock(return_value=False)
            await rec.reconcile_and_apply(
                _off(), a, ChargerPower(charger_id="wb_einfahrt", power_w=0.0), now=2.0)
            assert cleared == ["wb_einfahrt"]
        finally:
            ri.raise_charger_stop_unenforceable = real_raise
            ri.clear_charger_stop_unenforceable = real_clear
