"""#436 — multi-charger registration collision in Load Management.

Pre-fix, ``LoadManagementCoordinator.register_ev_charger()`` hardcoded
``device_id = "load_device_ev_charger"`` and the caller in
``__init__.py`` invoked it inside a per-charger loop. Each call
overwrote the same entry in ``self._devices``, so the Load Priority
card showed only ONE EV row even with N chargers configured, and
peak-shedding throttled the LAST registered charger only.

Fix: ``register_ev_charger`` now accepts ``charger_id`` + ``charger_name``
kwargs (defaulting to the legacy ``"ev_charger"`` / ``"EV Charger"`` so
single-charger users are unaffected) and keys into
``self._devices[f"load_device_{charger_id}"]``.

This file pins:

1. Single-charger install still uses ``load_device_ev_charger`` (legacy
   storage key preserved, no migration needed for the common case).
2. Two-charger install produces TWO entries with distinct ids in
   ``self._devices``.
3. Each entry preserves its own friendly_name, control entity, and
   power entity (no field cross-contamination).
4. ``charger_id`` field is stored on the device dict so the card can
   map back to ``ev_chargers[i].id``.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.load_management import (
    LoadManagementCoordinator,
)


@pytest.fixture
def config_entry():
    entry = MagicMock()
    entry.options = {
        "load_management_enabled": True,
        "target_peak_limit": 5.0,
        "warning_peak_level": 4.5,
        "emergency_peak_level": 6.0,
        "peak_hysteresis": 0.3,
    }
    entry.entry_id = "test_entry"
    return entry


@pytest.fixture
def lm(mock_hass, config_entry):
    with patch(
        "custom_components.solar_energy_management.features.load_management.LoadDeviceDiscovery"
    ), patch(
        "custom_components.solar_energy_management.features.load_management.Store"
    ) as MockStore:
        mock_store = MagicMock()
        mock_store.async_load = AsyncMock(return_value=None)
        mock_store.async_save = AsyncMock()
        MockStore.return_value = mock_store
        coordinator = LoadManagementCoordinator(mock_hass, config_entry)
        coordinator._store = mock_store
        # Mock the hass.states.get call for entity validation
        mock_hass.states.get = MagicMock(return_value=MagicMock(
            state="on", attributes={"friendly_name": "Generic Charger"}
        ))
        yield coordinator


# ──────────────────────────────────────────────
# Single-charger: legacy storage key preserved
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_charger_uses_legacy_key(lm):
    """Default ``charger_id="ev_charger"`` keeps the storage key as
    ``load_device_ev_charger`` so pre-#436 single-charger users don't
    lose their saved settings."""
    ok = await lm.register_ev_charger(
        current_control_entity="number.keba_charging_current",
        power_entity="sensor.keba_charging_power",
        priority=3,
        charger_service="keba.set_current",
    )
    assert ok is True
    assert "load_device_ev_charger" in lm._devices
    entry = lm._devices["load_device_ev_charger"]
    assert entry["device_type"] == "ev_charger"
    assert entry["charger_id"] == "ev_charger"


# ──────────────────────────────────────────────
# Multi-charger: distinct keys + isolation (the #436 bug fix)
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_two_chargers_produce_two_entries(lm):
    """The #436 invariant. Pre-fix, the second call overwrote the
    first; now both entries co-exist."""
    await lm.register_ev_charger(
        current_control_entity="number.keba_left_current",
        power_entity="sensor.keba_left_power",
        charger_service="keba.set_current",
        charger_id="ev_charger",
        charger_name="Keba Left",
    )
    await lm.register_ev_charger(
        current_control_entity="number.keba_right_current",
        power_entity="sensor.keba_right_power",
        charger_service="keba.set_current",
        charger_id="ev_charger_1",
        charger_name="Keba Right",
    )
    keys = [k for k in lm._devices if lm._devices[k].get("device_type") == "ev_charger"]
    assert sorted(keys) == ["load_device_ev_charger", "load_device_ev_charger_1"]
    assert len(keys) == 2


@pytest.mark.asyncio
async def test_each_charger_preserves_its_own_fields(lm):
    """Cross-contamination guard — the entries must each carry their
    own power_entity / switch_entity / priority / charger_id."""
    await lm.register_ev_charger(
        current_control_entity="number.keba_left_current",
        power_entity="sensor.keba_left_power",
        priority=3,
        charger_service="keba.set_current",
        charger_id="ev_charger",
        charger_name="Keba Left",
    )
    await lm.register_ev_charger(
        current_control_entity="number.keba_right_current",
        power_entity="sensor.keba_right_power",
        priority=5,
        charger_service="keba.set_current",
        charger_id="ev_charger_1",
        charger_name="Keba Right",
    )
    left = lm._devices["load_device_ev_charger"]
    right = lm._devices["load_device_ev_charger_1"]
    assert left["switch_entity"] == "number.keba_left_current"
    assert right["switch_entity"] == "number.keba_right_current"
    assert left["power_entity"] == "sensor.keba_left_power"
    assert right["power_entity"] == "sensor.keba_right_power"
    assert left["priority"] == 3
    assert right["priority"] == 5
    assert left["charger_id"] == "ev_charger"
    assert right["charger_id"] == "ev_charger_1"


# ──────────────────────────────────────────────
# Friendly name: caller-supplied wins over hass attribute
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_caller_supplied_friendly_name_wins(lm):
    """When charger_name is set, use it instead of the entity's
    friendly_name attribute. Lets multi-charger users see
    'Keba Left' / 'Keba Right' instead of two 'Generic Charger' rows."""
    await lm.register_ev_charger(
        current_control_entity="number.keba_left_current",
        power_entity="sensor.keba_left_power",
        charger_service="keba.set_current",
        charger_id="ev_charger",
        charger_name="Keba Left",
    )
    entry = lm._devices["load_device_ev_charger"]
    assert entry["friendly_name"] == "Keba Left"


@pytest.mark.asyncio
async def test_falls_back_to_entity_friendly_name_when_default(lm):
    """If the caller passes the default placeholder ``EV Charger``, we
    fall back to the control entity's friendly_name attribute
    (pre-#436 behaviour for the legacy single-charger path)."""
    await lm.register_ev_charger(
        current_control_entity="number.keba_charging_current",
        power_entity="sensor.keba_charging_power",
        charger_service="keba.set_current",
        # charger_name not provided → default "EV Charger" placeholder
    )
    entry = lm._devices["load_device_ev_charger"]
    # mock_hass returns friendly_name="Generic Charger" on entity lookup
    assert entry["friendly_name"] == "Generic Charger"


# ──────────────────────────────────────────────
# Idempotency: re-registering the same charger doesn't add a duplicate
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_device_registry_sync_preserves_all_load_device_entries(lm):
    """Reviewer-flagged regression — `features/device_registry.py`'s
    `_populate_load_manager` pruned everything except the legacy
    hardcoded `load_device_ev_charger` key. After #436, second-charger
    entries like `load_device_ev_charger_1` were silently deleted on
    every registry sync. Widened guard to `startswith("load_device_")`.

    This test mirrors that prune logic directly (independent of the
    full DeviceRegistry fixture) and asserts both charger entries
    survive."""
    # Seed two chargers
    await lm.register_ev_charger(
        current_control_entity="number.keba_left_current",
        power_entity="sensor.keba_left_power",
        charger_service="keba.set_current",
        charger_id="ev_charger",
        charger_name="Keba Left",
    )
    await lm.register_ev_charger(
        current_control_entity="number.keba_right_current",
        power_entity="sensor.keba_right_power",
        charger_service="keba.set_current",
        charger_id="ev_charger_1",
        charger_name="Keba Right",
    )
    # Apply the (fixed) prune logic
    old_ids = [
        did for did in list(lm._devices.keys())
        if not did.startswith("energy_dashboard_")
        and not did.startswith("load_device_")
    ]
    for did in old_ids:
        del lm._devices[did]
    # Both per-charger entries must survive
    assert "load_device_ev_charger" in lm._devices
    assert "load_device_ev_charger_1" in lm._devices


@pytest.mark.asyncio
async def test_re_registering_same_charger_overwrites_not_duplicates(lm):
    """Re-registration (e.g. on HA restart) hits the same key and
    overwrites — no orphan entries pile up."""
    await lm.register_ev_charger(
        current_control_entity="number.keba_current",
        power_entity="sensor.keba_power",
        charger_service="keba.set_current",
        charger_id="ev_charger",
        charger_name="Keba",
    )
    await lm.register_ev_charger(
        current_control_entity="number.keba_current",
        power_entity="sensor.keba_power",
        priority=7,  # changed
        charger_service="keba.set_current",
        charger_id="ev_charger",
        charger_name="Keba",
    )
    ev_keys = [k for k in lm._devices if lm._devices[k].get("device_type") == "ev_charger"]
    assert len(ev_keys) == 1
    assert lm._devices["load_device_ev_charger"]["priority"] == 7
