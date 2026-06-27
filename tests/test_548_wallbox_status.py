"""#548 — Wallbox status-enum adapter (evcc-connector concept).

The Wallbox cloud power reading lags the contactor by ~90 s, so a
power-only ``actual_charging`` makes the reconciler read OFF mode as
"already converged" and stop re-issuing the stop while the box is still
charging (the #548 symptom: "EV keeps charging in OFF mode"). The fix
makes the firmware STATUS enum authoritative for both "is it charging?"
and "can SEM control the contactor?" (app-lock detection), mirroring how
evcc's Pulsar connector treats the enum as the source of truth.

These tests need NO hardware — confidence comes from covering every
status string the Wallbox HA integration emits plus the safe
power-based fallback, and from the reconciler read-back-verify loop.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from custom_components.solar_energy_management.coordinator.charger_adapters import (
    WallboxAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    ActionKind,
    ChargerReconciler,
    DesiredState,
    ObservedState,
    observe,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerPower,
)


def _make_device(status_state: str | None = None, status_entity: str = "sensor.wallbox_status",
                 start_stop_entity: str = "", name: str = "wallbox"):
    """Wallbox-like device with a settable status sensor state."""
    device = Mock()
    device.name = name
    device.charger_service = "number.set_value"
    device.charger_service_entity_id = "number.wallbox_pulsar_charging_current"
    device.charger_current_entity = "number.wallbox_pulsar_charging_current"
    device.start_stop_entity = start_stop_entity
    device.charging_status_entity = status_entity
    device.hass = MagicMock()

    states = {}
    if status_state is not None and status_entity:
        states[status_entity] = SimpleNamespace(state=status_state)
    device.hass.states.get = lambda eid: states.get(eid)

    device.hass.services.async_call = AsyncMock()
    device._set_current = AsyncMock()
    device.stop_session = AsyncMock()
    device.start_session = AsyncMock()
    device._session_active = False
    device._current_setpoint = 0
    device.min_current = 6
    device.max_current = 32
    device.phases = 3
    device.voltage = 230
    return device


def _power(w: float) -> ChargerPower:
    return ChargerPower(charger_id="wallbox", power_w=w)


# ── _status_raw ───────────────────────────────────────────────────────

class TestStatusRaw:
    def test_lowercased(self):
        adapter = WallboxAdapter(_make_device(status_state="Charging"))
        assert adapter._status_raw() == "charging"

    def test_titlecase_compound_lowercased(self):
        adapter = WallboxAdapter(
            _make_device(status_state="Waiting in queue by Eco-Smart"))
        assert adapter._status_raw() == "waiting in queue by eco-smart"

    @pytest.mark.parametrize("bad", ["unavailable", "unknown", "", None])
    def test_unreadable_returns_empty(self, bad):
        adapter = WallboxAdapter(_make_device(status_state=bad))
        assert adapter._status_raw() == ""

    def test_no_entity_configured_returns_empty(self):
        adapter = WallboxAdapter(_make_device(status_entity=""))
        assert adapter._status_raw() == ""

    def test_no_hass_returns_empty(self):
        device = _make_device(status_state="Charging")
        device.hass = None
        adapter = WallboxAdapter(device)
        assert adapter._status_raw() == ""


# ── actual_charging — status is authoritative ─────────────────────────

class TestActualCharging:
    @pytest.mark.parametrize("status", ["Charging", "Discharging"])
    def test_charging_states_true_even_at_zero_power(self, status):
        adapter = WallboxAdapter(_make_device(status_state=status))
        # Cloud power not yet reflecting the contactor — status wins.
        assert adapter.actual_charging(_power(0)) is True

    @pytest.mark.parametrize(
        "status",
        ["Paused", "Ready", "Waiting", "Waiting for car demand",
         "Connected", "Disconnected", "No car connected"],
    )
    def test_idle_states_false_even_with_lagging_high_power(self, status):
        adapter = WallboxAdapter(_make_device(status_state=status))
        # Cloud power lagging high after a stop — status says it's done.
        assert adapter.actual_charging(_power(5000)) is False

    @pytest.mark.parametrize(
        "status",
        ["Locked", "Locked, car connected", "Scheduled",
         "Waiting in queue by Eco-Smart",
         "Waiting in queue by Power Sharing",
         "Waiting in queue by Power Boost"],
    )
    def test_locked_states_are_not_charging(self, status):
        adapter = WallboxAdapter(_make_device(status_state=status))
        assert adapter.actual_charging(_power(0)) is False

    @pytest.mark.parametrize("status", ["Error", "Updating", "Unknown",
                                        "Waiting MID failed"])
    def test_error_states_fall_back_to_power(self, status):
        adapter = WallboxAdapter(_make_device(status_state=status))
        assert adapter.actual_charging(_power(5000)) is True   # power>handshake
        assert adapter.actual_charging(_power(100)) is False   # power<handshake

    def test_no_status_sensor_falls_back_to_power(self):
        adapter = WallboxAdapter(_make_device(status_entity=""))
        assert adapter.actual_charging(_power(5000)) is True
        assert adapter.actual_charging(_power(100)) is False

    def test_unavailable_status_falls_back_to_power(self):
        adapter = WallboxAdapter(_make_device(status_state="unavailable"))
        assert adapter.actual_charging(_power(5000)) is True
        assert adapter.actual_charging(_power(100)) is False


# ── enable_state — app-lock detection from the status enum ────────────

class TestEnableState:
    @pytest.mark.parametrize(
        "status",
        ["Locked", "Locked, car connected", "Scheduled",
         "Waiting in queue by Eco-Smart",
         "Waiting in queue by Power Sharing",
         "Waiting in queue by Power Boost"],
    )
    def test_locked_status_reports_uncontrollable(self, status):
        adapter = WallboxAdapter(_make_device(status_state=status))
        enabled, controllable = adapter.enable_state()
        assert enabled is None
        assert controllable is False

    def test_charging_status_defers_to_switch(self):
        # No start/stop switch configured → base returns (None, True).
        adapter = WallboxAdapter(_make_device(status_state="Charging"))
        assert adapter.enable_state() == (None, True)

    def test_no_status_defers_to_switch(self):
        adapter = WallboxAdapter(_make_device(status_entity=""))
        assert adapter.enable_state() == (None, True)

    def test_locked_overrides_a_present_switch(self):
        # Even if a switch reads "on", a locked status means SEM can't
        # actually drive the contactor — surface it.
        device = _make_device(
            status_state="Waiting in queue by Eco-Smart",
            start_stop_entity="switch.wallbox_pause_resume")
        device.hass.states.get = lambda eid: {
            "sensor.wallbox_status": SimpleNamespace(
                state="Waiting in queue by Eco-Smart"),
            "switch.wallbox_pause_resume": SimpleNamespace(state="on"),
        }.get(eid)
        adapter = WallboxAdapter(device)
        assert adapter.enable_state() == (None, False)


# ── reconciler OFF path — surface app-lock instead of futile DISABLE ──

def _rec() -> ChargerReconciler:
    return ChargerReconciler(charger_id="wallbox", heartbeat_s=5.0,
                             idle_disable_threshold=4)


class TestReconcilerOffPath:
    def test_off_drawing_controllable_issues_disable(self):
        obs = ObservedState(charging=True, setpoint_a=0, self_charging=False,
                            power_w=5000, enabled=None, enable_controllable=True)
        actions = _rec().reconcile(DesiredState.OFF, 0, obs, now=100.0)
        assert [a.kind for a in actions] == [ActionKind.DISABLE]

    def test_off_drawing_uncontrollable_surfaces(self):
        obs = ObservedState(charging=True, setpoint_a=0, self_charging=False,
                            power_w=5000, enabled=None, enable_controllable=False)
        actions = _rec().reconcile(DesiredState.OFF, 0, obs, now=100.0)
        assert [a.kind for a in actions] == [ActionKind.REPORT_ENABLE_BLOCKED]

    def test_off_not_drawing_is_converged(self):
        # Even if uncontrollable, when nothing is drawing there's nothing
        # to surface — already where we want to be.
        obs = ObservedState(charging=False, setpoint_a=0, self_charging=False,
                            power_w=0, enabled=None, enable_controllable=False)
        actions = _rec().reconcile(DesiredState.OFF, 0, obs, now=100.0)
        assert [a.kind for a in actions] == [ActionKind.NONE]


# ── End-to-end: read-back-verify loop through observe()+reconcile() ───

class TestReadBackVerifyLoop:
    def test_off_keeps_disabling_until_status_confirms_stopped(self):
        """The #548 fix in one test: with power lagging at 0 W the whole
        time, status drives the loop — DISABLE while status=Charging,
        NONE once status=Paused. A power-only adapter would converge to
        NONE on cycle 1 and the box would keep charging."""
        device = _make_device(status_state="Charging")
        adapter = WallboxAdapter(device)
        rec = _rec()
        power = _power(0)  # cloud power never moves off 0 in this window

        # Cycle 1: status=Charging → observe charging=True → DISABLE.
        obs = observe(adapter, power)
        assert obs.charging is True
        actions = rec.reconcile(DesiredState.OFF, 0, obs, now=1.0)
        assert [a.kind for a in actions] == [ActionKind.DISABLE]

        # Contactor opens; cloud status catches up to Paused next poll.
        device.hass.states.get = lambda eid: {
            "sensor.wallbox_status": SimpleNamespace(state="Paused"),
        }.get(eid)

        # Cycle 2: status=Paused → observe charging=False → converged.
        obs = observe(adapter, power)
        assert obs.charging is False
        actions = rec.reconcile(DesiredState.OFF, 0, obs, now=2.0)
        assert [a.kind for a in actions] == [ActionKind.NONE]

    def test_eco_smart_lock_surfaces_through_observe(self):
        """An Eco-Smart-locked box that's still charging surfaces a
        REPORT_ENABLE_BLOCKED (SEM can't stop it) rather than spinning."""
        device = _make_device(status_state="Charging")
        adapter = WallboxAdapter(device)
        rec = _rec()

        # Box is charging but the firmware is in Eco-Smart queue control.
        device.hass.states.get = lambda eid: {
            "sensor.wallbox_status": SimpleNamespace(
                state="Waiting in queue by Eco-Smart"),
        }.get(eid)
        obs = observe(adapter, _power(0))
        # Eco-Smart queue = not charging AND not controllable.
        assert obs.charging is False
        assert obs.enable_controllable is False
        # When it IS drawing under the lock, OFF surfaces rather than DISABLE.
        obs_drawing = ObservedState(
            charging=False, setpoint_a=0, self_charging=True, power_w=4000,
            enabled=obs.enabled, enable_controllable=False)
        actions = rec.reconcile(DesiredState.OFF, 0, obs_drawing, now=1.0)
        assert [a.kind for a in actions] == [ActionKind.REPORT_ENABLE_BLOCKED]
