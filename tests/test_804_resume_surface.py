"""#804 (2.1 rework, B4a) — buttons become a first-class enable surface.

The gap, live-diagnosed on both reporters' hardware: a ``button.`` start
entity was INVISIBLE to the adapter layer — ``enable_state()`` filed it under
"no enable surface" and ``ensure_enabled()`` early-returned — while the only
code that ever pressed one (``devices/base.py``) string-mangled the entity id
(``resume``→``stop``…) and was reachable only when no session was active. So
after a latching stop (a Zaptec hard stop, a Wattpilot force-state), SEM
raised the current and nothing pressed resume, ever.

The fix rides EXISTING machinery instead of adding a resume subsystem:
``ensure_enabled()`` learns ``button.`` → press what the user named, no
string-mangling; the reconciler's ENABLE action, with its retry/backoff
budget (max_enable_attempts, enable_retry_interval_s), then paces the
presses. Zaptec recovery-after-hard-stop and the Wattpilot latch ride one
path — per-brand only in WHICH entity is named, never in new code paths.
"""
from __future__ import annotations

import asyncio

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.solar_energy_management.coordinator.charger_adapters.generic import (
    GenericAdapter,
)


def _adapter(start_stop="button.zaptec_resume_charging"):
    dev = MagicMock()
    dev.start_stop_entity = start_stop
    dev.hass = SimpleNamespace(
        states=SimpleNamespace(get=MagicMock(return_value=None)),
        services=SimpleNamespace(async_call=AsyncMock()),
    )
    dev._session_active = False
    a = GenericAdapter.__new__(GenericAdapter)
    a._device = dev
    return a


class TestButtonsAreAnEnableSurface:
    def test_ensure_enabled_presses_the_named_button(self):
        a = _adapter("button.guido_coppes_lader_hervat_laden")
        asyncio.run(a.ensure_enabled())
        call = a._device.hass.services.async_call.await_args
        assert call is not None, (
            "ensure_enabled still early-returns for button. — the resume "
            "surface gap (#804 B4a)"
        )
        assert call.args[0] == "button" and call.args[1] == "press"
        assert call.args[2] == {
            "entity_id": "button.guido_coppes_lader_hervat_laden"}

    def test_no_string_mangling_ever(self):
        """The old devices/base path rewrote resume→stop in the entity id.
        The adapter presses EXACTLY what the user named."""
        a = _adapter("button.wattpilot_start_charging")
        asyncio.run(a.ensure_enabled())
        call = a._device.hass.services.async_call.await_args
        assert call.args[2]["entity_id"] == "button.wattpilot_start_charging"

    def test_switch_behaviour_unchanged(self):
        a = _adapter("switch.wallbox_pause_resume")
        asyncio.run(a.ensure_enabled())
        call = a._device.hass.services.async_call.await_args
        assert call.args[0] == "switch" and call.args[1] == "turn_on"

    def test_enable_state_for_a_button_stays_not_applicable(self):
        """A button has no readable state — (None, True) remains correct;
        the reconciler infers progress from observed charging, and the
        ENABLE retry budget paces the presses."""
        a = _adapter("button.zaptec_resume_charging")
        assert a.enable_state() == (None, True)

    def test_session_marked_active_after_press(self):
        a = _adapter("button.zaptec_resume_charging")
        asyncio.run(a.ensure_enabled())
        assert a._device._session_active is True


class TestTheManglerIsGone:
    def test_devices_base_no_longer_rewrites_button_ids(self):
        import inspect
        from custom_components.solar_energy_management.devices import base
        src = inspect.getsource(base)
        assert 'replace("resume", "stop")' not in src and \
               'replace("_stop", "_stop_charging")' not in src, (
            "the fragile button-id rewriter survived (#804 B4a)"
        )


class TestWattpilotRow:
    """(B4b) The Wattpilot brand row gains the two surfaces its reporter's
    hardware actually needs: the frc/force-state select (the go-e firmware
    family's start/stop, mirrored from goecharger_mqtt) and a start/resume
    button for B4a's press path. Option VALUES for the select are left
    unconfigured on purpose — the integration's option labels vary by
    version, and a guessed label is the mangler bug in select form; the
    entity is surfaced and the reporter confirms the labels."""

    def _discover(self, entries):
        from unittest.mock import MagicMock, patch
        from custom_components.solar_energy_management.hardware_detection import (
            discover_all_ev_chargers_from_registry,
        )
        registry = MagicMock()
        registry.entities.values.return_value = entries
        with patch(
            "custom_components.solar_energy_management.hardware_detection."
            "entity_registry.async_get",
            return_value=registry,
        ):
            return discover_all_ev_chargers_from_registry(MagicMock())

    def _entry(self, eid, dc=None):
        from types import SimpleNamespace
        return SimpleNamespace(entity_id=eid, platform="wattpilot",
                               device_id="wp-1", unique_id=eid.split(".", 1)[1],
                               original_device_class=dc, disabled_by=None)

    def test_frc_select_and_resume_button_are_mapped(self):
        found = self._discover([
            self._entry("sensor.wattpilot_charging_power", "power"),
            self._entry("binary_sensor.wattpilot_car_connected", "plug"),
            self._entry("number.wattpilot_charging_current", "current"),
            self._entry("select.wattpilot_frc_force_state"),
            self._entry("button.wattpilot_resume_charging"),
        ])
        assert len(found) == 1
        c = found[0]
        assert c.get("ev_charge_mode_entity") == "select.wattpilot_frc_force_state"
        assert c.get("ev_start_stop_entity") == "button.wattpilot_resume_charging"
        assert "ev_charge_mode_start" not in c, (
            "a guessed option label is the mangler bug in select form"
        )


