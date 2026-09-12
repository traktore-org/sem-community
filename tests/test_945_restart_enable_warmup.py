"""#945 — a restart is not a fault. Bug class 86.

alexmc1510 restarted Home Assistant on 2.1.0-beta.14 and was told, within
about half a minute, that

    "SEM's last 3+ current commands to EV Charger were rejected: enable
     switch unavailable/locked — cannot start charging. The charger is NOT
     under SEM control right now…"

No current command had been sent. The charger was fine. What SEM had
actually observed was ``hass.states.get("switch.…") is None`` — which is
what EVERY entity looks like while its integration is still loading.

The surface for "the enable switch cannot be driven" (#536/#548) borrowed
``CurrentControlDevice._record_actuation_failure``, the counter built for
commands that RAISED (#462). That counter's threshold is three CYCLES, so
at the default 10 s interval SEM filed a persistent ERROR Repair 30 seconds
into every restart. Every other entity-absence Repair in SEM waits out
``UNAVAILABLE_REPAIR_THRESHOLD_S`` of wall clock for exactly this reason
(#611: "a restart's warm-up window must not cry wolf"), and #824 already
applies that hold to this very entity.

These tests pin both halves: silence is held on the wall clock, and
evidence keeps its own contract untouched.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator import (
    repair_issues as ri,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (  # noqa: E501
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_adapters import (
    GenericAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    observe,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.devices.base import (
    CurrentControlDevice,
)

#: The one constant, never a fresh literal (class 46).
HOLD = ri.UNAVAILABLE_REPAIR_THRESHOLD_S
CYCLE = 10.0  # DEFAULT_UPDATE_INTERVAL — what "three cycles" was worth


def _device(**kwargs) -> CurrentControlDevice:
    hass = MagicMock()
    defaults = dict(
        hass=hass,
        device_id="ev_charger_1",
        name="EV Charger",
        min_current=6.0,
        max_current=32.0,
        phases=3,
    )
    defaults.update(kwargs)
    dev = CurrentControlDevice(**defaults)
    dev.start_stop_entity = "switch.cargador_coche_carga_de_ve"
    return dev


@pytest.mark.unit
class TestTheRestartWindowIsSilent:
    """The reporter's own half-minute."""

    def test_thirty_seconds_of_a_missing_switch_raises_nothing(self):
        dev = _device()
        with patch.object(ri, "raise_charger_actuation_failed") as raised:
            for cycle in range(6):  # 0–50 s: twice what the old bug needed
                assert dev._note_enable_blocked(now=cycle * CYCLE) is False
            raised.assert_not_called()

    def test_a_non_command_never_spends_the_command_counter(self):
        """The vacuity twin of the whole fix: an observation that no command
        was possible must not look like three rejected commands."""
        dev = _device()
        with patch.object(ri, "raise_charger_actuation_failed"):
            for cycle in range(6):
                dev._note_enable_blocked(now=cycle * CYCLE)
        assert dev._actuation_failures == 0, (
            "silence was counted as a rejected command — the #945 shape"
        )

    def test_past_the_hold_it_raises_exactly_once(self):
        dev = _device()
        with patch.object(ri, "raise_charger_actuation_failed") as raised:
            assert dev._note_enable_blocked(now=0.0) is False
            assert dev._note_enable_blocked(now=HOLD - 1.0) is False
            raised.assert_not_called()
            assert dev._note_enable_blocked(now=HOLD + 1.0) is True
            raised.assert_called_once()
            # It persists; it does not re-file every cycle afterwards.
            for extra in (2.0, 12.0, 22.0):
                assert dev._note_enable_blocked(now=HOLD + extra) is True
            raised.assert_called_once()

    def test_a_switch_that_answers_restarts_the_window(self):
        """A blip must not accumulate towards the threshold across gaps."""
        dev = _device()
        with patch.object(ri, "raise_charger_actuation_failed") as raised, \
                patch.object(ri, "clear_charger_actuation_failed"):
            dev._note_enable_blocked(now=0.0)
            dev._note_enable_blocked(now=HOLD - 10.0)
            dev._note_enable_controllable()          # it answered
            dev._note_enable_blocked(now=HOLD)       # fresh window opens here
            assert dev._note_enable_blocked(now=2 * HOLD - 10.0) is False
            raised.assert_not_called()
            assert dev._note_enable_blocked(now=2 * HOLD + 1.0) is True


