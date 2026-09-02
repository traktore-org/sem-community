"""#895 — the #805 consent default has to reach the shedder, not just the
surplus side.

#805 made "a device SEM discovered by itself may do nothing until the user
says so" the rule (``DEFAULT_DISCOVERED_CONTROL_MODE = "off"``). It was
applied where the surplus controller builds its device — and nowhere else.
``_sync_to_load_manager`` and the card payload kept their own literal
``"peak_only"`` fallback, so on a first install every auto-discovered
device entered load management shed-eligible. Forum post #30 (ericdm): a
Span panel's per-circuit switches and a backup battery's output were
discovered, and emergency shedding switched the house off circuit by
circuit — including the one feeding the router and HA itself.

One resolver, three readers: the surplus sync, the load-manager sync and
the card payload must answer "what may this discovered device do?" from
the same place, so a default can never again reach one and miss another.
"""
from __future__ import annotations

import re
import inspect
from unittest.mock import MagicMock

from custom_components.solar_energy_management.features import device_registry as dr
from custom_components.solar_energy_management.features.device_axes import may_actuate
from custom_components.solar_energy_management.features.device_registry import (
    DEFAULT_DISCOVERED_CONTROL_MODE, UnifiedDevice, UnifiedDeviceRegistry,
)

SWITCH_CONTROL = {"type": "switch", "entity": "switch.span_kitchen"}


def _registry(overrides=None):
    reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
    reg.hass = MagicMock()
    reg.hass.states.get.return_value = None
    reg._surplus_controller = MagicMock()
    reg._surplus_controller.get_device.return_value = None
    reg._service_registrations = {}
    reg._control_mode_overrides = dict(overrides or {})
    reg._dependency_overrides = {}
    reg._device_goals = {}
    reg._critical_overrides = {}
    reg._controllable_overrides = {}
    reg._rated_power_overrides = {}
    reg._priority_overrides = {}
    reg._manual_mappings = {}
    reg._has_battery = False
    reg._ev_charger_rows = []
    reg._discovery = None
    reg._load_manager = MagicMock()
    reg._load_manager._devices = {}
    reg._devices = [
        UnifiedDevice(
            energy_sensor="sensor.span_kitchen_energy",
            power_sensor="sensor.span_kitchen_power",
            name="Kitchen circuit",
            priority=5,
            control=SWITCH_CONTROL,
        )
    ]
    reg._get_power_rating = MagicMock(return_value=1.0)
    reg._rated_power_for = MagicMock(return_value=1000.0)
    reg._configured_charger_entities = MagicMock(return_value=set())
    reg._direct_registration_entities = MagicMock(return_value=set())
    reg._is_charger_duplicate = MagicMock(return_value=False)
    return reg


DID = "energy_dashboard_span_kitchen"


class TestTheLoadManagerRowCarriesTheConsentDefault:

    def test_a_discovered_device_with_no_choice_is_not_shed_eligible(self):
        reg = _registry()
        reg._sync_to_load_manager()
        row = reg._load_manager._devices[DID]
        assert row["control_mode"] == DEFAULT_DISCOVERED_CONTROL_MODE, (
            "discovery is a suggestion, not consent (#805) — the shedder "
            "must see the same default the surplus side does"
        )
        assert may_actuate(row) is False, (
            "a device nobody opted in must not be on the shed list — this "
            "is how ericdm's house went dark (forum #30)"
        )

    def test_the_users_choice_still_wins(self):
        reg = _registry({DID: "peak_only"})
        reg._sync_to_load_manager()
        row = reg._load_manager._devices[DID]
        assert row["control_mode"] == "peak_only"
        assert may_actuate(row) is True


class TestTheCardPayloadAgrees:

    def test_the_card_shows_the_same_default_the_shedder_uses(self):
        reg = _registry()
        reg._sync_to_load_manager()
        payload = reg.get_devices_for_sensor()
        assert payload[DID]["control_mode"] == DEFAULT_DISCOVERED_CONTROL_MODE
        assert (payload[DID]["control_mode"]
                == reg._load_manager._devices[DID]["control_mode"])


class TestThereIsOneResolver:
    """A default that lives in three literals reaches one reader and misses
    two — that is the whole bug. Pin the shape, not just the value."""

    def test_no_reader_carries_its_own_fallback_literal(self):
        src = inspect.getsource(dr)
        stray = re.findall(
            r'_control_mode_overrides\.get\([^)]*,\s*"[a-z_]+"\)', src)
        assert stray == [], (
            f"a private fallback beside the resolver: {stray} — read the "
            "mode through UnifiedDeviceRegistry.control_mode_for()"
        )

    def test_the_resolver_defaults_to_the_consent_constant(self):
        reg = _registry()
        assert reg.control_mode_for(DID) == DEFAULT_DISCOVERED_CONTROL_MODE
        reg._control_mode_overrides[DID] = "surplus"
        assert reg.control_mode_for(DID) == "surplus"