class TestZaptecThresholdSuggestion:
    """(B4c) The installation's three_to_one_phase_switch_current is the
    brand's phase selector (EVCC's Go2 path: 32 A → 1-phase, 0 → 3-phase).
    Detection SUGGESTS it — entity + values — and never auto-configures:
    the user confirms it in the flow."""

    def _discover(self, entries):
        from unittest.mock import MagicMock, patch
        from custom_components.solar_energy_management.hardware_detection import (
            discover_all_ev_chargers_from_registry,
        )
        registry = MagicMock()
        registry.entities.values.return_value = entries
        with patch(
            "custom_components.solar_energy_management.hardware_detection."
            "entity_registry.async_get",
            return_value=registry,
        ):
            return discover_all_ev_chargers_from_registry(MagicMock())

    def _entries(self):
        from types import SimpleNamespace
        def e(eid, plat, dev, uid, dc=None):
            return SimpleNamespace(entity_id=eid, platform=plat, device_id=dev,
                                   unique_id=uid, original_device_class=dc,
                                   disabled_by=None)
        return [
            e("binary_sensor.guido_coppes_lader_kabel_aangesloten", "zaptec",
              "charger-1", "chg1_cable_connected", "plug"),
            e("binary_sensor.guido_coppes_lader_bezig_met_laden", "zaptec",
              "charger-1", "chg1_charging"),
            e("sensor.guido_coppes_lader_laadvermogen", "zaptec",
              "charger-1", "chg1_charge_power", "power"),
            e("number.guido_coppes_lader_maximale_laadstroom", "zaptec",
              "charger-1", "chg1_charger_max_current", "current"),
            # the INSTALLATION device
            e("number.guido_coppes_terugschakelen_van_drie_naar_een_fase",
              "zaptec", "install-1",
              "inst1_three_to_one_phase_switch_current", "current"),
        ]

    def test_the_installation_threshold_is_suggested_with_values(self):
        found = [c for c in self._discover(self._entries())
                 if c.get("_device_id") == "charger-1"]
        assert found
        sug = found[0].get("_suggested_phase_switch")
        assert sug, "the threshold entity was not suggested (#804 B4c)"
        assert sug["entity"] == \
            "number.guido_coppes_terugschakelen_van_drie_naar_een_fase"
        assert sug["value_1p"] == "32" and sug["value_3p"] == "0"

    def test_it_is_never_auto_configured(self):
        found = [c for c in self._discover(self._entries())
                 if c.get("_device_id") == "charger-1"]
        assert found[0].get("ev_phase_switch_entity") is None, (
            "the phase selector was auto-written — it must stay a "
            "SUGGESTION the user confirms (#804 B4c)"
        )


class TestGuardLearnsBelievedPhases:
    """(B4d, #843 folded in) A 3→1 switch lands the whole load on one
    conductor. The guard clamps per-phase amps but read STATIC nameplate
    phases — the belief knows the truth and now feeds it."""

    def _guard(self):
        from custom_components.solar_energy_management.coordinator.active_phase_guard import (
            ActivePhaseGuard,
        )
        g = ActivePhaseGuard.__new__(ActivePhaseGuard)
        return g

    def test_believed_phases_override_nameplate(self):
        from types import SimpleNamespace
        from custom_components.solar_energy_management.coordinator.active_phase_guard import (
            ActivePhaseGuard,
        )
        adapter = SimpleNamespace(phases=3, voltage=230.0,
                                  min_current_a=6, max_current_a=16)
        power = SimpleNamespace(power_w=3680.0)
        ctx3 = ActivePhaseGuard._actuation_context(adapter, power)
        ctx1 = ActivePhaseGuard._actuation_context(
            adapter, power, believed_phases=1)
        assert ctx3 is not None and ctx1 is not None
        # same watts on ONE conductor = 3x the per-phase current
        assert abs(ctx1[4] - 3.0 * ctx3[4]) < 0.01, (
            "believed phases did not change the per-phase current (#804 B4d)"
        )

    def test_absent_belief_falls_back_to_nameplate(self):
        from types import SimpleNamespace
        from custom_components.solar_energy_management.coordinator.active_phase_guard import (
            ActivePhaseGuard,
        )
        adapter = SimpleNamespace(phases=3, voltage=230.0,
                                  min_current_a=6, max_current_a=16)
        power = SimpleNamespace(power_w=3680.0)
        ctx = ActivePhaseGuard._actuation_context(
            adapter, power, believed_phases=None)
        assert ctx is not None and ctx[0] == 3