@pytest.mark.unit
class TestRecovery:

    def test_the_switch_answering_retires_the_repair_this_path_raised(self):
        dev = _device()
        with patch.object(ri, "raise_charger_actuation_failed"), \
                patch.object(ri, "clear_charger_actuation_failed") as cleared:
            dev._note_enable_blocked(now=0.0)
            assert dev._note_enable_blocked(now=HOLD + 1.0) is True
            dev._note_enable_controllable()
            cleared.assert_called_once_with(dev.hass, "ev_charger_1")
        assert dev._enable_blocked_repair_raised is False
        assert dev._actuation_repair_raised is False

    def test_a_write_raised_repair_survives_the_switch_recovering(self):
        """The two conditions share ONE issue id. Three rejected WRITES are
        harder evidence than a silent switch, so a switch coming back must
        not delete the #462 Repair the write side raised."""
        dev = _device()
        with patch.object(ri, "raise_charger_actuation_failed") as raised, \
                patch.object(ri, "clear_charger_actuation_failed") as cleared:
            for _ in range(3):
                dev._record_actuation_failure(RuntimeError("schema rejected"))
            raised.assert_called_once()
            dev._note_enable_controllable()
            cleared.assert_not_called()
        assert dev._actuation_repair_raised is True

    def test_a_fresh_lifetime_retires_a_predecessors_repair_once(self):
        """Class 84. The memo dies with the restart; the persistent Repair
        does not. A device that comes back to a healthy switch must retire
        what its predecessor raised, though it never raised anything itself
        — otherwise the restart that FIXES the switch is the one run that
        cannot clear the notice."""
        dev = _device()
        with patch.object(ri, "clear_charger_actuation_failed") as cleared:
            dev._note_enable_controllable()
            cleared.assert_called_once_with(dev.hass, "ev_charger_1")
            dev._note_enable_controllable()
            cleared.assert_called_once()  # once per lifetime, not per cycle

    def test_a_good_write_retires_the_warm_up_clock_too(self):
        dev = _device()
        with patch.object(ri, "raise_charger_actuation_failed"), \
                patch.object(ri, "clear_charger_actuation_failed"):
            dev._note_enable_blocked(now=0.0)
            assert dev._enable_blocked_since is not None
            dev._clear_actuation_failure()
        assert dev._enable_blocked_since is None


@pytest.mark.unit
class TestTheCommandCounterKeepsItsContract:
    """#462 is framework-tier: a command that RAISED is real evidence and
    keeps its three-strike threshold, with no wall clock at all."""

    def test_three_rejected_writes_still_raise_immediately(self):
        dev = _device()
        with patch.object(ri, "raise_charger_actuation_failed") as raised:
            dev._record_actuation_failure(RuntimeError("boom"))
            dev._record_actuation_failure(RuntimeError("boom"))
            raised.assert_not_called()
            dev._record_actuation_failure(RuntimeError("boom"))
            raised.assert_called_once()


@pytest.mark.unit
class TestTheAdapterHook:
    """End-to-end through the REAL adapter hook the reconciler calls."""

    @pytest.mark.asyncio
    async def test_the_hook_holds_through_the_warm_up_then_surfaces(self):
        dev = _device()
        adapter = GenericAdapter(dev)
        with patch.object(ri, "raise_charger_actuation_failed") as raised:
            await adapter.report_enable_blocked()
            raised.assert_not_called()
            assert dev._enable_blocked_since is not None, (
                "the hook never started the clock, so it can never surface"
            )
            # …and once the block has outlasted a restart's warm-up:
            dev._enable_blocked_since -= (HOLD + 1.0)
            await adapter.report_enable_blocked()
            raised.assert_called_once()
            assert dev._actuation_failures == 0


@pytest.mark.unit
class TestTheOtherHalfOfTheClock:
    """The reset has to live where the HEALTHY answer is computed every
    cycle. On the failure path it could never fire — that path only runs
    while the switch is unreadable."""

    @staticmethod
    def _adapter_for(dev, enable):
        adapter = MagicMock()
        adapter._device = dev
        adapter.enable_state = lambda: enable
        adapter.actual_charging = MagicMock(return_value=False)
        adapter.is_self_charging = MagicMock(return_value=False)
        return adapter

    def test_observe_retires_the_hold_when_the_switch_answers(self):
        dev = _device()
        power = SimpleNamespace(power_w=0.0, connected=True)
        with patch.object(ri, "raise_charger_actuation_failed"), \
                patch.object(ri, "clear_charger_actuation_failed") as cleared:
            dev._note_enable_blocked(now=0.0)
            assert dev._note_enable_blocked(now=HOLD + 1.0) is True
            out = observe(self._adapter_for(dev, (True, True)), power)
            assert out.enable_controllable is True
            cleared.assert_called_once()
        assert dev._enable_blocked_since is None

    def test_observe_leaves_the_hold_alone_while_it_is_still_blocked(self):
        """The twin: if observe() retired the clock unconditionally, the
        threshold could never be reached and the Repair would be dead."""
        dev = _device()
        power = SimpleNamespace(power_w=0.0, connected=True)
        with patch.object(ri, "clear_charger_actuation_failed") as cleared:
            dev._note_enable_blocked(now=0.0)
            out = observe(self._adapter_for(dev, (None, False)), power)
            assert out.enable_controllable is False
            cleared.assert_not_called()
        assert dev._enable_blocked_since is not None


