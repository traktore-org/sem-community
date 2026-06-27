"""Per-brand status-enum classification (#548 generalised).

Each string here is taken from the brand's real HA integration source
(see docs/MULTI_CHARGER.md for citations). The classifier must map every
brand's statuses to the right control class — and must NOT fall for the
substring traps where an idle state contains the word "charging".
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.charger_adapters.status_enum import (
    classify_charger_status as C,
)


class TestWallbox:
    @pytest.mark.parametrize("s", ["Charging", "Discharging"])
    def test_charging(self, s): assert C(s) == "charging"
    @pytest.mark.parametrize("s", ["Paused", "Ready", "Waiting", "Disconnected", "Connected"])
    def test_not(self, s): assert C(s) == "not_charging"
    @pytest.mark.parametrize("s", ["Locked", "Scheduled", "Waiting in queue by Eco-Smart",
                                   "Waiting in queue by Power Sharing"])
    def test_locked(self, s): assert C(s) == "locked"


class TestEasee:
    def test_charging(self): assert C("charging") == "charging"
    @pytest.mark.parametrize("s", ["awaiting_start", "completed", "ready_to_charge",
                                   "stop_charging", "disconnected"])
    def test_not(self, s): assert C(s) == "not_charging"
    @pytest.mark.parametrize("s", ["awaiting_authorization", "awaiting_smart_start",
                                   "awaiting_scheduled_start", "authenticating"])
    def test_locked(self, s): assert C(s) == "locked"
    @pytest.mark.parametrize("s", ["error", "offline", "error_overcurrent"])
    def test_error_is_unknown(self, s): assert C(s) == "unknown"


class TestZaptec:
    def test_charging(self): assert C("connected_charging") == "charging"
    @pytest.mark.parametrize("s", ["connected_requesting", "connected_finished", "disconnected"])
    def test_not(self, s): assert C(s) == "not_charging"
    def test_unknown(self): assert C("unknown") == "unknown"


class TestGoE:
    def test_charging(self): assert C("charging") == "charging"
    @pytest.mark.parametrize("s", ["Charger ready, no vehicle", "Waiting for vehicle",
                                   "charging finished, vehicle still connected"])
    def test_not(self, s): assert C(s) == "not_charging"
    def test_finished_substring_trap(self):
        # contains "charging" but is NOT charging — exact match must win
        assert C("charging finished, vehicle still connected") == "not_charging"


class TestOhme:
    def test_charging(self): assert C("charging") == "charging"
    @pytest.mark.parametrize("s", ["plugged_in", "paused", "finished", "unplugged"])
    def test_not(self, s): assert C(s) == "not_charging"
    def test_locked(self): assert C("pending_approval") == "locked"


class TestOCPP:
    def test_charging(self): assert C("Charging") == "charging"
    @pytest.mark.parametrize("s", ["Available", "Preparing", "SuspendedEV",
                                   "SuspendedEVSE", "Suspended_EV", "Finishing", "Reserved"])
    def test_not(self, s): assert C(s) == "not_charging"
    def test_unavailable_is_unknown_collides_with_ha_offline(self):
        # OCPP "Unavailable" == HA's entity-offline state → power fallback.
        assert C("Unavailable") == "unknown"
    def test_faulted_unknown(self): assert C("Faulted") == "unknown"


class TestAlfen:
    @pytest.mark.parametrize("s", ["Charging Normal", "Charging Simplified",
                                   "Solar Charging", "Partial Solar Charging"])
    def test_charging(self, s): assert C(s) == "charging"
    @pytest.mark.parametrize("s", ["Available", "Cable connected", "EV Connected",
                                   "Not Charging", "Wait Vehicle Charging",
                                   "Preparing Charging", "Solar Charging Wait"])
    def test_not(self, s): assert C(s) == "not_charging"
    def test_locked(self): assert C("In Operative") == "locked"
    def test_substring_traps(self):
        # all contain "charging" but are NOT charging
        for s in ("Wait Vehicle Charging", "Preparing Charging", "Solar Charging Wait",
                  "Charging Non Charging"):
            assert C(s) == "not_charging", s


class TestGenericAndEdges:
    def test_binary(self):
        assert C("on") == "charging"
        assert C("off") == "not_charging"
    @pytest.mark.parametrize("s", [None, "", "  ", "unavailable", "unknown", "42", "7.5", "garbage"])
    def test_unknown_falls_back(self, s): assert C(s) == "unknown"
    def test_case_insensitive(self):
        assert C("CHARGING") == "charging"
        assert C("  Paused ") == "not_charging"

    def test_no_charging_collisions(self):
        # Nothing classified "charging" may also be a known idle/locked word.
        from custom_components.solar_energy_management.coordinator.charger_adapters import status_enum as se
        assert se._CHARGING.isdisjoint(se._NOT_CHARGING)
        assert se._CHARGING.isdisjoint(se._LOCKED)
        assert se._NOT_CHARGING.isdisjoint(se._LOCKED)
