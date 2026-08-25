"""#833 — the plug reader must not keep its own status vocabulary.

Reported in discussion #821: a Wallbox Commander 2 whose only cable-state
signal is ``sensor.wallbox_*_status_description`` read as **disconnected**
whenever the box sat at ``Paused`` (its normal idle) or ``Locked`` (its
must-unlock-first state), so SEM never started a session.

The cause was two lists answering one question. ``status_enum.py`` already
classified ``paused`` and ``locked`` as cable-present, while
``sensor_reader._read_binary_sensor`` carried a separate hardcoded tuple for
``ev_plug`` that had drifted from it and omitted both. Adding two strings to
the second list would have fixed this reporter and left the drift in place,
so the second list is deleted and plug detection derives from the shared
vocabulary instead.

Delegation is NOT the naive "anything that isn't disconnected is plugged"
from the issue text: ``_NOT_CHARGING`` deliberately mixes cable-present
states (``paused``, ``ready``, ``connected``) with cable-ABSENT ones
(``unplugged``, ``available``, ``charger ready, no vehicle``,
``waiting for vehicle``). Cable presence is its own axis, so it gets its own
explicitly-enumerated set.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)

PLUG = "sensor.wallbox_commander_2_sn_648249_status_description"


def _reader(value):
    hass = MagicMock()
    st = SimpleNamespace(state=str(value), attributes={})
    hass.states.get = lambda eid: st if eid == PLUG else None
    r = SensorReader(hass, {"ev_connected_sensor": PLUG})
    r._sign_vote_warmup = 0
    return r


def _plugged(value):
    return _reader(value)._read_binary_sensor(PLUG, "ev_plug")


def _charging(value):
    return _reader(value)._read_binary_sensor(PLUG, "ev_charging")


class TestTheReportedCase:
    """Wallbox Commander 2's full status vocabulary, as the reporter listed it."""

    @pytest.mark.parametrize("status", ["Paused", "Locked", "Ready", "Charging"])
    def test_cable_present_states_read_plugged(self, status):
        assert _plugged(status) is True, f"{status!r} means the cable is in"

    @pytest.mark.parametrize("status", ["Disconnected", "Unavailable"])
    def test_cable_absent_states_read_unplugged(self, status):
        assert _plugged(status) is False, f"{status!r} means no cable"


class TestNoRegression:
    """Every string the deleted hardcoded tuple accepted must still be plugged."""

    @pytest.mark.parametrize("status", [
        "connected", "ready_to_charge", "awaiting_start",
        "awaiting_authorization", "charging", "completed", "ready",
        "preparing", "suspended_ev", "suspended_evse", "finishing",
        "plugged in", "ev connected", "charging power on",
    ])
    def test_previously_accepted_strings_still_plugged(self, status):
        assert _plugged(status) is True


class TestCableAbsentIsNotPlugged:
    """The states delegation must NOT read as plugged — the reason cable
    presence is enumerated rather than inferred from 'not disconnected'."""

    @pytest.mark.parametrize("status", [
        "disconnected", "no car connected", "unplugged",
        "available",                    # OCPP: no EV connected
        "charger ready, no vehicle",    # go-e
        "waiting for vehicle",          # go-e
    ])
    def test_no_cable_states(self, status):
        assert _plugged(status) is False


class TestUnknownFallsThrough:
    def test_unrecognised_string_is_not_plugged(self):
        assert _plugged("Grumpelstiltskin") is False

    def test_numeric_fallback_survives(self):
        assert _plugged("1") is True
        assert _plugged("0") is False

    @pytest.mark.parametrize("status", ["on", "off", "unknown", "unavailable"])
    def test_binary_and_sentinel_states_unchanged(self, status):
        assert _plugged(status) is (status == "on")


class TestChargingReaderSharesTheVocabulary:
    """Same drift, one field over: the ev_charging list knew only 'charging'
    and 'charging power on', while the shared vocabulary already recognised
    every brand's charging strings."""

    @pytest.mark.parametrize("status", [
        "charging", "charging power on",         # were already accepted
        "discharging",                            # V2G
        "start_charging",                         # Easee
        "connected_charging",                     # Zaptec
        "charging normal", "charging simplified", # Alfen
        "solar charging", "partial solar charging",
    ])
    def test_charging_states(self, status):
        assert _charging(status) is True

    @pytest.mark.parametrize("status", ["paused", "ready", "connected", "disconnected"])
    def test_not_charging_states(self, status):
        assert _charging(status) is False


class TestTheListIsGone:
    """The ratchet: a future edit must not reintroduce a private vocabulary."""

    def test_no_hardcoded_status_tuple_in_the_reader(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import (
            sensor_reader as sr,
        )
        src = inspect.getsource(sr._read_binary_sensor
                                if hasattr(sr, "_read_binary_sensor")
                                else SensorReader._read_binary_sensor)
        for leaked in ("ready_to_charge", "suspended_evse", "awaiting_start"):
            assert leaked not in src, (
                f"_read_binary_sensor names {leaked!r} again — brand status "
                "strings belong in status_enum.py, which is the only place "
                "the two readers can agree"
            )