# ── Sibling sweep: the same shape on the battery write verifier (#915) ────


def _hass(state=None):
    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.get = MagicMock(return_value=state)
    return hass


def _state(value, unit="W", **attrs):
    return SimpleNamespace(state=str(value),
                           attributes={"unit_of_measurement": unit, **attrs})


def _battery_adapter(hass):
    return GenericBatteryAdapter(hass, {
        "battery_discharge_control_entity": "number.limit",
    })


def _strikes_out(ad, hass):
    """An adapter that has really produced a not-reflected verdict and is at
    the Repair threshold, plus an owner double of the shape the #915 tests
    drive this method with.

    The verdict has to be REAL: ``_raise_or_clear_battery_write_repair``
    needs ``last_unverified_entity``, so an adapter that was never asked to
    judge a write makes every assertion here pass vacuously (class 8).
    """
    ad._note_pending_write("number.limit", 1200.0)
    with patch("time.monotonic", return_value=1e9):
        assert ad.verify_pending_write() is False
    assert ad.last_unverified_entity == "number.limit"
    ad.write_not_taken_strikes = SEMCoordinator.BATTERY_WRITE_STRIKES
    return SimpleNamespace(
        hass=hass,
        BATTERY_WRITE_STRIKES=SEMCoordinator.BATTERY_WRITE_STRIKES,
    )


@pytest.mark.unit
class TestABatteryEntityThatSaidNothing:
    """#915 counts three writes the register CONTRADICTED, and reports a
    vanished entity as "reads missing" — that verdict is deliberate (it is
    the evidence the Repair shows the owner) and stays. What must not happen
    is the ERROR Repair landing three cycles into a restart, while the
    battery's own integration is still loading."""

    def test_the_adapters_missing_verdict_is_unchanged(self):
        """The #915 pin this sweep must not break."""
        ad = _battery_adapter(_hass(None))
        ad._note_pending_write("number.limit", 1200.0)
        with patch("time.monotonic", return_value=1e9):
            assert ad.verify_pending_write() is False
        assert ad.last_unverified_seen == "missing"

    def test_silence_files_no_repair_inside_the_warm_up(self):
        ad = _battery_adapter(_hass(None))
        owner = _strikes_out(ad, _hass(None))
        with patch.object(ri, "raise_battery_control_write_not_taken") as raised:
            with patch("time.monotonic", return_value=1000.0):
                SEMCoordinator._raise_or_clear_battery_write_repair(
                    owner, ad, False)
            raised.assert_not_called()

    def test_silence_that_outlasts_the_warm_up_does_file(self):
        ad = _battery_adapter(_hass(None))
        owner = _strikes_out(ad, _hass(None))
        with patch.object(ri, "raise_battery_control_write_not_taken") as raised:
            with patch("time.monotonic", return_value=1000.0):
                SEMCoordinator._raise_or_clear_battery_write_repair(
                    owner, ad, False)
            raised.assert_not_called()
            with patch("time.monotonic", return_value=1000.0 + HOLD + 1.0):
                SEMCoordinator._raise_or_clear_battery_write_repair(
                    owner, ad, False)
            raised.assert_called_once()

    def test_a_register_that_contradicted_the_write_files_at_once(self):
        """The evidence twin: a live entity answering with the WRONG number
        is not silence, and must keep #915's original speed."""
        ad = _battery_adapter(_hass(_state(5000)))
        ad._note_pending_write("number.limit", 1200.0)
        with patch("time.monotonic", return_value=1e9):
            assert ad.verify_pending_write() is False
        assert ad.write_not_taken_strikes == 1
        owner = _strikes_out(ad, _hass(_state(5000)))
        with patch.object(ri, "raise_battery_control_write_not_taken") as raised:
            SEMCoordinator._raise_or_clear_battery_write_repair(
                owner, ad, False)
            raised.assert_called_once()
